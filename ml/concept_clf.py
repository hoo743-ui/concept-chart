# -*- coding: utf-8 -*-
"""concept_clf.py : 개념 분류기 점수 (0.8.0, 실험 experiments/2026-11-13-expand, 사용자 결정 11-13 '0.97로 가자').

    python ml/concept_clf.py --model models/concept-clf  < 입력.jsonl  > 점수.jsonl

입력 한 줄: {"id", "form", "sents": [문장...], "rule", "lex", "llm": true|false|null, "wiki": true|false|null}
출력 한 줄: {"id", "score"}   (0~1, 개념일 확률)

백본(kit/)은 이 파일을 불러오지 않는다. 작업자(kit/study_worker.py)가 별도 프로세스로 실행하고 결과 줄만 읽는다.
학습 패키지(torch·transformers)는 requirements-ml.txt. 없으면 이 프로세스가 실패하고 관문은 예전 판정을 쓴다.
입력 글자 만들기(text_of)는 학습(experiments/2026-11-13-expand/train.py)과 같아야 한다: 학습 코드가 여기서 불러다 쓴다.
"""
import argparse
import json
import sys

LEX = {"special": "전문", "mixed": "전문+일상", "general": "일상", None: "없음"}
YES = {True: "예", False: "아니오", None: "모름"}
HAS = {True: "있음", False: "없음", None: "모름"}
MAX_LEN = 160


def signal_text(r):
    return f"규칙 {r['rule']} · 사전 {LEX[r['lex']]} · AI {YES[r['llm']]} · 위키 {HAS[r['wiki']]}"


def text_of(r, signals=True):
    s = " / ".join(x[:200] for x in r["sents"]) or "(문장 없음)"
    return (signal_text(r) + " | " if signals else "") + r["form"], s


def encode(tok, batch, signals, dev):
    t = [text_of(r, signals) for r in batch]
    e = tok([x[0] for x in t], [x[1] for x in t], truncation="only_second", max_length=MAX_LEN, padding=True, return_tensors="pt")
    e.pop("token_type_ids", None)        # klue/roberta는 type_vocab_size=1인데 BERT식 토크나이저가 둘째 문장에 1을 붙인다
    return e.to(dev)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--min-gpu-mb", type=int, default=1500, help="GPU 여유 메모리가 이보다 적으면 CPU로")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    import pathlib

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    torch.set_num_threads(a.threads)
    cfg = json.loads((pathlib.Path(a.model) / "concept_clf.json").read_text(encoding="utf-8"))
    dev = "cpu"
    if torch.cuda.is_available():
        free, _total = torch.cuda.mem_get_info()
        dev = "cuda" if free / 2**20 >= a.min_gpu_mb else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(a.model).to(dev).eval()
    rows = [json.loads(line) for line in sys.stdin if line.strip()]
    with torch.no_grad():
        for i in range(0, len(rows), 16):
            b = rows[i:i + 16]
            with torch.autocast(dev, dtype=torch.float16, enabled=dev == "cuda"):
                logits = model(**encode(tok, b, bool(cfg.get("signals", 1)), dev)).logits
            for r, p in zip(b, torch.softmax(logits.float(), -1)[:, 1].tolist()):
                print(json.dumps({"id": r["id"], "score": round(p, 5)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
