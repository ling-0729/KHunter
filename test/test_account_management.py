# 账户管理功能单元测试
# 测试账户列表、当前账户、账户切换等功能

import unittest
import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading.dao import TradingAccountDAO, TradingPositionDAO, TradingTransactionDAO
from trading.service import TradingService


class TestAccountManagement(unittest.TestCase):
    """账户管理功能测试类"""

    @classmethod
    def setUpClass(cls):
        # 初始化DAO和服务
        cls.account_dao = TradingAccountDAO()
        cls.position_dao = TradingPositionDAO()
        cls.transaction_dao = TradingTransactionDAO()
        cls.service = TradingService(
            cls.account_dao,
            cls.position_dao,
            cls.transaction_dao
        )

    def test_get_all_accounts(self):
        # 测试获取所有账户
        result = self.service.get_all_accounts()
        
        # 验证返回结果
        self.assertTrue(result['success'], "获取账户列表应该成功")
        self.assertIn('data', result, "返回结果应该包含data字段")
        self.assertIn('accounts', result['data'], "data应该包含accounts字段")
        self.assertIn('total_count', result['data'], "data应该包含total_count字段")
        
        # 验证账户列表
        accounts = result['data']['accounts']
        self.assertIsInstance(accounts, list, "accounts应该是列表")
        
        # 验证账户数量
        total_count = result['data']['total_count']
        self.assertEqual(len(accounts), total_count, "账户数量应该与total_count一致")
        
        # 如果有账户，验证账户信息
        if len(accounts) > 0:
            account = accounts[0]
            self.assertIn('account_id', account, "账户应该包含account_id")
            self.assertIn('account_name', account, "账户应该包含account_name")
            self.assertIn('initial_cash', account, "账户应该包含initial_cash")
            self.assertIn('current_cash', account, "账户应该包含current_cash")
            self.assertIn('total_assets', account, "账户应该包含total_assets")
            self.assertIn('total_profit_loss', account, "账户应该包含total_profit_loss")
            self.assertIn('profit_loss_rate', account, "账户应该包含profit_loss_rate")
            self.assertIn('holding_count', account, "账户应该包含holding_count")
            self.assertIn('created_date', account, "账户应该包含created_date")
            self.assertIn('status', account, "账户应该包含status")

    def test_get_current_account_valid(self):
        # 测试获取有效的当前账户
        # 首先获取所有账户
        all_accounts_result = self.service.get_all_accounts()
        self.assertTrue(all_accounts_result['success'], "获取账户列表应该成功")
        
        accounts = all_accounts_result['data']['accounts']
        if len(accounts) > 0:
            # 使用第一个账户进行测试
            account_id = accounts[0]['account_id']
            
            # 获取当前账户
            result = self.service.get_current_account(account_id)
            
            # 验证返回结果
            self.assertTrue(result['success'], "获取当前账户应该成功")
            self.assertIn('data', result, "返回结果应该包含data字段")
            
            # 验证账户信息
            account = result['data']
            self.assertEqual(account['account_id'], account_id, "账户ID应该匹配")
            self.assertIn('account_name', account, "账户应该包含account_name")
            self.assertIn('initial_cash', account, "账户应该包含initial_cash")
            self.assertIn('current_cash', account, "账户应该包含current_cash")
            self.assertIn('total_assets', account, "账户应该包含total_assets")
            self.assertIn('total_profit_loss', account, "账户应该包含total_profit_loss")
            self.assertIn('profit_loss_rate', account, "账户应该包含profit_loss_rate")
            self.assertIn('holding_count', account, "账户应该包含holding_count")
            self.assertIn('created_date', account, "账户应该包含created_date")
            self.assertIn('updated_date', account, "账户应该包含updated_date")
            self.assertIn('status', account, "账户应该包含status")

    def test_get_current_account_invalid(self):
        # 测试获取无效的当前账户
        result = self.service.get_current_account('invalid_account_id')
        
        # 验证返回结果
        self.assertFalse(result['success'], "获取无效账户应该失败")
        self.assertIn('message', result, "返回结果应该包含message字段")
        self.assertIn('账户不存在', result['message'], "错误信息应该提示账户不存在")

    def test_account_list_contains_test_account(self):
        # 测试账户列表是否包含两个账户
        result = self.service.get_all_accounts()
        
        # 验证返回结果
        self.assertTrue(result['success'], "获取账户列表应该成功")
        
        # 查找两个账户
        accounts = result['data']['accounts']
        account_ids = {a['account_id']: a for a in accounts}
        
        # 验证找到两个账户
        self.assertEqual(len(accounts), 2, "应该找到两个账户")
        self.assertIn('test_account', account_ids, "应该找到测试账户")
        self.assertIn('trading_account', account_ids, "应该找到实际模拟交易账户")
        
        # 验证账户名称
        self.assertEqual(account_ids['test_account']['account_name'], '测试账户', "测试账户名称应该正确")
        self.assertEqual(account_ids['trading_account']['account_name'], '实际模拟交易账户', "实际模拟交易账户名称应该正确")

    def test_account_initial_cash(self):
        # 测试账户初始资金
        result = self.service.get_all_accounts()
        
        # 验证返回结果
        self.assertTrue(result['success'], "获取账户列表应该成功")
        
        # 检查所有账户的初始资金
        accounts = result['data']['accounts']
        for account in accounts:
            # 初始资金应该大于0
            self.assertGreater(account['initial_cash'], 0, "初始资金应该大于0")
            # 总资产应该大于等于初始资金
            self.assertGreaterEqual(account['total_assets'], 0, "总资产应该大于等于0")

    def test_account_status(self):
        # 测试账户状态
        result = self.service.get_all_accounts()
        
        # 验证返回结果
        self.assertTrue(result['success'], "获取账户列表应该成功")
        
        # 检查所有账户的状态
        accounts = result['data']['accounts']
        for account in accounts:
            # 状态应该是active
            self.assertEqual(account['status'], 'active', "账户状态应该是active")

    def test_account_holding_count(self):
        # 测试账户持仓数量
        result = self.service.get_all_accounts()
        
        # 验证返回结果
        self.assertTrue(result['success'], "获取账户列表应该成功")
        
        # 检查所有账户的持仓数量
        accounts = result['data']['accounts']
        for account in accounts:
            # 持仓数量应该大于等于0
            self.assertGreaterEqual(account['holding_count'], 0, "持仓数量应该大于等于0")


class TestAccountDataIntegrity(unittest.TestCase):
    """账户数据完整性测试类"""

    @classmethod
    def setUpClass(cls):
        # 初始化DAO和服务
        cls.account_dao = TradingAccountDAO()
        cls.position_dao = TradingPositionDAO()
        cls.transaction_dao = TradingTransactionDAO()
        cls.service = TradingService(
            cls.account_dao,
            cls.position_dao,
            cls.transaction_dao
        )

    def test_account_data_consistency(self):
        # 测试账户数据一致性
        result = self.service.get_all_accounts()
        
        # 验证返回结果
        self.assertTrue(result['success'], "获取账户列表应该成功")
        
        # 检查所有账户的数据一致性
        accounts = result['data']['accounts']
        for account in accounts:
            # 获取当前账户详细信息
            detail_result = self.service.get_current_account(account['account_id'])
            self.assertTrue(detail_result['success'], "获取账户详细信息应该成功")
            
            # 验证数据一致性
            detail = detail_result['data']
            self.assertEqual(account['account_id'], detail['account_id'], "账户ID应该一致")
            self.assertEqual(account['account_name'], detail['account_name'], "账户名称应该一致")
            self.assertEqual(account['initial_cash'], detail['initial_cash'], "初始资金应该一致")
            self.assertEqual(account['current_cash'], detail['current_cash'], "可用资金应该一致")
            self.assertEqual(account['total_assets'], detail['total_assets'], "总资产应该一致")
            self.assertEqual(account['total_profit_loss'], detail['total_profit_loss'], "总收益应该一致")
            self.assertEqual(account['profit_loss_rate'], detail['profit_loss_rate'], "收益率应该一致")
            self.assertEqual(account['holding_count'], detail['holding_count'], "持仓数量应该一致")

    def test_account_total_count_accuracy(self):
        # 测试账户总数准确性
        result = self.service.get_all_accounts()
        
        # 验证返回结果
        self.assertTrue(result['success'], "获取账户列表应该成功")
        
        # 验证总数准确性
        accounts = result['data']['accounts']
        total_count = result['data']['total_count']
        self.assertEqual(len(accounts), total_count, "账户数量应该与total_count一致")


if __name__ == '__main__':
    # 运行测试
    unittest.main()
