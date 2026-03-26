#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试底部趋势拐点策略的回调条件修复
验证西王食品（000639）是否会被正确过滤
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.csv_manager import CSVManager
from strategy.bottom_trend_inflection import BottomTrendInflectionStrategy

def test_west_king_food():
    """测试西王食品（000639）是否会被底部趋势拐点策略正确过滤"""
    print("=" * 80)
    print("测试底部趋势拐点策略的回调条件修复")
    print("=" * 80)
    
    # 初始化CSV管理器
    csv_manager = CSVManager("data")
    
    # 读取西王食品的K线数据
    stock_code = "000639"
    stock_name = "西王食品"
    
    print(f"正在读取 {stock_name}（{stock_code}）的K线数据...")
    df = csv_manager.read_stock(stock_code)
    
    if df.empty:
        print(f"错误：无法读取 {stock_name} 的数据")
        return False
    
    print(f"成功读取 {len(df)} 条数据")
    print(f"最近5天数据:")
    print(df.head())
    print()
    
    # 初始化底部趋势拐点策略
    strategy = BottomTrendInflectionStrategy()
    
    # 执行选股
    print("正在执行底部趋势拐点策略...")
    signals = strategy.select_stocks(df, stock_name)
    
    if signals:
        print(f"⚠️  测试失败：{stock_name} 被策略选中了！")
        print(f"选中原因：{signals[0]['reasons']}")
        return False
    else:
        print(f"✅  测试成功：{stock_name} 被正确过滤，未被策略选中")
        return True

def test_callback_condition():
    """测试回调条件的具体逻辑"""
    print("\n" + "=" * 80)
    print("测试回调条件逻辑")
    print("=" * 80)
    
    # 初始化CSV管理器
    csv_manager = CSVManager("data")
    
    # 读取西王食品的K线数据
    stock_code = "000639"
    df = csv_manager.read_stock(stock_code)
    
    if df.empty:
        print("错误：无法读取数据")
        return
    
    # 初始化策略
    strategy = BottomTrendInflectionStrategy()
    
    # 计算指标
    df_with_indicators = strategy.calculate_indicators(df)
    
    # 检查放量反弹条件（包含回调检查）
    has_volume_surge = strategy._check_volume_surge(df_with_indicators)
    
    print(f"放量反弹条件检查结果: {'通过' if has_volume_surge else '不通过'}")
    
    if not has_volume_surge:
        print("✅  回调条件正确生效：放量长阳后回调低于开盘价")
    else:
        print("⚠️  回调条件未生效：放量长阳后回调未被正确检查")

if __name__ == "__main__":
    # 运行测试
    test_west_king_food()
    test_callback_condition()
    
    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)