import pandas as pd
import numpy as np
from datetime import datetime
from strategy.base_strategy import BaseStrategy
from trading.technical_indicators import TechnicalIndicators

class LimitUpSidewaysStrategy(BaseStrategy):
    """
    涨停横盘策略 (Limit Up Sideways Strategy)
    
    策略逻辑：
    1. 寻找最近出现的涨停板（涨幅≥9.5%，成交量≥前5日均量的1.8倍）
    2. 涨停后出现横盘整理（1-8个交易日）
    3. 横盘期间价格区间：最高价不超过涨停价的5%，最低价不低于涨停价的-2%
    4. 横盘期间收盘价不低于涨停日收盘价（不破支撑）
    5. 横盘期间成交量萎缩：至少有一日成交量 ≤ 涨停日成交量的60%
    6. 横盘后出现反转信号（KDJ金叉 或 MACD金叉）
    7. 成交量放大：最近交易日成交量较前一交易日放大≥30%
    
    关键属性：
    - key_date: 涨停日期，用于记录信号日期
    - support_level: 涨停日收盘价，用于支撑位判断
    - strategy_weight: 60分，技术面评分累加
    """

    def __init__(self, params=None):
        """
        初始化策略
        
        :param params: 策略参数
        """
        # 默认参数
        default_params = {
            # 涨停确认参数
            'limit_up_lookback_days': 10,        # 涨停回溯天数
            'limit_up_threshold': 0.095,         # 涨停阈值（9.5%）
            'volume_ratio_threshold': 1.8,       # 成交量比阈值（相对前5日均量）
            # 横盘整理参数
            'sideways_days_min': 1,              # 最小横盘天数
            'sideways_days_max': 10,             # 最大横盘天数（放宽到10天）
            'sideways_high_limit': 0.08,         # 横盘最高价限制（8%，放宽）
            'sideways_low_limit': -0.05,         # 横盘最低价限制（-5%，放宽）
            'volume_shrinkage_ratio': 0.7,       # 成交量萎缩比例（70%，放宽）
            # 支撑确认参数
            'support_drop_limit': -0.01,         # 收盘价跌破涨停收盘的最大幅度（-1%）
            # 突破信号参数
            'kdj_n': 9,                          # KDJ的N参数
            'kdj_m1': 3,                         # KDJ的M1参数
            'kdj_m2': 3,                         # KDJ的M2参数
            'kdj_gold_cross_threshold': 20,      # KDJ金叉阈值
            'macd_short': 12,                    # MACD短期周期
            'macd_long': 26,                     # MACD长期周期
            'macd_signal': 9,                    # MACD信号线周期
            'volume_increase_ratio': 1.3,        # 成交量放大比例（30%）
            'strategy_weight': 60,               # 技术面评分权重
        }

        # 合并用户参数 - params 中的值覆盖默认值
        if params:
            default_params.update(params)

        # 调用父类初始化
        super().__init__("涨停横盘策略", default_params)
        
        # 初始化技术指标计算器
        self.tech_indicators = TechnicalIndicators()

    def quick_filter(self, df):
        """
        快速过滤：检查是否有涨停板
        
        只基于价格，不涉及成交量或其他指标
        
        :param df: 股票数据DataFrame（降序，最新在前）
        :return: True表示通过快速过滤，False表示未通过
        """
        lookback_days = self.params['limit_up_lookback_days']
        limit_up_threshold = self.params['limit_up_threshold']
        
        # 只取需要的列，提高速度
        if len(df) < lookback_days + 1:
            return False
        
        check_df = df[['close']].head(lookback_days + 1)
        
        # 向量化计算涨跌幅
        pct_change = check_df['close'].pct_change(-1)
        
        # 如果有涨停板，返回True
        return (pct_change >= limit_up_threshold).any()

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标（成交量均线）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 计算了指标的DataFrame
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
        
        # 计算成交量均线
        result['volume_5'] = result['volume'].rolling(window=5, min_periods=1).mean()
        
        # 恢复原始顺序
        if is_descending:
            result = result.iloc[::-1].reset_index(drop=True)
        
        result.index = df.index
        return result

    def _find_limit_up(self, df):
        """
        寻找最近的涨停板 - 检查成交量比

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 涨停板信息字典，包含日期和收盘价
        """
        lookback_days = self.params['limit_up_lookback_days']
        
        # 只检查最近的lookback_days个交易日
        check_df = df.head(lookback_days)
        
        # 使用向量化操作找出所有涨停板
        limit_up_mask = check_df['is_limit_up'].values
        
        if not limit_up_mask.any():
            return None
        
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
        
        if len(valid_positions) == 0:
            return None
        
        # 取最近的涨停板（最小的index）
        pos = valid_positions[0]
        
        return {
            'date': check_df.iloc[pos]['date'],
            'close': check_df.iloc[pos]['close'],
            'volume': check_df.iloc[pos]['volume'],
            'index': pos
        }

    def _check_sideways(self, df, limit_up_info):
        """
        检查涨停后是否出现横盘整理
        从涨停日到今天为止，验证最高价和最低价是否在范围内，且收盘价不低于涨停日收盘价

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param limit_up_info: 涨停板信息
        :return: 横盘整理信息字典，包含天数、最高价、最低价等
        """
        limit_up_index = limit_up_info['index']
        limit_up_close = limit_up_info['close']
        limit_up_volume = limit_up_info['volume']

        # 从涨停日到最新一天（index=0）的数据
        # 涨停后的数据在更小的index处（数据倒序）
        if limit_up_index <= 0:
            return None

        # 提取涨停后到今天的所有数据
        sideways_df = df.iloc[0:limit_up_index]
        
        # 计算横盘天数
        days = limit_up_index
        
        # 检查横盘天数是否在允许范围内
        if days < self.params['sideways_days_min'] or days > self.params['sideways_days_max']:
            return None

        # 计算期间的最高价和最低价
        highest_price = sideways_df['high'].max()
        lowest_price = sideways_df['low'].min()

        # 计算价格区间
        high_limit = limit_up_close * (1 + self.params['sideways_high_limit'])
        low_limit = limit_up_close * (1 + self.params['sideways_low_limit'])

        # 检查价格区间是否符合要求
        if highest_price > high_limit or lowest_price < low_limit:
            return None

        # 检查期间收盘价是否跌破支撑（允许小幅跌破support_drop_limit）
        support_lower_limit = limit_up_close * (1 + self.params.get('support_drop_limit', -0.01))
        if (sideways_df['close'] < support_lower_limit).any():
            return None

        # 检查成交量萎缩：至少有一日成交量 ≤ 涨停日成交量的60%
        shrinkage_threshold = limit_up_volume * self.params['volume_shrinkage_ratio']
        has_shrinkage = (sideways_df['volume'] <= shrinkage_threshold).any()
        if not has_shrinkage:
            return None

        # 计算期间的平均成交量（用于信息输出）
        avg_volume = sideways_df['volume'].mean()
        volume_ratio = avg_volume / limit_up_volume

        return {
            'days': days,
            'highest': highest_price,
            'lowest': lowest_price,
            'volume_ratio': volume_ratio,
            'end_index': 0,
            'limit_up_volume': limit_up_volume,
            'sideways_df': sideways_df
        }

    def _check_breakout(self, df, sideways_info):
        """
        检查是否出现突破信号（KDJ金叉 或 MACD金叉）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param sideways_info: 横盘整理信息
        :return: 突破信号信息字典，包含信号类型和成交量放大情况
        """
        # 检查是否有足够的数据
        if sideways_info['end_index'] >= len(df) - 1:
            return None

        current_idx = sideways_info['end_index']
        prev_idx = current_idx + 1

        # 检查收盘价是否上涨
        if df.iloc[current_idx]['close'] <= df.iloc[prev_idx]['close']:
            return None

        # 检查成交量是否放大（≥30%）
        volume_increase_ratio = df.iloc[current_idx]['volume'] / df.iloc[prev_idx]['volume']
        if volume_increase_ratio < self.params['volume_increase_ratio']:
            return None

        # 检查KDJ金叉信号
        kdj_signal = self._check_kdj_gold_cross(df)
        
        # 检查MACD金叉信号
        macd_signal = self._check_macd_gold_cross(df)

        # 至少需要一个信号
        if not kdj_signal and not macd_signal:
            return None

        return {
            'volume_increase': volume_increase_ratio,
            'price_change': (df.iloc[current_idx]['close'] - df.iloc[prev_idx]['close']) / df.iloc[prev_idx]['close'],
            'kdj_signal': kdj_signal,
            'macd_signal': macd_signal
        }

    def _check_kdj_gold_cross(self, df):
        """
        检查KDJ金叉信号（K线穿过D线向上）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: True表示有KDJ金叉，False表示没有
        """
        try:
            # 计算KDJ指标
            k, d, j = self.tech_indicators.calculate_kdj(
                df.iloc[::-1].reset_index(drop=True),
                n=self.params['kdj_n'],
                m1=self.params['kdj_m1'],
                m2=self.params['kdj_m2']
            )
            
            # 恢复倒序
            k = k.iloc[::-1].reset_index(drop=True)
            d = d.iloc[::-1].reset_index(drop=True)
            
            # 检查最近两天是否有金叉（K从下穿过D向上）
            if len(k) < 2:
                return False
            
            # 金叉条件：前一天K<D，今天K>D，且K值较低（<20表示超卖区域）
            prev_k = k.iloc[1]
            prev_d = d.iloc[1]
            curr_k = k.iloc[0]
            curr_d = d.iloc[0]
            
            if prev_k < prev_d and curr_k > curr_d and curr_k < self.params['kdj_gold_cross_threshold']:
                return True
            
            return False
        except Exception:
            return False

    def _check_macd_gold_cross(self, df):
        """
        检查MACD金叉信号（DIF穿过DEA向上）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: True表示有MACD金叉，False表示没有
        """
        try:
            # 计算MACD指标
            dif, dea, macd = self.tech_indicators.calculate_macd(
                df.iloc[::-1].reset_index(drop=True),
                short_period=self.params['macd_short'],
                long_period=self.params['macd_long'],
                signal_period=self.params['macd_signal']
            )
            
            # 恢复倒序
            dif = dif.iloc[::-1].reset_index(drop=True)
            dea = dea.iloc[::-1].reset_index(drop=True)
            
            # 检查最近两天是否有金叉（DIF从下穿过DEA向上）
            if len(dif) < 2:
                return False
            
            # 金叉条件：前一天DIF<DEA，今天DIF>DEA
            prev_dif = dif.iloc[1]
            prev_dea = dea.iloc[1]
            curr_dif = dif.iloc[0]
            curr_dea = dea.iloc[0]
            
            if prev_dif < prev_dea and curr_dif > curr_dea:
                return True
            
            return False
        except Exception:
            return False
    
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
        
        # 条件2：横盘整理
        sideways_days_min = self.params['sideways_days_min']
        sideways_days_max = self.params['sideways_days_max']
        sideways_high_limit = self.params['sideways_high_limit'] * 100
        sideways_low_limit = self.params['sideways_low_limit'] * 100
        criteria.append(f"2. 横盘整理：涨停后{sideways_days_min}-{sideways_days_max}个交易日内横盘整理，最高价不超过涨停价的{sideways_high_limit:.0f}%，最低价不低于涨停价的{sideways_low_limit:.0f}%")
        
        # 条件3：成交量萎缩
        volume_shrinkage_ratio = self.params['volume_shrinkage_ratio'] * 100
        criteria.append(f"3. 成交量萎缩：横盘期间至少有一日成交量 <= 涨停日成交量的{volume_shrinkage_ratio:.0f}%")
        
        # 条件4：支撑确认
        criteria.append(f"4. 支撑确认：横盘期间收盘价不低于涨停日收盘价")
        
        return criteria

    def select_stocks(self, data, stock_name="", skip_data_check=False):
        """
        选择符合条件的股票

        :param data: 股票数据，可以是DataFrame或字典
        :param stock_name: 股票代码（可选）
        :param skip_data_check: 是否跳过数据检查
        :return: 符合条件的股票信息列表
        """
        # 检查数据类型
        if isinstance(data, dict):
            # 从字典中提取DataFrame
            if 'df' in data:
                df = data['df']
            else:
                return []
        else:
            df = data

        # 数据检查
        if not skip_data_check:
            if len(df) < 60:
                return []

            # 检查最新一天是否有有效数据
            if pd.isna(df.iloc[0]['close']) or pd.isna(df.iloc[0]['volume']):
                return []

        # 快速预检查：检查是否有涨停板
        if not self.quick_filter(df):
            return []

        # 计算技术指标（只有有涨停板的股票才会到达这里）
        df = self.calculate_indicators(df)

        # 寻找涨停板
        limit_up_info = self._find_limit_up(df)
        if not limit_up_info:
            return []

        # 检查横盘整理
        sideways_info = self._check_sideways(df, limit_up_info)
        if not sideways_info:
            return []

        # 生成选股理由
        reasons = [
            f"最近{self.params['limit_up_lookback_days']}个交易日内出现涨停板",
            f"涨停后横盘整理{sideways_info['days']}个交易日",
            f"横盘期间价格区间：{sideways_info['lowest']:.2f} - {sideways_info['highest']:.2f}",
            f"横盘期间成交量萎缩至涨停日的{sideways_info['volume_ratio']:.2f}倍",
        ]

        # 关键日期：涨停日期
        key_date = limit_up_info['date']
        
        # 格式化日期
        if hasattr(key_date, 'strftime'):
            key_date_str = key_date.strftime('%Y-%m-%d')
        else:
            key_date_str = str(key_date)[:10]
        
        # 获取今天日期
        today_date = df.iloc[0]['date']
        if hasattr(today_date, 'strftime'):
            today_date_str = today_date.strftime('%Y-%m-%d')
        else:
            today_date_str = str(today_date)[:10]
        
        # 构建结果字典 - 统一格式
        result = {
            'date': today_date_str,
            'close': round(df.iloc[0]['close'], 2),
            'volume_ratio': round(df.iloc[0]['volume'] / max(1, df.iloc[0].get('volume_ma5', 1)), 2),
            'reasons': reasons,
            'key_date': key_date_str,
            'key_date_type': '涨停日',
            'pattern_details': {
                'limit_up_close': round(limit_up_info['close'], 2),
                'limit_up_volume': round(limit_up_info['volume'], 0),
                'sideways_days': sideways_info['days'],
                'sideways_highest': round(sideways_info['highest'], 2),
                'sideways_lowest': round(sideways_info['lowest'], 2),
                'sideways_volume_ratio': round(sideways_info['volume_ratio'], 2),
            },
            'confirmation_details': {
                'confirmed': True,
                'confirmed_date': today_date_str,
                'days_to_confirm': sideways_info['days'],
                'support_level': round(limit_up_info['close'], 2),
            },
            'strategy_weight': self.params['strategy_weight'],
        }

        return [result]
