# -*- coding: utf-8 -*-
"""
凯莉公式配置加载器和计算器

提供以下功能：
1. 加载策略凯莉配置文件
2. 提供凯莉公式计算方法
3. 计算首次建仓金额
"""

import os
import yaml
import logging

logger = logging.getLogger(__name__)


class KellyConfig:
    """凯莉公式配置加载器（单例模式）"""
    
    _instance = None
    _config = None
    
    CONFIG_PATH = 'config/strategy_kelly_config.yaml'
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(KellyConfig, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.CONFIG_PATH):
                with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
                    self._config = yaml.safe_load(f)
                logger.info(f"凯莉配置加载成功，策略数量: {len(self._config.get('strategies', {}))}")
            else:
                # 使用默认配置
                self._config = self._get_default_config()
                logger.warning(f"凯莉配置文件不存在，使用默认配置: {self.CONFIG_PATH}")
        except Exception as e:
            logger.error(f"加载凯莉配置失败: {str(e)}")
            self._config = self._get_default_config()
    
    def _get_default_config(self):
        """获取默认配置"""
        return {
            'strategies': {
                '_default_': {
                    'win_rate': 0.40,
                    'profit_loss_ratio': 1.5,
                    'description': '默认配置'
                }
            },
            'constraints': {
                'min_kelly_ratio': 0.0,
                'max_kelly_ratio': 0.30,
                'max_position_ratio': 0.50,
                'min_invest_amount': 100
            }
        }
    
    def get_strategy_config(self, strategy_name: str) -> dict:
        """
        获取策略配置，策略未配置时返回默认配置
        
        Args:
            strategy_name: 策略名称（英文类名或中文名称）
            
        Returns:
            策略配置字典，包含 win_rate, profit_loss_ratio, description
        """
        from utils.strategy_name_mapper import get_english_name
        
        strategies = self._config.get('strategies', {})
        
        # 直接匹配（英文类名）
        if strategy_name in strategies:
            return strategies[strategy_name]
        
        # 尝试去除"Strategy"后缀
        if strategy_name.endswith('Strategy'):
            short_name = strategy_name[:-8]
            if short_name in strategies:
                return strategies[short_name]
        
        # 尝试中文名称匹配（使用策略名称映射器）
        english_name = get_english_name(strategy_name)
        if english_name in strategies:
            return strategies[english_name]
        
        # 返回默认配置
        return strategies.get('_default_', {
            'win_rate': 0.40,
            'profit_loss_ratio': 1.5,
            'description': '默认配置'
        })
    
    def get_constraints(self) -> dict:
        """
        获取约束配置
        
        Returns:
            约束配置字典
        """
        return self._config.get('constraints', {
            'min_kelly_ratio': 0.0,
            'max_kelly_ratio': 0.30,
            'max_position_ratio': 0.50,
            'min_invest_amount': 100
        })
    
    def get_kelly_ratio(self, strategy_name: str) -> float:
        """
        根据策略名获取凯莉比例
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            凯莉比例（0-1）
        """
        config = self.get_strategy_config(strategy_name)
        win_rate = config.get('win_rate', 0.4)
        profit_loss_ratio = config.get('profit_loss_ratio', 1.5)
        
        return KellyCalculator.calculate_kelly_ratio(win_rate, profit_loss_ratio)


class KellyCalculator:
    """凯莉公式计算器"""
    
    @staticmethod
    def calculate_kelly_ratio(win_rate: float, profit_loss_ratio: float) -> float:
        """
        计算凯莉比例
        
        公式: f* = (p × b - q) / b = (胜率 × 盈亏比 - 败率) / 盈亏比
        
        Args:
            win_rate: 胜率 (0-1)
            profit_loss_ratio: 盈亏比（平均盈利/平均亏损）
            
        Returns:
            凯莉比例 (0-1)
        """
        if profit_loss_ratio <= 0:
            return 0.0
        
        p = win_rate
        q = 1 - p
        b = profit_loss_ratio
        
        kelly = (p * b - q) / b
        
        # 应用约束
        kelly = max(0.0, kelly)  # 不为负
        kelly = min(0.30, kelly)  # 上限30%
        
        return kelly
    
    @staticmethod
    def calculate_position_amount(total_capital: float, available_cash: float,
                                strategy_name: str) -> float:
        """
        计算首次建仓金额
        
        Args:
            total_capital: 当日总资金
            available_cash: 可用资金
            strategy_name: 策略名称
            
        Returns:
            投资金额（向下取整为100的整数倍）
        """
        # 获取配置
        config = KellyConfig().get_strategy_config(strategy_name)
        constraints = KellyConfig().get_constraints()
        
        # 获取参数
        win_rate = config.get('win_rate', 0.4)
        profit_loss_ratio = config.get('profit_loss_ratio', 1.5)
        
        # 计算凯莉比例
        kelly_ratio = KellyCalculator.calculate_kelly_ratio(win_rate, profit_loss_ratio)
        
        # 获取约束参数
        min_kelly_ratio = constraints.get('min_kelly_ratio', 0.0)
        max_kelly_ratio = constraints.get('max_kelly_ratio', 0.30)
        max_position_ratio = constraints.get('max_position_ratio', 0.50)
        min_invest_amount = constraints.get('min_invest_amount', 100)
        
        # 应用凯莉比例约束
        kelly_ratio = max(min_kelly_ratio, kelly_ratio)
        kelly_ratio = min(max_kelly_ratio, kelly_ratio)
        
        # 计算基于凯莉比例的金额
        amount_by_kelly = total_capital * kelly_ratio
        
        # 使用凯莉公式计算的金额，但不超过可用资金（兜底逻辑）
        amount = min(amount_by_kelly, available_cash)
        
        # 应用最小投资金额约束
        if amount < min_invest_amount:
            amount = 0
        
        # 向下取整为100的整数倍
        amount = int(amount // 100 * 100)
        
        logger.debug(f"凯莉计算结果 - 策略:{strategy_name}, 胜率:{win_rate}, 盈亏比:{profit_loss_ratio}, "
                    f"凯莉比例:{kelly_ratio:.4f}, 总资金:{total_capital}, 可用资金:{available_cash}, "
                    f"计算金额:{amount}")
        
        return amount
    
    @staticmethod
    def calculate_position_amount_with_params(total_capital: float, available_cash: float,
                                            strategy_name: str) -> dict:
        """
        计算首次建仓金额并返回计算过程中使用的所有凯利公式参数
        
        Args:
            total_capital: 当日总资金
            available_cash: 可用资金
            strategy_name: 策略名称
            
        Returns:
            包含计算结果和参数的字典：
            {
                'amount': 投资金额（向下取整为100的整数倍）,
                'win_rate': 胜率,
                'profit_loss_ratio': 盈亏比,
                'kelly_ratio': 计算得到的凯利比例,
                'total_capital': 计算时的总资金,
                'available_cash': 计算时的可用资金,
                'strategy_name': 使用的策略名称
            }
        """
        # 获取配置
        config = KellyConfig().get_strategy_config(strategy_name)
        constraints = KellyConfig().get_constraints()
        
        # 获取参数
        win_rate = config.get('win_rate', 0.4)
        profit_loss_ratio = config.get('profit_loss_ratio', 1.5)
        
        # 计算凯莉比例
        kelly_ratio = KellyCalculator.calculate_kelly_ratio(win_rate, profit_loss_ratio)
        
        # 获取约束参数
        min_kelly_ratio = constraints.get('min_kelly_ratio', 0.0)
        max_kelly_ratio = constraints.get('max_kelly_ratio', 0.30)
        max_position_ratio = constraints.get('max_position_ratio', 0.50)
        min_invest_amount = constraints.get('min_invest_amount', 100)
        
        # 应用凯莉比例约束
        kelly_ratio = max(min_kelly_ratio, kelly_ratio)
        kelly_ratio = min(max_kelly_ratio, kelly_ratio)
        
        # 计算基于凯莉比例的金额
        amount_by_kelly = total_capital * kelly_ratio
        
        # 使用凯莉公式计算的金额，但不超过可用资金（兜底逻辑）
        amount = min(amount_by_kelly, available_cash)
        
        # 应用最小投资金额约束
        if amount < min_invest_amount:
            amount = 0
        
        # 向下取整为100的整数倍
        amount = int(amount // 100 * 100)
        
        logger.debug(f"凯莉计算结果 - 策略:{strategy_name}, 胜率:{win_rate}, 盈亏比:{profit_loss_ratio}, "
                    f"凯莉比例:{kelly_ratio:.4f}, 总资金:{total_capital}, 可用资金:{available_cash}, "
                    f"计算金额:{amount}")
        
        return {
            'amount': amount,
            'win_rate': win_rate,
            'profit_loss_ratio': profit_loss_ratio,
            'kelly_ratio': kelly_ratio,
            'total_capital': total_capital,
            'available_cash': available_cash,
            'strategy_name': strategy_name
        }
    
    @staticmethod
    def calculate_buy_quantity(position_amount: float, price: float) -> int:
        """
        计算买入数量（A股规则：必须是100的整数倍）
        
        Args:
            position_amount: 投资金额
            price: 当前价格
            
        Returns:
            买入数量（100的整数倍）
        """
        if position_amount <= 0 or price <= 0:
            return 0
        
        # 计算数量并向下取整为100的整数倍
        quantity = int(position_amount / price // 100 * 100)
        
        return max(quantity, 0)
