#!/usr/bin/env python3
"""
SRSI 三周期共振信号 (TrendWatch)
规则（用户定义）：
  多头：1d SRSI < 20  且 4h SRSI ∈ [10,40]  且 1h SRSI < 20
  空头：1d SRSI > 80  且 4h SRSI ∈ [60,90]  且 1h SRSI > 80
  三个周期必须同一方向，全部符合才推送。
  额外门槛：1h ADX > 20（1h 级别需存在趋势，过滤横盘噪音）。
  质量过滤（沿用 ExtremeSRSI）：ATR(1h) < 2% 且 4h 无插针。
  ADX(1D) 作为趋势强度参考显示。
扫描池复用 Top200(成交量) + 新币50，推送标题 TrendWatch。
"""
import requests, time, os

OKX = "https://www.okx.com"

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

def calc_adx(candles, period=14):
    n = len(candles)
    if n < period + 1:
        return None, None, None
    h = [c["h"] for c in candles]; l = [c["l"] for c in candles]; cl = [c["c"] for c in candles]
    tr = [0] * n
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - cl[i - 1]), abs(l[i] - cl[i - 1]))
    pd = [0] * n; md = [0] * n
    for i in range(1, n):
        u = h[i] - h[i - 1]; d = l[i - 1] - l[i]
        if u > d and u > 0: pd[i] = u
        if d > u and d > 0: md[i] = d
    atrs = sum(tr[1:period + 1]) / period
    sp = sum(pd[1:period + 1]) / period
    sm = sum(md[1:period + 1]) / period
    dxv = []
    for i in range(period + 1, n):
        atrs = (atrs * (period - 1) + tr[i]) / period
        sp = (sp * (period - 1) + pd[i]) / period
        sm = (sm * (period - 1) + md[i]) / period
        p = sp / atrs * 100 if atrs > 0 else 0
        m = sm / atrs * 100 if atrs > 0 else 0
        s = p + m
        dxv.append(abs(p - m) / s * 100 if s > 0 else 0)
    if len(dxv) < period:
        return None, None, None
    av = sum(dxv[:period]) / period
    for i in range(period, len(dxv)):
        av = (av * (period - 1) + dxv[i]) / period
    return av, sp / atrs * 100 if atrs > 0 else 0, sm / atrs * 100 if atrs > 0 else 0

def calc_atr(candles, period=14):
    """真实波动幅度均值（沿用 ExtremeSRSI 口径）"""
    n = len(candles)
    if n < period + 1:
        return None
    h = [c["h"] for c in candles]; l = [c["l"] for c in candles]; cl = [c["c"] for c in candles]
    tr = [0] * n
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - cl[i - 1]), abs(l[i] - cl[i - 1]))
    atr = sum(tr[1:period + 1]) / period
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + tr[i]) / period
    return atr

def wick_ok(candles):
    """True = 干净 / 无插针（沿用 ExtremeSRSI 口径，检查近 20 根）"""
    wa = []; sp = 0
    for c in candles[-20:]:
        body = max(abs(c["c"] - c["o"]), 1e-10)
        uw = c["h"] - max(c["c"], c["o"]); lw = min(c["c"], c["o"]) - c["l"]
        r = min((uw + lw) / body, 10); wa.append(r)
        if r > 4: sp += 1
    return sum(wa) / len(wa) < 3 and sp <= 2

def fmt_p(p, inst):
    if "BTC" in inst or "ETH" in inst:
        return f"{p:.1f}"
    if p >= 1:
        return f"{p:.2f}"
    if p >= 0.01:
        return f"{p:.4f}"
    return f"{p:.6g}"

def check_resonance(s1, s4, s1h, adx1h):
    """三周期 SRSI 共振 + 1h ADX>20：同一方向全部符合才返回方向，否则 None"""
    if adx1h <= 20:          # 1h 级别无趋势（横盘）→ 过滤
        return None
    # 多头：1d<20 且 4h∈[10,40] 且 1h<20
    if s1 < 20 and (10 <= s4 <= 40) and s1h < 20:
        return "多"
    # 空头：1d>80 且 4h∈[60,90] 且 1h>80
    if s1 > 80 and (60 <= s4 <= 90) and s1h > 80:
        return "空"
    return None

def main():
    EXCL = ["BRL", "EUR", "TRY", "DAI", "USDC", "RUB"]
    r = requests.get(f"{OKX}/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=15)
    d = r.json()
    if d.get("code") != "0":
        print("Failed:", d); return
    items = [(t["instId"], float(t.get("volCcy24h", 0))) for t in d["data"]
             if "USDT" in t["instId"] and not any(x in t["instId"] for x in EXCL)]
    items.sort(key=lambda x: -x[1])
    vol_top = [i[0] for i in items[:200]]

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
        kv4 = calc_stoch_rsi_series(closes4)
        kv1h = calc_stoch_rsi_series(closes1h)
        if kv1 is None or kv4 is None or kv1h is None:
            continue
        s1 = srsi_last(kv1)
        s4 = srsi_last(kv4)
        s1h = srsi_last(kv1h)
        if s1 is None or s4 is None or s1h is None:
            continue
        adx1h, _, _ = calc_adx(c1h)
        adx1h = adx1h if adx1h else 0
        dirn = check_resonance(s1, s4, s1h, adx1h)
        if dirn is None:
            continue
        # 质量过滤（沿用 ExtremeSRSI）：ATR(1h) < 2% 且 4h 无插针
        price = closes4[-1]
        atr1h = calc_atr(c1h)
        if atr1h is None or atr1h / price >= 0.02:
            continue
        if not wick_ok(c4h):
            continue
        adx1, _, _ = calc_adx(c1d)
        cands.append({
            "name": name, "dir": dirn,
            "s1": round(s1, 1), "s4": round(s4, 1), "s1h": round(s1h, 1),
            "adx": round(adx1, 1) if adx1 else 0,
            "adx1h": round(adx1h, 1),
            "atr1h": round(atr1h / price * 100, 2),
            "price": closes1[-1],
        })
        time.sleep(0.05)

    token = os.environ.get("PUSHPLUS_TOKEN", "")
    if not token:
        tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pushplus_token")
        if os.path.exists(tp):
            token = open(tp).read().strip()

    # 多头在前、空头在后，组内按 ADX 降序（趋势越强越靠前）
    cands.sort(key=lambda x: (0 if x["dir"] == "多" else 1, -x["adx"]))

    if cands:
        print(f"\nSIGNALS({len(cands)}):")
        for r in cands:
            print(f"  {r['name']}{r['dir']} SRSI(1d/4h/1h)={r['s1']}/{r['s4']}/{r['s1h']} ADX(1d/1h)={r['adx']:.0f}/{r['adx1h']:.0f} ATR={r['atr1h']}%")

    if token and cands:
        h = '<div style="font-family:-apple-system,sans-serif;max-width:560px">'
        h += '<h3 style="margin:0 0 6px">SRSI 三周期共振 (TrendWatch)</h3>'
        h += f'<div style="font-size:11px;color:#666;margin-bottom:6px">多:1d&lt;20 &amp; 4h∈[10,40] &amp; 1h&lt;20 ｜ 空:1d&gt;80 &amp; 4h∈[60,90] &amp; 1h&gt;80 ｜ 且 1h ADX&gt;20 ｜ ATR(1h)&lt;2% &amp; 4h无插针　共 {len(cands)} 个</div>'
        for r in cands:
            color = "#27ae60" if r["dir"] == "多" else "#e74c3c"
            p = fmt_p(r["price"], f"{r['name']}-USDT-SWAP")
            h += f'<div style="margin:5px 0;padding:6px;background:#fff;border-left:3px solid {color}">'
            h += f'<b>{r["name"]}</b> <span style="color:{color}">{r["dir"]}</span> {p}<br>'
            h += f'<span style="font-size:11px;color:#333">SRSI(1d/4h/1h)={r["s1"]}/{r["s4"]}/{r["s1h"]} | ADX(1d/1h)={r["adx"]:.0f}/{r["adx1h"]:.0f} | ATR={r["atr1h"]}%</span>'
            h += '</div>'
        h += '</div>'
        pl = {"token": token, "title": "TrendWatch", "content": h, "template": "html"}
        try:
            rp = requests.post("http://www.pushplus.plus/send", json=pl, timeout=10)
            print("Push:", rp.json().get("code"))
        except Exception as e:
            print("Push error:", e)
    return cands

if __name__ == "__main__":
    main()
