# -*- coding: utf-8 -*-
"""실험 K2: 대문자가 들어간 영어 낱말은 위키백과 문서에 같은 대소문자로 나올 때만 두 번째 근거로 (밤 작업 11-12, 0.7.5 실제 사용에서 찾은 오탐).

    python experiments/2026-11-10-general-gate/case_check.py

0.7.5(영어 새 질문) 뒤 실제 공부 목록에 Design·Export·Dark·Authenticate·CHANGELOG가 들어왔다. 위키백과 문서가 그 말의 일반 명사 문서였다:
'디자인(design)은', '수출(輸出, export)은', 'A changelog is'. 제품 이름은 문서가 이름을 그대로 쓴다: '디스코드(영어: Discord)', '우분투(Ubuntu'.
- 규칙: 규칙이 판단 못 한(unknown) 영어 낱말 중 대문자가 들어간 것은, 위키백과 정의 문장에 그 표기가 대소문자까지 같게 있어야 sourced로 센다. 소문자 낱말은 그대로
- 평가 세트는 위키백과 확인을 참/거짓으로만 저장했으므로, 대상 낱말의 정의 문장을 serve.fetch_note로 다시 받아 defs_case.json에 저장한다 (사이트 규칙대로 천천히)
- 정밀도·재현율은 0.7.5 관문(영어 새 질문 + 이름 조각 거르기 + 코드 이름) 기준
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import en_prompt as E  # noqa: E402

C, c2, g, ev, R, p = E.C, E.c2, E.g, E.ev, E.R, E.p
sys.path.insert(0, str(c2.ROOT / "kit"))
import serve  # noqa: E402


def case_ok(form, definition):
    """대문자가 들어간 낱말: 정의에 같은 표기(대소문자 그대로)가 낱말로 있어야 한다"""
    if not re.search(r"[A-Z]", form):
        return True
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(form)}(?![A-Za-z0-9])", definition or ""))


def main():
    g.load_lexicons(ev.LEX)
    fb = json.loads((c2.EVAL / "feedback_gold.json").read_text(encoding="utf-8"))
    tag = p.tag(g.en_judge_prompt)
    for name, (items, gold, D, sfx, db) in C.sets().items():
        gold = dict(gold)
        if name == "개발 대화":
            gold.update({w: b for w, b in fb.items() if w in gold})
        drop = R.leaked_all(gold) | E.leaked_en(gold)
        items = [x for x in items if x["form"] not in drop]
        c_old, _, wk = c2.prepare(items, D, sfx)
        cen = D / f"llm{sfx}_en_{tag}.json"
        c = {**c_old, **(json.loads(cen.read_text(encoding="utf-8")) if cen.exists() else {})}
        wk = json.loads((D / "wiki.json").read_text(encoding="utf-8"))
        docs = C.texts(db)
        code = {x["form"]: g.code_name(x["form"], [t for t in docs if x["form"] in t]) for x in items if g.ASCII_FORM.fullmatch(x["form"])}
        path = D / f"defs_case{sfx}.json"
        defs = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        need = [x["form"] for x in items if wk.get(x["form"]) and g.ASCII_FORM.fullmatch(x["form"]) and re.search(r"[A-Z]", x["form"])
                and g.rule_verdict(x["form"], x.get("sents")) == "unknown" and x["form"] not in defs]
        for i, f in enumerate(need, 1):
            try:
                defs[f] = serve.fetch_note(f)[0]
            except Exception as e:  # noqa: BLE001 — 네트워크 오류는 저장하지 않고 다음에
                print("조회 실패", f, type(e).__name__, flush=True)
            if i % 10 == 0:
                path.write_bytes(json.dumps(defs, ensure_ascii=False).encode("utf-8"))
        path.write_bytes(json.dumps(defs, ensure_ascii=False).encode("utf-8"))
        pos = sum(gold[x["form"]] for x in items)

        def shown(strict):
            out = set()
            for x in items:
                f, s = x["form"], x.get("sents")
                r = g.rule_verdict(f, s)
                src = wk.get(f)
                if strict and src and r == "unknown" and g.ASCII_FORM.fullmatch(f) and f in defs:
                    src = case_ok(f, defs[f])
                if g.final(r, c.get(f), src, g.lexicon_verdict(f), code.get(f)) == "show":
                    out.add(f)
            return out
        a, b = shown(False), shown(True)
        for label, sel in (("0.7.5", a), ("+대소문자 확인", b)):
            tp = sum(gold[f] for f in sel)
            print(f"{name:10} {label:10} {len(sel):4} 정밀도 {tp / max(1, len(sel)):.3f} 재현율 {tp / max(1, pos):.3f}", flush=True)
        print("   빠진 낱말:", ", ".join(f + ("" if gold[f] else "✗") for f in sorted(a - b)), flush=True)


if __name__ == "__main__":
    main()
