"""
底部趋势拐点策略 - 识别股票在深度下跌后出现反转的拐点

选股条件（三个条件都必须满足）：
1. 深度下跌：从半年内最高点计算，下跌幅度超过45%
2. MACD底背离：股票价格创新低，但MACD指标不创新低
3. 放量反弹：涨停或涨幅超过12%，当日成交量是前十日成交量均值的3倍以上

策略特点：
- 捕捉底部反转机会
- 多指标组合确认
- 严格的选股条件
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import REF


class BottomTrendInflectionStrategy(BaseStrategy):
    """底部趋势拐点策略 - 识别股票在深度下跌后出现反转的拐点"""
    
    def __init__(self, params=None):
        # 默认参数配置
        default_params = {
            'lookback_days': 120,              # 回溯天数（半年交易日）
            'decline_threshold': 0.45,         # 下跌幅度阈值（45%）
            'volume_ratio_threshold': 2.5,     # 成交量倍数阈值（2.5倍，相对于前10日均量）
            'price_increase_threshold': 0.08,  # 涨幅阈值（8%）
            'volume_ma_period': 10,            # 成交量均值周期（10日）
            'macd_divergence_days': 20         # MACD底背离判断的时间窗口（交易日）
        }
        
        # 合并用户参数
        if params:
            default_params.update(params)
        
        super().__init__("底部趋势拐点", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算底部趋势拐点策略所需的指标
        
        计算的指标包括：
        - MACD：用于检测底背离
        - KDJ：用于输出信号
        - 趋势线：用于输出信号
        - 市值：用于输出信号
        """
        result = df.copy()
        
        # 计算MACD指标（用于检测底背离）
        # 确保数据按时间正序排列（从旧到新）
        result = result.sort_values('date', ascending=True).reset_index(drop=True)
        
        # DIF = 12日EMA - 26日EMA
        ema_12 = result['close'].ewm(span=12, adjust=False).mean()
        ema_26 = result['close'].ewm(span=26, adjust=False).mean()
        result['DIF'] = ema_12 - ema_26
        
        # DEA = DIF的9日EMA
        result['DEA'] = result['DIF'].ewm(span=9, adjust=False).mean()
        
        # MACD = DIF - DEA
        result['MACD'] = result['DIF'] - result['DEA']
        
        # 恢复原始顺序（从新到旧）
        result = result.sort_values('date', ascending=False).reset_index(drop=True)
        
        # 计算KDJ指标（与其他策略保持一致）
        from utils.technical import KDJ
        kdj_df = KDJ(result, n=9, m1=3, m2=3)
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']
        
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
        
        # 计算10日均量（用于放量判断）
        # 数据已按从新到旧排列，需要先按时间正序排列，计算后再恢复顺序
        result_sorted = result.sort_values('date', ascending=True).reset_index(drop=True)
        volume_ma_period = self.params['volume_ma_period']
        # 计算前N天的均量（shift(1)表示向后移动1行，即不包括当前行）
        result_sorted['volume_ma'] = result_sorted['volume'].shift(1).rolling(window=volume_ma_period, min_periods=1).mean()
        # 恢复原始顺序（从新到旧）
        result = result_sorted.sort_values('date', ascending=False).reset_index(drop=True)
        
        return result
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别底部趋势拐点
        
        参数说明：
        - lookback_days: 回溯天数，用于寻找底部拐点。设置为120时检查半年内的数据
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
        
        # 检查三个条件
        # 条件1：深度下跌（下跌幅度 > 45%）
        if not self._check_deep_decline(lookback_df):
            return []
        
        # 条件2：MACD底背离
        if not self._check_macd_divergence(lookback_df):
            return []
        
        # 条件3：放量反弹（需要在最近10个交易日内发生）
        if not self._check_volume_surge(df):
            return []
        
        # 三个条件都满足，生成选股信号
        signal_info = {
            'date': latest_date,
            'close': round(latest['close'], 2),
            'J': round(latest['J'], 2),
            'volume_ratio': round(latest['volume'] / latest['volume_ma'], 2) if not pd.isna(latest['volume_ma']) and latest['volume_ma'] > 0 else 1.0,
            'market_cap': round(latest['market_cap'] / 1e8, 2),
            'short_term_trend': round(latest['short_term_trend'], 2),
            'bull_bear_line': round(latest['bull_bear_line'], 2),
            'reasons': ['深度下跌45%以上', 'MACD底背离', '放量反弹']
        }
        
        return [signal_info]
    
    def _check_deep_decline(self, df) -> bool:
        """
        检查条件1：深度下跌
        
        判断逻辑：
        - 数据按从新到旧排列，需要找到高点在前、最低点在后的情况
        - 遍历数据，找到最高价出现的位置
        - 然后在该位置之后（时间上更近）找最低价
        - 计算下跌幅度 = (最高价 - 最低价) / 最高价
        - 判断下跌幅度是否 > 45%
        """
        if df.empty or len(df) < 2:
            return False
        
        # 获取回溯期间的数据
        lookback_days = self.params['lookback_days']
        lookback_df = df.head(lookback_days)
        
        # 找到最高价出现的位置（从后往前找，确保高点在前）
        highest_price = 0
        highest_idx = -1
        
        # 从后往前遍历（从时间上最早的开始），找最高价
        for i in range(len(lookback_df) - 1, -1, -1):
            if lookback_df.iloc[i]['high'] > highest_price:
                highest_price = lookback_df.iloc[i]['high']
                highest_idx = i
        
        # 如果没有找到有效的最高价，返回False
        if highest_idx < 0 or highest_price <= 0:
            return False
        
        # 在最高价之后（时间上更近）找最低价
        # 从最高价位置到最新一天的数据中找最低价
        after_highest = lookback_df.iloc[:highest_idx]
        
        if after_highest.empty:
            return False
        
        lowest_price = after_highest['low'].min()
        
        # 计算下跌幅度
        decline_ratio = (highest_price - lowest_price) / highest_price
        
        # 判断是否满足条件
        return decline_ratio > self.params['decline_threshold']
    
    def _check_macd_divergence(self, df) -> bool:
        """
        检查条件2：MACD底背离
        
        判断逻辑：
        - 在最近20个交易日内，检查是否存在底背离
        - 底背离定义：价格在下降 AND MACD没有继续下降
        - 即：当前价格 < 前N天平均价格 AND 当前MACD > 前N天平均MACD
        """
        if df.empty or len(df) < 2:
            return False
        
        # 获取最近N天的数据（用于判断底背离）
        divergence_days = self.params['macd_divergence_days']
        recent_df = df.head(divergence_days)
        
        if recent_df.empty or len(recent_df) < 2:
            return False
        
        # 获取当前（最新）的数据
        current_close = df.iloc[0]['close']
        current_macd = df.iloc[0]['MACD']
        
        # 检查是否为NaN
        if pd.isna(current_macd) or pd.isna(current_close):
            return False
        
        # 计算前N天的平均价格和平均MACD
        # 排除当前一天，使用前N天的数据
        prev_n_days = recent_df.iloc[1:divergence_days]
        
        if prev_n_days.empty:
            return False
        
        avg_price = prev_n_days['close'].mean()
        avg_macd = prev_n_days['MACD'].mean()
        
        # 检查是否为NaN
        if pd.isna(avg_price) or pd.isna(avg_macd):
            return False
        
        # 判断底背离：价格在下降 AND MACD没有继续下降
        # 价格在下降：当前价格 < 前N天平均价格
        price_declining = current_close < avg_price
        
        # MACD没有继续下降：当前MACD > 前N天平均MACD
        macd_not_declining = current_macd > avg_macd
        
        return price_declining and macd_not_declining
    
    def _check_volume_surge(self, df) -> bool:
        """
        检查条件3：放量反弹
        
        判断逻辑：
        - 在最近10个交易日内寻找放量反弹
        - 放量反弹定义：
          1. 涨幅 > 8% 或涨停（>= 9.5%）
             涨幅 = (当日收盘价 - 前一日收盘价) / 前一日收盘价
          2. 成交量 >= 2.5倍前10日均量
          3. 起涨点（前一天收盘价）距离最低点不超过15%
          4. 放量长阳后回调不低于长阳线开盘价（新增条件）
        """
        if df.empty or len(df) < 11:
            return False
        
        # 获取最近10个交易日的数据（包括当前一天）
        recent_10_days = df.head(11)  # 包括当前一天和前10天
        
        # 遍历最近10个交易日，寻找放量反弹
        for i in range(len(recent_10_days) - 1):
            current_day = recent_10_days.iloc[i]
            prev_day = recent_10_days.iloc[i + 1]
            
            # 检查数据有效性
            if pd.isna(current_day['open']) or pd.isna(current_day['close']) or pd.isna(current_day['volume']):
                continue
            if pd.isna(prev_day['close']) or pd.isna(prev_day['volume']) or prev_day['volume'] <= 0:
                continue
            
            # 检查涨幅条件
            # 涨幅 = (当日收盘价 - 前一日收盘价) / 前一日收盘价
            if prev_day['close'] <= 0:
                continue
            
            price_increase = (current_day['close'] - prev_day['close']) / prev_day['close']
            is_limit_up = price_increase >= 0.095  # 涨停 >= 9.5%
            is_high_increase = price_increase > self.params['price_increase_threshold']
            
            if not (is_limit_up or is_high_increase):
                continue
            
            # 检查成交量条件：与前10日均量相比
            # 使用calculate_indicators中已经计算好的volume_ma
            if pd.isna(current_day['volume_ma']) or current_day['volume_ma'] <= 0:
                continue
            
            volume_ratio = current_day['volume'] / current_day['volume_ma']
            is_volume_surge = volume_ratio >= self.params['volume_ratio_threshold']
            
            if not is_volume_surge:
                continue
            
            # 检查起涨点距离最低点的距离
            # 起涨点是前一天的收盘价
            start_price = prev_day['close']
            
            # 找出反弹发生前的最低点
            # 最低点应该在最高点之后，在起涨点之前
            # 取起涨点（前一天）之前的所有数据中的最低价
            # i+1是前一天的索引，所以要取i+1之后的数据（更早的数据）
            before_data = recent_10_days.iloc[i+1:]
            if before_data.empty:
                lowest_price = start_price
            else:
                # 在反弹前的数据中找最低点
                lowest_price = before_data['low'].min()
            
            # 计算距离
            if lowest_price <= 0:
                continue
            
            distance_ratio = (start_price - lowest_price) / lowest_price
            
            # 判断距离是否不超过15%
            # 这确保起涨点距离最低点不远，说明反弹是从底部开始的
            if distance_ratio <= 0.15:
                # 回调支撑条件：从长阳日到今天，所有天最低价不跌破长阳线开盘价
                # 长阳线的开盘价作为支撑位
                long_yang_open = current_day['open']
                
                # 数据是从新到旧排列的，长阳线之后的天数在原始df中索引更小
                # 在recent_10_days中，i是长阳线索引，0..i-1是长阳线之后的天数
                # 但recent_10_days只有11条，需要用原始df来检查到今天的所有数据
                # current_day的date可以用来定位在原始df中的位置
                long_yang_date = current_day['date']
                # 在原始df中找到长阳日的位置（df是倒序，最新在前）
                # 长阳日之后到今天的数据 = df中索引 < 长阳日索引的所有行
                df_idx = df.index[df['date'] == long_yang_date]
                if len(df_idx) > 0:
                    ly_pos = df_idx[0]
                    # 长阳日之后的数据（更新的天数，索引更小）
                    after_data = df.iloc[:ly_pos]
                    if not after_data.empty:
                        # 检查这些天的最低价是否不低于开盘价
                        min_low = after_data['low'].min()
                        if min_low < long_yang_open:
                            # 回调低于开盘价，不满足条件
                            continue
                
                return True
        
        return False
