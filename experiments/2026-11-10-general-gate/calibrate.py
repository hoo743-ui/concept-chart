# -*- coding: utf-8 -*-
"""보정 (사용자 결정 11-10: 정밀도 하한 0.8): 신호 조합(칸)별 정답 비율을 조정용 세트에서 세고, 비율이 높은 칸부터 열어
조정용 정밀도가 0.8 이상인 안에서 보여 주는 개념이 가장 많아지게 한다. 같은 칸 표를 개발 대화·새 분야 세트에 그대로 적용해 버티는지 본다.

    python experiments/2026-11-10-general-gate/calibrate.py

- 규칙이 확신한 낱말(accept·reject)은 그대로 둔다. 칸을 나누는 신호: 규칙(likely = 기술 용어집 / unknown), 분야 사전(special·mixed·general·없음),
  지금 LLM 질문, 새 LLM 질문(prompt_r8, 전문 뜻만 있는 낱말에만 물었다), 이름이 맞는 위키백과 문서.
- 위키백과는 LLM이 인정했거나 전문 뜻만 있는 낱말만 확인했다. 그래서 '문서 없음'에는 '확인 안 함'도 섞여 있다.
- 칸 정답 비율은 (맞음 + 1) / (수 + 2)로 줄여 본다 (작은 칸이 우연히 1.0이 되지 않게). 조정용에서 MIN_N개 미만인 칸은 열지 않는다.
- LLM을 새로 부르지 않는다 (캐시만). 정답은 review_sheet_filled.csv를 반영한 사용자 기준.
"""
import collections
import csv
import json
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prompt_r8 as p  # noqa: E402

g, ev, rs, ROOT = p.g, p.ev, p.rs, p.ROOT
FLOOR = 0.8
MIN_N = 3


def data():
    with open(ROOT / "data" / "eval" / "review_sheet_filled.csv", encoding="utf-8-sig", newline="") as f:
        fixes = {(r[0], r[1]): r[4] == "1" for r in list(csv.reader(f))[1:] if r[4] in ("0", "1")}
    dirs = {"조정용": ROOT / "data" / "eval" / "general", "개발 대화": ev.DEV_D, "새 분야": ROOT / "data" / "eval" / "fresh"}
    J = p.tag(p.judge_prompt)
    out = {}
    for name, (items, gold, c_old, wk, _ed, _fh) in rs.sets().items():
        sfx = "_dev" if name == "개발 대화" else ""
        path = dirs[name] / f"llm{sfx}_r8_{J}.json"
        c_new = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        gold = dict(gold, **{w: b for (s, w), b in fixes.items() if s == name and w in gold})
        out[name] = (items, gold, c_old, c_new, wk)
    return out


def cell(x, c_old, c_new, wk):
    """None = 규칙이 확신 (accept → 보여 줌, reject → 숨김). 그 밖에는 신호 조합"""
    f = x["form"]
    r = g.rule_verdict(f, x.get("sents"))
    if r in ("accept", "reject"):
        return None
    lex = g.lexicon_verdict(f) or "none"
    new = c_new.get(f) if lex == "special" else None              # 새 질문은 전문 뜻만 있는 낱말에만 썼다
    return (r, lex, c_old.get(f), new, bool(wk.get(f)))


def fixed(x):
    return g.rule_verdict(x["form"], x.get("sents")) == "accept"


def table(items, gold, c_old, c_new, wk):
    t = collections.defaultdict(lambda: [0, 0])
    for x in items:
        k = cell(x, c_old, c_new, wk)
        if k is not None:
            t[k][0] += gold[x["form"]]
            t[k][1] += 1
    return t


def fit(items, gold, c_old, c_new, wk):
    """비율 높은 칸부터 열며 정밀도 FLOOR 이상인 가장 큰 칸 묶음"""
    t = table(items, gold, c_old, c_new, wk)
    order = sorted((k for k, (tp, n) in t.items() if n >= MIN_N), key=lambda k: -(t[k][0] + 1) / (t[k][1] + 2))
    base_tp = sum(gold[x["form"]] for x in items if fixed(x))
    base_n = sum(1 for x in items if fixed(x))
    best, tp, n = [], base_tp, base_n
    for i, k in enumerate(order, 1):
        tp, n = tp + t[k][0], n + t[k][1]
        if tp / n >= FLOOR:
            best = order[:i]
    return set(best), t


def score(items, gold, c_old, c_new, wk, opened):
    pos = sum(gold[x["form"]] for x in items)
    shown = [x["form"] for x in items if fixed(x) or cell(x, c_old, c_new, wk) in opened]
    tp = sum(gold[w] for w in shown)
    return len(shown), tp / max(1, len(shown)), tp / max(1, pos), [w for w in shown if not gold[w]]


def current(items, gold, c_old, wk):
    pos = sum(gold[x["form"]] for x in items)
    shown = [x["form"] for x in items if g.final(g.rule_verdict(x["form"], x.get("sents")), c_old.get(x["form"]), wk.get(x["form"]), g.lexicon_verdict(x["form"])) == "show"]
    tp = sum(gold[w] for w in shown)
    return len(shown), tp / max(1, len(shown)), tp / max(1, pos)


def main():
    g.load_lexicons(ev.LEX)
    d = data()
    opened, t = fit(*d["조정용"])
    print(f"조정용에서 연 칸 {len(opened)}개 (칸: 규칙, 분야 사전, 지금 질문, 새 질문, 위키백과 문서 → 조정용 맞음/수)")
    for k in sorted(opened, key=lambda k: -(t[k][0] + 1) / (t[k][1] + 2)):
        print("  ", k, f"{t[k][0]}/{t[k][1]}")
    for name, (items, gold, c_old, c_new, wk) in d.items():
        n0, p0, r0 = current(items, gold, c_old, wk)
        n1, p1, r1, wrong = score(items, gold, c_old, c_new, wk, opened)
        print(f"{name:6} 지금 관문(기본 목록) 보여 줌 {n0:3} 정밀도 {p0:.3f} 재현율 {r0:.3f} | 보정 보여 줌 {n1:3} 정밀도 {p1:.3f} 재현율 {r1:.3f}")
        print("   보정 오탐:", ", ".join(sorted(wrong))[:500])


if __name__ == "__main__":
    main()
