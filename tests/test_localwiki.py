# -*- coding: utf-8 -*-
"""이 PC 안 위키백과 색인(0.8.2, lexicons/kowiki_dump.py) 점검. 네트워크 없이 작은 가짜 색인과 위키 문법 조각으로만 돈다.

    python tests/test_localwiki.py

- 첫 문단 뽑기: 틀·각주·표·그림을 걷고 링크는 글자만, 첫 문단만.
- 찾기: 정확한 제목 · 넘겨주기 · 대소문자 · 띄어쓰기만 다른 제목 · '낱말 (기술 분야)' 제목. 동음이의 문서와 기술 아닌 괄호는 받지 않는다.
- 색인이 있으면 한국어는 온라인으로 묻지 않는다.
"""
import pathlib
import sqlite3
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "lexicons"))
import fetch_sources as fs  # noqa: E402
import kowiki_dump as kd  # noqa: E402

FAILS = []


def ok(name, cond, info=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (f" — {info}" if info else ""))
    if not cond:
        FAILS.append(name)


def clean():
    t = ("{{다른 뜻|커밋}}\n[[파일:Git.png|섬네일|그림 [[깃]]]]\n'''커밋'''(commit, {{lang|en|commit}})은 [[버전 관리|버전 관리 시스템]]에서 "
         "바뀐 내용을 저장소에 기록하는 일이다.<ref>출처</ref> {{각주 필요}}\n\n== 역사 ==\n둘째 문단.")
    got = kd.clean(t)
    ok("틀·그림·각주를 걷고 링크는 글자만", got == "커밋(commit)은 버전 관리 시스템에서 바뀐 내용을 저장소에 기록하는 일이다.", got)
    ok("첫 문단만 (제목 아래 문단은 안 씀)", "둘째" not in got)
    ok("표만 있는 글은 빈 문단", kd.clean("{| class=wikitable\n|-\n| 칸 |}\n") == "")


def lookup():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="kowiki-")) / "kowiki.sqlite"
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE pages (title TEXT PRIMARY KEY, lead TEXT, disamb INTEGER)")
    con.execute("CREATE TABLE redirects (src TEXT PRIMARY KEY, dst TEXT)")
    con.executemany("INSERT INTO pages VALUES (?,?,?)", [
        ("그래픽 처리 장치", "그래픽 처리 장치(GPU)는 그림을 빠르게 그리는 처리 장치이다.", 0),
        ("파인 튜닝", "파인 튜닝은 학습된 모델을 새 데이터로 조금 더 학습하는 방법이다.", 0),
        ("커밋 (버전 관리)", "커밋은 바뀐 내용을 저장소에 기록하는 일이다.", 0),
        ("커밋 (낚시)", "낚시의 커밋은 다른 뜻이다.", 0),
        ("캐시", "캐시는 다음 뜻으로 쓰인다.", 1),
        ("Python", "파이썬은 프로그래밍 언어이다.", 0),
        ("KIWI", "KIWI는 라디오 방송국이다.", 0),
        ("최적화", "최적화는 다음을 가리키는 말이다:", 0),
        ("I-D", "I-D는 인터넷 초안이다.", 0)])
    con.execute("INSERT INTO redirects VALUES ('GPU', '그래픽 처리 장치')")
    kd.add_norm(con)
    con.close()
    real_local, real_get = fs._local, fs._get
    calls = []
    fs._local = sqlite3.connect(f"file:{tmp.as_posix()}?mode=ro", uri=True)
    fs._get = lambda url, *a, **k: calls.append(url) or (_ for _ in ()).throw(OSError("온라인 금지"))
    try:
        got = fs.wikipedia_exact("GPU")
        ok("넘겨주기를 따라 정의", got and got[0]["title"] == "그래픽 처리 장치" and got[0]["url"].startswith("https://ko.wikipedia.org/wiki/"), str(got))
        ok("첫 글자 대소문자만 바꿔 봄 (python → Python)", (fs.wikipedia_exact("python") or [{}])[0].get("title") == "Python")
        ok("모두 대문자인 다른 제목은 아님 (Kiwi ≠ KIWI)", fs.wikipedia_exact("Kiwi") == [])
        ok("동음이의 문서는 받지 않음", fs.wikipedia_exact("캐시") == [])
        ok("없는 제목은 빈 목록", fs.wikipedia_exact("없는낱말") == [])
        ok("띄어쓰기만 다른 제목", (fs.wikipedia("파인튜닝") or [{}])[0].get("title") == "파인 튜닝")
        got = fs.wikipedia_tech("커밋")
        ok("기술 분야 괄호 제목만 (낚시는 아님)", got and got[0]["title"] == "커밋 (버전 관리)", str(got))
        ok("'다음을 가리키는 말이다:' 문서는 동음이의로 보고 받지 않음", fs.wikipedia_exact("최적화") == [] and fs.wikipedia("최적화") == [])
        ok("영어 표기는 붙임표만 다른 제목을 받지 않음 (ID ≠ I-D)", fs.wikipedia("ID") == [])
        lead = fs.wikipedia_lead("GPU")
        ok("첫 문장을 정의로", lead and lead[0]["text"].startswith("그래픽 처리 장치(GPU)는"), str(lead))
        ok("색인이 있으면 한국어는 온라인으로 묻지 않음", not [u for u in calls if "ko.wikipedia" in u], str(calls))
    finally:
        fs._local.close()
        fs._local, fs._get = real_local, real_get


def main():
    clean()
    lookup()
    print("\n결과:", "모두 통과" if not FAILS else f"실패 {len(FAILS)}개: {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
