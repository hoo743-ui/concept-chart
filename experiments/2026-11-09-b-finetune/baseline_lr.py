# -*- coding: utf-8 -*-
"""기준선 ①: 지금 방식 (로지스틱 회귀 12개 특징, sim/sim_B.py와 같은 특징). 학습 세트로 학습, 임계값은 검증 세트.

    python experiments/2026-11-09-b-finetune/baseline_lr.py     # 기본 환경(.venv)에서. spaCy·romanizer 필요

특징 함수는 sim/sim_B.py에서 그대로 옮겼다 (불러오면 시뮬레이터 전체가 돌기 때문). TF-IDF는 학습 세트로만 맞춘다. 시험 세트는 건드리지 않는다.
"""
import json
import pathlib
import re
import sys
import time
import warnings

import numpy as np
import spacy
from korean_romanizer.romanizer import Romanizer
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import best_threshold, load_pairs, load_split, metrics, norm_key, part  # noqa: E402

nlp = spacy.load("ko_core_news_md", disable=["tagger", "parser", "ner", "lemmatizer", "morphologizer", "senter", "attribute_ruler"])
CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def is_latin(s):
    return bool(re.search(r"[A-Za-z]", s)) and not re.search(r"[가-힣]", s)


def is_hangul(s):
    return bool(re.search(r"[가-힣]", s)) and not re.search(r"[A-Za-z]", s)


def jamo(s):
    out = []
    for ch in s:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3:
            i = o - 0xAC00
            out += [CHO[i // 588], JUNG[(i % 588) // 28]]
            if i % 28:
                out.append(JONG[i % 28])
        else:
            out.append(ch)
    return "".join(out)


_rom, _vec = {}, {}


def rom(s):
    if s not in _rom:
        try:
            r = Romanizer(s).romanize()
        except Exception:
            r = s
        _rom[s] = norm_key(r)
    return _rom[s]


def fv(s):
    if s not in _vec:
        _vec[s] = nlp(s).vector
    return _vec[s]


def cos(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na > 0 and nb > 0 else 0.0


def is_acr(s):
    return bool(re.fullmatch(r"[A-Z0-9/]{2,6}", s.replace(" ", "")))


def features(a, b, tfv):
    na, nb = norm_key(a), norm_key(b)
    pre = 0
    for x, z in zip(rom(a), rom(b)):
        if x != z:
            break
        pre += 1
    la, lb, ha, hb = is_latin(a), is_latin(b), is_hangul(a), is_hangul(b)
    tf = float((tfv.transform([rom(a)]) @ tfv.transform([rom(b)]).T).toarray()[0, 0])
    return [fuzz.ratio(na, nb) / 100, fuzz.ratio(jamo(na), jamo(nb)) / 100, fuzz.ratio(rom(a), rom(b)) / 100, tf, cos(fv(a), fv(b)),
            min(len(na), len(nb)) / max(len(na), len(nb), 1), float(la and lb), float(ha and hb), float(la != lb),
            float(is_acr(a) or is_acr(b)), pre / max(1, min(len(rom(a)), len(rom(b)))), float(na == nb)]


def main():
    rows, split = load_pairs(), load_split()
    tr, va = part(rows, split["train"]), part(rows, split["val"])
    tfv = TfidfVectorizer(analyzer="char", ngram_range=(1, 3)).fit(sorted({rom(x) for r in tr for x in (r["a"], r["b"])}))
    t0 = time.time()
    Xtr = np.array([features(r["a"], r["b"], tfv) for r in tr])
    Xva = np.array([features(r["a"], r["b"], tfv) for r in va])
    ms = (time.time() - t0) * 1000 / (len(tr) + len(va))
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    lr = LogisticRegression(max_iter=2000, C=1.0).fit((Xtr - mu) / sd, [r["label"] for r in tr])
    s = lr.predict_proba((Xva - mu) / sd)[:, 1]
    thr = best_threshold(s, [r["label"] for r in va])
    m = metrics(va, [float(x) for x in s], thr)
    m["ms_per_pair"] = ms
    print(json.dumps(m, ensure_ascii=False, indent=1))
    (HERE / "baseline_lr.json").write_text(json.dumps({"method": "로지스틱 회귀 12개 특징", "val": m}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
