# -*- coding: utf-8 -*-
"""个股 ADX 状态机（纯函数 ✓ / 零依赖 ✓ / 可单测 ✓）

**单一事实源** ✓ —— §5.6（个股买入/加仓过滤）与 §5.8（大盘路由降温）**共用同一套原语** ✓，
杜绝"两处各写一份迟滞/降温逻辑"✗。

## 为什么需要"状态"✗✓

初稿个股条件是**无状态函数** ✗：

  · `上升 = adx[T-1] > adx[T-2]` —— **单日比较** ✗，差 `0.01` 就翻转 ✗（抖动 ✗）
  · `峰值 ≥ 40 后回落` —— "峰值"**无定义** ✗ 且无记忆 ✗

⇒ 用户定稿 ✓（2026-09-26）：**阈值 + 前一日状态** 判定 ✓，即本模块。

## 判定规则（唯一判定式 ✓）

放行 ⟺ **① `band=明确`** ✓（门槛 `≥25` ✓、**含迟滞** ✓）
　　 **且 ② `dir=上升`** ✓（**连续两日同向** ✓ ＋ **没方向沿用前一日** ✓，**不看 `ε`** ✗）
其余一律**拒绝** ✗（含 `band∈{震荡,萌芽}` ✓、`dir∈{下降,未定}` ✓）。

★ `cooled`（降温）**不是独立条件** ✗✓ —— 它**只把 `band` 压成「震荡」** ✓
（于是 `≥25 且上升` **本身就排除了回落** ✓，见 §5.6 ✓）。

## 三态递推（`f(今日值, 前一日状态)` ✓）

| 状态 | 规则 |
|---|---|
| `band` | 升档需 `adx ≥ 新档下界 + buffer`；降档需 `adx < 当前档下界 − buffer`；否则**保持** • **回落中的「反转日」⇒ 按当日 `adx` 原值直判**（**不吃 buffer** ✓，条件见 `is_mid_reversal` ✓ = **迟滞正托住更高档** ✓ ⇒ **只降不升** ✓）|
| `dir`  | `a > prev > grand` ⇒ **上升**；`a < prev < grand` ⇒ **下降**；**其余（一升一降/持平/预热不足）⇒ 沿用前一日 `dir`** ✓（首日无前值 ⇒ 未定 ✓）|
| `regime_of` | **唯一判定式** ✓：① `dir=上升` ⇒ 按 `band`；② `adx ≥ 40` 且 `dir≠上升` ⇒ **震荡**（**高位守门** ✓，**无状态** ✗）；③ `band=明确` 且 `dir≠上升` ⇒ **萌芽**；④ 其余 ⇒ 按 `band` ✓ |

⇒ **解除后以「震荡」为基准重新起算** ✓（不追溯"被压之前"的档位 ✗），
   因为 `cooled` 期间 `band` 字段本身就是「震荡」✓。

## 边界（易错 ✗✓）

· **判据是"档位"不是"数值"** ✗✓：因迟滞 ✓，`band=明确` **≠** `adx ≥ 25`
  —— 例 `26 → 24.2`：`24.2 ≥ 25−1 = 24` ⇒ **仍为「明确」** ✓（初稿按 `≥25` 会拒绝 ✗）
· **降档是严格小于** ✓：`adx < 下界 − buffer`（`24.0` **不算**跌破 ✗ ⇒ 保持「明确」✓）
· **升档非严格** ✓：`adx ≥ 下界 + buffer`（`21.0` 恰好 ⇒ 升「萌芽」✓）
· **反转日不吃 buffer** ✗✓（**2026-09-27 用户口径** ✓，**2026-09-28 保留** ✓）：
  **正常换挡有 buffer** ✓ —— 唯独「**回落中出现中间反转**（`dir` 转「上升」✓）」
  的那一天 ✓，`band` **直接按当日 `adx` 原值判定** ✓（等价 `buffer=0` ✓）；
  判据见 `is_mid_reversal` ✓：**迟滞正托住更高档** ✓（当日**原值档更低** ✓、
  却被 `current_band` **滞留** ✗）⇒ 命中日不吃缓冲 ✓。
  ⚠️ **只收紧不放宽** ✓（恒为降档方向 ✓）；实测 80 只 / 85942 日：
  **收紧 44 次 / 放宽 0 次** ✓（历史 (a) 分支"曾见 40+"随降温一起**已移除** ✗✓，
  它当时**零命中** ✗ ⇒ 无损失 ✓）。

## ★ 2026-09-28 用户口径 ✓：**降温机制已整体移除** ✗✓

理由 ✓（用户原话）：**过于复杂、很难理解** ✗。移除的东西 ✓：
`cooled`（降温态 ✓）/ 峰值门 `40` ✓ / `fell_from_high`（"曾见高位"✓）/
进入①② 与"连升两日解除" ✓ / 大盘侧 `enable_adx_falloff` ✓ / 强制「震荡」✓。
**现在只剩** ✓（**个股与大盘同一实现** ✓）：`band`（含缓冲带 ✓）+ `dir`（两日同向 ✓）
+ 反转日不吃缓冲 ✓ —— 判定式仅 **`regime_of`**（=`band + dir` ✓）一处 ✓。

## 预热（必须 ✓，与数据闸门联动 ✓）

状态**路径依赖** ✓ ⇒ 回测起点前必须回放 ✓：**ADX 历史起点 ≤ 回测起点** ✓，
否则**同日同 ADX 会得出不同档位** ✗（不可复现 ✗）。由数据闸门**明确拒绝** ✓（不静默 ✗）。

## 缺数据（不在此处理 ✗，由调用方按归因分流 ✓）

`step()` 遇到 `None` / `NaN` / 非有限值 ⇒ **原样返回前一状态** ✓（不破坏状态 ✓）。
"放行还是拒绝"由调用方按 §5.2 的归因决定 ✓：
`not_applicable`（样本不足 ✓）→ 放行 ✓；`missing`（故障 ✗）→ 拒绝 ✗ + WARN ✓。

## 用法

    from utils.stock_adx_state import AdxState, step, allows_entry

    st = AdxState()
    for adx in series:            # 按交易日**升序**逐个回放 ✓
        st = step(st, adx)
    if allows_entry(st):          # = ① band=明确 ② dir=上升 ✓
        ...

参数 ✓：**方向口径** `dir_mode`（默认 `two_day` ✓ = 连续两日同向 ＋ 没方向沿用前一日 ✓）；
`epsilon` 仅为**旧档**噪声门槛 ✗（`dir_mode='epsilon'` 时生效 ✓，见 `DIRECTION_EPSILON` ✓）。
**唯一判定式** = `regime_of` ✓（个股 / 大盘**同一实现** ✓）；**降温机制已整体移除** ✗（设计文档 §5.0 ✓）。
"""
import logging
import math
from dataclasses import dataclass, replace
from typing import Iterable, List, Optional, Tuple

# ★【2026-09-28 修复 ✗→✓】本模块**此前没有 `logger`** ✗ —— 而 `resolve_dir_mode` /
#   `resolve_entry_bands` 的"**未知入参**"分支都要 `logger.warning` ✗ ⇒ **一走到就
#   `NameError`** ✗✓（实测踩到 ✓）。现补上 ✓。
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ 常量

BAND_RANGE = '震荡'      # < 20
BAND_SPROUT = '萌芽'     # 20 ~ 25
BAND_TREND = '明确'      # >= 25

BAND_LABELS: Tuple[str, str, str] = (BAND_RANGE, BAND_SPROUT, BAND_TREND)

#: 档位下界（与标签一一对应 ✓）
BAND_THRESHOLDS: Tuple[float, float] = (20.0, 25.0)

#: 档位切换缓冲带（迟滞宽度 ✓；与 §5.8 的 `BAND_BUFFER` 同值同义 ✓）
BAND_BUFFER: float = 1.0

#: 方向防抖宽度 `ε` ✓（§9 Q7「**必须实测标定** ✗，不拍脑袋 ✓」）
#:
#: ⚠️【2026-09-28 口径变更 ✓】**默认档已改为 `two_day`（连续两日同向 ✓）⇒ 本常量
#:   只在旧档 `dir_mode='epsilon'` 下生效** ✗✓（A/B 用 ✓）。实测差异（80 只 / 13055 股日 ✓）：
#:   `epsilon` 放行 2279 ✗ → `two_day` **1976** ✓（**−13.3%** ⇒ 更严 ✓）。
#:
#: ★ **已标定** ✓（2026-09-27 ✓，M2 落地后 ✓）：实测个股 `|Δadx|` 分布 ✓
#:   样本 ✓：**537 只**（等距抽样 ✓）× **476,368** 对可比差分 ✓（只算相邻两日都非 NULL ✓）
#:
#:   | 分位 | p10 | p25 | **p50** | p60 | p75 | p90 | p95 |
#:   |---|---|---|---|---|---|---|---|
#:   | \|Δadx\| | 0.15 | 0.37 | **0.76** | 0.94 | 1.26 | 1.80 | 2.15 |
#:
#:   ⇒ 取 **中位数** ✓（≈0.76 ⇒ 定为 **0.75** ✓）—— 即"**约一半的日变化属工程噪声**"✓。
#:   ⚠️ 旧值 `0.5` 的问题 ✗✓：它 **低于中位数** ✗ ⇒ 仅 **33.4%** 的日"持平"✓
#:      ⇒ 方向**几乎两天翻一次** ✗（抖动 ✗）。
#:   ⚠️ 若求更保守 ✓：可取 p60~p75（0.94~1.26 ✓，持平 63%~83% ✓）—— **可配置** ✓：
#:      按次覆盖 `config['adx_direction_epsilon']` ✓（见 `trading/stock_adx_filter.py` ✓，
#:      A/B 友好 ✓），**不必**改本常量 ✓。
#:   ⚠️ 本值属**工程噪声门槛** ✗（非策略阈值 ✓）⇒ 仍需 M7 A/B 复核 ✓（§12 ✓）。
DIRECTION_EPSILON: float = 0.75

#: ⚠️【2026-09-28 **已移除** ✗✓】原「降温触发峰值门」`COOLED_PEAK = 40.0`
#:   —— 降温机制整体移除 ✓（用户口径：过于复杂、很难理解 ✗）；
#:   引用它的地方应改为**不再需要** ✓（预热/大盘路由均已简化 ✓）。

DIR_UP = '上升'
DIR_DOWN = '下降'
DIR_UNKNOWN = ''

# ------------------------------------------------------------------ 方向口径
# ★★【2026-09-28 用户口径 ✓】**`dir` 改由"连续两日"决定** ✗→✓ ★★
#
# 规则 ✓（新默认 = `two_day` ✓）：
#   · `a > prev > grand` ✓ ⇒ **上升** ✓
#   · `a < prev < grand` ✓ ⇒ **下降** ✓
#   · 其余（两日不同向 / 中间拐点 / 持平）⇒ **沿用前一日 `dir`** ✓
#     ★ 用户 2026-09-28 补充口径 ✓：**避免来回反复调整仓位** ✓（首日无前值 ⇒ 未定 ✓）
#   ⇒ **完全不使用 `ε`** ✗✓（原 `epsilon` 档的"|Δ|≤ε ⇒ 保持前一日"已不再默认 ✓）
#
# 为何改 ✗✓（用户 2026-09-28 决定 ✓）：`dir` 要表达的是**方向已被两日确认** ✓，
#   而不是"今天相对昨天的瞬时差" ✗ —— 后者靠 `ε` 挡噪声 ✗，噪声一多就**抖动** ✗；
#   两日同向则**天然要求连续性** ✓，且与降温的"连升/连降两日"**同一语义** ✓
#   （§5.8 ✓ —— 至此「方向」全库只有一种口径 ✓）。
#
# ⚠️ 影响面 ✗✓（**实测** ✓，详见设计文档 §5.0.4 ✓）：
#   · 相对 `epsilon` 档 ✓：`two_day` 放行 **2279 → 1976（−13.3%）** ⇒ **更严** ✓；
#   · 而**方向锁存**（本档 ✓）相对"未定"版 ⇒ **更宽松** ✗：
#     个股放行 **13581 → 16352（+2771 = +20.4%）**、大盘「明确」**308 → 364（+56 日）** ✓
#     —— **用户明确接受该取舍** ✓（**防抖优先** ✓：避免仓位来回反复 ✓）。
#   ⚠️ 大盘 `RegimeRouter` 共用本原语 ✓ ⇒ 自适应回测档位随之变化 ✓（个股闸门 / 大盘**同口径** ✓）。
# ⚠️ 旧口径**保留可切** ✓（A/B 用 ✓）：`dir_mode=epsilon`（+ `epsilon` ✓）。
DIR_MODE_TWO_DAY = 'two_day'      #: ★ **默认** ✓：连续两日同向 ✓（2026-09-28 用户口径 ✓）
DIR_MODE_EPSILON = 'epsilon'      #: 旧口径 ✓（保留 ✓：|Δ|≤ε ⇒ 保持前一日 ✓）
DEFAULT_DIR_MODE = DIR_MODE_TWO_DAY

#: 方向口径别名 ✓（大小写/写法不敏感 ✓；`config['adx_dir_mode']` ✓）
DIR_MODE_ALIASES = {
    'two_day': DIR_MODE_TWO_DAY, 'two-day': DIR_MODE_TWO_DAY, 'twoday': DIR_MODE_TWO_DAY,
    'two': DIR_MODE_TWO_DAY, '2day': DIR_MODE_TWO_DAY, '两日': DIR_MODE_TWO_DAY,
    '连续两日': DIR_MODE_TWO_DAY, '两日同向': DIR_MODE_TWO_DAY,
    'epsilon': DIR_MODE_EPSILON, 'eps': DIR_MODE_EPSILON, 'ε': DIR_MODE_EPSILON,
    '旧': DIR_MODE_EPSILON, '原口径': DIR_MODE_EPSILON,
}


def resolve_dir_mode(raw, default: str = DEFAULT_DIR_MODE) -> str:
    """解析方向口径 ✓（未知值 ⇒ `default` ✓ 并告警 ✓，**不抛** ✗）"""
    if raw is None or raw == '':
        return default
    m = DIR_MODE_ALIASES.get(str(raw).strip().lower())
    if not m:
        logger.warning(f'未知方向口径 {raw!r} ⇒ 回落 `{default}` ✓'
                       f'（已知：{DIR_MODE_TWO_DAY} / {DIR_MODE_EPSILON} ✓）')
        return default
    return m


# ------------------------------------------------------------------ 数据结构

@dataclass(frozen=True)
class AdxState:
    """ADX 状态快照（**不可变** ✓ == 比较可用 ✓ —— 可复现性测试依赖它 ✓）

    ★【2026-09-28 用户口径 ✓】**只剩两项** ✗→✓（"规则更简单"✓）：
      `band`（含**缓冲带/迟滞** ✓）+ `dir`（**连续两日同向** ✓）；
      ⚠️ **降温机制（`cooled` / 峰值 `40` / 强制「震荡」）已整体移除** ✗✓
      （用户 2026-09-28：**过于复杂、很难理解** ✗）。

    Attributes:
        band: 档位（`震荡`/`萌芽`/`明确`；未预热时为 `''` ✓）—— **带缓冲带** ✓
        dir: 方向（`上升`/`下降`；未定/首日/预热不足为 `''` ✓）—— **两日同向**才成立 ✓
        adx: 本日 ADX（`adx[T]` ✓）
        prev_adx: 前一日 ADX（`adx[T-1]` ✓）—— 供"两日同向"判定与日志 ✓
        reason: ★ **本步的判定依据** ✓（2026-09-27 用户要求"判定依据打印到日志" ✓）——
            **人话一行** ✓：是否走了"反转日按原值" ✓、迟滞是保持还是切换 ✓
    """
    band: str = ''
    dir: str = ''
    adx: Optional[float] = None
    prev_adx: Optional[float] = None
    #: ★ **本步的判定依据** ✓（**只用于日志/归因** ✗，**不参与**任何判定 ✓）
    #:   · **每步重写** ✗ ⇒ **无累积语义** ✓ ⇒ **不必持久化** ✓
    #:     （`RegimeRouter` 仍只存 6 个标量 ✗，**不扩存储** ✓）
    #:   · 多条理由用 `；` 连接 ✓（同日可能既"解除降温"又"命中反转日"✓）
    reason: str = ''

    # ---- 便捷只读属性 ----
    @property
    def is_trending(self) -> bool:
        """是否处于「明确」档 ✓（不看方向 ✓）"""
        return self.band == BAND_TREND

    @property
    def is_rising(self) -> bool:
        """方向是否「上升」✓"""
        return self.dir == DIR_UP

    @property
    def warmed_up(self) -> bool:
        """是否已预热 ✓（有档位且有方向 ⇒ 可参与判定 ✓）"""
        return bool(self.band) and bool(self.dir)


# ------------------------------------------------------------------ 纯函数原语

def band_of(adx: float,
            thresholds: Tuple[float, float] = BAND_THRESHOLDS,
            labels: Tuple[str, str, str] = BAND_LABELS) -> str:
    """**纯阈值**分档（无迟滞 ✓）：`<20 震荡` / `20~25 萌芽` / `≥25 明确` ✓

    非法/非有限入参 ⇒ 返回 `''` ✓（不抛异常 ✓）。
    """
    try:
        v = float(adx)
    except (TypeError, ValueError):
        return ''
    if not math.isfinite(v):
        return ''
    if v < thresholds[0]:
        return labels[0]
    if v < thresholds[1]:
        return labels[1]
    return labels[2]


def _lower_bound(band: str,
                 thresholds: Tuple[float, float] = BAND_THRESHOLDS,
                 labels: Tuple[str, str, str] = BAND_LABELS) -> float:
    """档位下界 ✓（未知档位 ⇒ `-1` ✓）；「明确」上界视为 `+∞` ✓"""
    if band == labels[0]:
        return 0.0
    if band == labels[1]:
        return thresholds[0]
    if band == labels[2]:
        return thresholds[1]
    return -1.0


def apply_hysteresis(adx: float, current_band: str = '',
                     thresholds: Tuple[float, float] = BAND_THRESHOLDS,
                     buffer: float = BAND_BUFFER,
                     labels: Tuple[str, str, str] = BAND_LABELS) -> str:
    """**带迟滞**分档 ✓ —— 升档 `≥ 下界+buffer` ✓；降档 `< 下界−buffer` ✓（**严格** ✗✓）；否则**保持** ✓

    `current_band` 为空或非法 ⇒ 退回**纯阈值** ✓（首日/预热不足 ✓）。
    """
    raw = band_of(adx, thresholds, labels)
    if not raw:
        return ''
    cur = str(current_band or '')
    if not cur or cur == raw or cur not in labels:
        return raw

    cur_low = _lower_bound(cur, thresholds, labels)
    raw_low = _lower_bound(raw, thresholds, labels)
    if raw_low > cur_low:                      # 升档 ✓（非严格 ✓）
        return raw if float(adx) >= raw_low + buffer else cur
    if raw_low < cur_low:                      # 降档 ✗（**严格小于** ✓）
        return raw if float(adx) < cur_low - buffer else cur
    return raw


def is_mid_reversal(dir_state: str,
                    current_band: str = '', adx: Optional[float] = None,
                    thresholds: Tuple[float, float] = BAND_THRESHOLDS,
                    labels: Tuple[str, str, str] = BAND_LABELS) -> bool:
    """**反转日 ⇒ 按当日 `adx` 原值判档** ✓（**2026-09-27 用户口径** ✓，09-28 保留 ✓）

    判据 ✓（**只剩一条** ✗→✓，`fell_from_high` 分支随降温一起移除 ✓）：
      · 「**反转**」✓ = 当日方向为**上升** ✓（= 两日连升 ✓）；
      · 「**回落中**」✓ = **迟滞正托住更高档** ✗✓ —— 当日**原值档更低** ✓、
        却被 `current_band` **滞留** ✗（`_lower_bound(原值) < _lower_bound(current_band)` ✓）。
    ⇒ 命中日 `band` **不吃缓冲带** ✗✓ —— **直接按当日 `adx` 原值**判定 ✓。

    ⚠️ **为何这条不可省** ✗✓（**实测** ✓，2026-09-27 ✓）：迟滞会把"回落前的旧高档"
      **继续托住** ✗ ⇒ 例 `25.6 → 24.9` ⇒ `24.9 ≥ 25−1 = 24` ⇒ `band` 仍「明确」✗
      ⇒ 与 `dir=上升` 组合成**误放行** ✗✓。

    ⚠️ **只可能收紧** ✗✓：本判据**恒为降档方向** ✓（`明确→萌芽` ✓ / `萌芽→震荡` ✓）
      ⇒ 绝不会因它而提前升档放行 ✗；实测 ✓：档位变化 **75 日** ✓、
      **收紧放行 44 次 / 放宽 0 次** ✓✓。
    """
    if str(dir_state or '') != DIR_UP:
        return False
    if not current_band or adx is None:
        return False
    try:
        raw = band_of(float(adx), thresholds, labels)
    except (TypeError, ValueError):
        return False
    if not raw or str(current_band) == raw:
        return False
    return (_lower_bound(raw, thresholds, labels)
            < _lower_bound(str(current_band), thresholds, labels))


# ------------------------------------------------------------------ 递推主函数

def step(state: Optional[AdxState], adx: Optional[float],
         band_thresholds: Tuple[float, float] = BAND_THRESHOLDS,
         band_buffer: float = BAND_BUFFER,
         epsilon: float = DIRECTION_EPSILON,
         dir_mode: str = DEFAULT_DIR_MODE) -> AdxState:
    """按**一个交易日**推进状态 ✓（`f(今日值, 前一日状态)` ✓）

    ★【2026-09-28 用户口径 ✓】**规则只剩两条** ✗→✓（"规则更简单"✓）：
      `band`（**含缓冲带/迟滞** ✓，用户明确要求保留 ✓）+ `dir`（**连续两日同向** ✓）；
      ⚠️ **降温机制已整体移除** ✗✓ —— 不再有 `cooled` / 峰值 `40` /
      `fell_from_high` / 进入①②/解除 ✗（用户：过于复杂、很难理解 ✗）。

    Args:
        state: 前一日状态（`None` / `AdxState()` ⇒ 视为**未预热** ✓）
        adx: 今日 `adx[T]` ✓（须为**已确认**的收盘后值 ✓，防前视 ✓）
        band_thresholds: 档位下界 ✓（默认 `(20, 25)` ✓）
        band_buffer: 迟滞宽度 ✓（默认 `1.0` ✓ —— **保留** ✓）
        epsilon: 方向防抖 `ε` ✓（**仅** `dir_mode='epsilon'` 时生效 ✗，见 `DIRECTION_EPSILON` ✓）
        dir_mode: 方向口径 ✓（默认 `two_day` = **连续两日同向** ✓，**不看 `ε`** ✗）

    Returns:
        新的 `AdxState` ✓；**缺数据时原样返回前一状态** ✓（不破坏状态 ✓）
    """
    st = state if isinstance(state, AdxState) else AdxState()
    try:
        a = float(adx)
    except (TypeError, ValueError):
        return st                            # 缺数据 ⇒ 原样返回 ✓（归因分流交给调用方 ✓）
    if not math.isfinite(a):
        return st

    prev = st.adx                            # = adx[T-1] ✓
    grand = st.prev_adx                      # = adx[T-2] ✓

    # ---- ① 方向（★ 2026-09-28 用户口径 ✓：**连续两日同向** + **没方向沿用前一日**）----
    #   规则 ✓（`two_day`＝**默认档** ✓）：
    #     · `a > prev > grand` ⇒ **上升** ✓；`a < prev < grand` ⇒ **下降** ✓；
    #     · **其余（一升一降 / 持平 / 预热不足 ✓）⇒ 沿用前一日 `dir`** ✓（首日无前值 ⇒ `''` ✓）。
    #   ★ 用户补充口径 ✓（2026-09-28 ✓，原话）：**没方向时沿用前一日方向，避免来回反复调整仓位** ✓。
    #   ⚠️ 代价 ✗（**已实测** ✓）：`dir` 会在**拐点后滞留 1~2 天** ✗ ⇒ 若前一日仍是「上升」✓，
    #     `regime_of` 会**按上升处理**（可能给「明确」⇒ 放行 ✗）—— 比"未定 ⇒ 最高萌芽"**更宽松** ✗✓；
    #     用户已明确接受该取舍 ✓（**防抖优先** ✓）。
    #   ⚠️ 回严开关 ✓：`dir_mode='epsilon'`（需要大变动才改向 ✓）或把本行初值改回 `DIR_UNKNOWN` ✓。
    #   旧口径 ✓（`dir_mode=epsilon` ✓，保留 A/B ✓）：单日 `|Δ| > ε` 才改向 ✓，否则**保持前一日** ✓。
    d = st.dir
    if prev is not None:
        if dir_mode == DIR_MODE_TWO_DAY:
            if grand is not None:
                if prev > grand and a > prev:
                    d = DIR_UP          # 两日**连升** ✓
                elif prev < grand and a < prev:
                    d = DIR_DOWN        # 两日**连降** ✓
                # 其余 ⇒ **沿用前一日** ✓（`d` 初值 = `st.dir` ✓）—— 用户 2026-09-28 口径 ✓
        else:
            delta = a - prev
            if delta > epsilon:
                d = DIR_UP
            elif delta < -epsilon:
                d = DIR_DOWN
            # |Δ| ≤ ε ⇒ **保持前一日方向** ✓（这是防抖的关键 ✗✓）

    # ---- ② 档位（**缓冲带** ✓；**反转日 ⇒ 按当日原值** ✓）----
    #   ★【2026-09-27 用户口径 ✓】**正常换挡有 buffer** ✓（**保留** ✓）；
    #     唯独"**回落中的中间反转**"那一天 ⇒ **按反转日的 `adx` 直接判定** ✓
    #     ⇒ 仅该日令 `buffer=0.0`
    #     （`buffer=0` ⇒ 升档门 `a ≥ raw_low` 恒真 ✓、降档门 `a < cur_low` 必真 ✓
    #      ⇒ **恰好等价于** `band_of(a)` 原值直判 ✓）
    #   ⚠️ 降温曾是**最高**优先（覆盖 band ✗）—— **已移除** ✗✓
    reasons: List[str] = []
    mid_reversal = is_mid_reversal(d, st.band, a, band_thresholds)
    if mid_reversal:
        reasons.append(f'反转日：dir={d} ✓ 且"迟滞托住更高档"✓ ⇒ 按当日原值 {a:g} 直判、'
                       f'不吃 ±{band_buffer:g} 缓冲（步进前档='
                       f'{st.band or "未预热"}）')
    band = apply_hysteresis(a, st.band, thresholds=band_thresholds,
                            buffer=(0.0 if mid_reversal else band_buffer))
    if band and band != st.band:
        reasons.append(f'迟滞切换：「{st.band or "未预热"}」→「{band}」'
                       f'（升档需 ≥ 下界+{band_buffer:g}／降档需 < 下界−{band_buffer:g}）')
    elif band:
        reasons.append(f'迟滞保持「{band}」')

    return AdxState(band=band, dir=d, adx=a, prev_adx=prev,
                    reason='；'.join(reasons))


def run(values: Iterable[Optional[float]], **kwargs) -> List[AdxState]:
    """按序列回放 ✓（升序 ✓），返回每一步的状态 ✓（调试/单测便利 ✓）"""
    st = AdxState()
    out: List[AdxState] = []
    for v in values:
        st = step(st, v, **kwargs)
        out.append(st)
    return out


# ------------------------------------------------------------------ 判定

#: ★【2026-09-28 用户口径 ✓】**高位守门线** ✓ —— **无状态**的绝对阈值 ✗✓
#:   `adx ≥ 40` 且**方向不再确认**（`dir ≠ 上升` ✓）⇒ 直接判「**震荡**」（空仓级 ✓）。
#:   ⚠️ 它**不是**原来的"降温机制" ✗✓ —— **无锁存 / 无记忆 / 无预热依赖** ✓：
#:   `adx` 回到 40 以下 或 `dir` 转「上升」⇒ **当日立刻**回正常档 ✓
#:   （原降温要"连升两日"才解除 ✗ —— 那套已整体移除 ✓）。
#:   实测 ✓（大盘 ADX 1633 日 ✓）：相对 `band+dir` **新增震荡 117 日** ✓、
#:   **放宽 0 日** ✓（**只可能更保守** ✓）；个股侧**零变化** ✓
#:   （个股只看"是否明确"⇒ 40+ 与 萌芽 都不放行 ✓）。
HIGH_ADX_GUARD: float = 40.0


def regime_of(state: Optional[AdxState]) -> str:
    """★★ **唯一判定式** ✓：`band + dir`（＋**高位守门** ✓）⇒ 档位 ✗→✓ ★★

    规则 ✓（**个股与大盘共用本函数** ✓ ⇒ 大盘「明确」 ⟺ 个股「放行」✓）：

        · `dir = 上升` ✓ ⇒ **按 `band`** ✓（**缓冲带/迟滞保留** ✓ 用户 2026-09-28 ✓）
        · `adx ≥ 40` 且 `dir ≠ 上升` ✓ ⇒ **震荡** ✓（高位 + 方向不再确认 ⇒ 空仓级 ✓）
        · `band = 明确` 且 `dir ≠ 上升` ✓ ⇒ **降一档 ⇒ 萌芽** ✓（方向存疑 ✓）
        · 其余 ✓ ⇒ 按 `band` ✓

    ⚠️ **③ 必须按 `band` 判，不能按 `adx` 原值区间** ✗✓（**实测踩到** ✓）：
      迟滞会把 `adx = 24.5` **托成「明确」** ✓ —— 若按"原值 25~40 ⇒ 萌芽"写 ✗，
      这些日子会落进"其余 ⇒ 按 band"⇒ **返回明确（满仓）** ✗✗；
      实测大盘 **23 日**被判错（比现方案**更宽松** ✗）⇒ 改为按 `band` 后 ✓：
      **只可能更保守** ✓（新增震荡 **117 日** ✓、放宽 **0** 日 ✓）。

    ⚠️ 两条不变量 ✓：
      ① **绝不放松** ✓：只在"方向未确认"时**降档** ✗（从不升档 ✓）；
      ② **无状态** ✓：只看**当日** `adx`/`dir`/`band` ✓ —— **无锁存、无解除条件** ✗✓
         （故**不需要**任何跨日记忆 ✓，预热只需 `band` 迟滞与 `dir` 两日的路径 ✓）。
    """
    if state is None:
        return ''
    band = state.band
    if state.dir != DIR_UP:
        # ① 高位 + 方向不再确认 ⇒ **震荡**（空仓级 ✓）★ 2026-09-28 用户口径 ✓
        try:
            if state.adx is not None and float(state.adx) >= HIGH_ADX_GUARD:
                return BAND_RANGE
        except (TypeError, ValueError):
            pass
        # ② 明确档但方向存疑 ⇒ **降一档 ⇒ 萌芽** ✓（按 `band` ✓，见 docstring ③ ✓）
        if band == BAND_TREND:
            return BAND_SPROUT
    return band


#: ★【2026-09-28 用户口径 ✓】**默认入场档位集合** ✓ = 只放「明确」✓（= **零行为变化** ✓）
DEFAULT_ENTRY_BANDS: Tuple[str, ...] = (BAND_TREND,)

#: 入场档位别名 ✓（`config['adx_entry_bands']` ✓，写法/大小写不敏感 ✓）
ENTRY_BAND_ALIASES = {
    '明确': BAND_TREND, 'trend': BAND_TREND, 'strong': BAND_TREND,
    '萌芽': BAND_SPROUT, 'sprout': BAND_SPROUT, 'medium': BAND_SPROUT,
    '震荡': BAND_RANGE, 'range': BAND_RANGE, 'weak': BAND_RANGE,
}


def resolve_entry_bands(raw, default: Tuple[str, ...] = DEFAULT_ENTRY_BANDS) -> Tuple[str, ...]:
    """解析**入场档位集合** ✓（`['明确','萌芽']` ✓ / `'明确,萌芽'` ✓；未知项**忽略**并告警 ✓）

    ⚠️ 空集合 ⇒ 回落 `default` ✓（**绝不**变成"全部放行"✗）。
    """
    if raw is None or raw == '':
        return tuple(default)
    items = raw if isinstance(raw, (list, tuple, set)) else str(raw).replace('，', ',').split(',')
    out: List[str] = []
    for it in items:
        key = str(it or '').strip().lower()
        if not key:
            continue
        v = ENTRY_BAND_ALIASES.get(key) or (key if key in BAND_LABELS else None)
        if not v:
            logger.warning(f'未知入场档位 {it!r} ⇒ 忽略 ✓（可选：明确 / 萌芽 / 震荡 ✓）')
            continue
        if v not in out:
            out.append(v)
    return tuple(out) or tuple(default)


def entry_allowed(state: Optional[AdxState],
                  bands: Tuple[str, ...] = DEFAULT_ENTRY_BANDS) -> bool:
    """★ **入场判定** ✓：**硬条件 `dir = 上升`** ✗✓ **且** `band ∈ bands` ✓

    ⚠️⚠️ **严禁**写成"`regime_of(state) ∈ bands`" ✗✓（**实测踩过** ✗）：
      `regime_of` 的「萌芽」有**两种来源** ——
        ① `band = 萌芽`（**任意方向** ✓）；② `band = 明确` 但 `dir ≠ 上升`（**被降档** ✓）。
      ⇒ 若按输出档位判 ✗ ⇒ 会把 **「萌芽 + 非上升」的 9291 天**也放进场 ✗✗
        （80 只 / 80151 天实测 ✓：比"明确+萌芽 ∧ 上升"的 24041 天还多一倍 ✗）。
      ⇒ 故本函数**只读原始两要素**（`dir` ✓ + `band` ✓）✓（**单一事实源** ✓）。

    ⚠️ 与 `allows_entry` 的关系 ✓：`allows_entry` = `entry_allowed(state)` ✓
      （默认集合 = `('明确',)` ✓ ⇒ **语义完全不变** ✓）。
    """
    if state is None:
        return False
    if state.dir != DIR_UP:
        return False                    # ★ 硬条件 ✓（不可配置 ✗、不可放宽 ✗）
    return state.band in tuple(bands or DEFAULT_ENTRY_BANDS)


#: ★【2026-09-28 用户口径 ✓】**个股入场区间**（**开区间** ✓：`low < adx < high` ✓；可配置 ✓）
#:   —— 与"档位集合"（`adx_entry_bands` ✓）**二选一** ✓，由 `adx_entry_mode` 决定 ✓
#:   （默认 `'range'` ✓ = 用户现行要求 ✓；回旧口径 ⇒ `'band'` ✓）。
DEFAULT_ENTRY_RANGE: Tuple[float, float] = (21.0, 30.0)


#: ★【2026-09-29 用户口径 ✓】**入场区间 = 可多段（并集 ✓）**
#:   用户原话 ✓："我希望扩大个股放行买入的区间：`15<ADX<18 ∪ 23<ADX<42`"
#:   ⇒ 表达为**两段并集** ✓：`(15,18) ∪ (23,42)` ✓（**中间 `18 ≤ ADX ≤ 23` 拒** ✗）。
#:   语法 ✓（**同一个键** `adx_entry_range` ✓，按元素个数区分 ✓，**旧写法完全兼容** ✓）：
#:     · `[21, 30]` ✓             ⇒ 单段 ✓（**与旧行为逐位一致** ✓）
#:     · `[15, 18, 23, 42]` ✓     ⇒ 两段 ✓（**扁平偶数个 = 两两成段** ✓）
#:     · `[[15,18],[23,42]]` ✓    ⇒ 两段 ✓（**嵌套写法** ✓）
#:     · `'15,18,23,42'` ✓        ⇒ 同上 ✓（字符串 CSV ✓；全角逗号也认 ✓）
#:   ⚠️ 段内**自动排序** ✓（小者作下界 ✓，写反了自动纠正 ✓）；
#:      段按**下界升序**排列 ✓（只为日志稳定 ✓，不影响判定 ✓）。
DEFAULT_ENTRY_RANGES: Tuple[Tuple[float, float], ...] = (DEFAULT_ENTRY_RANGE,)


def resolve_entry_ranges(raw, default=None) -> Tuple[Tuple[float, float], ...]:
    """解析**入场区间（可多段 ✓）** ⇒ `((lo, hi), ...)` ✓

    见 `DEFAULT_ENTRY_RANGES` 注释里的语法说明 ✓。
    **非法（奇数个 / 非数值 / 空）⇒ 告警 + 回落默认** ✓（**绝不抛** ✗ —— 绝不因一个配置写法阻断买卖 ✗）。
    """
    dflt: Tuple[Tuple[float, float], ...] = (tuple(default) if default
                                            else DEFAULT_ENTRY_RANGES)
    try:
        if raw is None or raw == '':
            return dflt
        # ① 嵌套写法 ✓：[[0,18],[21,42]] / [(0,18),(21,42)]
        if (isinstance(raw, (list, tuple)) and raw
                and all(isinstance(x, (list, tuple)) and len(x) == 2 for x in raw)):
            pairs = [tuple(sorted(float(str(y).strip()) for y in x)) for x in raw]
        else:
            # ② 扁平写法 ✓：[0,18,21,42] / '0,18,21,42' / [21,30]
            items = (raw if isinstance(raw, (list, tuple, set))
                     else str(raw).replace('，', ',').split(','))
            vals = [float(str(x).strip()) for x in items if str(x).strip() != '']
            if len(vals) % 2 != 0:
                raise ValueError(f'需要**偶数个**阈值（两两成段），收到 {len(vals)} 个')
            pairs = [tuple(sorted((vals[i], vals[i + 1])))
                     for i in range(0, len(vals), 2)]
        if not pairs:
            raise ValueError('空区间')
        return tuple(sorted(pairs))        # ★ 按下界升序 ✓（日志稳定 ✓）
    except Exception as e:
        logger.warning(f'入场区间 {raw!r} 非法 ✗（{e}）⇒ 回落默认 {dflt} ✓')
        return dflt


def resolve_entry_range(raw, default: Tuple[float, float] = DEFAULT_ENTRY_RANGE) -> Tuple[float, float]:
    """解析入场区间 ✓（**单段兼容版** ✓ = 取多段的**第一段** ✓）；**非法 ⇒ 回落默认** ✓

    ⚠️ 保留本函数只为**旧调用方 / 旧测试** ✓（`[21, 30]` ⇒ `(21.0, 30.0)` ✓）；
      需要多段能力 ⇒ 用 `resolve_entry_ranges` ✓。
    """
    return resolve_entry_ranges(raw, (tuple(default),))[0]


def entry_allowed_by_range(state: Optional[AdxState],
                           low: Optional[float] = None,
                           high: Optional[float] = None,
                           enforce_upper: bool = True,
                           check_range: bool = True) -> bool:
    """★ **个股入场（区间口径 ✓）**：`low < adx(T-1) < high` ✓ **且** `dir(T-1) = 上升` ✓

    ★【2026-09-28 用户口径 ✓】（原话）：**`21 < ADX < 30` 且 `dir = 上升`；阈值可调；
    **没有缓冲**；**反转（日）不参与** ✗**。

    ⚠️ 与 `band` 口径的**根本差别** ✗✓：
      · **不看 `band`** ✗ ⇒ **没有缓冲带 / 迟滞** ✗（`21` / `30` 是**原值硬边界** ✓）；
      · ⇒ **反转日无从生效** ✗✓（它本来的作用只是"不吃缓冲"✓；无缓冲时该规则**恒等价** ✓）；
      · **新增上界** ✓（`adx ≥ 30` **不放行** ✗）—— ⚠️ 与大盘"高位守门"（`≥40` ⇒ 震荡 ✓）
        **不是**一回事 ✗：这是**更早**的天花板 ✓（趋势**过热/过强 ⇒ 不追** ✓），而大盘是
        "高位 + 方向转弱 ⇒ 防守" ✓；
      · `dir` 口径**不变** ✓（两日同向 ＋ 没方向沿用 ✓）。

    Args:
        low/high: 阈值 ✓（`None` ⇒ 用 `DEFAULT_ENTRY_RANGE` ✓；**开区间** ✓）
    """
    # ★【2026-09-29】委托**多段版** ✓（单段 = 一段的特例 ✓ ⇒ 语义与旧实现**逐位一致** ✓）
    lo = DEFAULT_ENTRY_RANGE[0] if low is None else low
    hi = DEFAULT_ENTRY_RANGE[1] if high is None else high
    return entry_allowed_by_ranges(state, ((lo, hi),), enforce_upper=enforce_upper,
                                   check_range=check_range)


def entry_allowed_by_ranges(state: Optional[AdxState],
                            ranges=None,
                            enforce_upper: bool = True,
                            check_range: bool = True) -> bool:
    """★ **个股入场（多段区间口径 ✓）**：`dir(T-1)=上升` ✓ 且 `ADX(T-1)` **落入任一段** ✓

    ★【2026-09-29 用户口径 ✓】（原话）："我希望扩大个股放行买入的区间：
      `15<ADX<18 ∪ 23<ADX<42`" ⇒ **两段并集** ✓ `(15,18) ∪ (23,42)` ✓ ——
      ⚠️ 中间 **`18 ≤ ADX ≤ 23` 仍拒** ✗（**不是**连续区间 ✗）。

    ⚠️ 与单段版的语义 ✓：**命中任一段即放行** ✓（**并集** ✓，不是交集 ✗）；
      ⚠️ 比较仍是**开区间** ✓（`lo < v < hi` ✓ ⇒ 端点本身**不含** ✗，与旧口径一致 ✓）——
        故"`15<ADX<18`"⇒段 `(15,18)` ✓、"`23<ADX<42`"⇒段 `(23,42)` ✓。

    ★★【2026-09-29 用户口径 ✓】**加仓 ⇒ `check_range=False`** ✗→✓ ★★
      用户原话 ✓："**加仓只检查 dir 为上升**" ✓ ⇒ 加仓时**完全不校验 ADX** ✗✓
      （**不看区间 ✗、不看上界 ✗、也不看下界 ✗** ⇒ 只要 `dir=上升` 即放行 ✓）；
      ⚠️ 与旧档 `enforce_upper=False`（"**只豁免上界、下界仍管**"✗）**不是一回事** ✗✓：
        `enforce_upper=False` **保留** ✓（A/B 与旧测试用 ✓），但**加仓**现在走 `check_range=False` ✓
        ⇒ 两个参数**同时传**时 `check_range=False` **优先** ✓（先返回 ✓）。

    Args:
        ranges: 段集合 ✓（`None` ⇒ `DEFAULT_ENTRY_RANGES` ✓）
        enforce_upper: **仅 `check_range=True` 时有效** ✓ —— `False` ⇒ 忽略上界（旧档 ✓）
        check_range: `False`（**加仓专用 ✓**）⇒ **跳过整个 ADX 校验** ✗✓（只看 `dir` ✓）
    """
    if state is None or state.dir != DIR_UP:
        return False                    # ★ 硬条件 ✓（与档位口径一致 ✓、不可配置 ✓）
    # ★ 加仓 ✓：**只看方向** ✓（用户 2026-09-29 口径 ✓）—— 直接放行 ✓，不读 ADX ✓
    if not check_range:
        return True
    a = getattr(state, 'adx', None)
    if a is None:
        return False
    try:
        v = float(a)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(v):
        return False
    for lo, hi in (ranges or DEFAULT_ENTRY_RANGES):
        lo, hi = float(lo), float(hi)
        if v <= lo:
            continue                    # 未达本段下界 ⇒ 看下一段 ✓
        if not enforce_upper or v < hi:
            return True
    return False


def allows_entry(state: Optional[AdxState]) -> bool:
    """**放行判定** ✓ —— 默认口径 ✓（§5.6 ✓）

        `dir(T-1) = 上升` ✓ **且** `band(T-1) ∈ DEFAULT_ENTRY_BANDS`（= 只放「明确」✓）

    ⚠️ 本函数**只看 ADX 状态** ✗✓ —— **不看**浮动盈亏 / 持仓 / 成本 ✗
    （加仓与首仓**同一判据** ✓，见 §5.6 ✓）。
    ⚠️ 数据故障（`missing` ✗）与预热不足 ✗ **由调用方**在调用前拦掉 ✓（本函数不做归因 ✓）。
    ★【2026-09-28】委托 `entry_allowed` ✓ —— 与大盘**同一判据** ✓（杜绝两份口径 ✗）。
    """
    return entry_allowed(state, DEFAULT_ENTRY_BANDS)


# ------------------------------------------------------------------ 有状态封装

class AdxStateTracker:
    """**逐日推进**的封装 ✓（回测/实盘循环里用 ✓，避免手工传 state ✓）

    典型用法（回测逐日 ✓；每股一个实例 ✓）：

        t = AdxStateTracker()
        for date in trading_days:              # 升序 ✓
            st = t.update(adx_of(date))        # 缺数据传 None ⇒ 状态不变 ✓
            if t.allows_entry: ...

    预热 ✓：起点前须先按 ADX 全历史 `update` 一遍 ✓（状态路径依赖 ✓）。
    """

    __slots__ = ('_state', '_kwargs')

    def __init__(self, **kwargs):
        self._state = AdxState()
        self._kwargs = kwargs

    @property
    def state(self) -> AdxState:
        return self._state

    @property
    def band(self) -> str:
        return self._state.band

    @property
    def dir(self) -> str:
        return self._state.dir

    @property
    def cooled(self) -> bool:
        return self._state.cooled

    @property
    def allows_entry(self) -> bool:
        return allows_entry(self._state)

    def update(self, adx: Optional[float]) -> AdxState:
        """推进一日 ✓（缺数据 ⇒ 状态不变 ✓）"""
        self._state = step(self._state, adx, **self._kwargs)
        return self._state

    def reset(self) -> None:
        """清空状态 ✓（**换股/换起点必须调** ✓ —— 否则状态会被上一只股污染 ✗✓）"""
        self._state = AdxState()
