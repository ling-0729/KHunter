"""
数据库管理器模块
提供数据库连接管理、CRUD操作、事务管理等功能
"""

import sqlite3
import logging
import threading
import time
import pandas as pd
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager
from threading import Lock, RLock

# 配置日志
logger = logging.getLogger(__name__)


class DBManager:
    """
    数据库管理器类
    提供SQLite数据库的连接管理、CRUD操作、事务管理等功能
    """
    
    def __init__(self, db_path: str = None, timeout: int = None):
        """
        初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径，默认从配置文件读取
            timeout: 数据库连接超时时间（秒），默认从配置文件读取
        """
        # 导入配置管理器
        from utils.db_config import get_db_config
        
        # 如果未指定路径，从配置文件读取
        if db_path is None:
            db_path = get_db_config().get_db_path()
        
        # 如果未指定超时时间，从配置文件读取
        if timeout is None:
            timeout = get_db_config().get_timeout()
        
        # db_path: 数据库文件路径，类型str，必填
        self.db_path = Path(db_path)
        # timeout: 连接超时时间，类型int，默认30秒
        self.timeout = timeout
        # 确保数据库目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 线程锁，用于保护事务状态（RLock支持同一线程重入）
        self._lock = RLock()
        # 全局写入锁，保证同一时刻只有一个写入事务（RLock支持重入）
        self._write_lock = RLock()
        # 线程本地存储，每个线程独立维护事务状态
        self._local = threading.local()
        # 线程本地连接池，key为线程ID，value为连接对象
        self._connection_pool: Dict[int, sqlite3.Connection] = {}
        # 连接池锁，保护连接池的并发访问
        self._pool_lock = RLock()
    
    # ==================== 线程本地事务状态访问器 ====================

    @property
    def _tx_connection(self):
        """获取当前线程的事务专用连接"""
        return getattr(self._local, 'tx_connection', None)

    @_tx_connection.setter
    def _tx_connection(self, value):
        """设置当前线程的事务专用连接"""
        self._local.tx_connection = value

    @property
    def _transaction_count(self):
        """获取当前线程的事务计数器"""
        return getattr(self._local, 'transaction_count', 0)

    @_transaction_count.setter
    def _transaction_count(self, value):
        """设置当前线程的事务计数器"""
        self._local.transaction_count = value

    @property
    def _has_write_lock(self):
        """获取当前线程是否持有写入锁"""
        return getattr(self._local, 'has_write_lock', False)

    @_has_write_lock.setter
    def _has_write_lock(self, value):
        """设置当前线程是否持有写入锁"""
        self._local.has_write_lock = value

    def connect(self) -> sqlite3.Connection:
        """
        获取数据库连接
        
        - 如果当前在事务中，返回事务专用连接（保证事务内连接一致性）
        - 否则从线程本地连接池获取连接（每个线程独立连接）
        
        Returns:
            sqlite3.Connection: 数据库连接对象
        """
        # 如果在事务中，直接返回事务专用连接，保证事务内所有操作使用同一连接
        if self._tx_connection is not None:
            return self._tx_connection
        
        # 获取当前线程ID，用于线程本地连接池
        thread_id = threading.get_ident()
        
        # 如果当前线程没有连接，创建新连接
        if thread_id not in self._connection_pool:
            try:
                # 创建SQLite连接，timeout设置为30秒等待锁释放
                conn = sqlite3.connect(
                    str(self.db_path),
                    timeout=30.0,
                    check_same_thread=False
                )
                # 启用外键约束，保证数据完整性
                conn.execute('PRAGMA foreign_keys = ON')
                # 启用 WAL 模式，提高并发读写性能
                conn.execute('PRAGMA journal_mode = WAL')
                # 设置 busy_timeout 为 30 秒，等待锁释放
                conn.execute('PRAGMA busy_timeout = 30000')
                # 降低同步级别，提高写入速度（WAL模式下安全）
                conn.execute('PRAGMA synchronous = NORMAL')
                # 增加缓存大小，减少磁盘 I/O
                conn.execute('PRAGMA cache_size = 10000')
                # 使用内存存储临时表，提高性能
                conn.execute('PRAGMA temp_store = MEMORY')
                # 设置行工厂，使查询结果可以按列名访问
                conn.row_factory = sqlite3.Row
                # 保存到线程本地连接池
                self._connection_pool[thread_id] = conn
                logger.debug(f"数据库连接成功(线程{thread_id}): {self.db_path}")
            except sqlite3.Error as e:
                logger.error(f"数据库连接失败: {str(e)}")
                raise
        
        return self._connection_pool[thread_id]
    
    def close(self):
        """
        关闭数据库连接
        
        关闭当前线程的连接，并从连接池中移除
        """
        # 获取当前线程ID
        thread_id = threading.get_ident()
        # 关闭线程本地连接
        if thread_id in self._connection_pool:
            try:
                self._connection_pool[thread_id].close()
                del self._connection_pool[thread_id]
                logger.debug(f"数据库连接已关闭(线程{thread_id}): {self.db_path}")
            except sqlite3.Error as e:
                logger.error(f"关闭数据库连接失败: {str(e)}")
    
    def execute(self, sql: str, params: Tuple = ()) -> sqlite3.Cursor:
        """
        执行SQL语句
        
        Args:
            sql: SQL语句
            params: SQL参数元组
        
        Returns:
            sqlite3.Cursor: 游标对象
        """
        # sql: SQL语句，类型str，必填
        # params: SQL参数，类型tuple，默认空元组
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(sql, params)
            # 移除高频debug日志，避免日志轮转导致的权限问题
            return cursor
        except sqlite3.Error as e:
            logger.error(f"SQL执行失败: {sql[:100]} - {str(e)}")
            raise
    
    def execute_with_retry(self, sql: str, params: Tuple = (), max_retries: int = 3) -> sqlite3.Cursor:
        """
        执行SQL语句，带重试机制
        
        - 在事务中使用事务专用连接，保证连接一致性
        - 遇到 'database is locked' 时使用指数退避重试
        - 最大重试次数默认 3 次
        
        Args:
            sql: SQL语句
            params: SQL参数元组
            max_retries: 最大重试次数，默认 3 次
        
        Returns:
            sqlite3.Cursor: 游标对象
        """
        for attempt in range(max_retries):
            try:
                # 直接调用 execute，execute 内部会通过 connect() 获取正确连接
                # 如果在事务中，connect() 返回事务专用连接，保证一致性
                return self.execute(sql, params)
            except sqlite3.OperationalError as e:
                # 检查是否是数据库锁定错误
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    # 指数退避：0.5s, 1.0s, 2.0s
                    wait_time = 0.5 * (2 ** attempt)
                    logger.warning(f"数据库被锁定，{wait_time}秒后重试（第{attempt + 1}次）")
                    time.sleep(wait_time)
                    continue
                else:
                    # 其他错误或已达到最大重试次数，直接抛出
                    logger.error(f"SQL执行失败（重试{attempt + 1}次后）: {sql[:100]} - {str(e)}")
                    raise
    
    def insert(self, table: str, data: Dict[str, Any]) -> int:
        """
        插入数据
        
        Args:
            table: 表名
            data: 数据字典，键为列名，值为列值
        
        Returns:
            int: 插入的行ID
        """
        # table: 表名，类型str，必填
        # data: 数据字典，类型dict，必填
        if not data:
            raise ValueError("插入数据不能为空")
        
        # 构建INSERT语句
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data])
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        values = tuple(data.values())
        
        try:
            cursor = self.execute(sql, values)
            # 只在非事务模式下提交
            if self._transaction_count == 0:
                conn = self.connect()
                conn.commit()
            logger.debug(f"数据插入成功: {table}")
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"数据插入失败: {table} - {str(e)}")
            raise
    
    def insert_many(self, table: str, data_list: List[Dict[str, Any]]) -> int:
        """
        批量插入数据
        
        Args:
            table: 表名
            data_list: 数据字典列表
        
        Returns:
            int: 插入的行数
        """
        # table: 表名，类型str，必填
        # data_list: 数据字典列表，类型list，必填
        if not data_list:
            return 0
        
        # 获取第一条数据的列名
        first_data = data_list[0]
        columns = ', '.join(first_data.keys())
        placeholders = ', '.join(['?' for _ in first_data])
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        
        try:
            conn = self.connect()
            cursor = conn.cursor()
            # 构建值列表
            values_list = [tuple(data.values()) for data in data_list]
            cursor.executemany(sql, values_list)
            # 只在非事务模式下提交
            if self._transaction_count == 0:
                conn.commit()
            logger.debug(f"批量数据插入成功: {table}, 行数: {len(data_list)}")
            return len(data_list)
        except sqlite3.Error as e:
            logger.error(f"批量数据插入失败: {table} - {str(e)}")
            raise
    
    def update(self, table: str, data: Dict[str, Any], where: Dict[str, Any]) -> int:
        """
        更新数据
        
        Args:
            table: 表名
            data: 更新数据字典
            where: WHERE条件字典
        
        Returns:
            int: 更新的行数
        """
        # table: 表名，类型str，必填
        # data: 更新数据，类型dict，必填
        # where: WHERE条件，类型dict，必填
        if not data or not where:
            raise ValueError("更新数据和WHERE条件不能为空")
        
        # 构建UPDATE语句
        set_clause = ', '.join([f"{k} = ?" for k in data.keys()])
        where_clause = ' AND '.join([f"{k} = ?" for k in where.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        values = tuple(list(data.values()) + list(where.values()))
        
        try:
            cursor = self.execute(sql, values)
            # 只在非事务模式下提交
            if self._transaction_count == 0:
                conn = self.connect()
                conn.commit()
            logger.debug(f"数据更新成功: {table}, 行数: {cursor.rowcount}")
            return cursor.rowcount
        except sqlite3.Error as e:
            logger.error(f"数据更新失败: {table} - {str(e)}")
            raise
    
    def delete(self, table: str, where: Dict[str, Any]) -> int:
        """
        删除数据
        
        Args:
            table: 表名
            where: WHERE条件字典
        
        Returns:
            int: 删除的行数
        """
        # table: 表名，类型str，必填
        # where: WHERE条件，类型dict，必填
        if not where:
            raise ValueError("WHERE条件不能为空")
        
        # 构建DELETE语句
        where_clause = ' AND '.join([f"{k} = ?" for k in where.keys()])
        sql = f"DELETE FROM {table} WHERE {where_clause}"
        values = tuple(where.values())
        
        try:
            cursor = self.execute(sql, values)
            # 只在非事务模式下提交
            if self._transaction_count == 0:
                conn = self.connect()
                conn.commit()
            logger.debug(f"数据删除成功: {table}, 行数: {cursor.rowcount}")
            return cursor.rowcount
        except sqlite3.Error as e:
            logger.error(f"数据删除失败: {table} - {str(e)}")
            raise
    
    def query(self, sql: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """
        查询数据
        
        Args:
            sql: SQL查询语句
            params: SQL参数元组
        
        Returns:
            List[Dict]: 查询结果列表，每行为字典
        """
        # sql: SQL查询语句，类型str，必填
        # params: SQL参数，类型tuple，默认空元组
        import time
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                cursor = self.execute(sql, params)
                rows = cursor.fetchall()
                # 将sqlite3.Row对象转换为字典
                result = [dict(row) for row in rows]
                logger.debug(f"数据查询成功: 返回{len(result)}行")
                return result
            except sqlite3.OperationalError as e:
                # 检查是否是数据库锁定错误
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    # 计算等待时间（指数退避）
                    wait_time = 0.5 * (2 ** attempt)
                    logger.warning(f"数据库被锁定，{wait_time}秒后重试（第{attempt + 1}次）")
                    # 等待后重试
                    time.sleep(wait_time)
                    continue
                else:
                    # 其他错误或已达到最大重试次数，直接抛出异常
                    logger.error(f"数据查询失败（重试{attempt + 1}次后）: {sql[:100]} - {str(e)}")
                    raise
            except sqlite3.Error as e:
                logger.error(f"数据查询失败: {sql[:100]} - {str(e)}")
                raise
    
    def query_one(self, sql: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        """
        查询单条数据
        
        Args:
            sql: SQL查询语句
            params: SQL参数元组
        
        Returns:
            Dict or None: 查询结果字典，如果没有结果返回None
        """
        # sql: SQL查询语句，类型str，必填
        # params: SQL参数，类型tuple，默认空元组
        import time
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                cursor = self.execute(sql, params)
                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    logger.debug(f"单条数据查询成功")
                    return result
                return None
            except sqlite3.OperationalError as e:
                # 检查是否是数据库锁定错误
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    # 计算等待时间（指数退避）
                    wait_time = 0.5 * (2 ** attempt)
                    logger.warning(f"数据库被锁定，{wait_time}秒后重试（第{attempt + 1}次）")
                    # 等待后重试
                    time.sleep(wait_time)
                    continue
                else:
                    # 其他错误或已达到最大重试次数，直接抛出异常
                    logger.error(f"单条数据查询失败（重试{attempt + 1}次后）: {sql[:100]} - {str(e)}")
                    raise
            except sqlite3.Error as e:
                logger.error(f"单条数据查询失败: {sql[:100]} - {str(e)}")
                raise
    
    def begin_transaction(self):
        """
        开始事务
        
        - 获取全局写入锁，保证同一时刻只有一个写入事务
        - 保存事务专用连接，确保事务内所有操作使用同一连接
        - 执行 BEGIN IMMEDIATE 立即获取写入锁，避免锁升级冲突
        - 支持嵌套事务（通过线程本地计数器实现）
        """
        if self._transaction_count == 0:
            # 获取全局写入锁（阻塞直到获取成功）
            self._write_lock.acquire()
            # 标记当前线程持有写入锁
            self._has_write_lock = True
            try:
                # 获取连接并保存为事务专用连接
                conn = self.connect()
                self._tx_connection = conn
                # BEGIN IMMEDIATE 立即获取写入锁，避免后续锁升级失败
                conn.execute('BEGIN IMMEDIATE')
                logger.debug("事务开始（已获取写入锁）")
            except sqlite3.Error as e:
                # 事务开始失败，释放写入锁并清空事务连接
                self._tx_connection = None
                self._has_write_lock = False
                self._write_lock.release()
                logger.error(f"事务开始失败: {str(e)}")
                raise
        # 嵌套事务：计数器加1
        self._transaction_count += 1
    
    def commit(self):
        """
        提交事务
        
        - 只有最外层事务（计数器归零）才真正提交
        - 提交后清空事务专用连接
        - 释放全局写入锁
        """
        # 嵌套事务：计数器减1
        self._transaction_count -= 1
        if self._transaction_count == 0:
            try:
                # 提交事务
                if self._tx_connection:
                    self._tx_connection.commit()
                logger.debug("事务提交成功")
            except sqlite3.Error as e:
                logger.error(f"事务提交失败: {str(e)}")
                raise
            finally:
                # 无论成功失败，都清空事务连接并释放写入锁
                self._tx_connection = None
                if self._has_write_lock:
                    self._has_write_lock = False
                    self._write_lock.release()

    def rollback(self):
        """
        回滚事务
        
        - 无论嵌套层级，立即回滚并重置计数器
        - 清空事务专用连接
        - 释放全局写入锁（仅当当前线程持有时）
        """
        # 记录是否需要释放锁
        had_lock = self._has_write_lock
        # 重置事务计数器
        self._transaction_count = 0
        try:
            # 回滚事务
            if self._tx_connection:
                self._tx_connection.rollback()
            logger.debug("事务回滚成功")
        except sqlite3.Error as e:
            logger.error(f"事务回滚失败: {str(e)}")
        finally:
            # 清空事务连接
            self._tx_connection = None
            # 释放写入锁（仅当当前线程持有时）
            if had_lock:
                self._has_write_lock = False
                self._write_lock.release()
    
    @contextmanager
    def transaction(self):
        """
        事务上下文管理器
        
        Usage:
            with db_manager.transaction():
                db_manager.insert('table', data)
        """
        # 开始事务
        self.begin_transaction()
        try:
            yield
            # 提交事务
            self.commit()
        except Exception as e:
            # 回滚事务
            self.rollback()
            logger.error(f"事务执行失败，已回滚: {str(e)}")
            raise
    
    def get_table_count(self, table: str) -> int:
        """
        获取表中的行数
        
        Args:
            table: 表名
        
        Returns:
            int: 表中的行数
        """
        # table: 表名，类型str，必填
        try:
            sql = f"SELECT COUNT(*) as count FROM {table}"
            result = self.query_one(sql)
            count = result['count'] if result else 0
            logger.debug(f"表行数查询成功: {table}, 行数: {count}")
            return count
        except sqlite3.Error as e:
            logger.error(f"表行数查询失败: {table} - {str(e)}")
            raise
    
    def table_exists(self, table: str) -> bool:
        """
        检查表是否存在
        
        Args:
            table: 表名
        
        Returns:
            bool: 表是否存在
        """
        # table: 表名，类型str，必填
        try:
            sql = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
            result = self.query_one(sql, (table,))
            exists = result is not None
            logger.debug(f"表存在性检查: {table}, 存在: {exists}")
            return exists
        except sqlite3.Error as e:
            logger.error(f"表存在性检查失败: {table} - {str(e)}")
            raise
    
    def get_db_size(self) -> int:
        """
        获取数据库文件大小
        
        Returns:
            int: 数据库文件大小（字节）
        """
        # 获取数据库文件大小
        try:
            if self.db_path.exists():
                size = self.db_path.stat().st_size
                logger.debug(f"数据库大小: {size} 字节")
                return size
            return 0
        except Exception as e:
            logger.error(f"获取数据库大小失败: {str(e)}")
            raise
    
    def vacuum(self):
        """
        优化数据库，回收未使用的空间
        """
        # 执行VACUUM命令优化数据库
        try:
            conn = self.connect()
            conn.execute('VACUUM')
            conn.commit()
            logger.debug("数据库优化成功")
        except sqlite3.Error as e:
            logger.error(f"数据库优化失败: {str(e)}")
            raise
    
    def analyze(self):
        """
        分析数据库，更新查询优化器统计信息
        """
        # 执行ANALYZE命令更新统计信息
        try:
            conn = self.connect()
            conn.execute('ANALYZE')
            conn.commit()
            logger.debug("数据库分析成功")
        except sqlite3.Error as e:
            logger.error(f"数据库分析失败: {str(e)}")
            raise
    
    # ==================== CSV 替代方法 ====================
    # 以下方法用于替代 CSVManager，提供相同的接口
    
    def read_stock(self, stock_code: str, start_date: str = None, end_date: str = None, limit: int = None, order: str = 'desc') -> 'pd.DataFrame':
        """
        读取股票K线数据（替代 CSVManager.read_stock）

        Args:
            stock_code: 股票代码，例如000001
            start_date: 开始日期，格式为YYYY-MM-DD，None表示无限制
            end_date: 结束日期，格式为YYYY-MM-DD，None表示无限制
            limit: 限制返回的行数，None表示无限制
            order: 排序方式，'asc'升序(默认)或'desc'降序，默认返回最新数据

        Returns:
            pd.DataFrame: 股票数据，包含date, open, high, low, close, volume等列，date为索引
        """
        import pandas as pd

        try:
            # 从数据库查询股票数据
            sql = """
                SELECT code, date, open, high, low, close, volume, market_cap, K, D, J
                FROM stock_kline
                WHERE code = ?
            """
            params = [stock_code]

            # 添加日期范围条件（数据库中日期格式为 YYYYMMDD，需要转换）
            if start_date:
                start_date_formatted = start_date.replace('-', '')
                sql += " AND date >= ?"
                params.append(start_date_formatted)

            if end_date:
                end_date_formatted = end_date.replace('-', '')
                sql += " AND date <= ?"
                params.append(end_date_formatted)
            
            # 按日期排列，limit默认返回最新数据
            if order == 'desc':
                sql += " ORDER BY date DESC"
            else:
                sql += " ORDER BY date ASC"
            
            if limit:
                sql += f" LIMIT {limit}"
            
            results = self.query(sql, tuple(params))
            
            if not results:
                logger.debug(f"股票数据为空: {stock_code}")
                return pd.DataFrame()
            
            # 转换为DataFrame
            df = pd.DataFrame(results)
            # 转换date列为datetime类型
            df['date'] = pd.to_datetime(df['date'])
            logger.debug(f"读取股票数据成功: {stock_code}, 行数: {len(df)}")
            return df
        except Exception as e:
            logger.error(f"读取股票数据失败: {stock_code} - {str(e)}")
            return pd.DataFrame()
    
    def write_stock(self, stock_code: str, df: 'pd.DataFrame') -> bool:
        """
        写入股票K线数据（替代 CSVManager.write_stock）
        
        Args:
            stock_code: 股票代码
            df: 股票数据DataFrame，必须包含date列
        
        Returns:
            bool: 是否写入成功
        """
        # stock_code: 股票代码，类型str，必填
        # df: 股票数据，类型DataFrame，必填
        if df.empty:
            logger.warning(f"股票数据为空，跳过写入: {stock_code}")
            return False
        
        try:
            # 去重：按日期去重，保留最后出现的
            df = df.drop_duplicates(subset=['date'], keep='last')
            
            # 准备数据列表
            data_list = []
            for _, row in df.iterrows():
                data = {
                    'code': stock_code,
                    'date': str(row['date']).split()[0] if hasattr(row['date'], '__str__') else row['date'],
                    'open': float(row.get('open', 0)) if pd.notna(row.get('open')) else None,
                    'high': float(row.get('high', 0)) if pd.notna(row.get('high')) else None,
                    'low': float(row.get('low', 0)) if pd.notna(row.get('low')) else None,
                    'close': float(row.get('close', 0)) if pd.notna(row.get('close')) else None,
                    'volume': int(row.get('volume', 0)) if pd.notna(row.get('volume')) else None,
                    'market_cap': float(row.get('market_cap', 0)) if pd.notna(row.get('market_cap')) else None,
                    'K': float(row.get('K', 0)) if pd.notna(row.get('K')) else None,
                    'D': float(row.get('D', 0)) if pd.notna(row.get('D')) else None,
                    'J': float(row.get('J', 0)) if pd.notna(row.get('J')) else None,
                }
                data_list.append(data)
            
            # 使用事务批量插入或更新
            with self.transaction():
                for data in data_list:
                    # 先尝试删除已存在的数据
                    self.delete('stock_kline', {'code': stock_code, 'date': data['date']})
                    # 再插入新数据
                    self.insert('stock_kline', data)
            
            logger.debug(f"写入股票数据成功: {stock_code}, 行数: {len(data_list)}")
            return True
        except Exception as e:
            logger.error(f"写入股票数据失败: {stock_code} - {str(e)}")
            return False
    
    def update_stock(self, stock_code: str, new_df: 'pd.DataFrame') -> bool:
        """
        增量更新股票数据（替代 CSVManager.update_stock）
        
        Args:
            stock_code: 股票代码
            new_df: 新的股票数据DataFrame
        
        Returns:
            bool: 是否更新成功
        """
        # stock_code: 股票代码，类型str，必填
        # new_df: 新的股票数据，类型DataFrame，必填
        if new_df.empty:
            logger.warning(f"新股票数据为空，跳过更新: {stock_code}")
            return False
        
        try:
            # 读取现有数据
            existing_df = self.read_stock(stock_code)
            
            # 合并数据
            if not existing_df.empty:
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            else:
                combined_df = new_df
            
            # 写入合并后的数据
            return self.write_stock(stock_code, combined_df)
        except Exception as e:
            logger.error(f"更新股票数据失败: {stock_code} - {str(e)}")
            return False
    
    def list_all_stocks(self) -> List[str]:
        """
        列出所有已保存的股票代码（替代 CSVManager.list_all_stocks）
        
        Returns:
            List[str]: 股票代码列表，已排序
        """
        # 返回所有股票代码列表
        try:
            sql = "SELECT DISTINCT code FROM stock_kline ORDER BY code"
            results = self.query(sql)
            stocks = [row['code'] for row in results]
            logger.debug(f"列出所有股票成功，共{len(stocks)}只")
            return stocks
        except Exception as e:
            # 如果表不存在或查询失败，返回空列表
            logger.debug(f"列出所有股票失败: {str(e)}")
            return []
    
    def stock_exists(self, stock_code: str) -> bool:
        """
        检查股票数据是否存在（替代 CSVManager.stock_exists）
        
        Args:
            stock_code: 股票代码
        
        Returns:
            bool: 股票数据是否存在
        """
        # stock_code: 股票代码，类型str，必填
        try:
            sql = "SELECT COUNT(*) as count FROM stock_kline WHERE code = ?"
            result = self.query_one(sql, (stock_code,))
            exists = result and result['count'] > 0
            logger.debug(f"检查股票存在性: {stock_code}, 存在: {exists}")
            return exists
        except Exception as e:
            # 如果表不存在或查询失败，返回False
            logger.debug(f"检查股票存在性失败: {stock_code} - {str(e)}")
            return False
    
    def get_stock_count(self) -> int:
        """
        获取已保存的股票数量（替代 CSVManager.get_stock_count）
        
        Returns:
            int: 股票数量
        """
        # 返回不同股票代码的数量
        try:
            sql = "SELECT COUNT(DISTINCT code) as count FROM stock_kline"
            result = self.query_one(sql)
            count = result['count'] if result else 0
            logger.debug(f"获取股票数量成功: {count}")
            return count
        except Exception as e:
            # 如果表不存在或查询失败，返回0
            logger.debug(f"获取股票数量失败: {str(e)}")
            return 0

    def get_latest_trading_date(self) -> str:
        """
        获取数据库中所有股票的最晚交易日期（统一交易日）

        Returns:
            str: 最晚交易日期（YYYY-MM-DD格式），如果失败返回None
        """
        try:
            sql = "SELECT MAX(date) as max_date FROM stock_kline"
            result = self.query_one(sql)
            max_date = result['max_date'] if result and result.get('max_date') else None
            if max_date:
                if ' ' in str(max_date):
                    max_date = str(max_date).split()[0]
                # 转换为 YYYY-MM-DD 格式
                if len(str(max_date)) == 8:  # 20260430 格式
                    max_date = f"{str(max_date)[:4]}-{str(max_date)[4:6]}-{str(max_date)[6:8]}"
            logger.debug(f"获取最晚交易日期成功: {max_date}")
            return max_date
        except Exception as e:
            logger.debug(f"获取最晚交易日期失败: {str(e)}")
            return None

    def get_stock_name(self, stock_code: str) -> str:
        """
        从 stock_basic 表获取股票名称
        
        参数:
            stock_code: 股票代码（6位数字）
        
        返回:
            str: 股票名称，如果不存在则返回 '未知'
        """
        try:
            sql = "SELECT name FROM stock_basic WHERE code = ?"
            result = self.query_one(sql, (stock_code,))
            if result and result.get('name'):
                return result['name']
            return '未知'
        except Exception as e:
            logger.debug(f"获取股票名称失败: {stock_code} - {str(e)}")
            return '未知'
    
    def get_all_stock_names(self) -> dict:
        """
        获取所有股票的代码和名称映射
        
        返回:
            dict: {代码: 名称} 的字典
        """
        try:
            sql = "SELECT code, name FROM stock_basic WHERE code IS NOT NULL"
            results = self.query(sql)
            stock_names = {}
            for row in results:
                code = row.get('code')
                name = row.get('name', '未知')
                if code:
                    stock_names[code] = name
            logger.debug(f"获取所有股票名称成功: {len(stock_names)} 只")
            return stock_names
        except Exception as e:
            logger.debug(f"获取所有股票名称失败: {str(e)}")
            return {}
