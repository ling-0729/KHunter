# -*- coding: utf-8 -*-
"""回测数据闸门：启动前的**本地数据覆盖校验 + 数据指纹**✓（2026-09-25 定稿）

职责（M1 止血核心 ✓）：
  1. 校验回测所需的本地数据是否齐备：
       ① 交易日历（`trade_calendar` / JSON 缓存，已由 M0 加固 ✓）
       ② 个股资金流向（`stock_moneyflow_daily` ✓）
       ③ 个股基本面（`stock_finance_indicator` ✓）
       ④ 个股事件（`stock_announcement` ✓）
       ⑤ **个股 ADX 覆盖** ✓（`stock_kline.adx` ✓；2026-09-27 §5.2/S2 新增 ✓
          —— ⚠️ 它**只拦"真缺口"** ✗✓：预热期（前 120 根）的 NULL 是**正常**的 ✓）
  2. 缺什么 → **打印缺失清单并终止** ✗（不再静默漂移 ✓；可配置 `strict=False` 降级为告警）
  3. 计算**数据指纹** ✓（各表 行数/日期范围/数值校验和）→ 写入回测结果，便于事后归因 ✓

设计原则：**宁可失败，也不产出"看起来正常"的错误结果** ✗
"""

import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: 资金流向数据表（M0 新建 ✓）
MONEYFLOW_TABLE = 'stock_moneyflow_daily'
#: 基本面表（M2 回填；M1 先做存在性校验 ✓）
FUNDAMENTAL_TABLE = 'stock_finance_indicator'
#: 公告表（**独立新增** ✓，2026-09-25 由 `stock_event` 改名而来 ✓）
#:   ⚠️ 不得再用 `stock_event` ✗ —— 那是 `data/DataSql.sql` 的应用事件表 ✓
#:   （`event_type/event_date/event_title/...` ✓）；曾因表名撞车导致 **web_server 启动崩溃** ✗✓
EVENT_TABLE = 'stock_announcement'
#: 资金流每日最少记录数（低于此视为"该日未采到"✗）
MONEYFLOW_MIN_ROWS_PER_DAY = 500


def _table_exists(conn, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                       (table,)).fetchone()
    return row is not None


def _has_column(conn, table: str, column: str) -> bool:
    try:
        return any(r[1] == column for r in conn.execute(f'PRAGMA table_info({table})'))
    except Exception:
        return False


def _date_col(conn, table: str, candidates: Sequence[str]) -> Optional[str]:
    cols = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    for c in candidates:
        if c in cols:
            return c
    return None


# --------------------------------------------------------------------- 单项校验

def check_moneyflow(conn, trade_dates: Sequence[str],
                    min_rows_per_day: int = MONEYFLOW_MIN_ROWS_PER_DAY,
                    source: Optional[str] = None) -> Dict:
    """资金流向校验 ✓：**按数据源**逐日覆盖 + **支持区间**硬闸门 ✓

    【2026-09-26 方案 C 加固 ✓】两处关键修正 ✗→✓：
      ① **按 `source` 过滤** ✗→✓：表内**同时**存有同花顺（保真 ✓）与东财（备用 ✗）行 ✗，
         若不筛源，东财行会**顶替**同花顺缺失日 ✗ ⇒ "看着齐、实则缺"✗（静默偏差 ✗✓）。
      ② **支持区间硬闸门** ✓：回测起点早于该源**可评分起点** ✗（= 覆盖第 5 个交易日 ✓，
         需攒够 5 日窗口 ✓）⇒ **明确拒绝** ✓，并在报错中给出**支持区间** ✓
         （同花顺只有 2024-12-24 起 ✓；更早区间**暂不支持回测** ✗ —— 绝不静默出结果 ✗）
    """
    from utils.moneyflow_source import (SOURCE_THS, WINDOW_DAYS, resolve,
                                        support_window)
    src = source or resolve()
    item = {'name': '个股资金流向', 'table': MONEYFLOW_TABLE, 'source': src,
            'ok': False, 'missing_dates': [], 'thin_dates': [], 'detail': ''}
    if not _table_exists(conn, MONEYFLOW_TABLE):
        item['detail'] = f'表 {MONEYFLOW_TABLE} 不存在（请先运行资金流数据更新/初始化 ✗）'
        return item
    dates = sorted({str(d) for d in trade_dates})
    if not dates:
        item['detail'] = '未提供交易日列表'
        return item

    win = support_window(conn, src)
    item['support'] = win
    if not win['ready']:
        item['detail'] = (f'数据源 {src} 本地**无任何数据** ✗ —— '
                          f'请先运行资金流初始化/更新 ✓'
                          + (f'（该源理论起点 {win["supported_start"]} ✓）'
                             if win.get('supported_start') else ''))
        return item

    # ① 支持区间硬闸门 ✓（起点必须已攒够 5 日窗口 ✓）
    if dates[0] < win['ready_start']:
        hint = (f'数据源 {src} 的**可评分起点**为 {win["ready_start"]} ✓'
                f'（覆盖 {win["covered_start"]} ~ {win["covered_end"]}，'
                f'{win["days"]} 个交易日 ✓；需预热 {WINDOW_DAYS} 日窗口 ✓）'
                + (f'；该源理论起点 {win["supported_start"]} ✓' if win.get('supported_start') else '')
                + (f'。同花顺自 {win["supported_start"]} 起提供数据 ✓，'
                   f'更早区间**暂不支持回测** ✗' if src == SOURCE_THS else ''))
        item['detail'] = (f'回测起点 {dates[0]} **早于**该源的可评分起点 '
                          f'{win["ready_start"]} ✗ —— {hint}。请把起点调整到 '
                          f'{win["ready_start"]} 之后 ✓（否则首日 5 日窗口凑不满 ✗，'
                          f'评分将不可复现 ✗）')
        return item

    # ② 逐日覆盖 ✓（**按源过滤** ✓）
    placeholders = '?' * 0
    cur = conn.execute(
        f'SELECT trade_date, COUNT(*) FROM {MONEYFLOW_TABLE} '
        f'WHERE source=? AND trade_date BETWEEN ? AND ? GROUP BY trade_date',
        (src, dates[0], dates[-1]))
    rows_by_day = {str(r[0]): int(r[1]) for r in cur.fetchall()}
    item['missing_dates'] = [d for d in dates if d not in rows_by_day]
    item['thin_dates'] = [d for d in dates if rows_by_day.get(d, 0) and
                          rows_by_day[d] < min_rows_per_day]
    item['days_expected'] = len(dates)
    item['days_present'] = len([d for d in dates if d in rows_by_day])
    item['ok'] = not item['missing_dates'] and not item['thin_dates']
    if not item['ok']:
        parts = []
        if item['missing_dates']:
            parts.append(f'[{src}] 缺 {len(item["missing_dates"])} 天: '
                         f'{", ".join(item["missing_dates"][:10])}')
        if item['thin_dates']:
            parts.append(f'[{src}] {len(item["thin_dates"])} 天记录过少(<{min_rows_per_day}): '
                         f'{", ".join(item["thin_dates"][:10])}')
        item['detail'] = '；'.join(parts)
    return item


def check_fundamental(conn, start: str, end: str, max_stale_days: int = 200) -> Dict:
    """基本面校验 ✓：表存在 + 具备 `ann_date` + **起点可用最近一期**不早于区间 ✓

    【2026-09-25 M4 修复·误判 ✗→✓】原判据是 `最新公告日 < 起点 ⇒ 失败` ✗ ——
    财报是**季度低频**数据 ✓，5 个交易日的窗口**不可能**含新财报 ✗ ⇒
    任何短窗口回测都会被闸门**误拦** ✗✓（M4 验收实测到此问题 ✓）。

    正确语义 ✓（"时点可用性"，而非"区间内必须有新财报" ✗）：
      ① 最新一期公告日必须 **≤ 今天** ✓（**2026-09-27 修正** ✗→✓：原为"≤ 回测终点"✗ ——
         本表是**序列** ✓、消费侧按 `ann_date <= 选股日` **时点对齐** ✓ ⇒
         终点之后的行**不会被读到** ✓；原判据把**任何历史回测**都拦掉了 ✗✗）
      ② 起点之前（含）**存在**可用财报（否则起点无法做时点对齐 ✗）
      ③ 该可用财报距起点**不超过** `max_stale_days`（默认 200 天 ≈ 两个报告期 ✓，
         防"本地只到两年前"✗ 这种**过旧数据**静默通过 ✗）
    """
    item = {'name': '个股基本面', 'table': FUNDAMENTAL_TABLE, 'ok': False, 'detail': ''}
    if not _table_exists(conn, FUNDAMENTAL_TABLE):
        item['detail'] = (f'表 {FUNDAMENTAL_TABLE} 不存在（请先运行基本面初始化/更新 ✗）')
        return item
    if not _has_column(conn, FUNDAMENTAL_TABLE, 'ann_date'):
        item['detail'] = (f'{FUNDAMENTAL_TABLE} 缺少 `ann_date` 列 ✗ —— '
                          f'时点规则要求 `ann_date <= 选股日`（防前视偏差 ✓）')
        return item
    n = conn.execute(f'SELECT COUNT(*) FROM {FUNDAMENTAL_TABLE}').fetchone()[0]
    if not n:
        item['detail'] = f'{FUNDAMENTAL_TABLE} 为空（尚无财报数据 ✗）'
        return item
    latest = conn.execute(f'SELECT MAX(ann_date) FROM {FUNDAMENTAL_TABLE}').fetchone()[0]
    item['rows'] = int(n)
    item['latest_ann_date'] = latest
    # ① 不得"未来化"✗ —— ★ **基准是"今天"** ✓（**2026-09-27 修正** ✗→✓）
    #   · 原实现拿**回测终点**当基准 ✗ ⇒ **任何历史回测都会被拦** ✗✗ ——
    #     本表是**序列** ✓（实测 62677 行 / 5276 股 ≈ 每股 12 期季度财报 ✓，
    #     公告日 2023-10 ~ 2026-09 连续 ✓）⇒ 天然含"回测终点之后"的数据 ✓；
    #   · 而消费侧是**时点对齐** ✓（`trading/fundamental_scorer._fetch_fina_indicator_local` ✓
    #     只取 `ann_date <= 选股日` 的**最新一期** ✓，其 docstring 明写"防前视偏差"✓）
    #     ⇒ 终点之后的行**永不会被读到** ✓ ⇒ **不构成前视** ✗✓；
    #   · ★ **实测代价** ✗✓：`run_adx_ab.py` 的 `2025H1` 段被原判据**误拦** ✗
    #     （`max(ann_date)=2026-09-02 > 末点 2025-06-30` ✗）⇒ M7 根本跑不起来 ✗。
    #   · ⇒ 只拦**相对"今天"也在未来**的数据 ✓（那才是真脏数据 ✗）。
    from datetime import datetime as _dt2
    _today = _dt2.now().strftime('%Y-%m-%d')
    if latest and str(latest)[:10] > _today:
        item['detail'] = (f'最新公告日 {latest} **晚于今天 {_today}** ✗ ⇒ 疑似"未来数据"'
                          f'（时点规则被破坏 ✗，请检查采集/落库的时点口径 ✓）')
        return item
    # ② 起点可用最近一期 ✓
    usable = conn.execute(f'SELECT MAX(ann_date) FROM {FUNDAMENTAL_TABLE} '
                          f'WHERE ann_date <= ?', (start,)).fetchone()[0]
    item['usable_ann_date'] = usable
    if not usable:
        item['detail'] = (f'{FUNDAMENTAL_TABLE} 在起点 {start} 之前**无可用财报** ✗ ⇒ '
                          f'起点无法做时点对齐（请补齐更早期数据 ✓）')
        return item
    # ③ 过旧数据不得静默通过 ✗
    try:
        from datetime import datetime as _dt
        gap = (_dt.strptime(str(start)[:10], '%Y-%m-%d')
               - _dt.strptime(str(usable)[:10], '%Y-%m-%d')).days
    except Exception:
        gap = 0
    item['usable_gap_days'] = gap
    if gap > max_stale_days:
        item['detail'] = (f'起点可用财报为 {usable}（距起点 {gap} 天 > {max_stale_days} ✗）⇒ '
                          f'疑似数据过旧，请运行基本面更新 ✓')
        return item
    item['ok'] = True
    return item


def check_event(conn, start: str, end: str) -> Dict:
    """事件校验（M1 从轻 ✓）：表存在 + 区间内有公告标题 ✓"""
    item = {'name': '个股事件(公告)', 'table': EVENT_TABLE, 'ok': False, 'detail': ''}
    if not _table_exists(conn, EVENT_TABLE):
        item['detail'] = f'表 {EVENT_TABLE} 不存在（请先运行公告初始化/更新 ✗）'
        return item
    date_col = _date_col(conn, EVENT_TABLE, ('ann_date', 'trade_date', 'date'))
    if not date_col:
        item['detail'] = f'{EVENT_TABLE} 缺少日期列（ann_date ✗）'
        return item
    n, first_d, last_d = conn.execute(
        f'SELECT COUNT(*), MIN({date_col}), MAX({date_col}) FROM {EVENT_TABLE} '
        f'WHERE {date_col} BETWEEN ? AND ?', (start, end)).fetchone()
    latest = conn.execute(f'SELECT MAX({date_col}) FROM {EVENT_TABLE}').fetchone()[0]
    item['rows_in_range'] = int(n or 0)
    item['latest_ann_date'] = latest
    # 【2026-09-25 M4 修复·误判 ✗→✓】判据改为**覆盖语义** ✓：
    #   原判据"区间内必须有公告" ✗ 对短窗口可能误拦 ✗（例如长假前后 ✓）。
    #   正确做法 ✓：本地表对该区间的**覆盖是否连续完整** ✓ ——
    #   即"该区间确实落在本地已采集范围内" ✓；区间内 0 条才可能是**合法的空窗** ✓。
    #   注：**逐日**完整性由采集器 `verify_coverage` 负责 ✓（此处只看区间覆盖 ✓）。
    cover_first = conn.execute(f'SELECT MIN({date_col}) FROM {EVENT_TABLE}').fetchone()[0]
    covered = bool(cover_first) and str(cover_first)[:10] <= str(start) and \
        bool(latest) and str(latest)[:10] >= str(end)
    item['covered'] = covered
    item['cover_range'] = f'{cover_first} ~ {latest}'
    # 判据取**并集** ✓：区间内有记录 ✓ **或** 覆盖范围包含区间 ✓
    #   · 有记录 → 显然已采集 ✓
    #   · 无记录但覆盖完整 → **合法空窗** ✓（例如长假前后 ✓）
    #   · 无记录且覆盖不足 → 判定未采集 ✗（这才是真正的"缺数据" ✓）
    if int(n or 0) > 0:
        item['ok'] = True
        return item
    if covered:
        logger.warning(f'{EVENT_TABLE} 区间 {start} ~ {end} 内 0 条公告 ✓ '
                       f'（覆盖完整 {cover_first} ~ {latest} ⇒ 判定为合法空窗 ✓）')
        item['ok'] = True
        return item
    item['detail'] = (f'{EVENT_TABLE} 区间 {start} ~ {end} 内 0 条公告 ✗，且本地覆盖 '
                      f'{cover_first} ~ {latest} **未包含**该区间 ✗ ⇒ 疑似未采集 ✗')
    return item


def check_calendar(trade_dates: Sequence[str]) -> Dict:
    """交易日历校验：由调用方传入已加载的交易日列表 ✓（M0 已做完整性自检 ✓）"""
    dates = sorted({str(d) for d in trade_dates})
    item = {'name': '交易日历', 'ok': bool(dates), 'days': len(dates),
            'first': dates[0] if dates else None, 'last': dates[-1] if dates else None,
            'detail': '' if dates else '交易日历为空 ✗（请先运行数据更新）'}
    return item


def check_adx(conn, start: str, end: str, max_missing_ratio: float = 0.01) -> Dict:
    """个股 ADX 覆盖校验 ✓（§5.2 / §5.4 S2 ✓；2026-09-27 新增 ✓）

    **判据的关键 ✗✓**：`adx IS NULL` **不等于**"缺数据" ✗ ——
    §5.2 定稿：每只股票的**前 120 根**（预热期 ✓）**本就该是 NULL** ✓
    （归因 `not_applicable` ✓，次新股该规则**不适用** ✓ ⇒ 放行 ✓）。
    若直接拿"NULL 比例"当缺口 ✗ ⇒ **整库常年报 12% 缺口** ✗
    （实测：`632,173 / 5,289,071` ✗）⇒ 闸门沦为噪音 ✗ ⇒ 最后必被 `skip` 掉 ✗✓（= 闸门失效 ✗）。

    ⇒ 故此处做**精确归因** ✓：
      `预期 NULL` = Σ_股票 `clamp(120 − 该股在 start 之前的根数, 0, 区间内根数)` ✓
      （即"该股落在区间内、且**全局序号 ≤ 120** 的那些行" ✓）
      `真缺口 = 实际 NULL − 预期 NULL` ✓ —— 这才是**该算却没算** ✗（被写入方清空 ✗）。

    Args:
        max_missing_ratio: 真缺口占"应算行"的**容忍比例** ✓（默认 **1%** ✓；
            实测生产库缺口为 **0** ✓ ⇒ 正常回测必过 ✓；确有写入方清空则立即报错 ✗）
    """
    from utils.adx_reference import warmup_bars
    from utils.stock_adx import ADX_COLUMN, TABLE

    warm = warmup_bars()
    item = {'name': '个股 ADX 覆盖', 'table': TABLE, 'ok': False,
            'warmup_bars': warm, 'detail': ''}
    if not _table_exists(conn, TABLE):
        item['detail'] = f'表 {TABLE} 不存在（请先初始化/更新 K 线 ✗）'
        return item
    if not _has_column(conn, TABLE, ADX_COLUMN):
        item['detail'] = (f'{TABLE} 缺 `{ADX_COLUMN}` 列 ✗ —— 启动迁移本应自动补列 ✓'
                          f'（`schema_migrations.migrate_stock_kline_adx` ✓）；'
                          f'请重启服务，或直接调用 `utils.stock_adx.ensure_column` ✓')
        return item
    # 【2026-09-27】归因逻辑**下沉到 `utils/stock_adx.missing_stats`** ✓（**单一事实源** ✓）：
    #   同一套判据还被 §5.4 **自愈**（`stock_adx.run_selfheal` ✓）使用 ✓ ——
    #   若两处各写一份 ✗，闸门与自愈会**对"缺口"给出不同口径** ✗✓（迟早漂移 ✗）。
    try:
        from utils.stock_adx import missing_stats
        st = missing_stats(conn, start, end, warmup=warm)
    except Exception as e:
        item['detail'] = f'统计 {TABLE}.{ADX_COLUMN} 失败 ✗: {e}'
        return item
    if not st['rows']:
        item['detail'] = f'区间 {start} ~ {end} 内无 K 线数据 ✗'
        return item
    item.update(st)
    item['max_missing_ratio'] = max_missing_ratio
    item['ok'] = st['missing_ratio'] <= max_missing_ratio
    if not item['ok']:
        item['detail'] = (f'区间内 `{ADX_COLUMN}` **真缺口** {st["missing_rows"]} 行 ✗'
                          f'（占应算 {st["missing_ratio"]:.2%} > 容忍 {max_missing_ratio:.2%} ✓）——'
                          f'疑似被 K 线写入方清空 ✗（§5.3 覆盖矩阵 ✓）；'
                          f'请执行一次全量重算 ✓：'
                          f'`utils/stock_adx.py::backfill_all` ✓')
    return item


#: 大盘指数 ADX 表 ✓（降温状态机**唯一**数据源 ✓；与 `MarketIndexADXDAO.TABLE` 同表 ✓）
INDEX_ADX_TABLE = 'market_index_adx'
#: 默认指数 ✓（中证全指 ✓；与 `config/regime_router.yaml::index_code` ✓、
#: 以及回填脚本 `_backfill_index_adx.py` 口径一致 ✓）
INDEX_ADX_DEFAULT_CODE = '000985.CSI'
#: 状态机**预热**建议交易日数 ✓（经验值 ✓：少于它时"上次降温"可能落在数据之外 ✗
#: ⇒ 起点档位**不可复现** ✗）
INDEX_ADX_MIN_WARMUP_DAYS = 120


def check_index_adx(conn, start: str, end: str, required: bool = False,
                    min_warmup_days: int = INDEX_ADX_MIN_WARMUP_DAYS,
                    index_code: str = INDEX_ADX_DEFAULT_CODE) -> Dict:
    # ⚠️【2026-10-05 适配 ✓】本函数**已按 `index_code` 单指数校验** ✓ —— 多指数适配由
    #   **调用方** `run_gate(index_codes=[...])` 负责 ✓（主指数 required 语义不变 ✓，
    #   板块指数 2..n 只提醒 ✓）；默认值仍为 `000985.CSI` ✓（保持向后兼容 ✓）。
    """**大盘指数 ADX 覆盖 + 状态预热**校验 ✓（§5.6 / §5.8 ✓；2026-09-27 新增 ✓）

    ⚠️ **与个股 `check_adx` 的本质不同** ✗✓：这里拦的不是"NULL 缺口"✗，而是
    **「状态机的可复现性」** ✗✓ —— §5.6/§5.8 定稿：

        状态**路径依赖** ⇒ **ADX 数据起点 ≤ 回测起点** ✓，否则**明确拒绝** ✗（不静默 ✓）

    **为什么必须拦** ✗✓（实测）：`RegimeRouter` 的 `band/dir/cooled` 是**逐日递推**的 ✓ ⇒
    若 ADX 数据**从回测起点才开始** ✗，首日状态是"空"的 ✗ ⇒ **同一天、同一 ADX 得出不同 regime** ✗✓
    （本库原起点 `2025-01-02` ✗ ⇒ 2025H1 段起点即首日 ⇒ 档位不可复现 ✗；
     2026-09-27 已回填至 `2020-01-02` ✓（1633 天 ✓），三段起点均**不在降温期中** ✓✓）。

    Args:
        required: **是否硬拦** ✓ —— 由**调用方**按"本策略是否走大盘路由"决定 ✓：
            · 有 `RegimeRouter` 的引擎（`RegimeBacktestEngine` ✓）⇒ `required=True` ⇒ 不达标**失败** ✗；
            · 普通 `BacktestEngine`（无 router ✓）⇒ `required=False` ⇒ **只提醒不拦** ✓
              （大盘 ADX 与该策略无关 ✗ ⇒ 硬拦属**误伤** ✗）
        min_warmup_days: 起点**之前**至少需多少交易日 ✓（默认 120 ✓）
        index_code: 与路由配置一致 ✓（默认 `000985.CSI` ✓）
    """
    item = {'name': '大盘指数 ADX（状态预热 ✓）', 'table': INDEX_ADX_TABLE,
            'ok': True, 'required': bool(required), 'index_code': index_code,
            'warn': False, 'detail': ''}

    def _fail(detail: str) -> Dict:
        """**统一的不达标出口** ✓：`required=False` ⇒ **只提醒、不阻断** ✓

        ⚠️ 为什么**所有**失败模式都要走这里 ✗✓（实测踩到 ✗）：若"表不存在"直接判失败 ✗，
        则**没挂路由的普通回测**（`required=False` ✓）也会被拦 ✗ —— 属**误伤** ✗
        （大盘 ADX 与该策略无关 ✗）。
        """
        item['ok'] = not required
        item['warn'] = not required
        item['detail'] = ('（本策略未走大盘路由 ⇒ 不阻断 ✓）' + detail
                          if not required else detail)
        return item

    if not _table_exists(conn, INDEX_ADX_TABLE):
        return _fail(f'表 {INDEX_ADX_TABLE} 不存在 ✗')
    s, e = str(start).replace('-', ''), str(end).replace('-', '')
    try:
        head = conn.execute(
            f'SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM {INDEX_ADX_TABLE} '
            f'WHERE index_code = ?', (index_code,)).fetchone()
        inr = conn.execute(
            f'SELECT COUNT(*), SUM(CASE WHEN adx IS NULL THEN 1 ELSE 0 END) '
            f'FROM {INDEX_ADX_TABLE} WHERE index_code = ? '
            f'AND trade_date BETWEEN ? AND ?', (index_code, s, e)).fetchone()
        pre = conn.execute(
            f'SELECT COUNT(*) FROM {INDEX_ADX_TABLE} WHERE index_code = ? '
            f'AND trade_date < ?', (index_code, s)).fetchone()[0]
    except Exception as ex:
        return _fail(f'统计 {INDEX_ADX_TABLE} 失败 ✗: {ex}')

    total, first, last = int(head[0] or 0), head[1], head[2]
    in_rows, in_nulls = int(inr[0] or 0), int(inr[1] or 0)
    pre = int(pre or 0)
    item.update({'rows': total, 'first_date': first, 'last_date': last,
                 'rows_in_range': in_rows, 'null_in_range': in_nulls,
                 'pre_start_days': pre, 'min_warmup_days': int(min_warmup_days)})

    # ① 区间内**必须有数据** ✓（否则回测里 router 会一路 stale ✗）
    if not total or not in_rows:
        item['warmup_ok'] = False
        return _fail(f'区间 {s} ~ {e} 内无 {index_code} 的 ADX ✗（表内共 {total} 行 ✓）')

    # ② **起点覆盖 + 预热** ✓（§5.6「数据起点 ≤ 回测起点」✓）
    warm_ok = (first is not None and str(first) <= s) and pre >= int(min_warmup_days)
    item['warmup_ok'] = bool(warm_ok)
    if not warm_ok:
        why = (f'数据起点 {first} ✗ **晚于**回测起点 {s} ✗'
               if (first is None or str(first) > s) else
               f'起点前仅 {pre} 个交易日 ✗ < 需 {min_warmup_days} ✓')
        return _fail(
            f'【状态预热不足 ✗】{why} ⇒ `RegimeRouter` 的 `band/dir/cooled` '
            f'**不可复现** ✗（同一天同一 ADX 会得出不同 regime ✗）。'
            f'请先回填指数 ADX 历史 ✓（详见设计说明书 §5.8 ✓）：'
            f'`python tools/backfill_index_adx.py` ✓（**复用** `MarketIndexADX.calculate()` '
            f'同一口径 ✓、**只增不改** ✓、带交叉验证 ✓）')
    return item


# --------------------------------------------------------------------- 指纹

def fingerprint_tables(conn, tables: Dict[str, Dict]) -> Dict:
    """计算数据指纹 ✓（用于结果归因："这次结果和上次不同，是数据变了吗？"）

    Args:
        tables: {逻辑名: {'table': 表名, 'date_col': 日期列, 'value_col': 数值列(可空)}}

    Returns:
        {逻辑名: {'table','rows','date_min','date_max','hash'}}
    """
    out: Dict[str, Dict] = {}
    for name, spec in tables.items():
        table = spec['table']
        entry = {'table': table}
        if not _table_exists(conn, table):
            entry.update({'rows': 0, 'hash': 'absent'})
            out[name] = entry
            continue
        date_col = spec.get('date_col') or _date_col(conn, table, ('trade_date', 'date'))
        try:
            rows = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            dmin = dmax = None
            if date_col:
                dmin, dmax = conn.execute(
                    f'SELECT MIN({date_col}), MAX({date_col}) FROM {table}').fetchone()
            value_col = spec.get('value_col')
            h = hashlib.md5()
            h.update(f'{table}|{rows}|{dmin}|{dmax}'.encode('utf-8'))
            if value_col and _has_column(conn, table, value_col):
                agg = conn.execute(
                    f'SELECT ROUND(SUM({value_col}), 2) FROM {table}').fetchone()[0]
                h.update(f'|{agg}'.encode('utf-8'))
            entry.update({'rows': int(rows), 'date_min': dmin, 'date_max': dmax,
                          'hash': h.hexdigest()[:16]})
        except Exception as e:
            entry.update({'rows': -1, 'hash': 'error', 'error': str(e)[:100]})
        out[name] = entry
    return out


def default_fingerprint_specs() -> Dict[str, Dict]:
    """回测关心的表清单（含 K 线 → 让"K 线是否变过"显性可查 ✓）"""
    return {
        'kline': {'table': 'stock_kline', 'date_col': 'date', 'value_col': 'close'},
        # 【2026-09-27 §5.2 / M3-c ✓】**`adx` 也必须入指纹** ✗✓
        #   理由 ✓：ADX 已是**策略输入** ✓（个股闸门 §5.6 ✓ ＋ 大盘档位 §5.8 ✓）⇒
        #     它变了 ⇒ 结果就**不可直接比较** ✗ —— 若**不入**指纹 ✗，会出现
        #     "**数据版本相同、但 ADX 不同**"✗ 的两份结果被当成**可比** ✗✓（静默误判 ✗）。
        #   ⚠️ 影响 ✗（**须知情** ✓）：新增本项会**改变 `data_version`** ✗ ⇒
        #     与**既有历史结果判为不可比** ✗✓（这正是本项的目的 ✓ —— 旧结果**重跑一次**即恢复可比 ✓）。
        #   实现备注 ✓：`fingerprint_tables` 用 `SUM(value_col)` ✓，SQL 的 `SUM` **自动忽略 NULL** ✓
        #     ⇒ 预热期那 63 万行 NULL **不会**干扰哈希 ✓。
        'kline_adx': {'table': 'stock_kline', 'date_col': 'date', 'value_col': 'adx'},
        'moneyflow': {'table': MONEYFLOW_TABLE, 'date_col': 'trade_date',
                      'value_col': 'net_amount'},
        'fundamental': {'table': FUNDAMENTAL_TABLE, 'date_col': 'ann_date'},
        'event': {'table': EVENT_TABLE, 'date_col': 'ann_date'},
    }


# --------------------------------------------------------------------- 主入口

def _today_hint(missing: Sequence[str], end: str, now=None) -> str:
    """缺**今天**时追加的**可执行**指引 ✓；否则返回 `''` ✓（纯文案 ✓，不参与任何判定 ✗）

    背景 ✗✓（2026-09-28 用户实测 ✓）：08:47（周一·**开盘前** ✗）跑回测 ⇒
      闸门报 `[moneyflow_ths] 缺 1 天: 2026-09-28` ✗ + 原文案"请运行数据更新"✗ ——
      而**当日数据**（资金流 / K 线 / 大盘 ADX ✓）**收盘后**才采集入库 ✗
      ⇒ 此刻去跑"数据更新"**同样取不到** ✗✓（**无效指引** ✗，用户会被误导 ✗）。

    ⇒ 命中"含今天 / 终点=今天"时 ✓，给出两条**真出路** ✓：
      ① 把**回测终点**改到上一交易日 ✓（引擎入口**已自动回退** ✓）；
      ② 待 **15:01 之后**并跑完"数据更新"再跑 ✓。

    ⚠️ 缺**历史**日期 ⇒ **不**命中 ✓ ⇒ 保持原文案 ✓（那才是**真缺数据** ✗，
    继续由闸门如实拦下 ✓，**绝不**用"今天还没收盘"来掩盖 ✗）。
    """
    now = now or datetime.now()
    today = now.strftime('%Y-%m-%d')
    today_c = today.replace('-', '')
    hit = (any(today in m or today_c in m for m in missing)
           or str(end)[:10] == today or str(end)[:8] == today_c)
    if not hit:
        return ''
    prev = ''
    try:
        from utils.trade_date_utils import get_previous_trading_day
        prev = get_previous_trading_day(today)
    except Exception:
        prev = ''
    return (f'\n  ⚠️ 其中含**今天 {today}** ✗ —— 当日数据（资金流/K线/大盘ADX ✓）'
            f'**收盘后才采集入库** ✓，现在（{now:%H:%M}）**不可能有** ✗'
            f'（此刻跑"数据更新"**也取不到** ✗）。\n'
            f'  二选一 ✓：① 把**回测终点**改到**上一交易日**'
            f'{(" " + prev) if prev else ""} ✓；'
            f'② 待 **15:01 之后**、并跑完"数据更新"再跑 ✓'
            f'（回测引擎**已在入口自动回退** ✓：'
            f'`utils/trade_date_utils.resolve_end_date_for_data` ✓）')


def run_gate(conn, start: str, end: str, trade_dates: Sequence[str],
             strict: bool = True, min_rows_per_day: int = MONEYFLOW_MIN_ROWS_PER_DAY,
             skip: Optional[Sequence[str]] = None,
             index_adx_required: bool = False,
             index_codes: Optional[Sequence[str]] = None) -> Dict:
    """回测启动闸门：校验各类本地数据 → 返回报告（strict 时缺失即抛错 ✗）

    Args:
        conn: sqlite3 连接
        start / end: 回测区间（YYYY-MM-DD）
        trade_dates: **实际会跑到的交易日列表**（来自已加载的本地日历 ✓）
        strict: True = 有缺失立即抛 RuntimeError ✗（默认 ✓）
        min_rows_per_day: 资金流每日最少记录数阈值
        skip: 需要跳过的校验项名（如 ['fundamental']，用于尚未迁移完成的阶段 ✓）

    Returns:
        dict: {'ok': bool, 'strict': bool, 'items': {...}, 'missing': [...],
               'fingerprint': {...}}

    Raises:
        RuntimeError: strict=True 且校验不通过 ✗
    """
    skip = set(skip or ())
    items: Dict[str, Dict] = {}
    if 'calendar' not in skip:
        items['calendar'] = check_calendar(trade_dates)
    if 'moneyflow' not in skip:
        items['moneyflow'] = check_moneyflow(conn, trade_dates, min_rows_per_day)
    if 'fundamental' not in skip:
        items['fundamental'] = check_fundamental(conn, start, end)
    if 'event' not in skip:
        items['event'] = check_event(conn, start, end)
    # 【2026-09-27 §5.2/S2】个股 ADX 覆盖 ✓（**只拦"真缺口"** ✓；预热期 NULL **不算缺** ✓）
    if 'adx' not in skip:
        items['adx'] = check_adx(conn, start, end)
    # 【2026-09-27 §5.6/§5.8】大盘指数 ADX **起点覆盖 + 状态预热** ✓
    #   `required` 由调用方给 ✓（有 `RegimeRouter` 的引擎才硬拦 ✗ ⇒ 不误伤普通回测 ✓）
    if 'index_adx' not in skip:
        # ★★【2026-10-05 适配 ✓】**按"实际会用到的指数"校验** ✗→✓ ★★
        #   原实现恒校验 `000985.CSI` ✗ ⇒ 若把 `index_adx_code` / 路由指数改成别的 ✗
        #     ⇒ **真正判档的那个指数反而没做「起点覆盖 + 120 日预热」校验** ✗
        #     ⇒ 档位不可复现却**静默放行** ✗✓（这正是本闸门要拦的东西 ✗）。
        #   现 ✓：`index_codes[0]` = 主指数 ✓（`required` 语义**完全不变** ✓）；
        #     其余 = **板块回退**用的板块指数 ✓ ⇒ **只提醒不阻断** ✓
        #     （它们只是"全A 兜底时的回退路径"✗ ⇒ 硬拦会误伤"全A 放行"的正常回测 ✗✓），
        #     但**必须记 WARNING** ✓（缺数据 ⇒ 该板块**静默不放行** ✗ ⇒ 绝不无声 ✗）。
        _codes = [str(c).strip() for c in (index_codes or [INDEX_ADX_DEFAULT_CODE])
                  if str(c).strip()]
        _primary = _codes[0] if _codes else INDEX_ADX_DEFAULT_CODE
        items['index_adx'] = check_index_adx(conn, start, end,
                                             required=index_adx_required,
                                             index_code=_primary)
        for _c in _codes[1:]:
            if _c == _primary or ('index_adx:' + _c) in items:
                continue
            _it = check_index_adx(conn, start, end, required=False, index_code=_c)
            _it['name'] = f'大盘指数 ADX（板块回退用 ✓ {_c}）'
            _it['board_fallback_index'] = True
            items['index_adx:' + _c] = _it
            if _it.get('warn'):
                logger.warning(f'【回测数据闸门】板块回退指数 {_c} 未达标 ✓（**不阻断** ✓）：'
                               f'{_it.get("detail")}')

    missing: List[str] = []
    for key, item in items.items():
        if not item.get('ok'):
            missing.append(f'{item["name"]}({item["table"] if "table" in item else "日历"})'
                           f'：{item.get("detail") or "覆盖不足"}')

    report = {
        'ok': not missing,
        'strict': bool(strict),
        'start': start,
        'end': end,
        'trade_days': len(trade_dates),
        'items': items,
        'missing': missing,
        'fingerprint': fingerprint_tables(conn, default_fingerprint_specs()),
    }
    if missing:
        head = (f'【回测数据闸门】数据校验未通过 ✗（{len(missing)} 项）')
        body = '\n'.join(f'  · {m}' for m in missing)
        tail = '  处理：请先运行"数据更新/初始化"补齐本地数据（回测不联网 ✗）'
        # ★【2026-09-28】若缺的正是**今天** ⇒ 追加**可执行**指引 ✓（见 `_today_hint` ✓）
        #   原文案会**误导** ✗✓（用户实测 08:47 开盘前跑回测 ✗）：当日数据（资金流 /
        #   K 线 / 大盘 ADX ✓）**收盘后**才采集入库 ✗ ⇒ 此刻"去运行数据更新"**也取不到** ✗
        #   ⇒ 必须给出"改终点 / 等收盘"两条**真出路** ✓。
        tail += _today_hint(missing, end)
        report['message'] = f'{head}\n{body}\n{tail}'
        if strict:
            raise RuntimeError(report['message'])
        logger.error(report['message'])
    else:
        logger.info(f'【回测数据闸门】校验通过 ✓ 区间 {start} ~ {end}，'
                    f'{len(trade_dates)} 个交易日；指纹已生成 ✓')
    return report
