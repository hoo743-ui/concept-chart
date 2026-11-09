# -*- coding: utf-8 -*-
"""개념 관문을 조정용 낱말과 처음 보는 낱말에서 따로 잰다. 정답은 결과를 보기 전에 고정했다 (Claude 표시, 사용자 검토 전).

    python experiments/2026-11-09-concept-gate/holdout.py
"""
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import concept_gate as g  # noqa: E402
import llm  # noqa: E402

CACHE = ROOT / "data" / "eval" / "gate_llm_strict.json"


def score(name, words, gold, verdict):
    shown = [w for w in words if verdict(w)]
    tp = sum(w in gold for w in shown)
    r = {"set": name, "words": len(words), "gold": sum(w in gold for w in words), "shown": len(shown), "precision": round(tp / max(1, len(shown)), 3), "recall": round(tp / max(1, sum(w in gold for w in words)), 3),
         "wrong": [w for w in shown if w not in gold][:40]}
    print(json.dumps(r, ensure_ascii=False), flush=True)
    return r


def main():
    d = ROOT / "data" / "eval"
    tune = set(json.loads((d / "gate_llm.json").read_text(encoding="utf-8")))
    gold = set((d / "concept_gold.txt").read_text(encoding="utf-8").split()) | {x.replace("_", " ") for x in (d / "concept_gold_holdout.txt").read_text(encoding="utf-8").split()}
    con = sqlite3.connect(f"file:{pathlib.Path.home()}/.claude/concept-chart.sqlite?mode=ro", uri=True)
    rows = con.execute("SELECT f.concept, (SELECT form FROM forms x WHERE x.concept=f.concept ORDER BY n DESC LIMIT 1) FROM freq f ORDER BY f.n DESC, f.concept").fetchall()
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    client = llm.make("ollama:qwen3:4b")
    for c, f in rows:
        if f not in cache:
            sents = [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (c,))]
            cache[f] = bool(client.json(g.judge_prompt(f, sents), g.JUDGE_SCHEMA, 20)["is_term"])
            if len(cache) % 25 == 0:
                CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    words = [r[1] for r in rows]
    res = []
    for name, group in (("조정용", [w for w in words if w in tune]), ("처음 보는 낱말", [w for w in words if w not in tune])):
        res.append(score(name + ": 규칙만(LLM 없음)", group, gold, lambda w: g.final(g.rule_verdict(w), None) == "show"))
        res.append(score(name + ": 채택(공부 목록)", group, gold, lambda w: g.final(g.rule_verdict(w), cache.get(w)) == "show"))
        res.append(score(name + ": 후보까지", group, gold, lambda w: g.final(g.rule_verdict(w), cache.get(w)) in ("show", "candidate")))
    (HERE / "holdout_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
