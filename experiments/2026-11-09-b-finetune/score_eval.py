# -*- coding: utf-8 -*-
"""넓은 평가 세트 채점. 임계값은 검증 세트에서 고른 값을 그대로 쓴다. 시험 세트는 쓰지 않는다. 후보는 한 번에 하나씩 불러온다.

    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/score_eval.py models     파인튜닝·글자 모델 점수
    .venv/Scripts/python    experiments/2026-11-09-b-finetune/score_eval.py lr         지금 방식 점수
    .venv/Scripts/python    experiments/2026-11-09-b-finetune/score_eval.py summary    표 (eval_devgloss.json)

--eval로 다른 세트를 지정할 수 있다 (.jsonl 또는 사용자가 정답을 단 my_sheet.csv).
"""
import argparse
import csv
import gc
import json
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from common import HANGUL, cross_script, load_pairs, load_split, metrics, norm_key, part  # noqa: E402

SEEDS = (42, 1, 2)
DEFAULT = ROOT / "data" / "eval" / "devgloss_pairs.jsonl"
SCORES = ROOT / "data" / "eval" / "scores"


def load_eval(path):
    path = pathlib.Path(path)
    if path.suffix == ".jsonl":
        return load_pairs(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949")                      # 엑셀이 다시 저장하면 cp949 + 탭이 된다
    delim = "\t" if "\t" in text.splitlines()[0] else ","
    rows = list(csv.reader(text.splitlines(), delimiter=delim))[1:]
    out = []
    for a, b, label, kind in rows:
        if a and b and label.strip() in ("0", "1"):
            lab = int(label)
            out.append({"a": a, "b": b, "label": lab, "kind": "pos" if lab else ("rand" if kind == "rand" else "hard"), "source": "my:" + kind, "seen": False})
    return out


def save(path, name, scores):
    d = SCORES / pathlib.Path(path).stem
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(scores), encoding="utf-8")
    print(name, "완료", len(scores), flush=True)


def cmd_models(a):
    import threading

    import torch
    import train as ft
    import train_char as tc
    torch.set_num_threads(tc.CPU_THREADS)
    threading.Thread(target=tc.guard, daemon=True).start()
    rows = load_eval(a.eval)
    for arch in tc.ARCHES:
        if a.tag and arch != "bilstm":
            continue
        for s in SEEDS:
            ck = torch.load(ROOT / "models" / f"b-char-{a.tag}{arch}-seed{s}-best.pt", map_location=tc.DEVICE)
            net = tc.CharNet(arch, len(ck["vocab"]) + 2).to(tc.DEVICE)
            net.load_state_dict(ck["state"])
            save(a.eval, f"char-{a.tag}{arch}-seed{s}", tc.predict(net, rows, ck["vocab"], tc.DEVICE)[0])
    if a.tag:
        return
    for s in SEEDS:
        net = ft.PairNet(ft.MODEL).to(ft.DEVICE)
        net.load_state_dict(torch.load(ROOT / "models" / f"b-finetune-r2-dev-v2-seed{s}-best.pt", map_location=ft.DEVICE))
        save(a.eval, f"finetune-seed{s}", ft.predict(net, rows)[0])
        del net
        gc.collect()
        torch.cuda.empty_cache()
    print("최대 RAM", tc.peak_ram_gb(), "GB")


def cmd_lr(a):
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    import baseline_lr as bl
    data, split = load_pairs(), load_split()
    tr = part(data, split["train"])
    tfv = TfidfVectorizer(analyzer="char", ngram_range=(1, 3)).fit(sorted({bl.rom(x) for r in tr for x in (r["a"], r["b"])}))
    X = np.array([bl.features(r["a"], r["b"], tfv) for r in tr])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    lr = LogisticRegression(max_iter=2000, C=1.0).fit((X - mu) / sd, [r["label"] for r in tr])
    rows = load_eval(a.eval)
    Xe = np.array([bl.features(r["a"], r["b"], tfv) for r in rows])
    save(a.eval, "lr", [float(x) for x in lr.predict_proba((Xe - mu) / sd)[:, 1]])


def transliterated(a, b):
    """한↔영 쌍이 소리 옮김(음차)인가. 아니면 번역으로 본다"""
    import baseline_lr as bl
    from rapidfuzz import fuzz
    ko, en = (a, b) if HANGUL.search(a) else (b, a)
    return fuzz.ratio(bl.rom(ko), norm_key(en)) >= 60


def val_threshold(name):
    if name == "lr":
        p = HERE / "baseline_lr.json"
    elif name.startswith("finetune"):
        p = HERE / f"r2-dev-v2-{name.split('-')[1]}" / "metrics.json"
    else:
        p = HERE / name / "metrics.json"
    return json.loads(p.read_text(encoding="utf-8"))["val"]["threshold"]


def report(rows, scores, thr):
    """전체 지표 + 처음 보는 표기, 번역형·음차형 재현율"""
    def recall(idx):
        return sum(scores[i] >= thr for i in idx) / len(idx) if idx else None
    m = metrics(rows, scores, thr)
    pos = [i for i, r in enumerate(rows) if r["label"] and cross_script(r["a"], r["b"])]
    cross_hard = [i for i, r in enumerate(rows) if r["source"] in ("dev:similar-cross", "my:cross") and not r["label"]]
    kinds = {i: transliterated(rows[i]["a"], rows[i]["b"]) for i in pos}
    new = [i for i, r in enumerate(rows) if not r.get("seen")]
    out = {"ap": m["ap"], "auc": m["auc"], "f1": m["f1"], "precision": m["precision"], "recall": m["recall"], "hard_fp": m["hard_fp"], "cross_recall": m["cross_recall"],
           "cross_hard_fp": recall(cross_hard), "translit_recall": recall([i for i in pos if kinds[i]]), "transl_recall": recall([i for i in pos if not kinds[i]]),
           "n_translit": sum(kinds.values()), "n_transl": sum(not v for v in kinds.values())}
    if len(new) < len(rows):
        sub = [rows[i] for i in new]
        out["unseen_ap"] = metrics(sub, [scores[i] for i in new], thr)["ap"]
        out["unseen_hard_fp"] = metrics(sub, [scores[i] for i in new], thr)["hard_fp"]
    return out


def cmd_summary(a):
    rows = load_eval(a.eval)
    groups = {"지금 방식": ["lr"], "파인튜닝 r2": [f"finetune-seed{s}" for s in SEEDS], "글자 CNN": [f"char-cnn-seed{s}" for s in SEEDS], "글자 BiLSTM": [f"char-bilstm-seed{s}" for s in SEEDS]}
    d = SCORES / pathlib.Path(a.eval).stem
    if (d / "char-r3-bilstm-seed42.json").exists():
        groups["글자 BiLSTM r3"] = [f"char-r3-bilstm-seed{s}" for s in SEEDS]
    res = {}
    for g, names in groups.items():
        per = [report(rows, json.loads((d / f"{n}.json").read_text(encoding="utf-8")), val_threshold(n)) for n in names]
        res[g] = {k: {"mean": statistics.mean(p[k] for p in per), "min": min(p[k] for p in per), "max": max(p[k] for p in per)} for k in per[0] if per[0][k] is not None}
        print(g, {k: round(v["mean"], 3) for k, v in res[g].items()})
        print("   범위", {k: (round(res[g][k]["min"], 3), round(res[g][k]["max"], 3)) for k in ("ap", "hard_fp", "cross_recall", "transl_recall")})
    (HERE / f"eval_{pathlib.Path(a.eval).stem}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["models", "lr", "summary"])
    ap.add_argument("--eval", default=str(DEFAULT))
    ap.add_argument("--tag", default="", help="글자 BiLSTM 결과 이름 앞말만 채점. 예: r3-")
    a = ap.parse_args()
    {"models": cmd_models, "lr": cmd_lr, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    main()
