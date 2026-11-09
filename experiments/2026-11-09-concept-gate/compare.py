# -*- coding: utf-8 -*-
"""개념 관문 비교: 없음·사전·규칙·LLM·규칙+LLM. 정답은 결과를 보기 전에 고정한 data/eval/concept_gold.txt (Claude 판단, 사용자 검토 전).

    python experiments/2026-11-09-concept-gate/compare.py        # LLM 판정은 결과 파일에 저장, 다시 돌리면 건너뛴다
"""
import json
import pathlib
import sqlite3
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import concept_gate as g  # noqa: E402
import llm  # noqa: E402

CACHE = ROOT / "data" / "eval" / "gate_llm.json"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "ollama:qwen3:4b"


def score(name, shown, gold, order):
    tp = sum(1 for x in shown if x in gold)
    top = [x for x in order if x in shown][:30]
    r = {"method": name, "shown": len(shown), "precision": round(tp / max(1, len(shown)), 3), "recall": round(tp / len(gold), 3), "top30_precision": round(sum(x in gold for x in top) / max(1, len(top)), 3)}
    r["wrong_top"] = [x for x in top if x not in gold][:12]
    r["missed"] = [x for x in order if x in gold and x not in shown][:12]
    print(json.dumps(r, ensure_ascii=False))
    return r


def main():
    gold = set((ROOT / "data" / "eval" / "concept_gold.txt").read_text(encoding="utf-8").split())
    con = sqlite3.connect(f"file:{pathlib.Path.home()}/.claude/concept-chart.sqlite?mode=ro", uri=True)
    rows = con.execute("SELECT f.concept, (SELECT form FROM forms x WHERE x.concept=f.concept ORDER BY n DESC LIMIT 1) FROM freq f ORDER BY f.n DESC, f.concept").fetchall()
    order = [r[1] for r in rows]
    missing = gold - set(order)
    print("개념", len(order), "정답", len(gold), "목록에 없는 정답", sorted(missing))
    gold -= missing
    rule = {f: g.rule_verdict(f) for f in order}
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    client = llm.make(MODEL)
    assert client.available(), "LLM 없음"
    t0, fails = time.time(), 0
    for c, f in rows:
        if f in cache:
            continue
        sents = [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (c,))]
        try:
            cache[f] = bool(client.json(g.judge_prompt(f, sents), g.JUDGE_SCHEMA, 20)["is_term"])
        except llm.LLMError as e:
            fails += 1
            print("실패", type(e).__name__, str(e)[:80], flush=True)
        if len(cache) % 25 == 0:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print("LLM 판정", len(cache), "실패", fails, "초", round(time.time() - t0), flush=True)
    res = [score("없음", set(order), gold, order),
           score("사전만", {f for f in order if g.key(f) in g.terms()}, gold, order),
           score("규칙(LLM 없음)", {f for f in order if g.final(rule[f]) == "show"}, gold, order),
           score("LLM만", {f for f in order if cache.get(f)}, gold, order),
           score("규칙+LLM 전부", {f for f in order if g.final(rule[f], cache.get(f)) in ("show", "candidate")}, gold, order),
           score("채택: 공부 목록", {f for f in order if g.final(rule[f], cache.get(f)) == "show"}, gold, order)]
    (HERE / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
