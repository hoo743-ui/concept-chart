# -*- coding: utf-8 -*-
"""시뮬레이터 A: 빈도 기반 중요도 산정 방식 비교 (가상 사용자 로그, 미래 관심 예측 정답)"""
import json, math, pathlib, time, warnings
from collections import Counter, defaultdict
import numpy as np
import networkx as nx
import yake
from krwordrank.word import KRWordRank
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

from concepts import PERSONAS, CONCEPT_IDS, DISPLAY
from textgen import simulate_user, ground_truth, random_spec, lam
from pipeline import (tok_T0, tok_T1, tok_T2, Gazetteer, make_tok_T3, make_tok_T4, build_glossary,
                      concept_weight_fn, oracle_concept, norm_key)

warnings.filterwarnings('ignore')
EVAL_DAYS = [21, 28, 35, 42, 49, 56, 63, 70]
TEST_SEEDS = [0, 1, 2, 3, 4]

GLOSSARY = build_glossary(0.85, seed=123)
GAZ = Gazetteer(GLOSSARY)
CW = concept_weight_fn(GAZ)
PIPES = {'T0': tok_T0, 'T1': tok_T1, 'T2': tok_T2, 'T3': make_tok_T3(GAZ), 'T4': make_tok_T4(GAZ)}
_cache = {p: {} for p in PIPES}

def tokenize(p, text):
    c = _cache[p]
    if text not in c:
        c[text] = PIPES[p](text)
    return c[text]

# ---------------- 데이터 구조 ----------------
class Run:
    def __init__(self, user, pipe):
        self.user, self.pipe = user, pipe
        sess = user['sessions']
        self.days = np.array([s['day'] for s in sess], dtype=float)
        self.utt_toks = [[tokenize(pipe, u) for u in s['utts']] for s in sess]
        self.utts = [s['utts'] for s in sess]
        vocab = {}
        for st in self.utt_toks:
            for ut in st:
                for t in ut:
                    if t not in vocab:
                        vocab[t] = len(vocab)
        self.vocab = vocab
        self.tokens = list(vocab)
        M = np.zeros((len(sess), len(vocab)))
        for i, st in enumerate(self.utt_toks):
            for ut in st:
                for t in ut:
                    M[i, vocab[t]] += 1
        self.M = M
        self.P = (M > 0).astype(float)
        self.isg = np.array([CW(t) >= 1.0 for t in self.tokens])
        self.C = np.where(self.isg, 1.0, 0.35)
        self.concept = [oracle_concept(t) for t in self.tokens]

def build_idf(bg_users, pipe):
    df = Counter()
    n = 0
    for u in bg_users:
        for s in u['sessions']:
            n += 1
            toks = set()
            for x in s['utts']:
                toks.update(tokenize(pipe, x))
            df.update(toks)
    return df, n

def idf_vec(run, dfn):
    df, n = dfn
    return np.array([math.log((n + 1) / (df.get(t, 0) + 1)) + 1 for t in run.tokens])

# ---------------- 특징 계산 ----------------
def stats_at(run, t, h):
    mask = (run.days <= t).astype(float)
    w = mask * np.power(2.0, -(t - run.days) / h) if h < 1e8 else mask
    dtf = w @ run.M
    dsf = w @ run.P
    ds = dsf / max(w.sum(), 1e-9)
    return dtf, ds, dsf

def weekly(run, t, K=8):
    ys = []
    for k in range(K - 1, -1, -1):
        m = ((run.days > t - 7 * (k + 1)) & (run.days <= t - 7 * k)).astype(float)
        ys.append(m @ run.P)
    return np.array(ys)  # K x V (과거→현재)

def holt(ys, a=0.5, b=0.3):
    L = ys[0].copy()
    T = ys[1] - ys[0] if len(ys) > 1 else np.zeros_like(L)
    for y in ys[1:]:
        Ln = a * y + (1 - a) * (L + T)
        T = b * (Ln - L) + (1 - b) * T
        L = Ln
    return np.maximum(L + 1.5 * T, 0), T

def trend_term(run, t):
    ys = weekly(run, t)
    f, _ = holt(ys)
    recent = ys[-2:].mean(axis=0)
    ratio = np.clip((f + 0.25) / (recent + 0.25), 0.25, 4.0)
    return np.log2(ratio) / 2.0, f, ys

def score_ours(run, t, idf, h=14, beta=1.0, gamma=1.0, unit='mention', c_low=0.35,
               use_idf=True, use_c=True, cache=None):
    key = (h,)
    if cache is not None and key in cache:
        dtf, ds, dsf = cache[key]
    else:
        dtf, ds, dsf = stats_at(run, t, h)
        if cache is not None:
            cache[key] = (dtf, ds, dsf)
    if cache is not None and 'trend' in cache:
        T = cache['trend']
    else:
        T, _, _ = trend_term(run, t)
        if cache is not None:
            cache['trend'] = T
    F = np.log1p(dtf) if unit == 'mention' else np.log1p(dsf)
    s = F * (idf if use_idf else 1.0) * np.power(ds + 0.05, beta) * np.power(2.0, gamma * T)
    if use_c:
        s = s * np.where(run.isg, 1.0, c_low)
    return s

# ---------------- 베이스라인 ----------------
def recent_idx(run, t, window=28):
    return [i for i, d in enumerate(run.days) if t - window < d <= t]

def score_yake(run, t):
    idx = recent_idx(run, t)
    sents = []
    for i in idx:
        for ut in run.utt_toks[i]:
            if ut:
                sents.append(' '.join(x.replace(' ', '_') for x in ut) + '.')
    s = np.zeros(len(run.tokens))
    if not sents:
        return s
    kw = yake.KeywordExtractor(lan='en', n=1, dedupLim=0.95, top=120).extract_keywords(' '.join(sents))
    low = {x.replace(' ', '_').lower(): j for j, x in enumerate(run.tokens)}
    for k, sc in kw:
        j = low.get(k.lower())
        if j is not None:
            s[j] = 1.0 / (sc + 1e-6)
    return s * run.C

def score_textrank(run, t):
    idx = recent_idx(run, t)
    G = nx.Graph()
    for i in idx:
        for ut in run.utt_toks[i]:
            u = list(dict.fromkeys(ut))
            for a in range(len(u)):
                G.add_node(u[a])
                for b in range(a + 1, len(u)):
                    w = G[u[a]][u[b]]['weight'] + 1 if G.has_edge(u[a], u[b]) else 1
                    G.add_edge(u[a], u[b], weight=w)
    s = np.zeros(len(run.tokens))
    if G.number_of_nodes() == 0:
        return s
    pr = nx.pagerank(G, weight='weight')
    for k, v in pr.items():
        s[run.vocab[k]] = v
    return s * run.C

def score_krwr(run, t):
    idx = recent_idx(run, t)
    texts = [u for i in idx for u in run.utts[i]]
    s = np.zeros(len(run.tokens))
    if len(texts) < 5:
        return s, {}
    try:
        ext = KRWordRank(min_count=2, max_length=12, verbose=False)
        kws, _, _ = ext.extract(texts, beta=0.85, max_iter=10)
    except Exception:
        return s, {}
    # KR-WordRank는 자체 후보를 내므로 후보를 그대로 랭킹(토큰 공간으로 매핑)
    out = {}
    for w, v in kws.items():
        c = GAZ.v2c.get(norm_key(w))
        key = DISPLAY[c] if (c and run.pipe == 'T4') else w
        out[key] = max(out.get(key, 0), v * CW(key))
    return s, out

# ---------------- 평가 ----------------
def evaluate_rank(tokens_sorted, gt, user, t, k=10):
    seen, slots, dup = set(), [], 0
    raw = 0
    for tok in tokens_sorted:
        c = oracle_concept(tok)
        if raw < k:
            raw += 1
            if c is not None and c in seen:
                dup += 1
        if c is not None:
            if c in seen:
                continue
            seen.add(c)
        slots.append(c)
        if len(slots) == k:
            break
    gains = [gt.get(c, 0.0) if c else 0.0 for c in slots]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted(gt.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    true_top = set(sorted(gt, key=lambda c: -gt[c])[:k])
    pred_c = set(c for c in slots if c)
    p10 = len(pred_c & true_top) / max(1, min(k, len(true_top)))
    intr = sum(1 for c in slots if c is None) / k
    stale = sum(1 for c in slots if c and gt.get(c, 0) < 0.05) / k
    burst, rise, fade = [], [], []
    for c, (kind, p) in user['traj'].items():
        if kind == 'burst' and p['day'] <= t:
            burst.append(1.0 if c in pred_c else 0.0)
        if kind == 'rising':
            now = lam(kind, p, t)
            if now < 0.5 * p['a'] and gt.get(c, 0) >= 0.5 * p['a']:   # 이륙 직전: 아직 낮지만 곧 높아짐
                rise.append(1.0 if c in pred_c else 0.0)
        if kind == 'fading':
            if gt.get(c, 0) < 0.2 * p['a']:                         # 이미 식은 관심
                fade.append(1.0 if c in pred_c else 0.0)
    return dict(ndcg=dcg / idcg if idcg > 0 else 0, p10=p10, intrusion=intr, stale=stale, dup=dup / k,
                burst=burst, rise=rise, fade=fade, slots=slots)

def concept_scores(run, s):
    cs = defaultdict(float)
    for j, tok in enumerate(run.tokens):
        c = run.concept[j]
        if c:
            cs[c] = max(cs[c], s[j])
    return cs

def spearman(gt, cs):
    a = [gt.get(c, 0.0) for c in CONCEPT_IDS]
    b = [cs.get(c, 0.0) for c in CONCEPT_IDS]
    r = spearmanr(a, b).correlation
    return 0.0 if r != r else float(r)

def ranked_tokens(run, s):
    order = np.argsort(-s)
    return [run.tokens[j] for j in order if s[j] > 0]

class Agg:
    def __init__(self):
        self.d = defaultdict(list)
        self.prev = {}
    def add(self, ev, runkey, extra=None):
        for m in ('ndcg', 'p10', 'intrusion', 'stale', 'dup'):
            self.d[m].append(ev[m])
        for m in ('burst', 'rise', 'fade'):
            self.d[m].extend(ev[m])
        top = set(c for c in ev['slots'] if c)
        if runkey in self.prev:
            self.d['churn'].append(1 - len(top & self.prev[runkey]) / 10)
        self.prev[runkey] = top
        if extra:
            for k, v in extra.items():
                self.d[k].append(v)
    def summary(self):
        out = {}
        for k, v in self.d.items():
            out[k] = float(np.mean(v)) if len(v) else 0.0
        return out

def boot_diff(a, b, n=2000, seed=0):
    d = np.array(a) - np.array(b)
    rng = np.random.default_rng(seed)
    bs = [rng.choice(d, size=len(d), replace=True).mean() for _ in range(n)]
    return [float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]

# ---------------- 메인 ----------------
def main():
    T0 = time.time()
    bg = [simulate_user(random_spec(np.random.default_rng(1000 + i)), seed=1000 + i) for i in range(40)]
    train_users = [simulate_user(random_spec(np.random.default_rng(2000 + i)), seed=2000 + i) for i in range(24)]
    test_users = {(p, s): simulate_user(PERSONAS[p], seed=s) for p in PERSONAS for s in TEST_SEEDS}
    dfs = {p: build_idf(bg, p) for p in PIPES}
    test_runs = {p: {k: Run(u, p) for k, u in test_users.items()} for p in PIPES}
    train_runs = [Run(u, 'T4') for u in train_users]
    print('setup', round(time.time() - T0, 1), 's')

    # ---------- 1) 가중치 그리드 ----------
    Hs, Bs, Gs, Us, Cs = [2, 3.5, 7, 14, 28, 1e9], [0, 0.5, 1], [0, 0.5, 1, 2], ['mention', 'session'], [0.1, 0.35, 0.6, 1.0]
    combos = [(h, b, g, u, c) for h in Hs for b in Bs for g in Gs for u in Us for c in Cs]
    def grid_eval(pairs):
        aggs = {cb: Agg() for cb in combos}
        for ri, (run, user) in enumerate(pairs):
            idf = idf_vec(run, dfs['T4'])
            for t in EVAL_DAYS:
                gt = ground_truth(user['traj'], t)
                cache = {}
                for cb in combos:
                    h, b, g, u, c = cb
                    s = score_ours(run, t, idf, h, b, g, u, c, cache=cache)
                    aggs[cb].add(evaluate_rank(ranked_tokens(run, s), gt, user, t), ri)
        return {cb: a.summary() for cb, a in aggs.items()}
    g_train = grid_eval(list(zip(train_runs, train_users)))
    g_test = grid_eval([(test_runs['T4'][k], test_users[k]) for k in test_users])
    best = max(combos, key=lambda cb: g_train[cb]['ndcg'])
    near = [cb for cb in combos if g_train[cb]['ndcg'] >= g_train[best]['ndcg'] - 0.01]
    balanced = min(near, key=lambda cb: g_train[cb]['churn'])
    static = max((cb for cb in combos if cb[2] == 0), key=lambda cb: g_train[cb]['ndcg'])
    print('best', best, round(g_train[best]['ndcg'], 4), '| balanced', balanced, round(g_train[balanced]['ndcg'], 4),
          'churn', round(g_train[balanced]['churn'], 3), 'vs', round(g_train[best]['churn'], 3), '| static', static)
    print('grid', round(time.time() - T0, 1), 's')

    # ---------- 2) 학습형 랭커 ----------
    def feats(run, t, idf):
        mask = run.days <= t
        tf = mask.astype(float) @ run.M
        d7, _, _ = stats_at(run, t, 7)
        d14, ds14, _ = stats_at(run, t, 14)
        d28, _, _ = stats_at(run, t, 28)
        T, f, ys = trend_term(run, t)
        last = np.full(len(run.tokens), 84.0)
        for j in range(len(run.tokens)):
            dd = run.days[mask & (run.M[:, j] > 0)]
            if len(dd):
                last[j] = t - dd.max()
        mx = (run.M * mask[:, None]).max(axis=0)
        nsess = (run.P * mask[:, None]).sum(axis=0)
        return np.vstack([np.log1p(tf), np.log1p(d7), np.log1p(d14), np.log1p(d28), idf, ds14, ys[-1], ys[-2:].sum(0),
                          ys[-4:].sum(0), last, mx / np.maximum(tf, 1), f, T, run.isg.astype(float), np.log1p(nsess)]).T
    FEAT_NAMES = ['log 누적 빈도', 'log 감쇠 빈도(7일)', 'log 감쇠 빈도(14일)', 'log 감쇠 빈도(28일)', 'IDF(희소성)', '세션 분산도',
                  '최근 1주 세션 수', '최근 2주 세션 수', '최근 4주 세션 수', '마지막 언급 후 경과일', '한 세션 몰림 정도',
                  'Holt 예측', '추세', '개념 사전 포함 여부', 'log 누적 세션 수']
    Xs, ys_ = [], []
    for run, user in zip(train_runs, train_users):
        idf = idf_vec(run, dfs['T4'])
        for t in EVAL_DAYS:
            gt = ground_truth(user['traj'], t)
            ms = (run.M[run.days <= t].sum(0) > 0)
            Xs.append(feats(run, t, idf)[ms])
            ys_.append(np.array([gt.get(c, 0.0) if c else 0.0 for c, m in zip(run.concept, ms) if m]))
    Xtr, ytr = np.vstack(Xs), np.concatenate(ys_)
    gbm = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, random_state=0)
    t1 = time.time(); gbm.fit(Xtr, ytr); fit_sec = time.time() - t1

    def gbm_score(run, t, idf):
        ms = (run.M[run.days <= t].sum(0) > 0)
        p = gbm.predict(feats(run, t, idf))
        return np.where(ms, np.maximum(p, 0) + 1e-6, 0)

    # ---------- 3) 방법 비교 ----------
    def cfg_lambda(cb):
        h, b, g, u, c = cb
        return lambda run, t, idf: score_ours(run, t, idf, h, b, g, u, c)
    def lbl(cb):
        h, b, g, u, c = cb
        hh = '∞' if h > 1e8 else f'{h:g}일'
        return f'반감기 {hh} · 분산 β={b:g} · 추세 γ={g:g} · {"세션" if u == "session" else "언급"} 단위 · 사전 밖 {c:g}'
    methods = [
        ('단순 빈도 (TF)', '누적 언급 횟수', lambda run, t, idf: ((run.days <= t).astype(float) @ run.M) * run.C),
        ('TF-IDF', '누적 빈도 × 희소성', lambda run, t, idf: ((run.days <= t).astype(float) @ run.M) * idf * run.C),
        ('감쇠 빈도', '14일 반감기 빈도', lambda run, t, idf: stats_at(run, t, 14)[0] * run.C),
        ('감쇠 TF-IDF', '14일 반감기 빈도 × 희소성', lambda run, t, idf: stats_at(run, t, 14)[0] * idf * run.C),
        ('YAKE', '통계 기반 키워드 추출 (최근 4주)', lambda run, t, idf: score_yake(run, t)),
        ('TextRank', '공출현 그래프 PageRank (최근 4주)', lambda run, t, idf: score_textrank(run, t)),
        ('KR-WordRank', '토크나이저 없는 한국어 키워드 추출', None),
        ('Holt 시계열 예측', '주간 세션 수의 2주 뒤 예측 × 희소성', lambda run, t, idf: trend_term(run, t)[1] * idf * run.C),
        ('제안 A (정적 가중합)', lbl(static), cfg_lambda(static)),
        ('제안 B (NDCG 최적)', lbl(best), cfg_lambda(best)),
        ('제안 C (안정성 균형) ★', lbl(balanced), cfg_lambda(balanced)),
        ('학습형 랭커 (GBM)', '15개 특징 · 가상 사용자 24명으로 학습', gbm_score),
    ]
    aggs = {m[0]: Agg() for m in methods}
    lat = {m[0]: [] for m in methods}
    churn_true = Agg()
    per_ndcg = {m[0]: [] for m in methods}
    for ri, (key, user) in enumerate(test_users.items()):
        run = test_runs['T4'][key]
        idf = idf_vec(run, dfs['T4'])
        for t in EVAL_DAYS:
            gt = ground_truth(user['traj'], t)
            ttop = sorted(gt, key=lambda c: -gt[c])[:10]
            churn_true.add(dict(ndcg=1, p10=1, intrusion=0, stale=0, dup=0, burst=[], rise=[], fade=[], slots=ttop), ri)
            for name, _, f in methods:
                t1 = time.perf_counter()
                if name == 'KR-WordRank':
                    _, kw = score_krwr(run, t)
                    toks = [k for k, v in sorted(kw.items(), key=lambda x: -x[1]) if v > 0]
                    cs = defaultdict(float)
                    for k, v in kw.items():
                        c = oracle_concept(k)
                        if c:
                            cs[c] = max(cs[c], v)
                else:
                    s = f(run, t, idf)
                    toks = ranked_tokens(run, s)
                    cs = concept_scores(run, s)
                lat[name].append((time.perf_counter() - t1) * 1000)
                ev = evaluate_rank(toks, gt, user, t)
                aggs[name].add(ev, ri, extra={'spearman': spearman(gt, cs), 'ndcg_' + key[0]: ev['ndcg']})
                per_ndcg[name].append(ev['ndcg'])
    table = []
    for name, desc, _ in methods:
        s = aggs[name].summary()
        row = dict(method=name, desc=desc, ndcg=s['ndcg'], ndcg_sd=float(np.std(per_ndcg[name])), p10=s['p10'],
                   spearman=s['spearman'], intrusion=s['intrusion'], stale=s['stale'], burst_fp=s.get('burst', 0),
                   rise_hit=s.get('rise', 0), fade_stale=s.get('fade', 0), churn=s['churn'],
                   latency_ms=float(np.median(lat[name])), by_persona={p: s.get('ndcg_' + p, 0) for p in PERSONAS})
        table.append(row)
        print(f"{name:22s} NDCG {row['ndcg']:.3f}±{row['ndcg_sd']:.3f} P@10 {row['p10']:.3f} rho {row['spearman']:.3f} "
              f"intr {row['intrusion']:.3f} burst {row['burst_fp']:.3f} rise {row['rise_hit']:.3f} fade {row['fade_stale']:.3f} "
              f"churn {row['churn']:.3f} {row['latency_ms']:.1f}ms")
    print('true churn', churn_true.summary()['churn'])
    ci = {'C_vs_감쇠TFIDF': boot_diff(per_ndcg['제안 C (안정성 균형) ★'], per_ndcg['감쇠 TF-IDF']),
          'C_vs_TF': boot_diff(per_ndcg['제안 C (안정성 균형) ★'], per_ndcg['단순 빈도 (TF)']),
          'B_vs_C': boot_diff(per_ndcg['제안 B (NDCG 최적)'], per_ndcg['제안 C (안정성 균형) ★']),
          'GBM_vs_C': boot_diff(per_ndcg['학습형 랭커 (GBM)'], per_ndcg['제안 C (안정성 균형) ★'])}
    print('CI', ci)

    # ---------- 4) ablation (제안 C 고정) ----------
    h_, b_, g_, u_, c_ = balanced
    abl = []
    def run_cfg(label, pipe, **kw):
        ag = Agg()
        for ri, (key, user) in enumerate(test_users.items()):
            run = test_runs[pipe][key]
            idf = idf_vec(run, dfs[pipe])
            for t in EVAL_DAYS:
                gt = ground_truth(user['traj'], t)
                s = score_ours(run, t, idf, kw.get('h', h_), kw.get('beta', b_), kw.get('gamma', g_), kw.get('unit', u_),
                               kw.get('c_low', c_), use_idf=kw.get('use_idf', True), use_c=kw.get('use_c', True))
                ag.add(evaluate_rank(ranked_tokens(run, s), gt, user, t), ri)
        s = ag.summary()
        abl.append(dict(label=label, ndcg=s['ndcg'], intrusion=s['intrusion'], dup=s['dup'], churn=s['churn'],
                        burst=s.get('burst', 0), rise=s.get('rise', 0)))
        print(f"  {label:34s} NDCG {s['ndcg']:.3f} intr {s['intrusion']:.3f} dup {s['dup']:.3f} churn {s['churn']:.3f} burst {s.get('burst',0):.3f} rise {s.get('rise',0):.3f}")
    print('ablation:')
    run_cfg('전체 (사전 매칭+Kiwi+정규화)', 'T4')
    run_cfg('− 동의어 정규화', 'T3')
    run_cfg('− 개념 사전 매칭 (Kiwi 명사만)', 'T2')
    run_cfg('− 형태소 분석 (조사 규칙만)', 'T1')
    run_cfg('− 전처리 없음 (띄어쓰기 분리)', 'T0')
    run_cfg('− 개념성 가중치', 'T4', use_c=False)
    run_cfg('− IDF(희소성)', 'T4', use_idf=False)
    run_cfg('− 최근성 감쇠', 'T4', h=1e9)
    run_cfg('− 세션 단위 (언급 단위로)', 'T4', unit='mention')
    run_cfg('− 추세 항', 'T4', gamma=0)

    # ---------- 5) GBM 특징 중요도 ----------
    from sklearn.inspection import permutation_importance
    Xte, yte = [], []
    for key, user in test_users.items():
        run = test_runs['T4'][key]
        idf = idf_vec(run, dfs['T4'])
        for t in EVAL_DAYS:
            gt = ground_truth(user['traj'], t)
            ms = (run.M[run.days <= t].sum(0) > 0)
            Xte.append(feats(run, t, idf)[ms])
            yte.append(np.array([gt.get(c, 0.0) if c else 0.0 for c, m in zip(run.concept, ms) if m]))
    Xte, yte = np.vstack(Xte), np.concatenate(yte)
    pi = permutation_importance(gbm, Xte, yte, n_repeats=5, random_state=0)
    fi = sorted([dict(feature=n, importance=float(v)) for n, v in zip(FEAT_NAMES, pi.importances_mean)], key=lambda x: -x['importance'])
    print('fi', [(x['feature'], round(x['importance'], 3)) for x in fi[:6]])

    # ---------- 6) UI 데이터 ----------
    ui = {}
    for p in PERSONAS:
        key = (p, 0)
        user, run = test_users[key], test_runs['T4'][key]
        idf = idf_vec(run, dfs['T4'])
        weeks = []
        for wk in range(2, 12):
            t = wk * 7
            T, f, ys = trend_term(run, t)
            sC = score_ours(run, t, idf, h_, b_, g_, u_, c_)
            sTF = ((run.days <= t).astype(float) @ run.M)
            gt = ground_truth(user['traj'], t)
            def top_list(s, n=10):
                out, seen = [], set()
                for j in np.argsort(-s):
                    if s[j] <= 0 or len(out) >= n:
                        break
                    c = run.concept[j]
                    if c and c in seen:
                        continue
                    if c:
                        seen.add(c)
                    kind = user['traj'][c][0] if (c and c in user['traj']) else ('concept' if c else 'noise')
                    out.append(dict(term=run.tokens[j], cid=c, score=float(s[j]), trend=float(T[j]),
                                    spark=[float(v) for v in ys[:, j]], kind=kind, gt=float(gt.get(c, 0.0)) if c else 0.0,
                                    in_glossary=bool(run.isg[j])))
                return out
            weeks.append(dict(week=wk, day=t, ours=top_list(sC), tf=top_list(sTF),
                              gt_top=[dict(cid=c, term=DISPLAY[c], gt=float(v)) for c, v in sorted(gt.items(), key=lambda x: -x[1])[:10]]))
        lines = {}
        for c, (k, prm) in user['traj'].items():
            if k != 'low':
                lines[c] = dict(term=DISPLAY[c], kind=k, lam=[float(lam(k, prm, d)) for d in range(0, 85, 1)],
                                burst_day=prm.get('day'))
        # 개념별 예측 점수 궤적 (TF vs 제안 C), 일 단위
        traces = {}
        for c in lines:
            js = [j for j, cc in enumerate(run.concept) if cc == c]
            tr_c, tr_tf = [], []
            for t in range(7, 78):
                sC = score_ours(run, t, idf, h_, b_, g_, u_, c_)
                sT = ((run.days <= t).astype(float) @ run.M)
                tr_c.append(float(max([sC[j] for j in js], default=0)))
                tr_tf.append(float(max([sT[j] for j in js], default=0)))
            traces[c] = dict(ours=tr_c, tf=tr_tf)
        si = [i for i, d in enumerate(run.days) if d <= 56][-1]
        ui[p] = dict(name=PERSONAS[p]['name'], domain=PERSONAS[p]['domain'], weeks=weeks, lines=lines, traces=traces,
                     sample=dict(day=int(run.days[si]), utts=run.utts[si]),
                     n_sessions=len(run.days), n_utts=int(sum(len(x) for x in run.utts)))

    def ck(cb):
        return f'{cb[0]}|{cb[1]}|{cb[2]}|{cb[3]}|{cb[4]}'
    out = dict(
        config=dict(eval_days=EVAL_DAYS, test_seeds=TEST_SEEDS, n_bg=40, n_train=24, glossary_coverage=0.85,
                    missing_glossary=[DISPLAY[c] for c in CONCEPT_IDS if c not in GLOSSARY],
                    best=list(best), balanced=list(balanced), static=list(static),
                    grid=dict(H=Hs, B=Bs, G=Gs, U=Us, C=Cs), gbm_train_rows=int(Xtr.shape[0]), gbm_fit_sec=fit_sec,
                    n_test_points=len(per_ndcg['TF-IDF'])),
        table=table, ci=ci, ablation=abl, churn_true=churn_true.summary()['churn'],
        grid_train={ck(cb): dict(ndcg=v['ndcg'], churn=v['churn']) for cb, v in g_train.items()},
        grid_test={ck(cb): {m: v.get(m, 0) for m in ('ndcg', 'p10', 'intrusion', 'burst', 'rise', 'fade', 'churn', 'stale')} for cb, v in g_test.items()},
        feature_importance=fi, ui=ui)
    results_dir = pathlib.Path(__file__).resolve().parent / 'results'   # 실행 위치와 무관하게 sim/results/
    results_dir.mkdir(exist_ok=True)
    with open(results_dir / 'A.json', 'w', encoding='utf-8') as fp:
        json.dump(out, fp, ensure_ascii=False)
    print('done', round(time.time() - T0, 1), 's')

if __name__ == '__main__':
    main()
