# -*- coding: utf-8 -*-
"""지속 검증 (기획서 2절 4단계, 사용자 결정 11-11 '피드백 버튼 진행'): 사용자 판단만 정답에 더하고, 같은 세트를 다시 재서 기록하고, 떨어지면 알린다.

    python dev.py verify          (= python experiments/2026-11-10-general-gate/verify.py)

1. 피드백: 개념 노트의 '맞아요 · 아니에요'로 판단한 낱말에서 관문(사용자 판단을 뺀 판정)이 맞았는지 (study_api.feedback_check, 실제 DB 읽기 전용)
2. 개발 대화 세트: 정답 = 사용자 기준 정답 + 리뷰 시트, 그 위에 피드백(사용자 판단이 가장 앞선다). 저장된 LLM 답·위키백과 문서로만 잰다
   (없는 답이 있으면 묻는다. 개발 대화 세트는 낱말이 고정이라 보통 모두 저장돼 있다)
3. 기록: data/eval/scores/verify_log.jsonl 에 한 줄 (git 제외). 피드백 정답은 data/eval/feedback_gold.json
   + 설명이 붙은 비율 (사용자 결정 11-11 '1,2,3 싹다 진행'의 3): 공부 목록 개념 중 근거 확인된 쉬운 설명·출처 문장이 있는 비율 (study_api.coverage).
     목표가 '공부할 내용 전달'이라 관문 수치와 함께 본다. 직전 기록보다 0.05 넘게 떨어지면 알림
4. 알림: 정밀도가 하한(0.8, 사용자 결정 11-10) 아래이거나 직전 기록보다 0.02 넘게 떨어지면 '알림' 줄을 찍는다.
   피드백 정밀도는 관문이 보여 준 낱말 판단이 20개 이상일 때만 하한과 비교한다 (그보다 적으면 한두 개로 크게 흔들린다)
"""
import hashlib
import json
import pathlib
import sqlite3
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

c2, g, ev = R.c2, R.g, R.ev
sys.path.insert(0, str(c2.ROOT / "kit"))
import study_api  # noqa: E402

FLOOR, DROP, MIN_FEEDBACK, COV_DROP = 0.8, 0.02, 20, 0.05
DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
LOG = c2.EVAL / "scores" / "verify_log.jsonl"


def feedback():
    """→ (피드백 검증, 설명이 붙은 비율). 실제 DB가 없거나 공부 기능을 쓴 적이 없으면 빈 값"""
    empty = {"n": 0, "shown": 0, "shown_ok": 0, "precision": None, "wrong": [], "missed": [], "gold": {}}
    if not DB.exists():
        return empty, None
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='judgments'").fetchone():
        return empty, None
    return study_api.feedback_check(con), study_api.coverage(con)


def dev(fb_gold):
    items, gold, D, sfx = c2.dev_set(c2.fixes())
    over = {w: b for w, b in fb_gold.items() if w in gold}
    gold.update(over)
    drop = R.leaked_all(gold)
    items = [x for x in items if x["form"] not in drop]
    c_old, _c_sp, wk = c2.prepare(items, D, sfx)
    docs = []                                             # 0.7.0 코드 속 이름: 앱과 같게 원 답변에서 본다
    if DB.exists():
        con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
        docs = [r[0] for r in con.execute("SELECT text FROM answers") if r[0]]
    code = lambda f: g.code_name(f, [t for t in docs if f in t])
    sel = [x["form"] for x in items if g.final(g.rule_verdict(x["form"], x.get("sents")), c_old.get(x["form"]), wk.get(x["form"]), g.lexicon_verdict(x["form"]), code(x["form"])) == "show"]
    tp, pos = sum(gold[f] for f in sel), sum(gold[x["form"]] for x in items)
    return {"words": len(items), "gold": pos, "shown": len(sel), "precision": round(tp / max(1, len(sel)), 3),
            "recall": round(tp / max(1, pos), 3), "feedback_used": len(over)}


def main():
    g.load_lexicons(ev.LEX)
    fb, cov = feedback()
    (c2.EVAL / "feedback_gold.json").write_bytes(json.dumps(fb["gold"], ensure_ascii=False, indent=0).encode("utf-8"))
    d = dev(fb["gold"])
    rec = {"time": time.strftime("%Y-%m-%d %H:%M"), "gate": hashlib.sha1((c2.ROOT / "kit" / "concept_gate.py").read_bytes()).hexdigest()[:10],
           "feedback": {k: fb[k] for k in ("n", "shown", "shown_ok", "precision")}, "dev": d, "coverage": cov}
    prev = None
    if LOG.exists():
        lines = [l for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
        prev = json.loads(lines[-1]) if lines else None
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    p = fb["precision"]
    print(f"피드백: 판단 {fb['n']}개 (관문이 보여 준 것 {fb['shown']}개 중 사용자도 개념 {fb['shown_ok']}개"
          + (f", 정밀도 {p:.3f})" if p is not None else ")"))
    if fb["wrong"]:
        print("  관문은 보여 줬는데 '아니에요':", ", ".join(fb["wrong"][:30]))
    if fb["missed"]:
        print("  관문은 숨겼는데 '맞아요':", ", ".join(fb["missed"][:30]))
    print(f"개발 대화: 공부 목록 {d['shown']}개, 정밀도 {d['precision']:.3f}, 재현율 {d['recall']:.3f} (피드백으로 바꾼 정답 {d['feedback_used']}개)")
    if cov and cov["shown"]:
        print(f"설명이 붙은 비율: 공부 목록 {cov['shown']}개 중 {cov['explained']:.3f} (근거 확인된 쉬운 설명 {cov['ai_checked']}, 출처 문장 {cov['source']}, 아직 없음 {cov['none']})")
    alerts = []
    pc = (prev or {}).get("coverage")
    if cov and pc and cov["explained"] is not None and pc.get("explained") is not None and pc["explained"] - cov["explained"] > COV_DROP:
        alerts.append(f"설명이 붙은 비율이 직전 기록 {pc['explained']:.3f}에서 {cov['explained']:.3f}로 떨어짐")
    if d["precision"] < FLOOR:
        alerts.append(f"개발 대화 정밀도 {d['precision']:.3f}가 하한 {FLOOR} 아래")
    if prev and prev["dev"]["precision"] - d["precision"] > DROP:
        alerts.append(f"개발 대화 정밀도가 직전 기록({prev['time']}) {prev['dev']['precision']:.3f}에서 {d['precision']:.3f}로 떨어짐")
    if p is not None and fb["shown"] >= MIN_FEEDBACK and p < FLOOR:
        alerts.append(f"피드백 정밀도 {p:.3f}가 하한 {FLOOR} 아래")
    if fb["shown"] < MIN_FEEDBACK:
        print(f"(피드백 정밀도는 관문이 보여 준 낱말 판단이 {MIN_FEEDBACK}개 이상 모이면 하한과 비교합니다. 지금 {fb['shown']}개)")
    for a in alerts:
        print("알림:", a)
    print("기록:", LOG)
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
