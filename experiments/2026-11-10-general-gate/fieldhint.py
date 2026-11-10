# -*- coding: utf-8 -*-
"""실험 V4: 분야 사전의 분야를 LLM 질문(judge_prompt)에 힌트로 주면 V3(두 번째 질문 '일상어인가')보다 나은가. 사용자 결정 11-10 "가".

    python experiments/2026-11-10-general-gate/fieldhint.py            # 조정용 + 개발 대화(고정)
    python experiments/2026-11-10-general-gate/fieldhint.py --fresh    # 새 분야 세트(이미 본 세트)도

묻는 낱말: 규칙이 판단 못 함(unknown) + 전문 뜻만(special) + LLM이 아니라 함 + 사전에 분야가 있음. 답은 data/eval/<세트>/fieldhint_<질문 지문>.json.
비교하는 안 (모두 기본 목록은 r5 그대로이고, 살린 낱말을 더해 센다)
- base : 지금 관문
- V3   : 위키백과 문서 + 두 번째 질문 '일상어 아님' (everyday.py, 0.5.4에 들어감)
- V4   : 위키백과 문서 + 분야 힌트 질문 '전문 용어'
- V4w  : 분야 힌트 질문 '전문 용어'만 (위키백과 문서 조건 없음)
"""
import hashlib
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as ev  # noqa: E402
import everyday as ed_mod  # noqa: E402

g, llm = ev.g, ev.llm
ROOT = ev.ROOT
sys.path.insert(0, str(ROOT / "kit"))
import fields  # noqa: E402


def hint_prompt(form, sentences, flds):
    """judge_prompt 그대로 + 사전 분야 한 줄 (새 예시 낱말은 넣지 않는다: 평가 낱말이 새지 않게)"""
    base = g.judge_prompt(form, sentences)
    hint = f"참고: 국어사전에는 이 낱말이 '{', '.join(flds[:3])}' 분야의 전문 용어로만 실려 있다. 다만 사전에 전문 용어로 실린 말 중에도 일상에서 흔히 쓰는 말이 있다.\n"
    return base.replace("낱말: ", hint + "낱말: ", 1)


ASK = hashlib.sha1(hint_prompt("@@", ["@@"], ["@@"]).encode("utf-8")).hexdigest()[:10]


def asks(items, c):
    return [x for x in items if g.rule_verdict(x["form"], x.get("sents")) == "unknown" and g.lexicon_verdict(x["form"]) == "special"
            and c.get(x["form"]) is False and fields.fields_of(x["form"])]


def ask_all(items, path):
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo = [x for x in items if x["form"] not in cache]
    if todo:
        client = llm.make("ollama:qwen3:4b")
        assert client.available(), "LLM 없음"
    for i, x in enumerate(todo, 1):
        ev.gentle()
        cache[x["form"]] = bool(client.json(hint_prompt(x["form"], x.get("sents") or [], fields.fields_of(x["form"])), g.JUDGE_SCHEMA, 20)["is_term"])
        if i % 20 == 0:
            path.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
    path.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
    return cache


def verdict(variant, x, c, wk, ed, fh):
    f = x["form"]
    r, lex = g.rule_verdict(f, x.get("sents")), g.lexicon_verdict(f)
    v = g.final(r, c.get(f), wk.get(f), lex)
    if v == "show" or not (r == "unknown" and lex == "special" and c.get(f) is False):
        return v
    if variant == "V3" and wk.get(f) and ed.get(f) is False:
        return "show"
    if variant == "V4" and wk.get(f) and fh.get(f) is True:
        return "show"
    if variant == "V4w" and fh.get(f) is True:
        return "show"
    return v


def score(name, items, gold, c, wk, ed, fh):
    pos = [x["form"] for x in items if gold.get(x["form"])]
    out = {}
    for variant in ("base", "V3", "V4", "V4w"):
        shown = [x["form"] for x in items if x["form"] in gold and verdict(variant, x, c, wk, ed, fh) == "show"]
        tp = sum(gold[w] for w in shown)
        out[variant] = {"shown": len(shown), "precision": round(tp / max(1, len(shown)), 3), "recall": round(tp / max(1, len(pos)), 3),
                        "wrong": [w for w in shown if not gold[w]]}
        print(f"{name:12} {variant:4} 보여 줌 {len(shown):3}  정밀도 {out[variant]['precision']:.3f}  재현율 {out[variant]['recall']:.3f}")
    return out


def run_general(split, D, gold):
    ws = [x for x in json.loads((D / "words.json").read_text(encoding="utf-8")) if x["split"] == split and x["form"] in gold]
    c = json.loads((D / "llm_q4413de9271.json").read_text(encoding="utf-8"))
    wk = json.loads((D / "wiki.json").read_text(encoding="utf-8"))
    ed = ed_mod.ask_all(ed_mod.asks(ws, c, wk), D / f"everyday_{ed_mod.ASK}.json")
    fh = ask_all(asks(ws, c), D / f"fieldhint_{ASK}.json")
    print(f"{D.name}:{split} 힌트 질문 {len(asks(ws, c))}개")
    return score(f"{D.name}:{split}", ws, gold, c, wk, ed, fh)


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
    ed = ed_mod.ask_all(ed_mod.asks(items, c, wk), D / f"everyday_dev_{ed_mod.ASK}.json")
    fh = ask_all(asks(items, c), D / f"fieldhint_dev_{ASK}.json")
    print(f"개발 대화 힌트 질문 {len(asks(items, c))}개")
    return score("개발 대화", items, gold, c, wk, ed, fh)


def main():
    g.load_lexicons(ev.LEX)
    if not fields._open():
        sys.exit("분야 표가 있는 사전이 없습니다: python dev.py lexicon")
    D = ROOT / "data" / "eval" / "general"
    gold = json.loads((D / "gold.json").read_text(encoding="utf-8"))
    res = {"tune": run_general("tune", D, gold), "dev": run_dev()}
    if "--fresh" in sys.argv:
        F = ROOT / "data" / "eval" / "fresh"
        fg = json.loads((F / "gold.json").read_text(encoding="utf-8"))
        for w in ("번역", "통과", "형태소"):
            fg.pop(w, None)
        res["fresh(본 세트)"] = run_general("holdout", F, fg)
    print(json.dumps({k: {v: {"wrong": r["wrong"]} for v, r in x.items() if v in ("V4", "V4w")} for k, x in res.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
