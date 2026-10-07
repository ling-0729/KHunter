# -*- coding: utf-8 -*-
"""★ **手工验收自检** ✓ —— 一条命令跑完，只看 ✓/✗ 表 ✓（2026-09-27 ✓）

    python tools/manual_check_adx.py

**口径** ✓：**所有参数以 yaml 文件配置为准** ✓ ——
  · 回测/实盘参数 = `config/backtest_engine_config.yaml`（`backtest_mode` 顶层键 ✓ + `backtest:` 节 ✓）
  · 大盘路由（档位 = `band`+`dir`+高位守门 ✓）= `config/regime_router.yaml`
  · 个股 ADX 日更 = `config/config.yaml` 的 `update.stock_adx.enabled` ✓

**范围** ✓：只读 ✓、**不联网** ✓、**不跑回测** ✓（秒级 ✓）。
"""
import logging
import sqlite3
import sys

sys.path.insert(0, '.')
logging.disable(logging.CRITICAL)          # 自检只输出结论 ✓

from pathlib import Path                                            # noqa: E402

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'stock_selection.db'

_rows = []


def check(name, fn):
    try:
        ok, note = fn()
    except Exception as e:
        ok, note = False, f'{type(e).__name__}: {str(e)[:80]}'
    _rows.append((name, bool(ok), note))
    return ok


def _conn():
    from utils.global_db import get_global_db
    return get_global_db().connect()


# ---------------------------------------------------------------- ① yaml 参数
def _yaml_snapshot():
    import yaml
    eng = yaml.safe_load((ROOT / 'config' / 'backtest_engine_config.yaml')
                         .read_text(encoding='utf-8')) or {}
    rt = (yaml.safe_load((ROOT / 'config' / 'regime_router.yaml')
                         .read_text(encoding='utf-8')) or {}).get('regime_router') or {}
    from utils.backtest_mode import effective
    vals = {k: effective(k) for k in ('enable_stock_adx_filter', 'pool_entry_mode',
                                      'enable_add_open_rise_check')}
    note = (f"模式={eng.get('backtest_mode')} | 生效: "
            + ' '.join(f'{k}={v}' for k, v in vals.items())
            + f" | 入场={effective('adx_entry_mode', default='range')}"
              f"{list(effective('adx_entry_range', default=[21, 30]) or [])}"
              f"（上限仅首仓 ✓）"
            + f" | dir_mode={rt.get('dir_mode') or 'two_day(默认)'}"
              f" 确认={rt.get('confirm_days')}"
              f" auto_warmup={rt.get('auto_warmup')}"
            # ★【2026-09-28 用户口径 ✓】**当日仓位上限** ✓（仅开新仓 ✓、阈值/比例可配 ✓）
            #   ⚠️ 原「大盘 ADX 硬闸门」**已整体取消** ✗（"由仓位上限总控"✓）
            + f" | 仓位上限={'开' if effective('enable_index_position_cap') else '关'}"
              f"(ADX>{effective('index_cap_high_adx', default=25):g} 且上升⇒"
              f"{effective('index_cap_high_ratio', default=1.0):.0%} ✓；"
              f"ADX<{effective('index_cap_low_adx', default=18):g} 且上升⇒"
              f"{effective('index_cap_low_ratio', default=0.5):.0%} ✓；"
              f"其他⇒{effective('index_cap_other_ratio', default=0.0):.0%}"
              f"({'不允许开仓 ✓' if float(effective('index_cap_other_ratio', default=0.0) or 0) <= 0 else '兜底 ✓'})"
              f" 仅开新仓 ✓ 加仓不受限 ✓)")
    return True, note


# ---------------------------------------------------------------- ② 个股 ADX 列与闸门
def _stock_adx_gate():
    from utils.backtest_data_gate import check_adx
    conn = _conn()
    row = conn.execute("SELECT MAX(date) FROM stock_kline").fetchone()
    end = row[0]
    start = conn.execute("SELECT MIN(date) FROM (SELECT date FROM stock_kline "
                         "GROUP BY date ORDER BY date DESC LIMIT 60)").fetchone()[0]
    it = check_adx(conn, start, end)
    return it['ok'], (f"{start} ~ {end}：真缺口 {it.get('missing_rows')} 行"
                      f"（占比 {it.get('missing_ratio', 0):.4%}）预热 NULL "
                      f"{it.get('expected_warmup_nulls')} 行 ✓")


# ---------------------------------------------------------------- ③ 指数 ADX 起点/预热
def _index_adx_gate():
    from utils.backtest_data_gate import check_index_adx
    conn = _conn()
    it = check_index_adx(conn, '2025-01-01', '2026-09-24', required=True)
    return it['ok'], (f"起点 {it.get('first_date')} ✓ 预热 {it.get('pre_start_days')} 交易日 "
                      f"（≥{it.get('min_warmup_days')} ✓）")


# ---------------------------------------------------------------- ④ 迁移审计
def _migration():
    """**审计表存在** ✓ 即可通过 ✓ —— 历史行**允许为空** ✗✓

    ⚠️ 说明 ✗✓：本库 `adx` 列是在"审计漏记 bug"**修复前**加的 ✓ ⇒ 那一笔**注定没有记录** ✗
    （不伪造 ✓）。自 2026-09-27 起 `run_startup_migrations` **无论是否迁移**都会先建表 ✓
    ⇒ 此后每一次真实迁移都会留痕 ✓。
    """
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                     "AND name='schema_migration_log'").fetchone()[0]
    if not n:
        return False, 'schema_migration_log 不存在 ✗（跑一次启动迁移即建 ✓：见下方提示 ✓）'
    rows = conn.execute("SELECT name, action FROM schema_migration_log "
                        "ORDER BY id").fetchall()
    hit = [r for r in rows if 'adx' in str(r[0])]
    return True, (f'审计表已就绪 ✓；记录 {len(rows)} 条'
                  + (f'；adx 相关 {hit} ✓' if hit else '（历史那笔在修复前 ⇒ 本就无记录 ✓）'))


# ---------------------------------------------------------------- ⑤ 状态机与判定式
def _machine():
    """★【2026-09-28 定稿 ✓】自检：三态原语 + **唯一判定式** `regime_of` ✓

    核验 ✓：① `band` 迟滞（含**反转日不吃缓冲** ✓）；② `dir` **两日同向** ＋ **没方向沿用前一日** ✓；
            ③ `regime_of` 三条 + **铁律**（`dir ≠ 上升` ⇒ **绝不**判「明确」✓）。
    ⚠️ 原"降温"（`cooled` ✓）已整体移除 ✗✓（见设计说明书 §5.0 ✓）。
    """
    from utils import stock_adx_state as S
    cases = [
        ([10.0, 21.0, 26.0], '明确', '正常换挡（21≥21 ✓ 26≥26 ✓）'),
        # 反转日 ✓：迟滞托住「明确」✓ + **两日连升** ✓ ⇒ 当日按原值 24.8 直判 ⇒ 萌芽 ✓
        ([30.0, 24.0, 24.4, 24.8], '萌芽', '反转日按原值 ✓（迟滞托住却不吃 buffer ✓）'),
        # 高位守门**不是**降温 ✗：`regime_of` 看当日 `adx`/`dir` ⇒ 只改**结论档** ✓，不改 `band` ✓
        ([45.0, 41.0, 38.0], '明确', 'band 迟滞仍托住 ✓（原值 38 ≥ 25 ⇒ 明确 ✓）'),
    ]
    bad = []
    for vals, want_band, _why in cases:
        st = S.AdxState()
        for v in vals:
            st = S.step(st, v)
        if st.band != want_band:
            bad.append(f'{vals}⇒band={st.band}(期望 {want_band})')
    # ② 方向 ✓：两日同向才改向 ✓；**没方向沿用前一日** ✓（用户 2026-09-28 口径 ✓）
    for vals, want_dir in (([20.0, 22.0, 24.0], '上升'),
                           ([20.0, 22.0, 24.0, 23.0], '上升'),   # ★ 一升一降 ⇒ 沿用 ✓
                           ([30.0, 28.0], ''),
                           ([30.0, 28.0, 26.0, 27.0], '下降')):   # ★ 一降一升 ⇒ 沿用 ✓
        st = S.AdxState()
        for v in vals:
            st = S.step(st, v)
        if st.dir != want_dir:
            bad.append(f'{vals}⇒dir={st.dir or "未定"}(期望 {want_dir or "未定"})')
    # ③ 判定式 ✓（含"迟滞托住的 24.5 + dir=下降 ⇒ 萌芽"这条 **bug 回归** ✓）
    for band, d, a, want in (('明确', '上升', 45.0, '明确'),
                             ('明确', '下降', 45.0, '震荡'),      # ★ 高位守门 ✓
                             ('明确', '下降', 24.5, '萌芽'),      # ★ 按 band 判 ✓（bug 回归 ✓）
                             ('明确', '', 30.0, '萌芽'),          # ★ 方向未定 ⇒ 降档 ✓
                             ('萌芽', '上升', 22.0, '萌芽')):
        got = S.regime_of(S.AdxState(band=band, dir=d, adx=a))
        if got != want:
            bad.append(f'regime_of({band},{d or "未定"},{a})⇒{got}(期望 {want})')
    for b in ('', '震荡', '萌芽', '明确'):
        for a in (24.5, 30.0, 40.0, 60.0):
            if S.regime_of(S.AdxState(band=b, dir='下降', adx=a)) == '明确':
                bad.append(f'★ 铁律破坏：dir=下降 却判明确（band={b}, adx={a}）')
    total = len(cases) + 4 + 5 + 16
    return not bad, (f'{total} 项全过 ✓' if not bad else ' ✗ '.join(bad))


# ---------------------------------------------------------------- ⑥ 接线检查
def _wiring():
    need = {
        'trading/backtest_engine.py': ['stock_adx', 'merge_backtest_defaults',
                                       'log_backtest_params',
                                       '_resolve_end_date'],       # ★ 终点回退 ✓（当日未收盘 ✗）
        'utils/trade_date_utils.py': ['resolve_end_date_for_data'],  # ★ 回退规则**单一实现** ✓
        'utils/backtest_data_gate.py': ['_today_hint'],              # ★ 缺当天 ⇒ 可执行指引 ✓
        # ★【2026-09-28】大盘档位 = **个股同一函数** ✓（`regime_of` ✓ + 高位守门 ✓ + 方向口径 ✓）
        'trading/regime_router.py': ['is_mid_reversal', 'regime_of',
                                     'HIGH_ADX_GUARD', '_dir_mode', '_adx_state'],
        'trading/stock_adx_filter.py': ['format_gate_result',     # ★ 闸门"通过留痕" ✓
                                        'dir_mode=_resolve_dir_mode',   # ★ 方向口径接线 ✓
                                        'entry_allowed',          # ★ 入场档位集合 ✓（可配置 ✓）
                                        'describe_adx_params'],   # ★ ADX 参数摘要 ✓（回测/实盘同一 ✓）
        'trading/regime_backtest_engine.py': ['_warmup_router'],   # ★ 回测预热 ✓（起点无关 ✗）
        'trading/strategy_runner.py': ['stock_adx',           # 实盘首仓/加仓 ✓
                                       '【实盘参数】',         # ★ 运行参数快照 ✓（2026-09-28 ✓）
                                       '【实盘·ADX】'],        # ★ ADX 摘要 ✓（与回测同一函数 ✓）
        # ★【2026-09-28 用户口径 ✓】**当日仓位上限** ✓（"开新仓"的唯一大盘判据 ✓；
        #   仅首仓 ✓；`_state_at` **单一取数口** ✓ —— 原「大盘 ADX 硬闸门」已取消 ✗）
        'trading/index_adx_filter.py': ['index_position_cap_gate', 'enable_index_position_cap',
                                        'index_cap_low_ratio', 'index_cap_other_ratio',
                                        '不允许开仓', '_state_at', 'index_cap_high_ratio',
                                        # ★【2026-09-29 用户要求 ✓】不开新仓 ⇒ 跳过选股（**开关** ✓）
                                        'should_skip_selection_when_blocked',
                                        # ★【2026-10-05 用户要求 ✓】**板块回退**（全A 不放行 ⇒
                                        #   按科创板/创业板指数**部分放行**，且**只买对应板块** ✓）
                                        'index_cap_board_fallback', 'classify_board',
                                        'board_release_cap', 'any_board_release'],
        'trading/backtest_engine.py': ['_day_no_new_position',   # ★ 日级跳过选股 ✓（开关 ✓）
                                       '【跳过选股】'],
        'utils/stock_adx.py': ['def ensure_column', 'def run_selfheal'],
        'utils/kline_initializer.py': ['stock_adx'],
        'utils/data_collection_service.py': ['stock_adx'],
    }
    bad = []
    for rel, keys in need.items():
        p = ROOT / rel
        src = p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''
        miss = [k for k in keys if k not in src]
        if miss:
            bad.append(f'{rel} 缺 {miss}')
    return not bad, (f'{len(need)} 处全部接线 ✓' if not bad else ' ✗ '.join(bad))


# ---------------------------------------------------------------- ⑦ 配置一致性
def _yaml_vs_db():
    import yaml
    conn = _conn()
    sec = (yaml.safe_load((ROOT / 'config' / 'backtest_engine_config.yaml')
                          .read_text(encoding='utf-8')) or {}).get('backtest') or {}
    if not (DB.exists()):
        return True, '（无库 ⇒ 跳过 ✓）'
    cols = [r[1] for r in conn.execute('PRAGMA table_info(backtest_config)')]
    row = conn.execute('SELECT * FROM backtest_config LIMIT 1').fetchone()
    if not row:
        return True, '（backtest_config 空 ⇒ 跳过 ✓）'
    d = dict(zip(cols, row))
    diff = [k for k, v in sec.items()
            if k in d and d[k] is not None and float(v) != float(d[k])]
    return not diff, ('yaml `backtest:` 与 DB 一致 ✓' if not diff
                      else f'不一致 ✗: {diff}（请同步 yaml 或 DB ✓）')


def main():
    print('=' * 96)
    print('★ ADX / 大盘档位 —— 手工验收自检 ✓（所有参数以 yaml 为准 ✓）')
    print('=' * 96)
    check('① yaml 参数快照', _yaml_snapshot)
    check('② 个股 ADX 覆盖率（近 60 交易日）', _stock_adx_gate)
    check('③ 大盘 ADX 起点 + 状态预热', _index_adx_gate)
    check('④ 启动迁移审计', _migration)
    check('⑤ 状态机与判定式（换挡/反转日/方向/守门）', _machine)
    check('⑥ 写入方与消费方接线', _wiring)
    check('⑦ yaml `backtest:` 与 DB 一致', _yaml_vs_db)

    print()
    for name, ok, note in _rows:
        print(f'{"✓" if ok else "✗"} {name:<34} {note}')
    bad = [n for n, ok, _ in _rows if not ok]
    print('-' * 96)
    print(f'结论：{"**全部通过 ✓**" if not bad else "**有 " + str(len(bad)) + " 项未过 ✗**: " + ", ".join(bad)}')
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
