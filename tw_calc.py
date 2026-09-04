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
    否则(结构混合/样本不足/摆幅不足) = 0（横盘，不计入方向）"""
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
    用于类型2 判断「遇到阻力/支撑」——反转不能发生在半空中。"""
    if price <= 0:
        return False
    for lv in levels:
        if lv and abs(price - lv) / price <= pct:
            return True
    return False


def confirm_1h(highs, lows, closes, direction, p=CONFIRM_SWING_P,
               lookback=CONFIRM_LOOKBACK, max_bars=CONFIRM_MAX_BARS_1H):
    """类型2 的 1h 确认（CHoCH，Change of Character）：
    做多(direction=1)：在最近 lookback 根里取「最低点」作为本段起点，再取该点之后形成的
        最后一个 1h 反弹高点（LH）；某根 K 线收盘价站上它 = 第一个 Higher High，
        1h 下跌结构被打断 —— 这是客观事实，可回测。
    做空(direction=-1)：镜像，取最近最高点之后的最后一个回踩低点（HL），收盘跌破 = 第一个 Lower Low。
    注意：swing 必须用小窗口 p=2，否则「最新一次反弹高点」会因左右窗口未闭合而识别不到；
        也不能用「自低点以来的最高点」当突破位，那会让单调上涨中的每一根都算突破。
    返回 (是否确认, 突破位, 发生在几根前)；0 = 刚刚那根突破；未确认为 (False, 参考位, None)。"""
    n = len(closes)
    start = max(0, n - lookback)
    if direction == 1:
        seg = lows[start:]
        if not seg:
            return (False, None, None)
        base_i = start + seg.index(min(seg))
    else:
        seg = highs[start:]
        if not seg:
            return (False, None, None)
        base_i = start + seg.index(max(seg))
    if base_i >= n - 2:
        return (False, None, None)

    sh, sl = find_swings(highs, lows, p=p)
    if direction == 1:
        cands = [(i, v) for i, v in sh if i > base_i]
    else:
        cands = [(i, v) for i, v in sl if i > base_i]
    if not cands:
        return (False, None, None)
    lvl_i, lvl = cands[-1]

    for k in range(max_bars):
        i = n - 1 - k
        if i <= lvl_i or i < 1:
            break
        cur, prev = closes[i], closes[i - 1]
        if direction == 1 and cur > lvl and prev <= lvl:
            return (True, lvl, k)
        if direction == -1 and cur < lvl and prev >= lvl:
            return (True, lvl, k)
    return (False, lvl, None)


def classify(s1, s1h, adx1h, atr_ratio, wick_ok_flag, wick_ok_rev, d4h, d1d,
             price, sh1d, sl1d, highs1h, lows1h, closes1h):
    """两类信号判定（2026-09-02 改版），返回 (类型, 方向, 附加信息dict) 或 None。
    类型1 回调：1h SRSI 极值 + 4h/1d 结构同向 + 1d SRSI 不在反向极端
    类型2 反转：1d SRSI 处于同方向极端 + 贴近日线关键位 + 1h CHoCH 突破确认
    共用质量门：1h ADX>20、ATR/价>ATR_MIN_RATIO。
    插针门分开用：回调用 wick_ok_flag，反转用 wick_ok_rev（阈值已放宽）。
    注：目标位与空间只做展示、不参与过滤 —— 值不值得做由人判断（2026-09-02 用户定）。"""
    if adx1h < ADX_THRESHOLD:
        return None
    if atr_ratio < ATR_MIN_RATIO:
        return None

    levels_1d = [p for _, p in sh1d[-2:]] + [p for _, p in sl1d[-2:]]

    def _mk(kind, dirn, target):
        """统一附带目标位 / 空间百分比 / 空间相当于几倍 ATR（仅展示）"""
        info = {"tgt": target, "break_lvl": None, "ago": None,
                "space_pct": None, "space_atr": None}
        if target and price > 0:
            # 按交易方向取符号：多=(目标-现价)/现价，空=(现价-目标)/现价
            # 正数 = 还有空间；负数 = 目标已被越过（做多已站上前高 / 做空已跌破前低）
            sp = (target - price) / price if dirn == "多" else (price - target) / price
            info["space_pct"] = sp * 100.0
            info["space_atr"] = sp / atr_ratio if atr_ratio > 0 else None
        return (kind, dirn, info)

    # ---- 类型1：趋势回调（顺势中继）----
    if s1h < SRSI_LOW and d4h == 1 and d1d == 1 and s1 <= SRSI_HIGH:
        if not wick_ok_flag:
            return None
        return _mk("回调", "多", sh1d[-1][1] if sh1d else None)
    if s1h > SRSI_HIGH and d4h == -1 and d1d == -1 and s1 >= SRSI_LOW:
        if not wick_ok_flag:
            return None
        return _mk("回调", "空", sl1d[-1][1] if sl1d else None)

    # ---- 类型2：反转（逆势，必须 1h 确认；插针门用放宽后的阈值）----
    if d1d == -1 and s1 < SRSI_LOW and near_key_level(price, levels_1d):
        if not wick_ok_rev:
            return None
        ok, lvl, ago = confirm_1h(highs1h, lows1h, closes1h, 1)
        if ok:
            r = _mk("反转", "多", sh1d[-1][1] if sh1d else None)  # 目标 = 日线最近的 LH
            r[2]["break_lvl"] = lvl
            r[2]["ago"] = ago
            return r
    if d1d == 1 and s1 > SRSI_HIGH and near_key_level(price, levels_1d):
        if not wick_ok_rev:
            return None
        ok, lvl, ago = confirm_1h(highs1h, lows1h, closes1h, -1)
        if ok:
            r = _mk("反转", "空", sl1d[-1][1] if sl1d else None)  # 目标 = 日线最近的 HL
            r[2]["break_lvl"] = lvl
            r[2]["ago"] = ago
            return r
    return None


def fmt_p(p, inst):
    if "BTC" in inst or "ETH" in inst:
        return f"{p:.1f}"
    if p >= 1:
        return f"{p:.2f}"
    if p >= 0.01:
        return f"{p:.4f}"
    return f"{p:.6g}"
