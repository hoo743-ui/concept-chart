# -*- coding: utf-8 -*-
"""실험 K1: 코드 속 이름 (사용자 결정 11-11 '계속 진행해 재현율 올릴 수 있는 방법개선'의 ②).

    python experiments/2026-11-10-general-gate/codenames.py

정답 기준(11-10): 기술 제품·도구 이름은 개념. 그런데 소문자 라이브러리 이름(ipykernel, transformers)은 작은 LLM이 '아니다'라고 해 숨겨진다.
원 답변(answers.text)에서 그 낱말이 코드로 쓰인 자리를 찾는다 (LLM 없음):
- imp   : import X / from X import  (코드 블록 안)
- pip   : pip install X / conda install X / npm install X
- inline: `X` (인라인 코드, 그 칸 전체가 낱말)
관문이 숨긴 영문 낱말(규칙 unknown·likely)에 신호를 더한 안을 잰다. 개발 대화 정답에는 사용자 피드백(data/eval/feedback_gold.json)을 더한다.
"""
import json
import re
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cues as C  # noqa: E402

c2, g, ev, R = C.c2, C.g, C.ev, C.R


def code_cues(form, docs):
    f = re.escape(form)
    pats = {"imp": re.compile(rf"(?m)^\s*(?:import\s+{f}(?![\w])|from\s+{f}(?:\.\w+)*\s+import)"),
            "pip": re.compile(rf"(?:pip3?|conda|npm|uv pip)\s+install\s+(?:[-\w=.<>\[\]]+\s+)*{f}(?![\w-])"),
            "inline": re.compile(rf"`{f}`")}
    out = {k: 0 for k in pats}
    for d in docs:
        if form in d:
            for k, p in pats.items():
                out[k] += bool(p.search(d))
    return out


def main():
    g.load_lexicons(ev.LEX)
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
        print(f"\n{name}: 지금 {len(base)} 정밀도 {tp0 / max(1, len(base)):.3f} 재현율 {tp0 / max(1, pos):.3f}")
        hid = [x for x in items if x["form"] not in base and g.ASCII_FORM.fullmatch(x["form"]) and g.rule_verdict(x["form"], x.get("sents")) in ("unknown", "likely")]
        cu = {x["form"]: code_cues(x["form"], docs) for x in hid}
        for label, keep in (("imp·pip", lambda c: c["imp"] or c["pip"]), ("inline", lambda c: c["inline"]),
                            ("imp·pip·inline", lambda c: c["imp"] or c["pip"] or c["inline"]), ("inline 2번+", lambda c: c["inline"] >= 2)):
            add = [f for f, c in cu.items() if keep(c)]
            tp = tp0 + sum(gold[f] for f in add)
            n = len(base) + len(add)
            print(f"  +{label:15} 더함 {len(add):3} (개념 {sum(gold[f] for f in add)}) → 정밀도 {tp / max(1, n):.3f} 재현율 {tp / max(1, pos):.3f}"
                  + (f" | 개념: {', '.join(f for f in add if gold[f])[:160]} | 오탐: {', '.join(f for f in add if not gold[f])[:160]}" if add else ""), flush=True)


if __name__ == "__main__":
    main()
