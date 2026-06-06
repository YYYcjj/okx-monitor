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
    numeric_fields = ('srsi_1h','srsi_4h','srsi_1d','pct_4H','pct_12H','pct_24H',
                      'adx_1h','adx_4h','adx_1d','macd_1h','macd_4h','macd_1d',
                      'bbp_1h','bbp_4h','bbp_1d','cci_1h','cci_4h','cci_1d')
    int_fields = ('score',)
    bool_fields = ('win_4H','win_12H','win_24H')
    with open(BT_FILE, 'r') as f:
        for r in csv.DictReader(f):
            for k in numeric_fields:
                try: r[k] = None if r.get(k,'') == '' else float(r.get(k,''))
                except: r[k] = None
            for k in int_fields:
                try: r[k] = int(r[k])
                except: pass
            for k in bool_fields:
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

# ── 信号组合测试 ──

def test_signal_combinations(data):
    """对比不同信号组合的胜率"""
    print("\n" + "="*70)
    print("🔀 不同信号组合对比分析 (24H)")
    print("="*70)
    
    def eval_combo(name, rule_fn, only_bull=False, only_bear=False):
        """评估一个信号规则"""
        wins, pcts = [], []
        for r in data:
            if r.get("win_24H") is None: continue
            direction, triggered = rule_fn(r)
            if not triggered: continue
            if direction == "多" and only_bear: continue
            if direction == "空" and only_bull: continue
            wins.append(r["win_24H"])
            pcts.append(r.get("pct_24H", 0) or 0)
        if not wins: return (name, 0, 0, 0)
        wr = sum(wins)/len(wins)*100
        avg = sum(pcts)/len(pcts)
        return (name, len(wins), wr, avg)
    
    combos = []
    
    # 1. DMI only (纯方向分，无SRSI)
    def dmi_only(r):
        d = {t: r.get(f"dmi_{t.lower()}", "N/A") for t in ["1H","4H","1D"]}
        dirs = list(d.values())
        bull_count = dirs.count("多")
        bear_count = dirs.count("空")
        if bull_count >= 2:
            score = sum(1 if d[t]=="多" else 0 for t in ["1H","4H"]) + (2 if d["1D"]=="多" else 0)
            return ("多", score >= 4)
        if bear_count >= 2:
            score = sum(1 if d[t]=="空" else 0 for t in ["1H","4H"]) + (2 if d["1D"]=="空" else 0)
            return ("空", score >= 4)
        return ("N/A", False)
    combos.append(eval_combo("DMI纯方向 (≥2TF一致)", dmi_only))
    
    # 2. SRSI only (只看极端值)
    def srsi_only(r):
        s1h = r.get("srsi_1h"); s4h = r.get("srsi_4h"); s1d = r.get("srsi_1d")
        bull_score = 0; bear_score = 0
        for s, tf in [(s1h,"1H"),(s4h,"4H"),(s1d,"1D")]:
            if s is None: continue
            w = 2 if tf=="1D" else 1
            if s < 20: bull_score += w
            if s > 80: bear_score += w
        if bull_score >= 3: return ("多", True)
        if bear_score >= 3: return ("空", True)
        return ("N/A", False)
    combos.append(eval_combo("SRSI极端值 (SRSI<20多/>80空)", srsi_only))
    
    # 3. DMI + SRSI (当前策略)
    def dmi_srsi(r):
        params = {"alert_threshold": 5, "srsi_os": 20, "srsi_ob": 80,
                  "dir_1h": 1, "dir_4h": 1, "dir_1d": 2, "use_adx": False}
        bull, bear = rescore(r, params)
        if bull >= bear and bull >= 5: return ("多", True)
        if bear > bull and bear >= 5: return ("空", True)
        return ("N/A", False)
    combos.append(eval_combo("DMI+SRSI (当前策略 ≥5)", dmi_srsi))
    
    # 4. 多TF严格一致 (3/3方向相同)
    def tf_strict(r):
        d = {t: r.get(f"dmi_{t.lower()}", "N/A") for t in ["1H","4H","1D"]}
        if d["1H"] == d["4H"] == d["1D"] == "多":
            return ("多", True)
        if d["1H"] == d["4H"] == d["1D"] == "空":
            return ("空", True)
        return ("N/A", False)
    combos.append(eval_combo("3TF严格一致 (全多/全空)", tf_strict))
    
    # 5. 1D主导 (只跟1D方向)
    def d1_lead(r):
        d1d = r.get("dmi_1d", "N/A")
        s1d = r.get("srsi_1d")
        if d1d == "多": return ("多", True)
        if d1d == "空": return ("空", True)
        return ("N/A", False)
    combos.append(eval_combo("仅跟1D方向", d1_lead))
    
    # 6. 1D SRSI 极端 + DMI确认
    def d1_srsi_dmi(r):
        d1d = r.get("dmi_1d", "N/A")
        s1d = r.get("srsi_1d")
        if d1d == "多" and s1d is not None and s1d < 20: return ("多", True)
        if d1d == "空" and s1d is not None and s1d > 80: return ("空", True)
        return ("N/A", False)
    combos.append(eval_combo("1D SRSI极端 + 1D方向确认", d1_srsi_dmi))
    
    # 7. ADX>25 强趋势 + DMI
    def strong_trend(r):
        d1d = r.get("dmi_1d", "N/A")
        adx = r.get("adx_1d")
        if d1d == "多" and adx is not None and adx > 25: return ("多", True)
        if d1d == "空" and adx is not None and adx > 25: return ("空", True)
        return ("N/A", False)
    combos.append(eval_combo("强趋势 (ADX>25 + 1D方向)", strong_trend))
    
    # 8. DMI + 摆动点双重确认
    def dmi_swing(r):
        dmi = {t: r.get(f"dmi_{t.lower()}", "N/A") for t in ["1H","4H","1D"]}
        sw = {t: r.get(f"sw_{t.lower()}", "N/A") for t in ["1H","4H","1D"]}
        agree = sum(1 for t in ["1H","4H","1D"] if dmi[t] == sw[t] and dmi[t] in ("多","空"))
        if agree >= 2:
            if dmi["1D"] == "多": return ("多", True)
            if dmi["1D"] == "空": return ("空", True)
        return ("N/A", False)
    combos.append(eval_combo("DMI+摆动点双重确认", dmi_swing))
    
    # ── 新指标信号 ──
    # 9. EMA交叉
    def ema_cross_signal(r):
        dirs = [r.get("ema_1h"), r.get("ema_4h"), r.get("ema_1d")]
        bull = dirs.count("多"); bear = dirs.count("空")
        if bull >= 2: return ("多", True)
        if bear >= 2: return ("空", True)
        return ("N/A", False)
    if any(r.get("ema_1h") for r in data[:5]):
        combos.append(eval_combo("EMA交叉 (≥2TF一致)", ema_cross_signal))
    
    # 10. 布林带突破
    def boll_signal(r):
        dirs = [r.get("boll_1h"), r.get("boll_4h"), r.get("boll_1d")]
        bull = sum(1 for d in dirs if d == "多"); bear = sum(1 for d in dirs if d == "空")
        if bull >= 2: return ("多", True)
        if bear >= 2: return ("空", True)
        return ("N/A", False)
    if any(r.get("boll_1h") for r in data[:5]):
        combos.append(eval_combo("布林带突破 (≥2TF)", boll_signal))
    
    # 11. CCI极端
    def cci_signal(r):
        cci_1h = r.get("cci_1h"); cci_4h = r.get("cci_4h"); cci_1d = r.get("cci_1d")
        cci_dirs = [r.get("cci_dir_1h"), r.get("cci_dir_4h"), r.get("cci_dir_1d")]
        bull = sum(1 for d in cci_dirs if d == "多"); bear = sum(1 for d in cci_dirs if d == "空")
        extreme = (cci_1d is not None and abs(cci_1d) > 150)
        if bull >= 2 and extreme: return ("多", True)
        if bear >= 2 and extreme: return ("空", True)
        return ("N/A", False)
    if any(r.get("cci_1h") for r in data[:5]):
        combos.append(eval_combo("CCI极端 (>±150 + ≥2TF)", cci_signal))
    
    # 12. MACD方向
    def macd_signal(r):
        macds = [r.get("macd_1h"), r.get("macd_4h"), r.get("macd_1d")]
        valid = [m for m in macds if m is not None]
        if not valid: return ("N/A", False)
        bull = sum(1 for m in valid if m > 0); bear = sum(1 for m in valid if m < 0)
        if bull >= 2: return ("多", True)
        if bear >= 2: return ("空", True)
        return ("N/A", False)
    if any(r.get("macd_1h") for r in data[:5]):
        combos.append(eval_combo("MACD方向 (≥2TF)", macd_signal))
    
    # 13. 最佳混合: DMI + EMA双重确认
    def dmi_ema_combo(r):
        dmi_dirs = [r.get("dmi_1h"), r.get("dmi_4h"), r.get("dmi_1d")]
        ema_dirs = [r.get("ema_1h"), r.get("ema_4h"), r.get("ema_1d")]
        # DMI和EMA都同意
        agree = sum(1 for i in range(3) if dmi_dirs[i] == ema_dirs[i] and dmi_dirs[i] in ("多","空"))
        if agree >= 2:
            if dmi_dirs[2] == "多": return ("多", True)
            if dmi_dirs[2] == "空": return ("空", True)
        return ("N/A", False)
    if any(r.get("ema_1h") for r in data[:5]):
        combos.append(eval_combo("DMI+EMA双重确认", dmi_ema_combo))
    
    # 14. SRSI极端 + CCI确认
    def srsi_cci_combo(r):
        s1d = r.get("srsi_1d"); c1d = r.get("cci_1d")
        if s1d is None or c1d is None: return ("N/A", False)
        if s1d < 20 and c1d < -100: return ("多", True)
        if s1d > 80 and c1d > 100: return ("空", True)
        return ("N/A", False)
    if any(r.get("cci_1h") for r in data[:5]):
        combos.append(eval_combo("SRSI极端+CCI确认", srsi_cci_combo))
    
    # Print results
    combos.sort(key=lambda x: x[2], reverse=True)
    print(f"{'信号规则':<36} {'信号数':>6} {'24H胜率':>9} {'平均收益%':>9}")
    print("-" * 64)
    for name, n, wr, avg in combos:
        bar = "█" * int(wr/5) if wr > 0 else ""
        print(f"{name:<36} {n:>6}  {wr:>7.1f}%  {avg:>8.2f}%  {bar}")
    
    # Best combo recommendation
    best = max(combos, key=lambda x: (x[2], -x[1]) if x[1] > 10 else (0, 0))
    best_balanced = max(combos, key=lambda x: x[2] * min(x[1], 500))
    print(f"\n💡 最高胜率: {best[0]} ({best[2]:.1f}%, {best[1]}信号)")
    if best_balanced[0] != best[0]:
        print(f"💡 最佳平衡: {best_balanced[0]} ({best_balanced[2]:.1f}%, {best_balanced[1]}信号)")

def analyze_entry_confirmation(data):
    """测试不同入场确认规则的效果"""
    print("\n" + "="*70)
    print("✅ 入场确认规则对比")
    print("="*70)
    
    rules = []
    
    # Base: DMI + SRSI standard signal
    def base_signal(r):
        params = {"alert_threshold": 5, "srsi_os": 20, "srsi_ob": 80,
                  "dir_1h": 1, "dir_4h": 1, "dir_1d": 2, "use_adx": False}
        bull, bear = rescore(r, params)
        if bull >= bear and bull >= 5: return "多"
        if bear > bull and bear >= 5: return "空"
        return None
    
    # Confirmation filters
    confirmations = [
        ("无确认 (基准)", lambda r, d: True),
        ("1H同向确认", lambda r, d: r.get("dmi_1h") == d),
        ("4H同向确认", lambda r, d: r.get("dmi_4h") == d),
        ("1D同向确认", lambda r, d: r.get("dmi_1d") == d),
        ("1H+4H同向", lambda r, d: r.get("dmi_1h") == d and r.get("dmi_4h") == d),
        ("摆动点一致", lambda r, d: r.get("sw_1d") == d),
        ("ADX>20", lambda r, d: (r.get("adx_1d") or 0) > 20),
        ("ADX>25", lambda r, d: (r.get("adx_1d") or 0) > 25),
    ]
    
    print(f"{'确认规则':<20} {'信号数':>6} {'过滤率':>7} {'24H胜率':>9} {'提升':>7}")
    print("-" * 54)
    
    base_signals = []
    for r in data:
        if r.get("win_24H") is None: continue
        d = base_signal(r)
        if d: base_signals.append((r, d))
    
    base_wr = sum(s[0]["win_24H"] for s in base_signals)/len(base_signals)*100 if base_signals else 0
    print(f"{'无确认 (基准)':<20} {len(base_signals):>6} {'-':>7} {base_wr:>8.1f}% {'-':>7}")
    
    for conf_name, conf_fn in confirmations[1:]:  # skip baseline
        filtered = [(r, d) for r, d in base_signals if conf_fn(r, d)]
        if not filtered: continue
        wr = sum(s[0]["win_24H"] for s in filtered)/len(filtered)*100
        ratio = len(filtered)/len(base_signals)*100
        improvement = wr - base_wr
        sign = "+" if improvement > 0 else ""
        print(f"{conf_name:<20} {len(filtered):>6} {ratio:>6.1f}% {wr:>8.1f}% {sign}{improvement:>+5.1f}%")
    
    # Best confirmation
    best_conf = None
    best_improve = -999
    for conf_name, conf_fn in confirmations[1:]:
        filtered = [(r, d) for r, d in base_signals if conf_fn(r, d)]
        if not filtered or len(filtered) < 10: continue
        wr = sum(s[0]["win_24H"] for s in filtered)/len(filtered)*100
        if wr - base_wr > best_improve:
            best_improve = wr - base_wr
            best_conf = (conf_name, wr, len(filtered))
    
    if best_conf and best_improve > 0:
        print(f"\n💡 最佳确认规则: {best_conf[0]} (胜率+{best_improve:.1f}%, {best_conf[2]}信号)")

def analyze_srsi_dmi_matrix(data):
    """SRSI极端 × DMI方向 交叉矩阵"""
    print("\n" + "="*70)
    print("🧩 SRSI极端 × DMI方向 交叉矩阵 (24H胜率)")
    print("="*70)
    
    dmi_signals = [r for r in data if r["std"] == "DMI纯分" and r.get("win_24H") is not None]
    
    conditions = [
        ("1D SRSI<20", lambda r: r.get("srsi_1d") and r["srsi_1d"] < 20),
        ("4H SRSI<20", lambda r: r.get("srsi_4h") and r["srsi_4h"] < 20),
        ("1H SRSI<20", lambda r: r.get("srsi_1h") and r["srsi_1h"] < 20),
        ("1D SRSI>80", lambda r: r.get("srsi_1d") and r["srsi_1d"] > 80),
        ("4H SRSI>80", lambda r: r.get("srsi_4h") and r["srsi_4h"] > 80),
        ("1H SRSI>80", lambda r: r.get("srsi_1h") and r["srsi_1h"] > 80),
    ]
    
    dmi_tfs = ["1H", "4H", "1D"]
    
    print(f"{'SRSI条件\\DMI':<18}", end="")
    for tf in dmi_tfs: print(f" {tf}多:>7", end="")
    print(f" {'综合':>7}")
    print("-" * 48)
    
    for label, cond in conditions:
        subset = [r for r in dmi_signals if cond(r)]
        if not subset: continue
        print(f"{label:<18}", end="")
        total_wr = 0
        for tf in dmi_tfs:
            dmi_key = f"dmi_{tf.lower()}"
            tf_sub = [r for r in subset if r.get(dmi_key) == ("多" if "SRSI<" in label else "空")]
            if tf_sub:
                wr = sum(r["win_24H"] for r in tf_sub)/len(tf_sub)*100
                print(f" {wr:>6.1f}%", end="")
                total_wr += wr * len(tf_sub)
            else:
                print(f" {'-':>6}", end="")
        if subset:
            overall = sum(r["win_24H"] for r in subset)/len(subset)*100
            print(f" {overall:>6.1f}%", end="")
        print()

def analyze_timeframe_priority(data):
    """哪个时间框架的指标最重要"""
    print("\n" + "="*70)
    print("⏱️ 时间框架优先级分析")
    print("="*70)
    
    dmi_signals = [r for r in data if r["std"] == "DMI纯分" and r.get("win_24H") is not None]
    
    # Test: when 1D direction is right vs wrong
    print(f"\n{'指标':<18} {'与最终方向':>10} {'信号数':>6} {'24H胜率':>9}")
    print("-" * 48)
    
    for tf in ["1H", "4H", "1D"]:
        dmi_key = f"dmi_{tf.lower()}"
        # When this TF's DMI matches the signal direction
        for direction in ["多", "空"]:
            label = f"{tf} DMI={direction}"
            subset = [r for r in dmi_signals if r.get(dmi_key) == direction 
                     and r["direction"] == direction]
            if subset:
                wr = sum(r["win_24H"] for r in subset)/len(subset)*100
                print(f"{label:<18} {'→ 同向':>10} {len(subset):>6}  {wr:>7.1f}%")

    # 1D as anchor
    print(f"\n─ 1D方向作为锚点 ─")
    for d1d in ["多", "空"]:
        anchor = [r for r in dmi_signals if r.get("dmi_1d") == d1d]
        if not anchor: continue
        # When 1D matches vs doesn't match
        match = [r for r in anchor if r["direction"] == d1d]
        mismatch = [r for r in anchor if r["direction"] != d1d]
        print(f"  1D={d1d}: 同向{match and len(match) or 0}信号({match and sum(r['win_24H']for r in match)/len(match)*100 or 0:.0f}%) "
              f"反向{mismatch and len(mismatch) or 0}信号({mismatch and sum(r['win_24H']for r in mismatch)/len(mismatch)*100 or 0:.0f}%)")

def analyze_volatility_context(data):
    """波动率(ADX)环境对胜率的影响"""
    print("\n" + "="*70)
    print("📈 波动率环境对胜率的影响")
    print("="*70)
    
    dmi_signals = [r for r in data if r["std"] == "DMI纯分" and r.get("win_24H") is not None 
                   and r.get("adx_1d") is not None]
    
    # ADX buckets
    buckets = [(0, 15, "极弱趋势"), (15, 20, "弱趋势"), (20, 25, "趋势形成"), 
               (25, 35, "强趋势"), (35, 100, "极强趋势")]
    
    print(f"{'ADX区间':<16} {'描述':<10} {'信号':>6} {'24H胜率':>9} {'多胜率':>7} {'空胜率':>7}")
    print("-" * 60)
    
    for lo, hi, desc in buckets:
        subset = [r for r in dmi_signals if lo <= r["adx_1d"] < hi]
        if not subset: continue
        wr = sum(r["win_24H"] for r in subset)/len(subset)*100
        long = [r for r in subset if r["direction"] == "多"]
        short = [r for r in subset if r["direction"] == "空"]
        lwr = sum(r["win_24H"] for r in long)/len(long)*100 if long else 0
        swr = sum(r["win_24H"] for r in short)/len(short)*100 if short else 0
        print(f"ADX {lo}-{hi:<2}    {desc:<10} {len(subset):>6}  {wr:>7.1f}%  {lwr:>6.1f}%  {swr:>6.1f}%")

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
    test_signal_combinations(data)
    analyze_entry_confirmation(data)
    analyze_srsi_dmi_matrix(data)
    analyze_timeframe_priority(data)
    analyze_volatility_context(data)
    generate_recommendations(data)

if __name__ == "__main__":
    main()
