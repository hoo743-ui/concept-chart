# -*- coding: utf-8 -*-
"""data/raw/kowiki_ml → data/processed/B_pairs.jsonl (같은 개념인가) + B_review.jsonl (사람이 볼 넘겨주기) + experiments/splits/B.json

    python experiments/make_pairs.py

- 자동 정답(pos): 문서 제목 ↔ 영어 링크 제목, 띄어쓰기·기호만 다른 넘겨주기.
- 나머지 넘겨주기는 정답으로 쓰지 않는다: '과적합'의 넘겨주기에 '과소적합'처럼 다른 개념이 섞여 있다 → B_review.jsonl.
- 분할: 표기가 비슷한 개념은 묶어서 같은 세트에 넣는다 (묶지 않으면 어려운 오답이 세트 경계에 걸려 시험에서 사라진다).
- 오답은 분할 뒤에 각 세트 안에서 만든다: hard = 표기가 비슷한 다른 개념 (같은 문자, 그리고 그 개념의 한↔영 교차) + sim/concepts.py HARD_NEG,
  rand = 무작위 다른 개념 (시드 고정).
"""
import collections
import json
import pathlib
import random
import re
import sys

from rapidfuzz import fuzz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import HANGUL, PAIRS, ROOT, SPLIT, check_contract, make_group_split, nfc, norm_key, part  # noqa: E402

sys.path.insert(0, str(ROOT / "sim"))
from concepts import HARD_NEG  # noqa: E402

RAW = ROOT / "data" / "raw" / "kowiki_ml" / "pages.jsonl"
REVIEW = PAIRS.with_name("B_review.jsonl")
SEED = 42
HARD_MIN = 72           # 다른 개념인데 이만큼 비슷하면 어려운 오답 후보
HARD_PER_CONCEPT = 2    # 개념당 어려운 오답 수 (문자권별로)
RAND_PER_POS = 2


def clean(title):
    return nfc(re.sub(r"\s*\([^()]*\)\s*$", "", title))     # 문서 구분용 괄호 제거: Cross-validation (statistics)


def main():
    pages = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines()]
    rows, review, seen = [], [], set()
    drop = collections.Counter()
    concepts = {}

    def add(a, b, label, kind, ca, cb, source):
        key = tuple(sorted((norm_key(a), norm_key(b))))
        if key in seen or key[0] == key[1]:
            drop["중복·같은 표기"] += 1
            return False
        seen.add(key)
        rows.append({"a": a, "b": b, "label": label, "kind": kind, "concept_a": ca, "concept_b": cb, "source": source})
        return True

    for p in pages:
        ko = clean(p["title"])
        cid = "kowiki:" + str(p["pageid"])
        en = [clean(x) for x in p["en"]]
        if not en:
            drop["영어 링크 없는 문서"] += 1
        concepts[cid] = {"ko": ko, "en": en[0] if en else None}
        if en:
            if norm_key(ko) == norm_key(en[0]):
                drop["제목이 한영 같음 (Deeplearning4j 등)"] += 1
            else:
                add(ko, en[0], 1, "pos", cid, cid, "kowiki:langlink")
        for r in p["redirects"]:
            r = nfc(r)
            if norm_key(r) == norm_key(ko):
                if r != ko:
                    add(ko, r, 1, "pos", cid, cid, "kowiki:spacing")
            else:
                review.append({"title": ko, "en": en[:1], "redirect": r, "concept": cid})

    # 표기가 비슷한 개념 찾기 (같은 문자권끼리). 같은 표기를 가진 다른 문서도 묶는다 (시험으로 새지 않게)
    ids = sorted(concepts)
    edges = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            for side in ("ko", "en"):
                x, y = concepts[a][side], concepts[b][side]
                if not x or not y or len(x) < 3 or len(y) < 3:
                    continue
                s = fuzz.ratio(x.lower(), y.lower())
                if s >= HARD_MIN:
                    edges.append((s, a, b, side))
    near = collections.defaultdict(list)
    for s, a, b, side in sorted(edges, key=lambda e: (-e[0], e[1], e[2], e[3])):
        near[a].append((s, b, side))
    picked = []                                             # 실제로 오답으로 쓸 개념 쌍 (개념당 상위 몇 개)
    for a in ids:
        for s, b, side in near[a][:HARD_PER_CONCEPT]:
            picked.append((a, b))
    sim_pairs = []
    by_name = {}                                            # 같은 표기 = 같은 개념 (다르게 잡으면 학습과 시험에 같은 말이 들어가 점수가 부풀려진다)
    for c in ids:
        for side in ("ko", "en"):
            if concepts[c][side]:
                by_name.setdefault(norm_key(concepts[c][side]), c)
    for x, y in HARD_NEG:
        ca, cb = by_name.get(norm_key(x), "sim:" + norm_key(x)), by_name.get(norm_key(y), "sim:" + norm_key(y))
        if ca == cb:
            drop["시뮬레이터 오답이 위키백과에서는 같은 개념"] += 1
            continue
        sim_pairs.append((nfc(x), nfc(y), ca, cb))
    # 묶음: 오답으로 쓸 쌍은 반드시 같은 세트에
    links = picked + [(c, d) for _, _, c, d in sim_pairs]
    all_ids = ids + sorted(({c for _, _, c, _ in sim_pairs} | {d for _, _, _, d in sim_pairs}) - set(ids))
    split, groups = make_group_split(all_ids, links, seed=SEED)
    where = {c: k for k in ("train", "val", "test") for c in split[k]}

    # 어려운 오답
    for a, b in picked:
        ca, cb = concepts[a], concepts[b]
        if ca["ko"] and cb["ko"]:
            add(ca["ko"], cb["ko"], 0, "hard", a, b, "kowiki:similar")
        if ca["en"] and cb["en"]:
            add(ca["en"], cb["en"], 0, "hard", a, b, "kowiki:similar")
        if cb["en"]:
            add(ca["ko"], cb["en"], 0, "hard", a, b, "kowiki:similar-cross")   # 과적합 ↔ Underfitting 꼴
        if ca["en"]:
            add(cb["ko"], ca["en"], 0, "hard", a, b, "kowiki:similar-cross")
    for x, y, ca, cb in sim_pairs:
        add(x, y, 0, "hard", ca, cb, "sim:HARD_NEG")

    # 무작위 오답: 세트 안에서만
    rng = random.Random(SEED)
    for k in ("train", "val", "test"):
        names = [c for c in split[k] if c in concepts]
        n_pos = sum(1 for r in rows if r["label"] == 1 and where[r["concept_a"]] == k)
        made = tries = 0
        while made < n_pos * RAND_PER_POS and tries < n_pos * RAND_PER_POS * 50 and len(names) > 1:
            tries += 1
            a, b = rng.sample(names, 2)
            pick = lambda c: rng.choice([x for x in (concepts[c]["ko"], concepts[c]["en"]) if x])   # noqa: E731
            if add(pick(a), pick(b), 0, "rand", a, b, "kowiki:random"):
                made += 1

    summary = check_contract(rows)
    PAIRS.parent.mkdir(parents=True, exist_ok=True)
    with open(PAIRS, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(REVIEW, "w", encoding="utf-8", newline="\n") as f:
        for r in review:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    SPLIT.parent.mkdir(parents=True, exist_ok=True)
    SPLIT.write_text(json.dumps(split, ensure_ascii=False, indent=1), encoding="utf-8")

    print("요약", json.dumps(summary, ensure_ascii=False))
    print("제외", dict(drop), "| 검토 대기 넘겨주기", len(review))
    print("묶음", len(groups), "개, 가장 큰 묶음", max(map(len, groups)), "개념")
    sizes = {k: part(rows, split[k]) for k in ("train", "val", "test")}
    for k, v in sizes.items():
        cross = sum(1 for r in v if r["source"] == "kowiki:similar-cross")
        print(k, "개념", len(split[k]), "쌍", len(v), dict(collections.Counter(r["kind"] for r in v)), "한영 교차 오답", cross)
    print("세트에 걸쳐 버린 쌍", len(rows) - sum(len(v) for v in sizes.values()))
    key = lambda s: norm_key(s)  # noqa: E731
    name_sets = {k: {key(r["a"]) for r in v} | {key(r["b"]) for r in v} for k, v in sizes.items()}
    print("세트 사이 같은 표기: train∩test", len(name_sets["train"] & name_sets["test"]), "train∩val", len(name_sets["train"] & name_sets["val"]), "val∩test", len(name_sets["val"] & name_sets["test"]))
    print("\n--- 시험 세트 hard 표본")
    r2 = random.Random(1)
    t = [r for r in sizes["test"] if r["kind"] == "hard"]
    for r in r2.sample(t, min(16, len(t))):
        print(f"  {r['a']}  |  {r['b']}  ({r['source']})")


if __name__ == "__main__":
    main()
