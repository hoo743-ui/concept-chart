// 05 기록에 묻기 — Atelier 안의 채팅 화면 (11-13: chat/ 화면을 한 웹으로 합침).
// 답은 따로 도는 묻기 서버(chat/chat_server.py, 기본 127.0.0.1:8766)가 기록 값으로만 만든다. 이 화면은 그 답을 읽기 좋게 나눌 뿐이다.
// 서버 계약: GET {CHAT}/api/health → {llm, app, examples} / POST {CHAT}/api/ask {text} → {intent, text[], links[{label, href}], how} 또는 {error}
// 글은 textContent/append로만 넣는다 (HTML로 해석하지 않는다). 묻기 서버가 꺼져 있어도 다른 메뉴는 그대로 된다.
// atelier.js보다 먼저 불러온다(처음 주소가 #/chat이면 render가 곧바로 pageChat을 부른다). h·mascot·deskArt는 부를 때 atelier.js의 것을 쓴다.
// 브랜드 브리프 B(Thinking Space, 11-13): 첫 화면은 아치 별자리 그림 + 환영, 대화가 시작되면 마스코트는 답의 작은 얼굴, 답을 만드는 동안 그 얼굴이 천천히 숨 쉰다.
const AskChat = (() => {
  // 묻기 서버 주소: ?chat=http://127.0.0.1:포트 로 바꿀 수 있다(시험용). 이 PC 주소만 받는다
  const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/;
  const given = new URLSearchParams(location.search).get('chat');
  const CHAT = given && LOCAL.test(given.replace(/\/$/, '')) ? given.replace(/\/$/, '') : 'http://127.0.0.1:8766';
  const KEY = 'concept-chat-v1';         // 이 브라우저에만: 지금 대화 (새로 고쳐도 이어서 보이게)
  const MEM = 'concept-chat-memory-v1';  // 이 브라우저에만: 지난 질문과 나온 개념 ('전에 나눈 대화와 이어져요'용)
  const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 저장 못 해도 대화는 된다 */ } } };
  const safeHref = (x) => (/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(x || '') ? x : null);   // 이 PC의 개념 차트로만
  // 답의 노트 링크({개념 차트}/#/c/{id})는 같은 창의 개념 노트로 연다
  const noteHash = (x) => { try { const u = new URL(x); return /^#\/c\/[^/]+$/.test(u.hash) ? u.hash : null; } catch { return null; } };
  const linkAttrs = (x, title) => (noteHash(x) ? { href: noteHash(x), title } : { href: x, target: '_blank', rel: 'noopener', title });
  const day = (ts) => { const d = new Date(ts); return `${d.getMonth() + 1}/${d.getDate()}`; };
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.motion === 'reduced';
  const KIND = (t) => (/했던가|했었나/.test(t) ? '공부했는지 확인' : /분야/.test(t) ? '분야별로 정리' : /저번|최근|지난/.test(t) ? '최근에 공부한 것' : /학습|순서|공부하면/.test(t) ? '학습 순서 추천' : '물어보기');
  const ENVELOPE = { pasted_content: '붙여 넣은 글', 'agent-message': '다른 에이전트가 보낸 글', 'cross-session-message': '다른 세션이 보낸 글' };
  const tidy = (x) => String(x).replace(/“<(pasted_content|agent-message|cross-session-message)[^”]*”/g, (_, k) => `“(${ENVELOPE[k]})”`);

  let ui = null;           // 화면은 한 번만 만들고 메뉴를 오가도 그대로 둔다 (대화·입력 중인 글 보존)
  let busy = false, examples = [], server = 'checking';

  function avatar() { return mascot('xs'); }
  function botShell(...kids) { return h('article', { class: 'msg bot' }, avatar(), h('div', { class: 'bot-body' }, h('div', { class: 'bot-name' }, 'THYNK'), ...kids)); }

  // 문단: '- ' / '1. ' 줄은 목록으로. 답에 나온 개념 이름(links의 label)은 그 노트 링크로 (답마다 처음 한 번)
  function answerBody(paras, links) {
    const map = new Map(links.map((l) => [l.label, l.href]));
    const used = new Set();
    const labels = [...map.keys()].sort((a, b) => b.length - a.length).map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const rx = labels.length ? new RegExp(labels.join('|'), 'g') : null;
    const inline = (str) => {
      if (!rx) return [str];
      const out = []; let last = 0;
      for (const m of str.matchAll(rx)) {
        if (used.has(m[0])) continue;
        used.add(m[0]);
        if (m.index > last) out.push(str.slice(last, m.index));
        out.push(h('a', { class: 'term', ...linkAttrs(map.get(m[0]), m[0] + ' 개념 노트 열기') }, m[0]));
        last = m.index + m[0].length;
      }
      if (last < str.length) out.push(str.slice(last));
      return out;
    };
    const box = h('div', { class: 'ask-answer' });
    let list = null, listTag = '';
    for (const p of paras) {
      const bullet = p.match(/^\s*[-•]\s+(.*)$/s), num = p.match(/^\s*\d+[.)]\s+(.*)$/s);
      const tg = bullet ? 'ul' : num ? 'ol' : '';
      if (tg) {
        if (!list || listTag !== tg) { list = h(tg); listTag = tg; box.append(list); }
        list.append(h('li', {}, inline((bullet || num)[1])));
      } else { list = null; box.append(h('p', {}, inline(p))); }
    }
    return box;
  }
  // 이어서 물어볼 질문: 서버가 답할 수 있는 종류만
  function followUps(intent, links, asked) {
    const first = links[0];
    const ex = (re) => examples.find((t) => re.test(t));
    const plan = ex(/학습하면|순서/), field = ex(/분야/), recent = ex(/저번|최근/);
    const pick = { plan: [first && `${first.label}, 제가 공부했었나요?`, field], by_field: [recent, first && `${first.label}, 제가 공부했었나요?`], recent: [plan, first && `${first.label}, 제가 공부했었나요?`], check: [plan, recent], define: [first && `${first.label}, 제가 공부했었나요?`, plan], other: [plan, recent, field] }[intent] || [plan, recent];
    return [...new Set(pick.filter(Boolean))].filter((t) => t !== asked).slice(0, 3);
  }
  // 전에 나눈 대화와 이어지는 개념 (이 브라우저에 남은 내 질문 기록에서만 찾는다)
  function contextNotes(links, asked) {
    const mem = store.get(MEM, []);
    const now = new Set(store.get(KEY, []).map((t) => t.q));
    const notes = [];
    for (const l of links) {
      const prev = mem.find((m) => m.q !== asked && !now.has(m.q) && (m.hrefs || []).includes(l.href));
      if (prev && !notes.some((n) => n.q === prev.q)) notes.push({ label: l.label, q: prev.q, ts: prev.ts });
      if (notes.length >= 2) break;
    }
    return notes;
  }
  // 개념 링크가 많으면(분야별 정리 등) 12개만 먼저 보이고 나머지는 눌러서 펼친다
  function linkList(links) {
    const a = (l) => h('a', linkAttrs(l.href, l.label + ' 개념 노트 열기'), l.label);
    const box = h('div', { class: 'ask-links' }, links.slice(0, 12).map(a));
    if (links.length > 12) {
      const more = h('button', { type: 'button', class: 'more', onclick: () => { more.replaceWith(...links.slice(12).map(a)); } }, `나머지 ${links.length - 12}개 보기`);
      box.append(more);
    }
    return box;
  }
  const retry = (label, asked) => h('button', { type: 'button', class: 'btn quiet small', onclick: () => ask(asked) }, label);
  function showMe(text) { ui.log.append(h('div', { class: 'msg me' }, text)); }
  function showAnswer(d, asked) {
    const links = (d.links || []).filter((l) => safeHref(l.href));
    const paras = (d.text || []).filter((t) => String(t).trim()).map(tidy);
    if (!paras.length) return ui.log.append(botShell(h('div', { class: 'ask-state warn' }, h('p', {}, '답을 만들지 못했어요. 다르게 물어봐 주시겠어요?'), retry('다시 물어보기', asked))));
    if (paras.some((t) => /연결하지 못했어요/.test(t))) return ui.log.append(botShell(h('div', { class: 'ask-state warn' }, ...paras.map((t) => h('p', {}, t)), h('p', {}, '개념 차트가 켜지면 다시 물어봐 주세요.'), retry('다시 시도', asked))));
    const ctx = contextNotes(links, asked);
    const fu = followUps(d.intent, links, asked);
    ui.log.append(botShell(answerBody(paras, links),
      links.length ? h('div', { class: 'ask-sec' }, h('h3', {}, '함께 보면 좋은 개념', h('span', { class: 'n' }, `${links.length}개 · 개념 노트로 열려요`)), linkList(links)) : null,
      ctx.length ? h('div', { class: 'ask-sec' }, h('h3', {}, '전에 나눈 대화와 이어져요'), ctx.map((c) => h('p', { class: 'ask-context' }, `‘${c.label}’은(는) ${day(c.ts)}에 물어본 “${c.q}”에서도 나왔어요.`))) : null,
      fu.length ? h('div', { class: 'ask-sec' }, h('h3', {}, '이어서 물어보기'), h('div', { class: 'ask-follow' }, fu.map((t) => h('button', { type: 'button', onclick: () => ask(t) }, t)))) : null,
      d.intent === 'other' ? h('p', { class: 'ask-note' }, '내 공부 기록으로 답할 수 있는 질문에만 답해요. 개념의 뜻은 개념 노트에서 출처와 함께 볼 수 있어요.') : null));
  }
  function showError(title, help, asked) {
    ui.log.append(botShell(h('div', { class: 'ask-state err', role: 'alert' }, h('p', {}, h('strong', {}, title)), h('p', {}, help), retry('다시 시도', asked))));
  }
  function toBottom() { if (ui.log.lastElementChild && document.body.contains(ui.root)) ui.log.lastElementChild.scrollIntoView({ block: 'nearest', behavior: reduced() ? 'auto' : 'smooth' }); }

  function remember(entry) {
    const thread = store.get(KEY, []); thread.push(entry); store.set(KEY, thread.slice(-40));
    if (entry.d && !entry.err) { const mem = store.get(MEM, []); mem.unshift({ q: entry.q, ts: entry.ts, hrefs: (entry.d.links || []).map((l) => l.href) }); store.set(MEM, mem.slice(0, 100)); }
  }
  function setStarted(on) { ui.welcome.hidden = on; ui.reset.hidden = !on; }

  async function ask(text) {
    text = (text || '').trim();
    if (!text || busy) return;
    busy = true; updateSend();
    setStarted(true);
    showMe(text);
    const wait = botShell(h('p', { class: 'ask-note', style: 'margin-top:0' }, h('span', { class: 'dots', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')), '공부 기록을 살펴보고 있어요…'));
    wait.classList.add('waiting'); wait.setAttribute('aria-busy', 'true');
    ui.log.append(wait); toBottom();
    const ts = new Date().toISOString();
    try {
      const r = await fetch(CHAT + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
      let d = null; try { d = await r.json(); } catch { d = null; }
      wait.remove();
      if (!r.ok || !d) { showError('답을 받지 못했어요', (d && d.error) || `서버가 ${r.status} 오류를 보냈어요. 잠시 뒤 다시 물어봐 주세요.`, text); remember({ q: text, ts, err: (d && d.error) || String(r.status) }); }
      else { showAnswer(d, text); remember({ q: text, ts, d }); if (server !== 'on') checkServer(); }
    } catch {
      wait.remove();
      showError('묻기 서버에 연결하지 못했어요', 'python dev.py app 으로 켜져 있는지 확인한 뒤 다시 시도해 주세요.', text);
      if (server !== 'off') checkServer();
    }
    busy = false; updateSend(); toBottom();
  }

  function autosize() { ui.q.style.height = 'auto'; ui.q.style.height = Math.min(ui.q.scrollHeight, 168) + 'px'; }
  function updateSend() { ui.send.disabled = busy || !ui.q.value.trim(); ui.send.textContent = busy ? '답 기다리는 중' : '묻기'; }
  function drawExamples() {
    ui.chips.replaceChildren(...examples.map((t) => h('button', { type: 'button', class: 'ask-card', onclick: () => ask(t) }, h('span', { class: 'kind' }, KIND(t)), h('span', { class: 'q' }, t))));
  }
  function drawRecent() {
    const mem = store.get(MEM, []).slice(0, 3);
    ui.recent.hidden = !mem.length;
    ui.recentList.replaceChildren(...mem.map((m) => h('button', { type: 'button', onclick: () => ask(m.q), title: `${day(m.ts)}에 물어봤어요` }, m.q)));
  }
  // 묻기 서버 상태: 꺼져 있으면 켜는 방법을 보여 주고, 예시 카드 대신 안내만
  async function checkServer() {
    try {
      const r = await fetch(CHAT + '/api/health');
      const d = await r.json();
      server = 'on';
      ui.how.dataset.state = 'on';
      examples = d.examples || [];
      drawExamples();
      ui.how.textContent = d.llm && d.llm.available ? '기록에서만 답해요 · AI가 질문 종류를 골라요' : '기록에서만 답해요 · 낱말 규칙으로 질문을 구분해요';
    } catch {
      server = 'off';
      ui.how.dataset.state = 'off';
      ui.how.textContent = '묻기 서버가 꺼져 있어요';
    }
    ui.offline.hidden = server !== 'off';
  }

  function build() {
    const q = h('textarea', { id: 'ask-q', rows: '1', maxlength: '500', autocomplete: 'off', placeholder: '궁금한 개념이나 공부했던 내용을 물어보세요.' });
    const send = h('button', { class: 'btn primary send', type: 'submit', disabled: true }, '묻기');
    const form = h('form', { class: 'ask-form', onsubmit: (e) => { e.preventDefault(); const t = q.value; if (!t.trim() || busy) return; q.value = ''; autosize(); updateSend(); ask(t); } },
      h('label', { class: 'sr', for: 'ask-q' }, '질문'), q, send);
    const reset = h('button', { type: 'button', class: 'btn quiet small', hidden: true, onclick: () => {
      if (!confirm('지금 대화를 화면에서 지울까요? (개념 차트의 공부 기록은 그대로예요)')) return;
      store.set(KEY, []); ui.log.replaceChildren(); setStarted(false); drawRecent(); q.focus();
    } }, '새 대화');
    const how = h('p', { class: 'ask-how' }, '묻기 서버를 확인하는 중…');
    const offline = h('div', { class: 'ask-state warn', role: 'status', hidden: true },
      h('p', {}, h('strong', {}, '묻기 서버가 꺼져 있어요')),
      h('p', {}, 'python dev.py app 으로 켜면 함께 켜져요. 묻기만 따로 켜려면 python dev.py chat'),
      h('button', { type: 'button', class: 'btn quiet small', onclick: () => checkServer() }, '다시 확인'));
    const chips = h('div', { class: 'ask-cards', 'aria-label': '이렇게 물어볼 수 있어요' });
    const recentList = h('div', { class: 'ask-follow' });
    const recent = h('div', { class: 'ask-recent', hidden: true }, h('h2', {}, '지난번에 물어본 것'), recentList);
    const welcome = h('section', { class: 'ask-welcome reveal', 'aria-labelledby': 'ask-hello' },
      deskArt('ask-art'),
      h('p', { class: 'hello', id: 'ask-hello' }, '안녕하세요! 오늘은 어떤 개념을 함께 정리해 볼까요?'),
      h('p', { class: 'hello-sub' }, '공부한 기록을 바탕으로 답하고, 관련 개념 노트까지 연결해 드려요.'),
      h('p', { class: 'promise' }, '기록에 없는 내용은 지어내지 않아요. 개념의 뜻은 출처가 붙은 개념 노트로 안내해 드려요.'),
      chips, recent);
    const log = h('div', { class: 'ask-log', id: 'ask-log', 'aria-live': 'polite' });
    const root = h('div', { class: 'ask' },
      h('header', { class: 'ask-head' }, h('div', {}, h('p', { class: 'kicker' }, '공부 기록에서 찾아 답해요'), h('h1', { class: 'display' }, '기록에 묻기')), h('div', { class: 'ask-tools' }, how, reset)),
      offline, welcome, log,
      h('div', { class: 'ask-composer glass' }, form, h('p', { class: 'ask-hint' }, h('span', { class: 'keys' }, 'Enter 보내기 · Shift+Enter 줄바꿈'), h('span', {}, '내 공부 기록(진도·열어 본 노트·처음 만난 질문)에서만 답해요'))));
    ui = { root, log, q, send, reset, how, offline, chips, recent, recentList, welcome };
    q.addEventListener('input', () => { autosize(); updateSend(); });
    q.addEventListener('keydown', (e) => {
      // 한글 입력 중(조합 중)의 Enter는 글자 확정이라 보내지 않는다
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); form.requestSubmit(); }
    });
    const thread = store.get(KEY, []);
    if (thread.length) {
      setStarted(true);
      for (const t of thread) { showMe(t.q); if (t.d) showAnswer(t.d, t.q); else showError('답을 받지 못했어요', t.err || '', t.q); }
    } else drawRecent();
    checkServer();
  }

  async function page() {
    if (!ui) build(); else if (server !== 'on') checkServer();
    requestAnimationFrame(() => { autosize(); updateSend(); if (ui.log.childElementCount) toBottom(); ui.q.focus({ preventScroll: true }); });
    return [ui.root];
  }
  return { page, CHAT };
})();
const pageChat = () => AskChat.page();
