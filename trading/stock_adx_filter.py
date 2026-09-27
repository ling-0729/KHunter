# -*- coding: utf-8 -*-
"""个股 ADX 买入闸门（§5.6 ✓，2026-09-26 用户定稿 ✓）

## 口径（用户定稿 ✓，**首仓 vs 加仓**）

| 过滤项 | 首仓 ✓ | **加仓** ✓ |
|---|:--:|:--:|
| 规则2 当日开盘涨跌幅 `±4%` | ✓（走 `BuyPreFilter` ✓ 原有链）| **✓ 本模块 `add_open_rise_gate`** ★ |
| **ADX 判定**（`band=明确` ∧ `dir=上升` ✓）| **✓ `adx_entry_gate`** | **✓ `adx_entry_gate`** ★ |
| 其余（规则1/3/4 ✗、重复信号 ✗）| 沿用原链 ✓ | **一律不过滤** ✗ |

⇒ 加仓与首仓的**唯一差异** = 规则1（20日低点涨幅 ✓）✗。

## 关键约束 ✗✓

1. **判据是"状态"不是"数值"** ✗✓ —— 复放 `AdxState` 状态机 ✓（`band` 含迟滞 ✓、`dir` 含 `ε` 防抖 ✓）；
   ⚠️ **必须完整回放** ✓（状态**路径依赖** ✓）⇒ 只用最近 N 天近似 ✗ 会得到**不可复现**结果 ✗。
2. **防前视** ✓ —— 一律用 **信号日（T-1）及之前** 的 `adx` ✓（`exclude_last=True` 丢掉 T 日那根 ✓）。
3. **缺数据按归因分流** ✓（§5.2 ✓）：
   · `not_applicable`（**有效根数不足** ✓，< `MIN_APPLICABLE_BARS` = 120 ✓）⇒ **放行** ✓（不误伤次新 ✓）
   · `missing`（**故障** ✗：根数够却 **T-1 无值** ✗）⇒ **拒绝** ✗
   · 预热期（前 120 根 ✓）在**计算侧**已置 NULL ✓ ⇒ 回放时**跳过** ✓（未收敛值不可用 ✗）
4. **开关默认关** ✗（`enable_stock_adx_filter: false` ✓）⇒ M2 落地前**零行为变化** ✓✓。

## 前置依赖 ✗

需要 `stock_kline.adx` 列 ✓（**M2 交付** ✓）。列不存在时 ⇒ 视为 `missing` ✗ ⇒ **拒绝** ✗
（符合"缺数据宁可失败"契约 ✓；因开关默认关 ✗，正常不会触发 ✓）。
"""
import logging
from typing import Dict, List, Optional

import pandas as pd

from trading.buy_filter import BuyPreFilter
from utils.stock_adx_state import (DIRECTION_EPSILON, AdxStateTracker,
                                   allows_entry)

logger = logging.getLogger(__name__)

#: ADX 列名 ✓
ADX_COLUMN = 'adx'

#: 视为"规则不适用"的最小有效 ADX 根数 ✓（与 §5.2 的 120 根同源 ✓）
MIN_APPLICABLE_BARS = 120

#: 默认开关 ✓（生产建议显式写进 `config/backtest_engine_config.yaml` ✓）
#:
#: ⚠️ **两个都是"默认关"** ✗✓（§10 回滚设计 ✓）—— 理由 ✗：
#:   ① `enable_add_open_rise_check` 若默认**开** ✗，会让**加仓行为立刻改变** ✗
#:      （加仓此前**完全不过滤** ✗，见 `_should_apply_buy_filter` ✓）⇒ 基线被无声改写 ✗；
#:   ② A/B 对照**本来就需要**一个"完全等于改前"的基线 ✗ ⇒ 默认关 ✓ 才能构造 G0 ✓。
#:   ⇒ 用户口径"加仓要过滤开盘涨幅" ✓ 由**配置显式打开** ✓（A/B 的 G1/G4 ✓），不由代码默认决定 ✓。
DEFAULT_STOCK_ADX_FILTER = False       #: ADX 闸门（默认**关** ✗ = 现状 ✓）
DEFAULT_ADD_OPEN_RISE = False          #: 加仓「规则2」（默认**关** ✗；A/B 时显式开 ✓）


#: `config/backtest_engine_config.yaml` 进程内缓存 ✓（None = 尚未加载 ✓）
_ENGINE_YAML_CACHE: Optional[Dict] = None


def _load_engine_yaml() -> Dict:
    """读 `config/backtest_engine_config.yaml` ✓（**委派共享加载器** ✓ 单一口径 ✓）

    为什么本模块要读它 ✗✓：**模式开关 `backtest_mode` 与三个单键都在该文件** ✓，
    而调用点只传**请求 `config`** ✗ ⇒ 不读 yaml 就**看不到模式** ✗✓（等于功能没接上 ✗）。
    加载器统一在 `utils/backtest_mode.load_engine_yaml` ✓（与引擎/实盘同一份缓存 ✓✓）。
    """
    from utils.backtest_mode import load_engine_yaml
    return load_engine_yaml()


def _resolve(config: Optional[Dict], key: str, default: bool) -> bool:
    """取值优先级 ✓：**显式单键 > `backtest_mode` 预设 > 硬默认** ✓

    见 `utils/backtest_mode.py` ✓（`legacy` = 原有模式 ✓ / `adx` = ADX+免评分 ✓）。
    """
    from utils.backtest_mode import effective
    return bool(effective(key, config, _load_engine_yaml(), default))


def _resolve_epsilon(config: Optional[Dict]) -> float:
    """方向防抖宽度 `ε` ✓（§9 Q7 ✓）：**按次覆盖 > 标定常量** ✓

    语义 ✓：`|Δadx| ≤ ε` ⇒ 视为**持平** ⇒ `dir` **保持前一日** ✓（防抖 ✓）。
    标定 ✓：`DIRECTION_EPSILON = 0.75` ✓（实测 `|Δadx|` 中位数 ≈0.76 ✓，
    537 只 / 476,368 对差分 ✓；详见 `utils/stock_adx_state.py` 常量注释 ✓）。
    ⚠️ A/B 求更保守时 ✓：传 `config['adx_direction_epsilon']` ✓ 即可（**不改全局** ✓）。
    """
    try:
        v = (config or {}).get('adx_direction_epsilon')
        if v is not None:
            return max(0.0, float(v))
    except Exception:
        pass
    return DIRECTION_EPSILON


def is_adx_filter_enabled(config: Optional[Dict] = None) -> bool:
    """ADX 闸门是否启用 ✓（默认 **关** ✗；`backtest_mode: adx` 时自动**开** ✓）"""
    return _resolve(config, 'enable_stock_adx_filter', DEFAULT_STOCK_ADX_FILTER)


def is_add_open_rise_enabled(config: Optional[Dict] = None) -> bool:
    """加仓「规则2（开盘涨跌幅）」是否启用 ✓

    ⚠️ 默认 **关** ✗（§10 回滚设计 ✓：加仓此前**完全不过滤** ✗，默认开会**无声改写基线** ✗）；
    `backtest_mode: adx` 时预设为 **开** ✓；也可用单键显式覆盖 ✓。
    """
    return _resolve(config, 'enable_add_open_rise_check', DEFAULT_ADD_OPEN_RISE)


def _adx_series(df: pd.DataFrame, exclude_last: bool) -> List[float]:
    """取 **升序** 的 `adx` 序列 ✓（`exclude_last=True` ⇒ 丢掉最后一根 = T 日 ✓，防前视 ✓）

    行序无关 ✓（按 `date` 重排 ✓）；非数值 ⇒ 跳过 ✓（由调用方做归因 ✓）。
    """
    d = df
    if 'date' in d.columns:
        d = d.sort_values('date', ascending=True)
    if exclude_last and len(d) > 0:
        d = d.iloc[:-1]                       # 丢掉 T 日 ✓（只到 T-1 ✓）
    return pd.to_numeric(d[ADX_COLUMN], errors='coerce').tolist()


def _adx_series_from_db(stock_code: str, signal_date: Optional[str],
                        conn=None) -> Optional[List[float]]:
    """从库取该股 `adx` 序列 ✓（**只到信号日之前** ✗✓，防前视 ✓）

    ⚠️ 为什么要走库 ✗✓（**实测踩过的坑** ✗）：**引擎传入的 K 线 df 只取固定列** ✗
    ⇒ 里面**没有** `adx` 列 ✗ ⇒ 若只认 df，闸门会一律判 `missing` ⇒ **笔数 0** ✗✗。
    ⇒ 故：**df 有列就用 df** ✓（快路径 ✓，单测可控 ✓）；**没有就自取库** ✓ ✓。
    """
    from utils.stock_adx import fetch_adx_rows
    rows = fetch_adx_rows(stock_code, conn=conn)
    if not rows:
        return None
    if signal_date:
        sd = str(signal_date)
        rows = [r for r in rows if str(r[0]) < sd]      # `date < 信号日` ✓（= 只到 T-1 ✓）
    return [r[1] for r in rows]


def adx_entry_gate(df: pd.DataFrame, stock_code: str = '',
                   config: Optional[Dict] = None,
                   exclude_last: bool = True,
                   signal_date: Optional[str] = None,
                   use_db: bool = True) -> Dict:
    """**个股 ADX 买入闸门** ✓（首仓 ✓ + 加仓 ✓ **同一判据** ✓）

    Args:
        df: K线 df ✓（含 `adx` 列则直接使用 ✓；否则 `use_db=True` 时**自取库** ✓）
        stock_code: 股票代码 ✓（可带 `.SZ`/`.SH` 后缀 ✓，内部归一化 ✓）
        config: 配置 ✓
        exclude_last: `df` 快路径下是否丢掉最后一根（= T 日）✓
        signal_date: **信号日** ✓（库里取其**之前**的 `adx` ✗✓ 防前视 ✓）
        use_db: 允许自取库 ✓（单测可关 ✓，以保持纯函数可测性 ✓）

    Returns:
        `{'passed': bool, 'reason': str, 'band': str, 'dir': str, 'cooled': bool, 'skipped': bool}`
    """
    if not is_adx_filter_enabled(config):
        return {'passed': True, 'reason': 'ADX 闸门未启用（enable_stock_adx_filter=false ✓）',
                'skipped': True, 'band': '', 'dir': '', 'cooled': False}

    if df is None or getattr(df, 'empty', True):
        return {'passed': True, 'reason': '无K线数据（无法归因 ⇒ 放行 ✓）',
                'skipped': True, 'band': '', 'dir': '', 'cooled': False}

    if ADX_COLUMN in df.columns:
        series = _adx_series(df, exclude_last)                     # 快路径 ✓
    elif use_db:
        series = _adx_series_from_db(stock_code, signal_date)
        if series is None:
            logger.error(f'[StockAdxFilter] {stock_code} 在库中无 `{ADX_COLUMN}` 数据 ✗ '
                         f'（df 也无该列 ✗）⇒ 判为 missing ✗ 并拒绝 ✗')
            return {'passed': False, 'reason': f'无 `{ADX_COLUMN}` 数据（missing ✗）',
                    'skipped': False, 'band': '', 'dir': '', 'cooled': False}
    else:
        # 数据故障 ✗（显式拒绝 ✓，不静默通过 ✗）
        logger.error(f'[StockAdxFilter] {stock_code} 缺少 `{ADX_COLUMN}` 列 ✗ '
                     f'（且 `use_db=False` ✗）⇒ 拒绝 ✗')
        return {'passed': False, 'reason': f'缺少 `{ADX_COLUMN}` 列（missing ✗）',
                'skipped': False, 'band': '', 'dir': '', 'cooled': False}
    # 过滤缺失值 ✓：**必须同时排除 `None`** ✗✓ —— 库里的 NULL 取出来是 `None` ✗，
    #   而 `None == None` 为 **True** ✗ ⇒ 只写 `v == v` 会漏过 `None` ⇒ 后面 `float(None)` 崩 ✗
    #   （实测踩过 ✓：`TypeError: float() argument must be … not 'NoneType'` ✗）
    valid = [v for v in series if v is not None and v == v]

    # ① 归因分流 ✓（§5.2 ✓）：**有效**根数不足 ⇒ 规则**不适用** ⇒ 放行 ✓（不误伤次新 ✓）
    #    注 ✓：预热期（120 根 ✓）在**计算侧**已置 NULL ✓（见 `utils/stock_adx.py` ✓）
    if len(valid) < MIN_APPLICABLE_BARS:
        return {'passed': True,
                'reason': f'有效 ADX 仅 {len(valid)} 根(<{MIN_APPLICABLE_BARS}) ⇒ 规则不适用 ⇒ 放行 ✓',
                'skipped': True, 'band': '', 'dir': '', 'cooled': False}

    # ② **信号日（T-1）缺值** ⇒ 故障 ✗（根数够却没值 ✗）⇒ 拒绝 ✗（不静默通过 ✗）
    _last = series[-1] if series else None
    if _last is None or _last != _last:
        return {'passed': False,
                'reason': '信号日 T-1 的 ADX 缺失（missing ✗）⇒ 拒绝买入 ✗',
                'skipped': False, 'band': '', 'dir': '', 'cooled': False}

    # ③ 完整回放 ✓（状态**路径依赖** ✓，**不可**只取最近 N 天近似 ✗）
    #    · 起点 = 该股**首个有效** ADX ✓（预热期的 NULL 跳过 ✓ —— 未收敛值不可用 ✗）
    tracker = AdxStateTracker(epsilon=_resolve_epsilon(config))    # ε 可按次覆盖 ✓（§9 Q7 ✓）
    for v in valid:
        tracker.update(float(v))
    st = tracker.state

    passed = allows_entry(st)
    reason = '' if passed else (
        f'ADX 状态不放行 ✗（band={st.band or "未预热"} dir={st.dir or "未定"} '
        f'cooled={st.cooled}）—— 要求 band=明确 且 dir=上升 ✓')
    return {'passed': passed, 'reason': reason, 'skipped': False,
            'band': st.band, 'dir': st.dir, 'cooled': st.cooled}


def add_open_rise_gate(df: pd.DataFrame, stock_code: str = '',
                       config: Optional[Dict] = None) -> Dict:
    """**加仓专用：仅「规则2 当日开盘涨跌幅 ±4%」** ✓（§5.6 ✓）

    ⚠️ 实现要点 ✗✓：**不得**改用 `BuyPreFilter.check_filters` ✗ —— 它固定串跑
    `规则1 → 规则2 → 规则4` ✗（无法只跑规则2 ✗）；且规则1 会**误杀已盈利加仓** ✗
    （已大幅盈利的持仓必然远离 20 日低点 ✗）。
    """
    if not is_add_open_rise_enabled(config):
        return {'passed': True, 'reason': '加仓规则2 未启用（enable_add_open_rise_check=false ✓）',
                'skipped': True}
    r = BuyPreFilter._check_open_rise(df, stock_code)      # 只跑规则2 ✓
    # ⚠️ `passed` 是 `numpy.bool_` ✗ ⇒ 必须 `bool()` ✓（`is True` 恒假 ✗）
    ok = bool(r.get('passed'))
    return {'passed': ok, 'reason': r.get('reason', ''), 'skipped': False,
            'value': r.get('value')}


def add_entry_gate(df: pd.DataFrame, stock_code: str = '',
                   config: Optional[Dict] = None,
                   signal_date: Optional[str] = None,
                   use_db: bool = True) -> Dict:
    """**加仓总闸门** ✓ = 规则2 ✓ + ADX ✓（**其他不过滤** ✗，§5.6 ✓）"""
    g2 = add_open_rise_gate(df, stock_code, config)
    if not g2['passed']:
        return {'passed': False, 'reason': f'加仓-规则2-{g2["reason"]}'}
    ga = adx_entry_gate(df, stock_code, config, signal_date=signal_date, use_db=use_db)
    if not ga['passed']:
        return {'passed': False, 'reason': f'加仓-ADX-{ga["reason"]}'}
    return {'passed': True, 'reason': '', 'detail': {'rule2': g2, 'adx': ga}}
