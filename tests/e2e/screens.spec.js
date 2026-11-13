// 화면별 그리기 점검 (가짜 데이터): 주요 요소, 믿음 표시, 배치, 콘솔 오류, 캡처. 세 해상도(desktop·tablet·mobile) 모두에서 돈다.
const { test, expect } = require('@playwright/test');
const { mockApi, LONG_LABEL } = require('./mock/api_mock');
const { watchConsole, ready, checkLayout, shot } = require('./helpers');

const c = (id) => '#/c/' + encodeURIComponent(id);

const SCREENS = [
  { name: '01-today', hash: '#/', texts: ['오늘 볼 개념', '내 질문 2개에서 찾은 개념 4개', '파이썬 가상환경이랑 Docker', '기록이 남지 않은 대화', '이 질문에서 나온 개념 2개 더', '다시 볼 것', '근거 확인됨', '출처 문장', '출처 없음'] },
  { name: '02-today-more-open', hash: '#/', open: 'details.more', texts: ['이미지', '레이어'] },
  { name: '03-concept-ready', hash: c('가상환경'), texts: ['가상환경', '이 개념은', 'AI 요약 · 근거 확인됨 3/3', '근거 문장 보기', '출처 열기', '내 대화에서는', '내 질문: [테스트] 가상환경은 왜 써?', '빈칸에 들어갈 개념은?', '함께 나온 개념', '이해했어요', '다시 볼게요', '이 낱말이 공부할 개념인가요?', '다른 표기: 가상 환경, venv'] },
  { name: '04-concept-source-only', hash: c('docker'), texts: ['Docker', '출처 문장 그대로', '출처 열기', '내 판단: 공부할 개념', '판단 지우기'] },
  { name: '05-concept-pending', hash: c('컨테이너'), texts: ['믿을 만한 설명을 찾는 중이에요', '기록이 없어요'] },
  { name: '06-concept-wrong-sense', hash: c('이미지'), texts: ['내 대화와 다른 뜻이라 보여 주지 않아요'] },
  { name: '07-concept-none', hash: c('레이어'), texts: ['믿을 만한 출처에서 설명을 찾지 못했어요. 지어내지 않고 비워 둡니다.'] },
  { name: '08-concept-long-label', hash: c(LONG_LABEL), texts: [LONG_LABEL, '출처 문장 그대로'] },
  { name: '09-answers', hash: '#/answers', texts: ['AI 답변 읽기', '답변 추가', '최근 답변', 'Claude Code', '붙여넣기'] },
  { name: '10-answer-detail', hash: '#/a/a1', texts: ['AI 답변', '내 질문: [테스트] 파이썬 가상환경이랑', 'AI가 고른 원문 문장', '이 답변의 개념', '원문', '격리 범위'] },
  { name: '11-answer-no-summary', hash: '#/a/a2', texts: ['이 답변 요약하기', '공부할 개념을 찾지 못했어요.'] },
  { name: '12-all', hash: '#/all', texts: ['전체 개념 6개', '중요도 순서예요.', '숨긴 낱말 보기', '이해함'] },
  { name: '13-hidden', hash: '#/hidden', texts: ['숨긴 낱말 2개', '후보', '공부할 개념이에요', '← 전체 개념으로'] },
];

for (const s of SCREENS) {
  test(`[mock] ${s.name} 그리기·배치`, async ({ page }, testInfo) => {
    const con = watchConsole(page);
    const calls = await mockApi(page);
    await page.goto('/classic.html?static=1' + s.hash);
    await ready(page);
    if (s.open) await page.locator(s.open).first().locator('summary').click();
    for (const t of s.texts) await expect(page.locator('body'), `"${t}"`).toContainText(t);
    await expect(page.locator('#status')).toContainText('AI 요약 켜짐');
    await expect(page.locator('#status')).toContainText('준비 중 2건');
    await checkLayout(page, testInfo, s.name);
    await shot(page, testInfo, s.name);
    expect(con.errors, '콘솔 오류').toEqual([]);
    expect(calls.unknown, '계약에 없는 API 호출').toEqual([]);
  });
}

test('[mock] 오늘 공부: 다 끝냄 상태 (Completed)', async ({ page }, testInfo) => {
  await mockApi(page, { '/api/study/today': { project: null, groups: [], items: [], counts: { shown: 3, known: 3, left: 0, hidden: 0, questions: 0, extra: 0 } } });
  await page.goto('/classic.html?static=1#/');
  await ready(page);
  await expect(page.locator('#view')).toContainText('지금까지 나온 개념을 모두 이해했다고 표시했어요.');
  await checkLayout(page, testInfo, 'today-completed');
  await shot(page, testInfo, '14-today-completed');
});

test('[mock] 전체 개념: 찾기 결과 0개 (Empty)', async ({ page }, testInfo) => {
  await mockApi(page);
  await page.goto('/classic.html?static=1#/all');
  await ready(page);
  await page.getByRole('searchbox', { name: '개념 찾기' }).fill('없는낱말');
  await expect(page.locator('#view ul.list > li')).toHaveCount(0);
  await shot(page, testInfo, '15-all-search-empty');
});
