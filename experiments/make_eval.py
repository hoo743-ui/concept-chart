# -*- coding: utf-8 -*-
"""넓은 평가 세트 만들기. 평가 전용이라 학습 데이터에 넣지 않는다 (data/eval/, git 제외).

    python experiments/make_eval.py     # 기본 환경(.venv). romanizer 필요

1. data/eval/devgloss_pairs.jsonl: 공개 개발 용어집(MDN·Kubernetes). 정답 = 같은 항목의 한↔영, 어려운 오답 = 표기가 비슷한 다른 항목, 무작위 오답.
   쌍마다 seen(표기가 기존 학습 데이터에 있는가)을 적는다. 시험 세트 표기가 들어간 쌍은 뺀다.
2. data/eval/my_sheet.csv: 내 대화 DB의 개념 이름 쌍. 정답은 사용자가 label 칸에 적는다 (1 같음, 0 다름, 모르면 비움). 개인 데이터라 출력하지 않는다.
"""
import collections
import csv
import json
import pathlib
import random
import re
import sqlite3
import sys

import numpy as np
from korean_romanizer.romanizer import Romanizer
from rapidfuzz import fuzz, process

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import HANGUL, LATIN, ROOT, cross_script, load_pairs, load_split, nfc, norm_key, part  # noqa: E402

RAW = ROOT / "data" / "raw" / "devgloss" / "pages.jsonl"
OUT = ROOT / "data" / "eval"
EXTRA = ROOT / "data" / "processed" / "B_extra_r2-dev-v2.jsonl"
DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
HARD_MIN, HARD_PER, RAND_PER_POS, SEED = 72, 2, 2, 42
SHEET_NEAR, SHEET_RAND, SHEET_MIN, CROSS_MIN = 150, 50, 70, 65


def clean_mdn(p):
    en = p.get("slug", "").split("/")[-1].replace("_", " ")
    ko = re.sub(r"\s*[((][^()()]*[))]\s*$", "", p.get("title", ""))
    return nfc(ko), nfc(en)


def clean_k8s(p):
    t = p.get("title", "")
    m = re.match(r"(.+?)\s*\(원문,\s*(.+?)\)\s*$", t)
    if m:
        return nfc(m.group(1)), nfc(m.group(2))
    return nfc(t), nfc(p.get("id", "").replace("-", " "))


def glossary():
    seen, out, cut = set(), [], collections.Counter()
    for p in map(json.loads, RAW.read_text(encoding="utf-8").splitlines()):
        ko, en = clean_mdn(p) if p["source"] == "mdn" else clean_k8s(p)
        if not ko or not en or not HANGUL.search(ko) or not LATIN.search(en) or HANGUL.search(en):
            cut["한글 제목 또는 영어 이름 없음"] += 1
        elif norm_key(ko) in seen or norm_key(en) in seen:
            cut["같은 표기 중복"] += 1
        else:
            seen |= {norm_key(ko), norm_key(en)}
            out.append({"id": f"{p['source']}:{p['path']}", "source": p["source"], "ko": ko, "en": en})
    print("용어집 항목", len(out), dict(collections.Counter(x["source"] for x in out)), "제외", dict(cut))
    return out


def devgloss():
    items = glossary()
    rows, split = load_pairs(), load_split()
    test = {norm_key(x) for r in part(rows, split["test"]) for x in (r["a"], r["b"])}
    known = {norm_key(x) for r in part(rows, split["train"]) + part(rows, split["val"]) + load_pairs(EXTRA) for x in (r["a"], r["b"])}
    out, keys = [], set()

    def add(a, b, label, kind, x, y, source):
        ka, kb = norm_key(a), norm_key(b)
        key = tuple(sorted((ka, kb)))
        if ka == kb or key in keys or ka in test or kb in test:
            return False
        keys.add(key)
        out.append({"a": a, "b": b, "label": label, "kind": kind, "concept_a": x["id"], "concept_b": y["id"], "source": source, "gloss": x["source"], "seen": ka in known or kb in known})
        return True
    for x in items:
        add(x["ko"], x["en"], 1, "pos", x, x, "dev:gloss")
    for side in ("ko", "en"):
        names = [x[side].lower() for x in items]
        m = process.cdist(names, names, scorer=fuzz.ratio, score_cutoff=HARD_MIN, dtype=np.int16, workers=2)
        np.fill_diagonal(m, 0)
        for i in range(len(items)):
            if len(names[i]) < 3:
                continue
            for j in np.argsort(-m[i], kind="stable")[:HARD_PER]:
                if m[i, j] >= HARD_MIN and len(names[j]) >= 3:
                    add(items[i][side], items[j][side], 0, "hard", items[i], items[j], "dev:similar")
                    add(items[i]["ko"], items[j]["en"], 0, "hard", items[i], items[j], "dev:similar-cross")
    rng = random.Random(SEED)
    n_pos = sum(r["label"] for r in out)
    made = tries = 0
    while made < n_pos * RAND_PER_POS and tries < n_pos * RAND_PER_POS * 50:
        tries += 1
        x, y = rng.sample(items, 2)
        if add(rng.choice((x["ko"], x["en"])), rng.choice((y["ko"], y["en"])), 0, "rand", x, y, "dev:random"):
            made += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "devgloss_pairs.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("쌍", len(out), dict(collections.Counter(r["kind"] for r in out)), "seen", dict(collections.Counter((r["kind"], r["seen"]) for r in out)))
    print("한영 정답", sum(1 for r in out if r["label"] and cross_script(r["a"], r["b"])))
    for kind in ("pos", "hard"):
        print(f"--- {kind} 표본")
        for r in random.Random(1).sample([r for r in out if r["kind"] == kind], 18):
            print(f"  {r['a']}  |  {r['b']}  {'seen' if r['seen'] else ''}")


def rom(s):
    try:
        return norm_key(Romanizer(s).romanize())
    except Exception:  # noqa: BLE001
        return norm_key(s)


def my_sheet():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    best = {}
    for c, form, n in con.execute("select concept, form, n from forms order by concept, n desc"):
        best.setdefault(c, form)
    names = sorted(nfc(x) for x in best.values() if len(x) >= 2)
    near = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if norm_key(a) == norm_key(b):
                continue
            if cross_script(a, b):
                ko, en = (a, b) if HANGUL.search(a) else (b, a)
                s = fuzz.ratio(rom(ko), norm_key(en))
                if s >= CROSS_MIN:
                    near.append((s, a, b, "cross"))
            elif min(len(a), len(b)) >= 3:
                s = fuzz.ratio(a.lower(), b.lower())
                if s >= SHEET_MIN:
                    near.append((s, a, b, "same"))
    near.sort(key=lambda x: (-x[0], x[1], x[2]))
    chosen = near[:SHEET_NEAR]
    used = {(a, b) for _, a, b, _ in chosen}
    rng = random.Random(SEED)
    rows = [(a, b, kind) for _, a, b, kind in chosen]
    while len(rows) < len(chosen) + SHEET_RAND and len(names) > 1:
        a, b = sorted(rng.sample(names, 2))
        if (a, b) not in used and norm_key(a) != norm_key(b):
            used.add((a, b))
            rows.append((a, b, "rand"))
    rng.shuffle(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "my_sheet.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["a", "b", "label(1 같음, 0 다름, 모르면 비움)", "kind"])
        for a, b, kind in rows:
            w.writerow([a, b, "", kind])
    print("내 대화 개념", len(names), "후보", len(near), dict(collections.Counter(x[3] for x in near)), "시트", len(rows), dict(collections.Counter(r[2] for r in rows)))


if __name__ == "__main__":
    devgloss()
    my_sheet()
