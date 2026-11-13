"""브라우저 확장 실험 결과 세기 (11-13). 인박스를 읽기만 하고 숫자만 출력한다 (대화 글은 출력하지 않음).

실행: python experiments/2026-11-13-web-extension/check.py [--since 2026-11-13T09:00]
"""
import argparse
import json
import pathlib
from collections import Counter

ap = argparse.ArgumentParser()
ap.add_argument("--inbox", default=str(pathlib.Path.home() / ".claude" / "concept-inbox.jsonl"))
ap.add_argument("--since", default="", help="이 시각(UTC, ISO) 뒤의 기록만")
a = ap.parse_args()

rows = []
with open(a.inbox, encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("source") == "claude-web" and str(r.get("ts", "")) >= a.since:
            rows.append(r)
ans = [r for r in rows if r.get("role") == "assistant"]
qs = [r for r in rows if r.get("role") == "user"]
texts = Counter(r["text"] for r in ans)
sessions = {r.get("session_id") for r in ans}
with_q = sum(1 for r in ans if any(q.get("session_id") == r.get("session_id") and q["ts"] <= r["ts"] for q in qs))
print(json.dumps({
    "답변": len(ans), "질문": len(qs), "대화(세션)": len(sessions),
    "같은 글 두 번": sum(n - 1 for n in texts.values() if n > 1),
    "앞 질문이 있는 답변": with_q,
    "짧은 답변(20자 미만, 잘못 잡았을 수 있음)": sum(1 for r in ans if len(r["text"]) < 20),
    "답변 길이 중앙값": sorted(len(r["text"]) for r in ans)[len(ans) // 2] if ans else 0,
}, ensure_ascii=False, indent=1))
