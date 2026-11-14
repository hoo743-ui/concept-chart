# -*- coding: utf-8 -*-
"""Homebrew 패키지·앱 이름과 한 줄 설명 → kit/data/lexicon/homebrew.sqlite (11-14, kit/homebrew.py가 읽는다. git 제외, 다시 만들 수 있다)

    python lexicons/homebrew.py

원본: https://formulae.brew.sh/api/formula.json · cask.json (Homebrew/homebrew-core·homebrew-cask·formulae.brew.sh, BSD-2-Clause).
매일 바뀌는 목록이라 SHA-256은 고정하지 않고 받은 날의 값을 출력·기록한다 (experiments/DATA.md).
쓰는 열: 패키지 이름·별칭, 앱 토큰·이름, 설명(desc)뿐. 이름만 맞추면 다른 뜻이 많아 앱은 '대화에서 brew로 설치한 이름'에만 쓴다 (kit/homebrew.py).
"""
import json
import sqlite3
import sys
import urllib.request

from common import RAW, sha256

ROOT = RAW.parent.parent
OUT = ROOT / "kit" / "data" / "lexicon" / "homebrew.sqlite"
FILES = [("formula", "https://formulae.brew.sh/api/formula.json"), ("cask", "https://formulae.brew.sh/api/cask.json")]


def main():
    folder = RAW / "homebrew"
    folder.mkdir(parents=True, exist_ok=True)
    rows = {}
    for kind, url in FILES:
        path = folder / f"{kind}.json"
        with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as f:
            f.write(r.read())
        print(kind, path.stat().st_size, "바이트 sha256", sha256(path))
        for x in json.loads(path.read_text(encoding="utf-8")):
            if kind == "formula":
                name, keys = x["name"], [x["name"]] + list(x.get("aliases") or [])
            else:
                name, keys = x["token"], [x["token"]] + list(x.get("name") or [])
            for k in keys:
                rows.setdefault(k.strip().lower(), (kind, name, (x.get("desc") or "").strip()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE brew (key TEXT PRIMARY KEY, kind TEXT, name TEXT, desc TEXT) WITHOUT ROWID")
    con.executemany("INSERT INTO brew VALUES (?,?,?,?)", ((k, *v) for k, v in rows.items()))
    con.commit()
    con.close()
    tmp.replace(OUT)
    print("Homebrew 사전:", OUT, f"이름 {len(rows)}개")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
