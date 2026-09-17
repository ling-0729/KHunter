"""
底部趋势拐点策略 - 识别股票在深度下跌后出现反转的拐点

选股条件（三个条件都必须满足）：
1. 深度下跌：从半年内最高点计算，下跌幅度超过45%
2. MACD底背离：历史中已形成底背离结构（两次探底，价格新低但MACD不新低）
3. 放量反弹：最近3-5个交易日内出现，涨幅超过8%，成交量是前十日成交量均值的2.5倍以上

核心设计：以"放量长阳日"为锚点，回溯检查：
- C1 深度下跌：以锚点当时的价格计算
- C2 MACD底背离：在锚点之前的历史区间中查找已形成的底背离结构
- 放量长阳日限定在最近3-5个交易日内，避免信号过于陈旧

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
            'macd_divergence_days': 20,        # MACD底背离判断的时间窗口（交易日）
            'surge_search_start': 3,           # 放量长阳搜索起始偏移（第3个交易日起）
            'surge_search_end': 5,             # 放量长阳搜索结束偏移（第5个交易日止）
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
        
        # 计算成交量均线（前N日均量，排除当日）
        volume_ma_period = self.params['volume_ma_period']
        result['volume_ma'] = result['volume'].shift(1).rolling(
            window=volume_ma_period, min_periods=1
        ).mean()
        
        # 恢复倒序（从新到旧）
        result = result.sort_values('date', ascending=False).reset_index(drop=True)
        
        return result
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 以放量长阳日为锚点，回溯检查深度下跌和MACD底背离
        
        核心流程：
        1. 快速检查深度下跌（性能过滤）
        2. 计算指标
        3. 寻找放量长阳日（涨幅>8% + 量比>=2.5 的最近交易日）
        4. 以放量长阳日为锚点回溯：
           a. 检查深度下跌（从锚点前120天最高点计算）
           b. 检查MACD底背离（锚点之前的历史中已形成底背离结构）
           c. 检查起涨点距离（距120日内最低点<=15%）
           d. 检查回调支撑（放量长阳后收盘价未破开盘价）
        
        参数：
            df: 股票数据DataFrame（倒序，从新到旧，最新在index=0）
            stock_name: 股票名称
        
        返回：
            选股信号列表
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
        
        # 快速过滤：检查是否满足深度下跌条件（性能优化，使用原始数据）
        if not self._quick_check_deep_decline(df):
            return []
        
        # 计算指标（只调用一次）
        df_with_indicators = self.calculate_indicators(df)
        
        # 检查最新一天是否有有效交易
        latest = df_with_indicators.iloc[0]
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # Step 1: 寻找放量长阳日（最近3-5个交易日内）
        surge_result = self._find_volume_surge(df_with_indicators)
        if not surge_result:
            return []
        
        surge_date_str, surge_pos, surge_row = surge_result
        lookback_days = self.params['lookback_days']
        
        # Step 2: 以放量长阳日为锚点，截取锚点之前的数据用于C1/C2检查
        # 数据倒序排列，surge_pos是放量日在df中的索引位置
        # 截取从放量日开始、往前lookback_days天的数据
        anchor_df = df_with_indicators.iloc[surge_pos: surge_pos + lookback_days]
        
        if anchor_df.empty or len(anchor_df) < self.params['macd_divergence_days']:
            return []
        
        # Step 3: 检查条件1 - 深度下跌（从锚点回溯120天）
        if not self._check_deep_decline(anchor_df):
            return []
        
        # Step 4: 检查条件2 - MACD底背离（锚点之前20日已形成底背离结构）
        if not self._check_macd_divergence(anchor_df):
            return []
        
        # 所有条件满足，生成选股信号
        signal_info = {
            'key_date': surge_date_str,
            'key_date_type': '放量长阳日',
            'reasons': ['深度下跌45%以上', 'MACD底背离', '放量反弹']
        }
        
        return [signal_info]
    
    def _find_volume_surge(self, df):
        """
        在最近 surge_search_start ~ surge_search_end 个交易日内寻找放量长阳日
        
        放量长阳定义：
        1. 当日涨幅 > 8%（相对前一日收盘）
        2. 当日量比 >= 2.5（相对前10日均量）
        
        子条件（在找到放量日后验证）：
        - 起涨点距120日最低点 <= 15%
        - 放量日后收盘价未有效跌破长阳开盘价（支撑验证）
        
        搜索范围：
        - 跳过最近 surge_search_start-1 天，从第 surge_search_start 天开始
        - 最远搜索到第 surge_search_end 天
        - 默认 3~5：只检查第3、4、5个交易日（0=最新，跳过最近2天）
        
        参数：
            df: 完整的股票数据（倒序，包含指标列）
        
        返回：
            - (surge_date_str, surge_pos, surge_row) 元组 如果找到
            - None 如果未找到
        """
        surge_start = self.params['surge_search_start']  # 如 3
        surge_end = self.params['surge_search_end']      # 如 5
        
        # 需要 surge_end+1 天数据（候选日 + 1 天用于计算涨幅）
        if df.empty or len(df) <= surge_end:
            return None
        
        lookback_days = self.params['lookback_days']
        price_threshold = self.params['price_increase_threshold']
        vol_threshold = self.params['volume_ratio_threshold']
        
        # 遍历第 surge_start ~ surge_end 个交易日（0-based: surge_start-1 到 surge_end-1）
        for i in range(surge_start - 1, surge_end):
            if i >= len(df) - 1:
                break
            
            current_day = df.iloc[i]
            prev_day = df.iloc[i + 1]
            
            # 检查数据有效性
            if pd.isna(current_day['close']) or pd.isna(current_day['volume']):
                continue
            if pd.isna(prev_day['close']) or pd.isna(prev_day['volume']) or prev_day['volume'] <= 0:
                continue
            if pd.isna(current_day['volume_ma']) or current_day['volume_ma'] <= 0:
                continue
            
            # 计算当日涨幅（相对前一日收盘）
            price_increase = (current_day['close'] - prev_day['close']) / prev_day['close']
            if price_increase <= price_threshold:
                continue
            
            # 计算量比（当日成交量 / 前10日均量）
            volume_ratio = current_day['volume'] / current_day['volume_ma']
            if volume_ratio < vol_threshold:
                continue
            
            # 放量长阳日在df中的位置即为 i
            surge_pos = i
            
            # 子条件检查1: 起涨点距最低点距离
            anchor_data = df.iloc[surge_pos: surge_pos + lookback_days]
            if anchor_data.empty:
                continue
            lowest_price = anchor_data['low'].min()
            
            if lowest_price > 0:
                distance_ratio = (current_day['close'] - lowest_price) / lowest_price
            else:
                distance_ratio = float('inf')
            
            if distance_ratio > 0.15:
                continue
            
            # 子条件检查2: 回调支撑条件
            support_price = current_day['open']
            
            # 放量日之后到最新日之间的数据（索引更小的行）
            if surge_pos > 0:
                after_surge = df.iloc[:surge_pos]
                # 检查放量日后每个交易日的收盘价是否都不低于长阳开盘价
                if (after_surge['close'] < support_price).any():
                    continue
            
            # 所有子条件通过
            surge_date_str = str(current_day['date'])
            if len(surge_date_str) > 10:
                surge_date_str = surge_date_str[:10]
            return (surge_date_str, surge_pos, current_day)
        
        return None
    
    def _check_deep_decline(self, df) -> bool:
        """
        检查条件1：深度下跌
        
        判断逻辑：
        - 数据按倒序排列（从新到旧，锚点在index=0）
        - 找到最高价出现的位置
        - 在最高价之后（时间上更近，向锚点方向）找最低价
        - 计算下跌幅度 = (最高价 - 最低价) / 最高价
        - 判断下跌幅度是否 > 45%
        
        参数：
            df: 以锚点为起点的回溯数据（倒序，锚点在index=0）
        
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
        
        # 在最高价之后（时间上更近，即锚点方向）找最低价
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
        快速检查：深度下跌（在计算指标前进行，性能优化）
        
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
        - 检查放量长阳日之前20个交易日内是否出现过MACD底背离
        - 底背离定义：两次探底，后一次价格更低，但MACD柱更高（不创新低）
        
        方法：
        - 排除锚点（放量日），取放量日之前20日数据
        - 分为前后两段（各10日），各找最低价点
        - 后半段最低价更低、且MACD更高 → 底背离成立
        
        参数：
            df: 以锚点为起点的回溯数据（倒序，锚点在index=0）
        
        返回：
            True 如果放量日前20日内存在MACD底背离
        """
        if df.empty or len(df) < 22:  # 至少需要锚点 + 20日前数据
            return False
        
        divergence_days = self.params['macd_divergence_days']
        # 排除锚点（放量长阳日），取放量日之前 divergence_days 天数据
        pre_surge_df = df.iloc[1: 1 + divergence_days]
        
        if pre_surge_df.empty or len(pre_surge_df) < 10:
            return False
        
        # 转为正序（从旧到新），便于按时间分段分析
        recent_df = pre_surge_df.sort_values('date', ascending=True).reset_index(drop=True)
        
        # 分为前后两半段，各约10天
        mid = len(recent_df) // 2
        first_half = recent_df.iloc[:mid]   # 前半段（较早）
        second_half = recent_df.iloc[mid:]  # 后半段（较近）
        
        if first_half.empty or second_half.empty:
            return False
        
        # 找到每半段的价格最低点及其MACD
        first_low = first_half.loc[first_half['low'].idxmin()]
        second_low = second_half.loc[second_half['low'].idxmin()]
        
        # NaN检查
        if pd.isna(first_low['MACD']) or pd.isna(second_low['MACD']):
            return False
        
        # 底背离判断：
        # 1. 后半段最低价 < 前半段最低价 → 价格创新低
        # 2. 后半段MACD柱 > 前半段MACD柱 → MACD不创新低（背离）
        price_lower = second_low['low'] < first_low['low']
        macd_higher = second_low['MACD'] > first_low['MACD']
        
        return price_lower and macd_higher
    
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
        
        # 条件2：MACD底背离（放量长阳日前20日已形成底背离结构）
        macd_divergence_days = self.params['macd_divergence_days']
        criteria.append(f"2. MACD底背离：放量长阳日之前{macd_divergence_days}个交易日内，价格两次探底创新低但MACD未创新低（底背离结构已形成）")
        
        # 条件3：放量反弹（在最近3-5个交易日内）
        price_increase_threshold = self.params['price_increase_threshold'] * 100
        volume_ratio_threshold = self.params['volume_ratio_threshold']
        volume_ma_period = self.params['volume_ma_period']
        surge_start = self.params['surge_search_start']
        surge_end = self.params['surge_search_end']
        criteria.append(f"3. 放量反弹：最近{surge_start}-{surge_end}个交易日内出现，涨幅超过{price_increase_threshold:.0f}%，且成交量是前{volume_ma_period}日均量的{volume_ratio_threshold:.1f}倍以上")
        
        return criteria
