"""
启明星策略 - 三根K线底部反转形态

指标定义：
1. 第一根K线：长阴线（收盘价 < 开盘价，实体长度 > 阈值）
   - 表示下跌趋势

2. 第二根K线：小实体K线（开盘价和收盘价接近）
   - 可以是阳线或阴线，但实体很小
   - 表示市场犹豫

3. 第三根K线：长阳线（收盘价 > 开盘价，实体长度 > 阈值）
   - 必须突破第一根K线的开盘价
   - 实体大小 > 第一根K线实体的50%
   - 表示反转上升

选股条件：
- 三根K线按顺序出现
- 第一根K线是长阴线
- 第二根K线是小实体
- 第三根K线是长阳线且满足突破条件
- 在lookback_days内出现该形态
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import REF


class MorningStarStrategy(BaseStrategy):
    """启明星策略 - 三根K线底部反转形态"""
    
    def __init__(self, params=None):
        # 默认参数
        default_params = {
            'lookback_days': 30,        # 回溯天数，在此范围内寻找形态
            'small_body_ratio': 0.3,    # 第二根K线实体与第一根K线实体的比例阈值
            'long_candle_ratio': 0.5,   # 第三根K线实体与第一根K线实体的最小比例
            'volume_ratio': 1.5,        # 第三根K线成交量与第二根K线的比例
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
        
        # 计算K线实体大小（绝对值）
        result['body_size'] = abs(result['close'] - result['open'])
        
        # 计算K线方向（1=阳线，-1=阴线）
        result['candle_direction'] = (result['close'] > result['open']).astype(int) * 2 - 1
        
        # 计算成交量比例
        result['volume_ratio'] = result['volume'] / REF(result['volume'], 1)
        
        # 计算KDJ指标（与BowlReboundStrategy保持一致）
        from utils.technical import KDJ
        kdj_df = KDJ(result, n=9, m1=3, m2=3)
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']
        
        # 计算趋势线（与BowlReboundStrategy保持一致）
        from utils.technical import calculate_zhixing_trend
        trend_df = calculate_zhixing_trend(
            result,
            m1=14,  # MA周期1
            m2=28,  # MA周期2
            m3=57,  # MA周期3
            m4=114  # MA周期4
        )
        result['short_term_trend'] = trend_df['short_term_trend']
        result['bull_bear_line'] = trend_df['bull_bear_line']
        
        # 计算市值（如果CSV中有market_cap字段则使用，否则估算）
        if 'market_cap' not in result.columns:
            # 估算市值：假设总股本2亿股
            result['market_cap'] = result['close'] * 2e8
        
        return result
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别启明星形态
        
        参数说明：
        - lookback_days: 回溯天数，用于寻找启明星形态。设置为3时只检查最后3根K线，设置为30时检查30天内的形态
        """
        if df.empty or len(df) < 3:
            return []
        
        # 计算指标（必须在选股逻辑之前调用）
        df = self.calculate_indicators(df)
        
        # 过滤退市/异常股票
        if stock_name:
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in stock_name for kw in invalid_keywords):
                return []
            
            # 过滤 ST/*ST 股票
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []
        
        # 获取最新一天的数据
        latest = df.iloc[0]
        latest_date = latest['date']
        
        # 检查最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 在lookback_days范围内寻找启明星形态
        # lookback_days参数可以通过config/strategy_params.yaml调整
        # 设置lookback_days=3时只检查最后3根K线，设置lookback_days=30时检查30天内的形态
        lookback_days = self.params['lookback_days']
        lookback_df = df.head(lookback_days)
        
        # 遍历寻找三根K线的组合
        for i in range(len(lookback_df) - 2):
            # 获取三根K线（从新到旧）
            first_candle = lookback_df.iloc[i]      # 第一根K线（最新）
            second_candle = lookback_df.iloc[i + 1] # 第二根K线
            third_candle = lookback_df.iloc[i + 2]  # 第三根K线（最旧）
            
            # 检查是否满足启明星形态
            if self._is_morning_star_pattern(first_candle, second_candle, third_candle):
                # 构建选股信号 - 返回完整的数据结构，与BowlReboundStrategy保持一致
                signal_info = {
                    'date': latest_date,
                    'close': round(latest['close'], 2),
                    'J': round(latest['J'], 2),
                    'volume_ratio': round(latest['volume_ratio'], 2) if not pd.isna(latest['volume_ratio']) else 1.0,
                    'market_cap': round(latest['market_cap'] / 1e8, 2),
                    'short_term_trend': round(latest['short_term_trend'], 2),
                    'bull_bear_line': round(latest['bull_bear_line'], 2),
                    'reasons': ['启明星形态'],
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
        参数顺序：第一根K线（最新）、第二根K线、第三根K线（最旧）
        """
        # 第三根K线（最旧）：必须是长阴线
        third_body = third_candle['body_size']
        third_is_bearish = third_candle['close'] < third_candle['open']
        
        if not third_is_bearish or third_body < 0.01:  # 实体过小则不符合
            return False
        
        # 第二根K线：小实体（可以是阳线或阴线）
        second_body = second_candle['body_size']
        small_body_threshold = third_body * self.params['small_body_ratio']
        
        if second_body > small_body_threshold:
            return False
        
        # 第一根K线（最新）：必须是长阳线
        first_body = first_candle['body_size']
        first_is_bullish = first_candle['close'] > first_candle['open']
        
        if not first_is_bullish or first_body < 0.01:  # 实体过小则不符合
            return False
        
        # 第一根K线实体大小检查：必须 > 第三根K线实体的50%
        long_candle_threshold = third_body * self.params['long_candle_ratio']
        if first_body < long_candle_threshold:
            return False
        
        # 第一根K线必须突破第三根K线的开盘价
        if first_candle['close'] <= third_candle['open']:
            return False
        
        # 成交量检查（可选）：第一根K线成交量应该大于第二根K线
        if first_candle['volume'] < second_candle['volume'] * self.params['volume_ratio']:
            return False
        
        return True
