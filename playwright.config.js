// 브라우저 화면 점검 (Playwright). 실행: npm run test:e2e  ·  결과 보기: npx playwright show-report
// 서버는 실제 코드(kit/serve.py, chat/chat_server.py)를 쓰되, 개인 데이터(~/.claude)가 아닌 빈 임시 DB로 띄운다 (tests/e2e/start_server.js).
// 가짜 데이터는 tests/e2e/mock/ 에만 있고, 그 데이터를 쓰는 시험은 이름이 [mock]으로 시작한다.
// python dev.py check(CI)에는 들어가지 않는다: 브라우저 설치(npx playwright install chromium)가 필요한 선택 점검이다.
const { defineConfig, devices } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const APP_PORT = Number(process.env.E2E_APP_PORT || 8790);    // 평소 쓰는 8765·8766과 겹치지 않게
const CHAT_PORT = Number(process.env.E2E_CHAT_PORT || 8791);

// 서버를 돌릴 파이썬: PYTHON > 켜 둔 가상환경 > .venv > 켜 둔 conda 환경 > PATH (kiwipiepy가 있어야 한다, SETUP.md)
function python() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const win = process.platform === 'win32';
  const inEnv = (dir) => (dir ? path.join(dir, win ? 'Scripts/python.exe' : 'bin/python') : null);
  const conda = process.env.CONDA_PREFIX ? path.join(process.env.CONDA_PREFIX, win ? 'python.exe' : 'bin/python') : null;
  for (const p of [inEnv(process.env.VIRTUAL_ENV), inEnv(path.join(__dirname, '.venv')), conda]) if (p && fs.existsSync(p)) return p;
  return win ? 'python' : 'python3';
}
const PY = python();
const q = (s) => `"${s}"`;

module.exports = defineConfig({
  testDir: 'tests/e2e',
  outputDir: 'tests/e2e/.results',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  // 서버(ThreadingHTTPServer)의 연결 대기열이 기본 5개라, 동시 접속이 많으면 정적 파일(글꼴 조각) 요청이 ERR_CONNECTION_REFUSED로 거절된다(실측).
  // 서버는 바꾸지 않고 시험 쪽에서 줄인다: 기본 작업자 1개(11-12 작업자 2개로 atelier 시험 4건 거절 → 1개로 0건). 빠르게 돌리려면 E2E_WORKERS=2
  workers: Number(process.env.E2E_WORKERS || 1),
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'tests/e2e/.report' }]],
  use: {
    baseURL: `http://127.0.0.1:${APP_PORT}`,
    locale: 'ko-KR',
    timezoneId: 'Asia/Seoul',
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'tablet', use: { ...devices['Desktop Chrome'], viewport: { width: 768, height: 1024 }, hasTouch: true } },
    { name: 'mobile', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 } },
  ],
  webServer: [
    {
      command: `node tests/e2e/start_server.js app ${q(PY)} ${APP_PORT}`,
      url: `http://127.0.0.1:${APP_PORT}/api/health`,
      reuseExistingServer: false,             // 켜 둔 실제 서버(개인 데이터)에 붙지 않는다
      timeout: 60_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      command: `node tests/e2e/start_server.js chat ${q(PY)} ${CHAT_PORT} ${APP_PORT}`,
      url: `http://127.0.0.1:${CHAT_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
  ],
});
