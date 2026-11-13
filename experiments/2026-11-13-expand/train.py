# -*- coding: utf-8 -*-
"""개념 넓히기 실험 2 (사용자 결정 11-13 '빠르게 가보자'): 생성형 LLM의 예/아니오 대신 트랜스포머 분류기(인코더 미세조정)로 개념 점수를 내면 재현율이 늘어나나.

    .venv/Scripts/python.exe experiments/2026-11-13-expand/train.py [--model klue/roberta-base] [--signals 0|1]

- 데이터: build_data.py가 만든 data/processed/expand/words.jsonl (조정용·예전 holdout·새 분야·IT 조정용·개발 대화·피드백). 시험 세트(test)는 없다.
- 낱말(표기) 단위 5겹 교차 검증 (같은 표기는 한 겹에만, 시드 고정): 모든 낱말이 자기를 보지 않은 모델의 점수를 받는다.
- 입력: 낱말 [SEP] 대화 문장 3개. --signals 1이면 앞에 저장된 신호(규칙·분야 사전·LLM 답·위키백과 문서)를 글자로 붙인다.
- 판정: 규칙이 확신(accept/reject)하면 그대로, 나머지는 점수 >= 기준점. 기준점은 일반 세트 4개의 교차 검증 점수에서 정밀도 0.8 이상 중 F1 최대로 정하고
  개발 대화·피드백에는 그대로 적용한다 (거기서 고르지 않는다).
- 자원 상한(resource-limits): GPU 1개, fp16, 배치 16, 길이 160, 스레드 4, 사용 가능 RAM 1GB 아래면 멈춘다 (EXPAND_RAM_FLOOR_GB). 체크포인트는 저장하지 않는다.
"""
import argparse
import json
import pathlib
import random
import sys
import time

import torch

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "data" / "processed" / "expand" / "words.jsonl"
sys.path.insert(0, str(ROOT / "ml"))
GENERAL = ("조정용", "예전 holdout", "새 분야", "IT 조정용")
FLOOR = 0.8
RAM_FLOOR_GB = float(__import__("os").environ.get("EXPAND_RAM_FLOOR_GB", "1.0"))   # 사용 가능 RAM이 이보다 적으면 멈춘다
torch.set_num_threads(4)


def ram_ok():
    try:
        import ctypes

        class M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tot", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = M()
        m.l = ctypes.sizeof(M)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.avail > RAM_FLOOR_GB * 2**30
    except Exception:
        return True


from concept_clf import signal_text, text_of  # noqa: E402,F401  앱(ml/concept_clf.py)과 같은 입력 글자 (학습과 사용이 어긋나지 않게)


def folds(rows, k=5, seed=13):
    forms = sorted({r["form"] for r in rows})
    random.Random(seed).shuffle(forms)
    return {f: i % k for i, f in enumerate(forms)}


def train_fold(tok, model_name, tr, te, signals, epochs, dev, save=None):
    from transformers import AutoModelForSequenceClassification
    model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=2).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-5, weight_decay=0.01)
    steps = epochs * ((len(tr) + 15) // 16)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / (0.1 * steps)) * max(0.0, (steps - s) / steps))
    scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    pos = sum(r["gold"] for r in tr)
    w = torch.tensor([1.0, (len(tr) - pos) / max(1, pos)], device=dev)       # 개념이 적은 쪽에 무게

    def enc(batch):
        t = [text_of(r, signals) for r in batch]
        e = tok([x[0] for x in t], [x[1] for x in t], truncation="only_second", max_length=160, padding=True, return_tensors="pt")
        e.pop("token_type_ids", None)        # klue/roberta는 type_vocab_size=1인데 BERT식 토크나이저가 둘째 문장에 1을 붙인다
        return e.to(dev)

    rnd = random.Random(7)
    for _ep in range(epochs):
        model.train()
        order = tr[:]
        rnd.shuffle(order)
        for i in range(0, len(order), 16):
            if not ram_ok():
                raise SystemExit("사용 가능 RAM이 상한 아래라 멈춤")
            b = order[i:i + 16]
            y = torch.tensor([int(r["gold"]) for r in b], device=dev)
            with torch.autocast(dev, dtype=torch.float16, enabled=dev == "cuda"):
                logits = model(**enc(b)).logits
            loss = torch.nn.functional.cross_entropy(logits.float(), y, weight=w)
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(te), 32):
            b = te[i:i + 32]
            with torch.autocast(dev, dtype=torch.float16, enabled=dev == "cuda"):
                logits = model(**enc(b)).logits
            out += torch.softmax(logits.float(), -1)[:, 1].tolist()
    if save:                                                        # 앱이 쓸 모델 (models/는 git 제외)
        save.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(save)
        tok.save_pretrained(save)
    del model, opt
    torch.cuda.empty_cache()
    return out


def decide(r, s, t):
    if r["rule"] == "accept":
        return True
    if r["rule"] == "reject":
        return False
    return s >= t


def prf(sel, rows):
    tp = sum(r["gold"] for r, x in zip(rows, sel) if x)
    n = sum(sel)
    pos = sum(r["gold"] for r in rows)
    p, rc = tp / max(1, n), tp / max(1, pos)
    return n, round(p, 3), round(rc, 3), round(2 * p * rc / max(1e-9, p + rc), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="klue/roberta-base")
    ap.add_argument("--signals", type=int, default=1)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--holdout", action="store_true", help="일반 세트 4개로만 학습하고 개발 대화·피드백(같은 표기 포함)은 학습에 넣지 않고 잰다")
    ap.add_argument("--all", action="store_true", help="--holdout 대신 모든 세트(개발 대화·피드백 포함)로 학습해 저장한다. 성능 추정은 5겹 교차 검증 숫자를 쓴다")
    ap.add_argument("--save", default="", help="--holdout 모델을 저장할 폴더 (예: models/concept-clf)")
    a = ap.parse_args()
    if a.holdout or a.all:
        return holdout(a)
    from transformers import AutoTokenizer
    rows = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    fo = folds(rows)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model)
    score = [None] * len(rows)
    t0 = time.time()
    for k in range(5):
        te_i = [i for i, r in enumerate(rows) if fo[r["form"]] == k]
        tr = [r for r in rows if fo[r["form"]] != k]
        sc = train_fold(tok, a.model, tr, [rows[i] for i in te_i], a.signals, a.epochs, dev)
        for i, s in zip(te_i, sc):
            score[i] = s
        gpu = torch.cuda.max_memory_allocated() / 2**30 if dev == "cuda" else 0
        print(f"겹 {k + 1}/5 끝 ({time.time() - t0:.0f}초, GPU 최대 {gpu:.2f}GB)", flush=True)
    gen = [(r, s) for r, s in zip(rows, score) if r["set"] in GENERAL]
    best = (0.5, -1)
    for t in [x / 100 for x in range(5, 100)]:
        n, p, rc, f1 = prf([decide(r, s, t) for r, s in gen], [r for r, _ in gen])
        if p >= FLOOR and f1 > best[1]:
            best = (t, f1)
    t = best[0]
    res = {"model": a.model, "signals": a.signals, "epochs": a.epochs, "threshold": t, "sets": {}}
    print(f"\n기준점 {t:.2f} (일반 세트 교차 검증에서 정밀도 {FLOOR} 이상 중 F1 최대)")
    print("세트        지금 관문 (보임 P R F1)        분류기 (보임 P R F1)")
    for name in list(GENERAL) + ["일반 4개 합", "개발 대화", "피드백"]:
        sub = [(r, s) for r, s in zip(rows, score) if (r["set"] in GENERAL if name == "일반 4개 합" else r["set"] == name)]
        rr = [r for r, _ in sub]
        cur = prf([r["cur"] for r in rr], rr)
        new = prf([decide(r, s, t) for r, s in sub], rr)
        res["sets"][name] = {"cur": cur, "new": new}
        print(f"{name:10} {cur[0]:4} {cur[1]:.3f} {cur[2]:.3f} {cur[3]:.3f}      {new[0]:4} {new[1]:.3f} {new[2]:.3f} {new[3]:.3f}")
    for name in ("개발 대화", "피드백"):
        sub = [(r, s) for r, s in zip(rows, score) if r["set"] == name]
        added = [r["form"] + ("" if r["gold"] else "✗") for r, s in sub if decide(r, s, t) and not r["cur"]]
        lost = [r["form"] + ("" if r["gold"] else "✗") for r, s in sub if r["cur"] and not decide(r, s, t)]
        res["sets"][name]["added"], res["sets"][name]["lost"] = added, lost
        print(f"\n{name} 새로 보임 {len(added)}: {', '.join(added[:60])}\n{name} 빠짐 {len(lost)}: {', '.join(lost[:40])}")
    tag = a.model.split("/")[-1] + ("-sig" if a.signals else "-text")
    (HERE / f"train_{tag}.json").write_bytes(json.dumps(res, ensure_ascii=False, indent=1).encode("utf-8"))
    (ROOT / "data" / "processed" / "expand" / f"scores_{tag}.json").write_text(
        json.dumps([{"set": r["set"], "form": r["form"], "score": s} for r, s in zip(rows, score)], ensure_ascii=False), encoding="utf-8")


def holdout(a):
    """앱에 넣을 모델: 일반 세트 4개로만 학습한다. 개발 대화·피드백은 앞으로도 정직한 점검으로 남긴다 (verify가 이 모델 점수로 재도 새지 않는다)"""
    from transformers import AutoTokenizer
    rows = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    keep_out = {r["form"] for r in rows if r["set"] not in GENERAL}
    tr = rows if a.all else [r for r in rows if r["set"] in GENERAL and r["form"] not in keep_out]
    te = [] if a.all else [r for r in rows if r["set"] not in GENERAL]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model)
    t0 = time.time()
    save = (ROOT / a.save) if a.save else None
    sc = train_fold(tok, a.model, tr, te, a.signals, a.epochs, dev, save)
    print(f"학습 {len(tr)}개 ({'모든 세트' if a.all else f'일반 세트, 개발 대화·피드백 표기 {len(keep_out)}개 뺌'}), {time.time() - t0:.0f}초", flush=True)
    res = {"model": a.model, "signals": a.signals, "epochs": a.epochs, "train": len(tr), "sets": {}}
    for name in ("개발 대화", "피드백"):
        sub = [(r, s) for r, s in zip(te, sc) if r["set"] == name]
        rr = [r for r, _ in sub]
        cur = prf([r["cur"] for r in rr], rr)
        line = f"{name:8} 지금 {cur}"
        res["sets"][name] = {"cur": cur}
        for t in (0.88, 0.93, 0.95, 0.97, 0.98):
            new = prf([decide(r, s, t) for r, s in sub], rr)
            res["sets"][name][str(t)] = new
            line += f" | {t}: {new}"
        print(line)
    tag = a.model.split("/")[-1] + ("-sig" if a.signals else "-text")
    if not a.all:
        (HERE / f"holdout_{tag}.json").write_bytes(json.dumps(res, ensure_ascii=False, indent=1).encode("utf-8"))
    if save:
        (save / "concept_clf.json").write_text(json.dumps({"base": a.model, "signals": a.signals, "epochs": a.epochs, "threshold": 0.97,
                                                         "train_rows": len(tr), "trained_on": "all" if a.all else "general", "trained_forms": sorted({r["form"] for r in tr}), "data_sha": __import__("hashlib").sha256(DATA.read_bytes()).hexdigest()[:16],
                                                         "made": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
