#!/usr/bin/env python3
"""
TrendWatch 横盘窄幅扫描（box scan）—— 2026-09-21 新增

用途：找「长期横盘、最近 1h 开始有趋势」的标的。
    与 scan_trend / build_chart_data 的取向**正好相反**：那两套要求日线结构非横盘
    （d1d=0 直接淘汰），所以箱体横盘的币永远进不了候选；本脚本专门捞这一类。

扫描池：成交额前 SCAN_TOP(500) 的 USDT 永续 —— 比趋势扫描的 100 更大，
        因为「窄幅箱体」在大池子里出现的机会更多。

横盘判定（对 WINDOWS 里每个窗口各算一遍）：
    width(n) = 近 n 根日线的 (最高 - 最低) / 现价
    ratio(n) = 净位移 ÷ 宽度   （单边趋势≈1、来回震荡≈0）
    命中：width(n) <= BOX_MAX(6%) 且 ratio(n) <= BOX_RATIO_MAX(0.5) 且 n >= 7
    为什么必须带 ratio：只卡宽度会被「慢速单边」骗过 —— 例如每天涨 0.2% 的慢牛，
    近 7 日宽度只有 ~1.4%（远小于 6%），但它是趋势不是横盘。加上净位移约束才拦得住。
    hit      = 满足条件的**最长**窗口（= 已经横了多少天）
    narrow   = 所有窗口里最窄的那个（用于观察「还不够窄但接近」的币）

1h 启动判定（只看日线侧有苗头的币，省请求）：
    d1h != 0（1h 结构出方向）且 1h ADX > 20 且 ADX 近 6 根抬升 > 5

输出：box_scan.json（各阈值命中数 + 命中清单 + 最窄 TOP_N 观察名单）
"""

import json
import time
from datetime import datetime, timezone, timedelta

from tw_conf import *
from tw_calc import *

SCAN_TOP = 500          # 扫描池：成交额前 N
BARS_1D = 120           # 日线根数（够覆盖 30 日窗口 + 算结构）
BARS_1H = 100           # 1h 根数（算 ADX 轨迹与结构方向）
WINDOWS = (7, 10, 14, 21, 30)   # 横盘窗口（天），最小 7 = 「一周以上」
BOX_MAX = 6.0           # 横盘阈值：区间宽度 ≤ 6%
BOX_RATIO_MAX = 0.5     # 并要求 净位移÷宽度 ≤ 0.5（拦住「慢速单边」被误判成横盘）
WATCH_MAX = 12.0        # 观察名单门槛：宽度 ≤ 12% 才值得取 1h（省请求）
TOP_N = 40              # 观察名单规模
EXCL = ["BRL", "EUR", "TRY", "DAI", "USDC", "RUB"]
OUT = "box_scan.json"
MIN_INTERVAL_MIN = 55   # 距上次扫描不足这么多分钟就跳过（workflow 每 15 分钟触发，箱体是慢变量）
                        # 需要强制重扫时设环境变量 FORCE=1


def since_last_minutes():
    """距上次扫描过去多少分钟；读不到（首次运行）返回 None。"""
    try:
        t = json.load(open(OUT)).get("generated_at", "")
        dt = datetime.strptime(t, "%Y-%m-%d %H:%M CST").replace(
            tzinfo=timezone(timedelta(hours=8)))
        return (datetime.now(timezone(timedelta(hours=8))) - dt).total_seconds() / 60
    except Exception:
        return None


def box_stats(rows, n):
    """近 n 根日线：宽度%（相对现价）、净位移%、上下沿、净位移比值。"""
    w = rows[-n:]
    hi = max(r["h"] for r in w)
    lo = min(r["l"] for r in w)
    price = rows[-1]["c"]
    width = (hi - lo) / price * 100 if price > 0 else 0.0
    net = abs(rows[-1]["c"] - w[0]["c"]) / w[0]["c"] * 100 if w[0]["c"] > 0 else 0.0
    return width, net, hi, lo, (net / width if width > 0 else 0.0)


def adx_rise(rows_1h):
    """1h ADX 近 6 根的抬升幅度（逐段截断求末值序列，够看「刚起来」）。"""
    h = [r["h"] for r in rows_1h]
    l = [r["l"] for r in rows_1h]
    c = [r["c"] for r in rows_1h]
    out = []
    for i in range(max(40, len(c) - 30), len(c)):
        a = calc_adx(h[:i + 1], l[:i + 1], c[:i + 1])
        out.append(a if a is not None else 0.0)
    return (out[-1] - out[-7]) if len(out) >= 7 else 0.0


def main():
    age = since_last_minutes()
    if age is not None and age < MIN_INTERVAL_MIN and os.environ.get("FORCE") != "1":
        print(f"上次扫描在 {age:.0f} 分钟前（阈值 {MIN_INTERVAL_MIN} 分钟），本轮跳过"
              f"（需强制重扫请设 FORCE=1）")
        return
    r = requests.get(f"{OKX}/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=20)
    d = r.json()
    if d.get("code") != "0":
        raise SystemExit(f"tickers failed: {d.get('msg')}")
    items = [(t["instId"], float(t.get("volCcy24h", 0))) for t in d["data"]
             if "USDT" in t["instId"] and not any(x in t["instId"] for x in EXCL)]
    items.sort(key=lambda x: -x[1])
    syms = [i[0] for i in items[:SCAN_TOP]]
    print(f"扫描池：成交额前 {SCAN_TOP} → 实际 {len(syms)} 个", flush=True)

    coins = []
    skipped = 0
    for idx, s in enumerate(syms):
        name = s.replace("-USDT-SWAP", "")
        if is_stock_related(name):
            continue
        c1d = get_candles(s, "1D", BARS_1D)
        if not c1d or len(c1d) < 35:
            skipped += 1
            continue
        price = c1d[-1]["c"]
        hit, narrow = None, None
        for n in WINDOWS:
            if len(c1d) < n + 5:
                continue
            width, net, hi, lo, ratio = box_stats(c1d, n)
            cur = dict(n=n, width=width, net=net, ratio=ratio, hi=hi, lo=lo)
            if narrow is None or width < narrow["width"]:
                narrow = cur
            if (width <= BOX_MAX and ratio <= BOX_RATIO_MAX
                    and (hit is None or n > hit["n"])):
                hit = cur
        rec = {"name": name, "inst": s, "price": price, "hit": hit, "narrow": narrow}
        if hit or (narrow and narrow["width"] <= WATCH_MAX):
            coins.append(rec)
        if (idx + 1) % 100 == 0:
            print(f"  已扫 {idx + 1}/{len(syms)}（命中 {len([c for c in coins if c['hit']])}）", flush=True)
        time.sleep(0.03)

    print(f"日线扫描完成：取数失败 {skipped} 个，进入观察 {len(coins)} 个", flush=True)

    # 只给「命中」或「最窄 TOP_N」的币补 1h 数据（省一半请求）
    coins.sort(key=lambda c: (c["narrow"]["width"] if c["narrow"] else 999))
    need = [c for c in coins if c["hit"]] + coins[:TOP_N]
    seen, uniq = set(), []
    for c in need:
        if c["name"] not in seen:
            seen.add(c["name"]); uniq.append(c)
    print(f"补 1h 数据：{len(uniq)} 个", flush=True)

    for c in uniq:
        c1h = get_candles(c["inst"], "1H", BARS_1H)
        d1h, adx1h, rise = 0, 0.0, 0.0
        if c1h and len(c1h) >= 50:
            d1h = structure_dir([r["h"] for r in c1h], [r["l"] for r in c1h],
                                min_pct=MIN_SWING_PCT_1H)
            adx1h = calc_adx([r["h"] for r in c1h], [r["l"] for r in c1h],
                             [r["c"] for r in c1h]) or 0.0
            rise = adx_rise(c1h)
        started = (d1h != 0 and adx1h > 20 and rise > 5)
        box = c["hit"] or c["narrow"]
        pos = ((c["price"] - box["lo"]) / (box["hi"] - box["lo"]) * 100) if box["hi"] > box["lo"] else 50.0
        c.update({"d1h": d1h, "adx1h": round(adx1h, 1), "adx_rise": round(rise, 1),
                  "started": bool(started), "pos": round(pos, 1)})
        time.sleep(0.03)

    hits = [c for c in uniq if c["hit"]]
    for c in hits:
        print(f"  ★ {c['name']:10s} 横 {c['hit']['n']:2d} 日 宽 {c['hit']['width']:5.2f}% "
              f"比值 {c['hit']['ratio']:.2f} | 现价 {c['pos']:3.0f}% 位置 | "
              f"1h={'多' if c['d1h']==1 else '空' if c['d1h']==-1 else '横盘'} "
              f"ADX {c['adx1h']:.1f}（{c['adx_rise']:+.1f}）{' ★启动' if c['started'] else ''}",
              flush=True)

    # 各阈值下的合格币数：**口径必须与命中一致**（含比值门），否则数字会虚高
    counts = {}
    for t in (6.0, 7.0, 8.0, 10.0, 12.0):
        counts[str(t)] = sum(1 for c in uniq
                             if c["narrow"] and c["narrow"]["width"] <= t
                             and c["narrow"]["ratio"] <= BOX_RATIO_MAX)

    out = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST"),
        "scan_top": SCAN_TOP, "scanned": len(syms),
        "box_width_max": BOX_MAX, "box_ratio_max": BOX_RATIO_MAX,
        "min_days": min(WINDOWS),
        "counts": counts,
        "n_hit": len(hits),
        "n_started": sum(1 for c in hits if c["started"]),
        "hits": sorted([{k: v for k, v in c.items() if k != "narrow"} for c in hits],
                       key=lambda c: (not c["started"], c["hit"]["width"])),
        "watch": [{k: v for k, v in c.items() if k != "hit"}
                  for c in sorted(uniq, key=lambda c: c["narrow"]["width"])[:TOP_N]],
    }
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize(OUT) / 1024
    print(f"\nwrote {OUT}: {len(hits)} 命中（其中 1h 已启动 {out['n_started']} 个）"
          f"，各阈值 {counts}，{kb:.0f} KB", flush=True)


if __name__ == "__main__":
    main()
