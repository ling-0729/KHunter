"""
单元测试：多死叉共振策略
测试目标：验证多死叉共振策略的所有功能，包括指标计算、死叉识别、共振确认等
"""
import unittest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.multi_death_cross import MultiDeathCrossStrategy


class TestMultiDeathCrossIndicators(unittest.TestCase):
    """测试指标计算功能"""
    
    def setUp(self):
        """测试前准备 - 创建测试数据"""
        # 创建30天的测试数据
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.randn(30) * 2)
        
        self.test_df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(1000000000, 5000000000, 30)
        })
        
        # 反转数据顺序（最新的在前）
        self.test_df = self.test_df.iloc[::-1].reset_index(drop=True)
        
        self.strategy = MultiDeathCrossStrategy()
    
    def test_calculate_indicators_returns_dataframe(self):
        """测试calculate_indicators返回DataFrame"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证返回类型
        self.assertIsInstance(result, pd.DataFrame)
        
        # 验证返回的行数与输入相同
        self.assertEqual(len(result), len(self.test_df))
    
    def test_calculate_indicators_includes_ma(self):
        """测试calculate_indicators计算均线指标"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证均线列存在
        self.assertIn('ma_short', result.columns)
        self.assertIn('ma_long', result.columns)
        
        # 验证均线值合理
        valid_short = result['ma_short'].dropna()
        valid_long = result['ma_long'].dropna()
        if len(valid_short) > 0:
            self.assertTrue((valid_short > 0).all())
        if len(valid_long) > 0:
            self.assertTrue((valid_long > 0).all())
    
    def test_calculate_indicators_includes_kdj(self):
        """测试calculate_indicators计算KDJ指标"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证KDJ列存在
        self.assertIn('K', result.columns)
        self.assertIn('D', result.columns)
        self.assertIn('J', result.columns)
        
        # 验证KDJ值合理
        valid_k = result['K'].dropna()
        valid_d = result['D'].dropna()
        valid_j = result['J'].dropna()
        if len(valid_k) > 0:
            self.assertTrue((valid_k >= 0).all() & (valid_k <= 100).all())
        if len(valid_d) > 0:
            self.assertTrue((valid_d >= 0).all() & (valid_d <= 100).all())
    
    def test_calculate_indicators_includes_macd(self):
        """测试calculate_indicators计算MACD指标"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证MACD列存在
        self.assertIn('DIF', result.columns)
        self.assertIn('DEA', result.columns)
        self.assertIn('MACD', result.columns)
        
        # 验证MACD值合理
        valid_dif = result['DIF'].dropna()
        valid_dea = result['DEA'].dropna()
        if len(valid_dif) > 0:
            self.assertTrue(valid_dif.notna().all())
        if len(valid_dea) > 0:
            self.assertTrue(valid_dea.notna().all())
    
    def test_calculate_indicators_includes_trend_lines(self):
        """测试calculate_indicators计算趋势线"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证趋势线列存在
        self.assertIn('short_term_trend', result.columns)
        self.assertIn('bull_bear_line', result.columns)
        
        # 验证趋势线值合理
        valid_trend = result['short_term_trend'].dropna()
        valid_bull = result['bull_bear_line'].dropna()
        if len(valid_trend) > 0:
            self.assertTrue((valid_trend > 0).all())
        if len(valid_bull) > 0:
            self.assertTrue((valid_bull > 0).all())
    
    def test_calculate_indicators_includes_market_cap(self):
        """测试calculate_indicators计算市值"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证市值列存在
        self.assertIn('market_cap', result.columns)
        
        # 验证市值值合理
        valid_cap = result['market_cap'].dropna()
        if len(valid_cap) > 0:
            self.assertTrue((valid_cap > 0).all())
    
    def test_calculate_indicators_includes_volume_ratio(self):
        """测试calculate_indicators计算成交量比"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证成交量比列存在
        self.assertIn('volume_ratio', result.columns)
        
        # 验证成交量比值合理
        valid_ratio = result['volume_ratio'].dropna()
        if len(valid_ratio) > 0:
            self.assertTrue((valid_ratio > 0).all())


class TestMultiDeathCrossDeathCross(unittest.TestCase):
    """测试死叉识别功能"""
    
    def setUp(self):
        """测试前准备 - 创建测试数据"""
        # 创建30天的测试数据
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.randn(30) * 2)
        
        self.test_df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(1000000000, 5000000000, 30)
        })
        
        # 反转数据顺序（最新的在前）
        self.test_df = self.test_df.iloc[::-1].reset_index(drop=True)
        
        self.strategy = MultiDeathCrossStrategy()
    
    def test_find_ma_death_cross_returns_date_or_none(self):
        """测试_find_ma_death_cross返回日期或None"""
        # 计算指标
        df_with_indicators = self.strategy.calculate_indicators(self.test_df)
        
        # 查找均线死叉
        ma_death_cross_date = self.strategy._find_ma_death_cross(df_with_indicators.head(10))
        
        # 验证返回类型
        self.assertTrue(ma_death_cross_date is None or isinstance(ma_death_cross_date, pd.Timestamp))
    
    def test_find_kdj_death_cross_returns_date_or_none(self):
        """测试_find_kdj_death_cross返回日期或None"""
        # 计算指标
        df_with_indicators = self.strategy.calculate_indicators(self.test_df)
        
        # 查找KDJ死叉
        kdj_death_cross_date = self.strategy._find_kdj_death_cross(df_with_indicators.head(10))
        
        # 验证返回类型
        self.assertTrue(kdj_death_cross_date is None or isinstance(kdj_death_cross_date, pd.Timestamp))
    
    def test_find_macd_death_cross_returns_date_or_none(self):
        """测试_find_macd_death_cross返回日期或None"""
        # 计算指标
        df_with_indicators = self.strategy.calculate_indicators(self.test_df)
        
        # 查找MACD死叉
        macd_death_cross_date = self.strategy._find_macd_death_cross(df_with_indicators.head(10))
        
        # 验证返回类型
        self.assertTrue(macd_death_cross_date is None or isinstance(macd_death_cross_date, pd.Timestamp))


class TestMultiDeathCrossResonance(unittest.TestCase):
    """测试共振确认功能"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = MultiDeathCrossStrategy()
    
    def test_check_resonance_with_same_dates(self):
        """测试_check_resonance相同日期的情况"""
        # 创建相同的日期
        date1 = pd.Timestamp('2024-01-01')
        date2 = pd.Timestamp('2024-01-01')
        date3 = pd.Timestamp('2024-01-01')
        
        # 验证共振条件满足
        result = self.strategy._check_resonance(date1, date2, date3)
        self.assertTrue(result)
    
    def test_check_resonance_with_close_dates(self):
        """测试_check_resonance相近日期的情况"""
        # 创建相近的日期（相隔1天）
        date1 = pd.Timestamp('2024-01-01')
        date2 = pd.Timestamp('2024-01-02')
        date3 = pd.Timestamp('2024-01-03')
        
        # 验证共振条件满足
        result = self.strategy._check_resonance(date1, date2, date3)
        self.assertTrue(result)
    
    def test_check_resonance_with_far_dates(self):
        """测试_check_resonance相隔较远日期的情况"""
        # 创建相隔较远的日期（相隔4天）
        date1 = pd.Timestamp('2024-01-01')
        date2 = pd.Timestamp('2024-01-05')
        date3 = pd.Timestamp('2024-01-06')
        
        # 验证共振条件不满足
        result = self.strategy._check_resonance(date1, date2, date3)
        self.assertFalse(result)
    
    def test_check_resonance_with_none_dates(self):
        """测试_check_resonance包含None的情况"""
        # 创建包含None的日期
        date1 = pd.Timestamp('2024-01-01')
        date2 = None
        date3 = pd.Timestamp('2024-01-03')
        
        # 验证共振条件不满足
        result = self.strategy._check_resonance(date1, date2, date3)
        self.assertFalse(result)
    
    def test_calculate_max_time_diff(self):
        """测试_calculate_max_time_diff计算最大时间差"""
        # 创建日期
        date1 = pd.Timestamp('2024-01-01')
        date2 = pd.Timestamp('2024-01-02')
        date3 = pd.Timestamp('2024-01-04')
        
        # 计算最大时间差
        max_diff = self.strategy._calculate_max_time_diff(date1, date2, date3)
        
        # 验证最大时间差为3天
        self.assertEqual(max_diff, 3)
    
    def test_calculate_max_time_diff_with_none(self):
        """测试_calculate_max_time_diff包含None的情况"""
        # 创建包含None的日期
        date1 = pd.Timestamp('2024-01-01')
        date2 = None
        date3 = pd.Timestamp('2024-01-03')
        
        # 计算最大时间差
        max_diff = self.strategy._calculate_max_time_diff(date1, date2, date3)
        
        # 验证最大时间差为2天（有效日期之间的时间差）
        self.assertEqual(max_diff, 2)


class TestMultiDeathCrossPriceConfirmation(unittest.TestCase):
    """测试价格确认功能"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = MultiDeathCrossStrategy()
    
    def test_check_price_confirmation_with_valid_data(self):
        """测试_check_price_confirmation有效数据的情况"""
        # 创建有效的最新数据
        latest = pd.Series({
            'close': 95.0,
            'ma_short': 100.0,
            'ma_long': 105.0,
            'short_term_trend': 100.0,
            'bull_bear_line': 105.0
        })
        
        # 验证价格确认条件满足
        result = self.strategy._check_price_confirmation(latest)
        self.assertTrue(result)
    
    def test_check_price_confirmation_with_price_above_ma(self):
        """测试_check_price_confirmation价格高于均线的情况"""
        # 创建价格高于均线的最新数据
        latest = pd.Series({
            'close': 110.0,
            'ma_short': 100.0,
            'ma_long': 105.0,
            'short_term_trend': 100.0,
            'bull_bear_line': 105.0
        })
        
        # 验证价格确认条件不满足
        result = self.strategy._check_price_confirmation(latest)
        self.assertFalse(result)
    
    def test_check_price_confirmation_with_nan_data(self):
        """测试_check_price_confirmation包含NaN的情况"""
        # 创建包含NaN的最新数据
        latest = pd.Series({
            'close': np.nan,
            'ma_short': 100.0,
            'ma_long': 105.0,
            'short_term_trend': 100.0,
            'bull_bear_line': 105.0
        })
        
        # 验证价格确认条件不满足
        result = self.strategy._check_price_confirmation(latest)
        self.assertFalse(result)


class TestMultiDeathCrossSelectStocks(unittest.TestCase):
    """测试选股功能"""
    
    def setUp(self):
        """测试前准备 - 创建测试数据"""
        # 创建30天的测试数据
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.randn(30) * 2)
        
        self.test_df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(1000000000, 5000000000, 30)
        })
        
        # 反转数据顺序（最新的在前）
        self.test_df = self.test_df.iloc[::-1].reset_index(drop=True)
        
        self.strategy = MultiDeathCrossStrategy()
    
    def test_select_stocks_returns_list(self):
        """测试select_stocks返回列表"""
        # 计算指标
        df_with_indicators = self.strategy.calculate_indicators(self.test_df)
        
        # 执行选股
        result = self.strategy.select_stocks(df_with_indicators)
        
        # 验证返回类型
        self.assertIsInstance(result, list)
    
    def test_select_stocks_with_empty_dataframe(self):
        """测试select_stocks空DataFrame的情况"""
        # 创建空DataFrame
        empty_df = pd.DataFrame()
        
        # 执行选股
        result = self.strategy.select_stocks(empty_df)
        
        # 验证返回空列表
        self.assertEqual(result, [])
    
    def test_select_stocks_with_insufficient_data(self):
        """测试select_stocks数据不足的情况"""
        # 创建只有5天的数据（少于lookback_days=10）
        dates = pd.date_range(end='2024-01-01', periods=5, freq='D')
        short_df = pd.DataFrame({
            'date': dates,
            'open': [100] * 5,
            'high': [105] * 5,
            'low': [95] * 5,
            'close': [100] * 5,
            'volume': [1000000] * 5,
            'market_cap': [1000000000] * 5
        })
        
        # 执行选股
        result = self.strategy.select_stocks(short_df)
        
        # 验证返回空列表
        self.assertEqual(result, [])
    
    def test_select_stocks_filters_invalid_stocks(self):
        """测试select_stocks过滤无效股票"""
        # 计算指标
        df_with_indicators = self.strategy.calculate_indicators(self.test_df)
        
        # 测试退市股票
        result = self.strategy.select_stocks(df_with_indicators, stock_name='退市股票')
        self.assertEqual(result, [])
        
        # 测试ST股票
        result = self.strategy.select_stocks(df_with_indicators, stock_name='ST股票')
        self.assertEqual(result, [])
        
        # 测试*ST股票
        result = self.strategy.select_stocks(df_with_indicators, stock_name='*ST股票')
        self.assertEqual(result, [])


class TestMultiDeathCrossIntegration(unittest.TestCase):
    """测试集成功能"""
    
    def setUp(self):
        """测试前准备 - 创建测试数据"""
        # 创建30天的测试数据
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.randn(30) * 2)
        
        self.test_df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(1000000000, 5000000000, 30)
        })
        
        # 反转数据顺序（最新的在前）
        self.test_df = self.test_df.iloc[::-1].reset_index(drop=True)
        
        self.strategy = MultiDeathCrossStrategy()
    
    def test_full_workflow(self):
        """测试完整工作流程"""
        # 计算指标
        df_with_indicators = self.strategy.calculate_indicators(self.test_df)
        
        # 验证指标计算成功
        self.assertIn('ma_short', df_with_indicators.columns)
        self.assertIn('K', df_with_indicators.columns)
        self.assertIn('DIF', df_with_indicators.columns)
        
        # 执行选股
        result = self.strategy.select_stocks(df_with_indicators)
        
        # 验证选股结果
        self.assertIsInstance(result, list)
        
        # 如果有选股结果，验证结果结构
        if len(result) > 0:
            signal = result[0]
            self.assertIn('date', signal)
            self.assertIn('close', signal)
            self.assertIn('ma_short', signal)
            self.assertIn('ma_long', signal)
            self.assertIn('K', signal)
            self.assertIn('D', signal)
            self.assertIn('J', signal)
            self.assertIn('DIF', signal)
            self.assertIn('DEA', signal)
            self.assertIn('MACD', signal)
            self.assertIn('volume_ratio', signal)
            self.assertIn('market_cap', signal)
            self.assertIn('short_term_trend', signal)
            self.assertIn('bull_bear_line', signal)
            self.assertIn('reasons', signal)


if __name__ == '__main__':
    unittest.main()
