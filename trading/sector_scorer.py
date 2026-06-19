# -*- coding: utf-8 -*-
"""
板块强度评分器模块

基于板块行情和资金流向数据计算板块强度得分。
数据来源：
  - Tushare Pro ths_daily 接口（同花顺板块行情，需6000积分）
  - Tushare Pro moneyflow_ind_ths 接口（同花顺行业资金流向，需6000积分）
  - Tushare Pro ths_member 接口（个股-板块映射，需5000积分）

评分维度：
  1. 板块涨幅排名得分（近5日）- 前10名 +20分/天
  2. 板块资金流向得分（近5日）- 净流入 +20分/天，净流出 -20分/天

综合公式：
  板块强度得分 = 近5日涨幅排名总分 + 近5日资金流向总分
  得分范围：-100 到 +200

个股板块得分：
  个股板块得分 = MAX(所属板块的当日得分)

一票否决条件：
  - 板块得分 = -100 时，个股直接淘汰
"""

import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

# 导入板块强度详情模型
from trading.stock_score_models import SectorDetail

# 配置日志记录器
logger = logging.getLogger(__name__)


# ============================================================
# 板块强度评分常量配置
# ============================================================

# 一票否决得分
VETO_SCORE = -100
# 基准分
BASE_SCORE = 50
# 板块涨幅排名阈值（前20名加分）
RANK_TOP_N = 20
# 涨幅排名加分
RANK_SCORE = 50
# 资金流向加分（净流入 > 10000万元）
MONEYFLOW_POSITIVE = 50
# 资金流向减分（净流出 ≤ -10000万元）
MONEYFLOW_NEGATIVE = -50
# 资金流向阈值（万元）
MONEYFLOW_THRESHOLD = 10000

# 评分天数（仅当天）
SCORE_DAYS = 1

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


class SectorScorer:
    """
    板块强度评分器

    根据 Tushare 板块行情和资金流向数据计算板块强度得分。
    两个评分维度：涨幅排名得分、资金流向得分。
    支持一票否决机制（板块得分 -100 时个股直接淘汰）。
    """

    def __init__(self, tushare_token: str = None, **kwargs):
        """
        初始化板块强度评分器

        参数:
            tushare_token: Tushare API token，为 None 时从配置文件读取
            **kwargs: 兼容额外参数（如 db_manager）
        """
        # 初始化 Tushare token
        self._token = tushare_token or self._load_tushare_token()
        # 初始化 Tushare pro API 对象（延迟加载）
        self._pro = None
        # 初始化内存缓存
        self._cache = MemoryCache()
        # 记录初始化日志
        logger.info("板块强度评分器初始化完成")

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

    # ============================================================
    # 数据获取方法
    # ============================================================

    def _get_stock_sectors(self, stock_code: str) -> List[dict]:
        """
        获取个股所属板块列表

        通过 Tushare ths_member 接口查询个股所属板块代码，
        再通过 ths_index 接口获取板块名称。

        参数:
            stock_code: 股票代码（6位数字）
        返回:
            List[dict]: 板块列表，每个元素包含 ts_code 和 name
        """
        # 构建缓存键
        cache_key = f"stock_sectors_{stock_code}"
        # 检查缓存
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"命中板块映射缓存: {cache_key}")
            return cached

        # 转换为 Tushare 格式代码
        ts_code = self._convert_ts_code(stock_code)

        try:
            pro = self._get_pro()
            # 使用 con_code 参数查询个股所属板块
            df = self._call_tushare_with_retry(
                pro.ths_member,
                con_code=ts_code,
            )
            # 检查返回数据是否有效
            if df is None or df.empty:
                logger.warning(f"个股板块映射为空: {stock_code}")
                self._cache.set(cache_key, [])
                return []

            # 获取板块代码列表
            sector_codes = df["ts_code"].unique().tolist()

            # 通过 ths_index 获取板块名称映射（全量查询后缓存）
            sector_name_map = self._get_sector_name_map()

            # 只保留概念板块(N)和行业板块(I)，过滤大盘指数等
            # 排除"融资融券"板块，因为该板块评分不准确
            EXCLUDED_SECTORS = {"融资融券"}
            VALID_SECTOR_TYPES = {"N", "I"}
            sectors = []
            for sec_code in sector_codes:
                info = sector_name_map.get(sec_code, {})
                sec_name = info.get("name", "") if isinstance(info, dict) else ""
                sec_type = info.get("type", "") if isinstance(info, dict) else ""
                # 只保留概念板块和行业板块，排除"融资融券"板块
                if (sec_code and sec_name and sec_type in VALID_SECTOR_TYPES 
                    and sec_name not in EXCLUDED_SECTORS):
                    sectors.append({
                        "ts_code": sec_code,
                        "name": sec_name,
                    })

            logger.debug(
                f"获取个股板块映射成功: {stock_code}, "
                f"{len(sectors)} 个板块, "
                f"有名称: {sum(1 for s in sectors if s['name'])} 个"
            )
            # 写入缓存
            self._cache.set(cache_key, sectors)
            return sectors
        except Exception as e:
            logger.error(f"获取个股板块映射失败: {stock_code}, {e}")
            return []

    def _get_sector_name_map(self) -> dict:
        """
        获取板块代码到名称和类型的映射表

        通过 ths_index 接口全量查询板块列表，缓存结果。

        返回:
            dict: {板块代码: {"name": 板块名称, "type": 板块类型}}
        """
        # 检查缓存
        cache_key = "sector_name_map"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            pro = self._get_pro()
            # 全量查询板块列表（不限 type，获取所有板块）
            df = self._call_tushare_with_retry(pro.ths_index)
            name_map = {}
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = row.get("ts_code", "")
                    name = row.get("name", "")
                    sec_type = row.get("type", "")
                    if code and name:
                        name_map[code] = {
                            "name": name,
                            "type": sec_type,
                        }
            logger.debug(f"获取板块名称映射: {len(name_map)} 个板块")
            # 写入缓存
            self._cache.set(cache_key, name_map)
            return name_map
        except Exception as e:
            logger.error(f"获取板块名称映射失败: {e}")
            return {}

    def _fetch_sector_daily(
        self, trade_date: str
    ) -> Optional[pd.DataFrame]:
        """
        获取指定交易日所有板块的行情数据

        通过 Tushare ths_daily 接口获取当日所有板块涨跌幅。

        参数:
            trade_date: 交易日期（YYYYMMDD 格式）
        返回:
            DataFrame: 板块行情数据，失败返回 None
        """
        # 构建缓存键
        cache_key = f"sector_daily_{trade_date}"
        
        # 检查是否是今天的日期，如果是今天且尚未收盘，跳过缓存（允许重试获取）
        is_today = False
        try:
            today_str = datetime.now().strftime('%Y%m%d')
            is_today = trade_date == today_str
        except:
            pass
        
        # 检查缓存（非今日数据使用缓存，今日数据允许重新获取）
        cached = self._cache.get(cache_key)
        if cached is not None and not is_today:
            logger.debug(f"命中板块行情缓存: {cache_key}")
            return cached

        try:
            pro = self._get_pro()
            # 调用 ths_daily 接口获取当日所有板块行情
            df = self._call_tushare_with_retry(
                pro.ths_daily,
                trade_date=trade_date,
            )
            # 检查返回数据是否有效
            if df is not None and not df.empty:
                logger.debug(
                    f"获取板块行情成功: {trade_date}, {len(df)} 个板块"
                )
                # 写入缓存
                self._cache.set(cache_key, df)
                return df
            
            # 返回空数据 - 不输出日志，避免日志过多
            
            return None
        except Exception as e:
            logger.error(f"获取板块行情失败: {trade_date}, {e}")
            return None

    def _fetch_sector_moneyflow(
        self, trade_date: str
    ) -> Optional[pd.DataFrame]:
        """
        获取指定交易日所有板块的资金流向数据

        通过 Tushare moneyflow_cnt_ths 接口获取当日概念板块资金流向。
        注意：使用 moneyflow_cnt_ths（概念板块）而非 moneyflow_ind_ths（行业板块），
        因为 ths_member 返回的板块代码与概念板块资金流向接口匹配。

        参数:
            trade_date: 交易日期（YYYYMMDD 格式）
        返回:
            DataFrame: 板块资金流向数据，失败返回 None
        """
        # 构建缓存键
        cache_key = f"sector_moneyflow_{trade_date}"
        # 检查缓存
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"命中板块资金流向缓存: {cache_key}")
            return cached

        try:
            pro = self._get_pro()
            # 调用 moneyflow_cnt_ths 接口获取当日概念板块资金流向
            df = self._call_tushare_with_retry(
                pro.moneyflow_cnt_ths,
                trade_date=trade_date,
            )
            # 检查返回数据是否有效
            if df is not None and not df.empty:
                logger.debug(
                    f"获取板块资金流向成功: {trade_date}, {len(df)} 个板块"
                )
                # 写入缓存
                self._cache.set(cache_key, df)
                return df
            # 返回空数据，使用 debug 级别避免日志过多
            logger.debug(f"板块资金流向数据为空: {trade_date}")
            return None
        except Exception as e:
            logger.error(f"获取板块资金流向失败: {trade_date}, {e}")
            return None

    # ============================================================
    # 评分计算方法
    # ============================================================

    def _score_rank(self, sector_code: str, dates: List[str], sector_name: str = "") -> float:
        """
        计算板块涨幅排名得分

        评分规则：
          - 板块当日涨幅排名进入前20名：+50分
          - 板块当日涨幅排名未进入前20名：0分

        支持按板块代码或板块名称匹配（本地板块代码与Tushare格式不同时用名称匹配）。

        参数:
            sector_code: 板块代码（如 '885823.TI' 或 'TS108'）
            dates: 交易日列表（YYYYMMDD 格式）
            sector_name: 板块名称（用于名称匹配回退）
        返回:
            float: 涨幅排名得分
        """
        total_score = 0.0

        for trade_date in dates:
            # 获取当日所有板块行情
            df = self._fetch_sector_daily(trade_date)
            if df is None or df.empty:
                # 当日无数据，跳过
                logger.debug(f"板块行情无数据: {trade_date}")
                continue

            # 确保 pct_chg 字段存在（涨跌幅，也兼容 pct_change）
            pct_col = "pct_chg" if "pct_chg" in df.columns else "pct_change"
            if pct_col not in df.columns:
                logger.warning(f"板块行情缺少涨跌幅字段: {trade_date}")
                continue

            # 按涨跌幅降序排列，计算排名
            df_sorted = df.sort_values(pct_col, ascending=False).reset_index(drop=True)
            # 先尝试按板块代码匹配
            ts_code_col = "ts_code" if "ts_code" in df_sorted.columns else "code"
            sector_rows = df_sorted[df_sorted[ts_code_col] == sector_code]

            # 代码匹配失败时，尝试按名称匹配
            if sector_rows.empty and sector_name:
                name_col = "name" if "name" in df_sorted.columns else None
                if name_col:
                    sector_rows = df_sorted[df_sorted[name_col] == sector_name]

            if sector_rows.empty:
                # 该板块当日无数据
                logger.debug(f"板块 {sector_name or sector_code} 在 {trade_date} 无行情数据")
                continue

            # 获取排名（1-based）
            rank = sector_rows.index[0] + 1
            # 前20名加分
            if rank <= RANK_TOP_N:
                total_score = RANK_SCORE
                logger.debug(
                    f"板块 {sector_name or sector_code} 在 {trade_date} 排名第{rank}，+{RANK_SCORE}分"
                )

        return total_score

    def _score_moneyflow(self, sector_code: str, dates: List[str], sector_name: str = "") -> float:
        """
        计算板块资金流向得分

        评分规则：
          - 板块当日资金净流入 > 10000万元：+50分
          - 板块当日资金净流入 ≤ -10000万元：-50分
          - 其他情况：0分

        支持按板块代码或板块名称匹配。

        参数:
            sector_code: 板块代码（如 '885823.TI' 或 'TS108'）
            dates: 交易日列表（YYYYMMDD 格式）
            sector_name: 板块名称（用于名称匹配回退）
        返回:
            float: 资金流向得分
        """
        total_score = 0.0

        for trade_date in dates:
            # 获取当日所有板块资金流向
            df = self._fetch_sector_moneyflow(trade_date)
            if df is None or df.empty:
                # 当日无数据，跳过
                logger.debug(f"板块资金流向无数据: {trade_date}")
                continue

            # 确保 net_amount 字段存在
            if "net_amount" not in df.columns:
                logger.warning(f"板块资金流向缺少 net_amount 字段: {trade_date}")
                continue

            # 先尝试按板块代码匹配
            ts_code_col = "ts_code" if "ts_code" in df.columns else "code"
            sector_rows = df[df[ts_code_col] == sector_code]

            # 代码匹配失败时，尝试按名称匹配
            if sector_rows.empty and sector_name:
                # moneyflow_ind_ths 返回的名称字段为 industry
                name_col = None
                for col in ["industry", "name", "sector_name"]:
                    if col in df.columns:
                        name_col = col
                        break
                if name_col:
                    sector_rows = df[df[name_col] == sector_name]

            if sector_rows.empty:
                # 该板块当日无资金流向数据
                logger.debug(f"板块 {sector_name or sector_code} 在 {trade_date} 无资金流向数据")
                continue

            # 获取净流入金额（亿元）
            net_amount = float(sector_rows.iloc[0]["net_amount"])
            # 转换为万元
            net_amount_wan = net_amount * 10000
            # 根据资金流向计算得分
            if net_amount_wan > MONEYFLOW_THRESHOLD:
                total_score = MONEYFLOW_POSITIVE
                logger.debug(
                    f"板块 {sector_name or sector_code} 在 {trade_date} 净流入 {net_amount_wan:.2f}万，"
                    f"+{MONEYFLOW_POSITIVE}分"
                )
            elif net_amount_wan <= -MONEYFLOW_THRESHOLD:
                total_score = MONEYFLOW_NEGATIVE
                logger.debug(
                    f"板块 {sector_name or sector_code} 在 {trade_date} 净流出 {-net_amount_wan:.2f}万，"
                    f"{MONEYFLOW_NEGATIVE}分"
                )

        return total_score

    def _calculate_sector_score(
        self, sector_code: str, sector_name: str, dates: List[str]
    ) -> Tuple[float, SectorDetail]:
        """
        计算单个板块的综合得分

        综合公式：
          板块强度得分 = 基准分(50) + 涨幅排名得分 + 资金流向得分
          得分范围：0 到 150

        参数:
            sector_code: 板块代码
            sector_name: 板块名称
            dates: 交易日列表
        返回:
            Tuple[float, SectorDetail]: (板块得分, 板块详情对象)
        """
        # 初始化详情对象
        detail = SectorDetail()
        detail.sector_name = sector_name

        # 1. 计算涨幅排名得分（传递板块名称用于名称匹配）
        rank_score = self._score_rank(sector_code, dates, sector_name=sector_name)
        detail.rank_score = rank_score

        # 2. 计算资金流向得分（传递板块名称用于名称匹配）
        moneyflow_score = self._score_moneyflow(sector_code, dates, sector_name=sector_name)
        detail.moneyflow_score = moneyflow_score

        # 3. 计算综合得分（加上基准分）
        total_score = BASE_SCORE + rank_score + moneyflow_score

        return total_score, detail

    # ============================================================
    # 公开接口方法
    # ============================================================

    def calculate_score(
        self, stock_code: str, score_date: str
    ) -> Tuple[float, SectorDetail]:
        """
        计算指定股票在指定日期的板块强度得分

        流程：
          1. 获取个股所属板块列表
          2. 计算每个板块的综合得分
          3. 取最高分板块作为个股板块得分
          4. 检查一票否决条件

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期，格式 YYYY-MM-DD 或 YYYYMMDD
        返回:
            Tuple[float, SectorDetail]: (板块强度得分, 板块详情对象)
        """
        logger.debug(f"开始计算板块强度得分: {stock_code}, 日期: {score_date}")

        # 检查是否为交易日
        from utils.trade_date_utils import is_trading_day
        if not is_trading_day(score_date):
            logger.debug(f"日期 {score_date} 不是交易日，跳过板块强度评分")
            detail = SectorDetail()
            return 0, detail

        # 初始化详情对象
        detail = SectorDetail()
        # 统一日期格式为 YYYYMMDD
        formatted_date = self._format_date(score_date)

        # 获取近5个交易日列表
        dates = self._get_trade_dates(formatted_date, SCORE_DAYS)
        if not dates:
            # 无法获取交易日，返回 0 分
            logger.warning(f"无法获取交易日列表: {formatted_date}")
            return 0, detail

        # 预加载所有需要的板块数据（减少API调用）
        self._preload_sector_data(dates)

        # 获取个股所属板块列表
        sectors = self._get_stock_sectors(stock_code)
        if not sectors:
            # 无板块映射，返回 0 分
            logger.warning(f"个股无板块映射: {stock_code}")
            return 0, detail

        # 计算每个板块的得分，取最高分
        best_score = None
        best_detail = detail

        for sector in sectors:
            sector_code = sector["ts_code"]
            sector_name = sector["name"]
            # 只处理有名称的板块
            if not sector_name:
                continue
            # 计算该板块的综合得分
            sector_score, sector_detail = self._calculate_sector_score(
                sector_code, sector_name, dates
            )
            # 记录板块得分（debug级别）
            logger.debug(
                f"板块 {sector_name}({sector_code}) 得分: {sector_score}"
            )
            # 更新最高分板块（跳过无有效数据的板块：排名和资金都为0说明无数据）
            has_data = (sector_detail.rank_score != 0 or sector_detail.moneyflow_score != 0)
            if has_data and (best_score is None or sector_score > best_score):
                best_score = sector_score
                best_detail = sector_detail

        # 如果没有计算出任何板块得分
        if best_score is None:
            logger.warning(f"个股 {stock_code} 所有板块均无数据")
            return 0, detail

        # 检查一票否决条件
        if best_score <= VETO_SCORE:
            best_detail.veto = True
            best_detail.veto_reason = (
                f"板块 {best_detail.sector_name} 得分 {best_score}，"
                f"触发一票否决（得分 ≤ {VETO_SCORE}）"
            )
            logger.warning(
                f"股票 {stock_code} 板块强度一票否决: {best_detail.veto_reason}"
            )
            return VETO_SCORE, best_detail

        # 记录最终得分
        logger.debug(
            f"股票 {stock_code} 板块强度得分: {best_score} "
            f"(最优板块: {best_detail.sector_name})"
        )
        return best_score, best_detail

    def check_veto(
        self,
        stock_code: str,
        score_date: str,
        sector_score: float = None,
    ) -> Tuple[bool, str]:
        """
        检查板块强度一票否决条件

        一票否决条件：
          - 板块得分 = -100 时，个股直接淘汰

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期
            sector_score: 已计算的板块得分（可选，为 None 时重新计算）
        返回:
            Tuple[bool, str]: (是否触发一票否决, 否决原因)
        """
        # 如果未传入板块得分，重新计算
        if sector_score is None:
            sector_score, detail = self.calculate_score(stock_code, score_date)
        else:
            detail = SectorDetail()

        # 检查一票否决条件：板块得分 <= -100
        if sector_score <= VETO_SCORE:
            reason = f"板块得分 {sector_score}，触发一票否决（得分 ≤ {VETO_SCORE}）"
            logger.warning(f"股票 {stock_code} 板块一票否决: {reason}")
            return True, reason

        # 未触发一票否决
        return False, ""

    def _preload_sector_data(self, dates: List[str]):
        """
        预加载所有需要的板块数据，减少API调用次数

        参数:
            dates: 交易日列表（YYYYMMDD 格式）
        """
        try:
            # 预加载板块名称映射
            self._get_sector_name_map()
            
            # 预加载每个日期的板块行情和资金流向数据
            for trade_date in dates:
                # 预加载板块行情数据
                self._fetch_sector_daily(trade_date)
                # 预加载板块资金流向数据
                self._fetch_sector_moneyflow(trade_date)
            
            logger.debug(f"预加载板块数据完成: {len(dates)} 个交易日")
        except Exception as e:
            logger.warning(f"预加载板块数据失败: {e}")
