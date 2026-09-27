# -*- coding: utf-8 -*-
"""个股资金流向采集器：**同花顺口径 `moneyflow_ths`（保真源 ✓）**

定稿背景（2026-09-26 用户决策 ✓：**方案 C 保真** ✓）：
  · 之前回测用**同花顺**（`moneyflow_ths` ✓ 在线 ✗），评分阈值/权重全在该口径上标定 ✓
  · M1 本地化时误换成**东财**（`moneyflow_dc` ✗）—— 二者**字段同名但语义不同** ✗✓：
      - 同花顺「主力」= 源端 `net_d5_amount`（5 日主力净额 ✓，**无特大单字段** ✓）
      - 东财「主力」= 超大单 + 大单 ✗，且 `buy_lg_amount_rate` 只含**大单** ✗
      ⇒ 实测：600 条同股同日对照，东财口径 **99.8% 数值不同 / 1/3 符号相反** ✗，
        出货否决率 5.2% → **19.3%** ✗（把市场常态误判为出货 ✗）
  · 用户决策 ✓：**回到同花顺口径**，**有多少历史就用多少**；
    更早区间**暂不支持回测** ✗（由 `source_start_date` **硬拒绝** ✓，不静默截断 ✗）

实测覆盖（2026-09-26 直连源探测 ✓）：
  · 同花顺 `moneyflow_ths` 最早可用日 = **2024-12-24** ✓（000001.SZ / 600519.SH 一致 ✓）
  · 字段：`net_amount` ✓、**`net_d5_amount`** ✓、`buy_lg/md/sm_amount(_rate)` ✓
          **无** `buy_elg_*` ✗、**无** `net_amount_rate` ✗（落库为 NULL ✓）
  · 日粒度落库 ✓；单日调用返回**全市场** ✓（≈5,200 只/日 ✓）

表：`stock_moneyflow_daily`（与东财**同表** ✓，由 `source` 列隔离 ✓）
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from utils.data_collectors.base_collector import BaseCollector
from utils.data_collectors.moneyflow_dc_collector import (
    FLOW_FIELDS, _iter_records, normalize_trade_date)

logger = logging.getLogger(__name__)

SOURCE_NAME = 'moneyflow_ths'

#: 同花顺可用起点 ✓（**实测** 2026-09-26：`moneyflow_ths` 最早 2024-12-24 ✓）
#:   ⇒ 回测支持区间 = [SOURCE_START, 今天] ✓；更早区间**明确拒绝** ✗（见 `assert_supported_range` ✓）
SOURCE_START = '2024-12-24'


class _TushareThsFetcher:
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

    def moneyflow_ths(self, trade_date: str = None, ts_code: str = None,
                      start_date: str = None, end_date: str = None):
        """调用 Tushare `moneyflow_ths`（同花顺个股资金流 ✓）"""
        kwargs = {}
        if trade_date:
            kwargs['trade_date'] = trade_date
        if ts_code:
            kwargs['ts_code'] = ts_code
        if start_date:
            kwargs['start_date'] = start_date
        if end_date:
            kwargs['end_date'] = end_date
        return self._pro_api().moneyflow_ths(**kwargs)


class MoneyflowThsCollector(BaseCollector):
    """同花顺个股资金流向采集器（日粒度；**保真源** ✓）"""

    name = SOURCE_NAME
    table = 'stock_moneyflow_daily'
    pk_cols = ('stock_code', 'trade_date', 'source')
    columns = ('stock_code', 'trade_date', 'source') + FLOW_FIELDS + ('created_date', 'updated_date')
    source_start_date = SOURCE_START
    date_col = 'trade_date'
    #: 更新时**保留**首次入库时间 ✓（对齐 K 线 `created_date` 语义 ✓）
    preserve_on_update = ('created_date',)

    def __init__(self, conn, fetcher=None, **kwargs):
        super().__init__(conn, fetcher=fetcher or _TushareThsFetcher(), **kwargs)

    # ------------------------------------------------------------------ 采集

    def fetch_date(self, date_str: str):
        """抓取**单日全市场**资金流（一次调用返回全市场 ✓）"""
        return self.fetcher.moneyflow_ths(trade_date=date_str.replace('-', ''))

    def fetch_stock_range(self, stock_code: str, start: str, end: str):
        """抓取单只股票区间数据（用于定向补采/单股修复 ✓）"""
        ts_code = stock_code if '.' in stock_code else (
            f'{stock_code}.SH' if stock_code.startswith(('6', '9')) else f'{stock_code}.SZ')
        return self.fetcher.moneyflow_ths(ts_code=ts_code,
                                          start_date=start.replace('-', ''),
                                          end_date=end.replace('-', ''))

    def normalize(self, raw) -> List[Dict]:
        """规范化为库存行 ✓

        同花顺**没有** `buy_elg_*` / `net_amount_rate` ✗ → 这些列写 NULL ✓
        （**不臆造** ✓：宁可缺，也不填假值 ✗）；`net_d5_amount` **保留** ✓ ——
        它是旧评分路径的核心字段 ✓（保真 ✓）。
        """
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
                row[field] = rec.get(field)          # 源端没有的字段 → None ✓（不臆造 ✗）
            rows.append(row)
        return rows


def collect_moneyflow_ths(conn, trade_dates: Sequence[str], mode: str = 'incremental',
                          window: int = 3, fetcher=None, batch_sleep: float = 0.0,
                          state_dir: Optional[str] = None) -> Dict[str, int]:
    """便捷入口：增量（滚动 window 日）/ 初始化（全量回填）✓

    Args:
        conn: sqlite3 连接
        trade_dates: 交易日列表（升序 ✓）
        mode: 'incremental'（滚动 window 日 ✓）| 'initial'（全量回填 ✓）
        window: 增量滚动窗口（默认 3 ✓）
        state_dir: 进度文件目录（默认 data/logs/collector_state ✓；测试请注入 ✓）
    """
    collector = MoneyflowThsCollector(conn, fetcher=fetcher, state_dir=state_dir)
    collector.ensure_schema()
    if mode == 'incremental':
        return collector.run_daily_update(trade_dates, window=window)
    dates = sorted({str(d) for d in trade_dates})
    if not dates:
        raise ValueError('交易日列表为空')
    collector.assert_supported_range(dates[0], dates[-1])
    return collector.run_initial(dates[0], dates[-1], dates)
