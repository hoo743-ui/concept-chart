# -*- coding: utf-8 -*-
"""파인튜닝 시드 하나를 메모리 보호 장치와 함께 돌린다 (사용 가능 RAM 1GB 아래가 1분 이어지면 멈춤, 도는 동안 절전 방지).

    .venv-ml/Scripts/python experiments/2026-11-09-b-finetune/run_guarded.py --seed 42 --tag r3-clean --extra data/processed/B_extra_r3-clean.jsonl
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import threading

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import auto_rounds as ar  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--extra", required=True)
    a = ap.parse_args()
    ar.keep_awake()
    threading.Thread(target=ar.watch_memory, daemon=True).start()
    cmd = [sys.executable, str(HERE / "train.py"), "train", "--seed", str(a.seed), "--tag", a.tag, "--extra", a.extra]
    ar.child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONUTF8="1"))
    _, err = ar.child.communicate()
    if ar.child.returncode != 0:
        ar.log(a.tag, f"seed{a.seed} 실패:", err[-400:])
        sys.exit(1)
    m = json.loads((HERE / f"{a.tag}-seed{a.seed}" / "metrics.json").read_text(encoding="utf-8"))["val"]
    ar.log(a.tag, f"seed{a.seed}", f"AP {m['ap']:.4f} 어려운 오답 {m['hard_fp']:.3f} 한영 재현 {m['cross_recall']:.3f} best {m['best_epoch']} GPU {m.get('gpu_gb')}GB")


if __name__ == "__main__":
    main()
