# fetch_sources.py : 개념 1개 → 근거 문장 최대 3개 + 출처 URL
# 원칙: 캐시 먼저 → 무료·키 없는 위키백과 → (선택) 셀프호스팅 SearXNG 스니펫 → 그래도 부족할 때만 본문 1개 추출
# 무거운 크롤링·WebSocket 없이 HTTP GET 몇 번으로 끝낸다. 결과는 SQLite에 30일 캐시.
import json, re, sqlite3, time, urllib.parse, urllib.request

UA = "concept-chart/0.1 (personal study tool)"
TTL = 30 * 86400
MAX_SENT, MAX_CHARS = 3, 600
DEF_END = re.compile(r"(것|방법|기법|현상|과정|구조|모델|알고리즘|지표|단위|함수|값|메커니즘|플랫폼|방식|표현|비율|신경망|기술|도구)[을를]?\s*(말한다|뜻한다|가리킨다|의미한다|이다|다)[.]?\s*$")
DEF_MID = re.compile(r"(이란|란 |의 약자|라고 부르|을 말한다|를 말한다|을 뜻한다|를 뜻한다)")
SKIP = re.compile(r"(했다|했더니|봤다|만들었|이번|우리|가장|요즘|면접|려면|해야)")
_last = {}


def _get(url, timeout=6, max_bytes=400_000):
    host = urllib.parse.urlparse(url).netloc
    wait = 1.0 - (time.time() - _last.get(host, 0))      # 같은 사이트는 1초에 1번
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(max_bytes).decode("utf-8", errors="replace")


def open_cache(path="concept_cache.sqlite"):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS src_cache (k TEXT PRIMARY KEY, v TEXT, t REAL)")
    return con


def cached(con, key, fn):
    row = con.execute("SELECT v, t FROM src_cache WHERE k=?", (key,)).fetchone()
    if row and time.time() - row[1] < TTL:
        return json.loads(row[0])
    v = fn()
    con.execute("REPLACE INTO src_cache VALUES (?,?,?)", (key, json.dumps(v, ensure_ascii=False), time.time()))
    con.commit()
    return v


def wikipedia(term, lang="ko"):
    q = urllib.parse.quote(term)
    hits = json.loads(_get(f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={q}&limit=1&namespace=0&format=json"))
    if not hits[1]:
        return []
    title = urllib.parse.quote(hits[1][0].replace(" ", "_"))
    j = json.loads(_get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"))
    url = j.get("content_urls", {}).get("desktop", {}).get("page") or hits[3][0]
    return [{"url": url, "text": j.get("extract", ""), "src": "wikipedia"}] if j.get("extract") else []


def searxng(term, base="http://localhost:8888", n=3):
    q = urllib.parse.quote(term + " 뜻")
    j = json.loads(_get(f"{base}/search?q={q}&format=json&language=ko"))
    return [{"url": r["url"], "text": r.get("content", ""), "src": "searxng"} for r in j.get("results", [])[:n] if r.get("content")]


def page_text(url):
    import trafilatura                                    # 필요할 때만 불러온다
    return trafilatura.extract(_get(url)) or ""


def split_sents(text):
    return [s.strip() for s in re.split(r"(?<=[.!?다요])\s+", text or "") if len(s.strip()) > 10]


def pick(term, aliases, sources):
    """정의문 패턴으로 근거 문장을 골라 예산(3문장, 600자) 안에서 반환"""
    keys = [k.lower() for k in [term] + list(aliases)]
    cand = []
    for i, src in enumerate(sources):
        for j, s in enumerate(split_sents(src["text"])):
            low = s.lower()
            if not any(k in low for k in keys):
                continue
            sc = 2 * bool(DEF_END.search(s)) + 2 * bool(DEF_MID.search(s)) + any(low.startswith(k) for k in keys) - 2 * bool(SKIP.search(s)) - 0.1 * j
            if sc >= 0:                                    # 경험담·조언 위주 문장은 근거에서 뺀다
                cand.append((sc, i, s))
    cand.sort(key=lambda x: -x[0])
    out, used = [], 0
    for sc, i, s in cand:
        if len(out) == MAX_SENT or used + len(s) > MAX_CHARS:
            break
        out.append({"text": s, "url": sources[i]["url"], "score": round(sc, 2)})
        used += len(s)
    return out


def fetch_evidence(con, term, aliases=(), searx_base=None):
    def build():
        layers, srcs = [], []
        for name, fn in [("wikipedia", lambda: wikipedia(term))] + \
                        ([("searxng", lambda: searxng(term, searx_base))] if searx_base else []):
            try:
                got = fn()
            except Exception:
                got = []
            srcs += got
            layers.append(name)
            if len(pick(term, aliases, srcs)) >= 2:       # 근거 2문장 이상이면 더 가져오지 않는다
                break
        if len(pick(term, aliases, srcs)) < 2:
            for s in [x for x in srcs if x["src"] == "searxng"][:1]:   # 마지막 수단: 본문 1개만
                try:
                    srcs.append({"url": s["url"], "text": page_text(s["url"]), "src": "page"})
                    layers.append("page")
                except Exception:
                    pass
        return {"term": term, "evidence": pick(term, aliases, srcs), "layers": layers}
    return cached(con, "ev:" + term, build)
