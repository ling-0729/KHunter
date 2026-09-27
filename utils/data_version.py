# -*- coding: utf-8 -*-
"""回测结果的**数据版本**判定（2026-09-25 M4）

用途：杜绝"**跨版本直接比收益**" ✗✓ ——
  · 结果表已存 `data_version`（由数据指纹派生 ✓）/ `data_fingerprint` / `strict_mode` ✓
  · 只有**同版本**（= 底层四类数据逐表行数/日期范围/校验和一致 ✓）的结果才允许直接比较 ✓
  · 历史老结果（无版本列/空值 ✗）→ 一律视为**不可比** ✗（它们正是"数据漂移期"的产物 ✗）

设计原则：**宁可拒绝比较，也不给出"看起来合理"的错误对比** ✓
"""

import logging
import sqlite3
from typing import Dict, List, Sequence

logger = logging.getLogger(__name__)


def _columns(conn: sqlite3.Connection, table: str = 'backtest_result') -> set:
    try:
        return {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    except Exception:
        return set()


def result_version(conn: sqlite3.Connection, result_id: int) -> Dict:
    """取某条结果的版本信息 ✓

    Returns:
        dict: {'id', 'found', 'data_version', 'data_fingerprint', 'strict_mode', 'created_at'}
              版本列为空/不存在 → `data_version` 为空串 ✓（调用方据此判"不可比" ✗）
    """
    cols = _columns(conn)
    if not cols:
        return {'id': result_id, 'found': False, 'data_version': '',
                'data_fingerprint': '', 'strict_mode': '', 'created_at': ''}
    want = [c for c in ('data_version', 'data_fingerprint', 'strict_mode', 'created_at')
            if c in cols]
    sel = ', '.join(want) if want else 'id'
    try:
        row = conn.execute(f'SELECT {sel} FROM backtest_result WHERE id=?',
                           (result_id,)).fetchone()
    except Exception as e:
        logger.warning(f'读取结果版本失败 id={result_id}: {e}')
        row = None
    if not row:
        return {'id': result_id, 'found': False, 'data_version': '',
                'data_fingerprint': '', 'strict_mode': '', 'created_at': ''}
    data = dict(zip(want, row)) if want else {}
    return {
        'id': result_id,
        'found': True,
        'data_version': str(data.get('data_version') or ''),
        'data_fingerprint': str(data.get('data_fingerprint') or ''),
        'strict_mode': str(data.get('strict_mode') or ''),
        'created_at': str(data.get('created_at') or ''),
    }


def check_comparability(conn: sqlite3.Connection, result_ids: Sequence[int]) -> Dict:
    """判断若干结果是否**同一数据版本**（可直接比较 ✓）

    Returns:
        dict: {
          'comparable': bool,
          'versions': {id: data_version},
          'reason': str,          # 不可比时的原因（含缺失项说明 ✓）
          'missing_version': [id] # 无版本信息（老结果 ✗）
        }
    """
    infos = [result_version(conn, int(i)) for i in result_ids]
    missing = [i['id'] for i in infos if not i['data_version']]
    versions = {i['id']: i['data_version'] for i in infos}
    if missing:
        return {'comparable': False, 'versions': versions, 'missing_version': missing,
                'reason': (f'结果 {missing} **缺少数据版本** ✗（多为"数据本地化之前"的旧结果 ✓）'
                           f'⇒ 底层数据可能已变，**禁止直接比较** ✗')}
    uniq = {v for v in versions.values() if v}
    if len(uniq) > 1:
        return {'comparable': False, 'versions': versions, 'missing_version': [],
                'reason': (f'数据版本不一致 ✗（{sorted(uniq)}）⇒ 底层四类数据不同，'
                           f'**禁止直接比较收益** ✗；请先核对 data_fingerprint 差异项 ✓')}
    return {'comparable': True, 'versions': versions, 'missing_version': [],
            'reason': '同一数据版本 ✓ 可直接比较'}


def assert_comparable(conn: sqlite3.Connection, result_ids: Sequence[int]) -> None:
    """跨版本/无版本比较 → **直接抛错** ✗

    Raises:
        RuntimeError: 不可比 ✗（错误信息含各结果版本与原因 ✓）
    """
    rep = check_comparability(conn, result_ids)
    if not rep['comparable']:
        raise RuntimeError(f'【数据版本】不可比较 ✗ {rep["reason"]}\n'
                           f'  版本明细: {rep["versions"]}')


def list_versions(conn: sqlite3.Connection, limit: int = 20) -> List[Dict]:
    """按数据版本汇总结果数 ✓（便于识别"哪个版本跑出来的" ✓）"""
    cols = _columns(conn)
    if 'data_version' not in cols:
        return []
    try:
        rows = conn.execute(
            'SELECT COALESCE(NULLIF(data_version, ""), "(无版本)") AS v, '
            'COUNT(*) AS n, MIN(created_at), MAX(created_at) '
            'FROM backtest_result GROUP BY v ORDER BY n DESC LIMIT ?', (int(limit),)).fetchall()
        return [{'data_version': r[0], 'count': r[1], 'first': r[2], 'last': r[3]}
                for r in rows]
    except Exception as e:
        logger.warning(f'汇总数据版本失败: {e}')
        return []
