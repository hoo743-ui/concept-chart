# -*- coding: utf-8 -*-
"""실험 X1: '더 보기'(질문 묶음의 접힌 칸) 넓히기 (사용자 결정 11-11 '1,2,3방안 실행'의 3).

    python experiments/2026-11-10-general-gate/more_view.py

기본 목록은 그대로 두고(정밀도 하한 0.8, 11-10 사용자 결정), 접힌 '더 보기'에만 낱말을 더한다. 저장된 답만 쓴다 (LLM·네트워크 없음).
- 지금 더 보기 = gate.rescue (전문 뜻만 + LLM 아니라 함 + 위키백과 문서 + 두 번째 질문 '일상어 아님'). 두 번째 질문 답이 없는 낱말은 더하지 않은 것으로 센다
- S = 전문 뜻만 + LLM 아니라 함 + 분야 힌트 질문 인정 + 위키백과 문서 (fieldhint2.py의 S)
- C = 답변 속 정의 표시 신호 + LLM 인정 (cues.py의 C-llm)
보는 값: 더 보기 낱말 수와 그중 개념 비율, 기본 목록 + 더 보기의 재현율
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cues as C  # noqa: E402
import fieldhint2 as F  # noqa: E402

c2, g, ev, R = C.c2, C.g, C.ev, C.R


def load(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main():
    g.load_lexicons(ev.LEX)
    for name, (items, gold, D, sfx, db) in C.sets().items():
        drop = R.leaked_all(gold)
        items = [x for x in items if x["form"] not in drop]
        c_old, _c_sp, wk = c2.prepare(items, D, sfx)
        ed = load(D / f"everyday{sfx}_{R.ASK_ED}.json")
        fh = {**load(D / f"fieldhint{sfx}_{F.v4.ASK}.json"), **load(D / f"fieldhint{sfx}_m_{F.ASK_M}.json")}
        docs = C.texts(db)
        pos = sum(gold[x["form"]] for x in items)
        base = {x["form"] for x in items if C.shown_now(x, c_old, wk)}
        cand = [x for x in items if x["form"] not in base and g.rule_verdict(x["form"], x.get("sents")) != "reject" and g.lexicon_verdict(x["form"]) != "general"]
        now, S, Cc = set(), set(), set()
        for x in cand:
            f = x["form"]
            r, lex = g.rule_verdict(f, x.get("sents")), g.lexicon_verdict(f)
            if g.rescue(r, c_old.get(f), wk.get(f), lex, ed.get(f)):
                now.add(f)
            if F.target(x, c_old) and lex == "special" and fh.get(f) is True and wk.get(f):
                S.add(f)
            if c_old.get(f) is True:
                cu = C.cues(f, docs)
                if sum(cu.values()) >= 1:
                    Cc.add(f)
        tp0 = sum(gold[f] for f in base)
        print(f"\n{name}: 기본 목록 {len(base)}개 (정밀도 {tp0 / max(1, len(base)):.3f}, 재현율 {tp0 / max(1, pos):.3f})")
        for label, extra in (("지금 더 보기", now), ("+S", now | S), ("+C", now | Cc), ("+S+C", now | S | Cc)):
            te = sum(gold[f] for f in extra)
            print(f"  {label:10} 더 보기 {len(extra):3}개 중 개념 {te} ({te / max(1, len(extra)):.2f}) → 기본+더 보기 재현율 {(tp0 + te) / max(1, pos):.3f}"
                  + (f" | 오탐: {', '.join(sorted(f for f in extra if not gold[f]))[:200]}" if label == "+S+C" else ""), flush=True)


if __name__ == "__main__":
    main()
