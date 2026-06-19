"""
策略运行引擎核心模块
实现量化策略的实盘运行功能，连接回测与实盘操作
支持多组合策略选择功能
"""

import sqlite3
import datetime
import logging
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

from trading.timing_strategies import TimingStrategyFactory
from utils.strategy_name_mapper import get_english_name
from utils.trade_date_utils import is_trading_day, get_previous_trading_day
from utils.trading_time_validator import is_market_closed
from trading.ptrade.ptrade_feedback import PTradeFeedbackHandler, process_ptrade_feedback
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
                       f"threshold={self._fund_flow_rules.get('net_flow_threshold', -10000)}万元, "
                       f"min_hold_days={self._fund_flow_rules.get('min_hold_days', 1)}")
            
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
    
    # ==================== 预加载股票数据 ====================
    
    def _preload_stock_data(self, current_date: str, strategy_name: str = None):
        """预加载所有股票数据到内存
        
        Args:
            current_date: 当前日期
            strategy_name: 策略名称，用于计算需要的历史数据天数
        """
        from datetime import datetime, timedelta
        current_dt = datetime.strptime(current_date, '%Y-%m-%d')
        
        # 根据策略参数计算需要的历史数据天数
        buffer_days = 60
        required_days = buffer_days
        
        if strategy_name:
            strategy = self.strategy_registry.get_strategy(strategy_name)
            if strategy and hasattr(strategy, 'params'):
                params = strategy.params
                max_value = 0
                
                lookback_keys = [
                    'lookback_days', 'pattern_days', 'limit_up_lookback_days',
                    'lowest_point_lookback_days', 'surge_lookback_days', 'uptrend_lookback_days'
                ]
                period_keys = ['ma_period', 'ma_short_period', 'ma_long_period', 'kdj_n',
                             'macd_short', 'macd_long', 'macd_signal', 'volume_ma_period']
                
                for key in lookback_keys + period_keys:
                    if key in params:
                        val = params[key]
                        if isinstance(val, (int, float)):
                            max_value = max(max_value, int(val))
                
                required_days = max_value + buffer_days
        
        # 扩展开始日期
        extended_start = (current_dt - timedelta(days=required_days)).strftime('%Y-%m-%d')
        logger.info(f"预加载股票数据: {extended_start} ~ {current_date} (历史: {required_days}天)")
        
        # 获取所有股票代码
        stock_codes = self.db_manager.list_all_stocks()
        total = len(stock_codes)
        loaded = 0
        skipped = 0
        
        for i, code in enumerate(stock_codes):
            try:
                df = self.db_manager.read_stock(code)
                
                if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 60:
                    skipped += 1
                    continue
                
                # 缓存原始数据
                df_copy = df.copy()
                df_copy['date'] = df_copy['date'].dt.strftime('%Y-%m-%d')
                self.stock_data_cache[code] = df_copy
                
                # 获取股票名称
                name = self._get_stock_name(code)
                
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
                
                # 缓存有效股票
                df_filtered = df.copy()
                df_filtered['date'] = df_filtered['date'].dt.strftime('%Y-%m-%d')
                self.stock_filtered_cache[code] = df_filtered
                loaded += 1
                
            except Exception as e:
                logger.debug(f"预加载股票 {code} 失败: {str(e)}")
                skipped += 1
            
            if (i + 1) % 500 == 0:
                logger.info(f"预加载进度: {i + 1}/{total}, 有效股票: {loaded}, 跳过: {skipped}")
        
        logger.info(f"预加载完成: 有效股票 {loaded}, 跳过 {skipped}, 总计 {total}")

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
        
        # 获取策略的中文名称
        strategy = self.strategy_registry.get_strategy(strategy_name)
        strategy_display_name = strategy.name if strategy else strategy_name
        
        # 使用回测评分器进行批量评分
        scored_stocks = self.score_calculator.calculate_batch_scores(
            stocks=stocks,
            score_date=current_date,
            strategy_name=strategy_display_name
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
        
        # 评分
        logger.info(f"开始对 {len(selected_stocks)} 只股票进行评分")
        scored_stocks = self._score_stocks(selected_stocks, strategy_name, current_date)
        
        # 记录每只股票的综合评分（与回测引擎一致）
        logger.info("\n股票评分详情:")
        for stock in scored_stocks:
            logger.info(f"  - {stock['stock_code']} {stock['stock_name']}: 综合评分={stock['score']}，否决标志={stock.get('veto_flag', False)}")
        
        # 筛选：去除否决票且评分达标
        candidate_stocks = [
            stock for stock in scored_stocks 
            if not stock.get('veto_flag', False) and stock['score'] >= score_threshold
        ]
        
        logger.info(f"\n筛选后待买入股票数: {len(candidate_stocks)}")
        if candidate_stocks:
            logger.info("待买入股票列表:")
            for stock in candidate_stocks:
                logger.info(f"  - {stock['stock_code']} {stock['stock_name']}: 评分={stock['score']}")
        return candidate_stocks
    
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
    
    def _check_pool_removal(self, current_date: str) -> List[Dict]:
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
        
        # 获取前一个交易日
        prev_date = get_previous_trading_day(current_date)
        prev_date_str = prev_date.strftime('%Y-%m-%d') if isinstance(prev_date, datetime.datetime) else prev_date
        
        # 获取资金流向规则配置
        fund_flow_enabled = getattr(self, '_fund_flow_rules', {}).get('is_enabled', True)
        fund_flow_threshold = getattr(self, '_fund_flow_rules', {}).get('net_flow_threshold', -10000)
        fund_flow_min_hold_days = getattr(self, '_fund_flow_rules', {}).get('min_hold_days', 1)
        
        for candidate in self.buy_candidate_pool:
            stock_code = candidate['stock']['stock_code']
            stock_name = candidate['stock']['stock_name']
            strategy_name = candidate.get('strategy_name', '')

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
                remaining.append(candidate)
                continue
            
            # 破支撑位检查：使用当天收盘价（或最新可用收盘价）
            # 注意：缓存数据是倒序排列的（最新日期在前面）
            df_for_support = df[df['date'] <= current_date].copy()
            if len(df_for_support) < 20:
                remaining.append(candidate)
                continue
            price_for_check = df_for_support.iloc[0]['close']  # 最新数据在 iloc[0]
            
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
            
            # 条件3: 资金流向移除（同时满足两个条件时移除）
            # - 5日主力资金累计净流入 < 阈值（默认-10000万元）
            # - 大单净流出 且 小单净流入（出货信号）
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
                removed.append(candidate)
                logger.info(f"【移除】{current_date} {stock_code} {stock_name}: "
                           f"收盘={price_for_check:.2f}, 策略={strategy_name}, 持{hold_days}日, "
                           f"原因: {'; '.join(removal_reasons)}")
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
        
        return removed
    
    def _check_fund_flow_condition(self, stock_code: str, stock_name: str, current_date: str) -> Dict:
        """检查资金流向移除条件
        
        规则：
        - 如果5日主力净额 < -10000万元 或者 大单净流出小单净流入：
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
            
            # 提取资金流向指标（已确保类型正确）
            metrics = scorer._extract_flow_metrics(df)
            net_flow_5d = metrics['net_flow_5d']
            large_net = metrics['large_net']
            small_net = metrics['small_net']
            
            # 获取配置的阈值（确保转换为整数）
            threshold = int(getattr(self, '_fund_flow_rules', {}).get('net_flow_threshold', -10000))
            
            # 判断条件：满足任一条件触发处理
            condition1 = net_flow_5d < threshold  # 5日主力净额 < 阈值
            condition2 = (large_net < 0) and (small_net > 0)  # 大单出+小单进（出货信号）
            
            if condition1 or condition2:
                # 构建原因描述
                if condition1 and condition2:
                    reason_detail = f"5日主力净额{net_flow_5d:.0f}万元<{threshold}万元且大单净流出小单净流入"
                elif condition1:
                    reason_detail = f"5日主力净额{net_flow_5d:.0f}万元<{threshold}万元"
                else:
                    reason_detail = "大单净流出且小单净流入（出货信号）"
                
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
        
        # 尝试从yaml文件加载
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
        
        # 加载运行模式配置（手动/自动）和 PTrade 配置
        main_config_path = Path("config/config.yaml")
        if main_config_path.exists():
            try:
                with open(main_config_path, 'r', encoding='utf-8') as f:
                    main_config = yaml.safe_load(f)
                    # 运行模式
                    run_mode_config = main_config.get('run_mode', {})
                    self.run_mode = run_mode_config.get('mode', 'manual')
                    logger.info(f"运行模式: {self.run_mode}")
                    # 保存完整主配置供后续 PTrade 反馈处理等模块使用
                    self.main_config = main_config
            except Exception as e:
                logger.warning(f"加载运行模式配置失败，默认使用 manual 模式: {str(e)}")
                self.run_mode = 'manual'
                self.main_config = {}
        else:
            self.run_mode = 'manual'
            self.main_config = {}
            logger.info("config/config.yaml 不存在，默认使用 manual 模式")
        
        # 从数据库回测配置获取止盈止损参数（优先级最高）
        backtest_config = self._get_backtest_config()
        if backtest_config:
            # take_profit 和 stop_loss 使用百分比形式（如 21 表示 21%）
            # 转换为小数形式存储，与回测引擎保持一致
            default_config['take_profit_threshold'] = backtest_config.get('take_profit', 15) / 100
            default_config['stop_loss_threshold'] = backtest_config.get('stop_loss', -5) / 100
            logger.info(f"从回测配置获取止盈止损: take_profit={backtest_config.get('take_profit', 15)}%, stop_loss={backtest_config.get('stop_loss', -5)}%")
        
        return default_config
    
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
        
        current_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        trading_days_found = 0
        
        while trading_days_found < days:
            current_date += datetime.timedelta(days=1)
            if is_trading_day(current_date.strftime('%Y-%m-%d')):
                trading_days_found += 1
        
        return current_date.strftime('%Y-%m-%d')
    
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
        """获取当前工作日期
        
        判断逻辑（根据设计文档）：
        1. 如果当前是交易日 AND 当前时间 > 收盘时间(15:00): 处理日期 = 今日
        2. 如果当前是交易日 AND 当前时间 <= 收盘时间: 处理日期 = 昨日
        3. 否则（非交易日）: 处理日期 = 最近一个交易日
        
        Returns:
            工作日期字符串 (YYYY-MM-DD)
        """
        today = datetime.datetime.now()
        today_str = today.strftime('%Y-%m-%d')
        
        # 优先检查是否是交易日
        if is_trading_day(today_str):
            # 检查是否已收盘
            if is_market_closed():
                # 已收盘，使用今日
                logger.info(f"当日是交易日且已收盘，使用今日作为工作日期: {today_str}")
                return today_str
            else:
                # 未收盘，使用前一交易日
                working_date = get_previous_trading_day(today_str)
                logger.info(f"当日是交易日但未收盘，使用前一交易日: {working_date}")
                return working_date
        
        # 不是交易日，返回前一交易日
        working_date = get_previous_trading_day(today_str)
        logger.info(f"当日不是交易日，使用前一交易日: {working_date}")
        return working_date
    
    def _get_working_date_for_test(self, date_str: str) -> str:
        """测试用方法：获取指定日期的工作日期"""
        if self._has_kline_data(date_str):
            return date_str
        return get_previous_trading_day(date_str)
    
    # PTrade 交易时间常量（与 TradingTimeValidator 保持一致）
    _TRADING_START_MINUTES = 9 * 60 + 30   # 9:30
    _TRADING_END_MINUTES = 15 * 60          # 15:00
    
    def _should_process_ptrade_feedback(self) -> bool:
        """判断是否应该处理 PTrade 反馈文件
        
        规则：
        - 仅自动模式（run_mode=auto）且 ptrade.enabled=true 时才处理
        - 交易日盘中（9:30-15:00）不处理，避免干扰实时交易
        - 交易日盘后（15:00后）或非交易日：执行反馈处理
        
        Returns:
            是否应该处理 PTrade 反馈
        """
        # 仅自动模式处理
        if getattr(self, 'run_mode', 'manual') != 'auto':
            logger.debug(f"当前运行模式为 manual，跳过 PTrade 反馈处理")
            return False
        
        # 检查 ptrade.enabled 配置
        main_config = getattr(self, 'main_config', {})
        ptrade_cfg = main_config.get('ptrade', {}) if main_config else {}
        if not ptrade_cfg.get('enabled', True):
            logger.info("【PTrade反馈】ptrade.enabled=false，跳过反馈处理")
            return False
        
        now = datetime.datetime.now()
        current_minutes = now.hour * 60 + now.minute
        today_str = now.strftime('%Y-%m-%d')
        
        # 判断是否为交易日
        if is_trading_day(today_str):
            # 交易日：盘中（9:30-15:00）跳过，盘后处理
            if self._TRADING_START_MINUTES <= current_minutes < self._TRADING_END_MINUTES:
                logger.info("【PTrade反馈】当前为交易日盘中，跳过反馈处理")
                return False
            logger.info("【PTrade反馈】当前为交易日盘后，执行反馈处理")
            return True
        
        # 非交易日：处理
        logger.info("【PTrade反馈】当前非交易日，执行反馈处理")
        return True

    def sync_portfolio_from_ptrade(self, portfolio_date: str) -> bool:
        """同步 PTrade 反馈到 portfolio 文件（供 API 查询时自动更新）

        在 auto 模式下，当 PTrade 反馈文件比当前 portfolio 文件更新时，
        自动处理 PTrade 反馈以更新 portfolio 数据。

        Args:
            portfolio_date: 工作日期 YYYY-MM-DD

        Returns:
            是否执行了 PTrade 同步
        """
        # 只自动模式 + ptrade enabled 时才同步
        if not self._should_process_ptrade_feedback():
            return False

        # 将日期转为 PTrade 格式 YYYYMMDD
        feedback_date = portfolio_date.replace("-", "")
        # 构建 portfolio 文件路径
        portfolio_file = self.running_dir / f"portfolio_{portfolio_date}.json"

        try:
            # 创建临时 handler 检查文件
            # running_dir 是 {project_root}/data/running，取 parent.parent 得到项目根目录
            project_root = str(self.running_dir.parent.parent)
            temp_handler = PTradeFeedbackHandler(
                project_root=project_root,
                config=getattr(self, 'main_config', None))
            # 检查 PTrade 反馈文件是否存在
            if not temp_handler.check_feedback_exists(feedback_date):
                logger.debug(f"【PTrade同步】反馈文件不存在: {feedback_date}，跳过")
                return False
            # 获取 PTrade 反馈文件的修改时间
            fund_file = Path(temp_handler.feedback_dir) / f"Fund_{feedback_date}.csv"
            fund_mtime = fund_file.stat().st_mtime if fund_file.exists() else 0
            # 获取当前 portfolio 文件的修改时间
            portfolio_mtime = portfolio_file.stat().st_mtime \
                if portfolio_file.exists() else 0
            # 如果 portfolio 比 PTrade 反馈文件新，无需更新
            if portfolio_mtime >= fund_mtime:
                logger.debug(
                    f"【PTrade同步】portfolio 已是最新 "
                    f"(portfolio={datetime.datetime.fromtimestamp(portfolio_mtime)}, "
                    f"fund={datetime.datetime.fromtimestamp(fund_mtime)})")
                return False

            # PTrade 反馈文件更新 → 处理
            logger.info(
                f"【PTrade同步】检测到 PTrade 反馈已更新，同步 portfolio: "
                f"feedback_date={feedback_date}")
            result = temp_handler.process(feedback_date)
            if result.get("success"):
                logger.info(
                    f"【PTrade同步】portfolio 已从 PTrade 更新: "
                    f"持仓={len(result.get('holdings', []))} 条, "
                    f"现金={result.get('portfolio', {}).get('cash')}")
                return True
            else:
                logger.warning(
                    f"【PTrade同步】处理失败: {result.get('error')}")
                return False
        except Exception as e:
            logger.warning(f"【PTrade同步】同步异常: {str(e)}")
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
        
        # 获取当日日期（用于除权检测和持仓文件）
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        
        logger.info(f"【数据初始化】开始检查并初始化 {today} 的数据（信号日期: {date}）")
        
        # 检查是否已经初始化过（使用信号日期进行检查）
        if date in self._initialized_dates:
            logger.debug(f"【数据初始化】{date} 已经初始化过，跳过")
            return False
        
        # 检查当日持仓文件是否已存在（使用当日日期，而非前一交易日）
        portfolio_file = self.running_dir / f"portfolio_{today}.json"
        signals_file = self.running_dir / f"signals_{date}.json"
        trades_file = self.running_dir / f"trades_{today}.json"
        
        # ========== 如果当日持仓文件已存在，先加载数据再执行除权检测 ==========
        if portfolio_file.exists():
            logger.info(f"【数据初始化】{today} 的持仓文件已存在，加载数据并检测除权")
            prev_data = self._load_portfolio(str(portfolio_file))
            self.portfolio = prev_data.get('positions', {})
            self.current_total_capital = prev_data.get('cash', 300000)
            self.initial_capital = prev_data.get('initial_capital', 300000)
            
            # 执行除权检测
            # 根据盘中/盘后模式决定信号日期
            now = datetime.datetime.now()
            if now.hour < 15 or (now.hour == 15 and now.minute < 30):
                # 盘中模式：信号使用前一交易日
                self._perform_exdividend_check(current_date=today, signal_date=date)
            else:
                # 盘后模式：所有都使用当日日期
                self._perform_exdividend_check(current_date=today, signal_date=None)
            
            # 保存调整后的持仓
            self._save_portfolio(self.portfolio, str(portfolio_file))
            
            self._initialized_dates.add(date)
            return False
        
        # 查找有数据的最近交易日（向前查找最多30天）
        # 注意：使用 today（当日日期）而非 date（信号工作日期）作为搜索起点，
        # 因为持仓文件按真实日历日期保存（如 portfolio_2026-06-18.json）
        # 盘中时段 date 为前一交易日，会导致跳过最近一天的持仓文件
        current_date = today
        days_looked = 0
        max_days = 30
        found_date = None
        days_between = 0
        
        while days_looked < max_days:
            # 获取前一交易日
            current_date = get_previous_trading_day(current_date)
            days_looked += 1
            
            # 检查该交易日是否有持仓数据
            prev_portfolio_file = self.running_dir / f"portfolio_{current_date}.json"
            if prev_portfolio_file.exists():
                found_date = current_date
                days_between = days_looked
                break
        
        if found_date:
            logger.info(f"【数据初始化】{today} 的持仓文件不存在，从最近有数据的交易日 {found_date} 继承数据（间隔 {days_between} 个交易日）")
            
            # 加载找到的交易日的持仓数据
            prev_data = self._load_portfolio(str(prev_portfolio_file))
            prev_positions = prev_data.get('positions', {})
            prev_cash = prev_data.get('cash', 300000)
            prev_initial_capital = prev_data.get('initial_capital', 300000)
            
            # 更新持仓的持有天数和现价（加上间隔的交易日数）
            updated_positions = {}
            for code, pos in prev_positions.items():
                updated_pos = pos.copy()
                updated_pos['holding_days'] = pos.get('holding_days', 0) + days_between
                
                # 获取最新价格并更新现价和收益
                try:
                    # 获取股票最新数据
                    df = self._get_stock_data(code, date, date)
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
                        # 无法获取最新价格，保持原有现价
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
                logger.info(f"【数据初始化】检测 {found_date} 到 {today} 期间的除权...")
                # 从 today 开始，向后遍历到 found_date 的下一个交易日
                # 例如：found_date=2026-05-30, today=2026-06-02, days_between=3
                # 需要检测：2026-06-02, 2026-06-01, 2026-05-31
                check_date = today
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
        
        # 标记为已初始化
        self._initialized_dates.add(date)
        
        logger.info(f"【数据初始化】{date} 的数据初始化完成")
        return True
    
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
            
            data = {
                'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'cash': self.current_total_capital,
                'initial_capital': self.initial_capital,
                'positions': portfolio
            }
            with open(portfolio_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"持仓信息已保存到: {portfolio_file}")
        except Exception as e:
            logger.error(f"保存持仓文件失败: {str(e)}")
    
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
            
            # PTrade集成：信号CSV固定文件名，保存到 data/running/to_ptrade/
            # 每天只保留一份最新的 KHunter_signals.csv，避免重复上传
            ptrade_dir = self.running_dir / "to_ptrade"
            ptrade_dir.mkdir(parents=True, exist_ok=True)
            pt_csv_file = ptrade_dir / "KHunter_signals.csv"
            
            # PTrade批量埋单CSV列定义
            # 字段规范：exec_date, symbol, side, order_volume, order_price, price_type, strategy_name, signal_id
            # exec_date = 信号日(T日)的下一个交易日(T+1日)，PTrade直接与当日比较即可，无需自行计算交易日
            csv_columns = [
                'exec_date', 'symbol', 'side', 'order_volume', 'order_price', 
                'price_type', 'strategy_name', 'signal_id'
            ]
            
            # 从信号文件名中提取信号日期（T日），格式 YYYYMMDD
            # 文件名格式: signals_YYYY-MM-DD.json
            import re
            date_match = re.search(r'signals_(\d{4}-\d{2}-\d{2})', signals_file)
            signal_date = date_match.group(1).replace('-', '') if date_match else datetime.datetime.now().strftime('%Y%m%d')
            # 执行日期 = T日 + 1个交易日（T+1日执行），PTrade只需 exec_date == today_str 判断
            signal_date_dt = datetime.datetime.strptime(signal_date, '%Y%m%d').strftime('%Y-%m-%d')
            exec_date = self._get_future_trading_day(signal_date_dt, 1).replace('-', '')

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
            
            # 写入CSV文件（UTF-8编码，兼容PTrade批量埋单）
            with open(pt_csv_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=csv_columns)
                writer.writeheader()
                writer.writerows(csv_data)
            
            logger.info(f"PTrade格式CSV信号文件已保存到: {pt_csv_file}")
            
        except Exception as e:
            logger.error(f"保存信号文件失败: {str(e)}")
    
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
            
            # 2. 从执行当日（今日）的持仓文件加载"基线可用资金"
            today_str = datetime.datetime.now().strftime('%Y-%m-%d')
            pf_file_today = self.running_dir / f"portfolio_{today_str}.json"
            pf_file_signal = self.running_dir / f"portfolio_{portfolio_date}.json"
            
            baseline_cash = None
            if pf_file_today.exists():
                # 优先使用今日持仓文件
                with open(pf_file_today, 'r', encoding='utf-8') as f:
                    portfolio_data = json.load(f)
                baseline_cash = portfolio_data.get('cash', 0)
                positions_from_file = portfolio_data.get('positions', {})
                logger.info(f"【资金基线】从今日持仓文件加载基线: ¥{baseline_cash:.2f}")
            elif pf_file_signal.exists():
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
            
            # 保存更新后的信号和持仓
            # 信号文件使用信号日期，持仓文件使用今日日期（确保前端能正确读取）
            signals_file = self.running_dir / f"signals_{portfolio_date}.json"
            today_str = datetime.datetime.now().strftime('%Y-%m-%d')
            portfolio_file = self.running_dir / f"portfolio_{today_str}.json"
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
                        trade_date = self._get_previous_trading_day(today)
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
            self.portfolio = portfolio_data.get('positions', {})
            
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
        """将策略类名转换为中文名称"""
        name_mapping = {
            'ImmortalGuidanceStrategy': '仙人指路策略',
            'LimitUpSidewaysStrategy': '涨停横盘策略',
            'LimitUpPullbackStrategy': '涨停回马枪策略',
            'MACDReversalStrategy': 'MACD反转策略',
            'BullishHaramiStrategy': '多方炮策略',
            'BottomTrendReversalStrategy': '底部趋势拐点策略',
            'ResistanceBreakoutStrategy': '阻力位突破策略',
            'MultiPartyCannonStrategy': '多方炮策略',
            'MorningStarStrategy': '启明星策略',
            'TrendStartStrategy': '趋势起点策略',
            'Strategy2560Selection': '2560战法',
            'GoldenTriangleStrategy': '金三角策略',
            'ShunShiBaoStrategy': '顺势宝',
            'turtle': '海龟策略',
            'bollinger': '布林带策略',
            'rsi': 'RSI策略',
            'support': '支撑位策略'
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
            
            # 记录当前资金和持仓情况
            positions_count = len(self.portfolio)
            available_cash = getattr(self, 'current_total_capital', 0)
            total_assets = available_cash
            
            # 计算持仓市值
            for stock_code, position in self.portfolio.items():
                total_assets += position.get('market_value', 0)
            
            logger.info(f"【卖出准备】{trade_date} 当前资金: ¥{available_cash:.2f}, 持仓: {positions_count}只")
            
            # 获取持仓过期配置（提高资金利用率）
            enable_position_expire = self.config.get('enable_position_expire', True)
            position_expire_hold_days = self.config.get('position_expire_hold_days', 10)
            position_expire_return_threshold = self.config.get('position_expire_return_threshold', 5) / 100  # 转换为小数
            
            # 遍历持仓股票
            stocks_to_remove = []
            for stock_code, position in self.portfolio.items():
                # 获取股票数据
                end_date = trade_date
                start_date = (datetime.datetime.strptime(end_date, '%Y-%m-%d') - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
                df = self._get_stock_data(stock_code, start_date, end_date)
                
                if df is None or df.empty:
                    logger.warning(f"获取股票数据失败 {stock_code}，跳过卖出检查")
                    continue
                
                # 调用择时策略判断
                timing_result = self.timing_strategy.get_timing_result(df, position, use_prev_day_signal=False)

                # 检查止损止盈
                # 注意：缓存数据是倒序排列的（最新日期在前面）
                current_price = df.iloc[0]['close']
                open_price = df.iloc[0]['open']
                buy_price = position['buy_price']
                buy_date = position.get('buy_date', '')
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

                # 计算当前止损线（默认使用基础止损）
                current_stop = base_stop_level / 100
                highest_price_return = 0
                highest_price = current_price  # 默认使用当前价

                if enable_trailing_stop:
                    # 从持仓期间的历史数据中获取最高价（截至前一日，不含当日）
                    if buy_date and stock_code in self.stock_filtered_cache:
                        cache_df = self.stock_filtered_cache[stock_code]
                        # 筛选买入日期之后、前一交易日之前的数据
                        prev_date = (pd.Timestamp(trade_date) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                        holding_df = cache_df[(cache_df['date'] >= buy_date) & (cache_df['date'] <= prev_date)].copy()
                        if not holding_df.empty:
                            highest_price = holding_df['high'].max()
                            highest_price_return = (highest_price - buy_price) / buy_price * 100
                    
                    # 移动止损逻辑：
                    # - 最高收益 < 5%：使用固定止损 -6%
                    # - 最高收益 >= 5%：移动止损 = 截至前一日的最高价 × 92%
                    if highest_price_return >= trailing_trigger_threshold:
                        stop_price = highest_price * 0.92
                        current_stop = (stop_price - buy_price) / buy_price

                    logger.debug(f"  移动止损: 买入价={buy_price:.2f}, 最高价={highest_price:.2f}, 当前价={current_price:.2f}, 最高收益率={highest_price_return:.2f}%, 止损价={highest_price*0.92:.2f}")
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
                    stop_price = highest_price * 0.92 if enable_trailing_stop and highest_price_return >= trailing_trigger_threshold else buy_price * (1 + current_stop)
                    
                    # 构建止损方式说明
                    if enable_trailing_stop and highest_price_return >= trailing_trigger_threshold:
                        stop_method = f"移动止损(最高价{highest_price:.2f}×92%={highest_price*0.92:.2f})"
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
                    stop_price = highest_price * 0.92 if enable_trailing_stop and highest_price_return >= trailing_trigger_threshold else buy_price * (1 + current_stop)
                    # 构建止损方式说明
                    if enable_trailing_stop and highest_price_return >= trailing_trigger_threshold:
                        stop_method = f"移动止损(最高价{highest_price:.2f}×92%={highest_price*0.92:.2f})"
                    else:
                        stop_method = f"固定止损({base_stop_level}%)"
                    
                    # 保存止损价到持仓
                    position['stop_loss_price'] = round(stop_price, 2)
                    
                    # 持仓过期检查
                    if enable_position_expire and profit_rate <= position_expire_return_threshold:
                        # 计算持有天数
                        hold_days = self._calculate_hold_days(position.get('buy_date', ''), trade_date)
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
            
            # ========== 更新冷却池和连续亏损计数（基于生成的卖出信号）==========
            for sell_signal in sell_signals:
                stock_code = sell_signal['stock_code']
                profit_rate = sell_signal['profit_rate'] if 'profit_rate' in sell_signal else 0
                
                # 获取配置
                enable_loss_cool_down = self.config.get('enable_loss_cool_down', True)
                enable_consecutive_loss_limit = self.config.get('enable_consecutive_loss_limit', True)
                cool_down_threshold = self.config.get('cool_down_threshold', -8)
                cool_down_days = self.config.get('cool_down_days', 20)
                max_consecutive_losses = self.config.get('max_consecutive_losses', 2)
                consecutive_loss_cool_down = self.config.get('consecutive_loss_cool_down', 30)
                
                # 更新连续亏损计数
                if enable_consecutive_loss_limit:
                    if profit_rate > 0:
                        # 盈利，重置计数
                        self.consecutive_loss_count[stock_code] = 0
                    else:
                        # 亏损，增加计数
                        current_count = self.consecutive_loss_count.get(stock_code, 0) + 1
                        self.consecutive_loss_count[stock_code] = current_count
                        
                        # 检查是否达到连续亏损限制
                        if current_count >= max_consecutive_losses:
                            cool_down_end = self._get_future_trading_day(trade_date, consecutive_loss_cool_down)
                            # 更新股票池中的冷却状态
                            self._update_stock_cool_down_status(stock_code, True, cool_down_end)
                            logger.warning(f"  股票 {stock_code} 连续亏损 {current_count} 次，加入冷却池至 {cool_down_end}")
                
                # 检查是否触发亏损冷却期（单笔亏损超阈值）
                # 两个条件独立判断：单笔亏损超8% 或 连续两次亏损
                if enable_loss_cool_down and profit_rate * 100 <= cool_down_threshold:
                    # 检查是否已经在冷却期，避免重复记录
                    if not self._check_cool_down(stock_code, trade_date):
                        cool_down_end = self._get_future_trading_day(trade_date, cool_down_days)
                        # 更新股票池中的冷却状态
                        self._update_stock_cool_down_status(stock_code, True, cool_down_end)
                        logger.warning(f"  股票 {stock_code} 单笔亏损 {profit_rate*100:.2f}% 超过阈值 {cool_down_threshold}%，加入冷却池至 {cool_down_end}")
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
                
                # 调用择时策略判断
                timing_result = self.timing_strategy.get_timing_result(df_to_date, existing_pos, current_cash, use_prev_day_signal=False)
                
                # 记录择时信号详情
                current_price = df_to_date.iloc[0]['close']  # 倒序数据，iloc[0]是最新数据
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
                        # 加仓：使用策略返回的买入数量（不检查涨幅）
                        buy_quantity = timing_result.buy_quantity
                        quantity_source = '择时策略（加仓）'
                        trade_type = 'add'  # 加仓
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
                        
                        # ========== 重复信号检查：避免追高（仅首次建仓）==========
                        # 直接从信号文件中读取昨天和前天的信号，判断是否重复
                        from utils.trade_date_utils import get_previous_trading_day
                        prev_day1 = get_previous_trading_day(trade_date)
                        prev_day2 = get_previous_trading_day(prev_day1)
                        
                        has_repeat_signal = False
                        repeat_date = None
                        for check_date in [prev_day1, prev_day2]:
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
                        
                        # 计算总资产 = 可用现金 + 所有持仓的当前市值
                        # 参考回测引擎的计算方式
                        total_assets = current_cash  # 可用现金
                        for code, pos in self.portfolio.items():
                            # 使用持仓中已有的当前价格，若不存在则使用买入价
                            pos_price = pos.get('current_price', pos.get('buy_price', 0))
                            total_assets += pos['quantity'] * pos_price
                        
                        logger.info(f"【总资产计算】{trade_date} 可用现金: ¥{current_cash:.2f}, 持仓市值: ¥{total_assets - current_cash:.2f}, 总资产: ¥{total_assets:.2f}")
                        
                        position_amount = KellyCalculator.calculate_position_amount(
                            total_capital=total_assets,
                            available_cash=current_cash,
                            strategy_name=strategy_name
                        )
                        buy_quantity = KellyCalculator.calculate_buy_quantity(
                            position_amount=position_amount,
                            price=current_price,
                            stock_code=stock_code
                        )
                        quantity_source = '凯莉公式'
                        
                        # 记录买入数量计算详情
                        logger.info(f"【买入数量计算】{trade_date} {stock_code} {stock_name} | "
                                   f"凯利金额: ¥{position_amount:.2f} | 现价: ¥{current_price:.2f} | "
                                   f"计算数量: {buy_quantity}股 | 策略: {strategy_name}")

                    from utils.stock_utils import get_min_trade_unit
                    min_unit = get_min_trade_unit(stock_code)
                    if buy_quantity < min_unit:
                        logger.info(f"【买入检查】{trade_date} {stock_code} {stock_name} 买入数量 {buy_quantity}股 < 最小交易单位{min_unit}股，跳过")
                        continue
                    
                    # 记录买入决策
                    logger.info(f"【买入决策】{trade_date} {stock_code} {stock_name} | "
                               f"数量: {buy_quantity}股 ({quantity_source}) | 价格: ¥{current_price:.2f} | "
                               f"金额: ¥{current_price * buy_quantity:.2f} | "
                               f"信号: {timing_result.message}")
                    
                    signal = {
                        'id': f"buy_{stock_code}_{trade_date}",
                        'date': trade_date,
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'signal_type': 'buy',
                        'trade_type': trade_type,  # 标记是首次建仓还是加仓
                        'quantity': buy_quantity,
                        'price': current_price,
                        'amount': current_price * buy_quantity,
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
                        current_cash -= current_price * buy_quantity
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
        检查连续温度风控状态
        
        根据连续温度风控规则检查当前日期的风控状态，决定是否允许买入操作。
        规则：
        - 0%仓位限制：禁止买入
        - 20%/50%仓位限制：与实际仓位比较，当实际仓位大于限制阈值时，跳过买入
        
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
            total_assets = self.current_total_capital  # 可用现金
            
            # 计算持仓市值
            for code, pos in self.portfolio.items():
                pos_price = pos.get('current_price', pos.get('buy_price', 0))
                total_assets += pos['quantity'] * pos_price
            
            # 计算持仓市值
            position_value = 0
            for code, pos in self.portfolio.items():
                pos_price = pos.get('current_price', pos.get('buy_price', 0))
                position_value += pos['quantity'] * pos_price
            
            if total_assets > 0:
                return position_value / total_assets
            else:
                return 0.0
                
        except Exception as e:
            logger.warning(f"计算当前仓位比例失败: {e}")
            return 0.0
    
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
            
            # 【自动模式】处理 PTrade 反馈文件生成 portfolio（仅盘后/非交易日）
            if self._should_process_ptrade_feedback():
                # 将 working_date (YYYY-MM-DD) 转为 PTrade 需要的格式 (YYYYMMDD)
                feedback_date = working_date.replace("-", "")
                try:
                    # 传入主配置，让 Handler 从中读取 ptrade 和 trading 节
                    handler = PTradeFeedbackHandler(
                        config=getattr(self, 'main_config', None))
                    result = handler.process(feedback_date)
                    if result.get("success"):
                        logger.info(f"【PTrade反馈】已从 PTrade 文件生成 portfolio: "
                                    f"feedback_date={feedback_date}, "
                                    f"holdings={len(result.get('holdings', []))} 条")
                    else:
                        logger.info(f"【PTrade反馈】处理跳过: {result.get('error', '未知')} "
                                    f"(首次运行或 PTrade 文件未生成时正常)")
                except Exception as e:
                    logger.warning(f"【PTrade反馈】处理异常，继续使用本地 portfolio: {str(e)}")
            
            # 检查是否已处理
            if self.check_if_processed(working_date):
                logger.info(f"日期 {working_date} 已处理，直接返回结果")
                StrategyRunner._is_running = False
                return {"status": "success", "message": "日期已处理", "data": {"date": working_date}}
            
            # 加载持仓信息
            portfolio_file = self.running_dir / f"portfolio_{working_date}.json"
            portfolio_data = self._load_portfolio(str(portfolio_file))
            self.portfolio = portfolio_data.get('positions', {})
            
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
            
            # 预加载股票数据
            if not self.stock_filtered_cache:
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
            if removed:
                logger.info(f"股票池移除 {removed_count} 只股票，剩余: {len(self.buy_candidate_pool)} 只")
            
            # 执行卖出操作（在选股之前，释放资金用于买入）
            # 先初始化择时策略（使用第一个任务的择时策略）
            if tasks:
                first_task = tasks[0]
                timing_strategy = first_task.get('timing_strategy', 'support')
                timing_params = config.get('timing_params', {})
                strategy_params = timing_params.get(timing_strategy, {})
                
                # 特殊处理：如果是海龟策略
                if timing_strategy == 'turtle':
                    turtle_specific_params = {
                        'n_entry': config.get('n_entry'),
                        'n_exit': config.get('n_exit'),
                        'atr_period': config.get('atr_period'),
                        'entry_atr': config.get('entry_atr'),
                        'add_atr': config.get('add_atr'),
                        'exit_atr': config.get('exit_atr'),
                        'preset': config.get('turtle_preset'),
                        'base_position_amount': config.get('base_position_amount')
                    }
                    turtle_specific_params = {k: v for k, v in turtle_specific_params.items() if v is not None}
                    strategy_params.update(turtle_specific_params)
                
                self.timing_strategy = TimingStrategyFactory.create_strategy(
                    timing_strategy, strategy_params
                )
                self.timing_strategy_name = timing_strategy
                self.timing_strategy_params = strategy_params
            
            sell_signals = self._execute_sell_operations(working_date, config)
            logger.info(f"卖出操作完成，生成 {len(sell_signals)} 个卖出信号")
            
            # 初始化计数器（removed_count已在前面计算，这里只初始化added_count）
            added_count = 0
            
            # 顺序执行每个策略任务
            for idx, task in enumerate(tasks, 1):
                selection_strategy = task.get('selection_strategy', task.get('strategy_names', ['ImmortalGuidanceStrategy']))
                if isinstance(selection_strategy, list):
                    selection_strategy = selection_strategy[0] if selection_strategy else 'ImmortalGuidanceStrategy'
                timing_strategy = task.get('timing_strategy', 'support')
                
                logger.info(f"执行任务 {idx}/{len(tasks)}: 选股={selection_strategy}, 择时={timing_strategy}")
                
                try:
                    # 初始化择时策略
                    timing_params = config.get('timing_params', {})
                    strategy_params = timing_params.get(timing_strategy, {})
                    
                    # 特殊处理：如果是海龟策略
                    if timing_strategy == 'turtle':
                        turtle_specific_params = {
                            'n_entry': config.get('n_entry'),
                            'n_exit': config.get('n_exit'),
                            'atr_period': config.get('atr_period'),
                            'entry_atr': config.get('entry_atr'),
                            'add_atr': config.get('add_atr'),
                            'exit_atr': config.get('exit_atr'),
                            'preset': config.get('turtle_preset'),
                            'base_position_amount': config.get('base_position_amount')
                        }
                        turtle_specific_params = {k: v for k, v in turtle_specific_params.items() if v is not None}
                        strategy_params.update(turtle_specific_params)
                    
                    # 打印任务级别的策略参数
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
                    
                    self.timing_strategy = TimingStrategyFactory.create_strategy(
                        timing_strategy, strategy_params
                    )
                    self.timing_strategy_name = timing_strategy
                    self.timing_strategy_params = strategy_params
                    
                    # 执行选股
                    candidate_stocks = self._select_and_score_stocks(selection_strategy, working_date, score_threshold)
                    
                    # 将选出的股票加入股票池
                    new_added = 0
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
                    
                    task_results.append({
                        'selection_strategy': selection_strategy,
                        'timing_strategy': timing_strategy,
                        'selected_count': len(candidate_stocks),
                        'new_added': new_added,
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
            
            # ========== 所有策略执行完成后，统一保存文件 ==========
            
            # 保存股票池
            self._save_pool_to_file(self.buy_candidate_pool, working_date)
            
            # 连续温度风控检查（在生成买入信号之前）
            risk_control_result = self._check_continuous_temp_risk(working_date)
            if not risk_control_result['allow_buy']:
                logger.info(f"【风控检查】{working_date} {risk_control_result['message']}，跳过买入信号生成")
                buy_signals = []
            else:
                # 执行买入操作
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
                    "added_count": added_count if 'added_count' in locals() and added_count is not None else 0
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
            self.signals.extend(signals)
            self._save_signals(self.signals, str(signals_file))
            logger.info(f"信号已保存到: {signals_file}，卖出信号: {len(sell_signals)} 条，买入信号: {len(buy_signals)} 条")
            
            self._save_portfolio(self.portfolio, str(portfolio_file))
            logger.info(f"持仓信息已保存到: {portfolio_file}")
            
            logger.info(f"批量策略执行完成")
            return {
                "status": "success",
                "message": "批量策略运行完成",
                "data": {
                    "run_date": working_date,
                    "is_first_run": is_first_run,
                    "pool_count": len(self.buy_candidate_pool),
                    "total_signals": len(signals),
                    "buy_signals": len(buy_signals),
                    "sell_signals": len(sell_signals),
                    "position_count": len(self.portfolio),
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
