// 실제 서버(kit/serve.py)를 빈 임시 DB로 띄워 점검한다. 가짜 데이터 없음, 읽기 요청만 (데이터를 바꾸지 않는다).
// 처음 쓰는 사람이 보는 빈 화면과, 응답 모양이 docs/API.md 계약대로인지 본다.
const { test, expect } = require('@playwright/test');
const { watchConsole, ready, checkLayout, shot } = require('./helpers');

test.describe('[real] 빈 데이터', () => {
  let con;
  test.beforeEach(async ({ page }) => { con = watchConsole(page); });
  test.afterEach(async () => { expect(con.errors, '콘솔 오류').toEqual([]); });

  const SCREENS = [
    ['30-real-today-empty', '#/', '오늘 볼 개념이 없어요', ['AI 답변이 쌓이면 여기에 공부할 개념이 나타나요.', 'AI 답변 붙여넣기']],
    ['31-real-answers-empty', '#/answers', 'AI 답변 읽기', ['아직 답변이 없어요.']],
    ['32-real-all-empty', '#/all', '전체 개념 0개', ['중요도 순서예요.']],
    ['33-real-hidden-empty', '#/hidden', '숨긴 낱말 0개', ['되돌릴 수 있어요']],
  ];
  for (const [name, hash, title, texts] of SCREENS) {
    test(`${name}`, async ({ page }, testInfo) => {
      await page.goto('/classic.html' + hash);
      await ready(page);
      await expect(page.locator('#view h1')).toHaveText(title);
      for (const t of texts) await expect(page.locator('#view')).toContainText(t);
      await expect(page.locator('#status')).toHaveText('AI 요약 꺼짐: 출처 문장만 보여 줘요');
      await checkLayout(page, testInfo, name);
      await shot(page, testInfo, name);
    });
  }

  test('빈 화면의 "AI 답변 붙여넣기" 링크 → 답변 화면', async ({ page }) => {
    await page.goto('/classic.html#/');
    await ready(page);
    await page.getByRole('link', { name: 'AI 답변 붙여넣기' }).click();
    await expect(page.locator('#view h1')).toHaveText('AI 답변 읽기');
  });

  test('없는 개념 → 서버의 404 설명', async ({ page }) => {
    await page.goto('/classic.html#/c/' + encodeURIComponent('없는개념'));
    await ready(page);
    await expect(page.locator('#view h1')).toHaveText('불러오지 못했어요');
    await expect(page.locator('#view')).toContainText('없는 개념');
    con.errors = con.errors.filter((e) => !/status of 404/.test(e));      // 404 응답 로그는 의도한 것
  });
});

test('[real] API 응답 모양 (docs/API.md)', async ({ request }) => {
  const get = async (p) => { const r = await request.get(p); expect(r.ok(), p).toBeTruthy(); return r.json(); };
  const today = await get('/api/study/today?k=7');
  expect(Object.keys(today)).toEqual(expect.arrayContaining(['groups', 'items', 'counts']));
  expect(Object.keys(today.counts)).toEqual(expect.arrayContaining(['shown', 'known', 'left', 'hidden', 'questions', 'extra']));
  const concepts = await get('/api/study/concepts?view=show&k=50');
  expect(Object.keys(concepts)).toEqual(expect.arrayContaining(['items', 'n_sessions', 'total_words']));
  expect(Object.keys(await get('/api/study/history?k=50'))).toContain('items');
  expect(Object.keys(await get('/api/answers?k=20'))).toContain('items');
  const health = await get('/api/health');
  expect(Object.keys(health)).toEqual(expect.arrayContaining(['llm', 'jobs', 'study_worker', 'turns', 'sessions', 'web']));
  const missing = await request.get('/api/study/concept/' + encodeURIComponent('없는개념'));
  expect(missing.status()).toBe(404);
  expect(await missing.json()).toHaveProperty('error');
});
