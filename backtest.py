#!/usr/bin/env python3
"""
OKX 策略回测 v1.0
拉取近60天历史K线，逐小时模拟策略状态，对比三套评分标准的预测准确率
"""
import warnings
warnings.filterwarnings("ignore")
import requests
import time
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ── 配置 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SYMBOLS = [
    "APT-USDT", "HOME-USDT-SWAP", "WLD-USDT-SWAP", "BTC-USDT",
    "HUMA-USDT", "HMSTR-USDT", "PUMP-USDT", "ORDI-USDT"
]
OKX_BASE = "https://www.okx.com"
BACKTEST_DAYS = 60
CACHE_DIR = os.path.join(SCRIPT_DIR, "okx_data", "backtest_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ── 数据获取 ──
def fetch_ohlcv(symbol, bar, limit=300, after=None):
    """拉取历史K线，支持翻页"""
    url = f"{OKX_BASE}/api/v5/market/candles"
    params = {"instId": symbol, "bar": bar, "limit": limit}
    if after:
        params["after"] = after
    try:
        resp = requests.get(url, params=params, timeout=20)
        d = resp.json()
        if d.get("code") == "0":
            candles = []
            for c in d["data"]:
                ts = int(c[0])
                candles.append({
                    "ts": ts,
                    "o": float(c[1]), "h": float(c[2]),
                    "l": float(c[3]), "c": float(c[4])
                })
            candles.sort(key=lambda x: x["ts"])
            return candles
        return None
    except Exception as e:
        print(f"  ⚠️ 获取失败 {symbol} {bar}: {e}")
        return None

def fetch_historical(symbol, bar, days=60):
    """拉取完整历史数据并缓存"""
    cache_file = os.path.join(CACHE_DIR, f"{symbol.replace('/','_')}_{bar}.json")
    
    # 尝试从缓存读取
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            cached = json.load(f)
        newest = max(c["ts"] for c in cached) if cached else 0
        # 检查是否够新（最后一根在24小时内）
        now_ms = int(datetime.now().timestamp() * 1000)
        if now_ms - newest < 24 * 3600 * 1000:
            print(f"  📦 {symbol} {bar}: 使用缓存 ({len(cached)}根)")
            return cached
    
    print(f"  ⬇️ {symbol} {bar}: 拉取中...")
    all_candles = []
    after = None
    pages = 0
    
    while pages < 10:  # 最多10页
        candles = fetch_ohlcv(symbol, bar, limit=300, after=after)
        if not candles:
            break
        all_candles.extend(candles)
        pages += 1
        if len(candles) < 300:
            break
        after = str(candles[0]["ts"])
        time.sleep(0.3)
    
    # 去重排序
    seen = set(); unique = []
    for c in sorted(all_candles, key=lambda x: x["ts"]):
        if c["ts"] not in seen:
            seen.add(c["ts"]); unique.append(c)
    
    # 缓存
    with open(cache_file, 'w') as f:
        json.dump(unique, f)
    
    # 只保留需要的天数
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=days+5)).timestamp() * 1000)
    unique = [c for c in unique if c["ts"] >= cutoff]
    
    print(f"  ✅ {symbol} {bar}: {len(unique)}根K线")
    return unique

# ── 指标计算 (与 okx_monitor.py 相同) ──
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

def trend_dmi(candles, period=14):
    n = len(candles)
    if n < period + 1:
        return "N/A", None
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
        return "N/A", None
    adx = sum(dx_vals[:period]) / period
    for i in range(period, len(dx_vals)):
        adx = (adx * (period - 1) + dx_vals[i]) / period
    
    last_pdi = spdm / atr_s * 100 if atr_s > 0 else 0
    last_mdi = smdm / atr_s * 100 if atr_s > 0 else 0
    return ("多" if last_pdi > last_mdi else "空"), adx

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

DIR_SCORE = {"1H": 1, "4H": 1, "1D": 2}

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

# ── 辅助函数 ──
def candles_before(data, ts):
    """返回 ts 之前的K线"""
    return [c for c in data if c["ts"] <= ts]

def candles_at(data, target_ts, bar_seconds):
    """找到 time <= target_ts 的最近K线"""
    best = None
    for c in data:
        if c["ts"] <= target_ts:
            best = c
        else:
            break
    return best

def get_price_at(data_1h, ts):
    """获取指定时间的收盘价"""
    for c in reversed(data_1h):
        if c["ts"] <= ts:
            return c["c"]
    return None

# ── 回测引擎 ──
def backtest_symbol(sym, data_1h, data_4h, data_1d):
    """逐小时回测，记录≥6分信号及其结果"""
    print(f"\n{'='*60}")
    print(f"🔬 回测 {sym}")
    
    signals = []
    min_1h = min(c["ts"] for c in data_1h) if data_1h else 0
    max_1h = max(c["ts"] for c in data_1h) if data_1h else 0
    min_4h = min(c["ts"] for c in data_4h) if data_4h else 0
    max_4h = max(c["ts"] for c in data_4h) if data_4h else 0
    min_1d = min(c["ts"] for c in data_1d) if data_1d else 0
    max_1d = max(c["ts"] for c in data_1d) if data_1d else 0
    
    # 回测起点：需要足够的历史数据计算指标
    warmup = max(min_1h + 50 * 3600000, min_4h + 50 * 14400000, min_1d + 50 * 86400000)
    
    # 回测终点：留出24小时检验空间
    end = max_1h - 24 * 3600000
    if warmup >= end:
        print(f"  ⚠️ 数据不足，跳过")
        return []
    
    # 从 warmup 走到 end，每小时一步
    current = warmup - (warmup % 3600000)  # 对齐到整点
    
    step = 0; progress_mark = 0
    total_steps = (end - current) // 3600000 + 1
    
    while current <= end:
        step += 1
        pct = step * 100 // total_steps
        if pct >= progress_mark + 10:
            progress_mark = pct
            print(f"  进度 {pct}% ({step}/{total_steps})")
        
        # ── 获取当前时间点可用的数据 ──
        c_1h = candles_before(data_1h, current)
        c_4h = candles_before(data_4h, current)
        c_1d = candles_before(data_1d, current)
        
        if len(c_1h) < 50 or len(c_4h) < 50 or len(c_1d) < 50:
            current += 3600000
            continue
        
        # ── 计算指标 ──
        new_1h = c_1h[-200:]  # 最近200根
        new_4h = c_4h[-200:]
        new_1d = c_1d[-200:]
        
        closes_1h = [c["c"] for c in new_1h]
        closes_4h = [c["c"] for c in new_4h]
        closes_1d = [c["c"] for c in new_1d]
        
        dmi_1h, adx_1h = trend_dmi(new_1h)
        dmi_4h, adx_4h = trend_dmi(new_4h)
        dmi_1d, adx_1d = trend_dmi(new_1d)
        
        sw_1h = trend_swing(new_1h)
        sw_4h = trend_swing(new_4h)
        sw_1d = trend_swing(new_1d)
        
        srsi_1h = calc_stoch_rsi(closes_1h)
        srsi_4h = calc_stoch_rsi(closes_4h)
        srsi_1d = calc_stoch_rsi(closes_1d)
        
        trends_dmi = {"1H": dmi_1h, "4H": dmi_4h, "1D": dmi_1d}
        trends_sw = {"1H": sw_1h, "4H": sw_4h, "1D": sw_1d}
        srsis = {"1H": round(srsi_1h, 1) if srsi_1h else None,
                 "4H": round(srsi_4h, 1) if srsi_4h else None,
                 "1D": round(srsi_1d, 1) if srsi_1d else None}
        adxs = {"1H": round(adx_1h, 1) if adx_1h else None,
                "4H": round(adx_4h, 1) if adx_4h else None,
                "1D": round(adx_1d, 1) if adx_1d else None}
        
        (dmi_b, dmi_s), (adx_b, adx_s), (sw_b, sw_s) = calc_multi_score(trends_dmi, trends_sw, srsis, adxs)
        
        # ── 记录 ≥6 分信号 ──
        entry_price = get_price_at(data_1h, current)
        if entry_price is None:
            current += 3600000
            continue
        
        for std, bull, bear in [("DMI纯分", dmi_b, dmi_s), ("ADX加权", int(adx_b), int(adx_s)), ("摆动点", sw_b, sw_s)]:
            score = bull if bull >= bear else bear
            direction = "多" if bull >= bear else "空"
            
            if score >= 6:
                # 检查不同时间窗口的价格变化
                signal = {
                    "symbol": sym,
                    "time": current,
                    "time_str": datetime.fromtimestamp(current/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "std": std,
                    "direction": direction,
                    "score": score,
                    "entry": entry_price,
                    "dmi_1h": dmi_1h, "dmi_4h": dmi_4h, "dmi_1d": dmi_1d,
                    "srsi_1h": srsi_1h, "srsi_4h": srsi_4h, "srsi_1d": srsi_1d,
                }
                
                for label, offset_h in [("4H", 4), ("12H", 12), ("24H", 24)]:
                    exit_price = get_price_at(data_1h, current + offset_h * 3600000)
                    if exit_price:
                        pct = (exit_price - entry_price) / entry_price * 100
                        if direction == "多":
                            signal[f"win_{label}"] = pct > 0
                            signal[f"pct_{label}"] = pct
                        else:
                            signal[f"win_{label}"] = pct < 0
                            signal[f"pct_{label}"] = -pct  # 空头方向翻转
                        signal[f"exit_{label}"] = exit_price
                    else:
                        signal[f"win_{label}"] = None
                        signal[f"exit_{label}"] = None
                
                signals.append(signal)
        
        current += 3600000  # 下一小时
    
    print(f"  ✅ {sym}: {len(signals)} 个信号")
    return signals

# ── 结果分析 ──
def analyze(all_signals):
    if not all_signals:
        print("\n❌ 没有信号数据")
        return
    
    print(f"\n{'='*80}")
    print(f"📊 回测结果汇总: {BACKTEST_DAYS}天 · {len(set(s['symbol'] for s in all_signals))}品种 · {len(all_signals)}个信号")
    print(f"{'='*80}")
    
    # ── 总体胜率 ──
    for horizon in ["4H", "12H", "24H"]:
        print(f"\n── 胜率对比 ({horizon}) ──")
        
        # 表头
        header = f"{'标准':<12} {'信号数':>6} {'胜数':>6} {'胜率':>7} {'平均收益%':>10} {'多胜率':>8} {'空胜率':>8}"
        print(header)
        print("-" * len(header))
        
        for std in ["DMI纯分", "ADX加权", "摆动点"]:
            sigs = [s for s in all_signals if s["std"] == std and s.get(f"win_{horizon}") is not None]
            if not sigs:
                continue
            
            wins = [s for s in sigs if s[f"win_{horizon}"]]
            win_rate = len(wins) / len(sigs) * 100
            avg_pct = sum(s[f"pct_{horizon}"] for s in sigs) / len(sigs)
            
            long_sigs = [s for s in sigs if s["direction"] == "多"]
            long_wins = [s for s in long_sigs if s[f"win_{horizon}"]]
            short_sigs = [s for s in sigs if s["direction"] == "空"]
            short_wins = [s for s in short_sigs if s[f"win_{horizon}"]]
            
            lr = len(long_wins) / len(long_sigs) * 100 if long_sigs else 0
            sr = len(short_wins) / len(short_sigs) * 100 if short_sigs else 0
            
            print(f"{std:<12} {len(sigs):>6} {len(wins):>6} {win_rate:>6.1f}% {avg_pct:>9.2f}% {lr:>7.1f}% {sr:>7.1f}%")
    
    # ── 按分数段胜率 ──
    print(f"\n── 按分数段胜率 (24H, DMI纯分) ──")
    dmi_sigs = [s for s in all_signals if s["std"] == "DMI纯分" and s.get("win_24H") is not None]
    for score_range, label in [([6], "6分"), ([7], "7分"), ([8,9,10,11,12], "≥8分")]:
        sigs = [s for s in dmi_sigs if s["score"] in score_range]
        if sigs:
            wins = [s for s in sigs if s["win_24H"]]
            avg = sum(s["pct_24H"] for s in sigs) / len(sigs)
            print(f"  {label}: {len(sigs)}信号, 胜率 {len(wins)/len(sigs)*100:.1f}%, 平均收益 {avg:.2f}%")
    
    # ── 按品种胜率 ──
    print(f"\n── 按品种胜率 (24H, DMI纯分) ──")
    for sym in SYMBOLS:
        sigs = [s for s in dmi_sigs if s["symbol"] == sym and s.get("win_24H") is not None]
        if sigs:
            wins = [s for s in sigs if s["win_24H"]]
            name = sym.replace("-SWAP","").replace("-USDT","")
            print(f"  {name:<8}: {len(sigs):>3}信号, 胜率 {len(wins)/len(sigs)*100:>5.1f}%")
    
    # ── SRSI 极端值胜率 ──
    print(f"\n── SRSI 极端值胜率 (24H, DMI纯分) ──")
    dmi_sigs_24h = [s for s in dmi_sigs if s.get("win_24H") is not None]
    
    for label, srsi_check in [
        ("1D SRSI<20", lambda s: s.get("srsi_1d") is not None and s["srsi_1d"] < 20),
        ("4H SRSI<20", lambda s: s.get("srsi_4h") is not None and s["srsi_4h"] < 20),
        ("1D SRSI>80", lambda s: s.get("srsi_1d") is not None and s["srsi_1d"] > 80),
        ("4H SRSI>80", lambda s: s.get("srsi_4h") is not None and s["srsi_4h"] > 80),
    ]:
        sigs = [s for s in dmi_sigs_24h if srsi_check(s)]
        if sigs:
            wins = [s for s in sigs if s["win_24H"]]
            print(f"  {label:<14}: {len(sigs):>3}信号, 胜率 {len(wins)/len(sigs)*100:>5.1f}%")
    
    # ── 写入详细 CSV ──
    csv_file = os.path.join(SCRIPT_DIR, "okx_data", "backtest_results.csv")
    with open(csv_file, 'w') as f:
        keys = ["symbol","time_str","std","direction","score","entry",
                "dmi_1h","dmi_4h","dmi_1d","srsi_1h","srsi_4h","srsi_1d",
                "win_4H","pct_4H","win_12H","pct_12H","win_24H","pct_24H"]
        f.write(",".join(keys) + "\n")
        for s in all_signals:
            row = []
            for k in keys:
                v = s.get(k)
                if v is None: row.append("")
                elif isinstance(v, bool): row.append("1" if v else "0")
                elif isinstance(v, float): row.append(f"{v:.4f}")
                else: row.append(str(v))
            f.write(",".join(row) + "\n")
    print(f"\n📄 详细结果: {csv_file}")

# ── 主流程 ──
def main():
    print("="*60)
    print(f"📊 OKX 策略回测 - 近{BACKTEST_DAYS}天")
    print("="*60)
    print()
    
    # ── 1. 拉取数据 ──
    print("【1/3】拉取历史数据...")
    all_data = {}
    for sym in SYMBOLS:
        d1 = fetch_historical(sym, "1H", BACKTEST_DAYS)
        d4 = fetch_historical(sym, "4H", BACKTEST_DAYS)
        dd = fetch_historical(sym, "1D", BACKTEST_DAYS)
        all_data[sym] = (d1, d4, dd)
        time.sleep(0.3)
    
    # ── 2. 回测 ──
    print("\n【2/3】逐小时回测...")
    all_signals = []
    for sym in SYMBOLS:
        d1, d4, dd = all_data[sym]
        signals = backtest_symbol(sym, d1, d4, dd)
        all_signals.extend(signals)
    
    # ── 3. 分析 ──
    print(f"\n【3/3】结果分析...")
    analyze(all_signals)

if __name__ == "__main__":
    main()
