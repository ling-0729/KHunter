# -*- coding: utf-8 -*-
"""
基本面评分器模块

基于财务指标数据计算基本面得分。
数据来源：Tushare Pro fina_indicator 接口（财务指标数据）、
         Tushare daily_basic 接口（历史市值数据）（市值维度暂已屏蔽）

评分维度：
  1. 净利润增速（net_profit_yoy）- 公司赚钱能力增长
  2. 净资产收益率 ROE（roe）- 公司盈利能力
  3. 经营现金流（ocf_to_income）- 赚的钱是否真实
  4. 市值（market_cap）- 公司规模（暂时屏蔽）

综合公式：
  基本面得分 = 50 + 净利润增速得分 + ROE得分 + 经营现金流得分（市值已屏蔽）
  得分范围：-90 到 +90（实际限制在 -100 到 +100）

一票否决条件（★【2026-09-27 用户口径】**已去除** ✗ ⇒ 默认**不否决** ✓）：
  - 净利润同比下滑 > 50%（即 net_profit_yoy < -50）：-100分 ✗（**已停用** ✓）
  - ROE < -5%：-100分 ✗（**已停用** ✓）
  ⇒ 基本面**只打分、不否决** ✓（分数仍照常参与标准模式的加权 ✓）；
    恢复方式：把 `FUNDAMENTAL_VETO_ENABLED` 改回 `True` ✓（**唯一开关** ✓）
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

#: ★【2026-09-27 用户口径】基本面**一票否决总开关** ✓（现**关闭** ✗ = 去除该否决 ✓）
#:   · 关闭 ⇒ `check_veto` 恒 `False` ✓；`calculate_score` 内两条否决分支**不再短路** ✓
#:     （分数仍按 `50 + 三维度` 正常计算 ✓，仍参与**标准模式**的五维加权 ✓）
#:   · 恢复 ⇒ 改回 `True` ✓（**唯一开关** ✓，两处同时生效 ✓，不产生口径漂移 ✗）
FUNDAMENTAL_VETO_ENABLED = False



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
    评分维度：净利润增速、ROE、经营现金流（市值维度暂已屏蔽）。
    支持一票否决机制。
    """

    def __init__(self, tushare_token: str = None, db_manager=None):
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
        # 【2026-09-25 M2】本地优先：基本面只读本地表 `stock_finance_indicator` ✓
        #   · 时点规则 = **`ann_date <= 选股日`**（最新一期 ✓）—— 替代 `end_date <= 选股日` ✗
        #     （后者会把"报告期已到但尚未公告"的财报提前使用 ⇒ 前视偏差 ✗）
        #   · 本地无可用期 → **报错** ✗（不再静默回退联网 ✗）
        self.db_manager = db_manager          # 由构造参数显式传入时优先 ✓（否则用全局库 ✓）
        import os as _os
        self.allow_online_fallback = _os.environ.get(
            'KHUNTER_ALLOW_ONLINE_FALLBACK', '0').strip() in ('1', 'true', 'True')
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

    def _get_local_conn(self):
        """取本地库连接（离线 ✓）"""
        try:
            if getattr(self, 'db_manager', None) is not None:
                return self.db_manager.connect()
        except Exception:
            pass
        from utils.global_db import get_global_db
        return get_global_db().connect()

    @staticmethod
    def _to_iso(date_str: str) -> str:
        s = str(date_str).strip()
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}' if (len(s) == 8 and s.isdigit()) else s[:10]

    def _fetch_fina_indicator_local(self, stock_code: str,
                                    score_date: str) -> Optional[pd.DataFrame]:
        """【2026-09-25 M2】读本地**最新一期且已公告**的财务指标 ✓（离线 ✓）

        时点规则：`ann_date <= score_date` ✓（防前视偏差 ✗→✓）
        """
        from utils.data_collectors.local_data_collectors import load_indicators_local
        conn = self._get_local_conn()
        code6 = str(stock_code).split('.')[0][:6]
        rows = load_indicators_local(conn, code6, self._to_iso(score_date))
        if not rows:
            return None
        df = pd.DataFrame(rows)
        if 'ann_date' not in df.columns or df.empty:
            return None
        return df

    def _fetch_fina_indicator(
        self, stock_code: str, score_date: str
    ) -> Optional[pd.DataFrame]:
        """财务指标取数入口 ✓：**本地优先**（M2 定稿 ✓），本地无数据 → **返回 None** ✓

        规则（用户 2026-09-27 决策 ✓）：
          · 取**选股日所在季度**的财报（由 `load_indicators_local` 按季匹配 ✓）
          · 该季度财报**已公告** → 返回本地数据 ✓
          · 该季度财报**未公告** → 返回 `None`（**不计、不否决** ✓，不回溯上一季 ✗）
          · 仅 `KHUNTER_ALLOW_ONLINE_FALLBACK=1`（实盘/数据更新 ✓）才走在线分支 ✓
        """
        local = self._fetch_fina_indicator_local(stock_code, score_date)
        if local is not None and not local.empty:
            return local
        # 目标季度未公告 → 不计（返回 None，下游得基准分、不否决）
        if not self.allow_online_fallback:
            logger.info(
                f'基本面数据缺失（目标季度未公告）: {stock_code} @ {score_date} '
                f'→ 不计入基本面评分 ✓')
            return None
        return self._fetch_fina_indicator_online(stock_code, score_date)

    def _fetch_fina_indicator_online(
        self, stock_code: str, score_date: str
    ) -> Optional[pd.DataFrame]:
        """
        从 Tushare fina_indicator 接口获取评分日期之前的财务指标数据

        通过 end_date 参数过滤，只返回报告期截止日在评分日期之前的数据，
        确保回测和实盘使用数据逻辑一致（不会用到未来数据）。

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期，格式 YYYYMMDD 或 YYYY-MM-DD
        返回:
            DataFrame: 财务指标数据，失败返回 None
        """
        # 【2026-09-25 M2】在线取数检查点 ✓（回测期间为离线模式 → 直接抛错 ✗）
        from utils.online_guard import PURPOSE_SCORE, guard_online_call
        # 【2026-09-25 契约 ✓】**评分只读本地** ✗（在线回退 ⇒ 任何模式下都必须失败 ✗✓）
        guard_online_call('Tushare fina_indicator 取数（评分回退）', purpose=PURPOSE_SCORE)

        # 构建缓存键（包含评分日期）
        cache_key = f"fina_indicator_{stock_code}_{score_date}"
        # 检查缓存
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"命中缓存: {cache_key}")
            return cached

        # 转换为 Tushare 格式代码
        ts_code = self._convert_ts_code(stock_code)

        try:
            pro = self._get_pro()
            # 调用 fina_indicator 接口获取评分日期之前的财务指标
            # end_date 参数过滤报告期截止日 <= 评分日期的数据
            # 注意：Tushare 实际字段名为 netprofit_yoy（非 net_profit_yoy）
            df = self._call_tushare_with_retry(
                pro.fina_indicator,
                ts_code=ts_code,
                end_date=score_date.replace("-", "") if score_date else "",
                fields="ts_code,ann_date,end_date,roe,netprofit_yoy,ocfps,eps,ocf_to_opincome",
            )
            # 检查返回数据是否有效
            if df is not None and not df.empty:
                logger.debug(
                    f"获取财务指标数据成功: {stock_code} @ {score_date}, {len(df)} 条记录"
                )
                # 写入缓存
                self._cache.set(cache_key, df)
                return df
            # Tushare 返回空数据
            logger.warning(f"Tushare 财务指标返回空数据: {stock_code} @ {score_date}")
            return None
        except Exception as e:
            logger.error(f"Tushare 财务指标获取失败: {stock_code} @ {score_date}, {e}")
            return None

    def _extract_latest_indicators(
        self, df: Optional[pd.DataFrame], score_date: str
    ) -> dict:
        """
        从财务指标 DataFrame 中提取评分日期之前最新一期的评分所需指标

        过滤逻辑：
          - 只保留 end_date <= score_date 的记录（保证不用未来数据）
          - 按 end_date 降序取最新一期
        确保回测与实盘使用数据逻辑一致。

        提取指标：
          - net_profit_yoy: 净利润同比增速（%）
          - roe: 净资产收益率（%）
          - ocf_to_income: 经营现金流与收入比

        参数:
            df: 财务指标 DataFrame
            score_date: 评分日期，格式 YYYYMMDD 或 YYYY-MM-DD
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

        # 统一日期格式为 YYYYMMDD
        date_str = score_date.replace("-", "") if score_date else ""

        # 按报告期截止日过滤：只保留 end_date <= score_date 的记录
        if "end_date" in df.columns and date_str:
            df = df[df["end_date"].astype(str).str.replace("-", "") <= date_str]
            if df.empty:
                logger.warning(f"无评分日期之前的财务指标: {score_date}")
                return indicators

        # 按报告期截止日降序排列，取最新一期
        if "end_date" in df.columns:
            df = df.sort_values("end_date", ascending=False)
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

    # ---- 市值评分已注释（暂时屏蔽） ----
    # def _fetch_market_cap(self, stock_code: str, trade_date: str) -> Optional[float]:
    #     """
    #     通过 Tushare daily_basic 接口查询指定日期的总市值
    #
    #     参数:
    #         stock_code: 股票代码（6位数字）
    #         trade_date: 交易日期，格式 YYYYMMDD 或 YYYY-MM-DD
    #     返回:
    #         float: 市值（亿元），无数据返回 None
    #     """
    #     # 构建缓存键（包含日期）
    #     cache_key = f"market_cap_{stock_code}_{trade_date}"
    #     cached = self._cache.get(cache_key)
    #     if cached is not None:
    #         return cached
    #
    #     # 统一转换为 Tushare 格式（YYYYMMDD）
    #     date_str = trade_date.replace("-", "") if trade_date else ""
    #     # 转换为 Tushare 格式代码
    #     ts_code = self._convert_ts_code(stock_code)
    #
    #     try:
    #         pro = self._get_pro()
    #         # 调用 daily_basic 接口获取指定日期的总市值
    #         df = self._call_tushare_with_retry(
    #             pro.daily_basic,
    #             ts_code=ts_code,
    #             trade_date=date_str,
    #             fields="ts_code,trade_date,total_mv",
    #         )
    #         if df is not None and not df.empty:
    #             # total_mv 单位为万元，转换为亿元
    #             total_mv = float(df.iloc[0]["total_mv"])
    #             if total_mv > 0:
    #                 market_cap = total_mv / 10000
    #                 # 写入缓存
    #                 self._cache.set(cache_key, market_cap)
    #                 logger.debug(f"市值查询成功: {stock_code} @ {trade_date}, {market_cap:.2f}亿")
    #                 return market_cap
    #     except Exception as e:
    #         logger.debug(f"查询市值失败: {stock_code} @ {trade_date}, {e}")
    #
    #     # 缓存 None 避免重复请求
    #     self._cache.set(cache_key, None)
    #     return None

    # ---- 市值评分已注释（暂时屏蔽） ----
    # def _score_market_cap(self, market_cap: Optional[float]) -> float:
    #     """
    #     计算市值维度得分
    #
    #     评分标准：
    #       市值 < 50亿：-50分（小盘股风险较高）
    #       市值 ≥ 50亿 / 数据缺失：0分
    #
    #     参数:
    #         market_cap: 市值（亿元），None 表示数据缺失
    #     返回:
    #         float: 市值维度得分
    #     """
    #     # 数据缺失不作惩罚
    #     if market_cap is None:
    #         return 0
    #     # 市值 < 50亿：-50分
    #     if market_cap < 50:
    #         return -50
    #     # 市值 ≥ 50亿：不扣分
    #     return 0

    def check_veto(self, stock_code: str, score_date: str) -> Tuple[bool, str]:
        """检查基本面一票否决条件（**只判否决，不做打分**）

        否决条件（与 calculate_score 内保持一致）：
          1. 净利润同比下滑 > 50%
          2. ROE < -5%
        指标缺失（None）时不否决。

        返回:
            Tuple[bool, str]: (是否触发一票否决, 否决原因)
        """
        # ★【2026-09-27 用户口径】基本面否决**已去除** ✗ ⇒ 恒不否决 ✓（见模块常量 ✓）
        if not FUNDAMENTAL_VETO_ENABLED:
            return False, ""
        try:
            df = self._fetch_fina_indicator(stock_code, score_date)
            indicators = self._extract_latest_indicators(df, score_date)
        except Exception as e:
            logger.debug(f"基本面否决检查失败({stock_code}): {e}")
            return False, ""

        net_profit_yoy = indicators.get("net_profit_yoy")
        if net_profit_yoy is not None and net_profit_yoy < -50:
            reason = f"净利润同比下滑超过50%（{net_profit_yoy:.1f}%）"
            logger.warning(f"股票 {stock_code} 触发基本面一票否决: {reason}")
            return True, reason

        roe = indicators.get("roe")
        if roe is not None and roe < -5:
            reason = f"ROE低于-5%（{roe:.1f}%）"
            logger.warning(f"股票 {stock_code} 触发基本面一票否决: {reason}")
            return True, reason

        return False, ""

    def calculate_score(
        self, stock_code: str, score_date: str
    ) -> Tuple[float, FundamentalDetail]:
        """
        计算指定股票的基本面得分

        所有维度均使用评分日期的历史数据（end_date <= score_date），
        确保回测和实盘逻辑完全一致，避免未来函数。

        综合公式：
          基本面得分 = 50 + 净利润增速得分 + ROE得分 + 经营现金流得分（市值已屏蔽）
          得分范围：-90 到 +90（实际限制在 -100 到 +100）

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期，格式 YYYY-MM-DD 或 YYYYMMDD
        返回:
            Tuple[float, FundamentalDetail]: (基本面得分, 基本面详情对象)
        """
        logger.debug(f"开始计算基本面得分: {stock_code}, 日期: {score_date}")

        # 初始化详情对象
        detail = FundamentalDetail()

        # 获取评分日期之前的财务指标数据（确保不用未来数据）
        df = self._fetch_fina_indicator(stock_code, score_date)
        # 提取评分日期之前最新一期指标
        indicators = self._extract_latest_indicators(df, score_date)

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

        # ---- 市值评分已注释（暂时屏蔽） ----
        # 4. 获取评分日期的历史市值（通过 Tushare daily_basic 按 trade_date 查询）
        # market_cap = self._fetch_market_cap(stock_code, score_date)
        # detail.market_cap = market_cap
        # # 计算市值维度得分
        # market_cap_score = self._score_market_cap(market_cap)
        # detail.market_cap_score = market_cap_score
        # 市值得分暂时设为 0
        market_cap_score = 0

        # 一票否决：净利润同比下滑 > 50%
        #   ★【2026-09-27 用户口径】**已去除** ✗ ⇒ 由 `FUNDAMENTAL_VETO_ENABLED` 统一关断 ✓
        if (FUNDAMENTAL_VETO_ENABLED
                and indicators["net_profit_yoy"] is not None
                and indicators["net_profit_yoy"] < -50):
            detail.veto = True
            detail.veto_reason = f"净利润同比下滑超过50%（{indicators['net_profit_yoy']:.1f}%）"
            logger.warning(f"股票 {stock_code} 触发基本面一票否决: {detail.veto_reason}")
            return -100, detail

        # 一票否决：ROE < -5%
        #   ★【2026-09-27 用户口径】**已去除** ✗ ⇒ 同上 ✓
        if (FUNDAMENTAL_VETO_ENABLED
                and indicators["roe"] is not None
                and indicators["roe"] < -5):
            detail.veto = True
            detail.veto_reason = f"ROE低于-5%（{indicators['roe']:.1f}%）"
            logger.warning(f"股票 {stock_code} 触发基本面一票否决: {detail.veto_reason}")
            return -100, detail

        # 计算综合得分（基准分50 + 三个维度得分，市值已屏蔽）
        total_score = max(-100, min(100,
            50 + profit_score + roe_score + ocf_score + market_cap_score
        ))

        # 记录最终得分
        logger.debug(
            f"股票 {stock_code} @ {score_date} 基本面得分: {total_score} "
            f"(基准分=50, 净利润增速={profit_score}, ROE={roe_score}, "
            f"经营现金流={ocf_score}) [市值评分已屏蔽]"
        )
        return total_score, detail


