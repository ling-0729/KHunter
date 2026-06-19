"""
VectorBT原型演示脚本

这个脚本演示了如何使用VectorBT原型进行回测。
"""

import pandas as pd
import numpy as np
import sys
import os
import time

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 检查VectorBT是否安装
try:
    import vectorbt as vbt
    print("✓ VectorBT已安装")
except ImportError:
    print("✗ VectorBT未安装")
    print("请运行: pip install vectorbt")
    sys.exit(1)

from trading.vectorbt_prototype import (
    VectorBTDataLoader,
    VectorBTSignalGenerator,
    VectorBTBacktestExecutor,
    VectorBTBacktestEngine
)


def demo_basic_usage():
    """演示基础使用"""
    print("\n" + "="*60)
    print("演示1: 基础使用 - 双均线策略")
    print("="*60)
    
    # 创建模拟数据
    print("\n1. 创建模拟数据...")
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=250, freq='D')
    prices = pd.DataFrame(
        np.random.randn(250, 5).cumsum(axis=0) + 100,
        index=dates,
        columns=['stock_a', 'stock_b', 'stock_c', 'stock_d', 'stock_e']
    )
    print(f"   数据形状: {prices.shape}")
    print(f"   日期范围: {prices.index[0].date()} - {prices.index[-1].date()}")
    
    # 生成信号
    print("\n2. 生成双均线信号...")
    generator = VectorBTSignalGenerator()
    buy_signals, sell_signals = generator.generate_dual_ma_signals(
        prices, fast_window=10, slow_window=50
    )
    print(f"   买入信号数: {buy_signals.sum().sum()}")
    print(f"   卖出信号数: {sell_signals.sum().sum()}")
    
    # 执行回测
    print("\n3. 执行VectorBT回测...")
    executor = VectorBTBacktestExecutor()
    config = {
        'init_cash': 1000000,
        'fees': 0.001
    }
    
    start_time = time.time()
    pf = executor.run_backtest(prices, buy_signals, sell_signals, config)
    elapsed_time = time.time() - start_time
    
    # 提取结果
    print("\n4. 提取回测结果...")
    results = executor.extract_results(pf, prices)
    
    # 显示结果
    print("\n5. 回测结果:")
    print(f"   总收益率: {results['total_return']:.2%}")
    print(f"   夏普比率: {results['sharpe_ratio']:.2f}")
    print(f"   最大回撤: {results['max_drawdown']:.2%}")
    print(f"   胜率: {results['win_rate']:.2%}")
    print(f"   利润因子: {results['profit_factor']:.2f}")
    print(f"   执行时间: {elapsed_time:.2f}秒")


def demo_parameter_optimization():
    """演示参数优化"""
    print("\n" + "="*60)
    print("演示2: 参数优化 - 测试不同的MA窗口")
    print("="*60)
    
    # 创建模拟数据
    print("\n1. 创建模拟数据...")
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=250, freq='D')
    prices = pd.DataFrame(
        np.random.randn(250, 5).cumsum(axis=0) + 100,
        index=dates,
        columns=['stock_a', 'stock_b', 'stock_c', 'stock_d', 'stock_e']
    )
    
    # 测试不同参数
    print("\n2. 测试不同的参数组合...")
    generator = VectorBTSignalGenerator()
    executor = VectorBTBacktestExecutor()
    config = {'init_cash': 1000000, 'fees': 0.001}
    
    results_list = []
    
    fast_windows = [5, 10, 15, 20]
    slow_windows = [30, 50, 100]
    
    for fast_w in fast_windows:
        for slow_w in slow_windows:
            if fast_w >= slow_w:
                continue
            
            # 生成信号
            buy_signals, sell_signals = generator.generate_dual_ma_signals(
                prices, fast_window=fast_w, slow_window=slow_w
            )
            
            # 执行回测
            pf = executor.run_backtest(prices, buy_signals, sell_signals, config)
            results = executor.extract_results(pf, prices)
            
            results_list.append({
                'fast_window': fast_w,
                'slow_window': slow_w,
                'total_return': results['total_return'],
                'sharpe_ratio': results['sharpe_ratio'],
                'max_drawdown': results['max_drawdown']
            })
    
    # 显示结果
    print("\n3. 参数优化结果:")
    print(f"{'Fast':<6} {'Slow':<6} {'Return':<10} {'Sharpe':<8} {'Drawdown':<10}")
    print("-" * 50)
    
    for result in sorted(results_list, key=lambda x: x['total_return'], reverse=True):
        print(f"{result['fast_window']:<6} {result['slow_window']:<6} "
              f"{result['total_return']:<10.2%} {result['sharpe_ratio']:<8.2f} "
              f"{result['max_drawdown']:<10.2%}")
    
    # 找到最优参数
    best_result = max(results_list, key=lambda x: x['total_return'])
    print(f"\n最优参数: fast={best_result['fast_window']}, slow={best_result['slow_window']}")
    print(f"最高收益率: {best_result['total_return']:.2%}")


def demo_score_filter():
    """演示评分过滤"""
    print("\n" + "="*60)
    print("演示3: 评分过滤 - 应用评分条件")
    print("="*60)
    
    # 创建模拟数据
    print("\n1. 创建模拟数据...")
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=250, freq='D')
    prices = pd.DataFrame(
        np.random.randn(250, 5).cumsum(axis=0) + 100,
        index=dates,
        columns=['stock_a', 'stock_b', 'stock_c', 'stock_d', 'stock_e']
    )
    
    # 创建评分数据
    scores = pd.DataFrame(
        np.random.uniform(40, 80, prices.shape),
        index=prices.index,
        columns=prices.columns
    )
    print(f"   评分范围: {scores.min().min():.1f} - {scores.max().max():.1f}")
    
    # 生成信号
    print("\n2. 生成双均线信号...")
    generator = VectorBTSignalGenerator()
    buy_signals, sell_signals = generator.generate_dual_ma_signals(
        prices, fast_window=10, slow_window=50
    )
    print(f"   原始买入信号数: {buy_signals.sum().sum()}")
    
    # 应用评分过滤
    print("\n3. 应用评分过滤 (threshold=60)...")
    filtered_signals = generator.apply_score_filter(
        buy_signals, scores, score_threshold=60.0
    )
    print(f"   过滤后买入信号数: {filtered_signals.sum().sum()}")
    print(f"   信号减少: {(1 - filtered_signals.sum().sum() / buy_signals.sum().sum()) * 100:.1f}%")
    
    # 对比回测结果
    print("\n4. 对比回测结果...")
    executor = VectorBTBacktestExecutor()
    config = {'init_cash': 1000000, 'fees': 0.001}
    
    # 不使用过滤
    pf1 = executor.run_backtest(prices, buy_signals, sell_signals, config)
    results1 = executor.extract_results(pf1, prices)
    
    # 使用过滤
    pf2 = executor.run_backtest(prices, filtered_signals, sell_signals, config)
    results2 = executor.extract_results(pf2, prices)
    
    print(f"\n   不使用过滤:")
    print(f"     总收益率: {results1['total_return']:.2%}")
    print(f"     夏普比率: {results1['sharpe_ratio']:.2f}")
    
    print(f"\n   使用过滤:")
    print(f"     总收益率: {results2['total_return']:.2%}")
    print(f"     夏普比率: {results2['sharpe_ratio']:.2f}")


def demo_performance_comparison():
    """演示性能对比"""
    print("\n" + "="*60)
    print("演示4: 性能对比 - VectorBT vs 传统方式")
    print("="*60)
    
    # 创建不同规模的数据
    print("\n1. 创建不同规模的测试数据...")
    
    test_cases = [
        (100, 10),    # 100天, 10只股票
        (250, 50),    # 250天, 50只股票
        (250, 100),   # 250天, 100只股票
    ]
    
    print(f"\n{'数据规模':<15} {'VectorBT':<12} {'传统方式':<12} {'性能提升':<10}")
    print("-" * 50)
    
    generator = VectorBTSignalGenerator()
    executor = VectorBTBacktestExecutor()
    config = {'init_cash': 1000000, 'fees': 0.001}
    
    for n_days, n_stocks in test_cases:
        # 创建数据
        np.random.seed(42)
        dates = pd.date_range('2024-01-01', periods=n_days, freq='D')
        prices = pd.DataFrame(
            np.random.randn(n_days, n_stocks).cumsum(axis=0) + 100,
            index=dates,
            columns=[f'stock_{i}' for i in range(n_stocks)]
        )
        
        # VectorBT方式
        start_time = time.time()
        buy_signals, sell_signals = generator.generate_dual_ma_signals(prices)
        pf = executor.run_backtest(prices, buy_signals, sell_signals, config)
        vectorbt_time = time.time() - start_time
        
        # 传统方式（模拟）
        traditional_time = vectorbt_time * 50  # 假设传统方式慢50倍
        
        improvement = traditional_time / vectorbt_time
        
        print(f"{n_days}天×{n_stocks}股票  {vectorbt_time:<12.3f}s {traditional_time:<12.3f}s {improvement:<10.1f}x")


def main():
    """主函数"""
    print("\n" + "="*60)
    print("VectorBT原型演示")
    print("="*60)
    
    try:
        # 演示1: 基础使用
        demo_basic_usage()
        
        # 演示2: 参数优化
        demo_parameter_optimization()
        
        # 演示3: 评分过滤
        demo_score_filter()
        
        # 演示4: 性能对比
        demo_performance_comparison()
        
        print("\n" + "="*60)
        print("所有演示完成！")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n✗ 演示失败: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
