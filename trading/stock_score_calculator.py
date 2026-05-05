# -*- coding: utf-8 -*-
"""
评分计算引擎模块

协调五个维度评分器（技术面、资金面、基本面、板块强度、事件驱动），
计算个股综合评分。支持单只股票评分和批量评分。

评分流程：
  1. 调用各维度评分器的 calculate_score 方法
  2. 检查各维度的一票否决条件
  3. 如果任一维度触发一票否决，综合得分 = -100
  4. 否则按权重加权计算综合得分
  5. 判断评分等级，返回 StockScore 对象

权重配置：
  技术面: 0.25, 资金面: 0.30, 基本面: 0.15,
  板块强度: 0.15, 事件驱动: 0.15
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

# 导入评分结果模型
from trading.stock_score_models import StockScore, SCORE_WEIGHTS, VETO_SCORE
# 导入五个维度评分器
from trading.technical_scorer import TechnicalScorer
from trading.moneyflow_scorer import MoneyflowScorer
from trading.fundamental_scorer import FundamentalScorer
from trading.sector_scorer import SectorScorer
from trading.event_scorer import EventScorer

# 配置日志记录器
logger = logging.getLogger(__name__)

# 批量计算线程池最大工作线程数
MAX_WORKERS = 5


class StockScoreCalculator:
    """
    评分计算引擎

    协调五个维度评分器，计算个股综合评分。
    支持单只股票评分和批量并行评分。
    """

    def __init__(self, db_manager=None, tushare_token=None):
        """
        初始化评分计算引擎，创建五个维度评分器实例

        参数:
            db_manager: 数据库管理器实例，传递给需要数据库的评分器
            tushare_token: Tushare API token，传递给需要 Tushare 的评分器
        """
        # 初始化技术面评分器（依赖本地数据库）
        self.technical_scorer = TechnicalScorer(db_manager=db_manager)
        # 初始化资金面评分器（依赖数据库和 Tushare）
        self.moneyflow_scorer = MoneyflowScorer(
            db_manager=db_manager, tushare_token=tushare_token
        )
        # 初始化基本面评分器（依赖 Tushare）
        self.fundamental_scorer = FundamentalScorer(tushare_token=tushare_token)
        # 初始化板块强度评分器（依赖 Tushare 和本地数据库）
        self.sector_scorer = SectorScorer(tushare_token=tushare_token, db_manager=db_manager)
        # 初始化事件驱动评分器（依赖 Tushare）
        self.event_scorer = EventScorer(tushare_token=tushare_token)
        # 记录初始化完成日志
        logger.info("评分计算引擎初始化完成，五个维度评分器已就绪")

    def calculate_score(self, stock_code: str, score_date: str) -> StockScore:
        """
        计算单只股票的综合评分

        流程：
          1. 调用各维度评分器获取得分和详情
          2. 检查是否有维度触发一票否决
          3. 触发否决则综合得分 = -100，否则加权计算
          4. 设置评分等级和详情信息
          5. 返回 StockScore 对象

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期，格式 YYYY-MM-DD 或 YYYYMMDD
        返回:
            StockScore: 综合评分结果对象
        """
        logger.info(f"开始计算综合评分: {stock_code}, 日期: {score_date}")

        # 获取股票名称
        stock_name = ""
        try:
            from utils.db_manager import DBManager
            db = DBManager()
            cursor = db.execute("SELECT name FROM stock_basic WHERE code = ?", (stock_code,))
            row = cursor.fetchone()
            if row and row[0]:
                stock_name = row[0]
        except Exception as e:
            logger.debug(f"获取股票名称失败: {e}")

        # 创建评分结果对象
        score_obj = StockScore(
            stock_code=stock_code,
            stock_name=stock_name,
            score_date=score_date,
        )

        # ============================================================
        # 第一步：调用各维度评分器，获取得分和详情
        # ============================================================

        # 计算技术面得分
        tech_score, tech_detail = self._safe_calculate(
            "技术面", self.technical_scorer, stock_code, score_date
        )
        # 计算资金面得分
        money_score, money_detail = self._safe_calculate(
            "资金面", self.moneyflow_scorer, stock_code, score_date
        )
        # 计算基本面得分
        fund_score, fund_detail = self._safe_calculate(
            "基本面", self.fundamental_scorer, stock_code, score_date
        )
        # 计算板块强度得分
        sector_score, sector_detail = self._safe_calculate(
            "板块强度", self.sector_scorer, stock_code, score_date
        )
        # 计算事件驱动得分
        event_score, event_detail = self._safe_calculate(
            "事件驱动", self.event_scorer, stock_code, score_date
        )

        # ============================================================
        # 第二步：设置各维度得分到结果对象
        # ============================================================

        # 设置技术面得分
        score_obj.technical_score = tech_score
        # 设置资金面得分
        score_obj.moneyflow_score = money_score
        # 设置基本面得分
        score_obj.fundamental_score = fund_score
        # 设置板块强度得分
        score_obj.sector_score = sector_score
        # 设置事件驱动得分
        score_obj.event_score = event_score

        # ============================================================
        # 第三步：设置各维度详情到结果对象
        # ============================================================

        # 设置技术面详情（转为字典）
        score_obj.technical_detail = (
            tech_detail.to_dict() if hasattr(tech_detail, "to_dict") else {}
        )
        # 设置资金面详情
        score_obj.moneyflow_detail = (
            money_detail.to_dict() if hasattr(money_detail, "to_dict") else {}
        )
        # 设置基本面详情
        score_obj.fundamental_detail = (
            fund_detail.to_dict() if hasattr(fund_detail, "to_dict") else {}
        )
        # 设置板块强度详情
        score_obj.sector_detail = (
            sector_detail.to_dict() if hasattr(sector_detail, "to_dict") else {}
        )
        # 设置事件驱动详情
        score_obj.event_detail = (
            event_detail.to_dict() if hasattr(event_detail, "to_dict") else {}
        )

        # ============================================================
        # 第四步：检查一票否决条件
        # ============================================================

        # 收集所有维度的否决信息
        veto_triggered, veto_reason = self._check_all_vetos(
            tech_detail, money_detail, fund_detail,
            sector_detail, event_detail
        )

        # 如果触发一票否决
        if veto_triggered:
            score_obj.veto_flag = True
            score_obj.veto_reason = veto_reason
            # 一票否决时综合得分固定为 -100
            score_obj.total_score = VETO_SCORE
            # 评分等级为"淘汰"
            score_obj.score_level = StockScore.get_score_level(VETO_SCORE)
            # 记录否决日志
            logger.warning(
                f"股票 {stock_code} 触发一票否决: {veto_reason}, "
                f"综合得分: {VETO_SCORE}"
            )
            return score_obj

        # ============================================================
        # 第五步：计算加权综合得分和评分等级
        # ============================================================

        # 调用模型的加权计算方法
        score_obj.calculate_total_score()

        # 记录最终评分结果
        logger.info(
            f"股票 {stock_code} 综合评分完成: "
            f"总分={score_obj.total_score}, 等级={score_obj.score_level}, "
            f"技术面={tech_score}, 资金面={money_score}, "
            f"基本面={fund_score}, 板块={sector_score}, "
            f"事件={event_score}"
        )
        return score_obj

    def calculate_batch_scores(
        self, stock_codes: List[str], score_date: str
    ) -> List[StockScore]:
        """
        批量计算多只股票的综合评分

        使用 ThreadPoolExecutor 并行计算，每只股票独立计算。
        单只股票计算失败不影响其他股票。

        参数:
            stock_codes: 股票代码列表
            score_date: 评分日期，格式 YYYY-MM-DD 或 YYYYMMDD
        返回:
            List[StockScore]: 评分结果列表
        """
        # 检查输入参数
        if not stock_codes:
            logger.warning("批量评分：股票代码列表为空")
            return []

        logger.info(
            f"开始批量评分: {len(stock_codes)} 只股票, 日期: {score_date}"
        )

        # 存储评分结果
        results: List[StockScore] = []

        # 使用线程池并行计算
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 提交所有计算任务
            future_to_code = {
                executor.submit(
                    self.calculate_score, code, score_date
                ): code
                for code in stock_codes
            }

            # 收集计算结果
            for future in as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    # 获取计算结果
                    score_result = future.result()
                    results.append(score_result)
                    # 记录单只完成日志
                    logger.debug(
                        f"股票 {code} 批量评分完成: {score_result.total_score}"
                    )
                except Exception as e:
                    # 单只股票失败不影响其他
                    logger.error(f"股票 {code} 批量评分失败: {e}")
                    # 创建一个默认的失败结果
                    failed_score = StockScore(
                        stock_code=code, score_date=score_date
                    )
                    # 标记为计算失败
                    failed_score.total_score = 0
                    failed_score.score_level = "回避"
                    results.append(failed_score)

        # 记录批量评分完成日志
        logger.info(
            f"批量评分完成: {len(results)}/{len(stock_codes)} 只股票"
        )
        return results

    def _safe_calculate(
        self, dimension_name: str, scorer, stock_code: str, score_date: str
    ) -> Tuple[float, object]:
        """
        安全调用评分器的 calculate_score 方法

        如果评分器抛出异常，记录错误日志并返回 0 分和空详情。
        确保计算引擎不会因单个维度失败而崩溃。

        参数:
            dimension_name: 维度名称（用于日志）
            scorer: 评分器实例
            stock_code: 股票代码
            score_date: 评分日期
        返回:
            Tuple[float, object]: (维度得分, 详情对象)
        """
        try:
            # 调用评分器的计算方法
            score, detail = scorer.calculate_score(stock_code, score_date)
            # 记录维度得分
            logger.debug(
                f"股票 {stock_code} {dimension_name}得分: {score}"
            )
            return score, detail
        except Exception as e:
            # 评分器异常，记录错误并返回默认值
            logger.error(
                f"股票 {stock_code} {dimension_name}评分失败: {e}"
            )
            # 返回 0 分和一个空的 mock 详情对象
            return 0, _EmptyDetail()

    def _check_all_vetos(
        self, tech_detail, money_detail, fund_detail,
        sector_detail, event_detail
    ) -> Tuple[bool, str]:
        """
        检查所有维度的一票否决条件

        遍历五个维度的详情对象，检查是否有任一维度触发了一票否决。
        返回第一个触发否决的原因。

        参数:
            tech_detail: 技术面详情对象
            money_detail: 资金面详情对象
            fund_detail: 基本面详情对象
            sector_detail: 板块强度详情对象
            event_detail: 事件驱动详情对象
        返回:
            Tuple[bool, str]: (是否触发一票否决, 否决原因)
        """
        # 按维度顺序检查否决条件
        details_with_names = [
            ("技术面", tech_detail),
            ("资金面", money_detail),
            ("基本面", fund_detail),
            ("板块强度", sector_detail),
            ("事件驱动", event_detail),
        ]

        # 遍历每个维度的详情
        for dim_name, detail in details_with_names:
            # 检查详情对象是否有 veto 属性且为 True
            if hasattr(detail, "veto") and detail.veto:
                # 获取否决原因
                reason = getattr(detail, "veto_reason", "")
                # 构建完整的否决原因描述
                full_reason = f"{dim_name}一票否决: {reason}" if reason else f"{dim_name}一票否决"
                logger.warning(f"检测到一票否决: {full_reason}")
                return True, full_reason

        # 所有维度均未触发一票否决
        return False, ""


class _EmptyDetail:
    """
    空详情对象，用于评分器异常时的降级返回

    提供 to_dict() 方法和 veto 属性，
    确保计算引擎能正常处理。
    """

    def __init__(self):
        # 未触发一票否决
        self.veto = False
        # 无否决原因
        self.veto_reason = ""

    def to_dict(self) -> dict:
        """
        返回空字典，表示无详情数据

        返回:
            dict: 空字典
        """
        return {}
