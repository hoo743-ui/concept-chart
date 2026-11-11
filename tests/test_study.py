# -*- coding: utf-8 -*-
"""공부 기능·거짓 방지·독립성 점검. 네트워크와 실제 LLM 없이, 임시 폴더에서만 돈다.

    python tests/test_study.py

- 관문: 일상어가 공부 목록에 못 들어가고, 사용자 판단이 가장 앞선다. LLM이 없어도 동작한다.
- 거짓 방지: 근거에 없는 숫자·이름·반대 내용이 든 LLM 문장은 저장되지 않는다.
- 독립성: 화면은 api.js로만 서버와 만나고 문서에 있는 API만 쓴다. 서버는 화면 파일을 모른다. 모델이 없거나 죽어도 서버는 그대로다.
- 입구: 붙여넣기·파이프·내보내기 파일이 같은 인박스로 들어가고, 키는 가려지고, 다른 사이트의 기록 요청은 막힌다.
"""
import json
import os
import pathlib
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
import concept_add  # noqa: E402
import concept_gate as gate  # noqa: E402
import llm as llm_mod  # noqa: E402
import serve  # noqa: E402
import study_api  # noqa: E402

FAILS = []


def ok(name, cond, info=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (f" — {info}" if info else ""))
    if not cond:
        FAILS.append(name)


def check_gate():
    for w in ["추천", "통과", "대화", "설치", "저장", "이름", "출처", "main", "Actions", "Desktop", "fine", "AP"]:
        ok(f"일상어·조각은 공부 목록에 없음: {w}", gate.final(gate.rule_verdict(w), True) != "show")
    for w in ["API", "GitHub", "SearXNG", "KeyError", "PyTorch", "macOS", "sentence-transformers"]:
        ok(f"기술 이름은 규칙으로 통과: {w}", gate.rule_verdict(w) == "accept")
    for w, s in [("CH", "메탄(CH₄), 아세트산(CH₃COOH)"), ("SO", "황산(H₂SO₄)"), ("OH", "수산화 이온(OH⁻)")]:
        ok(f"화학식 조각은 숨김: {w}", gate.rule_verdict(w, [s]) == "reject")
    for w, s in [("NaOH", "수산화 나트륨(NaOH) 등"), ("COOH", "아세트산(CH₃COOH)"), ("GPU", "GPU₁ 아니고 GPU를 쓴다")]:
        ok(f"완성된 화학식·약어는 남김: {w}", gate.rule_verdict(w, [s]) == "accept")
    ok("아래첨자 글자가 붙은 조각도 숨김: NO(NOₓ)", gate.rule_verdict("NO", ["질소산화물(NOₓ)"]) == "reject")
    ok("숫자가 붙은 이름은 남김: SGLT(SGLT2)", gate.rule_verdict("SGLT", ["SGLT2 억제제"]) == "accept")
    code_doc = "```python\nimport pyarrow\nfrom ipykernel.kernelapp import App\n```\npip install -U matplotlib\n`torch`를 쓴다. 기본값은 ... 이다."
    for w in ["pyarrow", "ipykernel", "matplotlib"]:
        ok(f"코드로 쓰인 영어 이름: {w}", gate.code_name(w, [code_doc]))
    for w, why in [("pandas", "답변에 없음"), ("...", "글자 없음"), ("기본값", "한글"), ("torch", "인라인 코드만 (0.7.1에서 뺌)")]:
        ok(f"코드 이름 아님: {w} ({why})", not gate.code_name(w, [code_doc]))
    ok("코드 이름은 LLM이 아니라 해도 보여 줌", gate.final("unknown", False, None, None, True) == "show" and gate.final_no_ai("unknown", None, None, True) == "show")
    ok("규칙이 거절한 낱말은 코드 이름이어도 숨김", gate.final("reject", None, None, None, True) == "hide")
    for w, s in [("Server", "SQL Server는 관계형"), ("CROSS", "CROSS JOIN은 모든 조합")]:
        ok(f"영어 이름 조각은 숨김: {w}", gate.rule_verdict(w, [s]) == "reject")
    for w, s in [("ELB", "AWS ELB 등"), ("API", "REST API를 설계"), ("Server", "SQL Server 또는 Server 설정")]:
        ok(f"약어 뒷조각·혼자 쓰인 자리가 있으면 남김: {w} ({s})", gate.rule_verdict(w, [s]) == "accept")
    ok("LLM 혼자 인정한 낱말은 후보까지만", gate.final("unknown", True) == "candidate")
    ok("LLM이 없으면 모르는 낱말을 숨김", gate.final("unknown", None) == "hide")
    ok("LLM이 없으면 사전만으로 공부 목록에 넣지 않음", gate.final("likely", None) == "candidate")
    ok("사전과 LLM이 엇갈리면 숨김", gate.final("likely", False) == "hide")
    ok("사전과 LLM이 함께 인정하면 보여 줌", gate.final("likely", True) == "show")
    ok("LLM + 이름이 맞는 위키백과 문서면 보여 줌", gate.final("unknown", True, True) == "show")


def check_no_lexicon_tail():
    """사전이 없으면 '-당'은 떼지 않는다 (포도당이 '포도'가 되지 않게). '-별·-들'은 뗀다"""
    gate.load_lexicons(pathlib.Path(tempfile.mkdtemp()))
    ok("꼬리 떼기(사전 없음): 포도당·에폭당은 그대로, 단계별 → 단계", (serve.strip_tail("포도당"), serve.strip_tail("에폭당"), serve.strip_tail("단계별")) == ("포도당", "에폭당", "단계"))


def check_lexicon():
    """분야 사전(우리말샘 등)을 합쳐 읽고, 전문 뜻만 / 섞임 / 일상 뜻만으로 가른다. 임시 사전으로만 시험한다 (CI에는 사전 파일이 없다)"""
    d = pathlib.Path(tempfile.mkdtemp())
    try:
        (d / "a.tsv").write_text("# 머리말\n삼투압\t삼투압\t1\t0\t물리\n변이\t변이\t2\t0\t생명\n통과\t통과\t0\t5\t\n포도당\t포도당\t1\t0\t화학\n단계별\t단계별\t0\t1\t\n", encoding="utf-8")
        (d / "b.tsv").write_text("변이\t변이\t0\t3\t\n", encoding="utf-8")       # 두 번째 사전이 일상 뜻을 더한다
        gate.load_lexicons(d)
        ok("전문 뜻만 있는 낱말", gate.lexicon_verdict("삼투압") == "special")
        ok("사전을 합치면 뜻 수를 더한다 (변이 → 섞임)", gate.lexicon_verdict("변이") == "mixed")
        ok("일상 뜻만 있는 낱말", gate.lexicon_verdict("통과") == "general")
        ok("사전에 없는 낱말", gate.lexicon_verdict("리베이스") is None)
        ok("꼬리 떼기(사전 있음): 에폭당 → 에폭, 단계별(일상 뜻만) → 단계, 포도당(전문 뜻)은 그대로",
           (serve.strip_tail("에폭당"), serve.strip_tail("단계별"), serve.strip_tail("포도당")) == ("에폭", "단계", "포도당"))
        ok("'-적' 꼴은 앞말이 사전에 있으면 숨김 (삼투압적)", gate.rule_verdict("삼투압적") == "reject")
        ok("두 글자 '-적'은 그대로 (목적)", gate.rule_verdict("목적") != "reject")
        ok("전문 뜻만 + LLM 인정이면 보여 줌", gate.final("unknown", True, None, "special") == "show")
        ok("일상 뜻도 있으면 LLM + 위키백과 문서가 함께 인정해야 보여 줌", gate.final("unknown", True, True, "mixed") == "show")
        ok("일상 뜻도 있는데 문서가 없으면 후보까지만", gate.final("unknown", True, False, "mixed") == "candidate")
        ok("일상 뜻도 있는데 LLM이 아니라 하면 숨김", gate.final("unknown", False, True, "mixed") == "hide")
        ok("일상 뜻만 있으면 숨김", gate.final("unknown", True, True, "general") == "hide")
        ok("규칙이 확신하면 사전과 상관없이 보여 줌", gate.final("accept", None, None, "general") == "show")
        ok("AI 없음: 전문 뜻만 + 위키백과 문서면 보여 줌", gate.final_no_ai("unknown", True, "special") == "show")
        ok("AI 없음: 전문 뜻만이어도 문서가 없으면 후보", gate.final_no_ai("unknown", False, "special") == "candidate")
        ok("AI 없음: 사전에 없는 낱말은 숨김", gate.final_no_ai("unknown", True, None) == "hide")
        ok("더 보기로 살림: 전문 뜻만 + LLM 아님 + 문서 + 일상어 아님", gate.rescue("unknown", False, True, "special", False))
        ok("일상어라고 답하면 살리지 않음", not gate.rescue("unknown", False, True, "special", True))
        ok("두 번째 질문 전이면 살리지 않음", not gate.rescue("unknown", False, True, "special", None))
        ok("문서가 없거나 일상 뜻도 있으면 살리지 않음", not gate.rescue("unknown", False, False, "special", False) and not gate.rescue("unknown", False, True, "mixed", False))
        ok("살리는 낱말은 기본 목록에 들어가지 않음", gate.final("unknown", False, True, "special") == "hide")
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE notes (concept TEXT PRIMARY KEY, definition TEXT, sources TEXT, updated TEXT)")
        con.execute("INSERT INTO notes VALUES ('a','정의','[{\"text\":\"정의\",\"url\":\"https://ko.wikipedia.org/wiki/A\"}]','')")
        con.execute("INSERT INTO notes VALUES ('b','정의','[{\"text\":\"정의\",\"url\":\"https://blog.example.com/b\"}]','')")
        con.execute("INSERT INTO notes VALUES ('c','','[]','')")
        ok("위키백과 출처는 두 번째 근거", study_api.sourced(con, "a"))
        ok("검색(SearXNG) 출처는 근거가 아님", not study_api.sourced(con, "b"))
        ok("정의가 없으면 근거가 아님", not study_api.sourced(con, "c") and not study_api.sourced(con, "zz"))
    finally:
        gate.load_lexicons(d / "없음")                       # 다른 시험에는 사전 없이
        shutil.rmtree(d, ignore_errors=True)

def check_fields():
    """분야 꼬리표: 기술 용어집이면 정보·통신, 사전 분야는 함께 나온 개념 2개 이상이 같은 분야일 때만, 근거 없으면 None"""
    import fields
    d = pathlib.Path(tempfile.mkdtemp())
    old = os.environ.get("CONCEPT_CHART_LEXICON")
    try:
        lx = sqlite3.connect(d / "lexicon.sqlite")
        lx.execute("CREATE TABLE field (key TEXT PRIMARY KEY, fields TEXT)")
        lx.executemany("INSERT INTO field VALUES (?,?)", [("전류", "전기·전자;식물"), ("전압", "전기·전자"), ("저항", "전기·전자;물리"), ("체크포인트", "체육")])
        lx.commit()
        lx.close()
        os.environ["CONCEPT_CHART_LEXICON"] = str(d)
        fields._con, fields._cache = None, {}
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE cooc (a TEXT, b TEXT, n INTEGER)")
        con.execute("CREATE TABLE forms (concept TEXT, form TEXT, n INTEGER)")
        con.executemany("INSERT INTO forms VALUES (?,?,1)", [("i", "전류"), ("v", "전압"), ("r", "저항"), ("c", "체크포인트"), ("x", "버그")])
        con.executemany("INSERT INTO cooc VALUES (?,?,1)", [("i", "v"), ("i", "r"), ("c", "x"), ("v", "i")])
        ok("분야가 여럿이면 함께 나온 개념으로 고름 (전류 → 전기·전자)", fields.field_of(con, "i", "전류") == "전기·전자")
        ok("같은 분야 이웃이 하나뿐이면 달지 않음", fields.field_of(con, "v", "전압") is None)
        ok("사전 분야가 대화와 안 맞으면 달지 않음 (체크포인트 = 체육)", fields.field_of(con, "c", "체크포인트") is None)
        ok("사전에 없으면 None", fields.field_of(con, "x", "없는낱말") is None)
        ok("기술 용어집에 있으면 정보·통신", fields.field_of(con, "x", "Docker") == fields.TECH or "docker" not in gate.terms())
    finally:
        if old is None:
            os.environ.pop("CONCEPT_CHART_LEXICON", None)
        else:
            os.environ["CONCEPT_CHART_LEXICON"] = old
        fields._con, fields._cache = None, {}
        shutil.rmtree(d, ignore_errors=True)


class FakeLLM:
    name = "fake"

    def __init__(self, out):
        self.out = out

    def available(self):
        return True

    def json(self, prompt, schema, max_tokens=400):
        import study_worker as w
        props = schema["properties"]
        return {"field": w.TECH} if "field" in props else {"supported": True} if "supported" in props else {"answer": "같은 대상"} if "answer" in props else self.out


def db_with_note(tmp):
    con = serve.open_db(tmp / "n.sqlite")
    con.execute("INSERT INTO freq VALUES ('트랜스포머',2)")
    con.execute("INSERT INTO forms VALUES ('트랜스포머','트랜스포머',2)")
    con.execute("INSERT INTO mentions VALUES ('트랜스포머','2026-11-09T00:00:00+00:00','s','assistant','트랜스포머 모델의 어텐션을 조정했습니다.',NULL)")
    d = "트랜스포머는 순환 구조 없이 어텐션 메커니즘만으로 문장 속 단어들의 관계를 한 번에 계산하는 신경망 구조로, 2017년 논문에서 처음 제안되었다."
    serve.save_note(con, "트랜스포머", d, [{"text": d, "url": "https://example.org/t"}])
    return con


def check_grounding(tmp):
    import study_worker as w
    con = db_with_note(tmp)
    good = {"easy": "트랜스포머는 어텐션 메커니즘만으로 문장 속 단어들의 관계를 계산하는 신경망 구조입니다."}
    status, body = w.run_note(con, FakeLLM(good), "트랜스포머")
    ok("근거와 맞는 문장은 저장", status == "ready" and body["easy"], str(body and body["checked"]))
    ok("저장한 문장에 근거 문장이 붙음", bool(body["easy_evidence"]))
    for name, bad in [("없는 숫자·이름", "트랜스포머는 2019년 Google이 처음 공개한 신경망 구조입니다."), ("없는 개념", "트랜스포머는 순환 신경망과 강화 학습을 합친 모델입니다."),
                      ("깨진 낱말", "트랜스포머는 어텐셜 메커니즘만으로 문장 속 단어들의 관계를 계산합니다.")]:
        status, body = w.run_note(con, FakeLLM({"easy": bad}), "트랜스포머")
        ok(f"쉬운 설명 거절: {name}", status == "rejected" and not body["easy"], str(body and body["easy"]))
    ok("실제로 나왔던 오류 거절: 깨진 낱말", not w.strict_ok("PowerShell은 마이크로소과프트가 만든 셸입니다.", "PowerShell은 마이크로소프트가 만든 셸이다."))
    ok("실제로 나왔던 오류 거절: 낱말 일부", not w.strict_ok("파워셸은 셸 및 스크립과 언어입니다.", "파워셸은 셸 및 스크립트 언어를 특징으로 한다."))
    ok("복합어를 붙여 쓴 것은 허용", w.strict_ok("파인튜닝은 모델을 특화시키는 과정입니다.", "파인 튜닝은 모델을 특화시키는 과정이다."))
    ok("실제로 나왔던 오류 거절: 원문에 없는 숫자", not w.strict_ok("리눅스 운영체제는 1: 1991년 9월 17일 리누스 토르발스가 시작했습니다.", "리눅스 운영체제는 1991년 9월 17일 리누스 토르발스에 의해 시작되었다."))
    ok("실제로 나왔던 오류 거절: 겹친 어미", not w.strict_ok("난수는 무작위로 추출된 수를 일컫는다입니다.", "난수란 정의된 범위 내에서 무작위로 추출된 수를 일컫는다."))
    ok("원문 숫자는 허용", w.strict_ok("파이썬은 1991년 발표한 프로그래밍 언어입니다.", "파이썬은 1991년 발표한 프로그래밍 언어다."))
    ok("실제로 나왔던 오류 거절: 지어낸 조합", not w.strict_ok("GPU 메모리 사용량이 2.36GB로 0.04GB의 온도를 보입니다.", "GPU 메모리는 최대 2.36GB를 썼습니다."))

    class No(FakeLLM):
        def json(self, prompt, schema, max_tokens=400):
            return {"supported": False} if "supported" in schema["properties"] else FakeLLM.json(self, prompt, schema, max_tokens)
    status, body = w.run_note(con, No(good), "트랜스포머")
    ok("두 번째 확인에서 뒷받침되지 않으면 거절", status == "rejected" and not body["easy"])
    class Other(FakeLLM):
        def json(self, prompt, schema, max_tokens=400):
            return {"field": "다른 분야"} if "field" in schema["properties"] else FakeLLM.json(self, prompt, schema, max_tokens)
    status, body = w.run_note(con, Other(good), "트랜스포머")
    ok("출처가 다른 분야의 뜻이면 노트를 만들지 않음", status == "wrong_sense" and body is None)

    class SameName(FakeLLM):
        def json(self, prompt, schema, max_tokens=400):
            return {"answer": "다른 대상"} if "answer" in schema["properties"] else FakeLLM.json(self, prompt, schema, max_tokens)
    status, body = w.run_note(con, SameName(good), "트랜스포머")
    ok("이름만 같은 다른 대상이면 노트를 만들지 않음", status == "wrong_sense" and body is None)
    con.execute("REPLACE INTO study_notes VALUES ('트랜스포머',NULL,'wrong_sense','x','t')")
    ok("다른 뜻이면 요약 줄을 비움", study_api.summary_line(con, "트랜스포머") == (None, "none"))
    d = study_api.detail(con, {"label": "트랜스포머", "definition": "x", "summary": "x", "sources": [{"text": "x", "url": "u"}]}, "트랜스포머")
    ok("다른 뜻이면 정의·출처를 화면에 내지 않음", d["definition"] is None and not d["sources"])
    con.execute("DELETE FROM study_notes")
    w.run_judge(con, FakeLLM({"is_term": False}), "트랜스포머")
    w.run_everyday(con, FakeLLM({"everyday": False}), "트랜스포머")
    ok("두 번째 질문 답은 LLM 판정을 덮지 않고 따로 저장", con.execute("SELECT llm, everyday FROM judgments WHERE concept='트랜스포머'").fetchone() == (0, 0))
    con.execute("DELETE FROM judgments")
    import fetch_sources as fs
    ok("다른 낱말 설명은 거절: 이동 기준선", not fs.subject_ok("기준선", "이동 기준선 은 일반적으로 시스템을 측정한다."))
    ok("분야 앞말은 허용: 시스템에서 커밋", fs.subject_ok("커밋", "버전 관리 시스템에서 커밋은 변경을 기록한다."))
    ok("문장 시작 낱말은 허용", fs.subject_ok("함수", "함수는 입력을 받아 출력한다."))
    # 출처 고르기: 실제로 나온 오류를 고정한다. 'GPU는 점점 더 많이 쓰인다'처럼 뜻을 말하지 않는 문장이 정의 자리에 들어갔다
    page = lambda title, text: {"url": "https://example.org/" + title, "text": text, "src": "wikipedia", "title": title}
    gpu = page("그래픽 처리 장치", "그래픽 처리 장치는 컴퓨터 그래픽스 가속을 위해 설계된 전자 회로이다. GPU는 인공지능 처리 용도로도 점점 더 많이 사용되고 있다.")
    ok("문서 첫 문장을 정의로", fs.lead_sents(gpu)[0]["text"].startswith("그래픽 처리 장치는"))
    ok("동음이의 안내문은 정의가 아님", fs.lead_sents(page("Git", "Git 또는 GIT는 다음을 가리킨다. 분산 버전 관리 시스템이다.")) == [])
    ok("분야 괄호: 셸·AI는 기술", all(fs.TECH_PAREN.search(t) for t in ("Bash (Unix shell)", "Claude (AI)")))
    ok("분야 괄호: 낱말 일부는 아님", not any(fs.TECH_PAREN.search(t) for t in ("Thai (Thailand)", "Sea (seashell)", "Host (패러다이스 로스트의 음반)")))
    saved = fs.wikipedia_tech, fs.wikipedia_exact, fs.korean_version
    try:
        fs.wikipedia_tech = lambda t, lang="ko": [page("함수 (컴퓨터 과학)", "함수는 어떤 일을 수행하는 코드의 묶음이다.")] if (t, lang) == ("함수", "ko") else []
        fs.wikipedia_exact = lambda t, lang="ko": {("함수", "ko"): [page("함수", "수학에서 함수는 원소를 대응시키는 것이다.")],
                                                   ("GPU", "ko"): [gpu],
                                                   ("Git", "en"): [page("Git", "Git is a distributed version control system.")],
                                                   ("깃 (소프트웨어)", "ko"): [page("깃 (소프트웨어)", "깃은 분산 버전 관리 시스템이다.")],
                                                   ("SearXNG", "en"): [page("SearXNG", "SearXNG is a metasearch engine forked from searX.")]}.get((t, lang), [])
        fs.korean_version = lambda title: "깃 (소프트웨어)" if title == "Git" else None
        ok("기술 문서가 일반 문서보다 먼저", "코드의 묶음" in fs.wikipedia_lead("함수")[0]["text"])
        ok("넘겨주기로 찾은 문서의 정의", fs.wikipedia_lead("GPU")[0]["text"].startswith("그래픽 처리 장치는"))
        ok("영어 문서만 맞으면 한국어 문서를 찾아 씀", fs.wikipedia_lead("Git")[0]["text"].startswith("깃은"))
        ok("한국어 문서가 없으면 영어 문장", fs.wikipedia_lead("SearXNG")[0]["text"].startswith("SearXNG is"))
        ok("맞는 문서가 없으면 빈 목록", fs.wikipedia_lead("없는말") == [])
    finally:
        fs.wikipedia_tech, fs.wikipedia_exact, fs.korean_version = saved
    ok("마크다운·인라인 코드를 살린 문장", serve.extract("**핵심:** `main`에 커밋합니다.")[0][0] == "핵심: main에 커밋합니다.", str(serve.extract("**핵심:** `main`에 커밋합니다.")[0][0]))
    ok("표 줄은 칸으로 나눔", serve.plain_line("| 커밋 | 저장 |") == "커밋 · 저장" and serve.plain_line("|---|---|") == "")
    ok("도구 알림은 내 질문이 아님", bool(serve.SYSTEM_MSG.match("<task-notification>x")) and not serve.SYSTEM_MSG.match("커밋이 뭐야?"))
    con.execute("INSERT INTO answers VALUES ('a1','s','2026-11-09T00:00:00+00:00','paste','도커 컨테이너는 이미지로부터 만들어진다. 볼륨은 데이터를 보존한다.',NULL)")
    status, body = w.run_summary(con, FakeLLM({"picks": [2, 99, -1]}), "a1")
    ok("요약은 고른 번호의 원문 문장만, 없는 번호는 무시", status == "ready" and [p["text"] for p in body["points"]] == ["볼륨은 데이터를 보존한다."], str(body))
    status, body = w.run_summary(con, FakeLLM({"picks": [], "points": ["쿠버네티스 1.30이 필요하다."]}), "a1")
    ok("LLM이 문장을 써 보내도 쓰지 않음", status == "rejected" and not body["points"])
    p = study_api.practice("커밋은 저장소에 변경사항을 기록하는 것을 말한다. 다음 문장.", ["커밋"])
    ok("확인 문제는 출처 문장에서 이름만 가림", p == {"blank": "____은 저장소에 변경사항을 기록하는 것을 말한다.", "answer": "커밋"}, str(p))
    ok("정의가 없으면 문제도 없음", study_api.practice(None, ["커밋"]) is None)
    con.close()


def check_llm_slot():
    ok("LLM 끔: 사용 불가로 응답", llm_mod.make("off").available() is False and llm_mod.make(None).available() is False)
    try:
        llm_mod.make("이상한값:x")
        ok("모르는 LLM 값은 거절", False)
    except ValueError:
        ok("모르는 LLM 값은 거절", True)
    ok("LLM 주소는 이 PC로 고정", llm_mod.OLLAMA.startswith("http://127.0.0.1:"))


def check_inputs(tmp):
    ib = tmp / "in.jsonl"
    ok("붙여넣기 추가", concept_add.add("커밋은 변경을 기록한다.", "paste", inbox=ib))
    ok("같은 글은 다시 넣지 않음", not concept_add.add("커밋은 변경을 기록한다.", "paste", inbox=ib))
    ok("빈 글은 넣지 않음", not concept_add.add("   ", "paste", inbox=ib))
    concept_add.add("키는 sk-abcdefghijklmnopqrstuvwx 입니다", "paste", inbox=ib)
    rows = [json.loads(x) for x in ib.read_text(encoding="utf-8").splitlines()]
    ok("키·토큰은 가려서 저장", "sk-abc" not in rows[-1]["text"] and "[MASKED]" in rows[-1]["text"])
    ok("인박스 계약 필드", all(k in rows[0] for k in ("v", "source", "ts", "role", "text", "truncated")) and rows[0]["role"] == "assistant")
    env = dict(os.environ, CONCEPT_INBOX=str(ib), PYTHONUTF8="1")
    p = subprocess.run([sys.executable, str(ROOT / "kit" / "concept_add.py"), "text", "--source", "codex"], input="브랜치는 작업 갈래다.".encode("utf-8"), capture_output=True, env=env, timeout=30)
    ok("파이프로 추가", p.returncode == 0 and "codex" in ib.read_text(encoding="utf-8"), p.stderr.decode("utf-8", "replace")[-200:])
    export = tmp / "conversations.json"
    export.write_text(json.dumps([
        {"uuid": "c1", "name": "x", "chat_messages": [{"sender": "human", "text": "커밋이 뭐야?", "created_at": "2026-11-01T00:00:00Z"}, {"sender": "assistant", "text": "커밋은 저장 단위다.", "created_at": "2026-11-01T00:00:01Z"}]},
        {"id": "g1", "mapping": {"a": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["리베이스는 이력을 옮긴다."]}, "create_time": 1762000000}}}},
        {"이상한": "대화"}], ensure_ascii=False), encoding="utf-8")
    old = os.environ.get("CONCEPT_INBOX")
    os.environ["CONCEPT_INBOX"] = str(ib)
    try:
        ok("내보내기 파일: 두 형식 읽기, 모르는 형식은 건너뜀", concept_add.import_export(export) == (3, 0, 1), str(concept_add.import_export.__name__))
        ok("내보내기 파일: 다시 가져와도 중복 없음", concept_add.import_export(export) == (0, 3, 1))
    finally:
        if old is None:
            os.environ.pop("CONCEPT_INBOX", None)
        else:
            os.environ["CONCEPT_INBOX"] = old


def check_independence():
    js = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
    ok("화면 코드는 서버 주소를 직접 부르지 않음 (api.js만)", "fetch(" not in js and "/api/" not in js)
    used = set(re.findall(r"/api/[a-z/_]+", (ROOT / "app" / "api.js").read_text(encoding="utf-8")))
    doc = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    missing = sorted(u for u in used if u.rstrip("/") not in doc)
    ok("화면이 쓰는 API는 모두 docs/API.md에 있음", not missing, ", ".join(missing))
    ok("화면에 대화 글을 HTML로 넣지 않음", "innerHTML" not in js)
    kit = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "kit").glob("*.py"))
    ok("서버는 화면 파일을 모름", "app.js" not in kit and "style.css" not in kit)
    server_imports = (ROOT / "kit" / "serve.py").read_text(encoding="utf-8")
    ok("서버 본체는 Kiwi·검증기를 위로 불러오지 않음", not re.search(r"^(import|from) (verify_note|study_worker)", server_imports, re.M))
    demo = json.loads((ROOT / "app" / "demo.json").read_text(encoding="utf-8"))
    ok("서버 없이 도는 데모 데이터가 있음", "/api/study/today" in demo and "/api/health" in demo)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def check_server(tmp):
    ib, db = tmp / "srv.jsonl", tmp / "srv.sqlite"
    lines = [{"v": 1, "source": "claude-code", "role": "user", "session_id": "a", "ts": "2026-11-09T10:00:00+09:00", "text": "도커가 뭐야?"},
             {"v": 1, "source": "claude-code", "role": "assistant", "session_id": "a", "ts": "2026-11-09T10:00:05+09:00", "text": "Docker와 GitHub Actions를 추천합니다. 설치를 통과했습니다."}]
    ib.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
    port = free_port()
    p = subprocess.Popen([sys.executable, str(ROOT / "kit" / "serve.py"), "--inbox", str(ib), "--db", str(db), "--port", str(port), "--searx", "off", "--web", str(ROOT / "app"), "--llm", "ollama:없는모델"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ, PYTHONUTF8="1"))
    base = f"http://127.0.0.1:{port}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(path, body, headers=None):
        h = {"Content-Type": "application/json"} if headers is None else headers
        req = urllib.request.Request(base + path, json.dumps(body).encode("utf-8"), h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, {}
    try:
        for _ in range(240):
            try:
                if get("/api/status")["turns"] >= 1:
                    break
            except OSError:
                pass
            time.sleep(0.25)
        d = get("/api/study/today?k=20")
        labels = [x["label"] for x in d["items"]]
        ok("오늘 공부에 기술 이름만", "Docker" in labels and "GitHub" in labels and not {"추천", "통과", "설치", "Actions"} & set(labels), ", ".join(labels))
        o = d["items"][0].get("origin") or {}
        ok("카드에 처음 만난 질문 (누르면 그 답변이 열림)", o.get("question") == "도커가 뭐야?" and get("/api/answers/" + urllib.parse.quote(o.get("answer", "x")))["question"] == "도커가 뭐야?", str(o))
        gs = d.get("groups") or [{}]
        ok("오늘 공부는 질문별 묶음 (질문 하나에 개념, 펼친 것은 3개까지)", gs[0].get("question") == "도커가 뭐야?" and {"Docker", "GitHub"} <= {x["label"] for g in gs for x in g["items"]}
           and all(len(g["items"]) <= study_api.CORE for g in gs) and d["counts"]["questions"] == 1, str([(g.get("question"), len(g.get("items", []))) for g in gs]))
        cid = d["items"][0]["id"]
        c = get("/api/study/concept/" + urllib.parse.quote(cid))
        ok("개념 노트에도 처음 만난 질문과 분야 칸", (c.get("origin") or {}).get("question") == "도커가 뭐야?" and "field" in c)
        ok("개념 노트 계약", all(k in c for k in ("label", "gate", "progress", "note", "forms", "records", "related", "sources")))
        ok("LLM이 없어도 노트 화면이 응답", c["note"]["status"] in ("none", "rejected"))
        ok("근거가 없으면 설명을 만들지 않음", not c.get("definition") and not c["note"].get("easy"))
        ok("LLM 없음을 상태로 알림", get("/api/health")["llm"]["available"] is False)
        status, _ = post(f"/api/study/concept/{urllib.parse.quote(cid)}/progress", {"status": "known"})
        d2 = get("/api/study/today?k=20")
        ok("이해함 표시 → 오늘 목록에서 빠짐", status == 200 and cid not in [x["id"] for x in d2["items"]] and d2["counts"]["known"] == 1)
        status, _ = post(f"/api/study/concept/{urllib.parse.quote(cid)}/progress", {"status": "이상한값"})
        ok("잘못된 값은 400", status == 400)
        hid = get("/api/study/concepts?view=hidden&k=50")["items"]
        word = next(x for x in hid if x["label"] == "추천")
        post(f"/api/study/concept/{urllib.parse.quote(word['id'])}/feedback", {"verdict": "concept"})
        ok("사용자 판단이 관문보다 앞섬", "추천" in [x["label"] for x in get("/api/study/concepts?view=show&k=50")["items"]])
        status, _ = post("/api/ingest", {"text": "컨테이너는 격리된 실행 환경이다."}, {"Content-Type": "application/json", "Origin": "https://evil.example"})
        ok("다른 사이트의 기록 요청 차단", status == 403)
        status, _ = post("/api/ingest", {"text": "x"}, {"Content-Type": "text/plain"})
        ok("JSON이 아닌 기록 요청 차단", status == 415)
        status, r = post("/api/ingest", {"text": "컨테이너는 격리된 실행 환경이다."})
        ok("붙여넣기 API", status == 200 and r["added"] is True)
        for _ in range(60):
            if len(get("/api/answers?k=5")["items"]) == 2:
                break
            time.sleep(0.25)
        a = get("/api/answers?k=5")["items"]
        ok("답변 목록에 붙여넣은 글이 나타남", len(a) == 2 and a[0]["source"] == "paste", str(len(a)))
        full = get("/api/answers/" + a[-1]["id"])
        ok("답변 원문·내 질문·개념 표시", full["question"] == "도커가 뭐야?" and "Docker" in full["text"] and any(t["label"] == "Docker" for t in full["terms"]) and not any(t["label"] == "설치" for t in full["terms"]))
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            ok("화면 파일을 서버가 그대로 내줌", "개념 차트" in r.read().decode("utf-8"))
        req = urllib.request.Request(base + "/api/study/today", headers={"Host": "evil.example"})
        try:
            urllib.request.urlopen(req, timeout=5)
            ok("외부 Host 차단", False)
        except urllib.error.HTTPError as e:
            ok("외부 Host 차단", e.code == 403)
    finally:
        p.kill()
        p.wait()
    con = sqlite3.connect(db)
    ok("판정·진도는 색인을 다시 만들어도 남는 표에 있음", not ({"judgments", "progress", "study_notes", "answer_summaries", "jobs"} & set(serve.DERIVED)))
    con.close()


def check_warm(tmp):
    """(0.6.6) 공부 목록 전체가 정의 수집 대상, 모델 노트는 상위 WARM_TOP만"""
    con = serve.open_db(tmp / "w.sqlite")
    words = ["Docker", "GitHub", "PyTorch"]
    saved = serve.leaderboard, serve.WARM_TOP
    try:
        serve.leaderboard = lambda con, k=50, project=None: {"items": [{"id": w.lower(), "label": w, "sessions": 3 - i, "turns": 1, "last_seen": ""} for i, w in enumerate(words)], "n_sessions": 3, "n_concepts": 3}
        serve.WARM_TOP = 1
        top, rest = serve.warm_targets(con, ai=False)
        ok("상위 개념은 정의·노트, 나머지 공부 목록은 정의만 준비", top == ["docker"] and rest == ["github", "pytorch"], f"{top} {rest}")
        words[:] = ["pyarrow"]
        con.execute("INSERT INTO answers VALUES ('a1', 's', 't', 'x', '```python\nimport pyarrow\n```', NULL)")
        con.commit()
        ok("코드 이름 전: LLM 판정 없으면 숨김", study_api.gate_of(con, "pyarrow", "pyarrow")["show"] is False)
        serve.warm_targets(con, ai=False)
        ok("뒤에서 코드 이름을 한 번 계산해 저장 → 공부 목록에", con.execute("SELECT code FROM judgments WHERE concept='pyarrow'").fetchone() == (1,)
           and study_api.gate_of(con, "pyarrow", "pyarrow")["by"] == "code" and study_api.gate_of(con, "pyarrow", "pyarrow")["show"])
    finally:
        serve.leaderboard, serve.WARM_TOP = saved
        con.close()


def check_feedback(tmp):
    """지속 검증: 사용자 판단('맞아요·아니에요')과 사용자 판단을 뺀 관문 판정을 비교한다 (dev.py verify가 쓰는 study_api.feedback_check)"""
    con = serve.open_db(tmp / "f.sqlite")
    con.executemany("INSERT INTO forms VALUES (?,?,1)", [("추천", "추천"), ("docker", "Docker")])
    con.commit()
    study_api.set_feedback(con, "추천", "concept")
    ok("사용자 판단을 뺀 관문 판정: 추천은 관문만으로는 숨김", study_api.gate_of(con, "추천", "추천", use_user=False)["show"] is False and study_api.gate_of(con, "추천", "추천")["by"] == "user")
    fb = study_api.feedback_check(con)
    ok("지속 검증: 관문이 숨겼는데 사용자가 '맞아요'한 낱말을 셈", fb["n"] == 1 and fb["missed"] == ["추천"] and fb["precision"] is None and fb["gold"] == {"추천": True}, fb)
    study_api.set_feedback(con, "docker", "not_concept")
    fb = study_api.feedback_check(con)
    ok("지속 검증: 관문이 보여 줬는데 '아니에요'한 낱말은 정밀도에 들어감", fb["n"] == 2 and fb["shown"] == 1 and fb["precision"] == 0.0 and fb["wrong"] == ["Docker"], fb)
    study_api.set_feedback(con, "docker", "clear")
    ok("판단 지우기 → 검증 대상에서 빠짐", study_api.feedback_check(con)["n"] == 1)
    cv = study_api.coverage(con)
    ok("설명 비율: 공부 목록(사용자 판단 포함)에서 설명 없음", cv["shown"] == 2 and cv["none"] == 2 and cv["explained"] == 0.0, cv)
    con.execute("INSERT INTO notes VALUES ('docker', 'Docker는 컨테이너 플랫폼이다.', '[]', 't')")
    con.execute("INSERT INTO study_notes VALUES ('추천', ?, 'ok', 'm', 't')", (json.dumps({"easy": "쉬운 설명"}),))
    cv = study_api.coverage(con)
    ok("설명 비율: 출처 문장·근거 확인된 설명을 셈", cv["source"] == 1 and cv["ai_checked"] == 1 and cv["explained"] == 1.0, cv)
    con.close()


def check_today_extra(tmp):
    """관문이 '더 보기'에만 내놓은 낱말(gate.extra)은 펼친 칸에 들어가지 않고, 그런 낱말만 있는 질문은 묶음이 되지 않는다"""
    old = sqlite3.connect(tmp / "x.sqlite")
    old.execute("CREATE TABLE judgments (concept TEXT PRIMARY KEY, llm INTEGER, user TEXT, updated TEXT)")   # 0.5.3까지의 판정 표
    old.execute("INSERT INTO judgments VALUES ('k', 1, NULL, 't')")
    old.commit()
    old.close()
    con = serve.open_db(tmp / "x.sqlite")
    ok("예전 판정은 남음", con.execute("SELECT llm FROM judgments WHERE concept='k'").fetchone() == (1,))
    ok("예전 DB에도 두 번째 질문 열이 생김", "everyday" in {r[1] for r in con.execute("PRAGMA table_info(judgments)")})
    pre = sqlite3.connect(":memory:")                                       # 0.7.0 전 DB를 읽기 전용으로 열 때 (dev.py verify): code 열이 없어도 멈추지 않음
    pre.execute("CREATE TABLE judgments (concept TEXT PRIMARY KEY, llm INTEGER, user TEXT, updated TEXT, everyday INTEGER)")
    pre.execute("INSERT INTO judgments VALUES ('k', 1, 'concept', 't', NULL)")
    ok("code 열이 없는 예전 DB도 읽음", study_api.judgment_row(pre, "k") == (1, "concept", None, None) and study_api.judgment_row(pre, "x") is None)
    pre.close()
    words = [("a", "q1"), ("b", "q1"), ("민법", "q1"), ("세균", "q2")]       # 세균은 q2에서만 나옴
    for w, s in words:                                                     # 같은 답변 = 같은 세션·시각
        con.execute("INSERT INTO mentions VALUES (?,?,?, 'assistant', 'x', NULL)", (w, "2026-11-10T00:00:00+00:00", s))
    board = lambda con, k, project=None: {"items": [{"id": w, "label": w, "sessions": 1, "turns": 1, "last_seen": ""} for w, _ in words], "n_sessions": 2, "n_concepts": 4}
    saved = study_api.gate_of
    try:
        study_api.gate_of = lambda con, cid, label: {"show": cid in ("a", "b"), "candidate": False, "extra": cid in ("민법", "세균"), "by": "llm", "rule": "unknown"}
        d = study_api.today(con, board, k=10)
        items = [x["id"] for g in d["groups"] for x in g["items"]]
        more = [m for g in d["groups"] for m in g["more"]]
        ok("살린 낱말은 펼친 칸에 없음", sorted(items) == ["a", "b"], str(items))
        ok("살린 낱말은 같은 질문의 더 보기에 extra로", [m["id"] for m in more] == ["민법"] and more[0]["extra"] is True, str(more))
        ok("살린 낱말만 있는 질문은 묶음이 아님, 숫자는 따로", len(d["groups"]) == 1 and d["counts"]["shown"] == 2 and d["counts"]["extra"] == 2, str(d["counts"]))
    finally:
        study_api.gate_of = saved
        con.close()


def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    os.environ["CONCEPT_CHART_LEXICON"] = str(tmp / "no-lexicon")   # 개발 PC에 사전이 있어도 CI와 같게 (띄우는 서버에도 전해진다)
    gate.load_lexicons(tmp / "no-lexicon")
    try:
        check_gate()
        check_no_lexicon_tail()
        check_lexicon()
        check_fields()
        check_grounding(tmp)
        check_llm_slot()
        check_inputs(tmp)
        check_independence()
        check_server(tmp)
        check_today_extra(tmp)
        check_feedback(tmp)
        check_warm(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n결과: {'정상' if not FAILS else '실패 ' + str(len(FAILS)) + '개: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
