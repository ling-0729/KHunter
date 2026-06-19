"""
W底策略（WBottomStrategy）

基于经典双底反转形态的量化选股策略。
通过识别W底形态、颈线突破确认、趋势反转验证和量价配合分析，寻找潜在买入机会。
核心流程：W底形态识别 → 颈线突破确认 → 趋势反转验证 → 量价配合分析 → 假W底过滤
"""
import pandas as pd
from strategy.base_strategy import BaseStrategy


class WBottomStrategy(BaseStrategy):
    """
    W底策略类
    
    继承 BaseStrategy，实现 calculate_indicators() 和 select_stocks() 方法。
    通过五个核心步骤实现选股：
    1. W底形态识别（局部低点扫描 + 双底结构验证）
    2. 颈线突破确认（价格突破 + 放量验证）
    3. 趋势反转验证（3选2逻辑）
    4. 量价配合分析（缩量为加分项）
    5. 假W底过滤（下跌前置 + 突破后支撑）
    """

    def __init__(self, params=None):
        """
        初始化W底策略
        
        :param params: 用户自定义参数字典，会覆盖默认参数
        """
        # 默认参数 - 与 config/strategy_params.yaml 中的默认值保持一致
        default_params = {
            # W底形态识别参数
            'pattern_days': 40,              # 形态扫描回溯天数
            'low_window': 5,                 # 局部低点识别窗口
            'min_gap': 10,                   # 相邻低点最小间隔（交易日）
            'bottom_diff_threshold': 0.03,   # L1/L2价格差异阈值（3%）
            'min_pattern_days': 10,          # L1到突破日最小间隔（交易日）
            # 颈线突破参数
            'neckline_break_ratio': 1.01,    # 颈线突破比例（101%）
            'volume_ma_period': 5,           # 成交量均线周期
            'volume_expand_ratio': 1.2,      # 突破放量倍数
            # 趋势反转参数
            'short_ma_period': 10,           # 短期均线周期
            'long_ma_period': 30,            # 长期均线周期
            # 量价配合参数
            'volume_shrink_ratio': 0.8,      # 右侧缩量比例
            # 假W底过滤参数
            'support_days': 3,               # 突破后支撑验证天数
            'support_ratio': 0.02,           # 支撑位容忍比例（2%）
            # 突破时效参数
            'max_break_days': 20,            # 突破日距今最大天数（增加到20天）
        }

        # 合并用户参数 - params 中的值覆盖默认值
        if params:
            default_params.update(params)

        # 调用父类初始化
        super().__init__("W底策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标（MA、KDJ、趋势线、成交量均线）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 添加了指标列的DataFrame
        """
        from utils.technical import MA, KDJ, calculate_zhixing_trend

        # 检查输入数据是否为空
        if df is None or df.empty:
            return df

        # 1. 检查是否已经计算过指标，避免重复计算
        if all(col in df.columns for col in ['short_ma', 'long_ma', 'K', 'D', 'J', 'short_term_trend', 'bull_bear_line', 'volume_ma']):
            return df

        result = df.copy()

        # 2. 计算短期均线和长期均线
        short_period = self.params['short_ma_period']
        long_period = self.params['long_ma_period']
        result['short_ma'] = MA(result['close'], short_period)
        result['long_ma'] = MA(result['close'], long_period)

        # 3. 计算KDJ指标（K、D、J）
        kdj_df = KDJ(result, n=9, m1=3, m2=3)
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']

        # 4. 计算知行趋势线（短期趋势线和多空线）
        # 优化：直接计算，减少函数调用开销
        from utils.technical import EMA
        # 知行短期趋势线 = EMA(EMA(CLOSE,10),10)
        result['short_term_trend'] = EMA(EMA(result['close'], 10), 10)
        # 知行多空线 = (MA(m1) + MA(m2) + MA(m3) + MA(m4)) / 4
        m1, m2, m3, m4 = 14, 28, 57, 114
        result['bull_bear_line'] = (MA(result['close'], m1) + MA(result['close'], m2) + 
                                   MA(result['close'], m3) + MA(result['close'], m4)) / 4

        # 5. 计算成交量均线（排除当日，shift(1)后再rolling）
        vol_period = self.params['volume_ma_period']
        # 倒序数据：先转正序计算，再恢复倒序
        reversed_vol = result['volume'].iloc[::-1]
        # shift(1) 排除当日成交量
        shifted_vol = reversed_vol.shift(1)
        # 计算均线
        vol_ma_reversed = shifted_vol.rolling(window=vol_period, min_periods=1).mean()
        # 恢复倒序
        result['volume_ma'] = vol_ma_reversed.iloc[::-1].values

        return result


    def _find_local_lows(self, df, pattern_days):
        """
        在回溯窗口内识别局部低点（优化版本）
        
        使用 LLV 函数在 low_window 窗口内识别局部低点，
        并施加最小间隔约束过滤噪声低点。
        使用向量化操作优化性能。
        
        :param df: 含指标的DataFrame（倒序，最新在index=0）
        :param pattern_days: 形态扫描回溯天数
        :return: 局部低点列表 [(index, price, date), ...]
        """
        from utils.technical import LLV
        import numpy as np

        # 获取参数
        low_window = self.params['low_window']
        min_gap = self.params['min_gap']

        # 限定扫描范围为最近 pattern_days 个交易日
        # 但排除最新的 5 天数据（留给颈线突破检测）
        scan_start = 5  # 排除最新的 5 天
        scan_end = min(scan_start + pattern_days, len(df))
        scan_df = df.iloc[scan_start:scan_end].copy()
        
        if len(scan_df) < low_window:
            return []

        # 使用 LLV 计算窗口内最低值
        llv_values = LLV(scan_df['low'], low_window)

        # 识别局部低点：该交易日的 low == LLV 窗口最小值 - 使用向量化操作优化
        # 创建布尔掩码：low等于LLV值（浮点数比较使用近似相等）
        local_low_mask = (scan_df['low'] - llv_values).abs() < 1e-6
        
        # 获取所有局部低点的位置（使用 iloc 位置而不是索引标签）
        local_low_positions = np.where(local_low_mask.values)[0].tolist()
        
        # 如果没有局部低点，直接返回
        if not local_low_positions:
            return []
        
        # 施加最小间隔约束（倒序数据中索引越小越新）
        filtered_lows = []
        
        # 按位置排序（从新到旧）
        sorted_positions = sorted(local_low_positions)
        
        # 遍历排序后的位置
        for pos in sorted_positions:
            # 转换回原 DataFrame 中的位置
            original_pos = pos + scan_start
            low_price = df['low'].iloc[original_pos]
            date_val = df['date'].iloc[original_pos]
            
            # 检查与已保留低点的间隔
            if filtered_lows:
                last_pos = filtered_lows[-1][0]
                last_price = filtered_lows[-1][1]
                # 倒序数据中位置差即为交易日间隔
                if abs(original_pos - last_pos) < min_gap:
                    # 间隔不足，保留价格更低的低点
                    if low_price < last_price:
                        filtered_lows[-1] = (original_pos, low_price, date_val)
                    continue
            filtered_lows.append((original_pos, low_price, date_val))

        return filtered_lows

    def _find_w_bottom(self, local_lows, df):
        """
        从局部低点中筛选W底形态（L1, H, L2）
        
        只考虑最近的两个低点对（最新的两个低点）。
        如果最近的两个低点满足条件，返回该W底形态；
        否则返回None。
        
        这确保我们只选择最近形成的W底形态，而不是历史上的任何W底。
        
        关键验证：
        1. 两个低点价格差异 <= 3%
        2. 两个低点间隔 >= 10 个交易日
        3. 颈线位置（H的价格应该在L1和L2之间）
        
        :param local_lows: 局部低点列表 [(index, price, date), ...]
        :param df: 含指标的DataFrame（倒序）
        :return: (l1_idx, l1_price, h_idx, h_price, l2_idx, l2_price) 或 None
        """
        threshold = self.params['bottom_diff_threshold']
        min_gap = self.params['min_gap']

        # 至少需要两个低点才能构成W底
        if len(local_lows) < 2:
            return None

        # 只考虑最近的两个低点（最新的两个）
        # local_lows 是按从新到旧排序的，所以最近的两个是 local_lows[0] 和 local_lows[1]
        l2_idx, l2_price, l2_date = local_lows[0]  # 最新的低点
        l1_idx, l1_price, l1_date = local_lows[1]  # 次新的低点

        # 验证两个低点间隔 > min_gap（严格大于10个交易日）
        # 倒序数据中位置差即为交易日间隔
        gap = abs(l1_idx - l2_idx)
        if gap <= min_gap:
            # 间隔不足，返回None（必须严格大于10个交易日）
            return None

        # 验证价格差异 <= bottom_diff_threshold
        if l1_price == 0:
            return None
        price_diff = abs(l2_price - l1_price) / l1_price
        if price_diff > threshold:
            # 最近的两个低点不符合条件，返回None
            return None

        # 在 L1 和 L2 之间查找最高价作为 H
        # 倒序数据：L1 索引 > L2 索引，中间区间为 (l2_idx, l1_idx)
        between_start = l2_idx + 1
        between_end = l1_idx
        if between_start >= between_end:
            return None

        # 获取中间区间的数据（使用 iloc 避免索引问题）
        try:
            between_df = df.iloc[between_start:between_end]
            if between_df.empty:
                return None

            # 找到中间最高价（使用 idxmax 获取标签索引，然后转换为位置索引）
            h_label_idx = between_df['high'].idxmax()
            h_price = between_df['high'].loc[h_label_idx]
            
            # 将标签索引转换为原 DataFrame 中的位置索引
            # h_label_idx 是 between_df 中的标签，需要找到它在原 df 中的位置
            h_pos_in_original = df.index.get_loc(h_label_idx)

            # 验证 H > L1 且 H > L2
            if h_price <= l1_price or h_price <= l2_price:
                return None

            # 新增验证：颈线位 >= L1 * 110%（确保W底涨幅空间足够）
            if h_price < l1_price * 1.1:
                return None

            # 返回满足条件的W底形态
            return (l1_idx, l1_price, h_pos_in_original, h_price, l2_idx, l2_price)
        except Exception:
            return None

    def _check_neckline_break(self, df, l2_idx, neckline):
        """
        检测颈线突破（只检查价格，突破1%即可）
        
        在最近5天内检测是否有收盘价突破颈线的大阳线。
        倒序数据中最近5天是 iloc[0:5]。
        
        :param df: 含指标的DataFrame（倒序）
        :param l2_idx: L2 的位置（iloc）（未使用，保持接口一致）
        :param neckline: 颈线价格（H的价格）
        :return: 突破日的位置（iloc），或 None
        """
        # 突破价格阈值：颈线 × 1.01（突破1%）
        break_price = neckline * 1.01

        # 在最近5天内检测
        if df is None or len(df) < 5:
            return None
        
        recent_df = df.head(5)
        
        # 检查是否有收盘价 >= 颈线 × 1.01 的交易日
        for idx in range(len(recent_df)):
            try:
                close = recent_df['close'].iloc[idx]
                
                # 检查数据有效性
                if pd.isna(close) or close <= 0:
                    continue
                
                # 检查是否突破颈线
                if close >= break_price:
                    # 返回这一天在原 DataFrame 中的位置
                    return idx
            except Exception:
                continue
        
        # 无有效突破
        return None

    def _check_volume_break(self, df):
        """
        检查放量确认条件：5日内出现涨幅超过8%的交易日，且成交量是前5日均量的1.5倍以上
        
        涨幅 = (当日收盘价 - 前一日收盘价) / 前一日收盘价
        注意：不需要是阳线，只需要涨幅 > 8%（可以是假阴线）
        
        :param df: 含指标的DataFrame（倒序）
        :return: 如果通过，返回满足条件的日期索引；否则返回 None
        """
        if df is None or len(df) < 5:
            return None
        
        recent_df = df.head(5)
        expand_ratio = self.params['volume_expand_ratio']
        
        for idx in range(len(recent_df)):
            try:
                close = recent_df['close'].iloc[idx]
                volume = recent_df['volume'].iloc[idx]
                volume_ma = recent_df['volume_ma'].iloc[idx]
                
                if pd.isna(close) or close <= 0:
                    continue
                
                if idx + 1 >= len(recent_df):
                    continue
                
                prev_close = recent_df['close'].iloc[idx + 1]
                if pd.isna(prev_close) or prev_close <= 0:
                    continue
                
                pct_change = (close - prev_close) / prev_close
                
                if pct_change > 0.08 and volume >= volume_ma * expand_ratio:
                    return idx
            except Exception:
                continue
        
        return None

    def _check_trend_reversal(self, df):
        """
        趋势反转验证 - 简化版：10日均线在30日均线之上
        
        检查条件：short_ma > long_ma（10日均线大于30日均线）
        
        :param df: 含指标的DataFrame（倒序，index=0为最新）
        :return: 布尔值
        """
        # 取最新一行数据（index=0）
        latest = df.iloc[0]

        # 检查：10日均线 > 30日均线
        if not pd.isna(latest.get('short_ma')) and not pd.isna(latest.get('long_ma')):
            if latest['short_ma'] > latest['long_ma']:
                return True

        return False

    def _check_volume_analysis(self, df, l1_idx, l2_idx):
        """
        量价配合分析：比较 L1 和 L2 处的成交量
        
        缩量判定：L2 成交量 < L1 成交量 × volume_shrink_ratio。
        此结果为加分项，不影响选股通过与否。
        
        :param df: 含指标的DataFrame
        :param l1_idx: L1 索引
        :param l2_idx: L2 索引
        :return: {'shrink': bool, 'shrink_ratio': float}
        """
        shrink_ratio_param = self.params['volume_shrink_ratio']

        # 获取 L1 和 L2 处的成交量
        vol_l1 = df['volume'].iloc[l1_idx]
        vol_l2 = df['volume'].iloc[l2_idx]

        # 防止除零
        if pd.isna(vol_l1) or vol_l1 <= 0:
            return {'shrink': False, 'shrink_ratio': 0.0}

        # 计算缩量比例
        ratio = vol_l2 / vol_l1
        # 缩量判定
        is_shrink = vol_l2 < vol_l1 * shrink_ratio_param

        return {'shrink': is_shrink, 'shrink_ratio': round(ratio, 2)}

    def _check_fake_w_bottom(self, df, l1_idx, neckline, break_idx):
        """
        假W底过滤（优化版本）
        
        条件1：L1 之前存在下跌趋势（最高价 > L1 × 1.2）
        条件2：突破后价格维持在颈线支撑位之上
        两个条件都满足才通过（不是假W底）。
        使用向量化操作优化性能。
        
        :param df: 含指标的DataFrame（倒序）
        :param l1_idx: L1 索引
        :param neckline: 颈线价格
        :param break_idx: 突破日索引
        :return: True 表示通过过滤（不是假W底）
        """
        long_period = self.params['long_ma_period']
        support_days = self.params['support_days']
        support_ratio = self.params['support_ratio']

        # 条件1：L1 之前 long_ma_period 个交易日内最高价 > L1 × 1.2
        # 倒序数据中 L1 之前 = 索引 > l1_idx
        l1_price = df['low'].iloc[l1_idx]
        before_start = l1_idx + 1
        before_end = min(l1_idx + long_period + 1, len(df))
        if before_start >= len(df):
            return False

        # 获取 L1 之前的数据
        before_df = df.iloc[before_start:before_end]
        if before_df.empty:
            return False
        max_high = before_df['high'].max()
        # 验证存在 20% 以上的下跌
        if max_high <= l1_price * 1.2:
            return False

        # 条件2：突破后至今所有交易日收盘价 >= 颈线 × (1 - support_ratio)
        support_price = neckline * (1 - support_ratio)
        # 倒序数据中突破后 = 索引 0 到 break_idx-1
        after_df = df.iloc[0:break_idx]
        
        # 向量化检查：是否有任何交易日跌破支撑位
        # 过滤掉NaN值
        valid_closes = after_df['close'].dropna()
        
        if not valid_closes.empty:
            # 检查是否有任何收盘价跌破支撑位
            if (valid_closes < support_price).any():
                return False

        return True
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []
        
        # 快速过滤
        criteria.append(f"0. 快速过滤：最近5天内是否有涨幅超过5%的交易日")
        
        # 条件1：放量确认
        expand_ratio = self.params['volume_expand_ratio']
        criteria.append(f"1. 放量确认：5日内出现涨幅超过8%的交易日，且成交量是前5日均量的{expand_ratio}倍以上")
        
        # 条件2：W形态过滤
        pattern_days = self.params['pattern_days']
        low_window = self.params['low_window']
        min_gap = self.params['min_gap']
        bottom_diff_threshold = self.params['bottom_diff_threshold'] * 100
        criteria.append(f"2. W形态过滤：最近{pattern_days}个交易日内形成双底结构，两个低点价格差异不超过{bottom_diff_threshold:.0f}%，间隔至少{min_gap}个交易日，颈线位>=L1*110%")
        
        # 条件3：颈线突破确认
        criteria.append(f"3. 颈线突破确认：放量日收盘价突破颈线（突破1%），且前一日收盘价低于颈线")
        
        # 条件4：趋势确认
        short_ma_period = self.params['short_ma_period']
        long_ma_period = self.params['long_ma_period']
        criteria.append(f"4. 趋势确认：{short_ma_period}日均线在{long_ma_period}日均线之上")
        
        # 条件5：支撑位不破
        support_days = self.params['support_days']
        support_ratio = self.params['support_ratio'] * 100
        criteria.append(f"5. 支撑位不破：突破颈线后至今收盘价不低于颈线{support_ratio:.0f}%")
        
        return criteria

    def _quick_precheck(self, df):
        """
        快速预检查：提前过滤不符合条件的股票
        
        检查内容：
        最近5天内是否有涨幅超过5%的交易日（不需要是阳线）
        
        :param df: 股票数据DataFrame（倒序）
        :return: True表示通过预检查，False表示不通过
        """
        if df is None or len(df) < 5:
            return False
        
        # 获取最近5天的数据（倒序，所以head(5)是最近5天）
        recent_df = df.head(5)
        
        if len(recent_df) < 2:
            return False
        
        # 检查是否有涨幅 > 5% 的交易日（不需要是阳线）
        found_big_rise = False
        for idx in range(len(recent_df)):
            try:
                close = recent_df['close'].iloc[idx]
                
                # 检查数据有效性
                if pd.isna(close) or close <= 0:
                    continue
                
                # 获取前一日收盘价（倒序数据中前一日是 idx+1）
                if idx + 1 >= len(recent_df):
                    continue
                
                prev_close = recent_df['close'].iloc[idx + 1]
                if pd.isna(prev_close) or prev_close <= 0:
                    continue
                
                # 计算涨幅：(当日收盘价 - 前一日收盘价) / 前一日收盘价
                pct_change = (close - prev_close) / prev_close
                
                # 如果涨幅 > 5%，通过预检查（不需要是阳线）
                if pct_change > 0.05:
                    found_big_rise = True
                    break
            except Exception:
                continue
        
        return found_big_rise

    def quick_filter(self, df):
        """
        快速过滤 - 覆盖基类方法
        
        检查内容：最近5天内是否有涨幅超过5%的阳线
        
        :param df: 股票数据DataFrame（倒序）
        :return: True表示通过快速过滤，False表示未通过
        """
        return self._quick_precheck(df)

    def select_stocks(self, df, stock_name='') -> list:
        """
        选股主逻辑，按新的流程执行
        
        流程：
        1. 快速过滤 - 最近5天内是否有涨幅超过5%的阳线
        2. 条件1：放量确认 - 5日内出现大阳线超过5%，且成交量是前5日均量的1.5倍以上
        3. 条件2：W形态过滤 - 最近40个交易日内形成双底结构
        4. 条件3：颈线突破确认 - 价格突破颈线（突破101%），且成交量是前5日均量的1.5倍以上
        5. 条件4：趋势确认 - 10日均线在30日均线之上
        6. 条件5：支撑位不破 - 突破颈线后至今收盘价不低于颈线2%
        
        :param df: 股票数据DataFrame
        :param stock_name: 股票名称，用于过滤ST/退市股票
        :return: 选股信号列表，每个元素为字典包含信号详情
        """
        try:
            # 数据验证：行数 < 60 返回空列表
            if df is None or len(df) < 60:
                return []

            # 过滤 ST/*ST 和退市股票
            if stock_name:
                name_upper = stock_name.upper()
                # ST 股票过滤
                if 'ST' in name_upper or '*ST' in name_upper:
                    return []
                # 退市/异常股票过滤
                for keyword in ['退', '未知', '退市', '已退']:
                    if keyword in stock_name:
                        return []

            # 快速预检查：提前过滤不符合条件的股票
            if not self._quick_precheck(df):
                return []

            # 计算技术指标
            df_with_indicators = self.calculate_indicators(df)
            if df_with_indicators.empty:
                return []

            # 条件1：放量确认 - 5日内出现大阳线超过8%，且成交量是前5日均量的1.5倍以上
            volume_break_idx = self._check_volume_break(df_with_indicators)
            if volume_break_idx is None:
                return []

            # 条件2：W形态过滤 - 识别W底形态
            pattern_days = self.params['pattern_days']
            local_lows = self._find_local_lows(df_with_indicators, pattern_days)
            if len(local_lows) < 2:
                return []

            w_bottom = self._find_w_bottom(local_lows, df_with_indicators)
            if w_bottom is None:
                return []
            l1_idx, l1_price, h_idx, h_price, l2_idx, l2_price = w_bottom
            
            # 颈线 = 两个低点之间的最高点
            neckline = h_price

            # 条件3：颈线突破确认
            # 验证：放量确认日收盘价 >= 颈线 × 1.01
            # 且前一日收盘价 < 颈线（蓄势突破）
            break_price = neckline * 1.01
            try:
                close_price = df_with_indicators['close'].iloc[volume_break_idx]
                if close_price < break_price:
                    return []
                
                # 检查前一日收盘价是否低于颈线
                if volume_break_idx + 1 >= len(df_with_indicators):
                    return []
                prev_close_price = df_with_indicators['close'].iloc[volume_break_idx + 1]
                if prev_close_price >= neckline:
                    return []
                
                break_idx = volume_break_idx
            except Exception:
                return []

            # 条件4：趋势确认 - 10日均线在30日均线之上
            trend_ok = self._check_trend_reversal(df_with_indicators)
            if not trend_ok:
                return []

            # 条件5：支撑位不破 - 突破颈线后至今收盘价不低于颈线2%
            support_ok = self._check_fake_w_bottom(df_with_indicators, l1_idx, neckline, break_idx)
            if not support_ok:
                return []

            # 生成信号
            reasons = ['W底形态确认']

            # 计算突破放量倍数
            break_vol = df_with_indicators['volume'].iloc[break_idx]
            break_vol_ma = df_with_indicators['volume_ma'].iloc[break_idx]
            if break_vol_ma > 0:
                vol_ratio = round(break_vol / break_vol_ma, 1)
            else:
                vol_ratio = 0.0
            reasons.append(f'颈线突破放量{vol_ratio}倍')

            # 趋势信息
            latest = df_with_indicators.iloc[0]
            if not pd.isna(latest.get('short_ma')) and not pd.isna(latest.get('long_ma')):
                if latest['short_ma'] > latest['long_ma']:
                    reasons.append(f'10日均线{latest["short_ma"]:.2f} > 30日均线{latest["long_ma"]:.2f}')

            # 获取颈线突破日的日期
            break_date = df_with_indicators['date'].iloc[break_idx]
            
            # 构建信号字典
            signal = {
                'date': str(df_with_indicators['date'].iloc[0]),
                'close': float(df_with_indicators['close'].iloc[0]),
                'J': float(df_with_indicators['J'].iloc[0]) if 'J' in df_with_indicators.columns else 0.0,
                'volume_ratio': vol_ratio,
                'short_term_trend': float(df_with_indicators['short_term_trend'].iloc[0]) if 'short_term_trend' in df_with_indicators.columns else 0.0,
                'bull_bear_line': float(df_with_indicators['bull_bear_line'].iloc[0]) if 'bull_bear_line' in df_with_indicators.columns else 0.0,
                'neckline': float(neckline),
                'l1_price': float(l1_price),
                'l2_price': float(l2_price),
                'key_date': break_date.strftime('%Y-%m-%d') if hasattr(break_date, 'strftime') else str(break_date)[:10],
                'key_date_type': '颈线突破日',
                'reasons': reasons
            }

            return [signal]

        except Exception:
            # 异常保护：返回空列表
            return []
