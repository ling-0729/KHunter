"""
数据采集服务模块
用于管理数据初始化和更新的业务逻辑
"""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from utils.db_initializer import DatabaseInitializer
from utils.akshare_fetcher import AKShareFetcher
from utils.db_manager import DBManager
from utils.trading_time_validator import TradingTimeValidator
from utils.new_stock_detector import NewStockDetector
from utils.stock_data_fetcher import StockDataFetcher
from utils.data_initializer import DataInitializer
from utils.kline_updater import KlineUpdater
from utils.fund_flow_updater import FundFlowUpdater
from utils.fund_flow_fetcher import FundFlowFetcher
from datetime import timedelta

# 配置日志
logger = logging.getLogger(__name__)


class DataCollectionService:
    """数据采集服务类"""
    
    def __init__(self, data_dir: str = 'data'):
        """
        初始化数据采集服务
        
        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化各个管理器
        self.db_initializer = DatabaseInitializer(str(self.data_dir))
        self.akshare_fetcher = AKShareFetcher()
        
        # 数据库路径
        self.selection_db_path = self.data_dir / 'stock_selection.db'
        
        # 初始化数据库管理器
        from utils.global_db import get_global_db
        self.db_manager = get_global_db()
        
        # 初始化股票数据获取器
        self.stock_data_fetcher = StockDataFetcher()
        
        # 初始化状态
        self.init_status = {
            'running': False,
            'paused': False,
            'progress': 0,
            'total': 0,
            'current_task': '',
            'success': 0,
            'failed': 0,
            'message': '',
            'start_time': None,
            'end_time': None,
            'logs': [],
            'status': 'idle',  # idle, running, paused, completed, failed, cancelled
            'statistics': {}
        }
        
        # 更新状态
        self.update_status = {
            'running': False,
            'paused': False,
            'progress': 0,
            'total': 0,
            'current_task': '',
            'success': 0,
            'failed': 0,
            'message': '',
            'start_time': None,
            'end_time': None,
            'logs': [],
            'status': 'idle',  # idle, running, paused, completed, failed, cancelled
            'statistics': {},
            'tasks': [],  # 任务列表
            'totalStats': {  # 统计数据
                'added': 0,
                'updated': 0,
                'deleted': 0,
                'processed': 0,
                'new_stock_detected': 0,
                'new_stock_initialized': 0
            }
        }
        
        # 线程锁
        self.init_lock = threading.Lock()
        self.update_lock = threading.Lock()
    
    def get_init_config(self) -> Dict[str, Any]:
        """
        获取初始化配置
        
        Returns:
            dict: 初始化配置信息
        """
        return {
            'types': ['full', 'structure_only', 'custom'],
            'defaultType': 'full',
            'customOptions': {
                'structure': True,
                'basicData': True,
                'historyData': True,
                'industryData': True,
                'sectorData': True,
                'fundFlowData': True
            },
            'dateRangeDefault': {
                'start': '2024-01-01',
                'end': datetime.now().strftime('%Y-%m-%d')
            }
        }
    
    def get_update_config(self) -> Dict[str, Any]:
        """
        获取更新配置
        
        Returns:
            dict: 更新配置信息
        """
        return {
            'updateTypes': [
                'basic_data',
                'history_data',
                'industry_data',
                'sector_data',
                'fund_flow_data',
                'event_data'
            ],
            'defaultUpdateTypes': [
                'basic_data',
                'history_data',
                'industry_data',
                'sector_data',
                'fund_flow_data',
                'event_data'
            ],
            'updateFrequency': {
                'basic_data': 'weekly',
                'history_data': 'daily',
                'industry_data': 'daily',
                'sector_data': 'daily',
                'fund_flow_data': 'daily',
                'event_data': 'daily'
            }
        }
    
    def _check_data_initialized(self):
        """
        检查股票基础数据和K线数据是否已初始化
        
        Returns:
            bool: 已初始化返回True，否则返回False
        """
        try:
            # 检查stock_basic表是否有数据
            basic_count = 0
            try:
                result = self.db_manager.query_one("SELECT COUNT(*) as count FROM stock_basic")
                if result and result.get('count', 0) > 0:
                    basic_count = result['count']
            except Exception as e:
                logger.debug(f"检查stock_basic表失败: {str(e)}")
            
            # 检查stock_kline表是否有数据
            kline_count = 0
            try:
                result = self.db_manager.query_one("SELECT COUNT(*) as count FROM stock_kline")
                if result and result.get('count', 0) > 0:
                    kline_count = result['count']
            except Exception as e:
                logger.debug(f"检查stock_kline表失败: {str(e)}")
            
            # 如果两个表都有数据，说明已初始化
            if basic_count > 0 and kline_count > 0:
                logger.info(f"数据已初始化: stock_basic={basic_count}条, stock_kline={kline_count}条")
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"检查数据是否已初始化失败: {str(e)}")
            return False
    
    def start_initialization(self, init_type: str = 'full', options: Optional[Dict] = None):
        """
        开始数据初始化
        
        Args:
            init_type: 初始化类型 (full, structure_only, custom)
            options: 自定义选项
        
        Returns:
            dict: 初始化任务信息
        """
        # 检查是否已有初始化任务运行
        if self.init_status['running']:
            return {
                'success': False,
                'message': '已有初始化任务正在运行',
                'taskId': None
            }
        
        # 检查数据是否已初始化
        if self._check_data_initialized():
            return {
                'success': False,
                'message': '初始化已经完成，无需再次初始化',
                'taskId': None
            }
        
        # 生成任务ID
        task_id = f"INIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 在后台线程中执行初始化
        thread = threading.Thread(
            target=self._run_initialization,
            args=(task_id, init_type, options),
            daemon=True
        )
        thread.start()
        
        return {
            'success': True,
            'message': '初始化任务已启动',
            'taskId': task_id
        }
    
    def _run_initialization(self, task_id: str, init_type: str, options: Optional[Dict]):
        """
        执行初始化任务（在后台线程中运行）
        
        Args:
            task_id: 任务ID
            init_type: 初始化类型
            options: 自定义选项
        """
        with self.init_lock:
            # 检查是否已有初始化任务在运行
            if self.init_status['running']:
                logger.warning(f"初始化任务 {task_id} 已在运行，跳过执行")
                return
                
            try:
                # 初始化状态
                self.init_status['running'] = True
                self.init_status['paused'] = False
                self.init_status['status'] = 'running'
                self.init_status['progress'] = 0
                self.init_status['success'] = 0
                self.init_status['failed'] = 0
                self.init_status['start_time'] = datetime.now().isoformat()
                self.init_status['logs'] = []
                self.init_status['statistics'] = {}
                
                # 记录日志
                self._add_init_log(f"✓ 初始化任务 {task_id} 已启动")
                
                # 尝试导入并调用WebSocket推送函数
                try:
                    from web_server import emit_init_progress
                    emit_init_progress()
                except ImportError:
                    pass
                
                # 初始化数据（仅支持自定义初始化）
                if init_type == 'custom':
                    # 自定义初始化
                    total_tasks = 0
                    completed_tasks = 0
                    
                    # 计算总任务数
                    if options.get('basicData'):
                        total_tasks += 1
                    if options.get('historyData'):
                        total_tasks += 1
                    if options.get('industryData'):
                        total_tasks += 1
                    if options.get('sectorData'):
                        total_tasks += 1
                    if options.get('fundFlowData'):
                        total_tasks += 1
                    
                    # 初始化股票列表
                    stock_dict = self.akshare_fetcher.get_all_stock_codes()
                    stock_codes = list(stock_dict.keys()) if stock_dict else []
                    
                    # 初始化采集器
                    self.akshare_fetcher._init_collectors()
                    
                    # 初始化基础数据
                    if options.get('basicData'):
                        self.init_status['current_task'] = '初始化基础数据'
                        self._add_init_log("⟳ 正在初始化基础数据...")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                        
                        # 传入stock_dict参数，避免重复获取股票数据
                        self.akshare_fetcher._init_basic_data(stock_codes, stock_dict)
                        completed_tasks += 1
                        self.init_status['progress'] = int((completed_tasks / total_tasks) * 100)
                        self._add_init_log("✓ 基础数据初始化完成")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                    
                    # 初始化历史行情数据
                    if options.get('historyData'):
                        self.init_status['current_task'] = '初始化历史行情数据'
                        self._add_init_log("⟳ 正在初始化历史行情数据...")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                        
                        self.akshare_fetcher._init_history_data(stock_codes)
                        completed_tasks += 1
                        self.init_status['progress'] = int((completed_tasks / total_tasks) * 100)
                        self._add_init_log("✓ 历史行情数据初始化完成")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                    
                    # 初始化行业数据
                    if options.get('industryData'):
                        self.init_status['current_task'] = '初始化行业数据'
                        self._add_init_log("⟳ 正在初始化行业数据...")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                        
                        self.akshare_fetcher._init_industry_data(stock_codes)
                        completed_tasks += 1
                        self.init_status['progress'] = int((completed_tasks / total_tasks) * 100)
                        self._add_init_log("✓ 行业数据初始化完成")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                    
                    # 初始化板块数据
                    if options.get('sectorData'):
                        self.init_status['current_task'] = '初始化板块数据'
                        self._add_init_log("⟳ 正在初始化板块数据...")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                        
                        self.akshare_fetcher._init_sector_data(stock_codes)
                        completed_tasks += 1
                        self.init_status['progress'] = int((completed_tasks / total_tasks) * 100)
                        self._add_init_log("✓ 板块数据初始化完成")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                    
                    # 初始化资金流向数据
                    if options.get('fundFlowData'):
                        self.init_status['current_task'] = '初始化资金流向数据'
                        self._add_init_log("⟳ 正在初始化资金流向数据...")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                        
                        self.akshare_fetcher._init_fund_flow_data(stock_codes)
                        completed_tasks += 1
                        self.init_status['progress'] = int((completed_tasks / total_tasks) * 100)
                        self._add_init_log("✓ 资金流向数据初始化完成")
                        
                        # 尝试导入并调用WebSocket推送函数
                        try:
                            from web_server import emit_init_progress
                            emit_init_progress()
                        except ImportError:
                            pass
                
                # 完成
                self.init_status['progress'] = 100
                self.init_status['end_time'] = datetime.now().isoformat()
                self.init_status['message'] = '初始化完成'
                self.init_status['status'] = 'completed'
                self.init_status['success'] = 1
                self._add_init_log("✓ 初始化任务完成")
                
                # 更新统计信息
                self.init_status['statistics'] = self.get_tables_stats()
                
                # 尝试导入并调用WebSocket推送函数
                try:
                    from web_server import emit_init_progress
                    emit_init_progress()
                except ImportError:
                    pass
                
                logger.info(f"初始化任务 {task_id} 完成")
                
            except Exception as e:
                self.init_status['failed'] += 1
                self.init_status['message'] = f'初始化失败: {str(e)}'
                self.init_status['status'] = 'failed'
                self._add_init_log(f"✗ 错误: {str(e)}")
                
                # 尝试导入并调用WebSocket推送函数
                try:
                    from web_server import emit_init_progress
                    emit_init_progress()
                except ImportError:
                    pass
                
                logger.error(f"初始化任务 {task_id} 失败: {str(e)}")
            
            finally:
                self.init_status['running'] = False
                
                # 尝试导入并调用WebSocket推送函数
                try:
                    from web_server import emit_init_progress
                    emit_init_progress()
                except ImportError:
                    pass
    
    def get_init_progress(self) -> Dict[str, Any]:
        """
        获取初始化进度
        
        Returns:
            dict: 初始化进度信息，包含前端期望的所有字段
        """
        # 返回前端期望的格式
        return {
            'status': self.init_status['status'],
            'progress': self.init_status['progress'],
            'currentTask': self.init_status['current_task'],
            'currentTaskName': self.init_status['current_task'],
            'currentTaskProgress': 0,
            'currentTaskTotal': 0,
            'speed': 0,
            'estimatedTime': 0,
            'logs': self.init_status['logs'][-50:],  # 返回最后50条日志
            'statistics': self.init_status['statistics'],
            'message': self.init_status['message'],
            'running': self.init_status['running'],
            'paused': self.init_status['paused']
        }
    
    def cancel_initialization(self) -> Dict[str, Any]:
        """
        取消初始化任务
        
        Returns:
            dict: 取消结果
        """
        if not self.init_status['running']:
            return {
                'success': False,
                'message': '没有正在运行的初始化任务'
            }
        
        # 标记为取消
        self.init_status['running'] = False
        self.init_status['status'] = 'cancelled'
        self.init_status['message'] = '初始化已取消'
        self._add_init_log("✗ 初始化任务已取消")
        
        return {
            'success': True,
            'message': '初始化任务已取消'
        }
    
    def pause_initialization(self) -> Dict[str, Any]:
        """
        暂停初始化任务
        
        Returns:
            dict: 暂停结果
        """
        if not self.init_status['running']:
            return {
                'success': False,
                'message': '没有正在运行的初始化任务'
            }
        
        # 标记为暂停
        self.init_status['paused'] = True
        self.init_status['status'] = 'paused'
        self._add_init_log("⏸ 初始化任务已暂停")
        
        return {
            'success': True,
            'message': '初始化任务已暂停'
        }
    
    def resume_initialization(self) -> Dict[str, Any]:
        """
        恢复初始化任务
        
        Returns:
            dict: 恢复结果
        """
        if not self.init_status['paused']:
            return {
                'success': False,
                'message': '没有暂停的初始化任务'
            }
        
        # 标记为继续运行
        self.init_status['paused'] = False
        self.init_status['status'] = 'running'
        self._add_init_log("▶ 初始化任务已恢复")
        
        return {
            'success': True,
            'message': '初始化任务已恢复'
        }
    
    def start_update(self, update_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        开始数据更新
        
        Args:
            update_types: 更新类型列表
        
        Returns:
            dict: 更新任务信息
        """
        # 检查是否已有更新任务运行
        if self.update_status['running']:
            return {
                'success': False,
                'message': '已有更新任务正在运行',
                'taskId': None
            }
        
        # 生成任务ID
        task_id = f"UPDATE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 在后台线程中执行更新
        thread = threading.Thread(
            target=self._run_update,
            args=(task_id, update_types),
            daemon=True
        )
        thread.start()
        
        return {
            'success': True,
            'message': '更新任务已启动',
            'taskId': task_id
        }
    
    def _run_update(self, task_id: str, update_types: Optional[List[str]]):
        """
        执行更新任务（在后台线程中运行）
        
        流程:
        1. 检查交易时间和更新条件
        2. 检测并初始化新股票
        3. 获取所有股票列表
        4. 查询上次更新日期
        5. 更新K线数据
        6. 更新资金流向数据
        7. 更新股票市值信息
        8. 记录更新完成时间
        
        Args:
            task_id: 任务ID
            update_types: 更新类型列表（可选）
        """
        target_date = None
        validator = None
        
        try:
            # 初始化状态
            with self.update_lock:
                self.update_status['running'] = True
                self.update_status['paused'] = False
                self.update_status['status'] = 'running'
                self.update_status['start_time'] = datetime.now().isoformat()
                self.update_status['logs'] = []
                self.update_status['message'] = ''
                self.update_status['totalStats'] = {
                    'new_stock_detected': 0,
                    'new_stock_initialized': 0,
                    'kline_added': 0,
                    'kline_updated': 0,
                    'kline_failed': 0,
                    'fund_flow_added': 0,
                    'fund_flow_updated': 0,
                    'fund_flow_failed': 0,
                    'market_cap_updated': 0,
                    'market_cap_failed': 0
                }
            
            self._add_update_log(f"✓ 更新任务 {task_id} 已启动")
            
            # 【第1步】检查交易时间和更新条件
            self._add_update_log("【第1步】检查交易时间和更新条件...")
            validator = TradingTimeValidator(self.db_manager)
            is_valid, error_msg, target_date = validator.validate_update_time()
            
            if not is_valid:
                # 交易时间验证失败
                with self.update_lock:
                    self.update_status['status'] = 'failed'
                    self.update_status['message'] = error_msg
                
                self._add_update_log(f"✗ 错误: {error_msg}")
                logger.warning(f"更新任务 {task_id} 被拒绝: {error_msg}")
                return
            
            # 记录目标更新日期
            self._add_update_log(f"✓ 目标更新日期: {target_date}")
            
            # 记录更新开始
            validator.record_update_start(target_date)
            
            # 【第2步】检测并初始化新股票（优先级最高）
            self._add_update_log("【第2步】检测并初始化新股票...")
            try:
                # 创建新股票检测器
                stock_data_fetcher = StockDataFetcher()
                data_initializer = DataInitializer(
                    self.db_manager,
                    stock_data_fetcher,
                    None,  # kline_fetcher
                    None   # fund_flow_fetcher
                )
                
                detector = NewStockDetector(
                    self.db_manager,
                    stock_data_fetcher,
                    data_initializer
                )
                
                # 执行新股票检测和初始化
                new_stock_result = detector.detect_and_init_new_stocks(years=1, days=30)
                
                # 更新统计信息
                with self.update_lock:
                    self.update_status['totalStats']['new_stock_detected'] = new_stock_result.get('detected', 0)
                    self.update_status['totalStats']['new_stock_initialized'] = new_stock_result.get('initialized', 0)
                
                # 记录结果
                if new_stock_result['success']:
                    self._add_update_log(f"✓ 新股票检测完成: 检测 {new_stock_result['detected']} 只，初始化 {new_stock_result['initialized']} 只，失败 {new_stock_result['failed']} 只")
                    
                    # 如果有失败的股票，记录警告
                    if new_stock_result['failed'] > 0:
                        failed_stocks = new_stock_result.get('failed_stocks', [])
                        self._add_update_log(f"⚠ 初始化失败的股票: {', '.join(failed_stocks[:5])}")
                else:
                    # 新股票初始化失败，但不影响后续更新
                    self._add_update_log(f"⚠ 新股票检测失败: {new_stock_result.get('message', '未知错误')}")
                    logger.warning(f"新股票检测失败: {new_stock_result.get('message', '未知错误')}")
            
            except Exception as e:
                # 新股票初始化失败，但不影响后续更新
                self._add_update_log(f"⚠ 新股票检测异常: {str(e)}")
                logger.warning(f"新股票检测异常: {str(e)}")
            
            # 【第3步】获取所有股票列表
            self._add_update_log("【第3步】获取所有股票列表...")
            try:
                sql = "SELECT DISTINCT code FROM stock_basic ORDER BY code"
                result = self.db_manager.query(sql)
                stock_codes = [row['code'] for row in result] if result else []
                
                self._add_update_log(f"✓ 获取股票列表完成: {len(stock_codes)} 只股票")
            
            except Exception as e:
                self._add_update_log(f"✗ 获取股票列表失败: {str(e)}")
                logger.error(f"获取股票列表失败: {str(e)}")
                stock_codes = []
            
            # 【第4步】查询上次更新日期
            self._add_update_log("【第4步】查询上次更新日期...")
            try:
                last_update_date = validator.get_last_update_date()
                
                # 如果没有记录，使用默认日期（30天前）
                if not last_update_date:
                    last_update_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                
                self._add_update_log(f"✓ 上次更新日期: {last_update_date}")
            
            except Exception as e:
                self._add_update_log(f"✗ 查询上次更新日期失败: {str(e)}")
                logger.error(f"查询上次更新日期失败: {str(e)}")
                last_update_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            
            # 【第5步】更新K线数据
            if not update_types or 'kline' in update_types:
                self._add_update_log("【第5步】更新K线数据...")
                try:
                    # 创建 KlineUpdater 实例
                    stock_data_fetcher = StockDataFetcher()
                    kline_updater = KlineUpdater(self.db_manager, stock_data_fetcher)
                    
                    # 执行K线数据更新
                    kline_result = kline_updater.update_kline_data(
                        stock_codes=stock_codes,
                        last_update_date=last_update_date,
                        target_date=target_date,
                        batch_size=100
                    )
                    
                    # 更新统计信息
                    with self.update_lock:
                        self.update_status['totalStats']['kline_added'] = kline_result.get('added', 0)
                        self.update_status['totalStats']['kline_updated'] = kline_result.get('updated', 0)
                        self.update_status['totalStats']['kline_failed'] = kline_result.get('failed', 0)
                    
                    # 记录结果
                    if kline_result['success']:
                        self._add_update_log(f"✓ K线数据更新完成: 新增 {kline_result['added']} 条，更新 {kline_result['updated']} 条，失败 {kline_result['failed']} 条，耗时 {kline_result['total_time']:.1f}秒")
                    else:
                        self._add_update_log(f"✗ K线数据更新失败: {kline_result.get('message', '未知错误')}")
                        logger.warning(f"K线数据更新失败: {kline_result.get('message', '未知错误')}")
                
                except Exception as e:
                    self._add_update_log(f"✗ K线数据更新异常: {str(e)}")
                    logger.error(f"K线数据更新异常: {str(e)}")
                    with self.update_lock:
                        self.update_status['totalStats']['kline_failed'] = len(stock_codes)
            
            # 【第6步】更新资金流向数据
            if not update_types or 'fund_flow' in update_types:
                self._add_update_log("【第6步】更新资金流向数据...")
                try:
                    # 创建 FundFlowUpdater 实例
                    fund_flow_fetcher = FundFlowFetcher(self.db_manager)
                    fund_flow_updater = FundFlowUpdater(self.db_manager, fund_flow_fetcher)
                    
                    # 执行资金流向数据更新
                    fund_flow_result = fund_flow_updater.update_fund_flow_data(
                        last_update_date=last_update_date,
                        target_date=target_date
                    )
                    
                    # 更新统计信息
                    with self.update_lock:
                        self.update_status['totalStats']['fund_flow_added'] = fund_flow_result.get('added', 0)
                        self.update_status['totalStats']['fund_flow_updated'] = fund_flow_result.get('updated', 0)
                        self.update_status['totalStats']['fund_flow_failed'] = fund_flow_result.get('failed', 0)
                    
                    # 记录结果
                    if fund_flow_result['success']:
                        self._add_update_log(f"✓ 资金流向数据更新完成: 新增 {fund_flow_result['added']} 条，更新 {fund_flow_result['updated']} 条，失败 {fund_flow_result['failed']} 条，耗时 {fund_flow_result['total_time']:.1f}秒")
                    else:
                        self._add_update_log(f"✗ 资金流向数据更新失败: {fund_flow_result.get('message', '未知错误')}")
                        logger.warning(f"资金流向数据更新失败: {fund_flow_result.get('message', '未知错误')}")
                
                except Exception as e:
                    self._add_update_log(f"✗ 资金流向数据更新异常: {str(e)}")
                    logger.error(f"资金流向数据更新异常: {str(e)}")
                    with self.update_lock:
                        self.update_status['totalStats']['fund_flow_failed'] = 1
            
            # 【第7步】更新股票市值信息
            self._add_update_log("【第7步】更新股票市值信息...")
            try:
                # 创建 StockDataFetcher 实例
                stock_data_fetcher = StockDataFetcher()
                
                # 执行市值数据更新
                market_cap_result = stock_data_fetcher.update_stock_market_cap(
                    db_manager=self.db_manager,
                    max_retries=3
                )
                
                # 更新统计信息
                with self.update_lock:
                    self.update_status['totalStats']['market_cap_updated'] = market_cap_result.get('updated', 0)
                    self.update_status['totalStats']['market_cap_failed'] = market_cap_result.get('failed', 0)
                
                # 记录结果
                if market_cap_result['updated'] > 0:
                    self._add_update_log(f"✓ 股票市值更新完成: 更新 {market_cap_result['updated']} 只，失败 {market_cap_result['failed']} 只")
                else:
                    self._add_update_log(f"⚠ 股票市值更新: 更新 {market_cap_result['updated']} 只，失败 {market_cap_result['failed']} 只")
                    logger.warning(f"股票市值更新: 更新 {market_cap_result['updated']} 只，失败 {market_cap_result['failed']} 只")
            
            except Exception as e:
                self._add_update_log(f"✗ 股票市值更新异常: {str(e)}")
                logger.error(f"股票市值更新异常: {str(e)}")
                with self.update_lock:
                    self.update_status['totalStats']['market_cap_failed'] = len(stock_codes)
            
            # 【第8步】记录更新完成
            self._add_update_log("【第8步】记录更新完成...")
            try:
                # 汇总统计信息
                stats = {
                    'new_stock_detected': self.update_status['totalStats']['new_stock_detected'],
                    'new_stock_initialized': self.update_status['totalStats']['new_stock_initialized'],
                    'kline_added': self.update_status['totalStats']['kline_added'],
                    'kline_updated': self.update_status['totalStats']['kline_updated'],
                    'fund_flow_added': self.update_status['totalStats']['fund_flow_added'],
                    'fund_flow_updated': self.update_status['totalStats']['fund_flow_updated'],
                    'market_cap_updated': self.update_status['totalStats']['market_cap_updated'],
                    'market_cap_failed': self.update_status['totalStats']['market_cap_failed']
                }
                
                # 记录更新完成
                validator.record_update_complete(target_date, stats)
                
                self._add_update_log("✓ 更新统计信息已记录")
            
            except Exception as e:
                self._add_update_log(f"✗ 记录更新完成失败: {str(e)}")
                logger.error(f"记录更新完成失败: {str(e)}")
            
            # 【第9步】计算并保存市场温度
            self._add_update_log("【第9步】计算并保存市场温度...")
            try:
                # 导入市场温度计算器
                from utils.market_temperature import MarketTemperature, DataNotAvailableError
                from trading.market_temperature_dao import MarketTemperatureDAO
                
                # 转换日期格式为 YYYYMMDD
                trade_date_yyyymmdd = target_date.replace('-', '')
                
                # 计算市场温度（不使用缓存，确保获取最新数据）
                mt = MarketTemperature()
                temp_result = mt.calculate(trade_date_yyyymmdd, use_cache=False)
                
                # 保存到数据库
                dao = MarketTemperatureDAO()
                dao.save(temp_result)
                
                # 更新统计信息
                self._add_update_log(
                    f"✓ 市场温度计算完成: {temp_result.get('temperature', 'N/A')}° - "
                    f"{temp_result.get('status', '未知')} - "
                    f"仓位{temp_result.get('position_ratio', 0) * 100:.0f}%"
                )
                logger.info(f"市场温度已保存: {trade_date_yyyymmdd} - {temp_result.get('temperature')}°")
            except DataNotAvailableError as e:
                # 数据不可用（非交易日或API无数据），这是正常的，跳过
                self._add_update_log(f"ℹ 市场温度跳过: {str(e)}")
                logger.info(f"市场温度跳过（非交易日或数据不可用）: {trade_date_yyyymmdd} - {str(e)}")
            
            except Exception as e:
                self._add_update_log(f"⚠ 市场温度计算失败: {str(e)}")
                logger.warning(f"市场温度计算失败: {str(e)}")
            
            # 检查是否有数据被成功更新
            total_added = self.update_status['totalStats']['kline_added'] + self.update_status['totalStats']['fund_flow_added']
            total_updated = self.update_status['totalStats']['kline_updated'] + self.update_status['totalStats']['fund_flow_updated']
            total_success = total_added + total_updated
            
            # 更新任务状态
            with self.update_lock:
                if total_success > 0:
                    # 有数据被成功更新，标记为完成
                    self.update_status['status'] = 'completed'
                    self.update_status['end_time'] = datetime.now().isoformat()
                    self.update_status['message'] = '更新完成'
                    self.update_status['success'] = 1
                else:
                    # 没有数据被成功更新，标记为失败
                    self.update_status['status'] = 'failed'
                    self.update_status['end_time'] = datetime.now().isoformat()
                    self.update_status['message'] = '更新失败: 没有数据被成功更新'
            
            if total_success > 0:
                self._add_update_log("✓ 更新任务完成")
                logger.info(f"更新任务 {task_id} 完成")
            else:
                self._add_update_log("✗ 更新任务失败: 没有数据被成功更新")
                logger.warning(f"更新任务 {task_id} 失败: 没有数据被成功更新")
            
            # 记录更新完成或失败
            if validator and target_date:
                try:
                    if total_success > 0:
                        validator.record_update_complete(target_date, stats)
                    else:
                        validator.record_update_failed(target_date, '没有数据被成功更新')
                except Exception as log_e:
                    logger.error(f"记录更新状态失败: {str(log_e)}")
            
        except Exception as e:
            # 检查是否有数据被成功更新
            total_added = self.update_status['totalStats']['kline_added'] + self.update_status['totalStats']['fund_flow_added']
            total_updated = self.update_status['totalStats']['kline_updated'] + self.update_status['totalStats']['fund_flow_updated']
            total_success = total_added + total_updated
            
            with self.update_lock:
                if total_success > 0:
                    # 有数据被成功更新，标记为完成
                    self.update_status['status'] = 'completed'
                    self.update_status['end_time'] = datetime.now().isoformat()
                    self.update_status['message'] = f'更新完成（部分步骤失败）: {str(e)}'
                    self.update_status['success'] = 1
                else:
                    # 没有数据被成功更新，标记为失败
                    self.update_status['status'] = 'failed'
                    self.update_status['end_time'] = datetime.now().isoformat()
                    self.update_status['message'] = f'更新失败: {str(e)}'
            
            if total_success > 0:
                self._add_update_log(f"✓ 更新任务完成（部分步骤失败）: {str(e)}")
                logger.warning(f"更新任务 {task_id} 完成（部分步骤失败）: {str(e)}")
            else:
                self._add_update_log(f"✗ 错误: {str(e)}")
                logger.error(f"更新任务 {task_id} 失败: {str(e)}")
            
            # 记录更新完成或失败
            if validator and target_date:
                try:
                    if total_success > 0:
                        validator.record_update_complete(target_date, stats)
                    else:
                        validator.record_update_failed(target_date, str(e))
                except Exception as log_e:
                    logger.error(f"记录更新状态失败: {str(log_e)}")
        
        finally:
            with self.update_lock:
                self.update_status['running'] = False
    
    def get_update_progress(self) -> Dict[str, Any]:
        """
        获取更新进度
        
        Returns:
            dict: 更新进度信息
        """
        # 计算已耗时（秒）
        elapsed_time = 0
        if self.update_status['start_time']:
            try:
                start = datetime.fromisoformat(self.update_status['start_time'])
                elapsed_time = int((datetime.now() - start).total_seconds())
            except:
                elapsed_time = 0
        
        # 返回前端期望的格式
        return {
            'running': self.update_status['running'],
            'status': self.update_status['status'],
            'message': self.update_status['message'],
            'startTime': self.update_status['start_time'],
            'endTime': self.update_status['end_time'],
            'elapsedTime': elapsed_time,
            'logs': self.update_status['logs'][-50:],  # 返回最后50条日志
            'totalStats': self.update_status['totalStats']  # 统计数据
        }
    
    def cancel_update(self) -> Dict[str, Any]:
        """
        取消更新任务
        立即停止任务执行，清除进度信息
        
        Returns:
            dict: 取消结果
        """
        # 检查是否有正在运行或已暂停的任务
        if not self.update_status['running'] and not self.update_status.get('paused', False):
            return {
                'success': False,
                'message': '没有正在运行的更新任务'
            }
        
        # 标记为取消
        self.update_status['running'] = False
        self.update_status['paused'] = False
        self.update_status['message'] = '更新已取消'
        self.update_status['status'] = 'cancelled'
        self._add_update_log("✕ 更新任务已取消")
        
        logger.info("更新任务已取消")
        
        return {
            'success': True,
            'message': '更新任务已取消'
        }
    
    def update_task_stats(self, task_id: str, added: int = 0, updated: int = 0, deleted: int = 0):
        """
        更新任务统计数据
        
        Args:
            task_id: 任务ID
            added: 新增数量
            updated: 更新数量
            deleted: 删除数量
        """
        # 更新总统计
        self.update_status['totalStats']['added'] += added
        self.update_status['totalStats']['updated'] += updated
        self.update_status['totalStats']['deleted'] += deleted
        self.update_status['totalStats']['processed'] = (
            self.update_status['totalStats']['added'] +
            self.update_status['totalStats']['updated'] +
            self.update_status['totalStats']['deleted']
        )
    
    def get_tables_info(self) -> Dict[str, Any]:
        """
        获取新增表的信息
        
        Returns:
            dict: 新增表的信息
        """
        return self.db_initializer.get_new_tables_info()
    
    def get_tables_stats(self) -> Dict[str, Any]:
        """
        获取表数据统计
        
        Returns:
            dict: 表数据统计信息
        """
        stats = {}
        
        try:
            if self.selection_db_path.exists():
                import sqlite3
                conn = sqlite3.connect(str(self.selection_db_path))
                cursor = conn.cursor()
                
                # 查询各个表的行数
                tables = [
                    'stock_basic',
                    'stock_kline',
                    'stock_industry',
                    'stock_sector',
                    'stock_fund_flow',
                    'stock_event',
                    'stock_lhb',
                    'stock_margin_trading'
                ]
                
                for table in tables:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cursor.fetchone()[0]
                        stats[table] = count
                    except Exception as e:
                        logger.warning(f"查询表 {table} 行数失败: {str(e)}")
                        stats[table] = 0
                
                conn.close()
        
        except Exception as e:
            logger.error(f"获取表数据统计失败: {str(e)}")
        
        return stats
    
    def _add_init_log(self, message: str):
        """
        添加初始化日志
        
        Args:
            message: 日志消息
        """
        # 直接保存消息字符串，而不是对象
        self.init_status['logs'].append(message)
        logger.info(f"[初始化] {message}")
    
    def _add_update_log(self, message: str):
        """
        添加更新日志
        
        Args:
            message: 日志消息
        """
        # 直接保存消息字符串，而不是对象
        self.update_status['logs'].append(message)
        logger.info(f"[更新] {message}")


# 全局服务实例
_data_collection_service = None


def get_data_collection_service(data_dir: str = 'data') -> DataCollectionService:
    """
    获取数据采集服务实例（单例模式）
    
    Args:
        data_dir: 数据目录路径
    
    Returns:
        DataCollectionService: 数据采集服务实例
    """
    global _data_collection_service
    
    if _data_collection_service is None:
        _data_collection_service = DataCollectionService(data_dir)
    
    return _data_collection_service
