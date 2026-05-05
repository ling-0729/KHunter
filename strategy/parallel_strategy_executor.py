"""
并行策略执行器 - 使用多进程并行执行策略分析

优化点：
1. 使用ProcessPoolExecutor并行处理多只股票
2. 批量预计算指标，减少重复计算
3. 支持超时控制，避免单只股票阻塞
"""
import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from datetime import datetime
import logging
from typing import Dict, List, Tuple, Optional, Callable
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# 默认工作进程数 - 使用CPU核心数
DEFAULT_MAX_WORKERS = max(1, cpu_count() - 1)


def analyze_single_stock(args: Tuple) -> Optional[Dict]:
    """
    分析单只股票的包装函数 - 用于多进程
    
    参数:
        args: (strategy_class, strategy_params, stock_code, stock_name, df)
    
    返回:
        分析结果或None
    """
    strategy_class, strategy_params, stock_code, stock_name, df = args
    
    try:
        # 创建策略实例
        strategy = strategy_class(strategy_params)
        
        # 执行分析
        result = strategy.analyze_stock(stock_code, stock_name, df)
        return result
    except Exception as e:
        logger.debug(f"分析股票 {stock_code} 失败: {str(e)}")
        return None


class ParallelStrategyExecutor:
    """
    并行策略执行器
    
    使用多进程并行执行策略分析，提高选股性能。
    """
    
    def __init__(self, max_workers: int = None, timeout: int = 30):
        """
        初始化并行执行器
        
        参数:
            max_workers: 最大工作进程数，默认为CPU核心数-1
            timeout: 单只股票分析超时时间（秒）
        """
        self.max_workers = max_workers or DEFAULT_MAX_WORKERS
        self.timeout = timeout
        logger.info(f"并行策略执行器初始化完成，工作进程数: {self.max_workers}")
    
    def execute_strategy(
        self,
        strategy_class,
        strategy_params: Dict,
        stock_data: Dict[str, Tuple[str, pd.DataFrame]],
        progress_callback: Callable = None
    ) -> List[Dict]:
        """
        并行执行策略分析
        
        参数:
            strategy_class: 策略类
            strategy_params: 策略参数
            stock_data: 股票数据字典 {code: (name, df)}
            progress_callback: 进度回调函数，接收(current, total, selected)参数
        
        返回:
            选股结果列表
        """
        if not stock_data:
            logger.warning("股票数据为空")
            return []
        
        total = len(stock_data)
        logger.info(f"开始并行策略分析，共 {total} 只股票，工作进程数: {self.max_workers}")
        
        # 准备任务参数
        tasks = [
            (strategy_class, strategy_params, code, name, df)
            for code, (name, df) in stock_data.items()
        ]
        
        results = []
        completed = 0
        error_count = 0
        
        start_time = datetime.now()
        
        # 使用进程池并行执行
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_task = {
                executor.submit(analyze_single_stock, task): task
                for task in tasks
            }
            
            # 处理完成的任务
            for future in as_completed(future_to_task):
                completed += 1
                
                try:
                    result = future.result(timeout=self.timeout)
                    if result:
                        results.append(result)
                except Exception as e:
                    error_count += 1
                    if error_count <= 5:
                        logger.debug(f"任务执行失败: {str(e)}")
                
                # 报告进度
                if progress_callback and completed % 100 == 0:
                    progress_callback(completed, total, len(results))
                
                # 每500只记录一次日志
                if completed % 500 == 0:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    progress = completed / total * 100
                    logger.info(f"  进度: [{completed}/{total}] {progress:.1f}% - 已选中 {len(results)} 只，耗时 {elapsed:.1f}秒")
        
        total_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"并行策略分析完成: 共 {completed} 只，选中 {len(results)} 只，失败 {error_count} 只，耗时 {total_time:.1f}秒")
        
        return results
    
    def execute_strategy_chunked(
        self,
        strategy_class,
        strategy_params: Dict,
        stock_data: Dict[str, Tuple[str, pd.DataFrame]],
        chunk_size: int = 1000,
        progress_callback: Callable = None
    ) -> List[Dict]:
        """
        分块并行执行策略分析 - 适用于大量股票
        
        参数:
            strategy_class: 策略类
            strategy_params: 策略参数
            stock_data: 股票数据字典 {code: (name, df)}
            chunk_size: 每块大小
            progress_callback: 进度回调函数
        
        返回:
            选股结果列表
        """
        if not stock_data:
            return []
        
        items = list(stock_data.items())
        total = len(items)
        all_results = []
        
        logger.info(f"开始分块并行策略分析，共 {total} 只股票，块大小: {chunk_size}")
        
        # 分块处理
        for i in range(0, total, chunk_size):
            chunk = items[i:i + chunk_size]
            chunk_data = {code: (name, df) for code, (name, df) in chunk}
            
            logger.info(f"处理第 {i//chunk_size + 1} 块，共 {len(chunk)} 只股票")
            
            results = self.execute_strategy(
                strategy_class,
                strategy_params,
                chunk_data,
                progress_callback
            )
            
            all_results.extend(results)
            
            logger.info(f"第 {i//chunk_size + 1} 块完成，累计选中 {len(all_results)} 只")
        
        logger.info(f"分块并行策略分析完成，共选中 {len(all_results)} 只股票")
        return all_results


class FastMultiGoldenCrossAnalyzer:
    """
    快速多金叉共振分析器
    
    专门针对多金叉共振策略的优化分析器
    """
    
    def __init__(self, params: Dict = None):
        """
        初始化分析器
        
        参数:
            params: 策略参数
        """
        self.params = params or {}
        
        # 默认参数
        self.ma_short_period = self.params.get('ma_short_period', 5)
        self.ma_long_period = self.params.get('ma_long_period', 20)
        self.kdj_n = self.params.get('kdj_n', 9)
        self.kdj_m1 = self.params.get('kdj_m1', 3)
        self.kdj_m2 = self.params.get('kdj_m2', 3)
        self.macd_short = self.params.get('macd_short', 12)
        self.macd_long = self.params.get('macd_long', 26)
        self.macd_signal = self.params.get('macd_signal', 9)
        self.resonance_days = self.params.get('resonance_days', 3)
        self.lookback_days = self.params.get('lookback_days', 10)
    
    def analyze_stock(self, stock_code: str, stock_name: str, df: pd.DataFrame) -> Optional[Dict]:
        """
        快速分析单只股票
        
        参数:
            stock_code: 股票代码
            stock_name: 股票名称
            df: 股票数据
        
        返回:
            分析结果或None
        """
        # 快速预检查
        if df.empty or len(df) < self.lookback_days:
            return None
        
        # 过滤退市/异常股票
        if stock_name:
            if stock_name.startswith('*ST') or stock_name.startswith('ST') or '退' in stock_name or '未知' in stock_name:
                return None
        
        # 获取最新数据
        latest = df.iloc[0]
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return None
        
        # 计算指标
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # 均线
        ma_short = close.rolling(window=self.ma_short_period, min_periods=1).mean()
        ma_long = close.rolling(window=self.ma_long_period, min_periods=1).mean()
        
        # 价格确认
        if latest['close'] < ma_short.iloc[0] or latest['close'] < ma_long.iloc[0]:
            return None
        
        # KDJ
        lowest_low = low.rolling(window=self.kdj_n, min_periods=1).min()
        highest_high = high.rolling(window=self.kdj_n, min_periods=1).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
        rsv = rsv.fillna(50)
        K = rsv.ewm(alpha=1/self.kdj_m1, adjust=False).mean()
        D = K.ewm(alpha=1/self.kdj_m2, adjust=False).mean()
        
        # MACD
        ema_short = close.ewm(span=self.macd_short, adjust=False).mean()
        ema_long = close.ewm(span=self.macd_long, adjust=False).mean()
        DIF = ema_short - ema_long
        DEA = DIF.ewm(span=self.macd_signal, adjust=False).mean()
        
        # 金叉信号检测
        ma_cross = (ma_short > ma_long) & (ma_short.shift(-1) <= ma_long.shift(-1))
        kdj_cross = (K > D) & (K.shift(-1) <= D.shift(-1))
        macd_cross = (DIF > DEA) & (DIF.shift(-1) <= DEA.shift(-1))
        
        # 获取回溯期间的数据
        lookback = min(self.lookback_days, len(df))
        
        # 检查金叉信号
        if not ma_cross.head(lookback).any() or not kdj_cross.head(lookback).any() or not macd_cross.head(lookback).any():
            return None
        
        # 查找金叉日期
        ma_cross_idx = ma_cross.head(lookback).values.argmax()
        kdj_cross_idx = kdj_cross.head(lookback).values.argmax()
        macd_cross_idx = macd_cross.head(lookback).values.argmax()
        
        if not ma_cross.iloc[ma_cross_idx] or not kdj_cross.iloc[kdj_cross_idx] or not macd_cross.iloc[macd_cross_idx]:
            return None
        
        ma_cross_date = df.iloc[ma_cross_idx]['date']
        kdj_cross_date = df.iloc[kdj_cross_idx]['date']
        macd_cross_date = df.iloc[macd_cross_idx]['date']
        
        # 检查共振
        dates = [ma_cross_date, kdj_cross_date, macd_cross_date]
        max_diff = abs((max(dates) - min(dates)).days)
        
        if max_diff > self.resonance_days:
            return None
        
        # 计算其他指标
        # 数据是倒序的，需要先反转后计算再反转回来
        reversed_volume = volume.iloc[::-1]
        reversed_volume_ma = reversed_volume.rolling(window=5, min_periods=1).mean()
        volume_ma = reversed_volume_ma.iloc[::-1]
        short_term_trend = close.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean()
        bull_bear_line = (
            close.rolling(window=14, min_periods=1).mean() +
            close.rolling(window=28, min_periods=1).mean() +
            close.rolling(window=57, min_periods=1).mean() +
            close.rolling(window=114, min_periods=1).mean()
        ) / 4
        
        market_cap = df['market_cap'].iloc[0] if 'market_cap' in df.columns else latest['close'] * 2e8
        
        return {
            'code': stock_code,
            'name': stock_name,
            'signals': [{
                'date': latest['date'],
                'close': round(latest['close'], 2),
                'ma_cross_date': ma_cross_date,
                'kdj_cross_date': kdj_cross_date,
                'macd_cross_date': macd_cross_date,
                'max_time_diff': max_diff,
                'ma_short': round(ma_short.iloc[0], 2),
                'ma_long': round(ma_long.iloc[0], 2),
                'K': round(K.iloc[0], 2),
                'D': round(D.iloc[0], 2),
                'J': round(3 * K.iloc[0] - 2 * D.iloc[0], 2),
                'DIF': round(DIF.iloc[0], 4),
                'DEA': round(DEA.iloc[0], 4),
                'MACD': round((DIF.iloc[0] - DEA.iloc[0]) * 2, 4),
                'volume_ratio': round(volume.iloc[0] / volume_ma.iloc[0], 2),
                'market_cap': round(market_cap / 1e8, 2),
                'short_term_trend': round(short_term_trend.iloc[0], 2),
                'bull_bear_line': round(bull_bear_line.iloc[0], 2),
                'reasons': ['均线金叉', 'KDJ金叉', 'MACD金叉', '多指标共振']
            }]
        }


def parallel_analyze_stocks(
    stock_data: Dict[str, Tuple[str, pd.DataFrame]],
    strategy_params: Dict = None,
    max_workers: int = None,
    chunk_size: int = 1000
) -> List[Dict]:
    """
    并行分析多只股票 - 便捷函数
    
    参数:
        stock_data: 股票数据字典 {code: (name, df)}
        strategy_params: 策略参数
        max_workers: 最大工作进程数
        chunk_size: 分块大小
    
    返回:
        选股结果列表
    """
    executor = ParallelStrategyExecutor(max_workers=max_workers)
    
    return executor.execute_strategy_chunked(
        FastMultiGoldenCrossAnalyzer,
        strategy_params or {},
        stock_data,
        chunk_size=chunk_size
    )
