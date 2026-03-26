"""
单元测试：缩量回调策略
测试目标：验证缩量回调策略的所有功能，包括指标计算、上升趋势判断、缩量回调判断、企稳信号判断、支撑确认判断等
"""
import unittest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.volume_shrinkage_pullback import VolumeShrinkagePullbackStrategy


class TestVolumeShrinkagePullbackIndicators(unittest.TestCase):
    """测试指标计算功能"""
    
    def setUp(self):
        """测试前准备 - 创建测试数据"""
        # 创建30天的测试数据
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据（上升趋势）
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.rand(30) * 2)
        
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
        
        self.strategy = VolumeShrinkagePullbackStrategy()
    
    def test_calculate_indicators_returns_dataframe(self):
        """测试calculate_indicators返回DataFrame"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证返回类型
        self.assertIsInstance(result, pd.DataFrame)
        
        # 验证返回的行数与输入相同
        self.assertEqual(len(result), len(self.test_df))
    
    def test_calculate_indicators_includes_ma_short(self):
        """测试calculate_indicators计算短期均线"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证短期均线列存在
        self.assertIn('ma_short', result.columns)
        
        # 验证短期均线值合理
        valid_ma = result['ma_short'].dropna()
        if len(valid_ma) > 0:
            self.assertTrue((valid_ma > 0).all())
    
    def test_calculate_indicators_includes_ma_long(self):
        """测试calculate_indicators计算长期均线"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证长期均线列存在
        self.assertIn('ma_long', result.columns)
        
        # 验证长期均线值合理
        valid_ma = result['ma_long'].dropna()
        if len(valid_ma) > 0:
            self.assertTrue((valid_ma > 0).all())
    
    def test_calculate_indicators_includes_volume_ma(self):
        """测试calculate_indicators计算成交量均线"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证成交量均线列存在
        self.assertIn('volume_ma', result.columns)
        
        # 验证成交量均线值合理
        valid_ma = result['volume_ma'].dropna()
        if len(valid_ma) > 0:
            self.assertTrue((valid_ma > 0).all())
    
    def test_calculate_indicators_includes_volume_ratio(self):
        """测试calculate_indicators计算成交量比"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证成交量比列存在
        self.assertIn('volume_ratio', result.columns)
        
        # 验证成交量比值合理
        valid_ratio = result['volume_ratio'].dropna()
        if len(valid_ratio) > 0:
            self.assertTrue((valid_ratio > 0).all())
    
    def test_calculate_indicators_includes_highest_price(self):
        """测试calculate_indicators计算最高价"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证最高价列存在
        self.assertIn('highest_price', result.columns)
        
        # 验证最高价值合理
        valid_price = result['highest_price'].dropna()
        if len(valid_price) > 0:
            self.assertTrue((valid_price > 0).all())
    
    def test_calculate_indicators_includes_pullback_ratio(self):
        """测试calculate_indicators计算回调幅度"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证回调幅度列存在
        self.assertIn('pullback_ratio', result.columns)
        
        # 验证回调幅度值在合理范围内（0-1）
        valid_ratio = result['pullback_ratio'].dropna()
        if len(valid_ratio) > 0:
            self.assertTrue((valid_ratio >= 0).all() and (valid_ratio <= 1).all())
    
    def test_calculate_indicators_includes_lowest_price(self):
        """测试calculate_indicators计算最低价"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证最低价列存在
        self.assertIn('lowest_price', result.columns)
        
        # 验证最低价值合理
        valid_price = result['lowest_price'].dropna()
        if len(valid_price) > 0:
            self.assertTrue((valid_price > 0).all())
    
    def test_calculate_indicators_includes_trend(self):
        """测试calculate_indicators计算趋势线"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证趋势线列存在
        self.assertIn('short_term_trend', result.columns)
        self.assertIn('bull_bear_line', result.columns)
        
        # 验证趋势线值不全为NaN
        self.assertTrue(result['short_term_trend'].notna().sum() > 0)
        self.assertTrue(result['bull_bear_line'].notna().sum() > 0)


class TestUptrendCheck(unittest.TestCase):
    """测试上升趋势判断功能"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = VolumeShrinkagePullbackStrategy()
    
    def _create_test_df(self, ma_short_above_long=True, ma_short_up=True):
        """
        创建测试数据框
        
        参数：
        - ma_short_above_long: 短期均线是否在长期均线上方
        - ma_short_up: 短期均线是否向上
        """
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.rand(30) * 2)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(1000000000, 5000000000, 30)
        })
        
        # 反转数据顺序（最新的在前）
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 修改均线值以满足测试条件
        # 设置长期均线值
        ma_long_value = 100.0
        
        # 设置短期均线值
        if ma_short_above_long:
            ma_short_value = ma_long_value + 5.0
        else:
            ma_short_value = ma_long_value - 5.0
        
        # 设置前一日的短期均线值
        if ma_short_up:
            prev_ma_short_value = ma_short_value - 1.0
        else:
            prev_ma_short_value = ma_short_value + 1.0
        
        # 修改最新一天和前一日的均线值
        df.loc[0, 'ma_short'] = ma_short_value
        df.loc[0, 'ma_long'] = ma_long_value
        df.loc[1, 'ma_short'] = prev_ma_short_value
        df.loc[1, 'ma_long'] = ma_long_value
        
        return df
    
    def test_check_uptrend_with_valid_uptrend(self):
        """测试_check_uptrend识别有效的上升趋势"""
        df = self._create_test_df(ma_short_above_long=True, ma_short_up=True)
        
        result = self.strategy._check_uptrend(df)
        
        # 验证识别为上升趋势
        self.assertTrue(result)
    
    def test_check_uptrend_with_ma_short_below_long(self):
        """测试_check_uptrend拒绝短期均线在长期均线下方"""
        df = self._create_test_df(ma_short_above_long=False, ma_short_up=True)
        
        result = self.strategy._check_uptrend(df)
        
        # 验证不识别为上升趋势
        self.assertFalse(result)
    
    def test_check_uptrend_with_ma_short_down(self):
        """测试_check_uptrend拒绝短期均线向下"""
        df = self._create_test_df(ma_short_above_long=True, ma_short_up=False)
        
        result = self.strategy._check_uptrend(df)
        
        # 验证不识别为上升趋势
        self.assertFalse(result)


class TestVolumeShrinkagePullbackCheck(unittest.TestCase):
    """测试缩量回调判断功能"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = VolumeShrinkagePullbackStrategy()
    
    def _create_test_df(self, pullback=True, pullback_ratio=0.15, volume_shrink=True):
        """
        创建测试数据框
        
        参数：
        - pullback: 是否回调
        - pullback_ratio: 回调幅度
        - volume_shrink: 是否缩量
        """
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.rand(30) * 2)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(1000000000, 5000000000, 30)
        })
        
        # 反转数据顺序（最新的在前）
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 设置基础值
        highest_price = 120.0
        volume_ma = 5000000.0
        
        # 修改数据以满足测试条件
        if pullback:
            current_close = highest_price * (1 - pullback_ratio)
        else:
            current_close = highest_price
        
        if volume_shrink:
            current_volume = volume_ma * 0.4
        else:
            current_volume = volume_ma * 1.5
        
        # 设置最新一天的值
        df.loc[0, 'close'] = current_close
        df.loc[0, 'volume'] = current_volume
        df.loc[0, 'highest_price'] = highest_price
        df.loc[0, 'volume_ma'] = volume_ma
        df.loc[0, 'pullback_ratio'] = (highest_price - current_close) / highest_price
        df.loc[0, 'volume_ratio'] = current_volume / volume_ma
        
        return df
    
    def test_check_volume_shrinkage_pullback_with_valid_pullback(self):
        """测试_check_volume_shrinkage_pullback识别有效的缩量回调"""
        df = self._create_test_df(pullback=True, pullback_ratio=0.15, volume_shrink=True)
        
        result = self.strategy._check_volume_shrinkage_pullback(df)
        
        # 验证识别为缩量回调
        self.assertTrue(result['valid'])
        self.assertIn('pullback_ratio', result)
        self.assertIn('highest_price', result)
        self.assertIn('volume_ratio', result)
    
    def test_check_volume_shrinkage_pullback_without_pullback(self):
        """测试_check_volume_shrinkage_pullback拒绝未回调"""
        df = self._create_test_df(pullback=False, pullback_ratio=0.15, volume_shrink=True)
        
        result = self.strategy._check_volume_shrinkage_pullback(df)
        
        # 验证不识别为缩量回调
        self.assertFalse(result['valid'])
        self.assertIn('reason', result)
    
    def test_check_volume_shrinkage_pullback_with_too_small_pullback(self):
        """测试_check_volume_shrinkage_pullback拒绝回调幅度过小"""
        df = self._create_test_df(pullback=True, pullback_ratio=0.05, volume_shrink=True)
        
        result = self.strategy._check_volume_shrinkage_pullback(df)
        
        # 验证不识别为缩量回调
        self.assertFalse(result['valid'])
        self.assertIn('reason', result)
    
    def test_check_volume_shrinkage_pullback_with_too_large_pullback(self):
        """测试_check_volume_shrinkage_pullback拒绝回调幅度过大"""
        df = self._create_test_df(pullback=True, pullback_ratio=0.25, volume_shrink=True)
        
        result = self.strategy._check_volume_shrinkage_pullback(df)
        
        # 验证不识别为缩量回调
        self.assertFalse(result['valid'])
        self.assertIn('reason', result)
    
    def test_check_volume_shrinkage_pullback_without_volume_shrinkage(self):
        """测试_check_volume_shrinkage_pullback拒绝未缩量"""
        df = self._create_test_df(pullback=True, pullback_ratio=0.15, volume_shrink=False)
        
        result = self.strategy._check_volume_shrinkage_pullback(df)
        
        # 验证不识别为缩量回调
        self.assertFalse(result['valid'])
        self.assertIn('reason', result)


class TestStabilizationCheck(unittest.TestCase):
    """测试企稳信号判断功能"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = VolumeShrinkagePullbackStrategy()
    
    def _create_test_df(self, price_stabilized=True, volume_expanded=True):
        """
        创建测试数据框
        
        参数：
        - price_stabilized: 价格是否企稳
        - volume_expanded: 成交量是否放大
        """
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.rand(30) * 2)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(1000000000, 5000000000, 30)
        })
        
        # 反转数据顺序（最新的在前）
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 设置基础值
        volume_ma = 5000000.0
        
        # 修改数据以满足测试条件
        if price_stabilized:
            # 确保最近2天收盘价企稳
            df.loc[0, 'close'] = 100.10
            df.loc[1, 'close'] = 100.05
            df.loc[2, 'close'] = 100.00
        else:
            # 确保价格持续下跌，且最新收盘价不大于前一日的收盘价
            df.loc[0, 'close'] = 99.95
            df.loc[1, 'close'] = 100.00
            df.loc[2, 'close'] = 99.90
        
        if volume_expanded:
            df.loc[0, 'volume'] = volume_ma * 1.5
        else:
            df.loc[0, 'volume'] = volume_ma * 0.8
        
        # 重新计算成交量比
        df.loc[0, 'volume_ma'] = volume_ma
        df.loc[0, 'volume_ratio'] = df.loc[0, 'volume'] / volume_ma
        
        return df
    
    def test_check_stabilization_with_valid_stabilization(self):
        """测试_check_stabilization识别有效的企稳信号"""
        df = self._create_test_df(price_stabilized=True, volume_expanded=True)
        
        result = self.strategy._check_stabilization(df)
        
        # 验证识别为企稳
        self.assertTrue(result)
    
    def test_check_stabilization_without_price_stabilization(self):
        """测试_check_stabilization拒绝价格未企稳"""
        df = self._create_test_df(price_stabilized=False, volume_expanded=True)
        
        result = self.strategy._check_stabilization(df)
        
        # 验证不识别为企稳
        self.assertFalse(result)
    
    def test_check_stabilization_without_volume_expansion(self):
        """测试_check_stabilization拒绝成交量未放大"""
        df = self._create_test_df(price_stabilized=True, volume_expanded=False)
        
        result = self.strategy._check_stabilization(df)
        
        # 验证不识别为企稳
        self.assertFalse(result)


class TestSupportCheck(unittest.TestCase):
    """测试支撑确认判断功能"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = VolumeShrinkagePullbackStrategy()
    
    def _create_test_df(self, ma_support=True, price_support=True):
        """
        创建测试数据框
        
        参数：
        - ma_support: 均线支撑是否有效
        - price_support: 价格支撑是否有效
        """
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.rand(30) * 2)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(1000000000, 5000000000, 30)
        })
        
        # 反转数据顺序（最新的在前）
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 设置基础值
        ma_short_value = 105.0
        ma_long_value = 100.0
        support_price = min(ma_short_value, ma_long_value)
        
        # 修改数据以满足测试条件
        if ma_support and price_support:
            # 确保收盘价在短期均线上方且在支撑位上方
            current_close = max(ma_short_value, support_price) + 0.1
        elif not ma_support:
            # 确保收盘价在所有均线下方
            current_close = support_price - 0.1
        elif not price_support:
            # 确保收盘价跌破支撑位
            current_close = support_price * 0.95
        else:
            current_close = support_price + 0.1
        
        # 设置最新一天的值
        df.loc[0, 'close'] = current_close
        df.loc[0, 'ma_short'] = ma_short_value
        df.loc[0, 'ma_long'] = ma_long_value
        
        return df
    
    def test_check_support_with_valid_support(self):
        """测试_check_support识别有效的支撑确认"""
        df = self._create_test_df(ma_support=True, price_support=True)
        
        result = self.strategy._check_support(df)
        
        # 验证识别为支撑确认
        self.assertTrue(result)
    
    def test_check_support_without_ma_support(self):
        """测试_check_support拒绝均线支撑无效"""
        df = self._create_test_df(ma_support=False, price_support=True)
        
        result = self.strategy._check_support(df)
        
        # 验证不识别为支撑确认
        self.assertFalse(result)
    
    def test_check_support_without_price_support(self):
        """测试_check_support拒绝价格支撑无效"""
        df = self._create_test_df(ma_support=True, price_support=False)
        
        result = self.strategy._check_support(df)
        
        # 验证不识别为支撑确认
        self.assertFalse(result)


class TestSelectStocks(unittest.TestCase):
    """测试综合选股逻辑"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = VolumeShrinkagePullbackStrategy()
    
    def _create_valid_test_df(self):
        """创建满足所有条件的测试数据"""
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        
        # 生成基础价格数据（上升趋势）
        np.random.seed(42)
        close_prices = 100 + np.cumsum(np.random.rand(30) * 2)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(1000000000, 5000000000, 30)
        })
        
        # 反转数据顺序（最新的在前）
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 设置基础值
        ma_long_value = 100.0
        ma_short_value = ma_long_value + 5.0
        prev_ma_short_value = ma_short_value - 1.0
        highest_price = 120.0
        volume_ma = 5000000.0
        pullback_ratio = 0.15
        current_close = highest_price * (1 - pullback_ratio)
        lowest_price = 100.0
        support_price = min(ma_short_value, ma_long_value)
        
        # 条件1：上升趋势
        df.loc[0, 'ma_short'] = ma_short_value
        df.loc[0, 'ma_long'] = ma_long_value
        df.loc[1, 'ma_short'] = prev_ma_short_value
        df.loc[1, 'ma_long'] = ma_long_value
        
        # 条件2：缩量回调
        df.loc[0, 'close'] = current_close
        df.loc[0, 'volume'] = volume_ma * 0.4
        df.loc[0, 'highest_price'] = highest_price
        df.loc[0, 'volume_ma'] = volume_ma
        df.loc[0, 'pullback_ratio'] = pullback_ratio
        df.loc[0, 'volume_ratio'] = 0.4
        
        # 条件3：企稳信号
        df.loc[0, 'close'] = lowest_price + 0.1
        df.loc[1, 'close'] = lowest_price + 0.05
        df.loc[0, 'volume'] = volume_ma * 1.5
        df.loc[0, 'volume_ratio'] = 1.5
        
        # 条件4：支撑确认
        df.loc[0, 'close'] = support_price + 0.1
        
        return df
    
    def test_select_stocks_with_valid_conditions(self):
        """测试select_stocks识别满足所有条件的股票"""
        df = self._create_valid_test_df()
        
        signals = self.strategy.select_stocks(df, stock_name='测试股票')
        
        # 验证返回信号列表
        self.assertIsInstance(signals, list)
        self.assertEqual(len(signals), 1)
        
        # 验证信号内容
        signal = signals[0]
        self.assertIn('date', signal)
        self.assertIn('close', signal)
        self.assertIn('reasons', signal)
        self.assertIn('pattern_details', signal)
    
    def test_select_stocks_without_uptrend(self):
        """测试select_stocks拒绝不满足上升趋势的股票"""
        # 创建一个上升趋势的数据
        df = self._create_valid_test_df()
        
        # 修改数据使其不满足上升趋势
        # 在select_stocks调用后修改均线值
        original_check_uptrend = self.strategy._check_uptrend
        
        def mock_check_uptrend(df):
            return False
        
        self.strategy._check_uptrend = mock_check_uptrend
        
        try:
            signals = self.strategy.select_stocks(df, stock_name='测试股票')
            
            # 验证不返回信号
            self.assertEqual(len(signals), 0)
        finally:
            self.strategy._check_uptrend = original_check_uptrend
    
    def test_select_stocks_without_pullback(self):
        """测试select_stocks拒绝不满足缩量回调的股票"""
        df = self._create_valid_test_df()
        
        # Mock _check_volume_shrinkage_pullback 返回无效
        original_check_pullback = self.strategy._check_volume_shrinkage_pullback
        
        def mock_check_pullback(df):
            return {'valid': False, 'reason': '测试：未回调'}
        
        self.strategy._check_volume_shrinkage_pullback = mock_check_pullback
        
        try:
            signals = self.strategy.select_stocks(df, stock_name='测试股票')
            
            # 验证不返回信号
            self.assertEqual(len(signals), 0)
        finally:
            self.strategy._check_volume_shrinkage_pullback = original_check_pullback
    
    def test_select_stocks_without_stabilization(self):
        """测试select_stocks拒绝不满足企稳信号的股票"""
        df = self._create_valid_test_df()
        
        # Mock _check_stabilization 返回False
        original_check_stabilization = self.strategy._check_stabilization
        
        def mock_check_stabilization(df):
            return False
        
        self.strategy._check_stabilization = mock_check_stabilization
        
        try:
            signals = self.strategy.select_stocks(df, stock_name='测试股票')
            
            # 验证不返回信号
            self.assertEqual(len(signals), 0)
        finally:
            self.strategy._check_stabilization = original_check_stabilization
    
    def test_select_stocks_without_support(self):
        """测试select_stocks拒绝不满足支撑确认的股票"""
        df = self._create_valid_test_df()
        
        # Mock _check_support 返回False
        original_check_support = self.strategy._check_support
        
        def mock_check_support(df):
            return False
        
        self.strategy._check_support = mock_check_support
        
        try:
            signals = self.strategy.select_stocks(df, stock_name='测试股票')
            
            # 验证不返回信号
            self.assertEqual(len(signals), 0)
        finally:
            self.strategy._check_support = original_check_support
    
    def test_select_stocks_filters_st_stocks(self):
        """测试select_stocks过滤ST股票"""
        df = self._create_valid_test_df()
        
        signals = self.strategy.select_stocks(df, stock_name='ST测试股票')
        
        # 验证不返回信号
        self.assertEqual(len(signals), 0)
    
    def test_select_stocks_filters_asterisk_st_stocks(self):
        """测试select_stocks过滤*ST股票"""
        df = self._create_valid_test_df()
        
        signals = self.strategy.select_stocks(df, stock_name='*ST测试股票')
        
        # 验证不返回信号
        self.assertEqual(len(signals), 0)
    
    def test_select_stocks_filters_delisted_stocks(self):
        """测试select_stocks过滤退市股票"""
        df = self._create_valid_test_df()
        
        signals = self.strategy.select_stocks(df, stock_name='退测试股票')
        
        # 验证不返回信号
        self.assertEqual(len(signals), 0)
    
    def test_select_stocks_filters_market_cap(self):
        """测试select_stocks过滤市值不符合的股票"""
        df = self._create_valid_test_df()
        df.loc[0, 'market_cap'] = 1e7  # 1000万，小于最小市值20亿
        
        signals = self.strategy.select_stocks(df, stock_name='测试股票')
        
        # 验证不返回信号
        self.assertEqual(len(signals), 0)


class TestValidateData(unittest.TestCase):
    """测试数据验证功能"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = VolumeShrinkagePullbackStrategy()
    
    def test_validate_data_with_valid_df(self):
        """测试_validate_data接受有效的DataFrame"""
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        close_prices = 100 + np.cumsum(np.random.rand(30) * 2)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(30),
            'high': close_prices + np.random.rand(30) * 2,
            'low': close_prices - np.random.rand(30) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30)
        })
        
        result = self.strategy._validate_data(df)
        
        # 验证验证通过
        self.assertTrue(result)
    
    def test_validate_data_with_none_df(self):
        """测试_validate_data拒绝None"""
        result = self.strategy._validate_data(None)
        
        # 验证验证失败
        self.assertFalse(result)
    
    def test_validate_data_with_empty_df(self):
        """测试_validate_data拒绝空DataFrame"""
        df = pd.DataFrame()
        
        result = self.strategy._validate_data(df)
        
        # 验证验证失败
        self.assertFalse(result)
    
    def test_validate_data_with_insufficient_data(self):
        """测试_validate_data拒绝数据不足"""
        dates = pd.date_range(end='2024-01-01', periods=10, freq='D')
        close_prices = 100 + np.cumsum(np.random.rand(10) * 2)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices - np.random.rand(10),
            'high': close_prices + np.random.rand(10) * 2,
            'low': close_prices - np.random.rand(10) * 2,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 10)
        })
        
        result = self.strategy._validate_data(df)
        
        # 验证验证失败
        self.assertFalse(result)
    
    def test_validate_data_with_missing_fields(self):
        """测试_validate_data拒绝缺少必要字段"""
        dates = pd.date_range(end='2024-01-01', periods=30, freq='D')
        close_prices = 100 + np.cumsum(np.random.rand(30) * 2)
        
        df = pd.DataFrame({
            'date': dates,
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 30)
        })
        
        result = self.strategy._validate_data(df)
        
        # 验证验证失败
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
