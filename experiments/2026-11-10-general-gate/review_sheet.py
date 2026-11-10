# -*- coding: utf-8 -*-
"""정답 검토 시트: Claude가 표시한 정답 중 관문 판정과 엇갈린 낱말만 모은다 (사용자가 고칠 곳만 보게).

    python experiments/2026-11-10-general-gate/review_sheet.py           # → data/eval/review_sheet.csv (git에 없음, 엑셀용 BOM)
    python experiments/2026-11-10-general-gate/review_sheet.py --apply [시트 경로]   # 시트의 '내 판단'을 반영한 정답으로 다시 잰다 (원래 정답 파일은 그대로)

넣는 낱말 (조정용·개발 대화·새 분야 세트)
- 오탐: base·V3·V4·V4w 중 하나라도 보여 줬는데 Claude 정답이 '아님'
- 놓침: Claude 정답이 '개념'인데 base가 숨겼고, LLM이 인정했거나 분야 사전에 전문 뜻만 있는 낱말 (관문이 거의 통과시킬 뻔한 것)
LLM을 새로 부르지 않는다 (fieldhint.py가 남긴 캐시만 읽는다).
"""
import csv
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as ev  # noqa: E402
import everyday as ed_mod  # noqa: E402
import fieldhint as fh_mod  # noqa: E402

g = ev.g
ROOT = ev.ROOT
SHEET = ROOT / "data" / "eval" / "review_sheet.csv"
VARIANTS = ("base", "V3", "V4", "V4w")
HEAD = ["세트", "낱말", "엇갈림", "Claude 정답(1 개념, 0 아님)", "내 판단(1 개념, 0 아님, 빈칸 = Claude 정답 그대로)", "보여 준 방식", "예문"]


def load(cache):
    return json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}


def general(split, D, gold):
    ws = [x for x in json.loads((D / "words.json").read_text(encoding="utf-8")) if x["split"] == split and x["form"] in gold]
    c = load(D / "llm_q4413de9271.json")
    return ws, gold, c, load(D / "wiki.json"), load(D / f"everyday_{ed_mod.ASK}.json"), load(D / f"fieldhint_{fh_mod.ASK}.json")


def dev():
    d = ROOT / "data" / "eval"
    gold_pos = set((d / "concept_gold.txt").read_text(encoding="utf-8").split()) | {x.replace("_", " ") for x in (d / "concept_gold_holdout.txt").read_text(encoding="utf-8").split()}
    con = sqlite3.connect(f"file:{pathlib.Path.home()}/.claude/concept-chart.sqlite?mode=ro", uri=True)
    items = []
    for cid, f in con.execute("SELECT f.concept, (SELECT form FROM forms x WHERE x.concept=f.concept ORDER BY n DESC LIMIT 1) FROM freq f "
                              "WHERE (SELECT MIN(ts) FROM mentions m WHERE m.concept=f.concept) < ? ORDER BY f.n DESC, f.concept", (ev.DEV_CUTOFF,)):
        items.append({"form": f, "sents": [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (cid,))]})
    D = ev.DEV_D
    return (items, {x["form"]: x["form"] in gold_pos for x in items}, load(D / "llm_dev_q4413de9271.json"), load(D / "wiki.json"),
            load(D / f"everyday_dev_{ed_mod.ASK}.json"), load(D / f"fieldhint_dev_{fh_mod.ASK}.json"))


def sets():
    D, F = ROOT / "data" / "eval" / "general", ROOT / "data" / "eval" / "fresh"
    fg = json.loads((F / "gold.json").read_text(encoding="utf-8"))
    for w in ("번역", "통과", "형태소"):
        fg.pop(w, None)
    return {"조정용": general("tune", D, json.loads((D / "gold.json").read_text(encoding="utf-8"))), "개발 대화": dev(), "새 분야": general("holdout", F, fg)}


def disputed(items, gold, c, wk, ed, fh):
    for x in items:
        f = x["form"]
        shown = [v for v in VARIANTS if fh_mod.verdict(v, x, c, wk, ed, fh) == "show"]
        if shown and not gold[f]:
            yield x, "오탐", shown
        elif gold[f] and "base" not in shown and (c.get(f) is True or g.lexicon_verdict(f) == "special"):
            yield x, "놓침", shown


def example(x):
    s = next((s for s in (x.get("sents") or []) if x["form"] in s), (x.get("sents") or [""])[0])
    s = " ".join(s.split())
    i = max(0, s.find(x["form"]) - 40)
    return ("…" if i else "") + s[i:i + 90]


def write():
    rows = []
    for name, (items, gold, c, wk, ed, fh) in sets().items():
        for x, kind, shown in disputed(items, gold, c, wk, ed, fh):
            rows.append([name, x["form"], kind, int(gold[x["form"]]), "", " ".join(shown) or "없음", example(x)])
    with SHEET.open("w", encoding="utf-8-sig", newline="") as f:      # 엑셀이 한글을 깨지 않게 BOM
        csv.writer(f).writerows([HEAD] + rows)
    from collections import Counter
    print(f"{SHEET} : {len(rows)}개", dict(Counter((r[0], r[2]) for r in rows)))


def apply(path=SHEET):
    with pathlib.Path(path).open(encoding="utf-8-sig", newline="") as f:
        fixes = {(r[0], r[1]): r[4].strip() == "1" for r in list(csv.reader(f))[1:] if r[4].strip() in ("0", "1")}
    print(f"고친 낱말 {len(fixes)}개")
    for name, (items, gold, c, wk, ed, fh) in sets().items():
        gold = dict(gold, **{w: v for (s, w), v in fixes.items() if s == name and w in gold})
        pos = sum(gold[x["form"]] for x in items)
        for v in VARIANTS:
            shown = [x["form"] for x in items if fh_mod.verdict(v, x, c, wk, ed, fh) == "show"]
            tp = sum(gold[w] for w in shown)
            print(f"{name:6} {v:4} 정밀도 {tp / max(1, len(shown)):.3f}  재현율 {tp / max(1, pos):.3f}")


if __name__ == "__main__":
    g.load_lexicons(ev.LEX)
    if "--apply" in sys.argv:                                   # --apply [다른 시트 경로] (시트가 엑셀에 열려 있어 다른 이름으로 저장했을 때)
        rest = sys.argv[sys.argv.index("--apply") + 1:]
        apply(rest[0] if rest else SHEET)
    else:
        write()
