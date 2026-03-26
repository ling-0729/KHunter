"""
策略基类定义
"""
from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """策略抽象基类"""
    
    def __init__(self, name, params=None):
        """
        初始化策略
        :param name: 策略名称
        :param params: 参数字典
        """
        self.name = name
        self.params = params or {}
    
    @abstractmethod
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标
        :param df: 股票数据DataFrame
        :return: 添加了指标列的DataFrame
        """
        pass
    
    @abstractmethod
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑
        :param df: 包含指标的股票数据
        :param stock_name: 股票名称，用于过滤退市股票
        :return: 选股信号列表，每个元素为字典包含信号详情
        """
        pass
    
    def analyze_stock(self, stock_code, stock_name, df):
        """
        分析单只股票
        :return: 选股信号或None
        """
        if df is None or df.empty or len(df) < 60:
            return None
        
        # 计算指标
        df_with_indicators = self.calculate_indicators(df)
        
        # 选股 - 传递股票名称用于过滤
        signals = self.select_stocks(df_with_indicators, stock_name)
        
        if signals:
            return {
                'code': stock_code,
                'name': stock_name,
                'signals': signals
            }
        return None
