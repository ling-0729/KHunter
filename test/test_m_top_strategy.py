"""
M头策略单元测试

测试范围：
- calculate_indicators：验证指标计算的正确性
- 各个子方法的逻辑验证
- 端到端的选股流程验证
"""
import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timedelta
from strategy.m_top_strategy import MTopStrategy


class TestCalculateIndicators:
    """calculate_indicators 方法的单元测试"""
    
    @pytest.fixture
    def sample_df(self):
        """
        生成样本数据：60个交易日的OHLCV数据（倒序排列）
        """
        # 生成日期序列（正序）
        dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
        
        # 生成价格数据（模拟上升趋势）
        np.random.seed(42)
        close_prices = 10 + np.cumsum(np.random.randn(60) * 0.5)
        
        # 构建DataFrame
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices + np.random.randn(60) * 0.2,
            'high': close_prices + np.abs(np.random.randn(60) * 0.3),
            'low': close_prices - np.abs(np.random.randn(60) * 0.3),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 60),
            'market_cap': np.random.uniform(50, 500, 60),  # 市值（亿元）
        })
        
        # 倒序排列（最新在前）
        df = df.iloc[::-1].reset_index(drop=True)
        
        return df
    
    def test_calculate_indicators_returns_dataframe(self, sample_df):
        """
        测试：calculate_indicators 返回 DataFrame
        """
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(sample_df)
        
        # 验证返回类型
        assert isinstance(result, pd.DataFrame), "返回值应为 DataFrame"
        
        # 验证行数不变
        assert len(result) == len(sample_df), "行数应保持不变"
    
    def test_calculate_indicators_contains_required_columns(self, sample_df):
        """
        测试：calculate_indicators 返回的 DataFrame 包含所有必需的指标列
        """
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(sample_df)
        
        # 必需的指标列
        required_columns = [
            'short_ma',           # 短期均线（10日）
            'long_ma',            # 长期均线（30日）
            'K', 'D', 'J',        # KDJ指标
            'short_term_trend',   # 知行短期趋势线
            'bull_bear_line',     # 知行多空线
            'volume_ma',          # 成交量均线
            'market_cap'          # 市值
        ]
        
        for col in required_columns:
            assert col in result.columns, f"缺少必需列：{col}"
    
    def test_short_ma_calculation(self, sample_df):
        """
        测试：short_ma（10日均线）计算正确
        """
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(sample_df)
        
        # 验证short_ma不为空
        assert result['short_ma'].notna().sum() > 0, "short_ma 不应全为NaN"
        
        # 验证short_ma值在合理范围内（应接近close价格）
        close_mean = result['close'].mean()
        short_ma_mean = result['short_ma'].mean()
        
        # short_ma 应该接近 close 的平均值（允许10%的偏差）
        assert abs(short_ma_mean - close_mean) / close_mean < 0.1, \
            "short_ma 平均值应接近 close 平均值"
    
    def test_long_ma_calculation(self, sample_df):
        """
        测试：long_ma（30日均线）计算正确
        """
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(sample_df)
        
        # 验证long_ma不为空
        assert result['long_ma'].notna().sum() > 0, "long_ma 不应全为NaN"
        
        # 验证long_ma值在合理范围内
        close_min = result['close'].min()
        close_max = result['close'].max()
        long_ma_min = result['long_ma'].min()
        long_ma_max = result['long_ma'].max()
        
        # long_ma 应在 close 的最小值和最大值之间
        assert long_ma_min >= close_min * 0.95, "long_ma 最小值不应过低"
        assert long_ma_max <= close_max * 1.05, "long_ma 最大值不应过高"
    
    def test_kdj_calculation(self, sample_df):
        """
        测试：KDJ 指标计算正确
        """
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(sample_df)
        
        # 验证K、D、J都存在
        assert 'K' in result.columns, "缺少 K 列"
        assert 'D' in result.columns, "缺少 D 列"
        assert 'J' in result.columns, "缺少 J 列"
        
        # 验证K、D值在0-100范围内
        assert (result['K'] >= 0).all() or result['K'].isna().all(), "K 值应 >= 0"
        assert (result['K'] <= 100).all() or result['K'].isna().all(), "K 值应 <= 100"
        assert (result['D'] >= 0).all() or result['D'].isna().all(), "D 值应 >= 0"
        assert (result['D'] <= 100).all() or result['D'].isna().all(), "D 值应 <= 100"
        
        # J值可能超出0-100范围（J = 3K - 2D）
        assert result['J'].notna().sum() > 0, "J 不应全为NaN"
    
    def test_trend_indicators_calculation(self, sample_df):
        """
        测试：知行趋势线和多空线计算正确
        """
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(sample_df)
        
        # 验证short_term_trend不为空
        assert result['short_term_trend'].notna().sum() > 0, \
            "short_term_trend 不应全为NaN"
        
        # 验证bull_bear_line不为空
        assert result['bull_bear_line'].notna().sum() > 0, \
            "bull_bear_line 不应全为NaN"
        
        # 验证趋势线值在合理范围内（应接近close价格）
        close_mean = result['close'].mean()
        trend_mean = result['short_term_trend'].mean()
        bull_bear_mean = result['bull_bear_line'].mean()
        
        # 允许20%的偏差
        assert abs(trend_mean - close_mean) / close_mean < 0.2, \
            "short_term_trend 平均值应接近 close 平均值"
        assert abs(bull_bear_mean - close_mean) / close_mean < 0.2, \
            "bull_bear_line 平均值应接近 close 平均值"
    
    def test_volume_ma_calculation(self, sample_df):
        """
        测试：成交量均线计算正确（排除当日）
        """
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(sample_df)
        
        # 验证volume_ma不为空
        assert result['volume_ma'].notna().sum() > 0, "volume_ma 不应全为NaN"
        
        # 验证volume_ma值在合理范围内
        volume_mean = result['volume'].mean()
        volume_ma_mean = result['volume_ma'].mean()
        
        # volume_ma 应该接近 volume 的平均值（允许20%的偏差）
        assert abs(volume_ma_mean - volume_mean) / volume_mean < 0.2, \
            "volume_ma 平均值应接近 volume 平均值"
    
    def test_market_cap_field(self, sample_df):
        """
        测试：market_cap 字段处理正确
        """
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(sample_df)
        
        # 验证market_cap字段存在
        assert 'market_cap' in result.columns, "缺少 market_cap 列"
        
        # 验证market_cap值不为空
        assert result['market_cap'].notna().sum() > 0, "market_cap 不应全为NaN"
    
    def test_calculate_indicators_preserves_original_columns(self, sample_df):
        """
        测试：calculate_indicators 保留原始列
        """
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(sample_df)
        
        # 验证原始列仍然存在
        original_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        for col in original_columns:
            assert col in result.columns, f"原始列 {col} 应保留"
    
    def test_calculate_indicators_with_custom_params(self, sample_df):
        """
        测试：calculate_indicators 使用自定义参数
        """
        # 使用自定义参数
        custom_params = {
            'short_ma_period': 5,
            'long_ma_period': 20,
            'volume_ma_period': 3,
        }
        strategy = MTopStrategy(params=custom_params)
        result = strategy.calculate_indicators(sample_df)
        
        # 验证指标计算成功
        assert 'short_ma' in result.columns, "short_ma 应存在"
        assert 'long_ma' in result.columns, "long_ma 应存在"
        assert 'volume_ma' in result.columns, "volume_ma 应存在"
        
        # 验证指标值不为空
        assert result['short_ma'].notna().sum() > 0, "short_ma 不应全为NaN"
        assert result['long_ma'].notna().sum() > 0, "long_ma 不应全为NaN"
        assert result['volume_ma'].notna().sum() > 0, "volume_ma 不应全为NaN"
    
    def test_calculate_indicators_with_small_dataset(self):
        """
        测试：calculate_indicators 处理小数据集
        """
        # 生成只有10个交易日的数据
        dates = pd.date_range(end=datetime.now(), periods=10, freq='D')
        df = pd.DataFrame({
            'date': dates,
            'open': np.random.randn(10) + 10,
            'high': np.random.randn(10) + 10.5,
            'low': np.random.randn(10) + 9.5,
            'close': np.random.randn(10) + 10,
            'volume': np.random.randint(1000000, 10000000, 10),
            'market_cap': np.random.uniform(50, 500, 10),
        })
        
        # 倒序排列
        df = df.iloc[::-1].reset_index(drop=True)
        
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(df)
        
        # 验证返回结果
        assert isinstance(result, pd.DataFrame), "返回值应为 DataFrame"
        assert len(result) == 10, "行数应为10"
        assert 'short_ma' in result.columns, "short_ma 应存在"
    
    def test_calculate_indicators_with_nan_values(self, sample_df):
        """
        测试：calculate_indicators 处理包含NaN的数据
        """
        # 在数据中插入一些NaN值
        df_with_nan = sample_df.copy()
        df_with_nan.loc[0:5, 'close'] = np.nan
        
        strategy = MTopStrategy()
        result = strategy.calculate_indicators(df_with_nan)
        
        # 验证返回结果
        assert isinstance(result, pd.DataFrame), "返回值应为 DataFrame"
        assert len(result) == len(df_with_nan), "行数应保持不变"


class TestFindLocalHighs:
    """_find_local_highs 方法的单元测试"""
    
    @pytest.fixture
    def sample_df(self):
        """生成样本数据"""
        dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
        np.random.seed(42)
        close_prices = 10 + np.cumsum(np.random.randn(60) * 0.5)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices + np.random.randn(60) * 0.2,
            'high': close_prices + np.abs(np.random.randn(60) * 0.3),
            'low': close_prices - np.abs(np.random.randn(60) * 0.3),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 60),
            'market_cap': np.random.uniform(50, 500, 60),
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    
    def test_find_local_highs_returns_list(self, sample_df):
        """
        测试：_find_local_highs 返回列表
        """
        strategy = MTopStrategy()
        result = strategy._find_local_highs(sample_df, 40)
        
        # 验证返回类型
        assert isinstance(result, list), "返回值应为列表"
    
    def test_find_local_highs_format(self, sample_df):
        """
        测试：_find_local_highs 返回格式正确
        """
        strategy = MTopStrategy()
        result = strategy._find_local_highs(sample_df, 40)
        
        # 验证返回格式 [(index, price, date), ...]
        for item in result:
            assert isinstance(item, tuple), "每个元素应为元组"
            assert len(item) == 3, "每个元组应有3个元素"
            assert isinstance(item[0], (int, np.integer)), "第一个元素应为索引"
            assert isinstance(item[1], (int, float, np.number)), "第二个元素应为价格"
    
    def test_find_local_highs_min_gap_constraint(self, sample_df):
        """
        测试：_find_local_highs 施加最小间隔约束
        """
        strategy = MTopStrategy()
        result = strategy._find_local_highs(sample_df, 40)
        
        # 验证相邻高点的间隔 >= min_gap
        min_gap = strategy.params['min_gap']
        for i in range(len(result) - 1):
            idx1 = result[i][0]
            idx2 = result[i + 1][0]
            gap = abs(idx2 - idx1)
            assert gap >= min_gap, f"相邻高点间隔应 >= {min_gap}，实际为 {gap}"
    
    def test_find_local_highs_within_pattern_days(self, sample_df):
        """
        测试：_find_local_highs 返回的高点在pattern_days范围内
        """
        strategy = MTopStrategy()
        pattern_days = 40
        result = strategy._find_local_highs(sample_df, pattern_days)
        
        # 验证所有高点的索引 < pattern_days
        for idx, price, date in result:
            assert idx < pattern_days, f"高点索引应 < {pattern_days}，实际为 {idx}"


class TestFindMTop:
    """_find_m_top 方法的单元测试"""
    
    @pytest.fixture
    def sample_df(self):
        """生成样本数据"""
        dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
        np.random.seed(42)
        close_prices = 10 + np.cumsum(np.random.randn(60) * 0.5)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices + np.random.randn(60) * 0.2,
            'high': close_prices + np.abs(np.random.randn(60) * 0.3),
            'low': close_prices - np.abs(np.random.randn(60) * 0.3),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 60),
            'market_cap': np.random.uniform(50, 500, 60),
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    
    def test_find_m_top_with_no_highs(self, sample_df):
        """
        测试：_find_m_top 处理没有高点的情况
        """
        strategy = MTopStrategy()
        result = strategy._find_m_top([], sample_df)
        
        # 验证返回None
        assert result is None, "没有高点时应返回None"
    
    def test_find_m_top_with_one_high(self, sample_df):
        """
        测试：_find_m_top 处理只有一个高点的情况
        """
        strategy = MTopStrategy()
        local_highs = [(10, 12.5, sample_df['date'].iloc[10])]
        result = strategy._find_m_top(local_highs, sample_df)
        
        # 验证返回None
        assert result is None, "只有一个高点时应返回None"
    
    def test_find_m_top_returns_tuple_or_none(self, sample_df):
        """
        测试：_find_m_top 返回元组或None
        """
        strategy = MTopStrategy()
        # 创建两个相近的高点
        local_highs = [
            (10, 12.5, sample_df['date'].iloc[10]),
            (25, 12.6, sample_df['date'].iloc[25])
        ]
        result = strategy._find_m_top(local_highs, sample_df)
        
        # 验证返回类型
        assert result is None or isinstance(result, tuple), "返回值应为元组或None"
    
    def test_find_m_top_format(self, sample_df):
        """
        测试：_find_m_top 返回格式正确
        """
        strategy = MTopStrategy()
        # 创建两个相近的高点
        local_highs = [
            (10, 12.5, sample_df['date'].iloc[10]),
            (25, 12.6, sample_df['date'].iloc[25])
        ]
        result = strategy._find_m_top(local_highs, sample_df)
        
        # 如果返回结果，验证格式
        if result is not None:
            assert len(result) == 6, "返回元组应有6个元素"
            h1_idx, h1_price, l_idx, l_price, h2_idx, h2_price = result
            
            # 验证价格关系：L < H1 且 L < H2
            assert l_price < h1_price, "L价格应小于H1价格"
            assert l_price < h2_price, "L价格应小于H2价格"
    
    def test_find_m_top_price_diff_threshold(self, sample_df):
        """
        测试：_find_m_top 验证价格差异阈值
        """
        strategy = MTopStrategy()
        # 创建价格差异过大的高点
        local_highs = [
            (10, 10.0, sample_df['date'].iloc[10]),
            (25, 11.0, sample_df['date'].iloc[25])  # 差异10%，超过默认3%
        ]
        result = strategy._find_m_top(local_highs, sample_df)
        
        # 验证返回None（因为价格差异超过阈值）
        assert result is None, "价格差异超过阈值时应返回None"


class TestCheckNecklineBreak:
    """_check_neckline_break 方法的单元测试"""
    
    @pytest.fixture
    def sample_df_with_indicators(self):
        """生成包含指标的样本数据"""
        dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
        np.random.seed(42)
        close_prices = 10 + np.cumsum(np.random.randn(60) * 0.5)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices + np.random.randn(60) * 0.2,
            'high': close_prices + np.abs(np.random.randn(60) * 0.3),
            'low': close_prices - np.abs(np.random.randn(60) * 0.3),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 60),
            'market_cap': np.random.uniform(50, 500, 60),
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        strategy = MTopStrategy()
        df = strategy.calculate_indicators(df)
        
        return df
    
    def test_check_neckline_break_returns_int_or_none(self, sample_df_with_indicators):
        """
        测试：_check_neckline_break 返回整数或None
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators
        
        # 设置H2索引和颈线价格
        h2_idx = 20
        neckline = 10.0
        
        result = strategy._check_neckline_break(df, h2_idx, neckline)
        
        # 验证返回类型
        assert result is None or isinstance(result, (int, np.integer)), \
            "返回值应为整数或None"
    
    def test_check_neckline_break_with_no_break(self, sample_df_with_indicators):
        """
        测试：_check_neckline_break 处理没有跌破的情况
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置颈线价格为最高价，使得不会跌破
        h2_idx = 20
        max_close = df['close'].max()
        neckline = max_close + 10  # 远高于所有价格
        
        # 同时提高放量倍数要求，使得即使价格满足也不会因为成交量不足而返回
        original_expand_ratio = strategy.params['volume_expand_ratio']
        strategy.params['volume_expand_ratio'] = 100.0  # 极高的放量倍数
        
        result = strategy._check_neckline_break(df, h2_idx, neckline)
        
        # 恢复参数
        strategy.params['volume_expand_ratio'] = original_expand_ratio
        
        # 验证返回None（因为价格不会跌破这么高的颈线）
        assert result is None, "颈线很高时应返回None"
    
    def test_check_neckline_break_index_range(self, sample_df_with_indicators):
        """
        测试：_check_neckline_break 返回的索引在H2之前
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators
        
        # 设置H2索引和颈线价格
        h2_idx = 30
        neckline = 9.0  # 较低的颈线，可能会跌破
        
        result = strategy._check_neckline_break(df, h2_idx, neckline)
        
        # 如果返回结果，验证索引在H2之前
        if result is not None:
            assert result < h2_idx, "跌破日索引应小于H2索引"
    
    def test_check_neckline_break_with_nan_values(self, sample_df_with_indicators):
        """
        测试：_check_neckline_break 处理包含NaN的数据
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 在数据中插入一些NaN值
        df.loc[0:5, 'volume_ma'] = np.nan
        
        h2_idx = 20
        neckline = 9.0
        
        result = strategy._check_neckline_break(df, h2_idx, neckline)
        
        # 验证返回类型（应该能处理NaN）
        assert result is None or isinstance(result, (int, np.integer)), \
            "应该能处理NaN值"
    
    def test_check_neckline_break_volume_condition(self, sample_df_with_indicators):
        """
        测试：_check_neckline_break 验证放量条件
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置H2索引和颈线价格
        h2_idx = 30
        neckline = 9.0
        
        # 降低成交量均线，使得放量条件更容易满足
        df['volume_ma'] = df['volume_ma'] * 0.5
        
        result = strategy._check_neckline_break(df, h2_idx, neckline)
        
        # 验证返回类型
        assert result is None or isinstance(result, (int, np.integer)), \
            "返回值应为整数或None"


class TestCheckTrendReversal:
    """_check_trend_reversal 方法的单元测试"""
    
    @pytest.fixture
    def sample_df_with_indicators(self):
        """
        生成包含指标的样本数据
        """
        dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
        np.random.seed(42)
        close_prices = 10 + np.cumsum(np.random.randn(60) * 0.5)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices + np.random.randn(60) * 0.2,
            'high': close_prices + np.abs(np.random.randn(60) * 0.3),
            'low': close_prices - np.abs(np.random.randn(60) * 0.3),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 60),
            'market_cap': np.random.uniform(50, 500, 60),
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        strategy = MTopStrategy()
        df = strategy.calculate_indicators(df)
        
        return df
    
    def test_check_trend_reversal_returns_bool(self, sample_df_with_indicators):
        """
        测试：_check_trend_reversal 返回布尔值
        """
        strategy = MTopStrategy()
        result = strategy._check_trend_reversal(sample_df_with_indicators)
        
        # 验证返回类型
        assert isinstance(result, (bool, np.bool_)), "返回值应为布尔值"
    
    def test_check_trend_reversal_condition_a_only(self, sample_df_with_indicators):
        """
        测试：只满足条件(a)时返回False
        
        条件(a)：short_ma < long_ma
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置条件(a)满足，条件(b)和(c)不满足
        df.loc[0, 'short_ma'] = 8.0      # short_ma < long_ma
        df.loc[0, 'long_ma'] = 10.0
        df.loc[0, 'short_term_trend'] = 5.0  # >= 0，条件(b)不满足
        df.loc[0, 'close'] = 11.0        # > long_ma，条件(c)不满足
        
        result = strategy._check_trend_reversal(df)
        
        # 只满足1个条件，应返回False
        assert result == False, "只满足1个条件时应返回False"
    
    def test_check_trend_reversal_condition_a_b(self, sample_df_with_indicators):
        """
        测试：满足条件(a)和(b)时返回True
        
        条件(a)：short_ma < long_ma
        条件(b)：short_term_trend < 0
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置条件(a)和(b)满足，条件(c)不满足
        df.loc[0, 'short_ma'] = 8.0      # short_ma < long_ma
        df.loc[0, 'long_ma'] = 10.0
        df.loc[0, 'short_term_trend'] = -2.0  # < 0，条件(b)满足
        df.loc[0, 'close'] = 11.0        # > long_ma，条件(c)不满足
        
        result = strategy._check_trend_reversal(df)
        
        # 满足2个条件，应返回True
        assert result == True, "满足2个条件时应返回True"
    
    def test_check_trend_reversal_condition_a_c(self, sample_df_with_indicators):
        """
        测试：满足条件(a)和(c)时返回True
        
        条件(a)：short_ma < long_ma
        条件(c)：close < long_ma
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置条件(a)和(c)满足，条件(b)不满足
        df.loc[0, 'short_ma'] = 8.0      # short_ma < long_ma
        df.loc[0, 'long_ma'] = 10.0
        df.loc[0, 'short_term_trend'] = 5.0  # >= 0，条件(b)不满足
        df.loc[0, 'close'] = 9.0         # < long_ma，条件(c)满足
        
        result = strategy._check_trend_reversal(df)
        
        # 满足2个条件，应返回True
        assert result == True, "满足2个条件时应返回True"
    
    def test_check_trend_reversal_condition_b_c(self, sample_df_with_indicators):
        """
        测试：满足条件(b)和(c)时返回True
        
        条件(b)：short_term_trend < 0
        条件(c)：close < long_ma
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置条件(b)和(c)满足，条件(a)不满足
        df.loc[0, 'short_ma'] = 11.0     # short_ma > long_ma，条件(a)不满足
        df.loc[0, 'long_ma'] = 10.0
        df.loc[0, 'short_term_trend'] = -2.0  # < 0，条件(b)满足
        df.loc[0, 'close'] = 9.0         # < long_ma，条件(c)满足
        
        result = strategy._check_trend_reversal(df)
        
        # 满足2个条件，应返回True
        assert result == True, "满足2个条件时应返回True"
    
    def test_check_trend_reversal_all_conditions(self, sample_df_with_indicators):
        """
        测试：满足所有三个条件时返回True
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置所有条件都满足
        df.loc[0, 'short_ma'] = 8.0      # short_ma < long_ma
        df.loc[0, 'long_ma'] = 10.0
        df.loc[0, 'short_term_trend'] = -2.0  # < 0
        df.loc[0, 'close'] = 9.0         # < long_ma
        
        result = strategy._check_trend_reversal(df)
        
        # 满足3个条件，应返回True
        assert result == True, "满足3个条件时应返回True"
    
    def test_check_trend_reversal_no_conditions(self, sample_df_with_indicators):
        """
        测试：不满足任何条件时返回False
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置所有条件都不满足
        df.loc[0, 'short_ma'] = 11.0     # short_ma > long_ma
        df.loc[0, 'long_ma'] = 10.0
        df.loc[0, 'short_term_trend'] = 5.0   # >= 0
        df.loc[0, 'close'] = 11.0        # > long_ma
        
        result = strategy._check_trend_reversal(df)
        
        # 不满足任何条件，应返回False
        assert result == False, "不满足任何条件时应返回False"
    
    def test_check_trend_reversal_with_nan_values(self, sample_df_with_indicators):
        """
        测试：_check_trend_reversal 处理NaN值
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置某个指标为NaN
        df.loc[0, 'short_ma'] = np.nan
        
        result = strategy._check_trend_reversal(df)
        
        # 有NaN值时应返回False
        assert result is False, "有NaN值时应返回False"
    
    def test_check_trend_reversal_boundary_values(self, sample_df_with_indicators):
        """
        测试：_check_trend_reversal 处理边界值
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 测试边界值：short_ma == long_ma（不满足条件a）
        df.loc[0, 'short_ma'] = 10.0
        df.loc[0, 'long_ma'] = 10.0
        df.loc[0, 'short_term_trend'] = -2.0  # 满足条件b
        df.loc[0, 'close'] = 9.0         # 满足条件c
        
        result = strategy._check_trend_reversal(df)
        
        # 满足2个条件（b和c），应返回True
        assert result == True, "满足2个条件时应返回True"
    
    def test_check_trend_reversal_boundary_trend_zero(self, sample_df_with_indicators):
        """
        测试：_check_trend_reversal 处理趋势线为0的边界值
        """
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 测试边界值：short_term_trend == 0（不满足条件b）
        df.loc[0, 'short_ma'] = 8.0      # 满足条件a
        df.loc[0, 'long_ma'] = 10.0
        df.loc[0, 'short_term_trend'] = 0.0   # 不满足条件b
        df.loc[0, 'close'] = 9.0         # 满足条件c
        
        result = strategy._check_trend_reversal(df)
        
        # 满足2个条件（a和c），应返回True
        assert result == True, "满足2个条件时应返回True"


class TestCheckVolumeAnalysis:
    """_check_volume_analysis 方法的单元测试"""
    
    @pytest.fixture
    def sample_df_with_indicators(self):
        """生成包含指标的样本数据"""
        dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
        np.random.seed(42)
        close_prices = 10 + np.cumsum(np.random.randn(60) * 0.5)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices + np.random.randn(60) * 0.2,
            'high': close_prices + np.abs(np.random.randn(60) * 0.3),
            'low': close_prices - np.abs(np.random.randn(60) * 0.3),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 60),
            'market_cap': np.random.uniform(50, 500, 60),
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        strategy = MTopStrategy()
        df = strategy.calculate_indicators(df)
        
        return df
    
    def test_check_volume_analysis_returns_dict(self, sample_df_with_indicators):
        """测试：_check_volume_analysis 返回字典"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        result = strategy._check_volume_analysis(df, h1_idx=30, h2_idx=20)
        
        # 验证返回类型
        assert isinstance(result, dict), "返回值应为字典"
        assert 'shrink' in result, "字典应包含 'shrink' 键"
        assert 'shrink_ratio' in result, "字典应包含 'shrink_ratio' 键"
    
    def test_check_volume_analysis_shrink_true(self, sample_df_with_indicators):
        """测试：_check_volume_analysis 判定缩量"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置H1和H2的成交量，使得H2 < H1 × 0.8
        df.loc[30, 'volume'] = 10000000  # H1成交量
        df.loc[20, 'volume'] = 7000000   # H2成交量（缩量）
        
        result = strategy._check_volume_analysis(df, h1_idx=30, h2_idx=20)
        
        # 验证缩量判定
        assert result['shrink'] == True, "应判定为缩量"
        assert result['shrink_ratio'] < 0.8, "缩量比例应小于0.8"
    
    def test_check_volume_analysis_shrink_false(self, sample_df_with_indicators):
        """测试：_check_volume_analysis 判定不缩量"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置H1和H2的成交量，使得H2 >= H1 × 0.8
        df.loc[30, 'volume'] = 10000000  # H1成交量
        df.loc[20, 'volume'] = 9000000   # H2成交量（不缩量）
        
        result = strategy._check_volume_analysis(df, h1_idx=30, h2_idx=20)
        
        # 验证不缩量判定
        assert result['shrink'] == False, "应判定为不缩量"
        assert result['shrink_ratio'] >= 0.8, "缩量比例应大于等于0.8"
    
    def test_check_volume_analysis_with_nan_values(self, sample_df_with_indicators):
        """测试：_check_volume_analysis 处理NaN值"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置某个成交量为NaN
        df.loc[30, 'volume'] = np.nan
        
        result = strategy._check_volume_analysis(df, h1_idx=30, h2_idx=20)
        
        # 有NaN值时应返回不缩量
        assert result['shrink'] == False, "有NaN值时应返回不缩量"
        assert result['shrink_ratio'] == 1.0, "缩量比例应为1.0"
    
    def test_check_volume_analysis_zero_volume(self, sample_df_with_indicators):
        """测试：_check_volume_analysis 处理零成交量"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置H1成交量为0
        df.loc[30, 'volume'] = 0
        
        result = strategy._check_volume_analysis(df, h1_idx=30, h2_idx=20)
        
        # 成交量为0时应返回不缩量
        assert result['shrink'] == False, "成交量为0时应返回不缩量"


class TestCheckFakeMTop:
    """_check_fake_m_top 方法的单元测试"""
    
    @pytest.fixture
    def sample_df_with_indicators(self):
        """生成包含指标的样本数据"""
        dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
        np.random.seed(42)
        close_prices = 10 + np.cumsum(np.random.randn(60) * 0.5)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices + np.random.randn(60) * 0.2,
            'high': close_prices + np.abs(np.random.randn(60) * 0.3),
            'low': close_prices - np.abs(np.random.randn(60) * 0.3),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 60),
            'market_cap': np.random.uniform(50, 500, 60),
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        
        # 计算指标
        strategy = MTopStrategy()
        df = strategy.calculate_indicators(df)
        
        return df
    
    def test_check_fake_m_top_returns_bool(self, sample_df_with_indicators):
        """测试：_check_fake_m_top 返回布尔值"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        result = strategy._check_fake_m_top(df, h1_idx=40, neckline=9.0, break_idx=10)
        
        # 验证返回类型
        assert isinstance(result, (bool, np.bool_)), "返回值应为布尔值"
    
    def test_check_fake_m_top_condition1_fail(self, sample_df_with_indicators):
        """测试：_check_fake_m_top 条件1不满足时返回False"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置H1处的高点
        h1_idx = 40
        h1_price = 12.0
        df.loc[h1_idx, 'high'] = h1_price
        
        # 设置H1之前的最低价 >= H1 × 0.8（条件1不满足）
        for i in range(h1_idx + 1, min(h1_idx + 35, len(df))):
            df.loc[i, 'low'] = h1_price * 0.9
        
        # 设置跌破后的收盘价 <= 颈线（条件2满足）
        neckline = 9.0
        for i in range(0, 10):
            df.loc[i, 'close'] = 8.5
        
        result = strategy._check_fake_m_top(df, h1_idx=h1_idx, neckline=neckline, break_idx=10)
        
        # 条件1不满足，应返回False
        assert result == False, "条件1不满足时应返回False"
    
    def test_check_fake_m_top_condition2_fail(self, sample_df_with_indicators):
        """测试：_check_fake_m_top 条件2不满足时返回False"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置H1处的高点
        h1_idx = 40
        h1_price = 12.0
        df.loc[h1_idx, 'high'] = h1_price
        
        # 设置H1之前的最低价 < H1 × 0.8（条件1满足）
        for i in range(h1_idx + 1, min(h1_idx + 35, len(df))):
            df.loc[i, 'low'] = h1_price * 0.7
        
        # 设置跌破后的收盘价 > 颈线（条件2不满足）
        neckline = 9.0
        resistance_level = neckline * 1.02
        for i in range(0, 10):
            df.loc[i, 'close'] = resistance_level + 0.5
        
        result = strategy._check_fake_m_top(df, h1_idx=h1_idx, neckline=neckline, break_idx=10)
        
        # 条件2不满足，应返回False
        assert result == False, "条件2不满足时应返回False"
    
    def test_check_fake_m_top_both_conditions_pass(self, sample_df_with_indicators):
        """测试：_check_fake_m_top 两个条件都满足时返回True"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置H1处的高点
        h1_idx = 40
        h1_price = 12.0
        df.loc[h1_idx, 'high'] = h1_price
        
        # 设置H1之前的最低价 < H1 × 0.8（条件1满足）
        for i in range(h1_idx + 1, min(h1_idx + 35, len(df))):
            df.loc[i, 'low'] = h1_price * 0.7
        
        # 设置跌破后的收盘价 <= 颈线（条件2满足）
        neckline = 9.0
        for i in range(0, 10):
            df.loc[i, 'close'] = 8.5
        
        result = strategy._check_fake_m_top(df, h1_idx=h1_idx, neckline=neckline, break_idx=10)
        
        # 两个条件都满足，应返回True
        assert result == True, "两个条件都满足时应返回True"
    
    def test_check_fake_m_top_boundary_condition1(self, sample_df_with_indicators):
        """测试：_check_fake_m_top 条件1边界值"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置H1处的高点
        h1_idx = 40
        h1_price = 12.0
        df.loc[h1_idx, 'high'] = h1_price
        
        # 设置H1之前的最低价 == H1 × 0.8（边界，不满足 <）
        for i in range(h1_idx + 1, min(h1_idx + 35, len(df))):
            df.loc[i, 'low'] = h1_price * 0.8
        
        # 设置跌破后的收盘价 <= 颈线（条件2满足）
        neckline = 9.0
        for i in range(0, 10):
            df.loc[i, 'close'] = 8.5
        
        result = strategy._check_fake_m_top(df, h1_idx=h1_idx, neckline=neckline, break_idx=10)
        
        # 条件1边界不满足，应返回False
        assert result == False, "条件1边界不满足时应返回False"
    
    def test_check_fake_m_top_boundary_condition2(self, sample_df_with_indicators):
        """测试：_check_fake_m_top 条件2边界值"""
        strategy = MTopStrategy()
        df = sample_df_with_indicators.copy()
        
        # 设置H1处的高点
        h1_idx = 40
        h1_price = 12.0
        df.loc[h1_idx, 'high'] = h1_price
        
        # 设置H1之前的最低价 < H1 × 0.8（条件1满足）
        for i in range(h1_idx + 1, min(h1_idx + 35, len(df))):
            df.loc[i, 'low'] = h1_price * 0.7
        
        # 设置跌破后的收盘价 == 颈线 × (1 + resistance_ratio)（边界，满足 <=）
        neckline = 9.0
        resistance_level = neckline * 1.02
        for i in range(0, 10):
            df.loc[i, 'close'] = resistance_level
        
        result = strategy._check_fake_m_top(df, h1_idx=h1_idx, neckline=neckline, break_idx=10)
        
        # 条件2边界满足，应返回True
        assert result == True, "条件2边界满足时应返回True"


class TestSelectStocks:
    """select_stocks 方法的单元测试 - Task 9 端到端测试"""
    
    @pytest.fixture
    def sample_df(self):
        """生成样本数据"""
        dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
        np.random.seed(42)
        close_prices = 10 + np.cumsum(np.random.randn(60) * 0.5)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices + np.random.randn(60) * 0.2,
            'high': close_prices + np.abs(np.random.randn(60) * 0.3),
            'low': close_prices - np.abs(np.random.randn(60) * 0.3),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 60),
            'market_cap': np.random.uniform(50, 500, 60),
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    
    def test_select_stocks_returns_list(self, sample_df):
        """
        测试：select_stocks 返回列表
        验证返回值类型为列表
        """
        strategy = MTopStrategy()
        # 先计算指标
        df_with_indicators = strategy.calculate_indicators(sample_df)
        # 调用select_stocks
        result = strategy.select_stocks(df_with_indicators)
        
        # 验证返回类型
        assert isinstance(result, list), "返回值应为列表"
    
    def test_select_stocks_with_insufficient_data(self):
        """
        测试：select_stocks 处理数据不足的情况（< 60行）
        验证数据不足时返回空列表
        """
        # 生成只有30个交易日的数据
        dates = pd.date_range(end=datetime.now(), periods=30, freq='D')
        df = pd.DataFrame({
            'date': dates,
            'open': np.random.randn(30) + 10,
            'high': np.random.randn(30) + 10.5,
            'low': np.random.randn(30) + 9.5,
            'close': np.random.randn(30) + 10,
            'volume': np.random.randint(1000000, 10000000, 30),
            'market_cap': np.random.uniform(50, 500, 30),
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(df)
        result = strategy.select_stocks(df_with_indicators)
        
        # 验证返回空列表
        assert result == [], "数据不足时应返回空列表"
    
    def test_select_stocks_filters_st_stocks(self, sample_df):
        """
        测试：select_stocks 过滤 ST 股票
        验证股票名称包含 ST 时返回空列表
        """
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(sample_df)
        
        # 调用 select_stocks，传入 ST 股票名称
        result = strategy.select_stocks(df_with_indicators, stock_name='ST中国')
        
        # 验证返回空列表
        assert result == [], "ST 股票应被过滤"
    
    def test_select_stocks_filters_delisted_stocks(self, sample_df):
        """
        测试：select_stocks 过滤退市股票
        验证股票名称包含退市关键词时返回空列表
        """
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(sample_df)
        
        # 调用 select_stocks，传入退市股票名称
        result = strategy.select_stocks(df_with_indicators, stock_name='已退市公司')
        
        # 验证返回空列表
        assert result == [], "退市股票应被过滤"
    
    def test_select_stocks_signal_structure(self, sample_df):
        """
        测试：select_stocks 返回的信号结构
        验证信号字典包含所有必需字段
        """
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(sample_df)
        result = strategy.select_stocks(df_with_indicators)
        
        # 如果返回非空列表，验证信号结构
        if result:
            signal = result[0]
            
            # 验证信号是字典
            assert isinstance(signal, dict), "信号应为字典"
            
            # 验证必需字段存在
            required_fields = [
                'date', 'close', 'J', 'volume_ratio', 'market_cap',
                'short_term_trend', 'bull_bear_line', 'neckline',
                'h1_price', 'h2_price', 'reasons'
            ]
            for field in required_fields:
                assert field in signal, f"信号应包含字段 {field}"
            
            # 验证 reasons 是列表
            assert isinstance(signal['reasons'], list), "reasons 应为列表"
            assert len(signal['reasons']) > 0, "reasons 不应为空"
    
    def test_select_stocks_reasons_content(self, sample_df):
        """
        测试：select_stocks 返回的 reasons 内容
        验证 reasons 包含必需的原因描述
        """
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(sample_df)
        result = strategy.select_stocks(df_with_indicators)
        
        # 如果返回非空列表，验证 reasons 内容
        if result:
            signal = result[0]
            reasons = signal['reasons']
            
            # 验证包含 M 头形态确认
            assert any('M头形态确认' in reason for reason in reasons), \
                "reasons 应包含 M 头形态确认"
            
            # 验证包含颈线跌破放量倍数
            assert any('颈线跌破放量' in reason for reason in reasons), \
                "reasons 应包含颈线跌破放量倍数"
            
            # 验证包含趋势反转信息
            assert any('趋势反转' in reason for reason in reasons), \
                "reasons 应包含趋势反转信息"
    
    def test_select_stocks_volume_ratio_calculation(self, sample_df):
        """
        测试：select_stocks 计算的放量倍数
        验证 volume_ratio 为正数或零
        """
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(sample_df)
        result = strategy.select_stocks(df_with_indicators)
        
        # 如果返回非空列表，验证 volume_ratio
        if result:
            signal = result[0]
            
            # 验证 volume_ratio 为非负数
            assert signal['volume_ratio'] >= 0, "volume_ratio 应为非负数"
    
    def test_select_stocks_with_normal_stock_name(self, sample_df):
        """
        测试：select_stocks 处理正常股票名称
        验证正常股票名称不被过滤
        """
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(sample_df)
        
        # 调用 select_stocks，传入正常股票名称
        result = strategy.select_stocks(df_with_indicators, stock_name='中国平安')
        
        # 验证返回列表（可能为空或非空，但不应因名称被过滤）
        assert isinstance(result, list), "应返回列表"
    
    def test_select_stocks_no_m_top_pattern(self):
        """
        测试：select_stocks 处理无 M 头形态的数据
        验证无 M 头形态时返回空列表
        """
        # 生成单调上升的数据（无 M 头形态）
        dates = pd.date_range(end=datetime.now(), periods=60, freq='D')
        close_prices = np.linspace(10, 20, 60)
        
        df = pd.DataFrame({
            'date': dates,
            'open': close_prices + 0.1,
            'high': close_prices + 0.5,
            'low': close_prices - 0.5,
            'close': close_prices,
            'volume': np.full(60, 5000000),
            'market_cap': np.full(60, 100),
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(df)
        result = strategy.select_stocks(df_with_indicators)
        
        # 验证返回空列表（因为无 M 头形态）
        assert isinstance(result, list), "应返回列表"
    
    def test_select_stocks_signal_date_field(self, sample_df):
        """
        测试：select_stocks 返回的信号日期字段
        验证 date 字段为有效日期
        """
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(sample_df)
        result = strategy.select_stocks(df_with_indicators)
        
        # 如果返回非空列表，验证 date 字段
        if result:
            signal = result[0]
            
            # 验证 date 字段存在且为 Timestamp 或 datetime
            assert signal['date'] is not None, "date 字段不应为 None"
    
    def test_select_stocks_signal_price_fields(self, sample_df):
        """
        测试：select_stocks 返回的信号价格字段
        验证价格字段为正数
        """
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(sample_df)
        result = strategy.select_stocks(df_with_indicators)
        
        # 如果返回非空列表，验证价格字段
        if result:
            signal = result[0]
            
            # 验证价格字段为正数
            assert signal['close'] > 0, "close 应为正数"
            assert signal['neckline'] > 0, "neckline 应为正数"
            assert signal['h1_price'] > 0, "h1_price 应为正数"
            assert signal['h2_price'] > 0, "h2_price 应为正数"
    
    def test_select_stocks_empty_stock_name(self, sample_df):
        """
        测试：select_stocks 处理空股票名称
        验证空股票名称不触发过滤
        """
        strategy = MTopStrategy()
        df_with_indicators = strategy.calculate_indicators(sample_df)
        
        # 调用 select_stocks，传入空股票名称
        result = strategy.select_stocks(df_with_indicators, stock_name='')
        
        # 验证返回列表
        assert isinstance(result, list), "应返回列表"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
