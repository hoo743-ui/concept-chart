// 팝업: 기록 켜고 끄기, 연결·오늘 숫자, 이 탭에서 답변을 몇 개 찾는지 진단 (실험에서 화면 구조 추정이 맞는지 보는 곳)
const $ = (id) => document.getElementById(id);
const today = () => new Date().toISOString().slice(0, 10);

async function paint() {
  const { enabled = true, st, queue = [] } = await chrome.storage.local.get(['enabled', 'st', 'queue']);
  $('toggle').setAttribute('aria-pressed', String(enabled));
  $('toggle-t').textContent = enabled ? '기록 중' : '멈춤 · 누르면 다시 기록';
  const s = st && st.day === today() ? st : { added: 0, dup: 0 };
  $('added').textContent = s.added + '개';
  $('dup').textContent = s.dup + '개';
  $('queue').textContent = queue.length + '개';
  $('err').hidden = !s.lastError;
  $('err').textContent = s.lastError || '';
}
async function conn() {
  try {
    const r = await fetch('http://127.0.0.1:8765/api/health');
    if (!r.ok) throw new Error();
    $('conn').textContent = '연결됨'; $('conn').className = 'ok';
    chrome.runtime.sendMessage({ type: 'flush' }, paint);
  } catch { $('conn').textContent = '꺼져 있어요'; $('conn').className = 'bad'; }
}
async function diagnose() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https:\/\/claude\.ai\//.test(tab.url || '')) return;
  chrome.tabs.sendMessage(tab.id, { type: 'diagnose' }, (d) => {
    if (chrome.runtime.lastError || !d) { $('diag').textContent = '이 탭을 새로 고친 뒤 다시 열어 주세요.'; return; }
    $('diag').textContent = `답변 ${d.answers}개 (${d.answerSel || '못 찾음'})\n질문 ${d.questions}개 (${d.questionSel || '못 찾음'})\n쓰는 중 표시: ${d.streamingAttr ? '있음' : '없음'}\n대화: ${d.session || '없음'}`;
    $('all').disabled = !d.answers;
    $('all').onclick = () => chrome.tabs.sendMessage(tab.id, { type: 'send-all' }, (r) => { $('all').textContent = `${(r && r.n) || 0}개 보냄`; $('all').disabled = true; setTimeout(paint, 1500); });
  });
}
$('toggle').addEventListener('click', async () => {
  const { enabled = true } = await chrome.storage.local.get('enabled');
  await chrome.storage.local.set({ enabled: !enabled });
  paint();
});
paint(); conn(); diagnose();
