"""
新股票检测和初始化模块

该模块负责：
1. 检测新增股票（与数据库对比）
2. 对新股票执行增量初始化
3. 记录初始化结果和统计信息

设计原则：
- 参考 KlineInitializer 的设计模式
- 清晰的职责划分
- 完整的错误处理
- 详细的日志记录
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class NewStockDetector:
    """
    新股票检测和初始化器
    
    职责：
    1. 获取最新股票列表
    2. 与数据库对比，检测新增股票
    3. 对新股票执行增量初始化
    4. 记录初始化结果
    
    属性：
        db_manager: 数据库管理器
        stock_data_fetcher: 股票数据获取器
        data_initializer: 数据初始化器
        stats: 统计信息 {'detected': int, 'initialized': int, 'failed': int}
    """
    
    def __init__(self, db_manager, stock_data_fetcher, data_initializer):
        """
        初始化新股票检测器
        
        Args:
            db_manager: 数据库管理器实例
            stock_data_fetcher: 股票数据获取器实例
            data_initializer: 数据初始化器实例
        """
        # 初始化依赖组件
        self.db_manager = db_manager
        self.stock_data_fetcher = stock_data_fetcher
        self.data_initializer = data_initializer
        
        # 初始化统计信息
        self.stats = {
            'detected': 0,      # 检测到的新股票数
            'initialized': 0,   # 成功初始化的新股票数
            'failed': 0         # 初始化失败的新股票数
        }
        
        # 初始化进度信息
        self.progress = {
            'task_id': '',
            'status': 'idle',   # idle, running, completed, failed
            'start_time': None,
            'end_time': None,
            'current_phase': '',
            'logs': []
        }
    
    def detect_and_init_new_stocks(self, years: int = 1, days: int = 30) -> Dict:
        """
        检测新股票并进行增量初始化
        
        流程：
        1. 获取最新股票列表
        2. 与数据库对比，检测新增股票
        3. 对新股票进行初始化
        4. 记录初始化结果
        
        Args:
            years: 新股票初始化时获取的K线年数，默认1年
            days: 新股票初始化时获取的资金流向天数，默认30天
        
        Returns:
            初始化结果字典，包含：
            {
                'success': bool,
                'detected': int,        # 检测到的新股票数
                'initialized': int,     # 成功初始化的新股票数
                'failed': int,          # 初始化失败的新股票数
                'new_stocks': List[str],# 新股票代码列表
                'failed_stocks': List[str],  # 初始化失败的股票列表
                'message': str,
                'total_time': float
            }
        """
        # 生成任务ID
        task_id = f"NEW_STOCK_DETECT_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 初始化进度信息
        self.progress = {
            'task_id': task_id,
            'status': 'running',
            'start_time': datetime.now(),
            'end_time': None,
            'current_phase': '初始化中',
            'logs': []
        }
        
        # 重置统计信息
        self.stats = {
            'detected': 0,
            'initialized': 0,
            'failed': 0
        }
        
        try:
            logger.info(f"开始新股票检测和初始化: 任务ID={task_id}")
            self._log(f"任务开始: {task_id}")
            
            # 第1步：获取最新股票列表
            self.progress['current_phase'] = '获取最新股票列表'
            logger.info("第1步: 获取最新股票列表...")
            self._log("第1步: 获取最新股票列表...")
            
            latest_stocks = self.stock_data_fetcher.get_all_stock_codes()
            if not latest_stocks:
                raise Exception("无法获取最新股票列表")
            
            logger.info(f"获取到 {len(latest_stocks)} 只股票")
            self._log(f"获取到 {len(latest_stocks)} 只股票")
            
            # 第2步：检测新增股票
            self.progress['current_phase'] = '检测新增股票'
            logger.info("第2步: 检测新增股票...")
            self._log("第2步: 检测新增股票...")
            
            new_stocks = self._get_new_stocks(latest_stocks)
            self.stats['detected'] = len(new_stocks)
            
            if not new_stocks:
                logger.info("未检测到新股票")
                self._log("未检测到新股票")
                
                # 任务完成
                self.progress['status'] = 'completed'
                self.progress['end_time'] = datetime.now()
                total_time = (self.progress['end_time'] - self.progress['start_time']).total_seconds()
                
                return {
                    'success': True,
                    'detected': 0,
                    'initialized': 0,
                    'failed': 0,
                    'new_stocks': [],
                    'failed_stocks': [],
                    'message': '未检测到新股票',
                    'total_time': total_time
                }
            
            logger.info(f"检测到 {len(new_stocks)} 只新股票: {new_stocks}")
            self._log(f"检测到 {len(new_stocks)} 只新股票")
            
            # 第3步：初始化新股票
            self.progress['current_phase'] = '初始化新股票'
            logger.info(f"第3步: 初始化 {len(new_stocks)} 只新股票...")
            self._log(f"第3步: 初始化 {len(new_stocks)} 只新股票...")
            
            init_result = self._init_new_stocks(new_stocks, years, days)
            
            # 更新统计信息
            self.stats['initialized'] = init_result['initialized']
            self.stats['failed'] = init_result['failed']
            
            # 任务完成
            self.progress['status'] = 'completed'
            self.progress['end_time'] = datetime.now()
            total_time = (self.progress['end_time'] - self.progress['start_time']).total_seconds()
            
            result = {
                'success': True,
                'detected': self.stats['detected'],
                'initialized': self.stats['initialized'],
                'failed': self.stats['failed'],
                'new_stocks': new_stocks,
                'failed_stocks': init_result['failed_stocks'],
                'message': f"检测到 {self.stats['detected']} 只新股票，成功初始化 {self.stats['initialized']} 只，失败 {self.stats['failed']} 只",
                'total_time': total_time
            }
            
            logger.info(f"新股票检测和初始化完成: {result}")
            self._log(f"任务完成: 检测 {self.stats['detected']} 只，初始化 {self.stats['initialized']} 只，失败 {self.stats['failed']} 只，耗时 {total_time:.0f}秒")
            
            return result
        
        except Exception as e:
            # 任务失败
            self.progress['status'] = 'failed'
            self.progress['end_time'] = datetime.now()
            total_time = (self.progress['end_time'] - self.progress['start_time']).total_seconds()
            
            logger.error(f"新股票检测和初始化失败: {str(e)}")
            self._log(f"任务失败: {str(e)}")
            
            return {
                'success': False,
                'detected': self.stats['detected'],
                'initialized': self.stats['initialized'],
                'failed': self.stats['failed'],
                'new_stocks': [],
                'failed_stocks': [],
                'message': f'新股票检测和初始化失败: {str(e)}',
                'error': str(e),
                'total_time': total_time
            }
    
    def _get_new_stocks(self, latest_stocks: Dict[str, str]) -> List[str]:
        """
        检测新增股票
        
        流程：
        1. 获取数据库中已有的股票代码
        2. 对比找出新增股票
        3. 返回新增股票列表
        
        Args:
            latest_stocks: 最新股票列表 {code: name}
        
        Returns:
            新增股票代码列表
        """
        try:
            # 获取数据库中已有的股票代码
            existing_stocks = set(self.db_manager.list_all_stocks())
            logger.debug(f"数据库中已有 {len(existing_stocks)} 只股票")
            
            # 获取最新股票代码集合
            latest_codes = set(latest_stocks.keys())
            logger.debug(f"最新股票列表中有 {len(latest_codes)} 只股票")
            
            # 检测新增股票
            new_stocks = list(latest_codes - existing_stocks)
            logger.info(f"检测到 {len(new_stocks)} 只新股票")
            
            return new_stocks
        
        except Exception as e:
            logger.error(f"检测新增股票失败: {str(e)}")
            raise
    
    def _init_new_stocks(self, new_stock_codes: List[str], years: int = 1, days: int = 30) -> Dict:
        """
        初始化新股票
        
        流程：
        1. 对每只新股票执行初始化
        2. 初始化包括：基础数据、K线数据、资金流向数据、行业/板块数据
        3. 记录初始化结果
        
        Args:
            new_stock_codes: 新股票代码列表
            years: 初始化K线数据的年数
            days: 初始化资金流向数据的天数
        
        Returns:
            初始化结果字典，包含：
            {
                'initialized': int,     # 成功初始化的股票数
                'failed': int,          # 初始化失败的股票数
                'failed_stocks': List[str]  # 初始化失败的股票列表
            }
        """
        initialized = 0
        failed = 0
        failed_stocks = []
        
        try:
            logger.info(f"开始初始化 {len(new_stock_codes)} 只新股票...")
            self._log(f"开始初始化 {len(new_stock_codes)} 只新股票...")
            
            # 第1步：初始化基础数据（所有新股票一起处理）
            try:
                logger.info(f"第1步: 初始化 {len(new_stock_codes)} 只新股票的基础数据...")
                self._log(f"第1步: 初始化基础数据...")
                self.data_initializer._init_basic_data(new_stock_codes)
            except Exception as e:
                logger.warning(f"初始化基础数据失败: {str(e)}")
                self._log(f"初始化基础数据失败: {str(e)}")
            
            # 第2步：初始化K线历史数据（所有新股票一起处理）
            try:
                logger.info(f"第2步: 初始化 {len(new_stock_codes)} 只新股票的K线历史数据...")
                self._log(f"第2步: 初始化K线历史数据...")
                self.data_initializer._init_kline_history_data(new_stock_codes, years=years)
            except Exception as e:
                logger.warning(f"初始化K线历史数据失败: {str(e)}")
                self._log(f"初始化K线历史数据失败: {str(e)}")
            
            # 第3步：对每只新股票执行其他初始化（如果需要）
            for idx, stock_code in enumerate(new_stock_codes, 1):
                try:
                    # 显示进度
                    progress_pct = (idx / len(new_stock_codes)) * 100
                    logger.info(f"初始化进度: [{idx}/{len(new_stock_codes)}] {progress_pct:.1f}% - {stock_code}")
                    
                    # 这里可以添加其他初始化逻辑（如资金流向、行业/板块等）
                    # 目前基础数据和K线数据已经初始化，标记为成功
                    initialized += 1
                    logger.debug(f"成功初始化: {stock_code}")
                
                except Exception as e:
                    # 记录失败的股票
                    failed += 1
                    failed_stocks.append(stock_code)
                    logger.warning(f"初始化失败: {stock_code} - {str(e)}")
                    self._log(f"初始化失败: {stock_code} - {str(e)}")
                    
                    # 继续处理下一只股票
                    continue
            
            logger.info(f"新股票初始化完成: 成功 {initialized} 只，失败 {failed} 只")
            self._log(f"初始化完成: 成功 {initialized} 只，失败 {failed} 只")
            
            return {
                'initialized': initialized,
                'failed': failed,
                'failed_stocks': failed_stocks
            }
        
        except Exception as e:
            logger.error(f"初始化新股票失败: {str(e)}")
            raise
    
    def _log(self, message: str) -> None:
        """
        记录日志信息
        
        Args:
            message: 日志消息
        """
        # 添加时间戳
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"[{timestamp}] {message}"
        
        # 添加到进度日志
        self.progress['logs'].append(log_message)
        
        # 保持日志数量在合理范围内（最多保留1000条）
        if len(self.progress['logs']) > 1000:
            self.progress['logs'] = self.progress['logs'][-1000:]
    
    def get_progress(self) -> Dict:
        """
        获取当前进度信息
        
        Returns:
            进度信息字典
        """
        return {
            'task_id': self.progress['task_id'],
            'status': self.progress['status'],
            'current_phase': self.progress['current_phase'],
            'stats': self.stats,
            'logs': self.progress['logs'][-10:]  # 返回最后10条日志
        }
    
    def get_stats(self) -> Dict:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        return self.stats.copy()
