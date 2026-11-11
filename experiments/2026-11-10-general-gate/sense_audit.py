# -*- coding: utf-8 -*-
"""실험 (11-12 아침, 채택 안 함 — 측정만): 공부 목록에 나간 출처 설명 전체에 study_worker.run_note와 같은 뜻 확인
(분야 확인 sense_prompt + 같은 대상 확인 referent_prompt)을 돌리면 무엇이 걸리는가.

배경: 출처 문장은 쉬운 설명(상위 WARM_TOP개)을 만들 때만 뜻 확인을 거친다. 나머지는 확인 없이 화면에 나간다.
문서 제목으로 본 틀린 뜻: 중복 → 복날, 임시 → 이십사시, Settings → 안드로이드, epoch → Epoch (computing) …

    python experiments/2026-11-10-general-gate/sense_audit.py      (실제 DB 읽기 전용, LLM 답은 data/eval/sense_audit.json에 저장)

출력은 낱말 이름과 판정만 (대화 문장은 찍지 않는다).
"""
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "kit"))
import fields  # noqa: E402
import llm as llm_mod  # noqa: E402
import study_api  # noqa: E402
import study_worker as w  # noqa: E402

DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
CACHE = ROOT / "data" / "eval" / "sense_audit.json"

# 문서 제목만 보고 사람이 '다른 뜻'으로 본 것 (대화 문맥은 보지 않음 → 확인의 재현율을 대략 보는 용도)
MANUAL_WRONG = {"중복", "임시", "지연", "정적", "사전학습", "임계값", "Settings", "Structured", "Noto", "RTX", "Apache", "epoch",
                "Export", "import", "stream", "torch", "window", "temperature"}


def main():
    w.lower_priority()
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    client = llm_mod.make("ollama:qwen3:4b")
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    rows = []
    for (cid,) in con.execute("SELECT DISTINCT concept FROM forms").fetchall():
        top = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()
        label = top[0] if top else cid
        if not study_api.gate_of(con, cid, label)["show"]:
            continue
        definition = w.source_of(con, cid)
        if not definition:
            continue
        rows.append((cid, label, definition))
    print("공부 목록 중 출처 설명이 있는 개념", len(rows), flush=True)
    for i, (cid, label, definition) in enumerate(rows, 1):
        key = cid + "\t" + definition[:80]
        if key in cache:
            continue
        r = {"label": label, "tech": fields.field_of(con, cid, label) == fields.TECH}
        try:
            if r["tech"]:
                r["sense"] = client.json(w.sense_prompt(label, definition), w.SENSE_SCHEMA, 30).get("field")
            chat = [x[0] for x in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (cid,))]
            if chat:
                r["referent"] = client.json(w.referent_prompt(label, definition, chat), w.REFERENT_SCHEMA, 30).get("answer")
        except llm_mod.LLMError as e:
            r["error"] = str(e)[:80]
        cache[key] = r
        if i % 10 == 0:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_bytes(json.dumps(cache, ensure_ascii=False, indent=0).encode("utf-8"))
            print(f"{i}/{len(rows)}", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(json.dumps(cache, ensure_ascii=False, indent=0).encode("utf-8"))

    flagged, errors = [], []
    for cid, label, definition in rows:
        r = cache[cid + "\t" + definition[:80]]
        if "error" in r:
            errors.append(label)
        elif (r["tech"] and r.get("sense") != w.TECH) or r.get("referent") == w.OTHER:
            flagged.append(label)
    hit = sorted(set(flagged) & MANUAL_WRONG)
    print(f"걸린 것 {len(flagged)}개 / {len(rows)}개 (오류 {len(errors)})")
    print("걸린 낱말:", ", ".join(sorted(flagged)))
    print(f"사람이 본 틀린 뜻 {len(MANUAL_WRONG)}개 중 걸린 것 {len(hit)}개, 놓친 것:", ", ".join(sorted(MANUAL_WRONG - set(flagged))))


if __name__ == "__main__":
    main()
