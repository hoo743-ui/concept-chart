# -*- coding: utf-8 -*-
"""intents.py : 사용자가 무엇을 묻는지 고르기. LLM은 아래 스키마의 값만 고른다 (문장을 쓰지 않는다).

- LLM이 없거나 실패하면 낱말 규칙으로 고른다 (기능이 멈추지 않게).
- LLM이 뽑은 개념 이름이 사용자 글에 없으면 버린다 (없는 이름을 지어내지 못하게).
"""
import re

KINDS = ["plan", "by_field", "recent", "check", "define", "other"]
PERIODS = ["today", "yesterday", "week", "all"]
SCHEMA = {"type": "object", "properties": {"intent": {"type": "string", "enum": KINDS}, "concept": {"type": "string"},
                                           "period": {"type": "string", "enum": PERIODS}}, "required": ["intent", "concept", "period"]}


def prompt(text):
    return f"""사용자가 자기 공부 기록 앱에 한 말을 아래 종류 중 하나로 고른다.
plan: 어떻게 공부하면 좋은지, 무엇부터 볼지 묻는다
by_field: 개념이나 노트를 분야별로 나눠 달라고 한다
recent: 최근·저번·어제 공부한 것이 무엇인지 묻는다
check: 특정 개념을 공부했는지, 본 적 있는지 확인한다
define: 낱말의 뜻을 묻는다 (OO가 뭐야, OO 뜻, OO 설명해 줘)
other: 그 밖의 모든 것 (잡담 등)
concept: check·define일 때 확인하려는 낱말을 사용자 글에 적힌 그대로. 아니면 빈 문자열
period: recent일 때 today·yesterday·week·all 중 하나. 아니면 all
사용자 글: {text}
JSON으로만 답한다."""


def by_rules(text):
    t = text.strip()
    period = "today" if "오늘" in t else "yesterday" if "어제" in t else "week" if re.search(r"이번\s*주|지난\s*주|일주일|최근", t) else "all"
    if re.search(r"분야", t):
        return {"intent": "by_field", "concept": "", "period": "all"}
    if re.search(r"(했던가|했나|봤나|봤던가|본\s*적|공부했어\?|했었나)", t):
        name = re.split(r"\s*,?\s*(제가|내가|나|이거|을|를|은|는)?\s*(공부)?\s*(했던가|했나|봤나|봤던가|본\s*적|공부했어|했었나)", t)[0]
        name = re.sub(r"^(이거|그거|혹시)\s*", "", name).strip(" ?,'\"“”")
        return {"intent": "check", "concept": name, "period": "all"}
    if re.search(r"(저번|지난번|최근|어제|오늘|이번\s*주|지난\s*주).*(공부|봤|본|했)", t):
        return {"intent": "recent", "concept": "", "period": period}
    if re.search(r"(어떻게|뭐부터|무엇부터|어떤\s*순서).*(공부|학습)|(공부|학습).*(방법|순서|계획)", t):
        return {"intent": "plan", "concept": "", "period": "all"}
    name = define_name(t)
    if name:
        return {"intent": "define", "concept": name, "period": "all"}
    return {"intent": "other", "concept": "", "period": "all"}


# (11-13) 낱말 뜻 질문: 'DB가 뭐야?' 'API 설명해줘' '커밋 뜻'. 낱말이 짧을 때만 (긴 문장 '어떻게 … 알려줘'는 뜻 질문이 아니다)
DEFINE = re.compile(r"^(?P<name>.+?)\s*(?:이란|란|이라는\s*게|라는\s*게|이라는\s*건|라는\s*건)?\s*"
                    r"(?:뭐야|뭐예요|뭐에요|뭔가요|뭐지|뭐임|뭔데|무엇인가요|무엇이야|무엇이에요|뜻|의미|개념|설명해\s*줘|설명해\s*주세요|설명\s*좀|알려\s*줘|알려\s*주세요)"
                    r"\s*(?:이야|이에요|예요|가\s*뭐야|는|은|이\s*뭐야|가)?\s*[?？!.~ㅋㅎ]*$")


def define_name(text):
    m = DEFINE.match(text.strip().strip("'\"“”"))
    if not m:
        return ""
    name = m.group("name").strip(" ,'\"“”")
    if not name or len(name) > 30 or len(name.split()) > 3 or re.search(r"(어떻게|뭐부터|무엇부터|순서|방법|공부|학습|저번|최근|오늘|어제)", name):
        return ""
    return name


def classify(text, client=None):
    """→ ({intent, concept, period}, 'llm' | 'rules')"""
    name = define_name(text)
    if name:                                                # 뜻 질문은 규칙으로 먼저 (11-13: LLM이 'DB가 뭐야?'를 학습 순서로 골랐다)
        return {"intent": "define", "concept": name, "period": "all"}, "rules"
    if client is not None and client.available():
        try:
            got = client.json(prompt(text[:500]), SCHEMA, 60)
            intent = got.get("intent") if got.get("intent") in KINDS else "other"
            concept = (got.get("concept") or "").strip()
            if concept and re.sub(r"\s+", "", concept.lower()) not in re.sub(r"\s+", "", text.lower()):
                concept = ""                                # 사용자 글에 없는 이름은 버린다
            if intent == "define" and not concept:
                intent = "other"                            # 무엇의 뜻인지 모르면 지어내지 않는다
            if intent == "check" and not concept:
                concept = by_rules(text)["concept"]
            period = got.get("period") if got.get("period") in PERIODS else "all"
            return {"intent": intent, "concept": concept, "period": period}, "llm"
        except Exception:  # noqa: BLE001 — LLM 고장이면 규칙으로 계속
            pass
    return by_rules(text), "rules"
