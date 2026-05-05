#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
支撑位计算模块

该模块负责计算股票的支撑位，支持按策略配置不同的支撑位计算方法。
"""

import logging
import numpy as np
import pandas as pd
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Union

# 获取日志记录器
logger = logging.getLogger(__name__)


class BaseSupportLevelCalculator(ABC):
    """支撑位计算基类"""
    
    @abstractmethod
    def calculate(self, stock_data: pd.DataFrame, **kwargs) -> float:
        """
        计算支撑位
        
        Args:
            stock_data: 股票K线数据
            **kwargs: 额外参数
            
        Returns:
            支撑位价格
        """
        pass


class MASupportLevelCalculator(BaseSupportLevelCalculator):
    """移动平均线支撑位计算"""
    
    def calculate(self, stock_data: pd.DataFrame, **kwargs) -> float:
        """
        计算移动平均线支撑位
        
        Args:
            stock_data: 股票K线数据
            **kwargs:
                period: 移动平均线周期，默认20
                
        Returns:
            支撑位价格
        """
        try:
            period = kwargs.get('period', 20)
            
            # 计算移动平均线
            stock_data['ma'] = stock_data['close'].rolling(window=period).mean()
            
            # 使用最新的移动平均线值作为支撑位
            support_level = stock_data['ma'].iloc[-1]
            
            logger.debug(f"移动平均线支撑位计算完成: {support_level}")
            return support_level
            
        except Exception as e:
            logger.error(f"移动平均线支撑位计算失败: {str(e)}")
            return 0.0


class LowSupportLevelCalculator(BaseSupportLevelCalculator):
    """前低支撑位计算"""
    
    def calculate(self, stock_data: pd.DataFrame, **kwargs) -> float:
        """
        计算前低支撑位
        
        Args:
            stock_data: 股票K线数据
            **kwargs:
                lookback_period: 回溯周期，默认30
                
        Returns:
            支撑位价格
        """
        try:
            lookback_period = kwargs.get('lookback_period', 30)
            
            # 取最近一段时间的最低价
            recent_lows = stock_data['low'].tail(lookback_period)
            support_level = recent_lows.min()
            
            logger.debug(f"前低支撑位计算完成: {support_level}")
            return support_level
            
        except Exception as e:
            logger.error(f"前低支撑位计算失败: {str(e)}")
            return 0.0


class PercentageSupportLevelCalculator(BaseSupportLevelCalculator):
    """百分比支撑位计算"""
    
    def calculate(self, stock_data: pd.DataFrame, **kwargs) -> float:
        """
        计算百分比支撑位
        
        Args:
            stock_data: 股票K线数据
            **kwargs:
                percentage: 百分比，默认0.95（即收盘价的95%）
                
        Returns:
            支撑位价格
        """
        try:
            percentage = kwargs.get('percentage', 0.95)
            
            # 使用最新收盘价的一定百分比作为支撑位
            latest_close = stock_data['close'].iloc[-1]
            support_level = latest_close * percentage
            
            logger.debug(f"百分比支撑位计算完成: {support_level}")
            return support_level
            
        except Exception as e:
            logger.error(f"百分比支撑位计算失败: {str(e)}")
            return 0.0


class ResistanceSupportLevelCalculator(BaseSupportLevelCalculator):
    """阻力位转换支撑位计算"""
    
    def calculate(self, stock_data: pd.DataFrame, **kwargs) -> float:
        """
        计算阻力位转换支撑位
        
        Args:
            stock_data: 股票K线数据
            **kwargs:
                lookback_period: 回溯周期，默认60
                
        Returns:
            支撑位价格
        """
        try:
            lookback_period = kwargs.get('lookback_period', 60)
            
            # 取最近一段时间的最高价作为阻力位
            recent_highs = stock_data['high'].tail(lookback_period)
            resistance_level = recent_highs.max()
            
            # 阻力位转换为支撑位
            support_level = resistance_level
            
            logger.debug(f"阻力位转换支撑位计算完成: {support_level}")
            return support_level
            
        except Exception as e:
            logger.error(f"阻力位转换支撑位计算失败: {str(e)}")
            return 0.0


class SupportLevelCalculatorFactory:
    """支撑位计算工厂类"""
    
    # 支撑位计算方法映射
    CALCULATORS = {
        'ma': MASupportLevelCalculator,
        'low': LowSupportLevelCalculator,
        'percentage': PercentageSupportLevelCalculator,
        'resistance': ResistanceSupportLevelCalculator
    }
    
    @classmethod
    def get_calculator(cls, method: str) -> Optional[BaseSupportLevelCalculator]:
        """
        获取支撑位计算实例
        
        Args:
            method: 支撑位计算方法
            
        Returns:
            支撑位计算实例
        """
        try:
            calculator_class = cls.CALCULATORS.get(method.lower())
            if calculator_class:
                return calculator_class()
            else:
                logger.warning(f"不支持的支撑位计算方法: {method}")
                return None
        except Exception as e:
            logger.error(f"获取支撑位计算实例失败: {str(e)}")
            return None


class StrategySupportLevelManager:
    """策略支撑位管理类"""
    
    # 策略默认支撑位计算方法配置
    DEFAULT_STRATEGY_SUPPORT_METHODS = {
        'BottomTrendInflectionStrategy': {'method': 'low', 'params': {'lookback_period': 40}},
        'TrendAccelerationInflectionStrategy': {'method': 'ma', 'params': {'period': 10}},
        'ResistanceBreakoutStrategy': {'method': 'resistance', 'params': {'lookback_period': 60}},
        'VolumeShrinkagePullbackStrategy': {'method': 'ma', 'params': {'period': 20}},
        'WBottomStrategy': {'method': 'low', 'params': {'lookback_period': 50}},
        'MTopStrategy': {'method': 'ma', 'params': {'period': 30}},
        'MultiGoldenCrossStrategy': {'method': 'ma', 'params': {'period': 20}},
        'MultiDeathCrossStrategy': {'method': 'ma', 'params': {'period': 20}},
        'BowlReboundStrategy': {'method': 'low', 'params': {'lookback_period': 40}},
        'MorningStarStrategy': {'method': 'low', 'params': {'lookback_period': 30}},
        'MultiPartyCannonStrategy': {'method': 'ma', 'params': {'period': 15}},
        'StrongWashWeakToStrongStrategy': {'method': 'ma', 'params': {'period': 20}},
        'LimitUpPullbackStrategy': {'method': 'low', 'params': {'lookback_period': 30}},
        'LimitUpSidewaysStrategy': {'method': 'ma', 'params': {'period': 20}}
    }
    
    def __init__(self, custom_config: Optional[Dict] = None):
        """
        初始化策略支撑位管理器
        
        Args:
            custom_config: 自定义策略支撑位配置
        """
        self.config = self.DEFAULT_STRATEGY_SUPPORT_METHODS.copy()
        if custom_config:
            self.config.update(custom_config)
        
    def get_support_level_method(self, strategy_name: str) -> Dict:
        """
        获取策略的支撑位计算方法配置
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            支撑位计算方法配置
        """
        return self.config.get(strategy_name, {'method': 'ma', 'params': {'period': 20}})
    
    def calculate_support_level(self, strategy_name: str, stock_data: pd.DataFrame) -> float:
        """
        计算策略的支撑位
        
        Args:
            strategy_name: 策略名称
            stock_data: 股票K线数据
            
        Returns:
            支撑位价格
        """
        try:
            # 获取策略的支撑位计算方法配置
            config = self.get_support_level_method(strategy_name)
            method = config.get('method', 'ma')
            params = config.get('params', {})
            
            # 获取支撑位计算实例
            calculator = SupportLevelCalculatorFactory.get_calculator(method)
            if not calculator:
                logger.warning(f"无法获取支撑位计算实例，使用默认方法")
                calculator = MASupportLevelCalculator()
            
            # 计算支撑位
            support_level = calculator.calculate(stock_data, **params)
            
            logger.debug(f"策略 {strategy_name} 支撑位计算完成: {support_level}")
            return support_level
            
        except Exception as e:
            logger.error(f"计算策略支撑位失败: {str(e)}")
            return 0.0


# 全局支撑位管理器实例
global_support_level_manager = StrategySupportLevelManager()


def get_support_level_manager() -> StrategySupportLevelManager:
    """
    获取全局支撑位管理器实例
    
    Returns:
        支撑位管理器实例
    """
    return global_support_level_manager
