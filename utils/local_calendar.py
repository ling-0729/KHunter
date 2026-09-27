# -*- coding: utf-8 -*-
"""本地交易日历读取（**完全离线** ✓）

用途：回测/本地取数需要"最近 N 个交易日"窗口时，**不得**调用
`utils.trade_date_utils.get_trading_days`（它会先请求 Tushare ✗）。
本模块只读**本地**来源，优先级：
  1. 本地表 `trade_calendar`（M2 起落库 ✓）
  2. 本地缓存文件 `data/trading_calendar_cache.json`（已有 ✓，M0 已加固 ✓）
  3. 本地表 `stock_kline` 的 distinct 日期（兜底 ✓，纯本地 ✓）
读不到 → **报错** ✗（不联网、不静默 ✓）
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

_CACHE_FILE = Path('data') / 'trading_calendar_cache.json'


def _from_db(conn) -> List[str]:
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND "
                           "name='trade_calendar'").fetchone()
        if not row:
            return []
        return [str(r[0]) for r in conn.execute(
            'SELECT cal_date FROM trade_calendar WHERE is_open=1 ORDER BY cal_date')]
    except Exception:
        return []


def _from_cache_file(cache_file: Optional[Path] = None) -> List[str]:
    path = Path(cache_file or _CACHE_FILE)
    if not path.exists():
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return sorted({str(d) for d in (data.get('dates') or [])})
    except Exception as e:
        logger.warning(f'读取本地交易日历缓存失败: {e}')
        return []


def _from_kline(conn) -> List[str]:
    try:
        return [str(r[0]) for r in conn.execute(
            'SELECT DISTINCT date FROM stock_kline ORDER BY date')]
    except Exception:
        return []


def load_local_trade_dates(conn, cache_file: Optional[Path] = None,
                           prefer_db: bool = True) -> List[str]:
    """加载本地全部交易日（离线 ✓；来源：表 → 缓存文件 → K 线）

    Args:
        conn: sqlite3 连接
        cache_file: 自定义缓存文件（测试用 ✓）
        prefer_db: True = 优先读 `trade_calendar` 表 ✓（默认）；
                   **写入表时（CalendarCollector.sync_from_local_cache）必须传 False** ✗
                   —— 否则会"读自己刚写的表"，导致缓存里新增的日期**永远进不了表** ✗
    """
    loaders = ((lambda: _from_db(conn)), (lambda: _from_cache_file(cache_file)),
               (lambda: _from_kline(conn)))
    if not prefer_db:
        loaders = loaders[1:]                     # 跳过 DB，直接读缓存文件 → K 线 ✓
    for loader in loaders:
        dates = loader()
        if dates:
            return dates
    raise RuntimeError(
        '本地交易日历不可用 ✗（trade_calendar 表 / data/trading_calendar_cache.json / '
        'stock_kline 均无数据）—— 请先运行数据更新（回测不联网 ✗）')


def recent_trade_dates_local(conn, end_date: str, window: int = 5,
                             cache_file: Optional[Path] = None) -> List[str]:
    """取"截至 end_date 的最近 window 个交易日"（**纯本地** ✓）

    Raises:
        RuntimeError: 本地日历不足 window 天（**不静默截断** ✗）
    """
    dates = load_local_trade_dates(conn, cache_file)
    usable = [d for d in dates if d <= end_date]
    if len(usable) < window:
        raise RuntimeError(
            f'本地交易日历不足：请求最近 {window} 个交易日（截至 {end_date}），'
            f'本地仅 {len(usable)} 天 ✗ —— 请先补齐交易日历（每日数据更新 ✓）')
    return usable[-window:]
