# -*- coding: utf-8 -*-
"""설명 없는 개념의 '여러 뜻' 위키백과 문서에서 맞는 뜻 고르기 실험 (11-14, 사용자 승인 'ㅇㅇ 실험해').

    python experiments/2026-11-14-disamb/run.py            → results.json, 화면 요약

대상: 공부 목록(서버 /api/study/concepts)에서 설명이 없는 개념.
방법: 1) 한국어 위키백과 덤프 색인에서 그 이름이 동음이의 문서인지 본다
      2) 위키백과 API로 그 동음이의 문서가 가리키는 문서 목록을 받는다 (밖으로 나가는 건 개념 이름뿐)
      3) 후보 문서의 첫 문단(덤프 색인)에 내 대화에서 함께 나온 개념 이름이 몇 개 들었는지로 점수
      4) 1등 점수가 MIN_SCORE 이상이고 2등보다 MARGIN 이상 높을 때만 고른다. 아니면 '못 고름' (지어내지 않는다)
DB는 읽기만 한다. 서비스 코드는 바꾸지 않는다.
"""
import json
import pathlib
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(ROOT / "kit")]
sys.stdout.reconfigure(encoding="utf-8")
import fetch_sources as fs  # noqa: E402

DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
CTX_K = 12            # 함께 나온 개념 몇 개를 볼지
MIN_SCORE = 2         # 1등 후보에 든 함께 나온 개념 수
MARGIN = 1


def context(con, cid):
    import concept_gate as gate
    out = []
    for (b,) in con.execute("SELECT b FROM cooc WHERE a=? ORDER BY n DESC, b LIMIT 80", (cid,)):
        top = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC LIMIT 1", (b,)).fetchone()
        label = top[0] if top else b
        if len(label) < 2 or gate.lexicon_verdict(label) in ("general", "mixed") or label in gate.GENERAL:
            continue
        out.append(label)
        if len(out) == CTX_K:
            break
    return out


CACHE = HERE / "links_cache.json"
_cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.is_file() else {}


def sense_links(title):
    if title in _cache:
        return _cache[title]
    _cache[title] = _sense_links(title)
    CACHE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8", newline="\n")
    return _cache[title]


def _sense_links(title):
    q = urllib.parse.quote(title)
    j = json.loads(fs._get(f"https://ko.wikipedia.org/w/api.php?action=query&prop=links&titles={q}&plnamespace=0&pllimit=200&redirects=1&format=json"))
    out = []
    for p in j.get("query", {}).get("pages", {}).values():
        out += [x["title"] for x in p.get("links", [])]
    return out


def main():
    items = json.loads(urllib.request.urlopen("http://127.0.0.1:8765/api/study/concepts?view=show&k=5000", timeout=30).read())["items"]
    missing = [x for x in items if not x.get("line")]
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    wiki = fs.local_wiki()
    rows, kinds = [], {}
    for i, x in enumerate(missing):
        label = x["label"]
        page = fs._local_page(wiki, label)
        kind = "없음" if not page else "동음이의" if page[2] else "문서 있음"
        kinds[kind] = kinds.get(kind, 0) + 1
        row = {"label": label, "kind": kind}
        if kind == "동음이의":
            ctx = context(con, x["id"])
            cands = []
            for t in sense_links(page[0]):
                p = fs._local_page(wiki, t)
                if not p or p[2] or not p[1]:
                    continue
                lead = fs.tidy(p[1])[:500]
                hay = (p[0] + " " + lead).lower()
                hit = [c for c in ctx if c.lower() in hay]
                cands.append({"title": p[0], "score": len(hit), "hit": hit, "lead": fs.split_sents(lead)[0] if fs.split_sents(lead) else lead[:200]})
            cands.sort(key=lambda c: -c["score"])
            ok = cands and cands[0]["score"] >= MIN_SCORE and (len(cands) == 1 or cands[0]["score"] - cands[1]["score"] >= MARGIN)
            row.update({"context": ctx, "n_cands": len(cands), "top": cands[:3], "pick": cands[0] if ok else None})
        rows.append(row)
        print(f"\r{i + 1}/{len(missing)}", end="", flush=True)
    print()
    picked = [r for r in rows if r.get("pick")]
    summary = {"missing": len(missing), "kinds": kinds, "disamb_picked": len(picked), "MIN_SCORE": MIN_SCORE, "MARGIN": MARGIN, "CTX_K": CTX_K}
    (HERE / "results.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False))
    for r in picked:
        print(f"- {r['label']} → {r['pick']['title']} ({r['pick']['score']}: {', '.join(r['pick']['hit'])}) | {r['pick']['lead'][:90]}")


if __name__ == "__main__":
    main()
