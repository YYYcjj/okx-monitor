#!/usr/bin/env python3
"""
Trend Candidate Scanner — 监控“可能有大趋势的地方”
基于 1D 级别：
  强趋势   : ADX(1D) > 25
  排列     : 多头 close>EMA50>EMA200 / 空头 close<EMA50<EMA200
  清晰波   : 近200根涨跌波 > 30%
并标注当前阶段：趋势运行中 / 第一波回调(观察买点) / 回调过深
复用 scan_oversold 的指标函数与扫描池(Top200 + 新币50)
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

def calc_ema(closes, period):
    n = len(closes)
    if n < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def fmt_p(p, inst):
    if "BTC" in inst or "ETH" in inst:
        return f"{p:.1f}"
    if p >= 1:
        return f"{p:.2f}"
    if p >= 0.01:
        return f"{p:.4f}"
    return f"{p:.6g}"

def trend_state(close, ema50, ema200, low200, high200, high50, low50, adx, bull):
    """返回 (is_candidate, phase, wave_pct)"""
    if bull:
        wave = (close - low200) / low200 * 100 if low200 > 0 else 0
        pullback = (high50 - close) / high50 * 100 if high50 > 0 else 0
    else:
        wave = (high200 - close) / high200 * 100 if high200 > 0 else 0
        pullback = (close - low50) / low50 * 100 if low50 > 0 else 0
    if adx is None or adx <= 25:
        return False, None, round(wave, 1)
    if wave < 30:
        return False, None, round(wave, 1)
    if ema200 is not None:
        if bull and not (close > ema50 and ema50 > ema200):
            return False, None, round(wave, 1)
        if (not bull) and not (close < ema50 and ema50 < ema200):
            return False, None, round(wave, 1)
    else:
        if bull and not close > ema50:
            return False, None, round(wave, 1)
        if (not bull) and not close < ema50:
            return False, None, round(wave, 1)
    if pullback < 8:
        phase = "趋势运行中"
    elif pullback <= 30 and ((bull and close > ema50) or (not bull and close < ema50)):
        phase = "第一波回调(观察买点)"
    else:
        phase = "回调过深/转弱"
    return True, phase, round(wave, 1)

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
        c1d = get_candles(s, "1D", 300)
        if not c1d or len(c1d) < 200:
            continue
        closes = [c["c"] for c in c1d]
        adx, _, _ = calc_adx(c1d)
        ema50 = calc_ema(closes, 50)
        ema200 = calc_ema(closes, 200)
        low200 = min(c["l"] for c in c1d[-200:])
        high200 = max(c["h"] for c in c1d[-200:])
        high50 = max(c["h"] for c in c1d[-50:])
        low50 = min(c["l"] for c in c1d[-50:])
        close = closes[-1]
        for bull in (True, False):
            ok, phase, wave = trend_state(close, ema50, ema200, low200, high200,
                                          high50, low50, adx, bull)
            if ok:
                pullback = (high50 - close) / high50 * 100 if bull else (close - low50) / low50 * 100
                cands.append({
                    "name": name, "dir": "多" if bull else "空",
                    "adx": round(adx, 1) if adx else 0,
                    "wave": wave, "pullback": round(pullback, 1),
                    "phase": phase, "price": close,
                    "ema50": round(ema50, 4) if ema50 else 0,
                    "ema200": round(ema200, 4) if ema200 else 0,
                })
                break
        time.sleep(0.05)

    token = os.environ.get("PUSHPLUS_TOKEN", "")
    if not token:
        tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pushplus_token")
        if os.path.exists(tp):
            token = open(tp).read().strip()

    phase_order = {"第一波回调(观察买点)": 0, "趋势运行中": 1, "回调过深/转弱": 2}
    cands.sort(key=lambda x: (phase_order.get(x["phase"], 3), -x["adx"]))

    if cands:
        print(f"\nCANDIDATES({len(cands)}):")
        for r in cands:
            print(f"  {r['name']}{r['dir']}{r['phase']}ADX={r['adx']:.0f}波={r['wave']}%回撤={r['pullback']}%")

    if token and cands:
        h = '<div style="font-family:-apple-system,sans-serif;max-width:560px">' 
        h += '<h3 style="margin:0 0 6px">大趋势候选监控 (TrendWatch)</h3>'
        h += f'<div style="font-size:11px;color:#666;margin-bottom:6px">1D 强趋势(ADX&gt;25)+EMA排列+涨跌波&gt;30%　共 {len(cands)} 个</div>'
        for r in cands:
            color = "#27ae60" if r["dir"] == "多" else "#e74c3c"
            if r["phase"].startswith("第一波"):
                pcol = "#d35400"
            elif r["phase"] == "趋势运行中":
                pcol = "#2980b9"
            else:
                pcol = "#7f8c8d"
            p = fmt_p(r["price"], f"{r['name']}-USDT-SWAP")
            h += f'<div style="margin:6px 0;padding:6px;background:#fff;border-left:3px solid {pcol}">'
            h += f'<b>{r["name"]}</b> <span style="color:{color}">{r["dir"]}</span> '
            h += f'<span style="color:{pcol}">{r["phase"]}</span> {p}<br>'
            h += f'<span style="font-size:11px;color:#333">ADX={r["adx"]:.0f} | 波动={r["wave"]}% | 回撤={r["pullback"]}% | EMA50/200={r["ema50"]}/{r["ema200"]}</span>'
            h += '</div>'
        h += '</div>'
        pl = {"token": token, "title": "TrendWatch", "content": h, "template": "html"}
        try:
            rp = requests.post("http://www.pushplus.plus/send", json=pl, timeout=10)
            print("Push:", rp.json().get("code"))
        except Exception as e:
            print("Push error:", e)

if __name__ == "__main__":
    main()
