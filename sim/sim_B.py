# -*- coding: utf-8 -*-
"""시뮬레이터 B: 용어 정규화(동의어 병합) 방식 비교 — 같은 개념의 다른 표기인가?"""
import json, pathlib, time, itertools, re, warnings
import numpy as np
from rapidfuzz import fuzz
from korean_romanizer.romanizer import Romanizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score, average_precision_score, f1_score, precision_score, recall_score
import spacy

from concepts import CONCEPTS, HARD_NEG
from pipeline import oracle_concept, norm_key
warnings.filterwarnings('ignore')

nlp = spacy.load('ko_core_news_md', disable=['tagger', 'parser', 'ner', 'lemmatizer', 'morphologizer', 'senter', 'attribute_ruler'])

# ---------- 데이터 ----------
rng = np.random.default_rng(7)
pairs = []
for c, vs in CONCEPTS:
    for a, b in itertools.combinations(vs, 2):
        pairs.append((a, b, 1, 'pos', c))
hn = set()
for a, b in HARD_NEG:
    pairs.append((a, b, 0, 'hard', oracle_concept(a) or a))
    hn.add((a, b))
allv = [(v, c) for c, vs in CONCEPTS for v in vs]
seen = set()
while sum(1 for p in pairs if p[3] == 'rand') < 200:
    (a, ca), (b, cb) = allv[rng.integers(len(allv))], allv[rng.integers(len(allv))]
    if ca == cb or (a, b) in seen or (a, b) in hn or (b, a) in hn:
        continue
    seen.add((a, b))
    pairs.append((a, b, 0, 'rand', ca))
y = np.array([p[2] for p in pairs])
groups = np.array([p[4] for p in pairs])
print('pairs', len(pairs), 'pos', y.sum(), 'hard', sum(p[3] == 'hard' for p in pairs))

# ---------- 표현 ----------
def is_latin(s):
    return bool(re.search(r'[A-Za-z]', s)) and not re.search(r'[가-힣]', s)
def is_hangul(s):
    return bool(re.search(r'[가-힣]', s)) and not re.search(r'[A-Za-z]', s)

CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
JUNG = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
JONG = ' ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ'
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
    return ''.join(out)

_rom = {}
def rom(s):
    if s not in _rom:
        try:
            r = Romanizer(s).romanize()
        except Exception:
            r = s
        _rom[s] = norm_key(r)
    return _rom[s]

strings = sorted(set([p[0] for p in pairs] + [p[1] for p in pairs]))
tfv = TfidfVectorizer(analyzer='char', ngram_range=(1, 3)).fit([rom(s) for s in strings])
V = {s: tfv.transform([rom(s)]) for s in strings}
_vec = {}
def fv(s):
    if s not in _vec:
        _vec[s] = nlp(s).vector
    return _vec[s]

def cos(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na > 0 and nb > 0 else 0.0

def is_acr(s):
    return bool(re.fullmatch(r'[A-Z0-9/]{2,6}', s.replace(' ', '')))

def features(a, b):
    na, nb = norm_key(a), norm_key(b)
    f_char = fuzz.ratio(na, nb) / 100
    f_jamo = fuzz.ratio(jamo(na), jamo(nb)) / 100
    f_rom = fuzz.ratio(rom(a), rom(b)) / 100
    f_tfidf = float((V[a] @ V[b].T).toarray()[0, 0])
    f_vec = cos(fv(a), fv(b))
    lr = min(len(na), len(nb)) / max(len(na), len(nb))
    la, lb = is_latin(a), is_latin(b)
    ha, hb = is_hangul(a), is_hangul(b)
    pre = 0
    for x, z in zip(rom(a), rom(b)):
        if x != z:
            break
        pre += 1
    return [f_char, f_jamo, f_rom, f_tfidf, f_vec, lr, float(la and lb), float(ha and hb), float(la != lb),
            float(is_acr(a) or is_acr(b)), pre / max(1, min(len(rom(a)), len(rom(b)))), float(na == nb)]
FN = ['문자 편집 유사도', '자모 편집 유사도', '로마자 편집 유사도', '로마자 문자 n-gram TF-IDF', 'floret 정적 벡터', '길이 비율',
      '둘 다 영문', '둘 다 한글', '혼합 표기', '약어 포함', '공통 접두 비율', '정규화 후 동일']

t0 = time.perf_counter()
X = np.array([features(a, b) for a, b, *_ in pairs])
feat_ms = (time.perf_counter() - t0) * 1000 / len(pairs)

# ---------- 평가 ----------
gkf = GroupKFold(n_splits=5)
splits = list(gkf.split(X, y, groups))

def best_thr(scores, labels):
    cand = np.unique(scores)
    best, bt = -1, 0.5
    for t in cand:
        f = f1_score(labels, scores >= t, zero_division=0)
        if f > best:
            best, bt = f, t
    return bt

def eval_scores(name, desc, oof, thr_pred, ms, kind):
    hard = np.array([p[3] == 'hard' for p in pairs])
    cross = np.array([p[2] == 1 and (is_latin(p[0]) != is_latin(p[1])) for p in pairs])
    r = dict(method=name, desc=desc, kind=kind,
             auc=float(roc_auc_score(y, oof)), ap=float(average_precision_score(y, oof)),
             f1=float(f1_score(y, thr_pred)), precision=float(precision_score(y, thr_pred, zero_division=0)),
             recall=float(recall_score(y, thr_pred)), hard_fp=float(thr_pred[hard].mean()),
             cross_recall=float(thr_pred[cross].mean()), ms_per_1k=float(ms))
    print(f"{name:26s} AUC {r['auc']:.3f} AP {r['ap']:.3f} F1 {r['f1']:.3f} P {r['precision']:.3f} R {r['recall']:.3f} hardFP {r['hard_fp']:.3f} crossR {r['cross_recall']:.3f}")
    return r

results = []
zero = [('정확 일치(정규화)', '소문자·공백·하이픈 제거 후 동일', 11), ('문자 편집거리', 'rapidfuzz ratio', 0),
        ('자모 편집거리', '한글을 자모로 분해 후 편집거리', 1), ('로마자 변환 + 편집거리', 'korean-romanizer → ratio', 2),
        ('로마자 char n-gram', '로마자 1~3gram TF-IDF 코사인', 3), ('spaCy floret 벡터', 'ko_core_news_md 300차원', 4)]
for name, desc, j in zero:
    s = X[:, j]
    pred = np.zeros(len(y), dtype=bool)
    for tr, te in splits:
        thr = best_thr(s[tr], y[tr])
        pred[te] = s[te] >= thr
    results.append(eval_scores(name, desc, s, pred, feat_ms * 1000 / 6, 'zero-shot'))

for name, desc, mk in [('로지스틱 회귀 (특징 결합)', '12개 유사도 특징 · 개념 단위 교차검증', lambda: LogisticRegression(max_iter=2000, C=1.0)),
                       ('GBM 분류기 (특징 결합)', 'HistGradientBoosting · 개념 단위 교차검증', lambda: HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=0))]:
    oof = np.zeros(len(y))
    pred = np.zeros(len(y), dtype=bool)
    t0 = time.perf_counter()
    for tr, te in splits:
        m = mk().fit(X[tr], y[tr])
        p_tr = m.predict_proba(X[tr])[:, 1]
        thr = best_thr(p_tr, y[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]
        pred[te] = oof[te] >= thr
    ms = feat_ms * 1000 + (time.perf_counter() - t0) * 1000 / 5 / len(y) * 1000
    results.append(eval_scores(name, desc, oof, pred, ms, 'learned'))

# 계수 해석 (전체 데이터 로지스틱)
lr = LogisticRegression(max_iter=2000).fit((X - X.mean(0)) / (X.std(0) + 1e-9), y)
coef = sorted([dict(feature=f, coef=float(c)) for f, c in zip(FN, lr.coef_[0])], key=lambda d: -abs(d['coef']))

# 사례: 각 방법이 틀린 대표 쌍
examples = []
best_learned = max([r for r in results if r['kind'] == 'learned'], key=lambda r: r['auc'])
for a, b, lab, kind, _ in pairs:
    if kind == 'hard' or (lab == 1 and is_latin(a) != is_latin(b)):
        f = features(a, b)
        examples.append(dict(a=a, b=b, label=int(lab), kind=kind, char=round(f[0], 2), rom=round(f[2], 2), vec=round(f[4], 2)))
# 페이지에 보여 줄 14쌍: 발음이 가장 비슷한 '다른 개념' 7쌍 + 발음이 가장 다른 '같은 개념(한↔영)' 7쌍
# (예전엔 examples[:60]으로 잘라서 어려운 오답 쌍이 빠졌다)
examples = (sorted([e for e in examples if e['kind'] == 'hard'], key=lambda e: -e['rom'])[:7]
            + sorted([e for e in examples if e['kind'] != 'hard'], key=lambda e: e['rom'])[:7])

out = dict(n_pairs=len(pairs), n_pos=int(y.sum()), n_hard=int(sum(p[3] == 'hard' for p in pairs)),
           n_rand=int(sum(p[3] == 'rand' for p in pairs)), results=results, coef=coef, examples=examples,
           not_measured=[dict(method='BAAI/bge-m3', note='다국어 임베딩 · HF 차단으로 미실측'),
                         dict(method='intfloat/multilingual-e5-base', note='다국어 임베딩 · 미실측'),
                         dict(method='jhgan/ko-sroberta-multitask', note='한국어 SBERT · 미실측')])
results_dir = pathlib.Path(__file__).resolve().parent / 'results'   # 실행 위치와 무관하게 sim/results/
results_dir.mkdir(exist_ok=True)
with open(results_dir / 'B.json', 'w', encoding='utf-8') as fp:
    json.dump(out, fp, ensure_ascii=False)
print('coef', [(c['feature'], round(c['coef'], 2)) for c in coef[:6]])
