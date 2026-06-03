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

# ── 内联指标库 ──
OKX_BASE = "https://www.okx.com"
DIR_SCORE = {"1H": 1, "4H": 1, "1D": 2}
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
                    candles.append({"h": float(c[2]), "l": float(c[3]), "c": float(c[4])})
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
    rsi_values.append(100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi_values.append(100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
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

# ── DMI/ADX (Wilder's Directional Movement) ──
def trend_dmi(candles, period=14):
    n = len(candles)
    if n < period + 1:
        return "N/A", None, None
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    closes_arr = [c["c"] for c in candles]
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes_arr[i-1]), abs(lows[i] - closes_arr[i-1]))
    plus_dm = [0.0] * n; minus_dm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i-1]; down = lows[i-1] - lows[i]
        if up > down and up > 0: plus_dm[i] = up
        if down > up and down > 0: minus_dm[i] = down
    atr_s = sum(tr[1:period+1]) / period
    spdm = sum(plus_dm[1:period+1]) / period
    smdm = sum(minus_dm[1:period+1]) / period
    dx_vals = []
    for i in range(period+1, n):
        atr_s = (atr_s * (period - 1) + tr[i]) / period
        spdm = (spdm * (period - 1) + plus_dm[i]) / period
        smdm = (smdm * (period - 1) + minus_dm[i]) / period
        pdi = spdm / atr_s * 100 if atr_s > 0 else 0
        mdi = smdm / atr_s * 100 if atr_s > 0 else 0
        s = pdi + mdi
        dx_vals.append(abs(pdi - mdi) / s * 100 if s > 0 else 0)
    if len(dx_vals) < period:
        return "N/A", None, atr_s
    adx = sum(dx_vals[:period]) / period
    for i in range(period, len(dx_vals)):
        adx = (adx * (period - 1) + dx_vals[i]) / period
    last_pdi = spdm / atr_s * 100 if atr_s > 0 else 0
    last_mdi = smdm / atr_s * 100 if atr_s > 0 else 0
    return ("多" if last_pdi > last_mdi else "空"), adx, atr_s

# ── 摆动点方向 ──
def trend_swing(candles):
    n = len(candles)
    if n < 30: return "N/A"
    atr = calc_atr(candles)
    if atr is None: return "N/A"
    swing_highs, swing_lows = [], []
    for i in range(2, n - 2):
        h, l = candles[i]["h"], candles[i]["l"]
        if h >= candles[i-1]["h"] and h >= candles[i-2]["h"] and h >= candles[i+1]["h"] and h >= candles[i+2]["h"]:
            swing_highs.append(h)
        if l <= candles[i-1]["l"] and l <= candles[i-2]["l"] and l <= candles[i+1]["l"] and l <= candles[i+2]["l"]:
            swing_lows.append(l)
    if len(swing_highs) < 2 or len(swing_lows) < 2: return "N/A"
    h2, h1 = swing_highs[-2], swing_highs[-1]
    l2, l1 = swing_lows[-2], swing_lows[-1]
    highs_up = h1 > h2; lows_ok_ = l1 >= l2 - atr
    if highs_up and lows_ok_: return "多"
    elif not highs_up and not lows_ok_: return "空"
    return "多" if lows_ok_ else "空"

# ── 多标准评分 ──
def calc_multi_score(trends_dmi, trends_sw, srsis, adxs):
    def score_one(trends, weight_fn=None):
        bull, bear = 0, 0
        for tf in ["1H", "4H", "1D"]:
            d = trends[tf]; s = srsis[tf]; w = DIR_SCORE[tf]
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

def calc_score(trends, srsis, adx_values):
    bull, bear = 0, 0
    for tf in ["1H", "4H", "1D"]:
        d = trends[tf]; s = srsis[tf]; w = DIR_SCORE[tf]
        if d == "多": bull += w
        elif d == "空": bear += w
        if s is not None:
            if s < 20: bull += 2 if tf == "1D" else w
            elif s < 30 and tf == "1D": bull += 1
            if s > 80: bear += 2 if tf == "1D" else w
            elif s > 70 and tf == "1D": bear += 1
    return bull, bear

def adx_weight(adx):
    if adx is None: return 1.0
    if adx < 20: return 0.5
    elif adx < 25: return 0.75
    else: return 1.0

# ── EMA ──
def calc_ema(closes, period):
    """指数移动平均"""
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema

# ── MACD ──
def calc_macd(closes, fast=12, slow=26, signal=9):
    """MACD: 返回 (macd线, signal线, 柱)"""
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None, None, None
    macd_line = ema_fast - ema_slow
    
    # 需要历史MACD值计算signal线，简化：只用当前值
    # 实际需要完整序列，这里返回当前快慢线差值作为近似
    return macd_line, None, None

# ── 布林带 ──
def calc_bollinger(closes, period=20, std_dev=2):
    """布林带: 返回 (中轨, 上轨, 下轨, 带宽%, %B)"""
    if len(closes) < period:
        return None, None, None, None, None
    import math
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    std = math.sqrt(variance)
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    bw = (upper - lower) / mid * 100 if mid > 0 else 0
    last = closes[-1]
    b_pct = (last - lower) / (upper - lower) if upper != lower else 0.5
    return mid, upper, lower, bw, b_pct

# ── CCI ──
def calc_cci(candles, period=20):
    """商品通道指数 CCI"""
    if len(candles) < period:
        return None
    tp = [(c["h"] + c["l"] + c["c"]) / 3 for c in candles]
    window = tp[-period:]
    sma = sum(window) / period
    mad = sum(abs(x - sma) for x in window) / period
    if mad == 0:
        return 0
    return (tp[-1] - sma) / (0.015 * mad)

# ── 趋势方向: EMA交叉 ──
def trend_ema_cross(candles, fast=12, slow=26):
    """EMA快慢线交叉: 快线>慢线→多, 否则→空"""
    closes = [c["c"] for c in candles]
    ef = calc_ema(closes, fast)
    es = calc_ema(closes, slow)
    if ef is None or es is None:
        return "N/A"
    return "多" if ef > es else "空"

# ── 趋势方向: 布林带 ──
def trend_bollinger(candles):
    """布林带位置: %B>0.7→高位, %B<0.3→低位, 突破上/下轨"""
    closes = [c["c"] for c in candles]
    _, upper, lower, _, b_pct = calc_bollinger(closes)
    if b_pct is None:
        return "N/A"
    last = closes[-1]
    if last > upper: return "空"  # 突破上轨→超买
    if last < lower: return "多"  # 突破下轨→超卖
    if b_pct > 0.7: return "空"
    if b_pct < 0.3: return "多"
    return "N/A"  # 中性区域

# ── 趋势方向: CCI ──
def trend_cci(candles):
    """CCI方向: >100超买→预测空, <-100超卖→预测多"""
    cci = calc_cci(candles)
    if cci is None: return "N/A"
    if cci > 100: return "空"
    if cci < -100: return "多"
    if cci > 0: return "多"
    return "空"


# ── 配置 ──
SYMBOLS = [
    "APT-USDT-SWAP", "HOME-USDT-SWAP", "WLD-USDT-SWAP", "BTC-USDT-SWAP",
    "HUMA-USDT-SWAP", "HMSTR-USDT-SWAP", "PUMP-USDT-SWAP", "ORDI-USDT-SWAP"
]
ALERT_THRESHOLD = 6

# ── 项目根目录 ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 动态品种列表: 优先读取 SYMBOLS.txt（由 tools/pair_scanner.py 每天生成）
DYNAMIC_FILE = os.path.join(PROJECT_ROOT, "SYMBOLS.txt")
if os.path.exists(DYNAMIC_FILE):
    with open(DYNAMIC_FILE) as f:
        dynamic = [l.strip() for l in f if l.strip() and not l.startswith('#')]
    if dynamic:
        SYMBOLS = dynamic

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
                'ema_1h', 'ema_4h', 'ema_1d',
                'cci_1h', 'cci_4h', 'cci_1d',
                'bbp_1h', 'bbp_4h', 'bbp_1d',
                'boll_1h', 'boll_4h', 'boll_1d',
                'dmi_bull', 'dmi_bear', 'adx_bull', 'adx_bear', 'sw_bull', 'sw_bear'
            ])
        for r in results:
            if "_error" in r:
                continue
            sw = r.get("trends_sw", {})
            em = r.get("emas", {})
            cc = r.get("ccis", {})
            cd = r.get("cci_dirs", {})
            bb = r.get("bbps", {})
            bl = r.get("bolls", {})
            writer.writerow([
                ts, r['symbol'],
                r['trends'].get('1H', 'N/A'), r['trends'].get('4H', 'N/A'), r['trends'].get('1D', 'N/A'),
                sw.get('1H', 'N/A'), sw.get('4H', 'N/A'), sw.get('1D', 'N/A'),
                fmt_csv(r['adxs'].get('1H')), fmt_csv(r['adxs'].get('4H')), fmt_csv(r['adxs'].get('1D')),
                fmt_csv(r['srsis'].get('1H')), fmt_csv(r['srsis'].get('4H')), fmt_csv(r['srsis'].get('1D')),
                em.get('1H', 'N/A'), em.get('4H', 'N/A'), em.get('1D', 'N/A'),
                fmt_csv(cc.get('1H')), fmt_csv(cc.get('4H')), fmt_csv(cc.get('1D')),
                fmt_csv(bb.get('1H')), fmt_csv(bb.get('4H')), fmt_csv(bb.get('1D')),
                bl.get('1H', 'N/A'), bl.get('4H', 'N/A'), bl.get('1D', 'N/A'),
                r['bull'], r['bear'], r['bull_adx'], r['bear_adx'], r['bull_sw'], r['bear_sw']
            ])
    print(f"  📄 CSV已记录 → {csv_file}")

def fmt_csv(v):
    if v is None: return ''
    return f"{v:.1f}" if isinstance(v, float) else str(v)

# ── 时间判断 ──
GITHUB_EVENT = os.environ.get("GITHUB_EVENT_NAME", "")

def should_push_full(now):
    """日间整点±15分钟（放宽窗口） + 非push事件 → 推送完整报表"""
    h, m = now.hour, now.minute
    is_hourly = 7 <= h <= 23 and m <= 15
    is_schedule = GITHUB_EVENT in ("schedule", "workflow_dispatch", "")
    return is_hourly and is_schedule

def push_cooldown_ok():
    """全局冷却: 任意推送后2小时内不重复（持久化到 okx_data/ 以支持 Actions artifact）"""
    cooldown_file = os.path.join(PROJECT_ROOT, "okx_data", ".last_push")
    if os.path.exists(cooldown_file):
        try:
            with open(cooldown_file) as f:
                last = float(f.read().strip())
            if time.time() - last < 7200:  # 2小时
                return False
        except:
            pass
    return True

def save_cooldown():
    """推送成功后记录时间戳"""
    cooldown_file = os.path.join(PROJECT_ROOT, "okx_data", ".last_push")
    with open(cooldown_file, "w") as f:
        f.write(str(time.time()))

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
    htm += '<tr style="background:#f5f6fa;font-weight:bold;color:#666"><td style="padding:5px 3px">币种</td><td style="padding:5px 1px;text-align:center">1H</td><td style="padding:5px 1px;text-align:center">4H</td><td style="padding:5px 1px;text-align:center">1D</td><td style="padding:5px 1px;text-align:center;color:#3498db">1H SRSI</td><td style="padding:5px 1px;text-align:center;color:#3498db">4H SRSI</td><td style="padding:5px 1px;text-align:center;color:#3498db">1D SRSI</td><td style="padding:5px 1px;text-align:center;color:#e67e22">CCI</td><td style="padding:5px 1px;text-align:center;color:#8e44ad">BB%</td><td style="padding:5px 2px;text-align:center;color:#27ae60">多</td><td style="padding:5px 2px;text-align:center;color:#e74c3c">空</td></tr>'
    for i,r in enumerate(results):
        if "_error" in r: continue
        bg = "#fff" if i%2==0 else "#fafbfc"
        nm = r["symbol"].replace("-SWAP","").replace("-USDT","")
        t = r["trends"]; s = r["srsis"]
        cc = r.get("ccis", {}); bb = r.get("bbps", {})
        cc1h = f"{cc.get('1H'):.0f}" if cc.get('1H') is not None else "N/A"
        bb1h = f"{bb.get('1H'):.2f}" if bb.get('1H') is not None else "N/A"
        cc_color = "#e74c3c" if isinstance(cc.get('1H'), (int,float)) and cc['1H'] > 100 else ("#27ae60" if isinstance(cc.get('1H'), (int,float)) and cc['1H'] < -100 else "#333")
        bb_color = "#e74c3c" if isinstance(bb.get('1H'), (int,float)) and bb['1H'] > 0.7 else ("#27ae60" if isinstance(bb.get('1H'), (int,float)) and bb['1H'] < 0.3 else "#333")
        alert = r["bull"]>=ALERT_THRESHOLD or r["bear"]>=ALERT_THRESHOLD
        bd = "border-left:3px solid #e74c3c;" if alert else ""
        be_ = "🟢" if r["bull"]>=ALERT_THRESHOLD else ""
        re_ = "🔴" if r["bear"]>=ALERT_THRESHOLD else ""
        s1h,c1h,w1h=srf(s["1H"]); s4h,c4h,w4h=srf(s["4H"]); s1d,c1d,w1d=srf(s["1D"])
        htm += f'<tr style="background:{bg};{bd}"><td style="padding:5px 3px;font-weight:bold">{nm}</td><td style="padding:5px 1px;text-align:center;color:{dcol.get(t["1H"],"#999")};font-weight:bold;font-size:11px">{t["1H"]}</td><td style="padding:5px 1px;text-align:center;color:{dcol.get(t["4H"],"#999")};font-weight:bold;font-size:11px">{t["4H"]}</td><td style="padding:5px 1px;text-align:center;color:{dcol.get(t["1D"],"#999")};font-weight:bold;font-size:11px">{t["1D"]}</td><td style="padding:5px 1px;text-align:center;color:{c1h};font-weight:{w1h}">{s1h}</td><td style="padding:5px 1px;text-align:center;color:{c4h};font-weight:{w4h}">{s4h}</td><td style="padding:5px 1px;text-align:center;color:{c1d};font-weight:{w1d}">{s1d}</td><td style="padding:5px 1px;text-align:center;color:{cc_color};font-size:11px">{cc1h}</td><td style="padding:5px 1px;text-align:center;color:{bb_color};font-size:11px">{bb1h}</td><td style="padding:5px 2px;text-align:center;font-weight:bold;color:#27ae60">{be_}{r["bull"]}</td><td style="padding:5px 2px;text-align:center;font-weight:bold;color:#e74c3c">{re_}{r["bear"]}</td></tr>'
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
    emas = {}; ccis = {}; cci_dirs = {}; bbps = {}; bolls = {}; macds = {}
    for tf_label, bar in [("1H", "1H"), ("4H", "4H"), ("1D", "1D")]:
        candles = fetch_ohlcv(sym, bar)
        if not candles or len(candles) < 20:
            trends[tf_label] = "N/A"; trends_sw[tf_label] = "N/A"
            srsis[tf_label] = None; adxs[tf_label] = None
            emas[tf_label] = "N/A"; ccis[tf_label] = None; cci_dirs[tf_label] = "N/A"
            bbps[tf_label] = None; bolls[tf_label] = "N/A"; macds[tf_label] = None
            continue
        closes = [c["c"] for c in candles]
        d, adx, _ = trend_dmi(candles)
        sw = trend_swing(candles)
        sr = calc_stoch_rsi(closes)
        ea = trend_ema_cross(candles)
        cci_val = calc_cci(candles)
        cci_dir_val = trend_cci(candles)
        _, _, _, _, bb_b = calc_bollinger(closes)
        boll_dir = trend_bollinger(candles)
        macd_val, _, _ = calc_macd(closes)
        trends[tf_label] = d; trends_sw[tf_label] = sw
        srsis[tf_label] = round(sr, 1) if sr is not None else None
        adxs[tf_label] = round(adx, 1) if adx is not None else None
        emas[tf_label] = ea
        ccis[tf_label] = round(cci_val, 0) if cci_val is not None else None
        cci_dirs[tf_label] = cci_dir_val
        bbps[tf_label] = round(bb_b, 2) if bb_b is not None else None
        bolls[tf_label] = boll_dir
        macds[tf_label] = round(macd_val, 4) if macd_val is not None else None
        time.sleep(0.15)
    (dmi_b, dmi_s), (adx_b, adx_s), (sw_b, sw_s) = calc_multi_score(trends, trends_sw, srsis, adxs)
    row["trends"] = trends; row["trends_sw"] = trends_sw
    row["srsis"] = srsis; row["adxs"] = adxs
    row["emas"] = emas; row["ccis"] = ccis; row["cci_dirs"] = cci_dirs
    row["bbps"] = bbps; row["bolls"] = bolls; row["macds"] = macds
    row["bull"] = dmi_b; row["bear"] = dmi_s
    row["bull_adx"] = adx_b; row["bear_adx"] = adx_s
    row["bull_sw"] = sw_b; row["bear_sw"] = sw_s
    return row

# ── 格式化输出 ──
def fmt_srsi(v):
    return f"{v:.1f}" if v is not None else "N/A"

def fmt_val(v):
    if v is None: return "N/A"
    if isinstance(v, float):
        if abs(v) < 10: return f"{v:.2f}"
        return f"{v:.0f}"
    return str(v)

def fmt_line(row):
    name = row["symbol"].replace("-SWAP", "").replace("-USDT", "")
    t = row["trends"]; s = row["srsis"]; bull, bear = row["bull"], row["bear"]
    b_flag = "🟢" if bull >= ALERT_THRESHOLD else "  "
    r_flag = "🔴" if bear >= ALERT_THRESHOLD else "  "
    cc = row.get("ccis", {}); bb = row.get("bbps", {})
    return (f"{name:<10} {t['1H']:^4} {t['4H']:^4} {t['1D']:^4} "
            f"{fmt_srsi(s['1H']):>7} {fmt_srsi(s['4H']):>7} {fmt_srsi(s['1D']):>7} "
            f"{fmt_val(cc.get('1H')):>7} {fmt_val(bb.get('1H')):>6}  "
            f"{b_flag}{bull:<4}   {r_flag}{bear}")

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
    
    # 多空分开排序
    results.sort(key=lambda r: max(r.get("bull",0), r.get("bear",0)), reverse=True)
    
    if alerts:
        print(f"\n⚠️ 高分预警（≥{ALERT_THRESHOLD}分）：")
        for a in alerts:
            emoji = "🟢" if a["type"]=="多" else "🔴"
            name = a["symbol"].replace("-SWAP","").replace("-USDT","")
            print(f"  {emoji} {name} {a['type']}分={a['score']}")
    
    print(f"\n{'币种':<10} {'1H':^4} {'4H':^4} {'1D':^4} {'1H SRSI':>7} {'4H SRSI':>7} {'1D SRSI':>7} {'1H CCI':>7} {'1H BB':>6}   {'多分':>4}  {'空分':>4}")
    print("-" * 92)
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
    can_push = push_cooldown_ok()
    if is_full_push and can_push:
        print(f"\n📤 日间整点，推送完整报表...")
        pushed = send_report(results, now_str)
        if pushed:
            save_cooldown()
    elif alerts and can_push:
        print(f"\n📤 高分预警，推送简报...")
        pushed = send_high_alert(alerts, now_str)
        if pushed:
            save_cooldown()
    else:
        reason = "夜间/非整点" if not is_full_push else ("冷却中(2h)" if not can_push and alerts else "无预警")
        print(f"\n📄 仅记录CSV ({reason})")
    
    log_file = os.path.join(PROJECT_ROOT, "monitor_log.txt")
    status = "FULL" if is_full_push else ("ALERT" if alerts else "CSV")
    with open(log_file, "a") as f:
        f.write(f"\n[{now.strftime('%Y-%m-%d %H:%M')}] {period_label} {status} pushed={pushed} alerts={len(alerts)}\n")
    return results, alerts

if __name__ == "__main__":
    main()
