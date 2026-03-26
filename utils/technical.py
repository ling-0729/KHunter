"""
技术指标计算模块 - 通达信公式函数实现
"""
import pandas as pd
import numpy as np


def MA(series, n):
    """
    简单移动平均 - 正确处理倒序排列的数据
    
    对于倒序数据，MA(n)应该取当前及之后n-1个数据的平均值
    实现方式：反转数据 -> 计算rolling -> 反转回来
    """
    # 反转数据，使数据按时间正序排列
    reversed_series = series.iloc[::-1]
    
    # 在正序数据上计算MA（向前看n个值）
    ma_reversed = reversed_series.rolling(window=n, min_periods=1).mean()
    
    # 反转回来，恢复倒序
    return ma_reversed.iloc[::-1].reset_index(drop=True).set_axis(series.index)


def EMA(series, n):
    """
    指数移动平均 - 正确处理倒序排列的数据
    """
    reversed_series = series.iloc[::-1]
    ema_reversed = reversed_series.ewm(span=n, adjust=False, min_periods=1).mean()
    return ema_reversed.iloc[::-1].reset_index(drop=True).set_axis(series.index)


def LLV(series, n):
    """
    N周期最低值 - 正确处理倒序排列的数据
    """
    reversed_series = series.iloc[::-1]
    llv_reversed = reversed_series.rolling(window=n, min_periods=1).min()
    return llv_reversed.iloc[::-1].reset_index(drop=True).set_axis(series.index)


def HHV(series, n):
    """
    N周期最高值 - 正确处理倒序排列的数据
    """
    reversed_series = series.iloc[::-1]
    hhv_reversed = reversed_series.rolling(window=n, min_periods=1).max()
    return hhv_reversed.iloc[::-1].reset_index(drop=True).set_axis(series.index)


def SMA(X, n, m):
    """
    移动平均 - 通达信风格
    SMA(X,N,M): X的N日移动平均, M为权重
    公式: Y = (X*M + Y'*(N-M)) / N
    """
    result = pd.Series(index=X.index, dtype=float)
    result.iloc[0] = X.iloc[0]
    for i in range(1, len(X)):
        result.iloc[i] = (X.iloc[i] * m + result.iloc[i-1] * (n - m)) / n
    return result


def REF(series, n):
    """
    向前引用N周期 - 正确处理倒序排列的数据
    
    对于倒序数据（最新在前），REF(series, 1)应该获取"前一天"的数据
    实现方式：反转数据 -> shift -> 反转回来
    """
    reversed_series = series.iloc[::-1]
    ref_reversed = reversed_series.shift(n)
    return ref_reversed.iloc[::-1].reset_index(drop=True).set_axis(series.index)


def EXIST(cond, n):
    """
    N周期内是否存在满足COND的情况 - 正确处理倒序排列的数据
    """
    reversed_cond = cond.iloc[::-1]
    exist_reversed = reversed_cond.rolling(window=n, min_periods=1).max().astype(bool)
    return exist_reversed.iloc[::-1].reset_index(drop=True).set_axis(cond.index)


def FINANCE(df, field_code):
    """
    财务数据获取
    39: 总市值（注意：原通达信39是流通市值，本项目使用总市值）
    """
    if field_code == 39:
        return df.get('market_cap', pd.Series([0] * len(df), index=df.index))
    return pd.Series([0] * len(df), index=df.index)


def KDJ(df, n=9, m1=3, m2=3):
    """
    KDJ指标计算 - 标准实现
    通达信公式：
    RSV = (CLOSE - LLV(LOW,N)) / (HHV(HIGH,N) - LLV(LOW,N)) * 100
    K = SMA(RSV,M1,1)
    D = SMA(K,M2,1)
    J = 3*K - 2*D
    
    注意：数据可能是倒序（最新在前）或正序，需要自动检测并处理
    """
    # 检测数据顺序
    is_descending = df['date'].iloc[0] > df['date'].iloc[-1]
    
    # 统一转换为正序计算（从早到晚）
    if is_descending:
        df_calc = df.iloc[::-1].copy().reset_index(drop=True)
    else:
        df_calc = df.copy().reset_index(drop=True)
    
    # 计算RSV
    low_min = df_calc['low'].rolling(window=n, min_periods=1).min()
    high_max = df_calc['high'].rolling(window=n, min_periods=1).max()
    
    range_val = high_max - low_min
    rsv = pd.Series(index=df_calc.index, dtype=float)
    
    # RSV计算，前n-1个周期不足时用50填充
    for i in range(len(df_calc)):
        if i < n - 1 or range_val.iloc[i] == 0:
            rsv.iloc[i] = 50.0
        else:
            rsv.iloc[i] = (df_calc['close'].iloc[i] - low_min.iloc[i]) / range_val.iloc[i] * 100
    
    # SMA计算 - 通达信风格
    # K = SMA(RSV, M1, 1): K = (RSV*1 + K'*(M1-1)) / M1
    k = pd.Series(index=df_calc.index, dtype=float)
    d = pd.Series(index=df_calc.index, dtype=float)
    
    # 初始化第一日K、D值为50
    k.iloc[0] = 50.0
    d.iloc[0] = 50.0
    
    # 递归计算
    for i in range(1, len(df_calc)):
        k.iloc[i] = (rsv.iloc[i] * 1 + k.iloc[i-1] * (m1 - 1)) / m1
        d.iloc[i] = (k.iloc[i] * 1 + d.iloc[i-1] * (m2 - 1)) / m2
    
    # 计算J值
    j = 3 * k - 2 * d
    
    # 构建结果
    result = pd.DataFrame({
        'K': k,
        'D': d,
        'J': j
    })
    
    # 恢复原始顺序
    if is_descending:
        result = result.iloc[::-1].reset_index(drop=True)
    
    result.index = df.index
    return result


def calculate_zhixing_trend(df, m1=14, m2=28, m3=57, m4=114):
    """
    计算知行趋势线指标
    
    指标定义:
    - 知行短期趋势线 = EMA(EMA(CLOSE,10),10)
      对收盘价连续做两次10日指数移动平均
    
    - 知行多空线 = (MA(CLOSE,m1) + MA(CLOSE,m2) + MA(CLOSE,m3) + MA(CLOSE,m4)) / 4
      四条均线平均值，默认使用 14, 28, 57, 114
    
    参数:
        m1, m2, m3, m4: 多空线计算用的MA周期，默认14, 28, 57, 114
    """
    # 知行短期趋势线 = EMA(EMA(CLOSE,10),10)
    short_term_trend = EMA(EMA(df['close'], 10), 10)
    
    # 知行多空线 = (MA(m1) + MA(m2) + MA(m3) + MA(m4)) / 4
    bull_bear_line = (MA(df['close'], m1) + MA(df['close'], m2) + 
                      MA(df['close'], m3) + MA(df['close'], m4)) / 4
    
    return pd.DataFrame({
        'short_term_trend': short_term_trend,
        'bull_bear_line': bull_bear_line
    }, index=df.index)
