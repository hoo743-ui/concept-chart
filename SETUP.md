# 개발환경 세팅 — 다른 PC에서 이어 하기 (macOS · Windows)

목표: `git clone` → `python dev.py setup` 두 단계로 원래 PC와 같은 상태를 만든다. 명령만 순서대로 보려면 `docs/COMMANDS.md`.
마지막에 `결과: 모두 통과`가 나오면 끝이다. 각 단계는 macOS(Apple Silicon)와 Windows를 나눠 적었다.

## 0. 준비물

| 항목 | 용도 | macOS (터미널, zsh) | Windows (PowerShell) | 확인 |
|---|---|---|---|---|
| Xcode 명령줄 도구 | git, 컴파일러 | `xcode-select --install` | — | `git --version` |
| Homebrew | gh·node 설치 | 아래 1단계 | — | `brew --version` |
| Git | 클론·커밋 | Xcode 도구에 포함 | Git for Windows (Git Bash 포함) | `git --version` |
| GitHub CLI | 비공개 레포 로그인 | `brew install gh` | `winget install GitHub.cli` (선택) | `gh --version` |
| conda | 파이썬 환경 | Miniforge (아래 1단계) | Anaconda (있는 것) 또는 Miniforge | `conda --version` |
| Claude Code (2.1.47 이상) | 개발 + 대화 수집 훅 | `curl -fsSL https://claude.ai/install.sh \| bash` | `irm https://claude.ai/install.ps1 \| iex` | `claude --version` |
| Node.js 18 이상 (선택) | 페이지 자동 점검 | `brew install node@22` | nodejs.org LTS | `node --version` |
| VS Code + 확장 3개 (선택) | 편집, 데이터·학습 결과 직접 확인 | `brew install --cask visual-studio-code` | code.visualstudio.com에서 설치 | `code --version` |

## 1. 기본 도구 설치 (PC마다 한 번)

### macOS

먼저 이 두 줄만 따로 실행한다. Mac 터미널(zsh)은 기본 설정에서 `#` 뒤 설명을 명령으로 읽어서, 아래처럼 설명이 붙은 줄을 붙여넣으면 에러가 난다.

```bash
setopt interactivecomments
echo 'setopt interactivecomments' >> ~/.zshrc
```

```bash
xcode-select --install                                   # 이미 있으면 '설치됨' 메시지
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile   # Apple Silicon: brew를 PATH에 (Intel Mac은 /usr/local)
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install gh node@22                                  # node는 선택 (페이지 자동 점검용)
brew install --cask visual-studio-code                   # VS Code (선택, 5단계)
echo 'export PATH="/opt/homebrew/opt/node@22/bin:$PATH"' >> ~/.zshrc   # node@22는 자동으로 PATH에 안 들어감

# Miniforge (conda-forge 전용 conda) — CI가 macOS에서 쓰는 것과 같은 명령
curl -fsSL -o Miniforge3.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3.sh -b -p "$HOME/miniforge3"
"$HOME/miniforge3/bin/conda" init zsh                    # 터미널을 새로 열면 (base)가 보임

curl -fsSL https://claude.ai/install.sh | bash           # Claude Code
```

터미널을 완전히 껐다가(Cmd+Q) 다시 열고 `conda --version && gh --version && node --version && claude --version`, `claude doctor`로 확인한다. 이미 Anaconda가 있으면 Miniforge 세 줄은 건너뛴다.

### Windows

- Git for Windows, Anaconda(이미 있으면 그대로), Claude Code(`irm https://claude.ai/install.ps1 | iex`).
- 명령은 시작 메뉴의 **Anaconda Prompt**에서 실행하는 게 가장 편하다.

## 2. 받기

비공개 레포라 로그인이 필요하다.

```bash
gh auth login                                            # 브라우저로 GitHub 로그인 (한 번)
gh repo clone hoo743-ui/concept-chart
cd concept-chart
```

Windows에서 gh 없이: `git clone https://github.com/hoo743-ui/concept-chart.git` → 로그인 창(Git Credential Manager)에서 로그인.

## 3. 환경 만들기 + 점검

```bash
python3 dev.py setup        # Windows: python dev.py setup
conda activate concept-chart
```

- `dev.py`는 표준 라이브러리만 써서, 환경을 만들기 전 파이썬(macOS 기본 python3 3.9 이상, conda base)으로 실행된다.
- 하는 일: conda 환경 `concept-chart`가 없으면 만들고 있으면 갱신(`environment.yml`) → 새 환경에서 `python dev.py check`.
- 설치되는 것: Python 3.13 + `requirements.txt`의 패키지 전부 (numpy, scipy, scikit-learn, networkx, kiwipiepy + 모델, spaCy + 한국어 모델 `ko_core_news_md`, yake, krwordrank, korean_romanizer, RapidFuzz, rank-bm25, trafilatura). 설치 후 약 0.8GB, 인터넷 속도에 따라 수 분.
- **base 환경에 직접 설치하지 않는다.** 전용 환경 `concept-chart`만 쓴다.
- `environment.yml`은 conda-forge 채널만 쓰고(`nodefaults`), 환경을 켤 때 `PYTHONUTF8=1`을 자동으로 켠다.

conda 없이 하려면 (Python 3.13이 있을 때): `python3.13 dev.py setup --venv` → `source .venv/bin/activate` (Windows: `py -3.13 dev.py setup --venv` → `.venv\Scripts\activate` → `setx PYTHONUTF8 1`).

## 4. 점검 (언제든)

```bash
python dev.py check
```

`tests/check_env.py`(패키지, Kiwi·spaCy 한국어 모델, 검증 에이전트, 클릭 카드, 근거 문장 선택, 파이프라인 첫 셀, 훅 설치기, 훅 어댑터 테스트, 페이지 데이터·페이지 빌드 재현)를 돌리고, Node.js가 있으면 `npm ci` → `npm test`까지 한다.
훅 설치기 점검은 임시 폴더에서만 하므로 진짜 `~/.claude` 설정은 건드리지 않는다.

## 5. 매일 작업 시작 (Claude Code · VS Code)

```bash
cd ~/concept-chart              # 클론한 폴더
conda activate concept-chart
git pull
python dev.py check             # 마지막 줄 '결과: 모두 통과'
code .                          # VS Code (같은 폴더, 창이 열리고 터미널은 바로 돌아온다)
claude                          # Claude Code (끝낼 때까지 이 터미널을 쓴다)
```

- 레포의 `CLAUDE.md`(작업 원칙·구조·현재 상태·다음 할 일)를 Claude Code가 자동으로 읽는다. 설계와 변경 절차는 `docs/ARCHITECTURE.md`, 학습은 `docs/TRAINING.md`.

### VS Code 세팅 (한 번, 데이터·학습 결과를 직접 확인할 때)

```bash
code --install-extension ms-python.python          # 파이썬
code --install-extension ms-toolsai.jupyter        # # %% 셀 실행 (Interactive Window)
code --install-extension ms-toolsai.datawrangler   # 표 데이터 보기 (CSV·Parquet·JSONL·DataFrame)
conda activate concept-chart
python -m pip install ipykernel pandas matplotlib pyarrow   # 셀 실행·표·그림에 필요 (8단계와 같음)
```

1. `code` 명령이 없으면: VS Code에서 `Cmd+Shift+P` → **Shell Command: Install 'code' command in PATH** → 새 터미널.
2. 레포 폴더에서 `code .` → `Cmd+Shift+P` → **Python: Select Interpreter** → `concept-chart` (3.13). 목록에 없으면 **Enter interpreter path** → `conda env list`에 나온 경로 뒤에 `/bin/python` (Miniforge 기본: `~/miniforge3/envs/concept-chart/bin/python`).
3. 통합 터미널(메뉴 보기 → 터미널)에서 `python dev.py check`.
4. `.py` 파일에 `# %%`를 넣으면 셀 위에 **Run Cell**이 생기고, 누르면 Interactive Window에서 실행된다. 커널은 `concept-chart`를 고른다. 변수 창의 DataFrame 옆 버튼 → Data Wrangler. 파일은 탐색기에서 우클릭 → **Open in Data Wrangler**.
5. 단계별로 무엇을 확인하는지는 `docs/TRAINING.md` 5절.

## 6. 대화 수집 훅 (이 PC의 Claude Code 대화도 기록하려면)

```bash
conda activate concept-chart
python kit/install_concept_hook.py           # 전역 설치 (모든 프로젝트)
python kit/install_concept_hook.py --test    # '결과: 정상'
```

- 기록 위치: `~/.claude/concept-inbox.jsonl`. 기존 `~/.claude/settings.json`은 백업하고 다른 설정은 그대로 둔다. Claude Code 안에서 `/hooks`로 확인.
- 훅은 설치할 때 쓴 파이썬의 절대경로로 등록된다. 다른 파이썬·환경으로 바꿨으면 다시 설치한다.
- 제거: `python kit/install_concept_hook.py --uninstall`. 옵션: `--scope project --project <폴더>`, `--events user,assistant,subagent`, `--inbox <경로>`, `--no-mask`.
- 결과 페이지(`web/dist/index.html`)의 **04 입력 설정 시트**에서 같은 설치를 한 줄 명령으로 만들 수 있다 (macOS는 'mac/Linux' 선택).

### 내 대화로 보기 (로컬 서버)

```bash
python dev.py serve          # http://localhost:8765 — 인박스를 1초마다 읽어 순위·클릭 카드를 보여 준다 (Ctrl+C로 끝)
python dev.py serve --once   # 순위만 터미널에 출력
```

색인 DB는 `~/.claude/concept-chart.sqlite` (git 제외, 인박스에서 다시 만들 수 있음).

## 7. 작업 흐름

| 바꾼 것 | 다음에 할 일 |
|---|---|
| `kit/*.py` | `python dev.py build` (페이지 코드 상자·한 줄 설치 명령 갱신) |
| `web/page_template.html` | `python dev.py build` |
| 시뮬레이터 (`sim/*.py`) | `python dev.py sim` (A·B·C 재실행 → 페이지 데이터 → 페이지) |
| 훅 변환 규칙 (`kit/install_concept_hook.py`) | `python tests/test_hook.py` → `python dev.py build` |
| 로컬 서버 (`kit/serve.py`) | `python tests/test_serve.py` → `docs/ARCHITECTURE.md` API 표 |
| 패키지 추가 | `requirements.txt`에 버전까지 적기 → 다른 PC에서 `python dev.py setup` |

커밋 전에 `python dev.py check`. 브랜치 → 푸시 → GitHub Actions(Windows·macOS·Ubuntu)가 같은 점검을 다시 돌린다 → 통과하면 main.

## 8. 학습 실험용 패키지 (선택, 실험을 시작할 때)

기본 세팅에는 딥러닝 패키지를 넣지 않았다 (설치가 무겁고, 실험을 시작할 때 버전을 정하는 게 맞다). 환경을 켠 상태에서:

```bash
python -m pip install torch                                # macOS(Apple Silicon)는 GPU(MPS) 포함 빌드
python -m pip install transformers sentence-transformers   # 사전학습 인코더 미세조정용 (필요할 때)
python -m pip install pandas matplotlib ipykernel pyarrow  # 데이터 살펴보기·학습 곡선·VS Code 셀 실행
```

- 2026-11-07 PyPI 기준 torch 2.15.0의 macOS용 설치 파일은 Apple Silicon + macOS 14 이상이다.
- 같은 날 기준 macOS(Apple Silicon)·Python 3.13용 설치 파일 확인: pandas 3.1.1, matplotlib 3.11.2, pyarrow 26.0.1 (ipykernel 7.4.0은 순수 파이썬). 설치 파일이 있는 것만 확인했고 Mac에서 실행은 하지 않았다.
- 실험이 자리 잡으면 실제로 쓴 버전을 `requirements-ml.txt`로 고정해 레포에 넣는다 (`pip freeze | grep -i -E "torch|transformers|sentence"`).
- 데이터 받기 → 전처리 → 분할 → 학습(epoch·조기 종료) → 시험 → 기록 순서와 규칙은 `docs/TRAINING.md`.

## 9. PC를 옮길 때

- 코드: `git pull`. 패키지가 바뀌었으면 `python dev.py setup` (있는 환경을 갱신하고 점검).
- **git에 올라가지 않는 것** (개인 데이터라 일부러 뺐다): `~/.claude/concept-inbox.jsonl`(대화 기록), `concept_store.sqlite`, `concept_cache.sqlite`, 학습한 모델 파일. 필요하면 직접 복사한다.
- 줄바꿈은 `.gitattributes`로 LF에 고정돼 있어서 OS가 달라도 파일 내용이 바이트 단위로 같다.

## 10. 문제 해결

| 증상 | 해결 |
|---|---|
| (mac) `zsh: command not found: #` 또는 `unrecognized arguments: # …` | zsh가 `#` 설명을 명령으로 읽은 것. `setopt interactivecomments` 실행 + `~/.zshrc`에 같은 줄 (1단계 맨 앞) |
| `dev.py: error: the following arguments are required: cmd` | `dev.py` 뒤에 할 일을 붙인다: `setup` · `check` · `build` · `sim` (예: `python3 dev.py setup`) |
| (mac) `xcrun: error: invalid active developer path` | `xcode-select --install` |
| (mac) `conda: command not found` | `"$HOME/miniforge3/bin/conda" init zsh` 후 터미널을 새로 연다 |
| (mac) `zsh: command not found: brew` | `eval "$(/opt/homebrew/bin/brew shellenv)"` 후, 위 `~/.zprofile` 줄이 들어갔는지 확인 |
| (mac) `node: command not found` (brew로 설치했는데) | `node@22`는 PATH에 자동으로 안 들어간다. 위 `~/.zshrc` 줄 추가 후 새 터미널 |
| (mac) `zsh: command not found: claude` | 터미널을 새로 열거나 `source ~/.zshrc` |
| (mac) `python: command not found` | conda 환경을 켜기 전에는 `python3`를 쓴다. 환경을 켠 뒤에는 `python` |
| (mac) MPS에서 지원 안 되는 연산 오류 | `export PYTORCH_ENABLE_MPS_FALLBACK=1` 후 다시 실행 (그 연산만 CPU로) |
| (mac) `zsh: command not found: code` | VS Code에서 `Cmd+Shift+P` → Shell Command: Install 'code' command in PATH → 새 터미널 |
| (VS Code) 인터프리터·커널 목록에 `concept-chart`가 없음 | Python: Select Interpreter → Enter interpreter path → `~/miniforge3/envs/concept-chart/bin/python` (`conda env list`로 경로 확인). 커널 선택에 conda 환경이 base만 보이는 문제가 Python Environments 확장(`ms-python.vscode-python-envs`)과 함께 보고된 적이 있다(2026-08, Linux) — 같은 증상이면 그 확장을 꺼 본다 |
| (VS Code) Run Cell이 안 보이거나 커널 시작 실패 | Jupyter 확장 설치 확인, 환경에 `python -m pip install ipykernel` |
| (VS Code) Data Wrangler가 열리지 않음 | 선택한 인터프리터 환경에 `python -m pip install pandas` 후 다시 |
| `conda를 찾지 못했다` (dev.py setup) | macOS: 위 conda init. Windows: Anaconda Prompt에서 실행. conda 없이: `--venv` |
| `CondaToSNonInteractiveError` (이용약관) | `environment.yml`은 conda-forge만 써서 보통 안 생긴다. `conda create`를 직접 쓸 때는 `--override-channels -c conda-forge` |
| (Windows) PowerShell에서 `conda activate`가 안 됨 | Anaconda Prompt를 쓰거나 `conda init powershell` 후 새 창 |
| (Windows) `.venv\Scripts\activate`가 실행 정책에 막힘 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| (Windows) `python`을 치면 Microsoft Store가 열림 | 환경을 켠다 (`conda activate concept-chart`). 또는 설정 → 앱 실행 별칭에서 python 끄기 |
| (Windows) `UnicodeEncodeError: 'cp949' ...` | conda 환경이면 다시 activate, venv면 `setx PYTHONUTF8 1` 후 새 터미널 |
| (Windows) 훅 오류에 `PowerShell started no program` | Git Bash가 없어서 PowerShell에서 실행된 경우. Git for Windows 설치 후 Claude Code 세션을 새로 연다 |
| `ko_core_news_md` 설치 실패 | GitHub 접속이 막힌 망. 다른 망에서 휠을 받아 `pip install ko_core_news_md-3.8.0-py3-none-any.whl` |
| `kiwipiepy_model` 설치가 오래 걸림 | 형태소 분석 모델 데이터(약 100MB)라 정상 |
| check_env에 Python 버전 경고 | 3.13이 아닌 파이썬으로 실행 중. `python --version`과 켜진 환경 확인 |
| 훅이 기록을 남기지 않음 | `claude --version` 2.1.47 이상, `--test` 결과, Claude Code의 `/hooks` 확인. 파이썬 경로가 바뀌었으면 재설치 |
| 페이지 글꼴이 다르게 보임 | 오프라인이면 Google Fonts 대신 기본 글꼴. 기능은 같다 |

## 검증한 범위

- **CI (GitHub Actions):** Windows·macOS·Ubuntu에서 새 환경에 Python 3.13 + `requirements.txt` 설치 → `python dev.py check`. Windows·macOS에서 conda 설치 경로 `dev.py setup`. 결과는 레포 Actions 탭.
- **로컬 (Linux):** 새 클론에서 `python dev.py setup`(Miniforge, conda 설정에 defaults가 있어도 건드리지 않음) → `모두 통과`. 훅 설치기·`dev.py`는 Python 3.9(macOS 기본 python3 버전)에서도 동작 확인.
- **아직 안 해 본 것:** 사용자 Mac·Windows 실기, 실제 Claude Code 세션에서 훅이 기록하는 것, 학습용 패키지(torch 등) 실행, VS Code 세팅 단계 (확장 ID·명령은 공식 문서·마켓플레이스 기준으로 적었다).
