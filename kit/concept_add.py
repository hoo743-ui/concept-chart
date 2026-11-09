# -*- coding: utf-8 -*-
"""concept_add.py : AI 답변을 인박스에 넣는 입구 (표준 라이브러리만). 처리부는 입구가 어디인지 모른다.

    어떤-CLI | python kit/concept_add.py text --source codex     # 표준 입력의 글을 AI 답변으로 추가
    python kit/concept_add.py text 답변.txt                       # 파일에서
    python kit/concept_add.py import conversations.json           # Claude 앱·ChatGPT 내보내기 파일

- 키·토큰을 가린 뒤 저장한다. 내용은 이 PC의 인박스에만 쓴다.
- 같은 답변을 두 번 넣지 않는다 (내용 해시를 ~/.claude/concept-added.txt에 기록).
- 내보내기 형식은 공개된 설명을 바탕으로 만든 fixture로만 시험했다. 실제 파일과 다르면 건너뛴 개수를 알려 준다.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MAX_CHARS = 20000
LOCK_AT = 1 << 40        # 훅과 같은 자리를 잠근다 (install_concept_hook.py)
SECRETS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[MASKED]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[MASKED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[MASKED]"),
    (re.compile(r"(?i)((?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?)[^\s'\"]{8,}"), r"\1[MASKED]"),
]


def inbox_path(inbox=None):
    return pathlib.Path(inbox or os.environ.get("CONCEPT_INBOX") or "~/.claude/concept-inbox.jsonl").expanduser()


def mask(text):
    for rx, rep in SECRETS:
        text = rx.sub(rep, text)
    return text


def _lock(f, unlock=False):
    if os.name == "nt":
        import msvcrt
        f.seek(LOCK_AT)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.lockf(f, fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB, 1, LOCK_AT, 0)


def append_line(data, inbox=None):
    p = inbox_path(inbox)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("ab", buffering=0) as f:
        locked = False
        for _ in range(60):
            try:
                _lock(f)
                locked = True
                break
            except OSError:
                time.sleep(0.05)
        f.seek(0, os.SEEK_END)
        f.write(data)
        if locked:
            _lock(f, True)


def add(text, source="paste", role="assistant", ts=None, session=None, project=None, inbox=None):
    """→ True면 추가, False면 이미 있는 글이거나 빈 글"""
    text = (text or "").strip()
    if not text:
        return False
    digest = hashlib.sha1(f"{role}|{text}".encode("utf-8")).hexdigest()
    sp = inbox_path(inbox).with_name("concept-added.txt")
    seen = set(sp.read_text(encoding="utf-8").split()) if sp.exists() else set()
    if digest in seen:
        return False
    ts = ts or datetime.now(timezone.utc).isoformat()
    masked = mask(text)
    rec = {"v": 1, "source": source, "ts": ts, "role": role, "text": masked[:MAX_CHARS], "truncated": len(masked) > MAX_CHARS, "session_id": session or f"{source}:{ts[:10]}"}
    if project:
        rec["project"] = project
    append_line((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"), inbox)
    with sp.open("a", encoding="utf-8", newline="\n") as f:
        f.write(digest + "\n")
    return True


def _iso(x):
    if isinstance(x, (int, float)):
        return datetime.fromtimestamp(x, timezone.utc).isoformat()
    return x if isinstance(x, str) and x else None


def claude_messages(conv):
    for m in conv.get("chat_messages", []) or []:
        role = {"human": "user", "assistant": "assistant"}.get(m.get("sender"))
        text = m.get("text") or "\n".join(c.get("text", "") for c in m.get("content", []) or [] if isinstance(c, dict) and c.get("type") == "text")
        if role and text:
            yield role, text, _iso(m.get("created_at"))


def chatgpt_messages(conv):
    nodes = [n.get("message") for n in (conv.get("mapping") or {}).values() if isinstance(n, dict) and n.get("message")]
    nodes.sort(key=lambda m: m.get("create_time") or 0)
    for m in nodes:
        role = (m.get("author") or {}).get("role")
        parts = (m.get("content") or {}).get("parts") or []
        text = "\n".join(p for p in parts if isinstance(p, str))
        if role in ("user", "assistant") and text.strip():
            yield role, text, _iso(m.get("create_time"))


def import_export(path):
    """Claude 앱·ChatGPT의 conversations.json → (추가 수, 이미 있던 수, 형식을 모르는 대화 수)"""
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("대화 목록(JSON 배열)이 아닙니다. 내보내기의 conversations.json을 지정하세요.")
    added = dup = unknown = 0
    for i, conv in enumerate(data):
        if not isinstance(conv, dict):
            unknown += 1
            continue
        if "chat_messages" in conv:
            source, msgs = "claude-app", claude_messages(conv)
        elif "mapping" in conv:
            source, msgs = "chatgpt", chatgpt_messages(conv)
        else:
            unknown += 1
            continue
        sess = f"{source}:{conv.get('uuid') or conv.get('id') or conv.get('conversation_id') or i}"
        for role, text, ts in msgs:
            if add(text, source, role, ts, sess):
                added += 1
            else:
                dup += 1
    return added, dup, unknown


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("text", help="글 하나를 AI 답변으로 추가 (파일 또는 표준 입력)")
    t.add_argument("file", nargs="?")
    t.add_argument("--source", default="paste")
    i = sub.add_parser("import", help="Claude 앱·ChatGPT 내보내기 파일 가져오기")
    i.add_argument("file")
    a = ap.parse_args()
    if a.cmd == "text":
        text = pathlib.Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read()
        print("추가했습니다" if add(text, a.source) else "추가할 글이 없거나 이미 있는 글입니다")
        return 0
    added, dup, unknown = import_export(a.file)
    print(f"추가 {added}개, 이미 있음 {dup}개, 형식을 몰라 건너뜀 {unknown}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
