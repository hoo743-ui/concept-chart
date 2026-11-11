# -*- coding: utf-8 -*-
"""우리말샘(국립국어원, CC BY-SA 2.0 KR) → data/processed/lexicon/urimalsaem.tsv

원본: Hugging Face hac541309/woori_spring_dict 커밋 6066408 (우리말샘 xls_20230602을 한 행 한 문자열로 바꾼 것). 약 200MB.
한 행 = 뜻 하나. 쓰는 열은 어휘·구성 단위·전문 분야뿐이다 (출전이 있는 용례는 원저작자 것이라 쓰지 않는다).
- 전문 뜻: 고유명이 아닌 전문 분야가 붙은 뜻. 일상 뜻: 전문 분야가 없는 뜻. 고유명 분야(인명·지명·책명·고유명 일반)는 세지 않는다.
- 속담·관용구 행은 뺀다. 메모리: 2만 행씩 읽는다. pyarrow가 필요하다.
"""
import collections
import re
import sys

from common import OUT, fetch, key, write

REV = "6066408bc11f3ca38c5e3d73296ff6641ac2d11b"
BASE = f"https://huggingface.co/datasets/hac541309/woori_spring_dict/resolve/{REV}/data/"
FILES = [("train-00000-of-00002-50936618007f5b8d.parquet", BASE + "train-00000-of-00002-50936618007f5b8d.parquet", "77ff44716408f9f9ea3560df7032f7ffacf233b44ddd4c298e0f7ee5993544d2"),
         ("train-00001-of-00002-25e2c7bf6a9fca5e.parquet", BASE + "train-00001-of-00002-25e2c7bf6a9fca5e.parquet", "0f9e0173113c3ca60dcaeb74e1e00dc3d3970b963372cd790613a2f84e35a7ca")]
PROPER = {"인명", "지명", "책명", "고유명 일반"}


def parse(t):
    word = re.match(r"어휘: (.*?), 구성 단위: ([^,]+)", t)
    if not word:
        return None
    form = re.sub(r"[\^\-]", lambda m: " " if m.group(0) == "^" else "", word.group(1)).strip()
    form = re.sub(r"\d+$", "", form)                       # 동형어 번호
    m = re.search(r"전문 분야: ((?:『[^』]+』)+)", t)
    return form, word.group(2).strip(), re.findall(r"『([^』]+)』", m.group(1)) if m else []


DEF = re.compile(r"뜻풀이: (.*?)(?:, (?:용례|전문 분야|관련 어휘|규범 정보|수어 정보|대역어|멀티미디어|어원|다중 의미|문형|문법|지역|분류|생물 분류 정보|학명|속담|관용구):|$)", re.S)
DEFS_OUT = OUT.parent / "lexicon_defs"     # (0.7.2) 설명 출처용 뜻풀이. 사용자 결정 11-11 '같이보내자'


def clean(d):
    """뜻풀이 한 줄: 태그·줄바꿈을 걷고 300자까지"""
    d = re.sub(r"<[^>]+>", "", d)
    d = re.sub(r"\s+", " ", d).strip().replace("\t", " ")
    return d[:300]


def main():
    import pyarrow.parquet as pq
    folder = fetch("urimalsaem", FILES)
    spec, gen, flds, forms, defs = collections.Counter(), collections.Counter(), collections.defaultdict(set), {}, []
    rows = skipped = 0
    for fname, _, _ in FILES:
        for b in pq.ParquetFile(folder / fname).iter_batches(batch_size=20000, columns=["text"]):
            for t in b.column(0).to_pylist():
                rows += 1
                r = parse(t)
                if not r or r[1] in ("속담", "관용구"):
                    skipped += 1
                    continue
                form, _unit, fields = r
                k = key(form)
                if len(k) < 2:
                    continue
                forms.setdefault(k, form)
                if not fields:
                    gen[k] += 1
                elif set(fields) - PROPER:
                    spec[k] += 1
                    flds[k] |= set(fields) - PROPER
                    d = DEF.search(t)
                    if _unit == "단어" and d:
                        defs.append((k, ";".join(f for f in fields if f not in PROPER), clean(d.group(1))))
    keys = sorted(set(spec) | set(gen))
    write("urimalsaem", "우리말샘(국립국어원) CC BY-SA 2.0 KR에서 만든 파생 자료. key\t표기\t전문뜻\t일상뜻\t분야",
          ((k, forms[k], spec[k], gen[k], ";".join(sorted(flds[k]))) for k in keys))
    DEFS_OUT.mkdir(parents=True, exist_ok=True)              # 판정용 tsv 폴더와 따로 둔다 (concept_gate.read_tsv가 섞어 읽지 않게)
    with (DEFS_OUT / "urimalsaem.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 우리말샘(국립국어원) CC BY-SA 2.0 KR 뜻풀이(전문 분야가 붙은 단어 뜻만, 용례 없음). key\t분야(;로)\t뜻풀이\n")
        f.writelines(f"{k}\t{fl}\t{d}\n" for k, fl, d in defs if d)
    print(f"우리말샘 뜻풀이: {len(defs)}개 → {DEFS_OUT / 'urimalsaem.tsv'}")
    print(f"우리말샘: 행 {rows}, 건너뜀 {skipped}, 낱말 {len(keys)}, 전문 뜻 있음 {len(spec)} (전문 뜻만 {sum(1 for k in spec if not gen[k])}), 일상 뜻만 {sum(1 for k in gen if not spec[k])}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
