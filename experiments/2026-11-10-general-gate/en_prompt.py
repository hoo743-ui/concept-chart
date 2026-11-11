# -*- coding: utf-8 -*-
"""실험 P1: 영어 낱말에만 정답 기준(11-10)에 맞춘 LLM 질문 (사용자 '계속 성능 개선 진행해', 11-11).

    python experiments/2026-11-10-general-gate/en_prompt.py

지금 질문(concept_gate.judge_prompt)은 '사람·나라·회사 이름은 false'라고 하는데, 정답 기준은 '기술 제품·회사·도구 이름, AI 모델 이름은 개념'이다.
실제 피드백에서 Ubuntu·qwen이 이 때문에 숨겨졌다. r8(질문 전체를 바꿈)은 한글 일상어까지 올려 실패했으므로, 이번에는 영어 표기 낱말에만 새 질문을 쓴다.
- 대상: 규칙이 판단 못 한 영어 낱말(unknown·likely) — 지금 LLM에게 묻는 낱말 중 영문만
- 새 질문이 true면 지금 관문의 llm 자리에 넣는다 (나머지 조건 — 위키백과 문서 등 — 은 그대로). 새로 true가 된 낱말은 위키백과 문서를 확인한다
- 예시 낱말이 평가 낱말과 겹치면 그 낱말은 채점에서 뺀다. 시험 세트는 열지 않는다
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cues as C  # noqa: E402

c2, g, ev, R = C.c2, C.g, C.ev, C.R
p = c2.p


def en_prompt(form, sentences):
    joined = "\n".join("- " + s for s in sentences[:3]) or "- (문장 없음)"
    return f"""아래 영어 표기 낱말이 학습 도구에서 따로 공부할 '이름이나 용어'인지 판단한다.
true: 기술 제품·서비스·소프트웨어·라이브러리·프로그래밍 언어·회사·AI 모델의 이름, 그리고 분야 전문 용어나 약어. 예: Terraform, Kotlin, Mistral, Elasticsearch, TCP.
false: 문장 속 흔한 영어 단어나 동사·형용사, 잘린 조각, 사람·나라 이름. 예: hello, simple, really, John, Paris.
낱말: {form}
문장:
{joined}
JSON으로만 답한다. is_term은 true 또는 false."""


def leaked_en(words):
    import re
    ex = " ".join(re.findall(r"예:([^\n]*)", en_prompt("@@", [])))
    return {w for w in words if re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", ex, re.I)}


def main():
    g.load_lexicons(ev.LEX)
    fb = json.loads((c2.EVAL / "feedback_gold.json").read_text(encoding="utf-8")) if (c2.EVAL / "feedback_gold.json").exists() else {}
    tag = p.tag(en_prompt)
    for name, (items, gold, D, sfx, db) in C.sets().items():
        gold = dict(gold)
        if name == "개발 대화":
            gold.update({w: b for w, b in fb.items() if w in gold})
        drop = R.leaked_all(gold) | leaked_en(gold)
        items = [x for x in items if x["form"] not in drop]
        c_old, _c_sp, wk = c2.prepare(items, D, sfx)
        target = lambda x: g.ASCII_FORM.fullmatch(x["form"]) and g.rule_verdict(x["form"], x.get("sents")) in ("unknown", "likely")
        c_en = p.ask(items, D / f"llm{sfx}_en_{tag}.json", en_prompt, g.JUDGE_SCHEMA, "is_term", target)
        merged = {f: (c_en[f] if f in c_en else v) for f, v in c_old.items()}
        merged.update({f: v for f, v in c_en.items() if f not in merged})
        wk2 = ev.sourced_all(items, merged, D / "wiki.json")
        pos = sum(gold[x["form"]] for x in items)
        def shown(c, w):
            return {x["form"] for x in items if g.final(g.rule_verdict(x["form"], x.get("sents")), c.get(x["form"]), w.get(x["form"]), g.lexicon_verdict(x["form"])) == "show"}
        base, new = shown(c_old, wk), shown(merged, wk2)
        for label, sel in (("지금", base), ("영어 새 질문", new)):
            tp = sum(gold[f] for f in sel)
            print(f"{name:10} {label:8} {len(sel):4} 정밀도 {tp / max(1, len(sel)):.3f} 재현율 {tp / max(1, pos):.3f}", flush=True)
        add, rem = sorted(new - base), sorted(base - new)
        print(f"   더함 {len(add)} (개념 {sum(gold[f] for f in add)}): {', '.join(f + ('' if gold[f] else '✗') for f in add)[:400]}")
        print(f"   뺌 {len(rem)} (개념 {sum(gold[f] for f in rem)}): {', '.join(f + ('' if gold[f] else '✗') for f in rem)[:300]}", flush=True)


if __name__ == "__main__":
    main()
