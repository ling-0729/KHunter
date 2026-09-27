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
    """某采集器的**已登记源侧缺口日期**集合 ✓"""
    return set((load_gaps(path).get(domain) or {}).keys())


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
