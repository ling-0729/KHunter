# -*- coding: utf-8 -*-
"""ADX 自适应路由组合回测（独立功能）

特性：
  - **不依赖、也不改动**现有回测引擎与实盘运行器（只读数据库 + 读 ADX）
  - 逐交易日按【前一交易日】ADX 判定 regime（防前视），再按路由表决定
    当日采纳哪套选股策略的信号、以及仓位系数
  - 与基准（不做路由、固定策略/全策略、满仓）对比

数据来源：
  - 候选交易：backtest_trade JOIN backtest_result（按 strategy_name 区分）
  - regime：market_index_adx（由 utils/market_index_adx.py 每日产出）

局限（务必知悉）：
  - 交易记录来自多个已有回测（不同参数/区间），组合为**近似模拟**
  - 未模拟滑点/手续费/涨跌停/资金不足优先级；持仓期间净值按收益线性折算
  - 未做多策略候选池的“同一时刻谁先买”竞争（各策略信号互不冲突的假设）

用法：
    from trading.regime_backtest import RegimeBacktester
    bt = RegimeBacktester()
    r = bt.run('2025-01-01', '2026-09-10', benchmark='all')
    bt.print_report(r)
    # 或命令行：python -m trading.regime_backtest 2025-01-01 2026-09-10
"""
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from trading.regime_router import RegimeRouter

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _PROJECT_ROOT / 'data' / 'stock_selection.db'


class RegimeBacktester:
    """基于历史交易记录的 regime 路由组合回测器"""

    def __init__(self, initial_capital: float = 500000.0,
                 bet_ratio: float = 0.2, max_daily_buys: int = 5,
                 router_config: Optional[Dict] = None,
                 db_path: Optional[str] = None):
        """
        Args:
            initial_capital: 初始资金
            bet_ratio: 单笔买入占总资产比例上限
            max_daily_buys: 每日最多买入笔数（影响资金分配粒度）
            router_config: RegimeRouter 配置覆盖（默认读取 config/regime_router.yaml）
            db_path: 数据库路径（默认 data/stock_selection.db）
        """
        self.initial_capital = float(initial_capital)
        self.bet_ratio = float(bet_ratio)
        self.max_daily_buys = max(1, int(max_daily_buys))
        self.router_config = router_config or {}
        self.db_path = str(db_path or DB_PATH)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------
    @staticmethod
    def norm_date(d) -> str:
        """统一为 YYYY-MM-DD"""
        s = str(d).strip()
        return re.sub(r'^(\d{4})(\d{2})(\d{2})$', r'\1-\2-\3', s)

    def _load_trades(self, start_date: str, end_date: str) -> pd.DataFrame:
        conn = sqlite3.connect(self.db_path)
        try:
            df = pd.read_sql(
                "SELECT t.stock_code, t.buy_date, t.sell_date, t.return_rate, "
                "       t.hold_days, r.strategy_name "
                "FROM backtest_trade t JOIN backtest_result r ON t.result_id = r.id "
                "WHERE t.trade_type='sell' AND t.return_rate IS NOT NULL "
                "  AND t.buy_date >= ? AND t.buy_date <= ?",
                conn, params=(start_date, end_date))
        finally:
            conn.close()

        if df.empty:
            return df
        df['buy_date'] = df['buy_date'].map(self.norm_date)
        df['sell_date'] = df['sell_date'].map(self.norm_date)
        df['return_rate'] = pd.to_numeric(df['return_rate'], errors='coerce')
        df = df.dropna(subset=['return_rate'])
        # 去重：同一策略同一股票同一买入日可能出现在多个回测中（重复计数会严重失真）
        df = df.drop_duplicates(subset=['strategy_name', 'stock_code', 'buy_date'])
        return df.reset_index(drop=True)

    def _adx_days(self, start_date: str, end_date: str,
                  index_code: Optional[str] = None) -> List[str]:
        """ADX 覆盖的交易日序列（regime 判定依赖它）

        ★★【2026-10-05 适配修复 ✓】**必须按 `index_code` 过滤** ✗→✓ ★★
          隐患 ✗✓：本查询原先**不筛指数** ✗ —— 写它时表里只有 1 个指数 ✓ ⇒ 恰好等价 ✗；
            2026-10-05 新增创业板指 / 科创50 后 ✗ ⇒ **每个交易日返回 3 行** ✗
            ⇒ 这里返回的日期序列**大量重复** ✗ ⇒ 下游 `prev_day`（信号日映射 ✓）、
              `regime_days` 统计与**逐日决策**全部**静默失真** ✗✓。
          ⚠️ 光"去重"**不够** ✗✓：多指数下"某指数缺某天、别的指数有"✗ ⇒ 去重会把该指数
            **没有数据的日子**当成有 ✗ ⇒ 仍错 ✗ ⇒ **必须按指数过滤** ✓。
          指数来源 ✓：`router_config.index_code` ✓ >（回落）`resolve_index_adx_code()`
            （= `index_adx_code` > `regime_router.yaml::index_code` ✓）—— 与 `RegimeRouter`
            自己用的**完全同一个** ✓（否则"路由看 A、这里按 B 排日子"✗ 自相矛盾 ✗）。
        """
        code = str(index_code or '').strip()
        if not code:
            try:
                code = str((self.router_config or {}).get('index_code') or '').strip()
            except Exception:
                code = ''
        if not code:
            try:
                from trading.index_adx_filter import resolve_index_adx_code
                code = str(resolve_index_adx_code() or '').strip()
            except Exception as e:                   # 解析失败 ⇒ 保持旧行为 ✓ 但**告警** ✓
                logger.warning(f'[RegimeBacktester] 解析指数失败（按旧行为不过滤 ✗）: {e}')
        sql = ("SELECT trade_date FROM market_index_adx "
               "WHERE trade_date >= ? AND trade_date <= ?")
        params = [start_date.replace('-', ''), end_date.replace('-', '')]
        if code:
            sql += " AND index_code = ?"
            params.append(code)
        else:
            logger.warning('[RegimeBacktester] 未指定指数 ⇒ 跨全部指数取日期 ✗'
                           '（多指数下会重复 / 失真 ✗✓，请显式指定 ✓）')
        sql += " ORDER BY trade_date"
        conn = sqlite3.connect(self.db_path)
        try:
            rows = pd.read_sql(sql, conn, params=tuple(params))
        finally:
            conn.close()
        return [self.norm_date(d) for d in rows['trade_date'].tolist()]

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, start_date: str, end_date: str,
            benchmark: str = 'all',
            router_config: Optional[Dict] = None,
            route_table: Optional[Dict] = None,
            confirm_days: int = 5,
            pool_rebuild_days: int = 1) -> Dict:
        """执行组合回测

        Args:
            start_date / end_date: 区间（YYYY-MM-DD）
            benchmark: 基准口径 —— 'all'（全部策略，满仓不路由）或 '金三角策略' 等策略名
            router_config: 覆盖路由器配置（默认启用 enabled=True）
            route_table: 覆盖路由表（默认读取 config/regime_router.yaml）
            confirm_days: 连续确认天数
            pool_rebuild_days: **切换选股策略后清池重建所需交易日数**（默认 1）。
                现有引擎股票池为累积式（pool_mode=persistent），策略一换旧候选即失效，
                新策略需重新选股 → 该期间不买入。设为 0 可关闭该约束（偏乐观）。

        Returns:
            {'router': 指标, 'benchmark': 指标, 'summary': 对比, 'regime_days': {...}}
        """
        start_date, end_date = self.norm_date(start_date), self.norm_date(end_date)

        trades = self._load_trades(start_date, end_date)
        if trades.empty:
            raise ValueError(f'{start_date} ~ {end_date} 无可用交易记录')

        days = self._adx_days(start_date, end_date)
        if not days:
            raise ValueError('区间内无 ADX 数据（请先补算 market_index_adx）')

        # 交易日 → 前一交易日（信号日，防前视）
        prev_day = {days[i]: days[i - 1] for i in range(1, len(days))}

        # 路由器（内存态，避免污染实盘状态文件）
        cfg = {'enabled': True, 'confirm_days': confirm_days, 'init_immediate': True}
        cfg.update(router_config or {})
        if route_table:
            cfg['rules'] = route_table
        router = RegimeRouter(cfg, in_memory=True)

        # 预生成每日决策（按信号日）
        decisions: Dict[str, Dict] = {}
        regime_days: Dict[str, int] = {}
        for d in days:
            sig = prev_day.get(d)          # 决策使用前一交易日（防前视）
            if not sig:
                continue
            dec = router.decide(sig, persist=True)
            decisions[d] = {
                'regime': dec.regime,
                'selector': dec.selector_strategy,
                'position': float(dec.position_ratio) if dec.is_active() else 1.0,
                'active': dec.is_active(),
            }
            if dec.is_active():
                regime_days[dec.regime] = regime_days.get(dec.regime, 0) + 1

        # ========== 切换策略即清池：重建期内不买入 ==========
        # 现有回测引擎的股票池是累积的（pool_mode=persistent），池内候选由"当时那个
        # 选股策略"选出；一旦按 regime 切换选股策略，旧候选即失效，必须清池并由新策略
        # 重新选股。本模拟用「切换后 pool_rebuild_days 个交易日不采纳信号」近似该成本。
        switch_info = self._apply_pool_rebuild(days, decisions, pool_rebuild_days)

        router_result = self._simulate(trades, days, decisions, mode='router')
        bench_trades = trades if benchmark == 'all' else trades[
            trades['strategy_name'] == benchmark]
        benchmark_result = self._simulate(
            bench_trades, days,
            {d: {'active': False, 'selector': None, 'position': 1.0} for d in days},
            mode='benchmark')

        return {
            'period': f'{start_date} ~ {end_date}',
            'router': router_result,
            'benchmark': benchmark_result,
            'benchmark_name': benchmark,
            'summary': self._compare(router_result, benchmark_result),
            'regime_days': regime_days,
            'pool_rebuild': switch_info,
        }

    # ------------------------------------------------------------------
    # 切换策略清池（近似现有引擎的累积池行为）
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_pool_rebuild(days: List[str], decisions: Dict[str, Dict],
                            rebuild_days: int) -> Dict:
        """切换选股策略 → 清池重建，重建期内不采纳信号

        Returns:
            {'switches': 策略切换次数, 'blocked_days': 因重建被屏蔽的交易日数}
        """
        if rebuild_days <= 0:
            return {'switches': 0, 'blocked_days': 0}

        switches = 0
        blocked = 0
        prev_selector = None
        block_until = -1
        for i, d in enumerate(days):
            dec = decisions.get(d)
            if not dec:
                continue
            sel = dec.get('selector') if dec.get('active') else None
            if sel:
                if prev_selector and sel != prev_selector:
                    switches += 1
                    block_until = i + rebuild_days
                    logger.debug(f'[清池] {d} 切换 {prev_selector} → {sel}，'
                                 f'重建 {rebuild_days} 日')
                prev_selector = sel
            if i < block_until and dec.get('active'):
                dec['active'] = False       # 池重建中：当日不买入
                blocked += 1
        return {'switches': switches, 'blocked_days': blocked}

    # ------------------------------------------------------------------
    # 资金模拟
    # ------------------------------------------------------------------
    def _simulate(self, trades: pd.DataFrame, days: List[str],
                  decisions: Dict[str, Dict], mode: str) -> Dict:
        """按日推进资金：结算 → 决策 → 按路由分配买入 → 记录净值"""
        if trades.empty:
            return self._empty_result()

        by_buy_date = {d: g for d, g in trades.groupby('buy_date')}
        day_set = set(days)

        cash = self.initial_capital
        holdings: List[Dict] = []      # {amount, buy_date, sell_date, ret, code}
        nav_series: List[tuple] = []
        executed: List[Dict] = []
        day_index = {d: i for i, d in enumerate(days)}

        for d in days:
            # 1) 结算到期持仓（卖出日 <= 当日）
            still = []
            for h in holdings:
                if h['sell_date'] <= d:
                    cash += h['amount'] * (1 + h['ret'] / 100.0)
                    executed.append(h)
                else:
                    still.append(h)
            holdings = still

            # 2) 当日买入（router 模式下按路由表筛选策略与仓位）
            signals = by_buy_date.get(d)
            if signals is not None:
                dec = decisions.get(d, {'active': False, 'selector': None,
                                        'position': 1.0})
                if mode == 'router':
                    if not dec['active'] or not dec['selector']:
                        signals = None
                    else:
                        signals = signals[signals['strategy_name'] == dec['selector']]
                if signals is not None and not signals.empty:
                    position = float(dec.get('position', 1.0))
                    total_assets = cash + sum(
                        h['amount'] * (1 + h['ret'] / 100.0) for h in holdings)
                    # 当日信号等权分配（避免"按数据顺序截断"带来的选择偏差；
                    # 总预算 = 总资产 × 单笔比例 × regime仓位 × 每日上限）
                    budget = min(total_assets * self.bet_ratio * position
                                 * self.max_daily_buys, cash)
                    n = len(signals)
                    per_bet = budget / n if n else 0.0
                    if per_bet > 0:
                        for _, t in signals.iterrows():
                            if cash < per_bet:
                                break
                            cash -= per_bet
                            holdings.append({
                                'code': t['stock_code'], 'amount': per_bet,
                                'buy_date': d, 'sell_date': t['sell_date'],
                                'ret': float(t['return_rate']),
                                'strategy': t['strategy_name'],
                            })

            # 3) 当日净值（持仓按持有进度线性折算）
            mv = 0.0
            for h in holdings:
                i0 = day_index.get(h['buy_date'], 0)
                i1 = day_index.get(h['sell_date'], i0 + 1)
                total = max(1, i1 - i0)
                cur = day_index.get(d, i0)
                prog = min(1.0, max(0.0, (cur - i0) / total))
                mv += h['amount'] * (1 + h['ret'] / 100.0 * prog)
            nav_series.append((d, cash + mv))

        if not nav_series:
            return self._empty_result()

        nav_df = pd.DataFrame(nav_series, columns=['date', 'nav'])
        nav_df['ret'] = nav_df['nav'].pct_change().fillna(0.0)
        return self._metrics(nav_df, executed)

    @staticmethod
    def _empty_result() -> Dict:
        return {'total_return': 0.0, 'annual_return': 0.0, 'max_drawdown': 0.0,
                'sharpe': 0.0, 'trades': 0, 'win_rate': 0.0, 'avg_return': 0.0,
                'final_nav': 0.0}

    @staticmethod
    def _metrics(nav_df: pd.DataFrame, executed: List[Dict]) -> Dict:
        nav = nav_df['nav']
        total_return = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
        n_days = max(1, len(nav))
        annual = ((nav.iloc[-1] / nav.iloc[0]) ** (252.0 / n_days) - 1) * 100
        peak = nav.cummax()
        max_dd = ((nav - peak) / peak * 100).min()
        std = nav_df['ret'].std()
        sharpe = (nav_df['ret'].mean() / std * (252 ** 0.5)) if std and std > 0 else 0.0
        rets = [h['ret'] for h in executed]
        return {
            'total_return': round(total_return, 2),
            'annual_return': round(annual, 2),
            'max_drawdown': round(float(max_dd), 2),
            'sharpe': round(float(sharpe), 2),
            'trades': len(executed),
            'win_rate': round(sum(1 for r in rets if r > 0) / len(rets) * 100, 2) if rets else 0.0,
            'avg_return': round(sum(rets) / len(rets), 2) if rets else 0.0,
            'final_nav': round(float(nav.iloc[-1]), 2),
        }

    @staticmethod
    def _compare(router_r: Dict, bench_r: Dict) -> Dict:
        keys = ('total_return', 'annual_return', 'max_drawdown', 'sharpe',
                'trades', 'win_rate', 'avg_return')
        return {k: round(router_r[k] - bench_r[k], 2) for k in keys}

    # ------------------------------------------------------------------
    # 报告
    # ------------------------------------------------------------------
    @staticmethod
    def print_report(result: Dict) -> None:
        r, b, s = result['router'], result['benchmark'], result['summary']
        print(f"\n{'=' * 74}")
        print(f"ADX 自适应路由组合回测  {result['period']}")
        print(f"{'=' * 74}")
        print(f"{'指标':<12}{'路由组合':>14}{'基准(' + result['benchmark_name'] + ')':>18}{'差异':>12}")
        print('-' * 74)
        rows = [
            ('总收益%', 'total_return'), ('年化%', 'annual_return'),
            ('最大回撤%', 'max_drawdown'), ('夏普', 'sharpe'),
            ('交易数', 'trades'), ('胜率%', 'win_rate'), ('平均收益%', 'avg_return'),
        ]
        for label, key in rows:
            print(f'{label:<12}{r[key]:>14}{b[key]:>18}{s[key]:>+12}')
        print('-' * 74)
        print(f"期末净值: 路由 {r['final_nav']:.0f} | 基准 {b['final_nav']:.0f}")
        print(f"\n各 regime 生效天数: {result['regime_days']}")
        pr = result.get('pool_rebuild') or {}
        if pr:
            print(f"切换策略清池: 共切换 {pr.get('switches', 0)} 次, "
                  f"重建期屏蔽 {pr.get('blocked_days', 0)} 个交易日")


def main():
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    start = sys.argv[1] if len(sys.argv) > 1 else '2025-01-01'
    end = sys.argv[2] if len(sys.argv) > 2 else datetime.now().strftime('%Y-%m-%d')
    benchmark = sys.argv[3] if len(sys.argv) > 3 else 'all'
    bt = RegimeBacktester()
    result = bt.run(start, end, benchmark=benchmark)
    bt.print_report(result)


if __name__ == '__main__':
    main()
