// 화면. 서버 호출은 api.js만 거친다. 받은 글은 항상 textContent로 넣는다 (대화 내용이 HTML로 실행되지 않게).
const view = document.getElementById('view');
const statusBar = document.getElementById('status');
let routeNow = '';

function h(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) e.append(kid);
  return e;
}
const safeUrl = (u) => (/^https?:\/\//.test(u || '') ? u : null);
const cHash = (id) => '#/c/' + encodeURIComponent(id);
const when = (ts) => (ts ? new Date(ts).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '');

function lineTag(kind) {
  if (kind === 'ai_checked') return h('span', { class: 'tag ok' }, 'AI 요약 · 근거 확인됨');
  if (kind === 'source') return h('span', { class: 'tag' }, '출처 문장');
  return h('span', { class: 'tag warn' }, '출처 없음');
}

function conceptItem(x) {
  return h('li', {}, h('a', { class: 'item', href: cHash(x.id) },
    h('b', {}, x.label, x.progress === 'review' ? h('span', { class: 'tag warn' }, '다시 볼 것') : null, x.progress === 'known' ? h('span', { class: 'tag ok' }, '이해함') : null),
    h('span', { class: 'line' }, x.line || '아직 믿을 만한 설명을 찾지 못했어요.'), ' ', lineTag(x.line_kind)));
}

// ---------- 오늘 공부 ----------
async function pageToday() {
  const d = await API.today(7);
  const c = d.counts;
  const body = [h('h1', {}, d.items.length ? `오늘 볼 개념 ${d.items.length}개` : '오늘 볼 개념이 없어요'),
    h('p', { class: 'muted' }, `AI 답변에서 찾은 개념 ${c.shown}개 중 이해함 ${c.known}개 · 남은 것 ${c.left}개`)];
  if (d.items.length) body.push(h('ul', { class: 'list' }, d.items.map(conceptItem)));
  else if (!c.shown) body.push(h('div', { class: 'box' }, h('p', {}, 'AI 답변이 쌓이면 여기에 공부할 개념이 나타나요.'), h('p', {}, h('a', { href: '#/answers' }, 'AI 답변 붙여넣기'), '로 바로 시작할 수 있어요.')));
  else body.push(h('p', { class: 'box' }, '지금까지 나온 개념을 모두 이해했다고 표시했어요.'));
  return body;
}

// ---------- 개념 노트 ----------
function aiSentence(text, evidence) {
  return h('div', {}, h('p', { class: 'lead' }, text),
    evidence && evidence.length ? h('details', {}, h('summary', {}, '근거 문장 보기'), evidence.map((e) => h('p', { class: 'evidence' }, e))) : null);
}

function explainBlock(c) {
  const n = c.note || {};
  const src = (c.sources || [])[0];
  const link = src && safeUrl(src.url) ? h('a', { href: src.url, target: '_blank', rel: 'noopener noreferrer' }, '출처 열기') : null;
  if (n.easy) {
    const pass = n.checked ? ` ${n.checked.passed}/${n.checked.total}` : '';
    return [aiSentence(n.easy, n.easy_evidence), h('p', { class: 'muted' }, h('span', { class: 'tag ok', style: 'margin-left:0' }, 'AI 요약 · 근거 확인됨' + pass), ' ', link)];
  }
  if (c.definition) return [h('p', { class: 'lead' }, c.definition), h('p', { class: 'muted' }, h('span', { class: 'tag', style: 'margin-left:0' }, '출처 문장 그대로'), ' ', link)];
  if (c.note_status === 'pending') return [h('p', { class: 'muted' }, '믿을 만한 설명을 찾는 중이에요…')];
  if (n.status === 'wrong_sense') return [h('p', {}, '찾은 설명이 내 대화와 다른 뜻이라 보여 주지 않아요.'), h('p', { class: 'muted' }, '아래 내 대화의 문장으로 맥락을 확인해 보세요.')];
  return [h('p', {}, '믿을 만한 출처에서 설명을 찾지 못했어요. 지어내지 않고 비워 둡니다.'), h('p', { class: 'muted' }, '아래 내 대화의 문장으로 맥락을 확인해 보세요.')];
}

async function pageConcept(id) {
  const c = await API.concept(id);
  const n = c.note || {};
  const body = [h('a', { class: 'back', href: '#/' }, '← 오늘 공부'), h('h1', {}, c.label)];
  if (c.forms && c.forms.length > 1) body.push(h('p', { class: 'muted' }, '다른 표기: ' + c.forms.filter((f) => f !== c.label).join(', ')));
  body.push(h('h2', {}, '이 개념은'), ...explainBlock(c));

  body.push(h('h2', {}, '내 대화에서는'));
  if (c.records && c.records.length) {
    body.push(h('ul', { class: 'list' }, c.records.map((r) => h('li', { class: 'box' }, r.question ? h('p', { class: 'q' }, '내 질문: ' + r.question) : null, h('p', {}, r.snippet), h('p', { class: 'muted' }, when(r.ts))))));
  } else body.push(h('p', { class: 'muted' }, '기록이 없어요.'));

  if (c.practice) {
    const a = h('p', { hidden: true }, h('b', {}, '답: ' + c.practice.answer));
    body.push(h('h2', {}, '빈칸에 들어갈 개념은?'), h('div', { class: 'box' }, h('p', {}, c.practice.blank), h('button', { onclick: (e) => { a.hidden = false; e.target.remove(); } }, '답 보기'), a));
  }
  if (c.related && c.related.length) body.push(h('h2', {}, '함께 나온 개념'), h('div', { class: 'chips' }, c.related.map((r) => h('a', { href: cHash(r.id) }, r.label))));

  const mark = async (status) => { await API.setProgress(c.concept, status); location.hash = '#/'; };
  body.push(h('div', { class: 'actions' }, h('button', { class: 'primary', onclick: () => mark('known') }, '이해했어요'), h('button', { onclick: () => mark('review') }, '다시 볼게요')));
  body.push(h('p', { style: 'margin-top:12px' }, h('button', { class: 'link', onclick: async () => { await API.setFeedback(c.concept, 'not_concept'); location.hash = '#/'; } }, '공부할 개념이 아니에요 (목록에서 숨기기)')));
  return body;
}

// ---------- 답변 읽기 ----------
async function pageAnswers() {
  const d = await API.answers(30);
  const ta = h('textarea', { 'aria-label': 'AI 답변 붙여넣기', placeholder: '터미널이나 Claude·ChatGPT 앱의 AI 답변을 여기에 붙여넣으세요.' });
  const msg = h('span', { class: 'muted', role: 'status' });
  const add = async () => {
    if (!ta.value.trim()) { msg.textContent = '붙여넣은 글이 없어요.'; return; }
    try {
      const r = await API.addText(ta.value);
      msg.textContent = r.added ? '추가했어요. 잠시 뒤 목록에 나타나요.' : '이미 추가한 글이에요.';
      if (r.added) ta.value = '';
    } catch (e) { msg.textContent = e.message; }
  };
  return [h('h1', {}, 'AI 답변 읽기'), h('p', { class: 'muted' }, '답변을 열면 공부할 개념이 표시돼요. 눌러서 바로 뜻을 볼 수 있어요.'),
    h('div', { class: 'box' }, ta, h('div', { class: 'actions', style: 'margin-top:8px;align-items:center' }, h('button', { class: 'primary', onclick: add }, '답변 추가'), msg)),
    h('h2', {}, '최근 답변'),
    d.items.length ? h('ul', { class: 'list' }, d.items.map((a) => h('li', {}, h('a', { class: 'item', href: '#/a/' + encodeURIComponent(a.id) }, h('span', { class: 'line' }, a.preview), h('span', { class: 'muted' }, when(a.ts) + ' · ' + sourceName(a.source)))))) : h('p', { class: 'muted' }, '아직 답변이 없어요.')];
}
const sourceName = (s) => ({ 'claude-code': 'Claude Code', paste: '붙여넣기', 'claude-app': 'Claude 앱', chatgpt: 'ChatGPT' }[s] || s);

function renderMarked(text, terms) {
  // 긴 표기부터 찾아 개념에 표시한다. 영문은 낱말 경계를 지킨다 (git이 digit 안에서 잡히지 않게)
  const map = new Map();
  for (const t of terms) for (const f of t.forms) map.set(f.toLowerCase(), t);
  const seen = new Set();
  const parts = [...map.keys()].sort((a, b) => b.length - a.length).map((f) => f.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).map((f) => (/^[a-z0-9]/.test(f) ? `(?<![A-Za-z0-9_])${f}(?![A-Za-z0-9_])` : f));
  const rx = parts.length ? new RegExp(parts.join('|'), 'gi') : null;
  const plain = (s) => {
    if (!rx) return [s];
    const res = [];
    let last = 0;
    for (const m of s.matchAll(rx)) {
      const t = map.get(m[0].toLowerCase());
      if (m.index > last) res.push(s.slice(last, m.index));
      if (t && !seen.has(t.id)) { seen.add(t.id); res.push(h('mark', {}, h('a', { href: cHash(t.id), title: t.label + ' 노트 열기' }, m[0]))); } else res.push(m[0]);
      last = m.index + m[0].length;
    }
    if (last < s.length) res.push(s.slice(last));
    return res;
  };
  // 글자 꾸밈: **굵게**와 `코드`만 처리한다. 코드 안에는 개념 표시를 하지 않는다
  const inline = (s) => s.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g).flatMap((p) => {
    if (/^`[^`]+`$/.test(p)) return [h('code', {}, p.slice(1, -1))];
    if (/^\*\*[^*]+\*\*$/.test(p)) return [h('strong', {}, ...plain(p.slice(2, -2)))];
    return plain(p);
  });
  const cells = (row) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
  const out = [];
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (/^```/.test(line)) {                            // 코드 상자
      const code = [];
      for (i += 1; i < lines.length && !/^```/.test(lines[i]); i += 1) code.push(lines[i]);
      i += 1;
      out.push(h('pre', {}, code.join('\n')));
    } else if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?[\s:\-|]+\|?\s*$/.test(lines[i + 1] || '')) {   // 표
      const head = cells(line);
      const rows = [];
      for (i += 2; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i += 1) rows.push(cells(lines[i]));
      out.push(h('table', {}, h('thead', {}, h('tr', {}, head.map((c) => h('th', {}, inline(c))))), h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c) => h('td', {}, inline(c))))))));
    } else if (/^#{1,6}\s/.test(line)) {                // 제목
      out.push(h('h3', {}, inline(line.replace(/^#+\s*/, ''))));
      i += 1;
    } else if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {   // 목록
      const ordered = /^\s*\d/.test(line);
      const items = [];
      for (; i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i]); i += 1) items.push(h('li', {}, inline(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ''))));
      out.push(h(ordered ? 'ol' : 'ul', {}, items));
    } else if (/^>\s?/.test(line)) {
      out.push(h('blockquote', {}, inline(line.replace(/^>\s?/, ''))));
      i += 1;
    } else if (!line.trim()) {
      i += 1;
    } else {                                            // 문단
      const para = [];
      for (; i < lines.length && lines[i].trim() && !/^(```|#{1,6}\s|>\s?|\s*([-*+]|\d+[.)])\s+|\s*\|.*\|\s*$)/.test(lines[i]); i += 1) para.push(lines[i]);
      if (!para.length) { para.push(line); i += 1; }
      out.push(h('p', {}, inline(para.join(' '))));
    }
  }
  return h('div', { class: 'md' }, out);
}

function summaryBlock(a) {
  const s = a.summary || {};
  if (s.status === 'ready') {
    return h('div', { class: 'box' }, h('p', { class: 'muted' }, h('span', { class: 'tag ok', style: 'margin-left:0' }, 'AI가 고른 원문 문장')),
      h('ul', { class: 'points' }, s.points.map((p) => h('li', {}, p.text))));
  }
  if (s.status === 'rejected') return h('p', { class: 'box' }, '핵심 문장을 고르지 못했어요. 원문을 읽어 주세요.');
  const msg = h('span', { class: 'muted', role: 'status' });
  const btn = h('button', { onclick: async () => {
    btn.disabled = true;
    try { const r = await API.summarize(a.id); msg.textContent = r.queued ? ' 요약하는 중이에요. 끝나면 여기에 나타나요.' : ' ' + (r.reason || ''); } catch (e) { msg.textContent = ' ' + e.message; btn.disabled = false; }
  } }, '이 답변 요약하기');
  return h('div', {}, btn, msg);
}

async function pageAnswer(id) {
  const a = await API.answer(id);
  return [h('a', { class: 'back', href: '#/answers' }, '← 답변 목록'), h('h1', {}, 'AI 답변'), h('p', { class: 'muted' }, when(a.ts) + ' · ' + sourceName(a.source)),
    a.question ? h('p', { class: 'q' }, '내 질문: ' + a.question) : null,
    h('h2', {}, '요약'), summaryBlock(a),
    h('h2', {}, '이 답변의 개념'), a.terms.length ? h('div', { class: 'chips' }, a.terms.map((t) => h('a', { href: cHash(t.id) }, t.label))) : h('p', { class: 'muted' }, '공부할 개념을 찾지 못했어요.'),
    h('h2', {}, '원문'), h('div', { class: 'box' }, renderMarked(a.text, a.terms))];
}

// ---------- 전체 개념 ----------
async function pageAll(hidden) {
  const d = await API.concepts(hidden ? 'hidden' : 'show', 500);
  const list = h('ul', { class: 'list' });
  const draw = (q) => {
    list.replaceChildren(...d.items.filter((x) => x.label.toLowerCase().includes(q.toLowerCase())).map((x) => (hidden
      ? h('li', { class: 'box' }, h('b', {}, x.label), x.gate && x.gate.candidate ? h('span', { class: 'tag' }, '후보') : null, ' ', h('button', { class: 'link', onclick: async () => { await API.setFeedback(x.id, 'concept'); render(); } }, '공부할 개념이에요'))
      : conceptItem(x))));
  };
  draw('');
  return [h('h1', {}, hidden ? `숨긴 낱말 ${d.items.length}개` : `전체 개념 ${d.items.length}개`),
    h('p', { class: 'muted' }, hidden ? '일상어로 판단해 숨긴 낱말이에요. 잘못 숨겼다면 되돌릴 수 있어요.' : '중요도 순서예요.'),
    h('input', { type: 'search', placeholder: '찾기', 'aria-label': '개념 찾기', oninput: (e) => draw(e.target.value) }),
    list, h('p', { style: 'margin-top:16px' }, h('a', { href: hidden ? '#/all' : '#/hidden' }, hidden ? '← 전체 개념으로' : '숨긴 낱말 보기'))];
}

// ---------- 길 찾기 ----------
async function render() {
  const route = location.hash.slice(1) || '/';
  const parts = route.split('/').filter(Boolean);
  const same = route === routeNow;
  routeNow = route;
  document.querySelectorAll('nav a').forEach((a) => a.removeAttribute('aria-current'));
  const tab = parts[0] === 'answers' || parts[0] === 'a' ? 'answers' : parts[0] === 'all' || parts[0] === 'hidden' ? 'all' : 'today';
  document.querySelector(`nav a[data-tab="${tab}"]`).setAttribute('aria-current', 'page');
  try {
    let nodes;
    if (parts[0] === 'c') nodes = await pageConcept(decodeURIComponent(parts[1]));
    else if (parts[0] === 'answers') nodes = await pageAnswers();
    else if (parts[0] === 'a') nodes = await pageAnswer(decodeURIComponent(parts[1]));
    else if (parts[0] === 'all') nodes = await pageAll(false);
    else if (parts[0] === 'hidden') nodes = await pageAll(true);
    else nodes = await pageToday();
    if (route !== routeNow) return;                     // 그사이 다른 화면으로 갔다
    const active = document.activeElement;
    if (same && active && ['TEXTAREA', 'INPUT'].includes(active.tagName)) return;   // 입력 중에는 다시 그리지 않는다
    view.replaceChildren(...nodes.filter(Boolean));
    if (!same) { window.scrollTo(0, 0); view.focus({ preventScroll: true }); }
  } catch (e) {
    view.replaceChildren(h('h1', {}, '불러오지 못했어요'), h('p', {}, e.message), h('p', { class: 'muted' }, '서버가 켜져 있는지 확인해 주세요: python dev.py app'));
  }
  renderStatus();
}

async function renderStatus() {
  try {
    const s = await API.health();
    const llm = s.llm.available ? 'AI 요약 켜짐 (이 PC에서 실행)' : 'AI 요약 꺼짐: 출처 문장만 보여 줘요';
    const q = s.jobs && s.jobs.queued ? ` · 준비 중 ${s.jobs.queued}건` : '';
    statusBar.textContent = (API.demo ? '데모 화면 · ' : '') + llm + q;
  } catch { statusBar.textContent = ''; }
}

let timer;
window.addEventListener('hashchange', render);
API.onUpdate(() => { clearTimeout(timer); timer = setTimeout(render, 800); });
render();
