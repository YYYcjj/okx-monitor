#!/usr/bin/env python3
"""
热门币种筛选器
每天从OKX成交量前30名中，筛选符合策略条件的品种
条件: 1H ATR < 3% | 无离谱插针 | 趋势清晰
输出: SYMBOLS.txt (监控脚本可读取)
"""
import requests, time, urllib3, json, os, sys
urllib3.disable_warnings()

OKX = 'https://www.okx.com'
HEADERS = {'User-Agent': 'Mozilla/5.0'}
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR) if 'tools' in SCRIPT_DIR else SCRIPT_DIR
OUTPUT = os.path.join(PROJECT_ROOT, "SYMBOLS.txt")
FIXED_FILE = os.path.join(PROJECT_ROOT, "FIXED_SYMBOLS.txt")
HISTORY_FILE = os.path.join(os.path.dirname(SCRIPT_DIR) if 'tools' in SCRIPT_DIR else SCRIPT_DIR, "tools", "scan_history.json")

def fetch_top_pairs(limit=30):
    """获取成交量前N的USDT永续合约"""
    resp = requests.get(f'{OKX}/api/v5/market/tickers',
        params={'instType': 'SWAP'}, headers=HEADERS, verify=False, timeout=15)
    data = resp.json()
    pairs = []
    exclude = {'XAG-USDT-SWAP', 'XAU-USDT-SWAP'}  # 排除商品
    for t in data.get('data', []):
        instId = t['instId']
        if instId in exclude: continue
        if instId.endswith('-USDT-SWAP'):
            vol24 = float(t.get('vol24h', 0))
            pairs.append((instId, vol24))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return pairs[:limit]

def scan_pair(sym):
    """检查单个品种的质量"""
    try:
        resp = requests.get(f'{OKX}/api/v5/market/candles',
            params={'instId': sym, 'bar': '1H', 'limit': 100},
            headers=HEADERS, verify=False, timeout=15)
        candles = resp.json().get('data', [])
        if len(candles) < 72:
            return None
        
        candles.reverse()
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]
        closes = [float(c[4]) for c in candles]
        price = closes[-1]
        
        # 1H ATR
        trs = []
        for i in range(1, len(candles)):
            tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
            trs.append(tr)
        atr = sum(trs[-14:]) / 14
        atr_pct = atr / price * 100
        if atr_pct > 3:
            return None
        
        # 插针检查
        bad_wicks = 0
        for i in range(max(0, len(candles)-48), len(candles)):
            hi, lo, op = highs[i], lows[i], closes[i-1] if i > 0 else highs[i]
            cl = closes[i]
            upper_wick = hi - max(cl, op)
            lower_wick = min(cl, op) - lo
            max_wick = max(upper_wick, lower_wick)
            if max_wick > 3 * atr:
                bad_wicks += 1
        wick_pct = bad_wicks / 48
        if wick_pct > 0.12:
            return None
        
        # 趋势
        up_moves = sum(1 for i in range(max(0, len(candles)-24), len(candles)) if closes[i] > closes[i-1])
        trend = abs(up_moves / 24 - 0.5) * 2
        momentum = (price - closes[-24]) / closes[-24] * 100
        
        name = sym.replace('-USDT-SWAP', '')
        score = round(10 - atr_pct*1.5 - wick_pct*15 + trend*3 + min(abs(momentum)*1.5, 3), 1)
        
        return {
            'symbol': f"{name}-USDT-SWAP",
            'name': name,
            'atr_pct': round(atr_pct, 1),
            'wick_pct': round(wick_pct*100, 1),
            'trend': round(trend, 2),
            'momentum': round(momentum, 1),
            'score': score
        }
    except:
        return None

def main():
    print(f"🔍 扫描OKX成交量前30品种...")
    pairs = fetch_top_pairs(30)
    print(f"  获取 {len(pairs)} 个热门前30品种\n")
    
    results = []
    for sym, vol24 in pairs:
        info = scan_pair(sym)
        if info:
            info['vol24'] = vol24
            results.append(info)
        time.sleep(0.08)
    
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"{'品种':<10} {'ATR%':>6} {'插针%':>6} {'趋势':>5} {'24H':>6} {'评分':>5}")
    print("-" * 45)
    for r in results:
        name = r['name']
        print(f"{name:<10} {r['atr_pct']:>5.1f}% {r['wick_pct']:>5.1f}% {r['trend']:>4.2f} {r['momentum']:>+5.1f}% {r['score']:>5.1f}")
    
    # 取前15个
    selected = [r['symbol'] for r in results[:15]]
    
    # 确保BTC在列表中
    btc_swap = "BTC-USDT-SWAP"
    if btc_swap not in selected:
        selected.insert(0, btc_swap)
    
    # ── 连续3天跟踪 ──
    today = time.strftime("%Y-%m-%d")
    history = {}
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            history = json.load(f)
    
    # 记录今天
    history[today] = selected
    # 只保留最近7天
    history = {k: v for k, v in sorted(history.items())[-7:]}
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)
    
    # 检查连续3天上榜 → 加入固定清单
    dates = sorted(history.keys())
    if len(dates) >= 3:
        last3 = dates[-3:]
        consec = set(history[last3[0]])
        for d in last3[1:]:
            consec &= set(history[d])
        
        fixed = set()
        if os.path.exists(FIXED_FILE):
            with open(FIXED_FILE) as f:
                fixed = set(l.strip() for l in f if l.strip())
        
        new_fixed = consec - fixed
        if new_fixed:
            fixed |= new_fixed
            with open(FIXED_FILE, 'w') as f:
                f.write('\n'.join(sorted(fixed)) + '\n')
            print(f"\n⭐ 新固定清单: {' '.join(s.replace('-USDT-SWAP','') for s in new_fixed)}")
    
    # ── 合并: 固定清单优先，然后是今日筛选 ──
    fixed_list = []
    if os.path.exists(FIXED_FILE):
        with open(FIXED_FILE) as f:
            fixed_list = [l.strip() for l in f if l.strip()]
    
    final = fixed_list + [s for s in selected if s not in fixed_list]
    
    # 写入 SYMBOLS.txt（固定优先，动态补充，总数≤25）
    with open(OUTPUT, 'w') as f:
        f.write('\n'.join(selected[:10]) + '\n')
    
    print(f"\n✅ 共 {len(final[:25])} 个品种 → {OUTPUT}")
    fixed_names = [s.replace('-USDT-SWAP','') for s in fixed_list]
    dyn_names = [s.replace('-USDT-SWAP','') for s in selected if s not in fixed_list]
    print(f"   固定({len(fixed_list)}): {' '.join(fixed_names[:10])}{'...' if len(fixed_list)>10 else ''}")
    print(f"   动态({len(final[:25])-len(fixed_list)}): {' '.join(dyn_names[:10])}{'...' if len(selected)>10 else ''}")

if __name__ == '__main__':
    main()
