// 시안(app/atelier.html) 화면 캡처 — 보기 쉬운 한 벌 + 한눈에보기.html
//   node tests/e2e/capture.js [서버 주소]   (기본 http://127.0.0.1:8765, 실제 DB 사본 서버를 주면 원본에 '열어 본 기록'이 남지 않는다)
// 결과: tests/e2e/screenshots/ (git 제외 — 내 대화 내용이 들어 있다). 이전 캡처는 지우고 새로 만든다.
const { chromium } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, 'screenshots');
const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');

(async () => {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const get = async (p) => (await fetch(BASE + p)).json();
  const concepts = (await get('/api/study/concepts?view=show&k=500')).items;
  const rich = concepts.find((x) => x.id === '데이터베이스') || concepts.find((x) => x.line_kind === 'ai_checked') || concepts[0];
  const answer = (await get('/api/answers?k=1')).items[0];
  const SCREENS = [['01', '오늘공부', '#/'], ...(rich ? [['02', '개념노트', '#/c/' + encodeURIComponent(rich.id)]] : []), ['03', '답변기록', '#/answers'],
    ...(answer ? [['04', '답변읽기', '#/a/' + encodeURIComponent(answer.id)]] : []), ['05', '전체개념', '#/all'],
    // 분야를 고르고 관계 그래프에서 개념 하나를 고른 상태 (조작이 필요한 화면)
    ['05b', '전체개념_분야선택', '#/all', async (page) => { await page.locator('.lib-tile').first().click(); await page.locator('summary', { hasText: '이 분야의 개념 관계 보기' }).click(); await page.locator('.lib-graph .n').nth(2).click(); await page.waitForTimeout(300); }],
    ['06', '숨긴개념', '#/hidden'], ['07', '기록에묻기', '#/chat']];
  const SIZES = [['1440', 1440, 1000, 1], ['768', 768, 1024, 1], ['390', 390, 844, 2]];
  const browser = await chromium.launch();
  const made = [];
  for (const [label, w, hgt, dsf] of SIZES) {
    const page = await browser.newPage({ viewport: { width: w, height: hgt }, deviceScaleFactor: dsf });
    for (const [no, name, hash, act] of SCREENS) {
      await page.goto(BASE + '/atelier.html?static=1' + hash);
      await page.waitForSelector('#view h1');
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(500);
      if (act) await act(page);
      // 전체 페이지 캡처용: 고정 하단 메뉴를 페이지 맨 끝으로 옮긴다 (실제 화면에서는 화면 아래에 고정)
      await page.evaluate(() => {
        if (innerWidth <= 900) { const nav = document.querySelector('.nav'); nav.style.position = 'static'; document.body.append(nav); document.body.style.paddingBottom = '0'; }
        document.querySelectorAll('.reveal').forEach((e) => { e.style.animation = 'none'; });
      });
      const file = `${no}_${name}_${label}.png`;
      await page.screenshot({ path: path.join(OUT, file), fullPage: true });
      made.push({ no, name, label, file });
    }
    await page.close();
  }
  await browser.close();
  const rows = [...new Set(made.map((m) => m.no))].map((no) => {
    const r = made.filter((m) => m.no === no);
    return `<section><h2>${no} ${r[0].name}</h2><div class="row">${r.map((m) => `<figure><figcaption>${m.label}px</figcaption><a href="${m.file}" target="_blank"><img src="${m.file}" loading="lazy" alt="${m.name} ${m.label}px"></a></figure>`).join('')}</div></section>`;
  }).join('\n');
  fs.writeFileSync(path.join(OUT, '한눈에보기.html'), `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>개념 차트 화면 캡처</title><style>
body{margin:0;padding:32px;background:#f4f0e8;color:#171c32;font:15px/1.6 "Pretendard Variable",Pretendard,"Malgun Gothic",sans-serif}
h1{font:700 28px/1.3 inherit;margin:0 0 4px}p{margin:0 0 24px;color:#5c6074}
section{margin-bottom:40px}h2{font:700 20px/1.4 inherit;border-bottom:1px solid #d8d5cb;padding-bottom:6px}
.row{display:flex;gap:24px;align-items:flex-start;overflow-x:auto}figure{margin:0;flex:none}
figcaption{font:600 13px/1.4 inherit;color:#5c6074;margin-bottom:6px}img{display:block;height:640px;width:auto;border:1px solid #d8d5cb;background:#fff}
</style></head><body><h1>개념 차트 · 화면 캡처</h1><p>${new Date().toLocaleString('ko-KR')} · ${BASE} · 그림을 누르면 원본 크기로 열려요 · 태블릿·모바일 하단 메뉴는 캡처를 위해 맨 아래에 두었어요(실제로는 화면 아래 고정)</p>
${rows}</body></html>`);
  console.log(`${made.length}장 → ${OUT}`);
})();
