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

优化版本：
- 避免重复计算指标
- 快速预检查，提前过滤不符合条件的股票
- 优化循环逻辑，减少不必要的计算
- 减少KDJ和趋势线等不必要的计算
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
            'lookback_days': 5,        # 回溯天数，在此范围内寻找形态
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
        计算启明星策略所需的指标 - 优化版本
        """
        result = df.copy()
        
        # 计算K线实体大小（绝对值）
        result['body_size'] = abs(result['close'] - result['open'])
        
        # 计算K线方向（1=阳线，-1=阴线）
        result['candle_direction'] = (result['close'] > result['open']).astype(int) * 2 - 1
        
        # 计算成交量比例
        result['volume_ratio'] = result['volume'] / result['volume'].shift(1)
        
        # 填充缺失值
        result = result.ffill().bfill()
        
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
        criteria.append(f"1. 第一根K线（长阴线）：收盘价 < 开盘价，实体长度 > 0.01，表示下跌趋势")
        
        # 条件2：第二根K线（小实体）
        small_body_ratio = self.params['small_body_ratio'] * 100
        criteria.append(f"2. 第二根K线（小实体）：实体长度 <= 第一根K线实体的{small_body_ratio:.0f}%，可以是阳线或阴线，表示市场犹豫")
        
        # 条件3：第三根K线（长阳线）
        long_candle_ratio = self.params['long_candle_ratio'] * 100
        volume_ratio = self.params['volume_ratio']
        criteria.append(f"3. 第三根K线（长阳线）：收盘价 > 开盘价，实体长度 > 第一根K线实体的{long_candle_ratio:.0f}%，涨幅 > 5%，收盘价突破第一根K线开盘价，成交量 >= 第二根K线成交量的{volume_ratio:.1f}倍，表示反转上升")
        
        return criteria
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别启明星形态 - 优化版本
        """
        if df.empty or len(df) < 3:
            return []
        
        # 快速预检查：过滤退市/异常股票
        if stock_name:
            if '退' in stock_name or '未知' in stock_name or '已退' in stock_name:
                return []
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []
        
        # 获取最新一天的数据
        latest = df.iloc[0]
        latest_date = latest['date']
        
        # 快速检查：最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 快速检查：最新K线是否是阳线
        if latest['close'] <= latest['open']:
            return []
        
        # 快速检查：最新K线实体大小
        if abs(latest['close'] - latest['open']) < 0.01:
            return []
        
        # 在lookback_days范围内寻找启明星形态
        lookback_days = self.params.get('lookback_days', 3)
        max_search_days = min(lookback_days, len(df))
        
        # 只需要3根K线，不需要检查太多
        if max_search_days < 3:
            return []
        
        # 最多检查最近的几根K线
        search_range = min(10, max_search_days - 2)  # 最多检查10个组合
        
        # 向量化预计算 - 优化性能
        # 计算K线实体大小
        body_sizes = (df['close'] - df['open']).abs()
        
        # 计算阴线/阳线标记
        is_bullish = df['close'] > df['open']
        is_bearish = df['close'] < df['open']
        
        # 计算成交量比
        volume_ratios = df['volume'] / df['volume'].shift(-1)
        
        # 遍历寻找三根K线的组合
        for i in range(search_range):
            # 获取三根K线（从新到旧）
            first_candle = df.iloc[i]      # 第一根K线（最新）
            second_candle = df.iloc[i + 1] # 第二根K线
            third_candle = df.iloc[i + 2]  # 第三根K线（最旧）
            
            # 快速检查：第三根K线必须是阴线 - 使用预计算的标记
            if not is_bearish.iloc[i + 2]:
                continue
            
            # 快速检查：第二根K线实体必须小 - 使用预计算的实体大小
            third_body = body_sizes.iloc[i + 2]
            second_body = body_sizes.iloc[i + 1]
            if second_body > third_body * self.params['small_body_ratio']:
                continue
            
            # 检查是否满足启明星形态
            if self._is_morning_star_pattern(first_candle, second_candle, third_candle):
                # 关键日期：第三根K线（确认日）的日期
                key_date = first_candle['date']
                
                # 格式化关键日期，只保留日期部分
                key_date_str = key_date.strftime('%Y-%m-%d') if hasattr(key_date, 'strftime') else str(key_date)[:10]
                
                # 构建选股信号
                market_cap_val = latest.get('market_cap')
                if market_cap_val is None:
                    market_cap_val = latest['close'] * 2e8  # 默认市值计算
                
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
        检查是否满足启明星形态 - 优化版本
        """
        # 第三根K线（最旧）：长阴线
        third_body = abs(third_candle['close'] - third_candle['open'])
        third_is_bearish = third_candle['close'] < third_candle['open']
        
        if not third_is_bearish or third_body < 0.01:
            return False
        
        # 第二根K线：小实体
        second_body = abs(second_candle['close'] - second_candle['open'])
        small_body_threshold = third_body * self.params['small_body_ratio']
        
        if second_body > small_body_threshold:
            return False
        
        # 第一根K线（最新）：长阳线
        first_body = abs(first_candle['close'] - first_candle['open'])
        first_is_bullish = first_candle['close'] > first_candle['open']
        
        if not first_is_bullish or first_body < 0.01:
            return False
        
        # 第三根阳线涨幅>5%
        # 注意：这里使用日内涨幅（相对于开盘价），因为这是K线形态的标准定义
        first_candle_change = (first_candle['close'] - first_candle['open']) / first_candle['open'] * 100
        if first_candle_change <= 5:
            return False
        
        # 第一根K线实体大小检查
        long_candle_threshold = third_body * self.params['long_candle_ratio']
        if first_body < long_candle_threshold:
            return False
        
        # 第一根K线必须突破第三根K线的开盘价
        if first_candle['close'] <= third_candle['open']:
            return False
        
        # 成交量检查 - 优化：使用预计算的成交量比
        volume_ratio = first_candle['volume'] / second_candle['volume'] if second_candle['volume'] > 0 else 0
        if volume_ratio < self.params['volume_ratio']:
            return False
        
        return True
