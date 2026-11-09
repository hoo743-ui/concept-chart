# -*- coding: utf-8 -*-
"""개념 관문이 쓰는 기술 용어 목록을 만든다: 받아 둔 공개 데이터 → kit/data/tech_terms.txt (git에 올린다, 서비스에 함께 간다)

    python experiments/build_terms.py

출처: 한국어 위키백과 컴퓨터 분야 분류의 문서 제목(CC BY-SA), 위키데이터 이름(CC0), MDN 한국어 용어집(CC BY-SA), Kubernetes 한국어 용어집(CC BY 4.0).
문서 본문은 넣지 않는다. 제목과 이름만 넣는다. 받아 둔 원본만 쓰고 새로 받지 않는다.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "kit" / "data" / "tech_terms.txt"
DROP = re.compile(r"목록|^틀:|^분류:|위키백과|\d{4}년|^[\W\d_]+$")
PAREN = re.compile(r"\s*\([^()]*\)\s*$")


def clean(x):
    x = re.sub(r"\s+", " ", PAREN.sub("", x or "")).strip()
    return x if 2 <= len(x) <= 40 and not DROP.search(x) else None


def main():
    terms = set()
    for tag in ("ml", "r1-ai-nlp", "r2-dev", "r3-cs"):
        for line in (ROOT / "data" / "raw" / f"kowiki_{tag}" / "pages.jsonl").read_text(encoding="utf-8").splitlines():
            p = json.loads(line)
            terms |= {clean(p["title"])} | {clean(e) for e in p.get("en", [])[:1]}
    for line in (ROOT / "data" / "raw" / "wikidata_terms" / "items.jsonl").read_text(encoding="utf-8").splitlines():
        it = json.loads(line)
        terms |= {clean(v) for v in it["labels"].values()}
    for line in (ROOT / "data" / "raw" / "devgloss" / "pages.jsonl").read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        title = p.get("title", "")
        m = re.match(r"(.+?)\s*\(원문,\s*(.+?)\)\s*$", title)
        if m:
            terms |= {clean(m.group(1)), clean(m.group(2))}
        else:
            terms |= {clean(title), clean(p.get("slug", "").split("/")[-1].replace("_", " "))}
    terms.discard(None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    head = ["# 기술 용어 목록. experiments/build_terms.py가 만든다. 직접 고치지 않는다.",
            "# 출처: 위키백과 제목(CC BY-SA), 위키데이터(CC0), MDN 용어집(CC BY-SA), Kubernetes 용어집(CC BY 4.0)"]
    OUT.write_text("\n".join(head + sorted(terms, key=str.lower)) + "\n", encoding="utf-8", newline="\n")
    print("용어", len(terms), "크기 KB", OUT.stat().st_size // 1024)


if __name__ == "__main__":
    main()
