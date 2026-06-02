# OKX 策略监控系统 v2.1

每15分钟扫描8个加密货币品种，DMI/ADX 方向判断 + StochRSI 极端值评分，通过 PushPlus 推送到微信。

## 项目结构

```
okx-monitor/
├── monitor/                    # 项目1: 实时监控提醒
│   └── okx_monitor.py          #   每15min扫描 → 微信推送
├── analysis/                   # 项目2: 历史数据分析
│   ├── backtest.py             #   回测引擎：拉历史K线验证策略
│   ├── analyze_trades.py       #   交易记录分析
│   └── build_viewer.py         #   生成数据查看器HTML
├── strategy/                   # 项目3: 策略改善（待开发）
├── shared/                     # 共享函数库
│   └── indicators.py           #   DMI/ADX · StochRSI · 摆动点 · 评分
├── .github/workflows/          # CI：每15分钟自动扫描
└── okx_data/                   # 数据文件（gitignored）
    ├── scans/YYYY-MM-DD.csv    #   扫描记录
    ├── backtest_results.csv    #   回测结果
    ├── backtest_cache/         #   历史K线缓存
    └── viewer.html             #   数据查看器（双击打开）
```

## 快速开始

```bash
# 本地扫描
pip install requests
echo "your_token" > .pushplus_token
python monitor/okx_monitor.py

# 回测
python analysis/backtest.py

# 生成数据查看器（双击 okx_data/viewer.html 查看）
python analysis/build_viewer.py
```

## 策略算法

| 组件 | 方法 | 参数 |
|------|------|------|
| 方向判断 | DMI/ADX (Wilder) | +DI > -DI → 多 |
| 趋势强度 | ADX | <20弱 / 20-25形成中 / >25强 |
| 对比参考 | 摆动高低点 + 1×ATR 容差 | 5点摆动检测 |
| StochRSI | (K+D)/2, Wilder平滑 | RSI(14), Stoch(14) |
| 三套评分 | DMI纯整数 / ADX加权 / 摆动点 | 方向分+SRSI极端值加分 |

### 评分规则

```
方向分: 1H=1, 4H=1, 1D=2
SRSI <20: 多加(1D=2, 其他=方向分)
SRSI <30 + 1D: 多加1
SRSI >80: 空加(1D=2, 其他=方向分)
SRSI >70 + 1D: 空加1
预警阈值: ≥6分
```

### 监控品种

`APT, HOME, WLD, BTC, HUMA, HMSTR, PUMP, ORDI`

## 调度规则

| 时段 (CST) | 扫描 | 推送 |
|-----------|------|------|
| 日间 7:00-23:59 整点 | 每15min | 完整HTML报表（含多标准对比） |
| 日间非整点 | 每15min | 仅高分≥6 预警简报 |
| 夜间 0:00-6:59 | 每15min | 仅高分≥6 预警简报 |

## 回测结果

近60天回测（688个信号）：

| 标准 | 信号 | 24H胜率 | 最佳场景 |
|------|------|---------|---------|
| DMI纯分 | 141 | 39.7% | 1D SRSI>80 → 77.8% |
| ADX加权 | 34 | 58.8% | 信号极少但质量高 |
| 摆动点 | 513 | 54.8% | 信号最多，稳定性好 |

## 数据查看器

双击 `okx_data/viewer.html`，双标签切换：

- **📡 实时扫描** — 按日期/币种/方向/评分筛选，高分红标
- **🔬 回测结果** — 按标准(DMI/ADX/SW)/胜率筛选，✓✗可视化

每次跑 `python analysis/build_viewer.py` 即可刷新数据。

## 部署

### GitHub Actions（主力 24/7）

- 仓库: `YYYcjj/okx-monitor` (Private)
- Cron: `*/15 * * * *` UTC（每15分钟）
- Secrets: `PUSHPLUS_TOKEN`
- Artifacts: 每日CSV累积，随时下载分析

## 通知渠道

- **PushPlus**: [pushplus.plus](https://www.pushplus.plus) — 微信扫码，免费200条/天
- **企微机器人**: 配置 `.wecom_webhook`（备用）
