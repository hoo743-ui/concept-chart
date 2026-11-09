# -*- coding: utf-8 -*-
"""공개 개발 용어집(한↔영, 사람이 번역) 원본 수집. 평가 전용이라 학습 데이터에 넣지 않는다 (data/raw/devgloss/, git 제외).

    python experiments/collect_devgloss.py

- MDN 한국어 용어집 files/ko/glossary: title(한국어) + slug(영어). mdn/translated-content
- Kubernetes 한국어 용어집 content/ko/docs/reference/glossary: title "파드 (원문, Pod)" + id. kubernetes/website, CC-BY-4.0
받은 그대로 저장하고 고치지 않는다. 요청은 0.3초 간격.
"""
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "devgloss"
UA = {"User-Agent": "concept-chart-research/0.1 (personal study tool; ko-en term pairs)"}
SOURCES = {
    "mdn": ("mdn/translated-content", "main", "files/ko/glossary/", "/index.md"),
    "k8s": ("kubernetes/website", "main", "content/ko/docs/reference/glossary/", ".md"),
}


def get(url):
    time.sleep(0.3)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def front(text):
    """--- 사이의 title·slug·id 줄만 읽는다"""
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    out = {}
    for line in (m.group(1) if m else "").splitlines():
        k = re.match(r"(title|slug|id):\s*(.+)$", line)
        if k:
            out[k.group(1)] = k.group(2).strip().strip("\"'")
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "pages.jsonl"
    n = fail = 0
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for name, (repo, branch, prefix, tail) in SOURCES.items():
            tree = json.loads(get(f"https://api.github.com/repos/{repo}/git/trees/{branch}:{prefix.rstrip('/').replace(':', '%3A')}?recursive=1"))
            if tree.get("truncated"):
                raise RuntimeError(name + " 목록이 잘렸다")
            paths = sorted(t["path"] for t in tree["tree"] if t["type"] == "blob" and t["path"].endswith(tail) and not t["path"].startswith("_"))
            for p in paths:
                try:
                    text = get(f"https://raw.githubusercontent.com/{repo}/{branch}/{prefix}{p}").decode("utf-8")
                except urllib.error.HTTPError:
                    fail += 1
                    continue
                f.write(json.dumps({"source": name, "path": p, **front(text)}, ensure_ascii=False) + "\n")
                n += 1
            print(name, "문서", len(paths), flush=True)
    meta = {"sources": {k: v[0] for k, v in SOURCES.items()}, "pages": n, "failed": fail, "collected": datetime.now(timezone.utc).isoformat(), "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
