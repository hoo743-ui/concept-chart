# -*- coding: utf-8 -*-
"""실험 G1: 원어 병기 + 기술 용어집 (사용자 '계속 진행해줘 재현율 상승', 11-11).

    python experiments/2026-11-10-general-gate/gloss_terms.py

남은 놓친 개념의 큰 덩어리는 일상 뜻도 있는 개발 용어의 한국어 표기(대기열·어댑터·런타임·딕셔너리·호스팅·활성화)다. 작은 LLM이 거절한다.
AI 답변은 이런 말에 원어를 붙인다: '대기열(queue)', '런타임(runtime)'. 붙인 원어가 기술 용어집(kit/data/tech_terms.txt: MDN·Kubernetes 용어집)에 있으면 근거로 본다.
cues.py의 gloss(아무 영어나 붙음)는 개발 대화 6/39로 약했다. 이번에는 붙인 영어가 용어집에 있어야 한다. LLM·네트워크 없음.
"""
import json
import re
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cues as C  # noqa: E402

c2, g, ev, R = C.c2, C.g, C.ev, C.R


def glosses(form, docs):
    """낱말 바로 뒤 괄호 속 영어(첫 낱말 묶음)"""
    out = set()
    pat = re.compile(rf"(?<![가-힣A-Za-z]){re.escape(form)}\s?\(([A-Za-z][A-Za-z0-9 .+#\-]{{1,40}}?)[,;)/]")
    for d in docs:
        if form in d:
            out |= {m.group(1).strip() for m in pat.finditer(d)}
    return out


def main():
    g.load_lexicons(ev.LEX)
    T = g.terms()
    fb = json.loads((c2.EVAL / "feedback_gold.json").read_text(encoding="utf-8")) if (c2.EVAL / "feedback_gold.json").exists() else {}
    for name, (items, gold, D, sfx, db) in C.sets().items():
        gold = dict(gold)
        if name == "개발 대화":
            gold.update({w: b for w, b in fb.items() if w in gold})
        drop = R.leaked_all(gold)
        items = [x for x in items if x["form"] not in drop]
        c_old, _c_sp, wk = c2.prepare(items, D, sfx)
        docs = C.texts(db)
        pos = sum(gold[x["form"]] for x in items)
        base = {x["form"] for x in items if C.shown_now(x, c_old, wk)}
        tp0 = sum(gold[f] for f in base)
        hid = [x for x in items if x["form"] not in base and re.search(r"[가-힣]", x["form"])
               and g.rule_verdict(x["form"], x.get("sents")) != "reject" and g.lexicon_verdict(x["form"]) != "general"]
        any_g, tech_g = [], []
        for x in hid:
            gs = glosses(x["form"], docs)
            if gs:
                any_g.append(x["form"])
                if any(g.key(e) in T for e in gs):
                    tech_g.append(x["form"])
        print(f"\n{name}: 지금 {len(base)} 정밀도 {tp0 / max(1, len(base)):.3f} 재현율 {tp0 / max(1, pos):.3f}")
        for label, add in (("원어 병기(아무 영어)", any_g), ("원어가 기술 용어집에", tech_g)):
            tp, n = tp0 + sum(gold[f] for f in add), len(base) + len(add)
            print(f"  +{label:12} 더함 {len(add):3} (개념 {sum(gold[f] for f in add)}) → 정밀도 {tp / max(1, n):.3f} 재현율 {tp / max(1, pos):.3f}"
                  + (f" | 개념: {', '.join(f for f in add if gold[f])[:150]} | 오탐: {', '.join(f for f in add if not gold[f])[:150]}" if add and label.startswith("원어가") else ""), flush=True)


if __name__ == "__main__":
    main()
