#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试配置 — 为 akshare 缓存降级测试预填充缓存数据

确保 bug 条件测试中的缓存降级断言能够通过：
当 akshare 调用持续失败时，系统应从缓存获取历史数据。
"""

import sys
import os
import json
import time
import pandas as pd
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_akshare_cache():
    """预填充 akshare 缓存数据，供缓存降级测试使用"""
    from utils.akshare_retry import AkshareCache

    cache = AkshareCache()

    # 为 stock_zh_a_spot_em 预填充实时行情缓存
    spot_em_data = pd.DataFrame({
        "代码": ["600519", "000001", "300750"],
        "名称": ["贵州茅台", "平安银行", "宁德时代"],
        "最新价": [1800.0, 12.5, 220.0],
        "涨跌幅": [1.5, -0.3, 2.1],
    })
    cache.set("stock_zh_a_spot_em", spot_em_data)

    # 为 stock_individual_info_em(symbol="600519") 预填充基本信息缓存
    info_em_data = pd.DataFrame({
        "item": ["股票代码", "股票简称", "行业", "上市时间", "总市值"],
        "value": ["600519", "贵州茅台", "白酒", "20010827", "22600亿"],
    })
    cache.set("stock_individual_info_em", info_em_data, symbol="600519")


# 在测试收集阶段自动执行缓存预填充
_seed_akshare_cache()
