# -*- coding: utf-8 -*-
"""intents.py : 사용자가 무엇을 묻는지 고르기. LLM은 아래 스키마의 값만 고른다 (문장을 쓰지 않는다).

- LLM이 없거나 실패하면 낱말 규칙으로 고른다 (기능이 멈추지 않게).
- LLM이 뽑은 개념 이름이 사용자 글에 없으면 버린다 (없는 이름을 지어내지 못하게).
"""
import re

KINDS = ["plan", "by_field", "recent", "check", "other"]
PERIODS = ["today", "yesterday", "week", "all"]
SCHEMA = {"type": "object", "properties": {"intent": {"type": "string", "enum": KINDS}, "concept": {"type": "string"},
                                           "period": {"type": "string", "enum": PERIODS}}, "required": ["intent", "concept", "period"]}


def prompt(text):
    return f"""사용자가 자기 공부 기록 앱에 한 말을 아래 종류 중 하나로 고른다.
plan: 어떻게 공부하면 좋은지, 무엇부터 볼지 묻는다
by_field: 개념이나 노트를 분야별로 나눠 달라고 한다
recent: 최근·저번·어제 공부한 것이 무엇인지 묻는다
check: 특정 개념을 공부했는지, 본 적 있는지 확인한다
other: 그 밖의 모든 것 (개념의 뜻 질문, 잡담 등)
concept: check일 때 확인하려는 낱말을 사용자 글에 적힌 그대로. 아니면 빈 문자열
period: recent일 때 today·yesterday·week·all 중 하나. 아니면 all
사용자 글: {text}
JSON으로만 답한다."""


def by_rules(text):
    t = text.strip()
    period = "today" if "오늘" in t else "yesterday" if "어제" in t else "week" if re.search(r"이번\s*주|지난\s*주|일주일|최근", t) else "all"
    if re.search(r"분야", t):
        return {"intent": "by_field", "concept": "", "period": "all"}
    if re.search(r"(했던가|했나|봤나|봤던가|본\s*적|공부했어\?|했었나)", t):
        name = re.split(r"\s*(내가|나|이거|을|를|은|는)?\s*(했던가|했나|봤나|봤던가|본\s*적|공부했어|했었나)", t)[0]
        name = re.sub(r"^(이거|그거|혹시)\s*", "", name).strip(" ?'\"“”")
        return {"intent": "check", "concept": name, "period": "all"}
    if re.search(r"(저번|지난번|최근|어제|오늘|이번\s*주|지난\s*주).*(공부|봤|본|했)", t):
        return {"intent": "recent", "concept": "", "period": period}
    if re.search(r"(어떻게|뭐부터|무엇부터|어떤\s*순서).*(공부|학습)|(공부|학습).*(방법|순서|계획)", t):
        return {"intent": "plan", "concept": "", "period": "all"}
    return {"intent": "other", "concept": "", "period": "all"}


def classify(text, client=None):
    """→ ({intent, concept, period}, 'llm' | 'rules')"""
    if client is not None and client.available():
        try:
            got = client.json(prompt(text[:500]), SCHEMA, 60)
            intent = got.get("intent") if got.get("intent") in KINDS else "other"
            concept = (got.get("concept") or "").strip()
            if concept and re.sub(r"\s+", "", concept.lower()) not in re.sub(r"\s+", "", text.lower()):
                concept = ""                                # 사용자 글에 없는 이름은 버린다
            if intent == "check" and not concept:
                concept = by_rules(text)["concept"]
            period = got.get("period") if got.get("period") in PERIODS else "all"
            return {"intent": intent, "concept": concept, "period": period}, "llm"
        except Exception:  # noqa: BLE001 — LLM 고장이면 규칙으로 계속
            pass
    return by_rules(text), "rules"
