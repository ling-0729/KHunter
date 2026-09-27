# -*- coding: utf-8 -*-
"""个股资金流向：**本地聚合口径**（唯一权威实现）

设计定稿（2026-09-25）：
  1. 回测/实盘**只依赖日粒度数据**；5 日等聚合**一律本地计算** ✓
  2. 源端聚合字段（如 `net_d5_amount`）仅作**存证/双轨校验**，**不参与计算** ✓
     —— 该字段自 2027-07-06 起停供（Tushare 通知），本模块因此不受影响 ✓
  3. **聚合完整性**：窗口内交易日必须齐全；不全时 `complete=False` 并给出缺失数，
     调用方（回测）在严格模式下**必须报错**，禁止"少算一天"✗

字段语义（`moneyflow_dc` 与 `moneyflow_ths` 同构）：
  net_amount               主力净额（万元）  == buy_elg_amount + buy_lg_amount
  net_amount_rate          主力净额占比（%）
  buy_elg/lg/md/sm_amount  各档**净额**（万元，负 = 净流出）
  buy_*_amount_rate        各档净额占比（%）

口径对齐：与 `trading/moneyflow_scorer._extract_from_tushare` 的
  "无 `net_d5_amount` 时回退为 `Σ(net_amount)`“分支**同口径** ✓
"""

from typing import Dict, Iterable, List, Optional

WINDOW = 5  # 默认聚合窗口（交易日）

# 参与聚合的净额维度（源字段 → 指标键）
_DIMENSIONS = (
    ('net_amount', 'net_flow_5d'),   # 主力净额累计 ✓（键名与既有实现一致，便于无缝替换）
    ('buy_lg_amount', 'large_net'),  # 大单
    ('buy_sm_amount', 'small_net'),  # 小单
)

# 参与均值计算的占比字段
_RATE_FIELDS = (
    ('buy_lg_amount_rate', 'lg_rate_avg'),
    ('buy_sm_amount_rate', 'sm_rate_avg'),
    ('net_amount_rate', 'main_net_rate_avg'),
)


def _f(value) -> float:
    """安全转 float（None/空/非法 → 0.0）"""
    if value is None or value == '':
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_metrics(rows: Optional[Iterable[Dict]], window: int = WINDOW) -> Dict:
    """按**本地口径**计算窗口内资金流指标

    Args:
        rows: 日粒度记录（dict 列表，字段语义见模块 docstring），顺序不限
        window: 聚合窗口（交易日数，默认 5）

    Returns:
        dict:
          net_flow_5d        主力净额累计（万元）= Σ net_amount ✓
          large_net          大单净额累计（万元）✓
          small_net          小单净额累计（万元）✓
          amount_5d          窗口成交额（源端不提供 → 恒 0.0 ✓）
          daily_ratios       逐日大单净额占比列表（%）✓
          lg_rate_avg        大单净额占比均值（%）✓
          sm_rate_avg        小单净额占比均值（%）✓
          main_net_rate_avg  主力净额占比均值（%）✓
          days               实际参与聚合的交易日数
          complete           是否满足 window 个交易日（False ⇒ **不可用于判定** ✗）
          missing            距完整窗口还缺几个交易日
    """
    metrics = {
        'net_flow_5d': 0.0,
        'large_net': 0.0,
        'small_net': 0.0,
        'amount_5d': 0.0,
        'daily_ratios': [],
        'lg_rate_avg': 0.0,
        'sm_rate_avg': 0.0,
        'main_net_rate_avg': 0.0,
        'days': 0,
        'complete': False,
        'missing': window,
    }
    if not rows:
        return metrics

    ordered = sorted(rows, key=lambda r: str(r.get('trade_date', '')))
    used = ordered[-window:] if window > 0 else ordered

    for field, key in _DIMENSIONS:
        metrics[key] = float(sum(_f(r.get(field)) for r in used))

    # 逐日大单净额占比（与既有实现同口径：直接用源端 rate 字段 ✓）
    metrics['daily_ratios'] = [round(_f(r.get('buy_lg_amount_rate')), 6) for r in used]

    n = len(used)
    for field, key in _RATE_FIELDS:
        metrics[key] = float(sum(_f(r.get(field)) for r in used) / n) if n else 0.0

    metrics['days'] = n
    metrics['complete'] = n >= window
    metrics['missing'] = max(0, window - n)
    return metrics
