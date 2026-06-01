# OKX 策略监控系统 v2.1

每15分钟扫描8个加密货币品种，DMI/ADX 方向判断 + StochRSI 极端值评分，通过 PushPlus 推送到微信。

## 策略算法

| 组件 | 方法 | 参数 |
|------|------|------|
| 方向判断 | DMI/ADX (Wilder) | +DI > -DI → 多 |
| 趋势强度 | ADX | <20弱 / 20-25形成中 / >25强 |
| 对比参考 | 摆动高低点 + 1×ATR 容差 | 5点摆动检测 |
| StochRSI | (K+D)/2, Wilder平滑 | RSI(14), Stoch(14) |

### 评分规则

```
方向分: 1H=1, 4H=1, 1D=2
SRSI <20: 多加(1D=2, 其他=方向分)
SRSI <30 + 1D: 多加1
SRSI >80: 空加(1D=2, 其他=方向分)
SRSI >70 + 1D: 空加1
```

- **预警阈值**: 多/空分 ≥ 6
- **三套评分对比**: DMI纯整数 / ADX加权 / 摆动点

### 监控品种

`APT-USDT, HOME-USDT-SWAP, WLD-USDT-SWAP, BTC-USDT, HUMA-USDT, HMSTR-USDT, PUMP-USDT, ORDI-USDT`

## 调度规则

| 时段 (CST) | 扫描频率 | 推送行为 |
|------------|---------|---------|
| 日间 7:00-23:59 整点 | 每15分钟 | 推送完整HTML报表 |
| 日间 7:00-23:59 非整点 | 每15分钟 | 仅高分≥6推送预警简报 |
| 夜间 0:00-6:59 | 每15分钟 | 仅高分≥6推送预警简报 |
| 全天无高分 | 每15分钟 | 不推送 |

## CSV 文档

每次扫描结果追加到 `okx_data/scans/YYYY-MM-DD.csv`，17列：

```
timestamp, symbol,
dmi_1h, dmi_4h, dmi_1d,
sw_1h, sw_4h, sw_1d,
adx_1h, adx_4h, adx_1d,
srsi_1h, srsi_4h, srsi_1d,
dmi_bull, dmi_bear, adx_bull, adx_bear, sw_bull, sw_bear
```

用于对比三套评分标准的预示性，优化参数。

## 部署

### GitHub Actions（主力）

- 仓库: `YYYcjj/okx-monitor` (Private)
- Cron: `*/15 * * * *` (每15分钟)
- Secret: `PUSHPLUS_TOKEN`

```bash
git push origin main  # 自动触发 + 定时运行
```

### 本地运行

```bash
pip install requests
echo "your_token" > .pushplus_token
python okx_monitor.py
```

## 通知渠道

- **PushPlus**（主力）: [pushplus.plus](https://www.pushplus.plus) — 微信扫码获取Token，免费200条/天
- **企微机器人**（备用）: 配置 `.wecom_webhook` 文件

## 格式说明

- 方向: `多` / `空` 二元标签
- SRSI: 原始数值，<20 绿色加粗 / >80 红色加粗
- 多标准对比表: DMI纯分 | ADX加权(小数) | 摆动点
- 时间: CST (UTC+8)
