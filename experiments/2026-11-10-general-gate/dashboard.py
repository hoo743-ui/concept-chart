# -*- coding: utf-8 -*-
"""rounds.json → dashboard.html (파일 하나, 외부 연결 없음). evaluate.py가 라운드마다 다시 만든다.

    python experiments/2026-11-10-general-gate/dashboard.py
디자인은 정하지 않았다: 숫자를 읽기 쉽게 놓는 것만 한다.
"""
import html
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SETS = [("일반 분야 tune", "조정용 분야 (경제·의학·법·역사·생물)"), ("일반 분야 both", "여러 분야에 걸친 낱말"),
        ("개발 대화 (전체 낱말)", "개발 대화 (기존 결과 유지 확인)"), ("일반 분야 holdout", "처음 보는 분야 (마지막에 한 번)")]
COLORS = {"precision": "var(--p)", "recall": "var(--r)"}


def esc(x):
    return html.escape(str(x))


def chart(rounds, name):
    pts = [(i, r) for i, rd in enumerate(rounds) for r in rd["results"] if r["set"] == name]
    if not pts:
        return "<p class=muted>아직 없음</p>"
    w, h, pad = 520, 180, 30
    n = max(1, len(rounds) - 1)
    x = lambda i: pad + (w - 2 * pad) * (i / n if n else 0.5)
    y = lambda v: h - pad - (h - 2 * pad) * v
    parts = [f'<line x1={pad} y1={y(t)} x2={w - pad} y2={y(t)} class=grid /><text x=4 y={y(t) + 4} class=ax>{t:.1f}</text>' for t in (0, 0.5, 1)]
    for k, c in COLORS.items():
        xy = " ".join(f"{x(i):.0f},{y(r[k]):.0f}" for i, r in pts)
        parts.append(f'<polyline points="{xy}" fill=none stroke="{c}" stroke-width=2 />')
        parts += [f'<circle cx={x(i):.0f} cy={y(r[k]):.0f} r=3.5 fill="{c}"><title>{esc(rounds[i]["round"])} {k} {r[k]}</title></circle>' for i, r in pts]
    parts += [f'<text x={x(i):.0f} y={h - 8} class=ax text-anchor=middle>{esc(rd["round"])}</text>' for i, rd in enumerate(rounds)]
    return f'<svg viewBox="0 0 {w} {h}" role=img aria-label="{esc(name)} 라운드별 정밀도·재현율">{"".join(parts)}</svg>'


def no_ai_section(runs):
    """AI(로컬 LLM)를 받지 않은 컴퓨터 경우: 같은 정답으로 잰 마지막 결과"""
    if not runs:
        return ""
    rd = runs[-1]
    rows = "".join(f'<tr><td>{esc(r["set"])}</td><td>{r["precision"]:.3f}</td><td>{r["recall"]:.3f}</td><td>{r["shown"]} / {r["gold"]}</td>'
                   f'<td>{esc(", ".join(r["wrong"][:12]) or "없음")}</td></tr>' for r in rd["results"])
    return (f'<section><h2>AI 없는 컴퓨터 ({esc(rd["round"])}, {esc(rd["time"])})</h2><p class=muted>{esc(rd.get("note", ""))}</p>'
            f'<div class=scroll><table><tr><th>세트</th><th>정밀도</th><th>재현율</th><th>보여 줌 / 정답</th><th>잘못 보여 준 낱말(일부)</th></tr>{rows}</table></div></section>')


def build():
    allr = json.loads((HERE / "rounds.json").read_text(encoding="utf-8")) if (HERE / "rounds.json").exists() else []
    rounds = [r for r in allr if not r.get("no_llm")]
    last = rounds[-1] if rounds else None
    cards = []
    for name, title in SETS:
        r = next((r for r in last["results"] if r["set"] == name), None) if last else None
        prev = next((r for r in rounds[-2]["results"] if r["set"] == name), None) if len(rounds) > 1 else None
        delta = lambda k: "" if not (r and prev) else f' <span class=d>({r[k] - prev[k]:+.3f})</span>'
        body = (f'<div class=nums><div><b>{r["precision"]:.3f}</b>{delta("precision")}<small>정밀도: 보여 준 것 중 맞은 비율</small></div>'
                f'<div><b>{r["recall"]:.3f}</b>{delta("recall")}<small>재현율: 정답 중 보여 준 비율</small></div>'
                f'<div><b>{r["shown"]}</b><small>보여 줌 / 정답 {r["gold"]} / 낱말 {r["words"]}</small></div></div>'
                f'{chart(rounds, name)}'
                f'<details><summary>잘못 보여 준 낱말 {len(r["wrong"])}개 · 놓친 낱말 {len(r["missed"])}개 (최대 30개씩)</summary>'
                f'<p><em>잘못 보여 줌</em> {esc(", ".join(r["wrong"]) or "없음")}</p><p><em>놓침</em> {esc(", ".join(r["missed"]) or "없음")}</p></details>') if r else '<p class=muted>아직 측정하지 않음</p>'
        cards.append(f"<section><h2>{esc(title)}</h2>{body}</section>")
    rows = "".join(f'<tr><td>{esc(rd["round"])}{" (AI 없음)" if rd.get("no_llm") else ""}</td><td>{esc(rd["time"])}</td><td><code>{esc(rd["gate_version"])}</code></td><td><code>{esc(rd["gold"])}</code></td>'
                   f'<td>{"예" if rd["holdout"] else "아니요"}</td><td>{rd["seconds"]}초</td><td>{esc(rd.get("note", ""))}{"<br><span class=warn>예시와 겹친 평가 낱말 " + str(len(rd["leaked"])) + "개(이 낱말들은 낙관적): " + esc(", ".join(rd["leaked"])) + "</span>" if rd.get("leaked") else ""}</td></tr>' for rd in allr)
    gold_same = len({rd["gold"] for rd in rounds}) <= 1
    page = f"""<!doctype html><html lang=ko><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>개념 관문 평가</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--card:#fff;--line:#e7e5e4;--p:#2563eb;--r:#d97706}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--card:#292524;--line:#44403c;--p:#60a5fa;--r:#fbbf24}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,"Malgun Gothic",sans-serif}}
main{{max-width:1100px;margin:auto;padding:20px 16px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:0 0 10px}}
.muted,small,.ax{{color:var(--mut);fill:var(--mut);font-size:12px}}.grid{{stroke:var(--line)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin:16px 0}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.nums{{display:flex;gap:18px;flex-wrap:wrap}}.nums b{{font-size:24px}}.nums small{{display:block}}.d{{font-size:12px;color:var(--mut)}}
svg{{width:100%;height:auto;margin-top:8px}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{border-bottom:1px solid var(--line);padding:6px;text-align:left}}
.key span{{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 12px}}.warn{{color:#dc2626}}.scroll{{overflow-x:auto}}
</style></head><body><main>
<h1>개념 관문 평가: 어떤 질문의 답변이든 공부할 개념을 고르는가</h1>
<p class=muted>AI 답변의 낱말 중 공부할 개념을 고르는 판정을 라운드마다 고치고 잰다. 정답은 Claude가 결과를 보기 전에 표시했고 사용자 검토 전이다. 답변은 로컬 LLM(qwen3:4b)이 만든 글이다.
<span class=key><span style="background:var(--p)"></span>정밀도<span style="background:var(--r)"></span>재현율</span></p>
<p class="{'' if gold_same else 'warn'}">정답 파일 {'모든 라운드에서 같음' if gold_same else '라운드 사이에 바뀜: 수치를 직접 비교할 수 없음'} · 처음 보는 분야 측정 {'함' if any(rd['holdout'] for rd in rounds) else '아직 안 함'}</p>
<div class=cards>{''.join(cards)}</div>
{no_ai_section([r for r in allr if r.get("no_llm")])}
<section style="margin-top:14px"><h2>라운드 기록</h2><div class=scroll><table><tr><th>라운드</th><th>시각</th><th>판정 버전</th><th>정답 지문</th><th>처음 보는 분야</th><th>걸린 시간</th><th>바꾼 것</th></tr>{rows or '<tr><td colspan=7 class=muted>아직 없음</td></tr>'}</table></div></section>
</main></body></html>"""
    (HERE / "dashboard.html").write_text(page, encoding="utf-8")
    return HERE / "dashboard.html"


if __name__ == "__main__":
    print(build())
