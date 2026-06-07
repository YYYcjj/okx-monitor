# OKX 策略回測引擎

自動網格搜索最優交易參數：DMI+StochRSI 多空評分 + SuperTrend 入場 + 關鍵區間止盈。

## 快速開始

```bash
pip install requests
python engine.py
```

在 `engine.py` 最底部修改 `param_grid` 控制搜索範圍。

## 參數說明

| 參數 | 說明 | 候選值 |
|------|------|--------|
| alert_threshold | 預警閾值 | 7,8,9 |
| dmi_weights | DMI方向權重 | (1,2,3) (1,1,2) |
| st_mult | SuperTrend 倍數 | 0.5, 1.0, 1.5 |
| near_pct | ST 附近 % | 0.5%, 1%, 1.5% |
| sl_atr_mult | 止損 ATR 倍數 | 1.5, 2.0, 2.5 |
| min_sl_pct | 最低止損 % | 1%, 2% |
| tp_atr_mult | 止盈 ATR 倍數 | 4x, 6x, 8x |
| entry_mode | 入場模式 | st_near / st_in_zone |
| zone_depth | 關鍵區間深度 | 2, 5 |

## 評分權重

```python
綜合分 = 勝率×0.3 + 收益率/10×0.3 + Sharpe/2×0.2 + 交易數/50×0.2
```

## 輸出

- `results/grid_results.json` — Top 50 策略詳情
- 終端輸出 Top 20 排名
