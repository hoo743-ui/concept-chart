# 명령어 모음 (Mac 기준)

설명은 `SETUP.md`(세팅)와 `docs/TRAINING.md`(학습)에 있다. 여기는 순서대로 복사해서 쓰는 명령만 모았다.
`#` 뒤는 설명이라 같이 붙여넣어도 된다. Windows는 `python3` 대신 `python`, 1단계는 `SETUP.md`의 Windows 항목을 따른다.

## 1. 처음 한 번 — 도구 설치 (터미널)

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install gh node@22
brew install --cask visual-studio-code
echo 'export PATH="/opt/homebrew/opt/node@22/bin:$PATH"' >> ~/.zshrc
cd ~
curl -fsSL -o Miniforge3.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3.sh -b -p "$HOME/miniforge3"
"$HOME/miniforge3/bin/conda" init zsh
curl -fsSL https://claude.ai/install.sh | bash
```

터미널을 완전히 끄고(Cmd+Q) 다시 연 뒤 확인:

```bash
conda --version && gh --version && node --version && code --version && claude --version
claude doctor
```

## 2. 처음 한 번 — 받기 + 환경 만들기

```bash
gh auth login                          # 브라우저로 GitHub 로그인
cd ~
gh repo clone hoo743-ui/concept-chart
cd concept-chart
python3 dev.py setup                   # 마지막 줄 '결과: 모두 통과'
conda activate concept-chart
```

## 3. 처음 한 번 — VS Code

```bash
code --install-extension ms-python.python
code --install-extension ms-toolsai.jupyter
code --install-extension ms-toolsai.datawrangler
conda activate concept-chart
python -m pip install ipykernel pandas matplotlib pyarrow
code .
```

VS Code 안에서: `Cmd+Shift+P` → `Python: Select Interpreter` → `concept-chart`
(목록에 없으면 `Enter interpreter path` → `~/miniforge3/envs/concept-chart/bin/python`)

## 4. 학습 시작할 때 한 번 — 패키지

```bash
conda activate concept-chart
python -m pip install torch
python -m pip install transformers sentence-transformers
python -c "import torch; print(torch.__version__, 'MPS:', torch.backends.mps.is_available())"   # MPS: True 확인
```

## 5. (선택) 이 Mac의 Claude Code 대화도 기록

```bash
conda activate concept-chart
python kit/install_concept_hook.py           # 설치
python kit/install_concept_hook.py --test    # '결과: 정상'
python kit/install_concept_hook.py --uninstall   # 제거할 때
```

## 6. 매일 시작

```bash
cd ~/concept-chart
conda activate concept-chart
git pull
python dev.py check                    # '결과: 모두 통과'
code .                                 # VS Code
claude                                 # Claude Code
```

## 7. 고친 뒤 다시 만들기

```bash
python dev.py build                    # kit/*.py 또는 web/page_template.html을 고쳤을 때
python dev.py sim                      # sim/*.py를 고쳤을 때 (A·B·C 다시 실행 → 페이지까지)
python tests/test_hook.py              # 훅 변환 규칙을 고쳤을 때 (그다음 build)
python sim/make_page_data.py --check   # 페이지 데이터가 그대로인지만 확인
python web/build_page.py --check       # 결과 페이지가 그대로인지만 확인
```

## 8. 커밋 → CI → main

```bash
git switch -c feat/<이름>               # 브랜치 (처음 한 번)
python dev.py check                    # '결과: 모두 통과'
git status --short                     # data/ · models/ · *.pt 가 없어야 함
git add -A
git commit -m "<무엇을 왜>"
git push -u origin feat/<이름>
gh run list --branch feat/<이름> --limit 1   # CI 실행 번호 확인
gh run watch <실행 번호>                 # 5개 잡 모두 통과까지 대기
git switch main && git pull
git merge --ff-only feat/<이름>
git push
```

`CHANGELOG.md`에 한 줄 추가하는 것도 커밋에 넣는다.

## 9. 학습 실험 (순서대로)

```bash
# ① 폴더 (첫 실험 때 한 번)
mkdir -p data/raw data/processed experiments/splits models

# ② 받은 데이터 기록 → experiments/DATA.md 에 붙여넣기
shasum -a 256 data/raw/<데이터>/*      # 파일 해시
wc -l data/raw/<데이터>/*              # 행 수 (CSV·JSONL)

# ③ 실험 폴더
RUN=experiments/$(date +%F)-<이름>
mkdir -p "$RUN"

# ④ 실행 (Mac GPU, 안 되는 연산은 CPU로)
export PYTORCH_ENABLE_MPS_FALLBACK=1
python "$RUN/train.py"

# ⑤ config.json 에 넣을 값
git rev-parse --short HEAD
pip freeze | grep -i -E "torch|transformers|sentence"

# ⑥ 커밋 전 확인 → 8단계
git status --short                     # 기록 파일(config·log·metrics·RESULTS.md·splits)만
git check-ignore -v data models        # 둘 다 무시되는지 (출력이 있으면 정상)
```

단계별로 VS Code에서 볼 것은 `docs/TRAINING.md` 5절.

## 10. 상태 확인

```bash
python --version                       # 3.13.x
which python                           # .../miniforge3/envs/concept-chart/bin/python
conda env list                         # concept-chart 가 * 표시
git status -sb && git log --oneline -3
```

## 11. 막혔을 때

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"            # brew: command not found
"$HOME/miniforge3/bin/conda" init zsh                 # conda: command not found → 새 터미널
source ~/.zshrc                                       # claude·node: command not found
xcode-select --install                                # xcrun: invalid active developer path
python3 dev.py setup                                  # 패키지가 바뀌었거나 환경이 이상할 때 (갱신 + 점검)
conda deactivate && conda env remove -n concept-chart && python3 dev.py setup   # 환경을 처음부터 다시
```

`code` 명령이 없으면 VS Code에서 `Cmd+Shift+P` → `Shell Command: Install 'code' command in PATH`.
나머지 증상은 `SETUP.md` 10절.
