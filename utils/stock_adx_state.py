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
　　 **且 ② `dir=上升`** ✓（**含 ε 防抖** ✓）
其余一律**拒绝** ✗（含 `band∈{震荡,萌芽}` ✓、`dir∈{下降,未定}` ✓）。

★ `cooled`（降温）**不是独立条件** ✗✓ —— 它**只把 `band` 压成「震荡」** ✓
（于是 `≥25 且上升` **本身就排除了回落** ✓，见 §5.6 ✓）。

## 三态递推（`f(今日值, 前一日状态)` ✓）

| 状态 | 规则 |
|---|---|
| `band` | 升档需 `adx ≥ 新档下界 + buffer`；降档需 `adx < 当前档下界 − buffer`；否则**保持** • **回落中的「反转日」⇒ 按当日 `adx` 原值直判**（**不吃 buffer** ✓，条件见 `is_mid_reversal` ✓：(a) 曾见 `>40` ✓ 或 (b) 迟滞正托住更高档 ✓）• `cooled` 时**强制「震荡」**（**最高优先** ✓） |
| `dir`  | `Δ=adx[T]−adx[T-1]`：`Δ > +ε` ⇒ 上升；`Δ < −ε` ⇒ 下降；**`|Δ| ≤ ε` ⇒ 保持前一日**（防抖 ✓）|
| `cooled` | 进入：峰值日 `adx[T-2] > peak`（40）且**连降两日** ⇒ 压成「震荡」• 退出：**连升两日**（T-2 < T-1 < T ✓，**无水平门槛** ✓）⇒ 解除（"回落易、恢复难" ✓）|

⇒ **解除后以「震荡」为基准重新起算** ✓（不追溯"被压之前"的档位 ✗），
   因为 `cooled` 期间 `band` 字段本身就是「震荡」✓。

## 边界（易错 ✗✓）

· **判据是"档位"不是"数值"** ✗✓：因迟滞 ✓，`band=明确` **≠** `adx ≥ 25`
  —— 例 `26 → 24.2`：`24.2 ≥ 25−1 = 24` ⇒ **仍为「明确」** ✓（初稿按 `≥25` 会拒绝 ✗）
· **降档是严格小于** ✓：`adx < 下界 − buffer`（`24.0` **不算**跌破 ✗ ⇒ 保持「明确」✓）
· **升档非严格** ✓：`adx ≥ 下界 + buffer`（`21.0` 恰好 ⇒ 升「萌芽」✓）
· **`dir` 翻转是严格大于** ✓：`|Δ| ≤ ε` 一律**保持** ✓
· **反转日不吃 buffer** ✗✓（**2026-09-27 用户口径** ✓）：**正常换挡有 buffer** ✓ ——
  唯独「**回落中出现中间反转**（`dir` 转「上升」✓）」的那一天 ✓，
  `band` **直接按当日 `adx` 原值判定** ✓（等价 `buffer=0` ✓）。判据见 `is_mid_reversal` ✓：
  (a) 曾见 `> peak`(40) ✓（**高位回落** ✓）**或** (b) **迟滞正托住更高档** ✓。
  ⇒ 否则迟滞会把"**回落前的旧高档**"**继续托住** ✗：例 `25.6 → 24.9`
  （`Δ=−0.7 ≤ ε` ⇒ `dir` 仍「上升」✓、`24.9 ≥ 25−1 = 24` ⇒ `band` 仍「明确」✗）
  ⇒ 与"`dir`=上升"组合成 **误放行** ✗✓（实测可构造 ✓，见 `TestMidReversalNoBuffer` ✓）。
  ⚠️ **只收紧不放宽** ✓（(b) 恒为降档方向 ✓）；实测 80 只 / 85942 日：
  **收紧 44 次 / 放宽 0 次** ✓（只留 (a) 时**零命中** ✗ ⇒ (b) 不可省 ✗）。

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

参数（`epsilon` 为**工程噪声门槛** ✗ 非策略阈值 ✓；**已按实测分布标定** ✓
= **`0.75`** ✓，见 `DIRECTION_EPSILON` 注释与设计文档 §9 Q7 ✓）。
"""
import math
from dataclasses import dataclass, replace
from typing import Iterable, List, Optional, Tuple

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

#: 降温触发峰值门（`adx[T-1] > PEAK` 且连降两日 ✓；与 §5.8 一致 ✓）
COOLED_PEAK: float = 40.0

DIR_UP = '上升'
DIR_DOWN = '下降'
DIR_UNKNOWN = ''


# ------------------------------------------------------------------ 数据结构

@dataclass(frozen=True)
class AdxState:
    """个股 ADX 状态快照（**不可变** ✓ == 比较可用 ✓ —— 可复现性测试依赖它 ✓）

    Attributes:
        band: 档位（`震荡`/`萌芽`/`明确`；未预热时为 `''` ✓）
        dir: 方向（`上升`/`下降`；未定/首日/预热不足为 `''` ✓）
        cooled: 是否处于降温态 ✓（True ⇒ `band` 被压成「震荡」✓）
        adx: 本日 ADX（`adx[T]` ✓）
        prev_adx: 前一日 ADX（`adx[T-1]` ✓）—— 用于判定"连降/连升两日" ✓
        fell_from_high: 此前是否**见过 > `peak`(40)** ✓（2026-09-27 新增 ✓）——
            供"**从 40+ 一路回落到 20~25 且方向不变 ⇒ 仍判震荡**"这条进入条件用 ✓；
            **解除降温时清零** ✓（否则旧"高位史"会永久生效 ✗）
        reason: ★ **本步的判定依据** ✓（2026-09-27 用户要求"判定依据打印到日志" ✓）——
            **人话一行** ✓：为什么进入/保持/解除降温 ✓、是否走了"反转日按原值" ✓、
            迟滞是保持还是切换 ✓
    """
    band: str = ''
    dir: str = ''
    cooled: bool = False
    adx: Optional[float] = None
    prev_adx: Optional[float] = None
    fell_from_high: bool = False
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


def is_mid_reversal(dir_state: str, fell_from_high: bool,
                    current_band: str = '', adx: Optional[float] = None,
                    thresholds: Tuple[float, float] = BAND_THRESHOLDS,
                    labels: Tuple[str, str, str] = BAND_LABELS) -> bool:
    """**反转日 ⇒ 按当日 `adx` 原值判档** ✓（**2026-09-27 用户口径** ✓）

    · 「**反转**」✓ = 当日方向为**上升** ✓（含 `ε` 防抖 ✓ ⇒ `|Δ| ≤ ε` 的小反弹**不算** ✗）；
    · 「**回落中**」✓ = 满足**任一**：
        a) `fell_from_high` ✓ —— 曾观测到 `adx > peak`(40) ✓（= 字面的「**高位回落**」✓）；
        b) **迟滞正托住更高档** ✗✓ —— 当日**原值档更低** ✓、却被 `current_band` **滞留** ✗
           （`_lower_bound(原值) < _lower_bound(current_band)` ✓）。
    ⇒ 命中日 `band` **不吃缓冲带** ✗✓ —— **直接按当日 `adx` 原值**判定 ✓。

    ⚠️ **为何必须有 (b)** ✗✓（**实测** ✓，2026-09-27 ✓）：只留 (a) 时在**真库零命中** ✗——
      80 只 / 85942 日实测 ✓：档位变化 **0 日**✗。原因 ✓：`fell_from_high` 存在时，
      跌进 `[20,25)` 的**下降日**已被**余波回落（规则 ②）**压成「震荡」✗ ⇒
      根本走不到"迟滞托住「明确」"那一步 ✓；而**能**托住的那些日 ✓ 恰恰 `fell_from_high` 为假 ✗。
      ⇒ 补上 (b) 后 ✓：档位变化 **75 日** ✓、**收紧放行 44 次** ✓、**放宽 0 次** ✓✓。

    ⚠️ **本规则只可能收紧** ✗✓：(b) 恒为**降档方向** ✓（`明确→萌芽` ✓ / `萌芽→震荡` ✓）⇒
      绝不会因它而"提前升档放行" ✗（(a) 理论上可影响升档 ✓，但实测放宽 **0** 次 ✓）。

    ⚠️ 优先级 ✗✓：`cooled`（降温）**仍最高** ✓ —— 反转日**不得**解封降温 ✗
      （解除另有硬门：**连升两日** ✓，见 `step` ✓）。
    """
    if str(dir_state or '') != DIR_UP:
        return False
    if fell_from_high:
        return True
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
         peak: float = COOLED_PEAK) -> AdxState:
    """按**一个交易日**推进状态 ✓（`f(今日值, 前一日状态)` ✓）

    Args:
        state: 前一日状态（`None` / `AdxState()` ⇒ 视为**未预热** ✓）
        adx: 今日 `adx[T]` ✓（须为**已确认**的收盘后值 ✓，防前视 ✓）
        band_thresholds: 档位下界 ✓（默认 `(20, 25)` ✓）
        band_buffer: 迟滞宽度 ✓（默认 `1.0` ✓）
        epsilon: 方向防抖 `ε` ✓（默认 **`0.75`** ✓ = **已标定值** ✓，见 `DIRECTION_EPSILON` 注释 ✓）
        peak: 降温触发峰值门 ✓（默认 `40` ✓）

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

    # ---- ② 方向（ε 防抖 ✓）----
    d = st.dir
    if prev is not None:
        delta = a - prev
        if delta > epsilon:
            d = DIR_UP
        elif delta < -epsilon:
            d = DIR_DOWN
        # |Δ| ≤ ε ⇒ **保持前一日方向** ✓（这是防抖的关键 ✗✓）

    # ---- ③ 降温态（只改写 band ✓，**不**独立否决 ✗）----
    cooled = st.cooled
    # ★ **见过 40+** ✓（2026-09-27 新增 ✓）：一旦观测到 `adx > peak` 即置位 ✓，
    #   在**真反转解除**降温时清零 ✓（见下方退出分支 ✓）
    fell_from_high = st.fell_from_high or (a > peak)
    # ---- ④ 判定依据（人话 ✓，**只用于日志** ✗）----
    reasons: List[str] = []
    if a > peak and not st.fell_from_high:
        reasons.append(f'首次见 {a:g} > 峰值门 {peak:g} ⇒ 置"曾见高位"✓')
    if prev is not None and grand is not None:
        if not cooled:
            # 进入 ①（原有 ✓）：**从 peak（40）以上回落** ✓ —— 连降两日（T-2 > T-1 > T ✓）
            #   ⚠️ **口径更正** ✗→✓（2026-09-27 用户澄清 ✓）：
            #     原实现写 `adx[T-1] > peak` ✗ = 要求"回落**第二天仍在 40 以上**"✗ ——
            #     那**不是**规格的原意 ✓；规格只说"**从 40+ 回落**"✓
            #     ⇒ 锚点应是**峰值日（= 回落起点 T-2）** ✓，不是 T-1 ✗。
            #   ★ **真实案例（实测）** ✗✓：大盘 2025-04-18 峰值 **40.02** ✓、次日 **39.88** ✗
            #     ⇒ 旧口径**永不触发** ✗（差 **0.12** 点 ✗），而按"从 40+ 回落"**应触发** ✓。
            if grand > peak and prev < grand and a < prev:
                cooled = True
                reasons.append(f'降温进入①：{grand:g} 见顶后连降两日'
                               f'（{grand:g}→{prev:g}→{a:g}）⇒ 压成「震荡」')
            # 进入 ②（**2026-09-27 用户新增** ✗✓）：**从 40+ 一路回落到 `[20, 25)` 区间、
            #   且回落方向不变** ⇒ **仍判「震荡」** ✓（**不**判「萌芽」✗ —— 萌芽含"趋势新起"之意 ✓）
            #   · 为何需要它 ✗✓：进入 ① 要求**在顶部就"连降两日"** ✓；若顶部有一个小幅上翘 ✗
            #     （如 `42 → 39 → 40 → 38` ✓）⇒ ① 不成立 ✗ ⇒ 这波回落会**一路被判成「萌芽」** ✗。
            #   · 判据 ✓：`fell_from_high`（见过 > 40 ✓）+ **今日方向仍是下降** ✓（`d` ✓，
            #     含 `ε` 防抖 ✓ = "回落方向不变"✓）+ 今日 ADX 落在 **[20, 25)** ✓。
            elif (fell_from_high and d == DIR_DOWN
                  and band_thresholds[0] <= a < band_thresholds[1]):
                cooled = True
                reasons.append(f'降温进入②：曾见 >{peak:g} 且仍下降、'
                               f'{a:g} 落在[{band_thresholds[0]:g},'
                               f'{band_thresholds[1]:g}) ⇒ 压成「震荡」')
        else:
            # 退出 ✓（**2026-09-27 用户口径更正** ✗→✓）：**只要求"连升两日"** ✓（T-2 < T-1 < T）
            #   ⚠️ 原实现还要求 `adx[T-1] > 25` ✗ —— **用户明确：没有这个条件** ✗✓。
            #   ★ **实测代价** ✗✓（大盘 2026）：08-05 进入降温后，09-03~09-17 多次**连升两日** ✓
            #     却因 `T-1 ≤ 25` ✗ 一直解不掉 ⇒ **09-15（ADX 23.58 ✓ 已连升三日 ✓）被压成「震荡」**✗
            #     （其原值档是「萌芽」✓）—— 正是用户指出的那一日 ✓。
            #   ⇒ 而该门槛当年的理由（"否则低位反弹两日会被判**明确**"✗）**已不成立** ✓✓：
            #     2026-09-27 起"解除后**交回正常分档**"✓（**不再强制「明确」**✗）——
            #     低位解除至多得**震荡/萌芽** ✓，**不可能**凭空判「明确」✗。
            if prev > grand and a > prev:
                cooled = False
                fell_from_high = False        # ★ 解除 ⇒ **清零** ✓（否则旧"高位史"永久生效 ✗）
                reasons.append(f'降温解除：连升两日（{grand:g}→{prev:g}→{a:g}）'
                               f'⇒ 交回正常分档 ✓')

    # ---- ① 档位（迟滞 ✓；**反转日 ⇒ 按当日原值** ✓；降温 ⇒ 压成「震荡」✓）----
    #   注 ✓：`st.band` 在降温期间**就是**「震荡」⇒ 解除后自然以「震荡」为基准重新起算 ✓
    #   ★【2026-09-27 用户口径 ✓】**正常换挡有 buffer** ✓；**高位回落中的「中间反转」**
    #      ⇒ **按反转日的 `adx` 直接判定** ✓ ⇒ 仅该日令 `buffer=0.0`
    #      （`buffer=0` ⇒ 升档门 `a ≥ raw_low` 恒真 ✓、降档门 `a < cur_low` 必真 ✓
    #       ⇒ **恰好等价于** `band_of(a)` 原值直判 ✓）
    mid_reversal = is_mid_reversal(d, fell_from_high, st.band, a,
                                   band_thresholds)
    if mid_reversal:
        reasons.append(f'反转日：dir={d} ✓ 且"回落中"✓ ⇒ 按当日原值 {a:g} 直判、'
                       f'不吃 ±{band_buffer:g} 缓冲（步进前档='
                       f'{st.band or "未预热"}）')
    band_hyst = apply_hysteresis(a, st.band, thresholds=band_thresholds,
                                 buffer=(0.0 if mid_reversal else band_buffer))
    band = band_hyst
    if cooled:
        band = BAND_RANGE                      # ★ 降温仍是**最高**优先 ✓（反转日也不解封 ✗）
        if band_hyst != BAND_RANGE:
            reasons.append(f'降温中：迟滞档「{band_hyst}」被**强制**为「震荡」✗')
    elif band and band != st.band:
        reasons.append(f'迟滞切换：「{st.band or "未预热"}」→「{band}」'
                       f'（升档需 ≥ 下界+{band_buffer:g}／降档需 < 下界−{band_buffer:g}）')
    elif band:
        reasons.append(f'迟滞保持「{band}」')

    return AdxState(band=band, dir=d, cooled=cooled, adx=a, prev_adx=prev,
                    fell_from_high=fell_from_high,
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

def allows_entry(state: Optional[AdxState]) -> bool:
    """**放行判定** ✓ —— 唯一判定式 ✓（§5.6 ✓）

        `band(T-1) = 明确` ✓ **且** `dir(T-1) = 上升` ✓

    ⚠️ 本函数**只看 ADX 状态** ✗✓ —— **不看**浮动盈亏 / 持仓 / 成本 ✗
    （加仓与首仓**同一判据** ✓，见 §5.6 ✓）。
    ⚠️ 「回落」**不单列** ✗✓ —— `cooled` 已把 `band` 压成「震荡」⇒ 此处 ① 自然失败 ✓。
    ⚠️ 数据故障（`missing` ✗）与预热不足 ✗ **由调用方**在调用前拦掉 ✓（本函数不做归因 ✓）。
    """
    if state is None:
        return False
    return state.band == BAND_TREND and state.dir == DIR_UP


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
