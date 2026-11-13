// 불러오는 중 · 오류 상태 (가짜 응답). 서버가 늦거나 실패해도 화면이 멈추지 않고 알려 주는지 본다.
const { test, expect } = require('@playwright/test');
const { mockApi } = require('./mock/api_mock');
const { watchConsole, ready, shot } = require('./helpers');

test('[mock] 불러오는 중 (Loading)', async ({ page }, testInfo) => {
  let release;
  const gate = new Promise((r) => { release = r; });
  await mockApi(page, { '/api/study/today': async () => { await gate; return { status: 200, body: { project: null, groups: [], items: [], counts: { shown: 0, known: 0, left: 0, hidden: 0, questions: 0, extra: 0 } } }; } });
  await page.goto('/classic.html?static=1#/');
  await expect(page.locator('#view')).toHaveText('불러오는 중…');
  await shot(page, testInfo, '20-loading');
  release();
  await ready(page);
  await expect(page.locator('#view h1')).toHaveText('오늘 볼 개념이 없어요');
});

test('[mock] 서버 오류 500 → 오류 화면 (Error)', async ({ page }, testInfo) => {
  const con = watchConsole(page);
  await mockApi(page, { '/api/study/today': () => ({ status: 500, body: { error: '[테스트] 서버 오류' } }) });
  await page.goto('/classic.html?static=1#/');
  await ready(page);
  await expect(page.locator('#view h1')).toHaveText('불러오지 못했어요');
  await expect(page.locator('#view')).toContainText('[테스트] 서버 오류');
  await expect(page.locator('#view')).toContainText('python dev.py app');
  await shot(page, testInfo, '21-error');
  expect(con.errors.filter((e) => !/status of 500/.test(e)), '500 응답 로그 말고 다른 오류 없음').toEqual([]);
});

test('[mock] 서버가 꺼짐 (네트워크 실패) → 오류 화면, 상태 줄 비움', async ({ page }) => {
  await page.route(/\/api\//, (r) => r.abort('connectionrefused'));
  await page.goto('/classic.html?static=1#/');
  await ready(page);
  await expect(page.locator('#view h1')).toHaveText('불러오지 못했어요');
  await expect(page.locator('#status')).toHaveText('');
});

test('[mock] 없는 개념 404 → 오류 화면에 서버 설명', async ({ page }) => {
  await mockApi(page);
  await page.goto('/classic.html?static=1#/c/' + encodeURIComponent('없는개념'));
  await ready(page);
  await expect(page.locator('#view h1')).toHaveText('불러오지 못했어요');
  await expect(page.locator('#view')).toContainText('없는 개념');
});

test('[mock] AI 꺼짐 상태 줄', async ({ page }) => {
  await mockApi(page, { '/api/health': { llm: { name: 'off', available: false }, jobs: {}, study_worker: false, turns: 0, sessions: 0, web: true } });
  await page.goto('/classic.html?static=1#/');
  await ready(page);
  await expect(page.locator('#status')).toHaveText('AI 요약 꺼짐: 출처 문장만 보여 줘요');
});

// 기록 요청이 실패하면 사용자에게 알리고, 화면을 떠나지 않아야 한다
for (const [button, path] of [['이해했어요', 'progress'], ['맞아요', 'feedback']]) {
  test(`[mock] ${button} 저장 실패 → 알림, 잡히지 않은 오류 없음`, async ({ page }) => {
    const con = watchConsole(page);
    await mockApi(page, { [`POST /api/study/concept/가상환경/${path}`]: () => ({ status: 500, body: { error: '[테스트] 저장 실패' } }) });
    await page.goto('/classic.html?static=1#/c/' + encodeURIComponent('가상환경'));
    await ready(page);
    await page.getByRole('button', { name: button }).click();
    await expect(page.getByText('[테스트] 저장 실패')).toBeVisible();
    expect(decodeURIComponent(await page.evaluate(() => location.hash))).toBe('#/c/가상환경');
    expect(con.errors.filter((e) => e.startsWith('pageerror')), '잡히지 않은 오류').toEqual([]);
  });
}

test('[mock] 숨긴 낱말 되돌리기 저장 실패 → 알림', async ({ page }) => {
  const con = watchConsole(page);
  await mockApi(page, { 'POST /api/study/concept/폴더/feedback': () => ({ status: 500, body: { error: '[테스트] 저장 실패' } }) });
  await page.goto('/classic.html?static=1#/hidden');
  await ready(page);
  await page.getByRole('button', { name: '공부할 개념이에요' }).first().click();
  await expect(page.getByText('[테스트] 저장 실패')).toBeVisible();
  expect(con.errors.filter((e) => e.startsWith('pageerror')), '잡히지 않은 오류').toEqual([]);
});

test('[mock] 대화 글의 HTML을 실행하지 않음', async ({ page }) => {
  const data = require('./mock/api_mock').base();
  const a = data['/api/answers/a1'];
  a.text = '[테스트] <img src=x onerror="window.HACKED=1"> <script>window.HACKED=2</script>';
  a.question = '<b>[테스트]</b>';
  await mockApi(page, { '/api/answers/a1': a });
  await page.goto('/classic.html?static=1#/a/a1');
  await ready(page);
  await expect(page.locator('.md img')).toHaveCount(0);
  expect(await page.evaluate(() => window.HACKED)).toBeUndefined();
  await expect(page.locator('#view')).toContainText('<b>[테스트]</b>');
});

test('[mock] 움직임 줄이기 설정에서 도는 애니메이션 없음', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mockApi(page);
  await page.goto('/classic.html?static=1#/');
  await ready(page);
  const running = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === 'running' && (a.effect.getTiming().iterations === Infinity || a.effect.getComputedTiming().duration > 10)).length);
  expect(running).toBe(0);
});
