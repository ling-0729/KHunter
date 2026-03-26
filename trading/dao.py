# 模拟交易数据访问层 (DAO)
# 提供数据库操作接口

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
import os

# 获取数据库路径
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'stock_selection.db')


class TradingAccountDAO:
    """账户数据访问对象"""

    @staticmethod
    def get_connection():
        # 获取数据库连接
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def get_account(account_id: str) -> Optional[Dict[str, Any]]:
        # 根据账户ID获取账户信息
        conn = TradingAccountDAO.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM trading_account WHERE account_id = ?',
                (account_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_default_account() -> Optional[Dict[str, Any]]:
        # 获取默认账户
        return TradingAccountDAO.get_account('ACC_DEFAULT')

    @staticmethod
    def get_all_accounts() -> List[Dict[str, Any]]:
        # 获取所有活跃账户
        conn = TradingAccountDAO.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM trading_account WHERE status = ? ORDER BY created_date ASC',
                ('active',)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def create_account(account_id: str, account_name: str,
                      initial_cash: float) -> bool:
        # 创建新账户
        conn = TradingAccountDAO.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d')
            cursor.execute(
                '''INSERT INTO trading_account
                   (account_id, account_name, initial_cash, current_cash,
                    total_assets, total_profit_loss, profit_loss_rate,
                    created_date, updated_date, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (account_id, account_name, initial_cash, initial_cash,
                 initial_cash, 0.0, 0.0, now, now, 'active')
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    @staticmethod
    def update_account(account_id: str, current_cash: float,
                      total_assets: float) -> bool:
        # 更新账户信息（资金和总资产）
        conn = TradingAccountDAO.get_connection()
        try:
            cursor = conn.cursor()
            # 计算总收益和收益率
            account = TradingAccountDAO.get_account(account_id)
            if not account:
                return False

            initial_cash = account['initial_cash']
            total_profit_loss = total_assets - initial_cash
            profit_loss_rate = (total_profit_loss / initial_cash * 100
                               if initial_cash > 0 else 0)
            now = datetime.now().strftime('%Y-%m-%d')

            cursor.execute(
                '''UPDATE trading_account
                   SET current_cash = ?, total_assets = ?,
                       total_profit_loss = ?, profit_loss_rate = ?,
                       updated_date = ?
                   WHERE account_id = ?''',
                (current_cash, total_assets, total_profit_loss,
                 profit_loss_rate, now, account_id)
            )
            conn.commit()
            return True
        finally:
            conn.close()


class TradingPositionDAO:
    """持仓数据访问对象"""

    @staticmethod
    def get_connection():
        # 获取数据库连接
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def get_position(position_id: str) -> Optional[Dict[str, Any]]:
        # 根据持仓ID获取持仓信息
        conn = TradingPositionDAO.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM trading_position WHERE position_id = ?',
                (position_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_position_by_stock(account_id: str,
                             stock_code: str) -> Optional[Dict[str, Any]]:
        # 根据账户和股票代码获取持仓
        conn = TradingPositionDAO.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT * FROM trading_position
                   WHERE account_id = ? AND stock_code = ?''',
                (account_id, stock_code)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_positions(account_id: str) -> List[Dict[str, Any]]:
        # 获取账户的所有持仓
        conn = TradingPositionDAO.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM trading_position WHERE account_id = ?',
                (account_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def create_position(position_id: str, account_id: str,
                       stock_code: str, stock_name: str,
                       quantity: int, cost_price: float,
                       current_price: float, last_buy_date: str = None) -> bool:
        # 创建新持仓
        # 参数: position_id, account_id, stock_code, stock_name, quantity, cost_price, current_price, last_buy_date
        conn = TradingPositionDAO.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d')
            # 如果未指定last_buy_date，使用当前日期
            if last_buy_date is None:
                last_buy_date = now
            market_value = quantity * current_price
            profit_loss = market_value - (quantity * cost_price)
            profit_loss_rate = (profit_loss / (quantity * cost_price) * 100
                               if quantity * cost_price > 0 else 0)

            cursor.execute(
                '''INSERT INTO trading_position
                   (position_id, account_id, stock_code, stock_name,
                    quantity, cost_price, current_price, market_value,
                    profit_loss, profit_loss_rate, last_buy_date,
                    created_date, updated_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (position_id, account_id, stock_code, stock_name,
                 quantity, cost_price, current_price, market_value,
                 profit_loss, profit_loss_rate, last_buy_date, now, now)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    @staticmethod
    def update_position(position_id: str, quantity: int,
                       cost_price: float, current_price: float,
                       last_buy_date: str) -> bool:
        # 更新持仓信息
        conn = TradingPositionDAO.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d')
            market_value = quantity * current_price
            profit_loss = market_value - (quantity * cost_price)
            profit_loss_rate = (profit_loss / (quantity * cost_price) * 100
                               if quantity * cost_price > 0 else 0)

            cursor.execute(
                '''UPDATE trading_position
                   SET quantity = ?, cost_price = ?, current_price = ?,
                       market_value = ?, profit_loss = ?,
                       profit_loss_rate = ?, last_buy_date = ?,
                       updated_date = ?
                   WHERE position_id = ?''',
                (quantity, cost_price, current_price, market_value,
                 profit_loss, profit_loss_rate, last_buy_date, now,
                 position_id)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    def delete_position(position_id: str) -> bool:
        # 删除持仓
        conn = TradingPositionDAO.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM trading_position WHERE position_id = ?',
                (position_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


class TradingTransactionDAO:
    """交易记录数据访问对象"""

    @staticmethod
    def get_connection():
        # 获取数据库连接
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def get_transaction(transaction_id: str) -> Optional[Dict[str, Any]]:
        # 根据交易ID获取交易记录
        conn = TradingTransactionDAO.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM trading_transaction WHERE transaction_id = ?',
                (transaction_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def create_transaction(transaction_id: str, account_id: str,
                          stock_code: str, stock_name: str,
                          transaction_type: str, quantity: int,
                          price: float, amount: float, commission: float,
                          stamp_tax: float, total_cost: float,
                          profit_loss: Optional[float],
                          transaction_date: str) -> bool:
        # 创建交易记录
        conn = TradingTransactionDAO.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute(
                '''INSERT INTO trading_transaction
                   (transaction_id, account_id, stock_code, stock_name,
                    transaction_type, quantity, price, amount, commission,
                    stamp_tax, total_cost, profit_loss, transaction_date,
                    created_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (transaction_id, account_id, stock_code, stock_name,
                 transaction_type, quantity, price, amount, commission,
                 stamp_tax, total_cost, profit_loss, transaction_date, now)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    @staticmethod
    def get_transactions(account_id: str, start_date: Optional[str] = None,
                        end_date: Optional[str] = None,
                        stock_code: Optional[str] = None,
                        page: int = 1, limit: int = 20) -> Dict[str, Any]:
        # 获取交易历史（支持筛选和分页）
        conn = TradingTransactionDAO.get_connection()
        try:
            cursor = conn.cursor()
            # 构建查询条件
            where_clauses = ['account_id = ?']
            params = [account_id]

            if start_date:
                where_clauses.append('transaction_date >= ?')
                params.append(start_date)

            if end_date:
                where_clauses.append('transaction_date <= ?')
                params.append(end_date)

            if stock_code:
                where_clauses.append('stock_code = ?')
                params.append(stock_code)

            where_sql = ' AND '.join(where_clauses)

            # 获取总数
            cursor.execute(
                f'SELECT COUNT(*) as total FROM trading_transaction WHERE {where_sql}',
                params
            )
            total = cursor.fetchone()['total']

            # 获取分页数据
            offset = (page - 1) * limit
            cursor.execute(
                f'''SELECT * FROM trading_transaction
                   WHERE {where_sql}
                   ORDER BY transaction_date DESC, created_date DESC
                   LIMIT ? OFFSET ?''',
                params + [limit, offset]
            )
            rows = cursor.fetchall()
            transactions = [dict(row) for row in rows]

            return {
                'total': total,
                'page': page,
                'limit': limit,
                'transactions': transactions
            }
        finally:
            conn.close()

    @staticmethod
    def get_last_buy_date(account_id: str, stock_code: str) -> Optional[str]:
        # 获取最后一次买入日期
        conn = TradingTransactionDAO.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT MAX(transaction_date) as last_buy_date
                   FROM trading_transaction
                   WHERE account_id = ? AND stock_code = ?
                   AND transaction_type = 'buy' ''',
                (account_id, stock_code)
            )
            row = cursor.fetchone()
            return row['last_buy_date'] if row and row['last_buy_date'] else None
        finally:
            conn.close()
