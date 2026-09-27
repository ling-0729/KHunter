# -*- coding: utf-8 -*-
"""**启动期数据结构自愈迁移**（平滑无感升级 ✓，2026-09-25）

背景（实测事故 ✗✓）：
  · 「个股公告」表曾建为 `stock_event` ✗ —— 与 `data/DataSql.sql` 的**既定**应用事件表
    同名但结构不同 ✗（应用侧字段：`event_type/event_date/event_title/...` ✓）
  · 启动执行 DataSql.sql 时：`CREATE TABLE IF NOT EXISTS` 因同名而**不生效** ✗ →
    紧随其后的 `CREATE INDEX ... ON stock_event(event_date)` **报错** ✗ →
    `executescript` 中断 ✗ ⇒ **数据库初始化失败、web_server 启动崩溃** ✗✗

设计目标（"已使用用户平滑无感升级" ✓）：
  1. **自动** ✓：启动时自检并自愈，无需用户手工执行任何 SQL ✓
  2. **幂等** ✓：可重复执行；已迁移环境为**无操作** ✓
  3. **零数据丢失** ✓：只做 `RENAME` ✓ 或"**先全量复制、校验行数一致后才清理旧表**" ✓
  4. **绝不误伤应用表** ✓：仅当旧表**确为公告结构**（含 `ann_date` ✓）才动作 ✓；
     应用事件表（含 `event_date` ✗）**原样保留** ✓
  5. **失败可见** ✓：异常只记 ERROR ✗ 并返回结果 ✓（不吞异常静默 ✗），供上层决定 ✓
"""

import logging
import sqlite3
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)

#: 公告表（本地化链路 ✓）
ANNOUNCEMENT_TABLE = 'stock_announcement'
#: 应用既定事件表（**不得占用** ✗）
LEGACY_COLLIDING_TABLE = 'stock_event'
#: 公告表结构特征列 ✓（判定"这张 stock_event 到底是哪一家的" ✓）
ANNOUNCEMENT_MARKER_COL = 'ann_date'
#: 应用事件表结构特征列 ✓
APP_EVENT_MARKER_COL = 'event_date'


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _columns(conn: sqlite3.Connection, table: str) -> set:
    try:
        return {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    except Exception:
        return set()


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
    except Exception:
        return -1


def migrate_announcement_table(conn: sqlite3.Connection) -> Dict:
    """把**误占** `stock_event` 的公告表迁到 `stock_announcement` ✓（幂等 ✓ 零丢失 ✓）

    Returns:
        dict: {'action': 'noop'|'renamed'|'merged'|'skipped',
               'rows_before', 'rows_after', 'note'}
    """
    res = {'action': 'noop', 'rows_before': 0, 'rows_after': 0, 'note': ''}
    try:
        legacy_exists = _table_exists(conn, LEGACY_COLLIDING_TABLE)
        target_exists = _table_exists(conn, ANNOUNCEMENT_TABLE)
        if not legacy_exists:
            res['note'] = '无 stock_event 表 ⇒ 无需处理 ✓'
            return res

        legacy_cols = _columns(conn, LEGACY_COLLIDING_TABLE)
        if APP_EVENT_MARKER_COL in legacy_cols:
            # 已是**应用**事件表 ✓ → 绝不能动 ✗
            res['note'] = 'stock_event 为应用事件表（含 event_date ✓）⇒ 原样保留 ✓'
            return res
        if ANNOUNCEMENT_MARKER_COL not in legacy_cols:
            res['note'] = (f'stock_event 既非应用事件表也非公告表（列={sorted(legacy_cols)} ✗）'
                           f'⇒ 保守跳过，请人工核对 ✓')
            res['action'] = 'skipped'
            return res

        # 到这里 ⇒ 这是**旧的公告表** ✗（含 ann_date ✓）→ 必须让出 stock_event 这个表名 ✗
        n = _count(conn, LEGACY_COLLIDING_TABLE)
        res['rows_before'] = n

        if not target_exists:
            conn.execute(f'ALTER TABLE {LEGACY_COLLIDING_TABLE} '
                         f'RENAME TO {ANNOUNCEMENT_TABLE}')
            conn.commit()
            res['action'] = 'renamed'
            res['rows_after'] = _count(conn, ANNOUNCEMENT_TABLE)
            logger.warning(
                f'【启动迁移 ✓】检测到公告表误占应用表名 `{LEGACY_COLLIDING_TABLE}` ✗ → '
                f'已改名 `{ANNOUNCEMENT_TABLE}` ✓（{res["rows_before"]} 行无损 ✓）；'
                f'该表名将归还给应用事件表 ✓')
            return res

        # 两表并存 ✗ → **先合并复制** ✓ 再核对行数 ✓，全部到位才清理旧表 ✓
        before_target = _count(conn, ANNOUNCEMENT_TABLE)
        conn.execute(
            f'INSERT OR IGNORE INTO {ANNOUNCEMENT_TABLE} (stock_code, ann_date, title) '
            f'SELECT stock_code, ann_date, title FROM {LEGACY_COLLIDING_TABLE}')
        conn.commit()
        after_target = _count(conn, ANNOUNCEMENT_TABLE)
        res['rows_after'] = after_target
        if after_target >= before_target + n:
            conn.execute(f'DROP TABLE {LEGACY_COLLIDING_TABLE}')
            conn.commit()
            res['action'] = 'merged'
            logger.warning(
                f'【启动迁移 ✓】公告表与 `{LEGACY_COLLIDING_TABLE}` 并存 ✗ → '
                f'已合并 {before_target} → {after_target} 行 ✓ 并清理旧表 ✓')
        else:
            res['action'] = 'skipped'
            res['note'] = (f'合并后行数异常（{before_target}+{n} ≠ {after_target} ✗）'
                           f'⇒ **保留旧表不删** ✓，请人工核对 ✓')
            logger.error(res['note'])
        return res
    except Exception as e:
        conn.rollback() if hasattr(conn, 'rollback') else None
        res['note'] = f'迁移异常 ✗: {e}'
        logger.error(f'【启动迁移】公告表迁移失败 ✗: {e}', exc_info=True)
        return res


def needs_announcement_migration(conn: sqlite3.Connection) -> bool:
    """**预检** ✓：是否需要执行公告表迁移 ✓（不改任何数据 ✓，用于"是否要先备份"✓）"""
    try:
        if not _table_exists(conn, LEGACY_COLLIDING_TABLE):
            return False
        cols = _columns(conn, LEGACY_COLLIDING_TABLE)
        return APP_EVENT_MARKER_COL not in cols and ANNOUNCEMENT_MARKER_COL in cols
    except Exception:
        return False


# ---------------------------------------------------------------- §5.1 S1 ✓
#: 个股 K 线表 ✓（ADX 落地位置 ✓ —— 经评审由"独立表"改为**加列** ✓，见 §3.2 N6 ✗）
STOCK_KLINE_TABLE = 'stock_kline'
#: 新增列名 ✓
STOCK_KLINE_ADX_COL = 'adx'


def needs_stock_kline_adx(conn: sqlite3.Connection) -> bool:
    """**预检** ✓：`stock_kline` 存在但**缺 `adx` 列** ⇒ 需要迁移 ✓"""
    try:
        if not _table_exists(conn, STOCK_KLINE_TABLE):
            return False
        return STOCK_KLINE_ADX_COL not in _columns(conn, STOCK_KLINE_TABLE)
    except Exception:
        return False


def migrate_stock_kline_adx(conn: sqlite3.Connection) -> Dict:
    """给 `stock_kline` 加 `adx REAL` 列 ✓（§5.1 S1 ✓，**只加列不改列** ✓）

    · **元数据操作** ✓：SQLite `ADD COLUMN` **不重写数据** ✓（528 万行实测 **16.4ms** ✓）
    · **幂等** ✓：已有该列 ⇒ `noop` ✓
    · **不落数据** ✓：数值由 `utils/stock_adx.py` 回填 / 日更 ✓（**派生列** ✓ ⇒ 可随时重算 ✓）
    · **可回滚** ✓：`DROP COLUMN adx` ✓（无损 ✓，因为它是派生的 ✓）

    Returns:
        dict: {'action': 'added'|'noop'|'skipped'|'error', 'rows_before', 'note'}
    """
    res = {'action': 'noop', 'rows_before': -1, 'rows_after': -1, 'note': ''}
    try:
        if not _table_exists(conn, STOCK_KLINE_TABLE):
            res['action'] = 'skipped'
            res['note'] = f'{STOCK_KLINE_TABLE} 不存在（新库由 DataSql.sql 建表 ✓）'
            return res
        if STOCK_KLINE_ADX_COL in _columns(conn, STOCK_KLINE_TABLE):
            res['note'] = '已有 adx 列 ⇒ 无需迁移 ✓'
            return res

        res['rows_before'] = _count(conn, STOCK_KLINE_TABLE)
        conn.execute(f'ALTER TABLE {STOCK_KLINE_TABLE} '
                     f'ADD COLUMN {STOCK_KLINE_ADX_COL} REAL')
        conn.commit()
        res['action'] = 'added'
        res['rows_after'] = _count(conn, STOCK_KLINE_TABLE)
        res['note'] = ('已加列（元数据操作 ✓ 不重写数据 ✓）；'
                       '数值待 `utils/stock_adx.py` 回填 / 日更 ✓')
        logger.warning(f'【启动迁移】`{STOCK_KLINE_TABLE}` 已新增 `{STOCK_KLINE_ADX_COL}` 列 ✓'
                       f'（{res["rows_before"]} 行未重写 ✓）—— 请运行一次全量回填 ✓'
                       f'（`utils/stock_adx.py::backfill_all` ✓）')
        return res
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        res['action'] = 'error'
        res['note'] = f'加列失败 ✗: {e}'
        logger.error(f'【启动迁移】`{STOCK_KLINE_TABLE}.{STOCK_KLINE_ADX_COL}` 加列失败 ✗: {e}',
                     exc_info=True)
        return res


#: 迁移注册表 ✓（新增迁移只需追加 ✓；**必须幂等** ✓）
#:   三元组 = (名称, 执行函数, **预检函数** ✓) —— 预检用于"是否需要先备份" ✓
MIGRATIONS = (
    ('announcement_table_rename', migrate_announcement_table,
     needs_announcement_migration),
    ('stock_kline_add_adx', migrate_stock_kline_adx, needs_stock_kline_adx),
)

#: 「**确实改动了结构/数据**」的动作集合 ✓ ⇒ 计入 `applied` **并**写审计 ✓
#:
#: ⚠️ **修复** ✗→✓（2026-09-27 实测发现 ✓）：原先**只认** `('renamed', 'merged')` ✗ ——
#:   而 `migrate_stock_kline_adx` 返回的是 **`'added'`** ✗ ⇒
#:   ① 迁移**实际执行了** ✓，却**不进** `applied` ✗（日志显示"什么都没做"✗）；
#:   ② **不写审计** ✗ ⇒ `schema_migration_log` 表**从未被创建** ✗✓。
#:   实测取证 ✓：生产库 `stock_kline` **已有 `adx` 列** ✓ 但 `schema_migration_log`
#:   **不存在** ✗ —— 一个**静默失效**的审计 ✗（升级用户将无法取证/定位回滚点 ✗）。
#:   根因 ✓：**动作名清单硬编码不完整** ✗（新增一种动作就会漏一次 ✗）⇒ 改为**白名单常量** ✓。
CHANGED_ACTIONS = ('renamed', 'merged', 'added', 'dropped', 'created',
                   'updated', 'rebuilt', 'truncated')

#: 迁移审计表 ✓（记录每次实际执行的迁移 ✓，便于事后取证与回滚定位 ✓）
_MIGRATION_LOG_DDL = (
    'CREATE TABLE IF NOT EXISTS schema_migration_log ('
    'id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, action TEXT, '
    'rows_before INTEGER, rows_after INTEGER, backup_path TEXT, '
    'duration_ms INTEGER, applied_at TEXT, note TEXT)')


def _db_file(conn: sqlite3.Connection) -> str:
    """取当前连接对应的**数据库文件路径** ✓（内存库返回空串 ✓）"""
    try:
        for _seq, _name, path in conn.execute('PRAGMA database_list'):
            if path:
                return str(path)
    except Exception:
        pass
    return ''


def _backup_db_file(db_path: str) -> str:
    """迁移前**自动备份**数据库文件 ✓（2026-09-25 新增 ✓）

    原则 ✓：**任何会改动结构/数据的迁移，动手前必须先留一份可回滚的现场** ✓。
    此前只靠人工备份 ✗（本项目那份 2.1GB 备份就是手工做的 ✗✓）——
    升级用户根本不知道该备份 ✗ ⇒ 一旦迁移出问题就**无法回滚** ✗。

    Returns:
        备份文件路径 ✓（失败返回空串 ✗ —— 由调用方决定是否继续 ✓）
    """
    import shutil
    from pathlib import Path
    src = Path(db_path)
    if not src.exists() or src.stat().st_size == 0:
        return ''
    dst = src.with_name(f'{src.name}.bak-migrate-'
                        f'{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    try:
        shutil.copy2(src, dst)
        logger.warning(f'【启动迁移】已自动备份数据库 ✓ → {dst.name}'
                       f'（{dst.stat().st_size / 1048576:.1f} MB；回滚时用它替换回原文件 ✓）')
        return str(dst)
    except Exception as e:
        logger.error(f'【启动迁移】自动备份失败 ✗: {e}（仍将继续迁移 ✓，请人工备份 ✓）')
        return ''


def _log_migration(conn: sqlite3.Connection, name: str, result: Dict,
                   backup_path: str, duration_ms: int) -> None:
    """把实际执行的迁移写入审计表 ✓（失败不阻断 ✓）"""
    try:
        conn.execute(_MIGRATION_LOG_DDL)
        conn.execute(
            'INSERT INTO schema_migration_log (name, action, rows_before, rows_after, '
            'backup_path, duration_ms, applied_at, note) VALUES (?,?,?,?,?,?,?,?)',
            (name, result.get('action'), result.get('rows_before'),
             result.get('rows_after'), backup_path, duration_ms,
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'), result.get('note', '')))
        conn.commit()
    except Exception as e:
        logger.warning(f'【启动迁移】写审计记录失败（忽略 ✓）: {e}')


def run_startup_migrations(conn: sqlite3.Connection, backup: bool = True) -> Dict:
    """执行全部启动迁移 ✓（幂等 ✓；单项失败不影响其它 ✓ 但如实记录 ✗）

    **升级保障** ✓（2026-09-25 新增）：
      · 先**预检** ✓：只有确实需要迁移时才动手 ✓（**不备份、不写记录** ✓；
        仅**确保审计表存在** ✓ —— 见下方 ★ 说明 ✗✓，与
        `test_smooth_upgrade.py::test_无需迁移时不产生备份_零副作用` 断言一致 ✓）
      · 动手前**自动备份**数据库文件 ✓（`<db>.bak-migrate-<时间戳>` ✓）
      · 执行后写**审计记录** ✓（`schema_migration_log` ✓：动作/行数/备份路径/耗时 ✓）

    Args:
        conn: sqlite3 连接 ✓（用于定位数据库文件与写入审计 ✓）
        backup: 是否在真正迁移前自动备份 ✓（默认 True ✓；测试可关 ✓）

    Returns:
        dict: {'applied': [...], 'results': {...}, 'failed': {...},
               'needs': [...], 'backup_path': str}
    """
    # ① **预检** ✓：不迁移就什么都不做（绝大多数启动都是这条路径 ✓）
    needs = []
    for name, _fn, needs_fn in MIGRATIONS:
        try:
            if needs_fn(conn):
                needs.append(name)
        except Exception as e:
            logger.debug(f'【启动迁移】{name} 预检异常（按"需要"处理 ✓）: {e}')
            needs.append(name)

    # ★【2026-09-27】**先确保审计表存在** ✓（**无论**本次是否需要迁移 ✗✓）
    #   动机 ✗✓（**手工自检实测发现** ✓）：本库 `stock_kline.adx` 已加好 ✓ ⇒ 预检 `needs=[]` ✗
    #   ⇒ 直接 `return` ✗ ⇒ **审计表永远建不出来** ✗✓
    #   （正是"审计漏记 bug"修好后**依然存在**的残留 ✗ —— 只有"还会迁移"的库才轮得到建表 ✗）。
    #   ⇒ 把它提到**预检之后、早退之前** ✓：已迁移完的库也能有审计表 ✓，
    #     此后任何迁移都会被如实记录 ✓（**不伪造**历史记录 ✗）。
    try:
        conn.execute(_MIGRATION_LOG_DDL)
        conn.commit()
    except Exception as e:
        logger.warning(f'【启动迁移】创建审计表失败（忽略 ✓）: {e}')

    if not needs:
        return {'applied': [], 'results': {}, 'failed': {}, 'needs': [], 'backup_path': ''}

    # ② **迁移前自动备份** ✓（只在这一刻做一次 ✓，不会污染日常启动 ✓）
    backup_path = ''
    if backup:
        db_path = _db_file(conn)
        if db_path:
            backup_path = _backup_db_file(db_path)
        else:
            logger.warning('【启动迁移】未能定位数据库文件 ✗ → 跳过自动备份 ✓'
                           '（内存库/临时库属正常情况 ✓）')

    # ③ 执行 ✓
    applied, results, failed = [], {}, {}
    for name, fn, _needs in MIGRATIONS:
        t0 = datetime.now()
        try:
            r = fn(conn) or {}
            results[name] = r
            if r.get('action') in CHANGED_ACTIONS:      # ★ 见 `CHANGED_ACTIONS` 注释 ✓
                applied.append(name)
                _log_migration(conn, name, r, backup_path,
                               int((datetime.now() - t0).total_seconds() * 1000))
        except Exception as e:                       # 兜底：迁移异常不得阻断启动 ✗
            failed[name] = str(e)
            logger.error(f'【启动迁移】{name} 异常 ✗: {e}', exc_info=True)

    if applied:
        logger.warning(f'【启动迁移】本次实际执行: {applied} ✓'
                       f'（备份: {backup_path or "无 ✓"}；'
                       f'建议核对数据完整性 ✓，必要时用备份回滚 ✓）')
    return {'applied': applied, 'results': results, 'failed': failed,
            'needs': needs, 'backup_path': backup_path}
