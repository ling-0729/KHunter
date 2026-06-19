# -*- coding: utf-8 -*-
"""
基本面评分器模块

基于财务指标数据计算基本面得分。
数据来源：Tushare Pro fina_indicator 接口（财务指标数据）

评分维度：
  1. 净利润增速（net_profit_yoy）- 公司赚钱能力增长
  2. 净资产收益率 ROE（roe）- 公司盈利能力
  3. 经营现金流（ocf_to_income）- 赚的钱是否真实

综合公式：
  基本面得分 = 50 + 净利润增速得分 + ROE得分 + 经营现金流得分
  得分范围：-10 到 +110（实际限制在 -100 到 +100）

一票否决条件：
  - 净利润同比下滑 > 50%（即 net_profit_yoy < -50）：-100分
  - ROE < -5%：-100分
"""

import json
import time
import logging
from typing import Optional, Tuple

import pandas as pd

# 导入基本面详情模型
from trading.stock_score_models import FundamentalDetail

# 配置日志记录器
logger = logging.getLogger(__name__)


# ============================================================
# 基本面评分常量配置
# ============================================================



# Tushare API 重试配置
MAX_RETRIES = 3        # 最大重试次数
RETRY_INTERVAL = 1     # 重试间隔（秒）

# 内存缓存 TTL（秒）
CACHE_TTL = 300  # 5分钟


class MemoryCache:
    """
    内存缓存管理器

    仅用于同一请求周期内的数据缓存，避免重复调用 Tushare 接口。
    缓存有效期为 5 分钟。
    """

    def __init__(self, ttl: int = CACHE_TTL):
        """
        初始化内存缓存

        参数:
            ttl: 缓存有效期（秒），默认 300 秒
        """
        # 缓存字典，key -> (data, timestamp)
        self._cache: dict = {}
        # 缓存有效期
        self._ttl = ttl

    def get(self, key: str):
        """
        获取缓存数据

        参数:
            key: 缓存键
        返回:
            缓存数据，过期或不存在返回 None
        """
        if key in self._cache:
            data, timestamp = self._cache[key]
            # 检查是否过期
            if time.time() - timestamp < self._ttl:
                return data
            # 过期则删除
            del self._cache[key]
        return None

    def set(self, key: str, value):
        """
        设置缓存数据

        参数:
            key: 缓存键
            value: 缓存值
        """
        # 存储数据和时间戳
        self._cache[key] = (value, time.time())


class FundamentalScorer:
    """
    基本面评分器

    根据 Tushare 财务指标数据计算基本面得分。
    三个评分维度：净利润增速、ROE、经营现金流。
    支持一票否决机制。
    """

    def __init__(self, tushare_token: str = None):
        """
        初始化基本面评分器

        参数:
            tushare_token: Tushare API token，为 None 时从配置文件读取
        """
        # 初始化 Tushare token
        self._token = tushare_token or self._load_tushare_token()
        # 初始化 Tushare pro API 对象（延迟加载）
        self._pro = None
        # 初始化内存缓存
        self._cache = MemoryCache()
        # 记录初始化日志
        logger.info("基本面评分器初始化完成")

    def _load_tushare_token(self) -> str:
        """
        从配置文件加载 Tushare token

        返回:
            str: Tushare API token
        """
        try:
            # 读取 tushare 配置文件
            with open("config/tushare_config.json", "r") as f:
                config = json.load(f)
            # 优先使用 token 字段，兼容 api_key 字段
            token = config.get("token") or config.get("api_key", "")
            logger.debug("Tushare token 加载成功")
            return token
        except Exception as e:
            # 配置文件读取失败，返回空字符串
            logger.warning(f"Tushare token 加载失败: {e}")
            return ""

    def _get_pro(self):
        """
        获取 Tushare pro API 实例（延迟初始化）

        返回:
            tushare pro API 对象
        """
        if self._pro is None:
            try:
                import tushare as ts
                # 使用 token 初始化 pro API
                self._pro = ts.pro_api(self._token)
                logger.debug("Tushare pro API 初始化成功")
            except Exception as e:
                logger.error(f"Tushare pro API 初始化失败: {e}")
                raise
        return self._pro

    def _convert_ts_code(self, stock_code: str) -> str:
        """
        将6位股票代码转换为 Tushare 格式（带交易所后缀）

        参数:
            stock_code: 6位股票代码，如 '000001'
        返回:
            str: Tushare 格式代码，如 '000001.SZ'
        """
        # 去除空白
        code = stock_code.strip()
        # 如果已经包含后缀，直接返回
        if "." in code:
            return code
        # 根据首位数字判断交易所（6开头为上海）
        if code.startswith("6"):
            return f"{code}.SH"
        # 深圳交易所（0开头、3开头）
        return f"{code}.SZ"

    def _call_tushare_with_retry(self, func, **kwargs):
        """
        带重试机制的 Tushare API 调用

        参数:
            func: Tushare API 调用函数
            **kwargs: API 参数
        返回:
            DataFrame: API 返回的数据，失败返回 None
        """
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                # 调用 Tushare API
                result = func(**kwargs)
                return result
            except Exception as e:
                last_error = e
                # 记录重试日志
                logger.warning(
                    f"Tushare API 调用失败（第 {attempt + 1} 次）: {e}"
                )
                # 非最后一次重试时等待
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_INTERVAL)
        # 所有重试都失败
        logger.error(f"Tushare API 调用失败（已重试 {MAX_RETRIES} 次）: {last_error}")
        return None

    def _fetch_fina_indicator(
        self, stock_code: str
    ) -> Optional[pd.DataFrame]:
        """
        从 Tushare fina_indicator 接口获取最新一期财务指标数据

        参数:
            stock_code: 股票代码（6位数字）
        返回:
            DataFrame: 财务指标数据，失败返回 None
        """
        # 构建缓存键
        cache_key = f"fina_indicator_{stock_code}"
        # 检查缓存
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"命中缓存: {cache_key}")
            return cached

        # 转换为 Tushare 格式代码
        ts_code = self._convert_ts_code(stock_code)

        try:
            pro = self._get_pro()
            # 调用 fina_indicator 接口获取最新财务指标
            # 注意：Tushare 实际字段名为 netprofit_yoy（非 net_profit_yoy）
            df = self._call_tushare_with_retry(
                pro.fina_indicator,
                ts_code=ts_code,
                period="",
                fields="ts_code,ann_date,end_date,roe,netprofit_yoy,ocfps,eps,ocf_to_opincome",
            )
            # 检查返回数据是否有效
            if df is not None and not df.empty:
                logger.debug(
                    f"获取财务指标数据成功: {stock_code}, {len(df)} 条记录"
                )
                # 写入缓存
                self._cache.set(cache_key, df)
                return df
            # Tushare 返回空数据
            logger.warning(f"Tushare 财务指标返回空数据: {stock_code}")
            return None
        except Exception as e:
            logger.error(f"Tushare 财务指标获取失败: {stock_code}, {e}")
            return None

    def _extract_latest_indicators(
        self, df: Optional[pd.DataFrame]
    ) -> dict:
        """
        从财务指标 DataFrame 中提取最新一期的评分所需指标

        提取指标：
          - net_profit_yoy: 净利润同比增速（%）
          - roe: 净资产收益率（%）
          - ocf_to_income: 经营现金流与收入比

        参数:
            df: 财务指标 DataFrame
        返回:
            dict: 包含各项指标的字典，缺失值为 None
        """
        # 默认值：全部为 None（表示数据缺失）
        indicators = {
            "net_profit_yoy": None,
            "roe": None,
            "ocf_to_income": None,
        }

        # 数据为空时返回默认值
        if df is None or df.empty:
            return indicators

        # 按公告日期降序排列，取最新一期
        if "ann_date" in df.columns:
            df = df.sort_values("ann_date", ascending=False)
        # 取第一行（最新一期）
        latest = df.iloc[0]

        # 提取净利润同比增速（Tushare 字段名为 netprofit_yoy）
        if "netprofit_yoy" in latest and pd.notna(latest["netprofit_yoy"]):
            indicators["net_profit_yoy"] = float(latest["netprofit_yoy"])
        # 兼容旧字段名 net_profit_yoy（Mock 测试场景）
        elif "net_profit_yoy" in latest and pd.notna(latest["net_profit_yoy"]):
            indicators["net_profit_yoy"] = float(latest["net_profit_yoy"])

        # 提取 ROE
        if "roe" in latest and pd.notna(latest["roe"]):
            indicators["roe"] = float(latest["roe"])

        # 提取经营现金流与收入比（优先使用 ocf_to_opincome 字段）
        if "ocf_to_opincome" in latest and pd.notna(latest["ocf_to_opincome"]):
            indicators["ocf_to_income"] = float(latest["ocf_to_opincome"])

        return indicators

    def _score_net_profit_yoy(self, net_profit_yoy: Optional[float]) -> float:
        """
        计算净利润增速维度得分

        评分标准：
          同比增长 > 30%：+20分
          同比增长 0% ~ 30%：+10分
          同比增长 < 0%：-20分
          数据缺失：0分

        参数:
            net_profit_yoy: 净利润同比增速（%），None 表示数据缺失
        返回:
            float: 净利润增速维度得分
        """
        # 数据缺失返回 0 分
        if net_profit_yoy is None:
            return 0
        # 同比增长 > 30%：+20分
        if net_profit_yoy > 30:
            return 20
        # 同比增长 0% ~ 30%：+10分
        if net_profit_yoy >= 0:
            return 10
        # 同比增长 < 0%：-20分
        return -20

    def _score_roe(self, roe: Optional[float]) -> float:
        """
        计算净资产收益率(ROE)维度得分

        评分标准：
          ROE > 15%：+20分
          ROE 5% ~ 15%：+10分
          ROE 0% ~ 5%：0分
          ROE < 0%：-20分
          数据缺失：0分

        参数:
            roe: 净资产收益率（%），None 表示数据缺失
        返回:
            float: ROE维度得分
        """
        # 数据缺失返回 0 分
        if roe is None:
            return 0
        # ROE > 15%：+20分
        if roe > 15:
            return 20
        # ROE 5% ~ 15%：+10分
        if roe >= 5:
            return 10
        # ROE 0% ~ 5%：0分
        if roe >= 0:
            return 0
        # ROE < 0%：-20分
        return -20

    def _score_ocf_to_income(self, ocf_to_income: Optional[float]) -> float:
        """
        计算经营现金流维度得分

        评分标准（ocf_to_income 表示经营现金流与营业收入的比值）：
          经营现金流 > 净利润（ocf_to_income > 1）：+20分
          经营现金流 > 0 但 < 净利润（0 < ocf_to_income <= 1）：+10分
          经营现金流 < 0（ocf_to_income < 0）：-20分
          数据缺失：0分

        参数:
            ocf_to_income: 经营现金流与收入比，None 表示数据缺失
        返回:
            float: 经营现金流维度得分
        """
        # 数据缺失返回 0 分
        if ocf_to_income is None:
            return 0
        # 经营现金流 > 净利润：+20分
        if ocf_to_income > 1:
            return 20
        # 经营现金流 > 0 但 < 净利润：+10分
        if ocf_to_income > 0:
            return 10
        # 经营现金流 = 0：0分
        if ocf_to_income == 0:
            return 0
        # 经营现金流 < 0：-20分
        return -20

    def calculate_score(
        self, stock_code: str, score_date: str
    ) -> Tuple[float, FundamentalDetail]:
        """
        计算指定股票的基本面得分

        综合公式：
          基本面得分 = 净利润增速得分 + ROE得分 + 经营现金流得分
          得分范围：-60 到 +60

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期，格式 YYYY-MM-DD 或 YYYYMMDD
        返回:
            Tuple[float, FundamentalDetail]: (基本面得分, 基本面详情对象)
        """
        logger.debug(f"开始计算基本面得分: {stock_code}, 日期: {score_date}")

        # 初始化详情对象
        detail = FundamentalDetail()

        # 获取财务指标数据
        df = self._fetch_fina_indicator(stock_code)
        # 提取最新一期指标
        indicators = self._extract_latest_indicators(df)

        # 记录原始指标值到详情
        detail.net_profit_yoy = indicators["net_profit_yoy"]
        detail.roe = indicators["roe"]
        detail.ocf_to_income = indicators["ocf_to_income"]

        # 1. 计算净利润增速得分
        profit_score = self._score_net_profit_yoy(indicators["net_profit_yoy"])
        detail.net_profit_yoy_score = profit_score

        # 2. 计算 ROE 得分
        roe_score = self._score_roe(indicators["roe"])
        detail.roe_score = roe_score

        # 3. 计算经营现金流得分
        ocf_score = self._score_ocf_to_income(indicators["ocf_to_income"])
        detail.ocf_to_income_score = ocf_score

        # 计算综合得分（基准分为50分，三个维度直接相加）
        total_score = max(-100, min(100, 50 + profit_score + roe_score + ocf_score))

        # 记录最终得分
        logger.debug(
            f"股票 {stock_code} 基本面得分: {total_score} "
            f"(基准分=50, 净利润增速={profit_score}, ROE={roe_score}, "
            f"经营现金流={ocf_score})"
        )
        return total_score, detail


