"""
回测引擎核心模块
实现量化策略的自动化回测功能
"""

import sqlite3
from datetime import datetime, date, timedelta
import logging
import threading
import numpy as np
import pandas as pd
from scipy import stats
import json
import yaml
from pathlib import Path
from typing import List, Dict, Tuple

from utils.db_manager import DBManager
from utils.akshare_fetcher import AKShareFetcher
from strategy.strategy_registry import StrategyRegistry
from trading.stock_score_api import calculate_stock_score
from trading.backtest_scorer import BacktestScoreCalculator

from trading.timing_strategies import (
    TimingStrategyFactory, TURTLE_FAMILY_STRATEGIES, build_turtle_family_params)
from trading.buy_filter import BuyPreFilter
from utils.strategy_name_mapper import get_english_name
from trading.strategy_kelly_loader import KellyCalculator
from utils.system_utils import sleep_preventer

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 回测全局锁，确保同一时刻只有一个回测任务执行，避免日志交错和资源竞争
_backtest_lock = threading.Lock()

# ======================================================================
# 单次回测进度（内存态；供 Web 端轮询展示预估完成时间，不落库、不影响回测结果）
# 字段说明：
#   running      : 是否正在执行
#   percent      : 进度百分比（done_days/total_days*100，保留1位小数）
#   done_days    : 已处理交易日数
#   total_days   : 回测区间交易日总数
#   current_date : 当前正在处理的交易日
#   started_at   : 回测开始时间（用于计算已耗时和预估剩余）
#   finished_at  : 回测结束时间
#   message      : 状态说明文案
#   result_id    : 回测结果ID（完成后填充）
# ======================================================================
BACKTEST_PROGRESS: Dict = {
    'running': False,
    'percent': 0.0,
    'done_days': 0,
    'total_days': 0,
    'current_date': '',
    'started_at': '',
    'finished_at': '',
    'message': '',
    'result_id': None,
}


def get_backtest_progress() -> Dict:
    """获取单次回测进度快照（供 GET /api/trading/backtest/progress 使用）

    Returns:
        Dict: 进度字典副本，避免外部直接修改内部状态
    """
    # 返回副本，防止外部修改污染内部状态
    return dict(BACKTEST_PROGRESS)


def _begin_backtest_progress(total_days: int) -> None:
    """回测开始：重置进度并记录开始时间

    Args:
        total_days: 回测区间交易日总数
    """
    # 重置所有字段，记录开始时间供预估算法使用
    BACKTEST_PROGRESS.update({
        'running': True, 'percent': 0.0, 'done_days': 0,
        'total_days': int(total_days or 0), 'current_date': '',
        'message': '执行中', 'result_id': None, 'finished_at': '',
        'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })


def _update_backtest_progress(done_days: int, total_days: int, current_date) -> None:
    """每处理一个交易日更新一次进度

    Args:
        done_days: 已完成交易日数
        total_days: 交易日总数
        current_date: 当前正在处理的交易日
    """
    # 计算百分比，避免除零
    total = int(total_days or 0)
    BACKTEST_PROGRESS.update({
        'done_days': int(done_days),
        'total_days': total,
        'percent': round(done_days / total * 100, 1) if total else 0.0,
        'current_date': str(current_date),
    })


def _end_backtest_progress(message: str, ok: bool = True, result_id: int = None) -> None:
    """回测结束（成功或失败）

    Args:
        message: 结束说明文案
        ok: 是否成功（成功=True，失败=False）
        result_id: 回测结果ID（成功时填充）
    """
    # 标记结束状态，记录完成时间
    BACKTEST_PROGRESS.update({
        'running': False,
        'message': message,
        'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'result_id': result_id if ok else None,
    })


def calculate_backtest_cost(stock_code: str, price: float, quantity: int, is_buy: bool) -> dict:
    """计算回测交易成本（不含滑点，按T+1开盘价处理）
    
    Args:
        stock_code: 股票代码
        price: 交易价格
        quantity: 交易数量
        is_buy: 是否为买入操作
        
    Returns:
        成本明细字典
    """
    # 回测交易成本配置（固定值，不从配置文件读取）
    commission_rate = 0.00015     # 佣金率 0.015%
    min_commission = 5            # 最低佣金 5元
    stamp_tax_rate = 0.001        # 印花税率 0.1%（仅卖出）
    transfer_fee_rate = 0.00001   # 过户费率 0.001%（仅沪市）
    
    # 判断是否为沪市股票（6开头）
    is_shanghai = stock_code.startswith('6')
    
    # 计算成交金额
    amount = price * quantity
    
    # 佣金（双向收取）
    commission = amount * commission_rate
    commission = max(commission, min_commission)  # 最低佣金保底
    
    # 过户费（仅沪市，双向收取）
    transfer_fee = 0
    if is_shanghai:
        transfer_fee = amount * transfer_fee_rate
    
    # 印花税（仅卖出）
    stamp_tax = 0
    if not is_buy:
        stamp_tax = amount * stamp_tax_rate
    
    return {
        'commission': round(commission, 2),
        'transfer_fee': round(transfer_fee, 2) if is_shanghai else 0,
        'stamp_tax': round(stamp_tax, 2) if not is_buy else 0,
        'is_shanghai': is_shanghai
    }


def should_register_sell_cool_down(trade_type: str, return_rate: float,
                                   cool_down_threshold=None,
                                   cool_down_on_any_sell: bool = True) -> bool:
    """本次卖出是否需要登记冷却池（2026-09-16 新规则，回测/实盘**共用**同一判定）

    规则：
      - **任意清仓卖出**（trade_type='sell'）→ True：**盈利卖出同样冷却**；
        `cool_down_on_any_sell=False` 时回退旧规则（仅亏损卖出且过亏损门槛）。
      - 减仓（trade_type='reduce'）→ 仍按旧规则（亏损且过门槛）：减仓后仍持仓，
        登记冷却会阻塞随后加仓（如海龟/海龟plus 的第二买点加仓）。

    Args:
        trade_type: 'sell'=清仓 / 'reduce'=减仓
        return_rate: 本笔收益率（**百分数**，如 -3.5 表示 -3.5%）
        cool_down_threshold: 亏损门槛（None = 无门槛）
        cool_down_on_any_sell: 任意清仓卖出即冷却（默认 True）

    Returns:
        是否需要登记冷却池
    """
    is_full_sell = (trade_type or 'sell') == 'sell'
    if is_full_sell and cool_down_on_any_sell:
        return True
    loss_over_threshold = (cool_down_threshold is None
                           or return_rate <= cool_down_threshold)
    return return_rate < 0 and loss_over_threshold


# 【2026-09-22 口径修正】盈利因子"无亏损"时的上限哨兵值 ✓
#   盈利因子 = 总盈利金额 / 总亏损金额；若**一笔亏损都没有**，该比值数学上为 +∞ ✗ ——
#   +∞ 无法入库（JSON 序列化会产出非标准 Infinity ✗ → 前端 NaN ✗），也无法在表格里阅读 ✗。
#   故统一用该上限值表示"无亏损"✓（前端看到 99.99 即可理解为"极高"✓）。
#   回填脚本 tools 侧同值复用（见 backfill_backtest_metrics.py）✓
PROFIT_FACTOR_NO_LOSS_CAP = 99.99


class BacktestEngine:
    """回测引擎核心类"""

    # 【2026-09-15 暂时屏蔽】三日（滚动）未创新高止盈（sell_type=no_new_high）
    #   True  = 原逻辑生效：普通回测需 config['enable_no_new_high_exit']=True；
    #           自适应回测在 run_backtest 中默认开启（跟随本开关）
    #   False = 全局屏蔽：无论 config 如何传值，该条件都不参与卖出判定
    #   恢复方法：把本行改回 True（判定方法 _check_no_new_high_exit 与卖出块均完整保留）
    ENABLE_NO_NEW_HIGH_EXIT = False
    
    def __init__(self, *args, **kwargs):
        """初始化回测引擎
        
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
        # 初始化K线数据获取器
        from utils.stock_data_fetcher import StockDataFetcher
        self.stock_data_fetcher = StockDataFetcher("data")
        from utils.kline_fetcher import KlineFetcher
        self.kline_fetcher = KlineFetcher(self.db_manager, self.stock_data_fetcher)
        
        # 初始化回测专用评分器
        self.score_calculator = BacktestScoreCalculator(db_manager=self.db_manager)

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
        
        # 加载策略支撑位方法配置（从 config/support_methods.yaml）
        self._support_methods_config = self._load_support_methods_config()
        
        # 初始化技术指标计算模块
        from trading.technical_indicators import TechnicalIndicators
        self.technical_indicators = TechnicalIndicators()
        
        # 初始化预加载管理器
        from trading.preload_manager import PreloadManager
        self.preload_manager = PreloadManager(self)
        
        # ========== 新增：移动止损、亏损冷却期、连续亏损限制相关状态 ==========
        # 移动止损：持仓期间最高收益率
        self.position_highest_profit = {}  # {stock_code: highest_profit}
        
        # 亏损冷却池：单笔亏损超阈值后加入冷却
        self.loss_cool_down_pool = {}  # {stock_code: cool_down_end_date}
        
        # 连续亏损计数：记录每只股票的连续亏损次数
        self.consecutive_loss_count = {}  # {stock_code: consecutive_loss_count}
        
        # 资金流向冷却池：资金流向异常时加入冷却
        self.fund_flow_cool_down_pool = {}  # {stock_code: cool_down_end_date}
        
    def run_backtest(self, strategy_name: str, config: Dict) -> Dict:
        """运行回测
        
        Args:
            strategy_name: 策略名称
            config: 回测配置参数
            
        Returns:
            回测结果字典
        """
        # 获取回测锁，确保同一时刻只有一个回测任务执行
        if not _backtest_lock.acquire(blocking=False):
            logger.warning(f"回测任务正在执行中，策略 {strategy_name} 等待...")
            _backtest_lock.acquire(blocking=True)
            logger.info(f"获取回测锁，开始执行策略: {strategy_name}")
        
        try:
            logger.info(f"开始回测策略: {strategy_name}")
            
            # 启动防止系统睡眠
            sleep_preventer.start()
            
            # 清空上次的缓存数据
            self.stock_data_cache.clear()
            self.stock_name_cache.clear()
            self.stock_filtered_cache.clear()
            self.buy_candidate_pool.clear()
            
            # 【2026-09-23】双边成交滑点（默认买卖各 0.3% ✓）—— 本次回测全程生效 ✓
            self._slippage = self._slippage_rates(config)
            logger.info(f"成交滑点: 买入 {self._slippage['buy'] * 100:.3f}% / "
                        f"卖出 {self._slippage['sell'] * 100:.3f}%"
                        f"（对最终成交价双边调整 ✓；设为 0 即关闭 ✓）")

            # 初始化择时策略
            timing_strategy_name = config.get('timing_strategy', 'support')
            timing_params = config.get('timing_params', {})
            
            # 海龟类策略（海龟/低位海龟/海龟plus）参数合并：统一走共享实现
            # （名单与合并键只有一份，见 trading.timing_strategies），
            # 避免新增海龟类策略时各处漏改 → 回退到代码内默认预设（short = 10/5/10）
            strategy_params = build_turtle_family_params(
                config, timing_params, timing_strategy_name)

            self.timing_strategy = TimingStrategyFactory.create_strategy(
                timing_strategy_name, strategy_params
            )
            logger.info(f"初始化择时策略: {timing_strategy_name}")

            # 存储择时策略名称和参数，用于后续日志记录和结果输出
            self.timing_strategy_name = timing_strategy_name
            self.timing_strategy_params = strategy_params

            # 记录海龟类策略**真正生效**的参数（含海龟plus 的前溯窗口/加仓上限）
            # 【2026-09-23】改为打印**策略实例**上的取值 ✓：
            #   原实现打印的是"合并后的参数字典" ✗ —— 配置里没显式写出的项会显示 None ✗
            #   （如 entry_atr / add_atr / preset ✗），看起来像"参数没读取成功" ✗，
            #   实际它们是走**策略代码默认值** ✓（entry_atr=0.02 / add_atr=0.5 / preset=short ✓）。
            if timing_strategy_name in TURTLE_FAMILY_STRATEGIES:
                _st = self.timing_strategy
                logger.info(
                    f"{timing_strategy_name}生效参数: "
                    f"n_entry={getattr(_st, 'n_entry', None)}, "
                    f"n_exit={getattr(_st, 'n_exit', None)}, "
                    f"atr_period={getattr(_st, 'atr_period', None)}, "
                    f"entry_atr={getattr(_st, 'entry_atr', None)}, "
                    f"add_atr={getattr(_st, 'add_atr', None)}, "
                    f"exit_atr={getattr(_st, 'exit_atr', None)}, "
                    f"preset={getattr(_st, 'preset_name', None)}, "
                    f"lookback_days={getattr(_st, 'lookback_days', None)}, "
                    f"max_additions={getattr(_st, 'max_additions', None)}, "
                    f"add_profit_min={getattr(_st, 'add_profit_min', None)} "
                    f"（未出现在配置中的项 = 策略代码默认值 ✓，非读取失败 ✓）")
            

            
            # 1. 获取回测日期范围
            start_date = config.get('start_date')
            end_date = config.get('end_date')
            
            if not start_date or not end_date:
                raise ValueError("回测开始日期和结束日期不能为空")
            
            # 2. 确保策略已注册
            if not self.strategy_registry.strategies:
                self.strategy_registry.auto_register_from_directory("strategy")
            
            # 3. 加载交易日历（在预加载数据之前，先确定交易日）
            self._load_trading_calendar(start_date, end_date)
            
            # 4. 获取回测交易日列表并打印
            date_range = self._get_trading_dates(start_date, end_date)
            if not date_range:
                raise ValueError(f"回测期间 {start_date} ~ {end_date} 没有交易日")
            
            # 5. 预加载所有股票数据到内存（根据策略参数动态计算历史数据天数）
            self._preload_stock_data(start_date, end_date, strategy_name)
            
            # 6. 初始化回测环境
            initial_capital = config.get('initial_capital', 300000)
            current_capital = initial_capital
            positions = []  # 持仓列表
            trades = []     # 交易记录
            capital_history = [initial_capital]  # 资金历史
            dates = []      # 回测日期列表
            
            # 回测配置：同一只股票最大买入次数
            max_buy_count_per_stock = config.get('max_buy_count_per_stock', 6)
            # 回测配置：买入股票池遍历顺序（0=正序老股票优先，1=倒序新加入股票优先）
            engine_config = self._load_engine_config()
            reverse_pool_order = engine_config.get('reverse_pool_order', 0)

            # 股票池移除模式：config 传入优先，其次配置文件（backtest_engine_config.yaml）的 pool_mode，最后默认 persistent
            self.pool_mode = config.get('pool_mode') or engine_config.get('pool_mode', 'persistent')
            if self.pool_mode not in ('persistent', 'rotation'):
                logger.warning(f"未知 pool_mode={self.pool_mode}，回退为 persistent")
                self.pool_mode = 'persistent'
            logger.info(f"股票池模式 pool_mode={self.pool_mode}（来源：{'config' if config.get('pool_mode') else 'config_file'}）")
            # 股票累计买入次数计数器 {stock_code: buy_count}
            stock_buy_count = {}

            # 初始化单次回测进度（供 Web 端轮询展示预估完成时间）
            # 传入交易日总数，用于计算百分比和预估剩余时间
            _begin_backtest_progress(len(date_range))

            for i, current_date in enumerate(date_range):
                logger.info(f"\n============================================================")
                logger.info(f"处理日期: {current_date}")
                logger.info(f"============================================================")

                # 每个交易日处理前更新进度（i+1 表示已开始处理第 i+1 天）
                # 放在循环开头，前端能立即看到"开始处理当天"的反馈
                _update_backtest_progress(i + 1, len(date_range), current_date)
                
                # 初始化当日买入计数
                daily_buys = 0
                max_daily_buys = config.get('max_daily_buys', 5)
                
                # 记录当日卖出的股票（用于限制当天卖出的股票不买入）
                today_sold_stocks = set()
                
                # 记录当日交易情况
                logger.info(f"当日初始资金: {current_capital:.2f}")
                logger.info(f"当日初始持仓: {len(positions)} 只股票")
                logger.info(f"当日最大买入限制: {max_daily_buys} 只")
                
                # 统一处理逻辑：先处理卖出，再处理买入
                
                # 合并重复持仓（同一股票可能有多条记录）
                if positions and len(positions) > 1:
                    merged = {}
                    for pos in positions:
                        code = pos['stock_code']
                        if code in merged:
                            # 合并：累加数量和金额，重新计算均价
                            merged[code]['quantity'] += pos['quantity']
                            merged[code]['buy_amount'] += pos['buy_amount']
                            merged[code]['buy_price'] = merged[code]['buy_amount'] / merged[code]['quantity']
                        else:
                            merged[code] = pos.copy()
                    new_positions = list(merged.values())
                    if len(new_positions) < len(positions):
                        logger.info(f"合并重复持仓: {len(positions)} -> {len(new_positions)}")
                    positions = new_positions
                
                # 处理卖出（如果有持仓）
                if positions:
                    logger.info(f"开始执行卖出操作，当前持仓数: {len(positions)}")
                    # 记录当前持仓详情
                    logger.info("当前持仓详情:")
                    for i, pos in enumerate(positions):
                        # 获取昨日收盘价
                        prev_close = self._get_stock_price(pos['stock_code'], current_date, 'prev_close')
                        # 处理价格显示（避免格式化错误）
                        prev_close_str = f"{prev_close:.2f}" if prev_close else 'N/A'
                        # 计算持仓市值（昨日收盘价 × 持仓数量）
                        position_value = prev_close * pos['quantity'] if prev_close else 0.0
                        # 计算持仓收益（市值 - 成本）和收益率
                        position_profit = position_value - pos['buy_amount']
                        profit_rate = (position_profit / pos['buy_amount']) * 100 if pos['buy_amount'] > 0 else 0.0
                        logger.info(f"  {i+1}. {pos['stock_code']} {pos['stock_name']}: 持仓数量={pos['quantity']}, 成本价={pos['buy_price']:.2f}, 昨日收盘价={prev_close_str}, 持仓市值={position_value:.2f}, 持仓收益={position_profit:.2f}({profit_rate:.2f}%)")
                    
                    positions, sell_records = self._process_sell(positions, current_date, config)
                    logger.info(f"卖出操作完成，卖出 {len(sell_records)} 笔交易，剩余持仓数: {len(positions)}")
                    
                    # 更新资金（卖出资金立即可用，净金额已扣除成本）
                    for sell_record in sell_records:
                        current_capital += sell_record['sell_amount']
                        trades.append(sell_record)
                        # 记录当日卖出的股票
                        today_sold_stocks.add(sell_record['stock_code'])
                        total_sell_cost = sell_record['sell_commission'] + sell_record['sell_transfer_fee'] + sell_record['sell_stamp_tax']
                        logger.info(f"【卖出】股票: {sell_record['stock_code']} {sell_record['stock_name']}, 类型: {sell_record['sell_type']}, 价格: {sell_record['sell_price']:.2f}, 数量: {sell_record['quantity']}, 净金额: {sell_record['sell_amount']:.2f}(扣成本:佣金{sell_record['sell_commission']:.2f}+过户{sell_record['sell_transfer_fee']:.2f}+印花{sell_record['sell_stamp_tax']:.2f}), 收益率: {sell_record['return_rate']:.2f}%")
                    
                    if today_sold_stocks:
                        logger.info(f"当日卖出股票: {list(today_sold_stocks)}")
                    else:
                        logger.info("当日无卖出股票")
                
                # 检查股票池移除条件（在选股之前执行，使用前一日收盘价）
                if self.buy_candidate_pool:
                    logger.info(f"开始检查股票池移除条件，当前股票池数量: {len(self.buy_candidate_pool)}")
                    # 构造当前持仓代码集合：轮动模式下用于移除非持仓候选
                    held_codes = {pos.get('stock_code') for pos in positions if pos.get('stock_code')}
                    removed = self._check_pool_removal(current_date, config, held_codes=held_codes)
                    if removed:
                        logger.info(f"股票池移除 {len(removed)} 只股票")
                
                # 执行选股获得前一日的选股结果
                selection_date = self._get_previous_trading_day(current_date)
                logger.info(f"执行选股日期: {selection_date}")
                
                # 执行选股、评分、筛选，得到候选股票池
                candidate_stocks = self._select_and_score_stocks(strategy_name, selection_date, config)
                
                # 将新选出的股票加入可买股票池
                new_added = 0
                for stock in candidate_stocks:
                    # 检查是否已经在池中
                    if not any(item['stock']['stock_code'] == stock['stock_code'] for item in self.buy_candidate_pool):
                        # 计算支撑位（加入时直接计算并保存）
                        support_level = self._calculate_support_level(stock, selection_date, strategy_name)
                        # 获取支撑位计算方法
                        support_method = self._get_support_method_for_strategy(strategy_name)
                        
                        # 提取关键日（从策略信号中获取，默认为选入日期）
                        key_date = stock.get('signal', {}).get('key_date')
                        if key_date:
                            # 确保 key_date 是字符串格式
                            if hasattr(key_date, 'strftime'):
                                key_date = key_date.strftime('%Y-%m-%d')
                            key_date = str(key_date)
                        else:
                            key_date = selection_date.strftime('%Y-%m-%d') if hasattr(selection_date, 'strftime') else str(selection_date)

                        self.buy_candidate_pool.append({
                            'stock': stock,
                            'added_date': selection_date,
                            'key_date': key_date,                    # 关键日（形态实际形成日期）
                            'strategy_name': strategy_name,
                            'support_level': support_level,       # 支撑位价格
                            'support_method': support_method      # 支撑位计算方法
                        })
                        # 记录加入日志（包含关键日和支撑位信息）
                        if support_level > 0:
                            logger.info(f"股票 {stock['stock_code']} {stock['stock_name']} 加入可买股票池, "
                                       f"关键日={key_date}, 支撑位={support_level:.2f}, 方法={support_method}")
                        else:
                            logger.info(f"股票 {stock['stock_code']} {stock['stock_name']} 加入可买股票池, 支撑位计算失败")
                        new_added += 1
                
                # ===== 持仓股自动入池（当日已卖出的不计），便于加仓 =====
                from trading.pool_entry_rules import resolve_auto_add_holdings

                if resolve_auto_add_holdings(config, self._load_engine_config()):
                    self._add_holdings_to_pool(positions, current_date,
                                               today_sold_stocks, strategy_name)

                # 处理可买股票池
                logger.info(f"\n当前可买股票池数量: {len(self.buy_candidate_pool)} (新增 {new_added} 只)")
                if self.buy_candidate_pool:
                    logger.info("可买股票池详情:")
                    for i, candidate in enumerate(self.buy_candidate_pool):
                        stock = candidate['stock']
                        added_date = candidate['added_date']
                        support_level = candidate.get('support_level', 0.0)
                        support_method = candidate.get('support_method', 'unknown')
                        score = stock.get('score', 'N/A')
                        support_info = f"，支撑位={support_level:.2f}({support_method})" if support_level > 0 else "，支撑位=未计算"
                        logger.info(f"  {i+1}. {stock['stock_code']} {stock['stock_name']}: 加入日期={added_date}，评分={score}{support_info}")
                remaining_candidates = []
                
                # 记录当日已买入的股票代码
                today_bought_stocks = set()
                
                # 根据配置决定股票池遍历顺序
                # 正序（reverse_pool_order=0）：老股票优先，新加入股票后处理
                # 倒序（reverse_pool_order=1）：新加入股票优先，老股票后处理
                pool_iter = reversed(self.buy_candidate_pool) if reverse_pool_order else self.buy_candidate_pool
                if reverse_pool_order:
                    logger.info("买入顺序：倒序处理（新加入股票优先）")
                
                for candidate in pool_iter:
                    stock = candidate['stock']
                    stock_code = stock['stock_code']
                    added_date = candidate['added_date']
                    
                    # 当日已买入的股票：跳过检查，但保留在池中
                    if stock_code in today_bought_stocks:
                        logger.info(f"股票 {stock_code} 当日已买入，继续跟踪")
                        remaining_candidates.append(candidate)
                        continue
                    
                    # 检查同一股票最大买入次数
                    current_buy_count = stock_buy_count.get(stock_code, 0)
                    if current_buy_count >= max_buy_count_per_stock:
                        logger.info(f"股票 {stock_code} 已买入{current_buy_count}次，达到最大买入次数{max_buy_count_per_stock}，跳过")
                        remaining_candidates.append(candidate)
                        continue
                    
                    # ========== 新增：检查冷却期和连续亏损限制 ==========
                    # 获取配置（从config中获取，如果没有则使用默认值）
                    enable_loss_cool_down = config.get('enable_loss_cool_down', True)
                    enable_consecutive_loss_limit = config.get('enable_consecutive_loss_limit', True)
                    max_consecutive_losses = config.get('max_consecutive_losses', 2)
                    
                    # 检查冷却期
                    if enable_loss_cool_down or enable_consecutive_loss_limit:
                        if self._check_cool_down(stock_code, current_date):
                            cool_down_end = self.loss_cool_down_pool.get(stock_code, 'N/A')
                            logger.info(f"股票 {stock_code} 在冷却期内（至 {cool_down_end}），跳过")
                            remaining_candidates.append(candidate)
                            continue
                    
                    # 检查连续亏损限制
                    if enable_consecutive_loss_limit:
                        consecutive_count = self.consecutive_loss_count.get(stock_code, 0)
                        if consecutive_count >= max_consecutive_losses:
                            logger.info(f"股票 {stock_code} 连续亏损 {consecutive_count} 次，达到限制 {max_consecutive_losses}，跳过")
                            remaining_candidates.append(candidate)
                            continue
                    # ========== 冷却期和连续亏损限制检查结束 ==========
                    
                    # 当日已卖出的股票不再买入（与实盘一致）
                    # 说明：today_sold_stocks 此前只被写入、从未在买入循环读取，
                    #       导致回测允许"当日卖出后当日买回"，与实盘行为不一致。
                    if stock_code in today_sold_stocks:
                        logger.info(f"【未买入】{stock_code} {stock.get('stock_name', '')}: "
                                    f"当日已卖出，不再买入")
                        remaining_candidates.append(candidate)
                        continue
                    
                    # 检查当日最大买入限制
                    if daily_buys >= max_daily_buys:
                        logger.info(f"【未执行买入】{stock_code} {stock.get('stock_name', '')}: 达到今日买入次数{max_daily_buys}次限制，未执行")
                        remaining_candidates.append(candidate)
                        continue
                    
                    # 获取股票数据
                    df = self.stock_filtered_cache.get(stock_code)
                    if df is None:
                        logger.warning(f"无法获取股票 {stock_code} 的数据，跳过")
                        remaining_candidates.append(candidate)
                        continue
                    
                    # 日期切片：只取到当前日期为止的数据
                    date_str = current_date.strftime('%Y-%m-%d')
                    df_to_date = df[df['date'] <= date_str].copy()
                    if df_to_date.empty:
                        logger.warning(f"股票 {stock_code} 没有可用数据，跳过")
                        remaining_candidates.append(candidate)
                        continue
                    
                    # 如果是回测最后一天（今天）且没有当日数据，尝试获取实时数据
                    today = datetime.now().date()
                    last_data_date = df_to_date['date'].max()
                    if current_date == today and last_data_date < date_str:
                        logger.info(f"股票 {stock_code} 最后数据日期为 {last_data_date}，尝试获取实时数据...")
                        # 获取实时价格
                        try:
                            realtime_price = self.stock_data_fetcher.get_stock_price(stock_code)
                            if realtime_price and realtime_price > 0:
                                # 使用实时价格创建新的K线数据
                                # 获取前一天数据作为参考
                                prev_row = df_to_date[df_to_date['date'] == last_data_date].iloc[-1]
                                prev_close = float(prev_row['close'])
                                # 开盘价使用前一日收盘价（实时价格是当前价，不是开盘价）
                                open_price = prev_close
                                high_price = realtime_price if realtime_price > prev_close else prev_close
                                low_price = realtime_price if realtime_price < prev_close else prev_close
                                # 添加新行
                                new_row = pd.DataFrame([{
                                    'date': date_str,
                                    'open': open_price,
                                    'high': high_price,
                                    'low': low_price,
                                    'close': realtime_price,
                                    'volume': prev_row['volume']  # 用前一天的成交量
                                }])
                                df_to_date = pd.concat([df_to_date, new_row], ignore_index=True)
                                logger.info(f"股票 {stock_code} 添加实时数据: {date_str} 开盘={open_price}, 收盘={realtime_price}")

                                # 同步回写缓存：否则后续 _has_trading_data_on_date（停牌/退市检查）、
                                # 卖出/止损等直接读缓存的逻辑仍看不到当日数据，会把"已有实时数据"
                                # 误判为停牌而跳过买入。
                                try:
                                    merged = pd.concat([df, new_row], ignore_index=True)
                                    self.stock_filtered_cache[stock_code] = merged
                                    if stock_code in self.stock_data_cache:
                                        self.stock_data_cache[stock_code] = merged.copy()
                                except Exception as cache_err:
                                    logger.warning(
                                        f"股票 {stock_code} 实时数据回写缓存失败: {cache_err}")
                        except Exception as e:
                            logger.warning(f"股票 {stock_code} 获取实时数据失败: {str(e)}")
                    
                    # 反转数据为倒序（最新的在前），供策略使用
                    # 注意：read_stock默认返回倒序数据，截断后仍为倒序，无需反转
                    # 仅当数据为升序时才反转
                    if len(df_to_date) > 1 and df_to_date['date'].iloc[0] < df_to_date['date'].iloc[-1]:
                        df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)
                    
                    # 先检查该股票是否已有持仓（用于策略判断加仓）
                    existing_pos = None
                    for pos in positions:
                        if pos['stock_code'] == stock_code:
                            existing_pos = pos
                            break
                    
                    # 调用策略获取完整信号（策略会根据是否有持仓判断新买入或加仓）
                    # 传入 stock_code 以隔离技术指标缓存，避免不同股票间指标复用
                    result = None
                    if self.timing_strategy:
                        result = self.timing_strategy.get_timing_result(df_to_date, existing_pos, current_capital, stock_code=stock_code)
                        timing_name = self.timing_strategy.__class__.__name__
                        logger.info(f"{timing_name}信号: is_buy={result.is_buy}, is_sell={result.is_sell}, "
                                   f"buy_qty={result.buy_quantity}, sell_qty={result.sell_quantity}, "
                                   f"type={result.trade_type}, msg={result.message}")
                    
                    # 判断是否买入
                    is_buy = result.is_buy if result else False
                    if not is_buy:
                        logger.info(f"【未买入】{stock_code} {stock['stock_name']}: 无买入信号")
                        remaining_candidates.append(candidate)
                        continue
                    
                    # 买入前K线过滤检查（仅首次建仓；加仓不做该过滤）
                    # 说明：加仓由择时策略自身条件把关（如盈利门槛 + 趋势/BIAS/缩量），
                    #       再叠加"20日涨幅>50%"等规则会把已大幅盈利的持仓加仓误杀；
                    #       同时与实盘运行器保持一致（运行器加仓本就不做涨幅/涨停基因检查）。
                    # 涨停基因（规则4）可通过 enable_limit_up_check=false 关闭以提升成交率（默认开启）
                    # 优先级：config 传入 > config/backtest_engine_config.yaml > 默认 true
                    if self._should_apply_buy_filter(result, existing_pos):
                        limit_up_enabled = config.get(
                            'enable_limit_up_check',
                            self._load_engine_config().get('enable_limit_up_check', True))
                        filter_result = BuyPreFilter.check_filters_with_config(
                            df_to_date, stock_code,
                            {'enable_limit_up_check': limit_up_enabled})
                        if not filter_result['passed']:
                            logger.info(f"【未买入】{stock_code} {stock['stock_name']}: K线过滤未通过 - {filter_result['reason']}")
                            remaining_candidates.append(candidate)
                            continue
                    
                    # 停牌/退市检查：确认当日有真实行情数据（防止使用前一日收盘价兜底）
                    if not self._has_trading_data_on_date(stock_code, current_date):
                        logger.info(f"【未买入】{stock_code} {stock['stock_name']}: 当日{current_date}无行情数据（停牌/退市），跳过")
                        remaining_candidates.append(candidate)
                        continue
                    
                    # 解析买入执行方式：open=开盘价成交(原行为) / ma_limit=均线委托+滑点+触达成交
                    exec_result = self._resolve_buy_execution(
                        stock_code, current_date, config, df_to_date)
                    buy_price = exec_result['price']
                    # 【2026-09-23】买入滑点：成交价取不利方向（更贵 ✓）
                    #   ma_limit 模式的委托价已自带 slippage ✗ → 该模式不叠加 ✓（避免双计 ✗）
                    _slip = getattr(self, '_slippage', self.DEFAULT_SLIPPAGE)
                    _buy_slip = 0.0 if exec_result.get('mode') == 'ma_limit' else _slip['buy']
                    if buy_price and buy_price > 0 and _buy_slip:
                        buy_price = round(buy_price * (1.0 + _buy_slip), 4)
                    if not exec_result['filled']:
                        # 未成交（如当日最低价未触及委托价）：保留候选池，不记为交易
                        logger.info(f"【未买入】{current_date} {stock_code} "
                                   f"{stock['stock_name']}: {exec_result['reason']}"
                                   f"（委托价={exec_result['order_price']:.2f}）")
                        remaining_candidates.append(candidate)
                        continue
                    logger.info(f"股票 {current_date} {stock_code} {stock['stock_name']} "
                               f"买入成交价: {buy_price:.2f}（委托价="
                               f"{exec_result['order_price']:.2f}, 方式={exec_result['mode']}）")
                    
                    # 获取交易类型（首次建仓或加仓）
                    trade_type = result.trade_type if result else 'new'
                    
                    # ---- 凯利金额（首次建仓基准；加仓时取 1/2 作为数量下限）----
                    strategy_name = candidate.get('strategy_name', 'N/A')
                    total_assets = self._calc_total_assets(current_date, positions, current_capital)
                    kelly_result = KellyCalculator.calculate_position_amount_with_params(
                        total_capital=total_assets,
                        available_cash=current_capital,
                        strategy_name=strategy_name
                    )
                    kelly_amount = kelly_result['amount']

                    # 计算买入数量
                    if trade_type == 'add':
                        # 加仓：策略信号数量 与 1/2 凯利金额对应数量 **取大者**
                        #   —— 策略信号偏小时按"半仓凯利"补足；信号偏大时尊重策略
                        signal_qty = result.buy_quantity if (result and result.buy_quantity > 0) else 0
                        if signal_qty <= 0:
                            config_buy_amount = config.get('buy_amount', 100000)
                            signal_qty = int(config_buy_amount / buy_price) // 100 * 100
                        half_kelly_qty = KellyCalculator.calculate_buy_quantity(
                            position_amount=kelly_amount / 2,
                            price=buy_price,
                            stock_code=stock_code
                        )
                        quantity = max(signal_qty, half_kelly_qty)
                        logger.info(f"【加仓数量】{current_date} {stock_code} {stock['stock_name']}: "
                                    f"策略信号={signal_qty}股, 1/2凯利金额={kelly_amount / 2:.2f}元"
                                    f"→{half_kelly_qty}股, 取大者={quantity}股")

                        # 数量不足一手时不得下单（2026-09-13）：
                        # 此前缺该守卫，当"取大者"结果为 0（如高价股 + 金额兜底折算为 0 手）
                        # 会落库一笔 0 股 / 0 元的加仓订单，并误增 add_count、刷新
                        # last_add_price，干扰海龟后续加仓节奏
                        from utils.stock_utils import get_min_trade_unit
                        _min_unit = get_min_trade_unit(stock_code)
                        if quantity < _min_unit:
                            logger.info(f"【未加仓】{current_date} {stock_code} {stock['stock_name']}: "
                                        f"数量不足{_min_unit}股（策略信号={signal_qty}股，"
                                        f"半凯利={half_kelly_qty}股），跳过加仓")
                            remaining_candidates.append(candidate)
                            continue
                    else:
                        # 首次建仓：使用凯利公式计算（获取完整参数）
                        # 确定最终可用金额
                        if current_capital >= kelly_amount:
                            # 可用资金充足，用凯利金额，不预留费用
                            position_amount = kelly_amount
                            reserve_fee = 0.0
                        else:
                            # 可用资金不足，用可用资金，预留交易费用
                            position_amount = current_capital
                            reserve_fee = position_amount % 100
                            position_amount = position_amount // 100 * 100
                        
                        quantity = KellyCalculator.calculate_buy_quantity(
                            position_amount=position_amount,
                            price=buy_price,
                            stock_code=stock_code
                        )
                        from utils.stock_utils import get_min_trade_unit
                        min_unit = get_min_trade_unit(stock_code)
                        if quantity < min_unit:
                            logger.info(f"【未买入】{stock_code} {stock['stock_name']}: 买入数量不足{min_unit}股")
                            remaining_candidates.append(candidate)
                            continue

                        logger.info(f"【凯利公式计算】{current_date} {stock_code} {stock['stock_name']}: "
                                   f"策略={strategy_name}, 胜率={kelly_result['win_rate']:.2f}, 盈亏比={kelly_result['profit_loss_ratio']:.2f}, "
                                   f"凯利比例={kelly_result['kelly_ratio']:.4f}, 总资产={total_assets:.2f}, "
                                   f"可用资金={current_capital:.2f}, 持仓市值={total_assets - current_capital:.2f}, "
                                   f"凯利金额={kelly_amount:.2f}, 预留费用={reserve_fee:.2f}, 实际买入={position_amount:.2f}, 最小单位={min_unit}股")


                    
                    # 确保不超过可用资金
                    buy_amount = quantity * buy_price
                    # 可用资金小于2000元时跳过实际买入执行，但仍保留在候选池
                    if current_capital < 2000:
                        logger.info(f"【未执行买入】{stock_code} {stock['stock_name']}: 可用资金不足2000元（当前{current_capital:.2f}元），跳过执行")
                        remaining_candidates.append(candidate)
                        continue

                    # 含交易费用校验（2026-09-13）：
                    # 原逻辑仅比较 buy_amount 与可用资金，未给佣金/过户费留位，
                    # 买入后 current_capital -= (buy_amount + 费用) 会扣出几毛钱负数。
                    # 现在要求「买入金额 + 佣金 + 过户费 ≤ 可用资金」，不足则按手数回退。
                    from utils.stock_utils import get_min_trade_unit
                    _min_unit = get_min_trade_unit(stock_code)
                    while quantity >= _min_unit:
                        buy_amount = quantity * buy_price
                        _cost = calculate_backtest_cost(stock_code, buy_price, quantity, is_buy=True)
                        _need = buy_amount + _cost['commission'] + _cost['transfer_fee']
                        if _need <= current_capital:
                            break
                        # 通常只差"费用"这一小截：按差额退手（至少退一手）后复验
                        _deficit = _need - current_capital
                        quantity -= max(1, int(_deficit / (buy_price * _min_unit)) + 1) * _min_unit
                    if quantity < _min_unit:
                        logger.info(f"【未买入】{stock_code} {stock['stock_name']}: 可用资金不足以覆盖含费买入（当前{current_capital:.2f}元，价格{buy_price:.2f}），跳过执行")
                        remaining_candidates.append(candidate)
                        continue
                    buy_amount = quantity * buy_price
                    
                    # 执行买入
                    trade_type = result.trade_type if result else 'new'
                    
                    buy_record = self._execute_buy(stock_code, stock['stock_name'], added_date, current_date,
                                                  buy_price, buy_amount, quantity)
                    buy_record['trade_type'] = trade_type
                    
                    # 处理持仓：existing_pos 已在前面查找过
                    if existing_pos:
                        # 已有持仓，合并（加仓）
                        old_quantity = existing_pos['quantity']
                        old_amount = existing_pos['buy_amount']
                        existing_pos['quantity'] += quantity
                        existing_pos['buy_amount'] += buy_amount
                        # 加权平均买入价
                        existing_pos['buy_price'] = existing_pos['buy_amount'] / existing_pos['quantity']
                        # 更新加仓次数和加仓价格
                        # add_count 语义：加仓后的累计总次数（1-based），与 position['add_count'] 一致
                        # 策略未设置该字段（如顺势宝）时取 0，此处回退为自增，
                        # 避免 hasattr 恒为真导致计数被清零，同时与实盘运行器行为保持一致
                        result_add_count = getattr(result, 'add_count', 0) if result else 0
                        existing_pos['add_count'] = (result_add_count if result_add_count > 0
                                                     else existing_pos.get('add_count', 0) + 1)
                        existing_pos['last_add_price'] = buy_price
                        # 加仓不重置建仓日期（统一口径，所有策略一致）
                        # 说明：历史上此处把 buy_date 重置为当日，导致"持仓过期"被反复续命；
                        # 现统一保留首次建仓日期，加仓日期记入 last_add_date（仅用于展示/排查）。
                        existing_pos['last_add_date'] = current_date
                        logger.info(f"【加仓#{existing_pos['add_count']}】{current_date} {stock_code} {stock['stock_name']}: "
                                   f"原数量={old_quantity}, 加仓={quantity}, 合计={existing_pos['quantity']}, "
                                   f"均价={existing_pos['buy_price']:.2f}, 金额={buy_amount}")
                    else:
                        # 新买入：添加到持仓
                        # 保存首次建仓金额，用于后续加仓计算（海龟策略：每次加仓 = 首次建仓 × 50%）
                        base_position_amount = buy_amount
                        positions.append({
                            'stock_code': stock_code,
                            'stock_name': stock['stock_name'],
                            'buy_date': current_date,
                            'buy_price': buy_price,
                            'quantity': quantity,
                            'buy_amount': buy_amount,
                            'base_position_amount': base_position_amount,  # 首次建仓金额（用于加仓计算）
                            'buy_commission': buy_record['buy_commission'],
                            'buy_transfer_fee': buy_record['buy_transfer_fee'],
                            # 凯利公式参数
                            'kelly_win_rate': kelly_result.get('win_rate') if 'kelly_result' in locals() else None,
                            'kelly_profit_loss_ratio': kelly_result.get('profit_loss_ratio') if 'kelly_result' in locals() else None,
                            'kelly_ratio': kelly_result.get('kelly_ratio') if 'kelly_result' in locals() else None,
                            'kelly_strategy_name': kelly_result.get('strategy_name') if 'kelly_result' in locals() else None
                        })
                        buy_cost = buy_record['buy_commission'] + buy_record['buy_transfer_fee']
                        logger.info(f"【新买入】{current_date} {stock_code} {stock['stock_name']}: 价格={buy_price}, 数量={quantity}, 金额={buy_amount}, 佣金={buy_record['buy_commission']:.2f}, 过户费={buy_record['buy_transfer_fee']:.2f}, 首次建仓={base_position_amount}")
                    
                    current_capital -= (buy_amount + buy_cost)
                    trades.append(buy_record)
                    daily_buys += 1
                    today_bought_stocks.add(stock_code)
                    # 更新该股票的累计买入次数
                    stock_buy_count[stock_code] = stock_buy_count.get(stock_code, 0) + 1
                    
                    # 买入成功仍保留在股票池中
                    remaining_candidates.append(candidate)
                
                # 更新可买股票池（保留所有股票，不因买入而移出）
                self.buy_candidate_pool = remaining_candidates
                logger.info(f"处理后可买股票池数量: {len(self.buy_candidate_pool)}")
                
                # 计算当日总资产（可用资金 + 持仓市值）
                # 使用前一交易日收盘价进行结算，保持与交易决策的一致性
                total_assets = current_capital
                position_details = []
                prev_trading_day = self._get_previous_trading_day(current_date)
                prev_day_str = prev_trading_day.strftime('%Y-%m-%d') if prev_trading_day else current_date
                for position in positions:
                    # 获取前一交易日收盘价
                    current_price = self._get_stock_price(position['stock_code'], prev_trading_day, 'close')
                    if current_price is None or current_price <= 0:
                        current_price = position['buy_price']
                    position_value = current_price * position['quantity']
                    total_assets += position_value
                    # 计算持有天数
                    buy_date_str = position['buy_date'].strftime('%Y-%m-%d')
                    trading_days = self._get_trading_dates(buy_date_str, prev_day_str)
                    hold_days = len(trading_days) - 1 if len(trading_days) > 0 else 0
                    position_details.append({
                        'code': position['stock_code'],
                        'name': position['stock_name'],
                        'price': current_price,
                        'quantity': position['quantity'],
                        'value': position_value,
                        'hold_days': hold_days
                    })
                
                # 记录每日资产详情
                logger.info(f"\n========== {current_date} 每日资产 ==========")
                logger.info(f"资金余额: {current_capital:.2f}")
                if position_details:
                    logger.info(f"持股清单 ({len(position_details)} 只):")
                    for p in position_details:
                        logger.info(f"  - {p['code']} {p['name']}: 价格={p['price']:.2f}, 数量={p['quantity']}, 市值={p['value']:.2f}, 持{p['hold_days']}日")
                else:
                    logger.info(f"持股清单: 空仓")
                logger.info(f"持股市值: {total_assets - current_capital:.2f}")
                logger.info(f"总资产: {total_assets:.2f}")
                logger.info(f"==========================================")
                
                # 记录资金历史（包含持仓市值）
                capital_history.append(total_assets)
                dates.append(current_date)
            
            # 4. 结束结算：计算剩余持仓市值（不创建虚拟卖出记录）
            # 使用前一交易日收盘价进行结算，与主循环每日资产计算保持一致
            if positions:
                logger.info("计算剩余持仓市值")
                final_date = date_range[-1]
                # 使用前一交易日收盘价，与主循环结算逻辑一致（避免未来函数）
                prev_trading_day = self._get_previous_trading_day(final_date)
                prev_day_str = prev_trading_day.strftime('%Y-%m-%d') if prev_trading_day else final_date.strftime('%Y-%m-%d')
                for position in positions:
                    # 计算当前市值（使用前一交易日收盘价）
                    current_price = self._get_stock_price(position['stock_code'], prev_trading_day, 'close')
                    if current_price is None or current_price <= 0:
                        current_price = position['buy_price']
                    current_value = current_price * position['quantity']
                    current_capital += current_value
                    logger.info(f"剩余持仓: {position['stock_code']} {position['stock_name']}, "
                               f"买入价={position['buy_price']:.2f}, 当前价={current_price:.2f}, "
                               f"市值={current_value:.2f}")
                # 同步 capital_history 最后一个值为最终结算值，确保资金曲线与 total_return 使用相同基准
                if capital_history:
                    capital_history[-1] = current_capital
            
            # 5. 计算绩效指标
            final_capital = current_capital
            performance = self._calculate_performance(trades, initial_capital, final_capital, dates, capital_history)
            
            # 6. 构建回测结果
            backtest_result = {
                'strategy_name': strategy_name,
                'config': config,
                'start_date': start_date,
                'end_date': end_date,
                'initial_capital': initial_capital,
                'final_capital': final_capital,
                'performance': performance,
                'trades': trades,
                'capital_history': capital_history,
                'dates': dates,
                'timing_strategy': {
                    'name': self.timing_strategy_name,
                    'params': self.timing_strategy_params
                }
            }
            
            logger.info(f"回测完成，初始资金: {initial_capital}, 最终资金: {final_capital}, 总收益率: {performance['total_return']:.2f}%")

            # 回测成功结束：标记进度完成（result_id 由 routes.py 保存后回填，这里不传）
            _end_backtest_progress('完成', ok=True)

            return backtest_result

        except Exception as e:
            logger.error(f"回测失败: {str(e)}")
            # 回测异常结束：标记进度失败，前端据此停止轮询并显示错误
            _end_backtest_progress(f'失败: {e}', ok=False)
            raise
        finally:
            # 停止防止系统睡眠
            sleep_preventer.stop()
            
            # 释放回测锁，允许下一个任务执行
            _backtest_lock.release()
    
    def _execute_stock_pool_preload(self, strategy_name: str, start_date: str, config: Dict):
        """执行初始股票池预加载
        
        在正式回测前，预加载前N个交易日的可选股票作为初始股票池，
        确保回测第一天就能有可交易的股票。
        
        Args:
            strategy_name: 选股策略名称（前端选择的策略）
            start_date: 回测开始日期
            config: 回测配置参数
        """
        # 获取预加载配置
        preload_enabled = config.get('preload_enabled', True)
        preload_days = config.get('preload_days', 5)
        exclude_recent_days = config.get('preload_exclude_recent_days', 0)
        
        if not preload_enabled:
            logger.info("预加载功能已禁用")
            return
        
        logger.info(f"\n-------------------- 开始执行初始股票池预加载 --------------------")
        logger.info(f"策略: {strategy_name}, 回测开始日期: {start_date}")
        logger.info(f"预加载配置: preload_days={preload_days}, exclude_recent_days={exclude_recent_days}")
        
        try:
            # 设置预加载配置
            self.preload_manager.set_config(
                enabled=preload_enabled,
                preload_days=preload_days,
                exclude_recent_days=exclude_recent_days
            )
            
            # 执行预加载
            preloaded_stocks = self.preload_manager.execute_preload(strategy_name, start_date)
            
            # 获取评分阈值（与正常选股一致）
            score_threshold = config.get('score_threshold', 60)
            logger.info(f"预加载评分阈值: {score_threshold}")
            
            # 统计信息
            total_preload = len(preloaded_stocks)
            filtered_by_veto = 0
            filtered_by_score = 0
            
            # 将预加载的股票添加到可买股票池（与正常选股同一套入池规则）
            from trading.pool_entry_rules import resolve_pool_entry_simplified

            _simplified = resolve_pool_entry_simplified(config, self._load_engine_config())
            logger.info("预加载入池规则: " + (
                f"简易评分（先排除一票否决，资金面得分>={score_threshold}）"
                if _simplified else f"标准（综合评分>={score_threshold}）"))
            for stock in preloaded_stocks:
                # 评分过滤：与正常选股一致（统一规则：否决票 + 评分达标）
                if stock.get('veto_flag', False):
                    logger.debug(f"预加载股票 {stock['stock_code']} 被否决标志过滤，veto_flag={stock.get('veto_flag')}")
                    filtered_by_veto += 1
                    continue

                if stock.get('score', 0) < score_threshold:
                    logger.debug(f"预加载股票 {stock['stock_code']} 评分不达标，score={stock.get('score', 0)} < {score_threshold}")
                    filtered_by_score += 1
                    continue
                
                stock_info = {
                    'stock_code': stock['stock_code'],
                    'stock_name': stock['stock_name'],
                    'score': stock.get('score', 0),
                    'veto_flag': stock.get('veto_flag', False),
                    'reason': stock.get('reason', '')
                }
                
                # 计算支撑位
                support_level = self._calculate_support_level(stock_info, stock['preload_date'], stock['source_strategy'])
                support_method = self._get_support_method_for_strategy(stock['source_strategy'])
                
                # 从预加载数据中提取关键日
                key_date = stock.get('signal', {}).get('key_date')
                if key_date:
                    if hasattr(key_date, 'strftime'):
                        key_date = key_date.strftime('%Y-%m-%d')
                    key_date = str(key_date)
                else:
                    key_date = stock.get('preload_date', stock['preload_date'])

                self.buy_candidate_pool.append({
                    'stock': stock_info,
                    'added_date': stock['preload_date'],
                    'key_date': key_date,                      # 关键日（形态实际形成日期）
                    'strategy_name': stock['source_strategy'],
                    'support_level': support_level,
                    'support_method': support_method
                })
                
                if support_level > 0:
                    logger.info(f"预加载股票 {stock['stock_code']} {stock['stock_name']} 加入股票池, "
                               f"关键日={key_date}, 支撑位={support_level:.2f}, 方法={support_method}, 评分={stock.get('score', 0)}")
                else:
                    logger.info(f"预加载股票 {stock['stock_code']} {stock['stock_name']} 加入股票池, "
                               f"支撑位计算失败, 评分={stock.get('score', 0)}")
            
            logger.info(f"预加载完成: 总数={total_preload}, 因否决过滤={filtered_by_veto}, 因评分过滤={filtered_by_score}, 最终={len(self.buy_candidate_pool)} 只股票")
            
            # 打印前5只股票作为示例
            if self.buy_candidate_pool:
                sample_stocks = self.buy_candidate_pool[:5]
                logger.info(f"初始股票池示例: {[(s['stock']['stock_code'], s['stock']['stock_name']) for s in sample_stocks]}")
                
        except Exception as e:
            logger.error(f"初始股票池预加载失败: {str(e)}")
            # 预加载失败不影响回测继续，使用空股票池开始回测
        
        logger.info("-------------------- 初始股票池预加载结束 --------------------\n")
    
    def _load_trading_calendar(self, start_date: str, end_date: str):
        """加载交易日历数据（三级策略：Tushare API → 本地缓存 → 报错终止）
        
        不再降级到"仅过滤周末"，避免节假日被错误当作交易日处理。
        
        Args:
            start_date: 回测开始日期 (YYYY-MM-DD)
            end_date: 回测结束日期 (YYYY-MM-DD)
            
        Raises:
            RuntimeError: Tushare API 和本地缓存均不可用时抛出
        """
        from datetime import timedelta
        from pathlib import Path
        import json
        
        cache_file = Path("data/trading_calendar_cache.json")
        
        # 扩大加载范围：往前多加载60天，覆盖_get_previous_trading_day的需求
        extended_start_dt = datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=60)
        extended_start = extended_start_dt.strftime('%Y%m%d')
        end_date_str = end_date.replace('-', '')
        
        dates_cache = []  # 最终使用的交易日列表
        
        # 1. 尝试从 Tushare 加载交易日历
        try:
            import tushare as ts
            
            # 读取Tushare token
            tushare_token = None
            try:
                with open('config/tushare_config.json', 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    tushare_token = cfg.get('token') or cfg.get('api_key')
            except Exception:
                pass
            
            if tushare_token:
                logger.info(f"从 Tushare 加载交易日历范围: {extended_start} ~ {end_date_str}")
                
                pro = ts.pro_api(tushare_token)
                df = pro.trade_cal(
                    exchange='SSE',
                    start_date=extended_start,
                    end_date=end_date_str,
                    is_open='1'
                )
                
                if df is not None and not df.empty:
                    # 解析 Tushare 返回的日期列表
                    new_dates = []
                    for _, row in df.iterrows():
                        cal_date = row['cal_date']
                        new_dates.append(f"{cal_date[:4]}-{cal_date[4:6]}-{cal_date[6:8]}")
                    new_dates.sort()
                    
                    # 合并到本地缓存文件
                    all_dates = self._load_cache_dates(cache_file)
                    all_set = set(all_dates)
                    for d in new_dates:
                        all_set.add(d)
                    merged = sorted(all_set)
                    # 写回缓存文件
                    self._save_cache_dates(cache_file, merged)
                    
                    # 筛选回测所需范围
                    start_dt = extended_start_dt.date()
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
                    for d_str in merged:
                        d = datetime.strptime(d_str, '%Y-%m-%d').date()
                        if start_dt <= d <= end_dt:
                            dates_cache.append(d_str)
                    
                    logger.info(f"Tushare 返回 {len(new_dates)} 日，缓存总计 {len(merged)} 日，"
                                f"回测范围 {len(dates_cache)} 日")
        except Exception as e:
            logger.warning(f"从 Tushare 加载交易日历失败: {e}")
        
        # 2. 如果 Tushare 失败，尝试从本地缓存加载
        if not dates_cache and cache_file.exists():
            logger.info(f"Tushare 不可用，从本地缓存加载交易日历: {cache_file}")
            all_dates = self._load_cache_dates(cache_file)
            if all_dates:
                start_dt = extended_start_dt.date()
                end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
                for d_str in all_dates:
                    d = datetime.strptime(d_str, '%Y-%m-%d').date()
                    if start_dt <= d <= end_dt:
                        dates_cache.append(d_str)
                logger.info(f"从缓存加载回测范围交易日: {len(dates_cache)} 日 "
                            f"(缓存总计 {len(all_dates)} 日)")

        # 2.5 【2026-09-13 新增】覆盖不足时用 akshare 兜底（无需 token，节假日准确）
        #     本地缓存只积累"查询过的日期"，新部署/换机器可能只有几天，
        #     此前会静默用 1 个交易日跑完整个区间 → 结果完全错误。
        if self._calendar_coverage_insufficient(dates_cache, extended_start_dt, end_date):
            before = len(dates_cache)
            try:
                import akshare as ak
                df = ak.tool_trade_date_hist_sina()
                raw = [str(x) for x in df['trade_date'].tolist()]
                ak_dates = sorted({x if '-' in x else f"{x[:4]}-{x[4:6]}-{x[6:8]}"
                                   for x in raw})
                _d0 = extended_start_dt.date()
                _d1 = datetime.strptime(end_date, '%Y-%m-%d').date()
                dates_cache = [d for d in ak_dates
                               if _d0 <= datetime.strptime(d, '%Y-%m-%d').date() <= _d1]
                # 合并写回本地缓存，供后续离线运行使用（全量真实日历，含节假日）
                merged = sorted(set(self._load_cache_dates(cache_file)) | set(ak_dates))
                self._save_cache_dates(cache_file, merged)
                logger.warning(
                    f"本地缓存覆盖不足（区间仅 {before} 日）→ 已改用 akshare 交易日历"
                    f"（无需 token）：获取 {len(dates_cache)} 日，缓存已更新至 {len(merged)} 日")
            except Exception as e:
                logger.warning(f"本地缓存覆盖不足（{before} 日）且 akshare 兜底失败: {e}")

        # 3. 如果缓存/兜底都没有，报错终止（不再降级到仅过滤周末）
        if not dates_cache:
            raise RuntimeError(
                f"交易日历加载失败：Tushare API 不可用、本地缓存无覆盖、akshare 兜底也失败。\n"
                f"预期缓存路径: {cache_file.absolute()}\n"
                f"请在网络正常时先运行一次回测以生成/补全缓存文件。"
            )
        
        # 通知 trade_date_utils 刷新模块级缓存（Flask 长驻进程场景必需）
        # 其他模块（moneyflow_scorer 等）通过 trade_date_utils.is_trading_day()
        # 判断交易日，需要确保模块级缓存与文件缓存同步
        try:
            from utils.trade_date_utils import refresh_trading_calendar_cache
            refresh_trading_calendar_cache()
            logger.debug("已刷新 trade_date_utils 模块级交易日缓存")
        except Exception:
            pass
        
        # 构建交易日缓存字典和排序列表
        self.trading_calendar_cache.clear()
        for date_str in dates_cache:
            self.trading_calendar_cache[date_str] = True
        self._sorted_trading_dates = dates_cache.copy()
        
        # 打印前10个和后10个交易日，用于调试
        if dates_cache:
            logger.info(f"前10个交易日: {dates_cache[:10]}")
            logger.info(f"后10个交易日: {dates_cache[-10:]}")
        
        logger.info(f"交易日历加载完成，共 {len(self.trading_calendar_cache)} 个交易日")
    
    @staticmethod
    def _load_cache_dates(cache_file) -> list:
        """从本地缓存文件读取交易日列表
        
        Args:
            cache_file: Path 对象，缓存文件路径
            
        Returns:
            list: 日期字符串列表 ["YYYY-MM-DD", ...]
        """
        import json
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("dates", [])
        except Exception:
            return []
    
    @staticmethod
    def _save_cache_dates(cache_file, dates: list):
        """将交易日列表写入本地缓存文件
        
        Args:
            cache_file: Path 对象，缓存文件路径
            dates: 日期字符串列表 ["YYYY-MM-DD", ...]
        """
        import json
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({"dates": dates}, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _calendar_coverage_insufficient(dates: list, start_dt, end_date: str) -> bool:
        """交易日历覆盖是否明显不足（2026-09-13 新增）

        背景：本地缓存 `data/trading_calendar_cache.json` 只积累"曾经查询过的日期"，
        新部署/换机器时可能只有几天 —— 此前会**静默**用 1 个交易日跑完整个回测区间，
        得到完全错误的结果。

        判据：区间内"工作日数"作为上界，实际取得不足其 80% 即视为覆盖不足
        （扣除春节等长假约 5%~8% 的折损后仍留有安全余量）。

        Args:
            dates: 当前取得的交易日列表
            start_dt: 区间起始（date 或 datetime）
            end_date: 区间结束（YYYY-MM-DD）

        Returns:
            bool: True = 覆盖不足，需要兜底补齐
        """
        from datetime import timedelta
        try:
            d0 = start_dt.date() if hasattr(start_dt, 'date') else start_dt
            d1 = datetime.strptime(end_date, '%Y-%m-%d').date()
            if d1 < d0:
                return False
            expected_weekdays = sum(
                1 for i in range((d1 - d0).days + 1)
                if (d0 + timedelta(days=i)).weekday() < 5)
            if expected_weekdays <= 2:      # 极短区间不做覆盖判定
                return False
            return len(dates) < expected_weekdays * 0.8
        except Exception:
            return False

    def _is_trading_day(self, date: date) -> bool:
        """判断是否为交易日（必须基于交易日历缓存，不使用周末降级）
        
        Args:
            date: 日期
            
        Returns:
            是否为交易日
        """
        date_str = date.strftime('%Y-%m-%d')
        
        # 交易日历缓存未加载时，直接报错
        if not self.trading_calendar_cache:
            raise RuntimeError(
                f"交易日历缓存未加载，无法判断 {date_str} 是否为交易日。"
                f"请确保 _load_trading_calendar() 已成功执行。"
            )
        
        # 缓存中只存了交易日，不在缓存中说明不是交易日
        is_open = date_str in self.trading_calendar_cache
        logger.debug(f"使用交易日历判断日期 {date_str} 是否为交易日: {is_open}")
        return is_open
    
    def _get_trading_dates(self, start_date: str, end_date: str) -> List[date]:
        """获取回测期间的交易日列表
        
        直接从前一步加载的交易日历缓存中筛选，确保只处理真实交易日。
        不再降级到仅过滤周末的模式。
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            交易日期列表
            
        Raises:
            RuntimeError: 交易日历缓存未加载
        """
        # 转换为日期对象
        start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        # 必须从已排序的交易日列表中筛选
        if not (hasattr(self, '_sorted_trading_dates') and self._sorted_trading_dates):
            raise RuntimeError(
                "交易日历缓存未加载，无法获取回测交易日列表。"
                "请确保 _load_trading_calendar() 已成功执行。"
            )
        
        # 从已排序的交易日列表中筛选
        dates = []
        for d_str in self._sorted_trading_dates:
            d = datetime.strptime(d_str, '%Y-%m-%d').date()
            if start_dt <= d <= end_dt:
                dates.append(d)
        
        # 打印回测交易日列表
        logger.info(f"回测交易日: {start_date} 至 {end_date}，共 {len(dates)} 个交易日")
        for d in dates:
            logger.debug(f"  交易日: {d.strftime('%Y-%m-%d')}")
        
        return dates
    
    def _get_previous_trading_day(self, date: date) -> date:
        """获取前一个交易日
        
        优先从排序好的交易日列表中二分查找，效率更高且准确。
        
        Args:
            date: 当前日期
            
        Returns:
            前一个交易日
        """
        date_str = date.strftime('%Y-%m-%d')
        
        # 优先使用排序好的交易日列表
        if hasattr(self, '_sorted_trading_dates') and self._sorted_trading_dates:
            import bisect
            # 找到date_str在列表中的插入位置
            idx = bisect.bisect_left(self._sorted_trading_dates, date_str)
            # 前一个交易日是idx-1位置的日期
            if idx > 0:
                prev_date_str = self._sorted_trading_dates[idx - 1]
                return datetime.strptime(prev_date_str, '%Y-%m-%d').date()
        
        # fallback：逐日向前查找
        previous = date - timedelta(days=1)
        max_attempts = 10
        attempts = 0
        while attempts < max_attempts:
            if self._is_trading_day(previous):
                return previous
            previous -= timedelta(days=1)
            attempts += 1
        
        logger.warning(f"未找到前一个交易日，返回: {date - timedelta(days=1)}")
        return date - timedelta(days=1)
    
    def _get_stock_name(self, code: str) -> str:
        """获取股票名称（优先从缓存获取）
        
        Args:
            code: 股票代码
            
        Returns:
            股票名称，如果未找到则返回"未知"
        """
        # 优先从缓存获取
        if code in self.stock_name_cache:
            return self.stock_name_cache[code]
        
        try:
            cursor = self.db_manager.execute(
                "SELECT name FROM stock_basic WHERE code = ?",
                (code,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                name = row[0]
                self.stock_name_cache[code] = name
                return name
        except Exception as e:
            logger.debug(f"获取股票名称失败 {code}: {str(e)}")
        return "未知"
    
    def _generate_stock_detail_url(self, code: str) -> str:
        """生成股票详情链接
        
        使用与选股结果页面一致的链接格式：
        - 调用 viewStockDetail(code) 函数
        - 该函数会加载 /api/stock/{code} 接口获取股票详情
        
        Args:
            code: 股票代码（6位数字，如 000001）
            
        Returns:
            JavaScript 函数调用字符串
        """
        try:
            # 返回与选股结果页面一致的链接格式
            # 使用 javascript: 协议和 viewStockDetail 函数
            # 格式：javascript:viewStockDetail('000001')
            return f"javascript:viewStockDetail('{code}')" 
            
        except Exception as e:
            logger.debug(f"生成股票详情链接失败 {code}: {str(e)}")
            return f"javascript:viewStockDetail('{code}')"
    
    def _load_support_methods_config(self):
        """加载策略支撑位方法配置
        
        从 config/support_methods.yaml 读取策略与支撑位计算方法的映射关系。
        
        Returns:
            dict: 策略名称 -> 支撑位配置的映射字典
        """
        try:
            # 导入yaml模块
            import yaml
            # 构建配置文件路径
            config_path = Path(__file__).parent.parent / "config" / "support_methods.yaml"
            
            if config_path.exists():
                # 读取yaml配置文件
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                # 提取策略配置部分
                strategies_config = config.get('strategies', {})
                logger.info(f"加载支撑位方法配置: {len(strategies_config)} 个策略")
                return strategies_config
            else:
                logger.warning(f"支撑位配置文件不存在: {config_path}")
                return {}
        except Exception as e:
            logger.warning(f"加载支撑位方法配置失败: {str(e)}")
            return {}
    
    def _get_support_method_for_strategy(self, strategy_name):
        """获取策略的支撑位计算方法
        
        根据策略名称从配置中查找对应的支撑位计算方法。
        
        Args:
            strategy_name: 策略名称（类名）
            
        Returns:
            str: 支撑位计算方法（ma20/key_close_5/key_open/key_close）
        """
        # 从配置中查找策略对应的支撑位方法
        strategy_config = self._support_methods_config.get(strategy_name)
        # 中英文策略名兼容查找（调用方可能传入中文名，yaml 键为英文名）
        if strategy_config is None:
            try:
                from utils.strategy_name_mapper import get_english_name, get_chinese_name
                en = get_english_name(strategy_name)
                zh = get_chinese_name(strategy_name)
                strategy_config = self._support_methods_config.get(en) or self._support_methods_config.get(zh)
            except Exception:
                pass
        # 未找到配置，回退默认
        if strategy_config is None:
            strategy_config = {}
        # 配置为字典格式，提取support_method字段
        if isinstance(strategy_config, dict):
            return strategy_config.get('support_method', 'ma20')
        # 配置为字符串格式，直接返回
        elif isinstance(strategy_config, str):
            return strategy_config
        # 未找到配置，返回默认方法
        return 'ma20'
    
    def _calculate_support_level(self, stock, selection_date, strategy_name=None):
        """计算候选股票的支撑位
        
        在加入股票池时调用，根据策略的支撑位计算方法和关键日计算支撑位。
        参考狩猎场功能（khunter_support_calculator.py）的4种计算方法：
        - ma20: 20日均线
        - key_close_5: 关键日收盘价 × 0.95
        - key_open: 关键日开盘价
        - key_close: 关键日收盘价
        
        Args:
            stock: 股票信息（包含 signal 字段，signal 中包含 key_date）
            selection_date: 选股日期
            strategy_name: 策略名称（类名），也可以是支撑位方法名称（ma20/key_close_5/key_open/key_close）
            
            float: 支撑位价格，计算失败返回0.0
        """
        # stock_code: 股票代码，类型str，从stock中获取
        stock_code = stock['stock_code']
        
        # 获取策略对应的支撑位计算方法
        # 如果 strategy_name 已经是支撑位方法名称（ma20/key_close_5/key_open/key_close），直接使用
        # 如果 strategy_name 为 None，使用默认方法 ma20
        valid_support_methods = ['ma20', 'key_close_5', 'key_open', 'key_close', 't_day_low']
        if strategy_name is None:
            support_method = 'ma20'
        elif strategy_name in valid_support_methods:
            support_method = strategy_name
        else:
            support_method = self._get_support_method_for_strategy(strategy_name)
        
        # 获取K线数据
        df = self.stock_filtered_cache.get(stock_code)
        if df is None:
            logger.debug(f"支撑位计算: {stock_code} 无K线数据")
            return 0.0
        
        # 日期切片：只取到选股日期为止的数据
        # 处理 selection_date 可能是字符串或 datetime 对象的情况
        if isinstance(selection_date, str):
            date_str = selection_date
        else:
            date_str = selection_date.strftime('%Y-%m-%d')
        df_to_date = df[df['date'] <= date_str].copy()
        if df_to_date.empty:
            logger.debug(f"支撑位计算: {stock_code} 选股日期 {date_str} 无数据")
            return 0.0
        
        # 确保正序（日期从早到晚）
        if len(df_to_date) > 1 and df_to_date['date'].iloc[0] > df_to_date['date'].iloc[1]:
            df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)
        
        # 根据方法计算支撑位
        if support_method == 'ma20':
            # ma20: 20日均线
            if len(df_to_date) >= 20:
                ma20_value = round(df_to_date['close'].tail(20).mean(), 2)
                logger.debug(f"支撑位计算: {stock_code} ma20={ma20_value}")
                return ma20_value

        elif support_method == 't_day_low':
            # t_day_low: T日（选股日/selection_date 当日）最低价作为支撑位
            # 取 df_to_date 最后一行（已按日期升序排列）的最低价
            if len(df_to_date) >= 1:
                t_low = float(df_to_date['low'].iloc[-1])
                logger.debug(f"支撑位计算: {stock_code} t_day_low={t_low:.2f} (T日={date_str})")
                return round(t_low, 2)
            
        elif support_method in ['key_close_5', 'key_open', 'key_close']:
            # 需要关键日的方法：从信号中提取key_date
            signal = stock.get('signal', {})
            key_date = signal.get('key_date') if isinstance(signal, dict) else None
            
            if key_date:
                # 在K线数据中查找关键日
                key_date_str = str(key_date)[:10]
                key_date_data = df_to_date[df_to_date['date'].astype(str).str[:10] == key_date_str]
                
                if not key_date_data.empty:
                    if support_method == 'key_close_5':
                        # 关键日收盘价 × 0.95
                        support = round(float(key_date_data.iloc[0]['close']) * 0.95, 2)
                        logger.debug(f"支撑位计算: {stock_code} key_close_5={support} (关键日={key_date_str})")
                        return support
                    elif support_method == 'key_open':
                        # 关键日开盘价
                        support = round(float(key_date_data.iloc[0]['open']), 2)
                        logger.debug(f"支撑位计算: {stock_code} key_open={support} (关键日={key_date_str})")
                        return support
                    elif support_method == 'key_close':
                        # 关键日收盘价
                        support = round(float(key_date_data.iloc[0]['close']), 2)
                        logger.debug(f"支撑位计算: {stock_code} key_close={support} (关键日={key_date_str})")
                        return support
                else:
                    logger.debug(f"支撑位计算: {stock_code} 关键日 {key_date_str} 未在K线数据中找到")
            else:
                logger.debug(f"支撑位计算: {stock_code} 策略 {strategy_name} 需要关键日但信号中无key_date")
        
        # fallback: 使用20日均线作为默认支撑位
        if len(df_to_date) >= 20:
            fallback_value = round(df_to_date['close'].tail(20).mean(), 2)
            logger.debug(f"支撑位计算: {stock_code} fallback ma20={fallback_value}")
            return fallback_value
        
        # 无法计算支撑位
        logger.debug(f"支撑位计算: {stock_code} 数据不足，无法计算")
        return 0.0
    
    # 策略移除模式配置（仅针对选股策略）
    # 配置从 config/pool_removal_config.yaml 读取
    # 择时策略（TurtleStrategy、SupportStrategy）不用于选股，不参与股票池移除
    # 所有选股策略都有两个移除条件：破支撑位（始终生效）+ 趋势验证（延迟生效）
    # min_hold_days: 加入股票池多少天后开始趋势验证
    # - 0: 买入后立即验证趋势
    # - N: 加入股票池N天后才验证趋势

    # YAML配置文件缓存
    _pool_removal_config_cache = None
    _engine_config_cache = None

    def _load_engine_config(self) -> Dict:
        """加载回测引擎行为配置
        
        配置文件路径: config/backtest_engine_config.yaml
        
        Returns:
            引擎配置字典
        """
        # 使用类级别缓存，避免重复读取文件
        if BacktestEngine._engine_config_cache is not None:
            return BacktestEngine._engine_config_cache
        
        config_path = Path(__file__).parent.parent / "config" / "backtest_engine_config.yaml"
        
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f) or {}
            BacktestEngine._engine_config_cache = yaml_config
            logger.info(f"加载回测引擎配置: reverse_pool_order={yaml_config.get('reverse_pool_order', 0)}")
            return yaml_config
        else:
            logger.warning(f"回测引擎配置文件不存在: {config_path}，使用默认配置")
            default_config = {'reverse_pool_order': 0}
            BacktestEngine._engine_config_cache = default_config
            return default_config

    def _load_pool_removal_config(self) -> Dict[str, Dict]:
        """从YAML配置文件加载股票池移除策略配置
        
        配置文件路径: config/pool_removal_config.yaml
        
        Returns:
            策略名称 -> 配置字典的映射
            
        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置格式错误或无启用的策略
        """
        # 使用类级别缓存，避免重复读取文件
        if BacktestEngine._pool_removal_config_cache is not None:
            return BacktestEngine._pool_removal_config_cache
        
        config_map = {}
        config_path = Path(__file__).parent.parent / "config" / "pool_removal_config.yaml"
        
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            yaml_config = yaml.safe_load(f) or {}
        
        # 保存资金流向规则配置（类级别缓存）
        self._fund_flow_rules = yaml_config.get('fund_flow_rules', {})
        logger.info(f"加载资金流向移除规则: enabled={self._fund_flow_rules.get('is_enabled', False)}, "
                   f"min_hold_days={self._fund_flow_rules.get('min_hold_days', 1)}"
                   f"（判定条件与资金面一票否决一致，net_flow_threshold 已废弃）")
        
        strategies = yaml_config.get('removal_strategies', {})
        for name, cfg in strategies.items():
            if cfg.get('is_enabled', True):
                config_map[name] = {
                    'min_hold_days': cfg.get('min_hold_days', 2),
                    'display_name': cfg.get('display_name', '')
                }
                # 同时通过中文名称建立映射（兼容有无"策略"二字两种情况）
                display_name = cfg.get('display_name', '')
                if display_name:
                    config_map[display_name] = config_map[name]
                    # 兼容不带"策略"后缀的名称
                    if display_name.endswith('策略'):
                        config_map[display_name[:-2]] = config_map[name]
        
        if not config_map:
            raise ValueError("YAML配置无启用的策略")
        
        BacktestEngine._pool_removal_config_cache = config_map
        enabled_count = len([name for name, cfg in strategies.items() if cfg.get('is_enabled', True)])
        logger.info(f"从YAML配置加载股票池移除策略: {enabled_count} 个策略")
        
        return config_map

    def _get_strategy_removal_config(self, strategy_name: str) -> Dict:
        """获取策略的移除配置
        
        从YAML配置文件读取，支持类名和中文名称（含/不含"策略"后缀）。
        配置缺失时抛出异常。
        
        Args:
            strategy_name: 策略名称（类名或中文名称）
            
        Returns:
            移除配置字典，包含 min_hold_days
            
        Raises:
            KeyError: 策略未在配置文件中配置
        """
        yaml_config = self._load_pool_removal_config()
        
        # 直接匹配
        if strategy_name in yaml_config:
            return yaml_config[strategy_name]
        
        # 尝试添加"策略"后缀
        if not strategy_name.endswith('策略'):
            with_strategy = strategy_name + '策略'
            if with_strategy in yaml_config:
                return yaml_config[with_strategy]
        
        # 尝试去除"策略"后缀
        if strategy_name.endswith('策略'):
            without_strategy = strategy_name[:-2]
            if without_strategy in yaml_config:
                return yaml_config[without_strategy]
        
        raise KeyError(f"策略 {strategy_name} 未配置股票池移除参数，请在 config/pool_removal_config.yaml 中添加")

    def _check_pool_removal(self, current_date, config, held_codes=None):
        """检查股票池中需要移除的股票
        
        前置规则（优先于下列条件）：
        0. 持仓股不移除（2026-09-11）：处于持仓中的候选一律保留，不参与移除判断
           （避免"移除后又加回"的抖动，并保证加仓链路可用；回测与实盘同口径）

        移除条件（满足任一即移除）：
        1. 破支撑位：前一日收盘价 < 支撑位 × 0.98（始终生效）
        2. 不满足上升趋势条件（加入股票池 min_hold_days 天后生效）
        3. 资金流向条件（同时满足以下两个条件时移除）：
           - 5日主力资金累计净流入 < -10000万元
           - 大单净流出 且 小单净流入（出货信号）
        
        趋势验证条件：
        - 收盘价 >= MA10
        - 20日线性回归斜率 > 0
        - 20日R²拟合度 >= 0.3
        
        股票池模式（pool_mode，由 config 控制）：
        - persistent（默认）：维持现状，仅按上述条件移除，池跨交易日累积
        - rotation（轮动）：在条件移除之前，先把池中“非持仓”候选全部轮出，
          仅保留当前已持仓候选。即每日可买池 = 已持仓 + 当日新选，
          历史老候选每日被轮出。
        ⚠️ 由前置规则 0（持仓保留）与轮动规则（非持仓轮出）共同决定：
           rotation 模式下条件 1~3 实际不会命中任何候选（条件移除只对 persistent 生效）。
        
        Args:
            current_date: 当前交易日期
            config: 回测配置（含 pool_mode）
            held_codes: 当前持仓股票代码集合，轮动模式下用于移除非持仓候选
            
        Returns:
            list: 移除的候选列表
        """
        # 股票池移除模式：config 传入优先，其次实例属性（已由 run_backtest 融合配置文件），最后默认 persistent
        pool_mode = config.get('pool_mode') or getattr(self, 'pool_mode', 'persistent')
        if pool_mode not in ('persistent', 'rotation'):
            logger.warning(f"未知 pool_mode={pool_mode}，回退为 persistent")
            pool_mode = 'persistent'
        # 当前持仓代码集合（轮动模式用于移除非持仓候选）；缺省为空集
        if held_codes is None:
            held_codes = set()
        else:
            held_codes = set(held_codes)
        
        removed_candidates = []
        remaining_candidates = []
        
        # 获取前一个交易日（用于获取收盘价）
        prev_date = self._get_previous_trading_day(current_date)
        prev_date_str = prev_date.strftime('%Y-%m-%d')
        
        # 获取资金流向规则配置
        fund_flow_enabled = getattr(self, '_fund_flow_rules', {}).get('is_enabled', True)
        fund_flow_min_hold_days = getattr(self, '_fund_flow_rules', {}).get('min_hold_days', 1)
        
        for candidate in self.buy_candidate_pool:
            # 提取股票信息
            stock_code = candidate['stock']['stock_code']
            stock_name = candidate['stock']['stock_name']
            strategy_name = candidate.get('strategy_name', '')

            # ===== 持仓股不移除（2026-09-11）=====
            # 处于持仓中的候选一律保留（persistent / rotation 均适用），
            # 既避免"移除后又加回"的抖动，也保证加仓链路可用。
            if stock_code in held_codes:
                remaining_candidates.append(candidate)
                logger.info(f"【保留】{current_date} {stock_code} {stock_name}: "
                            f"当前持仓中，不参与移除判断")
                continue

            # 轮动模式：非持仓候选直接轮出，不参与条件判断（持仓候选已在上方保留）
            if pool_mode == 'rotation' and stock_code not in held_codes:
                removed_candidates.append(candidate)
                logger.info(f"【轮出】{current_date} {stock_code} {stock_name}: "
                           f"轮动模式移除非持仓候选（当前持仓 {len(held_codes)} 只）")
                continue
            
            # 获取策略的移除配置
            removal_config = self._get_strategy_removal_config(strategy_name)
            min_hold_days = removal_config.get('min_hold_days', 2)
            
            # 计算持有天数
            added_date = candidate.get('added_date')
            if isinstance(added_date, str):
                added_date = datetime.strptime(added_date, '%Y-%m-%d').date()
            elif not isinstance(added_date, date):
                added_date = date.today()
            
            hold_days = (prev_date - added_date).days
            
            # 获取股票数据
            df = self.stock_filtered_cache.get(stock_code)
            if df is None:
                # 无法获取数据，保留在池中
                remaining_candidates.append(candidate)
                continue
            
            # 日期切片：只取到前一日为止的数据
            df_to_date = df[df['date'] <= prev_date_str].copy()
            
            # 需要至少20日数据用于计算
            if len(df_to_date) < 20:
                remaining_candidates.append(candidate)
                continue
            
            # 确保正序（日期从早到晚）
            if df_to_date['date'].iloc[0] > df_to_date['date'].iloc[-1]:
                df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)
            
            prev_close = df_to_date.iloc[-1]['close']
            
            # ========== 移除条件判断 ==========
            removal_reasons = []
            should_remove = False
            
            # 条件1: 破支撑位移除（始终生效）
            support_level = candidate.get('support_level', 0.0)
            if support_level > 0 and prev_close > 0:
                if prev_close < support_level * 0.98:
                    should_remove = True
                    drop_pct = (prev_close - support_level) / support_level * 100
                    removal_reasons.append(f"跌破支撑位{support_level:.2f}{drop_pct:.1f}%")
            
            # 条件2: 趋势验证移除（持有 min_hold_days 天后生效）
            if hold_days >= min_hold_days:
                ma10 = df_to_date['close'].tail(10).mean()
                prices = df_to_date['close'].tail(20).values
                x = np.arange(len(prices))
                slope, _, r_value, _, _ = stats.linregress(x, prices)
                r_squared = r_value ** 2
                
                # 判断是否满足上升趋势条件
                trend_ok = (prev_close >= ma10 and slope > 0 and r_squared >= 0.3)
                
                if not trend_ok:
                    should_remove = True
                    if prev_close < ma10:
                        removal_reasons.append(f"收盘价{prev_close:.2f}<MA10{ma10:.2f}")
                    if slope <= 0:
                        removal_reasons.append(f"斜率{slope:.4f}<=0")
                    if r_squared < 0.3:
                        removal_reasons.append(f"R²{r_squared:.4f}<0.3")
            
            # 条件3: 资金流向移除（判定条件与「资金面一票否决」一致，两条件为 OR）
            # - 5日主力净额 < -1亿 且 大单净流入占比 < -5%（无占比字段→净额/成交额 < -1%）
            # - 出货信号：大单净流出占比 > 1% 且 小单净流入占比 > 1%
            if fund_flow_enabled and hold_days >= fund_flow_min_hold_days:
                fund_flow_result = self._check_fund_flow_condition(stock_code, current_date)
                if fund_flow_result['should_remove']:
                    should_remove = True
                    removal_reasons.append(fund_flow_result['reason'])
            
            # 决定是否移除
            if should_remove:
                removed_candidates.append(candidate)
                logger.info(f"【移除】{current_date} {stock_code} {stock_name}: "
                           f"收盘={prev_close:.2f}, 策略={strategy_name}, 持{hold_days}日, "
                           f"原因: {'; '.join(removal_reasons)}")
            else:
                remaining_candidates.append(candidate)
        
        # 更新股票池
        if removed_candidates:
            logger.info(f"股票池移除: {len(removed_candidates)} 只, "
                       f"剩余: {len(remaining_candidates)} 只")
            self.buy_candidate_pool = remaining_candidates
        
        return removed_candidates
    
    def _check_fund_flow_condition(self, stock_code: str, current_date: str) -> Dict:
        """检查资金流向移除条件
        
        判定条件（与「资金面一票否决」完全一致，直接复用 MoneyflowScorer.check_veto）：
        - 条件1  5日主力净额 < -1亿 且 大单净流入占比 < -5%
                 （无占比字段时回退：净额/成交额 < -1%）
        - 条件2  出货信号：大单净流出占比 > 1% 且 小单净流入占比 > 1%
        - 两条件为 **OR**：任一满足即触发处理：
          - 如果股票不在冷却池 → 加入冷却池3天，不移除
          - 如果股票已经在冷却池 → 直接移除
        
        Args:
            stock_code: 股票代码
            current_date: 当前日期（可以是字符串或date对象）
            
        Returns:
            包含 should_remove 和 reason 的字典
        """
        from trading.moneyflow_scorer import MoneyflowScorer
        
        try:
            # 先清理已过期的冷却池条目（出狱逻辑）
            if stock_code in self.fund_flow_cool_down_pool:
                cool_down_end = self.fund_flow_cool_down_pool.get(stock_code, '')
                if cool_down_end:
                    try:
                        # 解析冷却结束日期
                        if hasattr(cool_down_end, 'strftime'):
                            cool_down_end_obj = cool_down_end
                        else:
                            cool_down_end_obj = datetime.strptime(cool_down_end, '%Y-%m-%d').date()
                        
                        # 解析当前日期
                        if hasattr(current_date, 'strftime'):
                            current_date_obj_check = current_date
                        else:
                            current_date_obj_check = datetime.strptime(current_date, '%Y-%m-%d').date()
                        
                        # 冷却期已过，股票"出狱"
                        if current_date_obj_check > cool_down_end_obj:
                            del self.fund_flow_cool_down_pool[stock_code]
                            logger.info(f"股票 {stock_code}: 资金流向冷却期结束，股票出狱")
                    except Exception as e:
                        logger.debug(f"解析冷却结束日期失败: {cool_down_end}, {e}")
            
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
                # 统一获取current_date_obj
                if hasattr(current_date, 'strftime'):
                    current_date_obj = current_date
                else:
                    current_date_obj = datetime.strptime(current_date, '%Y-%m-%d').date()
                
                # 检查是否在资金流向冷却池中
                is_in_cool_down = stock_code in self.fund_flow_cool_down_pool
                
                if is_in_cool_down:
                    # 在冷却池中再次触发条件，直接移除
                    cool_down_end = self.fund_flow_cool_down_pool.get(stock_code, '')
                    reason = f"{stock_code}资金流向异常[{reason_detail}]，且已在冷却池(至{cool_down_end})，直接移除"
                    del self.fund_flow_cool_down_pool[stock_code]
                    logger.warning(reason)
                    return {'should_remove': True, 'reason': reason}
                else:
                    # 不在冷却池，加入冷却池3天
                    cool_down_end = self._get_future_trading_day(current_date_obj, 3)
                    self.fund_flow_cool_down_pool[stock_code] = cool_down_end
                    reason = f"{stock_code}资金流向异常[{reason_detail}]，加入冷却池至{cool_down_end}"
                    logger.warning(reason)
                    return {'should_remove': False, 'reason': reason}
            
            return {'should_remove': False, 'reason': ''}
            
        except Exception as e:
            logger.warning(f"检查资金流向条件失败: {stock_code}, {str(e)}")
            return {'should_remove': False, 'reason': ''}
    
    def _preload_stock_data(self, start_date: str, end_date: str, strategy_name: str = None) -> int:
        """预加载所有股票数据到内存（性能优化）
        
        Args:
            start_date: 回测开始日期
            end_date: 回测结束日期
            strategy_name: 策略名称，用于计算需要的历史数据天数
            
        Returns:
            预加载的股票数量
        """
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        
        # 根据策略参数计算需要的历史数据天数
        buffer_days = 60  # 基础缓冲
        required_days = buffer_days
        # 【2026-09-19】需全历史的策略：只对"需要的股票"取全历史（None = 全市场）
        full_history_codes = None
        
        if strategy_name:
            # 获取策略参数 - 需中英文名称映射（与 _execute_selection 保持一致）
            from utils.strategy_name_mapper import get_english_name
            mapped_name = get_english_name(strategy_name)
            strategy = self.strategy_registry.get_strategy(mapped_name)
            if not strategy:
                strategy = self.strategy_registry.get_strategy(strategy_name)
            if strategy and hasattr(strategy, 'params'):
                params = strategy.params
                max_value = 0
                
                # 常见回溯参数名 - 包含所有策略的历史数据需求参数
                lookback_keys = [
                    'lookback_days',                # 多金叉共振、多方炮、阻力位突破、启明星、底部趋势拐点
                    'high_drawdown_days',           # 超跌反弹：收盘价 vs 近 N 日最高价的回撤窗口
                    'pattern_days',                 # W底策略
                    'search_days',                  # 预留
                    'resonance_days',               # 预留
                    'limit_up_lookback_days',       # 涨停回马枪、涨停横盘
                    'lowest_point_lookback_days',   # 趋势加速拐点
                    'surge_lookback_days',          # 趋势加速拐点
                    'uptrend_lookback_days',        # 趋势加速拐点
                    'min_data_len',                 # 低位九转等：最少历史交易日（强约束，必须纳入预加载窗口）
                    'low_drawdown_window',          # 低位九转：距阶段高点回撤回溯窗口
                    'setup_window',                 # 低位九转：买入 Setup 连续根数（用于前置结构回溯）
                ]
                period_keys = ['ma_period', 'ma_short_period', 'ma_long_period', 'kdj_n', 'kdj_m1', 'kdj_m2',
                              'macd_short', 'macd_long', 'macd_signal', 'volume_ma_period', 'short_ma_period', 
                              'long_ma_period', 'period', 'min_pattern_days', 'max_break_days',
                              'short_period', 'mid_period', 'long_period', 'super_long_period']
                
                # 获取回溯天数
                for key in lookback_keys:
                    if key in params:
                        val = params[key]
                        if isinstance(val, (int, float)):
                            max_value = max(max_value, int(val))
                
                # 获取周期参数
                for key in period_keys:
                    if key in params:
                        val = params[key]
                        if isinstance(val, (int, float)):
                            max_value = max(max_value, int(val))
                
                required_days = max_value + buffer_days
                logger.info(f"策略 {strategy_name} 需要 {max_value} 天历史数据 + {buffer_days} 天缓冲")

                # 【2026-09-19】策略级特殊处理：需要"上市以来全历史"的策略（如次新腰斩）
                #   不能按参数天数截断窗口，否则「上市以来最高价」等全局指标失真。
                #   钩子：策略类属性 requires_full_history = True
                if getattr(strategy, 'requires_full_history', False):
                    required_days = 36500       # 100 年 ⇒ 等价于不截断（取全历史）
                    # 只对"需要的股票"取全历史：按策略钩子以**回测起始日**为界，
                    # 求出"该日之前 K 线根数少的次新 + 该日之后才上市的新股"（无未来函数）。
                    # 根数只增不减 → 该日已超阈值的股票后续不可能成为次新，可安全排除。
                    if hasattr(strategy, 'full_history_universe'):
                        full_history_codes = strategy.full_history_universe(
                            self.db_manager, start_date, params)
                    logger.info(f"策略 {strategy_name} 声明 requires_full_history=True，"
                                f"预加载改为全历史（仅限 %s 只需要的股票）",
                                len(full_history_codes) if full_history_codes else '全部')
        
        # SQL 查询起始日期：仅加载回测所需数据（start_date - required_days）
        # required_days 由策略参数 + buffer_days 计算得出，精确反映策略需要的历史数据量
        sql_start_dt = start_dt - timedelta(days=required_days)
        sql_start = sql_start_dt.strftime('%Y-%m-%d')
        if required_days >= 36500:
            # 需全历史的策略（requires_full_history）→ 从库内最早数据起取
            sql_start = '1990-01-01'

        logger.info(f"预加载股票数据: {sql_start} ~ {end_date} (需要历史: {required_days}天)")

        import pandas as pd

        # 第1步：一次SQL批量加载全市场K线（全部股票，不过滤ST/退市/数据量）
        step1_start = datetime.now()
        all_kline_df = self.db_manager.read_all_stocks_kline(
            sql_start, end_date, codes=full_history_codes)
        step1_time = (datetime.now() - step1_start).total_seconds()

        if all_kline_df.empty:
            logger.warning("批量K线数据为空，跳过预加载")
            return 0

        # 统一日期格式为字符串（SQL返回已是YYYY-MM-DD字符串，确保格式一致）
        if not pd.api.types.is_string_dtype(all_kline_df['date']):
            all_kline_df['date'] = pd.to_datetime(all_kline_df['date']).dt.strftime('%Y-%m-%d')
        # 按code和date正序排列
        all_kline_df = all_kline_df.sort_values(['code', 'date'])

        total_codes = all_kline_df['code'].nunique()
        logger.info(f"[预加载-第1步] 批量K线: {len(all_kline_df)} 行, {total_codes} 只股票, 耗时 {step1_time:.1f}s")

        # 第2步：批量获取股票名称
        step2_start = datetime.now()
        all_stock_names = self.db_manager.get_all_stock_names()
        self.stock_name_cache.update(all_stock_names)
        step2_time = (datetime.now() - step2_start).total_seconds()
        logger.info(f"[预加载-第2步] 批量名称: {len(all_stock_names)} 只, 耗时 {step2_time:.1f}s")

        # 第3步：按code分组构建缓存（全部加载，不做任何过滤）
        # 数据不足、ST、退市等过滤统一在选股时处理
        step3_start = datetime.now()
        loaded = 0
        processed = 0

        grouped = all_kline_df.groupby('code')
        for code, group_df in grouped:
            # 缓存原始数据（含退市、ST，用于价格查询和移动止损计算）
            self.stock_data_cache[code] = group_df.copy()
            # 缓存有效股票（全部入池，选股时再做数据量/ST/退市过滤）
            self.stock_filtered_cache[code] = group_df.copy()
            loaded += 1

            # 每500只显示一次进度
            processed += 1
            if processed % 500 == 0:
                logger.info(f"预加载进度: {processed}/{total_codes}, 已加载: {loaded}")

        step3_time = (datetime.now() - step3_start).total_seconds()

        total_time = step1_time + step2_time + step3_time
        logger.info(f"预加载完成: 全部加载 {loaded} 只股票, 总耗时 {total_time:.1f}s "
                    f"(步骤: SQL={step1_time:.1f}s 名称={step2_time:.1f}s 分组={step3_time:.1f}s)")
        return loaded
    
    def _execute_selection(self, strategy_name: str, date: date) -> List[Dict]:
        """执行选股（从缓存读取，使用日期切片）
        
        Args:
            strategy_name: 策略名称
            date: 选股日期
            
        Returns:
            选股结果列表
        """
        try:
            # 确保策略注册表已加载策略
            if not self.strategy_registry.strategies:
                self.strategy_registry.auto_register_from_directory("strategy")
            
            # 获取策略 - 策略注册时使用类名（如ContinuousRisingWithVolumeStrategyV2）
            # 需要先尝试映射为中文名称再转类名
            mapped_name = get_english_name(strategy_name)
            strategy = self.strategy_registry.get_strategy(mapped_name)
            
            if not strategy:
                # 尝试直接用原始名称查找
                strategy = self.strategy_registry.get_strategy(strategy_name)
            
            if not strategy:
                raise ValueError(f"策略 {strategy_name} 不存在")
            
            # 标准化返回格式
            standardized_stocks = []
            
            # 从缓存遍历全部股票，选股时做过滤
            for code, df in self.stock_filtered_cache.items():
                try:
                    # 股票名称：供策略的 _validate_stock_name 校验（ST/退市/未知等）
                    # 必须在此赋值：下方 execute_selection 依赖该变量。历史上一度在
                    # "移除 ST 过滤"时被连带删除，导致 NameError 并被 except 静默吞掉，
                    # 表现为全市场选股恒为 0 只，此处补回并注明用途防止再次误删。
                    # 默认值用空串而非"未知"：策略层将"未知"判为无效名称会误杀股票。
                    name = self.stock_name_cache.get(code, '')

                    # 日期切片：只取到目标日期为止的数据
                    date_str = date.strftime('%Y-%m-%d')
                    df_to_date = df[df['date'] <= date_str].copy()
                    
                    # 过滤1：数据为空 → 跳过
                    if df_to_date.empty:
                        continue
                    
                    # 注意：不过滤 ST/退市股票（历史回测无法准确还原当时状态，交给策略自身的 quick_filter 处理）
                    
                    # 反转数据为倒序（最新的在前），供策略使用
                    # 仅当数据为升序时才反转
                    if len(df_to_date) > 1 and df_to_date['date'].iloc[0] < df_to_date['date'].iloc[-1]:
                        df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)
                    
                    # 使用标准的 execute_selection 流程，确保指标被正确计算
                    # execute_selection 包含：数据验证 -> 快速过滤 -> 计算指标 -> 选股条件检查
                    # selection_date 传入选股日期，确保使用正确的日期进行数据时效性检查
                    signal_list = strategy.execute_selection(df_to_date, code, name, selection_date=date_str)
                    
                    # 处理选股结果
                    if signal_list:
                        for signal in signal_list:
                            # 生成股票详情链接
                            # 支持多个数据源的链接格式
                            stock_detail_url = self._generate_stock_detail_url(code)
                            
                            stock_info = {
                                'stock_code': code,
                                'stock_name': name,
                                'signal': signal,
                                'detail_url': stock_detail_url,  # 添加详情链接
                                'detail_link': f"[{code}]({stock_detail_url})"  # Markdown 格式链接
                            }
                            standardized_stocks.append(stock_info)
                            
                except Exception as e:
                    # 单只股票选股失败不影响整体流程
                    logger.debug(f"股票 {code} 选股失败: {str(e)}")
                    continue
            
            logger.info(f"{strategy_name} 策略在 {date} 选出 {len(standardized_stocks)} 只股票")
            
            return standardized_stocks
            
        except Exception as e:
            logger.error(f"执行选股失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _score_stocks(self, stocks: List[Dict], strategy_name: str, date: date) -> List[Dict]:
        """对股票进行评分（回测模式）

        使用 BacktestScoreCalculator 进行高效评分：
        - 技术面得分 = Σ(策略权重 × 命中标志)
        - 综合得分 = 技术面×0.35 + 资金面×0.35 + 基本面×0.10 + 板块×0.10 + 事件×0.10
        - 一票否决：M头策略 + 多死叉共振同时命中 → -100分
        - 技术面否决后立即跳过其他维度计算

        Args:
            stocks: 股票列表（来自选股结果）
            strategy_name: 策略名称（类名）
            date: 评分日期

        Returns:
            带评分的股票列表
        """
        if not stocks:
            return []

        date_str = date.strftime('%Y-%m-%d')

        # 获取策略的中文名称（用于评分）
        strategy = self.strategy_registry.get_strategy(strategy_name)
        strategy_display_name = strategy.name if strategy else strategy_name
        logger.info(f"评分使用的策略名称: {strategy_display_name} (类名: {strategy_name})")

        # 入池规则：简化模式下评分器只判一票否决（跳过所有维度打分）
        from trading.pool_entry_rules import resolve_pool_entry_simplified

        _simplified = resolve_pool_entry_simplified({}, self._load_engine_config())

        # 使用回测专用评分器进行批量评分
        scored_stocks = self.score_calculator.calculate_batch_scores(
            stocks=stocks,
            score_date=date_str,
            strategy_name=strategy_display_name,
            simplified=_simplified
        )

        return scored_stocks

    def _select_and_score_stocks(self, strategy_name: str, date: date, config: Dict) -> List[Dict]:
        """执行选股、评分、筛选，得到候选股票池
        
        封装选股流程，返回通过评分的候选股票列表。
        
        Args:
            strategy_name: 策略名称
            date: 选股日期
            config: 回测配置
            
        Returns:
            候选股票列表（已评分且通过筛选）
        """
        logger.info(f"开始执行选股，策略: {strategy_name}，择时策略: {self.timing_strategy_name}，日期: {date}")
        
        # 执行选股
        selected_stocks = self._execute_selection(strategy_name, date)
        logger.info(f"选股完成，共选出 {len(selected_stocks)} 只股票")
        
        if not selected_stocks:
            return []
        
        # 评分
        logger.info(f"开始对 {len(selected_stocks)} 只股票进行评分")
        scored_stocks = self._score_stocks(selected_stocks, strategy_name, date)
        
        # 记录每只股票的综合评分
        logger.info("\n股票评分详情:")
        for stock in scored_stocks:
            logger.info(f"  - {stock['stock_code']} {stock['stock_name']}: 综合评分={stock['score']}，否决标志={stock.get('veto_flag', False)}")
        
        # 筛选：入池规则（可配置，见 trading/pool_entry_rules.py）
        #   simplified=True  → 只剔除一票否决，其余全部入池（解决池/持仓不足）
        #   simplified=False → 原行为：否决票 + 评分达标
        from trading.pool_entry_rules import filter_candidates, resolve_pool_entry_simplified

        score_threshold = config.get('score_threshold', 60)
        _simplified = resolve_pool_entry_simplified(config, self._load_engine_config())
        candidate_stocks = filter_candidates(scored_stocks, score_threshold, _simplified)
        if _simplified:
            logger.info(f"【入池规则】简易评分：先排除一票否决，资金面得分>={score_threshold} 入池")
        else:
            logger.info(f"【入池规则】标准评分：否决票 + 综合评分>={score_threshold}")

        logger.info(f"\n筛选后待买入股票数: {len(candidate_stocks)}")
        if candidate_stocks:
            logger.info("待买入股票列表:")
            for stock in candidate_stocks:
                logger.info(f"  - {stock['stock_code']} {stock['stock_name']}: 评分={stock['score']}")
        
        return candidate_stocks

    def _add_holdings_to_pool(self, positions, current_date, today_sold_stocks,
                              strategy_name: str = '', enabled: bool = True) -> int:
        """持仓股自动入池（**当日已卖出的不计**），返回新增数量

        目的：策略切换清空股票池 / 候选被买入消费后，持仓股仍留在候选池中，
              这样择时给出 add 信号时才能正常加仓（否则池空 → 无法加仓）。

        Args:
            positions: 持仓。回测为 `list[dict]`（含 stock_code/stock_name）；
                       实盘为 `dict{code: {...}}`（键已归一化为纯数字代码）——两者均支持。
            current_date: 当日日期
            today_sold_stocks: 当日已卖出代码集合（不计入池）
            strategy_name: 当日策略名（写入池条目，供 Kelly/池移除配置查找）
            enabled: 开关（调用方从 `pool_entry.auto_add_holdings` 解析后传入）

        说明：
          - 已在池中的不重复加入；
          - 入池评分记为 0（仅用于池内排序，不会抢占新股优先级）；
          - 支撑位按当前策略计算（失败则记 0，不影响流程）。
        """
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
                if (not code or code in pool_codes
                        or code in (today_sold_stocks or set())):
                    continue

                info = {'stock_code': code,
                        'stock_name': pos.get('stock_name', ''),
                        'score': 0,
                        'veto_flag': False}
                try:
                    sup = self._calculate_support_level(info, current_date, strategy_name)
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

            if added:
                logger.info(f"【持仓入池】新增 {added} 只持仓股到股票池（当日卖出不计），"
                            f"池内合计 {len(self.buy_candidate_pool)} 只")
        except Exception as e:
            logger.warning(f"持仓股入池失败（不影响回测）: {e}")
        return added
    
    def _has_trading_data_on_date(self, stock_code: str, date: date) -> bool:
        """检查股票在指定日期是否有真实行情数据（非停牌、非退市）
        
        回测时通过股票缓存判断：如果缓存中该股票没有指定日期的任何数据，
        说明该股票在当日停牌或已退市，不可交易。
        
        Args:
            stock_code: 股票代码
            date: 检查日期
            
        Returns:
            True: 有真实行情数据，可交易
            False: 无数据（停牌/退市），不可交易
        """
        date_str = date.strftime('%Y-%m-%d')
        
        # 从缓存中查找该日期是否有数据
        df = self.stock_data_cache.get(stock_code)
        if df is None or df.empty:
            return False
        
        # 检查当日是否有数据行
        df_date = df[df['date'] == date_str]
        if df_date.empty:
            return False
        
        # 检查关键价格字段是否有效（open > 0 表示有真实交易）
        if 'open' in df_date.columns:
            open_val = df_date.iloc[0]['open']
            if open_val is None or (hasattr(open_val, '__float__') and float(open_val) <= 0):
                return False
        
        return True

    # ==================== 双边成交滑点（2026-09-23 新增）====================
    # 为什么需要：原实现 open 模式按 T 日开盘价**零滑点**成交 ✗，且
    #   calculate_backtest_cost 明确"不含滑点" ✗ → 回测系统性偏乐观 ✗。
    # 口径（对**最终成交价**双边调整 ✓，费用仍按原口径另计 ✓）：
    #   买入成交价 = 基准成交价 × (1 + buy)
    #   卖出成交价 = 基准成交价 × (1 - sell)
    # 读取优先级：run_backtest 的 config['slippage'] > config/backtest_engine_config.yaml
    #             的 slippage 节 > 本默认值（各 0.3% ✓）
    # 设为 0 可关闭（用于复现历史回测结果 ✓）。
    # 注意：ma_limit 买入模式的委托价**自带** slippage ✗ → 该模式不再叠加本滑点 ✓（避免双计 ✗）
    DEFAULT_SLIPPAGE = {'buy': 0.003, 'sell': 0.003}

    def _slippage_rates(self, config: Dict) -> Dict[str, float]:
        """解析双边滑点比例（买入/卖出 ✓）"""
        rates = dict(self.DEFAULT_SLIPPAGE)
        # 1) 引擎配置文件 config/backtest_engine_config.yaml 的 slippage 节
        try:
            file_cfg = (self._load_engine_config() or {}).get('slippage')
            if isinstance(file_cfg, dict):
                for k in ('buy', 'sell'):
                    if file_cfg.get(k) is not None:
                        rates[k] = max(0.0, float(file_cfg[k]))
        except (TypeError, ValueError):
            pass
        # 2) run_backtest 传入的 config['slippage']（最高优先级 ✓）
        raw = (config or {}).get('slippage')
        if raw is not None:
            try:
                if isinstance(raw, dict):
                    for k in ('buy', 'sell'):
                        if raw.get(k) is not None:
                            rates[k] = max(0.0, float(raw[k]))
                else:
                    v = max(0.0, float(raw))      # 标量写法：买卖同值 ✓
                    rates['buy'] = rates['sell'] = v
            except (TypeError, ValueError):
                pass
        return rates

    # 买入执行方式默认配置
    # mode 默认 'open'，保证不配置时行为与改造前完全一致（后向兼容）
    DEFAULT_BUY_EXECUTION = {
        'mode': 'open',               # open=开盘价无条件成交 | ma_limit=均线委托+滑点+触达成交
        'ma_period': 5,               # 委托价基准均线周期（5日线）
        'ma_source': 'close',         # 均线计算所用价格字段
        'ma_base': 'prev_day',        # 均线基准日：prev_day=截至T-1（防前视）
        'slippage': 0.005,            # 滑点 0.5%（买入取不利方向，即更贵）
        'fill_price': 'better',       # better=min(开盘价, 委托价) | limit=委托价
        'min_periods': 5,             # 均线有效所需最小样本数
        'insufficient_data': 'fallback_open',  # 样本不足时回退开盘价成交
        'on_unfilled': 'keep',        # 未成交时保留候选池
    }

    @staticmethod
    def _should_apply_buy_filter(result, existing_pos) -> bool:
        """买入前K线过滤是否生效

        仅【首次建仓】生效；【加仓】跳过该过滤：
          - 加仓由择时策略自身条件把关，重复过滤会误杀已盈利的加仓信号
          - 与实盘运行器保持一致（运行器加仓不做涨幅/涨停基因检查）

        Args:
            result: 择时结果（TimingResult）
            existing_pos: 已有持仓（None 表示首次建仓）

        Returns:
            True=执行K线过滤，False=跳过
        """
        if result is None:
            return existing_pos is None
        trade_type = getattr(result, 'trade_type', '') or ''
        if trade_type == 'add':
            return False
        return existing_pos is None

    def _get_highest_price_since_entry(self, stock_code: str, buy_date,
                                       until_date, buy_price: float) -> float:
        """获取建仓以来（【不含建仓日】）至 until_date 的最高价（用于移动止损）

        与实盘运行器保持一致（实盘 `_exclude_buy_day` 排除建仓日）：
        建仓日成交前形成的高点不应计入"买入以来最高价"，
        否则移动止损位被抬高，建仓首日即可能误触发移动止损。

        Args:
            stock_code: 股票代码
            buy_date: 建仓日（date）
            until_date: 截止日（date，含）；None 时返回 buy_price
            buy_price: 买入价（无有效数据时兜底）

        Returns:
            最高价（不低于 buy_price）
        """
        if buy_date is None or until_date is None:
            return buy_price

        df = self.stock_data_cache.get(stock_code)
        if df is None or df.empty:
            return buy_price

        buy_date_str = buy_date.strftime('%Y-%m-%d')
        until_str = until_date.strftime('%Y-%m-%d')
        # 不含建仓日：起始日严格大于建仓日
        mask = (df['date'] > buy_date_str) & (df['date'] <= until_str)
        filtered_df = df[mask]
        if filtered_df.empty:
            return buy_price

        return max(buy_price, float(filtered_df['high'].max()))

    def _resolve_buy_execution(self, stock_code: str, current_date: date,
                               config: Dict, df_to_date: pd.DataFrame = None) -> Dict:
        """解析买入执行结果：委托价、是否成交、成交价与未成交原因

        两种模式（由 config['buy_execution']['mode'] 决定）：
          - 'open'（默认）：T 日开盘价无条件成交，行为与改造前一致（后向兼容）
          - 'ma_limit'：以截至 T-1 的均线为基准计算委托价（含滑点），
            仅当 T 日最低价 <= 委托价 才视为成交；成交价取 min(开盘价, 委托价)

        Args:
            stock_code: 股票代码
            current_date: 当前回测日期（T 日）
            config: 回测配置，读取其中的 buy_execution 节
            df_to_date: 截至 T 日的K线（倒序，最新在前），用于计算均线

        Returns:
            dict: {'filled': 是否成交, 'price': 成交价, 'order_price': 委托价,
                   'reason': 未成交原因, 'mode': 执行方式}
        """
        # 合并配置：引擎内置默认 < 配置文件(backtest_engine_config.yaml) < 回测参数
        cfg = dict(self.DEFAULT_BUY_EXECUTION)
        engine_config = self._load_engine_config() or {}
        cfg.update(engine_config.get('buy_execution') or {})
        cfg.update(config.get('buy_execution') or {})
        mode = cfg.get('mode', 'open')

        # T 日开盘价：两种模式都需要（ma_limit 用于 better 成交价与样本不足回退）
        open_price = self._get_stock_price(stock_code, current_date, 'open')
        if open_price is None or open_price <= 0:
            # T 日无开盘数据时回退到前一交易日，避免无法成交（沿用原有逻辑）
            prev_buy_day = self._get_previous_trading_day(current_date)
            open_price = self._get_stock_price(
                stock_code, prev_buy_day, 'open') if prev_buy_day else None

        # 模式一：开盘价无条件成交（保持原行为）
        if mode != 'ma_limit':
            if open_price is None or open_price <= 0:
                return {'filled': False, 'price': 0.0, 'order_price': 0.0,
                        'reason': '无有效开盘价', 'mode': mode}
            return {'filled': True, 'price': open_price, 'order_price': open_price,
                    'reason': '', 'mode': mode}

        # 模式二：均线委托 + 滑点 + 最低价触达判定
        ma_period = int(cfg.get('ma_period', 5))
        min_periods = int(cfg.get('min_periods', ma_period))
        ma_source = cfg.get('ma_source', 'close')
        slippage = float(cfg.get('slippage', 0.005))

        # 1) 计算截至 T-1 的均线：df_to_date 为倒序（最新在前），第 0 行是 T 日，
        #    必须剔除后再取窗口，否则会把 T 日收盘价算进去造成前视偏差
        ma_value = None
        if df_to_date is not None and not df_to_date.empty and ma_source in df_to_date.columns:
            hist = df_to_date[ma_source].iloc[1:] if len(df_to_date) > 1 else df_to_date[ma_source]
            hist = pd.to_numeric(hist, errors='coerce').dropna()
            if len(hist) >= min_periods:
                ma_value = float(hist.iloc[:ma_period].mean())

        # 2) 样本不足（如新上市不足5日）→ 按确认口径取开盘价成交
        if ma_value is None or ma_value <= 0:
            if open_price and open_price > 0:
                return {'filled': True, 'price': open_price, 'order_price': open_price,
                        'reason': '均线样本不足，回退开盘价成交', 'mode': mode}
            return {'filled': False, 'price': 0.0, 'order_price': 0.0,
                    'reason': '均线样本不足且无开盘价', 'mode': mode}

        # 3) 委托价：买入滑点取不利方向（更贵）
        order_price = ma_value * (1.0 + slippage)

        # 4) 当日最低价（用于判断是否触达委托价）
        low_price = self._get_stock_price(stock_code, current_date, 'low')
        if low_price is None or low_price <= 0:
            low_price = open_price

        # 5) 触达判定：最低价 <= 委托价 才算成交
        if low_price is None or low_price > order_price:
            return {'filled': False, 'price': order_price, 'order_price': order_price,
                    'reason': '当日最低价未触及委托价', 'mode': mode}

        # 6) 成交价：better=min(开盘价, 委托价)，即以更优价格成交
        if cfg.get('fill_price', 'better') == 'better' and open_price and open_price > 0:
            fill_price = min(open_price, order_price)
        else:
            fill_price = order_price

        return {'filled': True, 'price': fill_price, 'order_price': order_price,
                'reason': '', 'mode': mode}

    def _get_stock_price(self, stock_code: str, date: date, price_type: str) -> float:
        """获取股票价格
        
        Args:
            stock_code: 股票代码
            date: 日期
            price_type: 价格类型 (open, close, high, low, prev_close)
            
        Returns:
            价格
        """
        try:
            # 特殊处理：获取前一天收盘价
            if price_type == 'prev_close':
                # 获取前一天的日期
                prev_date = self._get_previous_trading_day(date)
                if prev_date:
                    return self._get_stock_price(stock_code, prev_date, 'close')
                return None
            
            # 1. 优先从本地数据库获取
            date_str = date.strftime('%Y-%m-%d')
            sql = f"""
                SELECT {price_type} FROM stock_kline 
                WHERE code = ? AND date = ?
            """
            result = self.db_manager.query_one(sql, (stock_code, date_str))
            
            if result and result.get(price_type) is not None:
                return float(result[price_type])
            
            # 2. 备选：从tushare获取
            try:
                import tushare as ts
                
                # 读取Tushare token
                tushare_token = None
                try:
                    import json
                    with open('config/tushare_config.json', 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        tushare_token = config.get('token') or config.get('api_key')
                except:
                    pass
                
                if tushare_token:
                    pro = ts.pro_api(tushare_token)
                    df = pro.daily(
                        ts_code=f"{stock_code}.SH" if stock_code.startswith('6') else f"{stock_code}.SZ",
                        start_date=date_str,
                        end_date=date_str
                    )
                    if not df.empty:
                        if price_type == 'open':
                            return float(df.iloc[0]['open'])
                        elif price_type == 'close':
                            return float(df.iloc[0]['close'])
                        elif price_type == 'high':
                            return float(df.iloc[0]['high'])
                        elif price_type == 'low':
                            return float(df.iloc[0]['low'])
            except Exception as e:
                logger.debug(f"Tushare获取价格失败: {str(e)}")
            
            # 3. 备选：使用StockDataFetcher获取实时价格（仅用于收盘价，获取开盘价时不应使用实时价）
            # 注意：实时价格是当前价，不等于开盘价，开盘价只能从数据库获取
            if date == datetime.now().date() and price_type != 'open':
                price = self.stock_data_fetcher.get_stock_price(stock_code)
                if price:
                    return price
            
            # 4. 备选：从缓存中获取价格（用于回测）
            if stock_code in self.stock_data_cache:
                df = self.stock_data_cache[stock_code]
                date_str = date.strftime('%Y-%m-%d')
                df_date = df[df['date'] == date_str]
                if not df_date.empty:
                    if price_type in df_date.columns:
                        price = df_date.iloc[0][price_type]
                        if price is not None and not pd.isna(price):
                            logger.debug(f"从缓存获取股票 {stock_code} 日期 {date_str} {price_type} 价格: {price}")
                            return float(price)
                else:
                    logger.debug(f"缓存中没有股票 {stock_code} 日期 {date_str} 的数据")
            else:
                logger.debug(f"缓存中没有股票 {stock_code} 的数据")
            
            # 如果所有方法都失败，取前一交易日收盘价
            if stock_code in self.stock_data_cache:
                df = self.stock_data_cache[stock_code]
                # 查找目标日期之前最近的有效收盘价
                # 数据按日期升序排列，使用 iloc[-1:] 确保取到最接近目标日期的最近一天
                df_before = df[df['date'] < date_str].iloc[-1:]
                if not df_before.empty and 'close' in df_before.columns:
                    prev_close = df_before.iloc[0]['close']
                    if prev_close is not None and not pd.isna(prev_close):
                        logger.warning(f"股票 {stock_code} 日期 {date_str} 无{price_type}数据，使用前一交易日收盘价: {prev_close}")
                        return float(prev_close)
            
            logger.error(f"无法获取股票 {stock_code} 日期 {date_str} 的任何价格数据")
            return 0.0
            
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 价格失败: {str(e)}")
            return 10.0
    
    def _execute_buy(self, stock_code: str, stock_name: str, selection_date: date, 
                     buy_date: date, buy_price: float, buy_amount: float, 
                     quantity: int) -> Dict:
        """执行买入操作
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            selection_date: 选入日期
            buy_date: 买入日期
            buy_price: 买入价格
            buy_amount: 买入金额
            quantity: 买入数量
            
        Returns:
            买入记录
        """
        # 计算买入成本
        cost_info = calculate_backtest_cost(stock_code, buy_price, quantity, is_buy=True)
        
        # 生成股票详情链接
        stock_detail_url = self._generate_stock_detail_url(stock_code)
        
        return {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'selection_date': selection_date,
            'buy_date': buy_date,
            'buy_price': buy_price,
            'buy_amount': buy_amount,
            'quantity': quantity,
            'sell_date': None,
            'sell_price': None,
            'sell_amount': None,
            'sell_type': None,
            'return_rate': None,
            'profit_loss': None,
            'hold_days': None,
            'detail_url': stock_detail_url,
            # 交易成本字段
            'buy_commission': cost_info['commission'],
            'buy_transfer_fee': cost_info['transfer_fee'],
            'sell_commission': 0,
            'sell_transfer_fee': 0,
            'sell_stamp_tax': 0
        }
    
    def _calc_total_assets(self, current_date, positions: List[Dict],
                           current_capital: float) -> float:
        """计算总资产 = 可用资金 + 持仓市值

        持仓市值用**前一交易日收盘价**估值，避免未来函数（与首次建仓的凯利金额口径一致）。
        供首次建仓与加仓共用，确保两处凯利金额一致。
        """
        total_assets = current_capital
        prev_trading_day = self._get_previous_trading_day(current_date)
        for position in positions:
            position_price = self._get_stock_price(position['stock_code'], prev_trading_day, 'close')
            if position_price is None or position_price <= 0:
                position_price = position['buy_price']
            total_assets += position['quantity'] * position_price
        return total_assets

    def _check_no_new_high_exit(self, stock_code: str, as_of_date, window: int,
                                ma_period: int, buy_date=None) -> Tuple[bool, bool, str]:
        """判断"三日（滚动）未创新高 且 收盘跌破 N 日线"卖出条件

        判据（均以 as_of_date 及之前的数据为准，避免前视偏差）：
          A. **未创新高**：最近 window 日的最高价 < **买入以来**的最高价
             `max(high[-window:]) < max(high[buy_date .. as_of_date])`
             —— 即近 window 日再也刷不出持仓期新高，涨势已停滞
          B. **跌破均线**：as_of_date 收盘 < MA(ma_period)（默认 5 日线）

        Args:
            stock_code: 股票代码
            as_of_date: 判定基准日（调用方传 T-1，避免前视偏差）
            window: 未创新高的滚动窗口（默认 3 个交易日）
            ma_period: 均线周期（默认 5）
            buy_date: 建仓日；"买入以来最高价"自该日起算（含建仓日）。
                      未提供时退化为"截至基准日的全部数据"。

        返回:
            (A 是否成立, B 是否成立, 说明文本)
        """
        try:
            df = self.stock_filtered_cache.get(stock_code)
            if df is None or df.empty:
                return False, False, '无K线数据'
            d = df
            # 统一为正序（最旧在前）
            if len(d) > 1 and str(d['date'].iloc[0]) > str(d['date'].iloc[-1]):
                d = d.iloc[::-1].reset_index(drop=True)
            date_str = (as_of_date.strftime('%Y-%m-%d')
                        if hasattr(as_of_date, 'strftime') else str(as_of_date))
            d = d[d['date'] <= date_str]
            need = max(window, ma_period)
            if len(d) < need:
                return False, False, f'数据不足({len(d)}<{need})'
            high = d['high'].astype(float)
            close = d['close'].astype(float)
            recent_high = float(high.iloc[-window:].max())

            # 买入以来最高价（含建仓日）
            if buy_date is not None:
                bd_str = (buy_date.strftime('%Y-%m-%d')
                          if hasattr(buy_date, 'strftime') else str(buy_date))
                since_entry = d[d['date'] >= bd_str]
            else:
                since_entry = d
            since_high = (float(since_entry['high'].max())
                          if not since_entry.empty else recent_high)

            ma = float(close.iloc[-ma_period:].mean())
            cur_close = float(close.iloc[-1])
            a = recent_high < since_high
            b = cur_close < ma
            detail = (f'近{window}日最高{recent_high:.2f} < 买入以来最高{since_high:.2f}'
                      f'(未创新高={a})；收盘{cur_close:.2f} vs MA{ma_period} '
                      f'{ma:.2f}(破线={b})')
            return a, b, detail
        except Exception as e:
            logger.debug(f'三日未创新高判定异常({stock_code}): {e}')
            return False, False, '判定异常'

    def _process_sell(self, positions: List[Dict], current_date: date, config: Dict) -> Tuple[List[Dict], List[Dict]]:
        """处理卖出操作
        
        职责划分：
        - 回测引擎负责：T+1检查、止盈止损执行
        - 择时策略负责：买卖信号判断
        
        Args:
            positions: 持仓列表
            current_date: 当前日期
            config: 回测配置
            
        Returns:
            (剩余持仓列表, 卖出记录列表)
        """
        remaining_positions = []
        sell_records = []
        
        # 获取卖出条件参数
        take_profit = config.get('take_profit', 21)  # 止盈21%
        stop_loss = config.get('stop_loss', -7)  # 止损7%
        hold_period = config.get('hold_period', 10)
        
        # 获取移动止损配置（简化版）
        enable_trailing_stop = config.get('enable_trailing_stop', True)
        base_stop_level = -6  # 基础止损固定为-6%
        trailing_trigger_threshold = 5  # 触发移动止损的最低收益率（最高收益≥5%才启用移动止损）
        # 移动止损自最高价的回撤比例(%，默认8；与实盘运行器一致)
        trailing_drawdown_pct = config.get('trailing_drawdown_pct', 8)
        
        # 获取亏损冷却期配置
        #   2026-09-12 新规则：任意亏损即冷却 1 个月（21 个交易日）；
        #   连续亏损 2 次冷却 1 年（250 个交易日）。
        #   默认**取消亏损门槛**（cool_down_threshold 不配置 = 无门槛）；
        #   如需恢复阈值，显式配置 cool_down_threshold（如 -8）即可。
        enable_loss_cool_down = config.get('enable_loss_cool_down', True)
        cool_down_threshold = config.get('cool_down_threshold')   # None = 无门槛
        cool_down_days = config.get('cool_down_days', 21)         # 1 个月
        
        # 获取持仓过期配置（提高资金利用率）
        enable_position_expire = config.get('enable_position_expire', True)
        position_expire_hold_days = config.get('position_expire_hold_days', 10)
        position_expire_return_threshold = config.get('position_expire_return_threshold', 5)
        
        # 获取连续亏损限制配置
        enable_consecutive_loss_limit = config.get('enable_consecutive_loss_limit', True)
        max_consecutive_losses = config.get('max_consecutive_losses', 2)
        consecutive_loss_cool_down = config.get('consecutive_loss_cool_down', 250)   # 1 年
        
        for position in positions:
            stock_code = position['stock_code']
            stock_name = position['stock_name']
            
            # 计算持有天数（基于交易日）
            buy_date_str = position['buy_date'].strftime('%Y-%m-%d')
            current_date_str = current_date.strftime('%Y-%m-%d')
            trading_days = self._get_trading_dates(buy_date_str, current_date_str)
            hold_days = len(trading_days) - 1
            
            # 止盈止损信号判定用前一日收盘价；实际成交用T日开盘价（前一日收盘判定触发，当日开盘卖出）
            prev_trading_day = self._get_previous_trading_day(current_date)
            # 止损信号严格使用T-1日收盘价，无数据时不做止损判断（避免前视偏差）
            signal_close = self._get_stock_price(stock_code, prev_trading_day, 'close') if prev_trading_day else None
            # 实际成交价：处理日(current_date)当天开盘价
            sell_price = self._get_stock_price(stock_code, current_date, 'open')
            if sell_price is None or sell_price <= 0:
                # 当日无开盘数据时回退到当日收盘价，避免无法成交
                sell_price = self._get_stock_price(stock_code, current_date, 'close')
            # 【2026-09-23】卖出滑点：成交价取不利方向（更便宜 ✓）
            _slip = getattr(self, '_slippage', self.DEFAULT_SLIPPAGE)
            if sell_price and sell_price > 0 and _slip['sell']:
                sell_price = round(sell_price * (1.0 - _slip['sell']), 4)
            
            # 停牌/退市检查：当日无行情数据时不可卖出，保留持仓
            if not self._has_trading_data_on_date(stock_code, current_date):
                logger.info(f"  {stock_code} {stock_name} - 当日{current_date}无行情数据（停牌/退市），保留持仓")
                remaining_positions.append(position)
                continue
            
            # 计算含成本的收益率
            # 买入成本
            buy_commission = position.get('buy_commission', 0)
            buy_transfer_fee = position.get('buy_transfer_fee', 0)
            total_buy_cost = buy_commission + buy_transfer_fee
            # 实际投入成本 = 买入金额 + 买入佣金 + 过户费
            actual_cost = position['buy_amount'] + total_buy_cost
            
            # 卖出时计算成本（预估，待创建卖出记录时更新）
            # 注意：印花税只在卖出时收取
            sell_commission_estimate = sell_price * position['quantity'] * 0.00015
            sell_transfer_fee_estimate = sell_price * position['quantity'] * 0.00001 if stock_code.startswith('6') else 0
            sell_stamp_tax_estimate = sell_price * position['quantity'] * 0.001  # 印花税预估

            # 毛估收益率 = (卖出金额 - 预估卖出成本 - 实际买入成本) / 实际买入成本
            gross_sell_amount = sell_price * position['quantity']
            estimated_net_proceed = gross_sell_amount - sell_commission_estimate - sell_transfer_fee_estimate - sell_stamp_tax_estimate
            return_rate = (estimated_net_proceed - actual_cost) / actual_cost * 100
            
            # 获取买入价和当前最高价（从买入日期到前一交易日的最高价）
            buy_price = position['buy_price']
            buy_date = position['buy_date']
            
            # 计算从买入日期到前一交易日的最高价
            # 移动止损的最高价应该是买入日期至前一日的最高价，不包括当日最高价
            # 移动止损的最高价：截至前一日的最高价，且【不含建仓日】
            # 与实盘运行器一致（实盘 _exclude_buy_day 排除建仓日）：
            # 建仓日成交前形成的高点不应抬高移动止损位，否则建仓首日即可能误触发
            current_highest_price = self._get_highest_price_since_entry(
                stock_code, buy_date, prev_trading_day, buy_price)
            
            # 计算最高价收益率
            highest_price_return = (current_highest_price - buy_price) / buy_price * 100
            
            # 根据是否有择时策略决定卖出规则描述
            if self.timing_strategy:
                sell_rule = f"止盈={take_profit}%, 止损={stop_loss}%, 由策略决定卖出"
            else:
                sell_rule = f"止盈={take_profit}%, 止损={stop_loss}%, 持有期={hold_period}天"
            logger.debug(f"检查持仓 - {stock_code} {stock_name}: 买入日期={buy_date_str}, "
                       f"持有天数={hold_days}, 收益率(含成本)={return_rate:.2f}%, 最高价={current_highest_price:.2f}, 最高价收益率={highest_price_return:.2f}%, {sell_rule}")
            
            # 初始化卖出决策
            sell_type = None
            reduce_quantity = 0
            sell_quantity = position['quantity']
            
            # T+1规则：当天买入的股票不能当天卖出
            if hold_days > 0:
                # 1. 先检查止盈止损（优先级最高）
                if return_rate >= take_profit:
                    sell_type = 'take_profit'
                    logger.info(f"  {stock_code} {stock_name} - 触发止盈: 收益率 {return_rate:.2f}% >= {take_profit}%")
                else:
                    # 计算当前止损线
                    current_stop = base_stop_level  # 默认使用基础止损-6%
                    stop_price = buy_price * (1 + base_stop_level / 100)
                    
                    if enable_trailing_stop:
                        # 移动止损逻辑：
                        # - 最高收益 < 5%：使用固定止损 -6%
                        # - 最高收益 >= 5%：移动止损 = 截至前一日的最高价 × (1 - 回撤%)
                        if highest_price_return >= trailing_trigger_threshold:
                            stop_price = current_highest_price * (1 - trailing_drawdown_pct / 100)
                            current_stop = (stop_price - buy_price) / buy_price * 100
                        
                        logger.info(f"  {stock_code} {stock_name} - 移动止损: 买入价={buy_price:.2f}, 最高价={current_highest_price:.2f}, 最高价收益率={highest_price_return:.2f}%, 止损价={stop_price:.2f}")
                    
                    # 检查是否触发止损（包括移动止损），用前一日收盘价判定
                    # signal_close 为 None 时跳过止损判断（无前一日数据，避免前视偏差）
                    if signal_close is not None and signal_close > 0 and signal_close <= stop_price:
                        sell_type = 'trailing_stop' if current_stop > stop_loss else 'stop_loss'
                        logger.info(f"  {stock_code} {stock_name} - 触发{'移动' if current_stop > stop_loss else ''}止损: 信号价(前收) {signal_close:.2f} <= 止损价 {stop_price:.2f}")
                
                # 2. 持仓过期检查（持有超过指定天数且收益率低于阈值）
                if not sell_type and enable_position_expire:
                    if hold_days > position_expire_hold_days and return_rate <= position_expire_return_threshold:
                        sell_type = 'position_expire'
                        logger.info(f"  {stock_code} {stock_name} - 持仓过期: 持有{hold_days}天, 收益率{return_rate:.2f}%<={position_expire_return_threshold}%")
                
                # 3. 如果未触发止盈止损和持仓过期，调用择时策略获取信号
                if not sell_type and self.timing_strategy:
                    df = self.stock_filtered_cache.get(stock_code)
                    if df is not None:
                        date_str = current_date.strftime('%Y-%m-%d')
                        df_to_date = df[df['date'] <= date_str].copy()
                        if not df_to_date.empty:
                            # 确保数据为倒序（最新在前），供择时策略使用
                            # 仅当数据为升序时才反转
                            if len(df_to_date) > 1 and df_to_date['date'].iloc[0] < df_to_date['date'].iloc[-1]:
                                df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)
                            # 传入 stock_code 以隔离技术指标缓存，避免不同股票间指标复用
                            result = self.timing_strategy.get_timing_result(df_to_date, position, 0, stock_code=stock_code)
                            
                            if result.is_sell:
                                if result.trade_type == 'reduce':
                                    # 策略要求减仓
                                    reduce_quantity = result.sell_quantity if result.sell_quantity > 0 else position['quantity'] // 2
                                    if reduce_quantity >= position['quantity']:
                                        # 减仓数量>=持仓，执行清仓
                                        sell_type = 'strategy_sell'
                                        logger.info(f"  策略信号: 清仓 - {result.message}")
                                    else:
                                        sell_type = 'strategy_reduce'
                                        logger.info(f"  策略信号: 减仓{reduce_quantity}股 - {result.message}")
                                else:
                                    # 策略要求清仓
                                    sell_type = 'strategy_sell'
                                    sell_quantity = position['quantity']
                                    logger.info(f"  策略信号: 清仓 - {result.message}")
                
                # 4. 【可选】三日（滚动）未创新高 且 收盘跌破 N 日线 → 卖出
                #    "未创新高" = max(最近 N 日最高价) < max(买入以来最高价)
                #    【2026-09-15 暂时屏蔽】总开关 ENABLE_NO_NEW_HIGH_EXIT=False 时不参与判定；
                #    改回 True 即恢复（普通回测仍需 config 开启；自适应默认值跟随总开关）
                if (not sell_type and not reduce_quantity
                        and self.ENABLE_NO_NEW_HIGH_EXIT
                        and config.get('enable_no_new_high_exit', False)):
                    _w = int(config.get('no_new_high_window', 3))
                    _mp = int(config.get('no_new_high_ma', 5))
                    _no_new_high, _below_ma, _detail = self._check_no_new_high_exit(
                        stock_code, prev_trading_day, _w, _mp, buy_date)
                    if _no_new_high and _below_ma:
                        sell_type = 'no_new_high'
                        logger.info(f"  {stock_code} {stock_name} - "
                                    f"近{_w}日未创新高（未超买入以来最高价）且收盘跌破"
                                    f"{_mp}日线，卖出: {_detail}")

                if not sell_type and not reduce_quantity:
                    logger.info(f"  {stock_code} {stock_name} - 无卖出信号，继续持有")
            else:
                logger.info(f"  {stock_code} {stock_name} - T+1限制，今日不能卖出")
            
            # 执行卖出操作
            if sell_type:
                # 执行清仓（成交价用T+1开盘价）
                sell_amount = sell_price * sell_quantity
                profit_loss = sell_amount - position['buy_amount'] * (sell_quantity / position['quantity'])
                
                sell_record = self._create_sell_record(position, current_date, sell_price,
                                                       sell_quantity, sell_amount, return_rate, hold_days, sell_type)
                sell_records.append(sell_record)
                logger.info(f"  【卖出】{stock_code}: 类型={sell_type}, 价格={sell_price}, "
                           f"数量={sell_quantity}, 金额={sell_amount:.2f}, 收益率={return_rate:.2f}%")
                
            elif reduce_quantity > 0:
                # 执行减仓（成交价用T+1开盘价）
                reduce_amount = sell_price * reduce_quantity
                remaining_quantity = position['quantity'] - reduce_quantity
                remaining_ratio = remaining_quantity / position['quantity']
                
                reduce_record = self._create_sell_record(position, current_date, sell_price,
                                                          reduce_quantity, reduce_amount, return_rate, hold_days, 'strategy_reduce')
                sell_records.append(reduce_record)
                
                # 更新持仓（保留剩余部分）
                position['quantity'] = remaining_quantity
                position['buy_amount'] = position['buy_amount'] * remaining_ratio
                position['buy_price'] = position['buy_amount'] / remaining_quantity if remaining_quantity > 0 else 0
                position['buy_commission'] = position.get('buy_commission', 0) * remaining_ratio
                position['buy_transfer_fee'] = position.get('buy_transfer_fee', 0) * remaining_ratio
                
                remaining_positions.append(position)
                reduce_cost = reduce_record['sell_commission'] + reduce_record['sell_transfer_fee'] + reduce_record['sell_stamp_tax']
                logger.info(f"  【减仓】{stock_code}: 减仓数量={reduce_quantity}, 剩余数量={remaining_quantity}, 净减仓金额={reduce_record['sell_amount']:.2f}(扣成本:{reduce_cost:.2f})")
            else:
                # 继续持有
                remaining_positions.append(position)
        
        # ========== 卖出后更新冷却池和连续亏损计数 ==========
        for sell_record in sell_records:
            stock_code = sell_record['stock_code']
            return_rate = sell_record['return_rate']
            
            # 更新连续亏损计数
            if enable_consecutive_loss_limit:
                if return_rate > 0:
                    # 盈利，重置计数
                    self.consecutive_loss_count[stock_code] = 0
                    logger.info(f"  股票 {stock_code} 盈利，连续亏损计数重置为0")
                else:
                    # 亏损，增加计数
                    current_count = self.consecutive_loss_count.get(stock_code, 0) + 1
                    self.consecutive_loss_count[stock_code] = current_count
                    logger.info(f"  股票 {stock_code} 亏损，连续亏损计数: {current_count}")
                    
                    # 检查是否达到连续亏损限制
                    if current_count >= max_consecutive_losses:
                        # 添加到冷却池
                        if enable_loss_cool_down or enable_consecutive_loss_limit:
                            cool_down_end = self._get_future_trading_day(current_date, consecutive_loss_cool_down)
                            self.loss_cool_down_pool[stock_code] = cool_down_end
                            logger.warning(f"  股票 {stock_code} 连续亏损 {current_count} 次，加入冷却池至 {cool_down_end}")
            
            # 检查是否触发冷却期（2026-09-16 新规则：**任意清仓卖出**即冷却 1 个月，盈利同样冷却）
            # 与实盘一致：使用【独立 if】。原为 elif，因上方 enable_consecutive_loss_limit
            # 默认为 True，该分支永远不会执行，导致回测单笔亏损冷却完全失效。
            # 判定统一走 should_register_sell_cool_down（回测/实盘共用，防口径漂移）；
            # 且**不覆盖更长的冷却**——否则会用 21 天覆盖上面刚设置的 250 天连续亏损冷却
            # （与实盘 _check_cool_down 守卫一致）。
            _sell_trade_type = sell_record.get('trade_type', 'sell')
            if enable_loss_cool_down and should_register_sell_cool_down(
                    _sell_trade_type, return_rate, cool_down_threshold,
                    config.get('cool_down_on_any_sell', True)):
                if not self._check_cool_down(stock_code, current_date):
                    cool_down_end = self._get_future_trading_day(current_date, cool_down_days)
                    self.loss_cool_down_pool[stock_code] = cool_down_end
                    logger.warning(
                        f"  股票 {stock_code} "
                        f"{'清仓' if _sell_trade_type == 'sell' else '减仓'}卖出"
                        f"（收益 {return_rate:.2f}%），"
                        f"加入冷却池 {cool_down_days} 个交易日至 {cool_down_end}")
        
        return remaining_positions, sell_records
    
    def _check_cool_down(self, stock_code: str, current_date: date) -> bool:
        """检查股票是否在冷却期内
        
        Args:
            stock_code: 股票代码
            current_date: 当前日期
            
        Returns:
            True表示在冷却期内，False表示不在冷却期
        """
        if stock_code not in self.loss_cool_down_pool:
            return False
        
        cool_down_end = self.loss_cool_down_pool[stock_code]
        if isinstance(cool_down_end, str):
            # 如果是字符串格式的日期，转换为date对象
            try:
                cool_down_end = datetime.strptime(cool_down_end, '%Y-%m-%d').date()
            except ValueError:
                # 解析失败，移除该条目
                del self.loss_cool_down_pool[stock_code]
                return False
        
        if current_date <= cool_down_end:
            return True
        else:
            # 冷却期结束，移除
            del self.loss_cool_down_pool[stock_code]
            return False
    
    def _get_future_trading_day(self, start_date: date, days: int) -> date:
        """获取指定交易日之后的第N个交易日
        
        Args:
            start_date: 起始日期
            days: 往后多少个交易日
            
        Returns:
            目标交易日
        """
        # 获取排序后的交易日列表
        if not self._sorted_trading_dates:
            return start_date + timedelta(days=days * 2)  # 粗略估计
        
        start_str = start_date.strftime('%Y-%m-%d')
        if start_str in self._sorted_trading_dates:
            start_idx = self._sorted_trading_dates.index(start_str)
        else:
            # 找到最近的交易日索引
            for i, td in enumerate(self._sorted_trading_dates):
                if td >= start_str:
                    start_idx = i
                    break
            else:
                return start_date + timedelta(days=days * 2)
        
        # 获取第N个交易日
        target_idx = start_idx + days
        if target_idx < len(self._sorted_trading_dates):
            return datetime.strptime(self._sorted_trading_dates[target_idx], '%Y-%m-%d').date()
        else:
            # 超出范围，使用粗略估计
            return start_date + timedelta(days=days * 2)
    
    def _create_sell_record(self, position: Dict, sell_date: date, sell_price: float,
                            quantity: int, sell_amount: float, return_rate: float, hold_days: int, 
                            sell_type: str) -> Dict:
        """创建卖出记录
        
        Args:
            position: 持仓信息
            sell_date: 卖出日期
            sell_price: 卖出价格
            quantity: 卖出数量
            sell_amount: 卖出金额
            return_rate: 收益率（已含成本预估）
            hold_days: 持有天数
            sell_type: 卖出类型
            
        Returns:
            卖出记录字典
        """
        # 计算卖出成本
        cost_info = calculate_backtest_cost(position['stock_code'], sell_price, quantity, is_buy=False)
        
        # 持仓分摊比例（用于分摊成本）
        ratio = quantity / position['quantity']
        
        # 分摊的买入成本
        allocated_buy_amount = position['buy_amount'] * ratio
        allocated_buy_commission = position.get('buy_commission', 0) * ratio if position.get('buy_commission') else 0
        allocated_buy_transfer_fee = position.get('buy_transfer_fee', 0) * ratio if position.get('buy_transfer_fee') else 0
        total_allocated_cost = allocated_buy_amount + allocated_buy_commission + allocated_buy_transfer_fee
        
        # 卖出成本
        sell_commission = cost_info['commission']
        sell_transfer_fee = cost_info['transfer_fee']
        sell_stamp_tax = cost_info['stamp_tax']
        total_sell_cost = sell_commission + sell_transfer_fee + sell_stamp_tax
        
        # 净卖出金额
        net_sell_amount = sell_amount - total_sell_cost
        
        # 计算含成本的 profit_loss 和 return_rate
        profit_loss = net_sell_amount - total_allocated_cost
        actual_return_rate = (net_sell_amount - total_allocated_cost) / total_allocated_cost * 100 if total_allocated_cost > 0 else 0
        
        return {
            'stock_code': position['stock_code'],
            'stock_name': position['stock_name'],
            'selection_date': None,
            'buy_date': position['buy_date'],
            'buy_price': position['buy_price'],
            'buy_amount': allocated_buy_amount,
            'quantity': quantity,
            'sell_date': sell_date,
            'sell_price': sell_price,
            'sell_amount': net_sell_amount,
            'sell_type': sell_type,
            'return_rate': actual_return_rate,
            'profit_loss': profit_loss,
            'hold_days': hold_days,
            'detail_url': self._generate_stock_detail_url(position['stock_code']),
            'trade_type': 'sell' if quantity >= position['quantity'] else 'reduce',
            # 交易成本字段
            'buy_commission': allocated_buy_commission,
            'buy_transfer_fee': allocated_buy_transfer_fee,
            'sell_commission': sell_commission,
            'sell_transfer_fee': sell_transfer_fee,
            'sell_stamp_tax': sell_stamp_tax
        }
    
    def _calculate_performance(self, trades: List[Dict], initial_capital: float, 
                              final_capital: float, dates: List[date], 
                              capital_history: List[float]) -> Dict:
        """计算绩效指标
        
        统计所有 sell_date is not None 的交易（包括已卖出和持仓虚拟交易）
        
        Args:
            trades: 交易记录
            initial_capital: 初始资金
            final_capital: 最终资金
            dates: 回测日期
            capital_history: 资金历史
            
        Returns:
            绩效指标字典
        """
        # 过滤出有卖出日期的交易（包括实际卖出和持仓虚拟卖出）
        completed_trades = [t for t in trades if t.get('sell_date') is not None]
        
        if not completed_trades:
            # 即使没有完成交易，也要计算总收益率
            total_return = ((final_capital / initial_capital) - 1) * 100
            total_return = round(total_return, 2)
            return {
                'total_trades': 0,
                'win_trades': 0,
                'loss_trades': 0,
                'win_rate': 0.0,
                'avg_return': 0.0,
                'total_return': total_return,
                'profit_factor': 0.0,
                'max_return': 0.0,
                'min_return': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'volatility': 0.0,
                'sortino_ratio': 0.0,
                'avg_hold_days': 0.0,
                'winning_trades': 0,
                'losing_trades': 0
            }
        
        # 计算基本指标
        # 【2026-09-22 口径修正】空值安全 ✓
        #   `t.get('return_rate', 0)` 在"**键存在但值为 None**"时返回 None ✗（默认值只在缺键时生效 ✗）
        #   → `None > 0` 直接抛 TypeError ✗，整张回测报表会算不出来 ✗（冒烟测试已复现 ✓）
        def _ret(t):
            v = t.get('return_rate')
            return float(v) if v is not None else 0.0

        total_trades = len(completed_trades)
        win_trades = sum(1 for t in completed_trades if _ret(t) > 0)
        loss_trades = sum(1 for t in completed_trades if _ret(t) < 0)
        win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0
        
        # 【2026-09-22 口径修正】单笔收益率序列：**只取有效数值** ✓
        #   原实现 `t['return_rate']` 直接取值 ✗ —— 已完成交易若缺该键会抛 KeyError ✗，
        #   若为 None 则污染 mean ✗（avg_return / max_return / min_return 同源 ✓）
        #   口径：已完成交易（含期末虚拟平仓）的**单笔收益率算术平均**，单位 % ✓
        returns = [float(t['return_rate']) for t in completed_trades
                   if t.get('return_rate') is not None]
        avg_return = float(np.mean(returns)) if returns else 0.0
        total_return = ((final_capital / initial_capital) - 1) * 100
        total_return = round(total_return, 2)
        
        # 计算最大和最小单笔收益
        max_return = max(returns) if returns else 0
        min_return = min(returns) if returns else 0
        
        # 【2026-09-22 口径修正】计算盈利因子 → 改为**金额口径** ✓
        #   行业标准定义：盈利因子 = 总盈利金额 / 总亏损金额（Gross Profit / Gross Loss）✓
        #   原实现用**单笔收益率(%)** 求和 ✗ → 每笔等权、完全无视仓位大小 ✗
        #   （实测样本 #185：旧值 1.77 ✗ vs 金额口径 2.45 ✓，偏差 38% ✗）
        #   同时修掉"无亏损时把分母兜底为 1" ✗ → 旧实现会算出"总盈利百分比"这种
        #   无意义数值（如 250.3）✗；现：无亏损但有盈利 → 取上限哨兵 99.99 ✓，无盈利 → 0 ✓
        amounts = [float(t.get('profit_loss') or 0) for t in completed_trades]
        gross_profit = sum(a for a in amounts if a > 0)
        gross_loss = abs(sum(a for a in amounts if a < 0))
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = PROFIT_FACTOR_NO_LOSS_CAP if gross_profit > 0 else 0.0
        
        # 计算盈亏比（基于金额）
        # 【2026-09-22】同为空值问题：`t.get('profit_loss', 0)` 遇到值为 None 会抛 TypeError ✗
        #   （金额取值的兜底一并做掉 ✓；注意下方 `else 1` 的分母兜底属另一处口径问题 ✗，
        #     本次**未改**以免在未回填的情况下静默改动"盈亏比"数值 ✗，已在报告中列出 ✓）
        winning_profits = [float(t.get('profit_loss') or 0) for t in completed_trades
                           if (t.get('profit_loss') or 0) > 0]
        losing_losses = [abs(float(t.get('profit_loss') or 0)) for t in completed_trades
                         if (t.get('profit_loss') or 0) < 0]
        avg_win = sum(winning_profits) / len(winning_profits) if winning_profits else 0
        avg_loss = sum(losing_losses) / len(losing_losses) if losing_losses else 1
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        
        # 计算最大回撤
        capital_array = np.array(capital_history)
        running_max = np.maximum.accumulate(capital_array)
        drawdown = (capital_array - running_max) / running_max * 100
        max_drawdown = abs(np.min(drawdown))
        
        # 计算夏普比率和波动率（假设无风险利率为2%）
        daily_returns = []
        for i in range(1, len(capital_history)):
            daily_return = (capital_history[i] - capital_history[i-1]) / capital_history[i-1]  # 使用小数形式
            daily_returns.append(daily_return)
        # 使用样本标准差（ddof=1），更符合金融行业惯例
        volatility = np.std(daily_returns, ddof=1) if len(daily_returns) > 1 else 0
        risk_free_rate = 0.02 / 252  # 日无风险利率（小数形式，年化2%）
        excess_returns = [r - risk_free_rate for r in daily_returns]
        sharpe_ratio = np.mean(excess_returns) / volatility * np.sqrt(252) if volatility > 0 else 0
        
        # 计算索提诺比率（只考虑下行风险）
        downside_returns = [r for r in daily_returns if r < 0]
        downside_volatility = np.std(downside_returns, ddof=1) if len(downside_returns) > 1 else 0
        sortino_ratio = np.mean(excess_returns) / downside_volatility * np.sqrt(252) if downside_volatility > 0 else 0.0
        
        # 【2026-09-22 口径修正】计算平均持有天数 ✓
        #   口径：已平仓交易的**平均持有交易日**数（买入当日记 0 天 ✓，与 positions 展示同口径 ✓）
        #   原实现 `if 'hold_days' in t` ✗ —— 键存在但值为 None 时仍会进均值 ✗ → 均值变 nan ✗，
        #   落库后前端显示 nan/异常 ✗（与 avg_return 同类问题 ✓）
        hold_days_list = [float(t['hold_days']) for t in completed_trades
                          if t.get('hold_days') is not None]
        avg_hold_days = float(np.mean(hold_days_list)) if hold_days_list else 0.0
        
        return {
            'total_trades': total_trades,
            'win_trades': win_trades,
            'loss_trades': loss_trades,
            'win_rate': win_rate,
            'avg_return': avg_return,
            'total_return': total_return,
            'max_return': max_return,
            'min_return': min_return,
            'profit_factor': profit_factor,
            'profit_loss_ratio': round(profit_loss_ratio, 2),
            'max_drawdown': float(max_drawdown),
            'sharpe_ratio': float(sharpe_ratio),
            'volatility': float(volatility * 100),  # 转换为百分比
            'sortino_ratio': float(sortino_ratio),
            'avg_hold_days': float(avg_hold_days),
            'winning_trades': win_trades,
            'losing_trades': loss_trades
        }
