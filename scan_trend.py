#!/usr/bin/env python3
"""
SRSI 双周期极值 + 方向共振 (TrendWatch)
规则（用户定义）：
  多头：1d SRSI < 20  且 1h SRSI < 20  且 1h 价格方向与 4h 价格方向一致（均上行）
  空头：1d SRSI > 80  且 1h SRSI > 80  且 1h 价格方向与 4h 价格方向一致（均下行）
  方向：1h 与 4h 均取近 look 根收盘价的线性斜率方向（上行/下行/横盘，归一化），
        两个周期必须同向且非横盘，才视为方向一致。
  说明：去掉了原 ADX>20 / ATR(1h)<2% / 4h 无插针 / 4h SRSI 区间 等附加门槛，
        只保留用户要求的两条硬条件（双周期 SRSI 极值 + 1h/4h 方向一致）。
扫描池复用 Top100(成交量) + 新币50，推送标题 TrendWatch。
去重：同一 CST 日期内同一币种只推送一次（状态存于 pushed_state.json）。
"""
import requests, time, os, json
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pushed_state.json")

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

def trend_dir(closes, look=20, eps=0.0002):
    """近 look 根收盘价的线性斜率方向（按价格归一化）。
    返回 1 上行 / -1 下行 / 0 横盘或样本不足。
    eps 为最小有效斜率门槛：低于该值视为横盘（中性），不计入方向。"""
    cl = closes[-look:] if len(closes) >= look else closes
    n = len(cl)
    if n < 3:
        return 0
    x = list(range(n))
    mx = sum(x) / n
    my = sum(cl) / n
    num = sum((x[i] - mx) * (cl[i] - my) for i in range(n))
    den = sum((x[i] - mx) ** 2 for i in range(n))
    if den == 0:
        return 0
    sl = num / den / my
    if sl > eps:
        return 1
    if sl < -eps:
        return -1
    return 0

def check_signal(s1, s1h, d1h, d4h):
    """双周期 SRSI 极值 + 1h/4h 价格方向一致。
    多：1d<20 且 1h<20 且 1h 上行 & 4h 上行
    空：1d>80 且 1h>80 且 1h 下行 & 4h 下行
    方向必须同向且非横盘；SRSI 极值方向与交易方向一致。
    """
    if d1h == 1 and d4h == 1 and s1 < 20 and s1h < 20:
        return "多"
    if d1h == -1 and d4h == -1 and s1 > 80 and s1h > 80:
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
        kv1 = calc_stoch_rsi_series(closes1)
        kv1h = calc_stoch_rsi_series(closes1h)
        if kv1 is None or kv1h is None:
            continue
        s1 = srsi_last(kv1)
        s1h = srsi_last(kv1h)
        if s1 is None or s1h is None:
            continue
        # 方向：1h 与 4h 价格方向（归一化线性斜率）
        d1h = trend_dir(closes1h)
        d4h = trend_dir(closes4)
        dirn = check_signal(s1, s1h, d1h, d4h)
        if dirn is None:
            continue
        cands.append({
            "name": name, "dir": dirn,
            "s1": round(s1, 1), "s1h": round(s1h, 1),
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
            print(f"  {r['name']}{r['dir']} SRSI(1d/1h)={r['s1']}/{r['s1h']} dir(1h/4h)={r['d1h']}/{r['d4h']} price={r['price']}")

    if token and new_cands:
        h = '<div style="font-family:-apple-system,sans-serif;max-width:560px">' 
        h += '<h3 style="margin:0 0 6px">SRSI 双周期极值 + 方向共振 (TrendWatch)</h3>'
        h += f'<div style="font-size:11px;color:#666;margin-bottom:6px">多:1d&lt;20 &amp; 1h&lt;20 &amp; 1h/4h同向上行 ｜ 空:1d&gt;80 &amp; 1h&gt;80 &amp; 1h/4h同向下行 ｜ 当日同币去重　共 {len(new_cands)} 个</div>'
        for r in new_cands:
            color = "#27ae60" if r["dir"] == "多" else "#e74c3c"
            p = fmt_p(r["price"], f"{r['name']}-USDT-SWAP")
            h += f'<div style="margin:5px 0;padding:6px;background:#fff;border-left:3px solid {color}">'
            h += f'<b>{r["name"]}</b> <span style="color:{color}">{r["dir"]}</span> {p}<br>'
            h += f'<span style="font-size:11px;color:#333">SRSI(1d/1h)={r["s1"]}/{r["s1h"]} | dir(1h/4h)={r["d1h"]}/{r["d4h"]}</span>'
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
