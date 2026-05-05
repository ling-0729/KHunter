"""
K线历史数据初始化模块
用于初始化 stock_kline 表，加载 5000+ 只A股的 3 年历史K线数据
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import time
import pandas as pd
from pathlib import Path

# 配置日志
logger = logging.getLogger(__name__)


class KlineInitializer:
    """K线数据初始化器"""
    
    def __init__(self, db_manager, akshare_fetcher):
        """
        初始化K线初始化器
        
        Args:
            db_manager: 数据库管理器实例
            akshare_fetcher: AKShare数据获取器实例
        """
        # db_manager: 数据库管理器，类型DBManager，必填
        self.db_manager = db_manager
        # akshare_fetcher: 数据获取器，类型AKShareFetcher，必填
        self.akshare_fetcher = akshare_fetcher
        
        # 进度信息字典
        self.progress = {
            'task_id': '',
            'status': 'idle',  # idle, running, completed, failed
            'start_time': None,
            'end_time': None,
            'processed': 0,
            'total': 0,
            'inserted_records': 0,
            'failed_stocks': [],
            'current_stock': '',
            'logs': []
        }
    
    def _check_kline_initialized(self):
        """
        检查K线数据是否已初始化
        
        Returns:
            bool: 已初始化返回True，否则返回False
        """
        try:
            # 检查stock_kline表是否有数据
            result = self.db_manager.query_one("SELECT COUNT(*) as count FROM stock_kline")
            if result and result.get('count', 0) > 0:
                kline_count = result['count']
                logger.info(f"K线数据已初始化: stock_kline={kline_count}条")
                return True
            return False
        except Exception as e:
            logger.warning(f"检查K线数据是否已初始化失败: {str(e)}")
            return False
    
    def initialize_kline_data(self, stock_codes: Optional[List[str]] = None, 
                             years: int = 3, batch_size: int = 100):
        """
        初始化K线数据
        
        Args:
            stock_codes: 股票代码列表，不提供则获取全部
            years: 历史年份数，默认3年
            batch_size: 每批处理的股票数，默认100
        
        Returns:
            初始化结果字典
        """
        # 检查K线数据是否已初始化
        if self._check_kline_initialized():
            return {
                'success': False,
                'message': 'K线数据初始化已经完成，无需再次初始化'
            }
        
        # 生成任务ID
        task_id = f"KLINE_INIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        # 重置进度信息
        self.progress = {
            'task_id': task_id,
            'status': 'running',
            'start_time': datetime.now(),
            'end_time': None,
            'processed': 0,
            'total': 0,
            'inserted_records': 0,
            'failed_stocks': [],
            'current_stock': '',
            'logs': []
        }
        
        try:
            # 获取股票列表
            if stock_codes is None:
                logger.info("获取全部A股股票列表...")
                stock_dict = self.akshare_fetcher.get_all_stock_codes()
                stock_codes = list(stock_dict.keys())
            
            self.progress['total'] = len(stock_codes)
            logger.info(f"开始K线数据初始化: 任务ID={task_id}, 股票数={len(stock_codes)}, 年份={years}")
            self._log(f"初始化开始: 共 {len(stock_codes)} 只股票")
            
            # 分批处理
            total_batches = (len(stock_codes) + batch_size - 1) // batch_size
            for batch_idx in range(total_batches):
                # 获取当前批次的股票代码
                start_idx = batch_idx * batch_size
                end_idx = min(start_idx + batch_size, len(stock_codes))
                batch_codes = stock_codes[start_idx:end_idx]
                
                # 处理当前批次
                batch_result = self._fetch_and_insert_batch(batch_codes, years)
                
                # 更新进度
                self.progress['processed'] += len(batch_codes)
                self.progress['inserted_records'] += batch_result['inserted']
                self.progress['failed_stocks'].extend(batch_result['failed'])
                
                # 输出进度
                progress_pct = (self.progress['processed'] / self.progress['total']) * 100
                elapsed = (datetime.now() - self.progress['start_time']).total_seconds()
                speed = self.progress['processed'] / elapsed if elapsed > 0 else 0
                estimated_remaining = (self.progress['total'] - self.progress['processed']) / speed if speed > 0 else 0
                
                if (batch_idx + 1) % 5 == 0 or batch_idx == 0:
                    msg = f"进度: [{self.progress['processed']}/{self.progress['total']}] {progress_pct:.1f}% | " \
                          f"已插入: {self.progress['inserted_records']} 条 | " \
                          f"失败: {len(self.progress['failed_stocks'])} 只 | " \
                          f"耗时: {elapsed:.0f}秒 | " \
                          f"预计剩余: {estimated_remaining:.0f}秒"
                    logger.info(msg)
                    self._log(msg)
            
            # 初始化完成
            self.progress['status'] = 'completed'
            self.progress['end_time'] = datetime.now()
            total_time = (self.progress['end_time'] - self.progress['start_time']).total_seconds()
            
            result = {
                'success': True,
                'task_id': task_id,
                'message': '初始化完成',
                'total_stocks': self.progress['total'],
                'processed_stocks': self.progress['processed'],
                'inserted_records': self.progress['inserted_records'],
                'failed_stocks': len(self.progress['failed_stocks']),
                'total_time': total_time,
                'failed_stock_list': self.progress['failed_stocks'][:10]  # 返回前10个失败的股票
            }
            
            logger.info(f"K线初始化完成: {result}")
            self._log(f"初始化完成: 共插入 {self.progress['inserted_records']} 条记录, 耗时 {total_time:.0f}秒")
            return result
        
        except Exception as e:
            # 初始化失败
            self.progress['status'] = 'failed'
            self.progress['end_time'] = datetime.now()
            logger.error(f"K线初始化失败: {str(e)}")
            self._log(f"初始化失败: {str(e)}")
            
            return {
                'success': False,
                'task_id': task_id,
                'message': f'初始化失败: {str(e)}',
                'error': str(e)
            }
    
    def _fetch_and_insert_batch(self, batch_codes: List[str], years: int) -> Dict:
        """
        获取并插入一批股票的K线数据
        
        Args:
            batch_codes: 股票代码列表
            years: 历史年份数
        
        Returns:
            批次处理结果字典
        """
        # batch_codes: 股票代码列表，类型List[str]，必填
        # years: 历史年份数，类型int，必填
        inserted = 0
        failed = []
        
        for code in batch_codes:
            try:
                # 更新当前处理的股票
                self.progress['current_stock'] = code
                
                # 获取历史数据
                df = self.akshare_fetcher.fetch_stock_history(code, years=years)
                
                if df is None or df.empty:
                    logger.warning(f"获取股票数据为空: {code}")
                    failed.append(code)
                    continue
                
                # 转换数据格式
                records = self._convert_dataframe_to_records(code, df)
                
                # 插入数据库
                inserted_count = self._insert_kline_records(records)
                inserted += inserted_count
                
                logger.debug(f"股票 {code} 初始化完成: 插入 {inserted_count} 条记录")
            
            except Exception as e:
                logger.error(f"处理股票 {code} 失败: {str(e)}")
                failed.append(code)
                continue
        
        return {
            'inserted': inserted,
            'failed': failed
        }
    
    def _convert_dataframe_to_records(self, stock_code: str, df: pd.DataFrame) -> List[Dict]:
        """
        将DataFrame转换为数据库记录格式
        
        Args:
            stock_code: 股票代码
            df: 股票数据DataFrame
        
        Returns:
            记录列表
        """
        # stock_code: 股票代码，类型str，必填
        # df: 股票数据，类型pd.DataFrame，必填
        records = []
        
        for _, row in df.iterrows():
            try:
                # 转换日期格式
                if isinstance(row['date'], pd.Timestamp):
                    date_str = row['date'].strftime('%Y-%m-%d')
                else:
                    date_str = str(row['date'])
                
                # 构建记录
                record = {
                    'code': stock_code,
                    'date': date_str,
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': int(row.get('volume', 0)),
                    'market_cap': float(row.get('market_cap', 0)),
                    'K': float(row.get('K', 0)),
                    'D': float(row.get('D', 0)),
                    'J': float(row.get('J', 0))
                }
                records.append(record)
            
            except Exception as e:
                logger.warning(f"转换记录失败 ({stock_code}): {str(e)}")
                continue
        
        return records
    
    def _insert_kline_records(self, records: List[Dict]) -> int:
        """
        批量插入K线记录到数据库
        
        Args:
            records: 记录列表
        
        Returns:
            插入的记录数
        """
        # records: 记录列表，类型List[Dict]，必填
        if not records:
            return 0
        
        try:
            # 使用事务插入
            conn = self.db_manager.connect()
            cursor = conn.cursor()
            
            # 构建INSERT OR REPLACE语句
            sql = """
                INSERT OR REPLACE INTO stock_kline 
                (code, date, open, high, low, close, volume, market_cap, K, D, J, created_date, updated_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
            
            # 批量插入
            for record in records:
                cursor.execute(sql, (
                    record['code'],
                    record['date'],
                    record['open'],
                    record['high'],
                    record['low'],
                    record['close'],
                    record['volume'],
                    record['market_cap'],
                    record['K'],
                    record['D'],
                    record['J']
                ))
            
            # 提交事务（不关闭连接，由db_manager管理）
            conn.commit()
            
            logger.debug(f"插入 {len(records)} 条K线记录成功")
            return len(records)
        
        except Exception as e:
            logger.error(f"插入K线记录失败: {str(e)}")
            return 0
    
    def get_progress(self) -> Dict:
        """
        获取初始化进度
        
        Returns:
            进度信息字典
        """
        # 计算已耗时和预计剩余时间
        if self.progress['start_time']:
            elapsed = (datetime.now() - self.progress['start_time']).total_seconds()
            if self.progress['processed'] > 0 and elapsed > 0:
                speed = self.progress['processed'] / elapsed
                estimated_remaining = (self.progress['total'] - self.progress['processed']) / speed if speed > 0 else 0
            else:
                estimated_remaining = 0
        else:
            elapsed = 0
            estimated_remaining = 0
        
        # 计算进度百分比
        progress_pct = (self.progress['processed'] / self.progress['total'] * 100) if self.progress['total'] > 0 else 0
        
        return {
            'task_id': self.progress['task_id'],
            'status': self.progress['status'],
            'progress': round(progress_pct, 1),
            'processed': self.progress['processed'],
            'total': self.progress['total'],
            'inserted_records': self.progress['inserted_records'],
            'failed_stocks': len(self.progress['failed_stocks']),
            'current_stock': self.progress['current_stock'],
            'elapsed_time': round(elapsed, 0),
            'estimated_remaining': round(estimated_remaining, 0),
            'logs': self.progress['logs'][-20:]  # 返回最后20条日志
        }
    
    def _log(self, message: str) -> None:
        """
        记录日志信息
        
        Args:
            message: 日志消息
        """
        # message: 日志消息，类型str，必填
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        self.progress['logs'].append(log_entry)
        
        # 只保留最后100条日志
        if len(self.progress['logs']) > 100:
            self.progress['logs'] = self.progress['logs'][-100:]
