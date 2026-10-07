# -*- coding: utf-8 -*-
"""回填回测绩效三指标：avg_return / profit_factor / avg_hold_days（2026-09-22 口径修正）

一、为什么需要回填（口径问题）
  1) profit_factor 原实现用**单笔收益率(%)** 求和 ✗ → 每笔等权、完全无视仓位大小 ✗；
     标准口径应为**金额口径** = 总盈利金额 / |总亏损金额|（Gross Profit / Gross Loss）✓
     （实测样本 #185：旧值 1.77 ✗ vs 金额口径 2.45 ✓）
     另外原实现"无亏损时把分母兜底为 1"✗ → 会算出"总盈利百分比"这类无意义值 ✗
  2) avg_return / avg_hold_days 原实现未过滤空值 ✗（键存在但值为 None 时仍进均值 ✗ → nan ✗）
  3) avg_hold_days 从未落库 ✗（三条保存路径漏传该字段 ✗）→ 全库恒为 0 ✗

二、回填口径（与回测引擎 BacktestEngine._calculate_performance 完全一致）
  · 交易集合 = backtest_trade 中**已平仓**的行
      —— 引擎口径是 `sell_date is not None` ✓；
      ⚠️ 注意：未平仓行在库中存的是**空字符串 ''** 而不是 NULL ✗，
         所以必须写 `sell_date IS NOT NULL AND TRIM(sell_date) <> ''` ✓，
         否则会把首仓/加仓行（return_rate/hold_days 为 0 ✗）算进均值、把结果稀释数倍 ✗
  · avg_return     = mean(return_rate)                        ，单位 % ✓
  · profit_factor  = Σprofit_loss>0 金额 / |Σprofit_loss<0| ✓
                     无亏损但有盈利 → 99.99（上限哨兵 ✓，与 backtest_engine 常量一致 ✓）
  · avg_hold_days  = mean(hold_days)                          ，单位**交易日** ✓

三、用法
  python tools/backfill_backtest_metrics.py                      # 预览（dry-run，绝不改库 ✓）
  python tools/backfill_backtest_metrics.py --apply               # 真正回写（先备份旧值到 JSON ✓）
  python tools/backfill_backtest_metrics.py --ids 185,201 --apply # 只回填指定结果 ✓
"""
import argparse
import io
import json
import os
import sys
from datetime import datetime

# ⚠️【2026-10-07 ✓】本脚本已移入 `tools/` ⇒ 插入**仓库根**（上一级 ✓），
#   否则 `from utils...` 会因 sys.path 指向 `tools/` 而**导入失败** ✗✓
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.global_db import get_global_db

# 与 trading/backtest_engine.py 的 PROFIT_FACTOR_NO_LOSS_CAP 保持一致 ✓
NO_LOSS_CAP = 99.99

# 已平仓交易的判定（与引擎 completed_trades 等价 ✓）：
#   sell_date 非 NULL 且非空串（未平仓行存的是 '' ✗）
CLOSED_FILTER = "sell_date IS NOT NULL AND TRIM(sell_date) <> ''"


def _compute(trades):
    """按新口径计算三指标，trades 为已平仓交易行"""
    rets = [float(t['return_rate']) for t in trades if t.get('return_rate') is not None]
    hds = [float(t['hold_days']) for t in trades if t.get('hold_days') is not None]
    amounts = [float(t.get('profit_loss') or 0) for t in trades]
    gross_profit = sum(a for a in amounts if a > 0)
    gross_loss = abs(sum(a for a in amounts if a < 0))
    if gross_loss > 0:
        pf = gross_profit / gross_loss
    else:
        pf = NO_LOSS_CAP if gross_profit > 0 else 0.0
    return {
        'avg_return': round(sum(rets) / len(rets), 6) if rets else 0.0,
        'profit_factor': round(pf, 6),
        'avg_hold_days': round(sum(hds) / len(hds), 6) if hds else 0.0,
        '_n_trades': len(trades),
        '_n_ret': len(rets),
        '_n_hold': len(hds),
        '_gross_profit': round(gross_profit, 2),
        '_gross_loss': round(gross_loss, 2),
    }


def main():
    ap = argparse.ArgumentParser(description='回填回测绩效三指标（avg_return/profit_factor/avg_hold_days）')
    ap.add_argument('--apply', action='store_true', help='真正写入数据库（默认仅预览）')
    ap.add_argument('--ids', default='', help='只处理指定结果ID，逗号分隔；留空=全部')
    ap.add_argument('--backup-dir', default='data/backups', help='旧值备份目录')
    args = ap.parse_args()

    db = get_global_db()

    ids = [int(x) for x in args.ids.split(',') if x.strip()] if args.ids.strip() else None
    if ids:
        rows = []
        for rid in ids:
            r = db.query('SELECT * FROM backtest_result WHERE id = ?', (rid,))
            rows.extend(r)
    else:
        rows = db.query('SELECT * FROM backtest_result ORDER BY id')

    print('=== 回填回测绩效三指标（%s）===' % ('写入' if args.apply else '预览，不改库'))
    print('扫描 backtest_result 行数 = %d' % len(rows))
    if not rows:
        print('无数据，结束')
        return

    updates = []      # (id, new, old, stats)
    skipped = []      # (id, reason)
    warn_win = []     # win/total 与库内交易不一致的（本次不修，仅提示 ✓）

    for r in rows:
        r = dict(r)
        rid = r['id']
        trades = [dict(t) for t in db.query(
            "SELECT trade_type, return_rate, profit_loss, hold_days FROM backtest_trade "
            "WHERE result_id = ? AND " + CLOSED_FILTER, (rid,))]
        if not trades:
            skipped.append((rid, '无已平仓交易记录'))
            continue

        new = _compute(trades)
        old = {
            'avg_return': r.get('avg_return') or 0,
            'profit_factor': r.get('profit_factor') or 0,
            'avg_hold_days': r.get('avg_hold_days') or 0,
        }
        changed = any(abs(old[k] - new[k]) > 1e-6 for k in old)
        if changed:
            updates.append((rid, new, old, {
                'n': new['_n_trades'], 'gp': new['_gross_profit'], 'gl': new['_gross_loss'],
            }))

        # 附带体检：胜率/交易数是否与库内交易一致（不属于本次回填范围 ✓，仅提示 ✓）
        rets = [float(t['return_rate']) for t in trades if t.get('return_rate') is not None]
        win = sum(1 for v in rets if v > 0)
        if abs(float(r.get('win_rate') or 0) - (win / len(rets) * 100 if rets else 0)) > 0.05:
            warn_win.append((rid, r.get('win_rate'), round(win / len(rets) * 100, 2) if rets else 0))

    print('需回填 = %d 行；跳过（无已平仓交易）= %d 行' % (len(updates), len(skipped)))

    # ---------- 明细（最多展示 15 行）----------
    print('--- 明细（最多 15 行）：ID | avg_return 旧→新 | profit_factor 旧→新 | avg_hold_days 旧→新 ---')
    for rid, new, old, st in updates[:15]:
        print('  #%-5s | %-22s | %-30s | %s'
              % (rid,
                 '%.4f → %.4f' % (old['avg_return'], new['avg_return']),
                 '%.4f → %.4f' % (old['profit_factor'], new['profit_factor']),
                 '%.4f → %.4f' % (old['avg_hold_days'], new['avg_hold_days'])))
    if len(updates) > 15:
        print('  ...（其余 %d 行省略）' % (len(updates) - 15))

    # ---------- 汇总 ----------
    n_pf = sum(1 for _, n, o, _ in updates if abs(n['profit_factor'] - o['profit_factor']) > 1e-6)
    n_ar = sum(1 for _, n, o, _ in updates if abs(n['avg_return'] - o['avg_return']) > 1e-6)
    n_hd = sum(1 for _, n, o, _ in updates if abs(n['avg_hold_days'] - o['avg_hold_days']) > 1e-6)
    print('变更统计：profit_factor %d 行 / avg_return %d 行 / avg_hold_days %d 行' % (n_pf, n_ar, n_hd))
    cap_rows = [rid for rid, n, _, _ in updates if abs(n['profit_factor'] - NO_LOSS_CAP) < 1e-6]
    if cap_rows:
        print('其中 profit_factor 取"无亏损上限 %.2f"的结果：%s' % (NO_LOSS_CAP, cap_rows[:10]))
    if warn_win:
        print('提示：另有 %d 行的 win_rate 与库内交易复算不一致（本次未修 ✗，供后续排查）：' % len(warn_win))
        for rid, a, b in warn_win[:8]:
            print('   #%s 存库=%.2f%% 复算=%.2f%%' % (rid, float(a or 0), b))

    if not args.apply:
        print('（预览模式，未改库 ✓ 加 --apply 执行写入）')
        return

    # ---------- 备份旧值 ----------
    os.makedirs(args.backup_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(args.backup_dir, 'backtest_metrics_before_%s.json' % stamp)
    with io.open(backup_path, 'w', encoding='utf-8') as f:
        json.dump({str(rid): old for rid, _, old, _ in updates}, f, ensure_ascii=False, indent=2)
    print('旧值已备份 → %s' % backup_path)

    # ---------- 写入 ----------
    ok, fail = 0, 0
    for rid, new, old, _ in updates:
        try:
            db.execute(
                'UPDATE backtest_result SET avg_return = ?, profit_factor = ?, avg_hold_days = ? WHERE id = ?',
                (new['avg_return'], new['profit_factor'], new['avg_hold_days'], rid))
            ok += 1
        except Exception as e:
            fail += 1
            print('回填失败 #%s: %s' % (rid, e))
    db.connect().commit()
    print('回填完成：成功 %d 行，失败 %d 行' % (ok, fail))


if __name__ == '__main__':
    main()
