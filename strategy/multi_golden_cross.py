"""
多金叉共振策略 - 识别均线金叉、KDJ金叉、MACD金叉三者同时发生或相隔不到3天的共振信号

选股条件（三个金叉必须同时满足或相隔不到3天）：
1. 均线金叉：短期均线上穿长期均线（如5日上穿20日）
2. KDJ金叉：K线上穿D线
3. MACD金叉：DIF线上穿DEA线
4. 共振确认：三个金叉信号同时发生或相隔不到3天
5. 回溯范围：在最近10天内寻找金叉信号

策略特点：
- 多重确认：三个指标同时确认，降低误信号
- 信号强度：共振信号比单一信号更强
- 趋势反转：专门捕捉趋势反转机会
- 严格筛选：三个金叉同时发生的概率较低，但质量极高
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import MA, KDJ, REF


class MultiGoldenCrossStrategy(BaseStrategy):
    """多金叉共振策略 - 识别均线金叉、KDJ金叉、MACD金叉的共振信号"""
    
    def __init__(self, params=None):
        # 默认参数配置
        default_params = {
            # 均线参数
            'ma_short_period': 5,              # 短期均线周期
            'ma_long_period': 20,              # 长期均线周期
            
            # KDJ参数
            'kdj_n': 9,                       # KDJ的N参数
            'kdj_m1': 3,                      # KDJ的M1参数
            'kdj_m2': 3,                      # KDJ的M2参数
            
            # MACD参数
            'macd_short': 12,                  # MACD短期EMA周期
            'macd_long': 26,                   # MACD长期EMA周期
            'macd_signal': 9,                  # MACD信号线EMA周期
            
            # 共振参数
            'resonance_days': 3,               # 共振时间窗口（天）
            'lookback_days': 10                 # 回溯天数
        }
        
        # 合并用户参数
        if params:
            default_params.update(params)
        
        super().__init__("多金叉共振", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算多金叉共振策略所需的指标
        
        计算的指标包括：
        - 均线（短期、长期）：用于判断均线金叉
        - KDJ（K、D、J）：用于判断KDJ金叉
        - MACD（DIF、DEA、MACD）：用于判断MACD金叉
        - 趋势线：用于输出信号
        - 市值：用于输出信号
        """
        result = df.copy()
        
        # 确保数据按时间正序排列（从旧到新）
        result = result.sort_values('date', ascending=True).reset_index(drop=True)
        
        # 计算均线（用于判断均线金叉）
        result['ma_short'] = result['close'].rolling(window=self.params['ma_short_period']).mean()
        result['ma_long'] = result['close'].rolling(window=self.params['ma_long_period']).mean()
        
        # 计算KDJ指标（用于判断KDJ金叉）
        kdj_df = KDJ(result, n=self.params['kdj_n'], m1=self.params['kdj_m1'], m2=self.params['kdj_m2'])
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']
        
        # 计算MACD指标（用于判断MACD金叉）
        ema_12 = result['close'].ewm(span=self.params['macd_short'], adjust=False).mean()
        ema_26 = result['close'].ewm(span=self.params['macd_long'], adjust=False).mean()
        result['DIF'] = ema_12 - ema_26
        result['DEA'] = result['DIF'].ewm(span=self.params['macd_signal'], adjust=False).mean()
        result['MACD'] = result['DIF'] - result['DEA']
        
        # 计算成交量比（用于输出信号）
        result['volume_ma'] = result['volume'].rolling(window=5, min_periods=1).mean()
        result['volume_ratio'] = result['volume'] / result['volume_ma']
        
        # 填充缺失值
        result = result.ffill().bfill()
        
        # 计算金叉信号（向量化计算）
        result['ma_cross'] = 0
        result.loc[result['ma_short'] > result['ma_long'], 'ma_cross'] = 1
        result['ma_cross_signal'] = (result['ma_cross'] == 1) & (result['ma_cross'].shift(1) == 0)
        
        result['kdj_cross'] = 0
        result.loc[result['K'] > result['D'], 'kdj_cross'] = 1
        result['kdj_cross_signal'] = (result['kdj_cross'] == 1) & (result['kdj_cross'].shift(1) == 0)
        
        result['macd_cross'] = 0
        result.loc[result['DIF'] > result['DEA'], 'macd_cross'] = 1
        result['macd_cross_signal'] = (result['macd_cross'] == 1) & (result['macd_cross'].shift(1) == 0)
        
        # 恢复原始顺序（从新到旧）
        result = result.sort_values('date', ascending=False).reset_index(drop=True)
        
        # 计算趋势线（与其他策略保持一致）
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
        
        # 计算市值（如果CSV中有market_cap字段则使用，否则估算）
        if 'market_cap' not in result.columns:
            # 估算市值：假设总股本2亿股
            result['market_cap'] = result['close'] * 2e8
        
        return result
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别多金叉共振信号
        
        参数说明：
        - lookback_days: 回溯天数，用于寻找金叉信号。设置为10时检查最近10天内的金叉
        - resonance_days: 共振时间窗口，三个金叉信号的最大时间差。设置为3时表示三个金叉相隔不到3天
        """
        if df.empty or len(df) < self.params['lookback_days']:
            return []
        
        # 过滤退市/异常股票
        if stock_name:
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in stock_name for kw in invalid_keywords):
                return []
            
            # 过滤 ST/*ST 股票
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []
        
        # 获取最新一天的数据
        latest = df.iloc[0]
        latest_date = latest['date']
        
        # 检查最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 获取回溯期间的数据
        lookback_days = self.params['lookback_days']
        lookback_df = df.head(lookback_days)
        
        # 检查三个金叉条件
        # 条件1：均线金叉
        ma_cross_date = self._find_ma_cross(lookback_df)
        if ma_cross_date is None:
            return []
        
        # 条件2：KDJ金叉
        kdj_cross_date = self._find_kdj_cross(lookback_df)
        if kdj_cross_date is None:
            return []
        
        # 条件3：MACD金叉
        macd_cross_date = self._find_macd_cross(lookback_df)
        if macd_cross_date is None:
            return []
        
        # 条件4：共振确认（三个金叉相隔不到3天）
        if not self._check_resonance(ma_cross_date, kdj_cross_date, macd_cross_date):
            return []
        
        # 条件5：价格确认（收盘价在所有均线上方）
        if not self._check_price_confirmation(latest):
            return []
        
        # 所有条件都满足，生成选股信号
        signal_info = {
            'date': latest_date,
            'close': round(latest['close'], 2),
            'ma_cross_date': ma_cross_date,
            'kdj_cross_date': kdj_cross_date,
            'macd_cross_date': macd_cross_date,
            'max_time_diff': self._calculate_max_time_diff(ma_cross_date, kdj_cross_date, macd_cross_date),
            'ma_short': round(latest['ma_short'], 2),
            'ma_long': round(latest['ma_long'], 2),
            'K': round(latest['K'], 2),
            'D': round(latest['D'], 2),
            'J': round(latest['J'], 2),
            'DIF': round(latest['DIF'], 4),
            'DEA': round(latest['DEA'], 4),
            'MACD': round(latest['MACD'], 4),
            'volume_ratio': round(latest['volume_ratio'], 2),
            'market_cap': round(latest['market_cap'] / 1e8, 2),
            'short_term_trend': round(latest['short_term_trend'], 2),
            'bull_bear_line': round(latest['bull_bear_line'], 2),
            'reasons': ['均线金叉', 'KDJ金叉', 'MACD金叉', '多指标共振']
        }
        
        return [signal_info]
    
    def _find_ma_cross(self, df) -> str:
        """
        查找均线金叉
        
        使用预计算的ma_cross_signal列快速查找金叉
        
        返回：金叉发生的日期，如果没有找到则返回None
        """
        if df.empty:
            return None
        
        # 寻找最近的金叉信号
        cross_rows = df[df['ma_cross_signal'] == True]
        if not cross_rows.empty:
            # 返回最近的金叉日期
            return cross_rows.iloc[0]['date']
        
        return None
    
    def _find_kdj_cross(self, df) -> str:
        """
        查找KDJ金叉
        
        使用预计算的kdj_cross_signal列快速查找金叉
        
        返回：金叉发生的日期，如果没有找到则返回None
        """
        if df.empty:
            return None
        
        # 寻找最近的金叉信号
        cross_rows = df[df['kdj_cross_signal'] == True]
        if not cross_rows.empty:
            # 返回最近的金叉日期
            return cross_rows.iloc[0]['date']
        
        return None
    
    def _find_macd_cross(self, df) -> str:
        """
        查找MACD金叉
        
        使用预计算的macd_cross_signal列快速查找金叉
        
        返回：金叉发生的日期，如果没有找到则返回None
        """
        if df.empty:
            return None
        
        # 寻找最近的金叉信号
        cross_rows = df[df['macd_cross_signal'] == True]
        if not cross_rows.empty:
            # 返回最近的金叉日期
            return cross_rows.iloc[0]['date']
        
        return None
    
    def _check_resonance(self, ma_cross_date, kdj_cross_date, macd_cross_date) -> bool:
        """
        检查共振条件
        
        判断逻辑：
        - 三个金叉信号同时发生或相隔不到3天
        - 计算三个金叉日期的最大时间差
        - 确认最大时间差 < 3天
        
        返回：是否满足共振条件
        """
        if ma_cross_date is None or kdj_cross_date is None or macd_cross_date is None:
            return False
        
        # 计算时间差（天）
        time_diffs = []
        dates = [ma_cross_date, kdj_cross_date, macd_cross_date]
        
        for i in range(len(dates)):
            for j in range(i + 1, len(dates)):
                diff = abs((dates[i] - dates[j]).days)
                time_diffs.append(diff)
        
        # 获取最大时间差
        max_time_diff = max(time_diffs) if time_diffs else 0
        
        # 判断是否满足共振条件
        return max_time_diff <= self.params['resonance_days']
    
    def _calculate_max_time_diff(self, ma_cross_date, kdj_cross_date, macd_cross_date) -> int:
        """
        计算最大时间差
        
        返回：三个金叉日期的最大时间差（天）
        """
        if ma_cross_date is None or kdj_cross_date is None or macd_cross_date is None:
            return 0
        
        time_diffs = []
        dates = [ma_cross_date, kdj_cross_date, macd_cross_date]
        
        for i in range(len(dates)):
            for j in range(i + 1, len(dates)):
                diff = abs((dates[i] - dates[j]).days)
                time_diffs.append(diff)
        
        return max(time_diffs) if time_diffs else 0
    
    def _check_price_confirmation(self, latest) -> bool:
        """
        检查价格确认条件
        
        判断逻辑：
        - 收盘价在短期均线上方
        - 收盘价在长期均线上方
        
        返回：是否满足价格确认条件
        """
        if pd.isna(latest['close']) or pd.isna(latest['ma_short']) or pd.isna(latest['ma_long']):
            return False
        
        # 判断收盘价是否在所有均线上方
        return latest['close'] >= latest['ma_short'] and latest['close'] >= latest['ma_long']
