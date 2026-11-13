# -*- coding: utf-8 -*-
"""한국어 위키백과 덤프 → 이 PC 안의 문서 첫 문단 색인 (0.8.2, 사용자 결정 11-13 '둘 다': 온라인 검색이 요청 제한으로 막혀 설명을 못 찾는 개념을 넓힌다)

    python lexicons/kowiki_dump.py [덤프.xml.bz2]   → kit/data/lexicon/kowiki.sqlite (git 제외, 다시 만들 수 있다)

원본: https://dumps.wikimedia.org/kowiki/latest/kowiki-latest-pages-articles.xml.bz2 (CC BY-SA 4.0, 화면에는 문서 주소를 출처로 붙인다).
받은 파일은 data/raw/kowiki_dump/ (git 제외). 일반 문서(이름공간 0)만 읽는다.
- pages(title, lead, disamb): 위키 문법을 걷어 낸 첫 문단 (최대 1200자). 동음이의 문서는 disamb=1
- redirects(src, dst): 넘겨주기 (GPU → 그래픽 처리 장치)
메모리: 문서를 하나씩 읽고 버린다 (덤프 전체를 올리지 않는다). 문서 앞 12000자만 본다 (첫 문단은 맨 앞에 있다).
"""
import bz2
import html
import pathlib
import re
import sqlite3
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "kowiki_dump" / "kowiki-latest-pages-articles.xml.bz2"
OUT = ROOT / "kit" / "data" / "lexicon" / "kowiki.sqlite"
HEAD = 12000
LEAD_MAX = 1200
DROP_NS = re.compile(r"^\s*(파일|File|그림|Image|분류|Category|틀|Template|위키백과|Wikipedia|포털|Portal):", re.I)
DISAMB = re.compile(r"\{\{\s*(동음이의|disambig|다른 뜻 목록|동음이의어)", re.I)


def innermost(text, pat, repl, limit=30):
    for _ in range(limit):
        new = pat.sub(repl, text)
        if new == text:
            return new
        text = new
    return text


TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
TABLE = re.compile(r"\{\|[^{}]*?\|\}", re.S)


def link(m):
    inner = m.group(1)
    if DROP_NS.match(inner):
        return ""
    return inner.split("|")[-1]


LINK = re.compile(r"\[\[([^\[\]]*)\]\]")


def clean(wikitext):
    t = wikitext[:HEAD]
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<ref[^>/]*/>", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = innermost(t, TEMPLATE, "")
    t = innermost(t, TABLE, "")
    t = innermost(t, LINK, link)
    t = re.sub(r"\[https?://[^\s\]]+\s*([^\]]*)\]", r"\1", t)
    t = re.sub(r"'{2,}", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ")
    for para in re.split(r"\n\s*\n", t):
        lines = [ln.strip() for ln in para.split("\n") if ln.strip() and not ln.strip().startswith(("=", "*", "#", ":", ";", "|", "!", "{", "}", "__"))]
        p = re.sub(r"\s+", " ", " ".join(lines)).strip()
        p = re.sub(r"\(([^()]*?)[,;]\s*\)", r"(\1)", p)       # 걷어 낸 틀이 남긴 꼬리 쉼표 (數學, ) → (數學)
        p = re.sub(r"\(\s*[,;]?\s*\)", "", p).strip()        # 걷어 낸 틀이 남긴 빈 괄호
        if len(p) >= 20 and re.search(r"[가-힣]", p):
            return p[:LEAD_MAX]
    return ""


def norm(t):
    """띄어쓰기·붙임표만 다른 제목을 같은 것으로 (파인튜닝 = 파인 튜닝). kit/serve.norm_key와 같은 뜻"""
    return re.sub(r"[\s\-_/]+", "", t.lower())


def add_norm(con):
    """pages.norm 열과 색인 (덤프 색인을 다시 만들지 않고도 붙일 수 있다: --norm)"""
    if "norm" not in {r[1] for r in con.execute("PRAGMA table_info(pages)")}:
        con.execute("ALTER TABLE pages ADD COLUMN norm TEXT")
    con.create_function("norm", 1, norm)
    con.execute("UPDATE pages SET norm = norm(title)")
    con.execute("CREATE INDEX IF NOT EXISTS pages_norm ON pages (norm)")
    con.commit()


def pages_of(src):
    """덤프를 줄 단위로 읽어 (제목, 이름공간, 넘겨줄 제목 또는 None, 본문 앞 HEAD자). XML 파서를 쓰지 않는다:
    ElementTree(expat)는 아주 큰 문서 하나에서 'out of memory'로 멈췄다 (11-13, 3417만 번째 줄). 덤프는 한 줄에 태그 하나라 규칙적이다"""
    title = ns = redirect = None
    buf, in_text, size = [], False, 0
    with bz2.open(src, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if in_text:
                end = line.find("</text>")
                part = line if end < 0 else line[:end]
                if size < HEAD:
                    buf.append(part)
                    size += len(part)
                if end >= 0:
                    in_text = False
                continue
            s = line.strip()
            if s == "<page>":
                title = ns = redirect = None
                buf, size = [], 0
            elif s.startswith("<title>"):
                title = html.unescape(s[7:-8])
            elif s.startswith("<ns>"):
                ns = s[4:-5]
            elif s.startswith("<redirect "):
                m = re.search(r'title="([^"]*)"', s)
                redirect = html.unescape(m.group(1)) if m else ""
            elif s.startswith("<text"):
                if s.endswith("/>"):
                    continue
                body = line[line.index(">", line.index("<text")) + 1:]
                end = body.find("</text>")
                part = body if end < 0 else body[:end]
                buf.append(part)
                size += len(part)
                in_text = end < 0
            elif s == "</page>":
                yield title, ns, redirect, html.unescape("".join(buf)[:HEAD])


def main():
    if sys.argv[1:] == ["--norm"]:
        if not OUT.is_file():
            sys.exit(f"색인이 없다: {OUT}")
        con = sqlite3.connect(OUT)
        add_norm(con)
        print("norm 열을 붙였다:", OUT)
        return
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    if not src.is_file():
        sys.exit(f"덤프가 없다: {src} (https://dumps.wikimedia.org/kowiki/latest/ 에서 받는다)")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("CREATE TABLE pages (title TEXT PRIMARY KEY, lead TEXT, disamb INTEGER)")
    con.execute("CREATE TABLE redirects (src TEXT PRIMARY KEY, dst TEXT)")
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    t0, n, pages, reds = time.time(), 0, [], []
    for title, ns, redirect, text in pages_of(src):
        if ns == "0" and title:
            if redirect is not None:
                reds.append((title, redirect))
            else:
                pages.append((title, clean(text), int(bool(DISAMB.search(text)))))
        n += 1
        if len(pages) + len(reds) >= 5000:
            con.executemany("INSERT OR REPLACE INTO pages VALUES (?,?,?)", pages)
            con.executemany("INSERT OR REPLACE INTO redirects VALUES (?,?)", reds)
            con.commit()
            pages, reds = [], []
        if n % 100000 == 0:
            print(f"{n} 문서 ({time.time() - t0:.0f}초)", flush=True)
    con.executemany("INSERT OR REPLACE INTO pages VALUES (?,?,?)", pages)
    con.executemany("INSERT OR REPLACE INTO redirects VALUES (?,?)", reds)
    con.execute("CREATE INDEX pages_nocase ON pages (title COLLATE NOCASE)")
    con.execute("CREATE INDEX redirects_nocase ON redirects (src COLLATE NOCASE)")
    add_norm(con)
    con.executemany("INSERT INTO meta VALUES (?,?)", [("source", src.name), ("built", time.strftime("%Y-%m-%d %H:%M")),
                                                      ("license", "CC BY-SA 4.0 (Wikipedia)")])
    con.commit()
    np_ = con.execute("SELECT COUNT(*), SUM(lead<>'') FROM pages").fetchone()
    nr = con.execute("SELECT COUNT(*) FROM redirects").fetchone()[0]
    con.close()
    tmp.replace(OUT)
    print(f"끝: 문서 {np_[0]} (첫 문단 있음 {np_[1]}), 넘겨주기 {nr}, {time.time() - t0:.0f}초 → {OUT}")


if __name__ == "__main__":
    main()
