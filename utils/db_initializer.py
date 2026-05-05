"""
数据库初始化模块
用于创建和初始化SQLite数据库表和初始数据
"""

import sqlite3
import logging
from pathlib import Path

# 配置日志
logger = logging.getLogger(__name__)


class DatabaseInitializer:
    """数据库初始化器"""
    
    def __init__(self, data_dir: str = 'data'):
        """
        初始化数据库初始化器
        
        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 数据库文件路径
        self.selection_db_path = self.data_dir / 'stock_selection.db'
        self.trading_db_path = self.data_dir / 'stock_selection.db'
    
    def init_all_databases(self):
        """初始化所有数据库"""
        # 初始化选股数据库
        self._init_selection_database()
        
        # 初始化交易数据库
        self._init_trading_database()
        
        logger.info("所有数据库初始化完成")
    
    def _init_selection_database(self):
        """初始化选股数据库"""
        try:
            conn = sqlite3.connect(str(self.selection_db_path))
            cursor = conn.cursor()
            
            # 先执行数据库迁移脚本（删除旧表，修复结构问题）
            migration_sql_path = self.data_dir / 'MigrationSql.sql'
            if migration_sql_path.exists():
                try:
                    with open(migration_sql_path, 'r', encoding='utf-8') as f:
                        migration_script = f.read()
                    # 使用 executescript 执行迁移脚本
                    cursor.executescript(migration_script)
                    logger.info("数据库迁移脚本执行完成")
                except Exception as e:
                    logger.warning(f"执行数据库迁移脚本失败: {e}")
            
            # 再执行数据库表定义脚本（创建新表或更新现有表）
            data_sql_path = self.data_dir / 'DataSql.sql'
            if data_sql_path.exists():
                try:
                    # 尝试使用UTF-8编码读取
                    with open(data_sql_path, 'r', encoding='utf-8') as f:
                        sql_script = f.read()
                except UnicodeDecodeError:
                    # 如果UTF-8失败，尝试使用GBK编码
                    try:
                        with open(data_sql_path, 'r', encoding='gbk') as f:
                            sql_script = f.read()
                    except UnicodeDecodeError:
                        # 如果GBK也失败，使用errors='ignore'忽略错误
                        with open(data_sql_path, 'r', encoding='utf-8', errors='ignore') as f:
                            sql_script = f.read()
                
                # 过滤掉空字符和其他无效字符
                sql_script = ''.join(c for c in sql_script if c.isprintable() or c in '\n\r\t')
                
                # 使用executescript执行脚本，支持CREATE TABLE IF NOT EXISTS
                cursor.executescript(sql_script)
                logger.info(f"选股数据库表创建成功: {self.selection_db_path}")
            else:
                logger.warning(f"数据库表定义脚本不存在: {data_sql_path}")
            
            # 验证新增表是否创建成功
            self._verify_new_tables(cursor)
            
            # 检查是否需要加载初始化数据
            # 只在stock_basic表为空时加载初始化数据
            cursor.execute("SELECT COUNT(*) FROM stock_basic")
            stock_count = cursor.fetchone()[0]
            
            if stock_count == 0:
                # 读取并执行初始化数据脚本
                init_data_path = self.data_dir / 'InitData.sql'
                if init_data_path.exists():
                    with open(init_data_path, 'r', encoding='utf-8') as f:
                        sql_script = f.read()
                    cursor.executescript(sql_script)
                    logger.info(f"选股数据库初始化数据加载成功: {self.selection_db_path}")
                else:
                    logger.warning(f"初始化数据脚本不存在: {init_data_path}")
            else:
                logger.info(f"选股数据库已有初始化数据，跳过数据加载")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"选股数据库初始化失败: {str(e)}")
            raise
    
    def _init_trading_database(self):
        """初始化交易数据库 - 创建表结构并加载初始化数据"""
        try:
            conn = sqlite3.connect(str(self.trading_db_path))
            cursor = conn.cursor()
            
            # 读取并执行交易数据库表定义脚本
            # 从DataSql.sql文件中读取表定义，因为交易表定义已经包含在其中
            data_sql_path = self.data_dir / 'DataSql.sql'
            if data_sql_path.exists():
                try:
                    # 尝试使用UTF-8编码读取
                    with open(data_sql_path, 'r', encoding='utf-8') as f:
                        sql_script = f.read()
                except UnicodeDecodeError:
                    # 如果UTF-8失败，尝试使用GBK编码
                    try:
                        with open(data_sql_path, 'r', encoding='gbk') as f:
                            sql_script = f.read()
                    except UnicodeDecodeError:
                        # 如果GBK也失败，使用errors='ignore'忽略错误
                        with open(data_sql_path, 'r', encoding='utf-8', errors='ignore') as f:
                            sql_script = f.read()
                
                # 过滤掉空字符和其他无效字符
                sql_script = ''.join(c for c in sql_script if c.isprintable() or c in '\n\r\t')
                
                # 使用executescript执行脚本，支持CREATE TABLE IF NOT EXISTS
                cursor.executescript(sql_script)
                logger.info(f"交易数据库表创建成功: {self.trading_db_path}")
            else:
                logger.warning(f"数据库表定义脚本不存在: {data_sql_path}")
            
            # 检查是否需要加载初始化数据
            # 只在trading_account表为空时加载初始化数据
            cursor.execute("SELECT COUNT(*) FROM trading_account")
            account_count = cursor.fetchone()[0]
            
            if account_count == 0:
                # 读取并执行初始化数据脚本
                init_data_path = self.data_dir / 'InitData.sql'
                if init_data_path.exists():
                    with open(init_data_path, 'r', encoding='utf-8') as f:
                        sql_script = f.read()
                    cursor.executescript(sql_script)
                    logger.info(f"交易数据库初始化数据加载成功: {self.trading_db_path}")
                else:
                    logger.warning(f"初始化数据脚本不存在: {init_data_path}")
            else:
                logger.info(f"交易数据库已有初始化数据，跳过数据加载")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"交易数据库初始化失败: {str(e)}")
            raise
    
    def _verify_new_tables(self, cursor):
        """
        验证新增表是否创建成功
        
        Args:
            cursor: 数据库游标
        """
        # 新增表列表
        new_tables = [
            'stock_industry',
            'stock_sector',
            'stock_sector_mapping',
            'stock_fund_flow',
            'sector_fund_flow',
            'stock_event',
            'stock_lhb',
            'stock_margin_trading',
            'backtest_config',
            'backtest_result',
            'backtest_trade'
        ]
        
        # 查询所有表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = {row[0] for row in cursor.fetchall()}
        
        # 验证新增表
        missing_tables = []
        for table in new_tables:
            if table not in existing_tables:
                missing_tables.append(table)
        
        if missing_tables:
            logger.warning(f"以下新增表未创建: {', '.join(missing_tables)}")
        else:
            logger.info(f"所有新增表创建成功: {', '.join(new_tables)}")
        
        return len(missing_tables) == 0
    
    def check_databases_exist(self) -> bool:
        """
        检查数据库是否存在
        
        Returns:
            bool: 如果两个数据库都存在则返回True
        """
        selection_exists = self.selection_db_path.exists()
        trading_exists = self.trading_db_path.exists()
        
        return selection_exists and trading_exists
    
    def get_database_info(self) -> dict:
        """
        获取数据库信息
        
        Returns:
            dict: 包含数据库路径和存在状态的字典
        """
        return {
            'selection_db': {
                'path': str(self.selection_db_path),
                'exists': self.selection_db_path.exists(),
                'size': self.selection_db_path.stat().st_size if self.selection_db_path.exists() else 0
            },
            'trading_db': {
                'path': str(self.trading_db_path),
                'exists': self.trading_db_path.exists(),
                'size': self.trading_db_path.stat().st_size if self.trading_db_path.exists() else 0
            }
        }
    
    def get_new_tables_info(self) -> dict:
        """
        获取新增表的信息
        
        Returns:
            dict: 包含新增表的创建状态和数据统计
        """
        # 新增表列表
        new_tables = {
            'stock_industry': '行业信息表',
            'stock_sector': '板块信息表',
            'stock_sector_mapping': '股票板块映射表',
            'stock_fund_flow': '个股资金流向表',
            'sector_fund_flow': '板块资金流向表',
            'stock_event': '事件信息表',
            'stock_lhb': '龙虎榜数据表',
            'stock_margin_trading': '融资融券数据表',
            'backtest_config': '回测配置表',
            'backtest_result': '回测结果表',
            'backtest_trade': '回测交易记录表'
        }
        
        info = {}
        
        try:
            if self.selection_db_path.exists():
                conn = sqlite3.connect(str(self.selection_db_path))
                cursor = conn.cursor()
                
                # 查询所有表
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                existing_tables = {row[0] for row in cursor.fetchall()}
                
                # 获取每个新增表的信息
                for table_name, table_desc in new_tables.items():
                    if table_name in existing_tables:
                        # 获取表中的数据行数
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        row_count = cursor.fetchone()[0]
                        info[table_name] = {
                            'description': table_desc,
                            'exists': True,
                            'row_count': row_count
                        }
                    else:
                        info[table_name] = {
                            'description': table_desc,
                            'exists': False,
                            'row_count': 0
                        }
                
                conn.close()
            else:
                # 数据库不存在，所有表都不存在
                for table_name, table_desc in new_tables.items():
                    info[table_name] = {
                        'description': table_desc,
                        'exists': False,
                        'row_count': 0
                    }
        
        except Exception as e:
            logger.error(f"获取新增表信息失败: {str(e)}")
        
        return info


def init_databases_if_needed(data_dir: str = 'data'):
    """
    初始化数据库，确保所有表都已创建
    
    即使数据库文件已存在，也会执行DataSql.sql来创建可能缺失的新表
    （使用CREATE TABLE IF NOT EXISTS，不会影响已有表和数据）
    
    Args:
        data_dir: 数据目录路径
    """
    initializer = DatabaseInitializer(data_dir)
    
    # 始终执行初始化，确保新增的表被创建
    # DataSql.sql使用CREATE TABLE IF NOT EXISTS，不会影响已有表
    logger.info("开始数据库初始化（确保所有表已创建）...")
    initializer.init_all_databases()
    logger.info("数据库初始化完成")
    
    return initializer
