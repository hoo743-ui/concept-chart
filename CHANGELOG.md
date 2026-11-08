# 변경 기록

날짜는 한국 시간. 페이지에 보이는 숫자가 바뀐 변경은 따로 표시한다.

## 0.3.3 — 2026-11-08

- serve 개념 추출: 숫자 조각(`cu`, `GB`)·단위·소문자 주소 조각(`https`)을 뺀다. 내 대화 순위가 달라질 수 있고, 색인 DB는 처음 켤 때 다시 만든다 (정의는 남김). 결과 페이지 숫자 변경 없음

## 0.3.2 — 2026-11-08

- serve 저장 구조: 질문은 분석 없이 원문 저장 후 답변의 개념과 연결(`records[].question`), 답변 하나에 개념 1행. 기존 색인 DB는 처음 켤 때 인박스에서 다시 만든다(정의는 남김)
- serve 메모리: Kiwi를 자식 프로세스로 분리, 10분 쉬면 종료. 순위 계산 캐시
- 페이지 숫자 변경 없음

## 0.3.1 — 2026-11-08

- serve: 개념 카드를 열면 뒤에서 위키백과 근거를 찾아 `notes`에 저장(`note_status`, 30일 유효, 출처 문장 그대로). `fetch_sources.wikipedia`는 동음이의 안내 문서를 제외하고 문서 제목을 함께 돌려준다
- 위키백과에 없는 개념은 SearXNG로 찾기: `kit/searxng/`(compose·settings, 버전 고정), `python dev.py searx up|down`, `serve --searx`. 실제 컨테이너 확인 전 (개발 PC에 Docker 없음)
- 카드에 `summary`(출처 문장을 다듬은 한 줄), 내장 화면은 한 줄 + "더 알아보기"
- 페이지 숫자 변경 없음 (코드 상자의 `fetch_sources.py`만 바뀜)

## 0.3.0 — 2026-11-08

- 로컬 서버 `kit/serve.py` + `python dev.py serve`: 인박스 1초 이어 읽기 → SQLite → `/api/leaderboard`·`/api/concept/{id}`·`/api/events`(SSE)·`/api/status`, 내장 간이 화면. 개념 = 명사+코드 용어, 점수 = 제안 C(H 7·세션 단위)를 내 세션 IDF로 적용
- `tests/test_serve.py`(18항목)를 `check_env`에 추가, `docs/ARCHITECTURE.md`에 API 계약
- 페이지 숫자 변경 없음

## 0.2.4 — 2026-11-07

- SETUP.md·`docs/COMMANDS.md`: Mac zsh는 기본 설정에서 `#` 설명을 명령으로 읽으므로 `setopt interactivecomments`를 맨 앞에 추가, 문제 해결 2줄(`#` 에러, `dev.py` 하위 명령 빠짐)

## 0.2.3 — 2026-11-07

- `docs/COMMANDS.md`: 세팅·VS Code·매일 시작·다시 만들기·커밋→CI→main·학습 실험·상태 확인·막혔을 때 명령 모음 (Mac 기준)

## 0.2.2 — 2026-11-07

- `docs/TRAINING.md` 다시 씀: 데이터 받기 → 살펴보기 → 전처리(데이터 계약) → 개념 단위 분할 → 기준선 → epoch 학습·조기 종료·과적합 대응 → 시험 → 기록·채택, VS Code 확인 체크리스트
- SETUP.md: 매일 시작 명령, VS Code 세팅(확장 3개·인터프리터·Interactive Window·Data Wrangler), 데이터 도구(pandas·matplotlib·ipykernel·pyarrow), 문제 해결 4줄
- `.gitignore`에 `/data/`, `docs/ARCHITECTURE.md`에 `experiments/` 의존 방향

## 0.2.1 — 2026-11-07

- SETUP.md(macOS): Homebrew PATH 설정(`brew shellenv`)과 `node@22` PATH 줄 추가, 관련 문제 해결 2줄

## 0.2.0 — 2026-11-07

구조
- macOS(Apple Silicon) 세팅 경로: SETUP.md를 macOS·Windows 병기로 다시 씀, CI에 macOS 추가(점검 + Miniforge conda 설치)
- `docs/TRAINING.md`: 학습 실험 가이드라인, `.gitignore`에 모델 파일 제외
- 결과 페이지를 `web/`로 분리: `web/page_template.html`, `web/build_page.py`, `web/dist/index.html` (예전 `sim/out/index.html`)
- `dev.py` 추가: `setup`(conda 또는 `--venv`) · `check` · `build` · `sim`
- `docs/ARCHITECTURE.md`, `CLAUDE.md`, 이 파일 추가

기능
- `sim_A.py`가 추세 배지(두 비율 z-검정, z>1.64·2세션 이상)와 새 용어 목록을 직접 계산
- `sim/make_page_data.py` 추가: 시뮬레이터 결과 → 페이지 데이터
- 훅 변환부를 `normalize()`로 분리, 입력 형식이 다르면 원문을 `raw`에 보존

점검
- `tests/test_hook.py` + fixture 8개, `tests/check_env.py`에 페이지 데이터 재현·훅 테스트 추가
- GitHub Actions CI (Windows·Ubuntu)

성능
- 형태소 분석기 지연 로딩: `make_page_data.py --check` 1.2초·318MB → 0.2초·46MB

페이지 데이터 변화 (보이는 값 동일)
- 실행 시간 측정값 재측정
- '헷갈리는 개념' 4개(손실 함수, 전이 학습, 정확도, 인코더)의 표시 순서
- 페이지에서 쓰지 않던 항목별 `new` 필드 제거
- 배지 방식 비교표는 기록값 파일(`sim/results/badge_eval.json`)로 분리 — 계산 코드 없음

## 0.1.0 — 2026-11-07

- 시뮬레이터 A·B·C, 결과 페이지, 입력 수집 키트, 개발환경 문서 첫 업로드
