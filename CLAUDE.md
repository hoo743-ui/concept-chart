# CLAUDE.md — 개념 차트 (concept-chart)

Claude Code 대화에서 자주 나온 개념을 중요도 순으로 보여 주고, 개념을 누르면 출처가 붙은 공부 노트로 펼치는 1인 해커톤 프로젝트.
사용자는 한국어로 짧고 바로 쓸 수 있는 답을 원한다. 코드를 줄 때는 붙여넣을 위치(파일·셀)를 함께 적는다.

## 작업 원칙 (사용자가 가장 중요하게 본 것)

- **방향을 스스로 바꾸거나 앞서 나가지 않는다.** 합의된 다음 할 일만 하고, 그 밖의 것은 제안만 한다.
- **확인하지 않은 사실을 쓰지 않는다.** 외부 도구 형식·버전·숫자는 문서나 실행 결과로 확인하고, 못 했으면 못 했다고 쓴다.
- 페이지에 나간 숫자(시뮬레이터 결과)를 바꾸는 변경은 사용자 결정 없이 하지 않는다.

## 구조와 데이터 흐름

자세한 구성·데이터 계약·품질 특성별 설계·변경 절차는 `docs/ARCHITECTURE.md`. 사용자가 쓰는 명령 모음은 `docs/COMMANDS.md`.

- `dev.py`: 작업 진입점 (`setup` · `check` · `build` · `sim` · `serve` · `searx`), 표준 라이브러리만.
- `sim/`: 시뮬레이터 A(중요도)·B(용어 정규화)·C(근거 문장) → `results/A·B·C.json`
  → `make_page_data.py`(+ `results/badge_eval.json` 기록값, `concepts.py`) → `results/page_data.json`
- `web/`: `build_page.py`(+ `page_template.html`, `kit/*.py`, `sim/results/page_data.json`) → `dist/index.html`
- `kit/`: 실제 쓰는 코드. 로컬 서버(`serve.py`, API 계약은 `docs/ARCHITECTURE.md`), 훅 설치기(`install_concept_hook.py`, 훅 본문은 `HOOK_TEMPLATE` 안의 `normalize()`가 어댑터), 노트북 첫 셀, 클릭 카드, 근거 수집, 검증 에이전트.
- `tests/`: `check_env.py`(전체 점검), `test_hook.py`(훅 fixture), `test_serve.py`(서버), `check_page.js`·`check_setup.js`(jsdom).

## 규칙

- 텍스트 파일은 UTF-8 + LF (`.gitattributes`). 파일을 열 때 `encoding="utf-8"`를 꼭 쓴다 (Windows 기본 cp949).
- 경로는 스크립트 위치 기준(`pathlib.Path(__file__)`)으로 잡는다. 어느 폴더에서 실행해도 같아야 한다.
- 코드 상자 원본은 `kit/`뿐이다. `web/page_template.html`의 `tpl-*` 상자는 비워 두고 `web/build_page.py`가 채운다.
- 커밋 전: `python dev.py check` (마지막 줄 `결과: 모두 통과`). 브랜치 → 푸시 → CI(Windows·macOS·Ubuntu + Windows·macOS conda 설치) 통과 → main. `CHANGELOG.md`에 한 줄.
- 의존 방향: `kit/`는 다른 폴더에 의존하지 않고, `web/`·`sim/`은 `kit/`를 import하지 않는다 (`web/build_page.py`는 글자 그대로 읽기만).
- git에 올리지 않는 것: `~/.claude/concept-inbox.jsonl`, `*.sqlite` (개인 대화 데이터).
- 훅은 아무것도 출력하지 않고 항상 0으로 끝나야 한다 (UserPromptSubmit의 stdout은 Claude 문맥에 들어간다).

## 현재 상태 (2026-11-08)

개발 PC: macOS(Apple Silicon)·Windows 둘 다. 세팅은 `SETUP.md`.

완료
- 시뮬레이터 A·B·C, 결과 페이지, 입력 설정 시트(한 줄 설치), 클릭 카드·근거 수집·검증 에이전트
- 추세 배지(두 비율 z-검정)·새 용어 계산을 `sim_A.py`에 복원, `make_page_data.py`로 페이지 데이터 재현
- 훅 어댑터 정리(형식이 다르면 원문을 `raw`에 보존) + fixture 테스트, CI(Windows + Ubuntu)
- 구조 정리(0.2.0): 결과 페이지 `web/` 분리, `dev.py`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`, 형태소 분석기 지연 로딩
- 로컬 서버 `serve`(0.3.0): 인박스 1초 이어 읽기 → SQLite → `/api/leaderboard`·`/api/concept/{id}`·`/api/events`(SSE)·`/api/status`, `localhost:8765`. 사용자 결정(11-08): 개념 = 명사+코드 용어(사전 없음), IDF 배경 = 내 세션
- 사용자 흐름 데모 디자인(캔버스, 비공개): https://claude.ai/artifact/MrXdwFhQjyFokNCraw1Uz4

다음 할 일 (합의된 순서)
1. 웹 디자인 확정 (캔버스 기반). 데이터는 `/api/...`에서 받게 짜고(데모 모드 = 정적 JSON), `python dev.py serve --web <폴더>`로 띄운다.

나중에 / 사용자 결정 필요
- Gemini CLI·Codex CLI 입구(어댑터) 추가 — 범위 확장 포인트로만 둔 상태
- 배지 방식 비교표 재계산 — 평가 코드가 없어 기록값을 쓰는 중, 재계산하면 숫자가 바뀔 수 있음
- 사용자가 실제 데이터셋으로 모델 학습 실험을 할 계획 (용어 정규화 B·근거 문장 C 쪽이 적용 후보). 규칙은 `docs/TRAINING.md`를 따른다 (기준선 먼저, 개념 단위 분할, 시험 세트 고정, 기록만 커밋, 채택은 사용자 결정).

## 알려진 제약

- serve 개념 추출은 띄어 쓴 복합어(`조기 종료`)를 두 개로 센다. 인박스를 같은 크기 이상의 다른 파일로 바꾸면 자동으로 감지하지 못한다 → `--rebuild`.
- SearXNG는 실제 컨테이너로 `/search?format=json` 응답까지 확인했다(11-08). 다만 근거 문장 품질이 부족하다: 샘플 7개 중 첫 문장이 맞는 정의는 2개. 다른 뜻(`torch` → 손전등)·정의가 아닌 문장이 잡히고, 띄어쓰기가 다르면(`조기종료`) 탈락한다.
- 사용자 결정(11-08): 정의는 위키백과 → SearXNG(Docker), 화면은 한 줄 + "더 알아보기". 한 줄은 출처 문장을 다듬은 것이고 LLM 요약이 아니다.

- `badge_eval.json`은 다시 계산할 수 없는 기록값. `NEW_TERM_MIN_IDF = 3.6`은 저장 결과와 맞춰 찾은 값(3.56~3.66 구간).
- 훅 fixture는 공식 문서 필드로 만든 예시이고 실제 캡처가 아니다. Claude Code 입력이 바뀌면 실제 입력을 케이스로 추가한다.
- Windows에서 훅은 Git Bash로 실행된다. Git Bash가 없으면 PowerShell에서 실행돼 동작하지 않을 수 있다.
