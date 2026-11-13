// 화면 점검 공용 도구: 콘솔 오류 모으기, 배치 점검(가로 스크롤·겹침·잘림·이름 없는 버튼·글자 대비·누르는 영역), 캡처 저장.
const path = require('path');
const { expect } = require('@playwright/test');

const CHAT_URL = `http://127.0.0.1:${Number(process.env.E2E_CHAT_PORT || 8791)}`;
const SHOTS = path.join(__dirname, 'screenshots');

// 콘솔 오류·잡히지 않은 예외를 모은다. 파비콘 404는 브라우저가 알아서 요청하는 것이라 따로 센다.
function watchConsole(page) {
  const out = { errors: [], favicon: 0 };
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const where = (m.location() && m.location().url) || '';
    if (/favicon\.ico/.test(where) || /favicon\.ico/.test(m.text())) { out.favicon += 1; return; }
    out.errors.push(m.text() + (where ? ` (${where})` : ''));
  });
  page.on('pageerror', (e) => out.errors.push('pageerror: ' + e.message));
  return out;
}

// 화면이 다 그려질 때까지: #view 안에 h1이 생기고 글꼴이 준비됨
async function ready(page) {
  await expect(page.locator('#view h1').first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
}

// 브라우저 안에서 배치를 잰다. 숫자만 돌려주고 판단은 시험 쪽에서 한다.
async function layoutReport(page) {
  return page.evaluate(() => {
    // 닫힌 <details> 안(요약 줄 제외)은 보이지 않는데도 Chromium이 위치를 돌려준다(실측) → 보이지 않는 것으로 친다
    const inClosed = (e) => { const d = e.closest('details:not([open])'); return !!d && !e.closest('summary'); };
    const vis = (e) => { if (inClosed(e)) return false; const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
    const name = (e) => (e.getAttribute('aria-label') || e.textContent || e.getAttribute('title') || e.value || e.placeholder || '').trim();
    const desc = (e) => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : '') + ` "${name(e).slice(0, 30)}"`;
    const scrollableX = (e) => { for (let p = e; p && p !== document.body; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if ((o === 'auto' || o === 'scroll') && p.scrollWidth > p.clientWidth) return true; } return false; };

    // 1. 가로 스크롤
    const doc = document.documentElement;
    const hScroll = doc.scrollWidth > doc.clientWidth + 1 ? { scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth,
      culprits: [...document.querySelectorAll('body *')].filter((e) => vis(e) && !scrollableX(e.parentElement || e) && e.getBoundingClientRect().right > doc.clientWidth + 1).slice(0, 5).map(desc) } : null;

    // 2. 잘린 글자: 넘친 내용을 숨기는 상자(overflow hidden/clip, 말줄임) — 스스로 가로 스크롤되는 상자(pre·표)는 제외
    const srOnly = (e) => { const r = e.getBoundingClientRect(); return r.width <= 1 && r.height <= 1; };   // 화면 낭독기 전용(1px)은 일부러 숨긴 것
    const clipped = [...document.querySelectorAll('body *')].filter((e) => {
      if (!vis(e) || !e.textContent.trim() || srOnly(e)) return false;
      const s = getComputedStyle(e);
      const hides = ['hidden', 'clip'].includes(s.overflowX) || ['hidden', 'clip'].includes(s.overflowY) || s.textOverflow === 'ellipsis';
      return hides && (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1);
    }).map(desc);

    // 3. 누를 수 있는 것: 이름, 겹침, 크기
    const ctrls = [...document.querySelectorAll('a[href], button, input, textarea, select, summary')].filter(vis);
    const nameless = ctrls.filter((e) => !name(e)).map(desc);
    // 고정 요소(상단 바·하단 독)는 본문이 그 밑으로 스크롤되어 지나가는 것이 정상이라 본문과는 비교하지 않는다 (가려짐은 시험에서 맨 아래로 내려 따로 본다)
    const fixedOf = (e) => { for (let p = e; p; p = p.parentElement) { const pos = getComputedStyle(p).position; if (pos === 'fixed' || pos === 'sticky') return p; } return null; };
    // 스크롤 상자(overflow auto/scroll/hidden) 안의 요소는 그 상자에 보이는 부분만 비교한다 (상자 밖으로 스크롤된 부분은 화면에 없다)
    const clipTo = (e, r) => { let { left, top, right, bottom } = r; for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) { if (getComputedStyle(p).overflowY === 'visible' && getComputedStyle(p).overflowX === 'visible') continue; const c = p.getBoundingClientRect(); left = Math.max(left, c.left); top = Math.max(top, c.top); right = Math.min(right, c.right); bottom = Math.min(bottom, c.bottom); } return { left, top, right, bottom }; };
    const rects = ctrls.map((e) => ({ e, rs: [...e.getClientRects()].map((r) => clipTo(e, r)).filter((r) => r.right - r.left > 1 && r.bottom - r.top > 1), fx: fixedOf(e) }));
    const overlaps = [];
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i]; const b = rects[j];
      if (a.e.contains(b.e) || b.e.contains(a.e)) continue;
      if (a.fx !== b.fx) continue;
      for (const r1 of a.rs) for (const r2 of b.rs) {
        const w = Math.min(r1.right, r2.right) - Math.max(r1.left, r2.left);
        const h = Math.min(r1.bottom, r2.bottom) - Math.max(r1.top, r2.top);
        if (w > 1 && h > 1) overlaps.push(`${desc(a.e)} × ${desc(b.e)}`);
      }
    }
    const small = ctrls.filter((e) => { const r = e.getBoundingClientRect(); return r.height < 44 || r.width < 44; })
      .map((e) => { const r = e.getBoundingClientRect(); return `${desc(e)} ${Math.round(r.width)}×${Math.round(r.height)}`; });

    // 4. 글자 대비 (WCAG): 글자가 있는 요소의 글자색과, 위로 올라가며 겹친 배경색을 섞은 색. 배경 그림·흐림이 있으면 '판단 못함'으로 센다
    const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: v[0], g: v[1], b: v[2], a: v[3] === undefined ? 1 : v[3] }; };
    const over = (top, bottom) => ({ r: top.r * top.a + bottom.r * (1 - top.a), g: top.g * top.a + bottom.g * (1 - top.a), b: top.b * top.a + bottom.b * (1 - top.a), a: 1 });
    const lum = (c) => { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
    const bgOf = (e) => {
      const layers = [];
      for (let p = e; p; p = p.parentElement) {
        const s = getComputedStyle(p);
        if (s.backgroundImage !== 'none' || (s.backdropFilter && s.backdropFilter !== 'none')) return null;
        const c = parse(s.backgroundColor);
        if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
      }
      let out = { r: 255, g: 255, b: 255, a: 1 };
      for (const c of layers.reverse()) out = over(c, out);
      return out;
    };
    const lowContrast = []; let unknownContrast = 0;
    for (const e of document.querySelectorAll('body *')) {
      if (!vis(e) || e.closest('[disabled]')) continue;
      if (![...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
      const s = getComputedStyle(e);
      const bg = bgOf(e);
      if (!bg) { unknownContrast += 1; continue; }
      const fg = over(parse(s.color), bg);
      const size = parseFloat(s.fontSize); const bold = Number(s.fontWeight) >= 700;
      const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
      const r = ratio(fg, bg);
      if (r < need) lowContrast.push(`${desc(e)} ${r.toFixed(2)} < ${need}`);
    }
    return { hScroll, clipped, nameless, overlaps: [...new Set(overlaps)], small, lowContrast, unknownContrast };
  });
}

// 반드시 지킬 것은 실패로, 디자인 기준(누르는 영역 44px)은 보고로 남긴다
async function checkLayout(page, testInfo, label) {
  const r = await layoutReport(page);
  await testInfo.attach(`layout-${label}.json`, { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
  if (r.small.length) testInfo.annotations.push({ type: '누르는 영역 44px 미만', description: `${label}: ${r.small.length}개 — ${r.small.slice(0, 6).join(' / ')}` });
  if (r.unknownContrast) testInfo.annotations.push({ type: '대비 판단 못함(배경 그림·흐림)', description: `${label}: ${r.unknownContrast}개` });
  expect.soft(r.hScroll, `${label}: 가로 스크롤`).toBeNull();
  expect.soft(r.clipped, `${label}: 잘린 글자`).toEqual([]);
  expect.soft(r.nameless, `${label}: 이름 없는 버튼·링크`).toEqual([]);
  expect.soft(r.overlaps, `${label}: 겹친 버튼·링크`).toEqual([]);
  expect.soft(r.lowContrast, `${label}: 글자 대비 부족`).toEqual([]);
  return r;
}

async function shot(page, testInfo, name) {
  const file = path.join(SHOTS, testInfo.project.name, name + '.png');
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled' });
  return file;
}

module.exports = { CHAT_URL, watchConsole, ready, layoutReport, checkLayout, shot };
