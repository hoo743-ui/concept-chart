# -*- coding: utf-8 -*-
"""시뮬레이터 결과 → 결과 페이지용 데이터 (results/page_data.json)

    python sim/make_page_data.py           # results/A·B·C.json + badge_eval.json + concepts.py → page_data.json
    python sim/make_page_data.py --check   # 다시 만든 결과가 지금 page_data.json과 같은지만 확인

하는 일: 숫자 반올림(소수 셋째 자리), 페이지에 안 쓰는 필드 빼기, 그리드 결과 압축,
공부 노트·개념·페르소나 데이터 붙이기. 새로 계산하는 지표는 없다.
추세 배지 방식 비교표는 results/badge_eval.json(기록값)을 그대로 쓴다 — 파일 안 _note 참고.
"""
import argparse
import json
import pathlib
import sys

try:  # 출력이 파이프·파일로 갈 때(Windows 기본 인코딩)도 한글 메시지가 깨지거나 멈추지 않게
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from concepts import CONCEPTS, DEFS, DISPLAY, HARD_NEG, PERSONAS, VARIANTS  # noqa: E402
from pipeline import oracle_concept, sentence_kind  # noqa: E402

RES = HERE / "results"
OUT = RES / "page_data.json"
GRID_METRICS = ["ndcg", "p10", "intrusion", "burst", "rise", "fade", "churn", "stale"]


def load(name):
    with open(RES / name, encoding="utf-8") as f:
        return json.load(f)


def r3(x):
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, dict):
        return {k: r3(v) for k, v in x.items()}
    if isinstance(x, list):
        return [r3(v) for v in x]
    return x


def item(it):
    return {"term": it["term"], "cid": it["cid"], "kind": it["kind"],
            "spark": [int(v) for v in it["spark"]],          # 주간 세션 수 (정수)
            "badge": it["badge"], "z": round(it["z"], 2), "gt": r3(it["gt"]),
            "rs": it["recent_sessions"], "g": it["in_glossary"], "s": r3(it["score"])}


def page_A(A, badge_eval):
    ui = {}
    for p, u in A["ui"].items():
        ui[p] = {"name": u["name"], "domain": u["domain"],
                 "weeks": [{"week": w["week"], "day": w["day"],
                            "ours": [item(i) for i in w["ours"]], "tf": [item(i) for i in w["tf"]],
                            "gt_top": r3(w["gt_top"]), "new_terms": w["new_terms"]} for w in u["weeks"]],
                 "lines": r3(u["lines"]), "traces": r3(u["traces"]), "sample": u["sample"],
                 "n_sessions": u["n_sessions"], "n_utts": u["n_utts"]}
    grid = A["config"]["grid"]
    badge = {k: v for k, v in badge_eval.items() if not k.startswith("_")}
    return {"table": r3(A["table"]), "ci": r3(A["ci"]), "ablation": r3(A["ablation"]), "badge": r3(badge),
            "fi": r3(A["feature_importance"]), "config": r3(A["config"]), "churn_true": r3(A["churn_true"]),
            "grid_keys": r3(grid), "grid_metrics": GRID_METRICS,
            "grid": {k: [round(v[m], 3) for m in GRID_METRICS] for k, v in A["grid_test"].items()},
            "ui": ui, "grid_keys_str": {k: [str(x) for x in v] for k, v in grid.items()}}


def confusables():
    """헷갈리기 쉬운 개념: HARD_NEG 쌍을 양방향으로 (나온 순서대로)"""
    conf = {c: [] for c, _ in CONCEPTS}
    for a, b in HARD_NEG:
        ca, cb = oracle_concept(a), oracle_concept(b)
        if not ca or not cb or ca == cb:
            continue
        for x, y in ((ca, cb), (cb, ca)):
            if DISPLAY[y] not in conf[x]:
                conf[x].append(DISPLAY[y])
    return conf


def build():
    A, B, C = load("A.json"), load("B.json"), load("C.json")
    conf = confusables()
    return {
        "A": page_A(A, load("badge_eval.json")),
        "B": {k: r3(v) for k, v in B.items() if k != "not_measured"},
        "C": {k: r3(v) for k, v in C.items() if k != "not_measured"},
        "notes": {c: {"def_": s[0], "others": [{"s": x, "kind": sentence_kind(x)} for x in s[1:]]} for c, s in DEFS.items()},
        "concepts": {c: {"name": DISPLAY[c], "variants": VARIANTS[c], "conf": conf[c]} for c, _ in CONCEPTS},
        "personas": {p: {"name": v["name"], "domain": v["domain"]} for p, v in PERSONAS.items()},
    }


def dump(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="파일을 쓰지 않고 지금 page_data.json과 같은지만 확인")
    args = ap.parse_args()
    text = dump(build())
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("[make_page_data] page_data.json:", "최신 상태" if same else "다름 → python sim/make_page_data.py 로 다시 만들기")
        sys.exit(0 if same else 1)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print(f"[make_page_data] {OUT.relative_to(HERE.parent).as_posix()} 생성 ({len(text.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
