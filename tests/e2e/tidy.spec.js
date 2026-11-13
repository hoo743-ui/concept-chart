// (0.9.3) 전체 개념 → 한 번에 정리하기: 여러 낱말을 골라 한꺼번에 '아니에요'로 (11-14 사용자 '일일이 고르기 불편')
const { test, expect } = require('@playwright/test');
const { mockApi } = require('./mock/api_mock');
const { watchConsole, ready, checkLayout } = require('./helpers');

test('[mock] 한 번에 정리하기: 둘 고르고 빼면 아니에요 두 번, 목록에서 사라짐', async ({ page }, testInfo) => {
  const con = watchConsole(page);
  const calls = await mockApi(page);
  await page.goto('/atelier.html?static=1#/all');
  await ready(page);
  await page.getByRole('button', { name: '한 번에 정리하기' }).first().click();
  const bar = page.locator('.tidy-bar');
  await expect(bar).toBeVisible();
  const go = bar.getByRole('button', { name: '공부할 개념에서 빼기' });
  await expect(go).toBeDisabled();
  const rows = page.locator('label.tidy');
  const n = await rows.count();
  expect(n).toBeGreaterThan(2);
  const names = [await rows.nth(0).locator('.lib-label').innerText(), await rows.nth(1).locator('.lib-label').innerText()];
  await rows.nth(0).click();
  await rows.nth(1).click();
  await expect(bar).toContainText('2개 골랐어요');
  await checkLayout(page, testInfo, 'tidy');
  await go.click();
  await expect(page.locator('label.tidy')).toHaveCount(n - 2);
  const posts = calls.posts.filter((p) => p.path.endsWith('/feedback'));
  expect(posts.map((p) => p.body.verdict)).toEqual(['not_concept', 'not_concept']);
  for (const nm of names) await expect(page.locator('label.tidy .lib-label').getByText(nm, { exact: true })).toHaveCount(0);
  await bar.getByRole('button', { name: '그만두기' }).click();
  await expect(bar).toBeHidden();
  await expect(page.locator('.lib-card').first()).toHaveAttribute('href', /#\/c\//);
  expect(con.errors).toEqual([]);
  expect(calls.unknown).toEqual([]);
});
