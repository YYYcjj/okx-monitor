#!/usr/bin/env python3
"""成交分析: 拉取3个月成交 + 历史K线指标 + P&L"""
import csv, os, time, hmac, base64, hashlib, requests, statistics
from datetime import datetime, timezone, timedelta
import warnings; warnings.filterwarnings("ignore")

API_KEY = "6d758f5a-4ea7-44d1-bc56-5b8659263b1a"
API_SECRET = "760BEBD659B861D17B5DE6DF7112E5CF"
API_PASSPHRASE = "1qaz2wsxcJJ!"
OKX = "https://www.okx.com"
DIR = {'1h': 1, '4h': 2, '1d': 3}
MILD = 2
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def okx_sign(ts, method, path, body=""):
    return base64.b64encode(hmac.new(API_SECRET.encode(), (ts+method+path+body).encode(), hashlib.sha256).digest()).decode()

def okx_req(method, path, params=None):
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
    qs = "?" + "&".join(f"{k}={v}" for k,v in (params or {}).items()) if params else ""
    h = {"OK-ACCESS-KEY": API_KEY, "OK-ACCESS-SIGN": okx_sign(ts, method, path+qs),
         "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": API_PASSPHRASE}
    for _ in range(3):
        try:
            r = requests.get(f"{OKX}{path}{qs}", headers=h, timeout=15)
            return r.json()
        except:
            time.sleep(1)
    return {}

def calc_rsi(closes, period=14):
    if len(closes) < period+1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    rsi = [100 if al == 0 else 100 - 100/(1 + ag/al)]
    for i in range(period, len(gains)):
        ag = (ag*(period-1) + gains[i]) / period
        al = (al*(period-1) + losses[i]) / period
        rsi.append(100 if al == 0 else 100 - 100/(1 + ag/al))
    return rsi

def calc_stoch_rsi(closes):
    rsi_v = calc_rsi(closes)
    if not rsi_v or len(rsi_v) < 17:
        return None
    k_raw = []
    for i in range(13, len(rsi_v)):
        w = rsi_v[i-13:i+1]
        lo, hi = min(w), max(w)
        k_raw.append(50 if hi == lo else (rsi_v[i]-lo)/(hi-lo)*100)
    k_vals = [(k_raw[i]+k_raw[i+1]+k_raw[i+2])/3 for i in range(len(k_raw)-2)]
    if len(k_vals) < 4:
        return k_vals[-1]
    d = sum(k_vals[-3:]) / 3
    return (k_vals[-1] + d) / 2

def calc_ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period+1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p*k + ema*(1-k)
    return ema

def trend_dmi(candles, period=14):
    n = len(candles)
    if n < period+1:
        return "N/A"
    h = [c["h"] for c in candles]
    l = [c["l"] for c in candles]
    cl = [c["c"] for c in candles]
    tr = [0.0]*n
    pdm = [0.0]*n
    mdm = [0.0]*n
    for i in range(1, n):
        tr[i] = max(h[i]-l[i], abs(h[i]-cl[i-1]), abs(l[i]-cl[i-1]))
        up = h[i] - h[i-1]
        down = l[i-1] - l[i]
        if up > down and up > 0:
            pdm[i] = up
        if down > up and down > 0:
            mdm[i] = down
    atr_s = sum(tr[1:period+1]) / period
    sp = sum(pdm[1:period+1]) / period
    sm = sum(mdm[1:period+1]) / period
    for i in range(period+1, n):
        atr_s = (atr_s*(period-1) + tr[i]) / period
        sp = (sp*(period-1) + pdm[i]) / period
        sm = (sm*(period-1) + mdm[i]) / period
    pdi = sp/atr_s*100 if atr_s > 0 else 0
    mdi = sm/atr_s*100 if atr_s > 0 else 0
    return "多" if pdi > mdi else "空"

def trend_swing(candles):
    if len(candles) < 30:
        return "N/A"
    h = [c["h"] for c in candles]
    l = [c["l"] for c in candles]
    cl = [c["c"] for c in candles]
    tr_raw = []
    for i in range(1, len(candles)):
        tr_raw.append(max(h[i]-l[i], abs(h[i]-cl[i-1]), abs(l[i]-cl[i-1])))
    atr_vals = [sum(tr_raw[:14])/14]
    for i in range(1, len(tr_raw)):
        atr_vals.append((atr_vals[-1]*13 + tr_raw[i]) / 14)
    atr = atr_vals[-1] if atr_vals else 0
    sh, sl = [], []
    for i in range(2, len(candles)-2):
        if h[i] >= h[i-1] and h[i] >= h[i-2] and h[i] >= h[i+1] and h[i] >= h[i+2]:
            sh.append(h[i])
        if l[i] <= l[i-1] and l[i] <= l[i-2] and l[i] <= l[i+1] and l[i] <= l[i+2]:
            sl.append(l[i])
    if len(sh) < 2 or len(sl) < 2:
        return "N/A"
    up = sh[-1] > sh[-2]
    lo = sl[-1] >= sl[-2] - atr
    if up and lo:
        return "多"
    if not up and not lo:
        return "空"
    return "多" if lo else "空"

def trend_ema_cross(candles):
    cl = [c["c"] for c in candles]
    ef = calc_ema(cl, 12)
    es = calc_ema(cl, 26)
    if ef is None or es is None:
        return "N/A"
    return "空" if ef < es else "多"

def calc_score(trends, srsis):
    b, e = 0, 0
    for tf in ['1h', '4h', '1d']:
        d = trends.get(tf, 'N/A')
        s = srsis.get(tf)
        w = DIR[tf]
        if d == '多':
            b += w
        elif d == '空':
            e += w
        if s is not None:
            if s < 20:
                b += w
            elif s < 30 and tf == '1d':
                b += MILD
            if s > 80:
                e += w
            elif s > 70 and tf == '1d':
                e += MILD
    return b, e

def main():
    SYMS = ["BTC-USDT-SWAP","APT-USDT-SWAP","HOME-USDT-SWAP","WLD-USDT-SWAP",
            "HUMA-USDT-SWAP","HMSTR-USDT-SWAP","PUMP-USDT-SWAP","ORDI-USDT-SWAP"]
    end_ts = int(datetime.now().timestamp() * 1000)
    begin_ts = int((datetime.now() - timedelta(days=90)).timestamp() * 1000)

    trades = []
    for sym in SYMS:
        d = okx_req("GET", "/api/v5/trade/orders-history",
            {"instType":"SWAP","instId":sym,"ordType":"market","state":"filled",
             "begin":str(begin_ts),"end":str(end_ts),"limit":"100"})
        if d.get("code") == "0" and d.get("data"):
            for o in d["data"]:
                trades.append({"sym": sym.replace("-USDT-SWAP",""), "time": int(o["cTime"]),
                    "side": o["side"], "px": float(o["avgPx"]), "sz": float(o["accFillSz"])})
        time.sleep(0.3)
    trades.sort(key=lambda x: x["time"])
    print(f"成交: {len(trades)} 笔")

    by_sym = {}
    for t in trades:
        by_sym.setdefault(t["sym"], []).append(t)

    print("拉历史K线...")
    sym_c = {}
    for sym, sigs in by_sym.items():
        fsym = f"{sym}-USDT-SWAP"
        latest = max(s["time"] for s in sigs) + 48*3600*1000
        all_c = []
        before = str(latest)
        for pg in range(50):
            try:
                # 使用带认证的请求获取更多历史数据
                params = {"instId":fsym,"bar":"1H","limit":300,"before":before}
                ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
                qs = "?" + "&".join(f"{k}={v}" for k,v in params.items())
                sign = base64.b64encode(hmac.new(API_SECRET.encode(), (ts+"GET"+"/api/v5/market/candles"+qs).encode(), hashlib.sha256).digest()).decode()
                hdr = {"OK-ACCESS-KEY":API_KEY,"OK-ACCESS-SIGN":sign,"OK-ACCESS-TIMESTAMP":ts,"OK-ACCESS-PASSPHRASE":API_PASSPHRASE}
                r = requests.get(f"{OKX}/api/v5/market/candles{qs}", headers=hdr, timeout=15)
                d = r.json()
                if d.get("code") != "0" or not d.get("data"):
                    break
                batch = d["data"]
                all_c.extend(batch)
                if len(batch) < 300:
                    break
                before = batch[-1][0]
            except:
                break
            time.sleep(0.15)
        parsed = [{"ts":int(c[0]),"h":float(c[2]),"l":float(c[3]),"o":float(c[1]),"c":float(c[4])} for c in all_c]
        parsed.sort(key=lambda x: x["ts"])
        sym_c[sym] = parsed
        print(f"  {sym}: {len(parsed)}根1H K线")

    print("\n计算指标...")
    results = []
    for idx, t in enumerate(trades):
        ts_str = datetime.fromtimestamp(t["time"]/1000, tz=timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
        cds = sym_c.get(t["sym"], [])

        if len(cds) < 100:
            results.append({"time":ts_str,"sym":t["sym"],"side":t["side"],"px":t["px"],"sz":t["sz"],"err":True})
            continue

        ei = next((i for i,c in enumerate(cds) if c["ts"] >= t["time"]), None)
        if ei is None or ei < 60:
            results.append({"time":ts_str,"sym":t["sym"],"side":t["side"],"px":t["px"],"sz":t["sz"],"err":True})
            continue

        pre = cds[max(0, ei-250):ei+1]
        cl = [c["c"] for c in pre]

        d1h = trend_dmi(pre[-100:]) if len(pre) >= 100 else "N/A"
        s1h_v = calc_stoch_rsi(cl[-50:])
        srsi_1h = round(s1h_v, 1) if s1h_v is not None else None

        p4 = []
        for i in range(0, len(pre)-3, 4):
            g = pre[i:i+4]
            p4.append({"h":max(c["h"] for c in g),"l":min(c["l"] for c in g),"o":g[0]["o"],"c":g[-1]["c"]})
        d4h = trend_dmi(p4[-50:]) if len(p4) >= 50 else "N/A"
        cl4 = [c["c"] for c in p4]
        s4h_v = calc_stoch_rsi(cl4[-30:]) if len(p4) >= 30 else None
        srsi_4h = round(s4h_v, 1) if s4h_v is not None else None

        pd_d = []
        for i in range(0, len(pre)-23, 24):
            g = pre[i:i+24]
            pd_d.append({"h":max(c["h"] for c in g),"l":min(c["l"] for c in g),"o":g[0]["o"],"c":g[-1]["c"]})
        sw_c = pd_d[-60:]
        sw1d = trend_swing(sw_c) if len(sw_c) >= 30 else "N/A"
        ema1d = trend_ema_cross(pd_d[-60:]) if len(pd_d) >= 60 else "N/A"
        cld = [c["c"] for c in pd_d[-10:]]
        bearish = sum(1 for i in range(1, min(10, len(cld))) if cld[i] < cld[i-1])
        if sw1d == "多" and ema1d == "空" and bearish >= 7:
            d1d = "空"
        else:
            d1d = sw1d
        s1d_v = calc_stoch_rsi([c["c"] for c in pd_d[-30:]]) if len(pd_d) >= 30 else None
        srsi_1d = round(s1d_v, 1) if s1d_v is not None else None

        trends = {"1h":d1h,"4h":d4h,"1d":d1d}
        srsis = {"1h":srsi_1h,"4h":srsi_4h,"1d":srsi_1d}
        bull, bear = calc_score(trends, srsis)
        net = abs(bull-bear)
        net_str = f"多+{net}" if bull > bear else (f"空+{net}" if bear > bull else "0")

        ep = t["px"]
        dm = 1 if t["side"] == "buy" else -1
        pnls = {}
        for lbl, hh in [("4H",4),("12H",12),("24H",24)]:
            hi = min(ei+hh, len(cds)-1)
            pnls[lbl] = f"{(cds[hi]['c']-ep)/ep*100*dm:+.2f}%" if hi > ei else "--"

        s1h_s = f"{srsi_1h:.1f}" if srsi_1h is not None else "N/A"
        s4h_s = f"{srsi_4h:.1f}" if srsi_4h is not None else "N/A"
        s1d_s = f"{srsi_1d:.1f}" if srsi_1d is not None else "N/A"

        results.append({"time":ts_str,"sym":t["sym"],"side":t["side"],"px":t["px"],"sz":t["sz"],
            "d1h":d1h,"d4h":d4h,"d1d":d1d,"s1h":s1h_s,"s4h":s4h_s,"s1d":s1d_s,
            "bull":bull,"bear":bear,"net":net_str,"err":False,
            "p4h":pnls["4H"],"p12h":pnls["12H"],"p24h":pnls["24H"]})

        if (idx+1) % 10 == 0:
            print(f"  进度: {idx+1}/{len(trades)}")

    ok = sum(1 for r in results if not r.get("err"))
    print(f"\n成功: {ok}/{len(trades)}\n")

    print(f"{'时间':<17} {'币种':<6} {'S/B':<4} {'价':>9} | {'1H':>4} {'4H':>4} {'1D':>4} | {'S1H':>6} {'S4H':>6} {'S1D':>6} | {'多':>3} {'空':>3} {'净值':>6} | {'4H':>7} {'12H':>7} {'24H':>7}")
    print("-"*125)
    for r in results[:60]:
        if r.get("err"):
            print(f'{r["time"]:<17} {r["sym"]:<6} {r["side"]:<4} {r["px"]:>9.4f} | {"--- 数据不足 ---":>60} |')
        else:
            s = "卖" if r["side"] == "sell" else "买"
            print(f'{r["time"]:<17} {r["sym"]:<6} {s:<4} {r["px"]:>9.4f} | {r["d1h"]:>4} {r["d4h"]:>4} {r["d1d"]:>4} | {r["s1h"]:>6} {r["s4h"]:>6} {r["s1d"]:>6} | {r["bull"]:>3} {r["bear"]:>3} {r["net"]:>6} | {r["p4h"]:>7} {r["p12h"]:>7} {r["p24h"]:>7}')

    out = os.path.join(PROJECT_ROOT, "okx_data", "trade_analysis_full.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time","sym","side","px","sz","d1h","d4h","d1d","s1h","s4h","s1d","bull","bear","net","p4h","p12h","p24h"])
        w.writeheader()
        w.writerows([{k: r.get(k,"") for k in w.fieldnames} for r in results])
    print(f"\n✅ {out} ({len(results)}条)")

if __name__ == "__main__":
    main()
