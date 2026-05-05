#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
买点判断模块

该模块负责判断股票是否符合买点条件，基于支撑位、价格、趋势、成交量和评分等因素。
"""

import logging
import numpy as np
import pandas as pd
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Union

# 获取日志记录器
logger = logging.getLogger(__name__)


class BaseBuySignalJudger(ABC):
    """买点判断基类"""
    
    @abstractmethod
    def judge(self, stock_data: pd.DataFrame, support_level: float, **kwargs) -> Tuple[bool, str]:
        """
        判断是否符合买点条件
        
        Args:
            stock_data: 股票K线数据
            support_level: 支撑位价格
            **kwargs: 额外参数
            
        Returns:
            (是否符合买点, 买点信号原因)
        """
        pass


class PriceRangeBuySignalJudger(BaseBuySignalJudger):
    """价格区间买点判断"""
    
    def judge(self, stock_data: pd.DataFrame, support_level: float, **kwargs) -> Tuple[bool, str]:
        """
        基于价格区间判断买点
        
        Args:
            stock_data: 股票K线数据
            support_level: 支撑位价格
            **kwargs:
                lower_percent: 价格区间下限百分比，默认-1.0（支撑位下方1%）
                upper_percent: 价格区间上限百分比，默认3.0（支撑位上方3%）
                current_price: 当前价格，如果提供则使用，否则使用stock_data的最新收盘价
                
        Returns:
            (是否符合买点, 买点信号原因)
        """
        try:
            lower_percent = kwargs.get('lower_percent', -1.0)
            upper_percent = kwargs.get('upper_percent', 3.0)
            
            # 获取当前价格
            current_price = kwargs.get('current_price')
            if current_price is None:
                # 使用最新收盘价
                current_price = stock_data['close'].iloc[-1]
            
            # 计算价格区间
            lower_bound = support_level * (1 + lower_percent / 100)
            upper_bound = support_level * (1 + upper_percent / 100)
            
            # 判断价格是否在区间内
            if lower_bound <= current_price <= upper_bound:
                reason = f"价格在支撑位附近区间内 ({lower_bound:.2f} - {upper_bound:.2f})"
                logger.debug(f"价格区间买点判断: 符合，{reason}")
                return True, reason
            else:
                reason = f"价格不在支撑位附近区间内 ({lower_bound:.2f} - {upper_bound:.2f})"
                logger.debug(f"价格区间买点判断: 不符合，{reason}")
                return False, reason
                
        except Exception as e:
            logger.error(f"价格区间买点判断失败: {str(e)}")
            return False, f"判断失败: {str(e)}"


class TrendBuySignalJudger(BaseBuySignalJudger):
    """趋势买点判断"""
    
    def judge(self, stock_data: pd.DataFrame, support_level: float, **kwargs) -> Tuple[bool, str]:
        """
        基于趋势判断买点
        
        Args:
            stock_data: 股票K线数据
            support_level: 支撑位价格
            **kwargs:
                ma_period: 移动平均线周期，默认20
                
        Returns:
            (是否符合买点, 买点信号原因)
        """
        try:
            ma_period = kwargs.get('ma_period', 20)
            
            # 计算移动平均线
            stock_data['ma'] = stock_data['close'].rolling(window=ma_period).mean()
            
            # 判断趋势
            if len(stock_data) >= ma_period:
                # 最近5天的移动平均线趋势
                ma_trend = stock_data['ma'].tail(5).iloc[-1] - stock_data['ma'].tail(5).iloc[0]
                
                # 最近5天的收盘价趋势
                price_trend = stock_data['close'].tail(5).iloc[-1] - stock_data['close'].tail(5).iloc[0]
                
                # 趋势向上
                if ma_trend > 0 and price_trend > 0:
                    reason = "股价呈现上升趋势"
                    logger.debug(f"趋势买点判断: 符合，{reason}")
                    return True, reason
                else:
                    reason = "股价未呈现上升趋势"
                    logger.debug(f"趋势买点判断: 不符合，{reason}")
                    return False, reason
            else:
                reason = "数据不足，无法判断趋势"
                logger.debug(f"趋势买点判断: 不符合，{reason}")
                return False, reason
                
        except Exception as e:
            logger.error(f"趋势买点判断失败: {str(e)}")
            return False, f"判断失败: {str(e)}"


class VolumeBuySignalJudger(BaseBuySignalJudger):
    """成交量买点判断"""
    
    def judge(self, stock_data: pd.DataFrame, support_level: float, **kwargs) -> Tuple[bool, str]:
        """
        基于成交量判断买点
        
        Args:
            stock_data: 股票K线数据
            support_level: 支撑位价格
            **kwargs:
                volume_period: 成交量周期，默认5
                volume_ratio: 成交量放大比例，默认1.5
                
        Returns:
            (是否符合买点, 买点信号原因)
        """
        try:
            volume_period = kwargs.get('volume_period', 5)
            volume_ratio = kwargs.get('volume_ratio', 1.5)
            
            # 计算平均成交量
            avg_volume = stock_data['volume'].tail(volume_period).mean()
            
            # 获取最新成交量
            latest_volume = stock_data['volume'].iloc[-1]
            
            # 判断成交量是否放大
            if latest_volume > avg_volume * volume_ratio:
                reason = f"成交量明显放大 (当前: {latest_volume}, 平均: {avg_volume:.2f})"
                logger.debug(f"成交量买点判断: 符合，{reason}")
                return True, reason
            else:
                reason = f"成交量未明显放大 (当前: {latest_volume}, 平均: {avg_volume:.2f})"
                logger.debug(f"成交量买点判断: 不符合，{reason}")
                return False, reason
                
        except Exception as e:
            logger.error(f"成交量买点判断失败: {str(e)}")
            return False, f"判断失败: {str(e)}"


class ScoreBuySignalJudger(BaseBuySignalJudger):
    """评分买点判断"""
    
    def judge(self, stock_data: pd.DataFrame, support_level: float, **kwargs) -> Tuple[bool, str]:
        """
        基于评分判断买点
        
        Args:
            stock_data: 股票K线数据
            support_level: 支撑位价格
            **kwargs:
                score: 综合评分
                score_threshold: 评分阈值，默认60
                
        Returns:
            (是否符合买点, 买点信号原因)
        """
        try:
            score = kwargs.get('score', 0)
            score_threshold = kwargs.get('score_threshold', 60)
            
            # 判断评分是否达到阈值
            if score >= score_threshold:
                reason = f"综合评分达到阈值 ({score:.2f} >= {score_threshold})
                logger.debug(f"评分买点判断: 符合，{reason}")
                return True, reason
            else:
                reason = f"综合评分未达到阈值 ({score:.2f} < {score_threshold})
                logger.debug(f"评分买点判断: 不符合，{reason}")
                return False, reason
                
        except Exception as e:
            logger.error(f"评分买点判断失败: {str(e)}")
            return False, f"判断失败: {str(e)}"


class CompositeBuySignalJudger:
    """复合买点判断器"""
    
    def __init__(self):
        """
        初始化复合买点判断器
        """
        self.judgers = {
            'price_range': PriceRangeBuySignalJudger(),
            'trend': TrendBuySignalJudger(),
            'volume': VolumeBuySignalJudger(),
            'score': ScoreBuySignalJudger()
        }
    
    def judge(self, stock_data: pd.DataFrame, support_level: float, **kwargs) -> Tuple[bool, str]:
        """
        综合判断是否符合买点条件
        
        Args:
            stock_data: 股票K线数据
            support_level: 支撑位价格
            **kwargs:
                required_conditions: 必填条件列表，默认['price_range']
                optional_conditions: 选填条件列表，默认['trend', 'volume', 'score']
                optional_min_count: 选填条件需要满足的最小数量，默认1
                current_price: 当前价格，如果提供则使用，否则使用stock_data的最新收盘价
                
        Returns:
            (是否符合买点, 买点信号原因)
        """
        try:
            required_conditions = kwargs.get('required_conditions', ['price_range'])
            optional_conditions = kwargs.get('optional_conditions', ['trend', 'volume', 'score'])
            optional_min_count = kwargs.get('optional_min_count', 1)
            
            # 检查必填条件
            required_reasons = []
            for condition in required_conditions:
                judger = self.judgers.get(condition)
                if judger:
                    is_match, reason = judger.judge(stock_data, support_level, **kwargs)
                    if not is_match:
                        return False, f"必填条件未满足: {reason}"
                    required_reasons.append(reason)
            
            # 检查选填条件
            optional_reasons = []
            for condition in optional_conditions:
                judger = self.judgers.get(condition)
                if judger:
                    is_match, reason = judger.judge(stock_data, support_level, **kwargs)
                    if is_match:
                        optional_reasons.append(reason)
            
            # 检查选填条件是否满足最小数量
            if len(optional_reasons) >= optional_min_count:
                # 构建完整的买点信号原因
                all_reasons = required_reasons + optional_reasons
                reason = '; '.join(all_reasons)
                logger.debug(f"复合买点判断: 符合，{reason}")
                return True, reason
            else:
                reason = f"选填条件未满足足够数量 (需要至少{optional_min_count}个，实际{len(optional_reasons)}个)"
                logger.debug(f"复合买点判断: 不符合，{reason}")
                return False, reason
                
        except Exception as e:
            logger.error(f"复合买点判断失败: {str(e)}")
            return False, f"判断失败: {str(e)}"


class StrategyBuySignalManager:
    """策略买点管理类"""
    
    # 策略默认买点判断配置
    DEFAULT_STRATEGY_BUY_CONFIGS = {
        'BottomTrendInflectionStrategy': {
            'required_conditions': ['price_range'],
            'optional_conditions': ['trend', 'volume'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -2.0, 'upper_percent': 2.0}
        },
        'TrendAccelerationInflectionStrategy': {
            'required_conditions': ['price_range', 'trend'],
            'optional_conditions': ['volume'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -1.0, 'upper_percent': 3.0}
        },
        'ResistanceBreakoutStrategy': {
            'required_conditions': ['price_range', 'volume'],
            'optional_conditions': ['trend'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -0.5, 'upper_percent': 5.0}
        },
        'VolumeShrinkagePullbackStrategy': {
            'required_conditions': ['price_range'],
            'optional_conditions': ['volume', 'trend'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -1.5, 'upper_percent': 2.5}
        },
        'WBottomStrategy': {
            'required_conditions': ['price_range'],
            'optional_conditions': ['trend', 'volume'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -2.0, 'upper_percent': 2.0}
        },
        'MTopStrategy': {
            'required_conditions': [],
            'optional_conditions': [],
            'optional_min_count': 0
        },
        'MultiGoldenCrossStrategy': {
            'required_conditions': ['price_range', 'trend'],
            'optional_conditions': ['volume', 'score'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -1.0, 'upper_percent': 3.0}
        },
        'MultiDeathCrossStrategy': {
            'required_conditions': [],
            'optional_conditions': [],
            'optional_min_count': 0
        },
        'BowlReboundStrategy': {
            'required_conditions': ['price_range'],
            'optional_conditions': ['trend', 'volume'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -2.0, 'upper_percent': 2.0}
        },
        'MorningStarStrategy': {
            'required_conditions': ['price_range'],
            'optional_conditions': ['trend', 'volume'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -1.5, 'upper_percent': 2.5}
        },
        'MultiPartyCannonStrategy': {
            'required_conditions': ['price_range', 'trend'],
            'optional_conditions': ['volume', 'score'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -1.0, 'upper_percent': 3.0}
        },
        'StrongWashWeakToStrongStrategy': {
            'required_conditions': ['price_range', 'trend'],
            'optional_conditions': ['volume'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -1.0, 'upper_percent': 3.0}
        },
        'LimitUpPullbackStrategy': {
            'required_conditions': ['price_range'],
            'optional_conditions': ['volume', 'trend'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -2.0, 'upper_percent': 2.0}
        },
        'LimitUpSidewaysStrategy': {
            'required_conditions': ['price_range'],
            'optional_conditions': ['volume', 'trend'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -1.0, 'upper_percent': 2.0}
        }
    }
    
    def __init__(self, custom_config: Optional[Dict] = None):
        """
        初始化策略买点管理器
        
        Args:
            custom_config: 自定义策略买点配置
        """
        self.config = self.DEFAULT_STRATEGY_BUY_CONFIGS.copy()
        if custom_config:
            self.config.update(custom_config)
        self.judger = CompositeBuySignalJudger()
    
    def get_buy_config(self, strategy_name: str) -> Dict:
        """
        获取策略的买点判断配置
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            买点判断配置
        """
        return self.config.get(strategy_name, {
            'required_conditions': ['price_range'],
            'optional_conditions': ['trend', 'volume'],
            'optional_min_count': 1,
            'price_range': {'lower_percent': -1.0, 'upper_percent': 3.0}
        })
    
    def judge_buy_signal(self, strategy_name: str, stock_data: pd.DataFrame, support_level: float, **kwargs) -> Tuple[bool, str]:
        """
        判断策略的买点信号
        
        Args:
            strategy_name: 策略名称
            stock_data: 股票K线数据
            support_level: 支撑位价格
            **kwargs: 额外参数，如score、current_price等
            
        Returns:
            (是否符合买点, 买点信号原因)
        """
        try:
            # 获取策略的买点判断配置
            config = self.get_buy_config(strategy_name)
            
            # 合并配置和额外参数
            judge_kwargs = config.copy()
            judge_kwargs.update(kwargs)
            
            # 执行买点判断
            is_buy_signal, reason = self.judger.judge(stock_data, support_level, **judge_kwargs)
            
            logger.debug(f"策略 {strategy_name} 买点判断完成: {is_buy_signal}, {reason}")
            return is_buy_signal, reason
            
        except Exception as e:
            logger.error(f"判断策略买点失败: {str(e)}")
            return False, f"判断失败: {str(e)}"


# 全局买点管理器实例
global_buy_signal_manager = StrategyBuySignalManager()


def get_buy_signal_manager() -> StrategyBuySignalManager:
    """
    获取全局买点管理器实例
    
    Returns:
        买点管理器实例
    """
    return global_buy_signal_manager
