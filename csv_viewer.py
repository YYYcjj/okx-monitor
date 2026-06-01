#!/usr/bin/env python3
"""CSV 扫描数据查看器 - 本地 Web 界面"""
import http.server
import json
import csv
import os
import io
from urllib.parse import urlparse, parse_qs
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "okx_data", "scans")
PORT = 8899

HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OKX 扫描数据查看器</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f6fa;color:#333;padding:20px}
h1{font-size:20px;margin-bottom:4px}
.sub{color:#999;font-size:12px;margin-bottom:16px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}
.toolbar input,.toolbar select{padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px}
.toolbar input{width:160px}
.toolbar button{padding:6px 14px;border:0;border-radius:6px;font-size:13px;cursor:pointer;background:#3498db;color:#fff}
.toolbar button:hover{opacity:.9}
.toolbar button.reset{background:#e0e0e0;color:#555}
table{width:100%;border-collapse:collapse;font-size:12px;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
th{background:#f0f1f5;padding:8px 5px;text-align:left;font-weight:600;color:#666;position:sticky;top:0;cursor:pointer;user-select:none;white-space:nowrap}
th:hover{background:#e4e5ea}
td{padding:6px 5px;border-top:1px solid #f0f0f0}
tr:hover{background:#fafbfc}
.bull{color:#27ae60;font-weight:bold}
.bear{color:#e74c3c;font-weight:bold}
.na{color:#999}
.alert-row{background:#fff5f5}
.file-list{margin-bottom:16px;display:flex;flex-wrap:wrap;gap:6px}
.file-chip{padding:5px 12px;border-radius:20px;font-size:12px;cursor:pointer;border:1px solid #ddd;background:#fff;transition:all .15s}
.file-chip:hover{border-color:#3498db;color:#3498db}
.file-chip.active{background:#3498db;color:#fff;border-color:#3498db}
.stats{margin-bottom:12px;font-size:12px;color:#666}
.stats span{margin-right:12px}
.empty{padding:40px;text-align:center;color:#999}
.highlight td{background:#fffde7}
</style>
</head>
<body>
<h1>📊 OKX 扫描数据</h1>
<p class="sub" id="sub"></p>

<div class="file-list" id="fileList"></div>

<div class="toolbar">
  <input id="filterSymbol" placeholder="币种 (如 BTC)" oninput="doFilter()">
  <input id="filterTime" type="datetime-local" step="60" onchange="doFilter()">
  <select id="filterDir" onchange="doFilter()">
    <option value="">全部方向</option>
    <option value="多">只看多</option>
    <option value="空">只看空</option>
  </select>
  <button class="reset" onclick="resetFilter()">清除</button>
  <span id="rowCount" class="stats"></span>
</div>

<table id="table"><thead id="thead"></thead><tbody id="tbody"></tbody></table>
<div class="empty" id="empty">请选择日期文件查看</div>

<script>
let allRows = [], activeFile = '';
const dcol = {'多':'#27ae60','空':'#e74c3c','N/A':'#999'};

async function loadFiles(){
  const r = await fetch('/api/files');
  const files = await r.json();
  const fl = document.getElementById('fileList');
  fl.innerHTML = files.map((f,i) =>
    `<span class="file-chip${i===0?' active':''}" onclick="loadFile('${f}')">${f.replace('.csv','')}</span>`
  ).join('');
  if(files.length){
    loadFile(files[0]);
  }
}

async function loadFile(fn){
  activeFile = fn;
  document.querySelectorAll('.file-chip').forEach(c=>c.classList.toggle('active',c.textContent.trim()===fn.replace('.csv','')));
  const r = await fetch('/api/csv/'+encodeURIComponent(fn));
  const data = await r.json();
  allRows = data.rows;
  document.getElementById('sub').textContent = `${fn} · ${data.rows.length}条记录 · ${data.scans}次扫描`;
  if(!allRows.length){
    document.getElementById('empty').style.display='block';
    document.getElementById('table').style.display='none';
    return;
  }
  document.getElementById('empty').style.display='none';
  document.getElementById('table').style.display='';
  buildHeader(data.cols);
  doFilter();
}

function buildHeader(cols){
  const thead = document.getElementById('thead');
  thead.innerHTML = '<tr>'+cols.map(c=>
    `<th onclick="sortBy('${c}')" title="点击排序">${c}</th>`
  ).join('')+'</tr>';
}

let sortCol = '', sortDir = 1;

function sortBy(col){
  if(sortCol === col) sortDir *= -1; else {sortCol=col; sortDir=1;}
  doFilter();
}

function doFilter(){
  let rows = [...allRows];
  const sym = document.getElementById('filterSymbol').value.trim().toUpperCase();
  const timeVal = document.getElementById('filterTime').value;
  const dir = document.getElementById('filterDir').value;

  if(sym) rows = rows.filter(r=>r.symbol.toUpperCase().includes(sym));
  if(timeVal){
    const t = timeVal.replace('T',' ');
    rows = rows.filter(r=>r.timestamp.startsWith(t));
  }
  if(dir){
    const dmi = 'dmi_'+(dir==='多'?'bull':'bear');
    const adx = 'adx_'+(dir==='多'?'bull':'bear');
    const sw = 'sw_'+(dir==='多'?'bull':'bear');
    rows = rows.filter(r=>r[dmi]>=r[dmi.replace(dir==='多'?'bull':'bear',dir==='多'?'bear':'bull')]);
  }

  if(sortCol){
    const idx = Object.keys(allRows[0]).indexOf(sortCol);
    const key = sortCol;
    rows.sort((a,b)=>{
      const va = isNaN(a[key])?a[key]:+a[key];
      const vb = isNaN(b[key])?b[key]:+b[key];
      if(va<vb) return -sortDir;
      if(va>vb) return sortDir;
      return 0;
    });
  } else {
    rows.sort((a,b)=>b.timestamp.localeCompare(a.timestamp));
  }

  const tbody = document.getElementById('tbody');
  const cols = Object.keys(allRows[0]);
  tbody.innerHTML = rows.map(r=>{
    let cls = '';
    if(r.dmi_bull>=6||r.dmi_bear>=6||r.sw_bull>=6||r.sw_bear>=6) cls='alert-row';
    return '<tr class="'+cls+'">'+cols.map((c,i)=>{
      let v = r[c];
      if(c.includes('dmi_')&&['多','空'].includes(v)) v=`<span style="color:${dcol[v]};font-weight:bold">${v}</span>`;
      if(c.includes('sw_')&&['多','空'].includes(v)) v=`<span style="color:${dcol[v]};font-weight:bold">${v}</span>`;
      if((c==='dmi_bull'||c==='dmi_bear'||c==='sw_bull'||c==='sw_bear')&&v>=6) v=`<b class="bull">${v}</b>`;
      if((c==='adx_bull'||c==='adx_bear')&&+v>=6) v=`<b class="bull">${v}</b>`;
      if(v===null||v===undefined||v==='') v='<span class="na">-</span>';
      return `<td>${v}</td>`;
    }).join('')+'</tr>';
  }).join('');
  document.getElementById('rowCount').textContent = `显示 ${rows.length}/${allRows.length} 条`;
}

function resetFilter(){
  document.getElementById('filterSymbol').value='';
  document.getElementById('filterTime').value='';
  document.getElementById('filterDir').value='';
  sortCol=''; sortDir=1;
  doFilter();
}

loadFiles();
</script>
</body>
</html>"""

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        p = urlparse(self.path)
        if p.path == '/' or p.path == '/index.html':
            self._html(HTML)
        elif p.path == '/api/files':
            self._api_files()
        elif p.path.startswith('/api/csv/'):
            fn = os.path.basename(p.path[9:])
            self._api_csv(fn)
        else:
            self.send_error(404)

    def _html(self, content):
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content.encode('utf-8'))

    def _api_files(self):
        files = []
        if os.path.isdir(DATA_DIR):
            for f in os.listdir(DATA_DIR):
                if f.endswith('.csv'):
                    files.append(f)
        files.sort(reverse=True)
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps(files).encode())

    def _api_csv(self, filename):
        fpath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(fpath):
            self.send_error(404, 'File not found')
            return
        rows = []
        scans = set()
        with open(fpath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            cols = reader.fieldnames or []
            for row in reader:
                # convert numeric fields
                for k in ('adx_1h','adx_4h','adx_1d','srsi_1h','srsi_4h','srsi_1d',
                          'dmi_bull','dmi_bear','adx_bull','adx_bear','sw_bull','sw_bear'):
                    try:
                        v = row.get(k,'')
                        if v == '':
                            row[k] = None
                        elif '.' in str(v):
                            row[k] = round(float(v),1)
                        else:
                            row[k] = int(v)
                    except:
                        pass
                rows.append(row)
                scans.add(row.get('timestamp',''))
        result = {'cols': cols, 'rows': rows, 'scans': len(scans)}
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode())

    def log_message(self, format, *args):
        pass  # suppress logs

if __name__ == '__main__':
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"\n  📊 OKX 扫描数据查看器")
    print(f"  数据目录: {DATA_DIR}")
    print(f"  打开浏览器访问: http://localhost:{PORT}")
    print(f"  按 Ctrl+C 停止\n")
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止")
        server.server_close()
