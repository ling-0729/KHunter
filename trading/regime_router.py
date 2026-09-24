# -*- coding: utf-8 -*-
"""ADX 自适应路由模块（独立功能，默认关闭）

根据全A指数 ADX 强度档（震荡 / 萌芽 / 明确）决定当日的：
  选股策略 / 择时策略 / 仓位系数 / 买入执行方式

分类口径（2026-09-11 简化）：仅按强度 3 档，不再区分多空方向
  震荡 < 20 / 萌芽 20~25 / 明确 >= 25

设计文档：doc/ADX自适应策略设计说明书.md（第 10 章）

核心特性：
  1. 独立、无副作用、可单测；异常一律回退 disabled，不阻断主流程
  2. 连续 confirm_days（默认 5）个交易日同档才切换，抑制抖动
  3. 人工覆盖优先于自动路由
  4. 防前视：只使用 trade_date 及之前的 ADX

使用示例：
    router = RegimeRouter()
    d = router.decide('2026-09-10')
    if d.source != 'disabled':
        selector, timing, position = d.selector_strategy, d.timing_strategy, d.position_ratio
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / 'config' / 'regime_router.yaml'
_STATE_PATH = _PROJECT_ROOT / 'data' / 'running' / 'regime_state.json'

# 买入执行方式默认值（按档位，2026-09-11）：
#   明确 → open      ：T 日开盘价成交（趋势向上，不苛求回踩均线）
#   萌芽 → ma_limit  ：方向不明确 → 保守，挂均线委托价
#   震荡 → ma_limit  ：弱趋势 → 保守，挂均线委托价
#   参数与口径见 config/backtest_engine_config.yaml 的 buy_execution
BUY_EXECUTION_BY_REGIME: Dict[str, str] = {
    '明确': 'open',
    '萌芽': 'ma_limit',
    '震荡': 'ma_limit',
}


def default_buy_execution(regime: str) -> str:
    """按档位给出默认买入执行方式；无法判定时回退 open"""
    return BUY_EXECUTION_BY_REGIME.get(str(regime or ''), 'open')


# 选股策略「空值」= 当日空仓（2026-09-16）：
#   配置写法（config/regime_router.yaml）：selector: 空仓
#   语义：该档位当日**仍照常执行选股与评分流程**，只是把选股结果固定为 0 只（等价空仓）；
#         其余流程（卖出/止损/择时/买入方式/持仓管理/股票池维护）完全不变；
#         **不代表强制清仓**（是否持仓由 position 等既有规则决定）。
#   兼容别名：空仓 / none / 无（大小写、首尾空白不敏感）
NO_SELECTION_LABEL = '空仓'
NO_SELECTION_VALUES = ('空仓', 'none', '无')


def is_no_selection(value) -> bool:
    """是否为选股「空值」（显式空仓信号）

    仅识别显式空仓写法（空仓 / none / 无）；None 与空串视为「未配置」，
    交由调用方走原有回退逻辑（不改变历史行为）。
    """
    if value is None:
        return False
    return str(value).strip().lower() in NO_SELECTION_VALUES


# 内置默认路由表（配置文件缺失时使用；依据见设计文档第 3、4 节）
# 仅采用样本量 >= 1000 的策略（Q3 决策），剔除启明星(852)等小样本结论
#
# 2026-09-11 简化分类：6 档（强度 × 方向）→ 3 档（仅强度）
#   明确(>=25) → 沿用原"明确·多头"配置（策略层面最优档）
#   萌芽(20-25) → 沿用原"萌芽·多头"选股/择时，仓位取中性 0.5（原 1.0 偏激进）
#   震荡(<20)  → 沿用原"震荡·空头"配置（弱趋势少参与，保守）
# buy_execution：买入执行方式（open=T日开盘价 | ma_limit=均线委托价）
DEFAULT_RULES: Dict[str, Dict] = {
    '明确': {'selector': '多方炮策略', 'timing': 'uptrend_pullback', 'position': 1.0,
             'buy_execution': 'open'},
    '萌芽': {'selector': '多方炮策略', 'timing': 'macd_bollinger', 'position': 0.5,
             'buy_execution': 'ma_limit'},
    '震荡': {'selector': '2560战法选股策略', 'timing': 'macd_bollinger', 'position': 0.3,
             'buy_execution': 'ma_limit'},
}

DEFAULT_CONFIG: Dict = {
    'enabled': False,            # 默认关闭（Q6 决策）
    'confirm_days': 1,           # 连续确认天数；1 = 即时切换（2026-09-11 由 5 调整）
    'index_code': '000985.CSI',
    'init_immediate': True,      # 首次运行是否立即生效（否则需等 confirm_days）
    'state_file': None,          # None → data/running/regime_state.json
    'rules': None,               # None → DEFAULT_RULES
    'manual_override': {'enabled': False, 'selector': None, 'timing': None, 'position': None},
    # 方向过滤（2026-09-17 严格方案）：空头方向（-DI > +DI）不开新仓
    #   默认关闭；regime_router.yaml 中 enabled: true 时生效
    'direction_filter': {'enabled': False, 'block_open_when_bear': True},
}


@dataclass
class RouteDecision:
    """路由决策结果"""
    regime: str = ''                 # 生效档位（'震荡' | '萌芽' | '明确'）
    selector_strategy: str = ''      # 选股策略（中文名，可直接传给选股流程）
    no_selection: bool = False       # 选股「空值」=空仓：选股/评分照常执行，结果置 0 只
    bear_blocked: bool = False       # 空头方向过滤命中：当日不开新仓（仓位系数置 0）
    timing_strategy: str = ''        # 择时策略（工厂 key，如 'macd_bollinger'）
    position_ratio: float = 1.0      # 仓位系数 0.0 ~ 1.0
    buy_execution: str = ''          # 买入执行方式：'open' | 'ma_limit'
    source: str = 'disabled'         # 'auto' | 'manual' | 'stale' | 'pending' | 'disabled'
    raw_regime: str = ''             # 未平滑的即时 regime（排查用）
    confirm_count: int = 0           # 当前连续确认天数

    def is_active(self) -> bool:
        return self.source in ('auto', 'manual', 'stale')


class RegimeRouter:
    """ADX 自适应路由器"""

    # 强度分档：(下界, 上界, 标签)
    STRENGTH_BANDS = [(0.0, 20.0, '震荡'), (20.0, 25.0, '萌芽'), (25.0, 1e9, '明确')]
    # 档位切换缓冲带（2026-09-11，减少切换）：
    #   升档需 ADX >= 目标下界 + BAND_BUFFER；降档需 ADX < 当前下界 − BAND_BUFFER
    BAND_BUFFER = 1.0

    def __init__(self, config: Optional[Dict] = None, in_memory: bool = False):
        """
        Args:
            config: 配置覆盖（优先级：传入 > regime_router.yaml > 内置默认）
            in_memory: True 时状态仅存于实例内存（**回测必须用 True**，
                       否则会读写实盘的 data/running/regime_state.json 造成污染）
        """
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(self._load_yaml_config() or {})
        cfg.update(config or {})

        self.in_memory = bool(in_memory)
        self._mem_state: Dict = {}
        self.cfg = cfg
        self.enabled = bool(cfg.get('enabled', False))
        self.confirm_days = max(1, int(cfg.get('confirm_days', 5)))
        self.index_code = cfg.get('index_code') or '000985.CSI'
        self.init_immediate = bool(cfg.get('init_immediate', True))
        self.rules: Dict[str, Dict] = cfg.get('rules') or DEFAULT_RULES
        self.manual: Dict = cfg.get('manual_override') or {}
        # 方向过滤配置（空头方向不开新仓；见 _apply_direction_filter）
        self.direction_filter: Dict = cfg.get('direction_filter') or {}
        self.state_path = Path(cfg.get('state_file') or _STATE_PATH)

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    @staticmethod
    def _load_yaml_config() -> Dict:
        """读取 config/regime_router.yaml（缺失/异常时返回空字典）"""
        if not _CONFIG_PATH.exists():
            logger.debug(f'路由配置文件不存在，使用内置默认: {_CONFIG_PATH}')
            return {}
        try:
            import yaml
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            return data.get('regime_router', data) or {}
        except Exception as e:
            logger.warning(f'读取路由配置失败，使用内置默认: {e}')
            return {}

    # ------------------------------------------------------------------
    # 分类（纯函数）
    # ------------------------------------------------------------------
    @classmethod
    def _band_of(cls, adx_v: float) -> str:
        """纯阈值分档（无缓冲带）：震荡 <20 / 萌芽 20~25 / 明确 >=25"""
        for low, high, label in cls.STRENGTH_BANDS:
            if low <= adx_v < high:
                return label
        return ''

    @classmethod
    def _lower_bound(cls, band: str) -> float:
        """档位下界（震荡=0 / 萌芽=20 / 明确=25）；未知档位返回 -1"""
        for low, _high, label in cls.STRENGTH_BANDS:
            if label == band:
                return low
        return -1.0

    @classmethod
    def classify(cls, adx: float, plus_di: float = None, minus_di: float = None,
                 current_band: str = '', buffer: float = None) -> str:
        """ADX → 3 档 regime 之一（震荡 / 萌芽 / 明确）；入参非法时返回空字符串

        Args:
            adx: ADX 值
            plus_di / minus_di: DI（保留入参以兼容调用方，当前**不参与**分类）
            current_band: 当前生效档位；给定时启用**缓冲带（迟滞）**
            buffer: 缓冲宽度，默认 `BAND_BUFFER`（1.0）

        Returns:
            '震荡' | '萌芽' | '明确'；无法判定时返回 ''

        **缓冲带规则（2026-09-11，减少切换）**：
            升档：`ADX >= 目标档下界 + buffer`
            降档：`ADX <  当前档下界 − buffer`
            否则保持 `current_band` —— 档位之间形成 2×buffer 宽的缓冲带。
            例（buffer=1）：震荡→萌芽需 ADX≥21；萌芽→明确需 ADX≥26；
                            明确→萌芽需 ADX<24；萌芽→震荡需 ADX<19。
        """
        try:
            adx_v = float(adx)
        except (TypeError, ValueError):
            return ''
        # 说明：DI（plus_di / minus_di）自 2026-09-11 起不参与分类，
        #      故**不再**对其做数值转换——缺失/非法都不应导致分档失败
        #      （否则 DI 为空时整档丢失 → 决策回退 disabled）

        raw = cls._band_of(adx_v)
        if not raw:
            return ''

        cur = str(current_band or '')
        valid = [b[2] for b in cls.STRENGTH_BANDS]
        if not cur or cur == raw or cur not in valid:
            return raw

        b = cls.BAND_BUFFER if buffer is None else float(buffer)
        cur_low = cls._lower_bound(cur)
        raw_low = cls._lower_bound(raw)

        if raw_low > cur_low:            # 升档：需越过目标下界 + buffer
            return raw if adx_v >= raw_low + b else cur
        if raw_low < cur_low:            # 降档：需跌破当前下界 − buffer
            return raw if adx_v < cur_low - b else cur
        return raw

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------
    def _load_state(self) -> Dict:
        if self.in_memory:
            return dict(self._mem_state)
        try:
            if self.state_path.exists():
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    return json.load(f) or {}
        except Exception as e:
            logger.warning(f'读取 regime 状态失败，按空状态处理: {e}')
        return {}

    def _save_state(self, state: Dict) -> None:
        if self.in_memory:
            self._mem_state = dict(state)
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            state = dict(state)
            state['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f'保存 regime 状态失败（不影响决策）: {e}')

    # ------------------------------------------------------------------
    # ADX 读取（防前视：只用 trade_date 及之前）
    # ------------------------------------------------------------------
    def _read_adx(self, trade_date: str) -> Optional[Dict]:
        """读取 trade_date 当日 ADX；当日无数据时回退到不晚于该日的最近一条"""
        from trading.market_index_adx_dao import MarketIndexADXDAO

        d = str(trade_date).replace('-', '')
        dao = MarketIndexADXDAO()

        rec = dao.query_by_date(d, self.index_code)
        if rec:
            return rec

        # 回退：取 <= d 的最近一条（避免当日 ADX 尚未生成时无法决策）
        try:
            rows = dao.query_range('20200101', d, self.index_code) or []
            if rows:
                return rows[-1]
        except Exception as e:
            logger.debug(f'回退查询 ADX 失败: {e}')
        return None

    def raw_regime(self, trade_date: str, current_band: str = '') -> str:
        """即时档位（未经平滑）；给定 current_band 时按缓冲带判定（迟滞）"""
        rec = self._read_adx(trade_date)
        if not rec:
            return ''
        return self.classify(rec.get('adx'), rec.get('plus_di'), rec.get('minus_di'),
                             current_band=current_band)

    def recent_adx(self, trade_date: str, days: int = 5) -> List[Dict]:
        """读取【截至 trade_date（含当日）】的最近 N 个交易日 ADX（日期升序）

        仅用于日志展示/排查（防前视：查询上界 = trade_date，不含未来数据）。
        查询失败或无数据时返回空列表，绝不抛出。
        """
        try:
            from trading.market_index_adx_dao import MarketIndexADXDAO

            d = str(trade_date).replace('-', '')
            # 往前取 40 个自然日，足以覆盖 N 个交易日（含长假）
            start = (datetime.strptime(d, '%Y%m%d')
                     - timedelta(days=40)).strftime('%Y%m%d')
            rows = MarketIndexADXDAO().query_range(start, d, self.index_code) or []
            return rows[-days:] if len(rows) > days else rows
        except Exception as e:
            logger.debug(f'读取近 {days} 日 ADX 失败({trade_date}): {e}')
            return []

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def decide(self, trade_date: str, persist: bool = True) -> RouteDecision:
        """输出路由决策；任何异常均回退 disabled，绝不抛出

        ⚠️ **防前视（重要）**：入参 `trade_date` 是【信号日】，调用方必须传
        **前一交易日（T-1）**。本方法只读取 `trade_date` 及之前的 ADX
        （`_read_adx` 的区间上界 = trade_date），但若调用方传入 T 日，
        由于 T 日 ADX 需**当日收盘**后才能算出，即构成前视偏差。
        回测引擎已统一传 T-1（见 `RegimeBacktestEngine._decide`）。
        """
        decision = RouteDecision()
        try:
            if not self.enabled and not self.manual.get('enabled'):
                decision.source = 'disabled'
                return decision

            # 当前生效档（缓冲带需要）
            st = self._load_state()
            active = st.get('active_regime') or ''

            # 即时档（纯阈值，仅供日志/排查）与缓冲后档位（实际使用）
            rec = self._read_adx(trade_date)
            raw = ''
            if rec:
                decision.raw_regime = self.classify(rec.get('adx'))
                raw = self.classify(rec.get('adx'), current_band=active)

            if not raw:
                # 无 ADX 数据 → 沿用上一个已生效 regime
                if active and self.rules.get(active):
                    logger.debug(f'ADX 无数据({trade_date})，沿用 {active}')
                    return self._build(active, decision, int(st.get('pending_count') or 0),
                                       source='stale', adx_rec=rec)
                decision.source = 'disabled'
                return decision

            pending = st.get('pending_regime') or ''
            count = int(st.get('pending_count') or 0)

            if raw == pending:
                count += 1
            else:
                pending, count = raw, 1

            switched = False
            if not active and self.init_immediate:
                active = raw          # 首次运行立即生效（避免空等 confirm_days）
            elif count >= self.confirm_days and raw != active:
                logger.info(f'[RegimeRouter] 风格切换 {active} → {raw}（连续 {count} 日确认）')
                active = raw
                count = 0
                switched = True

            if persist:
                self._save_state({
                    'active_regime': active,
                    'pending_regime': pending,
                    'pending_count': count,
                    'last_trade_date': str(trade_date),
                })

            if not active:
                # 尚未确认出生效 regime（等待中，仅 init_immediate=False 时出现）→ 不干预调用方
                decision.source = 'pending'
                decision.confirm_count = count
                logger.debug(f'[RegimeRouter] 等待确认中（{raw} 连续 {count}/{self.confirm_days} 日）')
                return decision

            result = self._build(active, decision, count, source='auto', adx_rec=rec)
            if switched:
                logger.info(f'[RegimeRouter] 生效决策: {result.regime} | '
                            f'选股={result.selector_strategy or (NO_SELECTION_LABEL + "(结果置0)")} '
                            f'择时={result.timing_strategy} '
                            f'仓位={result.position_ratio:.0%}')
            return result

        except Exception as e:
            logger.warning(f'[RegimeRouter] 决策异常，回退 disabled: {e}')
            return RouteDecision(source='disabled')

    def _build(self, regime: str, decision: RouteDecision, count: int,
               source: str = 'auto', adx_rec: Optional[Dict] = None) -> RouteDecision:
        """按 regime 查表 + 应用人工覆盖 + 方向过滤（空头不开新仓）"""
        rule = self.rules.get(regime)
        if not rule:
            logger.debug(f'路由表缺少 regime={regime}，回退 disabled')
            decision.source = 'disabled'
            return decision

        decision.regime = regime
        decision.selector_strategy = rule.get('selector') or ''
        # 选股「空值」= 空仓：归一化为空串（避免被当策略名去选股），并打标记；
        # 调用方（回测引擎）据 no_selection 把当日选股结果置 0
        decision.no_selection = is_no_selection(decision.selector_strategy)
        if decision.no_selection:
            decision.selector_strategy = ''
        decision.timing_strategy = rule.get('timing') or ''
        decision.position_ratio = float(rule.get('position', 1.0))
        # 买入执行方式：缺省按方向推导（多头 open / 空头 ma_limit）
        decision.buy_execution = (rule.get('buy_execution')
                                  or default_buy_execution(regime))
        decision.confirm_count = count
        decision.source = source

        # 人工覆盖优先
        if self.manual.get('enabled'):
            if self.manual.get('selector'):
                decision.selector_strategy = self.manual['selector']
                # 人工覆盖同样支持「空值」（空仓）
                decision.no_selection = is_no_selection(decision.selector_strategy)
                if decision.no_selection:
                    decision.selector_strategy = ''
            if self.manual.get('timing'):
                decision.timing_strategy = self.manual['timing']
            if self.manual.get('position') is not None:
                decision.position_ratio = float(self.manual['position'])
            decision.source = 'manual'
            logger.info(f'[RegimeRouter] 人工覆盖生效: '
                        f'选股={decision.selector_strategy or (NO_SELECTION_LABEL + "(结果置0)")} '
                        f'择时={decision.timing_strategy} 仓位={decision.position_ratio:.0%}')

        # 方向过滤（严格方案）：空头方向（-DI > +DI）→ 当日不开新仓
        self._apply_direction_filter(decision, adx_rec)

        return decision

    def _apply_direction_filter(self, decision: RouteDecision,
                                rec: Optional[Dict]) -> None:
        """方向过滤：空头方向（-DI > +DI）→ 当日不开新仓（2026-09-17 严格方案）

        语义：
          - 判定用**信号日（T-1）及之前**的 +DI/-DI（来自 market_index_adx，防前视）；
          - 生效方式 = 把 `position_ratio` 置 0 → 回测引擎的仓位上限门禁只拦"新建仓"，
            **加仓不受仓位限制、卖出/止盈止损照常**；
          - 严格优先：在人工覆盖（manual_override）之后应用，避免被覆盖绕过；
            需要临时放行时，把配置 `direction_filter.enabled` 置 false 即可。
          - 开关关闭 / 缺少 DI 数据 / 决策未生效（pending、disabled）→ 一律不改动
            （保证不改变历史行为）。
        """
        cfg = self.direction_filter or {}
        if not cfg.get('enabled') or not cfg.get('block_open_when_bear', True):
            return
        if not rec or not decision.is_active():
            return
        try:
            pdi = float(rec.get('plus_di'))
            mdi = float(rec.get('minus_di'))
        except (TypeError, ValueError):
            return
        if mdi > pdi:
            decision.position_ratio = 0.0
            decision.bear_blocked = True
            logger.info(
                f'[RegimeRouter] 方向过滤生效: -DI({mdi:.1f}) > +DI({pdi:.1f}) → '
                f'{decision.regime} 档当日不开新仓（仓位系数置 0；加仓/卖出不受影响）')

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def reset_state(self) -> None:
        """清空平滑状态（回测开始/测试用）"""
        self._save_state({'active_regime': '', 'pending_regime': '', 'pending_count': 0})
