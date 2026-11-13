// Cognitive Atelier 시안(app/atelier.html) 점검.
// [real-copy]: 실제 DB의 '사본'으로 띄운 서버에서 실제 콘텐츠로 그려 본다. E2E_REAL_BASE(예: http://127.0.0.1:8792)가 있을 때만 돈다.
//   사본을 쓰는 까닭: 개념 노트를 열면 '열어 본 기록'이 DB에 남는다. 원본 데이터를 바꾸지 않는다. 캡처에는 내 대화가 들어가므로 git에 올리지 않는다(screenshots/는 .gitignore).
// [mock]: 실제 데이터에 없는 경우(뜻이 다름·준비 중·긴 영문 이름·200자 질문·긴 출처)만 시험용 가짜 데이터로 본다.
const { test, expect } = require('@playwright/test');
const { mockApi, base, T } = require('./mock/api_mock');
const { watchConsole, checkLayout, shot } = require('./helpers');

const REAL = process.env.E2E_REAL_BASE;
const ready = async (page) => { await expect(page.locator('#view h1').first()).toBeVisible(); await page.evaluate(() => document.fonts.ready); };

test.describe('[real-copy] 실제 콘텐츠', () => {
  test.skip(!REAL, 'E2E_REAL_BASE가 없음 (실제 DB 사본 서버)');
  const CONCEPTS = ['ram', '데이터베이스', '일관성', 'relu', '랭크', '개념'];   // 정의 최장 · 쉬운 설명 최장 · 출처 URL 최장 · 쉬운 설명 최단 · 정의 최단 · 설명 없음 (11-11 사본에서 잰 값)
  const SCREENS = [['A1-today', '#/'], ...CONCEPTS.map((c) => ['A2-concept-' + c, '#/c/' + encodeURIComponent(c)]), ['A3-all', '#/all'], ['A4-answers', '#/answers'], ['A6-hidden', '#/hidden'], ['A7-chat', '#/chat']];
  for (const [name, hash] of SCREENS) {
    test(name, async ({ page }, testInfo) => {
      const con = watchConsole(page);
      await page.goto(REAL + '/atelier.html?static=1' + hash);
      await ready(page);
      expect(await page.evaluate(() => document.fonts.check('500 17px "Pretendard Variable"')), 'Pretendard(로컬) 읽힘').toBe(true);
      expect(await page.evaluate(() => getComputedStyle(document.querySelector('#view h1')).fontFamily), '제목도 고딕').toContain('Pretendard');
      await checkLayout(page, testInfo, name);
      await shot(page, testInfo, name);
      expect(con.errors, '콘솔 오류').toEqual([]);
    });
  }
  test('A8-answer-envelope: 실제 봉투 질문이 라벨+제목으로', async ({ page, request }, testInfo) => {
    const items = (await (await request.get(REAL + '/api/answers?k=200')).json()).items;
    let target = null;
    for (const a of items) { const d = await (await request.get(REAL + '/api/answers/' + encodeURIComponent(a.id))).json(); if ((d.question || '').trimStart().startsWith('<')) { target = d; break; } }
    test.skip(!target, '봉투 질문이 달린 답변이 없음');
    await page.goto(REAL + '/atelier.html?static=1#/a/' + encodeURIComponent(target.id));
    await ready(page);
    await expect(page.locator('.qview.page .qbadge')).toBeVisible();
    expect(await page.locator('h1.qtitle').textContent()).not.toMatch(/^\s*[“"]?</);   // 태그가 제목이 되지 않음
    await checkLayout(page, testInfo, 'A8-answer-envelope');
    await shot(page, testInfo, 'A8-answer-envelope');
  });
  test('A5-answer-longest', async ({ page, request }, testInfo) => {
    const items = (await (await request.get(REAL + '/api/answers?k=200')).json()).items;
    const longest = items.reduce((a, b) => (b.chars > a.chars ? b : a));
    await page.goto(REAL + '/atelier.html?static=1#/a/' + encodeURIComponent(longest.id));
    await ready(page);
    await checkLayout(page, testInfo, 'A5-answer-longest');
    await shot(page, testInfo, 'A5-answer-longest');
  });
});

test.describe('[mock] 시안 · 실제 데이터에 없는 경우', () => {
  const LATIN = 'sentence-transformers-cross-encoder';
  const LONG_Q = T + '이 질문은 대화 기록 API가 주는 최대 길이(200자)에 가깝게 일부러 길게 쓴 시험용 질문입니다. '.repeat(4);
  const edge = () => {
    const d = base();
    const docker = d['/api/study/concept/docker'];
    d['/api/study/concept/' + LATIN] = { ...docker, concept: LATIN, label: LATIN, forms: [LATIN, 'sentence transformers'],
      records: [{ ts: docker.records[0].ts, role: 'assistant', snippet: T + '임베딩 모델을 불러와 문장 벡터를 만듭니다.', question: LONG_Q.slice(0, 200) }],
      sources: [1, 2, 3].map((i) => ({ text: T + '출처 문장 ' + i + ' — 아주 긴 출처 주소가 줄을 넘치지 않는지 확인합니다.', url: 'https://ko.wikipedia.org/wiki/' + encodeURIComponent('아주_긴_문서_제목_' + i + '_(정보_기술_분야의_매우_긴_괄호_설명)') + '#' + encodeURIComponent('섹션_이름') })) };
    return d;
  };
  for (const [name, id] of [['M1-latin-long', LATIN], ['M2-wrong-sense', '이미지'], ['M3-pending', '컨테이너'], ['M4-ready', '가상환경'], ['M8-paragraphs', '여러문단'], ['M9-no-explanation', '레이어']]) {
    test(name, async ({ page }, testInfo) => {
      const con = watchConsole(page);
      const calls = await mockApi(page, edge());
      await page.goto('/atelier.html?static=1#/c/' + encodeURIComponent(id));
      await ready(page);
      await checkLayout(page, testInfo, name);
      await shot(page, testInfo, name);
      expect(con.errors, '콘솔 오류').toEqual([]);
      expect(calls.unknown).toEqual([]);
    });
  }
  // 11-13 고요한 공부: 한 번에 한 개념, 하루 3개, 끝 화면, 숫자·목록은 '자세히' 아래
  test('M10-today-flow: 한 장씩 넘기며 표시, 3개면 끝, 하나 더 보기', async ({ page }, testInfo) => {
    const con = watchConsole(page);
    const calls = await mockApi(page);
    await page.goto('/atelier.html?static=1#/');
    await ready(page);
    const card = page.locator('.flow-card');
    await expect(card.locator('.flow-name')).toHaveText('가상환경');                  // 안 열어 본 개념부터 (docker는 '열어 봄'이라 뒤로, 브랜치는 이미 이해함)
    await expect(card.locator('.say')).toHaveText('출처 문장으로 확인한 쉬운 설명이에요');   // 배지 대신 문장
    await expect(page.locator('.flow-count')).toHaveText('1번째 · 오늘 3개');
    await expect(page.locator('.today-more')).not.toHaveAttribute('open', '');        // 목록과 숫자는 접혀 있음
    await expect(page.locator('.entry').first()).toBeHidden();
    await checkLayout(page, testInfo, 'today-flow');
    await shot(page, testInfo, '50-today-flow');
    await card.getByRole('button', { name: '이해했어요' }).click();
    await expect(card.locator('.flow-name')).toHaveText('컨테이너');
    await expect(card.locator('.flow-line')).toHaveText('아직 믿을 만한 설명을 찾지 못했어요.');
    await expect(page.locator('.flow-dots i.on')).toHaveCount(1);
    await card.getByRole('button', { name: '다시 볼게요' }).click();
    await expect(card.locator('.flow-name')).toHaveText('계약');
    await card.getByRole('button', { name: '이해했어요' }).click();
    const end = page.locator('.flow-end');
    await expect(end).toContainText('오늘 공부는 여기까지예요.');
    await expect(end).toContainText('이해한 개념 2개 · 다시 볼 개념 1개');
    await shot(page, testInfo, '51-today-end');
    expect(calls.posts.map((p) => [decodeURIComponent(p.path), p.body.status])).toEqual([
      ['/api/study/concept/가상환경/progress', 'known'], ['/api/study/concept/컨테이너/progress', 'review'], ['/api/study/concept/계약/progress', 'known']]);
    await end.getByRole('button', { name: '하나 더 보기' }).click();
    await expect(card.locator('.flow-name')).toHaveText('Docker');
    await card.getByRole('link', { name: '노트 펼쳐 읽기 →' }).click();
    await expect(page.locator('h1.concept-title')).toHaveText('Docker');
    expect(con.errors).toEqual([]);
  });
  test('M30-today-resume: 오늘 이미 표시한 개념은 세고 건너뜀 · 자세히는 펼친 상태를 기억', async ({ page }) => {
    const d = base();
    d['/api/study/history'] = { items: [{ id: '가상환경', label: '가상환경', kind: 'marked', status: 'known', ts: new Date().toISOString() }] };
    await mockApi(page, d);
    await page.goto('/atelier.html?static=1#/');
    await ready(page);
    await expect(page.locator('.flow-name')).toHaveText('Docker');                    // 오늘 표시한 가상환경은 건너뛰고, 다시 볼 개념부터
    await expect(page.locator('.flow-count')).toHaveText('2번째 · 오늘 3개');
    await page.locator('.today-more > summary').click();
    await expect(page.locator('.entry').filter({ has: page.locator('.label', { hasText: /^컨테이너$/ }) })).toContainText('아직 믿을 만한 설명을 찾지 못했어요.');
    await page.reload();
    await ready(page);
    await expect(page.locator('.today-more')).toHaveAttribute('open', '');
  });
  test('M31-focus-read: 기본은 모두 또렷하게(0.9.3), 켜면 읽는 구획만 또렷하게, 이 브라우저에 기억', async ({ page }) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/c/docker');
    await ready(page);
    const parts = page.locator('.reading > section, .reading > .progress-actions');
    const toggle = page.getByRole('button', { name: '집중 읽기' });
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await expect.poll(() => parts.last().evaluate((e) => getComputedStyle(e).opacity)).toBe('1');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await parts.first().hover();
    await expect(parts.first()).toHaveClass(/here/);
    await expect.poll(() => parts.last().evaluate((e) => Number(getComputedStyle(e).opacity))).toBeLessThan(1);
    await parts.last().hover();
    await expect(parts.last()).toHaveClass(/here/);
    await page.reload();
    await ready(page);
    await expect(page.getByRole('button', { name: '집중 읽기' })).toHaveAttribute('aria-pressed', 'true');   // 이 브라우저에 기억
  });
  test('M34-journal: 개념 노트의 관련 개념은 별자리, 섹션 사이에 작은 별', async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/c/' + encodeURIComponent('가상환경'));   // 관련 개념 2개
    await ready(page);
    await expect(page.locator('.related-map path.star')).toHaveCount(3);   // 관련 개념 2 + 가운데 1
    const second = page.locator('.reading > section + section').first();
    expect(await second.evaluate((e) => getComputedStyle(e, '::before').content)).not.toBe('none');
    await shot(page, testInfo, '53-journal');
  });
  test('M33-back-title: 라이브러리에서 연 노트는 라이브러리로 돌아가고, 탭 이름이 화면을 따름', async ({ page }) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/all');
    await ready(page);
    await expect(page).toHaveTitle('전체 개념 · THYNK');
    await page.goto('/atelier.html?static=1#/c/docker');
    await ready(page);
    await expect(page).toHaveTitle('Docker · THYNK');
    await expect(page.getByRole('link', { name: '← 전체 개념' })).toHaveAttribute('href', '#/all');
    await page.getByRole('button', { name: '다시 볼게요' }).click();
    await expect(page).toHaveURL(/#\/all$/);
  });
  test('M32-topbar: 아래로 내리면 상단 바가 비키고, 위로 올리면 다시 나옴', async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/c/' + encodeURIComponent('여러문단'));   // 스크롤할 만큼 긴 노트
    await ready(page);
    const top = () => page.locator('.topbar').evaluate((e) => e.getBoundingClientRect().bottom);
    await page.mouse.wheel(0, 900);
    await expect.poll(top).toBeLessThanOrEqual(0);
    if (testInfo.project.name !== 'desktop') await expect(page.locator('.nav a[data-tab="today"]')).toBeInViewport({ ratio: 0.9 });   // 좁은 화면의 아래 메뉴 독은 그대로
    await page.mouse.wheel(0, -200);
    await expect.poll(top).toBeGreaterThan(40);
  });
  test('M11-library: 처음엔 둘러보기, 진도 거르기·빈 결과·풀기', async ({ page }) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/all');
    await ready(page);
    await expect(page.locator('h1.display')).toHaveText('전체 개념');
    await expect(page.locator('.lib-explore')).toBeVisible();          // 긴 목록 대신 검색·둘러보기
    await expect(page.locator('.lib-results')).toBeHidden();
    await page.locator('.seg.review').click();                          // 학습 상태 막대 → 그 상태만
    await expect(page.locator('.lib-results .lib-item')).toHaveCount(1);
    await expect(page.locator('.lib-chip', { hasText: '상태: 다시 볼 개념' })).toBeVisible();
    await page.getByRole('searchbox', { name: '개념 찾기' }).fill('없는낱말');
    await expect(page.getByText('찾는 개념이 없어요')).toBeVisible();
    await page.getByRole('button', { name: '거르기 모두 풀기' }).click();
    await expect(page.locator('.lib-results .lib-item')).toHaveCount(6);
  });
  test('M12-hidden: 후보 먼저, 되돌리기는 그 줄에서 결과 표시', async ({ page }) => {
    const calls = await mockApi(page);
    await page.goto('/atelier.html?static=1#/hidden');
    await ready(page);
    await expect(page.locator('.marker').first()).toContainText('먼저 볼 후보');
    await page.getByRole('button', { name: '폴더 — 공부할 개념으로 표시' }).click();
    await expect(page.getByRole('status').filter({ hasText: '공부할 개념으로 표시했어요' })).toBeVisible();
    expect(calls.posts).toEqual([{ path: '/api/study/concept/폴더/feedback', body: { verdict: 'concept' } }]);
  });
  test('M13-archive: 날짜 묶음·찾기·읽기 이동', async ({ page }) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/answers');
    await ready(page);
    await expect(page.locator('.arow')).toHaveCount(2);
    await page.getByRole('searchbox', { name: '답변 찾기' }).fill('요약이 아직');
    await expect(page.locator('.arow:visible')).toHaveCount(1);
    await page.locator('.arow:visible a', { hasText: '답변 보기' }).click();
    await expect(page.locator('#view h1')).toBeVisible();   // 질문이 없는 답변은 'AI 답변' 제목
  });
  test('M14-error: 서버 오류 → 다시 시도', async ({ page }) => {
    let fail = true;
    await mockApi(page, { '/api/study/today': () => (fail ? { status: 500, body: { error: '[테스트] 서버 오류' } } : { status: 200, body: base()['/api/study/today'] }) });
    await page.goto('/atelier.html?static=1#/');
    await expect(page.locator('h1')).toHaveText('불러오지 못했어요');
    fail = false;
    await page.getByRole('button', { name: '다시 시도' }).click();
    await expect(page.locator('h1.display')).toHaveText('오늘 공부');
  });
  test('M15-korean-ui: 화면 라벨에 장식용 영문 대문자 문구가 없음', async ({ page }) => {
    await mockApi(page);
    const found = {};
    for (const hash of ['#/', '#/c/' + encodeURIComponent('가상환경'), '#/answers', '#/a/a1', '#/all', '#/hidden', '#/chat']) {
      await page.goto('/atelier.html?static=1' + hash);
      await ready(page);
      // 사용자 데이터(개념명·답변 원문·출처·대화)는 원문 그대로라 빼고, 화면이 직접 쓴 라벨만 본다
      const labels = await page.evaluate(() => [...document.querySelectorAll('.kicker, .marker, .k, .aux-k, .nav, th, button, .btn, .link, .tag, .prog, .brand-sub, .meta')]
        .filter((e) => !e.closest('.md, .chips, .src-link, .rs-item, .lab, .entry .label'))
        .map((e) => e.textContent).join(' | '));
      const caps = labels.match(/\b[A-Z][A-Z’' ]{4,}\b/g) || [];
      if (caps.length) found[hash] = caps;
    }
    expect(found).toEqual({});
  });
  test('M16-alias: 출처 문장에 적힌 우리말 이름만 보여 줌', async ({ page }) => {
    const d = base();
    d['/api/study/concept/docker'].definition = '[테스트] 도커(영어: Docker)는 컨테이너 안에서 프로그램을 실행하는 도구이다.';
    await mockApi(page, d);
    await page.goto('/atelier.html?static=1#/c/docker');
    await ready(page);
    await expect(page.locator('.concept-alias')).toContainText('도커');
  });
  test('M17-envelope: 질문 봉투는 라벨+안쪽 제목, 원문은 그대로 보고 복사', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/');
    await ready(page);
    await page.locator('.today-more > summary').click();                                // 질문별 목록은 '자세히' 아래
    const q = page.locator('.group').filter({ hasText: '붙여 넣은 문서 제목' }).locator('.qview');
    await expect(q.locator('.qbadge')).toHaveText('붙여 넣은 글');
    await expect(q.locator('.qtitle')).toHaveText('[테스트] 붙여 넣은 문서 제목');       // 태그가 제목으로 보이지 않는다
    await q.locator('summary', { hasText: '원문 그대로 보기' }).click();
    await expect(q.locator('.raw-pre')).toContainText('<pasted_content id="t1">');        // 원문은 지우지 않는다
    await q.getByRole('button', { name: '원본 복사' }).click();
    await expect(q.getByRole('button', { name: '복사했어요 ✓' })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('</pasted_content id="t1">');
  });
  test('M18-document: 제목 단계·목차·JSON 카드·코드·표·HTML 미실행', async ({ page, context }, testInfo) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/a/a3');
    await ready(page);
    await expect(page.locator('h1.qtitle')).toHaveText('[테스트] 붙여 넣은 문서 제목');
    await expect(page.locator('.md h3')).toHaveCount(2);
    await expect(page.locator('.md h4')).toHaveCount(1);
    await expect(page.locator('.toc li')).toHaveCount(3);
    // JSON: 기본은 접힘, 요약은 실제 키에서
    const json = page.locator('details.blk.json').first();
    await expect(json).not.toHaveAttribute('open', '');
    await expect(json.locator('.blk-sum')).toHaveText('객체 · 항목 4개 (name, items, ok, none)');
    await json.locator('summary').click();
    await expect(json.locator('.j-key').first()).toHaveText('"name"');
    await json.getByRole('button', { name: '원본 복사' }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('{"name": "[테스트]", "items": [1, 2, 3], "ok": true, "none": null}');
    await expect(page.locator('details.blk.json')).toHaveCount(2);                          // 문단 전체가 JSON인 것도
    await expect(page.locator('.blk-label', { hasText: 'JSON처럼 보이는 글' })).toHaveCount(1);   // 깨진 JSON은 고치지 않고 원문
    // HTML은 실행하지 않고 코드로
    expect(await page.evaluate(() => window.HACKED)).toBeUndefined();
    await expect(page.locator('.md div[onclick], .md script')).toHaveCount(0);
    await expect(page.locator('figure.blk.code .blk-label', { hasText: 'HTML' })).toHaveCount(2);
    await expect(page.locator('figure.blk.code .blk-label', { hasText: 'Bash' })).toHaveCount(1);
    await expect(page.locator('.table-wrap table td').first()).toHaveText('가상환경');
    await expect(page.locator('.md a.ext').first()).toHaveAttribute('rel', /noopener/);
    await checkLayout(page, testInfo, 'M18-document');
    await shot(page, testInfo, 'M18-document');
  });
  test('M19-motion: 평소엔 페이지 전환 효과, 움직임 줄이기에선 없음 · 계속 도는 장식 없음', async ({ page }) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/');
    await ready(page);
    expect(await page.evaluate(() => document.getAnimations().filter((a) => a.effect.getComputedTiming().iterations === Infinity).length)).toBe(0);
    await page.goto('/atelier.html?static=1#/all');
    await ready(page);
    expect(await page.evaluate(() => getComputedStyle(document.getElementById('view')).animationName)).toBe('pageIn');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/atelier.html?static=1#/hidden');
    await ready(page);
    expect(await page.evaluate(() => getComputedStyle(document.getElementById('view')).animationName)).toBe('none');
  });
  test('M20-envelope-cut: 80자에서 잘린 여는 태그도 봉투로 (글은 지우지 않음)', async ({ page }) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/');
    await ready(page);
    const r = await page.evaluate(() => {
      const cut = Render.envelope('<cross-session-message from="uds:\\.\pipe\LOCAL\cc-msg-6163ce45da0dc58ad3b487468');
      const plain = Render.envelope('일반 질문 <b>굵게</b>');
      const q = Render.question('<agent-message from="x">', { full: '<agent-message from="x">\n[Subagent hand-back] 보고 첫 줄\n</agent-message>' });
      return { cut: cut && cut.label, plain, title: q.querySelector('.qtitle').textContent, raw: q.querySelector('.raw-pre').textContent };
    });
    expect(r.cut).toBe('다른 세션의 메시지');
    expect(r.plain).toBeNull();                         // 글 중간의 태그는 봉투가 아니다
    expect(r.title).toBe('보고 첫 줄');                  // 에이전트 고정 머리말만 뗀다
    expect(r.raw).toContain('[Subagent hand-back]');     // 원문은 그대로
  });
  test('M21-library-search: 이름·우리말 이름·설명 검색, 지우기', async ({ page }) => {
    const d = base();
    d['/api/study/concepts?view=show'].items.push({ ...d['/api/study/concepts?view=show'].items[0], id: 'wcag', label: 'WCAG', rank: 9, field: '정보·통신', line: '[테스트] 웹 콘텐츠 접근성 가이드라인(Web Content Accessibility Guidelines, WCAG)은 웹 접근성 지침이다.', line_kind: 'source' });
    await mockApi(page, d);
    await page.goto('/atelier.html?static=1#/all');
    await ready(page);
    const box = page.getByRole('searchbox', { name: '개념 찾기' });
    await box.fill('접근성');                                            // 약어를 몰라도 우리말 이름으로
    const first = page.locator('.lib-results .lib-item').first();
    await expect(first.locator('.lib-label')).toHaveText('WCAG');
    await expect(first.locator('.alias')).toHaveText('웹 콘텐츠 접근성 가이드라인');
    await expect(first.locator('.lib-found')).toHaveCount(0);            // 이름(우리말 이름)에서 찾은 것
    await box.fill('컨테이너');
    await expect(page.locator('.lib-results .lib-item').first().locator('.lib-label')).toHaveText('컨테이너');   // 이름에서 찾은 게 먼저
    await expect(page.locator('.lib-item', { hasText: 'Docker' }).locator('.lib-found')).toHaveText('설명에서 찾음');
    await expect(page.locator('.lib-sstatus')).toContainText('찾음');
    await page.getByRole('button', { name: '검색어 지우기' }).click();
    await expect(box).toHaveValue('');
    await expect(page.locator('.lib-explore')).toBeVisible();
  });
  test('M22-library-filters: 분야 카드·여러 거르기·정렬·설명 없는 개념·노트 이동', async ({ page }) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/all');
    await ready(page);
    await page.locator('.lib-tile', { hasText: '정보·통신' }).first().click();
    await expect(page.locator('.lib-chip', { hasText: '분야: 정보·통신' })).toBeVisible();
    const names = () => page.locator('.lib-results .lib-label').allTextContents();
    expect((await names()).length).toBe(4);
    await page.getByLabel('정렬').selectOption('name');
    const sortedNames = await names();
    expect(sortedNames).toEqual([...sortedNames].sort((a, b) => a.localeCompare(b, 'ko', { sensitivity: 'base' })));
    await page.locator('.lib-progbtns button', { hasText: '처음 공부' }).click();   // 거르기 두 개
    await expect(page.locator('.lib-chip')).toHaveCount(2);
    for (const p of await page.locator('.lib-results .lib-card').evaluateAll((els) => els.map((e) => e.className))) expect(p).toContain('new');
    await page.locator('.lib-chip', { hasText: '분야' }).click();             // 하나만 풀기
    await expect(page.locator('.lib-chip')).toHaveCount(1);
    await page.getByRole('button', { name: '← 둘러보기로' }).click();
    await page.locator('.lib-tile', { hasText: '아직 설명이 없는 개념' }).click();
    for (const t of await page.locator('.lib-results .lib-desc').allTextContents()) expect(t).toBe('아직 믿을 만한 설명을 찾지 못했어요.');
    await page.locator('.lib-results .lib-card').first().click();
    await expect(page.locator('h1.concept-title')).toBeVisible();
  });
  test('M23-library-paging-graph: 24개씩 · 몇 개 보는지 · 분야 관계 그래프', async ({ page }) => {
    const d = base();
    const tpl = d['/api/study/concepts?view=show'].items[0];
    d['/api/study/concepts?view=show'].items = Array.from({ length: 60 }, (_, i) => ({ ...tpl, id: 'c' + i, label: '[테스트] 개념' + i, rank: i + 1, field: '정보·통신', origin: { ...tpl.origin, answer: 'ans' + (i % 5) } }));
    await mockApi(page, d);
    await page.goto('/atelier.html?static=1#/all');
    await ready(page);
    await page.getByRole('button', { name: '전체 60개 목록 보기' }).click();
    await expect(page.locator('.lib-count')).toHaveText('60개 중 24개를 보고 있어요');
    await page.getByRole('button', { name: /24개 더 보기/ }).click();
    await expect(page.locator('.lib-count')).toHaveText('60개 중 48개를 보고 있어요');
    await page.getByLabel('분야 고르기').selectOption('정보·통신');
    await page.locator('summary', { hasText: '이 분야의 개념 관계 보기' }).click();
    const nodes = page.locator('.lib-graph .n');
    await expect(nodes).toHaveCount(36);                                   // 중요한 순 36개까지만
    await nodes.first().click();
    await expect(page.locator('.lib-graph .n.mate')).toHaveCount(7);      // 그린 36개 중 ans0 = 0,5,…,35번 8개 → 자기 빼고 7개 (실제 관계만)
    await expect(page.locator('.lib-pick a', { hasText: '개념 노트 열기' })).toBeVisible();
  });
  // 1차 범위(11-12). 날짜는 지금 시각 기준으로 만든다 (다시 나온 개념은 '최근 14일' 규칙이라 고정 날짜면 시간이 지나 깨진다)
  const daysAgo = (n, hh = 10) => { const d = new Date(); d.setDate(d.getDate() - n); d.setHours(hh, 0, 0, 0); return d.toISOString(); };
  const withResurfaced = () => {
    const d = base();
    const show = d['/api/study/concepts?view=show'].items;
    show[0] = { ...show[0], sessions: 3, origin: { ...show[0].origin, ts: daysAgo(5) }, last_seen: daysAgo(1) };      // 가상환경: 5일 전 처음 → 1일 전 다시 = 4일 만에
    show[2] = { ...show[2], sessions: 1, origin: { ...show[2].origin, ts: daysAgo(5) }, last_seen: daysAgo(1) };      // 컨테이너: 대화 1개뿐 → 아님
    show[1] = { ...show[1], sessions: 4, origin: { ...show[1].origin, ts: daysAgo(40) }, last_seen: daysAgo(20) };    // Docker: 다시 나왔지만 14일보다 오래 → 아님
    return d;
  };
  test('M24-welcome: 기록이 하나도 없으면 서비스 소개(마스코트·3단계·시작 버튼)', async ({ page }, testInfo) => {
    const con = watchConsole(page);
    const d = base();
    d['/api/study/today'] = { project: null, counts: { shown: 0, known: 0, left: 0, hidden: 0, questions: 0, extra: 0 }, items: [], groups: [] };
    d['/api/study/concepts?view=show'] = { project: null, n_sessions: 0, total_words: 0, items: [] };
    d['/api/study/history'] = { items: [] };
    await mockApi(page, d);
    await page.goto('/atelier.html?static=1#/');
    await ready(page);
    await expect(page.locator('h1.display')).toHaveText('THYNK.');                        // 11-13 포스터 구도: 워드마크 · 약속 한 줄 · 세 걸음
    await expect(page.locator('.welcome-promise')).toHaveText('생각을 모으고, 지식을 키우다.');
    await expect(page.locator('.value-steps li')).toHaveCount(3);
    await expect.poll(() => page.locator('.welcome-hero img.mascot').evaluate((e) => e.complete && e.naturalWidth)).toBeGreaterThan(0);   // 마스코트 그림이 실제로 열림
    await shot(page, testInfo, '52-welcome');
    await expect(page.getByRole('link', { name: '답변 붙여넣기' })).toHaveAttribute('href', 'classic.html#/answers');
    await expect(page.locator('.rediscover, .growth')).toHaveCount(0);                                           // 없는 숫자를 보여 주지 않는다
    await checkLayout(page, testInfo, 'welcome');
    expect(con.errors).toEqual([]);
  });
  test('M25-rediscover: 다시 나온 개념은 규칙(대화 2개+ · 다른 날 · 최근 14일)에 맞는 것만, 쌓인 숫자는 실제 개수', async ({ page }, testInfo) => {
    await mockApi(page, withResurfaced());
    await page.goto('/atelier.html?static=1#/');
    await ready(page);
    await page.locator('.today-more > summary').click();                                // 쌓인 숫자·다시 나온 개념은 '자세히' 아래
    const cards = page.locator('.re-card');
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText('가상환경');
    await expect(cards.first()).toContainText('4일 만에 · 대화 3개에서 나옴');
    await expect(page.locator('.growth .g').first()).toContainText('6');                                        // 목록의 개념 6개
    await expect(page.locator('.growth')).toContainText('설명이 붙은 개념 · 67%');                                 // line이 있는 4개 / 6
    await cards.first().click();
    await expect(page.locator('h1.concept-title')).toHaveText('가상환경');
    await checkLayout(page, testInfo, 'rediscover-note');
  });
  test('M26-rediscover-empty: 다시 나온 개념이 없으면 이유를 말하는 빈 상태', async ({ page }) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/');
    await ready(page);
    await expect(page.locator('.re-card')).toHaveCount(0);
    await expect(page.locator('.rediscover')).toContainText('아직 다시 나온 개념이 없어요');
  });
  test('M27-timeline: 개념 노트의 시간은 기록에 있는 일만 (처음 만남·다시 나옴·열기 전 마지막 열어 봄)', async ({ page }) => {
    const d = base();
    d['/api/study/concept/docker'].records = [{ ts: '2026-11-11T09:00:00+09:00', role: 'assistant', snippet: '[테스트] 다시', question: null }, { ts: '2026-11-11T10:00:00+09:00', role: 'assistant', snippet: '[테스트] 또', question: null }];
    await mockApi(page, d);
    await page.goto('/atelier.html?static=1#/c/docker');
    await ready(page);
    const li = page.locator('.timeline li');
    await expect(li).toHaveCount(3);
    await expect(li.nth(0)).toContainText('처음 만남');
    await expect(li.nth(1)).toContainText('노트를 열어 봄');                                                       // history의 opened (11-10 10시)
    await expect(li.nth(2)).toContainText('다시 나옴');
    await expect(li.nth(2)).toContainText('대화 문장 2개');
    await expect(page.locator('.timeline')).not.toContainText('진도 표시');                                       // marked 기록이 없으니 없다
    await page.goto('/atelier.html?static=1#/c/' + encodeURIComponent('계약'));                                  // 처음 만난 자리·대화 문장 기록이 없고 last_seen만 있는 개념
    await ready(page);
    await expect(page.locator('.timeline li')).toHaveCount(1);
    await expect(page.locator('.timeline li')).toContainText('가장 최근에 나옴');
    await expect(page.locator('.timeline')).not.toContainText('처음 만남');
  });
  test('M28-archive-first: 답변마다 처음 만난 개념, 찾기에 개념 이름도', async ({ page }) => {
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/answers');
    await ready(page);
    const row = page.locator('.arow', { hasText: '가상환경은 파이썬 패키지를' });
    await expect(row.locator('.afirst .k')).toHaveText('처음 만난 개념 5');                                        // origin.answer = a1 인 개념 5개
    await expect(row.locator('.afirst a')).toHaveCount(4);
    await expect(row.locator('.afirst')).toContainText('외 1개');
    await expect(page.locator('.arow', { hasText: '요약이 아직 없는' }).locator('.afirst')).toHaveCount(0);
    await page.getByRole('searchbox', { name: '답변 찾기' }).fill('브랜치');                                       // 미리보기엔 없고 개념 이름에만 있는 낱말
    await expect(page.locator('.arow:visible')).toHaveCount(1);
  });
  test('M29-library-resurfaced: 라이브러리의 다시 나온 개념 거르기 · 주소로 바로 열기', async ({ page }) => {
    await mockApi(page, withResurfaced());
    await page.goto('/atelier.html?static=1#/all');
    await ready(page);
    await page.locator('.lib-tile', { hasText: '다시 나온 개념' }).click();
    await expect(page.locator('.lib-results .lib-item')).toHaveCount(1);
    await expect(page.locator('.lib-re')).toHaveText('4일 만에 다시');
    await expect(page.locator('.lib-chip', { hasText: '다시 나온 개념만' })).toBeVisible();
    await page.locator('.lib-chip', { hasText: '다시 나온 개념만' }).click();
    await expect(page.locator('.lib-chip')).toHaveCount(0);
    await page.goto('/atelier.html?static=1#/all/re');
    await ready(page);
    await expect(page.locator('.lib-results .lib-item')).toHaveCount(1);
    await expect(page.getByLabel('정렬')).toHaveValue('seen');
  });
  test('M7-dock: 맨 아래까지 내리면 마지막 버튼이 하단 독에 가려지지 않음', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === 'desktop', '독은 900px 이하에서만');
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/c/' + encodeURIComponent('가상환경'));
    await ready(page);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const hidden = await page.evaluate(() => {
      const dockTop = document.querySelector('.nav').getBoundingClientRect().top;
      return [...document.querySelectorAll('main a, main button, footer button')].filter((e) => { const r = e.getBoundingClientRect(); return r.height && r.top < window.innerHeight && r.bottom > dockTop; }).map((e) => e.textContent.trim());
    });
    expect(hidden).toEqual([]);
  });
  test('M5-motion-reduced: 빛이 멈추고 결은 그대로', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await mockApi(page);
    await page.goto('/atelier.html?static=1#/');
    await ready(page);
    const running = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === 'running' && a.effect.getComputedTiming().iterations === Infinity).length);
    expect(running).toBe(0);
    const grain = await page.evaluate(() => getComputedStyle(document.querySelector('.atmos'), '::after').backgroundImage);
    expect(grain).toContain('feTurbulence');
  });
  test('M6-background differs per screen', async ({ page }) => {
    await mockApi(page);
    const sig = {};
    for (const [k, hash] of [['today', '#/'], ['concept', '#/c/' + encodeURIComponent('가상환경')], ['all', '#/all'], ['answer', '#/a/a1'], ['chat', '#/chat']]) {
      await page.goto('/atelier.html?static=1' + hash);
      await ready(page);
      sig[k] = await page.evaluate(() => { const a = document.querySelector('.atmos'); const l = document.querySelector('.light'); const st = getComputedStyle(l); return [getComputedStyle(document.body).backgroundColor, getComputedStyle(a).backgroundImage.slice(0, 80), st.display, st.left, st.top, st.backgroundImage.slice(0, 60)].join('|'); });
    }
    expect(new Set(Object.values(sig)).size, JSON.stringify(sig, null, 1)).toBe(5);
  });
});
