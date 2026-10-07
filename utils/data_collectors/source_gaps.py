# -*- coding: utf-8 -*-
"""**上游源侧缺口**登记与分类（2026-09-25 新增）

背景（本轮实证 ✓）：`moneyflow_dc` 的 **2023-11-22** 在本地为 0 行 ✗，
直连源探测为 0 行 ✗（相邻日 5434/5434/5435 行 ✓）→ **上游无该日数据** ✗。

问题：这种缺口**补采永远补不上** ✗ —— 若与"我方漏采"混在同一个 `missing` 里 ✗：
  · 要么反复重试、每次巡检都报错 ✗（噪音 ✗）
  · 要么被"过滤掉"从而**掩盖真的漏采** ✗✗（危险 ✗）

因此独立成**显式登记表** ✓（`config/data_source_gaps.yaml` ✓）：
  · `verify_coverage` 把缺日切成 `missing`（需补 ✓）与 `known_gaps`（源侧 ✗）✓
  · `repair_coverage` 只补 `missing` ✓；`known_gaps` **照实上报** ✓（登记 ≠ 忽略 ✓）
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: 登记表路径（可用参数覆盖，便于测试 ✓）
GAPS_FILE = Path(__file__).resolve().parents[2] / 'config' / 'data_source_gaps.yaml'


@lru_cache(maxsize=4)
def _load_gaps_cached(path_str: str) -> Dict[str, Dict[str, Dict]]:
    """加载登记表（进程内缓存 ✓；文件缺失/损坏 → 空表 + 告警 ✗）"""
    try:
        import yaml
        p = Path(path_str)
        if not p.exists():
            return {}
        with open(p, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError('登记表结构非法（应为 dict）')
        out: Dict[str, Dict[str, Dict]] = {}
        for domain, items in data.items():
            if not isinstance(items, dict):
                continue
            out[str(domain)] = {str(k): (v or {}) for k, v in items.items()}
        return out
    except Exception as e:
        logger.warning(f'读取上游缺口登记表失败（按"无登记"处理）: {e}')
        return {}


def load_gaps(path: Optional[str] = None) -> Dict[str, Dict[str, Dict]]:
    """读取全部登记（domain → {date: 详情} ✓）"""
    return _load_gaps_cached(str(path or GAPS_FILE))


def known_gap_dates(domain: str, path: Optional[str] = None) -> set:
    """某采集器的**已登记源侧缺口日期**集合 ✓（**整日**口径 ✓）

    ⚠️【2026-09-28】只取 `YYYY-MM-DD` 形态的键 ✓ —— 登记表已扩展**个股级**区间
    （`stock_gap_ranges:` ✓，见 `is_stock_source_gap` ✓），若不过滤 ✗ ⇒
    那个**块名**会被当成"一个日期"✗ ⇒ 污染整日口径 ✗✓。
    """
    import re as _re
    _is_date = _re.compile(r'^\d{4}-\d{2}-\d{2}$').match
    return {k for k in (load_gaps(path).get(domain) or {}) if _is_date(str(k))}


def stock_gap_ranges(domain: str, path: Optional[str] = None) -> List[Dict]:
    """**个股级**源侧缺口区间 ✓（`<domain>: stock_gap_ranges: [...]` ✓）

    ★【2026-09-28 新增 ✓】背景 ✗✓（用户实测 ✓，连续三只：`000862` / `000852` / `000893`）：
      该批 **92 只**个股（`000004 … 000920`）在**同花顺**侧**整段断档** ✗：
        · 本地**形态完全同构** ✓ —— 每只 **52 行**（`2024-12-24 ~ 2025-03-14` ✓）、
          `2025-03-15 ~ 2026-03-09` **整段为空** ✗、`2026-03-10` 起恢复 ✓；
        · **直连源探测**（2026-09-28 ✓）3 只 × 3 时点 ✓：
          `20250110~0117` ⇒ **6 行** ✓、`20250610~0617` ⇒ **0 行** ✗、
          `20260224~0309` ⇒ **0 行** ✗ ⇒ **源端本就没有** ✗（**不可补采** ✗）。
      ⇒ 既有"整日"登记**表达不了个股** ✗（登记那 6 天会**连累**另外 5000 只 ✗✗），
        故扩出本结构 ✓。

    Returns:
        `[{'from': 'YYYY-MM-DD', 'to': 'YYYY-MM-DD', 'codes': [...], 'reason': …,
           'evidence': …}, …]` ✓（**保持登记顺序** ✓；结构非法项**跳过** ✗ 并告警 ✓）
    """
    raw = (load_gaps(path).get(domain) or {}).get('stock_gap_ranges')
    out: List[Dict] = []
    for item in (raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        _from, _to = str(item.get('from') or '')[:10], str(item.get('to') or '')[:10]
        codes = [str(c).split('.')[0] for c in (item.get('codes') or []) if c]
        if not (_from and _to and codes):
            logger.warning(f'个股级缺口登记项结构非法（已跳过 ✗）: {item}')
            continue
        out.append({'from': _from, 'to': _to, 'codes': codes,
                    'reason': item.get('reason') or '',
                    'evidence': item.get('evidence') or ''})
    return out


def is_stock_source_gap(domain: str, code: str, date_str: str,
                        path: Optional[str] = None) -> bool:
    """该 `(股票, 日期)` 是否属**已登记**的个股级源侧缺口 ✓（**只读** ✓，永不抛 ✗）"""
    c = str(code or '').split('.')[0]
    d = str(date_str or '')[:10]
    if not c or not d:
        return False
    for r in stock_gap_ranges(domain, path):
        if r['from'] <= d <= r['to'] and c in r['codes']:
            return True
    return False


def describe_stock_gap(domain: str, date_str: str, path: Optional[str] = None) -> str:
    """取覆盖该日期的**个股级**登记说明 ✓（供日志 ✓；无则 `''` ✓）"""
    d = str(date_str or '')[:10]
    for r in stock_gap_ranges(domain, path):
        if r['from'] <= d <= r['to']:
            return f'{r["from"]} ~ {r["to"]}（{len(r["codes"])} 只）: {r["reason"] or "未说明"}'
    return ''


def describe(domain: str, date_str: str, path: Optional[str] = None) -> str:
    """取某条登记的可读说明 ✓（用于日志与报告 ✓）"""
    info = (load_gaps(path).get(domain) or {}).get(str(date_str)) or {}
    reason = info.get('reason') or '未说明'
    ev = info.get('evidence') or ''
    return f'{date_str}: {reason}' + (f'｜证据: {str(ev)[:160]}' if ev else '')


def classify_gaps(domain: str, missing: Sequence[str],
                  path: Optional[str] = None) -> Tuple[List[str], List[str]]:
    """把缺日切分为 (需补采的 missing ✓, 已登记的源侧缺口 known_gaps ✓)

    Returns:
        (missing, known_gaps)：两者均为**升序**列表 ✓，且**互不重叠** ✓；
        两者之和 == 输入（**不丢任何一条** ✓ —— 不允许静默吞掉 ✗）
    """
    known = known_gap_dates(domain, path)
    miss, gaps = [], []
    for d in sorted({str(x) for x in (missing or [])}):
        (gaps if d in known else miss).append(d)
    return miss, gaps


def split_window(window: Sequence[str], domain: str,
                 path: Optional[str] = None) -> Tuple[List[str], List[str]]:
    """把**评分窗口**按登记表切分为 (可用日期, 窗口内已登记缺口) ✓

    用途：消费侧（如资金面评分）在"窗口完整性"判据里**豁免**已登记的上游缺口 ✓，
    同时把缺口日期**交回调用方**用于告警 ✓（豁免 ≠ 静默 ✗）。

    Returns:
        (expected, gaps)：均保持**升序**；两者互斥且并集 == 输入 ✓
    """
    return classify_gaps(domain, sorted({str(d) for d in (window or [])}), path)
