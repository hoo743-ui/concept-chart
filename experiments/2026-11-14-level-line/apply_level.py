# 실제 서버(임시 DB, 이 Mac의 Claude Code 대화 154답변)의 개념 판정 결과 위에 수준선 규칙을 얹어 본다. 서버 코드는 바꾸지 않는다.
# 규칙 (실험 2026-11-14-level-line에서 나온 제안):
#   초보   : 학습용 어휘 A·B 등급 명사는 선 아래
#   중급   : 학습용 어휘 A·B·C 모두 선 아래
#   실무자 : 중급 + 뉴스 빈도 zipf ≥ 4.0 이면 선 아래 (단, 개발 용어 사전에 있는 낱말은 남김 — 3-1에서 변수·상속이 숨던 문제)
import collections, csv, json, math, pathlib, re, sys, urllib.request
from kiwipiepy import Kiwi

DS, ROOT, PORT, OUT = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3], pathlib.Path(sys.argv[4])
get = lambda p: json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}{p}", timeout=60))

grade = {}
for line in (DS / "raw/vocab.txt").read_bytes().decode("cp949").splitlines()[1:]:
    p = line.split("\t")
    if len(p) >= 5 and p[2] == "명":
        grade.setdefault(re.sub(r"\d+$", "", p[1]).strip(), p[4].strip())
kiwi = Kiwi()
freq = collections.Counter()
sents = [l.split("\t", 1)[1] for l in (DS / "raw/kor_news_2022_100K/kor_news_2022_100K-sentences.txt").read_text(encoding="utf-8").splitlines() if "\t" in l]
for toks in kiwi.tokenize(sents):
    for t in toks:
        if t.tag in ("NNG", "NNP", "SL"):
            freq[t.form.lower() if t.tag == "SL" else t.form] += 1
N = sum(freq.values())
zipf = lambda w: math.log10((freq.get(w.lower() if w.isascii() else w, 0) + 1) / N * 1e9)
terms = {re.sub(r"[\s\-_/]+", "", l.strip().lower()) for l in (ROOT / "kit/data/tech_terms.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
in_terms = lambda w: re.sub(r"[\s\-_/]+", "", w.lower()) in terms

def below(label, level):
    g = grade.get(label)
    if level == "초보":
        return g in ("A", "B")
    if level == "중급":
        return g in ("A", "B", "C")
    return g in ("A", "B", "C") or (zipf(label) >= 4.0 and not in_terms(label))
LEVELS = ["초보", "중급", "실무자"]

items = get("/api/study/concepts?view=all&k=5000")["items"]
by_id = {x["id"]: x for x in items}
show = [x for x in items if x["gate"]["show"]]
judged = [x for x in items if x["gate"]["by"] != "unjudged"]
res = {"concepts_all": len(items), "judged": len(judged), "show_now": len(show)}
for top in (100, 200):
    t = [x for x in items if x["rank"] <= top]
    res[f"top{top}_judged"] = sum(x["gate"]["by"] != "unjudged" for x in t)
    res[f"top{top}_show_now"] = sum(x["gate"]["show"] for x in t)
    for lv in LEVELS:
        res[f"top{top}_show_{lv}"] = sum(x["gate"]["show"] and not below(x["label"], lv) for x in t)
for lv in LEVELS:
    res[f"show_{lv}"] = sum(not below(x["label"], lv) for x in show)

# 답변마다: 지금 공부 목록에 든 개념 수 → 수준선 뒤
answers = get("/api/answers?k=100")["items"]
per = []
for a in answers:
    d = get("/api/answers/" + a["id"])
    ids = [t["id"] if isinstance(t, dict) else t for t in d.get("terms", [])]
    shown = [by_id[i] for i in ids if i in by_id and by_id[i]["gate"]["show"]]
    per.append([len(shown)] + [sum(not below(x["label"], lv) for x in shown) for lv in LEVELS])
if per:
    res["answers"] = len(per)
    res["per_answer_now"] = round(sum(p[0] for p in per) / len(per), 2)
    for i, lv in enumerate(LEVELS, 1):
        res[f"per_answer_{lv}"] = round(sum(p[i] for p in per) / len(per), 2)

# 검증용 표: 지금 공부 목록의 모든 개념 + 수준별로 남는지
with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["순위", "개념", "답변 수", "판정 근거", "학습용 어휘 등급", "뉴스 zipf", "개발 용어 사전"] + [f"{lv} 남음" for lv in LEVELS] + ["내 판단(개념이 맞나·알아요/몰라요)"])
    for x in sorted(show, key=lambda x: x["rank"]):
        w.writerow([x["rank"], x["label"], x["turns"], x["gate"]["by"], grade.get(x["label"], ""), round(zipf(x["label"]), 2), "예" if in_terms(x["label"]) else ""]
                   + ["O" if not below(x["label"], lv) else "-" for lv in LEVELS] + [""])
res["dropped_examples"] = {lv: [x["label"] for x in sorted(show, key=lambda x: x["rank"]) if below(x["label"], lv)][:25] for lv in LEVELS}
res["kept_expert_examples"] = [x["label"] for x in sorted(show, key=lambda x: x["rank"]) if not below(x["label"], "실무자")][:25]
print(json.dumps(res, ensure_ascii=False, indent=1))
