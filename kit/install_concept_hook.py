#!/usr/bin/env python3
# install_concept_hook.py : 개념 차트 입력 설치기 (Claude Code 훅 → 로컬 인박스 JSONL)
# 사용법 (옵션은 모두 생략 가능)
#   python install_concept_hook.py                  설치: 모든 프로젝트, 내 질문 + AI 최종 답변 수집
#   python install_concept_hook.py --test           설치된 훅 자체 점검
#   python install_concept_hook.py --uninstall      이 훅만 제거 (다른 설정은 그대로)
#   --scope project --project C:/work/app           특정 프로젝트에만 설치
#   --events user,assistant,subagent                수집할 내용
#   --inbox ~/.claude/concept-inbox.jsonl           인박스 파일 위치
#   --timeout 10  --sync  --no-mask  --max-chars 20000
import argparse, datetime, json, os, pathlib, re, shutil, subprocess, sys, tempfile

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

MARK = "concept_hook.py"
EVENT_NAMES = {"user": "UserPromptSubmit", "assistant": "Stop", "subagent": "SubagentStop"}
MIN_CLAUDE = (2, 1, 47)   # Stop 훅의 last_assistant_message 필드가 들어온 버전

HOOK_TEMPLATE = r'''# concept_hook.py : Claude Code 훅 → 내 질문과 AI 최종 답변을 개념 차트 인박스(JSONL)에 한 줄씩 저장
# install_concept_hook.py가 생성. 아무것도 출력하지 않고 항상 0으로 끝난다.
import sys, os, re, json, time, datetime, pathlib

INBOX = pathlib.Path(os.environ.get("CONCEPT_INBOX") or "@@INBOX@@").expanduser()
MASK = @@MASK@@
MAX_CHARS = @@MAXCHARS@@
ROLE = {"UserPromptSubmit": ("user", "prompt"),
        "Stop": ("assistant", "last_assistant_message"),
        "SubagentStop": ("subagent", "last_assistant_message")}
SECRETS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[MASKED]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[MASKED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[MASKED]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "[MASKED]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{20,}"), r"\1[MASKED]"),
    (re.compile(r"(?i)((?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?)[^\s'\"]{8,}"), r"\1[MASKED]"),
]

def mask(text):
    if MASK:
        for rx, rep in SECRETS:
            text = rx.sub(rep, text)
    return text

def keep_raw(x):
    """형식이 예상과 다를 때 원문을 남긴다 (문자열은 가리고 자른다)"""
    if isinstance(x, dict):
        return {str(k): keep_raw(v) for k, v in x.items()}
    if isinstance(x, list):
        return [keep_raw(v) for v in x[:50]]
    if isinstance(x, str):
        return mask(x)[:MAX_CHARS]
    return x

def normalize(data, ts):
    """[어댑터] Claude Code 훅 입력 → inbox v1 레코드. 등록하지 않은 이벤트면 None.
    기대한 글 필드가 없거나 비어 있으면(구버전·형식 변경) text는 비우고 원문을 raw에 담는다."""
    if not isinstance(data, dict):
        return {"v": 1, "source": "claude-code", "ts": ts, "role": "unknown", "text": "", "truncated": False,
                "raw": keep_raw(data)}
    ev = data.get("hook_event_name")
    if ev not in ROLE:
        return None
    role, key = ROLE[ev]
    rec = {"v": 1, "source": "claude-code", "session_id": data.get("session_id"), "project": data.get("cwd"),
           "ts": ts, "role": role}
    text = data.get(key)
    if isinstance(text, str) and text.strip():
        text = mask(text)
        rec.update(text=text[:MAX_CHARS], truncated=len(text) > MAX_CHARS)
    else:
        rec.update(text="", truncated=False, raw=keep_raw(data))
    if data.get("agent_type"):
        rec["agent_type"] = data.get("agent_type")
    return rec

LOCK_AT = 1 << 40    # 파일 끝 훨씬 뒤의 1바이트만 잠근다: 인박스를 읽는 서버는 막지 않는다

def lock(f, unlock=False):
    if os.name == "nt":
        import msvcrt
        f.seek(LOCK_AT)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.lockf(f, fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB, 1, LOCK_AT, 0)

def append_line(data):
    """여러 세션이 동시에 끝나도 줄이 사라지지 않게 잠그고 쓴다. 3초 안에 못 잠그면 그냥 쓴다 (기록을 버리지 않는다)"""
    with INBOX.open("ab", buffering=0) as f:
        locked = False
        for _ in range(150):
            try:
                lock(f)
                locked = True
                break
            except OSError:
                time.sleep(0.02)
        f.seek(0, 2)
        f.write(data)
        if locked:
            lock(f, unlock=True)

def main():
    body = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        data = json.loads(body or "{}")
    except ValueError:
        data = ["unparsed", body]
    rec = normalize(data, ts)
    if rec is None:
        return
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    append_line((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
'''


def parse_args():
    p = argparse.ArgumentParser(description="개념 차트 입력 설치기 (Claude Code 훅)")
    p.add_argument("--scope", choices=["global", "project"], default="global")
    p.add_argument("--project", default="", help="--scope project일 때 프로젝트 폴더")
    p.add_argument("--events", default="user,assistant", help="user,assistant,subagent 중 선택")
    p.add_argument("--inbox", default="~/.claude/concept-inbox.jsonl")
    p.add_argument("--timeout", type=int, default=10)
    p.add_argument("--sync", action="store_true", help="동기 실행 (기본은 비동기)")
    p.add_argument("--no-mask", action="store_true", help="API 키·토큰 가리기 끄기")
    p.add_argument("--max-chars", type=int, default=20000)
    act = p.add_mutually_exclusive_group()
    act.add_argument("--test", action="store_true", help="설치된 훅 점검")
    act.add_argument("--uninstall", action="store_true", help="이 훅 제거")
    return p.parse_args()


def clean_path(s):
    return str(s or "").strip().replace("\\", "/").replace('"', "").replace("'", "").rstrip("/")


def home_claude():
    return pathlib.Path.home() / ".claude"


def hook_file():
    return home_claude() / "hooks" / MARK


def settings_file(a):
    if a.scope == "project":
        if not a.project:
            sys.exit("--scope project에는 --project 폴더가 필요합니다.")
        return pathlib.Path(clean_path(a.project)).expanduser() / ".claude" / "settings.json"
    return home_claude() / "settings.json"


def python_exe():
    exe = pathlib.Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":        # 창 없는 실행 파일은 stdin을 읽지 못함
        alt = exe.with_name("python.exe")
        if alt.exists():
            exe = alt
    return exe.as_posix()


def hook_command():
    # Windows에서 훅은 Git Bash로 실행될 수 있어 역슬래시가 지워진다 → 슬래시 + 따옴표 절대경로
    return '"%s" "%s"' % (python_exe(), hook_file().as_posix())


def read_settings(p):
    if not p.exists():
        return {}
    txt = p.read_text(encoding="utf-8-sig").strip()    # BOM이 있어도 읽음
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except json.JSONDecodeError as e:
        sys.exit("settings.json을 읽지 못했습니다 (JSON 형식 오류: %s). 파일을 고친 뒤 다시 실행하세요: %s" % (e, p))


def write_settings(p, cfg):
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bak = p.with_name(p.name + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(p, bak)
        print("기존 설정 백업:", bak)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")   # BOM 없이 저장


def remove_ours(cfg):
    hooks = cfg.get("hooks") or {}
    for ev in list(hooks):
        kept = []
        for group in hooks[ev] or []:
            hs = [h for h in (group.get("hooks") or []) if MARK not in str(h.get("command", ""))]
            if hs:
                g = dict(group)
                g["hooks"] = hs
                kept.append(g)
        if kept:
            hooks[ev] = kept
        else:
            del hooks[ev]
    if "hooks" in cfg and not cfg["hooks"]:
        del cfg["hooks"]
    return cfg


def check_claude_version():
    exe = shutil.which("claude")
    if not exe:
        print("참고: claude 명령을 찾지 못했습니다. 'claude --version'이 2.1.47 이상인지 직접 확인하세요.")
        return
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15).stdout
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
        if m and tuple(int(x) for x in m.groups()) < MIN_CLAUDE:
            print("경고: Claude Code %s 입니다. 2.1.47 이상이어야 AI 답변이 기록됩니다." % m.group(0))
        elif m:
            print("Claude Code 버전:", m.group(0), "(확인)")
    except Exception:
        pass


def render_hook(inbox, mask=True, max_chars=20000):
    """설치될 훅 파일 내용 (테스트도 이 함수로 같은 훅을 만든다)"""
    return (HOOK_TEMPLATE.replace("@@INBOX@@", inbox)
            .replace("@@MASK@@", "True" if mask else "False")
            .replace("@@MAXCHARS@@", str(max(1000, max_chars))))


def install(a):
    events =[EVENT_NAMES[e.strip()] for e in a.events.split(",") if e.strip() in EVENT_NAMES]
    if not events:
        sys.exit("--events에 user, assistant, subagent 중 하나 이상을 넣으세요.")
    inbox = clean_path(a.inbox) or "~/.claude/concept-inbox.jsonl"
    code = render_hook(inbox, not a.no_mask, a.max_chars)
    hf = hook_file()
    hf.parent.mkdir(parents=True, exist_ok=True)
    hf.write_text(code, encoding="utf-8")
    sp = settings_file(a)
    cfg = remove_ours(read_settings(sp))
    hooks = cfg.setdefault("hooks", {})
    for ev in events:
        h = {"type": "command", "command": hook_command(), "timeout": max(1, min(60, a.timeout))}
        if not a.sync:
            h["async"] = True
        hooks.setdefault(ev, []).append({"hooks": [h]})
    write_settings(sp, cfg)
    print("훅 파일:", hf)
    print("설정 파일:", sp)
    print("등록한 이벤트:", ", ".join(events))
    print("Python:", python_exe())
    print("인박스:", inbox)
    check_claude_version()
    print("다음: 같은 명령에 --test를 붙여 점검 → Claude Code를 다시 열고 /hooks에서 확인")


def uninstall(a):
    sp = settings_file(a)
    if sp.exists():
        write_settings(sp, remove_ours(read_settings(sp)))
        print("설정에서 제거:", sp)
    if hook_file().exists():
        hook_file().unlink()
        print("훅 파일 삭제:", hook_file())
    print("인박스 파일은 지우지 않았습니다.")


def selftest(a):
    hf = hook_file()
    if not hf.exists():
        sys.exit("훅 파일이 없습니다. 먼저 설치하세요.")
    masking = "MASK = True" in hf.read_text(encoding="utf-8")
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    tmp = tmpdir / "inbox.jsonl"
    env = dict(os.environ, CONCEPT_INBOX=str(tmp))
    samples = [
        {"hook_event_name": "UserPromptSubmit", "session_id": "selftest", "cwd": "C:/demo",
         "prompt": "RAG랑 벡터DB 차이가 뭐야?"},
        {"hook_event_name": "Stop", "session_id": "selftest", "cwd": "C:/demo", "stop_hook_active": False,
         "last_assistant_message": "RAG는 검색한 문서를 근거로 답하는 방식이에요. 예시 키 sk-test1234567890abcdefghijklmn 는 가려져야 해요."},
    ]
    for s in samples:
        subprocess.run([python_exe(), str(hf)], input=json.dumps(s, ensure_ascii=False).encode("utf-8"),
                       env=env, timeout=30)
    lines = tmp.read_text(encoding="utf-8").splitlines() if tmp.exists() else []
    ok = len(lines) == 2 and "벡터DB" in lines[0] and (not masking or "[MASKED]" in lines[1])
    for ln in lines:
        print(ln)
    print("결과:", "정상" if ok else "실패 (Python 경로, 훅 파일, 인코딩을 확인하세요)")
    shutil.rmtree(tmpdir, ignore_errors=True)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    if args.uninstall:
        uninstall(args)
    elif args.test:
        selftest(args)
    else:
        install(args)
