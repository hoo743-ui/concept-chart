// Cognitive Atelier 화면. 서버 호출은 api.js만 거친다(docs/API.md). 받은 글은 항상 textContent로 넣는다.
// 11-13부터 서버 첫 화면(index.html이 이리로 넘긴다). 예전 화면(classic.html·app.js)은 답변 붙여넣기용으로 남아 있다. 지어낸 설명·출처는 만들지 않는다.
const view = document.getElementById('view');
const NS = 'http://www.w3.org/2000/svg';
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
function s(tag, attrs = {}, ...kids) { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); for (const k of kids) e.append(k); return e; }
const cHash = (id) => '#/c/' + encodeURIComponent(id);
const aHash = (id) => '#/a/' + encodeURIComponent(id);
const pad = (n) => String(n).padStart(2, '0');
const when = (ts) => (ts ? new Date(ts).toLocaleString('ko-KR', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '');
const dayOf = (ts) => (ts ? new Date(ts).toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }) : '날짜 없음');
const time = (ts) => (ts ? new Date(ts).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false }) : '');
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : null);
const prettyUrl = (u) => { try { const x = new URL(u); return x.host + decodeURIComponent(x.pathname); } catch { return u; } };
// 목록에서는 짧게 (전문은 노트·원문에서). 글자를 지어내지 않고 자르기만 한다
const clip = (t, n) => { t = (t || '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n).replace(/\s\S*$/, '') + '…' : t; };
const paras = (t) => (t || '').split(/\n\s*\n|\n/).map((x) => x.trim()).filter(Boolean);
const PROG = { new: '처음 공부', review: '다시 볼 개념', known: '이해한 개념' };
const TAG = { ai_checked: ['checked', '근거 확인됨'], source: ['source', '출처 원문'], none: ['none', '설명 없음'], pending: ['pending', '준비 중'], own: ['own', '내 대화 문장'] };
const NO_LINE = '아직 믿을 만한 설명을 찾지 못했어요.';
const tag = (kind) => h('span', { class: 'tag ' + TAG[kind][0] }, TAG[kind][1]);
const prog = (p) => h('span', { class: 'prog ' + p }, PROG[p] || '');
const marker = (no, label, count) => h('h2', { class: 'marker' }, label, count !== undefined ? h('span', { class: 'count' }, String(count)) : null);   // 번호 표식(§)은 없앴다(3차)
const sourceName = (x) => ({ 'claude-code': 'Claude Code', paste: '붙여넣기', 'claude-app': 'Claude 앱', 'claude-web': 'Claude 웹', chatgpt: 'ChatGPT' }[x] || x || '');
const head = (kicker, title, lead) => h('header', { class: 'page-head reveal' }, h('p', { class: 'kicker' }, kicker), h('h1', { class: 'display' }, title), lead ? h('p', { class: 'lead' }, lead) : null);
const emptyBox = (title, text, action) => h('div', { class: 'sheet empty-box' }, h('h2', {}, title), h('p', { class: 'sub' }, text), action || null);
// 영문 약어의 우리말 이름: 출처 문장 안에 '우리말(영어…, 약어)' 또는 '약어(…, 우리말)'로 실제로 적혀 있을 때만 그대로 뽑는다. 없으면 null (지어내지 않는다)
const PARTICLE = /(에서|에게|으로|에|의|은|는|이|가|을|를|로|와|과|도|만)$/;
function aliasOf(label, text) {
  if (!label || !text || /[가-힣]/.test(label) || !/[A-Za-z]/.test(label)) return null;
  const esc = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  let m = text.match(new RegExp('((?:[가-힣]+\\s){0,3}[가-힣]+)\\s*\\([^()]*?(?<![A-Za-z])' + esc + '(?![A-Za-z])', 'i'));
  if (m) { const words = m[1].split(/\s+/); while (words.length > 1 && PARTICLE.test(words[0])) words.shift(); return words.join(' '); }
  m = text.match(new RegExp('(?<![A-Za-z])' + esc + '\\s*\\([^()]*?[,，]\\s*([가-힣][가-힣\\s]{1,20}?)\\s*\\)', 'i'));
  return m ? m[1].trim() : null;
}
const firstSentence = (t) => { const m = (t || '').match(/^.+?(?:다\.|요\.|\.)(?=\s|$)/); return m ? m[0] : (t || ''); };
const DAY = 864e5;
const shortDay = (ts) => new Date(ts).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' });
const midnight = (ts) => { const d = new Date(ts); return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); };
const daysBetween = (a, b) => Math.round((midnight(b) - midnight(a)) / DAY);   // 달력 날짜 차이 (11월 8일 → 12일 = 4일), 화면의 날짜와 맞춘다
// 다시 나온 개념(재발견): 처음 만난 뒤 하루 이상 지나 다시 나왔고, 대화 2개 이상에 나왔고, 그게 최근 14일 안.
// 목록 API의 실제 값(origin.ts·last_seen·sessions)만 쓴다. 학습 상태를 추정하지 않는다
function resurfaced(items, now = Date.now()) {
  return items.filter((x) => x.origin && x.origin.ts && x.last_seen && (x.sessions || 0) >= 2 && daysBetween(x.origin.ts, x.last_seen) >= 1 && now - new Date(x.last_seen) <= 14 * DAY)
    .map((x) => ({ ...x, gap: daysBetween(x.origin.ts, x.last_seen) }))
    .sort((a, b) => String(b.last_seen).localeCompare(String(a.last_seen)) || b.gap - a.gap || a.rank - b.rank);
}
const mascot = (cls, alt) => h('img', { class: 'mascot ' + cls, src: 'mascot.png', alt: alt || '', width: 320, height: 320, decoding: 'async',
  onerror: (e) => e.currentTarget.replaceWith(h('span', { class: 'mascot mascot-fallback ' + cls, 'aria-hidden': 'true' }, '차')) });

// ---------- 01 오늘 공부 ----------
function entry(x, i, seen) {
  const empty = !x.line;
  return h('li', {}, h('a', { class: `entry ${x.progress} reveal`, href: cHash(x.id), style: `animation-delay:${Math.min(i, 8) * 45}ms` },
    h('span', { class: 'no', 'aria-hidden': 'true' }, pad(i + 1)),
    h('span', {}, h('span', { class: 'head' }, h('span', { class: 'label' }, x.label), aliasOf(x.label, x.line) ? h('span', { class: 'alias' }, aliasOf(x.label, x.line)) : null, prog(x.progress), seen ? h('span', { class: 'seen' }, '읽어 봄') : null),
      h('p', { class: 'line' + (empty ? ' empty' : '') }, empty ? NO_LINE : clip(x.line, 72))),
    h('span', { class: 'side' }, tag(x.line_kind in TAG ? x.line_kind : 'none'))));
}
function welcomePage() {
  // 첫 방문 (11-13 THYNK 포스터 구도): 워드마크 · 한 줄 약속 · 세 걸음 · 행동 둘. 글은 적게, 한눈에
  const step = (n, t) => h('li', {}, h('span', { class: 'n', 'aria-hidden': 'true' }, n), h('b', {}, t));
  return [h('section', { class: 'welcome-hero reveal' },
    h('div', { class: 'welcome-copy' },
      h('h1', { class: 'display brand-display' }, 'THYNK', h('i', { class: 'brand-dot', 'aria-hidden': 'true' }, '.')),
      h('p', { class: 'lead welcome-promise' }, '생각을 모으고, 지식을 키우다.'),
      h('ol', { class: 'value-steps' },
        step('1', 'AI와 나눈 답변을 이 PC에 모아요'),
        step('2', '답변 속 개념을 출처가 붙은 노트로'),
        step('3', '하루 세 개씩, 한 장씩 읽어요')),
      h('div', { class: 'row' }, h('a', { class: 'btn primary', href: 'classic.html#/answers' }, '답변 붙여넣기'), h('a', { class: 'btn quiet', href: '#/chat' }, '기록에 묻기')),
      h('p', { class: 'meta' }, 'Claude Code에서 평소처럼 공부해도 답변이 저절로 모여요.')),
    deskArt())];
}
function growthStrip(all, opened, re) {
  const n = all.length; if (!n) return null;
  const withLine = all.filter((x) => x.line).length, read = all.filter((x) => opened.has(x.id)).length;
  const cell = (b, t) => h('div', { class: 'g' }, h('b', {}, b), h('span', {}, t));
  return h('section', { class: 'growth reveal', 'aria-label': '지금까지 쌓인 것' }, h('p', { class: 'kicker' }, '지금까지 쌓인 것'),
    h('div', { class: 'gs' }, cell(String(n), '모인 개념'), cell(`${withLine}`, `설명이 붙은 개념 · ${Math.round((withLine / n) * 100)}%`), cell(String(read), '열어 본 개념'), cell(String(re.length), '다른 날 다시 나온 개념')),
    h('a', { class: 'link', href: '#/all' }, '전체 개념 보기 →'));
}
function rediscover(re, opened) {
  const list = re.slice(0, 3);   // 11-13 사용자 지적(빽빽함): 한 줄 3개만, 나머지는 '모두 보기'
  return h('section', { class: 'rediscover reveal', 'aria-labelledby': 're-h' },
    h('h2', { class: 'marker', id: 're-h' }, '다시 나온 개념', re.length ? h('span', { class: 'count' }, `${re.length}개`) : null),
    re.length ? [h('p', { class: 'sub' }, '예전에 처음 만난 개념이 다른 날 대화에 다시 나왔어요. 지난번 공부와 이어서 보세요.'),
      h('ul', { class: 're-list' }, list.map((x) => h('li', {}, h('a', { class: 're-card ' + x.progress, href: cHash(x.id) },
        h('span', { class: 're-name' }, x.label, opened.has(x.id) ? h('span', { class: 'seen' }, '읽어 봄') : null),
        h('span', { class: 're-when' }, h('span', {}, shortDay(x.origin.ts) + ' 처음'), h('span', { class: 'arrow', 'aria-hidden': 'true' }, '→'), h('span', {}, shortDay(x.last_seen) + ' 다시')),
        h('span', { class: 'meta' }, `${x.gap}일 만에 · 대화 ${x.sessions}개에서 나옴`), prog(x.progress))))),
      re.length > list.length ? h('a', { class: 'link', href: '#/all/re' }, `다시 나온 개념 ${re.length}개 모두 보기 →`) : null]
      : h('p', { class: 'sub' }, '아직 다시 나온 개념이 없어요. 처음 만난 날과 다른 날 대화에 같은 개념이 나오면 여기에 모여요.'));
}
// 11-13 '고요한 공부'(사용자 승인): 한 번에 한 개념, 하루 분량에 끝이 있고, 숫자·목록은 '자세히' 아래에서 기다린다
const DAILY = 3;   // 하루에 보는 개념 수 (바꿀 곳은 여기 한 곳)
const LINE_SAY = { ai_checked: '출처 문장으로 확인한 쉬운 설명이에요', source: '출처 문장을 그대로 옮긴 설명이에요', own: '내 대화에 나온 문장이에요', pending: '설명을 준비하는 중이에요', none: NO_LINE };
const say = (kind) => h('p', { class: 'say ' + (TAG[kind] || TAG.none)[0] }, LINE_SAY[kind] || NO_LINE);
const isToday = (ts) => ts && new Date(ts).toDateString() === new Date().toDateString();
const calmMotion = () => !(document.documentElement.dataset.motion === 'reduced' || matchMedia('(prefers-reduced-motion: reduce)').matches);
const pause = (ms) => new Promise((r) => setTimeout(r, calmMotion() ? ms : 0));
let quietUntil = 0;   // 이 화면에서 직접 표시한 직후에는 새 기록 알림으로 화면을 다시 그리지 않는다 (넘김이 끊기지 않게)
function studyFlow(items, opened, hist, origins) {
  const marked = new Map(hist.filter((x) => x.kind === 'marked' && isToday(x.ts)).map((x) => [x.id, x.status]));
  const rank = (x) => (x.progress === 'review' ? 0 : 1) + (opened.has(x.id) ? 2 : 0);   // 다시 볼 개념, 아직 안 열어 본 개념부터
  const queue = items.filter((x) => !marked.has(x.id) && x.progress !== 'known').sort((a, b) => rank(a) - rank(b));
  let goal = Math.max(DAILY, marked.size), done = marked.size;
  const tally = { known: 0, review: 0 };
  for (const v of marked.values()) if (v in tally) tally[v]++;
  const dots = h('div', { class: 'flow-dots', 'aria-hidden': 'true' });
  const count = h('span', { class: 'flow-count' });
  const stage = h('div', { class: 'flow-stage', 'aria-live': 'polite' });
  const paint = () => {
    dots.replaceChildren(...Array.from({ length: goal }, (_, i) => h('i', { class: i < done ? 'on' : '' })));
    count.textContent = done >= goal || !queue.length ? `오늘 ${done}개를 봤어요` : `${done + 1}번째 · 오늘 ${goal}개`;
  };
  const card = (x) => {
    const from = origins.get(x.id);
    const fail = h('p', { class: 'meta', role: 'status' });
    const go = (status) => (e) => mark(x, status, fail, e.currentTarget);
    return h('article', { class: 'flow-card', 'data-id': x.id },
      from ? h('p', { class: 'flow-from' }, from) : null,
      h('h2', { class: 'flow-name' }, h('a', { href: cHash(x.id) }, x.label)),
      h('p', { class: 'flow-line' + (x.line ? '' : ' empty') }, x.line || NO_LINE),
      x.line ? say(x.line_kind in TAG ? x.line_kind : 'none') : null,
      h('div', { class: 'flow-acts' },
        h('button', { class: 'btn primary', type: 'button', onclick: go('known') }, '이해했어요'),
        h('button', { class: 'btn quiet', type: 'button', onclick: go('review') }, '다시 볼게요'),
        h('a', { class: 'link', href: cHash(x.id) }, '노트 펼쳐 읽기 →')), fail);
  };
  const end = () => h('div', { class: 'flow-end' },
    h('p', { class: 'flow-end-big' }, queue.length ? '오늘 공부는 여기까지예요.' : '오늘 볼 개념을 모두 봤어요.'),
    h('p', { class: 'sub' }, `이해한 개념 ${tally.known}개 · 다시 볼 개념 ${tally.review}개` + (tally.review ? '. 다시 볼 개념은 다음에 먼저 보여 드려요.' : '.')),
    h('div', { class: 'row' },
      queue.length ? h('button', { class: 'btn quiet', type: 'button', onclick: () => { goal++; show(true); } }, '하나 더 보기') : null,
      h('a', { class: 'btn quiet', href: '#/all' }, '전체 개념 보기')));
  const show = (focus) => {
    paint();
    stage.replaceChildren(done < goal && queue.length ? card(queue[0]) : end());
    if (focus) { const f = stage.querySelector('.btn'); if (f) f.focus({ preventScroll: true }); }
  };
  async function mark(x, status, fail, btn) {
    const btns = [...stage.querySelectorAll('button')];
    btns.forEach((b) => (b.disabled = true));
    quietUntil = Date.now() + 4000;
    try { await API.setProgress(x.id, status); } catch (e) { btns.forEach((b) => (b.disabled = false)); fail.textContent = '저장하지 못했어요: ' + e.message; return; }
    tally[status]++; done++; queue.shift();
    btn.textContent = status === 'known' ? '이해했어요 ✓' : '다시 볼 개념에 넣었어요 ✓'; btn.classList.add('done');
    await pause(260);
    stage.classList.add('out'); await pause(520);   // 間: 넘길 때 잠깐 비는 시간
    show(true); stage.classList.remove('out');
  }
  show(false);
  return h('section', { class: 'flow reveal', 'aria-label': '오늘 볼 개념' }, h('div', { class: 'flow-bar' }, count, dots), stage);
}
// 브랜드 그림 (11-13 THYNK 포스터): 아치 안의 밤하늘 별자리 + 책 읽는 마스코트. 그림은 읽기 도구에 숨기고, 겹친 단추(바로 가기 말풍선, atelier-notes.js)만 읽힌다
const starD = (x, y, r) => `M${x} ${y - r}L${x + r * .25} ${y - r * .25}L${x + r} ${y}L${x + r * .25} ${y + r * .25}L${x} ${y + r}L${x - r * .25} ${y + r * .25}L${x - r} ${y}L${x - r * .25} ${y - r * .25}Z`;   // 네 갈래 별 (그림·관련 개념 별자리가 같이 씀)
function deskArt(extra) {
  const sky = s('svg', { class: 'arch-sky', viewBox: '0 0 300 220', 'aria-hidden': 'true' });
  const star = (x, y, r) => s('path', { d: starD(x, y, r), class: 'spark' });
  const line = (pts) => { sky.append(s('polyline', { points: pts.map((p) => p.join(',')).join(' '), class: 'cline' })); for (const [x, y] of pts) sky.append(s('circle', { cx: x, cy: y, r: 2.4, class: 'cdot' })); };
  line([[176, 46], [206, 34], [222, 62], [252, 52]]);
  line([[200, 118], [222, 100], [244, 112], [232, 134]]);
  sky.append(star(96, 70, 7), star(140, 132, 4), star(270, 92, 5));
  const fig = h('figure', { class: 'desk-art reveal' + (extra ? ' ' + extra : '') }, sky, mascot('art'));
  return typeof MyNotes === 'object' ? MyNotes.attachArt(fig) : fig;
}
async function pageToday() {
  const [d, hist, allD] = await Promise.all([API.today(7), API.history(500).then((x) => x.items).catch(() => []), API.concepts('show', 5000).catch(() => ({ items: [] }))]);
  const opened = new Set(hist.filter((x) => x.kind === 'opened').map((x) => x.id));
  const c = d.counts, groups = d.groups || [];
  const all = allD.items || [];
  if (!all.length && !groups.length && !c.shown && !c.known) return welcomePage();
  const re = resurfaced(all);
  // 목록 API의 질문은 첫 줄(80자)만 온다. 봉투(<pasted_content …>)면 안쪽 제목을 보려고 답변 API(읽기 전용, 기록 안 남김)에서 질문 500자를 받는다
  const fulls = await Promise.all(groups.map((g) => (g.answer && g.question && Render.envelope(g.question) ? API.answer(g.answer).then((a) => a.question).catch(() => null) : null)));
  const items = groups.flatMap((g) => g.items);
  const origins = new Map(groups.flatMap((g, gi) => g.items.map((x) => [x.id, g.question ? qshort(fulls[gi] || g.question) + ' 나왔어요' : null])));
  const head = h('header', { class: 'page-head calm-head reveal' },
    h('p', { class: 'kicker' }, new Date().toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' })),
    h('h1', { class: 'display' }, '오늘 공부'),
    groups.length ? null : h('p', { class: 'lead' }, 'AI 답변이 쌓이면 여기에 공부할 개념이 나타나요.'));
  const ledger = h('div', { class: 'ledger-inner' }, marker('', '질문별로 볼 개념', `질문 ${groups.length}개 · 개념 ${items.length}개`));
  const FIRST_Q = 3;   // 11-13 사용자 지적(빽빽함): 질문 묶음은 처음 3개만, 나머지는 단추로 펼친다
  const rest = h('div', { class: 'group-rest', hidden: true });
  groups.forEach((g, gi) => {
    let n = 0;
    const seenHere = g.items.filter((x) => opened.has(x.id)).length;
    (gi < FIRST_Q ? ledger : rest).append(h('div', { class: 'group' },
      h('div', { class: 'q' }, h('p', { class: 'kicker' }, `질문 ${gi + 1}`),
        g.question ? Render.question(g.question, { full: fulls[gi] || g.question }) : h('p', { class: 'qtitle' }, g.answer ? '질문 없이 붙여 넣은 답변' : '기록이 남지 않은 대화'),
        h('p', { class: 'count' }, `개념 ${g.items.length + (g.more ? g.more.length : 0)}개 · 읽어 봄 ${seenHere}`),
        g.ts ? h('span', { class: 'meta' }, when(g.ts) + '에 물었어요') : null,
        g.answer ? h('a', { class: 'link', href: aHash(g.answer) }, '원래 답변 보기 →') : null),
      h('div', {}, h('ul', { class: 'entries' }, g.items.map((x) => entry(x, n++, opened.has(x.id)))),
        g.more && g.more.length ? h('details', { class: 'more' }, h('summary', {}, `이 질문의 개념 ${g.more.length}개 더 보기`), h('div', { class: 'chips' }, g.more.map((m) => h('a', { href: cHash(m.id) }, m.label + (m.extra ? ' · 추가' : ''))))) : null)));
  });
  if (groups.length > FIRST_Q) {
    const btn = h('button', { class: 'btn quiet group-more', type: 'button', onclick: () => { rest.hidden = false; btn.remove(); } }, `나머지 질문 ${groups.length - FIRST_Q}개 보기`);
    ledger.append(rest, btn);
  }
  const flow = groups.length ? studyFlow(items, opened, hist, origins)
    : c.shown ? emptyBox('오늘 볼 개념을 모두 읽었어요', '지금까지 나온 개념을 모두 이해했다고 표시했어요. 전체 개념에서 다시 읽을 수 있어요.', h('a', { class: 'btn quiet', href: '#/all' }, '전체 개념 보기'))
    : emptyBox('첫 배움은 답변 하나에서 시작해요', 'AI 답변을 붙여넣거나 Claude Code를 쓰면, 그 안에서 공부할 개념을 모아 드려요.', h('a', { class: 'btn primary', href: 'classic.html#/answers' }, '답변 붙여넣기'));
  // 숫자·목록은 물을 때만. 펼친 상태는 이 브라우저에 기억
  let open = false; try { open = localStorage.getItem('atelier-today-more') === '1'; } catch { /* 저장 못 해도 동작 */ }
  const more = h('details', { class: 'today-more' },
    h('summary', {}, h('span', { class: 'k' }, '자세히'), h('span', { class: 'meta' }, `남은 개념 ${c.left} · 다시 나온 개념 ${re.length} · 오늘 목록 ${items.length}개`)),
    growthStrip(all, opened, re), rediscover(re, opened), groups.length ? h('section', { class: 'ledger' }, ledger) : null);
  more.open = open;
  more.addEventListener('toggle', () => { try { localStorage.setItem('atelier-today-more', more.open ? '1' : ''); } catch { /* 무시 */ } });
  return [h('div', { class: 'today-grid' }, h('div', { class: 'today-main' }, head, flow), deskArt()), more];
}

// ---------- 02 개념 노트 ----------
// 관련 개념: 밤하늘 별자리 (브랜드 브리프 C, 11-13). 이웃끼리 잇는 옅은 고리 + 가운데로 모이는 점선, 점은 별
function relatedMap(label, related) {
  const W = 260, H = 210, cx = W / 2, cy = H / 2, svg = s('svg', { class: 'related-map', viewBox: `0 0 ${W} ${H}`, 'aria-hidden': 'true' });
  const nodes = related.slice(0, 6).map((r, i, arr) => { const a = -Math.PI / 2 + (i / arr.length) * Math.PI * 2; return { r, x: cx + Math.cos(a) * 88, y: cy + Math.sin(a) * 70 }; });
  if (nodes.length > 2) svg.append(s('polygon', { points: nodes.map((n) => `${n.x},${n.y}`).join(' '), class: 'ring' }));
  for (const n of nodes) svg.append(s('line', { x1: cx, y1: cy, x2: n.x, y2: n.y, class: 'spoke' }));
  for (const n of nodes) { svg.append(s('path', { d: starD(n.x, n.y, 6), class: 'star' })); svg.append(s('text', { x: n.x, y: n.y + (n.y < cy ? -11 : 19), 'text-anchor': n.x < cx - 10 ? 'start' : n.x > cx + 10 ? 'end' : 'middle', dx: n.x < cx - 10 ? -8 : n.x > cx + 10 ? 8 : 0 }, clip(n.r.label, 12))); }
  svg.append(s('path', { d: starD(cx, cy, 11), class: 'star center' }));
  svg.append(s('text', { x: cx, y: cy + 27, 'text-anchor': 'middle', class: 'center' }, clip(label, 14)));
  return svg;
}
const prose = (t, cls) => h('div', { class: 'prose ' + (cls || '') }, paras(t).map((p) => h('p', {}, p)));
function explain(c) {
  const n = c.note || {};
  if (n.easy) return h('section', {}, marker('', '한 문장으로'), h('div', { class: 'oneline' }, tag('ai_checked'), prose(n.easy, 'easy')),
    n.easy_evidence && n.easy_evidence.length ? h('div', { class: 'evidence' }, h('span', { class: 'k' }, '이 문장만 보고 쉽게 풀었어요 (근거 문장)'), n.easy_evidence.map((e) => h('p', {}, '“' + e + '”'))) : null);
  if (n.status === 'wrong_sense') return h('section', {}, marker('', '개념 설명'), tag('none'), h('div', { class: 'notice none' }, h('strong', {}, '찾은 설명이 내 대화와 다른 뜻이라 보여 주지 않아요.'), h('span', { class: 'meta' }, '아래 내 대화의 문장으로 맥락을 확인해 보세요.')));
  if (c.definition) { const one = firstSentence(c.definition), rest = c.definition.slice(one.length).trim(); return h('section', {}, marker('', '한 문장으로'), h('div', { class: 'oneline' }, tag('source'), h('p', { class: 'easy' }, one)), rest ? h('div', {}, h('h3', { class: 'h3' }, '더 읽기'), prose(rest)) : null); }
  if (c.note_status === 'pending') return h('section', {}, marker('', '개념 설명'), tag('pending'), h('div', { class: 'notice pending' }, h('strong', {}, '믿을 만한 설명을 찾는 중이에요.'), h('span', { class: 'meta' }, '근거 대조를 통과한 설명이 준비되면 여기에 나타나요.')));
  return h('section', {}, marker('', '개념 설명'), tag('none'), h('div', { class: 'notice none' }, h('strong', {}, NO_LINE), h('span', { class: 'meta' }, '지어내지 않고 비워 둡니다. 아래 내 대화의 문장으로 맥락을 확인해 보세요.')));
}
// 이번에 열기 전의 '열어 봄·진도 표시' (노트 API가 열 때마다 기록을 남기므로, 화면에 들어올 때 먼저 한 번 받아 둔다)
const beforeOpen = new Map();
function timeline(c, before) {
  const ev = [];
  const day = (ts) => new Date(ts).toLocaleDateString('ko-KR');
  if (c.origin && c.origin.ts) ev.push({ ts: c.origin.ts, k: '처음 만남', t: c.origin.question ? qshort(c.origin.question) + ' 처음 나왔어요' : '질문 없이 붙여 넣은 답변에서 처음 나왔어요', href: c.origin.answer ? aHash(c.origin.answer) : null });
  const firstDay = c.origin && c.origin.ts ? day(c.origin.ts) : null;
  const days = new Map();
  for (const r of c.records || []) { if (!r.ts || day(r.ts) === firstDay) continue; const k = day(r.ts); const v = days.get(k) || { ts: r.ts, n: 0 }; v.n++; if (r.ts < v.ts) v.ts = r.ts; days.set(k, v); }
  for (const v of days.values()) ev.push({ ts: v.ts, k: '다시 나옴', t: `대화 문장 ${v.n}개에 나왔어요` });
  if (c.last_seen && day(c.last_seen) !== firstDay && !days.has(day(c.last_seen))) ev.push({ ts: c.last_seen, k: '가장 최근에 나옴', t: '대화에 다시 나왔어요' });
  for (const x of before) {
    if (x.kind === 'opened') ev.push({ ts: x.ts, k: '노트를 열어 봄', t: '이번에 열기 전, 마지막으로 열어 본 때' });
    if (x.kind === 'marked') ev.push({ ts: x.ts, k: '진도 표시', t: `‘${PROG[x.status] || x.status}’로 표시했어요` });
  }
  ev.sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  if (!ev.length) return null;
  return h('section', { class: 'tl-wrap' }, marker('', '나와 이 개념의 시간'),
    h('ol', { class: 'timeline' }, ev.map((e) => h('li', { class: e.k === '처음 만남' ? 'first' : '' }, h('time', { datetime: e.ts }, when(e.ts)), h('b', {}, e.k), h('span', {}, e.t), e.href ? h('a', { class: 'link', href: e.href }, '그 답변 보기 →') : null))),
    h('p', { class: 'meta' }, '기록에 남은 일만 보여요. 열어 본 기록과 진도 표시는 가장 최근 것 하나씩만 남아요.' + (c.next_cursor ? ' 이 개념이 나온 대화 문장은 일부만 불러왔어요.' : '')));
}
async function pageConcept(id) {
  if (!beforeOpen.has(id)) beforeOpen.set(id, await API.history(500).then((x) => x.items.filter((y) => y.id === id)).catch(() => []));
  const c = await API.concept(id);
  const n = c.note || {};
  const originFull = c.origin && c.origin.answer && c.origin.question && Render.envelope(c.origin.question) ? await API.answer(c.origin.answer).then((a) => a.question).catch(() => null) : null;
  const back = backTarget();
  const latin = /^[\x00-\x7f]+$/.test(c.label);
  const alias = aliasOf(c.label, [c.definition, n.easy, ...(c.sources || []).map((x) => x.text)].filter(Boolean).join(' '));
  const top = h('header', { class: 'journal-head reveal' },
    h('a', { class: 'link', href: back.href }, '← ' + back.name),
    h('p', { class: 'kicker' }, '개념 노트' + (c.rank ? ` · 중요도 ${c.rank}위` : '')),
    h('h1', { class: 'concept-title' + (latin ? ' latin' : ''), lang: latin ? 'en' : 'ko' }, c.label),
    alias ? h('p', { class: 'concept-alias' }, alias, h('small', {}, '출처 문장에 적힌 우리말 이름')) : null,
    h('div', { class: 'head-meta' }, h('span', {}, c.field || '분야 미정'), prog(c.progress), c.forms && c.forms.length > 1 ? h('span', { class: 'meta' }, '다른 표기 ' + c.forms.filter((f) => f !== c.label).join(', ')) : null,
      h('button', { class: 'btn quiet small focus-toggle', type: 'button', 'aria-pressed': String(focusMode()), onclick: (e) => setFocus(!focusMode(), e.currentTarget) }, '집중 읽기'),
      typeof MyNotes === 'object' ? MyNotes.addButton(id, c.label) : null));
  const notes = [];
  if (c.origin && c.origin.ts) notes.push(['처음 만난 날짜', when(c.origin.ts)]);
  if (n.checked) notes.push(['근거 확인', `${n.checked.total}문장 중 ${n.checked.passed}문장 통과`]);
  if (c.sessions) notes.push(['등장 횟수', `대화 ${c.sessions}개에서 ${c.turns}번`]);
  if (c.gate && c.gate.by) notes.push(['판단 방식', c.gate.by === 'user' ? '내 판단' : '자동 판단']);
  const reading = h('article', { class: 'sheet reading reveal', style: 'animation-delay:80ms' }, explain(c));
  // 근거 문장 = 정의 = 출처 문장인 경우가 많다(실측). 같은 글은 한 번만 (화면에서만, 데이터는 그대로)
  const norm = (t) => (t || '').replace(/[\s“”"'.,·]/g, '');
  const shown = new Set([...(n.easy_evidence || []).map(norm), n.easy ? '' : norm(c.definition)].filter(Boolean));
  const showDef = n.easy && c.definition && !shown.has(norm(c.definition));
  if (showDef) shown.add(norm(c.definition));
  const byUrl = new Map();
  for (const x of (c.sources || []).filter((y) => y.text || y.url)) { const k = x.url || x.text; if (!byUrl.has(k)) byUrl.set(k, []); if (x.text && !shown.has(norm(x.text))) { byUrl.get(k).push(x.text); shown.add(norm(x.text)); } }
  if (showDef) reading.append(h('section', {}, marker('', '개념 설명'), tag('source'), prose(c.definition)));
  if (byUrl.size && n.status !== 'wrong_sense') reading.append(h('section', {}, marker('', '출처', byUrl.size), h('ul', { class: 'source-list' }, [...byUrl].map(([url, texts]) => h('li', {},
    texts.map((t) => h('p', { class: 'src-text' }, t)), !texts.length ? h('span', { class: 'meta' }, '위 문장의 출처') : null,
    safeUrl(url) ? h('a', { class: 'src-link', href: url, target: '_blank', rel: 'noopener noreferrer' }, h('span', { class: 'go' }, '출처 열기 ↗'), h('span', { class: 'url' }, prettyUrl(url))) : null)))));
  const recGroups = []; for (const r of c.records || []) { const last = recGroups[recGroups.length - 1]; if (last && last.q === r.question) last.rs.push(r); else recGroups.push({ q: r.question, rs: [r] }); }
  const tl = timeline(c, beforeOpen.get(id) || []);
  if (tl) reading.append(tl);
  reading.append(h('section', {}, marker('', '처음 질문과 내 대화'),
    c.origin ? h('div', { class: 'first-q' }, h('span', { class: 'k' }, '처음 질문'), c.origin.question ? Render.question(c.origin.question, { full: originFull || c.origin.question }) : h('p', { class: 'qtitle' }, '질문 없이 붙여 넣은 답변')) : null,
    tag('own'),
    recGroups.length ? recGroups.map((g) => h('div', { class: 'record' }, g.q ? Render.question(g.q, { size: 'small' }) : null,
      g.rs.map((r) => h('div', { class: 'rs-item' }, h('p', { class: 'rs' }, r.snippet), h('span', { class: 'meta' }, when(r.ts) + ' · ' + (r.role === 'assistant' ? 'AI 답변' : r.role)))))) : h('p', { class: 'meta' }, '기록이 없어요.'),
    c.next_cursor ? h('p', { class: 'meta' }, '이 개념이 나온 대화가 더 있어요. 처음 만난 답변에서 이어 읽을 수 있어요.') : null,
    c.origin && c.origin.answer ? h('a', { class: 'link', href: aHash(c.origin.answer) }, '원래 답변 보기 →') : null));
  if (c.practice) {
    const ans = h('p', { class: 'meta', hidden: true, style: 'color:var(--checked)' }, '정답 · ' + c.practice.answer);
    reading.append(h('section', {}, marker('', '복습 · 빈칸 채우기'), h('div', { class: 'practice' }, h('span', { class: 'k' }, '출처 문장에서 개념 이름만 가렸어요.'), h('p', { class: 'blank' }, c.practice.blank),
      h('div', {}, h('button', { class: 'btn quiet small', type: 'button', onclick: (e) => { ans.hidden = !ans.hidden; e.target.textContent = ans.hidden ? '정답 확인' : '정답 접기'; } }, '정답 확인')), ans)));
  }
  const fail = h('p', { class: 'meta', role: 'status' });
  const mark = async (status, btn) => { const row = [...btn.parentElement.querySelectorAll('button')]; row.forEach((b) => (b.disabled = true)); btn.classList.add('busy'); const old = btn.textContent; btn.textContent = '저장 중…'; const here = location.hash; try { await API.setProgress(c.concept, status); btn.textContent = status === 'known' ? '이해했어요 ✓' : '다시 볼 개념에 넣었어요 ✓'; btn.classList.add('done'); setTimeout(() => { if (location.hash === here) location.hash = back.href; }, 450); } catch (e) { row.forEach((b) => (b.disabled = false)); btn.classList.remove('busy'); btn.textContent = old; fail.textContent = '저장하지 못했어요. ' + e.message; } };
  reading.append(h('div', { class: 'progress-actions' }, h('h2', { class: 'h2' }, '읽은 내용을 기억해 두세요'),
    h('p', { class: 'sub' }, '이해했으면 오늘 목록에서 빠지고, 다시 볼 개념은 다음에 먼저 보여 드려요.'),
    h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: (e) => mark('known', e.currentTarget) }, '이해했어요'), h('button', { class: 'btn quiet', type: 'button', onclick: (e) => mark('review', e.currentTarget) }, '다시 볼게요')), fail));
  const mine = c.gate && c.gate.by === 'user';
  const send = async (verdict, btn) => { const row = btn ? [...btn.parentElement.querySelectorAll('button')] : []; row.forEach((b) => (b.disabled = true)); try { await API.setFeedback(c.concept, verdict); render(); } catch (e) { row.forEach((b) => (b.disabled = false)); fail.textContent = '저장하지 못했어요. ' + e.message; } };
  const aux = h('aside', { class: 'glass aux reveal', style: 'animation-delay:120ms', 'aria-label': '보조 정보' },
    c.related && c.related.length ? h('div', {}, h('span', { class: 'k' }, '관련 개념'), h('p', { class: 'meta' }, '같은 대화에 함께 나온 개념이에요.'), relatedMap(c.label, c.related), h('div', { class: 'chips' }, c.related.map((r) => h('a', { href: cHash(r.id) }, r.label)))) : null,
    h('div', {}, h('span', { class: 'k' }, '내 판단'),
      mine ? h('p', {}, '내 판단 · ' + (c.gate.show ? '공부할 개념' : '공부할 개념 아님')) : h('p', { style: 'font-weight:500' }, '이 낱말이 공부할 개념인가요?'),
      mine ? h('div', {}, h('button', { class: 'btn quiet small', type: 'button', onclick: (e) => send('clear', e.currentTarget) }, '내 판단 지우기'))
        : h('div', { class: 'row' }, h('button', { class: 'btn quiet small', type: 'button', onclick: (e) => send('concept', e.currentTarget) }, '공부할 개념으로 표시'), h('button', { class: 'btn quiet small', type: 'button', onclick: (e) => send('not_concept', e.currentTarget) }, '공부할 개념 아님 · 숨기기')),
      h('span', { class: 'meta' }, '내 판단은 자동 판단보다 앞서요.')));
  return [top, h('div', { class: 'journal' }, notes.length ? h('div', { class: 'margin-notes' }, notes.map(([k, t]) => h('div', { class: 'mnote' }, h('span', { class: 'k' }, k), h('span', { class: 't' }, t)))) : h('div'), reading, aux)];
}

// ---------- 03 답변 아카이브 ----------
// 미리보기용: Markdown 기호(#, **, `, 표의 |)만 떼서 읽기 쉽게. 원문은 답변 읽기에서 그대로
const plainPreview = (t) => (t || '').replace(/^#{1,6}\s+/gm, '').replace(/\*\*|`{1,3}/g, '').replace(/\s*\|\s*/g, ' · ').replace(/^[-*+]\s+/gm, '').replace(/^·\s*/, '');
async function pageAnswers() {
  const [d, cs] = await Promise.all([API.answers(60), API.concepts('show', 5000).catch(() => ({ items: [] }))]);
  // 답변마다 그 답변에서 처음 만난 개념 (목록 API의 origin.answer, 중요한 순). 답변 API를 더 부르지 않는다
  const firstIn = new Map(); for (const x of [...cs.items].sort((a, b) => a.rank - b.rank)) { const k = x.origin && x.origin.answer; if (!k) continue; if (!firstIn.has(k)) firstIn.set(k, []); firstIn.get(k).push(x); }
  if (!d.items.length) return [head('답변 0개', '답변 기록'), emptyBox('아직 저장한 답변이 없어요', 'AI 답변을 붙여넣으면 원문을 다시 읽고, 그 안의 개념으로 들어갈 수 있어요.', h('a', { class: 'btn primary', href: 'classic.html#/answers' }, '답변 붙여넣기'))];
  const days = new Map(); for (const a of d.items) { const k = dayOf(a.ts); if (!days.has(k)) days.set(k, []); days.get(k).push(a); }
  const sections = [];
  const nav = h('nav', { class: 'daynav', 'aria-label': '날짜로 이동' });
  [...days].forEach(([k, arr], i) => {
    const sec = h('section', { class: 'day', id: 'day-' + i }, h('div', { class: 'day-head' }, h('h2', {}, k), h('span', { class: 'meta' }, arr.length + '개')),
      h('ul', { class: 'alist' }, arr.map((a) => { const fs = firstIn.get(a.id) || []; return h('li', { class: 'arow', 'data-text': ((a.preview || '') + ' ' + fs.map((x) => x.label).join(' ')).toLowerCase() },
        h('span', { class: 't' }, time(a.ts)),
        h('div', {}, h('span', { class: 'src' }, sourceName(a.source) + ' · ' + a.chars.toLocaleString() + '자'), h('p', { class: 'pv' }, clip(plainPreview(a.preview), 110)),
          fs.length ? h('p', { class: 'afirst' }, h('span', { class: 'k' }, `처음 만난 개념 ${fs.length}`), fs.slice(0, 4).map((x) => h('a', { href: cHash(x.id) }, x.label)), fs.length > 4 ? h('span', { class: 'meta' }, `외 ${fs.length - 4}개`) : null) : null),
        h('a', { class: 'btn quiet small act', href: aHash(a.id) }, '답변 보기')); })));
    sections.push(sec);
    nav.append(h('a', { href: '#', onclick: (e) => { e.preventDefault(); sec.scrollIntoView({ behavior: document.documentElement.dataset.motion === 'reduced' ? 'auto' : 'smooth' }); } }, h('span', {}, k.replace(/^\d+년\s*/, '')), h('span', { class: 'n' }, String(arr.length))));
  });
  const status = h('span', { class: 'meta', role: 'status' });
  // 실측 60개를 다 펼치면 7,900px. 20개씩 보여 주고, 찾을 때는 전부에서 (불러온 답변 안에서만 — 서버 검색 API는 없다)
  const STEP = 20; let limit = STEP, q = '';
  const rows = sections.flatMap((sec) => [...sec.querySelectorAll('.arow')]);
  const more = h('button', { class: 'btn quiet', type: 'button', onclick: () => { limit += STEP; apply(); } });
  const apply = () => {
    let n = 0;
    for (const li of rows) { const ok = !q || li.dataset.text.includes(q); li.hidden = !ok || (!q && n >= limit); if (ok) n++; }
    for (const sec of sections) sec.hidden = ![...sec.querySelectorAll('.arow')].some((li) => !li.hidden);
    more.hidden = !!q || rows.length <= limit; more.textContent = `더 보기 · 남은 ${rows.length - limit}개`;
    status.textContent = q ? `${n}개 찾음` : '';
  };
  const filter = h('label', { class: 'filter glass' }, h('span', { 'aria-hidden': 'true' }, '⌕'), h('input', { type: 'search', placeholder: `불러온 답변 ${d.items.length}개의 첫 부분·개념 이름에서 찾기`, 'aria-label': '답변 찾기', oninput: (e) => { q = e.target.value.trim().toLowerCase(); apply(); } }), status);
  apply();
  return [head(`답변 ${d.items.length}개`, '답변 기록', '받은 AI 답변을 원문 그대로 날짜별로 모아 둬요. 답변마다 그 답변에서 처음 만난 개념을 함께 보여 드려요.'),
    h('div', { class: 'archive' }, nav, h('div', {}, filter, sections, more))];
}
async function pageAnswer(id) {
  const a = await API.answer(id);
  const sum = a.summary || {};
  const summary = h('div', { class: 'summary-box' }, h('h2', { class: 'marker' }, '요약'),
    sum.status === 'ready' ? [tag('source'), h('ul', {}, sum.points.map((p) => h('li', {}, p.text))), h('span', { class: 'meta' }, '새 문장을 만들지 않고, 답변 원문에서 고른 문장이에요.')]
      : h('p', { class: 'sub' }, sum.status === 'rejected' ? '핵심 문장을 고르지 못했어요. 아래 원문을 읽어 주세요.' : '아직 요약이 없어요. 아래 원문을 바로 읽을 수 있어요.'));
  // 목차: 원문의 제목(#, ##, ###)으로 만든다. 3개 이상일 때만
  const heads = [];
  const doc = Render.document(a.text, { terms: a.terms, onHeading: (el, lvl) => heads.push({ el, lvl }) });
  const toc = heads.length >= 3 ? h('div', {}, h('span', { class: 'k' }, '목차'), h('ol', { class: 'toc' }, heads.map(({ el, lvl }) => h('li', { class: 'l' + lvl }, h('a', { href: '#', onclick: (e) => { e.preventDefault(); el.scrollIntoView({ behavior: document.documentElement.dataset.motion === 'reduced' ? 'auto' : 'smooth', block: 'start' }); } }, clip(el.textContent, 40)))))) : null;
  return [h('header', { class: 'answer-head reveal' }, h('a', { class: 'link', href: '#/answers' }, '← 답변 기록'), h('p', { class: 'kicker' }, '답변 읽기 · ' + sourceName(a.source) + ' · ' + when(a.ts) + ' · ' + a.text.length.toLocaleString() + '자'),
    a.question ? Render.question(a.question, { full: a.question, size: 'page' }) : h('h1', { class: 'answer-q' }, 'AI 답변')),
  h('div', { class: 'answer-layout' }, h('article', { class: 'sheet paper-page reveal' }, summary, h('div', { class: 'doc-head' }, h('h2', { class: 'marker' }, '원문'), Render.copyButton(() => a.text, '원문 복사')), doc),
    h('aside', { class: 'glass aux', 'aria-label': '목차와 이 답변의 개념' }, toc, h('div', {}, h('span', { class: 'k' }, `이 답변의 개념 ${a.terms.length}개`), h('p', { class: 'sub' }, '원문에서 밑줄 친 낱말이에요. 누르면 개념 노트로 가요.'),
      a.terms.length ? h('div', { class: 'chips' }, a.terms.map((t) => h('a', { href: cHash(t.id) }, t.label))) : h('p', { class: 'meta' }, '공부할 개념을 찾지 못했어요.'))))];
}

// ---------- 04 내 지식 라이브러리 (전체 개념) ----------
// 287개 안팎을 한 번에 펼치지 않는다: 처음엔 검색·분야·학습 상태로 둘러보고, 범위를 고르면 결과를 24개씩.
// 데이터는 /api/study/concepts?view=show 한 번(concepts.items 그대로). 관계는 목록에 있는 실제 값(origin.answer: 같은 답변에서 처음 만남)만 쓴다.
// (related[]는 개념 노트 API에만 있고, 그 API는 부를 때마다 '열어 본 기록'을 남겨서 여기서는 부르지 않는다)
const PROG_ORDER = { review: 0, new: 1, known: 2 };
const SORTS = [['rank', '중요한 순'], ['recent', '최근 처음 만난 순'], ['seen', '최근에 나온 순'], ['name', '가나다순'], ['prog', '학습 상태순'], ['field', '분야별']];
const PAGE = 24;
function fieldGraph(list, onPick) {
  // 노드 = 이 분야 개념(중요한 순 최대 36개), 선 = 같은 답변(origin.answer)에서 처음 만난 개념끼리
  const nodes = list.slice(0, 36);
  const groups = new Map(); for (const x of nodes) { const k = (x.origin && x.origin.answer) || '·' + x.id; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(x); }
  const W = 720, H = 360, cx = W / 2, cy = H / 2, G = [...groups.values()];
  const pos = new Map();
  G.forEach((g, gi) => {
    const a = (gi / G.length) * Math.PI * 2 - Math.PI / 2, R = G.length > 1 ? 130 : 0;
    const gx = cx + Math.cos(a) * R * 1.55, gy = cy + Math.sin(a) * R * .9;
    const rr = g.length > 1 ? Math.min(20 + g.length * 5, 70) : 0;   // 묶음이 클수록 넓게 (겹치면 누를 수 없었다, 실측)
    g.forEach((x, i) => { const b = (i / g.length) * Math.PI * 2 + gi; pos.set(x.id, [gx + Math.cos(b) * rr, gy + Math.sin(b) * rr]); });
  });
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'lib-graph', role: 'group', 'aria-label': `개념 ${nodes.length}개와 같은 답변에서 처음 만난 관계` });
  // 답변 하나 = 작은 사각형(허브), 그 답변에서 처음 만난 개념을 허브에 잇는다. (서로 다 이으면 실측 10개 넘는 묶음이 실뭉치가 됐다)
  const edges = [];
  G.forEach((g) => { if (g.length < 2) return; const pts = g.map((x) => pos.get(x.id)); const hx = pts.reduce((a, p) => a + p[0], 0) / pts.length, hy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
    for (const x of g) { const [x2, y2] = pos.get(x.id); const l = s('line', { x1: hx, y1: hy, x2, y2, class: 'e' }); l.dataset.a = x.id; edges.push(l); svg.append(l); }
    const hub = s('rect', { x: hx - 4, y: hy - 4, width: 8, height: 8, class: 'hub' }); const t = s('title'); t.textContent = `같은 답변에서 처음 만난 개념 ${g.length}개`; hub.append(t); svg.append(hub); });
  const els = new Map();
  for (const x of nodes) {
    const [x0, y0] = pos.get(x.id);
    const node = s('g', { class: 'n ' + x.progress, tabindex: '0', role: 'button', 'aria-label': `${x.label} — 관련 개념 보기` });
    // 이름표는 고른 개념과 연결 개념에만 (모두 보이면 겹쳐 읽을 수 없다). 누르는 영역은 투명 원으로 넓힌다
    const tip = s('title'); tip.textContent = x.label;
    node.append(tip, s('circle', { cx: x0, cy: y0, r: 14, class: 'hit' }), s('circle', { cx: x0, cy: y0, r: x.progress === 'review' ? 7 : 6, class: 'dot' }), s('text', { x: x0, y: y0 - 12, 'text-anchor': 'middle' }, clip(x.label, 14)));
    const pick = () => {
      const k = (x.origin && x.origin.answer) || null;
      const mates = new Set(nodes.filter((y) => k && y.origin && y.origin.answer === k).map((y) => y.id));
      mates.add(x.id);
      els.forEach((e, id) => { e.classList.toggle('on', id === x.id); e.classList.toggle('mate', id !== x.id && mates.has(id)); e.classList.toggle('dim', !mates.has(id)); });
      edges.forEach((l) => l.classList.toggle('on', mates.size > 1 && mates.has(l.dataset.a)));
      onPick(x, [...mates].filter((id) => id !== x.id).map((id) => nodes.find((y) => y.id === id)));
    };
    node.addEventListener('click', pick);
    node.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
    els.set(x.id, node); svg.append(node);
  }
  // 그림 범위를 실제 점들에 맞춘다 (위쪽 이름표가 잘리고, 모바일에서 너무 작던 것 — 실측)
  const xs = [...pos.values()].map((q) => q[0]), ys = [...pos.values()].map((q) => q[1]);
  const PAD = 40, minX = Math.min(...xs) - PAD, minY = Math.min(...ys) - PAD - 14, w = Math.max(...xs) - minX + PAD, hh = Math.max(...ys) - minY + PAD;
  svg.setAttribute('viewBox', `${minX} ${minY} ${Math.max(w, 160)} ${Math.max(hh, 120)}`);
  return { svg, count: nodes.length, total: list.length };
}
async function pageAll(sub) {
  const [d, hist] = await Promise.all([API.concepts('show', 1000), API.history(200).catch(() => ({ items: [] }))]);
  if (!d.items.length) return [head('개념 0개', '전체 개념'), emptyBox('아직 쌓인 개념이 없어요', '답변을 저장하면 공부할 개념이 여기에 모여요.')];
  const items = d.items.map((x) => ({ ...x, alias: aliasOf(x.label, x.line) }));
  const total = items.length;
  const cnt = (f) => items.filter(f).length;
  const P = { new: cnt((x) => x.progress === 'new'), review: cnt((x) => x.progress === 'review'), known: cnt((x) => x.progress === 'known') };
  const T = { ai_checked: cnt((x) => x.line_kind === 'ai_checked'), source: cnt((x) => x.line_kind === 'source'), none: cnt((x) => !x.line) };
  const fieldCount = new Map(); for (const x of items) fieldCount.set(x.field || '', (fieldCount.get(x.field || '') || 0) + 1);
  const fieldList = [...fieldCount].filter(([f]) => f).sort((a, b) => b[1] - a[1]).concat(fieldCount.get('') ? [['', fieldCount.get('')]] : []);
  const fname = (f) => f || '분야 미정';
  const RE = resurfaced(items); const reGap = new Map(RE.map((x) => [x.id, x.gap]));
  const st = { q: '', field: undefined, prog: 'all', expl: 'all', re: sub === 're', sort: sub === 're' ? 'seen' : 'rank', limit: PAGE, active: false };
  // 최근 읽은 개념: '열어 본 기록'(history, kind=opened)에서, 지금 공부 목록에 있는 것만 최근 순 8개
  const byId = new Map(items.map((x) => [x.id, x]));
  const recent = [...new Map(hist.items.filter((x) => x.kind === 'opened' && byId.has(x.id)).map((x) => [x.id, x])).values()].sort((a, b) => (b.ts || '').localeCompare(a.ts || '')).slice(0, 8).map((x) => byId.get(x.id));

  // --- 위: 라이브러리 현황 (실제 값만) ---
  // 칸 폭은 실제 개수에 비례. 0개 칸은 좁고 흐리게 (없는 것이 가장 눈에 띄던 것, 실측)
  const seg = (k, label, n) => h('button', { type: 'button', class: 'seg ' + k + (n ? '' : ' zero'), style: `flex:${n} 1 0`, onclick: () => set({ prog: k }), 'aria-label': `${label} ${n}개만 보기` }, h('span', { class: 'seg-l' }, label), h('b', {}, String(n)));
  const hero = h('header', { class: 'page-head lib-head reveal' }, h('p', { class: 'kicker' }, `개념 ${total}개`), h('h1', { class: 'display' }, '전체 개념'),
    h('p', { class: 'lead' }, `지금까지 대화에서 만난 개념 ${total}개를 모았어요. 찾고 싶은 개념을 검색하거나, 분야와 학습 상태로 둘러보세요.`),
    h('div', { class: 'lib-stats' },
      h('div', { class: 'lib-progress' }, h('p', { class: 'lib-k' }, '학습 상태 · 누르면 그 개념만 봐요'), h('div', { class: 'segs' }, seg('new', '처음 공부', P.new), seg('review', '다시 볼 개념', P.review), seg('known', '이해함', P.known))),
      h('div', { class: 'lib-trust' }, h('p', { class: 'lib-k' }, '설명 상태'), h('p', {}, h('span', { class: 'tag checked' }, `근거 확인됨 ${T.ai_checked}`), ' ', h('span', { class: 'tag source' }, `출처 원문 ${T.source}`), ' ', h('span', { class: 'tag none' }, `설명 없음 ${T.none}`)))));

  // --- 검색 ---
  const input = h('input', { type: 'search', placeholder: '개념 이름·우리말 이름으로 찾기', 'aria-label': '개념 찾기', autocomplete: 'off' });
  const clearBtn = h('button', { type: 'button', class: 'lib-clear', 'aria-label': '검색어 지우기', hidden: true, onclick: () => { input.value = ''; set({ q: '' }); input.focus(); } }, '×');
  const searchStatus = h('span', { class: 'lib-sstatus', role: 'status' });
  input.addEventListener('input', () => set({ q: input.value }));
  const search = h('div', { class: 'lib-search' }, h('label', { class: 'search glass' }, h('span', { 'aria-hidden': 'true', class: 'lib-ico' }, '⌕'), input, clearBtn), searchStatus);

  // --- 둘러보기 (처음 화면) ---
  const tile = (label, n, sub, on) => h('button', { type: 'button', class: 'lib-tile', onclick: on }, h('span', { class: 'lib-tile-l' }, label), h('span', { class: 'lib-tile-n' }, `${n}개`), sub ? h('span', { class: 'lib-tile-s' }, sub) : null);
  const fieldTiles = (list) => list.map(([f, n]) => { const known = items.filter((x) => (x.field || '') === f && x.progress === 'known').length; return tile(fname(f), n, known ? `이해함 ${known}` : null, () => set({ field: f, active: true })); });
  const moreFields = fieldList.length > 6 ? h('details', { class: 'lib-morefields' }, h('summary', {}, `분야 ${fieldList.length - 6}개 더 보기`), h('div', { class: 'lib-tiles' }, fieldTiles(fieldList.slice(6)))) : null;
  const top = [...items].sort((a, b) => a.rank - b.rank).slice(0, 8);
  const explore = h('div', { class: 'lib-explore' },
    h('section', {}, h('h2', { class: 'marker' }, '분야로 둘러보기', h('span', { class: 'count' }, `${fieldList.length}개 분야`)), h('div', { class: 'lib-tiles' }, fieldTiles(fieldList.slice(0, 6))), moreFields),
    recent.length ? h('section', {}, h('h2', { class: 'marker' }, '최근 읽은 개념', h('span', { class: 'count' }, '열어 본 순서')), h('ul', { class: 'lib-grid' }, recent.map((x, i) => card(x, i)))) : null,
    h('section', {}, h('h2', { class: 'marker' }, '학습 상태로 보기'), h('div', { class: 'lib-tiles' }, tile('처음 공부', P.new, '아직 이해 표시를 안 한 개념', () => set({ prog: 'new', active: true })), tile('다시 볼 개념', P.review, '다시 보겠다고 표시한 개념', () => set({ prog: 'review', active: true })), tile('이해함', P.known, '이해했다고 표시한 개념', () => set({ prog: 'known', active: true })),
      tile('아직 설명이 없는 개념', T.none, '출처에서 믿을 만한 설명을 아직 못 찾은 개념', () => set({ expl: 'none', active: true })),
      tile('다시 나온 개념', RE.length, '처음 만난 뒤 다른 날 대화에 다시 나온 개념 (최근 14일)', () => set({ re: true, sort: 'seen', active: true })))),
    h('section', {}, h('h2', { class: 'marker' }, '자주 나온 개념', h('span', { class: 'count' }, '중요한 순 8개')), h('ul', { class: 'lib-grid' }, top.map((x, i) => card(x, i))),
      h('div', { class: 'list-foot' }, h('button', { class: 'btn quiet', type: 'button', onclick: () => set({ active: true }) }, `전체 ${total}개 목록 보기`), h('a', { class: 'link', href: '#/hidden' }, '숨긴 개념 검토하기 →'))));

  // --- 결과 ---
  const chips = h('div', { class: 'lib-chips', 'aria-label': '적용한 거르기' });
  const sortSel = h('select', { 'aria-label': '정렬', class: 'lib-sort', onchange: (e) => set({ sort: e.target.value }) }, SORTS.map(([v, l]) => h('option', { value: v }, l)));
  const fieldSel = h('select', { 'aria-label': '분야 고르기', class: 'lib-fieldsel', onchange: (e) => set({ field: e.target.value === '*' ? undefined : e.target.value }) }, h('option', { value: '*' }, `모든 분야 (${total})`), fieldList.map(([f, n]) => h('option', { value: f }, `${fname(f)} (${n})`)));
  const progBtns = h('div', { class: 'lib-progbtns', role: 'group', 'aria-label': '학습 상태로 거르기' }, [['all', '전체'], ['new', '처음 공부'], ['review', '다시 볼 개념'], ['known', '이해함']].map(([v, l]) => h('button', { type: 'button', 'data-p': v, onclick: () => set({ prog: v }) }, l)));
  const resultCount = h('p', { class: 'lib-count', role: 'status' });
  const grid = h('ul', { class: 'lib-grid' });
  const more = h('button', { class: 'btn quiet', type: 'button', onclick: () => set({ limit: st.limit + PAGE }, true) });
  const empty = h('div', { hidden: true }, emptyBox('찾는 개념이 없어요', '다른 낱말로 찾거나 거르기를 풀어 보세요. 공부할 개념에서 빠진 낱말은 숨긴 개념에 있을 수 있어요.', h('div', { class: 'row' }, h('button', { class: 'btn quiet', type: 'button', onclick: () => { input.value = ''; set({ q: '', field: undefined, prog: 'all', expl: 'all', re: false }); } }, '거르기 모두 풀기'), h('a', { class: 'link', href: '#/hidden' }, '숨긴 개념에서 찾기 →'))));
  const graphBox = h('div', { class: 'lib-graphbox' });
  const graphToggle = h('details', { class: 'lib-graphwrap', hidden: true }, h('summary', {}, '이 분야의 개념 관계 보기'), graphBox);
  graphToggle.addEventListener('toggle', () => { if (graphToggle.open) drawGraph(); });
  const results = h('section', { class: 'lib-results', hidden: true, 'aria-label': '검색 결과' },
    h('div', { class: 'lib-toolbar' }, h('div', { class: 'lib-filters' }, fieldSel, progBtns), h('label', { class: 'lib-sortwrap' }, h('span', {}, '정렬'), sortSel)),
    h('div', { class: 'lib-meta' }, resultCount, chips), graphToggle, grid, empty, h('div', { class: 'list-foot' }, more, h('button', { class: 'link', type: 'button', onclick: () => { input.value = ''; set({ q: '', field: undefined, prog: 'all', expl: 'all', re: false, active: false }); } }, '← 둘러보기로')));

  function drawGraph() {
    const list = filtered().filter((x) => (x.field || '') === st.field);
    const pick = h('div', { class: 'lib-pick', role: 'status' }, h('p', { class: 'meta' }, '점을 누르면 같은 답변에서 처음 만난 개념이 강조돼요.'));
    const g = fieldGraph(list, (x, mates) => pick.replaceChildren(
      h('p', {}, h('a', { class: 'lib-pick-name', href: cHash(x.id) }, x.label), x.alias ? h('span', { class: 'alias' }, ' ' + x.alias) : null, ' ', prog(x.progress)),
      h('p', { class: 'sub' }, x.line ? clip(x.line, 110) : NO_LINE),
      mates.length ? h('div', { class: 'chips' }, mates.map((m) => h('a', { href: cHash(m.id) }, m.label))) : h('p', { class: 'meta' }, '이 분야에서 같은 답변에 함께 나온 개념은 없어요.'),
      h('a', { class: 'link', href: cHash(x.id) }, '개념 노트 열기 →')));
    graphBox.replaceChildren(h('p', { class: 'meta' }, `선: 같은 답변에서 처음 만난 개념끼리 이었어요 (실제 기록). ${g.total > g.count ? `중요한 순 ${g.count}개만 그렸어요.` : ''}`), g.svg, pick);
  }
  function matchKind(x, q) {
    if (!q) return 'all';
    const n = q.toLowerCase();
    if (x.label.toLowerCase().includes(n) || (x.alias || '').toLowerCase().includes(n)) return 'name';
    if ((x.line || '').toLowerCase().includes(n)) return 'desc';
    return null;
  }
  function filtered() {
    return items.filter((x) => (st.field === undefined || (x.field || '') === st.field) && (st.prog === 'all' || x.progress === st.prog) && (st.expl === 'all' || !x.line) && (!st.re || reGap.has(x.id)) && matchKind(x, st.q.trim()));
  }
  function sorted(list) {
    const ko = (a, b) => a.label.localeCompare(b.label, 'ko', { sensitivity: 'base' });
    const by = { rank: (a, b) => a.rank - b.rank, seen: (a, b) => String(b.last_seen || '').localeCompare(String(a.last_seen || '')) || a.rank - b.rank, recent: (a, b) => ((b.origin && b.origin.ts) || '').localeCompare((a.origin && a.origin.ts) || '') || a.rank - b.rank, name: ko,
      prog: (a, b) => PROG_ORDER[a.progress] - PROG_ORDER[b.progress] || a.rank - b.rank, field: (a, b) => (a.field ? 0 : 1) - (b.field ? 0 : 1) || (a.field || '').localeCompare(b.field || '', 'ko') || a.rank - b.rank }[st.sort];
    const q = st.q.trim();
    return [...list].sort((a, b) => (q ? (matchKind(a, q) === 'name' ? 0 : 1) - (matchKind(b, q) === 'name' ? 0 : 1) : 0) || by(a, b));
  }
  function card(x, i, q) {
    const kind = q ? matchKind(x, q) : null;
    return h('li', { class: 'lib-item', style: `animation-delay:${Math.min(i, 6) * 30}ms` }, h('a', { class: 'lib-card ' + x.progress, href: cHash(x.id) },
      h('span', { class: 'lib-name' }, h('span', { class: 'lib-label' }, x.label), x.alias ? h('span', { class: 'alias' }, x.alias) : null),
      h('span', { class: 'lib-sub' }, h('span', {}, fname(x.field)), prog(x.progress), kind === 'desc' ? h('span', { class: 'lib-found' }, '설명에서 찾음') : null, st.re && reGap.has(x.id) ? h('span', { class: 'lib-re' }, `${reGap.get(x.id)}일 만에 다시`) : null),
      h('span', { class: 'lib-desc' + (x.line ? '' : ' none') }, x.line ? clip(x.line, 96) : NO_LINE),
      h('span', { class: 'lib-foot' }, tag(x.line_kind in TAG ? x.line_kind : 'none'), h('span', { class: 'lib-go', 'aria-hidden': 'true' }, '→'))));
  }
  function draw(keepScroll) {
    const active = st.active || !!st.q.trim() || st.field !== undefined || st.prog !== 'all' || st.expl !== 'all' || st.re;
    explore.hidden = active; results.hidden = !active;
    clearBtn.hidden = !st.q;
    const list = sorted(filtered());
    const q = st.q.trim();
    searchStatus.textContent = q ? (list.length ? `“${q}” ${list.length}개 찾음` : `“${q}”와 맞는 개념이 없어요`) : '';
    if (!active) return;
    const shown = list.slice(0, st.limit);
    const items_ = [];
    let lastField = null;
    shown.forEach((x, i) => {
      if (st.sort === 'field' && x.field !== lastField) { items_.push(h('li', { class: 'lib-group' }, fname(x.field))); lastField = x.field; }
      items_.push(card(x, keepScroll ? 0 : i, q));
    });
    grid.replaceChildren(...items_);
    grid.classList.remove('lib-swap'); void grid.offsetWidth; grid.classList.add('lib-swap');
    resultCount.textContent = list.length ? `${list.length}개 중 ${shown.length}개를 보고 있어요` : '0개';
    empty.hidden = list.length > 0; grid.hidden = !list.length;
    more.hidden = list.length <= st.limit; more.textContent = `${Math.min(PAGE, list.length - st.limit)}개 더 보기 · 남은 ${list.length - st.limit}개`;
    fieldSel.value = st.field === undefined ? '*' : st.field; sortSel.value = st.sort;
    progBtns.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.p === st.prog)));
    const chip = (label, clear) => h('button', { type: 'button', class: 'lib-chip', onclick: clear, 'aria-label': `${label} 거르기 풀기` }, label, h('span', { 'aria-hidden': 'true' }, ' ×'));
    chips.replaceChildren(...[q ? chip(`검색: ${q}`, () => { input.value = ''; set({ q: '' }); }) : null, st.field !== undefined ? chip(`분야: ${fname(st.field)}`, () => set({ field: undefined })) : null, st.prog !== 'all' ? chip(`상태: ${PROG[st.prog]}`, () => set({ prog: 'all' })) : null, st.expl === 'none' ? chip('설명 없는 개념만', () => set({ expl: 'all' })) : null, st.re ? chip('다시 나온 개념만', () => set({ re: false })) : null].filter(Boolean));
    graphToggle.hidden = st.field === undefined;
    if (graphToggle.open) drawGraph();
  }
  function set(patch, keepScroll) { Object.assign(st, patch); if (!('limit' in patch)) st.limit = PAGE; if (('field' in patch || 'prog' in patch || 'expl' in patch || 're' in patch) && !('active' in patch)) st.active = true; draw(keepScroll); }
  draw();
  return [hero, search, explore, results];
}

// ---------- 05 검토 책상 ----------
// 짧은 출처 질문 표시: 봉투면 종류 라벨만 (원문 태그를 제목처럼 보여 주지 않는다)
const qshort = (q) => { if (!q) return null; const env = Render.envelope(q); return env ? env.label + (env.title ? ' · ' + clip(env.title, 30) : '') + '에서' : '“' + clip(q, 44) + '”에서'; };
function why(x) {
  const g = x.gate || {};
  if (g.by === 'user') return '내가 공부할 개념이 아니라고 했어요.';
  if (g.candidate) return 'AI는 개념으로 봤지만, 일상 뜻도 있어 후보로 남겼어요.';
  if (g.by === 'llm') return '두 번째 근거(사전·위키백과)가 없거나 AI가 일상어로 봤어요.';
  if (g.by === 'rule' || g.by === 'lexicon') return '사전·규칙에서 일상어로 걸렀어요.';
  return '근거가 부족해 숨겼어요.';
}
async function pageHidden() {
  const d = await API.concepts('hidden', 500);
  const cands = d.items.filter((x) => x.gate && x.gate.candidate), rest = d.items.filter((x) => !(x.gate && x.gate.candidate));
  const row = (x) => {
    const li = h('li', { class: 'ritem' + (x.gate && x.gate.candidate ? '' : ' hidden-word') }, h('span', { class: 'w' }, x.label),
      h('p', { class: 'why' }, h('span', { class: 'meta' }, [x.field || '분야 미정', qshort(x.origin && x.origin.question)].filter(Boolean).join(' · '))));
    const btn = h('button', { class: 'btn quiet small', type: 'button', 'aria-label': `${x.label} — 공부할 개념으로 표시`, onclick: async () => {
      btn.disabled = true;
      try { await API.setFeedback(x.id, 'concept'); li.classList.add('done'); btn.replaceWith(h('a', { class: 'link', href: cHash(x.id), role: 'status' }, '공부할 개념으로 표시했어요 · 노트 열기 →')); }
      catch (err) { btn.disabled = false; btn.after(h('span', { class: 'meta', role: 'status' }, ' 저장하지 못했어요: ' + err.message)); }
    } }, '공부할 개념으로 표시');
    li.append(btn); return li;
  };
  const listOf = (arr, n) => { const ul = h('ul', { class: 'rlist' }, arr.slice(0, n).map(row)); if (arr.length <= n) return ul; let shown = n; const more = h('button', { class: 'btn quiet', type: 'button', style: 'margin-top:var(--s3)', onclick: () => { ul.append(...arr.slice(shown, shown + n).map(row)); shown += n; if (shown >= arr.length) more.remove(); else more.textContent = `더 보기 · 남은 ${arr.length - shown}개`; } }, `더 보기 · 남은 ${arr.length - n}개`); return h('div', {}, ul, more); };
  if (!d.items.length) return [head('낱말 0개', '숨긴 개념'), emptyBox('숨긴 낱말이 없어요', '자동으로 숨긴 낱말이 생기면 여기에 모여요. 모두 검토했다면 할 일이 없어요.', h('a', { class: 'btn quiet', href: '#/all' }, '전체 개념 보기'))];
  return [head(`낱말 ${d.items.length}개`, '숨긴 개념', '자동 판단이 목록에서 숨긴 낱말이에요. 공부하고 싶은 낱말이 있으면 "공부할 개념으로 표시"를 누르세요. 내 판단이 자동 판단보다 앞서요.'),
    h('div', { class: 'review-layout' }, h('div', { class: 'review-list' },
      cands.length ? h('section', {}, h('div', { style: 'margin-bottom:var(--s3)' }, marker('', '먼저 볼 후보', `${cands.length}개`)), h('p', { class: 'sub', style: 'margin-bottom:var(--s3)' }, 'AI는 개념이라고 했지만 일상 뜻도 있어 보류한 낱말이에요. 잘못 걸렀을 가능성이 가장 커요.'), listOf(cands, 20)) : null,
      rest.length ? h('section', {}, h('div', { style: 'margin-bottom:var(--s3)' }, marker('', '숨긴 낱말', `${rest.length}개`)),
        [...rest.reduce((m, x) => m.set(why(x), [...(m.get(why(x)) || []), x]), new Map())].map(([reason, arr]) => h('div', { class: 'rgroup' }, h('p', { class: 'rreason' }, reason, h('span', { class: 'count' }, ' ' + arr.length + '개')), listOf(arr, 10)))) : null),
    h('aside', { class: 'glass review-aside', 'aria-label': '검토 방법' }, h('span', { class: 'aux-k' }, '검토하는 방법'),
      h('ol', {}, h('li', {}, '후보부터 훑어보세요. 공부하고 싶은 낱말이면 "공부할 개념으로 표시".'), h('li', {}, '표시한 낱말은 내 판단으로 저장되고 전체 개념에 나타나요.'), h('li', {}, '마음이 바뀌면 개념 노트에서 내 판단을 지울 수 있어요.'))))];
}

// ---------- 05 기록에 묻기: atelier-chat.js (pageChat) ----------
// ---------- 06 나만의 노트: atelier-notes.js (pageNotes, 이 브라우저에만 저장) ----------

// ---------- 길 찾기 ----------
let cameFrom = '';   // 개념 노트로 들어오기 전 화면 (뒤로 링크·표시 뒤 돌아갈 곳)
const SCREEN_NAME = { all: '전체 개념', answers: '답변 기록', a: '답변', hidden: '숨긴 개념', chat: '기록에 묻기', notes: '나만의 노트' };
function backTarget() {
  const first = cameFrom.split('/').filter(Boolean)[0];
  return first && SCREEN_NAME[first] ? { href: '#' + cameFrom, name: SCREEN_NAME[first] } : { href: '#/', name: '오늘 공부' };
}
async function render() {
  const route = location.hash.slice(1) || '/';
  const parts = route.split('/').filter(Boolean);
  const same = route === routeNow;
  if (!same && routeNow && !routeNow.startsWith('/c/')) cameFrom = routeNow;
  routeNow = route;
  const screen = { c: 'concept', all: 'all', a: 'answer', answers: 'answers', hidden: 'hidden', chat: 'chat', notes: 'notes' }[parts[0]] || 'today';
  document.body.dataset.screen = screen;
  const from = { a: 'answers' }[(cameFrom.split('/').filter(Boolean)[0])] || cameFrom.split('/').filter(Boolean)[0];
  const tab = screen === 'concept' ? (SCREEN_NAME[from] ? from : 'today') : ({ answer: 'answers' }[screen] || screen);
  document.querySelectorAll('.nav a').forEach((a) => (a.dataset.tab === tab ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  if (same && screen === 'chat') return health();   // 채팅은 한 번 만든 화면을 그대로 둔다 (새 기록 알림으로 대화를 다시 그리지 않게)
  if (!same) { view.replaceChildren(h('p', { class: 'loading', role: 'status' }, '불러오는 중…')); beforeOpen.clear(); }
  try {
    const fn = { concept: () => pageConcept(decodeURIComponent(parts[1])), all: () => pageAll(parts[1]), answer: () => pageAnswer(decodeURIComponent(parts[1])), answers: pageAnswers, hidden: pageHidden, chat: pageChat, notes: () => pageNotes(parts[1]), today: pageToday }[screen];
    const nodes = await fn();
    if (route !== routeNow) return;
    const active = document.activeElement;
    if (same && active && ['TEXTAREA', 'INPUT'].includes(active.tagName)) return;
    view.replaceChildren(...nodes.filter(Boolean));
    const h1 = view.querySelector('h1');
    document.title = (screen === 'today' && !view.querySelector('.welcome-hero') ? '오늘 공부' : h1 ? h1.textContent.trim().replace(/\.$/, '') : '') + ' · THYNK';
    if (!same) { view.classList.remove('page-in'); void view.offsetWidth; view.classList.add('page-in'); }
    if (!same) { window.scrollTo(0, 0); view.focus({ preventScroll: true }); }
    focusByScroll();
  } catch (e) {
    document.title = '불러오지 못했어요 · THYNK';
    view.replaceChildren(h('header', { class: 'page-head', role: 'alert' }, h('p', { class: 'kicker', style: 'color:var(--error)' }, '오류'), h('h1', { class: 'display' }, '불러오지 못했어요'), h('p', { class: 'lead' }, e.message), h('p', { class: 'sub' }, '개념 차트가 켜져 있는지 확인한 뒤 다시 시도해 주세요.'), h('div', {}, h('button', { class: 'btn quiet', type: 'button', onclick: () => { routeNow = ''; render(); } }, '다시 시도'))));
  }
  health();
}
async function health() {
  try {
    const st = await API.health();
    const t = (st.llm.available ? 'AI 요약 켜짐' : 'AI 요약 꺼짐 · 출처 문장만') + (st.jobs && st.jobs.queued ? ` · 준비 중 ${st.jobs.queued}건` : '');
    document.getElementById('health').textContent = t;
    document.getElementById('status').textContent = '상태 · ' + t + ' · 이 PC에서만 실행';
  } catch { document.getElementById('status').textContent = ''; }
}
const motionBtn = document.getElementById('motion');
const setMotion = (reduced) => { document.documentElement.dataset.motion = reduced ? 'reduced' : ''; motionBtn.setAttribute('aria-pressed', String(reduced)); try { localStorage.setItem('atelier-motion', reduced ? 'reduced' : ''); } catch { /* 저장 못 해도 동작 */ } };
try { setMotion(localStorage.getItem('atelier-motion') === 'reduced'); } catch { setMotion(false); }
motionBtn.addEventListener('click', () => setMotion(document.documentElement.dataset.motion !== 'reduced'));
// 집중 읽기 (개념 노트): 마우스·키보드가 닿은 구획, 아니면 화면 40% 높이에 걸친 구획 하나만 또렷하게
const focusMode = () => document.documentElement.dataset.focus === 'on';
const FOCUS_PARTS = '.reading > section, .reading > .progress-actions';
function focusPick(part) { document.querySelectorAll(FOCUS_PARTS).forEach((x) => x.classList.toggle('here', x === part)); }
let pointerPickAt = 0;   // 마우스로 고른 직후에는 스크롤 위치로 덮어쓰지 않는다
function focusByScroll() {
  if (!focusMode() || document.body.dataset.screen !== 'concept' || Date.now() - pointerPickAt < 600) return;
  const parts = [...document.querySelectorAll(FOCUS_PARTS)]; if (!parts.length) return;
  if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4 && window.scrollY > 0) return focusPick(parts[parts.length - 1]);   // 맨 아래면 마지막 구획
  const line = window.innerHeight * 0.4;
  let best = parts[0], gap = Infinity;
  for (const p of parts) { const r = p.getBoundingClientRect(); const d = r.top <= line && r.bottom >= line ? 0 : Math.min(Math.abs(r.top - line), Math.abs(r.bottom - line)); if (d < gap) { gap = d; best = p; } }
  focusPick(best);
}
function setFocus(on, btn) {
  document.documentElement.dataset.focus = on ? 'on' : '';
  if (btn) btn.setAttribute('aria-pressed', String(on));
  try { localStorage.setItem('atelier-focus', on ? 'on' : 'off'); } catch { /* 저장 못 해도 동작 */ }
  focusByScroll();
}
try { setFocus(localStorage.getItem('atelier-focus') !== 'off'); } catch { setFocus(true); }
// 상단 바: 아래로 내리면 숨고 위로 올리면 나온다. 맨 위 근처·바 안에 키보드 초점이 있을 때는 항상 보인다
const topbar = document.querySelector('.topbar');
let lastY = window.scrollY;
function barByScroll() {
  const y = window.scrollY, dy = y - lastY;
  if (y < 120 || topbar.contains(document.activeElement)) document.body.classList.remove('bar-away');
  else if (dy > 6) document.body.classList.add('bar-away');
  else if (dy < -6) document.body.classList.remove('bar-away');
  if (Math.abs(dy) > 6 || y < 120) lastY = y;
}
topbar.addEventListener('focusin', () => document.body.classList.remove('bar-away'));
window.addEventListener('hashchange', () => { document.body.classList.remove('bar-away'); lastY = 0; });
let focusTick = 0;
window.addEventListener('scroll', () => { if (!focusTick) focusTick = requestAnimationFrame(() => { focusTick = 0; focusByScroll(); barByScroll(); }); }, { passive: true });
for (const ev of ['pointerover', 'focusin']) view.addEventListener(ev, (e) => { if (!focusMode()) return; const p = e.target.closest && e.target.closest(FOCUS_PARTS); if (p) { pointerPickAt = Date.now(); focusPick(p); } });
window.addEventListener('hashchange', render);
// 새 기록 알림: 보던 화면(입력·펼침·스크롤)을 지우지 않게 바로 다시 그리지 않고, 위에 띠로 알린다. 숫자만 보는 빈 화면·환영 화면은 바로 고친다
const fresh = h('div', { class: 'fresh glass', role: 'status', hidden: true }, h('span', {}, '새 공부 기록이 들어왔어요'), h('button', { class: 'btn quiet small', type: 'button', onclick: () => { fresh.hidden = true; render(); } }, '새로 보기'));
document.body.append(fresh);
window.addEventListener('hashchange', () => { fresh.hidden = true; });
let timer; API.onUpdate(() => { clearTimeout(timer); timer = setTimeout(() => {
  if (document.hidden) return;
  const screen = document.body.dataset.screen;
  if (screen === 'chat' || screen === 'notes' || (Date.now() < quietUntil && screen === 'today')) return;
  if (view.querySelector('.welcome-hero, .empty-box')) return render();
  fresh.hidden = false;
}, 800); });
render();
