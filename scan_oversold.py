#!/usr/bin/env python3
"""
Beyond Selling Scan v1.0
- 4H StochRSI < 10 AND 1D StochRSI < 10 (double-cycle deep oversold)
- Wick/ratio < 3.5 (no spikes)
- ADX(4H) > 15 (clear trend, no falling knife)
- Output: Top 5 ranked, push to PushPlus
"""
import requests, time, json, os
from datetime import datetime, timezone, timedelta

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
                    candles.append({
                        "h": float(c[2]), "l": float(c[3]), "c": float(c[4]),
                        "o": float(c[1]), "v": float(c[5])
                    })
                candles.reverse()
                return candles
        except: time.sleep(0.5)
    return None

def calc_rsi(closes, period=14):
    n = len(closes)
    if n < period+1: return None
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    avg_g = sum(gains[:period])/period; avg_l = sum(losses[:period])/period
    rsi_v = []
    rsi_v.append(100 if avg_l==0 else 100-100/(1+avg_g/avg_l))
    for i in range(period, len(gains)):
        avg_g = (avg_g*(period-1)+gains[i])/period
        avg_l = (avg_l*(period-1)+losses[i])/period
        rsi_v.append(100 if avg_l==0 else 100-100/(1+avg_g/avg_l))
    return rsi_v

def calc_stoch_rsi(closes, rsi_period=14, stoch_period=14, smooth_k=3):
    rsi = calc_rsi(closes, rsi_period)
    if not rsi or len(rsi) < stoch_period+smooth_k: return None
    k_raw = []
    for i in range(stoch_period-1, len(rsi)):
        w = rsi[i-stoch_period+1:i+1]
        lo, hi = min(w), max(w)
        k_raw.append(50 if hi==lo else (rsi[i]-lo)/(hi-lo)*100)
    k_vals = []
    for i in range(smooth_k-1, len(k_raw)):
        k_vals.append(sum(k_raw[i-smooth_k+1:i+1])/smooth_k)
    if len(k_vals) < 4: return k_vals[-1] if k_vals else None
    d = sum(k_vals[-3:])/3
    return (k_vals[-1]+d)/2

def calc_adx(candles, period=14):
    n = len(candles)
    if n < period+1: return None, None, None
    h = [c["h"] for c in candles]; l = [c["l"] for c in candles]
    cl = [c["c"] for c in candles]
    tr = [0]*n
    for i in range(1,n): tr[i]=max(h[i]-l[i],abs(h[i]-cl[i-1]),abs(l[i]-cl[i-1]))
    pd=[0]*n; md=[0]*n
    for i in range(1,n):
        u=h[i]-h[i-1]; d=l[i-1]-l[i]
        if u>d and u>0: pd[i]=u
        if d>u and d>0: md[i]=d
    atrs=sum(tr[1:period+1])/period
    sp=sum(pd[1:period+1])/period; sm=sum(md[1:period+1])/period
    dxv=[]
    for i in range(period+1,n):
        atrs=(atrs*(period-1)+tr[i])/period
        sp=(sp*(period-1)+pd[i])/period; sm=(sm*(period-1)+md[i])/period
        p=sp/atrs*100 if atrs>0 else 0; m=sm/atrs*100 if atrs>0 else 0
        s=p+m
        dxv.append(abs(p-m)/s*100 if s>0 else 0)
    if len(dxv)<period: return None, None, None
    av=sum(dxv[:period])/period
    for i in range(period,len(dxv)): av=(av*(period-1)+dxv[i])/period
    pdi=sp/atrs*100 if atrs>0 else 0; mdi=sm/atrs*100 if atrs>0 else 0
    return av, pdi, mdi

def trend_ema_cross(candles, fast=12, slow=26):
    closes = [c["c"] for c in candles]
    k = 2/(fast+1)
    ef = sum(closes[:fast])/fast
    for p in closes[fast:]: ef = p*k + ef*(1-k)
    k2 = 2/(slow+1)
    es = sum(closes[:slow])/slow
    for p in closes[slow:]: es = p*k2 + es*(1-k2)
    return "Long" if ef > es else "Short"

def wick_analysis(candles):
    ratios = []; spikes = 0
    for c in candles[-20:]:
        body = max(abs(c["c"]-c["o"]), 1e-10)
        uw = c["h"]-max(c["c"],c["o"]); lw = min(c["c"],c["o"])-c["l"]
        r = min((uw+lw)/body, 10)
        ratios.append(r)
        if r > 4: spikes += 1
    return sum(ratios)/len(ratios), spikes

def fmt_price(p, inst):
    if "BTC" in inst or "ETH" in inst:
        return f"{p:.1f}"
    if p >= 1: return f"{p:.2f}"
    if p >= 0.01: return f"{p:.4f}"
    return f"{p:.6g}"

def main():
    r = requests.get(f"{OKX}/api/v5/market/tickers",
        params={"instType": "SWAP"}, timeout=15)
    data = r.json()
    if data.get("code") != "0":
        print("Failed:", data); return
    items = [(t["instId"], float(t.get("volCcy24h",0)))
             for t in data["data"] if "USDT" in t["instId"]
             and not any(x in t["instId"] for x in
                 ["BRL","EUR","TRY","DAI","USDC","RUB"])]
    items.sort(key=lambda x: -x[1])
    symbols = [i[0] for i in items[:60]]
    print(f"Scanning {len(symbols)} coins...")

    results = []
    for s in symbols:
        name = s.replace("-USDT-SWAP","")
        c4h = get_candles(s, "4H", 100)
        c1d = get_candles(s, "1D", 100)
        if not c4h or not c1d: continue
        closes_4h = [c["c"] for c in c4h]; closes_1d = [c["c"] for c in c1d]
        srsi4 = calc_stoch_rsi(closes_4h); srsi1 = calc_stoch_rsi(closes_1d)
        if srsi4 is None or srsi1 is None: continue
        if not (srsi4 < 10 and srsi1 < 10): continue
        adx4, pdi, mdi = calc_adx(c4h)
        w_avg, w_spikes = wick_analysis(c4h)
        trend = trend_ema_cross(c4h) if adx4 and adx4 > 0 else "N/A"
        price = closes_4h[-1]
        adx_s = min(1, (adx4 or 0)/30) * 0.35
        wick_s = max(0, 1 - w_avg/3) * 0.25
        spike_s = max(0, 1 - w_spikes*5/20) * 0.15
        extreme_s = max(0, (10-srsi4)/10)*0.15 + max(0, (10-srsi1)/10)*0.10
        score = round(adx_s + wick_s + spike_s + extreme_s, 3)
        trend_ok = "OK" if (trend=="Short" and adx4 and adx4>15) else ("WARN" if adx4 and adx4>10 else "NO")
        results.append({
            "name":name,"srsi4":round(srsi4,1),"srsi1":round(srsi1,1),
            "adx4":round(adx4,1) if adx4 else 0,"price":price,
            "trend":trend,"trend_ok":trend_ok,
            "wick":round(w_avg,1),"spikes":w_spikes,"score":score})
        time.sleep(0.05)

    results.sort(key=lambda x: -x["score"])

    clean = [r for r in results if r["wick"]<3 and r["spikes"]<=2
             and r["adx4"]>15 and r["trend"]=="Short" and r["score"]>0.4]

    token = os.environ.get("PUSHPLUS_TOKEN","")
    if not token:
        tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pushplus_token")
        if os.path.exists(tp):
            with open(tp) as f: token = f.read().strip()

    if clean:
        print(f"\nCLEAN: {len(clean)} signals")
        for r in clean:
            print(f"  {r['name']} SRSI={r['srsi4']}/{r['srsi1']} ADX={r['adx4']:.0f}")

    if token and clean:
        htm = '<div style="font-family:-apple-system,sans-serif;max-width:480px">'
        htm += '<h3 style="color:#e74c3c;margin:0 0 6px">SUPER OVERSOLD (SRSI 4H+1D <10)</h3>'
        for r in clean:
            p = fmt_price(r["price"], f"{r['name']}-USDT-SWAP")
            htm += f'<div style="margin:6px 0;padding:6px;background:#f0fdf4;border-left:3px solid #27ae60">'
            htm += f'<b>{r["name"]}</b> {p}<br>'
            htm += f'<span style="font-size:11px;color:#333">SRSI={r["srsi4"]}/{r["srsi1"]} | ADX={r["adx4"]:.0f} | NoSpikes</span>'
            htm += '</div>'
        htm += '</div>'
        payload = {"token":token,"title":"SuperOversold","content":htm,"template":"html"}
        try:
            resp = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
            rj = resp.json()
            print(f"\nPush: {'OK' if rj.get('code')==200 else rj}")
        except Exception as e:
            print(f"\nPush error: {e}")

    return results, clean

if __name__ == "__main__":
    main()
