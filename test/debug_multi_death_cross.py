"""
调试脚本：多死叉共振策略
调试目标：分析策略未筛选出股票的原因
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.multi_death_cross import MultiDeathCrossStrategy


def debug_multi_death_cross_strategy():
    """
    调试多死叉共振策略
    
    调试流程：
    1. 读取部分股票数据
    2. 计算指标
    3. 详细分析死叉识别、共振确认、价格确认的执行情况
    4. 输出详细的调试信息
    """
    print("=" * 80)
    print("多死叉共振策略调试")
    print("=" * 80)
    print()
    
    # 创建策略实例
    strategy = MultiDeathCrossStrategy()
    
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
    
    # 读取股票数据（选择前20只股票进行调试）
    print("读取股票数据...")
    data_dir = Path(__file__).parent.parent / 'data' / '00'
    
    # 获取所有股票文件
    stock_files = list(data_dir.glob('*.csv'))[:20]  # 只调试前20只股票
    
    if len(stock_files) == 0:
        print("错误：未找到股票数据文件")
        return
    
    print(f"共读取 {len(stock_files)} 只股票用于调试")
    print()
    
    # 统计变量
    total_stocks = len(stock_files)
    ma_death_cross_count = 0
    kdj_death_cross_count = 0
    macd_death_cross_count = 0
    resonance_count = 0
    price_confirmation_count = 0
    
    # 遍历每只股票
    for i, stock_file in enumerate(stock_files, 1):
        try:
            # 提取股票代码和名称
            stock_code = stock_file.stem
            stock_name = stock_names.get(stock_code, stock_code)
            
            print(f"\n【调试股票 {i}/{total_stocks}】 {stock_code} {stock_name}")
            print("-" * 60)
            
            # 读取股票数据
            df = pd.read_csv(stock_file, parse_dates=['date'])
            
            # 检查数据长度
            if len(df) < strategy.params['lookback_days']:
                print(f"  数据长度不足: {len(df)} < {strategy.params['lookback_days']}")
                continue
            
            # 计算指标
            df_with_indicators = strategy.calculate_indicators(df)
            
            # 调试死叉识别
            ma_death_cross_date = strategy._find_ma_death_cross(df_with_indicators)
            kdj_death_cross_date = strategy._find_kdj_death_cross(df_with_indicators)
            macd_death_cross_date = strategy._find_macd_death_cross(df_with_indicators)
            
            print(f"  均线死叉日期: {ma_death_cross_date}")
            print(f"  KDJ死叉日期: {kdj_death_cross_date}")
            print(f"  MACD死叉日期: {macd_death_cross_date}")
            
            # 统计死叉数量
            if ma_death_cross_date:
                ma_death_cross_count += 1
            if kdj_death_cross_date:
                kdj_death_cross_count += 1
            if macd_death_cross_date:
                macd_death_cross_count += 1
            
            # 调试共振确认
            resonance = strategy._check_resonance(ma_death_cross_date, kdj_death_cross_date, macd_death_cross_date)
            print(f"  共振确认: {resonance}")
            
            if resonance:
                resonance_count += 1
                # 计算最大时间差
                max_time_diff = strategy._calculate_max_time_diff(ma_death_cross_date, kdj_death_cross_date, macd_death_cross_date)
                print(f"  最大时间差: {max_time_diff} 天")
                
                # 调试价格确认
                latest = df_with_indicators.iloc[0]
                price_confirmation = strategy._check_price_confirmation(latest)
                print(f"  价格确认: {price_confirmation}")
                
                if price_confirmation:
                    price_confirmation_count += 1
                    print(f"  ✅ 满足所有条件！")
                else:
                    # 详细分析价格确认失败的原因
                    print(f"  ❌ 价格确认失败原因：")
                    if pd.isna(latest['close']) or pd.isna(latest['ma_short']) or pd.isna(latest['ma_long']):
                        print(f"    - 数据缺失")
                    if latest['close'] >= latest['ma_short']:
                        print(f"    - 收盘价 >= MA5 ({latest['close']:.2f} >= {latest['ma_short']:.2f})")
                    if latest['close'] >= latest['ma_long']:
                        print(f"    - 收盘价 >= MA20 ({latest['close']:.2f} >= {latest['ma_long']:.2f})")
                    if not pd.isna(latest['short_term_trend']) and latest['close'] >= latest['short_term_trend']:
                        print(f"    - 收盘价 >= 短期趋势线 ({latest['close']:.2f} >= {latest['short_term_trend']:.2f})")
                    if not pd.isna(latest['bull_bear_line']) and latest['close'] >= latest['bull_bear_line']:
                        print(f"    - 收盘价 >= 多空线 ({latest['close']:.2f} >= {latest['bull_bear_line']:.2f})")
            
            # 输出最新一天的指标值
            if len(df_with_indicators) > 0:
                latest = df_with_indicators.iloc[0]
                print(f"  最新指标值:")
                print(f"    收盘价: {latest['close']:.2f}")
                print(f"    MA5: {latest['ma_short']:.2f}")
                print(f"    MA20: {latest['ma_long']:.2f}")
                print(f"    K: {latest['K']:.2f}")
                print(f"    D: {latest['D']:.2f}")
                print(f"    J: {latest['J']:.2f}")
                print(f"    DIF: {latest['DIF']:.4f}")
                print(f"    DEA: {latest['DEA']:.4f}")
                print(f"    MACD: {latest['MACD']:.4f}")
        
        except Exception as e:
            print(f"  处理股票 {stock_file.stem} 时出错: {str(e)}")
    
    print()
    print("=" * 80)
    print("调试结果统计")
    print("=" * 80)
    print(f"总股票数: {total_stocks}")
    print(f"均线死叉: {ma_death_cross_count} ({ma_death_cross_count / total_stocks * 100:.2f}%)")
    print(f"KDJ死叉: {kdj_death_cross_count} ({kdj_death_cross_count / total_stocks * 100:.2f}%)")
    print(f"MACD死叉: {macd_death_cross_count} ({macd_death_cross_count / total_stocks * 100:.2f}%)")
    print(f"共振确认: {resonance_count} ({resonance_count / total_stocks * 100:.2f}%)")
    print(f"价格确认: {price_confirmation_count} ({price_confirmation_count / total_stocks * 100:.2f}%)")
    print()
    
    # 分析原因
    if resonance_count == 0:
        print("【分析】共振确认失败的主要原因：")
        print("  1. 三个死叉同时发生的概率较低")
        print("  2. 时间窗口限制（3天）过严")
        print("  3. 可能是死叉识别逻辑有问题")
    
    if resonance_count > 0 and price_confirmation_count == 0:
        print("【分析】价格确认失败的主要原因：")
        print("  1. 价格确认条件过严")
        print("  2. 要求收盘价在所有均线下方")
        print("  3. 可能是趋势线计算有问题")
    
    print()
    print("=" * 80)
    print("调试完成")
    print("=" * 80)


if __name__ == '__main__':
    debug_multi_death_cross_strategy()
