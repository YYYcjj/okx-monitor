"""
共享指标计算库
DMI/ADX, StochRSI, 摆动点, 评分系统
"""
import requests
import time

OKX_BASE = "https://www.okx.com"
RSI_PERIOD = 14
STOCH_PERIOD = 14
ATR_PERIOD = 14
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
