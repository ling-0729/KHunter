# -*- coding: utf-8 -*-
"""
减持计划公告本地缓存模块

职责：
  - 作为"数据层"：从 AKShare 巨潮披露接口拉取候选池股票的减持计划公告，
    落盘到本地缓存文件 data/running/reduce_plan_cache.json，避免评分时实时请求巨潮。
  - 提供缓存读写、新鲜度判断、原子写、跨平台文件锁。

设计动机：
  巨潮对来源 IP 限流，实时评分每次请求会撞墙导致漏判。本模块将"数据获取"与"评分"解耦：
  离线（数据更新阶段）批量刷新写入缓存，评分时只读本地文件，彻底免疫限流。
"""

import contextlib
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ===== 减持计划关键词（集中定义，避免与 event_scorer 重复定义造成不一致）=====
# 计划关键词：命中其一即判定为减持计划预披露
REDUCE_PLAN_KEYWORDS = ["预披露", "计划", "拟减持", "提示性公告", "减持计划", "简式权益变动", "减持股份计划"]
# 排除词：命中即视为已实施减持进展或减持已结束，不计入计划（避免重复计分/误判）
# 含"结束类"表述（完毕/期限届满/实施完毕等）的公告代表减持已落地、利空出尽，
# 不应触发一票否决，故一并排除。
REDUCE_PLAN_EXCLUDE = ["进展", "实施结果", "完成", "终止", "时间过半", "数量过半",
                       "已减持", "完毕", "期限届满", "结束", "实施完毕", "已实施完毕"]
# 减持计划有效期（天）：公告发布后该天数内均参与判定
REDUCE_PLAN_VALIDITY = 180

# 缓存文件路径（与现有运行时文件同目录 data/running/）
REDUCE_PLAN_CACHE_FILE = "data/running/reduce_plan_cache.json"

# ===== 直连巨潮资讯接口（绕过 akshare，规避其硬编码列解析 bug 与无超时挂起）=====
# 巨潮公告查询接口（POST，form 表单）
CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
# 股票代码→orgId 映射源（用于拼装 stock={code},{orgId} 入参）
CNINFO_STOCK_JSON_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
# 请求头：模拟浏览器，避免被巨潮拒绝
CNINFO_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": "http://www.cninfo.com.cn/new/disclosure/stock",
}
# 单只公告查询 socket 超时（秒）——根治 akshare 无超时导致的挂起
CNINFO_TIMEOUT = 10
# 进程内缓存股票代码→orgId 映射，避免每只股票重复拉取
_ORG_ID_CACHE: Dict[str, str] = {}


def _get_org_id(stock_code: str) -> str:
    """
    查询股票代码对应的巨潮 orgId（进程内缓存，仅首次拉取一次映射表）。

    cninfo 公告查询接口要求 stock 参数形如 {code},{orgId}，orgId 来自官网股票列表 JSON。
    若映射缺失（如代码未收录）返回空串，由上层回退为仅用代码查询。

    参数:
        stock_code: 6 位股票代码
    返回:
        str: orgId；未找到返回空串
    """
    # 命中进程内缓存直接返回，避免重复网络请求
    if stock_code in _ORG_ID_CACHE:
        return _ORG_ID_CACHE[stock_code]
    try:
        # 拉取深交所股票列表（含沪深京 A 股），映射 code->orgId
        resp = requests.get(CNINFO_STOCK_JSON_URL, headers=CNINFO_HEADERS, timeout=CNINFO_TIMEOUT)
        resp.raise_for_status()
        stock_list = resp.json().get("stockList", [])
        for item in stock_list:
            code = item.get("code", "")
            org_id = item.get("orgId", "")
            if code and org_id:
                _ORG_ID_CACHE[code] = org_id
    except Exception as e:
        logger.warning("巨潮股票映射拉取失败，将回退仅用代码查询: %s", e)
    # 返回映射结果（缺失则为空串）
    return _ORG_ID_CACHE.get(stock_code, "")


def is_reduce_plan_title(title: str) -> bool:
    """
    纯逻辑判断公告标题是否为减持计划（预披露）公告，不依赖网络，便于单测。

    参数:
        title: 公告标题文本
    返回:
        bool: 是否为减持计划公告
    """
    # 空标题直接排除
    if not title:
        return False
    # 必须包含"减持"字样（与已实施减持区分基础）
    if "减持" not in title:
        return False
    # 命中排除词视为已实施减持进展，不计入计划
    if any(kw in title for kw in REDUCE_PLAN_EXCLUDE):
        return False
    # 命中任一计划关键词即判定为减持计划预披露
    return any(kw in title for kw in REDUCE_PLAN_KEYWORDS)


@contextlib.contextmanager
def _file_lock(cache_file: str):
    """
    跨平台文件锁上下文管理器，防止多进程并发写缓存导致损坏。

    使用独立 .lock 文件 + 平台原生锁（Windows msvcrt / POSIX fcntl）。
    """
    lock_path = cache_file + ".lock"
    if sys.platform == "win32":
        # Windows：基于 msvcrt 字节锁
        f = open(lock_path, "w")
        try:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            f.close()
    else:
        # POSIX：基于 fcntl 文件锁
        import fcntl
        f = open(lock_path, "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
            f.close()


def load_cache(cache_file: str = REDUCE_PLAN_CACHE_FILE) -> Dict[str, dict]:
    """
    加载减持计划缓存文件。

    参数:
        cache_file: 缓存文件路径
    返回:
        缓存字典；文件不存在或损坏返回空 dict（降级不抛异常）
    """
    # 文件不存在直接返回空，避免首跑报错
    if not os.path.exists(cache_file):
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("减持计划缓存读取失败，返回空: %s", e)
        return {}


def save_cache(cache: Dict[str, dict], cache_file: str = REDUCE_PLAN_CACHE_FILE,
              max_retry: int = 3) -> None:
    """
    原子写入缓存：先写临时文件再 rename，避免半写损坏导致评测读到残缺 JSON。

    Windows 下目标文件被占用时 os.replace 偶发 PermissionError，故加重试缓解。

    参数:
        cache: 完整缓存字典
        cache_file: 缓存文件路径
        max_retry: 替换失败最大重试次数
    """
    # 写临时文件，确保写入过程中主文件仍可读
    tmp = cache_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    # 原子替换（Windows 目标被占用时重试），读取方永远不会看到半写状态
    for attempt in range(max_retry):
        try:
            os.replace(tmp, cache_file)
            return
        except PermissionError:
            if attempt < max_retry - 1:
                time.sleep(0.05)  # 短暂退避后重试，缓解 Windows 文件占用
            else:
                raise


def get_plans(stock_code: str, cache_file: str = REDUCE_PLAN_CACHE_FILE) -> Tuple[str, List[dict]]:
    """
    读取某股票的 (updated_date, plans)。

    参数:
        stock_code: 股票代码（6位）
        cache_file: 缓存文件路径
    返回:
        (更新日期, 减持计划列表)；无记录返回 ("", [])
    """
    cache = load_cache(cache_file)
    entry = cache.get(stock_code)
    # 无记录返回空，交由调用方决定回退实时或沿用旧值
    if not entry:
        return "", []
    return entry.get("updated_date", ""), entry.get("plans", [])


def upsert_plan(stock_code: str, plans: List[dict], today: str,
                cache_file: str = REDUCE_PLAN_CACHE_FILE) -> None:
    """
    写入/刷新某股票减持计划并刷新 updated_date（带文件锁，保证并发安全）。

    参数:
        stock_code: 股票代码
        plans: 减持计划列表 [{title, ann_date}]
        today: 更新日期 YYYYMMDD
        cache_file: 缓存文件路径
    """
    with _file_lock(cache_file):
        cache = load_cache(cache_file)
        cache[stock_code] = {"updated_date": today, "plans": plans}
        save_cache(cache, cache_file)


def is_fresh(updated_date: str, today: str, max_age_days: int = 1) -> bool:
    """
    判断缓存是否新鲜（更新日期距今天数 <= max_age_days）。

    参数:
        updated_date: 缓存更新日期 YYYYMMDD
        today: 当前评分日期 YYYYMMDD
        max_age_days: 最大允许过期天数，默认 1（每日刷新）
    返回:
        bool: 是否新鲜
    """
    # 空日期视为过期，需回退实时
    if not updated_date:
        return False
    try:
        d = datetime.strptime(updated_date, "%Y%m%d").date()
        t = datetime.strptime(today, "%Y%m%d").date()
        return (t - d).days <= max_age_days
    except Exception:
        return False


def _get_start_date(score_date: str, days: int) -> str:
    """
    根据评分日期和有效期天数计算起始日期（YYYYMMDD）。

    参数:
        score_date: 评分日期 YYYYMMDD
        days: 向前天数
    返回:
        起始日期 YYYYMMDD
    """
    d = datetime.strptime(score_date, "%Y%m%d").date()
    return (d - timedelta(days=days)).strftime("%Y%m%d")


def _validity_range(score_date: str,
                    days: int = REDUCE_PLAN_VALIDITY) -> Tuple[str, str]:
    """评分日 ⇒ 公告**查询区间** `(start_fmt, end_fmt)`（均 YYYY-MM-DD ✓）

    ★【2026-09-28 抽公共 ✓】原只写在 `fetch_reduce_plans` 里 ✗ —— 而**批次级预判**
      （`refresh_reduce_plan_cache` ✓）也要同一区间 ✓ ⇒ 抽出来共用 ✓，
      免得两处各算一份、日久漂移 ✗✓。
    """
    start_date = _get_start_date(score_date, days)
    return (f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}",
            f"{score_date[:4]}-{score_date[4:6]}-{score_date[6:]}")


def _local_announcement_span() -> Optional[Tuple[str, str, int]]:
    """本地公告表 `stock_announcement` 的 `(最早日, 最晚日, 行数)` ✓（不可用 ⇒ None ✗）

    ⚠️ 这是"本地能否**替代在线**"的**唯一判据** ✓ —— `_query_local_announcements` ✓
      与批次级预判 ✓ **共用同一实现** ✗✓，杜绝"一处说覆盖、一处说不覆盖"✗。
    ⚠️ 表名是 `stock_announcement` ✓（**不是** `stock_event` ✗，详见下方注释 ✓）。
    """
    try:
        from utils.global_db import get_global_db
        conn = get_global_db().connect()
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                           "AND name='stock_announcement'").fetchone()
        if not row:
            return None
        rng = conn.execute('SELECT MIN(ann_date), MAX(ann_date), COUNT(*) '
                           'FROM stock_announcement').fetchone()
        if not rng or not rng[2]:
            return None
        return (str(rng[0]), str(rng[1]), int(rng[2]))
    except Exception as e:
        logger.warning('本地公告范围读取失败（视为**未覆盖** ✓，交由上层走在线 ✓）: %s', e)
        return None


def _local_announcement_covered(start_fmt: str, end_fmt: str) -> bool:
    """本地公告是否**完整覆盖** `[start_fmt, end_fmt]` ✓（判据同 `_query_local_announcements` ✓）"""
    span = _local_announcement_span()
    return bool(span) and span[0] <= start_fmt and span[1] >= end_fmt


def _query_local_announcements(stock_code: str, start_fmt: str, end_fmt: str) -> Optional[List[dict]]:
    """【2026-09-25 新增】从**本地表** `stock_announcement` 读取公告（离线 ✓，回测不联网 ✗）

    ⚠️ 表名注意 ✓：公告表是 `stock_announcement` ✓ —— **不是** `stock_event` ✗
    （后者是 `data/DataSql.sql` 的应用事件表 ✓，字段为 `event_type/event_date/...` ✗；
      2026-09-25 曾因同名撞车导致 web_server 启动崩溃 ✗✓）

    关键：返回与巨潮**完全同构**的原始结构 ✓（`announcementTitle` / `announcementTime`(ms UTC)
    / `secCode`）—— 这样下游（`<em>` 清洗、毫秒解析、关键词过滤）**一行都不用改** ✓。

    覆盖校验（防"假阴性" ✗）：
      · 本地表为空 / 不存在 → 返回 None（交由上层走在线 ✓）
      · 本地表的公告日期范围**未覆盖**请求区间 → 返回 None ✗
        （否则"本地没采到"会被误当成"没有公告"✗ —— 这正是最危险的静默偏差 ✗）
      · 覆盖良好 → 返回该股票在区间内的公告（可能为空列表 [] ✓）
        —— 空列表是**可信**的"确实没有公告" ✓（与"查不到"严格区分 ✓）

    Args:
        stock_code: 6 位代码
        start_fmt / end_fmt: YYYY-MM-DD

    Returns:
        List[dict] | None（None = 本地不可用，需在线 ✓）
    """
    try:
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        from utils.global_db import get_global_db

        # ★【2026-09-28】覆盖判据**提公共实现** ✓（`_local_announcement_span` ✓）
        #   ⇒ 与批次级预判（`refresh_reduce_plan_cache` ✓）**同一判据** ✗✓（防漂移 ✓）。
        span = _local_announcement_span()
        if not span:
            return None
        if span[0] > start_fmt or span[1] < end_fmt:
            logger.info("本地公告未覆盖请求区间（%s ~ %s，本地 %s ~ %s）→ 回退在线 ✓",
                        start_fmt, end_fmt, span[0], span[1])
            return None
        conn = get_global_db().connect()

        code6 = str(stock_code).split('.')[0][:6]
        rows = conn.execute(
            'SELECT ann_date, title FROM stock_announcement WHERE stock_code=? '
            'AND ann_date BETWEEN ? AND ? ORDER BY ann_date',
            (code6, start_fmt, end_fmt)).fetchall()
        items = []
        for ann_date, title in rows:
            # 还原为巨潮毫秒时间戳（UTC ✓）：保证下游 +8h 反解后回到同一日期 ✓
            try:
                ms = int(_dt.strptime(str(ann_date), '%Y-%m-%d')
                         .replace(hour=4, tzinfo=_tz.utc).timestamp() * 1000)
            except Exception:
                ms = None
            items.append({'announcementTitle': title, 'announcementTime': ms,
                          'secCode': code6})
        return items
    except Exception as e:
        logger.warning('本地公告读取失败（将回退在线）: %s', e)
        return None


def _query_cninfo_announcements(stock_code: str, start_fmt: str, end_fmt: str) -> Optional[List[dict]]:
    """
    直连巨潮公告查询接口，返回原始公告列表；失败/限流返回 None。

    直接 requests POST（设超时）并做字段容错，规避 akshare 硬编码列解析 bug 与无超时挂起。

    参数:
        stock_code: 股票代码
        start_fmt/end_fmt: 起止日期 YYYY-MM-DD
    返回:
        Optional[List[dict]]: 原始公告列表（含 announcementTitle/announcementTime）；失败返回 None
    """
    # 【2026-09-25 新增】**本地优先** ✓：本地 `stock_announcement` 覆盖良好即直接返回 ✓
    #   （回测期间为离线模式 ✓ → 走到下面的在线分支会被 online_guard 直接拦下 ✗）
    local_items = _query_local_announcements(stock_code, start_fmt, end_fmt)
    if local_items is not None:
        logger.debug("本地公告命中: %s %s~%s（%d 条）", stock_code, start_fmt, end_fmt,
                     len(local_items))
        return local_items

    # 取 orgId 拼装 stock 入参（缺失则仅用代码）
    org_id = _get_org_id(stock_code)
    stock = f"{stock_code},{org_id}" if org_id else stock_code
    # 与 akshare 一致的分页查询参数（form 表单）
    payload = {
        "pageNum": "1",
        "pageSize": "30",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": stock,
        "searchkey": "",  # 不限定关键词，拉全量后本地过滤，避免遗漏
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": f"{start_fmt}~{end_fmt}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    # 【2026-09-25 新增】在线检查点 ✓：回测（离线模式）走到这里会**直接抛错** ✗
    from utils.online_guard import PURPOSE_SCORE, guard_online_call
    # 【2026-09-25 契约 ✓】**评分/回测只读本地** ✗（在线回退 ⇒ 任何模式下都必须失败 ✗✓）
    guard_online_call(f'巨潮公告查询 {stock_code} {start_fmt}~{end_fmt}（评分回退）',
                      purpose=PURPOSE_SCORE)

    try:
        # 设超时根治挂起；form 表单提交
        resp = requests.post(CNINFO_QUERY_URL, headers=CNINFO_HEADERS, data=payload, timeout=CNINFO_TIMEOUT)
        # 限流/拦截精确识别，返回 None 由上层跳过写入（沿用旧缓存）
        if resp.status_code in (403, 429) or resp.status_code >= 500:
            logger.warning("巨潮接口限流/异常 HTTP %s: %s", resp.status_code, stock_code)
            return None
        resp.raise_for_status()
        text_json = resp.json()
    except Exception as e:
        logger.warning("巨潮公告查询异常(上层将重试): %s, %s", stock_code, e)
        return None
    # 字段容错：announcements 缺失/非列表 → 视为限流错误页，返回 None（不污染缓存）
    announcements = text_json.get("announcements")
    if not isinstance(announcements, list):
        logger.warning("巨潮返回结构异常(疑似限流/改版): %s, keys=%s", stock_code, list(text_json.keys()))
        return None
    return announcements


def fetch_reduce_plans(stock_code: str, score_date: str) -> Optional[List[dict]]:
    """
    直连巨潮拉取减持计划公告（含重试退避、<em> 清洗、毫秒时间戳解析、字段容错）。

    彻底绕过 akshare，规避其硬编码列解析 bug 与无超时挂起。

    参数:
        stock_code: 股票代码
        score_date: 评分日期 YYYYMMDD
    返回:
        有效期内减持计划列表 [{title, ann_date}]；限流耗尽/异常返回 None（上层据此不写缓存）
    """
    start_date = _get_start_date(score_date, REDUCE_PLAN_VALIDITY)
    start_fmt, end_fmt = _validity_range(score_date)
    # ★★【2026-09-28 修 ✓】**必失败 ⇒ 不重试** ✗→✓ ★★
    #   实测 ✗✓（用户日志 ✓）：本地公告只到 09-24 ✗ ⇒ 每次回退在线 ✗ ⇒
    #     `guard_online_call(purpose=PURPOSE_SCORE)` **必然抛错** ✗
    #     ⇒ 却仍被当成"限流"**重试 3 次 + 睡 5/10/15 秒** ✗ = **~32 秒/只** ✗
    #     （候选池几十只 ⇒ 数据更新被拖成分钟级 ✗，且**滴水不进**✗）。
    #   ⇒ 判据："本地未覆盖" ∧ "闸门会拦"（`online_blocked` ✓，与 `guard_online_call`
    #     **同一判据** ✓）⇒ **立即返回 None** ✗✓：语义与"重试耗尽"**完全一致** ✓
    #     （上层不写缓存、保留旧值 ✓），但**不再空耗** ✓。
    #   ⚠️ 若显式设了 `KHUNTER_SCORE_LOCAL_ONLY=0` ✗ 或不在评分侧 ✓
    #     ⇒ `online_blocked` 返回 None ⇒ **照旧走在线 + 重试** ✓（行为不变 ✓）。
    if not _local_announcement_covered(start_fmt, end_fmt):
        from utils.online_guard import PURPOSE_SCORE, online_blocked
        _blocked = online_blocked(PURPOSE_SCORE)
        if _blocked:
            logger.debug('减持计划**跳过在线回退** ✓（本地公告未覆盖 %s~%s 且「%s」✗）: %s',
                         start_fmt, end_fmt, _blocked, stock_code)
            return None
    raw_announcements = None
    last_err = None
    # 巨潮偶发限流，重试 3 次并退避缓解
    for attempt in range(3):
        try:
            announcements = _query_cninfo_announcements(stock_code, start_fmt, end_fmt)
            if announcements is not None:
                raw_announcements = announcements
                break
            last_err = "巨潮返回限流/结构异常"
        except Exception as e:
            last_err = e
            logger.warning("巨潮减持计划查询重试 %d/3: %s, %s", attempt + 1, stock_code, e)
        time.sleep(5 + attempt * 5)
    # 重试耗尽（限流/异常）返回 None 标记：上层据此不写缓存，避免假阴性污染
    if raw_announcements is None:
        logger.error("减持计划查询失败(重试耗尽/限流): %s, %s", stock_code, last_err)
        return None
    # 遍历原始公告，解析标题与时间，本地过滤减持计划
    plans = []
    for item in raw_announcements:
        # 字段容错取标题，清洗巨潮 <em> 高亮标签
        title = re.sub(r"<[^>]+>", "", str(item.get("announcementTitle", "")))
        if not is_reduce_plan_title(title):
            continue
        # announcementTime 为毫秒时间戳（UTC 计），+8h 转北京时间后取日期
        ann_ts = item.get("announcementTime")
        ann_date = ""
        if ann_ts:
            try:
                ann_dt = datetime.fromtimestamp(int(ann_ts) / 1000, tz=timezone.utc) + timedelta(hours=8)
                ann_date = ann_dt.strftime("%Y%m%d")
            except Exception:
                ann_date = ""
        # 公告日期需在有效期内（>= 起始日期）
        if ann_date and ann_date >= start_date:
            plans.append({"title": title, "ann_date": ann_date})
    return plans


def refresh_reduce_plan_cache(stock_codes: List[str], score_date: str,
                              sleep_range=(2, 3),
                              cache_file: str = REDUCE_PLAN_CACHE_FILE) -> Dict[str, int]:
    """
    串行批量刷新候选池减持计划缓存（离线调用，集成于数据更新阶段）。

    每只股票随机退避 2~3s 缓解巨潮限流；单只失败保留旧值不中断整体。

    ★【2026-09-28 修 ✓】**两种"整批预判"** ✗→✓（实测：此前第8步纯空耗 ~32s/只 ✗）：
      · 本地公告**未覆盖**请求区间 ✗ ∧ 闸门**必拦**在线 ✗ ⇒ **整体跳过** ✓
        （记 `skipped` ✓，不再逐只重试 ✗；详见函数内注释 ✓）
      · 本地公告**覆盖良好** ✓ ⇒ **免退避** ✓（全走本地 ✓，没有限流可言 ✓）

    参数:
        stock_codes: 候选池股票代码列表
        score_date: 评分/更新日期 YYYYMMDD
        sleep_range: 退避区间（秒），默认 (2,3)
        cache_file: 缓存文件路径
    返回:
        统计字典 {refreshed, failed, skipped}
    """
    stats = {"refreshed": 0, "failed": 0, "skipped": 0}
    total = len(stock_codes)
    if not total:
        return stats
    # ★★【2026-09-28 修 ✓】**批次级预判** ✗→✓ ★★
    #   动机 ✗✓（用户实测日志 ✓）：本地公告只到 09-24 ✗，而请求区间到 09-28 ✗ ⇒
    #     **每一只**都会"回退在线 ✗ → 被评分闸门必拦 ✗ → 重试 3 次 + 睡 5/10/15 秒"✗
    #     ≈ **32 秒/只** ✗（另加每只 2~3 秒退避 ✗）⇒ 第8步纯空耗、整轮更新被拖垮 ✗。
    #   判据 ✓：**本地未覆盖** ∧ **闸门会拦**（`online_blocked` ✓ = 与 `guard_online_call`
    #     同一判据 ✓）⇒ **整体跳过** ✓（`skipped = total` ✓，保留旧值 ✓，一条汇总日志 ✓）。
    #   ⚠️ 与"逐只失败"的**语义差别** ✗✓：以前会把 N 只都记成 `failed` ✗（其实一次也没真发出去 ✗
    #     ⇒ 用户误以为"巨潮限流"✗）。现记 `skipped` ✓ ⇒ 日志能分清"没联网"✓ 与"联网失败"✗。
    #   ⚠️ 本地**覆盖良好**时 ⇒ 逐只全走本地 ✓ ⇒ 顺带把退避 sleep **清零** ✓
    #     （否则 N 只空睡 N×2~3 秒 ✗）。
    start_fmt, end_fmt = _validity_range(score_date)
    if _local_announcement_covered(start_fmt, end_fmt):
        logger.debug('减持计划：本地公告已覆盖 %s~%s ✓ ⇒ 纯本地刷新、免退避 ✓',
                     start_fmt, end_fmt)
        sleep_range = (0.0, 0.0)
    else:
        from utils.online_guard import PURPOSE_SCORE, online_blocked
        _blocked = online_blocked(PURPOSE_SCORE)
        if _blocked:
            stats["skipped"] = total
            logger.warning('减持计划缓存刷新**整体跳过** ✓（%d 只，保留旧值 ✓）：'
                           '本地公告未覆盖 %s~%s 且「%s」✗ ⇒ 在线回退**必被拦** ✗，'
                           '重试纯属空耗 ✗。请先让数据更新补齐**公告（事件域）** ✓，'
                           '再刷新本缓存 ✓', total, start_fmt, end_fmt, _blocked)
            return stats
    for idx, code in enumerate(stock_codes, 1):
        try:
            # 随机退避缓解巨潮限流（首只也稍作停顿，避免瞬时并发）
            time.sleep(random.uniform(*sleep_range))
            plans = fetch_reduce_plans(code, score_date)
            # 实时拉取失败（限流/异常）返回 None：跳过写入，保留旧缓存，避免假阴性污染
            if plans is None:
                stats["failed"] += 1
                logger.warning("减持计划拉取失败(限流/异常)，跳过写入缓存(保留旧值): %s", code)
                continue
            # 写入缓存（即便为空也刷新 updated_date，避免每日重复实时请求）
            upsert_plan(code, plans, score_date, cache_file)
            stats["refreshed"] += 1
            logger.info("减持计划缓存刷新 %d/%d: %s, %d 条", idx, total, code, len(plans))
        except Exception as e:
            # 单只异常：保留旧值不中断，计入失败，继续下一只
            stats["failed"] += 1
            logger.warning("减持计划缓存刷新失败(保留旧值): %s, %s", code, e)
    return stats
