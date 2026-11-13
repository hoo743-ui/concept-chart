# -*- coding: utf-8 -*-
"""개념 분류기(0.8.0) 점검. 학습 패키지·실제 모델 없이, 가짜 점수 스크립트와 임시 폴더에서만 돈다.

    python tests/test_clf.py

- 관문: 분류기 점수와 기준점이 있을 때만 점수로 정하고, 규칙이 확신한 낱말·코드 이름·사용자 판단은 그대로 앞선다. 없으면 예전 판정.
- 작업자: 바뀐 낱말만 점수를 매기고(두 번째는 0개), 기준점을 적고, 점수 스크립트가 실패해도 예외로 끝나 관문은 예전 판정을 쓴다.
- 경계: kit/는 ml/을 불러오지 않는다 (별도 프로세스로만 실행).
"""
import ast
import json
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kit"))
import concept_gate as gate  # noqa: E402
import serve  # noqa: E402
import study_api  # noqa: E402
import study_worker  # noqa: E402

FAILS = []

FAKE = '''import json, sys
sys.stdin.reconfigure(encoding="utf-8"); sys.stdout.reconfigure(encoding="utf-8")
if "--fail" in open(sys.argv[0], encoding="utf-8").read().splitlines()[-1]:
    sys.exit(3)
for line in sys.stdin:
    r = json.loads(line)
    print(json.dumps({"id": r["id"], "score": 0.99 if r["form"] == "에폭" else 0.6 if r["form"] == "시드" else 0.1}))
# ok
'''


def ok(name, cond, info=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (f" — {info}" if info else ""))
    if not cond:
        FAILS.append(name)


def gate_rules():
    f = gate.final
    ok("점수 ≥ 기준점이면 보여 줌", f("unknown", False, False, "mixed", False, 0.98, 0.97) == "show")
    ok("기준점 아래·0.5 이상이면 후보", f("unknown", True, True, None, False, 0.6, 0.97) == "candidate")
    ok("0.5 아래면 숨김", f("likely", True, True, "special", False, 0.2, 0.97) == "hide")
    ok("규칙 reject는 점수가 높아도 숨김", f("reject", None, None, None, False, 0.99, 0.97) == "hide")
    ok("규칙 accept는 점수가 낮아도 보여 줌", f("accept", None, None, None, False, 0.01, 0.97) == "show")
    ok("코드 이름은 점수와 상관없이 보여 줌", f("unknown", False, False, None, True, 0.01, 0.97) == "show")
    ok("기준점이 없으면 예전 판정", f("unknown", True, True, None, False, 0.01, None) == f("unknown", True, True, None))


def worker_and_api():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="clf-"))
    try:
        db = tmp / "t.sqlite"
        con = serve.open_db(db)
        for cid, n in (("에폭", 5), ("시드", 4), ("CI", 3)):
            con.execute("INSERT INTO freq VALUES (?,?)", (cid, n))
            con.execute("INSERT INTO forms VALUES (?,?,?)", (cid, cid, n))
            con.execute("INSERT INTO mentions VALUES (?,?,?,?,?,?)", (cid, "2026-11-13T00:00:00", "s", "assistant", f"{cid}를 늘려 학습했다.", 0))
        con.commit()
        mdir = tmp / "model"
        mdir.mkdir()
        (mdir / "concept_clf.json").write_text(json.dumps({"threshold": 0.97, "made": "t", "data_sha": "x"}), encoding="utf-8")
        script = tmp / "fake_clf.py"
        script.write_text(FAKE, encoding="utf-8")
        old = {k: os.environ.get(k) for k in ("CONCEPT_CHART_CLF", "CONCEPT_CHART_CLF_SCRIPT")}
        try:
            os.environ.pop("CONCEPT_CHART_CLF", None)
            ok("분류기를 켜지 않으면 작업자는 아무것도 안 함", study_worker.run_score(con) == 0)
            before = study_api.gate_of(con, "에폭", "에폭", use_user=False)
            os.environ["CONCEPT_CHART_CLF"] = str(mdir)
            os.environ["CONCEPT_CHART_CLF_SCRIPT"] = str(script)
            n1 = study_worker.run_score(con)
            con.commit()
            n2 = study_worker.run_score(con)
            ok("규칙이 확신하지 못한 낱말만 점수 (CI는 규칙 accept)", n1 == 2, f"{n1}")
            ok("바뀐 것이 없으면 다시 매기지 않음", n2 == 0, f"{n2}")
            ok("기준점을 settings에 적음", study_api.clf_of(con, "에폭") == (0.99, 0.97), str(study_api.clf_of(con, "에폭")))
            g1 = study_api.gate_of(con, "에폭", "에폭", use_user=False)
            ok("점수가 기준점 이상이면 공부 목록 (by=clf)", g1["show"] and g1["by"] == "clf", str(g1))
            g2 = study_api.gate_of(con, "시드", "시드", use_user=False)
            ok("기준점 아래 0.6은 후보", g2["candidate"] and not g2["show"], str(g2))
            con.execute("UPDATE judgments SET user='not_concept' WHERE concept='에폭'")
            ok("사용자 판단이 가장 앞섬", not study_api.gate_of(con, "에폭", "에폭")["show"])
            con.execute("UPDATE judgments SET user=NULL WHERE concept='에폭'")
            con.execute("INSERT INTO mentions VALUES (?,?,?,?,?,?)", ("시드", "2026-11-13T01:00:00", "s", "assistant", "시드를 고정했다.", 0))
            script.write_text(FAKE.replace("# ok", "# --fail"), encoding="utf-8")
            try:
                study_worker.run_score(con)
                failed = False
            except RuntimeError:
                failed = True
            ok("점수 스크립트가 실패하면 예외 (작업만 실패)", failed)
            ok("실패해도 예전 점수는 그대로", study_api.clf_of(con, "시드")[0] == 0.6)
            con.execute("DELETE FROM settings WHERE k='clf_threshold'")
            ok("기준점을 지우면(분류기 끔) 예전 판정", study_api.gate_of(con, "에폭", "에폭", use_user=False) == before)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def boundary():
    bad = []
    for p in (ROOT / "kit").rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            bad += [f"{p.name}:{n}" for n in names if n.split(".")[0] in ("concept_clf", "ml")]
    ok("kit/는 ml/을 불러오지 않음", not bad, ", ".join(bad))
    src = (ROOT / "ml" / "concept_clf.py").read_text(encoding="utf-8")
    ok("학습 코드가 앱과 같은 입력 글자를 씀", "from concept_clf import signal_text, text_of" in (ROOT / "experiments" / "2026-11-13-expand" / "train.py").read_text(encoding="utf-8")
       and "def text_of" in src)


def main():
    gate_rules()
    worker_and_api()
    boundary()
    print("\n결과:", "모두 통과" if not FAILS else f"실패 {len(FAILS)}개: {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
