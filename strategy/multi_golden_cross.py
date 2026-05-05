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

优化版本：
- 减少数据排序次数
- 直接在倒序数据上计算指标
- 添加快速预检查
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy


class MultiGoldenCrossStrategy(BaseStrategy):
    """多金叉共振策略 - 识别均线金叉、KDJ金叉、MACD金叉的共振信号"""
    
    def __init__(self, params=None):
        # 默认参数配置 - 与 config/strategy_params.yaml 中的配置保持一致
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
            'resonance_days': 1,               # 共振时间窗口（天）
            'lookback_days': 3                 # 回溯天数
        }
        
        # 合并用户参数 - params 中的值覆盖默认值
        if params:
            default_params.update(params)
        
        super().__init__("多金叉共振", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算多金叉共振策略所需的指标 - 优化版本
        
        优化点：
        1. 先按日期升序排序，确保技术指标计算正确
        2. 使用更高效的向量化操作
        """
        # 检查输入数据是否有效
        if df.empty or len(df) < 2:
            return pd.DataFrame()
        
        result = df.copy()
        
        # 按日期升序排序，确保技术指标计算正确（使用过去的数据）
        result = result.sort_values('date', ascending=True)
        
        close = result['close']
        high = result['high']
        low = result['low']
        volume = result['volume']
        
        # 计算均线
        result['ma_short'] = close.rolling(window=self.params['ma_short_period'], min_periods=1).mean()
        result['ma_long'] = close.rolling(window=self.params['ma_long_period'], min_periods=1).mean()
        
        # 计算KDJ指标
        n = self.params['kdj_n']
        m1 = self.params['kdj_m1']
        m2 = self.params['kdj_m2']
        
        # RSV计算
        lowest_low = low.rolling(window=n, min_periods=1).min()
        highest_high = high.rolling(window=n, min_periods=1).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
        rsv = rsv.fillna(50)
        
        # K、D、J计算 - 使用向量化操作
        kdj_m1 = self.params['kdj_m1']
        kdj_m2 = self.params['kdj_m2']
        k_values = rsv.ewm(alpha=1/kdj_m1, adjust=False).mean()
        d_values = k_values.ewm(alpha=1/kdj_m2, adjust=False).mean()
        
        result['K'] = k_values
        result['D'] = d_values
        result['J'] = 3 * k_values - 2 * d_values
        
        # 计算MACD指标
        ema_short = close.ewm(span=self.params['macd_short'], adjust=False).mean()
        ema_long = close.ewm(span=self.params['macd_long'], adjust=False).mean()
        result['DIF'] = ema_short - ema_long
        result['DEA'] = result['DIF'].ewm(span=self.params['macd_signal'], adjust=False).mean()
        result['MACD'] = (result['DIF'] - result['DEA']) * 2
        
        # 计算成交量比
        result['volume_ma'] = volume.rolling(window=5, min_periods=1).mean()
        result['volume_ratio'] = volume / result['volume_ma']
        
        # 填充缺失值
        result = result.ffill().bfill()
        
        # 计算金叉信号 - 在升序数据上检测
        # 金叉 = 当前在上方且前一天在下方
        result['ma_cross_signal'] = (result['ma_short'] > result['ma_long']) & \
                                    (result['ma_short'].shift(1) <= result['ma_long'].shift(1))
        
        result['kdj_cross_signal'] = (result['K'] > result['D']) & \
                                     (result['K'].shift(1) <= result['D'].shift(1))
        
        result['macd_cross_signal'] = (result['DIF'] > result['DEA']) & \
                                      (result['DIF'].shift(1) <= result['DEA'].shift(1))
        
        # 计算趋势线
        result['short_term_trend'] = close.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean()
        m1, m2, m3, m4 = 14, 28, 57, 114
        result['bull_bear_line'] = (
            close.rolling(window=m1, min_periods=1).mean() +
            close.rolling(window=m2, min_periods=1).mean() +
            close.rolling(window=m3, min_periods=1).mean() +
            close.rolling(window=m4, min_periods=1).mean()
        ) / 4
        
        # 按日期降序排序，返回与输入相同的顺序
        result = result.sort_values('date', ascending=False)
        
        # 计算市值
        if 'market_cap' not in result.columns:
            result['market_cap'] = close * 2e8
        
        return result
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []
        
        # 条件1：均线金叉
        ma_short_period = self.params['ma_short_period']
        ma_long_period = self.params['ma_long_period']
        criteria.append(f"1. 均线金叉：{ma_short_period}日均线上穿{ma_long_period}日均线")
        
        # 条件2：KDJ金叉
        kdj_n = self.params['kdj_n']
        criteria.append(f"2. KDJ金叉：K线上穿D线（KDJ参数N={kdj_n}）")
        
        # 条件3：MACD金叉
        macd_short = self.params['macd_short']
        macd_long = self.params['macd_long']
        macd_signal = self.params['macd_signal']
        criteria.append(f"3. MACD金叉：DIF线上穿DEA线（MACD参数：{macd_short},{macd_long},{macd_signal}）")
        
        # 条件4：共振确认
        resonance_days = self.params['resonance_days']
        lookback_days = self.params['lookback_days']
        criteria.append(f"4. 共振确认：三个金叉信号在最近{lookback_days}天内发生，且相隔不超过{resonance_days}天")
        
        return criteria
    
    def select_stocks(self, df, stock_name='', df_with_indicators=None) -> list:
        """
        选股逻辑 - 识别多金叉共振信号 - 优化版本
        
        优化点：
        1. 快速预检查，提前过滤不符合条件的股票
        2. 减少不必要的计算
        3. 支持传入预计算的指标数据
        
        参数说明：
        - lookback_days: 回溯天数，用于寻找金叉信号。设置为10时检查最近10天内的金叉
        - resonance_days: 共振时间窗口，三个金叉信号的最大时间差。设置为3时表示三个金叉相隔不到3天
        - df_with_indicators: 可选，预计算的指标数据，如果提供则不再调用calculate_indicators
        """
        if df.empty or len(df) < self.params['lookback_days']:
            return []
        
        # 快速预检查：过滤退市/异常股票
        if stock_name:
            # 快速检查第一个字符
            if len(stock_name) > 0:
                first_char = stock_name[0]
                if first_char in ['*', 'S'] or '退' in stock_name or '未知' in stock_name or '已退' in stock_name:
                    if stock_name.startswith('*ST') or stock_name.startswith('ST') or '退' in stock_name:
                        return []
        
        # 计算技术指标（如果未提供预计算数据）
        if df_with_indicators is None:
            df_with_indicators = self.calculate_indicators(df)
        
        if df_with_indicators.empty:
            return []
        
        # 获取最新一天的数据
        latest = df_with_indicators.iloc[0]
        latest_date = latest['date']
        
        # 快速检查：最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 快速检查：价格确认（收盘价在均线上方）
        if latest['close'] < latest['ma_short'] or latest['close'] < latest['ma_long']:
            return []
        
        # 快速检查：成交量验证（最近有一定量能）
        if latest['volume_ratio'] < 1.0:
            return []
        
        # 获取回溯期间的数据
        lookback_days = self.params['lookback_days']
        lookback_df = df_with_indicators.head(lookback_days)
        
        # 快速检查：三个金叉信号必须都存在
        if not lookback_df['ma_cross_signal'].any():
            return []
        if not lookback_df['kdj_cross_signal'].any():
            return []
        if not lookback_df['macd_cross_signal'].any():
            return []
        
        # 查找金叉日期
        ma_cross_date = self._find_cross_date(lookback_df, 'ma_cross_signal')
        if ma_cross_date is None:
            return []
        
        kdj_cross_date = self._find_cross_date(lookback_df, 'kdj_cross_signal')
        if kdj_cross_date is None:
            return []
        
        macd_cross_date = self._find_cross_date(lookback_df, 'macd_cross_signal')
        if macd_cross_date is None:
            return []
        
        # 检查共振条件
        if not self._check_resonance(ma_cross_date, kdj_cross_date, macd_cross_date):
            return []
        
        # 关键日期：三个金叉中最早的一个
        # 确保日期是datetime类型
        dates = []
        for d in [ma_cross_date, kdj_cross_date, macd_cross_date]:
            if isinstance(d, str):
                dates.append(pd.to_datetime(d))
            else:
                dates.append(d)
        key_date = min(dates)
        
        # 所有条件都满足，生成选股信号
        # 格式化关键日期，只保留日期部分
        if hasattr(key_date, 'strftime'):
            key_date_str = key_date.strftime('%Y-%m-%d')
        else:
            key_date_str = str(key_date)[:10]
        
        signal_info = {
            'date': latest_date,
            'close': round(latest['close'], 2),
            'key_date': key_date_str,
            'key_date_type': '多金叉共振日',
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
            'short_term_trend': round(latest['short_term_trend'], 2),
            'bull_bear_line': round(latest['bull_bear_line'], 2),
            'reasons': ['均线金叉', 'KDJ金叉', 'MACD金叉', '多指标共振']
        }
        
        return [signal_info]
    
    def _find_cross_date(self, df, signal_column) -> str:
        """
        查找金叉日期 - 优化版本
        
        使用argmax找到第一个True值的索引
        
        参数:
            df: 回溯期间的数据
            signal_column: 信号列名
        
        返回:
            金叉发生的日期，如果没有找到则返回None
        """
        signal_series = df[signal_column]
        if not signal_series.any():
            return None
        
        # 找到第一个金叉的位置
        cross_idx = signal_series.values.argmax()
        if signal_series.iloc[cross_idx]:
            return df.iloc[cross_idx]['date']
        return None
    
    def _check_resonance(self, ma_cross_date, kdj_cross_date, macd_cross_date) -> bool:
        """
        检查共振条件 - 优化版本
        
        使用更简单的时间差计算
        
        返回：是否满足共振条件
        """
        if ma_cross_date is None or kdj_cross_date is None or macd_cross_date is None:
            return False
        
        # 确保日期是datetime类型
        dates = []
        for d in [ma_cross_date, kdj_cross_date, macd_cross_date]:
            if isinstance(d, str):
                dates.append(pd.to_datetime(d))
            else:
                dates.append(d)
        
        # 找到最早和最晚的日期
        max_diff = abs((max(dates) - min(dates)).days)
        
        return max_diff <= self.params['resonance_days']
    
    def _calculate_max_time_diff(self, ma_cross_date, kdj_cross_date, macd_cross_date) -> int:
        """
        计算最大时间差 - 优化版本
        """
        if ma_cross_date is None or kdj_cross_date is None or macd_cross_date is None:
            return 0
        
        # 确保日期是datetime类型
        dates = []
        for d in [ma_cross_date, kdj_cross_date, macd_cross_date]:
            if isinstance(d, str):
                dates.append(pd.to_datetime(d))
            else:
                dates.append(d)
        
        return abs((max(dates) - min(dates)).days)
