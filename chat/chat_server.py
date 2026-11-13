# -*- coding: utf-8 -*-
"""chat_server.py : '내 공부 기록에 묻기' — 개념 차트와 따로 도는 작은 앱 (표준 라이브러리만).

    python chat/chat_server.py                      # http://localhost:8766 , 개념 차트 API는 http://127.0.0.1:8765
    python chat/chat_server.py --llm off            # LLM 없이 낱말 규칙으로만

독립성 (tests/test_chat.py가 강제)
- 개념 차트와는 docs/API.md의 읽기(GET) API로만 만난다. DB를 열지 않고, 개념 차트에 아무것도 기록하지 않는다.
  개념 노트 API도 부르지 않는다: 부르면 '열어 본 기록'이 생기고 노트 작성이 예약된다.
- kit/에서는 LLM 연결부(llm.py)만 쓴다. kit/는 이 폴더를 모른다. 이 앱이 꺼지거나 죽어도 개념 차트는 그대로다.
- LLM은 질문 종류만 고른다 (intents.py). 답은 기록 값으로만 만든다 (answers.py).
- 화면은 개념 차트 웹(app/atelier.html의 '기록에 묻기', 11-13 한 웹으로 합침)에 있다. 이 서버는 API만 내고,
  주소(/)로 열면 그 화면으로 넘긴다. 화면이 다른 포트(8765)에서 부르므로 이 PC 주소에서 온 요청에만 CORS를 연다.
"""
import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent / "kit"))
import answers  # noqa: E402
import intents  # noqa: E402
import llm  # noqa: E402

MAX_POST = 8 * 1024
LOCAL = {"localhost", "127.0.0.1"}


class Api:
    """개념 차트 읽기 API (docs/API.md). 쓰는 경로는 이 셋뿐"""
    PATHS = ("/api/study/today", "/api/study/concepts", "/api/study/history")

    def __init__(self, base):
        self.base = base.rstrip("/")

    def get(self, path, **q):
        assert path in self.PATHS, path
        url = self.base + path + ("?" + urllib.parse.urlencode(q) if q else "")
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))


def ask(text, api, client, app_url):
    """사용자 글 → 답 (answers 형식 + how: llm|rules)"""
    got, how = intents.classify(text, client)
    try:
        if got["intent"] == "plan":
            out = answers.plan(api.get("/api/study/today", k=3), app_url)
        elif got["intent"] == "by_field":
            out = answers.by_field(api.get("/api/study/concepts", view="show", k=5000), app_url)
        elif got["intent"] == "recent":
            out = answers.recent(api.get("/api/study/history", k=200), app_url, got["period"])
        elif got["intent"] == "check":
            out = answers.check(got["concept"], api.get("/api/study/concepts", view="all", k=5000), api.get("/api/study/history", k=500), app_url)
        else:
            out = answers.other(text, api.get("/api/study/concepts", view="all", k=5000), app_url)
    except (OSError, ValueError):
        out = {"intent": got["intent"], "text": ["개념 차트 서버에 연결하지 못했어요. python dev.py app 으로 먼저 켜 주세요."], "links": []}
    out["how"] = how
    return out


def make_handler(api, client, app_url):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def local(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in LOCAL

        def local_origin(self):
            origin = self.headers.get("Origin")
            return origin if origin and urllib.parse.urlparse(origin).hostname in LOCAL else None

        def cors(self):
            origin = self.local_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

        def send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.local():
                return self.send(403, {"error": "이 PC에서만 열 수 있어요"})
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index.html"):        # 화면은 개념 차트 웹 안에 있다
                port = self.server.server_address[1]
                q = "" if port == 8766 else "?" + urllib.parse.urlencode({"chat": f"http://127.0.0.1:{port}"})
                self.send_response(302)
                self.send_header("Location", f"{app_url}/atelier.html{q}#/chat")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            if path == "/api/health":
                return self.send(200, {"llm": {"name": client.name, "available": client.available()}, "app": app_url, "examples": answers.EXAMPLES})
            return self.send(404, {"error": "없는 경로"})

        def do_OPTIONS(self):                       # 브라우저의 사전 확인(POST application/json): 이 PC 주소에서만
            if not self.local() or not self.local_origin():
                return self.send(403, {"error": "이 PC에서만 쓸 수 있어요"})
            self.send_response(204)
            self.cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        def do_POST(self):
            origin = self.headers.get("Origin")
            if not self.local() or (origin and urllib.parse.urlparse(origin).hostname not in LOCAL):
                return self.send(403, {"error": "이 PC에서만 쓸 수 있어요"})
            if urllib.parse.urlparse(self.path).path != "/api/ask":
                return self.send(404, {"error": "없는 경로"})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self.send(415, {"error": "application/json만 받아요"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_POST:
                return self.send(413, {"error": "너무 길어요"})
            try:
                text = str(json.loads(self.rfile.read(n).decode("utf-8")).get("text", "")).strip()
            except (ValueError, AttributeError):
                return self.send(400, {"error": "JSON 본문 {text}가 필요해요"})
            if not text:
                return self.send(400, {"error": "질문이 비어 있어요"})
            return self.send(200, ask(text[:1000], api, client, app_url))
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--api", default="http://127.0.0.1:8765", help="개념 차트 서버 주소")
    ap.add_argument("--app-url", default=None, help="답에 붙일 개념 노트 링크의 주소 (기본: --api와 같음)")
    ap.add_argument("--llm", default="ollama:qwen3:4b", help="질문 종류 고르기에 쓸 LLM, off면 낱말 규칙만")
    a = ap.parse_args()
    if urllib.parse.urlparse(a.api).hostname not in LOCAL:
        sys.exit("--api는 이 PC 주소만 쓸 수 있어요")
    client = llm.make(a.llm)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(Api(a.api), client, (a.app_url or a.api).rstrip("/")))
    print(f"내 공부 기록에 묻기: http://localhost:{a.port}  (개념 차트 {a.api}, LLM {client.name})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
