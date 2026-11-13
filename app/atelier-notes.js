// 06 나만의 노트 — 개념마다 내 말로 적는 노트 (11-13 사용자 요청: 각 낱말에 '추가하기', 따로 된 화면, 기존 설계에 영향 없이).
// 따로 선 화면: 서버·DB·API를 쓰지 않고 이 브라우저(localStorage)에만 저장한다. 개념 차트의 데이터·판정·노트는 건드리지 않는다.
// 노트 글은 사용자가 쓴 글이다. 출처·근거로 쓰지 않고 화면에서도 '내가 쓴 글'로만 보인다 (docs/CONSTRAINTS.md).
// 잃지 않게 '파일로 내보내기'(JSON)를 둔다. 글은 textContent/value로만 넣는다 (HTML로 해석하지 않는다).
// atelier.js보다 먼저 불러온다. h·mascot·emptyBox·when은 부를 때 atelier.js의 것을 쓴다.
// 마스코트 말풍선(바로 가기)도 여기서 만든다: atelier.js의 deskArt가 MyNotes.attachArt(figure)를 부른다.
const MyNotes = (() => {
  const KEY = 'thynk-mynotes-v1';        // { [개념 id]: { label, text, created, updated } }
  const MAX = 20000;                     // 노트 하나 글자 수 상한 (브라우저 저장 공간 보호)
  const load = () => { try { const v = JSON.parse(localStorage.getItem(KEY)); return v && typeof v === 'object' ? v : {}; } catch { return {}; } };
  const save = (all) => { try { localStorage.setItem(KEY, JSON.stringify(all)); return true; } catch { return false; } };
  const list = () => Object.entries(load()).map(([id, n]) => ({ id, ...n })).sort((a, b) => String(b.updated).localeCompare(String(a.updated)));
  const has = (id) => Object.prototype.hasOwnProperty.call(load(), id);
  const count = () => Object.keys(load()).length;
  const hash = (id) => '#/notes/' + encodeURIComponent(id);

  function add(id, label) {
    const all = load();
    if (!all[id]) { const now = new Date().toISOString(); all[id] = { label: String(label || id), text: '', created: now, updated: now }; if (!save(all)) return false; }
    return true;
  }

  // 개념 노트 머리에 붙는 단추: 없으면 추가하고 그 노트를 연다, 있으면 연다
  function addButton(id, label) {
    const on = has(id);
    return h('a', { class: 'btn quiet small mn-add' + (on ? ' on' : ''), href: hash(id),
      onclick: (e) => { if (!add(id, label)) { e.preventDefault(); e.currentTarget.textContent = '저장 공간이 없어요'; } } },
      on ? '나만의 노트 열기' : '＋ 나만의 노트에 추가');
  }

  function exportFile() {
    const blob = new Blob([JSON.stringify({ app: 'THYNK', kind: 'my-notes', v: 1, exported: new Date().toISOString(), notes: load() }, null, 1)], { type: 'application/json' });
    const a = h('a', { href: URL.createObjectURL(blob), download: `thynk-나만의노트-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function editor(n) {
    const status = h('p', { class: 'mn-status meta', role: 'status' }, n.updated ? '저장됨 · ' + when(n.updated) : '');
    const area = h('textarea', { class: 'mn-text', 'aria-label': n.label + ' 노트', maxlength: String(MAX), placeholder: '이 개념을 내 말로 적어 보세요. 예) 한 줄 정의, 헷갈렸던 점, 예시, 다음에 볼 것' });
    area.value = n.text || '';
    let t;
    area.addEventListener('input', () => {
      status.textContent = '저장 중…';
      clearTimeout(t);
      t = setTimeout(() => {
        const all = load();
        if (!all[n.id]) return;
        all[n.id].text = area.value.slice(0, MAX); all[n.id].updated = new Date().toISOString();
        status.textContent = save(all) ? '저장됨 · ' + when(all[n.id].updated) : '저장하지 못했어요 (브라우저 저장 공간)';
        const row = document.querySelector(`.mn-list a[data-id="${CSS.escape(n.id)}"] .mn-snip`);
        if (row) row.textContent = snip(area.value);
      }, 400);
    });
    const del = h('button', { class: 'btn quiet small', type: 'button', onclick: () => {
      if (!confirm(`‘${n.label}’ 노트를 지울까요? 되돌릴 수 없어요.`)) return;
      const all = load(); delete all[n.id]; save(all); location.hash = '#/notes';
    } }, '노트 지우기');
    return h('article', { class: 'sheet mn-sheet reveal' },
      h('header', { class: 'mn-head' },
        h('p', { class: 'kicker' }, '내가 쓴 글'),
        h('h2', { class: 'mn-title' }, n.label),
        h('p', { class: 'meta' }, '처음 적은 날 ' + when(n.created) + ' · ', h('a', { class: 'link', href: '#/c/' + encodeURIComponent(n.id) }, '개념 노트 보기 →'))),
      area,
      h('div', { class: 'mn-foot' }, status, del));
  }

  const snip = (t) => { const x = (t || '').replace(/\s+/g, ' ').trim(); return x ? (x.length > 54 ? x.slice(0, 54) + '…' : x) : '아직 비어 있어요'; };

  async function page(sel) {
    const items = list();
    const id = sel ? decodeURIComponent(sel) : null;
    const top = h('header', { class: 'page-head reveal' }, h('p', { class: 'kicker' }, `노트 ${items.length}개`), h('h1', { class: 'display' }, '나만의 노트'),
      h('p', { class: 'lead' }, '개념을 내 말로 정리하는 곳이에요. 적은 글은 이 브라우저에만 저장되고, 개념 노트의 출처·설명은 바뀌지 않아요.'));
    if (!items.length) return [top, emptyBox('아직 노트가 없어요', '개념 노트 위쪽의 ‘＋ 나만의 노트에 추가’를 누르면 여기에 모여요.', h('a', { class: 'btn quiet', href: '#/all' }, '전체 개념 보기'))];
    const cur = items.find((x) => x.id === id) || items[0];
    const q = h('input', { type: 'search', class: 'mn-q', placeholder: '노트 찾기', 'aria-label': '노트 찾기', autocomplete: 'off' });
    const ul = h('ul', { class: 'mn-list' }, items.map((x) => h('li', {}, h('a', { href: hash(x.id), 'data-id': x.id, 'aria-current': x.id === cur.id ? 'true' : null },
      h('b', {}, x.label), h('span', { class: 'mn-snip' }, snip(x.text)), h('time', { class: 'meta', datetime: x.updated }, when(x.updated))))));
    q.addEventListener('input', () => { const k = q.value.trim().toLowerCase(); ul.querySelectorAll('li').forEach((li) => { li.hidden = k && !li.textContent.toLowerCase().includes(k); }); });
    const side = h('aside', { class: 'mn-side reveal' }, q, ul, h('button', { class: 'btn quiet small mn-export', type: 'button', onclick: exportFile }, '파일로 내보내기'));
    return [top, h('div', { class: 'mn-layout' }, side, editor(cur))];
  }

  // ---------- 마스코트: 마우스를 올리면 움직이고, 누르면 말풍선 바로 가기 ----------
  let bubble = null;
  function close() { if (!bubble) return; bubble.owner.setAttribute('aria-expanded', 'false'); bubble.remove(); bubble = null; }
  function place() {
    if (!bubble) return;
    const r = bubble.owner.getBoundingClientRect(), b = bubble.getBoundingClientRect();
    const x = Math.min(Math.max(8, r.left + r.width / 2 - b.width / 2), document.documentElement.clientWidth - b.width - 8);
    const above = r.top + r.height * .28 - b.height - 14;
    bubble.style.left = x + scrollX + 'px';
    bubble.style.top = (above > 8 ? above : r.top + r.height * .28 + 14) + scrollY + 'px';
    bubble.classList.toggle('below', above <= 8);
  }
  function open(btn) {
    close();
    const screen = document.body.dataset.screen;
    const n = count();
    const links = [
      ['notes', '#/notes', '나만의 노트', n ? `노트 ${n}개` : '내 말로 정리하기'],
      ['chat', '#/chat', '기록에 묻기', '공부 기록에서 찾아 답해요'],
      ['all', '#/all', '전체 개념', '모든 개념 둘러보기'],
      ['today', '#/', '오늘 공부', '오늘 볼 개념 이어서'],
    ].filter(([k]) => k !== screen);
    bubble = h('div', { class: 'mn-bubble', role: 'dialog', 'aria-label': 'THYNK 바로 가기' },
      h('p', { class: 'mn-hi' }, '어디로 갈까요?'),
      h('ul', {}, links.map(([, href, t, sub]) => h('li', {}, h('a', { href, onclick: close }, h('b', {}, t), h('span', {}, sub))))));
    bubble.owner = btn;
    document.body.append(bubble);
    btn.setAttribute('aria-expanded', 'true');
    place();
    bubble.querySelector('a').focus({ preventScroll: true });
  }
  document.addEventListener('click', (e) => { if (bubble && !bubble.contains(e.target) && !bubble.owner.contains(e.target)) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && bubble) { const b = bubble.owner; close(); b.focus(); } });
  window.addEventListener('hashchange', close);
  window.addEventListener('resize', place);

  // deskArt(그림)에 누를 수 있는 단추를 겹친다. 그림은 그대로 두고 단추만 더한다
  function attachArt(fig) {
    const btn = h('button', { class: 'art-hit', type: 'button', 'aria-label': 'THYNK 바로 가기 열기', 'aria-haspopup': 'dialog', 'aria-expanded': 'false',
      onclick: (e) => { e.stopPropagation(); bubble && bubble.owner === e.currentTarget ? close() : open(e.currentTarget); } });
    fig.append(btn);
    return fig;
  }

  return { page, addButton, attachArt, add, has, count, KEY };
})();
const pageNotes = (sel) => MyNotes.page(sel);
