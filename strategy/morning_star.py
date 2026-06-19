"""
启明星策略 - 三根K线底部反转形态

指标定义：
1. 第一根K线：长阴线（收盘价 < 开盘价，实体长度 > 0.03）
   - 表示下跌趋势

2. 第二根K线：小实体K线（开盘价和收盘价接近）
   - 可以是阳线或阴线，但实体很小
   - 表示市场犹豫

3. 第三根K线：长阳线（收盘价 > 开盘价，实体长度 > 阈值）
   - 必须突破5日均线
   - 表示反转上升

选股条件：
- 三根K线按顺序出现
- 第一根K线是长阴线（实体 > 0.03）
- 第二根K线是小实体
- 第三根K线是长阳线且满足突破条件（突破5日均线）
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import calculate_daily_return


class MorningStarStrategy(BaseStrategy):
    """启明星策略 - 三根K线底部反转形态"""

    def __init__(self, params=None):
        # 默认参数
        default_params = {
            'lookback_days': 3,         # 回溯天数（只需检查最近3天）
            'small_body_ratio': 0.3,    # 第二根K线实体与第一根K线实体的比例阈值
            'long_candle_ratio': 0.5,   # 第三根K线实体与第一根K线实体的最小比例（已弃用）
            'volume_ratio': 1.5,        # 第三根K线成交量与第二根K线的比例
            'first_body_threshold': 0.03,# 第一根K线（长阴线）实体最小百分比（3%）
        }

        # 合并用户参数
        if params:
            default_params.update(params)

        super().__init__("启明星策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算启明星策略所需的指标
        """
        result = df.copy()

        # 计算K线实体大小（百分比幅度）
        # 实体 = |close - open| / open，表示涨跌幅
        result['body_size'] = abs(result['close'] - result['open']) / result['open']

        # 计算K线方向（1=阳线，-1=阴线）
        result['candle_direction'] = (result['close'] > result['open']).astype(int) * 2 - 1

        # 计算成交量比例
        result['volume_ratio'] = result['volume'] / result['volume'].shift(1)

        # 计算5日均线
        result['ma5'] = result['close'].rolling(window=5).mean()

        # 填充缺失值
        # 注意：此策略使用正序数据（index=0是最早日期）
        # 对于正序数据：ffill()使用历史数据（安全），bfill()使用未来数据（未来函数）
        # 所以只使用ffill()向前填充
        # result = result.ffill().bfill()  # ⚠️ bfill是未来函数！
        result = result.ffill()

        # 计算市值
        if 'market_cap' not in result.columns:
            result['market_cap'] = result['close'] * 2e8

        return result

    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []

        # 条件1：第一根K线（长阴线）
        first_body_threshold = self.params.get('first_body_threshold', 0.03)
        criteria.append(f"1. 第一根K线（长阴线）：收盘价 < 开盘价，实体长度 > {first_body_threshold}，表示下跌趋势")

        # 条件2：第二根K线（小实体）
        small_body_ratio = self.params['small_body_ratio'] * 100
        criteria.append(f"2. 第二根K线（小实体）：实体长度 <= 第一根K线实体的{small_body_ratio:.0f}%，可以是阳线或阴线，表示市场犹豫")

        # 条件3：第三根K线（长阳线）
        volume_ratio = self.params['volume_ratio']
        criteria.append(f"3. 第三根K线（长阳线）：收盘价 > 开盘价，涨幅 > 5%，收盘价突破5日均线，成交量 >= 第二根K线成交量的{volume_ratio:.1f}倍，表示反转上升")

        return criteria

    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别启明星形态
        只检查最新的三根K线（今天、昨天、前天）
        """
        if df.empty or len(df) < 3:
            return []

        # 快速预检查：过滤退市/异常股票
        if stock_name:
            if '退' in stock_name or '未知' in stock_name or '已退' in stock_name:
                return []
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []

        # 计算技术指标（包括MA5等）
        df = self.calculate_indicators(df.copy())

        # 获取最新一天的数据
        latest = df.iloc[0]
        latest_date = latest['date']

        # 快速检查：最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []

        # 只需检查最新三根K线（今天、昨天、前天）
        # df数据是倒序排列（最新在前）
        first_candle = df.iloc[0]      # 最新K线（第三根/阳线）
        second_candle = df.iloc[1]     # 第二根K线
        third_candle = df.iloc[2]      # 第一根K线（最旧/阴线）

        # 快速检查：第三根K线涨幅是否 > 5%
        # 只做快速过滤，详细条件在 _is_morning_star_pattern 中逐条验证
        third_candle_change = (first_candle['close'] - first_candle['open']) / first_candle['open'] * 100
        if third_candle_change <= 5:
            return []

        # 检查是否满足启明星形态
        if self._is_morning_star_pattern(first_candle, second_candle, third_candle):
            # 关键日期：最新K线（确认日）的日期
            key_date = first_candle['date']
            key_date_str = key_date.strftime('%Y-%m-%d') if hasattr(key_date, 'strftime') else str(key_date)[:10]

            # 构建选股信号
            market_cap_val = latest.get('market_cap')
            if market_cap_val is None:
                market_cap_val = latest['close'] * 2e8

            signal_info = {
                'date': latest_date,
                'close': round(latest['close'], 2),
                'volume_ratio': round(latest.get('volume_ratio', 1.0), 2),
                'market_cap': round(market_cap_val / 1e8, 2),
                'reasons': ['启明星形态'],
                'key_date': key_date_str,
                'key_date_type': '启明星确认日',
                'pattern_date': first_candle['date'],
                'pattern_details': {
                    'first_candle_date': third_candle['date'],
                    'first_candle_close': round(third_candle['close'], 2),
                    'first_candle_open': round(third_candle['open'], 2),
                    'second_candle_date': second_candle['date'],
                    'second_candle_close': round(second_candle['close'], 2),
                    'second_candle_open': round(second_candle['open'], 2),
                    'third_candle_date': first_candle['date'],
                    'third_candle_close': round(first_candle['close'], 2),
                    'third_candle_open': round(first_candle['open'], 2),
                }
            }
            return [signal_info]

        return []

    def _is_morning_star_pattern(self, first_candle, second_candle, third_candle) -> bool:
        """
        检查是否满足启明星形态
        验证顺序：第三根K线 → 第一根K线 → 第二根K线
        """
        # 第三根K线（最新）：阳线
        # 启明星形态的确认是第三根必须是阳线，表示反转
        third_is_bullish = first_candle['close'] > first_candle['open']
        if not third_is_bullish:
            return False

        # 第三根阳线涨幅 > 5%
        third_candle_change = (first_candle['close'] - first_candle['open']) / first_candle['open'] * 100
        if third_candle_change <= 5:
            return False

        # 第三根K线必须突破5日均线
        ma5 = first_candle.get('ma5')
        if pd.isna(ma5) or first_candle['close'] <= ma5:
            return False

        # 第一根K线（最旧）：长阴线，实体百分比 > 1%
        # 启明星形态的核心是第一根必须是长阴线，表示下跌趋势
        first_body_threshold = self.params.get('first_body_threshold', 0.01)
        # 计算实体百分比：|close - open| / open
        first_body = abs(third_candle['close'] - third_candle['open']) / third_candle['open']
        first_is_bearish = third_candle['close'] < third_candle['open']

        if not first_is_bearish or first_body < first_body_threshold:
            return False

        # 第二根K线：小实体
        # 表示市场犹豫阶段
        second_body = abs(second_candle['close'] - second_candle['open']) / second_candle['open']
        small_body_threshold = first_body * self.params['small_body_ratio']

        if second_body > small_body_threshold:
            return False

        # 成交量检查：第三根K线成交量 >= 第二根的1.5倍
        volume_ratio = first_candle['volume'] / second_candle['volume'] if second_candle['volume'] > 0 else 0
        if volume_ratio < self.params['volume_ratio']:
            return False

        return True
