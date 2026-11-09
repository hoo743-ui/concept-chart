// 화면이 서버와 만나는 유일한 파일. 계약은 docs/API.md. 화면을 바꾸거나 서버를 바꿔도 이 약속만 지키면 된다.
// ?demo=1 이면 서버 없이 demo.json으로 동작한다.
const API = (() => {
  const demo = new URLSearchParams(location.search).has('demo');
  let demoData = null;

  async function loadDemo() {
    if (!demoData) demoData = await (await fetch('demo.json')).json();
    return demoData;
  }

  async function get(path) {
    if (demo) {
      const d = await loadDemo();
      const key = path.split('?')[0];
      if (d[key] === undefined) throw new Error('데모에 없는 화면입니다');
      return d[key];
    }
    const r = await fetch(path);
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || '요청에 실패했습니다');
    return body;
  }

  async function post(path, body) {
    if (demo) return { ok: true, added: true, queued: false, reason: '데모에서는 저장하지 않습니다' };
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const out = await r.json();
    if (!r.ok) throw new Error(out.error || '저장에 실패했습니다');
    return out;
  }

  const enc = encodeURIComponent;
  return {
    demo,
    today: (k = 7) => get(`/api/study/today?k=${k}`),
    concepts: (view = 'show', k = 300) => get(`/api/study/concepts?view=${view}&k=${k}`),
    concept: (id) => get(`/api/study/concept/${enc(id)}`),
    answers: (k = 30) => get(`/api/answers?k=${k}`),
    answer: (id) => get(`/api/answers/${enc(id)}`),
    health: () => get('/api/health'),
    setProgress: (id, status) => post(`/api/study/concept/${enc(id)}/progress`, { status }),
    setFeedback: (id, verdict) => post(`/api/study/concept/${enc(id)}/feedback`, { verdict }),
    summarize: (id) => post(`/api/answers/${enc(id)}/summary`, {}),
    addText: (text) => post('/api/ingest', { text, source: 'paste' }),
    onUpdate(fn) {
      if (demo || !window.EventSource || new URLSearchParams(location.search).has('static')) return;   // static: 화면 캡처용, 실시간 연결 없음
      new EventSource('/api/events').addEventListener('update', fn);
    },
  };
})();
