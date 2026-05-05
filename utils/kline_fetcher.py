"""
K线数据批量处理器 - 批量获取、处理和保存K线数据
"""
import pandas as pd
import logging
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# 配置日志
logger = logging.getLogger(__name__)


class KlineFetcher:
    """K线数据批量处理器"""
    
    def __init__(self, db_manager, stock_data_fetcher):
        """
        初始化K线数据处理器
        
        参数：
            db_manager: 数据库管理器
            stock_data_fetcher: 股票数据采集器
        """
        self.db_manager = db_manager
        self.stock_data_fetcher = stock_data_fetcher
    
    # ==================== K线批量获取 ====================
    
    def _fetch_kline_batch(self, stock_codes: list, days: int = 30, use_concurrent: bool = False, max_workers: int = 5) -> dict:
        """
        批量获取K线数据 - 所有股票获取相同天数的数据
        支持并发获取以提升性能（默认关闭，因为可能导致 API 限流）
        
        参数：
            stock_codes: 股票代码列表
            days: 获取最近多少天的数据
            use_concurrent: 是否使用并发获取（默认 False，避免 API 限流）
            max_workers: 并发线程数（默认 5，减少并发数）
        
        返回：
            dict: {stock_code: DataFrame, ...}
        """
        logger.info(f"批量获取K线数据: {len(stock_codes)} 只股票，每只获取 {days} 天数据...")
        
        if use_concurrent:
            return self._fetch_kline_concurrent(stock_codes, days, max_workers)
        else:
            return self._fetch_kline_sequential(stock_codes, days)
    
    def _fetch_kline_sequential(self, stock_codes: list, days: int = 30) -> dict:
        """
        顺序获取K线数据（串行方式）
        
        参数：
            stock_codes: 股票代码列表
            days: 获取最近多少天的数据
        
        返回：
            dict: {stock_code: DataFrame, ...}
        """
        logger.info(f"使用顺序方式获取K线数据: {len(stock_codes)} 只股票...")
        
        results = {}
        success_count = 0
        failed_count = 0
        
        for idx, code in enumerate(stock_codes, 1):
            try:
                # 调用 stock_data_fetcher 获取K线数据
                df_kline = self.stock_data_fetcher.fetch_stock_update(code, days=days)
                
                if df_kline is not None and len(df_kline) > 0:
                    results[code] = df_kline
                    success_count += 1
                else:
                    failed_count += 1
                
                # 定期输出进度（每100只股票输出一次）
                if idx % 100 == 0:
                    logger.info(f"顺序获取进度: {idx}/{len(stock_codes)}, 成功: {success_count}, 失败: {failed_count}")
            
            except Exception as e:
                logger.debug(f"获取 {code} K线数据失败: {e}")
                failed_count += 1
        
        logger.info(f"顺序获取完成: {success_count} 只成功, {failed_count} 只失败")
        return results
    
    def _fetch_kline_concurrent(self, stock_codes: list, days: int = 30, max_workers: int = 10) -> dict:
        """
        并发获取K线数据（多线程方式）
        
        参数：
            stock_codes: 股票代码列表
            days: 获取最近多少天的数据
            max_workers: 并发线程数
        
        返回：
            dict: {stock_code: DataFrame, ...}
        """
        logger.info(f"使用并发方式获取K线数据: {len(stock_codes)} 只股票，并发线程数: {max_workers}...")
        
        results = {}
        success_count = 0
        failed_count = 0
        start_time = time.time()
        total_count = len(stock_codes)
        
        # 使用 ThreadPoolExecutor 并发获取
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_code = {
                executor.submit(self.stock_data_fetcher.fetch_stock_update, code, days): code 
                for code in stock_codes
            }
            
            # 处理完成的任务
            completed_count = 0
            for future in as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    df_kline = future.result()
                    
                    if df_kline is not None and len(df_kline) > 0:
                        results[code] = df_kline
                        success_count += 1
                    else:
                        failed_count += 1
                
                except Exception as e:
                    logger.debug(f"获取 {code} K线数据失败: {e}")
                    failed_count += 1
                
                # 定期输出进度（每100只股票输出一次）
                completed_count += 1
                if completed_count % 100 == 0:
                    elapsed = time.time() - start_time
                    progress_pct = (completed_count / total_count) * 100
                    estimated_total = elapsed * total_count / completed_count
                    estimated_remaining = estimated_total - elapsed
                    logger.info(f"并发获取进度: {completed_count}/{total_count} ({progress_pct:.1f}%), 成功: {success_count}, 失败: {failed_count}, 耗时: {elapsed:.1f}秒, 预计剩余: {estimated_remaining:.1f}秒")
        
        elapsed = time.time() - start_time
        logger.info(f"并发获取完成: {success_count} 只成功, {failed_count} 只失败, 总耗时: {elapsed:.1f}秒")
        return results
    
    # ==================== 数据库操作 ====================
    
    def _batch_update_kline_to_db(self, kline_data: dict) -> tuple:
        """
        批量更新K线数据到数据库 - 使用 UPSERT 语句
        
        参数：
            kline_data: {stock_code: DataFrame, ...}
        
        返回：
            (updated_count, failed_count)
        """
        logger.info(f"批量更新K线数据到数据库: {len(kline_data)} 只股票...")
        
        # UPSERT SQL 语句
        upsert_sql = """
        INSERT INTO stock_kline (code, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code, date) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume
        """
        
        updated_count = 0
        failed_count = 0
        total_records = 0
        
        # 统计总记录数
        for df in kline_data.values():
            total_records += len(df)
        
        # 批量插入所有数据
        try:
            with self.db_manager.transaction():
                record_count = 0
                for code, df in kline_data.items():
                    try:
                        for idx_row, row in df.iterrows():
                            try:
                                # 将日期转换为字符串格式
                                date_str = str(row['date']).split(' ')[0]
                                
                                # 使用 UPSERT 语句
                                self.db_manager.execute_with_retry(upsert_sql, (
                                    code, date_str,
                                    float(row['open']), float(row['high']), float(row['low']), 
                                    float(row['close']), int(row['volume'])
                                ))
                                record_count += 1
                            except Exception as e:
                                logger.debug(f"保存 {code} K线数据失败: {e}")
                                failed_count += 1
                        
                        updated_count += 1
                    except Exception as e:
                        logger.debug(f"处理 {code} K线数据失败: {e}")
                        failed_count += 1
        except Exception as e:
            logger.error(f"批量更新K线数据失败: {e}")
        
        logger.info(f"批量更新完成: {updated_count} 只成功, {failed_count} 只失败, {record_count} 条记录")
        return updated_count, failed_count
    
    def _get_latest_kline_date(self, stock_code: str) -> Optional[str]:
        """
        获取某只股票的最新K线日期
        
        参数：
            stock_code: 股票代码
        
        返回：
            最新K线日期（格式: YYYY-MM-DD），如果没有数据则返回 None
        """
        try:
            sql = "SELECT MAX(date) as latest_date FROM stock_kline WHERE code = ?"
            result = self.db_manager.query_one(sql, (stock_code,))
            
            if result and result.get('latest_date'):
                return result['latest_date']
            return None
        except Exception as e:
            logger.debug(f"查询 {stock_code} 最新K线日期失败: {e}")
            return None
    
    def _calculate_days_to_fetch(self, stock_code: str) -> int:
        """
        计算某只股票需要获取的天数（从上次更新到今天）
        如果当天已更新，返回 0（表示跳过）
        
        参数：
            stock_code: 股票代码
        
        返回：
            需要获取的天数，0 表示跳过（当天已更新）
        """
        try:
            # 获取最新K线日期
            latest_date = self._get_latest_kline_date(stock_code)
            today_str = datetime.now().strftime('%Y-%m-%d')
            
            if latest_date is None:
                # 如果没有数据，默认获取 365 天（一年）
                logger.debug(f"{stock_code} 没有K线数据，将获取 365 天")
                return 365
            
            # 检查当天是否已更新
            if latest_date == today_str:
                logger.debug(f"{stock_code} 当天已更新，将跳过")
                return 0  # 返回 0 表示跳过
            
            # 计算从最新日期到今天的天数
            latest_dt = datetime.strptime(latest_date, '%Y-%m-%d')
            today = datetime.now()
            days_diff = (today - latest_dt).days
            
            # 为了确保获取到所有新数据，多获取 2 天
            days_to_fetch = max(days_diff + 2, 5)
            
            logger.debug(f"{stock_code} 最新日期: {latest_date}, 需要获取: {days_to_fetch} 天")
            return days_to_fetch
        
        except Exception as e:
            logger.debug(f"计算 {stock_code} 需要获取的天数失败: {e}，默认获取 30 天")
            return 30
