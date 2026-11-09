# -*- coding: utf-8 -*-
"""학습 실시간 화면. 표준 라이브러리만 쓰고 이 PC 안에서만 열린다. 파일을 읽기만 하고 학습에 영향을 주지 않는다.

    python experiments/live_view.py        # http://127.0.0.1:8770

보여 주는 것: 지금 도는 학습의 진행률·손실·학습 중인 쌍(공개 위키 데이터)과 예측값, 에폭별 그래프, RAM·GPU, 끝난 학습 표.
시험 세트와 내 대화 시트는 읽지 않는다.
"""
import csv
import ctypes
import json
import pathlib
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / "experiments" / "2026-11-09-b-finetune"
LIVE = ROOT / "data" / "live.json"
PORT = 8770
LOCAL = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
_gpu = (0.0, None)


class MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong), ("total_virt", ctypes.c_ulonglong), ("avail_virt", ctypes.c_ulonglong), ("avail_ext", ctypes.c_ulonglong)]


def ram():
    m = MemStatus()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"avail": round(m.avail_phys / 1e9, 1), "total": round(m.total_phys / 1e9, 1)}


def gpu():
    global _gpu
    if time.time() - _gpu[0] > 5:                       # nvidia-smi는 5초에 한 번만
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
            used, total, util, temp = [int(x) for x in out.split(",")]
            _gpu = (time.time(), {"used": used, "total": total, "util": util, "temp": temp})
        except (OSError, ValueError, subprocess.SubprocessError):
            _gpu = (time.time(), None)
    return _gpu[1]


def runs():
    out = []
    for log in RUNS.glob("*/log.csv"):
        try:
            with open(log, encoding="utf-8", newline="") as f:
                rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]
            metrics = log.parent / "metrics.json"
            val = json.loads(metrics.read_text(encoding="utf-8"))["val"] if metrics.exists() else None
        except (OSError, ValueError, KeyError):
            continue
        out.append({"name": log.parent.name, "mtime": log.stat().st_mtime, "epochs": rows, "done": val is not None,
                    "final": {k: val.get(k) for k in ("ap", "hard_fp", "cross_recall", "best_epoch")} if val else None})
    return sorted(out, key=lambda r: r["mtime"], reverse=True)


def state():
    live = None
    try:
        live = json.loads(LIVE.read_text(encoding="utf-8"))
        live["age"] = round(time.time() - live["time"], 1)
    except (OSError, ValueError, KeyError):
        pass
    return {"live": live, "ram": ram(), "gpu": gpu(), "runs": runs(), "now": time.strftime("%H:%M:%S")}


PAGE = r"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>학습 실시간 화면</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e2e1dc;--a:#2f6fdb;--b:#c8553d;--ok:#2d8a57}
@media (prefers-color-scheme:dark){:root{--bg:#171716;--card:#21211f;--ink:#ecece8;--mute:#a3a39c;--line:#35352f;--a:#7aa7f0;--b:#e58a74;--ok:#5cbd86}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,"Malgun Gothic",sans-serif}
main{max-width:1000px;margin:auto;padding:20px 16px 48px}h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:0 0 10px}.mute{color:var(--mute);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-top:14px;overflow-x:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}.big{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin:8px 0}.bar i{display:block;height:100%;background:var(--a)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--mute);font-weight:500;font-size:13px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}svg{width:100%;height:auto;display:block}.ok{color:var(--ok)}.no{color:var(--b)}
.legend span{margin-right:12px;font-size:13px}.legend i{display:inline-block;width:10px;height:3px;margin-right:4px;vertical-align:middle}
</style><main><h1>학습 실시간 화면</h1><div class="mute" id="when">불러오는 중</div>
<section class="card"><h2 id="title">지금 도는 학습</h2><div id="live"></div></section>
<section class="card"><h2>이 PC 자원</h2><div class="grid" id="res"></div></section>
<section class="card"><h2 id="chartTitle">에폭별 변화</h2><div class="charts"><div><div class="mute">손실 (검증 손실이 오르면 과적합 신호)</div><svg id="c1" viewBox="0 0 400 180"></svg><div class="legend" id="l1"></div></div><div><div class="mute">검증 AP (높을수록 좋음)</div><svg id="c2" viewBox="0 0 400 180"></svg></div></div></section>
<section class="card"><h2>학습 기록</h2><table id="tbl"></table></section></main>
<script>
const $=id=>document.getElementById(id);
function el(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
function stat(label,value,sub){const d=el('div');d.append(el('div',label,'mute'),el('div',value,'big'));if(sub)d.append(el('div',sub,'mute'));return d}
function chart(svg,series,fix){
 const css=getComputedStyle(document.documentElement),pts=series.flatMap(s=>s.v.map(p=>p[1]));svg.replaceChildren();if(!pts.length)return;
 let lo=fix?fix[0]:Math.min(...pts),hi=fix?fix[1]:Math.max(...pts);if(hi===lo)hi=lo+1;const n=Math.max(...series.flatMap(s=>s.v.map(p=>p[0])),2);
 const X=x=>34+(x-1)/(n-1)*356,Y=y=>165-(y-lo)/(hi-lo)*150,NS='http://www.w3.org/2000/svg';
 for(const v of [lo,(lo+hi)/2,hi]){const l=document.createElementNS(NS,'line');l.setAttribute('x1',34);l.setAttribute('x2',390);l.setAttribute('y1',Y(v));l.setAttribute('y2',Y(v));l.setAttribute('stroke',css.getPropertyValue('--line'));svg.append(l);
  const t=document.createElementNS(NS,'text');t.setAttribute('x',0);t.setAttribute('y',Y(v)+4);t.setAttribute('font-size',11);t.setAttribute('fill',css.getPropertyValue('--mute'));t.textContent=v.toFixed(2);svg.append(t)}
 for(const s of series){const c=css.getPropertyValue(s.c),p=document.createElementNS(NS,'polyline');p.setAttribute('fill','none');p.setAttribute('stroke',c);p.setAttribute('stroke-width',2);p.setAttribute('points',s.v.map(q=>X(q[0])+','+Y(q[1])).join(' '));svg.append(p);
  for(const q of s.v){const o=document.createElementNS(NS,'circle');o.setAttribute('cx',X(q[0]));o.setAttribute('cy',Y(q[1]));o.setAttribute('r',3);o.setAttribute('fill',c);svg.append(o)}}
}
function fmt(x,d=3){return x==null?'-':Number(x).toFixed(d)}
async function tick(){
 let d;try{d=await (await fetch('/data')).json()}catch(e){$('when').textContent='화면 서버에 연결할 수 없습니다';return}
 $('when').textContent='갱신 '+d.now+' (3초마다)';
 const L=d.live,box=$('live');box.replaceChildren();const on=L&&L.age<90;
 if(on){$('title').textContent='지금 도는 학습: '+L.run;
  const pct=100*L.step/L.total,g=el('div','', 'grid');g.append(stat('에폭',L.epoch+' / '+L.max_epochs),stat('이번 에폭 진행',pct.toFixed(0)+'%',L.step+' / '+L.total+' 묶음'),stat('최근 학습 손실',fmt(L.loss)));box.append(g);
  const b=el('div','', 'bar'),i=el('i');i.style.width=pct+'%';b.append(i);box.append(b);
  box.append(el('div','방금 학습한 쌍 (정답과 모델 예측)','mute'));const t=el('table'),h=el('tr');for(const x of ['표기 A','표기 B','정답','모델 예측','판단'])h.append(el('th',x));t.append(h);
  for(const r of L.sample){const tr=el('tr'),right=(r.p>=.5)===(r.label===1);tr.append(el('td',r.a),el('td',r.b),el('td',r.label?'같음':'다름'),el('td',fmt(r.p,2)),el('td',right?'맞음':'틀림',right?'ok':'no'));t.append(tr)}box.append(t)
 }else{$('title').textContent='지금 도는 학습';box.append(el('div','실시간 기록을 보내는 학습이 없습니다. 이 화면을 만들기 전에 시작한 학습은 아래 표에 에폭 단위로만 나타납니다.','mute'))}
 const res=$('res');res.replaceChildren();res.append(stat('사용 가능 RAM',d.ram.avail+' GB','전체 '+d.ram.total+' GB'));
 if(d.gpu)res.append(stat('GPU 메모리',(d.gpu.used/1024).toFixed(1)+' GB','전체 '+(d.gpu.total/1024).toFixed(1)+' GB'),stat('GPU 사용률',d.gpu.util+'%'),stat('GPU 온도',d.gpu.temp+'°C'));
 const cur=(on&&d.runs.find(r=>r.name===L.run))||d.runs[0];
 if(cur){$('chartTitle').textContent='에폭별 변화: '+cur.name;const v=k=>cur.epochs.map(e=>[e.epoch,e[k]]);
  chart($('c1'),[{v:v('train_loss'),c:'--a'},{v:v('val_loss'),c:'--b'}]);chart($('c2'),[{v:v('val_ap'),c:'--ok'}],[0.4,1]);
  const l=$('l1');l.replaceChildren();for(const [n,c] of [['학습 손실','--a'],['검증 손실','--b']]){const s=el('span'),i=el('i');i.style.background=`var(${c})`;s.append(i,n);l.append(s)}}
 const t=$('tbl');t.replaceChildren();const h=el('tr');for(const x of ['학습','상태','에폭','검증 AP','어려운 오답 오판','한영 재현'])h.append(el('th',x));t.append(h);
 for(const r of d.runs){const last=r.epochs[r.epochs.length-1]||{},f=r.final,tr=el('tr');tr.append(el('td',r.name),el('td',r.done?'완료':(on&&r.name===L.run?'학습 중':'중단 또는 진행')),el('td',r.epochs.length),el('td',fmt(f?f.ap:last.val_ap)),el('td',fmt(f?f.hard_fp:last.val_hard_fp)),el('td',fmt(f?f.cross_recall:last.val_cross_recall)));t.append(tr)}
}
tick();setInterval(tick,3000);
</script></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Host") not in LOCAL:
            self.send_error(403)
            return
        path = self.path.split("?")[0]
        if path == "/":
            body, ctype = PAGE.encode("utf-8"), "text/html; charset=utf-8"
        elif path == "/data":
            body, ctype = json.dumps(state(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"학습 실시간 화면: http://127.0.0.1:{PORT}  (끄려면 Ctrl+C)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
