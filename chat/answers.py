# -*- coding: utf-8 -*-
"""answers.py : '내 공부 기록에 묻기'의 답 만들기 (순수 함수, 네트워크·LLM 없음).

답은 개념 차트 API가 돌려준 기록 값을 정해 둔 틀에 채워서만 만든다 (docs/WORKSHEET.md 2절 '내 공부 기록에 묻기').
- 일반 공부법 조언, 개념의 뜻 설명은 만들지 않는다. 뜻 질문에는 개념 노트에 이미 있는 출처 확인 문장만 옮기고(11-13), 없으면 없다고 한다.
- 기록으로 답할 수 없으면 "기록에 없어요"라고 한다.
- 모든 답에 근거(개념 노트 링크)를 붙인다.

답 형식: {"intent", "text": 문단 목록, "links": [{label, href}]}
"""
import re
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
STATUS = {"known": "이해함", "review": "다시 보기", "new": "아직 표시 안 함"}
EXAMPLES = ["어떻게 학습하면 좋을까요?", "분야별로 개념 노트를 나눠 주세요", "제가 저번에 공부했던 게 뭐였죠?", "트랜스포머, 제가 공부했었나요?"]   # 11-13: 존댓말 (사용자 결정)


def ro(word):
    """조사 (으)로: 받침이 있으면 '으로' (ㄹ 받침은 '로')"""
    last = word[-1] if word else ""
    if "가" <= last <= "힣":
        jong = (ord(last) - 0xAC00) % 28
        return word + ("으로" if jong and jong != 8 else "로")
    return word + "로"


def note_href(app_url, cid):
    from urllib.parse import quote
    return f"{app_url}/#/c/{quote(cid, safe='')}"


def norm(s):
    return re.sub(r"[\s\-_·]+", "", (s or "").lower())


def local_day(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(KST).date()
    except (ValueError, AttributeError):
        return None


def plan(today, app_url):
    """어떻게 학습하면 좋아? → 내 기록으로 정한 순서 (오늘 공부 화면과 같은 순서)"""
    c = today.get("counts", {})
    items = [x for g in today.get("groups", []) for x in g.get("items", [])]
    if not c.get("shown"):
        return {"intent": "plan", "text": ["아직 공부할 개념이 없어요. AI 답변이 쌓이면 개념을 골라 드려요."], "links": []}
    text = [f"기록으로 보면 이 순서가 좋아요. (공부할 개념 {c.get('shown', 0)}개 중 남은 것 {c.get('left', 0)}개, 이해함 {c.get('known', 0)}개)"]
    links = []
    review = [x for x in items if x.get("progress") == "review"]
    ready = [x for x in items if x.get("progress") != "review" and x.get("line_kind") in ("ai_checked", "source")]
    step = 1
    if review:
        text.append(f"{step}. '다시 보기'로 표시한 개념부터: " + ", ".join(x["label"] for x in review))
        links += [{"label": x["label"], "href": note_href(app_url, x["id"])} for x in review]
        step += 1
    if ready:
        text.append(f"{step}. 설명이 준비된 개념을 읽고 빈칸 문제로 확인하기: " + ", ".join(x["label"] for x in ready[:5]))
        links += [{"label": x["label"], "href": note_href(app_url, x["id"])} for x in ready[:5]]
        step += 1
    g = next((g for g in today.get("groups", []) if g.get("items")), None)
    if g:
        q = f"“{g['question']}”" if g.get("question") else "붙여 넣은 답변"
        text.append(f"{step}. 질문 하나씩 끝내기: {q}에서 나온 " + ", ".join(x["label"] for x in g["items"]))
    text.append("일반 공부법이 아니라 내 기록(진도·설명 준비·처음 만난 질문)만으로 정한 순서예요.")
    return {"intent": "plan", "text": text, "links": dedup(links)}


def by_field(concepts, app_url, per=8):
    """분야별로 나눠줘 → 분야 꼬리표로 묶기. 꼬리표가 없는 개념은 '분야 미정'"""
    items = concepts.get("items", [])
    if not items:
        return {"intent": "by_field", "text": ["아직 공부할 개념이 없어요."], "links": []}
    groups = {}
    for x in items:
        groups.setdefault(x.get("field") or "분야 미정", []).append(x)
    order = sorted(groups, key=lambda f: (f == "분야 미정", -len(groups[f]), f))
    text, links = [f"공부할 개념 {len(items)}개를 분야 꼬리표로 나눴어요."], []
    for f in order:
        xs = groups[f]
        more = f" 외 {len(xs) - per}개" if len(xs) > per else ""
        text.append(f"{f} ({len(xs)}개): " + ", ".join(x["label"] for x in xs[:per]) + more)
        links += [{"label": x["label"], "href": note_href(app_url, x["id"])} for x in xs[:per]]
    if "분야 미정" in groups:
        text.append("'분야 미정'은 분야 사전과 함께 나온 개념으로 분야를 정할 근거가 부족한 개념이에요. 추측해서 붙이지 않았어요.")
    return {"intent": "by_field", "text": text, "links": dedup(links)}


PERIOD = {"today": "오늘", "yesterday": "어제", "week": "최근 7일", "all": "지금까지"}


def recent(history, app_url, period="all", now=None, k=15):
    """저번에 공부한 게 뭐였지? → 노트를 연 기록과 진도 표시 기록"""
    today = (now or datetime.now(KST)).astimezone(KST).date()
    def keep(ts):
        d = local_day(ts)
        if d is None:
            return False
        return {"today": d == today, "yesterday": d == today - timedelta(days=1), "week": d >= today - timedelta(days=6)}.get(period, True)
    items = [x for x in history.get("items", []) if keep(x.get("ts"))]
    if not items:
        return {"intent": "recent", "text": [f"{PERIOD.get(period, '지금까지')} 공부한 기록이 없어요."], "links": []}
    text, links, seen = [f"{PERIOD.get(period, '지금까지')} 공부한 기록이에요 (최근 순)."], [], set()
    for x in items:
        if x["id"] in seen or len(seen) >= k:
            continue
        seen.add(x["id"])
        s = STATUS.get(x.get("status"), str(x.get("status")))
        what = "노트를 열어 봄" if x["kind"] == "opened" else f"'{s}'" + ro(s)[len(s):] + " 표시"
        d = local_day(x["ts"])
        text.append(f"- {x['label']}: {what} ({d.month}/{d.day})")
        links.append({"label": x["label"], "href": note_href(app_url, x["id"])})
    return {"intent": "recent", "text": text, "links": links}


def find(name, items):
    """이름으로 개념 찾기: 같은 표기 → 앞뒤 포함. 여러 개면 모두"""
    n = norm(name)
    if len(n) < 1:
        return []
    exact = [x for x in items if norm(x["label"]) == n or norm(x["id"]) == n]
    if exact:
        return exact
    return [x for x in items if len(n) >= 2 and (n in norm(x["label"]) or (len(norm(x["label"])) >= 2 and norm(x["label"]) in n))][:5]


def check(name, all_concepts, history, app_url):
    """이거 내가 했던가? → 그 개념의 진도·열어 본 기록·처음 만난 질문"""
    if not name:
        return {"intent": "check", "text": ["어떤 개념을 확인할지 이름을 함께 적어 주세요. 예: " + EXAMPLES[3]], "links": []}
    found = find(name, all_concepts.get("items", []))
    if not found:
        return {"intent": "check", "text": [f"'{name}'은(는) 기록에 없어요. 지금까지의 AI 답변에서 나온 적이 없는 낱말이에요."], "links": []}
    last = {}
    for h in history.get("items", []):
        last.setdefault((h["id"], h["kind"]), h)
    text, links = [], []
    for x in found:
        if not (x.get("gate") or {}).get("show"):
            text.append(f"{x['label']}: 기록에는 있지만 공부 목록에서 숨겨진 낱말이에요. (전체 개념 화면에서 되돌릴 수 있어요)")
            continue
        p = x.get("progress", "new")
        opened = last.get((x["id"], "opened"))
        marked = last.get((x["id"], "marked"))
        if p in ("known", "review") and marked:
            d = local_day(marked["ts"])
            line = f"{x['label']}: 네, '{STATUS[p]}'" + ro(STATUS[p])[len(STATUS[p]):] + f" 표시했어요 ({d.month}/{d.day})."
        elif opened:
            d = local_day(opened["ts"])
            line = f"{x['label']}: 노트를 열어 본 적은 있어요 ({d.month}/{d.day}). 아직 이해함으로 표시하지 않았어요."
        else:
            line = f"{x['label']}: 아직 공부하지 않았어요."
        o = x.get("origin") or {}
        if o.get("question"):
            line += f" 처음 만난 질문: “{o['question']}”"
        text.append(line)
        links.append({"label": x["label"], "href": note_href(app_url, x["id"])})
    return {"intent": "check", "text": text, "links": links}


KIND_SAY = {"ai_checked": "출처 문장으로 확인한 쉬운 설명", "source": "출처 문장 그대로", "own": "내 대화에 나온 문장"}
PARTICLE = re.compile(r"(이란|란|이|가|은|는|을|를|의)$")


def define(name, all_concepts, app_url):
    """OO가 뭐야? → 개념 노트에 있는 설명 한 줄(출처 문장)만 옮긴다. 설명이 없거나 기록에 없으면 없다고 한다 (뜻을 지어내지 않는다)"""
    items = all_concepts.get("items", [])
    cands = [name] + ([PARTICLE.sub("", name)] if PARTICLE.search(name) and len(PARTICLE.sub("", name)) >= 1 else [])
    found = []
    for c in cands:                                         # 같은 표기만 답으로 쓴다 (비슷한 이름은 '이것을 찾으셨나요'로만)
        found = [x for x in items if norm(x["label"]) == norm(c) or norm(x["id"]) == norm(c)]
        if found:
            break
    if not found:
        near = [x for x in find(cands[-1], items) if (x.get("gate") or {}).get("show")][:3]
        text = [f"'{cands[-1]}'은(는) 내 기록에 없는 낱말이에요. 지금까지의 AI 답변에 나온 적이 없어서 설명할 근거가 없어요."]
        if near:
            text.append("비슷한 이름의 개념은 있어요: " + ", ".join(x["label"] for x in near))
        return {"intent": "define", "text": text, "links": [{"label": x["label"], "href": note_href(app_url, x["id"])} for x in near]}
    text, links = [], []
    for x in found[:3]:
        line = (x.get("line") or "").strip()
        if line:
            text.append(f"{x['label']}: {line}")
            text.append(f"({KIND_SAY.get(x.get('line_kind'), '출처 문장')}이에요. 출처 링크는 개념 노트에 있어요.)")
        else:
            text.append(f"{x['label']}: 내 기록에는 있지만 아직 믿을 만한 설명을 찾지 못했어요. 지어내지 않으려고 비워 두었어요.")
        if not (x.get("gate") or {}).get("show"):
            text.append("이 낱말은 공부 목록에서 숨겨져 있어요.")
        links.append({"label": x["label"], "href": note_href(app_url, x["id"])})
    return {"intent": "define", "text": text, "links": links}


def other(text_in, all_concepts, app_url):
    """기록으로 답할 수 없는 질문. 개념 이름이 들어 있으면 그 노트로 안내만 한다 (뜻을 지어내지 않는다)"""
    hits = [x for x in all_concepts.get("items", []) if (x.get("gate") or {}).get("show") and len(norm(x["label"])) >= 2 and norm(x["label"]) in norm(text_in)][:3]
    text = ["그 질문은 내 공부 기록으로 답할 수 없어요. 이렇게 물어볼 수 있어요: " + " / ".join(EXAMPLES)]
    if hits:
        text.insert(0, "개념의 뜻은 출처가 붙은 개념 노트에서 볼 수 있어요: " + ", ".join(x["label"] for x in hits))
    return {"intent": "other", "text": text, "links": [{"label": x["label"], "href": note_href(app_url, x["id"])} for x in hits]}


def dedup(links):
    seen, out = set(), []
    for l in links:
        if l["href"] not in seen:
            seen.add(l["href"])
            out.append(l)
    return out
