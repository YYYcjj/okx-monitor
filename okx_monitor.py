#!/usr/bin/env python3
"""
OKX 策略监控 v2.0
- 方向: 摆动高低点 + 1×ATR 容差
- StochRSI: (K+D)/2, Wilder平滑
- 评分: 方向分 1H=1, 4H=1, 1D=2 + SRSI极端值加分
- 预警: 多/空分 ≥6 → Server酱推送到微信
"""
import warnings
warnings.filterwarnings("ignore")
import requests
import time
import json
import os
import sys
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

# ── 方向判断: 摆动高低点 + 1×ATR 容差 ──
def trend_swing(candles):
    """
    多: 新峰 > 旧峰 且 新谷 ≥ 旧谷 - 1×ATR
    空: 新峰 < 旧峰 且 新谷 < 旧谷 - 1×ATR
    中: 矛盾状态
    """
    n = len(candles)
    if n < 30:
        return "N/A", None
    
    atr = calc_atr(candles)
    if atr is None:
        return "N/A", None
    
    # 找摆动点 (前后各2根确认)
    swing_highs = []
    swing_lows = []
    for i in range(2, n - 2):
        h = candles[i]["h"]
        l = candles[i]["l"]
        if (h >= candles[i-1]["h"] and h >= candles[i-2]["h"] and
            h >= candles[i+1]["h"] and h >= candles[i+2]["h"]):
            swing_highs.append(h)
        if (l <= candles[i-1]["l"] and l <= candles[i-2]["l"] and
            l <= candles[i+1]["l"] and l <= candles[i+2]["l"]):
            swing_lows.append(l)
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "N/A", atr
    
    h2, h1 = swing_highs[-2], swing_highs[-1]
    l2, l1 = swing_lows[-2], swing_lows[-1]
    
    highs_up = h1 > h2
    lows_ok = l1 >= l2 - atr  # 1ATR容差
    
    if highs_up and lows_ok:
        return "多", atr
    elif not highs_up and not lows_ok:
        return "空", atr
    else:
        # 矛盾: 以谷为准
        return "多" if lows_ok else "空", atr

# ── 评分 ──
DIR_SCORE = {"1H": 1, "4H": 1, "1D": 2}

def calc_score(trends, srsis):
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
            # SRSI加分，跟方向无关
            if s < 20:
                bull += 2 if tf == "1D" else w
            elif s < 30 and tf == "1D":
                bull += 1
            if s > 80:
                bear += 2 if tf == "1D" else w
            elif s > 70 and tf == "1D":
                bear += 1
    
    return bull, bear

# ── 通知推送 ──
def send_report(full_text, now_str):
    """优先 PushPlus，其次企微。每次都推送完整报表"""
    if PUSHPLUS_TOKEN:
        return _send_pushplus(full_text, now_str)
    if WECOM_WEBHOOK:
        return _send_wecom(full_text, now_str)
    return False

def _send_pushplus(full_text, now_str):
    """PushPlus推送到微信，免费200条/天"""
    url = "http://www.pushplus.plus/send"
    
    # 提取预警摘要做标题
    lines = full_text.split("\n")
    alert_count = sum(1 for l in lines if l.strip().startswith("🟢") or l.strip().startswith("🔴"))
    
    # markdown 格式的全量推文
    content = f"## OKX 策略扫描 {now_str}\n\n"
    
    # 预警部分
    alert_lines = [l for l in lines if "分=" in l and ("🟢" in l or "🔴" in l)]
    if alert_lines:
        content += "**⚠️ 高分预警：**\n"
        for l in alert_lines:
            content += f"- {l.strip()}\n"
        content += "\n"
    
    # 表格
    content += "```\n"
    in_table = False
    for l in lines:
        if "═══" in l or "算法:" in l or "评分:" in l:
            continue
        if "1H" in l and "4H" in l and "SRSI" in l:
            in_table = True
        if in_table:
            content += l + "\n"
    content += "```\n\n> 评分: 方向分(1H=1 4H=1 1D=2) + SRSI极端值加分 | ≥6预警"
    
    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": f"OKX {alert_count}预警" if alert_count else "OKX 策略扫描",
        "content": content,
        "template": "markdown"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        r = resp.json()
        if r.get("code") == 200:
            print(f"  ✅ PushPlus已推送 ({alert_count}个预警)")
            return True
        else:
            print(f"  ❌ PushPlus推送失败: {r}")
            return False
    except Exception as e:
        print(f"  ❌ PushPlus推送异常: {e}")
        return False

def _send_wecom(full_text, now_str):
    """企微机器人推送（备用）"""
    url = WECOM_WEBHOOK
    content = full_text.replace("\n", "\n> ")
    content = f"## OKX 策略扫描 {now_str}\n> {content}"
    
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

# ── 单品种扫描 ──
def scan_symbol(sym):
    row = {"symbol": sym}
    trends = {}
    srsis = {}
    atrs = {}
    
    for tf_label, bar in [("1H", "1H"), ("4H", "4H"), ("1D", "1D")]:
        candles = fetch_ohlcv(sym, bar)
        if not candles or len(candles) < 20:
            trends[tf_label] = "N/A"
            srsis[tf_label] = None
            atrs[tf_label] = None
            continue
        
        closes = [c["c"] for c in candles]
        d, atr = trend_swing(candles)
        sr = calc_stoch_rsi(closes)
        
        trends[tf_label] = d
        srsis[tf_label] = round(sr, 1) if sr is not None else None
        atrs[tf_label] = atr
        time.sleep(0.15)
    
    bull, bear = calc_score(trends, srsis)
    row["trends"] = trends
    row["srsis"] = srsis
    row["atrs"] = atrs
    row["bull"] = bull
    row["bear"] = bear
    
    return row

# ── 格式化输出 ──
def fmt_srsi(v):
    return f"{v:.1f}" if v is not None else "N/A"

def fmt_line(row):
    name = row["symbol"].replace("-SWAP", "").replace("-USDT", "")
    t = row["trends"]
    s = row["srsis"]
    bull, bear = row["bull"], row["bear"]
    
    b_flag = "🟢" if bull >= ALERT_THRESHOLD else "  "
    r_flag = "🔴" if bear >= ALERT_THRESHOLD else "  "
    
    return (f"{name:<10} {t['1H']:^4} {t['4H']:^4} {t['1D']:^4} "
            f"{fmt_srsi(s['1H']):>8} {fmt_srsi(s['4H']):>8} {fmt_srsi(s['1D']):>8}  "
            f"{b_flag}{bull:<7} {r_flag}{bear}")

# ── 主函数 ──
def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    now_str = now.strftime("%Y-%m-%d %H:%M CST")
    
    # 扫描
    results = []
    for sym in SYMBOLS:
        try:
            row = scan_symbol(sym)
            results.append(row)
        except Exception as e:
            name = sym.replace("-SWAP", "").replace("-USDT", "")
            results.append({
                "symbol": sym, "trends": {"1H":"ERR","4H":"ERR","1D":"ERR"},
                "srsis": {"1H":None,"4H":None,"1D":None},
                "atrs": {"1H":None,"4H":None,"1D":None},
                "bull": 0, "bear": 0, "_error": str(e)
            })
    
    # 高分预警
    alerts = []
    for r in results:
        if r["bull"] >= ALERT_THRESHOLD:
            alerts.append({
                "type": "多", "symbol": r["symbol"], "score": r["bull"],
                "trends": r["trends"],
                "srsi_1h": fmt_srsi(r["srsis"]["1H"]),
                "srsi_4h": fmt_srsi(r["srsis"]["4H"]),
                "srsi_1d": fmt_srsi(r["srsis"]["1D"]),
            })
        if r["bear"] >= ALERT_THRESHOLD:
            alerts.append({
                "type": "空", "symbol": r["symbol"], "score": r["bear"],
                "trends": r["trends"],
                "srsi_1h": fmt_srsi(r["srsis"]["1H"]),
                "srsi_4h": fmt_srsi(r["srsis"]["4H"]),
                "srsi_1d": fmt_srsi(r["srsis"]["1D"]),
            })
    
    # 构建输出
    output = []
    if alerts:
        output.append("⚠️ 高分预警（≥6分）：")
        for a in alerts:
            emoji = "🟢" if a["type"] == "多" else "🔴"
            name = a["symbol"].replace("-SWAP", "").replace("-USDT", "")
            output.append(f"  {emoji} {name} {a['type']}分={a['score']}")
        output.append("")
    
    output.append(f"═══ OKX 策略扫描 {now_str} ═══")
    output.append("")
    output.append(f"{'币种':<10} {'1H':^4} {'4H':^4} {'1D':^4} {'1H SRSI':>8} {'4H SRSI':>8} {'1D SRSI':>8}   多分      空分")
    output.append("-" * 78)
    
    for r in results:
        if "_error" in r:
            name = r["symbol"].replace("-SWAP", "").replace("-USDT", "")
            output.append(f"{name:<10} 获取失败: {r['_error']}")
        else:
            output.append(fmt_line(r))
    
    output.append("")
    output.append("算法: 摆动高低点+1ATR容差 | StochRSI (K+D)/2 Wilder平滑")
    output.append("评分: 方向分(1H=1 4H=1 1D=2) + SRSI极端值加分 | ≥6预警")
    
    text = "\n".join(output)
    print(text)
    
    # 写日志
    log_file = os.path.join(SCRIPT_DIR, "monitor_log.txt")
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    with open(log_file, "a") as f:
        f.write(f"\n\n{'='*60}\n")
        f.write(f"[{timestamp}]\n")
        f.write(text)
    
    # 推送完整报表
    send_report(text, now_str)
    
    return results, alerts

if __name__ == "__main__":
    main()
