# -*- coding: utf-8 -*-
"""
全A指数 ADX 数据访问对象

提供 market_index_adx 表的读写：按 (trade_date, index_code) 唯一，
支持保存（upsert）、按日查询、区间查询、最新值与趋势。
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

# 配置日志
logger = logging.getLogger(__name__)


class MarketIndexADXDAO:
    """全A指数 ADX 数据访问对象"""

    TABLE = 'market_index_adx'

    def __init__(self, db=None):
        if db is None:
            from utils.global_db import get_global_db
            self.db = get_global_db()
        else:
            self.db = db

    def save(self, data: Dict) -> int:
        """
        保存指数ADX数据（存在则更新，不存在则插入）

        Args:
            data: 含 trade_date / index_code / adx / plus_di / minus_di 等字段

        Returns:
            记录ID
        """
        try:
            trade_date = data.get('trade_date')
            index_code = data.get('index_code')
            if not trade_date or not index_code:
                raise ValueError("trade_date and index_code are required")

            existing = self.query_by_date(trade_date, index_code)
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            record = {
                'trade_date': trade_date,
                'index_code': index_code,
                'period': data.get('period', 14),
                'adx': data.get('adx'),
                'plus_di': data.get('plus_di'),
                'minus_di': data.get('minus_di'),
                'adx_prev': data.get('adx_prev'),
                'adx_change': data.get('adx_change'),
                'trend_strength': data.get('trend_strength'),
                'trend_direction': data.get('trend_direction'),
                'close': data.get('close'),
                'data_points': data.get('data_points'),
                'has_enough_data': data.get('has_enough_data', 0),
                'updated_at': now,
            }

            if existing:
                self.db.update(self.TABLE, record,
                               {'trade_date': trade_date, 'index_code': index_code})
                logger.info(f"更新指数ADX: {trade_date} {index_code} ADX={record['adx']}")
                return existing['id']

            record['created_at'] = now
            record_id = self.db.insert(self.TABLE, record)
            logger.info(f"保存指数ADX: {trade_date} {index_code} ADX={record['adx']}")
            return record_id

        except Exception as e:
            logger.error(f"保存指数ADX数据失败: {e}")
            raise

    def query_by_date(self, trade_date: str, index_code: str = None) -> Optional[Dict]:
        """按日期（+指数代码）查询"""
        try:
            if index_code:
                return self.db.query_one(
                    f'SELECT * FROM {self.TABLE} WHERE trade_date = ? AND index_code = ?',
                    (trade_date, index_code))
            return self.db.query_one(
                f'SELECT * FROM {self.TABLE} WHERE trade_date = ? ORDER BY id DESC LIMIT 1',
                (trade_date,))
        except Exception as e:
            logger.error(f"查询指数ADX数据失败: {e}")
            return None

    def query_range(self, start_date: str, end_date: str,
                    index_code: str = None) -> List[Dict]:
        """查询日期区间数据（升序）"""
        try:
            if index_code:
                return self.db.query(
                    f'''SELECT * FROM {self.TABLE}
                        WHERE trade_date >= ? AND trade_date <= ? AND index_code = ?
                        ORDER BY trade_date ASC''',
                    (start_date, end_date, index_code))
            return self.db.query(
                f'''SELECT * FROM {self.TABLE}
                    WHERE trade_date >= ? AND trade_date <= ?
                    ORDER BY trade_date ASC''',
                (start_date, end_date))
        except Exception as e:
            logger.error(f"查询区间指数ADX数据失败: {e}")
            return []

    def _warn_if_multi_index(self, index_code) -> None:
        """⚠️【2026-10-05 护栏 ✓】未指定指数 + 表内**多指数** ⇒ **明确告警** ✗✓

        为什么必须有它 ✗✓（今天真事故 ✓）：本 DAO 的"不传 `index_code`"语义是
          **跨全部指数、按 `trade_date` 倒序 `LIMIT`** ✗ ⇒ 多指数后**同一天有多行** ✗
          ⇒ 取到**任意指数** ✗（实测：首页「市场 ADX」卡片显示 17.3 = 科创50 ✗，
            而文案写着全A ✗✓；飞书通知同病 ✓）。
        ⚠️ 行为**保持不变** ✗✓（不抛错、不改返回 ✓，避免打断既有调用 ✓），只加**告警** ✓
          ⇒ 任何**将来新增**的调用若漏传指数 ✗ ⇒ 日志里**立刻可见** ✓（不再静默复发 ✗✓）。
        """
        if index_code:
            return
        try:
            row = self.db.query_one(
                f'SELECT COUNT(DISTINCT index_code) AS n FROM {self.TABLE}') or {}
            n = int(row.get('n') or 0)
            if n > 1:
                logger.warning(
                    '【市场指数ADX ✗】调用未指定 `index_code` ⇒ 将**跨 %d 个指数**取数 ✗ '
                    '（结果可能来自**任意**指数 ✗；2026-10-05 已因此发生过'
                    '「卡片数字与文案不符」✗✓）。请显式传入指数 ✓，例如 '
                    '`resolve_index_adx_code()` ✓ / `resolve_board_index_code(...)` ✓。', n)
        except Exception:
            pass                                     # 护栏本身绝不影响主流程 ✗✓

    def get_latest(self, index_code: str = None) -> Optional[Dict]:
        """获取最新一条"""
        self._warn_if_multi_index(index_code)
        try:
            if index_code:
                return self.db.query_one(
                    f'SELECT * FROM {self.TABLE} WHERE index_code = ? '
                    f'ORDER BY trade_date DESC LIMIT 1', (index_code,))
            return self.db.query_one(
                f'SELECT * FROM {self.TABLE} ORDER BY trade_date DESC LIMIT 1')
        except Exception as e:
            logger.error(f"获取最新指数ADX失败: {e}")
            return None

    def get_trend(self, days: int = 10, index_code: str = None) -> Dict:
        """获取最近 N 天的 ADX 趋势"""
        self._warn_if_multi_index(index_code)        # ★ 同 `get_latest` ✓（多指数护栏 ✓）
        empty = {'trend': [], 'avg_adx': 0.0, 'max_adx': 0.0, 'min_adx': 0.0,
                 'latest_adx': None, 'latest_strength': None, 'latest_trade_date': None}
        try:
            if index_code:
                rows = self.db.query(
                    f'SELECT * FROM {self.TABLE} WHERE index_code = ? '
                    f'ORDER BY trade_date DESC LIMIT ?', (index_code, days))
            else:
                rows = self.db.query(
                    f'SELECT * FROM {self.TABLE} ORDER BY trade_date DESC LIMIT ?', (days,))
            if not rows:
                return empty

            trend = list(reversed(rows))
            values = [r['adx'] for r in rows if r['adx'] is not None]
            return {
                'trend': trend,
                'avg_adx': round(sum(values) / len(values), 2) if values else 0.0,
                'max_adx': max(values) if values else 0.0,
                'min_adx': min(values) if values else 0.0,
                'latest_adx': rows[0]['adx'],
                'latest_strength': rows[0]['trend_strength'],
                'latest_trade_date': rows[0]['trade_date'],
            }
        except Exception as e:
            logger.error(f"获取指数ADX趋势失败: {e}")
            return empty

    def delete(self, trade_date: str, index_code: str = None) -> bool:
        """删除指定日期数据"""
        try:
            if index_code:
                self.db.execute(
                    f'DELETE FROM {self.TABLE} WHERE trade_date = ? AND index_code = ?',
                    (trade_date, index_code))
            else:
                self.db.execute(
                    f'DELETE FROM {self.TABLE} WHERE trade_date = ?', (trade_date,))
            logger.info(f"删除指数ADX数据: {trade_date} {index_code or ''}")
            return True
        except Exception as e:
            logger.error(f"删除指数ADX数据失败: {e}")
            return False
