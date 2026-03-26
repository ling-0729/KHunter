"""
选股记录管理器 - 负责选股结果的保存、查询和去重处理
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json

# 导入pandas用于数据处理
try:
    import pandas as pd
except ImportError:
    pd = None

# 获取日志记录器
logger = logging.getLogger(__name__)


class SelectionRecordManager:
    """
    选股记录管理器
    
    职责：
    - 保存选股结果到数据库
    - 处理去重逻辑（一个月判断）
    - 查询选股历史
    - 生成选股方案名称
    - 实时计算价格指标
    """
    
    def __init__(self, db_path: str = 'data/stock_selection.db'):
        """
        初始化数据库连接
        
        参数：
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        """初始化数据库连接和表结构"""
        try:
            # 创建数据库连接，禁用线程检查以支持多线程环境
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            
            # 创建表
            self._create_tables()
            logger.info(f"数据库初始化成功: {self.db_path}")
        except Exception as e:
            logger.error(f"数据库初始化失败: {str(e)}")
            raise
    
    def _create_tables(self):
        """创建数据库表"""
        cursor = self.conn.cursor()
        
        # 创建选股记录表
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS stock_selection_record (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name VARCHAR(100) NOT NULL,
            stock_code VARCHAR(20) NOT NULL,
            stock_name VARCHAR(50) NOT NULL,
            industry VARCHAR(50),
            sector VARCHAR(50),
            selection_date DATE NOT NULL,
            selection_time DATETIME NOT NULL,
            selection_price DECIMAL(10,2) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(stock_code, selection_date)
        )
        """
        cursor.execute(create_table_sql)
        
        # 创建索引
        index_sqls = [
            "CREATE INDEX IF NOT EXISTS idx_strategy_name ON stock_selection_record(strategy_name)",
            "CREATE INDEX IF NOT EXISTS idx_selection_date ON stock_selection_record(selection_date)",
            "CREATE INDEX IF NOT EXISTS idx_is_active ON stock_selection_record(is_active)",
            "CREATE INDEX IF NOT EXISTS idx_stock_code ON stock_selection_record(stock_code)"
        ]
        
        for sql in index_sqls:
            cursor.execute(sql)
        
        self.conn.commit()
        logger.info("数据库表创建成功")
    
    def save_selection_result(self, strategy_names: List[str], signals: List[Dict], 
                             selection_time: datetime) -> Dict:
        """
        保存选股结果
        
        参数：
            strategy_names: 策略名称列表 ['morning_star', 'bowl_rebound']
            signals: 选股信号列表 [{'code': '000001', 'name': '平安银行', ...}]
            selection_time: 选股执行时间
        
        返回：
            {'success': True, 'saved': 10, 'skipped': 5, 'updated': 2, 'error': 0}
        """
        try:
            # 生成选股方案名称
            strategy_name = self.generate_strategy_name(strategy_names)
            selection_date = selection_time.date()
            
            # 统计信息
            stats = {'saved': 0, 'skipped': 0, 'updated': 0, 'error': 0}
            
            cursor = self.conn.cursor()
            
            # 遍历每个选股信号
            for signal in signals:
                try:
                    stock_code = signal.get('code')
                    stock_name = signal.get('name', '未知')
                    
                    # 行业和板块信息不再实时获取，避免akshare连接失败导致保存报错
                    industry, sector = '', ''
                    
                    # 获取选入价格（使用信号中的价格或从CSV获取）
                    selection_price = signal.get('price', 0.0)
                    if selection_price == 0.0:
                        selection_price = self._get_stock_price(stock_code, selection_date)
                    
                    # 检查是否重复选入
                    duplicate_info = self.check_duplicate(stock_code, selection_date)
                    
                    if duplicate_info['is_duplicate']:
                        if duplicate_info['should_update']:
                            # 删除旧记录，保存新记录
                            self.delete_old_record(stock_code)
                            self._insert_record(cursor, strategy_name, stock_code, stock_name,
                                              industry, sector, selection_date, selection_time,
                                              selection_price)
                            stats['updated'] += 1
                        else:
                            # 一个月内，跳过
                            stats['skipped'] += 1
                    else:
                        # 新股票，直接保存
                        self._insert_record(cursor, strategy_name, stock_code, stock_name,
                                          industry, sector, selection_date, selection_time,
                                          selection_price)
                        stats['saved'] += 1
                
                except Exception as e:
                    logger.error(f"保存股票 {signal.get('code')} 失败: {str(e)}")
                    stats['error'] += 1
            
            # 提交事务
            self.conn.commit()
            
            logger.info(f"选股结果保存完成 - 保存: {stats['saved']}, 跳过: {stats['skipped']}, "
                       f"更新: {stats['updated']}, 错误: {stats['error']}")
            
            return {
                'success': True,
                'saved': stats['saved'],
                'skipped': stats['skipped'],
                'updated': stats['updated'],
                'error': stats['error']
            }
        
        except Exception as e:
            logger.error(f"保存选股结果失败: {str(e)}")
            self.conn.rollback()
            return {
                'success': False,
                'error': str(e)
            }
    
    def _insert_record(self, cursor, strategy_name: str, stock_code: str, stock_name: str,
                      industry: str, sector: str, selection_date, selection_time: datetime,
                      selection_price: float):
        """
        插入选股记录
        
        参数：
            cursor: 数据库游标
            strategy_name: 选股方案名称
            stock_code: 股票代码
            stock_name: 股票名称
            industry: 行业
            sector: 板块
            selection_date: 选入日期
            selection_time: 选入时间
            selection_price: 选入价格
        """
        insert_sql = """
        INSERT INTO stock_selection_record 
        (strategy_name, stock_code, stock_name, industry, sector, 
         selection_date, selection_time, selection_price, created_at, updated_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """
        
        now = datetime.now()
        cursor.execute(insert_sql, (
            strategy_name, stock_code, stock_name, industry, sector,
            selection_date, selection_time, selection_price, now, now
        ))
    
    def get_selection_history(self, filters: Optional[Dict] = None, 
                             page: int = 1, limit: int = 20) -> Dict:
        """
        查询选股历史
        
        参数：
            filters: 筛选条件 {
                'strategy_name': '晨星',
                'start_date': '2024-01-01',
                'end_date': '2024-01-31',
                'stock_code': '000001'
            }
            page: 分页页码
            limit: 每页数量
        
        返回：
            {'total': 100, 'page': 1, 'limit': 20, 'data': [...]}
        """
        try:
            filters = filters or {}
            
            # 构建查询SQL
            where_clauses = ["is_active = 1"]
            params = []
            
            # 添加筛选条件
            if filters.get('strategy_name'):
                where_clauses.append("strategy_name LIKE ?")
                params.append(f"%{filters['strategy_name']}%")
            
            if filters.get('start_date'):
                where_clauses.append("selection_date >= ?")
                params.append(filters['start_date'])
            
            if filters.get('end_date'):
                where_clauses.append("selection_date <= ?")
                params.append(filters['end_date'])
            
            if filters.get('stock_code'):
                where_clauses.append("stock_code = ?")
                params.append(filters['stock_code'])
            
            where_sql = " AND ".join(where_clauses)
            
            # 查询总数
            count_sql = f"SELECT COUNT(*) as total FROM stock_selection_record WHERE {where_sql}"
            cursor = self.conn.cursor()
            cursor.execute(count_sql, params)
            total = cursor.fetchone()['total']
            
            # 查询分页数据
            offset = (page - 1) * limit
            query_sql = f"""
            SELECT * FROM stock_selection_record 
            WHERE {where_sql}
            ORDER BY selection_date DESC, selection_time DESC
            LIMIT ? OFFSET ?
            """
            
            cursor.execute(query_sql, params + [limit, offset])
            rows = cursor.fetchall()
            
            # 转换为字典列表并计算价格指标
            data = []
            for row in rows:
                record = dict(row)
                
                # 实时计算价格指标
                performance = self.calculate_performance(
                    record['stock_code'],
                    record['selection_price'],
                    record['selection_date']
                )
                
                # 合并价格指标
                record.update(performance)
                data.append(record)
            
            logger.info(f"查询选股历史 - 总数: {total}, 页码: {page}, 每页: {limit}")
            
            return {
                'success': True,
                'total': total,
                'page': page,
                'limit': limit,
                'data': data
            }
        
        except Exception as e:
            logger.error(f"查询选股历史失败: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def check_duplicate(self, stock_code: str, selection_date) -> Dict:
        """
        检查是否重复选入
        
        参数：
            stock_code: 股票代码
            selection_date: 选入日期
        
        返回：
            {
                'is_duplicate': True,
                'days_ago': 15,
                'should_update': False
            }
        """
        try:
            cursor = self.conn.cursor()
            
            # 查询该股票最近的选入记录
            query_sql = """
            SELECT selection_date FROM stock_selection_record
            WHERE stock_code = ? AND is_active = 1
            ORDER BY selection_date DESC
            LIMIT 1
            """
            
            cursor.execute(query_sql, (stock_code,))
            row = cursor.fetchone()
            
            if row is None:
                # 没有历史记录
                return {
                    'is_duplicate': False,
                    'days_ago': None,
                    'should_update': False
                }
            
            # 计算距离上次选入的天数
            last_selection_date = datetime.strptime(row['selection_date'], '%Y-%m-%d').date()
            current_date = selection_date if isinstance(selection_date, type(last_selection_date)) else datetime.strptime(str(selection_date), '%Y-%m-%d').date()
            days_ago = (current_date - last_selection_date).days
            
            # 一个月（30天）内跳过，一个月后重新记录
            should_update = days_ago >= 30
            
            return {
                'is_duplicate': True,
                'days_ago': days_ago,
                'should_update': should_update
            }
        
        except Exception as e:
            logger.error(f"检查重复选入失败: {str(e)}")
            return {
                'is_duplicate': False,
                'days_ago': None,
                'should_update': False
            }
    
    def delete_old_record(self, stock_code: str):
        """
        删除旧记录（逻辑删除）
        
        参数：
            stock_code: 股票代码
        """
        try:
            cursor = self.conn.cursor()
            
            # 逻辑删除：标记为不活跃
            update_sql = """
            UPDATE stock_selection_record
            SET is_active = 0, updated_at = ?
            WHERE stock_code = ? AND is_active = 1
            """
            
            cursor.execute(update_sql, (datetime.now(), stock_code))
            self.conn.commit()
            
            logger.info(f"删除股票 {stock_code} 的旧记录")
        
        except Exception as e:
            logger.error(f"删除旧记录失败: {str(e)}")
            self.conn.rollback()
    
    def generate_strategy_name(self, strategy_names: List[str]) -> str:
        """
        生成选股方案名称 - 从配置文件读取中文名称
        
        参数：
            strategy_names: 策略名称列表 ['MorningStarStrategy', 'BowlReboundStrategy']
        
        返回：
            '启明星策略+碗口反弹策略'
        """
        try:
            # 从配置文件读取策略的中文名称
            import yaml
            from pathlib import Path
            
            config_file = Path("config/strategy_params.yaml")
            strategy_display_names = {}
            
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                
                # 从配置中提取每个策略的 display_name
                strategies_config = config.get('strategies', {})
                for strategy_key, strategy_config in strategies_config.items():
                    display_name = strategy_config.get('display_name', strategy_key)
                    strategy_display_names[strategy_key] = display_name
        except Exception as e:
            logger.warning(f"读取策略配置失败: {str(e)}")
            strategy_display_names = {}
        
        # 转换为中文名称
        display_names = []
        for name in strategy_names:
            # 优先使用配置文件中的中文名称，如果没有则使用原名称
            display_name = strategy_display_names.get(name, name)
            display_names.append(display_name)
        
        # 使用"+"连接
        return '+'.join(display_names)
    
    def calculate_performance(self, stock_code: str, selection_price: float, 
                             selection_date) -> Dict:
        """
        实时计算表现指标
        
        参数：
            stock_code: 股票代码
            selection_price: 选入价格（未使用，使用选入日期的收盘价）
            selection_date: 选入日期
        
        返回：
            {
                'selection_day_price': 10.5,  # 选入当日收盘价（作为基准价格）
                'current_price': 11.2,        # 实时价格或收盘价
                'highest_price': 12.0,
                'lowest_price': 10.2,
                'return_rate': 6.67,
                'max_gain': 14.29,
                'max_loss': -2.86
            }
        """
        try:
            from utils.csv_manager import CSVManager
            from datetime import datetime, time
            import pytz
            
            csv_manager = CSVManager('data')
            
            # 读取股票数据
            df = csv_manager.read_stock(stock_code)
            
            if df is None or df.empty:
                logger.warning(f"无法获取股票 {stock_code} 的价格数据")
                return {
                    'selection_day_price': 0.0,
                    'current_price': 0.0,
                    'highest_price': 0.0,
                    'lowest_price': 0.0,
                    'return_rate': 0.0,
                    'max_gain': 0.0,
                    'max_loss': 0.0
                }
            
            # 转换selection_date为字符串格式
            if not isinstance(selection_date, str):
                selection_date_str = str(selection_date)
            else:
                selection_date_str = selection_date
            
            # 转换日期格式并按日期升序排列
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            selection_date_dt = pd.to_datetime(selection_date_str)
            
            # 获取选入当日的收盘价作为基准价格
            selection_day_data = df[df['date'] == selection_date_dt]
            if not selection_day_data.empty:
                selection_day_price = selection_day_data.iloc[0]['close']
            else:
                # 如果没有选入当日的数据，使用最接近的日期
                closest_idx = (df['date'] - selection_date_dt).abs().idxmin()
                selection_day_price = df.loc[closest_idx, 'close']
            
            # 获取实时价格
            current_price = self._get_current_price(stock_code, df)
            
            # 筛选选入日期到今天为止的数据（包括选入日期当天）
            from datetime import datetime, date
            import pytz
            
            tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(tz).date()
            today_dt = pd.to_datetime(today)
            
            # 从选入日期到今天的数据（包括选入日期当天）
            after_selection = df[(df['date'] >= selection_date_dt) & (df['date'] <= today_dt)]
            
            if not after_selection.empty:
                # 使用选入日期到今天的数据
                highest_price = after_selection['high'].max()
                lowest_price = after_selection['low'].min()
                
                # 如果今天的数据不在CSV中，需要从腾讯财经获取今天的最高最低价
                latest_date_in_csv = after_selection['date'].max()
                if latest_date_in_csv < today_dt:
                    # 今天的数据不在CSV中，从腾讯财经获取
                    try:
                        # 构建腾讯财经查询代码
                        if stock_code.startswith('6') or stock_code.startswith('8'):
                            query_code = f"sh{stock_code}"
                        else:
                            query_code = f"sz{stock_code}"
                        
                        # 调用腾讯财经接口获取实时数据
                        import requests
                        url = f"https://qt.gtimg.cn/q={query_code}"
                        resp = requests.get(url, timeout=10, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        })
                        
                        # 设置正确的字符编码
                        resp.encoding = 'gbk'
                        
                        if resp.status_code == 200:
                            text = resp.text.strip()
                            if '~' in text:
                                parts = text.split('~')
                                # 腾讯接口格式: parts[33]=最高价, parts[34]=最低价
                                if len(parts) >= 35:
                                    try:
                                        today_high = float(parts[33]) if parts[33] else highest_price
                                        today_low = float(parts[34]) if parts[34] else lowest_price
                                        # 与历史数据比较，取最高和最低
                                        highest_price = max(highest_price, today_high)
                                        lowest_price = min(lowest_price, today_low)
                                        logger.debug(f"获取今天的最高最低价: {stock_code} 最高={today_high:.2f}, 最低={today_low:.2f}")
                                    except (ValueError, IndexError):
                                        pass
                    except Exception as e:
                        logger.debug(f"获取今天的最高最低价失败: {str(e)}")
            else:
                # 没有选入日期到今天的数据，使用实时查询当日的最高最低价
                try:
                    # 构建腾讯财经查询代码
                    if stock_code.startswith('6') or stock_code.startswith('8'):
                        query_code = f"sh{stock_code}"
                    else:
                        query_code = f"sz{stock_code}"
                    
                    # 调用腾讯财经接口获取实时数据
                    import requests
                    url = f"https://qt.gtimg.cn/q={query_code}"
                    resp = requests.get(url, timeout=10, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    
                    # 设置正确的字符编码
                    resp.encoding = 'gbk'
                    
                    if resp.status_code == 200:
                        text = resp.text.strip()
                        if '~' in text:
                            parts = text.split('~')
                            # 腾讯接口格式: parts[33]=最高价, parts[34]=最低价
                            if len(parts) >= 35:
                                try:
                                    highest_price = float(parts[33]) if parts[33] else df['high'].max()
                                    lowest_price = float(parts[34]) if parts[34] else df['low'].min()
                                    logger.debug(f"实时查询当日最高最低价: {stock_code} 最高={highest_price:.2f}, 最低={lowest_price:.2f}")
                                except (ValueError, IndexError):
                                    highest_price = df['high'].max()
                                    lowest_price = df['low'].min()
                            else:
                                highest_price = df['high'].max()
                                lowest_price = df['low'].min()
                        else:
                            highest_price = df['high'].max()
                            lowest_price = df['low'].min()
                    else:
                        highest_price = df['high'].max()
                        lowest_price = df['low'].min()
                except Exception as e:
                    logger.debug(f"实时查询最高最低价失败: {str(e)}")
                    # 降级到使用最新数据
                    highest_price = df['high'].max()
                    lowest_price = df['low'].min()
            
            # 计算收益率（基于选入当日收盘价）
            return_rate = ((current_price - selection_day_price) / selection_day_price) * 100 if selection_day_price != 0 else 0.0
            max_gain = ((highest_price - selection_day_price) / selection_day_price) * 100 if selection_day_price != 0 else 0.0
            max_loss = ((lowest_price - selection_day_price) / selection_day_price) * 100 if selection_day_price != 0 else 0.0
            
            return {
                'selection_day_price': round(selection_day_price, 2),
                'current_price': round(current_price, 2),
                'highest_price': round(highest_price, 2),
                'lowest_price': round(lowest_price, 2),
                'return_rate': round(return_rate, 2),
                'max_gain': round(max_gain, 2),
                'max_loss': round(max_loss, 2)
            }
        
        except Exception as e:
            logger.error(f"计算表现指标失败: {str(e)}")
            return {
                'selection_day_price': 0.0,
                'current_price': 0.0,
                'highest_price': 0.0,
                'lowest_price': 0.0,
                'return_rate': 0.0,
                'max_gain': 0.0,
                'max_loss': 0.0
            }
    
    def _fetch_industry_from_akshare(self, stock_code: str) -> Tuple[str, str]:
        """
        从 AKShare 获取股票的行业和板块信息
        使用 akshare_call_with_retry 包装器，支持重试和缓存降级
        
        参数：
            stock_code: 股票代码
        
        返回：
            (industry, sector)
        """
        try:
            import akshare as ak
            from utils.akshare_retry import akshare_call_with_retry
            
            # 通过重试包装器获取单只股票的详细信息
            df = akshare_call_with_retry(ak.stock_individual_info_em, symbol=stock_code)
            
            if df is not None and len(df) > 0:
                # 查找行业和板块信息
                industry = ''
                sector = ''
                
                for idx, row in df.iterrows():
                    if '行业' in row.index:
                        industry = str(row['行业']).strip()
                    if '板块' in row.index:
                        sector = str(row['板块']).strip()
                
                return industry, sector
            
            return '', ''
        
        except Exception as e:
            logger.debug(f"从 AKShare 获取 {stock_code} 行业信息失败: {str(e)}")
            return '', ''
    
    def _get_stock_info(self, stock_code: str) -> Tuple[str, str]:
        """
        获取股票的行业和板块信息
        优先从缓存获取，缓存不存在时从腾讯财经实时获取
        
        参数：
            stock_code: 股票代码
        
        返回：
            (industry, sector)
        """
        try:
            # 优先从 stock_names.json 缓存获取
            names_file = Path("data/stock_names.json")
            if names_file.exists():
                with open(names_file, 'r', encoding='utf-8') as f:
                    stock_info = json.load(f)
                    if stock_code in stock_info:
                        info = stock_info[stock_code]
                        if isinstance(info, dict):
                            industry = info.get('industry', '')
                            sector = info.get('sector', '')
                            # 如果缓存中有有效数据，直接返回
                            if industry or sector:
                                return industry, sector
            
            # 缓存不存在或无效，从腾讯财经实时获取
            from utils.akshare_fetcher import AKShareFetcher
            fetcher = AKShareFetcher()
            industry, sector = fetcher.get_stock_industry_sector(stock_code)
            
            # 如果腾讯财经获取失败，尝试从 AKShare 获取
            if not industry and not sector:
                industry, sector = self._fetch_industry_from_akshare(stock_code)
            
            # 更新缓存
            if industry or sector:
                self._update_stock_cache(stock_code, industry, sector)
            
            return industry, sector
        
        except Exception as e:
            logger.debug(f"获取股票信息失败: {str(e)}")
            return '', ''
    
    def _update_stock_cache(self, stock_code: str, industry: str, sector: str):
        """
        更新 stock_names.json 缓存
        
        参数：
            stock_code: 股票代码
            industry: 行业
            sector: 板块
        """
        try:
            names_file = Path("data/stock_names.json")
            
            # 读取现有缓存
            stock_info = {}
            if names_file.exists():
                with open(names_file, 'r', encoding='utf-8') as f:
                    stock_info = json.load(f)
            
            # 更新或添加股票信息
            if stock_code not in stock_info:
                stock_info[stock_code] = {'name': '', 'industry': '', 'sector': ''}
            
            stock_info[stock_code]['industry'] = industry
            stock_info[stock_code]['sector'] = sector
            
            # 保存更新后的缓存
            with open(names_file, 'w', encoding='utf-8') as f:
                json.dump(stock_info, f, ensure_ascii=False, indent=2)
        
        except Exception as e:
            logger.debug(f"更新缓存失败: {str(e)}")
    
    def _update_stock_in_db(self, stock_code: str, industry: str, sector: str):
        """
        更新数据库中该股票的行业/板块信息
        
        参数：
            stock_code: 股票代码
            industry: 行业
            sector: 板块
        """
        try:
            cursor = self.conn.cursor()
            
            # 更新所有该股票的记录
            update_sql = """
            UPDATE stock_selection_record 
            SET industry = ?, sector = ?, updated_at = ?
            WHERE stock_code = ? AND is_active = 1
            """
            
            cursor.execute(update_sql, (industry, sector, datetime.now(), stock_code))
            self.conn.commit()
            
            logger.debug(f"更新数据库中 {stock_code} 的行业/板块信息: {industry}/{sector}")
        
        except Exception as e:
            logger.debug(f"更新数据库失败: {str(e)}")
            self.conn.rollback()
    
    def _get_stock_price(self, stock_code: str, date) -> float:
        """
        获取股票在指定日期的收盘价
        
        参数：
            stock_code: 股票代码
            date: 日期
        
        返回：
            收盘价
        """
        try:
            from utils.csv_manager import CSVManager
            csv_manager = CSVManager('data')
            
            df = csv_manager.read_stock(stock_code)
            if df is None or df.empty:
                return 0.0
            
            # 转换date为字符串格式
            if not isinstance(date, str):
                date_str = str(date)
            else:
                date_str = date
            
            # 查找指定日期的收盘价
            df['date'] = pd.to_datetime(df['date'])
            target_date = pd.to_datetime(date_str)
            
            # 查找最接近的日期
            closest_idx = (df['date'] - target_date).abs().idxmin()
            return float(df.loc[closest_idx, 'close'])
        
        except Exception as e:
            logger.debug(f"获取股票价格失败: {str(e)}")
            return 0.0
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")

    def _get_current_price(self, stock_code: str, df: pd.DataFrame) -> float:
        """
        获取当前价格：统一通过腾讯财经接口获取
        - 交易时间（9:30-15:00）：返回实时价格
        - 收盘后（15:00之后）：返回当日收盘价
        - 开盘前 / 非交易日：返回前一个交易日收盘价

        腾讯财经接口在任何时段都返回最新有效价格，天然满足以上规则。
        仅在接口调用失败时，回退到本地CSV数据。

        参数：
            stock_code: 股票代码
            df: 股票数据DataFrame（作为降级备选）

        返回：
            当前价格
        """
        try:
            # 优先通过腾讯财经接口获取最新价格
            price = self._fetch_realtime_price(stock_code)
            if price is not None and price > 0:
                return price

            # 接口失败，回退到本地CSV最新收盘价
            logger.warning(f"腾讯财经接口获取价格失败，回退CSV: {stock_code}")
            if not df.empty:
                return df.iloc[-1]['close']

            return 0.0
        except Exception as e:
            logger.warning(f"获取当前价格失败: {str(e)}")
            # 返回最新收盘价作为备选
            if not df.empty:
                return df.iloc[-1]['close']
            return 0.0

    def _fetch_realtime_price(self, stock_code: str) -> float:
        """
        通过腾讯财经接口获取股票最新价格

        该接口在任何时段都返回最新有效价格：
        - 交易中：实时价格
        - 收盘后：当日收盘价
        - 非交易日/开盘前：前一个交易日收盘价

        参数：
            stock_code: 股票代码（6位数字）

        返回：
            价格，失败返回 None
        """
        import requests

        try:
            # 构建腾讯财经查询代码
            if stock_code.startswith('6') or stock_code.startswith('8'):
                query_code = f"sh{stock_code}"
            else:
                query_code = f"sz{stock_code}"

            # 调用腾讯财经接口
            url = f"https://qt.gtimg.cn/q={query_code}"
            resp = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })

            # 设置正确的字符编码
            resp.encoding = 'gbk'

            if resp.status_code == 200:
                text = resp.text.strip()
                if '~' in text:
                    parts = text.split('~')
                    # parts[3] 是当前价格（实时价/收盘价）
                    if len(parts) >= 4:
                        price = float(parts[3])
                        if price > 0:
                            logger.debug(f"获取最新价格成功: {stock_code} = ¥{price:.2f}")
                            return price

            return None
        except Exception as e:
            logger.debug(f"腾讯财经接口调用失败 ({stock_code}): {str(e)}")
            return None

