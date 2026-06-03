#!/usr/bin/env python3
"""
指标两两组合胜率计算
输出: okx_data/pairwise_winrate.json (供 viewer.html 可视化)
"""
import csv
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BT_FILE = os.path.join(PROJECT_ROOT, "okx_data", "backtest_results.csv")
OUTPUT = os.path.join(PROJECT_ROOT, "okx_data", "pairwise_winrate.json")

# ── 指标条件定义 ──
CONDITIONS = {
    "DMI_1H多": lambda r: r.get("dmi_1h") == "多",
    "DMI_1H空": lambda r: r.get("dmi_1h") == "空",
    "DMI_4H多": lambda r: r.get("dmi_4h") == "多",
    "DMI_4H空": lambda r: r.get("dmi_4h") == "空",
    "DMI_1D多": lambda r: r.get("dmi_1d") == "多",
    "DMI_1D空": lambda r: r.get("dmi_1d") == "空",
    "EMA_1H多": lambda r: r.get("ema_1h") == "多",
    "EMA_1H空": lambda r: r.get("ema_1h") == "空",
    "EMA_4H多": lambda r: r.get("ema_4h") == "多",
    "EMA_4H空": lambda r: r.get("ema_4h") == "空",
    "EMA_1D多": lambda r: r.get("ema_1d") == "多",
    "EMA_1D空": lambda r: r.get("ema_1d") == "空",
    "CCI_1H多": lambda r: r.get("cci_dir_1h") == "多",
    "CCI_1H空": lambda r: r.get("cci_dir_1h") == "空",
    "CCI_4H多": lambda r: r.get("cci_dir_4h") == "多",
    "CCI_4H空": lambda r: r.get("cci_dir_4h") == "空",
    "CCI_1D多": lambda r: r.get("cci_dir_1d") == "多",
    "CCI_1D空": lambda r: r.get("cci_dir_1d") == "空",
    "SW_1H多": lambda r: r.get("sw_1h") == "多",
    "SW_1H空": lambda r: r.get("sw_1h") == "空",
    "SW_4H多": lambda r: r.get("sw_4h") == "多",
    "SW_4H空": lambda r: r.get("sw_4h") == "空",
    "SW_1D多": lambda r: r.get("sw_1d") == "多",
    "SW_1D空": lambda r: r.get("sw_1d") == "空",
    "BOLL_1H多": lambda r: r.get("boll_1h") == "多",
    "BOLL_1H空": lambda r: r.get("boll_1h") == "空",
    "BOLL_4H多": lambda r: r.get("boll_4h") == "多",
    "BOLL_4H空": lambda r: r.get("boll_4h") == "空",
    "BOLL_1D多": lambda r: r.get("boll_1d") == "多",
    "BOLL_1D空": lambda r: r.get("boll_1d") == "空",
    "SRSI_1H>80": lambda r: sval(r, "srsi_1h", ">", 80),
    "SRSI_1H<20": lambda r: sval(r, "srsi_1h", "<", 20),
    "SRSI_4H>80": lambda r: sval(r, "srsi_4h", ">", 80),
    "SRSI_4H<20": lambda r: sval(r, "srsi_4h", "<", 20),
    "SRSI_1D>80": lambda r: sval(r, "srsi_1d", ">", 80),
    "SRSI_1D<20": lambda r: sval(r, "srsi_1d", "<", 20),
    "ADX_1H>25": lambda r: sval(r, "adx_1h", ">", 25),
    "ADX_4H>25": lambda r: sval(r, "adx_4h", ">", 25),
    "ADX_1D>25": lambda r: sval(r, "adx_1d", ">", 25),
    "CCI_1H>100": lambda r: sval(r, "cci_1h", ">", 100),
    "CCI_1H<-100": lambda r: sval(r, "cci_1h", "<", -100),
    "CCI_4H>100": lambda r: sval(r, "cci_4h", ">", 100),
    "CCI_4H<-100": lambda r: sval(r, "cci_4h", "<", -100),
    "CCI_1D>100": lambda r: sval(r, "cci_1d", ">", 100),
    "CCI_1D<-100": lambda r: sval(r, "cci_1d", "<", -100),
    "BB_1H>0.7": lambda r: sval(r, "bbp_1h", ">", 0.7),
    "BB_1H<0.3": lambda r: sval(r, "bbp_1h", "<", 0.3),
    "BB_4H>0.7": lambda r: sval(r, "bbp_4h", ">", 0.7),
    "BB_4H<0.3": lambda r: sval(r, "bbp_4h", "<", 0.3),
    "BB_1D>0.7": lambda r: sval(r, "bbp_1d", ">", 0.7),
    "BB_1D<0.3": lambda r: sval(r, "bbp_1d", "<", 0.3),
}

def sval(r, key, op, threshold):
    try:
        v = float(r.get(key, None) or 0)
        if op == ">": return v > threshold
        return v < threshold
    except:
        return False

def load_backtest():
    if not os.path.exists(BT_FILE):
        return []
    rows = []
    with open(BT_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["win_24H"] = True if row.get("win_24H") == "1" else (False if row.get("win_24H") == "0" else None)
            row["win_12H"] = True if row.get("win_12H") == "1" else (False if row.get("win_12H") == "0" else None)
            row["win_4H"] = True if row.get("win_4H") == "1" else (False if row.get("win_4H") == "0" else None)
            if row["win_24H"] is not None:  # 只统计有结果的信号
                rows.append(row)
    return rows

def compute_pairwise():
    """计算所有指标两两组合的胜率"""
    rows = load_backtest()
    if not rows:
        print("⚠️ 无回测数据")
        return [], []

    names = list(CONDITIONS.keys())
    n = len(names)
    
    # 分组: 方向指标 vs 数值指标
    direction_names = [k for k in names if any(x in k for x in ["DMI_","EMA_","SW_","CCI_dir","BOLL_"])]
    value_names = [k for k in names if any(x in k for x in ["SRSI_","ADX_","CCI_1H>","CCI_4H>","CCI_1D>","CCI_1H<","CCI_4H<","CCI_1D<","BB_"])]
    
    # 全组合矩阵 (用于热力图)
    matrix = []
    for i in range(n):
        row_data = []
        for j in range(n):
            if i == j:
                # 单一条件
                sigs = [r for r in rows if CONDITIONS[names[i]](r)]
            else:
                # 两个条件 AND
                sigs = [r for r in rows if CONDITIONS[names[i]](r) and CONDITIONS[names[j]](r)]
            
            total = len(sigs)
            wins = sum(1 for r in sigs if r["win_24H"] is True)
            winrate = round(wins / total * 100, 1) if total > 0 else 0
            row_data.append({"total": total, "wins": wins, "wr": winrate})
        matrix.append(row_data)
    
    # Top组合列表 (排除自身，按胜率排序，至少有10个样本)
    top_pairs = []
    for i in range(n):
        for j in range(i+1, n):
            sigs = [r for r in rows if CONDITIONS[names[i]](r) and CONDITIONS[names[j]](r)]
            total = len(sigs)
            if total < 10:
                continue
            wins = sum(1 for r in sigs if r["win_24H"] is True)
            wr = round(wins / total * 100, 1)
            # 也看4H和12H
            wins_4h = sum(1 for r in sigs if r["win_4H"] is True)
            wins_12h = sum(1 for r in sigs if r["win_12H"] is True)
            wr_4h = round(wins_4h / total * 100, 1)
            wr_12h = round(wins_12h / total * 100, 1)
            top_pairs.append({
                "c1": names[i], "c2": names[j],
                "total": total, "wins": wins, "wr": wr,
                "wr_4h": wr_4h, "wr_12h": wr_12h
            })
    top_pairs.sort(key=lambda x: x["wr"], reverse=True)
    
    return {
        "conditions": names,
        "matrix": matrix,
        "top_pairs": top_pairs[:40]
    }

if __name__ == "__main__":
    data = compute_pairwise()
    if data:
        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ 组合胜率已计算: {len(data['top_pairs'])} 对 | matrix {len(data['conditions'])}×{len(data['conditions'])}")
        print(f"   → {OUTPUT}")
        print(f"\n🏆 Top 10 组合 (24H胜率):")
        for i, p in enumerate(data["top_pairs"][:10]):
            print(f"  {i+1}. {p['c1']} + {p['c2']} → {p['wr']}% ({p['total']}个) | 4H:{p['wr_4h']}% 12H:{p['wr_12h']}%")
    else:
        # 空输出
        empty_data = {"conditions": [], "matrix": [], "top_pairs": []}
        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(empty_data, f, ensure_ascii=False)
        print("⚠️ 无数据")
