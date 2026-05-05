"""
资金流向数据增量更新器

功能：
1. 计算需要获取的天数
2. 获取个股、行业、板块资金流向数据
3. 覆盖数据库中该时间段的数据
4. 统计更新结果

特点：
- 支持三种资金流向数据：个股、行业、板块
- 使用DELETE + INSERT方式覆盖数据
- 完善的错误处理和重试机制
- 详细的统计信息
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger(__name__)


class FundFlowUpdater:
    """资金流向数据增量更新器"""
    
    def __init__(self, db_manager, fund_flow_fetcher):
        """
        初始化资金流向更新器
        
        参数：
            db_manager: 数据库管理器
            fund_flow_fetcher: 资金流向数据采集器
        """
        self.db_manager = db_manager
        self.fund_flow_fetcher = fund_flow_fetcher
        
        # 统计信息
        self.stats = {
            'added': 0,      # 新增记录数
            'updated': 0,    # 更新记录数
            'failed': 0      # 失败记录数
        }
        
        # 进度信息
        self.progress = {
            'current': 0,
            'total': 3,      # 三种资金流向数据
            'percentage': 0
        }
    
    def update_fund_flow_data(self, last_update_date: str, target_date: str) -> Dict:
        """
        更新资金流向数据
        
        流程：
        1. 计算需要获取的天数 (从 last_update_date 到 target_date)
        2. 获取个股、行业、板块资金流向数据
        3. 覆盖数据库中该时间段的数据
        
        参数：
            last_update_date: 上次更新日期 (YYYY-MM-DD)
            target_date: 目标更新日期 (YYYY-MM-DD)
        
        返回：
            {
                'success': bool,
                'added': int,
                'updated': int,
                'failed': int,
                'message': str,
                'total_time': float
            }
        """
        start_time = datetime.now()
        
        try:
            logger.info(f"开始更新资金流向数据")
            
            # 第1步：计算需要获取的天数
            logger.info("第1步: 计算需要获取的天数...")
            days_to_fetch = self._calculate_days_to_fetch(last_update_date, target_date)
            
            if days_to_fetch <= 0:
                logger.info("无需更新资金流向数据（已是最新）")
                return {
                    'success': True,
                    'added': 0,
                    'updated': 0,
                    'failed': 0,
                    'message': '无需更新资金流向数据（已是最新）',
                    'total_time': (datetime.now() - start_time).total_seconds()
                }
            
            logger.info(f"需要获取 {days_to_fetch} 天的资金流向数据")
            
            # 第2步：更新个股资金流向
            logger.info("第2步: 更新个股资金流向...")
            self.progress['current'] = 1
            self.progress['percentage'] = int((self.progress['current'] / self.progress['total']) * 100)
            
            try:
                stock_result = self._update_stock_fund_flow(days_to_fetch)
                self.stats['added'] += stock_result['added']
                self.stats['updated'] += stock_result['updated']
                self.stats['failed'] += stock_result['failed']
            except Exception as e:
                logger.warning(f"更新个股资金流向失败: {str(e)}")
                self.stats['failed'] += 1
            
            # 第3步：更新行业资金流向
            logger.info("第3步: 更新行业资金流向...")
            self.progress['current'] = 2
            self.progress['percentage'] = int((self.progress['current'] / self.progress['total']) * 100)
            
            try:
                industry_result = self._update_industry_fund_flow(days_to_fetch)
                self.stats['added'] += industry_result['added']
                self.stats['updated'] += industry_result['updated']
                self.stats['failed'] += industry_result['failed']
            except Exception as e:
                logger.warning(f"更新行业资金流向失败: {str(e)}")
                self.stats['failed'] += 1
            
            # 第4步：更新板块资金流向
            logger.info("第4步: 更新板块资金流向...")
            self.progress['current'] = 3
            self.progress['percentage'] = int((self.progress['current'] / self.progress['total']) * 100)
            
            try:
                sector_result = self._update_sector_fund_flow(days_to_fetch)
                self.stats['added'] += sector_result['added']
                self.stats['updated'] += sector_result['updated']
                self.stats['failed'] += sector_result['failed']
            except Exception as e:
                logger.warning(f"更新板块资金流向失败: {str(e)}")
                self.stats['failed'] += 1
            
            # 第5步：返回结果
            total_time = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"资金流向数据更新完成: 新增 {self.stats['added']} 条, 更新 {self.stats['updated']} 条, 失败 {self.stats['failed']} 条, 耗时 {total_time:.1f}秒")
            
            return {
                'success': True,
                'added': self.stats['added'],
                'updated': self.stats['updated'],
                'failed': self.stats['failed'],
                'message': f"资金流向数据更新完成: 新增 {self.stats['added']} 条, 更新 {self.stats['updated']} 条",
                'total_time': total_time
            }
        
        except Exception as e:
            logger.error(f"资金流向数据更新失败: {str(e)}")
            total_time = (datetime.now() - start_time).total_seconds()
            
            return {
                'success': False,
                'added': self.stats['added'],
                'updated': self.stats['updated'],
                'failed': self.stats['failed'],
                'message': f"资金流向数据更新失败: {str(e)}",
                'error': str(e),
                'total_time': total_time
            }
    
    def _get_latest_fund_flow_date(self) -> str:
        """
        查询最新资金流向日期（取三个表的最小值）
        
        返回：
            最新资金流向日期 (YYYY-MM-DD)
        """
        try:
            # 查询三个表的最新日期
            stock_date = self._get_latest_stock_fund_flow_date()
            industry_date = self._get_latest_industry_fund_flow_date()
            sector_date = self._get_latest_sector_fund_flow_date()
            
            # 取最小值（最早的日期）
            dates = [d for d in [stock_date, industry_date, sector_date] if d]
            
            if not dates:
                # 如果没有数据，返回30天前的日期
                return (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            
            latest_date = min(dates)
            logger.debug(f"最新资金流向日期: {latest_date}")
            
            return latest_date
        
        except Exception as e:
            logger.error(f"查询最新资金流向日期失败: {str(e)}")
            # 默认返回30天前的日期
            return (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    def _get_latest_stock_fund_flow_date(self) -> Optional[str]:
        """查询个股资金流向的最新日期"""
        try:
            sql = "SELECT MAX(flow_date) as max_date FROM stock_fund_flow"
            result = self.db_manager.query_one(sql)
            
            if result and result[0]:
                return result[0]
            
            return None
        
        except Exception as e:
            logger.debug(f"查询个股资金流向最新日期失败: {str(e)}")
            return None
    
    def _get_latest_industry_fund_flow_date(self) -> Optional[str]:
        """查询行业资金流向的最新日期"""
        try:
            sql = "SELECT MAX(trade_date) as max_date FROM industry_fund_flow"
            result = self.db_manager.query_one(sql)
            
            if result and result[0]:
                return result[0]
            
            return None
        
        except Exception as e:
            logger.debug(f"查询行业资金流向最新日期失败: {str(e)}")
            return None
    
    def _get_latest_sector_fund_flow_date(self) -> Optional[str]:
        """查询板块资金流向的最新日期"""
        try:
            sql = "SELECT MAX(trade_date) as max_date FROM sector_fund_flow"
            result = self.db_manager.query_one(sql)
            
            if result and result[0]:
                return result[0]
            
            return None
        
        except Exception as e:
            logger.debug(f"查询板块资金流向最新日期失败: {str(e)}")
            return None
    
    def _calculate_days_to_fetch(self, last_update_date: str, target_date: str) -> int:
        """
        计算需要获取的天数
        
        参数：
            last_update_date: 上次更新日期 (YYYY-MM-DD)
            target_date: 目标更新日期 (YYYY-MM-DD)
        
        返回：
            需要获取的天数
        """
        try:
            # 解析日期
            last_date = datetime.strptime(last_update_date, '%Y-%m-%d')
            target = datetime.strptime(target_date, '%Y-%m-%d')
            
            # 计算天数差
            days_diff = (target - last_date).days
            
            # 为了确保获取到所有新数据，多获取2天
            days_to_fetch = max(days_diff + 2, 5)
            
            logger.debug(f"上次更新日期: {last_update_date}, 目标日期: {target_date}, 需要获取: {days_to_fetch} 天")
            
            return days_to_fetch
        
        except Exception as e:
            logger.error(f"计算需要获取的天数失败: {str(e)}")
            # 默认获取30天
            return 30
    
    def _update_stock_fund_flow(self, days: int) -> Dict:
        """
        更新个股资金流向
        
        流程：
        1. 计算时间范围
        2. 删除该时间段的旧数据
        3. 获取新数据
        4. 插入新数据
        
        参数：
            days: 获取最近多少天的数据
        
        返回：
            {'added': int, 'updated': int, 'failed': int}
        """
        added = 0
        updated = 0
        failed = 0
        
        try:
            logger.info(f"更新个股资金流向: 获取最近 {days} 天的数据...")
            
            # 计算时间范围
            end_date_str = datetime.now().strftime('%Y-%m-%d')
            start_date_str = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            logger.debug(f"时间范围: {start_date_str} 到 {end_date_str}")
            
            # 删除该时间段的旧数据
            logger.debug(f"删除 {start_date_str} 到 {end_date_str} 的旧数据...")
            delete_sql = "DELETE FROM stock_fund_flow WHERE flow_date >= ? AND flow_date <= ?"
            self.db_manager.execute_with_retry(delete_sql, (start_date_str, end_date_str))
            
            # 获取新数据 - 转换日期格式为 YYYYMMDD
            logger.debug(f"获取 {start_date_str} 到 {end_date_str} 的个股资金流向数据...")
            start_date_fmt = datetime.strptime(start_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            end_date_fmt = datetime.strptime(end_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            df_fund_flow = self.fund_flow_fetcher._fetch_daily_stock_moneyflow(start_date_fmt, end_date_fmt, None)
            
            if df_fund_flow is not None and len(df_fund_flow) > 0:
                # 插入新数据
                logger.debug(f"插入 {len(df_fund_flow)} 条个股资金流向数据...")
                added = self._save_stock_fund_flow_records(df_fund_flow)
                logger.info(f"个股资金流向更新完成: 新增 {added} 条")
            else:
                logger.warning(f"获取个股资金流向数据失败或无数据")
                failed = 1
            
            return {
                'added': added,
                'updated': updated,
                'failed': failed
            }
        
        except Exception as e:
            logger.error(f"更新个股资金流向失败: {str(e)}")
            return {
                'added': added,
                'updated': updated,
                'failed': 1
            }
    
    def _update_industry_fund_flow(self, days: int) -> Dict:
        """
        更新行业资金流向
        
        流程：
        1. 计算时间范围
        2. 删除该时间段的旧数据
        3. 获取新数据
        4. 插入新数据
        
        参数：
            days: 获取最近多少天的数据
        
        返回：
            {'added': int, 'updated': int, 'failed': int}
        """
        added = 0
        updated = 0
        failed = 0
        
        try:
            logger.info(f"更新行业资金流向: 获取最近 {days} 天的数据...")
            
            # 计算时间范围
            end_date_str = datetime.now().strftime('%Y-%m-%d')
            start_date_str = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            logger.debug(f"时间范围: {start_date_str} 到 {end_date_str}")
            
            # 删除该时间段的旧数据
            logger.debug(f"删除 {start_date_str} 到 {end_date_str} 的旧数据...")
            delete_sql = "DELETE FROM industry_fund_flow WHERE flow_date >= ? AND flow_date <= ?"
            self.db_manager.execute_with_retry(delete_sql, (start_date_str, end_date_str))
            
            # 获取新数据 - 转换日期格式为 YYYYMMDD
            logger.debug(f"获取 {start_date_str} 到 {end_date_str} 的行业资金流向数据...")
            start_date_fmt = datetime.strptime(start_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            end_date_fmt = datetime.strptime(end_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            df_fund_flow = self.fund_flow_fetcher._fetch_daily_industry_moneyflow(start_date_fmt, end_date_fmt, None)
            
            if df_fund_flow is not None and len(df_fund_flow) > 0:
                # 插入新数据
                logger.debug(f"插入 {len(df_fund_flow)} 条行业资金流向数据...")
                added = self._save_industry_fund_flow_records(df_fund_flow)
                logger.info(f"行业资金流向更新完成: 新增 {added} 条")
            else:
                logger.warning(f"获取行业资金流向数据失败或无数据")
                failed = 1
            
            return {
                'added': added,
                'updated': updated,
                'failed': failed
            }
        
        except Exception as e:
            logger.error(f"更新行业资金流向失败: {str(e)}")
            return {
                'added': added,
                'updated': updated,
                'failed': 1
            }
    
    def _update_sector_fund_flow(self, days: int) -> Dict:
        """
        更新板块资金流向
        
        流程：
        1. 计算时间范围
        2. 删除该时间段的旧数据
        3. 获取新数据
        4. 插入新数据
        
        参数：
            days: 获取最近多少天的数据
        
        返回：
            {'added': int, 'updated': int, 'failed': int}
        """
        added = 0
        updated = 0
        failed = 0
        
        try:
            logger.info(f"更新板块资金流向: 获取最近 {days} 天的数据...")
            
            # 计算时间范围
            end_date_str = datetime.now().strftime('%Y-%m-%d')
            start_date_str = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            logger.debug(f"时间范围: {start_date_str} 到 {end_date_str}")
            
            # 删除该时间段的旧数据
            logger.debug(f"删除 {start_date_str} 到 {end_date_str} 的旧数据...")
            delete_sql = "DELETE FROM sector_fund_flow WHERE flow_date >= ? AND flow_date <= ?"
            self.db_manager.execute_with_retry(delete_sql, (start_date_str, end_date_str))
            
            # 获取新数据 - 转换日期格式为 YYYYMMDD
            logger.debug(f"获取 {start_date_str} 到 {end_date_str} 的板块资金流向数据...")
            start_date_fmt = datetime.strptime(start_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            end_date_fmt = datetime.strptime(end_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            df_fund_flow = self.fund_flow_fetcher._fetch_daily_sector_moneyflow(start_date_fmt, end_date_fmt, None)
            
            if df_fund_flow is not None and len(df_fund_flow) > 0:
                # 插入新数据
                logger.debug(f"插入 {len(df_fund_flow)} 条板块资金流向数据...")
                added = self._save_sector_fund_flow_records(df_fund_flow)
                logger.info(f"板块资金流向更新完成: 新增 {added} 条")
            else:
                logger.warning(f"获取板块资金流向数据失败或无数据")
                failed = 1
            
            return {
                'added': added,
                'updated': updated,
                'failed': failed
            }
        
        except Exception as e:
            logger.error(f"更新板块资金流向失败: {str(e)}")
            return {
                'added': added,
                'updated': updated,
                'failed': 1
            }
    
    def _save_stock_fund_flow_records(self, df_fund_flow: pd.DataFrame) -> int:
        """
        保存个股资金流向记录到数据库
        
        参数：
            df_fund_flow: 资金流向数据DataFrame
        
        返回：
            保存的记录数
        """
        saved = 0
        
        try:
            # INSERT SQL 语句
            insert_sql = """
            INSERT INTO stock_fund_flow 
            (stock_code, flow_date, period, main_net_flow, super_large_net_flow, 
             large_net_flow, medium_net_flow, small_net_flow, net_flow_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            # 使用事务保存数据
            with self.db_manager.transaction():
                for _, row in df_fund_flow.iterrows():
                    try:
                        # 将日期转换为字符串格式
                        date_str = str(row.get('trade_date', '')).split(' ')[0]
                        
                        # 执行INSERT操作
                        self.db_manager.execute_with_retry(insert_sql, (
                            row.get('code', ''),
                            date_str,
                            '5d',  # 默认周期为5日
                            float(row.get('main_net_flow', 0)),
                            float(row.get('super_large_net_flow', 0)),
                            float(row.get('large_net_flow', 0)),
                            float(row.get('medium_net_flow', 0)),
                            float(row.get('small_net_flow', 0)),
                            float(row.get('net_flow_rate', 0))
                        ))
                        
                        saved += 1
                    
                    except Exception as e:
                        logger.debug(f"保存个股资金流向数据失败: {str(e)}")
            
            logger.debug(f"保存个股资金流向数据成功: {saved} 条记录")
            
            return saved
        
        except Exception as e:
            logger.error(f"保存个股资金流向数据失败: {str(e)}")
            return 0
    
    def _save_industry_fund_flow_records(self, df_fund_flow: pd.DataFrame) -> int:
        """
        保存行业资金流向记录到数据库
        
        参数：
            df_fund_flow: 资金流向数据DataFrame
        
        返回：
            保存的记录数
        """
        saved = 0
        
        try:
            # INSERT SQL 语句
            insert_sql = """
            INSERT INTO industry_fund_flow 
            (industry_name, trade_date, buy_vol, buy_amount, sell_vol, sell_amount, net_vol, net_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            # 使用事务保存数据
            with self.db_manager.transaction():
                for _, row in df_fund_flow.iterrows():
                    try:
                        # 将日期转换为字符串格式
                        date_str = str(row['trade_date']).split(' ')[0]
                        
                        # 执行INSERT操作
                        self.db_manager.execute_with_retry(insert_sql, (
                            row['industry_name'],
                            date_str,
                            int(row.get('buy_vol', 0)),
                            float(row.get('buy_amount', 0)),
                            int(row.get('sell_vol', 0)),
                            float(row.get('sell_amount', 0)),
                            int(row.get('net_vol', 0)),
                            float(row.get('net_amount', 0))
                        ))
                        
                        saved += 1
                    
                    except Exception as e:
                        logger.debug(f"保存行业资金流向数据失败: {str(e)}")
            
            logger.debug(f"保存行业资金流向数据成功: {saved} 条记录")
            
            return saved
        
        except Exception as e:
            logger.error(f"保存行业资金流向数据失败: {str(e)}")
            return 0
    
    def _save_sector_fund_flow_records(self, df_fund_flow: pd.DataFrame) -> int:
        """
        保存板块资金流向记录到数据库
        
        参数：
            df_fund_flow: 资金流向数据DataFrame
        
        返回：
            保存的记录数
        """
        saved = 0
        
        try:
            # INSERT SQL 语句
            insert_sql = """
            INSERT INTO sector_fund_flow 
            (sector_name, trade_date, buy_vol, buy_amount, sell_vol, sell_amount, net_vol, net_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            # 使用事务保存数据
            with self.db_manager.transaction():
                for _, row in df_fund_flow.iterrows():
                    try:
                        # 将日期转换为字符串格式
                        date_str = str(row['trade_date']).split(' ')[0]
                        
                        # 执行INSERT操作
                        self.db_manager.execute_with_retry(insert_sql, (
                            row['sector_name'],
                            date_str,
                            int(row.get('buy_vol', 0)),
                            float(row.get('buy_amount', 0)),
                            int(row.get('sell_vol', 0)),
                            float(row.get('sell_amount', 0)),
                            int(row.get('net_vol', 0)),
                            float(row.get('net_amount', 0))
                        ))
                        
                        saved += 1
                    
                    except Exception as e:
                        logger.debug(f"保存板块资金流向数据失败: {str(e)}")
            
            logger.debug(f"保存板块资金流向数据成功: {saved} 条记录")
            
            return saved
        
        except Exception as e:
            logger.error(f"保存板块资金流向数据失败: {str(e)}")
            return 0
    
    def get_progress(self) -> Dict:
        """获取更新进度"""
        return self.progress.copy()
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.stats.copy()
