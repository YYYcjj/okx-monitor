"""
OKX 策略回测引擎 v1.0
参数化回测：DMI+StochRSI评分 + SuperTrend入场 + 关键区间止盈
"""
import requests
import time
import math
from datetime import datetime, timezone, timedelta
import json
import itertools

OKX_BASE = "https://www.okx.com"
CST = timezone(timedelta(hours=8))

# ═══ 品种 ═══
SYMBOLS = [
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP",
    "APT-USDT-SWAP", "SUI-USDT-SWAP", "WLD-USDT-SWAP",
    "ORDI-USDT-SWAP", "DASH-USDT-SWAP",
    "HOME-USDT-SWAP", "HUMA-USDT-SWAP", "HMSTR-USDT-SWAP",
    "PUMP-USDT-SWAP", "APR-USDT-SWAP", "GALA-USDT-SWAP",
    "GMT-USDT-SWAP", "PI-USDT-SWAP",
]

# ═══ 数据获取 ═══
def fetch_ohlcv(symbol, bar="1H", limit=300, before=None):
    url = f"{OKX_BASE}/api/v5/market/candles"
    params = {"instId": symbol, "bar": bar, "limit": limit}
    if before:
        params["before"] = before
    for _ in range(3):
        try:
            resp = requests.get(url, params=params, timeout=15, proxies={"http": None, "https": None})
            d = resp.json()
            if d.get("code") == "0":
                candles = []
                for c in d["data"]:
                    candles.append({
                        "h": float(c[2]), "l": float(c[3]),
                        "c": float(c[4]), "o": float(c[1]),
                        "ts": int(c[0]), "vol": float(c[5]),
                    })
                candles.reverse()
                return candles
        except Exception:
            time.sleep(1)
    return None


def fetch_extended(symbol, bars=1000):
    """拉取超过300根K线"""
    all_candles = []
    before = None
    while len(all_candles) < bars:
        batch = fetch_ohlcv(symbol, "1H", limit=300, before=before)
        if not batch:
            break
        if not all_candles:
            all_candles = batch
        else:
            # 去重
            new = [c for c in batch if c["ts"] < all_candles[0]["ts"]]
            all_candles = new + all_candles
        if len(batch) < 300:
            break
        before = str(all_candles[0]["ts"])
        time.sleep(0.3)
    return all_candles


# ═══ 指标计算 ═══
def calc_rsi(closes, period=14):
    n = len(closes)
    if n < period + 1:
        return [None] * n
    gains, losses = [], []
    for i in range(1, n):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi = [None] * period
    rsi.append(100 if avg_loss == 0 else 100 - 100/(1 + avg_gain/avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain*(period-1) + gains[i]) / period
        avg_loss = (avg_loss*(period-1) + losses[i]) / period
        rsi.append(100 if avg_loss == 0 else 100 - 100/(1 + avg_gain/avg_loss))
    return rsi


def calc_atr(candles, period=14):
    n = len(candles)
    if n < period + 1:
        return [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(candles[i]["h"] - candles[i]["l"],
                    abs(candles[i]["h"] - candles[i-1]["c"]),
                    abs(candles[i]["l"] - candles[i-1]["c"]))
    atr = [0.0] * n
    atr[period] = sum(tr[1:period+1]) / period
    for i in range(period+1, n):
        atr[i] = (atr[i-1]*(period-1) + tr[i]) / period
    return atr


def calc_dmi(candles, period=14):
    n = len(candles)
    if n < period + 1:
        return [0] * n
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    closes = [c["c"] for c in candles]
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down
    atr_s = sum(tr[1:period+1]) / period
    spdm = sum(plus_dm[1:period+1]) / period
    smdm = sum(minus_dm[1:period+1]) / period
    dmi_dir = [0] * n
    for i in range(period+1, n):
        atr_s = (atr_s*(period-1) + tr[i]) / period
        spdm = (spdm*(period-1) + plus_dm[i]) / period
        smdm = (smdm*(period-1) + minus_dm[i]) / period
        dmi_dir[i] = 1 if (spdm > smdm) else -1
    return dmi_dir


def calc_stoch_rsi(rsi_vals, stoch_period=14, smooth_k=3):
    n = len(rsi_vals)
    srsi = [None] * n
    valid_start = next((i for i in range(n) if rsi_vals[i] is not None), n) + stoch_period
    if valid_start >= n:
        return srsi
    k_raw = []
    for i in range(valid_start, n):
        w = rsi_vals[i-stoch_period+1:i+1]
        lo, hi = min(w), max(w)
        k_raw.append(50 if hi == lo else (rsi_vals[i]-lo)/(hi-lo)*100)
    k_smooth = []
    for i in range(smooth_k-1, len(k_raw)):
        k_smooth.append(sum(k_raw[i-smooth_k+1:i+1])/smooth_k)
    for i in range(len(k_smooth)-3, len(k_smooth)):
        if i < 0:
            continue
        idx = valid_start + i + smooth_k - 1
        if idx < n:
            d = sum(k_smooth[max(0,i-2):i+1]) / min(3, i+1)
            srsi[idx] = (k_smooth[i] + d) / 2
    return srsi


def calc_supertrend(candles, period=10, mult=1.0):
    n = len(candles)
    if n < period + 1:
        return [0.0] * n, [0] * n
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    closes = [c["c"] for c in candles]
    atr = calc_atr(candles, period)
    upper = [0.0] * n
    lower = [0.0] * n
    for i in range(period, n):
        hl2 = (highs[i] + lows[i]) / 2
        upper[i] = hl2 + mult * atr[i]
        lower[i] = hl2 - mult * atr[i]
    st = [0.0] * n
    trend = [0] * n
    start = period
    if closes[start] >= upper[start]:
        trend[start] = -1; st[start] = upper[start]
    elif closes[start] <= lower[start]:
        trend[start] = 1; st[start] = lower[start]
    else:
        if abs(closes[start]-upper[start]) < abs(closes[start]-lower[start]):
            trend[start] = -1; st[start] = upper[start]
        else:
            trend[start] = 1; st[start] = lower[start]
    for i in range(start+1, n):
        if trend[i-1] == 1:
            trail = max(lower[i], st[i-1])
            if closes[i] < trail:
                trend[i] = -1; st[i] = upper[i]
            else:
                trend[i] = 1; st[i] = trail
        else:
            trail = min(upper[i], st[i-1])
            if closes[i] > trail:
                trend[i] = 1; st[i] = lower[i]
            else:
                trend[i] = -1; st[i] = trail
    return st, trend


def find_swing_levels(candles, depth=2):
    """basic swing point detection"""
    n = len(candles)
    levels = []
    for i in range(depth, n-depth):
        h, l = candles[i]["h"], candles[i]["l"]
        is_high = all(h >= candles[j]["h"] for j in range(i-depth, i+depth+1) if j != i)
        is_low = all(l <= candles[j]["l"] for j in range(i-depth, i+depth+1) if j != i)
        if is_high:
            levels.append({"type": "resistance", "price": h, "index": i})
        if is_low:
            levels.append({"type": "support", "price": l, "index": i})
    return levels


# ═══ 回测引擎 ═══
def backtest(symbol, candles, params):
    """
    params = {
        "alert_threshold": 9,
        "dmi_weights": (1,2,3),
        "st_period": 10, "st_mult": 1.0,
        "near_pct": 0.01,
        "sl_atr_mult": 2.0, "min_sl_pct": 0.02,
        "tp_atr_mult": 6.0,
        "entry_mode": "st_near",  # st_near | st_in_zone
        "zone_depth": 2,
        "trail_bull": 1.5,   # 强势判定阈值
    }
    """
    n = len(candles)
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]

    # Pre-calc indicators
    atr = calc_atr(candles)
    dmi = calc_dmi(candles)
    rsi = calc_rsi(closes)
    srsi = calc_stoch_rsi(rsi)
    st_line, st_trend = calc_supertrend(candles, params["st_period"], params["st_mult"])
    swings = find_swing_levels(candles, params["zone_depth"])

    # Simulate higher timeframe by downsampling
    dmi_4h = estimate_htf_dmi(candles, dmi, 4)
    srsi_4h = estimate_htf_srsi(closes, srsi, 4)
    dmi_1d = estimate_htf_dmi(candles, dmi, 24)
    srsi_1d = estimate_htf_srsi(closes, srsi, 24)

    w = params["dmi_weights"]
    trades = []
    position = None  # {"type": "long"/"short", "entry": price, "entry_i": idx, "atr": float, "sl": float, "tp": float, "tp_hit": bool, "half": bool}

    for i in range(24, n):  # start after enough data
        if srsi[i] is None: continue

        # ═══ scoring ═══
        d1h = dmi[i]; d4h = dmi_4h[i]; d1d = dmi_1d[i]
        bull = (1 if d1h == 1 else 0)*w[0] + (1 if d4h == 1 else 0)*w[1] + (1 if d1d == 1 else 0)*w[2]
        bear = (1 if d1h == -1 else 0)*w[0] + (1 if d4h == -1 else 0)*w[1] + (1 if d1d == -1 else 0)*w[2]

        srsi_1h_v = srsi[i]; srsi_4h_v = srsi_4h[i]; srsi_1d_v = srsi_1d[i]
        if srsi_1h_v is not None:
            if srsi_1h_v < 20: bull += w[0]
            if srsi_1h_v > 80: bear += w[0]
        if srsi_4h_v is not None:
            if srsi_4h_v < 20: bull += w[1]
            if srsi_4h_v > 80: bear += w[1]
        if srsi_1d_v is not None:
            if srsi_1d_v < 20: bull += w[2]
            elif srsi_1d_v < 30: bull += 1
            if srsi_1d_v > 80: bear += w[2]
            elif srsi_1d_v > 70: bear += 1

        threshold = params["alert_threshold"]
        near_flag = abs(closes[i] - st_line[i]) / st_line[i] <= params["near_pct"] if st_line[i] > 0 else False

        # Zone check
        current_swings = [s for s in swings if s["index"] < i - max(2, params["zone_depth"])]
        near_res = None; near_sup = None
        for s in reversed(current_swings):
            if s["type"] == "resistance" and s["price"] > closes[i]:
                near_res = s["price"]; break
        for s in reversed(current_swings):
            if s["type"] == "support" and s["price"] < closes[i]:
                near_sup = s["price"]; break

        zone_ok = False
        if params["entry_mode"] == "st_in_zone":
            zone_ok = (near_sup and abs(st_line[i]-near_sup) <= atr[i]) or \
                      (near_res and abs(st_line[i]-near_res) <= atr[i])
            long_sig = bull >= threshold and zone_ok
            short_sig = bear >= threshold and zone_ok
        else:
            long_sig = bull >= threshold and near_flag
            short_sig = bear >= threshold and near_flag

        # ═══ Position management ═══
        if position is None:
            if long_sig:
                atr_v = max(atr[i], 0.0001)
                sl = closes[i] - max(params["sl_atr_mult"]*atr_v, params["min_sl_pct"]*closes[i])
                tp_val = closes[i] + params["tp_atr_mult"] * atr_v
                if near_res and near_res > closes[i]:
                    tp_val = near_res
                tp_val = max(tp_val, closes[i] + params["tp_atr_mult"]*atr_v)
                position = {"type": "long", "entry": closes[i], "entry_i": i, "atr": atr_v, "sl": sl, "tp": tp_val, "tp_hit": False, "half": False}
            elif short_sig:
                atr_v = max(atr[i], 0.0001)
                sl = closes[i] + max(params["sl_atr_mult"]*atr_v, params["min_sl_pct"]*closes[i])
                tp_val = closes[i] - params["tp_atr_mult"] * atr_v
                if near_sup and near_sup < closes[i]:
                    tp_val = near_sup
                tp_val = min(tp_val, closes[i] - params["tp_atr_mult"]*atr_v)
                position = {"type": "short", "entry": closes[i], "entry_i": i, "atr": atr_v, "sl": sl, "tp": tp_val, "tp_hit": False, "half": False}
        else:
            p = position
            exit_reason = None
            exit_price = None

            # Tick-level check: only from next bar
            if i > p["entry_i"]:
                atr_v = p["atr"]

                if p["type"] == "long":
                    if not p["tp_hit"] and highs[i] >= p["tp"]:
                        p["tp_hit"] = True
                        # Rescan at TP
                        if bull < bear:
                            exit_reason = "tp_weak"; exit_price = p["tp"]
                        elif bull >= bear * params["trail_bull"]:
                            p["sl"] = p["entry"]  # move to BE
                            p["tp"] = p["entry"] + 10.0 * atr_v
                        else:
                            exit_reason = "tp_half"; exit_price = p["tp"]
                            p["half"] = True
                            p["sl"] = p["entry"]
                            p["tp"] = p["entry"] + 8.0 * atr_v
                    elif p["tp_hit"] and highs[i] >= p["tp"]:
                        exit_reason = "tp_final"; exit_price = p["tp"]
                    elif lows[i] <= p["sl"]:
                        exit_reason = "sl"; exit_price = p["sl"]
                else:  # short
                    if not p["tp_hit"] and lows[i] <= p["tp"]:
                        p["tp_hit"] = True
                        if bear < bull:
                            exit_reason = "tp_weak"; exit_price = p["tp"]
                        elif bear >= bull * params["trail_bull"]:
                            p["sl"] = p["entry"]
                            p["tp"] = p["entry"] - 10.0 * atr_v
                        else:
                            exit_reason = "tp_half"; exit_price = p["tp"]
                            p["half"] = True
                            p["sl"] = p["entry"]
                            p["tp"] = p["entry"] - 8.0 * atr_v
                    elif p["tp_hit"] and lows[i] <= p["tp"]:
                        exit_reason = "tp_final"; exit_price = p["tp"]
                    elif highs[i] >= p["sl"]:
                        exit_reason = "sl"; exit_price = p["sl"]

            if exit_reason:
                pnl = (exit_price - p["entry"]) / p["entry"] if p["type"] == "long" else (p["entry"] - exit_price) / p["entry"]
                if p["half"]:
                    pnl *= 0.5  # only half closed
                trades.append({
                    "type": p["type"], "entry": p["entry"], "exit": exit_price,
                    "exit_reason": exit_reason, "pnl_pct": pnl,
                    "entry_i": p["entry_i"], "exit_i": i,
                    "holding_bars": i - p["entry_i"], "half": p["half"],
                })
                if not p["half"] or exit_reason in ("tp_weak", "sl"):
                    position = None

    return trades


def estimate_htf_dmi(candles, dmi_1h, factor):
    """粗糙但OK的多TF估计: 用DMI方向众数"""
    n = len(dmi_1h)
    dmi_htf = [0] * n
    for i in range(factor, n):
        seg = dmi_1h[max(0,i-factor):i+1]
        longs = sum(1 for d in seg if d == 1)
        shorts = sum(1 for d in seg if d == -1)
        dmi_htf[i] = 1 if longs >= shorts else -1
    return dmi_htf


def estimate_htf_srsi(closes, srsi_1h, factor):
    """取最近的有效 StochRSI 值"""
    n = len(srsi_1h)
    srsi_htf = [None] * n
    for i in range(n):
        # 每 factor 根取平均
        start = max(0, i - factor + 1)
        vals = [v for v in srsi_1h[start:i+1] if v is not None]
        srsi_htf[i] = sum(vals) / len(vals) if vals else None
    return srsi_htf


# ═══ 指标统计 ═══
def calc_metrics(trades):
    if not trades:
        return {"trades": 0, "win_rate": 0, "total_return": 0, "avg_ret": 0, "max_dd": 0, "sharpe": 0}
    wins = sum(1 for t in trades if t["pnl_pct"] > 0)
    win_rate = wins / len(trades)
    returns = [t["pnl_pct"] for t in trades]
    total_ret = sum(returns)
    avg_ret = total_ret / len(trades) if trades else 0
    # Max drawdown
    cum = 0; peak = 0; max_dd = 0
    for r in returns:
        cum += r; peak = max(peak, cum); max_dd = min(max_dd, cum - peak)
    # Sharpe
    mean = sum(returns) / len(returns)
    var = sum((x-mean)**2 for x in returns) / len(returns)
    std = math.sqrt(var) if var > 0 else 0.01
    sharpe = mean / std * math.sqrt(len(trades)) if std else 0
    avg_hold = sum(t["holding_bars"] for t in trades) / len(trades) if trades else 0
    return {
        "trades": len(trades), "win_rate": round(win_rate, 3),
        "total_return": round(total_ret*100, 2),
        "avg_ret": round(avg_ret*100, 2),
        "max_dd": round(max_dd*100, 2),
        "sharpe": round(sharpe, 2),
        "avg_hold_bars": round(avg_hold, 1),
    }


# ═══ 网格搜索 ═══
def grid_search(symbols, candle_counts, test_candles):
    param_grid = {
        "alert_threshold": [7, 8, 9],
        "dmi_weights": [(1,2,3), (1,1,2)],
        "st_mult": [0.5, 1.0, 1.5],
        "near_pct": [0.005, 0.01, 0.015],
        "sl_atr_mult": [1.5, 2.0, 2.5],
        "min_sl_pct": [0.01, 0.02],
        "tp_atr_mult": [4.0, 6.0, 8.0],
        "entry_mode": ["st_near", "st_in_zone"],
        "zone_depth": [2, 5],
    }
    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    total = len(combos) * len(symbols)
    print(f"参数组合: {len(combos)}, 品种: {len(symbols)}, 总计: {total} 次回测")

    results = []
    for idx, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        params["st_period"] = 10
        params["trail_bull"] = 1.5

        all_metrics = []
        total_trades = 0
        for sym in symbols:
            candles = test_candles.get(sym, [])
            if len(candles) < 50:
                continue
            trades = backtest(sym, candles, params)
            total_trades += len(trades)
            m = calc_metrics(trades)
            m["symbol"] = sym
            all_metrics.append(m)

        if not all_metrics:
            continue

        # Aggregate
        agg = {
            "trades": sum(m["trades"] for m in all_metrics),
            "win_rate": round(sum(m["win_rate"] for m in all_metrics) / len(all_metrics), 3),
            "total_return": round(sum(m["total_return"] for m in all_metrics) / len(all_metrics), 2),
            "sharpe": round(sum(m["sharpe"] for m in all_metrics) / len(all_metrics), 2),
            "max_dd": round(sum(m["max_dd"] for m in all_metrics) / len(all_metrics), 2),
        }

        # Score: weighted composite
        score = agg["win_rate"] * 0.3 + min(agg["total_return"] / 10, 1) * 0.3 + \
                max(agg["sharpe"] / 2, 0) * 0.2 + min(agg["trades"] / 50, 1) * 0.2

        results.append({"params": params, "score": round(score, 4), **agg})

        if (idx + 1) % 50 == 0:
            print(f"  {idx+1}/{len(combos)} 完成...")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


if __name__ == "__main__":
    print("拉取历史数据...")
    test_candles = {}
    for sym in ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]:
        print(f"  {sym}...")
        data = fetch_extended(sym, bars=1000)
        if data:
            test_candles[sym] = data
            print(f"    获取 {len(data)} 根K线")

    print("\n开始网格搜索...")
    results = grid_search(["BTC-USDT-SWAP", "ETH-USDT-SWAP"], {"BTC-USDT-SWAP": 1000, "ETH-USDT-SWAP": 1000}, test_candles)

    print("\n═══ Top 20 策略 ═══")
    for i, r in enumerate(results[:20]):
        p = r["params"]
        print(f"{i+1:2d}. 得分={r['score']:.4f} 胜率={r['win_rate']:.1%} 收益={r['total_return']:.1f}% Sharpe={r['sharpe']:.1f} 交易={r['trades']}")
        print(f"    阈值={p['alert_threshold']} DMI权重={p['dmi_weights']} ST×{p['st_mult']} ST近={p['near_pct']:.1%}")
        print(f"    止损×{p['sl_atr_mult']} 最低{p['min_sl_pct']:.0%} 止盈×{p['tp_atr_mult']} 入场={p['entry_mode']} 区间={p['zone_depth']}")

    # Save
    with open("results/grid_results.json", "w") as f:
        json.dump(results[:50], f, indent=2)
    print("\n✅ 结果已保存到 results/grid_results.json")
