#!/usr/bin/python3
# TrendWatch 配置与数据层（2026-09-04 从 scan_trend.py 拆分，逻辑未改）
import requests, time, os, json
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pushed_state.json")

SWING_P = 5  # swing 判定左右窗口（根）
MIN_SWING_PCT_1H = 0.005  # 1h 结构最小摆幅（相对价格，0.5%）——过滤噪声小波动（2026-09-01 由 0.3% 收紧至 0.5%）
MIN_SWING_PCT_4H = 0.005  # 4h 结构最小摆幅（相对价格，0.5%）——过滤噪声小波动
MIN_SWING_PCT_1D = 0.01   # 1d 结构最小摆幅（相对价格，1%）——日线级，过滤噪声（2026-09-01 新增方向过滤用）
MIN_SWING_PCT_15M = 0.003 # 15m 结构最小摆幅（相对价格，0.3%）——15m 同方向共振过滤用（2026-09-05 新增）
TOP_N = 10                # 每日最多推送前 N 个（按信号极端度排序取最强），降低噪音（2026-09-05 新增）

# ---- SRSI 极值区（2026-09-02 改版：类型1 只看 1h，类型2 只看 1d）----
SRSI_LOW = 20             # SRSI 低于此值为超卖
SRSI_HIGH = 80            # SRSI 高于此值为超买
NEAR_LEVEL_PCT = 0.015    # 价格与日线关键位(swing 点)的相对距离 <= 1.5% 视为「遇到阻力/支撑」
CONFIRM_SWING_P = 2       # 1h 确认专用 swing 窗口（比 SWING_P=5 小，否则最新一次反弹高点识别不到）
CONFIRM_LOOKBACK = 20     # 1h 确认在最近 20 根内找「本段起点」（最低点 / 最高点）
CONFIRM_MAX_BARS_1H = 4   # 类型2 的 1h 突破必须发生在最近 4 根内（避免追已经跑远的）

# ---- 质量门阈值（沿用主策略/早期版既定标准，要求不变） ----
ADX_PERIOD = 14
ADX_THRESHOLD = 20      # 1h ADX > 20 确认趋势动能足够
ATR_PERIOD = 14
ATR_MIN_RATIO = 0.005   # ATR/价格 > 0.5%，波动足够才有交易空间（可微调）
WICK_LOOKBACK = 20      # 最近 20 根 1h K 线评估插针
WICK_AVG_MAX = 6.0      # 平均影线占比上限（放宽：原 4.0 对 1h K 线过严，单根插针即误杀）
WICK_SPIKE_MAX = 10.0    # 单根最大影线占比上限（放宽：保留对真实插针泵/砸的过滤）
# 类型2 反转专用插针门（2026-09-02 放宽）：反转行情本身由暴跌/插针/反抽组成，
# 长影线是常态而非异常，沿用严格门会把最典型的反转信号误杀（同类事故见 2026-08-31）。
WICK_AVG_MAX_REV = 10.0    # 反转类平均影线占比上限（回调类 6 → 10）
WICK_SPIKE_MAX_REV = 16.0  # 反转类单根最大占比上限（回调类 10 → 16）

# ---- 股票相关币种黑名单（不推送）----
# 用户要求（2026-08-25）：TrendWatch 不推荐股票相关币种。
# 两类：①代币化股票（常见美股 ticker）；②名称含股票关键词。
STOCK_TICKERS = {
    # 科技 / 美股龙头
    "TSLA","AAPL","NVDA","AMZN","GOOGL","GOOG","META","FB","MSFT","NFLX",
    "COIN","TWTR","NIO","BABA","JD","PDD","BIDU","XPEV","LCID","RIVN","PLTR",
    "AMD","INTC","IBM","ORCL","CRM","ADBE","PYPL","UBER","LYFT","SNAP","SQ",
    "SHOP","ROKU","PINS","Z","DOCU","OKTA","NOW","TEAM","CRWD","NET","ZS",
    "SNOW","DDOG","MDB","TWLO","ZM","CHWY","ETSY","MRNA","BNTX","PFE","JNJ",
    "KO","PEP","MCD","SBUX","DIS","BA","GE","CAT","WMT","TGT","HD","LOW",
    "COST","XOM","CVX","BAC","JPM","GS","WFC","C","V","MA",
    # 指数 / ETF 类
    "SPY","QQQ","DIA","VOO","IWM","ARKK","UVXY","VIX",
}
STOCK_KEYWORDS = ("STOCK", "SHARE", "EQUITY", "STK", "股票")

def is_stock_related(name: str) -> bool:
    """判断币种是否为股票相关（代币化股票或名称含股票关键词），命中则不推送。"""
    n = name.upper()
    if n in STOCK_TICKERS:
        return True
    return any(k in n for k in STOCK_KEYWORDS)


def cst_date():
    """当前 CST(UTC+8) 日期字符串，用于按天去重"""
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def load_pushed():
    """读取今天已推送过的币种集合（仅保留当天键，跨天自动重置）"""
    today = cst_date()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                st = json.load(f)
            if isinstance(st, dict):
                return set(st.get(today, []))
        except Exception:
            pass
    return set()


def get_candles(inst, bar, limit=100):
    for _ in range(4):
        try:
            r = requests.get(f"{OKX}/api/v5/market/candles",
                             params={"instId": inst, "bar": bar, "limit": limit}, timeout=12)
            if r.status_code == 429:
                time.sleep(2.0); continue  # 触发频率限制，退避后重试
            d = r.json()
            if d.get("code") == "0":
                candles = []
                for c in d["data"]:
                    candles.append({"h": float(c[2]), "l": float(c[3]),
                                    "c": float(c[4]), "o": float(c[1]), "v": float(c[5])})
                candles.reverse()
                return candles
        except Exception:
            time.sleep(0.5)
        time.sleep(0.06)  # 轻量限流，避免触发 OKX 公共 API 频率限制
    return None
