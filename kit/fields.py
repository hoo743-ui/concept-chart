# -*- coding: utf-8 -*-
"""fields.py : 개념 카드의 분야 꼬리표 (물리·법률·정보·통신 …). 화면에 보여 주기만 하고, 공부 목록 판정에는 쓰지 않는다.

근거는 분야 사전(kit/data/lexicon/lexicon.sqlite의 field 표 = 우리말샘 전문 분야)뿐이다. 근거가 없으면 꼬리표를 달지 않는다.
- 기술 용어집(kit/data/tech_terms.txt)에 있으면 '정보·통신' (Docker, GitHub, 파인튜닝).
- 그 밖에는 사전의 분야 중 함께 나온 개념들과 가장 많이 겹치는 분야 하나. 분야가 하나뿐이어도 겹치는 개념이 MIN_VOTES개 있어야 한다
  (사전의 전문 뜻이 대화의 뜻과 다를 수 있다: 체크포인트 = 체육). 하나로 정해지지 않으면 None.
"""
import collections
import os
import pathlib
import sqlite3
import threading

import concept_gate as gate

TECH = "정보·통신"
MIN_VOTES = 2          # 같은 분야인 이웃 개념이 이만큼 있어야 단다 (1이면 대시보드 = 기계, 라벨 = 경제가 붙었다. 틀린 꼬리표보다 없는 편이 낫다)
_con = None
_lock = threading.Lock()
_cache = {}


def _open():
    global _con
    if _con is None:
        folder = pathlib.Path(os.environ.get("CONCEPT_CHART_LEXICON") or gate.LEXICON_DIR)
        path = folder / "lexicon.sqlite"
        _con = False
        if path.exists():
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='field'").fetchone():   # 예전에 만든 사전에는 field 표가 없다: python dev.py lexicon
                _con = con
    return _con or None


def fields_of(form):
    """사전에 적힌 분야들 (없으면 [])"""
    k = gate.key(form).replace("^", "")
    if k not in _cache:
        con = _open()
        row = None
        if con:
            with _lock:
                row = con.execute("SELECT fields FROM field WHERE key=?", (k,)).fetchone()
        if len(_cache) > 20000:
            _cache.clear()
        _cache[k] = row[0].split(";") if row and row[0] else []
    return _cache[k]


def definitions(form):
    """(0.7.2) 우리말샘 전문 뜻풀이 [(분야들, 뜻풀이)]. 사전에 defs 표가 없으면(예전에 만든 사전) []: python dev.py lexicon"""
    con = _open()
    if not con:
        return []
    with _lock:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='defs'").fetchone():
            return []
        rows = con.execute("SELECT fields, def FROM defs WHERE key=?", (gate.key(form).replace("^", ""),)).fetchall()
    return [(f.split(";"), d) for f, d in rows if d]


def field_of(con, cid, label):
    """개념 하나의 분야 꼬리표 또는 None. con = 서버 DB (함께 나온 개념을 본다)"""
    if gate.key(label) in gate.terms():                     # 기술 용어집에 있으면 사전의 다른 분야(파인튜닝 = 천연자원)보다 이것
        return TECH
    fs = fields_of(label)
    if not fs:
        return None
    votes = collections.Counter()                           # 분야가 하나여도 함께 나온 개념이 같은 분야일 때만 (체크포인트 = 체육 같은 다른 뜻을 거른다)
    for (b,) in con.execute("SELECT b FROM cooc WHERE a=? ORDER BY n DESC, b LIMIT 20", (cid,)):
        row = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (b,)).fetchone()
        if row:
            votes.update(f for f in fields_of(row[0]) if f in fs)
    top = votes.most_common(2)
    if top and top[0][1] >= MIN_VOTES and (len(top) == 1 or top[0][1] > top[1][1]):
        return top[0][0]
    return None
