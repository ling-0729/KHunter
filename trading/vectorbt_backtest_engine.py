"""
VectorBT回测引擎集成

本模块实现VectorBT回测引擎与现有系统的集成，包括：
1. VectorBTDataLoader - 数据加载
2. VectorBTBacktestEngine - 统一的回测引擎接口

特点:
- 保持API兼容性
- 保持数据库兼容性
- 保持前端兼容性
- 无缝切换
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import logging

from trading.vectorbt_strategies import VectorBTSignalGenerator
from trading.vectorbt_backtest_executor import (
    VectorBTBacktestExecutor,
    PerformanceCalculator,
    TradeRecordManager
)

# 配置日志
logger = logging.getLogger(__name__)


class VectorBTDataLoader:
    """
    VectorBT数据加载器
    
    负责从数据库加载数据到矩阵格式
    """
    
    def __init__(self, db_manager):
        """
        初始化数据加载器
        
        参数:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
    
    def load_data(self, start_date: str, end_date: str) -> Tuple[pd.DataFrame, List[str], List[str]]:
        """
        加载价格数据
        
        参数:
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        
        返回:
            prices: 价格矩阵 (行=日期, 列=股票代码)
            dates: 日期列表
            codes: 股票代码列表
        """
        try:
            logger.info(f"开始加载数据: {start_date} - {end_date}")
            
            # 1. 获取所有股票代码
            codes = self._get_all_stock_codes()
            if not codes:
                logger.warning("没有找到任何股票代码")
                return pd.DataFrame(), [], []
            
            logger.info(f"找到{len(codes)}只股票")
            
            # 2. 加载价格数据和日期信息
            prices_data = {}  # {code: {date: price}}
            dates_set = set()
            
            for code in codes:
                try:
                    # 从数据库加载该股票的K线数据
                    df = self.db_manager.read_stock(code, start_date, end_date)
                    
                    if df is not None and len(df) > 0:
                        # 提取日期和收盘价
                        dates_list = []
                        if hasattr(df.index, 'strftime'):
                            # DatetimeIndex
                            dates_list = df.index.strftime('%Y-%m-%d').tolist()
                        elif 'date' in df.columns:
                            # 如果有date列，使用date列
                            dates_list = df['date'].astype(str).tolist()
                        else:
                            # 其他情况，尝试转换索引为字符串
                            dates_list = df.index.astype(str).tolist()
                        
                        # 创建日期-价格映射
                        prices_data[code] = dict(zip(dates_list, df['close'].values))
                        dates_set.update(dates_list)
                    
                except Exception as e:
                    logger.warning(f"加载股票{code}数据失败: {str(e)}")
                    continue
            
            if not prices_data:
                logger.warning("没有加载到任何价格数据")
                return pd.DataFrame(), [], []
            
            # 3. 排序日期
            dates = sorted(list(dates_set))
            logger.info(f"加载了{len(dates)}个交易日的数据")
            
            # 4. 创建价格矩阵 - 使用日期作为索引，确保所有列长度一致
            prices_dict = {}
            for code in prices_data:
                # 为每个股票创建完整的价格序列，缺失数据用NaN填充
                prices_dict[code] = [prices_data[code].get(date, float('nan')) for date in dates]
            
            # 创建DataFrame，使用日期作为索引
            prices = pd.DataFrame(prices_dict, index=dates)
            
            # 5. 处理 NaN 值 - 使用多步骤填充确保完整性
            # 记录处理前的 NaN 数量
            nan_count_before = prices.isnull().sum().sum()
            
            # 第一步：前向填充（只使用历史数据）
            prices = prices.ffill()
            
            # 第二步：使用列中位数填充剩余 NaN（避免使用 bfill() 引入未来函数）
            for col in prices.columns:
                if prices[col].isnull().any():
                    median_val = prices[col].median()
                    if pd.notna(median_val) and median_val > 0:
                        prices[col].fillna(median_val, inplace=True)
            
            # 第三步：最后用 0 填充剩余的 NaN
            prices = prices.fillna(0)
            
            # 记录 NaN 处理统计
            nan_count_after = prices.isnull().sum().sum()
            logger.info(f"NaN 值处理完成: 处理前={nan_count_before}, 处理后={nan_count_after}")
            


            # 6. 验证数据
            if len(prices) == 0:
                logger.warning("价格矩阵为空")
                return pd.DataFrame(), [], []
            
            logger.info(f"成功加载数据: {len(prices)}行 × {len(prices.columns)}列")
            
            return prices, dates, list(prices_data.keys())
            
        except Exception as e:
            logger.error(f"加载数据时出错: {str(e)}")
            raise
    
    def load_scores(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        加载评分矩阵
        
        参数:
            start_date: 开始日期
            end_date: 结束日期
        
        返回:
            评分矩阵 (行=日期, 列=股票代码)
        """
        try:
            logger.info(f"开始加载评分数据: {start_date} - {end_date}")
            
            # 获取所有股票代码
            codes = self._get_all_stock_codes()
            if not codes:
                logger.warning("没有找到任何股票代码")
                return pd.DataFrame()
            
            # 加载评分数据
            scores_dict = {}
            
            for code in codes:
                try:
                    # 从数据库加载该股票的评分数据
                    scores = self.db_manager.read_stock_scores(code, start_date, end_date)
                    
                    if scores is not None and len(scores) > 0:
                        scores_dict[code] = scores
                    
                except Exception as e:
                    logger.warning(f"加载股票{code}评分失败: {str(e)}")
                    continue
            
            if not scores_dict:
                logger.warning("没有加载到任何评分数据")
                return pd.DataFrame()
            
            # 创建评分矩阵
            scores_matrix = pd.DataFrame(scores_dict)
            logger.info(f"成功加载评分数据: {len(scores_matrix)}行 × {len(scores_matrix.columns)}列")
            
            return scores_matrix
            
        except Exception as e:
            logger.error(f"加载评分数据时出错: {str(e)}")
            raise
    
    def load_support_levels(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        加载支撑位矩阵
        
        参数:
            start_date: 开始日期
            end_date: 结束日期
        
        返回:
            支撑位矩阵 (行=日期, 列=股票代码)
        """
        try:
            logger.info(f"开始加载支撑位数据: {start_date} - {end_date}")
            
            # 获取所有股票代码
            codes = self._get_all_stock_codes()
            if not codes:
                logger.warning("没有找到任何股票代码")
                return pd.DataFrame()
            
            # 加载支撑位数据
            support_dict = {}
            
            for code in codes:
                try:
                    # 从数据库加载该股票的支撑位数据
                    support = self.db_manager.read_support_levels(code, start_date, end_date)
                    
                    if support is not None and len(support) > 0:
                        support_dict[code] = support
                    
                except Exception as e:
                    logger.warning(f"加载股票{code}支撑位失败: {str(e)}")
                    continue
            
            if not support_dict:
                logger.warning("没有加载到任何支撑位数据")
                return pd.DataFrame()
            
            # 创建支撑位矩阵
            support_matrix = pd.DataFrame(support_dict)
            logger.info(f"成功加载支撑位数据: {len(support_matrix)}行 × {len(support_matrix.columns)}列")
            
            return support_matrix
            
        except Exception as e:
            logger.error(f"加载支撑位数据时出错: {str(e)}")
            raise
    
    def _get_all_stock_codes(self) -> List[str]:
        """
        获取所有股票代码
        
        返回:
            股票代码列表
        """
        try:
            codes = self.db_manager.list_all_stocks()
            return codes if codes else []
        except Exception as e:
            logger.error(f"获取股票代码列表失败: {str(e)}")
            return []


class VectorBTBacktestEngine:
    """
    VectorBT回测引擎
    
    统一的回测引擎接口，整合数据加载、信号生成、回测执行
    """
    
    def __init__(self, db_manager):
        """
        初始化回测引擎
        
        参数:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.data_loader = VectorBTDataLoader(db_manager)
        self.signal_generator = VectorBTSignalGenerator()
        self.backtest_executor = VectorBTBacktestExecutor()
    
    def run_backtest(self, strategy_name: str, config: Dict) -> Dict:
        """
        运行回测
        
        参数:
            strategy_name: 策略名称
            config: 配置字典，包含:
                - start_date: 开始日期 (YYYY-MM-DD)
                - end_date: 结束日期 (YYYY-MM-DD)
                - initial_capital: 初始资金 (默认1000000)
                - fees: 手续费率 (默认0.001)
                - score_threshold: 评分阈值 (默认0)
        
        返回:
            回测结果字典
        """
        try:
            logger.info(f"开始运行回测: 策略={strategy_name}")
            
            # 1. 加载数据
            logger.info("第1步: 加载数据")
            prices, dates, codes = self.data_loader.load_data(
                config.get('start_date', '2024-01-01'),
                config.get('end_date', '2024-12-31')
            )
            
            if prices.empty:
                logger.error("数据加载失败")
                raise ValueError("无法加载数据")
            
            logger.info(f"数据加载完成: {len(prices)}行 × {len(prices.columns)}列")
            
            # 2. 生成信号
            logger.info("第2步: 生成交易信号")
            
            # 准备信号生成的额外参数
            signal_kwargs = {}
            
            # 规范化策略名称用于比较
            from trading.vectorbt_strategies import StrategyFactory
            normalized_name = StrategyFactory._normalize_strategy_name(strategy_name)
            
            # 如果是支撑位策略，加载支撑位数据
            if normalized_name == 'support_level':
                support_levels = self.data_loader.load_support_levels(
                    config.get('start_date', '2024-01-01'),
                    config.get('end_date', '2024-12-31')
                )
                signal_kwargs['support_levels'] = support_levels
                logger.info(f"加载支撑位数据: {support_levels.shape}")
            
            # 如果是组合策略，加载评分数据
            if normalized_name == 'combined':
                scores = self.data_loader.load_scores(
                    config.get('start_date', '2024-01-01'),
                    config.get('end_date', '2024-12-31')
                )
                signal_kwargs['scores'] = scores
                logger.info(f"加载评分数据: {scores.shape}")
            
            buy_signals, sell_signals = self.signal_generator.generate_signals(
                strategy_name,
                prices,
                config,
                **signal_kwargs
            )
            
            logger.info(f"信号生成完成: 买入信号数={buy_signals.sum().sum()}, 卖出信号数={sell_signals.sum().sum()}")
            
            # 3. 执行回测
            logger.info("第3步: 执行VectorBT回测")
            portfolio = self.backtest_executor.run_backtest(
                prices,
                buy_signals,
                sell_signals,
                {
                    'initial_capital': config.get('initial_capital', 1000000),
                    'fees': config.get('fees', 0.001),
                    'freq': 'D'
                }
            )
            
            logger.info("回测执行完成")
            
            # 4. 提取结果
            logger.info("第4步: 提取回测结果")
            results = self.backtest_executor.extract_results(
                portfolio,
                prices,
                dates,
                codes,
                config
            )
            
            logger.info("结果提取完成")
            
            # 5. 格式化结果
            logger.info("第5步: 格式化结果")
            formatted_results = self._format_results(
                results,
                strategy_name,
                config,
                dates
            )
            
            logger.info("回测完成")
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"运行回测时出错: {str(e)}")
            raise
    
    def _format_results(self, results: Dict, strategy_name: str, config: Dict, dates: List[str]) -> Dict:
        """
        格式化结果以保持兼容性
        
        参数:
            results: VectorBT回测结果
            strategy_name: 策略名称
            config: 配置字典
            dates: 日期列表
        
        返回:
            格式化后的结果字典
        """
        try:
            # 提取性能指标
            performance = results.get('performance', {})
            trades = results.get('trades', [])
            capital_history = results.get('capital_history', [])
            equity_curve = results.get('equity_curve', [])
            
            # 计算最终资金
            if capital_history:
                final_capital = capital_history[-1].get('capital', config.get('initial_capital', 1000000))
            else:
                final_capital = config.get('initial_capital', 1000000)
            
            # 格式化结果
            formatted_results = {
                'strategy_name': strategy_name,
                'start_date': config.get('start_date', ''),
                'end_date': config.get('end_date', ''),
                'initial_capital': config.get('initial_capital', 1000000),
                'final_capital': final_capital,
                'performance': {
                    'total_return': performance.get('total_return', 0),
                    'annual_return': performance.get('annual_return', 0),
                    'sharpe_ratio': performance.get('sharpe_ratio', 0),
                    'sortino_ratio': performance.get('sortino_ratio', 0),
                    'calmar_ratio': performance.get('calmar_ratio', 0),
                    'max_drawdown': performance.get('max_drawdown', 0),
                    'drawdown_duration': performance.get('drawdown_duration', 0),
                    'win_rate': performance.get('win_rate', 0),
                    'profit_factor': performance.get('profit_factor', 0),
                    'payoff_ratio': performance.get('payoff_ratio', 0),
                    'trades_count': performance.get('trades_count', 0),
                    'avg_trade_return': performance.get('avg_trade_return', 0),
                    'best_trade': performance.get('best_trade', 0),
                    'worst_trade': performance.get('worst_trade', 0),
                    'consecutive_wins': performance.get('consecutive_wins', 0),
                    'consecutive_losses': performance.get('consecutive_losses', 0),
                    'recovery_factor': performance.get('recovery_factor', 0)
                },
                'trades': trades,
                'capital_history': capital_history,
                'equity_curve': equity_curve,
                'dates': dates
            }
            
            logger.info("结果格式化完成")
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"格式化结果时出错: {str(e)}")
            raise
