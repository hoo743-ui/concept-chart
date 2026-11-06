# 개념 차트 (concept-chart)

Claude Code 대화에서 자주 나온 개념을 중요도 순으로 보여 주고, 개념을 누르면 출처가 붙은 공부 노트로 펼쳐 주는 개인 학습 도구.
이 저장소에는 모델 선택 시뮬레이터, Claude Code 입력 수집 키트, 결과 페이지가 들어 있다.

> 다른 PC에서 처음 받는다면 **[SETUP.md](SETUP.md)** 부터 보면 된다.

## 빠른 시작 (Windows · Anaconda Prompt)

```powershell
git clone https://github.com/hoo743-ui/concept-chart.git
cd concept-chart
conda env create -f environment.yml
conda activate concept-chart
python tests/check_env.py
```

마지막 줄이 `모두 정상`이면 끝. 결과 페이지는 `sim/out/index.html`을 브라우저로 열면 된다.

## 폴더 구조

```
concept-chart/
├─ sim/                         시뮬레이터 + 결과 페이지
│  ├─ concepts.py               개념 64개·표기 변형·페르소나·정의문 데이터
│  ├─ textgen.py                가상 사용자 대화 생성, 정답(앞으로 2주 관심도) 계산
│  ├─ pipeline.py               토크나이저 T0~T4, 개념 사전 매칭
│  ├─ sim_A.py                  중요도 산정 방식 비교          → results/A.json
│  ├─ sim_B.py                  용어 정규화(동의어 병합) 비교   → results/B.json
│  ├─ sim_C.py                  공부 노트 근거 문장 선택 비교   → results/C.json
│  ├─ page_template.html        결과 페이지 틀 (코드 상자·데이터는 빌드할 때 채움)
│  ├─ build_page.py             틀 + kit 코드 + page_data.json → out/index.html
│  ├─ results/                  시뮬레이터 결과, page_data.json(페이지용 데이터)
│  └─ out/index.html            결과 페이지 (게시본과 같은 파일)
├─ kit/                         실제로 쓰는 코드
│  ├─ install_concept_hook.py   Claude Code 훅 설치기 (대화 → ~/.claude/concept-inbox.jsonl)
│  ├─ loader_cell.py            노트북 첫 셀: 인박스 읽기·정제
│  ├─ concept_store.py          개념 클릭 카드 (SQLite, LLM 호출 없음)
│  ├─ fetch_sources.py          근거 수집: 캐시 → 위키백과 → SearXNG → 본문 1개
│  └─ verify_note.py            노트 검증 에이전트 (문장별 근거 대조)
├─ tests/
│  ├─ check_env.py              환경 점검 + 키트 스모크 테스트
│  ├─ check_page.js             페이지 렌더·조작 점검 (jsdom)
│  └─ check_setup.js            설정 시트·한 줄 설치 명령 점검 (jsdom)
├─ requirements.txt             파이썬 패키지 (버전 고정)
├─ environment.yml              conda 환경 (Python 3.13, conda-forge)
└─ package.json                 (선택) 페이지 점검용 jsdom
```

## 자주 쓰는 명령

저장소 폴더에서, `concept-chart` 환경을 켠 상태로 실행한다.

| 하는 일 | 명령 | 걸리는 시간 (참고) |
|---|---|---|
| 환경 점검 | `python tests/check_env.py` | 15초 |
| 결과 페이지 다시 만들기 | `python sim/build_page.py` | 1초 |
| 페이지가 최신인지 확인 | `python sim/build_page.py --check` | 1초 |
| 시뮬레이터 실행 | `python sim/sim_A.py` · `sim_B.py` · `sim_C.py` | 35초 · 15~35초 · 10초 |
| Claude Code 훅 설치 → 점검 | `python kit/install_concept_hook.py` → `... --test` | 몇 초 |
| 훅 제거 | `python kit/install_concept_hook.py --uninstall` | |
| 페이지 자동 점검 (선택, Node 18+) | `npm ci` → `npm test` | 5초 |

## 데이터 흐름

```
sim_A·B·C.py ──▶ sim/results/A·B·C.json
                        │  페이지용 가공 (반올림·축약·추세 배지)  ※ 아래 '알아 둘 점'
                        ▼
              sim/results/page_data.json ──┐
kit/*.py (코드 상자 원본) ─────────────────┼──▶ sim/build_page.py ──▶ sim/out/index.html
sim/page_template.html ────────────────────┘
```

- 코드는 `kit/` 쪽만 고치면 된다. 페이지 안 코드 상자와 한 줄 설치 명령은 빌드할 때 `kit/`에서 다시 채운다.
- 시뮬레이터는 시드가 고정돼 있어서, 같은 패키지 버전으로 다시 돌리면 같은 숫자가 나온다 (실행 시간 값만 다름).

### 알아 둘 점

A·B·C 결과를 `page_data.json`으로 바꾸는 가공 단계 중 **추세 배지(두 비율 z-검정)와 새 용어 목록**은 아직 스크립트로 정리되지 않았다.
그래서 `sim_A.py`를 다시 돌리면 `A.json`에서 배지 관련 필드가 빠진다. 페이지는 `page_data.json`을 쓰므로 영향은 없고, 원래 파일로 되돌리려면:

```powershell
git checkout sim/results/A.json
```
