#!/usr/bin/env python3
"""
项目4: 交易订单独立分析 - 确定最佳止损/止盈
- 从OKX API获取成交历史
- 对每笔交易追溯价格走势
- 计算最佳止损(回撤≤34%)和最大利润止盈位
"""
import csv, os, sys, time, json, hmac, base64, hashlib
from datetime import datetime, timezone, timedelta
import warnings; warnings.filterwarnings("ignore")
import urllib3; urllib3.disable_warnings()
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT = os.path.join(PROJECT_ROOT, "okx_data", "trade_optimization.json")

# OKX API 配置
API_KEY = "6d758f5a-4ea7-44d1-bc56-5b8659263b1a"
API_SECRET = "760BEBD659B861D17B5DE6DF7112E5CF"
API_PASSPHRASE = "1qaz2wsxcJJ!"
OKX_BASE = "https://www.okx.com"

def okx_sign(timestamp, method, path, body=""):
    sign_str = timestamp + method + path + body
    return base64.b64encode(hmac.new(API_SECRET.encode(), sign_str.encode(), hashlib.sha256).digest()).decode()

def okx_request(method, path, params=None):
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    qs = "?" + "&".join(f"{k}={v}" for k,v in (params or {}).items()) if params else ""
    sign = okx_sign(ts, method, path + qs)
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }
    for attempt in range(3):
        try:
            resp = requests.request(method, OKX_BASE + path + qs, headers=headers, timeout=20)
            return resp.json()
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                return {"code": "-1", "msg": str(e)}

def get_filled_orders():
    """获取近90天成交订单 (分页)"""
    all_orders = []
    after = ""
    
    for page in range(10):  # 最多10页
        params = {"instType": "SWAP", "state": "filled", "limit": "100"}
        if after:
            params["after"] = after
        
        result = okx_request("GET", "/api/v5/trade/orders-history", params)
        
        if result.get("code") != "0":
            print(f"  API错误: {result}")
            break
        
        data = result.get("data", [])
        if not data:
            break
        
        all_orders.extend(data)
        after = data[-1].get("ordId", "")
        
        if len(data) < 100:
            break
        time.sleep(0.3)
    
    print(f"  获取到 {len(all_orders)} 笔成交 ({page+1} 页)")
    return all_orders

def group_trades(orders):
    """将订单配对成完整交易 (reduceOnly区分开平仓)"""
    entries = []  # 开仓单
    exits = []    # 平仓单
    
    for o in orders:
        if o.get("reduceOnly") == "true":
            exits.append(o)
        else:
            entries.append(o)
    
    print(f"  开仓: {len(entries)} 笔 | 平仓: {len(exits)} 笔")
    
    trades = []
    # 对每个平仓单，找最近的开仓单匹配
    sorted_exits = sorted(exits, key=lambda x: int(x.get("cTime", "0")))
    
    for ex in sorted_exits:
        ex_sym = ex["instId"]
        ex_pos = ex["posSide"]  # long/short
        ex_time = int(ex["cTime"])
        
        # 找同样symbol+posSide且时间在前的最近开仓
        candidates = [(i, e) for i, e in enumerate(entries) 
                      if e["instId"] == ex_sym and e["posSide"] == ex_pos 
                      and int(e["cTime"]) < ex_time]
        if not candidates:
            continue
        
        # 取最近的
        candidates.sort(key=lambda x: int(x[1]["cTime"]), reverse=True)
        idx, en = candidates[0]
        entries.pop(idx)
        
        entry_px = float(en["avgPx"])
        exit_px = float(ex["avgPx"])
        direction = "多" if ex_pos == "long" else "空"
        pnl = float(ex.get("pnl", 0))
        fee = float(ex.get("fee", 0))
        
        trades.append({
            "symbol": ex_sym.replace("-USDT-SWAP", ""),
            "direction": direction,
            "entry": entry_px,
            "exit": exit_px,
            "pnl": pnl,
            "fee": fee,
            "entry_time": en["cTime"],
            "exit_time": ex["cTime"],
            "lever": ex.get("lever", "1"),
            "posSide": ex_pos
        })
    
    return trades

def analyze_trade_prices(trade):
    """获取交易期间K线，计算最佳止盈止损位"""
    sym = trade["symbol"] + "-USDT-SWAP"
    entry_ts = int(trade["entry_time"]) / 1000
    entry_px = trade["entry"]
    direction = trade["direction"]
    
    # 获取入场后的1H K线 (用公开API，不用签名)
    url = f"{OKX_BASE}/api/v5/market/candles"
    params = {"instId": sym, "bar": "1H", "limit": "200"}
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=15)
            result = resp.json()
            break
        except:
            if attempt < 2: time.sleep(2)
            else: return None
    
    if result.get("code") != "0" or not result.get("data"):
        return None
    
    candles = []
    for c in result["data"]:
        ts_ms = int(c[0])
        candles.append({"ts": ts_ms/1000, "h": float(c[2]), "l": float(c[3]), "c": float(c[4])})
    candles.reverse()
    
    # 找入场后的K线
    post_candles = [c for c in candles if c["ts"] >= entry_ts]
    if len(post_candles) < 2:
        return None
    
    mae = 0     # 最大浮亏(正数%)
    mfe = 0     # 最大浮盈(正数%)
    mae_px = entry_px
    mfe_px = entry_px
    
    for c in post_candles:
        if direction == "多":
            pct_low = (entry_px - c["l"]) / entry_px * 100
            pct_high = (c["h"] - entry_px) / entry_px * 100
            if pct_low > mae:
                mae = pct_low
                mae_px = c["l"]
            if pct_high > mfe:
                mfe = pct_high
                mfe_px = c["h"]
        else:
            pct_high = (c["h"] - entry_px) / entry_px * 100 * -1  # 做空：涨=亏损
            pct_low = (entry_px - c["l"]) / entry_px * 100       # 做空：跌=盈利
            if pct_high > mae:
                mae = pct_high
                mae_px = c["h"]
            if pct_low > mfe:
                mfe = pct_low
                mfe_px = c["l"]
    
    return {
        "mae_pct": round(mae, 2),
        "mfe_pct": round(mfe, 2),
        "mae_px": round(mae_px, 6),
        "mfe_px": round(mfe_px, 6),
        "actual_pnl": trade["pnl"],
        "exit_pct": round((trade["exit"] - entry_px) / entry_px * 100 * (1 if direction=="多" else -1), 2),
        "bars": len(post_candles)
    }

def find_optimal_stops(results):
    """在回撤≤34%约束下找最大利润位"""
    valid = [r for r in results if r and r["mae_pct"] < 34]
    if not valid:
        return None
    
    maes = sorted([r["mae_pct"] for r in valid])
    mfes = sorted([r["mfe_pct"] for r in valid])
    
    # 止损分析: 各阈值下的存活率和利润
    stops = []
    for sl in [1, 2, 3, 4, 5, 8, 10, 12, 15, 20, 25, 30]:
        survived = [r for r in valid if r["mae_pct"] <= sl]
        if not survived:
            continue
        avg_tp = sum(r["mfe_pct"] for r in survived) / len(survived)
        pct_survived = len(survived) / len(valid) * 100
        # 如果存活的交易都按最大涨幅止盈
        stops.append({
            "stop_loss": sl,
            "survived": len(survived),
            "survive_rate": round(pct_survived, 1),
            "avg_max_profit": round(avg_tp, 2)
        })
    
    # 最佳: 存活率最高的同时利润最大
    best = max(stops, key=lambda s: s["avg_max_profit"] * s["survive_rate"])
    
    return {
        "total_trades": len(valid),
        "mae_median": maes[len(maes)//2],
        "mfe_median": mfes[len(mfes)//2],
        "stop_loss_analysis": stops,
        "best": best
    }

def main():
    print("📊 项目4: 交易订单优化分析\n")
    
    # 尝试从OKX获取
    print("🔌 连接OKX API...")
    orders = get_filled_orders()
    
    if not orders:
        print("⚠️ 无法获取订单数据，请确认API权限包含交易历史")
        # 尝试从本地文件
        local = os.path.join(PROJECT_ROOT, "okx_data", "trades.csv")
        if os.path.exists(local):
            print(f"📂 使用本地文件: {local}")
            orders = []
            with open(local, encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    orders.append(row)
        else:
            print("📂 也未找到本地trades.csv")
            print("\n💡 请: 1) 检查OKX API权限 2) 或将交易CSV放到 okx_data/trades.csv")
            return
    
    # 配对成完整交易
    trades = group_trades(orders)
    print(f"\n📋 完整交易: {len(trades)} 笔")
    
    if not trades:
        print("⚠️ 无法配对交易")
        return
    
    # 逐笔分析
    print("📈 逐笔分析价格走势...")
    results = []
    for i, t in enumerate(trades):
        r = analyze_trade_prices(t)
        if r:
            r["symbol"] = t["symbol"]
            r["direction"] = t["direction"]
            r["entry"] = t["entry"]
            r["exit"] = t["exit"]
            r["pnl"] = t["pnl"]
            results.append(r)
        if (i+1) % 10 == 0:
            print(f"  {i+1}/{len(trades)}...")
        time.sleep(0.15)
    
    if not results:
        print("⚠️ 无有效K线数据")
        return
    
    # 优化分析
    opt = find_optimal_stops(results)
    if not opt:
        return
    
    print(f"\n{'='*60}")
    print(f"📊 交易优化结果 ({opt['total_trades']} 笔, MAE<34%)")
    print(f"{'='*60}")
    print(f"  MAE中位: {opt['mae_median']}% | MFE中位: {opt['mfe_median']}%")
    print(f"\n🎯 止损分析 (回撤<34%的交易):")
    print(f"  {'止损%':>6} {'存活':>5} {'存活率':>7} {'平均最大利润':>10}")
    for s in opt["stop_loss_analysis"]:
        print(f"  {s['stop_loss']:>6}% {s['survived']:>5} {s['survive_rate']:>6}% {s['avg_max_profit']:>+9}%")
    
    print(f"\n🏆 推荐: 止损{opt['best']['stop_loss']}% 存活率{opt['best']['survive_rate']}% 平均最大利润{opt['best']['avg_max_profit']:+.2f}%")
    
    # 保存
    with open(OUTPUT, "w") as f:
        json.dump({"trades": results, "optimization": opt}, f, ensure_ascii=False, indent=2)
    print(f"\n✅ {OUTPUT}")

if __name__ == "__main__":
    main()
