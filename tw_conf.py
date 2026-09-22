#!/usr/bin/env python3
# TrendWatch 配置与数据层（2026-09-04 从 scan_trend.py 拆分）
import requests, time, os, json
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pushed_state.json")

SWING_P = 5  # swing 判定左右窗口（根）
MIN_SWING_PCT_15M = 0.003 # 15m 结构最小摆幅（相对价格，0.3%）——15m 方向共振标注用（2026-09-05 新增）
MIN_SWING_PCT_1H = 0.005  # 1h 结构最小摆幅（相对价格，0.5%）——1h 方向参与「与日线同向」门（2026-09-01 由 0.3% 收紧至 0.5%）
MIN_SWING_PCT_4H = 0.0075 # 4h 结构最小摆幅（相对价格，0.75%），取 1h(0.5%) 与 1d(1%) 之间
                          # 2026-09-14 引入（4h 同向门）→ 09-19 门撤销时移除 → 09-21「4H 型」启用时回归 tw_conf
                          # → 09-22 统一为单一策略后，4h 结构**只用于页面展示**（判定只用 4h SRSI），此阈值仅供展示口径。
MIN_SWING_PCT_1D = 0.01   # 1d 结构最小摆幅（相对价格，1%）——日线级：找机会 + 定方向（2026-09-19 恢复 1h 同向共振后，1d 仍是方向锚）
TOP_N = 10                # 每日最多推送前 N 个（按信号极端度排序取最强），降低噪音（2026-09-05 新增）

# ---- SRSI 极值区（2026-09-02 改版：类型1 只看 1h，类型2 只看 1d）----
SRSI_LOW = 20             # SRSI 低于此值为超卖
SRSI_HIGH = 80            # SRSI 高于此值为超买
NEAR_LEVEL_PCT = 0.015    # 价格贴近日线关键位：做多近 swing low 支撑 / 做空近 swing high 阻力，距离 <=1.5%（双向贴靠，2026-09-07 恢复 9/5 推送版）
# CONFIRM_*（CHoCH 逆势 1h 确认）已于 2026-09-05 移除：系统改为纯顺势，1h 同向共振即确认，不再需要逆势突破确认。

# ---- 统一策略（2026-09-22 起：原先并列的「1d 型（回调/趋势）」与「4H 型」合并为**单一策略**）----
# 一句话：**以日线为锚（方向 + 位置 + 触发），1 小时确认方向，4 小时做反向保险。**
# 判定实现见 tw_calc.classify（唯一入口，kind 记为「日线」）。
#   固定门（系统既有质量门，不变）：
#       ADX(1h) > ADX_THRESHOLD ｜ ATR/价 ∈ (ATR_MIN_RATIO, ATR_MAX_RATIO)
#       ｜ 目标空间 > MIN_SPACE_PCT（目标取日线最近 swing 高/低）
#   策略四条件（须全部满足）：
#       ① 1日与1小时方向一致：d1d ≠ 0 且 d1h == d1d（任一横盘或方向相反 → 淘汰）
#       ② 日线在关键位置：多贴日线 swing low / 空贴日线 swing high，±NEAR_LEVEL_PCT
#       ③ 日线 SRSI 超买超卖位：多 s1 < SRSI_LOW，空 s1 > SRSI_HIGH
#       ④ 4小时 SRSI 不在反向极值：多 s4h ≤ SRSI_HIGH，空 s4h ≥ SRSI_LOW
#   阈值全部复用上面既有的常量，不另设一份。
# 产出量实测（2026-09-22，101 币 × 1111 个 4h 时点滚动回测）：本口径 0 命中；
#   逐门单独通过率：ADX 77% ｜ ATR 61% ｜ 1d 有方向 50% ｜ **1d/1h 同向仅 7.5%** ｜
#   贴日线关键位 ±1.5% 3.4% ｜ 1d SRSI 极端 22% ｜ 4h 不反向 39% ｜ 空间>10% 36%。
#   最大瓶颈是「1d/1h 方向一致」；若日后嫌推送太少，先动这一条（放宽为「1h 不反向」），
#   实测可把频率从 0% 提到约 0.9%（同批样本）。
# 去重键与推送排序见 scan_trend.py（键为「币种|日线多/空」）。

# ---- 质量门阈值（沿用主策略/早期版既定标准，要求不变） ----
ADX_PERIOD = 14
ADX_THRESHOLD = 20      # 1h ADX > 20 确认趋势动能足够
ATR_PERIOD = 14
ATR_MIN_RATIO = 0.005   # ATR/价格 > 0.5%，波动足够才有交易空间（下界，2026-09-07 恢复 9/5 区间要求）
ATR_MAX_RATIO = 0.02    # ATR/价格 < 2%，波动过大(风险失控)则剔除（上界）
MIN_SPACE_PCT = 10.0    # 目标空间下限：目标位（日线 swing 高/低）到现价的空间必须 > 10%（2026-09-13 新增，重新启用空间硬门）
# 注：MIN_SPACE_ATR / space_ok 仍维持移除状态；空间判定只用上面的百分比门。
WICK_LOOKBACK = 20      # 最近 20 根 1h K 线评估插针
WICK_AVG_MAX = 6.0      # 平均影线占比上限（放宽：原 4.0 对 1h K 线过严，单根插针即误杀）
WICK_SPIKE_MAX = 10.0    # 单根最大影线占比上限（放宽：保留对真实插针泵/砸的过滤）
# 注：2026-09-05 起系统改为纯顺势（无逆势反转类），插针门统一用上述阈值，不再区分回调/反转。

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
