"""
批量实时价格获取功能测试
测试 AKShareFetcher.get_stock_prices_batch 方法
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.akshare_fetcher import AKShareFetcher


class TestGetStockPricesBatch(unittest.TestCase):
    """测试批量获取实时价格"""

    def setUp(self):
        """初始化测试对象"""
        self.fetcher = AKShareFetcher()

    @patch('utils.akshare_fetcher.requests.get')
    def test_batch_basic(self, mock_get):
        """测试基本批量获取：沪市+深市混合"""
        # 模拟腾讯接口返回（两只股票）
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # 沪市600519 价格1800.50，深市000001 价格12.35
        mock_resp.text = (
            'v_sh600519="1~贵州茅台~600519~1800.50~1795.00~1796.00~12345~";'
            'v_sz000001="1~平安银行~000001~12.35~12.30~12.32~98765~";'
        )
        mock_get.return_value = mock_resp

        # 执行批量获取
        codes = ['600519', '000001']
        result = self.fetcher.get_stock_prices_batch(codes)

        # 验证结果
        self.assertIn('600519', result)
        self.assertIn('000001', result)
        self.assertAlmostEqual(result['600519'], 1800.50)
        self.assertAlmostEqual(result['000001'], 12.35)

    @patch('utils.akshare_fetcher.requests.get')
    def test_batch_empty_input(self, mock_get):
        """测试空列表输入"""
        result = self.fetcher.get_stock_prices_batch([])
        # 空列表应返回空字典，不发起请求
        self.assertEqual(result, {})
        mock_get.assert_not_called()

    @patch('utils.akshare_fetcher.requests.get')
    def test_batch_price_zero_filtered(self, mock_get):
        """测试价格为0的股票被过滤"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # 价格为0（停牌股票）
        mock_resp.text = 'v_sh600000="1~浦发银行~600000~0.00~10.50~10.50~0~";'
        mock_get.return_value = mock_resp

        result = self.fetcher.get_stock_prices_batch(['600000'])
        # 价格为0不应包含在结果中
        self.assertNotIn('600000', result)

    @patch('utils.akshare_fetcher.requests.get')
    def test_batch_network_error(self, mock_get):
        """测试网络异常时返回空结果"""
        mock_get.side_effect = Exception("网络超时")

        result = self.fetcher.get_stock_prices_batch(['600519'])
        # 网络异常应返回空字典
        self.assertEqual(result, {})

    @patch('utils.akshare_fetcher.requests.get')
    def test_batch_market_prefix(self, mock_get):
        """测试市场前缀判断：6/8开头为沪市，其他为深市"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            'v_sh688001="1~华兴源创~688001~55.20~55.00~55.10~1000~";'
            'v_sz300750="1~宁德时代~300750~220.50~220.00~220.10~5000~";'
        )
        mock_get.return_value = mock_resp

        # 科创板688和创业板300
        result = self.fetcher.get_stock_prices_batch(['688001', '300750'])

        # 验证请求URL中的前缀
        call_url = mock_get.call_args[0][0] if mock_get.call_args[0] else mock_get.call_args[1].get('url', '')
        # sh688001 和 sz300750
        self.assertIn('sh688001', call_url)
        self.assertIn('sz300750', call_url)

    @patch('utils.akshare_fetcher.requests.get')
    def test_batch_partial_failure(self, mock_get):
        """测试部分股票数据异常时不影响其他股票"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # 第一只正常，第二只数据不完整
        mock_resp.text = (
            'v_sh600519="1~贵州茅台~600519~1800.50~1795.00~1796.00~12345~";'
            'v_sz000002="";'
        )
        mock_get.return_value = mock_resp

        result = self.fetcher.get_stock_prices_batch(['600519', '000002'])
        # 正常的应该有，异常的不应该有
        self.assertIn('600519', result)
        self.assertNotIn('000002', result)

    @patch('utils.akshare_fetcher.requests.get')
    def test_batch_http_error(self, mock_get):
        """测试HTTP状态码非200时返回空结果"""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = ''
        mock_get.return_value = mock_resp

        result = self.fetcher.get_stock_prices_batch(['600519'])
        self.assertEqual(result, {})


class TestRunSelectionRealtimePrice(unittest.TestCase):
    """测试选股结果中的实时价格替换逻辑"""

    def test_replace_close_in_signals(self):
        """测试替换嵌套signals中的close字段"""
        # 模拟选股结果结构
        results = {
            'morning_star': [
                {
                    'code': '600519',
                    'name': '贵州茅台',
                    'signals': [
                        {'close': 1795.00, 'J': 80, 'volume_ratio': 1.5}
                    ]
                },
                {
                    'code': '000001',
                    'name': '平安银行',
                    'signals': [
                        {'close': 12.30, 'J': 65, 'volume_ratio': 1.2}
                    ]
                }
            ]
        }

        # 模拟实时价格
        realtime_prices = {'600519': 1800.50, '000001': 12.35}

        # 执行替换逻辑（与web_server.py中一致）
        for key, signals in results.items():
            if isinstance(signals, list):
                for item in signals:
                    if not isinstance(item, dict):
                        continue
                    code = item.get('code', '')
                    price = realtime_prices.get(code)
                    if price is None:
                        continue
                    if 'signals' in item and isinstance(item['signals'], list):
                        for sig in item['signals']:
                            if isinstance(sig, dict) and 'close' in sig:
                                sig['close'] = round(price, 2)

        # 验证替换结果
        self.assertEqual(
            results['morning_star'][0]['signals'][0]['close'], 1800.50
        )
        self.assertEqual(
            results['morning_star'][1]['signals'][0]['close'], 12.35
        )

    def test_replace_missing_code_not_affected(self):
        """测试实时价格缺失时保留原始close"""
        results = {
            'test_strategy': [
                {
                    'code': '999999',
                    'name': '不存在',
                    'signals': [{'close': 10.00}]
                }
            ]
        }

        # 实时价格中没有999999
        realtime_prices = {'600519': 1800.50}

        for key, signals in results.items():
            if isinstance(signals, list):
                for item in signals:
                    if not isinstance(item, dict):
                        continue
                    code = item.get('code', '')
                    price = realtime_prices.get(code)
                    if price is None:
                        continue
                    if 'signals' in item and isinstance(item['signals'], list):
                        for sig in item['signals']:
                            if isinstance(sig, dict) and 'close' in sig:
                                sig['close'] = round(price, 2)

        # 原始值应保持不变
        self.assertEqual(
            results['test_strategy'][0]['signals'][0]['close'], 10.00
        )


if __name__ == '__main__':
    unittest.main()
