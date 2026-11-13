# -*- coding: utf-8 -*-
"""뜻 고르기(0.9.2, kit/senses.py) 점검. 네트워크 없이 작은 가짜 위키백과 색인과 임시 DB로만 돈다.

    python tests/test_senses.py

- 후보: 동음이의 문서일 때만, 가리키는 문서의 첫 문장. 그 낱말을 직접 적은 문서가 앞에. 동음이의·빈 문서는 후보가 아니다.
- 고르기: 후보에 없는 제목은 받지 않는다 (지어낸 뜻이 들어오지 않게). '여기에 없어요'('')도 남는다.
- 사람이 고른 뜻은 정의를 다시 찾을 때도 그대로 쓴다 (수집기를 부르지 않는다).
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
import fetch_sources as fs  # noqa: E402
import senses  # noqa: E402
import serve  # noqa: E402

FAILS = []


def ok(name, cond, info=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (f" — {info}" if info else ""))
    if not cond:
        FAILS.append(name)


def fake_wiki():
    w = sqlite3.connect(":memory:", check_same_thread=False)
    w.execute("CREATE TABLE pages (title TEXT PRIMARY KEY, lead TEXT, disamb INTEGER)")
    w.execute("CREATE TABLE redirects (src TEXT PRIMARY KEY, dst TEXT)")
    w.executemany("INSERT INTO pages VALUES (?,?,?)", [
        ("DB", "DB는 다음 뜻을 가지고 있다.", 1),
        ("데시벨", "데시벨은 소리의 크기를 나타내는 단위이다.", 0),
        ("데이터베이스", "데이터베이스(DB)는 데이터의 체계적인 집합이다. 둘째 문장.", 0),
        ("대한민국", "대한민국은 동아시아의 나라이다.", 0),
        ("DB (동음이의)", "다른 목록", 1),
        ("커밋", "커밋은 바뀐 내용을 저장소에 기록하는 일이다.", 0)])
    return w


def main():
    fs._local = fake_wiki()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="senses-")) / "t.sqlite"
    con = serve.open_db(tmp)
    con.execute("INSERT INTO freq VALUES ('db', 5)")
    con.execute("INSERT INTO forms (concept, form, n) VALUES ('db', 'DB', 5)")
    con.commit()
    links = lambda title: ["데시벨", "대한민국", "DB (동음이의)", "없는 문서", "데이터베이스"]   # noqa: E731

    got = senses.candidates(con, "db", "DB", serve.label_of, links=links)
    titles = [c["title"] for c in got]
    ok("후보: 동음이의·없는 문서는 빼고 첫 문장만", set(titles) == {"데시벨", "대한민국", "데이터베이스"} and all("둘째" not in c["text"] for c in got), str(got))
    ok("후보: 그 낱말을 직접 적은 문서가 맨 앞", titles[0] == "데이터베이스", str(titles))
    ok("후보: 한 번 만들면 저장해 두고 씀 (다시 묻지 않음)", senses.candidates(con, "db", "DB", serve.label_of, links=lambda t: 1 / 0) == got)
    ok("후보: 동음이의 문서가 아니면 없음", senses.candidates(con, "commit", "커밋", serve.label_of, links=links) == [])

    try:
        senses.pick(con, "db", "지어낸 뜻")
        ok("고르기: 후보에 없는 제목은 거절", False)
    except ValueError:
        ok("고르기: 후보에 없는 제목은 거절", True)
    ok("고르기 전: 고른 적 없음", senses.picked(con, "db") is None)
    d, src = senses.pick(con, "db", "데이터베이스")
    ok("고르기: 출처 링크와 함께 정의", d.startswith("데이터베이스(DB)는") and src[0]["url"].startswith("https://ko.wikipedia.org/wiki/"), str(src))

    def boom(*a, **k):
        raise AssertionError("수집기를 부르면 안 됨")
    got = serve.collect_note(con, "db", boom)
    ok("다시 찾을 때: 사람이 고른 뜻을 그대로 (수집기 안 부름)", got[0] == d, str(got))

    senses.pick(con, "db", "")
    ok("'여기에 없어요'도 남음", senses.picked(con, "db") == ("", []))
    con.close()
    print(f"\n결과: {'정상' if not FAILS else '실패 ' + str(len(FAILS)) + '개: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
