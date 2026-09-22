#!/usr/bin/env python3
"""
TrendWatch —— 统一顺势信号扫描（2026-09-22 起为**单一策略**）

策略一句话：**以日线为锚（方向 + 位置 + 触发），1 小时确认方向，4 小时做反向保险。**
（2026-09-22 按用户要求，把原先并列的「1d 型（回调/趋势）」与「4H 型」合并成这一套。）

固定门（系统既有质量门，不变）：
    1h ADX > ADX_THRESHOLD(20) ｜ ATR/价 ∈ (0.5%, 2%) ｜ 目标空间 > MIN_SPACE_PCT(10%)
    （目标取日线最近 swing 高/低；空间 = 目标到现价）

策略四条件（须全部满足；判定见 tw_calc.classify）：
    ① 1小时不与日线反向：日线结构非横盘，且 1h 结构为「横盘或与日线同向」（明确反向才淘汰）
    ② 日线在关键位置：做多贴日线 swing low（支撑）/ 做空贴日线 swing high（阻力），±2.5%
    ③ 日线 SRSI 超买超卖位：做多 s1 < 25 / 做空 s1 > 75（触发条件）
    ④ 4小时 SRSI 不在反向极值：做多 s4h ≤ 80 / 做空 s4h ≥ 20（保险）

15m 共振：仅标注「★推荐」（15m 结构与信号同向），不过滤，帮助优先关注。
推送上限：每日最多前 TOP_N 个（多优先于空 → 推荐优先 → 日线 SRSI 越极端越靠前）。
目标位与空间：目标位（日线最近 swing 高/低）仅展示，空间参与过滤。
扫描池：成交量前 100 的 USDT 永续合约。
去重：同一 CST 日期内同一「币种 + 方向」只推送一次（key =「币种|日线多/空」，状态存于 pushed_state.json）。
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
        c4h = get_candles(s, "4H", 100)   # 4h 只用于「SRSI 不反向极值」这道保险门（2026-09-22 起不再用于方向/关键位）
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
        # 4h：SRSI 末值（保险门）+ 结构方向（仅卡片展示，不参与判定）
        s4h, d4h = None, 0
        if c4h:
            kv4 = calc_stoch_rsi_series([c["c"] for c in c4h])
            s4h = srsi_last(kv4) if kv4 else None
            d4h = structure_dir([c["h"] for c in c4h], [c["l"] for c in c4h],
                                min_pct=MIN_SWING_PCT_4H)
        # 质量门指标（1h）
        atr1h = calc_atr(highs1h, lows1h, closes1h)
        adx1h = calc_adx(highs1h, lows1h, closes1h)
        if atr1h is None or adx1h is None:
            continue
        atr_ratio = atr1h / closes1h[-1] if closes1h[-1] > 0 else 0.0
        # 结构方向：1d 与 1h 是**过滤依据**（须同向）；4h/15m 仅展示/标注
        d1h = structure_dir(highs1h, lows1h, min_pct=MIN_SWING_PCT_1H)
        d1d = structure_dir(highs1d, lows1d, min_pct=MIN_SWING_PCT_1D)
        # 日线 swing 点：关键位与参考目标
        sh1d, sl1d = find_swings(highs1d, lows1d, p=SWING_P)
        # —— 单一策略判定（tw_calc.classify）——
        res = classify(s1, s1h, s4h, adx1h, atr_ratio, d1d, d1h,
                       closes1[-1], sh1d, sl1d)
        if not res:
            continue
        kind, dirn, extra = res
        # 15m 共振（仅标注，不作为过滤门槛）：与信号同向(多=HH/HL，空=LH/LL)则标「推荐」
        c15 = get_candles(s, "15m", 100)
        d15m = 0
        if c15:
            d15m = structure_dir([c["h"] for c in c15], [c["l"] for c in c15],
                                 min_pct=MIN_SWING_PCT_15M)
        rec = (d15m == (1 if dirn == "多" else -1))
        cands.append({
            "name": name, "kind": kind, "dir": dirn,
            "s1": round(s1, 1), "s1h": round(s1h, 1),
            "s4h": None if s4h is None else round(s4h, 1),
            "d1h": d1h, "d4h": d4h, "d1d": d1d, "d15m": d15m, "rec": rec,
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

    # 同日去重：键为「币种|类型方向」（单类型后即「币种|日线多/空」），同一币当天同一方向只推一次
    def _dedup_key(c):
        return f"{c['name']}|{c['kind']}{c['dir']}"
    pushed = load_pushed()
    new_cands = [c for c in cands if _dedup_key(c) not in pushed]
    if cands and not new_cands:
        print(f"All {len(cands)} signal(s) already pushed today, skip.")

    # 排序：多在前、空在后 → 「推荐」优先 → 日线 SRSI 越极端越靠前
    #       （单类型后不再有类型分组；触发依据就是日线 SRSI）
    def _sort_key(x):
        base = 0 if x["dir"] == "多" else 1
        rec = 0 if x["rec"] else 1
        v = x["s1"]
        return (base, rec, v if x["dir"] == "多" else -v)
    new_cands.sort(key=_sort_key)
    if len(new_cands) > TOP_N:
        print(f"Cap to top {TOP_N} (from {len(new_cands)}).")
        new_cands = new_cands[:TOP_N]

    if new_cands:
        print(f"\nNEW SIGNALS({len(new_cands)}):")
        for r in new_cands:
            rec_tag = " [推荐]" if r["rec"] else ""
            line = (f"  [{r['kind']}]{rec_tag} {r['name']} {r['dir']} "
                    f"SRSI(1d/1h/4h)={r['s1']}/{r['s1h']}/{r['s4h']} ADX(1h)={r['adx']:.0f} "
                    f"ATR/价={r['atrr']*100:.2f}% "
                    f"结构(1d/1h/4h/15m)={r['d1d']}/{r['d1h']}/{r['d4h']}/{r['d15m']} "
                    f"price={r['price']}")
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
        h += '<h3 style="margin:0 0 6px">TrendWatch（日线关键位 · 1d/1h 同向）</h3>'
        h += (f'<div style="font-size:11px;color:#666;margin-bottom:6px">'
              f'<b>策略</b>：① 1小时不与日线反向 ② 日线在关键位置（±{NEAR_LEVEL_PCT*100:.1f}%）'
              f' ③ 日线 SRSI 超买超卖位（多&lt;{SRSI1D_LOW} / 空&gt;{SRSI1D_HIGH}）'
              f' ④ 4小时 SRSI 不在反向极值（{SRSI_LOW}/{SRSI_HIGH}） ｜ '
              f'质量门：ADX&gt;{ADX_THRESHOLD} &amp; ATR/价 {ATR_MIN_RATIO*100:.1f}-{ATR_MAX_RATIO*100:.0f}% &amp; 空间&gt;{MIN_SPACE_PCT:.0f}% ｜ '
              f'每日前 {TOP_N} 个　共 {len(new_cands)} 个</div>')
        for r in new_cands:
            color = "#27ae60" if r["dir"] == "多" else "#e74c3c"
            kcolor = "#7b4fb5"   # 单类型（日线锚定）统一紫色，与走势图页一致
            inst = f"{r['name']}-USDT-SWAP"
            p = fmt_p(r["price"], inst)
            dirmap = {1: "上行↑", -1: "下行↓", 0: "横盘"}
            # 推荐：加金色左边框 + 浅金底 + 「★推荐」徽标
            border = "#d4a017" if r["rec"] else color
            bg = "#fffdf2" if r["rec"] else "#fff"
            rec_badge = (' <span style="background:#d4a017;color:#fff;font-size:10px;'
                         'padding:1px 4px;border-radius:3px;font-weight:bold">★推荐</span>') if r["rec"] else ""
            h += f'<div style="margin:5px 0;padding:7px 9px;background:{bg};border-left:3px solid {border};border-radius:0 6px 6px 0">'
            # 第一行：币名 + 类型 + 方向 + 价格
            h += (f'<div style="display:flex;align-items:baseline;gap:5px;flex-wrap:wrap;line-height:1.4">'
                  f'<b style="font-size:14px">{r["name"]}</b>{rec_badge} '
                  f'<span style="color:{kcolor};font-size:12px">[{r["kind"]}]</span> '
                  f'<span style="color:{color};font-size:12px;font-weight:bold">{r["dir"]}</span> '
                  f'<span style="font-size:11px;color:#666">{p}</span></div>')
            # 第二行：SRSI —— 1d 是触发（标出），1h 是方向确认，4h 是反向保险
            s4txt = "—" if r["s4h"] is None else f'{r["s4h"]:.1f}'
            h += (f'<div style="font-size:12px;color:#333;margin-top:5px">SRSI '
                  f'<b style="color:{kcolor}">1d {r["s1"]:.1f}</b>'
                  f'<span style="color:#888;font-size:11px"> ← 触发</span>'
                  f' / 1h <b>{r["s1h"]:.1f}</b> / 4h <b>{s4txt}</b></div>')
            # 第三行：结构 + 方向（1d、1h 是过滤依据，4h/15m 仅展示与标注）
            h += (f'<div style="font-size:12px;color:#333;margin-top:2px">结构 '
                  f'1d <b>{dirmap.get(r["d1d"], r["d1d"])}</b> · '
                  f'1h <b>{dirmap.get(r["d1h"], r["d1h"])}</b> · '
                  f'4h <b>{dirmap.get(r["d4h"], r["d4h"])}</b> · '
                  f'15m <b>{dirmap.get(r["d15m"], r["d15m"])}</b> '
                  f'｜ 方向 <b style="color:{color}">{r["dir"]}</b></div>')
            # 第四行：ADX + ATR/价（质量门）
            h += (f'<div style="font-size:12px;color:#333;margin-top:2px">'
                  f'ADX(1h) <b>{r["adx"]:.0f}</b> ｜ ATR/价 <b>{r["atrr"]*100:.2f}%</b></div>')
            # 分隔线 + 目标/空间
            if r["tgt"] is not None and r["space_pct"] is not None:
                if r["space_pct"] >= 0:
                    seg = (f'<div style="font-size:12px;color:#333;margin-top:4px;'
                           f'border-top:0.5px solid #ececec;padding-top:4px">目标 {fmt_p(r["tgt"], inst)}'
                           f' · 空间 +{r["space_pct"]:.1f}%')
                    if r["space_atr"] is not None:
                        seg += f'（{r["space_atr"]:.1f}×ATR）'
                    h += seg + '</div>'
                else:
                    h += (f'<div style="font-size:12px;color:#a32d2d;margin-top:4px">目标 {fmt_p(r["tgt"], inst)}'
                          f'（已越过 {abs(r["space_pct"]):.1f}%，目标位无效）</div>')
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
