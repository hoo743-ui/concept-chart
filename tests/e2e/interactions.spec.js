// 누르고 입력하는 동작 점검 (가짜 데이터). 서버로 가는 기록 요청은 가로채서 본문이 docs/API.md 계약대로인지 본다.
const { test, expect } = require('@playwright/test');
const { mockApi, LONG_LABEL } = require('./mock/api_mock');
const { watchConsole, ready } = require('./helpers');

const c = (id) => '#/c/' + encodeURIComponent(id);
const hashIs = (page, h) => expect.poll(() => page.evaluate(() => decodeURIComponent(location.hash))).toBe(h);
const h1 = (page) => page.locator('#view h1').first();

test.describe('[mock] 동작', () => {
  let con;
  test.beforeEach(async ({ page }) => { con = watchConsole(page); });
  test.afterEach(async () => { expect(con.errors, '콘솔 오류').toEqual([]); });

  test('메뉴 이동과 현재 위치 표시', async ({ page }) => {
    await mockApi(page);
    await page.goto('/classic.html?static=1#/');
    await ready(page);
    const nav = page.getByRole('navigation', { name: '주요 화면' });
    for (const [label, hash, title] of [['답변 읽기', '#/answers', 'AI 답변 읽기'], ['전체 개념', '#/all', '전체 개념 6개'], ['오늘 공부', '#/', '오늘 볼 개념']]) {
      const link = nav.getByRole('link', { name: label });
      await expect(link).toBeInViewport();
      await link.click();
      await hashIs(page, hash);
      await expect(h1(page)).toHaveText(title);
      await expect(link).toHaveAttribute('aria-current', 'page');
      await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
    }
    // 개념 노트·답변 읽기·숨긴 낱말에서도 알맞은 메뉴가 켜진다
    for (const [hash, tab] of [[c('가상환경'), '오늘 공부'], ['#/a/a1', '답변 읽기'], ['#/hidden', '전체 개념']]) {
      await page.goto('/classic.html?static=1' + hash);
      await ready(page);
      await expect(nav.getByRole('link', { name: tab })).toHaveAttribute('aria-current', 'page');
    }
  });

  test('개념 카드를 누르면 개념 노트', async ({ page }) => {
    await mockApi(page);
    await page.goto('/classic.html?static=1#/');
    await ready(page);
    await page.locator('a.item', { hasText: '가상환경' }).first().click();
    await hashIs(page, '#/c/가상환경');
    await expect(h1(page)).toContainText('가상환경');
    await page.getByRole('link', { name: '← 오늘 공부' }).click();
    await expect(h1(page)).toHaveText('오늘 볼 개념');
  });

  test('질문을 누르면 그 답변, 더 보기를 펼쳐 개념으로', async ({ page }) => {
    await mockApi(page);
    await page.goto('/classic.html?static=1#/');
    await ready(page);
    const more = page.locator('details.more').first();
    await expect(more.getByRole('link', { name: '레이어' })).toBeHidden();
    await more.locator('summary').click();
    await expect(more).toHaveAttribute('open', '');
    await more.getByRole('link', { name: '레이어' }).click();
    await hashIs(page, '#/c/레이어');
    await expect(h1(page)).toContainText('레이어');
    await page.goto('/classic.html?static=1#/');
    await ready(page);
    await page.locator('a.qhead').first().click();
    await hashIs(page, '#/a/a1');
    await expect(h1(page)).toHaveText('AI 답변');
  });

  for (const [button, status] of [['이해했어요', 'known'], ['다시 볼게요', 'review']]) {
    test(`학습 상태 변경: ${button} → ${status}`, async ({ page }) => {
      const calls = await mockApi(page);
      await page.goto('/classic.html?static=1' + c('가상환경'));
      await ready(page);
      await page.getByRole('button', { name: button }).click();
      await hashIs(page, '#/');
      expect(calls.posts).toEqual([{ path: '/api/study/concept/가상환경/progress', body: { status } }]);
    });
  }

  test('사용자 판단: 맞아요 · 아니에요 · 판단 지우기', async ({ page }) => {
    const calls = await mockApi(page);
    await page.goto('/classic.html?static=1' + c('가상환경'));
    await ready(page);
    await page.getByRole('button', { name: '맞아요' }).click();
    await expect.poll(() => calls.posts.length).toBe(1);
    expect(calls.posts[0]).toEqual({ path: '/api/study/concept/가상환경/feedback', body: { verdict: 'concept' } });

    await page.getByRole('button', { name: '아니에요 (목록에서 숨기기)' }).click();
    await hashIs(page, '#/');
    expect(calls.posts[1]).toEqual({ path: '/api/study/concept/가상환경/feedback', body: { verdict: 'not_concept' } });

    await page.goto('/classic.html?static=1' + c('docker'));
    await ready(page);
    await page.getByRole('button', { name: '판단 지우기' }).click();
    await expect.poll(() => calls.posts.length).toBe(3);
    expect(calls.posts[2]).toEqual({ path: '/api/study/concept/docker/feedback', body: { verdict: 'clear' } });
  });

  test('숨긴 낱말 되돌리기', async ({ page }) => {
    const calls = await mockApi(page);
    await page.goto('/classic.html?static=1#/hidden');
    await ready(page);
    await page.getByRole('button', { name: '공부할 개념이에요' }).first().click();
    await expect.poll(() => calls.posts).toEqual([{ path: '/api/study/concept/폴더/feedback', body: { verdict: 'concept' } }]);
  });

  test('검색: 이름으로 거르고 지우면 다시 전체', async ({ page }) => {
    await mockApi(page);
    await page.goto('/classic.html?static=1#/all');
    await ready(page);
    const box = page.getByRole('searchbox', { name: '개념 찾기' });
    const rows = page.locator('#view ul.list > li');
    await expect(rows).toHaveCount(6);
    await box.fill('docker');                       // 대소문자 무시
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText('Docker');
    await box.fill('');
    await expect(rows).toHaveCount(6);
  });

  test('출처 링크: 새 창·noopener, http(s)만', async ({ page }) => {
    await mockApi(page);
    await page.goto('/classic.html?static=1' + c('가상환경'));
    await ready(page);
    const link = page.getByRole('link', { name: '출처 열기' });
    await expect(link).toHaveAttribute('href', /^https:\/\//);
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', /noopener/);
    await page.locator('summary', { hasText: '근거 문장 보기' }).click();
    await expect(page.locator('.evidence').first()).toBeVisible();
    // javascript: 주소는 링크로 만들지 않는다
    await page.goto('/classic.html?static=1' + c(LONG_LABEL));
    await ready(page);
    await expect(page.getByRole('link', { name: '출처 열기' })).toHaveCount(0);
  });

  test('답변 목록 → 답변 읽기 → 표시된 개념 → 돌아오기', async ({ page }) => {
    await mockApi(page);
    await page.goto('/classic.html?static=1#/answers');
    await ready(page);
    await page.locator('a.item').first().click();
    await hashIs(page, '#/a/a1');
    await expect(page.locator('.md table td').first()).toBeVisible();
    await expect(page.locator('.md pre')).toContainText('docker run hello-world');
    await expect(page.locator('.md code', { hasText: 'docker run' })).toBeVisible();
    await expect(page.locator('.md pre mark')).toHaveCount(0);         // 코드 안에는 개념 표시 없음
    await page.locator('.md mark a').first().click();
    await expect(page).toHaveURL(/#\/c\//);
    await page.goBack();
    await hashIs(page, '#/a/a1');
    await page.getByRole('link', { name: '← 답변 목록' }).click();
    await hashIs(page, '#/answers');
  });

  test('답변 붙여넣기: 빈 칸 안내, 추가 요청', async ({ page }) => {
    const calls = await mockApi(page);
    await page.goto('/classic.html?static=1#/answers');
    await ready(page);
    await page.getByRole('button', { name: '답변 추가' }).click();
    await expect(page.getByRole('status').first()).toHaveText('붙여넣은 글이 없어요.');
    const ta = page.getByRole('textbox', { name: 'AI 답변 붙여넣기' });
    await ta.fill('[테스트] 붙여넣은 답변');
    await page.getByRole('button', { name: '답변 추가' }).click();
    await expect(page.getByText('추가했어요. 잠시 뒤 목록에 나타나요.')).toBeVisible();
    await expect(ta).toHaveValue('');
    expect(calls.posts).toEqual([{ path: '/api/ingest', body: { text: '[테스트] 붙여넣은 답변', source: 'paste' } }]);
  });

  test('답변 요약 요청 (Pending)', async ({ page }) => {
    const calls = await mockApi(page);
    await page.goto('/classic.html?static=1#/a/a2');
    await ready(page);
    const btn = page.getByRole('button', { name: '이 답변 요약하기' });
    await btn.click();
    await expect(page.getByText('요약하는 중이에요. 끝나면 여기에 나타나요.')).toBeVisible();
    await expect(btn).toBeDisabled();
    expect(calls.posts).toEqual([{ path: '/api/answers/a2/summary', body: {} }]);
  });

  test('빈칸 문제: 답 보기', async ({ page }) => {
    await mockApi(page);
    await page.goto('/classic.html?static=1' + c('가상환경'));
    await ready(page);
    await expect(page.getByText('답: 가상 환경')).toBeHidden();
    await page.getByRole('button', { name: '답 보기' }).click();
    await expect(page.getByText('답: 가상 환경')).toBeVisible();
  });

  test('키보드만으로 메뉴 이동', async ({ page }) => {
    await mockApi(page);
    await page.goto('/classic.html?static=1#/');
    await ready(page);
    // 화면이 바뀌면 앱이 초점을 본문(#view)으로 옮긴다(화면 낭독기용, 의도된 동작). 메뉴는 맨 위에서부터 Tab으로 간다
    await expect(page.locator('#view')).toBeFocused();
    await page.locator('.brand').focus();
    await page.keyboard.press('Tab');           // 오늘 공부
    await page.keyboard.press('Tab');           // 답변 읽기
    await expect(page.locator(':focus')).toHaveText('답변 읽기');
    const outline = await page.locator(':focus').evaluate((e) => getComputedStyle(e).outlineStyle);
    expect(outline, '초점 표시').not.toBe('none');
    await page.keyboard.press('Enter');
    await hashIs(page, '#/answers');
  });
});

// 좁은 화면에서는 메뉴가 화면 안에 다 보이고 눌려야 한다 (지금 화면은 햄버거 메뉴 없이 위 줄이 접혀 내려간다)
test('[mock] 모바일 메뉴: 모든 메뉴가 화면 안, 누르면 이동', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', '모바일에서만');
  await mockApi(page);
  await page.goto('/classic.html?static=1#/');
  await ready(page);
  const links = page.getByRole('navigation', { name: '주요 화면' }).getByRole('link');
  await expect(links).toHaveCount(3);
  for (const l of await links.all()) await expect(l).toBeInViewport({ ratio: 1 });
  await links.nth(2).tap();
  await hashIs(page, '#/all');
  // 아래로 내려도 메뉴가 위에 붙어 있다 (sticky)
  await page.mouse.wheel(0, 600);
  await expect(links.first()).toBeInViewport();
});
