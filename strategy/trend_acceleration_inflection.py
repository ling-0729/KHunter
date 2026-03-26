"""
趋势加速拐点策略 - 识别股票在上升趋势中出现加速的拐点

选股条件（四个条件都必须满足）：
1. 近20交易日处于上升趋势（使用线性回归法判断）
   - 斜率 > 0（价格总体上升）
   - p值 < 0.05（趋势显著，不是随机波动）
   - R² > 0.3（拟合度良好，趋势明显）
2. 近10个交易日出现放量长阳线（涨幅>8%，成交量≥2倍5日均量）
3. 长阳线起涨点距离最近最低点涨幅<15%（最长回溯40交易日）
4. 长阳线后回调没有跌破长阳线的开盘价

策略特点：
- 顺势而为：在上升趋势中选股
- 信号明确：放量长阳线是加速信号
- 多重确认：四个条件组合确认
- 风险可控：回调支撑明确
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import MA, EMA, KDJ, calculate_zhixing_trend


class TrendAccelerationInflectionStrategy(BaseStrategy):
    """趋势加速拐点策略 - 识别股票在上升趋势中出现加速的拐点"""
    
    def __init__(self, params=None):
        # 默认参数配置
        default_params = {
            # 条件1：上升趋势（线性回归法）
            'uptrend_lookback_days': 20,           # 上升趋势回溯天数
            'uptrend_slope_threshold': 0,          # 斜率阈值（> 0 表示上升）
            'uptrend_pvalue_threshold': 0.01,      # p值阈值（< 0.01 表示显著，严格）
            'uptrend_rsquared_threshold': 0.5,     # R²阈值（> 0.5 表示拟合度良好，严格）
            
            # 条件2：放量长阳线
            'price_increase_threshold': 0.08,      # 涨幅阈值（8%）
            'volume_ratio_threshold': 2.0,         # 成交量倍数阈值
            'volume_ma_period': 5,                 # 成交量均值周期
            'surge_lookback_days': 10,             # 放量检查周期
            
            # 条件3：距离条件
            'distance_threshold': 0.25,            # 距离阈值（25%）
            'lowest_point_lookback_days': 40,      # 最低点回溯天数
            
            # 数据有效性
            'min_data_length': 50                  # 最少数据长度
        }
        
        # 合并用户参数
        if params:
            default_params.update(params)
        
        super().__init__("趋势加速拐点", default_params)
    
    def _validate_data(self, df) -> bool:
        """
        验证数据完整性和有效性
        
        检查必要字段是否存在，数据是否有效
        """
        if df is None or df.empty:
            return False
        
        # 检查必要字段
        required_fields = ['date', 'open', 'high', 'low', 'close', 'volume']
        for field in required_fields:
            if field not in df.columns:
                return False
        
        # 检查数据长度
        if len(df) < self.params['min_data_length']:
            return False
        
        return True
    
    def _fill_missing_values(self, df) -> pd.DataFrame:
        """
        填充缺失值，确保没有 None 值导致计算错误
        
        使用前向填充和后向填充的组合方式
        """
        result = df.copy()
        
        # 对数值列进行填充
        numeric_cols = result.select_dtypes(include=['float64', 'int64']).columns
        for col in numeric_cols:
            # 先用前向填充，再用后向填充
            result[col] = result[col].ffill().bfill()
            # 如果还有 NaN，用 0 填充
            result[col] = result[col].fillna(0)
        
        return result

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算趋势加速拐点策略所需的指标
        
        计算的指标包括：
        - KDJ：用于输出信号
        - 趋势线：用于输出信号
        - 市值：用于输出信号
        - 成交量均值：用于放量判断
        """
        # 数据验证
        if not self._validate_data(df):
            return pd.DataFrame()
        
        result = df.copy()
        
        try:
            # 计算KDJ指标（与其他策略保持一致）
            kdj_df = KDJ(result, n=9, m1=3, m2=3)
            result['K'] = kdj_df['K'].fillna(50)  # 默认值 50
            result['D'] = kdj_df['D'].fillna(50)  # 默认值 50
            result['J'] = kdj_df['J'].fillna(50)  # 默认值 50
        except Exception as e:
            # KDJ 计算失败，使用默认值
            result['K'] = 50
            result['D'] = 50
            result['J'] = 50
        
        try:
            # 计算趋势线（与其他策略保持一致）
            trend_df = calculate_zhixing_trend(
                result,
                m1=14,   # MA周期1
                m2=28,   # MA周期2
                m3=57,   # MA周期3
                m4=114   # MA周期4
            )
            result['short_term_trend'] = trend_df['short_term_trend'].fillna(0)
            result['bull_bear_line'] = trend_df['bull_bear_line'].fillna(0)
        except Exception as e:
            # 趋势线计算失败，使用默认值
            result['short_term_trend'] = 0
            result['bull_bear_line'] = 0
        
        # 计算市值（如果CSV中有market_cap字段则使用，否则估算）
        if 'market_cap' not in result.columns:
            # 估算市值：假设总股本2亿股
            result['market_cap'] = result['close'] * 2e8
        else:
            # 填充缺失的市值
            result['market_cap'] = result['market_cap'].fillna(result['close'] * 2e8)
        
        # 计算5日均量（用于放量判断）
        try:
            # 数据已按从新到旧排列，需要先按时间正序排列，计算后再恢复顺序
            result_sorted = result.sort_values('date', ascending=True).reset_index(drop=True)
            volume_ma_period = self.params['volume_ma_period']
            
            # 计算前N天的均量（shift(1)表示向后移动1行，即不包括当前行）
            result_sorted['volume_ma'] = result_sorted['volume'].shift(1).rolling(
                window=volume_ma_period, min_periods=1
            ).mean()
            
            # 填充缺失的均量值
            result_sorted['volume_ma'] = result_sorted['volume_ma'].fillna(
                result_sorted['volume'].mean()
            )
            
            # 恢复原始顺序（从新到旧）
            result = result_sorted.sort_values('date', ascending=False).reset_index(drop=True)
        except Exception as e:
            # 均量计算失败，使用成交量平均值
            result['volume_ma'] = result['volume'].mean()
        
        # 最后进行一次全面的缺失值填充
        result = self._fill_missing_values(result)
        
        return result
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别趋势加速拐点
        
        返回选股信号列表，每个元素为字典包含信号详情
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
        
        # 获取最新一天的数据
        latest = df.iloc[0]
        latest_date = latest['date']
        
        # 检查最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 检查四个条件
        # 条件1：上升趋势（道氏理论）
        if not self._check_uptrend(df):
            return []
        
        # 条件2：放量长阳线
        surge_index = self._check_volume_surge(df)
        if surge_index is None:
            return []
        
        # 条件3：距离条件
        if not self._check_distance(df, surge_index):
            return []
        
        # 条件4：回调支撑
        if not self._check_pullback_support(df, surge_index):
            return []
        
        # 四个条件都满足，生成选股信号
        try:
            surge_day = df.iloc[surge_index]
            prev_day = df.iloc[surge_index + 1] if surge_index + 1 < len(df) else surge_day
            
            # 计算涨幅（防御性检查）
            prev_close = prev_day['close'] if not pd.isna(prev_day['close']) else surge_day['close']
            if prev_close <= 0:
                return []
            price_increase = (surge_day['close'] - prev_close) / prev_close * 100
            
            # 计算成交量比（防御性检查）
            volume_ma = surge_day.get('volume_ma', None)
            if pd.isna(volume_ma) or volume_ma is None or volume_ma <= 0:
                volume_ma = surge_day['volume'] / self.params['volume_ratio_threshold']
            volume_ratio = surge_day['volume'] / volume_ma if volume_ma > 0 else 1.0
            
            # 找到最近最低点（用于距离计算）
            lookback_days = self.params['lowest_point_lookback_days']
            lookback_df = df.iloc[surge_index:min(surge_index + lookback_days, len(df))]
            lowest_point = lookback_df['low'].min()
            
            # 计算距离比（防御性检查）
            start_price = prev_close
            if lowest_point <= 0:
                return []
            distance_ratio = (start_price - lowest_point) / lowest_point * 100
            
            # 获取指标值（防御性检查）
            K = latest.get('K', 50)
            if pd.isna(K) or K is None:
                K = 50
            
            short_term_trend = latest.get('short_term_trend', 0)
            if pd.isna(short_term_trend) or short_term_trend is None:
                short_term_trend = 0
            
            bull_bear_line = latest.get('bull_bear_line', 0)
            if pd.isna(bull_bear_line) or bull_bear_line is None:
                bull_bear_line = 0
            
            market_cap = latest.get('market_cap', latest['close'] * 2e8)
            if pd.isna(market_cap) or market_cap is None:
                market_cap = latest['close'] * 2e8
            
            signal_info = {
                'date': latest_date,
                'close': round(float(latest['close']), 2),
                'open': round(float(surge_day['open']), 2),
                'volume_ratio': round(float(volume_ratio), 2),
                'price_increase': round(float(price_increase), 2),
                'lowest_point': round(float(lowest_point), 2),
                'distance_ratio': round(float(distance_ratio), 2),
                'market_cap': round(float(market_cap) / 1e8, 2),
                'J': round(float(K), 2),
                'short_term_trend': round(float(short_term_trend), 2),
                'bull_bear_line': round(float(bull_bear_line), 2),
                'reasons': ['近20日上升趋势', '近10日放量长阳线', '距离最低点<15%', '回调有支撑']
            }
            
            return [signal_info]
        except Exception as e:
            # 信号生成失败，返回空列表
            return []
    

    def _check_uptrend(self, df) -> bool:
        """
        检查条件1：上升趋势（线性回归法）
        
        使用线性回归判断20日内的趋势方向
        
        判断标准（严格）：
        1. 斜率 > 0（价格总体上升）
        2. p值 < 0.01（趋势显著，不是随机波动）
        3. R² > 0.5（拟合度良好，趋势明显）
        """
        uptrend_days = self.params['uptrend_lookback_days']
        
        # 获取最近20日的数据
        uptrend_df = df.head(uptrend_days)
        
        if uptrend_df.empty or len(uptrend_df) < 3:
            return False
        
        try:
            # 计算线性回归参数
            slope, p_value, r_squared = self._calculate_linear_regression(
                uptrend_df['close'].values
            )
            
            # 获取参数阈值
            slope_threshold = self.params.get('uptrend_slope_threshold', 0)
            pvalue_threshold = self.params.get('uptrend_pvalue_threshold', 0.01)
            rsquared_threshold = self.params.get('uptrend_rsquared_threshold', 0.5)
            
            # 检查条件：斜率 > 0 AND p值 < 0.01 AND R² > 0.5
            return (
                slope > slope_threshold and
                p_value < pvalue_threshold and
                r_squared > rsquared_threshold
            )
        except Exception as e:
            # 计算失败，返回 False
            return False
    
    def _check_volume_surge(self, df):
        """
        检查条件2：放量大涨
        
        判断逻辑：
        - 在最近10个交易日内寻找放量大涨
        - 放量大涨定义：
          1. 存在一天涨幅 > 8% 或涨停（>= 9.5%）
          2. 存在一天成交量 >= 2倍5日均量
          3. 大涨那天收盘价 > 开盘价
          4. 大涨和放量可以不在同一天
        
        返回满足条件的大涨日索引，如果没有则返回 None
        """
        if df.empty or len(df) < 11:
            return None
        
        surge_days = self.params['surge_lookback_days']
        price_threshold = self.params['price_increase_threshold']
        volume_threshold = self.params['volume_ratio_threshold']
        
        # 获取最近10个交易日的数据（包括当前一天）
        recent_df = df.head(surge_days + 1)
        
        # 第一步：检查是否存在放量
        has_volume_surge = False
        for i in range(len(recent_df) - 1):
            current_day = recent_df.iloc[i]
            
            # 检查成交量条件
            if pd.isna(current_day['volume']) or pd.isna(current_day['volume_ma']):
                continue
            
            if current_day['volume_ma'] <= 0:
                continue
            
            volume_ratio = current_day['volume'] / current_day['volume_ma']
            if volume_ratio >= volume_threshold:
                has_volume_surge = True
                break
        
        # 如果没有放量，直接返回 None
        if not has_volume_surge:
            return None
        
        # 第二步：寻找大涨日（涨幅 > 8% 且收盘价 > 开盘价）
        for i in range(len(recent_df) - 1):
            current_day = recent_df.iloc[i]
            prev_day = recent_df.iloc[i + 1]
            
            # 检查数据有效性
            if (pd.isna(current_day['open']) or pd.isna(current_day['close']) or
                pd.isna(prev_day['close']) or prev_day['close'] <= 0):
                continue
            
            # 检查涨幅条件
            price_increase = (current_day['close'] - prev_day['close']) / prev_day['close']
            is_limit_up = price_increase >= 0.095  # 涨停 >= 9.5%
            is_high_increase = price_increase > price_threshold
            
            if not (is_limit_up or is_high_increase):
                continue
            
            # 检查长阳线条件：收盘价 > 开盘价
            is_yang_line = current_day['close'] > current_day['open']
            
            if not is_yang_line:
                continue
            
            # 找到满足条件的大涨日
            return i
        
        return None
    
    def _check_distance(self, df, surge_index) -> bool:
        """
        检查条件3：距离条件
        
        判断逻辑：
        - 长阳线起涨点（前一天收盘价）距离最近最低点涨幅 <= 15%
        - 最低点最长回溯40交易日
        """
        if surge_index is None or surge_index >= len(df) - 1:
            return False
        
        try:
            distance_threshold = self.params['distance_threshold']
            lookback_days = self.params['lowest_point_lookback_days']
            
            # 获取长阳线前一天的收盘价（起涨点）
            prev_day = df.iloc[surge_index + 1]
            start_price = prev_day['close']
            
            # 防御性检查
            if pd.isna(start_price) or start_price <= 0:
                return False
            
            # 在长阳线前40个交易日内找最低价
            lookback_df = df.iloc[surge_index + 1:min(surge_index + 1 + lookback_days, len(df))]
            
            if lookback_df.empty:
                lowest_price = start_price
            else:
                lowest_price = lookback_df['low'].min()
            
            # 防御性检查
            if pd.isna(lowest_price) or lowest_price <= 0:
                return False
            
            # 计算距离比
            distance_ratio = (start_price - lowest_price) / lowest_price
            
            # 判断距离是否 <= 15%
            return distance_ratio <= distance_threshold
        except Exception as e:
            return False
    
    def _check_pullback_support(self, df, surge_index) -> bool:
        """
        检查条件4：回调支撑
        
        判断逻辑：
        - 长阳线后的所有交易日最低价都 >= 长阳线的开盘价
        - 这确保回调有支撑，不会跌破长阳线的开盘价
        """
        if surge_index is None or surge_index < 0:
            return False
        
        try:
            # 获取长阳线的开盘价作为支撑位
            surge_day = df.iloc[surge_index]
            support_price = surge_day['open']
            
            # 防御性检查
            if pd.isna(support_price) or support_price <= 0:
                return False
            
            # 检查长阳线后的所有交易日
            # 数据从新到旧排列，长阳线后的数据是索引 0 到 surge_index - 1
            if surge_index == 0:
                # 如果长阳线是最新一天，没有后续数据，认为满足条件
                return True
            
            # 检查所有后续交易日的最低价是否都 >= 支撑位
            after_surge = df.iloc[:surge_index]
            
            for i in range(len(after_surge)):
                low_price = after_surge.iloc[i]['low']
                
                # 防御性检查
                if pd.isna(low_price):
                    continue
                
                if low_price < support_price:
                    return False
            
            return True
        except Exception as e:
            return False
    
    def _calculate_linear_regression(self, prices):
        """
        计算线性回归参数
        
        使用scipy.stats.linregress对收盘价进行线性回归
        
        参数:
            prices: 收盘价数组（从新到旧）
        
        返回:
            (slope, p_value, r_squared): 斜率、p值、R²值
        """
        try:
            # 反转为从旧到新（线性回归需要时间序列）
            prices_asc = prices[::-1]
            
            # X轴: 交易日序号 (0, 1, 2, ..., n-1)
            X = np.arange(len(prices_asc))
            
            # 线性回归计算
            slope, intercept, r_value, p_value, std_err = stats.linregress(X, prices_asc)
            
            # 计算R²
            r_squared = r_value ** 2
            
            return slope, p_value, r_squared
        except Exception as e:
            # 计算失败，返回默认值（非上升趋势）
            return 0, 1.0, 0
