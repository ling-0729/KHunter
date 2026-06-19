#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易计划 DAO 模块
负责与 trading_plan 表的所有数据库交互
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class TradingPlanDAO:
    """
    交易计划数据访问对象
    负责与 trading_plan 表的所有数据库交互
    """

    TABLE_NAME = 'trading_plan'

    FIELDS = [
        'plan_date', 'hunting_date', 'stock_code', 'stock_name',
        'buy_lower_price', 'buy_upper_price', 'position_ratio',
        'support_level', 'stop_loss_price', 'take_profit_price',
        'hold_days', 'remark'
    ]

    def __init__(self, db_manager):
        self.db_manager = db_manager
        logger.info("TradingPlan DAO 初始化完成")

    def save_plan(self, plan: Dict[str, Any]) -> int:
        """
        保存单条交易计划

        参数：
            plan: 交易计划字典

        返回：
            int: 保存后的ID
        """
        try:
            self._validate_plan(plan)
            self.db_manager.begin_transaction()
            try:
                sql = """
                INSERT INTO trading_plan (
                    plan_date, hunting_date, stock_code, stock_name,
                    buy_lower_price, buy_upper_price, position_ratio,
                    support_level, stop_loss_price, take_profit_price,
                    hold_days, remark
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                params = (
                    plan['plan_date'], plan['hunting_date'], plan['stock_code'], plan['stock_name'],
                    plan.get('buy_lower_price'), plan.get('buy_upper_price'), plan.get('position_ratio'),
                    plan.get('support_level'), plan.get('stop_loss_price'), plan.get('take_profit_price'),
                    plan.get('hold_days'), plan.get('remark', '')
                )
                cursor = self.db_manager.execute(sql, params)
                self.db_manager.commit()
                return cursor.lastrowid
            except Exception as e:
                self.db_manager.rollback()
                logger.error(f"保存交易计划失败: {str(e)}")
                raise
        except Exception as e:
            logger.error(f"保存交易计划异常: {str(e)}")
            raise

    def save_batch_plans(self, plans: List[Dict[str, Any]]) -> int:
        """
        批量保存交易计划

        参数：
            plans: 交易计划列表

        返回：
            int: 保存成功的记录数
        """
        if not plans:
            return 0
        for plan in plans:
            self._validate_plan(plan)
        self.db_manager.begin_transaction()
        try:
            sql = """
            INSERT INTO trading_plan (
                plan_date, hunting_date, stock_code, stock_name,
                buy_lower_price, buy_upper_price, position_ratio,
                support_level, stop_loss_price, take_profit_price,
                hold_days, remark
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            success_count = 0
            for plan in plans:
                params = (
                    plan['plan_date'], plan['hunting_date'], plan['stock_code'], plan['stock_name'],
                    plan.get('buy_lower_price'), plan.get('buy_upper_price'), plan.get('position_ratio'),
                    plan.get('support_level'), plan.get('stop_loss_price'), plan.get('take_profit_price'),
                    plan.get('hold_days'), plan.get('remark', '')
                )
                self.db_manager.execute(sql, params)
                success_count += 1
            self.db_manager.commit()
            return success_count
        except Exception as e:
            self.db_manager.rollback()
            logger.error(f"批量保存交易计划失败: {str(e)}")
            raise

    def query_by_hunting_date(self, hunting_date: str) -> List[Dict[str, Any]]:
        """
        按狩猎日期查询交易计划

        参数：
            hunting_date: 狩猎日期

        返回：
            List[Dict[str, Any]]: 交易计划列表
        """
        sql = "SELECT * FROM trading_plan WHERE hunting_date = ? ORDER BY id"
        rows = self.db_manager.query(sql, (hunting_date,))
        return [dict(row) for row in rows]

    def query_by_plan_date(self, plan_date: str) -> List[Dict[str, Any]]:
        """
        按计划日期查询交易计划

        参数：
            plan_date: 计划日期

        返回：
            List[Dict[str, Any]]: 交易计划列表
        """
        sql = "SELECT * FROM trading_plan WHERE plan_date = ? ORDER BY id"
        rows = self.db_manager.query(sql, (plan_date,))
        return [dict(row) for row in rows]

    def delete_by_plan_date(self, plan_date: str) -> int:
        """
        删除指定计划日期的所有交易计划

        参数：
            plan_date: 计划日期

        返回：
            int: 删除的记录数
        """
        self.db_manager.begin_transaction()
        try:
            sql = "DELETE FROM trading_plan WHERE plan_date = ?"
            cursor = self.db_manager.execute(sql, (plan_date,))
            self.db_manager.commit()
            return cursor.rowcount
        except Exception as e:
            self.db_manager.rollback()
            logger.error(f"删除交易计划失败: {str(e)}")
            raise

    def _validate_plan(self, plan: Dict[str, Any]) -> None:
        """
        验证交易计划数据有效性

        参数：
            plan: 交易计划字典

        异常：
            ValueError: 如果数据无效
        """
        required_fields = ['plan_date', 'hunting_date', 'stock_code', 'stock_name']
        for field in required_fields:
            if field not in plan or not plan[field]:
                raise ValueError(f"缺少必填字段: {field}")
        if not isinstance(plan['stock_code'], str) or len(plan['stock_code']) != 6:
            raise ValueError("股票代码必须是6位字符串")