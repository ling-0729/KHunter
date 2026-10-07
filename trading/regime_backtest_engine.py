# -*- coding: utf-8 -*-
"""自适应回测引擎（独立功能，父类 BacktestEngine 零改动）

设计文档：doc/自适应回测功能设计说明书.md

与父类 BacktestEngine.run_backtest 的唯一差异（6 处改造）：
  ① 每日按 ADX regime 解析"当日选股策略/择时策略/仓位系数"；选股策略切换时**清空累积股票池**
  ② 选股使用当日策略（父类 352）
  ③ 支撑位算法使用当日策略（父类 360）
  ④ 支撑位方法使用当日策略（父类 362）
  ⑤ 入池字段写入当日策略（父类 378）
  ⑥ 首次建仓金额乘仓位系数（父类 632）；加仓金额同乘（父类 606）

其余流程与父类逐行一致：所有"能力"（选股/评分/支撑位/池移除/卖出/交易记录/绩效）
均**直接继承**父类方法，本文件只复制"编排骨架"。

⚠️ 本副本对应父类 run_backtest 版本：2026-09-11（如父类有重大变更需人工比对）
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from trading import backtest_engine as _be
from trading.backtest_engine import BacktestEngine
from trading.regime_router import RegimeRouter, RouteDecision, NO_SELECTION_LABEL
# ★【2026-09-28】原 `COOLED_PEAK` 已随降温机制移除 ✗✓（预热改为**全历史逐日回放** ✓）
from utils.online_guard import backtest_offline

logger = logging.getLogger(__name__)

# ======================================================================
# 回测进度（内存态；供 Web 端轮询展示，不落库、不影响回测结果）
# ======================================================================
REGIME_PROGRESS: Dict = {
    'running': False,
    'percent': 0.0,
    'done_days': 0,
    'total_days': 0,
    'current_date': '',
    'message': '',
    'result_id': None,
    'started_at': '',
    'finished_at': '',
}


def get_regime_progress() -> Dict:
    """获取进度快照（供 GET /backtest/regime/progress 使用）"""
    return dict(REGIME_PROGRESS)


def _begin_regime_progress(total_days: int) -> None:
    """回测开始：重置进度"""
    REGIME_PROGRESS.update({
        'running': True, 'percent': 0.0, 'done_days': 0,
        'total_days': int(total_days or 0), 'current_date': '',
        'message': '执行中', 'result_id': None, 'finished_at': '',
        'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })


def _update_regime_progress(done_days: int, total_days: int, current_date) -> None:
    """每处理一个交易日更新一次"""
    total = int(total_days or 0)
    REGIME_PROGRESS.update({
        'done_days': int(done_days),
        'total_days': total,
        'percent': round(done_days / total * 100, 1) if total else 0.0,
        'current_date': str(current_date),
    })


def _short_regime(regime: str) -> str:
    """档位文案；兼容旧的 '强度·方向' 写法（'震荡·多头' → '震荡'）"""
    r = str(regime or '')
    if not r:
        return '?'
    return r.split('·')[0]


def _adx_detail(rec: Dict) -> Dict:
    """ADX 记录 + 其对应的即时 regime（供日志展示"分数+regime"）"""
    try:
        adx = rec.get('adx')
        return {
            'date': str(rec.get('trade_date') or ''),
            'adx': adx,
            'regime': RegimeRouter.classify(adx, rec.get('plus_di'), rec.get('minus_di')),
        }
    except Exception:
        return {'date': '', 'adx': None, 'regime': ''}


def _end_regime_progress(message: str, ok: bool = True) -> None:
    """回测结束（成功或失败）"""
    REGIME_PROGRESS.update({
        'running': False,
        'percent': 100.0 if ok else REGIME_PROGRESS.get('percent', 0.0),
        'message': message,
        'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })


class RegimeBacktestEngine(BacktestEngine):
    """ADX 自适应回测引擎（独立功能）"""

    def __init__(self, db=None, router_config: Optional[Dict] = None):
        """
        Args:
            db: 数据库对象（透传父类）
            router_config: RegimeRouter 配置覆盖（默认读 config/regime_router.yaml）
        """
        super().__init__(db)
        # 路由器：内存态，避免污染实盘的 data/running/regime_state.json
        # ★【2026-09-28 用户口径 ✓】回测**必须关** `auto_warmup` ✗✓ —— 预热由
        #   `_warmup_router` 负责 ✓（按**回测起点**回放到起点前一日 ✓）；
        #   若沿用生产 yaml 的 `true` ✗ ⇒ `decide()` 每次都会先做一次"首次预热"
        #   （查库 ＋ `reset_state()` ✗）⇒ 与回测预热**互相打架** ✗✓（实测踩到 ✓）。
        _cfg = dict(router_config or {})
        _cfg.setdefault('auto_warmup', False)
        self._router = RegimeRouter(_cfg, in_memory=True)
        self._decision_cache: Dict[str, RouteDecision] = {}
        # 每轮回测重置
        self.regime_log = []
        self.strategy_switches = []
        self._current_strategy = None
        self._current_state = None      # 【2026-09-24】切换计数的"状态键"（含「空仓」✓）
        self._regime_ratio = 1.0

    # ------------------------------------------------------------------
    # 内部：regime 决策（防前视：用前一交易日 ADX）
    # ------------------------------------------------------------------
    def _decide(self, trade_date) -> RouteDecision:
        """按【前一交易日】ADX 判定 regime（T-1 决策、T 执行，防前视）"""
        key = str(trade_date)
        if key in self._decision_cache:
            return self._decision_cache[key]

        try:
            sig = self._get_previous_trading_day(trade_date) or trade_date
        except Exception:
            sig = trade_date

        try:
            d = self._router.decide(sig, persist=True)
        except Exception as e:      # 兜底：任何异常都不阻断回测
            logger.warning(f'[RegimeEngine] regime 决策失败({key})，按不启用处理: {e}')
            d = RouteDecision(source='disabled')

        # 近 5 个交易日 ADX（截至信号日；仅供日志展示，防前视）
        try:
            _adx5 = self._router.recent_adx(sig, 5)
        except Exception:
            _adx5 = []

        self._decision_cache[key] = d
        self.regime_log.append({
            'date': key,
            'signal_date': str(sig),
            'regime': d.regime,
            'raw_regime': d.raw_regime,
            'confirm_count': d.confirm_count,
            'selector': d.selector_strategy,
            'timing': d.timing_strategy,
            'position': d.position_ratio,
            'source': d.source,
            'adx5': [_adx_detail(r) for r in (_adx5 or [])],
        })
        return d

    # ------------------------------------------------------------------
    # ★【2026-09-27】**路由器预热** ✓ —— 消除"**档位依赖回测起点**"✗
    # ------------------------------------------------------------------
    def _warmup_router(self, start_date, dates: Optional[List] = None) -> int:
        """把路由器状态机推进到 `start_date` 之前 ✓ —— **逐日回放全历史** ✓

        背景 ✗✓（**实测** ✓，用户报 `2025-05-06` ✗）：
          `RegimeRouter.decide()` 是**逐日推进** ✓ —— `band`（**迟滞** ✓）与
          `dir`（**两日同向** ✓）都是**路径依赖** ✗；
          而本引擎此前只对 `[start_date, end_date]` 调 `decide` ✗
          ⇒ **回测起点一变，同一天的档位就变** ✗✗（实测同一日 `2025-05-06` ✓：
          起点早/晚分别得「震荡」与「明确」✗ ⇒ 仓位 `0.0` vs `1.0` ✗）。

        ★ **2026-09-28 简化** ✓：原"**锚点法**"（只回放「起点前最近一次 `adx > 40`」起 ✓）
          **已移除** ✗✓ —— 它依赖降温机制的 `fell_from_high` 标志 ✓，
          而**降温已整体移除** ✗ ⇒ 锚点**不再成立** ✗ ⇒ 回到
          「**数据起点 → 起点前一日**」的**全量逐日回放** ✓（最稳 ✓；~1600 日 ✓ 秒级 ✓）。

        做法 ✓：`reset_state()` 清零 ✓ → 对预热序列逐日调
        `self._router.decide(d, persist=True, verbose=False)` ✓
        （`persist=True` 是**必须**的 ✗：状态逐日累积 ✓；不落状态则次日 `prev_adx` 丢失 ✗
         ⇒ 迟滞与"两日同向"全失效 ✗）。

        ⚠️ 直接调 `self._router` ✓、**不走** `self._decide` ✗ ⇒ 预热**不写**
        `regime_log` / `_decision_cache` ✗（不进回测统计 ✓）。

        ⚠️ 必在**主循环之前** ✓（首日 `_decide` 就要用到已对齐的状态 ✓）；
        路由器为 `in_memory=True` ✓（见 `__init__` ✓）⇒ 预热**不碰**实盘状态文件 ✓。

        Args:
            start_date: 回测开始日 ✓（`YYYYMMDD` / `YYYY-MM-DD` 均可 ✓）
            dates: 预热日期序列 ✓（**测试注入** ✓）；`None` ⇒ 自动取**全部**历史 ✓

        Returns:
            预热天数 ✓（0 = 未预热 ✗；**任何异常也返回 0** ✓ —— 绝不阻断回测 ✓）
        """
        def _norm(x) -> str:
            return str(x or '').replace('-', '')[:8]

        try:
            self._router.reset_state()
            if not getattr(self._router, 'enabled', False):
                return 0
            start = _norm(start_date)
            if dates is None:
                prev = ''
                try:
                    prev = _norm(self._get_previous_trading_day(start_date))
                except Exception:
                    prev = ''
                from trading.market_index_adx_dao import MarketIndexADXDAO
                # ⚠️ 取库方式**必须**与 `RegimeRouter._read_adx` 一致 ✓：
                #   父类 `BacktestEngine` **不暴露** `self.db` ✗（实测 `AttributeError` ✗
                #   ⇒ 被本函数兜底吃掉 ⇒ **静默"零预热"** ✗✗）⇒ 用 `getattr` 兜底到全局库 ✓。
                _db = getattr(self, 'db', None)
                rows = MarketIndexADXDAO(_db).query_range(
                    '19000101', prev or start, self._router.index_code) or []
                # ★【2026-09-28】锚点法已移除 ✓ ⇒ 回放**全部**候选日 ✓
                dates = [r.get('trade_date') for r in rows]
            seq = [d for d in (_norm(x) for x in (dates or [])) if d and d < start]
            for d in seq:
                # ★ 预热**关掉**逐日「判定依据」明细 ✗（上千日会刷屏 ✗）
                self._router.decide(d, persist=True, verbose=False)
            if seq:
                logger.info(f'[RegimeEngine] 路由器预热 ✓ {len(seq)} 日 '
                            f'（{seq[0]} ~ {seq[-1]}）⇒ 起点 {start} 状态已对齐 ✓'
                            f'（`band` **迟滞** ✓ 与 `dir` **两日同向** ✓ 都是'
                            f'**路径依赖** ✗ ⇒ 不预热会与全历史重放不一致 ✗）')
            return len(seq)
        except Exception as e:
            logger.warning(f'[RegimeEngine] 路由器预热失败（按不预热继续 ✓）: {e}')
            return 0

    # ------------------------------------------------------------------
    # 内部：选股策略同一性判断（用于决定风格切换时是否清池）
    # ------------------------------------------------------------------
    @staticmethod
    def _same_selector(name_a, name_b) -> bool:
        """两个选股策略名是否指向**同一个策略**（中文名 / 英文类名 / 别名归一化后比较）

        用途（2026-09-13）：风格档位切换时判断"选股策略是否真的变了" ——
        只有真的变了才需要清理股票池。直接用字符串比较会被
        `主升低吸策略` vs `MainUptrendDipBuyStrategy` 这类别名写法差异误判成"切换"，
        从而把本来有效的候选池清掉。
        """
        if not name_a or not name_b:
            return False
        if name_a == name_b:
            return True
        try:
            from utils.strategy_name_mapper import get_english_name
            return get_english_name(name_a) == get_english_name(name_b)
        except Exception:
            return False

    @staticmethod
    def _is_state_switch(prev_state, day_state) -> bool:
        """当日"选股状态"是否发生变化（2026-09-24 新增 ✓）

        口径（2026-09-24 定稿）：
          · **「空仓」也是一种选股策略**（只是选股结果为 0 只 ✓）——
            故「其他策略 → 空仓」与「空仓 → 其他策略」**都算一次切换** ✓，
            且**同样要清池** ✓（调用方按本次返回 True 即清池 ✓）。
          · 两边都是具名策略时，用 `_same_selector` 做**中/英/别名归一化** ✓
            （避免 `金三角策略` 与 `GoldenTriangleStrategy` 这种同义写法被误计 ✗）。
          · 起始日（`prev_state` 为空）→ False ✓（只登记状态、不计数 ✓）。
        """
        if not prev_state or not day_state:
            return False
        if day_state == NO_SELECTION_LABEL or prev_state == NO_SELECTION_LABEL:
            return day_state != prev_state
        return not RegimeBacktestEngine._same_selector(day_state, prev_state)

    # ------------------------------------------------------------------
    # 内部：择时策略切换（含海龟参数合并，与父类初始化口径一致）
    # ------------------------------------------------------------------
    def _switch_timing(self, timing_name: str, config: Dict) -> None:
        # 海龟类策略参数合并：与父类初始化/普通回测/实盘共用同一实现（名单与键表只有一份）
        # 2026-09-16：此前本处另写一份名单，海龟plus 切档会回退默认预设（short = 10/5/10）
        params = _be.build_turtle_family_params(
            config, config.get('timing_params') or {}, timing_name)

        self.timing_strategy = _be.TimingStrategyFactory.create_strategy(timing_name, params)
        self.timing_strategy_name = timing_name
        self.timing_strategy_params = params
        logger.info(f'[RegimeEngine] 择时策略切换 → {timing_name}')

    def _pick_preload_strategy(self, fallback: str = '') -> str:
        """预加载使用的策略（取其 lookback 窗口）——取路由表首个候选策略

        说明：父类预加载按单一策略 lookback + 60 天缓冲；自适应会切换多种策略，
        这里取路由表候选之一（各策略 lookback 相近，且父类已有缓冲），
        如需更严谨可按候选策略的最大 lookback 计算。
        """
        try:
            for rule in (self._router.rules or {}).values():
                sel = (rule or {}).get('selector')
                if sel:
                    return sel
        except Exception:
            pass
        return fallback

    # ------------------------------------------------------------------
    # 结果统计：各 regime 贡献
    # ------------------------------------------------------------------
    @staticmethod
    def _summarize_by_regime(trades, regime_log):
        """按"买入日所在 regime"汇总交易表现"""
        date_regime = {r['date']: r['regime'] for r in regime_log}
        stats: Dict[str, Dict] = {}
        for t in trades:
            if t.get('trade_type') not in ('new', 'add') and 'buy_date' not in t:
                continue
            bd = t.get('buy_date')
            key = date_regime.get(str(bd), '未知') if bd is not None else '未知'
            s = stats.setdefault(key, {'regime': key, 'trades': 0, 'win': 0,
                                       'sum_return': 0.0})
            s['trades'] += 1
            rr = t.get('return_rate')
            if rr is None:
                continue
            s['sum_return'] += float(rr)
            if float(rr) > 0:
                s['win'] += 1
        out = []
        for s in stats.values():
            out.append({
                'regime': s['regime'],
                'trades': s['trades'],
                'win_rate': round(s['win'] / s['trades'] * 100, 2) if s['trades'] else 0.0,
                'avg_return': round(s['sum_return'] / s['trades'], 2) if s['trades'] else 0.0,
            })
        return sorted(out, key=lambda x: -x['trades'])

    # ------------------------------------------------------------------
    # 主流程（复制父类 run_backtest + 6 处改造）
    # ------------------------------------------------------------------
    @backtest_offline          # 【2026-09-25 契约 ✓】子类入口**单独**加保护 ✗（覆盖父类实现 ✓）
    def run_backtest(self, strategy_name: str, config: Dict) -> Dict:
        """运行自适应回测

        Args:
            strategy_name: 兜底策略名（可为空串；每日策略由 ADX regime 决定）
            config: 回测配置（含 regime_router 配置）

        Returns:
            回测结果字典（父类结构 + regime_stats / strategy_switches / regime_timeline）
        """
        # 【2026-09-27】与父类**同一口径** ✓：yaml `backtest:` 节作为**默认值**并入 ✓（只补缺 ✗✓）
        from utils.backtest_mode import merge_backtest_defaults
        config = merge_backtest_defaults(config)

        # ★【2026-09-27】启动参数快照 ✓ + **路由器开关本体** ✓（用户要求 ✓：一眼核对 ✓）
        #   ⚠️【2026-09-28】`大盘降温(enable_adx_falloff)` **已随机制移除** ✗✓
        self.log_backtest_params(config, tag='自适应引擎', extra={
            'router.enabled': self._router.enabled,
            'confirm_days': self._router.confirm_days,
            'dir口径': self._router._dir_mode,
            'index_code': self._router.index_code,
            'in_memory': self._router.in_memory})

        if not _be._backtest_lock.acquire(blocking=False):
            logger.warning(f"回测任务正在执行中，策略 {strategy_name} 等待...")
            _be._backtest_lock.acquire(blocking=True)
            logger.info(f"获取回测锁，开始执行自适应回测: {strategy_name}")

        try:
            logger.info(f"开始自适应回测: {strategy_name or '(由 ADX 决定)'}")

            _be.sleep_preventer.start()

            # 清空上次缓存
            self.stock_data_cache.clear()
            self.stock_name_cache.clear()
            self.stock_filtered_cache.clear()
            self.buy_candidate_pool.clear()

            # 【2026-09-23 修复】双边成交滑点初始化 ✓
            #   本类是**复制**父类 run_backtest（docstring："父类零改动 / 复制 + 6 处改造" ✗），
            #   父类 :308-312 的滑点初始化**没被复制过来** ✗ → 两个后果：
            #     ① 买入侧滑点代码（父类 :734-739）同样未复制 ✗ → 自适应回测买入**零滑点** ✗✓
            #        （而卖出侧因继承父类 _process_sell ✓ 仍带 0.3% ✗ → 买卖不对称 ✗，
            #          自适应回测系统性偏乐观 ✗，与普通回测口径不一致 ✗）
            #     ② self._slippage 未设置 ✗ → 继承来的 _process_sell 只能靠
            #        getattr 兜底取到**引擎硬编码默认** 0.003/0.003 ✓，
            #        yaml / config['slippage'] 里的自定义值**不生效** ✗
            #   故此处与父类同源取值（_slippage_rates ✓）+ 同口径日志 ✓，保证两条引擎口径一致 ✓
            self._slippage = self._slippage_rates(config)
            logger.info(f"成交滑点: 买入 {self._slippage['buy'] * 100:.3f}% / "
                        f"卖出 {self._slippage['sell'] * 100:.3f}%"
                        f"（对最终成交价双边调整 ✓；设为 0 即关闭 ✓）")

            # ===== 改造①：初始化自适应状态（回测级重置）=====
            self._decision_cache = {}
            self.regime_log = []
            self.strategy_switches = []
            self._current_strategy = None
            self._current_state = None      # 【2026-09-24】切换计数的"状态键"（含「空仓」✓）
            self._regime_ratio = 1.0

            # 初始化择时策略（入口值；实际每日由 regime 决定）
            timing_strategy_name = config.get('timing_strategy', 'support')
            timing_params = config.get('timing_params', {})
            # 海龟类策略参数合并：与普通回测/实盘共用同一实现（名单与键表只有一份），
            # 避免新增海龟类策略（海龟plus）时本处漏改 → 回退默认预设（short = 10/5/10）
            strategy_params = _be.build_turtle_family_params(
                config, timing_params, timing_strategy_name)

            self.timing_strategy = _be.TimingStrategyFactory.create_strategy(
                timing_strategy_name, strategy_params)
            self.timing_strategy_name = timing_strategy_name
            self.timing_strategy_params = strategy_params

            # 【自适应专属卖出条件｜2026-09-15 起暂时屏蔽】三日（滚动）未创新高 且 收盘跌破 5 日线 → 卖出
            #   默认值跟随总开关 BacktestEngine.ENABLE_NO_NEW_HIGH_EXIT（当前 False=屏蔽）；
            #   把总开关改回 True，即恢复自适应回测默认开启的原行为（窗口/均线默认值不变）
            config.setdefault('enable_no_new_high_exit', self.ENABLE_NO_NEW_HIGH_EXIT)
            config.setdefault('no_new_high_window', 3)
            config.setdefault('no_new_high_ma', 5)

            # 1. 回测日期范围
            start_date = config.get('start_date')
            end_date = config.get('end_date')
            if not start_date or not end_date:
                raise ValueError("回测开始日期和结束日期不能为空")

            # ★【2026-09-28】终点**自动回退** ✓ —— 当日数据（资金流/K线/大盘ADX ✓）
            #   **收盘后**才入库 ✗ ⇒ 终点=今天 且未收盘 ⇒ 闸门**必然**报"缺 1 天: 今天"✗
            #   （用户实测 2026-09-28 08:47 批量回测 ✗）。见 `_resolve_end_date` ✓。
            end_date = self._resolve_end_date(end_date)
            if str(start_date).replace('-', '')[:8] > str(end_date).replace('-', '')[:8]:
                raise ValueError(f'回测起点 {start_date} **晚于**可用终点 {end_date} ✗ —— '
                                 f'（终点已回退到"最近一个数据已齐备的交易日"✓）'
                                 f'请把起点提前 ✓')

            # 2. 确保策略已注册
            if not self.strategy_registry.strategies:
                self.strategy_registry.auto_register_from_directory("strategy")

            # 3. 交易日历
            self._load_trading_calendar(start_date, end_date)

            # 4. 交易日列表
            date_range = self._get_trading_dates(start_date, end_date)
            if not date_range:
                raise ValueError(f"回测期间 {start_date} ~ {end_date} 没有交易日")

            # 4.2 ★★【2026-09-30 用户要求 ✓】**补齐数据闸门** ✗→✓ ★★
            #   缺口 ✗✓（用户要求"补齐"时实测确认 ✓）：本引擎**复制**了父类的
            #     `run_backtest` ✗ ⇒ **没接闸门** ✗ ⇒ 与普通回测**两处不一致** ✗：
            #       ① 缺数据**不拦** ✗（普通回测会终止 ✗）；
            #       ② 结果里**没有 `data_fingerprint`** ✗ ⇒ 落库 `data_version` 为空 ✗
            #          ⇒ "重跑结果不一致，是数据变了吗？"**无从判断** ✗✓。
            #   做法 ✓：**复用父类同一实现** ✓（`BacktestEngine._run_data_gate` ✓）
            #     ⇒ 口径**不可能漂移** ✗✓（跳过项判据一并继承 ✓）：
            #       · `pool_entry_mode=direct` ⇒ 自动跳过 资金流/基本面/公告 ✓；
            #       · 个股 ADX 不参与判定 ⇒ 自动跳过 `adx` ✓；
            #       · ★ 本引擎挂了 `self._router` ✓ ⇒ `index_adx_required=True` ✓
            #         ⇒ **大盘指数 ADX 的"起点覆盖 + 120 日预热"会硬拦** ✗✓
            #         （正是 `backtest_data_gate.check_index_adx` docstring 写明的期望行为 ✓）；
            #       · 产出 `data_gate_report` + `data_fingerprint` ✓（见下方结果字典 ✓）。
            #   ⚠️ 确实想跳过时 ✓：yaml `data.gate_skip: ['index_adx']` ✓ 或
            #     `KHUNTER_DATA_STRICT=0` ✓（降级为告警 ✓）—— **绝不静默放过** ✗✓。
            self.data_gate_report = self._run_data_gate(start_date, end_date,
                                                        date_range, config)

            # 4.5 ★【2026-09-27】**路由器预热** ✓ —— 让同一天档位**与回测起点无关** ✓
            #   实测反例 ✗✓（用户报 `2025-05-06` ✗）：起点在 `2025-04-22` 之后 ⇒
            #   错过 `04-18` 的峰值 `40.02` ✗ ⇒ 该日由「震荡/空仓」✗ 变「明确/满仓」✗。
            #   必须在此处 ✓（主循环前 ✓）、且在交易日历就绪后 ✓（要取 `start_date` 前一日 ✓），
            #   详见 `_warmup_router` docstring ✓。
            self._warmup_router(start_date)

            # 5. 预加载（改造：按候选策略预加载，保证各 regime 策略数据充足）
            self._preload_stock_data(start_date, end_date,
                                     self._pick_preload_strategy(strategy_name))

            # 6. 初始化回测环境
            initial_capital = config.get('initial_capital') or 300000
            current_capital = initial_capital
            positions = []
            trades = []
            capital_history = [initial_capital]
            dates = []

            max_buy_count_per_stock = config.get('max_buy_count_per_stock', 6)
            engine_config = self._load_engine_config()
            reverse_pool_order = engine_config.get('reverse_pool_order', 0)

            self.pool_mode = config.get('pool_mode') or engine_config.get('pool_mode', 'persistent')
            if self.pool_mode not in ('persistent', 'rotation'):
                logger.warning(f"未知 pool_mode={self.pool_mode}，回退为 persistent")
                self.pool_mode = 'persistent'
            logger.info(f"股票池模式 pool_mode={self.pool_mode}")
            stock_buy_count = {}
            day_strategy = strategy_name or ''      # 兜底：循环内每日覆盖

            # 原始买入执行方式（每日按 regime 方向覆盖后，可回退）
            _origin_buy_execution = config.get('buy_execution')
            if _origin_buy_execution is not None:
                _origin_buy_execution = dict(_origin_buy_execution)

            # ===== 进度：初始化（Web 端轮询用）=====
            _begin_regime_progress(len(date_range))

            for i, current_date in enumerate(date_range):
                logger.info(f"\n============================================================")
                logger.info(f"处理日期: {current_date}")
                logger.info(f"============================================================")

                # ===== 进度：每处理一个交易日更新 =====
                _update_regime_progress(i + 1, len(date_range), current_date)

                # ============ 改造①：按 ADX regime 决定当日策略/择时/仓位 ============
                _dec = self._decide(current_date)
                # 选股「空值」（空仓）不改变 day_strategy 的解析口径：选股与评分**照常执行**，
                # 仅把结果置 0（见下方“选股”段），保证流程/日志/统计与普通档位一致
                day_strategy = _dec.selector_strategy or strategy_name
                # 【2026-09-24】切换计数的**状态键** ✓：
                #   空仓档的 `selector_strategy` 为空 ✗ → 上面会退回 `strategy_name`
                #   （名字没变 ✗），若直接拿它比较，"空仓 ↔ 其他策略"永远不算切换 ✗✓。
                #   故把「空仓」显式记成一个**独立状态** ✓
                #   （选股**执行口径不变** ✓：空仓档仍照常选股/评分、只是结果置 0 ✓；
                #     该键仅用于**切换计数与状态比较** ✓）
                day_state = NO_SELECTION_LABEL if _dec.no_selection else day_strategy
                self._regime_ratio = float(_dec.position_ratio) if _dec.is_active() else 1.0

                # ===== 改造⑦：按 regime 方向决定买入执行方式 =====
                # 多头部 → open（T日开盘价）；空头部 → ma_limit（均线委托价）
                # 非生效（disabled/pending）时回退到进入回测时的原始配置
                if _dec.is_active() and _dec.buy_execution:
                    _be_cfg = dict(_origin_buy_execution or {})
                    _be_cfg['mode'] = _dec.buy_execution
                    config['buy_execution'] = _be_cfg
                else:
                    config['buy_execution'] = _origin_buy_execution
                _buy_mode = (config.get('buy_execution') or {}).get('mode') or 'yaml默认'

                if _dec.no_selection:
                    logger.info(f"【自适应】{current_date} 空仓（选股=空值）："
                                f"选股与评分照常执行，结果固定为 0 只（regime={_dec.regime}）")
                elif not day_strategy:
                    logger.warning(f"【自适应】{current_date} 无可用选股策略"
                                   f"（regime={_dec.regime}, source={_dec.source}），跳过当日选股")
                if day_state and self._current_state is None:
                    # 起始：只登记状态，**不计**切换 ✓
                    self._current_state = day_state
                    if day_strategy:
                        self._current_strategy = day_strategy
                    logger.info(f"【自适应】{current_date} 起始 regime={_dec.regime} "
                                f"状态={day_state} 策略={day_strategy or '—'} "
                                f"仓位={self._regime_ratio:.0%}")
                elif day_state:
                    # 【2026-09-24】选股状态变化 = 一次切换 ✓，且**必须清池** ✓
                    #   口径：**「空仓」也是一种选股策略**（选股结果为 0 只 ✓）——
                    #   其他策略 → 空仓、空仓 → 其他策略，同样要清池 ✓
                    if self._is_state_switch(self._current_state, day_state):
                        _prev_state = self._current_state
                        _no_selection = (day_state == NO_SELECTION_LABEL)
                        # ⚠️ 三条保留规则（2026-09-13 补充第 2 条；2026-09-16 确认保留）：
                        #   1. 持仓股一律保留（2026-09-11）：持仓与 regime 无关，
                        #      不论切到哪一档都留在池中，保证加仓链路不中断。
                        #   2. **同一选股策略选出的候选也保留**：风格档位切换 ≠ 选股策略切换
                        #      （如 震荡→萌芽 两档 selector 都是"主升低吸策略"），
                        #      此时不清池纯属浪费；比较用 _same_selector 做中/英文名归一化。
                        #   3. 只有"由其它选股策略选出"的候选才剔除（已失效）。
                        #   4. 【2026-09-24】切到**空仓档**：其"选股结果为 0 只" ✓
                        #      → 除持仓股外一律清掉 ✓（与"空仓也是一种选股策略"一致 ✓）
                        prev_pool = len(self.buy_candidate_pool)
                        _held_codes = {pos.get('stock_code') for pos in positions
                                       if pos.get('stock_code')}

                        def _keep(c):
                            code = c.get('stock', {}).get('stock_code')
                            if code in _held_codes:
                                return True
                            if _no_selection:
                                return False
                            return self._same_selector(c.get('strategy_name'), day_strategy)

                        self.buy_candidate_pool = [c for c in self.buy_candidate_pool
                                                   if _keep(c)]
                        _kept = len(self.buy_candidate_pool)

                        self.strategy_switches.append({
                            'date': str(current_date),
                            'from': _prev_state,
                            'to': day_state,
                            'regime': _dec.regime,
                            'cleared_pool': True,
                        })
                        logger.info(f"【自适应】{current_date} 选股策略切换 "
                                    f"{_prev_state} → {day_state}"
                                    f"（regime={_dec.regime}），清池 {prev_pool} 只"
                                    f" → 保留 {_kept} 只"
                                    f"（{'空仓档：仅保留持仓股 ✓' if _no_selection else '同选股策略候选 + 持仓'}）")
                        self._current_state = day_state
                        if day_strategy:
                            self._current_strategy = day_strategy

                # 择时策略按 regime 切换（须在卖出之前，保证当日卖出用新实例）
                if _dec.timing_strategy and _dec.timing_strategy != self.timing_strategy_name:
                    self._switch_timing(_dec.timing_strategy, config)

                # ===== 每个处理日期输出：regime / 选股 / 择时 / 仓位 / 近5日ADX =====
                _rec = self.regime_log[-1] if self.regime_log else {}
                _adx5 = [x for x in (_rec.get('adx5') or []) if x.get('adx') is not None]
                if _adx5:
                    # 每个 ADX 值后标注其即时 regime（如 18.3(震荡·多)）
                    _adx_txt = '/'.join(
                        f"{float(x['adx']):.1f}({_short_regime(x.get('regime'))})"
                        for x in _adx5)
                    _adx_avg = f"{sum(float(x['adx']) for x in _adx5) / len(_adx5):.1f}"
                else:
                    _adx_txt, _adx_avg = '无数据', '—'
                # 生效档 ≠ 即时档时，给出原因：
                #   确认计数已满却仍未切换 → 卡在缓冲带内（未越阈）
                #   计数未满              → 仍在等待连续确认（仅 confirm_days>1 时出现）
                _raw = str(_rec.get('raw_regime') or '')
                _smooth_txt = ''
                if _raw and _dec.regime and _raw != _dec.regime:
                    _cd = self._router.confirm_days
                    _cnt = int(_rec.get('confirm_count') or 0)
                    if _cnt >= _cd:
                        _smooth_txt = f" | 即时={_raw}（缓冲带内，未越阈）"
                    else:
                        _smooth_txt = f" | 即时={_raw}（确认 {_cnt}/{_cd}）"
                logger.info(
                    f"【自适应】{current_date} | 信号日={_rec.get('signal_date', '—')} "
                    f"| regime={_dec.regime or ('未生效(' + _dec.source + ')')}"
                    f"{_smooth_txt} "
                    f"| 选股={'空仓(结果置0)' if _dec.no_selection else (day_strategy or '—')} "
                    f"| 择时={self.timing_strategy_name or '—'} "
                    f"| 仓位={self._regime_ratio:.0%} "
                    f"| 买入={_buy_mode} "
                    f"| 近5日ADX={_adx_txt}（均{_adx_avg}）")

                # 初始化当日买入计数
                daily_buys = 0
                max_daily_buys = config.get('max_daily_buys', 5)

                today_sold_stocks = set()

                logger.info(f"当日初始资金: {current_capital:.2f}")
                logger.info(f"当日初始持仓: {len(positions)} 只股票")
                logger.info(f"当日最大买入限制: {max_daily_buys} 只")

                # 合并重复持仓
                if positions and len(positions) > 1:
                    merged = {}
                    for pos in positions:
                        code = pos['stock_code']
                        if code in merged:
                            merged[code]['quantity'] += pos['quantity']
                            merged[code]['buy_amount'] += pos['buy_amount']
                            merged[code]['buy_price'] = (merged[code]['buy_amount']
                                                         / merged[code]['quantity'])
                        else:
                            merged[code] = pos.copy()
                    new_positions = list(merged.values())
                    if len(new_positions) < len(positions):
                        logger.info(f"合并重复持仓: {len(positions)} -> {len(new_positions)}")
                    positions = new_positions

                # 处理卖出
                if positions:
                    logger.info(f"开始执行卖出操作，当前持仓数: {len(positions)}")
                    logger.info("当前持仓详情:")
                    for i, pos in enumerate(positions):
                        prev_close = self._get_stock_price(pos['stock_code'], current_date,
                                                           'prev_close')
                        prev_close_str = f"{prev_close:.2f}" if prev_close else 'N/A'
                        position_value = prev_close * pos['quantity'] if prev_close else 0.0
                        position_profit = position_value - pos['buy_amount']
                        profit_rate = (position_profit / pos['buy_amount']) * 100 if pos['buy_amount'] > 0 else 0.0
                        logger.info(f"  {i+1}. {pos['stock_code']} {pos['stock_name']}: 持仓数量={pos['quantity']}, 成本价={pos['buy_price']:.2f}, 昨日收盘价={prev_close_str}, 持仓市值={position_value:.2f}, 持仓收益={position_profit:.2f}({profit_rate:.2f}%)")

                    positions, sell_records = self._process_sell(positions, current_date, config)
                    logger.info(f"卖出操作完成，卖出 {len(sell_records)} 笔交易，剩余持仓数: {len(positions)}")

                    for sell_record in sell_records:
                        current_capital += sell_record['sell_amount']
                        trades.append(sell_record)
                        today_sold_stocks.add(sell_record['stock_code'])
                        total_sell_cost = (sell_record['sell_commission']
                                           + sell_record['sell_transfer_fee']
                                           + sell_record['sell_stamp_tax'])
                        logger.info(f"【卖出】股票: {sell_record['stock_code']} {sell_record['stock_name']}, 类型: {sell_record['sell_type']}, 价格: {sell_record['sell_price']:.2f}, 数量: {sell_record['quantity']}, 净金额: {sell_record['sell_amount']:.2f}(扣成本:佣金{sell_record['sell_commission']:.2f}+过户{sell_record['sell_transfer_fee']:.2f}+印花{sell_record['sell_stamp_tax']:.2f}), 收益率: {sell_record['return_rate']:.2f}%")

                    if today_sold_stocks:
                        logger.info(f"当日卖出股票: {list(today_sold_stocks)}")
                    else:
                        logger.info("当日无卖出股票")

                # 股票池移除检查（选股之前，使用前一日收盘价）
                if self.buy_candidate_pool:
                    logger.info(f"开始检查股票池移除条件，当前股票池数量: {len(self.buy_candidate_pool)}")
                    held_codes = {pos.get('stock_code') for pos in positions if pos.get('stock_code')}
                    removed = self._check_pool_removal(current_date, config, held_codes=held_codes)
                    if removed:
                        logger.info(f"股票池移除 {len(removed)} 只股票")

                # 选股（改造②：使用当日 regime 策略）
                # ★★【2026-09-29 用户要求 ✓】**"不开新仓" ⇒ 跳过选股执行** ✗→✓ ★★
                #   用户口径 ✓："回测时，如果判定当日不开新仓，**跳过选股执行过程**，
                #   直接返回选股结果为 0" ✓ + "**建议作为开关参数，便于对比回测效果**" ✓。
                #   两处判据 ✓（任一命中即"不开新仓" ✓）：
                #     ① **自适应档位**："空仓（选股=空值）" ✓（`_dec.no_selection` ✓）；
                #     ② **仓位上限 0%** ✓（`_day_no_new_position` ✓ —— 只判档位 ✓）。
                #   **开关** ✓：`skip_selection_when_no_new_position`（默认 **开** ✓）
                #     ⇒ 关掉回到**旧行为** ✓（选股/评分照常执行、结果置 0 ✓）⇒ 可 A/B ✓。
                selection_date = self._get_previous_trading_day(current_date)
                candidate_stocks = []
                _skip_sel, _skip_why = False, ''
                if day_strategy:
                    if _dec.no_selection:
                        if self._skip_selection_switch(config):
                            _skip_sel = True
                            _skip_why = '【自适应】当日空仓（选股=空值 ✓）'
                    else:
                        # ★【2026-10-07 审计修复 ✓】同 `BacktestEngine` ✓：回测硬钉"前一根" ✓
                        #   （防 yaml 误开 ⇒ 前视 ✗；并保证与下方买入分支**同一时点** ✓）
                        from trading.index_adx_filter import backtest_gate_config as _bt_cfg
                        _nc = self._day_no_new_position(current_date, _bt_cfg(config))
                        if _nc is not None:
                            _skip_sel = True
                            _skip_why = f"仓位上限 **0%** ✓（{_nc.get('rule') or ''}）"
                if _skip_sel:
                    logger.info(
                        f"【跳过选股】{current_date} {_skip_why} ⇒ 选股结果 = **0** ✓"
                        f"（跳过选股/评分 ✓；卖出与加仓不受影响 ✓）")
                elif day_strategy:
                    logger.info(f"执行选股日期: {selection_date}")
                    candidate_stocks = self._select_and_score_stocks(
                        day_strategy, selection_date, config)
                    if _dec.no_selection:
                        # 开关**关** ⇒ 旧行为 ✓：照常执行、仅结果置 0 ✓（便于 A/B ✓）
                        logger.info(
                            f"【自适应】{current_date} 空仓（选股=空值）：选股/评分已执行，"
                            f"结果置 0（原 {len(candidate_stocks)} 只，不进候选池）")
                        candidate_stocks = []

                # 新选出的股票加入可买池
                new_added = 0
                for stock in candidate_stocks:
                    if not any(item['stock']['stock_code'] == stock['stock_code']
                               for item in self.buy_candidate_pool):
                        # 改造③：支撑位算法使用当日策略
                        support_level = self._calculate_support_level(
                            stock, selection_date, day_strategy)
                        # 改造④：支撑位方法使用当日策略
                        support_method = self._get_support_method_for_strategy(day_strategy)

                        key_date = stock.get('signal', {}).get('key_date')
                        if key_date:
                            if hasattr(key_date, 'strftime'):
                                key_date = key_date.strftime('%Y-%m-%d')
                            key_date = str(key_date)
                        else:
                            key_date = (selection_date.strftime('%Y-%m-%d')
                                        if hasattr(selection_date, 'strftime')
                                        else str(selection_date))

                        self.buy_candidate_pool.append({
                            'stock': stock,
                            'added_date': selection_date,
                            'key_date': key_date,
                            # 改造⑤：记录当日 regime 策略（供 Kelly / 池移除配置查找）
                            'strategy_name': day_strategy,
                            'support_level': support_level,
                            'support_method': support_method
                        })
                        if support_level > 0:
                            logger.info(f"股票 {stock['stock_code']} {stock['stock_name']} 加入可买股票池, "
                                        f"关键日={key_date}, 支撑位={support_level:.2f}, 方法={support_method}")
                        else:
                            logger.info(f"股票 {stock['stock_code']} {stock['stock_name']} 加入可买股票池, 支撑位计算失败")
                        new_added += 1

                # ===== 持仓股自动入池（当日已卖出的不计），便于加仓 =====
                from trading.pool_entry_rules import resolve_auto_add_holdings

                if resolve_auto_add_holdings(config, self._load_engine_config()):
                    self._add_holdings_to_pool(positions, current_date, today_sold_stocks,
                                               day_strategy or strategy_name)

                logger.info(f"\n当前可买股票池数量: {len(self.buy_candidate_pool)} (新增 {new_added} 只)")
                if self.buy_candidate_pool:
                    logger.info("可买股票池详情:")
                    for i, candidate in enumerate(self.buy_candidate_pool):
                        stock = candidate['stock']
                        added_date = candidate['added_date']
                        support_level = candidate.get('support_level', 0.0)
                        support_method = candidate.get('support_method', 'unknown')
                        score = stock.get('score', 'N/A')
                        support_info = (f"，支撑位={support_level:.2f}({support_method})"
                                        if support_level > 0 else "，支撑位=未计算")
                        logger.info(f"  {i+1}. {stock['stock_code']} {stock['stock_name']}: 加入日期={added_date}，评分={score}{support_info}")
                remaining_candidates = []
                today_bought_stocks = set()

                pool_iter = (reversed(self.buy_candidate_pool) if reverse_pool_order
                             else self.buy_candidate_pool)
                if reverse_pool_order:
                    logger.info("买入顺序：倒序处理（新加入股票优先）")

                for candidate in pool_iter:
                    stock = candidate['stock']
                    stock_code = stock['stock_code']
                    added_date = candidate['added_date']

                    if stock_code in today_bought_stocks:
                        logger.info(f"股票 {stock_code} 当日已买入，继续跟踪")
                        remaining_candidates.append(candidate)
                        continue

                    current_buy_count = stock_buy_count.get(stock_code, 0)
                    if current_buy_count >= max_buy_count_per_stock:
                        logger.info(f"股票 {stock_code} 已买入{current_buy_count}次，达到最大买入次数{max_buy_count_per_stock}，跳过")
                        remaining_candidates.append(candidate)
                        continue

                    enable_loss_cool_down = config.get('enable_loss_cool_down', True)
                    enable_consecutive_loss_limit = config.get('enable_consecutive_loss_limit', True)
                    max_consecutive_losses = config.get('max_consecutive_losses', 2)

                    if enable_loss_cool_down or enable_consecutive_loss_limit:
                        if self._check_cool_down(stock_code, current_date):
                            cool_down_end = self.loss_cool_down_pool.get(stock_code, 'N/A')
                            logger.info(f"股票 {stock_code} 在冷却期内（至 {cool_down_end}），跳过")
                            remaining_candidates.append(candidate)
                            continue

                    if enable_consecutive_loss_limit:
                        consecutive_count = self.consecutive_loss_count.get(stock_code, 0)
                        if consecutive_count >= max_consecutive_losses:
                            logger.info(f"股票 {stock_code} 连续亏损 {consecutive_count} 次，达到限制 {max_consecutive_losses}，跳过")
                            remaining_candidates.append(candidate)
                            continue

                    if stock_code in today_sold_stocks:
                        logger.info(f"【未买入】{stock_code} {stock.get('stock_name', '')}: "
                                    f"当日已卖出，不再买入")
                        remaining_candidates.append(candidate)
                        continue

                    if daily_buys >= max_daily_buys:
                        logger.info(f"【未执行买入】{stock_code} {stock.get('stock_name', '')}: 达到今日买入次数{max_daily_buys}次限制，未执行")
                        remaining_candidates.append(candidate)
                        continue

                    df = self.stock_filtered_cache.get(stock_code)
                    if df is None:
                        logger.warning(f"无法获取股票 {stock_code} 的数据，跳过")
                        remaining_candidates.append(candidate)
                        continue

                    date_str = current_date.strftime('%Y-%m-%d')
                    df_to_date = df[df['date'] <= date_str].copy()
                    if df_to_date.empty:
                        logger.warning(f"股票 {stock_code} 没有可用数据，跳过")
                        remaining_candidates.append(candidate)
                        continue

                    today = datetime.now().date()
                    last_data_date = df_to_date['date'].max()
                    if current_date == today and last_data_date < date_str:
                        logger.info(f"股票 {stock_code} 最后数据日期为 {last_data_date}，尝试获取实时数据...")
                        try:
                            realtime_price = self.stock_data_fetcher.get_stock_price(stock_code)
                            if realtime_price and realtime_price > 0:
                                prev_row = df_to_date[df_to_date['date'] == last_data_date].iloc[-1]
                                prev_close = float(prev_row['close'])
                                open_price = prev_close
                                high_price = realtime_price if realtime_price > prev_close else prev_close
                                low_price = realtime_price if realtime_price < prev_close else prev_close
                                new_row = pd.DataFrame([{
                                    'date': date_str,
                                    'open': open_price,
                                    'high': high_price,
                                    'low': low_price,
                                    'close': realtime_price,
                                    'volume': prev_row['volume']
                                }])
                                df_to_date = pd.concat([df_to_date, new_row], ignore_index=True)
                                logger.info(f"股票 {stock_code} 添加实时数据: {date_str} 开盘={open_price}, 收盘={realtime_price}")
                                try:
                                    merged = pd.concat([df, new_row], ignore_index=True)
                                    self.stock_filtered_cache[stock_code] = merged
                                    if stock_code in self.stock_data_cache:
                                        self.stock_data_cache[stock_code] = merged.copy()
                                except Exception as cache_err:
                                    logger.warning(f"股票 {stock_code} 实时数据回写缓存失败: {cache_err}")
                        except Exception as e:
                            logger.warning(f"股票 {stock_code} 获取实时数据失败: {str(e)}")

                    if len(df_to_date) > 1 and df_to_date['date'].iloc[0] < df_to_date['date'].iloc[-1]:
                        df_to_date = df_to_date.iloc[::-1].reset_index(drop=True)

                    existing_pos = None
                    for pos in positions:
                        if pos['stock_code'] == stock_code:
                            existing_pos = pos
                            break

                    result = None
                    if self.timing_strategy:
                        result = self.timing_strategy.get_timing_result(
                            df_to_date, existing_pos, current_capital, stock_code=stock_code)
                        timing_name = self.timing_strategy.__class__.__name__
                        # 【2026-09-28 减噪 ✗→✓】同 `backtest_engine` ✓：只在**真有信号**时
                        #   INFO ✓，其余降 `debug` ✓（原文案逐票逐日刷 ✗，实测单日 2 万行级 ✗）
                        _sig_msg = (f"{timing_name}信号: is_buy={result.is_buy}, "
                                    f"is_sell={result.is_sell}, buy_qty={result.buy_quantity}, "
                                    f"sell_qty={result.sell_quantity}, type={result.trade_type}, "
                                    f"msg={result.message}")
                        if result.is_buy or result.is_sell:
                            logger.info(_sig_msg)
                        else:
                            logger.debug(_sig_msg)

                    is_buy = result.is_buy if result else False
                    if not is_buy:
                        logger.info(f"【未买入】{stock_code} {stock['stock_name']}: 无买入信号")
                        remaining_candidates.append(candidate)
                        continue

                    if self._should_apply_buy_filter(result, existing_pos):
                        limit_up_enabled = config.get(
                            'enable_limit_up_check',
                            self._load_engine_config().get('enable_limit_up_check', True))
                        filter_result = _be.BuyPreFilter.check_filters_with_config(
                            df_to_date, stock_code,
                            {'enable_limit_up_check': limit_up_enabled})
                        if not filter_result['passed']:
                            logger.info(f"【未买入】{stock_code} {stock['stock_name']}: K线过滤未通过 - {filter_result['reason']}")
                            remaining_candidates.append(candidate)
                            continue

                    # ---------- ★★【2026-09-30 用户要求 ✓】**逐票「当日仓位上限」闸门** ✗→✓ ----------
                    #   缺口 ✗✓：本引擎**只有**"档位仓位系数 `_regime_ratio`"（见下方 ✓），
                    #     而**没有**父类 buy 循环里的 `index_position_cap_gate` ✗
                    #     ⇒ 与普通回测**少一道闸门** ✗（同一份策略两边结果不可直接比 ✗）。
                    #   口径 ✓：**与普通回测逐字同口径** ✗✓（照抄 `backtest_engine.py` 同一块 ✓）：
                    #     · **仅约束开新仓** ✗✓（整块在 `existing_pos is None` 内 ✓，加仓不受限 ✓）；
                    #     · 判据来自**大盘指数 ADX**（`market_index_adx` ✓，只用 **T-1** ✓ 防前视 ✓）；
                    #     · 规则 ✓：`ADX>25 ∧ dir上升 ⇒ 100%` ✓ / `ADX<18 ∧ dir上升 ⇒ 50%` ✓ /
                    #       **其他 ⇒ 0% ⇒ 不允许开仓** ✓；**持仓 ≥ 上限 ⇒ 停开新仓** ✓。
                    #   ⚠️ 与档位系数的**关系** ✓：两者**独立叠加** ✓（档位系数管"**总仓位目标**" ✓；
                    #     本闸门管"**大盘状态是否允许开新仓**"✗）⇒ 任一不过 ⇒ 不开新仓 ✓。
                    # ★【2026-10-07 审计修复 ✓】大盘与个股**共用**这份被钉死的 cfg ✓
                    #   （钉死"前一根" ✓ ⇒ 两者**不可能**分时点 ✓；须在 `if` 之前定义 ✓）
                    from trading.index_adx_filter import backtest_gate_config as _bt_cfg
                    _gate_cfg = _bt_cfg(config)
                    if existing_pos is None:
                        from trading.index_adx_filter import (
                            format_index_position_cap_result, index_position_cap_gate,
                            is_index_position_cap_enabled)
                        if is_index_position_cap_enabled(_gate_cfg):
                            _cur_ratio_cap = self._current_position_ratio(
                                current_date, positions, current_capital)
                            _cap_gate = index_position_cap_gate(
                                current_date, _cur_ratio_cap, _gate_cfg,
                                stock_code=stock_code)      # ★ 板块回退需知其所属板块 ✓
                            if not _cap_gate['passed']:
                                logger.info(
                                    f"【未买入】{stock_code} {stock['stock_name']}: "
                                    f"{format_index_position_cap_result(_cap_gate)}")
                                remaining_candidates.append(candidate)
                                continue
                            logger.info(f"【仓位上限】{current_date} {stock_code} "
                                        f"{stock['stock_name']}: "
                                        f"{format_index_position_cap_result(_cap_gate)}")

                    # ---------- 【2026-09-26 §5.6】个股 ADX 闸门 ✓（**首仓 + 加仓 均生效** ✗✓）----------
                    #   与 `BacktestEngine` 口径一致 ✓（`_should_apply_adx_filter` 由其**继承** ✓）
                    if self._should_apply_adx_filter(result, existing_pos):
                        from trading.stock_adx_filter import (add_entry_gate,
                                                              adx_entry_gate)
                        # ★【2026-10-07 审计修复 ✓】用**同一份** `_gate_cfg` ✗→✓（= 大盘那份 ✓）
                        adx_gate = (add_entry_gate(df_to_date, stock_code, _gate_cfg,
                                                   signal_date=current_date)
                                    if existing_pos is not None
                                    else adx_entry_gate(df_to_date, stock_code, _gate_cfg,
                                                        signal_date=current_date))
                        if not adx_gate['passed']:
                            # ★【2026-09-28】未通过也带 `ADX(T-1)` ✓（与普通回测同口径 ✓）
                            from trading.stock_adx_filter import format_gate_result
                            logger.info(f"【未买入】{stock_code} {stock['stock_name']}: "
                                        f"{format_gate_result(adx_gate)}")
                            remaining_candidates.append(candidate)
                            continue
                        # ★【2026-09-27 用户要求 ✓】**通过也要留痕** ✗✓ ——
                        #   否则"买入成功时看不到个股 ADX 信息"✗（实测反馈 ✓）
                        from trading.stock_adx_filter import format_gate_result
                        logger.info(f"【ADX 闸门】{current_date} {stock_code} "
                                    f"{stock['stock_name']}: {format_gate_result(adx_gate)}")

                    if not self._has_trading_data_on_date(stock_code, current_date):
                        logger.info(f"【未买入】{stock_code} {stock['stock_name']}: 当日{current_date}无行情数据（停牌/退市），跳过")
                        remaining_candidates.append(candidate)
                        continue

                    exec_result = self._resolve_buy_execution(
                        stock_code, current_date, config, df_to_date)
                    buy_price = exec_result['price']
                    # 【2026-09-23 修复】买入滑点：与父类 BacktestEngine :734-739 逐字同口径 ✓
                    #   本类复制父类买入循环时漏了这一段 ✗ → 自适应回测买入零滑点 ✗
                    #   口径：成交价取不利方向（更贵 ✓）—— buy_price × (1 + buy) ✓
                    #   例外：ma_limit 模式的委托价**自带** slippage ✗ → 该模式不叠加 ✓（避免双计 ✗）
                    _slip = getattr(self, '_slippage', self.DEFAULT_SLIPPAGE)
                    _buy_slip = 0.0 if exec_result.get('mode') == 'ma_limit' else _slip['buy']
                    if buy_price and buy_price > 0 and _buy_slip:
                        buy_price = round(buy_price * (1.0 + _buy_slip), 4)
                    if not exec_result['filled']:
                        logger.info(f"【未买入】{current_date} {stock_code} "
                                    f"{stock['stock_name']}: {exec_result['reason']}"
                                    f"（委托价={exec_result['order_price']:.2f}）")
                        remaining_candidates.append(candidate)
                        continue
                    trade_type = result.trade_type if result else 'new'

                    # ===== 改造⑥（2026-09-11 语义调整）：仓位系数 = 总仓位上限 =====
                    # 当前持仓比例 >= 系数  → 停止【开仓】（新建仓）
                    # 当前持仓比例 <  系数  → 按"剩余可开仓额度"开仓
                    #     额度 = 总资产 × 系数 − 当前持仓市值
                    # ⚠️ 加仓不受仓位系数限制（2026-09-14）：与实盘一致 —— 实盘的仓位风控
                    #    只做提示、不阻止信号生成（见 strategy_runner 连续温度风控注释），
                    #    加仓属对已建仓头寸的追加，额度按「可用资金」计算。
                    _prev_td = self._get_previous_trading_day(current_date)
                    _total_assets_now = current_capital
                    for _pos in positions:
                        _p = self._get_stock_price(_pos['stock_code'], _prev_td, 'close')
                        if _p is None or _p <= 0:
                            _p = _pos['buy_price']
                        _total_assets_now += _pos['quantity'] * _p
                    _held_value = _total_assets_now - current_capital
                    _cur_ratio = (_held_value / _total_assets_now
                                  if _total_assets_now > 0 else 0.0)
                    if trade_type == 'add':
                        # 加仓：不受仓位系数上限压制，额度=可用资金
                        if _cur_ratio >= self._regime_ratio:
                            logger.info(f"【自适应仓位】{current_date} {stock_code} "
                                        f"当前持仓比例 {_cur_ratio:.1%} ≥ 仓位系数 "
                                        f"{self._regime_ratio:.0%}，但【加仓不受仓位限制】，"
                                        f"按可用资金 {current_capital:.0f} 元继续")
                        remaining_quota = current_capital
                    else:
                        if _cur_ratio >= self._regime_ratio:
                            logger.info(f"【自适应仓位】{current_date} {stock_code} "
                                        f"当前持仓比例 {_cur_ratio:.1%} ≥ 仓位系数 "
                                        f"{self._regime_ratio:.0%}，停止开仓")
                            remaining_candidates.append(candidate)
                            continue
                        remaining_quota = max(0.0, _total_assets_now * self._regime_ratio
                                              - _held_value)

                    kelly_result = {}
                    if trade_type == 'add':
                        # 加仓数量 = max(策略信号数量, 1/2 凯利金额对应数量)，
                        # 且仍不得超过"剩余可开仓额度"（自适应引擎的仓位系数约束）
                        _add_kelly = _be.KellyCalculator.calculate_position_amount_with_params(
                            total_capital=_total_assets_now,
                            available_cash=current_capital,
                            strategy_name=candidate.get('strategy_name', day_strategy or 'N/A')
                        )
                        _half_kelly_qty = _be.KellyCalculator.calculate_buy_quantity(
                            position_amount=_add_kelly['amount'] / 2,
                            price=buy_price,
                            stock_code=stock_code
                        )
                        if result and result.buy_quantity > 0:
                            _signal_qty = result.buy_quantity
                        else:
                            # 策略未给定数量：用配置金额（受额度约束）折算
                            config_buy_amount = min(config.get('buy_amount', 100000),
                                                    remaining_quota)
                            _signal_qty = int(config_buy_amount / buy_price) // 100 * 100
                        _max_qty = int(remaining_quota / buy_price) // 100 * 100
                        quantity = min(max(_signal_qty, _half_kelly_qty), _max_qty)
                        logger.info(f"【加仓数量】{current_date} {stock_code} {stock['stock_name']}: "
                                    f"策略信号={_signal_qty}股, 1/2凯利金额="
                                    f"{_add_kelly['amount'] / 2:.2f}元→{_half_kelly_qty}股, "
                                    f"额度上限={_max_qty}股, 最终={quantity}股")

                        # 数量不足一手时不得下单（2026-09-13）：
                        # 剩余可开仓额度不足一手时 _max_qty = 0 → min(...) = 0，
                        # 此前缺少守卫会落库 0 股 / 0 元的加仓订单（本次回测 3 笔、
                        # 全库 26 笔全部是 add），并误增 add_count / last_add_price
                        from utils.stock_utils import get_min_trade_unit
                        _min_unit = get_min_trade_unit(stock_code)
                        if quantity < _min_unit:
                            logger.info(f"【未加仓】{current_date} {stock_code} {stock['stock_name']}: "
                                        f"数量不足{_min_unit}股（额度上限={_max_qty}股，"
                                        f"策略信号={_signal_qty}股，半凯利={_half_kelly_qty}股），跳过")
                            remaining_candidates.append(candidate)
                            continue
                    else:
                        # 首次建仓：凯利公式（策略取"当日 regime 策略"）
                        kelly_strategy_name = candidate.get('strategy_name', day_strategy or 'N/A')

                        total_assets = current_capital
                        prev_trading_day = self._get_previous_trading_day(current_date)
                        for position in positions:
                            position_price = self._get_stock_price(
                                position['stock_code'], prev_trading_day, 'close')
                            if position_price is None or position_price <= 0:
                                position_price = position['buy_price']
                            total_assets += position['quantity'] * position_price

                        kelly_result = _be.KellyCalculator.calculate_position_amount_with_params(
                            total_capital=total_assets,
                            available_cash=current_capital,
                            strategy_name=kelly_strategy_name
                        )
                        kelly_amount = kelly_result['amount']

                        # 改造⑥：仓位系数只作"总仓位上限"比对，不缩放单笔金额；
                        # 单笔金额 = min(凯利金额, 剩余可开仓额度)
                        if kelly_amount > remaining_quota:
                            logger.info(f"【自适应仓位】{current_date} {stock_code} "
                                        f"凯利金额 {kelly_amount:.0f} 超过剩余可开仓额度 "
                                        f"{remaining_quota:.0f}（仓位系数 "
                                        f"{self._regime_ratio:.0%}，当前持仓 "
                                        f"{_cur_ratio:.1%}），按额度开仓")
                            kelly_amount = remaining_quota

                        if current_capital >= kelly_amount:
                            position_amount = kelly_amount
                            reserve_fee = 0.0
                        else:
                            position_amount = current_capital
                            reserve_fee = position_amount % 100
                            position_amount = position_amount // 100 * 100

                        quantity = _be.KellyCalculator.calculate_buy_quantity(
                            position_amount=position_amount,
                            price=buy_price,
                            stock_code=stock_code
                        )
                        from utils.stock_utils import get_min_trade_unit
                        min_unit = get_min_trade_unit(stock_code)
                        if quantity < min_unit:
                            logger.info(f"【未买入】{stock_code} {stock['stock_name']}: 买入数量不足{min_unit}股")
                            remaining_candidates.append(candidate)
                            continue

                        logger.info(f"【凯利公式计算】{current_date} {stock_code} {stock['stock_name']}: "
                                    f"策略={kelly_strategy_name}, 胜率={kelly_result['win_rate']:.2f}, 盈亏比={kelly_result['profit_loss_ratio']:.2f}, "
                                    f"凯利比例={kelly_result['kelly_ratio']:.4f}, 总资产={total_assets:.2f}, "
                                    f"可用资金={current_capital:.2f}, 凯利金额={kelly_amount:.2f}, 预留费用={reserve_fee:.2f}, 实际买入={position_amount:.2f}")

                    buy_amount = quantity * buy_price
                    if current_capital < 2000:
                        logger.info(f"【未执行买入】{stock_code} {stock['stock_name']}: 可用资金不足2000元（当前{current_capital:.2f}元），跳过执行")
                        remaining_candidates.append(candidate)
                        continue

                    # 含交易费用校验（2026-09-13）：
                    # 原逻辑仅比较 buy_amount 与可用资金，未给佣金/过户费留位，
                    # 买入后 current_capital -= (buy_amount + 费用) 会扣出几毛钱负数。
                    # 现在要求「买入金额 + 佣金 + 过户费 ≤ 可用资金」，不足则按手数回退。
                    from utils.stock_utils import get_min_trade_unit
                    _min_unit = get_min_trade_unit(stock_code)
                    while quantity >= _min_unit:
                        buy_amount = quantity * buy_price
                        _cost = _be.calculate_backtest_cost(stock_code, buy_price, quantity, is_buy=True)
                        _need = buy_amount + _cost['commission'] + _cost['transfer_fee']
                        if _need <= current_capital:
                            break
                        # 通常只差"费用"这一小截：按差额退手（至少退一手）后复验
                        _deficit = _need - current_capital
                        quantity -= max(1, int(_deficit / (buy_price * _min_unit)) + 1) * _min_unit
                    if quantity < _min_unit:
                        logger.info(f"【未买入】{stock_code} {stock['stock_name']}: 可用资金不足以覆盖含费买入（当前{current_capital:.2f}元，价格{buy_price:.2f}），跳过执行")
                        remaining_candidates.append(candidate)
                        continue
                    buy_amount = quantity * buy_price

                    # 成交价日志移到"确认执行"处：原位置在仓位/数量闸门之前，
                    # 候选被闸门拦下时也会打印，容易被误读为已成交
                    logger.info(f"股票 {current_date} {stock_code} {stock['stock_name']} "
                                f"买入成交价: {buy_price:.2f}（委托价="
                                f"{exec_result['order_price']:.2f}, 方式={exec_result['mode']}，"
                                f"数量={quantity}）")

                    trade_type = result.trade_type if result else 'new'
                    buy_record = self._execute_buy(stock_code, stock['stock_name'], added_date,
                                                   current_date, buy_price, buy_amount, quantity)
                    buy_record['trade_type'] = trade_type

                    if existing_pos:
                        old_quantity = existing_pos['quantity']
                        existing_pos['quantity'] += quantity
                        existing_pos['buy_amount'] += buy_amount
                        existing_pos['buy_price'] = (existing_pos['buy_amount']
                                                     / existing_pos['quantity'])
                        result_add_count = getattr(result, 'add_count', 0) if result else 0
                        existing_pos['add_count'] = (result_add_count if result_add_count > 0
                                                     else existing_pos.get('add_count', 0) + 1)
                        existing_pos['last_add_price'] = buy_price
                        existing_pos['last_add_date'] = current_date
                        logger.info(f"【加仓#{existing_pos['add_count']}】{current_date} {stock_code} {stock['stock_name']}: "
                                    f"原数量={old_quantity}, 加仓={quantity}, 合计={existing_pos['quantity']}, "
                                    f"均价={existing_pos['buy_price']:.2f}, 金额={buy_amount}")
                    else:
                        base_position_amount = buy_amount
                        positions.append({
                            'stock_code': stock_code,
                            'stock_name': stock['stock_name'],
                            'buy_date': current_date,
                            'buy_price': buy_price,
                            'quantity': quantity,
                            'buy_amount': buy_amount,
                            'base_position_amount': base_position_amount,
                            'buy_commission': buy_record['buy_commission'],
                            'buy_transfer_fee': buy_record['buy_transfer_fee'],
                            'kelly_win_rate': kelly_result.get('win_rate'),
                            'kelly_profit_loss_ratio': kelly_result.get('profit_loss_ratio'),
                            'kelly_ratio': kelly_result.get('kelly_ratio'),
                            'kelly_strategy_name': kelly_result.get('strategy_name')
                        })
                        buy_cost = buy_record['buy_commission'] + buy_record['buy_transfer_fee']
                        logger.info(f"【新买入】{current_date} {stock_code} {stock['stock_name']}: 价格={buy_price}, 数量={quantity}, 金额={buy_amount}, 首次建仓={base_position_amount}")

                    current_capital -= (buy_amount + buy_record['buy_commission']
                                        + buy_record['buy_transfer_fee'])
                    trades.append(buy_record)
                    daily_buys += 1
                    today_bought_stocks.add(stock_code)
                    stock_buy_count[stock_code] = stock_buy_count.get(stock_code, 0) + 1
                    remaining_candidates.append(candidate)

                self.buy_candidate_pool = remaining_candidates
                logger.info(f"处理后可买股票池数量: {len(self.buy_candidate_pool)}")

                # 当日总资产
                total_assets = current_capital
                position_details = []
                prev_trading_day = self._get_previous_trading_day(current_date)
                prev_day_str = (prev_trading_day.strftime('%Y-%m-%d')
                                if prev_trading_day else current_date)
                for position in positions:
                    current_price = self._get_stock_price(
                        position['stock_code'], prev_trading_day, 'close')
                    if current_price is None or current_price <= 0:
                        current_price = position['buy_price']
                    position_value = current_price * position['quantity']
                    total_assets += position_value
                    buy_date_str = position['buy_date'].strftime('%Y-%m-%d')
                    trading_days = self._get_trading_dates(buy_date_str, prev_day_str)
                    hold_days = len(trading_days) - 1 if len(trading_days) > 0 else 0
                    position_details.append({
                        'code': position['stock_code'],
                        'name': position['stock_name'],
                        'price': current_price,
                        'quantity': position['quantity'],
                        'value': position_value,
                        'hold_days': hold_days
                    })

                logger.info(f"\n========== {current_date} 每日资产 ==========")
                logger.info(f"资金余额: {current_capital:.2f}")
                if position_details:
                    logger.info(f"持股清单 ({len(position_details)} 只):")
                    for p in position_details:
                        logger.info(f"  - {p['code']} {p['name']}: "
                                    f"价格={p['price']:.2f}, 数量={p['quantity']}, "
                                    f"市值={p['value']:.2f}, 持{p['hold_days']}日")
                else:
                    logger.info(f"持股清单: 空仓")
                logger.info(f"持股市值: {total_assets - current_capital:.2f}")
                logger.info(f"总资产: {total_assets:.2f}")
                logger.info(f"==========================================")

                capital_history.append(total_assets)
                dates.append(current_date)

            # 结束结算
            if positions:
                logger.info("计算剩余持仓市值")
                final_date = date_range[-1]
                prev_trading_day = self._get_previous_trading_day(final_date)
                for position in positions:
                    current_price = self._get_stock_price(
                        position['stock_code'], prev_trading_day, 'close')
                    if current_price is None or current_price <= 0:
                        current_price = position['buy_price']
                    current_value = current_price * position['quantity']
                    current_capital += current_value
                    logger.info(f"剩余持仓: {position['stock_code']} {position['stock_name']}, "
                                f"买入价={position['buy_price']:.2f}, 当前价={current_price:.2f}, "
                                f"市值={current_value:.2f}")
                if capital_history:
                    capital_history[-1] = current_capital

            final_capital = current_capital
            performance = self._calculate_performance(trades, initial_capital, final_capital,
                                                      dates, capital_history)

            # 结果（父类结构 + 自适应扩展）
            backtest_result = {
                'strategy_name': (f'自适应({day_strategy})' if day_strategy
                                  else '自适应'),
                'config': config,
                'start_date': start_date,
                'end_date': end_date,
                'initial_capital': initial_capital,
                'final_capital': final_capital,
                'performance': performance,
                'trades': trades,
                'capital_history': capital_history,
                'dates': dates,
                'timing_strategy': {
                    'name': self.timing_strategy_name,
                    'params': self.timing_strategy_params
                },
                # ★【2026-09-30】数据可追溯 ✓（与**普通回测同结构** ✗→✓）——
                #   补齐闸门后才有这两项 ✓ ⇒ 落库时 `data_version` 由指纹派生 ✓
                #   （`trading/backtest_dao.py::save_result` ✓）⇒ 两份结果可直接比对
                #   "**是不是底层数据变过**" ✓（此前自适应这份恒为空 ✗✓）。
                'data_gate': {
                    'strict': (self.data_gate_report or {}).get('strict'),
                    'ok': (self.data_gate_report or {}).get('ok'),
                    'trade_days': (self.data_gate_report or {}).get('trade_days'),
                },
                'data_fingerprint': json.dumps(self.data_fingerprint or {},
                                               ensure_ascii=False),
                # ★★【2026-10-03 用户要求 ✓】本次**主要参数设置情况** ✗→✓ ★★
                #   与普通回测**同一实现** ✓（`build_param_snapshot` ✓）⇒ 两份结果可比 ✓；
                #   ⚠️ 择时策略**按档位切换** ✗ ⇒ 这里只记"入口口径" ✓，
                #     各档位选择见 `router_config` ✓（详情页单列 ✓）。
                'param_snapshot': self.build_param_snapshot(
                    config, tag='自适应引擎'),
                # ===== 自适应扩展 =====
                'regime_stats': self._summarize_by_regime(trades, self.regime_log),
                'strategy_switches': self.strategy_switches,
                'regime_timeline': self.regime_log,
                'adaptive': True,
            }

            logger.info(f"自适应回测完成，初始资金: {initial_capital}, 最终资金: {final_capital}, "
                        f"总收益率: {performance['total_return']:.2f}%, "
                        f"策略切换 {len(self.strategy_switches)} 次")

            # ===== 进度：完成 =====
            _end_regime_progress('完成')

            return backtest_result

        except Exception as e:
            logger.error(f"自适应回测失败: {str(e)}")
            _end_regime_progress(f'失败: {e}', ok=False)
            raise
        finally:
            _be.sleep_preventer.stop()
            _be._backtest_lock.release()
