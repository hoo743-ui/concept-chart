// ⚠ 시험용 가짜 데이터 (MOCK) — 실제 대화·실제 판정 결과가 아니다.
// 화면 상태(설명 준비됨·출처 문장만·준비 중·뜻이 다름·설명 없음, 더 보기, 후보 …)를 한 번에 그려 보려고 docs/API.md 계약 모양대로 만들었다.
// 글마다 [테스트]를 붙여 캡처에서도 실제 데이터와 헷갈리지 않게 한다. 이 데이터를 쓰는 시험은 이름이 [mock]으로 시작한다.
const T = '[테스트] ';
const ts = (h) => `2026-11-10T${String(h).padStart(2, '0')}:00:00+09:00`;

const origin1 = { question: T + '파이썬 가상환경이랑 Docker 컨테이너는 뭐가 달라?', ts: ts(9), answer: 'a1' };

function summaryItem(id, label, o = {}) {
  return {
    id, label, rank: o.rank || 1, sessions: 1, turns: 2, last_seen: ts(9),
    gate: { show: true, candidate: false, extra: false, by: 'rule', rule: 'accept', ...(o.gate || {}) },
    progress: o.progress || 'new',
    line: o.line === undefined ? null : o.line,
    line_kind: o.line_kind || 'none',
    origin: o.origin === undefined ? origin1 : o.origin,
    field: o.field === undefined ? '정보·통신' : o.field,
  };
}

const LONG_LABEL = '아주길게이어붙인복합개념이름으로줄바꿈과잘림을시험하는낱말';
const items = {
  venv: summaryItem('가상환경', '가상환경', { rank: 1, line_kind: 'ai_checked', line: T + '프로젝트마다 따로 쓰는 파이썬 실행 환경이에요.' }),
  docker: summaryItem('docker', 'Docker', { rank: 2, progress: 'review', line_kind: 'source', line: T + 'Docker는 컨테이너 안에서 프로그램을 실행하는 도구이다.' }),
  container: summaryItem('컨테이너', '컨테이너', { rank: 3 }),
  long: summaryItem(LONG_LABEL, LONG_LABEL, { rank: 4, field: null, line_kind: 'source', line: T + '긴 설명 문장이 카드 안에서 잘리지 않고 여러 줄로 이어지는지 보려고 일부러 길게 쓴 문장입니다. '.repeat(3) }),
  known: summaryItem('브랜치', '브랜치', { rank: 5, progress: 'known', line_kind: 'source', line: T + '브랜치는 독립된 작업 흐름이다.' }),
  law: summaryItem('계약', '계약', { rank: 6, field: '법률', origin: null }),
};

function detail(it, o = {}) {
  return {
    concept: it.id, label: it.label, rank: it.rank, sessions: 1, turns: 2, last_seen: it.last_seen,
    gate: it.gate, progress: it.progress, origin: it.origin, field: it.field,
    summary: null, definition: null, chat_line: null, sources: [], note_status: 'none',
    related: [], records: [], next_cursor: null, forms: [it.label], note: { status: 'none' }, practice: null,
    ...o,
  };
}

const record = (q, s, h) => ({ ts: ts(h), role: 'assistant', snippet: T + s, question: q ? T + q : null });

function base() {
  return {
    '/api/health': { llm: { name: 'mock', available: true }, jobs: { queued: 2, done: 5, failed: 0 }, study_worker: true, turns: 12, sessions: 3, web: true },
    '/api/study/today': {
      project: null,
      counts: { shown: 4, known: 1, left: 4, hidden: 2, questions: 2, extra: 1 },
      items: [items.venv, items.docker, items.container, items.law],
      groups: [
        { answer: 'a1', question: origin1.question, ts: ts(9), items: [items.venv, items.docker, items.container],
          more: [{ id: '이미지', label: '이미지', extra: false }, { id: '레이어', label: '레이어', extra: true }] },
        { answer: null, question: null, ts: null, items: [items.law], more: [] },
        { answer: 'a3', question: '<pasted_content id="t1">', ts: ts(7), items: [items.known], more: [] },
      ],
    },
    '/api/study/concepts?view=show': { project: null, n_sessions: 3, total_words: 40, items: Object.values(items) },
    '/api/study/concepts?view=hidden': { project: null, n_sessions: 3, total_words: 40, items: [
      summaryItem('폴더', '폴더', { gate: { show: false, candidate: true, by: 'llm', rule: 'maybe' } }),
      summaryItem('오늘', '오늘', { gate: { show: false, candidate: false, by: 'rule', rule: 'reject' } }),
    ] },
    // 설명 준비됨: AI 쉬운 설명 + 근거 + 출처 링크 + 빈칸 문제 + 내 대화
    '/api/study/concept/가상환경': detail(items.venv, {
      summary: T + '프로젝트마다 따로 쓰는 파이썬 실행 환경이에요.',
      definition: T + '가상 환경은 파이썬 패키지를 프로젝트별로 분리해 설치하는 디렉터리이다.',
      sources: [{ text: T + '가상 환경은 파이썬 패키지를 프로젝트별로 분리해 설치하는 디렉터리이다.', url: 'https://ko.wikipedia.org/wiki/%ED%85%8C%EC%8A%A4%ED%8A%B8' }],
      note_status: 'ready',
      note: { status: 'ready', model: 'mock', updated: ts(10), easy: T + '프로젝트마다 따로 쓰는 파이썬 실행 환경이에요.',
        easy_evidence: [T + '가상 환경은 파이썬 패키지를 프로젝트별로 분리해 설치하는 디렉터리이다.'], checked: { total: 3, passed: 3 }, has_source: true },
      related: [{ id: 'docker', label: 'Docker' }, { id: '컨테이너', label: '컨테이너' }],
      records: [record('가상환경은 왜 써?', '가상환경을 만들면 패키지 버전이 프로젝트끼리 섞이지 않습니다.', 9), record(null, '가상환경을 켠 뒤 pip로 설치하세요.', 8)],
      practice: { blank: T + '____은 파이썬 패키지를 프로젝트별로 분리해 설치하는 디렉터리이다.', answer: '가상 환경' },
      forms: ['가상환경', '가상 환경', 'venv'],
    }),
    // 출처 문장만 (AI 설명은 대조에서 탈락) + 내 판단 있음
    '/api/study/concept/docker': detail({ ...items.docker, gate: { ...items.docker.gate, by: 'user', show: true } }, {
      definition: T + 'Docker는 컨테이너 안에서 프로그램을 실행하는 도구이다.',
      sources: [{ text: T + 'Docker는 컨테이너 안에서 프로그램을 실행하는 도구이다.', url: 'https://ko.wikipedia.org/wiki/%ED%85%8C%EC%8A%A4%ED%8A%B8' }],
      note_status: 'ready', note: { status: 'rejected', easy: null },
      records: [record('Docker 써야 해?', 'Docker로 실행하면 어느 PC에서나 같은 환경이 됩니다.', 9)],
    }),
    // 설명 준비 중
    '/api/study/concept/컨테이너': detail(items.container, { note_status: 'pending' }),
    // 뜻이 다름 (출처가 다른 분야)
    '/api/study/concept/이미지': detail(summaryItem('이미지', '이미지'), { note_status: 'ready', note: { status: 'wrong_sense', easy: null },
      records: [record(null, 'Docker 이미지를 먼저 받아야 합니다.', 9)] }),
    // 설명 없음, 기록 없음
    '/api/study/concept/레이어': detail(summaryItem('레이어', '레이어', { gate: { show: false, candidate: false, extra: true, by: 'rule', rule: 'maybe' } })),
    '/api/study/concept/계약': detail(items.law),
    '/api/study/concept/브랜치': detail(items.known),
    [`/api/study/concept/${LONG_LABEL}`]: detail(items.long, { definition: items.long.line, sources: [{ text: items.long.line, url: 'javascript:alert(1)' }] }),
    '/api/study/history': { items: [{ id: 'docker', label: 'Docker', kind: 'opened', status: 'review', ts: ts(10) }] },
    // 설명이 여러 문단·출처가 여럿인 경우 (실제 정의는 대개 한 문단이라 시험용으로만)
    '/api/study/concept/여러문단': detail(summaryItem('여러문단', '여러문단'), {
      definition: [1, 2, 3, 4].map((i) => T + `${i}번째 문단입니다. 정의가 여러 문단으로 들어와도 문단 사이 간격과 줄 길이가 유지되는지 확인합니다. 한 문단은 두세 줄 정도의 길이가 되도록 일부러 문장을 이어 붙였습니다.`).join('\n\n'),
      sources: [1, 2, 3].map((i) => ({ text: T + `출처 ${i}의 다른 문장입니다.`, url: 'https://ko.wikipedia.org/wiki/' + encodeURIComponent('시험_문서_' + i) })), note_status: 'ready', note: { status: 'rejected', easy: null } }),
    '/api/answers': { items: [
      { id: 'a1', session: 's1', ts: ts(9), source: 'claude-code', preview: T + '가상환경은 파이썬 패키지를 프로젝트별로 나누고, Docker는 운영체제 수준에서 격리합니다.', chars: 420 },
      { id: 'a2', session: 's2', ts: ts(8), source: 'paste', preview: T + '요약이 아직 없는 답변입니다.', chars: 30 },
    ] },
    '/api/answers/a1': {
      id: 'a1', session: 's1', ts: ts(9), source: 'claude-code', question: origin1.question,
      text: '## ' + T + '차이\n\n**가상환경**은 파이썬 패키지만 나누고, `docker run`으로 띄우는 Docker 컨테이너는 운영체제까지 격리합니다.\n\n| 구분 | 가상환경 | Docker |\n|---|---|---|\n| 격리 범위 | 파이썬 패키지 | 운영체제 |\n\n- 가볍게 시작하려면 가상환경\n- 배포까지 같게 하려면 Docker\n\n```\npython -m venv .venv\ndocker run hello-world\n```',
      terms: [{ id: '가상환경', label: '가상환경', forms: ['가상환경'] }, { id: 'docker', label: 'Docker', forms: ['Docker'] }, { id: '컨테이너', label: '컨테이너', forms: ['컨테이너'] }],
      summary: { status: 'ready', model: 'mock', points: [{ text: T + '가상환경은 파이썬 패키지만 나눕니다.', evidence: 1 }, { text: T + 'Docker 컨테이너는 운영체제까지 격리합니다.', evidence: 2 }], checked: { total: 2, passed: 2 }, extractive: true },
    },
    // 콘텐츠 종류 시험용 답변 (봉투 질문 · 제목 단계 · JSON · 깨진 JSON · HTML · 코드 · 표 · 긴 주소)
    '/api/answers/a3': { id: 'a3', session: 's3', ts: ts(7), source: 'claude-code',
      question: '<pasted_content id="t1">\n# [테스트] 붙여 넣은 문서 제목\n본문 첫 줄입니다.\n</pasted_content id="t1">',
      text: [
        '# [테스트] 첫째 제목', '설명 문단입니다. [가이드](https://example.com/guide) 와 https://example.com/' + 'a'.repeat(120) + ' 같은 긴 주소가 있어요.',
        '## 둘째 제목', '```json', '{"name": "[테스트]", "items": [1, 2, 3], "ok": true, "none": null}', '```',
        '{"inline": "문단 전체가 JSON", "count": 2}',
        '{"broken": "닫는 괄호가 없음",', '',
        '<div onclick="window.HACKED=3">[테스트] HTML 조각</div>', '',
        '<script>window.HACKED=4</script>', '',
        '### 셋째 제목', '```bash', 'python dev.py check', 'npx playwright test', '```',
        '| 항목 | 값 |', '|---|---|', '| 가상환경 | 파이썬 |', '',
        '> 인용문입니다.',
      ].join('\n'),
      terms: [{ id: '가상환경', label: '가상환경', forms: ['가상환경'] }], summary: { status: 'none' } },
    '/api/answers/a2': { id: 'a2', session: 's2', ts: ts(8), source: 'paste', question: null, text: T + '요약이 아직 없는 답변입니다.', terms: [], summary: { status: 'none' } },
  };
}

// page.route로 /api/*를 가로챈다. 계약에 없는 경로는 404로 돌려주고 unknown에 남긴다 (모르는 호출을 놓치지 않게).
// overrides: { '경로': 응답 | (req) => ({status, body}) }
async function mockApi(page, overrides = {}) {
  const data = { ...base(), ...overrides };
  const calls = { posts: [], unknown: [] };
  await page.route(/\/api\//, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = decodeURIComponent(url.pathname);
    if (p === '/api/events') return route.abort();
    if (req.method() === 'POST') {
      let body = null;
      try { body = req.postDataJSON(); } catch { body = req.postData(); }
      calls.posts.push({ path: p, body });
      const h = data['POST ' + p];
      if (typeof h === 'function') { const r = h(req); return route.fulfill({ status: r.status, json: r.body }); }
      const reply = p.endsWith('/progress') || p.endsWith('/feedback') ? { ok: true }
        : p === '/api/ingest' ? { added: true } : p.endsWith('/summary') ? { queued: true } : null;
      if (!reply) { calls.unknown.push('POST ' + p); return route.fulfill({ status: 404, json: { error: '없는 API' } }); }
      return route.fulfill({ json: reply });
    }
    const view = url.searchParams.get('view');
    const key = view ? `${p}?view=${view}` : p;
    const h = data[key] !== undefined ? data[key] : data[p];
    if (h === undefined) { calls.unknown.push('GET ' + key); return route.fulfill({ status: 404, json: { error: '없는 개념' } }); }
    if (typeof h === 'function') { const r = await h(req); return route.fulfill({ status: r.status, json: r.body }); }
    return route.fulfill({ json: JSON.parse(JSON.stringify(h)) });
  });
  return calls;
}

module.exports = { mockApi, base, LONG_LABEL, T };
