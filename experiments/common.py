# -*- coding: utf-8 -*-
"""실험들이 같이 쓰는 불러오기·계약 점검·분할 (docs/TRAINING.md 3-3, 3-4). 아무것도 experiments/를 import하지 않는다."""
import collections
import json
import pathlib
import random
import re
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAIRS = ROOT / "data" / "processed" / "B_pairs.jsonl"
SPLIT = ROOT / "experiments" / "splits" / "B.json"
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")


def nfc(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


def norm_key(s):
    """sim/pipeline.py·kit/serve.py와 같은 규칙: 소문자 + 공백·-·_·/ 제거"""
    return re.sub(r"[\s\-_/]+", "", s.lower())


def cross_script(a, b):
    """한쪽은 한글, 다른 쪽은 로마자만 (한↔영 재현율의 대상)"""
    ha, hb = bool(HANGUL.search(a)), bool(HANGUL.search(b))
    return ha != hb and bool(LATIN.search(b if ha else a))


def load_pairs(path=PAIRS):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def check_contract(rows):
    """데이터 계약. 어기면 예외, 통과하면 개수 요약"""
    for i, r in enumerate(rows):
        for k in ("a", "b", "kind", "concept_a", "concept_b", "source"):
            if not isinstance(r.get(k), str) or not r[k]:
                raise ValueError(f"{i}번 줄 {k}가 빈 값")
        if r["label"] not in (0, 1):
            raise ValueError(f"{i}번 줄 label")
        if r["kind"] not in ("pos", "hard", "rand"):
            raise ValueError(f"{i}번 줄 kind")
        if (r["label"] == 1) != (r["concept_a"] == r["concept_b"]) or (r["label"] == 1) != (r["kind"] == "pos"):
            raise ValueError(f"{i}번 줄 라벨과 개념이 어긋남: {r['a']} / {r['b']}")
        for k in ("a", "b"):
            if r[k] != unicodedata.normalize("NFC", r[k]):
                raise ValueError(f"{i}번 줄 {k}가 NFC가 아님")
    keys = [tuple(sorted((norm_key(r["a"]), norm_key(r["b"])))) for r in rows]
    dup = len(keys) - len(set(keys))
    if dup:
        raise ValueError(f"중복 쌍 {dup}개")
    return {"전체": len(rows), "라벨": dict(collections.Counter(r["label"] for r in rows)), "kind": dict(collections.Counter(r["kind"] for r in rows)),
            "개념": len({r["concept_a"] for r in rows} | {r["concept_b"] for r in rows}),
            "한영 정답 쌍": sum(1 for r in rows if r["label"] == 1 and cross_script(r["a"], r["b"]))}


def make_group_split(concepts, links, seed=42, ratio=(("train", 0.70), ("val", 0.15), ("test", 0.15))):
    """개념 단위 70/15/15. links로 이어진 개념은 같은 세트에 넣는다 (어려운 오답이 세트 경계에 걸려 사라지지 않게).
    한 번 만들고 고정한다. → (분할, 묶음 목록)"""
    parent = {c: c for c in concepts}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in links:
        parent[find(a)] = find(b)
    by = collections.defaultdict(list)
    for c in concepts:
        by[find(c)].append(c)
    groups = sorted((sorted(g) for g in by.values()), key=lambda g: g[0])
    random.Random(seed).shuffle(groups)
    split = {k: [] for k, _ in ratio}
    want = dict(ratio)
    # 묶인 개념과 혼자인 개념을 각각 같은 비율로 나눈다. 함께 나누면 묶음이 전부 학습 세트로 가서 시험에 어려운 오답이 없어진다
    for part_groups in (sorted((g for g in groups if len(g) > 1), key=len, reverse=True), [g for g in groups if len(g) == 1]):
        total = sum(map(len, part_groups))
        done = {k: 0 for k in split}
        for g in part_groups:
            k = max(split, key=lambda s: want[s] * total - done[s])
            split[k].extend(g)
            done[k] += len(g)
    out = {"seed": seed, **{k: sorted(v) for k, v in split.items()}}
    a, b, c = set(out["train"]), set(out["val"]), set(out["test"])
    assert not (a & b or a & c or b & c), "세트 사이에 개념이 겹친다"
    return out, groups


def best_threshold(scores, labels):
    """F1이 가장 큰 임계값 (검증 세트에서만 고른다)"""
    from sklearn.metrics import f1_score
    best, thr = -1.0, 0.5
    for t in sorted(set(float(s) for s in scores)):
        f = f1_score(labels, [s >= t for s in scores], zero_division=0)
        if f > best:
            best, thr = f, t
    return thr


def metrics(rows, scores, thr):
    """시뮬레이터와 같은 지표: AUC, AP, F1·정밀도·재현율, 어려운 오답 오판율, 한↔영 재현율"""
    from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
    y = [r["label"] for r in rows]
    pred = [float(s) >= thr for s in scores]
    hard = [p for p, r in zip(pred, rows) if r["kind"] == "hard"]
    cross_hard = [p for p, r in zip(pred, rows) if r["source"] == "kowiki:similar-cross"]
    cross = [p for p, r in zip(pred, rows) if r["label"] == 1 and cross_script(r["a"], r["b"])]
    avg = lambda v: sum(v) / len(v) if v else None   # noqa: E731
    return {"n": len(rows), "auc": roc_auc_score(y, scores), "ap": average_precision_score(y, scores), "f1": f1_score(y, pred, zero_division=0),
            "precision": precision_score(y, pred, zero_division=0), "recall": recall_score(y, pred, zero_division=0), "threshold": thr,
            "hard_fp": avg(hard), "cross_hard_fp": avg(cross_hard), "cross_recall": avg(cross)}


LIVE = ROOT / "data" / "live.json"


def write_live(**state):
    """실시간 화면(experiments/live_view.py)용 현재 상태. 학습에 영향을 주지 않고, 실패해도 학습을 멈추지 않는다"""
    try:
        tmp = LIVE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(LIVE)
    except OSError:
        pass


def load_split(path=SPLIT):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def part(rows, names):
    """두 개념이 모두 같은 세트에 있는 쌍만"""
    s = set(names)
    return [r for r in rows if r["concept_a"] in s and r["concept_b"] in s]
