# -*- coding: utf-8 -*-
"""海龟plus择时策略：只做第二买点

判据（2026-09-16 定稿）：

  前置① 第一买点：信号日前溯 `lookback_days`(5) 个**交易日**内存在一根"海龟入场K线"
        （突破 n_entry 日高点 + 上影线≤4% + 阳线 + 收盘上涨 + MA20）——同父类 _check_buy_signal。
  前置② 窗口内无卖点：第一买点之后、信号日之前不得出现卖点
        （跌破 n_exit 日下线 / exit_atr 倍 ATR 止损）；出现即视为该轮已结束，**直接跳过**。

  今日判据 = 海龟「加仓条件」（不要求今日突破新高）：
    A1 盈利门槛（**2026-09-23 口径修正** ✓ 按实际盈利判定 ✓）：
        信号日收盘价 ≥ **基准价** × (1 + add_profit_min)，基准价按场景取：
          · **已有持仓（加仓）** → **实际持仓均价** `position['buy_price']` ✓
            （回测=引擎持仓均价；实盘=PTrade 同步成本价；两端口径一致 ✓）
          · **空仓（第二买点首仓）** → 第一买点**成交价** = 第一买点信号日的
            **次一交易日开盘价**（T+1 开盘，与回测成交口径一致 ✓，原口径不变 ✓）
        修正原因：旧实现**恒用**第一买点成交价 ✗ → 已有持仓时，即使**持仓浮亏**
        也会因"股价较第一买点涨了 2%"而放行 ✗（实测 002185：持仓成本 18.5027 → 浮亏
        -0.72%，却因基准 16.68 被算成 +10.13% 而生成加仓委托 ✗）。
        现与父类海龟（`turtle_strategy.py` 用 `position['buy_price']`）口径统一 ✓。
    A2 ATR 间隔：信号日 high ≥ last_add_price + add_atr × ATR
       （require_add_atr 开启时；last_add_price 缺省回退第一买点成交价）
    A3 阳线 / A4 涨幅>0 / A5 上影线≤4% / A6 MA20 过滤

  输出：有持仓 → trade_type='add'；空仓 → 'buy'
        —— 策略只负责发出信号；是否建仓/加仓由引擎裁决；
        加仓次数上限**默认与海龟一致（4 次）**，可用 config['max_additions'] 覆盖：
        正整数 = 该上限；0 = 不设限；缺省/None/非法 = 4。

与父类关系：继承 TurtleStrategy 复用 calculate_indicators / _check_sell_signal / 卖出逻辑；
今日判据不再是父类的入场判据（B1 突破新高），故不调用 _check_buy_signal 判定"今日"。
"""
from typing import Dict, Optional, Tuple

import pandas as pd

from trading.timing_strategies import TimingResult
from trading.turtle_strategy import TurtleStrategy


class TurtlePlusStrategy(TurtleStrategy):
    """海龟plus（第二买点）"""

    # 信号文案标识（子类/实例可覆盖，仅影响展示）
    SIGNAL_LABEL = '第二买点'

    # 与海龟一致：开启 MA20 过滤
    USE_MA_FILTER = True

    def __init__(self, config):
        """初始化

        Args:
            config: 策略配置（含 lookback_days / max_additions / require_* 等）
        """
        super().__init__(config)
        # 前溯窗口（交易日数量）
        self.lookback_days = int(self.config.get('lookback_days', 5))
        # 【2026-09-23】加仓上限（max_additions）与盈利门槛（add_profit_min）改由
        #   **父类统一解析** ✓（同一实现、同一默认值 4 / 0.02 ✓），
        #   避免父子各写一份、日后再次漂移 ✗（父类 __init__ 已设置这两个属性 ✓）
        # 口径开关
        self.require_no_sell_between = bool(
            self.config.get('require_no_sell_between', True))
        self.require_add_atr = bool(self.config.get('require_add_atr', True))
        self.require_higher_high = bool(self.config.get('require_higher_high', False))

    # 说明：`_parse_max_additions` 已上移至父类 `TurtleStrategy` ✓
    #   —— 海龟 / 低位海龟 / 海龟plus 三处共用同一解析器，子类继承即可 ✓

    # ==================== 判据 ====================

    def _is_entry_bar(self, df: pd.DataFrame, idx: int) -> bool:
        """第 idx 根 K 线是否为「海龟入场K线」（判据与父类 _check_buy_signal 同源）

        仅使用 [0, idx] 的数据：up/ma20 由 rolling().shift(1) 得出，天然无未来函数。

        Args:
            df: 已算好指标的行情数据
            idx: 待判定的 K 线索引（0-based）

        Returns:
            是否为入场K线
        """
        if idx <= 0 or idx >= len(df):
            return False
        bar = df.iloc[idx]
        # B1 突破唐奇安上线
        if not (pd.notna(bar['up']) and bool(bar['high'] > bar['up'])):
            return False
        # B2 上影线 ≤4%（分母为 0 时按 0 处理，与父类一致）
        body_high = max(bar['open'], bar['close'])
        if body_high > 0 and (bar['high'] - body_high) / body_high > 0.04:
            return False
        # B3/B4 阳线 且 收盘上涨
        prev_close = df['close'].iloc[idx - 1]
        if not (bool(bar['close'] > bar['open']) and bool(bar['close'] > prev_close)):
            return False
        # B5 MA20 过滤（USE_MA_FILTER 关闭时跳过）
        if self.USE_MA_FILTER:
            if not (pd.notna(bar['ma20']) and bool(bar['close'] > bar['ma20'])):
                return False
        return True

    def _is_sell_bar(self, df: pd.DataFrame, idx: int, entry_price: float) -> bool:
        """第 idx 根 K 线是否触发海龟卖出条件（与父类 _check_sell_signal 同源）

        Args:
            df: 已算好指标的行情数据
            idx: 待判定的 K 线索引
            entry_price: 入场价（用于 ATR 止损）；<=0 时只判"跌破下线"

        Returns:
            是否触发卖出
        """
        bar = df.iloc[idx]
        # 跌破 n_exit 日下线
        if pd.notna(bar['down']) and bool(bar['low'] < bar['down']):
            return True
        # ATR 止损
        if entry_price and pd.notna(bar['atr']):
            if bool(bar['low'] <= entry_price - self.exit_atr * bar['atr']):
                return True
        return False

    @staticmethod
    def _first_entry_fill_price(df: pd.DataFrame, entry_idx: int) -> float:
        """第一买点成交价 = 第一买点信号日的**次一交易日开盘价**（T+1 开盘）

        与回测成交口径一致（T-1 信号 → T 日开盘成交）；越界/异常时退化为该日收盘价。

        Args:
            df: 行情数据
            entry_idx: 第一买点（信号日）索引

        Returns:
            成交价（元）
        """
        nxt = entry_idx + 1
        if nxt < len(df):
            price = df['open'].iloc[nxt]
            if pd.notna(price) and float(price) > 0:
                return float(price)
        return float(df['close'].iloc[entry_idx])

    def _find_first_entry(self, df: pd.DataFrame, signal_idx: int) -> Tuple[Optional[int], str]:
        """在前溯窗口 [signal_idx - lookback_days, signal_idx - 1] 内定位第一买点

        Args:
            df: 已算好指标的行情数据
            signal_idx: 信号日索引（回测=T-1，狩猎场=T）

        Returns:
            (第一买点索引 或 None, 跳过原因；命中时原因为空串)
        """
        if self.lookback_days <= 0:
            return None, f'前溯窗口未启用（lookback_days={self.lookback_days}）'
        start = signal_idx - self.lookback_days
        if start < 0:
            return None, f'数据不足（前溯需 {self.lookback_days} 个交易日）'
        first_idx = None
        for i in range(start, signal_idx):
            if self._is_entry_bar(df, i):
                first_idx = i
                break
        if first_idx is None:
            return None, f'前 {self.lookback_days} 个交易日内无第一买点'
        # 前置②：第一买点之后出现卖点 → 该轮已结束，直接跳过
        if self.require_no_sell_between:
            fill_price = self._first_entry_fill_price(df, first_idx)
            for i in range(first_idx + 1, signal_idx):
                if self._is_sell_bar(df, i, fill_price):
                    return None, (f'第一买点 {df["date"].iloc[first_idx]} 后 '
                                  f'{df["date"].iloc[i]} 出现卖点，该轮已结束，跳过')
        # 可选：要求今日 high 高于第一买点日 high（默认关闭）
        if self.require_higher_high:
            if not (df['high'].iloc[signal_idx] > df['high'].iloc[first_idx]):
                return None, '信号日高点未超过第一买点日高点'
        return first_idx, ''

    @staticmethod
    def _resolve_add_reference(position, base_price) -> Tuple[float, str]:
        """加仓盈利门槛 A1 的**基准价**（2026-09-23 口径修正 ✓）

        规则（按实际盈利判定 ✓）：
          · **已有持仓（加仓）** → 基准 = **实际持仓均价** `position['buy_price']` ✓
            （回测=引擎持仓均价；实盘=PTrade 同步成本价；两端口径一致 ✓）
          · **空仓（第二买点首仓）** → 基准 = 第一买点成交价（T+1 开盘，原口径 ✓）

        Args:
            position: 持仓字典（无持仓传 None ✓）
            base_price: 第一买点成交价（T+1 开盘 ✓）

        Returns:
            (基准价, 口径名称)；基准价不可用时退回第一买点成交价 ✓
        """
        if position:
            cost = position.get('buy_price')
            try:
                cost = float(cost) if cost is not None else 0.0
            except (TypeError, ValueError):
                cost = 0.0
            if cost > 0:
                return cost, '持仓均价'
        try:
            return float(base_price or 0), '第一买点成交价'
        except (TypeError, ValueError):
            return 0.0, '第一买点成交价'

    def _check_add_entry(self, df: pd.DataFrame, signal_bar: pd.Series,
                         signal_idx: int, base_price: float,
                         last_add_price: float,
                         add_ref_price: Optional[float] = None,
                         add_ref_label: Optional[str] = None) -> Tuple[bool, str]:
        """今日判据 = 海龟「加仓条件」（不要求突破新高）

        Args:
            df: 已算好指标的行情数据
            signal_bar: 信号日 K 线
            signal_idx: 信号日索引
            base_price: 第一买点成交价（T+1 开盘；**空仓首仓**的基准 ✓）
            last_add_price: 上次加仓价（缺省为第一买点成交价）
            add_ref_price: A1 基准价 ✓（**有持仓时=持仓均价** ✓；缺省/非法时回退 base_price ✓）
            add_ref_label: A1 基准口径名称（仅用于日志/提示文案 ✓）

        Returns:
            (是否满足, 不满足原因)
        """
        close = signal_bar['close']
        # A1 盈利门槛（2026-09-23 口径修正 ✓）：**按实际盈利判定** ✓
        #   旧实现恒以"第一买点成交价"为基准 ✗ → 已有持仓时，即使**持仓浮亏**也会
        #   因"股价较第一买点涨了 2%"而放行 ✗（实测 002185：持仓成本 18.5027 → 浮亏 -0.72%，
        #   却因基准 16.68 被算成 +10.13% 而生成加仓委托 ✗）
        #   新实现：有持仓 → 持仓均价 ✓；空仓 → 第一买点成交价 ✓（与父类海龟口径统一 ✓）
        if add_ref_price and add_ref_price > 0:
            ref_price = float(add_ref_price)
            ref_label = add_ref_label or '持仓均价'
        else:
            ref_price = float(base_price or 0)
            ref_label = '第一买点成交价'
        if ref_price <= 0:
            return False, f'{ref_label}异常'
        profit_ratio = (close - ref_price) / ref_price
        if profit_ratio < self.add_profit_min:
            return False, (f'较{ref_label} {ref_price:.2f} 仅 '
                           f'{profit_ratio * 100:.2f}% < {self.add_profit_min * 100:.2f}%')
        # A2 ATR 间隔（require_add_atr 开启时）
        if self.require_add_atr:
            atr = signal_bar['atr']
            if not pd.notna(atr):
                return False, 'ATR 不可用'
            threshold = last_add_price + self.add_atr * atr
            if not bool(signal_bar['high'] >= threshold):
                return False, f'未达加仓间隔 {threshold:.2f}'
        # A3/A4 阳线 且 涨幅>0
        prev_close = df['close'].iloc[signal_idx - 1] if signal_idx > 0 else close
        if not (bool(close > signal_bar['open']) and bool(close > prev_close)):
            return False, '非阳线或涨幅≤0'
        # A5 上影线 ≤4%
        body_high = max(signal_bar['open'], close)
        if body_high > 0 and (signal_bar['high'] - body_high) / body_high > 0.04:
            return False, '上影线>4%'
        # A6 MA20 过滤
        if self.USE_MA_FILTER:
            if not (pd.notna(signal_bar['ma20']) and bool(close > signal_bar['ma20'])):
                return False, '收盘未站上 MA20'
        return True, ''

    # ==================== 主流程 ====================

    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None,
                          cash: Optional[float] = None, use_prev_day_signal: bool = True,
                          stock_code: str = "") -> TimingResult:
        """获取海龟plus择时结果

        Args:
            df: 股票数据
            position: 持仓信息（None = 空仓；有持仓时产出 trade_type='add'）
            cash: 可用资金（保留参数，本策略不直接使用）
            use_prev_day_signal: True=回测（信号K线=T-1）；False=狩猎场（信号K线=T）
            stock_code: 股票代码

        Returns:
            TimingResult：is_buy/is_sell、trade_type（buy/add/sell）、buy_quantity、
                          add_count（加仓时必填）、indicators（含 lookback_hit_date/base_price）
        """
        result = TimingResult()
        df = self.calculate_indicators(df)
        if len(df) < 2:
            return result

        latest = df.iloc[-1]
        if use_prev_day_signal:
            signal_bar = df.iloc[-2]
            signal_idx = len(df) - 2
            signal_date_offset = 1
        else:
            signal_bar = latest
            signal_idx = len(df) - 1
            signal_date_offset = 0

        entry_price = position['buy_price'] if position else 0
        current_price = latest['close']
        hold_return = (current_price - entry_price) / entry_price if entry_price > 0 else 0

        # === 卖出优先（完全沿用父类口径）===
        if position:
            is_sell, reason = self._check_sell_signal(
                df, signal_bar, latest, entry_price, use_prev_day_signal)
            if is_sell:
                result.is_sell = True
                result.signal_strength = 1.0
                result.message = (f"T-{signal_date_offset}日{reason}，卖出信号"
                                  if signal_date_offset else f"今日{reason}，卖出信号")
                result.trade_type = 'sell'
                result.sell_quantity = position.get('quantity', 0)

        # === 第二买点买入（前置①第一买点 + 前置②窗口无卖点 + 今日加仓条件）===
        if not result.is_sell:
            hit_idx, skip_reason = self._find_first_entry(df, signal_idx)
            if hit_idx is None:
                result.indicators['skip_reason'] = skip_reason
            else:
                base_price = self._first_entry_fill_price(df, hit_idx)
                last_add_price = (
                    (position.get('last_add_price') if position else None) or base_price)
                # 【2026-09-23 口径修正】A1 盈利门槛基准价：**有持仓 → 持仓均价** ✓（按实际盈利 ✓）；
                #   空仓 → 第一买点成交价 ✓（原口径不变 ✓）
                add_ref_price, add_ref_label = self._resolve_add_reference(position, base_price)
                ok, why = self._check_add_entry(
                    df, signal_bar, signal_idx, base_price, last_add_price,
                    add_ref_price=add_ref_price, add_ref_label=add_ref_label)
                add_count = (position or {}).get('add_count', 0) or 0
                if not ok:
                    result.indicators['skip_reason'] = f'今日不满足加仓条件：{why}'
                elif position and self.max_additions is not None and add_count >= self.max_additions:
                    result.indicators['skip_reason'] = (
                        f'加仓次数已达上限 {self.max_additions}（由配置/引擎裁决）')
                else:
                    # 盈利口径与 A1 判定**同源** ✓（有持仓=持仓均价 ✓），并保留第一买点口径供参考 ✓
                    ref_is_hold = bool(add_ref_price and add_ref_price > 0)
                    ref_price = add_ref_price if ref_is_hold else base_price
                    ref_label = add_ref_label if ref_is_hold else '第一买点成交价'
                    profit_pct = ((signal_bar['close'] - ref_price) / ref_price * 100
                                  if ref_price > 0 else 0.0)
                    base_pct = ((signal_bar['close'] - base_price) / base_price * 100
                                if base_price > 0 else 0.0)
                    result.is_buy = True
                    result.signal_strength = 0.8 if position else 1.0
                    result.support_level = (
                        signal_bar['up'] * 0.95 if pd.notna(signal_bar['up']) else 0)
                    result.indicators['lookback_hit_date'] = str(df['date'].iloc[hit_idx])
                    result.indicators['base_price'] = base_price
                    result.indicators['add_ref_price'] = ref_price
                    result.indicators['add_ref_label'] = ref_label
                    if position:
                        # 加仓：数量沿用父类 1/(n+2) 递减；add_count 必须回填（引擎据此跟踪）
                        result.trade_type = 'add'
                        result.add_count = add_count + 1
                        result.indicators['last_add_price'] = signal_bar['close']
                        add_ratio = 1.0 / (add_count + 2)
                        add_quantity = int(
                            (position.get('quantity', 0) or 0) * add_ratio) // 100 * 100
                        result.buy_quantity = max(add_quantity, 100)
                        # 文案主口径 = **实际盈利** ✓（持仓均价 ✓）；第一买点口径仅作参考，
                        #   避免再次出现"用第一买点盈利掩盖持仓浮亏"的误导 ✗
                        result.message = (
                            f"{self.SIGNAL_LABEL}加仓#{add_count + 1}：{ref_label} "
                            f"{ref_price:.2f}，盈利 {profit_pct:.2f}%"
                            f"（第一买点 {df['date'].iloc[hit_idx]} T+1 开盘价 "
                            f"{base_price:.2f}，较其 {base_pct:.2f}%）")
                    else:
                        # 空仓：按首仓口径给数量（是否建仓由引擎裁决）
                        buy_price = (latest['open'] if use_prev_day_signal
                                     else latest['close']) or signal_bar['close']
                        if not buy_price or buy_price <= 0:
                            buy_price = max(float(signal_bar['close']), 0.01)
                        result.trade_type = 'buy'
                        result.buy_quantity = max(
                            int(self.base_position_amount / buy_price) // 100 * 100, 100)
                        result.message = (
                            f"{self.SIGNAL_LABEL}买入：第一买点 {df['date'].iloc[hit_idx]}，"
                            f"较其 T+1 开盘价 {base_price:.2f} 盈利 {profit_pct:.2f}%")

        # 指标回填（与父类一致）
        result.indicators['up'] = latest['up'] if pd.notna(latest['up']) else 0
        result.indicators['down'] = latest['down'] if pd.notna(latest['down']) else 0
        result.indicators['atr'] = latest['atr'] if pd.notna(latest['atr']) else 0
        result.indicators['ma20'] = latest['ma20'] if pd.notna(latest['ma20']) else 0
        result.indicators['current_price'] = current_price
        result.indicators['hold_return'] = hold_return

        return result
