# concept_store.py : 개념 클릭 응답을 토큰 0개로 만드는 로컬 색인 (SQLite)
# 인박스를 읽을 때 '개념이 나온 문장'과 '같이 나온 개념'만 색인해 두고,
# 클릭하면 정의 1줄 + 관련 개념 3개 + 기록 3개만 돌려준다 (더 보기는 커서로 다음 3개).
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS mentions (concept TEXT, ts TEXT, session TEXT, role TEXT, snippet TEXT);
CREATE INDEX IF NOT EXISTS ix_m ON mentions (concept, ts DESC);
CREATE TABLE IF NOT EXISTS cooc (a TEXT, b TEXT, n INTEGER, PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS freq (concept TEXT PRIMARY KEY, n INTEGER);
CREATE TABLE IF NOT EXISTS notes (concept TEXT PRIMARY KEY, definition TEXT, sources TEXT, updated TEXT);
"""


def open_store(path="concept_store.sqlite"):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def index_turn(con, turn, sent_concepts):
    """turn: 인박스 한 줄(dict), sent_concepts: [(문장, {개념...}), ...] — 파이프라인 T4 결과"""
    seen = set()
    for sent, cs in sent_concepts:
        for c in cs:
            con.execute("INSERT INTO mentions VALUES (?,?,?,?,?)",
                        (c, turn["ts"], turn["session_id"], turn["role"], sent[:160]))
        seen |= set(cs)
    for c in seen:
        con.execute("INSERT INTO freq VALUES (?,1) ON CONFLICT(concept) DO UPDATE SET n=n+1", (c,))
        for d in seen:
            if c != d:
                con.execute("INSERT INTO cooc VALUES (?,?,1) ON CONFLICT(a,b) DO UPDATE SET n=n+1", (c, d))
    con.commit()


def concept_card(con, concept, cursor=None, k=3):
    """클릭 응답: LLM 호출 없이 1~2KB JSON"""
    note = con.execute("SELECT definition, sources FROM notes WHERE concept=?", (concept,)).fetchone()
    related = con.execute(
        """SELECT b, c.n * 1.0 / ((SELECT n FROM freq WHERE concept=?) * (SELECT n FROM freq WHERE concept=b)) AS s
           FROM cooc c WHERE a=? ORDER BY s DESC, c.n DESC LIMIT ?""", (concept, concept, k)).fetchall()
    q = "SELECT ts, role, snippet, rowid FROM mentions WHERE concept=?"
    args = [concept]
    if cursor:                                            # 커서 = "시각|rowid" (같은 시각 기록도 빠짐없이)
        ts, rid = cursor.rsplit("|", 1)
        q += " AND (ts < ? OR (ts = ? AND rowid < ?))"
        args += [ts, ts, int(rid)]
    rows = con.execute(q + " ORDER BY ts DESC, rowid DESC LIMIT ?", args + [k]).fetchall()
    return {"concept": concept,
            "definition": note[0] if note else None,
            "sources": note[1] if note else None,
            "related": [r[0] for r in related],
            "records": [{"ts": r[0], "role": r[1], "snippet": r[2]} for r in rows],
            "next_cursor": "%s|%d" % (rows[-1][0], rows[-1][3]) if len(rows) == k else None}
