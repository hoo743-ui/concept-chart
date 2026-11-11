# -*- coding: utf-8 -*-
"""규칙 실험 (사용자 결정 11-11 '규칙 실험 진행'): 보정 2차에서 찾은 오탐 두 곳을 좁힌다.

    python experiments/2026-11-10-general-gate/rules.py

- A 뒷조각: 영어 낱말(첫 글자만 대문자이거나 소문자)이 나온 모든 자리에서 바로 앞에 대문자로 시작하는 영어 낱말이 있으면
  여러 낱말 이름의 조각으로 보고 숨긴다 (Google Cloud의 Cloud, SQL Server의 Server, Loss Function의 Function). 약어(대문자만)는 대상 아님 (AWS ELB의 ELB).
- H 앞조각: 대문자만인 낱말이 나온 모든 자리에서 바로 뒤에 대문자만인 낱말이 있으면 숨긴다 (CROSS JOIN의 CROSS).
- B 일상어 확인: r7 칸(일상 뜻도 있는 낱말 + LLM 인정 + 위키백과 문서)은 앱의 두 번째 질문(concept_gate.everyday_prompt)이
  '일상어 아님'이라 할 때만 보여 준다 (없는 답은 물어서 저장).
A·H는 IT 조정용을 보고 만든 규칙이라 판단은 개발 대화·다른 세트에서 한다. 시험 세트(test)는 열지 않는다.
결과(DECISION_LOG D8): A+H 채택(0.6.2, kit/concept_gate.name_fragment), B 채택 안 함. 채택 뒤에는 관문에 A+H가 들어 있어 '지금'이 A+H와 같게 나온다.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import calibrate2 as c2  # noqa: E402

g, ev, p = c2.g, c2.ev, c2.p
ASK_ED = c2.hashlib.sha1(g.everyday_prompt("@@", ["@@"]).encode("utf-8")).hexdigest()[:10]
WORD = r"[A-Za-z][A-Za-z0-9.+#]*"


def occurrences(form, sents):
    for s in sents or ():
        for m in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(form)}(?![A-Za-z0-9])", s):
            yield s[:m.start()], s[m.end():]


def tail_fragment(form, sents):
    if not re.fullmatch(r"[A-Za-z][a-z]+", form):
        return False
    occ = list(occurrences(form, sents))
    return bool(occ) and all(re.search(rf"(?<![A-Za-z0-9])[A-Z][A-Za-z0-9.+#]* $", before) for before, _ in occ)


def head_fragment(form, sents):
    if not re.fullmatch(r"[A-Z]{2,}", form):
        return False
    occ = list(occurrences(form, sents))
    return bool(occ) and all(re.match(r" [A-Z]{2,}(?![A-Za-z0-9])", after) for _, after in occ)


def leaked_all(words):
    t = c2.examples_text() + " " + " ".join(m.group(1) for m in re.finditer(r"예:([^\n]*)", g.everyday_prompt("@@", [])))
    return {w for w in words if len(w) >= 2 and re.search(rf"(?<![가-힣A-Za-z]){re.escape(w)}(?![가-힣A-Za-z])", t)}


def r7(x, c_old, wk):
    f = x["form"]
    return g.rule_verdict(f, x.get("sents")) == "unknown" and g.lexicon_verdict(f) == "mixed" and c_old.get(f) is True and bool(wk.get(f))


def show(x, c_old, wk, ed, A, H, B):
    f, s = x["form"], x.get("sents")
    r = g.rule_verdict(f, s)
    if r == "accept" and ((A and tail_fragment(f, s)) or (H and head_fragment(f, s))):
        return False
    if B and r7(x, c_old, wk):
        return ed.get(f) is False
    return g.final(r, c_old.get(f), wk.get(f), g.lexicon_verdict(f)) == "show"


VARIANTS = {"지금": (0, 0, 0), "A": (1, 0, 0), "A+H": (1, 1, 0), "B": (0, 0, 1), "A+B": (1, 0, 1), "A+H+B": (1, 1, 1)}


def main():
    g.load_lexicons(ev.LEX)
    fx = c2.fixes()
    sets = {"조정용": c2.general_set("조정용", c2.EVAL / "general", "tune", fx, "조정용"),
            "예전 holdout": c2.general_set("예전 holdout", c2.EVAL / "general", "holdout", fx, "예전 holdout"),
            "새 분야": c2.general_set("새 분야", c2.EVAL / "fresh", "holdout", fx, "새 분야"),
            "IT 조정용": c2.general_set("IT 조정용", c2.EVAL / "tune2", "tune", fx, "IT 조정용"),
            "개발 대화": c2.dev_set(fx)}
    out = {}
    for name, (items, gold, D, sfx) in sets.items():
        drop = leaked_all(gold)
        items = [x for x in items if x["form"] not in drop]
        c_old, _c_sp, wk = c2.prepare(items, D, sfx)
        ed = p.ask(items, D / f"everyday{sfx}_{ASK_ED}.json", g.everyday_prompt, g.EVERYDAY_SCHEMA, "everyday", lambda x: r7(x, c_old, wk))
        pos = sum(gold[x["form"]] for x in items)
        print(f"\n{name}: 낱말 {len(items)} 개념 {pos} (예시와 겹쳐 뺀 낱말 {sorted(drop)})", flush=True)
        base = {x["form"] for x in items if show(x, c_old, wk, ed, 0, 0, 0)}
        out[name] = {}
        for v, (A, H, B) in VARIANTS.items():
            sel = {x["form"] for x in items if show(x, c_old, wk, ed, A, H, B)}
            tp = sum(gold[f] for f in sel)
            out[name][v] = (len(sel), tp / max(1, len(sel)), tp / max(1, pos))
            gone = sorted(base - sel)
            print(f"  {v:6} {len(sel):4} 정밀도 {tp / max(1, len(sel)):.3f} 재현율 {tp / max(1, pos):.3f}"
                  + (f" | 빠진 개념 {[f for f in gone if gold[f]]} 빠진 오탐 {len([f for f in gone if not gold[f]])}" if gone else ""), flush=True)
    (HERE / "rules_result.json").write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))


if __name__ == "__main__":
    main()
