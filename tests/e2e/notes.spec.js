// 06 나만의 노트 (11-13, app/atelier-notes.js): 이 브라우저(localStorage)에만 저장하는 따로 선 화면 + 마스코트 바로 가기 말풍선.
// 서버·DB를 쓰지 않으므로 빈 임시 DB 서버에서 노트를 직접 넣어 확인한다.
const { test, expect } = require('@playwright/test');
const { CHAT_URL, watchConsole, checkLayout } = require('./helpers');

test('[real] 나만의 노트: 빈 화면 → 노트 쓰기·자동 저장·다시 열어도 남음·지우기', async ({ page }, testInfo) => {
  const con = watchConsole(page);
  await page.goto('/atelier.html#/notes');
  await expect(page.getByRole('heading', { name: '나만의 노트', level: 1 })).toBeVisible();
  await expect(page.locator('.nav a[data-tab="notes"]')).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('.empty-box')).toContainText('아직 노트가 없어요');
  await page.evaluate(() => MyNotes.add('어텐션', '어텐션'));
  await page.goto('/atelier.html#/notes/' + encodeURIComponent('어텐션'));
  await page.reload();
  await expect(page.locator('.mn-title')).toHaveText('어텐션');
  await page.locator('.mn-text').fill('내 말로: 중요한 곳에 더 집중하는 방법');
  await expect(page.locator('.mn-status')).toContainText('저장됨');
  await page.reload();
  await expect(page.locator('.mn-text')).toHaveValue('내 말로: 중요한 곳에 더 집중하는 방법');
  await expect(page.locator('.mn-list a[aria-current="true"] .mn-snip')).toContainText('중요한 곳에');
  await checkLayout(page, testInfo, 'notes');
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: '노트 지우기' }).click();
  await expect(page.locator('.empty-box')).toContainText('아직 노트가 없어요');
  expect(con.errors).toEqual([]);
});

test('[real] 마스코트 말풍선: 누르면 바로 가기, Esc로 닫힘, 지금 화면은 빠짐', async ({ page }) => {
  await page.goto('/atelier.html?chat=' + encodeURIComponent(CHAT_URL) + '#/chat');
  const hit = page.locator('.ask-welcome .desk-art .art-hit');
  await expect(hit).toBeVisible();
  await hit.click();
  const bubble = page.getByRole('dialog', { name: 'THYNK 바로 가기' });
  await expect(bubble).toBeVisible();
  await expect(hit).toHaveAttribute('aria-expanded', 'true');
  await expect(bubble.locator('a[href="#/chat"]')).toHaveCount(0);
  await expect(bubble.locator('a[href="#/notes"]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(bubble).toHaveCount(0);
  await hit.click();
  await page.getByRole('dialog').locator('a[href="#/notes"]').click();
  await expect(page.getByRole('heading', { name: '나만의 노트', level: 1 })).toBeVisible();
});
