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
DIR_SCORE = {"1H": 1, "4H": 2, "1D": 3}
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

# ── StochRSI (K+D)/2, K经SMA(3)平滑匹配TradingView ──
def calc_stoch_rsi(closes, rsi_period=14, stoch_period=14, smooth_k=3):
    _, rsi_values = calc_rsi(closes, rsi_period)
    if not rsi_values or len(rsi_values) < stoch_period + smooth_k:
        return None
    # Step 1: Stochastic %K_raw
    k_raw = []
    for i in range(stoch_period - 1, len(rsi_values)):
        w = rsi_values[i - stoch_period + 1 : i + 1]
        lo, hi = min(w), max(w)
        k_raw.append(50 if hi == lo else (rsi_values[i] - lo) / (hi - lo) * 100)
    # Step 2: %K = SMA(K_raw, 3)  ← TradingView同款
    k_vals = []
    for i in range(smooth_k - 1, len(k_raw)):
        k_vals.append(sum(k_raw[i - smooth_k + 1 : i + 1]) / smooth_k)
    if len(k_vals) < 4:
        return k_vals[-1] if k_vals else None
    # Step 3: %D = SMA(%K, 3), 返回 (K+D)/2
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
    if highs_up and lows_ok_: return "多"       # HH+HL → 上升趋势
    if not highs_up and not lows_ok_: return "空"  # LH+LL → 下降趋势
    # 混合信号（HH+LL 或 LH+HL）：用EMA交叉判断更可能的方向
    ema_dir = trend_ema_cross(candles)
    return ema_dir if ema_dir != "N/A" else ("多" if highs_up else "空")