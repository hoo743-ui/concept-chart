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
| `dev.py` | 생명주기 작업 진입점 (setup·check·build·sim·serve) | — | 어디서나 |
| `.github/workflows/` | CI (Windows·macOS·Ubuntu, conda 설치 경로 포함) | 푸시 | GitHub |

의존 방향 (반대 방향 import 금지):

- `web/build_page.py` → `kit/*.py`(글자 그대로 읽기), `sim/results/page_data.json` — 둘 다 읽기만 한다.
- `sim/make_page_data.py` → `sim/concepts.py`, `sim/pipeline.py`, `sim/results/*` — `kit/`를 import하지 않는다.
- `kit/` → 다른 폴더에 의존하지 않는다 (사용자 PC에 파일 하나씩 복사해도 돌아가야 함). 특히 훅 설치기는 파일 하나로 완결된다.
- `experiments/`(학습 실험, 첫 실험 때 생김) → `sim/`·`kit/`를 읽기만 한다. 아무것도 `experiments/`를 import하지 않는다. 데이터는 `data/`(git 제외), 규칙은 `docs/TRAINING.md`.

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

### 로컬 서버 API (`kit/serve.py`, `http://localhost:8765`, 127.0.0.1만)

인박스를 1초마다 이어 읽어(읽은 위치는 DB `meta.offset`, 쓰다 만 줄은 다음에) 색인 DB(`~/.claude/concept-chart.sqlite`)에 넣는다.
위 클릭 카드 표 4개 + `forms(concept, form, n)` 표기, `sessions(id, last_ts)`, `term_sess(concept, session)`, `meta`. 인박스가 줄면(새 파일) 색인을 처음부터 다시 만든다(`notes`는 남김).

| 경로 | 돌려주는 것 |
|---|---|
| `GET /api/leaderboard?k=10` | `{generated, project, n_sessions, n_concepts, items:[{rank, id, label, score, sessions, turns, badge, recent_sessions, weekly, last_seen}]}` · `recent_sessions` = 최근 14일 세션 수, `weekly` = 최근 8주 주별 세션 수(오래된 주 → 이번 주) |
| `GET /api/concept/{id}?cursor=` | `{concept, label, summary, definition, chat_line:{ts, text, question}, sources:[{text, url}], note_status, related:[{id, label}], records:[{ts, role, snippet, question}] ×3, next_cursor}` · 없으면 404. `question` = 그 답변을 끌어낸 내 질문(최대 200자), 없으면 null |
| `GET /api/events` | SSE. 연결할 때 1번, 새 턴을 색인하거나 정의 수집이 끝날 때마다 `event: update` / `data: {"version": n}`. 15초마다 `: ping` |
| `GET /api/projects` | `{default, items:[{path, name, sessions, last_seen}], no_project_sessions}` 최근에 쓴 폴더부터. `default` = `--project` |
| `GET /api/status` | `{inbox, offset, turns, sessions, version}` |
| `GET /` | `--web` 폴더의 파일, 없으면 내장 간이 화면 |

- 개념 `id` = 표기를 소문자로 바꾸고 공백·`-`·`_`·`/`를 뺀 키. `label` = 가장 많이 나온 표기.
- 개념 추출: Kiwi 명사(붙어 쓴 명사·명사 파생 접미사는 한 덩어리, 영문·한자 포함) + 코드 속 import·pip·에러 이름. 개념 사전 없음, 일반 명사 불용어 목록(`STOP`)만. 숫자에 붙어 잘린 영문(`8GB`의 `GB`, `cu121`의 `cu`)과 단위, 소문자 주소 조각(`https`·`http`·`www`)은 뺀다. 대문자 `HTTP`·`HTTPS`, `GPT4`의 `GPT`는 남긴다.
- 점수 = 제안 C(안정성 균형, `sim/results/A.json`의 `balanced` = H 7일·β 0·γ 0·세션 단위)를 사전 없이 적용: `log1p(Σ 개념이 나온 세션의 2^(-경과일/7)) × (log((N+1)/(df+1))+1)`, N·df는 내 세션 기준.
- 배지: 최근 14일 vs 그 전 28일 세션 비율 z-검정 (`sim_A.py`와 같은 기준 1.64, 최소 2세션).
- 정의(`note_status`: `ready`·`none`·`pending`·`failed`): 카드를 열 때 정의가 없으면 응답은 바로 주고, 일꾼 스레드 1개가 뒤에서 `kit/fetch_sources.py`로 위키백과(한국어 → 영어) → SearXNG(`kit/searxng/`, `python dev.py searx up`, `--searx off`로 끔) 순서로 찾아 `notes`에 저장한 뒤 `update`를 보낸다. 출처 문장을 그대로 쓰고 LLM은 쓰지 않는다. 밖으로 나가는 건 개념 이름뿐. 30일 유효. 동음이의 안내 문서와 이름이 다른 위키백과 문서, `http(s)`가 아닌 링크는 받지 않는다. 실패(SearXNG 꺼짐 포함)는 저장하지 않고 60초 뒤 다시 시도, 429는 대기열 전체를 `Retry-After`(없으면 60초)만큼 쉰다.
- 폴더: 인박스의 `project`(훅이 기록하는 `cwd`)를 `sessions.project`에 저장한다. 세션 하나 = 폴더 하나(처음 기록된 값). `/api/leaderboard`·`/api/concept/{id}`의 `?project=경로`는 그 폴더와 하위 폴더로 좁히고, 빈 값은 전체, 없으면 `--project` 값을 쓴다. 순위의 N·df·세션·턴 수와 카드의 내 기록·대화 문장이 좁혀진다. 정의와 관련 개념은 폴더와 무관하다. 폴더 정보가 없는 세션은 전체에서만 보인다.
- 검색 결과 고르기(`fetch_sources.definition_sents`): "개념 + 은/는/이란"으로 시작하는 완결된 문장만 받는다(띄어쓰기 차이는 허용). 검색어는 내 대화에서 함께 나온 개념 2개 → 1개 → 이름만 순서로 넓히되, 어느 단계든 그 개념들이 하나도 없는 결과는 다른 뜻으로 보고 버린다. 맞는 문장이 없으면 `none`.
- 색인은 줄마다 커밋한다. 쓰기 잠금을 짧게 쥐어 정의 저장·조회를 막지 않고, 도중에 끊겨도 이어서 읽는다. 쓰기 잠금 안에서 읽은 위치를 다시 확인해 같은 DB를 두 프로세스가 읽어도 중복으로 세지 않는다. 쓸 수 없는 줄은 경고만 남기고 건너뛰고, DB 잠금과 패키지 없음은 위치를 옮기지 않고 다시 시도한다.
- 인박스 교체 감지: 파일이 읽은 위치보다 작거나, 앞 256바이트의 지문이 다르면 색인을 처음부터 다시 만든다.
- 훅은 인박스에 쓸 때 파일 끝 뒤쪽 1바이트를 잠근다(읽기를 막지 않음). 여러 세션이 동시에 끝나도 줄이 사라지지 않게 하고, 3초 안에 못 잠그면 기록을 버리지 않고 그냥 쓴다.
- 접속: `Host`가 `localhost`·`127.0.0.1`·`::1`이 아니면 403(DNS 리바인딩 방어). `--host`로 다른 주소를 지정하면 이 검사를 끈다. 같은 포트가 쓰이고 있으면 시작 때 안내하고 끝난다.
- 정의를 못 찾으면(`none`·`failed`) `chat_line`을 "내 대화에서 (출처 확인 전)"으로 구분해 보여 준다: 개념 이름이 실제로 든 AI 답변 문장 중 "개념 + 은/는/이란"으로 시작하는 문장, 없으면 최근 문장. 그런 문장도 없으면 `null`. 정의가 있으면 항상 `null`.
- 화면 표시: 기본은 `summary` 한 줄(`definition`에서 괄호 설명을 걷어 내고 최대 90자, 새 낱말을 만들지 않음). "더 알아보기"를 누르면 근거 문장·출처·관련 개념·내 기록을 펼친다.
- 기본으로 `assistant`·`subagent` 글만 분석한다 (`--roles`). CORS 헤더는 붙이지 않는다 (다른 사이트가 읽지 못하게).
- 질문(`user`): 형태소 분석·학습에 넣지 않고 원문을 `questions(id, session, ts, text)`에 저장한다. 답변의 `mentions.question`이 같은 세션의 가장 최근 질문을 가리킨다.
- `mentions`는 답변 하나에 개념 1행(처음 나온 문장). 순위는 `freq`·`term_sess`로 계산하므로 영향 없다. 표 구조가 바뀌면 `SCHEMA_VERSION`을 올린다 → 색인을 지우고 다시 만든다(`notes`는 남김).
- 메모리: Kiwi는 자식 프로세스(`--worker`)에만 올린다. 서버 본체는 1초마다 파일 크기만 보고, 완성된 새 줄이 있을 때 자식을 깨운다. 10분(`WORKER_IDLE`) 쉬면 자식을 끝내고, 다음 기록은 Kiwi 로딩 약 2.5초 뒤에 반영된다. 순위는 새 기록이 있거나 60초가 지났을 때만 다시 계산한다.
- 점검: `tests/test_serve.py` (check_env에 포함).

### 모델 경계 (백본을 지키는 규칙, `tests/test_boundary.py`가 `dev.py check`에서 강제)

학습 모델이나 파인튜닝이 들어와도 백본은 그대로여야 한다. 사용자 결정(11-09).

- **끼우는 자리는 하나:** `kit/serve.py`의 `ModelSlot`. `--model 모듈:함수`로 켜고 기본은 끔이다. 함수가 돌려주는 객체는 `canonical(표기) -> 개념 이름 또는 None`을 가진다. 그 외 방식으로 백본에 모델을 넣지 않는다.
- **없어도 동작:** 끄면 규칙(`norm_key`)만 쓰고 결과가 같다. 기본 설치(`requirements.txt`, `environment.yml`)에 학습 패키지를 넣지 않는다. 학습 패키지는 `requirements-ml.txt`로 따로 둔다.
- **고장 나도 계속:** 불러오기 실패, 예외, 이상한 값, 제한 시간 초과(표기당 5초)면 그 프로세스에서 모델을 끄고 규칙으로 색인을 계속한다.
- **격리:** 모델은 분석 프로세스에만 올린다. 서버 본체는 불러오지 않는다. 분석 프로세스의 부모 통신은 stdout과 분리돼 있어 모델 출력이 섞여도 깨지지 않는다.
- **의존 방향:** `kit/`는 학습 패키지와 `experiments/`·`sim/`·`web/`을 불러오지 않는다. 아무것도 `experiments/`를 불러오지 않는다. 모델 코드는 `kit/` 밖에 두고 `PYTHONPATH`로 지정한다.
- **결과 교체는 명시적으로:** 모델을 바꾸면(`--model` 값 변경) 색인을 인박스에서 다시 만든다. 인박스와 저장된 정의는 그대로다. 기본값을 바꾸는 채택은 `docs/TRAINING.md` 8절 기준과 사용자 결정으로만 한다.

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
| 이식성 | 버전 고정(`requirements.txt`), conda-forge 전용 환경, UTF-8·LF 고정, 경로는 스크립트 위치 기준 | CI (Windows·macOS·Ubuntu) |

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
