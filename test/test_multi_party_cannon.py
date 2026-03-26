"""
单元测试：多方炮策略
测试目标：验证多方炮策略的所有功能，包括指标计算、形态识别、成交量条件、趋势过滤等
"""
import unittest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.multi_party_cannon import MultiPartyCannonStrategy


class TestMultiPartyCannonIndicators(unittest.TestCase):
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
        
        self.strategy = MultiPartyCannonStrategy()
    
    def test_calculate_indicators_returns_dataframe(self):
        """测试calculate_indicators返回DataFrame"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证返回类型
        self.assertIsInstance(result, pd.DataFrame)
        
        # 验证返回的行数与输入相同
        self.assertEqual(len(result), len(self.test_df))
    
    def test_calculate_indicators_includes_body_size(self):
        """测试calculate_indicators计算K线实体大小"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证body_size列存在
        self.assertIn('body_size', result.columns)
        
        # 验证body_size值非负
        self.assertTrue((result['body_size'] >= 0).all())
    
    def test_calculate_indicators_includes_candle_direction(self):
        """测试calculate_indicators计算K线方向"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证candle_direction列存在
        self.assertIn('candle_direction', result.columns)
        
        # 验证candle_direction值只能是1或-1
        valid_directions = result['candle_direction'].isin([1, -1])
        self.assertTrue(valid_directions.all())
    
    def test_calculate_indicators_includes_candle_rise(self):
        """测试calculate_indicators计算K线涨幅"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证candle_rise列存在
        self.assertIn('candle_rise', result.columns)
        
        # 验证candle_rise值合理
        self.assertTrue(result['candle_rise'].notna().sum() > 0)
    
    def test_calculate_indicators_includes_volume_ma(self):
        """测试calculate_indicators计算成交量均线"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证成交量均线列存在
        self.assertIn('VOLUME_MA5', result.columns)
        
        # 验证成交量均线值合理
        valid_ma = result['VOLUME_MA5'].dropna()
        if len(valid_ma) > 0:
            self.assertTrue((valid_ma > 0).all())
    
    def test_calculate_indicators_includes_macd(self):
        """测试calculate_indicators计算MACD指标"""
        result = self.strategy.calculate_indicators(self.test_df)
        
        # 验证MACD相关列存在
        self.assertIn('DIF', result.columns)
        self.assertIn('DEA', result.columns)
        self.assertIn('MACD', result.columns)
        
        # 验证MACD值不全为NaN
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


class TestPatternRecognition(unittest.TestCase):
    """测试形态识别功能"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = MultiPartyCannonStrategy()
    
    def _create_test_df(self, first_rise=0.05, second_body_ratio=0.4, 
                       second_fallback_ratio=0.3, third_rise=0.05,
                       first_volume=1000000, second_volume=800000, third_volume=1200000):
        """
        创建测试数据框
        
        参数：
        - first_rise: 第一根阳线涨幅
        - second_body_ratio: 第二根阴线实体占第一根的比例
        - second_fallback_ratio: 第二根阴线回调占第一根涨幅的比例
        - third_rise: 第三根阳线涨幅
        - first_volume: 第一根成交量
        - second_volume: 第二根成交量
        - third_volume: 第三根成交量
        """
        # 创建10天的数据
        dates = pd.date_range(end='2024-01-01', periods=10, freq='D')
        
        # 基础价格
        base_price = 100.0
        
        # 计算第一根K线的价格
        first_open = base_price
        first_close = base_price * (1 + first_rise)
        first_body = first_close - first_open
        
        # 计算第二根K线的价格（阴线）
        # 使用second_body_ratio来计算实体大小
        second_body = first_body * second_body_ratio
        
        # 如果second_fallback_ratio为负数，表示第二根是阳线（用于测试）
        if second_fallback_ratio < 0:
            # 第二根是阳线
            second_open = first_close
            second_close = second_open * (1 + abs(second_fallback_ratio))
        else:
            # 第二根是阴线
            # 计算回调后的收盘价
            second_close = first_close * (1 - first_rise * second_fallback_ratio)
            # 确保实体大小符合second_body_ratio
            second_open = second_close + second_body
        
        # 计算第三根K线的价格（阳线）
        third_open = second_close
        third_close = third_open * (1 + third_rise)
        
        # 构建数据
        data = []
        for i in range(10):
            if i == 0:  # 第三根K线（最新）
                data.append({
                    'date': dates[9 - i],
                    'open': third_open,
                    'close': third_close,
                    'high': max(third_open, third_close) * 1.01,
                    'low': min(third_open, third_close) * 0.99,
                    'volume': third_volume,
                })
            elif i == 1:  # 第二根K线
                data.append({
                    'date': dates[9 - i],
                    'open': second_open,
                    'close': second_close,
                    'high': max(second_open, second_close) * 1.01,
                    'low': min(second_open, second_close) * 0.99,
                    'volume': second_volume,
                })
            elif i == 2:  # 第一根K线
                data.append({
                    'date': dates[9 - i],
                    'open': first_open,
                    'close': first_close,
                    'high': max(first_open, first_close) * 1.01,
                    'low': min(first_open, first_close) * 0.99,
                    'volume': first_volume,
                })
            else:  # 其他天
                data.append({
                    'date': dates[9 - i],
                    'open': base_price,
                    'close': base_price,
                    'high': base_price * 1.01,
                    'low': base_price * 0.99,
                    'volume': 1000000,
                })
        
        df = pd.DataFrame(data)
        df = df.sort_values('date', ascending=False).reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        return df
    
    def test_standard_multi_party_cannon(self):
        """测试标准多方炮形态"""
        # 禁用趋势过滤以简化测试
        self.strategy.params['enable_ma_filter'] = False
        self.strategy.params['enable_macd_filter'] = False
        self.strategy.params['enable_kdj_filter'] = False
        
        # 创建标准多方炮数据
        df = self._create_test_df(
            first_rise=0.05,      # 第一根阳线涨幅5%
            second_body_ratio=0.4,  # 第二根阴线实体占40%
            second_fallback_ratio=0.3,  # 回调30%
            third_rise=0.05,       # 第三根阳线涨幅5%
            first_volume=1000000,
            second_volume=800000,    # 缩量80%
            third_volume=1200000     # 放量120%
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]   # 第三根（最新）
        second_candle = df.iloc[1]  # 第二根
        first_candle = df.iloc[2]   # 第一根
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证满足形态
        self.assertTrue(result)
    
    def test_strong_multi_party_cannon(self):
        """测试强势多方炮形态（涨幅≥7%）"""
        # 禁用趋势过滤以简化测试
        self.strategy.params['enable_ma_filter'] = False
        self.strategy.params['enable_macd_filter'] = False
        self.strategy.params['enable_kdj_filter'] = False
        
        # 创建强势多方炮数据
        df = self._create_test_df(
            first_rise=0.08,      # 第一根阳线涨幅8%（大阳线）
            second_body_ratio=0.4,
            second_fallback_ratio=0.3,
            third_rise=0.08,       # 第三根阳线涨幅8%（大阳线）
            first_volume=1000000,
            second_volume=800000,
            third_volume=1500000     # 放量150%
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证满足形态
        self.assertTrue(result)
        
        # 验证分类为强势
        category = self.strategy._classify_pattern(
            first_candle, second_candle, third_candle
        )
        self.assertEqual(category, 'strong')
    
    def test_weak_multi_party_cannon(self):
        """测试弱势多方炮形态（涨幅1%-3%）"""
        # 禁用趋势过滤以简化测试
        self.strategy.params['enable_ma_filter'] = False
        self.strategy.params['enable_macd_filter'] = False
        self.strategy.params['enable_kdj_filter'] = False
        
        # 调整涨幅阈值以适应弱势多方炮
        self.strategy.params['first_candle_rise'] = 0.01  # 1%
        self.strategy.params['third_candle_rise'] = 0.01  # 1%
        
        # 创建弱势多方炮数据
        df = self._create_test_df(
            first_rise=0.02,      # 第一根阳线涨幅2%（小阳线）
            second_body_ratio=0.4,
            second_fallback_ratio=0.3,
            third_rise=0.02,       # 第三根阳线涨幅2%（小阳线）
            first_volume=1000000,
            second_volume=800000,
            third_volume=1200000
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证满足形态
        self.assertTrue(result)
        
        # 验证分类为弱势
        category = self.strategy._classify_pattern(
            first_candle, second_candle, third_candle
        )
        self.assertEqual(category, 'weak')
    
    def test_first_candle_not_bullish(self):
        """测试不满足条件：第一根K线不是阳线"""
        # 禁用趋势过滤以简化测试
        self.strategy.params['enable_ma_filter'] = False
        self.strategy.params['enable_macd_filter'] = False
        self.strategy.params['enable_kdj_filter'] = False
        
        # 创建第一根为阴线的数据
        df = self._create_test_df(
            first_rise=-0.02,     # 第一根是阴线
            second_body_ratio=0.4,
            second_fallback_ratio=0.3,
            third_rise=0.05,
            first_volume=1000000,
            second_volume=800000,
            third_volume=1200000
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证不满足形态
        self.assertFalse(result)
    
    def test_second_candle_not_bearish(self):
        """测试不满足条件：第二根K线不是阴线"""
        # 禁用趋势过滤以简化测试
        self.strategy.params['enable_ma_filter'] = False
        self.strategy.params['enable_macd_filter'] = False
        self.strategy.params['enable_kdj_filter'] = False
        
        # 创建第二根为阳线的数据
        df = self._create_test_df(
            first_rise=0.05,
            second_body_ratio=0.4,
            second_fallback_ratio=-0.1,  # 第二根是阳线
            third_rise=0.05,
            first_volume=1000000,
            second_volume=800000,
            third_volume=1200000
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证不满足形态
        self.assertFalse(result)
    
    def test_third_candle_not_bullish(self):
        """测试不满足条件：第三根K线不是阳线"""
        # 禁用趋势过滤以简化测试
        self.strategy.params['enable_ma_filter'] = False
        self.strategy.params['enable_macd_filter'] = False
        self.strategy.params['enable_kdj_filter'] = False
        
        # 创建第三根为阴线的数据
        df = self._create_test_df(
            first_rise=0.05,
            second_body_ratio=0.4,
            second_fallback_ratio=0.3,
            third_rise=-0.02,     # 第三根是阴线
            first_volume=1000000,
            second_volume=800000,
            third_volume=1200000
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证不满足形态
        self.assertFalse(result)
    
    def test_second_candle_body_too_large(self):
        """测试不满足条件：第二根阴线实体过大"""
        # 禁用趋势过滤以简化测试
        self.strategy.params['enable_ma_filter'] = False
        self.strategy.params['enable_macd_filter'] = False
        self.strategy.params['enable_kdj_filter'] = False
        
        # 创建第二根阴线实体过大的数据
        df = self._create_test_df(
            first_rise=0.05,
            second_body_ratio=0.6,   # 第二根实体占60%（超过50%阈值）
            second_fallback_ratio=0.3,
            third_rise=0.05,
            first_volume=1000000,
            second_volume=800000,
            third_volume=1200000
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证不满足形态
        self.assertFalse(result)
    
    def test_second_candle_fallback_too_large(self):
        """测试不满足条件：第二根阴线回调过大"""
        # 禁用趋势过滤以简化测试
        self.strategy.params['enable_ma_filter'] = False
        self.strategy.params['enable_macd_filter'] = False
        self.strategy.params['enable_kdj_filter'] = False
        
        # 创建第二根阴线回调过大的数据
        df = self._create_test_df(
            first_rise=0.05,
            second_body_ratio=0.4,
            second_fallback_ratio=0.6,   # 回调60%（超过50%阈值）
            third_rise=0.05,
            first_volume=1000000,
            second_volume=800000,
            third_volume=1200000
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证不满足形态
        self.assertFalse(result)


class TestVolumeConditions(unittest.TestCase):
    """测试成交量条件"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = MultiPartyCannonStrategy()
        # 禁用趋势过滤以简化测试
        self.strategy.params['enable_ma_filter'] = False
        self.strategy.params['enable_macd_filter'] = False
        self.strategy.params['enable_kdj_filter'] = False
    
    def _create_test_df(self, first_volume=1000000, second_volume=800000, third_volume=1200000):
        """创建测试数据框"""
        dates = pd.date_range(end='2024-01-01', periods=10, freq='D')
        
        # 计算三根K线的价格
        base_price = 100.0
        first_rise = 0.05
        second_body_ratio = 0.4
        second_fallback_ratio = 0.3
        third_rise = 0.05
        
        first_open = base_price
        first_close = base_price * (1 + first_rise)
        first_body = first_close - first_open
        
        second_body = first_body * second_body_ratio
        second_close = first_close * (1 - first_rise * second_fallback_ratio)
        second_open = second_close + second_body
        
        third_open = second_close
        third_close = third_open * (1 + third_rise)
        
        data = []
        for i in range(10):
            if i == 0:  # 第三根K线（最新）
                data.append({
                    'date': dates[9 - i],
                    'open': third_open,
                    'close': third_close,
                    'high': max(third_open, third_close) * 1.01,
                    'low': min(third_open, third_close) * 0.99,
                    'volume': third_volume,
                })
            elif i == 1:  # 第二根K线
                data.append({
                    'date': dates[9 - i],
                    'open': second_open,
                    'close': second_close,
                    'high': max(second_open, second_close) * 1.01,
                    'low': min(second_open, second_close) * 0.99,
                    'volume': second_volume,
                })
            elif i == 2:  # 第一根K线
                data.append({
                    'date': dates[9 - i],
                    'open': first_open,
                    'close': first_close,
                    'high': max(first_open, first_close) * 1.01,
                    'low': min(first_open, first_close) * 0.99,
                    'volume': first_volume,
                })
            else:  # 其他天
                data.append({
                    'date': dates[9 - i],
                    'open': base_price,
                    'close': base_price,
                    'high': base_price * 1.01,
                    'low': base_price * 0.99,
                    'volume': 1000000,
                })
        
        df = pd.DataFrame(data)
        df = df.sort_values('date', ascending=False).reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        return df
    
    def test_second_candle_shrink_volume(self):
        """测试第二根阴线缩量（≤80%）"""
        df = self._create_test_df(
            first_volume=1000000,
            second_volume=800000,   # 缩量80%
            third_volume=1200000
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证满足形态（缩量条件满足）
        self.assertTrue(result)
    
    def test_second_candle_not_shrink_volume(self):
        """测试第二根阴线不缩量（>80%）"""
        df = self._create_test_df(
            first_volume=1000000,
            second_volume=900000,   # 不缩量（90% > 80%）
            third_volume=1200000
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证不满足形态（缩量条件不满足）
        self.assertFalse(result)
    
    def test_third_candle_expand_volume(self):
        """测试第三根阳线放量（≥120%）"""
        df = self._create_test_df(
            first_volume=1000000,
            second_volume=800000,
            third_volume=1200000   # 放量120%
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证满足形态（放量条件满足）
        self.assertTrue(result)
    
    def test_third_candle_not_expand_volume(self):
        """测试第三根阳线不放量（<120%）"""
        df = self._create_test_df(
            first_volume=1000000,
            second_volume=800000,
            third_volume=1100000   # 不放量（110% < 120%）
        )
        
        # 获取三根K线
        third_candle = df.iloc[0]
        second_candle = df.iloc[1]
        first_candle = df.iloc[2]
        
        # 测试形态识别
        result = self.strategy._is_multi_party_cannon_pattern(
            first_candle, second_candle, third_candle
        )
        
        # 验证不满足形态（放量条件不满足）
        self.assertFalse(result)


class TestTrendFilters(unittest.TestCase):
    """测试趋势过滤条件"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = MultiPartyCannonStrategy()
    
    def _create_test_df(self, enable_ma=True, enable_macd=False, enable_kdj=False):
        """创建测试数据框"""
        dates = pd.date_range(end='2024-01-01', periods=10, freq='D')
        
        data = []
        for i in range(10):
            if i == 0:  # 第三根K线（最新）
                data.append({
                    'date': dates[9 - i],
                    'open': 100.0,
                    'close': 105.0,
                    'high': 105.5,
                    'low': 99.5,
                    'volume': 1200000,
                    'MA20': 102.0 if enable_ma else 106.0,  # 股价在均线上方
                    'MACD': 0.5 if enable_macd else -0.5,  # MACD>0
                    'J': 70 if enable_kdj else 85,  # J<80
                })
            elif i == 1:  # 第二根K线
                data.append({
                    'date': dates[9 - i],
                    'open': 105.0,
                    'close': 103.5,
                    'high': 105.5,
                    'low': 103.0,
                    'volume': 800000,
                    'MA20': 102.0,
                    'MACD': 0.5,
                    'J': 70,
                })
            elif i == 2:  # 第一根K线
                data.append({
                    'date': dates[9 - i],
                    'open': 100.0,
                    'close': 105.0,
                    'high': 105.5,
                    'low': 99.5,
                    'volume': 1000000,
                    'MA20': 102.0,
                    'MACD': 0.5,
                    'J': 70,
                })
            else:  # 其他天
                data.append({
                    'date': dates[9 - i],
                    'open': 100.0,
                    'close': 100.0,
                    'high': 100.5,
                    'low': 99.5,
                    'volume': 1000000,
                    'MA20': 102.0,
                    'MACD': 0.5,
                    'J': 70,
                })
        
        df = pd.DataFrame(data)
        df = df.sort_values('date', ascending=False).reset_index(drop=True)
        
        return df
    
    def test_ma_filter_enabled_satisfied(self):
        """测试均线过滤启用且满足条件"""
        # 启用均线过滤
        self.strategy.params['enable_ma_filter'] = True
        self.strategy.params['ma_period'] = 20
        
        df = self._create_test_df(enable_ma=True)
        
        # 获取第三根K线
        third_candle = df.iloc[0]
        
        # 测试趋势过滤
        result = self.strategy._check_trend_filters(third_candle)
        
        # 验证满足条件
        self.assertTrue(result)
    
    def test_ma_filter_enabled_not_satisfied(self):
        """测试均线过滤启用但不满足条件"""
        # 启用均线过滤
        self.strategy.params['enable_ma_filter'] = True
        self.strategy.params['ma_period'] = 20
        
        df = self._create_test_df(enable_ma=False)  # 股价在均线下方
        
        # 获取第三根K线
        third_candle = df.iloc[0]
        
        # 测试趋势过滤
        result = self.strategy._check_trend_filters(third_candle)
        
        # 验证不满足条件
        self.assertFalse(result)
    
    def test_ma_filter_disabled(self):
        """测试均线过滤禁用"""
        # 禁用均线过滤
        self.strategy.params['enable_ma_filter'] = False
        
        df = self._create_test_df(enable_ma=False)  # 股价在均线下方
        
        # 获取第三根K线
        third_candle = df.iloc[0]
        
        # 测试趋势过滤
        result = self.strategy._check_trend_filters(third_candle)
        
        # 验证满足条件（均线过滤禁用，不影响结果）
        self.assertTrue(result)
    
    def test_macd_filter_enabled_satisfied(self):
        """测试MACD过滤启用且满足条件"""
        # 启用MACD过滤
        self.strategy.params['enable_macd_filter'] = True
        self.strategy.params['macd_above_zero'] = True
        
        df = self._create_test_df(enable_macd=True)  # MACD>0
        
        # 获取第三根K线
        third_candle = df.iloc[0]
        
        # 测试趋势过滤
        result = self.strategy._check_trend_filters(third_candle)
        
        # 验证满足条件
        self.assertTrue(result)
    
    def test_macd_filter_enabled_not_satisfied(self):
        """测试MACD过滤启用但不满足条件"""
        # 启用MACD过滤
        self.strategy.params['enable_macd_filter'] = True
        self.strategy.params['macd_above_zero'] = True
        
        df = self._create_test_df(enable_macd=False)  # MACD<0
        
        # 获取第三根K线
        third_candle = df.iloc[0]
        
        # 测试趋势过滤
        result = self.strategy._check_trend_filters(third_candle)
        
        # 验证不满足条件
        self.assertFalse(result)
    
    def test_kdj_filter_enabled_satisfied(self):
        """测试KDJ过滤启用且满足条件"""
        # 启用KDJ过滤
        self.strategy.params['enable_kdj_filter'] = True
        self.strategy.params['kdj_j_max'] = 80
        
        df = self._create_test_df(enable_kdj=True)  # J=70<80
        
        # 获取第三根K线
        third_candle = df.iloc[0]
        
        # 测试趋势过滤
        result = self.strategy._check_trend_filters(third_candle)
        
        # 验证满足条件
        self.assertTrue(result)
    
    def test_kdj_filter_enabled_not_satisfied(self):
        """测试KDJ过滤启用但不满足条件"""
        # 启用KDJ过滤
        self.strategy.params['enable_kdj_filter'] = True
        self.strategy.params['kdj_j_max'] = 80
        
        df = self._create_test_df(enable_kdj=False)  # J=85>80
        
        # 获取第三根K线
        third_candle = df.iloc[0]
        
        # 测试趋势过滤
        result = self.strategy._check_trend_filters(third_candle)
        
        # 验证不满足条件
        self.assertFalse(result)


class TestSelectStocks(unittest.TestCase):
    """测试综合选股逻辑"""
    
    def setUp(self):
        """测试前准备"""
        self.strategy = MultiPartyCannonStrategy()
    
    def test_select_stocks_filter_st_stock(self):
        """测试过滤ST股票"""
        # 创建测试数据
        dates = pd.date_range(end='2024-01-01', periods=10, freq='D')
        
        df = pd.DataFrame({
            'date': dates,
            'open': [100] * 10,
            'high': [105] * 10,
            'low': [99] * 10,
            'close': [105] + [103.5] + [105] + [100] * 7,
            'volume': [1200000] + [800000] + [1000000] + [1000000] * 7,
            'market_cap': [1000000000] * 10,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 选股（使用ST股票名称）
        result = self.strategy.select_stocks(df, stock_name='ST测试')
        
        # 验证被过滤
        self.assertEqual(len(result), 0)
    
    def test_select_stocks_filter_star_st_stock(self):
        """测试过滤*ST股票"""
        # 创建测试数据
        dates = pd.date_range(end='2024-01-01', periods=10, freq='D')
        
        df = pd.DataFrame({
            'date': dates,
            'open': [100] * 10,
            'high': [105] * 10,
            'low': [99] * 10,
            'close': [105] + [103.5] + [105] + [100] * 7,
            'volume': [1200000] + [800000] + [1000000] + [1000000] * 7,
            'market_cap': [1000000000] * 10,
        })
        
        # 反转数据顺序
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        df = self.strategy.calculate_indicators(df)
        
        # 选股（使用*ST股票名称）
        result = self.strategy.select_stocks(df, stock_name='*ST测试')
        
        # 验证被过滤
        self.assertEqual(len(result), 0)
    
    def test_select_stocks_insufficient_data(self):
        """测试数据不足时返回空列表"""
        # 创建数据不足的测试数据（少于3天）
        dates = pd.date_range(end='2024-01-01', periods=2, freq='D')
        
        df = pd.DataFrame({
            'date': dates,
            'open': [100] * 2,
            'high': [105] * 2,
            'low': [99] * 2,
            'close': [105, 103.5],
            'volume': [1200000, 800000],
            'market_cap': [1000000000] * 2,
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


if __name__ == '__main__':
    unittest.main()
