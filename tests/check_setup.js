// 설정 시트(04) 자동 점검: 한 줄 설치 명령 생성, 옵션 반영, 탭 렌더, 설치 파일 동일성
// 사용: node tests/check_setup.js [sim/out/index.html]   (npm test 에 포함)
const fs = require('fs');
const os = require('os');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');
const { TextEncoder } = require('util');
const ROOT = path.join(__dirname, '..');
const html = fs.readFileSync(process.argv[2] || path.join(ROOT, 'sim', 'out', 'index.html'), 'utf8');
const vc = new VirtualConsole(); const errors = [];
vc.on('jsdomError', e => errors.push(String(e && (e.stack || e.message || e))));
const dom = new JSDOM(html, { runScripts: 'dangerously', virtualConsole: vc, pretendToBeVisual: true, url: 'https://example.org/',
  beforeParse(w) { w.TextEncoder = TextEncoder; try { Object.defineProperty(w, 'crypto', { value: require('crypto').webcrypto }); } catch (e) {} } });
const w = dom.window, d = w.document;
setTimeout(() => {
  const S = w.__conceptSetup; const out = { errors };
  out.codeboxes = [...d.querySelectorAll('.codebox .cb-h b')].map(b => b.textContent);
  out.tabs = [...d.querySelectorAll('#su-tabs button')].map(b => b.textContent);
  out.kickers = [...d.querySelectorAll('.kicker')].map(k => k.textContent.trim().slice(0, 14));
  out.nav = [...d.querySelectorAll('nav.toc a')].map(a => a.textContent);
  // 기본 (Windows, 전역)
  out.win1 = S.oneliner('win').slice(0, 60) + ' … ' + S.oneliner('win').slice(-60);
  out.win1len = S.oneliner('win').length;
  // 한 줄 설치 명령 안의 설치기 = kit/install_concept_hook.py 와 바이트 단위로 같은가
  const b64 = (S.oneliner('nix').match(/b64decode\('([A-Za-z0-9+/=]+)'\)/) || [])[1] || '';
  const kitSrc = fs.readFileSync(path.join(ROOT, 'kit', 'install_concept_hook.py'));
  out.installerSameAsKit = Buffer.from(b64, 'base64').equals(kitSrc);
  fs.writeFileSync(path.join(os.tmpdir(), 'nix_install.sh'), S.oneliner('nix'));
  fs.writeFileSync(path.join(os.tmpdir(), 'nix_test.sh'), S.oneliner('nix', '--test'));
  // 옵션 바꿔 보기: 프로젝트 범위 + subagent + 동기 + 마스킹 끔
  S.O.scope = 'project'; S.O.proj = 'C:\\Users\\LG\\atlas\\'; S.O.evSub = true; S.O.async = false; S.O.mask = false; S.O.inbox = 'D:\\data\\inbox.jsonl';
  out.args = S.args();
  S.O.src = 'url'; S.O.url = 'https://gist.githubusercontent.com/u/abc/raw/install_concept_hook.py';
  out.urlWin = S.oneliner('win'); out.urlNix = S.oneliner('nix', '--test');
  S.O.url = 'https://evil.example/"; rm -rf ~'; out.badUrl = S.oneliner('nix').slice(0, 40);
  const sj = S.settingsJson(); out.settingsWhere = sj.where; out.settingsParsed = Object.keys(JSON.parse(sj.json).hooks);
  out.hookHead = S.hookCode().split('\n').slice(4, 7).join(' | ');
  // 탭 클릭 렌더
  for (const i of [1, 2, 3, 4]) { d.querySelectorAll('#su-tabs button')[i].click(); out['pane' + i] = [...d.querySelectorAll('#su-pane .codebox .cb-h b')].map(b => b.textContent).join(', '); }
  out.saved = d.querySelector('#su-saved').textContent;
  console.log(JSON.stringify(out, null, 1));
  const ok = errors.length === 0 && out.installerSameAsKit && out.tabs.length === 5;
  console.log(ok ? 'check_setup: 정상' : 'check_setup: 실패');
  process.exit(ok ? 0 : 1);
}, 800);
