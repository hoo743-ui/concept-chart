# -*- coding: utf-8 -*-
"""실험 W1: 도구·제품·회사 이름을 위키데이터로 확인한다 (사용자 결정 11-11 '1,2,3 싹다 진행', 정답 기준 11-10: 기술 제품·회사·도구 이름은 개념).

    python experiments/2026-11-10-general-gate/wikidata_names.py

- 대상: 규칙이 판단 못 함(unknown) + 분야 사전에 없음 + 지금 관문이 숨긴 낱말 (pandas, conda, Ubuntu처럼 국어사전 밖의 이름)
- 인정: 위키데이터 항목의 이름이나 별칭이 낱말과 정확히 같고(대소문자 무시), 그 항목이 아래 분류(하위 분류 포함)에 속한다
  소프트웨어 Q7397, 프로그래밍 언어 Q9143, 회사 Q783794, 사업 Q4830453, 웹사이트 Q35127, 파일 형식 Q235557 (번호는 11-11 API로 확인)
  LLM을 쓰지 않는다. 근거는 위키데이터 항목 번호로 남는다 (CC0)
- 함께 저장: 그 항목의 한국어 위키백과 문서 제목 (설명 찾기에 쓸 수 있는지 보려고)
- 조회는 1초에 한 번, 결과는 data/eval/<세트>/wikidata.json 에 저장해 다시 묻지 않는다
"""
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

c2, g, ev = R.c2, R.g, R.ev
UA = "concept-chart-eval/0.1 (local research script)"
CLASSES = {"Q7397": "소프트웨어", "Q9143": "프로그래밍 언어", "Q783794": "회사", "Q4830453": "사업", "Q35127": "웹사이트", "Q235557": "파일 형식"}


PACE = 5.0           # 요청 간격(초). 11-11에 위키데이터가 장애 대응으로 요청을 강하게 제한하고 있었다


class RateLimited(Exception):
    pass


def get(url):
    """서버가 429로 기다리라고 하면 retry-after만큼 기다린다. 연속 5번이면 멈춘다 (받은 것은 저장돼 있다)"""
    for _ in range(5):
        time.sleep(PACE)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            wait = int(e.headers.get("retry-after") or 30)
            print(f"  위키데이터가 기다리라고 함: {wait}초", flush=True)
            time.sleep(min(wait, 300))
    raise RateLimited("위키데이터 요청 제한이 계속됨")


def candidates(word):
    """이름·별칭이 정확히 같은 항목 번호 (영어·한국어 검색)"""
    ids = []
    for lang in ("en", "ko"):
        q = urllib.parse.urlencode({"action": "wbsearchentities", "search": word, "language": lang, "type": "item", "limit": 10, "format": "json"})
        for r in get("https://www.wikidata.org/w/api.php?" + q).get("search", []):
            m = r.get("match", {})
            if m.get("type") in ("label", "alias") and m.get("text", "").lower() == word.lower() and r["id"] not in ids:
                ids.append(r["id"])
    return ids


PARENTS = {}          # 분류 → 상위 분류(P279). 조회 서버(SPARQL)가 11-11에 1분 1회로 막혀 있어 일반 API로 직접 따라 올라간다
MAX_DEPTH = 8


def entities(ids, props):
    out = {}
    for i in range(0, len(ids), 50):
        q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": props, "sitefilter": "kowiki", "format": "json"})
        out.update(get("https://www.wikidata.org/w/api.php?" + q).get("entities", {}))
    return out


def claim_ids(ent, prop):
    return [c["mainsnak"]["datavalue"]["value"]["id"] for c in ent.get("claims", {}).get(prop, [])
            if c.get("mainsnak", {}).get("snaktype") == "value"]


def ancestors(classes):
    """분류들과 그 상위 분류 전부 (깊이 MAX_DEPTH까지)"""
    seen, frontier = set(classes), list(classes)
    for _ in range(MAX_DEPTH):
        todo = [c for c in frontier if c not in PARENTS]
        if todo:
            for k, e in entities(todo, "claims").items():
                PARENTS[k] = claim_ids(e, "P279")
        frontier = [p for c in frontier for p in PARENTS.get(c, []) if p not in seen]
        seen.update(frontier)
        if not frontier:
            break
    return seen


def classify(ids):
    """→ {항목: [분류 이름]} (분류에 속하고 한국어 위키백과 문서가 연결된 항목만), {항목: 한국어 위키백과 제목}.
    한국어 문서 조건(11-11 첫 세트 결과로 더함): active·complex·mg처럼 흔한 영어 낱말과 이름이 같은 작은 소프트웨어·회사 항목이 걸렸다.
    분류를 따라 올라가기 전에 거르므로 요청도 줄어든다"""
    if not ids:
        return {}, {}
    hits, ko = {}, {}
    for i, e in entities(ids, "claims|sitelinks").items():
        if "kowiki" not in e.get("sitelinks", {}):
            continue
        ko[i] = e["sitelinks"]["kowiki"]["title"]
        found = sorted({CLASSES[c] for c in ancestors(claim_ids(e, "P31")) if c in CLASSES})
        if found:
            hits[i] = found
    return hits, ko


def lookup(word, cache):
    if word not in cache:
        ids = candidates(word)
        hits, ko = classify(ids)
        cache[word] = {"ids": ids, "hits": hits, "ko": ko}
    return cache[word]


def target(x, c_old, wk):
    f = x["form"]
    return (g.rule_verdict(f, x.get("sents")) == "unknown" and g.lexicon_verdict(f) is None
            and g.final("unknown", c_old.get(f), wk.get(f), None) != "show")


CLASS_CACHE = c2.EVAL / "wikidata_classes.json"


def main():
    g.load_lexicons(ev.LEX)
    if CLASS_CACHE.exists():
        PARENTS.update(json.loads(CLASS_CACHE.read_text(encoding="utf-8")))
    try:
        run()
    except RateLimited as e:
        print("멈춤:", e, "— 받은 결과는 저장됨. 나중에 다시 실행하면 이어서 묻는다")
    finally:
        CLASS_CACHE.write_bytes(json.dumps(PARENTS, ensure_ascii=False).encode("utf-8"))


def accepted(entry):
    """분류에 속하고 한국어 위키백과 문서가 연결된 항목이 하나라도 있다 (예전 규칙으로 저장된 결과에도 같은 조건을 건다)"""
    return any(i in entry.get("ko", {}) for i in entry.get("hits", {}))


def run():
    fx = c2.fixes()
    sets = {"조정용": c2.general_set("조정용", c2.EVAL / "general", "tune", fx, "조정용"),
            "IT 조정용": c2.general_set("IT 조정용", c2.EVAL / "tune2", "tune", fx, "IT 조정용"),
            "예전 holdout": c2.general_set("예전 holdout", c2.EVAL / "general", "holdout", fx, "예전 holdout"),
            "새 분야": c2.general_set("새 분야", c2.EVAL / "fresh", "holdout", fx, "새 분야"),
            "개발 대화": c2.dev_set(fx)}
    if "--dev" in sys.argv:                              # 실제 대화 세트만 (11-11: 위키데이터 요청 제한 중이라 범위를 줄인다)
        sets = {"개발 대화": sets["개발 대화"]}
    for name, (items, gold, D, sfx) in sets.items():
        drop = R.leaked_all(gold)
        items = [x for x in items if x["form"] not in drop]
        c_old, _c_sp, wk = c2.prepare(items, D, sfx)
        path = D / f"wikidata{sfx}.json"
        cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        todo = [x for x in items if target(x, c_old, wk)]
        try:
            for i, x in enumerate(todo, 1):
                lookup(x["form"], cache)
                if i % 20 == 0:
                    print(f"  {name} {i}/{len(todo)}", flush=True)
        finally:
            path.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
        base = [x["form"] for x in items if g.final(g.rule_verdict(x["form"], x.get("sents")), c_old.get(x["form"]), wk.get(x["form"]), g.lexicon_verdict(x["form"])) == "show"]
        add = [x["form"] for x in todo if accepted(cache[x["form"]])]
        pos = sum(gold[x["form"]] for x in items)
        tp0, tp1 = sum(gold[f] for f in base), sum(gold[f] for f in base) + sum(gold[f] for f in add)
        n1 = len(base) + len(add)
        print(f"\n{name}: 대상 {len(todo)}, 위키데이터로 인정 {len(add)} (개념 {sum(gold[f] for f in add)})")
        print(f"  지금 {len(base)} 정밀도 {tp0 / max(1, len(base)):.3f} 재현율 {tp0 / max(1, pos):.3f} → 더하면 {n1} 정밀도 {tp1 / max(1, n1):.3f} 재현율 {tp1 / max(1, pos):.3f}")
        print("  인정한 개념:", ", ".join(f for f in add if gold[f])[:400])
        print("  인정한 오탐:", ", ".join(f"{f}({'/'.join(sorted({c for k, v in cache[f]['hits'].items() if k in cache[f]['ko'] for c in v}))})" for f in add if not gold[f])[:400])
        miss = [x["form"] for x in todo if gold[x["form"]] and not accepted(cache[x["form"]])]
        print("  못 찾은 개념:", ", ".join(miss)[:300])


if __name__ == "__main__":
    main()
