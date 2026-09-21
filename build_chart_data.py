#!/usr/bin/env python3
"""
TrendWatch 走势图数据生成（2026-09-20 重写）

用途：为 gh-pages 上的走势图页面（charts.html）生成 charts_data.json。
要点：
  1. 指标一律复用 tw_calc / tw_conf（与推送口径同源，避免两套逻辑分叉）。
  2. 判定口径 = 当前生效的 **V2**：ADX(1h)>20 → ATR/价 0.5-2% → 1d 结构定方向
     → 贴日线关键位 ±1.5% → SRSI 同向极端 → 目标空间 >10%；1h/4h 结构仅展示。
  3. 页面**不发任何外部请求**：K 线、SRSI、当日已推送列表全部内嵌，
     所以手机/受限网络下也能打开（这是它和浏览器直连版的根本区别）。
  4. 输出做数值压缩（5 位有效数字 + 精简分隔符），100 币约 1.5-2 MB。

每个币输出：
  - 1D / 4H / 1H K 线（最近 90 根，升序，[ts_sec, o, h, l, c]）
  - SRSI 1d / 1h 序列（需右对齐到对应 K 线末端）
  - ADX(1h)、ATR/价、四周期结构方向（1d/4h/1h/15m）
  - 日线 swing 高/低点（价位 + 时间）
  - 六道门的逐门通过情况 + 信号类型/方向/目标位/空间

币种范围：固定监控 7 币 + 当日已推送 + 成交额前 100（去重，固定币在前）。
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta

import requests

from tw_conf import (OKX, SWING_P, ADX_THRESHOLD, ATR_MIN_RATIO, ATR_MAX_RATIO,
                     SRSI_LOW, SRSI_HIGH, NEAR_LEVEL_PCT, MIN_SPACE_PCT,
                     MIN_SWING_PCT_1H, MIN_SWING_PCT_1D, MIN_SWING_PCT_4H,
                     MIN_SWING_PCT_15M, STATE_FILE)
from tw_calc import (calc_stoch_rsi_series, srsi_last, calc_atr, calc_adx,
                     structure_dir, find_swings, near_key_level)

# 注：4h 结构摆幅阈值 MIN_SWING_PCT_4H 原为**本文件局部定义**（当时 4h 不参与判定）；
# 2026-09-21 「4H 型」信号启用后已回归 tw_conf.py，这里改为导入，避免两份定义分叉。


FIXED = ["ORDI", "PUMP", "HUMA", "WLD", "APR", "BTC", "APT"]   # 固定监控币
SCAN_TOP = 100          # 成交额前 N
BARS = 90               # 每个周期取多少根（够指标预热 + 看图）
EXCL = ("BRL", "EUR", "TRY", "DAI", "USDC", "RUB")
LIM = {"1D": BARS, "4H": BARS, "1H": BARS, "15m": BARS}


def r5(x):
    """5 位有效数字，压缩 JSON 体积（价格精度足够看图与算指标）。

    注意：OKX 接口返回的 OHLC 是**字符串**，必须先 float() 再格式化，
    否则 f"{'123.4':.5g}" 会抛异常 → 被 fetch 的 except 吞掉 → 整轮空跑。
    （2026-09-20 实战踩坑：100 币每币重试 4 次 ×0.5s，正好把 15 分钟作业撑爆）
    """
    if x is None:
        return None
    return float(f"{float(x):.5g}")


def fetch(inst, bar, limit=LIM["1D"]):
    """取 K 线，返回 [[ts_sec, o, h, l, c], ...] 升序；失败返回 None。"""
    for _ in range(4):
        try:
            r = requests.get(f"{OKX}/api/v5/market/candles",
                             params={"instId": inst, "bar": bar, "limit": limit}, timeout=12)
            if r.status_code == 429:
                time.sleep(2.0)
                continue
            d = r.json()
            if d.get("code") == "0":
                rows = [[int(c[0]) // 1000, r5(c[1]), r5(c[2]), r5(c[3]), r5(c[4])]
                        for c in d["data"]]
                rows.reverse()
                return rows
        except Exception as e:
            # 打出异常：否则字段/类型问题会被静默重试吞掉（2026-09-20 空跑 15 分钟就是栽在这）
            print(f"    fetch {inst} {bar} 第{_ + 1}次失败: {type(e).__name__}: {e}", flush=True)
            time.sleep(0.5)
        time.sleep(0.06)
    return None


def today_pushed():
    """当日已推送的信号键（形如 SPACE|趋势多），用于页面标注与排序。"""
    try:
        if os.path.exists(STATE_FILE):
            st = json.load(open(STATE_FILE))
            today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            return sorted(st.get(today, []))
    except Exception as e:
        print("read pushed_state failed:", e)
    return []


def pick_coins():
    """固定监控 + 当日已推送 + 成交额前 SCAN_TOP（去重，固定币在前）。"""
    names, order = set(FIXED), list(FIXED)

    for key in today_pushed():
        nm = key.split("|")[0]
        if nm and nm not in names:
            names.add(nm); order.append(nm)

    try:
        r = requests.get(f"{OKX}/api/v5/market/tickers",
                         params={"instType": "SWAP"}, timeout=15)
        items = [(t["instId"], float(t.get("volCcy24h", 0))) for t in r.json()["data"]
                 if "USDT" in t["instId"] and not any(x in t["instId"] for x in EXCL)]
        items.sort(key=lambda x: -x[1])
        for inst, _ in items[:SCAN_TOP]:
            nm = inst.replace("-USDT-SWAP", "")
            if nm not in names:
                names.add(nm); order.append(nm)
    except Exception as e:
        print("tickers failed:", e)

    return order


def build_coin(name):
    inst = f"{name}-USDT-SWAP"
    d1 = fetch(inst, "1D")
    h4 = fetch(inst, "4H")
    h1 = fetch(inst, "1H")
    m15 = fetch(inst, "15m")
    if not d1 or not h1:
        return None

    closes1 = [c[4] for c in d1]
    closes1h = [c[4] for c in h1]
    highs1h = [c[2] for c in h1]; lows1h = [c[3] for c in h1]
    highs4h = [c[2] for c in (h4 or [])]; lows4h = [c[3] for c in (h4 or [])]
    highs1d = [c[2] for c in d1]; lows1d = [c[3] for c in d1]

    kv1 = calc_stoch_rsi_series(closes1)
    kv1h = calc_stoch_rsi_series(closes1h)
    atr1h = calc_atr(highs1h, lows1h, closes1h)
    adx1h = calc_adx(highs1h, lows1h, closes1h)
    if not kv1 or not kv1h or atr1h is None or adx1h is None:
        return None

    s1, s1h = srsi_last(kv1), srsi_last(kv1h)
    atr_ratio = atr1h / closes1h[-1] if closes1h[-1] > 0 else 0.0
    d1h = structure_dir(highs1h, lows1h, min_pct=MIN_SWING_PCT_1H)
    d4h = (structure_dir(highs4h, lows4h, min_pct=MIN_SWING_PCT_4H) if h4 else 0)
    d1d = structure_dir(highs1d, lows1d, min_pct=MIN_SWING_PCT_1D)
    d15m = (structure_dir([c[2] for c in m15], [c[3] for c in m15], min_pct=MIN_SWING_PCT_15M)
            if m15 else 0)
    sh1d, sl1d = find_swings(highs1d, lows1d, p=SWING_P)
    price = closes1[-1]

    # ---- 逐门判定（与 tw_calc.classify 的 V2 口径完全一致，仅拆开展示）----
    adx_ok = adx1h >= ADX_THRESHOLD
    atr_ok = ATR_MIN_RATIO < atr_ratio < ATR_MAX_RATIO
    dir1d_ok = d1d != 0
    if dir1d_ok:
        levels = [p for _, p in (sl1d[-2:] if d1d == 1 else sh1d[-2:])]
        level_ok = near_key_level(price, levels)
    else:
        level_ok = False
    if dir1d_ok and d1d == 1:
        srsi_ok = (s1 <= SRSI_HIGH and s1h <= SRSI_HIGH) and (s1 < SRSI_LOW or s1h < SRSI_LOW)
        kind = "回调" if s1 < SRSI_LOW else ("趋势" if s1h < SRSI_LOW else None)
    elif dir1d_ok:
        srsi_ok = (s1 >= SRSI_LOW and s1h >= SRSI_LOW) and (s1 > SRSI_HIGH or s1h > SRSI_HIGH)
        kind = "回调" if s1 > SRSI_HIGH else ("趋势" if s1h > SRSI_HIGH else None)
    else:
        srsi_ok, kind = False, None

    target = None
    if dir1d_ok:
        target = (sh1d[-1][1] if (d1d == 1 and sh1d)
                  else (sl1d[-1][1] if (d1d == -1 and sl1d) else None))
    space_pct = None
    if target and price > 0:
        sp = (target - price) / price if d1d == 1 else (price - target) / price
        space_pct = sp * 100.0
    space_ok = space_pct is not None and space_pct > MIN_SPACE_PCT

    dir_cn = {1: "多", -1: "空"}.get(d1d)
    signal = bool(adx_ok and atr_ok and dir1d_ok and level_ok and srsi_ok and space_ok and kind)

    # SRSI 序列右对齐到对应 K 线末端（长度短于 K 线，页面按下标偏移对齐）
    return {
        "name": name, "inst": inst, "price": r5(price),
        "d1": d1, "h4": h4 or [], "h1": h1,
        "srsi1d": [round(v, 1) for v in kv1[-BARS:]],
        "srsi1h": [round(v, 1) for v in kv1h[-BARS:]],
        "adx1h": round(adx1h, 1), "atr_pct": round(atr_ratio * 100, 2),
        "s1": round(s1, 1), "s1h": round(s1h, 1),
        "d1d": d1d, "d4h": d4h, "d1h": d1h, "d15m": d15m,
        "sh1d": [[d1[i][0], r5(p)] for i, p in sh1d[-4:]],
        "sl1d": [[d1[i][0], r5(p)] for i, p in sl1d[-4:]],
        "target": r5(target) if target else None,
        "space_pct": None if space_pct is None else round(space_pct, 1),
        "signal": signal, "kind": kind, "dir": dir_cn,
        "gates": {"adx": adx_ok, "atr": atr_ok, "dir1d": dir1d_ok,
                  "level": level_ok, "srsi": srsi_ok, "space": space_ok},
    }


def main():
    pushed = today_pushed()
    names = pick_coins()
    print(f"coins: {len(names)}  ({', '.join(names[:12])} ...)", flush=True)
    print(f"pushed today: {pushed}", flush=True)

    coins = []
    fails = 0
    for i, nm in enumerate(names):
        c = build_coin(nm)
        if c:
            coins.append(c)
            print(f"  {nm}: SRSI {c['s1']}/{c['s1h']} ADX {c['adx1h']} ATR {c['atr_pct']}% "
                  f"结构 {c['d1d']}/{c['d4h']}/{c['d1h']} 空间 {c['space_pct']} "
                  f"信号 {'★' if c['signal'] else '-'}", flush=True)
        else:
            fails += 1
            print(f"  {nm}: 数据不足，跳过", flush=True)
            # 快速失败：前 5 个全部取数失败，基本是接口/字段异常，别空跑到超时
            if fails == i + 1 and fails >= 5:
                raise SystemExit("前 5 个币全部取数失败，疑似接口或字段异常，提前终止")
        time.sleep(0.05)

    # 排序：信号优先 → 固定监控 → 有方向 → 空间大者在前
    def key(c):
        return (0 if c["signal"] else 1,
                0 if c["name"] in FIXED else 1,
                0 if c["d1d"] != 0 else 1,
                -(c["space_pct"] if c["space_pct"] is not None else -999))
    coins.sort(key=key)

    out = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST"),
        "pushed_today": pushed,
        "fixed": FIXED,
        "params": {"ADX": ADX_THRESHOLD,
                   "ATR": [ATR_MIN_RATIO * 100, ATR_MAX_RATIO * 100],
                   "SRSI": [SRSI_LOW, SRSI_HIGH],
                   "LEVEL_PCT": round(NEAR_LEVEL_PCT * 100, 1),
                   "SPACE_MIN": MIN_SPACE_PCT},
        "coins": coins,
    }
    with open("charts_data.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    kb = os.path.getsize("charts_data.json") / 1024
    sigs = sum(1 for c in coins if c["signal"])
    print(f"\nwrote charts_data.json: {len(coins)} coins, {kb:.0f} KB, 命中 {sigs} 个")
    if kb > 8192:
        raise SystemExit("charts_data.json 超过 8 MB，需下调 BARS 或 SCAN_TOP")


if __name__ == "__main__":
    main()
