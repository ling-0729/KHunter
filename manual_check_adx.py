# -*- coding: utf-8 -*-
"""★ **手工验收自检** ✓ —— 一条命令跑完，只看 ✓/✗ 表 ✓（2026-09-27 ✓）

    python manual_check_adx.py

**口径** ✓：**所有参数以 yaml 文件配置为准** ✓ ——
  · 回测/实盘参数 = `config/backtest_engine_config.yaml`（`backtest_mode` 顶层键 ✓ + `backtest:` 节 ✓）
  · 大盘路由/降温 = `config/regime_router.yaml`
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
            + f" | 降温={rt.get('enable_adx_falloff')} 确认={rt.get('confirm_days')}")
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


# ---------------------------------------------------------------- ⑤ 三态原语
def _machine():
    from utils import stock_adx_state as S
    cases = [
        ([10.0, 21.0, 26.0], '明确', False, '正常换挡（21≥21 ✓ 26≥26 ✓）'),
        ([30.0, 24.0, 24.8], '萌芽', False, '反转日按原值 ✓（迟滞托住却不吃 buffer ✓）'),
        ([45.0, 41.0, 38.0], '震荡', True, '从 40+ 连降两日 ⇒ 降温 ✓'),
        ([45.0, 41.0, 38.0, 39.5], '震荡', True, '降温中仅一日回升 ⇒ 仍压 ✓'),
        ([60.0, 50.0, 20.0, 24.0, 28.0], '明确', False, '连升两日 ⇒ 解除 ✓（无 >25 门槛 ✓）'),
    ]
    bad = []
    for vals, want_band, want_cooled, _why in cases:
        st = S.AdxState()
        for v in vals:
            st = S.step(st, v)
        if st.band != want_band or bool(st.cooled) != want_cooled:
            bad.append(f'{vals}⇒{st.band}/{st.cooled}(期望 {want_band}/{want_cooled})')
    return not bad, ('5 例全过 ✓' if not bad else ' ✗ '.join(bad))


# ---------------------------------------------------------------- ⑥ 接线检查
def _wiring():
    need = {
        'trading/backtest_engine.py': ['stock_adx', 'merge_backtest_defaults',
                                       'log_backtest_params'],
        'trading/regime_router.py': ['is_mid_reversal', 'enable_adx_falloff'],
        'trading/regime_backtest_engine.py': ['_warmup_router'],   # ★ 预热 ✓（起点无关 ✗）
        'trading/strategy_runner.py': ['stock_adx'],          # 实盘首仓/加仓 ✓
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
    print('★ ADX / 大盘降温 —— 手工验收自检 ✓（所有参数以 yaml 为准 ✓）')
    print('=' * 96)
    check('① yaml 参数快照', _yaml_snapshot)
    check('② 个股 ADX 覆盖率（近 60 交易日）', _stock_adx_gate)
    check('③ 大盘 ADX 起点 + 状态预热', _index_adx_gate)
    check('④ 启动迁移审计', _migration)
    check('⑤ 三态原语（换挡/反转日/降温/解除）', _machine)
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
