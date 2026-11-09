# -*- coding: utf-8 -*-
"""두 번째 정답 시트: 내 대화 개념의 모든 쌍을 모델로 점수 매겨, 철자로는 못 찾는 번역 쌍 후보를 뽑는다 (data/eval/my_sheet2.csv, git 제외).

    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/make_sheet2.py

- 파인튜닝 r2 상위 TOP_FT쌍 + 글자 BiLSTM 상위 TOP_CHAR쌍 (시드 3개 평균). 첫 시트의 쌍은 뺀다.
- 모델이 고른 쌍이라 편향이 있다. 빠진 같은 쌍을 찾는 용도이고, 재현율이나 AP를 재는 데 쓰지 않는다.
- 개인 데이터라 표기를 출력하지 않는다. 시트에 점수를 넣지 않는다 (정답 판단에 영향을 주지 않게).
"""
import collections
import csv
import pathlib
import random
import sqlite3
import sys
import threading

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(HERE), str(HERE.parent)]

import numpy as np  # noqa: E402
import torch  # noqa: E402
import score_eval as se  # noqa: E402
import train as ft  # noqa: E402
import train_char as tc  # noqa: E402
from common import cross_script, nfc, norm_key  # noqa: E402

DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
OUT = ROOT / "data" / "eval" / "my_sheet2.csv"
TOP_FT, TOP_CHAR = 40, 20


@torch.no_grad()
def pair_scores(emb, head, I, J):
    out = []
    for k in range(0, len(I), 4096):
        u, v = emb[I[k:k + 4096]], emb[J[k:k + 4096]]
        out.append(torch.sigmoid(head(torch.cat([u, v, (u - v).abs(), u * v], 1)).squeeze(1)).cpu())
    return torch.cat(out).numpy()


@torch.no_grad()
def finetune(names, I, J):
    total = np.zeros(len(I))
    for s in se.SEEDS:
        net = ft.PairNet(ft.MODEL).to(ft.DEVICE)
        net.load_state_dict(torch.load(ROOT / "models" / f"b-finetune-r2-dev-v2-seed{s}-best.pt", map_location=ft.DEVICE))
        net.eval()
        emb = torch.cat([net.embed(names[k:k + 64]) for k in range(0, len(names), 64)])
        total += pair_scores(emb, net.head, I, J)
        del net, emb
        torch.cuda.empty_cache()
    return total / len(se.SEEDS)


@torch.no_grad()
def bilstm(names, I, J):
    total = np.zeros(len(I))
    for s in se.SEEDS:
        ck = torch.load(ROOT / "models" / f"b-char-bilstm-seed{s}-best.pt", map_location=tc.DEVICE)
        net = tc.CharNet("bilstm", len(ck["vocab"]) + 2).to(tc.DEVICE)
        net.load_state_dict(ck["state"])
        net.eval()
        parts = [net.embed(*tc.encode(names[k:k + 256], ck["vocab"], tc.DEVICE)) for k in range(0, len(names), 256)]
        total += pair_scores(torch.cat(parts), net.head, I, J)
        del net
    return total / len(se.SEEDS)


def main():
    torch.set_num_threads(tc.CPU_THREADS)
    threading.Thread(target=tc.guard, daemon=True).start()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    best = {}
    for c, form, n in con.execute("select concept, form, n from forms order by concept, n desc"):
        best.setdefault(c, form)
    names = sorted({nfc(x) for x in best.values() if len(x) >= 2})
    done = {tuple(sorted((r["a"], r["b"]))) for r in se.load_eval(ROOT / "data" / "eval" / "my_sheet.csv")}
    pairs = [(i, j) for i in range(len(names)) for j in range(i + 1, len(names)) if tuple(sorted((names[i], names[j]))) not in done and norm_key(names[i]) != norm_key(names[j])]
    I, J = torch.tensor([p[0] for p in pairs], device=tc.DEVICE), torch.tensor([p[1] for p in pairs], device=tc.DEVICE)
    print("개념", len(names), "쌍", len(pairs), flush=True)
    chosen = {}
    for name, score, top in (("finetune", finetune(names, I, J), TOP_FT), ("bilstm", bilstm(names, I, J), TOP_CHAR)):
        n = 0
        for k in np.argsort(-score, kind="stable"):
            if pairs[k] not in chosen:
                chosen[pairs[k]] = name
                n += 1
                if n >= top:
                    break
        print(name, "상위에서 고름", n, flush=True)
    rows = list(chosen.items())
    random.Random(42).shuffle(rows)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["a", "b", "label(1 같음, 0 다름, 모르면 비움)", "kind"])
        for (i, j), _ in rows:
            w.writerow([names[i], names[j], "", "model-cross" if cross_script(names[i], names[j]) else "model-same"])
    print("시트", len(rows), collections.Counter("한영" if cross_script(names[i], names[j]) else "같은 문자" for (i, j), _ in rows), "최대 RAM", tc.peak_ram_gb(), "GB")


if __name__ == "__main__":
    main()
