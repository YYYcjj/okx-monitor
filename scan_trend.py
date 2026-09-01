#!/usr/bin/env python3
"""
TrendWatch —— 两类信号扫描（2026-09-02 改版）

类型1 趋势回调（顺势中继）：
    主信号：1h SRSI 极值（<20 多 / >80 空）—— 只要 1h，1d 不再要求极值
    方向  ：4h 与 1d 市场结构同向（多 = HH/HL，空 = LH/LL）
    保险  ：1d SRSI 不在反向极端（做多时 1d SRSI <= 80；做空时 1d SRSI >= 20）

类型2 反转（逆势，必须 1h 确认）：
    触发：1d SRSI 处于「同方向」极端
          日线空头结构 且 1d SRSI < 20 → 反转多（回测发现此类常大涨）
          日线多头结构 且 1d SRSI > 80 → 反转空
    位置：价格贴近日线关键位（最近两个 swing 高低点，NEAR_LEVEL_PCT 以内）
    确认：1h CHoCH —— 取最近 CONFIRM_LOOKBACK 根内的最低点/最高点作本段起点，
          再取其后形成的最后一个反弹高点(LH)/回踩低点(HL)；
          最近 CONFIRM_MAX_BARS_1H 根内收盘站上(多)/跌破(空)该位才算确认

质量门（两类共用，沿用既定标准，要求不变）：
    1h ADX > 20        ：确认有足够趋势动能（滤掉无趋势震荡）
    无极端插针(wick)   ：最近 WICK_LOOKBACK 根平均影线占比<WICK_AVG_MAX 且单根最大<=WICK_SPIKE_MAX
    ATR/价格 > 阈值     ：波动足够、有交易空间（ATR_MIN_RATIO，默认 0.5%）

扫描池：成交量前 100 的 USDT 永续合约。
去重：同一 CST 日期内同一「币种 + 类型 + 方向」只推送一次（状态存于 pushed_state.json）。
股票相关币种（代币化股票 + 名称含股票关键词）已加入黑名单，扫描时跳过、不推送（2026-08-25）。
"""
import requests, time, os, json
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pushed_state.json")

SWING_P = 5  # swing 判定左右窗口（根）
MIN_SWING_PCT_1H = 0.005  # 1h 结构最小摆幅（相对价格，0.5%）——过滤噪声小波动（2026-09-01 由 0.3% 收紧至 0.5%）
MIN_SWING_PCT_4H = 0.005  # 4h 结构最小摆幅（相对价格，0.5%）——过滤噪声小波动
MIN_SWING_PCT_1D = 0.01   # 1d 结构最小摆幅（相对价格，1%）——日线级，过滤噪声（2026-09-01 新增方向过滤用）

# ---- SRSI 极值区（2026-09-02 改版：类型1 只看 1h，类型2 只看 1d）----
SRSI_LOW = 20             # SRSI 低于此值为超卖
SRSI_HIGH = 80            # SRSI 高于此值为超买
NEAR_LEVEL_PCT = 0.015    # 价格与日线关键位(swing 点)的相对距离 <= 1.5% 视为「遇到阻力/支撑」
CONFIRM_SWING_P = 2       # 1h 确认专用 swing 窗口（比 SWING_P=5 小，否则最新一次反弹高点识别不到）
CONFIRM_LOOKBACK = 20     # 1h 确认在最近 20 根内找「本段起点」（最低点 / 最高点）
CONFIRM_MAX_BARS_1H = 4   # 类型2 的 1h 突破必须发生在最近 4 根内（避免追已经跑远的）

# ---- 质量门阈值（沿用主策略/早期版既定标准，要求不变） ----
ADX_PERIOD = 14
ADX_THRESHOLD = 20      # 1h ADX > 20 确认趋势动能足够
ATR_PERIOD = 14
ATR_MIN_RATIO = 0.005   # ATR/价格 > 0.5%，波动足够才有交易空间（可微调）
WICK_LOOKBACK = 20      # 最近 20 根 1h K 线评估插针
WICK_AVG_MAX = 6.0      # 平均影线占比上限（放宽：原 4.0 对 1h K 线过严，单根插针即误杀）
WICK_SPIKE_MAX = 10.0    # 单根最大影线占比上限（放宽：保留对真实插针泵/砸的过滤）

# ---- 股票相关币种黑名单（不推送）----
# 用户要求（2026-08-25）：TrendWatch 不推荐股票相关币种。
# 两类：①代币化股票（常见美股 ticker）；②名称含股票关键词。
STOCK_TICKERS = {
    # 科技 / 美股龙头
    "TSLA","AAPL","NVDA","AMZN","GOOGL","GOOG","META","FB","MSFT","NFLX",
    "COIN","TWTR","NIO","BABA","JD","PDD","BIDU","XPEV","LCID","RIVN","PLTR",
    "AMD","INTC","IBM","ORCL","CRM","ADBE","PYPL","UBER","LYFT","SNAP","SQ",
    "SHOP","ROKU","PINS","Z","DOCU","OKTA","NOW","TEAM","CRWD","NET","ZS",
    "SNOW","DDOG","MDB","TWLO","ZM","CHWY","ETSY","MRNA","BNTX","PFE","JNJ",
    "KO","PEP","MCD","SBUX","DIS","BA","GE","CAT","WMT","TGT","HD","LOW",
    "COST","XOM","CVX","BAC","JPM","GS","WFC","C","V","MA",
    # 指数 / ETF 类
    "SPY","QQQ","DIA","VOO","IWM","ARKK","UVXY","VIX",
}
STOCK_KEYWORDS = ("STOCK", "SHARE", "EQUITY", "STK", "股票")

def is_stock_related(name: str) -> bool:
    """判断币种是否为股票相关（代币化股票或名称含股票关键词），命中则不推送。"""
    n = name.upper()
    if n in STOCK_TICKERS:
        return True
    return any(k in n for k in STOCK_KEYWORDS)

def cst_date():
    """当前 CST(UTC+8) 日期字符串，用于按天去重"""
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

def load_pushed():
    """读取今天已推送过的信号键集合（仅保留当天键，跨天自动重置）"""
    today = cst_date()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                st = json.load(f)
            if isinstance(st, dict):
                return set(st.get(today, []))
        except Exception:
            pass
    return set()

def get_candles(inst, bar, limit=100):
    for _ in range(4):
        try:
            r = requests.get(f"{OKX}/api/v5/market/candles",
                             params={"instId": inst, "bar": bar, "limit": limit}, timeout=12)
            if r.status_code == 429:
                time.sleep(2.0); continue  # 触发频率限制，退避后重试
            d = r.json()
            if d.get("code") == "0":
                candles = []
                for c in d["data"]:
                    candles.append({"h": float(c[2]), "l": float(c[3]),
                                    "c": float(c[4]), "o": float(c[1]), "v": float(c[5])})
                candles.reverse()
                return candles
        except Exception:
            time.sleep(0.5)
        time.sleep(0.06)  # 轻量限流，避免触发 OKX 公共 API 频率限制
    return None

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


def classify(s1, s1h, adx1h, atr_ratio, wick_ok_flag, d4h, d1d,
             price, sh1d, sl1d, highs1h, lows1h, closes1h):
    """两类信号判定（2026-09-02 改版），返回 (类型, 方向, 附加信息dict) 或 None。
    类型1 回调：1h SRSI 极值 + 4h/1d 结构同向 + 1d SRSI 不在反向极端
    类型2 反转：1d SRSI 处于同方向极端 + 贴近日线关键位 + 1h CHoCH 突破确认
    两类共用质量门：1h ADX>20、无极端插针、ATR/价>ATR_MIN_RATIO。"""
    if not wick_ok_flag:
        return None
    if adx1h < ADX_THRESHOLD:
        return None
    if atr_ratio < ATR_MIN_RATIO:
        return None

    levels_1d = [p for _, p in sh1d[-2:]] + [p for _, p in sl1d[-2:]]

    # ---- 类型1：趋势回调（顺势中继）----
    if s1h < SRSI_LOW and d4h == 1 and d1d == 1 and s1 <= SRSI_HIGH:
        return ("回调", "多", {})
    if s1h > SRSI_HIGH and d4h == -1 and d1d == -1 and s1 >= SRSI_LOW:
        return ("回调", "空", {})

    # ---- 类型2：反转（逆势，必须 1h 确认）----
    if d1d == -1 and s1 < SRSI_LOW and near_key_level(price, levels_1d):
        ok, lvl, ago = confirm_1h(highs1h, lows1h, closes1h, 1)
        if ok:
            return ("反转", "多", {
                "break_lvl": lvl, "ago": ago,
                "tgt": sh1d[-1][1] if sh1d else None,   # 参考目标 = 日线最近的 LH
            })
    if d1d == 1 and s1 > SRSI_HIGH and near_key_level(price, levels_1d):
        ok, lvl, ago = confirm_1h(highs1h, lows1h, closes1h, -1)
        if ok:
            return ("反转", "空", {
                "break_lvl": lvl, "ago": ago,
                "tgt": sl1d[-1][1] if sl1d else None,   # 参考目标 = 日线最近的 HL
            })
    return None

def fmt_p(p, inst):
    if "BTC" in inst or "ETH" in inst:
        return f"{p:.1f}"
    if p >= 1:
        return f"{p:.2f}"
    if p >= 0.01:
        return f"{p:.4f}"
    return f"{p:.6g}"

def main():
    EXCL = ["BRL", "EUR", "TRY", "DAI", "USDC", "RUB"]
    r = requests.get(f"{OKX}/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=15)
    d = r.json()
    if d.get("code") != "0":
        print("Failed:", d); return
    items = [(t["instId"], float(t.get("volCcy24h", 0))) for t in d["data"]
             if "USDT" in t["instId"] and not any(x in t["instId"] for x in EXCL)]
    items.sort(key=lambda x: -x[1])
    vol_top = [i[0] for i in items[:100]]  # 扫描成交量前 100（2026-09-01 由 50 放宽至 100）

    new_coins = []  # 不再扫描新币池，只保留成交量前 100

    seen = set(); syms = []
    for s in vol_top + new_coins:
        if s not in seen:
            seen.add(s); syms.append(s)
    print(f"Scan pool: {len(vol_top)} vol-top + {len(new_coins)} new = {len(syms)} unique...")

    cands = []
    skipped_stock = 0
    for s in syms:
        name = s.replace("-USDT-SWAP", "")
        if is_stock_related(name):
            skipped_stock += 1
            continue
        c1d = get_candles(s, "1D", 200)
        c4h = get_candles(s, "4H", 100)
        c1h = get_candles(s, "1H", 100)
        if not c1d or not c4h or not c1h:
            continue
        closes1 = [c["c"] for c in c1d]
        closes4 = [c["c"] for c in c4h]
        closes1h = [c["c"] for c in c1h]
        opens1h = [c["o"] for c in c1h]
        highs1h = [c["h"] for c in c1h]
        lows1h = [c["l"] for c in c1h]
        highs4 = [c["h"] for c in c4h]
        lows4 = [c["l"] for c in c4h]
        highs1d = [c["h"] for c in c1d]
        lows1d = [c["l"] for c in c1d]
        kv1 = calc_stoch_rsi_series(closes1)
        kv1h = calc_stoch_rsi_series(closes1h)
        kv4 = calc_stoch_rsi_series(closes4)
        if kv1 is None or kv1h is None or kv4 is None:
            continue
        s1 = srsi_last(kv1)
        s1h = srsi_last(kv1h)
        s4 = srsi_last(kv4)
        if s1 is None or s1h is None or s4 is None:
            continue
        # 质量门指标（1h）
        atr1h = calc_atr(highs1h, lows1h, closes1h)
        adx1h = calc_adx(highs1h, lows1h, closes1h)
        if atr1h is None or adx1h is None:
            continue
        atr_ratio = atr1h / closes1h[-1] if closes1h[-1] > 0 else 0.0
        wflag = wick_ok(highs1h, lows1h, opens1h, closes1h)
        # 结构方向：4h/1d 用于类型1 同向过滤（2026-09-02 改版），1h 仅展示参考
        d1h = structure_dir(highs1h, lows1h, min_pct=MIN_SWING_PCT_1H)
        d4h = structure_dir(highs4, lows4, min_pct=MIN_SWING_PCT_4H)
        d1d = structure_dir(highs1d, lows1d, min_pct=MIN_SWING_PCT_1D)
        # 日线 swing 点：类型2 用作「关键位」与参考目标
        sh1d, sl1d = find_swings(highs1d, lows1d, p=SWING_P)
        res = classify(s1, s1h, adx1h, atr_ratio, wflag, d4h, d1d,
                       closes1[-1], sh1d, sl1d, highs1h, lows1h, closes1h)
        if res is None:
            continue
        kind, dirn, extra = res
        cands.append({
            "name": name, "kind": kind, "dir": dirn,
            "s1": round(s1, 1), "s1h": round(s1h, 1), "s4": round(s4, 1),
            "d1h": d1h, "d4h": d4h, "d1d": d1d,
            "adx": round(adx1h, 1), "atrr": atr_ratio,
            "price": closes1[-1],
            "break_lvl": extra.get("break_lvl"),
            "ago": extra.get("ago"),
            "tgt": extra.get("tgt"),
        })
        time.sleep(0.05)

    print(f"Skipped stock-related symbols: {skipped_stock}")
    token = os.environ.get("PUSHPLUS_TOKEN", "")
    if not token:
        tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pushplus_token")
        if os.path.exists(tp):
            token = open(tp).read().strip()

    # 同日去重：键为「币种|类型方向」，同一币当天可以分别推回调与反转
    def _dedup_key(c):
        return f"{c['name']}|{c['kind']}{c['dir']}"
    pushed = load_pushed()
    new_cands = [c for c in cands if _dedup_key(c) not in pushed]
    if cands and not new_cands:
        print(f"All {len(cands)} signal(s) already pushed today, skip.")

    # 排序：回调在前、反转在后；组内多在前、空在后；再按主信号 SRSI 排（越极端越靠前）
    def _sort_key(x):
        k = 0 if x["kind"] == "回调" else 1
        base = 0 if x["dir"] == "多" else 1
        v = x["s1h"] if x["kind"] == "回调" else x["s1"]   # 回调看 1h，反转看 1d
        return (k, base, v if x["dir"] == "多" else -v)
    new_cands.sort(key=_sort_key)

    if new_cands:
        print(f"\nNEW SIGNALS({len(new_cands)}):")
        for r in new_cands:
            line = (f"  [{r['kind']}] {r['name']} {r['dir']} "
                    f"SRSI(1d/1h/4h)={r['s1']}/{r['s1h']}/{r['s4']} ADX(1h)={r['adx']:.0f} "
                    f"ATR/价={r['atrr']*100:.2f}% 结构(4h/1d)={r['d4h']}/{r['d1d']} price={r['price']}")
            if r["kind"] == "反转" and r["break_lvl"] is not None:
                ago = "刚突破" if not r["ago"] else f"{r['ago']}根前"
                line += f" | 1h突破位={r['break_lvl']}({ago})"
                if r["tgt"] is not None:
                    line += f" | 参考目标={r['tgt']}"
            print(line)

    if token and new_cands:
        h = '<div style="font-family:-apple-system,sans-serif;max-width:560px">'
        h += '<h3 style="margin:0 0 6px">TrendWatch（回调 / 反转）</h3>'
        h += (f'<div style="font-size:11px;color:#666;margin-bottom:6px">回调：1h SRSI 极值 + 4h/1d 结构同向 ｜ '
              f'反转：1d SRSI 同向极端 + 贴近日线关键位 + 1h 突破确认 ｜ '
              f'质量门：1h ADX&gt;{ADX_THRESHOLD} &amp; 无极端插针 &amp; ATR/价&gt;{ATR_MIN_RATIO*100:.1f}%　共 {len(new_cands)} 个</div>')
        for r in new_cands:
            color = "#27ae60" if r["dir"] == "多" else "#e74c3c"
            kcolor = "#185fa5" if r["kind"] == "回调" else "#b8860b"
            inst = f"{r['name']}-USDT-SWAP"
            p = fmt_p(r["price"], inst)
            h += f'<div style="margin:5px 0;padding:6px;background:#fff;border-left:3px solid {color}">'
            h += (f'<b>{r["name"]}</b> <span style="color:{kcolor}">[{r["kind"]}]</span> '
                  f'<span style="color:{color}">{r["dir"]}</span> {p}<br>')
            h += (f'<span style="font-size:11px;color:#333">SRSI(1d/1h/4h)={r["s1"]}/{r["s1h"]}/{r["s4"]} | '
                  f'ADX(1h)={r["adx"]:.0f} | ATR/价={r["atrr"]*100:.2f}% | 结构(4h/1d)={r["d4h"]}/{r["d1d"]}</span>')
            if r["kind"] == "反转" and r["break_lvl"] is not None:
                ago = "刚突破" if not r["ago"] else f"{r['ago']} 根前"
                seg = (f'<br><span style="font-size:11px;color:{kcolor}">1h 突破位 {fmt_p(r["break_lvl"], inst)}'
                       f'（{ago}）')
                if r["tgt"] is not None:
                    seg += f' | 参考目标 {fmt_p(r["tgt"], inst)}'
                h += seg + '</span>'
            h += '</div>'
        h += '</div>'
        pl = {"token": token, "title": "TrendWatch", "content": h, "template": "html"}
        try:
            rp = requests.post("http://www.pushplus.plus/send", json=pl, timeout=10)
            print("Push:", rp.json().get("code"))
            # 推送成功 → 记录今日已推信号键，便于跨运行去重，并标记需提交状态文件
            pushed.update(_dedup_key(c) for c in new_cands)
            with open(STATE_FILE, "w") as f:
                json.dump({cst_date(): sorted(pushed)}, f)
            open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".need_commit"), "w").close()
        except Exception as e:
            print("Push error:", e)
    return cands

if __name__ == "__main__":
    main()
