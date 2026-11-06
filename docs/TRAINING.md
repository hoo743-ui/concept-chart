# 학습 가이드라인 — 데이터 받기부터 채택까지

실제 데이터셋으로 모델을 학습해 성능을 계속 확인할 때 따르는 순서와 규칙이다.
Claude Code는 이 문서와 `CLAUDE.md`를 먼저 읽고 따른다. VS Code에서 직접 확인할 지점은 각 단계의 **VS Code 확인**과 5절에 모았다 (VS Code 세팅은 `SETUP.md` 5단계).

목표는 하나다: **지금 방식보다 실제 데이터에서 나아졌는지를, 같은 기준으로, 반복해서 확인한다.**
학습 손실을 끝까지 내리는 것이 목표가 아니다. 검증 지표가 더 나아지지 않으면 멈춘다.

## 0. 한눈에 보기

| 단계 | 하는 일 | 남는 것 | 통과 기준 |
|---|---|---|---|
| 1 받기 | 원본을 그대로 보관, 출처 기록 | `data/raw/`, `experiments/DATA.md` | 원본을 고치지 않았다 |
| 2 살펴보기 | 크기·빈 값·중복·라벨 비율·길이·문자 정규화 | `DATA.md`에 메모 | 이상한 점을 목록으로 적었다 |
| 3 전처리 | 우리 형식(B 용어 쌍, C 후보 문장)으로 바꾸기 | `data/processed/` | 데이터 계약 점검 통과 |
| 4 분할 | 개념 단위 학습·검증·시험, 시드 고정 | `experiments/splits/` | 세트 사이 개념 겹침 0 |
| 5 기준선 | 지금 방식 + 사전학습 모델 그대로 | `experiments/<날짜>-baseline/` | 같은 분할·같은 지표 |
| 6 학습 | epoch마다 검증, 가장 좋은 것만 저장, 조기 종료 | `log.csv`, `models/`(git 제외) | 학습 곡선을 봤다 |
| 7 시험 | 시험 세트로 한 번만 | `metrics.json` | 기준선 대비 차이 + 95% 구간 |
| 8 기록·채택 | 한 줄 기록, 사용자가 결정 | `experiments/RESULTS.md` | 8절 채택 기준 |

## 1. 무엇을 학습하나 (시작 전 기대치)

시뮬레이터는 모델이 아니라 시험장이다. 정답이 우리가 만든 가상 데이터라서, 시뮬레이터 점수가 오르는 것과 실제로 좋아지는 것은 다르다. 개선은 **실제 데이터의 시험 세트**에서만 판단한다.

| 부품 | 지금 방식 (시뮬레이터 점수) | 학습으로 바꿀 후보 | 기대 |
|---|---|---|---|
| B 용어 정규화 (같은 개념인가) | 로지스틱 회귀 12개 특징: AUC 0.824, 어려운 오답 오판 17.9%, 한↔영 재현율 69.3% | 사전학습 다국어 인코더 미세조정 (쌍 분류 또는 대조 학습) | 높음 — 한↔영 재현율이 지금의 약점 |
| C 근거 문장 (정의문 고르기) | 로지스틱 회귀 13개 특징: MRR 0.975, Hit@1 0.967 (개념 30개, 가상 문장) | 사전학습 한국어 인코더 분류기·재순위 | 중간 — 시뮬레이터는 이미 천장이라 실제 웹 문장에서만 확인 가능 |
| A 중요도 순위 | 제안 C 공식: NDCG@10 0.845, 일반어 침입 4.8% (GBM 0.910이지만 안정성 때문에 보류) | 학습형 랭커 | 낮음 — 정답(사용자 반응) 데이터가 쌓이기 전에는 근거가 없다 |

## 2. 폴더 구조 (첫 실험에서 만든다 — 지금은 없음)

```
data/                          git 제외 (크고, 라이선스·개인정보가 있을 수 있음)
├─ raw/                        받은 그대로. 고치지 않는다
└─ processed/                  우리 형식: B_pairs.jsonl, C_sents.jsonl
experiments/                   기록만 커밋
├─ DATA.md                     데이터 이름·출처·라이선스·받은 날짜·파일 SHA-256·행 수·살펴본 결과
├─ common.py                   불러오기·계약 점검·분할·지표 (실험들이 같이 씀)
├─ splits/B.json, C.json       고정한 분할 (개념 목록 + 시드)
├─ <날짜>-<이름>/
│  ├─ train.py                 이 실험의 코드
│  ├─ config.json              데이터 해시, 모델, 하이퍼파라미터, 시드, git 커밋, 패키지 버전
│  ├─ log.csv                  epoch별 train_loss · val_loss · val_metric · 걸린 시간
│  ├─ curve.png                학습 곡선 (선택)
│  └─ metrics.json             검증·시험 지표, 기준선 대비 차이와 95% 구간, 추론 속도·메모리
└─ RESULTS.md                  실험마다 한 줄
models/                        git 제외. 체크포인트 (<실험 이름>-best.pt)
```

- `.gitignore`에 `/data/`, `models/`, `*.pt` 등이 이미 들어 있다. 커밋 전에 `git status`로 데이터·가중치가 안 올라가는지 본다.
- 의존 방향: `experiments/` → `sim/`(`concepts.py`, `pipeline.py`)과 `kit/`(같은 전처리 함수)를 **읽기만** 한다. 아무것도 `experiments/`를 import하지 않는다 (`docs/ARCHITECTURE.md`).
- 실험 결과는 `sim/results/`나 `page_data.json`에 섞지 않는다. 결과 페이지 숫자는 사용자 결정 없이 바꾸지 않는다.
- 파일은 `encoding="utf-8"`로 열고, 경로는 `pathlib.Path(__file__)` 기준으로 잡는다 (`CLAUDE.md` 규칙).

## 3. 단계별 가이드

### 3-1. 받기

- 원본은 `data/raw/<데이터 이름>/`에 받은 그대로 둔다. 고칠 일이 있으면 항상 코드로 `data/processed/`에 새로 만든다 (원본에서 결과를 언제든 다시 만들 수 있게).
- `experiments/DATA.md`에 적는다: 이름, 출처 URL, 라이선스(재배포·상업 이용 가능 여부), 받은 날짜, 파일별 SHA-256(`shasum -a 256 <파일>`), 행 수.
- 내 대화 기록(`~/.claude/concept-inbox.jsonl`)을 학습에 쓰면 개인 데이터다. `data/`에만 두고, 훅과 같은 비밀값 가리기 규칙(`kit/install_concept_hook.py`의 `SECRETS`)을 거친 것만 쓴다.

**VS Code 확인:** 탐색기에서 CSV·Parquet·JSONL 파일 우클릭 → **Open in Data Wrangler** → 열 이름·형식·앞부분.

### 3-2. 살펴보기 (전처리 전에)

| 볼 것 | 왜 |
|---|---|
| 행·열 수, 열별 빈 값 | 빠진 라벨·문장을 버릴지 채울지 정한다 |
| 라벨 비율 (0/1), B는 `kind`별 개수 | 한쪽이 너무 적으면 손실 가중치·지표 해석이 달라진다 |
| 중복 (정규화한 뒤 기준) | 같은 예가 학습과 시험에 갈려 들어가면 점수가 부풀려진다 |
| 문자 정규화 (NFC인지) | Mac 파일 이름 등에서 온 한글은 자모가 분리된 NFD일 수 있다. NFD 한글은 `[가-힣]` 정규식에 걸리지 않는다 |
| 라벨별 문장 길이 분포 (C) | 정의문이 유독 길거나 짧으면 모델이 길이만 보고 맞힐 수 있다 (시뮬레이터 C의 '문장 길이 빼기' 비교와 같은 점검) |
| 개념 수, 개념당 예 수 | 개념 단위 분할이 가능한지 (개념이 적으면 교차검증, 3-4) |
| 한·영 표기 섞인 정답 쌍 수 (B) | 한↔영 재현율을 따로 잴 만큼 있는지 |

```python
# %% 살펴보기 (B 예시 — C도 같은 방식)
import pathlib, unicodedata
import pandas as pd
here = pathlib.Path(globals().get("__file__", pathlib.Path.cwd() / "_")).resolve().parent
ROOT = next(p for p in [here, *here.parents] if (p / "dev.py").exists())   # 레포 폴더 (Interactive Window에서도)
df = pd.read_json(ROOT / "data/processed/B_pairs.jsonl", lines=True, encoding="utf-8")
print(df.shape)                                    # 행·열 수
print(df.isna().sum())                             # 열별 빈 값
print(df["label"].value_counts(normalize=True))    # 라벨 비율
print(df["kind"].value_counts())                   # pos / hard / rand
nfd = df["a"].map(lambda s: s != unicodedata.normalize("NFC", s)).sum()
print(nfd, "NFC가 아닌 문자열")                    # 0이 아니면 전처리에서 NFC로
df.sample(20, random_state=0)                      # 눈으로 20개
```

원본이 우리 형식이 아니면 같은 점검을 원본 열 이름으로 먼저 하고, 3-3 뒤에 위 코드로 한 번 더 한다.

**VS Code 확인:** 셀 출력의 숫자, 마지막 줄 표 → 변수 창에서 `df` 옆 Data Wrangler 버튼 → 열 통계(빈 값·고유값·분포).

### 3-3. 전처리 (우리 파이프라인 형식으로)

순서대로 한다. 같은 처리를 실제 사용 경로와 똑같이 해야 학습과 사용의 입력이 같아진다.

1. UTF-8로 읽고(`encoding="utf-8"`, BOM이 있으면 `utf-8-sig`) NFC 정규화(`unicodedata.normalize("NFC", s)`), 앞뒤 공백 제거, 연속 공백은 하나로.
2. (대화 데이터만) 비밀값 가리기 (3-1).
3. 용어 키: `norm_key()` (`sim/pipeline.py`: 소문자 + 공백·`-`·`_`·`/` 제거). 중복 판단과 개념 매핑에만 쓰고, 모델 입력은 원래 표기를 둔다 (모델이 표기 차이를 배워야 하므로).
4. 개념 id 붙이기: 데이터에 개념(동의어 묶음) 정보가 있으면 그것을 쓰고, 없으면 `oracle_concept()` (`sim/pipeline.py`, 개념 사전 64개 기준)로 매핑한다. 매핑 안 되는 용어는 버리지 말고 개수와 예를 `DATA.md`에 적는다.
5. 문장 나누기 (C): 실제 근거 수집과 같은 `split_sents()` (`kit/fetch_sources.py`: `.`·`!`·`?`·`다`·`요` 뒤 공백에서 나누고 10자 이하는 버림)를 쓴다.
6. 중복 제거: B는 `(norm_key(a), norm_key(b))`를 순서 없는 쌍으로, C는 `(term, 정규화한 문장)`으로. 분할 **전에** 한다.
7. B 어려운 오답: 발음·표기가 비슷하지만 다른 개념인 쌍을 `kind: "hard"`로 넣는다 (`sim/concepts.py`의 `HARD_NEG` 39쌍이 예). 이게 있어야 '어려운 오답 오판율'을 잴 수 있다.
8. 아래 계약 점검을 통과하면 `data/processed/`에 저장한다.

**데이터 계약** (한 줄 = JSON 하나, UTF-8). 시뮬레이터 B의 쌍 `(a, b, label, kind, 개념)`과 C의 `(개념, 질의, 후보 문장, 정답 여부)` 구조를 그대로 옮긴 것이다.

`data/processed/B_pairs.jsonl`

| 필드 | 형식 | 설명 |
|---|---|---|
| `a`, `b` | 문자열 | 두 용어 (원래 표기) |
| `label` | 0 / 1 | 같은 개념이면 1 |
| `kind` | `pos` / `hard` / `rand` | 정답 쌍 / 비슷하지만 다른 개념 / 무작위 다른 개념 |
| `concept_a`, `concept_b` | 문자열 | 개념 id (분할 기준) |
| `source` | 문자열 | 어느 데이터에서 왔는지 |

`data/processed/C_sents.jsonl`

| 필드 | 형식 | 설명 |
|---|---|---|
| `qid` | 문자열 | 질의 하나 (용어 하나와 그 후보 문장 묶음) |
| `term` | 문자열 | 찾는 용어 |
| `concept` | 문자열 | 개념 id (분할 기준) |
| `sentence` | 문자열 | 후보 문장 |
| `label` | 0 / 1 | 그 용어의 정의문이면 1 |
| `source_url` | 문자열 | 문장 출처 |

계약 점검 (`experiments/common.py`에 함수로 두고 매번 돈다):

- `label`은 0 또는 1, 빈 문자열 없음, 모든 문자열이 NFC.
- B: `label == 1`이면 `concept_a == concept_b`, `label == 0`이면 다르다.
- C: `qid`마다 정답(`label == 1`)이 1개 이상 (없으면 MRR을 계산할 수 없다 — `sim/sim_C.py`의 `rank_metrics`와 같은 정의).
- 개수 출력: 전체, 라벨별, `kind`별, 개념 수.

**VS Code 확인:** `data/processed/` 파일을 Data Wrangler로 열어 20개를 눈으로 본다 (표기·라벨이 맞는지). 계약 점검 출력이 통과인지.

### 3-4. 분할 (한 번 만들고 고정)

- **개념 단위로** 학습 70 / 검증 15 / 시험 15 (제안값). 같은 개념이 두 세트에 걸치면 외운 것을 맞힌 것으로 쳐서 점수가 부풀려진다 (시뮬레이터의 GroupKFold와 같은 이유).
- B의 다른 개념 쌍(`hard`·`rand`)은 **두 개념이 모두 같은 세트일 때만** 그 세트에 넣는다. 걸치는 쌍은 버리고 개수를 적는다. 시뮬레이터 B는 `a` 쪽 개념으로만 묶었으니 이쪽이 더 엄격하다.
- 시드를 고정하고 `experiments/splits/`에 저장해 커밋한다. 이후 바꾸지 않는다.
- 개념이 적으면 (예: 검증·시험 세트에 개념이 20개도 안 되면) 시험 세트는 그대로 따로 두고, 나머지에서 개념 단위 5겹 교차검증(`GroupKFold(n_splits=5)`, 시뮬레이터와 같음)으로 고른다.
- 표기 변형 추가 같은 데이터 늘리기는 분할 **뒤에**, 학습 세트 안에서만 한다.
- 시험 세트는 마지막 판정에만 쓴다. 하이퍼파라미터·조기 종료는 검증 세트로만 고른다.

```python
# %% 개념 단위 분할 (B 예시 — C는 concept 한 열로 같은 방식)
import json, random
concepts = sorted(set(df["concept_a"]) | set(df["concept_b"]))
random.Random(42).shuffle(concepts)                # 시드 고정
n = len(concepts)
split = {"seed": 42,
         "train": sorted(concepts[: int(n * 0.70)]),
         "val":   sorted(concepts[int(n * 0.70): int(n * 0.85)]),
         "test":  sorted(concepts[int(n * 0.85):])}
assert not (set(split["train"]) & set(split["val"]) or set(split["train"]) & set(split["test"])
            or set(split["val"]) & set(split["test"])), "세트 사이에 개념이 겹친다"
out = ROOT / "experiments/splits/B.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(split, ensure_ascii=False, indent=1), encoding="utf-8")

def part(df, names):                               # 두 개념이 모두 같은 세트에 있는 쌍만
    s = set(names)
    return df[df["concept_a"].isin(s) & df["concept_b"].isin(s)]
tr, va, te = (part(df, split[k]) for k in ("train", "val", "test"))
print(len(tr), len(va), len(te), "버린 쌍(세트에 걸침):", len(df) - len(tr) - len(va) - len(te))
```

**VS Code 확인:** 출력의 세 숫자와 버린 쌍 수, `assert` 통과. 소스 제어(Source Control) 창에 `experiments/splits/B.json`이 새 파일로 보이는지.

### 3-5. 기준선 (학습 전에)

같은 분할·같은 지표로 세 줄을 만든다.

1. **지금 방식**: B는 로지스틱 회귀 12개 특징, C는 로지스틱 회귀 13개 특징. 학습 세트로 학습, 임계값은 검증 세트에서.
2. **사전학습 모델 그대로** (학습 없이, 예: 문장 벡터 코사인 유사도). 미세조정이 정말 이득인지 알려면 필요하다.
3. **미세조정** — 이것이 실험이다 (3-6).

주의: `sim/sim_B.py`의 `features()`와 `sim/sim_C.py`의 `feat()`는 지금 스크립트 안에 있어서 바로 import되지 않는다 (불러오면 시뮬레이터 전체가 돈다). 첫 실험 때 함수만 모듈로 꺼내는 작업이 필요하다. 별도 커밋으로 하고 `python dev.py check`로 페이지 숫자가 그대로인지 확인한다.

지표 (시뮬레이터와 같은 정의):

| 부품 | 지표 | 메모 |
|---|---|---|
| B | AUC, AP (점수 기준) / F1·정밀도·재현율 (임계값 기준) / 어려운 오답 오판율 = `hard` 쌍 중 같다고 잘못 판정한 비율 / 한↔영 재현율 = 한쪽은 한글, 다른 쪽은 로마자인 정답 쌍 중 맞힌 비율 | 임계값은 검증 세트에서 F1이 가장 큰 값 (시뮬레이터는 학습 fold에서 골랐다) |
| C | MRR, Hit@1, Hit@3 (`qid`마다 정답 문장의 순위) | 동점은 원래 순서 유지 (`argsort(kind="stable")`) |

### 3-6. 학습 (epoch 반복 + 과적합 막기)

**기본 원칙**

- 처음부터 학습하지 않고 사전학습 인코더를 미세조정한다 (데이터가 적을 때 과적합을 줄인다). 어떤 모델을 쓸지는 첫 실험 계획에서 정하고 사용자 승인을 받는다.
- 매 epoch: 학습 → 검증 세트로 손실과 **결정 지표** → `log.csv`에 한 줄. 결정 지표는 시작 전에 하나로 정한다 (제안: B는 AP, C는 MRR).
- 결정 지표가 가장 좋았던 epoch의 가중치만 `models/`에 저장한다.
- 결정 지표가 `patience`번 연속 나아지지 않으면 멈춘다 (조기 종료). 시험에는 가장 좋았던 epoch을 쓴다.
- 손실 함수: B는 쌍 분류(이진 교차 엔트로피) 또는 대조 학습, C는 문장 분류(이진 교차 엔트로피) 또는 순위 손실.

**시작값** (제안 — 바꿀 때는 검증 세트로만 판단하고 모두 기록)

| 항목 | 시작값 | 메모 |
|---|---|---|
| 최대 epoch | 10 | 상한일 뿐, 보통 조기 종료가 먼저 멈춘다 |
| patience / min_delta | 3 / 0.001 | 결정 지표 기준 |
| 옵티마이저 | AdamW | |
| 학습률 | 2e-5 (1e-5 ~ 5e-5 안에서) | 미세조정은 작게 |
| weight decay | 0.01 | |
| 배치 크기 | 16 (메모리 보고 32) | |
| warmup | 전체 스텝의 10% | 처음에 학습률을 서서히 올림 |
| gradient clipping | 1.0 | |
| 시드 | 42, 그리고 다른 시드 2개로 반복 | 차이가 시드 운인지 확인 |

**학습 전 점검 두 가지** (짧게 끝난다)

1. 작은 묶음 외우기: 학습 예 32개로 여러 epoch → 학습 손실이 거의 0까지 내려가야 한다. 안 내려가면 라벨·입력·손실 연결 버그다.
2. 짧게 1 epoch: 데이터 1~5%로 1 epoch → 시간·메모리를 보고 전체 시간을 추정해 계획에 적는다.

**과적합 신호와 대응** (`log.csv`, 학습 곡선으로 본다)

| 신호 | 뜻 | 대응 (위에서부터 차례로) |
|---|---|---|
| 학습 손실 ↓, 검증 손실 ↑ | 외우기 시작 | 조기 종료가 처리한다. 매번 일찍 멈추면 학습률을 낮춘다 |
| 학습 지표와 검증 지표 차이가 epoch마다 커짐 | 과적합 | weight decay 올리기 → 아래 층 고정(위 몇 층만 학습) → 학습 세트 안에서 데이터 늘리기 |
| 검증 지표가 epoch마다 크게 오르내림 | 검증 세트가 작거나 학습률이 큼 | 학습률 낮추기, 교차검증, 시드 여러 개 평균 |
| 학습 손실도 안 내려감 | 과소적합 또는 버그 | 작은 묶음 외우기 점검부터 |
| 시험 점수가 검증보다 크게 낮음 | 검증 세트에 맞춰 너무 많이 고름 | 고르는 횟수를 줄인다. 기록에 남긴다 |

**하이퍼파라미터 고르기**

- 검증 세트로만. 시도한 것은 전부 기록한다 (가장 좋은 것만 남기지 않는다).
- 한 번에 하나씩 바꾼다. 격자는 작게 (예: 학습률 3개 × 시드 3개).
- 라벨 불균형이 크면 손실 가중치(`pos_weight`) 또는 표본 비율 조정 중 하나를 고르고 `config.json`에 적는다.

```python
# %% 조기 종료 (점수는 클수록 좋은 것: AP, MRR)
class EarlyStop:
    def __init__(self, patience=3, min_delta=0.001):
        self.patience, self.min_delta = patience, min_delta
        self.best, self.bad = float("-inf"), 0
    def step(self, score):
        if score > self.best + self.min_delta:
            self.best, self.bad = score, 0
            return "improved"
        self.bad += 1
        return "stop" if self.bad >= self.patience else "wait"

# %% epoch 루프 뼈대 (torch) — model, loaders, loss_fn, evaluate는 실험마다 정의
import csv, time, torch
device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)
opt = torch.optim.AdamW(model.parameters(), lr=2e-5, weight_decay=0.01)
stop, best_path = EarlyStop(patience=3), ROOT / "models" / f"{run_name}-best.pt"
best_path.parent.mkdir(exist_ok=True)
with open(run_dir / "log.csv", "w", newline="", encoding="utf-8") as f:
    log = csv.writer(f)
    log.writerow(["epoch", "train_loss", "val_loss", "val_metric", "sec"])
    for epoch in range(1, 11):                     # 최대 10 epoch
        t0, total = time.time(), 0.0
        model.train()
        for batch in train_loader:
            opt.zero_grad()
            loss = loss_fn(model, batch, device)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += loss.item()
        model.eval()
        with torch.no_grad():
            val_loss, val_metric = evaluate(model, val_loader, device)   # 결정 지표 (B: AP, C: MRR)
        log.writerow([epoch, total / len(train_loader), val_loss, val_metric, round(time.time() - t0, 1)])
        f.flush()
        result = stop.step(val_metric)
        if result == "improved":
            torch.save(model.state_dict(), best_path)
        if result == "stop":
            break
model.load_state_dict(torch.load(best_path, map_location=device))   # 시험에는 가장 좋았던 epoch

# %% 학습 곡선 (VS Code Interactive Window에 그려진다)
import pandas as pd
import matplotlib.pyplot as plt
log = pd.read_csv(run_dir / "log.csv")
fig, ax = plt.subplots(1, 2, figsize=(10, 3.5))
log.plot(x="epoch", y=["train_loss", "val_loss"], ax=ax[0], marker="o")
log.plot(x="epoch", y="val_metric", ax=ax[1], marker="o")
best = log.loc[log["val_metric"].idxmax(), "epoch"]
for a in ax:
    a.axvline(best, ls="--", c="gray")             # 가장 좋았던 epoch
fig.savefig(run_dir / "curve.png", dpi=120)
```

`EarlyStop`, 분할, 학습 곡선, 아래 재표집 코드는 가짜 데이터로 실행해 확인했다. torch 루프는 이 문서를 쓴 환경에서 torch를 설치할 수 없어 실행하지 못했다 — 첫 실험에서 '작은 묶음 외우기'로 확인한다.

**VS Code 확인:** 학습 중 `log.csv`를 열어 epoch마다 한 줄씩 느는지, 학습 곡선에서 학습 손실과 검증 손실이 벌어지는 지점과 점선(가장 좋았던 epoch). GPU 사용은 macOS 활동 모니터 → 윈도우 → GPU 기록.

### 3-7. 시험 (한 번만)

- 가장 좋았던 체크포인트로, 기준선 세 줄과 함께 시험 세트에서 잰다.
- 차이의 95% 구간은 개념 단위로 짝지어 재표집한다 (같은 개념의 예들은 서로 비슷해서 하나씩 재표집하면 구간이 너무 좁게 나온다). C는 `qid`별 역순위(1/순위)를 넣으면 MRR 차이가 된다. B의 AUC·AP처럼 묶음 전체로 계산하는 지표는 재표집마다 두 모델의 지표를 다시 계산해 차이를 모은다.
- 시험 결과를 보고 다시 고쳤다면 그 시험 세트는 이미 '본 것'이다. `RESULTS.md`에 그렇게 적는다.
- 추론 속도(1000개당 ms)와 메모리를 CPU와 MPS에서 각각 잰다.

```python
# %% 개념 단위 짝지은 재표집 (시험 항목별 점수 → 평균 차이와 95% 구간)
import numpy as np
def boot_diff_by_concept(new, old, concept, n=2000, seed=0):
    d = np.asarray(new, float) - np.asarray(old, float)
    concept = np.asarray(concept)
    groups = [d[concept == c] for c in np.unique(concept)]
    rng = np.random.default_rng(seed)
    bs = [np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))]).mean() for _ in range(n)]
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
```

### 3-8. 기록과 채택

- `experiments/RESULTS.md`에 실험마다 한 줄: `날짜 | 이름 | 데이터 해시 | 결정 지표 (검증 / 시험) | 기준선 대비 차이 [95% 구간] | 어려운 경우 | 속도 | 채택 여부`.
- `config.json`: git 커밋(`git rev-parse --short HEAD`), 패키지 버전(`pip freeze | grep -i -E "torch|transformers|sentence"`), 시드, 하이퍼파라미터, 데이터 SHA-256, 분할 파일 이름.
- 모델 가중치는 `models/`(git 제외). 기록(`config.json`·`log.csv`·`metrics.json`·`RESULTS.md`)만 커밋한다.

## 4. Mac (Apple Silicon)에서 학습

```python
import torch
device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
```

- 지원 안 되는 연산이 있으면 실행 전에 `export PYTORCH_ENABLE_MPS_FALLBACK=1` (그 연산만 CPU로).
- MPS는 float64를 지원하지 않는다. float32로 둔다.
- 설치: `python -m pip install torch` (SETUP.md 8단계). 2026-11-07 PyPI 기준 torch 2.15.0의 macOS용 설치 파일은 Apple Silicon + macOS 14 이상이다. 실험이 자리 잡으면 실제 쓴 버전을 `requirements-ml.txt`로 고정해 커밋한다.

## 5. VS Code에서 직접 확인하기 (체크리스트)

`.py` 파일에 `# %%`를 넣어 셀을 나누면, 셀 위의 **Run Cell**을 눌러 Interactive Window에서 실행된다. 노트북 파일(`.ipynb`)이 아니라 일반 파이썬 파일이라 git 변경 내역이 깔끔하다. 변수 창의 DataFrame은 Data Wrangler로 연다. 세팅은 `SETUP.md` 5단계.

| 언제 | 확인할 것 | 어디서 |
|---|---|---|
| 열 때마다 | 오른쪽 아래 상태 표시줄의 파이썬이 `concept-chart` (3.13)인지 | 상태 표시줄 / `Python: Select Interpreter` |
| 열 때마다 | `python dev.py check` 마지막 줄 `결과: 모두 통과` | 통합 터미널 |
| 받은 직후 | 원본 열 이름·형식·앞부분 | 파일 우클릭 → Open in Data Wrangler |
| 살펴보기 | 빈 값·라벨 비율·중복·NFC·길이 분포 | Interactive Window 출력, Data Wrangler 열 통계 |
| 전처리 뒤 | 샘플 20개를 눈으로, 계약 점검 통과 | Data Wrangler, 출력 |
| 분할 뒤 | 겹침 0, 버린 쌍 수, 분할 파일이 새 파일로 보이는지 | 출력, 소스 제어 창 |
| 학습 전 | Claude Code가 보여 준 계획(데이터·분할·모델·지표·예상 시간)을 승인 | Claude Code |
| 학습 중 | `log.csv` 한 줄씩, 학습 곡선, GPU 사용 | 편집기, Interactive Window, 활동 모니터 |
| 커밋 전 | `data/`·`models/`·`*.pt`가 변경 목록에 없는지, 기록 파일만 있는지 | 소스 제어 창 / `git status` |
| 시험 뒤 | `metrics.json`의 기준선 대비 차이와 구간, `RESULTS.md` 한 줄 | 편집기 |

## 6. 파이프라인에 붙이는 규칙 (구조를 깨지 않게)

- 새 모델은 **기존 방식을 지우지 않고 비교 행으로 추가**한다 (기준선과 같은 지표 함수를 쓰는 실험 스크립트).
- 실제 사용 경로(`kit/`)에 넣을 때는 같은 모양의 함수로 감싼다: B는 `same_concept(a, b) -> 확률`, C는 `definition_score(term, sentence) -> 점수`. `kit/`는 다른 폴더를 import하지 않는다는 규칙(`docs/ARCHITECTURE.md`)을 지킨다.
- 무료·경량 원칙: 추론은 CPU 또는 Mac GPU에서 돈다. 크면 int8 양자화(ONNX)를 검토한다.
- 바꿀 때마다 `python dev.py check` 통과 → 브랜치 → CI → main, `CHANGELOG.md`에 한 줄.

## 7. Claude Code에 맡길 때

- 긴 학습을 돌리기 전에 계획(데이터·분할·모델·지표·예상 시간)을 먼저 보여 주고 승인을 받는다.
- 분할 파일과 시험 세트는 수정하지 않는다. 시험 세트 평가는 사용자가 요청할 때만 한다.
- 점수는 기준선 행과 95% 구간을 같이 보고한다. 확인하지 않은 숫자는 쓰지 않는다.
- `data/`·`models/`·가중치 파일을 커밋하지 않는다 (커밋 전 `git status`).

## 8. 채택 기준 (사용자가 최종 결정)

모두 만족할 때만 기본 경로를 바꾼다.

1. 실제 시험 세트에서 지금 방식보다 좋고, 차이의 95% 구간이 0을 넘는다.
2. 어려운 경우(B: 발음·표기가 비슷한 다른 개념)가 나빠지지 않는다.
3. 추론 속도·메모리가 예산 안이다 (예산 값은 사용자가 정한다).
4. 결과를 `experiments/RESULTS.md`에 남기고 사용자가 승인한다.
