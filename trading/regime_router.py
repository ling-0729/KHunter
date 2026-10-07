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

# 【2026-09-26 §5.8】状态机**复用**个股侧原语 ✓（**单一事实源** ✓）
#   ⇒ 大盘与个股共用同一套 `band`(迟滞 ✓)/`dir`(两日同向 ✓) 递推 ✓，杜绝"两处各写一份"✗
#   ★【2026-09-28 用户口径 ✓】判定式也**统一** ✓：`regime_of` ✓（= `band + dir` ✓）
from utils.stock_adx_state import (HIGH_ADX_GUARD, AdxState, is_mid_reversal,
                                   regime_of)
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
    # ★【2026-09-28 用户口径 ✓】原 `enable_adx_falloff`（降温状态机开关 ✓）**已删除** ✗✓
    #   —— 机制整体移除 ✓（"过于复杂、很难理解"✗）；档位只由 `band`(缓冲 ✓)+`dir` 决定 ✓
    'index_code': '000985.CSI',
    # ★【2026-09-28 用户口径 ✓】**首次启用自动预热** ✓（默认 **关** ✗）
    #   动机 ✗✓：`band`（迟滞 ✓）与 `dir`（两日同向 ＋ 没方向沿用 ✓）都是**路径依赖** ✗
    #   ⇒ **实盘首次**启用时状态文件是空的 ✗ ⇒ 头 1~2 天「方向」为空 ✗（"无方向"✗）
    #   ⇒ 置 `true` 时，`decide()` 首次调用会先 `ensure_warmed()` 用**指数 ADX 全历史**
    #     回放到目标日之前 ✓（**幂等** ✓：状态里已有方向就直接跳过 ✓）。
    #   ⚠️ 默认关 ✗：单测 / 短任务不应触发 DB 回放 ✗（生产实盘请置 true ✓）。
    'auto_warmup': False,
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
    raw_regime: str = ''             # 纯阈值即时档（仅供排查 ✓）
    confirm_count: int = 0           # 当前连续确认天数
    # ★【2026-09-28 用户口径 ✓】原 `downgraded_by`（降温强制 ✓）/ `restored_by`（解除 ✓）
    #   **已删除** ✗✓ —— 降温机制整体移除 ✓（见 `utils.stock_adx_state.py` 顶部说明 ✓）

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
        # ★【2026-09-28 用户口径 ✓】降温机制**已整体移除** ✗✓
        #   （原 `enable_adx_falloff` ✓ + `cooled` ✓ + 峰值 40 的记忆 ✓ + 解除条件 ✗）
        #   现在只有状态机 ✓：`band`（**迟滞** ✓）+ `dir`（**两日同向** ✓）+ 高位守门 ✓
        self._adx_state = AdxState()
        # ★【2026-09-28 用户口径 ✓】方向口径 ✓ —— **默认"连续两日同向"** ✗→✓
        #   （与个股闸门**同一实现** ✓：`utils.stock_adx_state.resolve_dir_mode` ✓）；
        #   如需 A/B 旧口径 ✓：本文件写 `dir_mode: epsilon` ✓。
        from utils.stock_adx_state import resolve_dir_mode as _resolve_dir_mode
        self._dir_mode = _resolve_dir_mode(cfg.get('dir_mode'))
        # ★【2026-09-28 用户口径 ✓】**首次启用预热**开关 ✓（默认关 ✗，见 `DEFAULT_CONFIG` ✓）
        self.auto_warmup = bool(cfg.get('auto_warmup', False))
        self._in_warmup = False              # ★ 预热中标记 ✓（**防 `decide` 递归** ✗✓）
        # ★【2026-09-27 可观测性 ✓】**配置快照**：每次构造都打一行 ✓（A/B 一眼可核对 ✓）
        logger.info(f'[RegimeRouter] 生效配置 ✓ enabled={self.enabled} '
                    f'confirm_days={self.confirm_days} dir口径={self._dir_mode} '
                    f'init_immediate={self.init_immediate} index={self.index_code} '
                    f'in_memory={self.in_memory} 高位守门={HIGH_ADX_GUARD:g}')

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
        # ★【2026-10-05 适配 ✓】起点**不再写死 `20200101`** ✗→✓（与 `_warmup_dates()` 的
        #   `19000101` 口径一致 ✓）—— 原值对"历史更短/更晚发布"的指数 ✗（如科创50 2019-12-31 ✓）
        #   会在回退时**截掉更早的行** ✗ ⇒ 预热/方向判定可能少算 ✗✓。
        try:
            rows = dao.query_range('19000101', d, self.index_code) or []
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
                     f'反转日={"是" if mid_rev else "否"}',
                     f'状态机档={f_state.band or "-"}',
                     f'缓冲=±{self.BAND_BUFFER:g}']
            # ★ 高位守门 ✓（无状态 ✓）：`adx ≥ 40` 且非上升 ⇒ 直接震荡 ✓ 的**可见依据** ✓
            try:
                if (f_state.dir != '上升' and f_state.adx is not None
                        and float(f_state.adx) >= HIGH_ADX_GUARD):
                    bits.append(f'高位守门=触发({float(f_state.adx):g}≥{HIGH_ADX_GUARD:g}'
                                f'且dir≠上升)⇒震荡')
            except (TypeError, ValueError):
                pass
            if f_state.reason:
                bits.append(f'依据={f_state.reason}')
        bits.append(f'生效档={final or "-"}')
        if source:
            bits.append(f'来源={source}')
        if note:
            bits.append(f'备注={note}')
        return '[RegimeRouter] 判定依据 ✓ ' + ' '.join(bits)

    # ------------------------------------------------------------------
    # ★【2026-09-28 用户口径 ✓】**首次启用预热** ✓ —— 消除开头 1~2 天的"无方向"✗
    # ------------------------------------------------------------------
    def _warmup_dates(self, before: str) -> List[str]:
        """取 `≤ before` 的**指数 ADX** 交易日（升序 ✓）—— 与回测预热**同一数据源** ✓"""
        from trading.market_index_adx_dao import MarketIndexADXDAO
        rows = MarketIndexADXDAO().query_range('19000101', before, self.index_code) or []
        return [str(r.get('trade_date')) for r in rows if r.get('trade_date')]

    def ensure_warmed(self, trade_date: Optional[str] = None) -> int:
        """**首次启用时预热一次** ✓：把状态机回放到目标日**之前** ✓ 再开始决策 ✓

        背景 ✗✓（用户 2026-09-28 ✓）：`band`（迟滞 ✓）与 `dir`（两日同向 ＋ 没方向沿用 ✓）
        都是**路径依赖** ✗ ⇒ 实盘**首次**启用时状态文件是空的 ✗ ⇒ 头 1~2 天的「方向」
        为空 ✗（= "无方向"✗，用户要求**避免**✗）⇒ 本方法用**指数 ADX 全历史**补齐 ✓。

        行为 ✓：
          · **幂等** ✓：状态里已有 `adx_dir` ⇒ **直接返回 0** ✓（不重复回放 ✓）；
          · 回放范围 ✓：`数据起点 → trade_date 之前的最后一个交易日` ✓
            （`trade_date=None` ⇒ 按**今天** ✓）；
          · 逐日 `decide(persist=True, verbose=False)` ✓（`persist=True` **必须** ✗：
            否则跨日状态不落盘 ⇒ 回放白做 ✗）；
          · **异常兜底** ✓：任何异常 ⇒ 返回 0 ✓ + 告警 ✓（**绝不阻断**实盘 ✓）。

        ⚠️ 与 `decide` 的关系 ✓：由 `auto_warmup=True` 在 `decide` 首次调用时自动触发 ✓；
        回放期间 `self._in_warmup=True` ✓ ⇒ **不会递归** ✗✓。

        Returns:
            实际回放天数 ✓（0 = 无需预热 / 取不到数据 / 失败 ✓）
        """
        try:
            if not self.enabled and not self.manual.get('enabled'):
                return 0
            st = self._load_state()
            if st.get('adx_dir'):
                # 已有方向 ⇒ 说明此前预热过（或已自然累积 ✓）⇒ 幂等跳过 ✓
                return 0
            goal = str(trade_date or datetime.now().strftime('%Y-%m-%d'))
            prev = goal
            try:
                from utils.trade_date_utils import get_previous_trading_day
                prev = get_previous_trading_day(goal) or goal
            except Exception:
                prev = goal
            dates = self._warmup_dates(prev)
            if not dates:
                logger.warning(f'[RegimeRouter] 首次预热 ✗ 取不到历史指数 ADX'
                               f'（≤ {prev} ✓）⇒ 跳过 ✓（当日方向可能为空 ✗）')
                return 0
            self.reset_state()
            self._in_warmup = True
            try:
                for d in dates:
                    self.decide(d, persist=True, verbose=False)
            finally:
                self._in_warmup = False
            _st = self._load_state()
            logger.info(
                f'[RegimeRouter] **首次启用预热** ✓ 回放 {len(dates)} 日'
                f'（{dates[0]} ~ {dates[-1]}）⇒ 状态已对齐 ✓'
                f'（band={_st.get("adx_band") or "-"} dir={_st.get("adx_dir") or "-"} ✓）'
                f'—— 此后每日决策**不会**再出现"无方向" ✓')
            return len(dates)
        except Exception as e:
            logger.warning(f'[RegimeRouter] 首次预热失败 ✗（按不预热继续 ✓）: {e}')
            self._in_warmup = False
            return 0

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def decide(self, trade_date: str, persist: bool = True,
               verbose: bool = True) -> RouteDecision:
        """输出路由决策；任何异常均回退 disabled，绝不抛出

        ⚠️ **防前视（重要）**：入参 `trade_date` 是【信号日】，调用方必须传
        **前一交易日（T-1）**。本方法只读取 `trade_date` 及之前的 ADX
        （`_read_adx` 的区间上界 = trade_date），但若调用方传入 T 日，
        由于 T 日 ADX 需**当日收盘**后才能算出，即构成前视偏差。
        回测引擎已统一传 T-1（见 `RegimeBacktestEngine._decide`）。

        Args:
            trade_date: 【信号日】✓（调用方须传 **T-1** ✓）
            persist: 是否落状态 ✓（预热/回放可关 ✓）
            verbose: 是否输出「**判定依据**」一行 ✓（默认**开** ✓）——
                这是本次决策**唯一**的 INFO 明细 ✓（用户口径 2026-09-27 ✓：
                「每次决策只保留这一条」✓）。「风格切换/生效决策/解除降温」均已降为
                **DEBUG** ✗（信息未丢 ✓：判定依据行含 `原值档/迟滞后档/dir/降温/反转日/
                状态机档/生效档/来源/依据` ✓）。
                ⚠️ **预热必须传 `False`** ✗✓（`RegimeBacktestEngine._warmup_router` ✓）：
                预热要连续回放 **2020 → 起点**（上千日 ✗）⇒ 逐日打会淹没主回测日志 ✗✗
                （实测踩过 ✓）；关掉后本次决策**零 INFO** ✓，预热只留"进入/解除降温"结论事件 ✓。
                ⚠️ 该开关**只影响日志** ✗ —— **不改**任何判定/状态/持久化 ✓。
        """
        decision = RouteDecision()
        try:
            if not self.enabled and not self.manual.get('enabled'):
                decision.source = 'disabled'
                return decision

            # ★【2026-09-28 用户口径 ✓】**首次启用自动预热** ✓（`auto_warmup: true` 时生效 ✓）
            #   动机 ✗✓：实盘**首次**启用时状态为空 ⇒ 头 1~2 天「方向」为空 ✗（"无方向"✗）
            #   ⇒ 先 `ensure_warmed()` 前溯把状态补齐 ✓（**幂等** ✓；`_in_warmup` 防递归 ✓）
            if self.auto_warmup and not self._in_warmup:
                self.ensure_warmed(trade_date)

            # 当前生效档（缓冲带需要）
            st = self._load_state()
            active = st.get('active_regime') or ''

            # 即时档（**纯阈值** ✓，仅供日志/排查 ✓）
            rec = self._read_adx(trade_date)
            raw = ''
            if rec:
                decision.raw_regime = self.classify(rec.get('adx'))

            # ★★【2026-09-28 用户口径 ✓】**状态机推进 + 统一判定** ✗→✓ ★★
            #   · 状态机**无条件**推进 ✓（**不再有降温开关** ✗）——
            #     大盘档位/方向与个股走**同一条路径** ✓（`utils.stock_adx_state.step` ✓）；
            #   · 判定式**只有** `regime_of` ✓（= `band + dir` ✓）**一处** ✓ ——
            #     个股 `allows_entry` ✓ 与大盘本处 ✓ 是**同一行代码** ✓
            #     ⇒ **大盘「明确」 ⟺ 个股「放行」** ✓✓（用户要求"个股和大盘统一"✓）；
            #   · `band` 的**缓冲带（迟滞）保留** ✓（用户 2026-09-28 明确要求 ✓）；
            #   · ⚠️ **降温机制已整体移除** ✗✓（`cooled` / 峰值 `40` / 强制「震荡」/
            #     "连升两日解除" ✗ —— 用户口径：**过于复杂、很难理解** ✗）。
            f_state: Optional[AdxState] = None
            prev_f_state: Optional[AdxState] = None   # ★ 供「判定依据」日志 ✓
            mid_rev = False                           # ★ 反转日标志 ✓（只算一次 ✓）
            if rec:
                # 复用个股侧原语 ✓（**单一事实源** ✓）：逐日推进 `band`/`dir` ✓
                f_state = AdxState(
                    band=st.get('adx_band') or '',
                    dir=st.get('adx_dir') or '',
                    adx=st.get('adx_state'),
                    prev_adx=st.get('adx_prev'))
                prev_f_state = f_state          # ★ 步进**前** ✓（判据需"步进前的 band"✓）
                f_state = _adx_step(f_state, rec.get('adx'),
                                    dir_mode=self._dir_mode)   # ★ 与个股**同口径** ✓
                self._adx_state = f_state
                # ★ 反转日判据**只算一次** ✗✓（日志与判定**共用** ✓
                #   ⇒ 杜绝"日志说命中、分支没走"这类两处口径漂移 ✗）
                mid_rev = is_mid_reversal(f_state.dir, prev_f_state.band,
                                          rec.get('adx'))
                # ★ **统一判定** ✓：`band + dir`（**个股同一函数** ✓）
                raw = regime_of(f_state)
                # ★【2026-09-28 用户要求 ✓】**避免出现"无方向"** ✗→✓（大盘侧**同口径** ✓）：
                #   保证来源 = **前溯** ✓：回测由 `RegimeBacktestEngine._warmup_router`
                #   **从数据起点逐日回放** ✓；实盘等价物 = **状态文件持久化** ✓
                #   （`adx_band/adx_dir/adx_state/adx_prev` ✓）。
                #   ⇒ 若仍为空 ✗ ⇒ **预热/状态缺失** ✗ ⇒ 告警 ✓
                #     （表现 = 按"非上升"保守处理 ✓ ⇒ 最多判「萌芽/震荡」✓，绝不会误判「明确」✓）。
                if not f_state.dir:
                    logger.warning(
                        f'[RegimeRouter] {trade_date} **方向为空** ✗ ⇒ **前溯/预热不足** ✗'
                        f'（band={f_state.band or "-"} adx={f_state.adx} ✓）'
                        f'⇒ 按"非上升"保守处理 ✓（回测请查 `_warmup_router` ✓）')
                # ★ 状态机**必须持久化** ✗✓ —— 档位/方向都是**路径依赖** ✓
                #   （不存 ⇒ 次日 `prev_adx` 变 `None` ⇒ 迟滞与"两日同向"全失效 ✗，实测踩过 ✓）
                st.update({
                    'adx_band': f_state.band,
                    'adx_dir': f_state.dir,
                    'adx_state': f_state.adx,
                    'adx_prev': f_state.prev_adx,
                })

            if not raw:
                # 无 ADX 数据 → 沿用上一个已生效 regime
                if active and self.rules.get(active):
                    if verbose:
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
                # ⚠️【2026-09-27 用户口径 ✓】只保留「判定依据」一行 ⇒ 本条降为 **DEBUG** ✗
                #   （信息未丢 ✓：判定依据行的 `生效档=` / `迟滞后档=` / `依据=` 已覆盖 ✓）
                logger.debug(f'[RegimeRouter] 风格切换 {active} → {raw}'
                             f'（连续 {count} 日确认）')
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
                # ★ 状态机**必须随状态文件持久化** ✗✓ —— 档位/方向都是**路径依赖** ✓
                #   （不存 ⇒ 次日 `prev_adx` 为 `None` ⇒ 迟滞与"两日同向"全失效 ✗，实测踩过 ✓）
                _payload.update({k: st.get(k) for k in
                                 ('adx_band', 'adx_dir', 'adx_state', 'adx_prev')})
                self._save_state(_payload)

            if not active:
                # 尚未确认出生效 regime（等待中，仅 init_immediate=False 时出现）→ 不干预调用方
                decision.source = 'pending'
                decision.confirm_count = count
                if verbose:
                    logger.info(self._basis_line(
                        trade_date, rec, active, f_state, mid_rev,
                        final=active, source='pending',
                        note=f'等待确认：目标={raw} 连续 {count}/{self.confirm_days} 日'))
                logger.debug(f'[RegimeRouter] 等待确认中（{raw} 连续 {count}/{self.confirm_days} 日）')
                return decision

            if verbose:
                logger.info(self._basis_line(trade_date, rec, active, f_state,
                                             mid_rev, final=active,
                                             source='auto'))
            result = self._build(active, decision, count, source='auto')
            if switched:
                # ⚠️【2026-09-27 用户口径 ✓】只保留「判定依据」一行 ⇒ 本条降为 **DEBUG** ✗
                #   （要"选股/择时/仓位"时把日志级别调到 DEBUG ✓，或见下方可选项 ✓）
                logger.debug(f'[RegimeRouter] 生效决策: {result.regime} | '
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
