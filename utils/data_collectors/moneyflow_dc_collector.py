# -*- coding: utf-8 -*-
"""个股资金流向采集器：`moneyflow_dc`（东财）—— **2026-09-26 起降为备用源 ✗**

⚠️ **重要变更** ✓（2026-09-26 用户决策·方案 C ✓）：
  · 本采集器的数据**不再作为评分主源** ✗ —— 主源已改回**同花顺 `moneyflow_ths`** ✓
    （见 `moneyflow_ths_collector.py` ✓）。
  · 原因 ✗✓（实证）：东财与同花顺**字段同名但语义不同** ✗ ——
    同花顺「主力」= 源端 `net_d5_amount`（5 日主力净额 ✓）；东财「主力」= 超大单+大单 ✗。
    600 条同股同日对照：**99.8% 数值不同 / 1/3 符号相反** ✗；
    出货否决率 5.2% → **19.3%** ✗（把市场常态当出货 ✗）⇒ 回测表现显著变差 ✗。
  · 数据**已于 2026-09-26 彻底移除** ✗✓（4,276,029 行已删除 ✓）——
    本模块**仅保留"重采能力"** ✓（用户要求彻底去除东财数据 ✓）。
    如需重采：`collect_moneyflow_dc(conn, [起点, 终点], mode='initial')` ✓
    ⚠️ 重采得到的是**当时的源端版本** ✗（源会修订历史值 ✗），不保证与删除前逐位一致 ✓。

保留价值 ✓：东财覆盖更长（`2023-09-11` 起 ✓），可作**对照源/备用源** ✓。

原始定稿要点（2026-09-25）：
  · 起点 `2023-09-11` ✓
  · **日粒度落库** ✓；5 日等聚合**一律本地计算** ✓（不依赖源端 `net_d5_amount` ✗）
  · 字段与 `moneyflow_ths` **同构** ✓ ⇒ 既有评分/否决口径改动最小 ✓
  · **滚动重采最近 3 个交易日** ✓（每日数据更新时）
  · 请求区间早于源起点 → **直接报错** ✗（不静默截断 ✓）

表：`stock_moneyflow_daily`
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from utils.data_collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)

SOURCE_NAME = 'moneyflow_dc'
#: 数据源可用起点（Tushare `moneyflow_dc` 自 2023-09-11 起提供 ✓）
SOURCE_START = '2023-09-11'

#: 落库的业务字段（与源端一致；`net_d5_amount` 仅存证、不参与计算 ✓）
FLOW_FIELDS = (
    'net_amount', 'net_amount_rate',
    'buy_elg_amount', 'buy_elg_amount_rate',
    'buy_lg_amount', 'buy_lg_amount_rate',
    'buy_md_amount', 'buy_md_amount_rate',
    'buy_sm_amount', 'buy_sm_amount_rate',
    'net_d5_amount',
)


def normalize_trade_date(value) -> str:
    """把 `YYYYMMDD` / `YYYY-MM-DD` / Timestamp 统一为 `YYYY-MM-DD` ✓"""
    s = str(value).strip()
    if len(s) >= 10 and s[4] == '-':
        return s[:10]
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    return s[:10]


def _iter_records(raw) -> List[Dict]:
    """把 DataFrame / rows 统一成 dict 列表 ✓"""
    if raw is None:
        return []
    if hasattr(raw, 'to_dict'):          # pandas.DataFrame
        try:
            return raw.to_dict('records')
        except Exception:
            return []
    if isinstance(raw, dict):
        return [raw]
    return [dict(r) for r in raw]


class _TushareDCFetcher:
    """默认取数实现（懒加载 tushare ✓，便于测试注入 fake ✓）"""

    def __init__(self, token: Optional[str] = None):
        self._token = token
        self._pro = None

    def _pro_api(self):
        if self._pro is None:
            import json
            import tushare as ts
            token = self._token
            if not token:
                try:
                    with open('config/tushare_config.json', 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    token = cfg.get('api_key') or cfg.get('token')
                except Exception:
                    token = None
            if token:
                ts.set_token(token)
            self._pro = ts.pro_api()
        return self._pro

    def moneyflow_dc(self, trade_date: str = None, ts_code: str = None,
                     start_date: str = None, end_date: str = None):
        """调用 Tushare `moneyflow_dc`（东财个股资金流，每日盘后更新 ✓）"""
        kwargs = {}
        if trade_date:
            kwargs['trade_date'] = trade_date
        if ts_code:
            kwargs['ts_code'] = ts_code
        if start_date:
            kwargs['start_date'] = start_date
        if end_date:
            kwargs['end_date'] = end_date
        return self._pro_api().moneyflow_dc(**kwargs)


class MoneyflowDCCollector(BaseCollector):
    """东财个股资金流向采集器（日粒度）"""

    name = SOURCE_NAME
    table = 'stock_moneyflow_daily'
    pk_cols = ('stock_code', 'trade_date', 'source')
    columns = ('stock_code', 'trade_date', 'source') + FLOW_FIELDS + ('created_date', 'updated_date')
    source_start_date = SOURCE_START
    date_col = 'trade_date'
    #: 更新时**保留**首次入库时间 ✓（对齐 K 线 `created_date` 语义 ✓）
    preserve_on_update = ('created_date',)

    def __init__(self, conn, fetcher=None, **kwargs):
        super().__init__(conn, fetcher=fetcher or _TushareDCFetcher(), **kwargs)

    # ------------------------------------------------------------------ 采集

    def fetch_date(self, date_str: str):
        """抓取**单日全市场**资金流（一次调用返回全市场 ✓）"""
        return self.fetcher.moneyflow_dc(trade_date=date_str.replace('-', ''))

    def fetch_stock_range(self, stock_code: str, start: str, end: str):
        """抓取单只股票区间数据（用于定向补采/单股修复 ✓）"""
        ts_code = stock_code if '.' in stock_code else (
            f'{stock_code}.SH' if stock_code.startswith(('6', '9')) else f'{stock_code}.SZ')
        return self.fetcher.moneyflow_dc(ts_code=ts_code,
                                         start_date=start.replace('-', ''),
                                         end_date=end.replace('-', ''))

    def normalize(self, raw) -> List[Dict]:
        """规范化为库存行（含 `created_date/updated_date` 与来源标记 ✓）"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        rows: List[Dict] = []
        for rec in _iter_records(raw):
            ts_code = str(rec.get('ts_code') or '').strip()
            if not ts_code:
                continue
            row = {
                'stock_code': ts_code.split('.')[0][:6],
                'trade_date': normalize_trade_date(rec.get('trade_date')),
                'source': SOURCE_NAME,
                'created_date': now,
                'updated_date': now,
            }
            for field in FLOW_FIELDS:
                row[field] = rec.get(field)
            rows.append(row)
        return rows


def recent_trade_dates(all_trade_dates: Sequence[str], end_date: str, window: int = 5) -> List[str]:
    """取"截至 end_date 的最近 window 个**日历交易日**" ✓

    为什么要按**日历**取窗口（而不是按"库里已存在的最近 N 日"✗）：
      若某个交易日在库里**缺数据** ✗，按"已存在"取数会**默默用更早的日期顶上** ✗
      ⇒ 窗口看似凑满、实则少算一天 ✗（静默偏差）。
      按日历取窗口 ⇒ 缺失日期直接体现为"取不满" ✓，由 `compute_metrics` 标记
      `complete=False` ✓，回测（严格模式）据此报错 ✗。
    """
    dates = sorted({str(d) for d in all_trade_dates if str(d) <= end_date})
    return dates[-max(1, int(window)):]


def load_window_rows(conn, stock_code: str, window_dates: Sequence[str],
                     source: str = None) -> List[Dict]:
    """从本地表读取**指定交易日窗口**的资金流（回测/实盘只读本地 ✓）

    Args:
        conn: sqlite3 连接
        stock_code: 6 位代码（源端 ts_code 前 6 位 ✓）
        window_dates: **日历给出的窗口交易日列表**（升序，建议用 `recent_trade_dates` 生成 ✓）
        source: 数据源 ✓；**默认 = 当前配置数据源** ✓（2026-09-26 修正 ✗→✓）

    ⚠️ 修正说明 ✗✓：此前默认值是本模块的 `SOURCE_NAME`（**恒为东财** ✗）——
    东财数据已清除 ✗ ⇒ 任何**未显式传 source** 的调用都会**静默返回空** ✗✓
    （"空"被误当作"确实没有"，是最危险的静默偏差 ✗）。现跟随配置 ✓。

    Returns:
        按 `trade_date` 升序的 dict 列表；**缺失日期不会返回行** ✓
        （调用方用 `compute_metrics(rows, window=len(window_dates))` 判断 completeness ✓）
    """
    dates = sorted({str(d) for d in window_dates})
    if not dates:
        return []
    if not source:
        from utils.moneyflow_source import resolve
        source = resolve()
    cols = list(FLOW_FIELDS) + ['trade_date', 'stock_code', 'source']
    placeholders = ', '.join('?' for _ in dates)
    cur = conn.execute(
        f'SELECT {", ".join(cols)} FROM {MoneyflowDCCollector.table} '
        f'WHERE stock_code=? AND source=? AND trade_date IN ({placeholders}) '
        f'ORDER BY trade_date',
        tuple([stock_code, source] + dates))
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def collect_moneyflow_dc(conn, trade_dates: Sequence[str], mode: str = 'incremental',
                         window: int = 3, fetcher=None, batch_sleep: float = 0.0,
                         state_dir: Optional[str] = None) -> Dict[str, int]:
    """便捷入口：增量（滚动 window 日）/ 初始化（全量回填）✓

    Args:
        conn: sqlite3 连接
        trade_dates: 交易日列表（升序；初始化时传全区间，增量时传全量列表亦可 ✓）
        mode: 'incremental'（滚动 window 日 ✓）| 'initial'（全量回填到列表中的日期 ✓）
        window: 增量滚动窗口（默认 3 ✓）
        state_dir: 进度文件目录（默认 data/logs/collector_state ✓；测试请注入临时目录 ✓）
    """
    collector = MoneyflowDCCollector(conn, fetcher=fetcher, state_dir=state_dir)
    collector.ensure_schema()
    if mode == 'incremental':
        return collector.run_daily_update(trade_dates, window=window)
    dates = sorted({str(d) for d in trade_dates})
    if not dates:
        raise ValueError('交易日列表为空')
    return collector.run_initial(dates[0], dates[-1], dates)
