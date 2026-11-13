# -*- coding: utf-8 -*-
"""개념 넓히기 실험 2 준비: 분류기 학습용 낱말 표 (cells.py와 같은 세트·정답·저장된 신호). LLM·위키백과에 새로 묻지 않는다 (cells.py를 먼저 돌린다).

    .venv/Scripts/python.exe experiments/2026-11-13-expand/build_data.py   → data/processed/expand/words.jsonl (git 제외: 개발 대화 문장이 들어 있다)
시험 세트(test)는 넣지 않는다.
"""
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cells as C  # noqa: E402

c2, g, ev, p, R, S = C.c2, C.g, C.ev, C.p, C.R, C.S
OUT = c2.ROOT / "data" / "processed" / "expand" / "words.jsonl"


def main():
    g.load_lexicons(ev.LEX)
    fx = c2.fixes()
    extra = json.loads(C.EXTRA.read_text(encoding="utf-8"))
    sets = {"조정용": c2.general_set("조정용", c2.EVAL / "general", "tune", fx, "조정용"),
            "예전 holdout": c2.general_set("예전 holdout", c2.EVAL / "general", "holdout", fx, "예전 holdout"),
            "새 분야": c2.general_set("새 분야", c2.EVAL / "fresh", "holdout", fx, "새 분야"),
            "IT 조정용": c2.general_set("IT 조정용", c2.EVAL / "tune2", "tune", fx, "IT 조정용"),
            "개발 대화": c2.dev_set(fx)}
    fb_gold = json.loads((c2.EVAL / "feedback_gold.json").read_text(encoding="utf-8"))
    rows = []
    for name, (items, gold, D, sfx) in sets.items():
        if name == "개발 대화":
            gold.update({w: b for w, b in fb_gold.items() if w in gold})
        drop = R.leaked_all(gold)
        items = [x for x in items if x["form"] not in drop]
        c_old, _c_sp, wk = c2.prepare(items, D, sfx)
        if name == "개발 대화":
            c_en = p.ask(items, D / f"llm{sfx}_en_{p.tag(g.en_judge_prompt)}.json", g.en_judge_prompt, g.JUDGE_SCHEMA, "is_term",
                         lambda x: g.ASCII_FORM.fullmatch(x["form"]) and g.rule_verdict(x["form"], x.get("sents")) in ("unknown", "likely"))
            c_old = {**c_old, **c_en}
            wk = ev.sourced_all(items, c_old, D / "wiki.json")
        for x in items:
            f = x["form"]
            r = g.rule_verdict(f, x.get("sents"))
            w = wk.get(f) if f in wk else extra.get(f)
            rows.append({"set": name, "form": f, "sents": (x.get("sents") or [])[:3], "gold": bool(gold[f]), "rule": r,
                         "lex": g.lexicon_verdict(f), "llm": c_old.get(f), "wiki": None if w is None else bool(w),
                         "cur": g.final(r, c_old.get(f), wk.get(f) if r == "unknown" else None, g.lexicon_verdict(f)) == "show"})
    con = sqlite3.connect(f"file:{C.DB.as_posix()}?mode=ro", uri=True)
    lab = {c: f for c, f, n in con.execute("SELECT concept, form, n FROM forms ORDER BY n, form DESC")}
    by_label = {v: k for k, v in lab.items()}
    for w, y in fb_gold.items():
        cid = by_label.get(w)
        if not cid:
            continue
        j = S.judgment_row(con, cid)
        sents = [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? LIMIT 3", (cid,))]
        r = S.rule_of(con, cid, w)
        rows.append({"set": "피드백", "form": w, "sents": sents, "gold": bool(y), "rule": r, "lex": g.lexicon_verdict(w),
                     "llm": None if not j or j[0] is None else bool(j[0]), "wiki": S.sourced(con, cid),
                     "cur": S.gate_of(con, cid, w, use_user=False)["show"]})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(len(rows), "행 →", OUT)


if __name__ == "__main__":
    main()
