# -*- coding: utf-8 -*-
"""
回测数据访问对象

提供回测相关的数据库操作，包括：
- 回测配置的CRUD操作
- 回测结果的CRUD操作
- 交易记录的CRUD操作
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from utils.db_manager import DBManager

# 配置日志
logger = logging.getLogger(__name__)


class BacktestDAO:
    """回测数据访问对象"""
    
    def __init__(self, db_path: str = "data/stock_selection.db"):
        """
        初始化回测数据访问对象
        
        Args:
            db_path: 数据库路径
        """
        from utils.global_db import get_global_db
        self.db = get_global_db()
    
    # ==================== 回测配置相关操作 ====================
    
    def save_config(self, config: Dict) -> int:
        """
        保存回测配置（只保留一条记录，全局生效）
        
        Args:
            config: 回测配置字典
            
        Returns:
            配置ID
        """
        try:
            # 检查是否已有配置记录
            existing_config = self.db.query_one('SELECT id FROM backtest_config LIMIT 1')
            
            # 准备更新数据
            update_data = {
                'config_name': config.get('config_name', '默认配置'),
                'score_threshold': config.get('score_threshold', 60),
                'hold_period': config.get('hold_period', 10),
                'stop_loss': config.get('stop_loss', -5),
                'take_profit': config.get('take_profit', 15),
                'initial_capital': config.get('initial_capital', 1000000),
                'buy_amount': config.get('buy_amount', 100000),
                'max_daily_buys': config.get('max_daily_buys', 5),
                'buy_point_lower': config.get('buy_point_lower', -1),
                'buy_point_upper': config.get('buy_point_upper', 3)
            }
            
            if existing_config:
                # 更新现有配置
                config_id = existing_config['id']
                self.db.update('backtest_config', update_data, {'id': config_id})
            else:
                # 创建新配置
                update_data['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                config_id = self.db.insert('backtest_config', update_data)
            
            return config_id
            
        except Exception as e:
            logger.error(f"保存回测配置失败: {str(e)}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return 0
    
    def get_config(self, config_id: int) -> Optional[Dict]:
        """
        获取回测配置
        
        Args:
            config_id: 配置ID
            
        Returns:
            回测配置字典
        """
        try:
            sql = """
                SELECT * FROM backtest_config WHERE id = ?
            """
            result = self.db.query_one(sql, (config_id,))
            if result:
                return dict(result)
            return None
            
        except Exception as e:
            logger.error(f"获取回测配置失败: {str(e)}")
            return None
    
    def get_config_by_id(self, config_id: int) -> Optional[Dict]:
        """
        根据ID获取回测配置
        
        Args:
            config_id: 配置ID
            
        Returns:
            回测配置字典
        """
        return self.get_config(config_id)
    
    def get_all_configs(self) -> List[Dict]:
        """
        获取所有回测配置
        
        Returns:
            回测配置列表
        """
        try:
            sql = """
                SELECT * FROM backtest_config ORDER BY id DESC
            """
            results = self.db.query(sql)
            return [dict(result) for result in results]
            
        except Exception as e:
            logger.error(f"获取所有回测配置失败: {str(e)}")
            return []
    
    def update_config(self, config_id: int, config: Dict) -> bool:
        """
        更新回测配置
        
        Args:
            config_id: 配置ID
            config: 回测配置字典
            
        Returns:
            是否更新成功
        """
        try:
            sql = """
                UPDATE backtest_config SET
                    config_name = ?,
                    score_threshold = ?,
                    hold_period = ?,
                    stop_loss = ?,
                    take_profit = ?,
                    initial_capital = ?,
                    buy_amount = ?,
                    max_daily_buys = ?,
                    buy_point_lower = ?,
                    buy_point_upper = ?
                WHERE id = ?
            """
            params = (
                config.get('config_name', ''),
                config.get('score_threshold', 60),
                config.get('hold_period', 10),
                config.get('stop_loss', -5),
                config.get('take_profit', 15),
                config.get('initial_capital', 1000000),
                config.get('buy_amount', 100000),
                config.get('max_daily_buys', 5),
                config.get('buy_point_lower', -1),
                config.get('buy_point_upper', 3),
                config_id
            )
            
            self.db.execute(sql, params)
            self.db.connect().commit()
            return True
            
        except Exception as e:
            logger.error(f"更新回测配置失败: {str(e)}")
            return False
    
    def delete_config(self, config_id: int) -> bool:
        """
        删除回测配置
        
        Args:
            config_id: 配置ID
            
        Returns:
            是否删除成功
        """
        try:
            sql = "DELETE FROM backtest_config WHERE id = ?"
            self.db.execute(sql, (config_id,))
            self.db.connect().commit()
            return True
            
        except Exception as e:
            logger.error(f"删除回测配置失败: {str(e)}")
            return False
    
    # ==================== 回测结果相关操作 ====================
    
    def save_result(self, result: Dict) -> int:
        """
        保存回测结果
        
        Args:
            result: 回测结果字典
            
        Returns:
            结果ID
        """
        try:
            logger.info(f"开始保存回测结果: {result}")
            
            # 检查是否有必要的字段
            if not result:
                logger.error("回测结果为空")
                return 0
            
            # 使用DBManager的insert方法，它已经处理了事务和lastrowid的获取
            result_id = self.db.insert('backtest_result', {
                'strategy_name': result.get('strategy_name', ''),
                'support_level_method': result.get('support_level_method', ''),
                'backtest_name': result.get('backtest_name', ''),
                'start_date': result.get('start_date', ''),
                'end_date': result.get('end_date', ''),
                'total_trades': result.get('total_trades', 0),
                'win_trades': result.get('win_trades', 0),
                'loss_trades': result.get('loss_trades', 0),
                'win_rate': result.get('win_rate', 0),
                'avg_return': result.get('avg_return', 0),
                'total_return': result.get('total_return', 0),
                'max_return': result.get('max_return', 0),
                'min_return': result.get('min_return', 0),
                'profit_factor': result.get('profit_factor', 0),
                'profit_loss_ratio': result.get('profit_loss_ratio', 0),
                'max_drawdown': result.get('max_drawdown', 0),
                'sharpe_ratio': result.get('sharpe_ratio', 0),
                'initial_capital': result.get('initial_capital', 1000000),
                'final_capital': result.get('final_capital', 1000000),
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            logger.info(f"保存回测结果成功，result_id: {result_id}")
            return result_id
            
        except Exception as e:
            logger.error(f"保存回测结果失败: {str(e)}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return 0
    
    def save_equity_curve(self, result_id: int, equity_curve: List[Dict]) -> bool:
        """
        保存收益曲线数据
        
        Args:
            result_id: 回测结果ID
            equity_curve: 收益曲线数据
            
        Returns:
            是否保存成功
        """
        try:
            if not equity_curve:
                return True
            
            sql = """
                INSERT INTO backtest_equity_curve (
                    result_id, date, capital, return_rate
                ) VALUES (?, ?, ?, ?)
            """
            
            params_list = []
            for item in equity_curve:
                params = (
                    result_id,
                    item.get('date', ''),
                    item.get('capital', 0),
                    item.get('return_rate', 0)
                )
                params_list.append(params)
            
            conn = self.db.connect()
            cursor = conn.cursor()
            
            try:
                cursor.executemany(sql, params_list)
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                logger.error(f"批量保存收益曲线失败: {str(e)}")
                return False
            
        except Exception as e:
            logger.error(f"保存收益曲线失败: {str(e)}")
            return False
    
    def get_equity_curve(self, result_id: int) -> List[Dict]:
        """
        获取收益曲线数据
        
        Args:
            result_id: 回测结果ID
            
        Returns:
            收益曲线数据列表
        """
        try:
            sql = """
                SELECT date, capital, return_rate 
                FROM backtest_equity_curve 
                WHERE result_id = ? 
                ORDER BY date ASC
            """
            results = self.db.query(sql, (result_id,))
            return [dict(result) for result in results]
            
        except Exception as e:
            logger.error(f"获取收益曲线失败: {str(e)}")
            return []
    
    def get_result(self, result_id: int) -> Optional[Dict]:
        """
        获取回测结果
        
        Args:
            result_id: 结果ID
            
        Returns:
            回测结果字典
        """
        try:
            sql = """
                SELECT * FROM backtest_result WHERE id = ?
            """
            result = self.db.query_one(sql, (result_id,))
            if result:
                return dict(result)
            return None
            
        except Exception as e:
            logger.error(f"获取回测结果失败: {str(e)}")
            return None
    
    def get_result_by_id(self, result_id: int) -> Optional[Dict]:
        """
        根据ID获取回测结果
        
        Args:
            result_id: 结果ID
            
        Returns:
            回测结果字典
        """
        return self.get_result(result_id)
    
    def get_all_results(self) -> List[Dict]:
        """
        获取所有回测结果
        
        Returns:
            回测结果列表
        """
        try:
            sql = """
                SELECT * FROM backtest_result ORDER BY id DESC
            """
            results = self.db.query(sql)
            return [dict(result) for result in results]
            
        except Exception as e:
            logger.error(f"获取所有回测结果失败: {str(e)}")
            return []
    
    def get_results_by_strategy(self, strategy_name: str) -> List[Dict]:
        """
        根据策略名称获取回测结果
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            回测结果列表
        """
        try:
            sql = """
                SELECT * FROM backtest_result 
                WHERE strategy_name = ? 
                ORDER BY id DESC
            """
            results = self.db.query(sql, (strategy_name,))
            return [dict(result) for result in results]
            
        except Exception as e:
            logger.error(f"根据策略获取回测结果失败: {str(e)}")
            return []
    
    def get_result_by_strategy_and_dates(self, strategy_name: str, start_date: str, end_date: str) -> Optional[Dict]:
        """
        根据策略名称和日期范围获取回测结果
        用于检查是否已存在相同参数的回测结果
        
        Args:
            strategy_name: 策略名称
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            匹配的回测结果字典，如果不存在则返回None
        """
        try:
            sql = """
                SELECT * FROM backtest_result 
                WHERE strategy_name = ? AND start_date = ? AND end_date = ?
                LIMIT 1
            """
            result = self.db.query_one(sql, (strategy_name, start_date, end_date))
            if result:
                return dict(result)
            return None
            
        except Exception as e:
            logger.error(f"根据策略和日期获取回测结果失败: {str(e)}")
            return None
    
    def update_result(self, result_id: int, result: Dict) -> bool:
        """
        更新现有的回测结果记录
        
        Args:
            result_id: 回测结果ID
            result: 回测结果字典
            
        Returns:
            是否更新成功
        """
        try:
            sql = """
                UPDATE backtest_result SET
                    strategy_name = ?,
                    support_level_method = ?,
                    backtest_name = ?,
                    start_date = ?,
                    end_date = ?,
                    total_trades = ?,
                    win_trades = ?,
                    loss_trades = ?,
                    win_rate = ?,
                    avg_return = ?,
                    total_return = ?,
                    max_return = ?,
                    min_return = ?,
                    profit_factor = ?,
                    profit_loss_ratio = ?,
                    max_drawdown = ?,
                    sharpe_ratio = ?,
                    initial_capital = ?,
                    final_capital = ?,
                    created_at = ?
                WHERE id = ?
            """
            params = (
                result.get('strategy_name', ''),
                result.get('support_level_method', ''),
                result.get('backtest_name', ''),
                result.get('start_date', ''),
                result.get('end_date', ''),
                result.get('total_trades', 0),
                result.get('win_trades', 0),
                result.get('loss_trades', 0),
                result.get('win_rate', 0),
                result.get('avg_return', 0),
                result.get('total_return', 0),
                result.get('max_return', 0),
                result.get('min_return', 0),
                result.get('profit_factor', 0),
                result.get('profit_loss_ratio', 0),
                result.get('max_drawdown', 0),
                result.get('sharpe_ratio', 0),
                result.get('initial_capital', 1000000),
                result.get('final_capital', 1000000),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                result_id
            )
            
            self.db.execute(sql, params)
            self.db.connect().commit()
            logger.info(f"更新回测结果成功，result_id: {result_id}")
            return True
            
        except Exception as e:
            logger.error(f"更新回测结果失败: {str(e)}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return False
    
    # ==================== 交易记录相关操作 ====================
    
    def delete_equity_curve(self, result_id: int) -> bool:
        """
        删除指定回测结果的收益曲线数据
        
        Args:
            result_id: 回测结果ID
            
        Returns:
            是否删除成功
        """
        try:
            sql = "DELETE FROM backtest_equity_curve WHERE result_id = ?"
            self.db.execute(sql, (result_id,))
            self.db.connect().commit()
            return True
            
        except Exception as e:
            logger.error(f"删除收益曲线失败: {str(e)}")
            return False
    
    def delete_trades(self, result_id: int) -> bool:
        """
        删除指定回测结果的交易记录
        
        Args:
            result_id: 回测结果ID
            
        Returns:
            是否删除成功
        """
        try:
            sql = "DELETE FROM backtest_trade WHERE result_id = ?"
            self.db.execute(sql, (result_id,))
            self.db.connect().commit()
            return True
            
        except Exception as e:
            logger.error(f"删除交易记录失败: {str(e)}")
            return False
    
    def save_trade(self, trade: Dict) -> int:
        """
        保存交易记录
        
        Args:
            trade: 交易记录字典
            
        Returns:
            交易记录ID
        """
        try:
            sql = """
                INSERT INTO backtest_trade (
                    result_id, stock_code, stock_name, buy_date, 
                    buy_price, sell_date, sell_price, buy_amount, 
                    sell_amount, profit, profit_rate, trade_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                trade.get('result_id', 0),
                trade.get('stock_code', ''),
                trade.get('stock_name', ''),
                trade.get('buy_date', ''),
                trade.get('buy_price', 0),
                trade.get('sell_date', ''),
                trade.get('sell_price', 0),
                trade.get('buy_amount', 0),
                trade.get('sell_amount', 0),
                trade.get('profit', 0),
                trade.get('profit_rate', 0),
                trade.get('trade_type', 'normal')
            )
            
            cursor = self.db.execute(sql, params)
            self.db.connect().commit()
            return cursor.lastrowid
            
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
            return 0
    
    def get_trades_by_result(self, result_id: int) -> List[Dict]:
        """
        根据回测结果ID获取交易记录
        
        Args:
            result_id: 回测结果ID
            
        Returns:
            交易记录列表
        """
        try:
            sql = """
                SELECT * FROM backtest_trade 
                WHERE result_id = ? 
                ORDER BY buy_date ASC
            """
            results = self.db.query(sql, (result_id,))
            return [dict(result) for result in results]
            
        except Exception as e:
            logger.error(f"获取交易记录失败: {str(e)}")
            return []
    
    def get_trades_by_result_id(self, result_id: int) -> List[Dict]:
        """
        根据回测结果ID获取交易记录
        
        Args:
            result_id: 回测结果ID
            
        Returns:
            交易记录列表
        """
        return self.get_trades_by_result(result_id)
    
    def get_trades_by_stock(self, stock_code: str, result_id: int) -> List[Dict]:
        """
        根据股票代码和回测结果ID获取交易记录
        
        Args:
            stock_code: 股票代码
            result_id: 回测结果ID
            
        Returns:
            交易记录列表
        """
        try:
            sql = """
                SELECT * FROM backtest_trade 
                WHERE stock_code = ? AND result_id = ? 
                ORDER BY buy_date ASC
            """
            results = self.db.query(sql, (stock_code, result_id))
            return [dict(result) for result in results]
            
        except Exception as e:
            logger.error(f"获取股票交易记录失败: {str(e)}")
            return []
    
    # ==================== 批量操作 ====================
    
    def save_trades_batch(self, trades: List[Dict]) -> int:
        """
        批量保存交易记录
        
        Args:
            trades: 交易记录列表
            
        Returns:
            成功保存的记录数
        """
        try:
            if not trades:
                return 0
            
            sql = """
                INSERT INTO backtest_trade (
                    result_id, stock_code, stock_name, selection_date,
                    buy_date, buy_price, buy_amount, quantity,
                    sell_date, sell_price, sell_type, return_rate,
                    profit_loss, hold_days, support_level, trade_type,
                    buy_commission, buy_transfer_fee,
                    sell_commission, sell_transfer_fee, sell_stamp_tax,
                    total_cost, net_profit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            params_list = []
            for trade in trades:
                # 处理所有交易记录，包括未完成的交易（sell_date为空）
                # 处理日期格式
                selection_date = trade.get('selection_date', '')
                if hasattr(selection_date, 'strftime'):
                    selection_date = selection_date.strftime('%Y-%m-%d')
                    
                buy_date = trade.get('buy_date', '')
                if hasattr(buy_date, 'strftime'):
                    buy_date = buy_date.strftime('%Y-%m-%d')
                    
                sell_date = trade.get('sell_date', '')
                if hasattr(sell_date, 'strftime'):
                    sell_date = sell_date.strftime('%Y-%m-%d')
                elif sell_date is None:
                    sell_date = ''
                
                # 计算总成本和净盈亏
                total_cost = 0
                net_profit = trade.get('profit_loss', 0) or 0
                
                # 如果是卖出记录，计算成本
                if sell_date:
                    total_cost = (
                        (trade.get('buy_commission', 0) or 0) +
                        (trade.get('buy_transfer_fee', 0) or 0) +
                        (trade.get('sell_commission', 0) or 0) +
                        (trade.get('sell_transfer_fee', 0) or 0) +
                        (trade.get('sell_stamp_tax', 0) or 0)
                    )
                    net_profit = (trade.get('profit_loss', 0) or 0) - total_cost
                
                params = (
                    trade.get('result_id', 0),
                    trade.get('stock_code', ''),
                    trade.get('stock_name', ''),
                    selection_date,
                    buy_date,
                    trade.get('buy_price', 0),
                    trade.get('buy_amount', 0),
                    trade.get('quantity', 0),
                    sell_date,
                    trade.get('sell_price', 0) or 0,
                    trade.get('sell_type', 'normal') or 'normal',
                    trade.get('return_rate', 0) or 0,
                    trade.get('profit_loss', 0) or 0,
                    trade.get('hold_days', 0) or 0,
                    trade.get('support_level', 0) or 0,
                    trade.get('trade_type', 'normal') or 'normal',
                    # 交易成本字段
                    trade.get('buy_commission', 0) or 0,
                    trade.get('buy_transfer_fee', 0) or 0,
                    trade.get('sell_commission', 0) or 0,
                    trade.get('sell_transfer_fee', 0) or 0,
                    trade.get('sell_stamp_tax', 0) or 0,
                    round(total_cost, 2),
                    round(net_profit, 2)
                )
                params_list.append(params)
            
            conn = self.db.connect()
            cursor = conn.cursor()
            
            try:
                cursor.executemany(sql, params_list)
                conn.commit()
                return len(params_list)
            except Exception as e:
                conn.rollback()
                logger.error(f"批量保存交易记录失败: {str(e)}")
                return 0
            
        except Exception as e:
            logger.error(f"批量保存交易记录失败: {str(e)}")
            return 0
