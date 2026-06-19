"""
趋势共振反转策略 - 多指标共振底部反转

指标定义：
1. RSI突破信号：RSI(14)从超卖区域（30以下）突破至中性区域（50以上）
   - 表示股价从超卖状态转为中性偏强

2. 均线金叉信号：5日均线向上穿越20日均线
   - 表示短期趋势转强

3. MACD金叉信号：DIF线上穿DEA线
   - 表示动能转强

选股条件：
- RSI从30以下突破至50以上
- 5日均线上穿20日均线
- DIF线上穿DEA线
- 三个信号在3个交易日内发生（时间共振）
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import MA, MACD, RSI


class TrendResonanceReversalStrategy(BaseStrategy):
    """趋势共振反转策略 - 多指标共振底部反转"""
    
    def __init__(self, params=None):
        # 默认参数
        default_params = {
            # RSI参数
            'rsi_period': 14,           # RSI计算周期
            'rsi_oversold': 30,         # RSI超卖阈值
            'rsi_breakout': 50,         # RSI突破阈值
            
            # 均线参数
            'short_ma_period': 5,       # 短期均线周期
            'long_ma_period': 20,       # 长期均线周期
            
            # MACD参数
            'macd_fast': 12,            # MACD快线周期
            'macd_slow': 26,            # MACD慢线周期
            'macd_signal': 9,           # MACD信号线周期
            
            # 共振时间参数
            'signal_days': 3,           # 信号共振时间窗口（天）
            'lookback_days': 5,         # 回溯天数
        }
        
        # 合并用户参数
        if params:
            default_params.update(params)
        
        super().__init__("趋势共振反转策略", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算趋势共振反转策略所需的指标
        
        参数：
            df: 股票日线数据DataFrame
        
        返回：
            添加了指标的DataFrame
        """
        result = df.copy()
        
        # 计算RSI指标
        rsi_df = RSI(result, period=self.params['rsi_period'])
        result['rsi'] = rsi_df['rsi']
        
        # 计算均线
        result['ma_short'] = MA(result['close'], self.params['short_ma_period'])
        result['ma_long'] = MA(result['close'], self.params['long_ma_period'])
        
        # 计算MACD指标
        macd_df = MACD(result, 
                      fastperiod=self.params['macd_fast'],
                      slowperiod=self.params['macd_slow'],
                      signalperiod=self.params['macd_signal'])
        result['macd_dif'] = macd_df['macd']          # DIF线
        result['macd_dea'] = macd_df['macd_signal']   # DEA线
        result['macd_hist'] = macd_df['macd_hist']    # MACD柱状图
        
        return result
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []
        
        # 条件1：RSI突破
        rsi_period = self.params['rsi_period']
        rsi_oversold = self.params['rsi_oversold']
        rsi_breakout = self.params['rsi_breakout']
        criteria.append(f"1. RSI突破：RSI({rsi_period})从{rsi_oversold}以下突破至{rsi_breakout}以上")
        
        # 条件2：均线金叉
        short_ma_period = self.params['short_ma_period']
        long_ma_period = self.params['long_ma_period']
        criteria.append(f"2. 均线金叉：{short_ma_period}日均线上穿{long_ma_period}日均线")
        
        # 条件3：MACD金叉
        criteria.append(f"3. MACD金叉：DIF线上穿DEA线")
        
        # 条件4：时间共振
        signal_days = self.params['signal_days']
        criteria.append(f"4. 时间共振：三个信号在最近{signal_days}个交易日内发生")
        
        return criteria
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别趋势共振反转信号
        
        参数：
            df: 股票日线数据DataFrame
            stock_name: 股票名称
        
        返回：
            符合条件的信号列表
        """
        if df.empty or len(df) < 30:
            return []
        
        try:
            # 计算指标
            df = self.calculate_indicators(df)
            
            # 获取参数
            rsi_oversold = self.params['rsi_oversold']
            rsi_breakout = self.params['rsi_breakout']
            signal_days = self.params['signal_days']
            
            # 检查数据是否足够
            if len(df) < 30:
                return []
            
            # 初始化信号标记
            signals = []
            
            # 第一步：在最近signal_days天内寻找RSI突破信号
            # 数据是倒序的（最新在前），所以从索引0开始
            rsi_search_range = min(signal_days, len(df) - 1)
            rsi_breakout_day = None
            
            for i in range(rsi_search_range):
                # 当前RSI >= 突破阈值，且前一日RSI < 突破阈值
                # 且在之前几天内RSI曾经低于超卖阈值
                if (df['rsi'].iloc[i] >= rsi_breakout and 
                    df['rsi'].iloc[i+1] < rsi_breakout):
                    # 检查是否曾经超卖
                    lookback = min(self.params['lookback_days'], len(df) - i - 1)
                    if df['rsi'].iloc[i+1:i+1+lookback].min() <= rsi_oversold:
                        rsi_breakout_day = i
                        break  # 找到最近的RSI突破信号
            
            # 如果没有找到RSI突破信号，直接返回
            if rsi_breakout_day is None:
                return []
            
            # 第二步：在RSI突破信号的前后signal_days天内寻找均线金叉和MACD金叉
            # 扩大搜索范围到signal_days的两倍
            search_range = min(signal_days * 2 + 1, len(df) - 1)
            
            ma_cross_day = None
            macd_cross_day = None
            
            for i in range(search_range):
                # 均线金叉信号检测
                if ma_cross_day is None and i + 1 < len(df):
                    # 当前短期均线 > 长期均线，且前一日短期均线 <= 长期均线
                    if (df['ma_short'].iloc[i] > df['ma_long'].iloc[i] and 
                        df['ma_short'].iloc[i+1] <= df['ma_long'].iloc[i+1]):
                        ma_cross_day = i
                
                # MACD金叉信号检测
                if macd_cross_day is None and i + 1 < len(df):
                    # 当前DIF > DEA，且前一日DIF <= DEA
                    if (df['macd_dif'].iloc[i] > df['macd_dea'].iloc[i] and 
                        df['macd_dif'].iloc[i+1] <= df['macd_dea'].iloc[i+1]):
                        macd_cross_day = i
                
                # 如果两个信号都找到了，提前退出
                if ma_cross_day is not None and macd_cross_day is not None:
                    break
            
            # 第三步：检查三个信号是否在signal_days天内发生
            signal_days_list = [d for d in [rsi_breakout_day, ma_cross_day, macd_cross_day] if d is not None]
            
            if len(signal_days_list) == 3:
                # 三个信号都存在，检查时间间隔
                max_day = max(signal_days_list)
                min_day = min(signal_days_list)
                
                if max_day - min_day <= signal_days:
                    # 时间共振满足条件
                    # 关键日期：RSI突破日
                    key_date = df['date'].iloc[rsi_breakout_day]
                    
                    # 格式化关键日期，只保留日期部分
                    key_date_str = key_date.strftime('%Y-%m-%d') if hasattr(key_date, 'strftime') else str(key_date)[:10]
                    
                    signal = {
                        'stock_code': df['code'].iloc[0] if 'code' in df.columns else stock_name,
                        'stock_name': stock_name,
                        'date': df['date'].iloc[rsi_breakout_day],
                        'key_date': key_date_str,
                        'key_date_type': 'RSI突破日',
                        'rsi_breakout_day': df['date'].iloc[rsi_breakout_day],
                        'ma_cross_day': df['date'].iloc[ma_cross_day],
                        'macd_cross_day': df['date'].iloc[macd_cross_day],
                        'rsi_value': df['rsi'].iloc[rsi_breakout_day],
                        'ma_short': df['ma_short'].iloc[ma_cross_day],
                        'ma_long': df['ma_long'].iloc[ma_cross_day],
                        'macd_dif': df['macd_dif'].iloc[macd_cross_day],
                        'macd_dea': df['macd_dea'].iloc[macd_cross_day],
                        'close': df['close'].iloc[rsi_breakout_day],
                        'reason': f'RSI突破({df["rsi"].iloc[rsi_breakout_day]:.1f}), 均线金叉, MACD金叉'
                    }
                    signals.append(signal)
            
            return signals
            
        except Exception as e:
            import logging
            logging.error(f"趋势共振反转策略选股失败: {str(e)}")
            return []
