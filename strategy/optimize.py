#!/usr/bin/env python3
"""
策略参数优化器
基于回测数据，分析不同参数组合对胜率的影响，输出最优配置建议
"""
import json, csv, os, sys
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)
from shared.indicators import DIR_SCORE

BT_FILE = os.path.join(PROJECT_ROOT, "okx_data", "backtest_results.csv")
SCAN_DIR = os.path.join(PROJECT_ROOT, "okx_data", "scans")

def load_backtest():
    """加载回测数据"""
    rows = []
    with open(BT_FILE, 'r') as f:
        for r in csv.DictReader(f):
            for k in ('srsi_1h','srsi_4h','srsi_1d','pct_4H','pct_12H','pct_24H'):
                try: r[k] = None if r.get(k,'') == '' else float(r.get(k,''))
                except: r[k] = None
            for k in ('score',):
                try: r[k] = int(r[k])
                except: pass
            for k in ('win_4H','win_12H','win_24H'):
                r[k] = True if r.get(k) == '1' else (False if r.get(k) == '0' else None)
            rows.append(r)
    return rows

def load_scan_data():
    """加载所有扫描CSV数据"""
    all_rows = []
    import glob
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "*.csv")))
    for fp in files:
        with open(fp, 'r') as f:
            for r in csv.DictReader(f):
                for k in ('adx_1h','adx_4h','adx_1d','srsi_1h','srsi_4h','srsi_1d','dmi_bull','dmi_bear','adx_bull','adx_bear','sw_bull','sw_bear'):
                    try: r[k] = None if r.get(k,'') == '' else (float(r.get(k,'')) if '.' in str(r.get(k,'')) else int(r.get(k,'')))
                    except: r[k] = None
                all_rows.append(r)
    return all_rows

# ── 评分函数（可调参数版） ──
def rescore(row, params):
    """
    用给定参数重新计算评分
    params: {alert_threshold, srsi_os, srsi_ob, dir_1h, dir_4h, dir_1d, use_adx}
    """
    directions = {
        "1H": row.get("dmi_1h", "N/A"),
        "4H": row.get("dmi_4h", "N/A"),
        "1D": row.get("dmi_1d", "N/A"),
    }
    srsis = {
        "1H": row.get("srsi_1h"), "4H": row.get("srsi_4h"), "1D": row.get("srsi_1d")
    }
    adxs = {
        "1H": row.get("adx_1h"), "4H": row.get("adx_4h"), "1D": row.get("adx_1d")
    }
    
    dir_w = {"1H": params["dir_1h"], "4H": params["dir_4h"], "1D": params["dir_1d"]}
    srsi_os = params["srsi_os"]
    srsi_ob = params["srsi_ob"]
    
    bull, bear = 0, 0
    for tf in ["1H", "4H", "1D"]:
        d = directions[tf]
        s = srsis[tf]
        w = dir_w[tf]
        if params.get("use_adx", False):
            adx = adxs[tf]
            aw = 0.5 if (adx is not None and adx < 20) else (0.75 if (adx is not None and adx < 25) else 1.0)
            w *= aw
        if d == "多": bull += w
        elif d == "空": bear += w
        if s is not None:
            if s < srsi_os: bull += 2 if tf == "1D" else dir_w[tf]
            if s > srsi_ob: bear += 2 if tf == "1D" else dir_w[tf]
    return round(bull, 1), round(bear, 1)

# ── 分析函数 ──
def analyze_threshold_sensitivity(data):
    """不同评分阈值下的胜率变化"""
    print("\n" + "="*70)
    print("📊 评分阈值敏感度分析")
    print("="*70)
    
    results = []
    for th in [5, 6, 7, 8, 9]:
        params = {"alert_threshold": th, "srsi_os": 20, "srsi_ob": 80,
                  "dir_1h": 1, "dir_4h": 1, "dir_1d": 2, "use_adx": False}
        signals = []
        for r in data:
            if r.get("win_24H") is None: continue
            bull, bear = rescore(r, params)
            score = bull if bull >= bear else bear
            if score >= th:
                signals.append(r["win_24H"])
        if signals:
            wr = sum(signals)/len(signals)*100
            results.append((th, len(signals), wr))
    
    print(f"{'阈值':<6} {'信号数':>6} {'胜率':>8}")
    print("-" * 24)
    for th, n, wr in results:
        bar = "█" * int(wr/5)
        print(f"≥{th:<5} {n:>6}  {wr:>6.1f}%  {bar}")
    
    best = max(results, key=lambda x: (x[2], -x[1]))
    print(f"\n💡 推荐阈值: ≥{best[0]} (胜率{best[2]:.1f}%, {best[1]}个信号)")

def analyze_srsi_boundaries(data):
    """不同SRSI极端值边界的胜率"""
    print("\n" + "="*70)
    print("📊 SRSI 极值边界敏感度")
    print("="*70)
    
    # Test SRSI oversold (bullish signal)
    print("\n─ SRSI 超卖边界 (做多信号) ─")
    print(f"{'条件':<18} {'信号数':>6} {'24H胜率':>9} {'平均收益%':>9}")
    print("-" * 46)
    
    base_params = {"alert_threshold": 6, "srsi_os": 20, "srsi_ob": 80,
                   "dir_1h": 1, "dir_4h": 1, "dir_1d": 2, "use_adx": False}
    
    for os_level in [15, 18, 20, 25, 30]:
        params = {**base_params, "srsi_os": os_level}
        bull_sigs = []
        for r in data:
            if r.get("win_24H") is None: continue
            if r.get("dmi_1d", "") == "N/A": continue
            bull, bear = rescore(r, params)
            if bull >= bear and bull >= 6:
                bull_sigs.append((r["win_24H"], r.get("pct_24H", 0) or 0))
        if bull_sigs:
            wr = sum(s[0] for s in bull_sigs)/len(bull_sigs)*100
            avg = sum(s[1] for s in bull_sigs)/len(bull_sigs)
            print(f"SRSI < {os_level:<3}         {len(bull_sigs):>6}  {wr:>7.1f}%  {avg:>8.2f}%")
    
    # Test SRSI overbought (bearish signal)
    print("\n─ SRSI 超买边界 (做空信号) ─")
    for ob_level in [70, 75, 80, 85, 90]:
        params = {**base_params, "srsi_ob": ob_level}
        bear_sigs = []
        for r in data:
            if r.get("win_24H") is None: continue
            bull, bear = rescore(r, params)
            if bear > bull and bear >= 6:
                bear_sigs.append((r["win_24H"], r.get("pct_24H", 0) or 0))
        if bear_sigs:
            wr = sum(s[0] for s in bear_sigs)/len(bear_sigs)*100
            avg = sum(s[1] for s in bear_sigs)/len(bear_sigs)
            print(f"SRSI > {ob_level:<3}         {len(bear_sigs):>6}  {wr:>7.1f}%  {avg:>8.2f}%")

def analyze_timeframe_weights(data):
    """不同时间周期权重对比"""
    print("\n" + "="*70)
    print("📊 时间周期权重敏感度")
    print("="*70)
    
    combos = [
        ("1:1:1", 1, 1, 1),
        ("1:1:2", 1, 1, 2, "← 当前"),
        ("1:1:3", 1, 1, 3),
        ("1:2:2", 1, 2, 2),
        ("0.5:1:2", 0.5, 1, 2),
        ("1:1.5:3", 1, 1.5, 3),
    ]
    
    base_params = {"alert_threshold": 6, "srsi_os": 20, "srsi_ob": 80, "use_adx": False}
    
    print(f"{'权重(1H:4H:1D)':<16} {'信号数':>6} {'24H胜率':>9} {'平均收益%':>9}")
    print("-" * 44)
    
    results = []
    for idx, (label, w1, w4, wd, *extra) in enumerate(combos):
        params = {**base_params, "dir_1h": w1, "dir_4h": w4, "dir_1d": wd}
        sigs = []
        for r in data:
            if r.get("win_24H") is None: continue
            bull, bear = rescore(r, params)
            score = bull if bull >= bear else bear
            if score >= 6:
                sigs.append((r["win_24H"], r.get("pct_24H", 0) or 0))
        if sigs:
            wr = sum(s[0] for s in sigs)/len(sigs)*100
            avg = sum(s[1] for s in sigs)/len(sigs)
            note = " " + extra[0] if extra else ""
            print(f"{label:<16} {len(sigs):>6}  {wr:>7.1f}%  {avg:>8.2f}%{note}")
            results.append((label, len(sigs), wr, avg))

def analyze_adx_impact(data):
    """ADX权重过滤的影响"""
    print("\n" + "="*70)
    print("📊 ADX 趋势强度过滤效果")
    print("="*70)
    
    base_params = {"alert_threshold": 6, "srsi_os": 20, "srsi_ob": 80,
                   "dir_1h": 1, "dir_4h": 1, "dir_1d": 2}
    
    print(f"{'模式':<18} {'信号数':>6} {'24H胜率':>9} {'平均收益%':>9}")
    print("-" * 46)
    
    for label, use_adx in [("无ADX过滤", False), ("ADX加权", True)]:
        params = {**base_params, "use_adx": use_adx}
        sigs = []
        for r in data:
            if r.get("win_24H") is None: continue
            bull, bear = rescore(r, params)
            score = bull if bull >= bear else bear
            if score >= 6:
                sigs.append((r["win_24H"], r.get("pct_24H", 0) or 0))
        if sigs:
            wr = sum(s[0] for s in sigs)/len(sigs)*100
            avg = sum(s[1] for s in sigs)/len(sigs)
            print(f"{label:<18} {len(sigs):>6}  {wr:>7.1f}%  {avg:>8.2f}%")

def analyze_symbol_winrates(data):
    """各品种在不同标准下的表现"""
    print("\n" + "="*70)
    print("📊 品种 × 标准 交叉分析 (24H胜率)")
    print("="*70)
    
    stds = ["DMI纯分", "ADX加权", "摆动点"]
    symbols = sorted(set(r["symbol"] for r in data))
    
    print(f"{'品种':<10}", end="")
    for s in stds: print(f" {s:>8}", end="")
    print(f" {'综合':>8}")
    print("-" * 48)
    
    for sym in symbols:
        name = sym.replace("-SWAP","").replace("-USDT","")
        print(f"{name:<10}", end="")
        sym_results = []
        for std in stds:
            sigs = [r for r in data if r["symbol"] == sym and r["std"] == std and r.get("win_24H") is not None]
            if sigs:
                wr = sum(s["win_24H"] for s in sigs)/len(sigs)*100
                sym_results.append(wr)
                print(f" {wr:>7.1f}%", end="")
            else:
                print(f" {'-':>7}", end="")
        # Average
        if sym_results:
            avg = sum(sym_results)/len(sym_results)
            print(f" {avg:>7.1f}%", end="")
        print()

def generate_recommendations(data):
    """综合建议"""
    print("\n" + "="*70)
    print("🎯 策略优化建议")
    print("="*70)
    
    recommendations = []
    
    # 1. Score threshold
    best_th = (6, 0)
    for th in [5,6,7,8]:
        params = {"alert_threshold": th, "srsi_os": 20, "srsi_ob": 80,
                  "dir_1h": 1, "dir_4h": 1, "dir_1d": 2, "use_adx": False}
        wins = []
        for r in data:
            if r.get("win_24H") is None: continue
            bull, bear = rescore(r, params)
            score = bull if bull >= bear else bear
            if score >= th: wins.append(r["win_24H"])
        if wins and sum(wins)/len(wins) > best_th[1]:
            best_th = (th, sum(wins)/len(wins), len(wins))
    
    recommendations.append(f"1. 评分阈值: 保持 ≥{best_th[0]} (胜率{best_th[1]*100:.1f}%, {best_th[2]}信号)")
    
    # 2. Check 1D SRSI > 80 pattern
    dmi_data = [r for r in data if r["std"] == "DMI纯分" and r.get("win_24H") is not None]
    srsi80 = [r for r in dmi_data if r.get("srsi_1d") and r["srsi_1d"] > 80]
    if srsi80:
        wr80 = sum(r["win_24H"] for r in srsi80)/len(srsi80)*100
        recommendations.append(f"2. 1D SRSI>80 (做空): 胜率{wr80:.0f}% — {'✅ 强烈推荐' if wr80>70 else '⚠️ 谨慎使用'}")
    
    srsi15 = [r for r in dmi_data if r.get("srsi_4h") and r["srsi_4h"] < 15]
    if srsi15:
        wr15 = sum(r["win_24H"] for r in srsi15)/len(srsi15)*100
        recommendations.append(f"3. 4H SRSI<15 (做多): 胜率{wr15:.0f}% — {'✅ 推荐' if wr15>50 else '⚠️ 谨慎'}")
    
    # 3. Best symbol
    sym_wr = defaultdict(list)
    for r in dmi_data:
        sym_wr[r["symbol"]].append(r["win_24H"])
    sym_avg = [(sym, sum(w)/len(w)*100, len(w)) for sym, w in sym_wr.items() if len(w)>=5]
    sym_avg.sort(key=lambda x: x[1], reverse=True)
    if sym_avg:
        top = sym_avg[:3]
        rec = "4. 最佳品种: " + ", ".join(f"{s[0].replace('-SWAP','').replace('-USDT','')}({s[1]:.0f}%/{s[2]}信号)" for s in top)
        recommendations.append(rec)
    
    # 4. ADX filter recommendation
    with_adx = []
    without_adx = []
    for r in data:
        if r.get("win_24H") is None: continue
        bull_n, bear_n = rescore(r, {"alert_threshold": 6, "srsi_os": 20, "srsi_ob": 80,
                                      "dir_1h": 1, "dir_4h": 1, "dir_1d": 2, "use_adx": False})
        bull_a, bear_a = rescore(r, {"alert_threshold": 6, "srsi_os": 20, "srsi_ob": 80,
                                      "dir_1h": 1, "dir_4h": 1, "dir_1d": 2, "use_adx": True})
        sn = bull_n if bull_n >= bear_n else bear_n
        sa = bull_a if bull_a >= bear_a else bear_a
        if sn >= 6: without_adx.append(r["win_24H"])
        if sa >= 6: with_adx.append(r["win_24H"])
    
    if with_adx and without_adx:
        wr_with = sum(with_adx)/len(with_adx)*100
        wr_without = sum(without_adx)/len(without_adx)*100
        if wr_with > wr_without + 5:
            recommendations.append(f"5. ADX过滤: 开启 ✅ (胜率+{wr_with-wr_without:.1f}%, 信号{len(with_adx)}vs{len(without_adx)})")
        else:
            recommendations.append(f"5. ADX过滤: 不推荐 ❌ (胜率差异<5%)")
    
    for r in recommendations:
        print(f"  {r}")
    
    print(f"\n📋 推荐配置: 阈值≥{best_th[0]}, SRSI<20做多/SRSI>80做空, 方向权重1:1:2, 无ADX过滤")

# ── 主函数 ──
def main():
    print("="*70)
    print("🔬 OKX 策略参数优化器")
    print("="*70)
    
    if not os.path.exists(BT_FILE):
        print(f"\n⚠️ 回测数据不存在: {BT_FILE}")
        print("请先运行: python analysis/backtest.py")
        return
    
    print(f"\n加载回测数据...")
    data = load_backtest()
    print(f"  {len(data)} 个信号, {len(set(r['symbol'] for r in data))} 个品种")
    
    analyze_threshold_sensitivity(data)
    analyze_srsi_boundaries(data)
    analyze_adx_impact(data)
    analyze_symbol_winrates(data)
    generate_recommendations(data)

if __name__ == "__main__":
    main()
