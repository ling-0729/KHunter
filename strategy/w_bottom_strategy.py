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
            'max_break_days': 10,            # 突破日距今最大天数
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

        result = df.copy()

        # 1. 计算短期均线和长期均线
        short_period = self.params['short_ma_period']
        long_period = self.params['long_ma_period']
        result['short_ma'] = MA(result['close'], short_period)
        result['long_ma'] = MA(result['close'], long_period)

        # 2. 计算KDJ指标（K、D、J）
        kdj_df = KDJ(result, n=9, m1=3, m2=3)
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']

        # 3. 计算知行趋势线（短期趋势线和多空线）
        trend_df = calculate_zhixing_trend(result)
        result['short_term_trend'] = trend_df['short_term_trend']
        result['bull_bear_line'] = trend_df['bull_bear_line']

        # 4. 计算成交量均线（排除当日，shift(1)后再rolling）
        vol_period = self.params['volume_ma_period']
        # 倒序数据：先转正序计算，再恢复倒序
        reversed_vol = result['volume'].iloc[::-1]
        # shift(1) 排除当日成交量
        shifted_vol = reversed_vol.shift(1)
        # 计算均线
        vol_ma_reversed = shifted_vol.rolling(window=vol_period, min_periods=1).mean()
        # 恢复倒序
        result['volume_ma'] = vol_ma_reversed.iloc[::-1].values

        # 5. 计算市值（如无 market_cap 字段则用 close * volume 估算）
        if 'market_cap' not in result.columns:
            # 简单估算：收盘价 × 成交量 / 1e8（亿元）
            result['market_cap'] = result['close'] * result['volume'] / 1e8

        return result


    def _find_local_lows(self, df, pattern_days):
        """
        在回溯窗口内识别局部低点
        
        使用 LLV 函数在 low_window 窗口内识别局部低点，
        并施加最小间隔约束过滤噪声低点。
        
        :param df: 含指标的DataFrame（倒序，最新在index=0）
        :param pattern_days: 形态扫描回溯天数
        :return: 局部低点列表 [(index, price, date), ...]
        """
        from utils.technical import LLV

        # 获取参数
        low_window = self.params['low_window']
        min_gap = self.params['min_gap']

        # 限定扫描范围为最近 pattern_days 个交易日
        scan_df = df.head(pattern_days).copy()
        if len(scan_df) < low_window:
            return []

        # 使用 LLV 计算窗口内最低值
        llv_values = LLV(scan_df['low'], low_window)

        # 识别局部低点：该交易日的 low == LLV 窗口最小值
        raw_lows = []
        for i in range(len(scan_df)):
            low_price = scan_df['low'].iloc[i]
            llv_price = llv_values.iloc[i]
            # 浮点数比较，使用近似相等
            if abs(low_price - llv_price) < 1e-6:
                date_val = scan_df['date'].iloc[i]
                raw_lows.append((scan_df.index[i], low_price, date_val))

        # 施加最小间隔约束（倒序数据中索引越小越新）
        # 按索引升序排列（从新到旧），间隔不足时保留价格更低的低点
        raw_lows.sort(key=lambda x: x[0])
        filtered_lows = []
        for low_point in raw_lows:
            # 检查与已保留低点的间隔
            if filtered_lows:
                last_idx = filtered_lows[-1][0]
                last_price = filtered_lows[-1][1]
                # 倒序数据中索引差即为交易日间隔
                if abs(low_point[0] - last_idx) < min_gap:
                    # 间隔不足，保留价格更低的低点
                    if low_point[1] < last_price:
                        filtered_lows[-1] = low_point
                    continue
            filtered_lows.append(low_point)

        return filtered_lows

    def _find_w_bottom(self, local_lows, df):
        """
        从局部低点中筛选W底形态（L1, H, L2）
        
        遍历相邻低点对，验证价格差异和中间高点，
        返回第一个满足条件的W底形态。
        
        :param local_lows: 局部低点列表 [(index, price, date), ...]
        :param df: 含指标的DataFrame（倒序）
        :return: (l1_idx, l1_price, h_idx, h_price, l2_idx, l2_price) 或 None
        """
        threshold = self.params['bottom_diff_threshold']

        # 至少需要两个低点才能构成W底
        if len(local_lows) < 2:
            return None

        # 遍历所有相邻低点对（倒序数据中索引大的更早）
        for i in range(len(local_lows) - 1):
            # L2 是较新的低点（索引较小），L1 是较早的低点（索引较大）
            l2_idx, l2_price, l2_date = local_lows[i]
            l1_idx, l1_price, l1_date = local_lows[i + 1]

            # 验证价格差异 <= bottom_diff_threshold
            if l1_price == 0:
                continue
            price_diff = abs(l2_price - l1_price) / l1_price
            if price_diff > threshold:
                continue

            # 在 L1 和 L2 之间查找最高价作为 H
            # 倒序数据：L1 索引 > L2 索引，中间区间为 (l2_idx, l1_idx)
            between_start = l2_idx + 1
            between_end = l1_idx
            if between_start >= between_end:
                continue

            # 获取中间区间的数据
            between_df = df.loc[between_start:between_end - 1]
            if between_df.empty:
                continue

            # 找到中间最高价
            h_pos = between_df['high'].idxmax()
            h_price = between_df['high'].loc[h_pos]

            # 验证 H > L1 且 H > L2
            if h_price <= l1_price or h_price <= l2_price:
                continue

            # 返回第一个满足条件的W底形态
            return (l1_idx, l1_price, h_pos, h_price, l2_idx, l2_price)

        return None

    def _check_neckline_break(self, df, l2_idx, neckline):
        """
        检测颈线突破+放量确认
        
        在 L2 之后的交易日中检测收盘价是否放量突破颈线。
        倒序数据中 L2 之后的交易日索引 < l2_idx。
        
        :param df: 含指标的DataFrame（倒序）
        :param l2_idx: L2 的索引
        :param neckline: 颈线价格（H的价格）
        :return: 突破日的索引，或 None
        """
        # 获取参数
        break_ratio = self.params['neckline_break_ratio']
        expand_ratio = self.params['volume_expand_ratio']
        max_break_days = self.params.get('max_break_days', 10)

        # 突破价格阈值
        break_price = neckline * break_ratio

        # 在 L2 之后（索引 < l2_idx）的交易日中检测
        # 倒序数据中从 l2_idx-1 到 0，时间从早到新
        # 找首次突破日（最早满足条件的）
        first_break_idx = None
        for idx in range(l2_idx - 1, -1, -1):
            # 跳过无效数据
            if idx not in df.index:
                continue
            close = df['close'].iloc[idx]
            volume = df['volume'].iloc[idx]
            vol_ma = df['volume_ma'].iloc[idx]

            # 检查收盘价是否 NaN
            if pd.isna(close) or pd.isna(volume):
                continue

            # 突破条件：收盘价 >= 颈线 × neckline_break_ratio
            if close < break_price:
                continue

            # 放量条件：成交量 >= volume_ma × volume_expand_ratio
            # 防止 volume_ma 为 0 或 NaN
            if pd.isna(vol_ma) or vol_ma <= 0:
                continue
            if volume >= vol_ma * expand_ratio:
                # 两个条件同时满足，记录首次突破日
                first_break_idx = idx
                # 继续遍历找最早的突破日，不要break

        # 检查首次突破日是否在 max_break_days 范围内
        if first_break_idx is not None:
            # 修复：检查天数差，而不是索引值
            # 倒序数据中索引差即为交易日间隔
            days_diff = l2_idx - first_break_idx
            if days_diff <= max_break_days:
                return first_break_idx

        # 无有效突破或突破日距今过久
        return None

    def _check_trend_reversal(self, df):
        """
        趋势反转验证（3选2逻辑）
        
        检查以下三个子条件，满足 >= 2 个即通过：
        (a) short_ma > long_ma
        (b) short_term_trend > 0
        (c) 最新收盘价 > long_ma
        
        :param df: 含指标的DataFrame（倒序，index=0为最新）
        :return: 布尔值
        """
        # 取最新一行数据（index=0）
        latest = df.iloc[0]
        count = 0

        # 子条件 (a)：短期均线 > 长期均线
        if not pd.isna(latest.get('short_ma')) and not pd.isna(latest.get('long_ma')):
            if latest['short_ma'] > latest['long_ma']:
                count += 1

        # 子条件 (b)：短期趋势线 > 0
        if not pd.isna(latest.get('short_term_trend')):
            if latest['short_term_trend'] > 0:
                count += 1

        # 子条件 (c)：最新收盘价 > 长期均线
        if not pd.isna(latest.get('close')) and not pd.isna(latest.get('long_ma')):
            if latest['close'] > latest['long_ma']:
                count += 1

        # 满足 >= 2 个子条件即通过
        return count >= 2

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
        假W底过滤
        
        条件1：L1 之前存在下跌趋势（最高价 > L1 × 1.2）
        条件2：突破后价格维持在颈线支撑位之上
        两个条件都满足才通过（不是假W底）。
        
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
        for check_idx in range(break_idx - 1, -1, -1):
            close = df['close'].iloc[check_idx]
            if pd.isna(close):
                continue
            # 跌破支撑位则判定为假W底
            if close < support_price:
                return False

        return True

    def select_stocks(self, df, stock_name='') -> list:
        """
        选股主逻辑，串联五个核心步骤
        
        流程：数据验证 → W底形态识别 → 颈线突破确认 →
              趋势反转验证 → 量价配合分析 → 假W底过滤 → 生成信号
        
        :param df: 包含指标的股票数据DataFrame
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

            # 步骤1：识别局部低点
            pattern_days = self.params['pattern_days']
            local_lows = self._find_local_lows(df, pattern_days)
            if len(local_lows) < 2:
                return []

            # 步骤2：识别W底形态
            w_bottom = self._find_w_bottom(local_lows, df)
            if w_bottom is None:
                return []
            l1_idx, l1_price, h_idx, h_price, l2_idx, l2_price = w_bottom
            # 颈线价格 = H 的价格
            neckline = h_price

            # 步骤3：颈线突破确认
            break_idx = self._check_neckline_break(df, l2_idx, neckline)
            if break_idx is None:
                return []

            # 步骤3.5：验证形态时间间隔（L1到突破日至少10个交易日）
            min_pattern_days = self.params['min_pattern_days']
            pattern_interval = l1_idx - break_idx
            if pattern_interval < min_pattern_days:
                return []

            # 步骤4：趋势反转验证
            trend_ok = self._check_trend_reversal(df)
            if not trend_ok:
                return []

            # 步骤5：量价配合分析（缩量为加分项）
            vol_analysis = self._check_volume_analysis(df, l1_idx, l2_idx)

            # 步骤6：假W底过滤
            fake_ok = self._check_fake_w_bottom(df, l1_idx, neckline, break_idx)
            if not fake_ok:
                return []

            # 生成信号：构建 reasons 列表
            reasons = ['W底形态确认']

            # 计算突破放量倍数
            break_vol = df['volume'].iloc[break_idx]
            break_vol_ma = df['volume_ma'].iloc[break_idx]
            if break_vol_ma > 0:
                vol_ratio = round(break_vol / break_vol_ma, 1)
            else:
                vol_ratio = 0.0
            reasons.append(f'颈线突破放量{vol_ratio}倍')

            # 趋势反转信息
            latest = df.iloc[0]
            trend_count = 0
            if not pd.isna(latest.get('short_ma')) and not pd.isna(latest.get('long_ma')):
                if latest['short_ma'] > latest['long_ma']:
                    trend_count += 1
            if not pd.isna(latest.get('short_term_trend')):
                if latest['short_term_trend'] > 0:
                    trend_count += 1
            if not pd.isna(latest.get('close')) and not pd.isna(latest.get('long_ma')):
                if latest['close'] > latest['long_ma']:
                    trend_count += 1
            reasons.append(f'趋势反转({trend_count}/3)')

            # 缩量加分项（可选）
            if vol_analysis['shrink']:
                reasons.append('右侧底部缩量')

            # 构建信号字典
            signal = {
                'date': str(df['date'].iloc[0]),
                'close': float(df['close'].iloc[0]),
                'J': float(df['J'].iloc[0]) if 'J' in df.columns else 0.0,
                'volume_ratio': vol_ratio,
                'market_cap': float(df['market_cap'].iloc[0]) if 'market_cap' in df.columns else 0.0,
                'short_term_trend': float(df['short_term_trend'].iloc[0]) if 'short_term_trend' in df.columns else 0.0,
                'bull_bear_line': float(df['bull_bear_line'].iloc[0]) if 'bull_bear_line' in df.columns else 0.0,
                'neckline': float(neckline),
                'l1_price': float(l1_price),
                'l2_price': float(l2_price),
                'reasons': reasons
            }

            return [signal]

        except Exception:
            # 异常保护：返回空列表
            return []
