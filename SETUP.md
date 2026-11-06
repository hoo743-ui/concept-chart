# 개발환경 세팅 — 다른 PC에서 이어 하기

Windows 11 + Anaconda 기준이다. mac/Linux는 괄호 안 명령을 쓰면 된다.
아래대로 한 뒤 `python tests/check_env.py`의 마지막 줄이 **모두 정상**이면 원래 PC와 같은 상태다.

## 0. 준비물

| 항목 | 용도 | 확인 명령 |
|---|---|---|
| Git for Windows | 클론·커밋 (GitHub 로그인 창을 띄우는 Git Credential Manager 포함) | `git --version` |
| Anaconda (또는 Miniconda·Miniforge) | 파이썬 환경 | `conda --version` |
| VS Code + Python 확장 | 편집·실행 | |
| Claude Code 2.1.47 이상 | 대화 수집 훅 (AI 답변까지 기록하려면 필요) | `claude --version` |
| (선택) Node.js 18 이상 | 페이지 자동 점검 | `node --version` |

명령은 시작 메뉴의 **Anaconda Prompt**에서 실행하는 게 가장 편하다. VS Code 터미널(PowerShell)에서 쓰려면 맨 아래 '문제 해결'을 볼 것.

## 1. 받기

```powershell
git clone https://github.com/hoo743-ui/concept-chart.git
cd concept-chart
```

비공개 저장소라 처음 한 번 GitHub 로그인 창이 뜬다. 브라우저로 로그인하면 다음부터는 자동이다.

## 2. 파이썬 환경 만들기 (PC마다 한 번)

```powershell
conda env create -f environment.yml
conda activate concept-chart
```

- Python 3.13과 패키지 전부가 설치된다 (설치 후 약 0.8GB, 인터넷 속도에 따라 수 분).
- **base 환경에 바로 설치하지 말 것.** 다른 프로젝트 패키지와 버전이 꼬인다. 이 프로젝트 전용 환경 `concept-chart`만 쓴다.
- `environment.yml`은 conda-forge 채널만 쓰고, 환경을 켤 때 `PYTHONUTF8=1`(UTF-8 입출력)을 자동으로 켠다.
- spaCy 한국어 모델(`ko_core_news_md`)도 `requirements.txt`에 들어 있어서 따로 받을 필요 없다.

conda 없이 하려면 (Python 3.13이 설치돼 있을 때):

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate                     # (mac/Linux: source .venv/bin/activate)
python -m pip install -r requirements.txt
setx PYTHONUTF8 1                          # Windows만. 새 터미널부터 적용
```

## 3. 점검

```powershell
python tests/check_env.py
```

패키지, 한국어 모델(Kiwi·spaCy), 검증 에이전트, 클릭 카드, 근거 문장 선택, 파이프라인 첫 셀, 훅 설치기, 페이지 빌드까지 한 번에 확인한다.
훅 설치기는 임시 폴더에서 설치 → 점검 → 제거만 하므로 진짜 `~/.claude` 설정은 건드리지 않는다.

(선택) 페이지 자동 점검:

```powershell
npm ci
npm test          # 마지막에 'check_page: 정상', 'check_setup: 정상'
```

## 4. VS Code 연결

1. VS Code에서 저장소 폴더를 연다.
2. `Ctrl+Shift+P` → **Python: Select Interpreter** → `concept-chart` 환경을 고른다.
3. 새 터미널을 열면 보통 환경이 자동으로 켜진다. `python tests/check_env.py`로 확인한다 (안 켜지면 '문제 해결' 참고).

## 5. Claude Code 대화 수집 훅 (이 PC에서도 기록하려면)

```powershell
conda activate concept-chart
python kit/install_concept_hook.py           # 전역 설치 (모든 프로젝트)
python kit/install_concept_hook.py --test    # '결과: 정상'이 나오면 끝
```

- 기록 위치: `~/.claude/concept-inbox.jsonl` (Windows는 `C:\Users\<사용자>\.claude\`)
- 기존 `settings.json`은 백업하고 다른 설정은 그대로 둔다. Claude Code 안에서 `/hooks`로 등록 상태를 볼 수 있다.
- 훅은 설치할 때 쓴 파이썬의 절대경로로 등록된다. 다른 파이썬이나 환경으로 바꿨으면 다시 설치한다.
- 제거: `python kit/install_concept_hook.py --uninstall`
- 주요 옵션: `--scope project --project <폴더>`(그 프로젝트만), `--events user,assistant,subagent`, `--inbox <경로>`, `--no-mask`(키 가리기 끔)

결과 페이지(`sim/out/index.html`)의 **04 입력 설정 시트**에서 옵션을 고르면 같은 내용의 한 줄 설치 명령을 만들어 준다.

## 6. 작업 흐름

| 바꾼 것 | 다음에 할 일 |
|---|---|
| `kit/*.py` | `python sim/build_page.py` (페이지 코드 상자·한 줄 설치 명령 갱신) |
| `sim/page_template.html` | `python sim/build_page.py` |
| 시뮬레이터 (`sim/*.py`) | `python sim/sim_B.py` 등 → 결과 JSON 갱신 (README '알아 둘 점' 참고) |
| 패키지 추가 | `requirements.txt`에 버전까지 적기 → 다른 PC에서 `conda env update -f environment.yml --prune` |

커밋 전에 `python tests/check_env.py`를 한 번 돌리면 페이지가 최신인지까지 확인된다.

## 7. PC를 옮길 때

- 코드: `git pull` 하나면 된다.
- 패키지가 바뀌었으면: `conda env update -f environment.yml --prune`
- **git에 올라가지 않는 것** (개인 데이터라 일부러 뺐다): `~/.claude/concept-inbox.jsonl`(대화 기록), `concept_store.sqlite`, `concept_cache.sqlite`. 필요하면 직접 복사한다.
- 줄바꿈은 `.gitattributes`로 LF에 고정돼 있다. Windows에서 받아도 파일 내용이 바이트 단위로 같아서, 설치 파일 SHA-256과 한 줄 설치 명령이 PC마다 바뀌지 않는다.

## 8. 문제 해결

| 증상 | 해결 |
|---|---|
| `CondaToSNonInteractiveError` (이용약관 미동의) | `environment.yml`은 conda-forge만 써서 보통 생기지 않는다. `conda create`를 직접 쓸 때는 `--override-channels -c conda-forge`를 붙인다 |
| PowerShell에서 `conda activate`가 안 됨 | Anaconda Prompt를 쓰거나, `conda init powershell`을 한 번 실행하고 터미널을 새로 연다 |
| `.venv\Scripts\activate`가 실행 정책 때문에 막힘 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `python`을 치면 Microsoft Store가 열림 | 환경이 안 켜진 상태다. `conda activate concept-chart`를 확인한다 (또는 설정 → 앱 실행 별칭에서 python 끄기) |
| `UnicodeEncodeError: 'cp949' ...` | UTF-8 모드가 꺼진 상태다. conda 환경이면 `conda deactivate` 후 다시 activate, venv면 `setx PYTHONUTF8 1` 후 새 터미널 |
| `ko_core_news_md` 설치 실패 | GitHub 접속이 막힌 망이다. 다른 망에서 휠 파일을 받아 `pip install ko_core_news_md-3.8.0-py3-none-any.whl` |
| `kiwipiepy_model` 설치가 오래 걸림 | 형태소 분석 모델 데이터(약 100MB)라 정상이다 |
| check_env에 Python 버전 경고 | 3.13이 아닌 파이썬으로 실행 중이다. `python --version`과 켜진 환경을 확인한다 |
| 훅이 기록을 남기지 않음 | `claude --version`이 2.1.47 이상인지, `--test` 결과, Claude Code의 `/hooks`를 확인한다. 파이썬 경로가 바뀌었으면 훅을 다시 설치한다 |
| 페이지 글꼴이 다르게 보임 | 오프라인이면 Google Fonts 대신 기본 글꼴로 보인다. 기능은 같다 |

## 검증한 범위

- **실행 확인 (Linux, Python 3.13):** 새 가상환경에 `pip install -r requirements.txt` → `check_env.py` 통과 → 시뮬레이터 재실행 결과가 저장된 결과와 같음 → `npm test` 통과. `-X warn_default_encoding`으로 돌려서, 이 저장소 코드에는 인코딩을 지정하지 않은 파일 읽기·쓰기가 없는 것도 확인했다 (외부 패키지 trafilatura가 설정 파일 하나를 그렇게 읽지만 영문뿐이라 Windows에서도 문제없다).
- **설치 파일 확인 (Windows x64 · Python 3.13/3.12, macOS Apple Silicon · Python 3.13):** 의존 패키지 76개 모두 해당 OS용 설치 파일(wheel)이 PyPI에 있다. `kiwipiepy_model`만 소스 패키지인데, 모델 데이터만 들어 있어서 컴파일러 없이 설치된다.
- **아직 안 해 본 것:** Windows 실기에서의 실행. 처음 받으면 `check_env.py`부터 돌려 볼 것.
