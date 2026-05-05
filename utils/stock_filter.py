"""
股票过滤模块
用于对选股结果进行过滤，支持多种过滤条件
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Any

# 配置日志
logger = logging.getLogger(__name__)

# 反向策略列表（这些策略不需要过滤跌停）
REVERSE_STRATEGIES = ['MultiDeathCrossStrategy', 'MTopStrategy']


class StockFilter:
    """股票过滤器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化过滤器
        
        Args:
            config: 过滤配置字典，包含各种过滤条件的参数
        """
        # 默认配置
        self.config = config or {
            'enabled': True,
            'recent_gain': {
                'enabled': True,
                'threshold': 30.0,  # 涨幅阈值（%）
                'days': 5           # 回看天数
            },
            'low_price_gain': {
                'enabled': True,
                'threshold': 100.0,  # 涨幅阈值（%）
                'days': 120           # 回看天数
            },
            'bias': {
                'enabled': True,
                'threshold': 12.0,    # BIAS(5)阈值（%）
                'days': 5            # BIAS周期
            },
            'recent_limit_down': {
                'enabled': True,
                'threshold': -9.5,   # 跌停阈值（%），默认-9.5%
                'days': 3            # 检查最近N天
            }
        }
        
        # 过滤统计信息
        self.filter_stats = {
            'total_before': 0,
            'total_after': 0,
            'filtered_out': 0,
            'filters_applied': {}
        }
    
    def filter_by_recent_gain(self, df: pd.DataFrame, threshold: float = 30.0, days: int = 5) -> bool:
        """
        检查股票近N日涨幅是否超过阈值
        
        公式：近N日涨幅 = (当前价格 - N日前收盘价) / N日前收盘价 * 100
        
        Args:
            df: 股票K线数据，按日期降序排列（最新数据在前）
            threshold: 涨幅阈值（%），默认30%
            days: 回看天数，默认5天
            
        Returns:
            bool: True表示应该过滤掉（涨幅超过阈值），False表示保留
        """
        try:
            # 检查数据是否足够
            if df is None or df.empty or len(df) < days + 1:
                return False
            
            current_price = df.iloc[0]['close']
            price_n_days_ago = df.iloc[days]['close']
            
            gain = (current_price - price_n_days_ago) / price_n_days_ago * 100
            should_filter = gain > threshold
            
            return should_filter
            
        except Exception as e:
            logger.warning(f"计算近{days}日涨幅失败: {str(e)}")
            return False
    
    def filter_by_low_price_gain(self, df: pd.DataFrame, threshold: float = 100.0, days: int = 120) -> bool:
        """
        检查股票当前价格相对N天内最低价的涨幅是否超过阈值
        
        公式：涨幅 = (当前价格 - N天内最低价) / N天内最低价 * 100
        
        Args:
            df: 股票K线数据，按日期降序排列（最新数据在前）
            threshold: 涨幅阈值（%），默认100%
            days: 回看天数，默认120天
            
        Returns:
            bool: True表示应该过滤掉（涨幅超过阈值），False表示保留
        """
        try:
            if df is None or df.empty or len(df) < days:
                return False
            
            current_price = df.iloc[0]['close']
            df_period = df.iloc[1:days + 1]
            low_price = df_period['low'].min()
            
            gain = (current_price - low_price) / low_price * 100
            should_filter = gain > threshold
            
            return should_filter
            
        except Exception as e:
            logger.warning(f"计算相对{days}天内最低价涨幅失败: {str(e)}")
            return False
    
    def filter_by_bias(self, df: pd.DataFrame, threshold: float = 12.0, days: int = 5) -> bool:
        """
        检查股票BIAS(5)是否超过阈值
        
        公式：BIAS(n) = (收盘价 - n日移动平均线) / n日移动平均线 * 100
        
        Args:
            df: 股票K线数据，按日期降序排列（最新数据在前）
            threshold: BIAS阈值（%），默认7%
            days: BIAS周期，默认5天
            
        Returns:
            bool: True表示应该过滤掉（BIAS超过阈值），False表示保留
        """
        try:
            if df is None or df.empty or len(df) < days:
                return False
            
            df_reversed = df.iloc[::-1].copy()
            df_reversed['MA'] = df_reversed['close'].rolling(window=days).mean()
            latest_ma = df_reversed.iloc[-1]['MA']
            current_price = df.iloc[0]['close']
            
            if latest_ma != 0:
                bias = (current_price - latest_ma) / latest_ma * 100
            else:
                return False
            
            should_filter = bias > threshold
            return should_filter
            
        except Exception as e:
            logger.warning(f"计算BIAS({days})失败: {str(e)}")
            return False
    
    def filter_by_recent_limit_down(self, df: pd.DataFrame, threshold: float = -9.5, days: int = 3) -> Tuple[bool, str]:
        """
        检查股票最近N天是否有跌停
        
        跌停判断：单日跌幅 <= threshold（默认-9.5%）
        注意：数据按日期降序排列，使用pct_change(-1)计算涨跌幅
        
        Args:
            df: 股票K线数据，按日期降序排列（最新数据在前）
            threshold: 跌停阈值（%），默认-9.5%（主板/中小板）
            days: 检查天数，默认3天
            
        Returns:
            tuple: (是否应该过滤掉, 跌停日期字符串)
        """
        try:
            if df is None or df.empty or len(df) < days + 1:
                return False, ''
            
            # 检查最近N天（包括今天）
            check_df = df.head(days + 1)
            
            # 计算涨跌幅（使用-1计算相对于下一行，即更旧日期的变化）
            pct_change = check_df['close'].pct_change(-1)
            
            # 查找跌停日
            limit_down_mask = pct_change <= threshold / 100
            
            if limit_down_mask.any():
                # 找到第一个跌停日的索引
                limit_down_idx = limit_down_mask[limit_down_mask].index[0]
                limit_down_date = check_df.loc[limit_down_idx, 'date']
                limit_down_pct = pct_change.loc[limit_down_idx] * 100
                
                # 格式化日期
                if hasattr(limit_down_date, 'strftime'):
                    date_str = limit_down_date.strftime('%Y-%m-%d')
                else:
                    date_str = str(limit_down_date)
                
                return True, f"{date_str} (跌幅{limit_down_pct:.2f}%)"
            
            return False, ''
            
        except Exception as e:
            logger.warning(f"检查最近{days}天跌停失败: {str(e)}")
            return False, ''
    
    def is_reverse_strategy(self, strategy_name: str) -> bool:
        """
        判断是否为反向策略
        
        反向策略：多死叉共振策略、M头策略
        这些策略不需要过滤跌停
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            bool: True表示是反向策略，False表示是正向策略
        """
        # 检查策略名称是否在反向策略列表中
        for reverse_name in REVERSE_STRATEGIES:
            if reverse_name in strategy_name:
                return True
        return False
    
    def apply_filters(self, results: Dict[str, List[Dict]], stock_data: Dict[str, Tuple[str, pd.DataFrame]]) -> Tuple[Dict[str, List[Dict]], Dict[str, Any]]:
        """
        对选股结果应用所有过滤条件
        
        Args:
            results: 选股结果字典 {策略名: [信号列表]}
            stock_data: 股票数据字典 {股票代码: (股票名称, K线数据)}
            
        Returns:
            tuple: (过滤后的结果, 过滤统计信息)
        """
        if not self.config.get('enabled', True):
            return results, {'enabled': False}
        
        # 初始化统计信息
        self.filter_stats = {
            'enabled': True,
            'total_before': 0,
            'total_after': 0,
            'filtered_out': 0,
            'filters_applied': {
                'recent_gain': 0,
                'low_price_gain': 0,
                'bias': 0,
                'recent_limit_down': 0
            }
        }
        
        # 统计过滤前的总数
        for strategy_name, signals in results.items():
            if isinstance(signals, list):
                self.filter_stats['total_before'] += len(signals)
        
        # 过滤结果
        filtered_results = {}
        
        for strategy_name, signals in results.items():
            # 跳过特殊字段
            if strategy_name.startswith('_'):
                filtered_results[strategy_name] = signals
                continue
            
            # 确保signals是列表
            if not isinstance(signals, list):
                filtered_results[strategy_name] = signals
                continue
            
            # 判断是否为反向策略
            is_reverse = self.is_reverse_strategy(strategy_name)
            
            # 对每个信号进行过滤
            filtered_signals = []
            
            for signal in signals:
                # 验证信号结构
                if not isinstance(signal, dict) or 'code' not in signal:
                    filtered_signals.append(signal)
                    continue
                
                code = signal['code']
                
                # 获取股票数据
                if code not in stock_data:
                    filtered_signals.append(signal)
                    continue
                
                stock_name, df = stock_data[code]
                
                # 应用近N日涨幅过滤
                recent_gain_config = self.config.get('recent_gain', {})
                if recent_gain_config.get('enabled', True):
                    threshold = recent_gain_config.get('threshold', 30.0)
                    days = recent_gain_config.get('days', 5)
                    
                    if self.filter_by_recent_gain(df, threshold=threshold, days=days):
                        self.filter_stats['filters_applied']['recent_gain'] += 1
                        self.filter_stats['filtered_out'] += 1
                        
                        if 'filtered_stocks' not in self.filter_stats:
                            self.filter_stats['filtered_stocks'] = []
                        
                        try:
                            current_price = df.iloc[0]['close']
                            price_n_days_ago = df.iloc[days]['close']
                            gain = (current_price - price_n_days_ago) / price_n_days_ago * 100
                            
                            self.filter_stats['filtered_stocks'].append({
                                'code': code,
                                'name': stock_name,
                                'strategy': strategy_name,
                                'reason': f'近{days}日涨幅{gain:.2f}%超过{threshold}%',
                                'gain': round(gain, 2)
                            })
                        except:
                            pass
                        
                        continue
                
                # 应用相对最低价涨幅过滤
                low_price_gain_config = self.config.get('low_price_gain', {})
                if low_price_gain_config.get('enabled', True):
                    threshold = low_price_gain_config.get('threshold', 100.0)
                    days = low_price_gain_config.get('days', 120)
                    
                    if self.filter_by_low_price_gain(df, threshold=threshold, days=days):
                        self.filter_stats['filters_applied']['low_price_gain'] += 1
                        self.filter_stats['filtered_out'] += 1
                        
                        if 'filtered_stocks' not in self.filter_stats:
                            self.filter_stats['filtered_stocks'] = []
                        
                        try:
                            current_price = df.iloc[0]['close']
                            df_period = df.iloc[1:days + 1]
                            low_price = df_period['low'].min()
                            gain = (current_price - low_price) / low_price * 100
                            
                            self.filter_stats['filtered_stocks'].append({
                                'code': code,
                                'name': stock_name,
                                'strategy': strategy_name,
                                'reason': f'相对{days}天内最低价涨幅{gain:.2f}%超过{threshold}%',
                                'gain': round(gain, 2)
                            })
                        except:
                            pass
                        
                        continue
                
                # 应用BIAS过滤
                bias_config = self.config.get('bias', {})
                if bias_config.get('enabled', True):
                    threshold = bias_config.get('threshold', 12.0)
                    days = bias_config.get('days', 5)
                    
                    if self.filter_by_bias(df, threshold=threshold, days=days):
                        self.filter_stats['filters_applied']['bias'] += 1
                        self.filter_stats['filtered_out'] += 1
                        
                        if 'filtered_stocks' not in self.filter_stats:
                            self.filter_stats['filtered_stocks'] = []
                        
                        try:
                            df_reversed = df.iloc[::-1].copy()
                            df_reversed['MA'] = df_reversed['close'].rolling(window=days).mean()
                            latest_ma = df_reversed.iloc[-1]['MA']
                            current_price = df.iloc[0]['close']
                            if latest_ma != 0:
                                bias = (current_price - latest_ma) / latest_ma * 100
                                
                                self.filter_stats['filtered_stocks'].append({
                                    'code': code,
                                    'name': stock_name,
                                    'strategy': strategy_name,
                                    'reason': f'BIAS({days}){bias:.2f}%超过{threshold}%',
                                    'bias': round(bias, 2)
                                })
                        except:
                            pass
                        
                        continue
                
                # 应用跌停过滤（仅对正向策略）
                if not is_reverse:
                    limit_down_config = self.config.get('recent_limit_down', {})
                    if limit_down_config.get('enabled', True):
                        threshold = limit_down_config.get('threshold', -9.5)
                        days = limit_down_config.get('days', 3)
                        
                        should_filter, limit_down_info = self.filter_by_recent_limit_down(
                            df, threshold=threshold, days=days
                        )
                        
                        if should_filter:
                            self.filter_stats['filters_applied']['recent_limit_down'] += 1
                            self.filter_stats['filtered_out'] += 1
                            
                            if 'filtered_stocks' not in self.filter_stats:
                                self.filter_stats['filtered_stocks'] = []
                            
                            self.filter_stats['filtered_stocks'].append({
                                'code': code,
                                'name': stock_name,
                                'strategy': strategy_name,
                                'reason': f'最近{days}天有跌停: {limit_down_info}'
                            })
                            
                            continue
                
                # 通过所有过滤条件，保留该信号
                filtered_signals.append(signal)
            
            filtered_results[strategy_name] = filtered_signals
        
        # 统计过滤后的总数
        for strategy_name, signals in filtered_results.items():
            if isinstance(signals, list) and not strategy_name.startswith('_'):
                self.filter_stats['total_after'] += len(signals)
        
        return filtered_results, self.filter_stats
    
    def get_filter_stats(self) -> Dict[str, Any]:
        """
        获取过滤统计信息
        
        Returns:
            dict: 过滤统计信息
        """
        return self.filter_stats


def create_filter(config: Dict[str, Any] = None) -> StockFilter:
    """
    创建股票过滤器实例
    
    Args:
        config: 过滤配置
        
    Returns:
        StockFilter: 过滤器实例
    """
    return StockFilter(config)
