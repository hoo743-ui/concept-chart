# -*- coding: utf-8 -*-
"""가상 사용자 대화 로그 생성기: 관심 궤적(λ)을 심고 한국어 발화를 만든다."""
import math, random, re
import numpy as np
from concepts import CONCEPT_IDS, VARIANTS, GENERIC, DOMAINS

# ---------- 조사 ----------
def batchim_info(word):
    w = re.sub(r'[^0-9A-Za-z가-힣]+$', '', word.strip())
    if not w:
        return (False, False)
    ch = w[-1]
    code = ord(ch)
    if 0xAC00 <= code <= 0xD7A3:
        j = (code - 0xAC00) % 28
        return (j != 0, j == 8)
    if ch.isdigit():
        table = {'0': (True, False), '1': (True, True), '2': (False, False), '3': (True, False),
                 '4': (False, False), '5': (False, False), '6': (True, False), '7': (True, True),
                 '8': (True, True), '9': (False, False)}
        return table[ch]
    if ch.isupper():
        if ch in 'LMN':
            return (True, ch == 'L')
        if ch == 'R':
            return (True, True)
        return (False, False)
    lw = w.lower()
    if lw.endswith('ng'):
        return (True, False)
    if re.search(r'[^aeiou]e$', lw):
        lw = lw[:-1]
    if lw.endswith(('m', 'n')):
        return (True, False)
    if lw.endswith('l'):
        return (True, True)
    return (False, False)

PAIRS = {'을': ('을', '를'), '이': ('이', '가'), '은': ('은', '는'), '와': ('과', '와'),
         '이랑': ('이랑', '랑'), '이란': ('이란', '란')}

def josa(word, p):
    if not p:
        return word
    if p in ('도', '의', '에', '에서', '만'):
        return word + p
    bat, rieul = batchim_info(word)
    if p == '으로':
        return word + ('로' if (not bat or rieul) else '으로')
    a, b = PAIRS[p]
    return word + (a if bat else b)

# ---------- 템플릿 ----------
T1 = ["{C1:이} 정확히 뭐야?",
      "{C1:을} 공부하는데 {G1:이} 잘 이해가 안 돼",
      "오늘 {G1} 정리하다가 {C1:을} 처음 써봤어",
      "{C1} 때문에 {G1:이} 계속 이상하게 나와",
      "{D1} 업무에 {C1:을} 적용할 수 있을까?",
      "{C1} 예시 좀 보여줘",
      "{G1:을} 다시 보니까 {C1:이} 핵심인 것 같아",
      "{C1:은} 왜 필요한 거야? {G1:으로} 설명해줘",
      "{D1} {G1:에} {C1:을} 써도 돼?",
      "어제 본 {G1}에서 {C1} 얘기가 나왔는데 무슨 뜻이야"]
T2 = ["{C1:와} {C2:의} 차이가 뭐야?",
      "{C1:을} 쓰려면 {C2:도} 알아야 해?",
      "{C1} 다음에 {C2:을} 공부하면 될까?",
      "{C1:이랑} {C2} 같이 쓰는 {G1} 있어?"]
T0 = ["{D1} {G1:이} 너무 많아서 정리가 필요해",
      "{G1:이랑} {G2:을} 한 번에 정리해줘",
      "오늘 {D1} 때문에 {G1:을} 못 봤어",
      "{D1} 관련 {G1} 다시 설명해줘",
      "{G1:은} 어디서부터 보면 돼?"]
BURST_T = ["{C1:이} 요즘 다들 얘기하던데 뭐야?", "{C1} 구조 그림 좀 설명해줘", "{C1:은} 어디에 쓰여?",
           "{C1} 관련 {G1} 하나만 더 보여줘", "{C1:을} 처음부터 다시 설명해줘", "{C1:와} 다른 것들 차이가 뭐야?"]

SLOT = re.compile(r'\{([CGD])(\d)(?::([^}]*))?\}')

def render(tpl, fill):
    def rep(m):
        kind, idx, p = m.group(1), m.group(2), m.group(3)
        return josa(fill[kind + idx], p)
    return SLOT.sub(rep, tpl)

GEN_W = np.array([1.0 / (r + 1) ** 0.8 for r in range(len(GENERIC))])
GEN_W = GEN_W / GEN_W.sum()

def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))

# ---------- 페르소나 → 관심 궤적 ----------
def make_traj(spec, rng):
    """spec: dict(core, rising, fading, burst, low) -> {cid: (kind, params)}"""
    traj = {}
    for c in spec.get('core', []):
        traj[c] = ('core', dict(a=rng.uniform(0.8, 1.2)))
    for c in spec.get('rising', []):
        traj[c] = ('rising', dict(a=rng.uniform(1.0, 1.4), d0=rng.uniform(28, 48), s=rng.uniform(3, 6)))
    for c in spec.get('fading', []):
        traj[c] = ('fading', dict(a=rng.uniform(1.0, 1.4), d0=rng.uniform(24, 40), s=rng.uniform(3, 6)))
    for c in spec.get('low', []):
        traj[c] = ('low', dict(a=0.08))
    for c in spec.get('burst', []):
        traj[c] = ('burst', dict(day=None, k=int(rng.integers(6, 11))))
    return traj

def lam(kind, p, d):
    if kind == 'core':
        return p['a']
    if kind == 'rising':
        return p['a'] * sigmoid((d - p['d0']) / p['s'])
    if kind == 'fading':
        return p['a'] * (1 - sigmoid((d - p['d0']) / p['s']))
    if kind == 'low':
        return p['a']
    return 0.0  # burst: 관심이 아니라 일회성 사건

def simulate_user(spec, seed, days=84, p_session=3 / 7):
    rng = np.random.default_rng(seed)
    spec = dict(spec)
    used = set(spec.get('core', []) + spec.get('rising', []) + spec.get('fading', []) + spec.get('burst', []))
    if 'low' not in spec:
        others = [c for c in CONCEPT_IDS if c not in used]
        spec['low'] = list(rng.choice(others, size=6, replace=False))
    traj = make_traj(spec, rng)
    # 표기 선호 (사용자마다 다름)
    vpref = {}
    for c in traj:
        vs = VARIANTS[c]
        w = rng.dirichlet(np.ones(len(vs)) * 0.8)
        vpref[c] = w
    domain_words = DOMAINS[spec['domain']]
    session_days = [d for d in range(days) if rng.random() < p_session]
    # 버스트 날짜 지정
    for c, (kind, p) in traj.items():
        if kind == 'burst':
            cand = [d for d in session_days if 14 <= d <= 45] or session_days[len(session_days) // 3: len(session_days) // 2 + 1]
            p['day'] = int(rng.choice(cand))
    interest = [c for c, (k, _) in traj.items() if k != 'burst']

    def pick_variant(c):
        vs = VARIANTS[c]
        return vs[int(rng.choice(len(vs), p=vpref[c]))]

    def gen_fill(cs):
        fill = {}
        for i, c in enumerate(cs, 1):
            fill[f'C{i}'] = pick_variant(c)
        g = rng.choice(len(GENERIC), size=2, replace=False, p=GEN_W)
        fill['G1'], fill['G2'] = GENERIC[g[0]], GENERIC[g[1]]
        fill['D1'] = domain_words[int(rng.integers(len(domain_words)))]
        return fill

    sessions = []
    for d in session_days:
        n_utt = 6 + int(rng.poisson(5))
        w = np.array([lam(*traj[c], d) for c in interest]) + 1e-3
        w = w / w.sum()
        utts, mentions = [], []
        for _ in range(n_utt):
            r = rng.random()
            if r < 0.22:
                tpl = T0[int(rng.integers(len(T0)))]
                cs = []
            elif r < 0.82:
                tpl = T1[int(rng.integers(len(T1)))]
                cs = [interest[int(rng.choice(len(interest), p=w))]]
            else:
                tpl = T2[int(rng.integers(len(T2)))]
                idx = rng.choice(len(interest), size=2, replace=False, p=w)
                cs = [interest[int(idx[0])], interest[int(idx[1])]]
            utts.append(render(tpl, gen_fill(cs)))
            mentions.append(cs)
        for c, (kind, p) in traj.items():
            if kind == 'burst' and p['day'] == d:
                for _ in range(p['k']):
                    tpl = BURST_T[int(rng.integers(len(BURST_T)))]
                    utts.append(render(tpl, gen_fill([c])))
                    mentions.append([c])
        sessions.append(dict(day=d, utts=utts, mentions=mentions))
    return dict(spec=spec, traj=traj, sessions=sessions)

def ground_truth(traj, t, horizon=14):
    """정답 중요도 = 앞으로 horizon일 동안의 평균 관심 강도 (미래 예측 대상)"""
    gt = {}
    for c, (kind, p) in traj.items():
        v = np.mean([lam(kind, p, d) for d in range(t + 1, t + horizon + 1)])
        if v > 0:
            gt[c] = float(v)
    return gt

def random_spec(rng):
    ids = list(CONCEPT_IDS)
    rng.shuffle(ids)
    k = [int(rng.integers(2, 5)), int(rng.integers(2, 5)), int(rng.integers(1, 4)), int(rng.integers(1, 3))]
    s = 0
    spec = {}
    for name, n in zip(['core', 'rising', 'fading', 'burst'], k):
        spec[name] = ids[s:s + n]
        s += n
    spec['low'] = ids[s:s + 6]
    spec['domain'] = list(DOMAINS)[int(rng.integers(len(DOMAINS)))]
    return spec
