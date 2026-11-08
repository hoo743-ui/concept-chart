# -*- coding: utf-8 -*-
"""백본과 모델의 경계 점검: 학습 모델·실험 코드가 들어와도 백본이 깨지지 않게 막는다 (docs/ARCHITECTURE.md '모델 경계')

    python tests/test_boundary.py

- 의존: kit/는 학습 패키지와 실험 코드를 불러오지 않는다. 아무것도 experiments/를 불러오지 않는다. 기본 설치에 학습 패키지가 없다.
- 동작: 모델 없이 규칙 그대로, 모델이 고장·지연·이상한 값이어도 색인 계속, 서버 본체는 모델을 불러오지 않는다.
네트워크 없음, 임시 폴더에서만 돈다.
"""
import ast
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
import serve  # noqa: E402

FAILS = []
ML = {"torch", "transformers", "peft", "sentence_transformers", "onnxruntime", "tensorflow", "keras", "accelerate", "datasets"}
ROLES = {"assistant", "subagent"}


def ok(name, cond, info=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (f" — {info}" if info else ""))
    if not cond:
        FAILS.append(name)


def imports(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def rec(sess, text):
    return json.dumps({"v": 1, "role": "assistant", "session_id": sess, "ts": "2026-11-08T10:00:00+09:00", "text": text}, ensure_ascii=False) + "\n"


def check_imports():
    kit = sorted((ROOT / "kit").glob("*.py"))
    bad = {p.name: sorted(imports(p) & (ML | {"experiments", "sim", "web", "tests"})) for p in kit}
    bad = {k: v for k, v in bad.items() if v}
    ok("kit/는 학습 패키지·실험 코드·다른 폴더를 불러오지 않음", not bad, str(bad) if bad else f"{len(kit)}개 파일")
    others = [p for d in ("kit", "sim", "web", "tests") for p in (ROOT / d).glob("*.py")] + [ROOT / "dev.py"]
    bad = [p.name for p in others if "experiments" in imports(p)]
    ok("아무것도 experiments/를 불러오지 않음", not bad, ", ".join(bad))
    for name in ("requirements.txt", "environment.yml"):
        txt = (ROOT / name).read_text(encoding="utf-8").lower()
        found = [m for m in sorted(ML) if re.search(rf"(^|[\s\-]){re.escape(m)}\s*([=<>~]|$)", txt, re.M)]
        ok(f"{name}에 학습 패키지 없음 (학습은 requirements-ml.txt 따로)", not found, ", ".join(found))


def stub(tmp):
    (tmp / "stub_models.py").write_text(r'''
import sys, time
class Good:
    def canonical(self, form):
        return {"로라": "LoRA", "lora": "LoRA"}.get(form.lower())
class Boom:
    def canonical(self, form):
        raise RuntimeError("모델 고장")
class Odd:
    def canonical(self, form):
        return 123
class Empty:
    def canonical(self, form):
        return "   "
class Slow:
    def canonical(self, form):
        time.sleep(30)
class Noisy(Good):
    def canonical(self, form):
        print("모델이 stdout에 찍는 잡음")
        return super().canonical(form)
def good(): return Good()
def boom(): return Boom()
def odd(): return Odd()
def empty(): return Empty()
def slow(): return Slow()
def noisy(): return Noisy()
def broken_load(): raise ImportError("모델 파일 없음")
''', encoding="utf-8")
    sys.path.insert(0, str(tmp))


def board(tmp, name, spec, lines):
    ib, db = tmp / f"{name}.jsonl", tmp / f"{name}.sqlite"
    ib.write_text("".join(lines), encoding="utf-8")
    serve.set_model(spec)
    con = serve.open_db(db)
    try:
        n = serve.ingest(con, ib, ROLES)
        return n, {x["id"]: x["sessions"] for x in serve.leaderboard(con, k=50, now=0)["items"]}
    finally:
        con.close()
        serve.set_model(None)


def check_slot(tmp):
    lines = [rec("a", "LoRA는 미세조정 방법입니다."), rec("b", "로라로 학습합니다."), rec("c", "트랜스포머 이야기입니다.")]
    n, base = board(tmp, "none", None, lines)
    ok("모델 없음: 규칙 그대로 (LoRA와 로라는 따로)", n == 3 and "lora" in base and "로라" in base, ", ".join(sorted(base)))
    _, merged = board(tmp, "good", "stub_models:good", lines)
    ok("모델 켬: 표기를 묶을 수 있음", merged.get("lora") == 2 and "로라" not in merged, str(merged.get("lora")))
    for name, spec in [("예외", "stub_models:boom"), ("이상한 값", "stub_models:odd"), ("빈 값", "stub_models:empty"), ("불러오기 실패", "stub_models:broken_load"),
                       ("없는 모듈", "없는_모듈:load"), ("없는 함수", "stub_models:없는함수")]:
        n, got = board(tmp, f"bad{abs(hash(name))}", spec, lines)
        ok(f"모델 {name}: 색인 계속 + 규칙과 같은 결과", n == 3 and got == base)
    old = serve.MODEL_CALL_TIMEOUT
    serve.MODEL_CALL_TIMEOUT = 0.3
    t0 = time.time()
    n, got = board(tmp, "slow", "stub_models:slow", lines)
    serve.MODEL_CALL_TIMEOUT = old
    ok("모델 지연: 제한 시간 뒤 규칙으로 계속", n == 3 and got == base and time.time() - t0 < 10, f"{time.time() - t0:.1f}초")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def check_server(tmp):
    ib, db = tmp / "srv.jsonl", tmp / "srv.sqlite"
    ib.write_text(rec("a", "로라는 미세조정 방법입니다.") + rec("b", "LoRA로 학습합니다."), encoding="utf-8")
    port = free_port()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(tmp))
    p = subprocess.Popen([sys.executable, str(ROOT / "kit" / "serve.py"), "--inbox", str(ib), "--db", str(db), "--port", str(port), "--searx", "off", "--model", "stub_models:noisy"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)

    def get(path):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    try:
        got = None
        for _ in range(240):
            try:
                got = get("/api/status")
                if got["turns"] >= 2:
                    break
            except OSError:
                pass
            time.sleep(0.25)
        ok("stdout에 찍는 모델도 분석 프로세스 통신을 깨지 않음", bool(got) and got["turns"] == 2, str(got and got["turns"]))
        items = get("/api/leaderboard?k=20")["items"]
        ok("실제 서버에서 모델 적용", any(x["id"] == "lora" and x["sessions"] == 2 for x in items), ", ".join(x["id"] for x in items))
    finally:
        p.kill()
        p.wait()
        p.stdout.close()
    code = f"""
import sys, threading, time
sys.path.insert(0, {str(ROOT / 'kit')!r})
import serve
st = serve.State({str(tmp / 'iso.sqlite')!r}, {str(ib)!r}, {{'assistant'}}, None, None, 'stub_models:good')
threading.Thread(target=serve.tail_loop, args=(st, 0.1, 1.0), daemon=True).start()
for _ in range(1200):
    if st.version: break
    time.sleep(0.1)
print('version', st.version, 'stub', 'stub_models' in sys.modules, 'kiwi', 'kiwipiepy' in sys.modules)
st.stop.set()
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=180, env=env)
    out = r.stdout.decode("utf-8", "replace")
    ok("서버 본체는 모델을 불러오지 않음", "version 1 stub False kiwi False" in out, out.strip() + r.stderr.decode("utf-8", "replace")[-200:])
    # 모델을 바꾸면 색인을 다시 만든다 (정의는 남김)
    ib2, db2 = tmp / "ch.jsonl", tmp / "ch.sqlite"
    ib2.write_text(rec("a", "로라는 미세조정 방법입니다.") + rec("b", "LoRA로 학습합니다."), encoding="utf-8")

    def once(*extra):
        return subprocess.run([sys.executable, str(ROOT / "kit" / "serve.py"), "--once", "--inbox", str(ib2), "--db", str(db2), *extra],
                              capture_output=True, env=env, timeout=120).stdout.decode("utf-8", "replace")
    a = once()
    con = serve.open_db(db2)
    serve.save_note(con, "lora", "저장된 정의", [])
    con.close()
    b = once("--model", "stub_models:good")
    c = once()
    con = serve.open_db(db2)
    note = con.execute("SELECT definition FROM notes WHERE concept='lora'").fetchone()
    con.close()
    ok("모델을 켜고 끄면 색인을 다시 만들고 결과가 원래대로", "새 턴 2개" in b and "새 턴 2개" in c and "2세션" in b and [l for l in a.splitlines()[1:]] == [l for l in c.splitlines()[1:]])
    ok("모델을 바꿔도 저장된 정의는 남음", note is not None and note[0] == "저장된 정의")


def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        check_imports()
        stub(tmp)
        check_slot(tmp)
        check_server(tmp)
    finally:
        serve.set_model(None)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n결과: {'정상' if not FAILS else '실패 ' + str(len(FAILS)) + '개'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
