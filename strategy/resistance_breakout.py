"""
阻力位突破策略 - 识别放量长阳突破关键阻力位的信号

策略原理：
1. 阻力位识别：计算前60日最高价作为阻力位
2. 放量长阳突破：在最近10天内搜索涨幅>8%且放量的突破日
3. 回踩支撑：从突破日到今天，不跌破突破日开盘价
4. 趋势配合：确认短期趋势是否向上

选股条件：
- 突破日收盘价 >= 前60日最高价 × 0.98（达到阻力位98%即可）
- 突破日涨幅 >= 8%（放量长阳）
- 突破日成交量 >= 前10日均量 × 2.0
- 从突破日到今天，所有天最低价不跌破突破日开盘价
- 短期趋势向上
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import REF, MA


class ResistanceBreakoutStrategy(BaseStrategy):
    """阻力位突破策略 - 识别股价突破关键阻力位的信号"""

    def __init__(self, params=None):
        """初始化策略参数"""
        # 默认参数配置
        default_params = {
            # 阻力位参数
            'lookback_days': 60,              # 回溯天数（默认60天）
            'breakout_ratio': -0.02,          # 突破阈值（-0.02表示达到阻力位98%即可）

            # 突破日条件
            'min_change_pct': 0.08,           # 突破日最小涨幅（默认8%）
            'volume_ratio': 2.0,              # 成交量倍数（默认2.0）
            'volume_ma_period': 10,           # 成交量均值周期（默认10天）

            # 搜索参数
            'max_search_days': 10,            # 最大搜索天数（在最近N天内搜索突破日）

            # 其他参数
            'min_market_cap': 20,             # 最小市值（20亿元）
            'max_market_cap': 1000,           # 最大市值（1000亿元）
        }

        # 合并用户参数
        if params:
            default_params.update(params)

        super().__init__("阻力位突破策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算阻力位突破策略所需的指标
        包括：阻力位、成交量均线、趋势线等
        """
        result = df.copy()

        # 数据可能是倒序排列（最新的在前），需要转为正序计算指标
        is_descending = False
        if len(result) > 1 and result['date'].iloc[0] > result['date'].iloc[1]:
            is_descending = True
            result = result.iloc[::-1].reset_index(drop=True)

        # 计算阻力位（前N日最高价，含当天，用于指标展示）
        lookback_days = self.params['lookback_days']
        result['resistance_level'] = result['high'].rolling(window=lookback_days).max()

        # 计算成交量均线
        volume_ma_period = self.params['volume_ma_period']
        result['volume_ma'] = result['volume'].rolling(window=volume_ma_period).mean()

        # 计算成交量比
        result['volume_ratio'] = result['volume'] / result['volume_ma']

        # 计算突破幅度（基于rolling阻力位，用于指标展示）
        result['breakout_ratio'] = (
            (result['close'] - result['resistance_level']) / result['resistance_level']
        )

        # 计算趋势线（复用知行趋势线组件）
        from utils.technical import calculate_zhixing_trend
        trend_df = calculate_zhixing_trend(
            result, m1=14, m2=28, m3=57, m4=114
        )
        result['short_term_trend'] = trend_df['short_term_trend']
        result['bull_bear_line'] = trend_df['bull_bear_line']

        # 计算市值（如果CSV中有market_cap字段则使用，否则估算）
        if 'market_cap' not in result.columns:
            result['market_cap'] = result['close'] * 2e8

        # 始终返回正序数据（最新在后），方便后续搜索和索引
        return result

    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别阻力位突破信号

        核心流程：
        1. 数据验证和过滤
        2. 在最近一段时间内搜索突破日
        3. 验证突破日的成交量、站稳、回踩、趋势条件
        """
        # 数据验证
        if not self._validate_data(df):
            return []

        # 过滤退市/异常股票
        if stock_name:
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in stock_name for kw in invalid_keywords):
                return []
            # 过滤 ST/*ST 股票
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []

        # 计算指标
        df = self.calculate_indicators(df)

        # 获取最新数据
        latest = df.iloc[-1]

        # 检查最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []

        # 市值过滤
        market_cap = latest['market_cap'] / 1e8  # 转换为亿元
        if market_cap < self.params['min_market_cap'] or market_cap > self.params['max_market_cap']:
            return []

        # 核心：搜索放量长阳突破日（已包含涨幅和放量检查）
        breakout_pos = self._find_breakout_day(df)
        if breakout_pos is None:
            return []

        # 检查条件2：突破后回踩检查（从突破日到今天不跌破突破日开盘价）
        if not self._check_pullback(df, breakout_pos):
            return []

        # 检查条件3：趋势配合
        if not self._check_trend(df):
            return []

        # 生成选股信号
        signal = self._generate_signal(df, latest, market_cap, breakout_pos)
        return [signal]

    def _validate_data(self, df) -> bool:
        """数据验证：检查数据完整性和长度"""
        if df is None or df.empty:
            return False
        # 需要足够的数据来计算所有指标
        min_days = max(
            self.params['lookback_days'],
            self.params['volume_ma_period'], 30, 20
        ) + self.params['max_search_days']
        if len(df) < min_days:
            return False
        # 检查必要字段
        required = ['date', 'open', 'high', 'low', 'close', 'volume']
        for field in required:
            if field not in df.columns:
                return False
        return True

    def _find_breakout_day(self, df):
        """
        在最近max_search_days天内搜索放量长阳突破日。
        突破条件（同时满足）：
        1. 收盘价 >= 该天之前lookback_days日最高价 × (1+breakout_ratio)
        2. 当日涨幅 >= min_change_pct（放量长阳）
        3. 当日放量 >= 前N日均量 × volume_ratio
        突破日距今（含突破日当天）不超过max_search_days天。
        返回突破日在df中的绝对索引位置，未找到返回None。
        """
        lookback = self.params['lookback_days']
        ratio = self.params['breakout_ratio']
        min_chg = self.params['min_change_pct']
        vol_ratio = self.params['volume_ratio']
        vol_period = self.params['volume_ma_period']
        max_search = self.params['max_search_days']
        n = len(df)

        # 搜索范围：最近max_search_days天
        latest_candidate = n - 1
        earliest_candidate = max(lookback, n - max_search)

        # 从最近的候选日往前搜索（优先找最近的突破）
        for idx in range(latest_candidate, earliest_candidate - 1, -1):
            day_close = df['close'].iloc[idx]

            # 条件1：涨幅 >= min_change_pct（相对前一日收盘价）
            if idx < 1:
                continue
            prev_close = df['close'].iloc[idx - 1]
            if prev_close <= 0 or pd.isna(prev_close):
                continue
            change_pct = (day_close - prev_close) / prev_close
            if change_pct < min_chg:
                continue

            # 条件2：收盘价达到阻力位附近
            res_start = idx - lookback
            if res_start < 0:
                continue
            resistance = df['high'].iloc[res_start:idx].max()
            if resistance <= 0:
                continue
            if day_close < resistance * (1 + ratio):
                continue

            # 条件3：放量（突破日成交量 >= 前N日均量 × volume_ratio）
            vol_start = idx - vol_period
            if vol_start < 0:
                continue
            day_vol = df['volume'].iloc[idx]
            vol_ma = df['volume'].iloc[vol_start:idx].mean()
            if vol_ma <= 0 or day_vol < vol_ma * vol_ratio:
                continue

            # 三个条件都满足，找到突破日
            return idx

        return None

    def _check_pullback(self, df, breakout_pos) -> bool:
        """
        检查回踩：从突破日次日到今天（最后一天），所有天的最低价都不跌破突破日开盘价。
        突破日开盘价是多空博弈的起点，跌破说明突破力度不够。
        如果突破日就是今天（最后一天），则无需检查回踩，直接通过。
        """
        n = len(df)

        # 突破日开盘价作为回踩支撑位
        breakout_open = df['open'].iloc[breakout_pos]
        if breakout_open <= 0 or pd.isna(breakout_open):
            return False

        # 如果突破日就是最后一天，没有后续数据需要检查
        if breakout_pos >= n - 1:
            return True

        # 检查突破日次日到最后一天的所有最低价
        hold_lows = df['low'].iloc[breakout_pos + 1:]
        if len(hold_lows) == 0:
            return True
        min_low = hold_lows.min()

        # 最低价不能跌破突破日开盘价
        return bool(min_low >= breakout_open)

    def _check_trend(self, df) -> bool:
        """
        检查趋势配合（复用知行趋势线组件）。
        满足任一即可：
        1. 短期趋势线在多空线上方
        2. 短期趋势线方向向上（当前 > 前一天）
        """
        if len(df) < 3:
            return False
        # 获取最新趋势数据
        cur = df['short_term_trend'].iloc[-1]
        prev = df['short_term_trend'].iloc[-2]
        bb = df['bull_bear_line'].iloc[-1]
        # 数据有效性检查
        if pd.isna(cur) or pd.isna(prev) or pd.isna(bb):
            return False
        # 条件1：趋势线在多空线上方
        above = cur > bb
        # 条件2：趋势线方向向上
        rising = cur > prev
        return bool(above or rising)

    def _generate_signal(self, df, latest, market_cap, breakout_pos) -> dict:
        """
        生成选股信号，基于实际找到的突破日位置。
        """
        lookback = self.params['lookback_days']
        # 计算突破日的阻力位
        res_start = breakout_pos - lookback
        resistance = df['high'].iloc[res_start:breakout_pos].max()
        breakout_day = df.iloc[breakout_pos]

        # 生成选股原因
        reasons = self._generate_reasons(df, breakout_pos)

        # 处理NaN值
        vr = latest['volume_ratio']
        if pd.isna(vr):
            vr = 0
        st = latest['short_term_trend']
        if pd.isna(st):
            st = 0
        bb = latest['bull_bear_line']
        if pd.isna(bb):
            bb = 0
        vm = latest['volume_ma']
        if pd.isna(vm):
            vm = 0

        # 突破幅度（基于突破日）
        br = (breakout_day['close'] - resistance) / resistance

        # 突破后经过的天数
        days_since = len(df) - 1 - breakout_pos

        # 构建选股信号
        signal_info = {
            'date': latest['date'],
            'close': round(latest['close'], 2),
            'resistance_level': round(resistance, 2),
            'breakout_ratio': round(br, 4),
            'volume': int(latest['volume']) if not pd.isna(latest['volume']) else 0,
            'volume_ma': int(vm),
            'volume_ratio': round(vr, 2),
            'short_term_trend': round(st, 2),
            'bull_bear_line': round(bb, 2),
            'market_cap': round(market_cap, 2),
            'breakout_date': breakout_day['date'],
            'days_since_breakout': days_since,
            'reasons': reasons,
            'pattern_details': {
                'resistance_level': round(resistance, 2),
                'breakout_ratio': round(br * 100, 2),
                'volume_ratio': round(vr, 2),
                'short_term_trend': round(st, 2),
            }
        }
        return signal_info

    def _generate_reasons(self, df, breakout_pos) -> list:
        """
        生成选股原因列表，基于实际突破日位置。
        """
        reasons = []
        lookback = self.params['lookback_days']
        vol_period = self.params['volume_ma_period']

        # 突破日数据和阻力位
        res_start = breakout_pos - lookback
        resistance = df['high'].iloc[res_start:breakout_pos].max()
        bd = df.iloc[breakout_pos]

        # 原因1：放量长阳突破阻力位（涨幅 = 相对前一日收盘价的涨幅）
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

        # 原因3：回踩不破突破日开盘价（从突破日到今天）
        days_since = len(df) - 1 - breakout_pos
        bo = bd['open']
        if days_since > 0:
            # 突破日次日到最后一天的最低价
            rmin = df['low'].iloc[breakout_pos + 1:].min()
            reasons.append(
                f"突破后{days_since}天回踩最低{rmin:.2f}，未破突破日开盘价{bo:.2f}"
            )
        else:
            reasons.append(f"今日放量长阳突破，开盘价{bo:.2f}")

        # 原因4：趋势向上
        cur = df['short_term_trend'].iloc[-1]
        bb = df['bull_bear_line'].iloc[-1]
        if not pd.isna(cur) and not pd.isna(bb):
            if cur > bb:
                reasons.append(
                    f"短期趋势线{cur:.2f}在多空线{bb:.2f}上方，趋势向上"
                )
            else:
                prev = df['short_term_trend'].iloc[-2]
                reasons.append(
                    f"短期趋势线拐头向上（{prev:.2f}→{cur:.2f}）"
                )

        return reasons
