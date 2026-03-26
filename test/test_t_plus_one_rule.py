# T+1 业务规则修复单元测试
# 测试正确的 T+1 规则实现：
# - 买入：任何时候都可以买入（无限制）
# - 卖出：当天没有买入时，可以卖出旧持仓
# - 卖出：当天有买入时，不能卖出任何东西
# 规则：当天可卖出数量 = 昨天已经持有的数量 - 当天已经卖出数量
#      当天买入的不能卖出（完全不能卖）

import unittest
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading.validators import BuyValidator, SellValidator


class TestBuyValidatorNoSameDayBuySell(unittest.TestCase):
    """买入验证器 - 同日买卖验证测试"""

    def test_buy_always_allowed_no_transactions(self):
        # 测试买入总是允许的（无交易记录）
        # 规则：买入没有限制
        valid, error = BuyValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            existing_transactions=[]
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_buy_allowed_with_same_day_sell(self):
        # 测试买入允许（即使同日有卖出记录）
        # 规则：买入没有限制
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'SELL',
                'quantity': 100
            }
        ]
        valid, error = BuyValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            existing_transactions=existing_transactions
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_buy_allowed_with_same_day_buy(self):
        # 测试买入允许（即使同日已有买入记录）
        # 规则：买入没有限制
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 1000
            }
        ]
        valid, error = BuyValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            existing_transactions=existing_transactions
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_buy_allowed_multiple_transactions(self):
        # 测试买入允许（多个交易记录）
        # 规则：买入没有限制
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 1000
            },
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'SELL',
                'quantity': 500
            },
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 500
            }
        ]
        valid, error = BuyValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            existing_transactions=existing_transactions
        )
        self.assertTrue(valid)
        self.assertIsNone(error)


class TestSellValidatorNoSameDayBuySell(unittest.TestCase):
    """卖出验证器 - 同日买卖验证测试"""

    def test_sell_allowed_no_transactions(self):
        # 测试卖出允许（无交易记录，即卖出旧持仓）
        # 规则：当天没有买入时，允许卖出任何数量
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=100,
            existing_transactions=[]
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_sell_rejected_same_day_buy_full(self):
        # 测试卖出拒绝（当天买入 1000，卖出 1000）
        # 规则：当天有买入时，不能卖出任何东西
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 1000
            }
        ]
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=1000,
            existing_transactions=existing_transactions
        )
        self.assertFalse(valid)
        self.assertIsNotNone(error)
        self.assertIn('当天买入的股票不能卖出', error)

    def test_sell_rejected_partial_same_day_buy(self):
        # 测试卖出拒绝（当天买入 1000，卖出 500）
        # 规则：当天有买入时，不能卖出任何东西
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 1000
            }
        ]
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=500,
            existing_transactions=existing_transactions
        )
        self.assertFalse(valid)
        self.assertIsNotNone(error)
        self.assertIn('当天买入的股票不能卖出', error)

    def test_sell_rejected_after_partial_sell(self):
        # 测试卖出拒绝（当天买入 1000，卖出 500，再卖出 500）
        # 规则：当天有买入时，不能卖出任何东西
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 1000
            },
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'SELL',
                'quantity': 500
            }
        ]
        # 第二次卖出 500 应该失败（因为当天有买入）
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=500,
            existing_transactions=existing_transactions
        )
        self.assertFalse(valid)
        self.assertIsNotNone(error)

    def test_sell_allowed_old_holding_no_buy(self):
        # 测试卖出允许（持有旧股票，当天没有买入，卖出旧股票）
        # 规则：当天没有买入时，允许卖出任何数量
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-24',
                'transaction_type': 'BUY',
                'quantity': 2000
            }
        ]
        # 当天卖出 2000 股（旧持仓，当天没有买入）
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=2000,
            existing_transactions=existing_transactions
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_sell_rejected_with_same_day_buy_multiple(self):
        # 测试卖出拒绝（当天买入 1000，卖出 300，再买入 500，卖出 1300）
        # 规则：当天有买入时，不能卖出任何东西
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 1000
            },
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'SELL',
                'quantity': 300
            },
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 500
            }
        ]
        # 卖出 1300 应该失败（因为当天有买入）
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=1300,
            existing_transactions=existing_transactions
        )
        self.assertFalse(valid)
        self.assertIsNotNone(error)

    def test_sell_allowed_different_stock(self):
        # 测试卖出允许（不同股票的交易不影响）
        # 规则：只检查同一股票的当天买入
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000002',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 1000
            }
        ]
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=100,
            existing_transactions=existing_transactions
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_sell_allowed_different_account(self):
        # 测试卖出允许（不同账户的交易不影响）
        # 规则：只检查同一账户的当天买入
        existing_transactions = [
            {
                'account_id': 'ACC002',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'BUY',
                'quantity': 1000
            }
        ]
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=100,
            existing_transactions=existing_transactions
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_sell_allowed_different_date(self):
        # 测试卖出允许（不同日期的交易不影响）
        # 规则：只检查同一日期的当天买入
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-24',
                'transaction_type': 'BUY',
                'quantity': 1000
            }
        ]
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=1000,
            existing_transactions=existing_transactions
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_sell_allowed_only_sell_no_buy(self):
        # 测试卖出允许（当天只有卖出，没有买入）
        # 规则：当天没有买入时，允许卖出任何数量
        existing_transactions = [
            {
                'account_id': 'ACC001',
                'stock_code': '000001',
                'transaction_date': '2026-03-25',
                'transaction_type': 'SELL',
                'quantity': 500
            }
        ]
        valid, error = SellValidator.validate_no_same_day_buy_sell(
            account_id='ACC001',
            stock_code='000001',
            transaction_date='2026-03-25',
            sell_quantity=1000,
            existing_transactions=existing_transactions
        )
        self.assertTrue(valid)
        self.assertIsNone(error)


if __name__ == '__main__':
    unittest.main()
