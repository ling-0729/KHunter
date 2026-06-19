import pandas as pd
import numpy as np
from datetime import datetime
from strategy.base_strategy import BaseStrategy

class LimitUpPullbackStrategy(BaseStrategy):
    """
    涨停回马枪策略 - 简化版本

    策略逻辑：
    1. 寻找最近出现的涨停板
    2. 涨停后出现合理回调（不破涨停收盘价的95%）
    3. 回调期间出现成交量萎缩

    优化点：
    1. 快速预检查，提前过滤无涨停板的股票
    2. 去除复杂指标计算（KDJ、MACD），只基于价格和成交量
    3. 向量化操作替代循环
    """

    def __init__(self, params=None):
        """
        初始化策略

        :param params: 策略参数
        """
        # 默认参数
        default_params = {
            # 涨停确认参数
            'limit_up_lookback_days': 6,        # 涨停回溯天数
            'limit_up_threshold': 0.095,         # 涨停阈值（9.5%）
            'volume_ratio_threshold': 2.2,       # 成交量比阈值
            # 回调企稳参数
            'pullback_days_min': 1,             # 最小回调天数
            'pullback_days_max': 9,             # 最大回调天数（涨停后验证窗口）
            'pullback_range_min': 0.00,         # 最小回调幅度（0%）
            'pullback_range_max': 0.15,         # 最大回调幅度（15%）
            'volume_shrinkage_ratio': 0.5,      # 成交量萎缩比例
            'support_ratio': 0.95,             # 支撑比例（不破涨停收盘价的95%）
            'resistance_ratio': 1.05,           # 阻力比例（不超过涨停收盘价的105%）
        }

        # 合并用户参数 - params 中的值覆盖默认值
        if params:
            default_params.update(params)

        # 调用父类初始化
        super().__init__("涨停回马枪策略", default_params)

    def quick_filter(self, df):
        """
        快速过滤：检查最近10个交易日内是否有涨停板

        只基于价格，不涉及成交量或其他指标

        :param df: 股票数据DataFrame（倒序，从新到旧，最新在index=0）
        :return: True表示通过快速过滤，False表示未通过
        """
        # 检查数据是否足够
        if len(df) < 2:
            return False

        # 获取最近10个交易日的数据
        lookback_days = self.params['limit_up_lookback_days']
        limit_up_threshold = self.params['limit_up_threshold']

        # 取最近lookback_days+1行数据（数据是倒序的，所以head()取最新的）
        check_df = df.head(lookback_days + 1)

        # 由于数据是倒序的（从新到旧），需要反转后计算涨跌幅
        check_df_asc = check_df.iloc[::-1].reset_index(drop=True)

        # 计算涨跌幅（相对于前一日收盘价）
        pct_change = check_df_asc['close'].pct_change(1)

        # 检查是否有涨停板（涨幅 >= 阈值）
        # 排除第一行（NaN），检查其余行
        has_limit_up = (pct_change.iloc[1:] >= limit_up_threshold).any()

        return has_limit_up

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标（MA、成交量均线） - 简化版本

        优化策略：
        1. 一次性排序数据（从倒序转为正序）
        2. 在正序数据上计算所有指标
        3. 一次性恢复原始顺序
        4. 去除KDJ和MACD计算，只保留必要的指标

        注意：调用此方法前应先进行快速预检查，确保股票有涨停板

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 添加了指标列的DataFrame
        """
        # 检测数据顺序
        try:
            is_descending = df['date'].iloc[0] > df['date'].iloc[-1]
        except (IndexError, KeyError):
            is_descending = False

        # 统一转换为正序计算（从早到晚）
        if is_descending:
            df_calc = df.iloc[::-1].copy().reset_index(drop=True)
        else:
            df_calc = df.copy().reset_index(drop=True)

        # 在正序数据上计算所有指标
        result = df_calc.copy()

        # 标记涨停（向量化操作）
        result['pct_change'] = result['close'].pct_change()
        result['is_limit_up'] = result['pct_change'] >= self.params['limit_up_threshold']
        result = result.drop('pct_change', axis=1)

        # 1. 计算均线（直接在正序数据上计算，避免反转）
        result['ma5'] = result['close'].rolling(window=5, min_periods=1).mean()
        result['ma10'] = result['close'].rolling(window=10, min_periods=1).mean()
        result['ma20'] = result['close'].rolling(window=20, min_periods=1).mean()

        # 2. 计算成交量均线
        result['volume_ma5'] = result['volume'].rolling(window=5, min_periods=1).mean()
        result['volume_ma10'] = result['volume'].rolling(window=10, min_periods=1).mean()

        # 恢复原始顺序
        if is_descending:
            result = result.iloc[::-1].reset_index(drop=True)

        result.index = df.index
        return result

    def _find_limit_up(self, df):
        """
        寻找最近的涨停板 - 检查成交量比

        :param df: 含指标的DataFrame（倒序，最新在index=0）
        :return: 涨停板信息列表，每个元素为 (index, date, close, open, volume)
        """
        lookback_days = self.params['limit_up_lookback_days']

        # 只检查最近的lookback_days个交易日
        check_df = df.head(lookback_days)

        # 使用向量化操作找出所有涨停板
        limit_up_mask = check_df['is_limit_up'].values

        if not limit_up_mask.any():
            return []

        # 计算成交量比（当前成交量 / 前5日均量）
        volumes = check_df['volume'].values

        # 计算前5日均量（由于数据倒序，需要向后看）
        volume_ratios = []
        for i in range(len(volumes)):
            # 前5日是 i+1 到 i+5（数据倒序）
            if i + 5 < len(df):
                prev_5_volumes = df.iloc[i+1:i+6]['volume'].values
                prev_5_mean = prev_5_volumes.mean() if len(prev_5_volumes) > 0 else 0
            else:
                # 如果不足5日，用现有的
                prev_5_volumes = df.iloc[i+1:].iloc[:5]['volume'].values
                prev_5_mean = prev_5_volumes.mean() if len(prev_5_volumes) > 0 else 0

            if prev_5_mean > 0:
                volume_ratios.append(volumes[i] / prev_5_mean)
            else:
                volume_ratios.append(0)

        volume_ratios = np.array(volume_ratios)

        # 找出成交量放大的涨停板
        volume_ok = volume_ratios >= self.params['volume_ratio_threshold']

        # 找出同时满足涨停和成交量放大的位置
        valid_mask = limit_up_mask & volume_ok
        valid_positions = np.where(valid_mask)[0]

        # 如果没有找到符合条件的涨停板，直接返回
        if len(valid_positions) == 0:
            return []

        # 构建涨停板信息列表
        limit_ups = []
        dates = check_df['date'].values
        closes = check_df['close'].values
        opens = check_df['open'].values

        # 直接使用numpy数组索引，避免循环
        for pos in valid_positions:
            limit_ups.append((
                int(pos),  # 涨停板在DataFrame中的位置
                dates[pos],
                closes[pos],
                opens[pos],
                volumes[pos]
            ))

        return limit_ups

    def _check_pullback(self, df, limit_up_info):
        """
        检查涨停后是否出现合理回调 - 向量化优化版本

        回调企稳条件：
        1. 涨停后出现回调1-7天
        2. 回调幅度0%-15%
        3. 回调期间收盘价不破涨停收盘价的95%
        4. 回调期间，收盘价应低于涨停日收盘价

        优化点：
        1. 使用向量化操作计算最高价和最低价
        2. 避免循环操作
        3. 使用numpy的any()函数快速检查条件

        :param df: 含指标的DataFrame（倒序，最新在index=0）
        :param limit_up_info: 涨停板信息 (index, date, close, open, volume)
        :return: 回调信息字典，包含回调天数、幅度、支撑位、是否有成交量萎缩
        """
        # 获取参数
        pullback_days_min = self.params['pullback_days_min']
        pullback_days_max = self.params['pullback_days_max']
        pullback_range_min = self.params['pullback_range_min']
        pullback_range_max = self.params['pullback_range_max']
        volume_shrinkage_ratio = self.params['volume_shrinkage_ratio']
        support_ratio = self.params['support_ratio']

        # 涨停板信息
        lu_idx, lu_date, lu_close, lu_open, lu_volume = limit_up_info

        # 数据是倒序的：index=0是今天(选股日)，index=lu_idx是涨停日，index>lu_idx是涨停日之前(更早)的日子
        # 回调期间 = 涨停日之后（不含当天）= index=0到index=lu_idx-1
        # 涨停后验证窗口：从今天(index=0)到涨停日前一天(index=lu_idx-1)，最多pullback_days_max天
        start_idx = 0
        end_idx = min(lu_idx, pullback_days_max)

        # 检查回调期间的数据
        if end_idx <= start_idx:
            return None

        # 使用向量化操作获取数据
        pullback_df = df.iloc[start_idx:end_idx]
        if pullback_df.empty:
            return None

        # 向量化计算最高价和最低价
        highest_price = pullback_df['high'].max()
        lowest_price = pullback_df['low'].min()

        # 回调幅度：从最高价回撤到最低价的幅度
        pullback_range = (highest_price - lowest_price) / highest_price

        # 检查回调幅度是否在范围内
        if pullback_range < pullback_range_min or pullback_range > pullback_range_max:
            return None

        # 支撑位：涨停收盘价的95%
        support_price = lu_close * support_ratio
        # 阻力位：涨停收盘价的105%
        resistance_price = lu_close * self.params['resistance_ratio']

        # 检查是否不破支撑位（收盘价不破支撑价）
        # 检查回调期间所有收盘价是否都不低于支撑价
        pullback_closes = pullback_df['close'].values
        if np.any(pullback_closes < support_price):
            return None

        # 检查是否超过阻力位（收盘价不超过阻力价）
        # 回调期间所有收盘价应不超过涨停收盘价的105%
        if np.any(pullback_closes > resistance_price):
            return None

        # 新增条件：回调期间，收盘价应低于涨停日收盘价
        # 检查回调期间是否至少有一个收盘价低于涨停日收盘价
        has_lower_close = np.any(pullback_closes < lu_close)
        if not has_lower_close:
            return None

        # 向量化检查成交量萎缩
        pullback_volumes = pullback_df['volume'].values
        volume_threshold = lu_volume * volume_shrinkage_ratio
        has_volume_shrinkage = np.any(pullback_volumes <= volume_threshold)

        # 必须有缩量日
        if not has_volume_shrinkage:
            return None

        # 计算回调天数
        pullback_days = end_idx - start_idx
        # 确保回调天数在范围内
        if pullback_days < pullback_days_min or pullback_days > pullback_days_max:
            return None

        return {
            'pullback_days': pullback_days,
            'pullback_range': pullback_range,
            'lowest_price': lowest_price,
            'highest_price': highest_price,
            'limit_up_open': lu_open,
            'limit_up_close': lu_close,
            'support_price': support_price,
            'has_volume_shrinkage': has_volume_shrinkage
        }

    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []

        # 条件1：涨停确认
        limit_up_lookback_days = self.params['limit_up_lookback_days']
        limit_up_threshold = self.params['limit_up_threshold'] * 100
        volume_ratio_threshold = self.params['volume_ratio_threshold']
        criteria.append(f"1. 涨停确认：最近{limit_up_lookback_days}个交易日内出现涨停板（涨幅>={limit_up_threshold:.1f}%），且成交量是前5日均量的{volume_ratio_threshold:.1f}倍以上")

        # 条件2：回调企稳
        pullback_days_min = self.params['pullback_days_min']
        pullback_days_max = self.params['pullback_days_max']
        pullback_range_min = self.params['pullback_range_min'] * 100
        pullback_range_max = self.params['pullback_range_max'] * 100
        support_ratio = self.params['support_ratio'] * 100
        resistance_ratio = self.params['resistance_ratio'] * 100
        criteria.append(f"2. 回调企稳：涨停后{pullback_days_min}-{pullback_days_max}个交易日内出现回调，回调幅度{pullback_range_min:.0f}%-{pullback_range_max:.0f}%，回调期间收盘价不破涨停收盘价的{support_ratio:.0f}%且不超过{resistance_ratio:.0f}%")

        # 条件3：成交量萎缩
        volume_shrinkage_ratio = self.params['volume_shrinkage_ratio'] * 100
        criteria.append(f"3. 成交量萎缩：回调期间至少一日成交量 <= 涨停日成交量的{volume_shrinkage_ratio:.0f}%")

        return criteria

    def select_stocks(self, data, stock_name="", skip_data_check=False):
        """
        选择符合条件的股票 - 优化版本

        优化点：
        1. 快速预检查只检查涨幅，不计算其他指标
        2. 只有通过预检查的股票才计算完整指标
        3. 避免对无涨停板股票的复杂计算

        :param data: 股票数据（DataFrame或list）
        :param stock_name: 股票代码
        :param skip_data_check: 是否跳过数据检查
        :return: 选中的股票列表
        """
        try:
            # 数据检查
            if not skip_data_check:
                if data is None or (isinstance(data, list) and len(data) == 0):
                    return []

            # 转换为DataFrame
            if not isinstance(data, pd.DataFrame):
                df = pd.DataFrame(data)
            else:
                df = data.copy()

            # 快速预检查：检查是否有涨停板（只检查涨幅，不计算其他指标）
            lookback_days = self.params['limit_up_lookback_days']
            limit_up_threshold = self.params['limit_up_threshold']

            # 只取需要的列，提高速度
            # 注意：数据是倒序的（最新在index=0），所以需要计算相对于下一行（更早日期）的变化
            check_df = df[['close']].head(lookback_days + 1)

            # 向量化计算涨跌幅
            # 对于倒序数据，涨幅 = (当前close - 前一日close) / 前一日close
            # 前一日在倒序数据中是 index+1
            has_limit_up = False
            for i in range(len(check_df) - 1):
                if i + 1 < len(check_df):
                    pct_change = (check_df.iloc[i]['close'] - check_df.iloc[i + 1]['close']) / check_df.iloc[i + 1]['close']
                    if pct_change >= limit_up_threshold:
                        has_limit_up = True
                        break

            # 如果没有涨停板，直接返回空列表
            if not has_limit_up:
                return []

            # 计算指标（只有有涨停板的股票才会到达这里）
            df_with_indicators = self.calculate_indicators(df)

            # 寻找涨停板
            limit_ups = self._find_limit_up(df_with_indicators)
            if not limit_ups:
                return []

            # 检查回调条件
            for lu_info in limit_ups:
                pullback_info = self._check_pullback(df_with_indicators, lu_info)
                if pullback_info:
                    # 格式化日期
                    limit_up_date = lu_info[1]
                    if hasattr(limit_up_date, 'strftime'):
                        limit_up_date_str = limit_up_date.strftime('%Y-%m-%d')
                    else:
                        limit_up_date_str = str(limit_up_date)[:10]

                    support_ratio = self.params['support_ratio'] * 100
                    signal = {
                        'key_date': limit_up_date_str,
                        'key_date_type': '涨停日',
                        'reasons': [
                            f"涨停日期: {limit_up_date_str}",
                            f"涨停价格: {float(lu_info[2]):.2f}",
                            f"回调天数: {pullback_info['pullback_days']}",
                            f"回调幅度: {pullback_info['pullback_range']:.2%}",
                            f"支撑位: {pullback_info['support_price']:.2f}（涨停收盘×{support_ratio:.0f}%）"
                        ]
                    }
                    return [signal]

            return []

        except Exception:
            return []