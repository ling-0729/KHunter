# -*- coding: utf-8 -*-
"""
个股图谱评分数据模型模块

定义评分系统中使用的所有数据模型类，包括：
- StockScore: 股票综合评分结果模型
- ScoreDetail: 评分详情汇总模型
- TechnicalDetail: 技术面评分详情
- MoneyflowDetail: 资金面评分详情
- FundamentalDetail: 基本面评分详情
- SectorDetail: 板块强度评分详情
- EventDetail: 事件驱动评分详情
"""

import json
from typing import List, Optional


# ============================================================
# 评分等级常量定义
# ============================================================

# 各维度权重配置
SCORE_WEIGHTS = {
    "technical": 0.35,    # 技术面权重 35%
    "moneyflow": 0.35,    # 资金面权重 35%
    "fundamental": 0.10,  # 基本面权重 10%
    "sector": 0.10,       # 板块强度权重 10%
    "event": 0.10,        # 事件驱动权重 10%
}

# 一票否决时的固定得分
VETO_SCORE = -100


class TechnicalDetail:
    """
    技术面评分详情模型

    记录技术面评分的详细信息，包括命中的策略列表和一票否决信息。
    技术面得分 = Σ(策略权重 × 命中标志)
    """

    def __init__(self):
        # 命中的策略列表，每个元素为 {"name": "策略名", "weight": 权重值}
        self.strategies: List[dict] = []
        # 是否触发一票否决（M头 + 多死叉共振同时命中）
        self.veto: bool = False
        # 一票否决原因说明
        self.veto_reason: str = ""

    def to_dict(self) -> dict:
        """
        将技术面详情序列化为字典

        返回:
            dict: 包含策略列表和否决信息的字典
        """
        return {
            # 命中策略列表
            "strategies": self.strategies,
            # 一票否决标志
            "veto": self.veto,
            # 否决原因
            "veto_reason": self.veto_reason,
        }

    @staticmethod
    def from_dict(data: dict) -> "TechnicalDetail":
        """
        从字典创建技术面详情对象

        参数:
            data: 包含技术面详情的字典
        返回:
            TechnicalDetail 实例
        """
        detail = TechnicalDetail()
        # 解析策略列表
        detail.strategies = data.get("strategies", [])
        # 解析否决标志
        detail.veto = data.get("veto", False)
        # 解析否决原因
        detail.veto_reason = data.get("veto_reason", "")
        return detail


class MoneyflowDetail:
    """
    资金面评分详情模型

    记录资金面评分的四个维度详细信息：
    - 主力资金净流入（5日累计）
    - 大单占比（近5日）
    - 北向资金（最近季度）
    - 主力与散户方向
    """

    def __init__(self):
        # 5日主力资金净流入金额（万元）
        self.main_net_flow: float = 0
        # 主力净流入维度得分
        self.main_net_flow_score: float = 0
        # 大单占比维度得分
        self.large_ratio_score: float = 0
        # 北向资金状态：increase/decrease/hold/none
        self.north_fund_status: str = "none"
        # 北向资金维度得分
        self.north_fund_score: float = 0
        # 主力与散户方向维度得分
        self.direction_score: float = 0
        # 是否触发一票否决
        self.veto: bool = False
        # 一票否决原因
        self.veto_reason: str = ""

    def to_dict(self) -> dict:
        """
        将资金面详情序列化为字典

        返回:
            dict: 包含资金面四个维度详情的字典
        """
        return {
            # 主力净流入金额
            "main_net_flow": self.main_net_flow,
            # 主力净流入得分
            "main_net_flow_score": self.main_net_flow_score,
            # 大单占比得分
            "large_ratio_score": self.large_ratio_score,
            # 北向资金状态
            "north_fund_status": self.north_fund_status,
            # 北向资金得分
            "north_fund_score": self.north_fund_score,
            # 主力散户方向得分
            "direction_score": self.direction_score,
            # 一票否决标志
            "veto": self.veto,
            # 否决原因
            "veto_reason": self.veto_reason,
        }

    @staticmethod
    def from_dict(data: dict) -> "MoneyflowDetail":
        """
        从字典创建资金面详情对象

        参数:
            data: 包含资金面详情的字典
        返回:
            MoneyflowDetail 实例
        """
        detail = MoneyflowDetail()
        # 解析主力净流入金额
        detail.main_net_flow = data.get("main_net_flow", 0)
        # 解析主力净流入得分
        detail.main_net_flow_score = data.get("main_net_flow_score", 0)
        # 解析大单占比得分
        detail.large_ratio_score = data.get("large_ratio_score", 0)
        # 解析北向资金状态
        detail.north_fund_status = data.get("north_fund_status", "none")
        # 解析北向资金得分
        detail.north_fund_score = data.get("north_fund_score", 0)
        # 解析方向得分
        detail.direction_score = data.get("direction_score", 0)
        # 解析否决标志
        detail.veto = data.get("veto", False)
        # 解析否决原因
        detail.veto_reason = data.get("veto_reason", "")
        return detail


class FundamentalDetail:
    """
    基本面评分详情模型

    记录基本面评分的三个维度详细信息：
    - 净利润增速（net_profit_yoy）
    - 净资产收益率 ROE（roe）
    - 经营现金流与收入比（ocf_to_income）
    得分范围：-60 到 +60
    """

    def __init__(self):
        # 净利润同比增速（%）
        self.net_profit_yoy: Optional[float] = None
        # 净利润增速维度得分
        self.net_profit_yoy_score: float = 0
        # 净资产收益率（%）
        self.roe: Optional[float] = None
        # ROE维度得分
        self.roe_score: float = 0
        # 经营现金流与收入比
        self.ocf_to_income: Optional[float] = None
        # 经营现金流维度得分
        self.ocf_to_income_score: float = 0
        # 是否触发一票否决
        self.veto: bool = False
        # 一票否决原因
        self.veto_reason: str = ""

    def to_dict(self) -> dict:
        """
        将基本面详情序列化为字典

        返回:
            dict: 包含基本面三个维度详情的字典
        """
        return {
            # 净利润同比增速
            "net_profit_yoy": self.net_profit_yoy,
            # 净利润增速得分
            "net_profit_yoy_score": self.net_profit_yoy_score,
            # 净资产收益率
            "roe": self.roe,
            # ROE得分
            "roe_score": self.roe_score,
            # 经营现金流比
            "ocf_to_income": self.ocf_to_income,
            # 经营现金流得分
            "ocf_to_income_score": self.ocf_to_income_score,
            # 一票否决标志
            "veto": self.veto,
            # 否决原因
            "veto_reason": self.veto_reason,
        }

    @staticmethod
    def from_dict(data: dict) -> "FundamentalDetail":
        """
        从字典创建基本面详情对象

        参数:
            data: 包含基本面详情的字典
        返回:
            FundamentalDetail 实例
        """
        detail = FundamentalDetail()
        # 解析净利润增速
        detail.net_profit_yoy = data.get("net_profit_yoy")
        # 解析净利润增速得分
        detail.net_profit_yoy_score = data.get("net_profit_yoy_score", 0)
        # 解析ROE
        detail.roe = data.get("roe")
        # 解析ROE得分
        detail.roe_score = data.get("roe_score", 0)
        # 解析经营现金流比
        detail.ocf_to_income = data.get("ocf_to_income")
        # 解析经营现金流得分
        detail.ocf_to_income_score = data.get("ocf_to_income_score", 0)
        # 解析否决标志
        detail.veto = data.get("veto", False)
        # 解析否决原因
        detail.veto_reason = data.get("veto_reason", "")
        return detail


class SectorDetail:
    """
    板块强度评分详情模型

    记录板块强度评分的详细信息：
    - 板块名称
    - 涨幅排名得分（近5日）
    - 资金流向得分（近5日）
    得分范围：-100 到 +200
    """

    def __init__(self):
        # 所属板块名称
        self.sector_name: str = ""
        # 近5日涨幅排名总分（0 ~ 100）
        self.rank_score: float = 0
        # 近5日资金流向总分（-100 ~ +100）
        self.moneyflow_score: float = 0
        # 是否触发一票否决（板块得分 -100）
        self.veto: bool = False
        # 一票否决原因
        self.veto_reason: str = ""

    def to_dict(self) -> dict:
        """
        将板块强度详情序列化为字典

        返回:
            dict: 包含板块强度详情的字典
        """
        return {
            # 板块名称
            "sector_name": self.sector_name,
            # 涨幅排名得分
            "rank_score": self.rank_score,
            # 资金流向得分
            "moneyflow_score": self.moneyflow_score,
            # 一票否决标志
            "veto": self.veto,
            # 否决原因
            "veto_reason": self.veto_reason,
        }

    @staticmethod
    def from_dict(data: dict) -> "SectorDetail":
        """
        从字典创建板块强度详情对象

        参数:
            data: 包含板块强度详情的字典
        返回:
            SectorDetail 实例
        """
        detail = SectorDetail()
        # 解析板块名称
        detail.sector_name = data.get("sector_name", "")
        # 解析涨幅排名得分
        detail.rank_score = data.get("rank_score", 0)
        # 解析资金流向得分
        detail.moneyflow_score = data.get("moneyflow_score", 0)
        # 解析否决标志
        detail.veto = data.get("veto", False)
        # 解析否决原因
        detail.veto_reason = data.get("veto_reason", "")
        return detail


class EventDetail:
    """
    事件驱动评分详情模型

    记录事件驱动评分的详细信息：
    - 正面事件列表（加分项）
    - 负面事件列表（减分项）
    得分范围：-100 到 +100
    """

    def __init__(self):
        # 正面事件列表，每个元素为 {"type": "事件类型", "score": 分值, "date": "日期"}
        self.positive_events: List[dict] = []
        # 负面事件列表，每个元素为 {"type": "事件类型", "score": 分值, "date": "日期"}
        self.negative_events: List[dict] = []
        # 是否触发一票否决（ST/*ST、业绩暴雷、大股东减持）
        self.veto: bool = False
        # 一票否决原因
        self.veto_reason: str = ""

    def to_dict(self) -> dict:
        """
        将事件驱动详情序列化为字典

        返回:
            dict: 包含正面/负面事件列表和否决信息的字典
        """
        return {
            # 正面事件列表
            "positive_events": self.positive_events,
            # 负面事件列表
            "negative_events": self.negative_events,
            # 一票否决标志
            "veto": self.veto,
            # 否决原因
            "veto_reason": self.veto_reason,
        }

    @staticmethod
    def from_dict(data: dict) -> "EventDetail":
        """
        从字典创建事件驱动详情对象

        参数:
            data: 包含事件驱动详情的字典
        返回:
            EventDetail 实例
        """
        detail = EventDetail()
        # 解析正面事件列表
        detail.positive_events = data.get("positive_events", [])
        # 解析负面事件列表
        detail.negative_events = data.get("negative_events", [])
        # 解析否决标志
        detail.veto = data.get("veto", False)
        # 解析否决原因
        detail.veto_reason = data.get("veto_reason", "")
        return detail


class ScoreDetail:
    """
    评分详情汇总模型

    汇总五个维度的评分详情，用于存储到 stock_score_detail 表。
    每个维度的详情以 JSON 格式存储。
    """

    def __init__(self):
        # 技术面详情
        self.technical: TechnicalDetail = TechnicalDetail()
        # 资金面详情
        self.moneyflow: MoneyflowDetail = MoneyflowDetail()
        # 基本面详情
        self.fundamental: FundamentalDetail = FundamentalDetail()
        # 板块强度详情
        self.sector: SectorDetail = SectorDetail()
        # 事件驱动详情
        self.event: EventDetail = EventDetail()

    def to_dict(self) -> dict:
        """
        将评分详情汇总序列化为字典

        返回:
            dict: 包含五个维度详情的字典
        """
        return {
            # 技术面详情
            "technical": self.technical.to_dict(),
            # 资金面详情
            "moneyflow": self.moneyflow.to_dict(),
            # 基本面详情
            "fundamental": self.fundamental.to_dict(),
            # 板块强度详情
            "sector": self.sector.to_dict(),
            # 事件驱动详情
            "event": self.event.to_dict(),
        }

    def to_json_fields(self) -> dict:
        """
        将各维度详情转换为 JSON 字符串，用于数据库存储

        返回:
            dict: 各维度详情的 JSON 字符串字典
        """
        return {
            # 技术面详情 JSON
            "technical_strategies": json.dumps(
                self.technical.to_dict(), ensure_ascii=False
            ),
            # 资金面详情 JSON
            "moneyflow_details": json.dumps(
                self.moneyflow.to_dict(), ensure_ascii=False
            ),
            # 基本面详情 JSON
            "fundamental_details": json.dumps(
                self.fundamental.to_dict(), ensure_ascii=False
            ),
            # 板块强度详情 JSON
            "sector_details": json.dumps(
                self.sector.to_dict(), ensure_ascii=False
            ),
            # 事件驱动详情 JSON
            "event_details": json.dumps(
                self.event.to_dict(), ensure_ascii=False
            ),
        }

    @staticmethod
    def from_dict(data: dict) -> "ScoreDetail":
        """
        从字典创建评分详情汇总对象

        参数:
            data: 包含五个维度详情的字典
        返回:
            ScoreDetail 实例
        """
        detail = ScoreDetail()
        # 解析技术面详情
        if "technical" in data:
            detail.technical = TechnicalDetail.from_dict(data["technical"])
        # 解析资金面详情
        if "moneyflow" in data:
            detail.moneyflow = MoneyflowDetail.from_dict(data["moneyflow"])
        # 解析基本面详情
        if "fundamental" in data:
            detail.fundamental = FundamentalDetail.from_dict(data["fundamental"])
        # 解析板块强度详情
        if "sector" in data:
            detail.sector = SectorDetail.from_dict(data["sector"])
        # 解析事件驱动详情
        if "event" in data:
            detail.event = EventDetail.from_dict(data["event"])
        return detail

    @staticmethod
    def from_json_fields(
        technical_strategies: str = "{}",
        moneyflow_details: str = "{}",
        fundamental_details: str = "{}",
        sector_details: str = "{}",
        event_details: str = "{}",
    ) -> "ScoreDetail":
        """
        从数据库 JSON 字段创建评分详情汇总对象

        参数名与数据库字段名一致，便于直接传入查询结果。

        参数:
            technical_strategies: 技术面详情 JSON 字符串
            moneyflow_details: 资金面详情 JSON 字符串
            fundamental_details: 基本面详情 JSON 字符串
            sector_details: 板块强度详情 JSON 字符串
            event_details: 事件驱动详情 JSON 字符串
        返回:
            ScoreDetail 实例
        """
        detail = ScoreDetail()
        # 解析技术面 JSON
        detail.technical = TechnicalDetail.from_dict(
            json.loads(technical_strategies) if technical_strategies else {}
        )
        # 解析资金面 JSON
        detail.moneyflow = MoneyflowDetail.from_dict(
            json.loads(moneyflow_details) if moneyflow_details else {}
        )
        # 解析基本面 JSON
        detail.fundamental = FundamentalDetail.from_dict(
            json.loads(fundamental_details) if fundamental_details else {}
        )
        # 解析板块强度 JSON
        detail.sector = SectorDetail.from_dict(
            json.loads(sector_details) if sector_details else {}
        )
        # 解析事件驱动 JSON
        detail.event = EventDetail.from_dict(
            json.loads(event_details) if event_details else {}
        )
        return detail


class StockScore:
    """
    股票综合评分结果模型

    整合技术面、资金面、基本面、板块强度和事件驱动五个维度的评分，
    计算综合得分并判断评分等级。支持一票否决机制。

    综合得分计算公式：
        total = technical × 0.25 + moneyflow × 0.30 + fundamental × 0.15
                + sector × 0.15 + event × 0.15
    """

    def __init__(
        self,
        stock_code: str = "",
        stock_name: str = "",
        score_date: str = "",
    ):
        # 股票代码（6位数字）
        self.stock_code: str = stock_code
        # 股票名称
        self.stock_name: str = stock_name
        # 评分日期（格式：YYYYMMDD）
        self.score_date: str = score_date

        # 技术面得分（不限范围，策略权重累加）
        self.technical_score: float = 0
        # 资金面得分（-100 ~ 100）
        self.moneyflow_score: float = 0
        # 基本面得分（-60 ~ +60）
        self.fundamental_score: float = 0
        # 板块强度得分（-100 ~ +200）
        self.sector_score: float = 0
        # 事件驱动得分（-100 ~ +100）
        self.event_score: float = 0

        # 综合得分（加权计算后的结果）
        self.total_score: float = 0
        # 评分等级（强烈推荐/推荐/中性/谨慎/回避/淘汰）
        self.score_level: str = ""

        # 一票否决标志
        self.veto_flag: bool = False
        # 一票否决原因
        self.veto_reason: str = ""

        # 各维度评分详情
        self.technical_detail: dict = {}
        self.moneyflow_detail: dict = {}
        self.fundamental_detail: dict = {}
        self.sector_detail: dict = {}
        self.event_detail: dict = {}

    def calculate_total_score(self) -> float:
        """
        根据各维度得分和权重计算综合得分

        计算公式：
            total = technical × 0.25 + moneyflow × 0.30 + fundamental × 0.15
                    + sector × 0.15 + event × 0.15

        如果触发一票否决，综合得分直接为 -100。

        返回:
            float: 综合得分
        """
        # 一票否决时直接返回 -100
        if self.veto_flag:
            self.total_score = VETO_SCORE
            # 设置淘汰等级
            self.score_level = self.get_score_level(self.total_score)
            return self.total_score

        # 按权重加权计算综合得分
        self.total_score = (
            self.technical_score * SCORE_WEIGHTS["technical"]
            + self.moneyflow_score * SCORE_WEIGHTS["moneyflow"]
            + self.fundamental_score * SCORE_WEIGHTS["fundamental"]
            + self.sector_score * SCORE_WEIGHTS["sector"]
            + self.event_score * SCORE_WEIGHTS["event"]
        )

        # 四舍五入保留一位小数
        self.total_score = round(self.total_score, 1)
        # 根据综合得分判断评分等级
        self.score_level = self.get_score_level(self.total_score)
        return self.total_score

    @staticmethod
    def get_score_level(total_score: float) -> str:
        """
        根据综合得分判断评分等级

        评分等级对照表：
            ≥ 80    → 强烈推荐
            60-79   → 推荐
            40-59   → 中性
            20-39   → 谨慎
            < 20    → 回避
            -100    → 淘汰（一票否决）

        参数:
            total_score: 综合得分
        返回:
            str: 评分等级名称
        """
        # 一票否决：得分为 -100 时直接淘汰
        if total_score == VETO_SCORE:
            return "淘汰"
        # 强烈推荐：得分 >= 80
        if total_score >= 80:
            return "强烈推荐"
        # 推荐：得分 60-79
        if total_score >= 60:
            return "推荐"
        # 中性：得分 40-59
        if total_score >= 40:
            return "中性"
        # 谨慎：得分 20-39
        if total_score >= 20:
            return "谨慎"
        # 回避：得分 < 20
        return "回避"

    def to_dict(self) -> dict:
        """
        将评分结果序列化为字典，用于 API 响应

        返回格式与需求文档中定义的 API 响应格式一致。

        返回:
            dict: 完整的评分结果字典
        """
        return {
            # 股票基本信息
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "score_date": self.score_date,
            # 综合评分信息
            "total_score": self.total_score,
            "score_level": self.score_level,
            # 五维度评分详情
            "dimensions": {
                "technical": {
                    "score": self.technical_score,
                    "weight": SCORE_WEIGHTS["technical"],
                    # 加权得分
                    "weighted_score": round(
                        self.technical_score * SCORE_WEIGHTS["technical"], 2
                    ),
                    # 技术面详情
                    **self.technical_detail,
                },
                "moneyflow": {
                    "score": self.moneyflow_score,
                    "weight": SCORE_WEIGHTS["moneyflow"],
                    # 加权得分
                    "weighted_score": round(
                        self.moneyflow_score * SCORE_WEIGHTS["moneyflow"], 2
                    ),
                    # 资金面详情
                    "details": self.moneyflow_detail,
                },
                "fundamental": {
                    "score": self.fundamental_score,
                    "weight": SCORE_WEIGHTS["fundamental"],
                    # 加权得分
                    "weighted_score": round(
                        self.fundamental_score * SCORE_WEIGHTS["fundamental"], 2
                    ),
                    # 基本面详情
                    "details": self.fundamental_detail,
                },
                "sector": {
                    "score": self.sector_score,
                    "weight": SCORE_WEIGHTS["sector"],
                    # 加权得分
                    "weighted_score": round(
                        self.sector_score * SCORE_WEIGHTS["sector"], 2
                    ),
                    # 板块详情
                    **self.sector_detail,
                },
                "event": {
                    "score": self.event_score,
                    "weight": SCORE_WEIGHTS["event"],
                    # 加权得分
                    "weighted_score": round(
                        self.event_score * SCORE_WEIGHTS["event"], 2
                    ),
                    # 事件详情
                    **self.event_detail,
                },
            },
            # 一票否决信息
            "veto_flag": self.veto_flag,
            "veto_reason": self.veto_reason,
        }

    @staticmethod
    def from_dict(data: dict) -> "StockScore":
        """
        从字典创建评分结果对象

        参数:
            data: 包含评分结果的字典
        返回:
            StockScore 实例
        """
        score = StockScore(
            # 解析股票代码
            stock_code=data.get("stock_code", ""),
            # 解析股票名称
            stock_name=data.get("stock_name", ""),
            # 解析评分日期
            score_date=data.get("score_date", ""),
        )
        # 解析各维度得分
        score.technical_score = data.get("technical_score", 0)
        score.moneyflow_score = data.get("moneyflow_score", 0)
        score.fundamental_score = data.get("fundamental_score", 0)
        score.sector_score = data.get("sector_score", 0)
        score.event_score = data.get("event_score", 0)
        # 解析综合得分和等级
        score.total_score = data.get("total_score", 0)
        score.score_level = data.get("score_level", "")
        # 解析一票否决信息
        score.veto_flag = data.get("veto_flag", False)
        score.veto_reason = data.get("veto_reason", "")
        # 解析各维度详情
        score.technical_detail = data.get("technical_detail", {})
        score.moneyflow_detail = data.get("moneyflow_detail", {})
        score.fundamental_detail = data.get("fundamental_detail", {})
        score.sector_detail = data.get("sector_detail", {})
        score.event_detail = data.get("event_detail", {})
        return score

    def __repr__(self) -> str:
        """
        返回评分结果的字符串表示，便于调试

        返回:
            str: 格式化的评分摘要
        """
        # 格式化输出评分摘要信息
        return (
            f"StockScore({self.stock_code} {self.stock_name} "
            f"total={self.total_score} level={self.score_level} "
            f"veto={self.veto_flag})"
        )
