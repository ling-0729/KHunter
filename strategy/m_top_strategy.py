"""
M头策略（MTopStrategy）

基于经典双顶反转形态的量化选股策略。
通过识别M头形态、颈线跌破确认、趋势反转验证和量价配合分析，寻找潜在的卖出/风险信号。
核心流程：M头形态识别 → 颈线跌破确认 → 趋势反转验证 → 量价配合分析 → 假M头过滤
"""
import pandas as pd
from strategy.base_strategy import BaseStrategy


class MTopStrategy(BaseStrategy):
    """
    M头策略类
    
    继承 BaseStrategy，实现 calculate_indicators() 和 select_stocks() 方法。
    通过五个核心步骤实现选股：
    1. M头形态识别（局部高点扫描 + 双顶结构验证）
    2. 颈线跌破确认（价格跌破 + 放量验证）
    3. 趋势反转验证（3选2逻辑）
    4. 量价配合分析（缩量为加分项）
    5. 假M头过滤（上涨前置 + 跌破后压力）
    """

    def __init__(self, params=None):
        """
        初始化M头策略
        
        :param params: 用户自定义参数字典，会覆盖默认参数
        """
        # 默认参数 - 与 config/strategy_params.yaml 中的默认值保持一致
        default_params = {
            # M头形态识别参数
            'pattern_days': 40,              # 形态扫描回溯天数
            'high_window': 5,                # 局部高点识别窗口
            'min_gap': 10,                   # 相邻高点最小间隔（交易日）
            'top_diff_threshold': 0.03,      # H1/H2价格差异阈值（3%）
            'min_pattern_days': 10,          # H1到颈线跌破日最小间隔（交易日）
            # 颈线跌破参数
            'neckline_break_ratio': 0.99,    # 颈线跌破比例（99%）
            'volume_ma_period': 5,           # 成交量均线周期
            'volume_expand_ratio': 1.2,      # 跌破放量倍数
            # 趋势反转参数
            'short_ma_period': 10,           # 短期均线周期
            'long_ma_period': 30,            # 长期均线周期
            # 量价配合参数
            'volume_shrink_ratio': 0.8,      # 右侧缩量比例
            # 假M头过滤参数
            'support_days': 3,               # 跌破后支撑验证天数
            'resistance_ratio': 0.02,        # 颈线压力位容忍比例（2%）
        }

        # 合并用户参数 - params 中的值覆盖默认值
        if params:
            default_params.update(params)

        # 调用父类初始化
        super().__init__("M头策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标（MA、KDJ、趋势线、成交量均线）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 添加了指标列的DataFrame
        """
        # 复制DataFrame，避免修改原数据
        result = df.copy()
        
        # 导入技术指标函数
        from utils.technical import MA, KDJ, calculate_zhixing_trend, REF
        
        # 1. 计算短期均线和长期均线
        # short_ma：短期均线（默认10日）
        result['short_ma'] = MA(result['close'], self.params['short_ma_period'])
        
        # long_ma：长期均线（默认30日）
        result['long_ma'] = MA(result['close'], self.params['long_ma_period'])
        
        # 2. 计算KDJ指标（K、D、J）
        kdj_df = KDJ(result, n=9, m1=3, m2=3)
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']
        
        # 3. 计算知行趋势线和多空线
        # short_term_trend：知行短期趋势线 = EMA(EMA(CLOSE,10),10)
        # bull_bear_line：知行多空线 = (MA(14) + MA(28) + MA(57) + MA(114)) / 4
        trend_df = calculate_zhixing_trend(result)
        result['short_term_trend'] = trend_df['short_term_trend']
        result['bull_bear_line'] = trend_df['bull_bear_line']
        
        # 4. 计算成交量均线（排除当日，使用shift(1)）
        # volume_ma：成交量均线（默认5日，排除当日）
        # 先对成交量进行shift(1)，然后计算MA
        volume_shifted = REF(result['volume'], 1)
        result['volume_ma'] = MA(volume_shifted, self.params['volume_ma_period'])
        
        # 5. 计算市值（如无字段则估算）
        # 如果DataFrame中已有market_cap字段，直接使用；否则设为0（由上层处理）
        if 'market_cap' not in result.columns:
            result['market_cap'] = 0.0
        
        return result

    def _find_local_highs(self, df, pattern_days):
        """
        在回溯窗口内识别局部高点
        
        使用HHV函数在high_window窗口内识别局部高点，并施加最小间隔约束。
        
        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param pattern_days: 形态扫描的回溯天数
        :return: 局部高点列表 [(index, price, date), ...]
        """
        # 导入技术指标函数
        from utils.technical import HHV
        
        # 限制扫描范围：只在最近pattern_days个交易日内扫描
        scan_df = df.iloc[:pattern_days].copy() if len(df) > pattern_days else df.copy()
        
        # 计算HHV（high_window默认5）
        hhv_values = HHV(scan_df['high'], self.params['high_window'])
        
        # 识别局部高点：high == HHV值
        local_highs = []
        for idx in range(len(scan_df)):
            # 检查该交易日的high是否等于HHV值
            if pd.notna(hhv_values.iloc[idx]) and scan_df['high'].iloc[idx] == hhv_values.iloc[idx]:
                local_highs.append({
                    'index': idx,
                    'price': scan_df['high'].iloc[idx],
                    'date': scan_df['date'].iloc[idx]
                })
        
        # 施加最小间隔约束（min_gap，默认10个交易日）
        filtered_highs = []
        min_gap = self.params['min_gap']
        
        for high in local_highs:
            # 检查与最后一个高点的间隔
            if not filtered_highs or (high['index'] - filtered_highs[-1]['index']) >= min_gap:
                filtered_highs.append(high)
        
        # 转换为返回格式 [(index, price, date), ...]
        result = [(h['index'], h['price'], h['date']) for h in filtered_highs]
        
        return result

    def _find_m_top(self, local_highs, df):
        """
        从局部高点中筛选M头形态（H1, L, H2）
        
        遍历相邻高点对，验证价格差异和中间低点条件。
        
        :param local_highs: 局部高点列表 [(index, price, date), ...]
        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: (h1_idx, h1_price, l_idx, l_price, h2_idx, h2_price) 或 None
        """
        # 需要至少2个局部高点才能形成M头
        if len(local_highs) < 2:
            return None
        
        # 遍历相邻高点对
        for i in range(len(local_highs) - 1):
            h1_idx, h1_price, h1_date = local_highs[i]
            h2_idx, h2_price, h2_date = local_highs[i + 1]
            
            # 验证价格差异 <= top_diff_threshold（默认3%）
            price_diff_ratio = abs(h2_price - h1_price) / h1_price
            if price_diff_ratio > self.params['top_diff_threshold']:
                continue
            
            # 在H1和H2之间查找最低价作为L
            # 注意：倒序数据，H2的索引 > H1的索引（H2更早）
            start_idx = min(h1_idx, h2_idx)
            end_idx = max(h1_idx, h2_idx)
            
            # 获取H1和H2之间的数据
            between_df = df.iloc[start_idx:end_idx + 1]
            
            # 找最低价
            min_low_idx = between_df['low'].idxmin()
            min_low_price = between_df['low'].min()
            
            # 验证L < H1 且 L < H2
            if min_low_price >= h1_price or min_low_price >= h2_price:
                continue
            
            # 找到有效的M头形态，返回结果
            # 返回格式：(h1_idx, h1_price, l_idx, l_price, h2_idx, h2_price)
            return (h1_idx, h1_price, min_low_idx, min_low_price, h2_idx, h2_price)
        
        # 没有找到满足条件的M头形态
        return None

    def _check_neckline_break(self, df, h2_idx, neckline):
        """
        检测颈线跌破并验证放量条件
        
        在H2之后检测收盘价是否跌破颈线，并验证成交量条件。
        
        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param h2_idx: H2的索引
        :param neckline: 颈线价格
        :return: 跌破日的索引，或 None
        """
        # 在H2之后（索引 < h2_idx，因为倒序）的交易日中检测
        # 从H2之后开始扫描（索引从0到h2_idx-1）
        for idx in range(h2_idx):
            # 获取该交易日的数据
            close_price = df['close'].iloc[idx]
            volume = df['volume'].iloc[idx]
            volume_ma = df['volume_ma'].iloc[idx]
            
            # 检查是否有NaN值
            if pd.isna(close_price) or pd.isna(volume) or pd.isna(volume_ma):
                continue
            
            # 跌破条件：收盘价 <= 颈线 × neckline_break_ratio（默认0.99）
            break_threshold = neckline * self.params['neckline_break_ratio']
            if close_price > break_threshold:
                continue
            
            # 放量条件：跌破日成交量 >= volume_ma × volume_expand_ratio（默认1.2）
            volume_threshold = volume_ma * self.params['volume_expand_ratio']
            if volume < volume_threshold:
                continue
            
            # 两个条件都满足，验证最小形态天数
            # h1_idx - break_idx >= min_pattern_days（默认10）
            # 注意：这里需要h1_idx，但该方法没有接收h1_idx参数
            # 我们需要在调用处传入h1_idx，或者在这里返回idx让调用处验证
            # 根据设计文档，这里返回跌破日索引，由调用处验证最小形态天数
            
            # 找到有效跌破，返回跌破日索引
            return idx
        
        # 没有找到有效跌破
        return None

    def _check_trend_reversal(self, df) -> bool:
        """
        趋势反转验证 - 3选2逻辑
        
        验证以下三个子条件中至少满足两个：
        (a) 短期均线 < 长期均线
        (b) 知行短期趋势线 < 0
        (c) 最新收盘价 < 长期均线
        
        :param df: 包含指标的股票数据DataFrame（倒序，最新在index=0）
        :return: 布尔值，True表示趋势反转成立
        """
        # 获取最新交易日的数据（index=0）
        latest_idx = 0
        
        # 获取最新的指标值
        short_ma = df['short_ma'].iloc[latest_idx]
        long_ma = df['long_ma'].iloc[latest_idx]
        short_term_trend = df['short_term_trend'].iloc[latest_idx]
        close_price = df['close'].iloc[latest_idx]
        
        # 检查是否有NaN值
        if pd.isna(short_ma) or pd.isna(long_ma) or pd.isna(short_term_trend) or pd.isna(close_price):
            return False
        
        # 验证三个子条件
        # 子条件 (a)：short_ma < long_ma
        condition_a = short_ma < long_ma
        
        # 子条件 (b)：short_term_trend < 0
        condition_b = short_term_trend < 0
        
        # 子条件 (c)：最新收盘价 < long_ma
        condition_c = close_price < long_ma
        
        # 计算满足的条件数量
        conditions_met = sum([condition_a, condition_b, condition_c])
        
        # 满足 >= 2 个子条件即返回 True
        return conditions_met >= 2

    def _check_volume_analysis(self, df, h1_idx, h2_idx) -> dict:
        """
        量价配合分析 - 判断右侧顶部是否缩量
        
        比较 H1 和 H2 处的成交量，判断是否存在缩量（量价背离）。
        缩量为加分项，不影响选股通过与否，仅记录到 reasons 中。
        
        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param h1_idx: H1 的索引
        :param h2_idx: H2 的索引
        :return: 字典 {'shrink': bool, 'shrink_ratio': float}
        """
        # 获取 H1 和 H2 处的成交量
        h1_volume = df['volume'].iloc[h1_idx]
        h2_volume = df['volume'].iloc[h2_idx]
        
        # 检查是否有NaN值
        if pd.isna(h1_volume) or pd.isna(h2_volume) or h1_volume == 0:
            return {'shrink': False, 'shrink_ratio': 1.0}
        
        # 计算缩量比例：H2成交量 / H1成交量
        shrink_ratio = h2_volume / h1_volume
        
        # 缩量判定：H2成交量 < H1成交量 × volume_shrink_ratio（默认0.8）
        # 即 shrink_ratio < volume_shrink_ratio
        is_shrink = shrink_ratio < self.params['volume_shrink_ratio']
        
        return {
            'shrink': is_shrink,
            'shrink_ratio': shrink_ratio
        }

    def _check_fake_m_top(self, df, h1_idx, neckline, break_idx) -> bool:
        """
        假M头过滤 - 判断是否为上涨中继形成的假M头
        
        验证两个条件都满足才通过过滤（返回True）：
        条件1：H1之前long_ma_period个交易日内最低价 < H1价格 × 0.8（存在前期上涨）
        条件2：跌破后support_days个交易日内收盘价 <= 颈线 × (1 + resistance_ratio)（维持压力）
        
        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param h1_idx: H1 的索引
        :param neckline: 颈线价格
        :param break_idx: 跌破日的索引
        :return: 布尔值，True表示通过过滤（不是假M头）
        """
        # 条件1：H1之前long_ma_period个交易日内最低价 < H1价格 × 0.8
        # 获取H1处的价格
        h1_price = df['high'].iloc[h1_idx]
        
        # 获取H1之前long_ma_period个交易日的数据
        # 注意：倒序数据，H1之前的数据索引更大
        long_ma_period = self.params['long_ma_period']
        start_idx = h1_idx + 1
        end_idx = min(h1_idx + long_ma_period + 1, len(df))
        
        # 检查索引范围是否有效
        if start_idx >= len(df):
            return False
        
        # 获取该范围内的最低价
        before_h1_df = df.iloc[start_idx:end_idx]
        if len(before_h1_df) == 0:
            return False
        
        min_low_before_h1 = before_h1_df['low'].min()
        
        # 条件1判定：最低价 < H1价格 × 0.8
        condition1 = min_low_before_h1 < h1_price * 0.8
        
        # 条件2：跌破后support_days个交易日内收盘价 <= 颈线 × (1 + resistance_ratio)
        # 获取跌破日之后support_days个交易日的数据
        support_days = self.params['support_days']
        resistance_ratio = self.params['resistance_ratio']
        
        # 跌破日之后的数据（索引从0到break_idx-1）
        start_idx = 0
        end_idx = min(break_idx + support_days, len(df))
        
        # 检查索引范围是否有效
        if start_idx >= end_idx:
            return False
        
        # 获取该范围内的收盘价
        after_break_df = df.iloc[start_idx:end_idx]
        if len(after_break_df) == 0:
            return False
        
        # 计算压力位：颈线 × (1 + resistance_ratio)
        resistance_level = neckline * (1 + resistance_ratio)
        
        # 条件2判定：所有收盘价都 <= 压力位
        condition2 = (after_break_df['close'] <= resistance_level).all()
        
        # 两个条件都满足才通过过滤
        return condition1 and condition2

    def select_stocks(self, df, stock_name='') -> list:
        """
        选股主逻辑，串联六个核心步骤
        
        流程：数据验证 → M头形态识别 → 颈线跌破确认 →
              趋势反转验证 → 量价配合分析 → 假M头过滤 → 生成信号
        
        :param df: 包含指标的股票数据DataFrame
        :param stock_name: 股票名称，用于过滤ST/退市股票
        :return: 选股信号列表，每个元素为字典包含信号详情
        """
        # 步骤0：数据验证
        # 检查数据行数是否足够（至少60行）
        if len(df) < 60:
            return []
        
        # 过滤ST/*ST和退市股票
        if stock_name:
            # 检查股票名称中是否包含ST、退市等关键词
            if any(keyword in stock_name for keyword in ['ST', '*ST', '退', '未知', '退市', '已退']):
                return []
        
        # 步骤1：M头形态识别
        # 调用_find_local_highs识别局部高点
        local_highs = self._find_local_highs(df, self.params['pattern_days'])
        
        # 如果没有找到足够的局部高点，返回空列表
        if not local_highs:
            return []
        
        # 调用_find_m_top识别M头形态
        m_top_result = self._find_m_top(local_highs, df)
        
        # 如果没有找到M头形态，返回空列表
        if m_top_result is None:
            return []
        
        # 解析M头形态的结果
        h1_idx, h1_price, l_idx, l_price, h2_idx, h2_price = m_top_result
        neckline = l_price
        
        # 步骤2：颈线跌破确认
        # 调用_check_neckline_break检测颈线跌破
        break_idx = self._check_neckline_break(df, h2_idx, neckline)
        
        # 如果没有找到有效跌破，返回空列表
        if break_idx is None:
            return []
        
        # 验证最小形态天数：h1_idx - break_idx >= min_pattern_days
        if h1_idx - break_idx < self.params['min_pattern_days']:
            return []
        
        # 步骤3：趋势反转验证
        # 调用_check_trend_reversal验证趋势反转
        if not self._check_trend_reversal(df):
            return []
        
        # 步骤4：量价配合分析
        # 调用_check_volume_analysis分析成交量
        volume_analysis = self._check_volume_analysis(df, h1_idx, h2_idx)
        
        # 步骤5：假M头过滤
        # 调用_check_fake_m_top过滤假M头
        if not self._check_fake_m_top(df, h1_idx, neckline, break_idx):
            return []
        
        # 步骤6：生成信号
        # 获取跌破日的数据
        break_date = df['date'].iloc[break_idx]
        break_close = df['close'].iloc[break_idx]
        break_volume = df['volume'].iloc[break_idx]
        break_volume_ma = df['volume_ma'].iloc[break_idx]
        
        # 计算放量倍数
        if pd.isna(break_volume_ma) or break_volume_ma == 0:
            volume_ratio = 0.0
        else:
            volume_ratio = break_volume / break_volume_ma
        
        # 获取其他指标
        j_value = df['J'].iloc[break_idx] if 'J' in df.columns else 0.0
        market_cap = df['market_cap'].iloc[break_idx] if 'market_cap' in df.columns else 0.0
        short_term_trend = df['short_term_trend'].iloc[break_idx] if 'short_term_trend' in df.columns else 0.0
        bull_bear_line = df['bull_bear_line'].iloc[break_idx] if 'bull_bear_line' in df.columns else 0.0
        
        # 构建reasons列表
        reasons = []
        
        # 原因1：M头形态确认
        reasons.append('M头形态确认')
        
        # 原因2：颈线跌破放量倍数
        reasons.append(f'颈线跌破放量{volume_ratio:.1f}倍')
        
        # 原因3：趋势反转
        # 计算满足的趋势反转条件数量
        short_ma = df['short_ma'].iloc[0]
        long_ma = df['long_ma'].iloc[0]
        close_price = df['close'].iloc[0]
        
        trend_conditions = 0
        if short_ma < long_ma:
            trend_conditions += 1
        if short_term_trend < 0:
            trend_conditions += 1
        if close_price < long_ma:
            trend_conditions += 1
        
        reasons.append(f'趋势反转({trend_conditions}/3)')
        
        # 原因4：右侧顶部缩量（可选）
        if volume_analysis['shrink']:
            reasons.append('右侧顶部缩量')
        
        # 构建信号字典
        signal = {
            'date': break_date,
            'close': break_close,
            'J': j_value,
            'volume_ratio': volume_ratio,
            'market_cap': market_cap,
            'short_term_trend': short_term_trend,
            'bull_bear_line': bull_bear_line,
            'neckline': neckline,
            'h1_price': h1_price,
            'h2_price': h2_price,
            'reasons': reasons
        }
        
        return [signal]
