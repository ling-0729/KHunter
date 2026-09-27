# -*- coding: utf-8 -*-
"""
事件驱动评分器模块

基于多种事件数据计算事件驱动得分。
数据来源：Tushare Pro 多个接口

事件类型及有效期：
  1. 业绩预告（forecast）- 20天
  2. 股东增减持（stk_holdertrade）- 50天
  3. 股票回购（repurchase）- 50天
  4. 大宗交易（block_trade）- 5天
  5. 龙虎榜（top_list）- 5天
  6. 个股异常波动（stk_shock）- 10天
  7. ST状态（stock_basic）- 实时
  8. 减持计划公告（AKShare巨潮披露）- 180天

正面事件（加分）：
  - 业绩预增（增幅>50%）：+20分（20天）
  - 业绩略增：+10分（20天）
  - 股票回购：+10分（50天）
  - 股东增持：+20分（50天）
  - 龙虎榜机构净买入：+10分（5天）

负面事件（减分）：
  - 业绩预减/首亏：-20分（20天）
  - 业绩略减：-10分（20天）
  - 股东减持：-30分（50天）
  - 异常波动公告：-15分（10天）
  - 大宗交易折价>5%：-10分（5天）
  - 龙虎榜净卖出：-10分（5天）

一票否决条件：
  - 被ST或*ST：-100分
  - 业绩暴雷（预减>80%或巨亏）：-100分
  - 大股东减持：-100分
  - 减持计划公告（预披露）：-100分（一律否决）

综合公式：
  事件驱动得分 = 50 + Σ(正面事件加分) + Σ(负面事件减分)
  得分范围：-50 到 +150（实际限制在 -100 到 +100）
"""

import json
import re
import time
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd

# 导入事件驱动详情模型
from trading.stock_score_models import EventDetail
# 减持计划数据源解耦：关键词常量与数据层统一来自 trading.reduce_plan_cache
from trading import reduce_plan_cache as rpc
from trading.reduce_plan_cache import (
    REDUCE_PLAN_KEYWORDS, REDUCE_PLAN_EXCLUDE, REDUCE_PLAN_VALIDITY,
    is_reduce_plan_title,
)
from trading import reduce_plan_cache as rpc

# 配置日志记录器
logger = logging.getLogger(__name__)


# ============================================================
# 事件驱动评分常量配置
# ============================================================

# 一票否决得分
VETO_SCORE = -100

# 事件有效期配置（自然日）
#   ⚠️【2026-09-27 起**不再是生效口径** ✗】实际窗口统一由
#   `EVENT_WINDOW_TRADING_DAYS = 5`（**5 个交易日** ✓）决定 ✓；
#   本表仅作**历史参照/文档**保留 ✗（勿再据此判断行为 ✗）
EVENT_VALIDITY = {
    "forecast": 20,         # 业绩预告有效期
    "holdertrade": 50,      # 股东增减持有效期
    "repurchase": 50,       # 股票回购有效期
    "block_trade": 5,       # 大宗交易有效期
    "top_list": 5,          # 龙虎榜有效期
    "shock": 10,            # 异常波动有效期
}

# 正面事件加分配置
POSITIVE_SCORES = {
    "业绩预增": 20,          # 业绩预增（增幅>50%）
    "业绩略增": 10,          # 业绩略增
    "股票回购": 10,          # 股票回购
    "股东增持": 20,          # 股东增持
    "龙虎榜机构净买入": 10,  # 龙虎榜机构净买入
}

# 负面事件减分配置
NEGATIVE_SCORES = {
    "业绩预减": -20,         # 业绩预减/首亏
    "首亏": -20,             # 首亏
    "业绩略减": -10,         # 业绩略减
    "股东减持": -30,         # 股东减持
    "异常波动": -15,         # 异常波动公告
    "大宗交易折价": -10,     # 大宗交易折价>5%
    "龙虎榜净卖出": -10,     # 龙虎榜净卖出
}

# 减持计划公告（预披露）配置 —— 数据源：直连巨潮 hisAnnouncement/query（见 trading.reduce_plan_cache）
# 减持计划利空 > 已实施减持，用户确认：所有减持计划公告一律触发一票否决
# 关键词/排除词/有效期统一定义在 trading.reduce_plan_cache（单一权威源），本模块直接复用
# 减持计划否决分值（与 VETO_SCORE 一致，一律否决）
REDUCE_PLAN_VETO = VETO_SCORE  # 名称:减持计划否决分;类型:int;必填:否;默认:-100;备注:用户确认所有减持计划一律否决

# Tushare API 重试配置
MAX_RETRIES = 3        # 最大重试次数
RETRY_INTERVALS = [1, 2, 3]  # 指数退避重试间隔（秒）- 缩短间隔
API_CALL_TIMEOUT = 10   # API调用超时时间（秒）

# API调用限流配置
API_CALL_INTERVAL = 0.5  # API调用最小间隔（秒），避免请求过快
_last_api_call_time = 0  # 上次API调用时间

# 内存缓存 TTL（秒）
CACHE_TTL = 300  # 5分钟

# 大宗交易折价阈值（%）
BLOCK_TRADE_DISCOUNT_THRESHOLD = 5
# 业绩暴雷阈值（预减幅度 > 80%）
FORECAST_CRASH_THRESHOLD = -80

#: ★【2026-09-27 用户口径】**事件窗口统一 = 最近 5 个交易日** ✓（打分 ✓ 与 否决 ✓ **同口径**）
#:   · 原来各条用 `EVENT_VALIDITY` 的**自然日**：预告 20 ✓ / 减持 50 ✓ / 回购 50 ✓ /
#:     大宗 5 ✓ / 龙虎榜 5 ✓ / 异常波动 10 ✓；减持计划另为 180 天 ✗
#:   · 判据 ✓：以**交易日历**回溯 ✓（`utils.local_calendar.recent_trade_dates_local` ✓，**纯本地** ✓ 不联网 ✗）
#:   · 日历不可用 ⇒ 回退**自然日**（按 5 交易日 ≈ 7 自然日**等比换算** ✓）+ WARNING ✓
EVENT_WINDOW_TRADING_DAYS = 5      # 打分窗口 ✓（`_collect_all_events` 各 `_check_*` ✓）
VETO_WINDOW_TRADING_DAYS = 5       # 否决窗口 ✓（`check_veto` 三条 ✓）
#: 自然日兜底基准 ✓：`trading_days` 个交易日 ≈ `trading_days * 7 / 5` 自然日 ✓
WINDOW_FALLBACK_CALENDAR_DAYS = 7
#: 兼容别名 ✓（旧名保留 ✗，避免外部/测试引用失效 ✓）
VETO_WINDOW_FALLBACK_CALENDAR_DAYS = WINDOW_FALLBACK_CALENDAR_DAYS


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


class EventScorer:
    """
    事件驱动评分器

    根据 Tushare 多个接口的事件数据计算事件驱动得分。
    支持7种事件类型，包含正面加分、负面减分和一票否决机制。
    """

    def __init__(self, tushare_token: str = None):
        """
        初始化事件驱动评分器

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
        logger.info("事件驱动评分器初始化完成")

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

    def _format_date(self, date_str: str) -> str:
        """
        将日期字符串统一转换为 YYYYMMDD 格式

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

    def _get_start_date(self, score_date: str, days: int) -> str:
        """
        根据评分日期和有效期天数计算起始日期

        参数:
            score_date: 评分日期（YYYYMMDD 格式）
            days: 有效期天数
        返回:
            str: 起始日期（YYYYMMDD 格式）
        """
        # 解析评分日期
        end_dt = datetime.strptime(score_date, "%Y%m%d")
        # 向前推算有效期天数
        start_dt = end_dt - timedelta(days=days)
        return start_dt.strftime("%Y%m%d")

    # ------------------------------------------------------------------
    # ★【2026-09-27 用户口径】一票否决窗口 = **最近 5 个交易日** ✓
    # ------------------------------------------------------------------
    def _get_local_conn(self):
        """取本地库连接（**离线** ✓；与 `MoneyflowScorer._get_local_conn` **同一口径** ✓）"""
        try:
            if getattr(self, 'db_manager', None) is not None:
                return self.db_manager.connect()
        except Exception:
            pass
        from utils.global_db import get_global_db
        return get_global_db().connect()

    def _window_start(self, score_date: str, trading_days: int) -> str:
        """事件窗口**起点** ✓ = 最近 `trading_days` 个交易日的**首日** ✓（打分 ✓/否决 ✓ 共用）

        · 主路径 ✓：`recent_trade_dates_local` ✓（**纯本地** ✓：`trade_calendar` 表 →
          `data/trading_calendar_cache.json` → `stock_kline` ✓，**不联网** ✗）
        · 兜底 ✓：本地日历不可用（或不足 N 天 ✗）⇒ 回退**自然日** ✓
          （`trading_days × 7 / 5` ✓，例 5 交易日 ⇒ 7 自然日 ✓）+ WARNING ✓
          （宁可略宽也不漏判 ✗✓）

        ⚠️ 入参/返回均为 `YYYYMMDD` ✓；`recent_trade_dates_local` 用 **ISO** 日期 ✓ ⇒ 在此转换 ✓。
        """
        iso = f'{score_date[:4]}-{score_date[4:6]}-{score_date[6:]}'
        try:
            from utils.local_calendar import recent_trade_dates_local
            dates = recent_trade_dates_local(self._get_local_conn(), iso,
                                             window=int(trading_days))
            return str(dates[0]).replace('-', '')[:8]
        except Exception as e:
            fallback = max(1, round(int(trading_days) * WINDOW_FALLBACK_CALENDAR_DAYS / 5))
            logger.warning(
                f'事件窗口：本地交易日历不可用（{e}）⇒ 回退自然日 {fallback} 天 ✓'
                f'（{trading_days} 个交易日 ≈ {fallback} 自然日；不联网 ✗）')
            return self._get_start_date(score_date, fallback)

    def _veto_window_start(self, score_date: str) -> str:
        """**否决**窗口起点 ✓（= 最近 `VETO_WINDOW_TRADING_DAYS` 个交易日 ✓）"""
        return self._window_start(score_date, VETO_WINDOW_TRADING_DAYS)

    def _call_tushare_with_retry(self, func, **kwargs):
        """
        带重试机制的 Tushare API 调用（指数退避策略 + 限流）

        参数:
            func: Tushare API 调用函数
            **kwargs: API 参数
        返回:
            DataFrame: API 返回的数据，失败返回 None（由调用方使用默认值继续处理）
        """
        global _last_api_call_time

        # 限流：确保两次API调用之间有最小间隔
        elapsed = time.time() - _last_api_call_time
        if elapsed < API_CALL_INTERVAL:
            time.sleep(API_CALL_INTERVAL - elapsed)

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                # 记录API调用时间
                _last_api_call_time = time.time()
                # 设置超时
                import socket
                original_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(API_CALL_TIMEOUT)
                try:
                    # 调用 Tushare API
                    result = func(**kwargs)
                    return result
                finally:
                    socket.setdefaulttimeout(original_timeout)
            except Exception as e:
                last_error = e
                # 记录重试日志
                logger.warning(
                    f"Tushare API 调用失败（第 {attempt + 1} 次）: {e}"
                )
                # 非最后一次重试时等待（指数退避）
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_INTERVALS[attempt] if attempt < len(RETRY_INTERVALS) else RETRY_INTERVALS[-1]
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
        # 所有重试都失败，返回 None，由调用方使用默认值继续处理
        logger.error(f"Tushare API 调用失败（已重试 {MAX_RETRIES} 次）: {last_error}")
        logger.info("将使用默认值继续处理...")
        return None

    # ============================================================
    # 事件数据获取方法
    # ============================================================

    def _check_forecast(self, stock_code: str, score_date: str) -> List[dict]:
        """
        查询业绩预告事件

        通过 Tushare forecast 接口获取有效期内的业绩预告数据。
        有效期：20天

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            List[dict]: 业绩预告事件列表
        """
        # 构建缓存键
        cache_key = f"forecast_{stock_code}_{score_date}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # 计算窗口起始日期（★ 5 个交易日 ✓，原 20 自然日 ✗）
        start_date = self._window_start(score_date, EVENT_WINDOW_TRADING_DAYS)
        # 转换为 Tushare 格式代码
        ts_code = self._convert_ts_code(stock_code)
        events = []

        try:
            pro = self._get_pro()
            # 调用 forecast 接口获取业绩预告
            df = self._call_tushare_with_retry(
                pro.forecast,
                ts_code=ts_code,
                fields="ts_code,ann_date,end_date,type,p_change_min,p_change_max,net_profit_min,net_profit_max",
            )
            # 检查返回数据
            if df is None or df.empty:
                logger.debug(f"无业绩预告数据: {stock_code}")
                self._cache.set(cache_key, events)
                return events

            # 过滤有效期内的记录
            df = self._filter_by_date(df, "ann_date", start_date, score_date)
            if df.empty:
                self._cache.set(cache_key, events)
                return events

            # 遍历每条业绩预告记录
            for _, row in df.iterrows():
                event = self._parse_forecast_event(row)
                if event:
                    events.append(event)

            logger.debug(f"业绩预告事件: {stock_code}, {len(events)} 条")
        except Exception as e:
            logger.error(f"业绩预告查询失败: {stock_code}, {e}")

        # 写入缓存
        self._cache.set(cache_key, events)
        return events

    def _parse_forecast_event(self, row) -> Optional[dict]:
        """
        解析单条业绩预告记录，判断事件类型和分值

        业绩预告类型（type字段）：
          预增 → 检查增幅是否 > 50%
          略增 → +10分
          预减/首亏 → -20分
          略减 → -10分
          扭亏/续盈/续亏/不确定 → 不计分

        参数:
            row: DataFrame 行数据
        返回:
            dict: 事件字典 {"type": ..., "score": ..., "date": ...}，无效返回 None
        """
        # 获取预告类型
        forecast_type = str(row.get("type", "")).strip()
        # 获取公告日期
        ann_date = str(row.get("ann_date", ""))
        # 获取预计变动幅度
        p_change_min = row.get("p_change_min")
        p_change_max = row.get("p_change_max")

        # 业绩预增：检查增幅是否 > 50%
        if forecast_type == "预增":
            # 取最小变动幅度判断
            change = self._safe_float(p_change_min, 0)
            if change > 50:
                return {"type": "业绩预增", "score": POSITIVE_SCORES["业绩预增"], "date": ann_date}
            else:
                # 增幅不超过50%，视为略增
                return {"type": "业绩略增", "score": POSITIVE_SCORES["业绩略增"], "date": ann_date}

        # 业绩略增
        if forecast_type == "略增":
            return {"type": "业绩略增", "score": POSITIVE_SCORES["业绩略增"], "date": ann_date}

        # 业绩预减
        if forecast_type == "预减":
            return {"type": "业绩预减", "score": NEGATIVE_SCORES["业绩预减"], "date": ann_date}

        # 首亏
        if forecast_type == "首亏":
            return {"type": "首亏", "score": NEGATIVE_SCORES["首亏"], "date": ann_date}

        # 业绩略减
        if forecast_type == "略减":
            return {"type": "业绩略减", "score": NEGATIVE_SCORES["业绩略减"], "date": ann_date}

        # 其他类型（扭亏/续盈/续亏/不确定）不计分
        return None

    def _check_holdertrade(self, stock_code: str, score_date: str) -> List[dict]:
        """
        查询股东增减持事件

        通过 Tushare stk_holdertrade 接口获取有效期内的股东增减持数据。
        有效期：50天

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            List[dict]: 股东增减持事件列表
        """
        # 构建缓存键
        cache_key = f"holdertrade_{stock_code}_{score_date}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # 计算窗口起始日期（★ 5 个交易日 ✓，原 50 自然日 ✗）
        start_date = self._window_start(score_date, EVENT_WINDOW_TRADING_DAYS)
        # 转换为 Tushare 格式代码
        ts_code = self._convert_ts_code(stock_code)
        events = []

        try:
            pro = self._get_pro()
            # 调用 stk_holdertrade 接口
            df = self._call_tushare_with_retry(
                pro.stk_holdertrade,
                ts_code=ts_code,
                fields="ts_code,ann_date,holder_name,holder_type,in_de,change_vol,after_share",
            )
            # 检查返回数据
            if df is None or df.empty:
                logger.debug(f"无股东增减持数据: {stock_code}")
                self._cache.set(cache_key, events)
                return events

            # 过滤有效期内的记录
            df = self._filter_by_date(df, "ann_date", start_date, score_date)
            if df.empty:
                self._cache.set(cache_key, events)
                return events

            # 遍历每条增减持记录
            for _, row in df.iterrows():
                event = self._parse_holdertrade_event(row)
                if event:
                    events.append(event)

            logger.debug(f"股东增减持事件: {stock_code}, {len(events)} 条")
        except Exception as e:
            logger.error(f"股东增减持查询失败: {stock_code}, {e}")

        # 写入缓存
        self._cache.set(cache_key, events)
        return events

    def _parse_holdertrade_event(self, row) -> Optional[dict]:
        """
        解析单条股东增减持记录

        in_de 字段：IN=增持，DE=减持
        holder_type 字段：判断是否为大股东

        参数:
            row: DataFrame 行数据
        返回:
            dict: 事件字典，无效返回 None
        """
        # 获取增减持方向
        in_de = str(row.get("in_de", "")).strip().upper()
        # 获取公告日期
        ann_date = str(row.get("ann_date", ""))
        # 获取股东类型
        holder_type = str(row.get("holder_type", "")).strip()

        # 增持事件
        if in_de == "IN":
            return {"type": "股东增持", "score": POSITIVE_SCORES["股东增持"],
                    "date": ann_date, "holder_type": holder_type}

        # 减持事件
        if in_de == "DE":
            return {"type": "股东减持", "score": NEGATIVE_SCORES["股东减持"],
                    "date": ann_date, "holder_type": holder_type}

        # 未知方向不计分
        return None

    def _check_repurchase(self, stock_code: str, score_date: str) -> List[dict]:
        """
        查询股票回购事件

        通过 Tushare repurchase 接口获取有效期内的回购数据。
        有效期：50天

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            List[dict]: 回购事件列表
        """
        # 构建缓存键
        cache_key = f"repurchase_{stock_code}_{score_date}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # 计算窗口起始日期（★ 5 个交易日 ✓，原 50 自然日 ✗）
        start_date = self._window_start(score_date, EVENT_WINDOW_TRADING_DAYS)
        # 转换为 Tushare 格式代码
        ts_code = self._convert_ts_code(stock_code)
        events = []

        try:
            pro = self._get_pro()
            # 调用 repurchase 接口
            df = self._call_tushare_with_retry(
                pro.repurchase,
                ts_code=ts_code,
                fields="ts_code,ann_date,proc,amount,exp_date",
            )
            # 检查返回数据
            if df is None or df.empty:
                logger.debug(f"无股票回购数据: {stock_code}")
                self._cache.set(cache_key, events)
                return events

            # 过滤有效期内的记录
            df = self._filter_by_date(df, "ann_date", start_date, score_date)
            if df.empty:
                self._cache.set(cache_key, events)
                return events

            # 每条回购记录都是正面事件
            for _, row in df.iterrows():
                ann_date = str(row.get("ann_date", ""))
                events.append({
                    "type": "股票回购",
                    "score": POSITIVE_SCORES["股票回购"],
                    "date": ann_date,
                })
            logger.debug(f"股票回购事件: {stock_code}, {len(events)} 条")
        except Exception as e:
            logger.error(f"股票回购查询失败: {stock_code}, {e}")

        self._cache.set(cache_key, events)
        return events

    def _check_block_trade(self, stock_code: str, score_date: str) -> List[dict]:
        """
        查询大宗交易事件，折价超过5%为负面事件。有效期：5天

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            List[dict]: 大宗交易事件列表
        """
        # 构建缓存键
        cache_key = f"block_trade_{stock_code}_{score_date}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        # 计算窗口起始日期（★ 5 个交易日 ✓，原 5 自然日 ✗）
        start_date = self._window_start(score_date, EVENT_WINDOW_TRADING_DAYS)
        ts_code = self._convert_ts_code(stock_code)
        events = []
        try:
            pro = self._get_pro()
            # 调用 block_trade 接口
            df = self._call_tushare_with_retry(
                pro.block_trade, ts_code=ts_code,
                start_date=start_date, end_date=score_date,
                fields="ts_code,trade_date,price,vol,amount,buyer,seller,premium",
            )
            if df is None or df.empty:
                logger.debug(f"无大宗交易数据: {stock_code}")
                self._cache.set(cache_key, events)
                return events
            # 遍历每条大宗交易记录
            for _, row in df.iterrows():
                premium = self._safe_float(row.get("premium"), 0)
                trade_date = str(row.get("trade_date", ""))
                # 折价超过5%为负面事件（premium 为负表示折价）
                if premium < -BLOCK_TRADE_DISCOUNT_THRESHOLD:
                    events.append({"type": "大宗交易折价", "score": NEGATIVE_SCORES["大宗交易折价"],
                                   "date": trade_date, "premium": premium})
            logger.debug(f"大宗交易事件: {stock_code}, {len(events)} 条")
        except Exception as e:
            logger.error(f"大宗交易查询失败: {stock_code}, {e}")
        self._cache.set(cache_key, events)
        return events

    def _check_top_list(self, stock_code: str, score_date: str) -> List[dict]:
        """
        查询龙虎榜事件，机构净买入为正面事件，净卖出为负面事件。有效期：5天

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            List[dict]: 龙虎榜事件列表
        """
        cache_key = f"top_list_{stock_code}_{score_date}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        # 计算窗口起始日期（★ 5 个交易日 ✓，原 5 自然日 ✗）
        start_date = self._window_start(score_date, EVENT_WINDOW_TRADING_DAYS)
        ts_code = self._convert_ts_code(stock_code)
        events = []
        try:
            pro = self._get_pro()
            # top_list 接口需要 trade_date 参数，需要逐个日期查询
            # 获取有效期内的所有交易日
            from datetime import datetime, timedelta
            start_dt = datetime.strptime(start_date, "%Y%m%d")
            end_dt = datetime.strptime(score_date, "%Y%m%d")
            current_dt = start_dt
            while current_dt <= end_dt:
                trade_date = current_dt.strftime("%Y%m%d")
                df = self._call_tushare_with_retry(
                    pro.top_list, ts_code=ts_code, trade_date=trade_date,
                    fields="ts_code,trade_date,name,buy,sell,net_buy",
                )
                if df is not None and not df.empty:
                    # 遍历每条龙虎榜记录
                    for _, row in df.iterrows():
                        net_buy = self._safe_float(row.get("net_buy"), 0)
                        trade_date_str = str(row.get("trade_date", ""))
                        if net_buy > 0:
                            events.append({"type": "龙虎榜机构净买入", "score": POSITIVE_SCORES["龙虎榜机构净买入"], "date": trade_date_str})
                        elif net_buy < 0:
                            events.append({"type": "龙虎榜净卖出", "score": NEGATIVE_SCORES["龙虎榜净卖出"], "date": trade_date_str})
                current_dt += timedelta(days=1)
            logger.debug(f"龙虎榜事件: {stock_code}, {len(events)} 条")
        except Exception as e:
            logger.error(f"龙虎榜查询失败: {stock_code}, {e}")
        self._cache.set(cache_key, events)
        return events

    def _check_shock(self, stock_code: str, score_date: str) -> List[dict]:
        """
        查询个股异常波动事件。有效期：10天

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            List[dict]: 异常波动事件列表
        """
        cache_key = f"shock_{stock_code}_{score_date}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        # 计算窗口起始日期（★ 5 个交易日 ✓，原 10 自然日 ✗）
        start_date = self._window_start(score_date, EVENT_WINDOW_TRADING_DAYS)
        ts_code = self._convert_ts_code(stock_code)
        events = []
        try:
            pro = self._get_pro()
            df = self._call_tushare_with_retry(
                pro.stk_shock, ts_code=ts_code,
                fields="ts_code,ann_date,shock_reason",
            )
            if df is None or df.empty:
                logger.debug(f"无异常波动数据: {stock_code}")
                self._cache.set(cache_key, events)
                return events
            # 过滤有效期内的记录
            df = self._filter_by_date(df, "ann_date", start_date, score_date)
            if df.empty:
                self._cache.set(cache_key, events)
                return events
            for _, row in df.iterrows():
                ann_date = str(row.get("ann_date", ""))
                events.append({"type": "异常波动", "score": NEGATIVE_SCORES["异常波动"], "date": ann_date})
            logger.debug(f"异常波动事件: {stock_code}, {len(events)} 条")
        except Exception as e:
            logger.error(f"异常波动查询失败: {stock_code}, {e}")
        self._cache.set(cache_key, events)
        return events

    # ============================================================
    # 辅助方法
    # ============================================================

    def _filter_by_date(self, df: pd.DataFrame, date_col: str,
                        start_date: str, end_date: str) -> pd.DataFrame:
        """
        按日期列过滤 DataFrame，保留有效期内的记录

        参数:
            df: 原始 DataFrame
            date_col: 日期列名
            start_date: 起始日期（YYYYMMDD 格式）
            end_date: 结束日期（YYYYMMDD 格式）
        返回:
            DataFrame: 过滤后的数据
        """
        if date_col not in df.columns:
            return df
        df = df.copy()
        df[date_col] = df[date_col].astype(str).str.strip()
        mask = (df[date_col] >= start_date) & (df[date_col] <= end_date)
        return df[mask]

    def _safe_float(self, value, default: float = 0) -> float:
        """
        安全地将值转换为浮点数

        参数:
            value: 待转换的值
            default: 转换失败时的默认值
        返回:
            float: 转换后的浮点数
        """
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    # ============================================================
    # 核心评分方法
    # ============================================================

    def calculate_score(self, stock_code: str, score_date: str) -> Tuple[float, EventDetail]:
        """
        计算指定股票的事件驱动得分

        综合公式：事件驱动得分 = Sigma(正面事件加分) + Sigma(负面事件减分)
        得分范围：-100 到 +100

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期，格式 YYYY-MM-DD 或 YYYYMMDD
        返回:
            Tuple[float, EventDetail]: (事件驱动得分, 事件详情对象)
        """
        logger.debug(f"开始计算事件驱动得分: {stock_code}, 日期: {score_date}")
        detail = EventDetail()
        formatted_date = self._format_date(score_date)
        # 先检查一票否决条件
        is_veto, veto_reason = self.check_veto(stock_code, formatted_date)
        if is_veto:
            detail.veto = True
            detail.veto_reason = veto_reason
            logger.warning(f"股票 {stock_code} 事件驱动一票否决: {veto_reason}")
            return VETO_SCORE, detail
        # 收集所有事件
        all_events = self._collect_all_events(stock_code, formatted_date)
        # 分类正面和负面事件
        for event in all_events:
            score = event.get("score", 0)
            if score > 0:
                detail.positive_events.append(event)
            elif score < 0:
                detail.negative_events.append(event)
        # 计算总分，基准分为50分
        positive_total = sum(e.get("score", 0) for e in detail.positive_events)
        negative_total = sum(e.get("score", 0) for e in detail.negative_events)
        total_score = max(-100, min(100, 50 + positive_total + negative_total))
        logger.debug(f"股票 {stock_code} 事件驱动得分: {total_score} (基准分=50, 正面={positive_total}, 负面={negative_total})")
        return total_score, detail

    def _collect_all_events(self, stock_code: str, score_date: str) -> List[dict]:
        """收集所有类型的事件数据"""
        all_events = []
        all_events.extend(self._check_forecast(stock_code, score_date))
        all_events.extend(self._check_holdertrade(stock_code, score_date))
        all_events.extend(self._check_repurchase(stock_code, score_date))
        all_events.extend(self._check_block_trade(stock_code, score_date))
        all_events.extend(self._check_top_list(stock_code, score_date))
        all_events.extend(self._check_shock(stock_code, score_date))
        return all_events

    def check_veto(self, stock_code: str, score_date: str) -> Tuple[bool, str]:
        """
        检查事件驱动一票否决条件

        一票否决条件：
          1. 被ST或*ST
          2. 业绩暴雷（预减>80%或巨亏）
          3. 大股东减持

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            Tuple[bool, str]: (是否触发一票否决, 否决原因)
        """
        formatted_date = self._format_date(score_date)
        # 注意：不做 ST 状态检查（历史回测无法准确还原，由策略自身处理）
        # 条件1：检查业绩暴雷
        is_crash, crash_reason = self._check_forecast_crash(stock_code, formatted_date)
        if is_crash:
            logger.warning(f"股票 {stock_code} 一票否决: {crash_reason}")
            return True, crash_reason
        # 条件3：检查大股东减持
        is_major_sell, sell_reason = self._check_major_holder_sell(stock_code, formatted_date)
        if is_major_sell:
            logger.warning(f"股票 {stock_code} 一票否决: {sell_reason}")
            return True, sell_reason
        # 条件4：检查减持计划公告（预披露），用户确认一律否决
        is_reduce_plan, plan_reason = self._check_reduce_plan(stock_code, formatted_date)
        if is_reduce_plan:
            logger.warning(f"股票 {stock_code} 一票否决: {plan_reason}")
            return True, plan_reason
        return False, ""

    def _check_forecast_crash(self, stock_code: str, score_date: str) -> Tuple[bool, str]:
        """
        检查业绩暴雷条件（预减>80%或巨亏）

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            Tuple[bool, str]: (是否业绩暴雷, 原因)
        """
        ts_code = self._convert_ts_code(stock_code)
        try:
            pro = self._get_pro()
            df = self._call_tushare_with_retry(
                pro.forecast, ts_code=ts_code,
                fields="ts_code,ann_date,end_date,type,p_change_min,p_change_max,net_profit_min",
            )
            if df is None or df.empty:
                return False, ""
            # 过滤有效期内的记录
            #   ★【2026-09-27 用户口径】否决只看**最近 5 个交易日** ✓（原：20 自然日 ✗）
            start_date = self._veto_window_start(score_date)
            df = self._filter_by_date(df, "ann_date", start_date, score_date)
            if df.empty:
                return False, ""
            # 检查每条记录
            for _, row in df.iterrows():
                forecast_type = str(row.get("type", "")).strip()
                p_change_min = self._safe_float(row.get("p_change_min"), 0)
                # 预减幅度超过80%
                if forecast_type == "预减" and p_change_min < FORECAST_CRASH_THRESHOLD:
                    return True, f"业绩暴雷：预减幅度 {p_change_min:.1f}%"
                # 首亏且净利润为负（巨亏）
                if forecast_type == "首亏":
                    net_profit_min = self._safe_float(row.get("net_profit_min"), 0)
                    if net_profit_min < 0:
                        return True, "业绩暴雷：首亏巨亏"
        except Exception as e:
            logger.error(f"业绩暴雷检查失败: {stock_code}, {e}")
        return False, ""

    def _check_major_holder_sell(self, stock_code: str, score_date: str) -> Tuple[bool, str]:
        """
        检查大股东减持条件

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            Tuple[bool, str]: (是否大股东减持, 原因)
        """
        # ★【2026-09-27 用户口径】否决只看**最近 5 个交易日**内的公告 ✓
        #   · `_check_holdertrade` 仍按 50 自然日取数 ✓ —— 它是**打分维度共用**的 ✗，
        #     口径**不动** ✗；此处**只过滤否决** ✓（单一改动点 ✓，评分行为零变化 ✓）
        window_start = self._veto_window_start(score_date)
        holdertrade_events = self._check_holdertrade(stock_code, score_date)
        for event in holdertrade_events:
            if event.get("type") == "股东减持":
                _d = str(event.get("date") or "").replace("-", "")[:8]
                if not _d:
                    logger.debug(f"{stock_code} 减持事件缺日期 ⇒ 窗口外，不否决 ✓")
                    continue
                if _d < window_start:
                    logger.debug(f"{stock_code} 减持 {_d} < 窗口起点 {window_start} "
                                 f"⇒ 超 5 个交易日，不否决 ✓")
                    continue
                holder_type = event.get("holder_type", "")
                if any(kw in holder_type for kw in ["大股东", "控股股东", "实际控制人", "5%以上"]):
                    return True, f"大股东减持（{holder_type}，公告 {_d}）"
        return False, ""

    def _is_reduce_plan(self, title: str) -> bool:
        """
        判断公告标题是否为"减持计划（预披露）"公告（委托纯函数，便于单测）。

        参数:
            title: 公告标题文本
        返回:
            bool: 是否为减持计划公告
        """
        # 委托给 reduce_plan_cache 的纯函数（关键词权威源，避免重复定义）
        return is_reduce_plan_title(title)

    def _check_reduce_plan(self, stock_code: str, score_date: str) -> Tuple[bool, str]:
        """
        经本地缓存（数据层）核查减持计划公告（预披露）

        减持计划利空大于已实施减持，用户确认所有减持计划公告一律触发一票否决。
        优先读取离线刷新的本地缓存文件（评分零网络请求，免疫巨潮限流）；
        缓存缺失或过期才回退实时调用巨潮并落盘，失败则沿用旧缓存避免漏判。

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期（YYYYMMDD 格式）
        返回:
            Tuple[bool, str]: (是否命中减持计划, 原因描述)
        """
        # 计算有效期起始日期（用于过滤缓存中仍有效的计划）
        #   ★【2026-09-27 用户口径】否决只看**最近 5 个交易日** ✓（原：180 自然日 ✗）
        #   · 数据层 `rpc.fetch_reduce_plans` 仍按 180 天**取数/缓存** ✓（缓存是共享的 ✓，
        #     缩短取数范围会让缓存反复失效 ✗）⇒ 此处**只收窄判据** ✓
        start_date = self._veto_window_start(score_date)

        def _match(plans):
            # 在计划列表中找到有效期内命中的减持计划
            for p in plans:
                ann_date = p.get("ann_date", "")
                # 上界约束：公告日不得晚于评分日。防止回测/历史重放时误用
                # 尚未发布的"未来公告"造成提前函数（look-ahead bias）。
                # 实盘 score_date=当天时该上界恒成立（缓存公告均<=当天），无副作用。
                if ann_date and start_date <= ann_date <= score_date:
                    return True, f"减持计划公告：{p.get('title', '')}"
            return False, ""

        # 优先读取本地缓存文件（离线阶段批量刷新，评分零网络请求）
        updated_date, plans = rpc.get_plans(stock_code)
        if rpc.is_fresh(updated_date, score_date):
            hit, reason = _match(plans)
            # 缓存新鲜：直接判定，命中即否决
            if hit:
                return hit, reason
            return False, ""
        # 缓存缺失或过期：回退实时调用巨潮（保留重试退避），成功后落盘
        try:
            fresh_plans = rpc.fetch_reduce_plans(stock_code, score_date)
            # 实时拉取失败（限流/异常）返回 None：不写缓存，进入 except 沿用旧缓存
            if fresh_plans is None:
                raise RuntimeError("减持计划实时拉取失败")
            # 落盘（即便为空也刷新 updated_date，避免每日重复实时请求）
            # 仅实盘（评分日=当天）写回实盘缓存；回测/历史重放不写回，避免污染真实缓存
            if score_date == datetime.now().strftime("%Y%m%d"):
                rpc.upsert_plan(stock_code, fresh_plans, score_date)
            hit, reason = _match(fresh_plans)
            if hit:
                return hit, reason
            return False, ""
        except Exception as e:
            logger.error(f"减持计划实时查询异常: {stock_code}, {e}")
            # 实时失败：沿用旧缓存（不漏判）；无旧缓存则降级未命中
            hit, reason = _match(plans)
            if hit:
                return hit, reason
            return False, ""
