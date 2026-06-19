"""
金三角策略 - 均线金叉三角形形态选股策略

形态定义：
- A点：5日均线上穿10日均线
- B点：5日均线上穿20日均线
- C点：10日均线上穿20日均线
- A、B、C三点形成三角形

特殊形态：
- 金蜘蛛：A、B、C三点汇聚于同一天（ac_interval=0）
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from strategy.base_strategy import BaseStrategy


class GoldenTriangleStrategy(BaseStrategy):
    """金三角策略"""

    def __init__(self, params=None):
        default_params = {
            'short_period': 5,
            'mid_period': 10,
            'long_period': 20,
            'super_long_period': 60,
            'ac_interval': 3,
            'c_cross_min_gain': 0.01,
            'c_cross_min_volume_ratio': 1.1,
            'lookback_days': 30,
            'strategy_weight': 50,
        }
        if params:
            default_params.update(params)
        super().__init__("金三角策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """计算技术指标"""
        result = df.copy()
        
        # 检测数据是否为倒序
        is_reversed = len(result) > 1 and str(result['date'].iloc[0]) > str(result['date'].iloc[1])
        
        # 如果是倒序，先反转成正序以便正确计算
        if is_reversed:
            result = result.iloc[::-1].reset_index(drop=True)

        short_period = int(self.params['short_period'])
        mid_period = int(self.params['mid_period'])
        long_period = int(self.params['long_period'])
        super_long_period = int(self.params['super_long_period'])

        result['sma_short'] = result['close'].rolling(window=short_period).mean()
        result['sma_mid'] = result['close'].rolling(window=mid_period).mean()
        result['sma_long'] = result['close'].rolling(window=long_period).mean()
        result['sma_super_long'] = result['close'].rolling(window=super_long_period).mean()
        result['volume_ma5'] = result['volume'].rolling(window=5).mean()

        result['prev_close'] = result['close'].shift(1)
        result['gain'] = (result['close'] - result['prev_close']) / result['prev_close']

        # 注意：不使用ffill()向前填充，避免引入未来函数
        # ffill会使用未来数据填充NaN，导致回测结果失真
        # 如果需要处理缺失数据，应使用bfill()向后填充（使用历史数据）
        # result = result.ffill()  # ⚠️ 这是未来函数！
        
        # 只有原始数据是倒序时才反转回去
        # 如果原始数据是正序，保持正序返回
        if is_reversed:
            result = result.iloc[::-1].reset_index(drop=True)
        
        return result

    def get_selection_criteria(self):
        """获取选股条件描述"""
        return [
            f"1. A点形成：{self.params['short_period']}日均线上穿{self.params['mid_period']}日均线",
            f"2. B点形成：{self.params['short_period']}日均线上穿{self.params['long_period']}日均线",
            f"3. C点形成：{self.params['mid_period']}日均线上穿{self.params['long_period']}日均线",
            f"4. C点涨幅 >= {self.params['c_cross_min_gain']*100}%",
            f"5. C点量能比 >= {self.params['c_cross_min_volume_ratio']}",
            f"6. A-C间隔 <= {self.params['ac_interval']}天",
            f"7. 均线多头排列：MA{self.params['short_period']} >= MA{self.params['mid_period']} >= MA{self.params['long_period']} >= MA{self.params['super_long_period']}",
        ]

    def quick_filter(self, df):
        """快速过滤：检查数据是否足够并进行涨幅过滤"""
        if df is None or df.empty:
            return False
        
        # 数据量检查
        min_length = max(int(self.params['super_long_period']), 60)
        if len(df) < min_length:
            return False
        
        # 获取C点涨幅阈值作为快速过滤标准
        min_gain = float(self.params.get('c_cross_min_gain', 0.01))
        
        # 今日涨幅过滤：必须满足最小涨幅要求
        if len(df) >= 2:
            # 检查日期顺序
            if str(df['date'].iloc[0]) > str(df['date'].iloc[1]):
                # 倒序排列
                latest = df.iloc[0]
                prev_close = df.iloc[1]['close']
            else:
                # 正序排列
                latest = df.iloc[-1]
                prev_close = df.iloc[-2]['close']
            
            if prev_close > 0:
                today_gain = (latest['close'] - prev_close) / prev_close
                # 涨幅 >= c_cross_min_gain（默认1%）
                if today_gain < min_gain:
                    return False
        
        return True

    def select_stocks(self, df, stock_name='') -> list:
        """选股逻辑"""
        # 快速过滤：先排除明显不符合条件的股票
        if not self.quick_filter(df):
            return []

        if stock_name and not self._validate_stock_name(stock_name):
            return []

        df = self.calculate_indicators(df.copy())

        latest_idx = 0
        latest = df.iloc[latest_idx]

        cross_points = self._find_cross_points(df, latest_idx)
        if cross_points is None:
            return []

        a_date, b_date, c_date, a_idx, b_idx, c_idx = cross_points

        # 使用 index 差值计算交易日间隔（数据倒序排列，index越大日期越早）
        ac_interval_days = a_idx - c_idx
        if ac_interval_days > int(self.params['ac_interval']):
            return []

        c_day_data = df.iloc[c_idx]
        c_gain = c_day_data['gain'] if not pd.isna(c_day_data['gain']) else 0
        if c_gain < float(self.params['c_cross_min_gain']):
            return []

        c_volume_ratio = c_day_data['volume'] / c_day_data['volume_ma5'] \
            if c_day_data['volume_ma5'] > 0 else 0
        if c_volume_ratio < float(self.params['c_cross_min_volume_ratio']):
            return []

        sma_short = latest['sma_short']
        sma_mid = latest['sma_mid']
        sma_long = latest['sma_long']
        sma_super_long = latest['sma_super_long']

        if not (sma_short >= sma_mid >= sma_long >= sma_super_long):
            return []

        triangle_type = 'golden_spider' if ac_interval_days == 0 else 'golden_triangle'

        return [{
            'signal': 'buy',
            'reason': f'金三角形态({triangle_type})',
            'date': latest['date'],
            'close': latest['close'],
            'stock_code': '',
            'stock_name': stock_name,
            'triangle_type': triangle_type,
            'cross_details': {
                'a_cross_date': a_date,
                'b_cross_date': b_date,
                'c_cross_date': c_date,
                'c_cross_gain': c_gain,
                'c_cross_volume_ratio': c_volume_ratio,
                'ac_interval_days': ac_interval_days,
            },
            'ma_details': {
                'sma_short': sma_short,
                'sma_mid': sma_mid,
                'sma_long': sma_long,
                'sma_super_long': sma_super_long,
            },
            'pattern_confirmed': True,
            'strategy_weight': self.params['strategy_weight'],
        }]

    def _find_cross_points(self, df, latest_idx) -> Optional[Tuple]:
        """查找A、B、C三个金叉点

        逻辑：今天（index=0）必须满足条件
        - C点：MA10 >= MA20
        - A点（向前查找ac_interval天）：MA5 >= MA10
        - B点（向前查找ac_interval天）：MA5 >= MA20
        
        支持灵活的时间顺序：a <= b <= c
        - A、B、C三点可以在同一天（金蜘蛛）
        - 任意两个点可以在同一天
        - 但必须满足时间顺序（A最早或等于B，B最早或等于C）
        """
        ac_interval = int(self.params['ac_interval'])

        # 需要至少有前一天的数据来检查金叉
        if latest_idx + 1 >= len(df):
            return None

        c_idx = latest_idx
        curr = df.iloc[c_idx]
        prev = df.iloc[c_idx + 1]

        sma_mid_curr = curr['sma_mid']
        sma_long_curr = curr['sma_long']
        sma_mid_prev = prev['sma_mid']
        sma_long_prev = prev['sma_long']

        sma_short_curr = curr['sma_short']
        sma_short_prev = prev['sma_short']

        # 检查C点：MA10上穿MA20
        is_c_point = sma_mid_prev < sma_long_prev and sma_mid_curr >= sma_long_curr
        if not is_c_point:
            return None

        # 检查当天是否满足A点和B点条件（用于支持ABC同一天或AB=C的情况）
        is_a_today = sma_short_prev < sma_mid_prev and sma_short_curr >= sma_mid_curr
        is_b_today = sma_short_prev < sma_long_prev and sma_short_curr >= sma_long_curr

        # 初始化A、B点索引
        a_idx, b_idx = None, None

        # 如果当天满足A点条件，优先使用当天
        if is_a_today:
            a_idx = c_idx
        
        # 如果当天满足B点条件，优先使用当天
        if is_b_today:
            b_idx = c_idx

        # 如果A或B点还未找到，向前查找（从c_idx + 1开始）
        if a_idx is None or b_idx is None:
            search_end = min(c_idx + ac_interval + 2, len(df))
            for i in range(c_idx + 1, search_end):
                if i + 1 >= len(df):
                    continue

                curr_i = df.iloc[i]
                prev_i = df.iloc[i + 1]

                sma_short_curr_i = curr_i['sma_short']
                sma_mid_curr_i = curr_i['sma_mid']
                sma_long_curr_i = curr_i['sma_long']

                sma_short_prev_i = prev_i['sma_short']
                sma_mid_prev_i = prev_i['sma_mid']
                sma_long_prev_i = prev_i['sma_long']

                if a_idx is None:
                    if sma_short_prev_i < sma_mid_prev_i and sma_short_curr_i >= sma_mid_curr_i:
                        a_idx = i

                if b_idx is None:
                    if sma_short_prev_i < sma_long_prev_i and sma_short_curr_i >= sma_long_curr_i:
                        b_idx = i

        # 检查是否找到A、B点
        if a_idx is None or b_idx is None:
            return None

        # 验证时间顺序：a <= c and b <= c（由于数据倒序，索引越大表示时间越早）
        # 所以条件应为：a_idx >= c_idx and b_idx >= c_idx
        if not (a_idx >= c_idx and b_idx >= c_idx):
            return None

        return (
            str(df.iloc[a_idx]['date']).split()[0],
            str(df.iloc[b_idx]['date']).split()[0],
            str(df.iloc[c_idx]['date']).split()[0],
            a_idx, b_idx, c_idx
        )
