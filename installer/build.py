"""THYNK 윈도우 설치 파일 만들기 (11-13 실험, 사용자 승인). 표준 라이브러리 + Inno Setup(ISCC).

    python installer/build.py            → installer/out/THYNK-설치-<버전>.exe

하는 일
1. python.org의 윈도우 내장용 파이썬(embeddable, 저장소 가상환경과 같은 버전)을 받아 풀기 (installer/cache에 보관)
2. 서비스에 필요한 패키지만 버전 고정으로 넣기 (실험·학습용 torch 등은 넣지 않는다)
3. 저장소에서 서비스 파일만 복사: kit(분야 사전 포함), chat, app(화면·글꼴), extension, 실행기
4. 마스코트로 아이콘 만들기 → ISCC로 설치 파일 컴파일 → 설치 안내(THYNK-설치-안내.html)를 옆에

개인 데이터(~/.claude의 인박스·DB)는 넣지 않는다 (아래 SKIP 확인 + 마지막에 검사).
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD, OUT, CACHE = HERE / "build", HERE / "out", HERE / "cache"
VERSION = "0.1.0"
PYV = "%d.%d.%d" % sys.version_info[:3]                # 가상환경과 같은 파이썬 (패키지 바이너리가 맞게)
PACKAGES = ["kiwipiepy==0.24.1", "kiwipiepy_model==0.24.0", "trafilatura==2.3.1", "pywebview==6.2.1"]
# (0.8.0) 개념 분류기: 그래픽 카드용이 아닌 CPU용 torch(작다). 분류기는 새 낱말이 있을 때만 따로 켜졌다 끝난다
ML_PACKAGES = ["torch==2.15.0", "transformers==5.22.2"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
CLF_MODEL = ROOT / "models" / "concept-clf"
COPY = {"kit": "kit", "chat": "chat", "app": "app", "extension": "extension"}
SKIP_NAMES = {"__pycache__", ".pytest_cache", "node_modules"}
SKIP_SUFFIX = {".pyc", ".sqlite", ".sqlite-wal", ".sqlite-shm", ".jsonl", ".log"}
ALLOW = {"lexicon.sqlite"}                          # 분야 사전(공개 사전에서 만든 것)만 예외. 대화 기록 DB는 저장소 밖(~/.claude)에 있다
ISCC = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"


def step(t):
    print("\n== " + t, flush=True)


def fetch(url, dst):
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    print("받는 중:", url)
    with urllib.request.urlopen(url, timeout=120) as r, open(dst.with_suffix(".part"), "wb") as f:
        shutil.copyfileobj(r, f)
    dst.with_suffix(".part").rename(dst)
    return dst


def ignore(_dir, names):
    return [n for n in names if n not in ALLOW and (n in SKIP_NAMES or pathlib.Path(n).suffix in SKIP_SUFFIX or n.startswith("."))]


def size(p):
    return sum(f.stat().st_size for f in pathlib.Path(p).rglob("*") if f.is_file())


def make_icon(dst):
    from PIL import Image                                  # 개발 PC의 Pillow (설치판에는 들어가지 않음)
    im = Image.open(ROOT / "app" / "mascot.png").convert("RGBA")
    im.save(dst, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def write_guide(exe):
    """설치 안내(guide.html)를 설치 파일 옆에: 마스코트는 글 안에 넣고(파일 하나로 열리게), 버전·파일 이름을 채운다"""
    import base64
    mascot = "data:image/png;base64," + base64.b64encode((ROOT / "app" / "mascot.png").read_bytes()).decode("ascii")
    t = (HERE / "guide.html").read_text(encoding="utf-8").replace("{{MASCOT}}", mascot).replace("{{VERSION}}", VERSION).replace("{{FILE}}", exe.name)
    dst = OUT / "THYNK-설치-안내.html"
    dst.write_text(t, encoding="utf-8", newline="\n")
    return dst


def main():
    if not ISCC.exists():
        sys.exit("Inno Setup이 없습니다: winget install --id JRSoftware.InnoSetup -e")
    if BUILD.exists():
        shutil.rmtree(BUILD)
    rt, app = BUILD / "runtime", BUILD / "thynk"

    step(f"1. 내장용 파이썬 {PYV}")
    z = fetch(f"https://www.python.org/ftp/python/{PYV}/python-{PYV}-embed-amd64.zip", CACHE / f"python-{PYV}-embed-amd64.zip")
    print("sha256", hashlib.sha256(z.read_bytes()).hexdigest())
    with zipfile.ZipFile(z) as f:
        f.extractall(rt)
    pth = next(rt.glob("python*._pth"))
    zipname = next(rt.glob("python*.zip")).name
    # 경로: 표준 라이브러리, 패키지, 우리 코드(kit·chat). 스크립트 폴더가 자동으로 붙지 않는 내장판이라 직접 적는다
    pth.write_text("\n".join([zipname, ".", "Lib\\site-packages", "..\\thynk\\kit", "..\\thynk\\chat", "import site", ""]), encoding="utf-8")

    step("2. 서비스 패키지 (버전 고정)")
    # 이 PC(윈도우 64비트, 같은 파이썬 버전)에서 받는다. kiwipiepy_model은 휠이 없어 '바이너리만' 옵션을 쓸 수 없다
    ml = ML_PACKAGES if CLF_MODEL.joinpath("concept_clf.json").is_file() else []
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-compile", "--disable-pip-version-check",
                    *(["--extra-index-url", TORCH_INDEX] if ml else []),
                    "--target", str(rt / "Lib" / "site-packages"), *PACKAGES, *ml], check=True)

    step("3. 서비스 파일")
    for src, dst in COPY.items():
        shutil.copytree(ROOT / src, app / dst, ignore=ignore)
    shutil.copy2(HERE / "launcher.pyw", app / "launcher.pyw")
    if CLF_MODEL.joinpath("concept_clf.json").is_file():          # 개념 분류기: 실행 파일 하나 + 학습한 모델 폴더
        (app / "ml").mkdir()
        shutil.copy2(ROOT / "ml" / "concept_clf.py", app / "ml" / "concept_clf.py")
        shutil.copytree(CLF_MODEL, app / "models" / "concept-clf", ignore=ignore)
        print("개념 분류기: 넣음")
    else:
        print("개념 분류기: 없음 (models/concept-clf)")
    shutil.copy2(HERE / "NOTICE.txt", BUILD / "NOTICE.txt")
    make_icon(BUILD / "thynk.ico")
    bad = [p for p in BUILD.rglob("*") if p.name not in ALLOW and p.suffix in SKIP_SUFFIX]
    if bad:
        sys.exit("개인 데이터로 보이는 파일이 들어갔습니다: " + ", ".join(map(str, bad[:5])))
    lex = app / "kit" / "data" / "lexicon"
    print("분야 사전:", "있음" if lex.exists() and any(lex.iterdir()) else "없음 (python dev.py lexicon으로 먼저 만들 것)")

    step("4. 설치 파일 컴파일")
    OUT.mkdir(exist_ok=True)
    subprocess.run([str(ISCC), "/Q", f"/DAppVersion={VERSION}", f"/DBuildDir={BUILD}", f"/DOutDir={OUT}", str(HERE / "thynk.iss")], check=True)
    exe = next(OUT.glob(f"THYNK-*{VERSION}*.exe"))
    print(f"\n완료: {exe}\n  설치 파일 {exe.stat().st_size / 1e6:,.0f}MB · 풀린 크기 {size(BUILD) / 1e6:,.0f}MB "
          f"(파이썬+패키지 {size(rt) / 1e6:,.0f}MB, 서비스 {size(app) / 1e6:,.0f}MB)")
    print("sha256", hashlib.sha256(exe.read_bytes()).hexdigest())
    print("설치 안내:", write_guide(exe))


if __name__ == "__main__":
    main()
