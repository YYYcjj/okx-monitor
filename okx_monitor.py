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

# ── 配置 ──
RSI_PERIOD = 14
STOCH_PERIOD = 14
ATR_PERIOD = 14
SYMBOLS = [
    "APT-USDT", "HOME-USDT-SWAP", "WLD-USDT-SWAP", "BTC-USDT",
    "HUMA-USDT", "HMSTR-USDT", "PUMP-USDT", "ORDI-USDT"
]
OKX_BASE = "https://www.okx.com"
ALERT_THRESHOLD = 6

# ── 通知渠道 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# PushPlus (推荐): https://www.pushplus.plus/ 微信扫码 → 获取Token，免费200条/天
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()
PUSHPLUS_TOKEN_FILE = os.path.join(SCRIPT_DIR, ".pushplus_token")
if not PUSHPLUS_TOKEN and os.path.exists(PUSHPLUS_TOKEN_FILE):
    with open(PUSHPLUS_TOKEN_FILE) as f:
        PUSHPLUS_TOKEN = f.read().strip()

# 企微机器人 (备用)
WEBHOOK_FILE = os.path.join(SCRIPT_DIR, ".wecom_webhook")
WECOM_WEBHOOK = ""
if os.path.exists(WEBHOOK_FILE):
    with open(WEBHOOK_FILE) as f:
        WECOM_WEBHOOK = f.read().strip()
elif os.environ.get("WECOM_WEBHOOK"):
    WECOM_WEBHOOK = os.environ["WECOM_WEBHOOK"]

# ── 数据获取 ──
def fetch_ohlcv(symbol, bar, limit=200, retries=3):
    url = f"{OKX_BASE}/api/v5/market/candles"
    for attempt in range(retries):
        try:
            resp = requests.get(url, params={"instId": symbol, "bar": bar, "limit": limit}, timeout=15)
            d = resp.json()
            if d.get("code") == "0":
                candles = []
                for c in d["data"]:
                    candles.append({
                        "h": float(c[2]), "l": float(c[3]), "c": float(c[4])
                    })
                candles.reverse()
                return candles
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                return None
    return None

# ── RSI (Wilder's smoothing) ──
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None, []
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_values = []
    if avg_loss == 0:
        rsi_values.append(100)
    else:
        rsi_values.append(100 - 100 / (1 + avg_gain / avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rsi_values.append(100 - 100 / (1 + avg_gain / avg_loss))
    return rsi_values[-1], rsi_values

# ── StochRSI (K+D)/2 ──
def calc_stoch_rsi(closes, rsi_period=14, stoch_period=14):
    _, rsi_values = calc_rsi(closes, rsi_period)
    if not rsi_values or len(rsi_values) < stoch_period:
        return None
    k_vals = []
    for i in range(stoch_period - 1, len(rsi_values)):
        w = rsi_values[i - stoch_period + 1 : i + 1]
        lo, hi = min(w), max(w)
        k_vals.append(50 if hi == lo else (rsi_values[i] - lo) / (hi - lo) * 100)
    if len(k_vals) < 4:
        return k_vals[-1] if k_vals else None
    d = sum(k_vals[-3:]) / 3
    return (k_vals[-1] + d) / 2

# ── ATR (Wilder's smoothing) ──
def calc_atr(candles, period=14):
    n = len(candles)
    if n < period + 1:
        return None
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i-1]["c"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = sum(tr[1:period+1]) / period
    for i in range(period+1, n):
        atr = (atr * (period - 1) + tr[i]) / period
    return atr

# ── 方向判断: DMI/ADX (Wilder's Directional Movement) ──
def trend_dmi(candles, period=14):
    """
    DMI方向判断 + ADX趋势强度
    +DI > -DI → 多, -DI > +DI → 空
    ADX: <20弱趋势  20-25形成中  >25强趋势
    返回: (方向, ADX值, ATR值)
    """
    n = len(candles)
    if n < period + 1:
        return "N/A", None, None
    
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    closes = [c["c"] for c in candles]
    
    # True Range
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i-1]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    
    # Directional Movement
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down
    
    # Wilder's smoothing
    atr_smooth = sum(tr[1:period+1]) / period
    spdm = sum(plus_dm[1:period+1]) / period
    smdm = sum(minus_dm[1:period+1]) / period
    
    dx_vals = []
    for i in range(period+1, n):
        atr_smooth = (atr_smooth * (period - 1) + tr[i]) / period
        spdm = (spdm * (period - 1) + plus_dm[i]) / period
        smdm = (smdm * (period - 1) + minus_dm[i]) / period
        
        pdi = spdm / atr_smooth * 100 if atr_smooth > 0 else 0
        mdi = smdm / atr_smooth * 100 if atr_smooth > 0 else 0
        s = pdi + mdi
        dx_vals.append(abs(pdi - mdi) / s * 100 if s > 0 else 0)
    
    if len(dx_vals) < period:
        return "N/A", None, atr_smooth
    
    # ADX = Wilder smoothing of DX
    adx = sum(dx_vals[:period]) / period
    for i in range(period, len(dx_vals)):
        adx = (adx * (period - 1) + dx_vals[i]) / period
    
    # Final +DI/-DI from last bar
    last_atr = atr_smooth
    last_pdi = spdm / last_atr * 100 if last_atr > 0 else 0
    last_mdi = smdm / last_atr * 100 if last_atr > 0 else 0
    
    if last_pdi > last_mdi:
        return "多", adx, last_atr
    else:
        return "空", adx, last_atr

# ── 摆动点方向 (对比用) ──
def trend_swing(candles):
    """摆动高低点 + 1ATR容差 (原始算法，仅用于对比)"""
    n = len(candles)
    if n < 30:
        return "N/A"
    atr = calc_atr(candles)
    if atr is None:
        return "N/A"
    swing_highs, swing_lows = [], []
    for i in range(2, n - 2):
        h, l = candles[i]["h"], candles[i]["l"]
        if (h >= candles[i-1]["h"] and h >= candles[i-2]["h"] and
            h >= candles[i+1]["h"] and h >= candles[i+2]["h"]):
            swing_highs.append(h)
        if (l <= candles[i-1]["l"] and l <= candles[i-2]["l"] and
            l <= candles[i+1]["l"] and l <= candles[i+2]["l"]):
            swing_lows.append(l)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "N/A"
    h2, h1 = swing_highs[-2], swing_highs[-1]
    l2, l1 = swing_lows[-2], swing_lows[-1]
    highs_up = h1 > h2
    lows_ok = l1 >= l2 - atr
    if highs_up and lows_ok:
        return "多"
    elif not highs_up and not lows_ok:
        return "空"
    else:
        return "多" if lows_ok else "空"

# ── 多标准评分 ──
DIR_SCORE = {"1H": 1, "4H": 1, "1D": 2}

def calc_multi_score(trends_dmi, trends_sw, srsis, adxs):
    """
    返回三套评分:
      dmi_pure: DMI方向 (纯整数)
      dmi_adx:  DMI方向 × ADX权重
      swing:    摆动点方向 (纯整数)
    """
    def score_one(trends, weight_fn=None):
        bull, bear = 0, 0
        for tf in ["1H", "4H", "1D"]:
            d = trends[tf]
            s = srsis[tf]
            w = DIR_SCORE[tf]
            if weight_fn:
                adx = adxs[tf]
                aw = 0.5 if (adx is not None and adx < 20) else (0.75 if (adx is not None and adx < 25) else 1.0)
                w *= aw
            if d == "多": bull += w
            elif d == "空": bear += w
            if s is not None:
                if s < 20: bull += 2 if tf == "1D" else DIR_SCORE[tf]
                elif s < 30 and tf == "1D": bull += 1
                if s > 80: bear += 2 if tf == "1D" else DIR_SCORE[tf]
                elif s > 70 and tf == "1D": bear += 1
        return round(bull, 1), round(bear, 1)
    
    dmi_b, dmi_s = score_one(trends_dmi)
    adx_b, adx_s = score_one(trends_dmi, weight_fn=True)
    sw_b, sw_s = score_one(trends_sw)
    
    return (int(dmi_b), int(dmi_s)), (adx_b, adx_s), (int(sw_b), int(sw_s))

# ── 评分 (默认用DMI纯整数) ──
def adx_weight(adx):
    """ADX趋势强度 → 方向分权重"""
    if adx is None:
        return 1.0
    if adx < 20:
        return 0.5
    elif adx < 25:
        return 0.75
    else:
        return 1.0

def calc_score(trends, srsis, adx_values):
    bull, bear = 0, 0
    for tf in ["1H", "4H", "1D"]:
        d = trends[tf]
        s = srsis[tf]
        w = DIR_SCORE[tf]
        
        if d == "多":
            bull += w
        elif d == "空":
            bear += w
        
        if s is not None:
            if s < 20:
                bull += 2 if tf == "1D" else w
            elif s < 30 and tf == "1D":
                bull += 1
            if s > 80:
                bear += 2 if tf == "1D" else w
            elif s > 70 and tf == "1D":
                bear += 1
    
    return bull, bear

# ── CSV 文档存储 ──
def save_scan_csv(results, now):
    """每次扫描结果追加到当日CSV，供参数验证"""
    data_dir = os.path.join(SCRIPT_DIR, "okx_data", "scans")
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
    if v is None:
        return ''
    return f"{v:.1f}" if isinstance(v, float) else str(v)

# ── 时间判断 ──
def should_push_full(now):
    """日间(7:00-23:59)整点±5分钟 → 推送完整报表"""
    h, m = now.hour, now.minute
    return 7 <= h <= 23 and m <= 5

def is_daytime(now):
    """7:00-23:59 日间时段"""
    return 7 <= now.hour <= 23

def next_hour_cst():
    """下一整点 CST 时间字符串"""
    now = datetime.now(timezone(timedelta(hours=8)))
    nh = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return nh.strftime("%H:%M")

# ── 通知推送 ──

def send_report(results, now_str):
    """推送完整HTML报表 (日间整点用)"""
    if PUSHPLUS_TOKEN:
        return _send_pushplus_full(results, now_str)
    if WECOM_WEBHOOK:
        return _send_wecom(results, now_str)
    return False

def send_high_alert(alerts, now_str):
    """推送高分预警简报 (任何时段高分触发)"""
    if not PUSHPLUS_TOKEN:
        if WECOM_WEBHOOK:
            return _send_wecom_alert(alerts)
        return False
    return _send_pushplus_alert(alerts, now_str)

def _send_pushplus_full(results, now_str):
    """PushPlus 完整HTML报表"""
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
    
    alerts = [r for r in results if r.get("bull",0) >= ALERT_THRESHOLD or r.get("bear",0) >= ALERT_THRESHOLD]
    if alerts:
        htm += '<p style="color:#e74c3c;font-weight:bold;margin:0 0 6px">⚠️ 高分预警（≥6分）</p>'
        for r in alerts:
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
    
    # Comparison table
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
    
    htm += f'<hr style="border:0;border-top:1px solid #eee;margin:8px 0"><p style="color:#999;font-size:10px;margin:1px 0">📐 DMI/ADX | 15min扫描 · 日间整点推送 | ≥{ALERT_THRESHOLD}预警</p><p style="color:#999;font-size:10px;margin:1px 0">⚡ SRSI>80空加分 <20多加 · 1D加权×2</p><p style="color:#999;font-size:10px;margin:1px 0">🔔 下轮 {(datetime.now(timezone(timedelta(hours=8)))+timedelta(hours=1)).strftime("%H:%M")} CST</p></div>'
    
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
    """PushPlus 高分预警简报"""
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
    """企微机器人推送（备用）"""
    url = WECOM_WEBHOOK
    lines = [f"## OKX 策略扫描 {now_str}", ""]
    for r in results:
        if "_error" in r: continue
        name = r["symbol"].replace("-SWAP","").replace("-USDT","")
        t = r["trends"]
        s = r["srsis"]
        bull = r["bull"]
        bear = r["bear"]
        lines.append(f"- {name} {t['1H']}/{t['4H']}/{t['1D']} SRSI:{s['1H']}/{s['4H']}/{s['1D']} 多{bull}空{bear}")
    content = "\n".join(lines)
    
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content}
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        r = resp.json()
        if r.get("errcode") == 0:
            print(f"  ✅ 企微通知已发送")
            return True
        else:
            print(f"  ❌ 企微通知失败: {r}")
            return False
    except Exception as e:
        print(f"  ❌ 企微通知异常: {e}")
        return False

def _send_wecom_alert(alerts):
    """企微高分预警（备用）"""
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
    trends = {}
    trends_sw = {}
    srsis = {}
    adxs = {}
    
    for tf_label, bar in [("1H", "1H"), ("4H", "4H"), ("1D", "1D")]:
        candles = fetch_ohlcv(sym, bar)
        if not candles or len(candles) < 20:
            trends[tf_label] = "N/A"
            trends_sw[tf_label] = "N/A"
            srsis[tf_label] = None
            adxs[tf_label] = None
            continue
        
        closes = [c["c"] for c in candles]
        d, adx, atr = trend_dmi(candles)
        sw = trend_swing(candles)
        sr = calc_stoch_rsi(closes)
        
        trends[tf_label] = d
        trends_sw[tf_label] = sw
        srsis[tf_label] = round(sr, 1) if sr is not None else None
        adxs[tf_label] = round(adx, 1) if adx is not None else None
        time.sleep(0.15)
    
    (dmi_b, dmi_s), (adx_b, adx_s), (sw_b, sw_s) = calc_multi_score(trends, trends_sw, srsis, adxs)
    row["trends"] = trends
    row["trends_sw"] = trends_sw
    row["srsis"] = srsis
    row["adxs"] = adxs
    row["bull"] = dmi_b
    row["bear"] = dmi_s
    row["bull_adx"] = adx_b
    row["bear_adx"] = adx_s
    row["bull_sw"] = sw_b
    row["bear_sw"] = sw_s
    
    return row

# ── 格式化输出 ──
def fmt_srsi(v):
    return f"{v:.1f}" if v is not None else "N/A"

def fmt_line(row):
    name = row["symbol"].replace("-SWAP", "").replace("-USDT", "")
    t = row["trends"]
    s = row["srsis"]
    adxs = row.get("adxs", {})
    bull, bear = row["bull"], row["bear"]
    
    b_flag = "🟢" if bull >= ALERT_THRESHOLD else "  "
    r_flag = "🔴" if bear >= ALERT_THRESHOLD else "  "
    
    adx_1h = f"{adxs['1H']:.0f}" if adxs['1H'] is not None else "N/A"
    
    return (f"{name:<10} {t['1H']:^4} {t['4H']:^4} {t['1D']:^4} "
            f"{fmt_srsi(s['1H']):>7} {fmt_srsi(s['4H']):>7} {fmt_srsi(s['1D']):>7}  "
            f"{b_flag}{bull:<3}   {r_flag}{bear}")

# ── 主函数 ──
def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    now_str = now.strftime("%Y-%m-%d %H:%M CST")
    h, m = now.hour, now.minute
    
    # 判断时段标签
    if 7 <= h <= 23:
        period_label = "日间"
    else:
        period_label = "夜间"
    
    is_full_push = should_push_full(now)
    
    print(f"\n{'='*60}")
    print(f"[{now_str}] {period_label}扫描 | 整点推送={'是' if is_full_push else '否'}")
    print(f"{'='*60}")
    
    # ── 扫描所有品种 ──
    results = []
    for sym in SYMBOLS:
        try:
            row = scan_symbol(sym)
            results.append(row)
        except Exception as e:
            name = sym.replace("-SWAP", "").replace("-USDT", "")
            results.append({
                "symbol": sym,
                "trends": {"1H":"ERR","4H":"ERR","1D":"ERR"},
                "trends_sw": {"1H":"ERR","4H":"ERR","1D":"ERR"},
                "srsis": {"1H":None,"4H":None,"1D":None},
                "adxs": {"1H":None,"4H":None,"1D":None},
                "bull": 0, "bear": 0,
                "bull_adx": 0, "bear_adx": 0,
                "bull_sw": 0, "bear_sw": 0,
                "_error": str(e)
            })
    
    # ── 收集高分预警 ──
    alerts = []
    for r in results:
        if r.get("_error"): continue
        t = r["trends"]; s = r["srsis"]
        if r["bull"] >= ALERT_THRESHOLD:
            alerts.append({
                "type": "多", "symbol": r["symbol"], "score": r["bull"],
                "t_1h": t["1H"], "t_4h": t["4H"], "t_1d": t["1D"],
                "s_1h": fmt_srsi(s["1H"]), "s_4h": fmt_srsi(s["4H"]), "s_1d": fmt_srsi(s["1D"]),
            })
        if r["bear"] >= ALERT_THRESHOLD:
            alerts.append({
                "type": "空", "symbol": r["symbol"], "score": r["bear"],
                "t_1h": t["1H"], "t_4h": t["4H"], "t_1d": t["1D"],
                "s_1h": fmt_srsi(s["1H"]), "s_4h": fmt_srsi(s["4H"]), "s_1d": fmt_srsi(s["1D"]),
            })
    
    # ── 1. 始终保存CSV文档 ──
    save_scan_csv(results, now)
    
    # ── 2. 控制台输出 ──
    if alerts:
        print(f"\n⚠️ 高分预警（≥{ALERT_THRESHOLD}分）：")
        for a in alerts:
            emoji = "🟢" if a["type"] == "多" else "🔴"
            name = a["symbol"].replace("-SWAP", "").replace("-USDT", "")
            print(f"  {emoji} {name} {a['type']}分={a['score']}")
    
    print(f"\n{'币种':<10} {'1H':^4} {'4H':^4} {'1D':^4} {'1H SRSI':>7} {'4H SRSI':>7} {'1D SRSI':>7}   多分     空分")
    print("-" * 76)
    for r in results:
        if "_error" in r:
            name = r["symbol"].replace("-SWAP", "").replace("-USDT", "")
            print(f"{name:<10} 获取失败: {r['_error']}")
        else:
            print(fmt_line(r))
    
    print(f"\n─── 多标准对比 ───")
    print(f"{'币种':<10} {'DMI纯分':>8} {'ADX加权':>8} {'摆动点':>8}")
    print("-" * 38)
    for r in results:
        if "_error" in r: continue
        name = r["symbol"].replace("-SWAP","").replace("-USDT","")
        dmi_s = f"多{r['bull']}" if r['bull'] >= r['bear'] else f"空{r['bear']}"
        adx_s = f"多{r['bull_adx']:.1f}" if r['bull_adx'] >= r['bear_adx'] else f"空{r['bear_adx']:.1f}"
        sw_s = f"多{r['bull_sw']}" if r['bull_sw'] >= r['bear_sw'] else f"空{r['bear_sw']}"
        print(f"{name:<10} {dmi_s:>8} {adx_s:>8} {sw_s:>8}")
    
    # ── 3. 推送决策 ──
    pushed = False
    if is_full_push:
        # 日间整点 → 推送完整报表
        print(f"\n📤 日间整点，推送完整报表...")
        pushed = send_report(results, now_str)
    elif alerts:
        # 任何时段有高分 → 推送预警简报
        print(f"\n📤 高分预警，推送简报...")
        pushed = send_high_alert(alerts, now_str)
    else:
        print(f"\n📄 仅记录CSV (夜间无高分)")
    
    # ── 4. 写日志 ──
    log_file = os.path.join(SCRIPT_DIR, "monitor_log.txt")
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    status = "FULL" if is_full_push else ("ALERT" if alerts else "CSV")
    with open(log_file, "a") as f:
        f.write(f"\n[{timestamp}] {period_label} {status} pushed={pushed} alerts={len(alerts)}\n")
    
    return results, alerts

if __name__ == "__main__":
    main()
