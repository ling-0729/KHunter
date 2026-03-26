#!/usr/bin/env python3
"""
测试 akshare 股票数据获取功能
"""
import akshare as ak
import pandas as pd
import requests

print("测试 akshare 股票数据获取功能")
print("=" * 60)

# 测试网络连接
print("1. 测试网络连接...")
try:
    response = requests.get("https://www.baidu.com", timeout=10)
    print(f"   网络连接正常，状态码: {response.status_code}")
except Exception as e:
    print(f"   网络连接失败: {e}")

# 测试 akshare 版本
print("\n2. 测试 akshare 版本...")
print(f"   akshare 版本: {ak.__version__}")

# 测试获取股票列表
print("\n3. 测试获取股票列表...")
try:
    stock_list = ak.stock_zh_a_spot()
    print(f"   股票列表获取成功，共 {len(stock_list)} 条记录")
    print(f"   数据列名: {list(stock_list.columns)}")
    print(f"   前5条数据:\n{stock_list.head()}")
except Exception as e:
    print(f"   获取股票列表失败: {e}")
    import traceback
    traceback.print_exc()

# 测试获取股票历史数据
print("\n4. 测试获取股票历史数据...")
try:
    # 尝试使用不同的函数
    print("   尝试使用 stock_zh_a_hist...")
    stock_data = ak.stock_zh_a_hist(
        symbol="600519",
        period="daily",
        start_date="20260301",
        end_date="20260324",
        adjust="qfq"
    )
    print(f"   数据获取成功，共 {len(stock_data)} 条记录")
    print(f"   数据列名: {list(stock_data.columns)}")
    print(f"   数据类型: {stock_data.dtypes}")
    print(f"   前5条数据:\n{stock_data.head()}")
except Exception as e:
    print(f"   获取股票历史数据失败: {e}")
    import traceback
    traceback.print_exc()

# 测试获取公告数据
print("\n5. 测试获取公告数据...")
try:
    announcement_data = ak.stock_notice_report()
    print(f"   公告数据获取成功，共 {len(announcement_data)} 条记录")
    print(f"   数据列名: {list(announcement_data.columns)}")
    print(f"   前5条数据:\n{announcement_data.head()}")
except Exception as e:
    print(f"   获取公告数据失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成")
