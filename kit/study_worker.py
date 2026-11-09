# -*- coding: utf-8 -*-
"""study_worker.py : 모델 작업자 (서버와 별도 프로세스). 서버가 죽지 않게, 메모리를 돌려주게 분리한다.

    python kit/study_worker.py --db ~/.claude/concept-chart.sqlite --llm ollama:qwen3:4b

DB의 jobs 표에서 작업을 하나씩 꺼낸다. 작업 종류: judge(개념 판정), note(쉬운 설명), summary(답변 요약).

자원: 한 번에 하나, 낮은 우선순위, 사용 가능 RAM·GPU 메모리가 모자라면 기다린다, 일이 없으면 프로세스를 끝낸다.

거짓 방지 (실제 생성 결과를 읽고 정한 규칙, docs/CONSTRAINTS.md):
- 요약: LLM은 문장 번호만 고른다. 화면에는 원문 문장을 그대로 보여 주므로 새 문장이 생기지 않는다.
- 쉬운 설명: 근거 한 문장에서만 나와야 한다. 명사·숫자·영문이 그 문장에 모두 있고, 다른 프롬프트로 물어도 뒷받침된다고 나와야 저장한다.
- 낱말 겹침만 보던 예전 대조는 '0.04GB의 온도' 같은 문장을 통과시켰다. 대화 설명·기억할 점·LLM 퀴즈는 그래서 뺐다.
"""
import argparse
import ctypes
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import concept_gate as gate
import llm as llm_mod

MIN_RAM_GB, MIN_GPU_MB = 3.0, 3000       # 이보다 적으면 기다린다
IDLE_EXIT = 300                          # 일이 이만큼(초) 없으면 끝낸다
PAUSE = 2                                # 작업 사이 쉬는 시간 (초)
MAX_EVIDENCE = 5000
MAX_TRIES = 3
MAX_SENTENCES = 60                       # 요약 때 LLM에게 보여 줄 문장 수
MAX_PICKS = 5

TECH = "컴퓨터·소프트웨어·AI·데이터"
SENSE_SCHEMA = {"type": "object", "properties": {"field": {"type": "string", "enum": [TECH, "다른 분야"]}}, "required": ["field"]}
OTHER = "다른 대상"
REFERENT_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string", "enum": ["같은 대상", OTHER, "알 수 없음"]}}, "required": ["answer"]}
NOTE_SCHEMA = {"type": "object", "properties": {"easy": {"type": "string"}}, "required": ["easy"]}
ENTAIL_SCHEMA = {"type": "object", "properties": {"supported": {"type": "boolean"}}, "required": ["supported"]}
PICK_SCHEMA = {"type": "object", "properties": {"picks": {"type": "array", "items": {"type": "integer"}, "maxItems": MAX_PICKS}}, "required": ["picks"]}


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def lower_priority():
    if os.name == "nt":
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass(ctypes.c_void_p(k.GetCurrentProcess()), 0x00004000)
    else:
        os.nice(10)


def avail_ram_gb():
    if os.name == "nt":
        class M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = M()
        m.l = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.avail / 1e9
    return None


def gpu_free_mb():
    try:
        kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, **kw).stdout
        return int(out.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def wait_for_room(model_loaded=False):
    """메모리가 모자라면 기다린다. 이미 모델이 올라와 있으면 GPU 조건은 보지 않는다"""
    while True:
        ram, gpu = avail_ram_gb(), None if model_loaded else gpu_free_mb()
        if (ram is None or ram >= MIN_RAM_GB) and (gpu is None or gpu >= MIN_GPU_MB):
            return
        log(f"자원 대기: RAM {ram}GB, GPU 여유 {gpu}MB")
        time.sleep(30)


def source_of(con, cid):
    row = con.execute("SELECT definition, sources FROM notes WHERE concept=?", (cid,)).fetchone()
    return row[0][:MAX_EVIDENCE] if row and row[0] else None


def sense_prompt(label, definition):
    """개념은 이미 기술 용어로 판정됐다. 출처가 기술 분야를 설명하는지만 본다"""
    return f"""아래 설명문은 어느 분야의 내용인가? 낱말 '{label}'이 컴퓨터, 프로그래밍, 소프트웨어, 인터넷, 인공지능, 데이터, 통계, 전자기기와 관련된 뜻으로 설명되면 "{TECH}"를 고른다. 동물, 음식, 음악, 의학, 건설, 스포츠, 지리, 금융, 미술, 언론, 기계·자동차, 대학·학교처럼 그 밖의 뜻이면 "다른 분야"를 고른다.
설명문: {definition[:600]}
JSON으로만 답한다."""


def referent_prompt(label, definition, chat):
    joined = "\n".join("- " + c for c in chat[:3])
    return f"""[설명]이 [대화]에 나온 '{label}'과 같은 대상을 설명하는지 판단한다. 이름만 같고 다른 제품·회사·분야를 가리키면 "{OTHER}"다. 판단할 단서가 부족하면 "알 수 없음"이다.
예: 대화 "RTX 2060 그래픽카드로 학습", 설명 "RTX는 IntervalZero의 실시간 운영체제다" → {OTHER}
예: 대화 "API를 호출한다", 설명 "API는 프로그램 사이의 연결이다" → 같은 대상
[설명] {definition[:600]}
[대화]
{joined}
JSON으로만 답한다."""


def note_prompt(label, sentence):
    return f"""아래 [원문] 한 문장을 초보자가 읽기 쉽게 '{label}' 설명 한 문장으로 다듬는다.
반드시 지킬 것:
1. [원문]에 있는 낱말만 쓴다. 전문 용어, 이름, 숫자를 바꾸거나 더하지 않는다. 괄호 설명과 덜 중요한 부분은 빼도 된다.
2. 문장 끝만 '~입니다'로 바꾼다.
3. 한 문장으로 쓴다. 예: 원문 "NumPy(넘파이)는 대규모 다차원 배열을 쉽게 처리할 수 있도록 지원하는 파이썬의 라이브러리이다." → "NumPy는 대규모 다차원 배열을 쉽게 처리하는 파이썬 라이브러리입니다."
[원문]
{sentence}
JSON으로만 답한다. easy: 다듬은 문장."""


def entail_prompt(claim, sentence):
    return f"""[문장]의 내용이 [근거]에 모두 그대로 들어 있으면 true, 근거에 없는 내용이나 다른 내용이 하나라도 있으면 false다.
[근거]
{sentence}
[문장]
{claim}
JSON으로만 답한다. supported는 true 또는 false."""


def pick_prompt(sentences, question):
    q = f"[내 질문]\n{question}\n" if question else ""
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, 1))
    return f"""아래는 AI 답변을 번호를 붙여 나눈 문장이다. 질문에 답하는 핵심 문장의 번호를 최대 {MAX_PICKS}개 고른다. 문장을 새로 쓰지 않는다.
{q}[AI 답변]
{numbered}
JSON으로만 답한다. picks: 고른 번호 목록."""


def noun_tokens(text):
    import verify_note as v
    return {t.form.lower() for t in v.kiwi.tokenize(text) if t.tag in ("NNG", "NNP", "NR", "SN", "SL", "SH")}


BROKEN_END = re.compile(r"(다|요)입니다")


def strict_ok(claim, sentence):
    """명사·숫자·영문이 근거 한 문장에 모두 있는가. 깨진 낱말(마이크로소과프트)과 없는 사실이 여기서 걸린다"""
    src = re.sub(r"\s+", "", sentence).lower()
    src_nouns = noun_tokens(sentence)
    nouns = noun_tokens(claim)

    def ok(n):                                              # 붙여 쓴 복합어(파인 튜닝 → 파인튜닝)는 허용하되, 낱말의 앞부분만 맞는 경우(스크립트 → 스크립)는 거절
        return n in src_nouns or (n in src and not any(s != n and s.startswith(n) for s in src_nouns))
    if not set(re.findall(r"\d+", claim)) <= set(re.findall(r"\d+", sentence)):
        return False                                        # 원문에 없는 숫자 ('리눅스 운영체제는 1: 1991년')
    if BROKEN_END.search(claim):
        return False                                        # 어미가 겹친 문장 ('일컫는다입니다')
    return bool(nouns) and all(ok(n) for n in nouns)


def first_sentences(definition, n=2):
    import verify_note as v
    return v.sentences(definition)[:n]


def run_note(con, client, cid):
    row = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()
    label = row[0] if row else cid
    definition = source_of(con, cid)
    if not definition:
        return "no_evidence", None
    if client.json(sense_prompt(label, definition), SENSE_SCHEMA, 30).get("field") != TECH:
        return "wrong_sense", None                          # 출처가 다른 분야의 뜻이다: 설명을 만들지도 보여 주지도 않는다
    chat = [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (cid,))]
    if chat and client.json(referent_prompt(label, definition, chat), REFERENT_SCHEMA, 30).get("answer") == OTHER:
        return "wrong_sense", None                          # 같은 기술 분야지만 이름만 같은 다른 대상 (RTX 그래픽카드 ≠ RTX 운영체제)
    sents = first_sentences(definition)
    if not sents:
        return "no_evidence", None
    sentence = sents[0]
    claim = (client.json(note_prompt(label, sentence), NOTE_SCHEMA, 200).get("easy") or "").strip()
    passed = bool(claim) and strict_ok(claim, sentence) and client.json(entail_prompt(claim, sentence), ENTAIL_SCHEMA, 20).get("supported") is True
    return ("ready" if passed else "rejected"), {"easy": claim if passed else None, "easy_evidence": [sentence] if passed else [], "checked": {"total": 1, "passed": int(passed)}, "has_source": True}


def answer_sentences(text):
    """요약 후보: 코드 상자를 빼고 나눈 원문 문장 (마크다운 표시만 걷어 낸다)"""
    import verify_note as v
    prose = re.sub(r"```.*?```", " ", text, flags=re.S)
    out = []
    for line in prose.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s+)+", "", line.strip())
        if not line or re.fullmatch(r"[\s:\-|]+", line) or line.startswith("|"):
            continue
        out += [re.sub(r"\*\*|`", "", s).strip() for s in v.sentences(line)]
    return [s for s in out if len(s) >= 12][:MAX_SENTENCES]


def run_summary(con, client, aid):
    r = con.execute("SELECT text, question FROM answers WHERE id=?", (aid,)).fetchone()
    if not r:
        return "no_evidence", None
    sents = answer_sentences(r[0])
    if not sents:
        return "no_evidence", None
    q = con.execute("SELECT substr(text, 1, 500) FROM questions WHERE id=?", (r[1],)).fetchone() if r[1] else None
    picks = client.json(pick_prompt(sents, q[0] if q else None), PICK_SCHEMA, 60).get("picks") or []
    valid = sorted({p for p in picks if isinstance(p, int) and 1 <= p <= len(sents)})[:MAX_PICKS]
    points = [{"text": sents[p - 1], "evidence": sents[p - 1]} for p in valid]
    return ("ready" if points else "rejected"), {"points": points, "checked": {"total": len(points), "passed": len(points)}, "extractive": True}


def run_judge(con, client, cid):
    row = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()
    if not row:
        return
    sents = [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (cid,))]
    verdict = bool(client.json(gate.judge_prompt(row[0], sents), gate.JUDGE_SCHEMA, 20)["is_term"])
    con.execute("INSERT INTO judgments (concept, llm, updated) VALUES (?,?,?) ON CONFLICT(concept) DO UPDATE SET llm=excluded.llm, updated=excluded.updated",
                (cid, int(verdict), datetime.now(timezone.utc).isoformat()))


def run_job(con, client, kind, target):
    t = datetime.now(timezone.utc).isoformat()
    if kind == "judge":
        run_judge(con, client, target)
    elif kind == "note":
        status, body = run_note(con, client, target)
        con.execute("REPLACE INTO study_notes VALUES (?,?,?,?,?)", (target, json.dumps(body, ensure_ascii=False) if body else None, status, client.name, t))
    elif kind == "summary":
        status, body = run_summary(con, client, target)
        con.execute("REPLACE INTO answer_summaries VALUES (?,?,?,?,?)", (target, json.dumps(body, ensure_ascii=False) if body else None, status, client.name, t))
    else:
        raise ValueError(kind)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--llm", required=True)
    ap.add_argument("--idle", type=int, default=IDLE_EXIT)
    a = ap.parse_args()
    lower_priority()
    client = llm_mod.make(a.llm)
    con = sqlite3.connect(str(pathlib.Path(a.db).expanduser()), timeout=30)
    con.execute("PRAGMA synchronous=NORMAL")
    last = time.time()
    loaded = False
    while time.time() - last < a.idle:
        job = con.execute("SELECT id, kind, target, tries FROM jobs WHERE status='queued' ORDER BY priority, id LIMIT 1").fetchone()
        if not job:
            time.sleep(3)
            continue
        if not client.available():
            log("LLM을 쓸 수 없어 끝냅니다", client.name)
            return 2
        wait_for_room(loaded)
        jid, kind, target, tries = job
        t0 = time.time()
        try:
            run_job(con, client, kind, target)
            con.execute("UPDATE jobs SET status='done', updated=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), jid))
            loaded = True
            log(kind, f"끝 {time.time() - t0:.1f}초")
        except llm_mod.LLMError as e:
            fail = tries + 1 >= MAX_TRIES
            con.execute("UPDATE jobs SET tries=tries+1, status=? WHERE id=?", ("failed" if fail else "queued", jid))
            log(kind, "실패", str(e)[:120])
            time.sleep(10)
        except Exception as e:  # noqa: BLE001 — 이 작업만 실패 처리하고 계속
            con.execute("UPDATE jobs SET tries=?, status='failed' WHERE id=?", (MAX_TRIES, jid))
            log(kind, "실패", type(e).__name__, str(e)[:200])
        con.commit()
        last = time.time()
        time.sleep(PAUSE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
