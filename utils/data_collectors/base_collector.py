# -*- coding: utf-8 -*-
"""通用数据采集基类（分批 / 断点续采 / 重试 / 幂等写入 / 变更检测 / 失败落盘）

使用方式（子类只需实现 4 个属性 + 2 个方法）：
    class XxxCollector(BaseCollector):
        name = 'xxx'                       # 采集器名（也是状态文件名）
        table = 'xxx_table'                # 目标表
        pk_cols = ('stock_code', 'trade_date')
        columns = (...)                    # 参与写入与变更检测的业务列
        source_start_date = '2023-09-11'   # 源可用起点（硬校验）
        def fetch_date(self, date_str): ...   # 返回当日源数据（rows/DataFrame）
        def normalize(self, raw): ...         # 规范化为 rows（dict 列表）

设计原则：**宁可失败，也不产出"看起来正常"的错误结果** ——
  缺数据 / 源起点越界 / 重试耗尽 → 抛错或明确记账，绝不静默跳过。
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

# 幂等 UPSERT 需要 SQLite ≥ 3.24（Python 3.8+ 自带均满足）
_UPSERT_SUPPORTED = None

#: 采集失败登记表 DDL ✓（**单一事实源** ✓）
#:   运行时建表（`_ensure_failure_table`）与 `data/DataSql.sql` 的对应段落
#:   都由这里提供 ✓ —— 避免"两处定义漂移"✗（这正是本轮 `stock_event` 事故的根因 ✗✓）
FAILURE_TABLE_SQL = (
    'CREATE TABLE IF NOT EXISTS data_fetch_failure ('
    'id INTEGER PRIMARY KEY AUTOINCREMENT, data_type TEXT, key TEXT, error TEXT, '
    'retry_count INTEGER DEFAULT 0, last_try TEXT, resolved INTEGER DEFAULT 0)',
    'CREATE INDEX IF NOT EXISTS idx_dff_type ON data_fetch_failure(data_type, resolved)',
)


def _norm(value):
    """变更比较用的归一化（float 统一到 4 位小数，避免浮点噪声误报差异）"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    if isinstance(value, str):
        return value.strip()
    return value


class BaseCollector:
    """四类持久化数据的公共采集骨架"""

    name: str = ''
    table: str = ''
    pk_cols: Sequence[str] = ()
    columns: Sequence[str] = ()
    source_start_date: Optional[str] = None      # 'YYYY-MM-DD'
    date_col: str = 'trade_date'                 # 日期列名（用于区间校验）

    #: 状态文件名（断点续采）
    state_file_name: str = ''

    def __init__(self, conn, fetcher=None, state_dir: Optional[str] = None,
                 batch_size: int = 500, max_retries: int = 2, retry_wait: float = 1.0):
        """
        Args:
            conn: sqlite3.Connection（生产由 get_global_db().connect() 提供；测试注入临时库）
            fetcher: 数据源对象（需实现 fetch 所需接口；测试注入 fake）
            state_dir: 进度文件目录（默认 data/logs/collector_state）
            batch_size: 单批写入行数
            max_retries: 单日抓取失败重试次数
            retry_wait: 重试间隔（秒）
        """
        if not self.name or not self.table or not self.pk_cols or not self.columns:
            raise ValueError('采集器必须定义 name/table/pk_cols/columns')
        self.conn = conn
        self.fetcher = fetcher
        self.batch_size = max(1, int(batch_size))
        self.max_retries = max(0, int(max_retries))
        self.retry_wait = float(retry_wait)
        self._state_dir = Path(state_dir or Path('data') / 'logs' / 'collector_state')
        self._state_lock = threading.RLock()
        self.stats: Dict[str, int] = {}
        self._reset_stats()

    # ------------------------------------------------------------------ 基础

    def _reset_stats(self):
        self.stats = {'added': 0, 'updated': 0, 'changed': 0, 'failed': 0, 'skipped': 0, 'days': 0}

    @property
    def state_path(self) -> Path:
        return self._state_dir / (self.state_file_name or f'{self.name}.json')

    def load_state(self) -> Dict:
        """读取断点状态（文件缺失/损坏 → 空状态 + 告警 ✓）"""
        with self._state_lock:
            path = self.state_path
            if not path.exists():
                return {}
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except Exception as e:
                logger.warning(f'[{self.name}] 采集状态文件损坏（{e}）→ 按全新开始处理')
                return {}

    def save_state(self, **kwargs) -> None:
        """原子写回断点状态 ✓（临时文件 + os.replace）"""
        with self._state_lock:
            import os
            state = self.load_state()
            state.update(kwargs)
            state['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            path = self.state_path
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.tmp')
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            except Exception as e:
                logger.warning(f'[{self.name}] 保存采集状态失败: {e}')

    # ------------------------------------------------------------------ 建表

    def create_table_sql(self) -> str:
        """生成本采集器的 `CREATE TABLE IF NOT EXISTS`（**单一事实源** ✓）

        【2026-09-25 新增】建表语句由**代码生成** ✓，不再各处手抄 ✗：
          · `ensure_schema()` 直接执行它 ✓
          · `data/DataSql.sql` 的对应段落由它**程序化生成** ✓（杜绝"两处结构不一致"✗）
          · 测试据此校验"SQL 文件 ↔ 采集器定义"一致 ✓
        ⚠️ 教训 ✗：公告表曾与 `stock_event` 同名不同结构 ✗，直接导致
        `CREATE INDEX ... ON stock_event(event_date)` 报错 ✗ → web_server 启动崩溃 ✗✓。
        """
        all_cols = list(dict.fromkeys(list(self.pk_cols) + list(self.columns)))
        real_cols = set(getattr(self, 'real_cols', ()) or ())
        ddl_cols = []
        for col in all_cols:
            if col in self.pk_cols:
                ddl_cols.append(f'{col} TEXT NOT NULL')
            elif col in real_cols or col.endswith('_rate') or col.endswith('_amount'):
                ddl_cols.append(f'{col} REAL')      # 数值列必须声明为 REAL ✓
            else:
                ddl_cols.append(f'{col} TEXT')
        pk = ', '.join(self.pk_cols)
        return (f'CREATE TABLE IF NOT EXISTS {self.table} (\n  '
                + ',\n  '.join(ddl_cols)
                + f',\n  PRIMARY KEY ({pk})\n)')

    def ensure_schema(self) -> None:
        """建表（含唯一键）+ 失败登记表 ✓；幂等可反复调用 ✓"""
        self.conn.execute(self.create_table_sql())
        self._ensure_failure_table()
        self.conn.commit()

    #: 失败登记表 DDL ✓（由 `FAILURE_TABLE_SQL` 唯一提供 ✓，供 DataSql/测试复用 ✓）
    def _ensure_failure_table(self) -> None:
        for stmt in FAILURE_TABLE_SQL:
            self.conn.execute(stmt)

    # ------------------------------------------------------------------ 勾子

    def fetch_date(self, date_str: str):
        """抓取单日源数据（子类实现；返回 DataFrame / rows / None）"""
        raise NotImplementedError

    def normalize(self, raw) -> List[Dict]:
        """规范化为 rows（dict 列表，含 pk 与 columns；子类实现）"""
        raise NotImplementedError

    # ------------------------------------------------------------------ 区间校验

    def assert_supported_range(self, start: str, end: str) -> None:
        """源起点硬校验 ✓：请求区间早于源可用起点 → **直接报错**（不静默截断 ✗）"""
        if not self.source_start_date:
            return
        if start < self.source_start_date:
            raise ValueError(
                f'[{self.name}] 请求区间起点 {start} 早于源可用起点 {self.source_start_date}；'
                f'数据源不提供该区间，禁止静默截断（需改用其它源或调整回测起点）')

    # ------------------------------------------------------------------ 写入

    def _upsert_sql(self) -> str:
        cols = list(self.columns)
        placeholders = ', '.join('?' for _ in cols)
        sql = f'INSERT INTO {self.table} ({", ".join(cols)}) VALUES ({placeholders})'
        preserve = set(getattr(self, 'preserve_on_update', ()) or ())
        updatable = [c for c in cols if c not in self.pk_cols and c not in preserve]
        if updatable and self._supports_upsert():
            sets = ', '.join(f'{c}=excluded.{c}' for c in updatable)
            sql += f' ON CONFLICT({", ".join(self.pk_cols)}) DO UPDATE SET {sets}'
        else:  # 兜底：全列 REPLACE（列全写 ⇒ 不会重置未列出的列 ✓）
            sql = f'INSERT OR REPLACE INTO {self.table} ({", ".join(cols)}) VALUES ({placeholders})'
        return sql

    def _supports_upsert(self) -> bool:
        global _UPSERT_SUPPORTED
        if _UPSERT_SUPPORTED is None:
            try:
                import sqlite3
                _UPSERT_SUPPORTED = sqlite3.sqlite_version_info >= (3, 24, 0)
            except Exception:
                _UPSERT_SUPPORTED = False
        return _UPSERT_SUPPORTED

    def _select_existing(self, keys: List[tuple]) -> Dict[tuple, Dict]:
        """批量读取已存在行（用于变更检测 ✓）"""
        out: Dict[tuple, Dict] = {}
        if not keys:
            return out
        cols = list(dict.fromkeys(list(self.pk_cols) + list(self.columns)))
        where = ' AND '.join(f'{c}=?' for c in self.pk_cols)
        cur = self.conn.cursor()
        for key in keys:
            row = cur.execute(f'SELECT {", ".join(cols)} FROM {self.table} WHERE {where}',
                              tuple(key)).fetchone()
            if row is not None:
                out[tuple(key)] = dict(zip(cols, row))
        return out

    def upsert(self, rows: List[Dict]) -> Dict[str, int]:
        """幂等写入 + 变更检测 ✓

        Returns:
            {'added': n, 'updated': n, 'changed': n}
        """
        added = updated = changed = 0
        sql = self._upsert_sql()
        cur = self.conn.cursor()
        for i in range(0, len(rows), self.batch_size):
            batch = rows[i:i + self.batch_size]
            keys = [tuple(r[c] for c in self.pk_cols) for r in batch]
            existing = self._select_existing(keys)
            values = []
            for r in batch:
                key = tuple(r[c] for c in self.pk_cols)
                old = existing.get(key)
                if old is None:
                    added += 1
                else:
                    diff_cols = [c for c in self.columns
                                 if c not in self.pk_cols and not c.endswith('_date')]
                    if any(_norm(old.get(c)) != _norm(r.get(c)) for c in diff_cols):
                        updated += 1
                        changed += 1
                values.append(tuple(r.get(c) for c in self.columns))
            cur.executemany(sql, values)
        self.conn.commit()
        return {'added': added, 'updated': updated, 'changed': changed}

    # ------------------------------------------------------------------ 失败落盘

    def record_failure(self, key: str, error: str, retry_count: int = 0) -> None:
        """失败**逐条落盘** ✓（修掉"failed 恒为 0"的假象 ✗）"""
        try:
            self._ensure_failure_table()
            self.conn.execute(
                'INSERT INTO data_fetch_failure (data_type, key, error, retry_count, last_try) '
                'VALUES (?, ?, ?, ?, ?)',
                (self.name, str(key), str(error)[:500], int(retry_count),
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.conn.commit()
        except Exception as e:
            logger.error(f'[{self.name}] 记录失败明细时出错: {e}')

    def list_failures(self, only_unresolved: bool = True, limit: int = 500) -> List[Dict]:
        """列出失败明细 ✓（便于定向重试与巡检 ✓）"""
        try:
            self._ensure_failure_table()
            sql = ('SELECT id, data_type, key, error, retry_count, last_try, resolved '
                   'FROM data_fetch_failure WHERE data_type=?')
            args: List = [self.name]
            if only_unresolved:
                sql += ' AND resolved=0'
            sql += ' ORDER BY id LIMIT ?'
            args.append(int(limit))
            return [dict(zip(('id', 'data_type', 'key', 'error', 'retry_count',
                              'last_try', 'resolved'), r))
                    for r in self.conn.execute(sql, args)]
        except Exception as e:
            logger.error(f'[{self.name}] 读取失败明细出错: {e}')
            return []

    def resolve_failure(self, key: str, note: Optional[str] = None) -> int:
        """把某条失败标记为**已解决** ✓（补采成功后调用 ✓ / 或确认已废弃 ✓）

        Args:
            key: 失败键（日期或自定义键 ✓）
            note: 解决说明（拼接到 error 尾部，便于日后取证 ✓）

        Returns:
            int: 受影响行数
        """
        try:
            self._ensure_failure_table()
            if note:
                cur = self.conn.execute(
                    'UPDATE data_fetch_failure SET resolved=1, error=error||? '
                    'WHERE data_type=? AND key=? AND resolved=0', (f'｜已解决: {note}', self.name, str(key)))
            else:
                cur = self.conn.execute(
                    'UPDATE data_fetch_failure SET resolved=1 '
                    'WHERE data_type=? AND key=? AND resolved=0', (self.name, str(key)))
            self.conn.commit()
            return cur.rowcount or 0
        except Exception as e:
            logger.error(f'[{self.name}] 标记失败已解决时出错: {e}')
            return 0

    def repair_coverage(self, trade_dates: Sequence[str], max_days: Optional[int] = None,
                        strict: bool = False) -> Dict:
        """**只补缺口** ✓：以"本地表实际覆盖"为准找出缺失交易日并补采 ✓（幂等 ✓）

        【2026-09-25 新增】这是"静默缺日"的**自愈入口** ✓ ——
        此前 `verify_coverage` 只"能查"，但**没有统一的补救动作** ✗，
        缺日只能靠人工发现 ✗（本次 `2023-11-22` 就是一条漏网之鱼 ✗）。
        现补齐流程为：查缺口 → 只采缺口 → 复检 → 仍缺则按 `strict` 抛错 ✗。
        补采成功后会**自动 resolve 对应失败记录** ✓（失败闭环 ✓）。

        Args:
            trade_dates: 期望覆盖的交易日（升序 ✓）
            max_days: 单次最多补几天（None = 全部 ✓）
            strict: 复检仍有缺口时是否抛错

        Returns:
            dict: {'missing_before': [...], 'repaired': n, 'missing_after': [...], 'ok': bool}
        """
        rep = self.verify_coverage(trade_dates)
        missing = list(rep['missing'])
        known_gaps = list(rep.get('known_gaps') or [])
        if max_days:
            missing = missing[:int(max_days)]
        if not missing:
            # 无"我方漏采" → 完成 ✓（已登记的源侧缺口单独上报 ✓，不视为待补 ✗）
            return {'missing_before': [], 'repaired': 0, 'missing_after': [],
                    'known_gaps': known_gaps, 'ok': True}
        logger.warning(f'[{self.name}] 检出缺口 {len(rep["missing"])} 日 ✗，本次补采 {len(missing)} 日 ✓')
        stats = self.run(missing, resume=False)
        after = self.verify_coverage(trade_dates)
        healed = [d for d in missing if d not in set(after['missing'])]
        for d in healed:                      # 补采成功 → 关闭失败记录 ✓（闭环 ✓）
            self.resolve_failure(d, note='repair_coverage 补采成功')
        ok = not after['missing']
        out = {'missing_before': rep['missing'], 'repaired': len(healed),
               'missing_after': after['missing'],
               'known_gaps': list(after.get('known_gaps') or known_gaps),
               'ok': ok, 'stats': stats}
        if not ok:
            msg = (f'[{self.name}] 补采后仍缺 {len(after["missing"])} 日: '
                   f'{after["missing"][:20]}')
            if strict:
                raise RuntimeError(msg)
            logger.error(msg)
        else:
            logger.info(f'[{self.name}] 缺口已闭合 ✓ 补采 {len(healed)} 日，'
                        f'现覆盖 {after["actual"]}/{after["expected"]} 日 ✓')
        return out

    # ------------------------------------------------------------------ 运行

    def collect_one_day(self, date_str: str) -> Dict:
        """采集单日（含重试 ✓ 与失败落盘 ✓）

        Returns:
            {'ok': bool, 'added': n, 'updated': n, 'changed': n}
        """
        self.assert_supported_range(date_str, date_str)
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self.fetch_date(date_str)
                if raw is None or (hasattr(raw, 'empty') and raw.empty) or (isinstance(raw, (list, tuple)) and len(raw) == 0):
                    raise ValueError(f'源返回空数据（{date_str}）')
                rows = self.normalize(raw)
                res = self.upsert(rows)
                for k in ('added', 'updated', 'changed'):
                    self.stats[k] += res[k]
                self.stats['days'] += 1
                return {'ok': True, **res}
            except Exception as e:
                last_err = e
                if attempt < self.max_retries:
                    logger.warning(f'[{self.name}] {date_str} 采集失败（第 {attempt + 1} 次）: {e}；'
                                   f'{self.retry_wait}s 后重试')
                    time.sleep(self.retry_wait)
        self.stats['failed'] += 1
        self.record_failure(date_str, str(last_err), retry_count=self.max_retries)
        logger.error(f'[{self.name}] {date_str} 采集失败（已重试 {self.max_retries} 次）: {last_err}')
        return {'ok': False, 'added': 0, 'updated': 0, 'changed': 0}

    def run(self, trade_dates: Sequence[str], resume: bool = True,
            batch_sleep: float = 0.0, save_state_every: int = 1) -> Dict[str, int]:
        """批量采集（分批 + 断点续采 ✓）

        Args:
            trade_dates: 待采集交易日列表（升序）
            resume: True = 跳过状态文件中已完成的日期 ✓
                     （注意：即便 resume=False，**也会把本次成功日期并入**已有进度 ✓，
                       避免"增量更新覆盖掉初始化进度" ✗）
            batch_sleep: 批间 sleep（秒；对齐 K 线机制 ✓）
            save_state_every: 每 N 天落一次进度

        Returns:
            统计字典（added/updated/changed/failed/skipped/days）
        """
        self._reset_stats()
        if not trade_dates:
            return dict(self.stats)
        dates = sorted({str(d) for d in trade_dates})
        state = self.load_state()
        done = set(state.get('completed_dates') or [])   # 始终以"已有进度"为基准并入 ✓
        for idx, d in enumerate(dates):
            if resume and d in done:
                self.stats['skipped'] += 1
                continue
            res = self.collect_one_day(d)
            if res.get('ok'):
                done.add(d)                             # 仅**成功日**记入进度 ✓
            if save_state_every and (idx + 1) % save_state_every == 0:
                self.save_state(completed_dates=sorted(done)[-500:],
                                last_run_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                source=self.name)
            if batch_sleep:
                time.sleep(batch_sleep)
        self.save_state(completed_dates=sorted(done)[-500:],
                        last_run_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        source=self.name)
        return dict(self.stats)

    def local_dates(self, start: Optional[str] = None, end: Optional[str] = None) -> set:
        """本地表已落库的日期集合（用于**覆盖率驱动**的补全 ✓）"""
        sql = f'SELECT DISTINCT {self.date_col} FROM {self.table}'
        args: List = []
        conds = []
        if start:
            conds.append(f'{self.date_col} >= ?')
            args.append(start)
        if end:
            conds.append(f'{self.date_col} <= ?')
            args.append(end)
        if conds:
            sql += ' WHERE ' + ' AND '.join(conds)
        return {str(r[0]) for r in self.conn.execute(sql, args).fetchall()}

    def verify_coverage(self, trade_dates: Sequence[str]) -> Dict:
        """覆盖率自检 ✓：返回 {expected, actual, missing}

        【重要】初始化**不能**只依赖状态文件判断"已完成" ✗ ——
        状态文件可能陈旧/被增量覆盖/人工清理 ✗，会造成"静默假成功"（实际没数据 ✗）。
        因此初始化一律以**本地表实际覆盖**为准 ✓。
        """
        expected = sorted({str(d) for d in trade_dates})
        actual = self.local_dates(expected[0], expected[-1]) if expected else set()
        raw_missing = [d for d in expected if d not in actual]
        # 【2026-09-25 新增】缺日**分类** ✓：区分"我方漏采"（需补 ✗）与
        #   "上游源侧无数据"（已登记 ✓，补不上 ✓ —— 但**照实上报**，不静默吞掉 ✗）
        from utils.data_collectors.source_gaps import classify_gaps, describe
        missing, known_gaps = classify_gaps(self.name, raw_missing)
        if known_gaps:
            logger.warning(
                f'[{self.name}] {len(known_gaps)} 日为**已登记的上游源侧缺口** ✓（不计入待补 ✗）：'
                + '; '.join(describe(self.name, d) for d in known_gaps[:5]))
        if missing:
            logger.warning(f'[{self.name}] 检出 {len(missing)} 日**本地漏采** ✗（需补采 ✓）: '
                           f'{missing[:12]}{" ..." if len(missing) > 12 else ""}')
        return {'expected': len(expected), 'actual': len(actual),
                'missing': missing, 'known_gaps': known_gaps}

    def run_initial(self, start: str, end: str, trade_dates: Sequence[str],
                    strict: bool = True) -> Dict[str, int]:
        """初始化（全量回填）：**按源起点硬校验** ✓ + **覆盖率驱动的补全** ✓ + 完成自检 ✓

        与 K 线机制的差异（有意 ✓）：
          · 不看状态文件"跳过"✗，而是**对比本地表实际覆盖**，只采**缺失日期** ✓
            （⇒ 对状态文件损坏/增量覆盖免疫 ✓，不会静默假成功 ✗）
          · 采集完成后**再次自检**；仍有缺口 → strict=True 时**抛错** ✗（不静默 ✓）

        Args:
            start / end: 目标区间（YYYY-MM-DD）
            trade_dates: 区间内的交易日列表
            strict: 自检不过是否抛错（默认 True ✓）
        """
        self.assert_supported_range(start, end)
        dates = sorted({str(d) for d in trade_dates})
        if not dates:
            raise ValueError('交易日列表为空')
        have = self.local_dates(start, end)
        missing = [d for d in dates if d not in have]
        self.stats['skipped'] = len(dates) - len(missing)
        if missing:
            logger.info(f'[{self.name}] 初始化补全：本地已覆盖 {len(have)} 日，'
                        f'待采集 {len(missing)} 日（{missing[0]} ~ {missing[-1]}）')
            self.run(missing, resume=False)
        report = self.verify_coverage(dates)
        if report['missing']:
            msg = (f'[{self.name}] 初始化后仍有 {len(report["missing"])} 个交易日缺数据: '
                   f'{", ".join(report["missing"][:20])}')
            self.record_failure('coverage', msg)
            if strict:
                raise RuntimeError(msg)
            logger.error(msg)
        else:
            logger.info(f'[{self.name}] 初始化完成 ✓ 覆盖 {report["expected"]} 个交易日')
        result = dict(self.stats)
        result['coverage'] = report
        return result

    def run_daily_update(self, trade_dates_all: Sequence[str], window: int = 3) -> Dict[str, int]:
        """每日增量：**滚动重采最近 `window` 个交易日** ✓（定稿：window=3）"""
        dates = sorted({str(d) for d in trade_dates_all})
        if not dates:
            raise ValueError('交易日列表为空，无法执行增量更新')
        recent = dates[-max(1, int(window)):]
        self.assert_supported_range(recent[0], recent[-1])
        # ★【2026-09-29 用户要求 ✓】**过程与结果都要看得见** ✗→✓
        #   此前本方法**一条日志都不打** ✗ ⇒ 日志里看不到"本次窗口是哪儿几日、采了几条"✗
        #   ⇒ 用户只能靠猜（实测 ✗✓：资金流到底补没补上无从判断 ✗）。
        logger.info(f'[{self.name}] 每日增量开始 ✓ 窗口=最近 {len(recent)} 个交易日 {recent} ✓'
                    f'（**滚动重采** ✓，不做跳过 ✓）')
        # 增量**不做跳过**（resume=False）——保证滚动重采真正发生 ✓
        stats = self.run(recent, resume=False)
        logger.info(f'[{self.name}] 每日增量完成 ✓ 窗口 {len(recent)} 日 ⇒ '
                    f'新增 {stats.get("added", 0)} ✓ / 更新 {stats.get("updated", 0)} ✓ / '
                    f'变化 {stats.get("changed", 0)} ✓ / **失败 {stats.get("failed", 0)}** ✗')
        return stats
