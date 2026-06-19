"""
VectorBT回测执行引擎

本模块实现VectorBT回测的执行和结果提取功能，包括：
1. VectorBTBacktestExecutor - 回测执行和结果提取
2. PerformanceCalculator - 性能指标计算
3. TradeRecordManager - 交易记录管理

性能目标:
- 回测执行时间: < 5秒
- 性能指标计算: < 1秒
- 交易记录提取: < 1秒
- 总处理时间: < 10秒
"""

import pandas as pd
import numpy as np
import vectorbt as vbt
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import logging

# 配置日志
logger = logging.getLogger(__name__)


class PerformanceCalculator:
    """
    性能指标计算器
    
    计算15+个性能指标，包括：
    - 收益率指标: 总收益率、年化收益率、平均交易收益
    - 风险指标: 最大回撤、夏普比率、索提诺比率、卡玛比率
    - 交易指标: 胜率、利润因子、盈亏比、交易次数
    - 其他指标: 恢复因子、连胜/连败次数等
    """
    
    # 无风险利率 (年化)
    RISK_FREE_RATE = 0.02
    
    # 交易日数 (年)
    TRADING_DAYS_PER_YEAR = 252
    
    def __init__(self):
        """初始化性能指标计算器"""
        pass
    
    def calculate_all_metrics(self, portfolio: vbt.Portfolio, 
                             prices: pd.DataFrame,
                             trades_list: List[Dict]) -> Dict:
        """
        计算所有性能指标
        
        参数:
            portfolio: VectorBT Portfolio对象
            prices: 价格矩阵
            trades_list: 交易记录列表
        
        返回:
            包含所有性能指标的字典
        """
        # 初始化指标字典
        metrics = {}
        
        try:
            # 1. 收益率指标
            metrics['total_return'] = self._calculate_total_return(portfolio)
            metrics['annual_return'] = self._calculate_annual_return(portfolio)
            metrics['avg_trade_return'] = self._calculate_avg_trade_return(trades_list)
            
            # 2. 风险指标
            metrics['max_drawdown'] = self._calculate_max_drawdown(portfolio)
            metrics['sharpe_ratio'] = self._calculate_sharpe_ratio(portfolio)
            metrics['sortino_ratio'] = self._calculate_sortino_ratio(portfolio)
            metrics['calmar_ratio'] = self._calculate_calmar_ratio(portfolio)
            
            # 3. 交易指标
            metrics['win_rate'] = self._calculate_win_rate(trades_list)
            metrics['profit_factor'] = self._calculate_profit_factor(trades_list)
            metrics['payoff_ratio'] = self._calculate_payoff_ratio(trades_list)
            metrics['trades_count'] = len(trades_list)
            
            # 4. 其他指标
            metrics['recovery_factor'] = self._calculate_recovery_factor(
                portfolio, trades_list
            )
            metrics['consecutive_wins'] = self._calculate_consecutive_wins(trades_list)
            metrics['consecutive_losses'] = self._calculate_consecutive_losses(trades_list)
            metrics['drawdown_duration'] = self._calculate_drawdown_duration(portfolio)
            metrics['best_trade'] = self._calculate_best_trade(trades_list)
            metrics['worst_trade'] = self._calculate_worst_trade(trades_list)
            
            logger.info(f"成功计算所有性能指标，共{len(metrics)}个")
            
        except Exception as e:
            logger.error(f"计算性能指标时出错: {str(e)}")
            raise
        
        return metrics
    
    def _calculate_total_return(self, portfolio: vbt.Portfolio) -> float:
        """计算总收益率 (%)"""
        try:
            total_return = portfolio.total_return()
            # total_return是Series，取平均值
            if isinstance(total_return, pd.Series):
                total_return = total_return.mean()
            return float(total_return * 100) if total_return is not None else 0.0
        except Exception as e:
            logger.warning(f"计算总收益率失败: {str(e)}")
            return 0.0
    
    def _calculate_annual_return(self, portfolio: vbt.Portfolio) -> float:
        """计算年化收益率 (%)"""
        try:
            # 获取总收益率
            total_return = portfolio.total_return()
            if isinstance(total_return, pd.Series):
                total_return = total_return.mean()
            
            if total_return is None or total_return == 0:
                return 0.0
            
            # 获取交易日数
            trading_days = len(portfolio.close)
            years = trading_days / self.TRADING_DAYS_PER_YEAR
            
            if years <= 0:
                return 0.0
            
            # 计算年化收益率
            annual_return = ((total_return + 1) ** (1 / years) - 1) * 100
            return float(annual_return)
        except Exception as e:
            logger.warning(f"计算年化收益率失败: {str(e)}")
            return 0.0
    
    def _calculate_avg_trade_return(self, trades_list: List[Dict]) -> float:
        """计算平均交易收益 (%)"""
        try:
            if not trades_list or len(trades_list) == 0:
                return 0.0
            
            # 计算所有交易的收益率
            returns = [t.get('return_rate', 0) for t in trades_list]
            avg_return = np.mean(returns) if returns else 0.0
            
            return float(avg_return)
        except Exception as e:
            logger.warning(f"计算平均交易收益失败: {str(e)}")
            return 0.0
    
    def _calculate_max_drawdown(self, portfolio: vbt.Portfolio) -> float:
        """计算最大回撤 (%)"""
        try:
            max_drawdown = portfolio.max_drawdown()
            # max_drawdown是Series，取平均值
            if isinstance(max_drawdown, pd.Series):
                max_drawdown = max_drawdown.mean()
            return float(max_drawdown * 100) if max_drawdown is not None else 0.0
        except Exception as e:
            logger.warning(f"计算最大回撤失败: {str(e)}")
            return 0.0
    
    def _calculate_sharpe_ratio(self, portfolio: vbt.Portfolio) -> float:
        """计算夏普比率"""
        try:
            sharpe_ratio = portfolio.sharpe_ratio()
            # sharpe_ratio是Series，取平均值
            if isinstance(sharpe_ratio, pd.Series):
                sharpe_ratio = sharpe_ratio.mean()
            return float(sharpe_ratio) if sharpe_ratio is not None else 0.0
        except Exception as e:
            logger.warning(f"计算夏普比率失败: {str(e)}")
            return 0.0
    
    def _calculate_sortino_ratio(self, portfolio: vbt.Portfolio) -> float:
        """计算索提诺比率"""
        try:
            sortino_ratio = portfolio.sortino_ratio()
            # sortino_ratio是Series，取平均值
            if isinstance(sortino_ratio, pd.Series):
                sortino_ratio = sortino_ratio.mean()
            return float(sortino_ratio) if sortino_ratio is not None else 0.0
        except Exception as e:
            logger.warning(f"计算索提诺比率失败: {str(e)}")
            return 0.0
    
    def _calculate_calmar_ratio(self, portfolio: vbt.Portfolio) -> float:
        """计算卡玛比率"""
        try:
            calmar_ratio = portfolio.calmar_ratio()
            # calmar_ratio是Series，取平均值
            if isinstance(calmar_ratio, pd.Series):
                calmar_ratio = calmar_ratio.mean()
            return float(calmar_ratio) if calmar_ratio is not None else 0.0
        except Exception as e:
            logger.warning(f"计算卡玛比率失败: {str(e)}")
            return 0.0
    
    def _calculate_win_rate(self, trades_list: List[Dict]) -> float:
        """计算胜率 (%)"""
        try:
            if not trades_list or len(trades_list) == 0:
                return 0.0
            
            # 计算盈利交易数
            winning_trades = len([t for t in trades_list if t.get('profit', 0) > 0])
            win_rate = (winning_trades / len(trades_list)) * 100
            
            return float(win_rate)
        except Exception as e:
            logger.warning(f"计算胜率失败: {str(e)}")
            return 0.0
    
    def _calculate_profit_factor(self, trades_list: List[Dict]) -> float:
        """计算利润因子"""
        try:
            if not trades_list or len(trades_list) == 0:
                return 0.0
            
            # 计算总利润和总亏损
            gross_profit = sum([t.get('profit', 0) for t in trades_list if t.get('profit', 0) > 0])
            gross_loss = abs(sum([t.get('profit', 0) for t in trades_list if t.get('profit', 0) < 0]))
            
            if gross_loss == 0:
                return float(gross_profit) if gross_profit > 0 else 0.0
            
            profit_factor = gross_profit / gross_loss
            return float(profit_factor)
        except Exception as e:
            logger.warning(f"计算利润因子失败: {str(e)}")
            return 0.0
    
    def _calculate_payoff_ratio(self, trades_list: List[Dict]) -> float:
        """计算盈亏比"""
        try:
            if not trades_list or len(trades_list) == 0:
                return 0.0
            
            # 分离盈利和亏损交易
            winning_trades = [t for t in trades_list if t.get('profit', 0) > 0]
            losing_trades = [t for t in trades_list if t.get('profit', 0) < 0]
            
            if not winning_trades or not losing_trades:
                return 0.0
            
            # 计算平均盈利和平均亏损
            avg_win = np.mean([t.get('profit', 0) for t in winning_trades])
            avg_loss = abs(np.mean([t.get('profit', 0) for t in losing_trades]))
            
            if avg_loss == 0:
                return 0.0
            
            payoff_ratio = avg_win / avg_loss
            return float(payoff_ratio)
        except Exception as e:
            logger.warning(f"计算盈亏比失败: {str(e)}")
            return 0.0
    
    def _calculate_recovery_factor(self, portfolio: vbt.Portfolio, 
                                   trades_list: List[Dict]) -> float:
        """计算恢复因子"""
        try:
            if not trades_list or len(trades_list) == 0:
                return 0.0
            
            # 计算总利润
            total_profit = sum([t.get('profit', 0) for t in trades_list])
            
            # 计算最大回撤
            max_drawdown = portfolio.max_drawdown()
            if isinstance(max_drawdown, pd.Series):
                max_drawdown = max_drawdown.mean()
            
            if max_drawdown is None or max_drawdown == 0:
                return 0.0
            
            # 获取初始资金
            initial_capital = portfolio.init_cash
            max_drawdown_amount = initial_capital * max_drawdown
            
            if max_drawdown_amount == 0:
                return 0.0
            
            recovery_factor = total_profit / max_drawdown_amount
            return float(recovery_factor)
        except Exception as e:
            logger.warning(f"计算恢复因子失败: {str(e)}")
            return 0.0
    
    def _calculate_consecutive_wins(self, trades_list: List[Dict]) -> int:
        """计算最大连胜次数"""
        try:
            if not trades_list or len(trades_list) == 0:
                return 0
            
            # 获取交易结果序列
            results = [1 if t.get('profit', 0) > 0 else 0 for t in trades_list]
            
            # 计算最大连胜
            max_consecutive = 0
            current_consecutive = 0
            
            for result in results:
                if result == 1:
                    current_consecutive += 1
                    max_consecutive = max(max_consecutive, current_consecutive)
                else:
                    current_consecutive = 0
            
            return int(max_consecutive)
        except Exception as e:
            logger.warning(f"计算最大连胜失败: {str(e)}")
            return 0
    
    def _calculate_consecutive_losses(self, trades_list: List[Dict]) -> int:
        """计算最大连败次数"""
        try:
            if not trades_list or len(trades_list) == 0:
                return 0
            
            # 获取交易结果序列
            results = [1 if t.get('profit', 0) > 0 else 0 for t in trades_list]
            
            # 计算最大连败
            max_consecutive = 0
            current_consecutive = 0
            
            for result in results:
                if result == 0:
                    current_consecutive += 1
                    max_consecutive = max(max_consecutive, current_consecutive)
                else:
                    current_consecutive = 0
            
            return int(max_consecutive)
        except Exception as e:
            logger.warning(f"计算最大连败失败: {str(e)}")
            return 0
    
    def _calculate_drawdown_duration(self, portfolio: vbt.Portfolio) -> int:
        """计算最大回撤持续天数"""
        try:
            # 获取资产价值曲线
            asset_value = portfolio.asset_value()
            if asset_value is None or len(asset_value) == 0:
                return 0
            
            # 如果是Series，取第一列
            if isinstance(asset_value, pd.Series):
                equity = asset_value
            else:
                equity = asset_value.iloc[:, 0]
            
            # 计算回撤
            running_max = equity.expanding().max()
            drawdown = (equity - running_max) / running_max
            
            # 找到最大回撤的持续时间
            max_duration = 0
            current_duration = 0
            
            for dd in drawdown:
                if dd < 0:
                    current_duration += 1
                    max_duration = max(max_duration, current_duration)
                else:
                    current_duration = 0
            
            return int(max_duration)
        except Exception as e:
            logger.warning(f"计算回撤持续时间失败: {str(e)}")
            return 0
    
    def _calculate_best_trade(self, trades_list: List[Dict]) -> float:
        """计算最佳交易收益 (%)"""
        try:
            if not trades_list or len(trades_list) == 0:
                return 0.0
            
            # 获取所有交易的收益率
            returns = [t.get('return_rate', 0) for t in trades_list]
            best_trade = max(returns) if returns else 0.0
            
            return float(best_trade)
        except Exception as e:
            logger.warning(f"计算最佳交易失败: {str(e)}")
            return 0.0
    
    def _calculate_worst_trade(self, trades_list: List[Dict]) -> float:
        """计算最差交易收益 (%)"""
        try:
            if not trades_list or len(trades_list) == 0:
                return 0.0
            
            # 获取所有交易的收益率
            returns = [t.get('return_rate', 0) for t in trades_list]
            worst_trade = min(returns) if returns else 0.0
            
            return float(worst_trade)
        except Exception as e:
            logger.warning(f"计算最差交易失败: {str(e)}")
            return 0.0


class TradeRecordManager:
    """
    交易记录管理器
    
    负责从VectorBT Portfolio对象中提取交易记录和资金历史
    """
    
    def __init__(self):
        """初始化交易记录管理器"""
        pass
    
    def extract_trades(self, portfolio: vbt.Portfolio,
                      prices: pd.DataFrame,
                      dates: List[str],
                      codes: List[str]) -> List[Dict]:
        """
        提取交易记录
        
        参数:
            portfolio: VectorBT Portfolio对象
            prices: 价格矩阵
            dates: 日期列表
            codes: 股票代码列表
        
        返回:
            交易记录列表，每条记录包含:
            - trade_id: 交易ID
            - code: 股票代码
            - entry_date: 买入日期
            - entry_price: 买入价格
            - exit_date: 卖出日期
            - exit_price: 卖出价格
            - quantity: 交易数量
            - entry_fee: 买入手续费
            - exit_fee: 卖出手续费
            - profit: 利润
            - return_rate: 收益率 (%)
            - holding_days: 持仓天数
        """
        trades_list = []
        
        try:
            # 获取VectorBT的交易记录
            trades = portfolio.trades
            if trades is None or len(trades.records) == 0:
                logger.info("没有交易记录")
                return trades_list
            
            # 遍历每笔交易
            for idx, row in trades.records.iterrows():
                try:
                    # 提取交易信息
                    entry_idx = int(row['entry_idx'])
                    exit_idx = int(row['exit_idx'])
                    col_idx = int(row['col'])
                    
                    # 获取日期和股票代码
                    entry_date = dates[entry_idx] if entry_idx < len(dates) else None
                    exit_date = dates[exit_idx] if exit_idx < len(dates) else None
                    code = codes[col_idx] if col_idx < len(codes) else None
                    
                    if not entry_date or not exit_date or not code:
                        continue
                    
                    # 获取价格
                    entry_price = float(prices.iloc[entry_idx, col_idx])
                    exit_price = float(prices.iloc[exit_idx, col_idx])
                    
                    # 获取交易数量和手续费
                    quantity = float(row['size'])
                    entry_fee = float(row['entry_fees'])
                    exit_fee = float(row['exit_fees'])
                    
                    # 计算利润和收益率
                    profit = (exit_price - entry_price) * quantity - entry_fee - exit_fee
                    return_rate = (profit / (entry_price * quantity)) * 100 if entry_price > 0 else 0
                    
                    # 计算持仓天数
                    holding_days = exit_idx - entry_idx
                    
                    # 创建交易记录
                    trade_record = {
                        'trade_id': int(row['id']),
                        'code': code,
                        'entry_date': entry_date,
                        'entry_price': entry_price,
                        'exit_date': exit_date,
                        'exit_price': exit_price,
                        'quantity': quantity,
                        'entry_fee': entry_fee,
                        'exit_fee': exit_fee,
                        'profit': profit,
                        'return_rate': return_rate,
                        'holding_days': holding_days
                    }
                    
                    trades_list.append(trade_record)
                    
                except Exception as e:
                    logger.warning(f"提取第{idx}笔交易时出错: {str(e)}")
                    continue
            
            logger.info(f"成功提取{len(trades_list)}笔交易记录")
            
        except Exception as e:
            logger.error(f"提取交易记录时出错: {str(e)}")
            raise
        
        return trades_list
    
    def extract_capital_history(self, portfolio: vbt.Portfolio,
                               dates: List[str]) -> List[Dict]:
        """
        提取资金历史
        
        参数:
            portfolio: VectorBT Portfolio对象
            dates: 日期列表
        
        返回:
            资金历史列表，每条记录包含:
            - date: 日期
            - capital: 当前资金
            - equity: 权益
            - cash: 现金
            - position_value: 持仓价值
        """
        capital_history = []
        
        try:
            # 获取资产价值曲线
            asset_value = portfolio.asset_value()
            if asset_value is None or len(asset_value) == 0:
                logger.warning("无法获取资产价值曲线")
                return capital_history
            
            # 如果是Series，转换为DataFrame
            if isinstance(asset_value, pd.Series):
                asset_value = asset_value.to_frame()
            
            # 获取现金曲线
            cash = portfolio.cash()
            if cash is None:
                cash = pd.Series([portfolio.init_cash] * len(asset_value))
            
            # 如果cash是DataFrame，取第一列
            if isinstance(cash, pd.DataFrame):
                cash = cash.iloc[:, 0]
            
            # 遍历每个交易日
            for i, date in enumerate(dates):
                if i >= len(asset_value):
                    break
                
                try:
                    # 获取该日期的数据
                    if isinstance(asset_value, pd.DataFrame):
                        eq_value = float(asset_value.iloc[i, 0])
                    else:
                        eq_value = float(asset_value.iloc[i])
                    
                    if isinstance(cash, pd.Series):
                        cash_value = float(cash.iloc[i])
                    else:
                        cash_value = float(cash[i])
                    
                    position_value = eq_value - cash_value
                    
                    # 创建资金历史记录
                    capital_record = {
                        'date': date,
                        'capital': eq_value,
                        'equity': eq_value,
                        'cash': cash_value,
                        'position_value': position_value
                    }
                    
                    capital_history.append(capital_record)
                    
                except Exception as e:
                    logger.warning(f"提取{date}的资金数据时出错: {str(e)}")
                    continue
            
            logger.info(f"成功提取{len(capital_history)}条资金历史记录")
            
        except Exception as e:
            logger.error(f"提取资金历史时出错: {str(e)}")
            raise
        
        return capital_history


class VectorBTBacktestExecutor:
    """
    VectorBT回测执行器
    
    负责执行VectorBT回测并提取结果
    """
    
    def __init__(self):
        """初始化回测执行器"""
        self.performance_calculator = PerformanceCalculator()
        self.trade_record_manager = TradeRecordManager()
    
    def run_backtest(self, prices: pd.DataFrame,
                    buy_signals: pd.DataFrame,
                    sell_signals: pd.DataFrame,
                    config: Dict) -> vbt.Portfolio:
        """
        执行VectorBT回测
        
        参数:
            prices: 价格矩阵 (行=日期, 列=股票代码)
            buy_signals: 买入信号矩阵 (布尔值)
            sell_signals: 卖出信号矩阵 (布尔值)
            config: 配置字典，包含:
                - initial_capital: 初始资金 (默认1000000)
                - fees: 手续费率 (默认0.001)
                - slippage: 滑点 (默认0)
                - freq: 频率 (默认'D')
        
        返回:
            vbt.Portfolio: VectorBT Portfolio对象
        """
        try:
            # 提取配置参数
            initial_capital = config.get('initial_capital', 1000000)
            fees = config.get('fees', 0.001)
            slippage = config.get('slippage', 0)
            freq = config.get('freq', 'D')
            
            logger.info(f"开始执行VectorBT回测，初始资金: {initial_capital}, 手续费: {fees}")
            
            # 创建VectorBT Portfolio对象
            portfolio = vbt.Portfolio.from_signals(
                close=prices,
                entries=buy_signals,
                exits=sell_signals,
                init_cash=initial_capital,
                fees=fees,
                freq=freq
            )
            
            logger.info("VectorBT回测执行完成")
            
            return portfolio
            
        except Exception as e:
            logger.error(f"执行VectorBT回测时出错: {str(e)}")
            raise
    
    def extract_results(self, portfolio: vbt.Portfolio,
                       prices: pd.DataFrame,
                       dates: List[str],
                       codes: List[str],
                       config: Dict) -> Dict:
        """
        提取回测结果
        
        参数:
            portfolio: VectorBT Portfolio对象
            prices: 价格矩阵
            dates: 日期列表
            codes: 股票代码列表
            config: 配置字典
        
        返回:
            包含以下内容的字典:
            - performance: 性能指标
            - trades: 交易记录
            - capital_history: 资金历史
            - equity_curve: 权益曲线
        """
        try:
            logger.info("开始提取回测结果")
            
            # 1. 提取交易记录
            trades_list = self.trade_record_manager.extract_trades(
                portfolio, prices, dates, codes
            )
            
            # 2. 提取资金历史
            capital_history = self.trade_record_manager.extract_capital_history(
                portfolio, dates
            )
            
            # 3. 计算性能指标
            performance = self.performance_calculator.calculate_all_metrics(
                portfolio, prices, trades_list
            )
            
            # 4. 提取权益曲线
            equity_curve = self._extract_equity_curve(portfolio, dates)
            
            # 5. 组织结果
            results = {
                'performance': performance,
                'trades': trades_list,
                'capital_history': capital_history,
                'equity_curve': equity_curve,
                'config': config
            }
            
            logger.info("成功提取回测结果")
            
            return results
            
        except Exception as e:
            logger.error(f"提取回测结果时出错: {str(e)}")
            raise
    
    def _extract_equity_curve(self, portfolio: vbt.Portfolio,
                             dates: List[str]) -> List[Dict]:
        """
        提取权益曲线
        
        参数:
            portfolio: VectorBT Portfolio对象
            dates: 日期列表
        
        返回:
            权益曲线列表
        """
        equity_curve = []
        
        try:
            # 获取资产价值数据
            asset_value = portfolio.asset_value()
            if asset_value is None or len(asset_value) == 0:
                logger.warning("无法获取资产价值数据")
                return equity_curve
            
            # 如果是Series，转换为DataFrame
            if isinstance(asset_value, pd.Series):
                asset_value = asset_value.to_frame()
            
            # 遍历每个交易日
            for i, date in enumerate(dates):
                if i >= len(asset_value):
                    break
                
                try:
                    # 获取该日期的资产价值
                    if isinstance(asset_value, pd.DataFrame):
                        eq_value = float(asset_value.iloc[i, 0])
                    else:
                        eq_value = float(asset_value.iloc[i])
                    
                    equity_curve.append({
                        'date': date,
                        'equity': eq_value
                    })
                except Exception as e:
                    logger.warning(f"提取{date}的权益数据时出错: {str(e)}")
                    continue
            
            logger.info(f"成功提取{len(equity_curve)}条权益曲线数据")
            
        except Exception as e:
            logger.error(f"提取权益曲线时出错: {str(e)}")
            raise
        
        return equity_curve
