# API 계약 — 화면과 서버의 유일한 약속

화면(`app/`)은 이 문서의 API만 쓰고, 서버(`kit/serve.py`)는 화면 파일을 모른다. 이 약속만 지키면 어느 쪽이든 통째로 바꿀 수 있다. `tests/test_study.py`가 강제한다.
모든 주소는 `http://localhost:8765` 기준이고, 이 PC에서만 열린다. 응답은 JSON이다. `?project=폴더`로 좁힐 수 있고, 오류는 `{"error": 설명}`이다.

## 읽기 (GET)

| 경로 | 돌려주는 것 |
|---|---|
| `/api/study/today?k=7` | `{groups:[{answer, question, ts, items:[개념 요약], more:[{id, label}]}], items, counts:{shown, known, left, hidden, questions}}` 아직 '이해함'이 아닌 개념을 처음 만난 내 질문별로 묶는다 (`k` = 묶음 수). 묶음 순서는 '다시 볼 것'이 있는 질문 → 최근 질문, 묶음마다 `items`는 3개까지이고 나머지는 `more`. 맨 바깥 `items`는 펼친 개념을 이어 붙인 것 |
| `/api/study/concepts?view=show\|hidden\|all&k=50` | `{items:[개념 요약], n_sessions, total_words}` `hidden`은 후보가 먼저 |
| `/api/study/concept/{id}` | 개념 노트 (아래). 처음 열면 정의 수집과 노트 작성을 뒤에서 예약한다 |
| `/api/answers?k=20` | `{items:[{id, session, ts, source, preview, chars}]}` 최근 답변 |
| `/api/answers/{id}` | `{id, ts, source, text, question, terms:[{id, label, forms}], summary}` 답변 원문과 그 안의 공부 개념 |
| `/api/health` | `{llm:{name, available}, jobs:{queued, done, failed}, study_worker, turns, sessions, web}` |
| `/api/events` | SSE. 내용이 바뀌면 `update` 이벤트 |

**개념 요약** `{id, label, rank, sessions, turns, last_seen, gate, progress, line, line_kind, origin, field}`

- `gate`: `{show, candidate, by, rule}` 보여 줄지. `by` = `user`·`rule`·`llm`·`terms`·`unjudged`
- `progress`: `new`·`review`·`known`
- `line_kind`: `ai_checked`(근거 대조를 통과한 AI 문장) · `source`(출처 문장 그대로) · `none`(설명 없음)
- `origin`: `{question, ts, answer}` 이 개념을 처음 만난 자리. `question`은 그 답변 앞의 내 질문 첫 줄(80자까지, 없으면 `null`), `answer`는 `/api/answers/{id}`의 id. 기록이 없으면 `origin` 자체가 `null`
- `field`: 분야 꼬리표(`물리`, `법률`, `정보·통신` …) 또는 `null`. 우리말샘 전문 분야 중 함께 나온 개념 2개 이상과 겹치는 것, 기술 용어집이면 `정보·통신` (`kit/fields.py`). 화면 표시용이고 공부 목록 판정에는 쓰지 않는다

**개념 노트**: 개념 요약의 `id` 대신 `concept`, 그리고 `summary, definition, sources:[{text, url}], origin, field, note_status, chat_line, related:[{id, label}], records:[{ts, role, snippet, question}], next_cursor, forms, note, practice`.

**`note`**(쉬운 설명): `{status, model, updated, easy, easy_evidence, checked:{total, passed}, has_source}`

- `status`: `none`(아직 없음) · `ready`(통과) · `rejected`(대조 탈락, 출처 문장을 대신 보여 줌) · `no_evidence`(근거 없음) · `wrong_sense`(출처가 다른 분야의 뜻, `definition`과 `sources`를 비움)
- `easy`는 `easy_evidence`의 근거 한 문장과 대조를 통과했다. 없으면 `null`이고, 화면은 지어내지 않고 비워 둔다.

**`practice`**: `{blank, answer}` 또는 `null`. 출처 문장에서 개념 이름만 가린 빈칸 문제 (LLM 없음).

**`summary`**(답변 요약): `{status, model, points:[{text, evidence}], checked:{total, passed}, extractive}` LLM은 문장 번호만 고르고, `text`는 답변의 원문 문장이다.

## 기록 (POST)

본문은 `Content-Type: application/json`만 받는다. `Origin`이 이 PC가 아니면 403, 256KB를 넘으면 413.

| 경로 | 본문 | 돌려주는 것 |
|---|---|---|
| `/api/ingest` | `{text, source?}` | `{added}` AI 답변 추가. 키는 가려서 저장, 같은 글은 `false` |
| `/api/study/concept/{id}/progress` | `{status: new\|review\|known}` | `{ok}` |
| `/api/study/concept/{id}/feedback` | `{verdict: concept\|not_concept\|clear}` | `{ok}` 사용자 판단은 규칙과 LLM보다 앞선다 |
| `/api/answers/{id}/summary` | `{}` | `{queued, reason?}` 요약 예약 |

기존 API(`/api/leaderboard`, `/api/concept/{id}`, `/api/projects`, `/api/status`)는 `docs/ARCHITECTURE.md`에 있고 그대로 유지한다.

## 모델을 바꾸는 방법

모델은 서버와 다른 프로세스(`kit/study_worker.py`)에서 돌고, `jobs` 표로만 일을 받는다. 다른 LLM을 쓰려면 `kit/llm.py`에 `available()`과 `json(prompt, schema)`를 가진 클래스를 더하고 `--llm` 값만 바꾼다. 화면과 서버는 바뀌지 않는다. 생성한 문장은 어떤 모델이든 같은 근거 대조를 지나야 저장된다.
