"""
测试脚本：多金叉共振策略
测试目标：在500只股票样本上验证多金叉共振策略的选股效果
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.multi_golden_cross import MultiGoldenCrossStrategy


def test_multi_golden_cross_strategy():
    """
    测试多金叉共振策略
    
    测试流程：
    1. 读取500只股票的日线数据
    2. 对每只股票执行选股
    3. 统计选股结果
    4. 输出选股股票的详细信息
    """
    print("=" * 80)
    print("多金叉共振策略测试")
    print("=" * 80)
    print()
    
    # 创建策略实例
    strategy = MultiGoldenCrossStrategy()
    
    # 读取股票名称映射
    stock_names_file = Path(__file__).parent.parent / 'data' / 'stock_names.json'
    stock_names = {}
    if stock_names_file.exists():
        import json
        with open(stock_names_file, 'r', encoding='utf-8') as f:
            stock_names = json.load(f)
    
    # 输出策略参数
    print("策略参数：")
    for key, value in strategy.params.items():
        print(f"  {key}: {value}")
    print()
    
    # 读取股票数据
    print("读取股票数据...")
    data_dir = Path(__file__).parent.parent / 'data' / '00'
    
    # 获取所有股票文件
    stock_files = list(data_dir.glob('*.csv'))
    
    if len(stock_files) == 0:
        print("错误：未找到股票数据文件")
        return
    
    # 限制测试500只股票
    stock_files = stock_files[:500]
    print(f"共读取 {len(stock_files)} 只股票")
    print()
    
    # 统计变量
    total_stocks = len(stock_files)
    selected_stocks = []
    error_count = 0
    
    # 遍历每只股票
    for i, stock_file in enumerate(stock_files, 1):
        try:
            # 提取股票代码和名称
            stock_code = stock_file.stem
            stock_name = stock_names.get(stock_code, stock_code)
            
            # 读取股票数据
            df = pd.read_csv(stock_file, parse_dates=['date'])
            
            # 检查数据长度
            if len(df) < strategy.params['lookback_days']:
                continue
            
            # 计算指标
            df_with_indicators = strategy.calculate_indicators(df)
            
            # 执行选股
            results = strategy.select_stocks(df_with_indicators, stock_name=stock_name)
            
            # 如果有选股结果，添加到列表
            if results:
                for result in results:
                    result['stock_code'] = stock_code
                    result['stock_name'] = stock_name
                    selected_stocks.append(result)
            
            # 打印进度
            if i % 50 == 0:
                print(f"已处理 {i}/{total_stocks} 只股票，已选股 {len(selected_stocks)} 只")
        
        except Exception as e:
            error_count += 1
            if error_count <= 5:
                print(f"处理股票 {stock_file.stem} 时出错: {str(e)}")
    
    print()
    print("=" * 80)
    print("选股结果统计")
    print("=" * 80)
    print(f"总股票数: {total_stocks}")
    print(f"选股数量: {len(selected_stocks)}")
    print(f"选股比例: {len(selected_stocks) / total_stocks * 100:.2f}%")
    print(f"错误数量: {error_count}")
    print()
    
    # 输出选股股票的详细信息
    if selected_stocks:
        print("=" * 80)
        print("选股股票详细信息")
        print("=" * 80)
        print()
        
        for i, stock in enumerate(selected_stocks, 1):
            print(f"【选股股票 {i}】")
            print(f"  股票代码: {stock['stock_code']}")
            print(f"  股票名称: {stock['stock_name']}")
            print(f"  选股日期: {stock['date']}")
            print(f"  收盘价: {stock['close']}")
            print(f"  均线金叉日期: {stock['ma_cross_date']}")
            print(f"  KDJ金叉日期: {stock['kdj_cross_date']}")
            print(f"  MACD金叉日期: {stock['macd_cross_date']}")
            print(f"  最大时间差: {stock['max_time_diff']} 天")
            print(f"  短期均线: {stock['ma_short']}")
            print(f"  长期均线: {stock['ma_long']}")
            print(f"  KDJ-K: {stock['K']}")
            print(f"  KDJ-D: {stock['D']}")
            print(f"  KDJ-J: {stock['J']}")
            print(f"  MACD-DIF: {stock['DIF']}")
            print(f"  MACD-DEA: {stock['DEA']}")
            print(f"  MACD: {stock['MACD']}")
            print(f"  成交量比: {stock['volume_ratio']}")
            print(f"  市值: {stock['market_cap']} 亿元")
            print(f"  短期趋势线: {stock['short_term_trend']}")
            print(f"  多空线: {stock['bull_bear_line']}")
            print(f"  选股原因: {', '.join(stock['reasons'])}")
            print()
    else:
        print("未找到符合多金叉共振条件的股票")
        print()
        print("可能的原因：")
        print("  1. 三个金叉同时发生的概率较低")
        print("  2. 当前市场环境下，满足共振条件的股票较少")
        print("  3. 可以尝试调整参数，如延长共振时间窗口或回溯天数")
        print()
    
    print("=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == '__main__':
    test_multi_golden_cross_strategy()
