# -*- coding: utf-8 -*-
"""B(같은 개념인가) 인코더 파인튜닝. docs/TRAINING.md 3-6을 따른다. 시험 세트는 불러오지 않는다.

    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/train.py baseline --model <이름>    기준선 ②: 학습 없이 코사인 유사도
    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/train.py overfit                    작은 묶음 외우기 (버그 점검)
    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/train.py probe                      데이터 5%로 1 epoch (시간·메모리 추정)
    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/train.py train --seed 42            학습 (epoch마다 검증, 조기 종료)

구조: 표기 2개를 같은 인코더에 넣어 (u, v, |u-v|, u*v) → 작은 분류 층 → 같은 개념 확률. 손실은 이진 교차 엔트로피.
"""
import argparse
import csv
import hashlib
import json
import os
import pathlib
import platform
import random
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
os.environ.setdefault("HF_HOME", str(ROOT / "data" / "hf_cache"))     # 내려받은 모델을 프로젝트 안(git 제외)에 둔다
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(HERE.parent))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from transformers import AutoModel, AutoTokenizer, logging as hf_logging  # noqa: E402

from common import PAIRS, best_threshold, load_pairs, load_split, metrics, part, write_live  # noqa: E402

hf_logging.set_verbosity_error()
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CFG = dict(max_epochs=10, patience=3, min_delta=0.001, lr=2e-5, head_lr=1e-3, weight_decay=0.01, batch=16, warmup=0.10, clip=1.0, max_len=32)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


class PairNet(torch.nn.Module):
    def __init__(self, name):
        super().__init__()
        self.enc = AutoModel.from_pretrained(name)
        self.tok = AutoTokenizer.from_pretrained(name)
        d = self.enc.config.hidden_size
        self.head = torch.nn.Sequential(torch.nn.Linear(d * 4, 128), torch.nn.ReLU(), torch.nn.Dropout(0.1), torch.nn.Linear(128, 1))

    def embed(self, texts):
        b = self.tok(texts, padding=True, truncation=True, max_length=CFG["max_len"], return_tensors="pt").to(DEVICE)
        h = self.enc(**b).last_hidden_state
        m = b["attention_mask"].unsqueeze(-1).float()
        return (h * m).sum(1) / m.sum(1).clamp(min=1e-9)     # 평균 풀링 (이 모델의 sentence-transformers 설정과 같음)

    def forward(self, a, b):
        u, v = self.embed(a), self.embed(b)
        return self.head(torch.cat([u, v, (u - v).abs(), u * v], 1)).squeeze(1)


def batches(rows, size, shuffle, rng=None):
    idx = list(range(len(rows)))
    if shuffle:
        rng.shuffle(idx)
    for i in range(0, len(idx), size):
        yield [rows[j] for j in idx[i:i + size]]


@torch.no_grad()
def predict(net, rows):
    net.eval()
    out, loss_sum, n = [], 0.0, 0
    bce = torch.nn.BCEWithLogitsLoss(reduction="sum")
    for b in batches(rows, 64, False):
        logit = net([r["a"] for r in b], [r["b"] for r in b])
        y = torch.tensor([float(r["label"]) for r in b], device=DEVICE)
        loss_sum += bce(logit, y).item()
        n += len(b)
        out += torch.sigmoid(logit).cpu().tolist()
    return out, loss_sum / n


def make_opt(net, total_steps):
    enc = [p for p in net.enc.parameters() if p.requires_grad]
    opt = torch.optim.AdamW([{"params": enc, "lr": CFG["lr"]}, {"params": net.head.parameters(), "lr": CFG["head_lr"]}], weight_decay=CFG["weight_decay"])
    warm = max(1, int(total_steps * CFG["warmup"]))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * max(0.0, (total_steps - s) / max(1, total_steps - warm)) if s >= warm else (s + 1) / warm)
    return opt, sched


def train_step(net, b, bce, opt, sched=None):
    logit = net([r["a"] for r in b], [r["b"] for r in b])
    net.last_logit = logit.detach()                      # 실시간 화면용 기록. 학습에는 쓰지 않는다
    loss = bce(logit, torch.tensor([float(r["label"]) for r in b], device=DEVICE))
    opt.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(net.parameters(), CFG["clip"])
    opt.step()
    if sched:
        sched.step()
    return loss.item()


def data():
    rows, split = load_pairs(), load_split()
    return part(rows, split["train"]), part(rows, split["val"])     # 시험 세트는 여기서 꺼내지 않는다


def gpu_peak():
    return round(torch.cuda.max_memory_allocated() / 1e9, 2) if DEVICE == "cuda" else None


def cmd_baseline(a):
    """기준선 ②: 사전학습 모델 그대로 (코사인 유사도, 학습 없음)"""
    from sentence_transformers import SentenceTransformer
    tr, va = data()
    t0 = time.time()
    m = SentenceTransformer(a.model, device=DEVICE)
    load = time.time() - t0
    t0 = time.time()
    A = m.encode([r["a"] for r in va], convert_to_numpy=True, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    B = m.encode([r["b"] for r in va], convert_to_numpy=True, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    s = [float(x) for x in (A * B).sum(1)]
    sec = time.time() - t0
    r = metrics(va, s, best_threshold(s, [x["label"] for x in va]))
    r.update(load_sec=round(load, 1), ms_per_pair=round(sec * 1000 / len(va), 2), gpu_gb=gpu_peak())
    print(json.dumps(r, ensure_ascii=False, indent=1))
    name = a.model.split("/")[-1]
    (HERE / f"baseline_{name}.json").write_text(json.dumps({"method": a.model + " 코사인 (학습 없음)", "val": r}, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_overfit(a):
    """작은 묶음 외우기: 라벨·입력·손실 연결 버그 점검. 32개를 외우면 손실이 거의 0까지 내려가야 한다"""
    set_seed(42)
    tr, _ = data()
    rng = random.Random(0)
    small = rng.sample([r for r in tr if r["label"] == 1], 16) + rng.sample([r for r in tr if r["label"] == 0], 16)
    net = PairNet(MODEL).to(DEVICE)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-4)
    bce = torch.nn.BCEWithLogitsLoss()
    net.train()
    first = None
    for ep in range(60):
        ls = [train_step(net, b, bce, opt) for b in batches(small, 16, True, rng)]
        cur = sum(ls) / len(ls)
        first = first if first is not None else cur
        if ep % 10 == 0 or ep == 59:
            print(f"epoch {ep:>2} 손실 {cur:.4f}", flush=True)
    print(f"처음 {first:.4f} → 끝 {cur:.4f}", "통과" if cur < 0.05 else "실패")


def cmd_probe(a):
    set_seed(42)
    tr, va = data()
    rng = random.Random(0)
    sub = rng.sample(tr, max(32, len(tr) // 20))
    net = PairNet(MODEL).to(DEVICE)
    steps = len(sub) // CFG["batch"] + 1
    opt, sched = make_opt(net, steps)
    bce = torch.nn.BCEWithLogitsLoss()
    net.train()
    t0 = time.time()
    for b in batches(sub, CFG["batch"], True, rng):
        train_step(net, b, bce, opt, sched)
    sec = time.time() - t0
    t0 = time.time()
    predict(net, va)
    vs = time.time() - t0
    full = sec * len(tr) / len(sub) + vs
    print(f"장치 {DEVICE} | {len(sub)}쌍 {sec:.1f}초, 검증 {vs:.1f}초 | 전체 1 epoch 예상 {full:.0f}초, 시드 1개 최대 10 epoch {full*10/60:.1f}분, 시드 3개 {full*30/60:.1f}분 | GPU 최대 {gpu_peak()}GB")


def cmd_train(a):
    set_seed(a.seed)
    tr, va = data()
    extra_sha = None
    if a.extra:                                                # 학습 세트에만 더한다. 검증·시험 표기는 만들 때 이미 뺐다 (auto_rounds.py)
        tr = tr + load_pairs(a.extra)
        extra_sha = hashlib.sha256(pathlib.Path(a.extra).read_bytes()).hexdigest()
    print(f"학습 {len(tr)}쌍, 검증 {len(va)}쌍", flush=True)
    rng = random.Random(a.seed)
    tag = a.tag + "-" if a.tag else ""
    run = HERE / f"{tag}seed{a.seed}"
    run.mkdir(exist_ok=True)
    best_path = ROOT / "models" / f"b-finetune-{tag}seed{a.seed}-best.pt"
    best_path.parent.mkdir(exist_ok=True)
    net = PairNet(MODEL).to(DEVICE)
    steps = (len(tr) // CFG["batch"] + 1) * CFG["max_epochs"]
    opt, sched = make_opt(net, steps)
    bce = torch.nn.BCEWithLogitsLoss()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    import sentence_transformers
    import transformers
    (run / "config.json").write_text(json.dumps({"model": MODEL, "seed": a.seed, **CFG, "git": commit, "data_sha256": hashlib.sha256(PAIRS.read_bytes()).hexdigest(), "extra_sha256": extra_sha, "train_pairs": len(tr), "split": "experiments/splits/B.json",
                                                 "device": DEVICE, "gpu": torch.cuda.get_device_name(0) if DEVICE == "cuda" else None, "python": platform.python_version(),
                                                 "torch": torch.__version__, "transformers": transformers.__version__, "sentence_transformers": sentence_transformers.__version__,
                                                 "pos_weight": None}, ensure_ascii=False, indent=1), encoding="utf-8")
    best, bad, best_epoch = -1.0, 0, 0
    with open(run / "log.csv", "w", newline="", encoding="utf-8") as f:
        log = csv.writer(f)
        log.writerow(["epoch", "train_loss", "val_loss", "val_ap", "val_auc", "val_hard_fp", "val_cross_recall", "sec"])
        for ep in range(1, CFG["max_epochs"] + 1):
            t0 = time.time()
            net.train()
            ls, total = [], len(tr) // CFG["batch"] + 1
            for b in batches(tr, CFG["batch"], True, rng):
                ls.append(train_step(net, b, bce, opt, sched))
                if len(ls) % 20 == 0:
                    p = torch.sigmoid(net.last_logit).tolist()
                    write_live(run=run.name, epoch=ep, max_epochs=CFG["max_epochs"], step=len(ls), total=total, loss=sum(ls[-20:]) / 20, time=time.time(),
                               sample=[{"a": r["a"], "b": r["b"], "label": r["label"], "p": round(x, 3)} for r, x in list(zip(b, p))[:6]])
            s, val_loss = predict(net, va)
            thr = best_threshold(s, [r["label"] for r in va])
            m = metrics(va, s, thr)
            row = [ep, round(sum(ls) / len(ls), 4), round(val_loss, 4), round(m["ap"], 4), round(m["auc"], 4), round(m["hard_fp"], 4), round(m["cross_recall"], 4), round(time.time() - t0, 1)]
            log.writerow(row)
            f.flush()
            print("epoch", *row, flush=True)
            if m["ap"] > best + CFG["min_delta"]:
                best, bad, best_epoch = m["ap"], 0, ep
                torch.save(net.state_dict(), best_path)
            else:
                bad += 1
                if bad >= CFG["patience"]:
                    print("조기 종료", flush=True)
                    break
    net.load_state_dict(torch.load(best_path, map_location=DEVICE))
    s, _ = predict(net, va)
    r = metrics(va, s, best_threshold(s, [x["label"] for x in va]))
    r.update(best_epoch=best_epoch, gpu_gb=gpu_peak())
    (run / "metrics.json").write_text(json.dumps({"val": r}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["baseline", "overfit", "probe", "train"])
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--extra", default=None, help="학습 세트에 더할 쌍 파일")
    ap.add_argument("--tag", default="", help="라운드 이름 (결과 폴더·체크포인트 이름)")
    a = ap.parse_args()
    print("장치", DEVICE, torch.cuda.get_device_name(0) if DEVICE == "cuda" else "", flush=True)
    {"baseline": cmd_baseline, "overfit": cmd_overfit, "probe": cmd_probe, "train": cmd_train}[a.cmd](a)


if __name__ == "__main__":
    main()
