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
    
    # 反转回来，恢复倒序，保持原始索引
    return ma_reversed.iloc[::-1]


def EMA(series, n):
    """
    指数移动平均 - 正确处理倒序排列的数据
    """
    reversed_series = series.iloc[::-1]
    ema_reversed = reversed_series.ewm(span=n, adjust=False, min_periods=1).mean()
    return ema_reversed.iloc[::-1]


def LLV(series, n):
    """
    N周期最低值 - 正确处理倒序排列的数据
    """
    reversed_series = series.iloc[::-1]
    llv_reversed = reversed_series.rolling(window=n, min_periods=1).min()
    return llv_reversed.iloc[::-1]


def HHV(series, n):
    """
    N周期最高值 - 正确处理倒序排列的数据
    """
    reversed_series = series.iloc[::-1]
    hhv_reversed = reversed_series.rolling(window=n, min_periods=1).max()
    return hhv_reversed.iloc[::-1]


def SMA(X, n, m):
    """
    移动平均 - 通达信风格
    SMA(X,N,M): X的N日移动平均, M为权重
    公式: Y = (X*M + Y'*(N-M)) / N

    ★【2026-09-29 性能优化 ✓】**逐位等价**改写 ✗→✓

    实测 ✗✓（临时剖析 ✓）：原实现用 **pandas 标量 `.iloc` 递推** ✗ —— 每次读写都走
    `indexing._setitem_with_indexer` ✗ ⇒ 个股 ADX 全量重算（240 次调用 / 25.5 万次
    下标 ✓）里**约 100% 的耗时**都落在本函数 ✗：
    **500 只 191s** ✗ ⇒ 5193 只 ≈ **33 分钟** ✗✓（用户实测 ✓）。

    现改为**纯 Python 标量递推** ✓（取值用 `to_numpy().tolist()` ✓ = 同一批 float64 ✓）：
      · **递推式、运算顺序、初值完全不变** ✓ ⇒ 结果**逐位相同** ✓（测试锁死 ✓）；
      · **NaN 语义不变** ✓（NaN 参与递推继续传播 ✓ ⇒ "一次 NaN 永远 NaN" ✓，
        首位 NaN ⇒ 整体 NaN ✓ —— 与原实现一致 ✓）；
      · 仍返回 **`pd.Series`** ✓（`index` 与入参对齐 ✓）⇒ 调用方
        （`.replace(0,nan)` / `.fillna(0)` / `.abs()` ✓）**零改动** ✓。
    """
    vals = (X.to_numpy(dtype='float64').tolist()
            if hasattr(X, 'to_numpy') else [float(v) for v in X])
    size = len(vals)
    index = getattr(X, 'index', None)
    if size == 0:
        return pd.Series(index=index, dtype=float)
    out = [0.0] * size
    out[0] = vals[0]
    for i in range(1, size):
        out[i] = (vals[i] * m + out[i - 1] * (n - m)) / n
    return pd.Series(out, index=index, dtype='float64')


def REF(series, n):
    """
    向前引用N周期 - 正确处理倒序排列的数据
    
    对于倒序数据（最新在前），REF(series, 1)应该获取"前一天"的数据
    实现方式：反转数据 -> shift -> 反转回来
    """
    reversed_series = series.iloc[::-1]
    ref_reversed = reversed_series.shift(n)
    return ref_reversed.iloc[::-1]


def EXIST(cond, n):
    """
    N周期内是否存在满足COND的情况 - 正确处理倒序排列的数据
    """
    reversed_cond = cond.iloc[::-1]
    exist_reversed = reversed_cond.rolling(window=n, min_periods=1).max().astype(bool)
    return exist_reversed.iloc[::-1]


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
    # 检查数据是否为空
    if df is None or df.empty:
        return pd.DataFrame({'K': [], 'D': [], 'J': []}, index=df.index if df is not None else [])
    
    # 检测数据顺序
    try:
        is_descending = df['date'].iloc[0] > df['date'].iloc[-1]
    except (IndexError, KeyError):
        # 如果无法检测顺序，默认按正序处理
        is_descending = False
    
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


def RSI(df, period=14):
    """
    RSI指标计算 - 相对强弱指标
    
    通达信公式：
    LC := REF(CLOSE,1);
    RSI:SMA(MAX(CLOSE-LC,0),N,1)/SMA(ABS(CLOSE-LC),N,1)*100;
    
    参数：
        df: DataFrame，必须包含'close'列
        period: RSI周期，默认14
    
    返回：
        DataFrame，包含'rsi'列
    """
    # 检查数据是否为空
    if df is None or df.empty:
        return pd.DataFrame({'rsi': []}, index=df.index if df is not None else [])
    
    # 检测数据顺序
    try:
        is_descending = df['date'].iloc[0] > df['date'].iloc[-1]
    except (IndexError, KeyError):
        is_descending = False
    
    # 统一转换为正序计算（从早到晚）
    if is_descending:
        df_calc = df.iloc[::-1].copy().reset_index(drop=True)
    else:
        df_calc = df.copy().reset_index(drop=True)
    
    # 计算价格变化
    close = df_calc['close']
    delta = close.diff()
    
    # 分离上涨和下跌
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    # 计算平均上涨和下跌（使用EMA）
    avg_gain = gain.ewm(com=period-1, adjust=False, min_periods=1).mean()
    avg_loss = loss.ewm(com=period-1, adjust=False, min_periods=1).mean()
    
    # 计算RS和RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    # 处理除零情况
    rsi = rsi.fillna(50)  # 当avg_loss为0时，RSI设为50
    
    # 构建结果
    result = pd.DataFrame({'rsi': rsi})
    
    # 恢复原始顺序
    if is_descending:
        result = result.iloc[::-1].reset_index(drop=True)
    
    result.index = df.index
    return result


def ADX(df, period=14):
    """
    ADX 指标（DMI 体系，Wilder 平滑）

    计算口径：
        TR   = max(high-low, |high-REF(close,1)|, |low-REF(close,1)|)
        +DM  = 向上动量（high 抬升幅度 > low 下降幅度且为正）
        -DM  = 向下动量（low 下降幅度 > high 抬升幅度且为正）
        +DI  = 100 * SMA(+DM, N, 1) / SMA(TR, N, 1)
        -DI  = 100 * SMA(-DM, N, 1) / SMA(TR, N, 1)
        DX   = 100 * |(+DI)-(-DI)| / ((+DI)+(-DI))
        ADX  = SMA(DX, N, 1)        # SMA(X,N,1) 等价于 Wilder 平滑

    常用判读：ADX < 20 无趋势（震荡）；20~25 趋势萌芽；25~50 趋势明确；> 50 强趋势。
    配合 +DI/-DI 判断方向：+DI > -DI 为多头方向，反之为空头方向。

    参数：
        df: 含 date/high/low/close 的 DataFrame（支持倒序，最新在前）
        period: 周期，默认 14

    返回：
        DataFrame，含 adx / plus_di / minus_di 三列，index 与入参对齐
    """
    if df is None or df.empty:
        return pd.DataFrame({'adx': [], 'plus_di': [], 'minus_di': []},
                            index=df.index if df is not None else [])

    # 检测数据顺序（项目内K线多为倒序：最新在前）
    try:
        is_descending = df['date'].iloc[0] > df['date'].iloc[-1]
    except (IndexError, KeyError):
        is_descending = False

    if is_descending:
        df_calc = df.iloc[::-1].copy().reset_index(drop=True)
    else:
        df_calc = df.copy().reset_index(drop=True)

    high = df_calc['high'].astype(float)
    low = df_calc['low'].astype(float)
    close = df_calc['close'].astype(float)

    prev_close = close.shift(1)
    up_move = high.diff()
    down_move = -low.diff()

    # 方向动量：只保留"更大的那一侧"，两侧相等则都为 0
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0).fillna(0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0).fillna(0.0)

    # 真实波幅
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1
    ).max(axis=1).fillna(0.0)

    # 统一转为数值类型，避免 SMA 返回 object dtype 导致后续运算异常
    smooth_tr = pd.to_numeric(SMA(tr, period, 1), errors='coerce')
    smooth_plus = pd.to_numeric(SMA(plus_dm, period, 1), errors='coerce')
    smooth_minus = pd.to_numeric(SMA(minus_dm, period, 1), errors='coerce')

    # 分母为 0 时（如开盘一字板无波幅）置 NaN，再填 0，避免除零
    safe_tr = smooth_tr.replace(0, float('nan'))
    plus_di = (100 * smooth_plus / safe_tr).fillna(0.0).astype(float)
    minus_di = (100 * smooth_minus / safe_tr).fillna(0.0).astype(float)

    di_sum = (plus_di + minus_di).replace(0, float('nan'))
    dx = (100 * (plus_di - minus_di).abs() / di_sum).fillna(0.0).astype(float)
    adx = pd.to_numeric(SMA(dx, period, 1), errors='coerce')

    result = pd.DataFrame({
        'adx': adx,
        'plus_di': plus_di,
        'minus_di': minus_di,
    })

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


def MACD(df, fastperiod=12, slowperiod=26, signalperiod=9):
    """
    MACD指标计算 - 标准实现
    通达信公式：
    DIF: EMA(CLOSE,12) - EMA(CLOSE,26)
    DEA: EMA(DIF,9)
    MACD: 2*(DIF-DEA)
    
    注意：数据可能是倒序（最新在前）或正序，需要自动检测并处理
    """
    # 检查数据是否为空
    if df is None or df.empty:
        return pd.DataFrame({'macd': [], 'macd_signal': [], 'macd_hist': []}, index=df.index if df is not None else [])
    
    # 检测数据顺序
    try:
        is_descending = df['date'].iloc[0] > df['date'].iloc[-1]
    except (IndexError, KeyError):
        # 如果无法检测顺序，默认按正序处理
        is_descending = False
    
    # 统一转换为正序计算（从早到晚）
    if is_descending:
        df_calc = df.iloc[::-1].copy().reset_index(drop=True)
    else:
        df_calc = df.copy().reset_index(drop=True)
    
    # 计算快速和慢速EMA
    ema_fast = df_calc['close'].ewm(span=fastperiod, adjust=False, min_periods=1).mean()
    ema_slow = df_calc['close'].ewm(span=slowperiod, adjust=False, min_periods=1).mean()
    
    # 计算DIF（MACD线）
    dif = ema_fast - ema_slow
    
    # 计算DEA（信号线）
    dea = dif.ewm(span=signalperiod, adjust=False, min_periods=1).mean()
    
    # 计算MACD柱状图
    macd = 2 * (dif - dea)
    
    # 构建结果
    result = pd.DataFrame({
        'macd': dif,       # DIF线
        'macd_signal': dea, # DEA线
        'macd_hist': macd   # MACD柱状图
    })
    
    # 恢复原始顺序
    if is_descending:
        result = result.iloc[::-1].reset_index(drop=True)
    
    result.index = df.index
    return result


def calculate_price_change(df, method='prev_close'):
    """
    计算价格变化率 - 统一的涨幅计算函数
    
    参数：
        df: DataFrame，必须包含'open'和'close'列
        method: 计算方法
            - 'prev_close': 相对于前一天收盘价的涨幅（标准定义）
            - 'open': 相对于当天开盘价的涨幅（日内涨幅）
    
    返回：
        Series，包含价格变化率
    
    说明：
        - 数据可能是倒序（最新在前）或正序，函数会自动处理
        - 对于倒序数据，前一天是下一行（iloc[i+1]）
        - 对于正序数据，前一天是上一行（iloc[i-1]）
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    
    # 检测数据顺序
    try:
        is_descending = df['date'].iloc[0] > df['date'].iloc[-1]
    except (IndexError, KeyError):
        is_descending = False
    
    if method == 'prev_close':
        # 相对于前一天收盘价的涨幅（标准定义）
        if is_descending:
            # 倒序数据：前一天是下一行
            prev_close = df['close'].shift(-1)
        else:
            # 正序数据：前一天是上一行
            prev_close = df['close'].shift(1)
        
        # 计算涨幅
        price_change = (df['close'] - prev_close) / prev_close
        
    elif method == 'open':
        # 相对于当天开盘价的涨幅（日内涨幅）
        price_change = (df['close'] - df['open']) / df['open']
    
    else:
        raise ValueError(f"不支持的计算方法: {method}")
    
    return price_change


def calculate_daily_return(df):
    """
    计算日收益率 - 相对于前一天收盘价的涨幅
    
    这是 calculate_price_change(df, method='prev_close') 的简化版本
    
    参数：
        df: DataFrame，必须包含'close'列
    
    返回：
        Series，包含日收益率
    """
    return calculate_price_change(df, method='prev_close')


def calculate_intraday_return(df):
    """
    计算日内收益率 - 相对于当天开盘价的涨幅
    
    这是 calculate_price_change(df, method='open') 的简化版本
    
    参数：
        df: DataFrame，必须包含'open'和'close'列
    
    返回：
        Series，包含日内收益率
    """
    return calculate_price_change(df, method='open')
