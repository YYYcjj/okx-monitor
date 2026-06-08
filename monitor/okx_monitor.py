#!/usr/bin/env python3
"""
OKX 策略监控 v2.1
- 方向: DMI/ADX (Wilder) + 摆动点+ATR (对比)
- StochRSI: (K+D)/2, Wilder平滑
- 评分: 方向分 1H=1, 4H=1, 1D=2 + SRSI极端值加分
- 调度: 每15分钟扫描 → 日间(7-24)整点推送全量 / 夜间(0-7)仅高分预警
- 文档: 所有扫描结果存入 okx_data/scans/YYYY-MM-DD.csv 供参数验证
"""
import warnings
warnings.filterwarnings("ignore")
import requests
import time
import json
import os
import sys
import csv
from datetime import datetime, timezone, timedelta

# 共享指标库 (使用 python -m monitor.okx_monitor 时自动可用)
from shared.indicators import (
    fetch_ohlcv, calc_rsi, calc_stoch_rsi, calc_atr,
    trend_dmi, trend_swing, calc_multi_score, calc_score, adx_weight
)

# ── 配置 ──
SYMBOLS = [
    "HOME-USDT-SWAP", "HUMA-USDT-SWAP", "BTC-USDT-SWAP", "APR-USDT-SWAP",
    "ORDI-USDT-SWAP", "PUMP-USDT-SWAP", "APT-USDT-SWAP"
]
ALERT_THRESHOLD = 6

# ── 项目根目录 ──
MONITOR_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MONITOR_DIR)

# ── 通知渠道 ──
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()
PUSHPLUS_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".pushplus_token")
if not PUSHPLUS_TOKEN and os.path.exists(PUSHPLUS_TOKEN_FILE):
    with open(PUSHPLUS_TOKEN_FILE) as f:
        PUSHPLUS_TOKEN = f.read().strip()

WEBHOOK_FILE = os.path.join(PROJECT_ROOT, ".wecom_webhook")
WECOM_WEBHOOK = ""
if os.path.exists(WEBHOOK_FILE):
    with open(WEBHOOK_FILE) as f:
        WECOM_WEBHOOK = f.read().strip()
elif os.environ.get("WECOM_WEBHOOK"):
    WECOM_WEBHOOK = os.environ["WECOM_WEBHOOK"]

# ── CSV 文档存储 ──
def save_scan_csv(results, now):
    data_dir = os.path.join(PROJECT_ROOT, "okx_data", "scans")
    os.makedirs(data_dir, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    csv_file = os.path.join(data_dir, f"{date_str}.csv")
    ts = now.strftime("%Y-%m-%d %H:%M")
    
    file_exists = os.path.exists(csv_file)
    with open(csv_file, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                'timestamp', 'symbol',
                'dmi_1h', 'dmi_4h', 'dmi_1d',
                'sw_1h', 'sw_4h', 'sw_1d',
                'adx_1h', 'adx_4h', 'adx_1d',
                'srsi_1h', 'srsi_4h', 'srsi_1d',
                'dmi_bull', 'dmi_bear', 'adx_bull', 'adx_bear', 'sw_bull', 'sw_bear'
            ])
        for r in results:
            if "_error" in r:
                continue
            sw = r.get("trends_sw", {})
            writer.writerow([
                ts, r['symbol'],
                r['trends'].get('1H', 'N/A'), r['trends'].get('4H', 'N/A'), r['trends'].get('1D', 'N/A'),
                sw.get('1H', 'N/A'), sw.get('4H', 'N/A'), sw.get('1D', 'N/A'),
                fmt_csv(r['adxs'].get('1H')), fmt_csv(r['adxs'].get('4H')), fmt_csv(r['adxs'].get('1D')),
                fmt_csv(r['srsis'].get('1H')), fmt_csv(r['srsis'].get('4H')), fmt_csv(r['srsis'].get('1D')),
                r['bull'], r['bear'], r['bull_adx'], r['bear_adx'], r['bull_sw'], r['bear_sw']
            ])
    print(f"  📄 CSV已记录 → {csv_file}")

def fmt_csv(v):
    if v is None: return ''
    return f"{v:.1f}" if isinstance(v, float) else str(v)

# ── 时间判断 ──
def should_push_full(now):
    h, m = now.hour, now.minute
    return 7 <= h <= 23 and m <= 5

def is_daytime(now):
    return 7 <= now.hour <= 23

def next_hour_cst():
    now = datetime.now(timezone(timedelta(hours=8)))
    nh = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return nh.strftime("%H:%M")

# ── 通知推送 ──
def send_report(results, now_str):
    if PUSHPLUS_TOKEN:
        return _send_pushplus_full(results, now_str)
    if WECOM_WEBHOOK:
        return _send_wecom(results, now_str)
    return False

def send_high_alert(alerts, now_str):
    if not PUSHPLUS_TOKEN:
        if WECOM_WEBHOOK:
            return _send_wecom_alert(alerts)
        return False
    return _send_pushplus_alert(alerts, now_str)

def _send_pushplus_full(results, now_str):
    url = "http://www.pushplus.plus/send"
    alert_count = sum(1 for r in results if r.get("bull",0) >= ALERT_THRESHOLD or r.get("bear",0) >= ALERT_THRESHOLD)
    dcol = {"多":"#27ae60","空":"#e74c3c","N/A":"#999"}
    def sc(v):
        try:
            n = float(v)
            if n > 80: return "#e74c3c","bold"
            if n < 20: return "#27ae60","bold"
        except: pass
        return "#333","normal"
    def srf(v):
        if v is None: return "N/A","#999","normal"
        c,w = sc(v); return f"{v:.1f}",c,w
    htm = f'<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:520px">'
    htm += f'<h3 style="margin:0 0 6px;color:#333">📊 OKX 策略扫描</h3>'
    htm += f'<p style="color:#999;font-size:12px;margin:0 0 10px">{now_str}</p>'
    alerts_list = [r for r in results if r.get("bull",0) >= ALERT_THRESHOLD or r.get("bear",0) >= ALERT_THRESHOLD]
    if alerts_list:
        htm += '<p style="color:#e74c3c;font-weight:bold;margin:0 0 6px">⚠️ 高分预警（≥6分）</p>'
        for r in alerts_list:
            nm = r["symbol"].replace("-SWAP","").replace("-USDT","")
            if r.get("bull",0) >= ALERT_THRESHOLD: htm += f'<p style="margin:2px 0;font-size:14px">🟢 <b>{nm}</b> 多分={r["bull"]}</p>'
            if r.get("bear",0) >= ALERT_THRESHOLD: htm += f'<p style="margin:2px 0;font-size:14px">🔴 <b>{nm}</b> 空分={r["bear"]}</p>'
        htm += '<hr style="border:0;border-top:1px solid #eee;margin:8px 0">'
    htm += '<table style="width:100%;border-collapse:collapse;font-size:12px">'
    htm += '<tr style="background:#f5f6fa;font-weight:bold;color:#666"><td style="padding:5px 3px">币种</td><td style="padding:5px 1px;text-align:center">1H</td><td style="padding:5px 1px;text-align:center">4H</td><td style="padding:5px 1px;text-align:center">1D</td><td style="padding:5px 1px;text-align:center;color:#3498db">1H SRSI</td><td style="padding:5px 1px;text-align:center;color:#3498db">4H SRSI</td><td style="padding:5px 1px;text-align:center;color:#3498db">1D SRSI</td><td style="padding:5px 2px;text-align:center;color:#27ae60">多</td><td style="padding:5px 2px;text-align:center;color:#e74c3c">空</td></tr>'
    for i,r in enumerate(results):
        if "_error" in r: continue
        bg = "#fff" if i%2==0 else "#fafbfc"
        nm = r["symbol"].replace("-SWAP","").replace("-USDT","")
        t = r["trends"]; s = r["srsis"]
        alert = r["bull"]>=ALERT_THRESHOLD or r["bear"]>=ALERT_THRESHOLD
        bd = "border-left:3px solid #e74c3c;" if alert else ""
        be_ = "🟢" if r["bull"]>=ALERT_THRESHOLD else ""
        re_ = "🔴" if r["bear"]>=ALERT_THRESHOLD else ""
        s1h,c1h,w1h=srf(s["1H"]); s4h,c4h,w4h=srf(s["4H"]); s1d,c1d,w1d=srf(s["1D"])
        htm += f'<tr style="background:{bg};{bd}"><td style="padding:5px 3px;font-weight:bold">{nm}</td><td style="padding:5px 1px;text-align:center;color:{dcol.get(t["1H"],"#999")};font-weight:bold;font-size:11px">{t["1H"]}</td><td style="padding:5px 1px;text-align:center;color:{dcol.get(t["4H"],"#999")};font-weight:bold;font-size:11px">{t["4H"]}</td><td style="padding:5px 1px;text-align:center;color:{dcol.get(t["1D"],"#999")};font-weight:bold;font-size:11px">{t["1D"]}</td><td style="padding:5px 1px;text-align:center;color:{c1h};font-weight:{w1h}">{s1h}</td><td style="padding:5px 1px;text-align:center;color:{c4h};font-weight:{w4h}">{s4h}</td><td style="padding:5px 1px;text-align:center;color:{c1d};font-weight:{w1d}">{s1d}</td><td style="padding:5px 2px;text-align:center;font-weight:bold;color:#27ae60">{be_}{r["bull"]}</td><td style="padding:5px 2px;text-align:center;font-weight:bold;color:#e74c3c">{re_}{r["bear"]}</td></tr>'
    htm += '</table>'
    htm += '<div style="margin-top:10px"><p style="font-size:11px;font-weight:bold;color:#666;margin:0 0 4px">📊 多标准评分对比</p>'
    htm += '<table style="width:100%;border-collapse:collapse;font-size:11px">'
    htm += '<tr style="background:#f5f6fa;font-weight:bold;color:#666"><td style="padding:4px 3px">币种</td><td style="padding:4px 2px;text-align:center">DMI纯分</td><td style="padding:4px 2px;text-align:center">ADX加权</td><td style="padding:4px 2px;text-align:center">摆动点</td></tr>'
    for i,r in enumerate(results):
        if "_error" in r: continue
        bg = "#fff" if i%2==0 else "#fafbfc"
        nm = r["symbol"].replace("-SWAP","").replace("-USDT","")
        dmi = f"多{r['bull']}" if r['bull']>=r['bear'] else f"空{r['bear']}"
        adx = f"多{r['bull_adx']:.1f}" if r['bull_adx']>=r['bear_adx'] else f"空{r['bear_adx']:.1f}"
        sw = f"多{r['bull_sw']}" if r['bull_sw']>=r['bear_sw'] else f"空{r['bear_sw']}"
        htm += f'<tr style="background:{bg}"><td style="padding:4px 3px;font-weight:bold">{nm}</td><td style="padding:4px 2px;text-align:center">{dmi}</td><td style="padding:4px 2px;text-align:center">{adx}</td><td style="padding:4px 2px;text-align:center">{sw}</td></tr>'
    htm += '</table></div>'
    htm += f'<hr style="border:0;border-top:1px solid #eee;margin:8px 0"><p style="color:#999;font-size:10px;margin:1px 0">📐 DMI/ADX | 15min扫描 · 日间整点推送 | ≥{ALERT_THRESHOLD}预警</p><p style="color:#999;font-size:10px;margin:1px 0">🔔 下轮 {(datetime.now(timezone(timedelta(hours=8)))+timedelta(hours=1)).strftime("%H:%M")} CST</p></div>'
    payload = {"token": PUSHPLUS_TOKEN, "title": f"OKX {alert_count}预警" if alert_count else "OKX 策略扫描", "content": htm, "template": "html"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        r = resp.json()
        if r.get("code") == 200:
            print(f"  ✅ PushPlus完整报表已推送 ({alert_count}个预警)"); return True
        print(f"  ❌ PushPlus推送失败: {r}"); return False
    except Exception as e:
        print(f"  ❌ PushPlus推送异常: {e}"); return False

def _send_pushplus_alert(alerts, now_str):
    url = "http://www.pushplus.plus/send"
    htm = f'<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:400px">'
    htm += f'<h3 style="color:#e74c3c;margin:0 0 6px">⚠️ OKX 高分预警</h3>'
    htm += f'<p style="color:#999;font-size:11px;margin:0 0 8px">{now_str}</p>'
    for a in alerts:
        emoji = "🟢" if a["type"] == "多" else "🔴"
        name = a["symbol"].replace("-SWAP", "").replace("-USDT", "")
        htm += f'<p style="margin:4px 0;font-size:15px;font-weight:bold">{emoji} {name} {a["type"]}分={a["score"]}</p>'
        htm += f'<p style="margin:1px 0;font-size:11px;color:#666">方向: {a.get("t_1h","")}/{a.get("t_4h","")}/{a.get("t_1d","")} | SRSI: {a.get("s_1h","")}/{a.get("s_4h","")}/{a.get("s_1d","")}</p>'
    htm += f'<hr style="border:0;border-top:1px solid #eee;margin:6px 0"><p style="color:#999;font-size:10px;margin:0">📐 DMI/ADX | 15min扫描 | ≥{ALERT_THRESHOLD}预警 | 下轮 {next_hour_cst()} CST</p></div>'
    payload = {"token": PUSHPLUS_TOKEN, "title": f"⚠️ OKX {len(alerts)}个高分预警", "content": htm, "template": "html"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        r = resp.json()
        if r.get("code") == 200:
            print(f"  ✅ 高分预警已推送 ({len(alerts)}个)"); return True
        print(f"  ❌ 高分预警推送失败: {r}"); return False
    except Exception as e:
        print(f"  ❌ 高分预警推送异常: {e}"); return False

def _send_wecom(results, now_str):
    url = WECOM_WEBHOOK
    lines = [f"## OKX 策略扫描 {now_str}", ""]
    for r in results:
        if "_error" in r: continue
        name = r["symbol"].replace("-SWAP","").replace("-USDT","")
        t = r["trends"]; s = r["srsis"]
        lines.append(f"- {name} {t['1H']}/{t['4H']}/{t['1D']} SRSI:{s['1H']}/{s['4H']}/{s['1D']} 多{r['bull']}空{r['bear']}")
    content = "\n".join(lines)
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        r = resp.json()
        if r.get("errcode") == 0:
            print(f"  ✅ 企微通知已发送"); return True
        print(f"  ❌ 企微通知失败: {r}"); return False
    except Exception as e:
        print(f"  ❌ 企微通知异常: {e}"); return False

def _send_wecom_alert(alerts):
    url = WECOM_WEBHOOK
    lines = ["## ⚠️ OKX 高分预警", ""]
    for a in alerts:
        emoji = "🟢" if a["type"] == "多" else "🔴"
        name = a["symbol"].replace("-SWAP", "").replace("-USDT", "")
        lines.append(f"- {emoji} {name} {a['type']}分={a['score']}")
    content = "\n".join(lines)
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        r = resp.json()
        if r.get("errcode") == 0:
            print(f"  ✅ 企微预警已发送"); return True
        print(f"  ❌ 企微预警失败: {r}"); return False
    except Exception as e:
        print(f"  ❌ 企微预警异常: {e}"); return False

# ── 单品种扫描 ──
def scan_symbol(sym):
    row = {"symbol": sym}
    trends = {}; trends_sw = {}; srsis = {}; adxs = {}
    for tf_label, bar in [("1H", "1H"), ("4H", "4H"), ("1D", "1D")]:
        candles = fetch_ohlcv(sym, bar)
        if not candles or len(candles) < 20:
            trends[tf_label] = "N/A"; trends_sw[tf_label] = "N/A"
            srsis[tf_label] = None; adxs[tf_label] = None
            continue
        closes = [c["c"] for c in candles]
        d, adx, _ = trend_dmi(candles)
        sw = trend_swing(candles)
        sr = calc_stoch_rsi(closes)
        trends[tf_label] = d; trends_sw[tf_label] = sw
        srsis[tf_label] = round(sr, 1) if sr is not None else None
        adxs[tf_label] = round(adx, 1) if adx is not None else None
        time.sleep(0.15)
    (dmi_b, dmi_s), (adx_b, adx_s), (sw_b, sw_s) = calc_multi_score(trends, trends_sw, srsis, adxs)
    row["trends"] = trends; row["trends_sw"] = trends_sw
    row["srsis"] = srsis; row["adxs"] = adxs
    row["bull"] = dmi_b; row["bear"] = dmi_s
    row["bull_adx"] = adx_b; row["bear_adx"] = adx_s
    row["bull_sw"] = sw_b; row["bear_sw"] = sw_s
    return row

# ── 格式化输出 ──
def fmt_srsi(v):
    return f"{v:.1f}" if v is not None else "N/A"

def fmt_line(row):
    name = row["symbol"].replace("-SWAP", "").replace("-USDT", "")
    t = row["trends"]; s = row["srsis"]; bull, bear = row["bull"], row["bear"]
    b_flag = "🟢" if bull >= ALERT_THRESHOLD else "  "
    r_flag = "🔴" if bear >= ALERT_THRESHOLD else "  "
    return (f"{name:<10} {t['1H']:^4} {t['4H']:^4} {t['1D']:^4} "
            f"{fmt_srsi(s['1H']):>7} {fmt_srsi(s['4H']):>7} {fmt_srsi(s['1D']):>7}  "
            f"{b_flag}{bull:<3}   {r_flag}{bear}")

# ── 主函数 ──
def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    now_str = now.strftime("%Y-%m-%d %H:%M CST")
    h, m = now.hour, now.minute
    period_label = "日间" if 7 <= h <= 23 else "夜间"
    is_full_push = should_push_full(now)
    print(f"\n{'='*60}")
    print(f"[{now_str}] {period_label}扫描 | 整点推送={'是' if is_full_push else '否'}")
    print(f"{'='*60}")
    
    results = []
    for sym in SYMBOLS:
        try:
            row = scan_symbol(sym)
            results.append(row)
        except Exception as e:
            name = sym.replace("-SWAP", "").replace("-USDT", "")
            results.append({"symbol": sym, "trends": {"1H":"ERR","4H":"ERR","1D":"ERR"},
                "trends_sw": {"1H":"ERR","4H":"ERR","1D":"ERR"},
                "srsis": {"1H":None,"4H":None,"1D":None},
                "adxs": {"1H":None,"4H":None,"1D":None},
                "bull":0,"bear":0,"bull_adx":0,"bear_adx":0,"bull_sw":0,"bear_sw":0,"_error": str(e)})
    
    alerts = []
    for r in results:
        if r.get("_error"): continue
        t = r["trends"]; s = r["srsis"]
        if r["bull"] >= ALERT_THRESHOLD:
            alerts.append({"type":"多","symbol":r["symbol"],"score":r["bull"],
                "t_1h":t["1H"],"t_4h":t["4H"],"t_1d":t["1D"],
                "s_1h":fmt_srsi(s["1H"]),"s_4h":fmt_srsi(s["4H"]),"s_1d":fmt_srsi(s["1D"])})
        if r["bear"] >= ALERT_THRESHOLD:
            alerts.append({"type":"空","symbol":r["symbol"],"score":r["bear"],
                "t_1h":t["1H"],"t_4h":t["4H"],"t_1d":t["1D"],
                "s_1h":fmt_srsi(s["1H"]),"s_4h":fmt_srsi(s["4H"]),"s_1d":fmt_srsi(s["1D"])})
    
    save_scan_csv(results, now)
    
    if alerts:
        print(f"\n⚠️ 高分预警（≥{ALERT_THRESHOLD}分）：")
        for a in alerts:
            emoji = "🟢" if a["type"]=="多" else "🔴"
            name = a["symbol"].replace("-SWAP","").replace("-USDT","")
            print(f"  {emoji} {name} {a['type']}分={a['score']}")
    
    print(f"\n{'币种':<10} {'1H':^4} {'4H':^4} {'1D':^4} {'1H SRSI':>7} {'4H SRSI':>7} {'1D SRSI':>7}   多分     空分")
    print("-" * 76)
    for r in results:
        if "_error" in r:
            name = r["symbol"].replace("-SWAP","").replace("-USDT","")
            print(f"{name:<10} 获取失败: {r['_error']}")
        else:
            print(fmt_line(r))
    
    print(f"\n─── 多标准对比 ───")
    print(f"{'币种':<10} {'DMI纯分':>8} {'ADX加权':>8} {'摆动点':>8}")
    print("-" * 38)
    for r in results:
        if "_error" in r: continue
        name = r["symbol"].replace("-SWAP","").replace("-USDT","")
        dmi_s = f"多{r['bull']}" if r['bull']>=r['bear'] else f"空{r['bear']}"
        adx_s = f"多{r['bull_adx']:.1f}" if r['bull_adx']>=r['bear_adx'] else f"空{r['bear_adx']:.1f}"
        sw_s = f"多{r['bull_sw']}" if r['bull_sw']>=r['bear_sw'] else f"空{r['bear_sw']}"
        print(f"{name:<10} {dmi_s:>8} {adx_s:>8} {sw_s:>8}")
    
    pushed = False
    if is_full_push:
        print(f"\n📤 日间整点，推送完整报表...")
        pushed = send_report(results, now_str)
    elif alerts:
        print(f"\n📤 高分预警，推送简报...")
        pushed = send_high_alert(alerts, now_str)
    else:
        print(f"\n📄 仅记录CSV (夜间无高分)")
    
    log_file = os.path.join(PROJECT_ROOT, "monitor_log.txt")
    status = "FULL" if is_full_push else ("ALERT" if alerts else "CSV")
    with open(log_file, "a") as f:
        f.write(f"\n[{now.strftime('%Y-%m-%d %H:%M')}] {period_label} {status} pushed={pushed} alerts={len(alerts)}\n")
    return results, alerts

if __name__ == "__main__":
    main()
