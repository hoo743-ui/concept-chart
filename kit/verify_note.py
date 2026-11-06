# verify_note.py : 노트 검증 에이전트 (코드로 동작, LLM 판정은 선택)
# 노트를 문장(주장) 단위로 쪼개 각 문장이 출처 문장으로 뒷받침되는지 확인한다.
# 뒷받침이 안 되면 재생성 → 그래도 안 되면 근거 있는 문장만 남기고 → 그래도 부족하면 출처 문장 그대로(추출형) 쓴다.
import re
from kiwipiepy import Kiwi

kiwi = Kiwi()
CONTENT = ("NNG", "NNP", "NR", "SL", "SN", "SH", "XR", "VV", "VA")
NEG_TOK = {("없이", "MAG"), ("없", "VA"), ("않", "VX"), ("아니", "VCN"), ("못", "MAG"), ("안", "MAG")}
NUM = re.compile(r"\d+(?:\.\d+)?")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9\-]+")
HI, LO = 0.6, 0.35            # 뒷받침 점수 기준 (내용어 포함률)


def sentences(text):
    return [s.text.strip() for s in kiwi.split_into_sents(text or "") if len(s.text.strip()) > 4]


def content_words(s):
    return {t.form.lower() for t in kiwi.tokenize(s) if t.tag in CONTENT}


def neg_scope(s):
    """부정어(없이·않·아니·못·안)가 걸리는 내용어: 바로 앞 3개 토큰 (못·안은 바로 뒤 1개도)"""
    toks = kiwi.tokenize(s)
    scope = set()
    for i, t in enumerate(toks):
        if (t.form, t.tag) in NEG_TOK:
            win = toks[max(0, i - 3):i] + (toks[i + 1:i + 2] if t.form in ("못", "안") else [])
            scope |= {u.form.lower() for u in win if u.tag in CONTENT}
    return scope


def negation_flip(claim, ev, cw, ew):
    cs, es = neg_scope(claim), neg_scope(ev)
    a = (es & cw) - cs          # 출처는 부정, 노트는 긍정
    b = (cs & ew) - es          # 노트는 부정, 출처는 긍정
    return (es and len(a) >= min(2, len(es))) or (cs and len(b) >= min(2, len(cs)))


def index_sources(sources):
    """sources: [{"url":..., "text":...}] → 출처 문장 목록 [(번호, 문장, 내용어)]"""
    out = []
    for i, src in enumerate(sources, 1):
        for s in sentences(src.get("text", "")):
            out.append((i, s, content_words(s)))
    return out


def check_claim(claim, idx, all_src_text, judge=None):
    cw = content_words(claim)
    best, best_score = None, 0.0
    for n, s, sw in idx:
        sc = len(cw & sw) / max(1, len(cw))
        if sc > best_score:
            best, best_score = (n, s), sc
    reasons = []
    ev = best[1] if best else ""
    nums = [x for x in NUM.findall(claim) if x not in ev]
    if nums:
        reasons.append("출처에 없는 숫자: " + ", ".join(nums))
    latin = [x for x in LATIN.findall(claim) if x.lower() not in all_src_text]
    if latin:
        reasons.append("출처에 없는 용어: " + ", ".join(latin))
    neg_flip = best is not None and bool(negation_flip(claim, ev, cw, content_words(ev)))
    if neg_flip:
        reasons.append("부정 표현이 출처와 반대")
    if reasons and (nums or latin):
        verdict = "unsupported"
    elif best_score >= HI and not neg_flip:
        verdict = "supported"
    elif best_score < LO:
        verdict = "unsupported"
        reasons.append("뒷받침 문장 없음 (점수 %.2f)" % best_score)
    else:
        verdict = "uncertain"
        if not neg_flip:
            reasons.append("뒷받침이 약함 (점수 %.2f)" % best_score)
    if verdict == "uncertain" and judge is not None:     # 선택: 소형 NLI 모델이나 무료 LLM으로 판정
        j = judge(claim, ev)
        if j is not None:
            verdict = "supported" if j else "unsupported"
            reasons.append("판정기 결과 반영")
    return {"claim": claim, "verdict": verdict, "score": round(best_score, 2),
            "source": best[0] if best else None, "evidence": ev, "reasons": reasons}


def verify(note, sources, judge=None):
    idx = index_sources(sources)
    all_src = " ".join(s.get("text", "") for s in sources).lower()
    claims = [check_claim(c, idx, all_src, judge) for c in sentences(note)]
    ok = sum(c["verdict"] == "supported" for c in claims)
    return {"claims": claims, "faithfulness": round(ok / max(1, len(claims)), 2)}


def render(claims, sources):
    body = " ".join("%s [%d]" % (c["claim"], c["source"]) for c in claims)
    refs = ["[%d] %s" % (i, s.get("url", "")) for i, s in enumerate(sources, 1)]
    return body + "\n" + "\n".join(refs)


def run_agent(note, sources, generate=None, judge=None, max_rounds=2, min_faith=0.8):
    """generate(sources, feedback) -> 새 노트 (선택). 없으면 문장 삭제와 추출형 대체만 한다."""
    log = []
    for rnd in range(max_rounds + 1):
        rep = verify(note, sources, judge)
        bad = [c for c in rep["claims"] if c["verdict"] != "supported"]
        log.append({"round": rnd, "faithfulness": rep["faithfulness"], "flagged": [c["claim"] for c in bad]})
        if not bad and rep["claims"]:
            return {"mode": "verified", "note": render(rep["claims"], sources), "report": rep, "log": log}
        if generate is None or rnd == max_rounds:
            break
        note = generate(sources, [c["claim"] + " → " + "; ".join(c["reasons"]) for c in bad])
    kept = [c for c in rep["claims"] if c["verdict"] == "supported"]
    if kept and len(kept) / len(rep["claims"]) >= 0.5:
        return {"mode": "trimmed", "note": render(kept, sources), "report": rep, "log": log}
    first = index_sources(sources)[:2]                   # 추출형: 출처 문장을 그대로
    ext = [{"claim": s, "source": n} for n, s, _ in first]
    return {"mode": "extractive", "note": render(ext, sources), "report": rep, "log": log}


if __name__ == "__main__":
    src = [{"url": "https://ko.wikipedia.org/wiki/트랜스포머_(기계_학습)",
            "text": "트랜스포머는 순환 구조 없이 어텐션 메커니즘만으로 문장 속 단어들의 관계를 한 번에 계산하는 신경망 구조로, 2017년 논문에서 처음 제안되었다."},
           {"url": "https://example.org/attention",
            "text": "어텐션은 입력 문장의 각 단어가 다른 단어에 얼마나 주목해야 하는지를 가중치로 계산하는 메커니즘이다."}]
    note = ("트랜스포머는 어텐션 메커니즘만으로 문장 속 단어들의 관계를 계산하는 신경망 구조다. "
            "2017년 논문에서 처음 제안되었다. "
            "2019년 Google이 처음 공개했다. "
            "트랜스포머는 순환 구조를 핵심으로 사용한다.")
    out = run_agent(note, src)
    for c in out["report"]["claims"]:
        print(c["verdict"], c["score"], "|", c["claim"], "|", "; ".join(c["reasons"]))
    print("faithfulness", out["report"]["faithfulness"], "→ mode", out["mode"])
    print(out["note"])
