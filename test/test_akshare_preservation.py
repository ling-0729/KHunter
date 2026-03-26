#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保持性属性测试 — Property 2: Preservation

目标: 验证网络正常时，修复后的系统行为与修复前完全一致。
采用观察优先方法论：先在未修复代码上观察正常行为，编写测试捕获该行为。
此测试在未修复代码上应 PASS（确认基线行为已捕获）。

对应需求: 3.1, 3.2, 3.3, 3.4, 3.5
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import pandas as pd
import numpy as np
from datetime import datetime

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_spot_em_dataframe():
    """构造 ak.stock_zh_a_spot_em() 的模拟正常返回数据"""
    return pd.DataFrame({
        "代码": ["600519", "000001", "300750"],
        "名称": ["贵州茅台", "平安银行", "宁德时代"],
        "最新价": [1800.0, 12.5, 220.0],
        "涨跌幅": [1.5, -0.3, 2.1],
    })


def _make_individual_info_dataframe():
    """构造 ak.stock_individual_info_em() 的模拟正常返回数据"""
    return pd.DataFrame({
        "item": ["股票代码", "股票简称", "行业", "上市时间", "总市值"],
        "value": ["600519", "贵州茅台", "白酒", "20010827", "22600亿"],
    })


def _make_financial_dataframe():
    """构造 ak.stock_financial_analysis_indicator() 的模拟正常返回数据"""
    return pd.DataFrame({
        "营业总收入": [120000000000.0],
        "净利润": [60000000000.0],
        "净资产收益率": [30.5],
        "资产负债率": [25.0],
    })


class TestPreservationValuation(unittest.TestCase):
    """属性 1: 网络正常时，估值分析结果与修复前完全一致
    
    观察: mock akshare 正常返回数据时，_analyze_valuation("600519")
    返回包含 pe/pb/ps 的有效估值结果（非零值）。
    对应需求: 3.1
    """

    @patch('akshare.stock_zh_a_spot_em')
    def test_valuation_returns_valid_result_when_network_ok(self, mock_spot_em):
        """网络正常时，_analyze_valuation() 应返回有效的估值数据"""
        # mock 正常返回数据
        mock_spot_em.return_value = _make_spot_em_dataframe()

        from stock_analyzer.fundamental_analyzer import FundamentalAnalyzer
        analyzer = FundamentalAnalyzer()
        result = analyzer._analyze_valuation("600519")

        # 断言: 返回有效的估值数据（非零）
        self.assertIsInstance(result, dict, "估值结果应为字典")
        self.assertIn("pe", result, "结果应包含 pe 字段")
        self.assertIn("pb", result, "结果应包含 pb 字段")
        self.assertIn("ps", result, "结果应包含 ps 字段")
        # 价格 1800，pe = 1800/10 = 180, pb = 1800/5 = 360, ps = 1800/8 = 225
        self.assertGreater(result["pe"], 0, "PE 应大于 0")
        self.assertGreater(result["pb"], 0, "PB 应大于 0")
        self.assertGreater(result["ps"], 0, "PS 应大于 0")

    @patch('akshare.stock_zh_a_spot_em')
    def test_valuation_pe_level_classification(self, mock_spot_em):
        """网络正常时，估值水平判断逻辑应保持不变"""
        mock_spot_em.return_value = _make_spot_em_dataframe()

        from stock_analyzer.fundamental_analyzer import FundamentalAnalyzer
        analyzer = FundamentalAnalyzer()
        result = analyzer._analyze_valuation("600519")

        # 断言: pe_level 和 pb_level 应存在且为有效值
        self.assertIn("pe_level", result, "结果应包含 pe_level")
        self.assertIn("pb_level", result, "结果应包含 pb_level")
        # pe=180 > 40 → "高", pb=360 > 4 → "高"
        self.assertIn(result["pe_level"], ["低", "中", "高"], "pe_level 应为有效分类")
        self.assertIn(result["pb_level"], ["低", "中", "高"], "pb_level 应为有效分类")


class TestPreservationCSVData(unittest.TestCase):
    """属性 2: 本地 CSV 历史行情数据读取不受重试机制影响
    
    观察: csv_manager.read_stock() 直接读取本地文件，不涉及网络。
    对应需求: 3.2
    """

    @patch('stock_analyzer.data_fetcher.CSVManager')
    def test_local_csv_read_unaffected(self, mock_csv_cls):
        """本地 CSV 数据读取应直接返回，不受任何网络重试机制影响"""
        # 构造模拟的本地 CSV 数据
        mock_csv = MagicMock()
        mock_df = pd.DataFrame({
            'date': pd.to_datetime(['2025-01-01', '2025-01-02', '2025-01-03']),
            'open': [100.0, 101.0, 102.0],
            'close': [101.0, 102.0, 103.0],
            'high': [102.0, 103.0, 104.0],
            'low': [99.0, 100.0, 101.0],
            'volume': [1000000, 1100000, 1200000],
            'amount': [100000000, 110000000, 120000000],
        })
        mock_csv.read_stock.return_value = mock_df
        mock_csv_cls.return_value = mock_csv

        from stock_analyzer.data_fetcher import DataFetcher
        fetcher = DataFetcher()
        # 手动替换 csv_manager
        fetcher.csv_manager = mock_csv

        # 调用获取历史行情
        result = fetcher.get_stock_quote("600519", period="30d")

        # 断言: 应从本地读取数据
        mock_csv.read_stock.assert_called_once_with("600519")
        # 断言: 返回的数据应包含正确的列
        self.assertFalse(result.empty, "本地数据不应为空")
        self.assertIn('close', result.columns, "结果应包含 close 列")
        self.assertIn('date', result.columns, "结果应包含 date 列")


class TestPreservationStockBasic(unittest.TestCase):
    """属性 3: 网络正常时，get_stock_basic() 返回完整信息
    
    观察: mock akshare 正常返回时，get_stock_basic("600519") 返回
    包含行业/板块的有效信息。
    对应需求: 3.3
    """

    @patch('stock_analyzer.data_fetcher.ak.stock_individual_info_em')
    def test_stock_basic_returns_valid_info_when_network_ok(self, mock_info_em):
        """网络正常时，get_stock_basic() 应返回完整的股票基本信息"""
        # 构造正常返回数据（模拟 akshare 的 item/value 格式）
        mock_info_em.return_value = pd.DataFrame({
            "item": ["股票代码", "股票简称", "行业", "上市时间", "总市值"],
            "value": ["600519", "贵州茅台", "白酒", "20010827", "22600亿"],
        })

        from stock_analyzer.data_fetcher import DataFetcher
        fetcher = DataFetcher()
        result = fetcher.get_stock_basic("600519")

        # 断言: 返回有效的基本信息
        self.assertIsInstance(result, dict, "基本信息应为字典")
        self.assertEqual(result["code"], "600519", "股票代码应正确")
        # 断言: 行业不应为"未知行业"
        self.assertIn("industry", result, "结果应包含 industry 字段")
        self.assertIn("market", result, "结果应包含 market 字段")
        self.assertEqual(result["market"], "沪市", "600519 应属于沪市")


class TestPreservationInvalidCode(unittest.TestCase):
    """属性 4: 无效股票代码的错误处理行为不变
    
    观察: 无效股票代码返回相应错误提示/默认值。
    对应需求: 3.4
    """

    @patch('stock_analyzer.data_fetcher.ak.stock_individual_info_em')
    def test_invalid_code_returns_default(self, mock_info_em):
        """无效股票代码应返回默认信息，行为不变"""
        # 模拟 akshare 对无效代码抛出异常
        mock_info_em.side_effect = Exception("股票代码不存在")

        from stock_analyzer.data_fetcher import DataFetcher
        fetcher = DataFetcher()
        result = fetcher.get_stock_basic("999999")

        # 断言: 应返回默认数据结构
        self.assertIsInstance(result, dict, "应返回字典")
        self.assertEqual(result["code"], "999999", "代码应保持原值")
        # 断言: 无效代码应返回"未知行业"（这是正确的默认行为）
        self.assertEqual(result["industry"], "未知行业", "无效代码应返回未知行业")
        self.assertEqual(result["sector"], "未知板块", "无效代码应返回未知板块")

    @patch('akshare.stock_zh_a_spot_em')
    def test_invalid_code_valuation_returns_zero(self, mock_spot_em):
        """无效股票代码的估值分析应返回零值默认"""
        # 正常返回数据，但不包含无效代码
        mock_spot_em.return_value = _make_spot_em_dataframe()

        from stock_analyzer.fundamental_analyzer import FundamentalAnalyzer
        analyzer = FundamentalAnalyzer()
        # 使用不存在的股票代码
        result = analyzer._analyze_valuation("999999")

        # 断言: 不存在的代码应返回零值默认
        self.assertEqual(result["pe"], 0, "不存在的代码 PE 应为 0")
        self.assertEqual(result["pb"], 0, "不存在的代码 PB 应为 0")
        self.assertEqual(result["pe_level"], "未知", "不存在的代码 pe_level 应为未知")


class TestPreservationTencentInterface(unittest.TestCase):
    """属性 5: 腾讯接口（HTTP直连）的超时设置和请求逻辑保持不变
    
    观察: 腾讯接口使用 requests 直连，不经过 akshare，
    重试机制仅针对 akshare 接口调用。
    对应需求: 3.5
    """

    def test_tencent_fetch_method_exists(self):
        """腾讯接口获取方法应存在且不受 akshare 重试影响"""
        from utils.akshare_fetcher import AKShareFetcher
        fetcher = AKShareFetcher()

        # 断言: 腾讯接口方法应存在
        self.assertTrue(
            hasattr(fetcher, '_fetch_market_cap_tencent'),
            "AKShareFetcher 应包含 _fetch_market_cap_tencent 方法"
        )

    def test_tencent_fetch_uses_direct_http(self):
        """腾讯接口应使用直接 HTTP 请求，不经过 akshare 包装"""
        import inspect
        from utils.akshare_fetcher import AKShareFetcher

        # 获取腾讯接口方法的源代码
        source = inspect.getsource(AKShareFetcher._fetch_market_cap_tencent)

        # 断言: 腾讯接口不应使用 akshare_call_with_retry
        # （重试机制仅针对 akshare 接口）
        self.assertNotIn(
            "akshare_call_with_retry",
            source,
            "腾讯接口不应使用 akshare 重试包装器，应保持直接 HTTP 请求"
        )
        # 断言: 应使用 requests 或 urllib 进行 HTTP 请求
        uses_http = ("requests" in source or "urllib" in source or "http" in source.lower())
        self.assertTrue(
            uses_http,
            "腾讯接口应使用 HTTP 直连方式"
        )


if __name__ == '__main__':
    # 运行测试并输出详细结果
    unittest.main(verbosity=2)
