#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源测试脚本
用于验证各种数据源的可行性
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from stock_analyzer.data_fetcher import DataFetcher

def test_data_sources():
    """测试各种数据源"""
    print("=" * 80)
    print("📊 数据源测试")
    print("=" * 80)
    
    fetcher = DataFetcher()
    test_stock_code = "600519"  # 贵州茅台
    
    # 测试1: 股票基本信息
    print("\n1. 测试股票基本信息:")
    try:
        stock_info = fetcher.get_stock_basic(test_stock_code)
        print(f"   ✅ 成功: {stock_info}")
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    
    # 测试2: 历史行情数据
    print("\n2. 测试历史行情数据:")
    try:
        quote_data = fetcher.get_stock_quote(test_stock_code, period="30d")
        if not quote_data.empty:
            print(f"   ✅ 成功: 获取到 {len(quote_data)} 条数据")
            print(f"   数据示例: {quote_data.head(3).to_dict('records')}")
        else:
            print("   ⚠️  数据为空")
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    
    # 测试3: 财务数据
    print("\n3. 测试财务数据:")
    try:
        financial_data = fetcher.get_financial_data(test_stock_code)
        print(f"   ✅ 成功: {financial_data}")
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    
    # 测试4: 资金流向数据
    print("\n4. 测试资金流向数据:")
    try:
        fund_flow = fetcher.get_fund_flow(test_stock_code)
        print(f"   ✅ 成功: {fund_flow}")
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    
    # 测试5: 板块数据
    print("\n5. 测试板块数据:")
    try:
        sector_data = fetcher.get_sector_data(test_stock_code)
        print(f"   ✅ 成功: {sector_data}")
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    
    # 测试6: 事件数据
    print("\n6. 测试事件数据:")
    try:
        events = fetcher.get_event_data(test_stock_code)
        if events:
            print(f"   ✅ 成功: 获取到 {len(events)} 个事件")
            for event in events[:2]:  # 只显示前2个
                print(f"   - {event}")
        else:
            print("   ⚠️  无事件数据")
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    
    print("\n" + "=" * 80)
    print("测试完成！")
    print("=" * 80)

if __name__ == "__main__":
    test_data_sources()
