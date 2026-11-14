# -*- coding: utf-8 -*-
"""수준선 근거 데이터 30분 실험 (2026-11-14). 정답 데이터가 없어 대리 과제로 잰다.
대리 과제: 일상 기초어(학습용 어휘 1단계 명사)와 기술 용어(kit/data/tech_terms.txt 한국어 표기)를 각 신호가 얼마나 가르는가(AUC).
그리고 이 Mac의 실제 Claude Code 답변에 적용해 답변당 낱말이 얼마나 줄어드는지 본다 (원문은 출력하지 않음, 낱말 빈도만).
"""
import glob, json, math, os, pathlib, re, sys, collections
from kiwipiepy import Kiwi

DS = pathlib.Path(sys.argv[1]); ROOT = pathlib.Path(sys.argv[2]); OUT = pathlib.Path(sys.argv[3])
kiwi = Kiwi()
HANGUL = re.compile(r"^[가-힣]+$")

# 1) 학습용 어휘 목록: 명사 → 등급
grade = {}
for line in (DS / "raw/vocab.txt").read_bytes().decode("cp949").splitlines()[1:]:
    p = line.split("\t")
    if len(p) >= 5 and p[2] == "명":
        w = re.sub(r"\d+$", "", p[1]).strip()
        grade.setdefault(w, p[4].strip())
print("학습용 어휘 명사", len(grade), collections.Counter(grade.values()))

# 2) Leipzig 뉴스 10만 문장 → Kiwi 명사 빈도 (어절 빈도는 조사가 붙어 쓸 수 없다)
freq = collections.Counter()
sents = [l.split("\t", 1)[1] for l in (DS / "raw/kor_news_2022_100K/kor_news_2022_100K-sentences.txt").read_text(encoding="utf-8").splitlines() if "\t" in l]
for toks in kiwi.tokenize(sents):
    for t in toks:
        if t.tag in ("NNG", "NNP", "SL"):
            freq[t.form.lower() if t.tag == "SL" else t.form] += 1
N = sum(freq.values())
zipf = lambda w: math.log10((freq.get(w, 0) + 1) / N * 1e9)          # wordfreq와 같은 눈금 (10억 낱말당 log10)
print("뉴스 문장", len(sents), "명사 토큰", N, "서로 다른 명사", len(freq))

# 3) 대리 과제
tech = [l.strip() for l in (ROOT / "kit/data/tech_terms.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
tech_ko = sorted({w for w in tech if HANGUL.match(w) and 2 <= len(w) <= 8} - set(grade))
basic = sorted(w for w, g in grade.items() if g == "A" and HANGUL.match(w))
def auc(pos, neg, score):   # pos가 더 어렵다 = 점수가 커야 한다
    s = sorted([(score(w), 1) for w in pos] + [(score(w), 0) for w in neg])
    r, i = 0.0, 0
    ranks = {}
    while i < len(s):
        j = i
        while j < len(s) and s[j][0] == s[i][0]: j += 1
        for k in range(i, j): ranks.setdefault(k, (i + j + 1) / 2)
        i = j
    rp = sum(ranks[k] for k, (v, y) in enumerate(s) if y == 1)
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))
res = {"tech_ko": len(tech_ko), "basic_A": len(basic),
       "auc_news_rarity": round(auc(tech_ko, basic, lambda w: -zipf(w)), 3),
       "tech_unseen_in_news": round(sum(freq.get(w, 0) == 0 for w in tech_ko) / len(tech_ko), 3),
       "basic_unseen_in_news": round(sum(freq.get(w, 0) == 0 for w in basic) / len(basic), 3)}
for cut in (3.0, 3.5, 4.0, 4.5):
    res[f"cut{cut}"] = {"tech_kept": round(sum(zipf(w) < cut for w in tech_ko) / len(tech_ko), 3),
                        "basic_kept": round(sum(zipf(w) < cut for w in basic) / len(basic), 3)}
# 흔한데도 기술 용어인 것 (수준선이 내려 버릴 낱말 예시)
res["tech_common_examples"] = sorted(tech_ko, key=lambda w: -zipf(w))[:25]
res["basic_rare_examples"] = sorted(basic, key=lambda w: zipf(w))[:15]

# 영어: wordfreq 점수는 venv에서 따로 계산해 둔 파일
en = json.loads((DS / "en_zipf.json").read_text(encoding="utf-8"))
res["en_tech_n"] = len(en)
for cut in (3.0, 4.0, 4.5, 5.0):
    res[f"en_tech_zipf_ge_{cut}"] = round(sum(v >= cut for v in en.values()) / len(en), 3)
res["en_tech_most_common"] = sorted(en, key=lambda w: -en[w])[:25]

# 4) 실제 Claude Code 답변 (이 Mac의 ~/.claude/projects)
answers = []
for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
    for line in open(f, encoding="utf-8", errors="ignore"):
        try: r = json.loads(line)
        except Exception: continue
        if r.get("type") != "assistant": continue
        c = r.get("message", {}).get("content")
        t = "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text") if isinstance(c, list) else ""
        if len(t) > 200 and re.search(r"[가-힣]", t): answers.append(t)
res["cc_answers"] = len(answers)
def level(w):   # 예시 규칙: 기초어 A·B → 0, 뉴스에서 흔함(zipf≥4) → 1, 그 밖 → 2
    if grade.get(w) in ("A", "B"): return 0
    return 1 if zipf(w) >= 4.0 else 2
per, words = [], collections.Counter()
for toks in kiwi.tokenize(answers[:400]):
    ns = {t.form for t in toks if t.tag in ("NNG", "NNP") and len(t.form) >= 2}
    if not ns: continue
    lv = collections.Counter(level(w) for w in ns)
    per.append((len(ns), lv[2], lv[1] + lv[2]))
    words.update(ns)
if per:
    res["cc_nouns_per_answer"] = round(sum(a for a, _, _ in per) / len(per), 1)
    res["cc_kept_strict"] = round(sum(b for _, b, _ in per) / sum(a for a, _, _ in per), 3)     # 기초어·흔한 말 빼기
    res["cc_kept_basic_only"] = round(sum(c for _, _, c in per) / sum(a for a, _, _ in per), 3) # 기초어만 빼기
    top = [w for w, _ in words.most_common(300)]
    res["cc_examples"] = {str(k): [w for w in top if level(w) == k][:20] for k in (0, 1, 2)}
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
