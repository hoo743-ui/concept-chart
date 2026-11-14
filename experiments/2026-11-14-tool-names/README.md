# 영어 도구·제품 이름의 근거 넓히기 실험 (2026-11-14)

사용자 요청: "단어의 문맥(설명)을 아직 못 찾는다, 데이터셋을 넣어 최대한의 단어 매칭" · "qwen이나 SearXNG 같은 내용을 아직 모르는 것 같다".

## 1. 원인 확인 (서버 코드 그대로 실행)

`serve.fetch_note`를 직접 돌리면 Qwen·Ollama(한국어 위키백과), SearXNG(영어 위키백과), kiwipiepy(검색)는 설명을 **찾는다**.
못 보이는 이유는 낱말마다 달랐다 (이 Mac의 Claude Code 답변 154개로 만든 임시 DB):

| 낱말 | 판정 | 이유 |
|---|---|---|
| SearXNG · Ollama · Docker | 공부 목록 | 설명 찾기 작업이 그 낱말까지 아직 안 옴 (실제 사용자 DB는 기록 0건이었음) |
| qwen (소문자) | 후보(숨김) | 사전만 인정(likely), AI 판정 대기 |
| Colima · Termius | 후보(숨김) | AI는 개념이라 함, 이름이 맞는 위키백과 문서가 없어 두 번째 근거 없음 (원래 PC는 분류기 D9가 메움, 이 Mac엔 없음) |
| Kiwi · colima | — | 설명을 찾으면 다른 뜻(과일 키위, 멕시코 콜리마주)이 붙음 |

## 2. 이 Mac에 빠져 있던 기존 자료 설치 (설계 변경 없음)

- 분야 사전(D8): 우리말샘 + 학습용 어휘 → `kit/data/lexicon/lexicon.sqlite` 낱말 900,528개. 같은 판정 상태에서 공부 목록 222 → 230.
- 한국어 위키백과 덤프 색인(D10): `kit/data/lexicon/kowiki.sqlite`.

## 3. 새 데이터셋: Homebrew 패키지·앱 설명

- 출처: https://formulae.brew.sh/api/formula.json (8,730개), cask.json (7,832개). 라이선스 BSD-2-Clause (Homebrew/homebrew-core·homebrew-cask·formulae.brew.sh 저장소 라이선스, GitHub API로 확인).
- 방법: 영어 표기 낱말 728개를 이름(패키지 이름·별칭·앱 이름)으로 정확히 맞춰 봄 (`brew_match.py`).

| 판정 묶음 | 낱말 | Homebrew에 있음 | 맞는 뜻 (눈으로) |
|---|---|---|---|
| 후보, AI는 개념이라 함 | 40 | 12 | Colima·Termius·Raycast·Discord·Wayland·Rectangle·zip ≈ 7 · 틀림: Mac(오디오 코덱)·Silicon(코드 이미지)·Ubuntu(글꼴)·Alembic(그래픽)·has |
| 공부 목록 | 218 | 36 | ChatGPT·Claude·Docker·Git·FastAPI·EXIF 등 · 틀림: ACK(grep류 도구)·CLIP(차트)·GNOME(GIF 도구)·IO(언어)·GX |
| 숨김 (일상 영어 포함) | 451 | 45 | so·task·bridge·Connect·Adapter 같은 일상어가 도구 이름과 겹침 |

## 4. 결론 (사용자 결정 전)

- 이름만 맞추면 절반 가까이 다른 뜻이다 → 자동 근거·자동 설명으로 넣으면 오탐과 틀린 설명이 늘어난다(제약 9·12).
- 쓸 수 있는 자리: 이미 있는 '뜻 고르기'(0.9.2)의 후보로 넣어 사람이 고르게. 또는 대화에서 `brew install 이름`처럼 Homebrew로 쓰인 것이 보일 때만 근거로.
