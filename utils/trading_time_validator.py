"""
交易时间验证模块

用于验证当前时间是否允许进行数据更新，以及确定目标更新日期。
"""

from datetime import datetime, timedelta
from typing import Tuple, Dict, Any
import logging

logger = logging.getLogger(__name__)


class TradingTimeValidator:
    """
    交易时间验证器
    
    用于检查当前时间是否在交易时间内，以及确定目标更新日期。
    """
    
    # 交易时间配置
    TRADING_START_HOUR = 9
    TRADING_START_MINUTE = 30
    TRADING_END_HOUR = 15
    TRADING_END_MINUTE = 0
    
    def __init__(self, db_manager):
        """
        初始化交易时间验证器
        
        Args:
            db_manager: 数据库管理器实例
        """
        self.db_manager = db_manager
    
    def validate_update_time(self) -> Tuple[bool, str, str]:
        """
        验证当前时间是否允许更新
        
        返回值:
            (is_valid, error_message, target_date)
            - is_valid: 是否允许更新
            - error_message: 错误信息（如果不允许更新）
            - target_date: 目标更新日期（YYYY-MM-DD格式）
        """
        # 获取当前时间
        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        current_time_minutes = current_hour * 60 + current_minute
        
        # 计算交易时间的分钟数
        trading_start_minutes = self.TRADING_START_HOUR * 60 + self.TRADING_START_MINUTE
        trading_end_minutes = self.TRADING_END_HOUR * 60 + self.TRADING_END_MINUTE
        
        # 判断当前时间段
        if trading_start_minutes <= current_time_minutes < trading_end_minutes:
            # 在交易时间内，不允许更新
            return False, "交易时间不允许更新", ""
        
        # 确定目标更新日期
        if current_time_minutes < trading_start_minutes:
            # 交易前（00:00-09:30），更新到前一天数据
            target_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            # 收盘后（15:00-23:59），更新到当天数据
            target_date = now.strftime("%Y-%m-%d")
        
        # 检查是否已在目标日期更新过
        is_updated, error_msg = self._check_if_updated(target_date)
        if is_updated:
            return False, error_msg, target_date
        
        return True, "", target_date
    
    def _check_if_updated(self, target_date: str) -> Tuple[bool, str]:
        """
        检查是否已在目标日期更新过

        检查逻辑：
        1. 如果 update_log 表中有 'completed' 记录，则已更新
        2. 否则允许更新

        Args:
            target_date: 目标更新日期（YYYY-MM-DD格式）

        返回值:
            (is_updated, error_message)
            - is_updated: 是否已更新
            - error_message: 错误信息
        """
        try:
            cursor = self.db_manager.connect().cursor()

            # 第1步：检查 update_log 表中是否有 'completed' 记录
            cursor.execute(
                "SELECT id FROM update_log WHERE update_date = ? AND status = 'completed'",
                (target_date,)
            )
            if cursor.fetchone():
                # 已存在完成的更新记录
                return True, f"目标日期 {target_date} 已更新过"

            # 没有完成的更新记录，允许更新
            return False, ""

        except Exception as e:
            logger.error(f"检查更新日志失败: {str(e)}")
            return False, ""
    
    def record_update_start(self, target_date: str) -> str:
        """
        记录更新开始（已弃用）
        
        注意：此方法已弃用。应该只在更新成功完成后才记录。
        
        Args:
            target_date: 目标更新日期（YYYY-MM-DD格式）
        
        返回值:
            update_log 表的 ID
        """
        # 此方法已弃用，不再在更新开始时创建记录
        # 改为在 record_update_complete 中创建记录
        logger.warning(f"record_update_start 已弃用，应该只在更新成功后才记录")
        return ""
    
    def record_update_complete(self, target_date: str, stats: Dict[str, Any]) -> bool:
        """
        记录更新完成
        
        只在更新成功完成后才记录。如果记录不存在则创建，存在则更新。
        
        Args:
            target_date: 目标更新日期（YYYY-MM-DD格式）
            stats: 更新统计信息
        
        返回值:
            是否成功记录
        """
        try:
            cursor = self.db_manager.connect().cursor()
            
            # 检查是否已存在记录
            cursor.execute(
                "SELECT id FROM update_log WHERE update_date = ?",
                (target_date,)
            )
            result = cursor.fetchone()
            
            if result:
                # 更新现有记录
                cursor.execute(
                    """UPDATE update_log 
                    SET status = ?, 
                        update_time = ?,
                        new_stock_detected = ?,
                        new_stock_initialized = ?,
                        kline_added = ?,
                        kline_updated = ?,
                        fund_flow_added = ?,
                        fund_flow_updated = ?
                    WHERE update_date = ?""",
                    (
                        'completed',
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        stats.get('new_stock_detected', 0),
                        stats.get('new_stock_initialized', 0),
                        stats.get('kline_added', 0),
                        stats.get('kline_updated', 0),
                        stats.get('fund_flow_added', 0),
                        stats.get('fund_flow_updated', 0),
                        target_date
                    )
                )
            else:
                # 创建新记录（只在更新成功时创建）
                cursor.execute(
                    """INSERT INTO update_log 
                    (update_date, update_time, status, new_stock_detected, new_stock_initialized, 
                     kline_added, kline_updated, fund_flow_added, fund_flow_updated) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        target_date,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'completed',
                        stats.get('new_stock_detected', 0),
                        stats.get('new_stock_initialized', 0),
                        stats.get('kline_added', 0),
                        stats.get('kline_updated', 0),
                        stats.get('fund_flow_added', 0),
                        stats.get('fund_flow_updated', 0)
                    )
                )
            
            self.db_manager.connect().commit()
            return True
        
        except Exception as e:
            logger.error(f"记录更新完成失败: {str(e)}")
            return False
    
    def record_update_failed(self, target_date: str, error_message: str) -> bool:
        """
        记录更新失败
        
        如果更新失败，不记录任何信息。这样下次可以重新尝试更新。
        
        Args:
            target_date: 目标更新日期（YYYY-MM-DD格式）
            error_message: 错误信息
        
        返回值:
            是否成功处理
        """
        try:
            cursor = self.db_manager.connect().cursor()
            
            # 删除失败的记录（如果存在）
            # 这样下次可以重新尝试更新
            cursor.execute(
                "DELETE FROM update_log WHERE update_date = ? AND status != 'completed'",
                (target_date,)
            )
            
            self.db_manager.connect().commit()
            logger.info(f"更新失败，已清除 {target_date} 的未完成记录。错误: {error_message}")
            return True
        
        except Exception as e:
            logger.error(f"处理更新失败失败: {str(e)}")
            return False
    
    def get_last_update_date(self) -> str:
        """
        获取上次成功更新的日期
        
        优先级：
        1. 从 update_log 表中获取最后一次成功更新的日期
        2. 如果 update_log 表中没有记录，则从 stock_kline 表中获取最后一根 K 线的日期
        3. 如果都没有，则返回空字符串
        
        返回值:
            上次更新日期（YYYY-MM-DD格式），如果没有则返回空字符串
        """
        try:
            cursor = self.db_manager.connect().cursor()
            
            # 第1步：尝试从 update_log 表中获取
            cursor.execute(
                "SELECT update_date FROM update_log WHERE status = 'completed' ORDER BY update_date DESC LIMIT 1"
            )
            result = cursor.fetchone()
            
            if result:
                logger.debug(f"从 update_log 表中获取最后更新日期: {result[0]}")
                return result[0]
            
            # 第2步：如果 update_log 表中没有记录，则从 stock_kline 表中获取最后一根 K 线的日期
            logger.debug("update_log 表中没有完成的记录，尝试从 stock_kline 表中获取最后 K 线日期...")
            cursor.execute(
                "SELECT MAX(date) FROM stock_kline"
            )
            result = cursor.fetchone()
            
            if result and result[0]:
                logger.debug(f"从 stock_kline 表中获取最后 K 线日期: {result[0]}")
                return result[0]
            
            # 第3步：都没有记录
            logger.warning("无法获取最后更新日期：update_log 和 stock_kline 表中都没有记录")
            return ""
        
        except Exception as e:
            logger.error(f"获取上次更新日期失败: {str(e)}")
            return ""


def is_market_closed() -> bool:
    """
    检查当前是否已收盘

    返回值:
        bool: 是否已收盘
    """
    # 获取当前时间
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute
    current_time_minutes = current_hour * 60 + current_minute
    
    # 交易时间结束时间（15:00）
    trading_end_minutes = 15 * 60 + 0
    
    # 判断是否已收盘
    if current_time_minutes >= trading_end_minutes:
        return True
    else:
        return False
