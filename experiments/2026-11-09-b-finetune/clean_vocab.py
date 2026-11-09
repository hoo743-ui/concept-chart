# -*- coding: utf-8 -*-
"""넓힌 어휘 정리: 별칭은 믿을 만한 것만 남기고, 어려운 오답 비중을 되돌린다 (B_extra_r3-clean.jsonl). 받아 둔 원본만 쓰고 새로 받지 않는다.

    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/clean_vocab.py

별칭 규칙 (r3 BiLSTM이 나빠져서 넣었다. 원인이 별칭이라고 확인한 것은 아니다)
- 뺀다: 2글자 이하(약어 제외), 주소·식별자 꼴(: / . 포함), 한 단어짜리 일반어로 줄어드는 영어 별칭
- 약어는 대문자 2~6자이고 영어 이름의 머리글자와 맞을 때만
- 다른 별칭은 같은 언어 대표 이름과 철자가 FUZZ_MIN 이상 비슷할 때만 (표기 변형). 번역 대응은 대표 이름끼리만 믿는다
어려운 오답: 라운드 사이에도 만든다 (지금까지는 라운드 안에서만 만들어 넓힐수록 비중이 줄었다).
검증·시험·공개 용어집 표기는 새 쌍에 넣지 않는다.
"""
import collections
import json
import pathlib
import random
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402
from rapidfuzz import fuzz, process  # noqa: E402
from common import HANGUL, ROOT, check_contract, load_pairs, load_split, nfc, norm_key, part  # noqa: E402

SRC = ROOT / "data" / "processed" / "B_extra_r3-cs-v2.jsonl"
OUT = ROOT / "data" / "processed" / "B_extra_r3-clean.jsonl"
ITEMS = ROOT / "data" / "raw" / "wikidata_terms" / "items.jsonl"
FUZZ_MIN, MAX_ALIAS, HARD_MIN, HARD_PER, ALIAS_RAND_PER_POS = 60, 3, 72, 3, 1


def initials(name):
    return "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", name)).upper()


def is_acronym(x, en):
    return bool(re.fullmatch(r"[A-Z0-9]{2,6}", x)) and bool(en) and initials(en) == x


def usable(x):
    x = nfc(x)
    return x if 3 <= len(x) <= 50 and not re.search(r"[:/\[\]{}<>|]|\.[a-z]{2,}", x) else None


def page_ids():
    ids = {}
    for tag in ("ml", "r1-ai-nlp", "r2-dev", "r3-cs"):
        for line in (ROOT / "data" / "raw" / f"kowiki_{tag}" / "pages.jsonl").read_text(encoding="utf-8").splitlines():
            p = json.loads(line)
            ids[p["title"]] = p["pageid"]
    return ids


def main():
    rows, split = load_pairs(), load_split()
    held = {norm_key(x) for r in part(rows, split["val"]) + part(rows, split["test"]) for x in (r["a"], r["b"])}
    held |= {norm_key(x) for r in load_pairs(ROOT / "data" / "eval" / "devgloss_pairs.jsonl") for x in (r["a"], r["b"])}
    keep = [r for r in load_pairs(SRC) if r["source"].startswith("kowiki:")]
    n_keep = len(keep)
    known = {tuple(sorted((norm_key(r["a"]), norm_key(r["b"])))) for r in rows + keep}
    out, cut = [], collections.Counter()

    def add(a, b, label, kind, ca, cb, source):
        ka, kb = norm_key(a), norm_key(b)
        key = tuple(sorted((ka, kb)))
        if ka == kb or key in known or ka in held or kb in held:
            return False
        known.add(key)
        out.append({"a": a, "b": b, "label": label, "kind": kind, "concept_a": ca, "concept_b": cb, "source": source})
        return True
    ids, names = page_ids(), {}
    for it in map(json.loads, ITEMS.read_text(encoding="utf-8").splitlines()):
        pid = ids.get(it["title"])
        if pid is None:
            continue
        cid, labels = f"kowiki:{pid}", it["labels"]
        ko, en = nfc(labels.get("ko", "")), nfc(labels.get("en", ""))
        ko = ko if HANGUL.search(ko) and usable(ko) else None
        en = en if en and not HANGUL.search(en) and usable(en) else None
        if (ko and norm_key(ko) in held) or (en and norm_key(en) in held):
            cut["평가 표기"] += 1
            continue
        got = [x for x in (ko, en) if x]
        if ko and en:
            add(ko, en, 1, "pos", cid, cid, "wikidata:label")
        for x in map(nfc, it["aliases"].get("en", [])[:MAX_ALIAS]):
            if is_acronym(x, en):
                got.append(x)
                add(en, x, 1, "pos", cid, cid, "wikidata:acronym")
                if ko:
                    add(ko, x, 1, "pos", cid, cid, "wikidata:acronym")
            elif en and usable(x) and not HANGUL.search(x) and fuzz.ratio(x.lower(), en.lower()) >= FUZZ_MIN:
                got.append(x)
                add(en, x, 1, "pos", cid, cid, "wikidata:variant")
                if ko:
                    add(ko, x, 1, "pos", cid, cid, "wikidata:variant")
            else:
                cut["영어 별칭 탈락"] += 1
        for x in map(nfc, it["aliases"].get("ko", [])[:MAX_ALIAS]):
            if ko and usable(x) and HANGUL.search(x) and fuzz.ratio(x, ko) >= FUZZ_MIN:
                got.append(x)
                add(ko, x, 1, "pos", cid, cid, "wikidata:variant")
                if en:
                    add(x, en, 1, "pos", cid, cid, "wikidata:variant")
            else:
                cut["한글 별칭 탈락"] += 1
        if got:
            names[cid] = got
    n_pos = sum(r["label"] for r in out)

    # 라운드 사이 어려운 오답. 위키백과 문서 제목(한·영)끼리 만든다
    concepts = {r["concept_a"]: (r["a"], r["b"]) for r in keep if r["kind"] == "pos"}
    cids = sorted(concepts)
    hard_new = 0
    for side in (0, 1):
        low = [concepts[c][side].lower() for c in cids]
        m = process.cdist(low, low, scorer=fuzz.ratio, score_cutoff=HARD_MIN, dtype=np.int16, workers=2)
        np.fill_diagonal(m, 0)
        for i in range(len(cids)):
            if len(low[i]) < 3:
                continue
            for j in np.argsort(-m[i], kind="stable")[:HARD_PER]:
                if m[i, j] >= HARD_MIN and len(low[j]) >= 3:
                    a, b = concepts[cids[i]], concepts[cids[j]]
                    hard_new += add(a[side], b[side], 0, "hard", cids[i], cids[j], "kowiki:similar")
                    hard_new += add(a[0], b[1], 0, "hard", cids[i], cids[j], "kowiki:similar-cross")
    rng = random.Random(42)
    pool = sorted(names)
    made = tries = 0
    while made < n_pos * ALIAS_RAND_PER_POS and tries < n_pos * 50:
        tries += 1
        x, y = rng.sample(pool, 2)
        made += add(rng.choice(names[x]), rng.choice(names[y]), 0, "rand", x, y, "wikidata:random")
    final = keep + out
    print(check_contract(final))
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("위키 쌍", n_keep, "별칭 정답", n_pos, dict(collections.Counter(r["source"] for r in out)), "새 어려운 오답", hard_new, "제외", dict(cut))
    print("--- 별칭 정답 표본")
    for r in random.Random(5).sample([r for r in out if r["label"]], min(30, n_pos)):
        print(f"  {r['a']}  |  {r['b']}  ({r['source'].split(':')[1]})")
    print("--- 새 어려운 오답 표본")
    hard = [r for r in out if r["kind"] == "hard"]
    for r in random.Random(6).sample(hard, min(15, len(hard))):
        print(f"  {r['a']}  |  {r['b']}")


if __name__ == "__main__":
    main()
