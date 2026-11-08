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
        try:
            code, d = get(port, "/api/leaderboard?k=5")
            ok("GET /api/leaderboard", code == 200 and d["items"], d["items"][0]["label"])
            code, d = get(port, "/api/concept/" + urllib.request.quote(serve.norm_key("양자화")))
            ok("GET /api/concept/{id}", code == 200 and d["label"] == "양자화")
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
