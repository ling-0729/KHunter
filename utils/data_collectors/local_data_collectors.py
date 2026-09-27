# -*- coding: utf-8 -*-
"""M2 采集器：个股基本面 / 个股事件 / 交易日历（均落地本地 ✓）

定稿要点（2026-09-25）：
  · 全部数据**从 `2023-09-11` 起**回填（与主源起点对齐 ✓）
  · **基本面**：`stock_finance_indicator`，含 `ann_date` ✓；
    回测时点规则 = **`ann_date <= 选股日`** 的最新一期 ✓（替代 `end_date <= 选股日` ✗，消除前视偏差 ✓）
  · **事件（公告）**：`stock_announcement` **只保留标题** ✓（URL / 分类 / 来源不落库 ✗ → 规则演进无需重采 ✓）
      ⚠️ 注意表名：**不是** `stock_event` ✗（那是应用既有事件表 ✓，字段为 `event_type/event_date/...` ✓）
  · **交易日历**：`trade_calendar` 落库 ✓（真源仍为权威日历；本类只做 JSON 缓存 → DB 的同步 ✓，**无需联网** ✓）
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from utils.data_collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)

#: 统一回填起点（与 `moneyflow_dc` 源起点一致 ✓；已确认回测起点永不会更早 ✓）
SOURCE_START = '2023-09-11'

FUNDAMENTAL_TABLE = 'stock_finance_indicator'
# 【2026-09-25 改名 ✗→✓】公告表原用 `stock_event` ✗ —— 与 `data/DataSql.sql` 中**既有**的
#   `stock_event`（应用事件表 ✓：`event_type/event_date/event_title/...` ✓）**表名撞车** ✗✓：
#   本采集器建出的表是 `(stock_code, ann_date, title, ...)` ✗ ⇒ `CREATE TABLE IF NOT EXISTS`
#   不生效 ✗ ⇒ 紧随其后的 `CREATE INDEX ... ON stock_event(event_date)` **报错** ✗
#   ⇒ **数据库初始化中断、web_server 启动崩溃** ✗✓（2026-09-25 22:39 实测 ✓）。
#   现改名 `stock_announcement` ✓（与既定 SQL 零冲突 ✓，已验证 ✓），语义也更准确 ✓
#   —— 它存的是**公告标题** ✓，不是应用那套按 `event_type` 归类的事件 ✓。
EVENT_TABLE = 'stock_announcement'
CALENDAR_TABLE = 'trade_calendar'

#: 基本面落库字段（与 `trading/fundamental_scorer` 所需一致 ✓）
FUNDAMENTAL_FIELDS = ('roe', 'netprofit_yoy', 'ocfps', 'eps', 'ocf_to_opincome')


def _iso(value) -> str:
    """YYYYMMDD → YYYY-MM-DD（非 8 位数字则原样返回前 10 位）"""
    s = str(value).strip()
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    return s[:10]


def _iter_records(raw) -> List[Dict]:
    if raw is None:
        return []
    if hasattr(raw, 'to_dict'):
        try:
            return raw.to_dict('records')
        except Exception:
            return []
    if isinstance(raw, dict):
        return [raw]
    return [dict(r) for r in raw]


def quarter_periods(start: str, end: str) -> List[str]:
    """生成 `[start, end]` 覆盖到的**报告期**列表（季末 YYYYMMDD ✓）

    例：start=2023-09-11 → 从 `20230930` 起；end=2026-09-25 → 到 `20260630` 止
    （含 `start` 之前一季 ✓，保证首个选股日就有可用财报 ✓）
    """
    start_year, end_year = int(start[:4]), int(end[:4])
    periods = []
    for y in range(start_year - 1, end_year + 1):
        for md in ('0331', '0630', '0930', '1231'):
            p = f'{y}{md}'
            iso = f'{p[:4]}-{p[4:6]}-{p[6:8]}'
            if iso <= end:
                periods.append(p)
    # 只保留 start 前一季起（含 start 所在季）
    keep_from = None
    for i, p in enumerate(periods):
        if f'{p[:4]}-{p[4:6]}-{p[6:8]}' >= start:
            keep_from = max(0, i - 1)
            break
    return periods[keep_from:] if keep_from is not None else periods[-4:]


# ============================================================ 基本面

class _TushareFundamentalFetcher:
    """Tushare `fina_indicator`：**按报告期**一次取全市场 ✓（高效 ✓）"""

    def __init__(self, token: Optional[str] = None):
        self._token = token
        self._pro = None

    def _pro_api(self):
        if self._pro is None:
            import tushare as ts
            token = self._token
            if not token:
                try:
                    with open('config/tushare_config.json', 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    token = cfg.get('api_key') or cfg.get('token')
                except Exception:
                    token = None
            if token:
                ts.set_token(token)
            self._pro = ts.pro_api()
        return self._pro

    def fina_indicator(self, **kwargs):
        from utils.online_guard import PURPOSE_UPDATE, guard_online_call
        # 【2026-09-25 契约 ✓】采集 = **数据更新**流程 → `purpose='update'` ✓
        guard_online_call('Tushare fina_indicator 取数', purpose=PURPOSE_UPDATE)
        return self._pro_api().fina_indicator(**kwargs)


class FundamentalCollector(BaseCollector):
    """个股基本面采集器（报告期驱动 ✓）

    · 主键 `(stock_code, end_date, ann_date)` ✓（同一报告期可能有多次公告/更正 ✓）
    · 时点字段 `ann_date` **必须落库** ✓ —— 回测按 `ann_date <= 选股日` 取数 ✓
    """

    name = 'fundamental'
    table = FUNDAMENTAL_TABLE
    pk_cols = ('stock_code', 'end_date', 'ann_date')
    columns = (('stock_code', 'end_date', 'ann_date') + FUNDAMENTAL_FIELDS
               + ('created_date', 'updated_date'))
    source_start_date = SOURCE_START
    date_col = 'end_date'
    preserve_on_update = ('created_date',)
    #: 数值列（建表声明为 REAL ✓，避免被 TEXT 亲和性转成字符串 ✗）
    real_cols = FUNDAMENTAL_FIELDS

    def __init__(self, conn, fetcher=None, **kwargs):
        super().__init__(conn, fetcher=fetcher or _TushareFundamentalFetcher(), **kwargs)

    # ---- BaseCollector 勾子（本采集器按"报告期"驱动，不用日期循环 ✓）
    def fetch_date(self, date_str: str):                     # pragma: no cover - 未使用
        raise NotImplementedError('基本面按报告期采集，请使用 run_periods()')

    def normalize(self, raw) -> List[Dict]:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        rows: List[Dict] = []
        for rec in _iter_records(raw):
            ts_code = str(rec.get('ts_code') or '').strip()
            ann_date = rec.get('ann_date')
            end_date = rec.get('end_date')
            if not ts_code or not ann_date or not end_date:
                continue
            row = {'stock_code': ts_code.split('.')[0][:6],
                   'end_date': _iso(end_date),
                   'ann_date': _iso(ann_date),
                   'created_date': now, 'updated_date': now}
            for f in FUNDAMENTAL_FIELDS:
                row[f] = rec.get(f)
            rows.append(row)
        return rows

    def fetch_period(self, period: str):
        """按报告期取全市场财务指标 ✓（**仅 `fina_indicator_vip` 权限可用** ✗）

        实测（2026-09-25 ✓）：普通 `fina_indicator` **要求 `ts_code` 必填** ✗
        （`必填参数, ts_code`）→ 普通权限下请使用 `fetch_stock()` / `run_stocks()` ✓
        """
        return self.fetcher.fina_indicator(
            period=period,
            fields='ts_code,ann_date,end_date,roe,netprofit_yoy,ocfps,eps,ocf_to_opincome')

    # ---- 逐股模式（普通权限可用 ✓）------------------------------------

    def fetch_stock(self, stock_code: str, start: str, end: str):
        """取**单只股票**的财务指标（公告日区间 ✓；一次拿全历史 ✓）"""
        ts_code = stock_code if '.' in stock_code else (
            f'{stock_code}.SH' if stock_code.startswith(('6', '9')) else f'{stock_code}.SZ')
        return self.fetcher.fina_indicator(
            ts_code=ts_code,
            start_date=start.replace('-', ''), end_date=end.replace('-', ''),
            fields='ts_code,ann_date,end_date,roe,netprofit_yoy,ocfps,eps,ocf_to_opincome')

    def run_stocks(self, stock_codes: Sequence[str], start: str = SOURCE_START,
                   end: Optional[str] = None, batch_sleep: float = 0.12,
                   strict: bool = False, max_seconds: Optional[float] = None,
                   ignore_completed: bool = False) -> Dict:
        """逐股回填财务指标 ✓（普通 Tushare 权限下的可行路径 ✓）

        · 每股 1 次调用（一次取全历史 ✓）→ 全市场约 5000 次调用，可分批多次运行续采 ✓
        · 失败**逐条落盘** ✓（定向重试 ✓）；断点续采由状态文件承担 ✓
        · `max_seconds`: 单次运行的**时间上限** ✓（超时即停并保存进度 ✓，
          供"分块执行"使用 —— 避免一次调用过长导致任务被中断且进度丢失 ✗）
        · `ignore_completed`: **忽略"已完成"标记强制刷新** ✓
          （每日增量用：某只股票当天发了新财报 ⇒ 必须重采该股全部历史 ✓，
            否则"曾经采过"会导致**新财报永远进不来** ✗；写入幂等 + 变更检测保证安全 ✓）
        · 返回统计含 `stocks_done` / `stocks_failed` / `remain` ✓
        """
        end = end or datetime.now().strftime('%Y-%m-%d')
        self._reset_stats()
        codes = [str(c).split('.')[0][:6] for c in stock_codes]
        state = self.load_state()
        done = set(state.get('completed_codes') or []) if state else set()
        failed: List[str] = []
        t_start = time.time()
        budget_hit = False
        for i, code in enumerate(codes):
            if max_seconds and (time.time() - t_start) > float(max_seconds):
                budget_hit = True
                logger.info(f'[{self.name}] 达到时间上限 {max_seconds}s，'
                            f'已处理 {i}/{len(codes)} 只 → 保存进度，可再次运行续采 ✓')
                break
            if code in done and not ignore_completed:
                self.stats['skipped'] += 1
                continue
            last_err = None
            for attempt in range(self.max_retries + 1):
                try:
                    raw = self.fetch_stock(code, start, end)
                    rows = self.normalize(raw)
                    if not rows:
                        # 【2026-09-25】空数据（未上市/无财报的新股 ✓）→ 记为 skipped ✓
                        #   既不写库、也不算失败；标记为已完成避免反复重试 ✓
                        done.add(code)
                        self.stats['skipped'] += 1
                        last_err = None
                        break
                    res = self.upsert(rows)
                    for k in ('added', 'updated', 'changed'):
                        self.stats[k] += res[k]
                    self.stats['days'] += 1
                    done.add(code)
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    if attempt < self.max_retries:
                        time.sleep(self.retry_wait)
            if last_err is not None:
                # 空数据不算"失败"（如未上市/无财报的新股 ✓），仅记录轻量标记
                msg = str(last_err)
                if '空数据' in msg or 'empty' in msg.lower():
                    done.add(code)
                    self.stats['skipped'] += 1
                else:
                    self.stats['failed'] += 1
                    failed.append(code)
                    self.record_failure(f'stock:{code}', msg)
            if (i + 1) % 50 == 0:
                self.save_state(completed_codes=sorted(done),
                                last_run_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                source=self.name)
                logger.info(f'[{self.name}] 进度 {i + 1}/{len(codes)}：'
                            f'新增 {self.stats["added"]}，失败 {self.stats["failed"]}')
            if batch_sleep:
                time.sleep(batch_sleep)
        self.save_state(completed_codes=sorted(done),
                        last_run_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        source=self.name)
        result = dict(self.stats)
        result['stocks_done'] = len(done)
        result['stocks_failed'] = self.stats['failed']
        result['failed_stocks'] = failed[:50]
        result['remain'] = len([c for c in codes if c not in done])
        result['budget_hit'] = budget_hit
        if strict and failed:
            raise RuntimeError(f'[{self.name}] {len(failed)} 只股票采集失败: {failed[:10]}')
        return result

    def run_periods(self, periods: Sequence[str], strict: bool = True) -> Dict:
        """按报告期回填 ✓（失败逐条落盘 ✓ + 完成后覆盖率自检 ✓）"""
        self._reset_stats()
        for period in periods:
            last_err = None
            for attempt in range(self.max_retries + 1):
                try:
                    raw = self.fetch_period(period)
                    if raw is None or (hasattr(raw, 'empty') and raw.empty):
                        raise ValueError(f'源返回空数据（period={period}）')
                    rows = self.normalize(raw)
                    res = self.upsert(rows)
                    for k in ('added', 'updated', 'changed'):
                        self.stats[k] += res[k]
                    self.stats['days'] += 1
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    if attempt < self.max_retries:
                        import time
                        time.sleep(self.retry_wait)
            if last_err is not None:
                self.stats['failed'] += 1
                self.record_failure(f'period:{period}', str(last_err))
                logger.error(f'[{self.name}] 报告期 {period} 采集失败: {last_err}')
        report = self.verify_periods(periods)
        if report['missing'] and strict:
            raise RuntimeError(f'[{self.name}] 以下报告期无数据: {report["missing"]}')
        result = dict(self.stats)
        result['coverage'] = report
        return result

    def verify_periods(self, periods: Sequence[str]) -> Dict:
        """覆盖率自检：每期在表中至少要有记录 ✓"""
        have = {str(r[0]) for r in self.conn.execute(
            f'SELECT DISTINCT end_date FROM {self.table}').fetchall()}
        want = [f'{p[:4]}-{p[4:6]}-{p[6:8]}' for p in periods]
        missing = [p for p in want if p not in have]
        return {'expected': len(want), 'actual': len(have), 'missing': missing}


def load_indicators_local(conn, stock_code: str, score_date: str,
                          table: str = FUNDAMENTAL_TABLE) -> List[Dict]:
    """取**选股日所在季度**的财务指标（**按季匹配 + 公告日过滤** ✓）

    规则（用户 2026-09-27 决策 ✓）：
      · 选股日所属季度 → 取**对应报告期**的财报：
          1~3月选股 → 上一年 Q4（end_date=上一年 12-31）
          4~6月选股 → 当年 Q1（end_date=当年 03-31）
          7~9月选股 → 当年 Q2（end_date=当年 06-30）
          10~12月选股 → 当年 Q3（end_date=当年 09-30）
      · 该季度财报**已公告**（`ann_date <= score_date`）→ 返回该期 ✓
      · 该季度财报**未公告** → 返回 `[]`（**不计、不回溯上一季度** ✗）

    返回：`[]`（目标季度未公告 ✓）或 `[目标季度行 dict]` ✓
    """
    # 解析选股日
    s = str(score_date).strip()
    if len(s) >= 10 and s[4] == '-':
        year = int(s[:4])
        month = int(s[5:7])
    elif len(s) == 8 and s.isdigit():
        year = int(s[:4])
        month = int(s[4:6])
    else:
        year = int(s[:4])
        month = int(s[4:6])

    # 计算目标季度的 end_date
    if 1 <= month <= 3:
        target_end = f'{year - 1}-12-31'
    elif 4 <= month <= 6:
        target_end = f'{year}-03-31'
    elif 7 <= month <= 9:
        target_end = f'{year}-06-30'
    else:
        target_end = f'{year}-09-30'

    cols = list(FUNDAMENTAL_FIELDS) + ['stock_code', 'end_date', 'ann_date']
    cur = conn.execute(
        f'SELECT {", ".join(cols)} FROM {table} '
        f'WHERE stock_code=? AND end_date=? AND ann_date IS NOT NULL AND ann_date<=? '
        f'ORDER BY ann_date DESC LIMIT 1',
        (stock_code, target_end, score_date))
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows


def collect_fundamental(conn, start: str = SOURCE_START, end: Optional[str] = None,
                        fetcher=None, state_dir=None) -> Dict:
    """便捷入口：从 `start`（默认 2023-09-11 ✓）回填到 `end`（默认今天 ✓）"""
    end = end or datetime.now().strftime('%Y-%m-%d')
    collector = FundamentalCollector(conn, fetcher=fetcher, state_dir=state_dir)
    collector.ensure_schema()
    return collector.run_periods(quarter_periods(start, end))


# ============================================================ 事件（只留标题）

class EventCollector(BaseCollector):
    """个股公告**标题**采集器（`stock_announcement` 只保留标题 ✓）

    取数来源通过 `fetcher.fetch_day(date_str) -> [{stock_code, ann_date, title}]` 注入 ✓
    （真实巨潮全市场抓取在 M3 接入 ✓；本类负责落库/幂等/变更检测/失败落盘 ✓）
    """

    name = 'event'
    table = EVENT_TABLE
    pk_cols = ('stock_code', 'ann_date', 'title')
    columns = ('stock_code', 'ann_date', 'title', 'created_date', 'updated_date')
    source_start_date = SOURCE_START
    date_col = 'ann_date'
    preserve_on_update = ('created_date',)

    def __init__(self, conn, fetcher=None, **kwargs):
        super().__init__(conn, fetcher=fetcher, **kwargs)

    def fetch_date(self, date_str: str):
        if self.fetcher is None or not hasattr(self.fetcher, 'fetch_day'):
            raise RuntimeError('EventCollector 需要注入 fetcher.fetch_day(date_str)（M3 接入巨潮 ✓）')
        from utils.online_guard import PURPOSE_UPDATE, guard_online_call
        # 【2026-09-25 契约 ✓】采集 = **数据更新**流程 → `purpose='update'` ✓（同前 ✓）
        guard_online_call(f'公告标题抓取 {date_str}', purpose=PURPOSE_UPDATE)
        return self.fetcher.fetch_day(date_str)

    def normalize(self, raw) -> List[Dict]:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        rows: List[Dict] = []
        for rec in _iter_records(raw):
            code = str(rec.get('stock_code') or '').split('.')[0][:6]
            ann = rec.get('ann_date')
            title = (rec.get('title') or '').strip()
            if not code or not ann or not title:
                continue
            rows.append({'stock_code': code, 'ann_date': _iso(ann), 'title': title,
                         'created_date': now, 'updated_date': now})
        return rows


def load_announcement_titles(conn, stock_code: str, start_date: str, end_date: str,
                             table: str = EVENT_TABLE) -> List[Dict]:
    """读取区间内某股票的公告**标题**（离线 ✓；判定按标题关键词 ✓）"""
    cur = conn.execute(
        f'SELECT stock_code, ann_date, title FROM {table} '
        f'WHERE stock_code=? AND ann_date BETWEEN ? AND ? ORDER BY ann_date',
        (stock_code, start_date, end_date))
    return [{'stock_code': r[0], 'ann_date': r[1], 'title': r[2]} for r in cur.fetchall()]


# ============================================================ 交易日历落库

class CalendarCollector(BaseCollector):
    """交易日历落库（JSON 缓存 → `trade_calendar` 表 ✓，**无需联网** ✓）

    说明：日历的联网刷新仍只在"每日数据更新"流程中发生 ✓；
    本类只做"本地缓存/权威日历 → 落库"，供回测**只读本地表** ✓、并让日历也可被审计 ✓。
    """

    name = 'calendar'
    table = CALENDAR_TABLE
    pk_cols = ('cal_date',)
    columns = ('cal_date', 'is_open', 'exchange', 'source', 'created_date', 'updated_date')
    source_start_date = SOURCE_START
    date_col = 'cal_date'
    preserve_on_update = ('created_date',)

    def fetch_date(self, date_str: str):                       # pragma: no cover - 不使用
        raise NotImplementedError('交易日历按整体同步，请使用 sync_from_local_cache()')

    def normalize(self, raw) -> List[Dict]:                     # pragma: no cover - 不使用
        return []

    def sync_from_local_cache(self, cache_file: Optional[Path] = None) -> Dict:
        """把本地权威日历（JSON 缓存 ✓）同步进 `trade_calendar` 表 ✓

        【2026-09-25 修复】必须 `prefer_db=False` ✗→✓：
          否则会"读自己刚写的表"（循环 ✗），缓存里新增的日期**永远进不了表** ✗
        """
        from utils.local_calendar import load_local_trade_dates
        dates = load_local_trade_dates(self.conn, cache_file, prefer_db=False)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        rows = [{'cal_date': d, 'is_open': 1, 'exchange': 'SSE',
                 'source': 'akshare' if cache_file else 'local_cache',
                 'created_date': now, 'updated_date': now} for d in dates]
        res = self.upsert(rows)
        logger.info(f'[calendar] 交易日历已落库 ✓ 共 {len(rows)} 日 '
                    f'(新增 {res["added"]}，变更 {res["changed"]})')
        res['total'] = len(rows)
        return res
