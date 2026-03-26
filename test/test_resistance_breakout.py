"""
测试阻力位突破策略

测试用例覆盖：
- 指标计算、数据验证
- 突破日搜索（含涨幅+放量+阻力位三合一检查）
- 回踩检查、趋势配合
- 选股信号生成、原因生成、边界情况
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from strategy.resistance_breakout import ResistanceBreakoutStrategy


def _build_breakout_data(n=80, resistance=15.0, breakout_open=13.5,
                         breakout_close=15.0, post_days=3,
                         base_volume=1000000):
    """
    构造确定性的阻力位突破测试数据（正序，最新在后）

    参数说明：
    - resistance: 阻力位（前60日最高价）
    - breakout_open: 突破日开盘价（默认13.5）
    - breakout_close: 突破日收盘价（默认15.0）
      默认涨幅 = (15.0 - 13.5) / 13.5 = 11.1% > 8%
    - post_days: 突破后天数
    """
    dates = pd.bdate_range(end=datetime.now(), periods=n)
    # 震荡期天数
    pre_days = n - post_days - 1
    # 震荡期：价格在阻力位下方
    close_pre = np.full(pre_days, 13.0)
    high_pre = np.full(pre_days, 13.3)
    low_pre = np.full(pre_days, 12.7)
    open_pre = np.full(pre_days, 13.0)
    vol_pre = np.full(pre_days, base_volume, dtype=int)
    # 在突破日之前60日范围内设置阻力位高点
    high_pre[-30] = resistance

    # 突破日（1天）：放量长阳突破
    breakout_day_vol = int(base_volume * 2.5)

    # 突破后期
    if post_days > 0:
        post_closes = np.linspace(breakout_close, breakout_close + 0.3, post_days)
        post_highs = post_closes + 0.2
        # 最低价不跌破突破日开盘价
        post_lows = np.maximum(post_closes - 0.3, breakout_open + 0.01)
        post_opens = (post_highs + post_lows) / 2
        post_vols = np.full(post_days, base_volume, dtype=int)
    else:
        post_closes = np.array([])
        post_highs = np.array([])
        post_lows = np.array([])
        post_opens = np.array([])
        post_vols = np.array([], dtype=int)

    # 合并数据
    close_all = np.concatenate([close_pre, [breakout_close], post_closes])
    high_all = np.concatenate([high_pre, [breakout_close + 0.2], post_highs])
    low_all = np.concatenate([low_pre, [breakout_open - 0.1], post_lows])
    open_all = np.concatenate([open_pre, [breakout_open], post_opens])
    vol_all = np.concatenate([vol_pre, [breakout_day_vol], post_vols])

    df = pd.DataFrame({
        'date': dates, 'open': open_all, 'high': high_all,
        'low': low_all, 'close': close_all, 'volume': vol_all.astype(int),
    })
    return df


@pytest.fixture
def breakout_data():
    """构造满足所有条件的突破数据
    breakout_open=13.5, breakout_close=15.0 -> 涨幅11.1% > 8%
    resistance=15.0, close=15.0 >= 15.0*0.98=14.7 -> 达到阻力位
    放量2.5倍 > 2.0倍
    """
    return _build_breakout_data(
        n=80, resistance=15.0, breakout_open=13.5,
        breakout_close=15.0, post_days=3, base_volume=1000000
    )


@pytest.fixture
def strategy():
    """创建阻力位突破策略实例"""
    return ResistanceBreakoutStrategy()


# ========== 指标计算测试 ==========
def test_calculate_indicators(strategy, breakout_data):
    """测试指标计算功能"""
    df = strategy.calculate_indicators(breakout_data)
    assert 'resistance_level' in df.columns
    assert 'volume_ma' in df.columns
    assert 'volume_ratio' in df.columns
    assert 'breakout_ratio' in df.columns
    assert 'short_term_trend' in df.columns
    assert 'bull_bear_line' in df.columns
    assert not df['resistance_level'].isna().all()
    assert not df['volume_ma'].isna().all()


# ========== 数据验证测试 ==========
def test_validate_data(strategy, breakout_data):
    """测试数据验证功能"""
    assert strategy._validate_data(breakout_data) is True
    assert strategy._validate_data(pd.DataFrame()) is False
    assert strategy._validate_data(breakout_data.head(20)) is False
    missing_df = breakout_data.drop('volume', axis=1)
    assert strategy._validate_data(missing_df) is False


# ========== 突破日搜索测试 ==========
def test_find_breakout_day_pass(strategy, breakout_data):
    """测试突破日搜索 - 能找到突破日（涨幅11.1%、达阻力位、放量2.5倍）"""
    df = strategy.calculate_indicators(breakout_data)
    pos = strategy._find_breakout_day(df)
    assert pos is not None
    assert pos == len(df) - 4


def test_find_breakout_day_fail_low_change(strategy):
    """测试突破日搜索 - 涨幅不足（7.1% < 8%）
    前一日收盘=14.0（震荡期），突破日收盘=15.0
    涨幅 = (15.0-14.0)/14.0 = 7.1% < 8%
    """
    df = _build_breakout_data(
        resistance=15.0, breakout_open=14.5, breakout_close=15.0
    )
    # 将震荡期收盘价改为14.0，使前一日收盘→突破日收盘涨幅不足8%
    breakout_idx = len(df) - 4  # 突破日位置（post_days=3）
    for i in range(breakout_idx):
        df.loc[df.index[i], 'close'] = 14.0
        df.loc[df.index[i], 'high'] = 14.3
        df.loc[df.index[i], 'low'] = 13.7
        df.loc[df.index[i], 'open'] = 14.0
    # 保持阻力位高点
    df.loc[df.index[breakout_idx - 30], 'high'] = 15.0
    df = strategy.calculate_indicators(df)
    pos = strategy._find_breakout_day(df)
    assert pos is None


def test_find_breakout_day_fail_low_price(strategy):
    """测试突破日搜索 - 收盘价远低于阻力位（未达98%阈值）"""
    # 阻力位=20.0，突破日收盘=15.0，15.0 < 20.0*0.98=19.6，未达阻力位
    # 突破日涨幅 = (15.0-13.5)/13.5 = 11.1% > 8%，放量2.5倍
    df = _build_breakout_data(
        resistance=20.0, breakout_open=13.5, breakout_close=15.0
    )
    df = strategy.calculate_indicators(df)
    pos = strategy._find_breakout_day(df)
    # 15.0 < 20.0*0.98=19.6，未达阻力位，应返回None
    assert pos is None


def test_find_breakout_day_fail_low_volume(strategy):
    """测试突破日搜索 - 成交量不足"""
    df = _build_breakout_data(
        resistance=15.0, breakout_open=13.5, breakout_close=15.0
    )
    # 手动把突破日成交量改为正常量（不放量）
    breakout_idx = len(df) - 4
    df.loc[df.index[breakout_idx], 'volume'] = 1000000
    df = strategy.calculate_indicators(df)
    pos = strategy._find_breakout_day(df)
    assert pos is None


def test_find_breakout_day_today(strategy):
    """测试突破日搜索 - 今天就是突破日"""
    df = _build_breakout_data(
        n=80, resistance=15.0, breakout_open=13.5,
        breakout_close=15.0, post_days=0
    )
    df = strategy.calculate_indicators(df)
    pos = strategy._find_breakout_day(df)
    assert pos is not None
    assert pos == len(df) - 1


# ========== 回踩检查测试 ==========
def test_check_pullback_pass(strategy, breakout_data):
    """测试回踩检查 - 满足条件（突破后不跌破突破日开盘价13.5）"""
    df = strategy.calculate_indicators(breakout_data)
    pos = strategy._find_breakout_day(df)
    assert pos is not None
    assert strategy._check_pullback(df, pos) is True


def test_check_pullback_fail(strategy):
    """测试回踩检查 - 不满足条件（某天最低价跌破突破日开盘价13.5）"""
    df = _build_breakout_data(
        resistance=15.0, breakout_open=13.5, breakout_close=15.0
    )
    # 让突破后某天最低价跌破突破日开盘价13.5
    df.loc[df.index[-2], 'low'] = 12.0
    df = strategy.calculate_indicators(df)
    pos = strategy._find_breakout_day(df)
    assert pos is not None
    assert strategy._check_pullback(df, pos) is False


def test_check_pullback_today_breakout(strategy):
    """测试回踩检查 - 今天就是突破日，无需检查回踩"""
    df = _build_breakout_data(
        n=80, resistance=15.0, breakout_open=13.5,
        breakout_close=15.0, post_days=0
    )
    df = strategy.calculate_indicators(df)
    pos = strategy._find_breakout_day(df)
    assert pos is not None
    assert strategy._check_pullback(df, pos) is True


# ========== 趋势配合测试 ==========
def test_check_trend_pass(strategy):
    """测试趋势配合 - 满足条件（趋势线向上）"""
    n = 80
    dates = pd.bdate_range(end=datetime.now(), periods=n)
    close = np.linspace(10.0, 16.0, n)
    high = close + 0.3
    low = close - 0.3
    open_price = (high + low) / 2
    volume = np.full(n, 1000000)
    df = pd.DataFrame({
        'date': dates, 'open': open_price, 'high': high,
        'low': low, 'close': close, 'volume': volume,
    })
    df = strategy.calculate_indicators(df)
    assert strategy._check_trend(df) is True


def test_check_trend_fail(strategy):
    """测试趋势配合 - 不满足条件（趋势线向下）"""
    n = 80
    dates = pd.bdate_range(end=datetime.now(), periods=n)
    close = np.linspace(16.0, 10.0, n)
    high = close + 0.3
    low = close - 0.3
    open_price = (high + low) / 2
    volume = np.full(n, 1000000)
    df = pd.DataFrame({
        'date': dates, 'open': open_price, 'high': high,
        'low': low, 'close': close, 'volume': volume,
    })
    df = strategy.calculate_indicators(df)
    assert strategy._check_trend(df) is False


# ========== 选股功能测试 ==========
def test_select_stocks_signal_structure(strategy, breakout_data):
    """测试选股信号结构完整性"""
    signals = strategy.select_stocks(breakout_data, '测试股票')
    if len(signals) > 0:
        signal = signals[0]
        required_keys = [
            'date', 'close', 'resistance_level', 'breakout_ratio',
            'volume', 'volume_ma', 'volume_ratio',
            'short_term_trend', 'reasons',
            'pattern_details', 'breakout_date', 'days_since_breakout'
        ]
        for key in required_keys:
            assert key in signal, f'信号缺少字段: {key}'


# ========== 原因生成测试 ==========
def test_generate_reasons(strategy, breakout_data):
    """测试生成选股原因功能"""
    df = strategy.calculate_indicators(breakout_data)
    pos = strategy._find_breakout_day(df)
    assert pos is not None
    reasons = strategy._generate_reasons(df, pos)
    assert len(reasons) > 0
    reasons_text = ' '.join(reasons)
    # 应包含长阳、回踩/突破、趋势相关原因
    assert '长阳' in reasons_text
    assert '回踩' in reasons_text or '突破' in reasons_text
    assert '趋势' in reasons_text


# ========== 边界情况测试 ==========
def test_filter_st_stocks(strategy, breakout_data):
    """测试ST股票过滤"""
    assert len(strategy.select_stocks(breakout_data, 'ST测试')) == 0
    assert len(strategy.select_stocks(breakout_data, '*ST测试')) == 0


def test_filter_delisted_stocks(strategy, breakout_data):
    """测试退市股票过滤"""
    assert len(strategy.select_stocks(breakout_data, '测试退')) == 0
    assert len(strategy.select_stocks(breakout_data, '退市股票')) == 0


def test_filter_small_market_cap(strategy, breakout_data):
    """测试市值过小过滤"""
    small_cap = breakout_data.copy()
    small_cap['market_cap'] = 10e8  # 10亿 < 20亿
    assert len(strategy.select_stocks(small_cap, '小市值')) == 0


def test_filter_large_market_cap(strategy, breakout_data):
    """测试市值过大过滤"""
    large_cap = breakout_data.copy()
    large_cap['market_cap'] = 1500e8  # 1500亿 > 1000亿
    assert len(strategy.select_stocks(large_cap, '大市值')) == 0


if __name__ == '__main__':
    pytest.main(['-v', __file__])
