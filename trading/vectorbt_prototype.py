"""
VectorBT向量化回测原型

本模块实现了一个简单的VectorBT回测原型，用于验证向量化回测的性能和准确性。
主要功能：
1. 向量化数据加载 - 一次性加载所有股票数据到矩阵
2. 向量化信号生成 - 使用VectorBT计算技术指标和生成买卖信号
3. VectorBT回测执行 - 使用VectorBT执行向量化回测
4. 结果提取和分析 - 提取交易记录和性能指标

性能目标：
- 执行时间: < 30秒
- 内存占用: < 100MB
- 性能提升: > 30倍
"""

import pandas as pd
import numpy as np
import vectorbt as vbt
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import time

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VectorBTDataLoader:
    """向量化数据加载器"""
    
    def __init__(self, db_manager):
        """
        初始化数据加载器
        
        Args:
            db_manager: 数据库管理器实例
        """
        # db_manager: 数据库管理器，类型DBManager，必填
        self.db_manager = db_manager
    
    def load_prices_matrix(self, stock_codes: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        """
        加载价格矩阵 (行=日期, 列=股票代码)
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        
        Returns:
            pd.DataFrame: 价格矩阵，形状为 (n_days, n_stocks)
        """
        # stock_codes: 股票代码列表，类型List[str]，必填
        # start_date: 开始日期，类型str，必填
        # end_date: 结束日期，类型str，必填
        logger.info(f"开始加载价格数据: {len(stock_codes)}只股票, {start_date} - {end_date}")
        
        # 1. 一次性加载所有股票数据
        prices_dict = {}
        for code in stock_codes:
            try:
                # 从数据库读取股票数据
                df = self.db_manager.read_stock(code, end_date=end_date)
                
                # 过滤日期范围
                if not df.empty:
                    df['date'] = pd.to_datetime(df['date'])
                    df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
                    
                    # 按日期升序排列
                    df = df.sort_values('date')
                    
                    # 提取收盘价
                    prices_dict[code] = df['close'].values
            except Exception as e:
                logger.warning(f"加载股票数据失败: {code} - {str(e)}")
                continue
        
        # 2. 转换为DataFrame矩阵
        if not prices_dict:
            logger.error("没有成功加载任何股票数据")
            return pd.DataFrame()
        
        # 创建DataFrame，使用最长的数据作为索引
        prices = pd.DataFrame(prices_dict)
        
        logger.info(f"成功加载价格数据: {prices.shape[0]}个交易日, {prices.shape[1]}只股票")
        return prices
    
    def load_scores_matrix(self, stock_codes: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        """
        加载评分矩阵 (行=日期, 列=股票代码)
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        
        Returns:
            pd.DataFrame: 评分矩阵，形状为 (n_days, n_stocks)
        """
        # stock_codes: 股票代码列表，类型List[str]，必填
        # start_date: 开始日期，类型str，必填
        # end_date: 结束日期，类型str，必填
        logger.info(f"开始加载评分数据: {len(stock_codes)}只股票")
        
        # 1. 从数据库加载评分数据
        scores_dict = {}
        for code in stock_codes:
            try:
                # 查询评分数据
                sql = """
                    SELECT date, score
                    FROM stock_score
                    WHERE code = ? AND date >= ? AND date <= ?
                    ORDER BY date ASC
                """
                results = self.db_manager.query(sql, (code, start_date, end_date))
                
                if results:
                    # 转换为Series
                    df = pd.DataFrame(results)
                    scores_dict[code] = df['score'].values
            except Exception as e:
                logger.warning(f"加载评分数据失败: {code} - {str(e)}")
                continue
        
        # 2. 转换为DataFrame矩阵
        if not scores_dict:
            logger.warning("没有成功加载任何评分数据")
            return pd.DataFrame()
        
        scores = pd.DataFrame(scores_dict)
        logger.info(f"成功加载评分数据: {scores.shape[0]}个交易日, {scores.shape[1]}只股票")
        return scores


class VectorBTSignalGenerator:
    """向量化信号生成器"""
    
    def __init__(self):
        """初始化信号生成器"""
        pass
    
    def generate_dual_ma_signals(self, prices: pd.DataFrame, fast_window: int = 10, 
                                 slow_window: int = 50) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        生成双均线交叉信号
        
        Args:
            prices: 价格矩阵 (行=日期, 列=股票)
            fast_window: 快线窗口
            slow_window: 慢线窗口
        
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (买入信号, 卖出信号)
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # fast_window: 快线窗口，类型int，默认10
        # slow_window: 慢线窗口，类型int，默认50
        logger.info(f"生成双均线信号: fast_window={fast_window}, slow_window={slow_window}")
        
        # 1. 计算移动平均线
        ma_fast = vbt.MA.run(prices, window=fast_window)
        ma_slow = vbt.MA.run(prices, window=slow_window)
        
        # 2. 生成交叉信号
        buy_signals = ma_fast.ma_crossed_above(ma_slow)
        sell_signals = ma_fast.ma_crossed_below(ma_slow)
        
        logger.info(f"买入信号数: {buy_signals.sum().sum()}, 卖出信号数: {sell_signals.sum().sum()}")
        return buy_signals, sell_signals
    
    def apply_score_filter(self, buy_signals: pd.DataFrame, scores: pd.DataFrame, 
                          score_threshold: float = 50.0) -> pd.DataFrame:
        """
        应用评分过滤
        
        Args:
            buy_signals: 买入信号矩阵
            scores: 评分矩阵
            score_threshold: 评分阈值
        
        Returns:
            pd.DataFrame: 过滤后的买入信号
        """
        # buy_signals: 买入信号矩阵，类型pd.DataFrame，必填
        # scores: 评分矩阵，类型pd.DataFrame，必填
        # score_threshold: 评分阈值，类型float，默认50.0
        logger.info(f"应用评分过滤: threshold={score_threshold}")
        
        # 1. 对齐数据
        buy_signals, scores = buy_signals.align(scores, join='inner')
        
        # 2. 应用过滤条件
        filtered_signals = buy_signals & (scores >= score_threshold)
        
        logger.info(f"过滤后买入信号数: {filtered_signals.sum().sum()}")
        return filtered_signals


class VectorBTBacktestExecutor:
    """VectorBT回测执行器"""
    
    def __init__(self):
        """初始化回测执行器"""
        pass
    
    def run_backtest(self, prices: pd.DataFrame, buy_signals: pd.DataFrame, 
                    sell_signals: pd.DataFrame, config: Dict) -> vbt.Portfolio:
        """
        执行VectorBT回测
        
        Args:
            prices: 价格矩阵
            buy_signals: 买入信号矩阵
            sell_signals: 卖出信号矩阵
            config: 配置字典，包含 init_cash, fees等
        
        Returns:
            vbt.Portfolio: 回测结果
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        # buy_signals: 买入信号矩阵，类型pd.DataFrame，必填
        # sell_signals: 卖出信号矩阵，类型pd.DataFrame，必填
        # config: 配置字典，类型Dict，必填
        logger.info("开始执行VectorBT回测")
        
        # 1. 提取配置参数
        init_cash = config.get('init_cash', 1000000)
        fees = config.get('fees', 0.001)
        
        # 2. 对齐数据
        prices, buy_signals, sell_signals = vbt.broadcast(prices, buy_signals, sell_signals)
        
        # 3. 执行回测
        pf = vbt.Portfolio.from_signals(
            close=prices,
            entries=buy_signals,
            exits=sell_signals,
            init_cash=init_cash,
            fees=fees,
            freq='D'
        )
        
        logger.info("VectorBT回测执行完成")
        return pf
    
    def extract_results(self, pf: vbt.Portfolio, prices: pd.DataFrame) -> Dict:
        """
        提取回测结果
        
        Args:
            pf: Portfolio对象
            prices: 价格矩阵
        
        Returns:
            Dict: 回测结果字典
        """
        # pf: Portfolio对象，类型vbt.Portfolio，必填
        # prices: 价格矩阵，类型pd.DataFrame，必填
        logger.info("提取回测结果")
        
        # 1. 计算性能指标
        total_return = pf.total_return()
        sharpe_ratio = pf.sharpe_ratio()
        max_drawdown = pf.max_drawdown()
        win_rate = pf.win_rate()
        profit_factor = pf.profit_factor()
        
        # 2. 提取交易记录
        trades = pf.trades.records_readable
        
        # 3. 提取资金历史
        equity_curve = pf.final_value()
        
        # 4. 组织结果
        results = {
            'total_return': total_return.mean(),
            'sharpe_ratio': sharpe_ratio.mean(),
            'max_drawdown': max_drawdown.mean(),
            'win_rate': win_rate.mean(),
            'profit_factor': profit_factor.mean(),
            'trades': trades,
            'equity_curve': equity_curve,
            'stats': pf.stats()
        }
        
        logger.info(f"回测结果: 总收益率={results['total_return']:.2%}, "
                   f"夏普比率={results['sharpe_ratio']:.2f}, "
                   f"最大回撤={results['max_drawdown']:.2%}")
        
        return results


class VectorBTBacktestEngine:
    """VectorBT向量化回测引擎"""
    
    def __init__(self, db_manager):
        """
        初始化回测引擎
        
        Args:
            db_manager: 数据库管理器实例
        """
        # db_manager: 数据库管理器，类型DBManager，必填
        self.db_manager = db_manager
        self.data_loader = VectorBTDataLoader(db_manager)
        self.signal_generator = VectorBTSignalGenerator()
        self.backtest_executor = VectorBTBacktestExecutor()
    
    def run_backtest(self, stock_codes: List[str], start_date: str, end_date: str, 
                    config: Dict) -> Dict:
        """
        运行完整的回测流程
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            config: 配置字典
        
        Returns:
            Dict: 回测结果
        """
        # stock_codes: 股票代码列表，类型List[str]，必填
        # start_date: 开始日期，类型str，必填
        # end_date: 结束日期，类型str，必填
        # config: 配置字典，类型Dict，必填
        logger.info(f"开始VectorBT回测: {len(stock_codes)}只股票, {start_date} - {end_date}")
        
        # 记录开始时间
        start_time = time.time()
        
        try:
            # 1. 加载数据
            logger.info("第1步: 加载数据")
            prices = self.data_loader.load_prices_matrix(stock_codes, start_date, end_date)
            
            if prices.empty:
                logger.error("价格数据为空")
                return {'error': '价格数据为空'}
            
            # 2. 生成信号
            logger.info("第2步: 生成信号")
            fast_window = config.get('fast_window', 10)
            slow_window = config.get('slow_window', 50)
            buy_signals, sell_signals = self.signal_generator.generate_dual_ma_signals(
                prices, fast_window, slow_window
            )
            
            # 3. 应用评分过滤（可选）
            if config.get('use_score_filter', False):
                logger.info("第3步: 应用评分过滤")
                scores = self.data_loader.load_scores_matrix(stock_codes, start_date, end_date)
                if not scores.empty:
                    score_threshold = config.get('score_threshold', 50.0)
                    buy_signals = self.signal_generator.apply_score_filter(
                        buy_signals, scores, score_threshold
                    )
            
            # 4. 执行回测
            logger.info("第4步: 执行回测")
            pf = self.backtest_executor.run_backtest(prices, buy_signals, sell_signals, config)
            
            # 5. 提取结果
            logger.info("第5步: 提取结果")
            results = self.backtest_executor.extract_results(pf, prices)
            
            # 记录执行时间
            elapsed_time = time.time() - start_time
            results['execution_time'] = elapsed_time
            
            logger.info(f"VectorBT回测完成，耗时: {elapsed_time:.2f}秒")
            
            return results
            
        except Exception as e:
            logger.error(f"回测执行失败: {str(e)}", exc_info=True)
            return {'error': str(e)}


def compare_performance(vectorbt_time: float, traditional_time: float) -> Dict:
    """
    对比性能
    
    Args:
        vectorbt_time: VectorBT执行时间
        traditional_time: 传统方式执行时间
    
    Returns:
        Dict: 性能对比结果
    """
    # vectorbt_time: VectorBT执行时间，类型float，必填
    # traditional_time: 传统方式执行时间，类型float，必填
    improvement = traditional_time / vectorbt_time if vectorbt_time > 0 else 0
    
    return {
        'vectorbt_time': vectorbt_time,
        'traditional_time': traditional_time,
        'improvement': improvement,
        'improvement_percent': (improvement - 1) * 100
    }


if __name__ == '__main__':
    """
    测试VectorBT原型
    """
    # 导入数据库管理器
    from utils.db_manager import DBManager
    
    # 初始化数据库管理器
    db_manager = DBManager()
    
    # 初始化回测引擎
    engine = VectorBTBacktestEngine(db_manager)
    
    # 获取所有股票代码（示例）
    try:
        sql = "SELECT DISTINCT code FROM stock_kline LIMIT 100"
        results = db_manager.query(sql)
        stock_codes = [r[0] for r in results]
        
        if stock_codes:
            # 配置参数
            config = {
                'init_cash': 1000000,
                'fees': 0.001,
                'fast_window': 10,
                'slow_window': 50,
                'use_score_filter': False
            }
            
            # 运行回测
            results = engine.run_backtest(
                stock_codes,
                '2024-01-01',
                '2024-06-30',
                config
            )
            
            # 打印结果
            if 'error' not in results:
                print("\n=== VectorBT回测结果 ===")
                print(f"总收益率: {results['total_return']:.2%}")
                print(f"夏普比率: {results['sharpe_ratio']:.2f}")
                print(f"最大回撤: {results['max_drawdown']:.2%}")
                print(f"胜率: {results['win_rate']:.2%}")
                print(f"利润因子: {results['profit_factor']:.2f}")
                print(f"执行时间: {results['execution_time']:.2f}秒")
            else:
                print(f"回测失败: {results['error']}")
    except Exception as e:
        logger.error(f"测试失败: {str(e)}", exc_info=True)
