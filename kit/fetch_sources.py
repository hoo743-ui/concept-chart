# fetch_sources.py : 개념 1개 → 근거 문장 최대 3개 + 출처 URL
# 원칙: 캐시 먼저 → 무료·키 없는 위키백과 → (선택) 셀프호스팅 SearXNG 스니펫 → 그래도 부족할 때만 본문 1개 추출
# 무거운 크롤링·WebSocket 없이 HTTP GET 몇 번으로 끝낸다. 결과는 SQLite에 30일 캐시.
import json, re, sqlite3, time, urllib.error, urllib.parse, urllib.request

UA = "concept-chart/0.1 (personal study tool)"
MIN_GAP = 1.5                                             # 같은 사이트 호출 간격 (초). 1초 간격은 위키백과가 429로 막는 것을 확인했다
MAX_RETRY_WAIT = 60
TTL = 30 * 86400
MAX_SENT, MAX_CHARS = 3, 600
DEF_END = re.compile(r"(것|방법|기법|현상|과정|구조|모델|알고리즘|지표|단위|함수|값|메커니즘|플랫폼|방식|표현|비율|신경망|기술|도구)[을를]?\s*(말한다|뜻한다|가리킨다|의미한다|이다|다)[.]?\s*$")
DEF_MID = re.compile(r"(이란|란 |의 약자|라고 부르|을 말한다|를 말한다|을 뜻한다|를 뜻한다)")
SKIP = re.compile(r"(했다|했더니|봤다|만들었|이번|우리|가장|요즘|면접|려면|해야)")
_last = {}


def _get(url, timeout=6, max_bytes=400_000):
    host = urllib.parse.urlparse(url).netloc
    for retry in (True, False):
        wait = MIN_GAP - (time.time() - _last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(max_bytes).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code != 429 or not retry:
                raise
            after = str(e.headers.get("Retry-After") or "")      # 너무 많이 불렀다: 사이트가 말한 만큼 쉬고 한 번만 다시 시도한다
            time.sleep(min(int(after) if after.isdigit() else 30, MAX_RETRY_WAIT))


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
    if j.get("type") == "disambiguation":                 # 동음이의 안내 문서는 정의가 아니다
        return []
    url = j.get("content_urls", {}).get("desktop", {}).get("page") or hits[3][0]
    return [{"url": url, "text": j.get("extract", ""), "src": "wikipedia", "title": j.get("title", hits[1][0])}] if j.get("extract") else []


TECH_PAREN = re.compile(r"\((?:[^()]*(?:컴퓨팅|컴퓨터|소프트웨어|프로그래밍|프로그램|버전 관리|기계 학습|통계학|운영 체제|데이터베이스|네트워크|인터넷|웹|자료 구조|가상화|인공지능|computing|software|programming|computer|version control|machine learning|statistics|operating system|database|network|virtualization)[^()]*)\)\s*$", re.I)


def subject_ok(term, text):
    """문장의 첫 언급이 다른 낱말에 붙은 꼴이면 거절: '이동 기준선 은 …'은 기준선의 설명이 아니다.
    앞 낱말이 '에서·의·에' 같은 토씨로 끝나면 받는다 ('버전 관리 시스템에서 커밋은 …'). 한글 낱말만 본다."""
    if not re.search(r"[가-힣]", term):
        return True
    m = re.search(re.escape(term).replace(r"\ ", r"\s*"), text or "")
    if not m:
        return True                                       # 다른 표기로 쓰인 문장은 여기서 판단하지 않는다
    before = re.search(r"([가-힣]+)(\s*)$", text[:m.start()])
    return not before or bool(re.search(r"(에서|에게|에는|에|의|로|으로|은|는|이|가|을|를|와|과)$", before.group(1)))


def wikipedia_tech(term, lang="ko"):
    """제목에 분야가 괄호로 붙은 문서: 커밋 → 커밋 (버전 관리). 괄호 앞이 낱말과 같고 괄호가 기술 분야일 때만 받는다.
    낚시·기관처럼 다른 뜻의 문서를 받지 않으려고 다른 제목은 모두 버린다."""
    key = re.sub(r"[\s\-_/]+", "", term.lower())
    q = urllib.parse.quote(term)
    hits = json.loads(_get(f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={q}&limit=8&namespace=0&format=json"))
    for title in hits[1]:
        m = TECH_PAREN.search(title)
        if not m or re.sub(r"[\s\-_/]+", "", title[:m.start()].lower()) != key:
            continue
        j = json.loads(_get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'))}"))
        if j.get("type") != "disambiguation" and j.get("extract"):
            url = j.get("content_urls", {}).get("desktop", {}).get("page", "")
            return [{"url": url, "text": j["extract"], "src": "wikipedia", "title": title}]
    return []


def wikipedia_exact(term, lang="ko"):
    """이름과 정확히 같은 문서 또는 위키백과 편집자가 만든 넘겨주기(GPU → 그래픽 처리 장치). 검색이 아니라서 비슷한 제목이 끌려오지 않는다"""
    try:
        j = json.loads(_get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(term.replace(' ', '_'), safe='')}"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    if j.get("type") == "disambiguation" or not j.get("extract"):
        return []
    return [{"url": j.get("content_urls", {}).get("desktop", {}).get("page", ""), "text": j["extract"], "src": "wikipedia", "title": j.get("title", term)}]


def korean_version(en_title):
    """영어 문서와 언어 연결된 한국어 문서의 제목 (Git → 깃 (소프트웨어)). 없으면 None"""
    q = urllib.parse.quote(en_title)
    j = json.loads(_get(f"https://en.wikipedia.org/w/api.php?action=query&prop=langlinks&lllang=ko&redirects=1&format=json&titles={q}"))
    for page in j.get("query", {}).get("pages", {}).values():
        for link in page.get("langlinks", []):
            return link.get("*")
    return None


NOT_DEFINITION = re.compile(r"(다음을 가리킨다|다음과 같은 뜻|may refer to|can refer to)")


def lead_sents(src):
    """위키백과 문서의 맨 앞 문장들을 순서 그대로. 문서 첫 문장이 곧 정의문이다.
    낱말이 든 문장만 고르면 '그래픽 처리 장치는 …'이 버려지고 'GPU는 점점 더 많이 쓰인다'가 남는다"""
    sents = split_sents(src["text"])
    if not sents or NOT_DEFINITION.search(sents[0]):
        return []
    out, used = [], 0
    for s in sents[:MAX_SENT]:
        if used + len(s) > MAX_CHARS and out:
            break
        out.append({"text": s, "url": src["url"]})
        used += len(s)
    return out


def wikipedia_lead(term):
    """개념 이름 → 정의 문장들. 기술 문서를 먼저 본다: 함수 → 함수 (컴퓨터 과학)가 있으면 수학의 함수보다 앞선다.
    영어 문서만 맞으면 언어 연결로 한국어 문서를 찾아 쓴다. 찾지 못하면 빈 목록 (검색 단계로 넘어간다)"""
    for src in wikipedia_tech(term, "ko") or wikipedia_exact(term, "ko"):
        got = lead_sents(src)
        if got:
            return got
    for src in wikipedia_tech(term, "en") or wikipedia_exact(term, "en"):
        ko_title = korean_version(src["title"])
        for ko in wikipedia_exact(ko_title, "ko") if ko_title else []:
            got = lead_sents(ko)
            if got:
                return got
        got = lead_sents(src)
        if got:
            return got
    return []


def searxng(term, base="http://localhost:8888", n=3, context=()):
    """context: 뜻을 가르려고 검색어에 함께 넣는 개념 이름 (torch → torch GPU 뜻)"""
    q = urllib.parse.quote(" ".join([term, *context, "뜻"]))
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


def _term_pattern(term):
    """띄어쓰기만 다른 표기도 같게 본다 (조기종료 = 조기 종료)"""
    return r"\s*".join(re.escape(ch) for ch in re.sub(r"\s+", "", term))


LEAD_QUESTION = re.compile(r"^[^.?!]{1,40}\?\s*")                  # "KeyError란?KeyError는 …"의 앞부분
ENDS_DONE = re.compile(r"(다|요)[.]?$")
NOT_DONE = re.compile(r"(\.\.\.|…|\?)")
NEEDS_CONTEXT = re.compile(r"(위와 같이|이처럼|앞서|다음과 같|이 글|이번 글)")


def definition_sents(term, aliases, sources, limit=MAX_SENT, context=()):
    """검색 결과처럼 문장 품질을 믿기 어려운 출처용: '개념 + 은/는/이란'으로 시작하는 완결된 문장만 고른다.
    context가 있으면 그 낱말이 하나라도 들어 있는 검색 결과만 쓴다 (캐시 → 현금 같은 다른 뜻을 거른다).
    맞는 문장이 없으면 빈 목록 (틀린 정의보다 '근거 없음'이 낫다)"""
    ctx = [c.lower() for c in context if c.strip()]
    names = "|".join(_term_pattern(k) for k in sorted({term, *aliases}, key=len, reverse=True) if k.strip())
    head = re.compile(rf"^(?:[^,.?!]{{0,20}}에서\s+)?(?:{names})(?:\s*\([^()]*\))?\s*(?:은|는|이란|란|이라 함은|라 함은)\s", re.I)
    out, seen = [], set()
    for src in sources:
        low = src.get("text", "").lower()
        if ctx and not any(c in low for c in ctx):
            continue
        for s in split_sents(src.get("text", "")):
            s = LEAD_QUESTION.sub("", re.sub(r"\s+", " ", s)).strip()
            if s in seen or not 15 <= len(s) <= 200:
                continue
            if head.search(s) and ENDS_DONE.search(s) and not NOT_DONE.search(s) \
                    and not NEEDS_CONTEXT.search(s) and not SKIP.search(s):
                seen.add(s)
                out.append({"text": s, "url": src["url"]})
    return out[:limit]


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
