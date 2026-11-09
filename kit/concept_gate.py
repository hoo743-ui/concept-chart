# -*- coding: utf-8 -*-
"""concept_gate.py : 이 낱말이 공부할 개념인가를 가르는 관문 (오탐을 막는 자리). 서버·화면을 모른다.

순서: 사용자 판단 > 규칙 > LLM > 모름(숨김). LLM이 없거나 고장 나도 동작하고, 그때는 확실한 것만 보여 준다.
    rule_verdict(표기) → "accept" | "reject" | "likely" | "unknown"
    judge_prompt(표기, 문장들) → LLM에 줄 입력
    final(규칙 판정, LLM 판정 또는 None) → "show" | "candidate" | "hide"
"""
import pathlib
import re

TERMS_FILE = pathlib.Path(__file__).resolve().parent / "data" / "tech_terms.txt"
# 기술 문서 제목에도 있지만 대화에서는 거의 일반어인 낱말: 사전에 있어도 믿지 않는다
GENERAL = set("""이름 출처 구현 영역 요소 연어 이미지 사전 항구 설계 시스템 문서 목록 자료 주소 형식 환경 기능 구조 결과 상태
분석 과정 정의 평가 측정 입력 출력 연결 표시 설정 생성 변경 비교 적용 제거 조회 저장 설치 검색 실행 작업 시작 종료 요약""".split())
# 문장 속 평범한 영어 낱말 (대문자로 시작해도 일반어)
COMMON_EN = {"actions", "desktop", "main", "fine", "tuning", "out", "light", "beam", "sends", "powerful", "ok", "out", "note", "code", "data", "file", "user", "test", "fix", "add", "new", "run", "use"}
ACRONYM_NOISE = {"AP"}    # 대문자지만 뜻이 여럿이라 혼자서는 판단할 수 없다
_terms = None


def key(s):
    return re.sub(r"[\s\-_/]+", "", s.lower())


def terms():
    global _terms
    if _terms is None:
        lines = TERMS_FILE.read_text(encoding="utf-8").splitlines() if TERMS_FILE.exists() else []
        _terms = {key(x) for x in lines if x and not x.startswith("#")}
    return _terms


def rule_verdict(form):
    """accept = 규칙만으로 보여 줌, reject = 규칙만으로 숨김, likely = 사전에 있으니 LLM 확인, unknown = 판단 못 함"""
    f = form.strip()
    k = key(f)
    if len(k) < 2 or f.isdigit():
        return "reject"
    if re.fullmatch(r"[A-Za-z0-9.+#_\-]+", f):
        if f in ACRONYM_NOISE or f.lower() in COMMON_EN:
            return "reject"
        if re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", f):            # CI, API, GPU
            return "accept"
        if re.search(r"[a-z][A-Z]|[A-Z]{2}[a-z]|^[a-z]+[A-Z]|Error$|Exception$", f) or "-" in f or "_" in f:   # GitHub, SearXNG, macOS, KeyError
            return "accept"
        if k not in terms():
            return "unknown"
        return "accept" if f[0].isupper() else "likely"         # Docker는 사전으로 통과. 소문자(numpy, clean)는 일반 영어일 수 있어 LLM에게 확인
    if f in GENERAL:
        return "reject"
    return "likely" if k in terms() else "unknown"


def judge_prompt(form, sentences):
    joined = "\n".join("- " + s for s in sentences[:3]) or "- (문장 없음)"
    return f"""너는 개발자 학습 도구의 엄격한 심사관이다. 아래 낱말이 '소프트웨어·AI·컴퓨터 분야를 공부해야 뜻을 아는 전문 용어'인지 판단한다.
true: 그 분야를 모르면 뜻을 모를 기술 이름, 도구, 개념. 예: 커밋, 컨테이너, 함수, 정규화, 가상환경, 임베딩, 스레드.
false: 일상이나 다른 분야 글에서도 같은 뜻으로 흔히 쓰는 낱말. 문장이 기술 이야기여도 false다. 예: 서비스, 조건, 정보, 신호, 확장, 차단, 중단, 평균, 번역, 추천, 통과, 대화, 기록, 결정, 원인, clean, label, data.
잘린 조각이나 사람·회사 이름, 애매하면 false다.
낱말: {form}
문장:
{joined}
JSON으로만 답한다. is_term은 true 또는 false."""


JUDGE_SCHEMA = {"type": "object", "properties": {"is_term": {"type": "boolean"}}, "required": ["is_term"]}


def final(rule, llm=None):
    """→ "show"(공부 목록) | "candidate"(숨기되 사용자가 올릴 수 있는 후보) | "hide". 오탐을 먼저 막는다:
    LLM 혼자 인정한 낱말은 정밀도가 낮아(실측 0.72) 공부 목록에 넣지 않는다. 사전과 LLM이 함께 인정하거나 규칙이 확신할 때만 넣는다."""
    if rule == "accept":
        return "show"
    if rule == "reject":
        return "hide"
    if rule == "likely":                                    # 사전만으로는 부족하다 (처음 보는 낱말에서 정밀도 0.66)
        return "show" if llm is True else "candidate" if llm is None else "hide"
    return "candidate" if llm else "hide"
