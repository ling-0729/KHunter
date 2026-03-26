# 模拟交易 DAO 层单元测试

import unittest
import sqlite3
import os
import sys
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading.dao import (
    TradingAccountDAO,
    TradingPositionDAO,
    TradingTransactionDAO
)

# 测试数据库路径
TEST_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'data',
    'stock_selection.db'
)


class TestTradingAccountDAO(unittest.TestCase):
    """账户 DAO 测试"""

    @classmethod
    def setUpClass(cls):
        # 初始化测试数据库表
        cls._init_db()

    @staticmethod
    def _init_db():
        # 初始化数据库表
        conn = sqlite3.connect(TEST_DB_PATH)
        cursor = conn.cursor()

        # 删除旧表
        cursor.execute('DROP TABLE IF EXISTS trading_transaction')
        cursor.execute('DROP TABLE IF EXISTS trading_position')
        cursor.execute('DROP TABLE IF EXISTS trading_account')

        # 创建新表
        cursor.execute('''
            CREATE TABLE trading_account (
                account_id TEXT PRIMARY KEY,
                account_name TEXT NOT NULL,
                initial_cash REAL NOT NULL,
                current_cash REAL NOT NULL,
                total_assets REAL NOT NULL,
                total_profit_loss REAL DEFAULT 0,
                profit_loss_rate REAL DEFAULT 0,
                created_date TEXT NOT NULL,
                updated_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
        ''')

        cursor.execute('''
            CREATE TABLE trading_position (
                position_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                cost_price REAL NOT NULL,
                current_price REAL NOT NULL,
                market_value REAL NOT NULL,
                profit_loss REAL NOT NULL,
                profit_loss_rate REAL NOT NULL,
                last_buy_date TEXT NOT NULL,
                created_date TEXT NOT NULL,
                updated_date TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES trading_account(account_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE trading_transaction (
                transaction_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                amount REAL NOT NULL,
                commission REAL NOT NULL,
                stamp_tax REAL DEFAULT 0,
                total_cost REAL NOT NULL,
                profit_loss REAL,
                transaction_date TEXT NOT NULL,
                created_date TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES trading_account(account_id)
            )
        ''')

        conn.commit()
        conn.close()

    def test_create_account(self):
        # 测试创建账户
        result = TradingAccountDAO.create_account(
            'ACC_TEST_001',
            '测试账户',
            1000000.0
        )
        self.assertTrue(result)

        # 验证账户是否创建成功
        account = TradingAccountDAO.get_account('ACC_TEST_001')
        self.assertIsNotNone(account)
        self.assertEqual(account['account_name'], '测试账户')
        self.assertEqual(account['initial_cash'], 1000000.0)
        self.assertEqual(account['current_cash'], 1000000.0)

    def test_get_account(self):
        # 测试获取账户
        TradingAccountDAO.create_account(
            'ACC_TEST_002',
            '测试账户2',
            500000.0
        )

        account = TradingAccountDAO.get_account('ACC_TEST_002')
        self.assertIsNotNone(account)
        self.assertEqual(account['account_id'], 'ACC_TEST_002')
        self.assertEqual(account['account_name'], '测试账户2')

    def test_update_account(self):
        # 测试更新账户
        TradingAccountDAO.create_account(
            'ACC_TEST_003',
            '测试账户3',
            1000000.0
        )

        # 更新账户资金
        result = TradingAccountDAO.update_account(
            'ACC_TEST_003',
            950000.0,
            1050000.0
        )
        self.assertTrue(result)

        # 验证更新
        account = TradingAccountDAO.get_account('ACC_TEST_003')
        self.assertEqual(account['current_cash'], 950000.0)
        self.assertEqual(account['total_assets'], 1050000.0)
        self.assertEqual(account['total_profit_loss'], 50000.0)

    def test_duplicate_account(self):
        # 测试重复创建账户
        TradingAccountDAO.create_account(
            'ACC_TEST_004',
            '测试账户4',
            1000000.0
        )

        # 尝试创建相同ID的账户
        result = TradingAccountDAO.create_account(
            'ACC_TEST_004',
            '测试账户4',
            1000000.0
        )
        self.assertFalse(result)


class TestTradingPositionDAO(unittest.TestCase):
    """持仓 DAO 测试"""

    @classmethod
    def setUpClass(cls):
        # 初始化测试数据库表
        TestTradingAccountDAO._init_db()
        # 创建测试账户
        TradingAccountDAO.create_account(
            'ACC_POS_TEST',
            '持仓测试账户',
            1000000.0
        )

    def test_create_position(self):
        # 测试创建持仓
        result = TradingPositionDAO.create_position(
            'POS_TEST_001',
            'ACC_POS_TEST',
            '000001',
            '平安银行',
            100,
            10.5,
            11.0
        )
        self.assertTrue(result)

        # 验证持仓是否创建成功
        position = TradingPositionDAO.get_position('POS_TEST_001')
        self.assertIsNotNone(position)
        self.assertEqual(position['stock_code'], '000001')
        self.assertEqual(position['quantity'], 100)
        self.assertEqual(position['cost_price'], 10.5)

    def test_get_position_by_stock(self):
        # 测试根据股票代码获取持仓
        TradingPositionDAO.create_position(
            'POS_TEST_002',
            'ACC_POS_TEST',
            '000002',
            '万科A',
            50,
            20.0,
            21.0
        )

        position = TradingPositionDAO.get_position_by_stock(
            'ACC_POS_TEST',
            '000002'
        )
        self.assertIsNotNone(position)
        self.assertEqual(position['stock_name'], '万科A')

    def test_get_positions(self):
        # 测试获取账户的所有持仓
        TradingPositionDAO.create_position(
            'POS_TEST_003',
            'ACC_POS_TEST',
            '000003',
            '平安银行',
            100,
            10.5,
            11.0
        )
        TradingPositionDAO.create_position(
            'POS_TEST_004',
            'ACC_POS_TEST',
            '000004',
            '万科A',
            50,
            20.0,
            21.0
        )

        positions = TradingPositionDAO.get_positions('ACC_POS_TEST')
        self.assertGreaterEqual(len(positions), 2)

    def test_update_position(self):
        # 测试更新持仓
        TradingPositionDAO.create_position(
            'POS_TEST_005',
            'ACC_POS_TEST',
            '000005',
            '平安银行',
            100,
            10.5,
            11.0
        )

        # 更新持仓（增加数量）
        result = TradingPositionDAO.update_position(
            'POS_TEST_005',
            150,
            10.67,
            11.0,
            datetime.now().strftime('%Y-%m-%d')
        )
        self.assertTrue(result)

        # 验证更新
        position = TradingPositionDAO.get_position('POS_TEST_005')
        self.assertEqual(position['quantity'], 150)

    def test_delete_position(self):
        # 测试删除持仓
        TradingPositionDAO.create_position(
            'POS_TEST_006',
            'ACC_POS_TEST',
            '000006',
            '平安银行',
            100,
            10.5,
            11.0
        )

        # 删除持仓
        result = TradingPositionDAO.delete_position('POS_TEST_006')
        self.assertTrue(result)

        # 验证删除
        position = TradingPositionDAO.get_position('POS_TEST_006')
        self.assertIsNone(position)


class TestTradingTransactionDAO(unittest.TestCase):
    """交易记录 DAO 测试"""

    @classmethod
    def setUpClass(cls):
        # 初始化测试数据库表
        TestTradingAccountDAO._init_db()
        # 创建测试账户
        TradingAccountDAO.create_account(
            'ACC_TXN_TEST',
            '交易测试账户',
            1000000.0
        )

    def test_create_transaction(self):
        # 测试创建交易记录
        result = TradingTransactionDAO.create_transaction(
            'TXN_TEST_001',
            'ACC_TXN_TEST',
            '000001',
            '平安银行',
            'buy',
            100,
            10.5,
            1050.0,
            5.25,
            0.0,
            1055.25,
            None,
            '2026-03-25'
        )
        self.assertTrue(result)

        # 验证交易记录是否创建成功
        transaction = TradingTransactionDAO.get_transaction('TXN_TEST_001')
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction['transaction_type'], 'buy')
        self.assertEqual(transaction['quantity'], 100)

    def test_get_transactions(self):
        # 测试获取交易历史
        TradingTransactionDAO.create_transaction(
            'TXN_TEST_002',
            'ACC_TXN_TEST',
            '000001',
            '平安银行',
            'buy',
            100,
            10.5,
            1050.0,
            5.25,
            0.0,
            1055.25,
            None,
            '2026-03-25'
        )
        TradingTransactionDAO.create_transaction(
            'TXN_TEST_003',
            'ACC_TXN_TEST',
            '000001',
            '平安银行',
            'sell',
            50,
            11.0,
            550.0,
            2.75,
            0.55,
            546.7,
            21.7,
            '2026-03-26'
        )

        # 获取所有交易
        result = TradingTransactionDAO.get_transactions('ACC_TXN_TEST')
        self.assertGreaterEqual(result['total'], 2)
        self.assertEqual(len(result['transactions']), result['total'])

    def test_get_transactions_with_filter(self):
        # 测试带筛选条件的交易查询
        result = TradingTransactionDAO.get_transactions(
            'ACC_TXN_TEST',
            start_date='2026-03-25',
            end_date='2026-03-26',
            stock_code='000001'
        )
        self.assertGreater(result['total'], 0)

    def test_get_last_buy_date(self):
        # 测试获取最后一次买入日期
        TradingTransactionDAO.create_transaction(
            'TXN_TEST_004',
            'ACC_TXN_TEST',
            '000002',
            '万科A',
            'buy',
            50,
            20.0,
            1000.0,
            5.0,
            0.0,
            1005.0,
            None,
            '2026-03-25'
        )

        last_buy_date = TradingTransactionDAO.get_last_buy_date(
            'ACC_TXN_TEST',
            '000002'
        )
        self.assertEqual(last_buy_date, '2026-03-25')


if __name__ == '__main__':
    unittest.main()
