#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KHunter 买点判断模块
负责判断股票是否符合买点条件
"""

import logging
from typing import Dict, Any, Optional

# 配置日志
logger = logging.getLogger(__name__)


class KHunterBuyPointJudge:
    """
    KHunter 买点判断器
    根据当前价格和支撑位判断是否为买点
    """
    
    # 默认买点区间
    DEFAULT_BUY_POINT_LOWER = -1.0
    DEFAULT_BUY_POINT_UPPER = 3.0
    
    def __init__(self, db_manager):
        """
        初始化买点判断器
        
        参数：
            db_manager: 数据库管理器
        """
        # db_manager: 数据库管理器，类型object，必填
        self.db_manager = db_manager
        logger.info("KHunter 买点判断器初始化完成")
    
    # ==================== 公开方法 ====================
    
    def judge_buy_point(
        self,
        current_price: float,
        support_level: float
    ) -> Dict[str, Any]:
        """
        判断是否为买点
        
        参数：
            current_price: 当前价格
            support_level: 支撑位价格
        
        返回：
            Dict: {
                'is_buy_point': bool,
                'price_diff': float,
                'price_diff_percent': float,
                'buy_point_lower': float,
                'buy_point_upper': float
            }
        
        异常：
            ValueError: 如果价格无效或计算失败
        """
        # current_price: 当前价格，类型float，必填
        # support_level: 支撑位价格，类型float，必填
        try:
            # 1. 验证价格有效性
            if current_price <= 0 or support_level <= 0:
                raise ValueError("价格必须大于0")
            
            # 2. 计算价格差
            price_diff = self._calculate_price_diff(
                current_price, support_level
            )
            
            # 3. 计算价格差百分比
            price_diff_percent = self._calculate_price_diff_percent(
                price_diff, support_level
            )
            
            # 4. 获取买点区间配置
            buy_point_config = self._get_buy_point_config()
            buy_point_lower = buy_point_config['buy_point_lower']
            buy_point_upper = buy_point_config['buy_point_upper']
            
            # 5. 判断是否在买点区间内
            is_buy_point = self._is_in_buy_range(
                price_diff_percent, buy_point_lower, buy_point_upper
            )
            
            # 6. 返回结果
            result = {
                'is_buy_point': is_buy_point,
                'price_diff': price_diff,
                'price_diff_percent': price_diff_percent,
                'buy_point_lower': buy_point_lower,
                'buy_point_upper': buy_point_upper
            }
            
            logger.debug(
                f"买点判断完成: 当前价格={current_price} 支撑位={support_level} "
                f"价格差百分比={price_diff_percent}% 是否买点={is_buy_point}"
            )
            return result
        
        except Exception as e:
            logger.error(f"买点判断失败: {str(e)}")
            raise
    
    def judge_buy_points_batch(
        self,
        prices_dict: Dict[str, Dict[str, float]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        批量判断买点
        
        参数：
            prices_dict: 价格字典，格式 {
                stock_code: {
                    'current_price': float,
                    'support_level': float
                },
                ...
            }
        
        返回：
            Dict: {
                stock_code: {
                    'is_buy_point': bool,
                    'price_diff': float,
                    'price_diff_percent': float,
                    'buy_point_lower': float,
                    'buy_point_upper': float
                },
                ...
            }
        
        异常：
            ValueError: 如果价格无效或计算失败
        """
        # prices_dict: 价格字典，类型Dict[str, Dict[str, float]]，必填
        try:
            # 1. 批量判断买点
            results = {}
            for stock_code, prices in prices_dict.items():
                try:
                    # 2. 获取当前价格和支撑位
                    current_price = prices.get('current_price')
                    support_level = prices.get('support_level')
                    
                    # 3. 验证数据完整性
                    if current_price is None or support_level is None:
                        logger.warning(f"{stock_code} 价格数据不完整，跳过")
                        continue
                    
                    # 4. 判断买点
                    result = self.judge_buy_point(current_price, support_level)
                    results[stock_code] = result
                
                except Exception as e:
                    logger.warning(f"{stock_code} 买点判断失败: {str(e)}")
                    continue
            
            logger.info(f"批量买点判断完成: {len(results)} 只股票")
            return results
        
        except Exception as e:
            logger.error(f"批量买点判断失败: {str(e)}")
            raise
    
    # ==================== 私有方法 - 计算方法 ====================
    
    def _calculate_price_diff(
        self,
        current_price: float,
        support_level: float
    ) -> float:
        """
        计算价格差
        
        参数：
            current_price: 当前价格
            support_level: 支撑位价格
        
        返回：
            float: 价格差
        """
        # current_price: 当前价格，类型float，必填
        # support_level: 支撑位价格，类型float，必填
        try:
            # 1. 计算价格差
            price_diff = current_price - support_level
            
            # 2. 精确到小数点后两位
            return round(price_diff, 2)
        
        except Exception as e:
            logger.error(f"计算价格差失败: {str(e)}")
            raise
    
    def _calculate_price_diff_percent(
        self,
        price_diff: float,
        support_level: float
    ) -> float:
        """
        计算价格差百分比
        
        参数：
            price_diff: 价格差
            support_level: 支撑位价格
        
        返回：
            float: 价格差百分比
        """
        # price_diff: 价格差，类型float，必填
        # support_level: 支撑位价格，类型float，必填
        try:
            # 1. 检查支撑位是否为0
            if support_level == 0:
                raise ValueError("支撑位不能为0")
            
            # 2. 计算百分比
            price_diff_percent = (price_diff / support_level) * 100
            
            # 3. 精确到小数点后两位
            return round(price_diff_percent, 2)
        
        except Exception as e:
            logger.error(f"计算价格差百分比失败: {str(e)}")
            raise
    
    def _is_in_buy_range(
        self,
        price_diff_percent: float,
        buy_point_lower: float = None,
        buy_point_upper: float = None
    ) -> bool:
        """
        判断是否在买点区间内
        
        参数：
            price_diff_percent: 价格差百分比
            buy_point_lower: 买点下限（可选，默认从配置读取）
            buy_point_upper: 买点上限（可选，默认从配置读取）
        
        返回：
            bool: 是否在买点区间内
        """
        # price_diff_percent: 价格差百分比，类型float，必填
        # buy_point_lower: 买点下限，类型float，可选
        # buy_point_upper: 买点上限，类型float，可选
        try:
            # 1. 如果没有提供区间，从配置读取
            if buy_point_lower is None or buy_point_upper is None:
                config = self._get_buy_point_config()
                buy_point_lower = config['buy_point_lower']
                buy_point_upper = config['buy_point_upper']
            
            # 2. 判断是否在区间内（包含边界）
            return buy_point_lower <= price_diff_percent <= buy_point_upper
        
        except Exception as e:
            logger.error(f"判断买点区间失败: {str(e)}")
            raise
    
    # ==================== 私有方法 - 配置管理 ====================
    
    def _get_buy_point_config(self) -> Dict[str, float]:
        """
        从 backtest_config 表读取买点区间配置
        
        返回：
            Dict: {
                'buy_point_lower': float,
                'buy_point_upper': float
            }
        """
        try:
            # 1. 查询买点区间配置
            sql = """
            SELECT buy_point_lower, buy_point_upper
            FROM backtest_config
            LIMIT 1
            """
            
            result = self.db_manager.query_one(sql)
            
            # 2. 如果查询成功，返回配置
            if result:
                buy_point_lower = result.get('buy_point_lower')
                buy_point_upper = result.get('buy_point_upper')
                
                # 3. 使用默认值填充缺失的配置
                if buy_point_lower is None:
                    buy_point_lower = self.DEFAULT_BUY_POINT_LOWER
                if buy_point_upper is None:
                    buy_point_upper = self.DEFAULT_BUY_POINT_UPPER
                
                logger.debug(
                    f"读取买点区间配置: 下限={buy_point_lower} 上限={buy_point_upper}"
                )
                
                return {
                    'buy_point_lower': float(buy_point_lower),
                    'buy_point_upper': float(buy_point_upper)
                }
            
            # 4. 如果查询失败，使用默认值
            logger.debug("买点区间配置不存在，使用默认值")
            return {
                'buy_point_lower': self.DEFAULT_BUY_POINT_LOWER,
                'buy_point_upper': self.DEFAULT_BUY_POINT_UPPER
            }
        
        except Exception as e:
            logger.warning(f"读取买点区间配置失败: {str(e)}，使用默认值")
            return {
                'buy_point_lower': self.DEFAULT_BUY_POINT_LOWER,
                'buy_point_upper': self.DEFAULT_BUY_POINT_UPPER
            }
    
    def _get_buy_point_range(self) -> tuple:
        """
        获取买点区间（返回元组格式）
        
        返回：
            tuple: (buy_point_lower, buy_point_upper)
        """
        config = self._get_buy_point_config()
        return (config['buy_point_lower'], config['buy_point_upper'])
