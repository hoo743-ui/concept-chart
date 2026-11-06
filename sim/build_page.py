# -*- coding: utf-8 -*-
"""페이지 빌드: page_template.html + kit/*.py + results/page_data.json → out/index.html

    python sim/build_page.py           # out/index.html 다시 만들기 (어느 폴더에서 실행해도 됨)
    python sim/build_page.py --check   # 다시 만든 결과가 지금 out/index.html과 같은지만 확인

페이지의 코드 상자(설치 파일·파이프라인 셀·검증 에이전트 등)는 kit/ 원본을 빌드할 때 넣는다.
코드를 고칠 때는 kit/ 쪽 파일만 고치고 이 스크립트를 다시 돌리면 된다.
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
TEMPLATE = HERE / "page_template.html"
DATA = HERE / "results" / "page_data.json"
OUT = HERE / "out" / "index.html"

# 템플릿의 <script type="text/plain" id="tpl-…"> 상자 ↔ kit 원본 파일
EMBED = {
    "installer": "install_concept_hook.py",
    "loader": "loader_cell.py",
    "store": "concept_store.py",
    "fetch": "fetch_sources.py",
    "verify": "verify_note.py",
}


def read(path):
    # newline="" : 줄바꿈을 바꾸지 않고 그대로 읽는다 (Windows에서도 결과 바이트가 같도록)
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def build():
    html = read(TEMPLATE)
    for tid, name in EMBED.items():
        src = read(ROOT / "kit" / name)
        if "</script" in src.lower():
            sys.exit(f"[build_page] {name}: 코드 안에 '</script'가 있으면 페이지에 넣을 수 없음")
        pat = re.compile(r'(<script type="text/plain" id="tpl-%s"[^>]*>)(.*?)(</script>)' % tid, re.S)
        html, n = pat.subn(lambda m: m.group(1) + "\n" + src + m.group(3), html, count=1)
        if n != 1:
            sys.exit(f"[build_page] 템플릿에서 tpl-{tid} 상자를 찾지 못함")
    if html.count("__DATA__") != 1:
        sys.exit("[build_page] 템플릿에 __DATA__ 자리가 정확히 1개 있어야 함")
    data = json.loads(read(DATA))
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return html.replace("__DATA__", blob)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="파일을 쓰지 않고 out/index.html과 같은지만 확인")
    args = ap.parse_args()
    html = build()
    if args.check:
        same = OUT.exists() and read(OUT) == html
        print("[build_page] out/index.html:", "최신 상태" if same else "다름 → python sim/build_page.py 로 다시 만들기")
        sys.exit(0 if same else 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    print(f"[build_page] {OUT.relative_to(ROOT).as_posix()} 생성 ({len(html.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
