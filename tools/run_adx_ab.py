# -*- coding: utf-8 -*-
"""ADX / 入池 —— **A/B 跑测** ✓（设计文档 §12 ✓，2026-09-26 建 ✓ / 2026-09-27 扩 ✓）

## ★ 关键修正 ✗→✓（2026-09-27 实测发现：**设计 §12.1 的单表 5 组不可直接实现** ✗✓）

§12.1 把 `G0~G4` 列成"每次只动一个变量"✗ 的一张表 ✓ —— 但实测发现 ✗：
**`G2_大盘降温`（`enable_adx_falloff`）只在 `RegimeBacktestEngine` 里生效** ✗✓
（普通 `BacktestEngine` 根本不构造 `RegimeRouter` ✗）⇒
若把 G2/G4 放在普通引擎上跑 ✗ ⇒ **开关是空转** ✗（跑出来的"无差异"✗ 会被误读成"降温没用"✗✗）。
⇒ 故本脚本按**引擎**分两族 ✓，**各配自己的基线** ✓（跨引擎不可比 ✗✓）：

| 族 ✓ | 引擎 ✓ | 组 ✓ | 基线 ✓ |
|---|---|---|---|
| **A** | `BacktestEngine`（普通 ✓ = 生产现状 ✓）| `G0_基线` ✓ / `G1_加仓规则2` ✓ / `G3_个股ADX` ✓ / `G3G5` ✓ / `G5_去评分` ✓ | **G0** ✓ |
| **B** | `RegimeBacktestEngine`（大盘路由 ✓）| `R0_路由基线`（**跟随 yaml** ✓ = 生产现状 ✓）/ `R2_对照臂`（**取反** ✓）| **R0** ✓ |

> ★ **2026-09-27 更正** ✗→✓：两臂**不再写死** ✗（旧版硬编码 `R0=False / R2=True` ✗）⇒
> `R0` 跟随 `config/regime_router.yaml` 的 `enable_adx_falloff` ✓、`R2` 取其**反** ✓
> ⇒ **yaml 无论开关，对照都成立** ✓✓；实际值见每组打印的 `router={…}` ✓ 与 CSV 的 `router` 列 ✓。

> ⚠️ **不可**把 `G3`（普通引擎 ✓）与 `R2`（路由引擎 ✓）放同一张表比 ✗ ——
> 两者**路由机制不同** ✗，差异里混着"路由本身"✗ 与"降温"✗（§12.3 只允许比**相对差异** ✓）。

## 三段 ✓（AC7「三段同号」✓）

`2025H1` ✓ / `2025H2` ✓ / `2026` ✓（默认全跑 ✓；`--segments` 可挑 ✓）

## 用法 ✓

    python tools/run_adx_ab.py --strategy 金三角策略 --segments 2025H1,2025H2,2026
    python run_adx_ab.py --strategy 多方炮策略 --start 2026-01-01 --end 2026-09-24 --groups G0_基线,G1_加仓规则2
    python run_adx_ab.py --strategy 金三角策略 --segments 2026 --family B      # 只看大盘路由 ✓

**安全** ✓：默认**不写回测结果表** ✗（仅打印 + 落 CSV ✓）；`--save` 才落库 ✓。
**前置** ✗：① `adx` 已全量回填 ✓；② 回测起点 ≥ ADX 覆盖起点 ✓ 且**不落在降温期中** ✗（§12.3 ✓）；
③ 资金流同花顺源自 `2024-12-24` 起 ✓ ⇒ **更早区间闸门会明确拒绝** ✗（不静默 ✓）。
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '.')

DB_PATH = 'data/stock_selection.db'

#: **三段** ✓（AC7 ✓；`2026` 段止于库里 K 线最后一日 2026-09-24 ✓）
SEGMENTS = {
    '2025H1': ('2025-01-01', '2025-06-30'),
    '2025H2': ('2025-07-01', '2025-12-31'),
    '2026': ('2026-01-01', '2026-09-24'),
}

#: **A 族** ✓：普通引擎（= 生产现状 ✓）—— `(组名, 请求 config 覆盖 ✓, router 覆盖 ✗(空))`
GROUPS_A = [
    ('G0_基线', {}, {}),
    ('G1_加仓规则2', {'enable_add_open_rise_check': True}, {}),
    # ★【2026-09-28 用户口径 ✓】**个股入场口径**三臂对照 ✓（`dir=上升` 均为硬条件 ✗✓）：
    #   · `G3_个股ADX(档位)` ✓ = 旧口径 ✓：只放「明确」✓（`band` + 迟滞 ✓）；
    #   · `G4_区间入场` ✓ = ★**现行默认** ✓：`21 < ADX < 30` ✓（**开区间** ✓、**无缓冲** ✗）；
    #   · `G4b_萌芽入场` ✓ = 档位口径放宽 ✓：`明确 + 萌芽` ✓。
    #   实测（80 只 / 80151 天 ✓，`dir=上升` 36913 天）：档位(明确) **16352** ✓ →
    #   区间 **12222（×0.75 ✓ 更严，上界 30 砍掉 11499 天 ✗）**；档位放宽 **24041（×1.47）** ✗。
    ('G3_个股ADX', {'enable_stock_adx_filter': True, 'adx_entry_mode': 'band'}, {}),
    ('G4_区间入场', {'enable_stock_adx_filter': True}, {}),          # ★ 默认口径 ✓
    ('G4b_萌芽入场', {'enable_stock_adx_filter': True, 'adx_entry_mode': 'band',
                      'adx_entry_bands': ['明确', '萌芽']}, {}),
    ('G5_去评分', {'pool_entry_mode': 'veto_only'}, {}),
    ('G3G5_ADX+去评分', {'enable_stock_adx_filter': True,
                         'pool_entry_mode': 'veto_only'}, {}),
]

#: **B 族** ✓：大盘路由引擎（`G2 大盘降温` **只在**这里生效 ✗✓）
#:
#: ★ **2026-09-27 用户口径更正** ✗→✓：**两臂不再写死** ✗ ——
#:   · `R0_路由基线` ✓ = **跟随 yaml** ✓（= **生产现状** ✓；配置改了就跟着改 ✓）；
#:   · `R2_对照臂` ✓ = **方向口径对照** ✓（`two_day` ⇄ `epsilon` ✓）。
#: ⇒ **无论 yaml 取值如何，两臂都构成有效对照** ✓✓ —— 旧实现写死 `R0=False / R2=True` ✗ 有两个隐患：
#:   ① yaml 改成 `true` ✗ 时，`R0` 与"**生产现状**"脱节 ✗（**跑出来的"基线"其实不是现状** ✗✗）；
#:   ② 若两臂落到同值 ✗ ⇒ "无差异"✗ 会被误读成"降温没用"✗✗
#:      （本文件 docstring 早就警告过这个坑 ✓，现在由"**取另一档**"**动态保证** ✓）。
#: ⚠️【2026-09-28 用户口径 ✓】**降温机制已整体移除** ✗✓ ⇒ 对照变量改为**方向口径**
#:   （`dir_mode` ✓）：`R0` **跟随生产 yaml** ✓（现为 `two_day` ✓）；
#:   `R2` 取**另一档** ✓（现为旧 `epsilon` ✓）⇒ 仍构成有效对照 ✓。
#: ⚠️ 组名刻意**保持稳定** ✓（`--groups R0_路由基线` 好用 ✓）；**实际开关值**以
#:   控制台打印的 `router={…}` ✓ 与 CSV 的 `router` 列 ✓ 为准（**自证** ✓）。
def groups_b() -> list:
    """B 族两臂 ✓ —— `R0` 跟随生产 yaml ✓ / `R2` 取**另一方向口径** ✓（读一次即可 ✓）"""
    from trading.regime_router import RegimeRouter
    base = RegimeRouter({}, in_memory=True)._dir_mode          # ← 读 yaml/默认 ✓
    other = 'epsilon' if base == 'two_day' else 'two_day'      # ★ 取另一档 ✓（保证有对照 ✓）
    return [
        ('R0_路由基线', {}, {'enabled': True}),                           # ★ 跟随 yaml ✓
        ('R2_对照臂', {}, {'enabled': True, 'dir_mode': other}),          # ★ 另一档 ✓
    ]

#: 结果摘要要看的字段 ✓（与 `backtest_result` 表口径一致 ✓）
METRICS = ('total_trades', 'win_rate', 'total_return', 'max_drawdown',
           'sharpe_ratio', 'profit_factor', 'avg_return', 'avg_hold_days')


def load_base_config(strategy: str) -> dict:
    """取**库里那份**回测配置做基线 ✓（与 Web/流水线同源 ✓，避免脚本自造参数 ✗）

    【2026-09-27】改为走 **`utils/backtest_config_store`** ✓（单一存储层 ✓）：
    优先 yaml `backtest:` 节 ✓（= 现行默认值来源 ✓），缺键回落 DB ✓。
    """
    cfg: dict = {}
    try:
        from utils.backtest_config_store import load as _load_cfg
        cfg.update(_load_cfg() or {})
    except Exception as e:
        print(f'（读配置文件失败 ✗，回落到 DB ✓: {e}）')
    try:
        from utils.global_db import get_global_db
        conn = get_global_db().connect()
        cols = [x[1] for x in conn.execute('PRAGMA table_info(backtest_config)')]
        row = conn.execute('SELECT * FROM backtest_config LIMIT 1').fetchone()
        db_cfg = dict(zip(cols, row)) if row else {}
        db_cfg.pop('id', None)
        for k, v in db_cfg.items():
            cfg.setdefault(k, v)                 # yaml 优先 ✓（已在则不动 ✓）
    except Exception as e:
        print(f'（读 DB 基线失败 ✗: {e}）')
    cfg['strategy_name'] = strategy
    return cfg


def run_one(strategy: str, config: dict, family: str = 'A',
            router_config: dict = None, save: bool = False) -> dict:
    """跑一组 ✓，返回指标字典 ✓（异常不吞 ✗，原样抛出便于定位 ✓）

    Args:
        family: `A` = `BacktestEngine`（普通 ✓）；`B` = `RegimeBacktestEngine`（大盘路由 ✓）
        router_config: B 族必传 ✓（`RegimeRouter` 配置 ✓，含 `enable_adx_falloff` ✓）
    """
    t0 = time.time()
    if family == 'B':
        from trading.regime_backtest_engine import RegimeBacktestEngine
        engine = RegimeBacktestEngine(router_config=router_config or {})
        # ★【2026-09-27】**硬校验防"开关空转"** ✗✓：本文件 docstring 早就警告过 ✗
        #   ——若族 B 竟**没挂上** router ✗，`enable_adx_falloff` 会**静默空转** ✗，
        #     跑出的"无差异"✗会被误读成"降温没用"✗✗。故此处**直接失败** ✗（不静默 ✓）。
        if getattr(engine, '_router', None) is None:
            raise RuntimeError('族 B 未挂上 RegimeRouter ✗ ⇒ 降温开关会空转 ✗')
    else:
        from trading.backtest_engine import BacktestEngine
        engine = BacktestEngine(db_path=DB_PATH)
        if getattr(engine, '_router', None) is not None:
            raise RuntimeError('族 A 竟挂了 router ✗ ⇒ 两族"引擎不同"前提被破坏 ✗')
    result = engine.run_backtest(strategy, config)
    perf = (result or {}).get('performance') or {}
    out = {k: perf.get(k) for k in METRICS}
    out['final_capital'] = (result or {}).get('final_capital')
    out['seconds'] = round(time.time() - t0, 1)
    if save:
        from trading.backtest_dao import BacktestDAO
        dao = BacktestDAO(db_path=DB_PATH)
        payload = {k: perf.get(k, 0) for k in METRICS}
        payload.update({
            'strategy_name': strategy,
            'backtest_name': (f"AB_{config.get('_group', '')}_{config.get('start_date')}"
                              f"_{config.get('end_date')}"),
            'start_date': config.get('start_date'), 'end_date': config.get('end_date'),
            'initial_capital': config.get('initial_capital', 300000),
            'final_capital': out['final_capital'],
            'support_level_method': config.get('timing_strategy', ''),
        })
        out['result_id'] = dao.save_result(payload)
    return out


def _pick_plan(args) -> list:
    """返回 [(段名, 起, 止, 组名, 族, cfg覆盖, router覆盖), …] ✓"""
    if args.start and args.end:
        segments = [('custom', args.start, args.end)]
    else:
        names = [s.strip() for s in (args.segments or ','.join(SEGMENTS)).split(',') if s.strip()]
        segments = [(n, *SEGMENTS[n]) for n in names if n in SEGMENTS]
        unknown = [n for n in names if n not in SEGMENTS]
        if unknown:
            print(f'⚠ 未知段名（忽略 ✗）: {unknown}；可选: {list(SEGMENTS)}')

    want = [x.strip() for x in (args.groups or '').split(',') if x.strip()]
    plan = []
    for seg, start, end in segments:
        for family, groups in (('A', GROUPS_A), ('B', groups_b())):
            if args.family != 'all' and args.family.upper() != family:
                continue
            for name, cfg_extra, router_extra in groups:
                if want and name not in want and seg not in want:
                    continue
                plan.append((seg, start, end, name, family, cfg_extra, router_extra))
    return plan


def main():
    ap = argparse.ArgumentParser(description='ADX/入池 A/B 跑测（§12 ✓，A/B 两族 + 三段 ✓）')
    ap.add_argument('--strategy', required=True, help='策略名，如 金三角策略 / 多方炮策略')
    ap.add_argument('--start', default='', help='自定义区间起点（与 --end 同时给 ⇒ 只跑这一段 ✓）')
    ap.add_argument('--end', default='', help='自定义区间终点')
    ap.add_argument('--segments', default='', help='段名，逗号分隔（默认三段全跑 ✓）: '
                                                  + ','.join(SEGMENTS))
    ap.add_argument('--family', default='all', choices=['all', 'A', 'B', 'a', 'b'],
                    help='A=普通引擎 ✓；B=大盘路由引擎 ✓（G2 只在 B 生效 ✗✓）')
    ap.add_argument('--groups', default='', help='只跑指定组 / 段名，逗号分隔')
    ap.add_argument('--save', action='store_true', help='把结果写入 backtest_result（默认**不写** ✗）')
    ap.add_argument('--out', default='', help='CSV 输出路径（默认 data/runs/adx_ab_<时间戳>.csv）')
    args = ap.parse_args()

    plan = _pick_plan(args)
    # ★【2026-09-27】B 族两臂**当场自证** ✓（防"看日志猜开关" ✗✓）：
    #   `R2` 存的是**取反值** ✓ ⇒ 反推 yaml 现值 ✓（不再多构造一个 router ✓）
    if str(args.family).upper() in ('ALL', 'B'):
        _arms = groups_b()
        _base = _arms[0][2].get('dir_mode') or 'two_day(默认)'
        _other = _arms[1][2].get('dir_mode')
        print(f'B 族 ✓：{_arms[0][0]} = **跟随生产 yaml** ⇒ dir口径={_base} ✓'
              f'（= **生产现状** ✓）；{_arms[1][0]} = **另一档** ⇒ dir口径={_other} ✗'
              f'    〔2026-09-28 ✓：降温机制已移除，对照变量改为**方向口径** ✓〕')
    if not plan:
        print('没有匹配的组合 ✗。A 族组名: ' + ', '.join(g[0] for g in GROUPS_A))
        print('                     B 族组名: ' + ', '.join(g[0] for g in groups_b()))
        return 2

    base = load_base_config(args.strategy)
    print('=' * 92)
    print('ADX / 入池 A/B 跑测 ✓')
    print(f'  策略={args.strategy}  计划={len(plan)} 次'
          f'（A 族=普通引擎 ✓ / B 族=大盘路由引擎 ✓，**跨族不可比** ✗✓）')
    print('=' * 92)

    rows = []
    for seg, start, end, name, family, cfg_extra, router_extra in plan:
        cfg = dict(base)
        cfg.update(cfg_extra)
        cfg['start_date'] = start
        cfg['end_date'] = end
        cfg['_group'] = name
        print(f'\n>>> [{seg}] {name}（族 {family} ✓）  变更={json.dumps(cfg_extra, ensure_ascii=False) or "（无 ✓）"}'
              + (f'  router={json.dumps(router_extra, ensure_ascii=False)}'
                 if router_extra else ''))
        if family == 'A':
            print('    ⚠ 族 A = `BacktestEngine`（普通引擎）⇒ **不含** `RegimeRouter` ✗ ⇒ '
                  '`enable_adx_falloff`（大盘降温）在此**不生效** ✗✓ —— '
                  '日志里没有降温记录是**正常的** ✓；要看降温请跑 `--family B` ✓')
        try:
            m = run_one(args.strategy, cfg, family=family,
                        router_config=router_extra, save=args.save)
        except Exception as e:
            print(f'!! [{seg}] {name} 失败 ✗: {e}')
            rows.append({'segment': seg, 'family': family, 'group': name, 'error': str(e)})
            continue
        # ★ **把该组的 router 配置写进 CSV** ✓（自证式 A/B ✓：日后翻 CSV 就知道
        #   `enable_adx_falloff` 到底开没开 ✗✓，不必回看控制台日志 ✗）
        rows.append({'segment': seg, 'family': family, 'group': name,
                     'router': json.dumps(router_extra or {}, ensure_ascii=False), **m})
        print(f'    完成 ✓ 笔数={m.get("total_trades")} 胜率={m.get("win_rate")} '
              f'收益={m.get("total_return")} 回撤={m.get("max_drawdown")} '
              f'夏普={m.get("sharpe_ratio")}  ({m.get("seconds")}s)')

    # ---- 汇总表 ✓（按 段 × 族 分组 ✓，族内才可比 ✗✓）----
    print('\n' + '=' * 92)
    print('汇总 ✓（判据见 §12.4：**任一段显著变差 ⇒ 该开关不上线** ✗✓）')
    print('=' * 92)
    for seg in {r['segment'] for r in rows}:
        for fam in ('A', 'B'):
            sub = [r for r in rows if r['segment'] == seg and r['family'] == fam]
            if not sub:
                continue
            print(f'\n[{seg}] 族 {fam} ✓（**基线 = 该族第一行** ✓，只比**相对差异** ✗）')
            print(f'{"组":<20}{"笔数":>7}{"胜率":>9}{"总收益":>11}{"回撤":>10}{"夏普":>9}{"耗时s":>8}')
            for r in sub:
                if 'error' in r:
                    print(f'{r["group"]:<20}  失败 ✗ {r["error"][:44]}')
                    continue
                print(f'{r["group"]:<20}{int(r.get("total_trades") or 0):>7}'
                      f'{float(r.get("win_rate") or 0):>9.1f}'
                      f'{float(r.get("total_return") or 0):>11.2f}'
                      f'{float(r.get("max_drawdown") or 0):>10.2f}'
                      f'{float(r.get("sharpe_ratio") or 0):>9.2f}'
                      f'{float(r.get("seconds") or 0):>8.1f}')

    out = args.out or str(Path('data/runs') / f'adx_ab_{datetime.now():%Y%m%d_%H%M%S}.csv')
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    keys = ['segment', 'family', 'group'] + list(METRICS) + ['final_capital', 'seconds', 'error']
    with open(out, 'w', encoding='utf-8-sig') as f:
        f.write(','.join(keys) + '\n')
        for r in rows:
            f.write(','.join(str(r.get(k, '')) for k in keys) + '\n')
    print(f'\nCSV 已写入 ✓ {out}')
    print('提醒 ✓：① 只在**族内**比相对差异 ✗（跨族引擎不同 ✗，§12.3 ✓）；'
          '② 三段须**同号**才算过 ✓（AC7 ✓）；③ 笔数过少 ⇒ 不足以决策 ✗（继续观察 ✓）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
