# 실험: Homebrew 패키지·앱 설명(BSD-2-Clause)이 영어 도구 이름의 '두 번째 근거'·설명이 될 수 있나. 서버 코드는 바꾸지 않는다.
# 대상: 임시 서버 DB(이 Mac의 Claude Code 답변 154개)의 영어 표기 낱말 전부. 판정은 study_api.gate_of (분야 사전 설치 후).
import collections, json, pathlib, sqlite3, sys
KIT, DB, BREW, OUT = map(pathlib.Path, sys.argv[1:5])
sys.path.insert(0, str(KIT))
import concept_gate as gate, study_api as api

f = json.loads((BREW / "formula.json").read_text()); c = json.loads((BREW / "cask.json").read_text())
brew = {}
for x in f:
    for n in [x["name"]] + x.get("aliases", []):
        brew.setdefault(n.lower(), ("formula", x["name"], x.get("desc") or ""))
for x in c:
    for n in [x["token"]] + (x.get("name") or []):
        brew.setdefault(n.lower(), ("cask", x["token"], x.get("desc") or ""))

con = sqlite3.connect(DB)
rows = []
for cid, in con.execute("SELECT concept FROM freq"):
    lab = (con.execute("SELECT form FROM forms WHERE concept=? ORDER BY n DESC LIMIT 1", (cid,)).fetchone() or [cid])[0]
    if not gate.ASCII_FORM.fullmatch(lab):
        continue
    g = api.gate_of(con, cid, lab, use_user=False)
    j = api.judgment_row(con, cid) or (None, None, None, None)
    turns = con.execute("SELECT COUNT(DISTINCT ts) FROM mentions WHERE concept=?", (cid,)).fetchone()[0]
    note = con.execute("SELECT definition FROM notes WHERE concept=?", (cid,)).fetchone()
    rows.append({"label": lab, "turns": turns, "show": g["show"], "candidate": g["candidate"], "by": g["by"], "rule": g["rule"],
                 "llm": j[0], "brew": brew.get(lab.lower()), "has_note": bool(note and note[0])})

res = {"ascii_words": len(rows)}
grp = collections.defaultdict(list)
for r in rows:
    k = ("show" if r["show"] else "candidate" if r["candidate"] else "hide") + "/" + ("llm_yes" if r["llm"] == 1 else "llm_no" if r["llm"] == 0 else "llm_none")
    grp[k].append(r)
for k, v in sorted(grp.items()):
    res[k] = {"n": len(v), "brew_match": sum(bool(r["brew"]) for r in v), "examples": [(r["label"], r["brew"][1], r["brew"][2][:60]) for r in v if r["brew"]][:15]}
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1))
