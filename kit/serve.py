# -*- coding: utf-8 -*-
"""serve.py : 개념 차트 로컬 서버 (표준 라이브러리 + kiwipiepy, 정의 수집만 같은 폴더의 fetch_sources.py를 쓴다)

    python kit/serve.py                      # http://localhost:8765
    python kit/serve.py --port 8765 --inbox ~/.claude/concept-inbox.jsonl --db ~/.claude/concept-chart.sqlite
    python kit/serve.py --project C:/work/app  # 이 폴더(하위 포함)의 대화만 먼저 보여 준다
    python kit/serve.py --once               # 인박스를 한 번만 읽어 색인하고 끝 (점검용)
    python kit/serve.py --rebuild            # 색인을 지우고 인박스 처음부터 다시

인박스를 1초마다 이어 읽기 → SQLite 색인 → API
    GET /api/leaderboard?k=10      중요도 순위 (제안 C: 세션 빈도 반감기 7일 × 세션 IDF)
    GET /api/concept/{id}?cursor=  클릭 카드 (정의·출처·관련 개념 3개·기록 3개, LLM 없음).
                                   정의가 없으면 뒤에서 위키백과를 찾아 notes에 저장 (30일 유효)
    GET /api/events                새 기록을 색인하거나 정의를 저장하면 'update' 이벤트 (SSE)
    GET /api/projects              기록된 작업 폴더 목록 (순위·카드는 ?project=경로 로 좁힌다, 빈 값 = 전체)
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
import hashlib
import importlib
import importlib.util
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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
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
WEEKS = 8                      # 순위 표의 주별 막대 개수
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
COOC_KEEP = 150                # (11-13 사용자 결정) '함께 나온 개념' 표는 하루 한 번 개념마다 많이 나온 짝 150개만 남긴다. 실험: experiments/2026-11-13-cooc-slim
HEAD_BYTES = 256               # 인박스가 다른 파일로 바뀌었는지 볼 앞부분 길이
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
# (11-13 실험) 브라우저 확장 THYNK(extension/, manifest의 key로 고정한 ID)만 답변 추가(/api/ingest)를 쓸 수 있다. 다른 확장·사이트는 그대로 막는다
EXTENSION_IDS = {"idefgkkfmkgofakkaapjnafeleebnfla"}
MODEL_LOAD_TIMEOUT = 300       # 모델 불러오기 제한 (초). 넘으면 규칙으로 계속
MODEL_CALL_TIMEOUT = 5         # 표기 하나 판단 제한 (초). 넘으면 규칙으로 계속

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


class ModelSlot:
    """학습 모델을 끼우는 유일한 자리. 없거나 고장 나면 규칙(norm_key)으로 돌아가고 색인은 계속된다.

    --model 모듈:함수 로 켠다 (기본은 끔). 함수가 돌려주는 객체는 canonical(표기) -> 개념 이름 또는 None 을 가진다.
    분석 프로세스 안에서만 불러오므로 서버 본체의 메모리·응답에 영향을 주지 않는다. 계약은 docs/ARCHITECTURE.md"""

    def __init__(self, spec=None):
        self.spec, self.impl, self.pool = spec or None, None, None

    def _off(self, why):
        print(f"[경고] 모델을 끄고 규칙으로 계속합니다 ({self.spec}): {why}", file=sys.stderr, flush=True)
        self.spec = None
        if self.pool:
            self.pool.shutdown(wait=False, cancel_futures=True)

    def _load(self):
        module, _, factory = self.spec.partition(":")
        return getattr(importlib.import_module(module), factory or "load")()

    def key(self, form):
        rule = norm_key(form)
        if not self.spec:
            return rule
        try:
            if self.impl is None:
                self.pool = self.pool or ThreadPoolExecutor(max_workers=1)
                self.impl = self.pool.submit(self._load).result(timeout=MODEL_LOAD_TIMEOUT)
            name = self.pool.submit(self.impl.canonical, form).result(timeout=MODEL_CALL_TIMEOUT)
        except FutureTimeout:
            self._off("응답 시간 초과")
            return rule
        except Exception as e:  # noqa: BLE001 — 모델 문제로 색인을 멈추지 않는다
            self._off(f"{type(e).__name__}: {e}")
            return rule
        if name is None:
            return rule
        return (norm_key(name) or rule) if isinstance(name, str) else rule


_model = ModelSlot()


def set_model(spec):
    global _model
    _model = ModelSlot(spec)


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


SPLIT_SUFFIX = {"당", "별", "들", "씩", "째"}     # 0.7.0 (사용자 결정 11-11): 에폭당·에폭별·개발자들 → 에폭·개발자. 개념이 아니라 '마다·끼리·여럿'을 더하는 꼬리


def whole_word(w):
    """붙인 꼴 전체가 전문 뜻이 있는 낱말인가 (포도당·민주당은 '포도 + 당'이 아니다). 일상 뜻으로만 실린 꼴(단계별·국가별)은 뗀다"""
    import concept_gate as gate
    return gate.lexicon_verdict(w) in ("special", "mixed") or gate.key(w) in gate.terms()


def noun_groups(s):
    """붙어 있는 명사(+명사 파생 접미사 XSN)는 한 덩어리로: 가중+치 → 가중치, 시각+화 → 시각화. 영문·한자는 그대로.
    SPLIT_SUFFIX 꼬리(당·별·들·씩·째)는 붙이지 않고 버린다. 붙인 꼴 전체가 사전에 있으면(포도당) 붙인다"""
    out, cur, end = [], "", -1
    toks = get_kiwi().tokenize(s)
    for i, t in enumerate(toks):
        glued = bool(cur) and t.start == end
        if t.tag == "XSN" and glued and t.form in SPLIT_SUFFIX and not whole_word(cur + t.form):
            out.append(cur)
            cur = ""
        elif t.tag in ("NNG", "NNP") or (t.tag == "XSN" and glued):
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
    return [strip_tail(w) for w in out]


def strip_tail(w):
    """분석기가 한 명사로 묶은 '단계별·사람들·에폭당'의 꼬리(별·들·당)도 뗀다. 세 글자 이상이고 통째로 전문 뜻이 있는 낱말이 아닐 때만
    (포도당·민주당은 사전에 전문 뜻이 있어 그대로. 0.7.1: 실제 데이터의 에폭당·턴당은 분석기가 한 명사로 묶었다)"""
    if len(w) >= 3 and re.fullmatch(r"[가-힣]+", w) and w[-1] in "별들당" and not whole_word(w):
        import concept_gate as gate
        if w[-1] == "당" and not gate.has_lexicon():         # 사전이 없으면 포도당·민주당을 가를 수 없다: '-당'은 떼지 않는다
            return w
        return w[:-1]
    return w


def plain_line(s):
    """마크다운 표시를 걷어 낸 읽을 수 있는 문장: **굵게**·# 제목·- 목록·표 칸"""
    s = re.sub(r"\s+", " ", s).strip()
    if re.fullmatch(r"\|?[\s:\-|]+\|?", s):
        return ""
    s = re.sub(r"^(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s+)+", "", s)
    if s.startswith("|") and s.endswith("|"):
        s = " · ".join(c.strip() for c in s.strip("|").split("|") if c.strip())
    return re.sub(r"\*\*|__", "", s).strip()


def extract(text):
    """본문 → [(문장, {개념 키: 표기})] (코드 용어는 첫 문장 자리에 붙인다)"""
    code = "\n".join(FENCE.findall(text))
    prose = FENCE.sub(" ", text)
    inline = INLINE.findall(prose)
    prose = PATH.sub(" ", URL.sub(" ", INLINE.sub(" ", prose)))
    shown = URL.sub(" ", INLINE.sub(lambda m: m.group(1), FENCE.sub(" ", text)))     # 화면에 보일 문장: 인라인 코드를 빼지 않는다 (`main`에 커밋 → main에 커밋)
    both = code + "\n" + "\n".join(inline) + "\n" + text
    code_terms = {(a or b).split(".")[0] for a, b in IMPORT.findall(code)}
    code_terms |= {re.split(r"[=<>\[]", p)[0] for m in PIP.findall(both) for p in m.split() if not p.startswith("-")}
    code_terms |= set(ERR.findall(both))
    out = []
    parts = SENT.split(prose)
    display = SENT.split(shown)
    same = len(parts) == len(display)                     # 나뉜 수가 다르면(인라인 코드에 마침표 등) 분석한 문장을 그대로 보여 준다
    for i, s in enumerate(parts):
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) < 4:
            continue
        cs = {}
        for f in noun_groups(s):
            if len(f) >= 2 and f not in STOP and f not in STOP_LOWER and f.lower() not in STOP_EN:
                cs.setdefault(_model.key(f), f)
        if cs:
            out.append((plain_line(display[i] if same else s) or s, cs))
    code_cs = {_model.key(c): c for c in code_terms if len(c) >= 2 and c.lower() not in STOP_EN}
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
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, last_ts REAL, project TEXT);
CREATE TABLE IF NOT EXISTS term_sess (concept TEXT, session TEXT, PRIMARY KEY (concept, session));
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS answers (id TEXT PRIMARY KEY, session TEXT, ts TEXT, source TEXT, text TEXT, question INTEGER);
CREATE INDEX IF NOT EXISTS ix_a ON answers (ts DESC);
CREATE TABLE IF NOT EXISTS judgments (concept TEXT PRIMARY KEY, llm INTEGER, user TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS study_notes (concept TEXT PRIMARY KEY, body TEXT, status TEXT, model TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS answer_summaries (answer TEXT PRIMARY KEY, body TEXT, status TEXT, model TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS progress (concept TEXT PRIMARY KEY, status TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, kind TEXT, target TEXT, priority INTEGER, status TEXT, tries INTEGER DEFAULT 0, updated TEXT, UNIQUE (kind, target));
"""
SYSTEM_MSG = re.compile(r"\s*<(?:task-notification|system-reminder|command-|local-command)")
NOTE_REFETCH = 7              # 정의 찾는 방법이 바뀌면 올린다 (1: 0.7.2 우리말샘·PyPI, 2: 0.7.8·0.7.9 오류 고침, 3: 0.7.11 같은 분야 여러 뜻, 4: 0.7.12 언어 모델·챗봇 괄호, 5: 0.7.13 우리말샘 뜻 고르기 강화, 6: 0.7.15 다른 뜻으로 넘겨준 위키백과 문서 거르기, 7: 0.8.2 이 PC 안 위키백과 색인·검색 문맥에서 일상어 빼기)
SCHEMA_VERSION = 8            # (7: 0.7.0 꼬리 당·별·들 떼기, 8: 0.7.1 한 명사로 묶인 '-당'도 떼기) 색인 표 구조나 개념 추출 규칙이 바뀌면 올린다. 다르면 색인을 지우고 인박스에서 다시 만든다 (notes는 남김)
DERIVED = ("mentions", "questions", "cooc", "freq", "forms", "sessions", "term_sess", "meta", "answers")   # notes(웹 근거)·판정·노트·진도는 남긴다


def wiki_title(url):
    """위키백과 주소 → 문서 제목 (위키백과가 아니면 None)"""
    if "wikipedia.org/wiki/" not in str(url):
        return None
    return urllib.parse.unquote(str(url).split("/wiki/", 1)[1]).replace("_", " ")


def other_sense_notes(con):
    """(0.7.15) 저장된 정의 중 첫 출처가 다른 뜻의 위키백과 문서인 개념 (fetch_sources.other_sense)"""
    import fetch_sources as fs
    out = []
    for cid, src in con.execute("SELECT concept, sources FROM notes WHERE definition != '' AND sources LIKE '%wikipedia.org%'").fetchall():
        try:
            first = (json.loads(src) or [{}])[0]
        except (ValueError, TypeError):
            continue
        title = wiki_title(first.get("url", "")) if isinstance(first, dict) else None
        row = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()
        if title and fs.other_sense(row[0] if row else cid, title):
            out.append(cid)
    return out


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
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='judgments'").fetchone() and "code" in {r[1] for r in con.execute("PRAGMA table_info(judgments)")}:
            con.execute("UPDATE judgments SET code=NULL")      # 코드 이름 판정은 원 답변(색인)에서 나온다: 색인을 다시 만들면 다시 계산한다
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        con.commit()
    if "everyday" not in {r[1] for r in con.execute("PRAGMA table_info(judgments)")}:    # 0.5.4: 두 번째 질문 답 (판정 표는 지우지 않으므로 열만 더한다)
        con.execute("ALTER TABLE judgments ADD COLUMN everyday INTEGER")
        con.commit()
    if "code" not in {r[1] for r in con.execute("PRAGMA table_info(judgments)")}:        # 0.7.0: 원 답변에서 코드로 쓰인 영어 이름인가 (concept_gate.code_name, LLM 없음)
        con.execute("ALTER TABLE judgments ADD COLUMN code INTEGER")
        con.commit()
    con.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")     # 색인을 다시 만들어도 남는 작은 표시들
    if not con.execute("SELECT 1 FROM settings WHERE k='note_fallback_v1'").fetchone():
        con.execute("UPDATE notes SET updated='' WHERE definition=''")    # 0.7.2: 정의를 못 찾았던 개념은 우리말샘·PyPI로 한 번 다시 찾는다
        con.execute("INSERT INTO settings VALUES ('note_fallback_v1', ?)", (datetime.now(timezone.utc).isoformat(),))
        con.commit()
    got = con.execute("SELECT v FROM settings WHERE k='note_refetch'").fetchone()
    if not got or int(got[0]) < NOTE_REFETCH:                 # 정의 찾는 방법이 바뀌면(NOTE_REFETCH) 정의 없는 개념을 한 번 더 찾는다
        con.execute("UPDATE notes SET updated='' WHERE definition=''")
        if not got or int(got[0]) < 5:                        # 0.7.13: 예전 규칙으로 붙인 우리말샘 설명은 지우고 새 규칙으로 다시 (틀린 뜻이 섞였다)
            ids = [r[0] for r in con.execute("SELECT concept FROM notes WHERE sources LIKE '%opendict.korean.go.kr%'")]
            con.executemany("UPDATE notes SET definition='', sources='[]', updated='' WHERE concept=?", [(i,) for i in ids])
            con.executemany("DELETE FROM study_notes WHERE concept=?", [(i,) for i in ids])
        if not got or int(got[0]) < 6:                        # 0.7.15: 다른 뜻 문서(중복 → 복날, Export → 수출)로 붙인 위키백과 설명은 지우고 다시 찾는다
            ids = other_sense_notes(con)
            con.executemany("UPDATE notes SET definition='', sources='[]', updated='' WHERE concept=?", [(i,) for i in ids])
            con.executemany("DELETE FROM study_notes WHERE concept=?", [(i,) for i in ids])
        con.execute("REPLACE INTO settings VALUES ('note_refetch', ?)", (str(NOTE_REFETCH),))
        con.commit()
    con.execute("CREATE TABLE IF NOT EXISTS wiki_names (concept TEXT PRIMARY KEY, url TEXT, updated TEXT)")   # (0.7.16) 정의로 쓰지 않은 다른 뜻 위키백과 문서 (관문 근거만)
    if not con.execute("SELECT 1 FROM settings WHERE k='wiki_names_v1'").fetchone():
        # 0.7.16: 0.7.15가 지운 정의는 문서 주소도 함께 지워져 관문 근거를 잃었다. 다시 찾기를 기다리는 빈 기록을 지워
        # 관문 확인(warm_targets의 문서 확인)이 다시 찾게 한다. 다시 찾으면 다른 뜻 문서는 wiki_names에 남는다
        con.execute("DELETE FROM notes WHERE definition='' AND sources='[]' AND updated=''")
        con.execute("INSERT INTO settings VALUES ('wiki_names_v1', ?)", (datetime.now(timezone.utc).isoformat(),))
        con.commit()
    if not con.execute("SELECT 1 FROM settings WHERE k='sense_v2'").fetchone():
        con.execute("DELETE FROM study_notes WHERE status='wrong_sense'")    # 0.7.3: '기술 분야만' 확인으로 숨겼던 노트를 바뀐 기준으로 한 번 다시 만든다
        con.execute("INSERT INTO settings VALUES ('sense_v2', ?)", (datetime.now(timezone.utc).isoformat(),))
        con.commit()
    if not con.execute("SELECT 1 FROM settings WHERE k='en_judge_v1'").fetchone():        # 0.7.5: 영어 표기 낱말은 새 질문(en_judge_prompt)으로 한 번 다시 묻는다 (사용자 판단은 그대로)
        ids = [r[0] for r in con.execute("SELECT concept FROM judgments WHERE llm IS NOT NULL AND user IS NULL") if re.fullmatch(r"[a-z0-9.+#_\-]+", r[0])]
        con.executemany("UPDATE judgments SET llm=NULL WHERE concept=?", [(i,) for i in ids])
        con.execute("INSERT INTO settings VALUES ('en_judge_v1', ?)", (datetime.now(timezone.utc).isoformat(),))
        con.commit()
    if not con.execute("SELECT 1 FROM settings WHERE k='en_judge_v2'").fetchone():        # 0.7.7: 사용자 판단이 있는 영어 낱말도 측정용으로 새 질문에 다시 묻는다
        ids = [r[0] for r in con.execute("SELECT concept FROM judgments WHERE llm IS NOT NULL AND user IS NOT NULL") if re.fullmatch(r"[a-z0-9.+#_\-]+", r[0])]
        con.executemany("UPDATE judgments SET llm=NULL WHERE concept=?", [(i,) for i in ids])
        con.execute("INSERT INTO settings VALUES ('en_judge_v2', ?)", (datetime.now(timezone.utc).isoformat(),))
        con.commit()
    if not con.execute("SELECT 1 FROM settings WHERE k='note_retry_v1'").fetchone():
        con.execute("DELETE FROM study_notes WHERE status='rejected'")       # 0.7.4: 근거 대조에서 탈락한 쉬운 설명은 바뀐 방식(개념 이름 허용·한 번 더)으로 한 번 다시
        con.execute("INSERT INTO settings VALUES ('note_retry_v1', ?)", (datetime.now(timezone.utc).isoformat(),))
        con.commit()
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='views'").fetchone():    # 0.6.0: 개념 노트를 열어 본 기록 ('내 공부 기록에 묻기'용, 색인을 다시 만들어도 남는다)
        con.execute("CREATE TABLE views (concept TEXT, ts TEXT)")
        con.execute("CREATE INDEX ix_v ON views (ts DESC)")
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


def prepare_record(r, roles):
    """DB를 건드리지 않는 준비 단계 (형태소 분석 포함, 쓰기 잠금 밖에서 돈다). 쓸 수 없는 기록이면 None"""
    text, role = r.get("text"), r.get("role")
    if not isinstance(text, str) or not text or not isinstance(role, str):
        return None
    t = parse_ts(r.get("ts")) or time.time()
    ts = datetime.fromtimestamp(t, timezone.utc).isoformat()
    sess = r.get("session_id")
    sess = sess if isinstance(sess, str) and sess else "day:" + ts[:10]
    project = r.get("project")
    source = r.get("source")
    return {"t": t, "ts": ts, "sess": sess, "role": role, "text": text, "source": source if isinstance(source, str) and source else "unknown",
            "project": project if isinstance(project, str) else None,
            "sc": extract(text) if role in roles else None}


def apply_record(con, p):
    """준비한 기록을 DB에 넣는다 (쓰기 잠금 안). → 새로 색인한 턴이면 True"""
    t, ts, sess = p["t"], p["ts"], p["sess"]
    if p["role"] == "user" and not SYSTEM_MSG.match(p["text"]):   # 질문은 분석하지 않고 원문 그대로 저장 → 뒤따르는 답변의 개념과 연결. 도구가 보낸 알림은 질문이 아니다
        con.execute("INSERT INTO questions (session, ts, text) VALUES (?,?,?)", (sess, ts, p["text"]))
    if not p["sc"]:
        return False
    q = con.execute("SELECT MAX(id) FROM questions WHERE session=?", (sess,)).fetchone()[0]
    aid = hashlib.sha1(f"{sess}|{ts}".encode("utf-8")).hexdigest()[:16]    # 답변 읽기 화면용 원문 (study_api.answer_id와 같은 규칙)
    con.execute("INSERT OR REPLACE INTO answers VALUES (?,?,?,?,?,?)", (aid, sess, ts, p.get("source", "unknown"), p["text"], q))
    seen = set()
    for s, cs in p["sc"]:
        for k, form in cs.items():
            if k not in seen:                             # 답변 하나에 개념 1행 (처음 나온 문장만). 순위는 freq·term_sess로 계산해 영향 없음
                con.execute("INSERT INTO mentions VALUES (?,?,?,?,?,?)", (k, ts, sess, p["role"], s[:SNIPPET], q))
            con.execute("INSERT INTO forms VALUES (?,?,1) ON CONFLICT(concept, form) DO UPDATE SET n=n+1", (k, form))
        seen |= set(cs)
    con.execute("""INSERT INTO sessions VALUES (?,?,?) ON CONFLICT(id) DO UPDATE
                   SET last_ts=max(last_ts, excluded.last_ts), project=COALESCE(project, excluded.project)""",
                (sess, t, norm_project(p["project"])))
    day, last = ts[:10], meta_get(con, "cooc_day")
    if last is None or day > last:                        # 날짜가 넘어가면 지난 날까지 쌓인 짝을 정리 (처음이면 날짜만 적는다)
        if last is not None:
            compact_cooc(con)
        meta_set(con, "cooc_day", day)
    for c in seen:
        con.execute("INSERT INTO freq VALUES (?,1) ON CONFLICT(concept) DO UPDATE SET n=n+1", (c,))
        con.execute("INSERT OR IGNORE INTO term_sess VALUES (?,?)", (c, sess))
        for d in seen:
            if c != d:
                con.execute("INSERT INTO cooc VALUES (?,?,1) ON CONFLICT(a,b) DO UPDATE SET n=n+1", (c, d))
    return True


def compact_cooc(con, k=COOC_KEEP):
    """개념마다 짝을 n 큰 순(같으면 이름순)으로 k개만 남긴다. 관련 개념(상위 60개 중 6개)·정의 검색어(상위 2개)가 쓰는 앞쪽은 그대로다"""
    con.execute("""DELETE FROM cooc WHERE rowid IN (SELECT rowid FROM (
                   SELECT rowid, ROW_NUMBER() OVER (PARTITION BY a ORDER BY n DESC, b) AS r FROM cooc) WHERE r > ?)""", (k,))


def head_print(path, n):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read(n)).hexdigest()


def inbox_replaced(con, path, size, off):
    """다른 파일로 바뀌었는지: 파일이 읽은 위치보다 작거나, 앞부분 지문이 다르다 (인박스는 뒤에만 붙으므로 앞부분은 그대로여야 한다)"""
    if size < off:
        return True
    n, saved = int(meta_get(con, "head_len", 0)), meta_get(con, "head")
    return bool(n and saved) and head_print(path, n) != saved


def remember_head(con, path, off):
    n = min(HEAD_BYTES, off)
    if n and int(meta_get(con, "head_len", 0)) != n:
        meta_set(con, "head", head_print(path, n))
        meta_set(con, "head_len", n)
        con.commit()


def ingest(con, inbox, roles):
    """인박스에서 아직 안 읽은 완성된 줄만 색인한다. 다른 파일로 바뀌었으면 처음부터 다시. → 새로 색인한 턴 수
    줄마다 쓰기 잠금 안에서 읽은 위치를 다시 확인한다: 같은 DB를 쓰는 다른 프로세스가 있어도 한 줄을 두 번 세지 않는다.
    쓸 수 없는 줄은 건너뛰고, DB 잠금 같은 일시 오류와 패키지 없음은 위치를 옮기지 않고 올린다 (고친 뒤 이어서 읽는다)."""
    p = pathlib.Path(inbox).expanduser()
    if not p.exists():
        return 0
    size = p.stat().st_size
    off = int(meta_get(con, "offset", 0))
    if inbox_replaced(con, p, size, off):
        reset(con)
        off = 0
    if size == off:
        remember_head(con, p, off)
        return 0
    with open(p, "rb") as f:
        f.seek(off)
        chunk = f.read(size - off)
    end = chunk.rfind(b"\n")
    if end < 0:                                   # 아직 쓰는 중인 줄만 있음
        return 0
    n, pos = 0, off
    for line in chunk[:end].split(b"\n"):
        before, pos = pos, pos + len(line) + 1
        prepared = None
        try:
            r = json.loads(line.decode("utf-8"))
            prepared = prepare_record(r, roles) if isinstance(r, dict) else None
        except (ValueError, UnicodeDecodeError):
            pass
        except (ImportError, MemoryError):
            raise
        except Exception as e:  # noqa: BLE001 — 이 줄만 건너뛴다
            print(f"[경고] 인박스 줄 건너뜀 (위치 {before}): {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        con.execute("BEGIN IMMEDIATE")            # 줄마다 커밋: 쓰기 잠금을 짧게 쥐어 정의 저장·조회를 막지 않는다
        try:
            if int(meta_get(con, "offset", 0)) != before:   # 다른 프로세스가 먼저 읽었다
                con.rollback()
                return n
            if prepared and apply_record(con, prepared):
                n += 1
                meta_set(con, "turns", int(meta_get(con, "turns", 0)) + 1)
            meta_set(con, "offset", pos)
            con.commit()
        except sqlite3.OperationalError:
            con.rollback()
            raise
        except Exception as e:  # noqa: BLE001 — 이 줄만 건너뛴다
            con.rollback()
            print(f"[경고] 인박스 줄 건너뜀 (위치 {before}): {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            con.execute("BEGIN IMMEDIATE")
            meta_set(con, "offset", pos)
            con.commit()
    remember_head(con, p, pos)
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


def norm_project(p):
    """폴더 경로 비교용 표기: 슬래시 통일, 끝 슬래시 제거, 드라이브 대문자 (C:\\work\\app\\ = c:/work/app). 없으면 None"""
    if not p:
        return None
    s = str(p).strip().replace("\\", "/").rstrip("/")
    if re.match(r"^[a-z]:", s):
        s = s[0].upper() + s[1:]
    return s or None


def project_clause(project, column="project"):
    """그 폴더와 하위 폴더만 (app은 app/sub를 포함하고 app2는 포함하지 않는다) → (SQL 조건, 인자). 전체면 ("1=1", [])"""
    if not project:
        return "1=1", []
    return f"({column}=? OR substr({column},1,?)=?)", [project, len(project) + 1, project + "/"]


def in_project(project, column="m.session"):
    where, args = project_clause(project)
    return f"{column} IN (SELECT id FROM sessions WHERE {where})", args


def projects(con):
    """화면의 폴더 고르기: 최근에 쓴 폴더부터. 폴더 정보가 없는 세션(예전 기록 등)은 '전체'에서만 보인다"""
    rows = con.execute("""SELECT project, COUNT(*), MAX(last_ts) FROM sessions WHERE project IS NOT NULL
                          GROUP BY project ORDER BY MAX(last_ts) DESC, project""").fetchall()
    unknown = con.execute("SELECT COUNT(*) FROM sessions WHERE project IS NULL").fetchone()[0]
    return {"items": [{"path": p, "name": p.rsplit("/", 1)[-1] or p, "sessions": n,
                       "last_seen": datetime.fromtimestamp(t, timezone.utc).isoformat()} for p, n, t in rows],
            "no_project_sessions": unknown}


def leaderboard(con, k=10, now=None, project=None):
    """점수 = log1p(Σ 개념이 나온 세션의 2^(-경과일/7)) × (log((N+1)/(df+1)) + 1). project를 주면 N·df도 그 폴더의 세션만으로 계산"""
    now = time.time() if now is None else now
    where, wargs = project_clause(project)
    sess = dict(con.execute(f"SELECT id, last_ts FROM sessions WHERE {where}", wargs))
    N = len(sess)
    age = {s: max(0.0, (now - t) / 86400) for s, t in sess.items()}
    rec = [s for s, a in age.items() if a < 14]
    pri = [s for s, a in age.items() if 14 <= a < 42]
    by = {}
    for c, s in con.execute("SELECT concept, session FROM term_sess"):
        if s in sess:
            by.setdefault(c, []).append(s)
    items = []
    for c, ss in by.items():
        dsf = sum(2.0 ** (-age[s] / HALF_LIFE_DAYS) for s in ss if s in age)
        idf = math.log((N + 1) / (len(ss) + 1)) + 1
        x1 = sum(1 for s in ss if s in rec and s in age)
        x0 = sum(1 for s in ss if s in pri and s in age)
        z = two_prop_z(x1, len(rec), x0, len(pri))
        badge = "up" if z > BADGE_Z and x1 >= BADGE_MIN_SESS else "down" if z < -BADGE_Z and x0 >= BADGE_MIN_SESS else ""
        weekly = [0] * WEEKS                      # 오래된 주 → 이번 주, 그 주에 이 개념이 나온 세션 수
        for s in ss:
            if age[s] < WEEKS * 7:
                weekly[WEEKS - 1 - int(age[s] // 7)] += 1
        items.append((math.log1p(dsf) * idf, c, len(ss), badge, max(sess[s] for s in ss if s in sess), x1, weekly))
    items.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for i, (score, c, nsess, badge, last, recent, weekly) in enumerate(items[:k], 1):
        if project:
            clause, cargs = in_project(project, "session")
            m = con.execute(f"SELECT COUNT(*) FROM mentions WHERE concept=? AND {clause}", [c] + cargs).fetchone()
        else:
            m = con.execute("SELECT n FROM freq WHERE concept=?", (c,)).fetchone()
        out.append({"rank": i, "id": c, "label": label_of(con, c), "score": round(score, 4), "sessions": nsess,
                    "turns": m[0] if m else 0, "badge": badge, "recent_sessions": recent, "weekly": weekly,
                    "last_seen": datetime.fromtimestamp(last, timezone.utc).isoformat()})
    return {"generated": datetime.fromtimestamp(now, timezone.utc).isoformat(), "project": project, "n_sessions": N,
            "n_concepts": len(by), "items": out}


def context_terms(con, concept, k=2):
    """뜻을 가를 검색어: 내 대화에서 이 개념과 가장 자주 함께 나온 개념 이름.
    (0.8.2) 분야 사전에 일상 뜻이 있는 낱말(대화·기록·목록)은 빼고 고른다: 검색 결과에 그 낱말이 없다고 맞는 정의(conda·에폭)까지 버렸다"""
    import concept_gate as gate
    out = []
    for (b,) in con.execute("SELECT b FROM cooc WHERE a=? ORDER BY n DESC, b LIMIT 40", (concept,)).fetchall():
        label = label_of(con, b)
        if gate.lexicon_verdict(label) in ("general", "mixed") or label in gate.GENERAL:
            continue
        out.append(label)
        if len(out) == k:
            break
    return out


def fetch_note(term, aliases=(), searx=None, context=(), rejected=None):
    """개념 이름 → (정의 문장, [{text, url}]). 위키백과(ko → en) → 그래도 없으면 SearXNG (함께 나온 개념을 붙여서 → 없으면 이름만).
    근거가 없으면 ("", []), 네트워크 오류·SearXNG 꺼짐은 예외로 올린다 (저장하지 않고 나중에 다시 시도).
    출처 문장을 그대로 쓴다 (LLM이 만든 문장 없음). 밖으로 나가는 건 개념 이름뿐."""
    import fetch_sources as fs                            # 클릭할 때만 필요

    def result(ev):
        ev = [e for e in ev if str(e["url"]).startswith(("http://", "https://"))]   # 외부에서 온 링크: 화면에 넣기 전에 거른다
        ev = [e for e in ev if not hasattr(fs, "subject_ok") or fs.subject_ok(term, e["text"])]   # '이동 기준선은…'처럼 다른 낱말을 설명하는 문장은 받지 않는다
        return (ev[0]["text"], [{"text": e["text"], "url": e["url"]} for e in ev]) if ev else None
    got = result(fs.wikipedia_lead(term, rejected) if rejected is not None else fs.wikipedia_lead(term))   # 먼저 이름이 정확히 맞는 문서의 첫 문장 (문서 첫 문장이 곧 정의문이다)
    if got:
        return got
    for lang in NOTE_LANGS:
        # 띄어쓰기만 다른 문서 제목(파인튜닝 → 파인 튜닝)은 같은 개념의 표기로 본다. 다른 제목의 문서는 문장을 고르지 않는다 (AP → AP 통신, Chrome → Chrome OS)
        srcs = [s for s in fs.wikipedia(term, lang) if norm_key(s.get("title", "")) == norm_key(term)]
        titles = [s["title"] for s in srcs]
        got = result(fs.pick(term, list(aliases) + titles, srcs))
        if got:
            return got
        # 분야가 괄호로 붙은 문서(커밋 → 커밋 (버전 관리)): 기술 분야 괄호일 때만 같은 개념으로 본다
        tech = fs.wikipedia_tech(term, lang) if hasattr(fs, "wikipedia_tech") else []
        got = result(fs.pick(term, list(aliases) + [s["title"] for s in tech], tech))
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
    old = con.execute("SELECT definition FROM notes WHERE concept=?", (concept,)).fetchone()
    con.execute("REPLACE INTO notes VALUES (?,?,?,?)",
                (concept, definition, json.dumps(sources, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    if old and (old[0] or "") != (definition or ""):
        con.execute("DELETE FROM study_notes WHERE concept=?", (concept,))   # (0.7.13) 정의가 바뀌면 옛 정의로 만든 쉬운 설명을 지운다 (새 정의로 다시 만든다)
    con.commit()


def chat_line(con, concept, project=None):
    """정의를 못 찾았을 때 보여 줄 내 대화 속 문장. 개념 이름이 실제로 든 문장만 (코드에서만 나온 개념은 없음).
    '개념 + 은/는/이란'으로 시작하는 설명 문장을 먼저, 그다음 최근 문장"""
    forms = [re.sub(r"\s+", "", r[0]).lower() for r in con.execute("SELECT form FROM forms WHERE concept=?", (concept,))]
    clause, cargs = in_project(project)
    rows = con.execute(f"""SELECT m.ts, m.snippet, substr(qs.text, 1, ?) FROM mentions m LEFT JOIN questions qs ON qs.id = m.question
                           WHERE m.concept=? AND {clause} ORDER BY m.ts DESC, m.rowid DESC LIMIT 20""",
                       [QUESTION_MAX, concept] + cargs).fetchall()
    best = None
    for ts, snippet, question in rows:
        flat = re.sub(r"\s+", "", snippet).lower()
        if any(flat.startswith((f + "은", f + "는", f + "이란", f + "란")) for f in forms):
            best = (ts, snippet, question)
            break
        if best is None and any(f in flat for f in forms):
            best = (ts, snippet, question)
    return {"ts": best[0], "text": one_line(best[1]), "question": best[2]} if best else None


def concept_card(con, concept, cursor=None, k=3, project=None):
    """클릭 응답 (kit/concept_store.py와 같은 형식 + label): LLM 호출 없이. 근거 문장까지 채워지면 최대 약 4KB.
    project를 주면 내 기록·대화 문장만 그 폴더로 좁힌다 (정의와 관련 개념은 폴더와 무관)"""
    note = con.execute("SELECT definition, sources FROM notes WHERE concept=?", (concept,)).fetchone()
    related = con.execute(
        """SELECT b, c.n * 1.0 / ((SELECT n FROM freq WHERE concept=?) * (SELECT n FROM freq WHERE concept=b)) AS s
           FROM cooc c WHERE a=? ORDER BY s DESC, c.n DESC, b LIMIT ?""", (concept, concept, k)).fetchall()
    clause, cargs = in_project(project)
    q = f"""SELECT m.ts, m.role, m.snippet, m.rowid, substr(qs.text, 1, ?) FROM mentions m
            LEFT JOIN questions qs ON qs.id = m.question WHERE m.concept=? AND {clause}"""
    args = [QUESTION_MAX, concept] + cargs
    if cursor:
        ts, rid = cursor.rsplit("|", 1)
        q += " AND (m.ts < ? OR (m.ts = ? AND m.rowid < ?))"
        args += [ts, ts, int(rid)]
    rows = con.execute(q + " ORDER BY m.ts DESC, m.rowid DESC LIMIT ?", args + [k]).fetchall()
    return {"concept": concept, "label": label_of(con, concept),
            "summary": one_line(note[0]) if note else None,
            "definition": (note[0] or None) if note else None,
            "chat_line": None if note and note[0] else chat_line(con, concept, project),
            "sources": json.loads(note[1]) if note and note[1] and note[1][:1] in "[{" else [],
            "related": [{"id": r[0], "label": label_of(con, r[0])} for r in related],
            "records": [{"ts": r[0], "role": r[1], "snippet": r[2], "question": r[4]} for r in rows],
            "next_cursor": "%s|%d" % (rows[-1][0], rows[-1][3]) if len(rows) == k else None}


# ---------------- 서버 ----------------
PAGE = """<!doctype html><meta charset="utf-8"><title>개념 차트</title>
<style>body{font:15px/1.5 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}
li{cursor:pointer;margin:.3rem 0}small{color:#777}#card{border-top:1px solid #ddd;margin-top:1rem;padding-top:.5rem}</style>
<h1>개념 차트 <small id="st"></small></h1>
<p id="pjbox" hidden><label>폴더 <select id="pj"></select></label></p><ol id="lb"></ol><div id="card"></div>
<script>
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let pj,pjHtml='';const pq=()=>pj===undefined?'':'project='+encodeURIComponent(pj);
async function projects(){const d=await (await fetch('/api/projects')).json();
 if(pj===undefined)pj=d.default||'';
 const items=d.items.slice();if(pj&&!items.some(x=>x.path===pj))items.unshift({path:pj,name:pj.split('/').pop(),sessions:0});
 const html=`<option value="">전체 폴더</option>`+items.map(x=>`<option value="${esc(x.path)}" title="${esc(x.path)}">${esc(x.name)} (${x.sessions}세션) — ${esc(x.path)}</option>`).join('');
 if(html!==pjHtml){pjHtml=html;$('#pj').innerHTML=html;}
 $('#pj').value=pj;$('#pjbox').hidden=!items.length;}
$('#pj').onchange=e=>{pj=e.target.value;cur=null;open=false;$('#card').innerHTML='';lb();};
async function lb(){const d=await (await fetch('/api/leaderboard?k=10&'+pq())).json();
 $('#st').textContent=`세션 ${d.n_sessions} · 개념 ${d.n_concepts}`;
 $('#lb').innerHTML=d.items.map(x=>`<li data-id="${esc(x.id)}"><b>${esc(x.label)}</b> ${x.badge=='up'?'▲':x.badge=='down'?'▼':''} <small>${x.score} · ${x.sessions}세션</small></li>`).join('')||'<small>아직 기록이 없어요. Claude Code를 쓰면 여기에 쌓여요.</small>';}
let cur=null,open=false;const NOTE={pending:'정의를 찾는 중이에요…',none:'위키백과와 검색에서 근거를 찾지 못했어요.',failed:'정의를 가져오지 못했어요. 인터넷이나 SearXNG(python dev.py searx up)를 확인해 주세요.'};
async function card(){if(!cur)return;
 const c=await (await fetch('/api/concept/'+encodeURIComponent(cur)+'?'+pq())).json();
 const more=open?`<ol>${c.sources.map(s=>`<li style="cursor:auto">${esc(s.text)} <a href="${esc(s.url)}" target="_blank" rel="noopener">출처</a></li>`).join('')}</ol>
 <p>관련: ${c.related.map(r=>esc(r.label)).join(', ')||'-'}</p><ul>${c.records.map(r=>`<li style="cursor:auto"><small>${esc(r.ts.slice(0,16))}</small> ${r.question?`<b>내 질문:</b> ${esc(r.question)}<br>`:''}${esc(r.snippet)}</li>`).join('')}</ul>`:'';
 const chat=!c.summary&&c.note_status!=='pending'&&c.chat_line;
 const line=chat?`<small>내 대화에서 (출처 확인 전)</small><br>${esc(c.chat_line.text)}`:esc(c.summary||NOTE[c.note_status]||'');
 $('#card').innerHTML=`<h2>${esc(c.label)}</h2><p>${line}</p>
 <button type="button" id="more" aria-expanded="${open}">${open?'접기':'더 알아보기'}</button>${more}`;}
$('#lb').onclick=e=>{const li=e.target.closest('li');if(!li)return;cur=li.dataset.id;open=false;card();};
$('#card').onclick=e=>{if(e.target.id==='more'){open=!open;card();}};
projects().then(lb); new EventSource('/api/events').addEventListener('update',()=>{projects();lb();card();});
</script>"""


class State:
    def __init__(self, db, inbox, roles, web, project=None, model=None, any_host=False, llm="off"):
        self.db, self.inbox, self.roles, self.web = db, inbox, roles, web
        self.model, self.any_host, self.llm = model, any_host, llm or "off"
        self.project = norm_project(project)   # --project: 화면이 처음 보여 줄 폴더
        self.version = 0
        self.cond = threading.Condition()
        self.stop = threading.Event()
        self.note_q = queue.Queue()
        self.note_lock = threading.Lock()
        self.note_pending = set()
        self.note_failed = {}      # 개념 → 실패 시각 (NOTE_RETRY 동안 다시 시도하지 않음)
        self.note_error = None     # 마지막 수집 오류 (진단용)
        self.worker_starts = self.worker_closes = 0
        self.lb_cache = {}         # (k, 폴더) → (version, 계산 시각, 결과)
        self.lb_lock = threading.Lock()
        self.study_proc = None     # 모델 작업자 프로세스
        self.wake = threading.Event()

    def study_running(self):
        return self.study_proc is not None and self.study_proc.poll() is None

    def pick_project(self, q):
        """요청의 폴더: project=경로, project=(빈 값)은 전체, 없으면 서버 기본값(--project)"""
        return norm_project(q["project"]) if "project" in q else self.project

    def cached_leaderboard(self, con, k, project=None):
        """순위는 기록이 많으면 수백 ms 걸린다. 새 기록이 있거나 LB_TTL이 지났을 때만 다시 계산한다"""
        with self.lb_lock:
            hit = self.lb_cache.get((k, project))
            if hit and hit[0] == self.version and time.time() - hit[1] < LB_TTL:
                return hit[2]
            v = self.version
            out = leaderboard(con, k=k, project=project)
            self.lb_cache[(k, project)] = (v, time.time(), out)
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


def card_response(st, con, concept, cursor=None, project=None):
    """상태를 카드보다 먼저 읽는다. 반대로 읽으면 그 사이에 정의가 저장됐을 때 'ready'인데 정의가 빈 응답이 나간다.
    이 순서면 최악의 경우 'pending' + 정의가 나가고, 저장 뒤 update 이벤트로 다시 읽으므로 안전하다"""
    status = note_status(st, con, concept)
    return dict(concept_card(con, concept, cursor, project=project), note_status=status)


OPENDICT = "https://opendict.korean.go.kr/search/searchResult?query="
PYPI_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{1,60}")


def choose_sense(senses, field):
    """우리말샘 뜻 고르기: 개념의 분야 꼬리표(field)와 같은 분야의 뜻만. 분야를 모르면 None (추측하지 않는다).
    (0.7.13) 예전에는 '전문 뜻이 하나면 그것'이었는데, 사전 표에는 전문 뜻만 있어서 일상 뜻이 따로 있는 낱말도 하나로 보였다
    (유료 → 『공예』 도자기 약, 레포 → 『경제』 채권 거래, 트리거 → 『체육』 방아쇠)"""
    if not field:
        return None
    same = [s for s in senses if field in s[0]]
    if len(same) == 1:
        return same[0]
    if 2 <= len(same) <= 3:                                 # (0.7.11) 같은 분야의 뜻이 여럿이면 고르지 않고 모두 번호를 붙여 (모듈·포트: 정보·통신 뜻이 둘)
        return [field], " ".join(f"{'①②③'[i]} {d}" for i, (_f, d) in enumerate(same))
    return None


def pypi_info(text):
    """PyPI JSON의 info 부분만. 큰 패키지(torch·pyarrow)는 배포판 목록 때문에 응답이 수 MB라 읽기 상한(400KB)에서 잘린다 →
    맨 앞에 오는 "info" 객체만 떼어 읽는다 (0.7.9, 밤 작업에서 앱 로그로 찾음). 없으면 {}"""
    i = text.find('"info"')
    if i < 0:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, text.index("{", i))
    except (ValueError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def fallback_note(con, cid, label):
    """(0.7.2, 사용자 결정 11-11 '같이보내자') 위키백과·검색에서 정의를 못 찾았을 때만:
    1) 우리말샘 전문 뜻풀이 (분야가 맞는 뜻 하나) 2) 코드 속 이름(judgments.code=1)이면 PyPI 패키지 한 줄 설명.
    출처 링크를 붙이고, 관문(study_api.sourced)은 위키백과만 근거로 세므로 판정은 바뀌지 않는다. 없으면 None"""
    import fields
    import concept_gate as gate
    field = fields.field_of(con, cid, label)
    # (0.7.13) 정보·통신이 아닌 분야 꼬리표는 함께 나온 개념들의 분야 투표라 흔한 낱말에서 엉뚱하게 나올 수 있다(로직 → 역사, 증가 → 경제):
    # 그 분야에서는 일상 뜻 없이 전문 뜻만 있는 낱말일 때만 쓴다
    trusted = field == fields.TECH or (field and gate.lexicon_verdict(label) == "special")
    sense = choose_sense(fields.definitions(label), field) if trusted else None
    if sense:
        flds, d = sense
        return f"{label}: {d}", [{"text": f"{d} (우리말샘 『{'·'.join(flds)}』, 국립국어원, CC BY-SA 2.0 KR)", "url": OPENDICT + urllib.parse.quote(label)}]
    try:
        row = con.execute("SELECT code FROM judgments WHERE concept=?", (cid,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row and row[0] == 1 and PYPI_NAME.fullmatch(label):
        import fetch_sources as fs
        try:
            info = pypi_info(fs._get(f"https://pypi.org/pypi/{urllib.parse.quote(label)}/json"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        s = re.sub(r"\s+", " ", info.get("summary") or "").strip()
        if s and not re.search(r"deprecat|placeholder|reserved|do not use", s, re.I):
            return f"{label}: {s}", [{"text": f"{s} (PyPI 패키지 설명)", "url": f"https://pypi.org/project/{label}/"}]
    return None


def collect_note(con, c, fetcher):
    """개념 하나의 정의 → (정의, 출처). 위키백과·검색(fetcher)에 없거나 그 단계가 오류여도 우리말샘·PyPI(fallback_note)를 먼저 본다.
    (0.7.8) 예전에는 SearXNG가 꺼져 있으면 연결 오류로 끝나 대체 출처까지 가지 못했다 (밤 작업에서 앱 로그로 찾음).
    대체 출처에도 없으면 원래 오류를 그대로 올린다: 저장하지 않고 나중에 다시 시도 (검색이 켜지면 그때 찾는다)"""
    import senses
    mine = senses.picked(con, c)
    if mine and mine[0]:                                  # (0.9.2) 사람이 고른 뜻이 있으면 다시 찾지 않는다 (사람 판단이 앞선다)
        return mine
    forms = [r[0] for r in con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form", (c,))]
    label = forms[0] if forms else c
    err, rejected = None, []
    try:
        try:
            definition, sources = fetcher(label, forms[1:], context_terms(con, c), rejected=rejected)
        except TypeError as e:                            # 다른 뜻 문서 목록을 받지 않는 수집기 (시험용)
            if "rejected" not in str(e):
                raise
            definition, sources = fetcher(label, forms[1:], context_terms(con, c))
    except Exception as e:  # noqa: BLE001 — 아래에서 대체 출처를 본 뒤 다시 올린다
        definition, sources, err = "", [], e
    if rejected:                                          # (0.7.16) 정의로 쓰지 않은 다른 뜻 문서: 관문 근거로만 (검색 단계가 오류여도 남긴다)
        con.execute("REPLACE INTO wiki_names VALUES (?,?,?)", (c, rejected[0]["url"], datetime.now(timezone.utc).isoformat()))
        con.commit()
    if not definition:
        got = fallback_note(con, c, label)
        if got:
            return got
    if err is not None:
        raise err
    return definition, sources


def note_loop(st, fetcher=None):
    """노트 수집 일꾼 1개 (같은 사이트 1초 1번 규칙을 지키려고 한 번에 하나씩). 끝나면 update 이벤트로 알린다"""
    fetcher = fetcher or fetch_note
    con = open_db(st.db)
    while not st.stop.is_set():
        try:
            c = st.note_q.get(timeout=0.2)
        except queue.Empty:
            continue
        pause = 0
        try:
            definition, sources = collect_note(con, c, fetcher)
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
        finally:
            with st.note_lock:
                st.note_pending.discard(c)
            st.bump()
        if pause:                                 # 화면에 결과를 먼저 알린 뒤에 쉰다
            st.stop.wait(pause)
    con.close()


def has_new_lines(con, inbox):
    """분석 프로세스를 깨울 일이 있는지: 파일이 줄었거나, 읽은 위치 뒤에 완성된 줄이 있음 (Kiwi 없이 가볍게)"""
    p = pathlib.Path(inbox).expanduser()
    if not p.exists():
        return False
    size = p.stat().st_size
    off = int(meta_get(con, "offset", 0))
    if inbox_replaced(con, p, size, off):
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
        extra = ["--model", st.model] if st.model else []
        self.proc = subprocess.Popen(
            [sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", "--inbox", str(st.inbox),
             "--db", str(st.db), "--roles", ",".join(sorted(st.roles))] + extra,
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


def worker_main(inbox, db, roles, model=None):
    """--worker: 부모가 'go'를 보낼 때마다 이어 읽기. 부모가 끝나 stdin이 닫히면 같이 끝난다"""
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8")   # 부모와 주고받는 통로. 모델·패키지가 stdout에 뭘 찍어도 섞이지 않게 분리
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    set_model(model)
    con = open_db(db)
    try:
        for _ in sys.stdin:
            try:
                n = ingest(con, inbox, roles)
            except Exception as e:  # noqa: BLE001
                print(f"[경고] 색인 실패: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                n = -1
            print(n, file=proto, flush=True)
    except KeyboardInterrupt:
        pass
    con.close()


def tail_loop(st, interval=1.0, idle=WORKER_IDLE):
    con = open_db(st.db)
    worker, last_work, retry_at, fails = None, 0.0, 0.0, 0
    while not st.stop.is_set():
        try:
            now = time.time()
            if now >= retry_at and has_new_lines(con, st.inbox):
                if worker is None:
                    worker = IndexWorker(st)
                    st.worker_starts += 1
                n = worker.ingest()
                last_work, fails = time.time(), 0
                if n:
                    st.bump()
            if worker is not None and time.time() - last_work >= idle:
                worker.close()
                worker = None
                st.worker_closes += 1
        except Exception as e:  # noqa: BLE001 — 한 번 실패해도 서버는 계속 돈다
            print(f"[경고] 인박스 읽기 실패: {type(e).__name__}: {e}", flush=True)
            fails += 1
            retry_at = time.time() + min(WORKER_BACKOFF, 2 ** (fails - 1))   # 한 번 죽은 것은 바로 복구, 계속 실패하면 천천히
            if worker is not None:
                worker.close()
                worker = None
        st.stop.wait(interval)
    if worker is not None:
        worker.close()
    con.close()


MAX_POST = 256 * 1024          # 붙여넣기 등 요청 본문 상한 (바이트)
WARM_TOP = 50                  # 뒤에서 미리 준비할 상위 개념 수. 나머지는 열 때 준비한다 (개념 하나에 모델 약 12초: 많이 잡으면 GPU를 오래 쓴다)


def study_get(st, con, path, q):
    """공부 화면용 GET. 없는 경로면 None (계약: docs/API.md)"""
    import study_api as api                                # 쓸 때만 불러온다
    project = st.pick_project(q)
    board = lambda c, k, project=None: st.cached_leaderboard(c, k, project)   # noqa: E731 — 순위 계산은 캐시를 쓴다
    if path == "/api/study/today":
        return api.today(con, board, max(1, min(int(q.get("k", 7)), 50)), project)
    if path == "/api/study/concepts":
        view = q.get("view", "show")
        if view not in ("show", "hidden", "all"):
            raise ValueError("view는 show·hidden·all")
        return api.concepts(con, board, view, max(1, min(int(q.get("k", 50)), 5000)), project)
    if path == "/api/study/history":
        return api.history(con, max(1, min(int(q.get("k", 50)), 500)))
    m = re.fullmatch(r"/api/study/concept/([^/]+)/senses", path)
    if m:                                                   # (0.9.2) 뜻이 여러 개인 낱말: 고를 후보 (위키백과 동음이의 문서가 가리키는 문서의 첫 문장)
        import senses
        cid = urllib.parse.unquote(m.group(1))
        if not con.execute("SELECT 1 FROM freq WHERE concept=?", (cid,)).fetchone():
            return {"__status": 404, "error": "없는 개념", "id": cid}
        row = con.execute("SELECT title FROM sense_picks WHERE concept=?", (cid,)).fetchone() if senses.picked(con, cid) is not None else None
        try:
            cands = senses.candidates(con, cid, label_of(con, cid), label_of)
        except OSError:
            return {"senses": [], "picked": row[0] if row else None, "error": "위키백과에 연결하지 못했어요"}
        return {"senses": cands, "picked": row[0] if row else None}
    if path.startswith("/api/study/concept/"):
        cid = urllib.parse.unquote(path[len("/api/study/concept/"):])
        if not con.execute("SELECT 1 FROM freq WHERE concept=?", (cid,)).fetchone():
            return {"__status": 404, "error": "없는 개념", "id": cid}
        if not q.get("cursor"):                             # 기록 더 보기(다음 쪽)는 새로 연 것으로 세지 않는다
            api.record_view(con, cid)
        out = api.detail(con, card_response(st, con, cid, q.get("cursor"), project), cid)
        if out["note"]["status"] == "none" and out["note_status"] != "pending" and st.llm != "off":
            api.enqueue(con, "note", cid, 1)                # 연 개념을 먼저
            st.wake.set()
        return out
    if path == "/api/answers":
        clause = in_project(project, "session") if project else None
        return api.answers_list(con, max(1, min(int(q.get("k", 20)), 100)), project, clause)
    if path.startswith("/api/answers/"):
        got = api.answer_detail(con, urllib.parse.unquote(path[len("/api/answers/"):]))
        return got if got else {"__status": 404, "error": "없는 답변"}
    if path == "/api/health":
        import llm as llm_mod
        return {"llm": {"name": st.llm, "available": llm_mod.make(st.llm).available()}, "jobs": api.job_counts(con), "study_worker": st.study_running(),
                "turns": int(meta_get(con, "turns", 0)), "sessions": con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], "web": bool(st.web)}
    return None


def study_post(st, con, path, body):
    """공부 화면용 POST (기록). 없는 경로면 None"""
    import study_api as api
    if path == "/api/ingest":
        import concept_add
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text가 비어 있습니다")
        source = str(body.get("source") or "paste")[:40]
        session = body.get("session") if isinstance(body.get("session"), str) and body.get("session").strip() else None   # (11-13) 확장: 대화 하나 = 세션 하나
        session = session[:120] if session else None
        q = body.get("question")
        if isinstance(q, str) and q.strip():                # (11-13) 확장: 답변 앞의 내 질문 (분석하지 않고 원문 저장, 질문별 묶음용)
            concept_add.add(q, source, role="user", session=session, inbox=st.inbox)
        return {"added": concept_add.add(text, source, session=session, inbox=st.inbox)}    # 서버가 읽는 인박스에 쓴다
    m = re.fullmatch(r"/api/study/concept/([^/]+)/(progress|feedback)", path)
    if m:
        cid = urllib.parse.unquote(m.group(1))
        if not con.execute("SELECT 1 FROM freq WHERE concept=?", (cid,)).fetchone():
            return {"__status": 404, "error": "없는 개념", "id": cid}
        if m.group(2) == "progress":
            api.set_progress(con, cid, body.get("status"))
        else:
            api.set_feedback(con, cid, body.get("verdict"))
        st.bump()
        return {"ok": True}
    m = re.fullmatch(r"/api/study/concept/([^/]+)/sense", path)
    if m:                                                   # (0.9.2) 사람이 뜻을 고른다: 후보 제목 또는 ''(여기에 없어요)
        import senses
        cid = urllib.parse.unquote(m.group(1))
        if not con.execute("SELECT 1 FROM freq WHERE concept=?", (cid,)).fetchone():
            return {"__status": 404, "error": "없는 개념", "id": cid}
        title = body.get("title")
        if not isinstance(title, str):
            raise ValueError("title이 필요합니다 (모르면 빈 문자열)")
        definition, sources = senses.pick(con, cid, title.strip())
        if definition:
            save_note(con, cid, definition, sources)
        st.bump()
        return {"ok": True, "definition": definition}
    m = re.fullmatch(r"/api/answers/([^/]+)/summary", path)
    if m:
        aid = urllib.parse.unquote(m.group(1))
        if not con.execute("SELECT 1 FROM answers WHERE id=?", (aid,)).fetchone():
            return {"__status": 404, "error": "없는 답변"}
        if st.llm == "off":
            return {"queued": False, "reason": "LLM이 꺼져 있습니다"}
        api.enqueue(con, "summary", aid, 0)
        st.wake.set()
        return {"queued": True}
    return None


CHECK_TOP = 30                 # 한 번에 위키백과 문서를 확인할 낱말 수 (관문의 두 번째 근거). 수집 일꾼이 하나씩, 사이트 규칙대로 천천히


def warm_targets(con, ai=True):
    """뒤에서 준비할 것: 사전으로 못 가른 낱말 판정 → 두 번째 근거(위키백과 문서) 확인 → 상위 개념의 정의·노트 (작업자가 하나씩 처리).
    → (정의·노트까지 준비할 것, 정의만 찾을 나머지 공부 목록).
    분야 사전에 일상 뜻이 있는 낱말은 묻지도 찾지도 않는다 (어차피 공부 목록에 들어가지 않는다)"""
    import concept_gate as gate
    import study_api as api
    check = []
    for x in leaderboard(con, k=100000)["items"]:
        rule, lex = api.rule_of(con, x["id"], x["label"]), gate.lexicon_verdict(x["label"])
        if rule in ("unknown", "likely") and gate.ASCII_FORM.fullmatch(x["label"].strip()):     # 0.7.0: 코드로 쓰인 영어 이름인지 한 번만 본다 (LLM 없음)
            got = con.execute("SELECT code FROM judgments WHERE concept=?", (x["id"],)).fetchone()
            if not got or got[0] is None:
                texts = [r[0] for r in con.execute("SELECT text FROM answers WHERE instr(text, ?) > 0 LIMIT 50", (x["label"],))]
                con.execute("INSERT INTO judgments (concept, code, updated) VALUES (?,?,?) ON CONFLICT(concept) DO UPDATE SET code=excluded.code",
                            (x["id"], int(gate.code_name(x["label"], texts)), api.now()))
                con.commit()
        if rule == "unknown" and lex in ("general", "mixed") and not ai:
            continue
        row = con.execute("SELECT llm, user, everyday FROM judgments WHERE concept=?", (x["id"],)).fetchone()
        if row and row[1]:
            if ai and row[0] is None and (rule == "likely" or (rule == "unknown" and lex != "general")):
                api.enqueue(con, "judge", x["id"], 9, redo=True)     # (0.7.7) 사용자 판단이 있어도 측정용 판정은 둔다 (화면은 사용자 판단이 앞선다, verify의 '관문이 맞혔나')
            continue
        if ai and rule == "likely" or (ai and rule == "unknown" and lex != "general"):
            if not (row and row[0] is not None):
                api.enqueue(con, "judge", x["id"], 8, redo=True)      # 판정이 없을 때만 오므로 예전 완료 기록이 있어도 다시
        if ai and rule == "unknown" and lex == "special" and row and row[0] == 0 and row[2] is None and api.sourced(con, x["id"]):
            api.enqueue(con, "everyday", x["id"], 9, redo=True)        # '더 보기'에 살릴지 묻는 두 번째 질문 (gate.rescue)
        wants_source = rule == "unknown" and (lex == "special" or (ai and lex in (None, "mixed") and bool(row and row[0])))
        if wants_source and len(check) < CHECK_TOP and not con.execute("SELECT 1 FROM notes WHERE concept=?", (x["id"],)).fetchone()                 and not con.execute("SELECT 1 FROM wiki_names WHERE concept=?", (x["id"],)).fetchone():   # (0.7.16) 근거를 얻었으면 칸을 비운다 (검색이 꺼져 저장 못 해도)
            check.append(x["id"])
    shown = [x["id"] for x in api.concepts(con, leaderboard, "show", 100000, origin=False)["items"]]
    return check + shown[:WARM_TOP], shown[WARM_TOP:]     # (0.6.6) 상위 WARM_TOP 밖의 공부 목록도 정의는 찾는다. 예전에는 상위 50개만 예약해 설명이 붙은 비율이 0.396이었다


def study_loop(st, interval=5.0):
    """모델 작업자 관리: 할 일이 있을 때만 별도 프로세스를 띄운다. LLM이 없거나 작업자가 죽어도 서버는 그대로"""
    con = open_db(st.db)
    ai = st.llm != "off"                                    # AI가 꺼져 있으면 정의 확인만 하고 모델 작업자는 띄우지 않는다
    clf_on = ai and bool(os.environ.get("CONCEPT_CHART_CLF"))   # (0.8.0) 개념 분류기 (작업자가 ml/concept_clf.py를 따로 실행, 기본은 끔)
    if not clf_on:                                          # 끄면 예전 관문으로: 남은 점수는 기준점이 없으면 쓰지 않는다 (study_api.clf_of)
        con.execute("DELETE FROM settings WHERE k='clf_threshold'")
        con.commit()
    last_warm, backoff_until, seen_version = 0.0, 0.0, -1
    while not st.stop.is_set():
        try:
            now = time.time()
            if now - last_warm > 120 or (st.version != seen_version and now - last_warm > 15):   # 새 기록이 오면 곧바로 준비한다
                last_warm, seen_version = now, st.version
                import study_api as api
                top, rest = warm_targets(con, ai)
                if clf_on:
                    api.enqueue(con, "score", "all", 7, redo=True)    # 바뀐 낱말만 점수를 다시 매긴다 (없으면 금방 끝난다)
                for cid in top:
                    note_status(st, con, cid)               # 정의 수집 예약 (이미 있으면 그대로)
                    has_def = con.execute("SELECT 1 FROM notes WHERE concept=? AND definition<>''", (cid,)).fetchone()
                    if ai and has_def and not con.execute("SELECT 1 FROM study_notes WHERE concept=?", (cid,)).fetchone():
                        api.enqueue(con, "note", cid, 5, redo=True)     # 노트가 없을 때만 오므로 예전 완료 기록이 있어도 다시
                for cid in rest:                            # 나머지 공부 목록: 정의만 (수집 일꾼이 하나씩 천천히, 모델은 쓰지 않는다)
                    note_status(st, con, cid)
            if not ai:
                st.wake.wait(interval)
                st.wake.clear()
                continue
            pending = con.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
            if pending and st.study_proc is None and now >= backoff_until:
                st.study_proc = subprocess.Popen([sys.executable, str(pathlib.Path(__file__).with_name("study_worker.py")), "--db", str(pathlib.Path(st.db).expanduser()), "--llm", st.llm],
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if st.study_proc is not None and st.study_proc.poll() is not None:
                failed = st.study_proc.returncode != 0
                st.study_proc = None
                st.bump()
                if failed:
                    backoff_until = time.time() + 120       # LLM이 꺼져 있으면 2분 뒤 다시 본다
        except Exception as e:  # noqa: BLE001 — 모델 쪽 문제로 서버를 멈추지 않는다
            print(f"[경고] 모델 작업 관리 실패: {type(e).__name__}: {e}", flush=True)
        st.wake.wait(interval)
        st.wake.clear()
    if st.study_proc is not None:
        st.study_proc.terminate()
    con.close()


def make_handler(st):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            """기록 요청. 다른 사이트의 요청을 막으려고 Host·Origin·Content-Type을 모두 본다"""
            if not self.host_ok():
                return self.send(403, {"error": "이 PC 안에서만 접속할 수 있습니다"})
            origin = self.headers.get("Origin")
            ou = urllib.parse.urlparse(origin or "")
            ext_ok = ou.scheme in ("chrome-extension", "extension") and ou.hostname in EXTENSION_IDS and urllib.parse.urlparse(self.path).path == "/api/ingest"
            if origin and not st.any_host and (ou.hostname or "") not in LOCAL_HOSTS and not ext_ok:
                return self.send(403, {"error": "다른 사이트에서는 쓸 수 없습니다"})
            if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                return self.send(415, {"error": "JSON으로 보내 주세요"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self.send(400, {"error": "잘못된 길이"})
            if n > MAX_POST:
                return self.send(413, {"error": "글이 너무 깁니다"})
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                if not isinstance(body, dict):
                    raise ValueError("JSON 객체가 아닙니다")
            except (ValueError, UnicodeDecodeError) as e:
                return self.send(400, {"error": str(e)})
            con = open_db(st.db)
            try:
                got = study_post(st, con, urllib.parse.urlparse(self.path).path, body)
                if got is None:
                    return self.send(404, {"error": "없는 API"})
                return self.send(got.pop("__status", 200), got)
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            finally:
                con.close()

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

        def host_ok(self):
            """DNS 리바인딩 방어: 다른 사이트가 자기 주소를 127.0.0.1로 돌려 내 대화 개념을 읽지 못하게 한다"""
            if st.any_host:
                return True
            host = (self.headers.get("Host") or "").strip().lower()
            host = host[1:].split("]")[0] if host.startswith("[") else host.split(":")[0]
            return host in LOCAL_HOSTS

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, {"error": "이 PC 안에서만 접속할 수 있습니다"})
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query, keep_blank_values=True).items()}
            path = u.path
            if path == "/api/events":
                return self.events()
            if path.startswith("/api/"):
                con = open_db(st.db)
                try:
                    if path == "/api/leaderboard":
                        return self.send(200, st.cached_leaderboard(con, max(1, min(int(q.get("k", 10)), 100)), st.pick_project(q)))
                    if path == "/api/projects":
                        return self.send(200, dict(projects(con), default=st.project))
                    if path.startswith("/api/concept/"):
                        cid = urllib.parse.unquote(path[len("/api/concept/"):])
                        if not con.execute("SELECT 1 FROM freq WHERE concept=?", (cid,)).fetchone():
                            return self.send(404, {"error": "없는 개념", "id": cid})
                        return self.send(200, card_response(st, con, cid, q.get("cursor"), st.pick_project(q)))
                    if path == "/api/status":
                        return self.send(200, {"inbox": str(pathlib.Path(st.inbox).expanduser()),
                                               "offset": int(meta_get(con, "offset", 0)),
                                               "turns": int(meta_get(con, "turns", 0)),
                                               "sessions": con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                                               "version": st.version})
                    got = study_get(st, con, path, q)
                    if got is not None:
                        return self.send(got.pop("__status", 200), got)
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


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"   # Windows에서 켜 두면 같은 포트에 서버 두 개가 조용히 함께 뜬다


def make_server(st, host="127.0.0.1", port=8765):
    return LocalServer((host, port), make_handler(st))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inbox", default=DEFAULT_INBOX)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--roles", default="assistant,subagent", help="색인할 역할 (쉼표로)")
    ap.add_argument("--web", default=None, help="화면 폴더 (index.html). 없으면 내장 간이 화면")
    ap.add_argument("--searx", default=DEFAULT_SEARX, help="위키백과에 없는 개념을 찾을 SearXNG 주소. 안 쓰려면 off")
    ap.add_argument("--project", default=None, help="이 폴더(하위 포함)의 대화만 보기. 화면에서 다른 폴더로 바꿀 수 있다")
    ap.add_argument("--model", default=None, help="개념 묶기에 쓸 모델 (모듈:함수). 기본은 끔, 고장 나면 규칙으로 계속")
    ap.add_argument("--llm", default="off", help="공부 노트·요약에 쓸 로컬 LLM (예: ollama:qwen3:4b). 기본은 끔, 끄면 출처 문장만 보여 준다")
    ap.add_argument("--once", action="store_true", help="한 번 색인하고 순위를 출력한 뒤 끝")
    ap.add_argument("--rebuild", action="store_true", help="색인을 지우고 처음부터 다시")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)   # 서버가 띄우는 분석 프로세스
    a = ap.parse_args()
    roles = {r.strip() for r in a.roles.split(",") if r.strip()}
    if a.worker:
        return worker_main(a.inbox, a.db, roles, a.model)
    if not importlib.util.find_spec("kiwipiepy"):
        sys.exit(f"kiwipiepy가 없습니다 (지금 Python: {sys.executable}).\n"
                 "개발 환경을 켠 뒤 다시 실행하세요. Windows: .venv\\Scripts\\activate / Mac: source .venv/bin/activate (SETUP.md)")
    project = norm_project(pathlib.Path(a.project).expanduser().resolve()) if a.project else None
    con = open_db(a.db)
    if a.rebuild or (meta_get(con, "model") or "") != (a.model or ""):   # 모델을 바꾸면 개념 묶음이 달라지므로 색인을 다시 만든다 (정의는 남김)
        reset(con)
    meta_set(con, "model", a.model or "")
    con.commit()
    if a.once:
        set_model(a.model)
        t0 = time.time()
        n = ingest(con, a.inbox, roles)
        print(f"색인: 새 턴 {n}개 ({time.time() - t0:.1f}초) · 인박스 {pathlib.Path(a.inbox).expanduser()}", flush=True)
        board = leaderboard(con, project=project)
        if project:
            print(f"폴더 {project} · 세션 {board['n_sessions']}개", flush=True)
            if not board["n_sessions"]:
                known = [x["path"] for x in projects(con)["items"]]
                print("이 폴더의 대화가 없습니다. 기록된 폴더: " + (", ".join(known) or "(없음)"), flush=True)
        for x in board["items"]:
            print(f"{x['rank']:>2}. {x['label']}  {x['score']}  ({x['sessions']}세션) {x['badge']}")
        return
    con.close()
    print(f"인박스 {pathlib.Path(a.inbox).expanduser()} 을 뒤에서 색인합니다", flush=True)
    st = State(a.db, a.inbox, roles, a.web, project, a.model, any_host=a.host not in LOCAL_HOSTS, llm=a.llm)
    try:
        srv = make_server(st, a.host, a.port)
    except OSError:
        sys.exit(f"포트 {a.port}을 이미 쓰고 있습니다. 서버가 켜져 있다면 그대로 http://localhost:{a.port} 를 여세요. "
                 "다른 포트로 켜려면 --port 8766")
    if project:
        print(f"폴더 {project} 의 대화를 먼저 보여 줍니다 (화면에서 바꿀 수 있음)", flush=True)
    threading.Thread(target=tail_loop, args=(st,), daemon=True).start()
    searx = None if a.searx.lower() == "off" else a.searx
    threading.Thread(target=note_loop, args=(st, lambda t, al=(), ctx=(), rejected=None: fetch_note(t, al, searx, ctx, rejected)), daemon=True).start()
    import study_api
    study_api.AI = st.llm != "off"                         # AI가 없으면 관문은 규칙·사전·위키백과만으로 판정한다
    threading.Thread(target=study_loop, args=(st,), daemon=True).start()
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
