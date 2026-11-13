# -*- coding: utf-8 -*-
"""senses.py : 뜻이 여러 개인 낱말의 뜻 고르기 (0.9.2, 11-14 사용자 결정 '뜻 고르기 화면').

위키백과에서 동음이의 문서로 나오는 낱말(DB·PC·배포)은 정의를 비워 둔다 (틀린 뜻을 붙이지 않으려고).
자동으로 고르는 실험은 8개 중 4개가 틀렸다 (experiments/2026-11-14-disamb). 그래서 사람이 고른다:
- 후보: 동음이의 문서가 가리키는 문서들의 첫 문장 (한국어 위키백과 덤프 색인). 내 대화에서 함께 나온 개념이 많이 든 후보를 앞에
- 고른 뜻은 출처 링크와 함께 노트 정의가 되고, sense_picks에 남아 정의를 다시 찾을 때도 그대로 쓴다 (사람 판단이 앞선다)
- '여기에 없어요'도 남긴다 (다시 묻지 않는다). 고른 기록은 나중에 뜻 고르기 모델의 정답 데이터가 될 수 있다
밖으로 나가는 것은 낱말 이름뿐 (위키백과 API: 동음이의 문서의 링크 목록).
"""
import json
import urllib.parse
from datetime import datetime, timezone

CTX_K = 12
MAX_CANDS = 8


def ensure(con):
    con.execute("CREATE TABLE IF NOT EXISTS sense_picks (concept TEXT PRIMARY KEY, title TEXT, definition TEXT, sources TEXT, updated TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS sense_cands (concept TEXT PRIMARY KEY, cands TEXT, updated TEXT)")


def _now():
    return datetime.now(timezone.utc).isoformat()


def picked(con, cid):
    """사람이 고른 뜻 → (정의, 출처) | ('', []) '여기에 없어요' | None 고른 적 없음"""
    ensure(con)
    row = con.execute("SELECT title, definition, sources FROM sense_picks WHERE concept=?", (cid,)).fetchone()
    if not row:
        return None
    return (row[1] or "", json.loads(row[2] or "[]")) if row[0] else ("", [])


def _context(con, cid, label_of):
    import concept_gate as gate
    out = []
    for (b,) in con.execute("SELECT b FROM cooc WHERE a=? ORDER BY n DESC, b LIMIT 80", (cid,)):
        label = label_of(con, b)
        if len(label) < 2 or gate.lexicon_verdict(label) in ("general", "mixed") or label in gate.GENERAL:
            continue
        out.append(label)
        if len(out) == CTX_K:
            break
    return out


def _links(title):
    import fetch_sources as fs
    q = urllib.parse.quote(title)
    j = json.loads(fs._get(f"https://ko.wikipedia.org/w/api.php?action=query&prop=links&titles={q}&plnamespace=0&pllimit=200&redirects=1&format=json"))
    out = []
    for p in j.get("query", {}).get("pages", {}).values():
        out += [x["title"] for x in p.get("links", [])]
    return out


def candidates(con, cid, label, label_of, links=None):
    """→ 후보 [{title, text, url}] (동음이의 문서가 아니거나 색인이 없으면 []). 한 번 만든 후보는 저장해 두고 쓴다.
    links: 시험용 (위키백과 API 대신)"""
    ensure(con)
    row = con.execute("SELECT cands FROM sense_cands WHERE concept=?", (cid,)).fetchone()
    if row:
        return json.loads(row[0])
    import fetch_sources as fs
    wiki = fs.local_wiki()
    page = fs._local_page(wiki, label) if wiki is not None else None
    if not page or not page[2]:
        return []
    ctx = [c.lower() for c in _context(con, cid, label_of)]
    out, seen = [], set()
    for t in (links or _links)(page[0]):
        p = fs._local_page(wiki, t)
        if not p or p[2] or not p[1] or p[0] in seen:
            continue
        seen.add(p[0])
        sents = fs.split_sents(fs.tidy(p[1]))
        if not sents:
            continue
        hay = (p[0] + " " + p[1][:500]).lower()
        out.append({"title": p[0], "text": sents[0], "url": "https://ko.wikipedia.org/wiki/" + urllib.parse.quote(p[0].replace(" ", "_")),
                    "score": sum(1 for c in ctx if c in hay) + (3 if label.lower() in hay else 0)})   # 문서가 그 낱말을 직접 적으면('데이터베이스(DB)') 앞으로
    out.sort(key=lambda c: -c["score"])                      # 안정 정렬: 점수가 같으면 위키백과 목록 순서
    out = [{k: c[k] for k in ("title", "text", "url")} for c in out[:MAX_CANDS]]
    con.execute("REPLACE INTO sense_cands VALUES (?,?,?)", (cid, json.dumps(out, ensure_ascii=False), _now()))
    con.commit()
    return out


def pick(con, cid, title):
    """후보 중 하나(title) 또는 '' (여기에 없어요) → (정의, 출처). 후보에 없는 제목은 받지 않는다 (지어낸 뜻이 들어오지 않게)"""
    ensure(con)
    if title:
        row = con.execute("SELECT cands FROM sense_cands WHERE concept=?", (cid,)).fetchone()
        got = next((c for c in json.loads(row[0]) if c["title"] == title), None) if row else None
        if not got:
            raise ValueError("후보에 없는 뜻이에요")
        definition, sources = got["text"], [{"text": got["text"], "url": got["url"]}]
    else:
        definition, sources = "", []
    con.execute("REPLACE INTO sense_picks VALUES (?,?,?,?,?)", (cid, title or "", definition, json.dumps(sources, ensure_ascii=False), _now()))
    con.commit()
    return definition, sources
