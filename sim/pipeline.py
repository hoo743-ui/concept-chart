# -*- coding: utf-8 -*-
"""토큰화 파이프라인 T0~T4, 개념 사전(glossary), 평가용 매핑"""
import re
import numpy as np
from kiwipiepy import Kiwi
from concepts import CONCEPTS, CONCEPT_IDS, VARIANTS, DISPLAY

kiwi = Kiwi()

def norm_key(s):
    return re.sub(r'[\s\-_/]+', '', s.lower())

# 평가용 오라클 매핑: 어떤 표기든 개념 id로 (평가에만 사용)
ORACLE = {}
for c, vs in CONCEPTS:
    for v in vs:
        ORACLE[norm_key(v)] = c

def oracle_concept(token):
    return ORACLE.get(norm_key(token))

# ---- 개념 사전 (실서비스 자산): 커버리지 85% 가정 ----
def build_glossary(coverage=0.85, seed=123):
    rng = np.random.default_rng(seed)
    ids = list(CONCEPT_IDS)
    keep = set(rng.choice(ids, size=int(round(len(ids) * coverage)), replace=False).tolist())
    return keep

STOP = set("""정확히 뭐야 공부하는데 이해가 안 돼 오늘 정리하다가 처음 써봤어 때문에 계속 이상하게 나와 업무에 적용할 수 있을까
예시 좀 보여줘 다시 보니까 핵심인 것 같아 왜 필요한 거야 설명해줘 써도 어제 본 얘기가 나왔는데 무슨 뜻이야 차이가 쓰려면
알아야 해 다음에 공부하면 될까 같이 쓰는 있어 너무 많아서 정리가 필요해 한 번에 정리해줘 못 봤어 관련 어디서부터 보면
요즘 다들 얘기하던데 구조 그림 어디에 쓰여 하나만 더 처음부터 다른 것들 차이 거야 써봤어 될까 있어 뭐""".split())
JOSA = sorted(["이랑", "에서", "으로", "까지", "부터", "하고", "에게", "한테", "처럼", "보다", "이란", "의", "을", "를", "이", "가",
               "은", "는", "와", "과", "로", "도", "에", "랑", "만", "란"], key=len, reverse=True)
WORD = re.compile(r'[0-9A-Za-z가-힣/\-]+')

def tok_T0(text):
    return [t for t in WORD.findall(text) if len(t) >= 2 and t not in STOP]

def strip_josa(t):
    for j in JOSA:
        if t.endswith(j) and len(t) - len(j) >= 2:
            return t[:-len(j)]
    return t

def tok_T1(text):
    out = []
    for t in WORD.findall(text):
        t2 = strip_josa(t)
        if len(t2) >= 2 and t2 not in STOP:
            out.append(t2)
    return out

NOUN = ('NNG', 'NNP', 'SL', 'SH')

def kiwi_nouns(text):
    return [x.form for x in kiwi.tokenize(text) if x.tag in NOUN and len(x.form) >= 2]

def tok_T2(text):
    return kiwi_nouns(text)

class Gazetteer:
    def __init__(self, glossary_ids):
        self.ids = set(glossary_ids)
        pats = []
        self.v2c = {}
        for c in self.ids:
            for v in VARIANTS[c]:
                self.v2c[norm_key(v)] = c
                p = re.escape(v).replace(r'\ ', r'\s*')
                if re.match(r'[A-Za-z0-9]', v):
                    p = r'(?<![A-Za-z0-9])' + p
                if re.search(r'[A-Za-z0-9]$', v):
                    p = p + r'(?![A-Za-z])'
                pats.append((len(v), p))
        pats.sort(key=lambda x: -x[0])
        self.rx = re.compile('|'.join(p for _, p in pats), re.IGNORECASE)

    def split(self, text):
        found = []
        def rep(m):
            found.append(m.group(0))
            return ' ' * len(m.group(0))
        rest = self.rx.sub(rep, text)
        return found, rest

def make_tok_T3(gaz):
    def f(text):
        found, rest = gaz.split(text)
        return [re.sub(r'\s+', ' ', x) for x in found] + kiwi_nouns(rest)
    return f

def make_tok_T4(gaz):
    def f(text):
        found, rest = gaz.split(text)
        out = [DISPLAY[gaz.v2c[norm_key(x)]] for x in found]
        for t in kiwi_nouns(rest):
            c = gaz.v2c.get(norm_key(t))
            out.append(DISPLAY[c] if c else t)
        return out
    return f

def concept_weight_fn(gaz, low=0.35):
    """개념성 가중치: 개념 사전에 있으면 1, 아니면 low"""
    def w(token):
        return 1.0 if norm_key(token) in gaz.v2c else low
    return w
