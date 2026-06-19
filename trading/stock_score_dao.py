# -*- coding: utf-8 -*-
"""
个股评分数据访问对象模块 (DAO)

提供 stock_score 和 stock_score_detail 表的数据访问接口，
包括评分的保存、查询、历史记录和排行榜功能。

使用 DBManager 进行数据库操作，支持事务和错误处理。
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# 导入全局数据库管理器
from utils.global_db import get_global_db
# 导入评分数据模型
from trading.stock_score_models import StockScore, ScoreDetail

# 配置日志
logger = logging.getLogger(__name__)


class StockScoreDAO:
    """
    个股评分数据访问对象

    提供 stock_score 和 stock_score_detail 表的 CRUD 操作，
    支持单个保存、批量保存、查询、历史记录和排行榜功能。
    """

    def __init__(self, db_path: str = None):
        """
        初始化评分数据访问对象

        参数:
            db_path: 数据库文件路径（已废弃，使用全局DBManager）
        """
        # 使用全局数据库管理器实例
        self.db = get_global_db()

    def save_score(self, score: StockScore) -> bool:
        """
        保存单个评分结果（INSERT OR REPLACE）

        同时保存评分主表和详情表数据，使用事务保证一致性。
        基于 UNIQUE(stock_code, score_date) 约束实现 upsert。

        参数:
            score: StockScore 评分结果对象
        返回:
            bool: 保存是否成功
        """
        try:
            # 使用事务保证主表和详情表的一致性
            with self.db.transaction():
                # 构建评分主表数据
                score_data = self._build_score_data(score)
                # 执行 INSERT OR REPLACE 写入评分主表
                self._upsert_score(score_data)

                # 构建评分详情表数据
                detail_data = self._build_detail_data(score)
                # 执行 INSERT OR REPLACE 写入详情表
                self._upsert_detail(detail_data)

            logger.info(f"评分保存成功: {score.stock_code} {score.score_date}")
            return True
        except Exception as e:
            # 记录错误日志并返回失败
            logger.error(f"评分保存失败: {score.stock_code} - {str(e)}")
            return False

    def save_batch_scores(self, scores: List[StockScore]) -> int:
        """
        批量保存评分结果

        使用事务批量写入，提高性能。返回成功保存的数量。

        参数:
            scores: StockScore 评分结果列表
        返回:
            int: 成功保存的评分数量
        """
        # 空列表直接返回
        if not scores:
            return 0

        saved_count = 0
        try:
            # 使用事务批量保存
            with self.db.transaction():
                for score in scores:
                    try:
                        # 构建并写入评分主表数据
                        score_data = self._build_score_data(score)
                        self._upsert_score(score_data)

                        # 构建并写入评分详情表数据
                        detail_data = self._build_detail_data(score)
                        self._upsert_detail(detail_data)

                        # 计数成功保存的记录
                        saved_count += 1
                    except Exception as e:
                        # 单条记录失败不影响其他记录
                        logger.warning(
                            f"批量保存中单条失败: {score.stock_code} - {str(e)}"
                        )

            logger.info(f"批量评分保存完成: 成功 {saved_count}/{len(scores)}")
        except Exception as e:
            # 事务级别的错误
            logger.error(f"批量评分保存失败: {str(e)}")

        return saved_count

    def get_score(
        self, stock_code: str, score_date: str
    ) -> Optional[StockScore]:
        """
        获取单个评分结果（关联查询主表和详情表）

        通过 stock_code 和 score_date 联合查询，
        同时获取评分主表和详情表数据。

        参数:
            stock_code: 股票代码
            score_date: 评分日期（格式 YYYY-MM-DD）
        返回:
            StockScore 对象，不存在时返回 None
        """
        try:
            # 关联查询评分主表和详情表
            sql = """
                SELECT s.stock_code, s.stock_name, s.score_date,
                       s.technical_score, s.moneyflow_score,
                       s.fundamental_score, s.sector_score, s.event_score,
                       s.total_score, s.score_level,
                       s.veto_flag, s.veto_reason,
                       s.created_at, s.updated_at,
                       d.technical_strategies, d.moneyflow_details,
                       d.fundamental_details, d.sector_details,
                       d.event_details
                FROM stock_score s
                LEFT JOIN stock_score_detail d
                    ON s.stock_code = d.stock_code
                    AND s.score_date = d.score_date
                WHERE s.stock_code = ? AND s.score_date = ?
            """
            # 执行查询
            row = self.db.query_one(sql, (stock_code, score_date))

            # 无结果返回 None
            if not row:
                return None

            # 将查询结果转换为 StockScore 对象
            return self._row_to_stock_score(row)
        except Exception as e:
            logger.error(
                f"获取评分失败: {stock_code} {score_date} - {str(e)}"
            )
            return None

    def get_history(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> List[StockScore]:
        """
        获取历史评分记录

        按日期范围查询指定股票的历史评分，按日期升序排列。

        参数:
            stock_code: 股票代码
            start_date: 开始日期（格式 YYYY-MM-DD）
            end_date: 结束日期（格式 YYYY-MM-DD）
        返回:
            StockScore 列表，按日期升序排列
        """
        try:
            # 关联查询评分主表和详情表，按日期范围过滤
            sql = """
                SELECT s.stock_code, s.stock_name, s.score_date,
                       s.technical_score, s.moneyflow_score,
                       s.fundamental_score, s.sector_score, s.event_score,
                       s.total_score, s.score_level,
                       s.veto_flag, s.veto_reason,
                       s.created_at, s.updated_at,
                       d.technical_strategies, d.moneyflow_details,
                       d.fundamental_details, d.sector_details,
                       d.event_details
                FROM stock_score s
                LEFT JOIN stock_score_detail d
                    ON s.stock_code = d.stock_code
                    AND s.score_date = d.score_date
                WHERE s.stock_code = ?
                    AND s.score_date >= ?
                    AND s.score_date <= ?
                ORDER BY s.score_date ASC
            """
            # 执行查询
            rows = self.db.query(sql, (stock_code, start_date, end_date))

            # 将每行结果转换为 StockScore 对象
            results = []
            for row in rows:
                score = self._row_to_stock_score(row)
                results.append(score)

            logger.debug(
                f"历史评分查询: {stock_code} {start_date}~{end_date}, "
                f"共 {len(results)} 条"
            )
            return results
        except Exception as e:
            logger.error(
                f"获取历史评分失败: {stock_code} - {str(e)}"
            )
            return []

    def get_ranking(
        self,
        score_date: str,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "total_score",
    ) -> List[Dict[str, Any]]:
        """
        获取评分排行榜

        按指定维度排序，支持分页。返回字典列表便于 API 直接使用。

        参数:
            score_date: 评分日期（格式 YYYY-MM-DD）
            limit: 每页数量，默认 100
            offset: 偏移量，默认 0
            sort_by: 排序字段，默认 total_score，
                     可选 technical_score/moneyflow_score/
                     fundamental_score/sector_score/event_score
        返回:
            排行榜字典列表
        """
        # 允许的排序字段白名单，防止 SQL 注入
        allowed_sort_fields = {
            "total_score", "technical_score", "moneyflow_score",
            "fundamental_score", "sector_score", "event_score",
        }
        # 非法排序字段回退到默认值
        if sort_by not in allowed_sort_fields:
            sort_by = "total_score"

        try:
            # 查询排行榜数据，按指定字段降序排列
            sql = f"""
                SELECT stock_code, stock_name, score_date,
                       technical_score, moneyflow_score,
                       fundamental_score, sector_score, event_score,
                       total_score, score_level,
                       veto_flag, veto_reason
                FROM stock_score
                WHERE score_date = ?
                ORDER BY {sort_by} DESC
                LIMIT ? OFFSET ?
            """
            # 执行查询
            rows = self.db.query(sql, (score_date, limit, offset))

            logger.debug(
                f"排行榜查询: {score_date} sort={sort_by}, "
                f"共 {len(rows)} 条"
            )
            return rows
        except Exception as e:
            logger.error(f"获取排行榜失败: {score_date} - {str(e)}")
            return []

    # ============================================================
    # 私有辅助方法
    # ============================================================

    def _build_score_data(self, score: StockScore) -> dict:
        """
        构建评分主表数据字典

        将 StockScore 对象转换为数据库字段字典。

        参数:
            score: StockScore 评分结果对象
        返回:
            dict: 评分主表字段字典
        """
        # 获取当前时间戳
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "stock_code": score.stock_code,
            "stock_name": score.stock_name,
            "score_date": score.score_date,
            # 各维度得分
            "technical_score": score.technical_score,
            "moneyflow_score": score.moneyflow_score,
            "fundamental_score": score.fundamental_score,
            "sector_score": score.sector_score,
            "event_score": score.event_score,
            # 综合得分和等级
            "total_score": score.total_score,
            "score_level": score.score_level,
            # 一票否决信息
            "veto_flag": 1 if score.veto_flag else 0,
            "veto_reason": score.veto_reason or "",
            # 时间戳
            "updated_at": now,
        }

    def _build_detail_data(self, score: StockScore) -> dict:
        """
        构建评分详情表数据字典

        将 StockScore 中的各维度详情序列化为 JSON 字符串。

        参数:
            score: StockScore 评分结果对象
        返回:
            dict: 评分详情表字段字典
        """
        return {
            "stock_code": score.stock_code,
            "score_date": score.score_date,
            # 技术面详情 JSON
            "technical_strategies": json.dumps(
                score.technical_detail, ensure_ascii=False
            ) if score.technical_detail else "{}",
            # 资金面详情 JSON
            "moneyflow_details": json.dumps(
                score.moneyflow_detail, ensure_ascii=False
            ) if score.moneyflow_detail else "{}",
            # 基本面详情 JSON
            "fundamental_details": json.dumps(
                score.fundamental_detail, ensure_ascii=False
            ) if score.fundamental_detail else "{}",
            # 板块强度详情 JSON
            "sector_details": json.dumps(
                score.sector_detail, ensure_ascii=False
            ) if score.sector_detail else "{}",
            # 事件驱动详情 JSON
            "event_details": json.dumps(
                score.event_detail, ensure_ascii=False
            ) if score.event_detail else "{}",
        }

    def _upsert_score(self, data: dict) -> None:
        """
        执行评分主表的 INSERT OR REPLACE 操作

        基于 UNIQUE(stock_code, score_date) 约束实现 upsert。

        参数:
            data: 评分主表字段字典
        """
        # 构建 INSERT OR REPLACE SQL
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data])
        sql = f"INSERT OR REPLACE INTO stock_score ({columns}) VALUES ({placeholders})"
        # 执行写入（带重试机制）
        self.db.execute_with_retry(sql, tuple(data.values()))

    def _upsert_detail(self, data: dict) -> None:
        """
        执行评分详情表的 INSERT OR REPLACE 操作

        使用 INSERT OR REPLACE 替代 DELETE + INSERT，减少锁定时间，保证原子性。
        依赖 stock_score_detail 表的 UNIQUE(stock_code, score_date) 约束。

        参数:
            data: 评分详情表字段字典
        """
        # 使用 INSERT OR REPLACE 替代 DELETE + INSERT，减少操作次数和锁定时间
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data])
        sql = f"INSERT OR REPLACE INTO stock_score_detail ({columns}) VALUES ({placeholders})"
        # 执行写入（带重试机制，事务中使用同一连接）
        self.db.execute_with_retry(sql, tuple(data.values()))

    def _row_to_stock_score(self, row: dict) -> StockScore:
        """
        将数据库查询行转换为 StockScore 对象

        解析主表字段和详情表的 JSON 字段。

        参数:
            row: 数据库查询结果字典
        返回:
            StockScore 对象
        """
        # 创建 StockScore 对象并填充基本信息
        score = StockScore(
            stock_code=row.get("stock_code", ""),
            stock_name=row.get("stock_name", ""),
            score_date=row.get("score_date", ""),
        )

        # 填充各维度得分
        score.technical_score = row.get("technical_score", 0) or 0
        score.moneyflow_score = row.get("moneyflow_score", 0) or 0
        score.fundamental_score = row.get("fundamental_score", 0) or 0
        score.sector_score = row.get("sector_score", 0) or 0
        score.event_score = row.get("event_score", 0) or 0

        # 填充综合得分和等级
        score.total_score = row.get("total_score", 0) or 0
        score.score_level = row.get("score_level", "")

        # 填充一票否决信息
        score.veto_flag = bool(row.get("veto_flag", 0))
        score.veto_reason = row.get("veto_reason", "")

        # 解析技术面详情 JSON
        score.technical_detail = self._parse_json_field(
            row.get("technical_strategies")
        )
        # 解析资金面详情 JSON
        score.moneyflow_detail = self._parse_json_field(
            row.get("moneyflow_details")
        )
        # 解析基本面详情 JSON
        score.fundamental_detail = self._parse_json_field(
            row.get("fundamental_details")
        )
        # 解析板块强度详情 JSON
        score.sector_detail = self._parse_json_field(
            row.get("sector_details")
        )
        # 解析事件驱动详情 JSON
        score.event_detail = self._parse_json_field(
            row.get("event_details")
        )

        return score

    def _parse_json_field(self, value: Optional[str]) -> dict:
        """
        安全解析 JSON 字段

        处理 None、空字符串和无效 JSON 的情况。

        参数:
            value: JSON 字符串或 None
        返回:
            dict: 解析后的字典，解析失败返回空字典
        """
        # 空值返回空字典
        if not value:
            return {}
        try:
            # 尝试解析 JSON
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            # 解析失败返回空字典
            logger.warning(f"JSON 解析失败: {value[:50]}...")
            return {}
