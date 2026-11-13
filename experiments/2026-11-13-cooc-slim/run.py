"""'함께 나온 개념'(cooc) 표 줄이기 실험 (11-13, 사용자 승인: 실험부터)

실제 저장 파일은 읽기만 하고, 사본(임시 폴더)에서만 잰다. 결과 파일에는 숫자만 쓴다 (개념 이름·대화 문장 없음).

방식
  A  지금 방식: 답변 하나의 개념끼리 모든 짝 (기준)
  B  답변마다 처음 나온 순서로 개념 N개만 짝 (N=12, 24)
  C  답변마다 전체에서 자주 나온 개념 12개만 짝 (마지막 시점의 빈도를 쓰므로 실제보다 조금 유리)
  D  공부 목록에 보이는 개념끼리만 짝 (지금 판정 기준)
  E  하루에 한 번 정리: 개념마다 짝을 n 큰 순(같으면 이름순)으로 K개만 남김 (K=60·100·150). 날짜순으로 다시 쌓으며 흉내 낸다
  F  한쪽이라도 공부 개념인 짝만 (D처럼 마지막 판정을 쓰므로 실제보다 유리하다: 새 개념은 들어올 때 아직 판정 전이다)

재는 것
  - 줄 수, 표만 따로 담은 SQLite 파일 크기 (VACUUM 뒤)
  - 노트의 관련 개념 6개 (kit/study_api.detail과 같은 규칙: n 큰 순 상위 60개 중 공부 개념 6개)가 기준과 똑같은 개념 비율, 평균 겹침
  - 정의 검색어 2개 (kit/serve.context_terms: n 큰 순 상위 2개)가 기준과 같은 개념 비율
  - 실행 중 최대 메모리 (tracemalloc, 파이썬 객체 기준)

실행: python experiments/2026-11-13-cooc-slim/run.py [--db 경로] [--api http://127.0.0.1:8765]
"""
import argparse
import json
import pathlib
import sqlite3
import tempfile
import time
import tracemalloc
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from itertools import permutations

HERE = pathlib.Path(__file__).resolve().parent
RELATED_POOL, RELATED_N, CONTEXT_N = 60, 6, 2


def snapshot(src: pathlib.Path, dst: pathlib.Path):
    """서버가 쓰는 중이어도 일관된 사본 (SQLite backup API, 원본은 읽기 전용으로 연다)"""
    s = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    d = sqlite3.connect(str(dst))
    s.backup(d)
    s.close()
    return d


def answers_of(con):
    """답변 하나 = mentions의 (session, ts, role, question) 묶음. 개념은 처음 나온 순서(rowid)대로"""
    groups = defaultdict(list)
    for rid, concept, ts, sess, role, q in con.execute("SELECT rowid, concept, ts, session, role, question FROM mentions ORDER BY rowid"):
        groups[(sess, ts, role, q)].append(concept)
    out = []
    for (sess, ts, role, q), cs in groups.items():
        seen, order = set(), []
        for c in cs:
            if c not in seen:
                seen.add(c)
                order.append(c)
        out.append((ts, order))
    out.sort(key=lambda x: x[0])
    return out


def pairs_all(order):
    return permutations(order, 2)


def build(answers, pick, compact_k=None, keep=None):
    """pick(order) → 짝을 만들 개념 목록. compact_k가 있으면 날짜가 바뀔 때마다 개념별 상위 K개만 남긴다"""
    cooc = defaultdict(int)
    day = None
    for ts, order in answers:
        d = ts[:10]
        if compact_k and day is not None and d != day:
            compact(cooc, compact_k)
        day = d
        for a, b in permutations(pick(order), 2):
            if keep is None or keep(a, b):
                cooc[(a, b)] += 1
    if compact_k:
        compact(cooc, compact_k)
    return cooc


def compact(cooc, k):
    by = defaultdict(list)
    for (a, b), n in cooc.items():
        by[a].append((-n, b))
    keep = set()
    for a, lst in by.items():
        lst.sort()
        keep.update((a, b) for _, b in lst[:k])
    for key in [x for x in cooc if x not in keep]:
        del cooc[key]


def ranked(cooc):
    by = defaultdict(list)
    for (a, b), n in cooc.items():
        by[a].append((-n, b))
    for lst in by.values():
        lst.sort()
    return by


def related(by, a, shown):
    out = []
    for _, b in by.get(a, [])[:RELATED_POOL]:
        if b in shown:
            out.append(b)
            if len(out) >= RELATED_N:
                break
    return out


def table_bytes(cooc, tmp: pathlib.Path, name):
    p = tmp / f"cooc_{name}.sqlite"
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE cooc (a TEXT, b TEXT, n INTEGER, PRIMARY KEY (a, b))")
    con.executemany("INSERT INTO cooc VALUES (?,?,?)", ((a, b, n) for (a, b), n in cooc.items()))
    con.commit()
    con.execute("VACUUM")
    con.close()
    size = p.stat().st_size
    p.unlink()
    return size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(pathlib.Path.home() / ".claude" / "concept-chart.sqlite"))
    ap.add_argument("--api", default="http://127.0.0.1:8765")
    args = ap.parse_args()

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cooc-slim-"))
    con = snapshot(pathlib.Path(args.db), tmp / "copy.sqlite")
    con.execute("VACUUM")
    db_bytes = (tmp / "copy.sqlite").stat().st_size
    real = {(a, b): n for a, b, n in con.execute("SELECT a, b, n FROM cooc")}
    freq = dict(con.execute("SELECT concept, n FROM freq"))
    answers = answers_of(con)
    with urllib.request.urlopen(f"{args.api}/api/study/concepts?view=show&k=100000", timeout=60) as r:
        shown_items = json.load(r)["items"]
    shown = {x["id"] for x in shown_items}

    # 다시 쌓은 기준이 실제 표와 같은지 먼저 확인 (다르면 묶는 방법이 틀린 것)
    base = build(answers, lambda o: o)
    same_rows = base == real
    diff = sum(1 for k in set(base) | set(real) if base.get(k) != real.get(k))

    # 기준 관련 개념이 실제 노트 API와 같은지 몇 개 확인
    base_by = ranked(base)
    api_match, api_checked = 0, 0
    for x in shown_items[:30]:
        try:
            with urllib.request.urlopen(f"{args.api}/api/study/concept/{urllib.request.quote(x['id'])}", timeout=30) as r:
                got = [y["id"] for y in json.load(r).get("related", [])]
        except Exception:  # noqa: BLE001
            continue
        api_checked += 1
        api_match += got == related(base_by, x["id"], shown)

    variants = {
        "A_all": dict(pick=lambda o: o),
        "B_first12": dict(pick=lambda o: o[:12]),
        "B_first24": dict(pick=lambda o: o[:24]),
        "C_freq12": dict(pick=lambda o: sorted(o, key=lambda c: (-freq.get(c, 0), c))[:12]),
        "D_shown_only": dict(pick=lambda o: [c for c in o if c in shown]),
        "E_daily_top60": dict(pick=lambda o: o, compact_k=60),
        "E_daily_top100": dict(pick=lambda o: o, compact_k=100),
        "E_daily_top150": dict(pick=lambda o: o, compact_k=150),
        "F_either_shown": dict(pick=lambda o: o, keep=lambda a, b: a in shown or b in shown),
    }
    base_rel = {a: related(base_by, a, shown) for a in shown}
    all_concepts = set(freq)
    base_ctx = {a: [b for _, b in base_by.get(a, [])[:CONTEXT_N]] for a in all_concepts}
    results = {}
    for name, v in variants.items():
        tracemalloc.start()
        t0 = time.perf_counter()
        cooc = build(answers, v["pick"], v.get("compact_k"), v.get("keep"))
        secs = time.perf_counter() - t0
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        by = ranked(cooc)
        rel_same = rel_overlap = 0
        for a in shown:
            got = related(by, a, shown)
            want = base_rel[a]
            rel_same += got == want
            rel_overlap += (len(set(got) & set(want)) / len(want)) if want else (1.0 if not got else 0.0)
        ctx_same = sum(1 for a in all_concepts if [b for _, b in by.get(a, [])[:CONTEXT_N]] == base_ctx[a])
        ctx_same_shown = sum(1 for a in shown if [b for _, b in by.get(a, [])[:CONTEXT_N]] == base_ctx.get(a))
        max_pairs_one_answer = max(len(v["pick"](o)) * (len(v["pick"](o)) - 1) for _, o in answers)
        results[name] = {
            "rows": len(cooc), "table_bytes": table_bytes(cooc, tmp, name), "build_seconds": round(secs, 2), "peak_python_mb": round(peak / 1e6, 1),
            "max_rows_from_one_answer": max_pairs_one_answer,
            "related_identical": round(rel_same / len(shown), 4), "related_overlap_mean": round(rel_overlap / len(shown), 4),
            "context_identical": round(ctx_same / len(all_concepts), 4), "context_identical_shown": round(ctx_same_shown / len(shown), 4),
        }
        del cooc, by
    con.close()
    for p in tmp.iterdir():
        p.unlink()
    tmp.rmdir()

    out = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {"answers": len(answers), "days": len({ts[:10] for ts, _ in answers}), "concepts": len(freq), "shown_concepts": len(shown),
                 "db_bytes_after_vacuum": db_bytes, "concepts_per_answer_mean": round(sum(len(o) for _, o in answers) / len(answers), 1),
                 "concepts_per_answer_max": max(len(o) for _, o in answers)},
        "check": {"rebuilt_equals_real_table": same_rows, "rows_differing": diff, "related_matches_api": f"{api_match}/{api_checked}"},
        "variants": results,
    }
    (HERE / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
