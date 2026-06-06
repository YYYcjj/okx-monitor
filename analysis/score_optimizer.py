#!/usr/bin/env python3
"""评分赋分优化：网格搜索不同权重配置对胜率的影响"""
import csv, json, os, sys
from itertools import product

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BT_FILE = os.path.join(PROJECT_ROOT, "okx_data", "backtest_results.csv")
OUTPUT = os.path.join(PROJECT_ROOT, "okx_data", "score_optimization.json")

# 方向分权重组合
WEIGHT_CONFIGS = [
    {"id": "1-1-2", "weights": {"1H": 1, "4H": 1, "1D": 2}, "label": "原版 1-1-2"},
    {"id": "1-2-3", "weights": {"1H": 1, "4H": 2, "1D": 3}, "label": "当前 1-2-3"},
    {"id": "1-2-4", "weights": {"1H": 1, "4H": 2, "1D": 4}, "label": "激进 1-2-4"},
    {"id": "1-1-3", "weights": {"1H": 1, "4H": 1, "1D": 3}, "label": "偏日线 1-1-3"},
    {"id": "2-3-5", "weights": {"1H": 2, "4H": 3, "1D": 5}, "label": "重仓 2-3-5"},
]

# 预警阈值
THRESHOLDS = [6, 8, 10, 12, 14]

# SRSI 柔和加分（1D 专属）
MILD_BONUSES = [1, 2, 3]

def load_backtest():
    rows = []
    with open(BT_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = {}
            r["symbol"] = row["symbol"]
            r["std"] = row["std"]
            r["direction"] = row["direction"]
            r["score"] = int(row["score"]) if row.get("score") else 0
            # DMI
            r["dmi"] = {k: row.get(f"dmi_{k}", "N/A") for k in ["1h", "4h", "1d"]}
            # SW
            r["sw"] = {k: row.get(f"sw_{k}", "N/A") for k in ["1h", "4h", "1d"]}
            # SRSI
            r["srsi"] = {}
            for k in ["1h", "4h", "1d"]:
                try:
                    r["srsi"][k] = float(row.get(f"srsi_{k}", "")) if row.get(f"srsi_{k}", "") else None
                except:
                    r["srsi"][k] = None
            # Win rates
            for tf in ["4H", "12H", "24H"]:
                r[f"win_{tf}"] = row.get(f"win_{tf}", "") == "1"
                try:
                    r[f"pct_{tf}"] = float(row.get(f"pct_{tf}", 0))
                except:
                    r[f"pct_{tf}"] = 0.0
            rows.append(r)
    return rows

def calc_score(trends, srsis, weights, mild_bonus=2):
    """用给定权重计算多空评分"""
    bull, bear = 0, 0
    for tf in ["1h", "4h", "1d"]:
        d = trends.get(tf, "N/A")
        s = srsis.get(tf)
        w = weights[tf.upper()]
        if d == "多":
            bull += w
        elif d == "空":
            bear += w
        if s is not None:
            if s < 20:
                bull += w
            elif s < 30 and tf == "1d":
                bull += mild_bonus
            if s > 80:
                bear += w
            elif s > 70 and tf == "1d":
                bear += mild_bonus
    return bull, bear

def test_config(rows, weights, threshold, mild_bonus, trend_key="dmi"):
    """测试一个配置组合的胜率"""
    signals = []
    for r in rows:
        trends = r[trend_key]
        # 1D 方向用摆动点（和当前策略一致）
        if trend_key == "dmi":
            trends = dict(r["dmi"])
            if r["sw"]["1d"] != "N/A":
                trends["1d"] = r["sw"]["1d"]
        bull, bear = calc_score(trends, r["srsi"], weights, mild_bonus)
        if bull >= threshold or bear >= threshold:
            signals.append({
                "bull": bull, "bear": bear,
                "win_4H": r["win_4H"], "win_12H": r["win_12H"], "win_24H": r["win_24H"],
                "pct_4H": r["pct_4H"], "pct_12H": r["pct_12H"], "pct_24H": r["pct_24H"],
            })

    total = len(signals)
    if total < 5:
        return None

    # 分多空统计
    longs = [s for s in signals if s["bull"] >= threshold]
    shorts = [s for s in signals if s["bear"] >= threshold]

    def win_rate(lst, tf):
        wins = [s for s in lst if s[f"win_{tf}"]]
        return round(len(wins) / len(lst) * 100, 1) if lst else 0

    def avg_pct(lst, tf):
        return round(sum(s[f"pct_{tf}"] for s in lst) / len(lst) * 100, 2) if lst else 0

    return {
        "total": total,
        "long_count": len(longs),
        "short_count": len(shorts),
        "wr_4H": win_rate(signals, "4H"),
        "wr_12H": win_rate(signals, "12H"),
        "wr_24H": win_rate(signals, "24H"),
        "avg_4H": avg_pct(signals, "4H"),
        "avg_12H": avg_pct(signals, "12H"),
        "avg_24H": avg_pct(signals, "24H"),
        "long_wr_24H": win_rate(longs, "24H"),
        "short_wr_24H": win_rate(shorts, "24H"),
    }

def main():
    print("📊 加载回测数据...")
    rows = load_backtest()
    print(f"   共 {len(rows)} 条回测记录\n")

    results = []
    total_combos = len(WEIGHT_CONFIGS) * len(THRESHOLDS) * len(MILD_BONUSES)
    i = 0
    for wc in WEIGHT_CONFIGS:
        for mild in MILD_BONUSES:
            for thr in THRESHOLDS:
                i += 1
                result = test_config(rows, wc["weights"], thr, mild)
                if result:
                    result["config_id"] = wc["id"]
                    result["config_label"] = wc["label"]
                    result["weights"] = f"{wc['weights']['1H']}-{wc['weights']['4H']}-{wc['weights']['1D']}"
                    result["threshold"] = thr
                    result["mild_bonus"] = mild
                    results.append(result)
                pct = i / total_combos * 100
                if i % 10 == 0:
                    print(f"\r  进度: {i}/{total_combos} ({pct:.0f}%)", end="", flush=True)

    print(f"\n\n   有效配置: {len(results)}")

    # 按 24H 胜率排序
    results.sort(key=lambda x: (x["wr_24H"] * x["total"] / (x["total"] + 20), x["wr_24H"]), reverse=True)

    # 输出 Top 20
    print(f"\n🏆 Top 20 配置 (综合24H胜率+信号量):")
    print(f"{'权重':>8} | {'阈值':>4} | {'柔和':>4} | {'信号':>5} | {'24H胜率':>8} | {'12H胜率':>8} | {'多24H':>7} | {'空24H':>7} | {'均24H':>7}")
    print("-" * 85)
    for r in results[:20]:
        print(f"{r['weights']:>8} | {r['threshold']:>4} | {r['mild_bonus']:>4} | {r['total']:>5} | {r['wr_24H']:>6}% | {r['wr_12H']:>6}% | {r['long_wr_24H']:>5}% | {r['short_wr_24H']:>5}% | {r['avg_24H']:>+6.2f}%")

    # 按权重分组统计最佳阈值
    print(f"\n📊 各权重配置最佳参数:")
    for wc in WEIGHT_CONFIGS:
        subset = [r for r in results if r["config_id"] == wc["id"]]
        if not subset:
            continue
        best = max(subset, key=lambda x: x["wr_24H"] * x["total"] / (x["total"] + 20))
        print(f"  {wc['label']:>10}: 阈值={best['threshold']} 柔和={best['mild_bonus']} → {best['total']}信号 24H胜率={best['wr_24H']}%")


    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump({
            "all": results,
            "top_20": results[:20],
            "configs": WEIGHT_CONFIGS,
            "thresholds": THRESHOLDS,
            "total_signals": len(rows),
        }, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存: {OUTPUT}")

if __name__ == "__main__":
    main()
