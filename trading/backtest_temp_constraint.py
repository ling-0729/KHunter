# -*- coding: utf-8 -*-
"""
回测温度约束处理器

根据市场温度限制回测时的买入数量和仓位系数
"""

import logging
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


class BacktestTempConstraint:
    """回测温度约束处理器"""
    
    # 买入数量限制规则
    BUY_COUNT_RULES = [
        (80, float('inf'), "活跃", "不限"),
        (65, 5, "正常", "最多5只"),
        (50, 3, "偏冷", "最多3只"),
        (30, 1, "寒冷", "最多1只"),
        (15, 1, "冰封", "0-1只"),
        (0, 0, "极端", "禁止买入")
    ]
    
    # 仓位限制规则
    POSITION_RULES = [
        (80, 1.0, "活跃", "可满仓"),
        (65, 0.8, "正常", "适度控制"),
        (50, 0.5, "偏冷", "半仓以下"),
        (30, 0.25, "寒冷", "轻仓"),
        (15, 0.1, "冰封", "极轻仓"),
        (0, 0.0, "极端", "禁止操作")
    ]
    
    def __init__(self, dao=None):
        """
        初始化回测温度约束处理器
        
        Args:
            dao: MarketTemperatureDAO实例，如果为None则创建
        """
        self.dao = dao
        if dao is None:
            from trading.market_temperature_dao import MarketTemperatureDAO
            self.dao = MarketTemperatureDAO()
    
    def get_constraint(self, temperature: float, mode: str = 'both') -> Dict:
        """
        根据温度获取约束配置
        
        Args:
            temperature: 市场温度值（0-100）
            mode: 约束模式，'count'/'position'/'both'
        
        Returns:
            约束配置字典
        """
        # 获取数量限制
        max_count = self._get_max_buy_count(temperature)
        count_status, count_desc = self._get_buy_count_status(temperature)
        
        # 获取仓位限制
        max_position = self._get_max_position(temperature)
        pos_status, pos_desc = self._get_position_status(temperature)
        
        # 根据模式返回结果
        result = {
            'temperature': temperature,
            'count_constraint': {
                'max_buy_count': float('inf') if max_count == float('inf') else max_count,
                'status': count_status,
                'description': count_desc,
                'enabled': mode in ['count', 'both']
            },
            'position_constraint': {
                'max_position_ratio': max_position,
                'status': pos_status,
                'description': pos_desc,
                'enabled': mode in ['position', 'both']
            }
        }
        
        return result
    
    def apply_constraints(
        self, 
        trade_date: str, 
        candidates: List[Dict], 
        position_ratio: float,
        enable_temp_limit: bool = True,
        temp_limit_mode: str = 'both'
    ) -> Dict:
        """
        应用温度约束到候选股票
        
        Args:
            trade_date: 交易日期（YYYYMMDD格式）
            candidates: 候选股票列表（按评分排序）
            position_ratio: 原始计划仓位（0-1）
            enable_temp_limit: 是否启用温度限制
            temp_limit_mode: 约束模式，'count'/'position'/'both'
        
        Returns:
            约束后的结果字典，包含：
            - candidates: 约束后的候选股票列表
            - position_ratio: 约束后的仓位
            - max_buy_count: 最大买入数量
            - temperature: 市场温度
            - status: 市场状态
            - constrained: 是否被约束
            - reason: 约束原因
        """
        # 如果未启用温度限制，直接返回
        if not enable_temp_limit:
            return {
                'candidates': candidates,
                'position_ratio': position_ratio,
                'max_buy_count': len(candidates) if candidates else 0,
                'temperature': None,
                'status': None,
                'constrained': False,
                'reason': None
            }
        
        # 获取当日温度数据
        temp_data = self.dao.query_by_date(trade_date)
        if not temp_data:
            logger.warning(f"未找到温度数据: {trade_date}")
            return {
                'candidates': candidates,
                'position_ratio': position_ratio,
                'max_buy_count': len(candidates) if candidates else 0,
                'temperature': None,
                'status': None,
                'constrained': False,
                'reason': '无温度数据'
            }
        
        temperature = temp_data['temperature']
        status = temp_data['status']
        
        # 获取约束配置
        constraint = self.get_constraint(temperature, temp_limit_mode)
        
        # 应用数量限制
        if temp_limit_mode in ['count', 'both']:
            max_count = constraint['count_constraint']['max_buy_count']
            if max_count != float('inf'):
                constrained_candidates = candidates[:int(max_count)] if candidates else []
            else:
                constrained_candidates = candidates
        else:
            max_count = len(candidates) if candidates else 0
            constrained_candidates = candidates
        
        # 应用仓位限制
        if temp_limit_mode in ['position', 'both']:
            max_position = constraint['position_constraint']['max_position_ratio']
            effective_position = min(position_ratio, max_position)
        else:
            max_position = 1.0
            effective_position = position_ratio
        
        # 判断是否被约束
        constrained = (
            (temp_limit_mode in ['count', 'both'] and len(candidates) > max_count) or
            (temp_limit_mode in ['position', 'both'] and position_ratio > max_position)
        )
        
        return {
            'candidates': constrained_candidates,
            'position_ratio': effective_position,
            'max_buy_count': int(max_count) if max_count != float('inf') else None,
            'temperature': temperature,
            'status': status,
            'constrained': constrained,
            'reason': f"温度{temperature}° - {status}" if constrained else None,
            'constraint_details': constraint
        }
    
    def get_batch_constraints(
        self, 
        trade_dates: List[str], 
        mode: str = 'both'
    ) -> Dict:
        """
        批量获取温度约束
        
        Args:
            trade_dates: 交易日期列表
            mode: 约束模式
        
        Returns:
            批量约束结果，包含每日的约束详情和汇总统计
        """
        constraints = []
        temp_data_map = {}
        
        # 批量获取温度数据
        if trade_dates:
            from trading.market_temperature_dao import MarketTemperatureDAO
            dao = MarketTemperatureDAO()
            
            if len(trade_dates) == 1:
                data = dao.query_by_date(trade_dates[0])
                if data:
                    temp_data_map[trade_dates[0]] = data
            else:
                min_date = min(trade_dates)
                max_date = max(trade_dates)
                range_data = dao.query_range(min_date, max_date)
                for item in range_data:
                    temp_data_map[item['trade_date']] = item
        
        # 计算每日的约束
        days_constrained = 0
        days_banned = 0
        total_max_count = 0
        total_max_position = 0
        valid_days = 0
        
        for trade_date in trade_dates:
            temp_data = temp_data_map.get(trade_date)
            
            if temp_data:
                temperature = temp_data['temperature']
                status = temp_data['status']
                
                constraint = self.get_constraint(temperature, mode)
                
                max_count = constraint['count_constraint']['max_buy_count']
                max_position = constraint['position_constraint']['max_position_ratio']
                
                # 统计
                if max_count < float('inf'):
                    total_max_count += max_count
                valid_days += 1
                total_max_position += max_position
                
                if max_count == 0:
                    days_banned += 1
                elif max_count != float('inf'):
                    days_constrained += 1
                
                constraints.append({
                    'trade_date': trade_date,
                    'temperature': temperature,
                    'status': status,
                    'max_buy_count': int(max_count) if max_count != float('inf') else None,
                    'max_position_ratio': max_position
                })
            else:
                constraints.append({
                    'trade_date': trade_date,
                    'temperature': None,
                    'status': '未知',
                    'max_buy_count': None,
                    'max_position_ratio': 1.0
                })
        
        return {
            'constraints': constraints,
            'summary': {
                'total_days': len(trade_dates),
                'days_with_data': valid_days,
                'days_constrained': days_constrained,
                'days_banned': days_banned,
                'avg_max_count': round(total_max_count / valid_days, 1) if valid_days > 0 else None,
                'avg_max_position': round(total_max_position / valid_days, 2) if valid_days > 0 else 1.0
            }
        }
    
    def _get_max_buy_count(self, temperature: float) -> float:
        """根据温度获取最大买入数量"""
        for threshold, max_count, _, _ in self.BUY_COUNT_RULES:
            if temperature >= threshold:
                return max_count
        return 0
    
    def _get_max_position(self, temperature: float) -> float:
        """根据温度获取最大仓位系数"""
        for threshold, max_position, _, _ in self.POSITION_RULES:
            if temperature >= threshold:
                return max_position
        return 0.0
    
    def _get_buy_count_status(self, temperature: float) -> Tuple[str, str]:
        """获取买入数量限制状态"""
        for threshold, _, status, description in self.BUY_COUNT_RULES:
            if temperature >= threshold:
                return status, description
        return "极端", "禁止买入"
    
    def _get_position_status(self, temperature: float) -> Tuple[str, str]:
        """获取仓位限制状态"""
        for threshold, _, status, description in self.POSITION_RULES:
            if temperature >= threshold:
                return status, description
        return "极端", "禁止操作"
