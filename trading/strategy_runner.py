"""
策略运行引擎核心模块
实现量化策略的实盘运行功能，连接回测与实盘操作
支持多组合策略选择功能
"""

import sqlite3
import datetime
import logging
import os
import threading
import numpy as np
import pandas as pd
import json
import yaml
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from scipy import stats

from utils.db_manager import DBManager
from utils.akshare_fetcher import AKShareFetcher
from strategy.strategy_registry import StrategyRegistry
from trading.stock_score_api import calculate_stock_score

from trading.timing_strategies import (
    TimingStrategyFactory, TURTLE_FAMILY_STRATEGIES, build_turtle_family_params)
from utils.strategy_name_mapper import get_english_name
from utils.trade_date_utils import is_trading_day, get_previous_trading_day
from utils.trading_time_validator import is_market_closed
from trading.ptrade.ptrade_feedback import (
    PTradeFeedbackHandler,
    feedback_files_stamp,
    process_ptrade_feedback,
)
from trading.strategy_kelly_loader import KellyCalculator
from trading.strategy_execution_plan import ExecutionPlan, StrategyCombination
from trading.backtest_dao import BacktestDAO
from utils.feature_config_checker import FeatureConfigChecker

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 策略运行全局锁，确保同一时刻只有一个策略运行任务执行
_strategy_run_lock = threading.Lock()

# 信号执行全局锁，确保信号执行是串行的
_signal_execution_lock = threading.Lock()

# 股票池持久化文件路径
POOL_PERSIST_FILE = "data/running/buy_candidate_pool.json"

# 【2026-09-18】非股票品种（不得进入可买股票池；与 ETF 同口径）
#   标准券/质押券：PTrade 反馈会带进持仓，若被"持仓回池"吸收会污染股票池
NON_STOCK_KEYWORDS = ('标准券', '质押券')
#   深市标准券代码段（如 131990）；沪市标准券（205xxx）以名称为准
STANDARD_BOND_CODE_PREFIXES = ('131',)


def is_non_stock_instrument(stock_code, stock_name=None) -> bool:
    """是否为非股票品种（标准券/质押券等）

    与 ETF 同口径：不纳入可买股票池。识别口径：
      1. 名称含「标准券」或「质押券」；
      2. 代码属于标准券代码段（深市 131/131xxx，沪市 205xxx 以名称兜底）。
    """
    name = str(stock_name or '')
    if any(k in name for k in NON_STOCK_KEYWORDS):
        return True
    code = str(stock_code or '')
    # 深市标准券 131xxx；沪市标准券 205xxx（PTrade 反馈常见形态）
    return code.startswith(STANDARD_BOND_CODE_PREFIXES) or code.startswith('205')


def filter_non_stock_pool(pool, where: str = '股票池') -> list:
    """剔除股票池中的非股票品种（标准券/质押券），返回保留项列表

    背景（2026-09-18）：PTrade 反馈若把标准券带进持仓 → "持仓回池"会污染股票池；
    且**历史 buy_candidate_pool.json 中已残留的标准券**会在启动加载时被原样继承
    （`_load_pool_from_file` 不做过滤），导致前端股票池一直能看到它。
    因此加载与展示两处都需过滤，统一调用本函数。
    """
    kept, dropped = [], []
    for item in (pool or []):
        stock = item.get('stock', item) if isinstance(item, dict) else {}
        stock = stock if isinstance(stock, dict) else {}
        code = stock.get('stock_code')
        name = stock.get('stock_name')
        if is_non_stock_instrument(code, name):
            dropped.append(f"{code} {name or ''}".strip())
        else:
            kept.append(item)
    if dropped:
        logger.info("【%s】剔除非股票品种 %d 只（标准券/质押券不参与股票池）: %s",
                    where, len(dropped), ', '.join(dropped))
    return kept


def calculate_trading_cost(stock_code: str, price: float, quantity: int, is_buy: bool, config: dict) -> dict:
    """计算交易成本（佣金、印花税、过户费、滑点）
    
    Args:
        stock_code: 股票代码
        price: 交易价格
        quantity: 交易数量
        is_buy: 是否为买入操作
        config: 交易成本配置
        
    Returns:
        成本明细字典
    """
    trading_config = config.get('trading', {})
    
    # 获取配置参数
    commission_rate = trading_config.get('commission_rate', 0.00015)  # 默认0.015%
    min_commission = trading_config.get('min_commission', 5)            # 最低佣金5元
    stamp_tax_rate = trading_config.get('stamp_tax_rate', 0.001)       # 印花税0.1%
    transfer_fee_rate = trading_config.get('transfer_fee_rate', 0.00001)  # 过户费0.001%
    
    slippage_config = trading_config.get('slippage', {})
    slippage_enabled = slippage_config.get('enabled', True)
    buy_slippage = slippage_config.get('buy_slippage', 0.01)   # 默认买入滑点+1%
    sell_slippage = slippage_config.get('sell_slippage', 0.005) # 默认卖出滑点-0.5%
    
    # 判断是否为沪市股票（6开头）
    is_shanghai = stock_code.startswith('6')
    
    # 计算成交金额
    original_amount = price * quantity
    
    # 计算滑点调整后的价格
    if slippage_enabled:
        if is_buy:
            slippage_rate = buy_slippage
        else:
            slippage_rate = sell_slippage
        adjusted_price = price * (1 + slippage_rate if is_buy else 1 - slippage_rate)
    else:
        slippage_rate = 0
        adjusted_price = price
    
    # 滑点成本
    slippage_cost = abs(adjusted_price - price) * quantity
    
    # 调整后的成交金额
    adjusted_amount = adjusted_price * quantity
    
    # 佣金（双向收取）
    commission = adjusted_amount * commission_rate
    commission = max(commission, min_commission)  # 最低佣金保底
    
    # 过户费（仅沪市股票，双向收取）
    transfer_fee = 0
    if is_shanghai:
        transfer_fee = adjusted_amount * transfer_fee_rate
    
    # 印花税（仅卖出时收取）
    stamp_tax = 0
    if not is_buy:
        stamp_tax = adjusted_amount * stamp_tax_rate
    
    # 总成本
    total_cost = slippage_cost + commission + transfer_fee + stamp_tax
    
    # 买入成本 = 成交金额 + 所有费用
    # 卖出成本 = 滑点成本 + 佣金 + 过户费 + 印花税
    if is_buy:
        total_cost = slippage_cost + commission + transfer_fee
    else:
        total_cost = slippage_cost + commission + transfer_fee + stamp_tax
    
    return {
        'original_price': price,
        'adjusted_price': round(adjusted_price, 3),
        'slippage_rate': slippage_rate,
        'slippage_cost': round(slippage_cost, 2),
        'commission': round(commission, 2),
        'transfer_fee': round(transfer_fee, 2) if is_shanghai else 0,
        'stamp_tax': round(stamp_tax, 2) if not is_buy else 0,
        'total_cost': round(total_cost, 2),
        'is_shanghai': is_shanghai,
        'original_amount': round(original_amount, 2),
        'adjusted_amount': round(adjusted_amount, 2)
    }


# PTrade 信号文件保留数量上限（PTrade 上传文件数有限制）
MAX_PTRADE_CSV_FILES = 3

class StrategyRunner:
    """策略运行引擎核心类"""
    
    # 类级别：防止并发执行标志
    _is_running = False
    
    def __init__(self, *args, **kwargs):
        """初始化策略运行引擎
        
        Args:
            *args: 可变参数
            **kwargs: 关键字参数
        """
        # 从参数中获取db_path，默认值为"data/stock_selection.db"
        db_path = kwargs.get('db_path', "data/stock_selection.db")
        if args:
            db_path = args[0]
        
        from utils.global_db import get_global_db
        self.db_manager = get_global_db()
        self.akshare_fetcher = AKShareFetcher("data")
        self.strategy_registry = StrategyRegistry()
        # 自动注册所有策略
        self.strategy_registry.auto_register_from_directory()
        
        # 初始化K线数据获取器
        from utils.stock_data_fetcher import StockDataFetcher
        self.stock_data_fetcher = StockDataFetcher("data")
        from utils.kline_fetcher import KlineFetcher
        self.kline_fetcher = KlineFetcher(self.db_manager, self.stock_data_fetcher)
        
        # 股票数据缓存（性能优化）
        self.stock_data_cache = {}  # {code: df} 完整历史数据
        self.stock_name_cache = {}  # {code: name} 股票名称缓存
        self.stock_filtered_cache = {}  # {code: df} 已过滤ST/退市的股票
        self._preload_date = None  # 缓存预加载日期，日期变化时自动重新加载
        self._preload_days = 0  # 记录预加载时的历史天数，参数变化时重新加载
        
        # 可买股票池
        self.buy_candidate_pool = []  # 可买股票池，每个元素包含股票信息和加入日期
        
        # 交易日历缓存
        self.trading_calendar_cache = {}  # {date_str: is_open} 交易日历缓存
        self._sorted_trading_dates = []   # 排序后的交易日列表
        
        # 择时策略
        self.timing_strategy = None
        self.timing_strategy_name = None
        self.timing_strategy_params = {}
        
        # 加载策略运行配置（必须在使用配置之前）
        self.config = self._load_config()
        
        # 当前总资金（从配置中获取初始资金）
        self.current_total_capital = self.config.get('initial_capital', 300000.0)
        
        # 持仓信息
        self.portfolio = {}
        
        # 信号历史
        self.signals = []
        
        # 确保运行目录存在（使用绝对路径）
        self.running_dir = Path(__file__).resolve().parent.parent / "data/running"
        self.running_dir.mkdir(exist_ok=True)
        
        self.take_profit_threshold = self.config.get('take_profit_threshold', 0.21)
        self.stop_loss_threshold = self.config.get('stop_loss_threshold', -0.05)
        
        # 初始化标志，避免重复初始化
        self._initialized_dates = set()
        # 除权处理日期记录，避免同一天重复处理除权
        self._exdividend_processed_dates = set()
        # 工作日期缓存：同一进程内工作日期不变，避免重复计算交易日/收盘状态
        self._cached_working_date = None
        # 加载回测评分器
        from trading.backtest_scorer import BacktestScoreCalculator
        self.score_calculator = BacktestScoreCalculator(db_manager=self.db_manager)
        
        # 加载股票池移除配置
        self._pool_removal_config = self._load_pool_removal_config()

        # 加载支撑位方法配置
        self._support_methods_config = self._load_support_methods_config()

        # 初始化预加载管理器（复用过回测引擎的预加载机制）
        from trading.preload_manager import PreloadManager
        self.preload_manager = PreloadManager(self)
        
        # 连续亏损计数：记录每只股票的连续亏损次数（冷却状态已合并到股票池中）
        self.consecutive_loss_count = {}  # {stock_code: consecutive_loss_count}
    
    def _load_pool_removal_config(self) -> Dict:
        """加载股票池移除策略配置
        
        Returns:
            策略名称 -> 配置字典的映射
        """
        try:
            config_path = Path(__file__).parent.parent / "config" / "pool_removal_config.yaml"
            if not config_path.exists():
                logger.warning(f"股票池移除配置文件不存在: {config_path}")
                return {}
            
            with open(config_path, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f) or {}
            
            # 保存资金流向规则配置
            self._fund_flow_rules = yaml_config.get('fund_flow_rules', {})
            logger.info(f"加载资金流向移除规则: enabled={self._fund_flow_rules.get('is_enabled', False)}, "
                       f"min_hold_days={self._fund_flow_rules.get('min_hold_days', 1)}"
                       f"（判定条件与资金面一票否决一致，net_flow_threshold 已废弃）")
            
            config_map = {}
            strategies = yaml_config.get('removal_strategies', {})
            strategy_count = 0  # 统计实际的策略数量
            for name, cfg in strategies.items():
                if cfg.get('is_enabled', True):
                    strategy_count += 1
                    config_map[name] = {
                        'min_hold_days': cfg.get('min_hold_days', 2),
                        'display_name': cfg.get('display_name', '')
                    }
                    display_name = cfg.get('display_name', '')
                    if display_name:
                        config_map[display_name] = config_map[name]
                        if display_name.endswith('策略'):
                            config_map[display_name[:-2]] = config_map[name]
            
            logger.info(f"加载股票池移除策略: {strategy_count} 个策略")
            return config_map
        except Exception as e:
            logger.warning(f"加载股票池移除配置失败: {str(e)}")
            # 默认资金流向规则配置
            self._fund_flow_rules = {'is_enabled': True, 'net_flow_threshold': -10000, 'min_hold_days': 1}
            return {}
    
    def _load_support_methods_config(self) -> Dict:
        """加载策略支撑位方法配置
        
        Returns:
            策略名称 -> 支撑位配置字典
        """
        try:
            config_path = Path(__file__).parent.parent / "config" / "support_methods.yaml"
            if not config_path.exists():
                logger.warning(f"支撑位方法配置文件不存在: {config_path}")
                return {}
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            
            strategies_config = config.get('strategies', {})
            logger.info(f"加载支撑位方法配置: {len(strategies_config)} 个策略")
            return strategies_config
        except Exception as e:
            logger.warning(f"加载支撑位方法配置失败: {str(e)}")
            return {}

    def _load_task_history(self) -> List[Dict]:
        """加载任务历史记录
        
        Returns:
            任务历史列表
        """
        try:
            history_file = self.running_dir / "task_history.json"
            if history_file.exists():
                with open(history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    logger.info(f"加载任务历史记录: {len(history)} 条")
                    return history
            return []
        except Exception as e:
            logger.warning(f"加载任务历史记录失败: {str(e)}")
            return []

    def _save_task_history(self, history: List[Dict]):
        """保存任务历史记录
        
        Args:
            history: 任务历史列表
        """
        try:
            history_file = self.running_dir / "task_history.json"
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            logger.info(f"保存任务历史记录: {len(history)} 条")
        except Exception as e:
            logger.error(f"保存任务历史记录失败: {str(e)}")

    def _save_batch_task_config(self, tasks: List[Dict], working_date: str):
        """用标准 task_history.json 格式保存本次批量任务配置
        
        将 pipeline 格式（selection_strategy / strategy_names）映射为
        save_task_record 标准格式（strategies 类名列表）。
        
        Args:
            tasks: 任务列表，每个任务包含 selection_strategy 或 strategy_names、timing_strategy
            working_date: 运行日期
        """
        try:
            from utils.strategy_name_mapper import get_english_name
            history = self._load_task_history()
            # 提取策略类名列表（支持 selection_strategy 和 strategy_names 两种 key）
            strategy_list = []
            timing_strategy = 'support'
            for t in tasks:
                timing_strategy = t.get('timing_strategy', 'support')
                # 优先取 selection_strategy（web 端传入，单个策略），回退到 strategy_names（流水线传入，多策略列表）
                sel = t.get('selection_strategy', None)
                if sel:
                    # 单个策略：直接映射类名
                    class_name = get_english_name(sel) if sel else ''
                    if class_name:
                        strategy_list.append(class_name)
                else:
                    # 多策略列表：遍历所有策略名
                    names = t.get('strategy_names', [])
                    for name in names:
                        class_name = get_english_name(name) if name else ''
                        if class_name:
                            strategy_list.append(class_name)
            # 过滤空字符串，确保不写入无效记录
            strategy_list = [s for s in strategy_list if s]
            # 标准格式记录
            record = {
                'id': datetime.datetime.now().strftime('%Y%m%d_%H%M%S'),
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'strategies': strategy_list,
                'timing_strategy': timing_strategy,
                'mode': 'realtime',
                'status': 'completed'
            }
            # 与 save_task_record 保持一致：只保留最后一次任务记录
            self._save_task_history([record])
            logger.info(f"任务配置已保存到 task_history.json (策略: {strategy_list}, 择时: {timing_strategy})")
        except Exception as e:
            logger.warning(f"保存任务配置失败（不阻断主流程）: {e}")

    def save_task_record(self, task_config: Dict) -> Dict:
        """保存任务运行记录
        
        Args:
            task_config: 任务配置，包含 strategies、timing_strategy、initial_capital 等
            
        Returns:
            操作结果
        """
        try:
            record = {
                'id': datetime.datetime.now().strftime('%Y%m%d_%H%M%S'),
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'strategies': task_config.get('strategies', []),
                'timing_strategy': task_config.get('timing_strategy', 'support'),
                'initial_capital': task_config.get('initial_capital', 300000),
                'mode': task_config.get('mode', 'realtime'),
                'status': 'completed'
            }
            
            # 只保留上次执行的任务，不累积历史记录
            history = [record]
            
            self._save_task_history(history)
            
            return {'success': True, 'record': record}
        except Exception as e:
            logger.error(f"保存任务记录失败: {str(e)}")
            return {'success': False, 'error': str(e)}

    def get_task_history(self, limit: int = 10) -> List[Dict]:
        """获取任务历史记录
        
        Args:
            limit: 返回记录数量限制
            
        Returns:
            任务历史列表
        """
        history = self._load_task_history()
        return history[:limit]

    def get_last_task(self) -> Dict:
        """获取上次运行的任务配置
        
        Returns:
            上次任务配置，如果没有则返回空策略列表
        """
        history = self._load_task_history()
        if history:
            last_record = history[0]
            return {
                'strategies': last_record.get('strategies', []),
                'timing_strategy': last_record.get('timing_strategy', 'support'),
                'initial_capital': last_record.get('initial_capital', 300000),
                'mode': last_record.get('mode', 'realtime')
            }
        return None
    
    def _get_support_method_for_strategy(self, strategy_name: str) -> str:
        """获取策略的支撑位计算方法
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            支撑位计算方法（ma20/key_close_5/key_open/key_close）
        """
        strategy_config = self._support_methods_config.get(strategy_name, {})
        if isinstance(strategy_config, dict):
            return strategy_config.get('support_method', 'ma20')
        elif isinstance(strategy_config, str):
            return strategy_config
        return 'ma20'
    
    def _get_strategy_removal_config(self, strategy_name: str) -> Dict:
        """获取策略的移除配置
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            移除配置字典
        """
        if strategy_name in self._pool_removal_config:
            return self._pool_removal_config[strategy_name]
        
        if not strategy_name.endswith('策略'):
            with_strategy = strategy_name + '策略'
            if with_strategy in self._pool_removal_config:
                return self._pool_removal_config[with_strategy]
        
        if strategy_name.endswith('策略'):
            without_strategy = strategy_name[:-2]
            if without_strategy in self._pool_removal_config:
                return self._pool_removal_config[without_strategy]
        
        # 默认配置
        return {'min_hold_days': 2}
    
    # ==================== 股票池持久化方法 ====================
    
    def _load_pool_from_file(self, working_date: str = None) -> Tuple[List[Dict], bool]:
        """从文件加载股票池
        
        Args:
            working_date: 当前工作日期，用于检查是否当天已经执行过
            
        Returns:
            (股票池列表, 是否需要重新执行)
            - 需要重新执行的情况：文件不存在
            - 不需要重新执行的情况：文件存在（直接继承，不重新执行选股）
        """
        pool_file = Path(POOL_PERSIST_FILE)
        if not pool_file.exists():
            logger.info("股票池文件不存在，将初始化")
            return [], True
        
        try:
            with open(pool_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            pool = data.get('pool', [])
            last_date = data.get('last_date', '')
            
            logger.info(f"从文件加载股票池: {len(pool)} 只股票，上次运行日期: {last_date}")

            # 【2026-09-18】历史文件可能残留标准券/质押券（ETF 同口径的非股票品种）→
            #   启动加载时即剔除，避免前端股票池继续显示
            pool = filter_non_stock_pool(pool, where='股票池加载')
            
            # 确保每个候选股票都有冷却状态标记（兼容旧版本文件）
            for item in pool:
                if 'is_cooling' not in item:
                    item['is_cooling'] = False
                if 'cool_down_end' not in item:
                    item['cool_down_end'] = None
            
            # 用户需求：直接继承 buy_candidate_pool.json，不重建
            # 无论日期是否匹配，只要文件存在就直接加载
            # 需要重新执行选股的情况只有文件不存在时
            return pool, False
        except Exception as e:
            logger.error(f"加载股票池文件失败: {str(e)}")
            return [], True
    
    def _save_pool_to_file(self, pool: List[Dict], date: str):
        """保存股票池到文件
        
        Args:
            pool: 股票池列表
            date: 当前日期
        """
        try:
            # 确保每个候选股票都有冷却状态标记（已合并到股票池中）
            for item in pool:
                # 如果没有冷却状态标记，初始化默认值
                if 'is_cooling' not in item:
                    item['is_cooling'] = False
                if 'cool_down_end' not in item:
                    item['cool_down_end'] = None
            
            # 打印股票池清单
            logger.info(f"========== 股票池清单 ({len(pool)} 只) ==========")
            for i, item in enumerate(pool, 1):
                stock = item.get('stock', item)
                code = stock.get('stock_code', 'N/A')
                name = stock.get('stock_name', 'N/A')
                score = stock.get('score', 0)
                added_date = item.get('added_date', 'N/A')
                support = item.get('support_level', 0)
                strategy = item.get('strategy_name', 'N/A')
                is_cooling = item.get('is_cooling', False)
                cool_down_end = item.get('cool_down_end', 'N/A')
                cooling_info = f" | 冷却中" if is_cooling else ""
                if is_cooling and cool_down_end:
                    cooling_info = f" | 冷却中(至{cool_down_end})"
                logger.info(f"  {i}. {code} {name} | 评分: {score:.1f} | 入池: {added_date} | 支撑: ¥{support:.2f} | 策略: {strategy}{cooling_info}")
            logger.info("=" * 50)
            
            data = {
                'last_date': date,
                'pool': pool,
                'updated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            with open(POOL_PERSIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            
            logger.info(f"股票池已保存: {len(pool)} 只股票")
        except Exception as e:
            logger.error(f"保存股票池文件失败: {str(e)}")
    
    # ==================== 停牌检查 ====================
    
    def _is_stock_suspended(self, stock_code: str, current_date: str) -> bool:
        """
        检查股票是否在指定日期停牌
        
        判断依据：数据库中该股票是否有指定日期的K线数据
        
        Args:
            stock_code: 股票代码
            current_date: 检查日期，格式 YYYY-MM-DD
            
        Returns:
            True 表示停牌（无当日K线），False 表示正常交易（有当日K线）
        """
        # 方法1：从缓存中检查（如果缓存中有该股票的数据）
        if stock_code in self.stock_filtered_cache:
            df = self.stock_filtered_cache[stock_code]
            # 检查是否有 current_date 当日的数据
            dates = df['date'].unique()
            return current_date not in dates
        
        # 方法2：从数据库查询当日是否有K线
        try:
            # 数据库代码无 .SZ/.SH 后缀，需去除
            db_code = stock_code.replace('.SZ', '').replace('.SH', '')
            # 查询当日数据
            df = self.db_manager.read_stock(db_code, start_date=current_date, end_date=current_date)
            if df is None or df.empty:
                return True  # 无当日数据，视为停牌
            
            return False  # 有当日数据，正常交易
            
        except Exception as e:
            logger.debug(f"检查股票 {stock_code} 停牌状态失败: {str(e)}")
            return True  # 查询失败保守处理为停牌
    
    # ==================== 预加载股票数据 ====================
    
    def _preload_stock_data(self, current_date: str, strategy_name: str = None):
        """预加载所有股票数据到内存（批量加载优化版）

        优化：3次SQL替代逐只 read_stock（~5280次独立查询）

        Args:
            current_date: 当前日期
            strategy_name: 策略名称，用于计算需要的历史数据天数
        """
        from datetime import datetime, timedelta
        import pandas as pd

        current_dt = datetime.strptime(current_date, '%Y-%m-%d')

        # 与前端选股保持一致的K线加载范围，确保选股结果一致
        # 前端固定使用200天，此处 min_days 设为 200 以统一数据口径
        min_days = 200
        required_days = min_days
        # 【2026-09-19】需全历史的策略：只对"需要的股票"取全历史（None = 全部活跃股）
        full_history_codes = None

        if strategy_name:
            strategy = self.strategy_registry.get_strategy(strategy_name)
            if strategy and hasattr(strategy, 'params'):
                params = strategy.params
                max_value = 0

                lookback_keys = [
                    'lookback_days', 'pattern_days', 'limit_up_lookback_days',
                    'high_drawdown_days',  # 超跌反弹：收盘价 vs 近 N 日最高价的回撤窗口
                    'lowest_point_lookback_days', 'surge_lookback_days', 'uptrend_lookback_days'
                ]
                period_keys = ['ma_period', 'ma_short_period', 'ma_long_period', 'kdj_n',
                             'macd_short', 'macd_long', 'macd_signal', 'volume_ma_period']

                for key in lookback_keys + period_keys:
                    if key in params:
                        val = params[key]
                        if isinstance(val, (int, float)):
                            max_value = max(max_value, int(val))

                # 取策略所需天数与前端统一天数(200)的较大值
                required_days = max(min_days, max_value + 60)

                # 【2026-09-19】策略级特殊处理：需要"上市以来全历史"的策略（如次新腰斩）
                #   不受固定回溯天数截断（否则全局指标如"上市以来最高价"会失真）
                if getattr(strategy, 'requires_full_history', False):
                    required_days = 36500       # 100 年 ⇒ 等价于不截断（取全历史）
                    # 只对"需要的股票"取全历史（以当前选股日为界，无未来函数）
                    if hasattr(strategy, 'full_history_universe'):
                        full_history_codes = strategy.full_history_universe(
                            self.db_manager, current_date, params)
                    logger.info(f"策略 {strategy_name} 声明 requires_full_history=True，"
                                f"执行选股预加载改为全历史（仅限 %s 只需要的股票）",
                                len(full_history_codes) if full_history_codes else '全部')

        # 扩展开始日期
        extended_start = (current_dt - timedelta(days=required_days)).strftime('%Y-%m-%d')
        if required_days >= 36500:
            # 需全历史的策略（requires_full_history）→ 从库内最早数据起取
            extended_start = '1990-01-01'
        logger.info(f"预加载股票数据: {extended_start} ~ {current_date} (历史: {required_days}天)")

        # 第1步：一次SQL获取选股日有K线的活跃股票（退市/停牌自动排除）
        step1_start = datetime.now()
        # 向前回看5个交易日，解除对"当日"K线的强依赖：
        # 当日K线未入库(盘后延迟)时，只要近5日有K线即视为活跃，避免预加载整体跳过
        active_codes = self.db_manager.get_active_stock_codes(current_date, lookback_days=5)
        step1_time = (datetime.now() - step1_start).total_seconds()
        total_stocks = len(self.db_manager.list_all_stocks())
        logger.info(f"[预加载-第1步] 选股日{current_date}有效股票: {len(active_codes)} 只, "
                    f"排除(退市/停牌): {total_stocks - len(active_codes)} 只, "
                    f"耗时 {step1_time:.1f}s")

        if not active_codes:
            # 升级为 error：预加载整体失败属异常(近5日均无K线才可能触发)
            # 注意：此处"不"设置 self._preload_date，保留 need_reload 重试能力，
            # 避免当日固化导致后续运行不再重试预加载
            logger.error("【预加载】近5日均无活跃股票数据，跳过本次预加载；"
                         "未设置预加载日期以保留重试，请核查K线入库情况")
            return

        # 第2步：一次SQL批量加载活跃股票K线（仅限定日期范围）
        step2_start = datetime.now()
        if full_history_codes is not None:
            # 需全历史的策略：活跃股 ∩ 需要的股票（大幅收窄数据量）
            _codes = sorted(set(active_codes) & set(full_history_codes))
            logger.info(f"【预加载】全历史策略：活跃股 %d 只 ∩ 需要全历史 %d 只 = %d 只",
                        len(active_codes), len(full_history_codes), len(_codes))
        else:
            _codes = active_codes
        all_kline_df = self.db_manager.read_all_stocks_kline(
            extended_start, current_date, codes=_codes
        )
        step2_time = (datetime.now() - step2_start).total_seconds()

        if all_kline_df.empty:
            logger.warning("批量K线数据为空，跳过预加载")
            return

        # 统一日期格式为字符串（与原有 cache 格式一致）
        all_kline_df['date'] = pd.to_datetime(all_kline_df['date']).dt.strftime('%Y-%m-%d')
        # 按code分组，按日期正序排列（与原有格式一致）
        all_kline_df = all_kline_df.sort_values(['code', 'date'])

        # 第3步：批量获取股票名称
        step3_start = datetime.now()
        all_stock_names = self.db_manager.get_all_stock_names()
        self.stock_name_cache.update(all_stock_names)
        step3_time = (datetime.now() - step3_start).total_seconds()

        # 第4步：按code分组并构建缓存
        step4_start = datetime.now()
        loaded = 0
        skipped = 0
        no_kline_skip = 0  # 选股日无K线（不应出现，仅防御）

        grouped = all_kline_df.groupby('code')
        # 最小行数阈值：与前端选股保持一致，固定30行
        min_rows = 30
        for code, group_df in grouped:
            # 数据行数不足 → 跳过（按交易日比例折算，避免加载范围不足时全跳过）
            if len(group_df) < min_rows:
                skipped += 1
                continue

            # 缓存原始数据（正序，全部活跃股票）
            self.stock_data_cache[code] = group_df.copy()

            # 获取股票名称
            name = all_stock_names.get(code, '未知')

            # 过滤ST股票和退市股票
            invalid = name.startswith('ST') or name.startswith('*ST')
            if not invalid:
                for kw in ['退', '未知', '退市', '已退']:
                    if kw in name:
                        invalid = True
                        break

            if invalid:
                skipped += 1
                continue

            # 缓存有效股票（非ST/非退市）
            self.stock_filtered_cache[code] = group_df.copy()
            loaded += 1

        step4_time = (datetime.now() - step4_start).total_seconds()

        total_time = step1_time + step2_time + step3_time + step4_time
        logger.info(f"预加载完成: 有效股票 {loaded}, 跳过 {skipped}, "
                    f"总股票 {len(active_codes)}, 总耗时 {total_time:.1f}s "
                    f"(步骤: SQL-1={step1_time:.1f}s SQL-2={step2_time:.1f}s "
                    f"名称={step3_time:.1f}s 分组={step4_time:.1f}s)")
        # 记录预加载参数，用于后续检查是否需要重新加载
        self._preload_date = current_date
        self._preload_days = required_days

    # ==================== 初始股票池预加载 ====================

    def _execute_stock_pool_preload(self, strategy_name: str, config: Dict):
        """Execute initial stock pool preload (first run)

        Reuse PreloadManager mechanism, keep consistent with backtest engine.
        Note: Only preload data, do not execute stock selection strategy

        Args:
            strategy_name: Stock selection strategy name
            config: Configuration parameters
        """
        preload_enabled = config.get('preload_enabled', True)
        
        # User requirement: Do not preload stock selection, but data preload is needed
        if not preload_enabled:
            logger.info("Preload function is disabled")
            return
        
        # Only preload data if not already loaded (avoid duplicate preload)
        if self.stock_filtered_cache:
            logger.info("股票数据已预加载，跳过重复预加载")
            return
        
        logger.info("-------------------- Preload Stock Data --------------------")
        working_date = self.get_working_date()
        self._preload_stock_data(working_date, strategy_name)
        logger.info("Stock data preload completed, no preload stock selection")

    # ==================== 选股和评分 ====================
    
    def _execute_selection(self, strategy_name: str, current_date: str) -> List[Dict]:
        """执行选股（从缓存读取，使用日期切片）
        
        Args:
            strategy_name: 策略名称
            current_date: 选股日期
            
        Returns:
            选股结果列表
        """
        try:
            # 确保策略已注册
            if not self.strategy_registry.strategies:
                self.strategy_registry.auto_register_from_directory()
            
            # 获取策略
            from utils.strategy_name_mapper import get_english_name
            mapped_name = get_english_name(strategy_name)
            strategy = self.strategy_registry.get_strategy(mapped_name)
            
            if not strategy:
                strategy = self.strategy_registry.get_strategy(strategy_name)
            
            if not strategy:
                raise ValueError(f"策略 {strategy_name} 不存在")
            
            standardized_stocks = []
            
            # 从缓存遍历有效股票
            for code, df in self.stock_filtered_cache.items():
                try:
                    # 日期切片
                    df_to_date = df[df['date'] <= current_date].copy()
                    
                    if df_to_date.empty:
                        continue
                    
                    # 反转数据为倒序
                    if len(df_to_date) > 1 and df_to_date['date'].iloc[0] < df_to_date['date'].iloc[-1]:
                        df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)
                    
                    # 获取股票名称
                    name = self.stock_name_cache.get(code, "未知")
                    
                    # 执行选股（传递当前日期用于停牌检查）
                    signal_list = strategy.execute_selection(df_to_date, code, name, selection_date=current_date)
                    
                    if signal_list:
                        for signal in signal_list:
                            stock_info = {
                                'stock_code': code,
                                'stock_name': name,
                                'signal': signal,
                                'detail_url': f"javascript:viewStockDetail('{code}')"
                            }
                            standardized_stocks.append(stock_info)
                
                except Exception as e:
                    logger.debug(f"股票 {code} 选股失败: {str(e)}")
                    continue
            
            logger.info(f"{strategy_name} 策略在 {current_date} 选出 {len(standardized_stocks)} 只股票")
            return standardized_stocks
            
        except Exception as e:
            logger.error(f"执行选股失败: {str(e)}")
            return []
    
    def _score_stocks(self, stocks: List[Dict], strategy_name: str, current_date: str) -> List[Dict]:
        """对股票进行评分
        
        Args:
            stocks: 股票列表
            strategy_name: 策略名称
            current_date: 评分日期
            
        Returns:
            带评分的股票列表
        """
        if not stocks:
            return []
        
        # 应用策略名称映射（支持蛇形命名别名如 immortal_guidance）
        from utils.strategy_name_mapper import get_english_name
        mapped_name = get_english_name(strategy_name)
        
        # 获取策略的中文名称
        strategy = self.strategy_registry.get_strategy(mapped_name)
        if not strategy:
            strategy = self.strategy_registry.get_strategy(strategy_name)
        strategy_display_name = strategy.name if strategy else strategy_name
        
        # 入池规则：简化模式下评分器只判一票否决（跳过所有维度打分）
        from trading.pool_entry_rules import resolve_pool_entry_simplified

        _simplified = resolve_pool_entry_simplified(
            getattr(self, 'config', None) or {}, self._load_engine_config())

        # 使用回测评分器进行批量评分
        scored_stocks = self.score_calculator.calculate_batch_scores(
            stocks=stocks,
            score_date=current_date,
            strategy_name=strategy_display_name,
            simplified=_simplified
        )
        
        return scored_stocks
    
    def _select_and_score_stocks(self, strategy_name: str, current_date: str, score_threshold: int = 60) -> List[Dict]:
        """执行选股、评分、筛选，得到候选股票池
        
        Args:
            strategy_name: 策略名称
            current_date: 当前日期
            score_threshold: 评分阈值
            
        Returns:
            候选股票列表
        """
        logger.info(f"开始执行选股，策略: {strategy_name}，日期: {current_date}")
        
        # 执行选股
        selected_stocks = self._execute_selection(strategy_name, current_date)
        logger.info(f"选股完成，共选出 {len(selected_stocks)} 只股票")
        
        if not selected_stocks:
            return []
        
        # ========== 过滤停牌股票 ==========
        # 检查每只股票是否停牌，剔除当日停牌的股票
        active_stocks = []
        suspended_stocks = []
        for stock in selected_stocks:
            code = stock.get('stock_code', '')
            if self._is_stock_suspended(code, current_date):
                suspended_stocks.append(f"{code} {stock.get('stock_name', '')}")
                logger.debug(f"过滤停牌股票: {code} {stock.get('stock_name', '')}")
            else:
                active_stocks.append(stock)
        
        if suspended_stocks:
            logger.info(f"【停牌过滤】剔除 {len(suspended_stocks)} 只停牌股票: {', '.join(suspended_stocks[:5])}{'...' if len(suspended_stocks) > 5 else ''}")
        
        if not active_stocks:
            logger.warning(f"选股后全部股票均停牌，过滤后无可交易股票")
            return []
        
        logger.info(f"【停牌过滤】过滤后剩余 {len(active_stocks)} 只可交易股票")
        
        # 评分（仅对可交易股票评分）
        logger.info(f"开始对 {len(active_stocks)} 只可交易股票进行评分")
        scored_stocks = self._score_stocks(active_stocks, strategy_name, current_date)
        
        # 记录每只股票的综合评分（与回测引擎一致）
        logger.info("\n股票评分详情:")
        for stock in scored_stocks:
            logger.info(f"  - {stock['stock_code']} {stock['stock_name']}: 综合评分={stock['score']}，否决标志={stock.get('veto_flag', False)}")
        
        # 筛选：入池规则（与回测共用，见 trading/pool_entry_rules.py）
        from trading.pool_entry_rules import filter_candidates, resolve_pool_entry_simplified

        _simplified = resolve_pool_entry_simplified(
            getattr(self, 'config', None) or {}, self._load_engine_config())
        candidate_stocks = filter_candidates(scored_stocks, score_threshold, _simplified)
        logger.info("【入池规则】" + ("简化：只剔除一票否决"
                                     if _simplified else f"标准：评分>={score_threshold}"))
        
        logger.info(f"\n筛选后待买入股票数: {len(candidate_stocks)}")
        if candidate_stocks:
            logger.info("待买入股票列表:")
            for stock in candidate_stocks:
                logger.info(f"  - {stock['stock_code']} {stock['stock_name']}: 评分={stock['score']}")
        return candidate_stocks
    
    # ==================== 持仓股自动入池 ====================

    def _add_holdings_to_pool(self, positions, current_date, today_sold_stocks,
                              strategy_name: str = '', enabled: bool = True) -> int:
        """持仓股自动入池（**当日已卖出的不计**），返回新增数量

        目的：策略切换 / 候选被买入消费 / 池移除后，持仓股仍需留在候选池中，
              否则择时给出 add 信号时无法加仓（池空 → 加不进）。

        ⚠️ 实盘 2026-09-13 修复：`run_strategies_batch` 早已调用本方法，但方法漏了
        实现（只存在于回测引擎），导致每次都抛
        `AttributeError: 'StrategyRunner' object has no attribute '_add_holdings_to_pool'`，
        持仓股无法回池、加仓链路中断。现按 `BacktestEngine._add_holdings_to_pool`
        同一口径移植（回测与实盘一致）。

        Args:
            positions: 持仓。实盘为 `dict{code: {...}}`（键已归一化为纯数字代码）；
                       同时兼容回测的 `list[dict]`（含 stock_code/stock_name）
            current_date: 当日日期（str 或 date）
            today_sold_stocks: 当日已卖出代码集合（不计入池）
            strategy_name: 当日策略名（写入池条目，供 Kelly / 池移除配置查找）
            enabled: 开关（调用方由 pool_entry.auto_add_holdings 解析后传入）

        Returns:
            int: 新增入池数量
        """
        # 【2026-09-24】持仓回池**明细**载体 ✓（供飞书简报"股票池变动"一节使用）
        #   每次调用都重置 ✓ —— 避免上游未启用（enabled=False）时残留上一次的明细 ✗
        added_items = []
        self.last_holdings_pool_added_items = added_items

        if not enabled:
            return 0

        added = 0
        try:
            # 兼容 dict（实盘 self.portfolio）与 list（回测 positions）
            if isinstance(positions, dict):
                items = [{'stock_code': code,
                          'stock_name': (pos or {}).get('stock_name', '')}
                         for code, pos in positions.items()]
            else:
                items = list(positions or [])

            pool_codes = {c.get('stock', {}).get('stock_code')
                          for c in self.buy_candidate_pool}
            for pos in items:
                code = pos.get('stock_code')
                # 【2026-09-18】标准券/质押券等非股票品种不得回池（同 ETF 口径）：
                #   否则会被当作可买候选，出现在股票池/选股结果里
                _name = str(pos.get('stock_name') or '')
                if is_non_stock_instrument(code, _name):
                    logger.info(f"【持仓入池】跳过非股票品种 {code} {_name}"
                                f"（标准券/质押券不参与可买股票池）")
                    continue
                if (not code or code in pool_codes
                        or code in (today_sold_stocks or set())):
                    continue

                info = {'stock_code': code,
                        'stock_name': pos.get('stock_name', ''),
                        'score': 0,
                        'veto_flag': False}
                try:
                    # 注意：实盘与本方法的支撑位函数签名顺序为 (stock, strategy, date)
                    sup = self._calculate_support_level(info, strategy_name, current_date)
                    sup_method = self._get_support_method_for_strategy(strategy_name)
                except Exception as e:
                    sup, sup_method = 0.0, 'unknown'
                    logger.debug(f"持仓股 {code} 支撑位计算失败: {e}")

                self.buy_candidate_pool.append({
                    'stock': info,
                    'added_date': current_date,
                    'key_date': (current_date.strftime('%Y-%m-%d')
                                 if hasattr(current_date, 'strftime') else str(current_date)),
                    'strategy_name': strategy_name,
                    'support_level': sup,
                    'support_method': sup_method,
                    'from_holding': True,      # 标记来源：持仓股自动入池
                })
                pool_codes.add(code)
                added += 1
                added_items.append({
                    'code': code,
                    'name': pos.get('stock_name', '') or '',
                    'source': 'holding',          # 来源：持仓股回池（区别于选股入池 ✓）
                    'strategy': strategy_name,
                    'support_level': sup,
                    'support_method': sup_method,
                })

            if added:
                logger.info(f"【持仓入池】新增 {added} 只持仓股到股票池（当日卖出不计），"
                            f"池内合计 {len(self.buy_candidate_pool)} 只")
        except Exception as e:
            logger.warning(f"持仓股入池失败（不影响策略运行）: {e}")
        return added

    # ==================== 股票池移除检查 ====================
    
    def _calculate_support_level(self, stock: Dict, strategy_name: str, current_date: str) -> float:
        """计算候选股票的支撑位
        
        Args:
            stock: 股票信息
            strategy_name: 策略名称
            current_date: 当前日期
            
        Returns:
            支撑位价格
        """
        stock_code = stock['stock_code']
        support_method = self._get_support_method_for_strategy(strategy_name)
        
        df = self.stock_filtered_cache.get(stock_code)
        if df is None:
            return 0.0
        
        df_to_date = df[df['date'] <= current_date].copy()
        if df_to_date.empty:
            return 0.0
        
        if len(df_to_date) > 1 and df_to_date['date'].iloc[0] > df_to_date['date'].iloc[1]:
            df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)
        
        if support_method == 'ma20':
            if len(df_to_date) >= 20:
                return round(df_to_date['close'].tail(20).mean(), 2)
            
        elif support_method in ['key_close_5', 'key_open', 'key_close']:
            signal = stock.get('signal', {})
            key_date = signal.get('key_date') if isinstance(signal, dict) else None
            
            if key_date:
                key_date_str = str(key_date)[:10]
                key_date_data = df_to_date[df_to_date['date'].astype(str).str[:10] == key_date_str]
                
                if not key_date_data.empty:
                    if support_method == 'key_close_5':
                        return round(float(key_date_data.iloc[0]['close']) * 0.95, 2)
                    elif support_method == 'key_open':
                        return round(float(key_date_data.iloc[0]['open']), 2)
                    elif support_method == 'key_close':
                        return round(float(key_date_data.iloc[0]['close']), 2)
        
        # fallback: 使用20日均线
        if len(df_to_date) >= 20:
            return round(df_to_date['close'].tail(20).mean(), 2)
        
        return 0.0
    
    def _check_pool_removal(self, current_date: str, held_codes=None) -> List[Dict]:
        """检查股票池中需要移除的股票
        
        移除条件：
        1. 破支撑位：前一日收盘价 < 支撑位 × 0.98
        2. 不满足上升趋势条件（持有 min_hold_days 天后生效）
            - 收盘价 >= MA10
            - 20日线性回归斜率 > 0
            - 20日R²拟合度 >= 0.3
        3. 资金流向条件（同时满足以下两个条件时移除）：
            - 5日主力资金累计净流入 < -10000万元
            - 大单净流出 且 小单净流入（出货信号）
        
        Args:
            current_date: 当前交易日期
            
        Returns:
            移除的候选列表
        """
        from utils.trade_date_utils import get_previous_trading_day
        
        removed = []
        remaining = []

        # 持仓代码集合（缺省取当前实盘持仓）：**持仓中的候选一律不移除**
        if held_codes is None:
            held_codes = set((self.portfolio or {}).keys())
        else:
            held_codes = set(held_codes)
        
        # 获取前一个交易日
        prev_date = get_previous_trading_day(current_date)
        prev_date_str = prev_date.strftime('%Y-%m-%d') if isinstance(prev_date, datetime.datetime) else prev_date
        
        # 获取资金流向规则配置
        fund_flow_enabled = getattr(self, '_fund_flow_rules', {}).get('is_enabled', True)
        fund_flow_min_hold_days = getattr(self, '_fund_flow_rules', {}).get('min_hold_days', 1)
        
        for candidate in self.buy_candidate_pool:
            stock_code = candidate['stock']['stock_code']
            stock_name = candidate['stock']['stock_name']
            strategy_name = candidate.get('strategy_name', '')

            # ===== 持仓股不移除（2026-09-11）：持仓中的候选一律保留 =====
            if stock_code in held_codes:
                remaining.append(candidate)
                logger.info(f"【保留】{current_date} {stock_code} {stock_name}: "
                            f"当前持仓中，不参与移除判断")
                continue

            # ========== 更新过期冷却状态 ==========
            # 调用 _check_cool_down 更新冷却状态，如果冷却期已过期会自动重置
            self._check_cool_down(stock_code, current_date)
            # ========== 冷却状态更新结束 ==========
            
            # ========== 更新股票池现价（使用当日收盘价） ==========
            try:
                df_price = self.stock_filtered_cache.get(stock_code)
                if df_price is not None and not df_price.empty:
                    # 获取当日收盘价
                    price_row = df_price[df_price['date'] == current_date]
                    if not price_row.empty:
                        latest_price = float(price_row['close'].values[0])
                    else:
                        # 如果没有当日数据，取最新收盘价
                        latest_price = float(df_price['close'].values[0])
                    
                    # 更新股票信号中的价格
                    if 'signal' in candidate['stock']:
                        candidate['stock']['signal']['close'] = latest_price
                    elif 'close' in candidate['stock']:
                        candidate['stock']['close'] = latest_price
                    
                    logger.debug(f"【股票池】{stock_code} 现价更新为: {latest_price:.2f}")
            except Exception as e:
                logger.debug(f"【股票池】更新 {stock_code} 现价失败: {str(e)}")
            # ========== 股票池现价更新结束 ==========
            
            # 获取移除配置
            removal_config = self._get_strategy_removal_config(strategy_name)
            min_hold_days = removal_config.get('min_hold_days', 2)
            
            # 计算持有天数
            added_date = candidate.get('added_date', '')
            # 计算持有天数：从加入日期到今天（不含加入当天）
            # 例如：5月13日加入，5月14日检查，hold_days = 1
            if added_date:
                if isinstance(added_date, datetime.datetime):
                    added_date = added_date.strftime('%Y-%m-%d')
                try:
                    added_dt = datetime.datetime.strptime(added_date, '%Y-%m-%d')
                    if isinstance(current_date, datetime.datetime):
                        hold_days = (current_date - added_dt).days
                    else:
                        current_dt = datetime.datetime.strptime(current_date, '%Y-%m-%d')
                        hold_days = (current_dt - added_dt).days
                except:
                    hold_days = 0
            else:
                hold_days = 0
            
            # 获取股票数据
            df = self.stock_filtered_cache.get(stock_code)
            if df is None:
                # 老股票(>=min_hold_days)缓存无数据属异常，升级为 warning 让滞留可见；
                # 新股票数据尚未覆盖属正常，保持 debug
                if hold_days >= min_hold_days:
                    logger.warning(f"【股票池移除】{stock_code} {stock_name} 持有{hold_days}天但缓存无数据，"
                                   f"移除检查被跳过(可能预加载未覆盖)，请核查数据")
                else:
                    logger.debug(f"【股票池移除】{stock_code} {stock_name} 缓存无数据"
                                 f"(持有{hold_days}天<{min_hold_days})，跳过检查")
                remaining.append(candidate)
                continue
            
            # 破支撑位检查：使用当天收盘价（或最新可用收盘价）
            # 注意：缓存数据是正序排列的（最旧日期在前面），iloc[-1] 才是最新
            df_for_support = df[df['date'] <= current_date].copy()
            if len(df_for_support) < 20:
                # 老股票数据不足属异常，升级为 warning；新股票保持 debug
                if hold_days >= min_hold_days:
                    logger.warning(f"【股票池移除】{stock_code} {stock_name} 持有{hold_days}天但数据不足"
                                   f"{len(df_for_support)}天<20，支撑位检查被跳过，请核查数据")
                else:
                    logger.debug(f"【股票池移除】{stock_code} {stock_name} 数据不足"
                                 f"{len(df_for_support)}天<20，跳过检查")
                remaining.append(candidate)
                continue
            price_for_check = df_for_support.iloc[-1]['close']  # 正序数据，iloc[-1] 为最新
            
            # 趋势检查：需要至少20天历史数据
            trend_df = df_for_support.copy()
            if len(trend_df) < 20:
                remaining.append(candidate)
                continue
            
            # 确保数据按日期正序排列
            if trend_df['date'].iloc[0] > trend_df['date'].iloc[-1]:
                trend_df = trend_df.iloc[::-1].reset_index(drop=True)
            
            # 移除判断
            removal_reasons = []
            should_remove = False
            
            # 条件1: 破支撑位移除
            # 支撑位语义：ma20 方法使用"当前动态 MA20"(每日随行情刷新)，
            # 契合原设计"支撑位选入时确定、ma20 除外可变化"的约定；
            # 其余方法(key_close_5/key_open/key_close)保留加入时固定的 support_level
            support_method = candidate.get('support_method', 'unknown')
            if support_method == 'ma20' and len(df_for_support) >= 20:
                # 动态 MA20：取截至 current_date 最近20日收盘均值
                dynamic_ma20 = round(float(df_for_support['close'].tail(20).mean()), 2)
                # 刷新为动态支撑位，使移除判定与前端展示保持一致
                candidate['support_level'] = dynamic_ma20
                support_level = dynamic_ma20
            else:
                support_level = candidate.get('support_level', 0.0)
            if support_level > 0 and price_for_check > 0:
                if price_for_check < support_level * 0.98:
                    should_remove = True
                    drop_pct = (price_for_check - support_level) / support_level * 100
                    removal_reasons.append(f"跌破支撑位{support_level:.2f}{drop_pct:.1f}%")
            
            # 条件2: 趋势验证移除（需要至少20天数据）
            if hold_days >= min_hold_days and len(trend_df) >= 20:
                ma10 = trend_df['close'].tail(10).mean()
                prices = trend_df['close'].tail(20).values
                x = np.arange(len(prices))
                slope, _, r_value, _, _ = stats.linregress(x, prices)
                r_squared = r_value ** 2
                
                trend_ok = (price_for_check >= ma10 and slope > 0 and r_squared >= 0.3)
                
                if not trend_ok:
                    should_remove = True
                    if price_for_check < ma10:
                        removal_reasons.append(f"收盘价{price_for_check:.2f}<MA10{ma10:.2f}")
                    if slope <= 0:
                        removal_reasons.append(f"斜率{slope:.4f}<=0")
                    if r_squared < 0.3:
                        removal_reasons.append(f"R²{r_squared:.4f}<0.3")
            
            # 条件3: 资金流向移除（判定条件与「资金面一票否决」一致，两条件为 OR）
            # - 5日主力净额 < -1亿 且 大单净流入占比 < -5%（无占比字段→净额/成交额 < -1%）
            # - 出货信号：大单净流出占比 > 1% 且 小单净流入占比 > 1%
            fund_flow_reason = ''
            if fund_flow_enabled:
                if hold_days >= fund_flow_min_hold_days:
                    fund_flow_result = self._check_fund_flow_condition(stock_code, stock_name, current_date)
                    fund_flow_reason = fund_flow_result.get('reason', '')
                    if fund_flow_result['should_remove']:
                        should_remove = True
                        removal_reasons.append(fund_flow_result['reason'])
                else:
                    fund_flow_reason = f'持有{hold_days}天<{fund_flow_min_hold_days}天，跳过检查'
            
            if should_remove:
                # 【2026-09-24】把移除**原因/日期/收盘价/持有天数**挂到候选上 ✓
                #   原实现原因只写日志 ✗ → 简报与日报无法给出"移除整体情况 + 明细" ✗。
                #   安全说明：该候选随后即被移出 `buy_candidate_pool` ✓（下方 `self.buy_candidate_pool = remaining`），
                #   不会污染池数据、也不会被 `_save_pool_to_file` 持久化 ✓
                _reason_txt = '; '.join(removal_reasons)
                candidate['removed_reason'] = _reason_txt
                candidate['removed_date'] = current_date
                candidate['removed_price'] = round(float(price_for_check), 2)
                candidate['removed_hold_days'] = hold_days
                removed.append(candidate)
                logger.info(f"【移除】{current_date} {stock_code} {stock_name}: "
                           f"收盘={price_for_check:.2f}, 策略={strategy_name}, 持{hold_days}日, "
                           f"原因: {_reason_txt}")
            else:
                remaining.append(candidate)
                # 记录保留原因（用于调试）
                keep_reasons = []
                if support_level > 0:
                    if price_for_check >= support_level * 0.98:
                        keep_reasons.append(f'支撑位OK')
                    else:
                        keep_reasons.append(f'破支撑位但未移除')
                if hold_days < min_hold_days:
                    keep_reasons.append(f'持有{hold_days}<{min_hold_days}天，跳过趋势检查')
                elif len(trend_df) >= 20:
                    keep_reasons.append(f'趋势OK')
                else:
                    keep_reasons.append(f'数据不足{len(trend_df)}天<20，跳过趋势检查')
                if not fund_flow_reason:
                    keep_reasons.append(f'资金流向OK')
                logger.info(f"【保留】{stock_code} {stock_name}: 持{hold_days}日, {', '.join(keep_reasons)}")
        
        if removed:
            logger.info(f"股票池移除: {len(removed)} 只, 剩余: {len(remaining)} 只")
            self.buy_candidate_pool = remaining
        else:
            logger.info(f"股票池移除检查完成: 0 只移除, {len(remaining)} 只全部保留")
        
        return removed
    
    def _check_fund_flow_condition(self, stock_code: str, stock_name: str, current_date: str) -> Dict:
        """检查资金流向移除条件
        
        判定条件（与「资金面一票否决」完全一致，直接复用 MoneyflowScorer.check_veto）：
        - 条件1  5日主力净额 < -1亿 且 大单净流入占比 < -5%
                 （无占比字段时回退：净额/成交额 < -1%）
        - 条件2  出货信号：大单净流出占比 > 1% 且 小单净流入占比 > 1%
        - 两条件为 **OR**：任一满足即触发处理：
          - 如果股票不在冷却期 → 加入冷却期3天，不移除
          - 如果股票已经在冷却期(is_cooling=true) → 直接移除出股票池
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            current_date: 当前日期
            
        Returns:
            包含 should_remove 和 reason 的字典
        """
        from trading.moneyflow_scorer import MoneyflowScorer
        
        try:
            # 统一转换日期格式为字符串
            if hasattr(current_date, 'strftime'):
                # 如果是date对象，转换为字符串
                date_str = current_date.strftime('%Y%m%d')
            else:
                # 如果是字符串，移除横杠
                date_str = str(current_date).replace('-', '')
            
            # 使用资金评分器获取资金流向数据
            scorer = MoneyflowScorer()
            df = scorer._fetch_moneyflow_data(stock_code, date_str)
            
            if df is None or df.empty:
                return {'should_remove': False, 'reason': ''}
            
            # 提取指标后交由「资金面一票否决」同一套条件判定
            #   条件1  5日主力净额 < -1亿 且 大单净流入占比 < -5%（无占比字段→净额/成交额 < -1%）
            #   条件2  出货信号：大单净流出占比 > 1% 且 小单净流入占比 > 1%
            #   两条件为 OR 关系
            metrics = scorer._extract_flow_metrics(df)
            is_veto, reason_detail = scorer.check_veto(stock_code, date_str, metrics)

            if is_veto:
                # 检查是否已在冷却期（通过股票池的is_cooling字段）
                is_in_cool_down = self._check_cool_down(stock_code, current_date)
                
                if is_in_cool_down:
                    # 已在冷却期，再次触发条件，直接移除
                    reason = f"{stock_code} {stock_name}: 资金流向异常[{reason_detail}]，且已在冷却期，直接移除"
                    logger.warning(reason)
                    self._update_stock_cool_down_status(stock_code, False, None)
                    return {'should_remove': True, 'reason': reason}
                else:
                    # 不在冷却期，加入冷却期3天
                    cool_down_end = self._get_future_trading_day(current_date, 3)
                    self._update_stock_cool_down_status(stock_code, True, cool_down_end)
                    reason = f"{stock_code} {stock_name}: 资金流向异常[{reason_detail}]，加入冷却期至{cool_down_end}"
                    logger.warning(reason)
                    return {'should_remove': False, 'reason': reason}
            
            return {'should_remove': False, 'reason': ''}
            
        except Exception as e:
            logger.warning(f"检查资金流向条件失败: {stock_code} {stock_name}, {str(e)}")
            return {'should_remove': False, 'reason': ''}
    
    def _load_config(self) -> Dict:
        """加载策略运行配置
        
        优先使用数据库回测配置中的止盈止损参数，与回测引擎保持一致。
        如果数据库中没有配置，则使用默认值。
        
        Returns:
            配置字典
        """
        # 基础配置
        default_config = {
            'max_position_size': 0.1,
            'min_position_size': 0.01,
            'max_positions': 10,
            'selection_limit': 20,
            'min_score': 70,
            'working_hour': 9,
            'working_minute': 30,
            'check_interval': 60
        }
        
        # 项目根目录：基于当前文件绝对路径推导，不依赖进程 cwd
        # 重要：web_server 以服务/计划任务启动时 cwd 可能不是项目根目录，
        # 使用相对路径会导致 config 加载失败、run_mode 回退 manual，
        # 进而跳过 PTrade 同步（历史故障根因），因此必须使用绝对路径
        project_root = Path(__file__).resolve().parent.parent

        # 尝试从yaml文件加载（绝对路径优先）
        config_path = project_root / "config" / "strategy_params.yaml"
        if not config_path.exists():
            # 回退兼容：以项目根为 cwd 的旧部署方式
            config_path = Path("config/strategy_params.yaml")
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    runner_config = config.get('strategy_runner', {})
                    # 合并yaml配置到默认配置
                    default_config.update(runner_config)
                    logger.info("策略运行配置加载成功")
            except Exception as e:
                logger.error(f"加载策略运行配置失败: {str(e)}")
        
        # 加载运行模式配置（手动/自动）和 PTrade 配置（绝对路径优先）
        main_config_path = project_root / "config" / "config.yaml"
        if not main_config_path.exists():
            # 回退兼容：以项目根为 cwd 的旧部署方式
            main_config_path = Path("config/config.yaml")
        if main_config_path.exists():
            try:
                with open(main_config_path, 'r', encoding='utf-8') as f:
                    main_config = yaml.safe_load(f)
                    # 运行模式
                    run_mode_config = main_config.get('run_mode', {})
                    self.run_mode = run_mode_config.get('mode', 'manual')
                    # 打印配置来源与 PTrade 开关，便于排查"模式与预期不符"类问题
                    logger.info(
                        f"运行模式: {self.run_mode}（配置来源: {main_config_path}，"
                        f"ptrade.enabled="
                        f"{main_config.get('ptrade', {}).get('enabled', True)}）")
                    # 保存完整主配置供后续 PTrade 反馈处理等模块使用
                    self.main_config = main_config
            except Exception as e:
                logger.warning(f"加载运行模式配置失败，默认使用 manual 模式: {str(e)}")
                self.run_mode = 'manual'
                self.main_config = {}
        else:
            # config 缺失会导致 run_mode 回退 manual，进而跳过 PTrade 同步，
            # 属严重问题，必须用 WARNING 级告警便于排查
            self.run_mode = 'manual'
            self.main_config = {}
            logger.warning(
                f"config/config.yaml 不存在（已尝试绝对路径 "
                f"{project_root / 'config' / 'config.yaml'}），"
                f"默认使用 manual 模式，将跳过 PTrade 同步！")
        
        # 从数据库回测配置获取止盈止损参数（优先级最高）
        backtest_config = self._get_backtest_config()
        if backtest_config:
            # take_profit 和 stop_loss 使用百分比形式（如 21 表示 21%）
            # 转换为小数形式存储，与回测引擎保持一致
            default_config['take_profit_threshold'] = backtest_config.get('take_profit', 15) / 100
            default_config['stop_loss_threshold'] = backtest_config.get('stop_loss', -5) / 100
            logger.info(f"从回测配置获取止盈止损: take_profit={backtest_config.get('take_profit', 15)}%, stop_loss={backtest_config.get('stop_loss', -5)}%")
        
        return default_config
    
    @classmethod
    def _resolve_path(cls, path_str: str, fallback_dir: Path) -> Path:
        """解析路径：若为绝对路径直接使用，否则相对于 fallback_dir 拼接

        Args:
            path_str: 配置中的路径字符串（如 "D:/ptrade/output" 或 "data/running/to_ptrade"）
            fallback_dir: 当 path_str 为相对路径时的基准目录

        Returns:
            解析后的绝对路径 Path 对象
        """
        p = Path(path_str)
        if p.is_absolute():
            return p
        return fallback_dir / p

    # 默认配置参数（统一管理，避免硬编码分散在多处）
    _DEFAULT_CONFIG = {
        'initial_capital': 300000,
        'max_daily_buys': 8,
        'score_threshold': 60,
        'buy_amount': 100000,
        'stop_loss': -5,
        'take_profit': 15,
        'hold_period': 10,
        'support_level_method': 'ma20',
        'timing_strategy': 'support',
        'temp_limit_mode': 'both'
    }
    
    def _get_backtest_config(self) -> Dict:
        """获取回测配置
        
        从数据库获取最新的回测配置，用于策略运行的默认参数。
        与回测引擎保持一致，使用相同的配置源。
        如果数据库中没有配置，返回默认参数。
        
        Returns:
            回测配置字典，包含 initial_capital, max_daily_buys, score_threshold 等参数
        """
        try:
            backtest_dao = BacktestDAO()
            configs = backtest_dao.get_all_configs()
            
            if configs and len(configs) > 0:
                # 使用最新的配置
                db_config = configs[0]
                logger.info(f"获取到回测配置: config_name={db_config.get('config_name')}")
                # 合并配置：使用数据库值，不存在的使用默认值
                result = self._DEFAULT_CONFIG.copy()
                for key in result:
                    if db_config.get(key) is not None:
                        result[key] = db_config.get(key)
                return result
            else:
                logger.warning("未找到回测配置，使用默认参数")
                return self._DEFAULT_CONFIG.copy()
        except Exception as e:
            logger.error(f"获取回测配置失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return self._DEFAULT_CONFIG.copy()
    
    def _load_engine_config(self) -> Dict:
        """加载回测引擎行为配置（config/backtest_engine_config.yaml）
        
        与回测引擎共用同一配置文件，保证回测与实盘的开关（如涨停基因检测）语义一致。
        路径基于文件绝对路径推导，不依赖进程 cwd（避免服务启动时配置加载失败）；
        使用实例级缓存避免重复读取。
        
        Returns:
            引擎配置字典；文件缺失或读取失败时返回空字典，由调用方取默认值
        """
        if getattr(self, '_engine_config_cache', None) is not None:
            return self._engine_config_cache
        
        config_path = Path(__file__).resolve().parent.parent / "config" / "backtest_engine_config.yaml"
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    yaml_config = yaml.safe_load(f) or {}
                self._engine_config_cache = yaml_config
                logger.info(
                    f"加载回测引擎配置成功（{config_path}）: "
                    f"enable_limit_up_check="
                    f"{yaml_config.get('enable_limit_up_check', True)}")
                return yaml_config
            except Exception as e:
                logger.warning(f"加载回测引擎配置失败，使用默认值: {str(e)}")
        else:
            logger.warning(f"回测引擎配置文件不存在: {config_path}，使用默认值")
        
        self._engine_config_cache = {}
        return self._engine_config_cache
    
    # 买入执行方式默认配置（与回测引擎 BacktestEngine.DEFAULT_BUY_EXECUTION 保持一致，
    # 配置源共用 config/backtest_engine_config.yaml 的 buy_execution 节）
    DEFAULT_BUY_EXECUTION = {
        'mode': 'open',               # open=T日收盘价（原行为） | ma_limit=均线委托价
        'ma_period': 5,               # 委托价基准均线周期（5日线）
        'ma_source': 'close',         # 均线计算所用价格字段
        'slippage': 0.005,            # 滑点 0.5%（买入取不利方向，即更贵）
        'min_periods': 5,             # 均线有效所需最小样本数
    }
    
    def _resolve_buy_execution(self, stock_code: str, df_to_date, default_price: float) -> Dict:
        """解析实盘买入执行价（与回测共用 config/backtest_engine_config.yaml）
        
        两种模式（buy_execution.mode）：
          - open（默认）：T日收盘价，行为与改造前一致（后向兼容）
          - ma_limit    ：委托价 = 均线（默认MA5，截至T-1防前视）× (1 + 滑点)
        
        说明：实盘仅生成委托价，不模拟是否成交（实际成交以 PTrade 反馈为准）。
        
        Args:
            stock_code: 股票代码
            df_to_date: 截至T日的K线（倒序，最新在 index 0）
            default_price: 默认价格（T日收盘价），用于 open 模式与样本不足回退
            
        Returns:
            dict: {'price': 记账/委托价, 'order_price': 委托价, 'mode': 模式, 'reason': 说明}
        """
        cfg = dict(self.DEFAULT_BUY_EXECUTION)
        cfg.update((self._load_engine_config() or {}).get('buy_execution') or {})
        mode = cfg.get('mode', 'open')
        
        if mode != 'ma_limit':
            return {'price': default_price, 'order_price': default_price,
                    'mode': mode, 'reason': '收盘价模式（T日收盘价）'}
        
        ma_period = int(cfg.get('ma_period', 5))
        ma_source = cfg.get('ma_source', 'close')
        min_periods = int(cfg.get('min_periods', ma_period))
        slippage = float(cfg.get('slippage', 0.005))
        
        # 实盘基准：信号在 T 日盘后生成（T 日已收盘），五日线按【截至 T 日收盘】计算，
        # 含当日不构成前视。
        # 注意与回测不同：回测是 T-1 信号、T 日成交，必须剔除 T 日（ma_base=prev_day）防前视。
        ma_value = None
        if df_to_date is not None and len(df_to_date) > 0 and ma_source in df_to_date.columns:
            hist = pd.to_numeric(df_to_date[ma_source], errors='coerce').dropna()
            if len(hist) >= min_periods:
                ma_value = float(hist.iloc[:ma_period].mean())
        
        if ma_value is None or ma_value <= 0:
            return {'price': default_price, 'order_price': default_price,
                    'mode': mode, 'reason': '均线样本不足，回退T日收盘价'}
        
        # 买入滑点取不利方向（更贵）
        order_price = ma_value * (1.0 + slippage)
        return {'price': order_price, 'order_price': order_price,
                'mode': mode,
                'reason': f'MA{ma_period}={ma_value:.2f}，委托价={order_price:.2f}'
                          f'（滑点{slippage * 100:.1f}%）'}
    
    def _check_cool_down(self, stock_code: str, current_date: str) -> bool:
        """检查股票是否在冷却期内（从股票池的属性中检查）

        Args:
            stock_code: 股票代码
            current_date: 当前日期字符串
            
        Returns:
            True表示在冷却期内，False表示不在冷却期
        """
        # 遍历股票池，查找该股票
        for candidate in self.buy_candidate_pool:
            stock = candidate.get('stock', candidate)
            code = stock.get('stock_code', '')
            if code == stock_code:
                is_cooling = candidate.get('is_cooling', False)
                cool_down_end = candidate.get('cool_down_end', None)
                stock_name = stock.get('stock_name', code)
                
                if not is_cooling or not cool_down_end:
                    return False
                
                # 检查冷却是否过期
                try:
                    cool_down_end_date = datetime.datetime.strptime(cool_down_end, '%Y-%m-%d').date()
                    current_date_obj = datetime.datetime.strptime(current_date, '%Y-%m-%d').date()
                    
                    if current_date_obj <= cool_down_end_date:
                        return True
                    else:
                        # 冷却期结束，股票"出狱"，更新状态
                        candidate['is_cooling'] = False
                        candidate['cool_down_end'] = None
                        logger.info(f"【冷却期】{current_date} {stock_code} {stock_name}: 冷却期结束，股票出狱")
                        return False
                except Exception as e:
                    logger.debug(f"解析冷却结束日期失败: {cool_down_end}, {e}")
                    return False
        
        return False

    def _register_sell_cool_down(self, stock_code: str, profit_rate: float,
                                 trade_date: str) -> str:
        """卖出后登记冷却状态（与回测 BacktestEngine 同口径，2026-09-16 新规则）

        规则：
          1. 连续亏损达标（默认 2 次）→ 先登记超长冷却（默认 250 交易日 = 1 年）
          2. **任意清仓卖出** → 登记 cool_down_days（默认 21 交易日 = 1 个月）：
             盈利卖出同样冷却（cool_down_on_any_sell，默认 True；False 时回退"仅亏损"旧规则）。
             判定与回测**共用** should_register_sell_cool_down，避免两侧口径漂移。
          3. 已在冷却期不覆盖（避免 21 天覆盖连续亏损的 250 天）

        Args:
            stock_code: 股票代码
            profit_rate: 收益率（**小数**，如 0.05 = +5%；回测侧为百分数，此处内部换算）
            trade_date: 交易日 YYYY-MM-DD

        Returns:
            登记的冷却结束日期；未登记返回 ''
        """
        enable_loss_cool_down = self.config.get('enable_loss_cool_down', True)
        enable_consecutive_loss_limit = self.config.get(
            'enable_consecutive_loss_limit', True)
        cool_down_threshold = self.config.get('cool_down_threshold')      # None = 无门槛
        cool_down_days = self.config.get('cool_down_days', 21)            # 1 个月
        max_consecutive_losses = self.config.get('max_consecutive_losses', 2)
        consecutive_loss_cool_down = self.config.get('consecutive_loss_cool_down', 250)  # 1 年
        cool_down_on_any_sell = self.config.get('cool_down_on_any_sell', True)

        registered = ''
        # 1) 连续亏损计数与超长冷却
        if enable_consecutive_loss_limit:
            if profit_rate > 0:
                self.consecutive_loss_count[stock_code] = 0
            else:
                current_count = self.consecutive_loss_count.get(stock_code, 0) + 1
                self.consecutive_loss_count[stock_code] = current_count
                if current_count >= max_consecutive_losses:
                    cool_down_end = self._get_future_trading_day(
                        trade_date, consecutive_loss_cool_down)
                    self._update_stock_cool_down_status(stock_code, True, cool_down_end)
                    registered = cool_down_end
                    logger.warning(f"  股票 {stock_code} 连续亏损 {current_count} 次，"
                                   f"加入冷却池至 {cool_down_end}")
        # 2) 任意清仓卖出 → 冷却 1 个月（实盘生成的卖出信号一律为清仓）
        from trading.backtest_engine import should_register_sell_cool_down
        if enable_loss_cool_down and should_register_sell_cool_down(
                'sell', profit_rate * 100, cool_down_threshold, cool_down_on_any_sell):
            if not self._check_cool_down(stock_code, trade_date):
                cool_down_end = self._get_future_trading_day(trade_date, cool_down_days)
                self._update_stock_cool_down_status(stock_code, True, cool_down_end)
                registered = cool_down_end
                logger.warning(f"  股票 {stock_code} 清仓卖出"
                               f"（收益 {profit_rate * 100:.2f}%），"
                               f"加入冷却池 {cool_down_days} 个交易日至 {cool_down_end}")
        return registered

    def _update_stock_cool_down_status(self, stock_code: str, is_cooling: bool, cool_down_end: str = None):
        """更新股票池中的冷却状态
        
        Args:
            stock_code: 股票代码
            is_cooling: 是否在冷却期
            cool_down_end: 冷却结束日期（is_cooling=True时必填）
        """
        for candidate in self.buy_candidate_pool:
            # 与 _check_pool_removal 保持一致，直接从 candidate['stock']['stock_code'] 获取
            if candidate.get('stock', {}).get('stock_code', '') == stock_code:
                candidate['is_cooling'] = is_cooling
                candidate['cool_down_end'] = cool_down_end
                return

    def _calculate_hold_days(self, buy_date: str, current_date: str) -> int:
        """计算持有天数（交易日）
        
        Args:
            buy_date: 买入日期字符串 (YYYY-MM-DD)
            current_date: 当前日期字符串 (YYYY-MM-DD)
            
        Returns:
            持有天数（交易日数）
        """
        if not buy_date or not current_date:
            return 0
        try:
            from utils.trade_date_utils import get_trading_days
            trading_days = get_trading_days(buy_date, current_date)
            # 持有天数 = 交易日数量 - 1（买入当天不计入）
            return max(0, len(trading_days) - 1)
        except Exception as e:
            logger.debug(f"计算持有天数失败: {e}")
            # 回退到简单日历天数计算
            try:
                buy_dt = datetime.datetime.strptime(buy_date, '%Y-%m-%d').date()
                current_dt = datetime.datetime.strptime(current_date, '%Y-%m-%d').date()
                return max(0, (current_dt - buy_dt).days)
            except:
                return 0

    def _get_future_trading_day(self, start_date: str, days: int) -> str:
        """获取指定日期之后的第N个交易日
        
        Args:
            start_date: 起始日期字符串
            days: 往后多少个交易日
            
        Returns:
            目标交易日字符串
        """
        from utils.trade_date_utils import is_trading_day
        # 输入校验：防止非法日期导致 strptime 异常
        if not start_date or not isinstance(start_date, str):
            logger.warning(f"_get_future_trading_day 收到非法 start_date: {start_date}，使用当日兜底")
            start_date = datetime.date.today().strftime('%Y-%m-%d')
        if not isinstance(days, int) or days <= 0:
            logger.warning(f"_get_future_trading_day 收到非法 days: {days}，使用 1 兜底")
            days = 1
        
        current_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        trading_days_found = 0
        # 最大搜索范围：目标交易日数的 10 倍日历日（足够覆盖长假期）
        # 上限 365 天，防止死循环导致 date overflow
        max_calendar_days = min(days * 10, 365)
        
        for _ in range(max_calendar_days):
            current_date += datetime.timedelta(days=1)
            if is_trading_day(current_date.strftime('%Y-%m-%d')):
                trading_days_found += 1
                if trading_days_found >= days:
                    return current_date.strftime('%Y-%m-%d')
        
        # 兜底：搜索窗口内找不到足够交易日，直接用日历日推算
        logger.warning(f"_get_future_trading_day 在 {max_calendar_days} 天内未找到 {days} 个交易日，"
                       f"使用日历日兜底: {start_date} + {days * 7 // 5} 天")
        base_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        fallback_date = base_date + datetime.timedelta(days=max(days * 7 // 5, days))
        return fallback_date.strftime('%Y-%m-%d')
    
    def _has_kline_data(self, date: str) -> bool:
        """检查指定日期是否有K线数据
        
        Args:
            date: 日期字符串 (YYYY-MM-DD)
            
        Returns:
            True表示有K线数据，False表示没有
        """
        try:
            # 从数据库检查是否有当日K线数据
            from utils.db_manager import DBManager
            db_manager = DBManager()
            
            # 将日期格式转换为数据库存储的格式 (YYYY-MM-DD -> YYYYMMDD)
            date_db = date.replace('-', '')
            
            # 查询是否有当日的股票数据
            sql = f"""
                SELECT COUNT(*) FROM stock_kline 
                WHERE date = '{date_db}' 
                LIMIT 1
            """
            result = db_manager.query(sql)
            
            return result[0]['COUNT(*)'] > 0 if result else False
        except Exception as e:
            logger.warning(f"检查K线数据失败: {str(e)}")
            return False
    
    def get_working_date(self) -> str:
        """获取当前工作日期（进程级缓存，避免重复计算）
        
        判断逻辑（根据设计文档）：
        1. 如果当前是交易日 AND 当前时间 > 收盘时间(15:00): 处理日期 = 今日
        2. 如果当前是交易日 AND 当前时间 <= 收盘时间: 处理日期 = 昨日
        3. 否则（非交易日）: 处理日期 = 最近一个交易日
        
        Returns:
            工作日期字符串 (YYYY-MM-DD)
        """
        today = datetime.datetime.now()
        today_str = today.strftime('%Y-%m-%d')

        # 缓存仅在当日有效（跨日后或盘中→盘后切换时强制重新计算）
        if self._cached_working_date is not None and self._cached_working_date == today_str:
            return self._cached_working_date
        
        # 优先检查是否是交易日
        if is_trading_day(today_str):
            # 检查是否已收盘
            if is_market_closed():
                # 已收盘，使用今日
                logger.info(f"当日是交易日且已收盘，使用今日作为工作日期: {today_str}")
                self._cached_working_date = today_str
                return self._cached_working_date
            else:
                # 未收盘，使用前一交易日
                working_date = get_previous_trading_day(today_str)
                logger.info(f"当日是交易日但未收盘，使用前一交易日: {working_date}")
                self._cached_working_date = working_date
                return self._cached_working_date
        
        # 不是交易日，返回前一交易日
        working_date = get_previous_trading_day(today_str)
        logger.info(f"当日不是交易日，使用前一交易日: {working_date}")
        self._cached_working_date = working_date
        return self._cached_working_date
    
    def _get_working_date_for_test(self, date_str: str) -> str:
        """测试用方法：获取指定日期的工作日期"""
        if self._has_kline_data(date_str):
            return date_str
        return get_previous_trading_day(date_str)
    
    # PTrade 交易时间常量（与 TradingTimeValidator 保持一致）
    _TRADING_START_MINUTES = 9 * 60 + 30   # 9:30
    _TRADING_END_MINUTES = 15 * 60          # 15:00
    
    def _should_process_ptrade_feedback(self, force: bool = False) -> bool:
        """判断是否应该处理 PTrade 反馈文件

        时间策略（依据 get_working_date 确定的工作日）：
        - 盘前 / 盘中 / 非交易日：workding_date 为前一交易日，同步前一交易日反馈
        - 盘后：working_date 为当日，同步当日反馈
        本方法仅做运行模式与开关判断，具体读取哪一交易日由 get_working_date 决定。
        force=True 时绕过运行模式限制，用于前端查询兜底。

        Args:
            force: 是否强制处理（绕过运行模式判断，用于 API 查询兜底）

        Returns:
            是否应该处理 PTrade 反馈
        """
        # 仅自动模式处理（force 时跳过此限制，便于查询兜底）
        if not force and getattr(self, 'run_mode', 'manual') != 'auto':
            logger.info(f"【PTrade反馈】当前运行模式为 {getattr(self, 'run_mode', 'manual')}，跳过 PTrade 反馈处理")
            return False

        # 检查 ptrade.enabled 配置（始终尊重此开关）
        main_config = getattr(self, 'main_config', {})
        ptrade_cfg = main_config.get('ptrade', {}) if main_config else {}
        if not ptrade_cfg.get('enabled', True):
            logger.info("【PTrade反馈】ptrade.enabled=false，跳过反馈处理")
            return False

        # 运行模式与开关均满足，允许处理（具体读取前一交易日还是当日由 get_working_date 决定）
        logger.info("【PTrade反馈】运行模式与开关校验通过，允许处理反馈（工作日由 get_working_date 确定）")
        return True

    def sync_portfolio_from_ptrade(self, portfolio_date: str, force: bool = False) -> bool:
        """同步 PTrade 反馈到 portfolio 文件（供 API 查询时自动更新）

        时间策略由 get_working_date 决定读取哪个交易日（盘前/盘中/非交易日读前一交易日，
        盘后读当日）。当目标交易日反馈文件不存在时，记录告警并返回 False，终止加载，
        避免前端展示过期或错误数据。force=True 时绕过运行模式限制，用于前端查询兜底。

        Args:
            portfolio_date: 工作日期 YYYY-MM-DD
            force: 是否强制同步（绕过运行模式与时段判断）

        Returns:
            是否执行了 PTrade 同步
        """
        # 只自动模式 + ptrade enabled 时才同步（force 时允许兜底刷新）
        if not self._should_process_ptrade_feedback(force=force):
            logger.info(f"【PTrade同步】_should_process_ptrade_feedback 返回 False，"
                        f"run_mode={getattr(self, 'run_mode', 'N/A')}，跳过同步")
            return False

        # PTrade 反馈文件按交易日命名（如 20260626），需要将工作日期转为 YYYYMMDD
        working_date = self.get_working_date()
        feedback_date = working_date.replace("-", "")

        # 防重复同步：同一天只执行一次 PTrade 同步
        # 多个并发 API 请求可能同时触发此方法，避免重复处理
        if getattr(self, '_ptrade_synced_feedback_date', '') == feedback_date:
            logger.info(f"【PTrade同步】今日已同步过 feedback_date={feedback_date}，跳过重复调用")
            return True

        try:
            # 创建临时 handler 检查文件
            # running_dir 是 {project_root}/data/running，取 parent.parent 得到项目根目录
            project_root = str(self.running_dir.parent.parent)
            temp_handler = PTradeFeedbackHandler(
                project_root=project_root,
                config=getattr(self, 'main_config', None))
            # 检查 PTrade 反馈文件是否存在
            if not temp_handler.check_feedback_exists(feedback_date):
                # 打印实际检查的路径，方便排查；明确告警用户并终止加载
                fund_path = os.path.join(temp_handler.feedback_dir, f"Fund_{feedback_date}.csv")
                hold_path = os.path.join(temp_handler.feedback_dir, f"Hold_{feedback_date}.csv")
                logger.error(
                    f"【PTrade同步-终止加载】未找到交易日 {feedback_date} 的 PTrade 反馈文件！"
                    f"feedback_dir={temp_handler.feedback_dir}，"
                    f"Fund存在={os.path.isfile(fund_path)}，Hold存在={os.path.isfile(hold_path)}。"
                    f"请确认 PTrade 已导出当日（或前一交易日）反馈文件后重试。")
                return False
            # 自动模式下 PTrade 数据是唯一真实数据源，始终处理（不依赖 mtime 比较）
            # mtime 比较可能因 initialize_daily_data 保存操作更新文件时间而误判跳过
            logger.info(
                f"【PTrade同步】检测到 PTrade 反馈文件，同步 portfolio: "
                f"feedback_date={feedback_date}")
            result = temp_handler.process(feedback_date)
            if result.get("success"):
                # 同步成功后，更新内存中的 self.portfolio
                # PTrade 数据完全覆盖本地持仓，确保自动模式下持仓数据与实盘一致
                ptrade_portfolio = result.get('portfolio', {})
                new_positions = ptrade_portfolio.get('positions', {})
                # 合并旧 portfolio 中的追踪字段（PTrade Hold CSV 不包含这些字段）
                # add_count 丢失会导致已加仓股票被误判为首次加仓，加仓数量计算错误
                # self.portfolio 此时可能为空，需从上一个交易日 portfolio 文件加载旧数据
                # 依据 PTrade 反馈数量与前一日本地数量差推导加仓次数（当天只算一次）
                prev_portfolio = self._load_previous_portfolio_for_merge(portfolio_date)
                working_date = self.get_working_date()
                # 加载持久化追踪账本，作为 add_count 等字段的权威累积基准
                position_tracking = self._load_position_tracking()
                # 以账本为基准推导加仓次数，结果同时写回 new_positions 与账本
                self._reconcile_tracking_from_ptrade(prev_portfolio, new_positions, working_date, position_tracking)
                # 持久化账本，确保跨 PTrade 同步不丢失追踪字段
                self._save_position_tracking(position_tracking)
                self.portfolio = self._normalize_portfolio_keys(new_positions)
                self.current_total_capital = ptrade_portfolio.get('cash', getattr(self, 'current_total_capital', 300000))
                # 记录同步时刻的可用资金快照（= portfolio['cash']，与策略口径统一）：
                # 展示层复用本快照时，数值与「总资产 − 股票市值 − ETF市值」完全一致。
                # 注意：不要改用 Fund「可用资金」列——该列清算前会扣除未成交委托冻结
                # 资金、低于真实可用余额（2026-09-15 实盘：27425.82 vs 141472.44）
                self.current_ptrade_available_cash = ptrade_portfolio.get(
                    'available_cash', getattr(self, 'current_ptrade_available_cash', None))
                # 记录 PTrade 反馈的真实总资产（含 ETF 市值），供飞书通知等场景直接读取权威值，
                # 避免用「可用现金 + 持仓市值」反算时漏算 ETF（KHunter 持仓不含 ETF 但总资产含 ETF）
                self.current_total_asset = ptrade_portfolio.get('total_asset', getattr(self, 'current_total_asset', None))
                self.initial_capital = ptrade_portfolio.get('initial_capital', getattr(self, 'initial_capital', 300000))
                # 标记已同步，防止同一天重复处理
                self._ptrade_synced_feedback_date = feedback_date
                # 记录反馈目录与文件指纹：供前端展示层判断内存快照是否仍然新鲜
                # （mtime 变化说明 PTrade 重新导出过，展示层应回退直读文件）
                self._ptrade_feedback_dir = getattr(temp_handler, 'feedback_dir', None)
                self._ptrade_feedback_stamp = feedback_files_stamp(
                    self._ptrade_feedback_dir, feedback_date)
                logger.info(
                    f"【PTrade同步】portfolio 已从 PTrade 更新: "
                    f"持仓={len(result.get('holdings', []))} 条, "
                    f"现金={ptrade_portfolio.get('cash')}, "
                    f"总资产={ptrade_portfolio.get('total_asset')}")
                return True
            else:
                logger.warning(
                    f"【PTrade同步】处理失败: {result.get('error')}")
                return False
        except Exception as e:
            # 同步异常（如反馈文件读取失败）被安全捕获，返回 False 避免中断流程；
            # 异常信息含类型便于排查（如 PTrade 文件被占用导致的瞬时错误）
            logger.warning(f"【PTrade同步】同步异常: {type(e).__name__}: {str(e)}")
            return False

    def check_if_processed(self, date: str) -> bool:
        """检查指定日期是否已处理
        
        Args:
            date: 日期字符串 (YYYY-MM-DD)
            
        Returns:
            是否已处理
        """
        # 检查每日报告文件是否存在（兼容 .json 和 .md 格式）
        # 每日报告是策略执行完成的最终标志
        daily_file_json = self.running_dir / f"daily_{date}.json"
        daily_file_md = self.running_dir / f"daily_{date}.md"
        if daily_file_json.exists() or daily_file_md.exists():
            return True
        
        # 检查信号文件是否存在且包含策略生成的信号（排除手动信号）
        signals_file = self.running_dir / f"signals_{date}.json"
        if signals_file.exists():
            try:
                with open(signals_file, 'r', encoding='utf-8') as f:
                    signals_data = json.load(f)
                    # 如果信号数组不为空，检查是否包含策略生成的信号
                    if isinstance(signals_data, list) and len(signals_data) > 0:
                        # 判断是否存在非手动的信号（策略生成的信号）
                        has_strategy_signal = False
                        for signal in signals_data:
                            sell_type = signal.get('sell_type', '')
                            timing_strategy = signal.get('timing_strategy', '')
                            # 手动信号标记为 sell_type='manual' 或 timing_strategy='manual'
                            if sell_type != 'manual' and timing_strategy != 'manual':
                                has_strategy_signal = True
                                break
                        if has_strategy_signal:
                            return True
            except Exception:
                pass
        
        return False
    
    def initialize_daily_data(self, date: str = None) -> bool:
        """初始化当日数据
        
        当检测到新的交易日时，自动从前一交易日继承持仓数据来初始化当日数据。
        如果当日数据文件已存在，则跳过初始化。
        如果前一交易日没有数据，则继续向前查找更早的交易日，直到找到有数据的那天。
        
        Args:
            date: 日期字符串 (YYYY-MM-DD)，默认为当前工作日期
            
        Returns:
            是否成功初始化
        """
        # 如果未指定日期，使用当前工作日期
        if date is None:
            date = self.get_working_date()
        
        logger.info(f"【数据初始化】开始检查并初始化 {date} 的数据")
        
        # 检查是否已经初始化过（以工作日期判断，避免同一天重复初始化）
        if date in self._initialized_dates:
            logger.info(f"【数据初始化】{date} 已经初始化过，数据已在内存中，无需重复初始化")
            return True  # 已初始化，数据就绪，上层不应误判为失败
        # 立即标记为已初始化，防止并发 API 请求重复触发
        self._initialized_dates.add(date)
        
        # 所有文件以工作日期（交易日）命名
        portfolio_file = self.running_dir / f"portfolio_{date}.json"
        signals_file = self.running_dir / f"signals_{date}.json"
        trades_file = self.running_dir / f"trades_{date}.json"
        
        # ========== 统一入口：优先从 PTrade 同步真实持仓 ==========
        # PTrade 数据已是除权后信息，无需执行除权检测
        ptrade_synced = self.sync_portfolio_from_ptrade(date)
        
        if ptrade_synced:
            # PTrade 同步成功，portfolio 文件已由 sync_portfolio_from_ptrade 写入
            # 标记数据来源为 PTrade，供日志追溯与写盘防护判断使用
            self._portfolio_source = 'ptrade'
            logger.info(f"【数据初始化】{date} 数据从 PTrade 反馈同步完成")
            # 创建空的信号文件（如果不存在）
            if not signals_file.exists():
                self._save_signals([], str(signals_file))
            # 创建空的交易记录文件（如果不存在）
            if not trades_file.exists():
                with open(trades_file, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
            logger.info(f"【数据初始化】{date} 的数据初始化完成（PTrade 来源）")
            return True
        
        # ========== PTrade 同步失败，按运行模式分流 ==========
        if getattr(self, 'run_mode', 'manual') == 'auto':
            # 自动模式下 PTrade 是唯一数据源，同步失败直接报错，禁止任何回退
            logger.error(
                f"【数据初始化】{date} 自动模式下 PTrade 反馈文件不存在或同步失败，"
                f"禁止加载本地缓存。请检查 PTrade 反馈文件是否已生成。"
                f"预期路径: data/running/ptrade_feedback/Fund_{date.replace('-', '')}.csv 和 "
                f"Hold_{date.replace('-', '')}.csv")
            # 撤销入口处标记的"已初始化"：同步失败必须允许后续重试，
            # 否则守卫会让后续调用直接返回 True，使上层把 init_success 误判为成功，
            # 从而绕过自动模式的终止保护（历史故障被放大的关键原因）
            self._initialized_dates.discard(date)
            return False
        
        # ========== 非自动模式：本地文件或历史继承 ==========
        if portfolio_file.exists():
            logger.info(f"【数据初始化】{date} 的持仓文件已存在，从本地加载")
            # 标记数据来源为本地文件（非 PTrade），便于日志追溯
            self._portfolio_source = 'local'
            prev_data = self._load_portfolio(str(portfolio_file))
            self.portfolio = self._normalize_portfolio_keys(prev_data.get('positions', {}))
            self.current_total_capital = prev_data.get('cash', 300000)
            self.initial_capital = prev_data.get('initial_capital', 300000)
            return False
        
        # ========== 非自动模式：文件不存在，继承历史数据 ==========
        # 查找有数据的最近交易日 -> 继承历史数据
        # 标记数据来源为本地历史继承（非 PTrade），便于日志追溯
        self._portfolio_source = 'local(inherited)'
        prev_portfolio_path, found_date, days_between = self.find_latest_portfolio_file(date, max_days=30)
        
        if prev_portfolio_path and found_date:
            logger.info(f"【数据初始化】{date} 的持仓文件不存在，从最近有数据的交易日 {found_date} 继承数据（间隔 {days_between} 个交易日）")
            
            # 加载找到的交易日的持仓数据
            prev_data = self._load_portfolio(prev_portfolio_path)
            prev_positions = prev_data.get('positions', {})
            prev_cash = prev_data.get('cash', 300000)
            prev_initial_capital = prev_data.get('initial_capital', 300000)
            
            # 更新持仓的持有天数和现价（加上间隔的交易日数）
            updated_positions = {}
            for code, pos in prev_positions.items():
                updated_pos = pos.copy()
                updated_pos['holding_days'] = pos.get('holding_days', 0) + days_between
                
                # 获取最新价格并更新现价和收益
                # date 已是 get_working_date() 计算的工作日（已处理盘中/非交易日逻辑）
                # 走本地DB避免远程API超时
                try:
                    df = self._get_stock_data_from_db(code, date, date)
                    if df is not None and not df.empty:
                        latest_price = df.iloc[0]['close']
                        updated_pos['current_price'] = latest_price
                        # 计算收益
                        buy_price = pos.get('buy_price', pos.get('cost_price', 0))
                        if buy_price > 0:
                            profit_rate = (latest_price - buy_price) / buy_price
                            profit_loss = profit_rate * pos.get('quantity', 0) * buy_price
                            updated_pos['profit_rate'] = profit_rate
                            updated_pos['profit_loss'] = profit_loss
                        else:
                            updated_pos['profit_rate'] = 0.0
                            updated_pos['profit_loss'] = 0.0
                    else:
                        # 工作日DB无数据，保持原有现价
                        updated_pos['profit_rate'] = 0.0
                        updated_pos['profit_loss'] = 0.0
                except Exception as e:
                    logger.warning(f"【数据初始化】更新持仓 {code} 现价失败: {str(e)}")
                    updated_pos['profit_rate'] = 0.0
                    updated_pos['profit_loss'] = 0.0
                
                updated_positions[code] = updated_pos
            
            # 保存当日持仓文件
            self.current_total_capital = prev_cash
            self.initial_capital = prev_initial_capital
            
            # 计算总资产（可用资金 + 持仓市值）
            total_assets = prev_cash
            for code, pos in updated_positions.items():
                # 使用持仓中的当前价格
                position_price = pos.get('current_price', pos.get('buy_price', 0))
                total_assets += pos.get('quantity', 0) * position_price
            self.current_total_assets = total_assets
            
            # 设置当前持仓（用于后续除权检测）
            self.portfolio = updated_positions
            
            # ========== 除权检测：继承数据时检查期间是否有除权 ==========
            # 如果间隔多个交易日，需要检测期间的除权
            if days_between > 0:
                logger.info(f"【数据初始化】检测 {found_date} 到 {date} 期间的除权...")
                # 从 date 开始，向后遍历到 found_date 的下一个交易日
                # 例如：found_date=2026-05-30, date=2026-06-02, days_between=3
                # 需要检测：2026-06-02, 2026-06-01, 2026-05-31
                check_date = date
                for _ in range(days_between):
                    if self._check_portfolio_exdividend(check_date):
                        logger.info(f"【数据初始化】检测到 {check_date} 的除权，已调整持仓")
                    check_date = get_previous_trading_day(check_date)
                
                # 更新后的持仓
                updated_positions = self.portfolio
            
            self._save_portfolio(updated_positions, str(portfolio_file))
            logger.info(f"【数据初始化】成功从 {found_date} 继承持仓数据，共 {len(updated_positions)} 只股票，总资产: ¥{total_assets:.2f}")
        else:
            # 找不到有数据的交易日，使用初始资金初始化
            self.current_total_capital = self.config.get('initial_capital', 300000)
            self.initial_capital = self.current_total_capital
            self._save_portfolio({}, str(portfolio_file))
            logger.info(f"【数据初始化】未找到有数据的历史交易日，使用初始资金 {self.current_total_capital} 初始化")
        
        # 创建空的信号文件（如果不存在）
        if not signals_file.exists():
            self._save_signals([], str(signals_file))
            logger.info(f"【数据初始化】创建空信号文件: {signals_file}")
        
        # 创建空的交易记录文件（如果不存在）
        if not trades_file.exists():
            with open(trades_file, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            logger.info(f"【数据初始化】创建空交易记录文件: {trades_file}")
        
        # 已在方法入口处标记为已初始化，无需重复标记
        
        logger.info(f"【数据初始化】{date} 的数据初始化完成（历史继承）")
        return True
    
    def find_latest_portfolio_file(self, start_date: str = None, max_days: int = 30):
        """从指定日期向前查找最近有 portfolio 文件的交易日
        
        Args:
            start_date: 起始查找日期（YYYY-MM-DD），默认当天
            max_days: 最大向前查找交易日数
            
        Returns:
            (portfolio_file_path, found_date_str, trading_days_gap) 
            或 (None, None, 0) 如果找不到
        """
        if start_date is None:
            start_date = datetime.datetime.now().strftime('%Y-%m-%d')
        
        # 优先检查 start_date 本身
        portfolio_file = self.running_dir / f"portfolio_{start_date}.json"
        if portfolio_file.exists():
            return str(portfolio_file), start_date, 0
        
        # 向前查找最多 max_days 个交易日
        current_date = start_date
        for days_looked in range(1, max_days + 1):
            current_date = get_previous_trading_day(current_date)
            portfolio_file = self.running_dir / f"portfolio_{current_date}.json"
            if portfolio_file.exists():
                return str(portfolio_file), current_date, days_looked
        
        return None, None, 0
    
    def _load_portfolio(self, portfolio_file: str) -> Dict:
        """加载持仓信息
        
        Args:
            portfolio_file: 持仓文件路径
            
        Returns:
            包含 cash 和 positions 的字典
        """
        try:
            if not Path(portfolio_file).exists():
                return {'cash': 300000, 'positions': {}}
            with open(portfolio_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                cash = data.get('cash', 300000)
                initial_capital = data.get('initial_capital', 300000)
                positions = data.get('positions', {})
                # 恢复可用资金和初始资金
                self.current_total_capital = cash
                self.initial_capital = initial_capital
                return {'cash': cash, 'initial_capital': initial_capital, 'positions': positions}
        except Exception as e:
            logger.warning(f"加载持仓文件失败: {str(e)}")
            return {'cash': 300000, 'positions': {}}
    
    def _load_previous_portfolio_for_merge(self, current_date: str) -> Dict:
        """加载上一个交易日 portfolio 文件中的持仓数据，用于合并追踪字段
        
        PTrade 反馈同步时会完全覆盖 portfolio，add_count 等字段会丢失。
        需要从上一个交易日的 portfolio 文件中恢复这些字段。
        
        Args:
            current_date: 当前日期 YYYY-MM-DD
            
        Returns:
            上一交易日持仓字典 {stock_code: {...}}，找不到时返回 {}
        """
        try:
            prev_date = get_previous_trading_day(current_date)
            prev_file = self.running_dir / f"portfolio_{prev_date}.json"
            if not prev_file.exists():
                logger.debug(f"【合并追踪】上一交易日 portfolio 不存在: {prev_file}，跳过合并")
                return {}
            with open(prev_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            positions = data.get('positions', {})
            logger.info(f"【合并追踪】从 {prev_date} 加载旧持仓: {len(positions)} 条")
            return positions
        except Exception as e:
            logger.warning(f"【合并追踪】加载上一交易日 portfolio 失败: {e}")
            return {}

    def _load_position_tracking(self) -> Dict:
        """加载持仓追踪账本（持久化加仓追踪字段的权威来源）

        账本独立于每日 portfolio 文件，避免 PTrade 同步重建持仓时丢失 add_count 等字段。
        文件不存在或异常时返回空字典，由 reconcile 逻辑回退到 prev_portfolio 数量差初始化。
        账本与 portfolio 同目录（self.running_dir），随运行数据一起管理。

        Returns:
            持仓追踪字典 {stock_code: {quantity, add_count, first_buy_date, buy_date,
            last_add_date, last_add_price, last_updated}}
        """
        # 账本路径与 portfolio 同目录，集中管理运行期数据
        tracking_file = self.running_dir / "position_tracking.json"
        # 文件不存在时返回空字典，不阻断同步主流程
        if not tracking_file.exists():
            logger.debug(f"【持仓追踪】账本不存在: {tracking_file}，返回空")
            return {}
        try:
            with open(tracking_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"【持仓追踪】已加载账本: {len(data)} 条")
            return data
        except Exception as e:
            # 账本损坏不应中断主流程，回退为空字典
            logger.warning(f"【持仓追踪】加载账本失败: {e}，返回空")
            return {}

    def _save_position_tracking(self, tracking: Dict) -> None:
        """持久化持仓追踪账本到 JSON 文件

        将 add_count 等追踪字段落盘，作为跨 PTrade 同步的权威来源，
        彻底解耦于 PTrade 重建逻辑。

        Args:
            tracking: 持仓追踪字典 {stock_code: {...}}
        """
        # 账本与 portfolio 同目录，集中管理运行期数据
        tracking_file = self.running_dir / "position_tracking.json"
        try:
            with open(tracking_file, 'w', encoding='utf-8') as f:
                json.dump(tracking, f, ensure_ascii=False, indent=2)
            logger.info(f"【持仓追踪】账本已保存: {len(tracking)} 条 -> {tracking_file}")
        except Exception as e:
            # 账本保存失败仅告警，不影响当日 portfolio 同步结果
            logger.warning(f"【持仓追踪】保存账本失败: {e}")

    def _sync_tracking_on_add(self, stock_code: str, position: Dict, add_date: str, add_price: float) -> None:
        """加仓执行后同步更新持久化追踪账本

        本地或 PTrade 加仓成交后，将加仓计数与事实写入账本并落盘，
        作为跨 PTrade 同步的权威来源，避免 add_count 被重建持仓覆盖丢失。

        Args:
            stock_code: 股票代码（纯数字）
            position: 更新后的持仓字典（含最新 quantity/add_count）
            add_date: 加仓日期 YYYY-MM-DD
            add_price: 加仓价格
        """
        # 加载现有账本，保留其他股票的追踪记录
        tracking = self._load_position_tracking()
        # 合并当前股票的历史基准（首次建仓日等）
        prev = tracking.get(stock_code, {})
        tracking[stock_code] = {
            'quantity': position.get('quantity', 0),
            'add_count': position.get('add_count', 0),
            'first_buy_date': prev.get('first_buy_date', position.get('buy_date')),
            'buy_date': position.get('buy_date', add_date),
            'last_add_date': add_date,
            'last_add_price': add_price,
            'last_updated': add_date,
        }
        # 落盘账本，保证加仓事实持久化
        self._save_position_tracking(tracking)

    @staticmethod
    def _reconcile_tracking_from_ptrade(prev_portfolio: Dict, new_positions: Dict,
                                        working_date: str, tracking: Dict):
        """依据 PTrade 反馈数量与基准（账本优先，回退上一交易日）数量差值推导加仓次数。

        以持久化账本 tracking 为权威累积基准，替代脆弱的"上一交易日文件 add_count"链，
        避免首次加仓当天文件缺字段导致链条永久断裂。账本缺失时回退 prev_portfolio 数量差。
        推导结果同步写回 new_positions 与 tracking。

        规则（账本优先，回退上一交易日 portfolio 文件）：
          - 基准无持仓(base_qty==0) → 全新建仓，add_count=0；
          - 反馈数量>基准数量 → 当日加仓一次，add_count=基准+1；
          - 反馈数量<=基准数量 → 未加仓/减仓，保留基准计数与追踪字段。

        Args:
            prev_portfolio: 上一交易日 portfolio 文件中的旧持仓 {code: {...}}
            new_positions: PTrade 构建的新持仓（原地修改，目标）
            working_date: 当前工作日 YYYY-MM-DD（用于记录 last_add_date）
            tracking: 持久化持仓追踪账本（原地修改，权威基准与输出）
        """
        # 遍历 PTrade 返回的每只持仓，按数量差推导加仓计数
        for new_code, new_pos in new_positions.items():
            # 统一去除 PTrade 可能带的后缀，保证与账本/池代码一致
            clean_code = new_code.replace('.SZ', '').replace('.SH', '')
            # 优先以持久化账本为权威基准（跨同步不丢失）
            track_pos = tracking.get(clean_code) or tracking.get(new_code)
            # 回退基准：上一交易日 portfolio 文件
            prev_pos = prev_portfolio.get(new_code) or prev_portfolio.get(clean_code)

            # 提取基准数量、计数与追踪字段（账本优先）
            if track_pos:
                base_qty = track_pos.get('quantity', 0)
                base_count = track_pos.get('add_count', 0)
                base_first_buy = track_pos.get('first_buy_date')
                base_buy_date = track_pos.get('buy_date')
                base_last_add_date = track_pos.get('last_add_date')
                base_last_add_price = track_pos.get('last_add_price')
                has_base = True
            elif prev_pos:
                base_qty = prev_pos.get('quantity', 0)
                base_count = prev_pos.get('add_count', 0)
                base_first_buy = prev_pos.get('first_buy_date', prev_pos.get('buy_date'))
                base_buy_date = prev_pos.get('buy_date')
                base_last_add_date = prev_pos.get('last_add_date')
                base_last_add_price = prev_pos.get('last_add_price')
                has_base = True
            else:
                has_base = False

            # 无基准记录 → 视为全新建仓，初始化账本
            if not has_base:
                new_pos['add_count'] = 0
                tracking[clean_code] = {
                    'quantity': new_pos.get('quantity', 0),
                    'add_count': 0,
                    'first_buy_date': new_pos.get('buy_date'),
                    'buy_date': new_pos.get('buy_date'),
                    'last_add_date': None,
                    'last_add_price': None,
                    'last_updated': working_date,
                }
                continue

            # 基准数量为 0 → 视为建仓，不计入加仓次数
            if base_qty == 0:
                new_pos['add_count'] = 0
                tracking[clean_code] = {
                    'quantity': new_pos.get('quantity', 0),
                    'add_count': 0,
                    'first_buy_date': new_pos.get('buy_date'),
                    'buy_date': new_pos.get('buy_date'),
                    'last_add_date': None,
                    'last_add_price': None,
                    'last_updated': working_date,
                }
                logger.info(f"【PTrade同步】{new_pos.get('stock_name', new_code)} 前无持仓，判定为建仓，add_count=0")
                continue

            # 用账本记录的首次买入日覆盖 PTrade 同步日（build_portfolio 无建仓日期
            # 字段，会把 buy_date 硬编码为同步日），保证移动止损"买入以来最高价"
            # 的区间从真实建仓日开始计算，而非被截断为"同步日以来"
            if base_first_buy:
                new_pos['buy_date'] = base_first_buy

            # 反馈数量 > 基准数量 → 当日加仓，计数 +1（当天只算一次）
            new_qty = new_pos.get('quantity', 0)
            if new_qty > base_qty:
                new_count = base_count + 1
                new_pos['add_count'] = new_count
                new_pos['last_add_date'] = working_date
                new_pos['last_add_price'] = new_pos.get('cost_price', new_pos.get('buy_price'))
                tracking[clean_code] = {
                    'quantity': new_qty,
                    'add_count': new_count,
                    'first_buy_date': base_first_buy,
                    'buy_date': working_date,
                    'last_add_date': working_date,
                    'last_add_price': new_pos.get('last_add_price'),
                    'last_updated': working_date,
                }
                logger.info(f"【PTrade同步】{new_pos.get('stock_name', new_code)}({new_code}) 当日加仓："
                           f"基准{base_qty}→反馈{new_qty}，add_count={base_count}→{new_count}")
            else:
                # 数量未增加（未加仓或减仓/卖出），保留基准计数与追踪字段
                new_pos['add_count'] = base_count
                new_pos['last_add_date'] = base_last_add_date
                new_pos['last_add_price'] = base_last_add_price
                tracking[clean_code] = {
                    'quantity': new_qty,
                    'add_count': base_count,
                    'first_buy_date': base_first_buy,
                    'buy_date': base_buy_date,
                    'last_add_date': base_last_add_date,
                    'last_add_price': base_last_add_price,
                    'last_updated': working_date,
                }

        # 清理已清仓股票的追踪记录：加仓信息只针对有持仓的股票，
        # 实盘已无持仓（不在本次 PTrade 反馈中）则账本不保留，避免残留计数
        # 导致该股票重新建仓时被误判为"未加仓/沿用旧计数"
        present_codes = set()
        for code in new_positions:
            # 同时纳入原始代码与去后缀代码，确保带 .SZ/.SH 后缀的反馈也能匹配
            present_codes.add(code)
            present_codes.add(code.replace('.SZ', '').replace('.SH', ''))
        for code in [c for c in tracking if c not in present_codes]:
            logger.info(f"【PTrade同步】{code} 实盘已无持仓，清除追踪账本记录")
            del tracking[code]

        # 兜底：确保每只持仓都携带 first_buy_date 字段，供移动止损"买入以来最高价"
        # 直接使用，避免每日检查（仅 load_portfolio、不重新 reconcile）时 buy_date 仍
        # 为 PTrade 同步日导致区间被截断。缺失时回退到 buy_date
        for _pos in new_positions.values():
            if not _pos.get('first_buy_date'):
                _pos['first_buy_date'] = _pos.get('buy_date')

    @staticmethod
    def _normalize_portfolio_keys(positions: Dict) -> Dict:
        """标准化持仓字典的股票代码键名，去掉 PTrade 带来的 .SZ/.SH 后缀
        
        PTrade 反馈数据使用带交易所后缀的代码（如 002179.SZ），但系统内部
        候选池和选股流程使用纯数字代码（如 002179），统一去除后缀避免不匹配。
        
        Args:
            positions: 原始持仓字典，键可能带 .SZ/.SH 后缀
            
        Returns:
            标准化后的持仓字典，键为纯数字代码
        """
        if not positions:
            return {}
        normalized = {}
        for code, pos in positions.items():
            # 去除 PTrade 添加的交易所后缀
            clean_code = code.replace('.SZ', '').replace('.SH', '')
            if clean_code in normalized:
                # 同一只股票已存在（不应出现），合并或跳过
                logger.warning(f"【持仓标准化】代码冲突: {code} → {clean_code} 已存在，跳过重复条目")
                continue
            normalized[clean_code] = pos
        if len(normalized) != len(positions):
            logger.info(f"【持仓标准化】完成代码标准化，{len(positions)}条 → {len(normalized)}条")
        return normalized
    
    def _save_portfolio(self, portfolio: Dict, portfolio_file: str):
        """保存持仓信息
        
        Args:
            portfolio: 持仓字典
            portfolio_file: 持仓文件路径
        """
        try:
            # 确保资金信息已初始化
            if not hasattr(self, 'current_total_capital'):
                # 尝试从配置文件获取初始资金
                self.current_total_capital = self.config.get('initial_capital', 300000)
                logger.warning(f"【保存持仓】current_total_capital 未初始化，使用默认值: {self.current_total_capital}")
            
            if not hasattr(self, 'initial_capital'):
                self.initial_capital = self.current_total_capital

            # ========== 自动模式写盘防护 ==========
            # 自动模式下 PTrade 是唯一真实数据源。若数据来自本地（本地文件或历史
            # 继承）且持仓为空，说明 PTrade 同步并未生效，此时写盘会用空壳覆盖正确
            # 数据（历史故障：产生"持仓0只"的空壳 portfolio）。此处拒绝写盘并告警。
            # 注意：数据来自 PTrade 时空仓是合法的（如实盘清仓），必须允许写盘。
            _source = getattr(self, '_portfolio_source', None)
            if (getattr(self, 'run_mode', 'manual') == 'auto'
                    and not portfolio
                    and _source in ('local', 'local(inherited)')):
                logger.error(
                    f"【保存持仓】自动模式拒绝写入空持仓（数据来源: {_source}），"
                    f"避免覆盖 PTrade 同步结果: {portfolio_file}")
                return

            data = {
                'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'cash': self.current_total_capital,
                'initial_capital': self.initial_capital,
                'positions': portfolio
            }
            with open(portfolio_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 打印持仓条数与数据来源，便于追溯数据是否来自 PTrade 权威源
            logger.info(
                f"持仓信息已保存到: {portfolio_file}（持仓="
                f"{len(portfolio or {})} 条，来源="
                f"{getattr(self, '_portfolio_source', 'unknown')}）")
        except Exception as e:
            logger.error(f"保存持仓文件失败: {str(e)}")

    def _merge_tracking_into_portfolio(self):
        """从持久化账本合并追踪字段到当前持仓，保证择时加仓编号与移动止损区间正确。

        每日买入检查/执行仅 load_portfolio，而 portfolio 文件常缺失 add_count、
        last_add_date、last_add_price、first_buy_date 等由 sync/reconcile 维护、
        以账本 position_tracking 为权威的字段，导致：①择时加仓误判为"加仓#1"（实际
        已加仓多次，如 000526 账本 add_count=1 却显示加仓#1）；②移动止损"买入以来
        最高价"区间被同步日截断。以账本为准覆盖这些字段，确保 ||当前持仓|| 与账本一致。
        """
        # 每日检查路径未必加载账本，按需加载（sync 路径已加载则复用，避免重复 IO）
        if not hasattr(self, 'position_tracking') or not self.position_tracking:
            self.position_tracking = self._load_position_tracking()
        # 以账本为权威的追踪字段列表
        for code, pos in self.portfolio.items():
            # 账本键为无后缀代码，持仓键可能带 .SZ/.SH 后缀，两种都查，避免漏合
            track = self.position_tracking.get(code)
            if track is None:
                track = self.position_tracking.get(code.replace('.SZ', '').replace('.SH', ''))
            if not track:
                continue  # 账本无记录（全新本地建仓）则保留 portfolio 原值
            # 加仓次数以账本为准，确保择时信号"加仓#N"编号正确
            pos['add_count'] = track.get('add_count', pos.get('add_count', 0))
            # 首次建仓日以账本为准（移动止损"买入以来"区间从真实建仓日开始）
            if not pos.get('first_buy_date'):
                pos['first_buy_date'] = track.get('first_buy_date') or pos.get('buy_date')
            # 加仓历史补全（供展示/审计），缺失或为空时以账本覆盖
            pos['last_add_date'] = track.get('last_add_date')
            pos['last_add_price'] = track.get('last_add_price')

    def _load_signals(self, signals_file: str) -> List:
        """加载信号历史
        
        Args:
            signals_file: 信号文件路径
            
        Returns:
            信号列表
        """
        try:
            if not Path(signals_file).exists():
                return []
            with open(signals_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载信号文件失败: {str(e)}")
            return []
    
    def _save_signals(self, signals: List, signals_file: str):
        """保存信号历史（同时保存JSON和CSV格式）
        
        Args:
            signals: 信号列表
            signals_file: 信号文件路径（JSON格式）
        """
        try:
            # 保存JSON格式
            with open(signals_file, 'w', encoding='utf-8') as f:
                json.dump(signals, f, ensure_ascii=False, indent=2)
            logger.info(f"信号已保存到: {signals_file}")
            
            # 保存CSV格式（兼容PTrade批量埋单接口）
            import csv
            from pathlib import Path
            
            # PTrade集成：信号CSV按执行日期命名，保存到 ptrade.signal_dir 配置的目录
            # 支持绝对路径（如 D:/ptrade/output）和相对路径（如 data/running/to_ptrade）
            # 文件名格式: KHunter_signals_YYYYMMDD.csv，便于回测追溯历史信号
            signal_dir_raw = self.main_config.get('ptrade', {}).get(
                'signal_dir', 'data/running/to_ptrade') if self.main_config else 'data/running/to_ptrade'
            ptrade_dir = self._resolve_path(signal_dir_raw, self.running_dir)
            ptrade_dir.mkdir(parents=True, exist_ok=True)
            
            # 从信号文件名中提取信号日期（T日），格式 YYYYMMDD
            # 文件名格式: signals_YYYY-MM-DD.json
            import re
            date_match = re.search(r'signals_(\d{4}-\d{2}-\d{2})', signals_file)
            signal_date = date_match.group(1).replace('-', '') if date_match else datetime.datetime.now().strftime('%Y%m%d')
            # 执行日期 = T日 + 1个交易日（T+1日执行），PTrade只需 exec_date == today_str 判断
            signal_date_dt = datetime.datetime.strptime(signal_date, '%Y%m%d').strftime('%Y-%m-%d')
            exec_date = self._get_future_trading_day(signal_date_dt, 1).replace('-', '')
            # 文件路径依赖 exec_date，必须在计算 exec_date 之后构建
            pt_csv_file = ptrade_dir / f"KHunter_signals_{exec_date}.csv"
            
            # PTrade批量埋单CSV列定义
            # 字段规范：exec_date, symbol, side, order_volume, order_price, price_type, strategy_name, signal_id
            # exec_date = 信号日(T日)的下一个交易日(T+1日)，PTrade直接与当日比较即可，无需自行计算交易日
            csv_columns = [
                'exec_date', 'symbol', 'side', 'order_volume', 'order_price', 
                'price_type', 'strategy_name', 'signal_id'
            ]

            # 处理信号数据
            csv_data = []
            for signal in signals:
                stock_code = signal.get('stock_code', '')
                # 确保股票代码带市场后缀（SS/SZ，PTrade 格式）
                symbol = self._format_stock_code(stock_code)
                
                # 转换交易类型：buy/sell
                # 优先使用 signal_type 字段判断买卖方向
                signal_type = signal.get('signal_type', signal.get('trade_type', ''))
                side = 'buy' if signal_type in ('buy', 'buy_open', 'first', 'add') else 'sell' if signal_type in ('sell', 'sell_close', 'strategy_sell', 'take_profit', 'trailing_stop', 'stop_loss', 'position_expire') else ''
                
                # 获取信号中的价格和收盘价
                signal_price = signal.get('price', 0)
                close_price = signal.get('close', signal.get('current_price', signal_price))
                
                # 委托类型和价格
                # 买入：限价单，限价不超过收盘价1%
                # 卖出：市价单，按当前价格成交
                if side == 'buy':
                    price_type = 'limit'
                    # 买入限价不超过收盘价的1%
                    max_limit_pct = 0.01  # 1%限制
                    order_price = signal_price
                    if close_price > 0:
                        max_price = close_price * (1 + max_limit_pct)
                        if order_price > max_price:
                            order_price = max_price
                            logger.info(f"【限价调整】买入 {stock_code} 限价从 {signal_price:.2f} 调整为 {order_price:.2f}（不超过收盘价 {close_price:.2f} 的1%）")
                elif side == 'sell':
                    price_type = 'market'  # 卖出使用市价单
                    order_price = signal_price  # 市价单也保留价格字段用于记录
                else:
                    price_type = 'limit'
                    order_price = signal_price
                
                csv_row = {
                    'exec_date': exec_date,
                    'symbol': symbol,
                    'side': side,
                    'order_volume': signal.get('quantity', 0),
                    'order_price': round(order_price, 2),
                    'price_type': price_type,
                    'strategy_name': signal.get('strategy_name', ''),
                    'signal_id': signal.get('id', signal.get('signal_id', ''))
                }
                csv_data.append(csv_row)
            
            # 卖出信号排在买入信号前面：卖出释放资金后再买入
            csv_data.sort(key=lambda r: (0 if r['side'] == 'sell' else 1))

            # KHunter 只处理股票信号，写入单一 CSV 文件
            # 写入CSV文件（UTF-8编码，兼容PTrade批量埋单）
            with open(pt_csv_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=csv_columns)
                writer.writeheader()
                writer.writerows(csv_data)

            logger.info(f"PTrade 股票信号 CSV 已保存到: {pt_csv_file} ({len(csv_data)} 条)")

            # 保存 CSV 路径，供上层编排器报告使用
            signal_csv_path = str(pt_csv_file)

            # 清理旧信号文件，控制文件数量（PTrade 上传文件数有限制）
            # 保留最近 MAX_PTRADE_CSV_FILES 个文件，删除更早的
            import glob as _glob
            pattern = str(ptrade_dir / "KHunter_signals_*.csv")
            existing = sorted(_glob.glob(pattern))
            existing.sort(reverse=True)  # 按日期降序（最新在前）
            kept = 0
            for fpath in existing:
                fpath_obj = Path(fpath)
                if kept < MAX_PTRADE_CSV_FILES:
                    kept += 1
                    continue
                # 超过保留数，删除
                try:
                    fpath_obj.unlink()
                    logger.info(f"已清理过期信号文件: {fpath_obj.name}")
                except OSError as e:
                    logger.warning(f"清理过期文件失败 {fpath_obj.name}: {e}")
            if kept > 0:
                logger.info(f"信号文件清理完成: 保留 {kept} 个 (上限 {MAX_PTRADE_CSV_FILES})")

            # 返回 CSV 文件路径，供上层编排器报告使用
            return signal_csv_path
            
        except Exception as e:
            logger.error(f"保存信号文件失败: {str(e)}")
            return None
    
    def _format_stock_code(self, stock_code: str) -> str:
        """格式化股票代码，确保带市场后缀（PTrade 格式 .SS / .SZ）
        
        Args:
            stock_code: 股票代码
            
        Returns:
            带市场后缀的股票代码，如 000001.SZ, 600519.SS
        """
        if not stock_code:
            return ''
        
        # 如果已经带后缀，直接返回
        if '.' in stock_code:
            return stock_code
        
        # 根据股票代码判断市场
        # 60开头 -> 上海(.SS), 00开头 -> 深圳, 30开头 -> 创业板, 68开头 -> 科创板(.SS)
        if stock_code.startswith('6'):
            return f"{stock_code}.SS"
        elif stock_code.startswith('0') or stock_code.startswith('2'):
            return f"{stock_code}.SZ"
        elif stock_code.startswith('3'):
            return f"{stock_code}.SZ"
        elif stock_code.startswith('8'):
            return f"{stock_code}.SS"
        
        return stock_code
    
    def _save_trade_record(self, trade_record: Dict):
        """保存交易记录
        
        Args:
            trade_record: 交易记录字典，包含：
                - trade_id: 交易ID
                - trade_date: 交易日期
                - signal_id: 关联的信号ID
                - stock_code: 股票代码
                - stock_name: 股票名称
                - trade_type: 交易类型(buy/sell)
                - quantity: 交易数量
                - price: 交易价格
                - amount: 交易金额
                - fee: 交易费用
                - total_cost: 总成本（买入）/净收入（卖出）
                - executed_time: 执行时间
                - strategy_name: 策略名称
        """
        try:
            # 交易记录文件按日期命名
            trade_date = trade_record.get('trade_date', self.get_working_date())
            trade_file = self.running_dir / f"trades_{trade_date}.json"
            
            # 读取现有记录
            trades = []
            if trade_file.exists():
                with open(trade_file, 'r', encoding='utf-8') as f:
                    trades = json.load(f)
            
            # 添加新记录
            trades.append(trade_record)
            
            # 保存
            with open(trade_file, 'w', encoding='utf-8') as f:
                json.dump(trades, f, ensure_ascii=False, indent=2)
            
            logger.info(f"交易记录已保存到: {trade_file}")
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
    
    # ==================== 除权检测相关方法 ====================
    
    def _need_exdividend_check(self) -> bool:
        """
        判断当前是否需要进行除权检测
        
        规则：
        - 交易日（00:00-15:30）需要处理完整除权（信号+持仓+股票池）
        - 交易日（15:30-23:59）需要处理持仓和股票池除权（信号已执行）
        - 非交易日不需要处理
        
        Returns:
            是否需要进行除权检测
        """
        now = datetime.datetime.now()
        current_date = now.strftime('%Y-%m-%d')
        
        # 检查是否为交易日
        if not is_trading_day(current_date):
            logger.info(f"【除权检测】{current_date} 不是交易日，跳过检测")
            return False
        
        # 检查是否在交易日内（00:00-23:59）
        # 盘中模式（15:30前）：完整除权检测
        # 盘后模式（15:30后）：持仓和股票池除权检测
        if now.hour < 15 or (now.hour == 15 and now.minute < 30):
            logger.info(f"【除权检测】当前时间 {now.strftime('%H:%M')} < 15:30（盘中模式），需要检测")
            return True
        elif now.hour < 24:
            logger.info(f"【除权检测】当前时间 {now.strftime('%H:%M')} >= 15:30（盘后模式），需要检测持仓和股票池")
            return True
        
        logger.info(f"【除权检测】当前时间 {now.strftime('%H:%M')} 超出交易时间范围")
        return False
    
    
    def _load_last_exdividend_date(self) -> str:
        """
        加载最后一次处理除权的日期（持久化存储）
        
        Returns:
            最后处理日期，如果文件不存在或加载失败返回空字符串
        """
        processed_date_file = self.running_dir / 'last_exdividend_date.json'
        if not processed_date_file.exists():
            return ""
        
        try:
            with open(processed_date_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('last_date', "")
        except Exception as e:
            logger.warning(f"【除权处理】加载最后处理日期文件失败: {e}")
            return ""
    
    def _save_last_exdividend_date(self, trade_date: str):
        """
        保存最后处理除权的日期（持久化存储）
        
        Args:
            trade_date: 处理日期
        """
        processed_date_file = self.running_dir / 'last_exdividend_date.json'
        try:
            with open(processed_date_file, 'w', encoding='utf-8') as f:
                json.dump({'last_date': trade_date, 'saved_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, f, ensure_ascii=False, indent=2)
            logger.debug(f"【除权处理】已保存最后处理日期: {trade_date}")
        except Exception as e:
            logger.warning(f"【除权处理】保存最后处理日期失败: {e}")
    
    def _perform_exdividend_check(self, current_date: str, signal_date: str = None):
        """
        执行除权检测（根据盘中/盘后模式），包含双重保护检查
        
        Args:
            current_date: 当日日期（用于持仓和股票池除权）
            signal_date: 信号日期（用于信号除权，盘中模式为前一交易日，盘后模式为None）
        """
        # 双重保护检查：先检查内存标记，再检查持久化记录
        if current_date in self._exdividend_processed_dates:
            logger.info(f"【每日除权检测】{current_date} 已处理过除权检测（内存标记），跳过")
            return
        
        last_processed_date = self._load_last_exdividend_date()
        if last_processed_date == current_date:
            logger.info(f"【每日除权检测】{current_date} 已处理过除权检测（持久化记录），更新内存标记")
            self._exdividend_processed_dates.add(current_date)
            return
        
        # 判断当前时间，确定是否处理信号除权
        now = datetime.datetime.now()
        if now.hour < 15 or (now.hour == 15 and now.minute < 30):
            # 盘中模式（15:30前）：处理持仓除权 + 信号除权 + 股票池除权
            logger.info(f"【数据初始化】盘中模式（{now.strftime('%H:%M')} < 15:30）")
            # 持仓除权检测（使用当日日期）
            logger.info(f"【数据初始化】检测 {current_date} 的持仓除权信息...")
            portfolio_changed = self._check_portfolio_exdividend(current_date)
            if portfolio_changed:
                logger.info(f"【数据初始化】持仓除权检测完成，有 {len(self.portfolio)} 只股票进行了除权调整")
            else:
                logger.info(f"【数据初始化】持仓除权检测完成，{current_date} 无持仓除权信息")
            # 信号除权检测（检测当日除权信息，调整前一交易日的信号）
            if signal_date:
                logger.info(f"【数据初始化】检测 {current_date} 的信号除权信息（调整 {signal_date} 的信号）...")
                signals_changed = self._check_signals_exdividend(current_date, signal_date)
                if signals_changed:
                    logger.info(f"【数据初始化】信号除权检测完成，有信号进行了除权调整")
                else:
                    logger.info(f"【数据初始化】信号除权检测完成，{current_date} 无信号除权信息")
            else:
                logger.info(f"【数据初始化】跳过信号除权检测（无信号日期）")
            # 股票池除权检测（使用当日日期）
            logger.info(f"【数据初始化】检测 {current_date} 的股票池除权信息...")
            pool_changed = self._check_pool_exdividend(current_date)
            if pool_changed:
                logger.info(f"【数据初始化】股票池除权检测完成，有股票池条目进行了除权调整")
            else:
                logger.info(f"【数据初始化】股票池除权检测完成，{current_date} 无股票池除权信息")
        else:
            # 盘后模式（15:30后）：只处理持仓除权 + 股票池除权
            logger.info(f"【数据初始化】盘后模式（{now.strftime('%H:%M')} >= 15:30）")
            # 持仓除权检测（使用当日日期）
            logger.info(f"【数据初始化】检测 {current_date} 的持仓除权信息...")
            portfolio_changed = self._check_portfolio_exdividend(current_date)
            if portfolio_changed:
                logger.info(f"【数据初始化】持仓除权检测完成，有 {len(self.portfolio)} 只股票进行了除权调整")
            else:
                logger.info(f"【数据初始化】持仓除权检测完成，{current_date} 无持仓除权信息")
            # 股票池除权检测（使用当日日期）
            logger.info(f"【数据初始化】检测 {current_date} 的股票池除权信息...")
            pool_changed = self._check_pool_exdividend(current_date)
            if pool_changed:
                logger.info(f"【数据初始化】股票池除权检测完成，有股票池条目进行了除权调整")
            else:
                logger.info(f"【数据初始化】股票池除权检测完成，{current_date} 无股票池除权信息")
            # 跳过信号除权检测（盘后模式）
            logger.info(f"【数据初始化】跳过信号除权检测（盘后模式）")
        
        # 更新内存标记和持久化记录
        self._exdividend_processed_dates.add(current_date)
        self._save_last_exdividend_date(current_date)
    
    def _check_portfolio_exdividend(self, trade_date: str) -> bool:
        """
        检测持仓股票的除权情况并调整
        
        Args:
            trade_date: 交易日期
        
        Returns:
            是否有调整
        """
        from utils.exdividend_utils import ExdividendUtils
        
        has_changes = False
        
        for stock_code, position in self.portfolio.items():
            # 检查该股票当日是否已处理过除权
            rights_history = position.get('rights_history', [])
            if any(rh.get('date') == trade_date for rh in rights_history):
                logger.debug(f"【持仓除权调整】{stock_code} {trade_date} 已处理过除权，跳过")
                continue
            
            # 检测是否除权
            exdividend_info = ExdividendUtils.get_exdividend_info(stock_code, trade_date)
            
            if exdividend_info:
                factor = exdividend_info.get('factor', 1.0)
                logger.info(f"【持仓除权调整】{stock_code} 检测到除权，因子: {factor}")
                
                # 调整持仓成本价
                if 'buy_price' in position:
                    position['buy_price'] = position['buy_price'] * factor
                
                # 调整当前价格（如果存在）
                if 'current_price' in position:
                    position['current_price'] = position['current_price'] * factor
                
                # 调整数量（考虑送股）
                bonus_ratio = exdividend_info.get('bonus_ratio', 0)
                if bonus_ratio and 'quantity' in position:
                    position['quantity'] = int(position['quantity'] * (1 + bonus_ratio))
                
                # 记录除权历史
                if 'rights_history' not in position:
                    position['rights_history'] = []
                position['rights_history'].append({
                    'date': trade_date,
                    'factor': factor,
                    'type': 'exdividend'
                })
                
                has_changes = True
        
        return has_changes
    
    def _check_signals_exdividend(self, exdividend_date: str, signal_date: str = None) -> bool:
        """
        检测信号涉及股票的除权情况并调整
        
        Args:
            exdividend_date: 除权检测日期（当日日期，用于查询除权信息）
            signal_date: 信号日期（前一交易日，用于确定加载哪个日期的信号）
        
        Returns:
            是否有调整
        """
        from utils.exdividend_utils import ExdividendUtils
        
        has_changes = False
        
        for signal in self.signals:
            # 只处理未执行的买入/卖出信号
            signal_type = signal.get('signal_type', '')
            if signal.get('executed') or signal.get('ignored'):
                continue
            
            if signal_type not in ('buy', 'sell', 'strategy_sell'):
                continue
            
            # 检查该信号是否已处理过除权
            if signal.get('exdividend_adjusted'):
                logger.debug(f"【信号除权调整】{signal.get('stock_code')} 信号已处理过除权，跳过")
                continue
            
            stock_code = signal.get('stock_code')
            if not stock_code:
                continue
            
            # 检测是否除权（使用除权日期检测）
            exdividend_info = ExdividendUtils.get_exdividend_info(stock_code, exdividend_date)
            
            if exdividend_info:
                factor = exdividend_info.get('factor', 1.0)
                logger.info(f"【信号除权调整】{stock_code} {signal_type} 信号检测到除权，因子: {factor}")
                
                # 买入信号：调整买入价格和数量
                if signal_type == 'buy':
                    if 'price' in signal:
                        signal['original_price'] = signal['price']
                        signal['price'] = signal['price'] * factor
                    if 'quantity' in signal:
                        signal['original_quantity'] = signal['quantity']
                        bonus_ratio = exdividend_info.get('bonus_ratio', 0)
                        if bonus_ratio:
                            signal['quantity'] = int(signal['quantity'] * (1 + bonus_ratio))
                    signal['exdividend_adjusted'] = True
                    signal['exdividend_factor'] = factor
                
                # 卖出信号：调整卖出数量（考虑送股）
                if signal_type in ('sell', 'strategy_sell') and 'quantity' in signal:
                    signal['original_quantity'] = signal['quantity']
                    bonus_ratio = exdividend_info.get('bonus_ratio', 0)
                    if bonus_ratio:
                        signal['quantity'] = int(signal['quantity'] * (1 + bonus_ratio))
                    signal['exdividend_adjusted'] = True
                    signal['exdividend_factor'] = factor
                
                has_changes = True
        
        return has_changes
    
    def _check_pool_exdividend(self, trade_date: str) -> bool:
        """
        检测股票池中股票的除权情况并调整支撑位信息
        
        Args:
            trade_date: 交易日期
        
        Returns:
            是否有调整
        """
        from utils.exdividend_utils import ExdividendUtils
        
        has_changes = False
        
        for item in self.buy_candidate_pool:
            # 适配股票池结构
            stock_info = item.get('stock', item)
            stock_code = stock_info.get('stock_code')
            
            if not stock_code:
                continue
            
            # 检查该股票当日是否已处理过除权
            exdividend_dates = item.get('exdividend_dates', [])
            if trade_date in exdividend_dates:
                logger.debug(f"【股票池除权调整】{stock_code} {trade_date} 已处理过除权，跳过")
                continue
            
            # 检测是否除权
            exdividend_info = ExdividendUtils.get_exdividend_info(stock_code, trade_date)
            
            if exdividend_info:
                factor = exdividend_info.get('factor', 1.0)
                logger.info(f"【股票池除权调整】{stock_code} 检测到除权，因子: {factor}")
                
                # 调整支撑位和其他价格字段
                price_fields = ['support_level', 'resistance_level', 'target_price', 'entry_price']
                
                for field in price_fields:
                    if field in item:
                        item[field] = item[field] * factor
                        logger.info(f"【股票池除权调整】{stock_code} {field}: {item[field]}")
                        has_changes = True
                    if field in stock_info:
                        stock_info[field] = stock_info[field] * factor
                        has_changes = True
                
                # 记录除权日期（避免重复处理）
                if 'exdividend_dates' not in item:
                    item['exdividend_dates'] = []
                item['exdividend_dates'].append(trade_date)
        
        return has_changes
    
    def execute_signal(self, signal_id: str) -> Dict:
        """执行指定的信号（串行执行，确保原子操作）
        
        Args:
            signal_id: 信号ID
            
        Returns:
            执行结果字典
        """
        # 获取信号执行锁，确保串行执行
        _signal_execution_lock.acquire()
        try:
            logger.info(f"获取信号执行锁，开始执行信号: {signal_id}")
            
            # 先从内存中查找信号（前端已从文件加载所有信号到内存）
            signal = None
            for s in self.signals:
                if s.get('id') == signal_id:
                    signal = s
                    break
            
            # 记录调试信息
            if not signal:
                logger.debug(f"【调试】内存中未找到信号 {signal_id}，当前内存信号数量: {len(self.signals)}")
                if len(self.signals) > 0:
                    logger.debug(f"【调试】内存中的信号ID列表: {[s.get('id') for s in self.signals]}")
            
            # 如果内存中找不到，尝试从文件加载（Web界面执行时可能未初始化内存信号）
            if not signal:
                # 从信号ID中提取日期（格式: buy_688549_2026-05-06）
                signal_date = None
                parts = signal_id.split('_')
                if len(parts) >= 3:
                    # 最后一个部分应该是日期
                    date_part = parts[-1]
                    if len(date_part) == 10 and date_part.count('-') == 2:
                        signal_date = date_part
                
                # 如果从信号ID中提取不到日期，使用工作日期
                if not signal_date:
                    signal_date = self.get_working_date()
                
                logger.debug(f"【调试】尝试从文件加载信号，信号日期: {signal_date}")
                signals_file = self.running_dir / f"signals_{signal_date}.json"
                if signals_file.exists():
                    file_signals = self._load_signals(str(signals_file))
                    logger.info(f"从文件加载信号，当前信号数量: {len(file_signals)}")
                    for s in file_signals:
                        if s.get('id') == signal_id:
                            signal = s
                            # 添加到内存中以便后续查找
                            self.signals.append(s)
                            break
                else:
                    logger.debug(f"【调试】信号文件不存在: {signals_file}")
            
            if not signal:
                return {"success": False, "error": f"未找到信号: {signal_id}"}
            
            # ========== 确保持仓和信号数据已加载（修复：Web界面手动执行信号时持仓丢失问题）==========
            # 当StrategyRunner刚创建或Web服务器重启后，self.portfolio和self.signals可能为空
            # 必须先加载已有数据，否则保存时会覆盖丢失之前的持仓
            portfolio_date = signal.get('date')
            if not portfolio_date:
                # 从signal_id中提取日期（格式: buy_688549_2026-05-06）
                if 'signal_date' not in locals() or not signal_date:
                    parts = signal_id.split('_')
                    if len(parts) >= 3:
                        date_part = parts[-1]
                        if len(date_part) == 10 and date_part.count('-') == 2:
                            signal_date = date_part
                if not portfolio_date and 'signal_date' in locals():
                    portfolio_date = signal_date
            if not portfolio_date:
                portfolio_date = self.get_working_date()
            
            # ========== 关键修复：资金同步 ==========
            # 关键逻辑：可用资金 = 持仓文件中的可用资金 + 本次会话已执行的卖出收入
            # 内存中的 current_total_capital 可能在本次会话中已累加了卖出收入，
            # 而持仓文件中的 cash 是上次保存的快照。
            # 因此需要加载持仓文件获取"基线可用资金"，再加上本次会话的卖出增量。
            
            # 1. 记录加载前的当前可用资金（可能是会话内已累加的）
            current_cash_before_load = getattr(self, 'current_total_capital', 0)
            
            # 2. 从交易日持仓文件加载"基线可用资金"
            pf_file_signal = self.running_dir / f"portfolio_{portfolio_date}.json"
            
            baseline_cash = None
            if pf_file_signal.exists():
                # 使用交易日持仓文件
                with open(pf_file_signal, 'r', encoding='utf-8') as f:
                    portfolio_data = json.load(f)
                baseline_cash = portfolio_data.get('cash', 0)
                positions_from_file = portfolio_data.get('positions', {})
                logger.info(f"【资金基线】从信号日期持仓文件加载基线: ¥{baseline_cash:.2f}")
            else:
                positions_from_file = {}
                logger.info(f"【资金基线】无持仓文件，基线=0")
            
            # 3. 合并持仓（保留内存中的）
            if not self.portfolio:
                self.portfolio = positions_from_file
            else:
                for code, pos in positions_from_file.items():
                    if code not in self.portfolio:
                        self.portfolio[code] = pos
            
            # 4. 关键：计算"本次会话内已执行的卖出收入增量"
            # 内存中的 current_total_capital - 加载的基线 cash = 会话内增量
            if baseline_cash is not None and current_cash_before_load > baseline_cash:
                # 内存比基线多，说明本次会话执行了卖出
                session_sell_income = current_cash_before_load - baseline_cash
                logger.info(f"【资金增量】本次会话卖出收入: ¥{session_sell_income:.2f}")
                # 维持内存中的 current_total_capital（已包含卖出收入）
            elif baseline_cash is not None:
                # 内存比基线少或相等，说明本次会话没有卖出收入（或有买入）
                # 使用基线作为当前可用资金
                if hasattr(self, 'current_total_capital'):
                    logger.info(f"【资金同步】使用基线资金: ¥{baseline_cash:.2f}（原: ¥{current_cash_before_load:.2f}）")
                    self.current_total_capital = baseline_cash
                else:
                    self.current_total_capital = baseline_cash
            else:
                # 无基线文件，保持内存中的值
                if not hasattr(self, 'current_total_capital'):
                    self.current_total_capital = self.config.get('initial_capital', 300000.0)
            
            # 加载信号历史（如果内存中为空）
            if not self.signals:
                sig_file = self.running_dir / f"signals_{portfolio_date}.json"
                if sig_file.exists():
                    self.signals = self._load_signals(str(sig_file))
                    logger.info(f"【信号加载】从文件加载信号: {portfolio_date}, 共 {len(self.signals)} 条记录")
                else:
                    logger.info(f"【信号加载】信号文件不存在: {sig_file}，使用空信号列表")
            
            # 检查信号是否已执行
            if signal.get('executed'):
                return {"success": False, "error": f"信号已执行: {signal_id}"}
            
            # 立即标记信号为已执行，防止并发执行
            signal['executed'] = True
            signal['executed_date'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            signal_type = signal.get('signal_type', 'buy')
            stock_code = signal.get('stock_code')
            quantity = signal.get('quantity', 0)
            price = signal.get('price', 0)
            amount = signal.get('amount', quantity * price)
            
            # 计算交易费用（与回测一致）
            is_buy = (signal_type == 'buy')
            fee_result = calculate_trading_cost(stock_code, price, quantity, is_buy, self.config)
            total_cost = fee_result.get('total_cost', 0)
            
            # 获取当前可用资金（current_total_capital 直接表示可用资金）
            current_cash = self.current_total_capital if hasattr(self, 'current_total_capital') else 300000
            
            if signal_type == 'buy':
                # 检查当日是否卖出该股票（当日卖出的股票当日不买入）
                today_sold_stocks = getattr(self, '_today_sold_stocks', set())
                if stock_code in today_sold_stocks:
                    return {"success": False, "error": f"当日已卖出股票 {stock_code}，不允许当日买入"}
                
                # 计算实际需要支付的总金额（参考回测引擎逻辑）
                # adjusted_amount: 包含滑点的成交金额
                # commission: 佣金
                # transfer_fee: 过户费（买入时支付）
                # stamp_tax: 印花税（买入时不收取）
                adjusted_amount = fee_result.get('adjusted_amount', amount)
                commission = fee_result.get('commission', 0)
                transfer_fee = fee_result.get('transfer_fee', 0)
                total_deduct = adjusted_amount + commission + transfer_fee
                
                # 检查可用资金
                if current_cash < total_deduct:
                    return {"success": False, "error": f"可用资金不足: 需要¥{total_deduct:.2f}（金额¥{adjusted_amount:.2f} + 佣金¥{commission:.2f} + 过户费¥{transfer_fee:.2f}），可用¥{current_cash:.2f}"}
                
                # 执行买入
                if stock_code not in self.portfolio:
                    # 使用调整后的价格作为买入成本（包含滑点）
                    buy_price = fee_result.get('adjusted_price', price)
                    buy_fee = commission + transfer_fee  # 买入时不包含印花税
                    self.portfolio[stock_code] = {
                        'stock_name': signal.get('stock_name', ''),
                        'quantity': quantity,
                        'buy_price': buy_price,
                        'buy_date': signal.get('date', self.get_working_date()),
                        'current_price': price,
                        'buy_amount': adjusted_amount,
                        'buy_fee': buy_fee,
                        'total_cost': total_deduct,
                        'profit_loss': 0.0,
                        'profit_rate': 0.0,
                        'holding_days': 0,
                        'industry': '',
                        'sector': '',
                        'selection_score': signal.get('score', 0),
                        'support_level': signal.get('support_level', 0),
                        'strategy_name': signal.get('strategy_name', 'N/A')
                    }
                    # 扣减资金（买入金额 + 佣金 + 过户费）
                    if hasattr(self, 'current_total_capital'):
                        self.current_total_capital -= total_deduct
                    
                    # 保存交易记录
                    trade_record = {
                        'trade_id': f"trade_{signal_id}",
                        'trade_date': signal.get('date', self.get_working_date()),
                        'signal_id': signal_id,
                        'stock_code': stock_code,
                        'stock_name': signal.get('stock_name', ''),
                        'trade_type': 'buy',
                        'quantity': quantity,
                        'price': buy_price,
                        'amount': adjusted_amount,
                        'fee': buy_fee,
                        'total_cost': total_deduct,
                        'executed_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'strategy_name': signal.get('strategy_name', 'N/A')
                    }
                    self._save_trade_record(trade_record)
                    
                    logger.info(f"买入成功: {stock_code} x {quantity} @ ¥{buy_price:.2f}（佣金¥{commission:.2f} + 过户费¥{transfer_fee:.2f}），资金扣减¥{total_deduct:.2f}")
                else:
                    # 加仓：已有持仓，合并计算（参考回测引擎逻辑）
                    existing_pos = self.portfolio[stock_code]
                    old_quantity = existing_pos['quantity']
                    # 兼容旧版本持仓数据：旧数据可能没有 buy_amount 字段
                    # 通过 buy_price * quantity 反算买入金额
                    old_amount = existing_pos.get('buy_amount',
                                                   existing_pos.get('buy_price', price) * old_quantity)
                    old_cost = existing_pos.get('total_cost', 0)
                    # 如果旧持仓没有 buy_amount，补上该字段
                    if 'buy_amount' not in existing_pos:
                        existing_pos['buy_amount'] = old_amount
                    
                    # 使用调整后的价格作为买入成本（包含滑点）
                    buy_price = fee_result.get('adjusted_price', price)
                    buy_fee = commission + transfer_fee  # 买入时不包含印花税
                    
                    # 更新持仓数量和金额
                    existing_pos['quantity'] += quantity
                    existing_pos['buy_amount'] += adjusted_amount
                    existing_pos['total_cost'] = old_cost + total_deduct
                    # 加权平均买入价
                    existing_pos['buy_price'] = existing_pos['buy_amount'] / existing_pos['quantity']
                    # 更新最后加仓日期和价格
                    existing_pos['last_add_date'] = signal.get('date', self.get_working_date())
                    existing_pos['last_add_price'] = buy_price
                    # 更新加仓次数
                    existing_pos['add_count'] = existing_pos.get('add_count', 0) + 1
                    # 同步持久化追踪账本，确保 PTrade 同步覆盖后不丢失加仓计数
                    self._sync_tracking_on_add(
                        stock_code, existing_pos,
                        signal.get('date', self.get_working_date()), buy_price)
                    
                    # 扣减资金（买入金额 + 佣金 + 过户费）
                    if hasattr(self, 'current_total_capital'):
                        self.current_total_capital -= total_deduct
                    
                    # 保存交易记录
                    trade_record = {
                        'trade_id': f"trade_{signal_id}",
                        'trade_date': signal.get('date', self.get_working_date()),
                        'signal_id': signal_id,
                        'stock_code': stock_code,
                        'stock_name': existing_pos.get('stock_name', ''),
                        'trade_type': 'buy',
                        'quantity': quantity,
                        'price': buy_price,
                        'amount': adjusted_amount,
                        'fee': buy_fee,
                        'total_cost': total_deduct,
                        'executed_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'strategy_name': signal.get('strategy_name', 'N/A'),
                        'is_addition': True  # 标记为加仓
                    }
                    self._save_trade_record(trade_record)
                    
                    add_count = existing_pos['add_count']
                    logger.info(f"【加仓#{add_count}】{stock_code} x {quantity} @ ¥{buy_price:.2f}（佣金¥{commission:.2f} + 过户费¥{transfer_fee:.2f}），原数量={old_quantity}, 加仓={quantity}, 合计={existing_pos['quantity']}, 均价={existing_pos['buy_price']:.2f}")
            
            elif signal_type == 'sell':
                # 执行卖出
                if stock_code in self.portfolio:
                    # 计算卖出收入（考虑费用）
                    sell_price = fee_result.get('adjusted_price', price)
                    sell_amount = sell_price * quantity - total_cost
                    del self.portfolio[stock_code]
                    # 增加资金（卖出收入）- 直接增加到可用资金
                    if hasattr(self, 'current_total_capital'):
                        self.current_total_capital += sell_amount
                    logger.info(f"卖出成功: {stock_code} x {quantity} @ ¥{sell_price:.2f}（收入¥{sell_amount:.2f}，费用¥{total_cost:.2f}）")
                    
                    # 保存交易记录
                    trade_record = {
                        'trade_id': f"trade_{signal_id}",
                        'trade_date': signal.get('date', self.get_working_date()),
                        'signal_id': signal_id,
                        'stock_code': stock_code,
                        'stock_name': signal.get('stock_name', ''),
                        'trade_type': 'sell',
                        'quantity': quantity,
                        'price': sell_price,
                        'amount': sell_price * quantity,
                        'fee': total_cost,
                        'total_cost': sell_amount,
                        'executed_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'strategy_name': signal.get('strategy_name', 'N/A')
                    }
                    self._save_trade_record(trade_record)
                else:
                    return {"success": False, "error": f"未持有股票: {stock_code}"}
            
            # 保存更新后的信号和持仓（统一使用交易日 portfolio_date）
            signals_file = self.running_dir / f"signals_{portfolio_date}.json"
            portfolio_file = self.running_dir / f"portfolio_{portfolio_date}.json"
            self._save_signals(self.signals, str(signals_file))
            self._save_portfolio(self.portfolio, str(portfolio_file))
            
            return {"success": True, "message": f"{signal_type}信号执行成功", "fee_details": fee_result}
            
        except Exception as e:
            logger.error(f"执行信号失败: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            # 释放信号执行锁
            _signal_execution_lock.release()
            logger.info(f"释放信号执行锁，信号执行完成: {signal_id}")
    
    def ignore_signal(self, signal_id: str) -> Dict:
        """忽略指定的信号
        
        Args:
            signal_id: 信号ID
            
        Returns:
            操作结果字典
        """
        try:
            logger.info(f"忽略信号: {signal_id}")
            
            # 查找信号
            signal = None
            for s in self.signals:
                if s.get('id') == signal_id:
                    signal = s
                    break
            
            if not signal:
                return {"success": False, "error": f"未找到信号: {signal_id}"}
            
            # 标记信号为已忽略
            signal['ignored'] = True
            signal['ignored_date'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 保存更新后的信号
            working_date = self.get_working_date()
            signals_file = self.running_dir / f"signals_{working_date}.json"
            self._save_signals(self.signals, str(signals_file))
            
            return {"success": True, "message": "信号已忽略"}
            
        except Exception as e:
            logger.error(f"忽略信号失败: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def execute_pending_signals(self, trade_date: str = None) -> Dict:
        """执行所有待执行的信号（T+1日盘中调用）
        
        流程：
        1. 根据时间确定处理日期（15:30前处理T日，15:30后处理当日）
        2. 加载股票池、资金信息、持仓信息、交易信号
        3. 执行卖出信号
        4. 执行买入信号
        5. 保存持仓文件（重新计算资金）、交易文件、信号文件
        
        Args:
            trade_date: 交易日期，默认根据当前时间自动确定
            
        Returns:
            执行结果字典
        """
        try:
            if trade_date is None:
                # 根据当前时间确定处理日期
                now = datetime.datetime.now()
                today = now.strftime('%Y-%m-%d')
                
                # 判断是否是交易日
                if is_trading_day(today):
                    # 交易日：15:30之前处理T日（前一交易日）数据，15:30之后处理当日数据
                    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
                        # 15:30之前，处理前一交易日数据
                        # 注意：_get_previous_trading_day 是回测引擎专有方法，实盘不存在
                        # （2026-09-13 修复 AttributeError），此处统一用模块函数（返回 str，
                        #       与下方 portfolio_{trade_date}.json 等文件名拼接口径一致）
                        trade_date = get_previous_trading_day(today)
                        logger.info(f"【T+1执行】当前时间 {now.strftime('%H:%M')} < 15:30，处理前一交易日数据: {trade_date}")
                    else:
                        # 15:30之后，处理当日数据
                        trade_date = today
                        logger.info(f"【T+1执行】当前时间 {now.strftime('%H:%M')} >= 15:30，处理当日数据: {trade_date}")
                else:
                    # 非交易日，使用最近的交易日
                    trade_date = self.get_working_date()
                    logger.info(f"【T+1执行】今日({today})非交易日，处理最近交易日数据: {trade_date}")
            else:
                logger.info(f"【T+1执行】使用指定日期: {trade_date}")
            
            logger.info(f"【T+1执行】开始执行待处理信号: {trade_date}")
            
            # 1. 加载数据
            portfolio_file = self.running_dir / f"portfolio_{trade_date}.json"
            signals_file = self.running_dir / f"signals_{trade_date}.json"
            
            # 加载持仓信息
            portfolio_data = self._load_portfolio(str(portfolio_file))
            self.portfolio = self._normalize_portfolio_keys(portfolio_data.get('positions', {}))
            # 合并账本追踪字段（add_count/first_buy_date 等），保证择时加仓编号正确
            self._merge_tracking_into_portfolio()

            # 加载信号
            self.signals = self._load_signals(str(signals_file))
            
            # 加载股票池
            self.buy_candidate_pool = self._load_pool_from_file()[0]
            
            # 统计待执行的信号
            pending_buy_signals = [s for s in self.signals if s.get('signal_type') == 'buy' and not s.get('executed') and not s.get('ignored')]
            pending_sell_signals = [s for s in self.signals if s.get('signal_type') in ('sell', 'strategy_sell') and not s.get('executed') and not s.get('ignored')]
            
            logger.info(f"【T+1执行】待执行买入信号: {len(pending_buy_signals)}，待执行卖出信号: {len(pending_sell_signals)}")
            
            # 2. 先执行卖出信号
            executed_sells = 0
            # 初始化当日卖出股票集合
            if not hasattr(self, '_today_sold_stocks'):
                self._today_sold_stocks = set()
            for signal in pending_sell_signals:
                result = self.execute_signal(signal.get('id'))
                if result.get('success'):
                    executed_sells += 1
                    # 记录当日卖出的股票
                    self._today_sold_stocks.add(signal.get('stock_code'))
                    logger.info(f"【T+1执行】卖出成功: {signal.get('stock_code')}")
            
            # 3. 再执行买入信号
            executed_buys = 0
            for signal in pending_buy_signals:
                result = self.execute_signal(signal.get('id'))
                if result.get('success'):
                    executed_buys += 1
                    logger.info(f"【T+1执行】买入成功: {signal.get('stock_code')}")
            
            # 4. 保存最终结果
            self._save_signals(self.signals, str(signals_file))
            self._save_portfolio(self.portfolio, str(portfolio_file))
            
            logger.info(f"【T+1执行】执行完成: 卖出 {executed_sells}，买入 {executed_buys}")
            
            return {
                "success": True,
                "message": f"信号执行完成",
                "data": {
                    "date": trade_date,
                    "executed_sells": executed_sells,
                    "executed_buys": executed_buys,
                    "final_cash": self.current_total_capital,
                    "position_count": len(self.portfolio)
                }
            }
            
        except Exception as e:
            logger.error(f"执行待处理信号失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
    
    def _save_daily_record(self, date: str, record: Dict, records_file: str):
        """保存每日记录（仅生成 Markdown 报告，不保存 JSON）
        
        Args:
            date: 日期
            record: 每日记录
            records_file: 记录文件路径（已废弃，仅保留参数兼容性）
        """
        try:
            # 只生成文字版每日报告（Markdown格式），不保存 JSON 文件
            self._generate_daily_report(date, record)
        except Exception as e:
            logger.error(f"保存每日记录失败: {str(e)}")
    
    def _generate_daily_report(self, date: str, record: Dict):
        """生成文字版每日报告（Markdown格式）
        
        Args:
            date: 日期
            record: 每日记录数据
        """
        try:
            report_lines = []
            
            # 标题
            report_lines.append(f"# 策略执行日报 - {date}")
            report_lines.append("")
            
            # 执行概览
            report_lines.append("## 📊 执行概览")
            report_lines.append("")
            report_lines.append(f"- **执行日期**: {record.get('trading_date', date)}")
            report_lines.append(f"- **执行状态**: {'✅ 已完成' if record.get('status') == 'completed' else '❌ 未完成'}")
            report_lines.append("")
            
            # 股票池
            candidates = [s for s in record.get('pool_stocks', []) if s.get('status') == 'candidate']
            removed_count = record['pool_summary'].get('removed_count', 0)
            added_count = record['pool_summary'].get('added_count', 0)
            cooling_count = sum(1 for c in candidates if c.get('is_cooling', False))
            report_lines.append("## 📋 股票池")
            report_lines.append("")
            if candidates:
                report_lines.append(f"股票池合计 **{len(candidates)}** 只股票 今天移除 **{removed_count}** 只，新增加 **{added_count}** 只，其中冷却中 **{cooling_count}** 只：")
                report_lines.append("")
                report_lines.append("| 股票代码 | 股票名称 | 评分 | 策略 | 支撑位 | 入池日期 | 冷却 |")
                report_lines.append("|----------|----------|------|------|--------|----------|------|")
                for stock in candidates:
                    cooling_info = f"❄️ 至{stock['cool_down_end']}" if stock.get('is_cooling') and stock.get('cool_down_end') else ""
                    report_lines.append(f"| {stock['code']} | {stock['name']} | {stock['score']} | {self._get_strategy_name(stock['strategy'])} | {stock['support_level']} | {stock.get('days', 1) > 1 and stock.get('added_date', '') or '今日'} | {cooling_info} |")
            else:
                report_lines.append("暂无候选股票")
            report_lines.append("")

            # 【2026-09-24】股票池变动明细（原因分布 + 新增/移除逐条 ✓）
            #   数据源：record['pool_summary']（由 run_strategies_batch 写入 ✓，
            #   与飞书简报**同一份数据、同一套归类** ✓）
            pool_summary = record.get('pool_summary', {}) or {}
            added_items = pool_summary.get('added_items', []) or []
            removed_items = pool_summary.get('removed_items', []) or []
            if added_items or removed_items:
                from trading.pool_entry_rules import summarize_pool_removal_reasons
                report_lines.append("### 🔄 股票池变动明细")
                report_lines.append("")
                if removed_items:
                    counts = summarize_pool_removal_reasons(
                        [it.get('reason', '') for it in removed_items])
                    if counts:
                        dist = "、".join(f"{k} {v} 只" for k, v in
                                         sorted(counts.items(), key=lambda kv: -kv[1]))
                        report_lines.append(f"- **移除原因分布**: {dist}")
                        report_lines.append("")
                if added_items:
                    report_lines.append(f"**新增明细（{len(added_items)} 只）**")
                    report_lines.append("")
                    report_lines.append("| 股票代码 | 股票名称 | 来源 | 策略 | 支撑位 |")
                    report_lines.append("|----------|----------|------|------|--------|")
                    for it in added_items:
                        src = '持仓回池' if it.get('source') == 'holding' else '选股'
                        report_lines.append(
                            f"| {it.get('code', '')} | {it.get('name', '')} | {src} | "
                            f"{self._get_strategy_name(it.get('strategy', ''))} | "
                            f"{it.get('support_level', 0)} |")
                    report_lines.append("")
                if removed_items:
                    report_lines.append(f"**移除明细（{len(removed_items)} 只）**")
                    report_lines.append("")
                    report_lines.append("| 股票代码 | 股票名称 | 持有天数 | 收盘价 | 移除原因 |")
                    report_lines.append("|----------|----------|----------|--------|----------|")
                    for it in removed_items:
                        hold = it.get('hold_days')
                        price = it.get('price')
                        report_lines.append(
                            f"| {it.get('code', '')} | {it.get('name', '')} | "
                            f"{hold if hold is not None else '-'} | "
                            f"{f'¥{price:.2f}' if price else '-'} | "
                            f"{it.get('reason', '') or '—'} |")
                    report_lines.append("")
            
            # 交易信号
            buy_signals = record.get('buy_signals', [])
            sell_signals = record.get('sell_signals', [])
            
            if buy_signals or sell_signals:
                report_lines.append("## 📈 交易信号")
                report_lines.append("")
                
                if buy_signals:
                    report_lines.append(f"### 买入信号 ({len(buy_signals)}个)")
                    report_lines.append("")
                    for signal in buy_signals:
                        status = "⏳ 待执行" if not signal.get('executed') else "✅ 已执行"
                        report_lines.append(f"- **{signal['stock_code']} {signal['stock_name']}**: {signal['reason']}")
                        report_lines.append(f"  - 价格: ¥{signal['price']} | 数量: {signal['quantity']}股 | 金额: ¥{signal['amount']:.2f}")
                        report_lines.append(f"  - 策略: {self._get_strategy_name(signal['strategy_name'])} | {status}")
                    report_lines.append("")
                
                if sell_signals:
                    report_lines.append(f"### 卖出信号 ({len(sell_signals)}个)")
                    report_lines.append("")
                    for signal in sell_signals:
                        status = "⏳ 待执行" if not signal.get('executed') else "✅ 已执行"
                        report_lines.append(f"- **{signal['stock_code']} {signal['stock_name']}**: {signal['reason']}")
                        report_lines.append(f"  - 价格: ¥{signal['price']} | 数量: {signal['quantity']}股 | 金额: ¥{signal['amount']:.2f}")
                        report_lines.append(f"  - 策略: {self._get_strategy_name(signal['strategy_name'])} | {status}")
                    report_lines.append("")
            else:
                report_lines.append("## 📈 交易信号")
                report_lines.append("")
                report_lines.append("今日无交易信号")
                report_lines.append("")
            
            # 持仓状态
            portfolio = record.get('portfolio', {})
            report_lines.append("## 📦 持仓状态")
            report_lines.append("")
            if portfolio:
                total_value = 0
                total_profit = 0
                report_lines.append(f"当前持有 **{len(portfolio)}** 只股票：")
                report_lines.append("")
                report_lines.append("| 股票代码 | 股票名称 | 持仓数量 | 成本价 | 现价 | 盈亏 | 止损价 | 持有天数 |")
                report_lines.append("|----------|----------|----------|--------|------|------|--------|----------|")
                for code, pos in portfolio.items():
                    profit_rate = pos.get('profit_rate', 0)
                    profit_sign = "+" if profit_rate >= 0 else ""
                    stop_loss_price = pos.get('stop_loss_price', 0)
                    stop_loss_display = f"¥{stop_loss_price:.2f}" if stop_loss_price > 0 else "-"
                    report_lines.append(f"| {code} | {pos['stock_name']} | {pos['quantity']} | ¥{pos['buy_price']} | ¥{pos['current_price']} | {profit_sign}{pos['profit_loss']:.2f} | {stop_loss_display} | {pos.get('holding_days', 0)} |")
                    total_value += pos['quantity'] * pos['current_price']
                    total_profit += pos.get('profit_loss', 0)
                report_lines.append("")
                report_lines.append(f"- **持仓总市值**: ¥{total_value:.2f}")
                report_lines.append(f"- **持仓总盈亏**: {'+' if total_profit >= 0 else ''}{total_profit:.2f}")
            else:
                report_lines.append("暂无持仓")
            report_lines.append("")
            
            # 策略执行结果
            task_results = record.get('task_results', [])
            if task_results:
                report_lines.append("## 📋 策略执行详情")
                report_lines.append("")
                for task in task_results:
                    report_lines.append(f"- **{self._get_strategy_name(task['selection_strategy'])}**")
                    report_lines.append(f"  - 选出: {task['selected_count']}只 | 新增: {task['new_added']}只 | 池内: {task['pool_count']}只")
                    report_lines.append(f"  - 状态: {'✅ 成功' if task['status'] == 'success' else '❌ 失败'}")
                report_lines.append("")
            
            # 生成时间
            report_lines.append(f"---")
            report_lines.append(f"*报告生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
            
            # 保存报告
            report_file = self.running_dir / f"daily_{date}.md"
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_lines))
            
            logger.info(f"文字版日报已保存到: {report_file}")
            
        except Exception as e:
            logger.error(f"生成每日报告失败: {str(e)}")
    
    def _get_strategy_name(self, strategy_class_name: str) -> str:
        """将策略类名转换为中文名称

        【2026-09-24】优先走**统一映射表**（`utils.strategy_name_mapper.get_chinese_name` ✓）
          —— 原实现是**本方法内的一份硬编码字典** ✗（且键几乎只有全类名 ✗），
             传入短名（如 `GoldenTriangle` ✗）时原样返回英文 ✗，
             与 `config/strategy_name_mapping.yaml` 形成**两份口径** ✗，
             导致本地日报/简报里策略名显示英文 ✗。
          现：统一映射优先 ✓（支持短名 / 全类名 / 蛇形名归一化 ✓），
              下方本地字典仅作**兜底** ✓（保留历史条目，避免既有显示回退 ✓）。
        """
        try:
            from utils.strategy_name_mapper import get_chinese_name
            _cn = get_chinese_name(strategy_class_name)
            if _cn and _cn != strategy_class_name:
                return _cn
        except Exception:
            pass
        name_mapping = {
            'ImmortalGuidanceStrategy': '仙人指路策略',
            'LimitUpSidewaysStrategy': '涨停横盘策略',
            'LimitUpPullbackStrategy': '涨停回马枪策略',
            'MACDReversalStrategy': 'MACD反转策略',
            'BullishHaramiStrategy': '多方炮策略',
            'BottomTrendReversalStrategy': '底部趋势拐点策略',
            'ResistanceBreakoutStrategy': '阻力位突破策略',
            'MainUptrendDipBuyStrategy': '主升低吸策略',
            'NewStockDrawdownStrategy': '次新腰斩策略',
            'MultiPartyCannonStrategy': '多方炮策略',
            'MorningStarStrategy': '启明星策略',
            'TrendStartStrategy': '趋势起点策略',
            'Strategy2560Selection': '2560战法',
            'GoldenTriangleStrategy': '金三角策略',
            'ShunShiBaoStrategy': '顺势宝',
            'turtle': '海龟策略',
            'bollinger': '布林带策略',
            'rsi': 'RSI策略',
            'support': '支撑位策略',
            'uptrend_pullback': '趋势回调缩量策略'
        }
        return name_mapping.get(strategy_class_name, strategy_class_name)
    
    def _get_stock_data(self, stock_code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """获取股票数据
        
        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            股票数据DataFrame
        """
        try:
            # 尝试从缓存获取
            cache_key = f"{stock_code}_{start_date}_{end_date}"
            if cache_key in self.stock_data_cache:
                return self.stock_data_cache[cache_key]
            
            # 计算需要获取的天数
            from datetime import datetime
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            days = (end_dt - start_dt).days + 1
            
            # 从数据源获取
            df = self.stock_data_fetcher.fetch_stock_update(stock_code, days=days)
            if df is not None and not df.empty:
                # 按日期范围过滤
                df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
                self.stock_data_cache[cache_key] = df
                return df
            return None
        except Exception as e:
            logger.error(f"获取股票数据失败 {stock_code}: {str(e)}")
            return None
    
    def _get_stock_data_from_db(self, stock_code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """从本地数据库获取股票数据（用于卖出操作，不依赖外部API）
        
        与 _get_stock_data() 返回格式一致：
        - 倒序排列（最新在前），iloc[0] 为最新数据
        - 包含 date/open/high/low/close/volume 等列
        
        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame 或 None
        """
        try:
            # 尝试从缓存获取
            cache_key = f"{stock_code}_{start_date}_{end_date}"
            if cache_key in self.stock_data_cache:
                return self.stock_data_cache[cache_key]
            
            # 数据库 stock_kline 表中代码无 .SZ/.SH 后缀，需去除
            db_code = stock_code.replace('.SZ', '').replace('.SH', '')
            
            # 从本地数据库 stock_kline 表查询，默认倒序排列
            df = self.db_manager.read_stock(db_code, start_date=start_date, end_date=end_date)
            # read_stock 返回空 DataFrame（非 None）表示无数据
            if df is not None and not df.empty:
                # 缓存命中后写入
                self.stock_data_cache[cache_key] = df
                return df
            # 查询无结果
            logger.warning(f"数据库无 {stock_code} 在 {start_date}~{end_date} 的数据")
            return None
        except Exception as e:
            # DB 查询异常，记录日志后返回 None
            logger.error(f"从数据库获取股票数据失败 {stock_code}: {str(e)}")
            return None
    
    def _get_stock_name(self, stock_code: str) -> str:
        """获取股票名称
        
        Args:
            stock_code: 股票代码
            
        Returns:
            股票名称
        """
        try:
            if stock_code in self.stock_name_cache:
                return self.stock_name_cache[stock_code]
            
            # 从数据库获取
            query = "SELECT name FROM stock_basic WHERE code = ?"
            result = self.db_manager.query_one(query, (stock_code,))
            if result:
                name = result['name']
                self.stock_name_cache[stock_code] = name
                return name
            return stock_code
        except Exception as e:
            logger.error(f"获取股票名称失败 {stock_code}: {str(e)}")
            return stock_code
    
    def _calc_trailing_stop(self, buy_price, current_price, holding_df,
                            enable_trailing_stop=True, base_stop_level=-6,
                            trailing_trigger_threshold=5,
                            trailing_drawdown_pct=8):
        """计算移动止损价(通用方法，便于单元测试)

        直接基于持仓期K线的最高价计算移动止损：
        - 持仓期最高收益率 >= 触发阈值(默认5%)：移动止损 = 最高价 × (1 - 回撤%)
        - 否则(或未启用/无数据)：固定止损 = 买入价 × (1 + 基础止损)

        Args:
            buy_price: 买入价
            current_price: 当前价(无持仓期数据时兜底作为最高价)
            holding_df: 持仓期K线DataFrame(需含 'high' 列)，来自持久化数据库
            enable_trailing_stop: 是否启用移动止损
            base_stop_level: 基础止损百分比(默认 -6)
            trailing_trigger_threshold: 触发移动止损的最低收益率(%)
            trailing_drawdown_pct: 移动止损自最高价的回撤比例(%)，默认 8
                                   （设为 6 可更早锁定盈利）

        Returns:
            (stop_price, current_stop, highest_price, highest_price_return)
        """
        # 默认按固定止损初始化(买入价 × (1 - 6%))
        current_stop = base_stop_level / 100
        highest_price = current_price  # 无数据时以当前价作为最高价
        highest_price_return = 0
        stop_price = buy_price * (1 + current_stop)

        # 仅在启用且有持仓期数据时计算移动止损
        if enable_trailing_stop and holding_df is not None and not holding_df.empty:
            highest_price = holding_df['high'].max()  # 持仓期最高价
            # 最高收益率 = (最高价 - 买入价) / 买入价
            highest_price_return = (highest_price - buy_price) / buy_price * 100
            # 达到触发阈值才启用移动止损：最高价 × (1 - 回撤%)
            if highest_price_return >= trailing_trigger_threshold:
                stop_price = highest_price * (1 - trailing_drawdown_pct / 100)
                current_stop = (stop_price - buy_price) / buy_price

        return stop_price, current_stop, highest_price, highest_price_return

    @staticmethod
    def _exclude_buy_day(holding_df, buy_date):
        """排除首次建仓日当天的K线，返回用于移动止损的持仓期数据

        背景：买入当天的最高价可能形成于实际成交之前（当时尚未持仓），
        若计入"买入以来最高价"会虚高最高价，进而把移动止损位错误抬高，
        极端情况下刚建仓就误触发止损。

        口径：仅排除首次建仓日；移动止损基准仍自首次建仓日起算（不含当天那根K线）。

        Args:
            holding_df: 持仓期K线DataFrame（需含 'date' 列）
            buy_date: 首次建仓日（YYYY-MM-DD）

        Returns:
            排除建仓日后的DataFrame；若过滤后无剩余数据（如当日建仓当日检查）
            返回 None，由调用方按固定止损(-6%)兜底，坚决不使用买入当天高点
        """
        # 无数据或缺少建仓日时原样返回，不改变既有兜底行为
        if holding_df is None or holding_df.empty or not buy_date:
            return holding_df
        _buy_date_str = str(buy_date)
        # 剔除建仓日当天，移动止损区间自买入次日起算
        filtered = holding_df[holding_df['date'].astype(str) != _buy_date_str]
        # 过滤后无数据 → 返回 None，避免回退使用买入当天的高点
        return filtered if not filtered.empty else None

    def _resolve_first_buy_date(self, stock_code: str, position: Dict) -> str:
        """从持久化账本解析首次建仓日（移动止损"买入以来"区间的权威起点）

        直接使用 position_tracking.json（持久化账本）的 first_buy_date，而非依赖
        self.portfolio（其 buy_date 为 PTrade 同步日、且键可能带后缀导致合并查不到）。
        账本无记录时回退到 portfolio 的 first_buy_date / buy_date。

        Args:
            stock_code: 持仓键（可能带 .SZ/.SH 后缀）
            position: 当前持仓字典（可能缺失 first_buy_date）

        Returns:
            首次建仓日 YYYY-MM-DD（缺失时回退为空字符串）
        """
        # 优先直接读取持久化账本（权威来源），避免内存 merge 因键格式不一致漏合
        ledger = getattr(self, 'position_tracking', None)
        if not ledger:
            ledger = self._load_position_tracking()
        # 账本键为无后缀代码，持仓键可能带后缀，两种都试
        track = ledger.get(stock_code)
        if track is None:
            track = ledger.get(stock_code.replace('.SZ', '').replace('.SH', ''))
        if track and track.get('first_buy_date'):
            return track.get('first_buy_date')
        # 账本无记录时回退 portfolio 字段（本地建仓等场景）
        return position.get('first_buy_date') or position.get('buy_date', '')

    def _execute_sell_operations(self, trade_date: str, config: Dict = None) -> List[Dict]:
        """执行卖出操作
        
        Args:
            trade_date: 交易日期
            config: 运行时配置参数（从回测配置获取的止盈止损参数）
            
        Returns:
            卖出信号列表
        """
        sell_signals = []
        
        # 记录当日卖出的股票（用于限制当天卖出的股票不买入，且卖出后不算加仓）
        if not hasattr(self, '_today_sold_stocks'):
            self._today_sold_stocks = set()
        
        try:
            # 从运行时配置获取止盈止损参数（与回测引擎保持一致）
            # 回测配置中 take_profit/stop_loss 单位是百分比（如 21 表示 21%）
            # 策略运行器使用小数（如 0.21 表示 21%）
            # 优先级：运行时config > 实例self.config > 默认值
            if config and 'take_profit' in config and 'stop_loss' in config:
                take_profit_percent = config.get('take_profit')
                stop_loss_percent = config.get('stop_loss')
            elif hasattr(self, 'config') and 'take_profit_threshold' in self.config:
                # 从实例配置获取（已转换为小数形式）
                take_profit_threshold = self.config.get('take_profit_threshold')
                stop_loss_threshold = self.config.get('stop_loss_threshold')
                logger.info(f"从实例配置获取止盈止损: take_profit={take_profit_threshold*100:.0f}%, stop_loss={stop_loss_threshold*100:.0f}%")
            else:
                # 使用默认值
                take_profit_percent = 15
                stop_loss_percent = -5
            
            # 转换为小数阈值
            if 'take_profit_threshold' not in locals():
                take_profit_threshold = take_profit_percent / 100
            if 'stop_loss_threshold' not in locals():
                stop_loss_threshold = stop_loss_percent / 100
            
            # 记录当前资金和持仓情况；总资产直接采用 PTrade 反馈权威值（含 ETF），不在此重算
            positions_count = len(self.portfolio)
            available_cash = getattr(self, 'current_total_capital', 0)
            total_assets = getattr(self, 'current_total_asset', None) or 0

            logger.info(f"【卖出准备】{trade_date} 当前资金: ¥{available_cash:.2f}, 持仓: {positions_count}只, "
                       f"总资产(PTrade权威值): ¥{total_assets:.2f}")
            
            # 获取持仓过期配置（提高资金利用率）
            enable_position_expire = self.config.get('enable_position_expire', True)
            position_expire_hold_days = self.config.get('position_expire_hold_days', 10)
            position_expire_return_threshold = self.config.get('position_expire_return_threshold', 5) / 100  # 转换为小数
            
            # 遍历持仓股票（跳过持仓为0的空仓位，避免对已清仓股票生成卖出信号）
            stocks_to_remove = []
            for stock_code, position in self.portfolio.items():
                # 跳过持仓数量为0的空仓位
                if position.get('quantity', 0) <= 0:
                    logger.info(f"【卖出跳过】{stock_code} 持仓为0，跳过卖出检查")
                    continue
                
                # 获取股票数据
                end_date = trade_date
                start_date = (datetime.datetime.strptime(end_date, '%Y-%m-%d') - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
                df = self._get_stock_data_from_db(stock_code, start_date, end_date)
                
                if df is None or df.empty:
                    logger.warning(f"获取股票数据失败 {stock_code}，跳过卖出检查")
                    continue
                
                # 调用择时策略判断，传入 stock_code 以隔离技术指标缓存
                timing_result = self.timing_strategy.get_timing_result(df, position, use_prev_day_signal=False, stock_code=stock_code)

                # 检查止损止盈
                # 注意：缓存数据是倒序排列的（最新日期在前面）
                current_price = df.iloc[0]['close']
                open_price = df.iloc[0]['open']
                buy_price = position['buy_price']
                # 直接读取持久化账本解析首次建仓日（权威），避免 portfolio 的 buy_date
                # 为 PTrade 同步日、或键带后缀导致 merge 查不到，使移动止损区间被截断
                buy_date = self._resolve_first_buy_date(stock_code, position)
                profit_rate = (current_price - buy_price) / buy_price

                # 更新持仓的现价（确保前端显示最新价格）
                position['current_price'] = current_price
                position['profit_rate'] = profit_rate
                position['profit_loss'] = (current_price - buy_price) * position['quantity']

                # ========== 移动止损逻辑 ==========
                # 配置参数
                enable_trailing_stop = self.config.get('enable_trailing_stop', True)
                base_stop_level = -6  # 基础止损固定为-6%
                trailing_trigger_threshold = 5  # 触发移动止损的最低收益率
                # 移动止损自最高价的回撤比例(%，默认8；设为 6 可更早锁定盈利)
                trailing_drawdown_pct = self.config.get('trailing_drawdown_pct', 8)

                # 移动止损：直接基于持仓期K线(持久化数据库)最高价计算
                # 先确定持仓期K线来源：优先持久化数据库(建仓日到当日)，缺数据兜底用近期数据
                holding_df = None
                data_source = 'none'
                if enable_trailing_stop and buy_date:
                    # _get_stock_data_from_db 内部已按数据库代码规范(去后缀)查询，避免
                    # 内存缓存键格式(无后缀)与持仓键(带后缀)不一致导致查不到、移动止损失效
                    # 注意：实盘收盘后运行(>15:00)，当日OHLC已完整，纳入持仓期计算
                    holding_df = self._get_stock_data_from_db(stock_code, buy_date, trade_date)
                    if holding_df is not None and not holding_df.empty:
                        data_source = 'db'
                # 兜底：建仓日缺失或持久化读取失败时，使用已抓取的近期数据
                if holding_df is None or holding_df.empty:
                    if df is not None and not df.empty:
                        holding_df = df.copy()
                        data_source = 'recent_df'
                # 排除首次建仓日当天K线：其最高价可能形成于成交之前（当时尚未持仓），
                # 计入会虚高"买入以来最高价"而错误抬高移动止损位。
                # 过滤后无剩余数据（如当日建仓当日检查）→ None → 固定止损(-6%)兜底
                holding_df = self._exclude_buy_day(holding_df, buy_date)
                if holding_df is None and data_source in ('db', 'recent_df'):
                    data_source = 'excluded_buy_day'

                # 调用通用移动止损计算(含最高价/最高收益率/止损价)，便于单元测试
                stop_price, current_stop, highest_price, highest_price_return = \
                    self._calc_trailing_stop(buy_price, current_price, holding_df,
                                             enable_trailing_stop, base_stop_level,
                                             trailing_trigger_threshold,
                                             trailing_drawdown_pct)

                logger.debug(f"  移动止损: 买入价={buy_price:.2f}, 最高价={highest_price:.2f}, 当前价={current_price:.2f}, 最高收益率={highest_price_return:.2f}%, 止损价={stop_price:.2f}(回撤{trailing_drawdown_pct}%), 数据来源={data_source}")
                # ========== 移动止损逻辑结束 ==========

                # 记录择时信号详情
                stock_name = position['stock_name']
                
                # 生成卖出信号
                if timing_result.is_sell or profit_rate >= take_profit_threshold or profit_rate <= current_stop:
                    # 确定卖出原因
                    if timing_result.is_sell:
                        reason = timing_result.message
                        signal_type = 'strategy_sell'
                    elif profit_rate >= take_profit_threshold:
                        reason = f'止盈 (收益率: {profit_rate*100:.2f}%)'
                        signal_type = 'take_profit'
                    elif enable_trailing_stop and current_stop > stop_loss_threshold:
                        reason = f'移动止损 (最高收益率: {highest_price_return:.2f}%, 当前收益率: {profit_rate*100:.2f}%, 止损线: {current_stop*100:.2f}%)'
                        signal_type = 'trailing_stop'
                    else:
                        reason = f'止损 (收益率: {profit_rate*100:.2f}%)'
                        signal_type = 'stop_loss'
                    
                    # 计算止损价
                    stop_price = (highest_price * (1 - trailing_drawdown_pct / 100)
                                  if enable_trailing_stop and highest_price_return >= trailing_trigger_threshold
                                  else buy_price * (1 + current_stop))
                    
                    # 构建止损方式说明
                    if enable_trailing_stop and highest_price_return >= trailing_trigger_threshold:
                        stop_method = (f"移动止损(最高价{highest_price:.2f}×"
                                       f"{100 - trailing_drawdown_pct:.0f}%="
                                       f"{highest_price * (1 - trailing_drawdown_pct / 100):.2f})")
                    else:
                        stop_method = f"固定止损({base_stop_level}%)"
                    
                    # 记录卖出决策
                    logger.info(f"【卖出信号】{trade_date} {stock_code} {stock_name} | "
                               f"持仓: {position['quantity']}股 | "
                               f"成本: ¥{buy_price:.2f} | 现价: ¥{current_price:.2f} | "
                               f"收益率: {profit_rate*100:.2f}% | "
                               f"止损价: ¥{stop_price:.2f} [{stop_method}] | "
                               f"信号类型: {signal_type} | 原因: {reason}")
                    
                    signal = {
                        'id': f"sell_{stock_code}_{trade_date}",
                        'date': trade_date,
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'signal_type': 'sell',  # 统一为 'sell'，便于前端统计
                        'sell_type': signal_type,  # 保存具体的卖出类型
                        'quantity': position['quantity'],
                        'price': current_price,
                        'amount': current_price * position['quantity'],
                        'profit_rate': profit_rate,
                        'reason': reason,
                        'strategy_name': position.get('strategy_name', 'N/A'),
                        'timing_strategy': self.timing_strategy_name,
                        'executed': False,
                        'executed_date': None
                    }
                    # 保存止损价到持仓
                    position['stop_loss_price'] = round(stop_price, 2)
                    
                    sell_signals.append(signal)
                    stocks_to_remove.append(stock_code)
                    # 记录当日卖出的股票（用于限制当天卖出的股票不买入，且卖出后不算加仓）
                    self._today_sold_stocks.add(stock_code)
                else:
                    # 没有卖出信号，记录日志
                    # 计算止损价格（参考回测引擎逻辑）
                    stop_price = (highest_price * (1 - trailing_drawdown_pct / 100)
                                  if enable_trailing_stop and highest_price_return >= trailing_trigger_threshold
                                  else buy_price * (1 + current_stop))
                    # 构建止损方式说明
                    if enable_trailing_stop and highest_price_return >= trailing_trigger_threshold:
                        stop_method = (f"移动止损(最高价{highest_price:.2f}×"
                                       f"{100 - trailing_drawdown_pct:.0f}%="
                                       f"{highest_price * (1 - trailing_drawdown_pct / 100):.2f})")
                    else:
                        stop_method = f"固定止损({base_stop_level}%)"
                    
                    # 保存止损价到持仓
                    position['stop_loss_price'] = round(stop_price, 2)
                    
                    # 持仓过期检查
                    if enable_position_expire and profit_rate <= position_expire_return_threshold:
                        # 计算持有天数（复用上方已解析的首次建仓日 buy_date，优先取账本 first_buy_date，
                        # 避免直接使用 position['buy_date']——其为 PTrade 同步日，会使持有天数被算成 0）
                        hold_days = self._calculate_hold_days(buy_date, trade_date)
                        if hold_days > position_expire_hold_days:
                            reason = f'持仓过期 (持有{hold_days}天, 收益率{profit_rate*100:.2f}%<={position_expire_return_threshold*100:.0f}%)'
                            signal_type = 'position_expire'
                            
                            signal = {
                                'id': f"sell_{stock_code}_{trade_date}",
                                'date': trade_date,
                                'stock_code': stock_code,
                                'stock_name': stock_name,
                                'signal_type': 'sell',
                                'sell_type': signal_type,
                                'quantity': position['quantity'],
                                'price': current_price,
                                'amount': current_price * position['quantity'],
                                'profit_rate': profit_rate,
                                'reason': reason,
                                'strategy_name': position.get('strategy_name', 'N/A'),
                                'timing_strategy': self.timing_strategy_name,
                                'executed': False,
                                'executed_date': None
                            }
                            
                            logger.info(f"【卖出信号】{trade_date} {stock_code} {stock_name} | "
                                       f"持仓: {position['quantity']}股 | "
                                       f"成本: ¥{buy_price:.2f} | 现价: ¥{current_price:.2f} | "
                                       f"收益率: {profit_rate*100:.2f}% | "
                                       f"信号类型: {signal_type} | 原因: {reason}")
                            
                            sell_signals.append(signal)
                            stocks_to_remove.append(stock_code)
                            self._today_sold_stocks.add(stock_code)
                        else:
                            logger.info(f"【无卖出信号】{trade_date} {stock_code} {stock_name} | "
                                       f"持仓: {position['quantity']}股 | "
                                       f"成本: ¥{buy_price:.2f} | 现价: ¥{current_price:.2f} | "
                                       f"收益率: {profit_rate*100:.2f}% | "
                                       f"止损价: ¥{stop_price:.2f} [{stop_method}] | "
                                       f"择时卖出: {timing_result.is_sell} | 止盈未触发 | 止损未触发 | 持仓过期未触发(持{hold_days}天)")
                    else:
                        logger.info(f"【无卖出信号】{trade_date} {stock_code} {stock_name} | "
                                   f"持仓: {position['quantity']}股 | "
                                   f"成本: ¥{buy_price:.2f} | 现价: ¥{current_price:.2f} | "
                                   f"收益率: {profit_rate*100:.2f}% | "
                                   f"止损价: ¥{stop_price:.2f} [{stop_method}] | "
                                   f"择时卖出: {timing_result.is_sell} | 止盈未触发 | 止损未触发")
            
            # 注意：不立即删除持仓，只生成卖出信号
            # 持仓将在实际执行卖出信号时（T+1日）才被删除
            
            # ========== 更新冷却池和连续亏损计数 ==========
            # 2026-09-16 新规则：**任意清仓卖出**即冷却 1 个月（21 个交易日，盈利同样冷却）；
            # 连续亏损 2 次冷却 1 年（250 个交易日）。判定与回测共用同一函数，逻辑见
            # _register_sell_cool_down。
            for sell_signal in sell_signals:
                self._register_sell_cool_down(
                    sell_signal['stock_code'],
                    sell_signal.get('profit_rate', 0) or 0,
                    trade_date)
            # ========== 冷却池和连续亏损计数更新结束 ==========
            
            logger.info(f"【卖出汇总】{trade_date} 执行卖出操作，生成 {len(sell_signals)} 个卖出信号，共检查 {len(self.portfolio) + len(stocks_to_remove)} 只持仓")
            
            # 保存更新后的持仓（包含现价更新）
            portfolio_file = self.running_dir / f"portfolio_{trade_date}.json"
            self._save_portfolio(self.portfolio, str(portfolio_file))
            
        except Exception as e:
            logger.error(f"执行卖出操作失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        
        return sell_signals
    
    def _execute_buy_operations(self, trade_date: str, initial_cash: float, check_capital: bool = False) -> List[Dict]:
        """执行买入操作
        
        Args:
            trade_date: 交易日期
            initial_cash: 初始资金
            check_capital: 是否检查资金限制，默认False（T日生成信号时不限制）
            
        Returns:
            买入信号列表
        """
        buy_signals = []
        
        try:
            # 获取当前可用资金（从配置文件加载的初始资金，或从持仓文件恢复的资金）
            if not hasattr(self, 'current_total_capital'):
                self.current_total_capital = initial_cash
            
            # current_total_capital 直接表示可用资金，不需要重置
            current_cash = self.current_total_capital
            
            # T日生成信号模式：不限制资金
            if not check_capital:
                logger.info(f"【买入检查】{trade_date} T日信号生成模式 | 可用资金: ¥{current_cash:.2f} | "
                           f"持仓: {len(self.portfolio)} | 候选股票: {len(self.buy_candidate_pool)}")
            else:
                # T+1日执行模式：检查资金
                if current_cash < 2000:
                    logger.info(f"【买入检查】{trade_date} 可用资金不足2000元 (¥{current_cash:.2f})，跳过买入操作")
                    return buy_signals
                if current_cash <= 0:
                    logger.info(f"【买入检查】{trade_date} 可用资金为负 (¥{current_cash:.2f})，跳过买入操作")
                    return buy_signals
                logger.info(f"【买入检查】{trade_date} T+1日执行模式 | 可用资金: ¥{current_cash:.2f} | "
                           f"持仓: {len(self.portfolio)} | 候选股票: {len(self.buy_candidate_pool)}")
            
            # 遍历可买股票池
            for candidate in self.buy_candidate_pool:
                
                # 适配新的股票池结构
                stock_info = candidate.get('stock', candidate)
                stock_code = stock_info['stock_code']
                stock_name = stock_info['stock_name']
                score = stock_info.get('score', 0)
                
                # ========== 检查冷却期 ==========
                # 使用 _check_cool_down 方法检查，该方法会自动更新过期的冷却状态
                if self._check_cool_down(stock_code, trade_date):
                    cool_down_end = candidate.get('cool_down_end', 'N/A')
                    logger.info(f"【买入检查】{trade_date} {stock_code} 在冷却期内（至 {cool_down_end}），跳过")
                    continue
                # ========== 冷却期检查结束 ==========
                
                # ========== 检查当日是否卖出 ==========
                # 当日卖出的股票当日不买入（参考回测引擎逻辑）
                today_sold_stocks = getattr(self, '_today_sold_stocks', set())
                if stock_code in today_sold_stocks:
                    logger.info(f"【买入检查】{trade_date} {stock_code} 当日已卖出，跳过买入")
                    continue
                # ========== 当日卖出检查结束 ==========
                
                # 获取股票数据（优先从缓存获取）
                df = self.stock_filtered_cache.get(stock_code)
                if df is None:
                    logger.debug(f"【买入检查】{trade_date} {stock_code} {stock_name} 获取股票数据失败，跳过")
                    continue
                
                # 日期切片
                df_to_date = df[df['date'] <= trade_date].copy()
                if df_to_date.empty:
                    logger.debug(f"【买入检查】{trade_date} {stock_code} {stock_name} 无有效数据，跳过")
                    continue
                
                # 反转为倒序
                if len(df_to_date) > 1 and df_to_date['date'].iloc[0] < df_to_date['date'].iloc[-1]:
                    df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)
                
                # 检查是否已在持仓中
                existing_pos = self.portfolio.get(stock_code)
                
                # 调用择时策略判断，传入 stock_code 以隔离技术指标缓存
                timing_result = self.timing_strategy.get_timing_result(df_to_date, existing_pos, current_cash, use_prev_day_signal=False, stock_code=stock_code)
                
                # 记录择时信号详情
                current_price = df_to_date.iloc[0]['close']  # 倒序数据，iloc[0]是最新数据
                
                # 买入执行价：与回测共用 config/backtest_engine_config.yaml 的 buy_execution 配置
                # open(默认)=T日收盘价（原行为） | ma_limit=均线委托价（仅生成委托，实际成交以PTrade反馈为准）
                exec_result = self._resolve_buy_execution(stock_code, df_to_date, current_price)
                buy_price = exec_result['price']
                if exec_result['mode'] != 'open':
                    logger.info(f"【买入执行方式】{trade_date} {stock_code} {stock_name} | "
                               f"mode={exec_result['mode']} | {exec_result['reason']}")
                
                logger.info(f"【择时信号】{trade_date} {stock_code} {stock_name} | "
                           f"评分: {score:.1f} | 现价: ¥{current_price:.2f} | "
                           f"支撑位: ¥{candidate.get('support_level', 0):.2f} | "
                           f"买入信号: {timing_result.is_buy} | "
                           f"加仓信号: {timing_result.trade_type == 'add'} | "
                           f"信号强度: {timing_result.signal_strength:.2f} | "
                           f"信息: {timing_result.message}")
                
                # 生成买入信号
                if timing_result.is_buy:
                    # 根据交易类型决定买入数量计算方式
                    if timing_result.trade_type == 'add':
                        # 加仓（不检查涨幅、不检查重复信号）：
                        # 数量 = max(策略信号数量, 1/2 凯利金额对应数量)
                        trade_type = 'add'  # 加仓
                        signal_qty = timing_result.buy_quantity or 0
                        half_kelly_qty = 0
                        add_kelly_amount = 0.0
                        _add_total_assets = getattr(self, 'current_total_asset', None)
                        if _add_total_assets and _add_total_assets > 0:
                            add_kelly_amount = KellyCalculator.calculate_position_amount(
                                total_capital=_add_total_assets,
                                available_cash=current_cash,
                                strategy_name=candidate.get('strategy_name', 'N/A')
                            )
                            half_kelly_qty = KellyCalculator.calculate_buy_quantity(
                                position_amount=add_kelly_amount / 2,
                                price=buy_price,
                                stock_code=stock_code
                            )
                        else:
                            logger.warning(f"【加仓数量】{trade_date} {stock_code} {stock_name} "
                                           f"未获取到 PTrade 权威总资产，1/2 凯利金额不可用，"
                                           f"按策略信号数量 {signal_qty} 股执行")
                        buy_quantity = max(signal_qty, half_kelly_qty)
                        quantity_source = ('择时策略（加仓）' if buy_quantity == signal_qty
                                           else '半凯利金额（加仓）')
                        logger.info(f"【加仓数量】{trade_date} {stock_code} {stock_name} | "
                                    f"策略信号: {signal_qty}股 | 1/2凯利金额: ¥{add_kelly_amount / 2:.2f} "
                                    f"→ {half_kelly_qty}股 | 取大者: {buy_quantity}股 ({quantity_source})")
                    else:
                        # 首次建仓：使用凯莉公式计算
                        trade_type = 'first'  # 首次建仓
                        
                        # ========== 涨幅检查：相对20日最低点涨幅 > 50% 跳过（仅首次建仓）==========
                        # 使用T日收盘价为准，与回测引擎的T+1日开盘价逻辑有所不同
                        if len(df_to_date) >= 20:
                            # 获取20日内最低点（倒序数据，取最近20条）
                            low_20d = df_to_date.iloc[:20]['low'].min()
                            if low_20d > 0:
                                gain_from_low = (current_price - low_20d) / low_20d
                                if gain_from_low > 0.5:  # 涨幅超过50%
                                    logger.info(f"【买入检查】{trade_date} {stock_code} {stock_name} 相对20日最低点涨幅 {gain_from_low*100:.1f}% > 50%，跳过")
                                    continue
                        # ========== 涨幅检查结束 ==========
                        
                        # ========== 涨停基因检查：近30交易日(不含当日)至少1次涨停(>9.5%)（仅首次建仓）==========
                        # 复用回测引擎的 BuyPreFilter，保证两套流程规则一致
                        # 开关：enable_limit_up_check=false 时跳过该检查（用于提升成交率，默认开启）
                        # 开关统一取自 config/backtest_engine_config.yaml（与回测引擎同一配置源）
                        limit_up_enabled = self._load_engine_config().get('enable_limit_up_check', True)
                        if limit_up_enabled:
                            from trading.buy_filter import BuyPreFilter
                            limit_up_result = BuyPreFilter._check_limit_up_history(df_to_date, stock_code)
                            if not limit_up_result['passed']:
                                logger.info(f"【买入检查】{trade_date} {stock_code} {stock_name} "
                                            f"无涨停基因（{limit_up_result.get('reason', '')}），跳过首仓买入")
                                continue
                        else:
                            logger.info(f"【买入检查】{trade_date} {stock_code} {stock_name} "
                                        f"涨停基因检测已关闭（enable_limit_up_check=false），跳过该检查")
                        # ========== 涨停基因检查结束 ==========
                        
                        # ========== 重复信号检查：信号去重（仅首次建仓，与冷却期无关）==========
                        # 说明：此检查用于抑制"同一标的连续多天冒出首仓买入信号却未成交"的噪声，
                        # 属于信号级别去重，与买入候选池的"冷却期"(_check_cool_down/is_cooling，
                        # 因资金流向异常而冷却 3 天)是完全独立的两套机制，互不影响。
                        # 直接从信号文件中读取前 3 个交易日的信号，判断是否重复
                        from utils.trade_date_utils import get_previous_trading_day
                        prev_day1 = get_previous_trading_day(trade_date)
                        prev_day2 = get_previous_trading_day(prev_day1)
                        prev_day3 = get_previous_trading_day(prev_day2)
                        
                        has_repeat_signal = False
                        repeat_date = None
                        for check_date in [prev_day1, prev_day2, prev_day3]:
                            signals_file = self.running_dir / f"signals_{check_date}.json"
                            if signals_file.exists():
                                try:
                                    with open(signals_file, 'r', encoding='utf-8') as f:
                                        signals_data = json.load(f)
                                        if isinstance(signals_data, list):
                                            for signal in signals_data:
                                                if (signal.get('stock_code') == stock_code and 
                                                    signal.get('signal_type') == 'buy' and
                                                    signal.get('trade_type') == 'first'):
                                                    has_repeat_signal = True
                                                    repeat_date = check_date
                                                    break
                                    if has_repeat_signal:
                                        break
                                except Exception as e:
                                    logger.debug(f"【买入检查】读取信号文件 {signals_file} 失败: {str(e)}")
                        
                        if has_repeat_signal:
                            logger.info(f"【买入检查】{trade_date} {stock_code} {stock_name} 重复信号（前次信号: {repeat_date}），跳过")
                            continue
                        # ========== 重复信号检查结束 ==========
                        
                        strategy_name = candidate.get('strategy_name', 'N/A')
                        
                        # 总资产直接采用 PTrade 反馈文件的权威值（self.current_total_asset，已含 ETF 市值）。
                        # 该值在 sync_portfolio_from_ptrade 中已从 PTrade Fund 文件读取，不在此重算，
                        # 避免用「可用现金 + KHunter 持仓市值」反算时漏算 ETF 导致总资产偏低。
                        total_assets = getattr(self, 'current_total_asset', None)
                        if not total_assets or total_assets <= 0:
                            logger.error(f"【总资产计算】{trade_date} 未获取到 PTrade 反馈的权威总资产，"
                                         f"无法计算仓位金额，跳过买入信号 {candidate.get('code')}")
                            continue

                        logger.info(f"【总资产计算】{trade_date} 可用现金: ¥{current_cash:.2f}, "
                                   f"总资产(PTrade权威值): ¥{total_assets:.2f}")
                        
                        position_amount = KellyCalculator.calculate_position_amount(
                            total_capital=total_assets,
                            available_cash=current_cash,
                            strategy_name=strategy_name
                        )
                        buy_quantity = KellyCalculator.calculate_buy_quantity(
                            position_amount=position_amount,
                            price=buy_price,
                            stock_code=stock_code
                        )
                        quantity_source = '凯莉公式'
                        
                        # 记录买入数量计算详情
                        logger.info(f"【买入数量计算】{trade_date} {stock_code} {stock_name} | "
                                   f"凯利金额: ¥{position_amount:.2f} | 买入价: ¥{buy_price:.2f} (现价¥{current_price:.2f}) | "
                                   f"计算数量: {buy_quantity}股 | 策略: {strategy_name}")

                    from utils.stock_utils import get_min_trade_unit
                    min_unit = get_min_trade_unit(stock_code)
                    if buy_quantity < min_unit:
                        logger.info(f"【买入检查】{trade_date} {stock_code} {stock_name} 买入数量 {buy_quantity}股 < 最小交易单位{min_unit}股，跳过")
                        continue
                    
                    # 记录买入决策
                    logger.info(f"【买入决策】{trade_date} {stock_code} {stock_name} | "
                               f"数量: {buy_quantity}股 ({quantity_source}) | 价格: ¥{buy_price:.2f} | "
                               f"金额: ¥{buy_price * buy_quantity:.2f} | "
                               f"执行方式: {exec_result['mode']} | "
                               f"信号: {timing_result.message}")
                    
                    signal = {
                        'id': f"buy_{stock_code}_{trade_date}",
                        'date': trade_date,
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'signal_type': 'buy',
                        'trade_type': trade_type,  # 标记是首次建仓还是加仓
                        'quantity': buy_quantity,
                        'price': buy_price,
                        'amount': buy_price * buy_quantity,
                        'exec_mode': exec_result['mode'],           # open | ma_limit
                        'order_price': exec_result['order_price'],  # 委托价（open 模式下等于 price）
                        'reason': timing_result.message,
                        'strategy_name': candidate.get('strategy_name', 'N/A'),
                        'timing_strategy': self.timing_strategy_name,
                        'support_level': candidate.get('support_level', 0),
                        'executed': False,
                        'executed_date': None
                    }
                    buy_signals.append(signal)
                    
                    # T+1日执行模式：更新可用资金
                    if check_capital:
                        current_cash -= buy_price * buy_quantity
                        current_cash = round(current_cash, 2)
                        self.current_total_capital = current_cash
                
                # 记录加仓信号
                elif timing_result.trade_type == 'add' and existing_pos:
                    add_quantity = timing_result.buy_quantity if timing_result.buy_quantity > 0 else 100
                    logger.info(f"【加仓信号】{trade_date} {stock_code} {stock_name} | "
                               f"加仓数量: {add_quantity}股 | 价格: ¥{current_price:.2f} | "
                               f"金额: ¥{current_price * add_quantity:.2f} | "
                               f"加仓次数: {timing_result.add_count} | "
                               f"信号: {timing_result.message}")
                
                # 记录未生成买入信号的原因
                elif not timing_result.is_buy:
                    # 判断原因
                    reason = "不满足策略条件"
                    if timing_result.message:
                        reason = timing_result.message
                    elif existing_pos and timing_result.trade_type != 'add':
                        reason = "已有持仓但不满足加仓条件"
                    
                    logger.info(f"【未生成买入信号】{trade_date} {stock_code} {stock_name} | 原因: {reason}")
            
            logger.info(f"【买入汇总】{trade_date} 执行买入操作，生成 {len(buy_signals)} 个买入信号")
        except Exception as e:
            logger.error(f"执行买入操作失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        
        return buy_signals
    
    def _check_continuous_temp_risk(self, trade_date: str) -> Dict:
        """
        检查连续温度风控状态（仅记录警告，不阻止信号生成）
        
        根据连续温度风控规则检查当前日期的风控状态，返回风控评估结果。
        信号文件仍完整生成供回测追溯；PTrade 端根据风控结果自主决定是否执行实际交易。
        
        规则：
        - 0%仓位限制：allow_buy=False（警告级别）
        - 20%/50%仓位限制：按实际仓位比较决定
        
        Args:
            trade_date: 交易日期，格式 YYYY-MM-DD
            
        Returns:
            Dict: {'allow_buy': bool, 'message': str, 'position_ratio': float}
        """
        try:
            # 导入市场温度计算器
            from utils.market_temperature import MarketTemperature
            
            # 转换日期格式
            trade_date_str = trade_date.replace('-', '')
            
            # 获取市场温度数据（使用缓存）
            calculator = MarketTemperature()
            temp_data = calculator.calculate(trade_date_str, use_cache=True)
            
            position_ratio = temp_data.get('position_ratio', 1.0)
            action = temp_data.get('action', '正常执行')
            
            # 计算当前实际仓位
            current_position_ratio = self._calculate_current_position_ratio()
            
            # 根据连续温度风控规则判断
            if position_ratio == 0.0:
                # 0%仓位限制 - 禁止买入
                return {
                    'allow_buy': False,
                    'message': f'{action}，禁止买入操作',
                    'position_ratio': 0.0
                }
            elif position_ratio == 0.2 or position_ratio == 0.5:
                # 20%/50%仓位限制 - 与实际仓位比较
                if current_position_ratio >= position_ratio:
                    return {
                        'allow_buy': False,
                        'message': f'{action}，当前仓位{int(current_position_ratio*100)}% >= 限制{int(position_ratio*100)}%，跳过买入操作',
                        'position_ratio': position_ratio
                    }
                else:
                    return {
                        'allow_buy': True,
                        'message': f'{action}，当前仓位{int(current_position_ratio*100)}% < 限制{int(position_ratio*100)}%，允许买入',
                        'position_ratio': position_ratio
                    }
            else:
                # 无限制(100%) - 允许买入
                return {
                    'allow_buy': True,
                    'message': f'{action}，无仓位限制，允许买入',
                    'position_ratio': position_ratio
                }
                
        except Exception as e:
            logger.warning(f"【风控检查】连续温度风控检查失败，允许买入: {e}")
            return {
                'allow_buy': True,
                'message': '连续温度风控检查失败，允许买入',
                'position_ratio': 1.0
            }
    
    def _calculate_current_position_ratio(self) -> float:
        """
        计算当前实际仓位比例
        
        Returns:
            float: 当前仓位比例 (0.0 ~ 1.0)
        """
        try:
            # 持仓市值（KHunter 持仓，不含 ETF），仅用于分子
            position_value = 0
            for code, pos in self.portfolio.items():
                pos_price = pos.get('current_price', pos.get('buy_price', 0))
                position_value += pos['quantity'] * pos_price

            # 分母直接采用 PTrade 反馈的权威总资产（含 ETF 市值），不在此重算
            total_assets = getattr(self, 'current_total_asset', None)
            if not total_assets or total_assets <= 0:
                logger.error("【仓位比例】未获取到 PTrade 反馈的权威总资产，无法计算仓位比例")
                return 0.0

            return position_value / total_assets
                
        except Exception as e:
            logger.warning(f"计算当前仓位比例失败: {e}")
            return 0.0
    
    # 需要合并顶层 config 专用参数的海龟类策略
    #   名单唯一来源：trading.timing_strategies.TURTLE_FAMILY_STRATEGIES
    #   （2026-09-16：新增海龟plus 时回测/自适应/运行器曾各写一份名单，三处都漏改）
    TURTLE_STRATEGY_NAMES = TURTLE_FAMILY_STRATEGIES

    @staticmethod
    def _build_turtle_params(config: Dict, timing_params: Dict, timing_strategy: str) -> Dict:
        """构建海龟类择时策略参数（委托共享实现，保证与回测同一口径）

        背景：回测引擎与运行器曾各写一份"海龟类策略名单"，新增海龟plus 时两处都漏改，
        导致回测与实盘都回退到代码内默认预设（short = 10/5/10），与
        config/strategy_params.yaml（12/6/12 + 前溯/加仓参数）不一致 —— 回测结果无法
        指导实盘。现统一委托 trading.timing_strategies.build_turtle_family_params，
        名单与合并键只有一份（新增海龟类策略只改那一处）。

        优先级（由高到低）：顶层 config 海龟参数 > timing_params[策略名] > 策略默认预设。

        Args:
            config: 运行配置（顶层，可能直接包含 n_entry / lookback_days 等海龟参数）
            timing_params: config 中的 timing_params 字典
            timing_strategy: 择时策略名，如 'turtle' / 'low_turtle' / 'turtle_plus' / 'support'

        Returns:
            合并后的策略参数字典
        """
        params = build_turtle_family_params(config, timing_params, timing_strategy)
        if timing_strategy in TURTLE_FAMILY_STRATEGIES:
            # 打印生效参数，便于排查回测/实盘参数不一致问题
            logger.info(
                f"【海龟参数】{timing_strategy} 合并顶层配置后生效: "
                f"n_entry={params.get('n_entry')}, n_exit={params.get('n_exit')}, "
                f"atr_period={params.get('atr_period')}, "
                f"base_position_amount={params.get('base_position_amount')}, "
                f"lookback_days={params.get('lookback_days')}, "
                f"max_additions={params.get('max_additions')}")
        return params

    def run_strategies_batch(self, tasks: List[Dict], config: Dict) -> Dict:
        """批量运行策略（所有策略执行完成后统一保存文件）
        
        Args:
            tasks: 任务列表，每个任务包含：
                - selection_strategy: 选股策略名称
                - timing_strategy: 择时策略名称
            config: 运行配置参数
            
        Returns:
            批量执行结果
        """
        # 检查是否正在执行（防止并发）
        logger.info(f"检查执行状态: _is_running={StrategyRunner._is_running}, 锁状态={_strategy_run_lock.locked()}")
        if StrategyRunner._is_running:
            logger.warning("策略正在执行中，拒绝重复请求")
            return {
                "status": "failed",
                "message": "策略正在执行中，请等待当前任务完成"
            }
        
        # 检查所有任务的择时策略是否一致
        if len(tasks) > 1:
            timing_strategies = []
            for task in tasks:
                timing_strategy = task.get('timing_strategy', 'support')
                timing_strategies.append(timing_strategy)
            
            unique_timing_strategies = list(set(timing_strategies))
            if len(unique_timing_strategies) > 1:
                StrategyRunner._is_running = False
                error_msg = (
                    f"检测到多个不同的择时策略: {unique_timing_strategies}。"
                    f"策略运行器当前只支持所有任务使用相同的择时策略。"
                    f"请修改任务配置，确保所有任务使用相同的择时策略后重新执行。"
                )
                logger.error(error_msg)
                return {
                    "status": "failed",
                    "message": error_msg
                }
            logger.info(f"所有 {len(tasks)} 个任务使用相同的择时策略: {unique_timing_strategies[0]}")
        
        StrategyRunner._is_running = True
        
        # 获取策略运行锁
        if not _strategy_run_lock.acquire(blocking=False):
            logger.warning("策略运行任务正在执行中，等待...")
            _strategy_run_lock.acquire(blocking=True)
            logger.info("获取策略运行锁，开始执行批量任务")
        
        try:
            logger.info(f"开始批量执行 {len(tasks)} 个策略任务")
            
            # 清空上次的缓存数据（只清空一次）
            self.stock_data_cache.clear()
            self.stock_name_cache.clear()
            self.stock_filtered_cache.clear()
            self.buy_candidate_pool = []
            
            # 获取配置参数（与回测引擎保持一致）
            # 优先使用用户传入的config，其次从回测配置获取，最后使用默认值
            initial_capital = config.get('initial_capital', self._DEFAULT_CONFIG['initial_capital'])
            max_daily_buys = config.get('max_daily_buys', self._DEFAULT_CONFIG['max_daily_buys'])
            score_threshold = config.get('score_threshold', self._DEFAULT_CONFIG['score_threshold'])
            
            # 如果 config 中没有提供止盈止损参数，则从回测配置获取
            if 'take_profit' not in config or 'stop_loss' not in config:
                backtest_config = self._get_backtest_config()
                if backtest_config:
                    config = {**backtest_config, **config}  # config 中的值优先
            
            # 确保止盈止损参数存在
            take_profit = config.get('take_profit', self._DEFAULT_CONFIG['take_profit'])
            stop_loss = config.get('stop_loss', self._DEFAULT_CONFIG['stop_loss'])
            
            config['initial_capital'] = initial_capital
            config['max_daily_buys'] = max_daily_buys
            config['score_threshold'] = score_threshold
            config['take_profit'] = take_profit
            config['stop_loss'] = stop_loss
            
            # 确定工作日期
            working_date = self.get_working_date()
            logger.info(f"工作日期: {working_date}")
            
            # 确保当日数据已初始化（PTrade 同步、持仓继承等统一在此处理）
            # initialize_daily_data 内置 _initialized_dates 和 _ptrade_synced_feedback_date 双重守卫，
            # 同一日期多次调用不会重复处理
            init_success = self.initialize_daily_data(working_date)
            
            # 自动模式下 PTrade 反馈文件是唯一数据源，初始化失败必须终止
            run_mode = getattr(self, 'run_mode', 'manual')
            if run_mode == 'auto' and not init_success:
                error_msg = (
                    f"【自动任务终止】{working_date} PTrade 反馈文件不存在或同步失败，"
                    f"无法继续执行。请检查 PTrade 反馈文件是否已生成。"
                    f"预期路径: data/running/ptrade_feedback/Fund_{working_date.replace('-', '')}.csv "
                    f"和 Hold_{working_date.replace('-', '')}.csv"
                )
                logger.error(error_msg)
                StrategyRunner._is_running = False
                return {
                    "status": "failed",
                    "message": error_msg
                }
            
            # 用户点击执行 = 明确要运行策略，不因旧 daily 文件存在而跳过
            # 策略运行锁 (_strategy_run_lock) 已防止并发重复执行
            
            # 工作日期对应的持仓文件（后续保存信号与持仓时复用，必须始终定义）
            portfolio_file = self.running_dir / f"portfolio_{working_date}.json"

            # 加载持仓信息：按数据来源分流，避免用磁盘文件覆盖 PTrade 同步结果
            # 历史故障：此处原为无条件从文件二次加载，当 portfolio 文件被污染
            #（空持仓/旧现金）时会覆盖 sync 已写入内存的正确持仓，导致策略
            # 基于错误数据计算。故 PTrade 同步成功时直接使用内存权威结果。
            if getattr(self, '_ptrade_synced_feedback_date', ''):
                # PTrade 同步成功：self.portfolio 已是权威数据，不再二次加载
                logger.info(
                    f"【数据加载】{working_date} 使用 PTrade 同步结果，"
                    f"持仓={len(getattr(self, 'portfolio', {}) or {})} 条"
                    f"（跳过本地文件二次加载）")
                # 合并账本追踪字段（add_count/first_buy_date 等），保证择时加仓编号正确
                self._merge_tracking_into_portfolio()
            else:
                # 非 PTrade 来源（手动模式/同步未执行）：从本地文件加载
                portfolio_data = self._load_portfolio(str(portfolio_file))
                self.portfolio = self._normalize_portfolio_keys(
                    portfolio_data.get('positions', {}))
                # 合并账本追踪字段（add_count/first_buy_date 等），保证择时加仓编号正确
                self._merge_tracking_into_portfolio()

            # 加载信号历史
            signals_file = self.running_dir / f"signals_{working_date}.json"
            self.signals = self._load_signals(str(signals_file))
            
            # 记录每个任务的执行结果
            task_results = []
            
            # 首次运行标记
            is_first_run = False
            
            # 预加载数据（首次执行）
            first_task = tasks[0]
            first_strategy = first_task.get('selection_strategy', first_task.get('strategy_names', ['ImmortalGuidanceStrategy']))
            if isinstance(first_strategy, list):
                first_strategy = first_strategy[0] if first_strategy else 'ImmortalGuidanceStrategy'
            
            # 加载股票池（首次运行时初始化）
            loaded_pool, need_reexecute = self._load_pool_from_file(working_date)
            if need_reexecute:
                logger.info("需要重新执行，初始化股票池...")
                is_first_run = True
            
            # 预加载股票数据（缓存为空或工作日期变化时重新加载）
            need_reload = (
                not self.stock_filtered_cache
                or self._preload_date != working_date
            )
            if need_reload:
                if self._preload_date:
                    logger.info(f"工作日期变化 ({self._preload_date} → {working_date})，重新预加载股票数据...")
                else:
                    logger.info(f"股票数据缓存为空，开始预加载...")
                self._preload_stock_data(working_date, first_strategy)
            
            if need_reexecute:
                logger.info("需要重新执行，使用预加载机制初始化股票池...")
                self._execute_stock_pool_preload(first_strategy, config)
                logger.info(f"初始化股票池: {len(self.buy_candidate_pool)} 只股票")
            else:
                self.buy_candidate_pool = loaded_pool
                logger.info(f"从持久化文件加载股票池: {len(self.buy_candidate_pool)} 只股票")
            
            # 检查股票池移除条件
            logger.info(f"开始检查股票池移除条件，当前股票池数量: {len(self.buy_candidate_pool)}")
            removed = self._check_pool_removal(working_date)
            removed_count = len(removed) if removed else 0
            # 【2026-09-24】移除**明细**（代码/名称/策略/原因/日期/持有天数/收盘价）✓
            #   供飞书简报与本地日报共用同一份数据 ✓（原实现仅计数 ✗、原因只在日志 ✗）
            removed_items = [{
                'code': c.get('stock', {}).get('stock_code', ''),
                'name': c.get('stock', {}).get('stock_name', ''),
                'strategy': c.get('strategy_name', ''),
                'reason': c.get('removed_reason', ''),
                'date': str(c.get('removed_date', working_date))[:10],
                'hold_days': c.get('removed_hold_days'),
                'price': c.get('removed_price'),
            } for c in (removed or [])]
            if removed:
                logger.info(f"股票池移除 {removed_count} 只股票，剩余: {len(self.buy_candidate_pool)} 只")
            else:
                logger.info(f"股票池移除检查完成：无需移除，当前 {len(self.buy_candidate_pool)} 只全部通过条件检查")
            
            # 执行卖出操作（在选股之前，释放资金用于买入）
            # 先初始化择时策略（使用第一个任务的择时策略）
            if tasks:
                first_task = tasks[0]
                timing_strategy = first_task.get('timing_strategy', 'support')
                timing_params = config.get('timing_params', {})
                # 统一构建策略参数：海龟/低位海龟均合并顶层配置，保证与回测一致
                strategy_params = self._build_turtle_params(
                    config, timing_params, timing_strategy)
                
                self.timing_strategy = TimingStrategyFactory.create_strategy(
                    timing_strategy, strategy_params
                )
                self.timing_strategy_name = timing_strategy
                self.timing_strategy_params = strategy_params
            
            sell_signals = self._execute_sell_operations(working_date, config)
            logger.info(f"卖出操作完成，生成 {len(sell_signals)} 个卖出信号")
            
            # 初始化计数器（removed_count已在前面计算，这里只初始化added_count）
            added_count = 0
            added_items = []             # 【2026-09-24】新增明细（选股入池 + 持仓回池 ✓）
            selection_strategy = ''      # 循环内被覆盖；循环外（持仓入池）兜底使用
            
            # 顺序执行每个策略任务
            for idx, task in enumerate(tasks, 1):
                selection_strategy = task.get('selection_strategy', task.get('strategy_names', ['ImmortalGuidanceStrategy']))
                if isinstance(selection_strategy, list):
                    selection_strategy = selection_strategy[0] if selection_strategy else 'ImmortalGuidanceStrategy'
                timing_strategy = task.get('timing_strategy', 'support')
                
                logger.info(f"执行任务 {idx}/{len(tasks)}: 选股={selection_strategy}, 择时={timing_strategy}")
                
                try:
                    # 仅当择时策略与当前不同时才重新创建（避免与卖出阶段重复创建）
                    if timing_strategy != getattr(self, 'timing_strategy_name', None):
                        timing_params = config.get('timing_params', {})
                        # 统一构建策略参数：海龟/低位海龟均合并顶层配置，保证与回测一致
                        strategy_params = self._build_turtle_params(
                            config, timing_params, timing_strategy)
                        
                        self.timing_strategy = TimingStrategyFactory.create_strategy(
                            timing_strategy, strategy_params
                        )
                        self.timing_strategy_name = timing_strategy
                        self.timing_strategy_params = strategy_params
                        logger.info(f"  创建择时策略: {timing_strategy}")
                    else:
                        logger.debug(f"  择时策略 {timing_strategy} 已创建，复用已有实例")
                    
                    # 使用当前择时策略的参数进行日志记录
                    strategy_params = getattr(self, 'timing_strategy_params', {})
                    logger.info("-" * 60)
                    logger.info(f"任务 {idx}/{len(tasks)} 策略参数:")
                    logger.info(f"  择时策略: {timing_strategy}")
                    logger.info(f"  完整策略参数: {strategy_params}")
                    if timing_strategy == 'turtle':
                        logger.info(f"  海龟策略实际参数:")
                        logger.info(f"    n_entry: {strategy_params.get('n_entry')}")
                        logger.info(f"    n_exit: {strategy_params.get('n_exit')}")
                        logger.info(f"    atr_period: {strategy_params.get('atr_period')}")
                    logger.info("-" * 60)
                    
                    # 执行选股
                    candidate_stocks = self._select_and_score_stocks(selection_strategy, working_date, score_threshold)
                    
                    # 将选出的股票加入股票池
                    new_added = 0
                    new_added_items = []      # 【2026-09-24】本策略本次新增明细 ✓
                    for stock in candidate_stocks:
                        exists = any(item['stock']['stock_code'] == stock['stock_code'] for item in self.buy_candidate_pool)
                        if not exists:
                            support_level = self._calculate_support_level(stock, selection_strategy, working_date)
                            support_method = self._get_support_method_for_strategy(selection_strategy)
                            
                            key_date = stock.get('signal', {}).get('key_date')
                            if key_date:
                                if hasattr(key_date, 'strftime'):
                                    key_date = key_date.strftime('%Y-%m-%d')
                                key_date = str(key_date)
                            else:
                                key_date = working_date
                            
                            self.buy_candidate_pool.append({
                                'stock': stock,
                                'added_date': working_date,
                                'key_date': key_date,
                                'strategy_name': selection_strategy,
                                'support_level': support_level,
                                'support_method': support_method
                            })
                            new_added += 1
                            new_added_items.append({
                                'code': stock.get('stock_code', ''),
                                'name': stock.get('stock_name', ''),
                                'source': 'selection',    # 来源：选股入池 ✓
                                'strategy': selection_strategy,
                                'support_level': support_level,
                                'support_method': support_method,
                            })

                    added_items.extend(new_added_items)
                    task_results.append({
                        'selection_strategy': selection_strategy,
                        'timing_strategy': timing_strategy,
                        'selected_count': len(candidate_stocks),
                        'new_added': new_added,
                        'new_added_items': new_added_items,   # 【2026-09-24】分策略明细 ✓
                        'pool_count': len(self.buy_candidate_pool),
                        'status': 'success'
                    })
                    added_count += new_added
                    logger.info(f"{selection_strategy} 选出 {len(candidate_stocks)} 只股票，新增 {new_added} 只")
                    
                except Exception as e:
                    logger.error(f"任务执行失败: {selection_strategy} - {str(e)}")
                    task_results.append({
                        'selection_strategy': selection_strategy,
                        'timing_strategy': timing_strategy,
                        'status': 'failed',
                        'error': str(e)
                    })
            
            logger.info(f"选股完成，股票池数量: {len(self.buy_candidate_pool)}")

            # ===== 持仓股自动入池（当日已卖出的不计），便于加仓 =====
            # 说明：实盘持仓键已在 _normalize_portfolio_keys 中归一化为纯数字代码，
            #      与候选池一致；当日已产生卖出信号的股票不再入池。
            from trading.pool_entry_rules import resolve_auto_add_holdings

            # 【2026-09-24】先清空明细载体 ✓（未启用回池时不会残留上一轮结果 ✗）
            self.last_holdings_pool_added_items = []
            if resolve_auto_add_holdings(config, self._load_engine_config()):
                _sold_codes = {s.get('stock_code') for s in (sell_signals or [])
                               if s.get('stock_code')}
                _n_hold = self._add_holdings_to_pool(
                    self.portfolio or {}, working_date, _sold_codes, selection_strategy)
                if _n_hold:
                    logger.info(f"【持仓入池】{_n_hold} 只持仓股已回到候选池（当日卖出不计）")
                # 【2026-09-24】把"持仓回池"明细并入新增明细 ✓
                added_items.extend(getattr(self, 'last_holdings_pool_added_items', []) or [])

            # ========== 所有策略执行完成后，统一保存文件 ==========
            
            # 保存股票池
            self._save_pool_to_file(self.buy_candidate_pool, working_date)
            
            # 连续温度风控检查（仅记录警告，不阻止信号生成）
            # 信号文件仍完整生成，便于回测追溯；
            # PTrade 端可根据风控状态自主决定是否执行实际交易
            risk_control_result = self._check_continuous_temp_risk(working_date)
            if not risk_control_result['allow_buy']:
                logger.warning(f"【风控警告】{working_date} {risk_control_result['message']}，但仍生成买入信号供回测参考")
            
            # 始终执行买入操作，生成完整信号
            buy_signals = self._execute_buy_operations(working_date, initial_capital)
            
            # 构建当日记录
            signals = sell_signals + buy_signals
            daily_record = {
                "date": working_date,
                "trading_date": working_date,
                "status": "completed",
                "is_first_run": is_first_run,
                "pool_summary": {
                    "stock_count": len(self.buy_candidate_pool),
                    "removed_count": removed_count if 'removed_count' in locals() and removed_count is not None else 0,
                    "added_count": added_count if 'added_count' in locals() and added_count is not None else 0,
                    # 【2026-09-24】整体情况 + **明细** ✓（飞书简报与本地日报共用同一份 ✓）
                    "added_items": added_items,
                    "removed_items": removed_items,
                    "added_selection_count": added_count,
                    "added_holding_count": len(added_items) - added_count,
                },
                "pool_stocks": [
                    {
                        "code": candidate['stock']['stock_code'],
                        "name": candidate['stock']['stock_name'],
                        "score": candidate['stock'].get('score', 0),
                        "days": (datetime.datetime.strptime(working_date, '%Y-%m-%d') - 
                                datetime.datetime.strptime(candidate.get('added_date', working_date), '%Y-%m-%d')).days + 1,
                        "added_date": candidate.get('added_date', working_date),
                        "support_level": candidate.get('support_level', 0),
                        "support_method": candidate.get('support_method', ''),
                        "strategy": candidate.get('strategy_name', ''),
                        "status": "candidate",
                        "is_cooling": candidate.get('is_cooling', False),
                        "cool_down_end": candidate.get('cool_down_end', None)
                    } for candidate in self.buy_candidate_pool
                ] + [
                    {
                        "code": code,
                        "name": pos['stock_name'],
                        "score": 0,
                        "days": pos.get('holding_days', 0),
                        "support_level": 0,
                        "support_method": "",
                        "strategy": "",
                        "status": "holding"
                    } for code, pos in self.portfolio.items()
                ],
                "buy_signals": buy_signals,
                "sell_signals": sell_signals,
                "portfolio": self.portfolio,
                "task_results": task_results
            }
            
            # 保存所有文件
            records_file = self.running_dir / f"daily_{working_date}.json"
            self._save_daily_record(working_date, daily_record, str(records_file))
            logger.info(f"每日记录已保存到: {records_file}")
            
            # 确保信号文件路径正确
            signals_file = self.running_dir / f"signals_{working_date}.json"
            # 使用赋值替换（而非extend追加），防止重复执行时信号叠加
            self.signals = signals
            # 保存信号文件并获取 PTrade CSV 路径
            ptrade_csv_path = self._save_signals(self.signals, str(signals_file))
            logger.info(f"信号已保存到: {signals_file}，卖出信号: {len(sell_signals)} 条，买入信号: {len(buy_signals)} 条")
            
            self._save_portfolio(self.portfolio, str(portfolio_file))
            logger.info(f"持仓信息已保存到: {portfolio_file}")
            
            # 保存批量任务配置到 task_history.json
            self._save_batch_task_config(tasks, working_date)
            logger.info(f"批量策略执行完成")
            return {
                "status": "success",
                "message": "批量策略运行完成",
                "data": {
                    "run_date": working_date,
                    "is_first_run": is_first_run,
                    "pool_count": len(self.buy_candidate_pool),
                    # 【2026-09-24】股票池增删（**整体 + 明细**）→ 经 pipeline details 透传给飞书简报 ✓
                    "pool_added_items": added_items,
                    "pool_removed_items": removed_items,
                    "pool_added_selection_count": added_count,
                    "pool_added_holding_count": len(added_items) - added_count,
                    "pool_removed_count": removed_count,
                    "total_signals": len(signals),
                    "buy_signals": len(buy_signals),
                    "sell_signals": len(sell_signals),
                    "position_count": len(self.portfolio),
                    "ptrade_csv_file": ptrade_csv_path or "",
                    "task_results": task_results
                }
            }
            
        except Exception as e:
            logger.error(f"批量运行策略失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"status": "failed", "message": str(e)}
        finally:
            _strategy_run_lock.release()
            StrategyRunner._is_running = False
            logger.info("释放策略运行锁")
    
    def _check_feature_config(self) -> Dict:
        """检查功能配置文件
        
        验证功能配置文件是否存在且未过期，确保系统可以正常运行。
        如果没有有效的功能配置文件，阻止策略运行。
        
        Returns:
            检查结果字典，包含 success, message, days_remaining 字段
        """
        try:
            checker = FeatureConfigChecker()
            valid_files, expire_date = checker.check_config()
            
            if not valid_files:
                days_remaining = checker.get_days_remaining()
                if days_remaining <= 0:
                    return {
                        'success': False,
                        'message': '功能配置文件已过期，请更新配置',
                        'days_remaining': days_remaining
                    }
                else:
                    return {
                        'success': False,
                        'message': '未找到有效的功能配置文件，请检查配置',
                        'days_remaining': -1
                    }
            
            days_remaining = checker.get_days_remaining()
            
            if days_remaining > 0 and days_remaining <= 5:
                logger.warning(f"功能配置文件即将到期，剩余{days_remaining}天")
            
            return {
                'success': True,
                'message': '功能配置检查通过',
                'days_remaining': days_remaining,
                'valid_files': [f[0] for f in valid_files]
            }
        except Exception as e:
            logger.error(f"检查功能配置失败: {str(e)}")
            return {
                'success': False,
                'message': f'检查功能配置时发生错误: {str(e)}',
                'days_remaining': -1
            }
    
    def get_days_remaining(self) -> int:
        """获取当前配置剩余天数
        
        Returns:
            剩余天数，未找到配置返回-1
        """
        try:
            checker = FeatureConfigChecker()
            return checker.get_days_remaining()
        except Exception as e:
            logger.error(f"获取配置剩余天数失败: {str(e)}")
            return -1
