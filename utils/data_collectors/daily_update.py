# -*- coding: utf-8 -*-
"""**每日数据更新编排**（四类本地数据 ✓，2026-09-25 定稿）

一次调用完成（与设计说明书 §3/§5 一致 ✓）：
  ① 交易日历 → 落库（`trade_calendar` ✓，离线 ✓）
  ② 个股资金流向 → **滚动重采最近 3 个交易日** ✓（**按配置数据源** ✓，
    默认 **同花顺 `moneyflow_ths`** ✓ = 保真口径 ✓；见 `utils/moneyflow_source.py` ✓）
  ③ 个股基本面 → **公告驱动**：最近 3 个交易日里发了"报告/业绩"类公告的股票，
     强制重采其全部历史财务指标 ✓（新财报当天即可用 ✓）
  ④ 个股事件 → 最近 3 个交易日的全市场公告标题 ✓（只留标题 ✓）

设计要点：
  · **接口可注入**（`dc_fetcher` / `cninfo_fetcher` / `fina_fetcher`）→ 便于离线单元测试 ✓
  · 各域**独立失败**：某域异常不影响其它域，但结果里**如实标记** ✓（不静默 ✗）
  · 日历读取一律 `prefer_db=False`（读缓存文件，而非刚写的表 ✓）
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: 默认增量窗口（交易日 ✓，与"数据更新滚动重采近 3 个交易日"定稿一致）
DEFAULT_WINDOW = 3

#: 触发基本面重采的公告标题关键词（报告期类 ✓）
REPORT_TITLE_KEYWORDS = ('报告', '业绩', '快报', '财报')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def resolve_update_window(conn, window: int = DEFAULT_WINDOW):
    """解析更新窗口：返回 (全部可用交易日, 最近 window 个交易日) ✓

    Raises:
        RuntimeError: 本地交易日历不可用 ✗
    """
    from utils.local_calendar import load_local_trade_dates
    dates = [d for d in load_local_trade_dates(conn, prefer_db=False) if d <= _today()]
    if not dates:
        raise RuntimeError('本地交易日历为空（请先运行数据更新/补齐日历 ✗）')
    return dates, dates[-max(1, int(window)):]


def _sync_calendar(conn, state_dir: Optional[str]) -> Dict:
    """① 交易日历落库（离线 ✓）"""
    from utils.data_collectors.local_data_collectors import CalendarCollector
    cc = CalendarCollector(conn, state_dir=state_dir)
    cc.ensure_schema()
    return cc.sync_from_local_cache()


def _moneyflow_effective_dates(recent: Sequence[str],
                               now=None) -> Tuple[List[str], Optional[str]]:
    """资金流**有效窗口** ✓：把"**今日且未收盘**"从窗口里剔除 ✗→✓

    ★【2026-09-29 用户反馈 ✓】实测 ✗✓（用户日志 ✓）：09-29 **09:25** 跑更新 ⇒
      窗口末日 = **今日（尚未收盘）** ✗ ⇒ 资金流**当日数据源端未出** ✓ ⇒
      采集器把它记成 `failed: 1` ✗ ⇒ `daily_update` 判**整域失败** ✗ ⇒
      日志出现 `每日更新[moneyflow]部分/全部失败 ✗` ✗ ⇒ 用户合理判为
      "**资金流向更新失败**"✗（其实**当日数据本就不存在** ✓，且 09-28 已补上 ✓）。

    ⇒ 现：**未收盘的今日直接顺延** ✓（收盘后重跑自动补 ✓），且**不计失败** ✗✓。
    ⚠️ 只作用于**资金流** ✓（公告/财报盘中就有 ✓，不剔除 ✓）。
    """
    dates = [str(d) for d in recent]
    try:
        if now is None:
            from datetime import datetime as _dt
            now = _dt.now()
        today = now.strftime('%Y-%m-%d')
        if dates and dates[-1] == today and now.strftime('%H:%M') < '15:01':
            return dates[:-1], today
    except Exception as e:
        logger.debug('资金流"今日未收盘"判定失败（按不剔除处理 ✓）: %s', e)
    return dates, None


def _update_moneyflow(conn, recent: Sequence[str], state_dir: Optional[str],
                      fetcher=None, window: int = DEFAULT_WINDOW,
                      source: Optional[str] = None) -> Dict:
    """② 资金流向：滚动重采最近 window 个交易日 ✓（**按配置的数据源** ✓）

    【2026-09-26 方案 C ✓】默认源已改为**同花顺 `moneyflow_ths`**（保真口径 ✓）——
    每日更新必须与**评分读取的源一致** ✗✓，否则"更新东财、评分读同花顺"⇒
    评分侧天天缺数据 ✗（或反之：口径错配 ✗，正是本轮回测变差的根因 ✗）。
    """
    from utils.moneyflow_source import (clip_dates_to_source, make_collector,
                                       resolve)
    src = source or resolve()
    # ★【2026-09-29 用户反馈 ✓】未收盘的今日**顺延不采** ✓（否则会被记成失败 ✗✓）
    eff_dates, deferred = _moneyflow_effective_dates(list(recent))
    if deferred:
        logger.info('[moneyflow] 窗口末日 %s = **今日且未收盘** ✓ ⇒ 源端当日数据未出，'
                    '**本日顺延不采** ✓（**不计失败** ✗✓；收盘后重跑即补 ✓）', deferred)
    use, dropped, start = clip_dates_to_source(eff_dates, src)
    if dropped:
        logger.warning('资金流更新窗口裁剪 ✗：源 %s 起点 %s，跳过更早的 %d 日 ✓',
                       src, start, dropped)
    if not use:
        return {'skipped': True, 'reason': f'{src} 无可用区间（起点 {start}）'}
    # 统一由**唯一工厂**产出 ✓（与"初始化"入口共用 ✓，杜绝两处走岔 ✗）
    collector = make_collector(conn, src, fetcher=fetcher, state_dir=state_dir)
    collector.ensure_schema()
    stats = collector.run_daily_update(use, window=window)
    stats['window_used'] = list(use)          # ★ 供对账用 ✓（= 实际窗口 ✓）
    if deferred:
        stats['deferred_today'] = deferred
    return stats


def _stocks_with_reports(conn, recent: Sequence[str]) -> list:
    """找出最近窗口内发布"报告/业绩"类公告的股票（基本面重采对象 ✓）"""
    if not recent:
        return []
    from utils.data_collectors.local_data_collectors import EVENT_TABLE
    like = ' OR '.join(["title LIKE ?" for _ in REPORT_TITLE_KEYWORDS])
    args = [f'%{k}%' for k in REPORT_TITLE_KEYWORDS]
    sql = (f'SELECT DISTINCT stock_code FROM {EVENT_TABLE} WHERE ann_date BETWEEN ? AND ?'
           f' AND ({like})')
    try:
        return [r[0] for r in conn.execute(sql, [recent[0], recent[-1]] + args)]
    except Exception as e:
        logger.warning(f'查询"报告类公告股票"失败（跳过基本面增量）: {e}')
        return []


def _update_fundamental(conn, recent: Sequence[str], state_dir: Optional[str],
                        fetcher=None) -> Dict:
    """③ 基本面：公告驱动强制重采（新财报当天可用 ✓）"""
    from utils.data_collectors.local_data_collectors import FundamentalCollector
    fc = FundamentalCollector(conn, fetcher=fetcher, state_dir=state_dir,
                              max_retries=1, retry_wait=1.0)
    fc.ensure_schema()
    codes = _stocks_with_reports(conn, recent)
    if not codes:
        return {'added': 0, 'updated': 0, 'changed': 0, 'skipped': 0, 'failed': 0,
                'days': 0, 'stocks_done': 0, 'stocks_failed': 0, 'remain': 0,
                'budget_hit': False, 'targets': 0}
    stats = fc.run_stocks(codes, batch_sleep=0.0, ignore_completed=True)
    stats['targets'] = len(codes)
    return stats


def _update_event(conn, recent: Sequence[str], state_dir: Optional[str],
                  fetcher=None) -> Dict:
    """④ 事件：最近 window 个交易日的全市场公告标题 ✓"""
    from utils.data_collectors.cninfo_fetcher import CninfoAnnouncementFetcher
    from utils.data_collectors.local_data_collectors import EventCollector
    ec = EventCollector(conn, fetcher=fetcher or CninfoAnnouncementFetcher(),
                        state_dir=state_dir, max_retries=1, retry_wait=2.0)
    ec.ensure_schema()
    return ec.run(recent, resume=False)


def _moneyflow_latest(conn) -> Optional[str]:
    """规范表 `stock_moneyflow_daily` 的**最新交易日** ✓（取不到 ⇒ None ✗，绝不抛 ✗）"""
    try:
        row = conn.execute('SELECT MAX(trade_date) FROM stock_moneyflow_daily').fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception as e:                      # 纯日志用途 ✓ ⇒ 不抛 ✗
        logger.debug('读取 stock_moneyflow_daily 最新日期失败 ✓: %s', e)
        return None


def _log_daily_summary(conn, result: Dict, domains, recent) -> None:
    """★【2026-09-29 用户要求 ✓】结束时的**如实汇总** ✓（过程 + 结果 ✓）

    动机 ✗✓：用户问"为什么资金流更新**没完成**"✗ —— 翻阅日志**答不出来** ✗：
      · 只有"每日更新[moneyflow]完成 ✓ {stats}"一条 ✗，且 `added=0` ✗ 既可能是
        "已是最新"✓ 也可能是"**根本没补上**"✗（无法区分 ✗✓）；
      · 域被跳过 / 域异常时，**成功信息与失败信息互相顶掉** ✗（二选一打印 ✗）。
    ⇒ 现固定输出两段 ✓：
      ① **各域一行**（新增/更新/失败/跳过 原因 ✓）；
      ② **资金流落库对账** ✓ —— 用**表内最新日期**与"窗口末日"比 ✓，
         到位 ⇒ INFO ✓；落后 ⇒ **ERROR** ✗（并区分"今日未收盘 ⇒ 属正常"✓）。
    """
    parts = []
    for name in ('calendar', 'moneyflow', 'fundamental', 'event'):
        if name not in domains:
            parts.append(f'{name}=未参与')
            continue
        s = result['results'].get(name)
        if s is None:
            parts.append(f'{name}=**未完成** ✗')
        elif s.get('skipped'):
            parts.append(f"{name}=跳过({s.get('reason', '?')})")
        else:
            parts.append(f"{name}=+{s.get('added', 0)}/Δ{s.get('updated', 0)}/✗{s.get('failed', 0)}")
    logger.info('每日数据更新结束 ✓ %s', ' | '.join(parts))

    if 'moneyflow' not in domains or not recent:
        return
    # ★【2026-09-29 用户反馈 ✓】对账用**实际使用窗口** ✓（未收盘的今日已被剔除 ✓）
    _mf = (result.get('results') or {}).get('moneyflow') or {}
    if _mf.get('deferred_today'):
        logger.info('【资金流】今日 %s **未收盘** ⇒ 已顺延不采 ✓（收盘后重跑即补 ✓；'
                    '**不计失败** ✗✓）', _mf['deferred_today'])
    _win = list(_mf.get('window_used') or recent)
    target = str(_win[-1])
    expect = target
    # ⚠️ 窗口末日 = **今日且未收盘** ⇒ 源端当日数据本就未出 ✓ ⇒ 不算缺口 ✗✓（避免误报 ✗）
    try:
        from datetime import datetime as _dt
        _now = _dt.now()
        if target == _now.strftime('%Y-%m-%d') and _now.strftime('%H:%M') < '15:01' \
                and len(recent) > 1:
            expect = str(recent[-2])
            logger.info('【资金流对账】窗口末日 %s = **今日且未收盘** ✓ ⇒ 当日数据源端未出属正常 ✓，'
                        '本次按 %s 校验 ✓', target, expect)
    except Exception:
        pass
    latest = _moneyflow_latest(conn)
    if latest is None:
        logger.error('【资金流对账 ✗】stock_moneyflow_daily **为空** ✗ ⇒ 未落库 ✗'
                     '（请查域 errors 与 data_fetch_failure ✓）')
    elif latest >= expect:
        logger.info('【资金流对账 ✓】stock_moneyflow_daily 最新 %s ✓ 已覆盖应到日 %s ✓', latest, expect)
    else:
        logger.error('【资金流对账 ✗】stock_moneyflow_daily 最新 %s ✗ **落后** 应到日 %s ✗ '
                     '⇒ 该日资金流**未入库** ✗（评分/回测会按"本地数据缺失"处理 ✗）；'
                     '请查本域 errors / data_fetch_failure，或稍后重跑 ✓', latest, expect)


def run_daily_update(conn, *, window: int = DEFAULT_WINDOW,
                     trade_dates: Optional[Sequence[str]] = None,
                     state_dir: Optional[str] = None,
                     mf_fetcher=None, dc_fetcher=None,
                     cninfo_fetcher=None, fina_fetcher=None,
                     moneyflow_source: Optional[str] = None,
                     domains: Sequence[str] = ('calendar', 'moneyflow',
                                               'fundamental', 'event'),
                     raise_on_error: bool = False) -> Dict:
    """执行每日数据更新（四类 ✓）

    Args:
        conn: sqlite3 连接
        window: 增量窗口（交易日数，默认 3 ✓）
        trade_dates: 自定义交易日列表（None = 从本地日历解析 ✓）
        state_dir: 进度目录（默认 data/logs/collector_state ✓）
        mf_fetcher: 资金流数据源注入（测试用 ✓；`dc_fetcher` 为旧名，保留兼容 ✓）
        cninfo_fetcher / fina_fetcher: 其它域数据源（测试注入 ✓）
        moneyflow_source: 资金流数据源覆盖（None = 按配置 ✓，默认同花顺 ✓）
        domains: 需要更新的域子集 ✓
        raise_on_error: 某域异常时是否直接抛出（默认 False：记录并继续 ✓）

    Returns:
        dict: {'window': [...], 'results': {域: 统计}, 'errors': {域: 错误}, 'ok': bool}
    """
    domains = tuple(domains)
    result: Dict = {'window': [], 'results': {}, 'errors': {}, 'ok': True}
    try:
        all_dates, recent = resolve_update_window(conn, window)
        result['window'] = list(recent)
        result['calendar_days'] = len(all_dates)
    except Exception as e:
        result['ok'] = False
        result['errors']['calendar-window'] = str(e)
        if raise_on_error:
            raise
        logger.error(f'每日更新中止：{e}')
        return result

    # ★【2026-09-29 用户要求 ✓】开局如实说明**本次要做什么** ✗→✓（域 + 窗口 ✓）
    logger.info('每日数据更新开始 ✓ 域=%s ✓ 窗口=最近 %d 个交易日 %s ✓（本地日历共 %d 日 ✓）',
                list(domains), len(recent), list(recent), result['calendar_days'])


    steps = (
        ('calendar', lambda: _sync_calendar(conn, state_dir)),
        ('moneyflow', lambda: _update_moneyflow(conn, recent, state_dir,
                                                mf_fetcher or dc_fetcher, window,
                                                moneyflow_source)),
        ('fundamental', lambda: _update_fundamental(conn, recent, state_dir, fina_fetcher)),
        ('event', lambda: _update_event(conn, recent, state_dir, cninfo_fetcher)),
    )
    for name, fn in steps:
        if name not in domains:
            continue
        try:
            stats = fn() or {}
            result['results'][name] = stats
            # 【关键】"逐条失败"也要算**该域失败** ✗ ——
            #   采集器对单条失败是"记录到 data_fetch_failure 后继续"✓，
            #   若不在此处汇总，整域全挂也会被报成成功 ✗（静默失败 ✗✓ 已被测试抓出）
            n_failed = int(stats.get('failed') or 0)
            if n_failed:
                result['ok'] = False
                result['errors'][name] = (f'{n_failed} 个目标采集失败 ✗'
                                         f'（明细见 data_fetch_failure 表 ✓，可定向重试）')
                logger.error(f'每日更新[{name}]部分/全部失败 ✗ {stats}')
            else:
                logger.info(f'每日更新[{name}]完成 ✓ {stats}')
        except Exception as e:                     # 单域异常不影响其它域 ✓，但如实记录 ✗
            result['ok'] = False
            result['errors'][name] = str(e)[:300]
            logger.error(f'每日更新[{name}]异常 ✗: {e}')
            if raise_on_error:
                raise
    # ★【2026-09-29 用户要求 ✓】**固定汇总 + 资金流落库对账** ✗→✓
    #   （无论成败都输出 ✓ —— 不再"成功信息被失败信息顶掉"✗）
    _log_daily_summary(conn, result, domains, recent)
    return result
