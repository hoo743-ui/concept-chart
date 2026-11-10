# -*- coding: utf-8 -*-
"""분야별 질문에 로컬 LLM이 답한 글을 만든다 (비용 없음). 결과는 data/eval/general/ (git 제외).

    python experiments/2026-11-10-general-gate/make_answers.py
    python experiments/2026-11-10-general-gate/make_answers.py --set=fresh    # 새 분야 세트: questions_fresh.json → data/eval/fresh/

answers.jsonl: 질문·답변 / inbox.jsonl: 서버 색인용 인박스 (분야마다 세션 하나).
이미 만든 질문은 건너뛴다. 메모리가 모자라면 기다린다.
"""
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import llm  # noqa: E402
import study_worker as w  # noqa: E402

SET = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--set=")), "general")
OUT = ROOT / "data" / "eval" / SET
QUESTIONS = HERE / ("questions.json" if SET == "general" else f"questions_{SET}.json")
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
PROMPT = """너는 친절한 AI 도우미다. 아래 질문에 한국어로 답한다. 마크다운으로 제목, 목록, 굵은 글씨를 써서 600~900자로 설명한다.
질문: {q}
JSON으로만 답한다. answer: 답변 전체."""


def main():
    qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "answers.jsonl"
    done = {json.loads(l)["q"] for l in path.read_text(encoding="utf-8").splitlines()} if path.exists() else set()
    client = llm.make("ollama:qwen3:4b")
    assert client.available(), "LLM 없음"
    for split in [k for k in qs if not k.startswith("_")]:
        for field, items in qs[split].items():
            for q in items:
                if q in done:
                    continue
                w.wait_for_room(model_loaded=bool(done))   # 모델이 이미 올라와 있으면 GPU 여유를 다시 요구하지 않는다 (내렸다 올리기를 반복하지 않게)
                done.add(q)
                t0 = time.time()
                a = None
                for limit in (1400, 2200):                   # 길어서 잘리면 JSON이 깨진다: 한 번만 더 길게
                    try:
                        a = client.json(PROMPT.format(q=q), SCHEMA, limit)["answer"].strip()
                        break
                    except llm.LLMError as e:
                        print("다시 시도", field, q, e, flush=True)
                if not a:
                    print("건너뜀", field, q, flush=True)
                    continue
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"split": split, "field": field, "q": q, "a": a}, ensure_ascii=False) + "\n")
                print(split, field, len(a), f"{time.time() - t0:.0f}초", flush=True)
                time.sleep(2)
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    with (OUT / "inbox.jsonl").open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            ts = f"2026-11-10T{(i // 60):02d}:{i % 60:02d}:00+09:00"
            for role, text in (("user", r["q"]), ("assistant", r["a"])):
                f.write(json.dumps({"v": 1, "role": role, "session_id": r["field"], "ts": ts, "text": text}, ensure_ascii=False) + "\n")
    print("답변", len(rows), "→", OUT / "inbox.jsonl")


if __name__ == "__main__":
    main()
