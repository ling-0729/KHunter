# -*- coding: utf-8 -*-
"""回填 `market_index_adx` 的 **2025-01-02 之前**历史 ✓（**只增不改** ✗✓）

## 口径 ✓：**完全复用生产实现** ✓
不重写任何计算 ✗ —— 直接调 `MarketIndexADX.calculate()` ✓（列改名 ✓ 排序 ✓ `ADX(df, 14)` ✓
四舍五入 ✓ 字段映射 `adx/adx_prev/adx_change/trend_*/close/data_points/has_enough_data` ✓ 全同 ✓），
**只把它的取数**换成"本地已下载的全序列切片"✓（⇒ 零重复联网 ✓✓、零口径漂移 ✓✓）。

## 安全 ✓
· **只对"库里不存在的日期"写** ✓（已存在的 421 行**一律不动** ✗）；
· 写入前先做**交叉验证** ✓：用同一口径重算 `2025-01-02`（**已存在** ✓）与库值比对 ✓，
  **不一致就中止** ✗（不写任何东西 ✓）。

## 为什么需要它 ✗✓
§5.6/§5.8 要求「**ADX 数据起点 ≤ 回测起点**」✓ —— 而现库起点 = `2025-01-02` ✗
⇒ `run_adx_ab.py` 的 **2025H1 段（起点 2025-01-01）状态未预热** ✗，A/B 结论会被污染 ✗✓。
"""
import sys
import time
from datetime import timedelta

sys.path.insert(0, '.')

import pandas as pd                                   # noqa: E402
from trading.market_index_adx_dao import MarketIndexADXDAO   # noqa: E402
from utils.market_index_adx import MarketIndexADX      # noqa: E402

INDEX = '000985.CSI'
BACKFILL_START, BACKFILL_END = '20200101', '20241231'  # 落库范围 ✓（2025 起已有 ✓）
CHUNKS = [('20140101', '20160101'), ('20160101', '20180101'),
          ('20180101', '20200101'), ('20200101', '20220101'),
          ('20220101', '20240101'), ('20240101', '20250201')]  # 尾含 2025-01 ✓（供自检 ✓）
CHECK_DATE = '20250102'                                # 已存在 ⇒ 用来自检 ✓


def fetch_full() -> pd.DataFrame:
    """一次把指数日线取全 ✓（分段规避单次行数上限 ✓）"""
    import tushare as ts
    pro = ts.pro_api()
    frames = []
    for a, b in CHUNKS:
        df = pro.index_daily(ts_code=INDEX, start_date=a, end_date=b)
        if df is not None and not df.empty:
            frames.append(df)
        time.sleep(0.4)                                # 温和限速 ✓
    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={'trade_date': 'date', 'open': 'open', 'close': 'close',
                            'high': 'high', 'low': 'low', 'vol': 'volume',
                            'amount': 'amount', 'pct_chg': 'change_pct'})
    df['date'] = pd.to_datetime(df['date'])
    df = df.drop_duplicates('date').sort_values('date').reset_index(drop=True)
    return df


SERIES = fetch_full()
WARM = MarketIndexADX.WARMUP_CALENDAR_DAYS             # 400 自然日 ✓（与生产同 ✓）
print('取数 ✓ %s ~ %s，共 %d 根'
      % (SERIES['date'].iloc[0].date(), SERIES['date'].iloc[-1].date(), len(SERIES)))


def _slice_upto(trade_date, use_cache=False):          # ★ 替换取数（签名同生产 ✓）
    end = pd.to_datetime(trade_date)
    s = SERIES[(SERIES['date'] >= end - timedelta(days=WARM))
               & (SERIES['date'] <= end)]
    return s.reset_index(drop=True) if not s.empty else None


calc = MarketIndexADX(index_code=INDEX)
calc._fetch_index_df = _slice_upto                     # ★ 只换取数 ✓，逻辑全用生产 ✓

dao = MarketIndexADXDAO()
have = {r['trade_date'] for r in dao.query_range(BACKFILL_START, BACKFILL_END, INDEX)}
todo = [d.strftime('%Y%m%d') for d in SERIES['date']
        if BACKFILL_START <= d.strftime('%Y%m%d') <= BACKFILL_END
        and d.strftime('%Y%m%d') not in have]
print('落库范围 %s~%s：已存在 %d 天（**不动** ✓），待回填 %d 天'
      % (BACKFILL_START, BACKFILL_END, len(have), len(todo)))

# ---------------- ★ 交叉验证（不通过就中止 ✗）----------------
row = dao.query_by_date(CHECK_DATE, INDEX)
fresh = calc.calculate(CHECK_DATE)
db_adx = float(row['adx']) if row else None
print('交叉验证 %s：库 adx=%s ／ 同口径重算 adx=%s' % (CHECK_DATE, db_adx, fresh['adx']))
if db_adx is None or abs(db_adx - float(fresh['adx'])) > 0.02:
    print('✗ 口径不一致 ⇒ **中止，不写任何数据** ✗')
    sys.exit(1)
print('✓ 口径一致 ⇒ 开始回填 ✓')

n = 0
for d in todo:
    try:
        dao.save(calc.calculate(d))
        n += 1
        if n % 200 == 0:
            print('  已写 %d / %d' % (n, len(todo)))
    except Exception as e:
        print('  跳过 %s：%s' % (d, str(e)[:60]))
print('已写入 %d 行 ✓' % n)

allrows = dao.query_range('20200101', '20260924', INDEX)
print('回填后覆盖 ✓ %s ~ %s，共 %d 天'
      % (allrows[0]['trade_date'], allrows[-1]['trade_date'], len(allrows)))
