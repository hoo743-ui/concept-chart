# -*- coding: utf-8 -*-
"""개념 차트 개발 작업 진입점 (표준 라이브러리만 사용 — 환경을 만들기 전에도 실행된다)

    python dev.py setup          개발 환경 만들기/갱신 (conda 환경 concept-chart) + 전체 점검
                                 (macOS에서 python이 없으면 python3 dev.py setup)
    python dev.py setup --venv   conda 없이 .venv로 만들기 (Python 3.13 권장)
    python dev.py check          전체 점검 (tests/check_env.py + Node가 있으면 npm test)
    python dev.py build          결과 → 페이지 데이터 → 결과 페이지 다시 만들기
    python dev.py sim            시뮬레이터 A·B·C 다시 실행 → build
    python dev.py serve          로컬 서버 http://localhost:8765 (인박스 → 순위·클릭 카드, kit/serve.py)
    python dev.py app            프로토타입 켜기 (화면 + 서버 + 로컬 LLM) http://localhost:8765
    python dev.py add            AI 답변 추가 (어떤-CLI | python dev.py add)
    python dev.py import 파일    Claude 앱·ChatGPT 내보내기 가져오기
    python dev.py searx up       정의 검색용 SearXNG 켜기 (Docker 필요, http://localhost:8888, 8888을 다른 앱이 쓰면 8889). 끄기: searx down

check·build·sim·serve는 concept-chart 환경을 켠 상태에서 실행한다.
"""
import argparse
import json
import os
import pathlib
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import time

try:  # 출력이 파이프·파일로 갈 때(Windows 기본 인코딩)도 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent
ENV_NAME = "concept-chart"
LLM = "ollama:qwen3:4b"     # 비용 없는 로컬 LLM (Apache 2.0). 바꾸려면 --llm
WIN = platform.system() == "Windows"


def step(title):
    print(f"\n== {title} ==", flush=True)


def run(cmd, **kw):
    """명령을 실행하고 출력은 그대로 보여 준다. 실패하면 종료 코드를 돌려준다."""
    print("$ " + " ".join(str(c) for c in cmd), flush=True)
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, env=env, **kw).returncode


def find_conda():
    """Anaconda Prompt는 CONDA_EXE를, GitHub 러너는 CONDA(설치 폴더)를 준다. 둘 다 없으면 PATH에서 찾는다."""
    if os.environ.get("CONDA_EXE") and pathlib.Path(os.environ["CONDA_EXE"]).exists():
        return os.environ["CONDA_EXE"]
    base = os.environ.get("CONDA")
    if base:
        cand = pathlib.Path(base) / ("Scripts/conda.exe" if WIN else "bin/conda")
        if cand.exists():
            return str(cand)
    return shutil.which("conda")


def conda_env_exists(conda):
    out = subprocess.run([conda, "env", "list", "--json"], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        return False
    return any(pathlib.Path(p).name == ENV_NAME for p in json.loads(out.stdout).get("envs", []))


def setup_conda():
    conda = find_conda()
    if not conda:
        if WIN:
            sys.exit("conda를 찾지 못했다. 시작 메뉴의 'Anaconda Prompt'에서 다시 실행하거나, "
                     "conda 없이 하려면: python dev.py setup --venv")
        sys.exit("conda를 찾지 못했다. Miniforge 설치 후 'conda init zsh' → 새 터미널에서 다시 실행 (SETUP.md 1단계). "
                 "conda 없이 하려면: python3.13 dev.py setup --venv")
    step(f"conda 환경 '{ENV_NAME}' 만들기/갱신 ({conda})")
    if conda_env_exists(conda):
        rc = run([conda, "env", "update", "-n", ENV_NAME, "-f", "environment.yml", "--prune"])
    else:
        rc = run([conda, "env", "create", "-f", "environment.yml"])
    if rc != 0:
        sys.exit(f"환경 만들기 실패 (종료 코드 {rc}). SETUP.md '문제 해결' 참고")
    step("새 환경에서 전체 점검")
    rc = run([conda, "run", "--no-capture-output", "-n", ENV_NAME, "python", "dev.py", "check"])
    print("\n다음: conda activate " + ENV_NAME)
    return rc


def setup_venv():
    v = sys.version_info
    if (v.major, v.minor) != (3, 13):
        print(f"참고: 지금 파이썬은 {v.major}.{v.minor}. 검증한 버전은 3.13이라 설치가 실패할 수 있다.")
    venv = ROOT / ".venv"
    step(f"가상환경 만들기 ({venv})")
    if not venv.exists() and run([sys.executable, "-m", "venv", str(venv)]) != 0:
        sys.exit("가상환경 만들기 실패")
    py = venv / ("Scripts/python.exe" if WIN else "bin/python")
    if run([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"]) != 0:
        sys.exit("패키지 설치 실패. SETUP.md '문제 해결' 참고")
    step("새 환경에서 전체 점검")
    rc = run([py, "dev.py", "check"])
    print("\n다음: " + (r".venv\Scripts\activate" if WIN else "source .venv/bin/activate")
          + ("   (Windows는 setx PYTHONUTF8 1 도 한 번)" if WIN else ""))
    return rc


def check():
    step("파이썬 점검 (tests/check_env.py)")
    rc = run([sys.executable, "tests/check_env.py"])
    npm = shutil.which("npm")
    if npm:
        step("페이지 자동 점검 (npm)")
        rc = rc or run([npm, "ci", "--no-audit", "--no-fund"]) or run([npm, "test"])
    else:
        print("\n참고: Node.js가 없어 페이지 자동 점검(npm test)은 건너뜀 (선택 항목)")
    print("\n결과:", "모두 통과" if rc == 0 else "실패한 항목이 있음 — 위 [FAIL] 줄 확인")
    return rc


def build():
    step("결과 → 페이지 데이터 → 결과 페이지")
    return run([sys.executable, "sim/make_page_data.py"]) or run([sys.executable, "web/build_page.py"])


def sim():
    for name in ("sim_A", "sim_B", "sim_C"):
        step(f"시뮬레이터 {name[-1]}")
        t = time.time()
        rc = run([sys.executable, f"sim/{name}.py"])
        if rc != 0:
            return rc
        print(f"({time.time() - t:.0f}초)")
    return build()


def serve(extra):
    step("로컬 서버 (kit/serve.py) — 끝내려면 Ctrl+C")
    try:
        return run([sys.executable, "kit/serve.py"] + extra)
    except KeyboardInterrupt:
        return 0


SEARX_PORTS = (8888, 8889)     # 8888은 Jupyter 기본 포트와 겹친다: 비어 있는 쪽에 켜고, /healthz가 OK인 쪽을 쓴다


def searx_url():
    """켜져 있는 SearXNG 주소 또는 None. 포트만 열려 있는 것으로는 믿지 않는다 (Jupyter가 8888을 쓰면 정의 검색이 모두 실패했다, 11-13)"""
    import urllib.request
    for port in SEARX_PORTS:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                if r.status == 200 and r.read(16).strip() == b"OK":
                    return f"http://localhost:{port}"
        except OSError:
            continue
    return None


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def app(extra):
    """프로토타입 한 번에 켜기: 화면(app/) + 서버 + 로컬 LLM(있으면). LLM이나 SearXNG가 없어도 그대로 켜진다"""
    step("개념 차트 — 끝내려면 Ctrl+C")
    args = ["--web", "app"]
    if "--llm" not in extra:
        ollama = shutil.which("ollama") or next((p for p in [pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"] if p.is_file()), None)
        if ollama and not port_open(11434):
            subprocess.Popen([str(ollama), "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
        args += ["--llm", LLM] if ollama else []
        print(f"AI 요약: {LLM}" if ollama else "AI 요약: 꺼짐 (Ollama 없음). 출처 문장만 보여 줍니다")
    if "--searx" not in extra:
        url = searx_url()
        args += ["--searx", url or "off"]
        print(f"정의 검색: SearXNG {url}" if url else "정의 검색: 꺼짐 (python dev.py searx up)")
    clf = ROOT / "models" / "concept-clf"                   # (0.8.0) 개념 분류기: 학습해 둔 모델과 학습 패키지(requirements-ml.txt)가 있을 때만 켠다
    if "CONCEPT_CHART_CLF" not in os.environ and (clf / "concept_clf.json").is_file():
        import importlib.util
        if importlib.util.find_spec("torch") and importlib.util.find_spec("transformers"):
            os.environ["CONCEPT_CHART_CLF"] = str(clf)
            print("개념 분류기: 켜짐 (models/concept-clf)")
    chat_proc = None                                        # '내 공부 기록에 묻기'(chat/)는 따로 도는 앱: 못 켜거나 죽어도 개념 차트는 그대로
    if not port_open(8766):
        given = args + extra
        chat_llm = given[given.index("--llm") + 1] if "--llm" in given[:-1] else "off"   # 앱과 같은 LLM (없으면 낱말 규칙)
        try:
            chat_proc = subprocess.Popen([sys.executable, str(ROOT / "chat" / "chat_server.py"), "--llm", chat_llm],
                                         cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("내 공부 기록에 묻기: http://localhost:8766")
        except OSError as e:
            print("참고: 기록에 묻기 앱을 켜지 못했다 —", e)
    try:
        return run([sys.executable, "kit/serve.py"] + args + extra)
    except KeyboardInterrupt:
        return 0
    finally:
        if chat_proc:
            chat_proc.terminate()


def chat(extra):
    step("내 공부 기록에 묻기 (chat/chat_server.py) — 개념 차트(python dev.py app)가 켜져 있어야 답한다. 끝내려면 Ctrl+C")
    try:
        return run([sys.executable, "chat/chat_server.py"] + extra)
    except KeyboardInterrupt:
        return 0


def add(extra):
    return run([sys.executable, "kit/concept_add.py", "text"] + extra)


def import_chats(extra):
    return run([sys.executable, "kit/concept_add.py", "import"] + extra)


def searx(action):
    folder = ROOT / "kit" / "searxng"
    docker = shutil.which("docker")
    if not docker:
        sys.exit("docker를 찾지 못했다. Docker Desktop을 설치하고 켠 뒤 다시 실행 (SETUP.md '정의 검색')")
    env = folder / ".env"
    if not env.exists():                    # 비밀 키는 PC마다 새로 만들고 git에 올리지 않는다
        env.write_text("SEARXNG_SECRET=" + secrets.token_hex(32) + "\n", encoding="utf-8", newline="\n")
    args = ["up", "-d"] if action == "up" else ["down"]
    if action == "up" and "SEARXNG_PORT" not in os.environ:     # compose.yml의 ${SEARXNG_PORT:-8888}
        port = next((p for p in SEARX_PORTS if not port_open(p)), SEARX_PORTS[0])
        os.environ["SEARXNG_PORT"] = str(port)
        print(f"SearXNG 포트: {port}")
    return run([docker, "compose", "-f", folder / "compose.yml", *args])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="개발 환경 만들기/갱신 + 점검")
    s.add_argument("--venv", action="store_true", help="conda 대신 .venv 사용")
    sub.add_parser("check", help="전체 점검")
    sub.add_parser("build", help="페이지 데이터·결과 페이지 다시 만들기")
    sub.add_parser("sim", help="시뮬레이터 다시 실행 + build")
    sub.add_parser("serve", help="로컬 서버 (뒤에 붙인 옵션은 kit/serve.py로 전달: --port, --once, --rebuild ...)")
    sub.add_parser("app", help="프로토타입 켜기: 화면 + 서버 + 로컬 LLM (옵션은 kit/serve.py로 전달)")
    sub.add_parser("chat", help="내 공부 기록에 묻기만 따로 켜기 (app이 함께 켠다. 옵션은 chat/chat_server.py로 전달: --port, --api, --llm)")
    sub.add_parser("add", help="AI 답변 추가: 어떤-CLI | python dev.py add, 또는 python dev.py add 파일")
    sub.add_parser("import", help="Claude 앱·ChatGPT 내보내기 가져오기: python dev.py import conversations.json")
    sub.add_parser("verify", help="지속 검증: 개념 노트의 '맞아요·아니에요' 판단으로 관문을 다시 재고 기록, 떨어지면 알림 (개발용 평가 데이터 필요)")
    sub.add_parser("lexicon", help="분야 사전 받기·만들기 → kit/data/lexicon/ (우리말샘 약 200MB, pyarrow 필요)")
    s = sub.add_parser("searx", help="정의 검색용 SearXNG 켜기·끄기 (Docker 필요)")
    s.add_argument("action", choices=["up", "down"])
    a, extra = ap.parse_known_args()
    if extra and a.cmd not in ("serve", "app", "add", "import", "chat"):
        ap.error("알 수 없는 옵션: " + " ".join(extra))
    if a.cmd == "setup":
        rc = setup_venv() if a.venv else setup_conda()
    elif a.cmd == "chat":
        rc = chat(extra)
    elif a.cmd == "serve":
        rc = serve(extra)
    elif a.cmd == "app":
        rc = app(extra)
    elif a.cmd == "add":
        rc = add(extra)
    elif a.cmd == "import":
        rc = import_chats(extra)
    elif a.cmd == "searx":
        rc = searx(a.action)
    elif a.cmd == "verify":
        step("지속 검증 (experiments/2026-11-10-general-gate/verify.py)")
        rc = run([sys.executable, "experiments/2026-11-10-general-gate/verify.py"])
    elif a.cmd == "lexicon":
        step("분야 사전 (lexicons/build.py)")
        rc = run([sys.executable, "lexicons/build.py"])
    else:
        rc = {"check": check, "build": build, "sim": sim}[a.cmd]()
    sys.exit(rc)


if __name__ == "__main__":
    main()
