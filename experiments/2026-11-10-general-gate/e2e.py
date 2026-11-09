# -*- coding: utf-8 -*-
"""자문자답 전체 흐름 점검: 질문·답변 → 실제 서버(별도 DB·포트) → 개념 판정 → 출처 → 쉬운 설명 → 요약 → 검증 시트.

    python experiments/2026-11-10-general-gate/e2e.py                 # self_qa.json (Claude가 쓴 답변)
    python experiments/2026-11-10-general-gate/e2e.py --source=qwen   # make_answers.py가 만든 답변 중 조정용 분야

사용자 DB(~/.claude/concept-chart.sqlite)는 건드리지 않는다. 결과:
    data/eval/general/e2e_<source>.sqlite   서버 DB
    experiments/2026-11-10-general-gate/review_<source>.csv / .html   검증 시트 (사용자가 맞음·틀림을 표시)
컴퓨터 부담: 서버 작업자는 한 번에 하나, 낮은 우선순위, 메모리가 모자라면 기다린다. 이 스크립트는 30초마다 상태만 묻는다.
"""
import csv
import html
import json
import pathlib
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "kit"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import concept_gate as g  # noqa: E402

D = ROOT / "data" / "eval" / "general"
PORT = 8766
BASE = f"http://localhost:{PORT}"
CAP = 3 * 3600                 # 아무리 길어도 3시간이면 끝낸다


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def load_items(source):
    if source == "self":
        return json.loads((HERE / "self_qa.json").read_text(encoding="utf-8"))["items"]
    rows = [json.loads(l) for l in (D / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    return [{"field": r["field"], "q": r["q"], "a": r["a"]} for r in rows if r["split"] == "tune"]


def reason(rule, llm):
    return {("accept", None): "규칙: 기술 이름·약어 형태라 바로 보여 줌",
            ("reject", None): "규칙: 너무 짧음·숫자·일반어라 숨김"}.get((rule, None)) if rule in ("accept", "reject") else \
        {("likely", True): "사전에 있음 + LLM이 공부할 개념으로 판정", ("likely", False): "사전에 있지만 LLM이 일반어로 판정해 숨김",
         ("likely", None): "사전에 있음, LLM 판정 전 (후보)", ("unknown", True): "사전에 없음, LLM만 인정 → 후보로 숨김",
         ("unknown", False): "사전에 없고 LLM도 일반어로 판정해 숨김", ("unknown", None): "사전에 없음, LLM 판정 전 → 숨김"}[(rule, llm)]


def main():
    source = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--source=")), "self")
    items = load_items(source)
    inbox, db = D / f"e2e_{source}.jsonl", D / f"e2e_{source}.sqlite"
    with inbox.open("w", encoding="utf-8") as f:
        for i, x in enumerate(items):
            ts = f"2026-11-10T12:{i // 60:02d}:{i % 60:02d}+09:00"
            for role, text in (("user", x["q"]), ("assistant", x["a"])):
                f.write(json.dumps({"v": 1, "role": role, "session_id": f"{source}-{x['field']}", "ts": ts, "text": text}, ensure_ascii=False) + "\n")
    log = (D / f"e2e_{source}_server.txt").open("w", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, str(ROOT / "kit" / "serve.py"), "--inbox", str(inbox), "--db", str(db), "--port", str(PORT),
                            "--llm", "ollama:qwen3:4b", "--searx", "off", "--rebuild"], stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    try:
        while True:                                          # 색인이 끝날 때까지
            time.sleep(5)
            try:
                if len(get("/api/answers?k=500")["items"]) >= len(items):
                    break
            except OSError:
                pass
            if time.time() - t0 > 300:
                raise SystemExit("색인이 5분 안에 끝나지 않았습니다. 로그: " + str(log.name))
        answers = get("/api/answers?k=500")["items"]
        for a in answers:                                    # 화면에서 '요약' 버튼을 누른 것과 같다
            post(f"/api/answers/{urllib.parse.quote(a['id'])}/summary", {})
        quiet = 0
        while time.time() - t0 < CAP:                        # 모델 작업·정의 수집이 다 끝날 때까지
            shown = [x for x in get("/api/study/concepts?view=show&k=2000")["items"]]
            pending = 0
            for x in shown:                                  # 화면에서 개념을 연 것과 같다 (정의 수집·노트 예약)
                d = get(f"/api/study/concept/{urllib.parse.quote(x['id'])}")
                pending += d.get("note_status") == "pending" or d["note"]["status"] == "none"
            h = get("/api/health")
            queued = h["jobs"].get("queued", 0)
            print(f"{int(time.time() - t0)}초 · 보여 줄 개념 {len(shown)} · 준비 중 {pending} · 모델 작업 대기 {queued}", flush=True)
            quiet = quiet + 1 if not queued and not pending else 0
            if quiet >= 2:
                break
            time.sleep(30)
        export(source, items, db)
    finally:
        srv.terminate()
        try:
            srv.wait(20)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()
    print("걸린 시간", int(time.time() - t0), "초")


def export(source, items, db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    answers = {a["id"]: get(f"/api/answers/{urllib.parse.quote(a['id'])}") for a in get("/api/answers?k=500")["items"]}
    by_q = {a["question"]: a for a in answers.values()}
    rows, blocks = [], []
    for i, x in enumerate(items, 1):
        a = by_q.get(x["q"])
        if not a:
            continue
        pts = a["summary"].get("points") or []
        words = []
        for (cid,) in con.execute("SELECT DISTINCT concept FROM mentions WHERE session=? AND ts=?", (a["session"], a["ts"])):
            form = con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC, form LIMIT 1", (cid,)).fetchone()[0]
            j = con.execute("SELECT llm, user FROM judgments WHERE concept=?", (cid,)).fetchone()
            llm_v = None if not j or j[0] is None else bool(j[0])
            rule = g.rule_verdict(form)
            verdict = g.final(rule, llm_v)
            d = get(f"/api/study/concept/{urllib.parse.quote(cid)}") if verdict == "show" else None
            note = (d or {}).get("note", {})
            src = ((d or {}).get("sources") or [{}])[0]
            words.append({"answer": i, "field": x["field"], "word": form, "verdict": {"show": "보여 줌", "candidate": "후보(숨김)", "hide": "숨김"}[verdict],
                          "why": reason(rule, llm_v), "note_status": note.get("status", ""), "easy": note.get("easy") or "",
                          "evidence": ((note.get("easy_evidence") or [None])[0] or (d or {}).get("definition") or "")[:300], "source": src.get("url", ""),
                          "check": ""})
        words.sort(key=lambda w: ({"보여 줌": 0, "후보(숨김)": 1, "숨김": 2}[w["verdict"]], w["word"]))
        rows += words
        blocks.append((i, x, a, pts, words))
    out = HERE / f"review_{source}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:          # 엑셀에서 한글이 깨지지 않게 BOM
        wr = csv.DictWriter(f, fieldnames=["answer", "field", "word", "verdict", "why", "note_status", "easy", "evidence", "source", "check"])
        wr.writeheader()
        wr.writerows(rows)
    write_html(source, blocks)
    print("검증 시트", out, len(rows), "줄")


NOTE_KO = {"ready": "쉬운 설명 통과", "rejected": "쉬운 설명 탈락 → 출처 문장 표시", "wrong_sense": "출처가 다른 뜻 → 숨김", "no_evidence": "출처 없음", "none": "준비 안 됨", "": ""}


def write_html(source, blocks):
    e = html.escape
    parts = []
    for i, x, a, pts, words in blocks:
        shown = [w for w in words if w["verdict"] == "보여 줌"]
        rest = [w for w in words if w["verdict"] != "보여 줌"]
        summ = "".join(f"<li>{e(p['text'])}</li>" for p in pts) or f"<li class=muted>요약 상태: {e(a['summary'].get('status', ''))}</li>"
        trs = "".join(f"<tr><td><b>{e(w['word'])}</b></td><td>{e(w['why'])}</td><td>{e(NOTE_KO.get(w['note_status'], w['note_status']))}</td>"
                      f"<td>{e(w['easy']) or '<span class=muted>(없음)</span>'}</td><td class=ev>{e(w['evidence'])}</td>"
                      f"<td>{'<a href=\"' + e(w['source']) + '\" target=_blank>출처</a>' if w['source'] else ''}</td>"
                      f"<td class=chk><label><input type=radio name=s{i}{e(w['word'])}>맞음</label> <label><input type=radio name=s{i}{e(w['word'])}>틀림</label></td></tr>" for w in shown)
        hidden = ", ".join(f"<span title=\"{e(w['why'])}\" class=\"{'cand' if w['verdict'] == '후보(숨김)' else ''}\">{e(w['word'])}</span>" for w in rest)
        parts.append(f"""<section><h2>{i}. [{e(x['field'])}] {e(x['q'])}</h2>
<details><summary>AI 답변 원문</summary><pre>{e(x['a'])}</pre></details>
<h3>요약 (LLM이 고른 원문 문장)</h3><ul>{summ}</ul>
<h3>공부할 개념으로 보여 준 것 {len(shown)}개</h3>
<div class=scroll><table><tr><th>개념</th><th>왜 보여 줬나</th><th>설명 상태</th><th>쉬운 설명 (모델)</th><th>근거 문장 (출처 그대로)</th><th>링크</th><th>검증</th></tr>{trs or '<tr><td colspan=7 class=muted>없음</td></tr>'}</table></div>
<p><b>숨긴 낱말 {len(rest)}개</b> <span class=muted>(밑줄 = 후보. 낱말에 마우스를 올리면 숨긴 이유)</span><br>{hidden}</p></section>""")
    page = f"""<!doctype html><html lang=ko><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>자문자답 검증 시트</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--card:#fff;--line:#e7e5e4}}@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--card:#292524;--line:#44403c}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 system-ui,"Malgun Gothic",sans-serif}}main{{max-width:1200px;margin:auto;padding:20px 16px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0}}h2{{font-size:16px;margin:0 0 8px}}h3{{font-size:14px;margin:12px 0 4px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}}.ev{{color:var(--mut);max-width:340px}}
.muted{{color:var(--mut)}}.cand{{text-decoration:underline}}pre{{white-space:pre-wrap;font-size:12.5px}}.scroll{{overflow-x:auto}}.chk{{white-space:nowrap}}
</style></head><body><main><h1>자문자답 검증 시트 ({'Claude가 쓴 답변' if source == 'self' else '로컬 LLM이 쓴 답변'})</h1>
<p class=muted>사용자처럼 묻고 받은 AI 답변을 실제 앱 코드로 처리한 결과입니다. 모델이 내린 결론마다 이유와 출처를 붙였습니다. 표의 검증 칸은 화면에서만 표시되고 저장되지 않습니다. 기록하려면 같은 폴더의 review_{source}.csv의 check 칸에 O/X를 적어 주세요.</p>
{''.join(parts)}</main></body></html>"""
    (HERE / f"review_{source}.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
