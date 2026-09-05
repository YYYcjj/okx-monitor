#!/usr/bin/env python3
"""
TrendWatch —— 统一顺势信号扫描（2026-09-05 改版）

核心逻辑（用户定义）：
    在 1 日线关键位置找机会，1 小时与 1 日线共振（方向相同）、SRSI 同向；
    其余（ATR 0.5%-2%、插针门、15m 共振标注、TOP_N 等）都是筛选条件。

两类触发（方向均由 1h/1d 结构共振决定，同多/同空）：
    回调：1d SRSI 极端（1d 多结构+SRSI<20→多；1d 空结构+SRSI>80→空）
    趋势：1h SRSI 极端（1h 多结构+SRSI<20→多；1h 空结构+SRSI>80→空）
共用要求（不满足即剔除）：
    - 1h 结构方向 == 1d 结构方向 == 信号方向（共振同向，横盘 0 淘汰）
    - 价格贴近日线关键位且【未破位】（做多价在 swing low 上方、做空价在 swing high 下方，NEAR_LEVEL_PCT 内）
    - 1h ADX>20、ATR/价 在 (0.5%, 2%)
    - 插针门（WICK_AVG_MAX / WICK_SPIKE_MAX）
保险：非触发侧 SRSI 不在反向极端（做多时 1h/1d 均不>80；做空时均不<20）
拐头确认（补漏②）：触发侧 SRSI 需从极值区回升——做多当前值>前一根、做空当前值<前一根，剔除仍在加速赶底/赶顶的接飞刀情形。
空间硬门（补漏③）：目标位空间 >=3% 或 >=1.5×ATR 才通过（不足/已越过均剔除）。
15m 共振：仅标注「★推荐」（15m 结构与信号同向），不再过滤，帮助优先关注。
推送上限：每日最多前 TOP_N 个（回调优先于趋势、多优先于空、推荐优先、SRSI 越极端越靠前）。
目标位与空间：做多取日线最近 swing high、做空取最近 swing low，达标后仅展示空间。

扫描池：成交量前 100 的 USDT 永续合约。
去重：同一 CST 日期内同一「币种 + 类型 + 方向」只推送一次（状态存于 pushed_state.json）。
股票相关币种（代币化股票 + 名称含股票关键词）已加入黑名单，扫描时跳过、不推送（2026-08-25）。
"""

from tw_conf import *
from tw_calc import *


def main():
    EXCL = ["BRL", "EUR", "TRY", "DAI", "USDC", "RUB"]
    r = requests.get(f"{OKX}/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=15)
    d = r.json()
    if d.get("code") != "0":
        print("Failed:", d); return
    items = [(t["instId"], float(t.get("volCcy24h", 0))) for t in d["data"]
             if "USDT" in t["instId"] and not any(x in t["instId"] for x in EXCL)]
    items.sort(key=lambda x: -x[1])
    vol_top = [i[0] for i in items[:100]]  # 扫描成交量前 100

    seen = set(); syms = []
    for s in vol_top:
        if s not in seen:
            seen.add(s); syms.append(s)
    print(f"Scan pool: {len(syms)} vol-top unique...")

    cands = []
    skipped_stock = 0
    for s in syms:
        name = s.replace("-USDT-SWAP", "")
        if is_stock_related(name):
            skipped_stock += 1
            continue
        c1d = get_candles(s, "1D", 200)
        c1h = get_candles(s, "1H", 100)
        if not c1d or not c1h:
            continue
        closes1 = [c["c"] for c in c1d]
        closes1h = [c["c"] for c in c1h]
        opens1h = [c["o"] for c in c1h]
        highs1h = [c["h"] for c in c1h]
        lows1h = [c["l"] for c in c1h]
        highs1d = [c["h"] for c in c1d]
        lows1d = [c["l"] for c in c1d]
        kv1 = calc_stoch_rsi_series(closes1)
        kv1h = calc_stoch_rsi_series(closes1h)
        if kv1 is None or kv1h is None:
            continue
        s1 = srsi_last(kv1)
        s1h = srsi_last(kv1h)
        if s1 is None or s1h is None:
            continue
        # SRSI 前一根值（拐头确认用，补漏②）：做多需从极值回升、做空需从极值回落
        s1p = kv1[-2] if len(kv1) >= 2 else None
        s1hp = kv1h[-2] if len(kv1h) >= 2 else None
        # 质量门指标（1h）
        atr1h = calc_atr(highs1h, lows1h, closes1h)
        adx1h = calc_adx(highs1h, lows1h, closes1h)
        if atr1h is None or adx1h is None:
            continue
        atr_ratio = atr1h / closes1h[-1] if closes1h[-1] > 0 else 0.0
        wflag = wick_ok(highs1h, lows1h, opens1h, closes1h)
        # 结构方向（1h + 1d 共振，必须同向才算信号）
        d1h = structure_dir(highs1h, lows1h, min_pct=MIN_SWING_PCT_1H)
        d1d = structure_dir(highs1d, lows1d, min_pct=MIN_SWING_PCT_1D)
        # 日线 swing 点：关键位与参考目标
        sh1d, sl1d = find_swings(highs1d, lows1d, p=SWING_P)
        res = classify(s1, s1h, s1p, s1hp, adx1h, atr_ratio, wflag, d1h, d1d,
                       closes1[-1], sh1d, sl1d)
        if res is None:
            continue
        kind, dirn, extra = res
        # 15m 共振（仅标注，不再作为过滤门槛）：与信号同向(多=HH/HL，空=LH/LL)则标「推荐」
        c15 = get_candles(s, "15m", 100)
        d15m = 0
        if c15:
            d15m = structure_dir([c["h"] for c in c15], [c["l"] for c in c15],
                                 min_pct=MIN_SWING_PCT_15M)
        rec = (d15m == (1 if dirn == "多" else -1))
        cands.append({
            "name": name, "kind": kind, "dir": dirn,
            "s1": round(s1, 1), "s1h": round(s1h, 1),
            "d1h": d1h, "d1d": d1d, "d15m": d15m, "rec": rec,
            "adx": round(adx1h, 1), "atrr": atr_ratio,
            "price": closes1[-1],
            "tgt": extra.get("tgt"),
            "space_pct": extra.get("space_pct"),
            "space_atr": extra.get("space_atr"),
        })
        time.sleep(0.05)

    print(f"Skipped stock-related symbols: {skipped_stock}")
    token = os.environ.get("PUSHPLUS_TOKEN", "")
    if not token:
        tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pushplus_token")
        if os.path.exists(tp):
            token = open(tp).read().strip()

    # 同日去重：键为「币种|类型方向」，同一币当天可分别推回调与趋势
    def _dedup_key(c):
        return f"{c['name']}|{c['kind']}{c['dir']}"
    pushed = load_pushed()
    new_cands = [c for c in cands if _dedup_key(c) not in pushed]
    if cands and not new_cands:
        print(f"All {len(cands)} signal(s) already pushed today, skip.")

    # 排序：回调在前、趋势在后；组内多在前、空在后；同组内「推荐」优先；
    #       再按触发侧 SRSI 极端度排（越极端越靠前）：回调看 1d，趋势看 1h
    def _sort_key(x):
        k = 0 if x["kind"] == "回调" else 1
        base = 0 if x["dir"] == "多" else 1
        rec = 0 if x["rec"] else 1
        v = x["s1"] if x["kind"] == "回调" else x["s1h"]
        return (k, base, rec, v if x["dir"] == "多" else -v)
    new_cands.sort(key=_sort_key)
    if len(new_cands) > TOP_N:
        print(f"Cap to top {TOP_N} (from {len(new_cands)}).")
        new_cands = new_cands[:TOP_N]

    if new_cands:
        print(f"\nNEW SIGNALS({len(new_cands)}):")
        for r in new_cands:
            rec_tag = " [推荐]" if r["rec"] else ""
            line = (f"  [{r['kind']}]{rec_tag} {r['name']} {r['dir']} "
                    f"SRSI(1d/1h)={r['s1']}/{r['s1h']} ADX(1h)={r['adx']:.0f} "
                    f"ATR/价={r['atrr']*100:.2f}% 结构(1h/1d/15m)={r['d1h']}/{r['d1d']}/{r['d15m']} price={r['price']}")
            if r["tgt"] is not None and r["space_pct"] is not None:
                if r["space_pct"] >= 0:
                    line += f" | 目标={r['tgt']} 空间=+{r['space_pct']:.1f}%"
                    if r["space_atr"] is not None:
                        line += f"（{r['space_atr']:.1f}×ATR）"
                else:
                    line += f" | 目标={r['tgt']} 已越过{abs(r['space_pct']):.1f}%"
            print(line)

    if token and new_cands:
        h = '<div style="font-family:-apple-system,sans-serif;max-width:560px">' 
        h += '<h3 style="margin:0 0 6px">TrendWatch（回调 / 趋势）</h3>'
        h += (f'<div style="font-size:11px;color:#666;margin-bottom:6px">'
              f'1h/1d 共振同向 + SRSI 同向拐头 + 日线关键位未破 ｜ '
              f'回调：1d SRSI 极端触发 ｜ 趋势：1h SRSI 极端触发 ｜ '
              f'质量门：ADX&gt;{ADX_THRESHOLD} &amp; ATR/价 {ATR_MIN_RATIO*100:.1f}-{ATR_MAX_RATIO*100:.0f}% &amp; 插针门 &amp; 空间≥{MIN_SPACE_ATR:g}×ATR/{MIN_SPACE_PCT:g}% ｜ '
              f'每日前 {TOP_N} 个　共 {len(new_cands)} 个</div>')
        for r in new_cands:
            color = "#27ae60" if r["dir"] == "多" else "#e74c3c"
            kcolor = "#185fa5" if r["kind"] == "回调" else "#b8860b"
            inst = f"{r['name']}-USDT-SWAP"
            p = fmt_p(r["price"], inst)
            # 推荐：加金色左边框 + 浅金底 + 「★推荐」徽标
            border = "#d4a017" if r["rec"] else color
            bg = "#fffdf2" if r["rec"] else "#fff"
            rec_badge = (' <span style="background:#d4a017;color:#fff;font-size:10px;'
                         'padding:1px 4px;border-radius:3px;font-weight:bold">★推荐</span>') if r["rec"] else ""
            h += f'<div style="margin:5px 0;padding:6px;background:{bg};border-left:3px solid {border}">'
            h += (f'<b>{r["name"]}</b>{rec_badge} <span style="color:{kcolor}">[{r["kind"]}]</span> '
                  f'<span style="color:{color}">{r["dir"]}</span> {p}<br>')
            h += (f'<span style="font-size:11px;color:#333">SRSI(1d/1h)={r["s1"]}/{r["s1h"]} | '
                  f'ADX(1h)={r["adx"]:.0f} | ATR/价={r["atrr"]*100:.2f}% | 结构(1h/1d/15m)={r["d1h"]}/{r["d1d"]}/{r["d15m"]}</span>')
            if r["tgt"] is not None and r["space_pct"] is not None:
                if r["space_pct"] >= 0:
                    seg = (f'<br><span style="font-size:11px;color:#333">目标 {fmt_p(r["tgt"], inst)}'
                           f'（空间 +{r["space_pct"]:.1f}%')
                    if r["space_atr"] is not None:
                        seg += f'，{r["space_atr"]:.1f}×ATR'
                    h += seg + '）</span>'
                else:
                    h += (f'<br><span style="font-size:11px;color:#a32d2d">目标 {fmt_p(r["tgt"], inst)}'
                          f'（已越过 {abs(r["space_pct"]):.1f}%，目标位无效）</span>')
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
