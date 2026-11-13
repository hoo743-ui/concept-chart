// THYNK 공부 기록 — claude.ai 화면에서 '새로 끝난' AI 답변을 찾아 background.js로 넘긴다 (11-13 실험).
// 화면 구조는 공개된 약속이 아니다. 아래 SEL은 확인하지 않은 추정이라 한곳에 모아 두고, 팝업의 '진단'으로 실제로 몇 개 찾는지 본다.
// 원칙: 페이지를 열 때 이미 있던 답변은 보내지 않는다 (지난 대화를 열기만 해도 쌓이지 않게). 전부 보내기는 팝업의 단추로만.
(() => {
  const SEL = {
    answer: ['[data-is-streaming]', '.font-claude-response', '.font-claude-message'],   // 앞에서부터 처음으로 찾히는 것을 쓴다
    question: ['[data-testid="user-message"]', '.font-user-message'],
  };
  const STABLE_MS = 2500;      // 글이 이만큼 그대로면 답변이 끝난 것으로 본다
  const pick = (list) => { for (const s of list) { const got = document.querySelectorAll(s); if (got.length) return { sel: s, els: [...got] }; } return { sel: null, els: [] }; };
  const streaming = (el) => { const s = el.closest('[data-is-streaming]') || el.querySelector('[data-is-streaming]'); return s ? s.getAttribute('data-is-streaming') === 'true' : null; };
  // 답변 묶음 안의 버튼 줄(아이콘 글꼴 글자 + '지금' 같은 시간)을 뺀다 (11-13 실제 claude.ai에서 확인: 답 끝에 아이콘 글자 줄들과 '지금'이 붙어 옴).
  // 끝에서부터 아이콘·빈 줄·짧은 줄(10자 이하)을 지나가며 가장 위의 '아이콘 글자만 있는 줄'을 찾아 거기서 자른다. 아이콘 줄이 없으면 자르지 않는다
  const PUA = new RegExp('[' + String.fromCharCode(0xE000) + '-' + String.fromCharCode(0xF8FF) + ']', 'g');   // 아이콘 글꼴이 쓰는 사용자 정의 영역 글자
  const iconOnly = (l) => l.trim() && !l.replace(PUA, '').trim();
  function clean(t) {
    const lines = t.split('\n');
    let cut = lines.length;
    for (let i = lines.length - 1; i >= 0; i--) {
      const l = lines[i].trim();
      if (iconOnly(lines[i])) { cut = i; continue; }
      if (!l || l.length <= 10) continue;
      break;
    }
    return lines.slice(0, cut).join('\n').replace(PUA, '').trim();
  }
  const textOf = (el) => clean(el.innerText || '');
  const session = () => { const m = location.pathname.match(/\/chat\/([\w-]+)/); return m ? 'claude-web:' + m[1] : null; };

  let old = new WeakSet();     // 열 때 이미 있던 답변
  const sent = new WeakSet();
  const seen = new WeakMap();  // 답변 → { text, since }
  let path = location.pathname, settled = false;

  function snapshot() {        // 지금 화면의 끝난 답변을 '이미 있던 것'으로 (쓰는 중인 답은 빼서 새 대화 첫 답을 놓치지 않게)
    old = new WeakSet();
    for (const el of pick(SEL.answer).els) if (streaming(el) !== true && textOf(el)) old.add(el);
    settled = true;
  }
  function questionBefore(el) {
    let q = null;
    for (const x of pick(SEL.question).els) if (x.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) q = x;
    return q ? textOf(q) : null;
  }
  function send(el, text) {
    sent.add(el);
    try { chrome.runtime.sendMessage({ type: 'answer', text, question: questionBefore(el), session: session() }); } catch { /* 확장이 새로 고쳐진 뒤의 옛 스크립트 */ }
  }
  function tick() {
    if (location.pathname !== path) { path = location.pathname; settled = false; setTimeout(snapshot, 1500); return; }
    if (!settled) return;
    const now = Date.now();
    for (const el of pick(SEL.answer).els) {
      if (old.has(el) || sent.has(el)) continue;
      const t = textOf(el);
      if (!t || streaming(el) === true) { seen.delete(el); continue; }
      const s = seen.get(el);
      if (!s || s.text !== t) { seen.set(el, { text: t, since: now }); continue; }
      if (now - s.since >= STABLE_MS) send(el, t);
    }
  }
  setTimeout(snapshot, 2000);
  setInterval(tick, 1000);

  chrome.runtime.onMessage.addListener((msg, _from, reply) => {
    if (msg.type === 'diagnose') {
      const a = pick(SEL.answer), q = pick(SEL.question);
      reply({ answers: a.els.length, answerSel: a.sel, questions: q.els.length, questionSel: q.sel, streamingAttr: !!document.querySelector('[data-is-streaming]'), session: session() });
    } else if (msg.type === 'send-all') {
      let n = 0;
      for (const el of pick(SEL.answer).els) { const t = textOf(el); if (t && streaming(el) !== true && !sent.has(el)) { send(el, t); n++; } }
      reply({ n });
    }
    return false;
  });
})();
