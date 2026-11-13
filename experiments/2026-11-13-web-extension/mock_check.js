// 확장 프로그램 동작 점검 (11-13 실험). 진짜 claude.ai가 아니라 가짜 claude.ai 화면(아래 MOCK)으로 '구조가 추정과 같을 때' 흐름만 확인한다.
// 실제 claude.ai 화면 구조가 추정과 같은지는 이 점검으로 알 수 없다 → 사용자 브라우저에서 팝업 '진단'으로 확인 (README).
// 개인 데이터는 쓰지 않는다: 임시 폴더의 빈 DB·인박스로 시험 서버(포트 8795)를 띄우고, 확장 사본의 주소만 그 포트로 바꾼다 (같은 key → 같은 ID).
// 실행: node experiments/2026-11-13-web-extension/mock_check.js
const { chromium } = require('@playwright/test');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const PORT = 8795;
const PY = path.join(ROOT, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'thynk-ext-'));
const inbox = path.join(tmp, 'inbox.jsonl');
const ext = path.join(tmp, 'ext');

// 가짜 claude.ai (실제처럼 답 묶음 끝에 아이콘 버튼 줄·'지금'이 붙음): 이미 있던 답 1개 → 3초 뒤 새 질문 + 쓰는 중인 답 → 2초 동안 글이 늘어남 → 끝
const MOCK = `<!doctype html><meta charset="utf-8"><title>mock</title><body><div id="log">
<div data-testid="user-message">예전 질문</div><div data-is-streaming="false"><div class="font-claude-response">예전 답변: 이미 있던 글은 보내지 않아야 한다.</div></div></div>
<script>
const log = document.getElementById('log');
function turn(q, parts, delay) {
  setTimeout(() => {
    const u = document.createElement('div'); u.dataset.testid = 'user-message'; u.textContent = q; log.append(u);
    const w = document.createElement('div'); w.setAttribute('data-is-streaming', 'true');
    const a = document.createElement('div'); a.className = 'font-claude-response'; w.append(a); log.append(w);
    parts.forEach((p, i) => setTimeout(() => { a.textContent += p; if (i === parts.length - 1) { for (const c of [0xe056, 0xe0e4, 0xe0fb]) { const b = document.createElement('div'); b.textContent = String.fromCharCode(c); w.append(b); } const tm = document.createElement('div'); tm.textContent = '지금'; w.append(tm); w.setAttribute('data-is-streaming', 'false'); } }, 400 * (i + 1)));
  }, delay);
}
turn('쿠버네티스가 뭐야?', ['쿠버네티스는 ', '컨테이너를 ', '여러 서버에 ', '배치하고 관리하는 도구다.'], 3000);
window.second = () => turn('파드는?', ['파드는 ', '쿠버네티스의 가장 작은 배포 단위다.'], 0);
</script>`;

const lines = () => (fs.existsSync(inbox) ? fs.readFileSync(inbox, 'utf-8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : []);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const ok = (name, cond, info = '') => { results.push([name, !!cond]); console.log((cond ? '[OK]   ' : '[FAIL] ') + name + (info ? ' — ' + info : '')); };

(async () => {
  fs.cpSync(path.join(ROOT, 'extension'), ext, { recursive: true });
  for (const f of ['background.js', 'popup.js', 'popup.html', 'manifest.json']) {
    const p = path.join(ext, f); fs.writeFileSync(p, fs.readFileSync(p, 'utf-8').replaceAll('127.0.0.1:8765', '127.0.0.1:' + PORT));
  }
  const srv = spawn(PY, ['kit/serve.py', '--port', String(PORT), '--db', path.join(tmp, 'db.sqlite'), '--inbox', inbox, '--searx', 'off', '--llm', 'off'], { cwd: ROOT, stdio: 'ignore', env: { ...process.env, PYTHONUTF8: '1' } });
  let ctx;
  try {
    for (let i = 0; i < 60; i++) { try { if ((await fetch(`http://127.0.0.1:${PORT}/api/health`)).ok) break; } catch { /* 아직 */ } await wait(500); }
    ctx = await chromium.launchPersistentContext(path.join(tmp, 'profile'), { channel: 'chromium', headless: true, args: [`--disable-extensions-except=${ext}`, `--load-extension=${ext}`] });
    let [sw] = ctx.serviceWorkers(); if (!sw) sw = await ctx.waitForEvent('serviceworker');
    const id = sw.url().split('/')[2];
    ok('확장 ID가 서버가 허락한 ID와 같음', id === 'idefgkkfmkgofakkaapjnafeleebnfla', id);
    await ctx.route('https://claude.ai/**', (r) => r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: MOCK }));
    const page = await ctx.newPage();
    await page.goto('https://claude.ai/chat/abc-123');
    await wait(11000);
    let got = lines();
    const ans = got.filter((x) => x.role === 'assistant');
    ok('새로 끝난 답변 1개만 보냄 (이미 있던 답은 안 보냄)', ans.length === 1 && ans[0].text.includes('배치하고 관리하는 도구다.'), JSON.stringify(ans.map((x) => x.text)));
    ok('쓰는 중 글이 아니라 끝난 글 전체', ans[0] && ans[0].text === '쿠버네티스는 컨테이너를 여러 서버에 배치하고 관리하는 도구다.');
    ok('답변 앞 질문도 함께, 같은 대화로 묶임', got.some((x) => x.role === 'user' && x.text === '쿠버네티스가 뭐야?' && x.session_id === 'claude-web:abc-123') && ans[0] && ans[0].session_id === 'claude-web:abc-123' && ans[0].source === 'claude-web');

    const pop = await ctx.newPage();
    await pop.goto(`chrome-extension://${id}/popup.html`);
    await wait(1500);
    ok('팝업: 연결됨 · 오늘 보낸 답변 1개', (await pop.textContent('#conn')) === '연결됨' && (await pop.textContent('#added')) === '1개', `${await pop.textContent('#conn')} / ${await pop.textContent('#added')}`);
    await pop.click('#toggle');
    await wait(300);
    ok('팝업: 멈춤으로 바뀜', (await pop.getAttribute('#toggle', 'aria-pressed')) === 'false');
    await page.bringToFront();
    await page.evaluate(() => window.second());
    await wait(7000);
    ok('멈춤이면 보내지 않음', lines().filter((x) => x.role === 'assistant').length === 1);
    await pop.click('#toggle');
    await page.evaluate(() => window.second());
    await wait(7000);
    ok('다시 켜면 보냄', lines().filter((x) => x.role === 'assistant').length === 2);
    const r = await page.evaluate((p) => fetch(`http://127.0.0.1:${p}/api/ingest`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: 'x' }) }).then((x) => x.status).catch(() => 'blocked'), PORT);
    ok('claude.ai 페이지가 직접 보내는 요청은 막힘', r !== 200, String(r));
  } finally {
    if (ctx) await ctx.close();
    srv.kill();
    await wait(800);
    try { fs.rmSync(tmp, { recursive: true, force: true }); } catch { /* 임시 폴더 */ }
  }
  const bad = results.filter(([, c]) => !c).length;
  fs.writeFileSync(path.join(__dirname, 'mock_results.json'), JSON.stringify({ run_at: new Date().toISOString(), passed: results.length - bad, failed: bad, checks: results.map(([n, c]) => ({ name: n, ok: c })) }, null, 1) + '\n');
  console.log(`\n결과: ${bad ? '실패 ' + bad + '개' : '모두 통과'}`);
  process.exit(bad ? 1 : 0);
})();
