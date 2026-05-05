#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KHunter DAO 模块
负责与 KHunter 表的所有数据库交互
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# 配置日志
logger = logging.getLogger(__name__)


class KHunterDAO:
    """
    KHunter 数据访问对象
    负责与 KHunter 表的所有数据库交互
    """
    
    # 表名
    TABLE_NAME = 'khunter'
    
    # 字段列表
    FIELDS = [
        'stock_code', 'stock_name', 'industry', 'sector',
        'key_date', 'hunting_date', 'strategy_name', 'support_level', 'current_price',
        'price_diff', 'price_diff_percent', 'buy_range', 'score', 'score_date', 'selection_record_id',
        'timing_strategy', 'timing_signal'
    ]
    
    # 唯一约束字段
    UNIQUE_FIELDS = ['stock_code', 'hunting_date', 'strategy_name', 'timing_strategy']
    
    def __init__(self, db_manager):
        """
        初始化 DAO
        
        参数：
            db_manager: 数据库管理器
        """
        # db_manager: 数据库管理器，类型object，必填
        self.db_manager = db_manager
        # 检查并添加缺失的字段
        self._ensure_table_columns()
        logger.info("KHunter DAO 初始化完成")
    
    def _ensure_table_columns(self):
        """
        确保表包含所需的字段，如果缺失则添加
        """
        try:
            # 查询表的现有字段
            result = self.db_manager.query(f"PRAGMA table_info({self.TABLE_NAME})")
            existing_columns = {row['name'] for row in result}
            
            # 需要检查的字段
            required_columns = [
                ('key_date', 'TEXT')
            ]
            
            # 检查每个字段是否存在
            for column_name, column_type in required_columns:
                if column_name not in existing_columns:
                    # 添加缺失的字段
                    self.db_manager.execute(f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
                    logger.info(f"为表 {self.TABLE_NAME} 添加缺失字段: {column_name} ({column_type})")
        except Exception as e:
            logger.warning(f"检查表 {self.TABLE_NAME} 的字段时出错: {e}")
    
    # ==================== 公开方法 ====================
    
    def save_result(self, result: Dict[str, Any]) -> bool:
        """
        保存单条结果
        
        参数：
            result: 结果字典
        
        返回：
            bool: 是否保存成功
        
        异常：
            ValueError: 如果数据无效
            Exception: 如果数据库操作失败
        """
        # result: 结果字典，类型Dict[str, Any]，必填
        try:
            # 1. 验证数据有效性
            self._validate_result(result)
            
            # 2. 开启事务
            self.db_manager.begin_transaction()
            
            try:
                # 3. 执行 upsert 操作
                success = self._upsert(result)
                
                # 4. 提交事务
                self.db_manager.commit()
                
                # 5. 记录日志
                if success:
                    logger.debug(
                        f"保存结果成功: {result['stock_code']} "
                        f"{result['hunting_date']} {result['strategy_name']}"
                    )
                else:
                    logger.warning(
                        f"保存结果失败: {result['stock_code']} "
                        f"{result['hunting_date']} {result['strategy_name']}"
                    )
                
                return success
            
            except Exception as e:
                # 6. 事务出错，回滚
                self.db_manager.rollback()
                logger.error(f"保存结果失败，已回滚: {str(e)}")
                raise
        
        except Exception as e:
            logger.error(f"保存结果异常: {str(e)}")
            raise
    
    def save_batch_results(self, results: List[Dict[str, Any]]) -> int:
        """
        批量保存结果
        
        参数：
            results: 结果列表
        
        返回：
            int: 保存成功的记录数
        
        异常：
            ValueError: 如果数据无效
            Exception: 如果数据库操作失败
        """
        # results: 结果列表，类型List[Dict[str, Any]]，必填
        try:
            # 1. 验证数据有效性
            if not results:
                logger.debug("批量保存结果: 空列表")
                return 0
            
            # 2. 验证每条记录
            for result in results:
                self._validate_result(result)
            
            # 3. 开启事务，确保批量操作的原子性
            self.db_manager.begin_transaction()
            
            try:
                # 4. 执行批量 upsert 操作
                success_count = 0
                for result in results:
                    try:
                        # 5. 执行 upsert 操作
                        if self._upsert(result):
                            success_count += 1
                    
                    except Exception as e:
                        logger.warning(
                            f"保存单条结果失败: {result.get('stock_code')} - {str(e)}"
                        )
                        continue
                
                # 6. 提交事务
                self.db_manager.commit()
                
                # 7. 记录日志
                logger.info(f"批量保存结果完成: {success_count}/{len(results)} 条")
                return success_count
            
            except Exception as e:
                # 8. 事务出错，回滚
                self.db_manager.rollback()
                logger.error(f"批量保存结果失败，已回滚: {str(e)}")
                raise
        
        except Exception as e:
            logger.error(f"批量保存结果异常: {str(e)}")
            raise
    
    def query_by_date(
        self,
        hunting_date: str,
        timing_strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        按日期查询
        
        参数：
            hunting_date: 狩猎日期
            timing_strategy: 择时策略名称（可选，为None时不按策略过滤）
        
        返回：
            Dict: 查询结果
        
        异常：
            Exception: 如果查询失败
        """
        # hunting_date: 狩猎日期，类型str，必填
        # timing_strategy: 择时策略名称，类型str，可选
        try:
            # 1. 构建查询条件
            if timing_strategy:
                # 按日期+策略查询
                sql_count = f"SELECT COUNT(*) as count FROM {self.TABLE_NAME} WHERE hunting_date = ? AND timing_strategy = ?"
                result_count = self.db_manager.query_one(sql_count, (hunting_date, timing_strategy))
                
                sql = f"""
                SELECT stock_code, stock_name, industry, sector,
                       key_date, hunting_date,
                       support_level, current_price, price_diff, price_diff_percent,
                       buy_range, strategy_name, score_date, score,
                       timing_strategy, timing_signal
                FROM {self.TABLE_NAME}
                WHERE hunting_date = ? AND timing_strategy = ?
                ORDER BY score DESC
                """
                params = (hunting_date, timing_strategy)
            else:
                # 仅按日期查询（兼容旧逻辑）
                sql_count = f"SELECT COUNT(*) as count FROM {self.TABLE_NAME} WHERE hunting_date = ?"
                result_count = self.db_manager.query_one(sql_count, (hunting_date,))
                
                sql = f"""
                SELECT stock_code, stock_name, industry, sector,
                       key_date, hunting_date,
                       support_level, current_price, price_diff, price_diff_percent,
                       buy_range, strategy_name, score_date, score,
                       timing_strategy, timing_signal
                FROM {self.TABLE_NAME}
                WHERE hunting_date = ?
                ORDER BY score DESC
                """
                params = (hunting_date,)
            
            # 2. 获取总数
            total_count = result_count['count'] if result_count else 0
            
            # 3. 执行查询
            results = self.db_manager.query(sql, params)
            
            # 4. 记录日志
            strategy_info = f" 策略={timing_strategy}" if timing_strategy else ""
            logger.debug(
                f"按日期查询: {hunting_date}{strategy_info}，"
                f"总数 {total_count}，返回 {len(results)} 条"
            )
            
            # 5. 返回结果
            return {
                'total_count': total_count,
                'results': results
            }
        
        except Exception as e:
            logger.error(f"按日期查询失败: {str(e)}")
            raise
    
    def query_by_date_and_code(
        self,
        hunting_date: str,
        stock_code: str,
        timing_strategy: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        按日期和股票代码查询
        
        参数：
            hunting_date: 狩猎日期
            stock_code: 股票代码
            timing_strategy: 择时策略名称（可选，为None时不按策略过滤）
        
        返回：
            List: 查询结果列表
        
        异常：
            Exception: 如果查询失败
        """
        # hunting_date: 狩猎日期，类型str，必填
        # stock_code: 股票代码，类型str，必填
        # timing_strategy: 择时策略名称，类型str，可选
        try:
            # 1. 构建查询 SQL
            if timing_strategy:
                sql = f"""
                SELECT stock_code, stock_name, industry, sector,
                       support_level, current_price, price_diff, price_diff_percent,
                       buy_range, strategy_name, score_date, score,
                       timing_strategy, timing_signal
                FROM {self.TABLE_NAME}
                WHERE hunting_date = ? AND stock_code = ? AND timing_strategy = ?
                ORDER BY score DESC
                """
                params = (hunting_date, stock_code, timing_strategy)
            else:
                sql = f"""
                SELECT stock_code, stock_name, industry, sector,
                       support_level, current_price, price_diff, price_diff_percent,
                       buy_range, strategy_name, score_date, score,
                       timing_strategy, timing_signal
                FROM {self.TABLE_NAME}
                WHERE hunting_date = ? AND stock_code = ?
                ORDER BY score DESC
                """
                params = (hunting_date, stock_code)
            
            # 2. 执行查询
            results = self.db_manager.query(sql, params)
            
            # 3. 记录日志
            strategy_info = f" 策略={timing_strategy}" if timing_strategy else ""
            logger.debug(
                f"按日期和股票代码查询: {hunting_date} {stock_code}{strategy_info}，"
                f"返回 {len(results)} 条"
            )
            
            return results
        
        except Exception as e:
            logger.error(f"按日期和股票代码查询失败: {str(e)}")
            raise
    
    def check_cache(self, hunting_date: str, timing_strategy: Optional[str] = None) -> bool:
        """
        检查缓存
        
        参数：
            hunting_date: 狩猎日期
            timing_strategy: 择时策略名称（可选，为None时不按策略过滤）
        
        返回：
            bool: 是否存在缓存
        
        异常：
            Exception: 如果查询失败
        """
        # hunting_date: 狩猎日期，类型str，必填
        # timing_strategy: 择时策略名称，类型str，可选
        try:
            # 1. 查询记录数
            if timing_strategy:
                sql = f"SELECT COUNT(*) as count FROM {self.TABLE_NAME} WHERE hunting_date = ? AND timing_strategy = ?"
                result = self.db_manager.query_one(sql, (hunting_date, timing_strategy))
            else:
                sql = f"SELECT COUNT(*) as count FROM {self.TABLE_NAME} WHERE hunting_date = ?"
                result = self.db_manager.query_one(sql, (hunting_date,))
            
            # 2. 判断是否存在缓存
            has_cache = result and result['count'] > 0
            
            # 3. 记录日志
            strategy_info = f" 策略={timing_strategy}" if timing_strategy else ""
            logger.debug(f"检查缓存: {hunting_date}{strategy_info} - {'命中' if has_cache else '未命中'}")
            
            return has_cache
        
        except Exception as e:
            logger.error(f"检查缓存失败: {str(e)}")
            raise
    
    def delete_by_date(self, hunting_date: str) -> int:
        """
        按日期删除
        
        参数：
            hunting_date: 狩猎日期
        
        返回：
            int: 删除的记录数
        
        异常：
            Exception: 如果删除失败
        """
        # hunting_date: 狩猎日期，类型str，必填
        try:
            # 1. 先查询要删除的记录数
            sql_count = f"SELECT COUNT(*) as count FROM {self.TABLE_NAME} WHERE hunting_date = ?"
            result_count = self.db_manager.query_one(sql_count, (hunting_date,))
            count = result_count['count'] if result_count else 0
            
            # 2. 如果没有记录，直接返回
            if count == 0:
                logger.debug(f"按日期删除: {hunting_date} - 无记录")
                return 0
            
            # 3. 执行删除操作
            sql = f"DELETE FROM {self.TABLE_NAME} WHERE hunting_date = ?"
            self.db_manager.execute(sql, (hunting_date,))
            
            # 4. 记录日志
            logger.info(f"按日期删除: {hunting_date} - 删除 {count} 条记录")
            
            return count
        
        except Exception as e:
            logger.error(f"按日期删除失败: {str(e)}")
            raise
    
    # ==================== 私有方法 ====================
    
    def _upsert(self, result: Dict[str, Any]) -> bool:
        """
        插入或更新
        
        参数：
            result: 结果字典
        
        返回：
            bool: 是否操作成功
        """
        # result: 结果字典，类型Dict[str, Any]，必填
        try:
            # 1. 检查记录是否存在
            stock_code = result['stock_code']
            hunting_date = result['hunting_date']
            strategy_name = result['strategy_name']
            timing_strategy = result.get('timing_strategy', 'support')
            
            # 2. 查询是否存在
            sql_check = f"""
            SELECT COUNT(*) as count FROM {self.TABLE_NAME}
            WHERE stock_code = ? AND hunting_date = ? AND strategy_name = ? AND timing_strategy = ?
            """
            
            # 3. 执行查询
            result_check = self.db_manager.query_one(
                sql_check, (stock_code, hunting_date, strategy_name, timing_strategy)
            )
            
            # 4. 判断是否存在
            exists = result_check and result_check['count'] > 0
            
            # 5. 如果存在，执行更新；否则执行插入
            if exists:
                # 6. 执行更新操作
                return self._update(result)
            else:
                # 7. 执行插入操作
                return self._insert(result)
        
        except Exception as e:
            logger.error(f"Upsert 操作失败: {str(e)}")
            return False
    
    def _insert(self, result: Dict[str, Any]) -> bool:
        """
        插入记录
        
        参数：
            result: 结果字典
        
        返回：
            bool: 是否插入成功
        """
        # result: 结果字典，类型Dict[str, Any]，必填
        try:
            # 1. 构建插入 SQL
            sql = f"""
            INSERT INTO {self.TABLE_NAME} (
                stock_code, stock_name, industry, sector,
                key_date, hunting_date, strategy_name, support_level, current_price,
                price_diff, price_diff_percent, buy_range, score, score_date, selection_record_id,
                timing_strategy, timing_signal,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
            
            # 2. 准备参数
            params = (
                result['stock_code'],
                result['stock_name'],
                result.get('industry'),
                result.get('sector'),
                result.get('key_date'),  # 关键日日期（形态实际形成日期）
                result['hunting_date'],
                result['strategy_name'],
                result['support_level'],
                result['current_price'],
                result['price_diff'],
                result['price_diff_percent'],
                result.get('buy_range', ''),
                result.get('score'),
                result.get('score_date'),
                result.get('selection_record_id'),
                result.get('timing_strategy', 'support'),
                result.get('timing_signal', '')
            )
            
            # 3. 执行插入
            self.db_manager.execute(sql, params)
            
            # 4. 记录日志
            logger.debug(
                f"插入记录: {result['stock_code']} "
                f"关键日={result.get('key_date')} "
                f"选入日={result['hunting_date']} {result['strategy_name']}"
            )
            
            return True
        
        except Exception as e:
            logger.error(f"插入记录失败: {str(e)}")
            return False
    
    def _update(self, result: Dict[str, Any]) -> bool:
        """
        更新记录
        
        参数：
            result: 结果字典
        
        返回：
            bool: 是否更新成功
        """
        # result: 结果字典，类型Dict[str, Any]，必填
        try:
            # 1. 构建更新 SQL
            sql = f"""
            UPDATE {self.TABLE_NAME} SET
                key_date = ?,
                support_level = ?,
                current_price = ?,
                price_diff = ?,
                price_diff_percent = ?,
                buy_range = ?,
                score = ?,
                score_date = ?,
                timing_strategy = ?,
                timing_signal = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE stock_code = ? AND hunting_date = ? AND strategy_name = ? AND timing_strategy = ?
            """
            
            # 2. 准备参数
            params = (
                result.get('key_date'),  # 关键日日期（形态实际形成日期）
                result['support_level'],
                result['current_price'],
                result['price_diff'],
                result['price_diff_percent'],
                result.get('buy_range', ''),
                result.get('score'),
                result.get('score_date'),
                result.get('timing_strategy', 'support'),
                result.get('timing_signal', ''),
                result['stock_code'],
                result['hunting_date'],
                result['strategy_name'],
                result.get('timing_strategy', 'support')
            )
            
            # 3. 执行更新
            self.db_manager.execute(sql, params)
            
            # 4. 记录日志
            logger.debug(
                f"更新记录: {result['stock_code']} "
                f"关键日={result.get('key_date')} "
                f"选入日={result['hunting_date']} {result['strategy_name']}"
            )
            
            return True
        
        except Exception as e:
            logger.error(f"更新记录失败: {str(e)}")
            return False
    
    def _validate_result(self, result: Dict[str, Any]) -> None:
        """
        验证结果数据有效性
        
        参数：
            result: 结果字典
        
        异常：
            ValueError: 如果数据无效
        """
        # result: 结果字典，类型Dict[str, Any]，必填
        try:
            # 1. 检查必填字段
            required_fields = [
                'stock_code', 'stock_name', 'hunting_date',
                'strategy_name', 'support_level', 'current_price',
                'price_diff', 'price_diff_percent'
            ]
            
            # 2. 验证必填字段
            for field in required_fields:
                if field not in result or result[field] is None:
                    raise ValueError(f"缺少必填字段: {field}")
            
            # 3. 验证数值字段
            numeric_fields = [
                'support_level', 'current_price', 'price_diff', 'price_diff_percent'
            ]
            
            # 4. 验证数值有效性
            for field in numeric_fields:
                value = result[field]
                if not isinstance(value, (int, float)):
                    raise ValueError(f"字段 {field} 必须是数值类型")
                if value < 0 and field != 'price_diff' and field != 'price_diff_percent':
                    raise ValueError(f"字段 {field} 不能为负数")
            
            # 5. 验证日期格式
            hunting_date = result['hunting_date']
            try:
                datetime.strptime(hunting_date, '%Y-%m-%d')
            except ValueError:
                raise ValueError(f"日期格式无效: {hunting_date}")
            
            logger.debug(f"验证结果数据成功: {result['stock_code']}")
        
        except ValueError as e:
            logger.error(f"验证结果数据失败: {str(e)}")
            raise
