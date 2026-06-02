#!/usr/bin/env python3
"""OKX持仓历史分析 - 修正版"""
import csv
import os
from collections import defaultdict

CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "okx_data")
csv_file = None
for root, dirs, files in os.walk(CSV_DIR):
    for f in files:
        if f.endswith('.csv'):
            csv_file = os.path.join(root, f)
            break

if not csv_file:
    print("未找到CSV文件")
    exit(1)

rows = []
with open(csv_file, encoding='utf-8-sig') as f:
    # Skip first metadata line
    next(f)
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

total_pnl = 0.0
total_fees = 0.0
total_funding = 0.0
wins = 0
losses = 0
by_symbol = defaultdict(lambda: {'pnl': 0, 'count': 0, 'wins': 0, 'losses': 0, 'fees': 0, 'funding': 0})
by_month = defaultdict(lambda: {'pnl': 0, 'count': 0})
by_direction = defaultdict(lambda: {'pnl': 0, 'count': 0, 'wins': 0})
best_trades = []

def safe_float(v):
    try: return float(v) if v else 0
    except: return 0

for r in rows:
    pnl = safe_float(r.get('收益额', ''))
    fee = safe_float(r.get('累计手续费', ''))
    fund = safe_float(r.get('累计资金费用', ''))
    symbol = (r.get('交易产品', '') or '').replace('-SWAP', '')
    direction = r.get('持仓方向', '') or ''
    dt = (r.get('仓位创建时间', '') or '')[:7]
    
    total_pnl += pnl
    total_fees += fee
    total_funding += fund
    
    if pnl > 0.001:
        wins += 1
        by_symbol[symbol]['wins'] += 1
    elif pnl < -0.001:
        losses += 1
        by_symbol[symbol]['losses'] += 1
    
    by_symbol[symbol]['pnl'] += pnl
    by_symbol[symbol]['count'] += 1
    by_symbol[symbol]['fees'] += fee
    by_symbol[symbol]['funding'] += fund
    by_month[dt]['pnl'] += pnl
    by_month[dt]['count'] += 1
    by_direction[direction]['pnl'] += pnl
    by_direction[direction]['count'] += 1
    if pnl > 0:
        by_direction[direction]['wins'] += 1
    
    if pnl != 0:
        best_trades.append((pnl, symbol, direction, dt))

best_trades.sort(key=lambda x: x[0], reverse=True)

net = total_pnl - total_fees - total_funding
total = wins + losses
wr = wins / total * 100 if total > 0 else 0

print('=' * 68)
print('   📊 OKX 历史交易记录分析 (2023.05 ~ 2026.05)')
print('=' * 68)
print()
print(f'  📈 总交易:  {len(rows)}笔  盈利: {wins}  亏损: {losses}')
print(f'  🎯 胜率:    {wr:.1f}%')
print(f'  💰 总盈亏:  ¥{total_pnl:+,.2f}')
print(f'  🧾 手续费:  ¥{abs(total_fees):,.2f}')
print(f'  ⚡ 资金费:  ¥{total_funding:+,.2f}')
print(f'  💎 净收益:  ¥{net:+,.2f}')
print()

print('  ── 按方向 ──')
print(f'  {"方向":<6} {"次数":>5} {"胜场":>5} {"胜率":>7} {"PnL":>14}')
for d in ['做多', '做空']:
    dd = by_direction[d]
    dwr = dd['wins']/dd['count']*100 if dd['count'] else 0
    print(f'  {d:<6} {dd["count"]:>5} {dd["wins"]:>5} {dwr:>6.1f}% ¥{dd["pnl"]:>+12,.2f}')
print()

print('  ── 按币种 (按盈亏排序) ──')
print(f'  {"币种":<16} {"次数":>4} {"胜率":>7} {"PnL":>12} {"手续费":>10} {"资金费率":>10}')
sorted_sym = sorted(by_symbol.items(), key=lambda x: x[1]['pnl'], reverse=True)
for sym, d in sorted_sym:
    swr = d['wins']/d['count']*100 if d['count'] else 0
    print(f'  {sym:<16} {d["count"]:>4} {swr:>6.1f}% ¥{d["pnl"]:>+10,.2f} ¥{d["fees"]:>8,.2f} ¥{d["funding"]:>+8,.2f}')
print()

print('  ── 近12个月 ──')
print(f'  {"月份":<10} {"次数":>4} {"PnL":>14}')
for m in sorted(by_month.keys())[-12:]:
    d = by_month[m]
    print(f'  {m:<10} {d["count"]:>4} ¥{d["pnl"]:>+12,.2f}')
print()

print('  ── 最佳/最差各5笔 ──')
for i, (pnl, sym, dir_, dt) in enumerate(best_trades[:5], 1):
    print(f'  🏆{i}. {sym} {dir_} ¥{pnl:+,.2f} [{dt}]')
for i, (pnl, sym, dir_, dt) in enumerate(best_trades[-5:], 1):
    print(f'  💀{i}. {sym} {dir_} ¥{pnl:+,.2f} [{dt}]')
