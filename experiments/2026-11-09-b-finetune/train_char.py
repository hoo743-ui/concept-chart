# -*- coding: utf-8 -*-
"""B(같은 개념인가) 글자 단위 작은 모델을 처음부터 학습한다. 사전학습 모델을 쓰지 않는다. 시험 세트는 불러오지 않는다.

    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/train_char.py overfit     작은 묶음 외우기 (버그 점검)
    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/train_char.py train       cnn·bilstm 각각 시드 3개. 끝난 것은 건너뛴다

구조: 소문자·NFD(한글을 자모로 분해) 글자 → 작은 CNN 또는 BiLSTM → (u, v, |u-v|, u*v) → 분류 층. 데이터는 파인튜닝 r2-v2와 같다.

자원 상한 (사용자 결정 11-09: 메모리·컴퓨터 성능을 과하게 쓰면 안 된다)
- 한 번에 프로세스 1개, CPU 스레드 2개, 낮은 우선순위, GPU 메모리는 전체의 30%까지
- 사용 가능 RAM이 2GB 아래로 20초 이어지면 스스로 멈춘다. 다시 실행하면 끝난 시드는 건너뛴다
- 끝나면 파일 크기·CPU 속도·최대 RAM·GPU를 metrics.json에 남긴다
"""
import argparse
import csv
import ctypes
import hashlib
import json
import os
import pathlib
import random
import subprocess
import sys
import threading
import time
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(HERE.parent))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from common import PAIRS, best_threshold, load_pairs, load_split, metrics, part, write_live  # noqa: E402

ARCHES = ("cnn", "bilstm")
SEEDS = (42, 1, 2)
CFG = dict(max_epochs=20, patience=4, min_delta=0.001, lr=1e-3, weight_decay=0.01, batch=32, clip=1.0, max_len=48, emb=48, hidden=96, dropout=0.1)
MIN_RAM_GB, CPU_THREADS, GPU_FRACTION = 2.0, 2, 0.3
EXTRA = ROOT / "data" / "processed" / "B_extra_r2-dev-v2.jsonl"
TAG = ""
RUN_LOG = HERE / "char_run.log"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def log(*a):
    line = " ".join([time.strftime("[%H:%M:%S]"), *map(str, a)])
    print(line, flush=True)
    with open(RUN_LOG, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


class MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong), ("total_virt", ctypes.c_ulonglong), ("avail_virt", ctypes.c_ulonglong), ("avail_ext", ctypes.c_ulonglong)]


class ProcMem(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong), ("peak_ws", ctypes.c_size_t), ("ws", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("page", ctypes.c_size_t), ("peak_page", ctypes.c_size_t)]


def avail_ram_gb():
    m = MemStatus()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.avail_phys / 1e9


def peak_ram_gb():
    m = ProcMem()
    m.cb = ctypes.sizeof(m)
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(k.GetCurrentProcess()), ctypes.byref(m), m.cb)
    return round(m.peak_ws / 1e9, 2)


def guard():
    low = 0
    while True:
        low = low + 1 if avail_ram_gb() < MIN_RAM_GB else 0
        if low >= 2:
            log(f"사용 가능 RAM {avail_ram_gb():.1f}GB, 상한에 걸려 멈춤. 다시 실행하면 끝난 시드는 건너뛴다")
            os._exit(3)
        time.sleep(10)


def limit_resources():
    torch.set_num_threads(CPU_THREADS)
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass(ctypes.c_void_p(k.GetCurrentProcess()), 0x00004000)     # 보통 이하
    if DEVICE == "cuda":
        torch.cuda.set_per_process_memory_fraction(GPU_FRACTION)
    threading.Thread(target=guard, daemon=True).start()


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def chars(s):
    return unicodedata.normalize("NFD", s.lower())[:CFG["max_len"]]


def make_vocab(rows):
    return {c: i + 2 for i, c in enumerate(sorted({c for r in rows for x in (r["a"], r["b"]) for c in chars(x)}))}     # 0 채움, 1 처음 보는 글자


def encode(texts, vocab, device):
    seqs = [[vocab.get(c, 1) for c in chars(t)] or [1] for t in texts]
    n = max(4, max(map(len, seqs)))                                                                                     # CNN 창(4)보다 짧으면 안 된다
    ids = torch.zeros(len(seqs), n, dtype=torch.long)
    for i, s in enumerate(seqs):
        ids[i, :len(s)] = torch.tensor(s)
    return ids.to(device), torch.tensor([len(s) for s in seqs])


class CharNet(torch.nn.Module):
    def __init__(self, arch, n_vocab):
        super().__init__()
        self.arch = arch
        e, h = CFG["emb"], CFG["hidden"]
        self.emb = torch.nn.Embedding(n_vocab, e, padding_idx=0)
        if arch == "cnn":
            self.convs = torch.nn.ModuleList(torch.nn.Conv1d(e, h, k) for k in (2, 3, 4))
            d = h * 3
        else:
            self.lstm = torch.nn.LSTM(e, h, batch_first=True, bidirectional=True)
            d = h * 2
        self.head = torch.nn.Sequential(torch.nn.Linear(d * 4, 128), torch.nn.ReLU(), torch.nn.Dropout(CFG["dropout"]), torch.nn.Linear(128, 1))

    def embed(self, ids, lens):
        x = self.emb(ids)
        if self.arch == "cnn":
            x = x.transpose(1, 2)
            return torch.cat([torch.relu(c(x)).max(2).values for c in self.convs], 1)
        p = torch.nn.utils.rnn.pack_padded_sequence(x, lens.cpu(), batch_first=True, enforce_sorted=False)
        _, (h, _) = self.lstm(p)
        return torch.cat([h[0], h[1]], 1)

    def forward(self, a, b):
        u, v = self.embed(*a), self.embed(*b)
        return self.head(torch.cat([u, v, (u - v).abs(), u * v], 1)).squeeze(1)


def batches(rows, size, rng=None):
    idx = list(range(len(rows)))
    if rng:
        rng.shuffle(idx)
    for i in range(0, len(idx), size):
        yield [rows[j] for j in idx[i:i + size]]


def logits(net, b, vocab, device):
    return net(encode([r["a"] for r in b], vocab, device), encode([r["b"] for r in b], vocab, device))


@torch.no_grad()
def predict(net, rows, vocab, device):
    net.eval()
    out, total = [], 0.0
    bce = torch.nn.BCEWithLogitsLoss(reduction="sum")
    for b in batches(rows, 128):
        lg = logits(net, b, vocab, device)
        total += bce(lg, torch.tensor([float(r["label"]) for r in b], device=device)).item()
        out += torch.sigmoid(lg).cpu().tolist()
    return out, total / len(rows)


def step(net, b, vocab, bce, opt):
    lg = logits(net, b, vocab, DEVICE)
    net.last_logit = lg.detach()                         # 실시간 화면용 기록. 학습에는 쓰지 않는다
    loss = bce(lg, torch.tensor([float(r["label"]) for r in b], device=DEVICE))
    opt.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(net.parameters(), CFG["clip"])
    opt.step()
    return loss.item()


def data():
    rows, split = load_pairs(), load_split()
    return part(rows, split["train"]) + load_pairs(EXTRA), part(rows, split["val"])     # 시험 세트는 여기서 꺼내지 않는다


def cmd_overfit():
    tr, _ = data()
    for arch in ARCHES:
        set_seed(42)
        rng = random.Random(0)
        small = rng.sample([r for r in tr if r["label"] == 1], 16) + rng.sample([r for r in tr if r["label"] == 0], 16)
        vocab = make_vocab(small)
        net = CharNet(arch, len(vocab) + 2).to(DEVICE)
        opt = torch.optim.AdamW(net.parameters(), lr=2e-3)
        bce = torch.nn.BCEWithLogitsLoss()
        net.train()
        for _ in range(150):
            ls = [step(net, b, vocab, bce, opt) for b in batches(small, 16, rng)]
        cur = sum(ls) / len(ls)
        log(arch, f"외우기 끝 손실 {cur:.4f}", "통과" if cur < 0.05 else "실패", f"최대 RAM {peak_ram_gb()}GB")


def train_one(arch, seed, tr, va, sha):
    tag = f"char-{TAG}{arch}-seed{seed}"
    run = HERE / tag
    if (run / "metrics.json").exists() and json.loads((run / "config.json").read_text(encoding="utf-8")).get("extra_sha256") == sha:
        log(tag, "이미 끝남, 건너뜀")
        return
    (run / "metrics.json").unlink(missing_ok=True)
    run.mkdir(exist_ok=True)
    set_seed(seed)
    rng = random.Random(seed)
    vocab = make_vocab(tr)
    net = CharNet(arch, len(vocab) + 2).to(DEVICE)
    params = sum(p.numel() for p in net.parameters())
    best_path = ROOT / "models" / f"b-{tag}-best.pt"
    best_path.parent.mkdir(exist_ok=True)
    opt = torch.optim.AdamW(net.parameters(), lr=CFG["lr"], weight_decay=CFG["weight_decay"])
    bce = torch.nn.BCEWithLogitsLoss()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    (run / "config.json").write_text(json.dumps({"arch": arch, "seed": seed, **CFG, "git": commit, "data_sha256": hashlib.sha256(PAIRS.read_bytes()).hexdigest(), "extra_sha256": sha, "train_pairs": len(tr),
                                                 "vocab": len(vocab), "params": params, "split": "experiments/splits/B.json", "device": DEVICE, "torch": torch.__version__, "cpu_threads": CPU_THREADS}, ensure_ascii=False, indent=1), encoding="utf-8")
    best, bad, best_epoch, t_start = -1.0, 0, 0, time.time()
    with open(run / "log.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "train_loss", "val_loss", "val_ap", "val_auc", "val_hard_fp", "val_cross_recall", "sec"])
        for ep in range(1, CFG["max_epochs"] + 1):
            t0 = time.time()
            net.train()
            ls, total = [], len(tr) // CFG["batch"] + 1
            for b in batches(tr, CFG["batch"], rng):
                ls.append(step(net, b, vocab, bce, opt))
                if len(ls) % 50 == 0:
                    p = torch.sigmoid(net.last_logit).tolist()
                    write_live(run=tag, epoch=ep, max_epochs=CFG["max_epochs"], step=len(ls), total=total, loss=sum(ls[-50:]) / 50, time=time.time(),
                               sample=[{"a": r["a"], "b": r["b"], "label": r["label"], "p": round(x, 3)} for r, x in list(zip(b, p))[:6]])
            s, val_loss = predict(net, va, vocab, DEVICE)
            m = metrics(va, s, best_threshold(s, [r["label"] for r in va]))
            w.writerow([ep, round(sum(ls) / len(ls), 4), round(val_loss, 4), round(m["ap"], 4), round(m["auc"], 4), round(m["hard_fp"], 4), round(m["cross_recall"], 4), round(time.time() - t0, 1)])
            f.flush()
            if m["ap"] > best + CFG["min_delta"]:
                best, bad, best_epoch = m["ap"], 0, ep
                torch.save({"state": net.state_dict(), "vocab": vocab, "arch": arch, "cfg": CFG}, best_path)
            else:
                bad += 1
                if bad >= CFG["patience"]:
                    break
    net.load_state_dict(torch.load(best_path, map_location=DEVICE)["state"])
    s, _ = predict(net, va, vocab, DEVICE)
    r = metrics(va, s, best_threshold(s, [x["label"] for x in va]))
    net.to("cpu")
    t0 = time.time()
    predict(net, va, vocab, "cpu")
    r.update(best_epoch=best_epoch, params=params, file_mb=round(best_path.stat().st_size / 1e6, 2), cpu_ms_per_pair=round((time.time() - t0) * 1000 / len(va), 3), train_sec=round(time.time() - t_start, 1),
             peak_ram_gb=peak_ram_gb(), gpu_gb=round(torch.cuda.max_memory_allocated() / 1e9, 2) if DEVICE == "cuda" else None)
    (run / "metrics.json").write_text(json.dumps({"val": r}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(tag, f"AP {r['ap']:.4f} 어려운 오답 {r['hard_fp']:.3f} 한영 재현 {r['cross_recall']:.3f} best {best_epoch} | {r['file_mb']}MB CPU {r['cpu_ms_per_pair']}ms/쌍 RAM {r['peak_ram_gb']}GB GPU {r['gpu_gb']}GB {r['train_sec']}초")
    del net
    if DEVICE == "cuda":
        torch.cuda.empty_cache()


def cmd_train():
    tr, va = data()
    sha = hashlib.sha256(EXTRA.read_bytes()).hexdigest()
    log("학습", len(tr), "쌍, 검증", len(va), "쌍, 장치", DEVICE)
    for arch in ARCHES:
        for seed in SEEDS:
            train_one(arch, seed, tr, va, sha)
    log("끝")


def main():
    global ARCHES, EXTRA, TAG
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["overfit", "train"])
    ap.add_argument("--extra", default=str(EXTRA), help="학습 세트에 더할 쌍 파일")
    ap.add_argument("--tag", default="", help="결과 이름 앞에 붙일 말. 예: r3-")
    ap.add_argument("--arch", choices=ARCHES, help="한 구조만 학습")
    a = ap.parse_args()
    EXTRA, TAG = pathlib.Path(a.extra), a.tag
    ARCHES = (a.arch,) if a.arch else ARCHES
    limit_resources()
    {"overfit": cmd_overfit, "train": cmd_train}[a.cmd]()


if __name__ == "__main__":
    main()
