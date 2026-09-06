#!/usr/bin/env python3
"""
OKX 策略监控 v2.1（2026-09-06：币池=自选+近7天成交，去热点/每日候选）
- 方向: DMI/ADX (Wilder) + 摆动点+ATR (对比)
- StochRSI: (K+D)/2, Wilder平滑
- 评分: 方向分 1H=1, 4H=1, 1D=2 + SRSI极端值加分
- 调度: 每15分钟扫描 → 日间(6-24)整点推送全量 / 夜间(0-6)仅高分预警
- 文档: 所有扫描结果存入 okx_data/scans/YYYY-MM-DD.csv 供参数验证
- 成交量分布: 基于1H K线计算POC/VA作为支撑阻力参考
- 币池(2026-09-06): 只推 FIXED_SYMBOLS.txt 自选 + OKX 近7天成交过的币（orders-history 枚举），
  不再读 SYMBOLS.txt 热点前2、不再推送每日候选推荐（SHIB/GALA/DOGE）。
"""
import warnings
warnings.filterwarnings("ignore")
import requests
import time
import json
import os
import sys
import csv
from datetime import datetime, timezone, timedelta

OKX_BASE = "https://www.okx.com"
DIR_SCORE = {"1H": 1, "4H": 2, "1D": 3}
def fetch_ohlcv(symbol, bar, limit=200, retries=3):
    url = f"{OKX_BASE}/api/v5/market/candles"
    for attempt in range(retries):
        try:
            resp = requests.get(url, params={"instId": symbol, "bar": bar, "limit": limit}, timeout=15)
            d = resp.json()
            if d.get("code") == "0":
                candles = []
                for c in d["data"]:
                    candles.append({
                        "h": float(c[2]), "l": float(c[3]), "c": float(c[4]),
                        "o": float(c[1]), "v": float(c[5])
                    })
                candles.reverse()
                return candles
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                return None
    return None

# 2026-09-06：CANDIDATES + scan_candidates（每日候选推荐）已移除——币池限定为自选+近7天成交币。
