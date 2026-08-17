#!/usr/bin/env python3
"""
Trend Candidate Scanner (SRSI + ADX 简化版)
只用一个思路判断"哪里可能有大趋势"：
  - ADX(1D) > 25  → 日线级别存在趋势
  - SRSI(1D) 位置 → 判断趋势方向(>50多 / <50空)与所处阶段
  - SRSI(4H) 拐头 → 给出更及时的进场/出场时点
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
    """返回 SRSI 序列(已做 %K 平滑)，便于取末值与判断拐头"""
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
    """返回 (末值, 是否拐头向上)"""
    if not kv or len(kv) < 2:
        return (kv[-1] if kv else None), None
    last = (kv[-1] + (sum(kv[-3:]) / 3 if len(kv) >= 3 else kv[-1])) / 2
    prev = (kv[-2] + (sum(kv[-4:-1]) / 3 if len(kv) >= 4 else kv[-2])) / 2
    return last, last > prev

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

def fmt_p(p, inst):
    if "BTC" in inst or "ETH" in inst:
        return f"{p:.1f}"
    if p >= 1:
        return f"{p:.2f}"
    if p >= 0.01:
        return f"{p:.4f}"
    return f"{p:.6g}"

def classify(s1, up1, s4, up4):
    """只用 SRSI(1D/4H) 判断阶段，ADX>25 已由调用方保证"""
    if up1:
        if s1 >= 80:
            return "超买(多)"
        if s1 >= 50:
            return "趋势运行(多)"
        # 1D SRSI 落到 20~50：上升趋势里的回撤
        return "第一波回调买点(多)" if up4 else "回调中(多)"
    else:
        if s1 <= 20:
            return "超卖(空)"
        if s1 <= 50:
            return "趋势运行(空)"
        # 1D SRSI 升到 50~80：下降趋势里的反弹
        return "反弹观察(空)" if not up4 else "反弹中(空)"

def main():
    EXCL = ["BRL", "EUR", "TRY", "DAI", "USDC", "RUB"]
    r = requests.get(f"{OKX}/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=15)
    d = r.json()
    if d.get("code") != "0":
        print("Failed:", d); return
    items = [(t["instIdOrInst"], float(t.get("volCcy24h", 0))) for t in d["data"]
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
        if not c1d or not c4h:
            continue
        closes1 = [c["c"] for c in c1d]
        closes4 = [c["c"] for c in c4h]
        adx1, _, _ = calc_adx(c1d)
        if adx1 is None or adx1 <= 25:      # 无日线级趋势 → 跳过
            continue
        kv1 = calc_stoch_rsi_series(closes1)
        kv4 = calc_stoch_rsi_series(closes4)
        if kv1 is None or kv4 is None:
            continue
        s1, up1 = srsi_last(kv1)
        s4, up4 = srsi_last(kv4)
        if s1 is None or s4 is None:
            continue
        phase = classify(s1, up1, s4, up4)
        cands.append({
            "name": name, "phase": phase,
            "dir": "多" if s1 >= 50 else "空",
            "adx": round(adx1, 1),
            "s1": round(s1, 1), "s4": round(s4, 1),
            "price": closes1[-1],
        })
        time.sleep(0.05)

    token = os.environ.get("PUSHPLUS_TOKEN", "")
    if not token:
        tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pushplus_token")
        if os.path.exists(tp):
            token = open(tp).read().strip()

    priority = {
        "第一波回调买点(多)": 0, "反弹观察(空)": 0,
        "趋势运行(多)": 1, "趋势运行(空)": 1,
        "回调中(多)": 2, "反弹中(空)": 2,
        "超买(多)": 3, "超卖(空)": 3,
    }
    cands.sort(key=lambda x: (priority.get(x["phase"], 4), -x["adx"]))

    if cands:
        print(f"\nCANDIDATES({len(cands)}):")
        for r in cands:
            print(f"  {r['name']}{r['dir']}{r['phase']}ADX={r['adx']:.0f}SRSI={r['s1']}/{r['s4']}")

    if token and cands:
        h = '<div style="font-family:-apple-system,sans-serif;max-width:540px">'
        h += '<h3 style="margin:0 0 6px">大趋势候选 (TrendWatch · SRSI+ADX)</h3>'
        h += f'<div style="font-size:11px;color:#666;margin-bottom:6px">ADX(1D)&gt;25 的趋势币，按 SRSI 阶段分类　共 {len(cands)} 个</div>'
        for r in cands:
            color = "#27ae60" if r["dir"] == "多" else "#e74c3c"
            if r["phase"].startswith("第一波") or r["phase"].startswith("反弹观察"):
                pcol = "#d35400"   # 可操作买/卖点 高亮
            elif r["phase"].startswith("趋势运行"):
                pcol = "#2980b9"
            elif "超买" in r["phase"] or "超卖" in r["phase"]:
                pcol = "#8e44ad"
            else:
                pcol = "#7f8c8d"
            p = fmt_p(r["price"], f"{r['name']}-USDT-SWAP")
            h += f'<div style="margin:5px 0;padding:6px;background:#fff;border-left:3px solid {pcol}">'
            h += f'<b>{r["name"]}</b> <span style="color:{color}">{r["dir"]}</span> '
            h += f'<span style="color:{pcol}">{r["phase"]}</span> {p}<br>'
            h += f'<span style="font-size:11px;color:#333">ADX={r["adx"]:.0f} | SRSI(1D/4H)={r["s1"]}/{r["s4"]}</span>'
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
