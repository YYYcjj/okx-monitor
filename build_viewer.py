#!/usr/bin/env python3
"""生成自包含 HTML 查看器 - 双击 okx_data/viewer.html 即可打开"""
import csv
import json
import os
from glob import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "okx_data", "scans")
OUTPUT = os.path.join(SCRIPT_DIR, "okx_data", "viewer.html")

def load_all_csvs():
    files = sorted(glob(os.path.join(DATA_DIR, "*.csv")), reverse=True)
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
                for k in ('dmi_bull','dmi_bear','sw_bull','sw_bear'):
                    try: row[k] = int(row[k])
                    except: pass
                for k in ('adx_bull','adx_bear'):
                    try: row[k] = round(float(row[k]),1)
                    except: pass
                rows.append(row)
        all_data[fn] = rows
    return all_data

data = load_all_csvs()
json_data = json.dumps(data, ensure_ascii=False)

HTML = f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OKX 扫描数据查看器</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f6fa;color:#333;padding:20px}}
h1{{font-size:20px;margin-bottom:4px}}
.sub{{color:#999;font-size:12px;margin-bottom:12px}}
.file-list{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}}
.file-chip{{padding:5px 14px;border-radius:20px;font-size:12px;cursor:pointer;border:1px solid #ddd;background:#fff;transition:all .15s;white-space:nowrap}}
.file-chip:hover{{border-color:#3498db;color:#3498db}}
.file-chip.active{{background:#3498db;color:#fff;border-color:#3498db}}
.toolbar{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}}
.toolbar input,.toolbar select{{padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px}}
.toolbar input{{width:160px}}
.toolbar button{{padding:6px 14px;border:0;border-radius:6px;font-size:13px;cursor:pointer;background:#3498db;color:#fff;transition:opacity .15s}}
.toolbar button:hover{{opacity:.9}}
.toolbar button.reset{{background:#e0e0e0;color:#555}}
.toolbar button.refresh{{background:#27ae60}}
.table-wrap{{overflow-x:auto;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);max-height:70vh;overflow-y:auto}}
table{{width:100%;border-collapse:collapse;font-size:12px;background:#fff;min-width:900px}}
th{{background:#f0f1f5;padding:8px 5px;text-align:left;font-weight:600;color:#666;position:sticky;top:0;z-index:1;cursor:pointer;user-select:none;white-space:nowrap}}
th:hover{{background:#e4e5ea}}
th::after{{content:' ↕';font-size:10px;color:#bbb}}
th.asc::after{{content:' ↑';color:#3498db}}
th.desc::after{{content:' ↓';color:#3498db}}
td{{padding:6px 5px;border-top:1px solid #f0f0f0;white-space:nowrap}}
tr:hover{{background:#fafbfc!important}}
tr.alert{{background:#fff5f5}}
tr.alert:hover{{background:#ffeaea!important}}
.bull{{color:#27ae60;font-weight:bold}}
.bear{{color:#e74c3c;font-weight:bold}}
.na{{color:#ccc}}
.stats{{margin-bottom:12px;font-size:12px;color:#666}}
.stats span{{margin-right:16px}}
.empty{{padding:60px;text-align:center;color:#ccc;font-size:15px}}
.score-high{{font-weight:bold;color:#27ae60}}
.score-warn{{font-weight:bold;color:#e74c3c}}
@media(max-width:768px){{body{{padding:10px}}h1{{font-size:17px}}}}
</style>
</head>
<body>
<h1>📊 OKX 扫描数据查看器</h1>
<p class="sub" id="sub">请选择日期文件查看</p>

<div class="file-list" id="fileList"></div>
<div class="toolbar">
  <input id="filterSymbol" placeholder="币种筛选 (如 BTC)" oninput="deferFilter()">
  <select id="filterTf" onchange="deferFilter()">
    <option value="">全部周期</option>
    <option value="1H">只看1H</option>
    <option value="4H">只看4H</option>
    <option value="1D">只看1D</option>
  </select>
  <select id="filterDir" onchange="deferFilter()"><option value="">全部</option><option value="多">最多</option><option value="空">最空</option></select>
  <input id="filterScore" type="number" placeholder="评分≥" min="0" max="12" style="width:80px" oninput="deferFilter()">
  <input id="filterTime" type="datetime-local" step="60" onchange="deferFilter()">
  <button class="reset" onclick="resetFilter()">清除筛选</button>
  <button class="refresh" onclick="location.reload()">🔄 刷新</button>
</div>

<div id="stats" class="stats"></div>
<div class="table-wrap"><table id="table"><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
<div class="empty" id="empty">选择一个日期文件开始查看</div>

<script>
const DATA = {json_data};
let allRows = [], activeFile = '', sortCol = '', sortDir = 1, filterTimer;

function init() {{
  const keys = Object.keys(DATA).sort().reverse();
  const fl = document.getElementById('fileList');
  if(!keys.length){{ fl.innerHTML='<span style="color:#999;font-size:13px">暂无数据，等待扫描...</span>';return;}}
  fl.innerHTML = keys.map((f,i)=>`<span class="file-chip${{i===0?' active':''}}" onclick="loadFile('${{f}}')">${{f.replace('.csv','')}}</span>`).join('');
  loadFile(keys[0]);
}}

function loadFile(fn) {{
  activeFile = fn;
  document.querySelectorAll('.file-chip').forEach(c=>c.classList.toggle('active',c.textContent.trim()===fn.replace('.csv','')));
  const rows = DATA[fn] || [];
  allRows = rows;
  document.getElementById('sub').textContent = fn.replace('.csv','') + ' · ' + rows.length + ' 条记录';
  if(!rows.length){{document.getElementById('empty').style.display='block';document.getElementById('table').style.display='none';return;}}
  document.getElementById('empty').style.display='none';
  document.getElementById('table').style.display='';
  buildHeader(Object.keys(rows[0]));
  doFilter();
}}

function buildHeader(cols) {{
  const thead = document.getElementById('thead');
  const labels = {{timestamp:'时间',symbol:'币种',dmi_1h:'DMI 1H',dmi_4h:'DMI 4H',dmi_1d:'DMI 1D',
    sw_1h:'SW 1H',sw_4h:'SW 4H',sw_1d:'SW 1D',
    adx_1h:'ADX 1H',adx_4h:'ADX 4H',adx_1d:'ADX 1D',
    srsi_1h:'SRSI 1H',srsi_4h:'SRSI 4H',srsi_1d:'SRSI 1D',
    dmi_bull:'DMI多',dmi_bear:'DMI空',adx_bull:'ADX多',adx_bear:'ADX空',sw_bull:'SW多',sw_bear:'SW空'}};
  thead.innerHTML = '<tr>'+cols.map(c=>`<th onclick="sortBy('${{c}}')">${{labels[c]||c}}</th>`).join('')+'</tr>';
}}

function sortBy(col) {{
  if(sortCol===col)sortDir*=-1;else{{sortCol=col;sortDir=1;}}
  document.querySelectorAll('th').forEach(th=>{{th.classList.remove('asc','desc');if(th.textContent.includes(col))th.classList.add(sortDir===1?'asc':'desc');}});
  doFilter();
}}

function deferFilter(){{clearTimeout(filterTimer);filterTimer=setTimeout(doFilter,200);}}

function doFilter() {{
  let rows = [...allRows];
  const qSym = document.getElementById('filterSymbol').value.trim().toUpperCase();
  const qTf = document.getElementById('filterTf').value;
  const qDir = document.getElementById('filterDir').value;
  const qScore = parseInt(document.getElementById('filterScore').value)||0;
  const qTime = document.getElementById('filterTime').value;

  if(qSym) rows = rows.filter(r=>r.symbol.toUpperCase().includes(qSym));
  if(qTime) rows = rows.filter(r=>r.timestamp.startsWith(qTime.replace('T',' ')));
  if(qScore) rows = rows.filter(r=>(r.dmi_bull>=qScore||r.dmi_bear>=qScore||r.sw_bull>=qScore||r.sw_bear>=qScore));
  if(qDir==='多') rows = rows.filter(r=>r.dmi_bull>r.dmi_bear);
  if(qDir==='空') rows = rows.filter(r=>r.dmi_bear>r.dmi_bull);

  if(sortCol) {{
    rows.sort((a,b)=>{{
      const va = a[sortCol], vb = b[sortCol];
      const na=isNaN(va)||va===null, nb=isNaN(vb)||vb===null;
      if(na&&nb)return 0;if(na)return 1;if(nb)return -1;
      if(+va<+vb)return -sortDir;if(+va>+vb)return sortDir;return 0;
    }});
  }} else rows.sort((a,b)=>b.timestamp.localeCompare(a.timestamp));

  const tbody = document.getElementById('tbody');
  const cols = Object.keys(allRows[0]);
  tbody.innerHTML = rows.map(r=>{{
    const alert = (r.dmi_bull>=6||r.dmi_bear>=6) ? 'alert' : '';
    return '<tr class="'+alert+'">'+cols.map(c=>{{
      let v = r[c];
      if(v===null||v===undefined||v==='') return '<td><span class="na">-</span></td>';
      if(['dmi_1h','dmi_4h','dmi_1d','sw_1h','sw_4h','sw_1d'].includes(c))
        return `<td style="color:${{v==='多'?'#27ae60':v==='空'?'#e74c3c':'#999'}};font-weight:bold">${{v}}</td>`;
      if(c==='symbol') return `<td style="font-weight:bold">${{(v||'').replace('-USDT-SWAP','').replace('-USDT','').replace('-SWAP','')}}</td>`;
      if(['dmi_bull','sw_bull'].includes(c)) return `<td>${{v>=6?'<b class="score-high">'+v+'</b>':v}}</td>`;
      if(['dmi_bear','sw_bear'].includes(c)) return `<td>${{v>=6?'<b class="score-warn">'+v+'</b>':v}}</td>`;
      if((c==='adx_bull'||c==='adx_bear')&&+v>=6) return `<td><b class="score-high">${{v}}</b></td>`;
      return `<td>${{v}}</td>`;
    }}).join('')+'</tr>';
  }}).join('');

  const adxHigh = rows.filter(r=>(r.adx_bull>=6||r.adx_bear>=6)).length;
  const dmiHigh = rows.filter(r=>(r.dmi_bull>=6||r.dmi_bear>=6)).length;
  const swHigh = rows.filter(r=>(r.sw_bull>=6||r.sw_bear>=6)).length;
  document.getElementById('stats').innerHTML =
    `<span>📋 ${{rows.length}}/${{allRows.length}} 条</span><span>🟢 DMI预警${{dmiHigh}}</span><span>🔵 ADX预警${{adxHigh}}</span><span>🟡 SW预警${{swHigh}}</span>`;
}}

function resetFilter() {{
  document.getElementById('filterSymbol').value='';
  document.getElementById('filterTf').value='';
  document.getElementById('filterDir').value='';
  document.getElementById('filterScore').value='';
  document.getElementById('filterTime').value='';
  sortCol='';sortDir=1;
  document.querySelectorAll('th').forEach(th=>th.classList.remove('asc','desc'));
  doFilter();
}}

init();
</script>
</body>
</html>'''

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write(HTML)

print(f"✅ 查看器已生成: {OUTPUT}")
print(f"   {len(data)} 个CSV文件已嵌入")
for fn, rows in data.items():
    print(f"   {fn}: {len(rows)} 条")
