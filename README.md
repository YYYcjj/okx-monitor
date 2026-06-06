# OKX 策略监控 & 模拟交易系统

14币种 DMI+StochRSI 多空评分 + 1H SuperTrend 入场 + 四维关键区间止盈，PushPlus 推送 + 自动模拟交易。

## 项目结构

```
okx-monitor/
├── strategy_engine.py           # 🆕 策略执行引擎（扫描+信号+下单+推送）
├── KEY_ZONE_THEORY.md           # 🆕 关键区间识别理论文档
├── monitor/                     # 实时监控提醒
│   └── okx_monitor.py           #   每15min扫描 → 微信推送
├── analysis/                    # 历史数据分析
│   ├── backtest.py              #   回测引擎
│   ├── analyze_trades.py        #   交易记录分析
│   └── build_viewer.py          #   数据查看器
├── strategy/                    # 策略脚本
│   ├── strategy_a_srsi_cci.pine #   策略A: 精准狙击
│   ├── strategy_b_bb.pine       #   策略B: 趋势跟踪
│   └── strategy_c_ema.pine      #   策略C: EMA趋势
├── shared/                      # 共享函数库
│   └── indicators.py            #   DMI/ADX · StochRSI · ATR · 评分
├── .github/workflows/           # CI: 每15分钟自动扫描
├── okx_data/                    # 数据文件（gitignored）
└── SYMBOLS.txt                  # 监控品种列表
```

## 策略执行引擎

### 评分规则

```
方向分: 1H=1, 4H=2, 1D=3        （权重递增，日线最重）
满分: DMI 1+2+3=6 + SRSI 1+2+3=6 = 12分
预警阈值: ≥9分（12分的75%）
```

| 层级 | 规则 | 分值 |
|------|------|------|
| DMI方向 | 1H=多 | +1多 |
| | 4H=多 | +2多 |
| | 1D=多 | +3多 |
| StochRSI超卖(多信号) | 1H/4H < 20 | +1/+2多 |
| | 1D < 20 | +3多 |
| | 1D 20~30 | +1多 |
| StochRSI超买(空信号) | 1H/4H > 80 | +1/+2空 |
| | 1D > 80 | +3空 |
| | 1D 70~80 | +1空 |

### 入场规则

```
高分预警（多/空 ≥9分）
  + 价格在1H SuperTrend(10,1)线 ±0.5%内 → 入场
```

### 止损止盈

| 项目 | 规则 |
|------|------|
| 止损 | 2× 1H ATR(14) |
| 仓位 | 固定止损 = 总权益 2%（仓位大小动态计算） |
| 止盈 | 四维关键阻力/支撑区间 |

### 关键区间识别（四维评估）

| 维度 | 权重 | 说明 |
|------|------|------|
| 触及次数 | 40% | 历史摆动点在此区间反复出现 |
| 触及质量 | 25% | 每次触及后反转幅度 / ATR |
| 时间跨度 | 20% | 区间跨越K线数量 |
| 价格戏剧性 | 15% | 大K线/长影线→有战斗痕迹 |

自适应聚类半径：低价币 ATR×1.5，高价币 ATR×0.8

### 止盈重扫决策

到达止盈目标后重新扫描评分：

| 重扫结果 | 操作 |
|---------|------|
| 入场分 < 反向分 | 全部平仓 |
| 强势（ratio > 1.5） | 止损移至保本 + 移动止盈 |
| 多空均衡 | 平仓一半，剩余移保本 |

## 推送通知

每次扫描后通过 **PushPlus** 推送 HTML 报表到微信：

```
📊 OKX 策略扫描
├── 高分预警（≥9分） — 价格/ATR/SRSI/ST位/入场条件详情
├── 多空评分表 — 14币种 DMI1H/4H/1D + SRSI + 多/空分
└── 关键区间表 — 阻力/支撑中心价 + 触及次数 + 强度评分
```

去重规则：同币种+同方向 2 小时内不重复推送预警。

## 监控品种

见 `SYMBOLS.txt`（14币种 U本位永续合约）

## 快速开始

```bash
# 安装依赖
pip install requests

# 配置 PushPlus Token（可选，不配也能本地跑）
echo "your_token" > .pushplus_token

# 干跑扫描（仅查看，不交易）
python strategy_engine.py --dry-run

# 实际执行（会通过 OKX CLI 下单）
python strategy_engine.py

# 持续监控模式
python strategy_engine.py --loop --interval 900
```

## 部署

### GitHub Actions（主力 24/7）

- 仓库: `YYYcjj/okx-monitor`
- Cron: `*/15 * * * *` UTC（每15分钟）
- Secrets: `PUSHPLUS_TOKEN`

## 通知渠道

- **PushPlus**: [pushplus.plus](https://www.pushplus.plus) — 微信扫码，免费200条/天
