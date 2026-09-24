# -*- coding: utf-8 -*-
"""次新腰斩策略（NewStockDrawdownStrategy）

选股条件（2026-09-19 新增；同日按"简化口径 + 选股日往前算"调整）：
  1. **次新**：**截至选股日**上市的 K 线根数 ≤ max_kline_bars（默认 120 根 ≈ 半年交易日）
  2. **深度回撤**：当前价（信号日收盘）相对「上市以来最高价」跌幅 ≥ drawdown_min（默认 50%）

口径与实现要点
--------------
- **K 线根数 = len(df)（截至选股日往前算，不含未来）**
  调用方（回测/自适应/实盘）都会把 df 切到 `date <= 选股日`；配合
  `requires_full_history = True`（框架为该策略取上市以来全历史），
  `len(df)` 即"上市以来到选股日"的 K 线根数 —— **从选股日往前计算**，
  不会把选股日之后新增的 bar 计入（无未来函数）。
- **不舍弃历史上的次新股**：不用"今天的总根数"判断（那会把当年是次新、如今已
  上市多年的股票排除掉），而是用**选股日当时的根数**，历史每次选股都能正确识别。
- **最高价**：`high.cummax()`（逐行向后看）；信号行只依赖信号日及之前的数据。
- **只对需要的股票取全历史**：`full_history_universe()` 钩子按
  `COUNT(*) WHERE date <= as_of_date <= max_kline_bars` 先算出"需要全历史的代码集合"
  （选股日之前根数少的次新 + 选股日之后才上市的新股），回测/实盘预加载据此只取这批股票，
  避免全市场全历史带来的数据量与内存开销。
- 不使用 `ffill/bfill/shift(-n)` 等未来数据操作（对齐金三角策略口径）。
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

import pandas as pd

from strategy.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class NewStockDrawdownStrategy(BaseStrategy):
    """次新腰斩策略：截至选股日 K 线 ≤120 根 + 自上市最高价回撤 ≥ 50%"""

    # 【框架级特殊处理·2026-09-19】本策略依赖「上市以来最高价」与「截至选股日的
    #   K 线根数」，与其它策略的"固定天数回溯"要求不同：预加载窗口若被截断，
    #   两个指标都会失真。声明该钩子后：
    #     ① 回测预加载（backtest_engine._preload_stock_data）
    #     ② 执行选股预加载（strategy_runner._preload_stock_data）
    #   都会调用 full_history_universe() 求出"需要全历史的股票"，只对这批股票取全历史。
    requires_full_history = True

    def __init__(self, params=None):
        default_params = {
            'max_kline_bars': 120,        # 次新口径：截至选股日的 K 线根数上限（≈半年交易日）
            'drawdown_min': 0.50,         # 自上市以来最高价的跌幅下限
            'min_bars': 20,               # 最少 K 线根数（数据太少无法判断）
            'min_price': 1.0,             # 最低股价过滤（仙股/异常数据）
            'max_price': 500.0,           # 最高股价过滤（异常高价）
            'lookback_days': 220,         # 兼容参数（窗口由 requires_full_history 接管）
            'strategy_weight': 55,
        }
        if params:
            default_params.update(params)
        super().__init__("次新腰斩策略", default_params)

    # ==================== 全历史股票范围（供预加载收窄用）====================

    @staticmethod
    def _bare_code(code) -> str:
        """去掉 .SZ/.SH/.BJ 后缀，与数据库 code 口径一致"""
        return (str(code or '').strip().upper()
                .replace('.SZ', '').replace('.SH', '').replace('.BJ', ''))

    @classmethod
    def full_history_universe(cls, db, as_of_date: str, params: Dict = None) -> Optional[Set[str]]:
        """返回"需要全历史数据"的股票代码集合（无未来函数）

        规则（以 as_of_date 为界，只看该日及之前）：
          - 该日前 K 线根数 ≤ max_kline_bars（这些股票**当时**是次新）
          - 该日前没有任何 K 线（= 该日之后才上市的新股，根数从 0 起算，必须纳入）
        根数只增不减 → "该日之前已 >max 根"的股票后续不可能变成次新，可安全排除。

        Args:
            db: DBManager 实例
            as_of_date: 窗口基准日（回测起始日 / 当前选股日），YYYY-MM-DD
            params: 策略参数（取 max_kline_bars）

        Returns:
            代码集合（不含后缀）；查询失败返回 None（调用方回退为全市场全历史）
        """
        max_bars = int((params or {}).get('max_kline_bars', 120))
        try:
            rows = db.query(
                "SELECT code, COUNT(*) AS n FROM stock_kline WHERE date <= ? GROUP BY code",
                (str(as_of_date)[:10],)) or []
            counts = {cls._bare_code(r.get('code')): int(r.get('n') or 0) for r in rows}
            universe = {c for c, n in counts.items() if c and n <= max_bars}
            # 该日之后才上市的新股：在 stock_kline 中无更早记录 → counts 中缺失或为 0
            for r in db.query("SELECT code FROM stock_basic") or []:
                code = cls._bare_code(r.get('code'))
                if code and counts.get(code, 0) <= max_bars:
                    universe.add(code)
            logger.info("次新腰斩策略: 截至 %s 需全历史的股票 %d 只（K线 ≤ %d 根，含未上市新股）",
                        as_of_date, len(universe), max_bars)
            return universe
        except Exception as e:
            logger.warning("次新腰斩策略: 计算全历史范围失败，回退全市场: %s", e)
            return None

    # ==================== 指标 ====================

    def calculate_indicators(self, df) -> pd.DataFrame:
        """计算「上市以来最高价」与当前回撤（纯向后看，无未来函数）"""
        result = df.copy()
        # 与框架约定一致：df 倒序（最新在前）；计算 cummax 需按时间正序
        is_reversed = (len(result) > 1
                       and str(result['date'].iloc[0]) > str(result['date'].iloc[1]))
        if is_reversed:
            result = result.iloc[::-1].reset_index(drop=True)

        result['high_cummax'] = result['high'].cummax()
        result['drawdown_from_high'] = result['close'] / result['high_cummax'] - 1.0

        if is_reversed:
            result = result.iloc[::-1].reset_index(drop=True)
        return result

    def get_selection_criteria(self) -> List[str]:
        p = self.params
        return [
            f"1. 次新股：截至选股日的 K 线根数 ≤ {p['max_kline_bars']} 根（约半年交易日）",
            f"2. 深跌：当前价较上市以来最高价跌幅 ≥ {p['drawdown_min'] * 100:.0f}%",
            f"3. K 线不少于 {p['min_bars']} 根",
            f"4. 股价在 {p['min_price']} ~ {p['max_price']} 元之间（异常值过滤）",
        ]

    def quick_filter(self, df) -> bool:
        """快速过滤：仅做数据量与字段检查（不含次新/回撤判断）"""
        if df is None or len(df) == 0:
            return False
        if 'high' not in df.columns or 'close' not in df.columns:
            return False
        return len(df) >= int(self.params['min_bars'])

    # ==================== 选股 ====================

    def select_stocks(self, df, stock_name='', selection_date=None,
                      stock_code=None) -> list:
        """选股逻辑：截至选股日 K 线 ≤120 根（次新）+ 自上市最高价回撤 ≥ 50%"""
        if not self.quick_filter(df):
            return []

        # 排序自免疫（对齐金三角策略）：统一为"倒序、最新在前"，消除对调用方顺序的依赖
        if len(df) >= 2 and str(df['date'].iloc[0]) < str(df['date'].iloc[-1]):
            df = df.iloc[::-1].reset_index(drop=True)

        if stock_name and not self._validate_stock_name(stock_name):
            return []

        df = self.calculate_indicators(df.copy())
        latest = df.iloc[0]                      # 信号日（倒序首行）

        # 信号日：优先使用调用方传入的选股日，否则取 df 最新 bar 日期
        signal_date = str(selection_date or latest['date'])[:10]
        try:
            datetime.strptime(signal_date, '%Y-%m-%d')
        except ValueError:
            return []

        # ① 次新判断：**截至选股日**的 K 线根数（df 已被切到 date <= 选股日，且为全历史）
        #    从选股日往前算 → 不含未来 bar；也不使用"今天的总根数"（否则会舍弃历史上的次新股）
        bars_as_of_signal = int(len(df))
        if bars_as_of_signal > int(self.params['max_kline_bars']):
            return []

        # ② 回撤判断：当前价相对上市以来最高价
        close = float(latest['close'])
        high_since_list = float(latest['high_cummax'])
        if high_since_list <= 0:
            return []
        drawdown = 1.0 - close / high_since_list
        if drawdown < float(self.params['drawdown_min']):
            return []
        if not (float(self.params['min_price']) <= close <= float(self.params['max_price'])):
            return []

        # 股票代码（仅用于日志/详情；不参与判定，避免依赖数据库）
        code = self._bare_code(stock_code)
        if not code and 'code' in df.columns:
            code = self._bare_code(df['code'].iloc[0])

        reason = (f"次新腰斩：截至{signal_date}共 {bars_as_of_signal} 根K线，"
                  f"最高 {high_since_list:.2f} → 现价 {close:.2f}，回撤 {drawdown * 100:.1f}%")
        logger.info("【次新腰斩】%s %s %s", code or '-', stock_name, reason)
        return [{
            'signal': 'buy',
            'reason': reason,
            'reasons': [reason],
            'date': signal_date,
            'close': round(close, 2),
            'key_date': signal_date,
            'key_date_type': '信号日',
            'kline_bars': bars_as_of_signal,
            'high_since_list': round(high_since_list, 2),
            'drawdown': round(drawdown, 4),
            'pattern_details': {
                'kline_bars': bars_as_of_signal,
                'max_kline_bars': int(self.params['max_kline_bars']),
                'high_since_list': round(high_since_list, 2),
                'current_close': round(close, 2),
                'drawdown_from_high': round(drawdown, 4),
            },
            'pattern_confirmed': True,
            'strategy_weight': self.params['strategy_weight'],
        }]
