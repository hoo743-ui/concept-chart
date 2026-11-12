# -*- coding: utf-8 -*-
"""실험 (11-13, 채택 안 함 — 측정만): 출처 설명의 틀린 뜻을 '도착한 위키백과 문서 제목'으로 가를 수 있는가.

배경 (0.7.14 sense_audit.py): LLM 뜻 확인은 제목으로 본 틀린 뜻 18개 중 5개만 잡고 맞는 설명을 많이 걸었다.
틀린 뜻은 대부분 위키백과가 낱말과 다른 제목으로 넘겨준 경우다 (중복 → 복날, export → 수출, stream → 하천).

규칙 후보 (LLM 없음, 코드만) — 출처가 위키백과이고
  1) 도착 문서 제목(괄호 앞)이 낱말과 다르고, 제목 괄호가 기술 분야가 아니며(fetch_sources.TECH_PAREN)
  2) 그 제목이 분야 사전(우리말샘)에 있는데 정보·통신 분야 뜻이 없으면 → '다른 뜻일 수 있음'
  변형 A: 기술 개념(fields.field_of == TECH)일 때만
  변형 B: 모든 개념
  변형 C: B + 제목의 분야가 함께 나온 개념들의 분야와 맞으면 받는다 (화학 대화의 카복실산·질소)

정답: Claude가 문서 제목만 보고 표시했다 (대화 문맥은 보지 않음, 사용자 검토 전). WRONG·OK에 없는 낱말은 '애매'로 따로 센다.

    python experiments/2026-11-10-general-gate/sense_title.py      (실제 DB 읽기 전용, 네트워크 없음)
"""
import json
import pathlib
import re
import sqlite3
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "kit"))
import fetch_sources as fs  # noqa: E402
import fields  # noqa: E402
import study_api  # noqa: E402
import study_worker as w  # noqa: E402

DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
LEX = ROOT / "kit" / "data" / "lexicon" / "lexicon.sqlite"

# 제목으로 본 틀린 뜻 (Claude 표시, 11-13). 대화 맥락: 개발·디자인 대화
WRONG = {"Assets", "Button", "Chromium", "Cloud", "Codex", "Dark", "Electron", "Export", "hero", "import", "marketplace",
         "Noto", "public", "seed", "Settings", "stream", "temperature", "torch", "transformers", "visibility", "weight",
         "window", "임계값", "임시", "접근", "정적", "중복", "사전학습", "Apache", "Structured", "Tailwind", "지연",
         "epoch", "RTX"}
# 제목으로 본 맞는 뜻
OK = {"Accuracy", "Acronis", "AI", "Anthropic", "Authenticate", "Bash", "ChatGPT", "Claude", "COOH", "CPU", "Cryptography",
      "computing", "ConceptNet", "Ctrl", "Dashboard", "directory", "Discord", "Docker", "Dropbox", "Error", "FAQs", "Figma",
      "figma.com", "Function", "Gemini", "git", "GitHub", "Google", "GPU", "interface", "iPhone", "Jupyter", "Kubernetes",
      "Linux", "LLM", "LSTM", "Markdown", "message", "NaOH", "Nitrogen", "octet", "OneDrive", "OpenAI", "plugin",
      "PowerShell", "Pretendard", "PyPI", "Python", "RAM", "React", "README", "Redis", "Rhizobium", "SaaS", "security",
      "server", "SGLT", "Ubuntu", "UTF", "VPN", "WCAG", "WebView", "Whorf", "Wikidata", "Windows", "woff", "그래픽스",
      "대기열", "데이터셋", "데카르트", "런타임", "미세조정", "시뮬레이터", "잠금", "재현율", "정규식", "정확도", "추론",
      "트랜잭션", "할루시네이션"}


def norm(s):
    return re.sub(r"[\s\-_/·.]+", "", s.lower())


def wiki_title(url):
    if "wikipedia" not in urllib.parse.urlparse(url).netloc:
        return None
    return urllib.parse.unquote(url.rsplit("/", 1)[-1]).replace("_", " ")


def base_of(title):
    return re.sub(r"\s*\(.*\)\s*$", "", title)


def suspicious(lex, label, title):
    if fs.TECH_PAREN.search(title) or norm(base_of(title)) == norm(label):
        return False
    key = base_of(title).replace(" ", "")
    if not lex.execute("SELECT 1 FROM lex WHERE key=?", (key,)).fetchone():
        return False                                      # 사전에 없는 이름(앤트로픽·깃허브)은 판단하지 않는다
    f = lex.execute("SELECT fields FROM field WHERE key=?", (key,)).fetchone()
    return fields.TECH not in (f[0].split(";") if f and f[0] else [])


def report(name, rows, hit_of):
    hit = [(r["label"], r["title"]) for r in rows if hit_of(r)]
    hl = {l for l, _ in hit}
    wrong_seen = {r["label"] for r in rows} & WRONG
    print(f"\n[{name}] 걸린 것 {len(hit)}개 / 위키백과 출처 {len(rows)}개")
    print(f"  틀린 뜻 {len(wrong_seen)}개 중 잡음 {len(hl & WRONG)}개 · 놓침:", ", ".join(sorted(wrong_seen - hl)))
    print(f"  맞는 뜻을 건 것 {len(hl & OK)}개:", ", ".join(sorted(hl & OK)))
    print(f"  애매(정답 표시 없음) {len(hl - WRONG - OK)}개:", ", ".join(sorted(hl - WRONG - OK)))


def main():
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    lex = sqlite3.connect(f"file:{LEX.as_posix()}?mode=ro", uri=True)
    rows = []
    for (cid,) in con.execute("SELECT DISTINCT concept FROM forms").fetchall():
        top = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()
        label = top[0] if top else cid
        if not study_api.gate_of(con, cid, label)["show"] or not w.source_of(con, cid):
            continue
        src = json.loads(con.execute("SELECT sources FROM notes WHERE concept=?", (cid,)).fetchone()[0] or "[]")
        title = wiki_title(src[0].get("url", "")) if src else None
        if not title:
            continue
        sus = suspicious(lex, label, title)
        rows.append({"label": label, "title": title, "sus": sus,
                     "tech": fields.field_of(con, cid, label) == fields.TECH,
                     "ctx": sus and fields.field_of(con, cid, base_of(title)) is not None})
    report("A: 기술 개념만", rows, lambda r: r["sus"] and r["tech"])
    report("B: 모든 개념", rows, lambda r: r["sus"])
    report("C: B + 제목 분야가 대화 분야와 맞으면 받기", rows, lambda r: r["sus"] and not r["ctx"])
    print("\nC에서 받은 것:", ", ".join(f'{r["label"]}→{r["title"]}' for r in rows if r["ctx"]))


if __name__ == "__main__":
    main()
