# 개념 차트 (concept-chart)

Claude Code 대화에서 자주 나온 개념을 중요도 순으로 보여 주고, 개념을 누르면 출처가 붙은 공부 노트로 펼쳐 주는 개인 학습 도구.
이 저장소에는 모델 선택 시뮬레이터, Claude Code 입력 수집 키트, 결과 페이지가 들어 있다.

> **프로토타입:** `python dev.py app` → http://localhost:8765. 기획 `docs/WORKSHEET.md`, 결정 근거 `docs/DECISION_LOG.md`, 화면·서버 계약 `docs/API.md`, 오류 방지 규칙 `docs/CONSTRAINTS.md`.
>
> 다른 PC에서 처음 받는다면 **[SETUP.md](SETUP.md)**, 복사해서 쓰는 명령만 보려면 **[docs/COMMANDS.md](docs/COMMANDS.md)**, 구조와 설계 이유는 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## 빠른 시작

도구(conda·git·Claude Code) 설치는 [SETUP.md](SETUP.md) 1단계. 그다음:

```bash
gh repo clone hoo743-ui/concept-chart     # 또는 git clone https://github.com/hoo743-ui/concept-chart.git
cd concept-chart
python3 dev.py setup                      # Windows(Anaconda Prompt): python dev.py setup
conda activate concept-chart
```

`python dev.py setup`이 conda 환경 `concept-chart`(Python 3.13 + 패키지 전부)를 만들고 전체 점검까지 돌린다. 마지막에 `결과: 모두 통과`가 나오면 끝.
결과 페이지는 `web/dist/index.html`을 브라우저로 열면 된다.

## 폴더 구조

```
concept-chart/
├─ dev.py                       작업 진입점: setup · check · build · sim (표준 라이브러리만)
├─ kit/                         실제로 쓰는 코드 (사용자 PC에서 실행)
│  ├─ install_concept_hook.py   Claude Code 훅 설치기 (대화 → ~/.claude/concept-inbox.jsonl)
│  ├─ loader_cell.py            노트북 첫 셀: 인박스 읽기·정제
│  ├─ concept_store.py          개념 클릭 카드 (SQLite, LLM 호출 없음)
│  ├─ fetch_sources.py          근거 수집: 캐시 → 위키백과 → SearXNG → 본문 1개
│  └─ verify_note.py            노트 검증 에이전트 (문장별 근거 대조)
├─ sim/                         시뮬레이터 (방식 비교 실험)
│  ├─ concepts.py               개념 64개·표기 변형·페르소나·정의문 데이터
│  ├─ textgen.py                가상 사용자 대화 생성, 정답(앞으로 2주 관심도)
│  ├─ pipeline.py               토크나이저 T0~T4, 개념 사전 매칭, 문장 유형 표지
│  ├─ sim_A.py · sim_B.py · sim_C.py   중요도 · 용어 정규화 · 근거 문장 비교
│  ├─ make_page_data.py         A·B·C 결과 → results/page_data.json
│  └─ results/                  결과 JSON, badge_eval.json(배지 비교표 기록값)
├─ web/                         결과 페이지
│  ├─ page_template.html        틀 (코드 상자·데이터는 빌드할 때 채움)
│  ├─ build_page.py             틀 + kit 코드 + page_data.json → dist/index.html
│  └─ dist/index.html           완성된 페이지 (게시본과 같은 파일)
├─ tests/
│  ├─ check_env.py              환경 점검 + 스모크 테스트 (아래 테스트 포함)
│  ├─ test_hook.py              훅 어댑터 계약 테스트 (fixtures/claude_code/cases.json)
│  └─ check_page.js · check_setup.js   페이지 렌더·설정 시트 점검 (jsdom)
├─ docs/ARCHITECTURE.md         구성·데이터 계약·품질 특성별 설계·생명주기
├─ docs/TRAINING.md             학습 가이드라인 (데이터 → 전처리 → 분할 → 학습 → 시험 → 채택)
├─ docs/COMMANDS.md             명령어 모음 (세팅·매일·커밋·학습 실험, Mac 기준)
├─ .github/workflows/ci.yml     푸시마다 Windows·macOS·Ubuntu 점검 + conda 설치 경로 점검
├─ CLAUDE.md                    Claude Code로 이어서 작업할 때 읽는 현황·규칙
├─ CHANGELOG.md                 변경 기록
├─ requirements.txt             파이썬 패키지 (버전 고정)
├─ environment.yml              conda 환경 (Python 3.13, conda-forge)
└─ package.json                 (선택) 페이지 점검용 jsdom
```

## 자주 쓰는 명령

저장소 폴더에서, `concept-chart` 환경을 켠 상태로 실행한다.

| 하는 일 | 명령 | 걸리는 시간 (참고) |
|---|---|---|
| 전체 점검 | `python dev.py check` | 20초 |
| 결과 페이지 다시 만들기 | `python dev.py build` | 3초 |
| 시뮬레이터 다시 실행 + build | `python dev.py sim` | 1분 |
| 환경 갱신 (패키지가 바뀌었을 때) | `python dev.py setup` | 수 분 |
| Claude Code 훅 설치 → 점검 | `python kit/install_concept_hook.py` → `... --test` | 몇 초 |
| 훅 제거 | `python kit/install_concept_hook.py --uninstall` | |

개별 단계: `python sim/make_page_data.py`, `python web/build_page.py`(둘 다 `--check`는 최신인지만 확인), `python tests/test_hook.py`.

## 데이터 흐름

```
sim_A·B·C.py ──▶ sim/results/A·B·C.json ─┐
sim/results/badge_eval.json (기록값) ─────┼──▶ sim/make_page_data.py (반올림·축약)
sim/concepts.py (노트·개념·페르소나) ─────┘            │
                                                       ▼
              sim/results/page_data.json ──┐
kit/*.py (코드 상자 원본) ─────────────────┼──▶ web/build_page.py ──▶ web/dist/index.html
web/page_template.html ────────────────────┘
```

- 코드는 `kit/` 쪽만 고치면 된다. 페이지 안 코드 상자와 한 줄 설치 명령은 빌드할 때 `kit/`에서 다시 채운다.
- 시뮬레이터는 시드가 고정돼 있어서, 같은 패키지 버전으로 다시 돌리면 같은 숫자가 나온다 (실행 시간 값만 다름).

### 알아 둘 점

- **배지 방식 비교표는 기록값이다.** 페이지의 '추세 배지 방식 비교'(Holt 비율 vs z-검정, n=1,285) 표를 만든 평가 코드는 저장소에 없다. 숫자는 `sim/results/badge_eval.json`에 그대로 두었고, 다시 계산하려면 평가 절차를 새로 정해야 한다 (숫자가 바뀔 수 있음).
- **새 용어 기준값(`NEW_TERM_MIN_IDF = 3.6`)은 맞춰 찾은 값이다.** 원래 값 기록이 없어서, 저장돼 있던 결과와 30주 모두 똑같이 나오는 구간(3.56~3.66) 안에서 골랐다.
