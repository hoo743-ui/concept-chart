# -*- coding: utf-8 -*-
"""분야 사전을 모두 만들고 앱 폴더(kit/data/lexicon/)에 넣는다. python dev.py lexicon 이 이것을 부른다.

    python lexicons/build.py            # 받기(없으면) → 변환 → kit/data/lexicon/
    python lexicons/build.py --no-install   # 변환까지만 (평가용: data/processed/lexicon/)

새 데이터셋 넣는 법
1. 이 폴더에 <이름>.py를 만든다: FILES = [(파일 이름, 주소, SHA-256)], main()에서 common.fetch → common.write.
   전문 용어집처럼 일상 뜻 정보가 없으면 일상뜻수는 0으로 둔다. 사전들은 뜻 수를 더해서 합쳐진다.
2. 출처·라이선스·SHA-256을 experiments/DATA.md에 적는다 (라이선스는 원본 페이지에서 확인한 것만).
3. 평가: python experiments/2026-11-10-general-gate/refresh.py → 대시보드에서 앞 라운드보다 나아졌는지 본다.
   앱에 넣는 것은 사용자가 결정한다 (넣기로 했으면 이 스크립트를 --no-install 없이 돌린다).
"""
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
INSTALLED = ROOT / "kit" / "data" / "lexicon"
SKIP = {"common.py", "build.py"}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    built = []
    sys.path.insert(0, str(HERE))
    for conv in sorted(HERE.glob("*.py")):
        if conv.name in SKIP:
            continue
        subprocess.run([sys.executable, str(conv)], check=True, cwd=HERE)
        built.append(conv.stem)
    if "--no-install" not in sys.argv:
        install(built)
    return built


def install(names):
    """앱에는 합친 SQLite 하나만 넣는다 (필요한 낱말만 찾아 메모리를 거의 쓰지 않는다). 새로 만든 뒤 바꿔 끼운다"""
    import sqlite3
    sys.path.insert(0, str(ROOT / "kit"))
    import concept_gate
    lex = concept_gate.read_tsv(ROOT / "data" / "processed" / "lexicon")
    INSTALLED.mkdir(parents=True, exist_ok=True)
    tmp = INSTALLED / "lexicon.sqlite.new"
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE lex (key TEXT PRIMARY KEY, spec INTEGER, gen INTEGER) WITHOUT ROWID")
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO lex VALUES (?,?,?)", ((k, s, n) for k, (s, n) in lex.items()))
    con.execute("INSERT INTO meta VALUES ('sources', ?)", (", ".join(names),))
    con.commit()
    con.close()
    shutil.move(str(tmp), str(INSTALLED / "lexicon.sqlite"))
    for old in INSTALLED.glob("*.tsv"):                    # 예전 방식(메모리로 읽는 tsv)이 남아 있으면 지운다
        old.unlink()
    print("앱 사전:", INSTALLED / "lexicon.sqlite", f"낱말 {len(lex)}개", names)


if __name__ == "__main__":
    main()
