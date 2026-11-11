# -*- coding: utf-8 -*-
"""실험 C1: 답변 속 '정의 표시' 신호로 재현율 올리기 (사용자 결정 11-11 '1,2,3방안 실행'의 1).

    python experiments/2026-11-10-general-gate/cues.py

AI 답변은 중요한 용어를 정해진 모양으로 쓴다. 문장 조각(mentions.snippet)에서는 마크다운이 지워지므로 원 답변(answers.text)에서 찾는다.
- bold  : **…낱말…** (굵게 쓴 칸이 30자 이하)
- head  : 제목 줄(#)이나 목록 머리 '- **낱말**:' / '1. 낱말:' 에 나옴
- gloss : 낱말(영어…) 또는 낱말 (영어…) — 한국어 용어에 영어 원어를 붙임
- define: '낱말이란' · '낱말란' · 줄 머리의 '낱말은/는 …'
LLM을 쓰지 않는다. 세트·정답은 calibrate2와 같고 시험 세트는 열지 않는다.
먼저 신호별로 '신호가 붙은 낱말 중 개념 비율'을 보고, 관문이 숨긴 낱말에 신호를 더한 안을 잰다.
"""
import collections
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

c2, g, ev = R.c2, R.g, R.ev
LIVE = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
KINDS = ("bold", "head", "gloss", "define")


def texts(db):
    con = sqlite3.connect(f"file:{pathlib.Path(db).as_posix()}?mode=ro", uri=True)
    return [r[0] for r in con.execute("SELECT text FROM answers") if r[0]]


def cues(form, docs):
    """→ {신호: 그 신호가 붙은 답변 수}"""
    f = re.escape(form)
    pats = {
        "bold": re.compile(rf"\*\*[^*\n]{{0,28}}?(?<![가-힣A-Za-z]){f}[^*\n]{{0,28}}?\*\*"),
        "head": re.compile(rf"(?m)^(?:#{{1,6}}\s.*(?<![가-힣A-Za-z]){f}|\s*(?:[-*]|\d+\.)\s+(?:\*\*)?{f}(?:\*\*)?\s*[:：(])"),
        "gloss": re.compile(rf"(?<![가-힣A-Za-z]){f}\s?\([A-Za-z]"),
        "define": re.compile(rf"(?m)(?<![가-힣A-Za-z]){f}(?:이란|란|이라는 것은|라는 것은)|^\s*(?:[-*]\s+)?(?:\*\*)?{f}(?:\*\*)?(?:은|는)\s"),
    }
    out = collections.Counter()
    for d in docs:
        if form not in d:
            continue
        for k, p in pats.items():
            if p.search(d):
                out[k] += 1
    return out


def sets():
    fx = c2.fixes()
    return {"조정용": (*c2.general_set("조정용", c2.EVAL / "general", "tune", fx, "조정용"), c2.EVAL / "general" / "idx.sqlite"),
            "IT 조정용": (*c2.general_set("IT 조정용", c2.EVAL / "tune2", "tune", fx, "IT 조정용"), c2.EVAL / "tune2" / "idx.sqlite"),
            "예전 holdout": (*c2.general_set("예전 holdout", c2.EVAL / "general", "holdout", fx, "예전 holdout"), c2.EVAL / "general" / "idx.sqlite"),
            "새 분야": (*c2.general_set("새 분야", c2.EVAL / "fresh", "holdout", fx, "새 분야"), c2.EVAL / "fresh" / "idx.sqlite"),
            "개발 대화": (*c2.dev_set(fx), LIVE)}


def shown_now(x, c_old, wk):
    f = x["form"]
    return g.final(g.rule_verdict(f, x.get("sents")), c_old.get(f), wk.get(f), g.lexicon_verdict(f)) == "show"


def variant(x, c_old, wk, cu, name):
    """지금 관문에 더하는 안. 일상 뜻만(general)·규칙 거절은 그대로 숨긴다"""
    if shown_now(x, c_old, wk):
        return True
    f = x["form"]
    r, lex = g.rule_verdict(f, x.get("sents")), g.lexicon_verdict(f)
    if r == "reject" or lex == "general":
        return False
    strong = cu["bold"] + cu["head"] + cu["gloss"] + cu["define"]
    if name == "C-any":            # 신호 하나라도
        return strong >= 1
    if name == "C-wiki":           # 신호 + 위키백과 문서
        return strong >= 1 and bool(wk.get(f))
    if name == "C-llm":            # 신호 + LLM 인정 (위키백과 문서가 없어 숨긴 낱말)
        return strong >= 1 and c_old.get(f) is True
    if name == "C-2":              # 서로 다른 신호 둘 이상, 또는 두 답변 이상에서 신호
        return sum(1 for k in KINDS if cu[k]) >= 2 or max(cu.values(), default=0) >= 2
    if name == "C-2wiki":
        return (sum(1 for k in KINDS if cu[k]) >= 2 or max(cu.values(), default=0) >= 2) and (bool(wk.get(f)) or c_old.get(f) is True)
    return False


VARIANTS = ("지금", "C-any", "C-wiki", "C-llm", "C-2", "C-2wiki")


def main():
    g.load_lexicons(ev.LEX)
    per = collections.defaultdict(lambda: [0, 0])
    for name, (items, gold, D, sfx, db) in sets().items():
        drop = R.leaked_all(gold)
        items = [x for x in items if x["form"] not in drop]
        c_old, _c_sp, wk = c2.prepare(items, D, sfx)
        docs = texts(db)
        cu = {x["form"]: cues(x["form"], docs) for x in items}
        hidden = [x for x in items if not shown_now(x, c_old, wk)]
        for x in hidden:
            for k in KINDS:
                if cu[x["form"]][k]:
                    per[(name, k)][0] += gold[x["form"]]
                    per[(name, k)][1] += 1
        pos = sum(gold[x["form"]] for x in items)
        print(f"\n{name}: 낱말 {len(items)} 개념 {pos}, 답변 {len(docs)}개. 숨긴 낱말 중 신호별 개념 비율: "
              + ", ".join(f"{k} {per[(name, k)][0]}/{per[(name, k)][1]}" for k in KINDS), flush=True)
        base = {x["form"] for x in items if shown_now(x, c_old, wk)}
        for v in VARIANTS:
            sel = {x["form"] for x in items if v == "지금" and x["form"] in base or v != "지금" and variant(x, c_old, wk, cu[x["form"]], v)}
            tp = sum(gold[f] for f in sel)
            add = sorted(sel - base)
            print(f"  {v:8} {len(sel):4} 정밀도 {tp / max(1, len(sel)):.3f} 재현율 {tp / max(1, pos):.3f}"
                  + (f" | 더함 {sum(gold[f] for f in add)}/{len(add)}, 오탐: {', '.join(f for f in add if not gold[f])[:240]}" if add else ""), flush=True)


if __name__ == "__main__":
    main()
