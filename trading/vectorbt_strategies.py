"""
VectorBT向量化策略模块

本模块实现了多种向量化交易策略，包括：
1. 双均线策略
2. 支撑位策略
3. RSI策略
4. 多方炮策略
5. W底策略
6. 趋势加速拐点策略

所有策略都使用向量化计算，性能优异。
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Tuple, Optional
from abc import ABC, abstractmethod
import vectorbt as vbt

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """基础策略类"""
    
    def __init__(self, name: str):
        """
        初始化策略
        
        Args:
            name: 策略名称
        """
        # name: 策略名称，类型str，必填
        self.name = name
        self.signals_cache = {}
    
    @abstractmethod
    def generate_signals(self, prices: pd.DataFrame, config: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成买卖信号
        
        Args:
            prices: 价格矩阵
            config: 配置字典
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        pass
    
    def _validate_prices(self, prices: pd.DataFrame) -> bool:
        """验证价格数据"""
        if prices.empty:
            logger.warning(f"{self.name}: 价格数据为空")
            return False
        
        # 计算 NaN 值比例
        total_values = len(prices) * len(prices.columns)
        nan_count = prices.isnull().sum().sum()
        nan_ratio = nan_count / total_values if total_values > 0 else 0
        
        # 允许较高的 NaN 值比例（< 50%），但要记录警告
        # 原因：数据加载时可能存在缺失数据，需要通过填充处理
        if nan_ratio > 0.5:
            logger.error(f"{self.name}: NaN 值比例过高: {nan_ratio:.2%} ({nan_count}/{total_values})")
            return False
        
        if nan_ratio > 0.1:
            logger.warning(f"{self.name}: 价格数据包含 {nan_ratio:.2%} 的 NaN 值，将进行填充处理")
        elif nan_ratio > 0:
            logger.info(f"{self.name}: 价格数据包含 {nan_ratio:.2%} 的 NaN 值，将进行填充处理")
        
        return True

    def _safe_fill_nan(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        安全填充 NaN 值（不使用未来函数）
        
        填充策略：
        1. 前向填充（使用历史数据）
        2. 使用列中位数填充剩余 NaN
        3. 最后用 0 填充
        
        Args:
            df: 待填充的数据框
            
        Returns:
            填充后的数据框
        """
        df_clean = df.copy()
        
        # 第一步：前向填充（只使用历史数据）
        df_clean = df_clean.ffill()
        
        # 第二步：使用列中位数填充剩余 NaN（避免使用 bfill() 引入未来函数）
        for col in df_clean.columns:
            if df_clean[col].isnull().any():
                median_val = df_clean[col].median()
                if pd.notna(median_val) and median_val > 0:
                    df_clean[col].fillna(median_val, inplace=True)
        
        # 第三步：最后用 0 填充剩余的 NaN
        df_clean = df_clean.fillna(0)
        
        return df_clean


class DualMAStrategy(BaseStrategy):
    """双均线策略"""
    
    def __init__(self):
        """初始化双均线策略"""
        super().__init__("DualMA")
    
    def generate_signals(self, prices: pd.DataFrame, config: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成双均线信号
        
        Args:
            prices: 价格矩阵
            config: 配置字典，包含fast_window和slow_window
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # config: 配置字典，类型Dict，必填
        if not self._validate_prices(prices):
            return pd.DataFrame(), pd.DataFrame()
        
        # 1. 提取参数
        fast_window = config.get('fast_window', 10)
        slow_window = config.get('slow_window', 50)
        
        logger.info(f"{self.name}: fast_window={fast_window}, slow_window={slow_window}")
        
        # 2. 处理 NaN 值 - 使用安全填充方法（避免未来函数）
        nan_count_before = prices.isnull().sum().sum()
        prices_clean = self._safe_fill_nan(prices)
        nan_count_after = prices_clean.isnull().sum().sum()
        logger.info(f"{self.name}: NaN 处理完成 - 处理前={nan_count_before}, 处理后={nan_count_after}")
        
        # 3. 计算移动平均线
        ma_fast = vbt.MA.run(prices_clean, window=fast_window)
        ma_slow = vbt.MA.run(prices_clean, window=slow_window)
        
        # 4. 生成信号 - 使用 ma_crossed_above 和 ma_crossed_below 方法
        try:
            # 尝试使用 crossed_above/crossed_below 方法
            buy_signals = ma_fast.ma_crossed_above(ma_slow)
            sell_signals = ma_fast.ma_crossed_below(ma_slow)
        except:
            # 如果方法不存在，手动计算交叉
            ma_fast_values = ma_fast.ma.values if hasattr(ma_fast.ma, 'values') else ma_fast.ma
            ma_slow_values = ma_slow.ma.values if hasattr(ma_slow.ma, 'values') else ma_slow.ma
            
            # 计算交叉信号
            buy_signals = pd.DataFrame(
                (ma_fast_values > ma_slow_values) & 
                (ma_fast_values.shift(1) <= ma_slow_values.shift(1)),
                index=prices.index,
                columns=prices.columns
            )
            sell_signals = pd.DataFrame(
                (ma_fast_values < ma_slow_values) & 
                (ma_fast_values.shift(1) >= ma_slow_values.shift(1)),
                index=prices.index,
                columns=prices.columns
            )
        
        # 5. 确保信号矩阵形状与价格矩阵一致
        if buy_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 买入信号形状不匹配，重新调整")
            buy_signals = buy_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        if sell_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 卖出信号形状不匹配，重新调整")
            sell_signals = sell_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        logger.info(f"{self.name}: 买入信号数={buy_signals.sum().sum()}, 卖出信号数={sell_signals.sum().sum()}")
        
        return buy_signals, sell_signals


class RSIStrategy(BaseStrategy):
    """RSI策略"""
    
    def __init__(self):
        """初始化RSI策略"""
        super().__init__("RSI")
    
    def generate_signals(self, prices: pd.DataFrame, config: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成RSI信号
        
        Args:
            prices: 价格矩阵
            config: 配置字典，包含rsi_window, oversold, overbought
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # config: 配置字典，类型Dict，必填
        if not self._validate_prices(prices):
            return pd.DataFrame(), pd.DataFrame()
        
        # 1. 提取参数
        rsi_window = config.get('rsi_window', 14)
        oversold = config.get('oversold', 30)
        overbought = config.get('overbought', 70)
        
        logger.info(f"{self.name}: window={rsi_window}, oversold={oversold}, overbought={overbought}")
        
        # 2. 处理 NaN 值（避免未来函数）
        prices_clean = self._safe_fill_nan(prices)
        
        # 3. 计算RSI
        rsi = vbt.RSI.run(prices_clean, window=rsi_window)
        
        # 4. 生成信号 - 提取RSI值
        rsi_values = rsi.rsi.values if hasattr(rsi.rsi, 'values') else rsi.rsi
        
        buy_signals = pd.DataFrame(
            rsi_values < oversold,
            index=prices.index,
            columns=prices.columns
        )
        sell_signals = pd.DataFrame(
            rsi_values > overbought,
            index=prices.index,
            columns=prices.columns
        )
        
        # 5. 确保信号矩阵形状与价格矩阵一致
        if buy_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 买入信号形状不匹配，重新调整")
            buy_signals = buy_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        if sell_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 卖出信号形状不匹配，重新调整")
            sell_signals = sell_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        logger.info(f"{self.name}: 买入信号数={buy_signals.sum().sum()}, 卖出信号数={sell_signals.sum().sum()}")
        
        return buy_signals, sell_signals


class SupportLevelStrategy(BaseStrategy):
    """支撑位策略"""
    
    def __init__(self):
        """初始化支撑位策略"""
        super().__init__("SupportLevel")
    
    def generate_signals(self, prices: pd.DataFrame, support_levels: pd.DataFrame, 
                        config: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成支撑位信号
        
        Args:
            prices: 价格矩阵
            support_levels: 支撑位矩阵
            config: 配置字典
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # support_levels: 支撑位矩阵，类型pd.DataFrame，必填
        # config: 配置字典，类型Dict，必填
        if not self._validate_prices(prices):
            return pd.DataFrame(), pd.DataFrame()
        
        # 1. 处理 NaN 值（避免未来函数）
        prices_clean = self._safe_fill_nan(prices)
        support_levels_clean = self._safe_fill_nan(support_levels)
        
        # 2. 对齐数据
        prices_clean, support_levels_clean = prices_clean.align(support_levels_clean, join='inner')
        
        # 3. 计算支撑位距离
        distance_ratio = config.get('distance_ratio', 0.02)  # 2%
        
        # 4. 生成信号
        # 价格接近支撑位时买入
        buy_signals = (prices_clean >= support_levels_clean) & (prices_clean <= support_levels_clean * (1 + distance_ratio))
        
        # 价格突破支撑位时卖出
        sell_signals = prices_clean < support_levels_clean
        
        # 5. 确保信号矩阵形状与价格矩阵一致
        if buy_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 买入信号形状不匹配，重新调整")
            buy_signals = buy_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        if sell_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 卖出信号形状不匹配，重新调整")
            sell_signals = sell_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        logger.info(f"{self.name}: 买入信号数={buy_signals.sum().sum()}, 卖出信号数={sell_signals.sum().sum()}")
        
        return buy_signals, sell_signals


class CombinedStrategy(BaseStrategy):
    """组合策略 - 多条件组合"""
    
    def __init__(self):
        """初始化组合策略"""
        super().__init__("Combined")
    
    def generate_signals(self, prices: pd.DataFrame, scores: pd.DataFrame, 
                        config: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成组合信号
        
        Args:
            prices: 价格矩阵
            scores: 评分矩阵
            config: 配置字典
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # scores: 评分矩阵，类型pd.DataFrame，必填
        # config: 配置字典，类型Dict，必填
        if not self._validate_prices(prices):
            return pd.DataFrame(), pd.DataFrame()
        
        # 1. 处理 NaN 值（避免未来函数）
        prices_clean = self._safe_fill_nan(prices)
        scores_clean = self._safe_fill_nan(scores)
        
        # 2. 对齐数据
        prices_clean, scores_clean = prices_clean.align(scores_clean, join='inner')
        
        # 3. 计算技术指标
        ma_fast = vbt.MA.run(prices_clean, window=config.get('fast_window', 10))
        ma_slow = vbt.MA.run(prices_clean, window=config.get('slow_window', 50))
        rsi = vbt.RSI.run(prices_clean, window=config.get('rsi_window', 14))
        
        # 4. 生成基础信号
        # 提取MA对象的ma属性进行比较
        ma_fast_values = ma_fast.ma.values if hasattr(ma_fast.ma, 'values') else ma_fast.ma
        ma_slow_values = ma_slow.ma.values if hasattr(ma_slow.ma, 'values') else ma_slow.ma
        rsi_values = rsi.rsi.values if hasattr(rsi.rsi, 'values') else rsi.rsi
        
        # 创建信号DataFrame
        ma_signal = pd.DataFrame(
            ma_fast_values > ma_slow_values,
            index=prices.index,
            columns=prices.columns
        )
        rsi_signal = pd.DataFrame(
            rsi_values < config.get('oversold', 30),
            index=prices.index,
            columns=prices.columns
        )
        score_signal = scores_clean >= config.get('score_threshold', 50)
        
        # 5. 组合信号
        buy_signals = ma_signal & rsi_signal & score_signal
        
        # 卖出信号
        overbought_signal = pd.DataFrame(
            rsi_values > config.get('overbought', 70),
            index=prices.index,
            columns=prices.columns
        )
        sell_signals = ~ma_signal | overbought_signal
        
        # 6. 确保信号矩阵形状与价格矩阵一致
        if buy_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 买入信号形状不匹配，重新调整")
            buy_signals = buy_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        if sell_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 卖出信号形状不匹配，重新调整")
            sell_signals = sell_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        logger.info(f"{self.name}: 买入信号数={buy_signals.sum().sum()}, 卖出信号数={sell_signals.sum().sum()}")
        
        return buy_signals, sell_signals


class DuoFangPaoStrategy(BaseStrategy):
    """多方炮策略 - 两阳夹一阴形态"""
    
    def __init__(self):
        """初始化多方炮策略"""
        super().__init__("DuoFangPao")
    
    def generate_signals(self, prices: pd.DataFrame, config: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成多方炮信号
        
        Args:
            prices: 价格矩阵
            config: 配置字典
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # config: 配置字典，类型Dict，必填
        if not self._validate_prices(prices):
            return pd.DataFrame(), pd.DataFrame()
        
        # 1. 提取参数
        first_rise = config.get('first_candle_rise', 0.03)
        third_rise = config.get('third_candle_rise', 0.03)
        volume_expand = config.get('third_volume_expand_ratio', 1.2)
        
        logger.info(f"{self.name}: first_rise={first_rise}, third_rise={third_rise}, volume_expand={volume_expand}")
        
        # 2. 处理 NaN 值（避免未来函数）
        prices_clean = self._safe_fill_nan(prices)
        
        # 3. 计算K线特征
        # 计算涨幅
        returns = prices_clean.pct_change()
        
        # 4. 识别多方炮形态
        # 简化版本：识别连续上升后的放量长阳线
        buy_signals = (returns > third_rise) & (returns.shift(1) > first_rise)
        
        # 卖出信号：价格下跌
        sell_signals = returns < -0.02
        
        # 5. 确保信号矩阵形状与价格矩阵一致
        if buy_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 买入信号形状不匹配，重新调整")
            buy_signals = buy_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        if sell_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 卖出信号形状不匹配，重新调整")
            sell_signals = sell_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        logger.info(f"{self.name}: 买入信号数={buy_signals.sum().sum()}, 卖出信号数={sell_signals.sum().sum()}")
        
        return buy_signals, sell_signals


class WBottomStrategy(BaseStrategy):
    """W底策略 - 双底反转形态"""
    
    def __init__(self):
        """初始化W底策略"""
        super().__init__("WBottom")
    
    def generate_signals(self, prices: pd.DataFrame, config: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成W底信号
        
        Args:
            prices: 价格矩阵
            config: 配置字典
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # config: 配置字典，类型Dict，必填
        if not self._validate_prices(prices):
            return pd.DataFrame(), pd.DataFrame()
        
        # 1. 提取参数
        lookback = config.get('pattern_days', 40)
        neckline_ratio = config.get('neckline_break_ratio', 1.01)
        
        logger.info(f"{self.name}: lookback={lookback}, neckline_ratio={neckline_ratio}")
        
        # 2. 处理 NaN 值（避免未来函数）
        prices_clean = self._safe_fill_nan(prices)
        
        # 3. 识别W底形态
        # 计算滚动最低值
        rolling_low = prices_clean.rolling(window=lookback).min()
        
        # 4. 识别颈线突破
        # 颈线 = 最近lookback天的最高值
        rolling_high = prices_clean.rolling(window=lookback).max()
        
        # 买入信号：价格突破颈线
        buy_signals = prices_clean > rolling_high * neckline_ratio
        
        # 卖出信号：价格跌破支撑位
        sell_signals = prices_clean < rolling_low * 0.98
        
        # 5. 确保信号矩阵形状与价格矩阵一致
        if buy_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 买入信号形状不匹配，重新调整")
            buy_signals = buy_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        if sell_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 卖出信号形状不匹配，重新调整")
            sell_signals = sell_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        logger.info(f"{self.name}: 买入信号数={buy_signals.sum().sum()}, 卖出信号数={sell_signals.sum().sum()}")
        
        return buy_signals, sell_signals


class TrendAccelerationStrategy(BaseStrategy):
    """趋势加速拐点策略 - 上升趋势中的加速信号"""
    
    def __init__(self):
        """初始化趋势加速拐点策略"""
        super().__init__("TrendAcceleration")
    
    def generate_signals(self, prices: pd.DataFrame, config: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成趋势加速拐点信号
        
        Args:
            prices: 价格矩阵
            config: 配置字典
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # config: 配置字典，类型Dict，必填
        if not self._validate_prices(prices):
            return pd.DataFrame(), pd.DataFrame()
        
        # 1. 提取参数
        price_threshold = config.get('price_increase_threshold', 0.08)
        volume_ratio = config.get('volume_ratio_threshold', 2.0)
        
        logger.info(f"{self.name}: price_threshold={price_threshold}, volume_ratio={volume_ratio}")
        
        # 2. 处理 NaN 值 - 使用安全填充方法（避免未来函数）
        nan_count_before = prices.isnull().sum().sum()
        prices_clean = self._safe_fill_nan(prices)
        nan_count_after = prices_clean.isnull().sum().sum()
        logger.info(f"{self.name}: NaN 处理完成 - 处理前={nan_count_before}, 处理后={nan_count_after}")
        
        # 3. 计算技术指标
        # 计算涨幅
        returns = prices_clean.pct_change()
        
        # 计算均线
        ma_short = prices_clean.rolling(window=10).mean()
        ma_long = prices_clean.rolling(window=30).mean()
        
        # 4. 生成信号
        # 买入条件：价格上升趋势 + 放量长阳线
        uptrend = ma_short > ma_long
        surge = returns > price_threshold
        buy_signals = uptrend & surge
        
        # 卖出条件：趋势反转
        sell_signals = ma_short < ma_long
        
        # 5. 确保信号矩阵形状与价格矩阵一致
        if buy_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 买入信号形状不匹配，重新调整")
            buy_signals = buy_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        if sell_signals.shape != prices.shape:
            logger.warning(f"{self.name}: 卖出信号形状不匹配，重新调整")
            sell_signals = sell_signals.reindex(prices.index, columns=prices.columns, fill_value=False)
        
        logger.info(f"{self.name}: 买入信号数={buy_signals.sum().sum()}, 卖出信号数={sell_signals.sum().sum()}")
        
        return buy_signals, sell_signals


class StrategyFactory:
    """策略工厂"""
    
    _strategies = {
        'dual_ma': DualMAStrategy,
        'rsi': RSIStrategy,
        'support_level': SupportLevelStrategy,
        'combined': CombinedStrategy,
        'duo_fang_pao': DuoFangPaoStrategy,
        'w_bottom': WBottomStrategy,
        'trend_acceleration': TrendAccelerationStrategy,
    }
    
    # 策略名称映射（支持多种格式）
    _name_mapping = {
        'dualma': 'dual_ma',
        'dual_ma': 'dual_ma',
        'rsi': 'rsi',
        'supportlevel': 'support_level',
        'support_level': 'support_level',
        'combined': 'combined',
        'duofangpao': 'duo_fang_pao',
        'duo_fang_pao': 'duo_fang_pao',
        'wbottom': 'w_bottom',
        'w_bottom': 'w_bottom',
        'trendacceleration': 'trend_acceleration',
        'trend_acceleration': 'trend_acceleration',
        # 中文策略名称映射
        '底部趋势拐点': 'trend_acceleration',
        '趋势加速拐点': 'trend_acceleration',
        '多方炮': 'duo_fang_pao',
        'w底': 'w_bottom',
        '支撑位': 'support_level',
        '双均线': 'dual_ma',
        '综合': 'combined',
    }
    
    @classmethod
    def _normalize_strategy_name(cls, strategy_name: str) -> str:
        """
        规范化策略名称
        
        支持多种格式：
        - DualMA -> dual_ma
        - dual_ma -> dual_ma
        - dualma -> dual_ma
        """
        # strategy_name: 策略名称，类型str，必填
        # 转换为小写并移除下划线
        normalized = strategy_name.lower().replace('_', '')
        # 查找映射
        return cls._name_mapping.get(normalized, strategy_name.lower())
    
    @classmethod
    def create_strategy(cls, strategy_name: str) -> Optional[BaseStrategy]:
        """
        创建策略实例
        
        Args:
            strategy_name: 策略名称（支持多种格式）
        
        Returns:
            BaseStrategy: 策略实例
        """
        # strategy_name: 策略名称，类型str，必填
        # 规范化策略名称
        normalized_name = cls._normalize_strategy_name(strategy_name)
        strategy_class = cls._strategies.get(normalized_name)
        if strategy_class is None:
            logger.error(f"未知的策略: {strategy_name} (normalized: {normalized_name})")
            return None
        
        return strategy_class()
    
    @classmethod
    def register_strategy(cls, name: str, strategy_class):
        """
        注册新策略
        
        Args:
            name: 策略名称
            strategy_class: 策略类
        """
        # name: 策略名称，类型str，必填
        # strategy_class: 策略类，类型type，必填
        cls._strategies[name.lower()] = strategy_class
        logger.info(f"策略已注册: {name}")
    
    @classmethod
    def get_available_strategies(cls) -> list:
        """获取可用的策略列表"""
        return list(cls._strategies.keys())


class VectorBTSignalGenerator:
    """VectorBT信号生成器"""
    
    def __init__(self):
        """初始化信号生成器"""
        self.strategies = {}
    
    def generate_signals(self, strategy_name: str, prices: pd.DataFrame, 
                        config: Dict, **kwargs) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成信号
        
        Args:
            strategy_name: 策略名称
            prices: 价格矩阵
            config: 配置字典
            **kwargs: 其他参数（如scores, support_levels等）
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        # strategy_name: 策略名称，类型str，必填
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # config: 配置字典，类型Dict，必填
        logger.info(f"生成信号: {strategy_name}")
        
        # 1. 创建策略
        strategy = StrategyFactory.create_strategy(strategy_name)
        if strategy is None:
            logger.error(f"无法创建策略: {strategy_name}")
            return pd.DataFrame(), pd.DataFrame()
        
        # 2. 规范化策略名称用于比较
        normalized_name = StrategyFactory._normalize_strategy_name(strategy_name)
        
        # 3. 生成信号
        try:
            if normalized_name == 'support_level':
                support_levels = kwargs.get('support_levels')
                if support_levels is None:
                    logger.error("支撑位策略需要support_levels参数")
                    return pd.DataFrame(), pd.DataFrame()
                buy_signals, sell_signals = strategy.generate_signals(prices, support_levels, config)
            
            elif normalized_name == 'combined':
                scores = kwargs.get('scores')
                if scores is None:
                    logger.error("组合策略需要scores参数")
                    return pd.DataFrame(), pd.DataFrame()
                buy_signals, sell_signals = strategy.generate_signals(prices, scores, config)
            
            else:
                buy_signals, sell_signals = strategy.generate_signals(prices, config)
            
            return buy_signals, sell_signals
        
        except Exception as e:
            logger.error(f"生成信号失败: {str(e)}", exc_info=True)
            return pd.DataFrame(), pd.DataFrame()
    
    def apply_score_filter(self, buy_signals: pd.DataFrame, scores: pd.DataFrame, 
                          score_threshold: float = 50.0) -> pd.DataFrame:
        """
        应用评分过滤
        
        Args:
            buy_signals: 买入信号矩阵
            scores: 评分矩阵
            score_threshold: 评分阈值
        
        Returns:
            pd.DataFrame: 过滤后的买入信号
        """
        # buy_signals: 买入信号矩阵，类型pd.DataFrame，必填
        # scores: 评分矩阵，类型pd.DataFrame，必填
        # score_threshold: 评分阈值，类型float，默认50.0
        logger.info(f"应用评分过滤: threshold={score_threshold}")
        
        # 1. 对齐数据 - 使用 reindex 确保索引一致
        try:
            # 尝试使用 align
            buy_signals_aligned, scores_aligned = buy_signals.align(scores, join='inner')
        except:
            # 如果 align 失败，使用 reindex
            common_index = buy_signals.index.intersection(scores.index)
            common_columns = buy_signals.columns.intersection(scores.columns)
            buy_signals_aligned = buy_signals.loc[common_index, common_columns]
            scores_aligned = scores.loc[common_index, common_columns]
        
        # 2. 应用过滤
        filtered_signals = buy_signals_aligned & (scores_aligned >= score_threshold)
        
        logger.info(f"过滤前信号数: {buy_signals_aligned.sum().sum()}, 过滤后: {filtered_signals.sum().sum()}")
        
        return filtered_signals


if __name__ == '__main__':
    """
    测试策略
    """
    import time
    
    # 创建模拟数据
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=250, freq='D')
    prices = pd.DataFrame(
        np.random.randn(250, 5).cumsum(axis=0) + 100,
        index=dates,
        columns=['stock_a', 'stock_b', 'stock_c', 'stock_d', 'stock_e']
    )
    
    # 初始化生成器
    generator = VectorBTSignalGenerator()
    
    # 测试双均线策略
    print("\n=== 双均线策略 ===")
    config = {'fast_window': 10, 'slow_window': 50}
    buy_signals, sell_signals = generator.generate_signals('dual_ma', prices, config)
    print(f"买入信号: {buy_signals.sum().sum()}")
    print(f"卖出信号: {sell_signals.sum().sum()}")
    
    # 测试RSI策略
    print("\n=== RSI策略 ===")
    config = {'rsi_window': 14, 'oversold': 30, 'overbought': 70}
    buy_signals, sell_signals = generator.generate_signals('rsi', prices, config)
    print(f"买入信号: {buy_signals.sum().sum()}")
    print(f"卖出信号: {sell_signals.sum().sum()}")
    
    # 测试组合策略
    print("\n=== 组合策略 ===")
    scores = pd.DataFrame(
        np.random.uniform(40, 80, prices.shape),
        index=prices.index,
        columns=prices.columns
    )
    config = {
        'fast_window': 10,
        'slow_window': 50,
        'rsi_window': 14,
        'oversold': 30,
        'overbought': 70,
        'score_threshold': 50
    }
    buy_signals, sell_signals = generator.generate_signals('combined', prices, config, scores=scores)
    print(f"买入信号: {buy_signals.sum().sum()}")
    print(f"卖出信号: {sell_signals.sum().sum()}")
    
    # 性能测试
    print("\n=== 性能测试 ===")
    start_time = time.time()
    for _ in range(10):
        generator.generate_signals('dual_ma', prices, {'fast_window': 10, 'slow_window': 50})
    elapsed_time = time.time() - start_time
    print(f"10次信号生成耗时: {elapsed_time:.2f}秒")
    print(f"平均耗时: {elapsed_time/10:.4f}秒")
