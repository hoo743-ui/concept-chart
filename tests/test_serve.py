# -*- coding: utf-8 -*-
"""kit/serve.py 점검: 이어 읽기·역할 필터·파일 교체·순위·카드·HTTP API·SSE (임시 폴더에서만, 네트워크 없음)

    python tests/test_serve.py
"""
import json
import pathlib
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
import serve  # noqa: E402

FAILS = []
NOW = serve.parse_ts("2026-11-08T12:00:00+09:00")
ROLES = {"assistant", "subagent"}


def ok(name, cond, info=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (f" — {info}" if info else ""))
    if not cond:
        FAILS.append(name)


def rec(ts, sess, text, role="assistant"):
    return json.dumps({"v": 1, "source": "claude-code", "ts": ts, "role": role, "session_id": sess,
                       "text": text, "truncated": False}, ensure_ascii=False) + "\n"


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    inbox, db = tmp / "inbox.jsonl", tmp / "db.sqlite"
    try:
        inbox.write_text(
            rec("2026-11-01T10:00:00+09:00", "s1", "어텐션은 문맥을 본다. 임베딩이 입력이다.\n```python\nimport torch\n```")
            + rec("2026-11-06T10:00:00+09:00", "s2", "어텐션 가중치를 시각화한다.")
            + rec("2026-11-07T10:00:00+09:00", "s3", "사용자만 쓴 단어 파이프라인", role="user")
            + rec("2026-11-07T11:00:00+09:00", "s3", "KeyError가 나면 어텐션 마스크를 본다."),
            encoding="utf-8")
        con = serve.open_db(db)
        n = serve.ingest(con, inbox, ROLES)
        ok("이어 읽기: AI 답변만 색인", n == 3, f"{n}턴")
        lb = serve.leaderboard(con, now=NOW)
        top = lb["items"][0]
        ok("1위 = 세 세션에 나온 개념", top["label"] == "어텐션" and top["sessions"] == 3, top["label"])
        labels = [x["label"] for x in lb["items"]]
        ok("사용자 글은 세지 않음", "파이프라인" not in labels)
        ok("붙은 명사·접미사 합치기 + 코드 용어", {"가중치", "시각화", "torch", "KeyError"} <= set(labels), ", ".join(labels))
        ok("세션 수 = 3", lb["n_sessions"] == 3)

        with open(inbox, "a", encoding="utf-8") as f:            # 쓰다 만 줄: 아직 안 읽어야 함
            f.write(rec("2026-11-08T09:00:00+09:00", "s4", "트랜스포머 구조").rstrip("\n"))
        ok("쓰다 만 줄은 기다림", serve.ingest(con, inbox, ROLES) == 0)
        with open(inbox, "a", encoding="utf-8") as f:
            f.write("\nnot json\n")
        ok("줄이 끝나면 읽음 (깨진 줄은 건너뜀)", serve.ingest(con, inbox, ROLES) == 1)

        card = serve.concept_card(con, serve.norm_key("어텐션"))
        ok("클릭 카드: 기록 3개 + 다음 커서", len(card["records"]) == 3 and card["next_cursor"], card["records"][0]["snippet"])
        more = serve.concept_card(con, serve.norm_key("어텐션"), card["next_cursor"])
        ok("더 보기: 남은 기록", len(more["records"]) == 0 or more["records"][0] != card["records"][0])
        ok("카드 크기 2KB 이하", len(json.dumps(card, ensure_ascii=False).encode("utf-8")) <= 2048)

        # 위키백과 응답 흉내: 동음이의 문서 제외, 띄어쓰기만 다른 제목 허용, 다른 제목 거부 (네트워크 없음)
        import fetch_sources as fs
        real_wiki = fs.wikipedia
        pages = {"파인튜닝": [{"url": "https://example.org/f", "text": "딥 러닝에서 파인 튜닝은 모델을 새로운 작업에 특화시키는 과정이다.", "title": "파인 튜닝", "src": "wikipedia"}],
                 "에이피": [{"url": "https://example.org/a", "text": "AP 통신은 미국의 통신사이다.", "title": "AP 통신", "src": "wikipedia"}]}
        fs.wikipedia = lambda term, lang="ko": pages.get(term, []) if lang == "ko" else []
        try:
            d, s = serve.fetch_note("파인튜닝")
            ok("띄어쓰기만 다른 문서 제목은 받음", "파인 튜닝" in d and len(s) == 1, d)
            d, s = serve.fetch_note("에이피")
            ok("이름이 다른 문서는 받지 않음", d == "" and s == [], d)
            d, s = serve.fetch_note("없는말")
            ok("문서가 없으면 빈 값", d == "" and s == [])
        finally:
            fs.wikipedia = real_wiki

        # 위키백과에 없으면 SearXNG, 위험한 링크 거르기, SearXNG가 꺼져 있으면 예외 (저장 안 하고 재시도)
        real_wiki, real_searx = fs.wikipedia, fs.searxng
        fs.wikipedia = lambda term, lang="ko": []
        try:
            fs.searxng = lambda term, base: [{"url": "https://example.org/e", "text": "임베딩은 단어를 벡터로 바꾸는 방법이다.", "src": "searxng"}]
            d, s = serve.fetch_note("임베딩", searx="http://localhost:8888")
            ok("위키백과에 없으면 SearXNG로 채움", d.startswith("임베딩은") and s[0]["url"] == "https://example.org/e", d)
            d, s = serve.fetch_note("임베딩")
            ok("--searx off면 검색하지 않음", d == "" and s == [])
            fs.searxng = lambda term, base: [{"url": "javascript:alert(1)", "text": "임베딩은 단어를 벡터로 바꾸는 방법이다.", "src": "searxng"}]
            d, s = serve.fetch_note("임베딩", searx="http://localhost:8888")
            ok("http(s)가 아닌 링크는 버림", d == "" and s == [])

            def down(term, base):
                raise OSError("연결 거부")
            fs.searxng = down
            try:
                serve.fetch_note("임베딩", searx="http://localhost:8888")
                ok("SearXNG가 꺼져 있으면 예외", False)
            except OSError:
                ok("SearXNG가 꺼져 있으면 예외", True)
        finally:
            fs.wikipedia, fs.searxng = real_wiki, real_searx

        # 한 줄 요약: 실제 위키백과 문장 (2026-11-08 응답)
        line = serve.one_line("딥 러닝에서 파인 튜닝(fine-tuning)은 하나의 작업을 위해 설계된 모델(상위 작업)을 새로운 작업(하위 작업)에 특화시키는 과정이다.")
        ok("한 줄 요약: 괄호 설명 제거", line == "딥 러닝에서 파인 튜닝은 하나의 작업을 위해 설계된 모델을 새로운 작업에 특화시키는 과정이다.", line)
        line = serve.one_line("API(application programming interface 애플리케이션 프로그래밍 인터페이스[*], 응용 프로그램 프로그래밍 인터페이스)는 컴퓨터 사이의 연결이다.")
        ok("한 줄 요약: 괄호 안 괄호", line == "API는 컴퓨터 사이의 연결이다.", line)
        line = serve.one_line("가나다 " * 50)
        ok("한 줄 요약: 길면 낱말 경계에서 자름", len(line) <= serve.SUMMARY_MAX + 1 and line.endswith("다…"), line)
        ok("한 줄 요약: 없으면 None", serve.one_line("") is None)

        real_get = fs._get
        fs._get = lambda url, **k: (json.dumps(["임베딩", ["임베딩"], [""], ["https://ko.wikipedia.org/wiki/x"]])
                                    if "opensearch" in url else
                                    json.dumps({"type": "disambiguation", "extract": "임베딩은 아래 항목을 함의한다.", "title": "임베딩"}))
        try:
            ok("동음이의 안내 문서는 정의로 쓰지 않음", fs.wikipedia("임베딩") == [])
        finally:
            fs._get = real_get

        inbox.write_text(rec("2026-11-08T10:00:00+09:00", "n1", "새 파일의 양자화 이야기."), encoding="utf-8")
        serve.ingest(con, inbox, ROLES)
        labels = [x["label"] for x in serve.leaderboard(con, now=NOW)["items"]]
        ok("인박스가 새로 만들어지면 처음부터 다시", "양자화" in labels and "어텐션" not in labels, ", ".join(labels))
        con.close()

        # ---- HTTP + SSE ----
        st = serve.State(str(db), str(inbox), ROLES, None)
        srv = serve.make_server(st, port=0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        threading.Thread(target=serve.tail_loop, args=(st, 0.2), daemon=True).start()
        note_calls = []

        def fake_note(term, aliases=()):                         # 네트워크 없이 정의 수집 흉내
            note_calls.append(term)
            if term == "양자화":
                return "양자화는 연속적인 값을 띄엄띄엄한 값으로 근사하는 과정이다.", [{"text": "근거 문장", "url": "https://example.org/q"}]
            if term == "파일":
                raise OSError("네트워크 끊김")
            return "", []
        threading.Thread(target=serve.note_loop, args=(st, fake_note), daemon=True).start()
        try:
            code, d = get(port, "/api/leaderboard?k=5")
            ok("GET /api/leaderboard", code == 200 and d["items"], d["items"][0]["label"])
            code, d = get(port, "/api/concept/" + urllib.request.quote(serve.norm_key("양자화")))
            ok("GET /api/concept/{id}", code == 200 and d["label"] == "양자화")
            cid = "/api/concept/" + urllib.request.quote(serve.norm_key("양자화"))
            ok("처음 누르면 기다리지 않고 수집 예약", d["note_status"] in ("pending", "ready"), d["note_status"])

            def wait_note(path, want):
                for _ in range(50):
                    _, card = get(port, path)
                    if card["note_status"] == want:
                        return card
                    time.sleep(0.1)
                return card
            d = wait_note(cid, "ready")
            ok("수집 후 카드에 정의·출처가 채워짐", d["definition"].startswith("양자화는") and d["sources"][0]["url"].startswith("https://"), d["note_status"])
            ok("카드에 한 줄 요약", d["summary"] == d["definition"], d["summary"])
            n_calls = len(note_calls)
            get(port, cid)
            ok("저장된 정의는 다시 수집하지 않음", len(note_calls) == n_calls)

            # 근거 없음·실패 ('이야기'·'파일'은 위 인박스에 이미 색인된 개념)
            none_path = "/api/concept/" + urllib.request.quote("이야기")
            d = wait_note(none_path, "none")
            ok("근거가 없으면 none", d["note_status"] == "none" and d["definition"] is None and d["sources"] == [], d["note_status"])
            fail_term = "파일"
            fail_path = "/api/concept/" + urllib.request.quote(fail_term)
            d = wait_note(fail_path, "failed")
            ok("수집 실패는 failed", d["note_status"] == "failed", d["note_status"])
            n_fail = note_calls.count(fail_term)
            get(port, fail_path)
            time.sleep(0.4)
            ok("실패 직후 다시 눌러도 재시도하지 않음", note_calls.count(fail_term) == n_fail == 1, f"{n_fail}번")
            con = serve.open_db(db)
            ok("실패는 저장하지 않음 (나중에 다시 시도)",
               not con.execute("SELECT 1 FROM notes WHERE concept=?", (fail_term,)).fetchone())
            serve.reset(con)
            ok("--rebuild 해도 정의는 남음", con.execute("SELECT COUNT(*) FROM notes").fetchone()[0] >= 1)
            con.close()
            for _ in range(50):                                  # 지운 색인을 서버가 처음부터 다시 읽을 때까지 기다림
                _, s = get(port, "/api/status")
                if s["turns"] >= 1:
                    break
                time.sleep(0.1)
            try:
                get(port, "/api/concept/" + urllib.request.quote("없는개념"))
                ok("없는 개념은 404", False)
            except urllib.error.HTTPError as e:
                ok("없는 개념은 404", e.code == 404)
            code, d = get(port, "/api/status")
            ok("GET /api/status", code == 200 and d["turns"] >= 1)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
                ok("GET / 내장 화면", "개념 차트" in r.read().decode("utf-8"))

            got = []

            def listen():
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events", timeout=10) as r:
                    for line in r:
                        got.append(line.decode("utf-8").strip())
                        if len([g for g in got if g.startswith("event: update")]) >= 2:
                            return
            th = threading.Thread(target=listen, daemon=True)
            th.start()
            time.sleep(0.5)
            with open(inbox, "a", encoding="utf-8") as f:
                f.write(rec("2026-11-08T11:00:00+09:00", "n2", "증류 모델 이야기."))
            th.join(timeout=8)
            ok("SSE: 연결 시 1번 + 새 기록 색인 후 1번 더", len([g for g in got if g.startswith("event: update")]) >= 2)
            code, d = get(port, "/api/leaderboard?k=10")
            ok("서버가 1초 주기로 이어 읽음", "증류" in [x["label"] for x in d["items"]])
        finally:
            st.stop.set()
            srv.shutdown()
            srv.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n결과: {'정상' if not FAILS else '실패 ' + str(len(FAILS)) + '개'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
