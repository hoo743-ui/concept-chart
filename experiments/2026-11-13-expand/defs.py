# -*- coding: utf-8 -*-
"""개념 넓히기 실험 3 (사용자 요청 11-13 'SearXNG 켜서 설명 비율 올려줘'·'이걸 좀 확장하고 싶은데'): 설명을 못 찾는 공부 목록 낱말을 어떻게 더 찾나.

    .venv/Scripts/python.exe experiments/2026-11-13-expand/defs.py [--n 60] [--searx http://localhost:8889]

원인 가설: 검색 결과 거르기의 문맥(serve.context_terms = 내 대화에서 함께 많이 나온 개념)이 이 사용자 대화에서는 '대화·기록·목록' 같은 일반어라
맞는 결과도 버린다 (conda → 문맥 ['Windows', '대화']).
비교 (실제 DB 읽기 전용, 설명이 없는 공부 목록 낱말을 빈도순으로 n개):
  A 지금: 문맥 = 함께 나온 개념 2개
  B 공부 목록 문맥: 함께 나온 개념 중 공부 목록(관문 show)이고 분야 사전에 일상 뜻이 없는 것만 2개
  C 문맥 없음
결과 → defs_result.json (낱말, 방식별 정의 첫 문장·출처). 맞는 뜻인지는 사람이 본다 (Claude 표시, 사용자 검토 전).
"""
import argparse
import json
import pathlib
import sqlite3
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "kit"))
import concept_gate as gate  # noqa: E402
import serve  # noqa: E402
import study_api as api  # noqa: E402

DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"


def study_context(con, cid, k=2):
    out = []
    for (b,) in con.execute("SELECT b FROM cooc WHERE a=? ORDER BY n DESC, b LIMIT 40", (cid,)):
        label = serve.label_of(con, b)
        if gate.lexicon_verdict(label) in ("general", "mixed"):
            continue
        if api.gate_of(con, b, label)["show"]:
            out.append(label)
        if len(out) == k:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--searx", default="http://localhost:8889")
    a = ap.parse_args()
    gate.load_lexicons()
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    items = api.concepts(con, serve.leaderboard, "show", 100000, origin=False)["items"]
    todo = [x for x in items if api.summary_line(con, x["id"])[0] is None][:a.n]
    print(f"설명 없는 공부 목록 낱말 {len(todo)}개", flush=True)
    out = []
    for i, x in enumerate(todo, 1):
        cid, label = x["id"], x["label"]
        aliases = [r[0] for r in con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form", (cid,))][1:]
        row = {"id": cid, "label": label}
        for name, ctx in (("A", serve.context_terms(con, cid)), ("B", study_context(con, cid)), ("C", [])):
            try:
                d, src = serve.fetch_note(label, aliases, a.searx, ctx)
                row[name] = {"ctx": ctx, "def": d, "url": src[0]["url"] if src else None}
            except Exception as e:  # noqa: BLE001
                row[name] = {"ctx": ctx, "error": f"{type(e).__name__}: {e}"[:120]}
        out.append(row)
        print(i, label, *(f"{k}:{'O' if row[k].get('def') else 'X'}" for k in "ABC"), flush=True)
        time.sleep(1)
    (HERE / "defs_result.json").write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    for k in "ABC":
        print(k, sum(bool(r[k].get("def")) for r in out), "/", len(out))


if __name__ == "__main__":
    main()
