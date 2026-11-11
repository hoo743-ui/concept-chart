# -*- coding: utf-8 -*-
"""study_api.py : 공부 화면용 조회·기록 (순수 함수, HTTP·화면·모델을 모른다). 계약은 docs/API.md.

보여 줄지는 concept_gate가, 문장이 믿을 만한지는 study_worker의 근거 대조가 정한다. 여기서는 저장된 판정을 읽어 합칠 뿐이다.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

import concept_gate as gate
import fields

STATUSES = {"known", "review", "new"}
VERDICTS = {"concept", "not_concept", "clear"}


def now():
    return datetime.now(timezone.utc).isoformat()


def answer_id(session, ts):
    return hashlib.sha1(f"{session}|{ts}".encode("utf-8")).hexdigest()[:16]


AI = True          # 서버가 --llm off로 켜지면 False: AI 없는 판정(concept_gate.final_no_ai)을 쓴다


def sourced(con, cid):
    """이름이 맞는 위키백과 문서에서 정의를 찾았는가 (관문의 두 번째 근거). 검색(SearXNG) 결과는 근거로 치지 않는다"""
    row = con.execute("SELECT definition, sources FROM notes WHERE concept=?", (cid,)).fetchone()
    if not (row and row[0] and row[1]):
        return False
    try:
        return any("wikipedia.org/" in str(s.get("url", "")) for s in json.loads(row[1]))
    except (ValueError, AttributeError):
        return False


def rule_of(con, cid, label):
    """규칙 판정. 영문 표기는 대화 문장을 함께 넘겨 화학식 조각(CH₄의 CH)을 거른다"""
    sents = None
    if gate.ASCII_FORM.fullmatch(label.strip()):
        sents = [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? LIMIT 20", (cid,))]
    return gate.rule_verdict(label, sents)


def gate_of(con, cid, label, use_user=True):
    """use_user=False: 사용자 판단을 빼고 관문만의 판정 (지속 검증에서 사용자 판단과 비교할 때)"""
    row = con.execute("SELECT llm, user, everyday FROM judgments WHERE concept=?", (cid,)).fetchone()
    llm, user, everyday = (row[0], row[1], row[2]) if row else (None, None, None)
    rule = rule_of(con, cid, label)
    if use_user and user in ("concept", "not_concept"):
        return {"show": user == "concept", "candidate": False, "extra": False, "by": "user", "rule": rule}
    lex = gate.lexicon_verdict(label)
    src = sourced(con, cid) if rule == "unknown" and lex != "general" else False
    llm = None if llm is None else bool(llm)
    extra = False
    if AI:
        verdict = gate.final(rule, llm, src, lex)
        extra = verdict != "show" and gate.rescue(rule, llm, src, lex, None if everyday is None else bool(everyday))
    else:
        verdict = gate.final_no_ai(rule, src, lex)
    by = ("rule" if rule in ("accept", "reject") else "lexicon" if rule == "unknown" and lex in ("general", "mixed") and llm is None
          else "llm" if llm is not None else "terms" if rule == "likely" else "unjudged")
    return {"show": verdict == "show", "candidate": verdict == "candidate", "extra": extra, "by": by, "rule": rule, "lexicon": lex}


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


def origin_of(con, cid):
    """이 개념을 처음 만난 자리: 처음 나온 답변과 그 앞의 내 질문 (질문 없이 붙여 넣은 답변이면 question은 None)"""
    r = con.execute("SELECT m.ts, m.session, q.text FROM mentions m LEFT JOIN questions q ON q.id = m.question "
                    "WHERE m.concept=? ORDER BY m.ts LIMIT 1", (cid,)).fetchone()
    if not r:
        return None
    line = next((x.strip() for x in (r[2] or "").splitlines() if x.strip()), "")
    line = re.sub(r"\s+", " ", line)
    return {"question": (line[:80] + "…" if len(line) > 80 else line) or None, "ts": r[0], "answer": answer_id(r[1], r[0])}


def with_origin(con, items):
    """화면에 나갈 개념에만 출처 질문과 분야 꼬리표를 붙인다 (전체 개념에 붙이면 느리다)"""
    for x in items:
        x["origin"] = origin_of(con, x["id"])
        x["field"] = fields.field_of(con, x["id"], x["label"])
    return items


def concepts(con, board, view="show", k=50, project=None, origin=True, extra=False):
    """view: show(공부할 개념) · hidden(숨겨진 낱말) · all. extra=True면 show에 '더 보기'에만 낼 낱말(gate.extra)도 넣는다 (today용)"""
    data = board(con, k=100000, project=project)
    items = []
    for x in data["items"]:
        g = gate_of(con, x["id"], x["label"])
        if view == "all" or (view == "show") == g["show"] or (view == "show" and extra and g["extra"]):
            line, kind = summary_line(con, x["id"])
            items.append({"id": x["id"], "label": x["label"], "rank": len(items) + 1, "sessions": x["sessions"], "turns": x["turns"], "last_seen": x["last_seen"],
                          "gate": g, "progress": progress_of(con, x["id"]), "line": line, "line_kind": kind})
    items.sort(key=lambda x: (-x["sessions"], -x["turns"], x["rank"]))       # 세션이 적을 때는 점수가 같은 개념이 많아 자주 나온 순서로 가른다
    if view == "hidden":                                    # 후보를 먼저
        items.sort(key=lambda x: not x["gate"]["candidate"])
    items = items[:k]
    for i, x in enumerate(items, 1):
        x["rank"] = i
    if origin:
        with_origin(con, items)
    return {"project": project, "n_sessions": data["n_sessions"], "total_words": data["n_concepts"], "items": items}


CORE = 3                       # 질문 묶음 하나에 바로 보여 줄 개념 수 (나머지는 접어 둔다. 사용자 결정 11-10: 첫 화면은 질문별)


def today(con, board, k=7, project=None):
    """오늘 볼 것: 아직 '이해함'이 아닌 개념을, 처음 만난 내 질문별로 묶는다 (k = 질문 묶음 수).
    묶음 순서: 다시 볼 것이 있는 질문 → 최근 질문. 묶음 안: 다시 볼 것 → 설명이 준비된 것 → 중요도. 묶음마다 CORE개만 펼친다.
    관문이 '더 보기'에만 내놓은 낱말(gate.extra)은 펼치지 않고 more 끝에 extra=True로 붙인다. 그런 낱말만 있는 질문은 묶음을 만들지 않는다.
    items는 펼친 개념을 이어 붙인 것 (예전 화면·도구용)"""
    data = concepts(con, board, "show", 100000, project, origin=False, extra=True)
    shown = [x for x in data["items"] if x["gate"]["show"]]
    todo = [x for x in data["items"] if x["progress"] != "known"]
    todo.sort(key=lambda x: (x["gate"]["extra"], x["progress"] != "review", not x["line"], x["rank"]))     # 다시 볼 것 → 설명이 준비된 것 먼저, 덧붙일 낱말은 맨 뒤
    known = sum(1 for x in shown if x["progress"] == "known")
    groups = {}
    for x in with_origin(con, todo):
        o = x["origin"] or {}
        if x["gate"]["extra"] and o.get("answer") not in groups:
            continue
        g = groups.setdefault(o.get("answer"), {"answer": o.get("answer"), "question": o.get("question"), "ts": o.get("ts"), "items": [], "more": []})
        (g["items"] if len(g["items"]) < CORE and not x["gate"]["extra"] else g["more"]).append(x)
    def has_review(g):
        return any(x["progress"] == "review" for x in g["items"] + g["more"])
    order = sorted(groups.values(), key=lambda g: (g["ts"] is not None, g["ts"] or ""), reverse=True)    # 최근 질문 먼저 (기록 없는 묶음은 맨 뒤)
    order.sort(key=lambda g: not has_review(g))                                                          # 안정 정렬: 다시 볼 것이 있는 질문을 앞으로
    picked = order[:k]
    for g in picked:
        g["more"] = [{"id": x["id"], "label": x["label"], "extra": x["gate"]["extra"]} for x in g["more"]]
    left = sum(1 for x in todo if x["gate"]["show"])
    return {"project": project, "groups": picked, "items": [x for g in picked for x in g["items"]],
            "counts": {"shown": len(shown), "known": known, "left": left, "hidden": data["total_words"] - len(shown), "questions": len(groups),
                       "extra": len(todo) - left}}


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
    return dict(card, related=related, gate=gate_of(con, cid, card["label"]), progress=progress_of(con, cid), note=note, origin=origin_of(con, cid), field=fields.field_of(con, cid, card["label"]), forms=forms, practice=practice(card.get("definition"), forms or [card["label"]]))


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


VIEWS_KEEP = 5000              # 열어 본 기록은 최근 이만큼만 남긴다


def record_view(con, cid):
    """개념 노트를 연 시각 (사용자가 '저번에 무엇을 봤지?'를 물을 수 있게)"""
    con.execute("INSERT INTO views VALUES (?,?)", (cid, now()))
    con.execute("DELETE FROM views WHERE rowid <= (SELECT MAX(rowid) FROM views) - ?", (VIEWS_KEEP,))
    con.commit()


def history(con, k=50):
    """최근 공부 기록: 노트를 연 것(opened)과 진도를 표시한 것(marked, status = 지금 상태). 개념마다 가장 최근 것 하나씩, 최근 순"""
    rows = {}
    for cid, ts in con.execute("SELECT concept, MAX(ts) FROM views GROUP BY concept"):
        rows[(cid, "opened")] = {"id": cid, "kind": "opened", "status": None, "ts": ts}
    for cid, status, ts in con.execute("SELECT concept, status, updated FROM progress"):
        rows[(cid, "marked")] = {"id": cid, "kind": "marked", "status": status, "ts": ts}
    items = sorted(rows.values(), key=lambda x: x["ts"] or "", reverse=True)[:k]
    for x in items:
        top = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (x["id"],)).fetchone()
        x["label"] = top[0] if top else x["id"]
    return {"items": items}


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


def feedback_check(con):
    """지속 검증 (기획서 2절 4단계): 사용자가 '맞아요·아니에요'로 판단한 낱말에서 관문(사용자 판단을 뺀 판정)이 맞았는지.
    → {"n", "shown", "shown_ok", "precision"(보여 준 것 중 사용자도 개념이라 한 비율, 보여 준 것이 없으면 None),
       "wrong": 관문은 보여 줬는데 사용자는 아니라 한 낱말, "missed": 관문은 숨겼는데 사용자는 개념이라 한 낱말, "gold": {낱말: 개념인가}}"""
    rows = con.execute("SELECT concept, user FROM judgments WHERE user IN ('concept','not_concept') ORDER BY concept").fetchall()
    wrong, missed, gold, shown_ok, shown = [], [], {}, 0, 0
    for cid, user in rows:
        top = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()
        label = top[0] if top else cid
        g = gate_of(con, cid, label, use_user=False)
        yes = user == "concept"
        gold[label] = yes
        if g["show"]:
            shown += 1
            shown_ok += yes
            if not yes:
                wrong.append(label)
        elif yes:
            missed.append(label)
    return {"n": len(rows), "shown": shown, "shown_ok": shown_ok, "precision": round(shown_ok / shown, 3) if shown else None,
            "wrong": wrong, "missed": missed, "gold": gold}


def coverage(con):
    """공부 내용 전달 지표: 공부 목록에 나온 개념(사용자 판단 포함) 중 설명이 붙은 비율.
    ai_checked = 근거 대조를 통과한 쉬운 설명, source = 출처 문장 한 줄, none = 아직 설명 없음(또는 출처가 다른 뜻)"""
    n = {"ai_checked": 0, "source": 0, "none": 0}
    for (cid,) in con.execute("SELECT DISTINCT concept FROM forms").fetchall():
        top = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()
        if gate_of(con, cid, top[0] if top else cid)["show"]:
            n[summary_line(con, cid)[1]] += 1
    total = sum(n.values())
    return dict(n, shown=total, explained=round((n["ai_checked"] + n["source"]) / total, 3) if total else None)


def enqueue(con, kind, target, priority=5):
    """모델 작업 예약. 같은 작업이 이미 있으면 우선순위만 올린다. 작업자는 별도 프로세스 (study_worker.py)"""
    con.execute("""INSERT INTO jobs (kind, target, priority, status, updated) VALUES (?,?,?,'queued',?)
                   ON CONFLICT(kind, target) DO UPDATE SET priority=min(priority, excluded.priority),
                   status=CASE WHEN status='done' THEN status ELSE 'queued' END, updated=excluded.updated""", (kind, target, priority, now()))
    con.commit()


def job_counts(con):
    return dict(con.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
