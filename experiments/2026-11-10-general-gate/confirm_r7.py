# -*- coding: utf-8 -*-
"""r7 칸 신호 확인 (사용자 결정 11-11 '1순위부터 진행'): 동사로 쓰임·기초 어휘 신호를 처음 보는 분야(확인 세트)에서 확인한다.

    python experiments/2026-11-10-general-gate/make_answers.py --set=confirm      # 질문: questions_confirm.json
    python experiments/2026-11-10-general-gate/evaluate.py words --set=confirm
    python experiments/2026-11-10-general-gate/confirm_r7.py list    # r7 칸 낱말만 → data/eval/confirm/r7_words.txt (신호 값은 보여 주지 않는다)
    (정답 표시: data/eval/confirm/r7_gold.json {낱말: true/false}, 사용자 기준, 신호를 보기 전에)
    python experiments/2026-11-10-general-gate/confirm_r7.py score   # 확인 세트 + 지금까지의 세트

신호 (r7 칸 = 일상 뜻도 있는 낱말 + LLM 인정 + 위키백과 문서, concept_gate.final의 mixed 줄):
- 동사로 쓰임: 그 낱말이 나온 자리의 절반 이상에서 바로 뒤에 하다·되다·시키다 꼴이 붙는다 (유출되다, 반영하다)
- 기초 어휘: 국립국어원 「한국어 학습용 어휘 목록」 명사 (data/processed/lexicon/basicvocab.tsv)
둘 중 하나에 걸리면 공부 목록에서 뺀다. 신호는 조정용·예전 holdout·새 분야·IT 조정용·개발 대화를 보고 골랐다 (11-11).
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

c2, g, ev = R.c2, R.g, R.ev
D = c2.EVAL / "confirm"
VERB = re.compile(r"^(하|되|시키|된|한|할|해|돼|됨|함|됩|합|했|됐)")


def basic():
    p = c2.ROOT / "data" / "processed" / "lexicon" / "basicvocab.tsv"
    return {l.split("\t")[0] for l in p.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")}


def verb_used(form, sents):
    occ = [s[s.find(form) + len(form):] for s in sents or () if form in s]
    return bool(occ) and sum(bool(VERB.match(a)) for a in occ) / len(occ) >= 0.5


def blocked(x, B):
    return verb_used(x["form"], x.get("sents")) or g.key(x["form"]) in B


def confirm_items():
    ws = [x for x in json.loads((D / "words.json").read_text(encoding="utf-8")) if x["split"] == "holdout"]
    drop = R.leaked_all({x["form"] for x in ws})
    return [x for x in ws if x["form"] not in drop], drop


def r7_items(items, D_, sfx):
    c_old, _c_sp, wk = c2.prepare(items, D_, sfx)
    return [x for x in items if R.r7(x, c_old, wk)]


def line(name, xs, gold, B):
    keep = [x for x in xs if not blocked(x, B)]
    tp0, tp1 = sum(gold[x["form"]] for x in xs), sum(gold[x["form"]] for x in keep)
    lost = sorted(x["form"] for x in xs if blocked(x, B) and gold[x["form"]])
    gone = sum(1 for x in xs if blocked(x, B) and not gold[x["form"]])
    print(f"{name:10} r7 칸 지금 {tp0}/{len(xs)} ({tp0 / max(1, len(xs)):.3f}) → 신호 {tp1}/{len(keep)} ({tp1 / max(1, len(keep)):.3f}) | 빠진 오탐 {gone}, 잃은 개념 {lost}")
    return tp0, len(xs), tp1, len(keep)


def main():
    g.load_lexicons(ev.LEX)
    items, drop = confirm_items()
    xs = r7_items(items, D, "")
    if sys.argv[1] == "list":
        (D / "r7_words.txt").write_text("\n".join(sorted(x["form"] for x in xs)) + "\n", encoding="utf-8")
        print(f"확인 세트 낱말 {len(items)} (예시와 겹쳐 뺀 낱말 {sorted(drop)}), r7 칸 {len(xs)}개 → {D / 'r7_words.txt'}")
        return
    gold = {k: bool(v) for k, v in json.loads((D / "r7_gold.json").read_text(encoding="utf-8")).items()}
    missing = [x["form"] for x in xs if x["form"] not in gold]
    assert not missing, f"정답 없는 낱말: {missing}"
    B = basic()
    print("확인 세트 (처음 보는 분야, 신호를 고를 때 보지 않음)")
    line("확인 세트", xs, gold, B)
    print("\n신호를 고를 때 본 세트 (참고)")
    fx = c2.fixes()
    for name, (its, gd, D_, sfx) in {"조정용": c2.general_set("조정용", c2.EVAL / "general", "tune", fx, "조정용"),
                                     "예전 holdout": c2.general_set("예전 holdout", c2.EVAL / "general", "holdout", fx, "예전 holdout"),
                                     "새 분야": c2.general_set("새 분야", c2.EVAL / "fresh", "holdout", fx, "새 분야"),
                                     "IT 조정용": c2.general_set("IT 조정용", c2.EVAL / "tune2", "tune", fx, "IT 조정용"),
                                     "개발 대화": c2.dev_set(fx)}.items():
        dr = R.leaked_all(gd)
        line(name, r7_items([x for x in its if x["form"] not in dr], D_, sfx), gd, B)


if __name__ == "__main__":
    main()
