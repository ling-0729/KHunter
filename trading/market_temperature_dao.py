# -*- coding: utf-8 -*-
"""
市场温度数据访问对象

提供市场温度数据的数据库操作，包括：
- 温度数据的保存和查询
- 温度趋势分析
- 仓位系数获取
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from utils.db_manager import DBManager

# 配置日志
logger = logging.getLogger(__name__)


class MarketTemperatureDAO:
    """市场温度数据访问对象"""
    
    def __init__(self, db=None):
        """
        初始化市场温度数据访问对象
        
        Args:
            db: 数据库实例，如果为None则使用全局数据库
        """
        if db is None:
            from utils.global_db import get_global_db
            self.db = get_global_db()
        else:
            self.db = db
    
    def save(self, data: Dict) -> int:
        """
        保存市场温度数据（存在则更新，不存在则插入）
        
        Args:
            data: 市场温度数据字典，包含字段：
                - trade_date: 交易日期（YYYYMMDD格式）
                - temperature: 综合温度值
                - status: 市场状态
                - position_ratio: 仓位系数
                - action: 狩猎场执行规则
                - 各维度得分和原始数据（可选）
        
        Returns:
            数据记录ID
        """
        try:
            trade_date = data.get('trade_date')
            if not trade_date:
                raise ValueError("trade_date is required")
            
            # 检查是否已存在
            existing = self.query_by_date(trade_date)
            
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            record = {
                'trade_date': trade_date,
                'temperature': data.get('temperature'),
                'status': data.get('status'),
                'position_ratio': data.get('position_ratio'),
                'action': data.get('action'),
                'up_down_ratio_score': data.get('up_down_ratio_score'),
                'limit_down_score': data.get('limit_down_score'),
                'limit_up_performance_score': data.get('limit_up_performance_score'),
                'volume_score': data.get('volume_score'),
                'up_count': data.get('up_count'),
                'down_count': data.get('down_count'),
                'limit_down_count': data.get('limit_down_count'),
                'avg_limit_up_change': data.get('avg_limit_up_change'),
                'total_volume': data.get('total_volume'),
                'volume_ma5_ratio': data.get('volume_ma5_ratio'),
                'updated_at': now
            }
            
            if existing:
                # 更新现有记录
                self.db.update('market_temperature', record, {'trade_date': trade_date})
                logger.info(f"更新市场温度数据: {trade_date}, 温度={record['temperature']}")
                return existing['id']
            else:
                # 插入新记录
                record['created_at'] = now
                record_id = self.db.insert('market_temperature', record)
                logger.info(f"保存市场温度数据: {trade_date}, 温度={record['temperature']}")
                return record_id
                
        except Exception as e:
            logger.error(f"保存市场温度数据失败: {e}")
            raise
    
    def query_by_date(self, trade_date: str) -> Optional[Dict]:
        """
        按交易日期查询市场温度数据
        
        Args:
            trade_date: 交易日期（YYYYMMDD格式）
        
        Returns:
            市场温度数据字典，如果不存在返回None
        """
        try:
            result = self.db.query_one(
                'SELECT * FROM market_temperature WHERE trade_date = ?',
                (trade_date,)
            )
            return result
        except Exception as e:
            logger.error(f"查询市场温度数据失败: {e}")
            return None
    
    def query_range(self, start_date: str, end_date: str) -> List[Dict]:
        """
        查询日期范围内的市场温度数据
        
        Args:
            start_date: 开始日期（YYYYMMDD格式）
            end_date: 结束日期（YYYYMMDD格式）
        
        Returns:
            市场温度数据列表
        """
        try:
            results = self.db.query(
                '''SELECT * FROM market_temperature 
                   WHERE trade_date >= ? AND trade_date <= ?
                   ORDER BY trade_date ASC''',
                (start_date, end_date)
            )
            return results
        except Exception as e:
            logger.error(f"查询日期范围市场温度数据失败: {e}")
            return []
    
    def get_trend(self, days: int = 5) -> Dict:
        """
        获取最近N天的温度趋势
        
        Args:
            days: 天数，默认5天
        
        Returns:
            趋势数据字典，包含：
            - trend: 趋势列表
            - avg_temperature: 平均温度
            - max_temperature: 最高温度
            - min_temperature: 最低温度
            - latest_status: 最新状态
        """
        try:
            results = self.db.query(
                '''SELECT * FROM market_temperature 
                   ORDER BY trade_date DESC LIMIT ?''',
                (days,)
            )
            
            if not results:
                return {
                    'trend': [],
                    'avg_temperature': 0,
                    'max_temperature': 0,
                    'min_temperature': 0,
                    'latest_status': None
                }
            
            # 反转列表使日期升序
            trend = list(reversed(results))
            
            temperatures = [r['temperature'] for r in results]
            
            return {
                'trend': trend,
                'avg_temperature': round(sum(temperatures) / len(temperatures), 1),
                'max_temperature': max(temperatures),
                'min_temperature': min(temperatures),
                'latest_status': results[0]['status'] if results else None,
                'latest_temperature': results[0]['temperature'] if results else None,
                'latest_trade_date': results[0]['trade_date'] if results else None
            }
        except Exception as e:
            logger.error(f"获取温度趋势失败: {e}")
            return {
                'trend': [],
                'avg_temperature': 0,
                'max_temperature': 0,
                'min_temperature': 0,
                'latest_status': None
            }
    
    def get_position_ratio(self, trade_date: str) -> float:
        """
        获取指定日期的仓位系数
        
        Args:
            trade_date: 交易日期（YYYYMMDD格式）
        
        Returns:
            仓位系数（0-1），如果不存在返回默认值0.5
        """
        data = self.query_by_date(trade_date)
        if data:
            return data.get('position_ratio', 0.5)
        return 0.5  # 默认半仓
    
    def get_latest(self) -> Optional[Dict]:
        """
        获取最新的市场温度数据
        
        Returns:
            最新市场温度数据字典，如果不存在返回None
        """
        try:
            result = self.db.query_one(
                'SELECT * FROM market_temperature ORDER BY trade_date DESC LIMIT 1'
            )
            return result
        except Exception as e:
            logger.error(f"获取最新市场温度数据失败: {e}")
            return None
    
    def delete(self, trade_date: str) -> bool:
        """
        删除指定日期的市场温度数据
        
        Args:
            trade_date: 交易日期（YYYYMMDD格式）
        
        Returns:
            是否删除成功
        """
        try:
            self.db.execute('DELETE FROM market_temperature WHERE trade_date = ?', (trade_date,))
            logger.info(f"删除市场温度数据: {trade_date}")
            return True
        except Exception as e:
            logger.error(f"删除市场温度数据失败: {e}")
            return False
