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

# 【2026-09-26 §5.8 M6】降温状态机**复用**个股侧原语 ✓（**单一事实源** ✓）
#   ⇒ 大盘与个股共用同一套 `band`/迟滞/`cooled` 递推 ✓，杜绝"两处各写一份"✗
from utils.stock_adx_state import COOLED_PEAK, AdxState, is_mid_reversal
from utils.stock_adx_state import step as _adx_step

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
    # 【2026-09-26 §5.8 M6】降温状态机开关 ✓（用户定稿 ✓）：**默认关** ✗ = 保持现状 ✓
    #   开启后 ✓：峰值 `> 40` 且**连降两日** ⇒ 强制「震荡」✓（进入）；
    #             **连升两日** ⇒ 解除降温 ✓（**交回正常分档** ✓，**不再**强制「明确」✗
    #             —— 2026-09-27 用户修正 ✓；退出门**无** `T-1 > 25` 门槛 ✗ ✓）
    #   两者均**绕开** `confirm_days` 与 `±BAND_BUFFER` ✗✓（覆盖式 ✓，见 §5.8 ✓）
    'enable_adx_falloff': False,
    'index_code': '000985.CSI',
    'init_immediate': True,      # 首次运行是否立即生效（否则需等 confirm_days）
    'state_file': None,          # None → data/running/regime_state.json
    'rules': None,               # None → DEFAULT_RULES
    'manual_override': {'enabled': False, 'selector': None, 'timing': None, 'position': None},
    # 【2026-09-26 **已删除** ✗】方向过滤（'-DI>+DI 当日不开新仓'）
    #   实测结论 ✗✓（用户指正 ✓ + 代码核实 ✓）：它在生产配置下**从未生效** ✗ ——
    #     ① `config/regime_router.yaml → regime_router.enabled: false` ✗（整条链路未启用 ✓）
    #     ② 该过滤自身 `direction_filter.enabled: false` ✗
    #     ③ `bear_blocked` 字段**无任何消费方** ✗（只赋不用 ✓）
    #   ⇒ 按用户决策**整体删除** ✓，删除**行为中性** ✓（原本就不会触发 ✓，
    #     不改变任何历史/回测结果 ✓）。如需恢复，见 git 历史 ✓。
}


@dataclass
class RouteDecision:
    """路由决策结果"""
    regime: str = ''                 # 生效档位（'震荡' | '萌芽' | '明确'）
    selector_strategy: str = ''      # 选股策略（中文名，可直接传给选股流程）
    no_selection: bool = False       # 选股「空值」=空仓：选股/评分照常执行，结果置 0 只
    timing_strategy: str = ''        # 择时策略（工厂 key，如 'macd_bollinger'）
    position_ratio: float = 1.0      # 仓位系数 0.0 ~ 1.0
    buy_execution: str = ''          # 买入执行方式：'open' | 'ma_limit'
    source: str = 'disabled'         # 'auto' | 'manual' | 'stale' | 'pending' | 'disabled'
    raw_regime: str = ''             # 未平滑的即时 regime（排查用）
    confirm_count: int = 0           # 当前连续确认天数
    downgraded_by: str = ''          # 非空 ⇒ 本次档位被**降温强制**为「震荡」（值 'adx_falloff' ✓）
    restored_by: str = ''            # 非空 ⇒ 本次**解除**降温（值 'adx_recover' ✓）；
    #                                   ⚠️ 2026-09-27 起：解除后**交回正常分档** ✓，
    #                                   `regime` **由阈值+迟滞决定** ✗（不再强制「明确」✗）

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
        # 【2026-09-26 删除 ✗】原 `self.direction_filter`（-DI>+DI 不开新仓）已整体移除 ✓
        self.state_path = Path(cfg.get('state_file') or _STATE_PATH)
        # 【2026-09-26 §5.8 M6】降温状态机 ✓（默认关 ✗）
        self.enable_adx_falloff = bool(cfg.get('enable_adx_falloff', False))
        # 降温状态内在状态 ✓（由 `decide()` 逐日推进 ✓，并随既有状态文件持久化 ✓）
        self._adx_falloff_state = AdxState()
        # ★【2026-09-27 可观测性 ✓】**开关快照**：每次构造都打一行 ✓ ——
        #   动机 ✗✓（用户反馈 ✓）：A/B 跑测的日志里**看不出** `enable_adx_falloff` 到底开没开 ✗
        #   （尤其**族 A 普通引擎根本不构造本类** ✗ ⇒ 若把两族混看，会把"没降温"✗误读成"降温没用"✗✗）。
        logger.info(f'[RegimeRouter] 生效配置 ✓ enabled={self.enabled} '
                    f'降温状态机={self.enable_adx_falloff} confirm_days={self.confirm_days} '
                    f'init_immediate={self.init_immediate} index={self.index_code} '
                    f'in_memory={self.in_memory} 峰值门={COOLED_PEAK}')

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
    # ★【2026-09-27 用户要求 ✓】**判定依据**（一行 ✓，可直接 grep ✓）
    # ------------------------------------------------------------------
    def _basis_line(self, trade_date: str, rec: Optional[Dict], active: str,
                    f_state: Optional[AdxState] = None,
                    mid_rev: bool = False, final: str = '',
                    source: str = '', note: str = '') -> str:
        """把"这一天**为什么**是这个档"压成**一行** ✓（字段顺序固定 ⇒ 可 grep/比对 ✓）

        字段 ✓：`ADX` ✓ · `原值档`（纯阈值 ✓）· `迟滞后档`（以当前生效档为基准 ✓）·
        `dir` ✓ · `前日` ✓ · `曾见>40` ✓ · `降温` ✓ · `反转日` ✓ ·
        `状态机档`（**同一原语**的输出 ✓）· `缓冲` ✓ · `生效档` ✓ · `来源` ✓ ·
        `依据`（状态机自带的**人话理由** ✓，见 `AdxState.reason` ✓）

        ⚠️ 纯日志 ✓：**不参与**任何判定 ✗、**不改**状态 ✗（可安全删除 ✓）。
        """
        adx = (rec or {}).get('adx')
        bits = [f'日期={trade_date}',
                f'ADX={adx if adx is not None else "-"}',
                f'原值档={self.classify(adx) or "-"}',
                f'迟滞后档={self.classify(adx, current_band=active) or "-"}']
        if f_state is not None:
            bits += [f'dir={f_state.dir or "-"}',
                     f'前日={f_state.prev_adx if f_state.prev_adx is not None else "-"}',
                     f'曾见>40={"是" if f_state.fell_from_high else "否"}',
                     f'降温={"是" if f_state.cooled else "否"}',
                     f'反转日={"是" if mid_rev else "否"}',
                     f'状态机档={f_state.band or "-"}',
                     f'缓冲=±{self.BAND_BUFFER:g}']
            if f_state.reason:
                bits.append(f'依据={f_state.reason}')
        bits.append(f'生效档={final or "-"}')
        if source:
            bits.append(f'来源={source}')
        if note:
            bits.append(f'备注={note}')
        return '[RegimeRouter] 判定依据 ✓ ' + ' '.join(bits)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def decide(self, trade_date: str, persist: bool = True,
               log_basis: bool = True) -> RouteDecision:
        """输出路由决策；任何异常均回退 disabled，绝不抛出

        ⚠️ **防前视（重要）**：入参 `trade_date` 是【信号日】，调用方必须传
        **前一交易日（T-1）**。本方法只读取 `trade_date` 及之前的 ADX
        （`_read_adx` 的区间上界 = trade_date），但若调用方传入 T 日，
        由于 T 日 ADX 需**当日收盘**后才能算出，即构成前视偏差。
        回测引擎已统一传 T-1（见 `RegimeBacktestEngine._decide`）。

        Args:
            trade_date: 【信号日】✓（调用方须传 **T-1** ✓）
            persist: 是否落状态 ✓（预热/回放可关 ✓）
            log_basis: 是否打「**判定依据**」一行 ✓（默认**开** ✓；
                预热会连续回放上千日 ✗ ⇒ 由 `_warmup_router` 关掉 ✗ 并只留结论性事件 ✓）
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

            # ---------- 【§5.8 M6】降温状态机 ✓（开关关闭时**完全跳过** ✗ = 现状 ✓）----------
            # ⚠️ 降温字段必须**并入下面常规保存** ✗✓ —— 否则"当日未被强制"时字段丢失 ✗，
            #    下一日 `prev_adx` 变 `None` ⇒ 连降/连升判定**永不触发** ✗（实测踩过 ✓）
            falloff_fields: Dict = {}
            # ★【2026-09-27】先**初始化** ✗✓ —— 下面「判定依据」日志在**块外**也要用 ✓
            #   （`f_state` 原来只在 `if enable_adx_falloff and rec:` 内定义 ✗
            #    ⇒ 块外引用会 `UnboundLocalError` ✗ ⇒ 被 `except` 兜底成 `disabled` ✗✗，
            #    实测：开关关闭 / 无 ADX 两条路径直接判错 ✓）
            f_state: Optional[AdxState] = None
            prev_f_state: Optional[AdxState] = None   # ★ 供「判定依据」日志 ✓
            mid_rev = False                           # ★ 反转日标志 ✓（只算一次 ✓）
            if self.enable_adx_falloff and rec:
                # 复用个股侧原语 ✓（单一事实源 ✓）：逐日推进 `band`/`dir`/`cooled` ✓
                prev_cooled = bool(st.get('falloff_cooled'))
                f_state = AdxState(
                    band=st.get('falloff_band') or '',
                    dir=st.get('falloff_dir') or '',
                    cooled=prev_cooled,
                    adx=st.get('falloff_adx'),
                    prev_adx=st.get('falloff_prev_adx'),
                    fell_from_high=bool(st.get('falloff_fell_high')))
                prev_f_state = f_state          # ★ 步进**前** ✓（(b) 判据需"步进前的 band"✓）
                f_state = _adx_step(f_state, rec.get('adx'))
                self._adx_falloff_state = f_state
                # ★ 反转日判据**只算一次** ✗✓（下面的分支与日志**共用** ✓
                #   ⇒ 杜绝"日志说命中、分支没走"这类两处口径漂移 ✗）
                mid_rev = is_mid_reversal(f_state.dir, f_state.fell_from_high,
                                          prev_f_state.band, rec.get('adx'))
                # 持久化到**既有**状态文件 ✓（6 个标量 ✓，不新增存储 ✗）
                falloff_fields = {
                    'falloff_band': f_state.band,
                    'falloff_dir': f_state.dir,
                    'falloff_cooled': bool(f_state.cooled),
                    'falloff_adx': f_state.adx,
                    'falloff_prev_adx': f_state.prev_adx,
                    # 【2026-09-27 新增规则 ✓】"见过 >40" 标志 ✓ —— 必须一起持久化 ✗✓，
                    #   否则跨日丢失 ⇒ "从 40+ 回落到 20~25"这条进入条件**永不触发** ✗
                    'falloff_fell_high': bool(f_state.fell_from_high),
                }
                st.update(falloff_fields)

                forced = ''
                if f_state.cooled:
                    # 进入或**保持**降温 ✓ ⇒ 强制「震荡」✗（**绕开** confirm_days 与防抖 ✓）
                    forced = '震荡'
                    decision.downgraded_by = 'adx_falloff'
                elif prev_cooled:
                    # 【2026-09-27 用户修正 ✗→✓】**解除后不再强制「明确」** ✗
                    #   ⇒ **交回正常分档** ✓：按**原始区间**（阈值 `20/25` ✓）+ **迟滞**
                    #     （`±BAND_BUFFER` ✓）判**真实档位** ✓（"趋势反转后按原始分数区间判定"✓）
                    #   · 为何必须改 ✗✓：解除判据**只**要求**连升两日** ✓，此刻真实档位
                    #     **未必**是「明确」✗ —— 迟滞可能还没过升档门 ✓：
                    #     例 `adx = 25.5 < 25 + 1 = 26` ✗ ⇒ 正常分档应判**「震荡」**✓，
                    #     旧实现却**强制「明确」**✗ ⇒ **越过迟滞** ✗、把"刚解除"错报成明确 ✗✓。
                    #   · 仍**记录**恢复事件 ✓（`restored_by` ✓）⇒ 日志/A/B 归因仍可看到"何时反转" ✓
                    decision.restored_by = 'adx_recover'
                    # ★【2026-09-27 可观测性 ✓】解除降温也**必须**留痕 ✗✓ ——
                    #   否则 A/B 日志里只能看到"进入降温"✗，"何时恢复"无从查证 ✗（归因断链 ✗）
                    logger.info(f'[RegimeRouter] 解除降温 ✓（adx={f_state.adx} '
                                f'前日={f_state.prev_adx} 连升两日 ✓）'
                                f'⇒ 交回正常分档 ✓（band={f_state.band}）')
                    #   · ⚠️ 并**以降温态的「震荡」为基准**重新起算 ✓（见 §5.6 ✓）——
                    #     否则会拿"**降温前的旧档位**"当基准 ✗✓（实测踩到 ✓）：
                    #     旧实现里强制降温**不更新** `active` ✗ ⇒ 解除日 `active` 仍是降温前的
                    #     「明确」✗ ⇒ `classify(25.5, current_band='明确')` 会**保持明确** ✗
                    #     （降档需 `< 24` ✗）⇒ 与"解除后以震荡为基准"的既定语义矛盾 ✗。
                    raw = self.classify(rec.get('adx'),
                                        current_band=(f_state.band or active))
                elif mid_rev:
                    # ★【2026-09-27 用户口径 ✗→✓】**回落中的「反转日」**
                    #   ⇒ **按反转日的 `adx` 原值直接判定 regime** ✓（**不吃 buffer** ✗）
                    #   · 判据 ✓：**复用同一函数** ✓（`utils.stock_adx_state.is_mid_reversal` ✓
                    #     ⇒ 大盘与个股**逐字同口径** ✗✓，**单一事实源** ✓）——它已含两个分支 ✓：
                    #     (a) 曾见 `>40` ✓；(b) **迟滞正托住更高档** ✓（实测：只留 (a) **零命中** ✗）。
                    #   · 为何 ✗✓：迟滞会把"回落前的旧高档"**继续托住** ✗ ⇒
                    #     "数值已跌破 25、`band` 仍是「明确」" + `dir` 转升 ⇒ **误判为明确** ✗。
                    #   · 实现 ✓：`f_state.band` 就是**同一原语**在**同一口径**下算出的档位 ✓
                    #     （`step` 已在反转日自动跳过缓冲带 ✓）⇒ 此处**直接采用** ✓。
                    #   · ⚠️ 优先级 ✓：`cooled`（上面那支）**最高** ✓ —— 反转日**不得**解封降温 ✗
                    #     （解除仍需**连升两日** ✓）。
                    if f_state.band:
                        raw = f_state.band

                if forced:
                    if persist:
                        self._save_state(st)
                    if log_basis:
                        logger.info(self._basis_line(
                            trade_date, rec, active, f_state, mid_rev,
                            final=forced, source='auto(降温强制)'))
                    return self._build(forced, decision, 0, source='auto')

            if not raw:
                # 无 ADX 数据 → 沿用上一个已生效 regime
                if active and self.rules.get(active):
                    if log_basis:
                        logger.info(self._basis_line(
                            trade_date, rec, active, f_state, mid_rev,
                            final=active, source='stale',
                            note='无 ADX 数据 ⇒ 沿用上一档'))
                    return self._build(active, decision, int(st.get('pending_count') or 0),
                                       source='stale')
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
                _payload = {
                    'active_regime': active,
                    'pending_regime': pending,
                    'pending_count': count,
                    'last_trade_date': str(trade_date),
                }
                _payload.update(falloff_fields)   # ★ 保留降温状态 ✓（否则跨日丢失 ✗）
                self._save_state(_payload)

            if not active:
                # 尚未确认出生效 regime（等待中，仅 init_immediate=False 时出现）→ 不干预调用方
                decision.source = 'pending'
                decision.confirm_count = count
                if log_basis:
                    logger.info(self._basis_line(
                        trade_date, rec, active, f_state, mid_rev,
                        final=active, source='pending',
                        note=f'等待确认：目标={raw} 连续 {count}/{self.confirm_days} 日'))
                logger.debug(f'[RegimeRouter] 等待确认中（{raw} 连续 {count}/{self.confirm_days} 日）')
                return decision

            if log_basis:
                logger.info(self._basis_line(trade_date, rec, active, f_state,
                                             mid_rev, final=active,
                                             source='auto'))
            result = self._build(active, decision, count, source='auto')
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
               source: str = 'auto') -> RouteDecision:
        """按 regime 查表 + 应用人工覆盖 ✓

        【2026-09-26 ✗→✓】原第 3 步"方向过滤（-DI>+DI 不开新仓 ✓）"**已整体删除** ✗
        （实证从未生效 ✓，见 `DEFAULT_CONFIG` 注释 ✓）⇒ 入参 `adx_rec` 随之移除 ✓。
        """
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

        return decision

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def reset_state(self) -> None:
        """清空平滑状态（回测开始/测试用）"""
        self._save_state({'active_regime': '', 'pending_regime': '', 'pending_count': 0})
