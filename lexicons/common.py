# -*- coding: utf-8 -*-
"""분야 사전 변환기들이 같이 쓰는 것: 원본 받기(해시 확인)와 출력 형식.

출력 형식 (data/processed/lexicon/<이름>.tsv, 한 줄 = 낱말 하나, 탭 구분, '#'로 시작하는 줄은 설명):
    key  표기  전문뜻수  일상뜻수  분야(;로)
key는 소문자 + 공백·-·_·/·^ 제거 (kit/concept_gate.lexicon_verdict와 같은 규칙).
"""
import hashlib
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "lexicon"


def key(s):
    return re.sub(r"[\s\-_/^]+", "", s.lower())


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name, files):
    """files = [(파일 이름, 주소, SHA-256)]. 없으면 받고, 해시가 다르면 멈춘다 (원본이 바뀌었으면 사람이 확인해야 한다)"""
    folder = RAW / name
    folder.mkdir(parents=True, exist_ok=True)
    for fname, url, digest in files:
        p = folder / fname
        if not p.exists():
            print("받는 중:", fname, flush=True)
            tmp = p.with_suffix(p.suffix + ".part")
            req = urllib.request.Request(url, headers={"User-Agent": "concept-chart-lexicon/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            tmp.replace(p)
        if sha256(p) != digest:
            raise SystemExit(f"{p} 의 SHA-256이 기록(experiments/DATA.md)과 다릅니다. 원본이 바뀌었는지 확인하세요")
    return folder


def write(name, header, rows):
    """rows = [(key, 표기, 전문뜻수, 일상뜻수, 분야)]"""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.tsv"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# " + header + "\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    return path
