# -*- coding: utf-8 -*-
"""
资金面评分器模块

基于资金流向数据计算资金面得分。
数据来源：Tushare Pro moneyflow_ths 接口（同花顺个股资金流向）
         Tushare Pro hk_hold 接口（北向资金持股）

个股图谱使用实时数据，不从本地数据库降级。

评分维度：
  1. 主力资金净流入（5日累计）- 权重 35%
  2. 大单占比（近5日）- 权重 20%
  3. 北向资金（最近季度）- 权重 20%
  4. 主力与散户方向 - 权重 25%

一票否决条件：
  - 5日主力净额 < -1000万元
  - 大单净流入 < 0 且 小单净流入 > 0（出货信号）
"""

import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

# 导入数据库管理器
from utils.db_manager import DBManager
# 导入资金面详情模型
from trading.stock_score_models import MoneyflowDetail

# 配置日志记录器
logger = logging.getLogger(__name__)


# ============================================================
# 资金面评分常量配置
# ============================================================

# 各维度权重
WEIGHT_MAIN_NET_FLOW = 0.55   # 主力净流入权重
WEIGHT_LARGE_RATIO = 0.10     # 大单占比权重
WEIGHT_NORTH_FUND = 0.10      # 北向资金权重
WEIGHT_DIRECTION = 0.25       # 主力散户方向权重

# 一票否决得分
VETO_SCORE = -100
# 主力净流入一票否决阈值（万元）
VETO_MAIN_NET_FLOW_THRESHOLD = -10000

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
        self._cache: Dict[str, Tuple] = {}
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


class MoneyflowScorer:
    """
    资金面评分器

    根据 Tushare 资金流向数据计算资金面得分。
    四个评分维度：主力净流入、大单占比、北向资金、主力散户方向。
    支持一票否决机制。
    """

    def __init__(self, db_manager: DBManager = None, tushare_token: str = None):
        """
        初始化资金面评分器

        参数:
            db_manager: 数据库管理器实例，为 None 时使用默认实例
            tushare_token: Tushare API token，为 None 时从配置文件读取
        """
        # 使用传入的 db_manager 或创建默认实例
        from utils.global_db import get_global_db
        self.db = db_manager or get_global_db()
        # 初始化 Tushare token
        self._token = tushare_token or self._load_tushare_token()
        # 初始化 Tushare pro API 对象
        self._pro = None
        # 初始化内存缓存
        self._cache = MemoryCache()
        # 记录初始化日志
        logger.info("资金面评分器初始化完成")

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

    def _format_date(self, date_str: str) -> str:
        """
        将日期字符串统一转换为 YYYYMMDD 格式（Tushare 接口要求）

        参数:
            date_str: 日期字符串，支持 YYYYMMDD 或 YYYY-MM-DD
        返回:
            str: YYYYMMDD 格式的日期字符串
        """
        # 去除空白字符
        date_str = date_str.strip()
        # 如果包含横杠，去除横杠
        if "-" in date_str:
            return date_str.replace("-", "")
        return date_str

    def _get_trade_dates(self, end_date: str, count: int = 5) -> List[str]:
        """
        获取截止日期前的 N 个交易日列表

        参数:
            end_date: 截止日期（YYYYMMDD 格式）
            count: 需要的交易日数量，默认 5
        返回:
            List[str]: 交易日列表（YYYYMMDD 格式），按日期升序
        """
        # 解析截止日期
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        # 向前推算足够多的自然日（考虑周末和节假日）
        start_dt = end_dt - timedelta(days=count * 3)
        start_date = start_dt.strftime("%Y%m%d")

        # 生成自然日列表，过滤周末
        dates = []
        current = start_dt
        while current <= end_dt:
            # 排除周六(5)和周日(6)
            if current.weekday() < 5:
                dates.append(current.strftime("%Y%m%d"))
            current += timedelta(days=1)

        # 取最后 count 个交易日
        return dates[-count:] if len(dates) >= count else dates

    def _call_tushare_with_retry(self, func, **kwargs):
        """
        带重试机制的 Tushare API 调用

        参数:
            func: Tushare API 调用函数
            **kwargs: API 参数
        返回:
            DataFrame: API 返回的数据
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
        # 根据首位数字判断交易所
        if code.startswith("6"):
            return f"{code}.SH"
        # 深圳交易所（0开头、3开头）
        return f"{code}.SZ"

    def _fetch_moneyflow_data(
        self, stock_code: str, score_date: str
    ) -> Optional[pd.DataFrame]:
        """
        从 Tushare moneyflow_ths 接口获取个股资金流向数据

        获取近5个交易日的资金流向数据。
        个股图谱应该取实时数据，不从本地数据库降级。

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            DataFrame: 资金流向数据，失败返回 None
        """
        # 构建缓存键
        cache_key = f"moneyflow_{stock_code}_{score_date}"
        # 检查缓存
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"命中缓存: {cache_key}")
            return cached

        # 计算5日交易日范围
        trade_dates = self._get_trade_dates(score_date, 5)
        if not trade_dates:
            logger.warning(f"无法获取交易日列表: {score_date}")
            return None

        # 起始日期和结束日期
        start_date = trade_dates[0]
        end_date = trade_dates[-1]
        # 转换为 Tushare 格式代码
        ts_code = self._convert_ts_code(stock_code)

        try:
            # 调用 Tushare moneyflow_ths 接口获取实时数据
            pro = self._get_pro()
            df = self._call_tushare_with_retry(
                pro.moneyflow_ths,
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            # 检查返回数据是否有效
            if df is not None and not df.empty:
                logger.debug(
                    f"获取资金流向数据成功: {stock_code}, {len(df)} 条记录"
                )
                # 写入缓存
                self._cache.set(cache_key, df)
                return df
            # Tushare 返回空数据
            logger.warning(f"Tushare 返回空数据: {stock_code}")
            return None
        except Exception as e:
            # 获取实时数据失败，返回 None（不降级到本地数据）
            logger.error(f"Tushare 资金流向获取失败: {stock_code}, {e}")
            return None

    def _fetch_north_fund_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        从 Tushare hk_hold 接口获取北向资金持股数据

        获取最近两个季度的北向资金持股数据，用于判断增减持。

        参数:
            stock_code: 股票代码（6位数字）
        返回:
            DataFrame: 北向资金持股数据，失败返回 None
        """
        # 构建缓存键
        cache_key = f"north_fund_{stock_code}"
        # 检查缓存
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"命中北向资金缓存: {cache_key}")
            return cached

        # 转换为 Tushare 格式代码
        ts_code = self._convert_ts_code(stock_code)

        try:
            pro = self._get_pro()
            # 获取最近 180 天的北向资金数据
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

            # 调用 hk_hold 接口
            df = self._call_tushare_with_retry(
                pro.hk_hold,
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            # 检查返回数据
            if df is not None and not df.empty:
                logger.debug(f"获取北向资金数据成功: {stock_code}, {len(df)} 条")
                # 写入缓存
                self._cache.set(cache_key, df)
                return df
            logger.debug(f"北向资金无持股数据: {stock_code}")
            return None
        except Exception as e:
            logger.warning(f"北向资金数据获取失败: {stock_code}, {e}")
            return None

    def _score_main_net_flow(self, net_flow_5d: float) -> float:
        """
        计算主力资金净流入维度得分（5日累计）

        评分标准：
          净额 > 10000万元：100分
          净额 > 5000万元：80分
          净额 > 100万元：60分
          净额 > 0：40分
          净额 < 0：-20分
          一票否决：净额 < -10000万元 → -100分

        参数:
            net_flow_5d: 5日主力资金净流入金额（万元）
        返回:
            float: 主力净流入维度得分
        """
        # 一票否决条件：净额 < -10000万元
        if net_flow_5d < VETO_MAIN_NET_FLOW_THRESHOLD:
            return VETO_SCORE
        # 净额 > 10000万元：100分
        if net_flow_5d > 10000:
            return 100
        # 净额 > 5000万元：80分
        if net_flow_5d > 5000:
            return 80
        # 净额 > 100万元：60分
        if net_flow_5d > 100:
            return 60
        # 净额 > 0：40分
        if net_flow_5d > 0:
            return 40
        # 净额 <= 0：-20分
        return -20

    def _score_large_ratio(self, daily_ratios: List[float]) -> float:
        """
        计算大单占比维度得分（近5日）

        评分标准（每天独立评分，5日累加）：
          某天流入超过5%：40分
          某天流入超过1%：20分
          某天流入 > 0：10分
          某天流入 < 0：-30分

        参数:
            daily_ratios: 近5日大单净流入占比列表（百分比）
        返回:
            float: 大单占比维度总分
        """
        total = 0.0
        for ratio in daily_ratios:
            # 流入超过5%
            if ratio > 5:
                total += 40
            # 流入超过1%
            elif ratio > 1:
                total += 20
            # 流入 > 0
            elif ratio > 0:
                total += 10
            # 流入 < 0
            elif ratio < 0:
                total += -30
            # ratio == 0 时不加分不减分
        return total

    def _score_north_fund(self, stock_code: str) -> Tuple[float, str]:
        """
        计算北向资金维度得分

        评分标准：
          没有持股：0分
          有持股基础分：50分
            增持：+50分 = 100分
            减持：-50分 = 0分
            不变：维持 = 50分

        参数:
            stock_code: 股票代码（6位数字）
        返回:
            Tuple[float, str]: (北向资金得分, 持股状态)
            状态: "none" / "increase" / "decrease" / "hold"
        """
        # 获取北向资金数据
        df = self._fetch_north_fund_data(stock_code)

        # 没有数据，视为没有持股
        if df is None or df.empty:
            logger.debug(f"北向资金无持股: {stock_code}")
            return 0, "none"

        # 按日期排序（降序），取最近两条记录
        if "trade_date" in df.columns:
            df = df.sort_values("trade_date", ascending=False)
        # 获取最近一期持股量
        latest = df.iloc[0]
        # 获取持股量字段（兼容不同字段名）
        vol_field = "vol" if "vol" in df.columns else "ratio"
        latest_vol = float(latest.get(vol_field, 0))

        # 没有持股量
        if latest_vol <= 0:
            return 0, "none"

        # 有持股，基础分 50
        base_score = 50
        # 如果只有一条记录，无法判断增减持
        if len(df) < 2:
            logger.debug(f"北向资金仅一期数据: {stock_code}")
            return base_score, "hold"

        # 获取上一期持股量
        prev = df.iloc[1]
        prev_vol = float(prev.get(vol_field, 0))

        # 判断增减持
        if latest_vol > prev_vol:
            # 增持：+50分
            logger.debug(f"北向资金增持: {stock_code}")
            return base_score + 50, "increase"
        elif latest_vol < prev_vol:
            # 减持：-50分
            logger.debug(f"北向资金减持: {stock_code}")
            return base_score - 50, "decrease"
        else:
            # 不变：维持
            logger.debug(f"北向资金持平: {stock_code}")
            return base_score, "hold"

    def _score_direction(self, large_net: float, small_net: float) -> float:
        """
        计算主力与散户方向维度得分

        评分标准：
          大单净流入 > 0 且 小单净流入 < 0：100分
          大单净流入 > 0 且 小单净流入 >= 0：60分
          大单净流入 < 0 且 小单净流入 > 0：-100分（一票否决）
          其他情况：0分

        参数:
            large_net: 大单净流入金额（万元）
            small_net: 小单净流入金额（万元）
        返回:
            float: 主力散户方向得分
        """
        # 大单流入 + 小单流出 = 主力吸筹
        if large_net > 0 and small_net < 0:
            return 100
        # 大单流入 + 小单也流入 = 共同看多
        if large_net > 0 and small_net >= 0:
            return 60
        # 大单流出 + 小单流入 = 出货信号（一票否决）
        if large_net < 0 and small_net > 0:
            return VETO_SCORE
        # 其他情况（大单流出 + 小单也流出等）
        return 0

    def _extract_flow_metrics(
        self, df: pd.DataFrame
    ) -> Dict[str, float]:
        """
        从资金流向 DataFrame 中提取评分所需指标

        提取指标：
          - net_flow_5d: 5日主力净流入累计（万元）
          - daily_ratios: 每日大单净流入占比列表
          - large_net: 大单净流入累计（万元）
          - small_net: 小单净流入累计（万元）

        参数:
            df: 资金流向 DataFrame（Tushare 格式）
        返回:
            Dict: 包含各项指标的字典
        """
        metrics = {
            "net_flow_5d": 0.0,
            "daily_ratios": [],
            "large_net": 0.0,
            "small_net": 0.0,
        }

        if df is None or df.empty:
            return metrics

        # 从 Tushare moneyflow_ths 格式提取指标
        return self._extract_from_tushare(df)

    def _extract_from_tushare(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        从 Tushare moneyflow_ths 格式数据中提取指标

        参数:
            df: Tushare 格式的资金流向 DataFrame
        返回:
            Dict: 评分指标字典
        """
        metrics = {
            "net_flow_5d": 0.0,
            "daily_ratios": [],
            "large_net": 0.0,
            "small_net": 0.0,
        }

        # 累计5日主力净买入金额（万元）
        if "net_amount" in df.columns:
            metrics["net_flow_5d"] = float(df["net_amount"].sum())
        elif "net_buy_amount" in df.columns:
            metrics["net_flow_5d"] = float(df["net_buy_amount"].sum())

        # 每日大单净流入占比
        if "buy_lg_amount_rate" in df.columns:
            metrics["daily_ratios"] = df["buy_lg_amount_rate"].fillna(0).tolist()
        elif "net_buy_rate" in df.columns:
            metrics["daily_ratios"] = df["net_buy_rate"].fillna(0).tolist()

        # 大单净流入累计
        if "buy_lg_amount" in df.columns and "sell_lg_amount" in df.columns:
            # 计算大单净流入 = 买入 - 卖出
            large_buy = df["buy_lg_amount"].fillna(0).sum()
            large_sell = df["sell_lg_amount"].fillna(0).sum()
            metrics["large_net"] = float(large_buy - large_sell)
        elif "buy_lg_amount" in df.columns:
            # 如果只有买入字段，假设为净流入金额
            metrics["large_net"] = float(df["buy_lg_amount"].fillna(0).sum())

        # 小单净流入累计
        if "buy_sm_amount" in df.columns and "sell_sm_amount" in df.columns:
            # 计算小单净流入 = 买入 - 卖出
            small_buy = df["buy_sm_amount"].fillna(0).sum()
            small_sell = df["sell_sm_amount"].fillna(0).sum()
            metrics["small_net"] = float(small_buy - small_sell)
        elif "buy_sm_amount" in df.columns:
            # 如果只有买入字段，假设为净流入金额
            metrics["small_net"] = float(df["buy_sm_amount"].fillna(0).sum())

        return metrics

    def calculate_score(
        self, stock_code: str, score_date: str
    ) -> Tuple[float, MoneyflowDetail]:
        """
        计算指定股票在指定日期的资金面得分

        综合公式：
          资金面得分 = (主力净流入得分 × 0.35)
                     + (大单占比得分 × 0.20)
                     + (北向资金得分 × 0.20)
                     + (主力散户方向得分 × 0.25)

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期，格式 YYYY-MM-DD 或 YYYYMMDD
        返回:
            Tuple[float, MoneyflowDetail]: (资金面得分, 资金面详情对象)
        """
        logger.debug(f"开始计算资金面得分: {stock_code}, 日期: {score_date}")

        # 检查是否为交易日
        from utils.trade_date_utils import is_trading_day
        if not is_trading_day(score_date):
            logger.debug(f"日期 {score_date} 不是交易日，跳过资金面评分")
            detail = MoneyflowDetail()
            return 0, detail

        # 初始化详情对象
        detail = MoneyflowDetail()
        # 统一日期格式为 YYYYMMDD
        formatted_date = self._format_date(score_date)

        # 获取资金流向数据（无论是否触发一票否决都需要）
        df = self._fetch_moneyflow_data(stock_code, formatted_date)
        # 提取评分指标
        metrics = self._extract_flow_metrics(df)
        
        # 保存主力净流入数据
        detail.main_net_flow = metrics["net_flow_5d"]

        # 先检查一票否决条件
        is_veto, veto_reason = self.check_veto(stock_code, formatted_date)
        if is_veto:
            # 触发一票否决
            detail.veto = True
            detail.veto_reason = veto_reason
            logger.warning(f"股票 {stock_code} 资金面一票否决: {veto_reason}")
            return VETO_SCORE, detail

        # 1. 计算主力净流入得分
        net_flow_5d = metrics["net_flow_5d"]
        detail.main_net_flow = net_flow_5d
        main_score = self._score_main_net_flow(net_flow_5d)
        detail.main_net_flow_score = main_score

        # 检查主力净流入一票否决
        if main_score == VETO_SCORE:
            detail.veto = True
            detail.veto_reason = f"5日主力净额 {net_flow_5d:.0f} 万元 < -10000万元"
            logger.warning(f"股票 {stock_code} 主力净流入一票否决")
            return VETO_SCORE, detail

        # 2. 计算大单占比得分
        daily_ratios = metrics["daily_ratios"]
        large_ratio_score = self._score_large_ratio(daily_ratios)
        detail.large_ratio_score = large_ratio_score

        # 3. 计算北向资金得分
        north_score, north_status = self._score_north_fund(stock_code)
        detail.north_fund_score = north_score
        detail.north_fund_status = north_status

        # 4. 计算主力散户方向得分
        large_net = metrics["large_net"]
        small_net = metrics["small_net"]
        direction_score = self._score_direction(large_net, small_net)
        detail.direction_score = direction_score

        # 检查方向一票否决（出货信号）
        if direction_score == VETO_SCORE:
            detail.veto = True
            detail.veto_reason = "出货信号：大单净流出且小单净流入"
            logger.warning(f"股票 {stock_code} 出货信号一票否决")
            return VETO_SCORE, detail

        # 计算综合得分（加权求和）
        total_score = (
            main_score * WEIGHT_MAIN_NET_FLOW
            + large_ratio_score * WEIGHT_LARGE_RATIO
            + north_score * WEIGHT_NORTH_FUND
            + direction_score * WEIGHT_DIRECTION
        )
        # 四舍五入保留一位小数
        total_score = round(total_score, 1)

        # 记录最终得分
        logger.debug(
            f"股票 {stock_code} 资金面得分: {total_score} "
            f"(主力={main_score}, 大单={large_ratio_score}, "
            f"北向={north_score}, 方向={direction_score})"
        )
        return total_score, detail

    def check_veto(
        self, stock_code: str, score_date: str
    ) -> Tuple[bool, str]:
        """
        检查资金面一票否决条件

        一票否决条件：
          1. 5日主力净额 < -1000万元
          2. 大单净流入 < 0 且 小单净流入 > 0（出货信号）

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            Tuple[bool, str]: (是否触发一票否决, 否决原因)
        """
        # 统一日期格式
        formatted_date = self._format_date(score_date)

        # 获取资金流向数据
        df = self._fetch_moneyflow_data(stock_code, formatted_date)
        # 提取评分指标
        metrics = self._extract_flow_metrics(df)

        # 条件1：5日主力净额 < -10000万元
        net_flow_5d = metrics["net_flow_5d"]
        if net_flow_5d < VETO_MAIN_NET_FLOW_THRESHOLD:
            reason = f"5日主力净额 {net_flow_5d:.0f} 万元 < -10000万元"
            logger.warning(f"股票 {stock_code} 一票否决: {reason}")
            return True, reason

        # 条件2：大单净流出 + 小单净流入（出货信号）
        large_net = metrics["large_net"]
        small_net = metrics["small_net"]
        if large_net < 0 and small_net > 0:
            reason = "出货信号：大单净流出且小单净流入"
            logger.warning(f"股票 {stock_code} 一票否决: {reason}")
            return True, reason

        # 未触发一票否决
        return False, ""
