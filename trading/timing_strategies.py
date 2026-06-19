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
        self.add_count = 0         # 加仓次数（用于海龟等加仓策略）


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
    
    def is_buy_point(self, df: pd.DataFrame, position: Optional[Dict] = None, cash: Optional[float] = None) -> bool:
        """判断是否为买点
        
        Args:
            df: 股票数据
            position: 持仓信息
            cash: 可用资金
            
        Returns:
            是否为买点
        """
        result = self.get_timing_result(df, position, cash)
        return result.is_buy
    
    def is_sell_point(self, df: pd.DataFrame, position: Dict) -> bool:
        """判断是否为卖点
        
        Args:
            df: 股票数据
            position: 持仓信息
            
        Returns:
            是否为卖点
        """
        result = self.get_timing_result(df, position)
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
    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None, cash: Optional[float] = None, use_prev_day_signal: bool = True) -> TimingResult:
        """获取择时结果
        
        Args:
            df: 股票数据
            position: 持仓信息
            cash: 可用资金
            use_prev_day_signal: 是否使用前一天信号（回测模式），默认True
                - True: 使用倒数第二根K线判断前一天是否突破
                - False: 使用最新K线判断当天是否突破（狩猎场模式）
            
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
        elif strategy_name == "macd_bollinger":
            logger.info("创建顺势宝策略实例")
            from trading.macd_bollinger_strategy import ShunShiBaoStrategy
            return ShunShiBaoStrategy(config)
        else:
            logger.error(f"未知的择时策略: {strategy_name}")
            raise ValueError(f"Unknown timing strategy: {strategy_name}")
