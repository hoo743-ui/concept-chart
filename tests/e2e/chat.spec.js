// 기록에 묻기 (11-13: 개념 차트 웹 app/atelier.html #/chat 안으로 합침). 답은 실제 chat_server.py가 빈 임시 DB의 개념 차트 서버를 읽어 만든다.
// LLM은 꺼서 낱말 규칙으로 답한다. 화면은 개념 차트 서버(APP)가, 답은 묻기 서버(CHAT_URL)가 낸다 → 서로 다른 포트(CORS).
const { test, expect } = require('@playwright/test');
const { CHAT_URL, watchConsole, checkLayout, shot } = require('./helpers');

const PAGE = '/atelier.html?chat=' + encodeURIComponent(CHAT_URL) + '#/chat';
const bot = (page) => page.locator('#ask-log .msg.bot:not(.waiting)');

test('[real] 기록에 묻기: 첫 화면, 예시 질문, 묻고 답 받기, 배치', async ({ page }, testInfo) => {
  const con = watchConsole(page);
  await page.goto(PAGE);
  await expect(page.getByRole('heading', { name: '기록에 묻기', level: 1 })).toBeVisible();
  await expect(page.locator('.nav a[data-tab="chat"]')).toHaveAttribute('aria-current', 'page');   // 한 웹: 메뉴 안의 화면
  await expect(page.locator('#ask-hello')).toHaveText('안녕하세요! 오늘은 어떤 개념을 함께 정리해 볼까요?');
  await expect(page.locator('.ask-how')).toContainText('낱말 규칙으로');          // LLM이 꺼져 있을 때
  const cards = page.locator('.ask-cards button');
  await expect(cards).toHaveCount(4);                                            // 서버가 주는 예시 질문 그대로
  await page.evaluate(() => document.fonts.ready);
  await checkLayout(page, testInfo, 'chat-start');
  await expect(page.locator('.ask-welcome .desk-art.ask-art')).toBeVisible();   // 브리프 B: 빈 화면은 아치 별자리 그림
  await shot(page, testInfo, '40-chat-start');

  await cards.first().click();
  await expect(page.locator('#ask-log .msg.me')).toHaveCount(1);
  await expect(bot(page)).toHaveCount(1);
  await expect(bot(page).first().locator('.ask-answer, .ask-state')).toBeVisible();
  await expect(page.locator('.ask-welcome')).toBeHidden();
  await expect(page.getByRole('button', { name: '새 대화' })).toBeVisible();
  await expect(bot(page).first().locator('.bot-name')).toHaveText('THYNK');   // 브리프 B: 대화가 시작되면 마스코트는 답의 작은 얼굴

  const box = page.getByPlaceholder('궁금한 개념이나 공부했던 내용을 물어보세요.');
  await box.fill('트랜스포머 내가 했던가?');
  await page.getByRole('button', { name: '묻기', exact: true }).click();
  await expect(bot(page)).toHaveCount(2);
  await expect(bot(page).nth(1)).not.toContainText('오류');
  // 답에 붙는 링크는 같은 창의 개념 노트(#/c/…) 또는 이 PC 주소로만
  for (const a of await page.locator('#ask-log a').all()) await expect(a).toHaveAttribute('href', /^(#\/c\/|http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/)/);
  await expect(page.locator('#ask-log')).not.toContainText('"intent"');        // JSON 원문·개발자 표현을 보여 주지 않는다
  await checkLayout(page, testInfo, 'chat-answered');
  await shot(page, testInfo, '41-chat-answered');
  expect(con.errors, '콘솔 오류').toEqual([]);
});

test('[real] 기록에 묻기: 빈 질문은 못 보냄, Enter 보내기 · Shift+Enter 줄바꿈', async ({ page }) => {
  await page.goto(PAGE);
  const send = page.getByRole('button', { name: '묻기', exact: true });
  await expect(send).toBeDisabled();
  const box = page.locator('#ask-q');
  await box.fill('   ');
  await expect(send).toBeDisabled();
  await box.press('Enter');
  await expect(page.locator('#ask-log .msg')).toHaveCount(0);
  await box.fill('내가 저번에');
  await box.press('Shift+Enter');
  await box.pressSequentially('공부했던 게 뭐였지?');
  await expect(box).toHaveValue('내가 저번에\n공부했던 게 뭐였지?');
  await expect(page.locator('#ask-log .msg')).toHaveCount(0);
  await box.press('Enter');
  await expect(page.locator('#ask-log .msg.me')).toHaveCount(1);
  await expect(box).toHaveValue('');
  await box.press('Enter');                                                     // 빈 칸에서 다시 Enter → 아무것도 안 감
  await expect(bot(page)).toHaveCount(1);
  await expect(page.locator('#ask-log .msg.me')).toHaveCount(1);
});

test('[real] 기록에 묻기: 다른 메뉴에 다녀와도, 새로 고쳐도 대화가 이어지고, 새 대화로 지우면 지난 질문만 남음', async ({ page }) => {
  await page.goto(PAGE);
  await page.locator('.ask-cards button').nth(2).click();
  await expect(bot(page)).toHaveCount(1);
  await page.locator('#ask-q').fill('적던 질문');
  await page.locator('.nav a[data-tab="all"]').click();
  await expect(page.locator('body')).toHaveAttribute('data-screen', 'all');
  await page.locator('.nav a[data-tab="chat"]').click();
  await expect(page.locator('#ask-log .msg.me')).toHaveCount(1);
  await expect(page.locator('#ask-q')).toHaveValue('적던 질문');                // 입력 중인 글도 그대로
  await page.reload();
  await expect(page.locator('#ask-log .msg.me')).toHaveCount(1);
  await expect(page.locator('.ask-welcome')).toBeHidden();
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: '새 대화' }).click();
  await expect(page.locator('#ask-log .msg')).toHaveCount(0);
  await expect(page.locator('.ask-welcome')).toBeVisible();
  await expect(page.locator('.ask-recent button')).toHaveCount(1);              // 이 브라우저에 남은 지난 질문
});

test('[real] 기록에 묻기: 서버에 닿지 못하면 오류와 다시 시도', async ({ page }) => {
  await page.goto(PAGE);
  await expect(page.locator('.ask-cards button')).toHaveCount(4);
  await page.route('**/api/ask', (r) => r.abort());
  await page.locator('#ask-q').fill('어떻게 학습하면 좋아?');
  await page.locator('#ask-q').press('Enter');
  const err = page.locator('#ask-log .ask-state.err');
  await expect(err).toBeVisible();
  await expect(err).toContainText('연결하지 못했어');
  await page.unroute('**/api/ask');
  await err.getByRole('button', { name: '다시 시도' }).click();
  await expect(page.locator('#ask-log .msg.bot .ask-answer').first()).toBeVisible();
});

test('[real] 기록에 묻기: 묻기 서버가 꺼져 있으면 켜는 방법을 보여 주고, 다른 메뉴는 그대로', async ({ page }) => {
  await page.goto('/atelier.html?chat=' + encodeURIComponent('http://127.0.0.1:9') + '#/chat');   // 아무도 듣지 않는 포트
  await expect(page.locator('.ask .ask-state.warn')).toContainText('묻기 서버가 꺼져 있어요');
  await expect(page.locator('.ask-cards button')).toHaveCount(0);
  await page.locator('.nav a[data-tab="today"]').click();
  await expect(page.locator('#view h1').first()).toBeVisible();
});

test('[real] 묻기 서버 주소로 열면 개념 차트 웹의 기록에 묻기로 넘어감', async ({ page }) => {
  await page.goto(CHAT_URL + '/');
  await expect(page).toHaveURL(/\/atelier\.html\?chat=.*#\/chat$/);
  await expect(page.getByRole('heading', { name: '기록에 묻기', level: 1 })).toBeVisible();
  await expect(page.locator('.ask-cards button')).toHaveCount(4);
});
