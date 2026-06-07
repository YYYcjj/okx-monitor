"""
快速回测运行器 — BTC/ETH 最优参数搜索
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from engine import fetch_extended, backtest, calc_metrics, grid_search

print("=" * 60)
print("OKX 策略回测 — 寻找最优入场/离场参数")
print("=" * 60)

# 拉数据
print("\n📡 拉取 BTC + ETH 1H 数据...")
test_candles = {}
for sym in ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]:
    data = fetch_extended(sym, bars=1000)
    if data:
        test_candles[sym] = data
        print(f"  {sym}: {len(data)} 根K线")

# 缩小网格（关键参数）
print("\n🔍 网格搜索中...")
results = grid_search(
    ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
    {"BTC-USDT-SWAP": 1000, "ETH-USDT-SWAP": 1000},
    test_candles
)

# 输出
print("\n" + "=" * 60)
print("🏆 Top 15 策略排名")
print("=" * 60)
for i, r in enumerate(results[:15]):
    p = r["params"]
    print(f"\n{i+1:2d}. 综合得分={r['score']:.4f}  | 胜率={r['win_rate']:.1%} | 收益率={r['total_return']:.1f}% | Sharpe={r['sharpe']:.1f} | 交易{r['trades']}次")
    print(f"   阈值={p['alert_threshold']}  DMI权={p['dmi_weights']}  ST×{p['st_mult']}  近ST={p['near_pct']:.1%}")
    print(f"   止损×{p['sl_atr_mult']}(最低{p['min_sl_pct']:.0%})  止盈×{p['tp_atr_mult']}  入场={p['entry_mode']}  区间深={p['zone_depth']}")

# 分析最佳入场模式
print("\n\n📊 按入场模式分组:")
for mode in ["st_near", "st_in_zone"]:
    group = [r for r in results if r["params"]["entry_mode"] == mode]
    if group:
        avg_win = sum(r["win_rate"] for r in group) / len(group)
        avg_ret = sum(r["total_return"] for r in group) / len(group)
        avg_trades = sum(r["trades"] for r in group) / len(group)
        print(f"  {mode}: 平均胜率={avg_win:.1%} 平均收益={avg_ret:.1f}% 平均交易={avg_trades:.0f} (n={len(group)})")

# 分析最佳阈值
print("\n📊 按预警阈值分组:")
for th in [7, 8, 9]:
    group = [r for r in results if r["params"]["alert_threshold"] == th]
    if group:
        avg_win = sum(r["win_rate"] for r in group) / len(group)
        avg_ret = sum(r["total_return"] for r in group) / len(group)
        avg_trades = sum(r["trades"] for r in group) / len(group)
        print(f"  阈值={th}: 平均胜率={avg_win:.1%} 平均收益={avg_ret:.1f}% 平均交易={avg_trades:.0f} (n={len(group)})")

# 最佳盈亏比分析
print("\n📊 按止盈倍数分组:")
for tp in [4.0, 6.0, 8.0]:
    group = [r for r in results if r["params"]["tp_atr_mult"] == tp]
    if group:
        avg_win = sum(r["win_rate"] for r in group) / len(group)
        avg_ret = sum(r["total_return"] for r in group) / len(group)
        print(f"  止盈×{tp:.0f}: 平均胜率={avg_win:.1%} 平均收益={avg_ret:.1f}% (n={len(group)})")
