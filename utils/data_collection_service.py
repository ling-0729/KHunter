"""
数据采集服务模块
用于管理数据初始化和更新的业务逻辑
"""

import json
import logging
import re
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

    #: ★【2026-09-29 用户要求 ✓】"当前环节"跟踪 ✗→✓（类级默认值 ✓，未初始化亦可安全打印 ✓）
    _current_stage = ''      #: 展示用 ✓（可能是**子阶段** ✓）
    _main_stage = ''         #: **主环节** ✓（耗时/收尾以它为准 ✓）
    _stage_started_at = 0.0
    _stage_no = 0

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

    def check_data_completeness(self) -> Dict[str, Any]:
        """
        检查数据完整性
        
        Returns:
            dict: 各数据表的完整性信息
        """
        result = {
            'success': True,
            'data': {
                'basic': {'table': 'stock_basic', 'count': 0, 'complete': False},
                'kline': {'table': 'stock_kline', 'count': 0, 'complete': False}
            },
            'lastUpdate': None
        }
        
        try:
            # 检查 stock_basic 表
            r = self.db_manager.query_one("SELECT COUNT(*) as count FROM stock_basic")
            basic_count = r['count'] if r else 0
            result['data']['basic']['count'] = basic_count
            result['data']['basic']['complete'] = basic_count > 0
            
            # 检查 stock_kline 表
            r = self.db_manager.query_one("SELECT COUNT(*) as count FROM stock_kline")
            kline_count = r['count'] if r else 0
            result['data']['kline']['count'] = kline_count
            result['data']['kline']['complete'] = kline_count > 0
            
            # 获取最后更新时间
            r = self.db_manager.query_one(
                "SELECT MAX(date) as last_date FROM stock_kline"
            )
            result['lastUpdate'] = r['last_date'] if r and r.get('last_date') else None
            
            # 获取股票数量
            r = self.db_manager.query_one("SELECT COUNT(DISTINCT code) as count FROM stock_kline")
            stock_count = r['count'] if r else 0
            result['data']['kline']['stockCount'] = stock_count
            
        except Exception as e:
            result['success'] = False
            logger.error(f"检查数据完整性失败: {e}")
        
        return result
    
    def get_data_status(self) -> Dict[str, Any]:
        """
        获取数据状态摘要
        
        Returns:
            dict: 数据状态信息
        """
        completeness = self.check_data_completeness()
        
        return {
            'initialized': completeness['data']['basic']['complete'],
            'basicCount': completeness['data']['basic']['count'],
            'klineCount': completeness['data']['kline']['count'],
            'klineStockCount': completeness['data'].get('kline', {}).get('stockCount', 0),
            'lastUpdate': completeness.get('lastUpdate')
        }
    
    def start_reinit(self, stock_count: int = None, kline_days: int = None) -> Dict[str, Any]:
        """
        强制重新初始化（删除现有数据，重新初始化）
        
        Args:
            stock_count: 初始化股票数量（默认2000）
            kline_days: K线历史天数（默认250）
        
        Returns:
            dict: 任务信息
        """
        if stock_count is None:
            stock_count = 2000
        if kline_days is None:
            kline_days = 250
            
        if self.init_status['running']:
            return {
                'success': False,
                'message': '已有初始化任务正在运行'
            }
        
        task_id = f"REINIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        thread = threading.Thread(
            target=self._run_reinit,
            args=(task_id, stock_count, kline_days),
            daemon=True
        )
        thread.start()
        
        return {
            'success': True,
            'message': '重新初始化任务已启动',
            'taskId': task_id
        }
    
    def _run_reinit(self, task_id: str, stock_count: int, kline_days: int):
        """
        执行强制重新初始化（在后台线程中运行）
        
        Args:
            task_id: 任务ID
            stock_count: 股票数量（忽略，使用全量）
            kline_days: K线天数（转换为年数，3年约750天）
        """
        with self.init_lock:
            if self.init_status['running']:
                logger.warning(f"重新初始化任务 {task_id} 已在运行")
                return
            
            try:
                self.init_status['running'] = True
                self.init_status['paused'] = False
                self.init_status['status'] = 'running'
                self.init_status['progress'] = 0
                self.init_status['start_time'] = datetime.now().isoformat()
                self.init_status['logs'] = []
                self.init_status['tasks'] = []
                
                years = 3
                self._add_init_log(f"⚠ 重新初始化任务 {task_id} 已启动")
                self._add_init_log(f"  - 全量初始化，K线年数: {years}")
                
                try:
                    from web_server import emit_init_progress
                    emit_init_progress()
                except ImportError:
                    pass
                
                # 步骤1: 删除现有数据
                self._add_init_log("⟳ 正在删除现有数据...")
                self._delete_all_data()
                self._add_init_log("✓ 已删除现有数据")
                self._update_progress(10)
                
                # 步骤2: 使用统一初始化入口全量初始化（带进度回调）
                self._add_init_log("⟳ 正在全量初始化...")

                # 创建进度回调（映射到 10%-100% 区间）
                def reinit_progress_cb(progress_pct, message):
                    mapped = 10 + int(progress_pct * 0.9)  # 10 + 0~90
                    self.init_status['current_task'] = message
                    self._update_progress(mapped)

                data_initializer = DataInitializer(
                    self.db_manager,
                    self.stock_data_fetcher,
                    None,
                    None,
                    progress_callback=reinit_progress_cb
                )
                data_initializer.init_full_data(years=years)
                self._add_init_log("✓ 全量初始化完成")
                self._update_progress(100)
                
                self.init_status['status'] = 'completed'
                self.init_status['end_time'] = datetime.now().isoformat()
                self._add_init_log("✓ 重新初始化全部完成")
                
            except Exception as e:
                self.init_status['status'] = 'failed'
                self.init_status['end_time'] = datetime.now().isoformat()
                self._add_init_log(f"✗ 重新初始化失败: {str(e)}")
                logger.error(f"重新初始化失败: {e}")
    
    def _delete_all_data(self):
        """删除所有数据表内容（**危险操作** ✗ → 需**显式确认** ✓）

        【2026-09-25 加固】此前可无条件 `DELETE FROM stock_kline` ✗ ——
        该表 500 万行历史会被整体擦除后重建 ✗，且重建后**所有行的写入时间被刷新** ✓
        （实测：5,289,071 行同为 `updated_date=2026-05-06` ✗）⇒
        前复权历史可能随之改变 ✗ → 任何既有回测结果**不可复现** ✗✓。

        现要求显式确认（环境变量 `KHUNTER_ALLOW_FULL_WIPE=1` ✓）并**醒目告警** ✗；
        未确认则**拒绝执行** ✗（宁可失败，也不静默改写历史 ✗）。
        """
        import os
        n_kline = 0
        try:
            r = self.db_manager.query_one("SELECT COUNT(*) AS n FROM stock_kline")
            if isinstance(r, dict):
                n_kline = int(r.get('n') or 0)
            elif r:
                n_kline = int(r[0] or 0)
        except Exception:
            n_kline = 0
        allow = str(os.environ.get('KHUNTER_ALLOW_FULL_WIPE', '')).strip().lower() in ('1', 'true', 'yes')
        if n_kline and not allow:
            msg = (f"拒绝清空 stock_kline（现有 {n_kline} 行）✗：全量擦除+重建会刷新所有行的写入时间 ✗，"
                   f"前复权历史可能改变 ✗ ⇒ 既有回测结果将不可复现 ✗。若确需重来，请设置环境变量 "
                   f"KHUNTER_ALLOW_FULL_WIPE=1 后重试 ✓（并建议先备份 data 目录 ✓）")
            logger.error(msg)
            raise RuntimeError(msg)
        if n_kline:
            logger.warning(f"⚠ **全量清空** stock_kline（{n_kline} 行）+ stock_basic ✗ —— "
                           f"已由 KHUNTER_ALLOW_FULL_WIPE=1 显式确认 ✓；"
                           f"此后既有回测结果将不可复现 ✗（请记录该时点 ✓）")
        try:
            self.db_manager.execute("DELETE FROM stock_kline")
            self.db_manager.execute("DELETE FROM stock_basic")
            logger.info("已清空 stock_kline 和 stock_basic 表")
            # 【2026-09-27 §5.3 覆盖矩阵】擦除后的 ADX 处置 ✓：
            #   ① 擦除后 `stock_kline` 已空 ⇒ **无行可算** ✓（此处不必重算 ✓）；
            #   ② ⚠️ 但**必须清 ADX 进程内缓存** ✗✓ —— 键是**股票代码** ✓，不随擦除失效 ✗
            #      ⇒ 长驻进程（web_server ✓）会继续拿**已删数据的旧 `adx`** ✓✗ 判买卖 ✗；
            #   ③ 重建完成后**必须**补算 ✓ ⇒ 已有自动挂钩 ✓（`KlineInitializer` ✓ / 日更第 5.5 步 ✓）；
            #      若走**其他**重建路径 ✗ ⇒ 需手动 `utils/stock_adx.py::backfill_all` ✓（此处显式提示 ✗）。
            try:
                from utils.stock_adx import clear_adx_cache
                clear_adx_cache()
            except Exception:
                pass
            logger.warning("⚠ stock_kline 已清空 ✗ ⇒ 重建完成后**必须**补算 ADX ✓："
                           "走 `KlineInitializer` ✓（已自动补算 ✓）或日更第 5.5 步 ✓；"
                           "其他重建路径请手动跑 `utils/stock_adx.py::backfill_all` ✓")
        except Exception as e:
            logger.error(f"删除数据失败: {e}")
            raise
    
    def _update_progress(self, progress: int):
        """更新进度"""
        self.init_status['progress'] = progress
        try:
            from web_server import emit_init_progress
            emit_init_progress()
        except ImportError:
            pass
    
    def _add_init_log(self, message: str):
        """添加初始化日志"""
        log_entry = f"{datetime.now().strftime('%H:%M:%S')} - {message}"
        self.init_status['logs'].append(log_entry)
        logger.info(message)
    
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
        # 【2026-09-25 修正 ✗→✓】原逻辑"只要已初始化就**一律拒绝**"✗ —— 会挡住**新增的数据维度** ✗✓：
        #   老用户的基础/K线早已就绪 ✓，但"交易日历 / 个股资金流 / 基本面 / 公告"可能尚未初始化 ✗，
        #   此时点"开始初始化"会被直接弹回 ✗，新维度**永远点不动** ✗。
        #   现改为：勾选了**本地数据维度**时放行 ✓（各采集器均为**覆盖驱动 + 幂等** ✓，重复跑安全 ✓）
        # ★【2026-10-07 ✓】`indexAdxData` 也在此列 ✓ —— 否则"已初始化"的老用户
        #   点它会被"初始化已经完成"直接挡回 ✗（= 2026-09-25 修过的那个坑 ✗✓ 复发）
        _localized_keys = ('calendarData', 'fundFlowData', 'fundamentalData',
                           'announcementData', 'indexAdxData')
        _wants_localized = any((options or {}).get(k) for k in _localized_keys)
        if self._check_data_initialized():
            if not _wants_localized:
                return {
                    'success': False,
                    'message': '初始化已经完成，无需再次初始化',
                    'taskId': None
                }
            logger.info('基础/K线数据已存在 ✓ → 本次仅初始化所选的数据维度 ✓')
        
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
                
                # 初始化数据（统一入口，带进度回调）
                if init_type == 'custom' or init_type == 'full':
                    # 使用统一初始化入口
                    self.init_status['current_task'] = '初始化基础数据和K线'
                    self._add_init_log("⟳ 正在初始化数据...")

                    try:
                        from web_server import emit_init_progress
                        emit_init_progress()
                    except ImportError:
                        pass

                    # 获取股票列表
                    stock_dict = self.akshare_fetcher.get_all_stock_codes()

                    # 创建进度回调（映射到 0%-100%）
                    def init_progress_cb(progress_pct, message):
                        self.init_status['current_task'] = message
                        self._update_progress(progress_pct)

                    # 使用 DataInitializer 统一入口
                    data_initializer = DataInitializer(
                        self.db_manager,
                        self.stock_data_fetcher,
                        None,
                        None,
                        progress_callback=init_progress_cb
                    )
                    data_initializer.init_full_data(years=3, stock_dict=stock_dict)

                    self.init_status['progress'] = 100
                    self._add_init_log("✓ 数据初始化完成")

                    try:
                        from web_server import emit_init_progress
                        emit_init_progress()
                    except ImportError:
                        pass
                
                # 【2026-09-25 新增】**四类本地数据维度** ✓（与初始化页面选项一一对应 ✓）
                if init_type in ('custom', 'full'):
                    self._init_localized_domains(options or {})

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
    
    def _init_localized_domains(self, options: Dict) -> Dict:
        """按**数据维度**初始化四类本地数据 ✓（2026-09-25 新增，幂等 ✓）

        与初始化页面选项**一一对应** ✓：
          · `calendarData`     → 交易日历（`trade_calendar` ✓，离线 ✓）
          · `fundFlowData`     → 个股资金流（`stock_moneyflow_daily` ✓，**按配置数据源** ✓，
                                 默认同花顺 `moneyflow_ths` ✓ = 保真口径 ✓；见 §4.9 ✓）
          · `fundamentalData`  → 个股基本面（`stock_finance_indicator` ✓，逐股 ✓）
          · `announcementData` → 个股公告（`stock_announcement` ✓，按交易日 ✓）
          · ★ `indexAdxData`   → **大盘指数 ADX**（`market_index_adx` ✓，主指数 + 双创 ✓）
            —— ★【2026-10-07 新增 ✓】此前**没有入口** ✗ ⇒ 用户点了"全部"仍缺该表 ✗
               ⇒ 回测被数据闸门拦 ✗（还要**手工**跑 `backfill_index_adx.py` ✗✓）。

        设计 ✓：全部走"**覆盖驱动 + 只补缺口**"的实现 ✓（可重复执行 ✓）；
        单维度失败**不影响**其它维度 ✓，但会 `_add_init_log` **如实记录** ✗（不静默 ✓）。
        行业/板块资金流**不在**此处 ✓（暂不处理 ✓，页面已置灰 ✓）。
        """
        want = {
            'calendar': bool((options or {}).get('calendarData')),
            'moneyflow': bool((options or {}).get('fundFlowData')),
            'fundamental': bool((options or {}).get('fundamentalData')),
            'announcement': bool((options or {}).get('announcementData')),
            'index_adx': bool((options or {}).get('indexAdxData')),
        }
        result = {'done': {}, 'failed': {}}
        if not any(want.values()):
            self._add_init_log("ℹ 未选择任何本地数据维度 → 跳过 ✓")
            return result

        def _emit():
            try:
                from web_server import emit_init_progress
                emit_init_progress()
            except Exception:
                pass

        try:
            from utils.data_collectors.cninfo_fetcher import CninfoAnnouncementFetcher
            from utils.data_collectors.local_data_collectors import (SOURCE_START,
                                                                     CalendarCollector,
                                                                     EventCollector,
                                                                     FundamentalCollector)
            # ★【2026-10-07 ✓】"数据源无权限 ⇒ 跳过而不中断"的**统一判据** ✗→✓
            from utils.online_guard import is_permission_error
            from utils.global_db import get_global_db
            from utils.local_calendar import load_local_trade_dates
            # 【2026-09-26 ✓】资金流**不再直连某个采集器** ✗（此前硬编码东财 ✗✓）——
            #   改由 `moneyflow_source.make_collector()` 按**配置数据源**产出 ✓
            from utils.moneyflow_source import clip_dates_to_source, make_collector, resolve
        except Exception as e:
            msg = f'本地数据采集模块导入失败 ✗: {e}'
            self._add_init_log(f"✗ {msg}")
            logger.error(msg)
            result['failed']['import'] = msg
            return result

        conn = get_global_db().connect()
        state_dir = 'data/logs/collector_state'
        today = datetime.now().strftime('%Y-%m-%d')
        try:
            dates = [d for d in load_local_trade_dates(conn, prefer_db=False) if d <= today]
        except Exception as e:
            self._add_init_log(f"✗ 本地交易日历不可用 ✗: {e}")
            result['failed']['calendar_dates'] = str(e)
            return result

        def _calendar():
            return CalendarCollector(conn, state_dir=state_dir).sync_from_local_cache()

        def _moneyflow():
            """资金流初始化 ✓：**按配置数据源** ✓ + **裁剪到该源起点** ✓

            修正的漏洞 ✗✓（2026-09-26 实测）：此前**硬编码东财采集器** ✗ ⇒
            ① 与"每日更新/评分"的源（同花顺 ✓）**不一致** ✗；
            ② 会把已按用户要求**彻底清除**的东财数据**重新拉回来** ✗✓；
            ③ 且区间取"本地日历全量（自 2023-09-11 ✗）"⇒ 对同花顺越界 ✗（会直接报错 ✗）。
            现：工厂产出 ✓ + 区间裁剪 ✓ + 裁掉的天数**如实上报** ✗。
            """
            src = resolve()
            if not dates:
                return {'skipped': True, 'reason': '无可用交易日'}
            use, dropped, start = clip_dates_to_source(dates, src)
            if dropped:
                self._add_init_log(
                    f"ℹ 资金流初始化区间已裁剪 ✓：数据源 {src} 可用起点 {start} ✓，"
                    f"更早的 {dropped} 个交易日**不受支持** ✗（回测起点亦须 ≥ 该源可评分起点 ✓）")
            if not use:
                return {'skipped': True,
                        'reason': f'{src} 无可用区间（起点 {start}）'}
            c = make_collector(conn, src, state_dir=state_dir,
                               max_retries=1, retry_wait=1.0)
            c.ensure_schema()
            return c.run_initial(use[0], use[-1], use, strict=False)

        def _fundamental():
            codes = [r[0] for r in conn.execute('SELECT DISTINCT code FROM stock_kline ORDER BY code')]
            if not codes:
                return {'skipped': True, 'reason': 'stock_kline 无股票（请先初始化历史行情 ✓）'}
            c = FundamentalCollector(conn, state_dir=state_dir, max_retries=1, retry_wait=1.0)
            c.ensure_schema()
            # ★★★★【2026-10-07 用户要求 ✓】**先试一只 ⇒ 无权限就整维度跳过** ✗→✓ ★★★★
            #   用户原话 ✓："没有对应数据源权限时，**自动跳过，避免中断**" ✓
            #   ⚠️ 为什么必须"先试"✗✓：财务指标是**逐股**调用（全市场 ≈ 5000 次 ✓）——
            #     无权限时**每次都失败** ✗ ⇒ ① 白跑几十分钟 ✗ ② 日志刷 ~5000 条失败 ✗
            #     ③ 结果被记成"失败"✗（其实是"没买这个接口"✓）⇒ 用户以为系统坏了 ✗✓。
            #   ⇒ 探一只（`000001` ✓）：
            #     · **权限错** ⇒ 直接跳过该维度 ✓（**不算失败** ✓、**不中断** ✓）；
            #     · **其它错**（网络抖动等 ✓）⇒ 不在这里下结论 ✓，交给 `run_stocks` 逐股重试 ✓
            #       （它 `strict=False` ✓ ⇒ 单股失败不会抛 ✓）。
            try:
                c.fetch_stock('000001', SOURCE_START,
                              datetime.now().strftime('%Y-%m-%d'))
            except Exception as e:
                if is_permission_error(e):
                    return {'skipped': True,
                            'reason': '数据源无权限 ✓（Tushare fina_indicator ✗）'
                                      ' ⇒ 整维度跳过，不中断其它维度 ✓'}
            return c.run_stocks(codes, batch_sleep=0.0)

        def _announcement():
            if not dates:
                return {'skipped': True, 'reason': '无可用交易日'}
            c = EventCollector(conn, fetcher=CninfoAnnouncementFetcher(), state_dir=state_dir,
                               max_retries=1, retry_wait=2.0)
            c.ensure_schema()
            return c.run(dates, resume=True)

        def _index_adx():
            """★★【2026-10-07 新增 ✓】**大盘指数 ADX**（主指数 + 双创 ✓）★★

            用户口径 ✓："初始化会初始化**完整数据**" ✓ ⇒ 这一项必须进页面 ✓：
              否则新用户点了"一键全量"✓ 之后 `market_index_adx` **仍是空表** ✗
              ⇒ 回测被数据闸门拦下 ✗，而提示偏偏又叫他"先运行数据更新/初始化"✗
              —— 明明已经点过了 ✓（本轮审计发现的**体验断点** ✗✓）。

            ⚠️ 复用**同一实现** ✗✓：直接调 `backfill_index_adx.backfill_one()` ✓
              （**绝不另写一套取数逻辑** ✗ —— 否则"脚本口径"与"页面口径"会漂移 ✗）；
              其自带**只增不改 + 交叉验证 + 健全性校验** ✓（见该脚本文档 ✓）。
            ⚠️ 联网**必须过闸** ✗✓：`guard_online_call(purpose='update')` ✓
              —— 离线/回测语境下本维度会**如实失败** ✓（不静默联网 ✗，与其它维度同规矩 ✓）。
            ⚠️ 区间取 `20200101 ~ 今天` ✓（与手册 §3.1 那条命令**同口径** ✓；
              科创50 发布于 2019-12-31 ⇒ 其预热不足的前几行 `adx` 为 NULL ✓ **是对的** ✓）。
            """
            from utils.online_guard import PURPOSE_UPDATE, guard_online_call
            guard_online_call('大盘指数 ADX 回填（数据更新 ✓）', purpose=PURPOSE_UPDATE)
            # ⚠️ 注意 ✓：离线闸门抛的是"**离线模式禁止在线调用**"✗ ⇒ 它**不是**权限错 ✓
            #   （`is_permission_error` 不会误判它 ✓ ⇒ 离线语境仍**如实失败** ✗ 不回退成"跳过"✓）
            from backfill_index_adx import backfill_one
            from trading.index_adx_filter import (BOARD_CHINEXT, BOARD_STAR,
                                                  resolve_board_index_code,
                                                  resolve_index_adx_code)
            from trading.market_index_adx_dao import MarketIndexADXDAO
            codes = []
            for _c in (resolve_index_adx_code(),
                       resolve_board_index_code(BOARD_STAR),
                       resolve_board_index_code(BOARD_CHINEXT)):
                _c = str(_c or '').strip()
                if _c and _c not in codes:
                    codes.append(_c)
            if not codes:
                return {'skipped': True, 'reason': '未解析到任何指数代码 ✗'}
            from utils.online_guard import is_permission_error   # ★ 无权限 ⇒ 跳过 ✓
            dao = MarketIndexADXDAO()
            start, end = '20200101', datetime.now().strftime('%Y%m%d')
            rows = {}
            for _c in codes:               # 逐指数 ✓：单个失败**不拖垮**其它 ✓（但如实记录 ✗）
                try:
                    rows[_c] = backfill_one(_c, start, end, dao)
                except Exception as e:
                    # ★★【2026-10-07 用户要求 ✓】**无权限 ⇒ 跳过 ✓，不算失败、不中断** ✗✓ ★★
                    #   用户原话 ✓："没有对应数据源权限时，自动跳过，避免中断" ✓
                    #   （指数接口可能未开通 ✓ ⇒ 该指数跳过 ✓，其余指数与其余维度照跑 ✓）
                    if is_permission_error(e):
                        rows[_c] = 'skipped：数据源无权限 ✓'
                        self._add_init_log(
                            f'⏭ [{_c}] 跳过 ✓：**数据源无权限** ✗（不中断 ✓；'
                            f'其余指数/维度照常 ✓）')
                        logger.warning(f'指数 ADX 回填跳过（无权限 ✗）{_c}: {e}')
                    else:
                        rows[_c] = f'失败 ✗: {str(e)[:120]}'
                        logger.error(f'指数 ADX 回填失败 {_c} ✗: {e}', exc_info=True)
            return {'start': start, 'end': end, 'rows': rows}

        steps = (
            ('calendar', '交易日历', _calendar),
            ('moneyflow', '个股资金流向', _moneyflow),
            ('fundamental', '个股基本面', _fundamental),
            ('announcement', '个股公告事件', _announcement),
            ('index_adx', '大盘指数 ADX', _index_adx),
        )
        total = sum(1 for k, _, _ in steps if want[k]) or 1
        idx = 0
        for key, label, fn in steps:
            if not want[key]:
                self._add_init_log(f"ℹ 未选择[{label}] → 跳过 ✓")
                continue
            idx += 1
            self.init_status['current_task'] = f'初始化{label}...'
            self._add_init_log(f"⟳ [{label}] 开始初始化（第 {idx}/{total} 项 ✓）...")
            _emit()
            try:
                stats = fn() or {}
                if stats.get('skipped'):
                    # ★【2026-10-07 ✓】**"跳过"不是"失败"** ✗→✓（用户要求：无权限别中断 ✓）
                    #   ⚠️ 但仍要**留痕** ✗（`result['skipped']` ✓ + 日志 ✓ + `failed` **不计数**）
                    result.setdefault('skipped', {})[key] = stats.get('reason') or 'skipped'
                    self._add_init_log(
                        f"⏭ [{label}] 跳过 ✓: {stats.get('reason') or '未说明'}（不计失败 ✓）")
                else:
                    result['done'][key] = stats
                    self._add_init_log(f"✓ [{label}] 完成: {stats}")
            except Exception as e:              # 单维度失败不影响其它 ✓（但如实记录 ✗）
                if is_permission_error(e):
                    # ★★【2026-10-07 用户要求 ✓】**无权限 ⇒ 跳过 ✓，不中断 ✓** ★★
                    result.setdefault('skipped', {})[key] = f'数据源无权限 ✓: {str(e)[:150]}'
                    self._add_init_log(
                        f"⏭ [{label}] 跳过 ✓：**数据源无权限** ✗（不中断其它维度 ✓）: "
                        f"{str(e)[:150]}")
                    logger.warning(f'初始化[{label}] 跳过（数据源无权限 ✗）: {e}')
                else:
                    result['failed'][key] = str(e)[:200]
                    self.init_status['failed'] += 1
                    self._add_init_log(f"✗ [{label}] 失败 ✗: {str(e)[:200]}")
                    logger.error(f'初始化[{label}]失败 ✗: {e}', exc_info=True)
            self._update_progress(int(10 + 85 * idx / total))
            _emit()

        self.init_status['statistics'] = self.get_tables_stats()
        return result

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
    
    # 手动"重新更新"（force=True）时，若上次更新已是最新，则回退到最近 N 个自然日重新拉取
    FORCE_LOOKBACK_DAYS = 7

    @classmethod
    def _resolve_window(cls, last_update_date: Optional[str], target_date: str,
                        force: bool = False) -> Optional[str]:
        """计算本次更新实际使用的起始日期（窗口起点）

        手动重新更新（force=True，前端"更新数据"按钮）时**不考虑当天是否更新过**：
          - 窗口为空（`last_update_date >= target_date` 或缺失）→ 回退到
            `target_date - FORCE_LOOKBACK_DAYS`（默认 7 个自然日 ≈ 5 个交易日），
            保证确实重新拉取（K线写入是 `INSERT OR REPLACE`，重跑幂等 ✓）；
          - 窗口本来更宽（`last_update_date < target_date`）→ 原样沿用，不缩小 ✓。

        Args:
            last_update_date: 上次更新完成日期（YYYY-MM-DD，可能为 None）
            target_date: 目标更新日期（YYYY-MM-DD）
            force: 是否手动强制重新更新

        Returns:
            起始日期（YYYY-MM-DD）
        """
        if not force:
            return last_update_date
        if last_update_date and last_update_date < target_date:
            return last_update_date
        try:
            end = datetime.strptime(str(target_date)[:10], '%Y-%m-%d')
        except (ValueError, TypeError):
            end = datetime.now()
        return (end - timedelta(days=cls.FORCE_LOOKBACK_DAYS)).strftime('%Y-%m-%d')

    def start_update(self, update_types: Optional[List[str]] = None,
                     force: bool = False) -> Dict[str, Any]:
        """
        开始数据更新
        
        Args:
            update_types: 更新类型列表
            force: True = 手动重新更新（不考虑当天是否已更新过，重新拉取最近数据）
        
        Returns:
            dict: 更新任务信息
        """
        # 检查是否已有更新任务运行
        if self.update_status['running']:
            # 记录到日志：此前该分支静默返回，导致"点了没反应"难以排查
            logger.warning(
                f"数据更新请求被拒绝：已有更新任务正在运行"
                f"（force={force}，前端会收到'已有更新任务正在运行'）")
            self._add_update_log("⚠ 数据更新请求被拒绝：已有更新任务正在运行")
            return {
                'success': False,
                'message': '已有更新任务正在运行',
                'taskId': None
            }

        # 记录本次是否为"手动重新更新"（用于日志自证：有这行 = 新代码 + force 生效）
        if force:
            logger.info("收到手动重新更新请求（force=True）：将忽略'已是最新'的幂等跳过")
        
        # 生成任务ID
        task_id = f"UPDATE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 在后台线程中执行更新
        thread = threading.Thread(
            target=self._run_update,
            args=(task_id, update_types, force),
            daemon=True
        )
        thread.start()
        
        return {
            'success': True,
            'message': '更新任务已启动',
            'taskId': task_id
        }
    
    def _run_update(self, task_id: str, update_types: Optional[List[str]],
                    force: bool = False):
        """
        执行更新任务（在后台线程中运行）
        
        流程（**日志以 `【第X步】` 文案为准** ✓）:
        1.  检查交易时间和更新条件（得到 target_date）
        2.  查询上次更新日期（前置）并幂等判断：**已最新 ⇒ 跳过全部** ✗
        3.  检测并初始化新股票
        4.  获取所有股票列表
        5.  更新 **K线**（内部含：拉取 ✓ → **除权检测重建** ✓ → **个股 ADX 补算** ✓）
        5.5 个股 ADX **自愈**（缺口超阈值 ⇒ 全量重算 ✓）
        6.  更新 **资金流向**（`FundFlowUpdater` ✓；勾选项 `fund_flow` ✓）
        7.  更新股票市值信息
        8.  刷新减持计划缓存
        8.5 **四类本地数据**（资金流 / 基本面 / 事件 / 日历 ✓；勾选项 `local_data` ✓）
        9.  记录更新完成
        10. 计算并保存 **市场温度**
        11. 计算并保存 **风控状态**
        12. 计算并保存 **全A指数 ADX**（与温度同批次产出 ✓）

        ⚠️ **勾选项门控** ✗✓（`update_types` ✓）：`kline` ✓ / `fund_flow` ✓ / `local_data` ✓
          —— **未勾选 ⇒ 该步直接跳过** ✗（日志里也不会出现 ✗）
          ⇒ 遇到"**看不到某步骤**"✗ 先查这里 ✓，再看日志是否**还没跑到** ✓。
        ⚠️【2026-09-28 修 ✓】**文案编号曾与注释错位** ✗：温度/风控/指数ADX 的日志文案
          原写成 `【第9/10/11步】`✗，与前面"**第9步 记录更新完成**"**重号** ✗
          （实测用户因此以为"没有温度步骤"✗✓）⇒ 现统一为 `【第10/11/12步】` ✓
          （**注释、文案、本清单三处一致** ✓）。
        
        Args:
            task_id: 任务ID
            update_types: 更新类型列表（可选）
        """
        target_date = None
        validator = None
        # ★【2026-09-29 用户要求 ✓】总耗时计时 + 环节跟踪复位 ✓（收尾汇总用 ✓）
        _t0 = time.monotonic()
        self._reset_stage_tracking()
        
        try:
            # 初始化状态
            with self.update_lock:
                self.update_status['running'] = True
                self.update_status['paused'] = False
                self.update_status['status'] = 'running'
                self.update_status['skipped'] = False
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
                    'market_cap_failed': 0,
                    'reduce_plan_refreshed': 0,
                    'reduce_plan_failed': 0
                }
            
            # ★【2026-09-29 用户要求 ✓】开局说清"本次要做什么 + 怎么读进度" ✗→✓
            self._add_update_log(
                f"✓ 更新任务 {task_id} 已启动（更新类型={update_types or '全部'} ✓ "
                f"force={force} ✓ 共 {self._TOTAL_STAGES} 步 ✓）—— "
                f"每进入一步都会打一行 `▶ 当前环节（第 N 个）` ✓，"
                f"结束时会打 `⏱ 环节耗时` 与收尾汇总 ✓（出问题据此定位环节 ✓）")
            
            # 【第1步】检查交易时间和更新条件
            self._add_update_log("【第1步】检查交易时间和更新条件...")
            validator = TradingTimeValidator()
            is_valid, error_msg, target_date = validator.validate_update_time()
            
            if not is_valid:
                # 交易时间验证失败
                with self.update_lock:
                    self.update_status['status'] = 'failed'
                    self.update_status['message'] = error_msg
                
                self._add_update_log(f"✗ 错误: {error_msg}")
                logger.warning(f"更新任务 {task_id} 被拒绝: {error_msg}")
                # ★【2026-09-29】被拒绝也要有收尾行 ✓（含环节与耗时 ✓，便于判断"是否真的跑过"✓）
                self._log_update_finish(task_id, _t0, '失败（时间校验未通过）', error_msg)
                return
            
            # 记录目标更新日期
            self._add_update_log(f"✓ 目标更新日期: {target_date}")
            
            # 记录更新开始（已弃用空操作，保留以兼容流程日志）
            validator.record_update_start(target_date)
            
            # 【第2步】查询上次更新日期（前置，用于幂等判断）
            self._add_update_log("【第2步】查询上次更新日期...")
            try:
                last_update_date = validator.get_last_update_date()
                
                # 如果没有记录，使用默认日期（3天前），视为需要更新
                if not last_update_date:
                    last_update_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
                
                self._add_update_log(f"✓ 上次更新日期: {last_update_date}")
            
            except Exception as e:
                self._add_update_log(f"✗ 查询上次更新日期失败: {str(e)}")
                logger.error(f"查询上次更新日期失败: {str(e)}")
                last_update_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
            
            # 【手动重新更新】force=True（前端"更新数据"按钮）→ 不考虑当天是否更新过：
            #   窗口为空时回退到最近 FORCE_LOOKBACK_DAYS 个自然日，保证确实重新拉取；
            #   K线写入为 INSERT OR REPLACE（幂等），重跑不会产生重复/脏数据
            if force:
                _eff = self._resolve_window(last_update_date, target_date, force=True)
                if _eff != last_update_date:
                    self._add_update_log(
                        f"⚠ 手动重新更新：忽略'数据已是最新'状态，"
                        f"窗口回退为 {_eff} ~ {target_date}")
                    logger.info(f"手动重新更新：窗口 {last_update_date} → {_eff}（target={target_date}）")
                else:
                    self._add_update_log(
                        f"⚠ 手动重新更新：忽略幂等跳过（窗口 {last_update_date} ~ {target_date}）")
                last_update_date = _eff

            # 【幂等保护】数据已是最新则跳过全部更新步骤，直接进入后续流程（策略运行）
            # 判断依据：上次更新完成日期(last_update_date) >= 目标更新日期(target_date)
            #   force=True（手动重新更新）时**不跳过**
            if (not force) and last_update_date and last_update_date >= target_date:
                # 记录跳过原因，便于运维在日志中确认幂等生效
                self._add_update_log(
                    f"ℹ 数据已是最新（上次更新日期 {last_update_date} >= 目标更新日期 {target_date}），"
                    f"跳过全部更新步骤（新股票/股票列表/K线/资金流向/市值/减持缓存/市场温度/风控），直接结束更新任务"
                )
                logger.info(
                    f"数据已是最新（{last_update_date} >= {target_date}），幂等跳过全部更新步骤，"
                    f"流水线将直接进入策略运行"
                )
                # 闭合更新状态：标记为完成且成功，确保上层 PipelineOrchestrator 判定为 success 并继续执行策略
                with self.update_lock:
                    self.update_status['status'] = 'completed'   # 任务整体完成
                    self.update_status['success'] = 1            # 标记为成功，避免上层误判为失败
                    self.update_status['skipped'] = False        # 非 skipped，确保进入策略运行
                    self.update_status['already_latest'] = True  # 标记数据已最新（供前端/通知展示）
                    self.update_status['end_time'] = datetime.now().isoformat()
                    self.update_status['message'] = f'数据已是最新（{last_update_date}），跳过全部更新步骤'
                # 幂等写入完成记录（覆盖同一 target_date 的 update_log，状态保持 completed，不影响下次幂等判断）
                try:
                    validator.record_update_complete(target_date, {})
                except Exception as e:
                    logger.warning(f"记录幂等跳过完成异常（可忽略）: {str(e)}")
                # ★【2026-09-29】幂等跳过也给收尾行 ✓（明确"什么都没做"✓ + 耗时 ✓）
                self._log_update_finish(task_id, _t0, '完成（幂等跳过：数据已是最新）')
                return
            
            # 【第3步】检测并初始化新股票（优先级最高）
            self._add_update_log("【第3步】检测并初始化新股票...")
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
                # 【2026-09-24】若本次任务稍后**仍会做全量 K 线更新**（【第5步】✓，判据与其一致 ✓），
                #   则新股票初始化**不再单独拉 K 线** ✓ → 由【第5步】统一拉取：
                #     · 避免新股票被更新两遍 ✗
                #     · 避免"检测除权并重建历史数据"重复执行 ✗（此前日志里出现两次 ✓）
                _will_update_kline = (not update_types) or ('kline' in update_types)
                new_stock_result = detector.detect_and_init_new_stocks(
                    years=3, days=30, skip_kline=_will_update_kline)
                
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
            
            # 【第4步】获取所有股票列表
            self._add_update_log("【第4步】获取所有股票列表...")
            try:
                sql = "SELECT DISTINCT code FROM stock_basic ORDER BY code"
                result = self.db_manager.query(sql)
                stock_codes = [row['code'] for row in result] if result else []
                
                self._add_update_log(f"✓ 获取股票列表完成: {len(stock_codes)} 只股票")
            
            except Exception as e:
                self._add_update_log(f"✗ 获取股票列表失败: {str(e)}")
                logger.error(f"获取股票列表失败: {str(e)}")
                stock_codes = []
            
            # 【第5步】更新K线数据
            if not update_types or 'kline' in update_types:
                self._add_update_log("【第5步】更新K线数据...")
                try:
                    # 创建 KlineUpdater 实例
                    stock_data_fetcher = StockDataFetcher()
                    kline_updater = KlineUpdater(self.db_manager, stock_data_fetcher)
                    
                    # 执行K线数据更新（TickFlow 批量接口，一次请求全批次）
                    kline_result = kline_updater.update_kline_data(
                        stock_codes=stock_codes,
                        last_update_date=last_update_date,
                        target_date=target_date,
                        batch_size=100  # TickFlow API每批最大100只股票
                    )
                    
                    # 更新统计信息
                    with self.update_lock:
                        self.update_status['totalStats']['kline_added'] = kline_result.get('added', 0)
                        self.update_status['totalStats']['kline_updated'] = kline_result.get('updated', 0)

                    # ★★【2026-09-29 用户反馈 ✓】**K 线结果行必须紧跟 K 线** ✗→✓ ★★
                    #   实测 ✗✓：原先"记录结果"整块排在【第5.5步】**之后** ✗ ⇒ 日志顺序错乱：
                    #     `▶ 第5.5步 自愈检查` → `· 第5.5步：自愈检查` → **`✓ K线数据更新完成`** ✗✓
                    #     —— 用户据此判定"**环节没有顺序**"✗（完全成立 ✓）。
                    #   现前移到 K 线**刚结束**处 ✓ ⇒ 顺序 = 真实执行顺序 ✓。
                    if kline_result['success']:
                        self._add_update_log(f"✓ K线数据更新完成: 新增 {kline_result['added']} 条，更新 {kline_result['updated']} 条，失败 {kline_result['failed']} 条，耗时 {kline_result['total_time']:.1f}秒")

                        # 如果数据源尚未就绪，直接退出整个更新流程
                        if '数据源尚未就绪' in kline_result.get('message', ''):
                            self._add_update_log(f"⚠ 数据源尚未就绪，跳过本次更新（不执行资金流向更新）")
                            logger.info(f"数据源尚未就绪，跳过本次更新")
                            # 标记更新完成（虽然被跳过，但仍是一个合法的完成状态）
                            # 否则前端会因 status='running' 而一直显示"更新中"
                            self.update_status['status'] = 'completed'
                            self.update_status['skipped'] = True
                            self.update_status['end_time'] = datetime.now().isoformat()
                            self.update_status['message'] = '数据源尚未就绪，已跳过本次更新'
                            return
                    else:
                        # ★【2026-09-29 如实化 ✓】K 线失败时**此前一声不响** ✗ ⇒ 补一行 ✗→✓
                        self._add_update_log(
                            f"✗ K线数据更新未成功: {kline_result.get('message', '未知原因')}")
                        logger.warning(f"K线数据更新未成功: {kline_result.get('message')}")

                    # ---------- 【第5.5步】重算个股 ADX ✓（§5.5 ✓，**位置关键** ✗）----------
                    #   ⚠️ 注释**更正** ✗→✓（2026-09-27 实测 ✓）：`KlineUpdater` 实为 **UPSERT** ✓
                    #      （`kline_upsert_sql()` ✓「只更新行情列、保留派生列」✓，2026-09-25 起 ✓）
                    #      ⇒ 日增量路径上 `adx` **一般不会被清空** ✓；但**仍需本步** ✓：
                    #      ① **OHLC 被更正**时**必须**重算 ✓（A4「价格变了就必须重算」✓）；
                    #      ② SQLite < 3.24 会退回 `INSERT OR REPLACE` ✗ ⇒ 未列出列（含 `adx`）被清 ✗。
                    #   开关 ✓：`update.stock_adx.enabled`（默认 true ✓；由 `update_recent_days` 自判 ✓）
                    #   失败处理 ✗：只告警**不阻断** K 线更新 ✓（K 线是主数据 ✓，ADX 是派生 ✓）
                    #              + **逐条落盘** `data_fetch_failure` ✓（§5.5 要求 ✓，2026-09-27 补 ✓）
                    #              + **§5.4 自愈** ✓（真缺口 > 5% ⇒ 自动全量重算 ✓，AC10 ✓）
                    try:
                        from utils.stock_adx import (clear_adx_cache, record_failures,
                                                     run_selfheal, update_recent_days)
                        _adx_conn = self.db_manager.connect()
                        # ★【2026-09-28 可观测性 ✓】**开始也要留痕** ✗→✓
                        #   实测踩到 ✗（用户 2026-09-28 ✓）：本步要跑"全市场 × 近 5 日" ✓，
                        #     且**只在结束时**打一行 ✓ ⇒ 中间几分钟**日志完全空白** ✗
                        #     ⇒ 前方刚打完"K线数据更新完成"✗ ⇒ 极易被误判为**卡死/停滞** ✗✓。
                        self._add_update_log(
                            "· 第5.5步：个股 ADX 增量重算开始（全市场 × 近 5 日 ✓；"
                            "每只从**全历史递推** ✓ ⇒ 分钟级；"
                            "**进度每 500 只一行** ✓（含百分比/耗时/剩余时间 ✓），无需看 CPU ✓）")
                        _adx = update_recent_days(_adx_conn, 5)
                        if _adx.get('skipped'):
                            self._add_update_log(f"· 个股ADX重算已跳过（{_adx.get('note', '')}）")
                        else:
                            logger.info(f"【第5.5步】个股ADX重算 ✓ {_adx['updated_rows']} 行 / "
                                        f"{_adx['codes']} 只（失败 {len(_adx['failed'])} 只 ✗；"
                                        f"耗时 {_adx.get('elapsed', 0):.1f}s ✓）")
                            self._add_update_log(
                                f"✓ 个股ADX重算完成: {_adx['updated_rows']} 行 / {_adx['codes']} 只 ✓"
                                f"（失败 {len(_adx['failed'])} 只 ✗；"
                                f"耗时 {_adx.get('elapsed', 0):.1f}s ✓）")
                            if _adx.get('failed'):
                                record_failures(_adx_conn, _adx['failed'])   # 逐条落盘 ✓（§5.5 ✓）
                        # ★ 日更后**必须清 ADX 缓存** ✗✓ —— 键是股票代码 ✓，不随重算失效 ✗
                        #   ⇒ 长驻进程（web_server ✓）否则会**一直用旧值** ✓✗ 判买卖 ✗
                        clear_adx_cache()
                        # 【§5.4 自愈 ✓】真缺口 > 5% ⇒ 自动全量重算 ✓
                        #   （实测生产库真缺口为 **0** ✓ ⇒ 平时**永不触发** ✓，不会拖慢日更 ✓）
                        # ★【2026-09-28 可观测性 ✓】**全量重算默认**不打进度** ✗✓**
                        #   （`backfill_all` 的 `chunk_size=0` ✓）⇒ 触发时会是**长静默** ✗
                        #   ⇒ 这里显式传 `chunk_size=200` ✓（**每 200 只一行 ✓**），
                        #     并先打一行"开始"✓ ⇒ 用户一眼能看出"在跑 + 跑到哪" ✓✓。
                        self._add_update_log(
                            "· 第5.5步：§5.4 自愈检查（若真缺口 > 5% ⇒ 全量重算 ✓；"
                            "重算为分钟级 ✗，进度每 200 只一行 ✓）")
                        _heal = run_selfheal(_adx_conn, days=5, threshold=0.05,
                                             chunk_size=200)
                        if _heal.get('healed'):
                            self._add_update_log(
                                f"⚠ 检测到 ADX 缺口（{_heal['missing_ratio']:.2%}）⇒ 已自动全量重算 ✓")
                            logger.error(f"【第5.5步】§5.4 自愈已触发并完成 ✓：{_heal}")
                    except Exception as _adx_e:
                        logger.warning(f"【第5.5步】个股ADX重算失败（不影响K线更新 ✓）: {_adx_e}")
                        self._add_update_log(f"✗ 个股ADX重算失败: {_adx_e}")
                        self.update_status['totalStats']['kline_failed'] = kline_result.get('failed', 0)
                    
                    # （K 线结果行已**前移**至 K 线刚结束处 ✓ —— 见上方说明 ✗→✓）
                
                except Exception as e:
                    self._add_update_log(f"✗ K线数据更新异常: {str(e)}")
                    logger.error(f"K线数据更新异常: {str(e)}")
                    with self.update_lock:
                        self.update_status['totalStats']['kline_failed'] = len(stock_codes)
            
            # 【第6步】更新资金流向数据
            if not update_types or 'fund_flow' in update_types:
                # ★【2026-09-29 如实化 ✓】原文案会让人以为"这一步 = 资金流更新"✗ ——
                #   实际它是**已停用的旧路径** ✗（旧表 `stock_fund_flow` 已停用 ✓
                #   + 行业/板块暂不处理 ✓ ⇒ 通常恒为 0 条 ✗）；
                #   真正的资金流（规范表 `stock_moneyflow_daily` ✓）在**【第8.5步】** ✓
                #   ⇒ 文案里**直接写明** ✓，免得再被误读为"资金流更新失败"✗✓。
                # ★【2026-09-29 用户要求 ✓】标题**缩短** ✗→✓ —— 原长句被进度行截断成
                #   "第6步 更新资金流向数据（**旧路径**：旧…" ✗ ⇒ 看不出重点 ✗✓；
                #   现标题只留"（旧路径·已停用）"✓，**细节放到结果行** ✓（见下 ✓）。
                self._add_update_log("【第6步】更新资金流向数据（旧路径·已停用）...")
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
                        # ★【2026-09-28 减噪 ✓】旧路径**整步空转**时不再播报 ✗→✓
                        #   实测 ✗✓：旧表已停用 ✗ + 行业/板块暂不处理 ✗ ⇒ 每轮更新都会打
                        #   "✓ 资金流向数据更新完成: 新增 0 条，更新 0 条，失败 0 条，耗时 0.0秒"✗
                        #   ⇒ 用户据此以为"资金流更新**没成功**"✗✓（真入口是【第8.5步】✓）。
                        _ff_noop = ('跳过' in str(fund_flow_result.get('message', ''))
                                    or not (fund_flow_result['added']
                                            or fund_flow_result['updated']
                                            or fund_flow_result['failed']))
                        if _ff_noop:
                            # ★【2026-09-29 用户要求 ✓】**如实播报"跳过"** ✗→✓
                            #   用户原话 ✓："这段日志很不明确，**到底更新了没有**" ✓ ——
                            #   此前这里只有 `debug` ✗ ⇒ INFO 级看不到 ✗，再叠加进度行的
                            #   "…**完成** ✓ 耗时 0.0s"✗ ⇒ 读者**无法判断** ✓。
                            #   现：① 本步**结果行**明确写"跳过"✓（进 `logs` ⇒ 前端面板可见 ✓）；
                            #       ② `_mark_stage_skipped` ✓ ⇒ 下一环节的耗时行也标"跳过"✓。
                            self._add_update_log(
                                "ℹ 【第6步】旧路径：旧表 stock_fund_flow 已停用 ⇒ "
                                "**本步跳过** ✓（新增 0 条 ✗、未联网 ✗）—— "
                                "**规范表 stock_moneyflow_daily 由【第8.5步】维护** ✓")
                            self._mark_stage_skipped('旧表已停用 ⇒ 本步无实际动作 ✓')
                        else:
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
            
            # 【第8步】刷新减持计划缓存（离线批量拉取候选池，落盘本地缓存）
            self._add_update_log("【第8步】刷新减持计划缓存...")
            try:
                from trading.reduce_plan_cache import refresh_reduce_plan_cache
                # 读取候选池股票代码（结构：pool[].stock.stock_code）
                pool_codes = []
                pool_file = Path(self.data_dir) / "running" / "buy_candidate_pool.json"
                if pool_file.exists():
                    try:
                        with open(pool_file, 'r', encoding='utf-8') as pf:
                            pool_data = json.load(pf)
                        for item in pool_data.get('pool', []):
                            sc = item.get('stock', {}).get('stock_code', '')
                            if sc:
                                pool_codes.append(sc)
                    except Exception as pe:
                        logger.warning("读取候选池失败: %s", pe)
                if pool_codes:
                    # 目标更新日期 YYYY-MM-DD 转 YYYYMMDD 作为刷新日期
                    score_dt = target_date.replace('-', '')
                    rp_stats = refresh_reduce_plan_cache(pool_codes, score_dt)
                    with self.update_lock:
                        self.update_status['totalStats']['reduce_plan_refreshed'] = rp_stats.get('refreshed', 0)
                        self.update_status['totalStats']['reduce_plan_failed'] = rp_stats.get('failed', 0)
                        self.update_status['totalStats']['reduce_plan_skipped'] = rp_stats.get('skipped', 0)
                    # ★【2026-09-28 修 ✓】如实汇总 `skipped` ✗→✓ —— 此前只报"刷新/失败"✗，
                    #   而"整体跳过"（本地公告未覆盖 + 闸门必拦 ✓）会被显示成
                    #   "刷新 0 只，失败 0 只"✗ ⇒ 用户误判为"正常但没数据"✗✓。
                    self._add_update_log(
                        f"✓ 减持计划缓存刷新完成: 刷新 {rp_stats.get('refreshed',0)} 只，"
                        f"失败 {rp_stats.get('failed',0)} 只，"
                        f"跳过 {rp_stats.get('skipped',0)} 只"
                        + ("（⚠️ 本地公告未覆盖 ⇒ 未联网、保留旧值 ✓；请先补齐公告域 ✓）"
                           if rp_stats.get('skipped') else "")
                    )
                else:
                    self._add_update_log("ℹ 候选池为空，跳过减持计划缓存刷新")
            except Exception as e:
                self._add_update_log(f"⚠ 减持计划缓存刷新异常(不影响其他步骤): {str(e)}")
                logger.warning(f"减持计划缓存刷新异常: {str(e)}")

            # 【第8.5步·2026-09-25 新增】四类本地数据更新（资金流 / 基本面 / 事件 / 日历 ✓）
            #   设计定稿：**滚动重采最近 3 个交易日** ✓ + 幂等写入 ✓ + 失败逐条落盘 ✓
            #   目的：让回测**只读本地**、结果可复现（杜绝同日同股评分漂移 ✗）
            #   注：K 线仍由上面的第 5 步负责（前复权机制不变 ✓）
            if not update_types or 'local_data' in update_types:
                self._add_update_log("【第8.5步】更新四类本地数据（资金流/基本面/事件/日历）...")
                try:
                    from utils.data_collectors.daily_update import run_daily_update
                    from utils.global_db import get_global_db

                    lc = run_daily_update(get_global_db().connect(), window=3)
                    _res = lc.get('results') or {}
                    _ts = self.update_status['totalStats']
                    _ts['local_moneyflow_added'] = (_res.get('moneyflow') or {}).get('added', 0)
                    _ts['local_event_added'] = (_res.get('event') or {}).get('added', 0)
                    _ts['local_fundamental_added'] = (_res.get('fundamental') or {}).get('added', 0)
                    _ts['local_fundamental_targets'] = (_res.get('fundamental') or {}).get('targets', 0)
                    _ts['local_calendar_days'] = (_res.get('calendar') or {}).get('total', 0)
                    # ★★【2026-09-29 用户要求 ✓】**过程 + 结果**一条说清 ✗→✓ ★★
                    #   动机 ✗✓：用户问"资金流为什么没完成"✗，而旧日志只有
                    #   "✓ 四类本地数据更新完成: 资金流+0 条"✗ —— `+0` **无法区分**
                    #   "已是最新"✓ 与"**根本没补上**"✗（本会话实测踩过 ✗✓）。
                    #   ⇒ ① 各域**明细**（新增/更新/失败/跳过原因 ✓）；
                    #     ② **落库对账** ✓：打印规范表真实最新日期 ✓（结果以**库为准** ✗✓）；
                    #     ③ 失败信息**不再顶掉**成功信息 ✗→✓（各自独立一行 ✓）。
                    _mf = _res.get('moneyflow') or {}
                    _mf_txt = (f"资金流 +{_mf.get('added', 0)}/Δ{_mf.get('updated', 0)}"
                               f"/✗{_mf.get('failed', 0)} 条"
                               + (f"（**跳过**：{_mf.get('reason')}）" if _mf.get('skipped') else ""))
                    self._add_update_log(
                        f"✓ 四类本地数据更新完成（窗口={lc.get('window')} ✓）: "
                        f"{_mf_txt} ✓ | 公告 +{_ts['local_event_added']} 条 ✓ | "
                        f"财报 +{_ts['local_fundamental_added']} 行"
                        f"({_ts['local_fundamental_targets']} 只) ✓ | "
                        f"日历 {_ts['local_calendar_days']} 日 ✓")
                    # ② 落库对账（只看**事实** ✓，不做判读 ✗ —— 判读与告警在 daily_update ✓）
                    try:
                        _row = get_global_db().connect().execute(
                            'SELECT MAX(trade_date) FROM stock_moneyflow_daily').fetchone()
                        _mf_latest = str(_row[0]) if _row and _row[0] else '（空 ✗）'
                    except Exception as _e_latest:
                        _mf_latest = f'（读取失败 ✗ {_e_latest}）'
                    self._add_update_log(
                        f"ℹ 资金流落库对账 ✓：stock_moneyflow_daily 最新 = **{_mf_latest}** ✓"
                        f"（窗口末日 {lc.get('window')[-1] if lc.get('window') else '?'} ✓）")
                    if lc.get('errors'):
                        self._add_update_log(f"⚠ 四类本地数据**部分失败** ✗（详见 data_fetch_failure ✓）: {lc['errors']}")
                    elif not lc.get('ok'):
                        self._add_update_log("⚠ 四类本地数据未全部成功（ok=False ✗）")
                except Exception as e:
                    # 单步失败不影响既有的 K 线/资金流等步骤 ✓，但如实记录 ✗
                    self._add_update_log(f"⚠ 四类本地数据更新异常(不影响其他步骤): {str(e)[:200]}")
                    logger.warning(f"四类本地数据更新异常: {e}", exc_info=True)
            else:
                # ★【2026-09-29 如实化 ✓】未勾选 `local_data` 时**此前一声不响** ✗ ⇒
                #   用户完全不知道"这一步被跳过 ⇒ 资金流/公告/财报都不会更新"✗✓。
                self._add_update_log(
                    "ℹ 未选择「本地数据」维度 ⇒ **跳过【第8.5步】** ✗"
                    "（资金流/公告/财报/日历**本次都不会更新** ✗；"
                    "如需更新请在更新选项中勾选「本地数据」✓）")
                # ★【2026-09-29】同步标记 ⇒ 耗时行也显示"本步跳过"✓（不再误读为"已完成"✗）
                self._mark_stage_skipped('未勾选「本地数据」维度 ⇒ 本步无实际动作 ✗')

            # 【第9步】记录更新完成
            self._add_update_log("【第9步】记录更新完成...")
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
            
            # 【第10步】计算并保存市场温度
            self._add_update_log("【第10步】计算并保存市场温度...")
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
            
            # 【第11步】计算并保存风控状态
            self._add_update_log("【第11步】计算并保存风控状态...")
            try:
                from utils.risk_controller import RiskController
                
                # 获取风控控制器
                controller = RiskController()
                
                # 计算风控状态（不使用缓存，确保获取最新数据）
                risk_status = controller.get_risk_status(
                    date=target_date,
                    force_refresh=True
                )
                
                if risk_status:
                    # 更新统计信息
                    self._add_update_log(
                        f"✓ 风控状态计算完成: VaR(1d)={risk_status.var_1d*100:.2f}% - "
                        f"风险等级={risk_status.risk_level.value} - "
                        f"仓位上限={risk_status.position_limit*100:.0f}%"
                    )
                    logger.info(f"风控状态已保存: {target_date} - VaR={risk_status.var_1d*100:.2f}%")
                else:
                    self._add_update_log(f"⚠ 风控状态计算失败: 返回空值")
                    logger.warning(f"风控状态计算失败: {target_date} - 返回空值")
            
            except Exception as e:
                self._add_update_log(f"⚠ 风控状态计算失败: {str(e)}")
                logger.warning(f"风控状态计算失败: {str(e)}")
            
            # 【第12步】计算并保存**大盘指数 ADX**（市场趋势强度，与温度同批次产出）
            # ★★【2026-10-05 用户要求 ✓】**要算多个指数**（不止全A）✗→✓ ★★
            #   用户原话 ✓："自动更新需要计算三个大盘 adx" ✓
            #   清单与逐个更新全在 `utils.market_index_adx.update_all_index_adx()` ✓
            #     （**可单测** ✓ + **失败隔离** ✓ + 代码**读同一份配置** ✓）——
            #     本处只负责调用与写日志 ✓（`_add_update_log` 进"数据更新"页 ✓）。
            self._add_update_log("【第12步】计算并保存大盘指数ADX（多指数 ✓）...")
            try:
                from utils.market_index_adx import update_all_index_adx

                # 不使用缓存 ⇒ 确保取最新数据 ✓；逐个指数独立计算/落库 ✓
                adx_res = update_all_index_adx(trade_date_yyyymmdd, use_cache=False)
                _saved, _skip = adx_res['saved'], adx_res['skipped']
                _failed = adx_res['failed']

                for _code in _saved:
                    self._add_update_log(f"  ✓ 指数ADX已保存 [{_code}] ✓")
                if _skip:
                    # 非交易日/接口无数据 ⇒ 正常跳过 ✓（不算失败 ✓，与既有口径一致 ✓）
                    self._add_update_log(
                        f"ℹ 指数ADX跳过（非交易日或数据不可用 ✓）: {', '.join(_skip)}")
                for _code, _err in _failed.items():
                    self._add_update_log(f"⚠ 指数ADX失败 [{_code}]: {str(_err)[:120]}")
                if not _failed:
                    self._add_update_log(
                        f"✓ 大盘指数ADX完成：成功 {len(_saved)} 个 / 跳过 {len(_skip)} 个 "
                        f"（清单={', '.join(adx_res['index_codes'])} ✓）")
                logger.info(
                    f"大盘指数ADX已处理: {trade_date_yyyymmdd} - 成功={_saved} "
                    f"跳过={_skip} 失败={_failed}")

            except Exception as e:
                self._add_update_log(f"⚠ 大盘指数ADX计算失败: {str(e)}")
                logger.warning(f"大盘指数ADX计算失败: {str(e)}")
            
            # 检查是否有数据被成功更新
            total_added = self.update_status['totalStats']['kline_added'] + self.update_status['totalStats']['fund_flow_added']
            total_updated = self.update_status['totalStats']['kline_updated'] + self.update_status['totalStats']['fund_flow_updated']
            total_success = total_added + total_updated
            total_failed = self.update_status['totalStats']['kline_failed'] + self.update_status['totalStats']['fund_flow_failed']
            
            # 更新任务状态
            with self.update_lock:
                # 如果失败数量超过1000，标记为失败（即使有成功的数据）
                if total_failed > 1000:
                    self.update_status['status'] = 'failed'
                    self.update_status['end_time'] = datetime.now().isoformat()
                    self.update_status['message'] = f'更新失败: 失败股票数量({total_failed})超过1000，请重新更新'
                    self.update_status['success'] = 0
                elif total_success > 0:
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
            
            if total_failed > 1000:
                self._add_update_log(f"✗ 更新任务失败: 失败股票数量({total_failed})超过1000")
                logger.warning(f"更新任务 {task_id} 失败: 失败股票数量({total_failed})超过1000")
                self._log_update_finish(task_id, _t0, '失败',
                                        f'失败股票数量({total_failed})超过1000')
            elif total_success > 0:
                self._add_update_log("✓ 更新任务完成")
                logger.info(f"更新任务 {task_id} 完成")
                self._log_update_finish(task_id, _t0, '完成')
            else:
                self._add_update_log("✗ 更新任务失败: 没有数据被成功更新")
                logger.warning(f"更新任务 {task_id} 失败: 没有数据被成功更新")
                self._log_update_finish(task_id, _t0, '失败', '没有数据被成功更新')
            
            # 记录更新完成或失败
            if validator and target_date:
                try:
                    if total_failed <= 1000 and total_success > 0:
                        validator.record_update_complete(target_date, stats)
                    else:
                        if total_failed > 1000:
                            validator.record_update_failed(target_date, f'失败股票数量({total_failed})超过1000')
                        else:
                            validator.record_update_failed(target_date, '没有数据被成功更新')
                except Exception as log_e:
                    logger.error(f"记录更新状态失败: {str(log_e)}")
            
        except Exception as e:
            # 检查是否有数据被成功更新
            total_added = self.update_status['totalStats']['kline_added'] + self.update_status['totalStats']['fund_flow_added']
            total_updated = self.update_status['totalStats']['kline_updated'] + self.update_status['totalStats']['fund_flow_updated']
            total_success = total_added + total_updated
            total_failed = self.update_status['totalStats']['kline_failed'] + self.update_status['totalStats']['fund_flow_failed']
            
            with self.update_lock:
                # 如果失败数量超过1000，标记为失败（即使有成功的数据）
                if total_failed > 1000:
                    self.update_status['status'] = 'failed'
                    self.update_status['end_time'] = datetime.now().isoformat()
                    self.update_status['message'] = f'更新失败: 失败股票数量({total_failed})超过1000，请重新更新'
                    self.update_status['success'] = 0
                elif total_success > 0:
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
            
            if total_failed > 1000:
                self._add_update_log(f"✗ 更新任务失败: 失败股票数量({total_failed})超过1000")
                logger.warning(f"更新任务 {task_id} 失败: 失败股票数量({total_failed})超过1000")
                self._log_update_finish(task_id, _t0, '失败',
                                        f'失败股票数量({total_failed})超过1000；异常={e}')
            elif total_success > 0:
                self._add_update_log(f"✓ 更新任务完成（部分步骤失败）: {str(e)}")
                logger.warning(f"更新任务 {task_id} 完成（部分步骤失败）: {str(e)}")
                self._log_update_finish(task_id, _t0, '完成（部分步骤失败）', str(e))
            else:
                self._add_update_log(f"✗ 错误: {str(e)}")
                logger.error(f"更新任务 {task_id} 失败: {str(e)}")
                # ★ 异常时**点名环节** ✓（用户要求："明确反映当前处于什么环节" ✓）
                self._add_update_log(
                    f"✗ 更新任务异常终止 ✗ —— **出错环节：{self._current_stage or '启动'}** ✓ "
                    f"（请据该环节排查 ✓；已完成部分的统计见下方汇总 ✓）")
                self._log_update_finish(task_id, _t0, '异常终止', str(e))
            
            # 记录更新完成或失败
            if validator and target_date:
                try:
                    if total_failed <= 1000 and total_success > 0:
                        validator.record_update_complete(target_date, stats)
                    else:
                        if total_failed > 1000:
                            validator.record_update_failed(target_date, f'失败股票数量({total_failed})超过1000')
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
            'skipped': self.update_status.get('skipped', False),  # 是否因数据源未就绪被跳过
            # ★【2026-09-29 用户要求 ✓】把"**当前环节**"透出给前端 ✗→✓
            #   前端进度区可直接显示（无需解析 logs 数组 ✓）；缺失/未开始 ⇒ 空串 ✓（前端不显示假信息 ✓）
            'currentStage': self.update_status.get('current_stage', ''),
            'stageNo': self.update_status.get('stage_no', 0),
            'totalStages': self._TOTAL_STAGES,
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
            dict: 表数据统计信息，包含前端需要的 success 和 failed 字段
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
                    'stock_margin_trading',
                    # 【2026-09-25 新增】本地化数据表（回测复现依赖 ✓）
                    'trade_calendar',
                    'stock_moneyflow_daily',
                    'stock_finance_indicator',
                    'stock_announcement',
                    'data_fetch_failure'
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
            
            # 前端期望的 success 和 failed 字段
            # success: 成功初始化的股票数量（stock_basic 表行数）
            # failed: 失败数量（股票总数 - 成功数量，或默认0）
            stats['success'] = stats.get('stock_basic', 0)
            stats['failed'] = self.init_status.get('failed', 0)
        
        except Exception as e:
            logger.error(f"获取表数据统计失败: {str(e)}")
            stats['success'] = 0
            stats['failed'] = 0
        
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

        ★【2026-09-29 用户要求 ✓】**明确反映"当前处于什么环节"** ✗→✓

        实测痛点 ✗✓：步骤行与结果行**混在一起**✗ —— 一旦**卡住/异常/被中断** ✗，
        翻日志**看不出跑到哪一步** ✗，也看不出**每步花了多久** ✗
        （本会话实测：第8步空耗 20 分钟 ✗，日志里只有一堆重试行 ✗，无法定位"仍在第8步"✗）。

        实现 ✓（**单点** ✓，**不改任何既有文案** ✗✓ —— 避免影响既有测试与前端展示 ✓）：
          ① 识别 `【第X步】` 步骤行 ⇒ 记下**当前环节** ✓；
          ② 打一条**环节切换行** ✓（含**上一环节耗时** ✓）⇒ 环节与耗时随时可查 ✓；
          ③ 异常/收尾日志据 `self._current_stage` 带上环节 ✓（见 `_log_update_finish` ✓）。

        ★★【2026-09-29 用户反馈 ✓】**改为"两级"：主环节 + 子阶段** ✗→✓ ★★
          实测 ✗✓：原先把**子阶段**（`· 第5.5步：…` ✓）也当成一个"环节"**计数** ✗ ⇒
          用户看到 `第 7 个环节 = 第5.5步 自愈检查` ✓、`第 8 个 = 第6步` ✗
          ⇒ 直判"**环节编号混乱、而且没有顺序**"✗（**完全成立** ✓）。
          现改为 ✓：
            · **主环节**（`【第X步】` ✓）⇒ 编号 = **真实步骤号 / 总步数** ✓（如 `▶ 环节 6/12：第6步 …` ✓）
              ⇒ 编号与顺序**天然一致** ✓（第5.5步只是第5步的子阶段 ✓，不再单独占号 ✗）；
            · **子阶段**（`· 第X步：…` ✓）⇒ 只打 `↳ 子阶段：…` ✓，**不计数、不重算耗时** ✗✓
              （该耗时并入其所属主环节 ✓）。

        Args:
            message: 日志消息
        """
        _msg = str(message)
        _m_main = re.match(r'^【第([\d.]+)步】\s*(.*?)[.。…]*$', _msg)
        _m_sub = re.match(r'^·\s*第([\d.]+)步[：:]\s*(.*?)[.。…]*$', _msg)
        if _m_main or _m_sub:
            _no_txt = (_m_main or _m_sub).group(1)
            _tail = (_m_main or _m_sub).group(2).strip(' .。…')
            _name = f'第{_no_txt}步' + (f' {_tail}' if _tail else '')
            if len(_name) > 22:                       # 长句会淹没重点 ✗ ⇒ 截断 ✓
                _name = _name[:22] + '…'
            if _m_main:
                # ⏱ 只报**主环节** ✓（用 `_main_stage` ✗✓ —— 否则标题会被其**子阶段**顶掉 ✗）
                _prev, _prev_t = self._main_stage, self._stage_started_at
                _now = time.monotonic()
                if _prev and _prev_t:
                    # ★【2026-09-29 用户要求 ✓】**区分"完成"与"跳过"** ✗→✓
                    #   用户原话 ✓："这段日志很不明确，**到底更新了没有**"✓ ——
                    #   空转步骤（0.0s ✓）原先同样打"…完成 ✓"✗ ⇒ 无法分辨 ✗✓。
                    _why = getattr(self, '_stage_skip_reason', '')
                    if _why:
                        logger.info('⏱ 环节「%s」**本步跳过** ✓（%s）耗时 %.1fs',
                                    _prev, _why, _now - _prev_t)
                    else:
                        logger.info('⏱ 环节「%s」完成 ✓ 耗时 %.1fs', _prev, _now - _prev_t)
                self._stage_skip_reason = ''          # ★ 新环节起点清空标记 ✓（防串台 ✗）
                self._stage_no = float(_no_txt)
                self._main_stage = _name
                self._current_stage = _name
                self._stage_started_at = _now
                # ★ 写进 `update_status` ✓ ⇒ 前端进度面板直接显示 ✓（无需解析 logs ✓）
                self.update_status['current_stage'] = _name
                self.update_status['stage_no'] = self._stage_no
                # ⚠️ **不再显示 "/12"** ✗✓：步号本身含 `5.5` / `8.5` ✗ ⇒ "N/12" 会误导 ✓
                logger.info('▶ 环节：%s ✓', _name)
            else:
                # 子阶段 ✓：只更新"当前在干什么" ✓（编号`_stage_no`与耗时`_stage_started_at`归属主环节 ✓）
                self._current_stage = _name
                self.update_status['current_stage'] = _name
                logger.info('↳ 子阶段：%s ✓', _name)
        # 直接保存消息字符串，而不是对象
        self.update_status['logs'].append(_msg)
        logger.info(f"[更新] {_msg}")

    #: 更新流水线的步骤总数 ✓（用于"环节/总步数"展示 ✓）
    _TOTAL_STAGES = 12

    def _mark_stage_skipped(self, reason: str = '') -> None:
        """★★【2026-09-29 用户要求 ✓】把**当前主环节**标记为"**本步跳过**" ✗→✓ ★★

        用户原话 ✓："这段日志很不明确，**到底更新了没有**" ✓ ——
          空转步骤（如【第6步】旧路径 ⇒ 0.0s ✓）原先照样打
          `⏱ 环节「…」完成 ✓ 耗时 0.0s` ✗ ⇒ 读日志的人**无法分辨**
          "真的更新了 ✓" 与"**整步跳过** ✗"（本会话实测踩到 ✓✓）。

        行为 ✓：
          · **立刻**打一条 INFO 结果行 ✓（不用等到下一步切换 ✓）⇒ 当场能看懂 ✓；
          · 记下原因 ✓ ⇒ 下一环节开始时，耗时行会写成
            `⏱ 环节「…」**本步跳过** ✓（原因 ✓）耗时 …` ✓；
          · ⚠️ **只影响展示** ✗✓ —— 不改 `update_status['logs']` 里的原消息 ✓、
            不改 `totalStats` ✓、不改任何判定 ✓。
        """
        self._stage_skip_reason = str(reason or '本步无实际动作')
        logger.info('ℹ 环节「%s」⇒ **本步跳过** ✓（%s）',
                    self._main_stage or self._current_stage or '（未命名环节）',
                    self._stage_skip_reason)

    def _reset_stage_tracking(self) -> None:
        """重置环节跟踪 ✓（每次更新任务开始时调用 ✓）

        ⚠️ 必须**同时清空** `update_status` 里的同名透出字段 ✗✓ ——
        否则新一轮更新开始后，前端的"当前环节"会**残留上一轮的环节** ✗（实测踩过 ✗）。
        """
        self._current_stage = ''
        self._main_stage = ''
        self._stage_started_at = 0.0
        self._stage_no = 0
        self._stage_skip_reason = ''
        try:
            if isinstance(getattr(self, 'update_status', None), dict):
                self.update_status['current_stage'] = ''
                self.update_status['stage_no'] = 0
        except Exception as e:                       # 纯展示字段 ✓ ⇒ 绝不因它中断任务 ✗
            logger.debug('重置环节透出字段失败（忽略 ✓）: %s', e)

    def _log_update_finish(self, task_id: str, t0: float, status: str,
                           note: str = '') -> None:
        """★【2026-09-29 用户要求 ✓】收尾**总汇总** ✗→✓（环节 + 总耗时 + 各环节关键结果 ✓）

        动机 ✗✓：原收尾只有"✓ 更新任务完成"✗ / "✗ 错误: xxx"✗ ——
        既没有**总耗时** ✓，也没有**各环节关键结果** ✓，还看不出**结束在哪个环节** ✗
        （实测：任务被中断后日志里连"结束行"都没有 ✗，只能靠人工推断 ✗✓）。
        """
        _el = time.monotonic() - t0 if t0 else 0.0
        _ts = self.update_status.get('totalStats') or {}
        _ok = str(status).startswith('完成')
        # 收尾报**主环节** ✓（子阶段只是它的细目 ✗）⇒ `_main_stage` 优先 ✓
        _stage = self._main_stage or self._current_stage or '启动'

        def _g(k):
            return _ts.get(k, 0)

        self._add_update_log(
            f"{'✓' if _ok else '✗'} 更新任务{status}（总耗时 {_el:.1f}s ✓；"
            f"结束环节：{_stage} ✓）")
        self._add_update_log(
            f"· 汇总: K线 +{_g('kline_added')}/Δ{_g('kline_updated')}/✗{_g('kline_failed')} ✓ | "
            f"本地数据(资金流/公告/财报) +{_g('local_moneyflow_added')}/"
            f"+{_g('local_event_added')}/+{_g('local_fundamental_added')} ✓ | "
            f"市值 ✓{_g('market_cap_updated')}/✗{_g('market_cap_failed')} ✓ | "
            f"减持缓存 ✓{_g('reduce_plan_refreshed')}/✗{_g('reduce_plan_failed')}/"
            f"跳过{_g('reduce_plan_skipped')} ✓ | "
            f"新股票 检测{_g('new_stock_detected')}/初始化{_g('new_stock_initialized')} ✓")
        logger.info('【更新总结】task=%s ✓ 状态=%s ✓ 总耗时=%.1fs ✓ 末环节=%s ✓ 统计=%s',
                    task_id, status, _el, self._current_stage or '-', dict(_ts))
        if note:
            logger.warning('【更新总结】备注 %s', note)


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
