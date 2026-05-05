"""
技术指标计算模块
提供常用技术指标的计算，支持缓存机制，确保一个技术指标只计算一次
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional


class TechnicalIndicators:
    """技术指标计算类"""
    
    def __init__(self):
        """初始化技术指标计算类"""
        # 缓存计算结果，格式: {股票代码: {指标名称: 计算结果}}
        self.cache: Dict[str, Dict[str, pd.Series]] = {}
    
    def _get_cache_key(self, stock_code: str, indicator_name: str, params: Tuple) -> str:
        """生成缓存键
        
        Args:
            stock_code: 股票代码
            indicator_name: 指标名称
            params: 指标参数
            
        Returns:
            缓存键
        """
        params_str = "_".join(map(str, params))
        return f"{indicator_name}_{params_str}"
    
    def calculate_ma(self, df: pd.DataFrame, period: int, stock_code: str = "") -> pd.Series:
        """计算移动平均线
        
        Args:
            df: 股票数据
            period: 周期
            stock_code: 股票代码（用于缓存）
            
        Returns:
            移动平均线
        """
        if stock_code not in self.cache:
            self.cache[stock_code] = {}
        
        key = self._get_cache_key(stock_code, "ma", (period,))
        if key not in self.cache[stock_code]:
            self.cache[stock_code][key] = df['close'].rolling(window=period).mean()
        
        return self.cache[stock_code][key]
    
    def calculate_atr(self, df: pd.DataFrame, period: int, stock_code: str = "") -> pd.Series:
        """计算真实波幅
        
        Args:
            df: 股票数据
            period: 周期
            stock_code: 股票代码（用于缓存）
            
        Returns:
            真实波幅
        """
        if stock_code not in self.cache:
            self.cache[stock_code] = {}
        
        key = self._get_cache_key(stock_code, "atr", (period,))
        if key not in self.cache[stock_code]:
            # 计算真实波幅（与海归策略一致的计算方法）
            df_copy = df.copy()
            df_copy['true_high'] = df_copy[['high', 'close']].max(axis=1)
            df_copy['true_low'] = df_copy[['low', 'close']].min(axis=1)
            df_copy['atr'] = df_copy['true_high'] - df_copy['true_low']
            self.cache[stock_code][key] = df_copy['atr'].rolling(window=period).mean()
        
        return self.cache[stock_code][key]
    
    def calculate_rsi(self, df: pd.DataFrame, period: int, stock_code: str = "") -> pd.Series:
        """计算相对强弱指数
        
        Args:
            df: 股票数据
            period: 周期
            stock_code: 股票代码（用于缓存）
            
        Returns:
            RSI值
        """
        if stock_code not in self.cache:
            self.cache[stock_code] = {}
        
        key = self._get_cache_key(stock_code, "rsi", (period,))
        if key not in self.cache[stock_code]:
            df_copy = df.copy()
            # 计算涨跌值
            df_copy['change'] = df_copy['close'].diff()
            df_copy['gain'] = df_copy['change'].apply(lambda x: x if x > 0 else 0)
            df_copy['loss'] = df_copy['change'].apply(lambda x: abs(x) if x < 0 else 0)
            
            # 计算平均涨幅和平均跌幅
            df_copy['avg_gain'] = df_copy['gain'].rolling(window=period).mean()
            df_copy['avg_loss'] = df_copy['loss'].rolling(window=period).mean()
            
            # 计算RSI
            def rsi_calc(row):
                if row['avg_loss'] == 0:
                    return 100
                rs = row['avg_gain'] / row['avg_loss']
                return 100 - (100 / (1 + rs))
            
            self.cache[stock_code][key] = df_copy.apply(rsi_calc, axis=1)
        
        return self.cache[stock_code][key]
    
    def calculate_bollinger_bands(self, df: pd.DataFrame, period: int, multiplier: float, stock_code: str = "") -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算布林带
        
        Args:
            df: 股票数据
            period: 周期
            multiplier: 标准差倍数
            stock_code: 股票代码（用于缓存）
            
        Returns:
            (中轨, 上轨, 下轨)
        """
        if stock_code not in self.cache:
            self.cache[stock_code] = {}
        
        key_mid = self._get_cache_key(stock_code, "boll_mid", (period,))
        key_upper = self._get_cache_key(stock_code, "boll_upper", (period, multiplier))
        key_lower = self._get_cache_key(stock_code, "boll_lower", (period, multiplier))
        
        if key_mid not in self.cache[stock_code]:
            # 计算中轨
            mid = df['close'].rolling(window=period).mean()
            self.cache[stock_code][key_mid] = mid
        else:
            mid = self.cache[stock_code][key_mid]
        
        if key_upper not in self.cache[stock_code] or key_lower not in self.cache[stock_code]:
            # 计算标准差
            std = df['close'].rolling(window=period).std()
            # 计算上轨和下轨
            upper = mid + multiplier * std
            lower = mid - multiplier * std
            self.cache[stock_code][key_upper] = upper
            self.cache[stock_code][key_lower] = lower
        else:
            upper = self.cache[stock_code][key_upper]
            lower = self.cache[stock_code][key_lower]
        
        return mid, upper, lower
    
    def calculate_kdj(self, df: pd.DataFrame, n: int, m1: int, m2: int, stock_code: str = "") -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算KDJ指标
        
        Args:
            df: 股票数据
            n: 周期
            m1: 快线平滑周期
            m2: 慢线平滑周期
            stock_code: 股票代码（用于缓存）
            
        Returns:
            (K值, D值, J值)
        """
        if stock_code not in self.cache:
            self.cache[stock_code] = {}
        
        key_k = self._get_cache_key(stock_code, "kdj_k", (n, m1, m2))
        key_d = self._get_cache_key(stock_code, "kdj_d", (n, m1, m2))
        key_j = self._get_cache_key(stock_code, "kdj_j", (n, m1, m2))
        
        if key_k not in self.cache[stock_code] or key_d not in self.cache[stock_code] or key_j not in self.cache[stock_code]:
            df_copy = df.copy()
            # 计算RSV
            df_copy['low_n'] = df_copy['low'].rolling(window=n).min()
            df_copy['high_n'] = df_copy['high'].rolling(window=n).max()
            df_copy['rsv'] = (df_copy['close'] - df_copy['low_n']) / (df_copy['high_n'] - df_copy['low_n']) * 100
            
            # 计算K值
            df_copy['k'] = 50
            for i in range(1, len(df_copy)):
                df_copy.loc[df_copy.index[i], 'k'] = df_copy.loc[df_copy.index[i-1], 'k'] * (m1-1)/m1 + df_copy.loc[df_copy.index[i], 'rsv'] * 1/m1
            
            # 计算D值
            df_copy['d'] = 50
            for i in range(1, len(df_copy)):
                df_copy.loc[df_copy.index[i], 'd'] = df_copy.loc[df_copy.index[i-1], 'd'] * (m2-1)/m2 + df_copy.loc[df_copy.index[i], 'k'] * 1/m2
            
            # 计算J值
            df_copy['j'] = 3 * df_copy['k'] - 2 * df_copy['d']
            
            self.cache[stock_code][key_k] = df_copy['k']
            self.cache[stock_code][key_d] = df_copy['d']
            self.cache[stock_code][key_j] = df_copy['j']
        else:
            k = self.cache[stock_code][key_k]
            d = self.cache[stock_code][key_d]
            j = self.cache[stock_code][key_j]
        
        return k, d, j
    
    def calculate_macd(self, df: pd.DataFrame, short_period: int, long_period: int, signal_period: int, stock_code: str = "") -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算MACD指标
        
        Args:
            df: 股票数据
            short_period: 短期EMA周期
            long_period: 长期EMA周期
            signal_period: 信号周期
            stock_code: 股票代码（用于缓存）
            
        Returns:
            (MACD线, 信号线, 柱状图)
        """
        if stock_code not in self.cache:
            self.cache[stock_code] = {}
        
        key_macd = self._get_cache_key(stock_code, "macd", (short_period, long_period, signal_period))
        key_signal = self._get_cache_key(stock_code, "macd_signal", (short_period, long_period, signal_period))
        key_hist = self._get_cache_key(stock_code, "macd_hist", (short_period, long_period, signal_period))
        
        if key_macd not in self.cache[stock_code] or key_signal not in self.cache[stock_code] or key_hist not in self.cache[stock_code]:
            # 计算短期EMA
            ema_short = df['close'].ewm(span=short_period, adjust=False).mean()
            # 计算长期EMA
            ema_long = df['close'].ewm(span=long_period, adjust=False).mean()
            # 计算MACD线
            macd_line = ema_short - ema_long
            # 计算信号线
            signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
            # 计算柱状图
            hist = macd_line - signal_line
            
            self.cache[stock_code][key_macd] = macd_line
            self.cache[stock_code][key_signal] = signal_line
            self.cache[stock_code][key_hist] = hist
        else:
            macd_line = self.cache[stock_code][key_macd]
            signal_line = self.cache[stock_code][key_signal]
            hist = self.cache[stock_code][key_hist]
        
        return macd_line, signal_line, hist
    
    def clear_cache(self, stock_code: Optional[str] = None):
        """清空缓存
        
        Args:
            stock_code: 股票代码，如果为None则清空所有缓存
        """
        if stock_code:
            if stock_code in self.cache:
                del self.cache[stock_code]
        else:
            self.cache.clear()
    
    def get_cached_indicators(self, stock_code: str) -> Dict[str, pd.Series]:
        """获取股票的缓存指标
        
        Args:
            stock_code: 股票代码
            
        Returns:
            缓存的指标
        """
        return self.cache.get(stock_code, {})
    
    def has_cached(self, stock_code: str, indicator_name: str, params: Tuple) -> bool:
        """检查指标是否已缓存
        
        Args:
            stock_code: 股票代码
            indicator_name: 指标名称
            params: 指标参数
            
        Returns:
            是否已缓存
        """
        if stock_code not in self.cache:
            return False
        
        key = self._get_cache_key(stock_code, indicator_name, params)
        return key in self.cache[stock_code]
