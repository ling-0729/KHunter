#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 API 响应数据是否包含 selection_day_price 字段
"""

import requests
import json

# 调用 API
url = "http://localhost:5000/api/selection-history?limit=3"
response = requests.get(url)
data = response.json()

print("=" * 80)
print("API 响应状态:", data.get('success'))
print("=" * 80)

if data.get('success') and data.get('data'):
    for i, record in enumerate(data['data']):
        print(f"\n记录 {i+1}:")
        print(f"  股票代码: {record.get('stock_code')}")
        print(f"  股票名称: {record.get('stock_name')}")
        print(f"  selection_day_price: {record.get('selection_day_price')} (类型: {type(record.get('selection_day_price')).__name__})")
        print(f"  selection_price: {record.get('selection_price')} (类型: {type(record.get('selection_price')).__name__})")
        print(f"  current_price: {record.get('current_price')} (类型: {type(record.get('current_price')).__name__})")
        print(f"  highest_price: {record.get('highest_price')} (类型: {type(record.get('highest_price')).__name__})")
        print(f"  lowest_price: {record.get('lowest_price')} (类型: {type(record.get('lowest_price')).__name__})")
        print(f"  return_rate: {record.get('return_rate')} (类型: {type(record.get('return_rate')).__name__})")
else:
    print("API 返回错误:", data.get('error'))

print("\n" + "=" * 80)
print("完整 JSON 响应:")
print("=" * 80)
print(json.dumps(data, indent=2, ensure_ascii=False))
