#!/usr/bin/env python3
"""
测试事件驱动策略
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from strategy.strategy_registry import get_registry

def test_event_driven_strategy():
    """
    测试事件驱动策略
    """
    print("=" * 60)
    print("测试事件驱动策略")
    print("=" * 60)
    
    # 获取策略注册器
    registry = get_registry("config/strategy_params.yaml")
    
    # 自动注册策略
    print("\n1. 注册策略...")
    registry.auto_register_from_directory("strategy")
    
    # 列出所有注册的策略
    print("\n2. 已注册的策略:")
    for strategy_name in registry.list_strategies():
        print(f"   - {strategy_name}")
    
    # 检查事件驱动策略是否注册成功
    event_driven_strategy_name = "EventDrivenStrategy"
    if event_driven_strategy_name in registry.list_strategies():
        print(f"\n3. ✓ 事件驱动策略注册成功")
        
        # 获取策略实例
        strategy = registry.get_strategy(event_driven_strategy_name)
        print(f"   策略名称: {strategy.strategy_name}")
        print(f"   显示名称: {strategy.display_name}")
        print(f"   描述: {strategy.description}")
        print(f"   参数: {strategy.params}")
        
        # 测试运行策略
        print("\n4. 测试运行策略...")
        try:
            result = strategy.run_strategy()
            print(f"   ✓ 策略运行成功")
            print(f"   选出股票数量: {result['total']}")
            print(f"   执行时间: {result['date']}")
            
            # 显示选出的股票
            if result['stocks']:
                print("\n   选出的股票:")
                for stock in result['stocks'][:5]:  # 只显示前5只
                    print(f"   - {stock['code']} {stock['name']}: {stock['reason']}")
            else:
                print("   未选出符合条件的股票")
                
        except Exception as e:
            print(f"   ✗ 策略运行失败: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"\n3. ✗ 事件驱动策略注册失败")

if __name__ == "__main__":
    test_event_driven_strategy()
