# -*- coding: utf-8 -*-
"""훅 어댑터 계약 테스트: tests/fixtures/<도구>/cases.json 의 입력을 실제 훅 파일에 넣어 인박스 기록을 확인한다.

    python tests/test_hook.py

설치기(kit/install_concept_hook.py)의 render_hook()으로 설치될 것과 같은 훅을 임시 폴더에 만들고,
케이스마다 별도 프로세스로 실행한다. 진짜 ~/.claude 설정과 인박스는 건드리지 않는다.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "claude_code" / "cases.json"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_concept_hook", ROOT / "kit" / "install_concept_hook.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_record(rec, exp):
    errs = []
    for k in ("role", "text", "session_id", "project", "agent_type", "truncated"):
        if k in exp and rec.get(k) != exp[k]:
            errs.append(f"{k}: {rec.get(k)!r} ≠ {exp[k]!r}")
    if "raw" in exp and ("raw" in rec) != exp["raw"]:
        errs.append(f"raw 있음={('raw' in rec)} ≠ {exp['raw']}")
    if "raw_has" in exp and exp["raw_has"] not in json.dumps(rec.get("raw"), ensure_ascii=False):
        errs.append(f"raw에 {exp['raw_has']!r} 없음")
    if "text_has" in exp and exp["text_has"] not in rec.get("text", ""):
        errs.append(f"text에 {exp['text_has']!r} 없음")
    for bad in exp.get("text_not_has", []):
        if bad in rec.get("text", ""):
            errs.append(f"text에 가려야 할 {bad!r}가 남음")
    if "text_len" in exp and len(rec.get("text", "")) != exp["text_len"]:
        errs.append(f"text 길이 {len(rec.get('text', ''))} ≠ {exp['text_len']}")
    for k in ("v", "source", "ts"):
        if k not in rec:
            errs.append(f"{k} 없음")
    return errs


def main():
    inst = load_installer()
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
    tmp = pathlib.Path(tempfile.mkdtemp())
    failed = 0
    try:
        hook = tmp / "concept_hook.py"
        hook.write_text(inst.render_hook((tmp / "unused.jsonl").as_posix()), encoding="utf-8")
        for i, case in enumerate(cases):
            inbox = tmp / f"inbox_{i}.jsonl"
            if "stdin" in case:
                body = case["stdin"]
            else:
                payload = dict(case["payload"])
                if payload.get("prompt") == "@@LONG@@":
                    payload["prompt"] = "가" * 25000
                body = json.dumps(payload, ensure_ascii=False)
            env = dict(os.environ, CONCEPT_INBOX=str(inbox))
            r = subprocess.run([sys.executable, str(hook)], input=body.encode("utf-8"), env=env,
                               capture_output=True, timeout=30)
            lines = inbox.read_text(encoding="utf-8").splitlines() if inbox.exists() else []
            errs = []
            if r.returncode != 0:
                errs.append(f"종료 코드 {r.returncode} (항상 0이어야 함)")
            if r.stdout.strip():
                errs.append("훅이 화면(stdout)에 무언가 출력함 — UserPromptSubmit에서는 Claude 문맥에 섞인다")
            if case["expect"] is None:
                if lines:
                    errs.append(f"기록이 없어야 하는데 {len(lines)}줄 생김")
            elif len(lines) != 1:
                errs.append(f"기록 1줄이어야 하는데 {len(lines)}줄")
            else:
                errs += check_record(json.loads(lines[0]), case["expect"])
            print(("[OK]   " if not errs else "[FAIL] ") + case["name"] + ("" if not errs else " — " + "; ".join(errs)))
            failed += bool(errs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print(f"훅 어댑터 테스트: {len(cases) - failed}/{len(cases)} 통과")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
