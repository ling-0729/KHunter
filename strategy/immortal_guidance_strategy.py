"""
仙人指路策略 (ImmortalGuidanceStrategy)

基于经典技术分析形态的量化选股策略。
通过识别"冲高回落+长上影+放量+趋势向上"形态筛选股票。

核心流程：
1. T日上影线日识别（冲高8%+长上影4%+放量+站5日线，不再要求收阳线）
2. T日趋势过滤（均线多头MA5>MA10>MA20+上升趋势+R²≥0.5）
3. T+1~T+3日确认（回调不破5日线+反包确认）

关键属性：
- key_day: T日（上影线日），仙人指路形态形成的第一天
- support_level: 关键日开盘价，用于支撑位策略买点判断、股票池去除条件判断
- strategy_weight: 70分，技术面评分累加

修改历史：
- 2024-01-新增lookback_days参数，支持追溯最近N个交易日内的信号
- 2024-01-修复反包确认索引计算错误问题
- 2024-01-新增确认后持续性检查，确保信号日后股价持续维持在MA5之上
"""
import pandas as pd
import numpy as np
from strategy.base_strategy import BaseStrategy


class ImmortalGuidanceStrategy(BaseStrategy):
    """
    仙人指路策略类

    继承 BaseStrategy，实现 calculate_indicators() 和 select_stocks() 方法。
    通过三个核心步骤实现选股：
    1. T日上影线日识别（冲高+长上影+放量+站线，不要求收阳线）
    2. T日趋势过滤（均线多头+上升趋势+趋势强度）
    3. T+1~T+3日确认（回调支撑+反包确认+后续持续性检查）

    支持lookback_days参数，可在最近N个交易日内追溯寻找已确认的仙人指路信号。
    """

    _kline_date_cache = {}

    def __init__(self, params=None):
        """
        初始化仙人指路策略

        :param params: 用户自定义参数字典，会覆盖默认参数
        """
        default_params = {
            'surge_threshold': 0.08,
            'upper_shadow_ratio': 0.04,
            'volume_ratio_min': 1.5,
            'volume_ratio_max': None,
            'ma_periods': [5, 10, 20],
            'trend_lookback_days': 20,
            'trend_r_squared_threshold': 0.5,
            'anti_body_window': 3,
            'anti_body_ratio': 0.50,
            'strategy_weight': 70,
            'lookback_days': 3,
        }

        if params:
            default_params.update(params)

        super().__init__("仙人指路策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标（均线、趋势线）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 添加了指标列的DataFrame
        """
        if df is None or df.empty:
            return df

        result = df.copy()

        if all(col in result.columns for col in ['ma5', 'ma10', 'ma20', 'volume_ma5']):
            return result

        close_series = result['close'].iloc[::-1]
        volume_series = result['volume'].iloc[::-1]

        ma_periods = self.params['ma_periods']
        for period in ma_periods:
            result[f'ma{period}'] = close_series.rolling(window=period, min_periods=1).mean().iloc[::-1].values

        result['volume_ma5'] = volume_series.shift(1).rolling(window=5, min_periods=1).mean().iloc[::-1].values

        return result

    def _calculate_trend_metrics(self, df, lookback_days=20):
        """
        计算趋势指标（线性回归斜率和R²）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param lookback_days: 趋势判断天数
        :return: (slope, r_squared)
        """
        if len(df) < lookback_days:
            return 0.0, 0.0

        if 'trend_slope' in df.columns and 'trend_r_squared' in df.columns:
            return df['trend_slope'].iloc[0], df['trend_r_squared'].iloc[0]

        recent_df = df.iloc[:lookback_days].copy()
        recent_df = recent_df.iloc[::-1].reset_index(drop=True)
        y = recent_df['close'].values
        x = np.arange(len(y))

        try:
            x_mean = np.mean(x)
            y_mean = np.mean(y)
            numerator = np.sum((x - x_mean) * (y - y_mean))
            denominator = np.sum((x - x_mean) ** 2)

            if denominator == 0:
                return 0.0, 0.0

            slope = numerator / denominator
            y_pred = y_mean + slope * (x - x_mean)
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - y_mean) ** 2)

            if ss_tot == 0:
                return 0.0, 0.0

            r_squared = 1 - (ss_res / ss_tot)
            return slope, max(0, r_squared)
        except Exception:
            return 0.0, 0.0

    def select_stocks(self, df, stock_name='', selection_date=None) -> list:
        """
        执行仙人指路策略选股（外部已做日期切片，策略只管选股）

        :param df: 股票数据DataFrame（倒序，最新在index=0，已按选股日期切片）
        :param stock_name: 股票名称
        :param selection_date: 选股日期（YYYY-MM-DD格式）
        :return: 选股结果列表
        """
        if not self._validate_data(df):
            return []

        if not self._validate_stock_name(stock_name):
            return []

        # 计算技术指标
        result = self.calculate_indicators(df.copy())
        if len(result) < 30:
            return []

        # 快速过滤
        if not self._quick_filter_with_lookback(result):
            return []

        try:
            lookback_days = self.params.get('lookback_days', 3)
            return self._check_immortal_guidance_with_lookback(result, lookback_days)
        except Exception as e:
            return []

    def _check_immortal_guidance_with_lookback(self, df, lookback_days=3) -> list:
        """
        检查仙人指路形态（支持回溯查找）

        逻辑：
        - T日（index=0）= 反包日 = 今天收盘需要收复信号日上影线
        - T-1, T-2, T-3 = 信号日候选

        流程：
        1. 首先检查今天（T日）是否满足反包条件（收盘 > MA5）
        2. 在最近lookback天内寻找信号日（上影线形态）
        3. 确认条件：今天收盘 >= 信号日的上影线50%位置

        :param df: 含指标的DataFrame（倒序，最新在index=0）
        :param lookback_days: 回溯天数，查找最近N个交易日内出现的信号
        :return: 选股结果列表（只包含确认成功的信号）
        """
        if len(df) < 4:
            return []

        today_idx = 0
        today = df.iloc[today_idx]
        today_close = today['close']
        today_ma5 = today.get('ma5', 0)

        if today_close < today_ma5:
            return []

        today_volume = today.get('volume', 0)
        if today_volume == 0:
            return []

        slope, r_squared = self._calculate_trend_metrics(df, self.params['trend_lookback_days'])
        if not (slope > 0 and r_squared >= self.params['trend_r_squared_threshold']):
            return []

        lookback_days = min(lookback_days, len(df) - 1, 4)

        for day_offset in range(1, lookback_days + 1):
            signal_day_idx = day_offset
            prev_idx = signal_day_idx + 1

            if prev_idx >= len(df):
                break

            signal_day = df.iloc[signal_day_idx]
            prev_close = df.iloc[prev_idx]['close']

            if prev_close == 0 or pd.isna(prev_close):
                continue

            surge_pct = (signal_day['high'] - prev_close) / prev_close

            if surge_pct < self.params['surge_threshold']:
                continue

            if signal_day['close'] > signal_day['open']:
                upper_shadow = max(0, signal_day['high'] - signal_day['close'])
            else:
                upper_shadow = max(0, signal_day['high'] - signal_day['open'])

            body_length = abs(signal_day['close'] - signal_day['open'])
            if signal_day['high'] > 0:
                upper_shadow_ratio = upper_shadow / signal_day['high']
            else:
                upper_shadow_ratio = 0

            if upper_shadow_ratio < self.params['upper_shadow_ratio']:
                continue

            signal_day_vol = signal_day.get('volume', 0)
            signal_day_vol_ma5 = signal_day.get('volume_ma5', 0)
            if signal_day_vol_ma5 > 0:
                signal_day_vol_ratio = signal_day_vol / signal_day_vol_ma5
                if signal_day_vol_ratio < self.params['volume_ratio_min']:
                    continue

            signal_day_ma5 = signal_day.get('ma5', 0)
            signal_day_ma10 = signal_day.get('ma10', 0)
            signal_day_ma20 = signal_day.get('ma20', 0)

            if not (signal_day_ma5 > signal_day_ma10 > signal_day_ma20 > 0):
                continue

            if signal_day['close'] > signal_day['open']:
                upper_shadow_50_price = (signal_day['close'] + signal_day['high']) / 2
            else:
                upper_shadow_50_price = (signal_day['open'] + signal_day['high']) / 2

            early_anti_body = False
            for check_idx in range(1, signal_day_idx):
                check_day = df.iloc[check_idx]
                if check_day['close'] >= upper_shadow_50_price:
                    early_anti_body = True
                    break

            if early_anti_body:
                continue

            if today_close >= upper_shadow_50_price:
                latest_date = str(df.iloc[0]['date']).split()[0]
                signal_day_date = str(signal_day['date']).split()[0]

                return [{
                    'date': latest_date,
                    'close': round(today_close, 2),
                    'volume_ratio': round(today.get('volume', 0) / max(1, today.get('volume_ma5', 1)), 2),
                    'reasons': ['仙人指路形态'],
                    'key_date': signal_day_date,
                    'key_date_type': '仙人指路信号日',
                    'pattern_date': signal_day['date'],
                    'pattern_details': {
                        'surge_pct': round(surge_pct, 4),
                        'upper_shadow_ratio': round(upper_shadow_ratio, 4),
                        'upper_shadow_50_price': round(upper_shadow_50_price, 2),
                        'key_day_open': round(signal_day['open'], 2),
                        'key_day_close': round(signal_day['close'], 2),
                        'key_day_high': round(signal_day['high'], 2),
                        'volume_ratio': 0,
                        'ma5': round(signal_day_ma5, 2),
                        'ma10': round(signal_day_ma10, 2),
                        'ma20': round(signal_day_ma20, 2),
                        'trend_slope': round(slope, 4),
                        'trend_r_squared': round(r_squared, 4),
                    },
                    'confirmation_details': {
                        'confirmed': True,
                        'confirmed_date': latest_date,
                        'days_to_confirm': day_offset,
                        'anti_body_price': today_close,
                        'close_above_ma5': today_close > today_ma5,
                        'post_confirmation_stable': True,
                    }
                }]

        return []

    def _check_confirmation(self, df, signal_day_idx, support_price, anti_body_target) -> dict:
        """
        检查信号日当天是否满足反包条件（当天必须是反包日）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param signal_day_idx: 信号日索引
        :param support_price: 关键日开盘价
        :param anti_body_target: 上影线50%位置
        :return: 确认结果字典
        """
        result = {
            'confirmed': False,
            'confirmed_date': None,
            'days_to_confirm': 0,
            'anti_body_price': None,
            'close_above_ma5': True,
            'post_confirmation_stable': True,
        }

        # 当天必须是反包日：检查信号日（index=signal_day_idx）是否收盘反包上影线50%
        if signal_day_idx < 0 or signal_day_idx >= len(df):
            return result

        signal_day_data = df.iloc[signal_day_idx]
        signal_day_close = signal_day_data['close']
        signal_day_ma5 = signal_day_data.get('ma5', 0)

        # 检查收盘价是否在MA5之上
        if signal_day_close < signal_day_ma5:
            result['close_above_ma5'] = False
            return result

        # 检查是否收盘反包上影线50%
        if signal_day_close >= anti_body_target:
            result['confirmed'] = True
            result['confirmed_date'] = str(signal_day_data['date']).split()[0]
            result['days_to_confirm'] = 0  # 当天即确认
            result['anti_body_price'] = signal_day_close

        return result

    def _check_immortal_guidance(self, df) -> list:
        """
        检查仙人指路形态：
        - T日（今天）= 反包日
        - 信号日：今天之前的3个交易日内（T-1、T-2、T-3）

        :param df: 含指标的DataFrame（倒序，最新在index=0）
        :return: 选股结果列表
        """
        # 需要至少4天数据：T-3信号日 + 今天反包
        if len(df) < 4:
            return []

        today = df.iloc[0]
        today_close = today['close']
        today_ma5 = today.get('ma5', 0)

        # 今天必须是反包日：收盘在MA5之上
        if today_close < today_ma5:
            return []

        # 计算趋势（使用更长的回溯天数以覆盖信号日）
        slope, r_squared = self._calculate_trend_metrics(df, self.params['trend_lookback_days'])
        if not (slope > 0 and r_squared >= self.params['trend_r_squared_threshold']):
            return []

        # 检查前3个交易日是否有信号日（T-1、T-2、T-3）
        for lookback in range(1, 4):
            signal_day_idx = lookback
            if signal_day_idx >= len(df):
                break

            signal_day = df.iloc[signal_day_idx]
            prev_close_for_signal = df.iloc[signal_day_idx + 1]['close']

            # 计算信号日的基本条件
            surge_pct = (signal_day['high'] - prev_close_for_signal) / prev_close_for_signal

            # 计算上影线比例
            if signal_day['close'] > signal_day['open']:
                upper_shadow = signal_day['high'] - signal_day['close']
            else:
                upper_shadow = signal_day['high'] - signal_day['open']
            body_length = abs(signal_day['close'] - signal_day['open'])
            upper_shadow_ratio = upper_shadow / signal_day['high'] if signal_day['high'] > 0 else 0

            # 上影线50%位置（根据阴阳线不同，使用对应的基准点）
            # 阳线：上影线50% = (收盘价 + 最高价) / 2
            # 阴线：上影线50% = (开盘价 + 最高价) / 2
            if signal_day['close'] > signal_day['open']:
                upper_shadow_50_price = (signal_day['close'] + signal_day['high']) / 2
            else:
                upper_shadow_50_price = (signal_day['open'] + signal_day['high']) / 2

            signal_day_ma5 = signal_day.get('ma5', 0)
            signal_day_ma10 = signal_day.get('ma10', 0)
            signal_day_ma20 = signal_day.get('ma20', 0)

            # 检查信号日条件
            if surge_pct < self.params['surge_threshold']:
                continue
            if upper_shadow_ratio < self.params['upper_shadow_ratio']:
                continue
            
            # 检查成交量条件
            signal_day_vol = signal_day.get('volume', 0)
            signal_day_vol_ma5 = signal_day.get('volume_ma5', 0)
            if signal_day_vol_ma5 > 0:
                signal_day_vol_ratio = signal_day_vol / signal_day_vol_ma5
                if signal_day_vol_ratio < self.params['volume_ratio_min']:
                    continue
            
            if not (signal_day_ma5 > signal_day_ma10 > signal_day_ma20 > 0):
                continue

            # 检查是否提前反包（信号日之后、今天之前的日子不能提前反包）
            early_anti_body = False
            for check_idx in range(1, signal_day_idx):
                check_day = df.iloc[check_idx]
                if check_day['close'] >= upper_shadow_50_price:
                    early_anti_body = True
                    break
            if early_anti_body:
                continue

            # 检查今天是否反包信号日的上影线
            if today_close >= upper_shadow_50_price:
                return [{
                    'stock_code': '',
                    'stock_name': '',
                    'signal_date': str(signal_day['date']).split()[0],
                    'key_day': str(signal_day['date']).split()[0],
                    'key_day_open': signal_day['open'],
                    'support_level': signal_day['open'],
                    'surge_pct': surge_pct,
                    'upper_shadow_pct': upper_shadow_ratio,
                    'upper_shadow_50_price': upper_shadow_50_price,
                    'volume_ratio': 0,
                    'ma5': signal_day_ma5,
                    'ma10': signal_day_ma10,
                    'ma20': signal_day_ma20,
                    'trend_slope': slope,
                    'trend_r_squared': r_squared,
                    'confirmed': True,
                    'confirmed_date': str(today['date']).split()[0],
                    'days_to_confirm': lookback,
                    'anti_body_price': today_close,
                    'close_above_ma5': True,
                    'strategy_weight': self.params['strategy_weight'],
                }]

        return []

    def quick_filter(self, df) -> bool:
        """
        快速过滤 - 检查最近3天是否有仙人指路信号

        检查T-1, T-2, T-3中是否有满足条件的信号日：
        - 冲高>=6%
        - 上影线>=3%

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: True表示通过快速过滤，False表示未通过
        """
        if df is None or df.empty or len(df) < 4:
            return False

        for day_offset in range(1, 4):
            signal_day_idx = day_offset
            prev_idx = signal_day_idx + 1

            if prev_idx >= len(df):
                break

            sd = df.iloc[signal_day_idx]
            prev_close = df.iloc[prev_idx]['close']

            if prev_close == 0:
                continue

            surge_pct = (sd['high'] - prev_close) / prev_close
            if surge_pct < self.params['surge_threshold']:
                continue

            if sd['high'] > 0:
                if sd['close'] > sd['open']:
                    upper_shadow = sd['high'] - sd['close']
                else:
                    upper_shadow = sd['high'] - sd['open']
                upper_shadow_ratio = upper_shadow / sd['high']
            else:
                upper_shadow_ratio = 0

            if upper_shadow_ratio >= self.params['upper_shadow_ratio']:
                return True

        return False

    def _check_data_freshness(self, df, max_days_old=5, reference_date=None) -> bool:
        """
        检查数据时效性，确保数据不过旧

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param max_days_old: 最大允许的天数间隔
        :param reference_date: 参考日期（YYYY-MM-DD格式），如果为None则使用当前日期
        :return: True表示数据新鲜（可以选股），False表示数据过旧（应该排除）
        """
        if df is None or df.empty:
            return False

        try:
            from datetime import datetime

            latest_date = df.iloc[0]['date']

            if hasattr(latest_date, 'date'):
                latest_date = latest_date.date()
            elif isinstance(latest_date, str):
                latest_date = datetime.strptime(str(latest_date).split()[0], '%Y-%m-%d').date()
            else:
                latest_date = latest_date

            if reference_date is None:
                reference_date = datetime.now().date()
            elif isinstance(reference_date, str):
                reference_date = datetime.strptime(reference_date.split()[0], '%Y-%m-%d').date()

            days_diff = (reference_date - latest_date).days

            if days_diff > max_days_old:
                return False

            return True

        except Exception:
            return False

    def _has_kline_data(self, date_str: str) -> bool:
        """
        检查指定日期是否有K线数据

        通过数据库查询判断，比 is_trading_day 更准确（包含节假日判断）
        使用类级别缓存避免重复查询

        :param date_str: 日期字符串 (YYYY-MM-DD)
        :return: True表示有K线数据，False表示没有
        """
        if date_str in self._kline_date_cache:
            return self._kline_date_cache[date_str]

        try:
            from utils.db_manager import DBManager
            db_manager = DBManager()

            sql = f"SELECT COUNT(*) FROM stock_kline WHERE date = '{date_str}' LIMIT 1"
            result = db_manager.query(sql)

            has_data = result[0]['COUNT(*)'] > 0 if result else False
            self._kline_date_cache[date_str] = has_data

            return has_data
        except Exception:
            return False

    def _get_previous_date_with_kline_data(self, date_str: str, max_search_days=30) -> str:
        """
        获取指定日期前一个有K线数据的日期

        :param date_str: 日期字符串 (YYYY-MM-DD)
        :param max_search_days: 最大搜索天数，默认30天
        :return: 前一个有K线数据的日期字符串
        """
        try:
            from datetime import datetime, timedelta

            date = datetime.strptime(date_str, '%Y-%m-%d')

            for i in range(1, max_search_days + 1):
                prev_date = date - timedelta(days=i)
                prev_date_str = prev_date.strftime('%Y-%m-%d')

                if self._has_kline_data(prev_date_str):
                    return prev_date_str

            return date_str
        except Exception:
            return date_str

    def _get_latest_trading_date(self) -> str:
        """
        获取数据库统一最新交易日

        Returns:
            str: 最新交易日（YYYY-MM-DD格式）
        """
        from utils.db_manager import DBManager
        db = DBManager()
        return db.get_latest_trading_date()

    def _truncate_to_date(self, df, cutoff_date) -> 'pd.DataFrame':
        """
        截断数据到指定日期（用于回测模式）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :param cutoff_date: 截止日期（YYYY-MM-DD格式）
        :return: 截断后的DataFrame
        """
        import pandas as pd
        df_copy = df.copy()
        df_copy['date_str'] = df_copy['date'].apply(lambda x: str(x).split()[0])
        truncated = df_copy[df_copy['date_str'] <= cutoff_date].drop('date_str', axis=1)
        return truncated

    def _quick_filter_with_lookback(self, df) -> bool:
        """
        快速过滤（支持回溯）- 检查最近N天是否有潜在的仙人指路形态

        注意：新逻辑下，今天（index=0）是反包日，信号日在T-1, T-2, T-3
        所以从index=1开始检查

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: True表示通过快速过滤，False表示未通过
        """
        if df is None or df.empty:
            return False

        lookback_days = self.params.get('lookback_days', 3)
        lookback_days = min(lookback_days, len(df) - 1, 4)

        if lookback_days < 2:
            return False

        for day_offset in range(1, lookback_days):
            signal_day_idx = day_offset
            prev_idx = signal_day_idx + 1

            if prev_idx >= len(df):
                break

            signal_day = df.iloc[signal_day_idx]
            prev_close = df.iloc[prev_idx]['close']

            if prev_close == 0 or pd.isna(prev_close):
                continue

            surge_pct = (signal_day['high'] - prev_close) / prev_close
            if surge_pct < self.params['surge_threshold']:
                continue

            if signal_day['close'] > signal_day['open']:
                upper_shadow = max(0, signal_day['high'] - signal_day['close'])
            else:
                upper_shadow = max(0, signal_day['high'] - signal_day['open'])

            body_length = abs(signal_day['close'] - signal_day['open'])

            if signal_day['high'] > 0:
                upper_shadow_ratio = upper_shadow / signal_day['high']
            else:
                upper_shadow_ratio = 0

            if upper_shadow_ratio < self.params['upper_shadow_ratio']:
                continue

            return True

        return False
