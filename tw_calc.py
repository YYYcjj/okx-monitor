#!/usr/bin/env python3
# TrendWatch 指标与信号判定层（2026-09-04 从 scan_trend.py 拆分，逻辑未改）
from tw_conf import *

def calc_rsi(closes, period=14):
    n = len(closes)
    if n < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains[:period]) / period; al = sum(losses[:period]) / period
    rv = [100 if al == 0 else 100 - 100 / (1 + ag / al)]
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        rv.append(100 if al == 0 else 100 - 100 / (1 + ag / al))
    return rv


def calc_stoch_rsi_series(closes, rsi_period=14, stoch_period=14, sk=3):
    """返回 SRSI 序列(%K 平滑)，便于取末值"""
    rsi = calc_rsi(closes, rsi_period)
    if not rsi or len(rsi) < stoch_period + sk:
        return None
    kr = []
    for i in range(stoch_period - 1, len(rsi)):
        w = rsi[i - stoch_period + 1:i + 1]; lo, hi = min(w), max(w)
        kr.append(50 if hi == lo else (rsi[i] - lo) / (hi - lo) * 100)
    kv = []
    for i in range(sk - 1, len(kr)):
        kv.append(sum(kr[i - sk + 1:i + 1]) / sk)
    return kv


def srsi_last(kv):
    """返回末值"""
    return kv[-1] if kv else None


def calc_tr(highs, lows, closes):
    """真实波幅序列（Wilder）"""
    n = len(closes)
    tr = [0.0]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i],
                      abs(highs[i] - closes[i - 1]),
                      abs(lows[i] - closes[i - 1])))
    return tr


def calc_adx(highs, lows, closes, period=ADX_PERIOD):
    """Wilder 平滑 ADX，返回末值（无方向趋势强度）"""
    n = len(closes)
    if n < period + 1:
        return None
    pdm = [0.0]
    mdm = [0.0]
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
    tr = calc_tr(highs, lows, closes)
    atr = sum(tr[1:period + 1]) / period
    pdi = sum(pdm[1:period + 1]) / period
    mdi = sum(mdm[1:period + 1]) / period
    dxs = []
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + tr[i]) / period
        pdi = (pdi * (period - 1) + pdm[i]) / period
        mdi = (mdi * (period - 1) + mdm[i]) / period
        di_sum = pdi + mdi
        dxs.append(100 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0.0)
    if len(dxs) < period:
        return None
    adx = sum(dxs[:period]) / period
    for i in range(period, len(dxs)):
        adx = (adx * (period - 1) + dxs[i]) / period
    return adx


def calc_atr(highs, lows, closes, period=ATR_PERIOD):
    """Wilder 平滑 ATR，返回末值"""
    tr = calc_tr(highs, lows, closes)
    if len(tr) < period + 1:
        return None
    atr = sum(tr[1:period + 1]) / period
    for i in range(period + 1, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
    return atr


def wick_ok(highs, lows, opens, closes, lookback=WICK_LOOKBACK,
            avg_max=WICK_AVG_MAX, spike_max=WICK_SPIKE_MAX):
    """剔除极端插针币：最近 lookback 根 K 线，每根取较大影线占比(max(上影,下影)/实体)，
    要求平均占比<avg_max 且单根最大<=spike_max。
    修复(2026-08-31)：实体过小(十字星)原分支 ratio=(h-l)/(h*1e-6)≈上千倍必杀，
    改为用中间价 0.1% 作实体下限(eff_body)，使 doji 的 ratio 回到合理量级(range/price 量级)，不再误杀。"""
    n = len(closes)
    if n < lookback:
        return True
    ratios = []
    for i in range(n - lookback, n):
        o, c = opens[i], closes[i]
        h, l = highs[i], lows[i]
        body = abs(c - o)
        ref = (h + l) / 2.0
        eff_body = body if body > ref * 1e-3 else ref * 1e-3  # 实体下限=中间价 0.1%，防 doji 爆量
        up = (h - max(o, c)) / eff_body
        dn = (min(o, c) - l) / eff_body
        ratios.append(max(up, dn))
    avg = sum(ratios) / len(ratios)
    mx = max(ratios)
    return avg < avg_max and mx <= spike_max


def find_swings(highs, lows, p=SWING_P):
    """返回 swing 高低点列表，元素为 (index, price)。
    swing high: 中间根为左右各 p 根窗口内的最高价。
    swing low : 中间根为左右各 p 根窗口内的最低价。
    注：平顶/平底区多根并列最高会都被标记，但后续结构比较用严格 >/<，
        并列相等会判为 0（横盘），避免在震荡区误判方向。"""
    sh, sl = [], []
    n = len(highs)
    for i in range(p, n - p):
        if highs[i] >= max(highs[i - p:i]) and highs[i] >= max(highs[i + 1:i + p + 1]):
            sh.append((i, highs[i]))
        if lows[i] <= min(lows[i - p:i]) and lows[i] <= min(lows[i + 1:i + p + 1]):
            sl.append((i, lows[i]))
    return sh, sl


def structure_dir(highs, lows, p=SWING_P, min_pct=0.003):
    """市场结构方向（HH/HL/LH/LL），带最小摆幅过滤：
    上行(1) = 最近两个 swing high 走高(HH) 且 最近两个 swing low 走高(HL)，且两组差值均 > min_pct*价格量级
    下行(-1)= 最近两个 swing high 走低(LH) 且 最近两个 swing low 走低(LL)，且两组差值均 > min_pct*价格量级
    否则(结构混合/样本不足/摆幅不足) = 0（横盘，不计入方向）
    注：2026-09-05 起作为信号条件（1h/1d 必须共振同向）。"""
    sh, sl = find_swings(highs, lows, p)
    if len(sh) < 2 or len(sl) < 2:
        return 0
    last_sh, prev_sh = sh[-1][1], sh[-2][1]
    last_sl, prev_sl = sl[-1][1], sl[-2][1]
    ref = (last_sh + prev_sh + last_sl + prev_sl) / 4.0
    min_move = ref * min_pct
    if last_sh - prev_sh > min_move and last_sl - prev_sl > min_move:
        return 1
    if prev_sh - last_sh > min_move and prev_sl - last_sl > min_move:
        return -1
    return 0


def near_key_level(price, levels, pct=NEAR_LEVEL_PCT):
    """价格是否贴近日线关键位：与任一 swing 高低点的相对距离 <= pct。
    用于顺势信号判断「处于关键位置」（做多传 swing low、做空传 swing high）。"""
    if price <= 0:
        return False
    for lv in levels:
        if lv and abs(price - lv) / price <= pct:
            return True
    return False


def classify(s1, s1h, adx1h, atr_ratio, wick_ok_flag, d1h, d1d, price, sh1d, sl1d):
    """统一顺势信号（2026-09-05 改版）：
    核心：1日线关键位置 + 1h 与 1d 共振(方向相同) + SRSI 同向。
    两类触发（方向均由 1h/1d 共振决定）：
      回调：1d SRSI 极端（1d 多结构+SRSI<20→多；1d 空结构+SRSI>80→空）
      趋势：1h SRSI 极端（1h 多结构+SRSI<20→多；1h 空结构+SRSI>80→空）
    共用要求（不满足即剔除）：
      - 1d 结构方向 == 1h 结构方向 == 信号方向（共振同向，横盘 0 淘汰）
      - 价格贴近日线关键位（做多近 swing low 支撑；做空近 swing high 阻力，NEAR_LEVEL_PCT 内）
      - 1h ADX>20、ATR/价 在 (ATR_MIN_RATIO, ATR_MAX_RATIO)
      - 插针门（wick_ok_flag）
    保险：非触发侧 SRSI 不在反向极端（做多时 1h/1d 均不>80；做空时均不<20）
    目标位仅展示、不参与过滤（用户定）。
    返回 (类型, 方向, 附加信息dict) 或 None。"""
    if adx1h < ADX_THRESHOLD:
        return None
    if not (ATR_MIN_RATIO < atr_ratio < ATR_MAX_RATIO):
        return None
    # 1h 与 1d 必须共振同向（横盘 0 视为不共振，淘汰）
    if d1h != d1d or d1d == 0:
        return None
    dirn = d1d  # 信号方向 = 结构方向（1h/1d 已一致）

    # 关键位置：做多贴近日线 swing low（支撑），做空贴近日线 swing high（阻力）
    if dirn == 1:
        if not near_key_level(price, [p for _, p in sl1d[-2:]]):
            return None
    else:
        if not near_key_level(price, [p for _, p in sh1d[-2:]]):
            return None

    if not wick_ok_flag:
        return None

    def _mk(kind, dn, target):
        """统一附带目标位 / 空间百分比 / 空间相当于几倍 ATR（仅展示）"""
        info = {"tgt": target, "space_pct": None, "space_atr": None}
        if target and price > 0:
            # 按交易方向取符号：多=(目标-现价)/现价，空=(现价-目标)/现价
            sp = (target - price) / price if dn == "多" else (price - target) / price
            info["space_pct"] = sp * 100.0
            info["space_atr"] = sp / atr_ratio if atr_ratio > 0 else None
        return (kind, dn, info)

    # SRSI 同向：任一侧极端即触发；另一侧不能反向极端（保险）
    if dirn == 1:
        triggered = (s1 < SRSI_LOW) or (s1h < SRSI_LOW)
        reverse = (s1 > SRSI_HIGH) or (s1h > SRSI_HIGH)
        if not triggered or reverse:
            return None
        kind = "回调" if s1 < SRSI_LOW else "趋势"
        return _mk(kind, "多", sh1d[-1][1] if sh1d else None)
    else:  # dirn == -1
        triggered = (s1 > SRSI_HIGH) or (s1h > SRSI_HIGH)
        reverse = (s1 < SRSI_LOW) or (s1h < SRSI_LOW)
        if not triggered or reverse:
            return None
        kind = "回调" if s1 > SRSI_HIGH else "趋势"
        return _mk(kind, "空", sl1d[-1][1] if sl1d else None)


def fmt_p(p, inst):
    if "BTC" in inst or "ETH" in inst:
        return f"{p:.1f}"
    if p >= 1:
        return f"{p:.2f}"
    if p >= 0.01:
        return f"{p:.4f}"
    return f"{p:.6g}"
