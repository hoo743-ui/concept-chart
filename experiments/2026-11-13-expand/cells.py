# -*- coding: utf-8 -*-
"""개념 넓히기 실험 1 (사용자 요청 11-13 '최대한 확장할 수 있는 방법 알아봐'): 관문이 숨기는 칸을 하나씩 열면 정밀도·재현율이 어떻게 바뀌나.

    .venv/Scripts/python.exe experiments/2026-11-13-expand/cells.py

칸 = (규칙, 분야 사전, LLM 답, 이름이 맞는 위키백과 문서). 지금 관문(concept_gate.final)이 숨기는 칸만 센다.
세트: 조정용·예전 holdout·새 분야·IT 조정용·개발 대화 (2026-11-10-general-gate와 같은 정답·캐시) + 피드백(실제 DB의 '맞아요·아니에요', 읽기 전용).
시험 세트(test)는 열지 않는다. LLM에 새로 묻지 않는다(저장된 답만). LLM이 '아님'이라 해서 위키백과를 찾지 않은 낱말은
wiki_extra.json에 따로 찾아 둔다 (앱 0.7.16과 같게: 정의로 쓴 문서 또는 다른 뜻이라 버린 문서가 있으면 근거).
"""
import collections
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
GG = HERE.parent / "2026-11-10-general-gate"
sys.path.insert(0, str(GG))
import rules as R  # noqa: E402

c2, g, ev, p = R.c2, R.g, R.ev, R.p
sys.path.insert(0, str(c2.ROOT / "kit"))
import fetch_sources as fs  # noqa: E402
import study_api as S  # noqa: E402

DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
EXTRA = HERE / "wiki_extra.json"


def wiki_has(term):
    rej = []
    got = fs.wikipedia_lead(term, rej)
    return bool(got) or bool(rej)


def fill_wiki(forms, wk):
    extra = json.loads(EXTRA.read_text(encoding="utf-8")) if EXTRA.exists() else {}
    todo = [f for f in forms if f not in wk and f not in extra]
    for i, f in enumerate(todo, 1):
        try:
            extra[f] = wiki_has(f)
        except Exception as e:  # noqa: BLE001
            print("위키 조회 실패", f, type(e).__name__, flush=True)
        if i % 25 == 0:
            EXTRA.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
            print(f"  위키 {i}/{len(todo)}", flush=True)
    EXTRA.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
    return {**extra, **{k: v for k, v in wk.items() if k in wk}}


def cell(rule, lex, llm, src):
    return f"{rule}|{lex or 'none'}|llm={'T' if llm is True else 'F' if llm is False else '-'}|wiki={'Y' if src else 'N'}"


def main():
    g.load_lexicons(ev.LEX)
    fx = c2.fixes()
    sets = {"조정용": c2.general_set("조정용", c2.EVAL / "general", "tune", fx, "조정용"),
            "예전 holdout": c2.general_set("예전 holdout", c2.EVAL / "general", "holdout", fx, "예전 holdout"),
            "새 분야": c2.general_set("새 분야", c2.EVAL / "fresh", "holdout", fx, "새 분야"),
            "IT 조정용": c2.general_set("IT 조정용", c2.EVAL / "tune2", "tune", fx, "IT 조정용"),
            "개발 대화": c2.dev_set(fx)}
    fb_gold = json.loads((c2.EVAL / "feedback_gold.json").read_text(encoding="utf-8"))
    rows = {}            # 세트 → [(칸, 정답, 지금 보임, 낱말)]
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
        need = [x["form"] for x in items if g.rule_verdict(x["form"], x.get("sents")) in ("unknown", "likely")
                and g.lexicon_verdict(x["form"]) != "general"]
        wk = fill_wiki(need, wk)
        rr = []
        for x in items:
            f = x["form"]
            r = g.rule_verdict(f, x.get("sents"))
            lex, llm, src = g.lexicon_verdict(f), c_old.get(f), bool(wk.get(f))
            cur = g.final(r, llm, wk.get(f) if r == "unknown" else None, lex) == "show"
            rr.append((cell(r, lex, llm, src), gold[f], cur, f))
        rows[name] = rr
        print(f"{name}: 낱말 {len(items)} 개념 {sum(gold[x['form']] for x in items)}", flush=True)
    # 피드백: 실제 DB의 저장된 신호
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    lab = {}
    for c, f, n in con.execute("SELECT concept, form, n FROM forms ORDER BY n, form DESC"):
        lab[c] = f
    by_label = {v: k for k, v in lab.items()}
    rr = []
    for w, y in fb_gold.items():
        cid = by_label.get(w)
        if not cid:
            continue
        j = S.judgment_row(con, cid)
        llm = None if not j or j[0] is None else bool(j[0])
        r = S.rule_of(con, cid, w)
        lex = g.lexicon_verdict(w)
        src = S.sourced(con, cid)
        cur = S.gate_of(con, cid, w, use_user=False)["show"]
        rr.append((cell(r, lex, llm, src), y, cur, w))
    rows["피드백"] = rr
    # 칸별 표
    hidden = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, []]))
    for name, rr in rows.items():
        for k, y, cur, f in rr:
            if not cur:
                t = hidden[k][name]
                t[0] += y
                t[1] += 1
                t[2].append(f + ("" if y else "✗"))
    out = {"sets": {}, "cells": {}}
    for name, rr in rows.items():
        sel = [y for k, y, cur, f in rr if cur]
        pos = sum(y for *_x, in [(r[1],) for r in rr] for y in _x)
        out["sets"][name] = {"words": len(rr), "gold": pos, "shown": len(sel), "tp": sum(sel)}
    order = sorted(hidden, key=lambda k: -sum(t[1] for t in hidden[k].values()))
    for k in order:
        out["cells"][k] = {n: {"ok": t[0], "n": t[1], "eg": t[2][:15]} for n, t in hidden[k].items()}
    (HERE / "cells_result.json").write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    print("\n세트별 지금 관문 (보인 것, 정밀도, 재현율)")
    for n, s in out["sets"].items():
        print(f"  {n:10} 낱말 {s['words']:4} 개념 {s['gold']:4} 보임 {s['shown']:4} P {s['tp']/max(1,s['shown']):.3f} R {s['tp']/max(1,s['gold']):.3f}")
    print("\n숨긴 칸 (세트별 개념/낱말)")
    for k in order:
        tot = [sum(t[0] for n, t in hidden[k].items() if n != "피드백"), sum(t[1] for n, t in hidden[k].items() if n != "피드백")]
        cells = "  ".join(f"{n} {t[0]}/{t[1]}" for n, t in hidden[k].items())
        print(f"{k:42} 합(피드백 뺀) {tot[0]}/{tot[1]} = {tot[0]/max(1,tot[1]):.2f} | {cells}")


if __name__ == "__main__":
    main()
