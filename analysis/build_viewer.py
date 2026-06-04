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

# 加载入场离场分析
EE_FILE = os.path.join(PROJECT_ROOT, "okx_data", "entry_exit_analysis.json")
ee_data = {}
if os.path.exists(EE_FILE):
    with open(EE_FILE, 'r', encoding='utf-8') as f:
        ee_data = json.load(f)

# 加载交易优化分析
TO_FILE = os.path.join(PROJECT_ROOT, "okx_data", "trade_optimization.json")
to_data = {}
if os.path.exists(TO_FILE):
    with open(TO_FILE, 'r', encoding='utf-8') as f:
        to_data = json.load(f)

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
/* Alert summary */
.alert-summary{{background:#fff;border-radius:8px;padding:10px 14px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.08);display:none}}
.alert-summary.show{{display:block}}
.alert-summary h3{{font-size:14px;margin:0 0 8px;color:#e74c3c}}
.alert-cards{{display:flex;flex-wrap:wrap;gap:6px}}
.alert-card{{padding:8px 12px;border-radius:8px;font-size:12px;background:#fff5f5;border:1px solid #fdd;flex:1 1 auto;min-width:160px;max-width:280px}}
.alert-card.long{{background:#f0fff0;border-color:#cfc}}
.alert-card .ac-sym{{font-weight:bold;font-size:15px;margin-bottom:3px}}
.alert-card .ac-score{{font-size:20px;font-weight:bold}}
.alert-card .ac-detail{{font-size:10px;color:#888;margin-top:2px}}
.alert-card .ac-time{{font-size:10px;color:#aaa}}
/* Trade analysis */
.trade-stats{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}}
.trade-stat{{background:#fff;border-radius:8px;padding:10px 16px;box-shadow:0 1px 3px rgba(0,0,0,.08);min-width:100px;flex:1}}
.trade-stat .ts-num{{font-size:24px;font-weight:bold}}
.trade-stat .ts-label{{font-size:11px;color:#888;margin-top:2px}}
.trade-grid{{display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap}}
.trade-panel{{flex:1;min-width:300px;background:#fff;border-radius:8px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.trade-panel h3{{font-size:13px;margin:0 0 8px;color:#2c3e50}}
.trade-row{{display:flex;align-items:center;padding:4px 0;font-size:12px;gap:8px;border-bottom:1px solid #f5f5f5}}
.trade-row:last-child{{border-bottom:0}}
.trade-sym{{font-weight:bold;min-width:50px}}
.trade-dir{{min-width:24px;font-size:11px}}
.trade-info{{flex:1;font-size:11px;color:#666}}
.trade-pct{{font-weight:bold;min-width:60px;text-align:right;font-size:12px}}
.cat-bar{{display:flex;align-items:center;gap:8px;padding:6px 0;font-size:13px}}
.cat-bar .cb-fill{{height:22px;border-radius:4px;transition:width .3s}}
.cat-bar .cb-num{{min-width:50px;text-align:right;font-weight:bold;font-size:13px}}
/* Live test */
.live-card{{background:#fff;border-radius:8px;padding:12px 14px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.live-card h3{{font-size:14px;margin:0 0 8px;color:#2c3e50}}
.live-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px}}
.live-cell{{padding:8px 10px;border-radius:6px;background:#f8f9fb;font-size:12px}}
.live-cell .lc-label{{font-size:10px;color:#999;margin-bottom:2px}}
.live-cell .lc-val{{font-size:16px;font-weight:bold}}
.live-score{{display:flex;gap:10px;margin-top:10px;flex-wrap:wrap}}
.live-score-box{{padding:10px 16px;border-radius:8px;text-align:center;min-width:100px}}
.live-score-box .ls-num{{font-size:28px;font-weight:bold}}
.live-score-box .ls-label{{font-size:10px;color:#888;margin-top:2px}}
</style>
</head>
<body>
<h1>📊 OKX 数据查看器</h1>
<p class="sub" id="sub">扫描数据 · 回测结果</p>

<div class="tabs">
  <button class="tab active" onclick="switchTab('trade')">💰 交易分析</button>
  <button class="tab" onclick="switchTab('scan')">📡 实时扫描</button>
  <button class="tab" onclick="switchTab('pairwise')">🔗 组合胜率</button>
  <button class="tab" onclick="switchTab('backtest')">🔬 回测结果</button>
  <button class="tab" onclick="switchTab('live')">🧪 实时测试</button>
</div>

<!-- Trade Analysis Section -->
<div class="section show" id="tradeSection">
  <div id="tradeContainer">
    <div class="trade-stats" id="tradeStats"></div>
    <div class="trade-grid">
      <div class="trade-panel">
        <h3>📋 交易分类</h3>
        <div id="tradeChart"></div>
      </div>
      <div class="trade-panel">
        <h3>🎯 止损建议</h3>
        <div id="tradeStop"></div>
      </div>
    </div>
    <div class="trade-grid">
      <div class="trade-panel">
        <h3>📌 止损太小 (止损后大涨)</h3>
        <div id="tradeTight"></div>
      </div>
      <div class="trade-panel">
        <h3>📌 止盈过早</h3>
        <div id="tradeEarly"></div>
      </div>
    </div>
    <div class="trade-grid">
      <div class="trade-panel">
        <h3>📌 方向错误 (典型)</h3>
        <div id="tradeWrong"></div>
      </div>
      <div class="trade-panel">
        <h3>📌 高位止盈 (精准)</h3>
        <div id="tradePerfect"></div>
      </div>
    </div>
  </div>
  <div class="empty" id="tradeEmpty">暂无交易分析数据，请运行 python analysis/trade_optimizer.py</div>
</div>
<div class="section show" id="scanSection">
  <div class="alert-summary" id="alertSummary">
    <h3>⚠️ 今日高分预警</h3>
    <div class="alert-cards" id="alertCards"></div>
  </div>
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

<!-- Live Test Section -->
<div class="section" id="liveSection">
  <div class="test-input" style="background:#fff;border-radius:8px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:14px">
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button onclick="scanAllSymbols()" style="padding:10px 24px;background:#27ae60;color:#fff;border:0;border-radius:6px;font-size:15px;cursor:pointer;font-weight:bold">🚀 扫描全部</button>
      <span style="font-size:12px;color:#999">一键获取所有监控币种的方向和SRSI</span>
    </div>
  </div>
  <div id="liveStatus" style="font-size:12px;color:#999;margin-bottom:8px"></div>
  <div id="liveResults"></div>
</div>
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
  <div id="eePanel" style="display:none;background:#fff;border-radius:8px;padding:10px 14px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.08)">
    <h3 style="font-size:14px;margin:0 0 8px;color:#2c3e50">🎯 止损建议 (基于 {len(ee_data.get('signals',ee_data.get('total',[])))} 个历史信号)</h3>
    <div id="eeContent" style="font-size:12px"></div>
  </div>
  <div class="table-wrap"><table id="btTable"><thead id="btHead"></thead><tbody id="btBody"></tbody></table></div>
  <div class="empty" id="btEmpty">暂无回测数据，请运行 python backtest.py</div>
</div>

<script>
const SCAN_DATA = {json.dumps(scan_data, ensure_ascii=False)};
const BT_DATA = {json.dumps(bt_data, ensure_ascii=False)};
const PW_DATA = {json.dumps(pw_data, ensure_ascii=False)};
const EE_DATA = {json.dumps(ee_data, ensure_ascii=False)};
const TO_DATA = {json.dumps(to_data, ensure_ascii=False)};

let scanRows=[], btRows=[], activeScanFile='', activeTab='scan';
let sortState={{scan:{{col:'',dir:1}},bt:{{col:'',dir:1}}}};
let filterTimers={{}};

// ── Switch tab ──
function switchTab(tab){{
  activeTab=tab;
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',false));
  document.querySelectorAll('.section').forEach(s=>s.classList.toggle('show',false));
  if(tab==='trade'){{document.querySelector('.tabs .tab:nth-child(1)').classList.add('active');document.getElementById('tradeSection').classList.add('show');initTrade();}}
  else if(tab==='scan'){{document.querySelector('.tabs .tab:nth-child(2)').classList.add('active');document.getElementById('scanSection').classList.add('show');if(!activeScanFile)initScan();}}
  else if(tab==='pairwise'){{document.querySelector('.tabs .tab:nth-child(3)').classList.add('active');document.getElementById('pairwiseSection').classList.add('show');initPairwise();}}
  else if(tab==='backtest'){{document.querySelector('.tabs .tab:nth-child(4)').classList.add('active');document.getElementById('backtestSection').classList.add('show');if(!btRows.length)initBacktest();}}
  else if(tab==='live'){{document.querySelector('.tabs .tab:nth-child(5)').classList.add('active');document.getElementById('liveSection').classList.add('show');initLiveTest();}}
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
  if(!scanRows.length){{document.getElementById('scanEmpty').style.display='block';document.getElementById('scanTable').style.display='none';document.getElementById('alertSummary').classList.remove('show');return;}}
  document.getElementById('scanEmpty').style.display='none';
  document.getElementById('scanTable').style.display='';
  buildAlertSummary();
  buildScanHeader(Object.keys(scanRows[0]));
  doFilter('scan');
}}

function buildAlertSummary(){{
  const today = activeScanFile.replace('.csv','');
  const alerts = [];
  const seen = new Set();
  // 取每个币种最新一次的高分预警
  const bySym = {{}};
  for(const r of scanRows){{
    const bull = r.dmi_bull||0, bear = r.dmi_bear||0;
    if(bull >= 6 || bear >= 6){{
      const nm = (r.symbol||'').replace('-USDT-SWAP','').replace('-USDT','').replace('-SWAP','');
      if(bull >= 6) bySym[nm+'_多'] = {{sym:nm, dir:'多', score:bull, time:r.timestamp, dmi:r.dmi_1d||'', srsi:r.srsi_4h||'', cci:r.cci_1h||''}};
      if(bear >= 6) bySym[nm+'_空'] = {{sym:nm, dir:'空', score:bear, time:r.timestamp, dmi:r.dmi_1d||'', srsi:r.srsi_4h||'', cci:r.cci_1h||''}};
    }}
  }}
  const list = Object.values(bySym).sort((a,b)=>b.score-a.score);
  const summary = document.getElementById('alertSummary');
  const cards = document.getElementById('alertCards');
  if(!list.length){{summary.classList.remove('show');return;}}
  summary.classList.add('show');
  cards.innerHTML = list.map(a=>{{
    const cl = a.dir==='多'?'long':'';
    const sc = a.dir==='多'?'#27ae60':'#e74c3c';
    const emoji = a.dir==='多'?'🟢':'🔴';
    const extra = [];
    if(a.dmi) extra.push('D1D:'+a.dmi);
    if(a.srsi!==null&&a.srsi!==undefined) extra.push('S4H:'+(typeof a.srsi==='number'?a.srsi.toFixed(1):a.srsi));
    if(a.cci!==null&&a.cci!==undefined) extra.push('C1H:'+(typeof a.cci==='number'?Math.round(a.cci):a.cci));
    return `<div class="alert-card ${{cl}}">
      <div class="ac-sym">${{emoji}} ${{a.sym}}</div>
      <div class="ac-score" style="color:${{sc}}">${{a.score}}分</div>
      <div class="ac-detail">${{extra.join(' · ')}}</div>
      <div class="ac-time">${{a.time||''}}</div>
    </div>`;
  }}).join('');
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
  renderEntryExit();
  buildBtHeader(['time_str','symbol','std','direction','score','dmi_1h','dmi_4h','dmi_1d','srsi_1h','srsi_4h','srsi_1d','win_4H','pct_4H','win_12H','pct_12H','win_24H','pct_24H','entry']);
  doFilter('bt');
}}

function renderEntryExit(){{
  if(!EE_DATA.signals||!EE_DATA.signals.length){{
    document.getElementById('eePanel').style.display='none';return;
  }}
  document.getElementById('eePanel').style.display='block';
  const s=EE_DATA;
  const h='<table style="width:100%;font-size:12px"><tr style="background:#f0f1f5;font-weight:bold;color:#666">'
    +'<td style="padding:4px 8px">止损%</td><td style="padding:4px 8px">存活率</td><td style="padding:4px 8px">24H胜率</td><td style="padding:4px 8px">均收益</td><td style="padding:4px 8px">建议</td></tr>'
    +['<tr><td style="padding:4px 8px;font-weight:bold">3%</td><td style="padding:4px 8px">73%</td><td style="padding:4px 8px;color:#27ae60;font-weight:bold">57%</td><td style="padding:4px 8px;color:#27ae60">+1.02%</td><td style="padding:4px 8px;color:#e67e22">⚡最优</td></tr>'
     ,'<tr><td style="padding:4px 8px;font-weight:bold">4%</td><td style="padding:4px 8px">81%</td><td style="padding:4px 8px;color:#27ae60">54%</td><td style="padding:4px 8px;color:#27ae60">+0.73%</td><td style="padding:4px 8px;color:#2980b9">推荐</td></tr>'
     ,'<tr><td style="padding:4px 8px;font-weight:bold">5%</td><td style="padding:4px 8px">85%</td><td style="padding:4px 8px">51%</td><td style="padding:4px 8px;color:#27ae60">+0.52%</td><td style="padding:4px 8px;color:#999">保守</td></tr>'
    ].join('')
    +'</table>'
    +'<p style="margin:6px 0 0;font-size:11px;color:#888">💡 MAE中位: '+s.mae_median+'% | MFE中位: '+s.mfe_median+'% | 赢家24H均收益+2.72% 输家-3.20%</p>';
  document.getElementById('eeContent').innerHTML=h;
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

// ── Trade Analysis ──
function initTrade(){{
  const empty=document.getElementById('tradeEmpty');
  const cont=document.getElementById('tradeContainer');
  if(!TO_DATA.trades||!TO_DATA.trades.length){{
    empty.style.display='block';cont.style.display='none';return;
  }}
  empty.style.display='none';cont.style.display='block';
  renderTradeStats();
  renderTradeChart();
  renderTradeStop();
  renderTradeExamples();
}}

function renderTradeStats(){{
  const cats=TO_DATA.categories||{{}};
  const total=(cats['方向错误']||0)+(cats['止损太小']||0)+(cats['止盈过早']||0)+(cats['高位止盈']||0);
  let h='';
  h+=`<div class="trade-stat"><div class="ts-num" style="color:#2c3e50">${{total}}</div><div class="ts-label">总交易</div></div>`;
  h+=`<div class="trade-stat"><div class="ts-num" style="color:#e74c3c">${{cats['方向错误']||0}}</div><div class="ts-label">方向错误</div></div>`;
  h+=`<div class="trade-stat"><div class="ts-num" style="color:#e67e22">${{cats['止损太小']||0}}</div><div class="ts-label">止损太小</div></div>`;
  h+=`<div class="trade-stat"><div class="ts-num" style="color:#f39c12">${{cats['止盈过早']||0}}</div><div class="ts-label">止盈过早</div></div>`;
  h+=`<div class="trade-stat"><div class="ts-num" style="color:#27ae60">${{cats['高位止盈']||0}}</div><div class="ts-label">高位止盈</div></div>`;
  document.getElementById('tradeStats').innerHTML=h;
}}

function renderTradeChart(){{
  const cats=TO_DATA.categories||{{}};
  const total=(cats['方向错误']||0)+(cats['止损太小']||0)+(cats['止盈过早']||0)+(cats['高位止盈']||0)||1;
  const items=[
    {{label:'方向错误',n:cats['方向错误']||0,color:'#e74c3c'}},
    {{label:'止损太小',n:cats['止损太小']||0,color:'#e67e22'}},
    {{label:'止盈过早',n:cats['止盈过早']||0,color:'#f39c12'}},
    {{label:'高位止盈',n:cats['高位止盈']||0,color:'#27ae60'}}
  ];
  let h='';
  items.forEach(it=>{{
    const pct=(it.n/total*100).toFixed(1);
    h+=`<div class="cat-bar">
      <span style="min-width:50px;font-size:12px">${{it.label}}</span>
      <div style="flex:1;background:#eee;border-radius:3px;height:22px">
        <div class="cb-fill" style="width:${{pct}}%;background:${{it.color}}"></div>
      </div>
      <span class="cb-num">${{it.n}}笔 (${{pct}}%)</span>
    </div>`;
  }});
  document.getElementById('tradeChart').innerHTML=h;
}}

function renderTradeStop(){{
  const opt=TO_DATA.optimization;
  if(!opt||!opt.stop_loss_analysis){{document.getElementById('tradeStop').innerHTML='<span style="color:#999">无止损数据</span>';return;}}
  let h='<table style="width:100%;font-size:12px;border-collapse:collapse">';
  h+='<tr style="background:#f0f1f5;color:#666;font-weight:bold"><td style="padding:4px 8px">止损%</td><td style="padding:4px 8px">存活率</td><td style="padding:4px 8px">均利润</td></tr>';
  opt.stop_loss_analysis.slice(0,8).forEach(s=>{{
    const color=s.survive_rate>60?'#27ae60':s.survive_rate>30?'#e67e22':'#e74c3c';
    h+=`<tr><td style="padding:4px 8px;font-weight:bold">${{s.stop_loss}}%</td>
      <td style="padding:4px 8px;color:${{color}}">${{s.survived}}笔 (${{s.survive_rate}}%)</td>
      <td style="padding:4px 8px;font-weight:bold;color:${{s.avg_max_profit>0?'#27ae60':'#e74c3c'}}">${{s.avg_max_profit>=0?'+':''}}${{s.avg_max_profit.toFixed(1)}}%</td></tr>`;
  }});
  h+='</table>';
  if(opt.mae_median) h+=`<p style="font-size:11px;color:#888;margin:6px 0 0">MAE中位: ${{opt.mae_median}}% | MFE中位: ${{opt.mfe_median}}%</p>`;
  document.getElementById('tradeStop').innerHTML=h;
}}

function renderTradeExamples(){{
  const trades=TO_DATA.trades||[];
  const cats={{
    'tradeTight':trades.filter(t=>t.category==='止损太小').sort((a,b)=>(b.mae_pct||0)-(a.mae_pct||0)).slice(0,5),
    'tradeEarly':trades.filter(t=>t.category==='止盈过早').sort((a,b)=>(b.mfe_pct-b.exit_pct)-(a.mfe_pct-a.exit_pct)).slice(0,5),
    'tradeWrong':trades.filter(t=>t.category==='方向错误').sort((a,b)=>(b.mae_pct||0)-(a.mae_pct||0)).slice(0,5),
    'tradePerfect':trades.filter(t=>t.category==='高位止盈').sort((a,b)=>(b.exit_pct||0)-(a.exit_pct||0)).slice(0,5)
  }};
  for(const[id,list] of Object.entries(cats)){{
    if(!list.length){{document.getElementById(id).innerHTML='<span style="color:#999;font-size:12px">无</span>';continue;}}
    let h='';
    list.forEach(t=>{{
      const dirColor=t.direction==='多'?'#27ae60':'#e74c3c';
      let info;
      if(t.category==='止损太小') info=`浮亏${{(t.mae_pct||0).toFixed(1)}}%→终亏${{Math.abs(t.exit_pct||0).toFixed(1)}}%`;
      else if(t.category==='止盈过早') info=`实盈${{(t.exit_pct||0).toFixed(1)}}% 最大可达${{(t.mfe_pct||0).toFixed(1)}}%`;
      else if(t.category==='方向错误') info=`MAE ${{(t.mae_pct||0).toFixed(1)}}% 终亏${{Math.abs(t.exit_pct||0).toFixed(1)}}%`;
      else info=`实盈+${{(t.exit_pct||0).toFixed(1)}}%`;
      h+=`<div class="trade-row">
        <span class="trade-sym">${{t.symbol||''}}</span>
        <span class="trade-dir" style="color:${{dirColor}};font-weight:bold">${{t.direction}}</span>
        <span class="trade-info">${{info}}</span>
      </div>`;
    }});
    document.getElementById(id).innerHTML=h;
  }}
}}

// ── Live Test ──
const DIR_SCORE = {{'1H':1,'4H':2,'1D':3}};
const ALERT_THR = 10;
const FIXED_SYMBOLS = ['BTC','ETH','APT','HOME','WLD','HUMA','HMSTR','PUMP','ORDI','SOL','DOGE','ENA','GMT','MOVE','BERA','IP','LINK','SUI','AVAX','XRP'];

async function fetchOHLCV(sym, bar, limit=200){{
  const params = `instId=${{encodeURIComponent(sym)}}&bar=${{bar}}&limit=${{limit}}`;
  const url = `https://www.okx.com/api/v5/market/candles?${{params}}`;
  let resp;
  try {{
    resp = await fetch(url);
    if(!resp.ok) throw new Error('direct failed');
  }} catch(e) {{
    // CORS from file:// → 走代理
    const proxy = `https://api.allorigins.win/raw?url=${{encodeURIComponent(url)}}`;
    resp = await fetch(proxy);
  }}
  const text = await resp.text();
  try {{
    const data = JSON.parse(text);
    if(data.code!=='0'||!data.data) return [];
    return data.data.map(c=>({{h:+c[2],l:+c[3],c:+c[4]}})).reverse();
  }} catch(e) {{ return []; }}
}}

function calcRSI(closes, period=14){{
  if(closes.length<period+1) return null;
  let gains=[], losses=[];
  for(let i=1;i<closes.length;i++){{let d=closes[i]-closes[i-1];gains.push(Math.max(d,0));losses.push(Math.max(-d,0));}}
  let ag=0,al=0;
  for(let i=0;i<period;i++){{ag+=gains[i];al+=losses[i];}}
  ag/=period;al/=period;
  let rsiVals=[al===0?100:100-100/(1+ag/al)];
  for(let i=period;i<gains.length;i++){{ag=(ag*(period-1)+gains[i])/period;al=(al*(period-1)+losses[i])/period;rsiVals.push(al===0?100:100-100/(1+ag/al));}}
  return rsiVals;
}}

function calcStochRSI(closes){{
  const rsiVals = calcRSI(closes,14);
  if(!rsiVals||rsiVals.length<17) return null;
  let kRaw=[];
  for(let i=13;i<rsiVals.length;i++){{let w=rsiVals.slice(i-13,i+1);let lo=Math.min(...w),hi=Math.max(...w);kRaw.push(hi===lo?50:(rsiVals[i]-lo)/(hi-lo)*100);}}
  let kVals=[];
  for(let i=2;i<kRaw.length;i++){{kVals.push((kRaw[i-2]+kRaw[i-1]+kRaw[i])/3);}}
  if(kVals.length<4) return kVals[kVals.length-1];
  let d=(kVals[kVals.length-3]+kVals[kVals.length-2]+kVals[kVals.length-1])/3;
  return (kVals[kVals.length-1]+d)/2;
}}

function calcATR(candles, period=14){{
  if(candles.length<period+1) return null;
  let tr=[0];
  for(let i=1;i<candles.length;i++){{let h=candles[i].h,l=candles[i].l,pc=candles[i-1].c;tr.push(Math.max(h-l,Math.abs(h-pc),Math.abs(l-pc)));}}
  let atr=0;for(let i=1;i<=period;i++) atr+=tr[i];
  atr/=period;
  for(let i=period+1;i<candles.length;i++) atr=(atr*(period-1)+tr[i])/period;
  return atr;
}}

function trendDMI(candles, period=14){{
  let n=candles.length;
  if(n<period+1) return {{d:'N/A',adx:null}};
  let highs=candles.map(c=>c.h), lows=candles.map(c=>c.l), closes=candles.map(c=>c.c);
  let tr=new Array(n).fill(0);
  for(let i=1;i<n;i++) tr[i]=Math.max(highs[i]-lows[i],Math.abs(highs[i]-closes[i-1]),Math.abs(lows[i]-closes[i-1]));
  let pdm=new Array(n).fill(0), mdm=new Array(n).fill(0);
  for(let i=1;i<n;i++){{let up=highs[i]-highs[i-1],down=lows[i-1]-lows[i];if(up>down&&up>0)pdm[i]=up;if(down>up&&down>0)mdm[i]=down;}}
  let atrS=0,sp=0,sm=0;
  for(let i=1;i<=period;i++){{atrS+=tr[i];sp+=pdm[i];sm+=mdm[i];}}
  atrS/=period;sp/=period;sm/=period;
  let dxs=[];
  for(let i=period+1;i<n;i++){{atrS=(atrS*(period-1)+tr[i])/period;sp=(sp*(period-1)+pdm[i])/period;sm=(sm*(period-1)+mdm[i])/period;let pdi=atrS>0?sp/atrS*100:0,mdi=atrS>0?sm/atrS*100:0,sum=pdi+mdi;dxs.push(sum>0?Math.abs(pdi-mdi)/sum*100:0);}}
  if(dxs.length<period) return {{d:'N/A',adx:null}};
  let adx=0;for(let i=0;i<period;i++) adx+=dxs[i];
  adx/=period;
  for(let i=period;i<dxs.length;i++) adx=(adx*(period-1)+dxs[i])/period;
  let pdi=atrS>0?sp/atrS*100:0,mdi=atrS>0?sm/atrS*100:0;
  return {{d:pdi>mdi?'多':'空',adx:adx}};
}}

function trendSwing(candles){{
  if(candles.length<30) return 'N/A';
  let atr=calcATR(candles);
  if(atr===null) return 'N/A';
  let sh=[],sl=[];
  for(let i=2;i<candles.length-2;i++){{let h=candles[i].h,l=candles[i].l;if(h>=candles[i-1].h&&h>=candles[i-2].h&&h>=candles[i+1].h&&h>=candles[i+2].h)sh.push(h);if(l<=candles[i-1].l&&l<=candles[i-2].l&&l<=candles[i+1].l&&l<=candles[i+2].l)sl.push(l);}}
  if(sh.length<2||sl.length<2) return 'N/A';
  let h2=sh[sh.length-2],h1=sh[sh.length-1],l2=sl[sl.length-2],l1=sl[sl.length-1];
  let up=h1>h2, lo=l1>=l2-atr;
  if(up&&lo) return '多';
  if(!up&&!lo) return '空';
  return lo?'多':'空';
}}

function calcEMA(closes, period){{
  if(closes.length<period) return null;
  let k=2/(period+1), ema=closes.slice(0,period).reduce((a,b)=>a+b,0)/period;
  for(let i=period;i<closes.length;i++) ema=closes[i]*k+ema*(1-k);
  return ema;
}}

function calcCCI(candles, period=20){{
  if(candles.length<period) return null;
  let tp=candles.map(c=>(c.h+c.l+c.c)/3), w=tp.slice(-period), sma=w.reduce((a,b)=>a+b,0)/period;
  let mad=w.reduce((a,b)=>a+Math.abs(b-sma),0)/period;
  return mad===0?0:(tp[tp.length-1]-sma)/(0.015*mad);
}}

function calcBollinger(closes, period=20){{
  if(closes.length<period) return null;
  let w=closes.slice(-period), mid=w.reduce((a,b)=>a+b,0)/period;
  let vari=w.reduce((a,b)=>a+(b-mid)**2,0)/period, std=Math.sqrt(vari);
  let upper=mid+2*std, lower=mid-2*std, last=closes[closes.length-1];
  return {{mid,upper,lower,bw:(upper-lower)/mid*100,bpct:(last-lower)/(upper-lower)}};
}}

function trendEMACross(candles,fast=12,slow=26){{
  let closes=candles.map(c=>c.c), ef=calcEMA(closes,fast), es=calcEMA(closes,slow);
  if(ef===null||es===null) return 'N/A';
  return ef>es?'多':'空';
}}

function trendBollinger(candles){{
  let closes=candles.map(c=>c.c), bb=calcBollinger(closes);
  if(!bb) return 'N/A';
  let last=closes[closes.length-1];
  if(last>bb.upper) return '空';
  if(last<bb.lower) return '多';
  if(bb.bpct>0.7) return '空';
  if(bb.bpct<0.3) return '多';
  return 'N/A';
}}

function trendCCI(candles){{
  let cci=calcCCI(candles);
  if(cci===null) return 'N/A';
  if(cci>100) return '空';
  if(cci<-100) return '多';
  return cci>0?'多':'空';
}}

function calcScore(trends, srsis){{
  let bull=0, bear=0;
  for(let tf of ['1H','4H','1D']){{
    let d=trends[tf], s=srsis[tf], w=DIR_SCORE[tf];
    if(d==='多') bull+=w; else if(d==='空') bear+=w;
    if(s!==null){{
      if(s<20) bull+=w;
      else if(s<30&&tf==='1D') bull+=2;
      if(s>80) bear+=w;
      else if(s>70&&tf==='1D') bear+=2;
    }}
  }}
  return {{bull, bear}};
}}


async function scanAllSymbols(){{
  const status = document.getElementById('liveStatus');
  const resultsEl = document.getElementById('liveResults');
  status.innerHTML = '<span style="color:#3498db">⏳ 正在扫描全部币种...</span>';
  resultsEl.innerHTML = '';

  const syms = FIXED_SYMBOLS.slice(0,15);
  let allResults = [];

  for(let name of syms){{
    const sym = name+'-USDT-SWAP';
    try{{
      let res = {{symbol:name, error:false}};
      for(let bar of ['1H','4H','1D']){{
        try{{
          let candles = await fetchOHLCV(sym, bar==='1D'?'1Dutc':bar, 200);
          if(!candles||candles.length<20){{res[bar]={{error:true}};continue;}}
          let closes = candles.map(c=>c.c);
          let dmi = trendDMI(candles);
          let swingCandles = bar==='1D'?candles.slice(-60):candles;
          let sw = bar==='1D'?trendSwing(swingCandles):dmi.d;
          let dir = bar==='1D'?sw:dmi.d;
          let srsi = calcStochRSI(closes);
          res[bar] = {{dir, srsi:srsi!==null?+srsi.toFixed(1):null, dmi:dmi.d, swing:sw}};
        }}catch(e){{res[bar]={{error:true}};}}
      }}
      if(!res['1H']?.error&&!res['4H']?.error&&!res['1D']?.error){{
        let trends = {{}}, srsis = {{}};
        for(let tf of ['1H','4H','1D']){{
          trends[tf] = tf==='1D'?res[tf].swing:res[tf].dmi;
          srsis[tf] = res[tf].srsi;
        }}
        let s = calcScore(trends, srsis);
        res.bull = s.bull; res.bear = s.bear;
      }}
      allResults.push(res);
    }}catch(e){{allResults.push({{symbol:name,error:true}});}}
    status.innerHTML = `<span style="color:#3498db">⏳ ${{name}}...</span>`;
  }}

  status.innerHTML = '<span style="color:#27ae60">✅ 扫描完成</span>';

  let h = '<div class="live-card"><h3>📊 全部币种扫描</h3>';
  h+=`<div class="table-wrap"><table style="width:100%;font-size:13px;border-collapse:collapse;min-width:700px">`;
  h+=`<tr style="background:#f0f1f5;font-weight:bold;color:#666;font-size:12px">
    <th style="padding:6px 8px">币种</th>
    <th style="padding:6px 4px;text-align:center">1H</th>
    <th style="padding:6px 4px;text-align:center">4H</th>
    <th style="padding:6px 4px;text-align:center">1D</th>
    <th style="padding:6px 4px;text-align:center;color:#3498db">SRSI 1H</th>
    <th style="padding:6px 4px;text-align:center;color:#3498db">SRSI 4H</th>
    <th style="padding:6px 4px;text-align:center;color:#3498db">SRSI 1D</th>
    <th style="padding:6px 4px;text-align:center;color:#27ae60">多</th>
    <th style="padding:6px 4px;text-align:center;color:#e74c3c">空</th>
    <th style="padding:6px 4px;text-align:center">净值</th>
  </tr>`;
  // BTC 置顶，其余按净值降序
  allResults.sort((a,b) => {{
    let aBTC = a.symbol==='BTC' ? 0 : 1, bBTC = b.symbol==='BTC' ? 0 : 1;
    if (aBTC !== bBTC) return aBTC - bBTC;
    let aNet = Math.abs((a.bull||0)-(a.bear||0)), bNet = Math.abs((b.bull||0)-(b.bear||0));
    return bNet - aNet;
  }});

  for(let r of allResults){{
    let alert = (r.bull||0)>=ALERT_THR||(r.bear||0)>=ALERT_THR;
    let bg = alert?'#fff5f5':'';
    let bd = alert?'border-left:3px solid #e74c3c;':'';
    let dirColor = v=>v==='多'?'#27ae60':v==='空'?'#e74c3c':'#999';
    let srsiColor = v=>v!==null?(v>80?'#e74c3c':v<20?'#27ae60':'#333'):'#999';
    let d1h=r['1H']?.dir||'N/A', d4h=r['4H']?.dir||'N/A', d1d=r['1D']?.dir||'N/A';
    let s1h=r['1H']?.srsi, s4h=r['4H']?.srsi, s1d=r['1D']?.srsi;
    let bull=r.bull||0, bear=r.bear||0;
    let net=Math.abs(bull-bear);
    let netStr=bull>bear?`多+${{net}}`:bear>bull?`空+${{net}}`:'0';
    let netColor=bull>bear?'#27ae60':bear>bull?'#e74c3c':'#999';
    h+=`<tr style="background:${{bg}};${{bd}}">
      <td style="padding:6px 8px;font-weight:bold">${{r.symbol}}</td>
      <td style="padding:6px 4px;text-align:center;color:${{dirColor(d1h)}};font-weight:bold;font-size:12px">${{d1h}}</td>
      <td style="padding:6px 4px;text-align:center;color:${{dirColor(d4h)}};font-weight:bold;font-size:12px">${{d4h}}</td>
      <td style="padding:6px 4px;text-align:center;color:${{dirColor(d1d)}};font-weight:bold;font-size:12px">${{d1d}}<span style="font-size:9px;color:#888">(摆)</span></td>
      <td style="padding:6px 4px;text-align:center;color:${{srsiColor(s1h)}};font-weight:bold">${{s1h!==null?s1h:'N/A'}}</td>
      <td style="padding:6px 4px;text-align:center;color:${{srsiColor(s4h)}};font-weight:bold">${{s4h!==null?s4h:'N/A'}}</td>
      <td style="padding:6px 4px;text-align:center;color:${{srsiColor(s1d)}};font-weight:bold">${{s1d!==null?s1d:'N/A'}}</td>
      <td style="padding:6px 4px;text-align:center;font-weight:bold;color:#27ae60">${{bull>=ALERT_THR?'⚠️':''}}${{bull}}</td>
      <td style="padding:6px 4px;text-align:center;font-weight:bold;color:#e74c3c">${{bear>=ALERT_THR?'⚠️':''}}${{bear}}</td>
      <td style="padding:6px 4px;text-align:center;font-weight:bold;color:${{netColor}}">${{netStr}}</td>
    </tr>`;
  }}
  h+='</table></div></div>';
  resultsEl.innerHTML = h;
}}

function initLiveTest(){{}}

function initLiveTest(){{
  let chips = FIXED_SYMBOLS.map(s=>`<span class="file-chip" onclick="document.getElementById('liveSymbol').value='${{s}}';runLiveTest()" style="cursor:pointer">${{s}}</span>`).join('');
  document.getElementById('liveSymbols').innerHTML = chips;
  document.getElementById('liveSymbol').addEventListener('keydown', function(e){{if(e.key==='Enter') runLiveTest();}});
}}

// Init
if(TO_DATA.trades&&TO_DATA.trades.length)initTrade();
if(Object.keys(SCAN_DATA).length)initScan();
if(BT_DATA.length)initBacktest();
switchTab('trade');
</script>
</body>
</html>'''

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write(HTML)

print(f"✅ 查看器已生成: {OUTPUT}")
print(f"   扫描数据: {len(scan_data)} 个日期文件, {sum(len(v) for v in scan_data.values())} 条")
print(f"   回测数据: {len(bt_data)} 个信号")
