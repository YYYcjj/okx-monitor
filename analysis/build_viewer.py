#!/usr/bin/env python3
"""生成自包含 HTML 查看器 - 双击 okx_data/viewer.html 即可打开"""
import csv
import json
import os
from glob import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SCAN_DIR = os.path.join(PROJECT_ROOT, "okx_data", "scans")
BT_FILE = os.path.join(PROJECT_ROOT, "okx_data", "backtest_results.csv")
OUTPUT = os.path.join(PROJECT_ROOT, "okx_data", "viewer.html")

def load_scans():
    files = sorted(glob(os.path.join(SCAN_DIR, "*.csv")), reverse=True)
    all_data = {}
    for fp in files:
        fn = os.path.basename(fp)
        rows = []
        with open(fp, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                for k in ('adx_1h','adx_4h','adx_1d','srsi_1h','srsi_4h','srsi_1d'):
                    try: row[k] = None if row.get(k,'') == '' else round(float(row.get(k,'')),1)
                    except: row[k] = None
                for k in ('cci_1h','cci_4h','cci_1d'):
                    try: row[k] = None if row.get(k,'') == '' else round(float(row.get(k,'')),0)
                    except: row[k] = None
                for k in ('bbp_1h','bbp_4h','bbp_1d'):
                    try: row[k] = None if row.get(k,'') == '' else round(float(row.get(k,'')),2)
                    except: row[k] = None
                for k in ('dmi_bull','dmi_bear','sw_bull','sw_bear'):
                    try: row[k] = int(row[k])
                    except: pass
                for k in ('adx_bull','adx_bear'):
                    try: row[k] = round(float(row[k]),1)
                    except: pass
                rows.append(row)
        all_data[fn] = rows
    return all_data

def load_backtest():
    if not os.path.exists(BT_FILE):
        return []
    rows = []
    with open(BT_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            for k in ('entry','dmi_1h','dmi_4h','dmi_1d'):
                pass
            for k in ('srsi_1h','srsi_4h','srsi_1d','pct_4H','pct_12H','pct_24H'):
                try: row[k] = None if row.get(k,'') == '' else round(float(row.get(k,'')),2)
                except: row[k] = None
            for k in ('score',):
                try: row[k] = int(row[k])
                except: pass
            for k in ('win_4H','win_12H','win_24H'):
                v = row.get(k,'')
                row[k] = True if v == '1' else (False if v == '0' else None)
            rows.append(row)
    return rows

scan_data = load_scans()
bt_data = load_backtest()

# 加载组合胜率数据
PW_FILE = os.path.join(PROJECT_ROOT, "okx_data", "pairwise_winrate.json")
pw_data = {}
if os.path.exists(PW_FILE):
    with open(PW_FILE, 'r', encoding='utf-8') as f:
        pw_data = json.load(f)

HTML = f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OKX 数据查看器</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f6fa;color:#333;padding:20px}}
h1{{font-size:20px;margin-bottom:4px}}
.sub{{color:#999;font-size:12px;margin-bottom:12px}}
.tabs{{display:flex;gap:4px;margin-bottom:14px}}
.tab{{padding:8px 20px;border-radius:8px 8px 0 0;font-size:14px;cursor:pointer;background:#e0e0e0;color:#666;border:0;transition:all .15s}}
.tab.active{{background:#3498db;color:#fff}}
.file-list{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}}
.file-chip{{padding:5px 14px;border-radius:20px;font-size:12px;cursor:pointer;border:1px solid #ddd;background:#fff;transition:all .15s;white-space:nowrap}}
.file-chip:hover{{border-color:#3498db;color:#3498db}}
.file-chip.active{{background:#3498db;color:#fff;border-color:#3498db}}
.toolbar{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}}
.toolbar input,.toolbar select{{padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px}}
.toolbar input{{width:140px}}
.toolbar button{{padding:6px 14px;border:0;border-radius:6px;font-size:13px;cursor:pointer;background:#3498db;color:#fff;transition:opacity .15s}}
.toolbar button:hover{{opacity:.9}}
.toolbar button.reset{{background:#e0e0e0;color:#555}}
.toolbar button.refresh{{background:#27ae60}}
.table-wrap{{overflow-x:auto;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);max-height:70vh;overflow-y:auto}}
table{{width:100%;border-collapse:collapse;font-size:12px;background:#fff;min-width:700px}}
th{{background:#f0f1f5;padding:8px 5px;text-align:left;font-weight:600;color:#666;position:sticky;top:0;z-index:2;cursor:pointer;user-select:none;white-space:nowrap}}
th:hover{{background:#e4e5ea}}
th::after{{content:' ↕';font-size:10px;color:#bbb}}
th.asc::after{{content:' ↑';color:#3498db}}
th.desc::after{{content:' ↓';color:#3498db}}
td{{padding:6px 5px;border-top:1px solid #f0f0f0;white-space:nowrap}}
tr:hover{{background:#fafbfc!important}}
tr.alert{{background:#fff5f5}}
tr.win-4h{{background:#f0fff0}}
.bull{{color:#27ae60;font-weight:bold}}
.bear{{color:#e74c3c;font-weight:bold}}
.na{{color:#ccc}}
.stats{{margin-bottom:12px;font-size:12px;color:#666}}
.stats span{{margin-right:16px}}
.empty{{padding:60px;text-align:center;color:#ccc;font-size:15px}}
.score-high{{font-weight:bold}}
.badge{{display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;margin-left:3px;color:#fff}}
.badge-win{{background:#27ae60}}
.badge-lose{{background:#e74c3c}}
.badge-dmi{{background:#3498db}}
.badge-adx{{background:#8e44ad}}
.badge-sw{{background:#f39c12}}
.section{{display:none}}
.section.show{{display:block}}
@media(max-width:768px){{body{{padding:10px}}h1{{font-size:17px}}}}
/* Pairwise styles */
.pw-container{{display:flex;gap:14px;flex-wrap:wrap}}
.pw-left{{flex:1;min-width:280px;max-width:360px}}
.pw-right{{flex:2;min-width:400px}}
.pw-list{{max-height:60vh;overflow-y:auto;font-size:12px}}
.pw-item{{display:flex;align-items:center;padding:6px 8px;border-radius:6px;margin-bottom:3px;background:#fff;gap:6px}}
.pw-item:nth-child(odd){{background:#fafbfc}}
.pw-rank{{width:22px;text-align:center;font-weight:bold;color:#999;font-size:11px}}
.pw-tags{{display:flex;flex:1;gap:4px;overflow:hidden}}
.pw-tag{{padding:2px 7px;border-radius:4px;font-size:10px;font-weight:bold;white-space:nowrap;background:#e8f4fd;color:#2980b9}}
.pw-tag.dir{{background:#eafaf1;color:#27ae60}}
.pw-tag.val{{background:#fef9e7;color:#e67e22}}
.pw-bar-wrap{{width:80px;height:14px;background:#eee;border-radius:7px;overflow:hidden;flex-shrink:0}}
.pw-bar{{height:100%;border-radius:7px;transition:width .3s}}
.pw-num{{width:60px;text-align:right;font-weight:bold;font-size:12px;flex-shrink:0}}
.pw-heatmap{{overflow-x:auto;overflow-y:auto;max-height:55vh;font-size:10px;margin-top:8px}}
.pw-heatmap table{{border-collapse:collapse;width:auto}}
.pw-heatmap th{{position:sticky;top:0;z-index:3;background:#f0f1f5;font-size:9px;padding:2px 3px;max-width:50px;overflow:hidden;text-overflow:ellipsis;writing-mode:vertical-lr;text-orientation:mixed;height:80px;vertical-align:bottom;min-width:22px}}
.pw-heatmap td{{padding:0;text-align:center;cursor:pointer;min-width:22px;height:22px;font-size:9px}}
.pw-heatmap td:hover{{outline:2px solid #3498db;z-index:1;position:relative}}
.pw-heatmap .corner{{position:sticky;left:0;z-index:4;background:#f0f1f5;font-weight:bold;font-size:9px;text-align:left;padding:1px 4px;max-width:55px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.pw-legend{{display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:11px;color:#999}}
.pw-grad{{width:120px;height:10px;border-radius:5px;background:linear-gradient(to right,#27ae60,#f1c40f,#e74c3c)}}
.pw-grad-inv{{background:linear-gradient(to right,#e74c3c,#f1c40f,#27ae60)}}
</style>
</head>
<body>
<h1>📊 OKX 数据查看器</h1>
<p class="sub" id="sub">扫描数据 · 回测结果</p>

<div class="tabs">
  <button class="tab active" onclick="switchTab('scan')">📡 实时扫描</button>
  <button class="tab" onclick="switchTab('pairwise')">🔗 组合胜率</button>
  <button class="tab" onclick="switchTab('backtest')">🔬 回测结果</button>
</div>

<!-- Scan Section -->
<div class="section show" id="scanSection">
  <div class="file-list" id="scanFiles"></div>
  <div class="toolbar" id="scanToolbar">
    <input id="scSymbol" placeholder="币种筛选" oninput="deferFilter('scan')">
    <select id="scTf" onchange="deferFilter('scan')">
      <option value="">全部周期</option>
      <option value="1H">1H方向</option>
      <option value="4H">4H方向</option>
      <option value="1D">1D方向</option>
    </select>
    <select id="scDir" onchange="deferFilter('scan')"><option value="">全部</option><option value="多">最多</option><option value="空">最空</option></select>
    <input id="scScore" type="number" placeholder="评分≥" min="0" max="12" style="width:70px" oninput="deferFilter('scan')">
    <input id="scTime" type="datetime-local" step="60" onchange="deferFilter('scan')">
    <button class="reset" onclick="resetFilter('scan')">清除</button>
  </div>
  <div id="scanStats" class="stats"></div>
  <div class="table-wrap"><table id="scanTable"><thead id="scanHead"></thead><tbody id="scanBody"></tbody></table></div>
  <div class="empty" id="scanEmpty">暂无实时扫描数据</div>
</div>

<!-- Pairwise Section -->
<div class="section" id="pairwiseSection">
  <div id="pwContainer" class="pw-container">
    <div class="pw-left">
      <h3 style="font-size:14px;margin-bottom:8px">🏆 Top 组合 (24H胜率, ≥10样本)</h3>
      <div id="pwTopList" class="pw-list"></div>
    </div>
    <div class="pw-right">
      <h3 style="font-size:14px;margin-bottom:8px">📊 胜率热力图</h3>
      <div class="pw-legend">
        <span>0%</span><div class="pw-grad"></div><span>100%</span>
      </div>
      <div id="pwHeatmap" class="pw-heatmap"></div>
    </div>
  </div>
  <div class="empty" id="pwEmpty">暂无组合胜率数据，请运行 python analysis/pairwise_winrate.py</div>
</div>

<!-- Backtest Section -->
<div class="section" id="backtestSection">
  <div class="toolbar" id="btToolbar">
    <input id="btSymbol" placeholder="币种筛选" oninput="deferFilter('bt')">
    <select id="btStd" onchange="deferFilter('bt')">
      <option value="">全部标准</option>
      <option value="DMI纯分">DMI纯分</option>
      <option value="ADX加权">ADX加权</option>
      <option value="摆动点">摆动点</option>
    </select>
    <select id="btDir" onchange="deferFilter('bt')"><option value="">全部方向</option><option value="多">多</option><option value="空">空</option></select>
    <select id="btWin" onchange="deferFilter('bt')"><option value="">全部结果</option><option value="4H">4H胜</option><option value="12H">12H胜</option><option value="24H">24H胜</option></select>
    <input id="btScore" type="number" placeholder="评分≥" min="0" max="12" style="width:70px" oninput="deferFilter('bt')">
    <input id="btTime" type="datetime-local" step="60" onchange="deferFilter('bt')">
    <button class="reset" onclick="resetFilter('bt')">清除</button>
    <button class="refresh" onclick="location.reload()">🔄 刷新</button>
  </div>
  <div id="btStats" class="stats"></div>
  <div class="table-wrap"><table id="btTable"><thead id="btHead"></thead><tbody id="btBody"></tbody></table></div>
  <div class="empty" id="btEmpty">暂无回测数据，请运行 python backtest.py</div>
</div>

<script>
const SCAN_DATA = {json.dumps(scan_data, ensure_ascii=False)};
const BT_DATA = {json.dumps(bt_data, ensure_ascii=False)};
const PW_DATA = {json.dumps(pw_data, ensure_ascii=False)};

let scanRows=[], btRows=[], activeScanFile='', activeTab='scan';
let sortState={{scan:{{col:'',dir:1}},bt:{{col:'',dir:1}}}};
let filterTimers={{}};

// ── Tab switching ──
function switchTab(tab){{
  activeTab=tab;
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',false));
  document.querySelectorAll('.section').forEach(s=>s.classList.toggle('show',false));
  if(tab==='scan'){{document.querySelector('.tabs .tab:nth-child(1)').classList.add('active');document.getElementById('scanSection').classList.add('show');if(!activeScanFile)initScan();}}
  else if(tab==='pairwise'){{document.querySelector('.tabs .tab:nth-child(2)').classList.add('active');document.getElementById('pairwiseSection').classList.add('show');initPairwise();}}
  else{{document.querySelector('.tabs .tab:nth-child(3)').classList.add('active');document.getElementById('backtestSection').classList.add('show');if(!btRows.length)initBacktest();}}
}}

// ── Scan init ──
function initScan(){{
  const keys=Object.keys(SCAN_DATA).sort().reverse();
  const fl=document.getElementById('scanFiles');
  if(!keys.length){{fl.innerHTML='<span style="color:#999;font-size:13px">暂无数据</span>';return;}}
  fl.innerHTML=keys.map((f,i)=>`<span class="file-chip${{i===0?' active':''}}" onclick="loadScan('${{f}}')">${{f.replace('.csv','')}}</span>`).join('');
  loadScan(keys[0]);
}}

function loadScan(fn){{
  activeScanFile=fn;
  document.querySelectorAll('#scanFiles .file-chip').forEach(c=>c.classList.toggle('active',c.textContent.trim()===fn.replace('.csv','')));
  scanRows=SCAN_DATA[fn]||[];
  document.getElementById('sub').textContent='实时扫描 · '+fn.replace('.csv','')+' · '+scanRows.length+' 条';
  if(!scanRows.length){{document.getElementById('scanEmpty').style.display='block';document.getElementById('scanTable').style.display='none';return;}}
  document.getElementById('scanEmpty').style.display='none';
  document.getElementById('scanTable').style.display='';
  buildScanHeader(Object.keys(scanRows[0]));
  doFilter('scan');
}}

function buildScanHeader(cols){{
  const labels={{timestamp:'时间',symbol:'币种',dmi_1h:'DMI 1H',dmi_4h:'DMI 4H',dmi_1d:'DMI 1D',
    sw_1h:'SW 1H',sw_4h:'SW 4H',sw_1d:'SW 1D',adx_1h:'ADX 1H',adx_4h:'ADX 4H',adx_1d:'ADX 1D',
    srsi_1h:'SRSI 1H',srsi_4h:'SRSI 4H',srsi_1d:'SRSI 1D',
    ema_1h:'EMA 1H',ema_4h:'EMA 4H',ema_1d:'EMA 1D',
    cci_1h:'CCI 1H',cci_4h:'CCI 4H',cci_1d:'CCI 1D',
    bbp_1h:'BB% 1H',bbp_4h:'BB% 4H',bbp_1d:'BB% 1D',
    boll_1h:'BOLL 1H',boll_4h:'BOLL 4H',boll_1d:'BOLL 1D',
    dmi_bull:'DMI多',dmi_bear:'DMI空',adx_bull:'ADX多',adx_bear:'ADX空',sw_bull:'SW多',sw_bear:'SW空'}};
  document.getElementById('scanHead').innerHTML='<tr>'+cols.map(c=>`<th onclick="sortBy('scan','${{c}}')">${{labels[c]||c}}</th>`).join('')+'</tr>';
}}

// ── Backtest init ──
function initBacktest(){{
  btRows=BT_DATA;
  document.getElementById('sub').textContent='回测结果 · '+btRows.length+' 个信号';
  if(!btRows.length){{document.getElementById('btEmpty').style.display='block';document.getElementById('btTable').style.display='none';return;}}
  document.getElementById('btEmpty').style.display='none';
  document.getElementById('btTable').style.display='';
  buildBtHeader(['time_str','symbol','std','direction','score','dmi_1h','dmi_4h','dmi_1d','srsi_1h','srsi_4h','srsi_1d','win_4H','pct_4H','win_12H','pct_12H','win_24H','pct_24H','entry']);
  doFilter('bt');
}}

function buildBtHeader(cols){{
  const labels={{time_str:'时间',symbol:'币种',std:'标准',direction:'方向',score:'评分',entry:'入场价',
    dmi_1h:'DMI 1H',dmi_4h:'DMI 4H',dmi_1d:'DMI 1D',
    srsi_1h:'SRSI 1H',srsi_4h:'SRSI 4H',srsi_1d:'SRSI 1D',
    win_4H:'4H胜',pct_4H:'4H%',win_12H:'12H胜',pct_12H:'12H%',win_24H:'24H胜',pct_24H:'24H%'}};
  document.getElementById('btHead').innerHTML='<tr>'+cols.map(c=>`<th onclick="sortBy('bt','${{c}}')">${{labels[c]||c}}</th>`).join('')+'</tr>';
}}

// ── Sort ──
function sortBy(tab,col){{
  const ss=sortState[tab];
  if(ss.col===col)ss.dir*=-1;else{{ss.col=col;ss.dir=1;}}
  const prefix=tab==='scan'?'scan':'bt';
  document.querySelectorAll('#'+prefix+'Head th').forEach(th=>{{th.classList.remove('asc','desc');if(th.textContent.includes(col))th.classList.add(ss.dir===1?'asc':'desc');}});
  doFilter(tab);
}}

// ── Filter ──
function deferFilter(tab){{clearTimeout(filterTimers[tab]);filterTimers[tab]=setTimeout(()=>doFilter(tab),200);}}

function doFilter(tab){{
  const isScan=tab==='scan';
  let rows=[...(isScan?scanRows:btRows)];
  const prefix=isScan?'sc':'bt';
  const qSym=document.getElementById(prefix+'Symbol')?.value.trim().toUpperCase()||'';
  const qDir=document.getElementById(prefix+'Dir')?.value||'';
  const qScore=parseInt(document.getElementById(prefix+'Score')?.value)||0;
  const qTime=document.getElementById(prefix+'Time')?.value||'';

  if(qSym) rows=rows.filter(r=>r.symbol.toUpperCase().includes(qSym));
  if(qTime) rows=rows.filter(r=>(r.timestamp||r.time_str||'').startsWith(qTime.replace('T',' ')));
  if(qScore) rows=rows.filter(r=>{{
    if(isScan) return (r.dmi_bull>=qScore||r.dmi_bear>=qScore||r.sw_bull>=qScore||r.sw_bear>=qScore);
    return r.score>=qScore;
  }});
  if(qDir==='多') rows=rows.filter(r=>isScan?r.dmi_bull>r.dmi_bear:r.direction==='多');
  if(qDir==='空') rows=rows.filter(r=>isScan?r.dmi_bear>r.dmi_bull:r.direction==='空');

  // Backtest-only filters
  if(!isScan){{
    const qStd=document.getElementById('btStd')?.value||'';
    const qWin=document.getElementById('btWin')?.value||'';
    if(qStd) rows=rows.filter(r=>r.std===qStd);
    if(qWin) rows=rows.filter(r=>r['win_'+qWin]===true);
  }}

  // Sort
  const ss=sortState[tab];
  if(ss.col){{
    rows.sort((a,b)=>{{
      const va=a[ss.col], vb=b[ss.col];
      const na=isNaN(va)||va===null||va===undefined, nb=isNaN(vb)||vb===null||vb===undefined;
      if(na&&nb)return 0;if(na)return 1;if(nb)return -1;
      if(+va<+vb)return -ss.dir;if(+va>+vb)return ss.dir;return 0;
    }});
  }}else{{
    rows.sort((a,b)=>((b.timestamp||b.time_str||'').localeCompare(a.timestamp||a.time_str||'')));
  }}

  if(isScan) renderScan(rows);
  else renderBacktest(rows);
}}

// ── Render Scan ──
function renderScan(rows){{
  const cols=scanRows.length?Object.keys(scanRows[0]):[];
  const tbody=document.getElementById('scanBody');
  tbody.innerHTML=rows.map(r=>{{
    const alert=(r.dmi_bull>=6||r.dmi_bear>=6)?'alert':'';
    return '<tr class="'+alert+'">'+cols.map(c=>{{
      let v=r[c];
      if(v===null||v===undefined||v==='')return'<td><span class="na">-</span></td>';
      if(['dmi_1h','dmi_4h','dmi_1d','sw_1h','sw_4h','sw_1d','ema_1h','ema_4h','ema_1d','boll_1h','boll_4h','boll_1d'].includes(c))
        return`<td style="color:${{v==='多'?'#27ae60':v==='空'?'#e74c3c':'#999'}};font-weight:bold;font-size:11px">${{v}}</td>`;
      if(c==='symbol')return`<td style="font-weight:bold">${{(v||'').replace('-USDT-SWAP','').replace('-USDT','').replace('-SWAP','')}}</td>`;
      if(['dmi_bull','sw_bull'].includes(c))return`<td>${{v>=6?'<span class="score-high" style="color:#27ae60">'+v+'</span>':v}}</td>`;
      if(['dmi_bear','sw_bear'].includes(c))return`<td>${{v>=6?'<span class="score-high" style="color:#e74c3c">'+v+'</span>':v}}</td>`;
      if(['adx_bull','adx_bear'].includes(c)&&+v>=6)return`<td><span class="score-high" style="color:#27ae60">${{v}}</span></td>`;
      if(c.startsWith('cci_')){{
        const n=+v;
        if(n>100)return`<td style="color:#e74c3c;font-weight:bold">${{v}}</td>`;
        if(n<-100)return`<td style="color:#27ae60;font-weight:bold">${{v}}</td>`;
        if(n>0)return`<td style="color:#27ae60">${{v}}</td>`;
        return`<td style="color:#e74c3c">${{v}}</td>`;
      }}
      if(c.startsWith('bbp_')){{
        const n=+v;
        if(n>0.7)return`<td style="color:#e74c3c;font-weight:bold">${{v.toFixed(2)}}</td>`;
        if(n<0.3)return`<td style="color:#27ae60;font-weight:bold">${{v.toFixed(2)}}</td>`;
        return`<td>${{typeof v==='number'?v.toFixed(2):v}}</td>`;
      }}
      if(c.startsWith('srsi_')){{
        const n=+v;
        if(n>80)return`<td style="color:#e74c3c;font-weight:bold">${{v}}</td>`;
        if(n<20)return`<td style="color:#27ae60;font-weight:bold">${{v}}</td>`;
        return`<td>${{v}}</td>`;
      }}
      return`<td>${{v}}</td>`;
    }}).join('')+'</tr>';
  }}).join('');
  const dmiH=rows.filter(r=>r.dmi_bull>=6||r.dmi_bear>=6).length;
  const adxH=rows.filter(r=>r.adx_bull>=6||r.adx_bear>=6).length;
  const swH=rows.filter(r=>r.sw_bull>=6||r.sw_bear>=6).length;
  document.getElementById('scanStats').innerHTML=`<span>📋 ${{rows.length}}/${{scanRows.length}} 条</span><span>🟢 DMI预警${{dmiH}}</span><span>🔵 ADX预警${{adxH}}</span><span>🟡 SW预警${{swH}}</span>`;
}}

// ── Render Backtest ──
function renderBacktest(rows){{
  const btCols=['time_str','symbol','std','direction','score','dmi_1h','dmi_4h','dmi_1d','srsi_1h','srsi_4h','srsi_1d','win_4H','pct_4H','win_12H','pct_12H','win_24H','pct_24H'];
  const tbody=document.getElementById('btBody');
  tbody.innerHTML=rows.map(r=>{{
    let rowClass='';
    return '<tr class="'+rowClass+'">'+btCols.map(c=>{{
      let v=r[c];
      if(v===null||v===undefined||v==='')return'<td><span class="na">-</span></td>';
      if(c==='symbol')return`<td style="font-weight:bold">${{(v||'').replace('-USDT-SWAP','').replace('-USDT','').replace('-SWAP','')}}</td>`;
      if(c==='std'){{
        const cl=v==='DMI纯分'?'badge-dmi':v==='ADX加权'?'badge-adx':'badge-sw';
        return`<td><span class="badge ${{cl}}">${{v}}</span></td>`;
      }}
      if(c==='direction')return`<td style="color:${{v==='多'?'#27ae60':'#e74c3c'}};font-weight:bold">${{v}}</td>`;
      if(['dmi_1h','dmi_4h','dmi_1d'].includes(c))return`<td style="color:${{v==='多'?'#27ae60':v==='空'?'#e74c3c':'#999'}};font-weight:bold;font-size:11px">${{v}}</td>`;
      if(c.startsWith('win_')){{
        if(v===true)return`<td><span class="badge badge-win">✓</span></td>`;
        if(v===false)return`<td><span class="badge badge-lose">✗</span></td>`;
        return'<td><span class="na">-</span></td>';
      }}
      if(c.startsWith('pct_')){{
        const sign=v>=0?'+':'';
        const color=v>0?'#27ae60':v<0?'#e74c3c':'#999';
        return`<td style="color:${{color}};font-weight:bold">${{sign}}${{v.toFixed(1)}}%</td>`;
      }}
      if(c==='score')return`<td style="font-weight:bold;color:${{v>=6?'#e74c3c':'#333'}}">${{v}}</td>`;
      return`<td>${{v}}</td>`;
    }}).join('')+'</tr>';
  }}).join('');

  // Calculate stats
  const totals=rows.length;
  const stds={{'DMI纯分':rows.filter(r=>r.std==='DMI纯分').length,'ADX加权':rows.filter(r=>r.std==='ADX加权').length,'摆动点':rows.filter(r=>r.std==='摆动点').length}};
  const win24=rows.filter(r=>r.win_24H===true).length;
  const wr=totals>0?(win24/totals*100).toFixed(1):'0';
  let s='';
  s+=`<span>📋 信号 ${{totals}}/${{btRows.length}}</span>`;
  s+=`<span>🏆 24H胜 ${{win24}}(<b>${{wr}}%</b>)</span>`;
  s+=`<span>🔵DMI${{stds['DMI纯分']||0}}  🟣ADX${{stds['ADX加权']||0}}  🟡SW${{stds['摆动点']||0}}</span>`;
  document.getElementById('btStats').innerHTML=s;
}}

function resetFilter(tab){{
  const prefix=tab==='scan'?'sc':'bt';
  document.getElementById(prefix+'Symbol')&&(document.getElementById(prefix+'Symbol').value='');
  document.getElementById(prefix+'Tf')&&(document.getElementById(prefix+'Tf').value='');
  document.getElementById(prefix+'Dir')&&(document.getElementById(prefix+'Dir').value='');
  document.getElementById(prefix+'Score')&&(document.getElementById(prefix+'Score').value='');
  document.getElementById(prefix+'Time')&&(document.getElementById(prefix+'Time').value='');
  document.getElementById(prefix+'Win')&&(document.getElementById(prefix+'Win').value='');
  document.getElementById(prefix+'Std')&&(document.getElementById(prefix+'Std').value='');
  sortState[tab]={{col:'',dir:1}};
  doFilter(tab);
}}

// ── Pairwise Win Rate ──
function initPairwise(){{
  const empty=document.getElementById('pwEmpty');
  const cont=document.getElementById('pwContainer');
  if(!PW_DATA.top_pairs||!PW_DATA.top_pairs.length){{
    empty.style.display='block';cont.style.display='none';return;
  }}
  empty.style.display='none';cont.style.display='flex';
  renderTopPairs();
  renderHeatmap();
}}

function renderTopPairs(){{
  const list=document.getElementById('pwTopList');
  const colors_4h=['#2ecc71','#27ae60','#1e8449','#f39c12','#e67e22','#e74c3c'];
  let h='';
  PW_DATA.top_pairs.slice(0,25).forEach((p,i)=>{{
    const wr=p.wr||0;
    const cl=wr>=70?'#27ae60':wr>=50?'#2980b9':wr>=40?'#e67e22':'#e74c3c';
    const c1Dir=['DMI','EMA','SW','CCI_dir','BOLL'].some(x=>p.c1.includes(x));
    const c1Cls=c1Dir?'dir':'val';
    const c2Dir=['DMI','EMA','SW','CCI_dir','BOLL'].some(x=>p.c2.includes(x));
    const c2Cls=c2Dir?'dir':'val';
    h+=`<div class="pw-item">
      <span class="pw-rank">${{i+1}}</span>
      <div class="pw-tags">
        <span class="pw-tag ${{c1Cls}}">${{p.c1}}</span>
        <span style="color:#999;font-size:10px">+</span>
        <span class="pw-tag ${{c2Cls}}">${{p.c2}}</span>
      </div>
      <div class="pw-bar-wrap"><div class="pw-bar" style="width:${{wr}}%;background:${{cl}}"></div></div>
      <span class="pw-num" style="color:${{cl}}">${{wr}}%</span>
      <span style="font-size:10px;color:#999;width:50px;text-align:right">${{p.total}}个</span>
    </div>`;
  }});
  list.innerHTML=h;
}}

function renderHeatmap(){{
  const hm=document.getElementById('pwHeatmap');
  const conds=PW_DATA.conditions||[];
  const mat=PW_DATA.matrix||[];
  if(!conds.length){{hm.innerHTML='<span style=\"color:#999\">无数据</span>';return;}}
  
  // 只显示胜率差异较大的指标
  let h='<table><thead><tr><th class="corner">指标1\\指标2</th>';
  conds.forEach(c=>h+=`<th title="${{c}}">${{c.replace('_',' ')}}</th>`);
  h+='</tr></thead><tbody>';
  for(let i=0;i<conds.length;i++){{
    h+=`<tr><td class="corner">${{conds[i].replace('_',' ')}}</td>`;
    for(let j=0;j<conds.length;j++){{
      const cell=mat[i]&&mat[i][j]||{{wr:0,total:0}};
      const wr=cell.wr||0;
      const t=cell.total||0;
      if(i===j&&t<5){{h+='<td style="background:#f0f0f0;color:#ccc">-</td>';continue;}}
      const r=Math.round(wr/100*255);
      const g=Math.round((1-Math.abs(wr-50)/50)*200);
      const b=Math.round((100-wr)/100*255);
      const bg=wr>=50?`rgb(${{Math.round(255-r)}},${{Math.round(200+(55*(wr-50)/50))}},${{Math.round(200-r)}})`:
                     `rgb(${{Math.round(255-(100-wr)*2)}},${{Math.round(200-(50-wr)*3)}},${{Math.round(255-b)}})`;
      h+=`<td style="background:${{bg}};font-size:9px;color:${{wr>65||wr<35?'#fff':'#333'}}" title="${{conds[i]}}+${{conds[j]}}: ${{wr}}% (${{t}}个)">${{t>0?wr:''}}</td>`;
    }}
    h+='</tr>';
  }}
  h+='</tbody></table>';
  hm.innerHTML=h;
}}

// Init
if(Object.keys(SCAN_DATA).length)initScan();
if(BT_DATA.length)initBacktest();
switchTab('scan');
</script>
</body>
</html>'''

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write(HTML)

print(f"✅ 查看器已生成: {OUTPUT}")
print(f"   扫描数据: {len(scan_data)} 个日期文件, {sum(len(v) for v in scan_data.values())} 条")
print(f"   回测数据: {len(bt_data)} 个信号")
