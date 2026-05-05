"""
K线数据增量更新器

功能：
1. 计算需要获取的天数
2. 分批获取K线数据
3. 流式处理：边获取边保存
4. 统计更新结果

特点：
- 流式处理，避免一次性加载所有数据到内存
- 使用UPSERT操作，避免重复检查
- 分批处理，提高网络请求成功率
- 完善的错误处理和重试机制
"""

import logging
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import pandas as pd
import time

logger = logging.getLogger(__name__)


class KlineUpdater:
    """K线数据增量更新器"""
    
    def __init__(self, db_manager, stock_data_fetcher):
        """
        初始化K线更新器
        
        参数：
            db_manager: 数据库管理器
            stock_data_fetcher: 股票数据采集器
        """
        self.db_manager = db_manager
        self.stock_data_fetcher = stock_data_fetcher
        
        # 统计信息
        self.stats = {
            'added': 0,      # 新增记录数
            'updated': 0,    # 更新记录数
            'failed': 0      # 失败记录数
        }
        
        # 进度信息
        self.progress = {
            'current': 0,
            'total': 0,
            'percentage': 0
        }
    
    def update_kline_data(self, stock_codes: List[str], last_update_date: str, target_date: str, batch_size: int = 100) -> Dict:
        """
        增量更新K线数据
        
        流程：
        1. 计算需要获取的天数 (从 last_update_date 到 target_date)
        2. 分批获取数据（所有股票使用相同的天数范围）
        3. 立即保存到数据库
        
        参数：
            stock_codes: 股票代码列表
            last_update_date: 上次更新日期 (YYYY-MM-DD)
            target_date: 目标更新日期 (YYYY-MM-DD)
            batch_size: 每批处理的股票数
        
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
            logger.info(f"开始更新K线数据: {len(stock_codes)} 只股票")
            
            # 第1步：计算需要获取的天数
            logger.info("第1步: 计算需要获取的天数...")
            days_to_fetch = self._calculate_days_to_fetch(last_update_date, target_date)
            
            if days_to_fetch <= 0:
                logger.info("无需更新K线数据（已是最新）")
                return {
                    'success': True,
                    'added': 0,
                    'updated': 0,
                    'failed': 0,
                    'message': '无需更新K线数据（已是最新）',
                    'total_time': (datetime.now() - start_time).total_seconds()
                }
            
            logger.info(f"需要获取 {days_to_fetch} 天的K线数据")
            
            # 第2步：分批处理
            logger.info(f"第2步: 分批处理 {len(stock_codes)} 只股票...")
            self.progress['total'] = len(stock_codes)
            
            for batch_idx in range(0, len(stock_codes), batch_size):
                # 获取该批股票
                batch_codes = stock_codes[batch_idx:batch_idx + batch_size]
                
                # 更新进度
                self.progress['current'] = min(batch_idx + batch_size, len(stock_codes))
                self.progress['percentage'] = int((self.progress['current'] / self.progress['total']) * 100)
                
                logger.info(f"处理进度: [{self.progress['current']}/{self.progress['total']}] {self.progress['percentage']}%")
                
                # 获取并保存该批数据
                try:
                    batch_result = self._fetch_and_save_batch(batch_codes, days_to_fetch)
                    self.stats['added'] += batch_result['added']
                    self.stats['updated'] += batch_result['updated']
                    self.stats['failed'] += batch_result['failed']
                except Exception as e:
                    logger.warning(f"处理批次失败: {str(e)}")
                    self.stats['failed'] += len(batch_codes)
            
            # 第3步：返回结果
            total_time = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"K线数据更新完成: 新增 {self.stats['added']} 条, 更新 {self.stats['updated']} 条, 失败 {self.stats['failed']} 条, 耗时 {total_time:.1f}秒")
            
            return {
                'success': True,
                'added': self.stats['added'],
                'updated': self.stats['updated'],
                'failed': self.stats['failed'],
                'message': f"K线数据更新完成: 新增 {self.stats['added']} 条, 更新 {self.stats['updated']} 条",
                'total_time': total_time
            }
        
        except Exception as e:
            logger.error(f"K线数据更新失败: {str(e)}")
            total_time = (datetime.now() - start_time).total_seconds()
            
            return {
                'success': False,
                'added': self.stats['added'],
                'updated': self.stats['updated'],
                'failed': self.stats['failed'],
                'message': f"K线数据更新失败: {str(e)}",
                'error': str(e),
                'total_time': total_time
            }
    
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
            
            # 为了确保获取到所有新数据，多获取2天，最小获取3天
            days_to_fetch = max(days_diff + 2, 3)
            
            logger.debug(f"上次更新日期: {last_update_date}, 目标日期: {target_date}, 需要获取: {days_to_fetch} 天")
            
            return days_to_fetch
        
        except Exception as e:
            logger.error(f"计算需要获取的天数失败: {str(e)}")
            # 默认获取30天
            return 30
    
    def _fetch_and_save_batch(self, batch_codes: List[str], days: int) -> Dict:
        """
        获取一批股票的K线数据并立即保存
        
        流程：
        1. 获取该批股票的K线数据（带重试机制）
        2. 立即保存到数据库（UPSERT）
        3. 返回统计信息
        
        参数：
            batch_codes: 股票代码列表
            days: 获取最近多少天的数据
        
        返回：
            {'added': int, 'updated': int, 'failed': int}
        """
        added = 0
        updated = 0
        failed = 0
        failed_stocks = []  # 记录失败的股票
        processed_count = 0  # 已处理股票数
        log_interval = 100  # 每100只股票打一次日志
        
        try:
            logger.info(f"获取 {len(batch_codes)} 只股票的K线数据...")
            
            # 对每只股票获取K线数据
            for stock_code in batch_codes:
                try:
                    # 获取K线数据（带重试）
                    df_kline = self._fetch_with_retry(stock_code, days, max_retries=2)
                    
                    if df_kline is not None and len(df_kline) > 0:
                        # 保存到数据库（按100条记录一批保存）
                        batch_added, batch_updated = self._save_kline_records_batch(stock_code, df_kline, batch_size=100)
                        added += batch_added
                        updated += batch_updated
                    else:
                        # 获取数据为空
                        failed += 1
                        failed_stocks.append(stock_code)
                        logger.debug(f"获取 {stock_code} K线数据为空或无数据")
                
                except Exception as e:
                    # 获取数据异常
                    failed += 1
                    failed_stocks.append(stock_code)
                    logger.error(f"处理 {stock_code} K线数据异常: {type(e).__name__}: {str(e)}")
                
                # 更新已处理计数
                processed_count += 1
                
                # 每100只股票打一次日志
                if processed_count % log_interval == 0:
                    logger.info(f"已处理 {processed_count}/{len(batch_codes)} 只股票，新增 {added} 条记录")
            
            # 记录失败的股票列表
            if failed_stocks:
                logger.warning(f"失败的股票: {', '.join(failed_stocks[:10])}" + 
                             (f" 等 {len(failed_stocks)} 只" if len(failed_stocks) > 10 else ""))
            
            logger.info(f"批次处理完成: 已处理 {processed_count} 只股票，新增 {added} 条, 更新 {updated} 条, 失败 {failed} 条")
            
            return {
                'added': added,
                'updated': updated,
                'failed': failed
            }
        
        except Exception as e:
            logger.error(f"批次处理失败: {str(e)}")
            return {
                'added': added,
                'updated': updated,
                'failed': failed + len(batch_codes)
            }
    
    def _fetch_with_retry(self, stock_code: str, days: int, max_retries: int = 2) -> Optional[pd.DataFrame]:
        """
        带重试机制的获取K线数据
        
        参数：
            stock_code: 股票代码
            days: 获取最近多少天的数据
            max_retries: 最大重试次数
        
        返回：
            K线数据DataFrame，如果失败则返回None
        """
        import time
        
        for attempt in range(max_retries):
            try:
                # 获取K线数据
                df_kline = self.stock_data_fetcher.fetch_stock_update(stock_code, days=days)
                
                if df_kline is not None and len(df_kline) > 0:
                    # 成功获取数据
                    if attempt > 0:
                        logger.debug(f"{stock_code} 第 {attempt + 1} 次尝试成功")
                    return df_kline
                
                # 数据为空，不需要重试
                return None
            
            except Exception as e:
                # 发生异常，尝试重试
                if attempt < max_retries - 1:
                    # 等待后重试
                    wait_time = 0.5 * (attempt + 1)  # 递增等待时间
                    logger.debug(f"{stock_code} 获取失败，{wait_time}秒后重试: {str(e)}")
                    time.sleep(wait_time)
                else:
                    # 最后一次重试也失败
                    logger.error(f"{stock_code} 重试 {max_retries} 次后仍失败: {str(e)}")
                    return None
        
        return None
    
    def _save_kline_records_batch(self, stock_code, df_kline, batch_size = 100):
        """
        批量保存K线记录到数据库
        
        使用UPSERT操作：INSERT OR REPLACE
        使用executemany批量执行，大幅提升性能
        
        参数：
            stock_code: 股票代码
            df_kline: K线数据DataFrame
            batch_size: 每批保存的记录数（已弃用，保留用于兼容性）
        
        返回：
            (新增数, 更新数)
        """
        added = 0
        updated = 0
        
        try:
            # UPSERT SQL 语句
            upsert_sql = """
            INSERT OR REPLACE INTO stock_kline 
            (code, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            
            # 确定成交量列名：优先使用volume，其次使用vol
            volume_col = 'volume' if 'volume' in df_kline.columns else 'vol'
            
            # 使用向量化操作准备数据，比iterrows()快10-100倍
            try:
                # 准备日期列
                dates = df_kline['date'].astype(str).str.split(' ').str[0]
                
                # 准备成交量列，处理NaN值
                volumes = df_kline[volume_col].fillna(0).astype(int)
                
                # 准备OHLC数据
                opens = df_kline['open'].astype(float)
                highs = df_kline['high'].astype(float)
                lows = df_kline['low'].astype(float)
                closes = df_kline['close'].astype(float)
                
                # 构建记录列表（使用zip比iterrows快得多）
                records_to_save = list(zip(
                    [stock_code] * len(df_kline),  # 股票代码
                    dates,                           # 日期
                    opens,                           # 开盘价
                    highs,                           # 最高价
                    lows,                            # 最低价
                    closes,                          # 收盘价
                    volumes                          # 成交量
                ))
                
            except Exception as e:
                logger.error(f"准备 {stock_code} K线数据失败: {str(e)}")
                return 0, 0
            
            # 使用原生executemany批量保存所有记录，大幅提升性能
            if records_to_save:
                with self.db_manager.transaction():
                    conn = self.db_manager.connect()
                    cursor = conn.cursor()
                    cursor.executemany(upsert_sql, records_to_save)
                added = len(records_to_save)
            
            return added, updated
        
        except Exception as e:
            logger.error(f"保存 {stock_code} K线数据失败: {str(e)}")
            return 0, 0
    
    def get_progress(self) -> Dict:
        """获取更新进度"""
        return self.progress.copy()
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.stats.copy()
