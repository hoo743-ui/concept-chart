# 이 Mac의 Claude Code 대화 기록(~/.claude/projects/*/*.jsonl) → 훅이 남겼을 형식(inbox v1)으로 임시 인박스 만들기.
# 훅은 질문(UserPromptSubmit)과 차례마다 마지막 답변(Stop의 last_assistant_message)을 남긴다 → 같은 규칙으로 고른다.
# 키·토큰 가리기는 훅 코드(mask)를 그대로 쓴다. 결과는 임시 폴더에만.
import glob, json, os, re, sys
KEY = re.compile(r"(sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,})")
mask = lambda t: KEY.sub("[가림]", t)

out = open(sys.argv[1], "w", encoding="utf-8")
n_q = n_a = 0
for f in sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))):
    last, sess, cwd = None, None, None
    def flush(ts):
        global n_a
        if last:
            out.write(json.dumps({"v": 1, "source": "claude-code", "session_id": sess, "project": cwd, "ts": ts, "role": "assistant",
                                  "text": mask(last)[:20000], "truncated": len(last) > 20000}, ensure_ascii=False) + "\n")
            n_a += 1
    for line in open(f, encoding="utf-8", errors="ignore"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        sess, cwd, ts = r.get("sessionId", sess), r.get("cwd", cwd), r.get("timestamp")
        m = r.get("message") or {}
        if r.get("type") == "user" and isinstance(m.get("content"), str) and not r.get("isMeta"):
            flush(ts); last = None
            out.write(json.dumps({"v": 1, "source": "claude-code", "session_id": sess, "project": cwd, "ts": ts, "role": "user",
                                  "text": mask(m["content"])[:20000], "truncated": False}, ensure_ascii=False) + "\n")
            n_q += 1
        elif r.get("type") == "assistant" and isinstance(m.get("content"), list):
            t = "\n".join(x.get("text", "") for x in m["content"] if isinstance(x, dict) and x.get("type") == "text").strip()
            if t:
                last = t
    flush(ts)
print("질문", n_q, "답변", n_a)
