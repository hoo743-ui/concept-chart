# -*- coding: utf-8 -*-
"""study_api.py : 공부 화면용 조회·기록 (순수 함수, HTTP·화면·모델을 모른다). 계약은 docs/API.md.

보여 줄지는 concept_gate가, 문장이 믿을 만한지는 study_worker의 근거 대조가 정한다. 여기서는 저장된 판정을 읽어 합칠 뿐이다.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

import concept_gate as gate

STATUSES = {"known", "review", "new"}
VERDICTS = {"concept", "not_concept", "clear"}


def now():
    return datetime.now(timezone.utc).isoformat()


def answer_id(session, ts):
    return hashlib.sha1(f"{session}|{ts}".encode("utf-8")).hexdigest()[:16]


def gate_of(con, cid, label):
    row = con.execute("SELECT llm, user FROM judgments WHERE concept=?", (cid,)).fetchone()
    llm, user = (row[0], row[1]) if row else (None, None)
    rule = gate.rule_verdict(label)
    if user in ("concept", "not_concept"):
        return {"show": user == "concept", "candidate": False, "by": "user", "rule": rule}
    verdict = gate.final(rule, None if llm is None else bool(llm))
    by = "rule" if rule in ("accept", "reject") else "llm" if llm is not None else "terms" if rule == "likely" else "unjudged"
    return {"show": verdict == "show", "candidate": verdict == "candidate", "by": by, "rule": rule}


def progress_of(con, cid):
    row = con.execute("SELECT status FROM progress WHERE concept=?", (cid,)).fetchone()
    return row[0] if row else "new"


def note_of(con, cid):
    row = con.execute("SELECT body, status, model, updated FROM study_notes WHERE concept=?", (cid,)).fetchone()
    if not row:
        return {"status": "none"}
    return dict(json.loads(row[0]) if row[0] else {}, status=row[1], model=row[2], updated=row[3])


def summary_line(con, cid):
    note = note_of(con, cid)
    if note.get("easy"):
        return note["easy"], "ai_checked"
    if note["status"] == "wrong_sense":                     # 출처가 내 대화와 다른 뜻이면 보여 주지 않는다
        return None, "none"
    row = con.execute("SELECT definition FROM notes WHERE concept=?", (cid,)).fetchone()
    if row and row[0]:
        return row[0].strip().split("\n")[0][:120], "source"
    return None, "none"


def concepts(con, board, view="show", k=50, project=None):
    """view: show(공부할 개념) · hidden(숨겨진 낱말) · all"""
    data = board(con, k=100000, project=project)
    items = []
    for x in data["items"]:
        g = gate_of(con, x["id"], x["label"])
        if view == "all" or (view == "show") == g["show"]:
            line, kind = summary_line(con, x["id"])
            items.append({"id": x["id"], "label": x["label"], "rank": len(items) + 1, "sessions": x["sessions"], "turns": x["turns"], "last_seen": x["last_seen"],
                          "gate": g, "progress": progress_of(con, x["id"]), "line": line, "line_kind": kind})
    items.sort(key=lambda x: (-x["sessions"], -x["turns"], x["rank"]))       # 세션이 적을 때는 점수가 같은 개념이 많아 자주 나온 순서로 가른다
    if view == "hidden":                                    # 후보를 먼저
        items.sort(key=lambda x: not x["gate"]["candidate"])
    items = items[:k]
    for i, x in enumerate(items, 1):
        x["rank"] = i
    return {"project": project, "n_sessions": data["n_sessions"], "total_words": data["n_concepts"], "items": items}


def today(con, board, k=7, project=None):
    """오늘 볼 것: 아직 '이해함'이 아닌 개념을 중요도 순으로. 다시 볼 것을 앞에"""
    data = concepts(con, board, "show", 100000, project)
    todo = [x for x in data["items"] if x["progress"] != "known"]
    todo.sort(key=lambda x: (x["progress"] != "review", not x["line"], x["rank"]))     # 다시 볼 것 → 설명이 준비된 것 먼저
    known = sum(1 for x in data["items"] if x["progress"] == "known")
    return {"project": project, "items": todo[:k], "counts": {"shown": len(data["items"]), "known": known, "left": len(todo), "hidden": data["total_words"] - len(data["items"])}}


def detail(con, card, cid):
    """개념 노트. card = 서버의 클릭 카드 (정의·출처·내 기록)"""
    forms = [r[0] for r in con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form", (cid,))]
    note = note_of(con, cid)
    if note["status"] == "wrong_sense":                     # 출처가 다른 뜻을 설명한다: 정의를 화면에 내지 않는다
        card = dict(card, summary=None, definition=None, sources=[])
    related = []                                            # 함께 나온 낱말 중 공부 개념만
    for (b,) in con.execute("SELECT b FROM cooc WHERE a=? ORDER BY n DESC, b LIMIT 60", (cid,)):
        label = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (b,)).fetchone()
        if label and gate_of(con, b, label[0])["show"]:
            related.append({"id": b, "label": label[0]})
        if len(related) >= 6:
            break
    return dict(card, related=related, gate=gate_of(con, cid, card["label"]), progress=progress_of(con, cid), note=note, forms=forms, practice=practice(card.get("definition"), forms or [card["label"]]))


def practice(definition, forms):
    """확인 문제: 출처 문장에서 개념 이름만 가린 빈칸 문제. LLM을 쓰지 않아 새 내용이 생기지 않는다"""
    if not definition:
        return None
    sentence = re.split(r"(?<=[.!?。])\s+", definition.strip().split("\n")[0])[0]
    sentence = re.sub(r"\s*\([^()]*\)", "", sentence)      # 괄호 속 영어 이름 등은 답을 알려 준다
    for f in sorted(forms, key=len, reverse=True):
        rx = re.compile(re.escape(f), re.I)
        if len(sentence) >= 20 and rx.search(sentence):
            return {"blank": rx.sub("____", sentence), "answer": f}
    return None


def answers_list(con, k=20, project=None, clause=None):
    q = "SELECT id, session, ts, source, substr(text, 1, 160), length(text) FROM answers"
    args = []
    if clause:
        q += " WHERE " + clause[0]
        args += clause[1]
    rows = con.execute(q + " ORDER BY ts DESC, rowid DESC LIMIT ?", args + [k]).fetchall()
    return {"items": [{"id": r[0], "session": r[1], "ts": r[2], "source": r[3], "preview": re.sub(r"[*#`|]+|\s+", " ", r[4]).strip(), "chars": r[5]} for r in rows]}


def answer_detail(con, aid):
    r = con.execute("SELECT id, session, ts, source, text, question FROM answers WHERE id=?", (aid,)).fetchone()
    if not r:
        return None
    terms = []
    for (cid,) in con.execute("SELECT DISTINCT concept FROM mentions WHERE session=? AND ts=?", (r[1], r[2])):
        forms = [x[0] for x in con.execute("SELECT form FROM forms WHERE concept=? ORDER BY length(form) DESC", (cid,))]
        label = forms[0] if forms else cid
        top = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()
        if gate_of(con, cid, top[0] if top else label)["show"]:
            terms.append({"id": cid, "label": top[0] if top else label, "forms": forms})
    question = con.execute("SELECT substr(text, 1, 500) FROM questions WHERE id=?", (r[5],)).fetchone() if r[5] else None
    s = con.execute("SELECT body, status, model FROM answer_summaries WHERE answer=?", (aid,)).fetchone()
    return {"id": r[0], "session": r[1], "ts": r[2], "source": r[3], "text": r[4], "question": question[0] if question else None, "terms": sorted(terms, key=lambda t: -len(t["label"])),
            "summary": dict(json.loads(s[0]) if s[0] else {}, status=s[1], model=s[2]) if s else {"status": "none"}}


def set_progress(con, cid, status):
    if status not in STATUSES:
        raise ValueError("status는 known·review·new")
    con.execute("REPLACE INTO progress VALUES (?,?,?)", (cid, status, now()))
    con.commit()


def set_feedback(con, cid, verdict):
    if verdict not in VERDICTS:
        raise ValueError("verdict는 concept·not_concept·clear")
    con.execute("INSERT INTO judgments (concept, user, updated) VALUES (?,?,?) ON CONFLICT(concept) DO UPDATE SET user=excluded.user, updated=excluded.updated",
                (cid, None if verdict == "clear" else verdict, now()))
    con.commit()


def enqueue(con, kind, target, priority=5):
    """모델 작업 예약. 같은 작업이 이미 있으면 우선순위만 올린다. 작업자는 별도 프로세스 (study_worker.py)"""
    con.execute("""INSERT INTO jobs (kind, target, priority, status, updated) VALUES (?,?,?,'queued',?)
                   ON CONFLICT(kind, target) DO UPDATE SET priority=min(priority, excluded.priority),
                   status=CASE WHEN status='done' THEN status ELSE 'queued' END, updated=excluded.updated""", (kind, target, priority, now()))
    con.commit()


def job_counts(con):
    return dict(con.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
