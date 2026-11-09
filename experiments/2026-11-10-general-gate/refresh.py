# -*- coding: utf-8 -*-
"""데이터셋을 넣으면 바로 반영: 분야 사전을 모두 다시 만들고(lexicons/build.py) 같은 기준으로 재서 대시보드에 올린다.

    python experiments/2026-11-10-general-gate/refresh.py            # 라운드 이름은 자동 (auto-월일-시분)

새 데이터셋 넣는 법은 lexicons/build.py 설명. 처음 보는 분야(holdout)는 여기서 재지 않는다.
채택(앱에 넣기)은 사용자가 결정한다: python dev.py lexicon
"""
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "lexicons" / "build.py"), "--no-install"], check=True)
    names = sorted(p.stem for p in (ROOT / "data" / "processed" / "lexicon").glob("*.tsv"))
    tag = "auto-" + time.strftime("%m%d-%H%M")
    subprocess.run([sys.executable, str(HERE / "evaluate.py"), "score", tag, f"--note=사전 다시 만듦: {', '.join(names) or '없음'}"], check=True)


if __name__ == "__main__":
    main()
