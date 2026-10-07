"""
择时策略基类和工厂
"""
from abc import ABC, abstractmethod
import pandas as pd
import logging
from typing import Dict, Optional, Any
from utils.feature_config_checker import FeatureConfigChecker

logger = logging.getLogger(__name__)


class TimingResult:
    """择时结果"""
    def __init__(self):
        self.is_buy = False        # 是否为买点
        self.is_sell = False       # 是否为卖点
        self.buy_quantity = 0      # 买入数量
        self.sell_quantity = 0     # 卖出数量（包括减仓）
        self.signal_strength = 0.0 # 信号强度（0-1）
        self.support_level = 0.0   # 支撑位
        self.resistance_level = 0.0 # 压力位
        self.indicators = {}       # 指标值
        self.message = ""          # 信号说明
        self.trade_type = ""       # 交易类型：buy, add, sell, reduce
        # 加仓后的【累计总次数】（1-based）：首次加仓=1，第2次=2，...，上限由各策略自定
        # 语义必须与 position['add_count'] 一致（回测引擎与实盘运行器均据此跟踪加仓进度），
        # 非加仓信号保持 0。策略产生 trade_type='add' 时必须设置该值。
        self.add_count = 0


class TimingStrategy(ABC):
    """择时策略基类"""
    
    def __init__(self, config):
        """初始化策略
        
        Args:
            config: 策略配置
        """
        self.config = config or {}
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算指标
        
        Args:
            df: 股票数据
            
        Returns:
            添加了指标的DataFrame
        """
        return df
    
    def is_buy_point(self, df: pd.DataFrame, position: Optional[Dict] = None, cash: Optional[float] = None, stock_code: str = "") -> bool:
        """判断是否为买点
        
        Args:
            df: 股票数据
            position: 持仓信息
            cash: 可用资金
            stock_code: 股票代码（用于指标缓存隔离）
            
        Returns:
            是否为买点
        """
        result = self.get_timing_result(df, position, cash, stock_code=stock_code)
        return result.is_buy
    
    def is_sell_point(self, df: pd.DataFrame, position: Dict, stock_code: str = "") -> bool:
        """判断是否为卖点
        
        Args:
            df: 股票数据
            position: 持仓信息
            stock_code: 股票代码（用于指标缓存隔离）
            
        Returns:
            是否为卖点
        """
        result = self.get_timing_result(df, position, stock_code=stock_code)
        return result.is_sell
    
    def calculate_support(self, df: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """计算支撑位
        
        Args:
            df: 股票数据
            key_date: 关键日期
            
        Returns:
            支撑位价格
        """
        return 0.0
    
    @abstractmethod
    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None, cash: Optional[float] = None, use_prev_day_signal: bool = True, stock_code: str = "") -> TimingResult:
        """获取择时结果
        
        Args:
            df: 股票数据
            position: 持仓信息
            cash: 可用资金
            use_prev_day_signal: 是否使用前一天信号（回测模式），默认True
                - True: 使用倒数第二根K线判断前一天是否突破
                - False: 使用最新K线判断当天是否突破（狩猎场模式）
            stock_code: 股票代码（用于指标缓存隔离）
            
        Returns:
            择时结果
        """
        pass


class TimingStrategyFactory:
    """择时策略工厂"""
    
    @staticmethod
    def create_strategy(strategy_name: str, config: Dict) -> TimingStrategy:
        """创建择时策略
        
        Args:
            strategy_name: 策略名称
            config: 策略配置
            
        Returns:
            择时策略实例
        """
        logger.info(f"开始创建择时策略: {strategy_name}")
        
        # 顺势宝策略需要检查功能配置
        if strategy_name == "macd_bollinger":
            logger.info("检测到顺势宝策略，开始检查功能配置")
            checker = FeatureConfigChecker()
            try:
                valid_files, expire_date = checker.check_config()
                logger.info(f"配置检查结果: 有效文件={valid_files}, 过期日期={expire_date}")
                # 没有有效配置文件时必须阻止创建策略
                if not valid_files:
                    logger.error("顺势宝策略创建失败：未找到有效的功能配置文件")
                    raise ValueError("顺势宝策略创建失败：未找到有效的功能配置文件")
                logger.info("顺势宝策略配置检查通过")
            except ValueError:
                raise  # 直接重新抛出 ValueError
            except Exception as e:
                logger.error(f"顺势宝策略：检查功能配置失败: {e}")
        
        if strategy_name == "turtle":
            logger.info("创建海龟策略实例")
            from trading.turtle_strategy import TurtleStrategy
            return TurtleStrategy(config)
        elif strategy_name == "low_turtle":
            logger.info("创建低位海龟策略实例（去除MA20过滤）")
            from trading.low_turtle_strategy import LowTurtleStrategy
            return LowTurtleStrategy(config)
        elif strategy_name == "turtle_plus":
            logger.info("创建海龟plus策略实例（只做第二买点）")
            from trading.turtle_plus_strategy import TurtlePlusStrategy
            return TurtlePlusStrategy(config)
        elif strategy_name == "rsi":
            logger.info("创建RSI策略实例")
            from trading.rsi_strategy import RSIStrategy
            return RSIStrategy(config)
        elif strategy_name == "bollinger":
            logger.info("创建布林带策略实例")
            from trading.bollinger_strategy import BollingerStrategy
            return BollingerStrategy(config)
        elif strategy_name == "support":
            logger.info("创建支撑位策略实例")
            from trading.support_strategy import SupportStrategy
            return SupportStrategy(config)
        elif strategy_name == "uptrend_pullback":
            logger.info("创建趋势回调缩量策略实例")
            from trading.uptrend_pullback_strategy import UptrendPullbackStrategy
            return UptrendPullbackStrategy(config)
        elif strategy_name == "macd_bollinger":
            logger.info("创建顺势宝策略实例")
            from trading.macd_bollinger_strategy import ShunShiBaoStrategy
            return ShunShiBaoStrategy(config)
        else:
            logger.error(f"未知的择时策略: {strategy_name}")
            raise ValueError(f"Unknown timing strategy: {strategy_name}")


# ==================== 海龟类策略参数合并（回测/自适应/实盘统一口径）====================
# 背景（2026-09-16）：海龟类策略参数来自① timing_params[策略名]（参数面板/策略配置）
# 与② 顶层 config 的海龟参数（routes._load_turtle_params 等注入）。
# 原先 backtest_engine / regime_backtest_engine / strategy_runner 各写一份"海龟类策略名单"，
# 新增「海龟plus」时三处全部漏改 → 回测与实盘都回退到代码内默认预设（short = 10/5/10），
# 与 config/strategy_params.yaml（12/6/12 + 前溯/加仓参数）不一致，回测结果无法代表配置口径。
# 现收敛为唯一实现：名单与合并键只有一份，新增海龟类策略只改这里。
TURTLE_FAMILY_STRATEGIES = ('turtle', 'low_turtle', 'turtle_plus')

# 顶层 config → 策略参数的合并键（仅合并非 None，避免覆盖已有配置）
TURTLE_FAMILY_PARAM_KEYS = (
    'n_entry', 'n_exit', 'atr_period', 'entry_atr', 'add_atr', 'exit_atr',
    'base_position_amount',
    # 海龟plus 专属（turtle/low_turtle 会忽略未知键）
    'lookback_days', 'max_additions', 'add_profit_min',
    'require_add_atr', 'require_no_sell_between', 'require_higher_high',
)


def build_turtle_family_params(config: Dict, timing_params: Dict,
                               timing_strategy: str) -> Dict:
    """构建海龟类择时策略参数（回测/自适应回测/实盘共用同一实现）

    优先级（由高到低）：顶层 config 海龟参数 > timing_params[策略名] > 策略内默认预设。

    Args:
        config: 顶层配置（可能直接包含 n_entry / lookback_days 等海龟参数）
        timing_params: config 中的 timing_params 字典
        timing_strategy: 择时策略名（如 'turtle' / 'low_turtle' / 'turtle_plus' / 'support'）

    Returns:
        合并后的策略参数字典（非海龟类策略原样返回 timing_params[策略名]）
    """
    params = dict((timing_params or {}).get(timing_strategy, {}) or {})
    if timing_strategy not in TURTLE_FAMILY_STRATEGIES:
        return params
    cfg = config or {}
    specific = {k: cfg.get(k) for k in TURTLE_FAMILY_PARAM_KEYS}
    # 预设特例：顶层沿用 turtle_preset 传参（timing_params 内仍叫 preset）
    if cfg.get('turtle_preset') is not None:
        specific['preset'] = cfg.get('turtle_preset')
    params.update({k: v for k, v in specific.items() if v is not None})
    return params


# ==================== 海龟类配置的唯一读取入口（2026-09-23 合并）====================
# 背景：海龟 / 海龟plus 的参数原先散落在**多处** ——
#   ① yaml 里两个块（TurtleStrategy / TurtlePlusStrategy）；
#   ② 各入口各自维护 `_blocks` 映射（routes / web_server / 流水线 / 批量回测）。
#   已多次漂移并造成严重后果：同一策略、同一区间，批量回测用**代码默认**（10/5/10），
#   而单次回测用另一套配置 → 收益差出一倍以上 ✗，回测结果无法指导实盘 ✗。
# 现在：yaml **只保留一个** 海龟类配置块 ✓，所有入口统一调用本函数读取 ✓，
#   新增海龟类策略或改参数只需动这一处 ✓。
TURTLE_CONFIG_BLOCK = 'TurtleStrategy'

# 代码内兜底默认（yaml 缺失/读取失败时使用）＝ 短线海龟 10/5/10 ✓
# ★【2026-10-01 用户要求 ✓】"**改回 10/5/10**" ✓（12/6/12 试过一版 ⇒ 已回退 ✓）
#   ⚠️ 必须与 `config/strategy_params.yaml` 的 `TurtleStrategy.params` ✓ 与
#     `turtle_strategy.SHORT_TURTLE_PRESET` ✓ **三层保持一致** ✗✓
#     —— 项目历史上正是"三层不一致"✗ 导致批量回测与单次回测收益差一倍 ✗✓（见上方背景 ✓）。
TURTLE_DEFAULT_PARAMS = {
    'n_entry': 10, 'n_exit': 5, 'atr_period': 10,
    'entry_atr': 0.02, 'add_atr': 0.5, 'exit_atr': 2.0,
    'base_position_amount': 20000, 'preset': 'short',
    # 海龟plus 专属（turtle/low_turtle 会忽略未知键）
    'lookback_days': 5, 'max_additions': 4, 'add_profit_min': 0.02,
    'require_add_atr': True, 'require_no_sell_between': True,
}

# 低位海龟保持自身口径（低位股常低于 MA20，故 n_entry 极小且关闭 MA20 过滤）
LOW_TURTLE_DEFAULT_PARAMS = {
    'n_entry': 1, 'n_exit': 6, 'atr_period': 12,
    'entry_atr': 0.02, 'add_atr': 0.5, 'exit_atr': 2.0,
    'base_position_amount': 20000,
}


def load_turtle_family_params(timing_strategy: str, config_manager=None) -> Dict:
    """读取海龟类策略参数（**唯一入口** ✓）

    与 `build_turtle_family_params` 的分工：
      · 本函数 = "**从配置取默认值**"（yaml → dict，各入口共用一份 ✓）
      · `build_turtle_family_params` = "**与调用方传入值合并**"（顶层 config 优先 ✓）

    取值规则：
      · turtle / turtle_plus → yaml 的 `TurtleStrategy.params`（**同一份** ✓）
      · low_turtle           → 自身固定口径（1/6/12、无 MA20 过滤 ✓），不参与共享块 ✓
      · 非海龟类             → 返回 {}（调用方忽略注入 ✓）
      · 读取失败 / 块缺失    → 退回 TURTLE_DEFAULT_PARAMS（**10/5/10** ✓），并告警 ✓

    Args:
        timing_strategy: 择时策略名（turtle / low_turtle / turtle_plus / 其它）
        config_manager: 可选，复用外部 StrategyConfigManager 实例

    Returns:
        dict: 策略参数键值
    """
    if timing_strategy not in TURTLE_FAMILY_STRATEGIES:
        return {}
    if timing_strategy == 'low_turtle':
        return dict(LOW_TURTLE_DEFAULT_PARAMS)
    try:
        if config_manager is None:
            from utils.strategy_config_manager import StrategyConfigManager
            config_manager = StrategyConfigManager()
        block = config_manager.get_strategy_config(TURTLE_CONFIG_BLOCK) or {}
        params = dict(block.get('params') or {})
        if params:
            logger.info(f"从配置文件读取海龟类参数（{TURTLE_CONFIG_BLOCK}，供 {timing_strategy} 使用）: "
                        f"n_entry={params.get('n_entry')}, n_exit={params.get('n_exit')}, "
                        f"atr_period={params.get('atr_period')}, preset={params.get('preset')}")
            return params
        logger.warning(f"配置块 {TURTLE_CONFIG_BLOCK}.params 为空，使用代码默认（10/5/10）")
    except Exception as e:
        logger.warning(f"读取海龟类配置失败，使用代码默认（10/5/10）: {e}")
    return dict(TURTLE_DEFAULT_PARAMS)
