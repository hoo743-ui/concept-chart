# -*- coding: utf-8 -*-
"""보정 2차 (사용자 결정 11-10: 정밀도 하한 0.8, 데이터 확장안): 넓힌 보정용 묶음(20분야)으로 칸 보정을 하고 개발 대화 세트에서 버티는지 본다.

    python experiments/2026-11-10-general-gate/calibrate2.py

보정용 묶음 (모두 이미 본 세트):
- 조정용(경제·의학·법·역사·생물), 예전 holdout(화학·심리학·회계·음악·지구과학), 새 분야(물리·천문·철학·언어학·환경), IT 조정용 tune2(프로그래밍·서버·AI·네트워크·일상 컴퓨터)
점검: 개발 대화(사용자 실제 대화). 시험 세트(test)는 여기서 열지 않는다.
- 없는 LLM 답(지금 질문, 그리고 전문 뜻만 있는 낱말의 새 질문)과 위키백과 문서는 물어서 저장한다 (evaluate·prompt_r8과 같은 캐시).
- 정답: 각 세트 gold + review_sheet_filled.csv(사용자 기준). 질문 예시와 겹친 낱말은 채점에서 뺀다.
- 칸 보정 방법은 calibrate.py와 같다.
"""
import collections
import csv
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import calibrate as cb  # noqa: E402
import prompt_r8 as p  # noqa: E402

g, ev, rs, ROOT = p.g, p.ev, p.rs, p.ROOT
EVAL = ROOT / "data" / "eval"
ASK_OLD = hashlib.sha1(g.judge_prompt("@@", ["@@"]).encode("utf-8")).hexdigest()[:10]
ASK_NEW = p.tag(p.judge_prompt)


def examples_text():
    return " ".join(m.group(1) for fn in (g.judge_prompt, p.judge_prompt) for m in re.finditer(r"예:([^\n]*)", fn("@@", [])))


def leaked(words):
    t = examples_text()
    return {w for w in words if len(w) >= 2 and re.search(rf"(?<![가-힣A-Za-z]){re.escape(w)}(?![가-힣A-Za-z])", t)}


def fixes():
    with open(EVAL / "review_sheet_filled.csv", encoding="utf-8-sig", newline="") as f:
        return {(r[0], r[1]): r[4] == "1" for r in list(csv.reader(f))[1:] if r[4] in ("0", "1")}


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def general_set(name, D, split, fx, sheet_name):
    ws = [x for x in load(D / "words.json") if x["split"] == split]
    gold = load(D / "gold.json")
    if sheet_name == "새 분야":
        for w in ("번역", "통과", "형태소"):
            gold.pop(w, None)
    ws = [x for x in ws if x["form"] in gold]
    gold = {x["form"]: bool(gold[x["form"]]) for x in ws}
    gold.update({w: b for (s, w), b in fx.items() if s == sheet_name and w in gold})
    return ws, gold, D, ""


def dev_set(fx):
    items, gold, *_ = rs.dev()
    gold = dict(gold)
    gold.update({w: b for (s, w), b in fx.items() if s == "개발 대화" and w in gold})
    return items, gold, ev.DEV_D, "_dev"


def prepare(items, D, sfx):
    """LLM 답·위키백과 문서를 채운다 (이미 있으면 다시 묻지 않는다)"""
    c_old = ev.judge_all(items, D / f"llm{sfx}_q{ASK_OLD}.json") if sfx else ev.judge_all(items, D / f"llm_q{ASK_OLD}.json")
    special = lambda x: p.judged(x) and g.lexicon_verdict(x["form"]) == "special"
    c_sp = p.ask(items, D / f"llm{sfx}_r8_{ASK_NEW}.json", p.judge_prompt, g.JUDGE_SCHEMA, "is_term", special)
    either = {f: (c_old.get(f) is True or c_sp.get(f) is True) for f in {x["form"] for x in items}}
    wk = ev.sourced_all(items, either, D / "wiki.json")
    return c_old, c_sp, wk


def rows(items, gold, c_old, c_sp, wk):
    out = []
    for x in items:
        out.append((cb.cell(x, c_old, c_sp, wk), gold[x["form"]], cb.fixed(x), x["form"],
                    g.final(g.rule_verdict(x["form"], x.get("sents")), c_old.get(x["form"]), wk.get(x["form"]), g.lexicon_verdict(x["form"])) == "show"))
    return out


def fit(pool):
    t = collections.defaultdict(lambda: [0, 0])
    for k, y, fixed, _f, _cur in pool:
        if k is not None:
            t[k][0] += y
            t[k][1] += 1
    order = sorted((k for k, (tp, n) in t.items() if n >= cb.MIN_N), key=lambda k: -(t[k][0] + 1) / (t[k][1] + 2))
    tp = sum(y for k, y, fixed, *_ in pool if fixed)
    n = sum(1 for k, y, fixed, *_ in pool if fixed)
    best = []
    for i, k in enumerate(order, 1):
        tp, n = tp + t[k][0], n + t[k][1]
        if tp / n >= cb.FLOOR:
            best = order[:i]
    return set(best), t


def score(rs_, opened):
    pos = sum(y for _k, y, *_ in rs_)
    cal = [(y, f) for k, y, fixed, f, _c in rs_ if fixed or k in opened]
    cur = [(y, f) for k, y, fixed, f, c in rs_ if c]
    def pr(sel):
        tp = sum(y for y, _ in sel)
        return len(sel), tp / max(1, len(sel)), tp / max(1, pos)
    return pr(cur), pr(cal), sorted(f for y, f in cal if not y)


def main():
    g.load_lexicons(ev.LEX)
    fx = fixes()
    sets = {"조정용": general_set("조정용", EVAL / "general", "tune", fx, "조정용"),
            "예전 holdout": general_set("예전 holdout", EVAL / "general", "holdout", fx, "예전 holdout"),
            "새 분야": general_set("새 분야", EVAL / "fresh", "holdout", fx, "새 분야"),
            "IT 조정용": general_set("IT 조정용", EVAL / "tune2", "tune", fx, "IT 조정용"),
            "개발 대화": dev_set(fx)}
    data = {}
    for name, (items, gold, D, sfx) in sets.items():
        drop = leaked(gold)
        items = [x for x in items if x["form"] not in drop]
        print(f"{name}: 낱말 {len(items)} 개념 {sum(gold[x['form']] for x in items)} (질문 예시와 겹쳐 뺀 낱말 {sorted(drop)})", flush=True)
        data[name] = rows(items, gold, *prepare(items, D, sfx))
    pool = [r for name, rr in data.items() if name != "개발 대화" for r in rr]
    opened, t = fit(pool)
    print(f"\n보정용 묶음 {len(pool)}개 낱말에서 연 칸 {len(opened)}개 (칸: 규칙, 분야 사전, 지금 질문, 새 질문, 위키백과 문서 → 맞음/수)")
    for k in sorted(opened, key=lambda k: -(t[k][0] + 1) / (t[k][1] + 2)):
        print("  ", k, f"{t[k][0]}/{t[k][1]}")
    print()
    for name, rr in list(data.items()) + [("보정용 묶음 전체", pool)]:
        (n0, p0, r0), (n1, p1, r1), wrong = score(rr, opened)
        print(f"{name:10} 지금 관문 {n0:4} 정밀도 {p0:.3f} 재현율 {r0:.3f} | 보정 {n1:4} 정밀도 {p1:.3f} 재현율 {r1:.3f}")
        if name == "개발 대화":
            print("   보정 오탐:", ", ".join(wrong)[:600])


if __name__ == "__main__":
    main()
