# 설계 문서 — 개념 차트

구성 요소, 데이터 계약, 품질 특성별 설계 결정, 생명주기 단계별 산출물을 한곳에 둔다.
구조를 바꿀 때는 이 문서와 `CLAUDE.md`를 같이 고친다.

## 1. 구성 요소와 책임

| 폴더 | 책임 | 들어오는 것 → 나가는 것 | 실행 |
|---|---|---|---|
| `kit/` | 실제 사용 코드 (입구·처리·저장·근거·검증) | Claude Code 훅 입력 → `~/.claude/concept-inbox.jsonl` → 카드·근거·검증 결과 | 사용자 PC |
| `sim/` | 방식 비교 실험과 그 결과 | 가상 사용자 대화 → `results/A·B·C.json` → `results/page_data.json` | 개발 시 |
| `web/` | 결과 페이지 (화면) | `sim/results/page_data.json` + `kit/*.py` → `web/dist/index.html` | 개발 시 |
| `tests/` | 점검·계약 테스트 | 위 전부를 호출 | 커밋 전·CI |
| `dev.py` | 생명주기 작업 진입점 (setup·check·build·sim) | — | 어디서나 |
| `.github/workflows/` | CI (Windows·macOS·Ubuntu, conda 설치 경로 포함) | 푸시 | GitHub |

의존 방향 (반대 방향 import 금지):

- `web/build_page.py` → `kit/*.py`(글자 그대로 읽기), `sim/results/page_data.json` — 둘 다 읽기만 한다.
- `sim/make_page_data.py` → `sim/concepts.py`, `sim/pipeline.py`, `sim/results/*` — `kit/`를 import하지 않는다.
- `kit/` → 다른 폴더에 의존하지 않는다 (사용자 PC에 파일 하나씩 복사해도 돌아가야 함). 특히 훅 설치기는 파일 하나로 완결된다.

## 2. 데이터 계약

### 인박스 레코드 v1 (`~/.claude/concept-inbox.jsonl`, 한 줄 = 한 레코드)

| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `v` | 정수 | 예 | 형식 버전. 지금은 1. 필드 의미가 바뀌면 올린다 |
| `source` | 문자열 | 예 | 입구 이름 (`claude-code`). 새 도구는 새 값 |
| `ts` | ISO 8601 (시간대 포함) | 예 | 기록 시각 |
| `role` | `user` · `assistant` · `subagent` · `unknown` | 예 | 누가 쓴 글인지 |
| `text` | 문자열 | 예 | 본문 (키·토큰은 가림, 기본 최대 20,000자). 형식이 다르면 빈 문자열 |
| `truncated` | 불리언 | 예 | 잘렸는지 |
| `session_id`, `project` | 문자열 | 아니요 | 세션, 작업 폴더 |
| `agent_type` | 문자열 | 아니요 | 서브에이전트 이름 |
| `raw` | 객체 | 아니요 | 입력이 예상과 다를 때만: 원문(가리고 자른 것). 나중에 변환 규칙을 고쳐 다시 읽는 데 쓴다 |

입구 하나 = 어댑터 하나 = `normalize()` 하나. 계약 테스트는 `tests/fixtures/<도구>/cases.json` + `tests/test_hook.py`.

### 결과 페이지 데이터 (`sim/results/page_data.json`)

최상위 키: `A`(중요도 실험) · `B`(용어 정규화) · `C`(근거 문장) · `notes` · `concepts` · `personas`.
만드는 곳은 `sim/make_page_data.py` 하나뿐이고, 쓰는 곳은 `web/page_template.html` 하나뿐이다.
`make_page_data.py --check`로 결과와 커밋된 파일이 같은지 확인한다.

### 클릭 카드 저장소 (SQLite, `kit/concept_store.py`)

`mentions(concept, ts, session, role, snippet)`, `cooc(a, b, n)`, `freq(concept, n)`, `notes(concept, definition, sources, updated)`.
인박스에서 언제든 다시 만들 수 있는 파생 데이터라 git에 올리지 않는다.

## 3. 품질 특성별 설계 결정 (ISO/IEC 25010 8가지 특성 기준)

| 특성 | 이 프로젝트에서의 결정 | 확인 방법 |
|---|---|---|
| 기능 적합성 | 시뮬레이터로 방식을 비교해 고른 공식(제안 C)만 쓴다. 페이지 숫자는 결과 파일에서만 나온다 | `make_page_data.py --check` |
| 성능 효율성 | 클릭 응답은 LLM 없이 SQLite 조회(카드 약 1KB). 웹 근거는 캐시 30일, 본문은 최대 1개. 형태소 분석기는 쓸 때만 로딩 | check_env의 카드 크기 |
| 호환성 | 인박스 형식을 버전(`v`)과 출처(`source`)로 고정해, 입구가 늘어도 처리부는 그대로 | 훅 fixture 테스트 |
| 사용성 | `dev.py` 명령 하나로 세팅·점검. 결과 페이지에서 한 줄 설치 명령 생성 | 새 클론에서 `python dev.py setup` |
| 신뢰성 | 훅은 실패해도 0으로 끝나고 아무것도 출력하지 않는다. 형식이 다르면 버리지 않고 `raw`로 보존 | `tests/test_hook.py` |
| 보안성 | 키·토큰 가리기, 대화 기록·DB는 git 제외, 밖으로 나가는 건 검색어(개념 이름)뿐 | 훅 fixture 가리기 케이스 |
| 유지보수성 | 책임별 폴더 분리, 코드 상자 원본은 `kit/` 하나, 생성물은 스크립트로만 만든다 | `build_page.py --check` |
| 이식성 | 버전 고정(`requirements.txt`), conda-forge 전용 환경, UTF-8·LF 고정, 경로는 스크립트 위치 기준 | CI (Windows·Ubuntu) |

## 4. 생명주기 단계별 산출물

| 단계 | 산출물 |
|---|---|
| 요구사항 | `README.md`(목적), `CLAUDE.md`(합의된 범위·다음 할 일) |
| 설계 | 이 문서, 데모 디자인 캔버스 |
| 구현 | `kit/`, `sim/`, `web/` |
| 테스트 | `tests/`, CI, 검증 문서(사용자 확인용), 학습 실험 기록(`docs/TRAINING.md`의 `experiments/`) |
| 배포 | `git clone` + `python dev.py setup`, 결과 페이지의 한 줄 설치 명령 |
| 유지보수 | `CHANGELOG.md`, 분기별 패키지 갱신(브랜치 → CI → main), fixture 추가 |

## 5. 변경 절차

1. 브랜치를 만든다.
2. 고친 뒤 `python dev.py check` → `모두 통과`.
3. 시뮬레이터·페이지 숫자가 바뀌는 변경이면 무엇이 왜 바뀌는지 적고 사용자 결정을 받는다 (실행 시간 값 제외).
4. 푸시 → CI 통과 → main에 합친다. `CHANGELOG.md`에 한 줄 남긴다.
