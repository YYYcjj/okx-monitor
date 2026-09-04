#!/usr/bin/env python3
"""
TrendWatch —— 两类信号扫描（2026-09-02 改版）

类型1 趋势回调（顺势中继）：
    主信号：1h SRSI 极值（<20 多 / >80 空）—— 只要 1h，1d 不再要求极值
    方向  ：4h 与 1d 市场结构同向（多 = HH/HL，空 = LH/LL）
    保险  ：1d SRSI 不在反向极端（做多时 1d SRSI <= 80；做空时 1d SRSI >= 20）

类型2 反转（逆势，必须 1h 确认）：
    触发：1d SRSI 处于「同方向」极端
          日线空头结构 且 1d SRSI < 20 → 反转多（回测发现此类常大涨）
          日线多头结构 且 1d SRSI > 80 → 反转空
    位置：价格贴近日线关键位（最近两个 swing 高低点，NEAR_LEVEL_PCT 以内）
    确认：1h CHoCH —— 取最近 CONFIRM_LOOKBACK 根内的最低点/最高点作本段起点，
          再取其后形成的最后一个反弹高点(LH)/回踩低点(HL)；
          最近 CONFIRM_MAX_BARS_1H 根内收盘站上(多)/跌破(空)该位才算确认

质量门（共用）：1h ADX>20、ATR/价>0.5%
插针门（分开）：回调类 WICK_AVG_MAX=6.0 / WICK_SPIKE_MAX=10.0
              反转类 WICK_AVG_MAX_REV=10.0 / WICK_SPIKE_MAX_REV=16.0
              —— 反转行情由剧烈波动构成，长影线是常态，沿用严阈值会误杀典型反转（2026-09-02）
目标位与空间（2026-09-02 新增）：做多取日线最近 swing high、做空取最近 swing low，
    推送显示「目标价（空间 X%，N×ATR）」，仅作展示、**不参与过滤**，值不值得做由人判断。

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
    vol_top = [i[0] for i in items[:100]]  # 扫描成交量前 100（2026-09-01 由 50 放宽至 100）

    new_coins = []  # 不再扫描新币池，只保留成交量前 100

    seen = set(); syms = []
    for s in vol_top + new_coins:
        if s not in seen:
            seen.add(s); syms.append(s)
    print(f"Scan pool: {len(vol_top)} vol-top + {len(new_coins)} new = {len(syms)} unique...")

    cands = []
    skipped_stock = 0
    for s in syms:
        name = s.replace("-USDT-SWAP", "")
        if is_stock_related(name):
            skipped_stock += 1
            continue
        c1d = get_candles(s, "1D", 200)
        c4h = get_candles(s, "4H", 100)
        c1h = get_candles(s, "1H", 100)
        if not c1d or not c4h or not c1h:
            continue
        closes1 = [c["c"] for c in c1d]
        closes4 = [c["c"] for c in c4h]
        closes1h = [c["c"] for c in c1h]
        opens1h = [c["o"] for c in c1h]
        highs1h = [c["h"] for c in c1h]
        lows1h = [c["l"] for c in c1h]
        highs4 = [c["h"] for c in c4h]
        lows4 = [c["l"] for c in c4h]
        highs1d = [c["h"] for c in c1d]
        lows1d = [c["l"] for c in c1d]
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
        # 质量门指标（1h）
        atr1h = calc_atr(highs1h, lows1h, closes1h)
        adx1h = calc_adx(highs1h, lows1h, closes1h)
        if atr1h is None or adx1h is None:
            continue
        atr_ratio = atr1h / closes1h[-1] if closes1h[-1] > 0 else 0.0
        wflag = wick_ok(highs1h, lows1h, opens1h, closes1h)
        # 反转类专用：插针门放宽（反转行情长影线是常态，沿用严阈值会误杀）
        wflag_rev = wick_ok(highs1h, lows1h, opens1h, closes1h,
                            avg_max=WICK_AVG_MAX_REV, spike_max=WICK_SPIKE_MAX_REV)
        # 结构方向：4h/1d 用于类型1 同向过滤（2026-09-02 改版），1h 仅展示参考
        d1h = structure_dir(highs1h, lows1h, min_pct=MIN_SWING_PCT_1H)
        d4h = structure_dir(highs4, lows4, min_pct=MIN_SWING_PCT_4H)
        d1d = structure_dir(highs1d, lows1d, min_pct=MIN_SWING_PCT_1D)
        # 日线 swing 点：类型2 用作「关键位」与参考目标
        sh1d, sl1d = find_swings(highs1d, lows1d, p=SWING_P)
        res = classify(s1, s1h, adx1h, atr_ratio, wflag, wflag_rev, d4h, d1d,
                       closes1[-1], sh1d, sl1d, highs1h, lows1h, closes1h)
        if res is None:
            continue
        kind, dirn, extra = res
        cands.append({
            "name": name, "kind": kind, "dir": dirn,
            "s1": round(s1, 1), "s1h": round(s1h, 1), "s4": round(s4, 1),
            "d1h": d1h, "d4h": d4h, "d1d": d1d,
            "adx": round(adx1h, 1), "atrr": atr_ratio,
            "price": closes1[-1],
            "break_lvl": extra.get("break_lvl"),
            "ago": extra.get("ago"),
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

    # 同日去重：键为「币种|类型方向」，同一币当天可以分别推回调与反转
    def _dedup_key(c):
        return f"{c['name']}|{c['kind']}{c['dir']}"
    pushed = load_pushed()
    new_cands = [c for c in cands if _dedup_key(c) not in pushed]
    if cands and not new_cands:
        print(f"All {len(cands)} signal(s) already pushed today, skip.")

    # 排序：回调在前、反转在后；组内多在前、空在后；再按主信号 SRSI 排（越极端越靠前）
    def _sort_key(x):
        k = 0 if x["kind"] == "回调" else 1
        base = 0 if x["dir"] == "多" else 1
        v = x["s1h"] if x["kind"] == "回调" else x["s1"]   # 回调看 1h，反转看 1d
        return (k, base, v if x["dir"] == "多" else -v)
    new_cands.sort(key=_sort_key)

    if new_cands:
        print(f"\nNEW SIGNALS({len(new_cands)}):")
        for r in new_cands:
            line = (f"  [{r['kind']}] {r['name']} {r['dir']} "
                    f"SRSI(1d/1h/4h)={r['s1']}/{r['s1h']}/{r['s4']} ADX(1h)={r['adx']:.0f} "
                    f"ATR/价={r['atrr']*100:.2f}% 结构(4h/1d)={r['d4h']}/{r['d1d']} price={r['price']}")
            if r["tgt"] is not None and r["space_pct"] is not None:
                if r["space_pct"] >= 0:
                    line += f" | 目标={r['tgt']} 空间=+{r['space_pct']:.1f}%"
                    if r["space_atr"] is not None:
                        line += f"（{r['space_atr']:.1f}×ATR）"
                else:
                    line += f" | 目标={r['tgt']} 已越过{abs(r['space_pct']):.1f}%"
            if r["kind"] == "反转" and r["break_lvl"] is not None:
                ago = "刚突破" if not r["ago"] else f"{r['ago']}根前"
                line += f" | 1h突破位={r['break_lvl']}({ago})"
            print(line)

    if token and new_cands:
        h = '<div style="font-family:-apple-system,sans-serif;max-width:560px">'
        h += '<h3 style="margin:0 0 6px">TrendWatch（回调 / 反转）</h3>'
        h += (f'<div style="font-size:11px;color:#666;margin-bottom:6px">回调：1h SRSI 极值 + 4h/1d 结构同向 ｜ '
              f'反转：1d SRSI 同向极端 + 贴近日线关键位 + 1h 突破确认 ｜ '
              f'质量门：1h ADX&gt;{ADX_THRESHOLD} &amp; ATR/价&gt;{ATR_MIN_RATIO*100:.1f}% &amp; 插针门（回调严/反转宽）　'
              f'共 {len(new_cands)} 个</div>')
        for r in new_cands:
            color = "#27ae60" if r["dir"] == "多" else "#e74c3c"
            kcolor = "#185fa5" if r["kind"] == "回调" else "#b8860b"
            inst = f"{r['name']}-USDT-SWAP"
            p = fmt_p(r["price"], inst)
            h += f'<div style="margin:5px 0;padding:6px;background:#fff;border-left:3px solid {color}">'
            h += (f'<b>{r["name"]}</b> <span style="color:{kcolor}">[{r["kind"]}]</span> '
                  f'<span style="color:{color}">{r["dir"]}</span> {p}<br>')
            h += (f'<span style="font-size:11px;color:#333">SRSI(1d/1h/4h)={r["s1"]}/{r["s1h"]}/{r["s4"]} | '
                  f'ADX(1h)={r["adx"]:.0f} | ATR/价={r["atrr"]*100:.2f}% | 结构(4h/1d)={r["d4h"]}/{r["d1d"]}</span>')
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
            if r["kind"] == "反转" and r["break_lvl"] is not None:
                ago = "刚突破" if not r["ago"] else f"{r['ago']} 根前"
                h += (f'<br><span style="font-size:11px;color:{kcolor}">1h 突破位 '
                      f'{fmt_p(r["break_lvl"], inst)}（{ago}）</span>')
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
