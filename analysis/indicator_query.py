#!/usr/bin/env python3
"""
实时指标查询工具
查询任意品种当前的DMI/SRSI/ADX/摆动点等指标值
用法: python analysis/indicator_query.py [品种]  或  python analysis/indicator_query.py  列出支持列表
"""
import warnings
warnings.filterwarnings("ignore")
import os, sys, time, urllib3
urllib3.disable_warnings()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# 复用共享指标库
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..'))  
from shared.indicators import *

# 历史记录文件
SCAN_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "okx_data", "scans")

def query_symbol(sym):
    """查询单个品种当前指标值"""
    if not sym.endswith("-USDT-SWAP"):
        sym = f"{sym.upper()}-USDT-SWAP"
    
    name = sym.replace("-USDT-SWAP", "").replace("-USDT", "")
    print(f"\n🔍 {name}")
    print(f"{'='*60}")
    print(f"{'TF':<6} {'DMI':>4} {'ADX':>6} {'SRSI':>6} {'EMA':>5} {'MACD':>8} {'BB(%B)':>7} {'CCI':>6} {'SW':>4}")
    print("-" * 60)
    
    for tf_label, bar in [("1H", "1H"), ("4H", "4H"), ("1D", "1D")]:
        candles = fetch_ohlcv(sym, bar, limit=200)
        if not candles or len(candles) < 30:
            print(f"{tf_label:<6} 数据不足")
            continue
        
        closes = [c["c"] for c in candles]
        dmi_dir, adx_val, _ = trend_dmi(candles)
        srsi_val = calc_stoch_rsi(closes)
        sw_dir = trend_swing(candles)
        ema_dir = trend_ema_cross(candles)
        macd_val, _, _ = calc_macd(closes)
        _, _, _, _, bb_b = calc_bollinger(closes)
        cci_val = calc_cci(candles)
        
        dmi_icon = "🟢" if dmi_dir == "多" else ("🔴" if dmi_dir == "空" else "⚪")
        srsi_fmt = f"{srsi_val:.1f}" if srsi_val else "N/A"
        adx_fmt = f"{adx_val:.1f}" if adx_val else "N/A"
        macd_fmt = f"{macd_val:.4f}" if macd_val else "N/A"
        bb_fmt = f"{bb_b:.2f}" if bb_b else "N/A"
        cci_fmt = f"{cci_val:.0f}" if cci_val else "N/A"
        
        print(f"{tf_label:<6} {dmi_icon} {dmi_dir:<3} {adx_fmt:>6} {srsi_fmt:>6} {ema_dir:>5} {macd_fmt:>8} {bb_fmt:>7} {cci_fmt:>6} {sw_dir:>4}")
    
    # 评分
    print(f"\n📊 评分: DMI纯={calc_current_score(sym, 'DMI')}  ADX加权={calc_current_score(sym, 'ADX')}  摆动点={calc_current_score(sym, 'SW')}")
    print("-" * 60)

def calc_current_score(sym, mode='DMI'):
    """快速计算当前评分"""
    trends = {}; trends_sw = {}; srsis = {}; adxs = {}
    for tf_label, bar in [("1H", "1H"), ("4H", "4H"), ("1D", "1D")]:
        candles = fetch_ohlcv(sym, bar, limit=200)
        if not candles or len(candles) < 30:
            trends[tf_label] = "N/A"; trends_sw[tf_label] = "N/A"
            srsis[tf_label] = None; adxs[tf_label] = None
            continue
        closes = [c["c"] for c in candles]
        dmi_dir, adx_val, _ = trend_dmi(candles)
        trends[tf_label] = dmi_dir
        trends_sw[tf_label] = trend_swing(candles)
        srsis[tf_label] = calc_stoch_rsi(closes)
        adxs[tf_label] = adx_val
        time.sleep(0.15)
    
    (dmi_b, dmi_s), (adx_b, adx_s), (sw_b, sw_s) = calc_multi_score(trends, trends_sw, srsis, adxs)
    if mode == 'DMI': return f"多{dmi_b} 空{dmi_s}"
    if mode == 'ADX': return f"多{adx_b:.1f} 空{adx_s:.1f}"
    return f"多{sw_b} 空{sw_s}"

def show_history_summary():
    """显示历史数据汇总"""
    import glob, csv
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "*.csv")), reverse=True)
    if not files:
        print("暂无历史数据")
        return
    
    print(f"\n📁 历史扫描记录 ({len(files)} 天)")
    print(f"{'日期':<12} {'扫描次数':>8} {'品种数':>6} {'高分预警':>8}")
    print("-" * 40)
    
    for fp in files[:14]:
        date = os.path.basename(fp).replace('.csv', '')
        with open(fp) as f:
            rows = list(csv.DictReader(f))
            scans = len(set(r['timestamp'] for r in rows))
            syms = len(set(r['symbol'] for r in rows))
            alerts = sum(1 for r in rows if int(r.get('dmi_bull',0)) >= 6 or int(r.get('dmi_bear',0)) >= 6)
        print(f"{date:<12} {scans:>8} {syms:>6} {alerts:>8}")

def show_recent_alerts(days=3):
    """显示最近几天的预警"""
    import glob, csv
    from datetime import datetime, timedelta
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "*.csv")), reverse=True)[:days]
    
    print(f"\n⚠️ 最近{days}天高分预警")
    alerts_found = []
    for fp in files:
        with open(fp) as f:
            for r in csv.DictReader(f):
                bull = int(r.get('dmi_bull', 0))
                bear = int(r.get('dmi_bear', 0))
                if bull >= 6 or bear >= 6:
                    nm = r['symbol'].replace('-USDT-SWAP','').replace('-USDT','')
                    ts = r['timestamp']
                    d = f"DMI:多{bull}/空{bear}" if bull>=bear else f"DMI:多{bull}/空{bear}"
                    alerts_found.append(f"  {ts} {'🟢' if bull>=bear else '🔴'} {nm:<8} {d}")
    
    if alerts_found:
        for a in alerts_found[-20:]:
            print(a)
    else:
        print("  无预警")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        query_symbol(sys.argv[1])
    else:
        show_history_summary()
        show_recent_alerts()
        print(f"\n💡 用法: python analysis/indicator_query.py BTC")
        print(f"   支持品种: 任意OKX永续合约 (自动加 -USDT-SWAP)")
