# -*- coding: utf-8 -*-
"""TD Sequential（九转）序列计算 —— 共享实现（2026-09-20）

来源与约束
----------
本模块从 `strategy/disabled/low_td9_strategy._run_td_state_machine` 抽取：

  1) **买入（下跌/底部）线逐条复刻原实现**（选股策略依赖它，语义禁止变化）；
  2) 新增**卖出（上升/顶部）线的镜像序列**（原实现仅有"卖出 Setup 完成"用于取消，
     没有卖出 Countdown）；
  3) 新增**逐 bar 序号**（原实现只有聚合结果），供股票详情页在 K 线上标注 1..9。

规则（调用方传入**倒序** df，index=0 最新；内部翻转为时间序计算）
-----------------------------------------------------------------
  买入 Setup    : close[i] <  close[i-4] 连续 9 根 → 激活买入 Countdown
  买入 Countdown: close[i] <= close[i-2] 累计 9 根（不满足归零；卖出 Setup 完成 → 取消）
  卖出 Setup    : close[i] >  close[i-4] 连续 9 根 → 激活卖出 Countdown（镜像新增）
  卖出 Countdown: close[i] >= close[i-2] 累计 9 根（不满足归零；买入 Setup 完成 → 取消）
  取消规则仅在 enable_cancellation=True 时生效。

与原文的差异说明（买入线**零差异**）
------------------------------------
原文的 `sell_setup_cnt`（取消计数器）仅在**买入 Countdown 激活**时统计。
本模块把卖出线拆成**独立状态**：卖出 Setup 计数（用于激活卖出 Countdown）只在
"卖出 Countdown 未激活"时进行，取消买入 Countdown 仍沿用原文的独立计数器。
两套计数器互不共用，因此买入线结果与原文完全一致（详见单测的逐条比对）。
"""
from typing import Dict, List

import pandas as pd

BUY_SETUP = 'buy_setup'
BUY_COUNTDOWN = 'buy_countdown'
SELL_SETUP = 'sell_setup'
SELL_COUNTDOWN = 'sell_countdown'

LEGACY_KEYS = ('setup_done', 'setup_end_pos', 'countdown_complete',
               'countdown_end_pos', 'cancelled')


def compute_td_marks(df, setup_window: int = 9, setup_offset: int = 4,
                     countdown_offset: int = 2, countdown_target: int = 9,
                     enable_cancellation: bool = True,
                     only_complete: bool = True) -> Dict:
    """计算四条 TD 序列的逐 bar 序号（并保留原状态机的聚合结果）

    Args:
        df: 含 close（建议含 date）的 DataFrame，**倒序**（index=0 最新）
        setup_window/setup_offset/countdown_offset/countdown_target: 与策略默认一致
        enable_cancellation: 是否启用"反向 Setup 完成即取消"规则

    Returns:
        dict:
          marks: [{date, pos, type, seq, cancelled}]（按时间升序，pos 为时间序下标）
          buy_view: 原 `_run_td_state_machine` 的 5 个键（策略委托用）
          buy_countdown_complete_on / sell_countdown_complete_on: 完成日（str 或 None）
          bars: 参与计算的 bar 数
          顶层同时含 LEGACY_KEYS，便于直接 `return`。
    """
    out = {
        'marks': [],
        'buy_view': {},
        'buy_countdown_complete_on': None,
        'sell_countdown_complete_on': None,
        'bars': 0,
        # 原状态机聚合结果（默认值）
        'setup_done': False,
        'setup_end_pos': -1,
        'countdown_complete': False,
        'countdown_end_pos': -1,
        'cancelled': False,
    }
    if df is None or len(df) == 0 or 'close' not in getattr(df, 'columns', []):
        out['buy_view'] = {k: out[k] for k in LEGACY_KEYS}
        return out

    n = len(df)
    out['bars'] = n
    close_fwd = df['close'].iloc[::-1].reset_index(drop=True)
    dates_fwd = (df['date'].iloc[::-1].reset_index(drop=True)
                 if 'date' in df.columns else pd.Series([None] * n))

    def _d(i):
        v = dates_fwd.iloc[i]
        return None if v is None or pd.isna(v) else str(v)[:10]

    marks: List[Dict] = []

    def _push(i, kind, seq):
        marks.append({'date': _d(i), 'pos': i, 'type': kind,
                      'seq': int(seq), 'cancelled': False})

    def _mark_cancelled(kind):
        """把最近一段该方向的 Countdown 标记为"被取消"（前端灰显）"""
        for m in reversed(marks):
            if m['type'] != kind:
                break
            m['cancelled'] = True

    def _cmp(i, off, op):
        """close[i] op close[i-off]，数据不足/NaN → False"""
        if i < off or off <= 0:
            return False
        a, b = close_fwd.iloc[i], close_fwd.iloc[i - off]
        if pd.isna(a) or pd.isna(b):
            return False
        return a < b if op == '<' else (a <= b if op == '<=' else
                                        (a > b if op == '>' else a >= b))

    # ---------------- 状态（命名对齐原文） ----------------
    buy_setup_cnt = 0            # 原文 setup_cnt
    cancel_setup_cnt = 0         # 原文 sell_setup_cnt（仅用于取消买入 Countdown）
    buy_cd_cnt = 0
    last_buy_setup_end = -1
    buy_cd_active = False

    sell_setup_cnt = 0           # 卖出线自身 Setup 计数（镜像新增）
    sell_cd_cnt = 0
    sell_cancel_cnt = 0          # 卖出 Countdown 的取消计数器（镜像）
    last_sell_setup_end = -1
    sell_cd_active = False

    for i in range(n):
        # ================= 原文：买入 Setup =================
        if not buy_cd_active:
            if i >= setup_offset and _cmp(i, setup_offset, '<'):
                buy_setup_cnt += 1
            else:
                buy_setup_cnt = 0
            if buy_setup_cnt:
                _push(i, BUY_SETUP, min(buy_setup_cnt, setup_window))
            if buy_setup_cnt == setup_window:
                last_buy_setup_end = i
                buy_setup_cnt = 0
                buy_cd_active = True
                out['setup_done'] = True
                out['setup_end_pos'] = i

        # ================= 原文：卖出 Setup（仅作取消用） =================
        sell_just_done = False
        if enable_cancellation and buy_cd_active and i >= setup_offset:
            if _cmp(i, setup_offset, '>'):
                cancel_setup_cnt += 1
            else:
                cancel_setup_cnt = 0
            if cancel_setup_cnt == setup_window:
                sell_just_done = True
                cancel_setup_cnt = 0

        # ================= 原文：买入 Countdown =================
        if buy_cd_active and i > last_buy_setup_end:
            if sell_just_done:
                buy_cd_cnt = 0
                buy_cd_active = False
                out['cancelled'] = True
                _mark_cancelled(BUY_COUNTDOWN)
            elif _cmp(i, countdown_offset, '<='):
                buy_cd_cnt += 1
                if buy_cd_cnt <= countdown_target:
                    _push(i, BUY_COUNTDOWN, buy_cd_cnt)
                if buy_cd_cnt == countdown_target:
                    out['buy_countdown_complete_on'] = _d(i)
                    if i == n - 1:
                        out['countdown_complete'] = True
                        out['countdown_end_pos'] = i
            else:
                buy_cd_cnt = 0

        # ================= 镜像新增：卖出线 =================
        # ① 卖出 Setup：仅在卖出 Countdown 未激活时累计（独立计数器，不干扰原文）
        if not sell_cd_active:
            if i >= setup_offset and _cmp(i, setup_offset, '>'):
                sell_setup_cnt += 1
            else:
                sell_setup_cnt = 0
            if sell_setup_cnt:
                _push(i, SELL_SETUP, min(sell_setup_cnt, setup_window))
            if sell_setup_cnt == setup_window:
                last_sell_setup_end = i
                sell_setup_cnt = 0
                sell_cd_active = True
                sell_cancel_cnt = 0

        # ② 取消规则（镜像）：买入 Setup 完成 → 取消卖出 Countdown
        sell_cancelled_now = False
        if enable_cancellation and sell_cd_active:
            if _cmp(i, setup_offset, '<'):
                sell_cancel_cnt += 1
            else:
                sell_cancel_cnt = 0
            if sell_cancel_cnt == setup_window:
                sell_cancelled_now = True
                sell_cancel_cnt = 0

        # ③ 卖出 Countdown
        if sell_cd_active and i > last_sell_setup_end:
            if sell_cancelled_now:
                sell_cd_cnt = 0
                sell_cd_active = False
                _mark_cancelled(SELL_COUNTDOWN)
            elif _cmp(i, countdown_offset, '>='):
                sell_cd_cnt += 1
                if sell_cd_cnt <= countdown_target:
                    _push(i, SELL_COUNTDOWN, sell_cd_cnt)
                if sell_cd_cnt == countdown_target:
                    out['sell_countdown_complete_on'] = _d(i)
            else:
                sell_cd_cnt = 0

    # 【2026-09-20 按用户口径】只输出"完整 9 转"的序列：
    #   把每个方向的标记按"连续段"分组（段内 pos 连续、seq 递增 1），仅当该段达到目标根数
    #   （Setup → setup_window，Countdown → countdown_target）时保留；否则丢弃（图上不再出现
    #   1、2、3 这类碎片）。被取消的 Countdown 必然未完成 → 一并丢弃。
    if only_complete:
        target_of = {BUY_SETUP: setup_window, SELL_SETUP: setup_window,
                     BUY_COUNTDOWN: countdown_target, SELL_COUNTDOWN: countdown_target}
        keep_ids = set()
        for kind, tgt in target_of.items():
            run = []
            for m in [x for x in marks if x['type'] == kind]:
                if run and not (m['pos'] == run[-1]['pos'] + 1
                                and m['seq'] == run[-1]['seq'] + 1):
                    if run[-1]['seq'] >= tgt:
                        keep_ids.update(id(x) for x in run)
                    run = []
                run.append(m)
            if run and run[-1]['seq'] >= tgt:
                keep_ids.update(id(x) for x in run)
        marks = [m for m in marks if id(m) in keep_ids]

    out['marks'] = marks
    out['buy_view'] = {k: out[k] for k in LEGACY_KEYS}
    return out
