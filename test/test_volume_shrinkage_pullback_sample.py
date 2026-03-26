"""
测试脚本：缩量回调策略
测试目标：在500只股票样本上验证缩量回调策略的选股效果
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.volume_shrinkage_pullback import VolumeShrinkagePullbackStrategy


def test_volume_shrinkage_pullback_strategy():
    """
    测试缩量回调策略
    
    测试流程：
    1. 读取500只股票的日线数据
    2. 对每只股票执行选股
    3. 统计选股结果
    4. 输出选股股票的详细信息
    """
    print("=" * 80)
    print("缩量回调策略测试")
    print("=" * 80)
    print()
    
    # 创建策略实例
    strategy = VolumeShrinkagePullbackStrategy()
    
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
    
    # 统计各条件通过情况
    condition_stats = {
        'uptrend': 0,
        'pullback': 0,
        'stabilization': 0,
        'support': 0,
        'market_cap': 0
    }
    
    # 遍历每只股票
    for i, stock_file in enumerate(stock_files, 1):
        try:
            # 提取股票代码和名称
            stock_code = stock_file.stem
            stock_name = stock_names.get(stock_code, stock_code)
            
            # 读取股票数据
            df = pd.read_csv(stock_file, parse_dates=['date'])
            
            # 检查数据长度（需要足够的数据计算所有指标）
            min_required_days = max(
                strategy.params['lookback_days'],
                strategy.params['long_ma_period'],
                114,  # 趋势线计算需要114天
                30
            ) + 10  # 额外缓冲
            if len(df) < min_required_days:
                continue
            
            # 过滤退市/异常股票
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in stock_name for kw in invalid_keywords):
                continue
            
            # 过滤 ST/*ST 股票
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                continue
            
            # 计算指标
            df_with_indicators = strategy.calculate_indicators(df)
            
            # 检查市值条件
            latest = df_with_indicators.iloc[0]
            market_cap = latest['market_cap'] / 1e8  # 转换为亿元
            if market_cap >= strategy.params['min_market_cap'] and market_cap <= strategy.params['max_market_cap']:
                condition_stats['market_cap'] += 1
            
            # 检查上升趋势
            if strategy._check_uptrend(df_with_indicators):
                condition_stats['uptrend'] += 1
            
            # 检查缩量回调
            pullback_info = strategy._check_volume_shrinkage_pullback(df_with_indicators)
            if pullback_info['valid']:
                condition_stats['pullback'] += 1
            
            # 检查企稳信号
            if strategy._check_stabilization(df_with_indicators):
                condition_stats['stabilization'] += 1
            
            # 检查支撑确认
            if strategy._check_support(df_with_indicators):
                condition_stats['support'] += 1
            
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
    
    # 输出各条件通过情况
    print("各条件通过情况：")
    print(f"  市值过滤通过: {condition_stats['market_cap']} 只 ({condition_stats['market_cap'] / total_stocks * 100:.2f}%)")
    print(f"  上升趋势通过: {condition_stats['uptrend']} 只 ({condition_stats['uptrend'] / total_stocks * 100:.2f}%)")
    print(f"  缩量回调通过: {condition_stats['pullback']} 只 ({condition_stats['pullback'] / total_stocks * 100:.2f}%)")
    print(f"  企稳信号通过: {condition_stats['stabilization']} 只 ({condition_stats['stabilization'] / total_stocks * 100:.2f}%)")
    print(f"  支撑确认通过: {condition_stats['support']} 只 ({condition_stats['support'] / total_stocks * 100:.2f}%)")
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
            print(f"  收盘价: {stock['close']:.2f}")
            print(f"  回调幅度: {stock['pullback_ratio'] * 100:.2f}%")
            print(f"  成交量比: {stock['volume_ratio']:.2f}")
            print(f"  短期均线: {stock['ma_short']:.2f}")
            print(f"  长期均线: {stock['ma_long']:.2f}")
            print(f"  市值: {stock['market_cap']:.2f} 亿元")
            print(f"  短期趋势线: {stock['short_term_trend']:.2f}")
            print(f"  多空线: {stock['bull_bear_line']:.2f}")
            print(f"  选股原因: {', '.join(stock['reasons'])}")
            print()
    else:
        print("未找到符合缩量回调条件的股票")
        print()
        print("可能的原因：")
        print("  1. 当前市场环境下，满足缩量回调条件的股票较少")
        print("  2. 策略参数可能过于严格，可以尝试调整")
        print("  3. 可以尝试放宽回调幅度范围或缩短企稳天数")
        print()
    
    print("=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == '__main__':
    test_volume_shrinkage_pullback_strategy()
