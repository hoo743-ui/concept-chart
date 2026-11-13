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
- `chat/`: 내 공부 기록에 묻기 (따로 도는 API 서버, 포트 8766. 화면은 11-13부터 개념 차트 웹 `app/atelier.html#/chat`, `app/atelier-chat.js`). 개념 차트와는 `docs/API.md`의 읽기 API로만 만나고, `kit/`에서는 `llm.py`만 쓴다. `kit/`는 `chat/`을 모른다.
- `ml/`: 학습한 모델을 쓰는 코드 (`concept_clf.py`, 작업자가 별도 프로세스로만 실행, `kit/`는 불러오지 않는다).
- `tests/`: `check_env.py`(전체 점검), `test_hook.py`(훅 fixture), `test_serve.py`(서버), `check_page.js`·`check_setup.js`(jsdom).

## 규칙

- 텍스트 파일은 UTF-8 + LF (`.gitattributes`). 파일을 열 때 `encoding="utf-8"`를 꼭 쓴다 (Windows 기본 cp949).
- 경로는 스크립트 위치 기준(`pathlib.Path(__file__)`)으로 잡는다. 어느 폴더에서 실행해도 같아야 한다.
- 코드 상자 원본은 `kit/`뿐이다. `web/page_template.html`의 `tpl-*` 상자는 비워 두고 `web/build_page.py`가 채운다.
- 커밋 전: `python dev.py check` (마지막 줄 `결과: 모두 통과`). 브랜치 → 푸시 → CI(Windows·macOS·Ubuntu + Windows·macOS conda 설치) 통과 → main. `CHANGELOG.md`에 한 줄.
- 의존 방향: `kit/`는 다른 폴더에 의존하지 않고, `web/`·`sim/`은 `kit/`를 import하지 않는다 (`web/build_page.py`는 글자 그대로 읽기만).
- git에 올리지 않는 것: `~/.claude/concept-inbox.jsonl`, `*.sqlite` (개인 대화 데이터).
- 훅은 아무것도 출력하지 않고 항상 0으로 끝나야 한다 (UserPromptSubmit의 stdout은 Claude 문맥에 들어간다).

## 현재 상태 (2026-11-12)

개발 PC: macOS(Apple Silicon)·Windows 둘 다. 세팅은 `SETUP.md`.

완료
- 시뮬레이터 A·B·C, 결과 페이지, 입력 설정 시트(한 줄 설치), 클릭 카드·근거 수집·검증 에이전트
- 추세 배지(두 비율 z-검정)·새 용어 계산을 `sim_A.py`에 복원, `make_page_data.py`로 페이지 데이터 재현
- 훅 어댑터 정리(형식이 다르면 원문을 `raw`에 보존) + fixture 테스트, CI(Windows + Ubuntu)
- 구조 정리(0.2.0): 결과 페이지 `web/` 분리, `dev.py`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`, 형태소 분석기 지연 로딩
- 로컬 서버 `serve`(0.3.0): 인박스 1초 이어 읽기 → SQLite → `/api/leaderboard`·`/api/concept/{id}`·`/api/events`(SSE)·`/api/status`, `localhost:8765`. 사용자 결정(11-08): 개념 = 명사+코드 용어(사전 없음), IDF 배경 = 내 세션
- serve 확장(0.3.1~0.3.6): 정의 수집(위키백과 → SearXNG, `kit/searxng/`), 화면은 한 줄 + "더 알아보기", 근거가 없으면 내 대화 문장, 질문 원문 저장·개념 연결(질문은 분석 안 함), 답변당 개념 1행, Kiwi 자식 프로세스 분리, 숫자·단위·주소 조각 제외, 작업 폴더별 보기(`--project`)
- 사용자 흐름 데모 디자인(캔버스, 비공개): https://claude.ai/artifact/MrXdwFhQjyFokNCraw1Uz4

- 공부 프로토타입(0.4.0, 사용자가 방향을 맡김 11-09): `python dev.py app`. 개념 관문(`kit/concept_gate.py`), 비용 없는 로컬 LLM(`kit/llm.py`, `qwen3:4b`), 별도 프로세스 모델 작업자(`kit/study_worker.py`), 근거 대조 통과 문장만 저장, 화면(`app/`)과 계약(`docs/API.md`) 분리, 입구 확장(`kit/concept_add.py`: 붙여넣기·파이프·내보내기 파일)
- 표기 합치기 모델 실험 결론: 서비스에 켜지 않음 (`docs/DECISION_LOG.md` D1)
- 분야 무관 개념 관문(0.5.0, 11-10): 분야 사전(`lexicons/` → `python dev.py lexicon`) + 위키백과를 두 번째 근거로 (D8). 평가·대시보드는 `experiments/2026-11-10-general-gate/`
- 화학식 조각 거르기 + 새 분야 세트 측정(0.5.1, 11-10): `--set=fresh`. 화면 정리 방향(11-10 사용자 결정): 첫 화면은 질문별 묶음. 먼저 카드에 출처 질문(`origin`)·분야 꼬리표(`field`, `kit/fields.py`)를 넣었다
- 배포 방향(11-10 사용자 결정, D7): 작은 설치 파일 하나 + 앱 창(로컬 서버 + OS 웹뷰) + AI는 첫 실행에서 선택 받기, Claude Code 플러그인은 입구. 디자인·UI/UX는 사용자가 나중에 직접
- 내 공부 기록에 묻기(0.6.0): 따로 도는 앱 `chat/`. 지속 검증(0.6.4~): 개념 노트의 '맞아요·아니에요' + `python dev.py verify` (피드백 정밀도·개발 대화·설명이 붙은 비율을 기록, 떨어지면 알림)
- 11-11~12 개선(0.6.6~0.7.10, 자세한 근거는 CHANGELOG·DECISION_LOG D8): 공부 목록 전체 정의 찾기, 코드 속 이름(import·pip), 꼬리 떼기(당·별·들), 위키백과에 없으면 우리말샘 뜻풀이·PyPI 설명, 설명 단계의 '기술 분야 전용' 확인 고침, 쉬운 설명 한 번 더, 영어 표기 낱말 전용 질문, 작업 다시 예약 고침. 실제 기록(11-12 01시): 피드백 정밀도 0.940, 개발 대화 0.912·0.486, 설명이 붙은 비율 0.725
- 디자인 가이드 `docs/DESIGN_GUIDE.md` (사용자가 피그마로 화면을 그림)
- 0.7.15~0.7.16(11-13, 사용자 결정): 위키백과가 다른 뜻 문서로 넘겨준 정의는 쓰지 않는다(중복 → 복날, Export → 수출). 그 문서는 관문 근거로만 센다(0.7.15에서 근거까지 뺐더니 사용자가 '맞아요'한 낱말 10개가 빠짐). 사용자 판단으로는 Variables·Mock 같은 영어 낱말도 개념. 웹 디자인은 챗봇까지 한 웹으로 합쳐 투자하는 방향(11-13 사용자 의견, 합치는 순서는 정하기 전)

- 개념 분류기(0.8.0, 11-13 사용자 결정 '0.97로 가자', D9): klue/roberta-base 미세조정 점수로 관문을 정한다(`ml/concept_clf.py`, 모델은 `models/concept-clf` git 제외). 교차 검증 개발 대화 0.893·0.472 → 0.855·0.665. 일반 세트로만 배우면 재현율이 오히려 낮다(내 대화 정답을 배운 덕분)

- 설명 넓히기(0.8.2, 11-13, D10): 한국어 위키백과는 이 PC 안 덤프 색인(`lexicons/kowiki_dump.py` → `kit/data/lexicon/kowiki.sqlite`)을 먼저, SearXNG는 네이버·빙 추가, 8888이 막히면 8889

읽을 것: `docs/WORKSHEET.md`(기획 5단계), `docs/DECISION_LOG.md`(결정 근거), `docs/CONSTRAINTS.md`(할루시네이션 방지 규칙, 새 기능은 이 규칙을 지킨다), `docs/API.md`(화면과 서버의 계약), `docs/DESIGN_GUIDE.md`(피그마로 화면 그리기: 지킬 원칙·화면별 데이터·상태)

다음 할 일 (합의된 순서)
1. 지속 검증: 사용자가 공부하며 '맞아요·아니에요'를 누르고 `python dev.py verify`로 지표를 본다. 개선은 실험 → 평가 세트 + 실제 피드백으로 확인 → 사용자 결정 → 반영.
2. 사용자 결정 대기: 0.7.5(영어 새 질문)가 실제 사용에서 흔한 영어 단어(Design·Export·Dark)도 올리는 문제 — 그대로 두기 / 되돌리기 / 영어 빈도 데이터(wordfreq, Apache-2.0·데이터 CC BY-SA 4.0) 실험(설치 권한 필요).
3. 그 뒤: 디자인(피그마 → `app/`), 설치 파일, 사용자 수준별 추출(검증을 마친 뒤), 시험 세트 최종 측정(맨 마지막 한 번).

나중에 / 사용자 결정 필요
- Gemini CLI·Codex CLI 입구(어댑터) 추가 — 범위 확장 포인트로만 둔 상태
- 배지 방식 비교표 재계산 — 평가 코드가 없어 기록값을 쓰는 중, 재계산하면 숫자가 바뀔 수 있음
- 사용자가 실제 데이터셋으로 모델 학습 실험을 할 계획 (용어 정규화 B·근거 문장 C 쪽이 적용 후보). 규칙은 `docs/TRAINING.md`를 따른다 (기준선 먼저, 개념 단위 분할, 시험 세트 고정, 기록만 커밋, 채택은 사용자 결정).

## 알려진 제약

- serve 개념 추출은 띄어 쓴 복합어(`조기 종료`)를 두 개로 센다. 인박스를 앞 256바이트까지 같은 다른 파일로 바꾸면 자동으로 감지하지 못한다 → `--rebuild`.
- 사용자 결정(11-09): 모델·파인튜닝이 들어와도 백본이 깨지면 안 된다. `docs/ARCHITECTURE.md`의 모델 경계를 따르고 `tests/test_boundary.py`로 강제한다.
- SearXNG는 실제 컨테이너로 확인했다(11-08). 문장 거르기·뜻 구분을 넣은 뒤 처음 보는 12개(검색 단계만, 사람 판정): 맞음 7 · 부족 1 · 근거 없음 4 · 틀림 0. `근거 없음`이 남고, 정의가 아닌 평가 문장(`데드락`)이 통과할 수 있다. 위키백과 단계에는 뜻 구분이 없다.
- 사용자 결정(11-08): 정의는 위키백과 → SearXNG(Docker), 화면은 한 줄 + "더 알아보기". 한 줄은 출처 문장을 다듬은 것이고 LLM 요약이 아니다.

- `badge_eval.json`은 다시 계산할 수 없는 기록값. `NEW_TERM_MIN_IDF = 3.6`은 저장 결과와 맞춰 찾은 값(3.56~3.66 구간).
- 훅 fixture는 공식 문서 필드로 만든 예시이고 실제 캡처가 아니다. Claude Code 입력이 바뀌면 실제 입력을 케이스로 추가한다.
- Windows에서 훅은 Git Bash로 실행된다. Git Bash가 없으면 PowerShell에서 실행돼 동작하지 않을 수 있다.
