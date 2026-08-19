#!/usr/bin/env python3
"""
SRSI 双周期极值 + 4h 方向区 + 市场结构方向共振 (TrendWatch)
规则（用户定义）：
  多头：1d SRSI < 20  且 1h SRSI < 20  且 4h SRSI 在明显下半区[0,40]  且 1h 与 4h 市场结构方向一致（均上行）
  空头：1d SRSI > 80  且 1h SRSI > 80  且 4h SRSI 在明显上半区[60,100]  且 1h 与 4h 市场结构方向一致（均下行）
  4h 方向区：多头要求 SRSI(4h) ∈ [0,40]（明显下半区，动量明确未超买、有上行空间）；空头要求 SRSI(4h) ∈ [60,100]（明显上半区，动量明确未超卖、有下行空间）
  方向（结构法）：用 swing 高低点判断市场结构（HH/HL、LH/LL），并要求连续两个 swing 高低点差值超过最小摆幅(min_pct)以剔除噪声小波动
    上行(1) = 最近两个 swing high 走高(HH) 且 最近两个 swing low 走高(HL)，且两组差值均 > min_pct*价格量级
    下行(-1)= 最近两个 swing high 走低(LH) 且 最近两个 swing low 走低(LL)，且两组差值均 > min_pct*价格量级
    否则(结构混合/样本不足/摆幅不足) = 0（横盘，不计入方向）
  说明：仅保留用户要求的硬条件（1d+1h SRSI 极值 + 4h 方向区 + 1h/4h 结构方向一致）；结构方向带最小摆幅过滤(min_pct)以剔除噪声小波动。
扫描池复用 Top100(成交量) + 新币50，推送标题 TrendWatch。
去重：同一 CST 日期内同一币种只推送一次（状态存于 pushed_state.json）。
"""
import requests, time, os, json
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pushed_state.json")

SWING_P = 5  # swing 判定左右窗口（根）
MIN_SWING_PCT_1H = 0.003  # 1h 结构最小摆幅（相对价格，0.3%）——过滤噪声小波动
MIN_SWING_PCT_4H = 0.005  # 4h 结构最小摆幅（相对价格，0.5%）——过滤噪声小波动

def cst_date():
    """当前 CST(UTC+8) 日期字符串，用于按天去重"""
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

def load_pushed():
    """读取今天已推送过的币种集合（仅保留当天键，跨天自动重置）"""
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
    for _ in range(3):
        try:
            r = requests.get(f"{OKX}/api/v5/market/candles",
                             params={"instId": inst, "bar": bar, "limit": limit}, timeout=12)
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

def check_signal(s1, s1h, s4, d1h, d4h):
    """双周期 SRSI 极值 + 4h 方向区 + 1h/4h 市场结构方向一致。
    多：1d<20 且 1h<20 且 SRSI(4h)∈[0,40] 且 1h 上行(HH+HL) & 4h 上行(HH+HL)
    空：1d>80 且 1h>80 且 SRSI(4h)∈[60,100] 且 1h 下行(LH+LL) & 4h 下行(LH+LL)
    方向必须同向且非横盘；SRSI 极值方向与交易方向一致。
    """
    # 4h 方向区：多头要求明显下半区[0,40](动量明确未超买、有上行空间)，空头要求明显上半区[60,100](动量明确未超卖、有下行空间)
    if d1h == 1 and d4h == 1 and s1 < 20 and s1h < 20 and 0 <= s4 <= 40:
        return "多"
    if d1h == -1 and d4h == -1 and s1 > 80 and s1h > 80 and 60 <= s4 <= 100:
        return "空"
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
    vol_top = [i[0] for i in items[:100]]

    new_coins = []
    try:
        r2 = requests.get(f"{OKX}/api/v5/public/instruments", params={"instType": "SWAP"}, timeout=15)
        d2 = r2.json()
        if d2.get("code") == "0":
            insts = []
            for it in d2["data"]:
                if "USDT" in it["instId"] and not any(x in it["instId"] for x in EXCL):
                    lt = it.get("listTime") or 0
                    insts.append((it["instId"], int(lt)))
            insts.sort(key=lambda x: -x[1])
            new_coins = [i[0] for i in insts[:50]]
    except Exception as e:
        print(f"new-coins fetch failed: {e}")

    seen = set(); syms = []
    for s in vol_top + new_coins:
        if s not in seen:
            seen.add(s); syms.append(s)
    print(f"Scan pool: {len(vol_top)} vol-top + {len(new_coins)} new = {len(syms)} unique...")

    cands = []
    for s in syms:
        name = s.replace("-USDT-SWAP", "")
        c1d = get_candles(s, "1D", 200)
        c4h = get_candles(s, "4H", 100)
        c1h = get_candles(s, "1H", 100)
        if not c1d or not c4h or not c1h:
            continue
        closes1 = [c["c"] for c in c1d]
        closes4 = [c["c"] for c in c4h]
        closes1h = [c["c"] for c in c1h]
        highs1h = [c["h"] for c in c1h]
        lows1h = [c["l"] for c in c1h]
        highs4 = [c["h"] for c in c4h]
        lows4 = [c["l"] for c in c4h]
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
        # 方向：1h 与 4h 市场结构（HH/HL/LH/LL），带最小摆幅过滤
        d1h = structure_dir(highs1h, lows1h, min_pct=MIN_SWING_PCT_1H)
        d4h = structure_dir(highs4, lows4, min_pct=MIN_SWING_PCT_4H)
        dirn = check_signal(s1, s1h, s4, d1h, d4h)
        if dirn is None:
            continue
        cands.append({
            "name": name, "dir": dirn,
            "s1": round(s1, 1), "s1h": round(s1h, 1), "s4": round(s4, 1),
            "d1h": d1h, "d4h": d4h,
            "price": closes1[-1],
        })
        time.sleep(0.05)

    token = os.environ.get("PUSHPLUS_TOKEN", "")
    if not token:
        tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pushplus_token")
        if os.path.exists(tp):
            token = open(tp).read().strip()

    # 同日同币去重：今天已推送过的币种不再重复推送
    pushed = load_pushed()
    new_cands = [c for c in cands if c["name"] not in pushed]
    if cands and not new_cands:
        print(f"All {len(cands)} signal(s) already pushed today, skip.")

    # 多头在前、空头在后，组内按 SRSI(1d) 升序（越超卖靠前）—空头按 SRSI(1d) 降序（越超买靠前）
    def _sort_key(x):
        base = 0 if x["dir"] == "多" else 1
        s1k = x["s1"] if x["dir"] == "多" else -x["s1"]
        return (base, -s1k if x["dir"] == "多" else s1k)
    new_cands.sort(key=_sort_key)

    if new_cands:
        print(f"\nNEW SIGNALS({len(new_cands)}):")
        for r in new_cands:
            print(f"  {r['name']}{r['dir']} SRSI(1d/1h/4h)={r['s1']}/{r['s1h']}/{r['s4']} str(1h/4h)={r['d1h']}/{r['d4h']} price={r['price']}")

    if token and new_cands:
        h = '<div style="font-family:-apple-system,sans-serif;max-width:560px">'
        h += '<h3 style="margin:0 0 6px">SRSI 双周期极值 + 结构方向共振 (TrendWatch)</h3>'
        h += f'<div style="font-size:11px;color:#666;margin-bottom:6px">多:1d&lt;20 &amp; 1h&lt;20 &amp; 4h∈[0,40] &amp; 1h/4h结构同向上行(HH+HL) ｜ 空:1d&gt;80 &amp; 1h&gt;80 &amp; 4h∈[60,100] &amp; 1h/4h结构同向下行(LH+LL) ｜ 当日同币去重　共 {len(new_cands)} 个</div>'
        for r in new_cands:
            color = "#27ae60" if r["dir"] == "多" else "#e74c3c"
            p = fmt_p(r["price"], f"{r['name']}-USDT-SWAP")
            h += f'<div style="margin:5px 0;padding:6px;background:#fff;border-left:3px solid {color}">'
            h += f'<b>{r["name"]}</b> <span style="color:{color}">{r["dir"]}</span> {p}<br>'
            h += f'<span style="font-size:11px;color:#333">SRSI(1d/1h/4h)={r["s1"]}/{r["s1h"]}/{r["s4"]} | 结构(1h/4h)={r["d1h"]}/{r["d4h"]}</span>'
            h += '</div>'
        h += '</div>'
        pl = {"token": token, "title": "TrendWatch", "content": h, "template": "html"}
        try:
            rp = requests.post("http://www.pushplus.plus/send", json=pl, timeout=10)
            print("Push:", rp.json().get("code"))
            # 推送成功 → 记录今日已推币种，便于跨运行去重，并标记需提交状态文件
            pushed.update(c["name"] for c in new_cands)
            with open(STATE_FILE, "w") as f:
                json.dump({cst_date(): sorted(pushed)}, f)
            open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".need_commit"), "w").close()
        except Exception as e:
            print("Push error:", e)
    return cands

if __name__ == "__main__":
    main()
