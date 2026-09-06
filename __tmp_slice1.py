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

ALERT_THRESHOLD = 9

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

FIXED_FILE = os.path.join(PROJECT_ROOT, "FIXED_SYMBOLS.txt")
fixed_list = []
if os.path.exists(FIXED_FILE):
    with open(FIXED_FILE) as f:
        fixed_list = [l.strip() for l in f if l.strip() and not l.startswith('#')]

# 2026-09-06 起：币池不再读 SYMBOLS.txt 热点，改为「自选(FIXED) ∪ OKX 近7天成交币」，
# 由 main() 内 build_pool() 动态组装；此处仅保留自选作为兜底。
SYMBOLS = list(fixed_list)

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()
PUSHPLUS_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".pushplus_token")
if not PUSHPLUS_TOKEN and os.path.exists(PUSHPLUS_TOKEN_FILE):
    with open(PUSHPLUS_TOKEN_FILE) as f:
        PUSHPLUS_TOKEN = f.read().strip()

WEBHOOK_FILE = os.path.join(PROJECT_ROOT, ".wecom_webhook")
WECOM_WEBHOOK = ""
if os.path.exists(WEBHOOK_FILE):
    with open(WEBHOOK_FILE) as f:
        WECOM_WEBHOOK = f.read().strip()
elif os.environ.get("WECOM_WEBHOOK"):
    WECOM_WEBHOOK = os.environ["WECOM_WEBHOOK"]

OKX_API_KEY = os.environ.get("OKX_API_KEY", "6d758f5a-4ea7-44d1-bc56-5b8659263b1a")
OKX_SECRET = os.environ.get("OKX_SECRET", "760BEBD659B861D17B5DE6DF7112E5CF")
OKX_PASSPHRASE = os.environ.get("OKX_PASSPHRASE", "1qaz2wsxcJJ!")
import hmac as _hmac, base64 as _b64, hashlib as _hashlib

def _okx_sign(ts, method, path, body=""):
    return _b64.b64encode(_hmac.new(OKX_SECRET.encode(), (ts+method+path+body).encode(), _hashlib.sha256).digest()).decode()

def _okx_req(method, path, params=None):
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
    qs = "?" + "&".join(f"{k}={v}" for k,v in (params or {}).items()) if params else ""
    h = {"OK-ACCESS-KEY":OKX_API_KEY,"OK-ACCESS-SIGN":_okx_sign(ts,method,path+qs),
         "OK-ACCESS-TIMESTAMP":ts,"OK-ACCESS-PASSPHRASE":OKX_PASSPHRASE,"Content-Type":"application/json"}
    for _ in range(3):
        try:
            r = requests.get(f"{OKX_BASE}{path}{qs}", headers=h, timeout=15)
            return r.json()
        except: time.sleep(1)
    return {}

def fetch_recent_traded_symbols(days=7, max_pages=5):
    """枚举 OKX 近 N 天成交过的 USDT 永续币种（orders-history 不带 instId，分页拉全）。
    返回去重后的 instId 列表（如 ['ORDI-USDT-SWAP', ...]）；失败返回 []。"""
    end_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    begin_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    syms = []
    seen = set()
    after = None
    for _ in range(max_pages):
        params = {"instType": "SWAP", "state": "filled",
                  "begin": str(begin_ts), "end": str(end_ts), "limit": "100"}
        if after:
            params["after"] = str(after)
        data = _okx_req("GET", "/api/v5/trade/orders-history", params)
        if data.get("code") != "0" or not data.get("data"):
            break
        batch = data["data"]
        for o in batch:
            inst = o.get("instId", "")
            if "USDT-SWAP" in inst and inst not in seen:
                seen.add(inst)
                syms.append(inst)
        if len(batch) < 100:
            break
        after = batch[-1].get("ordId")
        time.sleep(0.12)
    return syms


def fetch_recent_trades(hours=4):
    end_ts = int(datetime.now(timezone.utc).timestamp()*1000)
    begin_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()*1000)
    trades = []
    for sym in SYMBOLS:
        data = _okx_req("GET", "/api/v5/trade/orders-history",
            {"instType":"SWAP","instId":sym,"ordType":"market","state":"filled",
             "begin":str(begin_ts),"end":str(end_ts),"limit":"20"})
        if data.get("code")=="0" and data.get("data"):
            for o in data["data"]:
                trades.append({"sym":sym.replace("-USDT-SWAP",""),"time":o["cTime"],
                    "side":o["side"],"px":float(o["avgPx"]),"sz":float(o["accFillSz"])})
        time.sleep(0.15)
    trades.sort(key=lambda x:x["time"])
    return trades
