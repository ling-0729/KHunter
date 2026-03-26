"""
碗口反弹策略调试 - 分析为什么没有股票被选中
"""
import sys
from pathlib import Path
import pandas as pd

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.csv_manager import CSVManager
from strategy.bowl_rebound import BowlReboundStrategy


def debug_bowl_rebound():
    """调试碗口反弹策略"""
    print("=" * 60)
    print("碗口反弹策略调试")
    print("=" * 60)
    
    # 加载策略
    strategy = BowlReboundStrategy()
    print(f"\n策略参数: {strategy.params}")
    
    # 加载股票数据
    csv_manager = CSVManager("data")
    stock_codes = csv_manager.list_all_stocks()
    
    # 测试前5只股票
    test_stocks = stock_codes[:5]
    
    for code in test_stocks:
        print(f"\n{'='*60}")
        print(f"测试股票: {code}")
        print(f"{'='*60}")
        
        try:
            df = csv_manager.read_stock(code)
            if df.empty or len(df) < 60:
                print(f"  ✗ 数据不足: {len(df)} 行")
                continue
            
            # 计算指标
            df_with_indicators = strategy.calculate_indicators(df)
            
            # 获取最新一天的数据
            latest = df_with_indicators.iloc[0]
            print(f"\n最新数据 ({latest['date']}):")
            print(f"  收盘价: {latest['close']}")
            print(f"  成交量: {latest['volume']}")
            print(f"  J值: {latest['J']:.2f}")
            print(f"  上升趋势 (trend_above): {latest['trend_above']}")
            print(f"  J值低 (j_low): {latest['j_low']}")
            print(f"  回落碗中 (fall_in_bowl): {latest['fall_in_bowl']}")
            print(f"  靠近多空线 (near_duokong): {latest['near_duokong']}")
            print(f"  靠近短期趋势线 (near_short_trend): {latest['near_short_trend']}")
            
            # 检查异动条件
            M = strategy.params['M']
            lookback_df = df_with_indicators.head(M)
            key_candles = lookback_df[
                (lookback_df['key_candle'] == True) & 
                (lookback_df['close'] > lookback_df['open'])
            ]
            print(f"\n异动条件 (M={M}):")
            print(f"  回溯行数: {len(lookback_df)}")
            print(f"  放量阳线数: {len(key_candles)}")
            
            if len(key_candles) > 0:
                print(f"  放量阳线日期: {key_candles['date'].values}")
            
            # 执行选股
            result = strategy.select_stocks(df_with_indicators, f"测试股票{code}")
            print(f"\n选股结果: {le