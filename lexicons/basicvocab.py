# -*- coding: utf-8 -*-
"""국립국어원 「한국어 학습용 어휘 목록」(2003, 공공누리 제1유형: 출처 표시) → data/processed/lexicon/basicvocab.tsv

원본: 국립국어원 누리집의 텍스트 파일 (cp949, 탭 구분: 순위·단어·품사·풀이·등급).
기초 어휘 = 한국어를 배우는 사람도 먼저 배우는 일상어이므로, 명사마다 '일상 뜻 1'로 적는다 (전문 뜻 0).
다른 사전과 합치면 우리말샘에서 전문 뜻만 있던 낱말도 '섞임'이 되어 공부 목록에서 후보로 내려간다.
"""
import re
import sys

from common import fetch, key, write

URL = ("https://www.korean.go.kr/common/download.do?file_path=etcData&c_file_name=b73a8438-4713-4436-8481-ec26fd0dce2a_0.txt"
       "&o_file_name=%ED%95%9C%EA%B5%AD%EC%96%B4%20%ED%95%99%EC%8A%B5%EC%9A%A9%20%EC%96%B4%ED%9C%98%20%EB%AA%A9%EB%A1%9D.txt")
FILES = [("vocab.txt", URL, "3b49681f05d6a7490c13da2a2847e433effdf65da409fd295792d6ee33685064")]


def main():
    folder = fetch("basicvocab", FILES)
    words = {}
    for line in (folder / "vocab.txt").read_bytes().decode("cp949").splitlines()[1:]:
        p = line.split("\t")
        if len(p) >= 5 and p[2] == "명":
            w = re.sub(r"\d+$", "", p[1]).strip()
            words.setdefault(key(w), (w, p[4].strip()))
    write("basicvocab", "국립국어원 한국어 학습용 어휘 목록(2003), 공공누리 제1유형. key\t표기\t전문뜻\t일상뜻\t분야(여기서는 등급)",
          ((k, words[k][0], 0, 1, "등급" + words[k][1]) for k in sorted(words)))
    print("기초 어휘: 명사", len(words))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
