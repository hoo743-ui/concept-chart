// 화면이 서버와 만나는 유일한 파일. 계약은 docs/API.md. 화면을 바꾸거나 서버를 바꿔도 이 약속만 지키면 된다.
// ?demo=1 이면 서버 없이 demo.json으로 동작한다.
const API = (() => {
  const demo = new URLSearchParams(location.search).has('demo');
  let demoData = null;

  async function loadDemo() {
    if (!demoData) demoData = await (await fetch('demo.json')).json();
    return demoData;
  }

  // 서버에 닿지 못하면 브라우저 영문 예외(Failed to fetch) 대신 한국어 안내
  async function reach(path, opt) {
    try { return await fetch(path, opt); } catch { throw new Error('개념 차트 서버에 연결하지 못했어요.'); }
  }

  async function get(path) {
    if (demo) {
      const d = await loadDemo();
      const key = decodeURIComponent(path.split('?')[0]);
      if (d[key] === undefined) throw new Error('데모에 없는 화면이에요');
      return d[key];
    }
    const r = await reach(path);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || (r.status === 404 ? '찾는 내용이 없어요.' : '요청을 처리하지 못했어요.'));
    return body;
  }

  async function post(path, body) {
    if (demo) return { ok: true, added: true, queued: false, reason: '데모에서는 저장하지 않아요' };
    const r = await reach(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const out = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(out.error || '저장하지 못했어요.');
    return out;
  }

  const enc = encodeURIComponent;
  return {
    demo,
    today: (k = 7) => get(`/api/study/today?k=${k}`),
    concepts: (view = 'show', k = 300) => get(`/api/study/concepts?view=${view}&k=${k}`),
    concept: (id) => get(`/api/study/concept/${enc(id)}`),
    history: (k = 200) => get(`/api/study/history?k=${k}`),   // docs/API.md의 읽기 API (열어 본 기록·진도 표시)
    answers: (k = 30) => get(`/api/answers?k=${k}`),
    answer: (id) => get(`/api/answers/${enc(id)}`),
    health: () => get('/api/health'),
    setProgress: (id, status) => post(`/api/study/concept/${enc(id)}/progress`, { status }),
    setFeedback: (id, verdict) => post(`/api/study/concept/${enc(id)}/feedback`, { verdict }),
    setKnown: (id, known) => post(`/api/study/concept/${enc(id)}/known`, { known }),   // (11-14, D12) 이미 아는 낱말: 공부 목록에서만 뺀다
    senses: (id) => (demo ? Promise.resolve({ senses: [], picked: null }) : get(`/api/study/concept/${enc(id)}/senses`)),   // (0.9.2) 뜻이 여러 개인 낱말의 후보
    pickSense: (id, title) => post(`/api/study/concept/${enc(id)}/sense`, { title }),
    summarize: (id) => post(`/api/answers/${enc(id)}/summary`, {}),
    addText: (text) => post('/api/ingest', { text, source: 'paste' }),
    onUpdate(fn) {
      if (demo || !window.EventSource || new URLSearchParams(location.search).has('static')) return;   // static: 화면 캡처용, 실시간 연결 없음
      new EventSource('/api/events').addEventListener('update', fn);
    },
  };
})();
