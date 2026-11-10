# -*- coding: utf-8 -*-
"""concept_gate.py : 이 낱말이 공부할 개념인가를 가르는 관문 (오탐을 막는 자리). 서버·화면을 모른다.

순서: 사용자 판단 > 규칙 > LLM > 모름(숨김). LLM이 없거나 고장 나도 동작하고, 그때는 확실한 것만 보여 준다.
    rule_verdict(표기, 문장들=None) → "accept" | "reject" | "likely" | "unknown"
    judge_prompt(표기, 문장들) → LLM에 줄 입력
    lexicon_verdict(표기) → "special" | "mixed" | "general" | None   (분야 사전: kit/data/lexicon/, 없으면 None)
    final(규칙, LLM 또는 None, 위키백과 문서 여부, 분야 사전) → "show" | "candidate" | "hide"   (AI 없음: final_no_ai)
"""
import os
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


ASCII_FORM = re.compile(r"[A-Za-z0-9.+#_\-]+")
SCRIPT_AFTER = "₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻"    # 아래·위 첨자: 화학식(H₂SO₄, OH⁻)이 형태소 분석에서 잘린 자리


def formula_fragment(form, sentences):
    """화학식 조각인가: 문장 속 모든 자리에서 바로 뒤에 첨자가 붙어 있다 (CH₄ → CH, H₂SO₄ → SO, ZnSO₄ → ZnSO).
    완성된 화학식(NaOH, KOH, COOH)은 첨자 없이 끝나므로 남는다. 문장이 없으면 판단하지 않는다"""
    seen = cut = 0
    for s in sentences or ():
        for m in re.finditer(rf"(?<![A-Za-z]){re.escape(form)}(?![a-z])", s):
            seen += 1
            nxt = s[m.end():m.end() + 1]
            cut += bool(nxt) and nxt in SCRIPT_AFTER
    return seen > 0 and cut == seen


def rule_verdict(form, sentences=None):
    """accept = 규칙만으로 보여 줌, reject = 규칙만으로 숨김, likely = 사전에 있으니 LLM 확인, unknown = 판단 못 함.
    sentences(그 낱말이 나온 문장)가 있으면 화학식 조각을 거른다"""
    f = form.strip()
    k = key(f)
    if len(k) < 2 or f.isdigit():
        return "reject"
    if ASCII_FORM.fullmatch(f):
        if f in ACRONYM_NOISE or f.lower() in COMMON_EN or formula_fragment(f, sentences):
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
    return f"""너는 학습 도구의 엄격한 심사관이다. 아래 낱말이 '어느 분야든 그 분야를 공부해야 정확한 뜻을 아는 전문 용어'인지 판단한다. 분야는 가리지 않는다.
true: 그 분야를 배우지 않은 사람은 정확히 설명하지 못할 개념, 이론, 제도, 물질, 기술 이름. 예: 커밋, 임베딩, 기회비용, 형태소, 내력벽, 삼투압, 판례.
false: 일상에서도 같은 뜻으로 흔히 쓰는 낱말. 문장이 전문적인 이야기여도 false다. 예: 방법, 문제, 내용, 경우, 부분, 가능, 사용, 설명, 신호, 차단, 번역, 추천, 통과, clean, label.
잘린 조각, 사람·나라·회사 이름, 형용사꼴(~적), 분야 이름 자체, 애매하면 false다.
낱말: {form}
문장:
{joined}
JSON으로만 답한다. is_term은 true 또는 false."""


JUDGE_SCHEMA = {"type": "object", "properties": {"is_term": {"type": "boolean"}}, "required": ["is_term"]}


LEXICON_DIR = pathlib.Path(__file__).resolve().parent / "data" / "lexicon"   # 사전 파일은 git에 없다: python dev.py lexicon 으로 만든다
_lex = None


class _SqliteLex:
    """앱용: 합친 사전(lexicon.sqlite)에서 필요한 낱말만 찾는다. 90만 낱말을 메모리에 올리면 프로세스마다 약 135MB라서"""

    def __init__(self, path):
        import sqlite3
        import threading
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.lock = threading.Lock()
        self.cache = {}

    def get(self, k):
        if k not in self.cache:
            with self.lock:
                row = self.con.execute("SELECT spec, gen FROM lex WHERE key=?", (k,)).fetchone()
            if len(self.cache) > 50000:
                self.cache.clear()
            self.cache[k] = tuple(row) if row else None
        return self.cache[k]


def read_tsv(folder):
    """분야 사전들(*.tsv: key, 표기, 전문 뜻 수, 일상 뜻 수, 분야)을 합친다. 사전을 더 넣으면 뜻 수를 더한다"""
    lex = {}
    for p in sorted(pathlib.Path(folder).glob("*.tsv")):
        with p.open(encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                k, _form, spec, gen = line.rstrip("\n").split("\t")[:4]
                s, n = lex.get(k, (0, 0))
                lex[k] = (s + int(spec), n + int(gen))
    return lex


def load_lexicons(folder=None):
    """폴더에 lexicon.sqlite가 있으면 그것을(앱), 없으면 *.tsv를 메모리로 읽는다(평가·시험). 둘 다 없으면 빈 사전 (그때는 예전처럼 동작).
    폴더는 인자 → 환경 변수 CONCEPT_CHART_LEXICON → kit/data/lexicon 순서"""
    global _lex
    folder = pathlib.Path(folder or os.environ.get("CONCEPT_CHART_LEXICON") or LEXICON_DIR)
    _lex = _SqliteLex(folder / "lexicon.sqlite") if (folder / "lexicon.sqlite").is_file() else read_tsv(folder)
    return _lex


def lexicon_verdict(form):
    """"special"(전문 뜻만) | "mixed"(전문 뜻과 일상 뜻) | "general"(일상 뜻만) | None(사전에 없음)"""
    if _lex is None:
        load_lexicons()
    v = _lex.get(re.sub(r"[\s\-_/^]+", "", form.strip().lower()))
    if not v:
        return None
    s, n = v
    return "special" if s and not n else "mixed" if s else "general"


def final_no_ai(rule, sourced=None, lex=None):
    """AI(로컬 LLM)를 받지 않은 컴퓨터: 규칙이 확신하거나, 분야 사전에 전문 뜻만 있고 이름이 맞는 위키백과 문서도 있을 때만 보여 준다"""
    if rule == "accept" or (rule == "unknown" and lex == "special" and sourced):
        return "show"
    if rule == "reject" or lex == "general":
        return "hide"
    return "candidate" if rule == "likely" or lex == "special" else "hide"


def final(rule, llm=None, sourced=None, lex=None):
    """→ "show"(공부 목록) | "candidate"(숨기되 사용자가 올릴 수 있는 후보) | "hide". 오탐을 먼저 막는다:
    LLM 혼자 인정한 낱말은 정밀도가 낮아(실측 0.72) 공부 목록에 넣지 않는다. 두 번째 근거가 있을 때만 넣는다:
    사전(개발 용어), 분야 사전에 전문 뜻만 있음(lex="special"), 또는 sourced = 이름이 맞는 위키백과 문서가 있음.
    분야 사전에 일상 뜻만 있으면 숨기고(LLM에 묻지 않아도 된다), 일상 뜻도 있으면 후보까지만 둔다."""
    if rule == "unknown" and lex == "general":
        return "hide"
    if rule == "unknown" and lex == "mixed":
        return "candidate" if llm else "hide"
    if rule == "unknown" and llm is True and (lex == "special" or sourced):
        return "show"
    if rule == "accept":
        return "show"
    if rule == "reject":
        return "hide"
    if rule == "likely":                                    # 사전만으로는 부족하다 (처음 보는 낱말에서 정밀도 0.66)
        return "show" if llm is True else "candidate" if llm is None else "hide"
    return "candidate" if llm else "hide"
