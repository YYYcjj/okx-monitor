#!/usr/bin/env python3
"""
项目3: 高分信号入场/离场分析
- 回测扫描CSV中的≥6分信号
- 计算: MAE(最大回撤)/MFE(最大盈利)/不同时间胜率
- 确定最优止损阈值和离场时机
用法: python analysis/entry_exit_analysis.py [csv文件]  默认用今天
"""
import csv, os, sys, time, json, math
from datetime import datetime, timezone, timedelta
import warnings
warnings.filterwarnings("ignore")
import urllib3; urllib3.disable_warnings()
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SCAN_DIR = os.path.join(PROJECT_ROOT, "okx_data", "scans")
OUTPUT = os.path.join(PROJECT_ROOT, "okx_data", "entry_exit_analysis.json")

OKX_BASE = "https://www.okx.com"

def fetch_history(symbol, bar="1H", after_ts=None, limit=24):
    """获取历史K线，返回 [{h,l,c,ts}]"""
    url = f"{OKX_BASE}/api/v5/market/history-candles"
    params = {"instId": symbol, "bar": bar, "limit": limit}
    if after_ts:
        params["after"] = str(int(after_ts))
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=15)
            d = resp.json()
            if d.get("code") == "0":
                candles = []
                for c in d["data"]:
                    ts_ms = int(c[0])
                    candles.append({
                        "ts": ts_ms / 1000,
                        "h": float(c[2]), "l": float(c[3]), "c": float(c[4])
                    })
                candles.reverse()
                return candles
            return None
        except:
            if attempt < 2: time.sleep(1)
    return None

def get_entry_price(symbol, target_ts):
    """获取指定时间戳附近的K线收盘价作为入场价"""
    candles = fetch_history(symbol, "5m", after_ts=target_ts * 1000, limit=5)
    if candles and len(candles) >= 1:
        return candles[0]["c"]
    return None

def analyze_signal(symbol, direction, entry_price, entry_ts):
    """跟踪信号入场后24H表现"""
    candles = fetch_history(symbol, "1H", after_ts=entry_ts * 1000, limit=24)
    if not candles or len(candles) < 4:
        return None

    mae_pct = 0    # max adverse excursion (最大浮亏%)
    mfe_pct = 0    # max favorable excursion (最大浮盈%)
    results = {"4H": None, "12H": None, "24H": None}
    
    for i, c in enumerate(candles):
        if direction == "多":
            pct = (c["l"] - entry_price) / entry_price * 100  # 最低点回撤
            profit = (c["c"] - entry_price) / entry_price * 100
        else:
            pct = (entry_price - c["h"]) / entry_price * 100   # 最高点回撤
            profit = (entry_price - c["c"]) / entry_price * 100
        
        if pct < mae_pct:
            mae_pct = pct
        if profit > mfe_pct:
            mfe_pct = profit
        
        if i == 3 and results["4H"] is None:
            results["4H"] = round(profit, 2)
        if i == 11 and results["12H"] is None:
            results["12H"] = round(profit, 2)
        if i == 23:
            results["24H"] = round(profit, 2)

    return {
        "mae": round(mae_pct, 2),
        "mfe": round(mfe_pct, 2),
        "4H": results["4H"],
        "12H": results["12H"],
        "24H": results["24H"],
        "entry": round(entry_price, 6)
    }

def load_signals(csv_file=None):
    """加载扫描CSV中的≥6分信号"""
    if csv_file and os.path.exists(csv_file):
        fp = csv_file
    else:
        files = sorted([f for f in os.listdir(SCAN_DIR) if f.endswith('.csv')], reverse=True)
        if not files:
            print("⚠️ 无扫描数据")
            return []
        fp = os.path.join(SCAN_DIR, files[0])
    
    print(f"📂 {os.path.basename(fp)}")
    signals = []
    seen = set()
    with open(fp, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            bull = int(row.get('dmi_bull', 0))
            bear = int(row.get('dmi_bear', 0))
            if bull < 6 and bear < 6:
                continue
            sym = row.get('symbol', '')
            ts = row.get('timestamp', '')
            # 每个币种+方向只取最早一次
            direction = "多" if bull >= bear else "空"
            score = max(bull, bear)
            key = f"{sym}_{direction}"
            if key in seen:
                continue
            seen.add(key)
            signals.append({"symbol": sym, "direction": direction, "score": score, "timestamp": ts})
    
    print(f"  ≥6分信号: {len(signals)} 个（去重后按首次出现）")
    return signals

def analyze_backtest(bt_file):
    """分析回测数据中的信号（已有pct_4H/12H/24H，不需要API）"""
    results = []
    with open(bt_file, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            score = int(row.get('score', 0))
            if score < 6:
                continue
            pcts = []
            for k in ['pct_4H', 'pct_12H', 'pct_24H']:
                try: pcts.append(float(row.get(k, 0) or 0))
                except: pcts.append(0)
            
            # 用最差值估算MAE
            mae = min(pcts) if min(pcts) < 0 else 0
            mfe = max(pcts) if max(pcts) > 0 else 0
            
            results.append({
                "symbol": row.get('symbol', ''),
                "direction": row.get('direction', ''),
                "score": score,
                "mae": round(mae, 2),
                "mfe": round(mfe, 2),
                "4H": pcts[0], "12H": pcts[1], "24H": pcts[2],
                "entry": float(row.get('entry', 0))
            })
    print(f"  ≥6分信号: {len(results)} 个 (回测数据)")
    return results

def print_summary(results):
    """打印汇总分析"""
    if not results:
        print("\n⚠️ 无有效结果")
        return

    print(f"\n{'='*65}")
    print(f"📊 汇总分析 ({len(results)} 个信号)")
    print(f"{'='*65}")

    # 胜率
    for label, key in [("4H", "4H"), ("12H", "12H"), ("24H", "24H")]:
        wins = sum(1 for r in results if r[key] is not None and r[key] > 0)
        total = sum(1 for r in results if r[key] is not None)
        avg = sum(r[key] for r in results if r[key] is not None) / total if total > 0 else 0
        wr = wins / total * 100 if total > 0 else 0
        print(f"  {label}胜率: {wins}/{total} = {wr:.1f}%  平均收益: {avg:+.2f}%")

    # MAE分布
    maes = sorted([abs(r["mae"]) for r in results])
    mfes = sorted([r["mfe"] for r in results])
    
    print(f"\n📉 MAE分布(最大回撤): 中位={maes[len(maes)//2]:.2f}%  最差={maes[-1]:.2f}%")
    print(f"📈 MFE分布(最大盈利): 中位={mfes[len(mfes)//2]:.2f}%  最佳={mfes[-1]:.2f}%")

    # 止损阈值
    print(f"\n🎯 止损阈值建议:")
    thresholds = [1, 2, 3, 4, 5, 8, 10, 15, 20]
    for t in thresholds:
        survived = sum(1 for m in maes if m <= t)
        pct = survived / len(maes) * 100
        surv_24h = [r for r in results if abs(r["mae"]) <= t and r["24H"] is not None]
        win_24h = sum(1 for r in surv_24h if r["24H"] > 0)
        wr_24h = win_24h / len(surv_24h) * 100 if surv_24h else 0
        avg_24h = sum(r["24H"] for r in surv_24h) / len(surv_24h) if surv_24h else 0
        bar = "█" * int(pct / 5)
        print(f"  止损 {t:>2}%: 存活{survived}/{len(maes)}({pct:.0f}%) {bar}  24H胜率{wr_24h:.0f}% 均收益{avg_24h:+.2f}%")

    # 离场时机
    print(f"\n⏰ 离场时机分析:")
    for label, key in [("4H", "4H"), ("12H", "12H"), ("24H", "24H")]:
        valid = [r[key] for r in results if r[key] is not None]
        if not valid: continue
        wins = sum(1 for v in valid if v > 0)
        avg_all = sum(valid) / len(valid)
        avg_win = sum(v for v in valid if v > 0) / max(1, wins)
        avg_loss = sum(v for v in valid if v <= 0) / max(1, len(valid) - wins)
        print(f"  {label}: 胜率{wins}/{len(valid)}={wins/len(valid)*100:.0f}%  均{avg_all:+.2f}%  赢均{avg_win:+.2f}%  输均{avg_loss:+.2f}%")

    # 持仓>24H分析
    long_holds = [r for r in results if r["24H"] is not None and r["24H"] > 0]
    if long_holds:
        avg_24h_win = sum(r["24H"] for r in long_holds) / len(long_holds)
        print(f"  >24H: 盈利{len(long_holds)}个 均收益{avg_24h_win:+.2f}%")
    
    # JSON
    with open(OUTPUT, "w") as f:
        json.dump({
            "total": len(results),
            "signals": results,
            "mae_median": maes[len(maes)//2],
            "mfe_median": mfes[len(mfes)//2]
        }, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果: {OUTPUT}")

def parse_timestamp(ts_str):
    """解析 '2026-06-03 21:58' 格式为 UTC timestamp"""
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
        return dt.timestamp()
    except:
        return None

def main():
    csv_file = sys.argv[1] if len(sys.argv) > 1 else None
    
    # 如果没有扫描CSV，用回测数据
    if not csv_file:
        bt_file = os.path.join(PROJECT_ROOT, "okx_data", "backtest_results.csv")
        if os.path.exists(bt_file):
            print("📂 使用回测数据 (backtest_results.csv)")
            results = analyze_backtest(bt_file)
            print_summary(results)
            return
    
    signals = load_signals(csv_file)
    if not signals:
        # 回退到回测数据
        bt_file = os.path.join(PROJECT_ROOT, "okx_data", "backtest_results.csv")
        if os.path.exists(bt_file):
            print("📂 回退到回测数据")
            results = analyze_backtest(bt_file)
            print_summary(results)
        return

    results = []
    print(f"\n{'符号':<10} {'方向':^4} {'入场':>10} {'MAE%':>7} {'MFE%':>7} {'4H%':>7} {'12H%':>7} {'24H%':>7}")
    print("-" * 65)

    for sig in signals:
        ts = parse_timestamp(sig["timestamp"])
        if not ts:
            continue
        entry = get_entry_price(sig["symbol"], ts)
        if not entry:
            name = sig["symbol"].replace("-USDT-SWAP", "")
            print(f"{name:<10} {sig['direction']:^4} {'N/A':>10}")
            continue
        
        r = analyze_signal(sig["symbol"], sig["direction"], entry, ts)
        if not r:
            name = sig["symbol"].replace("-USDT-SWAP", "")
            print(f"{name:<10} {sig['direction']:^4} {entry:<10.6f} 数据不足")
            continue

        r["symbol"] = sig["symbol"]
        r["direction"] = sig["direction"]
        r["score"] = sig["score"]
        results.append(r)
        
        name = sig["symbol"].replace("-USDT-SWAP", "")
        sign_4h = "+" if (r["4H"] or 0) > 0 else ""
        sign_12h = "+" if (r["12H"] or 0) > 0 else ""
        sign_24h = "+" if (r["24H"] or 0) > 0 else ""
        print(f"{name:<10} {r['direction']:^4} {r['entry']:<10.6f} {r['mae']:>7.2f} {r['mfe']:>7.2f} {sign_4h}{r['4H']:>6.2f} {sign_12h}{r['12H']:>6.2f} {sign_24h}{r['24H']:>6.2f}")
        time.sleep(0.3)

    if not results:
        print("\n⚠️ 无有效结果")
        return

    # ── 汇总分析 ──
    print(f"\n{'='*65}")
    print(f"📊 汇总分析 ({len(results)} 个信号)")
    print(f"{'='*65}")

    # 胜率
    for label, key in [("4H", "4H"), ("12H", "12H"), ("24H", "24H")]:
        wins = sum(1 for r in results if r[key] is not None and r[key] > 0)
        total = sum(1 for r in results if r[key] is not None)
        avg = sum(r[key] for r in results if r[key] is not None) / total if total > 0 else 0
        wr = wins / total * 100 if total > 0 else 0
        print(f"  {label}胜率: {wins}/{total} = {wr:.1f}%  平均收益: {avg:+.2f}%")

    # MAE分布 → 止损建议
    maes = sorted([abs(r["mae"]) for r in results])
    mfes = sorted([r["mfe"] for r in results])
    
    print(f"\n📉 MAE分布(最大回撤): 中位={maes[len(maes)//2]:.2f}%  最差={maes[-1]:.2f}%")
    print(f"📈 MFE分布(最大盈利): 中位={mfes[len(mfes)//2]:.2f}%  最佳={mfes[-1]:.2f}%")

    # 止损阈值建议
    print(f"\n🎯 止损阈值建议:")
    thresholds = [1, 2, 3, 4, 5, 8, 10, 15, 20]
    for t in thresholds:
        survived = sum(1 for m in maes if m <= t)
        pct = survived / len(maes) * 100
        # 在这些存活信号中，24H胜率
        surv_24h = [r for r, m in zip(results, maes) if abs(r["mae"]) <= t and r["24H"] is not None]
        win_24h = sum(1 for r in surv_24h if r["24H"] > 0)
        wr_24h = win_24h / len(surv_24h) * 100 if surv_24h else 0
        avg_24h = sum(r["24H"] for r in surv_24h) / len(surv_24h) if surv_24h else 0
        bar = "█" * int(pct / 5)
        print(f"  止损 {t:>2}%: 存活{survived}/{len(maes)}({pct:.0f}%) {bar}  24H胜率{wr_24h:.0f}% 均收益{avg_24h:+.2f}%")

    # 离场时机
    print(f"\n⏰ 离场时机分析:")
    for label, key in [("4H", "4H"), ("12H", "12H"), ("24H", "24H")]:
        valid = [r[key] for r in results if r[key] is not None]
        if not valid: continue
        wins = sum(1 for v in valid if v > 0)
        avg_all = sum(valid) / len(valid)
        avg_win = sum(v for v in valid if v > 0) / max(1, wins)
        avg_loss = sum(v for v in valid if v <= 0) / max(1, len(valid) - wins)
        print(f"  {label}: 胜率{wins}/{len(valid)}={wins/len(valid)*100:.0f}%  均{avg_all:+.2f}%  赢均{avg_win:+.2f}%  输均{avg_loss:+.2f}%")

    # 输出JSON
    with open(OUTPUT, "w") as f:
        json.dump({"signals": results, "mae_median": maes[len(maes)//2], "mfe_median": mfes[len(mfes)//2]}, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存: {OUTPUT}")

if __name__ == "__main__":
    main()
