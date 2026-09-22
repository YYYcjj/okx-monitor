#!/usr/bin/env python3
# TrendWatch 指标与信号判定层（2026-09-04 从 scan_trend.py 拆分）
# 2026-09-10：classify 移除 1h/1d 结构共振 + 插针门
# 2026-09-13：classify 新增目标空间 >10% 门
# 2026-09-14：classify 新增 4h 结构同向门
# 2026-09-19：撤销 4h 门、恢复 1h 与 1d 共振
# 2026-09-20：按用户选择回到 V2 口径——撤销 1h 同向门（1h/4h 结构仅展示），保留空间 >10% 门
# 2026-09-21：新增 classify_4h（「4H 型」第二类推送）——固定条件不变，方向锚与位置换成 4h
# 2026-09-22：按用户要求**合并为单一策略**——撤销 classify_4h，「1d 型 / 4H 型」两类归一：
#            以日线为锚（①1d 与 1h 方向一致 ②日线关键位 ③日线 SRSI 极端），4h SRSI 仅作反向保险；
#            固定门（ADX / ATR / 空间）不变。
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
    改为用中间价 0.1% 作实体下限(eff_body)，使 doji 的 ratio 回到合理量级(range/price 量级)，不再误杀。
    注：2026-09-10 起不再作为信号过滤门（classify 已移除调用），函数保留备用。"""
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
    注：1d 结构找机会并定方向（2026-09-20 起 1h/4h 结构仅展示、不参与过滤）。"""
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
    """价格是否贴近日线关键位：与任一 swing 高低点的相对距离 <= pct（双向贴靠）。
    用于顺势信号判断「处于关键位置」（做多传 swing low、做空传 swing high）。
    2026-09-07 恢复为 9/5(推12个)行为：破位(越过)后仍在 ±pct 内也算贴近。"""
    if price <= 0:
        return False
    for lv in levels:
        if lv and abs(price - lv) / price <= pct:
            return True
    return False


def classify(s1, s1h, s4h, adx1h, atr_ratio, d1d, d1h,
             price, sh1d, sl1d):
    """统一顺势信号（2026-09-22 起为**单一策略**，取代原先并列的「1d 型 / 4H 型」两类）：
    一句话：**以日线为锚（方向 + 位置 + 触发），1 小时确认方向，4 小时做反向保险。**

    固定门（系统既有质量门，不变）：
        - 1h ADX > ADX_THRESHOLD(20)
        - ATR/价 ∈ (ATR_MIN_RATIO, ATR_MAX_RATIO) = (0.5%, 2%)
        - 目标空间 > MIN_SPACE_PCT(10%)：目标取日线最近 swing 高(多)/低(空)

    策略四条件（须全部满足，任一不满足即淘汰）：
        ① 1日与1小时方向一致：d1d ≠ 0 且 d1h == d1d（任一横盘、或方向相反 → 淘汰）
        ② 日线在关键位置：做多贴日线 swing low（支撑）、做空贴日线 swing high（阻力），
           距离 ≤ NEAR_LEVEL_PCT(±1.5%)
        ③ 日线 SRSI 超买超卖位：做多 s1 < SRSI_LOW(20)；做空 s1 > SRSI_HIGH(80)
        ④ 4小时 SRSI 不在反向极值：做多 s4h ≤ SRSI_HIGH(80)；做空 s4h ≥ SRSI_LOW(20)

    s4h 为 None（4h 数据不足）时保险门无法确认，直接淘汰。
    返回 ("日线", "多"/"空", 附加信息dict) 或 None。
    """
    # ---- 固定门 ----
    if adx1h < ADX_THRESHOLD:
        return None
    if not (ATR_MIN_RATIO < atr_ratio < ATR_MAX_RATIO):
        return None

    # ---- ① 1日与1小时方向一致（横盘 0 淘汰；方向相反淘汰）----
    if d1d == 0 or d1h != d1d:
        return None
    dirn = d1d  # 信号方向 = 日线结构方向（已确认 1h 同向）

    # ---- ② 日线在关键位置 ----
    if dirn == 1:
        if not near_key_level(price, [p for _, p in sl1d[-2:]]):
            return None
    else:
        if not near_key_level(price, [p for _, p in sh1d[-2:]]):
            return None

    # ---- ③ 日线 SRSI 同向极端（触发） + ④ 4h SRSI 不反向极值（保险）----
    if dirn == 1:
        if s1 >= SRSI_LOW:                      # ③ 日线未进入超卖
            return None
        if s4h is None or s4h > SRSI_HIGH:      # ④ 4h 反向极值（超买）
            return None
        target = sh1d[-1][1] if sh1d else None
    else:
        if s1 <= SRSI_HIGH:                     # ③ 日线未进入超买
            return None
        if s4h is None or s4h < SRSI_LOW:       # ④ 4h 反向极值（超卖）
            return None
        target = sl1d[-1][1] if sl1d else None

    # ---- 固定门：目标空间 > MIN_SPACE_PCT ----
    if not target or price <= 0:
        return None
    sp = (target - price) / price if dirn == 1 else (price - target) / price
    if sp * 100.0 <= MIN_SPACE_PCT:
        return None
    return ("日线", "多" if dirn == 1 else "空",
            {"tgt": target, "space_pct": sp * 100.0,
             "space_atr": sp / atr_ratio if atr_ratio > 0 else None})


def fmt_p(p, inst):
    if "BTC" in inst or "ETH" in inst:
        return f"{p:.1f}"
    if p >= 1:
        return f"{p:.2f}"
    if p >= 0.01:
        return f"{p:.4f}"
    return f"{p:.6g}"
