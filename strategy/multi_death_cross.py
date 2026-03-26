"""
多死叉共振策略实现

策略原理：
识别均线死叉、KDJ死叉、MACD死叉三者同时发生或相隔不到3天的共振信号，
用于识别下跌趋势的卖出信号。

选股条件：
1. 均线死叉：MA5从上方向下穿过MA20
2. KDJ死叉：K线从上方向下穿过D线
3. MACD死叉：DIF线从上方向下穿过DEA线
4. 共振条件：三个死叉信号的最大时间差不超过3天
5. 价格确认：收盘价在所有均线下方
"""
import pandas as pd
import numpy as np
from typing import Optional
from pathlib import Path
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy


class MultiDeathCrossStrategy(BaseStrategy):
    """多死叉共振策略"""
    
    def __init__(self, params=None):
        """
        初始化策略
        :param params: 参数字典
        """
        # 默认参数
        default_params = {
            'ma_short_period': 5,      # 短期均线周期
            'ma_long_period': 20,      # 长期均线周期
            'kdj_n': 9,               # KDJ的N参数
            'kdj_m1': 3,              # KDJ的M1参数
            'kdj_m2': 3,              # KDJ的M2参数
            'macd_short': 12,          # MACD短期EMA周期
            'macd_long': 26,          # MACD长期EMA周期
            'macd_signal': 9,         # MACD信号线EMA周期
            'resonance_days': 3,       # 共振时间窗口（天）
            'lookback_days': 10,       # 回溯天数
        }
        
        # 合并参数
        if params:
            default_params.update(params)
        
        super().__init__('多死叉共振策略', default_params)
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算技术指标
        :param df: 股票数据DataFrame
        :return: 添加了指标列的DataFrame
        """
        result = df.copy()
        
        # 确保数据按时间正序排列（从旧到新）
        result = result.sort_values('date', ascending=True).reset_index(drop=True)
        
        # 计算均线（用于判断均线死叉）
        result['ma_short'] = result['close'].rolling(window=self.params['ma_short_period']).mean()
        result['ma_long'] = result['close'].rolling(window=self.params['ma_long_period']).mean()
        
        # 计算KDJ指标（用于判断KDJ死叉）
        from utils.technical import KDJ
        kdj_df = KDJ(result, n=self.params['kdj_n'], m1=self.params['kdj_m1'], m2=self.params['kdj_m2'])
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']
        
        # 计算MACD指标（用于判断MACD死叉）
        macd_short = self.params['macd_short']
        macd_long = self.params['macd_long']
        macd_signal = self.params['macd_signal']
        
        ema_short = result['close'].ewm(span=macd_short, adjust=False).mean()
        ema_long = result['close'].ewm(span=macd_long, adjust=False).mean()
        
        result['DIF'] = ema_short - ema_long
        result['DEA'] = result['DIF'].ewm(span=macd_signal, adjust=False).mean()
        result['MACD'] = result['DIF'] - result['DEA']  # 与多金叉策略保持一致
        
        # 计算成交量比（用于输出信号）
        result['volume_ma'] = result['volume'].rolling(window=5, min_periods=1).mean()
        result['volume_ratio'] = result['volume'] / result['volume_ma']
        
        # 填充缺失值
        result = result.ffill().bfill()
        
        # 计算死叉信号（向量化计算）
        result['ma_death_cross'] = 0
        result.loc[result['ma_short'] < result['ma_long'], 'ma_death_cross'] = 1
        result['ma_death_cross_signal'] = (result['ma_death_cross'] == 1) & (result['ma_death_cross'].shift(1) == 0)
        
        result['kdj_death_cross'] = 0
        result.loc[result['K'] < result['D'], 'kdj_death_cross'] = 1
        result['kdj_death_cross_signal'] = (result['kdj_death_cross'] == 1) & (result['kdj_death_cross'].shift(1) == 0)
        
        result['macd_death_cross'] = 0
        result.loc[result['DIF'] < result['DEA'], 'macd_death_cross'] = 1
        result['macd_death_cross_signal'] = (result['macd_death_cross'] == 1) & (result['macd_death_cross'].shift(1) == 0)
        
        # 恢复原始顺序（从新到旧）
        result = result.sort_values('date', ascending=False).reset_index(drop=True)
        
        # 计算趋势线（与多金叉策略保持一致）
        from utils.technical import calculate_zhixing_trend
        trend_df = calculate_zhixing_trend(
            result,
            m1=14,   # MA周期1
            m2=28,   # MA周期2
            m3=57,   # MA周期3
            m4=114   # MA周期4
        )
        result['short_term_trend'] = trend_df['short_term_trend']
        result['bull_bear_line'] = trend_df['bull_bear_line']
        
        return result
    
    def _find_ma_death_cross(self, df: pd.DataFrame) -> Optional[pd.Timestamp]:
        """
        查找均线死叉
        :param df: 包含指标的股票数据
        :return: 死叉日期或None
        """
        lookback_days = self.params['lookback_days']
        
        # 只查看最近lookback_days天的数据
        recent_df = df.head(lookback_days)
        
        # 检查是否有足够的数据
        if recent_df.empty:
            return None
        
        # 寻找最近的死叉信号
        cross_rows = recent_df[recent_df['ma_death_cross_signal'] == True]
        if not cross_rows.empty:
            # 返回最近的死叉日期
            return cross_rows.iloc[0]['date']
        
        return None
    
    def _find_kdj_death_cross(self, df: pd.DataFrame) -> Optional[pd.Timestamp]:
        """
        查找KDJ死叉
        :param df: 包含指标的股票数据
        :return: 死叉日期或None
        """
        lookback_days = self.params['lookback_days']
        
        # 只查看最近lookback_days天的数据
        recent_df = df.head(lookback_days)
        
        # 检查是否有足够的数据
        if recent_df.empty:
            return None
        
        # 寻找最近的死叉信号
        cross_rows = recent_df[recent_df['kdj_death_cross_signal'] == True]
        if not cross_rows.empty:
            # 返回最近的死叉日期
            return cross_rows.iloc[0]['date']
        
        return None
    
    def _find_macd_death_cross(self, df: pd.DataFrame) -> Optional[pd.Timestamp]:
        """
        查找MACD死叉
        :param df: 包含指标的股票数据
        :return: 死叉日期或None
        """
        lookback_days = self.params['lookback_days']
        
        # 只查看最近lookback_days天的数据
        recent_df = df.head(lookback_days)
        
        # 检查是否有足够的数据
        if recent_df.empty:
            return None
        
        # 寻找最近的死叉信号
        cross_rows = recent_df[recent_df['macd_death_cross_signal'] == True]
        if not cross_rows.empty:
            # 返回最近的死叉日期
            return cross_rows.iloc[0]['date']
        
        return None
    
    def _check_resonance(self, date1: Optional[pd.Timestamp], 
                        date2: Optional[pd.Timestamp], 
                        date3: Optional[pd.Timestamp]) -> bool:
        """
        检查共振条件
        :param date1: 第一个死叉日期
        :param date2: 第二个死叉日期
        :param date3: 第三个死叉日期
        :return: 是否满足共振条件
        """
        # 如果任何一个日期为None，不满足共振条件
        if date1 is None or date2 is None or date3 is None:
            return False
        
        # 计算最大时间差
        max_diff = self._calculate_max_time_diff(date1, date2, date3)
        
        # 检查是否在共振时间窗口内
        return max_diff <= self.params['resonance_days']
    
    def _calculate_max_time_diff(self, date1: pd.Timestamp, 
                                date2: pd.Timestamp, 
                                date3: pd.Timestamp) -> int:
        """
        计算最大时间差
        :param date1: 第一个日期
        :param date2: 第二个日期
        :param date3: 第三个日期
        :return: 最大时间差（天数）
        """
        # 过滤掉None值
        dates = [d for d in [date1, date2, date3] if d is not None]
        
        # 如果有效日期少于2个，返回0
        if len(dates) < 2:
            return 0
        
        # 找到最早和最晚的日期
        min_date = min(dates)
        max_date = max(dates)
        
        # 计算时间差
        time_diff = (max_date - min_date).days
        
        return time_diff
    
    def _check_price_confirmation(self, latest: pd.Series) -> bool:
        """
        检查价格确认条件
        :param latest: 最新一天的数据
        :return: 是否满足价格确认条件
        """
        # 检查收盘价是否在所有均线下方
        if pd.isna(latest['close']) or pd.isna(latest['ma_short']) or pd.isna(latest['ma_long']):
            return False
        
        # 收盘价在MA5下方
        if latest['close'] >= latest['ma_short']:
            return False
        
        # 收盘价在MA20下方
        if latest['close'] >= latest['ma_long']:
            return False
        
        # 收盘价在短期趋势线下方
        if pd.isna(latest['short_term_trend']):
            return False
        if latest['close'] >= latest['short_term_trend']:
            return False
        
        # 收盘价在多空线下方
        if pd.isna(latest['bull_bear_line']):
            return False
        if latest['close'] >= latest['bull_bear_line']:
            return False
        
        return True
    
    def select_stocks(self, df: pd.DataFrame, stock_name='') -> list:
        """
        选股逻辑
        :param df: 包含指标的股票数据
        :param stock_name: 股票名称，用于过滤退市股票
        :return: 选股信号列表
        """
        # 检查数据是否为空
        if df is None or df.empty:
            return []
        
        # 计算指标（必须在选股逻辑之前调用）
        df = self.calculate_indicators(df)
        
        # 检查数据长度是否足够
        lookback_days = self.params['lookback_days']
        if len(df) < lookback_days:
            return []
        
        # 过滤退市股票
        if stock_name and ('退市' in stock_name or 'ST' in stock_name or '*ST' in stock_name):
            return []
        
        # 查找三个死叉信号
        ma_cross_date = self._find_ma_death_cross(df)
        kdj_cross_date = self._find_kdj_death_cross(df)
        macd_cross_date = self._find_macd_death_cross(df)
        
        # 检查共振条件
        if not self._check_resonance(ma_cross_date, kdj_cross_date, macd_cross_date):
            return []
        
        # 检查价格确认条件
        latest = df.iloc[0]
        if not self._check_price_confirmation(latest):
            return []
        
        # 计算最大时间差
        max_time_diff = self._calculate_max_time_diff(ma_cross_date, kdj_cross_date, macd_cross_date)
        
        # 生成选股信号
        signal = {
            'date': latest['date'],
            'close': latest['close'],
            'ma_short': latest['ma_short'],
            'ma_long': latest['ma_long'],
            'ma_cross_date': ma_cross_date,
            'K': latest['K'],
            'D': latest['D'],
            'J': latest['J'],
            'kdj_cross_date': kdj_cross_date,
            'DIF': latest['DIF'],
            'DEA': latest['DEA'],
            'MACD': latest['MACD'],
            'macd_cross_date': macd_cross_date,
            'max_time_diff': max_time_diff,
            'volume_ratio': latest['volume_ratio'],
            'market_cap': latest['market_cap'] / 100000000,  # 转换为亿元
            'short_term_trend': latest['short_term_trend'],
            'bull_bear_line': latest['bull_bear_line'],
            'reasons': ['均线死叉', 'KDJ死叉', 'MACD死叉', '多指标共振']
        }
        
        return [signal]
