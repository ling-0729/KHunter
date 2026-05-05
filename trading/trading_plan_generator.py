#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易计划生成器模块
负责根据狩猎场筛选结果生成交易计划
"""

import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TradingPlanGenerator:
    """
    交易计划生成器
    根据狩猎场筛选结果生成交易计划
    """

    DEFAULT_POSITION_RATIO = 5
    STOP_LOSS_PERCENT = 0.05
    TAKE_PROFIT_PERCENT = 0.20

    def __init__(self, db_manager, khunter_dao, trading_plan_dao):
        self.db_manager = db_manager
        self.khunter_dao = khunter_dao
        self.trading_plan_dao = trading_plan_dao

    def generate(self, plan_date_input: str) -> Dict[str, Any]:
        """
        生成交易计划

        参数：
            plan_date_input: 用户输入的日期（可能是交易日或非交易日），格式 YYYY-MM-DD

        返回：
            Dict: 包含 plan_date, hunting_date, total_count, plans, temperature_info
        """
        # 获取实际狩猎日期（如果当天有K线则用当天，否则用前一天）
        hunting_date = self._get_hunting_date(plan_date_input)
        
        # 获取下一个交易日作为计划执行日期
        plan_date = self._get_next_trading_date(hunting_date)
        
        # 获取温度信息（使用狩猎日期，因为温度数据与K线日期对应）
        temperature_info = self._get_market_temperature(hunting_date)
        
        # 获取狩猎结果（使用实际狩猎日期）
        hunting_results = self._get_hunting_results(hunting_date)
        
        # 获取温度约束建议（仅供参考，不限制数据）
        temp_constraints = self._get_temp_constraints(temperature_info)
        # 转换为对象格式以匹配前端期望
        temp_constraints_dict = {
            'max_stocks': temp_constraints[0],
            'position_ratio': temp_constraints[1]
        }
        
        # 生成交易计划（不改变数据，只添加建议信息）
        plans = []
        for stock_data in hunting_results:
            plan = self._generate_plan_for_stock(stock_data, plan_date, hunting_date)
            plans.append(plan)
        
        return {
            'plan_date': plan_date,
            'hunting_date': hunting_date,
            'total_count': len(plans),
            'plans': plans,
            'temperature_info': temperature_info,
            'temp_constraints': temp_constraints_dict  # 温度约束建议（仅供参考）
        }

    def _get_market_temperature(self, hunting_date: str) -> Dict[str, Any]:
        """
        获取市场温度信息

        参数：
            hunting_date: 狩猎日期

        返回：
            Dict: 温度信息字典
        """
        try:
            # 转换日期格式为 YYYYMMDD
            trade_date = hunting_date.replace('-', '')
            
            # 导入市场温度计算器
            from utils.market_temperature import MarketTemperature
            calculator = MarketTemperature()
            
            # 计算温度
            temp_data = calculator.calculate(trade_date, use_cache=True)
            
            return {
                'temperature': temp_data.get('temperature'),
                'status': temp_data.get('status'),
                'position_ratio': temp_data.get('position_ratio'),
                'action': temp_data.get('action'),
                'suggestion': self._generate_temperature_suggestion(temp_data)
            }
        except Exception as e:
            logger.warning(f"获取市场温度失败: {e}")
            return {
                'temperature': None,
                'status': '未知',
                'position_ratio': 1.0,
                'action': '正常执行',
                'suggestion': '市场温度数据获取失败，请手动判断'
            }

    def _generate_temperature_suggestion(self, temp_data: Dict) -> str:
        """
        生成温度建议文本（只包含仓位建议）

        参数：
            temp_data: 温度数据

        返回：
            str: 建议文本
        """
        temp = temp_data.get('temperature')
        position_ratio = temp_data.get('position_ratio', 1.0)
        
        if temp is None:
            return '市场温度数据获取失败，建议谨慎操作'
        
        # 只生成仓位建议
        position_pct = int(position_ratio * 100)
        if temp >= 80:
            return f'当前市场活跃({temp}°)，建议仓位{position_pct}%'
        elif temp >= 65:
            return f'当前市场正常({temp}°)，建议仓位{position_pct}%'
        elif temp >= 50:
            return f'当前市场偏冷({temp}°)，建议仓位{position_pct}%'
        elif temp >= 30:
            return f'当前市场寒冷({temp}°)，建议仓位{position_pct}%'
        elif temp >= 15:
            return f'当前市场冰封({temp}°)，建议仓位{position_pct}%'
        else:
            return f'当前市场极端({temp}°)，建议暂停买入'
            suggestions.append('耐心等待市场回暖')
        
        return '；'.join(suggestions)

    def _get_temp_constraints(self, temperature_info: Dict) -> tuple:
        """
        根据温度信息获取交易约束

        参数：
            temperature_info: 温度信息

        返回：
            tuple: (最大股票数量, 调整后的仓位系数)
        """
        temp = temperature_info.get('temperature')
        if temp is None:
            return (999, 1.0)  # 无限制
        
        if temp >= 80:
            return (5, 1.0)
        elif temp >= 65:
            return (3, 0.8)
        elif temp >= 50:
            return (2, 0.5)
        elif temp >= 30:
            return (1, 0.25)
        elif temp >= 15:
            return (1, 0.1)
        else:
            return (0, 0.0)  # 禁止买入

    def _get_hunting_date(self, plan_date: str) -> str:
        """
        获取实际狩猎日期
        如果选择的日期有K线数据则用当天，否则用前一天

        参数：
            plan_date: 用户选择的日期

        返回：
            str: 实际狩猎日期，格式 YYYY-MM-DD
        """
        # 检查当天是否有K线数据
        if self._has_kline_data(plan_date):
            return plan_date
        
        # 没有K线数据，使用前一天
        plan_dt = datetime.strptime(plan_date, '%Y-%m-%d')
        prev_dt = plan_dt - timedelta(days=1)
        return f"{prev_dt.year}-{prev_dt.month:02d}-{prev_dt.day:02d}"
    
    def _has_kline_data(self, date_str: str) -> bool:
        """
        检查指定日期是否有K线数据

        参数：
            date_str: 日期字符串

        返回：
            bool: 是否有K线数据
        """
        try:
            sql = "SELECT COUNT(*) as count FROM stock_kline WHERE date = ?"
            result = self.db_manager.query_one(sql, (date_str,))
            return result and result.get('count', 0) > 0
        except Exception as e:
            logger.warning(f"检查K线数据失败: {e}")
            return False

    def _get_next_trading_date(self, hunting_date: str) -> str:
        """
        获取狩猎日的下一个交易日

        参数：
            hunting_date: 狩猎日期，格式 YYYY-MM-DD

        返回：
            str: 下一个交易日，格式 YYYY-MM-DD
        """
        try:
            # 往前找一天，查询是否有下一个交易日的K线数据
            hunting_dt = datetime.strptime(hunting_date, '%Y-%m-%d')
            
            # 逐日向后查找，最多查找30天
            for i in range(1, 31):
                next_dt = hunting_dt + timedelta(days=i)
                next_date_str = f"{next_dt.year}-{next_dt.month:02d}-{next_dt.day:02d}"
                
                # 检查是否有K线数据
                if self._has_kline_data(next_date_str):
                    logger.debug(f"狩猎日 {hunting_date} 的下一个交易日: {next_date_str}")
                    return next_date_str
            
            # 如果没找到，使用后一天（周末等）
            next_dt = hunting_dt + timedelta(days=1)
            fallback_date = f"{next_dt.year}-{next_dt.month:02d}-{next_dt.day:02d}"
            logger.warning(f"未找到下一个交易日，使用后一天: {fallback_date}")
            return fallback_date
            
        except Exception as e:
            logger.error(f"获取下一个交易日失败: {e}")
            # fallback：直接返回后一天
            hunting_dt = datetime.strptime(hunting_date, '%Y-%m-%d')
            next_dt = hunting_dt + timedelta(days=1)
            return f"{next_dt.year}-{next_dt.month:02d}-{next_dt.day:02d}"

    def _get_hunting_results(self, hunting_date: str) -> List[Dict[str, Any]]:
        """
        获取狩猎场筛选结果

        参数：
            hunting_date: 狩猎日期

        返回：
            List[Dict]: 狩猎结果列表
        """
        result = self.khunter_dao.query_by_date(hunting_date)
        results = result.get('results', [])
        
        # 添加排名信息
        for idx, item in enumerate(results, 1):
            item['rank'] = idx
        
        return results

    def _generate_plan_for_stock(
        self,
        stock_data: Dict[str, Any],
        plan_date: str,
        hunting_date: str
    ) -> Dict[str, Any]:
        """
        为单只股票生成交易计划

        参数：
            stock_data: 股票数据
            plan_date: 计划日期
            hunting_date: 狩猎日期

        返回：
            Dict: 交易计划
        """
        # 获取支撑位和当前价格
        support_level = float(stock_data.get('support_level', 0))
        current_price = float(stock_data.get('current_price', support_level))
        buy_plan = self._calculate_buy_plan(current_price)
        
        # 择时策略中文名称映射
        timing_strategy_display = {
            'turtle': '海龟策略',
            'rsi': 'RSI策略',
            'bollinger': '布林带策略',
            'support': '支撑位策略'
        }
        timing_strategy = stock_data.get('timing_strategy', '')
        timing_strategy_name = timing_strategy_display.get(timing_strategy, timing_strategy)
        
        return {
            'plan_date': plan_date,
            'hunting_date': hunting_date,
            'stock_code': stock_data.get('stock_code', ''),
            'stock_name': stock_data.get('stock_name', ''),
            'buy_lower_price': buy_plan['buy_lower_price'],
            'buy_upper_price': buy_plan['buy_upper_price'],
            'position_ratio': self.DEFAULT_POSITION_RATIO,
            'support_level': support_level,
            'current_price': current_price,
            'stop_loss_price': self._calculate_stop_loss(support_level),
            'take_profit_price': self._calculate_take_profit(support_level),
            'timing_strategy': timing_strategy_name,
            'remark': '',
            'rank': stock_data.get('rank', 0)
        }

    def _calculate_buy_plan(self, current_price: float) -> Dict[str, float]:
        """
        计算买入计划（当前价格±1%）

        参数：
            current_price: 当前价格

        返回：
            Dict: 包含 buy_lower_price, buy_upper_price
        """
        return {
            'buy_lower_price': round(current_price * 0.99, 2),
            'buy_upper_price': round(current_price * 1.01, 2)
        }

    def _calculate_stop_loss(self, support_level: float) -> float:
        """
        计算止损价格

        参数：
            support_level: 支撑位价格

        返回：
            float: 止损价格
        """
        return round(support_level * (1 - self.STOP_LOSS_PERCENT), 2)

    def _calculate_take_profit(self, support_level: float) -> float:
        """
        计算止盈价格

        参数：
            support_level: 支撑位价格

        返回：
            float: 止盈价格
        """
        return round(support_level * (1 + self.TAKE_PROFIT_PERCENT), 2)

    def _save_plans(self, plans: List[Dict[str, Any]]) -> int:
        """
        保存交易计划到数据库

        参数：
            plans: 交易计划列表

        返回：
            int: 保存成功的记录数
        """
        if not plans:
            return 0
        return self.trading_plan_dao.save_batch_plans(plans)