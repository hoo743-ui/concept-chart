# -*- coding: utf-8 -*-
"""시뮬레이터 C: 공부 노트 근거 문장 선택 — 크롤링한 문장 중 '정의문'을 1순위로 고를 수 있는가?"""
import json, pathlib, re, time, warnings
import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
import spacy
from kiwipiepy import Kiwi
from concepts import DEFS, VARIANTS, DISPLAY
from pipeline import norm_key
from textgen import josa
warnings.filterwarnings('ignore')

kiwi = Kiwi()
nlp = spacy.load('ko_core_news_md', disable=['tagger', 'parser', 'ner', 'lemmatizer', 'morphologizer', 'senter', 'attribute_ruler'])

docs, dconcept, dgold = [], [], []
for c, sents in DEFS.items():
    for i, s in enumerate(sents):
        docs.append(s); dconcept.append(c); dgold.append(i == 0)
dconcept = np.array(dconcept); dgold = np.array(dgold)
concepts = list(DEFS)

def q_variant(c, alt):
    vs = VARIANTS[c]
    if not alt:
        v = DISPLAY[c]
    else:
        lat = [x for x in vs if re.search(r'[A-Za-z]', x) and x != DISPLAY[c]]
        oth = [x for x in vs if x != DISPLAY[c]]
        v = (lat or oth or [DISPLAY[c]])[0]
    return v, josa(v, '이란') + ' 무엇인가?'

def morphs(s):
    return [t.form.lower() for t in kiwi.tokenize(s) if not t.tag.startswith(('S', 'J', 'E')) or t.tag in ('SL', 'SN', 'SH')]

doc_tok = [morphs(d) for d in docs]
bm25 = BM25Okapi(doc_tok)
tfv = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4)).fit(docs)
D = tfv.transform(docs)
DV = np.array([nlp(d).vector for d in docs])

DEF_END = re.compile(r'(것|방법|기법|현상|과정|구조|모델|알고리즘|지표|단위|함수|값|메커니즘|플랫폼|데이터베이스|작업|방식|표현|자료형|비율|신경망)[을를]?\s*(말한다|뜻한다|가리킨다|의미한다|이다|다)[.]?\s*$')
DEF_MID = re.compile(r'(이란|란|이라는 것은|의 약자|라고 부르|을 말한다|를 말한다|을 뜻한다|를 뜻한다|을 가리|를 가리)')
EXP = re.compile(r'(했다|했더니|봤다|됐다|만들었|이번|우리|팀원|나는|처음|놀랐|퇴근|하루 종일|다들)')
HOW = re.compile(r'(려면|좋다|해야|하는 것이|요령|권장|먼저|반드시|꼭)')
OPI = re.compile(r'(가장|자주|요즘|유명|평가|시장|키워드|면접|단골|인기|빠지지|업무다|화제|관심)')

def term_hits(s, c):
    keys = [norm_key(v) for v in VARIANTS[c]]
    ns = norm_key(s)
    return any(k in ns for k in keys)

def starts_with_term(s, c):
    ns = norm_key(s[:30])
    return any(ns.startswith(norm_key(v)) for v in VARIANTS[c])

def feat(i, qtoks, qvec, qtf, c, bm, expand):
    s = docs[i]
    hit = term_hits(s, c) if expand else any(norm_key(t) in norm_key(s) for t in qtoks if len(t) > 1)
    return [bm, float((qtf @ D[i].T).toarray()[0, 0]), float(qvec @ DV[i] / (np.linalg.norm(qvec) * np.linalg.norm(DV[i]) + 1e-9)),
            float(hit), float(starts_with_term(s, c) and hit), float(bool(DEF_END.search(s))), float(bool(DEF_MID.search(s))),
            float('(' in s[:40]), float(bool(EXP.search(s))), float(bool(HOW.search(s))), float(bool(OPI.search(s))),
            len(s) / 100, float(bool(re.search(r'\d', s)))]
FN = ['BM25', '문자 n-gram 코사인', 'floret 코사인', '용어 포함', '용어로 시작', '정의형 어미(…방법이다/말한다)', '정의 표지(이란/약자)',
      '앞부분 괄호(약어 병기)', '경험 서술 표지', '방법·조언 표지', '평가·여론 표지', '문장 길이', '숫자 포함']

def build(alt, expand):
    rows, labels, grp, qids = [], [], [], []
    for qi, c in enumerate(concepts):
        v, q = q_variant(c, alt)
        qt = morphs(q)
        if expand:
            for vv in VARIANTS[c]:
                qt += morphs(vv)
        bm = bm25.get_scores(qt)
        bm = bm / (bm.max() + 1e-9)
        qtf = tfv.transform([' '.join([q] + (VARIANTS[c] if expand else []))])
        qvec = np.mean([nlp(x).vector for x in ([q] + (VARIANTS[c] if expand else []))], axis=0)
        for i in range(len(docs)):
            rows.append(feat(i, qt, qvec, qtf, c, bm[i], expand))
            labels.append(int(dconcept[i] == c and dgold[i]))
            grp.append(c); qids.append(qi)
    return np.array(rows), np.array(labels), np.array(grp), np.array(qids)

def rank_metrics(scores, labels, qids):
    rr, h1, h3 = [], [], []
    for q in np.unique(qids):
        m = qids == q
        s, l = scores[m], labels[m]
        order = np.argsort(-s, kind='stable')
        pos = int(np.where(l[order] == 1)[0][0]) + 1
        rr.append(1 / pos); h1.append(pos == 1); h3.append(pos <= 3)
    return dict(mrr=float(np.mean(rr)), hit1=float(np.mean(h1)), hit3=float(np.mean(h3)))

results = []
for qname, alt in [('Q1', False), ('Q2', True)]:
    for expand in [False, True]:
        X, y, g, qid = build(alt, expand)
        tag = f"{qname}{'+확장' if expand else ''}"
        base = {
            'BM25 (Kiwi 형태소)': X[:, 0],
            '문자 n-gram TF-IDF': X[:, 1],
            'spaCy floret 벡터': X[:, 2],
            '정의 패턴 규칙만': X[:, 3] * (1 + 2 * X[:, 5] + 2 * X[:, 6] + X[:, 4] + X[:, 7] - X[:, 8] - X[:, 9] - X[:, 10]),
        }
        # BM25 + 패턴 (가중치는 개념 단위 교차검증으로 선택)
        gkf = GroupKFold(n_splits=5)
        hyb = np.zeros(len(y)); lrp = np.zeros(len(y))
        for tr, te in gkf.split(X, y, g):
            best_w, best_m = 0, -1
            for w in [0, 0.25, 0.5, 1, 2, 4]:
                sc = X[tr, 0] + w * base['정의 패턴 규칙만'][tr]
                mtr = rank_metrics(sc, y[tr], qid[tr])['mrr']
                if mtr > best_m:
                    best_m, best_w = mtr, w
            hyb[te] = X[te, 0] + best_w * base['정의 패턴 규칙만'][te]
            m = LogisticRegression(max_iter=3000, C=1.0, class_weight='balanced').fit(X[tr], y[tr])
            lrp[te] = m.predict_proba(X[te])[:, 1]
        base['BM25 + 정의 패턴 (가중치 CV)'] = hyb
        base['로지스틱 회귀 (13개 특징, 개념 단위 CV)'] = lrp
        for name, sc in base.items():
            r = rank_metrics(sc, y, qid)
            r.update(method=name, query=tag)
            results.append(r)
            print(f'{tag:8s} {name:32s} MRR {r["mrr"]:.3f} Hit@1 {r["hit1"]:.3f} Hit@3 {r["hit3"]:.3f}')

X, y, g, qid = build(False, True)
m = LogisticRegression(max_iter=3000, class_weight='balanced').fit((X - X.mean(0)) / (X.std(0) + 1e-9), y)
coef = sorted([dict(feature=f, coef=float(c)) for f, c in zip(FN, m.coef_[0])], key=lambda d: -abs(d['coef']))
print('coef', [(c['feature'], round(c['coef'], 2)) for c in coef[:6]])

# 예시: BM25 1위 vs 학습형 1위 (확장 Q1)
ex = []
gkf = GroupKFold(n_splits=5); lrp = np.zeros(len(y))
for tr, te in gkf.split(X, y, g):
    mm = LogisticRegression(max_iter=3000, class_weight='balanced').fit(X[tr], y[tr])
    lrp[te] = mm.predict_proba(X[te])[:, 1]
for qi, c in enumerate(concepts):
    msk = qid == qi
    idx = np.where(msk)[0]
    b1 = idx[np.argmax(X[msk, 0])] % len(docs)
    l1 = idx[np.argmax(lrp[msk])] % len(docs)
    ex.append(dict(concept=DISPLAY[c], query=q_variant(c, False)[1], bm25_top=docs[b1], bm25_ok=bool(dgold[b1] and dconcept[b1] == c),
                   learned_top=docs[l1], learned_ok=bool(dgold[l1] and dconcept[l1] == c), gold=DEFS[c][0]))
# 점검: '문장 길이' 특징을 빼도 정의문을 고르는지 (길이에만 기대는 모델인지 확인) + 정의문/기타 문장 평균 길이
keep = [i for i, f in enumerate(FN) if f != '문장 길이']
no_length = {}
for qname, alt in [('Q1', False), ('Q2', True)]:
    Xq, yq, gq, qq = build(alt, True)
    p = np.zeros(len(yq))
    for tr, te in GroupKFold(n_splits=5).split(Xq, yq, gq):
        mm = LogisticRegression(max_iter=3000, C=1.0, class_weight='balanced').fit(Xq[tr][:, keep], yq[tr])
        p[te] = mm.predict_proba(Xq[te][:, keep])[:, 1]
    no_length[f'{qname}+확장'] = rank_metrics(p, yq, qq)
len_gold = float(np.mean([len(d) for d, gd in zip(docs, dgold) if gd]))
len_other = float(np.mean([len(d) for d, gd in zip(docs, dgold) if not gd]))

out = dict(n_concepts=len(concepts), n_sentences=len(docs), results=results, coef=coef, examples=ex,
           not_measured=[dict(method='BAAI/bge-m3 (dense)', note='미실측'), dict(method='BAAI/bge-reranker-v2-m3 (cross-encoder)', note='미실측'),
                         dict(method='LLM 판정 (정의문인가?)', note='미실측')],
           no_length=no_length, len_gold=len_gold, len_other=len_other)
results_dir = pathlib.Path(__file__).resolve().parent / 'results'   # 실행 위치와 무관하게 sim/results/
results_dir.mkdir(exist_ok=True)
with open(results_dir / 'C.json', 'w', encoding='utf-8') as fp:
    json.dump(out, fp, ensure_ascii=False)
print('ok', sum(e['bm25_ok'] for e in ex), sum(e['learned_ok'] for e in ex))
