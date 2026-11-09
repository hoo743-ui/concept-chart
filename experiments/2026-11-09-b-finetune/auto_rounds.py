# -*- coding: utf-8 -*-
"""무인 라운드: 위키백과 분류를 넓혀 학습 세트만 늘리고 다시 학습한다. 시험 세트는 평가하지 않는다.

    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/auto_rounds.py             라운드 전체 (끊겼으면 끝난 시드는 건너뛴다)
    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/auto_rounds.py --prepare   데이터만 만들고 표본을 보여 준다

지키는 것
- 검증·시험 세트는 고정. 그 표기(문서 제목·영어 제목)를 가진 문서는 새 데이터에서 뺀다. 시험 표기는 이 제외에만 쓴다.
- 라운드는 r1, r2. 문서는 data/raw에 저장돼 있으면 다시 받지 않는다. 디스크 여유 10GB 아래면 멈춘다. 체크포인트는 평균 AP가 가장 좋은 라운드 것만 남긴다.
- v1은 어려운 오답이 0개인 버그가 있었다 (rounds_v1_no_hard.json). 결과는 -v2 이름으로 따로 남긴다.
"""
import collections
import ctypes
import hashlib
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys
import threading
import time

import numpy as np
from rapidfuzz import fuzz, process

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import collect_kowiki as cw  # noqa: E402
from common import ROOT, check_contract, load_pairs, load_split, nfc, norm_key, part  # noqa: E402

SEEDS = (42, 1, 2)
MIN_FREE_GB = 10
MIN_GAIN = 0.005         # 평균 AP가 이만큼 올라야 나아졌다고 본다
MAX_PAGES = 2500         # 라운드당 새로 모으는 문서 상한 (한 번에 수천 요청을 보내지 않게)
HARD_MIN, HARD_PER = 72, 2
RAND_PER_POS = 2
SKIP_RE = re.compile(r"인물|사람|기업|회사|선수|영화|게임|소설|음악|대학|국가|도시|역사|출신|단체|콘퍼런스|수상|일본|미국|중국|대한민국|목록|스텁|토막글|위키백과")
ROUNDS = [
    ("r1-ai-nlp", ["분류:인공지능", "분류:자연어 처리", "분류:컴퓨터 비전", "분류:데이터 마이닝", "분류:통계학"], 1),
    ("r2-dev", ["분류:프로그래밍 언어", "분류:소프트웨어 공학", "분류:데이터베이스", "분류:운영 체제", "분류:컴퓨터 네트워크", "분류:웹 개발", "분류:컴퓨터 보안", "분류:알고리즘", "분류:자료 구조"], 1),
]
VERSION = "v2"
PY = sys.executable
OUT = HERE / "rounds.json"


MIN_RAM_GB = 1.0         # 사용 가능 RAM이 이 아래로 1분 동안 있으면 학습을 멈춘다. 끝난 시드는 다시 돌리면 건너뛴다
RUN_LOG = HERE / "rounds_run.log"
child = None


def log(*a):
    line = " ".join([time.strftime("[%H:%M:%S]"), *map(str, a)])
    print(line, flush=True)
    with open(RUN_LOG, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


class MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong), ("total_virt", ctypes.c_ulonglong), ("avail_virt", ctypes.c_ulonglong), ("avail_ext", ctypes.c_ulonglong)]


def memory_gb():
    """(사용 가능 RAM, 남은 커밋) GB. Windows 전용"""
    m = MemStatus()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.avail_phys / 1e9, m.avail_page / 1e9


def kill_tree(p):
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)


def watch_memory():
    low, tick = 0, 0
    while True:
        ram, commit = memory_gb()
        if tick % 3 == 0:
            log(f"메모리 사용 가능 RAM {ram:.1f}GB, 남은 커밋 {commit:.1f}GB")
        tick += 1
        low = low + 1 if ram < MIN_RAM_GB else 0
        if low >= 3:
            log(f"RAM {ram:.1f}GB 상태가 1분 이어져 학습을 멈춤. 다시 실행하면 끝난 시드는 건너뛴다")
            if child:
                kill_tree(child)                # 가상환경 python.exe는 중간 프로세스라 child.kill()로는 실제 학습이 안 꺼진다
            os._exit(3)
        time.sleep(20)


def keep_awake():
    """이 프로세스가 도는 동안만 절전을 막는다. 끝나면 저절로 풀린다"""
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)


def free_gb():
    return shutil.disk_usage(ROOT).free / 1e9


def clean(title):
    return nfc(re.sub(r"\s*\([^()]*\)\s*$", "", title))


def build_extra(tag, roots, depth, known_ids, known_keys, held, extra_rows):
    """새 문서 → 학습 전용 쌍. known_keys(이미 있는 쌍), held(검증·시험 표기)와 겹치면 뺀다"""
    raw = ROOT / "data" / "raw" / f"kowiki_{tag}"
    if (raw / "pages.jsonl").exists():
        pages = {r["pageid"]: r for r in map(json.loads, (raw / "pages.jsonl").read_text(encoding="utf-8").splitlines())}
    else:
        pages, _ = cw.crawl(roots, depth, set(), SKIP_RE, MAX_PAGES)
        raw.mkdir(parents=True, exist_ok=True)
        with open(raw / "pages.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for r in sorted(pages.values(), key=lambda r: r["pageid"]):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    concepts, cut = {}, collections.Counter()
    for p in pages.values():
        if p["pageid"] in known_ids:
            cut["이미 있는 문서"] += 1
            continue
        ko, en = clean(p["title"]), [clean(x) for x in p["en"]]
        if not en:
            cut["영어 링크 없음"] += 1
            continue
        if norm_key(ko) in held or norm_key(en[0]) in held:
            cut["검증·시험과 같은 표기"] += 1
            continue
        if norm_key(ko) == norm_key(en[0]):
            cut["한영 제목 같음"] += 1
            continue
        concepts["kowiki:" + str(p["pageid"])] = (ko, en[0])
    rows = []

    def add(a, b, label, kind, ca, cb, source):
        key = tuple(sorted((norm_key(a), norm_key(b))))
        if key in known_keys or key[0] == key[1]:
            return False
        known_keys.add(key)
        rows.append({"a": a, "b": b, "label": label, "kind": kind, "concept_a": ca, "concept_b": cb, "source": source})
        return True
    for c, (ko, en) in concepts.items():
        add(ko, en, 1, "pos", c, c, "kowiki:langlink")
    ids = sorted(concepts)
    if len(ids) > 1:
        for side in (0, 1):
            names = [concepts[c][side].lower() for c in ids]
            m = process.cdist(names, names, scorer=fuzz.ratio, score_cutoff=HARD_MIN, dtype=np.int16, workers=-1)    # 부호 있는 정수: uint8에 -를 붙이면 값이 뒤집혀 0점이 맨 앞에 온다
            np.fill_diagonal(m, 0)
            for i in range(len(ids)):
                if m[i].max() < HARD_MIN or len(names[i]) < 3:
                    continue
                for j in np.argsort(-m[i], kind="stable")[:HARD_PER]:
                    if m[i, j] >= HARD_MIN and len(names[j]) >= 3:
                        a, b = ids[i], ids[j]
                        add(concepts[a][side], concepts[b][side], 0, "hard", a, b, "kowiki:similar")
                        add(concepts[a][0], concepts[b][1], 0, "hard", a, b, "kowiki:similar-cross")
    rng = random.Random(42)
    n_pos = sum(r["label"] for r in rows)
    made = tries = 0
    while made < n_pos * RAND_PER_POS and tries < n_pos * RAND_PER_POS * 50 and len(ids) > 1:
        tries += 1
        a, b = rng.sample(ids, 2)
        if add(rng.choice(concepts[a]), rng.choice(concepts[b]), 0, "rand", a, b, "kowiki:random"):
            made += 1
    known_ids |= {p["pageid"] for p in pages.values()}
    log(tag, "새 문서", len(pages), "제외", dict(cut), "새 쌍", len(rows), dict(collections.Counter(r["kind"] for r in rows)))
    extra_rows += rows
    check_contract(extra_rows)
    path = ROOT / "data" / "processed" / f"B_extra_{tag}-{VERSION}.jsonl"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in extra_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def train_round(tag, extra):
    res = []
    sha = hashlib.sha256(extra.read_bytes()).hexdigest()
    for s in SEEDS:
        run = HERE / f"{tag}-seed{s}"
        done = (run / "metrics.json").exists() and json.loads((run / "config.json").read_text(encoding="utf-8")).get("extra_sha256") == sha
        if done:
            log(tag, f"seed{s} 이미 끝남, 건너뜀")
        else:
            (run / "metrics.json").unlink(missing_ok=True)
            cmd = [PY, str(HERE / "train.py"), "train", "--seed", str(s), "--tag", tag, "--extra", str(extra)]
            global child
            child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONUTF8="1"))
            _, err = child.communicate()
            if child.returncode != 0:
                raise RuntimeError(f"{tag} seed{s} 실패: {err[-400:]}")
        m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))["val"]
        log(tag, f"seed{s}", f"AP {m['ap']:.4f} AUC {m['auc']:.4f} 어려운 오답 {m['hard_fp']:.3f} 한영 재현 {m['cross_recall']:.3f} best {m['best_epoch']}")
        res.append(m)
    return res


def mean(res, k):
    return sum(r[k] for r in res) / len(res)


def main():
    all_rows, split = load_pairs(), load_split()
    va, te = part(all_rows, split["val"]), part(all_rows, split["test"])
    held = {norm_key(x) for r in va + te for x in (r["a"], r["b"])}          # 표기 제외에만 쓴다. 시험 점수는 재지 않는다
    known_keys = {tuple(sorted((norm_key(r["a"]), norm_key(r["b"])))) for r in all_rows}
    known_ids = {json.loads(line)["pageid"] for line in (ROOT / "data" / "raw" / "kowiki_ml" / "pages.jsonl").read_text(encoding="utf-8").splitlines()}
    base = [json.loads((HERE / f"seed{s}" / "metrics.json").read_text(encoding="utf-8"))["val"] for s in SEEDS]
    results = [{"round": "r0-base", "train_pairs": len(part(all_rows, split["train"])), "ap_mean": mean(base, "ap"), "seeds": base}]
    best_ap, best_tag = results[0]["ap_mean"], "r0"
    extra_rows = []
    prepare = "--prepare" in sys.argv
    if not prepare:
        keep_awake()
        threading.Thread(target=watch_memory, daemon=True).start()
    for tag, roots, depth in ROUNDS:
        if free_gb() < MIN_FREE_GB:
            log("디스크 여유 부족으로 멈춤", round(free_gb(), 1))
            break
        try:
            extra = build_extra(tag, roots, depth, known_ids, known_keys, held, extra_rows)
            if prepare:
                continue
            tag = f"{tag}-{VERSION}"
            res = train_round(tag, extra)
        except Exception as e:  # noqa: BLE001
            log("라운드 실패, 멈춤:", type(e).__name__, str(e)[:300])
            results.append({"round": tag, "error": str(e)[:300]})
            break
        ap = mean(res, "ap")
        results.append({"round": tag, "train_pairs": results[0]["train_pairs"] + len(extra_rows), "extra_sha256": hashlib.sha256(extra.read_bytes()).hexdigest(),
                        "ap_mean": ap, "hard_fp_mean": mean(res, "hard_fp"), "cross_recall_mean": mean(res, "cross_recall"), "seeds": res})
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        log(tag, f"평균 AP {ap:.4f} (지금까지 최고 {best_ap:.4f}, {best_tag})")
        if ap > best_ap:
            for f in (ROOT / "models").glob(f"b-finetune-{best_tag}-seed*-best.pt"):
                f.unlink()
            best_ap, best_tag = ap, tag
        else:
            for f in (ROOT / "models").glob(f"b-finetune-{tag}-seed*-best.pt"):
                f.unlink()
    if prepare:
        rng = random.Random(7)
        hard = [r for r in extra_rows if r["kind"] == "hard"]
        log("쌍 합계", len(extra_rows), dict(collections.Counter(r["kind"] for r in extra_rows)), dict(collections.Counter(r["source"] for r in extra_rows)))
        for r in rng.sample(hard, min(50, len(hard))):
            print(f"  {r['a']}  |  {r['b']}")
        return
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    log("끝. 최고", best_tag, round(best_ap, 4), "디스크 여유", round(free_gb(), 1), "GB, 요청", cw.requests_made)


if __name__ == "__main__":
    main()
