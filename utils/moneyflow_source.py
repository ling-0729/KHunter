# -*- coding: utf-8 -*-
"""资金流**数据源口径**与**支持区间**的单一事实源 ✓（2026-09-26 方案 C ✓）

为什么需要它 ✗✓（本轮实证）：
  · 东财（`moneyflow_dc`）与同花顺（`moneyflow_ths`）**字段同名但语义不同** ✗：
      同花顺「主力」= 源端 `net_d5_amount`（5 日主力净额 ✓，无特大单字段 ✓）
      东财「主力」  = 超大单 + 大单 ✗，`buy_lg_amount_rate` 只含大单 ✗
    ⇒ 600 条同股同日对照：**99.8% 数值不同、1/3 符号相反** ✗；
      出货否决率 5.2% → 19.3% ✗（把市场常态当出货 ✗）
  · 策略的**评分阈值/权重全部在同花顺口径上标定** ✓
    ⇒ 数据源必须与"标定时所用口径"一致 ✓，否则阈值含义漂移 ✗、股票池被系统性改写 ✗
  · 同花顺覆盖自 **2024-12-24** 起 ✓（实测 ✓）
    ⇒ 更早区间**暂不支持回测** ✗（由闸门**明确拒绝** ✓，绝不静默出结果 ✗）

对外接口：
    resolve()                   → 当前数据源 ✓（env > config > 默认同花顺 ✓）
    supported_start(source)     → 该源的理论可用起点 ✓
    support_window(conn, source)→ 本地实际覆盖 + **可评分起点** ✓（含 5 日窗口预热 ✓）
"""

import logging
from typing import Dict, Optional, Sequence

logger = logging.getLogger(__name__)

SOURCE_THS = 'moneyflow_ths'      #: 同花顺（**默认** ✓ = 保真口径 ✓）
SOURCE_DC = 'moneyflow_dc'        #: 东财（保留备用 ✓）
KNOWN_SOURCES = (SOURCE_THS, SOURCE_DC)

#: 理论可用起点 ✓（**实测** 2026-09-26 ✓）
SUPPORTED_START: Dict[str, Optional[str]] = {
    SOURCE_THS: '2024-12-24',     # 同花顺实测最早日 ✓（000001.SZ / 600519.SH 一致 ✓）
    SOURCE_DC: '2023-09-11',      # 东财 ✓（备用）
}

#: 评分窗口长度 ✓（`net_d5_amount` / 5 日窗口 ✓）—— 起点必须已攒够这个天数 ✓
WINDOW_DAYS = 5

TABLE = 'stock_moneyflow_daily'


def resolve() -> str:
    """解析当前资金流数据源 ✓（`KHUNTER_MONEYFLOW_SOURCE` > `config.yaml → moneyflow.source` > 同花顺 ✓）"""
    import os
    src = (os.environ.get('KHUNTER_MONEYFLOW_SOURCE') or '').strip()
    if not src:
        try:
            import yaml
            from pathlib import Path
            cfg = Path(__file__).resolve().parents[1] / 'config' / 'config.yaml'
            if cfg.exists():
                with open(cfg, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                src = str(((data.get('moneyflow') or {}).get('source')) or '').strip()
        except Exception as e:
            logger.warning(f'读取 moneyflow.source 失败（按默认同花顺处理）: {e}')
    src = src or SOURCE_THS
    if src not in KNOWN_SOURCES:
        logger.warning(f'未知的资金流数据源 {src!r} → 回落 `{SOURCE_THS}` ✓'
                       f'（已知：{", ".join(KNOWN_SOURCES)} ✓）')
        src = SOURCE_THS
    return src


def supported_start(source: Optional[str] = None) -> Optional[str]:
    """该源的**理论**可用起点 ✓（None = 未知/不限 ✓）"""
    return SUPPORTED_START.get(source or resolve())


def clip_dates_to_source(dates: Sequence[str],
                         source: Optional[str] = None):
    """把交易日列表**裁剪**到该源可用起点之后 ✓

    为什么必须裁剪 ✗✓（本轮实测漏洞 ✗）：初始化入口传的是"本地日历全量"
    （自 `2023-09-11` 起 ✓），而**同花顺起点是 `2024-12-24`** ✗ ⇒
    若不做裁剪，`assert_supported_range` 会直接抛错 ✗（整个初始化失败 ✗）；
    更糟的是——**改前它硬编码东财** ✗ ⇒ 一点"初始化资金流"就把已清除的东财数据
    重新拉回来 ✗✓。裁剪后：**只采该源支持的区间** ✓，并把裁掉的天数**如实上报** ✗。

    Returns:
        (kept, dropped, start)：kept 为升序可用日期 ✓；dropped 为被裁掉的天数 ✓
    """
    src = source or resolve()
    start = supported_start(src)
    ds = sorted({str(d) for d in (dates or [])})
    if not start:
        return ds, 0, None
    kept = [d for d in ds if d >= start]
    return kept, len(ds) - len(kept), start


def make_collector(conn, source: Optional[str] = None, **kwargs):
    """按**当前数据源**创建资金流采集器 ✓（**唯一工厂** ✓）

    为什么要有工厂 ✗✓：本轮实测——初始化入口**各自 new 采集器** ✗，
    结果"更新走同花顺 ✓、初始化走东财 ✗"⚠️（两处口径不一致 ✗，
    且会把已清除的东财数据拉回来 ✗✓）。
    现统一由本工厂产出 ✓，初始化/每日更新/脚本都走它 ✓ ⇒ **不可能再走岔** ✓。
    """
    src = source or resolve()
    if src == SOURCE_THS:
        from utils.data_collectors.moneyflow_ths_collector import MoneyflowThsCollector
        return MoneyflowThsCollector(conn, **kwargs)
    from utils.data_collectors.moneyflow_dc_collector import MoneyflowDCCollector
    return MoneyflowDCCollector(conn, **kwargs)


def support_window(conn, source: Optional[str] = None) -> Dict:
    """本地实际覆盖 + **可评分起点** ✓

    `ready_start` 的语义 ✓：**能产出完整 5 日窗口的最早评分日** ✓ ——
      窗口预热需要 `WINDOW_DAYS` 个交易日 ✓，故 `ready_start` = 该源本地覆盖的**第 5 个**交易日 ✓
      （回测起点早于它 ✗ ⇒ 首日窗口必然凑不满 ✗ ⇒ 必须**明确拒绝** ✓）

    Returns:
        {'source', 'supported_start', 'covered_start', 'covered_end', 'days',
         'ready_start', 'ready': bool}
    """
    src = source or resolve()
    out = {'source': src, 'supported_start': supported_start(src),
           'covered_start': None, 'covered_end': None, 'days': 0,
           'ready_start': None, 'ready': False}
    try:
        row = conn.execute(
            f'SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date) '
            f'FROM {TABLE} WHERE source=?', (src,)).fetchone()
    except Exception as e:
        logger.warning(f'读取 {src} 本地覆盖失败: {e}')
        return out
    if not row or not row[0]:
        return out
    out['covered_start'] = str(row[0])[:10]
    out['covered_end'] = str(row[1])[:10]
    out['days'] = int(row[2] or 0)
    try:
        r2 = conn.execute(
            f'SELECT trade_date FROM (SELECT DISTINCT trade_date FROM {TABLE} '
            f'WHERE source=? ORDER BY trade_date LIMIT ?) ORDER BY trade_date DESC LIMIT 1',
            (src, WINDOW_DAYS)).fetchone()
        if r2 and r2[0]:
            out['ready_start'] = str(r2[0])[:10]
    except Exception as e:
        logger.warning(f'计算 {src} 可评分起点失败: {e}')
    # 就绪判定 ✓：不仅要有 5 个交易日 ✓，还要求**覆盖日数 ≥ 窗口长度** ✓
    #   （否则 `ready_start` 会指向"第 3 个交易日"✗，回测起点通过闸门 ✗
    #    却在评分时因窗口凑不满而失败 ✗ —— 闸门必须**前置**暴露该问题 ✓）
    out['ready'] = bool(out['ready_start']) and out['days'] >= WINDOW_DAYS
    return out
