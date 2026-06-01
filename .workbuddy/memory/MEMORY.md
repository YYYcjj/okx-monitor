# 项目记忆

## OKX 策略监控系统

### 文件
- `okx_monitor.py` - 主监控脚本
- `.wecom_webhook` - 企微机器人 Webhook URL（需配置）

### 算法
- 方向：摆动高低点 + 1×ATR 容差
  - 多：新峰 > 旧峰 且 新谷 ≥ 旧谷 - 1×ATR
  - 空：新峰 < 旧峰 且 新谷 < 旧谷 - 1×ATR
- StochRSI：(K+D)/2, Wilder平滑(14)
- ATR：Wilder平滑(14)
- 评分：方向分(1H=1, 4H=1, 1D=2) + SRSI极端值加分
  - SRSI < 20: 多加(1D=2, 其他=方向权重)
  - SRSI < 30 + 1D: 多加1
  - SRSI > 80: 空加(1D=2, 其他=方向权重)
  - SRSI > 70 + 1D: 空加1
- 预警阈值：≥6分

### 品种（8个）
APT-USDT, HOME-USDT-SWAP, WLD-USDT-SWAP, BTC-USDT, HUMA-USDT, HMSTR-USDT, PUMP-USDT, ORDI-USDT

### 自动化
- ID: automation-1780309593355
- 名称: OKX策略每小时扫描
- 频率: FREQ=HOURLY
- Python: /Users/yyy/.workbuddy/binaries/python/envs/default/bin/python
