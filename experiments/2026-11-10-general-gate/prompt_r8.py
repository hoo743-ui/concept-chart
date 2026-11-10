# -*- coding: utf-8 -*-
"""실험 r8: LLM 질문 두 개(judge_prompt·everyday_prompt)를 사용자 정답 기준(11-10, DECISION_LOG D8 '정답 기준')에 맞게 고치면 나아지나.

    python experiments/2026-11-10-general-gate/prompt_r8.py

- 새 질문은 이 파일에만 있다 (채택 전에는 kit/concept_gate.py를 바꾸지 않는다).
- 정답: data/eval/review_sheet_filled.csv의 사용자 판단을 반영한 정답 (review_sheet.py --apply와 같은 채점).
- 묻는 낱말: evaluate.judge_all과 같다 (규칙이 확신하지 못하고, 분야 사전에 일상 뜻만 있는 낱말이 아닌 것). 위키백과 문서 확인은 evaluate.sourced_all 그대로.
- 예시 낱말이 세 세트(조정용·개발 대화·새 분야)의 낱말과 겹치면 멈춘다.
"""
import csv
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as ev  # noqa: E402
import review_sheet as rs  # noqa: E402

g, llm = ev.g, ev.llm
ROOT = ev.ROOT


def judge_prompt(form, sentences):
    joined = "\n".join("- " + s for s in sentences[:3]) or "- (문장 없음)"
    return f"""너는 학습 도구의 심사관이다. 아래 낱말이 '어떤 분야의 용어로서 따로 공부해 둘 만한 개념'인지 판단한다. 분야는 가리지 않는다.
true: 의학, 법률, 경제, 과학, 언어, 컴퓨터, 인공지능 같은 분야의 용어. 일상에서 흔히 듣는 말이어도 그 분야의 용어면 true다. 개념, 이론, 제도, 물질, 현상, 질병, 기술 이름, 학문 이름, 역사적 사건 이름을 포함한다. 예: 리베이스, 역전파, 기회비용, 내력벽, 삼투압, 판례, 위염, 이자율, 엽록소, 지질학, 병자호란.
false: 분야와 상관없이 두루 쓰는 말, 누구나 쓰는 컴퓨터 사용 말, 생활 속 물건이나 장소 이름, 사람·나라·회사·제품·별 이름, 단위, 잘린 조각, 형용사꼴(~적), 일반적인 '~성' 꼴. 예: 방법, 문제, 내용, 경우, 부분, 설명, 바탕화면, 비밀번호, 냉장고, 뉴턴, 킬로그램, 편리성.
낱말: {form}
문장:
{joined}
JSON으로만 답한다. is_term은 true 또는 false."""


def everyday_prompt(form, sentences):
    joined = "\n".join("- " + s for s in sentences[:2]) or "- (문장 없음)"
    return f"""아래 낱말이 어떤 분야의 용어가 아니라 생활 속 낱말인지 판단한다.
true: 분야와 상관없이 누구나 쓰는 생활 낱말, 생활 속 물건이나 장소 이름, 사람·나라·도시 이름. 예: 칫솔, 우산, 냉장고, 편의점, 버스.
false: 의학, 법률, 경제, 과학, 언어, 컴퓨터 같은 분야의 용어. 흔히 듣는 말이어도 분야 용어면 false다. 학문 이름과 역사적 사건 이름도 false다. 예: 삼투압, 판례, 내력벽, 위염, 이자율.
낱말: {form}
문장:
{joined}
JSON으로만 답한다. everyday는 true 또는 false."""


def tag(fn):
    return hashlib.sha1(fn("@@", ["@@"]).encode("utf-8")).hexdigest()[:10]


def examples(fn):
    return " ".join(m.group(1) for m in re.finditer(r"예:([^\n]*)", fn("@@", [])))


def leak_guard(all_words):
    text = examples(judge_prompt) + " " + examples(everyday_prompt)
    leaked = sorted(w for w in all_words if len(w) >= 2 and re.search(rf"(?<![가-힣A-Za-z]){re.escape(w)}(?![가-힣A-Za-z])", text))
    if leaked:
        sys.exit(f"새 질문 예시에 평가 낱말이 있습니다: {leaked}")


def ask(items, path, fn, schema, key, want):
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo = [x for x in items if x["form"] not in cache and want(x)]
    client = llm.make("ollama:qwen3:4b") if todo else None
    if client:
        assert client.available(), "LLM 없음"
    for i, x in enumerate(todo, 1):
        ev.gentle()
        cache[x["form"]] = bool(client.json(fn(x["form"], x.get("sents") or []), schema, 20)[key])
        if i % 25 == 0:
            path.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
            print(path.name, i, "/", len(todo), flush=True)
    path.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
    return cache


def judged(x):
    r = g.rule_verdict(x["form"], x.get("sents"))
    return r not in ("accept", "reject") and not (r == "unknown" and g.lexicon_verdict(x["form"]) == "general")


def verdict(x, c, wk, ed, rescue=True):
    f = x["form"]
    r, lex = g.rule_verdict(f, x.get("sents")), g.lexicon_verdict(f)
    v = g.final(r, c.get(f), wk.get(f), lex)
    if v != "show" and rescue and g.rescue(r, c.get(f), wk.get(f), lex, ed.get(f)):
        v = "show"
    return v


def main():
    g.load_lexicons(ev.LEX)
    sets = rs.sets()
    leak_guard({x["form"] for items, *_ in sets.values() for x in items})
    with open(ROOT / "data" / "eval" / "review_sheet_filled.csv", encoding="utf-8-sig", newline="") as f:
        fixes = {(r[0], r[1]): r[4] == "1" for r in list(csv.reader(f))[1:] if r[4] in ("0", "1")}
    J, E = tag(judge_prompt), tag(everyday_prompt)
    dirs = {"조정용": ROOT / "data" / "eval" / "general", "개발 대화": ev.DEV_D, "새 분야": ROOT / "data" / "eval" / "fresh"}
    for name, (items, gold, c_old, wk, ed_old, _fh) in sets.items():
        D = dirs[name]
        sfx = "_dev" if name == "개발 대화" else ""
        gold = dict(gold, **{w: b for (s, w), b in fixes.items() if s == name and w in gold})
        # 조합안 (11-10 조정용에서 고름): 새 질문을 모든 낱말에 쓰면 거의 다 '개념'이라 답한다 (조정용 341개 중 288개, 정밀도 0.607).
        # 그래서 새 질문은 분야 사전에 전문 뜻만 있는 낱말에만 쓰고, 나머지는 지금 질문의 답을 쓴다
        special = lambda x: judged(x) and g.lexicon_verdict(x["form"]) == "special"
        c_sp = ask(items, D / f"llm{sfx}_r8_{J}.json", judge_prompt, g.JUDGE_SCHEMA, "is_term", special)
        c_new = {x["form"]: (c_sp if g.lexicon_verdict(x["form"]) == "special" else c_old).get(x["form"]) for x in items}
        c_new = {k: v for k, v in c_new.items() if v is not None}
        wiki_path = D / "wiki.json"
        wk = ev.sourced_all(items, c_new, wiki_path)               # 새로 인정된 낱말의 위키백과 문서 (저장해 두고 다시 묻지 않는다)
        need_ed = lambda x: (g.rule_verdict(x["form"], x.get("sents")) == "unknown" and g.lexicon_verdict(x["form"]) == "special"
                             and c_new.get(x["form"]) is False and wk.get(x["form"]))
        ed_new = ask(items, D / f"everyday{sfx}_r8_{E}.json", everyday_prompt, g.EVERYDAY_SCHEMA, "everyday", need_ed)
        pos = sum(gold[x["form"]] for x in items)
        for label, c, ed, resc in (("지금 질문 기본", c_old, ed_old, False), ("지금 질문 +더보기", c_old, ed_old, True),
                                   ("조합 기본", c_new, ed_new, False), ("조합 +더보기", c_new, ed_new, True)):
            shown = [x["form"] for x in items if verdict(x, c, wk, ed, resc) == "show"]
            tp = sum(gold[w] for w in shown)
            print(f"{name:6} {label:12} 보여 줌 {len(shown):3}  정밀도 {tp / max(1, len(shown)):.3f}  재현율 {tp / max(1, pos):.3f}", flush=True)
        shown_new = {x["form"] for x in items if verdict(x, c_new, wk, ed_new) == "show"}
        print(" 조합 오탐:", ", ".join(sorted(w for w in shown_new if not gold[w]))[:600], flush=True)


if __name__ == "__main__":
    main()
