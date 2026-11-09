# -*- coding: utf-8 -*-
"""분야를 가리지 않는 개념 관문 평가. 라운드(epoch)마다 같은 방법으로 잰다.

    python experiments/2026-11-10-general-gate/evaluate.py words            # 1) 색인 → 낱말 목록 (정답 표시용)
    python experiments/2026-11-10-general-gate/evaluate.py score r0         # 2) 조정용 분야 + 개발 대화 측정, rounds.json에 기록
    python experiments/2026-11-10-general-gate/evaluate.py score final --holdout   # 마지막에 한 번: 처음 보는 분야

할루시네이션·과적합 방지
- 정답(data/eval/general/gold.json)은 관문 결과를 보기 전에 고정한다. 정답 파일이 바뀌면 지문(hash)이 달라져 기록에 남는다.
- LLM 질문 예시에 평가 낱말이 들어 있으면 측정을 멈춘다.
- --holdout 없이는 처음 보는 분야 결과를 계산하지 않는다.
"""
import hashlib
import json
import pathlib
import re
import sqlite3
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import concept_gate as g  # noqa: E402
import llm  # noqa: E402

D = ROOT / "data" / "eval" / "general"
IDX = D / "idx.sqlite"
GOLD = D / "gold.json"
ROUNDS = HERE / "rounds.json"


def index():
    if IDX.exists():
        IDX.unlink()
    subprocess.run([sys.executable, str(ROOT / "kit" / "serve.py"), "--once", "--inbox", str(D / "inbox.jsonl"), "--db", str(IDX)], check=True, capture_output=True)


def words():
    """(개념 id, 대표 표기, 분야, split, 문장들). 답변(assistant)에 나온 낱말만"""
    qs = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    split_of = {f: s for s in ("tune", "holdout") for f in qs[s]}
    con = sqlite3.connect(IDX)
    out = []
    for c, form in con.execute("SELECT f.concept, (SELECT form FROM forms x WHERE x.concept=f.concept ORDER BY n DESC, form LIMIT 1) FROM freq f ORDER BY f.n DESC, f.concept"):
        sess = [r[0] for r in con.execute("SELECT DISTINCT session FROM term_sess WHERE concept=?", (c,))]
        splits = {split_of.get(s) for s in sess}
        sents = [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (c,))]
        out.append({"id": c, "form": form, "fields": sess, "split": "tune" if splits == {"tune"} else "holdout" if splits == {"holdout"} else "both", "sents": sents})
    return out


def fingerprint(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()[:10] if path.exists() else None


def guard_prompt(gold, allow=False):
    """LLM 질문의 예시('예:' 뒤)에 평가 낱말이 있으면 그 낱말의 결과를 믿을 수 없다. 기준선(r0)만 --allow-leak로 재고, 겹친 낱말을 기록한다"""
    examples = " ".join(m.group(1) for m in re.finditer(r"예:([^\n]*)", g.judge_prompt("@@", [])))
    leaked = sorted(w for w in gold if len(w) >= 2 and re.search(rf"(?<![가-힣A-Za-z]){re.escape(w)}(?![가-힣A-Za-z])", examples))
    if leaked and not allow:
        sys.exit(f"LLM 질문 예시에 평가 낱말이 들어 있습니다: {leaked}")
    return leaked


MAX_GPU_TEMP = 80              # 넘으면 식을 때까지 기다린다
PAUSE = 1.0                    # LLM 호출 사이 쉬는 시간 (초)


def gentle():
    """컴퓨터에 무리가 가지 않게: 메모리가 모자라거나 GPU가 뜨거우면 기다린다"""
    import study_worker as w
    w.wait_for_room(model_loaded=True)
    while True:
        try:
            temp = int(subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.split()[0])
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            temp = None
        if temp is None or temp < MAX_GPU_TEMP:
            break
        print(f"GPU {temp}도: 식을 때까지 기다림", flush=True)
        time.sleep(60)
    time.sleep(PAUSE)


NO_LLM = "--no-llm" in sys.argv     # AI를 받지 않은 컴퓨터 경우: LLM을 부르지 않고 kit/concept_gate.final_no_ai로 판정


def judge_all(items, cache_path):
    if NO_LLM:
        return {}
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    client = llm.make("ollama:qwen3:4b")
    assert client.available(), "LLM 없음"
    for x in items:
        if g.rule_verdict(x["form"]) in ("accept", "reject") or x["form"] in cache:
            continue
        if g.rule_verdict(x["form"]) == "unknown" and g.lexicon_verdict(x["form"]) == "general":
            continue                                   # 일상 뜻만 있는 낱말은 묻지 않아도 숨긴다
        gentle()
        cache[x["form"]] = bool(client.json(g.judge_prompt(x["form"], x["sents"]), g.JUDGE_SCHEMA, 20)["is_term"])
        if len(cache) % 25 == 0:
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


WIKI = D / "wiki.json"


def sourced_all(items, cache):
    """LLM이 인정했지만 사전에 없는 낱말만: 앱과 같은 코드(serve.fetch_note)로 이름이 맞는 위키백과 문서가 있는지. 저장해 두고 다시 묻지 않는다"""
    import serve
    wiki = json.loads(WIKI.read_text(encoding="utf-8")) if WIKI.exists() else {}
    want = (lambda f: g.lexicon_verdict(f) == "special") if NO_LLM else (lambda f: cache.get(f) is True)
    todo = [x["form"] for x in items if g.rule_verdict(x["form"]) == "unknown" and want(x["form"]) and x["form"] not in wiki]
    for i, f in enumerate(todo, 1):
        try:
            wiki[f] = bool(serve.fetch_note(f)[0])
        except Exception as e:  # noqa: BLE001 — 네트워크 오류는 저장하지 않고 다음에 다시
            print("위키 조회 실패", f, type(e).__name__, flush=True)
        if i % 20 == 0:
            WIKI.write_text(json.dumps(wiki, ensure_ascii=False), encoding="utf-8")
    WIKI.write_text(json.dumps(wiki, ensure_ascii=False), encoding="utf-8")
    return wiki


LEX = ROOT / "data" / "processed" / "lexicon"     # 분야 사전 (lexicon_*.py가 만든다). 없으면 사전 없이 잰다


def score(name, items, gold, cache, wiki=None):
    items = [x for x in items if x["form"] in gold]
    wiki = wiki or {}
    def verdict(f):
        if NO_LLM:
            return g.final_no_ai(g.rule_verdict(f), wiki.get(f), g.lexicon_verdict(f))
        return g.final(g.rule_verdict(f), cache.get(f), wiki.get(f), g.lexicon_verdict(f))
    shown = [x["form"] for x in items if verdict(x["form"]) == "show"]
    pos = [x["form"] for x in items if gold[x["form"]]]
    tp = sum(gold[w] for w in shown)
    r = {"set": name, "words": len(items), "gold": len(pos), "shown": len(shown), "precision": round(tp / max(1, len(shown)), 3), "recall": round(tp / max(1, len(pos)), 3),
         "wrong": [w for w in shown if not gold[w]][:30], "missed": [w for w in pos if w not in shown][:30]}
    print(json.dumps({k: v for k, v in r.items() if k not in ("wrong", "missed")}, ensure_ascii=False))
    return r


def dev_regression(cache_path):
    """개발 대화 낱말에서 이전 결과(정밀도 0.92 계열)가 무너지지 않는지. 정답은 data/eval/concept_gold*.txt"""
    d = ROOT / "data" / "eval"
    gold_pos = set((d / "concept_gold.txt").read_text(encoding="utf-8").split()) | {x.replace("_", " ") for x in (d / "concept_gold_holdout.txt").read_text(encoding="utf-8").split()}
    con = sqlite3.connect(f"file:{pathlib.Path.home()}/.claude/concept-chart.sqlite?mode=ro", uri=True)
    items = []
    for c, f in con.execute("SELECT f.concept, (SELECT form FROM forms x WHERE x.concept=f.concept ORDER BY n DESC LIMIT 1) FROM freq f ORDER BY f.n DESC, f.concept"):
        items.append({"form": f, "sents": [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (c,))]})
    cache = judge_all(items, cache_path)
    return score("개발 대화 (전체 낱말)", items, {x["form"]: x["form"] in gold_pos for x in items}, cache, sourced_all(items, cache))


def main():
    cmd = sys.argv[1]
    if cmd == "words":
        index()
        ws = words()
        (D / "words.json").write_text(json.dumps(ws, ensure_ascii=False, indent=0), encoding="utf-8")
        print("낱말", len(ws), {s: sum(x["split"] == s for x in ws) for s in ("tune", "holdout", "both")})
        return
    tag = sys.argv[2]
    holdout = "--holdout" in sys.argv
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    leaked = guard_prompt(gold, "--allow-leak" in sys.argv)
    ws = json.loads((D / "words.json").read_text(encoding="utf-8"))
    lex_files = sorted(LEX.glob("*.tsv")) if "--no-lex" not in sys.argv else []
    g.load_lexicons(LEX if lex_files else ROOT / "__none__")
    ver = hashlib.sha1((g.judge_prompt("@@", ["@@"]) + pathlib.Path(g.__file__).read_text(encoding="utf-8")).encode("utf-8")).hexdigest()[:10]   # 판정 버전 (기록용)
    ask = hashlib.sha1(g.judge_prompt("@@", ["@@"]).encode("utf-8")).hexdigest()[:10]   # LLM 질문이 같으면 답도 같다: 캐시는 질문 기준
    cache_path = D / f"llm_q{ask}.json"
    t0 = time.time()
    sets = ["tune", "both"] + (["holdout"] if holdout else [])
    cache = judge_all([x for x in ws if x["split"] in sets], cache_path)
    wiki = sourced_all([x for x in ws if x["split"] in sets], cache)
    res = [score(f"일반 분야 {s}", [x for x in ws if x["split"] == s], gold, cache, wiki) for s in sets]
    res.append(dev_regression(D / f"llm_dev_q{ask}.json"))
    log = json.loads(ROUNDS.read_text(encoding="utf-8")) if ROUNDS.exists() else []
    note = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--note=")), "")
    log.append({"round": tag, "time": time.strftime("%Y-%m-%d %H:%M"), "gate_version": ver, "gold": fingerprint(GOLD), "lexicons": {p.name: fingerprint(p) for p in lex_files}, "no_llm": NO_LLM, "holdout": holdout, "seconds": round(time.time() - t0), "note": note, "leaked": leaked, "results": res})
    ROUNDS.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    import dashboard
    print("대시보드", dashboard.build())


if __name__ == "__main__":
    main()
