# 변경 기록

날짜는 한국 시간. 페이지에 보이는 숫자가 바뀐 변경은 따로 표시한다.

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
