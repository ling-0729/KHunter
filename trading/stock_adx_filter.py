# -*- coding: utf-8 -*-
"""个股 ADX 买入闸门（§5.6 ✓，2026-09-26 用户定稿 ✓）

## 口径（用户定稿 ✓，**首仓 vs 加仓**）

| 过滤项 | 首仓 ✓ | **加仓** ✓ |
|---|:--:|:--:|
| 规则2 当日开盘涨跌幅 `±4%` | ✓（走 `BuyPreFilter` ✓ 原有链）| **✓ 本模块 `add_open_rise_gate`** ★ |
| **ADX 判定**（默认**区间口径** ✓：`21 < ADX < 30` ✓ ∧ `dir=上升` ✓）| **✓ `adx_entry_gate`** | **✓ `add_entry_gate` → `adx_entry_gate(is_add=True)`** ★ |
| ⚠️ **ADX 上限（30）** ✓ | **生效** ✓（约束**新买入** ✓）| **不校验** ✗✓（★ 2026-09-28 用户口径：**加仓豁免上限** ✓；**下界 21 仍生效** ✓）|
| ★ **收盘 > MA20**（`close(T-1) > MA20` ✓）| **✓ 生效** ★（2026-09-30 用户要求 ✓）| ★ **✓ 也生效** ★（**2026-10-04 用户要求 ✓**：答"需要" ✓）；<br>★ **独立开关** ✓ `adx_add_require_above_ma` ✓ |
| 其余（规则1/3/4 ✗、重复信号 ✗）| 沿用原链 ✓ | **一律不过滤** ✗ |

⇒ 加仓与首仓的**差异** = 规则1（20日低点涨幅 ✓）✗（其余含 MA20 ✓ **两条路各自开关** ✓）。

## ★ 个股放行新增「T-1 收盘 > MA20」✓（2026-09-30 ✓；**2026-10-04 起加仓也判** ✓）

用户原话 ✓："**个股放行过滤增加 t-1(close) > ma20**" ✓
补充 ✓（2026-10-04 用户答"**需要**"✓）：**加仓也判** ✓ ⇒ 两条路**各自一个开关** ✗✓
（`adx_entry_require_above_ma` 首仓 ✓ / `adx_add_require_above_ma` 加仓 ✓）——
⚠️ **分开是刻意的** ✗✓：加仓口径你 2026-09-29 定稿过"只看 `dir=上升`" ✓ ⇒
   两条路必须能**各自 A/B、各自回退** ✓（改加仓**不该**牵动首仓 ✓，反之亦然 ✓）。

| 项 ✓ | 口径 ✓ |
|---|---|
| 生效范围 | ★ **首仓 ✓ 与 加仓 ✓ 都判** ✓（**各自开关** ✗✓，可独立关 ✓）；<br>⚠️ 2026-09-30 ~ 2026-10-03 期间**只有首仓**判 ✗（历史回测口径 ✓） |
| 判据 ✓ | `close(T-1) > MA20(T-1)` ✓ —— `MA20` = **T-1 往前含 T-1 共 20 根收盘的均值** ✓ |
| 防前视 ✓ | 一律 **T-1 及之前** ✓（与 ADX 判定**同一纪律** ✓：df 快路径 `exclude_last` ✓ / 库路径 `date < 信号日` ✓） |
| 数据源 ✓ | ① df 有 `close` 列 ⇒ 用 df ✓（**生产常规路径** ✓ —— 引擎/实盘的 K 线 df 本就带 OHLCV ✓）；<br>② 否则 ⇒ 自取库 ✓（`stock_kline.close` ✓，**与 `adx` 同表同源** ✓ ⇒ 不联网 ✓ 不漂移 ✓） |
| 缺数据 ✓ | **不放行** ✗（收盘不足 20 根 ✓ / 取不到 ✓）—— 与"缺 ADX ⇒ 不放行"**同一保守取向** ✓ |
| 开关 ✓ | `adx_entry_require_above_ma` ✓（默认 **开** ✓；置 `false` ⇒ **旧行为** ✓，A/B 用 ✓） |
| 周期 ✓ | `adx_entry_ma_period` ✓（默认 **20** ✓ = 用户原话 `MA20` ✓；2~250 ✓，非法回落 20 ✓） |

⚠️ **判定顺序** ✗✓：**先 ADX 后 MA** ✓ —— ADX 已拒 ⇒ **不去读收盘** ✗（省一次取数 ✓，
且归因**只有一条**、不含糊 ✓）。

## 关键约束 ✗✓

1. **判据是"状态"不是"数值"** ✗✓ —— 复放 `AdxState` 状态机 ✓（`band` 含迟滞 ✓、
   `dir` = **连续两日同向** ✓（★ 2026-09-28 用户口径 ✓，**不用 `ε`** ✗；旧 `epsilon` 档保留可切 ✓）；
   ⚠️ **必须完整回放** ✓（状态**路径依赖** ✓）⇒ 只用最近 N 天近似 ✗ 会得到**不可复现**结果 ✗。
2. **防前视** ✓ —— 默认一律用 **信号日（T-1）及之前** 的 `adx` ✓（`exclude_last=True` 丢掉 T 日那根 ✓）。
   ★★【2026-10-07 用户口径 ✓】"**个股也应该一致**" ✓ ⇒ 新增开关
     `resolve_use_signal_day(config)` ✓（认 `adx_use_signal_day` ✓ 或既有的
     `index_cap_use_signal_day` ✓，**默认 False** ✓）：
     · **实盘** ✓（开 ✓）：用**信号日当天**的 ADX/收盘 ✓（`exclude_last=False` ✓、
       库路径 `date <= 信号日` ✓）—— 实盘**收盘后决策、T+1 成交** ✓ ⇒ 用当天**不是前视** ✗✓；
     · **回测** ✓（默认关 ✓）：仍取**前一根** ✓（T 日开盘成交时当天 ADX 尚不存在 ✗）⇒ **零回归** ✓。
3. **缺数据一律"不放行"** ✓（**2026-09-28 用户要求** ✗→✓；原为"根数不足 ⇒ 放行"✗）：
   · **无 K 线** ✓ / **有效根数不足**（< `MIN_APPLICABLE_BARS` = 120 ✓，未收敛 ✓）⇒ **不放行** ✗
     （⚠️ **次新股因此不再放行** ✗✓ —— 宁可不买 ✓；回测/实盘结果会变 ✓）
   · `missing`（**故障** ✗：根数够却 **T-1 无值** ✗）⇒ **拒绝** ✗
   · 预热期（前 120 根 ✓）在**计算侧**已置 NULL ✓ ⇒ 回放时**跳过** ✓（未收敛值不可用 ✗）
   ⚠️ **仅"闸门未启用"（`enable_stock_adx_filter=false`）仍放行** ✓ —— 那是用户**主动关闸** ✓
      ⇒ 若它也判"不放行" ✗ ⇒ `legacy` 模式下**全部买入被拦** ✗✗（等于停掉交易 ✗）。
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
                                   allows_entry, entry_allowed,
                                   entry_allowed_by_range,
                                   entry_allowed_by_ranges)

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
#: ★★【2026-09-30 用户要求 ✓】个股放行**新增**「`close(T-1) > MA20`」✓（默认**开** ✓）
#:   用户原话 ✓："**个股放行过滤增加 t-1(close) > ma20**" ✓
#:   ⚠️ 置 `false` ⇒ **旧行为** ✓（只要 ADX 口径过就放行 ✓）—— 供 **A/B 对比** ✓
#:   ⚠️ **只在首仓生效** ✗✓（加仓仍只看 `dir=上升` ✓ —— 用户 2026-09-29 定稿 ✓）
DEFAULT_ENTRY_REQUIRE_ABOVE_MA = True
#: ★ MA 周期 ✓（默认 **20** ✓ = 用户原话 `MA20` ✓）—— 非法（<2 / >250）⇒ 回落 20 ✓
DEFAULT_ENTRY_MA_PERIOD = 20
#: ★★【2026-10-04 用户要求 ✓】**加仓也判**「`close(T-1) > MA20`」✓（默认**开** ✓）
#:   缘由 ✓：上轮我问过"要不要加仓也判" ✓ ⇒ 用户答"**需要**" ✓
#:   ⚠️ **独立开关** ✗✓（不与首仓共用 ✗）：加仓口径你 2026-09-29 定稿过
#:      "**只看 `dir=上升`**" ✓ ⇒ 两条路必须能**各自 A/B / 各自回退** ✓
#:   ⚠️ 置 `false` ⇒ 加仓**回到** 2026-09-29 口径 ✓（只看 `dir=上升` ✓）
DEFAULT_ADD_REQUIRE_ABOVE_MA = True


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


def _resolve_dir_mode(config: Optional[Dict]) -> str:
    """方向口径 ✓（★ 2026-09-28 用户口径 ✓：**默认"连续两日同向"** ✗→✓）

    取值 ✓：`config['adx_dir_mode']` ✓ > 默认 `two_day` ✓ ——
      · `two_day` ✓（默认 ✓）：`a > prev > grand` ⇒ 上升 ✓、`a < prev < grand` ⇒ 下降 ✓、
        其余 ⇒ **未定** ✓（**不看 `ε`** ✗）；
      · `epsilon` ✓（旧口径 ✓，保留 A/B ✓）：`|Δ| > ε` 才改向 ✓，否则保持前一日 ✓。

    解析委托 `utils.stock_adx_state.resolve_dir_mode` ✓（**单一实现** ✓，别名容错 ✓）。
    """
    from utils.stock_adx_state import resolve_dir_mode
    return resolve_dir_mode((config or {}).get('adx_dir_mode'))


def _resolve_entry_bands(config: Optional[Dict]) -> tuple:
    """**入场档位集合** ✓（★ 2026-09-28 用户口径 ✓：可选放宽到「萌芽」✓）

    取值 ✓：`config['adx_entry_bands']` ✓ > 默认 `('明确',)` ✓
      · **默认只放「明确」** ✓ ⇒ **零行为变化** ✓；
      · 放宽 ✅：`['明确', '萌芽']` ✓（放行天数实测 **×1.47** ✓，须以 A/B 回测定论 ✗）。

    ⚠️ **硬条件 `dir = 上升` 不可配置** ✗✓（写在 `entry_allowed` 里 ✓）——
      否则会放进"**萌芽 + 非上升**"（实测 **9291 天** ✗）。
    """
    from utils.backtest_mode import effective
    from utils.stock_adx_state import resolve_entry_bands
    # ★【2026-09-28 同步 ✓】改走**统一入口** `effective()` ✓ —— 与三个既有开关**同一优先级链** ✓
    #   （请求 config ✓ > yaml 顶层 ✓ > yaml `backtest:` 节 ✓ > `backtest_mode` 预设 ✓ > 默认 ✓）
    #   ⚠️ 旧写法直读 `config` ✗ ⇒ **实盘侧读不到 yaml `backtest:` 节里的键** ✗✓（同步审查发现 ✓）。
    return resolve_entry_bands(effective('adx_entry_bands', config,
                                         _load_engine_yaml(), default=None))


def _resolve_entry_mode(config: Optional[Dict]) -> str:
    """**个股入场口径** ✓（★ 2026-09-28 用户口径 ✓）

    取值 ✓：`config['adx_entry_mode']` ✓
      · `'range'` ✓（**默认** ✓）：`low < ADX(T-1) < high`（默认 `21/30` ✓）∧ `dir=上升` ✓
        —— **无缓冲** ✗、**不看 `band`** ✗；
      · `'band'` ✓（旧口径 ✓）：`dir=上升` ∧ `band ∈ adx_entry_bands` ✓（默认只放「明确」✓）。

    别名 ✓：`区间/interval/数值/阈值` ⇒ range ✓；`档位/bands` ⇒ band ✓；
    未知值 ⇒ **回落 `range`** ✓ + 告警 ✓（**不**静默变成别的口径 ✗）。
    """
    from utils.backtest_mode import effective
    raw = str(effective('adx_entry_mode', config, _load_engine_yaml(),
                        default='range') or '').strip().lower()
    if not raw:
        return 'range'                       # ★ 默认 = 用户现行要求 ✓
    if raw in ('range', 'interval', '区间', '数值', '阈值'):
        return 'range'
    if raw in ('band', 'bands', '档位', '档位集合'):
        return 'band'
    logger.warning(f'未知入场口径 {raw!r} ⇒ 回落 `range` ✓（可选：range / band ✓）')
    return 'range'


def _resolve_entry_ranges(config: Optional[Dict]) -> tuple:
    """**入场区间（可多段 ✓）** ⇒ `((lo, hi), ...)` ✓（默认 `((21, 30),)` ✓ = 与旧行为一致 ✓）

    ★【2026-09-29 用户要求 ✓】用户口径："扩大个股放行买入的区间：`15<ADX<18 ∪ 23<ADX<42`"
      ⇒ 配置写 `adx_entry_range: [15, 18, 23, 42]` ✓（**扁平 4 个 = 两两成段** ✓；
      **多段 = 并集** ✓，段与段之间为**拒** ✗）；语法详见
      `utils/stock_adx_state.resolve_entry_ranges` ✓（旧写法 `[21, 30]` **完全兼容** ✓）。
    """
    from utils.backtest_mode import effective
    from utils.stock_adx_state import resolve_entry_ranges
    return resolve_entry_ranges(effective('adx_entry_range', config,
                                         _load_engine_yaml(), default=None))


def _resolve_entry_range(config: Optional[Dict]) -> tuple:
    """**入场区间（单段兼容版 ✓）** —— 取多段的**第一段** ✓（旧调用方/测试用 ✓）"""
    return _resolve_entry_ranges(config)[0]


def is_entry_above_ma_required(config: Optional[Dict] = None) -> bool:
    """★★【2026-09-30 用户要求 ✓】首仓是否要求「**`close(T-1) > MA`**」✗→✓ ★★

    用户原话 ✓："个股放行过滤增加 **t-1(close) > ma20**" ✓
    ⇒ 默认 **开** ✓（用户要的就是这个口径 ✓）；置 `false` ⇒ **旧行为** ✓（A/B 用 ✓）。
    ⚠️ **只约束首仓** ✗✓（加仓不看它 ✓ —— 用户 2026-09-29 定稿："加仓只看 `dir=上升`" ✓）。
    """
    return _resolve(config, 'adx_entry_require_above_ma',
                    DEFAULT_ENTRY_REQUIRE_ABOVE_MA)


def is_add_above_ma_required(config: Optional[Dict] = None) -> bool:
    """★★【2026-10-04 用户要求 ✓】**加仓**是否也要求「**`close(T-1) > MA`**」✗→✓ ★★

    缘由 ✓：上轮我问"要不要**加仓也判**" ✓ ⇒ 用户答"**需要**" ✓。
    ⇒ 默认 **开** ✓；置 `false` ⇒ **加仓回到 2026-09-29 口径** ✓（只看 `dir=上升` ✓）。

    ⚠️ **独立于首仓** ✗✓（`adx_entry_require_above_ma` ✓）：两条路分开 ⇒
      **各自 A/B、各自回退** ✓（这正是你 9-29 定稿"加仓只看 dir"能保住的唯一方式 ✓）。
    """
    return _resolve(config, 'adx_add_require_above_ma',
                    DEFAULT_ADD_REQUIRE_ABOVE_MA)


def resolve_use_signal_day(config: Optional[Dict] = None) -> bool:
    """★★【2026-10-07 用户口径 ✓】**个股闸门是否用「信号日当天」的 ADX/收盘** ✗→✓ ★★

    用户原话 ✓："**个股也应该一致**" ✓（= 与**大盘档位**同一口径 ✓）

    ⇒ 语义 ✓（与 `index_adx_filter.resolve_cap_use_signal_day` **逐字一致** ✗✓，
      两边必须能**同时开、同时关** ⇒ 否则又回到"大盘用 T ✓、个股用 T-1"的混用 ✗）：
      · `False` ✓（**默认** ✓）：取**信号日的前一根** —— **回测**口径 ✓
        （回测信号日 = 执行日 T 的前一根 ✓；T 日开盘成交时 T 日 ADX 还不存在 ✗ ⇒ 必须如此 ✓）；
      · `True` ✓（**实盘** ✓）：取**信号日当天** ✓ —— 实盘在信号日收盘后决策 ✓、
        **T+1 成交** ✓（用户定稿时序 ✓：\"T 日出信号，T+1 实盘时按即时价格成交\"✓）
        ⇒ 用当天数据**不是未来函数** ✗✓。

    ⚠️ 键名优先级 ✗✓（两个都认 ✓，便于"一处开关、两处口径"✓）：
      ① `adx_use_signal_day` ✓（**通用名** ✓，推荐新配置用它 ✓）
      ② `index_cap_use_signal_day` ✓（**既有键** ✓ —— 实盘运行器注的就是它 ✓
         ⇒ 个股闸门**无需额外接线**就跟着一致 ✓✓）
    """
    from utils.backtest_mode import effective
    # ★★★★【2026-10-07 审计修复 ✓】**改为委托"唯一解析器"** ✗→✓ ★★★★
    #   缘由 ✗✓：本函数原先自己遍历两个键（`adx_use_signal_day` **在前** ✗）⇒
    #     与大盘侧（只认 `index_cap_use_signal_day` ✗）**键集合与顺序都不同** ✗
    #     ⇒ 一旦两键写得不一致 ⇒ **大盘/个股时点分叉** ✗✗（用户本次明确不许 ✓）。
    #   ⇒ 现在**直接复用** `index_adx_filter.resolve_cap_use_signal_day` ✓
    #     ⇒ 两处**同一实现、同一顺序** ✓ ⇒ 结构上不可能分叉 ✓✓。
    try:
        from trading.index_adx_filter import (
            resolve_cap_use_signal_day as _shared)
        return bool(_shared(config))
    except Exception:                 # ⚠️ 极端情况下（导入失败 ✓）**保守取前一根** ✓
        #   为什么保守 ✗✓：`True` 会改变实盘成交口径 ✓ ⇒ 宁可"回退到更严的口径" ✓，
        #   也绝不因一次导入异常而**悄悄**换成"用当天" ✗。
        logger.debug('复用共享时点解析器失败 ⇒ 回退"前一根"口径 ✓', exc_info=True)
        try:
            raw = effective('index_cap_use_signal_day', config,
                            _load_engine_yaml(), default=None)
        except Exception:
            raw = None
        if raw is None or raw == '':
            return False
        return (bool(raw) if not isinstance(raw, str)
                else raw.strip().lower() in ('1', 'true', 'yes', 'on', '是', '开'))


def resolve_entry_ma_period(config: Optional[Dict] = None) -> int:
    """MA 周期 ✓（用户原话 `MA20` ✓ ⇒ 默认 **20** ✓；可配 ✓）

    ⚠️ 非法（非数值 / <2 / >250）⇒ **回落 20** ✓ + 告警 ✓（**不抛** ✗、**不静默按 1** ✗
      —— 那会变成"收盘 > 前一日收盘"✗，是**另一种口径** ✗✓）。
    """
    from utils.backtest_mode import effective
    raw = effective('adx_entry_ma_period', config, _load_engine_yaml(), default=None)
    if raw is None or raw == '':
        return int(DEFAULT_ENTRY_MA_PERIOD)
    try:
        p = int(float(raw))
    except (TypeError, ValueError):
        logger.warning(f'adx_entry_ma_period={raw!r} 非法 ⇒ 回落默认 '
                       f'{DEFAULT_ENTRY_MA_PERIOD} ✓')
        return int(DEFAULT_ENTRY_MA_PERIOD)
    if not (2 <= p <= 250):
        logger.warning(f'adx_entry_ma_period={raw!r} 超出范围 [2, 250] ⇒ 回落默认 '
                       f'{DEFAULT_ENTRY_MA_PERIOD} ✓')
        return int(DEFAULT_ENTRY_MA_PERIOD)
    return p


def is_adx_filter_enabled(config: Optional[Dict] = None) -> bool:
    """ADX 闸门是否启用 ✓（默认 **关** ✗；`backtest_mode: adx` 时自动**开** ✓）"""
    return _resolve(config, 'enable_stock_adx_filter', DEFAULT_STOCK_ADX_FILTER)


def is_add_open_rise_enabled(config: Optional[Dict] = None) -> bool:
    """加仓「规则2（开盘涨跌幅）」是否启用 ✓

    ⚠️ 默认 **关** ✗（§10 回滚设计 ✓：加仓此前**完全不过滤** ✗，默认开会**无声改写基线** ✗）；
    `backtest_mode: adx` 时预设为 **开** ✓；也可用单键显式覆盖 ✓。
    """
    return _resolve(config, 'enable_add_open_rise_check', DEFAULT_ADD_OPEN_RISE)


def describe_adx_params(config: Optional[Dict] = None) -> str:
    """**ADX 一族参数的一行摘要** ✓ —— 回测与实盘**同一实现** ✓（防口径漂移 ✗）

    ★【2026-09-28 用户要求 ✓】"**回测和实盘时打印参数日志**" ✗→✓：
      ADX 这族参数最多（闸门 ✓ / 入场口径 ✓ / **上下限** ✓ / 档位集合 ✓ /
      方向口径 ✓ / `ε` ✓ / 缓冲带 ✓ / 高位守门 ✓），**分散在 4 个解析器**里 ✗
      ⇒ 不给统一摘要就**只能靠猜** ✗（用户已实测踩过 ✓：跑 A/B 时看不出真正生效值 ✗）。
      实测 2026-09-28：用户问"**上限/下限在哪儿配置**"✓ —— 正说明**日志里看不到** ✗。

    ⚠️ 全部走**本模块自己的解析器** ✓ ⇒ 它们共用 `utils.backtest_mode.effective` 的
      **同一条优先级链** ✓（请求 config > yaml 顶层 > yaml `backtest:` 节 >
      `backtest_mode` 预设 > 默认 ✓）⇒ 打出来的就是**真生效值** ✓（不是"有没有设置"✗）。

    ⚠️ 只读 ✓、**不发请求** ✓、**任何异常都不抛** ✗（纯日志 ✓ ⇒ 绝不阻断回测/实盘 ✓）。

    Returns:
        一行 `key=value（来源 ✓）| …` ✓；取不到时尽力而为 ✓（缺项省略但不报错 ✓）。
    """
    from utils.backtest_mode import is_explicit, preset as _preset
    from utils.stock_adx_state import BAND_BUFFER, HIGH_ADX_GUARD

    _pres = _preset(config) or {}

    def _src(key: str) -> str:
        """**来源**标注 ✓ —— 与 `log_backtest_params` 的三档口径**一致** ✓：
        `配置` ✓ > `模式预设` ✓ > `内置默认` ✓（**实测** ✓：不写清楚
        用户就分不清"我改了没生效"✗ 还是"本来就是这个值"✓）。
        """
        if is_explicit(key, config):
            return '配置'
        return '模式预设' if key in _pres else '内置默认'

    parts: List[str] = []
    try:
        parts.append(f'enable_stock_adx_filter={is_adx_filter_enabled(config)}'
                     f'（{_src("enable_stock_adx_filter")} ✓）')
    except Exception:
        pass
    _mode = 'range'
    try:
        _mode = _resolve_entry_mode(config)
        parts.append(f'adx_entry_mode={_mode}（{_src("adx_entry_mode")} ✓）')
    except Exception:
        pass

    def _inactive(key: str, why: str) -> None:
        """★【2026-09-29 用户要求 ✓】**不生效的参数默认不打** ✗→✓

        用户口径 ✓："**有些参数已经不使用，请去除**" ✓ —— 指那种"当前口径下
        **根本不参与判定**"的项 ✗（如 `range` 口径下的 `adx_entry_bands` ✗、
        `two_day` 口径下的 `adx_direction_epsilon` ✗）⇒ 每行都在读却**毫无用处** ✗。

        ⚠️ 但**显式配置过**的项仍给一行**短提示** ✗✓ —— 否则用户会以为
        "我配了、日志里没有 ⇒ 配置丢了吗"✗✓（比噪声更危险 ✗）。
        """
        if not is_explicit(key, config):
            return
        try:
            if key == 'adx_entry_bands':
                _v = list(_resolve_entry_bands(config))
            elif key == 'adx_entry_range':
                # ★【2026-09-29】多段并集 ✓（旧写法 = 一段 ✓）⇒ 提示里也如实展示 ✓
                _v = ' ∪ '.join(f'{lo:g}<ADX<{hi:g}'
                                for lo, hi in _resolve_entry_ranges(config))
            else:
                _v = f'{_resolve_epsilon(config):g}'
            parts.append(f'⚠ {key}={_v}（**已配置但当前不生效** ✗：{why}）')
        except Exception:
            pass

    # ---- 入场口径：**只打当前口径真正生效的那组** ✓ ----
    if _mode == 'range':
        try:
            _rs = _resolve_entry_ranges(config)
            _txt = ' ∪ '.join(f'{lo:g}<ADX<{hi:g}' for lo, hi in _rs)
            parts.append(f'adx_entry_range={_txt}（{_src("adx_entry_range")} ✓；'
                         f'**开区间** ✗ ⇒ 端点本身不含 ✓；'
                         + ('多段 = **并集** ✓（段与段之间为**拒** ✗）；'
                            if len(_rs) > 1 else '')
                         + '**首仓**校验整段 ✓；**加仓只看 `dir=上升`** ✓'
                           '（**不校验 ADX** ✗ —— 用户 2026-09-29 口径 ✓））')
        except Exception:
            pass
        _inactive('adx_entry_bands', '`adx_entry_mode=band` 口径才用')
    else:
        try:
            _bands = list(_resolve_entry_bands(config))
            parts.append(f'adx_entry_bands={_bands}（{_src("adx_entry_bands")} ✓；'
                         f'`range` 上下限**本口径不使用** ✗）')
        except Exception:
            pass
        _inactive('adx_entry_range', '`adx_entry_mode=range` 口径才用')

    # ---- ★【2026-09-30 用户要求 ✓】首仓 MA 闸门：**自证**开关 / 周期 / 作用域 ✓ ----
    #   为什么必须打 ✗✓：这是**新增的硬条件** ✓（`close(T-1) > MA20`）——
    #   不打出来则"某天没买入"✗ 完全看不出是它拦的 ✗✓（用户已多次要求"真生效值要可见" ✓）。
    #   ⚠️ 只打**生效时**的项 ✓（关掉时只留一行"已关 ⇒ 旧行为" ✓，不刷周期噪声 ✗）。
    try:
        _p = resolve_entry_ma_period(config)
        _on_e = is_entry_above_ma_required(config)
        _on_a = is_add_above_ma_required(config)      # ★ 2026-10-04 ✓ 加仓独立开关 ✓
        parts.append(
            f'adx_entry_require_above_ma={_on_e}'
            f'（{_src("adx_entry_require_above_ma")} ✓；'
            + (f'**首仓**须 **close(T-1) > MA{_p}** ✓' if _on_e
               else '**已关 ⇒ 首仓旧行为** ✓（ADX 口径过即放行 ✓）')
            + '）')
        parts.append(
            f'adx_add_require_above_ma={_on_a}'
            f'（{_src("adx_add_require_above_ma")} ✓；'
            + (f'**加仓也须 close(T-1) > MA{_p}** ✓（2026-10-04 用户要求 ✓）' if _on_a
               else '**已关 ⇒ 加仓只看 `dir=上升`** ✓（2026-09-29 原口径 ✓）')
            + '）')
        if _on_e or _on_a:
            parts.append(f'adx_entry_ma_period={_p}'
                         f'（{_src("adx_entry_ma_period")} ✓）')
    except Exception:
        pass

    # ---- 方向口径：**ε 只在 epsilon 档生效** ✗ ⇒ 其余档不打 ✓ ----
    _dm = ''
    try:
        _dm = _resolve_dir_mode(config)
        parts.append(f'adx_dir_mode={_dm}（{_src("adx_dir_mode")} ✓）')
    except Exception:
        pass
    if _dm == 'epsilon':
        try:
            parts.append(f'adx_direction_epsilon={_resolve_epsilon(config):g}'
                         f'（本档**生效** ✓）')
        except Exception:
            pass
    else:
        _inactive('adx_direction_epsilon', '`adx_dir_mode=epsilon` 档才生效')

    # ---- `band` 一族（缓冲带 / 高位守门）：**只在 band 口径下出场** ✓ ----
    #   ⚠️ 实测口径 ✓：两者都只作用于 `band` 分档（`apply_hysteresis` ✓）与
    #     **大盘路由**（`regime_of` ✓）✗ ⇒ 在个股 `range` 口径下**不参与判定** ✗✓
    #     ⇒ 默认不打 ✗（用户要求 ✓）；切到 `band` 口径时自动出现在此处 ✓。
    if _mode == 'band':
        _bb = float(BAND_BUFFER)
        _hg = float(HIGH_ADX_GUARD)
        parts.append(f'band缓冲带=±{_bb:g}（**保留** ✓，正常换挡有迟滞 ✓）')
        parts.append(f'高位守门={_hg:g}（adx≥{_hg:g} 且 dir≠上升 ⇒ **震荡** ✓，'
                     f'**无状态** ✓）')
    # ★【2026-09-28 用户口径 ✓】原「大盘 ADX 硬闸门」**已取消** ✗ ⇒ 本摘要**不再**附它 ✓
    #   （开新仓的大盘判据现为**仓位上限** ✓ —— 由 `index_adx_filter` 的
    #    `describe_index_position_cap_params` ✓ **单独一行**打印 ✓，见回测/实盘入口 ✓）。
    return ' | '.join(parts)


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
                        conn=None,
                        include_signal_day: bool = False) -> Optional[List[float]]:
    """从库取该股 `adx` 序列 ✓（默认**只到信号日之前** ✗✓，防前视 ✓）

    ★【2026-10-07 ✓】`include_signal_day=True` ⇒ **含信号日当天那根** ✓（**仅实盘** ✓，
      见 `resolve_use_signal_day` ✓）：截断由 `date < 信号日` 改为 `date <= 信号日` ✓。

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
        # ★【2026-10-07 ✓】默认 `date < 信号日` ✓（= 只到 T-1 ✓）；
        #   实盘口径 ⇒ `<= 信号日` ✓（含当天 ✓ —— 成交在次日 ⇒ 不是前视 ✗✓）
        rows = [r for r in rows
                if (str(r[0]) <= sd if include_signal_day else str(r[0]) < sd)]
    return [r[1] for r in rows]


def _close_series(df: pd.DataFrame, exclude_last: bool) -> List[float]:
    """取 **升序** 的 `close` 序列 ✓（`exclude_last=True` ⇒ 丢掉 T 日那根 ✓，防前视 ✓）

    口径与 `_adx_series` **逐字一致** ✗✓（行序无关 → 按 `date` 升序 ✓；非数值 ⇒ 跳过 ✓）
    —— 两条序列必须**同一天对齐** ✓，否则 `close(T-1)` 对不上 `ADX(T-1)` ✗✓。
    """
    d = df
    if 'close' not in getattr(d, 'columns', []):
        return []
    if 'date' in d.columns:
        d = d.sort_values('date', ascending=True)
    if exclude_last and len(d) > 0:
        d = d.iloc[:-1]                       # 丢掉 T 日 ✓（只到 T-1 ✓）
    return pd.to_numeric(d['close'], errors='coerce').tolist()


def _close_series_from_db(stock_code: str, signal_date: Optional[str],
                          conn=None,
                          include_signal_day: bool = False) -> Optional[List[float]]:
    """从库取该股 `close` 序列 ✓（默认**只到信号日之前** ✗✓，防前视 ✓）

    与 `_adx_series_from_db` **同一范式** ✓（同表 ✓ 同截断规则 ✓）；`None` = 一只都没取到 ✗。
    ★【2026-10-07 ✓】`include_signal_day=True` ⇒ **含信号日当天** ✓（`date <= 信号日` ✓）
      —— 与 ADX 序列**必须同一天对齐** ✗✓，否则 `close(信号日)` 对不上 `ADX(信号日)` ✗。
    """
    from utils.stock_adx import fetch_close_rows
    rows = fetch_close_rows(stock_code, conn=conn)
    if not rows:
        return None
    if signal_date:
        sd = str(signal_date)
        # ★【2026-10-07 ✓】默认 `date < 信号日` ✓；实盘口径 ⇒ `<= 信号日` ✓（含当天 ✓）
        rows = [r for r in rows
                if (str(r[0]) <= sd if include_signal_day else str(r[0]) < sd)]
    return [r[1] for r in rows]


def _ma_gate(df: pd.DataFrame, stock_code: str, config: Optional[Dict],
             exclude_last: bool, signal_date: Optional[str],
             use_db: bool, include_signal_day: bool = False) -> Dict:
    """★★【2026-09-30 用户要求 ✓】**`收盘 > MA`** 判定 ✓（**首仓 ✓ 与 加仓 ✓ 各自开关 ✓**）★★

    ★【2026-10-07 用户口径 ✓】"**个股也应该一致**" ✓：`include_signal_day=True` ⇒
      用**信号日当天**的收盘与 MA ✓（末端 = 信号日 ✓）；默认仍取**前一根** ✓。

    Returns:
        `{'passed','close','ma','ma_period','reason'}` ✓
        ⚠️ `passed=False` 时 `reason` **必须带两个数** ✗✓（"为什么今天不放行"要能直接看到 ✓）。

    ⚠️ 缺数据一律 **不放行** ✗ — 与"缺 ADX ⇒ 不放行"**同一保守取向** ✓：
      · df 无 `close` 列 且 库取不到 ⇒ 不放行 ✓；
      · 有效收盘不足 `period` 根 ⇒ 不放行 ✓（**不足以成均线** ✗）；
      · 收盘非数值 ⇒ 不放行 ✓。
    """
    p = resolve_entry_ma_period(config)
    out = {'passed': False, 'close': None, 'ma': None, 'ma_period': p, 'reason': ''}
    # ★【2026-10-07 ✓】归因文案随口径走 ✓（否则实盘日志里写 `close(T-1)` 会**误导** ✗✓）
    _lbl = 'close(信号日)' if include_signal_day else 'close(T-1)'
    try:
        series = _close_series(df, exclude_last) if df is not None else []
        if not series and use_db:
            series = _close_series_from_db(
                stock_code, signal_date,
                include_signal_day=include_signal_day) or []
    except Exception as e:                        # 取数异常 ⇒ 保守不放行 ✓（不抛 ✗）
        out['reason'] = f'收盘价读取失败 ✗({e}) ⇒ **不放行** ✗'
        return out
    valid = [v for v in series if v is not None and v == v]
    if len(valid) < p:
        out['reason'] = (f'有效收盘仅 {len(valid)} 根（< MA{p} ✗）⇒ 不足以成均线 ⇒ '
                         f'**不放行** ✗')
        return out
    c = float(valid[-1])                          # ★ 序列末值（= 前一根 或 信号日当根 ✓）
    ma = sum(float(x) for x in valid[-p:]) / float(p)   # ★ 含末值在内 p 根均值 ✓
    out.update(close=c, ma=ma)
    if c > ma:
        out['passed'] = True
        out['reason'] = f'{_lbl}={c:.2f} > MA{p}={ma:.2f} ✓'
    else:
        out['reason'] = (f'{_lbl}={c:.2f} ≤ MA{p}={ma:.2f} ✗（**未站上均线** ✗）'
                         f' ⇒ **不放行** ✗')
    return out


def format_gate_result(gate: Dict) -> str:
    """把闸门结果压成**一行** ✓（**通过 / 未通过 / 跳过** 都打 ✓）

    ★【2026-09-27 用户要求 ✓】：此前**只有"未通过"有日志** ✗ ⇒
    买入成功时**看不到个股 ADX 信息** ✗（实测反馈 ✓）⇒ 三处调用点在**通过时也打** ✓。

    输出 ✓：`ADX 闸门 通过/未通过/跳过 + ADX(T-1 或 信号日)=… + band=… + dir=… + （原因）`

    ★ `ADX(T-1)` ✓（2026-09-28 用户要求 ✓）：**判定所用的那一根** ✓ ——
      即 `exclude_last` / 库查询 `date < 信号日` 之后序列的**末值** ✗✓；
      取不到 ⇒ 打 `-` ✓（不误导 ✗）。

    ★★【2026-10-07 ✓】文案**随口径走** ✗→✓：实盘开了"信号日当天"口径 ⇒
      打成 `ADX(信号日)=…` / `close(信号日)=…` ✓（否则实盘日志写 `T-1` 会**误导** ✗✓）。
    """
    if gate.get('skipped'):
        head = '跳过·放行 ✓'
    elif gate.get('passed'):
        head = '通过 ✓'
    else:
        head = '未通过 ✗'
    try:
        _a_txt = f"{float(gate.get('adx')):.2f}"
    except (TypeError, ValueError):
        _a_txt = '-'
    # ★【2026-09-30 用户要求 ✓】MA 闸门有值时**一并打出** ✗→✓（否则"为什么没放行"又要靠猜 ✗）
    _ma_txt = ''
    # ★【2026-10-07 ✓】标签随口径 ✓：默认 `T-1` ✓（既有测试/日志检索依赖它 ✓）；
    #   实盘开了"信号日当天"⇒ 打 `信号日` ✓（不让日志误导 ✗）
    _lbl = '信号日' if gate.get('use_signal_day') else 'T-1'
    try:
        _c, _m = gate.get('close'), gate.get('ma')
        if _c is not None and _m is not None:
            _p = gate.get('ma_period') or DEFAULT_ENTRY_MA_PERIOD
            _ma_txt = f"close({_lbl})={float(_c):.2f} MA{int(_p)}={float(_m):.2f} "
    except (TypeError, ValueError):
        _ma_txt = ''
    return (f"ADX 闸门 {head} ADX({_lbl})={_a_txt} " + _ma_txt +
            f"band={gate.get('band') or '-'} "
            f"dir={gate.get('dir') or '-'} "
            f"（{gate.get('reason') or '-'}）")


def adx_entry_gate(df: pd.DataFrame, stock_code: str = '',
                   config: Optional[Dict] = None,
                   exclude_last: bool = True,
                   signal_date: Optional[str] = None,
                   use_db: bool = True,
                   is_add: bool = False) -> Dict:
    """**个股 ADX 买入闸门** ✓（首仓 ✓ + 加仓 ✓ **同一判据** ✓）

    Args:
        df: K线 df ✓（含 `adx` 列则直接使用 ✓；否则 `use_db=True` 时**自取库** ✓）
        stock_code: 股票代码 ✓（可带 `.SZ`/`.SH` 后缀 ✓，内部归一化 ✓）
        config: 配置 ✓
        exclude_last: `df` 快路径下是否丢掉最后一根（= T 日）✓
        signal_date: **信号日** ✓（库里取其**之前**的 `adx` ✗✓ 防前视 ✓）
        use_db: 允许自取库 ✓（单测可关 ✓，以保持纯函数可测性 ✓）

    Returns:
        `{'passed': bool, 'reason': str, 'band': str, 'dir': str,
          'skipped': bool, 'adx': float|None, 'close': float|None,
          'ma': float|None, 'ma_period': int}` ✓
        （`adx` = **判定所用那一根** ✓，即 T-1 ✓；取不到为 `None` ✓ —— 供日志 ✓）
        ★ 末三项（2026-09-30 ✓）= 首仓 MA 闸门用的 **T-1 收盘 / MA / 周期** ✓
          ⚠️ **只在真的进 MA 判定时才有值** ✓（加仓 ✗ / ADX 已拒 ✗ / 开关关 ✗ ⇒ `None` ✓
             —— 省掉无谓取数 ✓；`ma_period` 则总是给出 ✓）
    """
    if not is_adx_filter_enabled(config):
        return {'passed': True, 'reason': 'ADX 闸门未启用（enable_stock_adx_filter=false ✓）',
                'skipped': True, 'band': '', 'dir': '', 'adx': None}

    # ★★★★【2026-10-07 用户口径 ✓】**个股与大盘同口径：用「信号日当天」** ✗→✓ ★★★★
    #   用户原话 ✓："**个股也应该一致**" ✓（= 与大盘档位 `index_cap_use_signal_day` 一致 ✓）
    #   · **实盘** ✓：信号日收盘后决策 ⇒ 当天 ADX 已知 ✓、**T+1 成交** ✓（用户定稿时序 ✓）
    #     ⇒ 用当天**不是未来函数** ✗✓；
    #   · **回测** ✓：信号日 = 执行日 T 的**前一根** ✓，T 日**开盘**成交 ⇒ 当天 ADX 尚不存在 ✗
    #     ⇒ 必须仍取"前一根"✓（`exclude_last=True` ✓）—— 故本开关**默认 False** ✓、零回归 ✓。
    #   ⚠️ 只覆盖**取数口径** ✗✓：`dir`/`band` 仍是**完整回放**同一条序列 ✓
    #     （状态路径依赖 ✓ ⇒ 多/少一根都要从头重放 ✓，不会"近似"✗）。
    _today = resolve_use_signal_day(config)
    if _today:
        exclude_last = False        # ★ 快路径保留末根 = 信号日当天 ✓

    if df is None or getattr(df, 'empty', True):
        # ★【2026-09-28 用户要求 ✓】**改为不放行** ✗→✓（原为"无法归因 ⇒ 放行"✗）
        logger.warning(f'[StockAdxFilter] {stock_code} 无 K 线数据 ⇒ ADX 无法判定 ⇒ **不放行** ✗')
        return {'passed': False,
                'reason': '无 K 线数据 ⇒ 无法判定 ADX ⇒ **不放行** ✗（原为放行 ✗→✓）',
                'skipped': False, 'band': '', 'dir': '', 'adx': None}

    if ADX_COLUMN in df.columns:
        series = _adx_series(df, exclude_last)                     # 快路径 ✓
    elif use_db:
        series = _adx_series_from_db(stock_code, signal_date,
                                     include_signal_day=_today)    # ★ 实盘含当天 ✓
        if series is None:
            logger.error(f'[StockAdxFilter] {stock_code} 在库中无 `{ADX_COLUMN}` 数据 ✗ '
                         f'（df 也无该列 ✗）⇒ 判为 missing ✗ 并拒绝 ✗')
            return {'passed': False, 'reason': f'无 `{ADX_COLUMN}` 数据（missing ✗）',
                    'skipped': False, 'band': '', 'dir': '', 'adx': None}
    else:
        # 数据故障 ✗（显式拒绝 ✓，不静默通过 ✗）
        logger.error(f'[StockAdxFilter] {stock_code} 缺少 `{ADX_COLUMN}` 列 ✗ '
                     f'（且 `use_db=False` ✗）⇒ 拒绝 ✗')
        return {'passed': False, 'reason': f'缺少 `{ADX_COLUMN}` 列（missing ✗）',
                'skipped': False, 'band': '', 'dir': '', 'adx': None}
    # 过滤缺失值 ✓：**必须同时排除 `None`** ✗✓ —— 库里的 NULL 取出来是 `None` ✗，
    #   而 `None == None` 为 **True** ✗ ⇒ 只写 `v == v` 会漏过 `None` ⇒ 后面 `float(None)` 崩 ✗
    #   （实测踩过 ✓：`TypeError: float() argument must be … not 'NoneType'` ✗）
    valid = [v for v in series if v is not None and v == v]

    # ① 归因分流 ✓（§5.2 ✓）：**有效**根数不足 ⇒ 规则**不适用** ⇒ 放行 ✓（不误伤次新 ✓）
    #    注 ✓：预热期（120 根 ✓）在**计算侧**已置 NULL ✓（见 `utils/stock_adx.py` ✓）
    if len(valid) < MIN_APPLICABLE_BARS:
        # ★【2026-09-28 用户要求 ✓】**改为不放行** ✗→✓（原为"规则不适用 ⇒ 放行"✗）
        #   语义 ✓：ADX 尚未**收敛**（预热不足 ✓）⇒ 无法证明"明确且上升"✓ ⇒ **宁可不买** ✗
        #   ⚠️ 影响面 ✗✓：**上市不足 `MIN_APPLICABLE_BARS`(120) 根的次新股**将**不能买入** ✓
        #      （此前是"不误伤、放行"✗）⇒ 回测/实盘结果会变 ✓，须与新口径对比 ✓。
        logger.info(f'[StockAdxFilter] {stock_code} 有效 ADX 仅 {len(valid)} 根'
                    f'(<{MIN_APPLICABLE_BARS}，未收敛) ⇒ **不放行** ✗')
        return {'passed': False,
                'reason': (f'有效 ADX 仅 {len(valid)} 根(<{MIN_APPLICABLE_BARS}) ⇒ 未收敛 ⇒ '
                           f'**不放行** ✗（原为"规则不适用 ⇒ 放行"✗→✓）'),
                'skipped': False, 'band': '', 'dir': '', 'adx': None}

    # ② **信号日（T-1）缺值** ⇒ 故障 ✗（根数够却没值 ✗）⇒ 拒绝 ✗（不静默通过 ✗）
    _last = series[-1] if series else None
    if _last is None or _last != _last:
        return {'passed': False,
                'reason': '信号日 T-1 的 ADX 缺失（missing ✗）⇒ 拒绝买入 ✗',
                'skipped': False, 'band': '', 'dir': '', 'adx': None}

    # ③ 完整回放 ✓（状态**路径依赖** ✓，**不可**只取最近 N 天近似 ✗）
    #    · 起点 = 该股**首个有效** ADX ✓（预热期的 NULL 跳过 ✓ —— 未收敛值不可用 ✗）
    # ★【2026-09-28】方向口径 ✓：默认 `two_day`（连续两日同向 ✓，**不用 ε** ✗）；
    #   `epsilon` 档保留可切 ✓（A/B ✓）。两者都经同一 `resolve_dir_mode` ✓。
    tracker = AdxStateTracker(dir_mode=_resolve_dir_mode(config),
                              epsilon=_resolve_epsilon(config))   # ε 仅 epsilon 档生效 ✗
    for v in valid:
        tracker.update(float(v))
    st = tracker.state

    # ★【2026-09-28 用户要求 ✓】**避免出现"无方向"** ✗→✓：**判定日必须已有方向** ✓
    #   保证来源 = **前溯** ✓：
    #     · 序列起点 = 该股**最早的 ADX** ✓（`utils.stock_adx.fetch_adx_rows` ✓ 的 SQL
    #       **无日期下界** ✓，只有 `date < 信号日` 的**上界** ✓ ⇒ 天然全量 ✓）；
    #     · 且要求**有效根数 ≥ `MIN_APPLICABLE_BARS`(120)** ✓ ⇒ 判定日早已越过起点 ✓。
    #   ⇒ 因此这里若 `dir` 仍为空 ✗ ⇒ 属**数据异常** ✗（**不是**正常状态 ✓）：
    #     明确告警 ✓（提示前溯不足 ✓）+ 保守**不放行** ✓。
    if not st.dir:
        logger.warning(
            f'[StockAdxFilter] {stock_code} **判定日方向为空** ✗（有效 {len(valid)} 根 ✓）'
            f' ⇒ **前溯不足** ✗ —— 应"从该股最早 ADX 全量回放"✓（见 `_adx_series_from_db` ✓）；'
            f'按"非上升"保守处理 ⇒ **不放行** ✗')

    # ★【2026-09-28 用户口径 ✓】个股入场两档口径 ✓（由 `adx_entry_mode` 选 ✓，默认 `range` ✓）：
    #   · `'range'` ✓（**默认** ✓）：`low < ADX(T-1) < high` ✓ **且** `dir=上升` ✓
    #     —— **无缓冲** ✗、**不看 `band`** ✗（⇒ 反转日恒等价 ✓）；
    #   · `'band'` ✓（旧口径 ✓）：`dir=上升` ✓ 且 `band ∈ adx_entry_bands` ✓（默认只放「明确」✓）。
    #   ⚠️ **硬条件 `dir=上升` 两档都写死在实现里** ✗✓（不可配置 ✓，防"萌芽+非上升"误放 ✗）。
    mode = _resolve_entry_mode(config)
    if mode == 'range':
        _ranges = _resolve_entry_ranges(config)
        # ★【2026-09-29 用户要求 ✓】**多段并集** ✓（口径：`15<ADX<18 ∪ 23<ADX<42` ✓
        #   ⇒ `[(15,18), (23,42)]` ✓；**段之间为拒** ✗）
        # ★★【2026-09-29 用户口径 ✓】**加仓只检查 `dir=上升`** ✗→✓ ★★
        #   用户原话 ✓："**加仓只检查 dir 为上升**" ✓ ⇒ `check_range=False` ✓
        #   ⇒ **完全不校验 ADX** ✗（不看区间 ✗、不看上界 ✗、也不看下界 ✗），只要方向向上即放行 ✓；
        #   ⚠️ 这**取代**了旧档"加仓只豁免上界、下界仍管" ✗✓（旧档仍可由 `enforce_upper=False` 表达 ✓）。
        passed = entry_allowed_by_ranges(st, _ranges, enforce_upper=True,
                                         check_range=not is_add)
        _txt = ' ∪ '.join(f'{lo:g} < ADX < {hi:g}' for lo, hi in _ranges)
        _how = (_txt if not is_add
                else '**加仓 ⇒ 只看 `dir=上升`** ✓（**不校验 ADX** ✗）')
    else:
        bands = _resolve_entry_bands(config)
        passed = entry_allowed(st, bands)
        _how = f'band ∈ {"、".join(bands)}'
    reason = '' if passed else (
        f'ADX 状态不放行 ✗（band={st.band or "未预热"} dir={st.dir or "未定"}'
        f' adx={getattr(st, "adx", None)}）—— 要求 **dir=上升** 且 {_how} ✓')
    _ma = {'close': None, 'ma': None, 'ma_period': resolve_entry_ma_period(config)}
    # ★★【2026-09-30 用户要求 ✓】**首仓**追加「`close(T-1) > MA20`」✗→✓ ★★
    #   用户原话 ✓："**个股放行过滤增加 t-1(close) > ma20**" ✓
    #   ★★【2026-10-04 用户要求 ✓】**加仓也判** ✗→✓（用户答"需要" ✓）★★
    #   ⚠️ 顺序 ✗✓：**先 ADX 后 MA** ✓ —— ADX 已拒 ⇒ **不读收盘** ✗（省一次取数 ✓，
    #     且归因**只有一条**、不含糊 ✓）。
    #   ⚠️ **两条路各自一个开关** ✗✓（首仓 `adx_entry_require_above_ma` ✓ /
    #     加仓 `adx_add_require_above_ma` ✓）—— 分开是刻意的 ✓：
    #     加仓口径你 2026-09-29 定稿过"只看 `dir=上升`" ✓ ⇒ 必须能**独立回退** ✓，
    #     改加仓不该牵动首仓 ✗，反之亦然 ✗。
    if passed:
        _req = (is_add_above_ma_required(config) if is_add
                else is_entry_above_ma_required(config))
        if _req:
            _who = '加仓' if is_add else '首仓'
            try:
                _mg = _ma_gate(df, stock_code, config, exclude_last, signal_date,
                               use_db, include_signal_day=_today)   # ★ 同口径 ✓
                _ma = {'close': _mg['close'], 'ma': _mg['ma'],
                       'ma_period': _mg['ma_period']}
                if not _mg['passed']:
                    passed = False
                    _mlbl = 'close(信号日)' if _today else 'close(T-1)'
                    reason = (f'MA 闸门不放行 ✗（{_mg["reason"]}）—— '
                              f'{_who}要求 **{_mlbl} > MA{_mg["ma_period"]}** ✓')
            except Exception as e:                # 任何异常 ⇒ **保守不放行** ✓（绝不静默放行 ✗）
                logger.warning(f'[StockAdxFilter] {stock_code} MA 闸门异常 ✗({e}) ⇒ 保守不放行 ✗')
                passed = False
                reason = f'MA 闸门异常 ✗({e}) ⇒ 保守**不放行** ✗'
    # ★ `adx` = **判定所用那一根** ✓（= 序列末值 ✓：默认 T-1 ✓ / 实盘口径 = **信号日当天** ✓）
    return {'passed': passed, 'reason': reason, 'skipped': False,
            'band': st.band, 'dir': st.dir,
            'adx': getattr(st, 'adx', None),
            'close': _ma['close'], 'ma': _ma['ma'], 'ma_period': _ma['ma_period'],
            # ★【2026-10-07 ✓】口径**自证** ✓（日志/排查能直接看出用的哪一根 ✓）
            'use_signal_day': bool(_today)}


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
        # ★ 统一带上 `band/dir/adx` ✓ ⇒ 日志格式化**一套** ✓（加仓也看得到 T-1 值 ✓）
        # ⚠️ ADX 闸门**未运行**（规则2 先拒 ✓）⇒ `use_signal_day` 给 `False` ✓
        #   （此时 `adx=None` ⇒ 日志本来也只打 `-` ✓，不会误导 ✗）
        return {'passed': False, 'reason': f'加仓-规则2-{g2["reason"]}',
                'skipped': bool(g2.get('skipped')), 'band': '', 'dir': '',
                'adx': None, 'use_signal_day': False,
                'close': None, 'ma': None, 'ma_period': None}
    ga = adx_entry_gate(df, stock_code, config, signal_date=signal_date, use_db=use_db,
                        is_add=True)      # ★ 加仓 ✓：**不校验 ADX 上限** ✗✓（用户 2026-09-28 ✓）
    # ★★【2026-10-07 修复 ✓】**必须透传 `use_signal_day`（以及 MA 三项）** ✗→✓ ★★
    #   缘由 ✗✓（**测试当场抓出** ✓）：`_base` 原先只带 `skipped/band/dir/adx` ✗ ⇒
    #     `format_gate_result` 拿不到口径标记 ✗ ⇒ 实盘**加仓那条日志**
    #     （运行器打的正是 `add_entry_gate(...)` 的结果 ✗）会**误标回 `ADX(T-1)`** ✗✓
    #     —— 日志与真实口径不符 ⇒ 排查又被误导 ✗（本项目最忌的一类 ✗）。
    _base = {'skipped': bool(ga.get('skipped')), 'band': ga.get('band', ''),
             'dir': ga.get('dir', ''), 'adx': ga.get('adx'),
             'use_signal_day': bool(ga.get('use_signal_day')),
             'close': ga.get('close'), 'ma': ga.get('ma'),
             'ma_period': ga.get('ma_period')}
    if not ga['passed']:
        return dict(_base, passed=False, reason=f'加仓-ADX-{ga["reason"]}')
    return dict(_base, passed=True, reason='', detail={'rule2': g2, 'adx': ga})
