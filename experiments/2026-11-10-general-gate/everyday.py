# -*- coding: utf-8 -*-
"""실험: 분야 사전에 전문 뜻만 있는 낱말에 두 번째 질문(concept_gate.everyday_prompt)을 던지면 재현율을 올릴 수 있나.

    python experiments/2026-11-10-general-gate/everyday.py            # 조정용 + 개발 대화(고정)만
    python experiments/2026-11-10-general-gate/everyday.py --fresh    # 새 분야 세트(이미 본 세트)도

묻는 낱말: 규칙이 판단 못 함(unknown) + 전문 뜻만(special) + (LLM 인정 또는 위키백과 문서). 답은 data/eval/<세트>/everyday_<질문 지문>.json에 저장.
비교하는 안
- base : 지금 관문 (concept_gate.final)
- V1   : 전문 뜻만 + 위키백과 문서면 LLM이 아니라 해도 보여 줌
- V2   : 전문 뜻만 + (LLM 인정 또는 위키백과 문서) + 두 번째 질문이 '일상어 아님'이면 보여 줌, '일상어'면 숨김
- V3   : 지금 관문 + 구조만: 전문 뜻만 + LLM이 아니라 함 + 위키백과 문서 + 두 번째 질문이 '일상어 아님'이면 보여 줌
"""
import hashlib
import json
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as ev  # noqa: E402

g, llm = ev.g, ev.llm
ROOT = ev.ROOT
ASK = hashlib.sha1(g.everyday_prompt("@@", ["@@"]).encode("utf-8")).hexdigest()[:10]


def leak_guard(gold):
    examples = " ".join(m.group(1) for m in re.finditer(r"예:([^\n]*)", g.everyday_prompt("@@", [])))
    leaked = sorted(w for w in gold if len(w) >= 2 and re.search(rf"(?<![가-힣A-Za-z]){re.escape(w)}(?![가-힣A-Za-z])", examples))
    if leaked:
        sys.exit(f"두 번째 질문 예시에 평가 낱말이 있습니다: {leaked}")


def asks(items, llm_cache, wiki):
    return [x for x in items if g.rule_verdict(x["form"], x.get("sents")) == "unknown" and g.lexicon_verdict(x["form"]) == "special"
            and (llm_cache.get(x["form"]) is True or wiki.get(x["form"]))]


def ask_all(items, path):
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo = [x for x in items if x["form"] not in cache]
    if todo:
        client = llm.make("ollama:qwen3:4b")
        assert client.available(), "LLM 없음"
    for i, x in enumerate(todo, 1):
        ev.gentle()
        cache[x["form"]] = bool(client.json(g.everyday_prompt(x["form"], x.get("sents") or []), g.EVERYDAY_SCHEMA, 20)["everyday"])
        if i % 20 == 0:
            path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


def verdict(variant, x, c, wk, ed):
    f = x["form"]
    r, lex = g.rule_verdict(f, x.get("sents")), g.lexicon_verdict(f)
    v = g.final(r, c.get(f), wk.get(f), lex)
    if r == "unknown" and lex == "special":
        if variant == "V1" and wk.get(f):
            v = "show"
        if variant == "V2" and f in ed and (c.get(f) is True or wk.get(f)):
            v = "hide" if ed[f] else "show"
        if variant == "V3" and c.get(f) is False and wk.get(f) and ed.get(f) is False:
            v = "show"
    return v


def score(name, items, gold, c, wk, ed):
    pos = [x["form"] for x in items if gold.get(x["form"])]
    out = {}
    for variant in ("base", "V1", "V2", "V3"):
        shown = [x["form"] for x in items if x["form"] in gold and verdict(variant, x, c, wk, ed) == "show"]
        tp = sum(gold[w] for w in shown)
        out[variant] = {"shown": len(shown), "precision": round(tp / max(1, len(shown)), 3), "recall": round(tp / max(1, len(pos)), 3),
                        "wrong": [w for w in shown if not gold[w]]}
        print(f"{name:12} {variant:4} 보여 줌 {len(shown):3}  정밀도 {out[variant]['precision']:.3f}  재현율 {out[variant]['recall']:.3f}")
    return out


def run_general(split, D, gold):
    ws = [x for x in json.loads((D / "words.json").read_text(encoding="utf-8")) if x["split"] == split and x["form"] in gold]
    c = json.loads((D / "llm_q4413de9271.json").read_text(encoding="utf-8"))
    wk = json.loads((D / "wiki.json").read_text(encoding="utf-8"))
    ed = ask_all(asks(ws, c, wk), D / f"everyday_{ASK}.json")
    return score(f"{D.name}:{split}", ws, gold, c, wk, ed)


def run_dev():
    d = ROOT / "data" / "eval"
    gold_pos = set((d / "concept_gold.txt").read_text(encoding="utf-8").split()) | {x.replace("_", " ") for x in (d / "concept_gold_holdout.txt").read_text(encoding="utf-8").split()}
    con = sqlite3.connect(f"file:{pathlib.Path.home()}/.claude/concept-chart.sqlite?mode=ro", uri=True)
    items = []
    for cid, f in con.execute("SELECT f.concept, (SELECT form FROM forms x WHERE x.concept=f.concept ORDER BY n DESC LIMIT 1) FROM freq f "
                              "WHERE (SELECT MIN(ts) FROM mentions m WHERE m.concept=f.concept) < ? ORDER BY f.n DESC, f.concept", (ev.DEV_CUTOFF,)):
        items.append({"form": f, "sents": [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (cid,))]})
    gold = {x["form"]: x["form"] in gold_pos for x in items}
    D = ev.DEV_D
    c = json.loads((D / "llm_dev_q4413de9271.json").read_text(encoding="utf-8"))
    wk = json.loads((D / "wiki.json").read_text(encoding="utf-8"))
    ed = ask_all(asks(items, c, wk), D / f"everyday_dev_{ASK}.json")
    return score("개발 대화", items, gold, c, wk, ed)


def main():
    g.load_lexicons(ev.LEX)
    D = ROOT / "data" / "eval" / "general"
    gold = json.loads((D / "gold.json").read_text(encoding="utf-8"))
    leak_guard(gold)
    res = {"tune": run_general("tune", D, gold), "dev": run_dev()}
    if "--fresh" in sys.argv:
        F = ROOT / "data" / "eval" / "fresh"
        fg = json.loads((F / "gold.json").read_text(encoding="utf-8"))
        leak_guard(fg)
        for w in ("번역", "통과", "형태소"):
            fg.pop(w, None)
        res["fresh(본 세트)"] = run_general("holdout", F, fg)
    print(json.dumps({k: {v: {"wrong": r["wrong"]} for v, r in x.items() if v != "base"} for k, x in res.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
