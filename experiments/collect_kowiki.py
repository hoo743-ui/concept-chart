# -*- coding: utf-8 -*-
"""한국어 위키백과 분류 → 문서 제목·영어 링크·넘겨주기 원본 수집 (data/raw/, git 제외)

    python experiments/collect_kowiki.py

요청은 1.5초 간격, 429면 Retry-After만큼 쉰다. 받은 그대로 저장하고 고치지 않는다 (docs/TRAINING.md 3-1).
"""
import hashlib
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "kowiki_ml"
ROOTS = ["분류:기계 학습"]
MAX_DEPTH = 2                       # 분류를 몇 단계 아래까지 볼지
SKIP_CATS = {"분류:인공지능 콘퍼런스", "분류:기계 학습 및 데이터 마이닝 소프트웨어"}   # 개념이 아니라 행사·제품 위주
UA = {"User-Agent": "concept-chart-research/0.1 (personal study tool; ko-en term pairs)"}
API = "https://ko.wikipedia.org/w/api.php"
requests_made = 0


def api(**p):
    global requests_made
    url = API + "?" + urllib.parse.urlencode(dict(p, format="json", formatversion=2))
    for attempt in range(6):
        time.sleep(1.5)
        requests_made += 1
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 5:
                raise
            wait = int(e.headers.get("Retry-After") or 60)
            print(f"429: {wait}초 대기", flush=True)
            time.sleep(wait)


def crawl():
    seen_cats, queue, pages = set(), [(c, 0) for c in ROOTS], {}
    while queue:
        cat, depth = queue.pop(0)
        if cat in seen_cats or cat in SKIP_CATS:
            continue
        seen_cats.add(cat)
        # 문서: 영어 링크 + 넘겨주기 (한 요청에 최대 50개, 부분 결과는 이어 받아 합친다)
        cont = {}
        while True:
            d = api(action="query", generator="categorymembers", gcmtitle=cat, gcmlimit=50, gcmnamespace=0,
                    prop="langlinks|redirects", lllang="en", lllimit=500, rdlimit=500, rdnamespace=0, **cont)
            for p in d.get("query", {}).get("pages", []):
                rec = pages.setdefault(p["pageid"], {"pageid": p["pageid"], "title": p["title"], "en": [], "redirects": [], "cats": []})
                rec["en"] = sorted(set(rec["en"]) | {x["title"] for x in p.get("langlinks", [])})
                rec["redirects"] = sorted(set(rec["redirects"]) | {x["title"] for x in p.get("redirects", [])})
                if cat not in rec["cats"]:
                    rec["cats"].append(cat)
            if "continue" not in d:
                break
            cont = d["continue"]
        if depth < MAX_DEPTH:
            cont = {}
            while True:
                d = api(action="query", list="categorymembers", cmtitle=cat, cmtype="subcat", cmlimit=200, **cont)
                queue += [(x["title"], depth + 1) for x in d["query"]["categorymembers"]]
                if "continue" not in d:
                    break
                cont = d["continue"]
        print(f"분류 {len(seen_cats)}개, 문서 {len(pages)}개, 요청 {requests_made}번, 대기열 {len(queue)}", flush=True)
    return pages, sorted(seen_cats)


def main():
    pages, cats = crawl()
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "pages.jsonl"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for rec in sorted(pages.values(), key=lambda r: r["pageid"]):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    meta = {"source": API, "roots": ROOTS, "max_depth": MAX_DEPTH, "skip": sorted(SKIP_CATS), "categories": cats, "pages": len(pages),
            "requests": requests_made, "collected": datetime.now(timezone.utc).isoformat(), "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("pages", "requests", "sha256")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
