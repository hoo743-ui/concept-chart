# THYNK 실행기 (설치판, 11-13 설치 파일 실험). 바탕화면·시작 메뉴 아이콘이 이 파일을 창 없는 파이썬(pythonw)으로 연다.
#   pythonw launcher.pyw               서버를 (꺼져 있으면) 켜고 THYNK 창을 연다. 창을 닫으면 이 실행기가 켠 서버는 끈다
#   pythonw launcher.pyw --background  윈도우 시작 때 (설치에서 고른 경우만): 개념 차트 서버만 켜 둔다 (브라우저 확장이 답을 보낼 곳)
# 메모리: 켜 둔 서버는 약 50MB. 형태소 분석(약 500MB)은 새 답변이 올 때만 켜지고 10분 동안 없으면 스스로 끝난다(kit/serve.py WORKER_IDLE).
# 기록에 묻기 서버(약 26MB)는 창을 열 때만 켠다. 데이터는 개발판과 같은 곳(~/.claude)을 쓴다. 바깥 서버로는 아무것도 보내지 않는다.
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

HERE = pathlib.Path(__file__).resolve().parent             # 설치 폴더\thynk (kit, chat, app 이 저장소와 같은 배치)
PY = pathlib.Path(sys.executable).with_name("python.exe")   # 서버는 창 없이 python.exe로 (pythonw는 표준 입출력이 없어 분석 프로세스와 못 주고받는다)
LOGS = pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home()))) / "THYNK" / "logs"
APP_URL = "http://127.0.0.1:8765/atelier.html"
NO_WINDOW = 0x08000000                                     # CREATE_NO_WINDOW
LLM = "ollama:qwen3:4b"


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def healthy(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def ollama():
    p = shutil.which("ollama") or pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return pathlib.Path(p) if p and pathlib.Path(p).is_file() else None


CLF = HERE / "models" / "concept-clf"          # (0.8.0) 개념 분류기가 함께 설치됐으면 켠다 (AI가 켜져 있을 때만 쓰인다, kit/serve.py)
CLF_ENV = {"CONCEPT_CHART_CLF": str(CLF)} if (CLF / "concept_clf.json").is_file() else {}


def spawn(args, name):
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / f"{name}.log", "a", encoding="utf-8")
    return subprocess.Popen([str(a) for a in args], cwd=HERE, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                            env={**os.environ, "PYTHONUTF8": "1", **CLF_ENV})


def llm_name():
    o = ollama()
    if not o:
        return "off"
    if not port_open(11434):
        subprocess.Popen([str(o), "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    return LLM


def start_app(llm):
    if healthy(8765):
        return None
    p = spawn([PY, HERE / "kit" / "serve.py", "--web", "app", "--searx", "off", "--llm", llm], "app")
    for _ in range(60):
        if healthy(8765):
            break
        time.sleep(0.5)
    return p


def start_chat(llm):
    if healthy(8766):
        return None
    return spawn([PY, HERE / "chat" / "chat_server.py", "--llm", llm], "chat")


def open_window():
    try:
        import webview                                       # 윈도우에 들어 있는 WebView2로 자기 창 (pywebview)
        webview.create_window("THYNK", APP_URL, width=1320, height=880, min_size=(380, 560))
        webview.start()
        return True                                          # 창을 닫을 때까지 기다렸다
    except Exception as e:  # noqa: BLE001 — 창을 못 띄우면 엣지 앱 창 → 기본 브라우저
        LOGS.mkdir(parents=True, exist_ok=True)
        (LOGS / "window.log").open("a", encoding="utf-8").write(f"{time.ctime()} webview 실패: {type(e).__name__}: {e}\n")
    edge = shutil.which("msedge") or next((p for p in [pathlib.Path(os.environ.get(v, "")) / "Microsoft/Edge/Application/msedge.exe" for v in ("PROGRAMFILES(X86)", "PROGRAMFILES")] if p.is_file()), None)
    if edge:
        subprocess.Popen([str(edge), f"--app={APP_URL}"])
    else:
        webbrowser.open(APP_URL)
    return False                                             # 브라우저 창은 언제 닫는지 알 수 없다 → 서버를 끄지 않는다


def stop(p):
    """켠 서버와 그 아래 분석·모델 작업자까지 함께 끈다 (창 없는 프로세스라 강제 종료. 저장은 SQLite 트랜잭션 단위라 반쯤 쓴 기록이 남지 않는다)"""
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)


def main():
    llm = llm_name()
    if "--background" in sys.argv:
        start_app(llm)                                      # 서버가 끝날 때까지 기다리지 않는다 (서버는 따로 돈다)
        return
    started = [p for p in (start_app(llm), start_chat(llm)) if p]
    if not open_window():
        return
    if not (HERE.parent / "autostart.flag").exists():       # 윈도우 시작 때 켜기를 고르지 않았으면 창을 닫을 때 같이 끈다 (메모리 돌려주기)
        for p in started:
            stop(p)
    else:
        for p in started:                                   # 켜 두기를 골랐으면 개념 차트 서버만 남기고 기록에 묻기는 끈다
            if "chat_server.py" in " ".join(map(str, p.args)):
                stop(p)


if __name__ == "__main__":
    main()
