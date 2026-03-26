"""
单元测试：底部趋势拐点策略
测试目标：验证底部趋势拐点策略的所有功能，包括指标计算、三个条件检查、综合判断等
"""
import unittest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.bottom_trend_inflection import BottomTrendInflectionStrategy


class TestBottomTrendInflectionIndicators(unittest.TestCase):
    """测试指标计算功能"""
    
    def setUp(self):
        """测试前准备 - 创建测试数据"""
        # 创建120天的测试数据
        dates = pd.date_range(end='2024-01-01', periods=120, freq='D')
        
        # 生成基础价格数据
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.randn(120) * 2)
        
        self.test_df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(120),
            'high': close_prices + np.random.rand(120) * 2,
            'low': close_prices - np.random.rand(120) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 120),
            'market_cap': np.random.uniform(1000000000, 5000000000, 120)
        })
        
        # 反转数据顺序（最新的在前）
        self.test_df = self.test_df.iloc[::-1].reset_index(drop=True)
        
        self.strategy = BottomTrendInflectionStrategy()
    
    def test_calculate_indicators_returns_dataframe(self):
        """测试calculate_indicators返回DataFrame"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证返回类型
        self.assertIsInstance(result, pd.DataFrame)
        
        # 验证返回的行数与输入相同
        self.assertEqual(len(result), len(self.test_df))
    
    def test_calculate_indicators_includes_macd(self):
        """测试calculate_indicators计算MACD指标"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证MACD相关列存在
        self.assertIn('DIF', result.columns)
        self.assertIn('DEA', result.columns)
        self.assertIn('MACD', result.columns)
        
        # 验证MACD值不全为NaN（至少有一些有效值）
        self.assertTrue(result['MACD'].notna().sum() > 0)
    
    def test_calculate_indicators_includes_kdj(self):
        """测试calculate_indicators计算KDJ指标"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证KDJ相关列存在
        self.assertIn('K', result.columns)
        self.assertIn('D', result.columns)
        self.assertIn('J', result.columns)
        
        # 验证KDJ值在合理范围内（0-100）
        valid_k = result['K'].dropna()
        if len(valid_k) > 0:
            self.assertTrue((valid_k >= 0).all() and (valid_k <= 100).all())
    
    def test_calculate_indicators_includes_trend(self):
        """测试calculate_indicators计算趋势线"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证趋势线列存在
        self.assertIn('short_term_trend', result.columns)
        self.assertIn('bull_bear_line', result.columns)
        
        # 验证趋势线值不全为NaN
        self.assertTrue(result['short_term_trend'].notna().sum() > 0)
        self.assertTrue(result['bull_bear_line'].notna().sum() > 0)
    
    def test_calculate_indicators_includes_volume_ma(self):
        """测试calculate_indicators计算10日均量"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证volume_ma列存在（用于计算成交量比率）
        self.assertIn('volume_ma', result.columns)
        
        # 验证volume_ma值合理（应该有有效值）
        valid_ma = result['volume_ma'].dropna()
        if len(valid_ma) > 0:
            self.assertTrue((valid_ma > 0).all())


class TestDeepDeclineCondition(unittest.TestCase):
    """测试条件1：深度下跌（下跌幅度 > 45%）"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = BottomTrendInflectionStrategy()
    
    def test_deep_decline_satisfied(self):
        """测试满足深度下跌条件"""
        # 创建测试数据：最高价100，最低价50，下跌50%
        df = pd.DataFrame({
            'date': pd.date_range(end='2024-01-01', periods=120, freq='D'),
            'open': [50] * 120,
            'high': [100] + [50] * 119,  # 第一个最高价是100
            'low': [50] * 120,
            'close': [50] * 120,
            'volume': [1000000] * 120,
            'DIF': [0] * 120,
            'DEA': [0] * 120,
            'MACD': [0] * 120,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 测试条件
        result = self.strategy._check_deep_decline(df)
        self.assertTrue(result)
    
    def test_deep_decline_not_satisfied(self):
        """测试不满足深度下跌条件"""
        # 创建测试数据：最高价100，最低价80，下跌20%
        df = pd.DataFrame({
            'date': pd.date_range(end='2024-01-01', periods=120, freq='D'),
            'open': [80] * 120,
            'high': [100] + [80] * 119,
            'low': [80] * 120,
            'close': [80] * 120,
            'volume': [1000000] * 120,
            'DIF': [0] * 120,
            'DEA': [0] * 120,
            'MACD': [0] * 120,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 测试条件
        result = self.strategy._check_deep_decline(df)
        self.assertFalse(result)
    
    def test_deep_decline_boundary_45_percent(self):
        """测试边界情况：恰好45%下跌"""
        # 创建测试数据：最高价100，最低价55，下跌45%
        df = pd.DataFrame({
            'date': pd.date_range(end='2024-01-01', periods=120, freq='D'),
            'open': [55] * 120,
            'high': [100] + [55] * 119,
            'low': [55] * 120,
            'close': [55] * 120,
            'volume': [1000000] * 120,
            'DIF': [0] * 120,
            'DEA': [0] * 120,
            'MACD': [0] * 120,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 测试条件（45%不满足，需要>45%）
        result = self.strategy._check_deep_decline(df)
        self.assertFalse(result)
    
    def test_deep_decline_boundary_46_percent(self):
        """测试边界情况：46%下跌（满足条件）"""
        # 创建测试数据：最高价100，最低价54，下跌46%
        df = pd.DataFrame({
            'date': pd.date_range(end='2024-01-01', periods=120, freq='D'),
            'open': [54] * 120,
            'high': [100] + [54] * 119,
            'low': [54] * 120,
            'close': [54] * 120,
            'volume': [1000000] * 120,
            'DIF': [0] * 120,
            'DEA': [0] * 120,
            'MACD': [0] * 120,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 测试条件
        result = self.strategy._check_deep_decline(df)
        self.assertTrue(result)
    
    def test_deep_decline_empty_dataframe(self):
        """测试空DataFrame"""
        df = pd.DataFrame()
        result = self.strategy._check_deep_decline(df)
        self.assertFalse(result)


class TestMACDDivergenceCondition(unittest.TestCase):
    """测试条件2：MACD底背离"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = BottomTrendInflectionStrategy()
    
    def test_macd_divergence_not_satisfied_price_not_new_low(self):
        """测试不满足条件：价格没有创新低"""
        # 创建测试数据：价格没有创新低
        df = pd.DataFrame({
            'date': pd.date_range(end='2024-01-01', periods=120, freq='D'),
            'open': [50] * 120,
            'high': [100] + [50] * 119,
            'low': [50] * 120,
            'close': [50] * 120,
            'volume': [1000000] * 120,
            'DIF': [0] * 120,
            'DEA': [0] * 120,
            'MACD': [-0.5] + [-1.0] * 119,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 设置最低价：最新=60，历史最低=50（最新不是新低）
        df.loc[0, 'low'] = 60
        df.loc[119, 'low'] = 50
        
        # 测试条件
        result = self.strategy._check_macd_divergence(df)
        self.assertFalse(result)
    
    def test_macd_divergence_not_satisfied_macd_also_new_low(self):
        """测试不满足条件：MACD也创新低"""
        # 创建测试数据：价格和MACD都创新低
        df = pd.DataFrame({
            'date': pd.date_range(end='2024-01-01', periods=120, freq='D'),
            'open': [50] * 120,
            'high': [100] + [50] * 119,
            'low': [50] * 120,
            'close': [50] * 120,
            'volume': [1000000] * 120,
            'DIF': [0] * 120,
            'DEA': [0] * 120,
            'MACD': [-1.5] + [-1.0] * 119,  # 最新MACD=-1.5，历史最低=-1.0（最新是新低）
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 设置最低价：最新=40，历史最低=50
        df.loc[0, 'low'] = 40
        df.loc[119, 'low'] = 50
        
        # 测试条件
        result = self.strategy._check_macd_divergence(df)
        self.assertFalse(result)
    
    def test_macd_divergence_with_nan_values(self):
        """测试处理NaN值"""
        # 创建测试数据：包含NaN值
        df = pd.DataFrame({
            'date': pd.date_range(end='2024-01-01', periods=120, freq='D'),
            'open': [50] * 120,
            'high': [100] + [50] * 119,
            'low': [50] * 120,
            'close': [50] * 120,
            'volume': [1000000] * 120,
            'DIF': [0] * 120,
            'DEA': [0] * 120,
            'MACD': [np.nan] + [-1.0] * 119,  # 最新MACD是NaN
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 测试条件
        result = self.strategy._check_macd_divergence(df)
        self.assertFalse(result)


class TestVolumeSurgeCondition(unittest.TestCase):
    """测试条件3：放量反弹"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = BottomTrendInflectionStrategy()
    
    def _create_test_df(self, surge_day_index=0, open_price=100.0, close_price=109.5, 
                        volume=4000000.0, prev_volume=1000000.0, lowest_price=90.0):
        """
        创建测试数据框
        
        参数：
        - surge_day_index: 放量反弹发生在第几天（0表示最新一天）
        - open_price: 开盘价（当日）
        - close_price: 收盘价（当日）
        - volume: 成交量（当日）
        - prev_volume: 前一天成交量
        - lowest_price: 反弹发生前的最低价
        """
        # 创建11天的数据（包括当前一天和前10天）
        dates = pd.date_range(end='2026-03-21', periods=11, freq='D')
        
        data = []
        for i in range(11):
            if i == surge_day_index:
                # 放量反弹的那一天
                data.append({
                    'date': dates[10 - i],
                    'open': open_price,
                    'close': close_price,
                    'high': max(open_price, close_price) * 1.01,
                    'low': min(open_price, close_price) * 0.99,
                    'volume': volume,
                })
            elif i == surge_day_index + 1:
                # 放量反弹前一天（起涨点）
                data.append({
                    'date': dates[10 - i],
                    'open': open_price * 0.98,
                    'close': open_price,  # 前一天收盘价作为起涨点
                    'high': open_price * 1.01,
                    'low': lowest_price,
                    'volume': prev_volume,
                })
            else:
                # 其他天（反弹发生前的历史数据）
                data.append({
                    'date': dates[10 - i],
                    'open': lowest_price * 1.05,
                    'close': lowest_price * 1.05,
                    'high': lowest_price * 1.06,
                    'low': lowest_price,
                    'volume': 1000000.0,
                })
        
        df = pd.DataFrame(data)
        df = df.sort_values('date', ascending=False).reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        return df
    
    def test_volume_surge_limit_up(self):
        """测试满足条件：涨停（相对前一日收盘价）且放量（距离条件15%）"""
        # 创建测试数据：前一日收盘价100，当日收盘价109.5（涨幅9.5%=涨停）
        # 成交量4倍，起涨点距离最低点12%（满足15%条件）
        df = self._create_test_df(surge_day_index=0, open_price=100.0, close_price=109.5, 
                                  volume=4000000.0, prev_volume=1000000.0, lowest_price=90.0)
        
        result = self.strategy._check_volume_surge(df)
        self.assertTrue(result)
    
    def test_volume_surge_high_increase(self):
        """测试满足条件：涨幅>8%（相对前一日收盘价）且放量"""
        # 创建测试数据：前一日收盘价100，当日收盘价113（涨幅13%）且成交量4倍
        df = self._create_test_df(surge_day_index=0, open_price=100.0, close_price=113.0, 
                                  volume=4000000.0, prev_volume=1000000.0, lowest_price=90.0)
        
        result = self.strategy._check_volume_surge(df)
        self.assertTrue(result)
    
    def test_volume_surge_not_satisfied_low_increase(self):
        """测试不满足条件：涨幅<8%（相对前一日收盘价）且不涨停"""
        # 创建测试数据：前一日收盘价100，当日收盘价107（涨幅7%<8%）
        # 且不涨停（< 109.5），成交量4倍
        df = self._create_test_df(surge_day_index=0, open_price=100.0, close_price=107.0, 
                                  volume=4000000.0, prev_volume=1000000.0, lowest_price=90.0)
        
        result = self.strategy._check_volume_surge(df)
        self.assertFalse(result)
    
    def test_volume_surge_not_satisfied_low_volume(self):
        """测试不满足条件：成交量<2.5倍10日均量"""
        # 创建测试数据：涨幅13%但成交量只有2倍10日均量
        df = self._create_test_df(surge_day_index=0, open_price=100.0, close_price=113.0, 
                                  volume=2000000.0, prev_volume=1000000.0, lowest_price=90.0)
        
        result = self.strategy._check_volume_surge(df)
        self.assertFalse(result)
    
    def test_volume_surge_boundary_12_percent(self):
        """测试边界情况：涨幅12%（相对前一日收盘价）但不涨停"""
        # 创建测试数据：前一日收盘价100，当日收盘价112（涨幅12%>8%）
        # 但不涨停（< 109.5），成交量4倍
        df = self._create_test_df(surge_day_index=0, open_price=100.0, close_price=112.0, 
                                  volume=4000000.0, prev_volume=1000000.0, lowest_price=90.0)
        
        result = self.strategy._check_volume_surge(df)
        self.assertTrue(result)  # 涨幅12%满足条件
    
    def test_volume_surge_boundary_12_01_percent(self):
        """测试边界情况：涨幅12.01%（相对前一日收盘价）"""
        # 创建测试数据：前一日收盘价100，当日收盘价112.01（涨幅12.01%）且成交量4倍
        df = self._create_test_df(surge_day_index=0, open_price=100.0, close_price=112.01, 
                                  volume=4000000.0, prev_volume=1000000.0, lowest_price=90.0)
        
        result = self.strategy._check_volume_surge(df)
        self.assertTrue(result)
    
    def test_volume_surge_boundary_3x_volume(self):
        """测试边界情况：恰好3倍成交量"""
        # 创建测试数据：涨幅13%且成交量恰好3倍10日均量
        df = self._create_test_df(surge_day_index=0, open_price=100.0, close_price=113.0, 
                                  volume=3000000.0, prev_volume=1000000.0, lowest_price=90.0)
        
        result = self.strategy._check_volume_surge(df)
        self.assertTrue(result)  # 3倍满足条件（>= 3倍）
    
    def test_volume_surge_with_nan_values(self):
        """测试处理NaN值"""
        # 创建测试数据：包含NaN值
        df = self._create_test_df(surge_day_index=0, open_price=100.0, close_price=113.0, 
                                  volume=4000000.0, prev_volume=1000000.0, lowest_price=90.0)
        
        # 设置某些值为NaN
        df.loc[0, 'open'] = np.nan
        
        result = self.strategy._check_volume_surge(df)
        self.assertFalse(result)


class TestSelectStocks(unittest.TestCase):
    """测试综合选股逻辑"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = BottomTrendInflectionStrategy()
    
    def test_select_stocks_filter_st_stock(self):
        """测试过滤ST股票"""
        # 创建测试数据
        dates = pd.date_range(end='2024-01-01', periods=120, freq='D')
        
        df = pd.DataFrame({
            'date': dates,
            'open': [100] * 120,
            'high': [150] + [100] * 119,
            'low': [40] + [100] * 119,
            'close': [113] + [100] * 119,
            'volume': [3000000] + [1000000] * 119,
            'market_cap': [1000000000] * 120,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 调整MACD
        df.loc[0, 'MACD'] = -0.5
        df.loc[119, 'MACD'] = -1.0
        
        # 选股（使用ST股票名称）
        result = self.strategy.select_stocks(df, stock_name='ST测试')
        
        # 验证被过滤
        self.assertEqual(len(result), 0)
    
    def test_select_stocks_filter_star_st_stock(self):
        """测试过滤*ST股票"""
        # 创建测试数据
        dates = pd.date_range(end='2024-01-01', periods=120, freq='D')
        
        df = pd.DataFrame({
            'date': dates,
            'open': [100] * 120,
            'high': [150] + [100] * 119,
            'low': [40] + [100] * 119,
            'close': [113] + [100] * 119,
            'volume': [3000000] + [1000000] * 119,
            'market_cap': [1000000000] * 120,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 调整MACD
        df.loc[0, 'MACD'] = -0.5
        df.loc[119, 'MACD'] = -1.0
        
        # 选股（使用*ST股票名称）
        result = self.strategy.select_stocks(df, stock_name='*ST测试')
        
        # 验证被过滤
        self.assertEqual(len(result), 0)
    
    def test_select_stocks_insufficient_data(self):
        """测试数据不足时返回空列表"""
        # 创建数据不足的测试数据（少于120天）
        dates = pd.date_range(end='2024-01-01', periods=50, freq='D')
        
        df = pd.DataFrame({
            'date': dates,
            'open': [100] * 50,
            'high': [150] + [100] * 49,
            'low': [40] + [100] * 49,
            'close': [113] + [100] * 49,
            'volume': [3000000] + [1000000] * 49,
            'market_cap': [1000000000] * 50,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 选股
        result = self.strategy.select_stocks(df, stock_name='测试股票')
        
        # 验证返回空列表
        self.assertEqual(len(result), 0)
    
    def test_select_stocks_empty_dataframe(self):
        """测试空DataFrame"""
        df = pd.DataFrame()
        result = self.strategy.select_stocks(df, stock_name='测试股票')
        self.assertEqual(len(result), 0)


class TestStrategyInitialization(unittest.TestCase):
    """测试策略初始化"""
    
    def test_strategy_initialization_default_params(self):
        """测试默认参数初始化"""
        strategy = BottomTrendInflectionStrategy()
        
        # 验证策略名称
        self.assertEqual(strategy.name, "底部趋势拐点")
        
        # 验证默认参数
        self.assertEqual(strategy.params['lookback_days'], 120)
        self.assertEqual(strategy.params['decline_threshold'], 0.45)
        self.assertEqual(strategy.params['volume_ratio_threshold'], 2.5)
        self.assertEqual(strategy.params['price_increase_threshold'], 0.08)
        self.assertEqual(strategy.params['volume_ma_period'], 10)
        self.assertEqual(strategy.params['macd_divergence_days'], 20)
    
    def test_strategy_initialization_custom_params(self):
        """测试自定义参数初始化"""
        custom_params = {
            'lookback_days': 60,
            'decline_threshold': 0.50,
        }
        
        strategy = BottomTrendInflectionStrategy(params=custom_params)
        
        # 验证自定义参数被应用
        self.assertEqual(strategy.params['lookback_days'], 60)
        self.assertEqual(strategy.params['decline_threshold'], 0.50)
        
        # 验证其他参数保持默认值
        self.assertEqual(strategy.params['volume_ratio_threshold'], 2.5)


if __name__ == '__main__':
    unittest.main()
