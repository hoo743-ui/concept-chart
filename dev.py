# -*- coding: utf-8 -*-
"""개념 차트 개발 작업 진입점 (표준 라이브러리만 사용 — 환경을 만들기 전에도 실행된다)

    python dev.py setup          개발 환경 만들기/갱신 (conda 환경 concept-chart) + 전체 점검
                                 (macOS에서 python이 없으면 python3 dev.py setup)
    python dev.py setup --venv   conda 없이 .venv로 만들기 (Python 3.13 권장)
    python dev.py check          전체 점검 (tests/check_env.py + Node가 있으면 npm test)
    python dev.py build          결과 → 페이지 데이터 → 결과 페이지 다시 만들기
    python dev.py sim            시뮬레이터 A·B·C 다시 실행 → build
    python dev.py serve          로컬 서버 http://localhost:8765 (인박스 → 순위·클릭 카드, kit/serve.py)

check·build·sim·serve는 concept-chart 환경을 켠 상태에서 실행한다.
"""
import argparse
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import time

try:  # 출력이 파이프·파일로 갈 때(Windows 기본 인코딩)도 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent
ENV_NAME = "concept-chart"
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="개발 환경 만들기/갱신 + 점검")
    s.add_argument("--venv", action="store_true", help="conda 대신 .venv 사용")
    sub.add_parser("check", help="전체 점검")
    sub.add_parser("build", help="페이지 데이터·결과 페이지 다시 만들기")
    sub.add_parser("sim", help="시뮬레이터 다시 실행 + build")
    sub.add_parser("serve", help="로컬 서버 (뒤에 붙인 옵션은 kit/serve.py로 전달: --port, --once, --rebuild ...)")
    a, extra = ap.parse_known_args()
    if extra and a.cmd != "serve":
        ap.error("알 수 없는 옵션: " + " ".join(extra))
    if a.cmd == "setup":
        rc = setup_venv() if a.venv else setup_conda()
    elif a.cmd == "serve":
        rc = serve(extra)
    else:
        rc = {"check": check, "build": build, "sim": sim}[a.cmd]()
    sys.exit(rc)


if __name__ == "__main__":
    main()
