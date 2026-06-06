"""
OKX 模拟交易策略执行引擎
策略: 扫描高分 + 1H SuperTrend(10,3) ±0.5% 入场
止损: 2×1H ATR | 止盈: 关键位重扫
"""
import sys, os, json, time, csv, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 借用 okx-monitor 的指标库
sys.path.insert(0, "/Users/yyy/WorkBuddy/2026-06-04-22-04-27/okx-monitor")
from shared.indicators import fetch_ohlcv, calc_stoch_rsi, trend_dmi, calc_atr, calc_score

OKX_CLI = "/Users/yyy/.workbuddy/binaries/node/versions/22.12.0/bin/node"
OKX_JS = "/Users/yyy/.workbuddy/binaries/node/workspace/node_modules/@okx_ai/okx-trade-cli/dist/index.js"
OKX_NODE_PATH = "/Users/yyy/.workbuddy/binaries/node/workspace/node_modules"
OKX_PROFILE = "demo"

CST = timezone(timedelta(hours=8))
WORKSPACE = Path("/Users/yyy/WorkBuddy/2026-06-06-00-14-15")
TRADE_LOG = WORKSPACE / "trades.csv"
POSITIONS_FILE = WORKSPACE / "positions.json"

# 策略参数
ST_PERIOD, ST_MULT = 10, 3
NEAR_PCT = 0.005  # ±0.5%
ALERT_THRESHOLD = 6
MAX_RISK_PCT = 0.02  # 每笔最大亏损2%

# 14币种池
SYMBOLS_FILE = "/Users/yyy/WorkBuddy/2026-06-03-21-23-44/okx-monitor/SYMBOLS.txt"
with open(SYMBOLS_FILE) as f:
    SYMBOLS = [line.strip() for line in f if line.strip()]

# PushPlus 配置
PUSHPLUS_TOKEN = "68fb8af9e2764f5f9a3bb29ab1418cd3"
PUSHPLUS_URL = "http://www.pushplus.plus/send"

# 合约面值 (U本位)
CT_VAL = {
    "BTC-USDT-SWAP": 0.01, "ETH-USDT-SWAP": 0.1, "SOL-USDT-SWAP": 1,
    "DOGE-USDT-SWAP": 1000, "XRP-USDT-SWAP": 100, "SUI-USDT-SWAP": 10,
    "APT-USDT-SWAP": 1, "HOME-USDT-SWAP": 100, "WLD-USDT-SWAP": 1,
    "HUMA-USDT-SWAP": 10, "HMSTR-USDT-SWAP": 1000, "PUMP-USDT-SWAP": 1000,
    "ORDI-USDT-SWAP": 0.1, "APR-USDT-SWAP": 10, "DASH-USDT-SWAP": 0.1,
    "GMT-USDT-SWAP": 10, "GALA-USDT-SWAP": 100, "PI-USDT-SWAP": 10,
}

# ── SuperTrend 计算 ──
def calc_supertrend(candles, period=10, multiplier=3):
    """返回 (trend: '多'/'空', st_line: 当前SuperTrend值, st_prev: 前一根)"""
    n = len(candles)
    if n < period + 1:
        return "N/A", None, None
    
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    closes = [c["c"] for c in candles]
    
    # 计算 ATR
    atr_list = [0.0] * n
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i-1]
        atr_list[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr_val = sum(atr_list[1:period+1]) / period
    for i in range(period + 1, n):
        atr_val = (atr_val * (period - 1) + atr_list[i]) / period
        atr_list[i] = atr_val
    
    # 基本带
    upper = [0.0] * n
    lower = [0.0] * n
    for i in range(n):
        hl2 = (highs[i] + lows[i]) / 2
        upper[i] = hl2 + multiplier * atr_list[i]
        lower[i] = hl2 - multiplier * atr_list[i]
    
    # SuperTrend 最终值（带趋势修正）
    st_final = [0.0] * n
    trend = [1] * n  # 1=多, -1=空
    start = period
    
    # 初始方向
    if closes[start] > upper[start]:
        trend[start] = -1
        st_final[start] = upper[start]
    else:
        trend[start] = 1
        st_final[start] = lower[start]
    
    for i in range(start + 1, n):
        prev_trend = trend[i-1]
        prev_st = st_final[i-1]
        
        if prev_trend == 1:  # 之前多头
            # 下轨不能低于前值
            curr_lower = max(lower[i], prev_st) if closes[i-1] > lower[i] and lower[i] > prev_st else lower[i]
            if closes[i] < curr_lower:
                trend[i] = -1
                st_final[i] = upper[i]
            else:
                trend[i] = 1
                st_final[i] = curr_lower
        else:  # 之前空头
            curr_upper = min(upper[i], prev_st) if closes[i-1] < upper[i] and upper[i] < prev_st else upper[i]
            if closes[i] > curr_upper:
                trend[i] = 1
                st_final[i] = lower[i]
            else:
                trend[i] = -1
                st_final[i] = curr_upper
    
    return ("多" if trend[-1] == 1 else "空"), st_final[-1], st_final[-2]


# ── 关键区间检测（历史多次触及）──
def find_key_zones(candles, st_line=None, atr_val=None):
    """
    找出历史多次触及的关键支撑/阻力区间
    
    四个维度评估区间强度:
    1. 触及次数 (权重 0.40)
    2. 触及质量 - 每次触及后的反转幅度/ATR (权重 0.25)
    3. 时间跨度 (权重 0.20)
    4. 价格戏剧性 - 是否有大K线/长影线 (权重 0.15)
    
    返回 (key_resistance, key_support, all_zones)
    """
    if len(candles) < 10:
        return None, None, []
    
    n = len(candles)
    atr = atr_val or (calc_atr(candles) or 1)
    price = candles[-1]["c"]
    
    # 自适应聚类半径（微盘币价格低，波动率大）
    if price < 0.01:
        cluster_radius = atr * 1.5
        min_touches_strong = 2
    elif price < 1:
        cluster_radius = atr * 1.0
        min_touches_strong = 2
    else:
        cluster_radius = atr * 0.8
        min_touches_strong = 3
    
    # 第一遍：摆动点检测
    swing_highs = []
    swing_lows = []
    for i in range(2, n - 2):
        h, l = candles[i]["h"], candles[i]["l"]
        if h >= max(candles[j]["h"] for j in range(i-2, i+3)):
            swing_highs.append({"price": h, "index": i})
        if l <= min(candles[j]["l"] for j in range(i-2, i+3)):
            swing_lows.append({"price": l, "index": i})
    
    # 辅助函数：计算一次触及的质量（触及后3根K线最大反向幅度/ATR）
    def touch_quality(swing_index, is_high):
        if swing_index >= n - 4:
            return 1.0
        ref_price = candles[swing_index]["h" if is_high else "l"]
        max_reverse = 0
        for j in range(swing_index + 1, min(n, swing_index + 4)):
            if is_high:
                reverse = ref_price - candles[j]["l"]
            else:
                reverse = candles[j]["h"] - ref_price
            max_reverse = max(max_reverse, reverse)
        return min(max_reverse / atr, 3.0) if atr > 0 else 1.0
    
    # 辅助函数：检测价格戏剧性（大K线/长影线）
    def price_drama(near_swing_index, radius=3):
        """检查摆动点附近是否有戏剧性K线"""
        drama_score = 0
        start = max(0, near_swing_index - radius)
        end = min(n, near_swing_index + radius + 1)
        for i in range(start, end):
            body = abs(candles[i]["c"] - candles[i]["h"]) + abs(candles[i]["c"] - candles[i]["l"])
            lower_wick = min(candles[i]["c"], candles[i]["c"]) - candles[i]["l"]  # simplified
            upper_wick = candles[i]["h"] - max(candles[i]["c"], candles[i]["c"])
            total_range = candles[i]["h"] - candles[i]["l"]
            # 大实体 (>2x ATR)
            if body > 2 * atr:
                drama_score += 1.0
            # 长影线 (影线 > 2x 实体)
            if total_range > 0 and max(upper_wick, lower_wick) > 2 * body / total_range:
                drama_score += 0.5
        return min(drama_score, 3.0)
    
    # 第二遍：聚类
    def cluster_levels(swing_points, is_resistance):
        if not swing_points:
            return []
        points = sorted(swing_points, key=lambda x: x["price"])
        clusters = []
        current_cluster = [points[0]]
        
        for pt in points[1:]:
            if pt["price"] - current_cluster[-1]["price"] <= cluster_radius:
                current_cluster.append(pt)
            else:
                clusters.append(build_zone(current_cluster, is_resistance))
                current_cluster = [pt]
        clusters.append(build_zone(current_cluster, is_resistance))
        return clusters
    
    def build_zone(cluster, is_resistance):
        prices = [p["price"] for p in cluster]
        indices = [p["index"] for p in cluster]
        touches = len(cluster)
        
        # 触及质量：所有触及的平均反转幅度
        qualities = [touch_quality(idx, is_resistance) for idx in indices]
        avg_quality = sum(qualities) / len(qualities) if qualities else 1.0
        
        # 时间跨度：第一个触及到最后一个触及
        time_span = abs(indices[-1] - indices[0]) if len(indices) > 1 else 0
        time_norm = min(time_span / n, 1.0)
        
        # 价格戏剧性：在区间点位附近找
        mid_idx = int(sum(indices) / len(indices)) if indices else 0
        drama = price_drama(mid_idx)
        
        # 综合强度评分
        strength = (
            min(touches / 7, 1.0) * 0.40 +    # 触及次数（正态化到7次满分）
            min(avg_quality / 2, 1.0) * 0.25 + # 触及质量（2x ATR满分）
            time_norm * 0.20 +                   # 时间跨度
            min(drama / 3, 1.0) * 0.15          # 戏剧性
        )
        
        return {
            "lower": min(prices),
            "upper": max(prices),
            "center": sum(prices) / len(prices),
            "touches": touches,
            "quality": round(avg_quality, 2),
            "time_span_pct": round(time_norm * 100, 1),
            "drama": round(drama, 1),
            "strength": round(strength, 3),
            "is_resistance": is_resistance,
        }
    
    # 阻力区间和支撑区间
    resistance_zones = cluster_levels(
        [p for p in swing_highs if p["price"] > price], True
    )
    support_zones = cluster_levels(
        [p for p in swing_lows if p["price"] < price], False
    )
    
    # 按综合强度排序
    resistance_zones.sort(key=lambda z: z["strength"], reverse=True)
    support_zones.sort(key=lambda z: z["strength"], reverse=True)
    
    # 优先选最合适的区间
    def pick_best_zone(zones, direction="above"):
        if not zones:
            return None
        # 只选触及足够的强区间
        strong = [z for z in zones if z["touches"] >= min_touches_strong]
        if not strong:
            strong = zones
        
        if st_line and st_line > 0:
            # ST-区间距离加权：离ST越近的区间在综合排序中加权
            for z in strong:
                st_proximity = max(0, 1 - abs(z["center"] - st_line) / atr / 3)
                z["strength"] = round(z["strength"] * (1 + st_proximity * 0.3), 3)
            strong.sort(key=lambda z: z["strength"], reverse=True)
        
        if direction == "above":
            # 最近的阻力区
            strong.sort(key=lambda z: z["center"])
            for z in strong:
                if z["center"] > price:
                    return z
            return strong[0] if strong else None
        else:
            # 最近的支撑区
            strong.sort(key=lambda z: -z["center"])
            for z in strong:
                if z["center"] < price:
                    return z
            return strong[0] if strong else None
    
    key_resistance = pick_best_zone(resistance_zones, "above")
    key_support = pick_best_zone(support_zones, "below")
    
    all_zones = resistance_zones[:5] + support_zones[:5]
    
    return key_resistance, key_support, all_zones


# ── 运行 OKX CLI ──
def run_okx(args, timeout=30):
    import subprocess
    env = os.environ.copy()
    env["NODE_PATH"] = OKX_NODE_PATH
    cmd = [OKX_CLI, OKX_JS, "--profile", OKX_PROFILE] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return "", "timeout"
    except Exception as e:
        return "", str(e)


def get_balance():
    stdout, _ = run_okx(["account", "balance", "--json"])
    try:
        data = json.loads(stdout)
        details = (data.get("data") or [{}])[0].get("details", [])
        usdt = next((d for d in details if d.get("ccy") == "USDT"), {})
        return float(usdt.get("eq", 0))
    except:
        return 5000  # fallback


def get_positions():
    stdout, _ = run_okx(["swap", "positions", "--json"])
    try:
        return json.loads(stdout).get("data", [])
    except:
        return []


# ── 仓位计算 ──
def calc_position_size(equity, entry_price, stop_loss_price, ct_val):
    """max_risk = equity * 2%; size = risk / (stop_distance * ct_val)"""
    risk_usdt = equity * MAX_RISK_PCT
    stop_distance = abs(entry_price - stop_loss_price)
    if stop_distance == 0:
        return 1
    size = risk_usdt / (stop_distance * ct_val)
    # 向下取整到最小精度
    size = max(1, int(size))
    return size


# ── 策略扫描 ──
def scan_all():
    results = []
    for symbol in SYMBOLS:
        try:
            # 分别获取各时间框架数据
            candles_1h = fetch_ohlcv(symbol, "1H", limit=80)
            candles_4h = fetch_ohlcv(symbol, "4H", limit=80)
            candles_1d = fetch_ohlcv(symbol, "1D", limit=80)
            
            if not candles_1h or len(candles_1h) < 50:
                continue
            
            # 使用1H数据做SuperTrend（主时间框架）
            candles = candles_1h
            
            # DMI 方向（各用各自时间框架数据）
            dmi_1h, adx_1h, _ = trend_dmi(candles_1h) if candles_1h else ("N/A", None, None)
            dmi_4h_d, adx_4h, _ = trend_dmi(candles_4h) if candles_4h else ("N/A", None, None)
            dmi_1d_d, adx_1d, _ = trend_dmi(candles_1d) if candles_1d else ("N/A", None, None)
            
            # StochRSI（各用各自时间框架数据）
            closes_1h = [c["c"] for c in candles_1h]
            closes_4h = [c["c"] for c in candles_4h] if candles_4h else []
            closes_1d = [c["c"] for c in candles_1d] if candles_1d else []
            srsi_1h = calc_stoch_rsi(closes_1h) if len(closes_1h) >= 30 else None
            srsi_4h = calc_stoch_rsi(closes_4h) if len(closes_4h) >= 30 else None
            srsi_1d = calc_stoch_rsi(closes_1d) if len(closes_1d) >= 30 else None
            
            # 评分
            trends = {"1H": dmi_1h, "4H": dmi_4h_d, "1D": dmi_1d_d}
            srsis = {"1H": srsi_1h, "4H": srsi_4h, "1D": srsi_1d}
            adxs = {"1H": adx_1h, "4H": adx_4h, "1D": adx_1d}
            bull, bear = calc_score(trends, srsis, adxs)
            
            # SuperTrend
            st_trend, st_line, st_prev = calc_supertrend(candles, ST_PERIOD, ST_MULT)
            
            # ATR
            atr_1h = calc_atr(candles[-30:])
            
            # 当前价格
            price = candles[-1]["c"]
            
            # 关键支撑/阻力区间
            key_res, key_sup, all_zones = find_key_zones(candles, st_line, atr_1h)
            
            results.append({
                "symbol": symbol,
                "price": price,
                "dmi_1h": dmi_1h, "dmi_4h": dmi_4h_d, "dmi_1d": dmi_1d_d,
                "srsi_1h": srsi_1h, "srsi_4h": srsi_4h, "srsi_1d": srsi_1d,
                "adx_1h": adx_1h,
                "bull": bull, "bear": bear,
                "st_trend": st_trend, "st_line": st_line,
                "atr": atr_1h,
                "key_resistance": key_res,
                "key_support": key_sup,
            })
        except Exception as e:
            print(f"  ⚠️ {symbol} error: {e}")
    return results


# ── 信号检测 ──
def detect_signals(scan_results, active_positions):
    """检测入场信号：高分 + 1H SuperTrend附近 + 方向一致 + 没持仓"""
    signals = []
    active_pair_dirs = set()
    for p in active_positions:
        symbol = p["instId"]
        side = p["posSide"]
        active_pair_dirs.add(f"{symbol}_{side}")
    
    now_cst = datetime.now(CST)
    
    for r in scan_results:
        symbol = r["symbol"]
        
        # 高分预警
        max_score = max(r["bull"], r["bear"])
        if max_score < ALERT_THRESHOLD:
            continue
        
        # 确定方向
        if r["bull"] >= ALERT_THRESHOLD:
            direction = "long"
            score_dir = r["bull"]
        elif r["bear"] >= ALERT_THRESHOLD:
            direction = "short"
            score_dir = r["bear"]
        else:
            continue
        
        # 已有同向持仓，跳过
        if f"{symbol}_{direction}" in active_pair_dirs:
            continue
        
        # SuperTrend检查
        st_trend = r["st_trend"]
        st_line = r["st_line"]
        if st_line is None or st_line == 0:
            continue
        price = r["price"]
        near_st = abs(price - st_line) / st_line
        
        # 价格必须在SuperTrend附近 ±0.5%
        if near_st > NEAR_PCT:
            continue
        
        # 方向必须和SuperTrend一致
        if direction == "long" and st_trend != "多":
            continue
        if direction == "short" and st_trend != "空":
            continue
        
        # 信号强度评分
        strength = min(max_score / 10, 1.0)
        
        # 获取 ATR 和关键区间
        atr = r["atr"] or (price * 0.01)
        
        # 止损价：2x ATR
        if direction == "long":
            stop_loss = price - 2 * atr
        else:
            stop_loss = price + 2 * atr
        
        # 止盈目标：关键阻力/支撑区间
        # 做多 → 看上方的阻力区间；做空 → 看下方的支撑区间
        key_res = r.get("key_resistance")
        key_sup = r.get("key_support")
        if direction == "long":
            tp_zone = key_res
            tp_target = tp_zone["center"] if tp_zone else (price + 4 * atr)
            tp_desc = f"阻力区(触及{tp_zone['touches']}次@{tp_zone['center']:.4f})" if tp_zone else f"ATR目标@{tp_target:.4f}"
        else:
            tp_zone = key_sup
            tp_target = tp_zone["center"] if tp_zone else (price - 4 * atr)
            tp_desc = f"支撑区(触及{tp_zone['touches']}次@{tp_zone['center']:.4f})" if tp_zone else f"ATR目标@{tp_target:.4f}"
        
        signals.append({
            "symbol": symbol,
            "direction": direction,
            "score": score_dir,
            "price": price,
            "st_trend": st_trend,
            "st_line": st_line,
            "near_pct": near_st * 100,
            "stop_loss": stop_loss,
            "tp_target": tp_target,
            "tp_desc": tp_desc,
            "atr": atr,
            "time": now_cst.isoformat(),
            "strength": strength,
        })
    
    return signals


# ── 下单 ──
def place_order(symbol, direction, size, stop_loss, tp_target):
    side = "buy" if direction == "long" else "sell"
    pos_side = direction
    
    # 计算止盈止损价用于附加订单
    stdout, stderr = run_okx([
        "swap", "place",
        "--instId", symbol,
        "--side", side,
        "--ordType", "market",
        "--sz", str(size),
        "--tdMode", "cross",
        "--posSide", pos_side,
        "--slTriggerPx", str(stop_loss) if direction == "long" else str(stop_loss),
        "--slOrdPx", "-1",
        "--json"
    ])
    
    if stderr and "Error" in stderr:
        return None, stderr
    try:
        data = json.loads(stdout)
        if data.get("error") == False:
            ord_id = data["data"][0]["ordId"]
            return ord_id, None
        else:
            return None, data.get("msg", "order failed")
    except:
        return None, stdout or "parse error"


def close_position(symbol, pos_side, size=None):
    """平仓"""
    args = [
        "swap", "close",
        "--instId", symbol,
        "--mgnMode", "cross",
        "--posSide", pos_side,
    ]
    if size:
        args += ["--sz", str(size)]
    stdout, stderr = run_okx(args + ["--json"])
    if stderr and "Error" in stderr:
        return None, stderr
    try:
        data = json.loads(stdout)
        return data, None
    except:
        return None, stdout


# ── 止盈重扫决策 ──
def rescan_decision(symbol, current_direction, current_score):
    """在止盈目标处重新扫描，决定操作"""
    try:
        candles = fetch_ohlcv(symbol, "1H", limit=200)
        if not candles or len(candles) < 60:
            return "hold", 0, 0
        
        closes = [c["c"] for c in candles]
        dmi_1h, adx_1h, _ = trend_dmi(candles[-30:])
        dmi_4h_d, adx_4h, _ = trend_dmi(candles[-120:])
        dmi_1d_d, adx_1d, _ = trend_dmi(candles[-200:])
        srsi_1h = calc_stoch_rsi(closes[-30:])
        srsi_4h = calc_stoch_rsi(closes[-120:])
        srsi_1d = calc_stoch_rsi(closes[-200:])
        
        trends = {"1H": dmi_1h, "4H": dmi_4h_d, "1D": dmi_1d_d}
        srsis = {"1H": srsi_1h, "4H": srsi_4h, "1D": srsi_1d}
        adxs = {"1H": adx_1h, "4H": adx_4h, "1D": adx_1d}
        bull, bear = calc_score(trends, srsis, adxs)
        
        if current_direction == "long":
            my_score = bull
            opposite_score = bear
        else:
            my_score = bear
            opposite_score = bull
        
        ratio = my_score / max(opposite_score, 1)
        
        if my_score < opposite_score:
            return "close_all", my_score, opposite_score
        elif ratio > 1.5:
            return "move_stop", my_score, opposite_score
        else:
            return "half_close", my_score, opposite_score
    except:
        return "hold", 0, 0


# ── 交易日志 ──
def log_trade(entry_time, symbol, direction, entry_price, size, stop_loss,
              exit_time=None, exit_price=None, exit_reason=None, pnl=None):
    file_exists = TRADE_LOG.exists()
    with open(TRADE_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "entry_time", "symbol", "direction", "entry_price", "size",
                "stop_loss", "exit_time", "exit_price", "exit_reason", "pnl_usdt"
            ])
        writer.writerow([
            entry_time, symbol, direction, entry_price, size, stop_loss,
            exit_time or "", exit_price or "", exit_reason or "", pnl or ""
        ])


# ── 保存活跃持仓 ──
def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2, default=str)


def load_local_positions():
    if POSITIONS_FILE.exists():
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return []


# ── PushPlus 推送 ──
def pushplus_send(title, content, template="html"):
    """发送 PushPlus 通知"""
    if not PUSHPLUS_TOKEN:
        print("  ⚠️ PushPlus Token 未配置")
        return False
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": template}
        resp = requests.post(PUSHPLUS_URL, json=payload, timeout=10,
                           proxies={"http": None, "https": None})
        r = resp.json()
        if r.get("code") == 200:
            return True
        print(f"  ❌ PushPlus失败: {r.get('msg','')}")
        return False
    except Exception as e:
        print(f"  ❌ PushPlus异常: {e}")
        return False


def push_scan_report(results, now_str):
    """推送完整扫描报表（HTML格式）"""
    if not PUSHPLUS_TOKEN:
        return

    alert_count = sum(1 for r in results if max(r["bull"], r["bear"]) >= ALERT_THRESHOLD)
    dcol = {"多": "#27ae60", "空": "#e74c3c", "N/A": "#999"}

    def sc(v):
        try:
            n = float(v)
            if n > 80: return "#e74c3c", "bold"
            if n < 20: return "#27ae60", "bold"
        except: pass
        return "#333", "normal"

    def srf(v):
        if v is None: return "N/A", "#999", "normal"
        c, w = sc(v); return f"{v:.0f}", c, w

    htm = '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:560px">'
    htm += f'<h3 style="margin:0 0 6px;color:#333">📊 OKX 策略扫描 + SuperTrend</h3>'
    htm += f'<p style="color:#999;font-size:12px;margin:0 0 10px">{now_str}</p>'

    # 高分预警区
    alerts = [r for r in results if max(r["bull"], r["bear"]) >= ALERT_THRESHOLD]
    if alerts:
        htm += f'<p style="color:#e74c3c;font-weight:bold;margin:0 0 6px">⚠️ 高分预警（≥{ALERT_THRESHOLD}分）</p>'
        for r in alerts:
            nm = r["symbol"].replace("-USDT-SWAP", "")
            # 入场条件检查
            st = r.get("st_trend", "N/A")
            st_line = r.get("st_line", 0) or 0
            near = abs(r["price"] - st_line) / max(st_line, 1) * 100 if st_line else 999
            near_ok = "✅" if near <= (NEAR_PCT * 100) else "❌"
            dir_ok = "✅" if (r["bull"] >= ALERT_THRESHOLD and st == "多") or (r["bear"] >= ALERT_THRESHOLD and st == "空") else "❌"

            if r["bull"] >= ALERT_THRESHOLD:
                htm += f'<p style="margin:4px 0;font-size:14px">🟢 <b>{nm}</b> 多分={r["bull"]} | ST:{st}@{st_line:.2f} 距ST:{near:.1f}% {near_ok} {dir_ok}</p>'
            if r["bear"] >= ALERT_THRESHOLD:
                htm += f'<p style="margin:4px 0;font-size:14px">🔴 <b>{nm}</b> 空分={r["bear"]} | ST:{st}@{st_line:.2f} 距ST:{near:.1f}% {near_ok} {dir_ok}</p>'

            # 关键区间
            kr = r.get("key_resistance")
            ks = r.get("key_support")
            if kr:
                htm += f'<p style="margin:1px 0;font-size:11px;color:#666">  阻力: {kr["center"]:.4f} (触及{kr["touches"]}次/质量{kr["quality"]}/强度{kr["strength"]})</p>'
            if ks:
                htm += f'<p style="margin:1px 0;font-size:11px;color:#666">  支撑: {ks["center"]:.4f} (触及{ks["touches"]}次/质量{ks["quality"]}/强度{ks["strength"]})</p>'

        htm += '<hr style="border:0;border-top:1px solid #eee;margin:8px 0">'

    # 全量表
    htm += '<table style="width:100%;border-collapse:collapse;font-size:11px">'
    htm += '<tr style="background:#f5f6fa;font-weight:bold;color:#666">'
    htm += '<td style="padding:4px 2px">币种</td>'
    htm += '<td style="padding:4px 1px;text-align:center">1H</td>'
    htm += '<td style="padding:4px 1px;text-align:center">4H</td>'
    htm += '<td style="padding:4px 1px;text-align:center">1D</td>'
    htm += '<td style="padding:4px 1px;text-align:center">SRSI 1H</td>'
    htm += '<td style="padding:4px 1px;text-align:center">SRSI 4H</td>'
    htm += '<td style="padding:4px 1px;text-align:center">SRSI 1D</td>'
    htm += '<td style="padding:4px 1px;text-align:center">ST</td>'
    htm += '<td style="padding:4px 1px;text-align:center;color:#27ae60">多</td>'
    htm += '<td style="padding:4px 1px;text-align:center;color:#e74c3c">空</td>'
    htm += '</tr>'

    for i, r in enumerate(results):
        bg = "#fff" if i % 2 == 0 else "#fafbfc"
        nm = r["symbol"].replace("-USDT-SWAP", "")
        alert_flag = max(r["bull"], r["bear"]) >= ALERT_THRESHOLD
        bd = "border-left:3px solid #e74c3c;" if alert_flag else ""

        s1h, c1h, w1h = srf(r.get("srsi_1h"))
        s4h, c4h, w4h = srf(r.get("srsi_4h"))
        s1d, c1d, w1d = srf(r.get("srsi_1d"))

        be_ = "🟢" if r["bull"] >= ALERT_THRESHOLD else ""
        re_ = "🔴" if r["bear"] >= ALERT_THRESHOLD else ""
        st = r.get("st_trend", "N/A")

        htm += f'<tr style="background:{bg};{bd}">'
        htm += f'<td style="padding:4px 2px;font-weight:bold">{nm}</td>'
        htm += f'<td style="padding:4px 1px;text-align:center;color:{dcol.get(r["dmi_1h"],"#999")}">{r["dmi_1h"]}</td>'
        htm += f'<td style="padding:4px 1px;text-align:center;color:{dcol.get(r["dmi_4h"],"#999")}">{r["dmi_4h"]}</td>'
        htm += f'<td style="padding:4px 1px;text-align:center;color:{dcol.get(r["dmi_1d"],"#999")}">{r["dmi_1d"]}</td>'
        htm += f'<td style="padding:4px 1px;text-align:center;color:{c1h};font-weight:{w1h}">{s1h}</td>'
        htm += f'<td style="padding:4px 1px;text-align:center;color:{c4h};font-weight:{w4h}">{s4h}</td>'
        htm += f'<td style="padding:4px 1px;text-align:center;color:{c1d};font-weight:{w1d}">{s1d}</td>'
        htm += f'<td style="padding:4px 1px;text-align:center;font-size:10px;color:{dcol.get(st,"#999")}">{st}</td>'
        htm += f'<td style="padding:4px 1px;text-align:center;font-weight:bold;color:#27ae60">{be_}{r["bull"]}</td>'
        htm += f'<td style="padding:4px 1px;text-align:center;font-weight:bold;color:#e74c3c">{re_}{r["bear"]}</td>'
        htm += '</tr>'

    htm += '</table>'
    htm += '<hr style="border:0;border-top:1px solid #eee;margin:6px 0">'
    htm += '<p style="color:#999;font-size:10px;margin:0">📐 DMI+StochRSI+SuperTrend(10,3) | 15min扫描 | ≥6分预警</p>'
    htm += f'<p style="color:#999;font-size:10px;margin:0">🎯 入场: ST±{NEAR_PCT*100:.1f}%同向 | 止损:2×ATR | 仓位:总权益2%</p>'
    htm += '</div>'

    title = f"OKX {alert_count}预警" if alert_count else "OKX 策略扫描"
    pushplus_send(title, htm)


def push_trade_alert(action, symbol, direction, price, size, extra=""):
    """推送交易操作通知"""
    if not PUSHPLUS_TOKEN:
        return
    emoji = "🟢" if direction == "long" else "🔴"
    dir_cn = "开多" if direction == "long" else "开空"
    htm = f'<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:400px">'
    htm += f'<h3 style="margin:0 0 6px">{emoji} {action}</h3>'
    htm += f'<p style="font-size:15px;font-weight:bold;margin:4px 0">{symbol.replace("-USDT-SWAP","")} {dir_cn} {size}张 @ {price}</p>'
    if extra:
        htm += f'<p style="font-size:12px;color:#666;margin:2px 0">{extra}</p>'
    htm += f'<p style="font-size:11px;color:#999;margin:6px 0 0">{datetime.now(CST).strftime("%m-%d %H:%M")}</p>'
    htm += '</div>'
    pushplus_send(f"{emoji} {symbol.replace('-USDT-SWAP','')} {dir_cn}", htm)


# ── 主循环 ──
def run_once(dry_run=False):
    now = datetime.now(CST)
    print(f"\n{'='*60}")
    print(f"  🔍 策略扫描 {now.strftime('%Y-%m-%d %H:%M:%S')} CST")
    print(f"{'='*60}")
    
    # 1. 扫描
    print("\n📡 获取行情数据...")
    results = scan_all()
    print(f"  ✅ 成功扫描 {len(results)}/{len(SYMBOLS)} 个品种")
    
    # 2. 显示评分
    print(f"\n📊 多空评分 (阈值 {ALERT_THRESHOLD}分):")
    for r in sorted(results, key=lambda x: max(x["bull"], x["bear"]), reverse=True):
        name = r["symbol"].replace("-USDT-SWAP", "")
        bull = r["bull"]
        bear = r["bear"]
        max_s = max(bull, bear)
        st_info = f"ST={r['st_trend']}@{r['st_line']:.2f}" if r["st_line"] else "ST=N/A"
        flag = "⚠️" if max_s >= ALERT_THRESHOLD else "  "
        near = abs(r["price"] - (r["st_line"] or 0)) / max((r["st_line"] or 1), 1) * 100 if r["st_line"] else 999
        near_st = f"距ST: {near:.2f}%" if r["st_line"] and near < 10 else "离ST较远" if r["st_line"] else ""
        s1h = f"{r['srsi_1h']:.0f}" if r['srsi_1h'] is not None else "N/A"
        s4h = f"{r['srsi_4h']:.0f}" if r['srsi_4h'] is not None else "N/A"
        s1d = f"{r['srsi_1d']:.0f}" if r['srsi_1d'] is not None else "N/A"
        print(f"  {flag} {name:8s} 多{bull} 空{bear}  | {r['dmi_1h']}/{r['dmi_4h']}/{r['dmi_1d']} | SRSI:{s1h}/{s4h}/{s1d} | {near_st} | {st_info}")
    
    # 3. 获取活跃持仓
    active = get_positions()
    local_pos = load_local_positions()
    
    # 合并：OKX持仓 + 本地跟踪的额外信息
    active_with_info = []
    for p in active:
        entry_time = "unknown"
        for lp in local_pos:
            if lp["instId"] == p["instId"] and lp["posSide"] == p["posSide"]:
                entry_time = lp.get("entry_time", "unknown")
                break
        active_with_info.append({**p, "entry_time": entry_time})
    
    print(f"\n📋 当前持仓: {len(active)} 个")
    for p in active:
        pnl = float(p.get("upl", 0))
        pnl_str = f"{'+' if pnl>=0 else ''}{pnl:.2f}"
        print(f"  {p['instId'].replace('-USDT-SWAP',''):8s} {p['posSide']:5s} {p['pos']}张 | UPL:{pnl_str}")
    
    # 4. 检测入场信号
    signals = detect_signals(results, active)
    print(f"\n🎯 入场信号: {len(signals)} 个")
    
    if dry_run or not signals:
        # 推送扫描报告（即使无信号也推）
        now_str = now.strftime("%m-%d %H:%M")
        push_scan_report(results, now_str)
        return results, signals, active
    
    # 5. 获取余额
    equity = get_balance()
    print(f"\n💰 账户权益: {equity:.2f} USDT")
    
    # 6. 执行入场
    for sig in signals:
        if len(active_with_info) >= 5:  # 最多同时5个仓位
            print(f"  ⚠️ 已达最大持仓数，跳过 {sig['symbol']}")
            continue
        
        ct_val = CT_VAL.get(sig["symbol"], 1)
        size = calc_position_size(equity, sig["price"], sig["stop_loss"], ct_val)
        
        print(f"\n{'▶'*30}")
        print(f"  🟢 入场信号: {sig['symbol'].replace('-USDT-SWAP','')} {sig['direction']}")
        print(f"     评分: {sig['score']} | 价格: {sig['price']} | ST: {sig['st_trend']}@{sig['st_line']:.2f}")
        print(f"     距ST: {sig['near_pct']:.2f}% | 止损: {sig['stop_loss']:.2f} | 止盈目标: {sig['tp_target']:.2f}")
        print(f"     仓位: {size}张 | 合约面值: {ct_val}")
        
        if dry_run:
            continue
        
        ord_id, err = place_order(sig["symbol"], sig["direction"], size,
                                   sig["stop_loss"], sig["tp_target"])
        if err:
            print(f"  ❌ 下单失败: {err}")
        else:
            print(f"  ✅ 已下单: {ord_id}")
            # 推送交易通知
            push_trade_alert("入场", sig["symbol"], sig["direction"], sig["price"], size,
                           f"止损:{sig['stop_loss']:.2f} 止盈:{sig['tp_target']:.4f} [{now.strftime('%m/%d %H:%M')}]" if False else f"止损:{sig['stop_loss']:.2f} 止盈:{sig['tp_target']:.4f}")
            log_trade(
                sig["time"], sig["symbol"], sig["direction"],
                sig["price"], size, sig["stop_loss"]
            )
            # 保存持仓跟踪信息
            local_pos.append({
                "instId": sig["symbol"],
                "posSide": sig["direction"],
                "entry_time": sig["time"],
                "entry_price": sig["price"],
                "stop_loss": sig["stop_loss"],
                "tp_target": sig["tp_target"],
                "atr": sig["atr"],
                "size": size,
            })
            save_positions(local_pos)
    
    # 7. 检查已有持仓是否需要止盈重扫
    print(f"\n📐 持仓检查:")
    for i, pos in enumerate(active_with_info):
        symbol = pos["instId"]
        pos_side = pos["posSide"]
        mark_px = float(pos.get("markPx", 0))
        upl = float(pos.get("upl", 0))
        lp = next((p for p in local_pos if p["instId"] == symbol and p["posSide"] == pos_side), None)
        
        if not lp or mark_px == 0:
            continue
        
        tp_target = lp.get("tp_target", 0)
        stop_loss = lp.get("stop_loss", 0)
        direction = pos_side
        
        # 检查止损
        hit_sl = False
        if direction == "long" and mark_px <= stop_loss:
            hit_sl = True
        elif direction == "short" and mark_px >= stop_loss:
            hit_sl = True
        
        # 检查止盈
        hit_tp = False
        if direction == "long" and mark_px >= tp_target:
            hit_tp = True
        elif direction == "short" and mark_px <= tp_target:
            hit_tp = True
        
        name = symbol.replace("-USDT-SWAP", "")
        print(f"  {name:8s} {direction:5s} | 标记价:{mark_px:.2f} | 止损:{stop_loss:.2f} | 止盈:{tp_target:.2f} | UPL:{upl:+.2f}")
        
        if hit_sl:
            print(f"    🔴 触发止损！平仓")
            close_position(symbol, pos_side)
            log_trade(lp["entry_time"], symbol, direction, lp["entry_price"], lp["size"],
                      stop_loss, exit_time=now.isoformat(), exit_price=mark_px,
                      exit_reason="stop_loss", pnl=upl)
            push_trade_alert("止损平仓", symbol, direction, mark_px, lp["size"],
                           f"UPL:{upl:+.2f} [模式: 模拟盘]")
            local_pos = [p for p in local_pos if not (p["instId"]==symbol and p["posSide"]==pos_side)]
            save_positions(local_pos)
        
        elif hit_tp:
            print(f"    🎯 到达止盈目标！重新扫描...")
            decision, my_score, opp_score = rescan_decision(symbol, direction, 0)
            print(f"    重扫: 我方{my_score} vs 对方{opp_score} → {decision}")
            
            if decision == "close_all":
                print(f"    🔴 入场分 < 反向分，全部平仓")
                close_position(symbol, pos_side)
                log_trade(lp["entry_time"], symbol, direction, lp["entry_price"], lp["size"],
                          stop_loss, exit_time=now.isoformat(), exit_price=mark_px,
                          exit_reason="tp_close_all", pnl=upl)
                push_trade_alert("止盈全平", symbol, direction, mark_px, lp["size"],
                               f"UPL:{upl:+.2f} | 我方{my_score} vs 对方{opp_score} [模式: 模拟盘]")
                local_pos = [p for p in local_pos if not (p["instId"]==symbol and p["posSide"]==pos_side)]
            
            elif decision == "move_stop":
                print(f"    🟡 信号仍然强势，移动止损到保本")
                entry = lp["entry_price"]
                # 移动止损到入场价（保本）
                lp["stop_loss"] = entry
                # 同时更新止盈（移动止盈 = 2x ATR 距离）
                atr = lp.get("atr", entry * 0.01)
                if direction == "long":
                    lp["tp_target"] = mark_px + 2 * atr
                else:
                    lp["tp_target"] = mark_px - 2 * atr
                print(f"    新止损: 保本{entry:.2f} | 新止盈: {lp['tp_target']:.2f}")
            
            elif decision == "half_close":
                half_size = max(1, lp["size"] // 2)
                print(f"    🟡 多空均衡，平仓一半 ({half_size}张)")
                close_position(symbol, pos_side, half_size)
                push_trade_alert("止盈平半", symbol, direction, mark_px, half_size,
                               f"UPL:{upl:+.2f} | 剩余{lp['size']-half_size}张移保本 [模式: 模拟盘]")
                # 更新剩余一半的止损为保本
                entry = lp["entry_price"]
                lp["stop_loss"] = entry
                lp["size"] = lp["size"] - half_size
                atr = lp.get("atr", entry * 0.01)
                if direction == "long":
                    lp["tp_target"] = mark_px + 2 * atr
                else:
                    lp["tp_target"] = mark_px - 2 * atr
                print(f"    剩余{lp['size']}张 | 止损: 保本{entry:.2f} | 新止盈: {lp['tp_target']:.2f}")
            
            save_positions(local_pos)
    
    # 推送扫描报告
    now_str = now.strftime("%m-%d %H:%M")
    push_scan_report(results, now_str)
    
    return results, signals, active


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="仅扫描不交易")
    p.add_argument("--loop", action="store_true", help="持续监控")
    p.add_argument("--interval", type=int, default=900, help="扫描间隔(秒) 默认15分钟")
    args = p.parse_args()
    
    if args.loop:
        print("🔄 进入持续监控模式...")
        while True:
            run_once(dry_run=args.dry_run)
            print(f"\n⏳ 等待 {args.interval} 秒后下一次扫描...")
            time.sleep(args.interval)
    else:
        run_once(dry_run=args.dry_run)
