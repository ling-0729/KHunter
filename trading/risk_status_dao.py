"""
风控状态数据访问对象

提供风控状态的数据库操作，包括：
- 风控状态的保存和查询
- 风控历史趋势分析
- 风险等级统计
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from utils.db_manager import DBManager

# 配置日志
logger = logging.getLogger(__name__)


class RiskStatusDAO:
    """风控状态数据访问对象"""
    
    def __init__(self, db=None):
        """
        初始化风控状态数据访问对象
        
        参数：
            db: 数据库实例，如果为None则使用全局数据库
        """
        if db is None:
            from utils.global_db import get_global_db
            self.db = get_global_db()
        else:
            self.db = db
    
    def save(self, risk_status) -> int:
        """
        保存风控状态（存在则更新，不存在则插入）
        
        参数：
            risk_status: RiskStatus对象或风控状态字典
        
        返回：
            数据记录ID
        """
        try:
            # 处理RiskStatus对象
            if hasattr(risk_status, 'date'):
                date = risk_status.date
                var_1d = risk_status.var_1d
                var_5d = risk_status.var_5d
                es_1d = risk_status.es_1d
                risk_level = risk_status.risk_level.value
                position_limit = risk_status.position_limit
                stop_loss_multiplier = risk_status.stop_loss_multiplier
                score_extra = risk_status.score_extra
                strategy_enabled = 1 if risk_status.strategy_enabled else 0
                liquidate = 1 if risk_status.liquidate else 0
            else:
                # 处理字典
                date = risk_status.get('date')
                var_1d = risk_status.get('var_1d')
                var_5d = risk_status.get('var_5d')
                es_1d = risk_status.get('es_1d')
                risk_level = risk_status.get('risk_level')
                position_limit = risk_status.get('position_limit')
                stop_loss_multiplier = risk_status.get('stop_loss_multiplier')
                score_extra = risk_status.get('score_extra')
                strategy_enabled = 1 if risk_status.get('strategy_enabled', True) else 0
                liquidate = 1 if risk_status.get('liquidate', False) else 0
            
            if not date:
                raise ValueError("date is required")
            
            # 检查是否已存在
            existing = self.query_by_date(date)
            
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            record = {
                'date': date,
                'var_1d': var_1d,
                'var_5d': var_5d,
                'es_1d': es_1d,
                'risk_level': risk_level,
                'position_limit': position_limit,
                'stop_loss_multiplier': stop_loss_multiplier,
                'score_extra': score_extra,
                'strategy_enabled': strategy_enabled,
                'liquidate': liquidate,
                'updated_at': now
            }
            
            if existing:
                # 更新现有记录
                self.db.update('risk_status', record, {'date': date})
                logger.info(f"更新风控状态: {date}, VaR={var_1d*100:.2f}%, 风险等级={risk_level}")
                return existing['id']
            else:
                # 插入新记录
                record['created_at'] = now
                record_id = self.db.insert('risk_status', record)
                logger.info(f"保存风控状态: {date}, VaR={var_1d*100:.2f}%, 风险等级={risk_level}")
                return record_id
                
        except Exception as e:
            logger.error(f"保存风控状态失败: {e}")
            raise
    
    def query_by_date(self, date: str) -> Optional[Dict]:
        """
        按日期查询风控状态
        
        参数：
            date: 日期（YYYY-MM-DD格式）
        
        返回：
            风控状态字典，如果不存在返回None
        """
        try:
            result = self.db.query_one(
                'SELECT * FROM risk_status WHERE date = ?',
                (date,)
            )
            return result
        except Exception as e:
            logger.error(f"查询风控状态失败: {e}")
            return None
    
    def query_range(self, start_date: str, end_date: str) -> List[Dict]:
        """
        查询日期范围内的风控状态
        
        参数：
            start_date: 开始日期（YYYY-MM-DD格式）
            end_date: 结束日期（YYYY-MM-DD格式）
        
        返回：
            风控状态列表
        """
        try:
            results = self.db.query(
                '''SELECT * FROM risk_status 
                   WHERE date >= ? AND date <= ?
                   ORDER BY date ASC''',
                (start_date, end_date)
            )
            return results
        except Exception as e:
            logger.error(f"查询日期范围风控状态失败: {e}")
            return []
    
    def get_trend(self, days: int = 30) -> Dict:
        """
        获取最近N天的风控状态趋势
        
        参数：
            days: 天数，默认30天
        
        返回：
            趋势数据字典，包含：
            - trend: 趋势列表
            - avg_var_1d: 平均VaR(1日)
            - max_var_1d: 最大VaR(1日)
            - min_var_1d: 最小VaR(1日)
            - latest_risk_level: 最新风险等级
            - risk_level_distribution: 风险等级分布
        """
        try:
            results = self.db.query(
                '''SELECT * FROM risk_status 
                   ORDER BY date DESC LIMIT ?''',
                (days,)
            )
            
            if not results:
                return {
                    'trend': [],
                    'avg_var_1d': 0,
                    'max_var_1d': 0,
                    'min_var_1d': 0,
                    'latest_risk_level': None,
                    'risk_level_distribution': {}
                }
            
            # 反转列表使日期升序
            trend = list(reversed(results))
            
            var_1d_values = [r['var_1d'] for r in results]
            
            # 统计风险等级分布
            risk_level_dist = {}
            for r in results:
                level = r['risk_level']
                risk_level_dist[level] = risk_level_dist.get(level, 0) + 1
            
            return {
                'trend': trend,
                'avg_var_1d': round(sum(var_1d_values) / len(var_1d_values), 4),
                'max_var_1d': max(var_1d_values),
                'min_var_1d': min(var_1d_values),
                'latest_risk_level': results[0]['risk_level'] if results else None,
                'latest_var_1d': results[0]['var_1d'] if results else None,
                'latest_date': results[0]['date'] if results else None,
                'risk_level_distribution': risk_level_dist
            }
        except Exception as e:
            logger.error(f"获取风控状态趋势失败: {e}")
            return {
                'trend': [],
                'avg_var_1d': 0,
                'max_var_1d': 0,
                'min_var_1d': 0,
                'latest_risk_level': None,
                'risk_level_distribution': {}
            }
    
    def get_latest(self) -> Optional[Dict]:
        """
        获取最新的风控状态
        
        返回：
            最新风控状态字典，如果不存在返回None
        """
        try:
            result = self.db.query_one(
                'SELECT * FROM risk_status ORDER BY date DESC LIMIT 1'
            )
            return result
        except Exception as e:
            logger.error(f"获取最新风控状态失败: {e}")
            return None
    
    def delete(self, date: str) -> bool:
        """
        删除指定日期的风控状态
        
        参数：
            date: 日期（YYYY-MM-DD格式）
        
        返回：
            是否删除成功
        """
        try:
            self.db.execute('DELETE FROM risk_status WHERE date = ?', (date,))
            logger.info(f"删除风控状态: {date}")
            return True
        except Exception as e:
            logger.error(f"删除风控状态失败: {e}")
            return False
    
    def get_risk_level_stats(self, days: int = 30) -> Dict:
        """
        获取最近N天的风险等级统计
        
        参数：
            days: 天数，默认30天
        
        返回：
            风险等级统计字典
        """
        try:
            results = self.db.query(
                '''SELECT risk_level, COUNT(*) as count, 
                          AVG(var_1d) as avg_var,
                          AVG(position_limit) as avg_position
                   FROM risk_status 
                   WHERE date >= date('now', '-{} days')
                   GROUP BY risk_level
                   ORDER BY count DESC'''.format(days)
            )
            
            stats = {}
            for r in results:
                stats[r['risk_level']] = {
                    'count': r['count'],
                    'avg_var': round(r['avg_var'], 4),
                    'avg_position': round(r['avg_position'], 2)
                }
            
            return stats
        except Exception as e:
            logger.error(f"获取风险等级统计失败: {e}")
            return {}