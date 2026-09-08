#!/usr/bin/env python3
"""一次性分析：9/5 推送的 12 个信号，其触发 swing 关键位被历史触及过几次。
用于判断：算法 swing 点里有多少是「多次验证的硬位」vs「单次偶然点」。
口径说明：
  关键位 = 触发日(2025-09-05)前最后两个 swing low(做多) / swing high(做空)，同 TrendWatch 逻辑(SWING_P=5)。
  触及   = 某日 K 线区间与 [p*0.995, p*1.005] 相交算一次接触；连续接触合并为 1 次事件，
           需价格明显离开(>2%远离)后再返回才算下一次。仅统计最近一个月（2025-08-01 起），到触发日前一天止。
输出：keylevel_report.md（自动 commit）。
"""
import requests, time, os, json
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"
S = 5
END = int(datetime(2025, 9, 5, tzinfo=timezone.utc).timestamp() * 1000) + 86400000  # 9/5 收盘后
BEGIN = int(datetime(2025, 8, 1, tzinfo=timezone.utc).timestamp() * 1000)          # 统计最近一个月（用户指定）

# 9/5 推送记录：币 -> 方向
SYMS = {
    "ALGO": "多", "CFX": "多", "ICX": "空", "LAB": "空", "NEIRO": "多", "OL": "多",
    "PEOPLE": "多", "PIPPIN": "多", "SHIB": "多", "STRK": "多", "SUI": "多", "ZAMA": "多",
}

def _fetch(params):
    for _ in range(4):
        try:
            r = requests.get(f"{OKX}/api/v5/market/history-candles", params=params, timeout=15)
            return r.json()
        except Exception:
            time.sleep(1.0)
    return {"code": "net_err", "msg": "network retry exhausted"}

def get_daily(inst):
    candles = []
    after = END
    while True:
        d = _fetch({"instId": inst, "bar": "1D", "after": str(after), "limit": "100"})
        if d.get("code") != "0" or not d.get("data"):
            break
        for c in d["data"]:
            ts = int(c[0])
            if ts < BEGIN:
                if not candles:
                    return None, None
                break  # 已越过起始时间，停止翻页
            candles.append({"ts": ts, "h": float(c[2]), "l": float(c[3]),
                            "c": float(c[4]), "o": float(c[1])})
        else:
            after = candles[-1]["ts"] if candles else after - 86400000
            if len(d["data"]) < 100:
                break
            time.sleep(0.1)
            continue
        break
    candles.reverse()
    return [c["h"] for c in candles], candles  # 返回 (highs, full list)

def find_swings(highs, lows):
    n = len(highs)
    sh, sl = [], []
    for i in range(S, n - S):
        if highs[i] >= max(highs[i - S:i]) and highs[i] >= max(highs[i + 1:i + S + 1]):
            sh.append((i, highs[i]))
        if lows[i] <= min(lows[i - S:i]) and lows[i] <= min(lows[i + 1:i + S + 1]):
            sl.append((i, lows[i]))
    return sh, sl

def touch_events(candles, p):
    """统计价格 p 的历史触及事件次数（截至 9/4，排除 9/5 当天自身）。"""
    ev = 0
    inside = False
    for c in candles[:-1]:
        touch = c["low"] <= p * 1.005 and c["high"] >= p * 0.995
        if touch and not inside:
            inside = True
            ev += 1
        elif inside and not touch:
            if c["low"] > p * 1.02 or c["high"] < p * 0.98:  # 明显离开才算事件结束
                inside = False
    return ev

def main():
    out = ["# 9/5 推送信号的 swing 关键位触及统计（最近一个月）", "",
           f"口径：关键位=触发前最后两个 swing(窗口{S})；触及=价格进入 ±0.5% 区间(离开>2% 算一次)，统计窗口 2025-08-01 ~ 09-04。",
           "", "| 币 | 方向 | 最近swing#1 价位 | 触及次数 | 最近swing#2 价位 | 触及次数 |",
           "|---|---|---|---|---|---|---|"]
    hard, soft = 0, 0
    detail = []
    for name, dr in SYMS.items():
        try:
            inst = f"{name}-USDT-SWAP"
            highs, candles = get_daily(inst)
            if not candles:
                out.append(f"| {name} | {dr} | 拉取失败 | - | - | - |")
                continue
            lows = [c["l"] for c in candles]
            # 只在截至 9/5 前已能确认的 K 线上找 swing（右侧需 S 根确认窗口，且不含 9/5 当日）
            conf = max(0, len(candles) - 1 - S)
            sh, sl = find_swings(highs[:conf], lows[:conf])
            if dr == "多" and len(sl) >= 2:
                lv = [sl[-2], sl[-1]]
            elif dr == "空" and len(sh) >= 2:
                lv = [sh[-2], sh[-1]]
            else:
                out.append(f"| {name} | {dr} | swing 不足 | - | - | - |")
                continue
            p1, p2 = lv[-2][1], lv[-1][1]
            t1, t2 = touch_events(candles, p1), touch_events(candles, p2)
            out.append(f"| {name} | {dr} | {p1:.6g} | {t1} | {p2:.6g} | {t2} |")
            detail.append((name, dr, p1, t1, p2, t2))
            hard += (1 if t1 >= 2 else 0) + (1 if t2 >= 2 else 0)
            soft += (1 if t1 == 1 else 0) + (1 if t2 == 1 else 0)
        except Exception as e:
            import traceback
            out.append(f"| {name} | {dr} | 异常: {e} | - | - | - |")
            print(f"ERR {name}: {traceback.format_exc()}")
            continue
    total = hard + soft
    out.append("")
    out.append(f"**总计 {total} 个候选关键位：多次验证(≥2次触及) {hard} 个 ({hard/max(total,1)*100:.0f}%)；单次偶然点(仅1次) {soft} 个。**")
    out.append("")
    out.append("> 注：最近 swing#2 是代码实际贴靠判定的主要对象（classify 取 sl1d[-1] 为主贴靠位/目标展示），两个都列出便于对比。")
    md = "\n".join(out)
    with open("keylevel_report.md", "w") as f:
        f.write(md + "\n")
    print(md)
    print("\nDONE")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("FATAL:", tb)
        with open("keylevel_report.md", "w") as f:
            f.write("# 分析失败\n\n```\n" + tb + "\n```\n")
        raise
