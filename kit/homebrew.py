# -*- coding: utf-8 -*-
"""homebrew.py : 내 대화에서 Homebrew로 설치한 도구 이름의 근거·설명 (11-14 사용자 결정 '대화 속 설치 명령이 있을 때만').

영어 도구 이름(Colima·Termius)은 이름이 맞는 위키백과 문서가 없거나 다른 뜻(콜리마주)이라 근거를 못 얻었다.
Homebrew 패키지·앱 설명(formulae.brew.sh, BSD-2-Clause)은 이름만 맞추면 절반 가까이 다른 뜻이었다(Mac → 오디오 코덱,
ACK → 검색 도구; experiments/2026-11-14-tool-names). 그래서 내 질문·답변에 `brew install 이름`처럼 Homebrew로 쓴 흔적이 있는
낱말만 맞춘다: 그 대화에서는 그 도구라는 뜻이 정해져 있다.
- evidence(con, label) → {"kind", "name", "desc", "url"} | None
- 사전 파일이 없으면(lexicons/homebrew.py를 돌리지 않은 PC) 항상 None → 예전과 같다
밖으로 나가는 것은 없다 (이 PC 안 사전과 DB만 읽는다).
"""
import os
import pathlib
import re
import sqlite3

LEXICON_DIR = pathlib.Path(__file__).resolve().parent / "data" / "lexicon"


def db_path():
    """lexicons/homebrew.py가 만든 사전. 분야 사전과 같은 폴더 (환경 변수 CONCEPT_CHART_LEXICON이 있으면 그 폴더: 시험은 사전 없이)"""
    return pathlib.Path(os.environ.get("CONCEPT_CHART_LEXICON") or LEXICON_DIR) / "homebrew.sqlite"


# brew install / reinstall / upgrade / info 뒤의 이름들 (--cask 같은 옵션은 건너뛴다). 줄·명령 구분(; & |)에서 끊는다
CMD = re.compile(r"\bbrew\s+(?:install|reinstall|upgrade|info|uninstall)\s+([^\n;&|`]+)", re.I)
NAME = re.compile(r"^[a-z0-9][a-z0-9@+._\-]*$")
_cache = {"key": None, "names": set()}


def _open():
    db = db_path()
    if not db.is_file():
        return None
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def names_in(text):
    """글 속 brew 명령에 나온 이름들 (소문자). 'brew install --cask termius colima' → {'termius', 'colima'}"""
    out = set()
    for m in CMD.finditer(text or ""):
        for tok in m.group(1).split():
            tok = tok.strip().strip("'\"").lower()
            if tok.startswith("-"):
                continue
            tok = tok.rsplit("/", 1)[-1]                   # homebrew/cask/termius 같은 전체 이름
            if NAME.match(tok):
                out.add(tok)
    return out


def installed(con):
    """내 질문·답변에 나온 brew 명령의 이름 전체. 새 기록이 오면 다시 센다 (답변·질문 수와 마지막 시각으로 확인)"""
    try:
        key = (con.execute("PRAGMA database_list").fetchone()[2], id(con)) + tuple(con.execute("SELECT (SELECT COUNT(*) FROM answers), (SELECT MAX(ts) FROM answers), (SELECT COUNT(*) FROM questions)").fetchone())   # DB가 달라도 섞이지 않게
    except sqlite3.OperationalError:
        return set()
    if _cache["key"] == key:
        return _cache["names"]
    names = set()
    for (t,) in con.execute("SELECT text FROM answers WHERE instr(lower(text), 'brew ') > 0"):
        names |= names_in(t)
    for (t,) in con.execute("SELECT text FROM questions WHERE instr(lower(text), 'brew ') > 0"):
        names |= names_in(t)
    _cache.update(key=key, names=names)
    return names


def evidence(con, label):
    """이 낱말을 내 대화에서 Homebrew로 설치했고, Homebrew 사전에 설명이 있으면 그 설명"""
    k = (label or "").strip().lower()
    if not k or not NAME.match(k) or k not in installed(con):
        return None
    lex = _open()
    if lex is None:
        return None
    try:
        row = lex.execute("SELECT kind, name, desc FROM brew WHERE key=?", (k,)).fetchone()
    finally:
        lex.close()
    if not row or not row[2]:
        return None
    kind, name, desc = row
    return {"kind": kind, "name": name, "desc": desc, "url": f"https://formulae.brew.sh/{kind}/{name}"}
