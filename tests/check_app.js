// 화면(app/) 자동 점검: 서버 없이 demo.json으로 네 화면을 그려 본다. 대화 글이 HTML로 실행되지 않는지도 본다.
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const APP = path.join(__dirname, '..', 'app');
const demo = JSON.parse(fs.readFileSync(path.join(APP, 'demo.json'), 'utf8'));
const html = fs.readFileSync(path.join(APP, 'index.html'), 'utf8').replace(/<script[^>]*><\/script>/g, '').replace(/<link[^>]*>/g, '');
let fails = 0;
const ok = (name, cond, info = '') => { console.log((cond ? '[OK]   ' : '[FAIL] ') + name + (info ? ' — ' + info : '')); if (!cond) fails += 1; };
const wait = () => new Promise((r) => setTimeout(r, 30));

(async () => {
  const dom = new JSDOM(html, { url: 'http://localhost/?demo=1', runScripts: 'outside-only' });
  const { window } = dom;
  const data = JSON.parse(JSON.stringify(demo));
  window.fetch = async (u) => ({ ok: true, json: async () => (String(u).includes('demo.json') ? data : {}) });
  window.scrollTo = () => {};
  window.eval(fs.readFileSync(path.join(APP, 'api.js'), 'utf8').replace('const API =', 'window.API ='));
  window.eval(fs.readFileSync(path.join(APP, 'app.js'), 'utf8'));
  const text = () => window.document.getElementById('view').textContent;
  const go = async (hash) => { window.location.hash = hash; window.dispatchEvent(new window.HashChangeEvent('hashchange')); await wait(); };

  await wait();
  ok('오늘 공부: 질문별 묶음', text().includes('브랜치랑 Docker를 같이 쓰는 법 알려줘') && text().includes('브랜치') && text().includes('Docker') && text().includes('내 질문 1개'));
  ok('오늘 공부: 설명 없음을 지어내지 않음', text().includes('믿을 만한 설명을 찾지 못했어요'));
  ok('데모 표시', window.document.getElementById('status').textContent.includes('데모'));

  await go('#/c/docker');
  ok('개념 노트: 근거가 없으면 비워 둠', text().includes('지어내지 않고 비워 둡니다'));
  await go('#/c/' + encodeURIComponent('브랜치'));
  ok('개념 노트: 출처 문장 표시와 이해 버튼', text().includes('출처 문장 그대로') && text().includes('이해했어요') && text().includes('내 질문'));

  data['/api/answers/demo1'].text = '## 제목\n\n**굵게** `코드`와 브랜치\n\n| 칸1 | 칸2 |\n|---|---|\n| 가 | 나 |\n\n- 목록\n\n<img src=x onerror="window.HACKED=1">';
  await go('#/a/demo1');
  const doc = window.document;
  ok('답변 읽기: 마크다운을 읽기 좋게', doc.querySelector('.md h3') && doc.querySelector('.md strong') && doc.querySelector('.md code') && doc.querySelector('.md table td') && doc.querySelector('.md li'));
  ok('답변 읽기: 개념을 노트로 연결', Boolean(doc.querySelector('.md mark a[href^="#/c/"]')));
  ok('답변 글의 HTML을 실행하지 않음', !doc.querySelector('.md img') && !window.HACKED);

  await go('#/answers');
  ok('답변 목록과 붙여넣기', text().includes('최근 답변') && Boolean(doc.querySelector('textarea')));
  await go('#/all');
  ok('전체 개념', text().includes('전체 개념 1개'));

  console.log(fails ? `check_app: 실패 ${fails}개` : 'check_app: 정상');
  process.exit(fails ? 1 : 0);
})();
