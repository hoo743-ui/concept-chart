// 콘텐츠 렌더러: 받은 글을 종류별로 나눠 안전하게 그린다. 원문은 바꾸지 않는다 (보여 주는 방식만 다르다).
// 모든 글은 textContent로 넣는다 — HTML·스크립트는 실행되지 않는다.
//   - 봉투(envelope): 질문 전체를 감싼 <pasted_content …> / <agent-message …> 같은 태그. 실측(11-11): 질문 225개 중 31개.
//     태그를 지우지 않고 '종류 라벨 + 안쪽 첫 줄 제목'으로 보여 주고, 원문은 '원문 그대로 보기'로 언제든 본다.
//   - 본문: Markdown(제목 단계·목록·표·인용·링크) / 코드 블록 / JSON(접힌 카드 → 펼치면 정렬된 트리) / HTML·XML(코드로, 실행 안 함)
const Render = (() => {
  function el(tag, props = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) e.append(kid);
    return e;
  }
  const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : null);
  const clip = (t, n) => { t = (t || '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n).replace(/\s\S*$/, '') + '…' : t; };

  // ---------- 복사 ----------
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* 아래 대체 방법 */ }
    try { const ta = el('textarea', { style: 'position:fixed;opacity:0' }); ta.value = text; document.body.append(ta); ta.select(); const ok = document.execCommand('copy'); ta.remove(); return ok; } catch { return false; }
  }
  function copyButton(getText, label = '원본 복사') {
    const b = el('button', { class: 'btn quiet small copy', type: 'button' }, label);
    b.addEventListener('click', async (e) => {
      e.preventDefault(); e.stopPropagation();
      const ok = await copyText(getText());
      b.textContent = ok ? '복사했어요 ✓' : '복사하지 못했어요';
      b.classList.toggle('done', ok);
      clearTimeout(b._t); b._t = setTimeout(() => { b.textContent = label; b.classList.remove('done'); }, 1600);
    });
    return b;
  }

  // ---------- 봉투 ----------
  const KINDS = { pasted_content: '붙여 넣은 글', 'agent-message': '다른 에이전트의 보고', 'cross-session-message': '다른 세션의 메시지', 'system-reminder': '시스템 안내', 'task-notification': '작업 알림' };
  // 글 전체가 <태그 …> … </태그> 로 감싸였을 때만 봉투로 본다. 확실하지 않으면 null (그대로 일반 글)
  function envelope(text) {
    const t = text || '';
    const m = t.match(/^\s*<([A-Za-z][\w-]*)((?:\s+[\w:-]+="[^"]*")*)\s*\/?>/);
    if (!m) {
      // 목록 API가 첫 줄을 80자에서 자르면 여는 태그의 '>'까지 잘린다(실측: <cross-session-message from="uds:…). 한 줄짜리 잘린 여는 태그만 봉투로 본다
      const cut = t.match(/^\s*<([A-Za-z][\w-]*)\s+[\w:-]+="[^\n>]*$/);
      if (!cut) return null;
      const name = (t.match(/from-name="([^"]*)"/) || [])[1] || null;
      return { tag: cut[1], attrs: {}, inner: '', closed: false, truncated: true, title: '', label: KINDS[cut[1]] || `<${cut[1]}> 형식의 기술 데이터`, from: name };
    }
    const tag = m[1];
    const attrs = {}; for (const a of m[2].matchAll(/([\w:-]+)="([^"]*)"/g)) attrs[a[1]] = a[2];
    let inner = t.slice(m[0].length);
    const close = inner.search(new RegExp('<\\/' + tag.replace(/[-]/g, '\\-') + '\\b[^>]*>\\s*$'));
    const closed = close >= 0;
    if (closed) inner = inner.slice(0, close);
    inner = inner.replace(/^\s*\n/, '');
    // 제목: 안쪽 첫 의미 있는 줄 (Markdown 제목 기호·고정 머리말 [..]만 떼고, 글은 그대로)
    const first = inner.split('\n').map((l) => l.trim()).find((l) => l && !/^[-=*_]{3,}$/.test(l)) || '';
    // 에이전트 보고의 고정 머리말([Subagent hand-back] 등)만 뗀다. 사용자가 쓴 [..]는 그대로 (실측: [테스트]가 지워졌던 것)
    let title = first.replace(/^#{1,6}\s+/, '').replace(/^\*\*(.+)\*\*$/, '$1').trim();
    if (tag === 'agent-message') title = title.replace(/^\[[^\]]{1,40}\]\s*/, '');
    return { tag, attrs, inner, closed, title, label: KINDS[tag] || `<${tag}> 형식의 기술 데이터`, from: attrs['from-name'] || null };
  }

  // 질문 보기: 봉투면 라벨 + 제목, 아니면 질문 그대로. full이 있으면 원문 보기·복사
  function question(text, { full, size = 'card', link } = {}) {
    const raw = full || text || '';
    const env = envelope(raw) || envelope(text || '');
    const box = el('div', { class: 'qview ' + size });
    if (env) {
      box.append(el('span', { class: 'qbadge' }, env.label + (env.from ? ' · ' + env.from : '')));
      box.append(el(size === 'page' ? 'h1' : 'p', { class: 'qtitle' }, env.title ? clip(env.title, size === 'page' ? 160 : 90) : '내용은 원래 답변에서 볼 수 있어요'));
    } else box.append(el(size === 'page' ? 'h1' : 'p', { class: 'qtitle' }, '“' + clip(raw, size === 'page' ? 200 : 110) + '”'));
    if (env || raw.length > 110) {
      const d = el('details', { class: 'raw' }, el('summary', {}, '원문 그대로 보기'),
        el('div', { class: 'raw-body' }, el('pre', { class: 'raw-pre' }, raw), el('div', { class: 'raw-actions' }, copyButton(() => raw), full && full.length >= 500 ? el('span', { class: 'meta' }, '처음 500자까지예요. 전체는 원래 답변에서 볼 수 있어요.') : null)));
      box.append(d);
    }
    if (link) box.append(link);
    return box;
  }

  // ---------- JSON ----------
  function jsonSummary(v) {
    if (Array.isArray(v)) return `배열 · ${v.length}개 항목`;
    if (v && typeof v === 'object') { const k = Object.keys(v); return `객체 · 항목 ${k.length}개` + (k.length ? ` (${k.slice(0, 4).join(', ')}${k.length > 4 ? ', …' : ''})` : ''); }
    return '값 하나';
  }
  function jsonTree(v, depth = 0) {
    const pad = '  '.repeat(depth);
    if (v === null) return [el('span', { class: 'j-null' }, 'null')];
    if (typeof v === 'string') return [el('span', { class: 'j-str' }, JSON.stringify(v))];
    if (typeof v === 'number') return [el('span', { class: 'j-num' }, String(v))];
    if (typeof v === 'boolean') return [el('span', { class: 'j-bool' }, String(v))];
    const arr = Array.isArray(v), entries = arr ? v.map((x, i) => [i, x]) : Object.entries(v);
    if (!entries.length) return [el('span', { class: 'j-punc' }, arr ? '[]' : '{}')];
    const out = [el('span', { class: 'j-punc' }, arr ? '[' : '{'), '\n'];
    entries.forEach(([k, x], i) => {
      out.push(pad + '  ');
      if (!arr) out.push(el('span', { class: 'j-key' }, JSON.stringify(k)), el('span', { class: 'j-punc' }, ': '));
      out.push(...jsonTree(x, depth + 1));
      if (i < entries.length - 1) out.push(el('span', { class: 'j-punc' }, ','));
      out.push('\n');
    });
    out.push(pad, el('span', { class: 'j-punc' }, arr ? ']' : '}'));
    return out;
  }
  function jsonBlock(raw) {
    let v, ok = true;
    try { v = JSON.parse(raw); } catch { ok = false; }
    const head = el('summary', {}, el('span', { class: 'blk-label' }, ok ? '구조화된 데이터 · JSON' : 'JSON처럼 보이는 글'), el('span', { class: 'blk-sum' }, ok ? jsonSummary(v) : '형식이 맞지 않아 원문 그대로 보여 줘요'), el('span', { class: 'blk-open' }, '펼쳐 보기'));
    return el('details', { class: 'blk json' }, head, el('div', { class: 'blk-body' },
      el('div', { class: 'blk-actions' }, copyButton(() => raw)),
      el('pre', { class: 'json-tree', tabindex: '0', 'aria-label': 'JSON 내용' }, ok ? jsonTree(v) : raw)));
  }
  const looksJson = (s) => { const t = (s || '').trim(); if (!/^[[{]/.test(t)) return false; try { const v = JSON.parse(t); return v !== null && typeof v === 'object'; } catch { return /^\{\s*"/.test(t); } };

  // ---------- 코드 ----------
  const LANG = { '': '코드', bash: 'Bash', sh: 'Shell', shell: 'Shell', powershell: 'PowerShell', ps1: 'PowerShell', python: 'Python', py: 'Python', js: 'JavaScript', javascript: 'JavaScript', html: 'HTML', xml: 'XML', css: 'CSS', sql: 'SQL', text: '텍스트' };
  function codeBlock(code, lang) {
    const l = (lang || '').toLowerCase();
    return el('figure', { class: 'blk code' }, el('figcaption', {}, el('span', { class: 'blk-label' }, LANG[l] || l || '코드'), el('span', { class: 'blk-sum' }, `${code.split('\n').length}줄`), copyButton(() => code, '복사')),
      el('pre', { tabindex: '0' }, el('code', {}, code)));
  }

  // ---------- Markdown ----------
  // 지원: 제목(#~####), 문단, 목록, 인용, 가로줄, 표, 코드 블록, **굵게**, `코드`, [링크](주소), 주소 자동 링크
  function markdown(text, { terms = [], onHeading } = {}) {
    const map = new Map(); for (const t of terms) for (const f of t.forms || []) map.set(f.toLowerCase(), t);
    const seen = new Set();
    const parts = [...map.keys()].sort((a, b) => b.length - a.length).map((f) => f.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).map((f) => (/^[a-z0-9]/.test(f) ? `(?<![A-Za-z0-9_])${f}(?![A-Za-z0-9_])` : f));
    const rx = parts.length ? new RegExp(parts.join('|'), 'gi') : null;
    const terms_ = (str) => { if (!rx) return [str]; const res = []; let last = 0; for (const m of str.matchAll(rx)) { const t = map.get(m[0].toLowerCase()); if (m.index > last) res.push(str.slice(last, m.index)); if (t && !seen.has(t.id)) { seen.add(t.id); res.push(el('mark', {}, el('a', { href: '#/c/' + encodeURIComponent(t.id), title: t.label + ' 개념 노트 열기' }, m[0]))); } else res.push(m[0]); last = m.index + m[0].length; } if (last < str.length) res.push(str.slice(last)); return res; };
    const links = (str) => str.split(/(\[[^\]\n]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s)<>"']+)/g).flatMap((p) => {
      let m = p.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      if (m && safeUrl(m[2])) return [el('a', { href: m[2], target: '_blank', rel: 'noopener noreferrer', class: 'ext' }, m[1])];
      if (/^https?:\/\//.test(p) && safeUrl(p)) return [el('a', { href: p, target: '_blank', rel: 'noopener noreferrer', class: 'ext url' }, p)];
      return terms_(p);
    });
    const inline = (s) => s.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g).flatMap((p) => (/^`[^`]+`$/.test(p) ? [el('code', {}, p.slice(1, -1))] : /^\*\*[^*]+\*\*$/.test(p) ? [el('strong', {}, ...links(p.slice(2, -2)))] : links(p)));
    const cells = (row) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
    const out = []; const lines = (text || '').replace(/\r\n/g, '\n').split('\n');
    const BLOCK = /^(```|#{1,6}\s|>\s?|\s*([-*+]|\d+[.)])\s+|\s*\|.*\|\s*$|\s*(-{3,}|\*{3,}|_{3,})\s*$)/;
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      const fence = line.match(/^```\s*([\w+-]*)/);
      if (fence) {
        const code = []; for (i += 1; i < lines.length && !/^```/.test(lines[i]); i += 1) code.push(lines[i]); i += 1;
        const body = code.join('\n');
        out.push(fence[1].toLowerCase() === 'json' || (!fence[1] && looksJson(body)) ? jsonBlock(body) : codeBlock(body, fence[1]));
      } else if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?[\s:\-|]+\|?\s*$/.test(lines[i + 1] || '')) {
        const hd = cells(line); const rows = []; for (i += 2; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i += 1) rows.push(cells(lines[i]));
        out.push(el('div', { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': '표' }, el('table', {}, el('thead', {}, el('tr', {}, hd.map((c) => el('th', {}, inline(c))))), el('tbody', {}, rows.map((r) => el('tr', {}, r.map((c) => el('td', {}, inline(c)))))))));
      } else if (/^#{1,6}\s/.test(line)) {
        const lvl = line.match(/^#+/)[0].length; const tag = lvl <= 2 ? 'h3' : lvl === 3 ? 'h4' : 'h5';
        const hEl = el(tag, { id: 'sec-' + out.length }, inline(line.replace(/^#+\s*/, '')));
        if (onHeading && tag !== 'h5') onHeading(hEl, tag === 'h3' ? 1 : 2);
        out.push(hEl); i += 1;
      } else if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { out.push(el('hr')); i += 1; }
      else if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        const ordered = /^\s*\d/.test(line); const items = [];
        for (; i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i]); i += 1) items.push(el('li', { class: /^\s{2,}/.test(lines[i]) ? 'nested' : null }, inline(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ''))));
        out.push(el(ordered ? 'ol' : 'ul', {}, items));
      } else if (/^>\s?/.test(line)) {
        const q = []; for (; i < lines.length && /^>\s?/.test(lines[i]); i += 1) q.push(lines[i].replace(/^>\s?/, ''));
        out.push(el('blockquote', {}, q.map((x) => el('p', {}, inline(x)))));
      } else if (!line.trim()) i += 1;
      else {
        const para = []; for (; i < lines.length && lines[i].trim() && !BLOCK.test(lines[i]); i += 1) para.push(lines[i]);
        if (!para.length) { para.push(line); i += 1; }
        const joined = para.join('\n');
        if (looksJson(joined)) out.push(jsonBlock(joined));
        else if (/^\s*<([A-Za-z][\w-]*)[^>]*>[\s\S]*<\/\1>\s*$/.test(joined) || /^\s*<[A-Za-z][\w-]*(\s[^>]*)?\/?>\s*$/.test(joined)) out.push(codeBlock(joined, 'html'));   // HTML·XML 조각: 실행하지 않고 코드로
        else out.push(el('p', {}, inline(para.join(' '))));
      }
    }
    return out;
  }

  // 답변·질문처럼 봉투가 있을 수 있는 글 전체: 봉투면 라벨 카드 + 안쪽을 Markdown으로
  function document_(text, opts = {}) {
    const env = envelope(text);
    if (!env) return el('div', { class: 'md' }, markdown(text, opts));
    return el('div', { class: 'md' }, el('div', { class: 'env-note' }, el('span', { class: 'qbadge' }, env.label + (env.from ? ' · ' + env.from : '')), el('span', { class: 'meta' }, `원문은 <${env.tag}> 태그로 감싸여 있어요. 태그를 지우지 않고 안쪽 내용을 읽기 좋게 보여 드려요.`), copyButton(() => text)), markdown(env.inner, opts));
  }

  return { el, envelope, question, markdown, document: document_, jsonBlock, codeBlock, copyButton, looksJson, clip };
})();
