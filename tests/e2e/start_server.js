// Playwright가 띄우는 시험용 서버. 실제 서버 코드를 그대로 쓰고, 데이터만 매번 새로 만든 빈 임시 폴더에 둔다.
//   node tests/e2e/start_server.js app  <python> <port>
//   node tests/e2e/start_server.js chat <python> <port> <app_port>
// 개인 인박스(~/.claude/concept-inbox.jsonl)와 DB는 열지 않는다. LLM·SearXNG는 끈다(같은 입력이면 같은 화면).
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const [kind, py, port, appPort] = process.argv.slice(2);

let args;
let tmp = null;
if (kind === 'app') {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'concept-chart-e2e-'));
  args = ['kit/serve.py', '--web', 'app', '--port', port, '--db', path.join(tmp, 'e2e.sqlite'),
    '--inbox', path.join(tmp, 'inbox.jsonl'), '--searx', 'off', '--llm', 'off'];
} else if (kind === 'chat') {
  args = ['chat/chat_server.py', '--port', port, '--api', `http://127.0.0.1:${appPort}`, '--llm', 'off'];
} else {
  console.error('사용법: start_server.js app|chat <python> <port> [app_port]');
  process.exit(2);
}

const child = spawn(py, args, { cwd: ROOT, stdio: 'inherit', env: { ...process.env, PYTHONUTF8: '1' } });
const cleanup = () => { if (tmp) try { fs.rmSync(tmp, { recursive: true, force: true }); } catch { /* 서버가 아직 파일을 잡고 있으면 OS 임시 폴더에 남는다 */ } };
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { child.kill(); });
child.on('exit', (code) => { cleanup(); process.exit(code ?? 0); });
