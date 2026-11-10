// 내 공부 기록에 묻기 — 화면. 글은 append(문자열)로만 넣는다 (HTML로 해석하지 않는다)
const log = document.getElementById('log');

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  for (const k of kids) if (k != null) e.append(k);
  return e;
}

function show(who, paragraphs, links) {
  const box = el('div', { class: 'msg ' + who });
  for (const p of paragraphs) box.append(el('p', {}, p));
  if (links && links.length) {
    const row = el('div', { class: 'links' });
    for (const l of links) if (/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(l.href)) row.append(el('a', { href: l.href, target: '_blank', rel: 'noopener' }, l.label));
    box.append(row);
  }
  log.append(box);
  box.scrollIntoView({ block: 'end' });
}

async function ask(text) {
  show('me', [text]);
  try {
    const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    const d = await r.json();
    if (!r.ok) return show('bot', [d.error || '오류가 났어요.']);
    show('bot', d.text, d.links);
  } catch (e) {
    show('bot', ['이 앱의 서버에 연결하지 못했어요.']);
  }
}

document.getElementById('f').addEventListener('submit', (e) => {
  e.preventDefault();
  const q = document.getElementById('q');
  if (q.value.trim()) ask(q.value.trim());
  q.value = '';
});

fetch('/api/health').then((r) => r.json()).then((d) => {
  document.getElementById('how').textContent = d.llm.available ? '' : '(LLM이 꺼져 있어 낱말 규칙으로 질문을 구분해요)';
  const chips = document.getElementById('chips');
  for (const ex of d.examples) chips.append(el('button', { type: 'button' }, ex));
  chips.addEventListener('click', (e) => { if (e.target.tagName === 'BUTTON') ask(e.target.textContent); });
}).catch(() => {});
