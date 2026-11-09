# -*- coding: utf-8 -*-
"""어휘 넓히기 (r3): 위키백과 분류 추가 + 위키데이터(CC0) 이름·별칭. 학습 세트에만 더한다.

    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/expand_vocab.py

- 기존 B_extra_r2-dev-v2.jsonl에 더해 B_extra_r3-cs-v2.jsonl을 만든다. 받은 원본은 data/raw/에 저장하고 있으면 다시 받지 않는다.
- 검증·시험·공개 용어집(data/eval) 표기는 새 쌍에 넣지 않는다. 내 대화 시트 표기는 보지 않는다.
- 위키백과 넘겨주기는 쓰지 않는다 ('과적합'→'과소적합'처럼 다른 개념이 섞여 있다). 별칭은 항목당 언어별 3개까지.
"""
import collections
import json
import pathlib
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import auto_rounds as ar  # noqa: E402
from common import HANGUL, ROOT, check_contract, load_pairs, load_split, nfc, norm_key, part  # noqa: E402

ROUND = ("r3-cs", ["분류:컴퓨터 과학", "분류:정보 기술", "분류:클라우드 컴퓨팅", "분류:소프트웨어"], 1)
BASE = ROOT / "data" / "processed" / "B_extra_r2-dev-v2.jsonl"
OUT = ROOT / "data" / "processed" / "B_extra_r3-cs-v2.jsonl"
WD_RAW = ROOT / "data" / "raw" / "wikidata_terms"
WD_API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "concept-chart-research/0.1 (personal study tool; ko-en term pairs)"}
MAX_ALIAS = 3


def pages_of(tag):
    return [json.loads(x) for x in (ROOT / "data" / "raw" / f"kowiki_{tag}" / "pages.jsonl").read_text(encoding="utf-8").splitlines()]


def fetch_wikidata(titles):
    path = WD_RAW / "items.jsonl"
    if path.exists():
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    WD_RAW.mkdir(parents=True, exist_ok=True)
    items, reqs = [], 0
    for i in range(0, len(titles), 50):
        body = urllib.parse.urlencode({"action": "wbgetentities", "sites": "kowiki", "titles": "|".join(titles[i:i + 50]), "props": "labels|aliases|sitelinks", "languages": "ko|en", "sitefilter": "kowiki", "format": "json", "formatversion": 2}).encode()
        for attempt in range(6):
            time.sleep(1.5)
            reqs += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(WD_API, data=body, headers=UA), timeout=60) as r:
                    d = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 5:
                    raise
                time.sleep(int(e.headers.get("Retry-After") or 60))
        for q, e in d.get("entities", {}).items():
            title = e.get("sitelinks", {}).get("kowiki", {}).get("title")
            if title:
                items.append({"qid": q, "title": title, "labels": {k: v["value"] for k, v in e.get("labels", {}).items()}, "aliases": {k: [x["value"] for x in v] for k, v in e.get("aliases", {}).items()}})
        ar.log("위키데이터", i + 50, "/", len(titles), "항목", len(items))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for x in items:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    (WD_RAW / "meta.json").write_text(json.dumps({"source": WD_API, "license": "CC0", "items": len(items), "requests": reqs, "collected": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=1), encoding="utf-8")
    return items


def good(x):
    x = nfc(x)
    return x if 2 <= len(x) <= 60 and not re.search(r"[\[\]{}<>|]", x) else None


def main():
    all_rows, split = load_pairs(), load_split()
    held = {norm_key(x) for r in part(all_rows, split["val"]) + part(all_rows, split["test"]) for x in (r["a"], r["b"])}
    held |= {norm_key(x) for r in load_pairs(ROOT / "data" / "eval" / "devgloss_pairs.jsonl") for x in (r["a"], r["b"])}
    extra = load_pairs(BASE)
    n_base = len(extra)
    known_keys = {tuple(sorted((norm_key(r["a"]), norm_key(r["b"])))) for r in all_rows + extra}
    ml, r1, r2 = pages_of("ml"), pages_of("r1-ai-nlp"), pages_of("r2-dev")
    known_ids = {p["pageid"] for p in ml + r1 + r2}
    tag, roots, depth = ROUND
    ar.build_extra(tag, roots, depth, known_ids, known_keys, held, extra)
    r3 = pages_of(tag)
    by_title = {p["title"]: p for p in ml + r1 + r2 + r3}
    items = fetch_wikidata(sorted(by_title))
    rows, cut = [], collections.Counter()

    def add(a, b, cid):
        ka, kb = norm_key(a), norm_key(b)
        key = tuple(sorted((ka, kb)))
        if ka == kb or key in known_keys:
            cut["이미 있거나 같은 표기"] += 1
        elif ka in held or kb in held:
            cut["평가 표기"] += 1
        else:
            known_keys.add(key)
            rows.append({"a": a, "b": b, "label": 1, "kind": "pos", "concept_a": cid, "concept_b": cid, "source": "wikidata:alias"})
    names = {}
    for it in items:
        p = by_title.get(it["title"])
        if not p:
            continue
        cid = "kowiki:" + str(p["pageid"])
        ko, en = good(it["labels"].get("ko", "")), good(it["labels"].get("en", ""))
        ko = ko if ko and HANGUL.search(ko) else None
        en = en if en and not HANGUL.search(en) else None
        ka = [x for x in map(good, it["aliases"].get("ko", [])) if x][:MAX_ALIAS]
        ea = [x for x in map(good, it["aliases"].get("en", [])) if x and not HANGUL.search(x)][:MAX_ALIAS]
        if not (norm_key(ko or "") in held or norm_key(en or "") in held):
            if ko and en:
                add(ko, en, cid)
            for x in ka:
                if en:
                    add(x, en, cid)
                if ko:
                    add(x, ko, cid)
            for x in ea:
                if ko:
                    add(ko, x, cid)
                if en:
                    add(en, x, cid)
            if ko or en:
                names[cid] = [x for x in (ko, en, *ka, *ea) if x and norm_key(x) not in held]
    rng = random.Random(42)
    ids = sorted(c for c, v in names.items() if v)
    n_pos, made, tries = len(rows), 0, 0
    while made < n_pos * ar.RAND_PER_POS and tries < n_pos * ar.RAND_PER_POS * 50:
        tries += 1
        x, y = rng.sample(ids, 2)
        a, b = rng.choice(names[x]), rng.choice(names[y])
        key = tuple(sorted((norm_key(a), norm_key(b))))
        if key not in known_keys and key[0] != key[1]:
            known_keys.add(key)
            rows.append({"a": a, "b": b, "label": 0, "kind": "rand", "concept_a": x, "concept_b": y, "source": "wikidata:random"})
            made += 1
    extra += rows
    print(check_contract(extra), flush=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for r in extra:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ar.log("기존", n_base, "→ 전체", len(extra), "별칭 쌍", n_pos, "제외", dict(cut), dict(collections.Counter(r["kind"] for r in extra)), "위키데이터 항목", len(items))
    print("--- 별칭 정답 표본")
    for r in random.Random(5).sample([r for r in rows if r["label"]], min(30, n_pos)):
        print(f"  {r['a']}  |  {r['b']}")


if __name__ == "__main__":
    main()
