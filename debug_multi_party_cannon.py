"""
调试多方炮策略，查看具体是哪个条件导致股票被过滤
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from strategy.multi_party_cannon import MultiPartyCannonStrategy

def debug_single_stock(stock_code):
    """
    调试单个股票的选股过程
    """
    print(f"\n{'='*80}")
    print(f"调试股票: {stock_code}")
    print(f"{'='*80}")
    
    # 读取股票数据
    stock_file = Path(f'data/00/{stock_code}.csv')
    if not stock_file.exists():
        print(f"股票文件不存在: {stock_file}")
        return
    
    df = pd.read_csv(stock_file)
    df['date'] = pd.to_datetime(df['date'])
    
    print(f"数据行数: {len(df)}")
    print(f"数据日期范围: {df['date'].min()} 到 {df['date'].max()}")
    
    # 初始化策略
    strategy = MultiPartyCannonStrategy()
    
    # 计算指标
    df = strategy.calculate_indicators(df)
    
    print(f"\n最新5天数据:")
    print(df[['date', 'open', 'close', 'volume', 'candle_rise', 'body_size', 'MA20']].head())
    
    # 检查市值过滤
    latest = df.iloc[0]
    market_cap = latest['market_cap'] / 1e8
    print(f"\n市值过滤:")
    print(f"  市值: {market_cap:.2f}亿元")
    print(f"  最小市值: {strategy.params['min_market_cap']}亿元")
    print(f"  最大市值: {strategy.params['max_market_cap']}亿元")
    print(f"  是否通过市值过滤: {market_cap >= strategy.params['min_market_cap'] and market_cap <= strategy.params['max_market_cap']}")
    
    # 检查均线过滤
    if strategy.params['enable_ma_filter']:
        ma_value = latest['MA20']
        print(f"\n均线过滤:")
        print(f"  收盘价: {latest['close']:.2f}")
        print(f"  MA20: {ma_value:.2f}")
        print(f"  是否通过均线过滤: {latest['close'] >= ma_value}")
    
    # 在回溯天数内寻找多方炮形态
    lookback_days = strategy.params['lookback_days']
    lookback_df = df.head(lookback_days)
    
    print(f"\n在回溯{lookback_days}天内寻找多方炮形态:")
    
    found_patterns = []
    for i in range(len(lookback_df) - 2):
        third_candle = lookback_df.iloc[i]
        second_candle = lookback_df.iloc[i + 1]
        first_candle = lookback_df.iloc[i + 2]
        
        print(f"\n--- 检查第{i+1}组K线 ---")
        print(f"第一根K线 ({first_candle['date'].strftime('%Y-%m-%d')}):")
        print(f"  开盘价: {first_candle['open']:.2f}, 收盘价: {first_candle['close']:.2f}")
        print(f"  涨幅: {first_candle['candle_rise']*100:.2f}%")
        print(f"  是否阳线: {first_candle['close'] > first_candle['open']}")
        print(f"  涨幅是否达标: {first_candle['candle_rise'] >= strategy.params['first_candle_rise']}")
        
        print(f"\n第二根K线 ({second_candle['date'].strftime('%Y-%m-%d')}):")
        print(f"  开盘价: {second_candle['open']:.2f}, 收盘价: {second_candle['close']:.2f}")
        print(f"  涨幅: {second_candle['candle_rise']*100:.2f}%")
        print(f"  是否阴线: {second_candle['close'] < second_candle['open']}")
        print(f"  实体大小: {second_candle['body_size']:.2f}")
        print(f"  第一根实体大小: {first_candle['body_size']:.2f}")
        print(f"  实体比例: {second_candle['body_size']/first_candle['body_size']*100:.2f}%")
        print(f"  实体比例是否达标: {second_candle['body_size'] <= first_candle['body_size'] * strategy.params['second_candle_body_ratio']}")
        
        fallback_ratio = strategy._calculate_fallback_ratio(first_candle, second_candle)
        print(f"  回调比例: {fallback_ratio*100:.2f}%")
        print(f"  回调比例是否达标: {fallback_ratio <= strategy.params['second_candle_fallback_ratio']}")
        
        print(f"  成交量: {second_candle['volume']:.0f}")
        print(f"  第一根成交量: {first_candle['volume']:.0f}")
        print(f"  缩量比例: {second_candle['volume']/first_candle['volume']*100:.2f}%")
        print(f"  缩量是否达标: {second_candle['volume'] <= first_candle['volume'] * strategy.params['second_volume_shrink_ratio']}")
        
        print(f"\n第三根K线 ({third_candle['date'].strftime('%Y-%m-%d')}):")
        print(f"  开盘价: {third_candle['open']:.2f}, 收盘价: {third_candle['close']:.2f}")
        print(f"  涨幅: {third_candle['candle_rise']*100:.2f}%")
        print(f"  是否阳线: {third_candle['close'] > third_candle['open']}")
        print(f"  涨幅是否达标: {third_candle['candle_rise'] >= strategy.params['third_candle_rise']}")
        
        if strategy.params['third_candle_breakthrough']:
            print(f"  是否突破前高: {third_candle['close'] > first_candle['close']}")
        
        print(f"  成交量: {third_candle['volume']:.0f}")
        print(f"  第一根成交量: {first_candle['volume']:.0f}")
        print(f"  放量比例: {third_candle['volume']/first_candle['volume']*100:.2f}%")
        print(f"  放量是否达标: {third_candle['volume'] >= first_candle['volume'] * strategy.params['third_volume_expand_ratio']}")
        
        # 检查是否满足多方炮形态
        is_pattern = strategy._is_multi_party_cannon_pattern(first_candle, second_candle, third_candle)
        print(f"\n是否满足多方炮形态: {is_pattern}")
        
        if is_pattern:
            found_patterns.append({
                'first_candle': first_candle,
                'second_candle': second_candle,
                'third_candle': third_candle
            })
    
    print(f"\n{'='*80}")
    print(f"总结:")
    print(f"{'='*80}")
    print(f"找到多方炮形态数量: {len(found_patterns)}")
    
    if found_patterns:
        for idx, pattern in enumerate(found_patterns, 1):
            print(f"\n形态 {idx}:")
            print(f"  第一根: {pattern['first_candle']['date'].strftime('%Y-%m-%d')}, 收盘价={pattern['first_candle']['close']:.2f}, 涨幅={pattern['first_candle']['candle_rise']*100:.2f}%")
            print(f"  第二根: {pattern['second_candle']['date'].strftime('%Y-%m-%d')}, 收盘价={pattern['second_candle']['close']:.2f}, 涨幅={pattern['second_candle']['candle_rise']*100:.2f}%")
            print(f"  第三根: {pattern['third_candle']['date'].strftime('%Y-%m-%d')}, 收盘价={pattern['third_candle']['close']:.2f}, 涨幅={pattern['third_candle']['candle_rise']*100:.2f}%")
    else:
        print("未找到多方炮形态")

if __name__ == '__main__':
    # 调试几个有数据的股票
    test_stocks = ['000001', '000002', '000004', '000006', '000007', '000008', '000009', '000010']
    
    for stock_code in test_stocks:
        debug_single_stock(stock_code)
