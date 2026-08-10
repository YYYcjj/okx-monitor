#!/usr/bin/env python3
"""
Find Best Coins — 找出最适合当前系统的币种
系统标准：4H+1D SRSI 极端 + 无插针 + ADX>15 + 趋势匹配
回测范围：成交量Top200，回溯~25天(150根4H)
"""
import requests, time, os

OKX = "https://www.okx.com"

def get_candles(inst, bar, limit=150):
    for _ in range(3):
        try:
            r = requests.get(f"{OKX}/api/v5/market/candles",
                params={"instId": inst, "bar": bar, "limit": limit}, timeout=12)
            d = r.json()
            if d.get("code") == "0":
                candles = []
                for c in d["data"]:
                    candles.append({"h": float(c[2]), "l": float(c[3]), "c": float(c[4]), "o": float(c[1])})
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
    ag = sum(gains[:period])/period; al = sum(losses[:period])/period
    rv = [100 if al==0 else 100-100/(1+ag/al)]
    for i in range(period, len(gains)):
        ag = (ag*(period-1)+gains[i])/period; al = (al*(period-1)+losses[i])/period
        rv.append(100 if al==0 else 100-100/(1+ag/al))
    return rv

def calc_stoch_rsi(closes):
    rsi = calc_rsi(closes)
    if not rsi or len(rsi) < 17: return None
    kr = []
    for i in range(13, len(rsi)):
        w = rsi[i-13:i+1]; lo, hi = min(w), max(w)
        kr.append(50 if hi==lo else (rsi[i]-lo)/(hi-lo)*100)
    kv = []
    for i in range(2, len(kr)): kv.append(sum(kr[i-2:i+1])/3)
    if len(kv) < 4: return kv[-1] if kv else None
    d = sum(kv[-3:])/3
    return (kv[-1]+d)/2

def calc_adx(candles):
    n = len(candles)
    if n < 15: return None
    h = [c["h"] for c in candles]; l = [c["l"] for c in candles]
    cl = [c["c"] for c in candles]
    tr = [0]*n
    for i in range(1,n): tr[i]=max(h[i]-l[i],abs(h[i]-cl[i-1]),abs(l[i]-cl[i-1]))
    pd=[0]*n; md=[0]*n
    for i in range(1,n):
        u=h[i]-h[i-1]; d=l[i-1]-l[i]
        if u>d and u>0: pd[i]=u
        if d>u and d>0: md[i]=d
    atrs=sum(tr[1:15])/14; sp=sum(pd[1:15])/14; sm=sum(md[1:15])/14
    dxv=[]
    for i in range(15,n):
        atrs=(atrs*13+tr[i])/14; sp=(sp*13+pd[i])/14; sm=(sm*13+md[i])/14
        p=sp/atrs*100 if atrs>0 else 0; m=sm/atrs*100 if atrs>0 else 0; s=p+m
        dxv.append(abs(p-m)/s*100 if s>0 else 0)
    if len(dxv)<14: return None
    av=sum(dxv[:14])/14
    for i in range(14,len(dxv)): av=(av*13+dxv[i])/14
    return av

def trend_ema(candles, fast=12, slow=26):
    cl = [c["c"] for c in candles]
    k = 2/(fast+1); ef = sum(cl[:fast])/fast
    for p in cl[fast:]: ef = p*k + ef*(1-k)
    k2 = 2/(slow+1); es = sum(cl[:slow])/slow
    for p in cl[slow:]: es = p*k2 + es*(1-k2)
    return "Long" if ef > es else "Short"

def wick_ok(candles):
    spikes = 0
    for c in candles[-20:]:
        body = max(abs(c["c"]-c["o"]), 1e-10)
        uw = c["h"]-max(c["c"],c["o"]); lw = min(c["c"],c["o"])-c["l"]
        if (uw+lw)/body > 4: spikes += 1
    return spikes <= 2

def main():
    r = requests.get(f"{OKX}/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=15)
    d = r.json()
    if d.get("code") != "0":
        print("Failed:", d); return
    items = [(t["instId"], float(t.get("volCcy24h",0))) for t in d["data"]
             if "USDT" in t["instId"] and not any(x in t["instId"] for x in ["BRL","EUR","TRY","DAI","USDC","RUB"])]
    items.sort(key=lambda x: -x[1])
    syms = [i[0] for i in items[:200]]

    print(f"Scanning {len(syms)} coins for SRSI extreme signal history...\n")
    print(f"{'Coin':<10} {'Signal':>6} {'Qualified':>9} {'Rate':>6} {'AvgADX':>7} {'Score':>6}")
    print("-" * 52)

    results = []
    for s in syms:
        name = s.replace("-USDT-SWAP","")
        c4h = get_candles(s, "4H", 150)
        c1d = get_candles(s, "1D", 150)
        if not c4h or not c1d: continue

        total_signals = 0; qualified = 0; adx_vals = []

        for start in range(0, len(c4h)-80, 6):
            seg4 = c4h[start:start+100]
            day_idx = start // 6
            if day_idx + 70 > len(c1d): break
            seg1 = c1d[day_idx:day_idx+100]

            s4 = calc_stoch_rsi([c["c"] for c in seg4])
            s1 = calc_stoch_rsi([c["c"] for c in seg1])
            if s4 is None or s1 is None: continue

            ovs = s4 < 10 and s1 < 10
            ovb = s4 > 90 and s1 > 90
            if not ovs and not ovb: continue
            total_signals += 1

            adx4 = calc_adx(seg4)
            if adx4: adx_vals.append(adx4)
            tr = trend_ema(seg4) if adx4 else "N/A"
            trq = "Short" if ovs else "Long"

            if adx4 and adx4 > 15 and tr == trq and wick_ok(seg4):
                qualified += 1

        if total_signals == 0: continue

        avg_adx = sum(adx_vals)/len(adx_vals) if adx_vals else 0
        rate = qualified / total_signals
        score = round(rate * min(avg_adx/30, 1), 3)

        results.append({"name":name, "signals":total_signals, "qual":qualified,
                       "rate":rate, "adx":round(avg_adx,1), "score":score})
        time.sleep(0.03)

    results.sort(key=lambda x: (-x["qual"], -x["score"]))

    for r in results[:30]:
        print(f"{r['name']:<10} {r['signals']:>6} {r['qual']:>9} {r['rate']*100:>5.0f}% {r['adx']:7.1f} {r['score']:>6.3f}")

    best = [r for r in results if r["qual"] >= 3 and r["score"] > 0.2]
    if not best: best = results[:10]
    else: best.sort(key=lambda x: (-x["qual"], -x["score"])); best = best[:10]

    print(f"\n=== TOP 10 BEST-FIT COINS ===")
    for r in best:
        print(f"  {r['name']:<10} 信号{r['signals']}次 合格{r['qual']}次 成功率{r['rate']*100:.0f}%")

    print(f"\n=== YOUR 7 FIXED COINS ===")
    MY = {"ORDI","PUMP","HUMA","WLD","APR","BTC","APT"}
    for r in results:
        if r["name"] in MY:
            print(f"  {r['name']:<10} 信号{r['signals']}次 合格{r['qual']}次 成功率{r['rate']*100:.0f}% ADX={r['adx']:.0f}")

    token = os.environ.get("PUSHPLUS_TOKEN","")
    if token and best:
        h = '<div style="font-family:-apple-system,sans-serif;max-width:480px">'
        h += '<h3>System-Fit Coins</h3>'
        h += '<p style="font-size:11px;color:#666">SRSI extreme(4H+1D) + NoSpike + ADX>15 + Trend</p>'
        h += '<table style="width:100%;border-collapse:collapse;font-size:12px">'
        h += '<tr style="background:#f5f6fa"><td>Coin</td><td>Signals</td><td>Good</td><td>Rate</td><td>ADX</td></tr>'
        for r in best:
            h += f'<tr><td style="font-weight:bold">{r["name"]}</td><td>{r["signals"]}</td><td>{r["qual"]}</td><td>{r["rate"]*100:.0f}%</td><td>{r["adx"]:.0f}</td></tr>'
        h += '</table></div>'
        pl = {"token":token, "title":"SystemFit", "content":h, "template":"html"}
        try:
            rp = requests.post("http://www.pushplus.plus/send", json=pl, timeout=10)
            print(f"\nPush: {'OK' if rp.json().get('code')==200 else rp.json()}")
        except Exception as e: print(f"Push error: {e}")

if __name__ == "__main__":
    main()
