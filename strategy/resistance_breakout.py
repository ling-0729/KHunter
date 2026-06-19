"""
阻力位突破策略 - 识别放量长阳突破关键阻力位的信号

策略原理：
1. 阻力位识别：计算前60日最高价作为阻力位
2. 放量长阳突破：在最近3天内搜索涨幅>9%且放量的突破日
3. 回踩支撑：从突破日到今天，不跌破阻力位的98%
4. 均线多头排列：确保股价处于上升趋势中

选股条件：
- 突破日收盘价 >= 前60日最高价（100%突破）
- 突破日涨幅 >= 9%（放量长阳）
- 突破日成交量 >= 前5日均量 × 2.2
- 从突破日到今天，所有天最低价不跌破阻力位的98%
- 长阳日与阻力高点日相隔不少于30个交易日
- 均线多头排列：MA5 > MA10 > MA20
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy


class ResistanceBreakoutStrategy(BaseStrategy):
    """阻力位突破策略 - 识别股价突破关键阻力位的信号"""

    def __init__(self, params=None):
        """初始化策略参数"""
        default_params = {
            'lookback_days': 60,              # 回溯天数
            'breakout_ratio': 0.0,             # 突破阈值（0表示100%）
            'min_change_pct': 0.09,            # 最小涨幅（9%）
            'volume_ratio': 2.2,               # 成交量倍数
            'volume_ma_period': 5,             # 成交量均值周期
            'max_search_days': 3,              # 最大搜索天数（修改为3天）
            'ma_short_period': 5,              # 短期均线周期
            'ma_mid_period': 10,               # 中期均线周期
            'ma_long_period': 20,              # 长期均线周期
        }

        if params:
            default_params.update(params)

        super().__init__("阻力位突破策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """计算指标"""
        result = df.copy()

        # 数据可能是倒序排列，需要转为正序计算指标
        is_descending = False
        if len(result) > 1 and result['date'].iloc[0] > result['date'].iloc[1]:
            is_descending = True
            result = result.iloc[::-1].reset_index(drop=True)

        # 计算阻力位（前N日最高价）
        lookback_days = self.params['lookback_days']
        result['resistance_level'] = result['high'].rolling(window=lookback_days).max()

        # 计算成交量均线
        volume_ma_period = self.params['volume_ma_period']
        result['volume_ma'] = result['volume'].rolling(window=volume_ma_period).mean()

        # 计算成交量比
        result['volume_ratio'] = result['volume'] / result['volume_ma']

        # 计算均线（用于多头排列判断）
        ma_short_period = self.params['ma_short_period']
        ma_mid_period = self.params['ma_mid_period']
        ma_long_period = self.params['ma_long_period']
        result['ma_short'] = result['close'].rolling(window=ma_short_period).mean()
        result['ma_mid'] = result['close'].rolling(window=ma_mid_period).mean()
        result['ma_long'] = result['close'].rolling(window=ma_long_period).mean()

        # 始终返回正序数据
        return result
    
    def get_selection_criteria(self):
        """获取选股条件描述"""
        criteria = []
        min_change_pct = self.params['min_change_pct'] * 100
        volume_ratio = self.params['volume_ratio']
        volume_ma_period = self.params['volume_ma_period']
        max_search_days = self.params['max_search_days']
        lookback_days = self.params['lookback_days']
        breakout_ratio = self.params['breakout_ratio'] * 100
        
        ma_short = self.params['ma_short_period']
        ma_mid = self.params['ma_mid_period']
        ma_long = self.params['ma_long_period']
        
        criteria.append(f"1. 放量长阳日：最近{max_search_days}个交易日内出现涨幅>={min_change_pct:.0f}%的阳线，且成交量是前{volume_ma_period}日均量的{volume_ratio:.1f}倍以上")
        criteria.append(f"2. 阻力位突破：长阳日收盘价突破该日前{lookback_days}日最高价的{100+breakout_ratio:.0f}%以上")
        criteria.append(f"3. 高点间隔：长阳日与阻力高点日相隔不少于30个交易日")
        criteria.append(f"4. 回踩支撑：从长阳日到今天，所有天的最低价不跌破长阳日收盘价的95%")
        criteria.append(f"5. 均线多头排列：MA{ma_short} > MA{ma_mid} > MA{ma_long}")
        
        return criteria

    def quick_filter(self, df) -> bool:
        """快速过滤"""
        if df is None or df.empty or len(df) < 5:
            return False
        
        max_search_days = self.params['max_search_days']
        # df 是倒序的（最新在前），所以使用 head() 获取最近的数据
        recent_df = df.head(max_search_days + 1)
        
        # 计算涨跌幅（倒序数据，所以使用 pct_change(-1)）
        pct_change = recent_df['close'].pct_change(-1)
        min_change_pct = self.params['min_change_pct']
        
        return bool((pct_change >= min_change_pct).any())

    def select_stocks(self, df, stock_name='') -> list:
        """选股逻辑"""
        # 数据检查
        if df is None or df.empty or len(df) < 70:
            return []

        # 检查数据是否过时（最新数据距今超过5年）
        try:
            from datetime import datetime
            latest_date_str = str(df.iloc[-1]['date']).split()[0]  # 只取日期部分
            latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d')
            current_date = datetime.now()
            days_diff = (current_date - latest_date).days
            # 如果最新数据超过5年前，认为是已退市股票
            if days_diff > 365 * 5:
                return []
        except Exception:
            pass

        # 快速预检查：检查是否有放量长阳线
        max_search_days = self.params['max_search_days']
        # df 是正序的（最新在最后），所以使用 tail() 获取最近的数据
        recent_df = df.tail(max_search_days + 1)
        
        # 计算涨跌幅
        pct_change = recent_df['close'].pct_change()
        min_change_pct = self.params['min_change_pct']
        if not (pct_change >= min_change_pct).any():
            return []
        
        # 检查成交量是否放大
        volume_ma_period = self.params['volume_ma_period']
        recent_df_copy = recent_df.copy()
        # recent_df 已经是正序的，直接计算均线
        recent_df_copy['volume_ma'] = recent_df_copy['volume'].rolling(window=volume_ma_period, min_periods=1).mean()
        
        volume_ratio = recent_df_copy['volume'] / recent_df_copy['volume_ma']
        volume_ratio_threshold = self.params['volume_ratio']
        if not (volume_ratio >= volume_ratio_threshold).any():
            return []

        # 获取最新数据
        latest = df.iloc[-1]
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []

        # 检查均线多头排列
        if not self._check_ma_bullish(df):
            return []

        # 搜索放量长阳突破日
        breakout_pos = self._find_breakout_day(df)
        if breakout_pos is None:
            return []

        # 检查回踩支撑
        if not self._check_pullback(df, breakout_pos):
            return []

        # 生成选股信号
        signal = self._generate_signal(df, latest, breakout_pos)
        return [signal]

    def _find_breakout_day(self, df):
        """搜索放量长阳突破日"""
        lookback = self.params['lookback_days']
        ratio = self.params['breakout_ratio']
        min_chg = self.params['min_change_pct']
        vol_ratio = self.params['volume_ratio']
        vol_period = self.params['volume_ma_period']
        max_search = self.params['max_search_days']
        n = len(df)
        
        # 新增：阻力高点间隔天数
        min_resistance_gap = 30

        # 搜索范围：最近max_search_days天
        latest_candidate = n - 1
        earliest_candidate = max(lookback, n - max_search)

        # 从最近的候选日往前搜索
        for idx in range(latest_candidate, earliest_candidate - 1, -1):
            day_close = df['close'].iloc[idx]

            # 条件1：涨幅 >= min_change_pct
            if idx < 1:
                continue
            prev_close = df['close'].iloc[idx - 1]
            if prev_close <= 0 or pd.isna(prev_close):
                continue
            change_pct = (day_close - prev_close) / prev_close
            if change_pct < min_chg:
                continue

            # 条件2：放量
            vol_start = idx - vol_period
            if vol_start < 0:
                continue
            day_vol = df['volume'].iloc[idx]
            vol_ma = df['volume'].iloc[vol_start:idx].mean()
            if vol_ma <= 0 or day_vol < vol_ma * vol_ratio:
                continue

            # 条件3：突破阻力位
            res_start = idx - lookback
            if res_start < 0:
                continue
            resistance = df['high'].iloc[res_start:idx].max()
            if resistance <= 0:
                continue
            if day_close < resistance * (1 + ratio):
                continue
            
            # 条件4：长阳日与阻力高点日相隔不少于min_resistance_gap交易日
            # 找到前lookback日内最高价出现的位置
            resistance_high_idx = df['high'].iloc[res_start:idx].idxmax()
            gap_days = idx - resistance_high_idx
            if gap_days < min_resistance_gap:
                continue

            # 找到突破日
            return idx

        return None

    def _check_ma_bullish(self, df) -> bool:
        """检查均线多头排列：MA短期 > MA中期 > MA长期"""
        try:
            # 获取均线周期参数
            ma_short_period = self.params['ma_short_period']
            ma_mid_period = self.params['ma_mid_period']
            ma_long_period = self.params['ma_long_period']
            
            # 计算均线（确保数据是正序的）
            df_copy = df.copy()
            if len(df_copy) > 1 and df_copy['date'].iloc[0] > df_copy['date'].iloc[-1]:
                df_copy = df_copy.iloc[::-1].reset_index(drop=True)
            
            # 计算均线
            ma_short = df_copy['close'].rolling(window=ma_short_period).mean().iloc[-1]
            ma_mid = df_copy['close'].rolling(window=ma_mid_period).mean().iloc[-1]
            ma_long = df_copy['close'].rolling(window=ma_long_period).mean().iloc[-1]
            
            # 检查是否存在NaN值
            if pd.isna(ma_short) or pd.isna(ma_mid) or pd.isna(ma_long):
                return False
            
            # 检查多头排列：MA短期 > MA中期 > MA长期
            return ma_short > ma_mid > ma_long
        
        except Exception as e:
            return False

    def _check_pullback(self, df, breakout_pos) -> bool:
        """检查回踩支撑"""
        n = len(df)

        # 阻力位（突破前lookback日内最高点）的98%作为支撑位（允许回调不超过2%）
        lookback = self.params['lookback_days']
        res_start = breakout_pos - lookback
        if res_start < 0:
            res_start = 0
        resistance = df['high'].iloc[res_start:breakout_pos].max()
        support_level = resistance * 0.98
        if resistance <= 0 or pd.isna(resistance):
            return False

        # 如果突破日就是最后一天，无需检查回踩
        if breakout_pos >= n - 1:
            return True

        # 检查突破日次日到最后一天的所有最低价
        hold_lows = df['low'].iloc[breakout_pos + 1:]
        if len(hold_lows) == 0:
            return True
        min_low = hold_lows.min()

        # 最低价不能跌破阻力位的98%
        return bool(min_low >= support_level)

    def _generate_signal(self, df, latest, breakout_pos) -> dict:
        """生成选股信号"""
        lookback = self.params['lookback_days']
        
        # 计算突破日的阻力位
        res_start = breakout_pos - lookback
        resistance = df['high'].iloc[res_start:breakout_pos].max()
        breakout_day = df.iloc[breakout_pos]

        # 生成选股原因
        reasons = self._generate_reasons(df, breakout_pos)

        # 突破幅度
        br = (breakout_day['close'] - resistance) / resistance

        # 突破后经过的天数
        days_since = len(df) - 1 - breakout_pos

        # 关键日期：突破日
        key_date = breakout_day['date']
        if hasattr(key_date, 'strftime'):
            key_date_str = key_date.strftime('%Y-%m-%d')
        else:
            key_date_str = str(key_date)[:10]
        
        # 构建选股信号
        signal_info = {
            'key_date': key_date_str,
            'key_date_type': '阻力位突破日',
            'price': float(latest['close']),
            'resistance': float(resistance),
            'breakout_ratio': float(br),
            'days_since_breakout': int(days_since),
            'reasons': reasons
        }
        return signal_info

    def _generate_reasons(self, df, breakout_pos) -> list:
        """生成选股原因列表"""
        reasons = []
        lookback = self.params['lookback_days']
        vol_period = self.params['volume_ma_period']

        # 突破日数据和阻力位
        res_start = breakout_pos - lookback
        resistance = df['high'].iloc[res_start:breakout_pos].max()
        bd = df.iloc[breakout_pos]

        # 原因1：放量长阳突破阻力位
        bd_idx = breakout_pos
        if bd_idx >= 1:
            prev_close = df['close'].iloc[bd_idx - 1]
            change_pct = (bd['close'] - prev_close) / prev_close * 100
        else:
            change_pct = 0
        reasons.append(
            f"放量长阳突破{lookback}日阻力位{resistance:.2f}，涨幅{change_pct:.1f}%"
        )

        # 原因2：突破日成交量放大
        vs = breakout_pos - vol_period
        if vs >= 0:
            vma = df['volume'].iloc[vs:breakout_pos].mean()
            if vma > 0:
                vr = bd['volume'] / vma
                reasons.append(f"突破日成交量放大{vr:.1f}倍")

        # 原因3：回踩不破支撑位（阻力位的98%）
        days_since = len(df) - 1 - breakout_pos
        if days_since > 0:
            rmin = df['low'].iloc[breakout_pos + 1:].min()
            # 阻力位（突破前lookback日内最高点）的98%作为支撑位
            support_level = resistance * 0.98
            reasons.append(
                f"突破后{days_since}天回踩最低{rmin:.2f}，未破支撑位{support_level:.2f}"
            )
        else:
            reasons.append(f"今日放量长阳突破，收盘价{bd['close']:.2f}")

        return reasons
