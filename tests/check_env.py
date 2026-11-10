# -*- coding: utf-8 -*-
"""개발환경 점검 + 키트 스모크 테스트 (네트워크·실제 ~/.claude 설정을 건드리지 않음)

    python tests/check_env.py

통과하면 마지막 줄에 '모두 정상'이 나온다. 실패 항목은 SETUP.md의 '문제 해결' 표를 보면 된다.
"""
import contextlib
import importlib
import importlib.metadata as md
import io
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile
import time

try:  # 출력이 파일·파이프로 갈 때(Windows cp949)도 한글·기호가 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "kit")]
FAILS, WARNS = [], []


def check(name, fn, required=True):
    t0 = time.perf_counter()
    try:
        info = fn()
        print(f"[OK]   {name}" + (f" — {info}" if info else "") + f"  ({time.perf_counter() - t0:.1f}s)")
    except Exception as e:  # noqa: BLE001 — 점검 스크립트라 어떤 오류든 이유를 보여 준다
        tag = "[FAIL]" if required else "[WARN]"
        print(f"{tag} {name} — {type(e).__name__}: {e}")
        (FAILS if required else WARNS).append(name)


# ---------- 1) 파이썬 ----------
def py_version():
    v = sys.version_info
    if v < (3, 10):
        raise RuntimeError(f"Python {v.major}.{v.minor} — 3.10 이상 필요 (권장 3.13)")
    if (v.major, v.minor) != (3, 13):
        WARNS.append("python-version")
        return f"{platform.python_version()} (검증한 버전은 3.13 — 다른 버전이면 설치 오류가 날 수 있음)"
    return f"{platform.python_version()} · {sys.executable}"


def encoding():
    enc = sys.flags.utf8_mode
    return "UTF-8 모드 켜짐" if enc else "UTF-8 모드 꺼짐 (코드는 인코딩을 직접 지정해서 괜찮지만, PYTHONUTF8=1 권장)"


# ---------- 2) 패키지 ----------
REQUIRED = [  # (import 이름, 배포 이름)
    ("numpy", "numpy"), ("scipy", "scipy"), ("sklearn", "scikit-learn"), ("networkx", "networkx"),
    ("kiwipiepy", "kiwipiepy"), ("spacy", "spacy"), ("yake", "yake"), ("krwordrank", "krwordrank"),
    ("korean_romanizer", "korean_romanizer"), ("rapidfuzz", "RapidFuzz"), ("rank_bm25", "rank-bm25"),
]


def packages():
    missing, got = [], []
    for mod, dist in REQUIRED:
        try:
            importlib.import_module(mod)
            got.append(f"{dist} {md.version(dist)}")
        except Exception:
            missing.append(dist)
    if missing:
        raise RuntimeError("설치 안 됨: " + ", ".join(missing) + " → pip install -r requirements.txt")
    return f"{len(got)}개 ({', '.join(got[:4])} …)"


def optional_trafilatura():
    importlib.import_module("trafilatura")
    return "trafilatura " + md.version("trafilatura")


# ---------- 3) 한국어 모델 ----------
def kiwi():
    from kiwipiepy import Kiwi
    toks = [t.form for t in Kiwi().tokenize("트랜스포머는 어텐션으로 문맥을 계산한다.")]
    if "트랜스포머" not in toks:
        raise RuntimeError(f"형태소 결과가 이상함: {toks}")
    return " / ".join(toks[:5])


def spacy_model():
    import spacy
    nlp = spacy.load("ko_core_news_md", disable=["tagger", "parser", "ner", "lemmatizer", "morphologizer", "senter", "attribute_ruler"])
    dim = nlp("임베딩").vector.shape[0]
    if dim == 0:
        raise RuntimeError("벡터가 비어 있음 (ko_core_news_md 대신 sm 모델이 깔렸는지 확인)")
    return f"ko_core_news_md {md.version('ko_core_news_md')} · 벡터 {dim}차원"


# ---------- 4) 키트 ----------
def verify_agent():
    from verify_note import run_agent
    src = [{"url": "https://example.org/t", "text": "트랜스포머는 순환 구조 없이 어텐션 메커니즘만으로 문장 속 단어들의 관계를 한 번에 계산하는 신경망 구조로, 2017년 논문에서 처음 제안되었다."}]
    note = "트랜스포머는 어텐션 메커니즘만으로 단어들의 관계를 계산하는 신경망 구조다. 2019년 Google이 처음 공개했다."
    out = run_agent(note, src)
    verdicts = [c["verdict"] for c in out["report"]["claims"]]
    if verdicts[0] != "supported" or "supported" == verdicts[-1]:
        raise RuntimeError(f"판정이 예상과 다름: {verdicts}")
    return f"근거 있는 문장 통과 · 틀린 문장 걸러냄 (mode={out['mode']})"


def store_card():
    from concept_store import open_store, index_turn, concept_card
    con = open_store(":memory:")
    for i in range(5):
        turn = {"ts": f"2026-11-0{i + 1}T10:00:00", "session_id": f"s{i}", "role": "user"}
        index_turn(con, turn, [(f"RAG와 임베딩 질문 {i}", {"rag", "embedding"})])
    card = concept_card(con, "rag")
    page2 = concept_card(con, "rag", cursor=card["next_cursor"])
    size = len(json.dumps(card, ensure_ascii=False).encode("utf-8"))
    if card["related"] != ["embedding"] or len(card["records"]) != 3 or len(page2["records"]) != 2 or size > 2048:
        raise RuntimeError(f"카드/페이지 넘김 결과가 이상함: {card}")
    return f"카드 {size}B · 더 보기 3+2건 · LLM 호출 0회"


def evidence_pick():
    from fetch_sources import pick
    srcs = [{"url": "u1", "text": "RAG란 검색한 문서를 근거로 답을 생성하는 방법이다. 이번 해커톤에서 RAG로 챗봇을 만들었다."},
            {"url": "u2", "text": "RAG는 질문과 관련된 문서를 먼저 찾아 언어 모델에 함께 넣는 기법이다."}]
    got = pick("RAG", ["검색 증강 생성"], srcs)
    if len(got) != 2 or any("해커톤" in g["text"] for g in got):
        raise RuntimeError(f"근거 문장 선택이 이상함: {got}")
    return "정의문 2개 선택 · 경험담 제외"


def loader():
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        inbox = tmp / "inbox.jsonl"
        rows = [{"session_id": "a", "role": "user", "text": "pandas로 `df.groupby` 쓰다가 KeyError 났어 https://x.org"},
                {"session_id": "a", "role": "assistant", "text": "```python\nimport pandas as pd\n```\n컬럼 이름을 확인하세요."}]
        inbox.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        code = (ROOT / "kit" / "loader_cell.py").read_text(encoding="utf-8").replace("@@INBOX@@", inbox.as_posix())
        ns = {}
        with contextlib.redirect_stdout(io.StringIO()):  # 셀이 찍는 요약 줄은 숨긴다
            exec(compile(code, "loader_cell.py", "exec"), ns)  # 노트북 첫 셀을 그대로 실행
        turns = ns["sessions"]["a"]
        if "pandas" not in turns[1]["code_terms"] or "KeyError" not in turns[0]["errors"] or "https" in turns[0]["prose"]:
            raise RuntimeError(f"정제 결과가 이상함: {turns}")
        return "세션 1개 · 2턴 · 코드/URL 정제"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def installer():
    """임시 홈 폴더에 설치 → --test → --uninstall (진짜 ~/.claude는 건드리지 않음)"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        env = dict(os.environ, HOME=str(tmp), USERPROFILE=str(tmp), PYTHONUTF8="1")
        env.pop("CONCEPT_INBOX", None)
        inst = [sys.executable, str(ROOT / "kit" / "install_concept_hook.py")]

        def run(*args):
            r = subprocess.run(inst + list(args), env=env, capture_output=True, timeout=120)
            out = (r.stdout + r.stderr).decode("utf-8", "replace")
            if r.returncode != 0:
                raise RuntimeError(f"{' '.join(args) or '설치'} 실패 (코드 {r.returncode}): {out[-400:]}")
            return out
        run()
        cfg = json.loads((tmp / ".claude" / "settings.json").read_text(encoding="utf-8"))
        n_hooks = sum(len(v) for v in cfg.get("hooks", {}).values())
        if "결과: 정상" not in run("--test"):
            raise RuntimeError("--test 결과가 정상이 아님")
        run("--uninstall")
        left = json.loads((tmp / ".claude" / "settings.json").read_text(encoding="utf-8")).get("hooks", {})
        if any("concept_hook" in json.dumps(v) for v in left.values()):
            raise RuntimeError("--uninstall 후에도 훅이 남아 있음")
        return f"설치(훅 {n_hooks}개) → --test 정상 → 제거 확인"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def serve_api():
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "test_serve.py")], capture_output=True, timeout=300)
    out = r.stdout.decode("utf-8", "replace").strip().splitlines()
    if r.returncode != 0:
        raise RuntimeError(" / ".join(l for l in out if l.startswith("[FAIL]"))[:400] or (r.stderr.decode("utf-8", "replace")[-400:]))
    return f"{sum(l.startswith('[OK]') for l in out)}개 항목 (이어 읽기·순위·카드·API·SSE)"


def model_boundary():
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "test_boundary.py")], capture_output=True, timeout=300)
    out = r.stdout.decode("utf-8", "replace").strip().splitlines()
    if r.returncode != 0:
        raise RuntimeError(" / ".join(l for l in out if l.startswith("[FAIL]"))[:400] or (r.stderr.decode("utf-8", "replace")[-400:]))
    return f"{sum(l.startswith('[OK]') for l in out)}개 항목 (의존 방향·모델 고장 시 규칙으로 계속)"


def study_features():
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "test_study.py")], capture_output=True, timeout=300)
    out = r.stdout.decode("utf-8", "replace").strip().splitlines()
    if r.returncode != 0:
        raise RuntimeError(" / ".join(l for l in out if l.startswith("[FAIL]"))[:400] or (r.stderr.decode("utf-8", "replace")[-400:]))
    return f"{sum(l.startswith('[OK]') for l in out)}개 항목 (개념 관문·거짓 방지·화면 독립·입구)"


def chat_app():
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "test_chat.py")], capture_output=True, timeout=300)
    out = r.stdout.decode("utf-8", "replace").strip().splitlines()
    if r.returncode != 0:
        raise RuntimeError(" / ".join(l for l in out if l.startswith("[FAIL]"))[:400] or (r.stderr.decode("utf-8", "replace")[-400:]))
    return f"{sum(l.startswith('[OK]') for l in out)}개 항목 (기록으로만 답함·개념 차트와 독립)"


def hook_fixtures():
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "test_hook.py")], capture_output=True, timeout=300)
    out = r.stdout.decode("utf-8", "replace").strip().splitlines()
    if r.returncode != 0:
        raise RuntimeError(" / ".join(l for l in out if l.startswith("[FAIL]"))[:400] or out[-1:])
    return out[-1] if out else ""


def page_data():
    r = subprocess.run([sys.executable, str(ROOT / "sim" / "make_page_data.py"), "--check"], capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError((r.stdout + r.stderr).decode("utf-8", "replace").strip()[-400:])
    return "시뮬레이터 결과로 다시 만든 페이지 데이터 = sim/results/page_data.json"


def page_build():
    r = subprocess.run([sys.executable, str(ROOT / "web" / "build_page.py"), "--check"], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError((r.stdout + r.stderr).decode("utf-8", "replace").strip())
    return "kit 원본 + page_data.json으로 다시 만든 페이지 = web/dist/index.html"


def node_jsdom():
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js 없음 (페이지 자동 점검에만 필요 — 없어도 됨)")
    if not (ROOT / "node_modules" / "jsdom").exists():
        raise RuntimeError("jsdom 없음 → npm ci")
    v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    return f"node {v} · jsdom 설치됨 (npm test로 페이지 점검)"


if __name__ == "__main__":
    print(f"== concept-chart 환경 점검 ({platform.system()} {platform.release()}) ==")
    check("Python 버전", py_version)
    check("인코딩", encoding, required=False)
    check("필수 패키지", packages)
    check("선택 패키지 (웹 본문 추출)", optional_trafilatura, required=False)
    check("Kiwi 형태소 분석기", kiwi)
    check("spaCy 한국어 모델", spacy_model)
    check("검증 에이전트 (verify_note)", verify_agent)
    check("클릭 카드 (concept_store)", store_card)
    check("근거 문장 선택 (fetch_sources, 오프라인)", evidence_pick)
    check("파이프라인 첫 셀 (loader_cell)", loader)
    check("훅 설치기 (임시 홈에서)", installer)
    check("훅 어댑터 fixture (tests/test_hook.py)", hook_fixtures)
    check("로컬 서버 serve (tests/test_serve.py)", serve_api)
    check("백본과 모델의 경계 (tests/test_boundary.py)", model_boundary)
    check("공부 기능 (tests/test_study.py)", study_features)
    check("내 공부 기록에 묻기 (tests/test_chat.py)", chat_app)
    check("페이지 데이터 재현 (make_page_data)", page_data)
    check("페이지 빌드 재현", page_build)
    check("페이지 자동 점검 도구 (선택)", node_jsdom, required=False)
    print()
    if FAILS:
        print(f"실패 {len(FAILS)}개: {', '.join(FAILS)} → SETUP.md '문제 해결' 참고")
        sys.exit(1)
    print("모두 정상" + (f" (참고 {len(set(WARNS))}개: {', '.join(sorted(set(WARNS)))})" if WARNS else ""))
