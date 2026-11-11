# -*- coding: utf-8 -*-
"""실험 V5: 분야 힌트 질문을 사용자 정답 기준(11-10)으로 다시 잰다 (사용자 결정 11-11 '1,2,3 싹다 진행').

    python experiments/2026-11-10-general-gate/fieldhint2.py

V4(fieldhint.py)는 정답 기준을 정하기 전에 '상속·혈압·징역이 통과한다'는 이유로 버렸다. 지금 기준에서는 셋 다 개념이다.
놓친 개념이 가장 많은 칸은 '일상 뜻도 있는 낱말(mixed) + LLM이 아니라 함'이라 이번에는 그 칸에도 힌트를 준다.
- 묻는 낱말: 규칙이 판단 못 함 + 분야 사전에 전문 뜻이 있음(special·mixed) + 지금 질문(judge_prompt)이 아니라 함 + 사전에 분야가 있음
- 힌트 질문: judge_prompt + "국어사전에는 이 낱말이 'X' 분야의 전문 용어로만(special)/로도(mixed) 실려 있다". special 문장은 V4와 같다(저장된 답을 다시 쓴다)
- 안 (모두 지금 관문에 더한다):
  S  = 전문 뜻만 + 힌트 인정 + 위키백과 문서 (V4)
  M  = 일상 뜻도 + 힌트 인정 + 위키백과 문서
  S+M
  Sw+M = 전문 뜻만은 위키백과 조건 없이 + M
- 세트: 조정용·IT 조정용(맞추는 쪽), 예전 holdout·새 분야(이미 본 세트), 개발 대화(실제 사용, 판단 기준). 시험 세트는 열지 않는다.
"""
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

c2, g, ev = R.c2, R.g, R.ev
sys.path.insert(0, str(c2.ROOT / "kit"))
import fields  # noqa: E402
import fieldhint as v4  # noqa: E402


def hint_prompt(form, sentences, flds, lex):
    if lex == "special":
        return v4.hint_prompt(form, sentences, flds)
    base = g.judge_prompt(form, sentences)
    hint = f"참고: 국어사전에는 이 낱말이 일상 뜻과 함께 '{', '.join(flds[:3])}' 분야의 전문 용어로도 실려 있다. 이 대화에서 그 분야의 뜻으로 쓰였는지 본다.\n"
    return base.replace("낱말: ", hint + "낱말: ", 1)


ASK_M = hashlib.sha1(hint_prompt("@@", ["@@"], ["@@"], "mixed").encode("utf-8")).hexdigest()[:10]


def target(x, c_old):
    f = x["form"]
    return (g.rule_verdict(f, x.get("sents")) == "unknown" and g.lexicon_verdict(f) in ("special", "mixed")
            and c_old.get(f) is False and bool(fields.fields_of(f)))


def ask(items, D, sfx, c_old):
    """special은 V4 캐시(같은 질문 문장), mixed는 새 캐시"""
    out = {}
    for lex, path in (("special", D / f"fieldhint{sfx}_{v4.ASK}.json"), ("mixed", D / f"fieldhint{sfx}_m_{ASK_M}.json")):
        cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        todo = [x for x in items if target(x, c_old) and g.lexicon_verdict(x["form"]) == lex and x["form"] not in cache]
        client = None
        if todo:
            client = v4.llm.make("ollama:qwen3:4b")
            assert client.available(), "LLM 없음"
        for i, x in enumerate(todo, 1):
            ev.gentle()
            cache[x["form"]] = bool(client.json(hint_prompt(x["form"], x.get("sents") or [], fields.fields_of(x["form"]), lex), g.JUDGE_SCHEMA, 20)["is_term"])
            if i % 20 == 0:
                path.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
                print(path.name, i, "/", len(todo), flush=True)
        path.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
        out.update({k: v for k, v in cache.items()})
    return out


def show(x, c_old, wk, fh, variant):
    f = x["form"]
    r, lex = g.rule_verdict(f, x.get("sents")), g.lexicon_verdict(f)
    if g.final(r, c_old.get(f), wk.get(f), lex) == "show":
        return True
    if variant == "지금" or not target(x, c_old) or fh.get(f) is not True:
        return False
    if lex == "special":
        return variant in ("S", "S+M") and bool(wk.get(f)) or variant == "Sw+M"
    return variant in ("M", "S+M", "Sw+M") and bool(wk.get(f))


VARIANTS = ("지금", "S", "M", "S+M", "Sw+M")


def main():
    g.load_lexicons(ev.LEX)
    if not fields._open():
        sys.exit("분야 표가 있는 사전이 없습니다: python dev.py lexicon")
    fx = c2.fixes()
    sets = {"조정용": c2.general_set("조정용", c2.EVAL / "general", "tune", fx, "조정용"),
            "IT 조정용": c2.general_set("IT 조정용", c2.EVAL / "tune2", "tune", fx, "IT 조정용"),
            "예전 holdout": c2.general_set("예전 holdout", c2.EVAL / "general", "holdout", fx, "예전 holdout"),
            "새 분야": c2.general_set("새 분야", c2.EVAL / "fresh", "holdout", fx, "새 분야"),
            "개발 대화": c2.dev_set(fx)}
    res = {}
    for name, (items, gold, D, sfx) in sets.items():
        drop = R.leaked_all(gold)
        items = [x for x in items if x["form"] not in drop]
        c_old, _c_sp, wk = c2.prepare(items, D, sfx)
        fh = ask(items, D, sfx, c_old)
        pos = sum(gold[x["form"]] for x in items)
        print(f"\n{name}: 낱말 {len(items)} 개념 {pos}, 힌트 질문 대상 {sum(target(x, c_old) for x in items)}", flush=True)
        base = {x["form"] for x in items if show(x, c_old, wk, fh, "지금")}
        res[name] = {}
        for v in VARIANTS:
            sel = {x["form"] for x in items if show(x, c_old, wk, fh, v)}
            tp = sum(gold[f] for f in sel)
            res[name][v] = [len(sel), round(tp / max(1, len(sel)), 3), round(tp / max(1, pos), 3)]
            add = sorted(sel - base)
            print(f"  {v:5} {len(sel):4} 정밀도 {tp / max(1, len(sel)):.3f} 재현율 {tp / max(1, pos):.3f}"
                  + (f" | 더한 개념 {sum(gold[f] for f in add)}/{len(add)}, 더한 오탐: {', '.join(f for f in add if not gold[f])[:300]}" if add else ""), flush=True)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
