# -*- coding: utf-8 -*-
"""실험 D1: 영어 약어의 위키백과 안내 문서에서 LLM이 '고르기만' 하게 하기 (사용자 '계속적으로 성능 개선', 11-11).

    python experiments/2026-11-10-general-gate/disambig_pick.py

공부 목록에 있지만 정의가 없는 영어 낱말(BERT·CLI·DB·IDE …)은 대부분 영어 위키백과에서도 동음이의 안내 문서다.
안내 문서가 연결한 문서 제목(최대 25개)과 내 대화 문장 3개를 주고, LLM은 번호 하나(또는 0 = 없음)만 고른다. 글은 쓰지 않는다.
대화 문맥이 '개념·대화' 같은 흔한 말뿐이라 실패한 '함께 나온 개념 겹치기'(11-11) 대신 대화 문장 자체를 준다.
출력: 낱말 → 고른 제목 (대화 문장은 출력하지 않는다). 실제 DB는 읽기 전용, 위키백과는 개념 이름만 보낸다.
"""
import json
import pathlib
import re
import sqlite3
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kit"))
import concept_gate as g  # noqa: E402
import fetch_sources as fs  # noqa: E402
import llm  # noqa: E402
import study_api  # noqa: E402

DB = pathlib.Path.home() / ".claude" / "concept-chart.sqlite"
SCHEMA = {"type": "object", "properties": {"pick": {"type": "integer"}}, "required": ["pick"]}


def candidates(term, lang="en", limit=25):
    q = urllib.parse.urlencode({"action": "query", "prop": "pageprops|links", "pllimit": 500, "plnamespace": 0, "redirects": 1, "format": "json", "titles": term})
    for p in json.loads(fs._get(f"https://{lang}.wikipedia.org/w/api.php?{q}")).get("query", {}).get("pages", {}).values():
        if "disambiguation" in p.get("pageprops", {}):
            return [l["title"] for l in p.get("links", []) if not l["title"].startswith(("List of", "All pages"))][:limit]
    return None


def prompt(term, titles, chat):
    opts = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
    sents = "\n".join("- " + s[:200] for s in chat[:3])
    return f"""아래 [대화]에 나온 '{term}'이 가리키는 것을 [후보] 위키백과 문서 제목 중에서 고른다. 번호 하나만 고른다.
대화의 뜻과 맞는 후보가 없거나 확실하지 않으면 0을 고른다.
[대화]
{sents}
[후보]
{opts}
JSON으로만 답한다. pick은 정수."""


def main():
    g.load_lexicons()
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    client = llm.make("ollama:qwen3:4b")
    assert client.available(), "LLM 없음"
    for (cid,) in con.execute("SELECT DISTINCT concept FROM forms").fetchall():
        top = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()[0]
        if not g.ASCII_FORM.fullmatch(top) or not re.search(r"[A-Za-z]", top) or not study_api.gate_of(con, cid, top)["show"] or study_api.summary_line(con, cid)[1] != "none":
            continue
        n = con.execute("SELECT definition FROM notes WHERE concept=?", (cid,)).fetchone()
        if not n or n[0]:
            continue
        titles = candidates(top)
        if not titles:
            print(top, "| 안내 문서 아님")
            continue
        chat = [r[0] for r in con.execute("SELECT snippet FROM mentions WHERE concept=? ORDER BY ts DESC LIMIT 3", (cid,))]
        pick = client.json(prompt(top, titles, chat), SCHEMA, 20).get("pick", 0)
        print(top, "|", f"후보 {len(titles)}", "→", titles[pick - 1] if isinstance(pick, int) and 1 <= pick <= len(titles) else "고르지 않음", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
