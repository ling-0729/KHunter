"""
底部趋势拐点策略 - 识别股票在深度下跌后出现反转的拐点

选股条件（三个条件都必须满足）：
1. 深度下跌：从半年内最高点计算，下跌幅度超过45%
2. MACD底背离：股票价格创新低，但MACD指标不创新低
3. 放量反弹：涨幅超过8%，当日成交量是前十日成交量均值的2.5倍以上

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


class BottomTrendInflectionStrategy(BaseStrategy):
    """底部趋势拐点策略 - 识别股票在深度下跌后出现反转的拐点"""
    
    def __init__(self, params=None):
        """
        初始化策略
        :param params: 策略参数
        """
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
        
        参数：
            df: 股票数据DataFrame（倒序，从新到旧，最新在index=0）
        
        返回：
            计算后的DataFrame，包含以下列：
            - DIF：12日EMA - 26日EMA
            - DEA：DIF的9日EMA
            - MACD：DIF - DEA
            - volume_ma：成交量均线
        
        注意：
            - 数据按倒序排列（从新到旧）
            - 计算时需要转换为正序（从旧到新）
        """
        result = df.copy()
        
        # 转换为正序（从旧到新）用于计算指标
        result = result.sort_values('date', ascending=True).reset_index(drop=True)
        
        # 计算MACD指标
        # DIF = 12日EMA - 26日EMA
        ema_12 = result['close'].ewm(span=12, adjust=False).mean()
        ema_26 = result['close'].ewm(span=26, adjust=False).mean()
        result['DIF'] = ema_12 - ema_26
        
        # DEA = DIF的9日EMA
        result['DEA'] = result['DIF'].ewm(span=9, adjust=False).mean()
        
        # MACD = DIF - DEA
        result['MACD'] = result['DIF'] - result['DEA']
        
        # 计算成交量均线
        volume_ma_period = self.params['volume_ma_period']
        result['volume_ma'] = result['volume'].shift(1).rolling(
            window=volume_ma_period, min_periods=1
        ).mean()
        
        # 恢复倒序（从新到旧）
        result = result.sort_values('date', ascending=False).reset_index(drop=True)
        
        return result
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别底部趋势拐点
        
        参数：
            df: 股票数据DataFrame（倒序，从新到旧，最新在index=0）
            stock_name: 股票名称
        
        返回：
            选股信号列表
        
        数据顺序说明：
            - df是倒序的（从新到旧），最新数据在index=0
            - 使用iloc[0]获取最新数据，iloc[-1]获取最旧数据
        """
        # 基本检查
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
        
        # 快速过滤：检查是否满足深度下跌条件（使用原始数据，避免计算指标）
        # 这样可以在计算复杂指标前快速排除不符合条件的股票
        if not self._quick_check_deep_decline(df):
            return []
        
        # 计算指标（只调用一次）
        df_with_indicators = self.calculate_indicators(df)
        
        # 获取最新一天的数据
        latest = df_with_indicators.iloc[0]
        latest_date = latest['date']
        
        # 检查最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 获取回溯期间的数据
        lookback_days = self.params['lookback_days']
        lookback_df = df_with_indicators.head(lookback_days)
        
        # 检查三个条件
        # 条件1：深度下跌（下跌幅度 > 45%）
        if not self._check_deep_decline(lookback_df):
            return []
        
        # 条件2：MACD底背离
        if not self._check_macd_divergence(lookback_df):
            return []
        
        # 条件3：放量反弹（需要在最近10个交易日内发生）
        volume_surge_result = self._check_volume_surge(df_with_indicators)
        if not volume_surge_result:
            return []
        
        # 获取放量长阳日的日期
        key_date = volume_surge_result if isinstance(volume_surge_result, str) else latest_date
        
        # 格式化日期
        if hasattr(key_date, 'strftime'):
            key_date_str = key_date.strftime('%Y-%m-%d')
        else:
            key_date_str = str(key_date)[:10]
        
        # 三个条件都满足，生成选股信号
        signal_info = {
            'key_date': key_date_str,
            'key_date_type': '放量长阳日',
            'reasons': ['深度下跌45%以上', 'MACD底背离', '放量反弹']
        }
        
        return [signal_info]
    
    def _check_deep_decline(self, df) -> bool:
        """
        检查条件1：深度下跌
        
        判断逻辑：
        - 数据按倒序排列（从新到旧）
        - 找到最高价出现的位置
        - 然后在该位置之后（时间上更近）找最低价
        - 计算下跌幅度 = (最高价 - 最低价) / 最高价
        - 判断下跌幅度是否 > 45%
        
        参数：
            df: 回溯期间的数据（倒序）
        
        返回：
            True 如果满足深度下跌条件，否则 False
        """
        if df.empty or len(df) < 2:
            return False
        
        # 找到最高价出现的位置
        highest_pos = df['high'].argmax()
        highest_price = df['high'].iloc[highest_pos]
        
        # 如果没有找到有效的最高价，返回False
        if pd.isna(highest_price) or highest_price <= 0:
            return False
        
        # 在最高价之后（时间上更近）找最低价
        # 从最高价位置到最新一天的数据中找最低价
        after_highest = df.iloc[:highest_pos]
        
        if after_highest.empty:
            return False
        
        lowest_price = after_highest['low'].min()
        
        # 计算下跌幅度
        decline_ratio = (highest_price - lowest_price) / highest_price
        
        # 判断是否满足条件
        return decline_ratio > self.params['decline_threshold']
    
    def _quick_check_deep_decline(self, df) -> bool:
        """
        快速检查：深度下跌（在计算指标前进行）
        
        这个方法在计算指标前快速检查是否满足深度下跌条件
        使用原始数据，避免不必要的指标计算
        
        参数：
            df: 原始股票数据（倒序）
        
        返回：
            True 如果满足深度下跌条件，否则 False
        """
        if df.empty or len(df) < self.params['lookback_days']:
            return False
        
        # 获取回溯期间的数据
        lookback_days = self.params['lookback_days']
        lookback_df = df.head(lookback_days)
        
        # 找到最高价出现的位置
        highest_pos = lookback_df['high'].argmax()
        highest_price = lookback_df['high'].iloc[highest_pos]
        
        # 如果没有找到有效的最高价，返回False
        if pd.isna(highest_price) or highest_price <= 0:
            return False
        
        # 在最高价之后（时间上更近）找最低价
        after_highest = lookback_df.iloc[:highest_pos]
        
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
        
        参数：
            df: 回溯期间的数据（倒序）
        
        返回：
            True 如果存在MACD底背离，否则 False
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
    
    def _check_volume_surge(self, df):
        """
        检查条件3：放量反弹
        
        判断逻辑：
        - 在最近10个交易日内寻找放量反弹
        - 放量反弹定义：
          1. 涨幅 > 8%
          2. 成交量 >= 2.5倍前10日均量
        
        参数：
            df: 完整的股票数据（倒序）
        
        返回：
            - 如果满足条件，返回放量长阳日的日期字符串
            - 如果不满足条件，返回False
        """
        if df.empty or len(df) < 11:
            return False
        
        # 获取最近10个交易日的数据（包括当前一天）
        recent_10_days = df.head(11)
        
        # 遍历最近10个交易日，寻找放量反弹
        for i in range(len(recent_10_days) - 1):
            current_day = recent_10_days.iloc[i]
            prev_day = recent_10_days.iloc[i + 1]
            
            # 检查数据有效性
            if pd.isna(current_day['close']) or pd.isna(current_day['volume']):
                continue
            if pd.isna(prev_day['close']) or pd.isna(prev_day['volume']) or prev_day['volume'] <= 0:
                continue
            if pd.isna(current_day['volume_ma']) or current_day['volume_ma'] <= 0:
                continue
            
            # 计算涨幅
            price_increase = (current_day['close'] - prev_day['close']) / prev_day['close']
            
            # 检查涨幅条件
            price_increase_threshold = self.params['price_increase_threshold']
            if price_increase <= price_increase_threshold:
                continue
            
            # 检查成交量条件
            volume_ratio = current_day['volume'] / current_day['volume_ma']
            volume_ratio_threshold = self.params['volume_ratio_threshold']
            
            if volume_ratio >= volume_ratio_threshold:
                # 检查起涨点距离条件
                # 找到最近的最低点
                lookback_days = self.params['lookback_days']
                recent_data = df.head(lookback_days)
                lowest_price = recent_data['low'].min()
                
                # 计算起涨点距离
                if lowest_price > 0:
                    distance_ratio = (current_day['close'] - lowest_price) / lowest_price
                else:
                    distance_ratio = 0
                
                # 距离要求：起涨点距离最低点 <= 15%
                if distance_ratio <= 0.15:
                    # 检查回调支撑条件：放量长阳后回调不低于长阳线开盘价
                    # 获取放量长阳日之后到今天的数据
                    surge_day_idx = df[df['date'] == current_day['date']].index
                    if not surge_day_idx.empty:
                        surge_day_pos = surge_day_idx[0]
                        # 从放量长阳日到今天（最新交易日）
                        after_surge = df.iloc[:surge_day_pos]
                        
                        if not after_surge.empty:
                            # 获取放量长阳日的开盘价作为支撑位
                            support_price = current_day['open']
                            # 检查所有交易日的最低价
                            all_above_support = (after_surge['low'] >= support_price).all()
                            
                            if all_above_support:
                                # 找到放量反弹，返回日期
                                return str(current_day['date'])
        
        return False
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []
        
        # 条件1：深度下跌
        decline_threshold = self.params['decline_threshold'] * 100
        lookback_days = self.params['lookback_days']
        criteria.append(f"1. 深度下跌：从最近{lookback_days}个交易日内的最高点下跌幅度超过{decline_threshold:.0f}%")
        
        # 条件2：MACD底背离
        macd_divergence_days = self.params['macd_divergence_days']
        criteria.append(f"2. MACD底背离：在最近{macd_divergence_days}个交易日内，价格创新低但MACD不创新低")
        
        # 条件3：放量反弹
        price_increase_threshold = self.params['price_increase_threshold'] * 100
        volume_ratio_threshold = self.params['volume_ratio_threshold']
        volume_ma_period = self.params['volume_ma_period']
        criteria.append(f"3. 放量反弹：涨幅超过{price_increase_threshold:.0f}%，且成交量是前{volume_ma_period}日均量的{volume_ratio_threshold:.1f}倍以上")
        
        return criteria
