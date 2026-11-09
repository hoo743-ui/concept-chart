# -*- coding: utf-8 -*-
"""kit/serve.py 점검: 이어 읽기·역할 필터·파일 교체·순위·카드·HTTP API·SSE (임시 폴더에서만, 네트워크 없음)

    python tests/test_serve.py
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
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
        # NOW = 11-08 12:00. 어텐션 세션: 11-01 10:00(7.1일 전), 11-06(2.1일 전), 11-07(1일 전)
        ok("최근 2주 세션 수", top["recent_sessions"] == 3, str(top["recent_sessions"]))
        ok("주별 막대: 오래된 주 → 이번 주", top["weekly"] == [0, 0, 0, 0, 0, 0, 1, 2], str(top["weekly"]))

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

        # 정의가 없을 때 내 대화 문장
        line = card["chat_line"]
        ok("정의가 없으면 개념으로 시작하는 내 대화 문장", line and line["text"] == "어텐션은 문맥을 본다.", str(line))
        ok("코드에서만 나온 개념은 엉뚱한 문장을 안 보여 줌", serve.concept_card(con, "torch")["chat_line"] is None)
        serve.save_note(con, serve.norm_key("어텐션"), "어텐션은 정의 문장이다.", [])
        ok("정의가 있으면 대화 문장을 쓰지 않음", serve.concept_card(con, serve.norm_key("어텐션"))["chat_line"] is None)
        con.execute("DELETE FROM notes")
        con.commit()

        # 개념이 아닌 조각 빼기 (순위판에 cu·GB·https가 올라오던 문제)
        def terms(s):
            return {k for _, cs in serve.extract(s) for k in cs}
        got = terms("cu121로 받고 py3를 쓴다. 메모리는 8GB이고 16 GB도 된다. 주소는 https로 시작하고 www도 붙는다. 2FA를 켠다.")
        ok("숫자 조각·단위·주소 조각은 개념이 아님", not ({"cu", "py", "gb", "https", "www", "fa"} & got), ", ".join(sorted(got)))
        got = terms("GPT4와 Python3를 쓰고 HTTPS와 HTTP와 API와 GPU 메모리를 본다.")
        ok("이름과 대문자 용어는 남음", {"gpt", "python", "https", "http", "api", "gpu", "메모리"} <= got, ", ".join(sorted(got)))

        # 질문: 분석하지 않고 원문 저장 → 뒤따르는 답변의 개념과 연결
        qinbox, qdb = tmp / "q.jsonl", tmp / "q.sqlite"
        long_q = "왜 이럴 때 " + "어떻게 " * 200
        qinbox.write_text(
            rec("2026-11-08T09:00:00+09:00", "q1", "배포가 자꾸 실패하는데 왜 그래?", role="user")
            + rec("2026-11-08T09:01:00+09:00", "q1", "컨테이너 로그를 보세요. 컨테이너 설정도 보세요.")
            + rec("2026-11-08T09:02:00+09:00", "q2", "어텐션 답변")
            + rec("2026-11-08T09:03:00+09:00", "q3", long_q, role="user")
            + rec("2026-11-08T09:04:00+09:00", "q3", "가중치 답변"),
            encoding="utf-8")
        qc = serve.open_db(qdb)
        ok("질문은 턴 수에 안 들어감", serve.ingest(qc, qinbox, ROLES) == 3)
        ok("질문 원문 그대로 저장", qc.execute("SELECT text FROM questions ORDER BY id LIMIT 1").fetchone()[0] == "배포가 자꾸 실패하는데 왜 그래?")
        ok("질문의 낱말은 개념이 아님", not qc.execute("SELECT 1 FROM freq WHERE concept=?", ("배포",)).fetchone())
        cc = serve.concept_card(qc, serve.norm_key("컨테이너"))
        ok("답변의 개념이 내 질문과 연결", cc["records"][0]["question"] == "배포가 자꾸 실패하는데 왜 그래?", str(cc["records"][0]["question"]))
        ok("답변 하나에 개념 1행", len(cc["records"]) == 1, f"{len(cc['records'])}행")
        # 경합: 카드를 읽은 직후 정의가 저장돼도 'ready인데 정의 없음'이 나가면 안 된다 (CI에서 가끔 나던 버그)
        real_card = serve.concept_card
        race_id = serve.norm_key("컨테이너")

        def card_then_save(c, concept, cursor=None, k=3, project=None):
            out = real_card(c, concept, cursor, k, project)
            serve.save_note(c, concept, "컨테이너는 격리된 실행 환경이다.", [])
            return out
        serve.concept_card = card_then_save
        try:
            r = serve.card_response(serve.State(str(qdb), str(qinbox), ROLES, None), qc, race_id)
        finally:
            serve.concept_card = real_card
        ok("카드와 저장이 겹쳐도 ready인데 정의 없음은 없음", not (r["note_status"] == "ready" and r["definition"] is None), r["note_status"])
        qc.execute("DELETE FROM notes")
        qc.commit()
        ok("다른 세션의 질문과 섞이지 않음", serve.concept_card(qc, serve.norm_key("어텐션"))["records"][0]["question"] is None)
        ok("카드의 긴 질문은 잘림 (원문은 DB에)",
           len(serve.concept_card(qc, serve.norm_key("가중치"))["records"][0]["question"]) == serve.QUESTION_MAX
           and qc.execute("SELECT MAX(length(text)) FROM questions").fetchone()[0] > serve.QUESTION_MAX)
        qc.close()

        # 예전 구조의 DB: 색인만 다시 만들고 정의는 남긴다
        odb = tmp / "old.sqlite"
        oc = serve.sqlite3.connect(odb)
        oc.executescript("""CREATE TABLE mentions (concept TEXT, ts TEXT, session TEXT, role TEXT, snippet TEXT);
            INSERT INTO mentions VALUES ('a','t','s','assistant','x');
            CREATE TABLE notes (concept TEXT PRIMARY KEY, definition TEXT, sources TEXT, updated TEXT);
            INSERT INTO notes VALUES ('a','정의','[]','t');""")
        oc.close()
        oc = serve.open_db(odb)
        ok("구조가 바뀌면 색인을 다시 만듦 (정의는 남김)",
           oc.execute("SELECT COUNT(*) FROM mentions").fetchone()[0] == 0
           and oc.execute("SELECT definition FROM notes").fetchone()[0] == "정의"
           and "question" in [r[1] for r in oc.execute("PRAGMA table_info(mentions)")])
        oc.close()
        oc = serve.open_db(odb)
        ok("같은 구조면 다시 열어도 유지", oc.execute("SELECT definition FROM notes").fetchone()[0] == "정의")
        oc.execute("BEGIN IMMEDIATE")                            # 색인이 쓰는 중이라고 가정
        oc.execute("INSERT INTO meta VALUES ('x','y')")
        reader = serve.sqlite3.connect(odb, timeout=0.2)         # 잠금 대기를 짧게 해서 막히면 바로 실패
        reader.close()
        t0 = time.time()
        try:
            rc = serve.open_db(odb)
            rc.execute("SELECT COUNT(*) FROM notes").fetchone()
            rc.close()
            ok("쓰는 중에도 DB를 열어 조회 가능", time.time() - t0 < 1, f"{time.time() - t0:.2f}초")
        except serve.sqlite3.OperationalError as e:
            ok("쓰는 중에도 DB를 열어 조회 가능", False, str(e))
        oc.rollback()
        oc.close()

        # 작업 폴더로 좁히기
        def prec(ts, sess, text, project):
            return json.dumps({"v": 1, "source": "claude-code", "ts": ts, "role": "assistant", "session_id": sess, "project": project,
                               "text": text, "truncated": False}, ensure_ascii=False) + "\n"
        pinbox, pdb = tmp / "p.jsonl", tmp / "p.sqlite"
        pinbox.write_text(
            prec("2026-11-07T09:00:00+09:00", "a1", "양자화는 값을 근사한다.", "C:\\work\\app")
            + prec("2026-11-07T09:30:00+09:00", "a2", "어텐션은 문맥을 본다.", "c:/work/app/sub/")
            + prec("2026-11-07T10:00:00+09:00", "b1", "컨테이너는 격리 환경이다. 양자화 이야기.", "C:/work/app2")
            + rec("2026-11-07T11:00:00+09:00", "n1", "가중치는 학습된다."),      # 폴더 정보 없는 예전 기록
            encoding="utf-8")
        pc = serve.open_db(pdb)
        serve.ingest(pc, pinbox, ROLES)
        ok("경로 표기 통일 (역슬래시·드라이브·끝 슬래시)", serve.norm_project("c:\\work\\app\\") == "C:/work/app" and serve.norm_project("") is None)
        ok("폴더 목록은 폴더 없는 세션을 따로 셈",
           {x["path"] for x in serve.projects(pc)["items"]} == {"C:/work/app", "C:/work/app/sub", "C:/work/app2"} and serve.projects(pc)["no_project_sessions"] == 1)
        board = serve.leaderboard(pc, now=NOW, project="C:/work/app")
        got = {x["label"] for x in board["items"]}
        ok("폴더 + 하위 폴더만, 이름이 비슷한 옆 폴더는 제외", board["n_sessions"] == 2 and {"양자화", "어텐션"} <= got and not ({"컨테이너", "가중치"} & got), ", ".join(sorted(got)))
        ok("전체 순위는 그대로", serve.leaderboard(pc, now=NOW)["n_sessions"] == 4)
        only = next(x for x in board["items"] if x["label"] == "양자화")
        ok("세션·턴 수도 폴더 안에서만 셈", only["sessions"] == 1 and only["turns"] == 1, f"{only['sessions']}세션 {only['turns']}턴")
        all_q = serve.concept_card(pc, serve.norm_key("양자화"))
        app_q = serve.concept_card(pc, serve.norm_key("양자화"), project="C:/work/app")
        ok("카드 기록도 폴더로 좁힘", len(all_q["records"]) == 2 and len(app_q["records"]) == 1 and app_q["chat_line"]["text"].startswith("양자화는"))
        pc.close()
        pst = serve.State(str(pdb), str(pinbox), ROLES, None, "C:\\work\\app")
        psrv = serve.make_server(pst, port=0)
        pport = psrv.server_address[1]
        threading.Thread(target=psrv.serve_forever, daemon=True).start()
        try:
            _, d = get(pport, "/api/projects")
            ok("GET /api/projects: 기본 폴더와 목록", d["default"] == "C:/work/app" and len(d["items"]) == 3)
            _, d = get(pport, "/api/leaderboard")
            ok("--project면 처음부터 그 폴더", d["project"] == "C:/work/app" and d["n_sessions"] == 2)
            _, d = get(pport, "/api/leaderboard?project=")
            ok("project= 빈 값은 전체", d["project"] is None and d["n_sessions"] == 4)
            _, d = get(pport, "/api/leaderboard?project=" + urllib.request.quote("C:\\work\\app2"))
            ok("다른 폴더로 바꾸기 (캐시가 섞이지 않음)", d["n_sessions"] == 1 and d["items"][0]["label"] in ("컨테이너", "양자화", "이야기", "환경", "격리"))
            with urllib.request.urlopen(f"http://127.0.0.1:{pport}/", timeout=10) as r:
                ok("내장 화면에 폴더 고르기", 'id="pj"' in r.read().decode("utf-8"))
        finally:
            pst.stop.set()
            psrv.shutdown()
            psrv.server_close()

        # 백본 점검에서 찾은 문제들 (11-09)
        def fresh(name, text):
            p, d = tmp / f"{name}.jsonl", tmp / f"{name}.sqlite"
            p.write_text(text, encoding="utf-8")
            return p, d, serve.open_db(d)
        bad_lines = [{"role": "assistant", "text": 123, "session_id": "x"}, {"role": "assistant", "text": ["a"], "session_id": "x"},
                     {"role": ["assistant"], "text": "양자화"}, {"role": "assistant", "text": "양자화 설명입니다.", "session_id": ["a"]},
                     {"role": "assistant", "text": "양자화 설명입니다.", "session_id": "y", "project": {"a": 1}}, {"role": "user", "text": 5, "session_id": "z"}]
        bp, _, bc = fresh("bad", "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in bad_lines) + rec("2026-11-08T10:00:00+09:00", "ok", "트랜스포머 정상 답변입니다."))
        serve.ingest(bc, bp, ROLES)
        ok("이상한 줄을 건너뛰고 뒤의 기록까지 색인", bc.execute("SELECT 1 FROM freq WHERE concept=?", ("트랜스포머",)).fetchone() is not None
           and int(serve.meta_get(bc, "offset")) == bp.stat().st_size)
        bc.close()
        rp, _, rc = fresh("retry", rec("2026-11-08T10:00:00+09:00", "ok", "양자화 설명입니다."))
        real_extract = serve.extract

        def no_pkg(text):
            raise ImportError("kiwipiepy 없음")
        serve.extract = no_pkg
        try:
            serve.ingest(rc, rp, ROLES)
            ok("패키지 없음은 건너뛰지 않음", False)
        except ImportError:
            ok("패키지 없음은 건너뛰지 않음 (고친 뒤 이어서 읽음)", int(serve.meta_get(rc, "offset", 0)) == 0)
        finally:
            serve.extract = real_extract
        ok("패키지가 돌아오면 그 줄부터 색인", serve.ingest(rc, rp, ROLES) == 1)
        rc.close()
        sp, _, sc = fresh("same", rec("2026-11-08T10:00:00+09:00", "a", "양자화 설명입니다."))
        serve.ingest(sc, sp, ROLES)
        sp.write_text(rec("2026-11-08T10:00:00+09:00", "b", "컨테이너 설명입니다. 트랜스포머 설명입니다."), encoding="utf-8")
        ok("새 줄 확인이 파일 교체를 알아챔", serve.has_new_lines(sc, sp))
        serve.ingest(sc, sp, ROLES)
        got = {x["label"] for x in serve.leaderboard(sc, now=NOW)["items"]}
        ok("더 큰 다른 파일로 바뀌어도 처음부터 다시", "컨테이너" in got and "양자화" not in got, ", ".join(sorted(got)))
        with open(sp, "a", encoding="utf-8") as f:
            f.write(rec("2026-11-08T11:00:00+09:00", "b", "드롭아웃 설명입니다."))
        before = int(serve.meta_get(sc, "turns"))
        serve.ingest(sc, sp, ROLES)
        ok("뒤에 붙는 기록은 교체로 보지 않음", int(serve.meta_get(sc, "turns")) == before + 1)
        sc.close()
        dp, dd, dc = fresh("dbl", "".join(rec("2026-11-08T10:00:00+09:00", "s", f"양자화 설명 {i}번입니다.") for i in range(40)))
        dc.close()
        env_once = dict(os.environ, PYTHONUTF8="1")
        ps = [subprocess.Popen([sys.executable, str(ROOT / "kit" / "serve.py"), "--once", "--inbox", str(dp), "--db", str(dd)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env_once) for _ in range(2)]
        for p_ in ps:
            p_.wait()
        dc = serve.open_db(dd)
        n_turns, n_men = int(serve.meta_get(dc, "turns")), dc.execute("SELECT COUNT(*) FROM mentions WHERE concept=?", ("양자화",)).fetchone()[0]
        ok("같은 DB를 두 프로세스가 읽어도 중복으로 세지 않음", n_turns == 40 and n_men == 40, f"턴 {n_turns}, 언급 {n_men} (정답 40)")
        dc.close()
        hst = serve.State(str(pdb), str(pinbox), ROLES, None)
        hsrv = serve.make_server(hst, port=0)
        hport = hsrv.server_address[1]
        threading.Thread(target=hsrv.serve_forever, daemon=True).start()
        try:
            def with_host(host):
                c = socket.create_connection(("127.0.0.1", hport), timeout=5)
                c.sendall(f"GET /api/status HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
                data = c.recv(200)
                c.close()
                return data.split(b"\r\n")[0]
            ok("다른 Host 요청은 거부", b"403" in with_host("evil.example.com"))
            ok("localhost·127.0.0.1은 허용", all(b"200" in with_host(h) for h in (f"localhost:{hport}", f"127.0.0.1:{hport}", f"[::1]:{hport}")))
            try:
                serve.make_server(hst, port=hport)
                ok("쓰고 있는 포트는 시작 전에 알아챔", False)
            except OSError:
                ok("쓰고 있는 포트는 시작 전에 알아챔", True)
        finally:
            hst.stop.set()
            hsrv.shutdown()
            hsrv.server_close()

        # 서버 본체는 Kiwi를 불러오지 않고, 분석 프로세스는 쉬면 끝난다
        winbox, wdb = tmp / "w.jsonl", tmp / "w.sqlite"
        winbox.write_text("", encoding="utf-8")
        probe = f"""
import sys, threading, time
sys.path.insert(0, {str(ROOT / 'kit')!r})
import serve
st = serve.State({str(wdb)!r}, {str(winbox)!r}, {{'assistant'}}, None)
threading.Thread(target=serve.tail_loop, args=(st, 0.1, 1.0), daemon=True).start()
time.sleep(0.5)
print('idle_start', st.worker_starts)
with open({str(winbox)!r}, 'a', encoding='utf-8') as f:
    f.write({rec('2026-11-08T09:00:00+09:00', 'w1', '양자화 답변')!r})
for _ in range(1200):
    if st.version: break
    time.sleep(0.1)
print('version', st.version, 'starts', st.worker_starts)
for _ in range(100):
    if st.worker_closes: break
    time.sleep(0.1)
print('closes', st.worker_closes, 'kiwi', 'kiwipiepy' in sys.modules)
st.stop.set()
"""
        pr = subprocess.run([sys.executable, "-c", probe], capture_output=True, timeout=180, env=dict(os.environ, PYTHONUTF8="1"))
        out = pr.stdout.decode("utf-8", "replace")
        ok("기록이 없으면 분석 프로세스를 띄우지 않음", "idle_start 0" in out, out.replace("\n", " / ") + pr.stderr.decode("utf-8", "replace")[-200:])
        ok("새 기록이 오면 분석 프로세스가 색인", "version 1 starts 1" in out)
        ok("쉬면 분석 프로세스가 끝남", "closes 1" in out)
        ok("서버 본체는 Kiwi를 불러오지 않음", "kiwi False" in out)

        # 위키백과 응답 흉내: 동음이의 문서 제외, 띄어쓰기만 다른 제목 허용, 다른 제목 거부 (네트워크 없음)
        import fetch_sources as fs
        fs.wikipedia_tech = lambda term, lang="ko": []     # 네트워크 없이: 괄호 제목 찾기는 tests/test_study.py에서 따로 본다
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
            fs.searxng = lambda term, base, **k: [{"url": "https://example.org/e", "text": "임베딩은 단어를 벡터로 바꾸는 방법이다.", "src": "searxng"}]
            d, s = serve.fetch_note("임베딩", searx="http://localhost:8888")
            ok("위키백과에 없으면 SearXNG로 채움", d.startswith("임베딩은") and s[0]["url"] == "https://example.org/e", d)
            d, s = serve.fetch_note("임베딩")
            ok("--searx off면 검색하지 않음", d == "" and s == [])
            fs.searxng = lambda term, base, **k: [{"url": "javascript:alert(1)", "text": "임베딩은 단어를 벡터로 바꾸는 방법이다.", "src": "searxng"}]
            d, s = serve.fetch_note("임베딩", searx="http://localhost:8888")
            ok("http(s)가 아닌 링크는 버림", d == "" and s == [])

            asked = []

            def by_context(term, base, n=3, context=()):
                asked.append(list(context))
                good = {"url": "https://example.org/t", "text": "torch는 GPU를 쓰는 파이썬 딥러닝 라이브러리이다.", "src": "searxng"}
                return [good] if not context else []
            fs.searxng = by_context
            d, s = serve.fetch_note("torch", searx="http://localhost:8888", context=["GPU", "CUDA"])
            ok("맥락 2개 → 1개 → 이름만 순서로 찾기", asked == [["GPU", "CUDA"], ["GPU"], []] and d.startswith("torch는"), str(asked))
            # 실제 SearXNG에서 이름만으로 찾았을 때 나온 다른 뜻 (2026-11-08)
            fs.searxng = lambda term, base, **k: [{"url": "https://example.org/c", "text": "캐시는 현금을 뜻하는 영어 단어이다.", "src": "searxng"}]
            d, s = serve.fetch_note("캐시", searx="http://localhost:8888", context=["메모리", "서버"])
            ok("맥락 단어가 없는 결과는 다른 뜻으로 보고 버림", d == "" and s == [], d)

            def down(term, base, **k):
                raise OSError("연결 거부")
            fs.searxng = down
            try:
                serve.fetch_note("임베딩", searx="http://localhost:8888")
                ok("SearXNG가 꺼져 있으면 예외", False)
            except OSError:
                ok("SearXNG가 꺼져 있으면 예외", True)
        finally:
            fs.wikipedia, fs.searxng = real_wiki, real_searx

        # 검색 결과 문장 거르기: 실제 SearXNG 응답에서 나온 문장 (2026-11-08)
        def defs(term, text):
            return [e["text"] for e in fs.definition_sents(term, [], [{"url": "https://example.org", "text": text}])]
        ok("정의 문장은 통과", defs("랭체인", "랭체인은 언어 모델 기반의 애플리케이션을 개발하는 프레임워크입니다.") != [])
        ok("다른 언어·뜻의 문장 거름", defs("torch", "The torch sends out a powerful beam of light.") == [])
        ok("개념으로 시작하지 않으면 거름", defs("활성화 함수", "ReLU, 시그모이드 함수, 쌍곡탄젠트 함수 등이 대표적인 활성화 함수이다.") == [])
        ok("질문 문장 거름", defs("교차 검증", "1) 교차 검증은 그럼 뭔가?") == [])
        ok("잘린 문장 거름", defs("임베딩", "임베딩은 텍스트, 이미지 등의 데이터를 벡터 공간에 표현하는 기술로 LLM의 성능과 활용에 핵심적인 역할을 ...") == [])
        ok("앞 문맥이 필요한 문장 거름", defs("임베딩", "임베딩이란 위와 같이 사람이 쓰는 자연어를 벡터로 바꾼 결과를 의미합니다.") == [])
        ok("띄어쓰기만 달라도 통과", defs("조기종료", "조기 종료는 과적합이 일어나기 전 훈련을 멈추는 정규화 기법입니다.") != [])
        ok("앞 질문 떼고 통과", defs("KeyError", "KeyError란?KeyError는 파이썬 딕셔너리에서 요청한 키가 존재하지 않을 때 발생하는 내장 예외입니다.")
           == ["KeyError는 파이썬 딕셔너리에서 요청한 키가 존재하지 않을 때 발생하는 내장 예외입니다."])

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

        def fake_note(term, aliases=(), context=()):             # 네트워크 없이 정의 수집 흉내
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
                for _ in range(600):                             # CI는 Kiwi 로딩이 느릴 수 있다
                    _, card = get(port, path)
                    if card["note_status"] == want:
                        return card
                    time.sleep(0.1)
                return card
            d = wait_note(cid, "ready")
            diag = f"상태={d['note_status']} 호출={note_calls} 실패={list(st.note_failed)} 대기={list(st.note_pending)} 오류={st.note_error} 정의={d['definition']}"
            ok("수집 후 카드에 정의·출처가 채워짐", (d["definition"] or "").startswith("양자화는") and d["sources"] and d["sources"][0]["url"].startswith("https://"), diag)
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
            for _ in range(600):                                 # 지운 색인을 서버가 처음부터 다시 읽을 때까지 기다림 (분석 프로세스 시작 포함)
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
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events", timeout=60) as r:
                    for line in r:
                        got.append(line.decode("utf-8").strip())
                        if len([g for g in got if g.startswith("event: update")]) >= 2:
                            return
            th = threading.Thread(target=listen, daemon=True)
            th.start()
            time.sleep(0.5)
            with open(inbox, "a", encoding="utf-8") as f:
                f.write(rec("2026-11-08T11:00:00+09:00", "n2", "증류 모델 이야기."))
            th.join(timeout=60)
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
