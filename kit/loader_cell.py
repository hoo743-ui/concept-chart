# 파이프라인 노트북 첫 셀: 인박스 읽기 + 정제 (코드·경로·URL 제거, 코드에서는 라이브러리·에러 이름만)
import re, json, pathlib
from collections import defaultdict

INBOX = pathlib.Path("@@INBOX@@").expanduser()
FENCE  = re.compile(r"```[^\n]*\n(.*?)```", re.S)
INLINE = re.compile(r"`([^`\n]+)`")
URL    = re.compile(r"https?://\S+")
PATH   = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-]+){2,}")
IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))", re.M)
PKG    = r"[A-Za-z0-9_.\-\[\]=<>]+"
PIP    = re.compile(rf"pip3?\s+install\s+((?:{PKG}[ \t]*)+)")
ERR    = re.compile(r"\b([A-Z][A-Za-z]+(?:Error|Exception))\b")


def clean_turn(text):
    code = "\n".join(FENCE.findall(text))
    prose = FENCE.sub(" ", text)
    inline = INLINE.findall(prose)
    prose = URL.sub(" ", INLINE.sub(" ", prose))
    prose = PATH.sub(" ", prose)
    both = code + "\n" + "\n".join(inline) + "\n" + text
    libs = {(a or b).split(".")[0] for a, b in IMPORT.findall(code)}
    pips = {re.split(r"[=<>\[]", p)[0] for m in PIP.findall(both) for p in m.split() if not p.startswith("-")}
    return {"prose": re.sub(r"\s+", " ", prose).strip(),
            "code_terms": sorted(libs | pips), "errors": sorted(set(ERR.findall(both)))}


def load_inbox(path=INBOX):
    sessions = defaultdict(list)                     # session_id → 턴 목록 (시뮬레이터의 '세션' 단위)
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            r.update(clean_turn(r.get("text", "")))
            sessions[r.get("session_id")].append(r)
    return sessions


sessions = load_inbox()
print(len(sessions), "세션 /", sum(len(v) for v in sessions.values()), "턴")
