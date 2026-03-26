import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.multi_party_cannon import MultiPartyCannonStrategy

strategy = MultiPartyCannonStrategy()
strategy.params['enable_ma_filter'] = False
strategy.params['enable_macd_filter'] = False
strategy.params['enable_kdj_filter'] = False

# 创建测试数据
dates = pd.date_range(end='2024-01-01', periods=10, freq='D')
base_price = 100.0
first_rise = 0.05
second_body_ratio = 0.4
second_fallback_ratio = 0.3
third_rise = 0.05

first_open = base_price
first_close = base_price * (1 + first_rise)
first_body = first_close - first_open

second_body = first_body * second_body_ratio
second_close = first_close * (1 - first_rise * second_fallback_ratio)
second_open = second_close + second_body

third_open = second_close
third_close = third_open * (1 + third_rise)

print(f'第一根K线: open={first_open}, close={first_close}, rise={first_rise}, body={first_body}')
print(f'第二根K线: open={second_open}, close={second_close}, body={second_body}')
print(f'第三根K线: open={third_open}, close={third_close}, rise={third_rise}')

data = []
for i in range(10):
    if i == 0:
        data.append({
            'date': dates[9 - i],
            'open': third_open,
            'close': third_close,
            'high': max(third_open, third_close) * 1.01,
            'low': min(third_open, third_close) * 0.99,
            'volume': 1200000,
        })
    elif i == 1:
        data.append({
            'date': dates[9 - i],
            'open': second_open,
            'close': second_close,
            'high': max(second_open, second_close) * 1.01,
            'low': min(second_open, second_close) * 0.99,
            'volume': 800000,
        })
    elif i == 2:
        data.append({
            'date': dates[9 - i],
            'open': first_open,
            'close': first_close,
            'high': max(first_open, first_close) * 1.01,
            'low': min(first_open, first_close) * 0.99,
            'volume': 1000000,
        })
    else:
        data.append({
            'date': dates[9 - i],
            'open': base_price,
            'close': base_price,
            'high': base_price * 1.01,
            'low': base_price * 0.99,
            'volume': 1000000,
        })

df = pd.DataFrame(data)
df = df.sort_values('date', ascending=False).reset_index(drop=True)
df = strategy.calculate_indicators(df)

third_candle = df.iloc[0]
second_candle = df.iloc[1]
first_candle = df.iloc[2]

print(f'\n第一根K线计算后: open={first_candle["open"]}, close={first_candle["close"]}, candle_rise={first_candle["candle_rise"]}, body_size={first_candle["body_size"]}')
print(f'第二根K线计算后: open={second_candle["open"]}, close={second_candle["close"]}, candle_rise={second_candle["candle_rise"]}, body_size={second_candle["body_size"]}')
print(f'第三根K线计算后: open={third_candle["open"]}, close={third_candle["close"]}, candle_rise={third_candle["candle_rise"]}')

print(f'\n第一根涨幅阈值: {strategy.params["first_candle_rise"]}, 实际: {first_candle["candle_rise"]}')
print(f'第二根实体比例阈值: {strategy.params["second_candle_body_ratio"]}, 实际: {second_candle["body_size"] / first_candle["body_size"]}')
print(f'第二根回调比例阈值: {strategy.params["second_candle_fallback_ratio"]}, 实际: {strategy._calculate_fallback_ratio(first_candle, second_candle)}')
print(f'第三根涨幅阈值: {strategy.params["third_candle_rise"]}, 实际: {third_candle["candle_rise"]}')
print(f'第三根突破要求: {strategy.params["third_candle_breakthrough"]}, 实际: {third_candle["close"] > first_candle["close"]}')
print(f'第二根缩量阈值: {strategy.params["second_volume_shrink_ratio"]}, 实际: {second_candle["volume"] / first_candle["volume"]}')
print(f'第三根放量阈值: {strategy.params["third_volume_expand_ratio"]}, 实际: {third_candle["volume"] / first_candle["volume"]}')

result = strategy._is_multi_party_cannon_pattern(first_candle, second_candle, third_candle)
print(f'\n形态识别结果: {result}')

# 逐步检查每个条件
print('\n逐步检查每个条件:')
print(f'第一根是阳线: {first_candle["close"] > first_candle["open"]}')
print(f'第一根涨幅达标: {first_candle["candle_rise"] >= strategy.params["first_candle_rise"]}')
print(f'第二根是阴线: {second_candle["close"] < second_candle["open"]}')
print(f'第二根实体大小达标: {second_candle["body_size"] <= first_candle["body_size"] * strategy.params["second_candle_body_ratio"]}')
print(f'第二根回调幅度达标: {strategy._calculate_fallback_ratio(first_candle, second_candle) <= strategy.params["second_candle_fallback_ratio"]}')
print(f'第三根是阳线: {third_candle["close"] > third_candle["open"]}')
print(f'第三根涨幅达标: {third_candle["candle_rise"] >= strategy.params["third_candle_rise"]}')
print(f'第三根突破前高: {third_candle["close"] > first_candle["close"]}')
print(f'第二根缩量: {second_candle["volume"] <= first_candle["volume"] * strategy.params["second_volume_shrink_ratio"]}')
print(f'第三根放量: {third_candle["volume"] >= first_candle["volume"] * strategy.params["third_volume_expand_ratio"]}')
