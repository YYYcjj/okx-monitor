#!/usr/bin/env python3
"""
TrendWatch 逐门诊断（临时脚本，用完即撤）

目的：
  1) 统计扫描池在每道门各被砍掉多少币（回答"为什么没推送"）
  2) 同一批行情下对照几种放宽方案的产出量（回答"放宽哪一条最有效"）

产出：gate_diag.md
口径：基础门槛与 tw_calc.classify 一致（同一批 tw_conf 阈值）
"""

import collections
import os
import time
from datetime import datetime, timezone, timedelta

from tw_conf import *
from tw_calc import *

EXCL = ["BRL", "EUR", "TRY", "DAI", "USDC", "RUB"]

D = []   # 每个币的原始指标


def eval_coin(c, level_pct, space_min, allow_1h_anchor, use_space=True):
    """按给定口径返回失败门列表 + 触发信息。"""
    fails = []
    if c["adx"] < ADX_THRESHOLD:
        fails.append("ADX≤20")
    if not (ATR_MIN_RATIO < c["atr_ratio"] < ATR_MAX_RATIO):
        fails.append("ATR区间外")
    d1d, d1h, price = c["d1d"], c["d1h"], c["price"]
    # 方向锚：默认 1d；allow_1h_anchor 时，1d 横盘则改用 1h 定方向
    dirn = d1d
    if dirn == 0:
        if allow_1h_anchor and d1h != 0:
            dirn = d1h
        else:
            fails.append("1d结构横盘")
    if dirn != 0:
        if d1h != dirn:
            fails.append("1h未同向")
        levels = [p for _, p in (c["sl1d"][-2:] if dirn == 1 else c["sh1d"][-2:])]
        if not near_key_level(price, levels, pct=level_pct):
            fails.append("未贴关键位")
        s1, s1h = c["s1"], c["s1h"]
        if dirn == 1:
            srsi_ok = (s1 <= SRSI_HIGH and s1h <= SRSI_HIGH) and (s1 < SRSI_LOW or s1h < SRSI_LOW)
            kind = "回调" if s1 < SRSI_LOW else ("趋势" if s1h < SRSI_LOW else None)
        else:
            srsi_ok = (s1 >= SRSI_LOW and s1h >= SRSI_LOW) and (s1 > SRSI_HIGH or s1h > SRSI_HIGH)
            kind = "回调" if s1 > SRSI_HIGH else ("趋势" if s1h > SRSI_HIGH else None)
        if not srsi_ok:
            fails.append("SRSI未极端")
        target = c["sh_last"] if (dirn == 1) else c["sl_last"]
        space = None
        if target and price > 0:
            space = ((target - price) / price if dirn == 1 else (price - target) / price) * 100
        if use_space and (space is None or space <= space_min):
            fails.append("空间≤10%")
        return fails, (dirn, kind, space)
    return fails, (0, None, None)


def main():
    global D
    r = requests.get(f"{OKX}/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=15)
    d = r.json()
    if d.get("code") != "0":
        print("Failed:", d); return
    items = [(t["instId"], float(t.get("volCcy24h", 0))) for t in d["data"]
             if "USDT" in t["instId"] and not any(x in t["instId"] for x in EXCL)]
    items.sort(key=lambda x: -x[1])
    syms = [i[0] for i in items[:100]]

    skip = collections.Counter()
    for s in syms:
        name = s.replace("-USDT-SWAP", "")
        if is_stock_related(name):
            skip["黑名单(股票类)"] += 1
            continue
        c1d = get_candles(s, "1D", 200)
        c1h = get_candles(s, "1H", 100)
        if not c1d or not c1h:
            skip["数据拉取失败"] += 1
            continue
        cl1 = [c["c"] for c in c1d]; cl1h = [c["c"] for c in c1h]
        hi1h = [c["h"] for c in c1h]; lo1h = [c["l"] for c in c1h]
        hi1d = [c["h"] for c in c1d]; lo1d = [c["l"] for c in c1d]
        kv1 = calc_stoch_rsi_series(cl1); kv1h = calc_stoch_rsi_series(cl1h)
        atr1h = calc_atr(hi1h, lo1h, cl1h); adx1h = calc_adx(hi1h, lo1h, cl1h)
        if not kv1 or not kv1h or atr1h is None or adx1h is None:
            skip["指标样本不足"] += 1
            continue
        sh1d, sl1d = find_swings(hi1d, lo1d, p=SWING_P)
        D.append({
            "name": name, "price": cl1[-1],
            "s1": srsi_last(kv1), "s1h": srsi_last(kv1h),
            "adx": adx1h, "atr_ratio": atr1h / cl1h[-1] if cl1h[-1] > 0 else 0.0,
            "d1h": structure_dir(hi1h, lo1h, min_pct=MIN_SWING_PCT_1H),
            "d1d": structure_dir(hi1d, lo1d, min_pct=MIN_SWING_PCT_1D),
            "sh1d": sh1d, "sl1d": sl1d,
            "sh_last": sh1d[-1][1] if sh1d else None,
            "sl_last": sl1d[-1][1] if sl1d else None,
        })
        time.sleep(0.05)

    # 基础口径
    cnt = collections.Counter()
    near1, near2, passed = [], [], []
    for c in D:
        fails, _ = eval_coin(c, NEAR_LEVEL_PCT, MIN_SPACE_PCT, False, True)
        detail = (f"{c['name']} {'多' if c['d1d'] == 1 else ('空' if c['d1d'] == -1 else '-')} "
                  f"SRSI {c['s1']:.0f}/{c['s1h']:.0f} ADX {c['adx']:.0f} "
                  f"ATR {c['atr_ratio']*100:.2f}% 结构 {c['d1h']}/{c['d1d']}")
        if not fails:
            passed.append(detail)
        else:
            for f in fails:
                cnt[f] += 1
            if len(fails) == 1:
                near1.append(f"{detail} ← 只差「{fails[0]}」")
            elif len(fails) == 2:
                near2.append(f"{detail} ← 差「{fails[0]}」「{fails[1]}」")
    for k, v in skip.items():
        cnt[k] += v

    # 放宽方案对照
    variants = [
        ("基础口径（现状）", NEAR_LEVEL_PCT, MIN_SPACE_PCT, False, True),
        ("A. 去掉空间 >10% 门", NEAR_LEVEL_PCT, MIN_SPACE_PCT, False, False),
        ("B. 贴关键位放宽到 ±2.5%", 0.025, MIN_SPACE_PCT, False, True),
        ("C. 1d 横盘时改用 1h 定方向", NEAR_LEVEL_PCT, MIN_SPACE_PCT, True, True),
        ("D. A+B+C 全放宽", 0.025, MIN_SPACE_PCT, True, False),
    ]
    vres = []
    for label, lp, sp, anchor, use_space in variants:
        rows = []
        for c in D:
            fails, info = eval_coin(c, lp, sp, anchor, use_space)
            if not fails:
                dirn, kind, space = info
                rows.append(f"{c['name']} {'多' if dirn == 1 else '空'} {kind or ''} "
                            f"SRSI {c['s1']:.0f}/{c['s1h']:.0f} 空间 " +
                            ("—" if space is None else f"{space:.1f}%"))
        vres.append((label, rows))

    cst = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST")
    L = [f"# TrendWatch 逐门诊断（{cst}）\n",
         f"扫描池：成交额前 100 的 USDT 永续（本次参与判定 {len(D)} 个）\n",
         "口径：ADX>20 → ATR/价 0.5-2% → 1d 结构定方向 → 1h 同向 → 贴日线关键位 ±1.5% → SRSI 同向极端 → 目标空间 >10%\n",
         "## 一、各门淘汰计数（同一币可命中多个门）\n", "| 门 | 淘汰币数 |", "|---|---|"]
    for k, v in cnt.most_common():
        L.append(f"| {k} | {v} |")
    L.append(f"\n**基础口径通过的候选：{len(passed)} 个**")
    if passed:
        L.append("```"); L += passed; L.append("```")
    L.append(f"\n**只差 1 门的币：{len(near1)} 个**（看是哪道门在卡）")
    if near1:
        L.append("```"); L += near1[:25]; L.append("```")
    L.append(f"\n**只差 2 门的币：{len(near2)} 个（前 15）**")
    if near2:
        L.append("```"); L += near2[:15]; L.append("```")

    L.append("\n## 二、放宽方案对照（同一批行情，同时刻计算）\n")
    L.append("| 方案 | 通过候选数 |")
    L.append("|---|---|")
    for label, rows in vres:
        L.append(f"| {label} | **{len(rows)}** |")
    for label, rows in vres:
        L.append(f"\n### {label} → {len(rows)} 个")
        if rows:
            L.append("```"); L += rows[:20]; L.append("```")
        else:
            L.append("（无）")

    L.append("\n> 本文件由 diag_gates.py 生成（临时诊断，用完即撤）")
    open("gate_diag.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
