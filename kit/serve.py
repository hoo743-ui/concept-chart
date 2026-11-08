# -*- coding: utf-8 -*-
"""serve.py : 개념 차트 로컬 서버 (표준 라이브러리 + kiwipiepy, 정의 수집만 같은 폴더의 fetch_sources.py를 쓴다)

    python kit/serve.py                      # http://localhost:8765
    python kit/serve.py --port 8765 --inbox ~/.claude/concept-inbox.jsonl --db ~/.claude/concept-chart.sqlite
    python kit/serve.py --once               # 인박스를 한 번만 읽어 색인하고 끝 (점검용)
    python kit/serve.py --rebuild            # 색인을 지우고 인박스 처음부터 다시

인박스를 1초마다 이어 읽기 → SQLite 색인 → API
    GET /api/leaderboard?k=10      중요도 순위 (제안 C: 세션 빈도 반감기 7일 × 세션 IDF)
    GET /api/concept/{id}?cursor=  클릭 카드 (정의·출처·관련 개념 3개·기록 3개, LLM 없음).
                                   정의가 없으면 뒤에서 위키백과를 찾아 notes에 저장 (30일 유효)
    GET /api/events                새 기록을 색인하거나 정의를 저장하면 'update' 이벤트 (SSE)
    GET /api/status                인박스 위치·읽은 위치·세션·턴 수
    GET /                          --web 폴더의 index.html, 없으면 내장 간이 화면

- 개념 = Kiwi 명사(붙어 쓴 명사·접미사는 한 덩어리, 영문·한자 포함, 2글자 이상) + 코드 속 라이브러리·에러 이름.
  개념 사전은 쓰지 않는다. IDF 배경은 내 세션들(세션 1개 = 문서 1개).
- 기본으로 AI 답변(assistant·subagent)만 분석한다 (--roles로 변경). 질문은 분석하지 않고 원문을 저장해 뒤따르는 답변의 개념과 연결한다.
- Kiwi는 자식 프로세스(--worker)에만 올리고, 10분간 새 기록이 없으면 끝낸다. 서버 본체는 Kiwi를 불러오지 않는다.
- 127.0.0.1에만 열고 CORS 헤더를 붙이지 않는다 (다른 사이트가 내 대화 개념을 읽지 못하게).
- 색인 DB는 인박스에서 언제든 다시 만들 수 있다. git에 올리지 않는다.
"""
import argparse
import json
import math
import os
import pathlib
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_INBOX = os.environ.get("CONCEPT_INBOX") or "~/.claude/concept-inbox.jsonl"
DEFAULT_DB = "~/.claude/concept-chart.sqlite"
HALF_LIFE_DAYS = 7.0           # 제안 C(안정성 균형): H=7, β=0, γ=0, 단위=세션
BADGE_Z, BADGE_MIN_SESS = 1.64, 2
SNIPPET = 160
NOTE_TTL = 30 * 86400          # 정의 유효 기간 (fetch_sources.py 캐시와 같은 30일)
NOTE_RETRY = 60                # 수집 실패 후 다시 시도하기까지 (초)
NOTE_LANGS = ("ko", "en")      # 한국어 위키백과에 근거가 없을 때만 영어
DEFAULT_SEARX = "http://localhost:8888"   # python dev.py searx up
SUMMARY_MAX = 90               # 화면 한 줄 길이 (글자)
SEARCH_RESULTS = 8             # 정의 문장을 고를 검색 결과 수
QUESTION_MAX = 200             # 카드에 보여 줄 질문 길이 (글자). 원문은 DB에 그대로 있다
WORKER_IDLE = 600              # 새 답변이 이만큼(초) 없으면 분석 프로세스를 끝내 메모리를 돌려준다
WORKER_BACKOFF = 30            # 분석 프로세스가 실패하면 다시 시도하기까지 (초)
LB_TTL = 60                    # 새 기록이 없어도 순위를 다시 계산하는 주기 (초, 경과일 반영)

# ---------------- 정제 (kit/loader_cell.py와 같은 규칙) ----------------
FENCE  = re.compile(r"```[^\n]*\n(.*?)```", re.S)
INLINE = re.compile(r"`([^`\n]+)`")
URL    = re.compile(r"https?://\S+")
PATH   = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-]+){2,}")
IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))", re.M)
PKG    = r"[A-Za-z0-9_.\-\[\]=<>]+"
PIP    = re.compile(rf"pip3?\s+install\s+((?:{PKG}[ \t]*)+)")
ERR    = re.compile(r"\b([A-Z][A-Za-z]+(?:Error|Exception))\b")
SENT   = re.compile(r"(?<=[.!?。])\s+|\n+")
# 어느 대화에나 나오는 일반 명사 (IDF로도 낮아지지만 처음 몇 세션은 IDF가 약해서 미리 뺀다)
STOP = set("""것 수 때 등 경우 부분 정도 이번 다음 하나 방법 내용 문제 결과 설명 확인 필요 기준 이유 상태 시간 처리 생각
정리 진행 실행 추가 변경 수정 사용 위치 방식 단계 지금 아래 위 앞 뒤 전 후 중 안 밖 쪽 줄 개 번 거 게 데 뭐 이것 그것
여기 거기 하나 두 세 모두 전체 각 기본 대부분 직접 바로 그대로 정상 가능 예 예시 참고 요청 답 질문 말 글 경우 이상 이하""".split())
STOP_EN = {"the", "and", "for", "you", "this", "that", "with", "not", "are", "ok", "is", "it", "to", "of", "in", "on",
           "kb", "mb", "gb", "tb", "ms", "mhz", "ghz", "px", "fps"}     # 뒤쪽: 단위
STOP_LOWER = {"http", "https", "www"}   # 주소 조각. 소문자만 뺀다 (대문자 HTTP·HTTPS는 개념일 수 있음)

_kiwi = None


def get_kiwi():
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


def norm_key(s):
    return re.sub(r"[\s\-_/]+", "", s.lower())


def number_fragment(t, toks, i):
    """숫자에 붙어 잘린 영문 조각인지: 8GB의 GB, 2FA의 FA(숫자 바로 뒤), cu121의 cu, py3의 py(소문자 1~2글자 + 숫자).
    GPT4의 GPT, Python3의 Python은 이름이라 남긴다."""
    if t.tag != "SL":
        return False
    prev = toks[i - 1] if i else None
    nxt = toks[i + 1] if i + 1 < len(toks) else None
    if prev is not None and prev.tag == "SN" and prev.start + prev.len == t.start:
        return True
    return (nxt is not None and nxt.tag == "SN" and t.start + t.len == nxt.start
            and len(t.form) <= 2 and t.form.islower())


def noun_groups(s):
    """붙어 있는 명사(+명사 파생 접미사 XSN)는 한 덩어리로: 가중+치 → 가중치, 시각+화 → 시각화. 영문·한자는 그대로"""
    out, cur, end = [], "", -1
    toks = get_kiwi().tokenize(s)
    for i, t in enumerate(toks):
        glued = bool(cur) and t.start == end
        if t.tag in ("NNG", "NNP") or (t.tag == "XSN" and glued):
            if glued:
                cur += t.form
            else:
                if cur:
                    out.append(cur)
                cur = t.form
        else:
            if cur:
                out.append(cur)
                cur = ""
            if t.tag in ("SL", "SH") and not number_fragment(t, toks, i):
                out.append(t.form)
        end = t.start + t.len
    if cur:
        out.append(cur)
    return out


def extract(text):
    """본문 → [(문장, {개념 키: 표기})] (코드 용어는 첫 문장 자리에 붙인다)"""
    code = "\n".join(FENCE.findall(text))
    prose = FENCE.sub(" ", text)
    inline = INLINE.findall(prose)
    prose = PATH.sub(" ", URL.sub(" ", INLINE.sub(" ", prose)))
    both = code + "\n" + "\n".join(inline) + "\n" + text
    code_terms = {(a or b).split(".")[0] for a, b in IMPORT.findall(code)}
    code_terms |= {re.split(r"[=<>\[]", p)[0] for m in PIP.findall(both) for p in m.split() if not p.startswith("-")}
    code_terms |= set(ERR.findall(both))
    out = []
    for s in SENT.split(prose):
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) < 4:
            continue
        cs = {}
        for f in noun_groups(s):
            if len(f) >= 2 and f not in STOP and f not in STOP_LOWER and f.lower() not in STOP_EN:
                cs.setdefault(norm_key(f), f)
        if cs:
            out.append((s, cs))
    code_cs = {norm_key(c): c for c in code_terms if len(c) >= 2 and c.lower() not in STOP_EN}
    if code_cs:
        snip = out[0][0] if out else re.sub(r"\s+", " ", prose).strip() or "(코드)"
        out.append((snip, code_cs))
    return out


# ---------------- 저장소 ----------------
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS mentions (concept TEXT, ts TEXT, session TEXT, role TEXT, snippet TEXT, question INTEGER);
CREATE INDEX IF NOT EXISTS ix_m ON mentions (concept, ts DESC);
CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, session TEXT, ts TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS ix_q ON questions (session, id);
CREATE TABLE IF NOT EXISTS cooc (a TEXT, b TEXT, n INTEGER, PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS freq (concept TEXT PRIMARY KEY, n INTEGER);
CREATE TABLE IF NOT EXISTS notes (concept TEXT PRIMARY KEY, definition TEXT, sources TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS forms (concept TEXT, form TEXT, n INTEGER, PRIMARY KEY (concept, form));
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, last_ts REAL);
CREATE TABLE IF NOT EXISTS term_sess (concept TEXT, session TEXT, PRIMARY KEY (concept, session));
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""
SCHEMA_VERSION = 3             # 색인 표 구조나 개념 추출 규칙이 바뀌면 올린다. 다르면 색인을 지우고 인박스에서 다시 만든다 (notes는 남김)
DERIVED = ("mentions", "questions", "cooc", "freq", "forms", "sessions", "term_sess", "meta")   # notes(웹 근거)는 남긴다


def open_db(path):
    p = pathlib.Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=10, check_same_thread=False)
    con.execute("PRAGMA synchronous=NORMAL")      # 줄마다 커밋해도 느리지 않게 (색인은 인박스에서 다시 만들 수 있다)
    if con.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:   # 같으면 쓰지 않는다: 색인이 쓰는 동안 조회가 막히지 않게
        for t in DERIVED:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.commit()
        con.executescript(SCHEMA)
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        con.commit()
    return con


def meta_get(con, k, default=None):
    r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def meta_set(con, k, v):
    con.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def reset(con):
    for t in DERIVED:
        con.execute(f"DELETE FROM {t}")
    con.commit()


def parse_ts(ts):
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except (ValueError, TypeError):
        return None


def index_record(con, r, roles):
    if not r.get("text"):
        return False
    t = parse_ts(r.get("ts")) or time.time()
    ts = datetime.fromtimestamp(t, timezone.utc).isoformat()
    sess = r.get("session_id") or "day:" + ts[:10]
    if r.get("role") == "user":                           # 질문은 분석하지 않고 원문 그대로 저장 → 뒤따르는 답변의 개념과 연결
        con.execute("INSERT INTO questions (session, ts, text) VALUES (?,?,?)", (sess, ts, r["text"]))
    if r.get("role") not in roles:
        return False
    sc = extract(r["text"])
    if not sc:
        return False
    q = con.execute("SELECT MAX(id) FROM questions WHERE session=?", (sess,)).fetchone()[0]
    seen = set()
    for s, cs in sc:
        for k, form in cs.items():
            if k not in seen:                             # 답변 하나에 개념 1행 (처음 나온 문장만). 순위는 freq·term_sess로 계산해 영향 없음
                con.execute("INSERT INTO mentions VALUES (?,?,?,?,?,?)", (k, ts, sess, r["role"], s[:SNIPPET], q))
            con.execute("INSERT INTO forms VALUES (?,?,1) ON CONFLICT(concept, form) DO UPDATE SET n=n+1", (k, form))
        seen |= set(cs)
    con.execute("INSERT INTO sessions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET last_ts=max(last_ts, excluded.last_ts)",
                (sess, t))
    for c in seen:
        con.execute("INSERT INTO freq VALUES (?,1) ON CONFLICT(concept) DO UPDATE SET n=n+1", (c,))
        con.execute("INSERT OR IGNORE INTO term_sess VALUES (?,?)", (c, sess))
        for d in seen:
            if c != d:
                con.execute("INSERT INTO cooc VALUES (?,?,1) ON CONFLICT(a,b) DO UPDATE SET n=n+1", (c, d))
    return True


def ingest(con, inbox, roles):
    """인박스에서 아직 안 읽은 완성된 줄만 색인한다. 파일이 줄었으면(새로 만듦) 처음부터 다시. → 새로 색인한 턴 수"""
    p = pathlib.Path(inbox).expanduser()
    if not p.exists():
        return 0
    size = p.stat().st_size
    off = int(meta_get(con, "offset", 0))
    if size < off:
        reset(con)
        off = 0
    if size == off:
        return 0
    with open(p, "rb") as f:
        f.seek(off)
        chunk = f.read(size - off)
    end = chunk.rfind(b"\n")
    if end < 0:                                   # 아직 쓰는 중인 줄만 있음
        return 0
    n, pos = 0, off
    for line in chunk[:end].split(b"\n"):
        pos += len(line) + 1
        try:
            r = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            r = None
        try:                                      # 줄마다 커밋: 쓰기 잠금을 짧게 쥐어 정의 저장·조회를 막지 않는다
            if isinstance(r, dict) and index_record(con, r, roles):
                n += 1
                meta_set(con, "turns", int(meta_get(con, "turns", 0)) + 1)
            meta_set(con, "offset", pos)
            con.commit()
        except Exception:
            con.rollback()
            raise
    return n


# ---------------- 조회 ----------------
def label_of(con, k):
    r = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (k,)).fetchone()
    return r[0] if r else k


def two_prop_z(x1, n1, x0, n0):
    if not (n1 and n0):
        return 0.0
    p = (x1 + x0) / (n1 + n0)
    if not 0 < p < 1:
        return 0.0
    return (x1 / n1 - x0 / n0) / math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))


def leaderboard(con, k=10, now=None):
    """점수 = log1p(Σ 개념이 나온 세션의 2^(-경과일/7)) × (log((N+1)/(df+1)) + 1)"""
    now = time.time() if now is None else now
    sess = dict(con.execute("SELECT id, last_ts FROM sessions"))
    N = len(sess)
    age = {s: max(0.0, (now - t) / 86400) for s, t in sess.items()}
    rec = [s for s, a in age.items() if a < 14]
    pri = [s for s, a in age.items() if 14 <= a < 42]
    by = {}
    for c, s in con.execute("SELECT concept, session FROM term_sess"):
        by.setdefault(c, []).append(s)
    items = []
    for c, ss in by.items():
        dsf = sum(2.0 ** (-age[s] / HALF_LIFE_DAYS) for s in ss if s in age)
        idf = math.log((N + 1) / (len(ss) + 1)) + 1
        x1 = sum(1 for s in ss if s in rec and s in age)
        x0 = sum(1 for s in ss if s in pri and s in age)
        z = two_prop_z(x1, len(rec), x0, len(pri))
        badge = "up" if z > BADGE_Z and x1 >= BADGE_MIN_SESS else "down" if z < -BADGE_Z and x0 >= BADGE_MIN_SESS else ""
        items.append((math.log1p(dsf) * idf, c, len(ss), badge, max(sess[s] for s in ss if s in sess)))
    items.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for i, (score, c, nsess, badge, last) in enumerate(items[:k], 1):
        m = con.execute("SELECT n FROM freq WHERE concept=?", (c,)).fetchone()
        out.append({"rank": i, "id": c, "label": label_of(con, c), "score": round(score, 4), "sessions": nsess,
                    "turns": m[0] if m else 0, "badge": badge,
                    "last_seen": datetime.fromtimestamp(last, timezone.utc).isoformat()})
    return {"generated": datetime.fromtimestamp(now, timezone.utc).isoformat(), "n_sessions": N,
            "n_concepts": len(by), "items": out}


def context_terms(con, concept, k=2):
    """뜻을 가를 검색어: 내 대화에서 이 개념과 가장 자주 함께 나온 개념 이름"""
    rows = con.execute("SELECT b FROM cooc WHERE a=? ORDER BY n DESC, b LIMIT ?", (concept, k)).fetchall()
    return [label_of(con, r[0]) for r in rows]


def fetch_note(term, aliases=(), searx=None, context=()):
    """개념 이름 → (정의 문장, [{text, url}]). 위키백과(ko → en) → 그래도 없으면 SearXNG (함께 나온 개념을 붙여서 → 없으면 이름만).
    근거가 없으면 ("", []), 네트워크 오류·SearXNG 꺼짐은 예외로 올린다 (저장하지 않고 나중에 다시 시도).
    출처 문장을 그대로 쓴다 (LLM이 만든 문장 없음). 밖으로 나가는 건 개념 이름뿐."""
    import fetch_sources as fs                            # 클릭할 때만 필요

    def result(ev):
        ev = [e for e in ev if str(e["url"]).startswith(("http://", "https://"))]   # 외부에서 온 링크: 화면에 넣기 전에 거른다
        return (ev[0]["text"], [{"text": e["text"], "url": e["url"]} for e in ev]) if ev else None
    for lang in NOTE_LANGS:
        srcs = fs.wikipedia(term, lang)
        # 띄어쓰기만 다른 문서 제목(파인튜닝 → 파인 튜닝)은 같은 개념의 표기로 본다. 다른 제목은 받지 않는다 (AP → AP 통신)
        titles = [s["title"] for s in srcs if norm_key(s.get("title", "")) == norm_key(term)]
        got = result(fs.pick(term, list(aliases) + titles, srcs))
        if got:
            return got
    if searx:
        context = list(context)
        for ctx in ([context, context[:1], []] if len(context) > 1 else [context, []] if context else [[]]):
            srcs = fs.searxng(term, searx, n=SEARCH_RESULTS, context=ctx)
            got = result(fs.definition_sents(term, aliases, srcs, context=context))
            if got:
                return got
    return "", []


def one_line(text, limit=SUMMARY_MAX):
    """출처 문장 → 화면용 한 줄: 괄호 설명을 걷어 내고 첫 줄만, 길면 낱말 경계에서 자른다. 새 낱말을 만들지 않는다 (LLM 없음)"""
    if not text:
        return None
    first = text.strip().split("\n")[0].strip()
    s = first
    for _ in range(3):                                    # 괄호 안 괄호까지
        s = re.sub(r"\s*(\([^()]*\)|\[[^\[\]]*\])", "", s)
    s = re.sub(r"\s+", " ", s).strip() or first
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0] or s[:limit]
    return cut.rstrip(" ,·") + "…"


def save_note(con, concept, definition, sources):
    con.execute("REPLACE INTO notes VALUES (?,?,?,?)",
                (concept, definition, json.dumps(sources, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    con.commit()


def chat_line(con, concept):
    """정의를 못 찾았을 때 보여 줄 내 대화 속 문장. 개념 이름이 실제로 든 문장만 (코드에서만 나온 개념은 없음).
    '개념 + 은/는/이란'으로 시작하는 설명 문장을 먼저, 그다음 최근 문장"""
    forms = [re.sub(r"\s+", "", r[0]).lower() for r in con.execute("SELECT form FROM forms WHERE concept=?", (concept,))]
    rows = con.execute("""SELECT m.ts, m.snippet, substr(qs.text, 1, ?) FROM mentions m LEFT JOIN questions qs ON qs.id = m.question
                          WHERE m.concept=? ORDER BY m.ts DESC, m.rowid DESC LIMIT 20""", (QUESTION_MAX, concept)).fetchall()
    best = None
    for ts, snippet, question in rows:
        flat = re.sub(r"\s+", "", snippet).lower()
        if any(flat.startswith((f + "은", f + "는", f + "이란", f + "란")) for f in forms):
            best = (ts, snippet, question)
            break
        if best is None and any(f in flat for f in forms):
            best = (ts, snippet, question)
    return {"ts": best[0], "text": one_line(best[1]), "question": best[2]} if best else None


def concept_card(con, concept, cursor=None, k=3):
    """클릭 응답 (kit/concept_store.py와 같은 형식 + label): LLM 호출 없이. 근거 문장까지 채워지면 최대 약 4KB"""
    note = con.execute("SELECT definition, sources FROM notes WHERE concept=?", (concept,)).fetchone()
    related = con.execute(
        """SELECT b, c.n * 1.0 / ((SELECT n FROM freq WHERE concept=?) * (SELECT n FROM freq WHERE concept=b)) AS s
           FROM cooc c WHERE a=? ORDER BY s DESC, c.n DESC, b LIMIT ?""", (concept, concept, k)).fetchall()
    q = """SELECT m.ts, m.role, m.snippet, m.rowid, substr(qs.text, 1, ?) FROM mentions m
           LEFT JOIN questions qs ON qs.id = m.question WHERE m.concept=?"""
    args = [QUESTION_MAX, concept]
    if cursor:
        ts, rid = cursor.rsplit("|", 1)
        q += " AND (m.ts < ? OR (m.ts = ? AND m.rowid < ?))"
        args += [ts, ts, int(rid)]
    rows = con.execute(q + " ORDER BY m.ts DESC, m.rowid DESC LIMIT ?", args + [k]).fetchall()
    return {"concept": concept, "label": label_of(con, concept),
            "summary": one_line(note[0]) if note else None,
            "definition": (note[0] or None) if note else None,
            "chat_line": None if note and note[0] else chat_line(con, concept),
            "sources": json.loads(note[1]) if note and note[1] and note[1][:1] in "[{" else [],
            "related": [{"id": r[0], "label": label_of(con, r[0])} for r in related],
            "records": [{"ts": r[0], "role": r[1], "snippet": r[2], "question": r[4]} for r in rows],
            "next_cursor": "%s|%d" % (rows[-1][0], rows[-1][3]) if len(rows) == k else None}


# ---------------- 서버 ----------------
PAGE = """<!doctype html><meta charset="utf-8"><title>개념 차트</title>
<style>body{font:15px/1.5 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}
li{cursor:pointer;margin:.3rem 0}small{color:#777}#card{border-top:1px solid #ddd;margin-top:1rem;padding-top:.5rem}</style>
<h1>개념 차트 <small id="st"></small></h1><ol id="lb"></ol><div id="card"></div>
<script>
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function lb(){const d=await (await fetch('/api/leaderboard?k=10')).json();
 $('#st').textContent=`세션 ${d.n_sessions} · 개념 ${d.n_concepts}`;
 $('#lb').innerHTML=d.items.map(x=>`<li data-id="${esc(x.id)}"><b>${esc(x.label)}</b> ${x.badge=='up'?'▲':x.badge=='down'?'▼':''} <small>${x.score} · ${x.sessions}세션</small></li>`).join('')||'<small>아직 기록이 없어요. Claude Code를 쓰면 여기에 쌓여요.</small>';}
let cur=null,open=false;const NOTE={pending:'정의를 찾는 중이에요…',none:'위키백과와 검색에서 근거를 찾지 못했어요.',failed:'정의를 가져오지 못했어요. 인터넷이나 SearXNG(python dev.py searx up)를 확인해 주세요.'};
async function card(){if(!cur)return;
 const c=await (await fetch('/api/concept/'+encodeURIComponent(cur))).json();
 const more=open?`<ol>${c.sources.map(s=>`<li style="cursor:auto">${esc(s.text)} <a href="${esc(s.url)}" target="_blank" rel="noopener">출처</a></li>`).join('')}</ol>
 <p>관련: ${c.related.map(r=>esc(r.label)).join(', ')||'-'}</p><ul>${c.records.map(r=>`<li style="cursor:auto"><small>${esc(r.ts.slice(0,16))}</small> ${r.question?`<b>내 질문:</b> ${esc(r.question)}<br>`:''}${esc(r.snippet)}</li>`).join('')}</ul>`:'';
 const chat=!c.summary&&c.note_status!=='pending'&&c.chat_line;
 const line=chat?`<small>내 대화에서 (출처 확인 전)</small><br>${esc(c.chat_line.text)}`:esc(c.summary||NOTE[c.note_status]||'');
 $('#card').innerHTML=`<h2>${esc(c.label)}</h2><p>${line}</p>
 <button type="button" id="more" aria-expanded="${open}">${open?'접기':'더 알아보기'}</button>${more}`;}
$('#lb').onclick=e=>{const li=e.target.closest('li');if(!li)return;cur=li.dataset.id;open=false;card();};
$('#card').onclick=e=>{if(e.target.id==='more'){open=!open;card();}};
lb(); new EventSource('/api/events').addEventListener('update',()=>{lb();card();});
</script>"""


class State:
    def __init__(self, db, inbox, roles, web):
        self.db, self.inbox, self.roles, self.web = db, inbox, roles, web
        self.version = 0
        self.cond = threading.Condition()
        self.stop = threading.Event()
        self.note_q = queue.Queue()
        self.note_lock = threading.Lock()
        self.note_pending = set()
        self.note_failed = {}      # 개념 → 실패 시각 (NOTE_RETRY 동안 다시 시도하지 않음)
        self.note_error = None     # 마지막 수집 오류 (진단용)
        self.worker_starts = self.worker_closes = 0
        self.lb_cache = {}         # k → (version, 계산 시각, 결과)
        self.lb_lock = threading.Lock()

    def cached_leaderboard(self, con, k):
        """순위는 기록이 많으면 수백 ms 걸린다. 새 기록이 있거나 LB_TTL이 지났을 때만 다시 계산한다"""
        with self.lb_lock:
            hit = self.lb_cache.get(k)
            if hit and hit[0] == self.version and time.time() - hit[1] < LB_TTL:
                return hit[2]
            v = self.version
            out = leaderboard(con, k=k)
            self.lb_cache[k] = (v, time.time(), out)
            return out

    def bump(self):
        with self.cond:
            self.version += 1
            self.cond.notify_all()


def note_status(st, con, concept):
    """ready·none·pending·failed. 노트가 없거나 오래됐으면 수집을 예약한다 (응답은 기다리지 않음)"""
    row = con.execute("SELECT definition, updated FROM notes WHERE concept=?", (concept,)).fetchone()
    t = parse_ts(row[1]) if row else None
    fresh = t is not None and time.time() - t < NOTE_TTL
    has_def = bool(row and row[0])
    status = "ready" if has_def else "none"
    with st.note_lock:
        if not fresh and concept not in st.note_pending:
            failed_at = st.note_failed.get(concept)
            if failed_at is None or time.time() - failed_at >= NOTE_RETRY:
                st.note_pending.add(concept)
                st.note_q.put(concept)
        if has_def:
            return status
        if concept in st.note_pending:
            return "pending"
        if concept in st.note_failed:
            return "failed"
    return status


def note_loop(st, fetcher=None):
    """노트 수집 일꾼 1개 (같은 사이트 1초 1번 규칙을 지키려고 한 번에 하나씩). 끝나면 update 이벤트로 알린다"""
    fetcher = fetcher or fetch_note
    con = open_db(st.db)
    while not st.stop.is_set():
        try:
            c = st.note_q.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            forms = [r[0] for r in con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form", (c,))]
            definition, sources = fetcher(forms[0] if forms else c, forms[1:], context_terms(con, c))
            save_note(con, c, definition, sources)
            with st.note_lock:
                st.note_failed.pop(c, None)
        except Exception as e:  # noqa: BLE001 — 네트워크가 끊겨도 서버는 계속 돈다. 저장하지 않으므로 나중에 다시 시도
            print(f"[경고] 정의 수집 실패: {type(e).__name__}: {e}", flush=True)
            st.note_error = f"{type(e).__name__}: {e}"
            with st.note_lock:
                st.note_failed[c] = time.time()
            if isinstance(e, urllib.error.HTTPError) and e.code == 429:   # 요청이 많다는 응답: 대기열 전체를 쉰다
                try:
                    pause = int(e.headers.get("Retry-After", NOTE_RETRY))
                except (TypeError, ValueError):
                    pause = NOTE_RETRY
                st.stop.wait(pause)
        finally:
            with st.note_lock:
                st.note_pending.discard(c)
            st.bump()
    con.close()


def has_new_lines(con, inbox):
    """분석 프로세스를 깨울 일이 있는지: 파일이 줄었거나, 읽은 위치 뒤에 완성된 줄이 있음 (Kiwi 없이 가볍게)"""
    p = pathlib.Path(inbox).expanduser()
    if not p.exists():
        return False
    size = p.stat().st_size
    off = int(meta_get(con, "offset", 0))
    if size < off:
        return True
    with open(p, "rb") as f:
        f.seek(off)
        while True:
            chunk = f.read(65536)
            if not chunk:
                return False
            if b"\n" in chunk:
                return True


class IndexWorker:
    """Kiwi(약 550MB)는 이 자식 프로세스에만 올린다. 서버 본체는 가볍게 두고, 오래 쉬면 프로세스째 끝낸다."""

    def __init__(self, st):
        self.proc = subprocess.Popen(
            [sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "--inbox", str(st.inbox),
             "--db", str(st.db), "--roles", ",".join(sorted(st.roles))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")

    def ingest(self):
        self.proc.stdin.write("go\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline().strip()        # 새 턴 수. 실패는 -1, 프로세스가 죽으면 빈 줄
        if not line or int(line) < 0:
            raise RuntimeError("분석 프로세스 실패")
        return int(line)

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.proc.kill()
            self.proc.wait()
        self.proc.stdout.close()


def worker_main(inbox, db, roles):
    """--worker: 부모가 'go'를 보낼 때마다 이어 읽기. 부모가 끝나 stdin이 닫히면 같이 끝난다"""
    con = open_db(db)
    try:
        for _ in sys.stdin:
            try:
                n = ingest(con, inbox, roles)
            except Exception as e:  # noqa: BLE001
                print(f"[경고] 색인 실패: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                n = -1
            print(n, flush=True)
    except KeyboardInterrupt:
        pass
    con.close()


def tail_loop(st, interval=1.0, idle=WORKER_IDLE):
    con = open_db(st.db)
    worker, last_work, retry_at = None, 0.0, 0.0
    while not st.stop.is_set():
        try:
            now = time.time()
            if now >= retry_at and has_new_lines(con, st.inbox):
                if worker is None:
                    worker = IndexWorker(st)
                    st.worker_starts += 1
                n = worker.ingest()
                last_work = time.time()
                if n:
                    st.bump()
            if worker is not None and time.time() - last_work >= idle:
                worker.close()
                worker = None
                st.worker_closes += 1
        except Exception as e:  # noqa: BLE001 — 한 번 실패해도 서버는 계속 돈다
            print(f"[경고] 인박스 읽기 실패: {type(e).__name__}: {e}", flush=True)
            retry_at = time.time() + WORKER_BACKOFF
            if worker is not None:
                worker.close()
                worker = None
        st.stop.wait(interval)
    if worker is not None:
        worker.close()
    con.close()


def make_handler(st):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json; charset=utf-8"):
            b = body if isinstance(body, bytes) else (
                body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8"))
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass                                      # 브라우저가 먼저 닫은 경우

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            path = u.path
            if path == "/api/events":
                return self.events()
            if path.startswith("/api/"):
                con = open_db(st.db)
                try:
                    if path == "/api/leaderboard":
                        return self.send(200, st.cached_leaderboard(con, max(1, min(int(q.get("k", 10)), 100))))
                    if path.startswith("/api/concept/"):
                        cid = urllib.parse.unquote(path[len("/api/concept/"):])
                        if not con.execute("SELECT 1 FROM freq WHERE concept=?", (cid,)).fetchone():
                            return self.send(404, {"error": "없는 개념", "id": cid})
                        return self.send(200, dict(concept_card(con, cid, q.get("cursor")),
                                                   note_status=note_status(st, con, cid)))
                    if path == "/api/status":
                        return self.send(200, {"inbox": str(pathlib.Path(st.inbox).expanduser()),
                                               "offset": int(meta_get(con, "offset", 0)),
                                               "turns": int(meta_get(con, "turns", 0)),
                                               "sessions": con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                                               "version": st.version})
                    return self.send(404, {"error": "없는 API"})
                except ValueError as e:
                    return self.send(400, {"error": str(e)})
                finally:
                    con.close()
            return self.static(path)

        def static(self, path):
            if st.web:
                root = pathlib.Path(st.web).resolve()
                f = (root / (path.lstrip("/") or "index.html")).resolve()
                if f.is_dir():
                    f = f / "index.html"
                if root in f.parents and f.is_file():
                    ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                             ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png"}.get(
                        f.suffix, "application/octet-stream")
                    return self.send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
                return self.send(404, {"error": "없는 파일"})
            if path in ("/", "/index.html"):
                return self.send(200, PAGE, "text/html; charset=utf-8")
            return self.send(404, {"error": "없는 경로"})

        def events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = -1
            try:
                while not st.stop.is_set():
                    with st.cond:
                        if st.version == seen:
                            st.cond.wait(timeout=15)
                        v = st.version
                    if v != seen:
                        seen = v
                        self.wfile.write(f"event: update\ndata: {json.dumps({'version': v})}\n\n".encode("utf-8"))
                    else:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
    return H


def make_server(st, host="127.0.0.1", port=8765):
    srv = ThreadingHTTPServer((host, port), make_handler(st))
    srv.daemon_threads = True
    return srv


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inbox", default=DEFAULT_INBOX)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--roles", default="assistant,subagent", help="색인할 역할 (쉼표로)")
    ap.add_argument("--web", default=None, help="화면 폴더 (index.html). 없으면 내장 간이 화면")
    ap.add_argument("--searx", default=DEFAULT_SEARX, help="위키백과에 없는 개념을 찾을 SearXNG 주소. 안 쓰려면 off")
    ap.add_argument("--once", action="store_true", help="한 번 색인하고 순위를 출력한 뒤 끝")
    ap.add_argument("--rebuild", action="store_true", help="색인을 지우고 처음부터 다시")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)   # 서버가 띄우는 분석 프로세스
    a = ap.parse_args()
    roles = {r.strip() for r in a.roles.split(",") if r.strip()}
    if a.worker:
        return worker_main(a.inbox, a.db, roles)
    con = open_db(a.db)
    if a.rebuild:
        reset(con)
    if a.once:
        t0 = time.time()
        n = ingest(con, a.inbox, roles)
        print(f"색인: 새 턴 {n}개 ({time.time() - t0:.1f}초) · 인박스 {pathlib.Path(a.inbox).expanduser()}", flush=True)
        for x in leaderboard(con)["items"]:
            print(f"{x['rank']:>2}. {x['label']}  {x['score']}  ({x['sessions']}세션) {x['badge']}")
        return
    con.close()
    print(f"인박스 {pathlib.Path(a.inbox).expanduser()} 을 뒤에서 색인합니다", flush=True)
    st = State(a.db, a.inbox, roles, a.web)
    threading.Thread(target=tail_loop, args=(st,), daemon=True).start()
    searx = None if a.searx.lower() == "off" else a.searx
    threading.Thread(target=note_loop, args=(st, lambda t, al=(), ctx=(): fetch_note(t, al, searx, ctx)), daemon=True).start()
    srv = make_server(st, a.host, a.port)
    print(f"열림: http://localhost:{srv.server_address[1]}  (끝내려면 Ctrl+C)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        st.stop.set()
        srv.server_close()


if __name__ == "__main__":
    main()
