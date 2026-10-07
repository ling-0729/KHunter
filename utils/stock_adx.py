# -*- coding: utf-8 -*-
"""个股 ADX 计算与回填（**M2 交付** ✓，§5.1 / §5.2 / §5.5 ✓）

## 唯一实现 ✗✓（**硬约束** ✓，由 `test_adx_alignment.py` 守着 ✓）

**唯一实现** = `utils.technical.ADX` ✓（指数侧经 `utils/market_index_adx` 也用它 ✓）。
本模块**只做薄包装** ✓ —— **禁止**自研第二套 ✗（否则个股/指数分档语义会悄然分叉 ✗）。
`utils/adx_reference.py`（Wilder 参考实现 ✓）**仅用于对齐验证** ✗，不参与生产计算 ✓。

## 职责 ✓

| 函数 | 用途 |
|---|---|
| `compute(df)` ✓ | 单股 K线 → `adx` 序列 ✓（**升/倒序皆可** ✓，系统实现两序等价 ✓）|
| `update_codes(conn, codes)` ✓ | 重算并回写指定股票的 `stock_kline.adx` ✓（**幂等** ✓）|
| `update_recent_days(conn, n)` ✓ | §5.5 日环节：重算**最近 n 个交易日**涉及的所有股票 ✓ |
| `backfill_all(conn)` ✓ | **全量回填** ✓（首次落地 ✓）|

## 关键约定 ✗✓

1. **预热期写 NULL** ✗✓ —— 系统实现前 `2*period` 根为 `NaN` ✓，实测收敛需 **120 根** ✓
   （`adx_reference.PREHEAT_BARS` ✓）⇒ **不臆造 0** ✗，写 `NULL` ✓；
   下游按 §5.2 归因分流 ✓（有效根数不足 ⇒ `not_applicable` ⇒ 放行 ✓）。
2. **防前视** ✓ —— 每行的 `adx` 只用**该行及之前**的数据 ✓（因果计算 ✓，无未来信息 ✓）。
3. **幂等** ✓ —— `UPDATE ... WHERE code=? AND date=?` ✓ 可反复执行 ✓。
4. **只读 K 线的 `high/low/close`** ✓，**不联网** ✗。
"""
import logging
import sqlite3
import time
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

# ★ 唯一实现 ✓（**不得**另写一套 ✗ —— 见 `test_adx_alignment.py::test_个股计算器尚未另立门户` ✓）
from utils.technical import ADX
#: 预热根数 ✓（= **120** ✓，由 M1 实测标定 ✓，单一来源 ✓）
from utils.adx_reference import warmup_bars

logger = logging.getLogger(__name__)

TABLE = 'stock_kline'
ADX_COLUMN = 'adx'
DEFAULT_PERIOD = 14

#: 每次提交的行数 ✓（避免超长事务 ✓）
BATCH_SIZE = 200_000


def compute(df: pd.DataFrame, period: int = DEFAULT_PERIOD) -> pd.Series:
    """单股 K线 → `adx` ✓（返回 Series，index 与入参对齐 ✓）

    ⚠️ **前 `warmup_bars()` 根强制置 `NaN`** ✗✓（= **120** ✓，M1 实测标定 ✓）：
    系统实现会**提前出值** ✗，但那些值**未收敛** ✗（实测 bar 60~90 处偏差仍达 **3.19** ✗，
    足以翻转"`ADX ≥ 25` / 上升下降"这类判定 ✗✓）⇒ **必须丢弃** ✗，
    否则下游闸门会拿到**不可靠**的 ADX ✗。
    """
    if df is None or df.empty:
        return pd.Series(dtype='float64')
    out = ADX(df, period)
    s = out['adx'] if isinstance(out, pd.DataFrame) else out
    s = pd.to_numeric(s, errors='coerce').astype(float)
    n_warm = min(warmup_bars(period), len(s))
    if n_warm > 0:
        s = s.copy()
        s.iloc[:n_warm] = float('nan')          # 预热期 ⇒ NaN ⇒ 落库为 NULL ✓（不臆造 0 ✗）
    return s


def ensure_column(conn: sqlite3.Connection) -> bool:
    """**幂等**确保 `stock_kline.adx` 存在 ✓（**使用点自愈** ✓，与启动迁移**同一实现** ✓）

    ⚠️ 为什么必须有它 ✗✓（**2026-09-27 实测发现** ✓）：
      `utils/db_initializer` 里**迁移先于 `DataSql.sql`** 执行 ✗ ⇒ **全新库**在迁移那一刻
      `stock_kline` **还不存在** ✗ ⇒ 加列迁移返回 `skipped` ✗ ⇒ 随后建表出来**没有 `adx` 列** ✗
      ⇒ 只能**等下一次启动**才补上 ✗ —— 而**首次日更**的第 5.5 步会因
      `no such column: adx` ✗ **直接失败** ✗✓（不是"没数据"，是**报错** ✗）。

    ⇒ 故在使用点再兜一次 ✓（成本 = 一次 `PRAGMA table_info` ✓，可忽略 ✓）；
      且复用 `schema_migrations` 的实现 ✓（**不**在这里另写一份 DDL ✗ —— 单一事实源 ✓）。
    """
    try:
        from utils.schema_migrations import migrate_stock_kline_adx
        action = (migrate_stock_kline_adx(conn) or {}).get('action')
        if action in ('added', 'noop'):
            return True
        logger.warning(f'[StockADX] `{TABLE}.{ADX_COLUMN}` 不可用（action={action} ✗）')
        return False
    except Exception as e:
        logger.error(f'[StockADX] 确保 `{TABLE}.{ADX_COLUMN}` 列失败 ✗: {e}')
        return False


def _fetch(conn: sqlite3.Connection, codes: Sequence[str],
           period: int) -> pd.DataFrame:
    ph = ','.join('?' * len(codes))
    return pd.read_sql_query(
        f'SELECT code, date, high, low, close FROM {TABLE} '
        f'WHERE code IN ({ph}) ORDER BY code, date', conn, params=list(codes))


def update_codes(conn: sqlite3.Connection, codes: Iterable[str],
                 period: int = DEFAULT_PERIOD,
                 progress_every: int = 0) -> Dict:
    """重算并回写指定股票的 `adx` ✓（**幂等** ✓；单股失败不影响其它 ✓）

    Args:
        progress_every: ★ 每处理多少只打一行进度 ✓（0 = 不打 ✓）
            ⚠️【2026-09-28 可观测性 ✓】实测踩到 ✗（用户 2026-09-28 ✓）：
              本函数是**分钟级**任务 ✓（5000+ 只 × 全历史递推 ✓），原先**只在最后打一行** ✗
              ⇒ 日志空白 ⇒ 用户误判为**卡死** ✗✓（"没有日志了，是否停滞状态？" ✓）。

    Returns:
        dict: {'updated_rows': int, 'codes': int, 'failed': {code: err}}
    """
    codes = [str(c) for c in codes if c]
    if not codes:
        return {'updated_rows': 0, 'codes': 0, 'failed': {}}

    # ★ **使用点自愈** ✗✓（2026-09-27 实测补 ✓）：列不存在 ⇒ 先补建 ✓
    #   否则全新库首次日更第 5.5 步会因 `no such column: adx` ✗ **直接报错** ✗
    if not ensure_column(conn):
        msg = f'{TABLE}.{ADX_COLUMN} 列不存在且无法自动补建 ✗'
        logger.error(f'[StockADX] {msg} ⇒ 本次跳过 ✓（不抛异常 ✓，不阻断日更 ✓）')
        return {'updated_rows': 0, 'codes': len(codes),
                'failed': {c: msg for c in codes}}

    n_rows, failed = 0, {}
    t0, last_mark = time.time(), 0        # ★ 进度留痕用 ✓（见下方 `progress_every` ✓）
    for i in range(0, len(codes), 500):
        chunk = codes[i:i + 500]
        try:
            df = _fetch(conn, chunk, period)
        except Exception as e:
            logger.error(f'[StockADX] 读取 K 线失败 ✗: {e}')
            failed.update({c: str(e) for c in chunk})
            continue
        if df.empty:
            continue

        payload: List[tuple] = []
        for code, g in df.groupby('code', sort=False):
            try:
                g = g.sort_values('date')                      # 升序 ✓（因果 ✓）
                adx = compute(g, period)
                for d, v in zip(g['date'].tolist(), adx.tolist()):
                    # 预热期/异常 ⇒ 写 NULL ✓（**不臆造 0** ✗，§5.2 ✓）
                    payload.append((None if (v is None or v != v) else float(v),
                                    str(code), str(d)))
            except Exception as e:
                logger.warning(f'[StockADX] {code} 计算失败 ✗: {e}')
                failed[str(code)] = str(e)

        if payload:
            conn.executemany(
                f'UPDATE {TABLE} SET {ADX_COLUMN}=? WHERE code=? AND date=?', payload)
            conn.commit()
            n_rows += len(payload)

        # ★【2026-09-28 可观测性 ✓】**进度留痕** ✗→✓（原先**只在全部结束时打一行** ✗
        #   ⇒ 分钟级静默 ⇒ 用户实测误判"卡死"✗✓ —— 见 docstring ✓）
        if progress_every:
            done = min(i + 500, len(codes))
            mark = done // int(progress_every)
            if mark > last_mark:
                last_mark = mark
                el = max(time.time() - t0, 1e-6)
                rate = done / el
                eta = (len(codes) - done) / rate if rate > 0 else 0.0
                logger.info(f'[StockADX] 重算进度 {done}/{len(codes)} 只 ✓'
                            f'（{done * 100 // max(1, len(codes))}% ✓；'
                            f'{n_rows} 行 / {el:.0f}s；约 {rate:.0f} 只每秒，'
                            f'剩余 ~{eta / 60:.1f} 分钟 ✓）')
    return {'updated_rows': n_rows, 'codes': len(codes), 'failed': failed}


def _codes_of_recent_days(conn: sqlite3.Connection, days: int) -> List[str]:
    """最近 `days` 个交易日（**全市场** ✓）涉及的股票代码 ✓（§5.5 日环节 ✓）"""
    cur = conn.execute(
        f'SELECT DISTINCT date FROM {TABLE} ORDER BY date DESC LIMIT ?', (int(days),))
    dates = [str(r[0]) for r in cur.fetchall()]
    if not dates:
        return []
    ph = ','.join('?' * len(dates))
    cur = conn.execute(
        f'SELECT DISTINCT code FROM {TABLE} WHERE date IN ({ph})', dates)
    return [str(r[0]) for r in cur.fetchall()]


def is_daily_update_enabled() -> bool:
    """日环节开关 ✓：`config/config.yaml → update.stock_adx.enabled` ✓（默认 **true** ✓）

    默认开 ✓ 的理由（§5.5 ✓）：`adx` 是**派生数据** ✓、只读本地 K 线 ✓、无副作用 ✓；
    关掉它只会让 `adx` 逐渐失效 ✗（被写入方清空 ✗）⇒ 反而需要人工补算 ✗。
    """
    try:
        import yaml
        from pathlib import Path as _P
        p = _P(__file__).resolve().parents[1] / 'config' / 'config.yaml'
        if not p.exists():
            return True
        with open(p, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        return bool((((data.get('update') or {}).get('stock_adx') or {})
                     .get('enabled', True)))
    except Exception as e:
        logger.warning(f'[StockADX] 读取 update.stock_adx.enabled 失败（按 true 处理 ✓）: {e}')
        return True


def update_recent_days(conn: sqlite3.Connection, days: int = 5,
                       period: int = DEFAULT_PERIOD) -> Dict:
    """§5.5 日环节 ✓：重算**最近 n 个交易日**涉及股票的 ADX ✓

    ⚠️ 必须在 K 线写入**之后**调用 ✓（否则又被写入方清空 ✗，见 §5.3 覆盖矩阵 ✓）。
    ⚠️ 只重算"最近 n 日涉及"的股票 ✓，但**每只从全历史重算** ✓ ——
       ADX 是**递推**指标 ✗，截断历史会得到错值 ✗✓（不是性能取舍，是正确性 ✗）。
    """
    if not is_daily_update_enabled():
        return {'updated_rows': 0, 'codes': 0, 'failed': {}, 'skipped': True,
                'note': 'update.stock_adx.enabled=false ⇒ 跳过 ✓'}
    codes = _codes_of_recent_days(conn, days)
    # ★★【2026-09-29 用户要求 ✓】**补日志：开工要说清规模，收工要说清耗时** ✗→✓ ★★
    #   实测痛点 ✗✓：用户看到"期间无逐条日志，请以 CPU 占用判断是否在跑"✗ ——
    #     那等于**要求用户去看任务管理器** ✗（且分钟级静默 ✗）。
    #   现补两行 ✓：
    #     · **开局**：涉及多少只 ✓（用户据此判断"大概要等多久"✓）；
    #     · **收工**：更新行数 + 失败只数 + **耗时** ✓。
    #   逐块进度由 `update_codes(progress_every=500)` 负责 ✓（含速率与剩余时间 ✓）。
    _t0 = time.time()
    logger.info(f'[StockADX] 日环节开始 ✓ 最近 {days} 日涉及 {len(codes)} 只 '
                f'（每只**从全历史递推** ✓ ⇒ 分钟级）；**进度每 500 只一行** ✓')
    res = update_codes(conn, codes, period, progress_every=500)
    res['dates_scope'] = int(days)
    res['elapsed'] = round(time.time() - _t0, 1)
    logger.info(f'[StockADX] 日环节完成 ✓ 最近 {days} 日涉及 {len(codes)} 只 ⇒ '
                f'更新 {res["updated_rows"]} 行 ✓'
                f'（失败 {len(res["failed"])} 只 ✗；耗时 {res["elapsed"]:.1f}s ✓）')
    return res


def _all_codes(conn: sqlite3.Connection) -> List[str]:
    cur = conn.execute(f'SELECT DISTINCT code FROM {TABLE} ORDER BY code')
    return [str(r[0]) for r in cur.fetchall()]


#: 单股 `(date, adx)` 全历史缓存 ✓（进程内 ✓，每只只查一次 ✓）
_ADX_ROWS_CACHE: Dict[str, List[tuple]] = {}
#: ★【2026-09-30 用户要求 ✓】单股 `(date, close)` 全历史缓存 ✓（**同一张表** `stock_kline` ✓
#:   ⇒ 与 `adx` **同源** ✓、不联网 ✓、不新增采集 ✓）—— 供「个股放行 `close(T-1) > MA20`」✓
_CLOSE_ROWS_CACHE: Dict[str, List[tuple]] = {}


def normalize_code(stock_code: str) -> str:
    """归一到纯数字代码 ✓（引擎/实盘的 `stock_code` 可能带 `.SZ`/`.SH` 后缀 ✗）"""
    return str(stock_code or '').strip().replace('.SZ', '').replace('.SH', '').replace('.sz', '').replace('.sh', '')


def fetch_adx_rows(stock_code: str, conn: sqlite3.Connection = None,
                   use_cache: bool = True) -> List[tuple]:
    """取该股全历史 `(date, adx)` ✓（**升序** ✓，含 `adx` 为 NULL 的行 ✓）

    ⚠️ **引擎传入的 K 线 df 未必含 `adx` 列** ✗✓（实测踩过：df 只取固定列 ✗
    ⇒ 闸门会一律判 `missing` ⇒ **笔数 0** ✗）⇒ 故闸门由此处**自取** ✓。

    调用方须按"信号日"**截断** ✗（`date < signal_date` ✓）—— 本函数**不**截断 ✓，
    以免把截断逻辑藏进缓存 ✗（那会造成前视 ✗✓）。
    """
    code = normalize_code(stock_code)
    if not code:
        return []
    if use_cache and code in _ADX_ROWS_CACHE:
        return _ADX_ROWS_CACHE[code]
    rows: List[tuple] = []
    try:
        if conn is None:
            from utils.global_db import get_global_db
            conn = get_global_db().connect()
        rows = [(str(r[0]), r[1]) for r in conn.execute(
            f'SELECT date, {ADX_COLUMN} FROM {TABLE} WHERE code=? ORDER BY date', (code,))]
    except Exception as e:
        logger.warning(f'[StockADX] 读取 {code} 的 adx 失败 ✗（按"无数据"处理 ✓）: {e}')
        rows = []
    if use_cache:
        _ADX_ROWS_CACHE[code] = rows
    return rows


def fetch_close_rows(stock_code: str, conn: sqlite3.Connection = None,
                     use_cache: bool = True) -> List[tuple]:
    """★【2026-09-30 用户要求 ✓】取该股全历史 `(date, close)` ✓（**升序** ✓）

    动机 ✗✓（用户原话 ✓）："**个股放行过滤增加 t-1(close) > ma20**" ✓
      ⇒ 闸门新增「T-1 收盘 > MA20」✓ 需要**收盘价**序列 ✓。

    ⚠️ **与 `fetch_adx_rows` 同表同源** ✗✓（都是 `stock_kline` ✓）—— 保证"ADX 用新数据、
      MA 用旧数据"这种**漂移不可能发生** ✗✓；也保证**不联网** ✓。
    ⚠️ 调用方须按信号日**截断** ✗（`date < signal_date` ✓）—— 本函数**不**截断 ✓
      （同 `fetch_adx_rows` ✓：截断逻辑藏在缓存里会造成**前视** ✗✓）。
    ⚠️ `close` 为空/非数的行**照原样返回** ✓（由调用方决定"跳过 vs 保守"✗✓，
      本函数不做静默填充 ✗ —— 那会把"缺数据"✗变成"价格为 0"✗，最危险 ✗）。
    """
    code = normalize_code(stock_code)
    if not code:
        return []
    if use_cache and code in _CLOSE_ROWS_CACHE:
        return _CLOSE_ROWS_CACHE[code]
    rows: List[tuple] = []
    try:
        if conn is None:
            from utils.global_db import get_global_db
            conn = get_global_db().connect()
        rows = [(str(r[0]), r[1]) for r in conn.execute(
            f'SELECT date, close FROM {TABLE} WHERE code=? ORDER BY date', (code,))]
    except Exception as e:
        logger.warning(f'[StockADX] 读取 {code} 的 close 失败 ✗（按"无数据"处理 ✓）: {e}')
        rows = []
    if use_cache:
        _CLOSE_ROWS_CACHE[code] = rows
    return rows


def clear_adx_cache() -> None:
    """清空缓存 ✓（回测/长驻进程按需调用 ✓；日更后应清 ✓）"""
    _ADX_ROWS_CACHE.clear()
    _CLOSE_ROWS_CACHE.clear()             # ★ 收盘序列同清 ✓（2026-09-30 ✓）


def backfill_all(conn: sqlite3.Connection, period: int = DEFAULT_PERIOD,
                 limit_codes: Optional[int] = None, offset: int = 0,
                 chunk_size: int = 0,
                 codes: Optional[Sequence[str]] = None) -> Dict:
    """**全量回填** ✓（首次落地 / 自愈重算 ✓）—— 支持**分批** ✓（可反复续跑 ✓）

    Args:
        period: ADX 周期 ✓（14 ✓）
        limit_codes: 本批最多处理多少只 ✓（`None` = 不限 ✓）
        offset: 从**按代码排序**后的第几只开始 ✓（**分批续跑用** ✓；
            配合 `next_offset` ✓ 可把长任务切成多段 ✓，且**永远前进** ✓
            —— 不能用"只补 NULL 行"分批 ✗：整段处于预热期的次新股会**永远**是 NULL ✗）
        chunk_size: 每处理多少只打一次进度日志 ✓（0 = 不打 ✓）
        codes: ★ **只重算这些股票** ✓（`None` = 全市场 ✓；见 `codes_with_missing` ✓）
            ⚠️【2026-09-28 用户质疑 ✓】自愈原先**无脑全市场** ✗ —— 而它触发的依据是
              "**最近 N 日**真缺口 > 5%" ✓（范围小 ✓）⇒ 处方**过重** ✗✓。
              本参数让自愈**只处理真有缺口的股票** ✓ ⇒ **算法完全不变** ✓
              （每只仍**从全历史递推** ✓）⇒ 结果与全量**逐位相同** ✓、只是跳过无缺口者 ✓✓。

    Returns:
        dict: {'updated_rows', 'codes', 'failed', 'next_offset', 'total_codes', 'done'}
    """
    all_codes = ([str(c) for c in codes] if codes is not None else _all_codes(conn))
    total = len(all_codes)
    codes = all_codes[int(offset):]
    if limit_codes:
        codes = codes[:int(limit_codes)]

    t0 = time.time()
    updated, failed = 0, {}
    if not chunk_size:
        res = update_codes(conn, codes, period)
        updated, failed = res['updated_rows'], res['failed']
    else:
        for i in range(0, len(codes), int(chunk_size)):
            part = codes[i:i + int(chunk_size)]
            res = update_codes(conn, part, period)
            updated += res['updated_rows']
            failed.update(res['failed'])
            done = i + len(part)
            el = max(time.time() - t0, 1e-6)
            rate = done / el
            eta = (len(codes) - done) / rate if rate > 0 else 0
            logger.info(f'[StockADX] 回填进度 {done}/{len(codes)} 只 ✓ '
                        f'（{updated} 行 / {el:.0f}s；约 {rate:.0f} 只每秒，'
                        f'本批剩余 ~{eta / 60:.1f} 分钟 ✓）')

    next_offset = int(offset) + len(codes)
    res = {'updated_rows': updated, 'codes': len(codes), 'failed': failed,
           'next_offset': next_offset, 'total_codes': total,
           'done': next_offset >= total}
    logger.info(f'[StockADX] 回填批次完成 ✓ 本批 {len(codes)} 只 / {updated} 行 ✓'
                f'（失败 {len(failed)} 只 ✗）⇒ 进度 {next_offset}/{total} ✓'
                f'{" —— 全部完成 ✓" if res["done"] else "（可继续续跑 ✓）"}')
    return res


def coverage_stats(conn: sqlite3.Connection, days: int = 5) -> Dict:
    """可观测性 ✓（§5.4 ✓）：最近 `days` 个交易日的 `adx` 覆盖情况 ✓"""
    cur = conn.execute(
        f'SELECT DISTINCT date FROM {TABLE} ORDER BY date DESC LIMIT ?', (int(days),))
    dates = [str(r[0]) for r in cur.fetchall()]
    total = null_cnt = 0
    for d in dates:
        row = conn.execute(
            f'SELECT COUNT(*), SUM(CASE WHEN {ADX_COLUMN} IS NULL THEN 1 ELSE 0 END) '
            f'FROM {TABLE} WHERE date=?', (d,)).fetchone()
        total += int(row[0] or 0)
        null_cnt += int(row[1] or 0)
    return {'days': len(dates), 'rows': total, 'null_rows': null_cnt,
            'null_ratio': (null_cnt / total) if total else 0.0}


# ================================================================ §5.2 精确归因 / §5.4 自愈

def missing_stats(conn: sqlite3.Connection, start: str, end: str,
                  warmup: Optional[int] = None) -> Dict:
    """`[start, end]` 区间内 `adx` 的**精确缺口**归因 ✓（§5.2 ✓，2026-09-27 ✓）

    ⚠️ 为什么不能直接用"NULL 比例" ✗✓：每只股票的**前 120 根**（预热期 ✓）
    **本就该是 NULL** ✓（归因 `not_applicable` ✓ —— 次新股该规则**不适用** ✓，不是故障 ✗）。
    实测 ✗：整库 NULL 比例 **12%**（`632,173 / 5,289,071` ✓）⇒ 若当成缺口 ✗
    ⇒ 闸门/自愈会**常年误报** ✗ ⇒ 最后必被人关掉 ✗✓（= 机制失效 ✗）。

    **判据** ✓：`真缺口 = 实际 NULL − Σ_股票 clamp(120 − 起始前根数, 0, 区间内根数)` ✓
    （即"该股落在区间内、且**全局序号 ≤ 120** 的那些行" ✓ —— 只有它们**本该**为 NULL ✓）

    Returns:
        {'rows','null_rows','expected_warmup_nulls','missing_rows','missing_ratio','warmup_bars'}
    """
    warm = int(warmup if warmup is not None else warmup_bars())
    row = conn.execute(
        f'SELECT COUNT(*), SUM(CASE WHEN {ADX_COLUMN} IS NULL THEN 1 ELSE 0 END) '
        f'FROM {TABLE} WHERE date BETWEEN ? AND ?', (start, end)).fetchone()
    total, nulls = int(row[0] or 0), int(row[1] or 0)
    expected = 0
    if total:
        expected = int(conn.execute(
            f'SELECT SUM(CASE WHEN n_before >= ? THEN 0 '
            f'WHEN n_before + n_in >= ? THEN ? - n_before ELSE n_in END) FROM ('
            f'  SELECT k.code AS code,'
            f'    (SELECT COUNT(*) FROM {TABLE} b WHERE b.code=k.code AND b.date < ?) AS n_before,'
            f'    (SELECT COUNT(*) FROM {TABLE} i WHERE i.code=k.code '
            f'      AND i.date BETWEEN ? AND ?) AS n_in'
            f'  FROM (SELECT DISTINCT code FROM {TABLE} WHERE date BETWEEN ? AND ?) k)',
            (warm, warm, warm, start, start, end, start, end)).fetchone()[0] or 0)
    missing = max(0, nulls - expected)
    usable = max(1, total - expected)              # "应算行" ✓（含已算 ✓ + 缺口 ✗）
    return {'rows': total, 'null_rows': nulls, 'expected_warmup_nulls': expected,
            'missing_rows': missing, 'missing_ratio': missing / usable,
            'warmup_bars': warm}


def recent_dates(conn: sqlite3.Connection, days: int = 5) -> List[str]:
    """最近 `days` 个交易日 ✓（**降序** → 返回**升序** ✓）"""
    cur = conn.execute(
        f'SELECT DISTINCT date FROM {TABLE} ORDER BY date DESC LIMIT ?', (int(days),))
    return sorted(str(r[0]) for r in cur.fetchall())


def codes_with_missing(conn: sqlite3.Connection, days: int = 5,
                       warmup: Optional[int] = None) -> List[str]:
    """★ **有"真缺口"的股票清单** ✓（升序 ✓，**排除预热期本该 NULL 的行** ✗）

    【2026-09-28 用户质疑 ✓】"缺口 > 5% ⇒ **全量**重算"✗ —— 触发依据是**最近 `days` 日**
      的真缺口 ✓（范围小 ✓），而处方却是**全市场 × 全历史** ✗ ⇒ **量级不匹配** ✗✓：
        · 实测（2026-09-28 ✓）：最近 5 日缺口 ≈ **2108 / 5191 只** ✓
          ⇒ 无脑全市场 ⇒ **多算 ~3083 只 × 全历史** ✗（纯浪费 ✓，且结果一样 ✓）；
        · 更糟 ✗：`update_recent_days` **刚刚**才把"最近 N 日涉及的股票"全历史重算过一遍 ✓
          ⇒ 自愈再来一遍**同一批** ✗ ⇒ **重复劳动** ✗（用户实测整轮被拖到 ~20 分钟+ ✓）。
      ⇒ 本函数给出**真正需要重算的股票** ✓ ⇒ 自愈只处理它们 ✓
        （**算法不变 ✓ ⇒ 结果逐位相同 ✓**，零口径风险 ✓✓）。

    ⚠️ 口径与 `missing_stats` 的"真缺口"**完全一致** ✗✓：预热期（该行全局序号 ≤ `warmup_bars()` ✓）
      本就该 NULL ✓ ⇒ **不算缺口** ✗（否则次新股会被**每晚**重算 ✗ —— 项目已明确否决 ✗✓）。
    """
    dates = recent_dates(conn, days)
    if not dates:
        return []
    warm = int(warmup if warmup is not None else warmup_bars())
    start, end = dates[0], dates[-1]
    # ⚠️ 判据必须与 `missing_stats` **逐字同源** ✗✓（实测踩到 ✗）：
    #   "该行是否预热"看的是它在**该股整段历史里的序号** ✓
    #     = 窗口之前的根数 + 窗口内该行之前的根数 ✓
    #   ⇒ 若只用"窗口之前的根数"，会把**次新股的窗口内前段**整体当预热 ✗
    #     ⇒ **漏掉真缺口** ✗（触发说"有缺口"✓、自愈却说"无缺口股票"✗ ⇒ 永远修不好 ✗✓）。
    cur = conn.execute(
        f'SELECT DISTINCT k.code FROM {TABLE} k '
        f'WHERE k.date BETWEEN ? AND ? AND k.{ADX_COLUMN} IS NULL '
        f'  AND (SELECT COUNT(*) FROM {TABLE} b '
        f'       WHERE b.code = k.code AND b.date < ?) '
        f'    + (SELECT COUNT(*) FROM {TABLE} i '
        f'       WHERE i.code = k.code AND i.date BETWEEN ? AND ? AND i.date < k.date) '
        f'      >= ? '
        f'ORDER BY k.code', (start, end, start, start, end, warm))
    return [str(r[0]) for r in cur.fetchall()]


def check_null_ratio(conn: sqlite3.Connection, days: int = 5,
                     threshold: float = 0.05) -> Dict:
    """§5.4 自愈判据 ✓：最近 `days` 日的**真缺口比例**是否超阈值 ✓（**只测量** ✗，不重算 ✓）"""
    dates = recent_dates(conn, days)
    if not dates:
        return {'dates': [], 'days': 0, 'exceeded': False, 'missing_ratio': 0.0,
                'missing_rows': 0, 'threshold': float(threshold), 'note': '库内无 K 线日期'}
    st = missing_stats(conn, dates[0], dates[-1])
    st.update({'dates': dates, 'days': len(dates), 'threshold': float(threshold),
               'exceeded': st['missing_ratio'] > float(threshold)})
    return st


def run_selfheal(conn: sqlite3.Connection, days: int = 5, threshold: float = 0.05,
                 auto_backfill: bool = True, **bf_kwargs) -> Dict:
    """§5.4 **自愈** ✓（AC10 ✓）：最近 `days` 日**真缺口** > `threshold` ⇒ **自动全量重算** ✓

    ⚠️ 为什么必须有它 ✗✓：`adx` 是**派生列** ✓，而 `stock_kline` 有 **8+ 个写入方** ✗
    （§5.3 矩阵 ✓）—— 指望"**每个写入方都记得补算**"✗ 是**不可靠**的 ✓
    ⇒ 必须有**兜底** ✓：由日环节**主动发现**缺口并补齐 ✓✓（连"未知/未来新增写入方"✗ 也一并覆盖 ✓）。

    ⚠️ 触发**昂贵** ✗（全量重算 ≈ 分钟级 ✓）⇒ 故：
      · 阈值默认 **5%** ✓（§5.4 ✓）；生产实测**真缺口 = 0** ✓ ⇒ 平时**永不触发** ✓；
      · 只在**日环节**调用一次 ✓；
      · 触发时打 **ERROR** ✓（提示"疑似写入方清空 `adx`"✗，便于追根因 ✓）。
    """
    st = check_null_ratio(conn, days=days, threshold=threshold)
    st['healed'] = False
    if not st.get('exceeded'):
        return st
    logger.error(f'[StockADX] §5.4 自愈触发 ✗：最近 {st["days"]} 日真缺口 '
                 f'{st["missing_rows"]} 行（{st["missing_ratio"]:.2%} > {threshold:.0%}）'
                 f'—— 疑似有 K 线写入方清空了 `{ADX_COLUMN}` ✗（§5.3 矩阵 ✓）⇒ 开始全量重算 ✓')
    # ★★【2026-09-28 用户质疑 ✓】**只重算"真有缺口"的股票** ✗→✓ ★★
    #   用户原话 ✓："缺口 > 5% ⇒ 触发全量 ADX 重算？？**为什么全量，应该只是增量**" ✓
    #   口径澄清 ✓（**为何不能"按行增量"** ✗）：
    #     · `compute()` 用 `utils.technical.ADX` ✓ ⇒ **Wilder 递推** ✗
    #       ⇒ 某行的 ADX 依赖**该行及之前的全部数据** ✓
    #       ⇒ **只补缺失那几行**需要从**该股序列起点**算起 ✗ —— 否则是**错值** ✗
    #       （`update_recent_days` 注释原文 ✓："不是性能取舍，是**正确性** ✗"）；
    #     ⇒ 所以"增量"只能体现在 **① 只挑有缺口的股票** ✓ 与
    #       **② 截短起算历史（近似 ✗ 会破坏逐位一致 ✗，故不做 ✗）** ✓。
    #   本处实施 ① ✓：**算法完全不变** ✓（每只仍从全历史递推 ✓）⇒ **结果逐位相同** ✓，
    #     只是跳过"无缺口"的股票 ✗（实测本次 5191 只中只有 ~2108 只有缺口 ✓ ⇒ 省掉 ~60% ✗✓）。
    codes = codes_with_missing(conn, days=days)
    if not codes:
        st['note'] = '触发但**无"非预热"缺口股票** ⇒ 无需重算 ✓（预热期 NULL 不算缺口 ✓）'
        logger.error('[StockADX] §5.4 自愈：非预热真缺口股票 = 0 ⇒ **跳过重算** ✓')
        return st
    logger.error(f'[StockADX] §5.4 自愈：**只重算真有缺口的 {len(codes)} 只** ✓'
                 f'（跳过无缺口者 ✗ —— 每只仍**从全历史递推** ✓ ⇒ 结果与全量逐位相同 ✓）')
    if not auto_backfill:
        st['note'] = 'auto_backfill=False ⇒ 仅告警 ✓'
        return st
    res = backfill_all(conn, codes=codes, **bf_kwargs)
    st['healed'] = True
    st['backfill'] = {k: res.get(k) for k in
                      ('updated_rows', 'codes', 'next_offset', 'total_codes', 'done')}
    st['failed_codes'] = len(res.get('failed') or {})
    logger.error(f'[StockADX] §5.4 自愈完成 ✓ 重算 {res.get("updated_rows")} 行 '
                 f'（失败 {st["failed_codes"]} 只 ✗）')
    return st


def record_failures(conn: sqlite3.Connection, failed: Dict[str, str],
                    data_type: str = 'stock_adx') -> int:
    """把**单股失败逐条落盘**到 `data_fetch_failure` ✓（§5.5 要求 ✓，2026-09-27 补 ✓）

    ⚠️ 为什么不能只打日志 ✗✓（§5.5 表第 172 行要求"逐条落盘"✗）：`adx` 是**派生列** ✓，
    单股失败会让该股**静默缺失** ✗ —— 日志会被日更噪音淹没 ✗，
    而该表**可查/可重试/可审计** ✓（`resolved` 标记 ✓，既有 `list_failures` / `resolve_failure` ✓）。

    DDL 来自 `data_collectors.base_collector.FAILURE_TABLE_SQL` ✓（**单一事实源** ✓，不另写一份 ✗）。
    """
    if not failed:
        return 0
    try:
        from datetime import datetime as _dt
        from utils.data_collectors.base_collector import FAILURE_TABLE_SQL
        for ddl in FAILURE_TABLE_SQL:
            conn.execute(ddl)
        now = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.executemany(
            'INSERT INTO data_fetch_failure (data_type, key, error, retry_count, '
            'last_try, resolved) VALUES (?,?,?,?,?,0)',
            [(data_type, str(k), str(v)[:500], 0, now) for k, v in failed.items()])
        conn.commit()
        logger.warning(f'[StockADX] 已把 {len(failed)} 只失败登记到 `data_fetch_failure` ✓'
                       f'（data_type={data_type} ✓）')
        return len(failed)
    except Exception as e:                     # 登记失败**不得**影响主流程 ✓
        logger.error(f'[StockADX] 登记失败明细出错 ✗（不影响主流程 ✓）: {e}')
        return 0
