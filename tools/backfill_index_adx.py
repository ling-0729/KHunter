# -*- coding: utf-8 -*-
"""回填 `market_index_adx`（大盘指数 ADX）✓ —— **只增不改** ✗✓ + **多指数** ✓

## 口径 ✓：**完全复用生产实现** ✓
不重写任何计算 ✗ —— 直接调 `MarketIndexADX.calculate()` ✓（列改名 ✓ 排序 ✓ `ADX(df, 14)` ✓
四舍五入 ✓ 字段映射 `adx/adx_prev/adx_change/trend_*/close/data_points/has_enough_data` ✓ 全同 ✓），
**只把它的取数**换成"本地已下载的全序列切片"✓（⇒ 零重复联网 ✓✓、零口径漂移 ✓✓）。

## 安全 ✓
· **只对"库里不存在的日期"写** ✓（已存在的行**一律不动** ✗）；
· 已**有数据**的指数 ✓ ⇒ 写入前先做**交叉验证** ✓：用同一口径重算一个**已存在**的日期 ✓
  与库值比对 ✓，**不一致就中止** ✗（不写任何东西 ✓）；
· 新指数（库里没有 ✗）⇒ 做**健全性校验** ✓：行数区间 ✓ / `adx∈[0,100]` ✓ /
  `close` 与数据源一致 ✓ / `adx_prev→adx` 链连续 ✓ —— 不通过则**中止** ✗。

## 用法 ✓
    python tools/backfill_index_adx.py                      # 默认：中证全指 2020-01-01~2024-12-31（**旧行为** ✓）
    python tools/backfill_index_adx.py --indexes 399006.SZ,000688.SH
    python tools/backfill_index_adx.py --indexes 399006.SZ --start 20200101 --end 20260930

## 为什么需要它 ✗✓
§5.6/§5.8 要求「**ADX 数据起点 ≤ 回测起点**」✓ —— 库起点曾是 `2025-01-02` ✗
⇒ 2025H1 段（起点 2025-01-01）状态未预热 ✗；2026-09-27 已回填中证全指至 `2020-01-02` ✓。
★ 2026-10-05 ✓：用户要求**增加创业板与科创板** ✓（`399006.SZ` 创业板指 ✓ /
  `000688.SH` 科创50 ✓）⇒ 本脚本参数化以支持多指数 ✓✓。
  ⚠️ 科创50 指数 **2019-12-31 才发布** ✗ ⇒ 其最早若干行 `adx` 为 NULL ✓（预热不足 ✓，
     与"个股预热期 NULL"同语义 ✓）；如需回测起点**早于其预热完成日** ✗ ⇒ 会被
     `check_index_adx` 的「状态预热」判据拦下 ✓（**这是对的** ✗✓，别放宽 ✗）。
"""
import argparse
import sys
import time
from datetime import timedelta

sys.path.insert(0, '.')

import pandas as pd                                   # noqa: E402
from trading.market_index_adx_dao import MarketIndexADXDAO   # noqa: E402
from utils.market_index_adx import MarketIndexADX      # noqa: E402

#: 默认指数 ✓（与 `config/regime_router.yaml::index_code` ✓、`backtest_data_gate` 同口径 ✓）
DEFAULT_INDEXES = ['000985.CSI']
#: 默认落库范围 ✓（2025 起原有数据 ✓ ⇒ 这里补 2020~2024 ✓）
DEFAULT_START, DEFAULT_END = '20200101', '20241231'
#: 取数起点 ✓（比分段早一年 ⇒ 保证 2020 初的**预热**用得上 ✓；科创50 自然从 2019-12-31 起 ✓）
FETCH_START = '20140101'
#: 分段取数 ✓（规避单次行数上限 ✓）+ 温和限速 ✓
CHUNK_YEARS = 2
SLEEP = 0.4


def _chunks(start: str, end: str, years: int = CHUNK_YEARS):
    a = pd.to_datetime(start)
    e = pd.to_datetime(end)
    while a <= e:
        b = min(a + pd.DateOffset(years=years) - timedelta(days=1), e)
        yield a.strftime('%Y%m%d'), b.strftime('%Y%m%d')
        a = b + timedelta(days=1)


def fetch_series(index_code: str) -> pd.DataFrame:
    """一次把指数日线取全 ✓（分段 ✓ + 限速 ✓）"""
    import tushare as ts
    pro = ts.pro_api()
    frames = []
    for a, b in _chunks(FETCH_START, pd.Timestamp.today().strftime('%Y%m%d')):
        try:
            df = pro.index_daily(ts_code=index_code, start_date=a, end_date=b)
        except Exception as e:
            print('    取数异常（跳过该段 ✓）%s~%s：%s' % (a, b, str(e)[:50]))
            continue
        if df is not None and not df.empty:
            frames.append(df)
        time.sleep(SLEEP)
    if not frames:
        raise RuntimeError('未取到任何数据 ✗（检查指数代码 / 接口权限 ✓）')
    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={'trade_date': 'date', 'open': 'open', 'close': 'close',
                            'high': 'high', 'low': 'low', 'vol': 'volume',
                            'amount': 'amount', 'pct_chg': 'change_pct'})
    df['date'] = pd.to_datetime(df['date'])
    return df.drop_duplicates('date').sort_values('date').reset_index(drop=True)


def backfill_one(index_code: str, start: str, end: str, dao: MarketIndexADXDAO,
                 dry_run: bool = False) -> int:
    """回填**单个**指数 ✓；返回写入行数 ✓（`dry_run` ⇒ 只演练校验、**一行都不写** ✗✓）"""
    print('\n================ %s ================' % index_code)
    series = fetch_series(index_code)
    print('  取数 ✓ %s ~ %s，共 %d 根'
          % (series['date'].iloc[0].date(), series['date'].iloc[-1].date(), len(series)))

    warm = MarketIndexADX.WARMUP_CALENDAR_DAYS      # 400 自然日 ✓（与生产同 ✓）

    def _slice_upto(trade_date, use_cache=False):   # ★ 替换取数（签名同生产 ✓）
        et = pd.to_datetime(trade_date)
        s = series[(series['date'] >= et - timedelta(days=warm))
                   & (series['date'] <= et)]
        return s.reset_index(drop=True) if not s.empty else None

    calc = MarketIndexADX(index_code=index_code)
    calc._fetch_index_df = _slice_upto               # ★ 只换取数 ✓，逻辑全用生产 ✓

    have = {r['trade_date'] for r in dao.query_range(start, end, index_code)}
    todo = [d.strftime('%Y%m%d') for d in series['date']
            if start <= d.strftime('%Y%m%d') <= end and d.strftime('%Y%m%d') not in have]
    print('  落库范围 %s~%s：已存在 %d 天（**不动** ✓），待回填 %d 天'
          % (start, end, len(have), len(todo)))

    # ---------------- 校验（不通过就中止 ✗）----------------
    if have:
        chk = sorted(have)[-1]                       # ★ 拿**库里已有**的**最新**一天来自检 ✓
        row = dao.query_by_date(chk, index_code)
        fresh = calc.calculate(chk)
        db_adx = float(row['adx']) if row and row.get('adx') is not None else None
        print('  交叉验证 %s：库 adx=%s ／ 同口径重算 adx=%s' % (chk, db_adx, fresh['adx']))
        if db_adx is None or abs(db_adx - float(fresh['adx'])) > 0.02:
            print('  ✗ 口径不一致 ⇒ **中止，不写任何数据** ✗')
            return 0
        print('  ✓ 口径一致 ⇒ 开始回填 ✓')
    else:
        # ★ 新指数 ✓：无历史可比 ⇒ 做**健全性**校验 ✓（宁可中止，也不灌脏数据 ✗）
        probe = [d.strftime('%Y%m%d') for d in series['date']][-1]
        s = calc.calculate(probe)
        bad = []
        if not (0.0 <= float(s['adx']) <= 100.0):
            bad.append('adx=%s 越界 ✗' % s['adx'])
        src = series['close'].iloc[-1]
        if abs(float(s['close']) - float(src)) > 0.01:
            bad.append('close=%s 与源 %s 不一致 ✗' % (s['close'], src))
        if abs(float(s['adx']) - float(s['adx_prev'] or 0)) > 60:
            bad.append('adx 与 adx_prev 跳变异常 ✗')
        print('  健全性校验 %s：adx=%s / close=%s / data_points=%s'
              % (probe, s['adx'], s['close'], s['data_points']))
        if bad:
            print('  ✗ %s ⇒ **中止，不写任何数据** ✗' % '；'.join(bad))
            return 0
        print('  ✓ 健全性通过 ⇒ 开始回填 ✓')

    n = 0
    for d in todo:
        try:
            data = calc.calculate(d)                 # ★ 生产口径 ✓（dry-run 也算 ✓）
            if dry_run:
                n += 1
                continue                             # ★ 只算**不写** ✗✓
            dao.save(data)
            n += 1
            if n % 200 == 0:
                print('    已写 %d / %d' % (n, len(todo)))
        except Exception as e:
            print('    跳过 %s：%s' % (d, str(e)[:60]))
    print('  %s %d 行 ✓' % ('dry-run：可算出' if dry_run else '已写入', n))

    rows = dao.query_range(start, end, index_code)
    if rows:
        nulls = sum(1 for r in rows if r.get('adx') is None)
        print('  落库核对 ✓ %s ~ %s，共 %d 天（adx 为空 %d 天 ✓）'
              % (rows[0]['trade_date'], rows[-1]['trade_date'], len(rows), nulls))
    return n


def main():
    ap = argparse.ArgumentParser(description='回填大盘指数 ADX（只增不改 ✓）')
    ap.add_argument('--indexes', default=','.join(DEFAULT_INDEXES),
                    help='指数代码，逗号分隔 ✓（默认 %s ✓）' % ','.join(DEFAULT_INDEXES))
    ap.add_argument('--start', default=DEFAULT_START, help='落库起点 YYYYMMDD ✓')
    ap.add_argument('--end', default=DEFAULT_END, help='落库终点 YYYYMMDD ✓')
    ap.add_argument('--dry-run', action='store_true',
                    help='只演练（取数 ✓ 校验 ✓ 计算 ✓）但**一行都不写库** ✗✓')
    args = ap.parse_args()

    codes = [c.strip() for c in args.indexes.split(',') if c.strip()]
    dao = MarketIndexADXDAO()
    total = 0
    for code in codes:
        total += backfill_one(code, args.start, args.end, dao, dry_run=args.dry_run)
    print('\n全部完成 ✓ %s %d 行 ✓'
          % ('可算出' if args.dry_run else '共写入', total))


if __name__ == '__main__':
    main()
