# -*- coding: utf-8 -*-
"""공부 목록에 쉬운 낱말·영어 일상어가 많이 박힌다 (11-14 사용자: '이걸 일일이 사용자가 다 골라야돼? 불편해').
개발 서버는 개념 분류기(0.8.0, 사용자 결정 '0.97로 가자')를 켜지 않고 돌고 있었다. 켜면 지금 공부 목록에서 무엇이 빠지는지 잰다.

    python experiments/2026-11-14-clf-on/run.py     → results.json (낱말 이름·점수만), 화면 요약

DB는 읽기만 한다. 점수는 작업자와 같은 입력(kit/study_worker.clf_inputs)으로 ml/concept_clf.py를 따로 실행해 얻는다.
사람이 판단한 낱말(맞아요·아니에요)은 분류기와 상관없이 그대로라서 따로 센다.
"""
import json
import pathlib
import sqlite3
import subprocess
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(ROOT / "kit")]
sys.stdout.reconfigure(encoding="utf-8")
import study_worker as sw  # noqa: E402

DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
MODEL = ROOT / "models" / "concept-clf"


def main():
    cfg = json.loads((MODEL / "concept_clf.json").read_text(encoding="utf-8"))
    th = float(cfg["threshold"])
    items = json.loads(urllib.request.urlopen("http://127.0.0.1:8765/api/study/concepts?view=show&k=5000", timeout=30).read())["items"]
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    rows = [r for r, _k in sw.clf_inputs(con, "exp")]
    r = subprocess.run([sys.executable, str(ROOT / "ml" / "concept_clf.py"), "--model", str(MODEL)],
                       input="\n".join(json.dumps(x, ensure_ascii=False) for x in rows), capture_output=True, text=True, encoding="utf-8", timeout=1800)
    if r.returncode != 0:
        sys.exit(r.stderr[-800:])
    score = {}
    for line in r.stdout.splitlines():
        try:
            g = json.loads(line)
            score[g["id"]] = g["score"]
        except (ValueError, KeyError):
            pass
    out, drop, keep, user, rule = [], [], [], [], []
    for x in items:
        by = (x.get("gate") or {}).get("by")
        s = score.get(x["id"])
        row = {"label": x["label"], "by": by, "rule": (x.get("gate") or {}).get("rule"), "score": s}
        out.append(row)
        if by == "user":
            user.append(row)
        elif s is None:
            rule.append(row)                                 # 규칙이 확신한 낱말(accept): 분류기를 쓰지 않는다
        elif s < th:
            drop.append(row)
        else:
            keep.append(row)
    summary = {"show": len(items), "threshold": th, "user_judged": len(user), "rule_sure": len(rule), "clf_keep": len(keep), "clf_drop": len(drop)}
    (HERE / "results.json").write_text(json.dumps({"summary": summary, "rows": out}, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False))
    print("\n빠지는 낱말:", " ".join(r["label"] for r in sorted(drop, key=lambda r: r["score"])))
    print("\n남는 낱말(분류기):", " ".join(r["label"] for r in sorted(keep, key=lambda r: -r["score"])))
    print("\n규칙이 확신해서 남는 낱말:", " ".join(r["label"] for r in rule))



def caps():
    """두 번째 실험: 대문자 줄임말(2~6자)은 지금 규칙만으로 통과(accept)한다 → BY·KR·CH·OH·OIL 같은 조각도 들어온다.
    규칙 통과를 빼고(unknown으로 보고) 분류기가 판정하면 어디에 서는지 잰다. 사람이 판단한 낱말은 뺀다."""
    import re
    import concept_gate as gate
    import study_api as api
    cfg = json.loads((MODEL / "concept_clf.json").read_text(encoding="utf-8"))
    items = json.loads(urllib.request.urlopen("http://127.0.0.1:8765/api/study/concepts?view=show&k=5000", timeout=30).read())["items"]
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    rows = []
    for x in items:
        g = x.get("gate") or {}
        if g.get("by") != "rule" or g.get("rule") != "accept" or not re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", x["label"]):
            continue
        lex = gate.lexicon_verdict(x["label"])
        j = con.execute("SELECT llm FROM judgments WHERE concept=?", (x["id"],)).fetchone()
        sents = [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (x["id"],))]
        rows.append({"id": x["id"], "form": x["label"], "sents": sents, "rule": "unknown", "lex": lex,
                     "llm": None if not j or j[0] is None else bool(j[0]), "wiki": None if lex == "general" else api.sourced(con, x["id"])})
    r = subprocess.run([sys.executable, str(ROOT / "ml" / "concept_clf.py"), "--model", str(MODEL)],
                       input="\n".join(json.dumps(x, ensure_ascii=False) for x in rows), capture_output=True, text=True, encoding="utf-8", timeout=1800)
    if r.returncode != 0:
        sys.exit(r.stderr[-800:])
    sc = {json.loads(l)["id"]: json.loads(l)["score"] for l in r.stdout.splitlines() if l.strip().startswith("{")}
    lab = {x["id"]: x["form"] for x in rows}
    ranked = sorted(sc.items(), key=lambda kv: kv[1])
    th = float(cfg["threshold"])
    print("대문자 줄임말", len(rows), "개 · 기준점", th)
    print("빠짐:", " ".join(f"{lab[k]}({v:.2f})" for k, v in ranked if v < th))
    print("남음:", " ".join(f"{lab[k]}({v:.2f})" for k, v in ranked if v >= th))
    (HERE / "caps_results.json").write_text(json.dumps({lab[k]: v for k, v in ranked}, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    caps() if "--caps" in sys.argv else main()
