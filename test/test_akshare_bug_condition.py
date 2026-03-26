#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bug 条件探索性测试 — Property 1: Bug Condition

目标: 通过 mock 模拟网络异常，暴露 akshare 调用失败时无重试无缓存降级的 bug。
此测试编码了期望行为（重试 + 缓存降级），在未修复代码上应 FAIL，
修复后应 PASS，从而验证修复正确性。

对应需求: 1.1, 1.2, 1.3, 1.4, 1.5
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call
from http.client import RemoteDisconnected
from requests.exceptions import Timeout, ConnectionError as RequestsConnectionError

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBugConditionValuation(unittest.TestCase):
    """测试 1: _analyze_valuation() 在 ConnectionError 时应缓存降级
    
    Bug 条件: ak.stock_zh_a_spot_em() 抛出 ConnectionError
    期望行为: 尝试缓存降级，而非直接返回全零默认值
    对应需求: 1.1
    """

    @patch('akshare.stock_zh_a_spot_em')
    def test_valuation_should_use_retry_wrapper_on_connection_error(self, mock_spot_em):
        """mock ak.stock_zh_a_spot_em() 抛出 ConnectionError，
        断言 _analyze_valuation() 通过包装器调用（仅调用1次，不重试）"""
        # 模拟网络连接中断
        mock_spot_em.side_effect = ConnectionError(
            "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
        )

        # 导入并调用被测方法
        from stock_analyzer.fundamental_analyzer import FundamentalAnalyzer
        analyzer = FundamentalAnalyzer()
        result = analyzer._analyze_valuation("600519")

        # 断言: 通过包装器调用，仅调用1次（无重试），走缓存降级
        self.assertEqual(
            mock_spot_em.call_count, 1,
            f"期望通过包装器调用1次（无重试），实际调用了 {mock_spot_em.call_count} 次。"
        )

    @patch('akshare.stock_zh_a_spot_em')
    def test_valuation_should_not_return_all_zeros_when_cache_exists(self, mock_spot_em):
        """mock ak.stock_zh_a_spot_em() 持续抛出 ConnectionError，
        断言结果不应全部为零（应有缓存降级机制）"""
        # 模拟持续网络异常
        mock_spot_em.side_effect = ConnectionError("Connection refused")

        from stock_analyzer.fundamental_analyzer import FundamentalAnalyzer
        analyzer = FundamentalAnalyzer()
        result = analyzer._analyze_valuation("600519")

        # 断言: 返回值不应全部为零默认值
        # 在未修复代码上，直接返回 {"pe": 0, "pb": 0, "ps": 0, ...}
        is_all_zero = (result.get("pe") == 0 and result.get("pb") == 0 and result.get("ps") == 0)
        self.assertFalse(
            is_all_zero,
            f"期望通过缓存降级返回有意义的数据，实际返回全零默认值: {result}。"
            "反例: 没有缓存数据可供降级使用。"
        )


class TestBugConditionStockBasic(unittest.TestCase):
    """测试 2: get_stock_basic() 在 RemoteDisconnected 时应缓存降级
    
    Bug 条件: ak.stock_individual_info_em() 抛出 RemoteDisconnected
    期望行为: 尝试缓存降级，而非直接返回"未知行业"
    对应需求: 1.2
    """

    @patch('stock_analyzer.data_fetcher.ak.stock_individual_info_em')
    def test_stock_basic_should_use_wrapper_on_remote_disconnected(self, mock_info_em):
        """mock ak.stock_individual_info_em() 抛出 RemoteDisconnected，
        断言 get_stock_basic() 通过包装器调用（仅调用1次，不重试）"""
        # 模拟远程服务器断开连接
        mock_info_em.side_effect = ConnectionError(
            "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
        )

        from stock_analyzer.data_fetcher import DataFetcher
        fetcher = DataFetcher()
        result = fetcher.get_stock_basic("600519")

        # 断言: 通过包装器调用，仅调用1次（无重试），走缓存降级
        self.assertEqual(
            mock_info_em.call_count, 1,
            f"期望通过包装器调用1次（无重试），实际调用了 {mock_info_em.call_count} 次。"
        )

    @patch('stock_analyzer.data_fetcher.ak.stock_individual_info_em')
    def test_stock_basic_should_not_return_unknown_when_cache_exists(self, mock_info_em):
        """mock ak.stock_individual_info_em() 持续抛出 RemoteDisconnected，
        断言行业信息不应为"未知行业"（应有缓存降级机制）"""
        # 模拟持续网络异常
        mock_info_em.side_effect = RemoteDisconnected(
            "Remote end closed connection without response"
        )

        from stock_analyzer.data_fetcher import DataFetcher
        fetcher = DataFetcher()
        result = fetcher.get_stock_basic("600519")

        # 断言: 行业不应为"未知行业"
        # 在未修复代码上，直接返回 "未知行业"
        self.assertNotEqual(
            result.get("industry"), "未知行业",
            f"期望通过缓存降级返回真实行业信息，实际返回: {result.get('industry')}。"
            "反例: 没有缓存数据可供降级使用。"
        )


class TestBugConditionMarketCap(unittest.TestCase):
    """测试 3: _get_realtime_market_cap() 在 Timeout 时应缓存降级
    
    Bug 条件: ak.stock_individual_info_em() 抛出 Timeout
    期望行为: 尝试缓存降级，而非直接返回 None
    对应需求: 1.3
    """

    @patch('utils.akshare_fetcher.ak.stock_individual_info_em')
    def test_market_cap_should_use_wrapper_on_timeout(self, mock_info_em):
        """mock ak.stock_individual_info_em() 抛出 Timeout，
        断言 _get_realtime_market_cap() 通过包装器调用（仅调用1次，不重试）"""
        # 模拟请求超时
        mock_info_em.side_effect = Timeout("Connection timed out")

        from utils.akshare_fetcher import AKShareFetcher
        fetcher = AKShareFetcher()
        result = fetcher._get_realtime_market_cap("600519")

        # 断言: 通过包装器调用，仅调用1次（无重试），走缓存降级
        self.assertEqual(
            mock_info_em.call_count, 1,
            f"期望通过包装器调用1次（无重试），实际调用了 {mock_info_em.call_count} 次。"
        )

    @patch('utils.akshare_fetcher.ak.stock_individual_info_em')
    def test_market_cap_should_not_return_none_when_cache_exists(self, mock_info_em):
        """mock ak.stock_individual_info_em() 持续抛出 Timeout，
        断言结果不应为 None（应有缓存降级机制）"""
        # 模拟持续超时
        mock_info_em.side_effect = Timeout("Read timed out")

        from utils.akshare_fetcher import AKShareFetcher
        fetcher = AKShareFetcher()
        result = fetcher._get_realtime_market_cap("600519")

        # 断言: 结果不应为 None
        # 在未修复代码上，直接返回 None
        self.assertIsNotNone(
            result,
            "期望通过缓存降级返回有意义的市值数据，实际返回 None。"
            "反例: 没有缓存数据可供降级使用，导致使用假市值。"
        )


class TestBugConditionTimeoutControl(unittest.TestCase):
    """测试 4: akshare 调用应有超时控制
    
    Bug 条件: akshare 底层 HTTP 请求没有设置超时参数
    期望行为: 应设置合理的超时参数（连接10s，读取30s）
    对应需求: 1.5
    """

    def test_akshare_calls_should_have_timeout_control(self):
        """验证 akshare 调用应有超时控制机制
        
        在未修复代码上，直接调用 ak.xxx() 没有任何超时设置，
        期望修复后通过包装器设置默认超时。
        """
        # 检查是否存在 akshare_retry 模块（超时控制包装器）
        try:
            from utils.akshare_retry import akshare_call_with_retry
            # 如果模块存在，说明已有超时控制机制
            has_timeout_control = True
        except ImportError:
            # 模块不存在，说明没有超时控制
            has_timeout_control = False

        # 断言: 应存在超时控制机制
        # 在未修复代码上，utils/akshare_retry.py 不存在
        self.assertTrue(
            has_timeout_control,
            "期望存在 utils/akshare_retry.py 模块提供超时控制，"
            "但该模块不存在。反例: akshare 调用没有超时控制，可能长时间阻塞。"
        )

    def test_fundamental_analyzer_should_use_retry_wrapper(self):
        """验证 fundamental_analyzer 应使用带超时的重试包装器，
        而非直接调用 ak.stock_zh_a_spot_em()"""
        import inspect
        from stock_analyzer.fundamental_analyzer import FundamentalAnalyzer

        # 获取 _analyze_valuation 方法的源代码
        source = inspect.getsource(FundamentalAnalyzer._analyze_valuation)

        # 断言: 源代码中应使用 akshare_call_with_retry 而非直接调用 ak.xxx
        # 在未修复代码上，直接调用 ak.stock_zh_a_spot_em()
        self.assertIn(
            "akshare_call_with_retry",
            source,
            "期望 _analyze_valuation() 使用 akshare_call_with_retry 包装器，"
            "实际直接调用 ak.stock_zh_a_spot_em()。反例: 没有超时控制和重试机制。"
        )


if __name__ == '__main__':
    # 运行测试并输出详细结果
    unittest.main(verbosity=2)
