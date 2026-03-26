# 模拟交易业务逻辑层单元测试

import unittest
import sys
import os
import uuid

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading.service import TradingService
from trading.dao import (
    TradingAccountDAO,
    TradingPositionDAO,
    TradingTransactionDAO
)


class TestTradingService(unittest.TestCase):
    """交易服务测试"""

    @classmethod
    def setUpClass(cls):
        # 清空数据库中的所有交易数据
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'stock_selection.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM trading_transaction')
        cursor.execute('DELETE FROM trading_position')
        cursor.execute('DELETE FROM trading_account')
        conn.commit()
        
        # 重新初始化账户
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'TradingInitData.sql'), 'r', encoding='utf-8') as f:
            sql_script = f.read()
        cursor.executescript(sql_script)
        conn.commit()
        conn.close()

    def setUp(self):
        # 初始化 DAO 和 Service
        self.account_dao = TradingAccountDAO()
        self.position_dao = TradingPositionDAO()
        self.transaction_dao = TradingTransactionDAO()
        self.service = TradingService(
            self.account_dao,
            self.position_dao,
            self.transaction_dao
        )

        # 使用预定义的测试账户
        self.account_id = 'test_account'
        
        # 清空该账户的交易数据（保留账户本身）
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'stock_selection.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM trading_transaction WHERE account_id = ?', (self.account_id,))
        cursor.execute('DELETE FROM trading_position WHERE account_id = ?', (self.account_id,))
        # 重置账户资金
        cursor.execute('''UPDATE trading_account SET current_cash = 1000000.0, total_assets = 1000000.0,
                         total_profit_loss = 0.0, profit_loss_rate = 0.0 WHERE account_id = ?''', (self.account_id,))
        conn.commit()
        conn.close()

    def test_buy_success(self):
        # 测试买入成功
        result = self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False  # 禁用价格验证以便测试
        )
        self.assertTrue(result['success'], f"买入失败: {result['message']}")
        self.assertEqual(result['data']['quantity'], 100)
        self.assertEqual(result['data']['price'], 10.5)

    def test_buy_insufficient_cash(self):
        # 测试资金不足
        result = self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100000,
            price=100.0,
            transaction_date='2026-03-25',
            current_date='2026-03-25'
        )
        self.assertFalse(result['success'])
        self.assertIn('资金不足', result['message'])

    def test_buy_invalid_quantity(self):
        # 测试数量无效
        result = self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=0,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25'
        )
        self.assertFalse(result['success'])

    def test_buy_invalid_price(self):
        # 测试价格无效
        result = self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=0,
            transaction_date='2026-03-25',
            current_date='2026-03-25'
        )
        self.assertFalse(result['success'])

    def test_buy_future_date(self):
        # 测试未来日期
        result = self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-26',
            current_date='2026-03-25'
        )
        self.assertFalse(result['success'])

    def test_buy_account_not_exist(self):
        # 测试账户不存在
        result = self.service.buy(
            account_id='ACC_NOT_EXIST',
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25'
        )
        self.assertFalse(result['success'])
        self.assertIn('账户不存在', result['message'])

    def test_sell_success(self):
        # 先买入，再卖出
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False  # 禁用价格验证以便测试
        )

        # 测试卖出成功
        result = self.service.sell(
            account_id=self.account_id,
            stock_code='000001',
            quantity=50,
            price=11.0,
            transaction_date='2026-03-26',
            current_date='2026-03-26',
            validate_price=False  # 禁用价格验证以便测试
        )
        self.assertTrue(result['success'], f"卖出失败: {result['message']}")
        self.assertEqual(result['data']['quantity'], 50)

    def test_sell_position_not_exist(self):
        # 测试持仓不存在
        result = self.service.sell(
            account_id=self.account_id,
            stock_code='000002',
            quantity=50,
            price=11.0,
            transaction_date='2026-03-26',
            current_date='2026-03-26'
        )
        self.assertFalse(result['success'])
        self.assertIn('持仓不存在', result['message'])

    def test_sell_insufficient_position(self):
        # 先买入，再尝试卖出超过持仓数量
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False  # 禁用价格验证以便测试
        )

        # 测试卖出数量超过持仓
        result = self.service.sell(
            account_id=self.account_id,
            stock_code='000001',
            quantity=150,
            price=11.0,
            transaction_date='2026-03-26',
            current_date='2026-03-26'
        )
        self.assertFalse(result['success'])

    def test_sell_t_plus_one_violation(self):
        # 先买入，再尝试同日卖出
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False  # 禁用价格验证以便测试
        )

        # 测试同日卖出（违反T+1）
        result = self.service.sell(
            account_id=self.account_id,
            stock_code='000001',
            quantity=50,
            price=11.0,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False  # 禁用价格验证以便测试
        )
        self.assertFalse(result['success'])
        self.assertIn('T+1', result['message'])

    def test_get_account_summary(self):
        # 测试获取账户总览
        result = self.service.get_account_summary(self.account_id)
        self.assertTrue(result['success'])
        self.assertEqual(result['data']['current_cash'], 1000000.0)
        self.assertEqual(result['data']['holding_count'], 0)

    def test_get_positions_empty(self):
        # 测试获取空持仓列表
        result = self.service.get_positions(self.account_id)
        self.assertTrue(result['success'])
        self.assertEqual(len(result['data']['positions']), 0)

    def test_get_transactions_empty(self):
        # 测试获取空交易历史
        result = self.service.get_transactions(self.account_id)
        self.assertTrue(result['success'])
        self.assertEqual(result['data']['total'], 0)

    def test_buy_creates_position(self):
        # 测试买入后创建持仓
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False  # 禁用价格验证以便测试
        )

        # 验证持仓被创建
        position = self.position_dao.get_position_by_stock(
            self.account_id,
            '000001'
        )
        self.assertIsNotNone(position)
        self.assertEqual(position['quantity'], 100)

    def test_buy_records_transaction(self):
        # 测试买入后记录交易
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False  # 禁用价格验证以便测试
        )

        # 验证交易被记录
        result = self.transaction_dao.get_transactions(self.account_id)
        transactions = result.get('transactions', [])
        self.assertGreater(len(transactions), 0)

    def test_sell_deletes_position_when_all_sold(self):
        # 先买入，再全部卖出
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False  # 禁用价格验证以便测试
        )

        # 全部卖出
        self.service.sell(
            account_id=self.account_id,
            stock_code='000001',
            quantity=100,
            price=11.0,
            transaction_date='2026-03-26',
            current_date='2026-03-26',
            validate_price=False  # 禁用价格验证以便测试
        )

        # 验证持仓被删除
        position = self.position_dao.get_position_by_stock(
            self.account_id,
            '000001'
        )
        self.assertIsNone(position)

    def test_sell_updates_position_when_partial_sold(self):
        # 先买入，再部分卖出
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False  # 禁用价格验证以便测试
        )

        # 部分卖出
        self.service.sell(
            account_id=self.account_id,
            stock_code='000001',
            quantity=50,
            price=11.0,
            transaction_date='2026-03-26',
            current_date='2026-03-26',
            validate_price=False  # 禁用价格验证以便测试
        )

        # 验证持仓被更新
        position = self.position_dao.get_position_by_stock(
            self.account_id,
            '000001'
        )
        self.assertIsNotNone(position)
        self.assertEqual(position['quantity'], 50)

    def test_get_positions_returns_current_price(self):
        # 测试 get_positions 返回当前价格
        # 先买入一个持仓
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False
        )

        # 获取持仓列表
        result = self.service.get_positions(self.account_id)
        self.assertTrue(result['success'])
        self.assertEqual(len(result['data']['positions']), 1)
        
        # 验证返回的持仓包含当前价格
        position = result['data']['positions'][0]
        self.assertIn('current_price', position)
        self.assertIsNotNone(position['current_price'])
        self.assertGreater(position['current_price'], 0)

    def test_get_positions_with_multiple_holdings(self):
        # 测试 get_positions 返回多个持仓的当前价格
        # 买入第一个股票
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False
        )

        # 买入第二个股票
        self.service.buy(
            account_id=self.account_id,
            stock_code='000002',
            stock_name='万科A',
            quantity=50,
            price=20.0,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False
        )

        # 获取持仓列表
        result = self.service.get_positions(self.account_id)
        self.assertTrue(result['success'])
        self.assertEqual(len(result['data']['positions']), 2)
        
        # 验证每个持仓都有当前价格
        for position in result['data']['positions']:
            self.assertIn('current_price', position)
            self.assertIsNotNone(position['current_price'])
            self.assertGreater(position['current_price'], 0)

    def test_get_positions_calculates_market_value(self):
        # 测试 get_positions 正确计算市值
        # 买入持仓
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False
        )

        # 获取持仓列表
        result = self.service.get_positions(self.account_id)
        self.assertTrue(result['success'])
        
        position = result['data']['positions'][0]
        # 验证市值 = 数量 * 当前价格
        expected_market_value = position['quantity'] * position['current_price']
        self.assertAlmostEqual(
            position['market_value'],
            expected_market_value,
            places=2
        )

    def test_get_positions_calculates_profit_loss(self):
        # 测试 get_positions 正确计算收益
        # 买入持仓
        self.service.buy(
            account_id=self.account_id,
            stock_code='000001',
            stock_name='平安银行',
            quantity=100,
            price=10.5,
            transaction_date='2026-03-25',
            current_date='2026-03-25',
            validate_price=False
        )

        # 获取持仓列表
        result = self.service.get_positions(self.account_id)
        self.assertTrue(result['success'])
        
        position = result['data']['positions'][0]
        # 验证收益 = (当前价 - 成本价) * 数量
        expected_profit = (position['current_price'] - position['cost_price']) * position['quantity']
        self.assertAlmostEqual(
            position['profit_loss'],
            expected_profit,
            places=2
        )

    def test_get_positions_account_not_exist(self):
        # 测试获取不存在账户的持仓
        result = self.service.get_positions('ACC_NOT_EXIST')
        self.assertFalse(result['success'])
        self.assertIn('账户不存在', result['message'])


if __name__ == '__main__':
    unittest.main()
