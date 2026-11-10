# -*- coding: utf-8 -*-
"""'내 공부 기록에 묻기'(chat/) 점검: 답은 기록으로만, 개념 차트와 독립. 네트워크·실제 LLM 없이, 임시 폴더에서만 돈다.

    python tests/test_chat.py

- 답: 네 가지 질문(학습 순서·분야별·최근 공부·했던가)이 기록 값으로만 답하고, 없으면 '기록에 없어요'. 뜻을 지어내지 않는다.
- 질문 고르기: LLM이 사용자 글에 없는 개념 이름을 내면 버린다. LLM이 없거나 고장 나도 낱말 규칙으로 계속.
- 독립: chat/은 DB·서버 코드를 불러오지 않고 kit/에서는 llm.py만 쓴다. 쓰는 API는 docs/API.md의 읽기 API뿐. kit/는 chat/을 모른다.
- 실제 두 서버: 챗봇이 꺼져도 개념 차트는 그대로, 개념 차트가 꺼져도 챗봇은 안내 문장으로 답한다.
"""
import ast
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "chat"), str(ROOT / "kit")]
import answers  # noqa: E402
import intents  # noqa: E402

FAILS = []
APP = "http://127.0.0.1:8765"


def ok(name, cond, info=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (f" — {info}" if info else ""))
    if not cond:
        FAILS.append(name)


def concept(cid, label, progress="new", show=True, field=None, line_kind="none", question=None):
    return {"id": cid, "label": label, "progress": progress, "gate": {"show": show}, "field": field, "line_kind": line_kind,
            "origin": {"question": question, "ts": "2026-11-09T01:00:00+00:00", "answer": "a1"} if question else None}


def check_answers():
    items = [concept("docker", "Docker", "review", field="정보·통신", line_kind="source", question="도커가 뭐야?"),
             concept("민법", "민법", "known", field="법률"), concept("세포", "세포", line_kind="ai_checked"),
             concept("추천", "추천", show=False)]
    today = {"groups": [{"question": "도커가 뭐야?", "items": items[:3]}], "counts": {"shown": 3, "left": 2, "known": 1}}
    a = answers.plan(today, APP)
    ok("학습 순서: 다시 보기 → 설명 준비된 것, 내 기록이라고 밝힘", "Docker" in a["text"][1] and "세포" in a["text"][2] and "내 기록" in a["text"][-1], str(a["text"]))
    ok("학습 순서: 근거 링크는 개념 노트", all(l["href"].startswith(APP + "/#/c/") for l in a["links"]) and a["links"])
    ok("학습 순서: 개념이 없으면 그렇다고만", "없어요" in answers.plan({"groups": [], "counts": {"shown": 0}}, APP)["text"][0])
    b = answers.by_field({"items": items[:3]}, APP)
    ok("분야별: 꼬리표로 묶고 없는 것은 '분야 미정' (추측 안 함)", any(t.startswith("법률") for t in b["text"]) and any(t.startswith("분야 미정") for t in b["text"]) and "추측" in b["text"][-1], str(b["text"]))
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    hist = {"items": [{"id": "docker", "label": "Docker", "kind": "opened", "status": None, "ts": "2026-11-10T02:00:00+00:00"},
                      {"id": "민법", "label": "민법", "kind": "marked", "status": "known", "ts": "2026-11-09T02:00:00+00:00"}]}
    r = answers.recent(hist, APP, "today", now=now)
    ok("최근 공부: 오늘만 거름", len(r["links"]) == 1 and "Docker" in r["text"][1] and "열어 봄" in r["text"][1], str(r["text"]))
    ok("최근 공부: 어제 = 이해함 표시", "이해함" in answers.recent(hist, APP, "yesterday", now=now)["text"][1])
    ok("최근 공부: 기록이 없으면 없다고", "없어요" in answers.recent({"items": []}, APP, "week", now=now)["text"][0])
    allc = {"items": items}
    c = answers.check("민법", allc, hist, APP)
    ok("했던가: 이해함으로 표시한 날짜", "네" in c["text"][0] and "이해함" in c["text"][0] and "11/9" in c["text"][0], str(c["text"]))
    c = answers.check("docker", allc, hist, APP)
    ok("했던가: 열어 보기만 한 개념 + 처음 만난 질문", "열어 본 적" in c["text"][0] and "도커가 뭐야?" in c["text"][0], str(c["text"]))
    ok("했던가: 숨겨진 낱말은 숨겨졌다고", "숨겨진" in answers.check("추천", allc, hist, APP)["text"][0])
    ok("했던가: 없는 낱말은 '기록에 없어요'", "기록에 없어요" in answers.check("양자역학", allc, hist, APP)["text"][0])
    o = answers.other("세포가 뭐야?", allc, APP)
    ok("그 밖의 질문: 뜻을 쓰지 않고 노트로 안내", "개념 노트" in o["text"][0] and o["links"] and "세포는" not in " ".join(o["text"]), str(o["text"]))


class FakeLLM:
    name = "fake"

    def __init__(self, out=None, boom=False):
        self.out, self.boom = out, boom

    def available(self):
        return True

    def json(self, prompt, schema, max_tokens=400):
        if self.boom:
            raise RuntimeError("고장")
        return self.out


def check_intents():
    for text, want in [("어떻게 학습하면 좋아?", "plan"), ("분야별로 개념노트 나눠줘", "by_field"), ("내가 저번에 공부했던게 무엇이였지?", "recent"),
                       ("트랜스포머 내가 했던가?", "check"), ("오늘 날씨 어때", "other")]:
        got, how = intents.classify(text, None)
        ok(f"LLM 없이 낱말 규칙: {text} → {want}", got["intent"] == want and how == "rules", str(got))
    ok("규칙: 했던가에서 개념 이름 뽑기", intents.by_rules("트랜스포머 내가 했던가?")["concept"] == "트랜스포머")
    got, how = intents.classify("이거 내가 했던가? 커밋", FakeLLM({"intent": "check", "concept": "리베이스", "period": "all"}))
    ok("LLM이 글에 없는 이름을 내면 버림", how == "llm" and got["concept"] != "리베이스", str(got))
    got, _ = intents.classify("어제 공부한 거", FakeLLM({"intent": "recent", "concept": "", "period": "어제"}))
    ok("LLM이 목록 밖 값을 내면 기본값", got["period"] == "all")
    got, how = intents.classify("분야별로 나눠줘", FakeLLM(boom=True))
    ok("LLM 고장: 규칙으로 계속", how == "rules" and got["intent"] == "by_field")


def imports(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def check_boundary():
    kit_mods = {p.stem for p in (ROOT / "kit").glob("*.py")}
    used = set().union(*(imports(p) for p in (ROOT / "chat").glob("*.py")))
    ok("chat/은 kit/에서 llm.py만 씀", used & kit_mods == {"llm"}, str(sorted(used & kit_mods)))
    ok("chat/은 DB를 열지 않음", "sqlite3" not in used)
    src = (ROOT / "chat" / "chat_server.py").read_text(encoding="utf-8")
    ok("chat/은 개념 노트 API를 부르지 않음 (열어 본 기록·노트 예약이 생기지 않게)", "/api/study/concept/" not in src and "method=\"POST\"" not in src)
    import chat_server
    doc = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    ok("chat/이 쓰는 API는 모두 docs/API.md에 있음", all(f"`{p}" in doc for p in chat_server.Api.PATHS), str(chat_server.Api.PATHS))
    kit = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "kit").glob("*.py"))
    ok("kit/는 chat/을 모름", not re.search(r"chat_server|import intents|import answers|chat/", kit))
    js = (ROOT / "chat" / "chat.js").read_text(encoding="utf-8")
    ok("챗봇 화면은 글을 HTML로 넣지 않음", "innerHTML" not in js)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def check_servers(tmp):
    ib, db = tmp / "c.jsonl", tmp / "c.sqlite"
    lines = [{"v": 1, "source": "claude-code", "role": "user", "session_id": "a", "ts": "2026-11-09T10:00:00+09:00", "text": "도커가 뭐야?"},
             {"v": 1, "source": "claude-code", "role": "assistant", "session_id": "a", "ts": "2026-11-09T10:00:05+09:00", "text": "Docker와 GitHub Actions를 추천합니다. 설치를 통과했습니다."}]
    ib.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
    p1, p2 = free_port(), free_port()
    env = dict(os.environ, PYTHONUTF8="1")
    main = subprocess.Popen([sys.executable, str(ROOT / "kit" / "serve.py"), "--inbox", str(ib), "--db", str(db), "--port", str(p1), "--searx", "off", "--llm", "off"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    chat = subprocess.Popen([sys.executable, str(ROOT / "chat" / "chat_server.py"), "--port", str(p2), "--api", f"http://127.0.0.1:{p1}", "--llm", "off"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

    def get(port, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))

    def ask(text):
        req = urllib.request.Request(f"http://127.0.0.1:{p2}/api/ask", json.dumps({"text": text}).encode("utf-8"), {"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    try:
        for _ in range(240):
            try:
                if get(p1, "/api/status")["turns"] >= 1 and get(p2, "/api/health"):
                    break
            except OSError:
                pass
            time.sleep(0.25)
        a = ask("Docker 내가 했던가?")
        ok("실제 서버: 아직 안 본 개념", "아직 공부하지 않았어요" in a["text"][0] and "도커가 뭐야?" in a["text"][0], str(a["text"]))
        h0 = get(p1, "/api/study/history")["items"]
        ok("챗봇이 물어봐도 개념 차트에 열어 본 기록이 생기지 않음", h0 == [], str(h0))
        get(p1, "/api/study/concept/docker")                # 사용자가 개념 차트에서 노트를 연다
        h = get(p1, "/api/study/history")["items"]
        ok("개념 차트: 노트를 열면 기록 (history API)", h and h[0]["id"] == "docker" and h[0]["kind"] == "opened" and h[0]["label"] == "Docker", str(h))
        ok("실제 서버: 열어 본 뒤에는 '열어 본 적'", "열어 본 적" in ask("Docker 내가 했던가?")["text"][0])
        ok("실제 서버: 최근 공부에 나옴", any("Docker" in t for t in ask("오늘 공부했던 게 뭐였지?")["text"]))
        ok("실제 서버: 분야별 (기술 용어집 = 정보·통신)", any(t.startswith("정보·통신") for t in ask("분야별로 개념노트 나눠줘")["text"]))
        ok("실제 서버: 학습 순서", "순서" in ask("어떻게 학습하면 좋아?")["text"][0])
        req = urllib.request.Request(f"http://127.0.0.1:{p2}/api/ask", b'{"text":"x"}', {"Content-Type": "application/json", "Origin": "http://evil.example"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            ok("챗봇: 다른 사이트의 요청 막음", False)
        except urllib.error.HTTPError as e:
            ok("챗봇: 다른 사이트의 요청 막음", e.code == 403)
        chat.kill()
        chat.wait()
        ok("챗봇이 꺼져도 개념 차트는 그대로", get(p1, "/api/study/today")["counts"]["shown"] >= 1)
        main.kill()
        main.wait()
        chat = subprocess.Popen([sys.executable, str(ROOT / "chat" / "chat_server.py"), "--port", str(p2), "--api", f"http://127.0.0.1:{p1}", "--llm", "off"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        for _ in range(80):
            try:
                get(p2, "/api/health")
                break
            except OSError:
                time.sleep(0.25)
        ok("개념 차트가 꺼지면 챗봇은 켜 달라고 안내", "연결하지 못했어요" in ask("어떻게 학습하면 좋아?")["text"][0])
    finally:
        for p in (main, chat):
            p.kill()
            p.wait()


def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        check_answers()
        check_intents()
        check_boundary()
        check_servers(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n결과: {'정상' if not FAILS else '실패 ' + str(len(FAILS)) + '개: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
