# -*- coding: utf-8 -*-
"""실험 (11-13, 채택 안 함 — 측정만): sense_title.py 규칙 B에 걸린 위키백과 설명을 (가) '숨기고 다른 출처로 넘어가기'로 처리하면
화면에 무엇이 남는가.

걸린 개념마다:
  1) 관문: 위키백과 문서가 두 번째 근거였다면 빠지므로 공부 목록에 남는가 (study_api.sourced를 거짓으로 두고 gate_of 다시)
  2) 대체 설명: serve.fallback_note의 우리말샘 단계 (로컬 사전만, PyPI·SearXNG는 네트워크라 이번에는 돌리지 않고 'PyPI 후보'로만 센다)
  3) 그것도 없으면 내 대화 문장(serve.chat_line)이 있는가

    python experiments/2026-11-10-general-gate/sense_fallback.py      (실제 DB 읽기 전용, 네트워크 없음)
"""
import collections
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(HERE))
import concept_gate as gate  # noqa: E402
import fields  # noqa: E402
import serve  # noqa: E402
import study_api  # noqa: E402
import study_worker as w  # noqa: E402
from sense_title import DB, LEX, OK, WRONG, suspicious, wiki_title  # noqa: E402

import json  # noqa: E402


def main():
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    lex = sqlite3.connect(f"file:{LEX.as_posix()}?mode=ro", uri=True)
    flagged = []
    for (cid,) in con.execute("SELECT DISTINCT concept FROM forms").fetchall():
        top = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()
        label = top[0] if top else cid
        if not study_api.gate_of(con, cid, label)["show"] or not w.source_of(con, cid):
            continue
        src = json.loads(con.execute("SELECT sources FROM notes WHERE concept=?", (cid,)).fetchone()[0] or "[]")
        title = wiki_title(src[0].get("url", "")) if src else None
        if title and suspicious(lex, label, title):
            flagged.append((cid, label, title))

    real_sourced = study_api.sourced
    hidden = set()
    study_api.sourced = lambda c, i: False if i in hidden else real_sourced(c, i)
    out = collections.defaultdict(list)
    for cid, label, title in flagged:
        hidden.add(cid)
        stays = study_api.gate_of(con, cid, label)["show"]
        field = fields.field_of(con, cid, label)
        trusted = field == fields.TECH or (field and gate.lexicon_verdict(label) == "special")
        sense = serve.choose_sense(fields.definitions(label), field) if trusted else None
        code = con.execute("SELECT code FROM judgments WHERE concept=?", (cid,)).fetchone()
        pypi = bool(code and code[0] == 1 and serve.PYPI_NAME.fullmatch(label))
        chat = serve.chat_line(con, cid) is not None
        tag = "틀린뜻" if label in WRONG else "맞는뜻" if label in OK else "애매"
        if not stays:
            kind = "공부 목록에서 빠짐"
        elif sense:
            kind = "우리말샘 설명"
        elif pypi:
            kind = "PyPI 후보 (네트워크라 미확인)"
        elif chat:
            kind = "내 대화 문장"
        else:
            kind = "찾지 못했어요"
        out[kind].append(f"{label}({tag})" + (f"→『{'·'.join(sense[0])}』{sense[1][:30]}" if kind == "우리말샘 설명" else ""))
    study_api.sourced = real_sourced

    print(f"규칙 B에 걸린 개념 {len(flagged)}개를 (가)로 처리하면:")
    for kind in ["공부 목록에서 빠짐", "우리말샘 설명", "PyPI 후보 (네트워크라 미확인)", "내 대화 문장", "찾지 못했어요"]:
        items = out.get(kind, [])
        print(f"\n[{kind}] {len(items)}개")
        if items:
            print("  " + ", ".join(items))
        c = collections.Counter(s.split("(")[1].split(")")[0] for s in items)
        print(f"  틀린뜻 {c['틀린뜻']} · 맞는뜻 {c['맞는뜻']} · 애매 {c['애매']}")


if __name__ == "__main__":
    main()
