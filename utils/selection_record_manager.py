"""
选股记录管理器 - 负责选股结果的保存、查询和去重处理
"""

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

# 导入全局数据库管理器
from utils.global_db import get_global_db

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
    
    def __init__(self, db_path: str = None):
        """
        初始化选股记录管理器
        
        参数：
            db_path: 数据库文件路径（已废弃，使用全局DBManager）
        """
        # 使用全局数据库管理器实例
        self.db_manager = get_global_db()
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表结构"""
        try:
            # 创建表
            self._create_tables()
            logger.info("数据库表结构初始化成功")
        except Exception as e:
            logger.error(f"数据库初始化失败: {str(e)}")
            raise
    
    def _create_tables(self):
        """创建数据库表"""
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
            score DECIMAL(5,2),
            rank_position INTEGER,
            key_dates TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 1,
            strategy_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(stock_code, selection_date)
        )
        """
        self.db_manager.execute_with_retry(create_table_sql)
        
        # 检查并添加字段（用于数据库迁移）
        try:
            # 获取表结构
            columns = []
            cursor = self.db_manager.execute_with_retry("PRAGMA table_info(stock_selection_record)")
            for row in cursor.fetchall():
                columns.append(row[1])
            
            if 'key_dates' not in columns:
                self.db_manager.execute_with_retry("ALTER TABLE stock_selection_record ADD COLUMN key_dates TEXT")
                logger.info("数据库迁移：添加key_dates字段")
            if 'score' not in columns:
                self.db_manager.execute_with_retry("ALTER TABLE stock_selection_record ADD COLUMN score DECIMAL(5,2)")
                logger.info("数据库迁移：添加score字段")
            if 'rank_position' not in columns:
                self.db_manager.execute_with_retry("ALTER TABLE stock_selection_record ADD COLUMN rank_position INTEGER")
                logger.info("数据库迁移：添加rank_position字段")
            if 'strategy_count' not in columns:
                self.db_manager.execute_with_retry("ALTER TABLE stock_selection_record ADD COLUMN strategy_count INTEGER DEFAULT 1")
                logger.info("数据库迁移：添加strategy_count字段")
        except Exception as e:
            logger.warning(f"数据库迁移失败: {str(e)}")
        
        # 创建索引
        index_sqls = [
            "CREATE INDEX IF NOT EXISTS idx_strategy_name ON stock_selection_record(strategy_name)",
            "CREATE INDEX IF NOT EXISTS idx_selection_date ON stock_selection_record(selection_date)",
            "CREATE INDEX IF NOT EXISTS idx_is_active ON stock_selection_record(is_active)",
            "CREATE INDEX IF NOT EXISTS idx_stock_code ON stock_selection_record(stock_code)",
            "CREATE INDEX IF NOT EXISTS idx_score ON stock_selection_record(selection_date, score)",
            "CREATE INDEX IF NOT EXISTS idx_rank_position ON stock_selection_record(selection_date, rank_position)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_date ON stock_selection_record(stock_code, selection_date)"
        ]
        
        for sql in index_sqls:
            self.db_manager.execute_with_retry(sql)
        
        logger.info("数据库表创建成功")
    
    def save_selection_result(self, strategy_names: List[str], signals: List[Dict], 
                             selection_time: datetime, end_date: str = None) -> Dict:
        """
        保存选股结果
        
        参数：
            strategy_names: 策略名称列表 ['morning_star', 'bowl_rebound']（已废弃，使用signal中的strategies字段）
            signals: 选股信号列表 [{'code': '000001', 'name': '平安银行', 'strategies': ['morning_star'], ...}]
            selection_time: 选股执行时间
            end_date: 用户选择的选股日期（格式：YYYY-MM-DD）
        
        返回：
            {'success': True, 'saved': 10, 'skipped': 5, 'updated': 2, 'error': 0}
        """
        try:
            # 确定选入日期：优先使用用户选择的日期，如果该日期没有K线则向前查找
            selection_date = None
            
            if end_date:
                # 用户选择了日期，先检查该日期是否有K线数据
                try:
                    user_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                    selection_date = self._get_nearest_kline_date(user_date)
                    if selection_date:
                        logger.info(f"用户选择日期: {user_date}，使用最近的交易日: {selection_date}")
                    else:
                        logger.warning(f"用户选择日期 {user_date} 及之前没有K线数据")
                except Exception as e:
                    logger.warning(f"解析用户选择日期失败: {str(e)}")
            
            # 如果没有找到合适的日期，使用当前时间的日期
            if selection_date is None:
                selection_date = selection_time.date()
                logger.warning(f"未找到合适的交易日期，使用当前日期: {selection_date}")
            
            # 统计信息
            stats = {'saved': 0, 'skipped': 0, 'updated': 0, 'error': 0}
            
            # 按股票代码分组，确保每个股票只保存一条记录
            stock_map = {}
            for signal in signals:
                try:
                    stock_code = signal.get('code')
                    if not stock_code:
                        continue
                    
                    # 获取该股票命中的策略列表
                    stock_strategies = signal.get('strategies', [])
                    if not stock_strategies:
                        # 如果没有strategies字段，使用传入的strategy_names作为备选
                        stock_strategies = strategy_names
                    
                    # 转换策略名称为中文
                    try:
                        import yaml
                        from pathlib import Path
                        
                        config_path = Path(__file__).parent.parent / "config" / "strategy_params.yaml"
                        if config_path.exists():
                            with open(config_path, 'r', encoding='utf-8') as f:
                                config = yaml.safe_load(f) or {}
                            
                            strategies_config = config.get('strategies', {})
                            strategy_display_names = {}
                            for strategy_key, strategy_config in strategies_config.items():
                                strategy_display_names[strategy_key] = strategy_config.get('display_name', strategy_key)
                            
                            # 转换策略名称为中文
                            stock_strategies = [strategy_display_names.get(s, s) for s in stock_strategies]
                    except Exception as e:
                        logger.debug(f"转换策略名称失败: {str(e)}")
                    
                    # 生成该股票的选股方案名称
                    strategy_name = self.generate_strategy_name(stock_strategies)
                    
                    # 从stock_basic表获取行业信息
                    industry = self._get_stock_industry(stock_code)
                    
                    # 获取选入价格（使用信号中的价格或从CSV获取）
                    selection_price = signal.get('price', 0.0)
                    if selection_price == 0.0:
                        selection_price = self._get_stock_price(stock_code, selection_date)
                    
                    # 提取关键日期信息
                    key_dates = self._extract_key_dates(signal)
                    
                    # 按股票代码分组
                    if stock_code not in stock_map:
                        # 计算策略数量：strategy_name 中 " + " 的个数 + 1
                        strategy_count = strategy_name.count('+') + 1
                        stock_map[stock_code] = {
                            'stock_code': stock_code,
                            'stock_name': signal.get('name', '未知'),
                            'strategy_name': strategy_name,
                            'industry': industry,
                            'selection_price': selection_price,
                            'key_dates': key_dates,
                            'strategy_count': strategy_count
                        }
                except Exception as e:
                    logger.error(f"处理信号失败: {str(e)}")
                    stats['error'] += 1
            
            # 处理每个股票
            for stock_info in stock_map.values():
                try:
                    stock_code = stock_info['stock_code']
                    stock_name = stock_info['stock_name']
                    strategy_name = stock_info['strategy_name']
                    industry = stock_info['industry']
                    selection_price = stock_info['selection_price']
                    key_dates = stock_info['key_dates']
                    
                    # 检查是否重复选入
                    duplicate_info = self.check_duplicate(stock_code, selection_date)
                    
                    if duplicate_info['is_duplicate']:
                        if duplicate_info['should_update']:
                            # 删除旧记录，保存新记录
                            self.delete_old_record(stock_code, selection_date)
                            self._insert_record(strategy_name, stock_code, stock_name,
                                              industry, selection_date, selection_time,
                                              selection_price, key_dates, stock_info.get('strategy_count', 1))
                            stats['updated'] += 1
                        else:
                            # 当天内，跳过
                            stats['skipped'] += 1
                    else:
                        # 新股票，直接保存
                        self._insert_record(strategy_name, stock_code, stock_name,
                                          industry, selection_date, selection_time,
                                          selection_price, key_dates, stock_info.get('strategy_count', 1))
                        stats['saved'] += 1
                except Exception as e:
                    logger.error(f"保存股票 {stock_info.get('stock_code')} 失败: {str(e)}")
                    stats['error'] += 1
            
            logger.info(f"选股结果保存完成 - 保存: {stats['saved']}, 跳过: {stats['skipped']}, "
                       f"更新: {stats['updated']}, 错误: {stats['error']}")
            
            # 统一提交事务，确保所有INSERT操作持久化到数据库
            if stats['saved'] > 0 or stats['updated'] > 0:
                conn = self.db_manager.connect()
                conn.commit()
            
            return {
                'success': True,
                'saved': stats['saved'],
                'skipped': stats['skipped'],
                'updated': stats['updated'],
                'error': stats['error']
            }
        
        except Exception as e:
            logger.error(f"保存选股结果失败: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _insert_record(self, strategy_name: str, stock_code: str, stock_name: str,
                      industry: str, selection_date, selection_time: datetime,
                      selection_price: float, key_dates: str = None, strategy_count: int = 1):
        """
        插入选股记录
        
        参数：
            strategy_name: 选股方案名称
            stock_code: 股票代码
            stock_name: 股票名称
            industry: 行业
            selection_date: 选入日期
            selection_time: 选入时间
            selection_price: 选入价格
            key_dates: 关键日期信息（JSON字符串）
            strategy_count: 命中策略个数
        """
        insert_sql = """
        INSERT INTO stock_selection_record 
        (strategy_name, stock_code, stock_name, industry, 
         selection_date, selection_time, selection_price, key_dates, created_at, updated_at, is_active, strategy_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """
        
        now = datetime.now()
        self.db_manager.execute_with_retry(insert_sql, (
            strategy_name, stock_code, stock_name, industry,
            selection_date, selection_time, selection_price, key_dates, now, now, strategy_count
        ))
        
        # 不需要再调用 _update_strategy_count，因为我们已经知道策略数量
    
    def _update_strategy_count(self, stock_code: str, selection_date):
        """
        更新股票的策略计数
        
        参数：
            stock_code: 股票代码
            selection_date: 选入日期
        """
        try:
            # 转换选入日期为字符串格式
            if isinstance(selection_date, datetime):
                selection_date_str = selection_date.date().strftime('%Y-%m-%d')
            elif isinstance(selection_date, str):
                selection_date_str = selection_date
            else:
                selection_date_str = str(selection_date)
            
            # 计算该股票在该日期的策略数
            count_sql = """
                SELECT COUNT(*) 
                FROM stock_selection_record 
                WHERE stock_code = ? AND selection_date = ? AND is_active = 1
            """
            cursor = self.db_manager.execute_with_retry(count_sql, (stock_code, selection_date_str))
            row = cursor.fetchone()
            strategy_count = row[0] if row else 1
            
            # 更新该股票在该日期的所有记录的strategy_count
            update_sql = """
                UPDATE stock_selection_record
                SET strategy_count = ?
                WHERE stock_code = ? AND selection_date = ? AND is_active = 1
            """
            self.db_manager.execute_with_retry(update_sql, (strategy_count, stock_code, selection_date_str))
        except Exception as e:
            logger.warning(f"更新策略计数失败: {stock_code} {selection_date} - {str(e)}")
    
    def _extract_key_dates(self, signal: Dict) -> str:
        """
        从策略信号中提取关键日期信息
        
        参数：
            signal: 选股信号字典，可能包含以下字段：
                - key_date: 关键日期（字符串）
                - key_date_type: 关键日期类型（字符串，如"颈线突破日"）
                - signals: 策略信号列表（多策略时）
        
        返回：
            JSON字符串，包含关键日期信息
        """
        key_dates_list = []
        
        try:
            # 检查是否有单个策略的关键日期信息
            if 'key_date' in signal and signal['key_date']:
                key_date_info = {
                    'date': signal['key_date'],
                    'type': signal.get('key_date_type', '关键日期'),
                    'description': signal.get('key_date_type', '关键日期')
                }
                key_dates_list.append(key_date_info)
            
            # 检查是否有多个策略的信号（多策略选中同一只股票）
            if 'signals' in signal and isinstance(signal['signals'], list):
                for sig in signal['signals']:
                    if isinstance(sig, dict) and 'key_date' in sig and sig['key_date']:
                        key_date_info = {
                            'date': sig['key_date'],
                            'type': sig.get('key_date_type', '关键日期'),
                            'description': sig.get('key_date_type', '关键日期')
                        }
                        # 避免重复添加相同日期
                        if not any(kd['date'] == key_date_info['date'] for kd in key_dates_list):
                            key_dates_list.append(key_date_info)
            
            # 如果没有找到关键日期，使用选股日期作为默认值
            if not key_dates_list and 'date' in signal:
                key_date_info = {
                    'date': signal['date'],
                    'type': '选股日期',
                    'description': '选股日期'
                }
                key_dates_list.append(key_date_info)
            
            # 转换为JSON字符串
            if key_dates_list:
                return json.dumps(key_dates_list, ensure_ascii=False)
            else:
                return None
        
        except Exception as e:
            logger.warning(f"提取关键日期失败: {str(e)}")
            return None
    
    def _get_stock_industry(self, stock_code: str) -> str:
        """
        获取股票行业信息
        优先从stock_basic表获取，如果没有则尝试从industry_fetcher获取
        
        参数：
            stock_code: 股票代码
        
        返回：
            行业名称，如果获取失败返回空字符串
        """
        try:
            # 首先尝试从stock_basic表获取
            industry = None
            cursor = self.db_manager.execute_with_retry("SELECT industry FROM stock_basic WHERE code = ?", (stock_code,))
            row = cursor.fetchone()
            if row and row[0]:
                industry = row[0]
            
            if industry:
                return industry
            
            # 如果stock_basic表中没有，尝试使用industry_fetcher获取
            try:
                from utils.industry_fetcher import IndustryFetcher
                from utils.cache_manager import CacheManager
                
                cache_manager = CacheManager()
                fetcher = IndustryFetcher(self.db_manager, cache_manager)
                
                # 使用fetch_with_retry获取行业信息
                industry_data = fetcher.fetch_with_retry(stock_code=stock_code)
                if industry_data and 'industry_name' in industry_data:
                    industry_name = industry_data['industry_name']
                    logger.debug(f"从industry_fetcher获取到股票 {stock_code} 的行业: {industry_name}")
                    return industry_name
            except Exception as e:
                logger.debug(f"从industry_fetcher获取行业信息失败: {str(e)}")
            
            return ''
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 行业信息失败: {str(e)}")
            return ''
    
    def _get_stock_sector(self, stock_code: str) -> str:
        """
        获取股票板块信息
        从stock_score_detail表获取最优板块（得分最高的板块）
        
        参数：
            stock_code: 股票代码
        
        返回：
            板块名称，如果获取失败返回空字符串
        """
        try:
            # 从stock_score_detail表获取最新的板块详情
            sector_details = None
            def callback(row):
                nonlocal sector_details
                if row and row[0]:
                    sector_details = row[0]
            
            self.db_manager.execute_with_retry("""
                SELECT sector_details 
                FROM stock_score_detail 
                WHERE stock_code = ? 
                ORDER BY score_date DESC 
                LIMIT 1
            """, (stock_code,), callback=callback)
            
            if sector_details:
                try:
                    # 解析JSON格式的板块详情
                    sector_data = json.loads(sector_details)
                    
                    # 直接从sector_details中获取板块名称
                    # 因为SectorDetail.to_dict()返回的是单个板块信息
                    if 'sector_name' in sector_data and sector_data['sector_name']:
                        return sector_data['sector_name']
                    # 兼容旧格式：如果有sectors列表，按得分排序取最高
                    elif 'sectors' in sector_data and isinstance(sector_data['sectors'], list):
                        # 按得分降序排序
                        sorted_sectors = sorted(sector_data['sectors'], 
                                              key=lambda x: x.get('score', 0), 
                                              reverse=True)
                        
                        # 返回得分最高的板块名称
                        if sorted_sectors:
                            best_sector = sorted_sectors[0]
                            if 'name' in best_sector:
                                return best_sector['name']
                except Exception as e:
                    logger.debug(f"解析板块详情失败: {str(e)}")
            
            # 如果没有评分数据，尝试从stock_sector_mapping表获取最新的板块信息
            try:
                # 先获取最新的板块代码
                sector_code = None
                def sector_code_callback(row):
                    nonlocal sector_code
                    if row and row[0]:
                        sector_code = row[0]
                
                self.db_manager.execute_with_retry("""
                    SELECT sector_code 
                    FROM stock_sector_mapping 
                    WHERE stock_code = ? 
                    ORDER BY mapping_date DESC 
                    LIMIT 1
                """, (stock_code,), callback=sector_code_callback)
                
                if sector_code:
                    # 再从stock_sector表获取板块名称
                    sector_name = None
                    def sector_name_callback(row):
                        nonlocal sector_name
                        if row and row[0]:
                            sector_name = row[0]
                    
                    self.db_manager.execute_with_retry("SELECT sector_name FROM stock_sector WHERE sector_code = ?", 
                                                     (sector_code,), callback=sector_name_callback)
                    if sector_name:
                        return sector_name
            except Exception as e:
                logger.debug(f"从stock_sector_mapping表获取板块信息失败: {str(e)}")
            
            # 如果没有板块映射，尝试从stock_basic表获取行业信息作为板块（因为stock_basic表没有sector字段）
            try:
                industry = None
                def industry_callback(row):
                    nonlocal industry
                    if row and row[0]:
                        industry = row[0]
                
                self.db_manager.execute_with_retry("SELECT industry FROM stock_basic WHERE code = ?", 
                                                 (stock_code,), callback=industry_callback)
                if industry:
                    return industry
            except Exception as e:
                logger.debug(f"从stock_basic表获取行业信息失败: {str(e)}")
            
            return ''
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 板块信息失败: {str(e)}")
            return ''
    
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
            
            # 策略名称筛选需要特殊处理，因为我们需要先分组再筛选
            strategy_name_filter = filters.get('strategy_name', '')
            
            # 查询分组后的总数
            total = 0
            count_sql = f"""
            SELECT COUNT(*) as total 
            FROM (
                SELECT DISTINCT stock_code, selection_date 
                FROM stock_selection_record 
                WHERE {where_sql}
            ) as distinct_records
            """
            cursor = self.db_manager.execute_with_retry(count_sql, params)
            row = cursor.fetchone()
            if row and row[0]:
                total = row[0]
            
            # 转换为字典列表并计算价格指标
            data = []
            filtered_total = 0
            
            # 计算偏移量
            offset = (page - 1) * limit
            current_offset = offset
            
            while len(data) < limit:
                # 构建查询SQL，使用strategy_count字段
                query_sql = f"""
                SELECT DISTINCT stock_code, stock_name, selection_date, MIN(selection_price) as selection_price, 
                       MIN(industry) as industry, MIN(sector) as sector, 
                       MIN(selection_time) as selection_time, 
                       MAX(strategy_count) as strategy_count
                FROM stock_selection_record 
                WHERE {where_sql}
                GROUP BY stock_code, selection_date
                ORDER BY selection_date DESC, strategy_count DESC, selection_time DESC
                LIMIT ? OFFSET ?
                """
                
                # 执行查询
                cursor = self.db_manager.execute_with_retry(query_sql, params + [limit * 2, current_offset])
                batch_rows = [dict(row) for row in cursor.fetchall()]
                
                if not batch_rows:
                    break
                
                current_offset += len(batch_rows)
                
                for record in batch_rows:
                    stock_code = record['stock_code']
                    selection_date = record['selection_date']
                    
                    # 获取该股票在该日期的所有策略
                    strategies_sql = """
                    SELECT strategy_name 
                    FROM stock_selection_record 
                    WHERE stock_code = ? AND selection_date = ? AND is_active = 1
                    """
                    strategies_cursor = self.db_manager.execute_with_retry(strategies_sql, (stock_code, selection_date))
                    strategies = [row[0] for row in strategies_cursor.fetchall()]
                    
                    # 如果有策略名称筛选，检查是否包含该策略
                    if strategy_name_filter:
                        # 检查是否有策略名称包含筛选条件（兼容有无"策略"二字的情况）
                        filter_text = strategy_name_filter
                        # 移除"策略"二字进行比较
                        filter_text_no_strategy = filter_text.replace('策略', '')
                        
                        matched = False
                        for strategy in strategies:
                            # 检查原始策略名称是否包含筛选条件
                            if filter_text in strategy:
                                matched = True
                                break
                            # 检查移除"策略"二字后的策略名称是否包含筛选条件
                            strategy_no_strategy = strategy.replace('策略', '')
                            if filter_text_no_strategy in strategy_no_strategy:
                                matched = True
                                break
                        
                        if not matched:
                            continue
                    
                    # 实时计算价格指标
                    performance = self.calculate_performance(
                        stock_code,
                        record['selection_price'],
                        selection_date
                    )
                    
                    # 合并价格指标和策略信息
                    record.update(performance)
                    record['strategy_name'] = "，".join(strategies)  # 用中文逗号连接策略名称
                    record['strategies'] = strategies  # 添加策略列表
                    data.append(record)
                    filtered_total += 1
                    
                    if len(data) >= limit:
                        break
            
            # 计算实际的总记录数（如果有筛选）
            if strategy_name_filter:
                # 重新查询符合筛选条件的总记录数
                filtered_count_sql = f"""
                SELECT COUNT(*) as total 
                FROM (
                    SELECT DISTINCT stock_code, selection_date 
                    FROM stock_selection_record 
                    WHERE {where_sql}
                ) as distinct_records
                """
                cursor = self.db_manager.execute_with_retry(filtered_count_sql, params)
                row = cursor.fetchone()
                if row and row[0]:
                    total = row[0]
            else:
                # 使用之前查询的总记录数
                pass
            
            logger.info(f"查询选股历史 - 总数: {total}, 筛选后: {filtered_total}, 页码: {page}, 每页: {limit}")
            
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
                'days_ago': 0,
                'should_update': False
            }
        """
        try:
            # 转换选入日期为字符串格式
            if isinstance(selection_date, datetime):
                selection_date_str = selection_date.date().strftime('%Y-%m-%d')
            elif isinstance(selection_date, str):
                selection_date_str = selection_date
            else:
                selection_date_str = str(selection_date)
            
            # 查询该股票当天是否已经选入
            is_duplicate = False
            query_sql = """
            SELECT selection_date FROM stock_selection_record
            WHERE stock_code = ? AND selection_date = ? AND is_active = 1
            """
            
            cursor = self.db_manager.execute_with_retry(query_sql, (stock_code, selection_date_str))
            row = cursor.fetchone()
            if row:
                is_duplicate = True
            
            if not is_duplicate:
                # 当天没有选入记录
                return {
                    'is_duplicate': False,
                    'days_ago': 0,
                    'should_update': False
                }
            else:
                # 当天已经选入过，返回 should_update: True，这样会删除旧记录并保存新记录
                return {
                    'is_duplicate': True,
                    'days_ago': 0,
                    'should_update': True
                }
        
        except Exception as e:
            logger.error(f"检查重复选入失败: {str(e)}")
            return {
                'is_duplicate': False,
                'days_ago': 0,
                'should_update': False
            }
    
    def delete_old_record(self, stock_code: str, selection_date):
        """
        删除旧记录（物理删除）
        
        参数：
            stock_code: 股票代码
            selection_date: 选入日期
        """
        try:
            # 转换选入日期为字符串格式
            if isinstance(selection_date, datetime):
                selection_date_str = selection_date.date().strftime('%Y-%m-%d')
            elif isinstance(selection_date, str):
                selection_date_str = selection_date
            else:
                selection_date_str = str(selection_date)
            
            # 物理删除：直接删除旧记录
            delete_sql = """
            DELETE FROM stock_selection_record
            WHERE stock_code = ? AND selection_date = ?
            """
            
            self.db_manager.execute_with_retry(delete_sql, (stock_code, selection_date_str))
            
            logger.info(f"删除股票 {stock_code} 在 {selection_date_str} 的旧记录")
        
        except Exception as e:
            logger.error(f"删除旧记录失败: {str(e)}")
    
    def generate_strategy_name(self, strategy_names: List[str]) -> str:
        """
        生成选股方案名称 - 直接使用策略名称
        
        参数：
            strategy_names: 策略名称列表 ['启明星策略', '碗口反弹策略']
        
        返回：
            '启明星策略+碗口反弹策略'
        """
        # 直接使用策略名称，因为选股结果中已经包含了策略的中文名称
        return '+'.join(strategy_names)
    
    def calculate_performance(self, stock_code: str, selection_price: float, 
                             selection_date) -> Dict:
        """
        实时计算表现指标
        
        参数：
            stock_code: 股票代码
            selection_price: 选入价格
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
            from datetime import datetime, time
            import pytz
            
            # 从数据库读取股票数据
            df = self.db_manager.read_stock(stock_code)
            
            # 获取实时价格
            current_price = self._get_current_price(stock_code, df)
            
            # 转换selection_date为字符串格式
            if not isinstance(selection_date, str):
                selection_date_str = str(selection_date)
            else:
                selection_date_str = selection_date
            
            # 转换日期格式并按日期升序排列
            selection_day_price = selection_price  # 使用传入的选入价格作为基准
            if df is not None and not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                selection_date_dt = pd.to_datetime(selection_date_str)
                
                # 获取选入当日的收盘价作为基准价格（如果有数据）
                selection_day_data = df[df['date'] == selection_date_dt]
                if not selection_day_data.empty:
                    selection_day_price = selection_day_data.iloc[0]['close']
                else:
                    # 如果没有选入当日的数据，使用最接近的日期
                    closest_idx = (df['date'] - selection_date_dt).abs().idxmin()
                    selection_day_price = df.loc[closest_idx, 'close']
            
            # 初始化最高最低价
            highest_price = current_price  # 默认使用当前价格
            lowest_price = current_price  # 默认使用当前价格
            
            # 筛选选入日期之后到今天为止的数据（不包括选入日期当天）
            from datetime import datetime, date, timedelta
            import pytz
            
            tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(tz).date()
            today_dt = pd.to_datetime(today)
            
            if df is not None and not df.empty:
                selection_date_dt = pd.to_datetime(selection_date_str)
                # 选入日期的下一天开始
                next_day = selection_date_dt + timedelta(days=1)
                # 从选入日期之后到今天的数据（不包括选入日期当天）
                after_selection = df[(df['date'] >= next_day) & (df['date'] <= today_dt)]
                
                if not after_selection.empty:
                    # 使用选入日期之后到今天的数据
                    highest_price = after_selection['high'].max()
                    lowest_price = after_selection['low'].min()
                
                # 无论是否有历史数据，都获取今天的实时最高最低价
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
            
            # 没有任何数据时，使用选入价格
            if highest_price == 0:
                highest_price = selection_price
            if lowest_price == 0:
                lowest_price = selection_price
            
            # 确保最高价至少等于当前价格和选入价格
            highest_price = max(highest_price, current_price, selection_price)
            
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
            # 异常情况下，使用选入价格作为所有价格
            return {
                'selection_day_price': round(selection_price, 2),
                'current_price': round(selection_price, 2),
                'highest_price': round(selection_price, 2),
                'lowest_price': round(selection_price, 2),
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
        从腾讯财经实时获取（不再使用 stock_names.json 缓存）
        
        参数：
            stock_code: 股票代码
        
        返回：
            (industry, sector)
        """
        try:
            # 从腾讯财经实时获取行业和板块信息
            from utils.akshare_fetcher import AKShareFetcher
            fetcher = AKShareFetcher()
            industry, sector = fetcher.get_stock_industry_sector(stock_code)
            
            # 如果腾讯财经获取失败，尝试从 AKShare 获取
            if not industry and not sector:
                industry, sector = self._fetch_industry_from_akshare(stock_code)
            
            return industry, sector
        
        except Exception as e:
            logger.debug(f"获取股票信息失败: {str(e)}")
            return '', ''

    
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
            # 从数据库读取股票数据
            df = self.db_manager.read_stock(stock_code)
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
    

    def _get_latest_kline_date(self):
        """
        获取stock_kline表中的最新日期
        
        返回：
            最新日期（date对象），如果没有数据则返回None
        """
        try:
            latest_date = None
            cursor = self.db_manager.execute_with_retry("SELECT MAX(date) as latest_date FROM stock_kline")
            row = cursor.fetchone()
            if row and row[0]:
                latest_date = row[0]
            
            if latest_date:
                # 确保日期格式正确
                if isinstance(latest_date, str):
                    return datetime.strptime(latest_date, '%Y-%m-%d').date()
                elif hasattr(latest_date, 'date'):
                    return latest_date.date()
            return None
        except Exception as e:
            logger.warning(f"获取最新K线日期失败: {str(e)}")
            return None
    
    def _get_nearest_kline_date(self, target_date):
        """
        获取最近的有K线数据的日期（不超过target_date）
        
        逻辑：
        1. 先检查target_date是否有K线数据
        2. 如果没有，则向前查找最近的有K线数据的日期
        
        参数：
            target_date: 目标日期（date对象或字符串YYYY-MM-DD）
        
        返回：
            最近的有K线数据的日期（date对象），如果没有找到则返回None
        """
        try:
            # 确保target_date是date对象
            if isinstance(target_date, str):
                target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
            
            # 查询不超过target_date的最新日期
            cursor = self.db_manager.execute_with_retry(
                "SELECT MAX(date) as nearest_date FROM stock_kline WHERE date <= ?",
                (target_date.strftime('%Y-%m-%d'),)
            )
            row = cursor.fetchone()
            
            if row and row[0]:
                nearest_date = row[0]
                # 确保日期格式正确
                if isinstance(nearest_date, str):
                    return datetime.strptime(nearest_date, '%Y-%m-%d').date()
                elif hasattr(nearest_date, 'date'):
                    return nearest_date.date()
            
            return None
        except Exception as e:
            logger.warning(f"获取最近K线日期失败: {str(e)}")
            return None
    
    def close(self):
        """关闭数据库连接（已废弃，使用全局DBManager）"""
        # 由于使用全局DBManager，不需要单独关闭连接
        logger.debug("SelectionRecordManager close() called - no action needed for global DBManager")

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

