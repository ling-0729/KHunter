#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时价格获取功能测试

测试内容：
1. AKShareFetcher.get_stock_price() 单只股票实时价格
2. AKShareFetcher.get_stock_prices_batch() 批量实时价格
3. SelectionRecordManager._fetch_realtime_price() 实时价格
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGetStockPrice(unittest.TestCase):
    """测试 AKShareFetcher.get_stock_price 单只获取"""

    def setUp(self):
        """初始化测试对象"""
        from utils.akshare_fetcher import AKShareFetcher
        self.fetcher = AKShareFetcher()

    @patch('utils.akshare_fetcher.requests.get')
    def test_get_price_success_sh(self, mock_get):
        """测试沪市股票获取成功"""
        # 模拟腾讯接口返回（GBK编码）
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = 'v_sh600519="1~贵州茅台~600519~1800.00~1790.00~1795.00~50000~25000~25000~1800.01~100~1800.00~200"'
        mock_get.return_value = mock_resp

        # 调用并验证
        price = self.fetcher.get_stock_price('600519')
        self.assertEqual(price, 1800.00)

    @patch('utils.akshare_fetcher.requests.get')
    def test_get_price_success_sz(self, mock_get):
        """测试深市股票获取成功"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = 'v_sz000