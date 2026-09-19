#!/usr/bin/env python3
"""
TrendWatch 逐门诊断（临时脚本，用完即撤）

目的：回答"为什么没有推送"——统计扫描池在每个过滤门各被砍掉多少币，
      并列出「只差一门」的币，便于判断是哪道门在挡。

产出：gate_diag.md（提交回仓库，便于直接查看）
口径：与 scan_trend.py / tw_calc.classify 完全一致（同一批 tw_conf 阈值）
"""

import collections
import os
import time
from datetime import datetime, timezone, timedelta

from tw_conf import *
from tw_calc import *

EXCL = ["BRL", "EUR", "TRY", "DAI", "USDC", "RUB"]


def main():
    r = requests.get(f"{OKX}/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=15)
    d = r.json()
    if d.get("code") != "0":
        print("Failed:", d); return
    items = [(t["instId"], float(t.get("volCcy24h", 0))) for t in d["data"]
             if "USDT" in t["instId"] and not any(x in t["instId"] for x in EXCL)]
    items.sort(key=lambda x: -x[1])
    syms = [i[0] for i in items[:100]]

    cnt = collections.Counter()
    near = []          # 只差 1 门
    near2 = []         # 只差 2 门
    passed = []        # 全通过
    passed_no_space = []   # 忽略空间门后通过

    for s in syms:
        name = s.replace("-USDT-SWAP", "")
        if is_stock_related(name):
            cnt["黑名单(股票类)"] += 1
            continue
        c1d = get_candles(s, "1D", 200)
        c1h = get_candles(s, "1H", 100)
        if not c1d or not c1h:
            cnt["数据拉取失败"] += 1
            continue
        closes1 = [c["c"] for c in c1d]
        closes1h = [c["c"] for c in c1h]
        highs1h = [c["h"] for c in c1h]; lows1h = [c["l"] for c in c1h]
        highs1d = [c["h"] for c in c1d]; lows1d = [c["l"] for c in c1d]
        kv1 = calc_stoch_rsi_series(closes1)
        kv1h = calc_stoch_rsi_series(closes1h)
        atr1h = calc_atr(highs1h, lows1h, closes1h)
        adx1h = calc_adx(highs1h, lows1h, closes1h)
        if not kv1 or not kv1h or atr1h is None or adx1h is None:
            cnt["指标样本不足"] += 1
            continue
        s1, s1h = srsi_last(kv1), srsi_last(kv1h)
        atr_ratio = atr1h / closes1h[-1] if closes1h[-1] > 0 else 0.0
        d1h = structure_dir(highs1h, lows1h, min_pct=MIN_SWING_PCT_1H)
        d1d = structure_dir(highs1d, lows1d, min_pct=MIN_SWING_PCT_1D)
        sh1d, sl1d = find_swings(highs1d, lows1d, p=SWING_P)
        price = closes1[-1]

        fails = []
        if adx1h < ADX_THRESHOLD:
            fails.append("ADX≤20")
        if not (ATR_MIN_RATIO < atr_ratio < ATR_MAX_RATIO):
            fails.append("ATR区间外")
        dirn = None
        if d1d == 0:
            fails.append("1d结构横盘")
        else:
            dirn = d1d
            if d1h != dirn:
                fails.append("1h未同向")
            levels = [p for _, p in (sl1d[-2:] if dirn == 1 else sh1d[-2:])]
            if not near_key_level(price, levels):
                fails.append("未贴关键位")
            if dirn == 1:
                srsi_ok = (s1 <= SRSI_HIGH and s1h <= SRSI_HIGH) and (s1 < SRSI_LOW or s1h < SRSI_LOW)
                kind = "回调" if s1 < SRSI_LOW else ("趋势" if s1h < SRSI_LOW else None)
            else:
                srsi_ok = (s1 >= SRSI_LOW and s1h >= SRSI_LOW) and (s1 > SRSI_HIGH or s1h > SRSI_HIGH)
                kind = "回调" if s1 > SRSI_HIGH else ("趋势" if s1h > SRSI_HIGH else None)
            if not srsi_ok:
                fails.append("SRSI未极端")
            target = (sh1d[-1][1] if (dirn == 1 and sh1d) else (sl1d[-1][1] if (dirn == -1 and sl1d) else None))
            space = None
            if target and price > 0:
                space = ((target - price) / price if dirn == 1 else (price - target) / price) * 100
            if space is None or space <= MIN_SPACE_PCT:
                fails.append("空间≤10%")

        detail = (f"{name} {'多' if dirn == 1 else ('空' if dirn == -1 else '-')} "
                  f"SRSI {s1:.0f}/{s1h:.0f} ADX {adx1h:.0f} ATR {atr_ratio*100:.2f}% "
                  f"结构 {d1h}/{d1d}")
        if not fails:
            passed.append(detail)
        else:
            for f in fails:
                cnt[f] += 1
            if len(fails) == 1:
                near.append(f"{detail} ← 只差「{fails[0]}」")
            elif len(fails) == 2:
                near2.append(f"{detail} ← 差「{fails[0]}」「{fails[1]}」")
            if [f for f in fails if f != "空间≤10%"] == []:
                passed_no_space.append(detail)
        time.sleep(0.05)

    cst = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST")
    L = []
    L.append(f"# TrendWatch 逐门诊断（{cst}）\n")
    L.append(f"扫描池：成交额前 100 的 USDT 永续（本次实际参与判定 {sum(1 for s in syms)} 个）\n")
    L.append("口径：ADX>20 → ATR/价 0.5-2% → 1d 结构定方向 → 1h 同向 → 贴日线关键位 ±1.5% → SRSI 同向极端 → 目标空间 >10%\n")
    L.append("## 各门淘汰计数（同一币可命中多个门）\n")
    L.append("| 门 | 淘汰币数 |\n|---|---|")
    for k, v in cnt.most_common():
        L.append(f"| {k} | {v} |")
    L.append(f"\n**通过全部门的候选：{len(passed)} 个**\n")
    if passed:
        L.append("```")
        L += passed
        L.append("```")
    L.append(f"\n**只差 1 门的币：{len(near)} 个**\n")
    if near:
        L.append("```")
        L += near[:20]
        L.append("```")
    L.append(f"\n**只差 2 门的币：{len(near2)} 个（前 15）**\n")
    if near2:
        L.append("```")
        L += near2[:15]
        L.append("```")
    L.append(f"\n**对照：如果只看「其他门全过、仅卡在空间门」→ {len(passed_no_space)} 个**")
    L.append("\n> 本文件由 diag_gates.py 生成（临时诊断，用完即撤）\n")

    open("gate_diag.md", "w").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
