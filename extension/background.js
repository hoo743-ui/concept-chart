// THYNK 공부 기록 — 받은 답변을 이 PC의 개념 차트(127.0.0.1:8765/api/ingest)로만 보낸다. 바깥 주소로는 보내지 않는다.
// 서버가 꺼져 있으면 최대 50개까지 이 브라우저에 모아 두었다가 다음에 다시 보낸다. 키 가리기·같은 글 막기는 서버가 한다.
const API = 'http://127.0.0.1:8765/api/ingest';
const QMAX = 50;
const today = () => new Date().toISOString().slice(0, 10);
const get = (k) => chrome.storage.local.get(k);
const set = (o) => chrome.storage.local.set(o);

async function stats(patch) {
  const { st } = await get('st');
  const s = st && st.day === today() ? st : { day: today(), added: 0, dup: 0 };
  Object.assign(s, typeof patch === 'function' ? patch(s) : patch);
  await set({ st: s });
}
async function post(item) {
  const r = await fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...item, source: 'claude-web' }) });
  if (!r.ok) throw new Error('개념 차트 응답 ' + r.status);
  return (await r.json()).added;
}
async function deliver(item) {
  try {
    const added = await post(item);
    await stats((s) => (added ? { added: s.added + 1, lastAt: new Date().toISOString(), lastError: null } : { dup: s.dup + 1, lastError: null }));
    return true;
  } catch (e) {
    const { queue = [] } = await get('queue');
    queue.push(item);
    await set({ queue: queue.slice(-QMAX) });
    await stats({ lastError: '개념 차트에 보내지 못했어요 (꺼져 있나요?) · ' + e.message });
    return false;
  }
}
async function flush() {
  const { queue = [] } = await get('queue');
  if (!queue.length) return;
  await set({ queue: [] });
  for (const it of queue) if (!(await deliver(it))) break;   // 실패하면 deliver가 다시 줄에 넣는다
}

chrome.runtime.onMessage.addListener((msg, _from, reply) => {
  if (msg.type === 'answer' && typeof msg.text === 'string' && msg.text.trim()) {
    (async () => {
      const { enabled = true } = await get('enabled');
      if (!enabled) return;
      await flush();
      await deliver({ text: msg.text.slice(0, 200000), question: msg.question || null, session: msg.session || null });
    })();
  } else if (msg.type === 'flush') {
    flush().then(() => reply(true));
    return true;
  }
  return false;
});
