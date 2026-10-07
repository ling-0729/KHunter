# -*- coding: utf-8 -*-
"""**大盘（指数）ADX 闸门** ✓ —— **只在「首仓」买入前**检查 ✗→✓（2026-09-28 用户要求 ✓）

用户口径 ✓（2026-09-28 原文 ✓）：

> 处理买入（**首次买入，不含加仓** ✗）前，增加检查：**大盘条件（ADX>25 且 dir 上升）**
> 25 作为参数，**可以设置** ✓。

## 唯一规则：**当日仓位上限** ✓（首仓；2026-09-28 用户**最终口径** ✓）

> ⚠️ **原「大盘 ADX 硬闸门」（`ADX>25 ∧ dir上升` 才许开首仓）已整体取消** ✗
> （用户 2026-09-28 ✓："**这个规则取消，由仓位上限总控**" ✓）——
> 其职责已由下表「**其他 ⇒ 0%**」档承担 ✓，且**更贴合用户规则** ✓
> （`ADX<18 ∧ 上升` 现在**允许**开仓、只是限 50% ✓ —— 硬闸门在时它被整段挡死 ✗）。

| 档 ✓ | 条件 ✓ | 上限 ✓ |
|---|---|---|
| 规则1 ✓ | `ADX > 25` ∧ `dir=上升` ✓ | **100%** ✓ |
| 规则2 ✓ | `ADX < 18` ∧ `dir=上升` ∧ ★**指数收盘 > MA20** ✓ | **50%** ✓ |
| 其他 ✓ | `18≤ADX≤25` ✗ / `dir≠上升` ✗ / ★**ADX<18 但收盘 ≤ MA20** ✗ / 缺数据 ✗ | **0% ⇒ 不允许开仓** ✓ |

★ **规则2 的「收盘 > MA20」附加条件** ✓（2026-09-30 用户要求 ✓）：
用户原话 ✓："大盘仓位控制规则：**adx<18 时增加条件，dir 上升，而且 >ma20**" ✓。
· 只加在**规则2** ✗✓（规则1 `ADX>25` **不受影响** ✓）；
· 数据源 ✓：`market_index_adx.close` ✓ —— 与 ADX **同一张表** ✓（⇒ 零联网 ✓、无需新增采集 ✓、
  与 ADX 状态**同一 T-1 纪律** ✓ 不可能漂移 ✗）；
· ⚠️ **MA 不足 20 根 ⇒ 保守**（落兜底 ✓，与"缺数据 ⇒ 0%"同取向 ✓）；
· 可关 ✓（`index_cap_low_require_above_ma: false` ⇒ **旧行为** ✓，供 A/B 对比 ✓）。

⇒ **持仓 ≥ 上限 ⇒ 停止开新仓** ✓；**加仓不受限** ✓；
⚠️ 比较符用 **`≥`**（不是 `>` ✓ —— 上限 `0%` 时 `>` 会让**空仓反能开仓** ✗，见常量注释 ✓）。

⚠️ **本规则是"开新仓"的唯一大盘判据** ✓（硬闸门已取消 ✗ ⇒ 不存在两套口径相冲 ✓）。

## 边界（都是用户明确口径 ✓）

- ⚠️ **只对首仓** ✓（**加仓不检查** ✗ —— 加仓由择时策略自身条件把关 ✓）；
- ⚠️ **防前视** ✓：只用到 **T-1 及之前** ✓（与个股闸门同口径 ✓）；
- ⚠️ **数据缺失 / 预热不足** ⇒ **保守拒绝** ✓（与个股闸门一致 ✓），但**必须明确归因** ✓
  （日志能看出是"没数据"✗ 还是"条件不满足"✓ —— 实测踩过"闸门不通过却看不到数值"✗）；
- ⚠️ **阈值/指数/方向口径/开关/各档上限都可配** ✓（见下 ✓）。

## 配置（`config/backtest_engine_config.yaml` ✓，与其它 ADX 参数同一处 ✓）

| 键 ✓ | 默认 ✓ | 说明 ✓ |
|---|---|---|
| `enable_index_position_cap` ✓ | **关** ✗（`adx` 预设 **开** ✓） | ★ **仓位上限总开关** ✓ |
| `index_cap_high_adx` / `index_cap_high_ratio` ✓ | **25** / **100%** ✓ | 规则1 ✓ |
| `index_cap_low_adx` / `index_cap_low_ratio` ✓ | **18** / **50%** ✓ | 规则2 ✓ |
| ★ `index_cap_low_require_above_ma` ✓ | **开** ✓ | 规则2 是否**加**「收盘 > MA20」✓（关 ⇒ 旧行为 ✓） |
| ★ `index_cap_ma_period` ✓ | **20** ✓ | MA 周期 ✓（2~250 ✓，非法回落 20 ✓） |
| `index_cap_other_ratio` ✓ | **0%** ✓ | ★ 其他情况 ⇒ **不允许开仓** ✓ |
| `index_adx_code` ✓ | `regime_router.yaml` 的 `index_code` ✓ ⇒ `000985.CSI` ✓ | 看哪个指数 ✓ |
| `index_adx_dir_mode` ✓ | 回落 `adx_dir_mode` ✓ ⇒ `two_day` ✓ | 方向口径 ✓ |

⇒ 优先级 ✓ 与全库一致 ✓：请求 `config` ✓ > yaml 顶层 ✓ > yaml `backtest:` 节 ✓ >
`backtest_mode` 预设 ✓ > 默认 ✓（**同一入口** `utils.backtest_mode.effective` ✓）。
"""
import bisect
import logging
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 指数代码兜底 ✓（与 `MarketIndexADX.DEFAULT_INDEX_CODE` ✓ / `regime_router.yaml` 一致 ✓）
DEFAULT_INDEX_CODE = '000985.CSI'
# ★★【2026-09-28 用户口径 ✓】**原「大盘 ADX 硬闸门」已整体取消** ✗✓ ★★
#   用户原话 ✓："上一轮的『大盘 ADX 首仓闸门』（`ADX>25 ∧ dir上升` 才许开首仓）**这个规则取消**，
#   **由仓位上限总控**" ✓。
#   ⇒ 本模块**不再有**：`enable_index_adx_filter` ✓ / `index_adx_entry_threshold` ✓ /
#     `index_adx_entry_gate` ✓ / `format_index_gate_result` ✓ /
#     `describe_index_adx_params` ✓ / `conflict_note` ✓
#     ⇒ **开新仓的唯一大盘判据 = 仓位上限**（`index_position_cap*` ✓）。
#   ⚠️ 职责去向 ✓（**不是简单删掉、而是被覆盖** ✓）：硬闸门当初挡的是"非 `ADX>25 ∧ 上升`"
#     的日子 ✗ ⇒ 该职责现由**仓位上限的「其他 ⇒ 0%」档**承担 ✓；
#     且**更贴合用户规则** ✓：`ADX<18 ∧ 上升` 现在**允许**开仓、只是**限 50%** ✓
#     （硬闸门在时它被整段挡死 ✗ —— 实测 **136 天** ✗，正是取消它的原因 ✓）。

# ★★【2026-09-28 用户**最终口径** ✓】**当日仓位上限** ✓（买入前判定 ✓；**只约束"开新仓"** ✗加仓）★★
#   规则 ✓（用户原文 ✓，**完备无缺档** ✓）：
#     · 大盘 `ADX > 25` **且** `dir 上升` ⇒ 仓位上限 **100%** ✓
#     · 大盘 `ADX < 18` **且** `dir 上升` **且** ★**指数收盘 > MA20** ⇒ 仓位上限 **50%** ✓
#       ★【2026-09-30 用户要求 ✓】附加条件 ✓（用户原话："adx<18 时**增加条件**，
#         dir 上升，而且 **>ma20**" ✓）—— 只加在规则2 ✗✓（规则1 **不受影响** ✓）
#     · **其他情况 ⇒ 仓位上限 0 ⇒ 不允许开仓** ✓（`18≤ADX≤25` ✗ / `dir≠上升` ✗ /
#       ★ `ADX<18` 但**收盘 ≤ MA20** ✗ / 缺数据 ✗）
#     · **持仓 ≥ 上限** ⇒ **停止开新仓** ✓（**可以加仓** ✗✓）
#   ⚠️⚠️ **比较符必须是 `≥`（不是 `>`）** ✗✓（**实测推出的硬约束** ✓）：
#     用户原话是"持仓 > 上限"，但**上限 = 0%** 时 `>` 会让 **空仓（持仓=0）反而能开仓** ✗✗
#     ⇒ 与"其他情况**不允许开仓**"✗ **直接矛盾** ✗。故统一用 `≥`：
#       · 上限 `0%` ✓ ⇒ **一律不开新仓** ✓（含空仓 ✓ —— 这正是"不允许开仓" ✓）；
#       · 上限 `50%` ✓ ⇒ 持仓 `≥ 50%` 即停 ✓；
#       · 上限 `100%` ✓ ⇒ 持仓 `≥ 100%` 才停 ✓。
#   ⚠️ 判定用 **T-1** 状态 ✓（防前视 ✓，与大盘闸门**同一份状态** ✓ `_state_at` ✓）。
DEFAULT_INDEX_POSITION_CAP = False           #: 总开关默认**关** ✗（`adx` 模式预设 **开** ✓）
DEFAULT_CAP_HIGH_ADX = 25.0                  #: 规则1 ✓：ADX **> 25** ✓（严格 ✓）
DEFAULT_CAP_HIGH_RATIO = 1.0                 #: 规则1 ✓：上限 **100%** ✓
DEFAULT_CAP_LOW_ADX = 18.0                   #: 规则2 ✓：ADX **< 18** ✓（严格 ✓）
DEFAULT_CAP_LOW_RATIO = 0.5                  #: 规则2 ✓：上限 **50%** ✓
#: ★★【2026-09-30 用户要求 ✓】规则2 的**附加条件** ✓：指数**收盘价 > MA20** ✓（默认**开** ✓）
#:   用户原话 ✓："大盘仓位控制规则：**adx<18 时增加条件，dir 上升，而且 >ma20**" ✓
#:   ⚠️ 置 `false` ⇒ **旧行为** ✓（`ADX<18 ∧ dir上升` 即 50% ✓）—— 供 **A/B 对比** ✓
DEFAULT_CAP_LOW_REQUIRE_ABOVE_MA = True
#: ★★【2026-10-07 用户口径 ✓】**大盘档位用「信号日当天收盘」判** ✗→✓ ★★
#:   用户原话 ✓①："实盘模式下，应该根据**当日收盘的 adx** 判定仓位，**现在是 t-1 的**" ✓
#:   用户原话 ✓②（时序定稿 ✓）："**T 日出信号，T+1 实盘时按即时价格成交**，
#:     **和回测一致**，信号的价格只是参考价" ✓
#:   ⇒ 两边**本质是同一条** ✗✓（都是"**用信号日当天收盘**"✓）：
#:     · **回测** ✓：信号日 = **T−1** ✓（`current_date` 是执行日 T ✓，内部取"严格早于 T"= T−1 ✓），
#:       成交 = **T 日开盘价** ✓；
#:     · **实盘** ✓：信号日 = **T** ✓，成交 = **T+1 即时价** ✓。
#:   ⇒ 所以本键的准确语义是"**用信号日当天（而不是它的前一天）**" ✓✓
#:     —— 别再读成"实盘就比回测晚一天用数据"✗（那会以为两套口径不一致 ✗）。
#:   · ⚠️ 默认 **`False`** ✓＝"取信号日的前一根" ⇒ 这是**回测**口径 ✓（回测不注入 ✓ ⇒ 零回归 ✓）；
#:     实盘侧在**未显式**时注入 `True` ✓（见 `strategy_runner` ✓，用 `is_explicit` 判 ✓，不硬覆盖 ✗）；
#:   · 置 `false` ⇒ 实盘**回到"取前一根"** ✓（A/B 对比用 ✓）。
DEFAULT_CAP_USE_SIGNAL_DAY = True

#: ★ MA 周期 ✓（默认 **20** ✓；`>MA20` 是用户原话 ✓）—— 非法（<2 / >250）⇒ 回落 20 ✓
DEFAULT_CAP_MA_PERIOD = 20
DEFAULT_CAP_OTHER_RATIO = 0.0                #: ★ 兜底 ✓ ⇒ **0% = 不允许开仓** ✓（用户口径 ✓）
#:   ⚠️ 规则2 的**附加条件不满足**（`ADX<18` 但收盘 ≤ MA20 ✓ / MA 不足 ✓）**也落本档** ✓
#:     —— 与"缺数据 ⇒ 不允许开仓"**同取向** ✓（保守 ✓），且**归因明确** ✓（日志写明是哪一条 ✗✓）
#: ★【2026-09-29 用户要求 ✓】**不开新仓当日是否跳过"选股执行"**（默认 **开** ✓ = 用户现行口径 ✓）
#:   ⚠️ 设 `false` 即**旧行为**（选股/评分照跑、结果置 0 ✓）—— 用于**A/B 对比** ✓
DEFAULT_SKIP_SELECTION_WHEN_BLOCKED = True

#: 全历史状态缓存 ✓（**路径依赖** ✗ ⇒ 逐日回放一次、按日查表 ✓；见 `_series` ✓）
_SERIES_CACHE: Dict[Tuple[str, str], Dict] = {}
#: 表指纹缓存 ✓ + TTL ✓（**实测必需** ✗：指纹本身是一次 DB 往返 ✓ ⇒ 每次判都查
#:   ⇒ 单次 ~5.9ms ✗（实测 2000 次 **11.7s** ✗）⇒ 回测逐日逐票调用会拖成分钟级 ✗✓）。
#:   TTL 30s ⇒ 数据更新（每日采集 ✓）后**最多 30 秒**即自动重建 ✓（实盘安全 ✓）。
_SIG_CACHE: Dict[str, Tuple[float, Tuple]] = {}
_SIG_TTL = 30.0
#: 兜底指数代码缓存 ✓ + TTL ✓（**实测必需** ✗：见 `_yaml_index_code` ✓）
_CODE_CACHE: Dict[str, Tuple[float, str]] = {}
_CODE_TTL = 60.0
#: ★【2026-09-30 用户要求 ✓】指数**收盘价**序列缓存 ✓（**同一张表 `market_index_adx`** ✓
#:   同一**表指纹** ✓ ⇒ 数据一更新自动重建 ✓，与 ADX 状态**永不漂移** ✗✓）—— 供规则2 `>MA20` ✓
_CLOSE_CACHE: Dict[str, Dict] = {}


def _load_engine_yaml() -> Dict:
    """读 `config/backtest_engine_config.yaml` ✓（**委派共享加载器** ✓ 单一口径 ✓）"""
    from utils.backtest_mode import load_engine_yaml
    return load_engine_yaml()


def _resolve_bool(config: Optional[Dict], key: str, default: bool) -> bool:
    from utils.backtest_mode import effective
    return bool(effective(key, config, _load_engine_yaml(), default))


def _yaml_index_code() -> str:
    """从 `config/regime_router.yaml` **直接读** `index_code` ✓（**带 TTL 缓存** ✓）

    ⚠️ **实测踩到** ✗✓：原先回落时写 `RegimeRouter().index_code` ✗ ⇒ **每次判定都构造
      一个路由器** ✗（读 yaml + 打日志 ⇒ 单次 **~4.6ms** ✗，20000 次 **92.8s** ✗）
      ⇒ 回测（逐日 × 每只候选 ✗）会被拖垮 ✗。改为**直接读 yaml + 缓存** ✓ ⇒ 微秒级 ✓。

    ⚠️ 仍是**同一事实源** ✓（读的就是路由器那份 yaml ✓）⇒ "路由看 A、闸门看 B"✗ 不会发生 ✓。
    """
    now = time.monotonic()
    hit = _CODE_CACHE.get('code')
    if hit and (now - hit[0]) < _CODE_TTL:
        return hit[1]
    code = DEFAULT_INDEX_CODE
    try:
        import yaml
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / 'config' / 'regime_router.yaml'
        if p.exists():
            cfg = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
            code = str(((cfg.get('regime_router') or {}).get('index_code'))
                       or DEFAULT_INDEX_CODE)
    except Exception as e:
        logger.debug(f'读 `regime_router.yaml` 的 index_code 失败'
                     f'（用 {DEFAULT_INDEX_CODE} ✓）: {e}')
    _CODE_CACHE['code'] = (now, code)
    return code


def resolve_index_adx_code(config: Optional[Dict] = None) -> str:
    """看哪个指数 ✓（默认取 `regime_router.yaml` 的 `index_code` ✓ ⇒ `000985.CSI` ✓）

    ⚠️ 与大盘路由**共用同一指数** ✗✓ —— 否则"路由说明确、闸门看另一个指数"✗ 必然自相矛盾 ✗。
    """
    from utils.backtest_mode import effective
    raw = effective('index_adx_code', config, _load_engine_yaml(), default=None)
    if raw:
        return str(raw).strip()
    return _yaml_index_code()                    # 回落：与大盘路由同一指数 ✓（缓存 ✓）


def resolve_index_adx_dir_mode(config: Optional[Dict] = None) -> str:
    """方向口径 ✓ —— **回落 `adx_dir_mode`** ✓（默认 `two_day` = 连续两日同向 ✓）"""
    from utils.backtest_mode import effective
    from utils.stock_adx_state import resolve_dir_mode
    raw = effective('index_adx_dir_mode', config, _load_engine_yaml(), default=None)
    if not raw:
        raw = effective('adx_dir_mode', config, _load_engine_yaml(), default=None)
    return resolve_dir_mode(raw)


def _load_rows(index_code: str) -> List[Dict]:
    """读**全历史**指数 ADX ✓（升序 ✓）—— **唯一取数口** ✓（测试可只替换它 ✓）"""
    from trading.market_index_adx_dao import MarketIndexADXDAO
    return MarketIndexADXDAO().query_range('19000101', '29991231', index_code) or []


def _signature(index_code: str, ttl: float = _SIG_TTL) -> Tuple:
    """表**指纹** ✓（`COUNT(*) + MAX(trade_date)` ✓）—— 数据一更新（如每日采集 ✓）
    ⇒ 指纹变化 ⇒ **自动重建缓存** ✓✓（否则实盘整天用旧状态 ✗，实测易踩 ✓）

    ⚠️ **必须带 TTL 缓存** ✗✓（**实测** ✓）：指纹是一次 DB 往返 ✓ ⇒ 若每次判定都查 ✗
      ⇒ 单次 ~5.9ms ✗（2000 次 **11.7s** ✗）⇒ 回测（逐日 × 每只候选 × 上千日 ✗）
      会被拖到**分钟级** ✗。TTL **30s** ✓ ⇒ 既快 ✓ 又能让"当日采集完成"在 30 秒内被感知 ✓。
    """
    now = time.monotonic()
    hit = _SIG_CACHE.get(index_code)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    try:
        from trading.market_index_adx_dao import MarketIndexADXDAO
        dao = MarketIndexADXDAO()
        row = dao.db.query_one(
            'SELECT COUNT(*) AS c, MAX(trade_date) AS m FROM market_index_adx '
            'WHERE index_code = ?', (index_code,)) or {}
        sig: Tuple = (int(row.get('c') or 0), str(row.get('m') or ''))
    except Exception as e:                       # 指纹取不到 ⇒ 视为"不稳定"⇒ 每次重建 ✓（安全 ✓）
        logger.debug(f'大盘 ADX 表指纹读取失败（退化为不缓存 ✓）: {e}')
        sig = (None, str(e))
    _SIG_CACHE[index_code] = (now, sig)
    return sig


def _series(index_code: str, dir_mode: str) -> Tuple[List[str], Dict]:
    """**全历史逐日状态** ✓ ⇒ `(日期升序表, {日期: AdxState})` ✓（**带指纹缓存** ✓）

    为什么**不能**"每次只回放一小段" ✗✓：`dir`（**两日同向** ✓）与 `band`（**迟滞** ✓）
      都是**路径依赖** ✗ ⇒ 必须从**数据起点**逐日推进 ✓（与个股闸门"完整回放"同口径 ✓）。
      指数表约 1600 行 ✓ ⇒ 单次回放毫秒级 ✓；之后按日**查表 O(1)** ✓（回测逐日逐票调用 ✓ 才够快 ✓）。

    ⚠️ **同一实现** ✗✓：直接调 `utils.stock_adx_state.step` ✓
      ⇒ 与个股闸门 / `RegimeRouter` **同一状态机** ✓（杜绝"两处各写一份"✗）。
    """
    key = (index_code, dir_mode)
    sig = _signature(index_code)
    hit = _SERIES_CACHE.get(key)
    if hit and hit.get('sig') == sig:
        return hit['dates'], hit['states']

    from utils.stock_adx_state import step as _step
    rows = _load_rows(index_code)
    states: Dict = {}
    st = None
    for r in rows:
        d = str(r.get('trade_date') or '').replace('-', '')[:8]
        try:
            a = float(r.get('adx'))
        except (TypeError, ValueError):
            continue
        st = _step(st, a, dir_mode=dir_mode)     # ★ 同一状态机 ✓（含 band 迟滞 ✓ / dir 两日 ✓）
        if len(d) == 8:
            states[d] = st
    dates = sorted(states)
    _SERIES_CACHE[key] = {'sig': sig, 'dates': dates, 'states': states}
    return dates, states


def clear_index_adx_cache() -> None:
    """清缓存 ✓（测试 / 数据更新后手工刷新 ✓）"""
    _SERIES_CACHE.clear()
    _SIG_CACHE.clear()
    _CODE_CACHE.clear()
    _CLOSE_CACHE.clear()                      # ★ 收盘价序列也要清 ✓（2026-09-30 ✓）


def _state_at(signal_date: str, index_code: str, dir_mode: str,
              use_signal_day: bool = False) -> Dict:
    """取状态 ✓：默认 **严格早于信号日的最后一根**（= **T-1** ✓，防前视 ✓）；
    ★ `use_signal_day=True` ⇒ **信号日当天（T）那根** ✓（**仅实盘**用 ✓，见常量注释 ✓）

    ★ **单一取数口** ✗✓：**仓位上限**（`index_position_cap` ✓）走这里 ✓
      ⇒ 全库"大盘 ADX 状态"只有**一处**取数口径 ✓（口径不可能漂移 ✗✓）。

    ⚠️ `use_signal_day=True` 的**边界** ✗✓：若**没有 T 日那根**（数据未采集 / T 非交易日 ✓）
      ⇒ **回落 T-1** ✓（**保守** ✓，绝不用"未来"那根 ✗，也绝不猜 ✗）。

    Returns:
        `{'state_date','adx','dir','band','error'}` ✓ —— `error` **非空** ⇒ 调用方须**保守处理** ✓
    """
    out = {'state_date': '', 'adx': None, 'dir': '', 'band': '', 'error': ''}
    try:
        dates, states = _series(index_code, dir_mode)
    except Exception as e:                       # 取数/回放异常 ⇒ 交给调用方**保守处理** ✓
        out['error'] = f'大盘 ADX 读取失败 ✗({e}) ⇒ 保守拒绝 ✓'
        return out
    i = bisect.bisect_left(dates, signal_date)   # 严格早于 T 的最近一根的位置 ✓ = T-1 ✓
    # ★【2026-10-07 ✓】实盘口径 ✓：有 T 日那根就用它 ✓；没有 ⇒ 回落 T-1 ✓（保守 ✓）
    if use_signal_day and i < len(dates) and dates[i] == signal_date:
        j = i
    else:
        j = i - 1
    if j < 0:
        out['error'] = (f'大盘 ADX 无「{signal_date}」' +
                        ('当日及之前' if use_signal_day else '之前') +
                        f'的数据 ✗ ⇒ 保守拒绝 ✓'
                        f'（检查数据是否已采集 ✓：`market_index_adx` ✓）')
        return out
    st = states[dates[j]]
    out.update(state_date=dates[j], adx=st.adx, dir=st.dir, band=st.band)
    return out


def _close_series(index_code: str) -> List[Tuple[str, float]]:
    """指数**收盘价**升序序列 ✓ `[(日期, 收盘), …]` ✓（**带表指纹缓存** ✓）

    ⚠️ 与 `_series`（ADX 状态）**同一张表、同一指纹** ✗✓ ⇒ 两者**永远同步** ✓
      （不可能出现"ADX 用新数据、MA 用旧数据"✗）。**不联网** ✗（表里已落库 ✓ 实测 1635 行 ✓）。
    ⚠️ `close` 缺失的行 ✗ ⇒ **跳过**（宁可让 MA 不足而**保守** ✓，也不拿 0 当价格 ✗✓）。
    """
    sig = _signature(index_code)
    hit = _CLOSE_CACHE.get(index_code)
    if hit and hit.get('sig') == sig:
        return hit['rows']
    rows: List[Tuple[str, float]] = []
    for r in _load_rows(index_code):
        d = str(r.get('trade_date') or '').replace('-', '')[:8]
        if len(d) != 8:
            continue
        try:
            rows.append((d, float(r.get('close'))))
        except (TypeError, ValueError):
            continue                          # 无收盘价 ⇒ 跳过 ✓（不拿 0 冒充 ✗）
    rows.sort(key=lambda x: x[0])             # 升序 ✓（状态机/MA 都要求时间序 ✓）
    _CLOSE_CACHE[index_code] = {'sig': sig, 'rows': rows}
    return rows


def _ma_state_at(signal_date: str, index_code: str, period: int,
                 use_signal_day: bool = False) -> Dict:
    """规则2 附加条件所需的 **收盘 + MA** ✓
    （默认 **只用到 T-1 及之前** ✗✓，防前视 ✓；★ `use_signal_day=True` ⇒ **用 T 日收盘** ✓ 仅实盘 ✓）

    口径 ✓（与 ADX 的 `_state_at` **同一纪律** ✗✓）：
      · 默认 ✓：`close` = **严格早于 T 的最后一根**收盘 ✓（= T-1 ✓）；
                `ma` = **T-1 往前数 `period` 根（**含 T-1** ✓）的算术均值** ✓；
      · `use_signal_day=True` ✓（实盘 ✓）：`close` = **T 日收盘** ✓；
                `ma` = **以 T 为末端**往前 `period` 根（**含 T** ✓）的均值 ✓。
    ⚠️ 没有 T 日那根 ⇒ **回落 T-1** ✓（保守 ✓，与 `_state_at` 同一取向 ✓）。

    Returns:
        `{'close','ma','ma_date','ma_period','error'}` ✓ —— `error` 非空 ⇒ 调用方**保守处理** ✓
        （由"其他 ⇒ 0%"档承担 ✓，与"缺数据 ⇒ 不允许开仓"**同取向** ✓）。
    """
    out = {'close': None, 'ma': None, 'ma_date': '',
           'ma_period': int(period), 'error': ''}
    p = int(period)
    try:
        rows = _close_series(index_code)
    except Exception as e:                    # 取数异常 ⇒ 交给调用方**保守处理** ✓
        out['error'] = f'指数收盘价读取失败 ✗({e})'
        return out
    dates = [d for d, _ in rows]
    i = bisect.bisect_left(dates, signal_date)   # 严格早于 T ✓ = T-1 的位置 ✓
    # ★【2026-10-07 ✓】实盘口径 ✓：窗口**末端** = T 日（若有 ✓），否则 T-1 ✓
    if use_signal_day and i < len(dates) and dates[i] == signal_date:
        j = i + 1                                # 末端含 T ✓
    else:
        j = i                                    # 末端 = T-1 ✓
    if j < p:
        out['error'] = (f'指数收盘价不足 {p} 根（{"当日及之前" if use_signal_day and j > i else "T-1 之前"}'
                        f'仅 {j} 根 ✗）⇒ **保守**不给 50% 档 ✓')
        return out
    window = [c for _, c in rows[j - p:j]]    # ★ 含"末端"在内共 p 根 ✓
    out['close'] = float(rows[j - 1][1])
    out['ma'] = sum(window) / float(p)
    out['ma_date'] = dates[j - 1]
    return out


# ---------------------------------------------------------------------------
# ★★【2026-09-28 用户口径 ✓】**当日仓位上限**（只约束"开新仓" ✗加仓）★★
#   ★ 2026-09-28 用户口径更新 ✓：原「大盘 ADX 硬闸门」**已整体取消** ✗
#     ⇒ **开新仓的大盘判据只有本规则** ✓（"由仓位上限总控" ✓）
# ---------------------------------------------------------------------------

def is_index_position_cap_enabled(config: Optional[Dict] = None) -> bool:
    """仓位上限是否启用 ✓（默认**关** ✗；`adx` 模式预设 **开** ✓；可单键覆盖 ✓）"""
    return _resolve_bool(config, 'enable_index_position_cap',
                         DEFAULT_INDEX_POSITION_CAP)


def should_skip_selection_when_blocked(config: Optional[Dict] = None) -> bool:
    """★【2026-09-29 用户要求 ✓】**不开新仓时是否跳过选股执行**（开关 ✓，默认 **开** ✓）

    用户口径 ✓："回测时，如果判定当日**不开新仓**，**跳过选股执行过程**，直接返回
    选股结果为 0" ✓；随后追加 ✓："**建议作为开关参数，便于对比回测效果**" ✓。

    ⚠️ **为什么必须能关** ✗✓（用户洞察 ✓）：跳过选股 ⇒ 当日 `0%` 档下**本会入池**的
      候选**不进池** ✗ ⇒ **次日**买入集可能不同 ✗ ⇒ **回测结果可能变化** ✗✓
      （候选池是**跨日持久**的 ✓，不是当日即弃 ✓）
      ⇒ 要做 A/B 对比就把它设 `false` ✓（= 旧行为：选股/评分照跑、结果置 0 ✓）。

    读取 ✓：`skip_selection_when_no_new_position`（yaml `backtest:` 节 / 顶层 / 请求 config ✓
    同一优先级链 ✓）；缺省 = **true** ✓（用户现行要求 ✓）。
    """
    return _resolve_bool(config, 'skip_selection_when_no_new_position',
                         DEFAULT_SKIP_SELECTION_WHEN_BLOCKED)


def resolve_cap_low_require_above_ma(config: Optional[Dict] = None) -> bool:
    """★★【2026-09-30 用户要求 ✓】规则2 是否**追加**「指数收盘 > MA20」** ✗→✓ ★★

    用户原话 ✓："大盘仓位控制规则：**adx<18 时增加条件，dir 上升，而且 >ma20**" ✓
    ⇒ 默认 **开** ✓（用户要的就是这个口径 ✓）；置 `false` ⇒ **旧行为** ✓
      （`ADX<18 ∧ dir上升` 即 50% ✓）—— 供 **A/B 对比** ✓。
    """
    return _resolve_bool(config, 'index_cap_low_require_above_ma',
                         DEFAULT_CAP_LOW_REQUIRE_ABOVE_MA)


# ---------------------------------------------------------------------------
# ★★【2026-10-05 用户要求 ✓】**板块回退**（全A 不放行 ⇒ 看科创板 / 创业板）★★
#   用户原话 ✓："全a指数adx放行或部分放行（规则1，规则2）时，**全部股票可以买入**；
#     全a指数不放行（兜底仓位限制为0）时，如果**科创板或者创业板**adx符合放行规则，
#     则按**部分放行（规则2）**执行，但**买入股票需要符合对应的指数**" ✓
#
#   落成三条 ✓（只有三条 ✗，其余一律沿用现状 ✓）：
#     ① 全A **放行**（规则1 ✓ 或 规则2 ✓）⇒ **全部股票**照旧 ✓（**不看板块** ✗✓，
#        与现状**逐字一致** ✓ ⇒ 不影响任何既有结果 ✓）；
#     ② 全A **兜底 0%** ✗ ⇒ 逐票看**它所属板块**的指数 ✓：
#        · 688/689（科创板 ✓）⇒ 看 `000688.SH`（科创50 ✓）；
#        · 300/301（创业板 ✓）⇒ 看 `399006.SZ`（创业板指 ✓）；
#        · 其它（主板/北交所 ✓）⇒ **仍 0%** ✗（用户口径：只放行"对应的指数"✓）；
#     ③ 板块指数**放行**（规则1 ✓ 或 规则2 ✓）⇒ 一律按**规则2 的比例**
#        （`index_cap_low_ratio` ✓ = **部分放行** ✓）；⚠️ **即便板块指数走的是规则1** ✗✓
#        ⇒ 也**不给 100%** ✗ —— 用户原话是"**按部分放行（规则2）执行**" ✓（保守 ✓）。
#
#   ⚠️ 口径铁律 ✗✓：与全A 同源同算法 ✓ —— 同一个 `index_position_cap()` ✓、
#     同样只用 **T-1** ✓、同样的 `收盘>MA20` 附加条件 ✓、同样的 `dir=上升` ✓
#     （只换 `index_adx_code` ✓，**不另写任何阈值** ✗✓）。
#   ⚠️ 缺数据/预热不足 ✓ ⇒ 该板块**不放行** ✓（与"缺数据 ⇒ 不允许开仓"**同取向** ✓）。
# ---------------------------------------------------------------------------

#: 板块标识 ✓
BOARD_STAR = 'star'            # 科创板 ✓
BOARD_CHINEXT = 'chinext'      # 创业板 ✓
#: 代码前缀 ✓（科创板 688/689 ✓；创业板 300/301 ✓）
STAR_PREFIXES = ('688', '689')
CHINEXT_PREFIXES = ('300', '301')
#: ★ 默认**开** ✓（用户 2026-10-05 要求 ✓）；置 `false` ⇒ **旧行为** ✓（全A 兜底 ⇒ 全拒 ✓，A/B 用 ✓）
DEFAULT_BOARD_FALLBACK = True
#: 板块指数代码 ✓（默认即 2026-10-05 已初始化的两个 ✓）
DEFAULT_STAR_INDEX_CODE = '000688.SH'        # 科创50 ✓
DEFAULT_CHINEXT_INDEX_CODE = '399006.SZ'     # 创业板指 ✓


def is_board_fallback_enabled(config: Optional[Dict] = None) -> bool:
    """★★【2026-10-05 用户要求 ✓】全A 兜底时是否**按板块指数部分放行** ✗→✓ ★★

    默认 **开** ✓（用户要的口径 ✓）；置 `false` ⇒ **旧行为** ✓（全A 兜底 ⇒ 全部不买 ✓）——
    供 **A/B 对比** ✓。

    ⚠️【2026-10-05 口径二次调整 ✓】用户先要"去除"✗、旋即改为"**保留 + 调整**"✓：
      **"当科创板和创业板同时放行时，判定为整体不放行"** ✓
      ⇒ 该细则实现于 `board_release_cap()` ✓（逐票 ✓）与 `any_board_release()` ✓（日级 ✓）
         —— **不改本开关** ✗✓（开关仍只管"要不要看板块" ✓）。
    """
    return _resolve_bool(config, 'index_cap_board_fallback',
                         DEFAULT_BOARD_FALLBACK)


def classify_board(stock_code: str) -> str:
    """个股 → 板块 ✓（`'star'` / `'chinext'` / `''`=其它或无法识别 ✓）

    ⚠️ 用**代码前缀**判定 ✗✓（不查库 ✗）：回测里本函数**逐票逐日**调用 ✓，
      查 `stock_basic` 会是每票一次 DB 往返 ✗ ⇒ 前缀判定 O(1) ✓ 且与
      `reinit_kcb_data.py`（"688/689 科创板"✓）等既有口径一致 ✓。
    ⚠️ 无法识别（非 6 位数字 ✓ / 带后缀 ✓ 会先剥掉 ✓）⇒ 返回 `''` ⇒ **不放行** ✓（保守 ✓）。
    """
    c = str(stock_code or '').strip().upper().split('.')[0]
    if len(c) != 6 or not c.isdigit():
        return ''
    if c.startswith(STAR_PREFIXES):
        return BOARD_STAR
    if c.startswith(CHINEXT_PREFIXES):
        return BOARD_CHINEXT
    return ''


def resolve_board_index_code(board: str, config: Optional[Dict] = None) -> str:
    """该板块用**哪个指数**判 ✓（可配 ✓；缺省 = `000688.SH` / `399006.SZ` ✓）

    键 ✓：`index_cap_star_code`（科创板 ✓）/ `index_cap_chinext_code`（创业板 ✓）。
    ⚠️ 改这两个键**必须**保证该指数在 `market_index_adx` 里**已初始化** ✗✓
      （否则档位落"缺数据 ⇒ 0%"✗ ⇒ 等于该板块不放行 ✓ —— 保守 ✓ 但会静默变严 ✗，
       故回退日志会**带上代码** ✓ 便于排查 ✓）。
    """
    star = (board == BOARD_STAR)
    key = 'index_cap_star_code' if star else 'index_cap_chinext_code'
    default = DEFAULT_STAR_INDEX_CODE if star else DEFAULT_CHINEXT_INDEX_CODE
    try:
        from utils.backtest_mode import effective
        raw = effective(key, config, _load_engine_yaml(), default=None)
    except Exception:
        raw = None
    return str(raw).strip() if raw else default


def _board_index_cap(board: str, signal_date: str,
                     config: Optional[Dict] = None) -> Dict:
    """**该板块指数的档位** ✓（复用同一个 `index_position_cap()` ✓ —— 只换指数代码 ✓）"""
    code = resolve_board_index_code(board, config)
    out = {'board': board, 'index_code': code, 'cap': 0.0, 'rule': '',
           'adx': None, 'dir': '', 'error': '', 'rule_id': 'other'}
    cfg = dict(config or {})
    cfg['index_adx_code'] = code                     # ★ 只换指数 ✓，算法/阈值全不动 ✓
    try:
        st = index_position_cap(signal_date, cfg)
        out.update(cap=float(st.get('cap') or 0.0), rule=st.get('rule') or '',
                   adx=st.get('adx'), dir=st.get('dir') or '',
                   error=st.get('error') or '',
                   rule_id=st.get('rule_id') or 'other')     # ★ 结构化档位 ✓
    except Exception as e:                           # 取数异常 ⇒ **不放行** ✓（保守 ✓）
        out['error'] = f'板块指数({code})判读异常 ✗({e})'
    return out


def board_release_cap(signal_date: str, stock_code: str,
                      config: Optional[Dict] = None) -> Dict:
    """★ 全A 兜底时，**该票**能否按板块指数"**部分放行**" ✓

    Returns:
        `{'board','board_name','index_code','released','cap','rule','adx','dir','error'}` ✓
        `released=True` ⇒ `cap` = **规则2 的比例**（`index_cap_low_ratio` ✓ = 部分放行 ✓）
    """
    out = {'board': '', 'board_name': '', 'index_code': '', 'released': False,
           'cap': 0.0, 'rule': '', 'adx': None, 'dir': '', 'error': ''}
    board = classify_board(stock_code)
    if not board:                                    # 非双创 ⇒ 兜底下**不放行** ✓
        out['error'] = '非科创板/创业板票 ✗ ⇒ 全A 兜底时不再放行 ✓'
        return out
    out['board'] = board
    out['board_name'] = '科创板' if board == BOARD_STAR else '创业板'
    st = _board_index_cap(board, signal_date, config)
    out.update(index_code=st['index_code'], rule=st['rule'], adx=st['adx'],
               dir=st['dir'], rule_id=st.get('rule_id') or 'other')
    # ★★【2026-10-05 用户口径 ✓】**放行 = 规则1 或 规则2** ✗✓（**按档位判** ✗✓，
    #   **不看比例大小** ✗ —— 即"规则2 放行但比例配成 0"✗ 也能被**正确识别** ✓）
    if out['rule_id'] not in ('high', 'low'):
        # ★ 归因要**带板块指数自己的判据原文** ✗→✓（否则只看到"也未放行"✗，
        #   查不出是"落在 18~25 ✓"还是"破 MA20 ✗"还是"缺数据 ✗"✗✓）
        _why = st['error'] or st['rule'] or '判据为空 ✗'
        out['error'] = (f'{out["board_name"]}指数({st["index_code"]}) **未放行** ✗'
                        f'（{_why}）')
        return out
    # ★★★★【2026-10-05 用户口径二次调整 ✓】**双创同时放行 ⇒ 整体不放行** ✗✓ ★★★★
    #   用户原话 ✓："**保留规则，但是需要调整：当科创板和创业板同时放行时，
    #     判定为整体不放行**" ✓
    #   ⚠️ 判据与上面**同一套** ✗✓（按 `rule_id` **档位** ✓、**不看比例** ✗）——
    #     否则会出现"科创板按档位放行 ✓、创业板因 `low_ratio=0` 被判没放行 ✗"
    #     ⇒ **同时放行识别不出来** ✗✓（口径分裂 ✓）。
    #   ⚠️ 探另一个板块**只许用纯函数** `_board_index_cap` ✗✓（**不**回调
    #     `board_release_cap` ✗ —— 那是互相探测 ⇒ **递归** ✗）；
    #     探测异常（缺数据等 ✓）⇒ 视为**未放行** ✓（保守 ✓，不误伤 ✓）。
    try:
        _other = BOARD_CHINEXT if board == BOARD_STAR else BOARD_STAR
        _os = _board_index_cap(_other, signal_date, config)
        _other_on = _os.get('rule_id') in ('high', 'low')
    except Exception:
        _os, _other_on = {}, False
    if _other_on:
        _oname = '创业板' if board == BOARD_STAR else '科创板'
        out['error'] = (
            f'★ **双创同时放行 ⇒ 整体不放行** ✗✓（2026-10-05 用户口径 ✓）：'
            f'{out["board_name"]}指数({st["index_code"]}) 放行 ✓ 且 '
            f'{_oname}指数({_os.get("index_code") or "?"}) 也放行 ✓'
            f' ⇒ **当日一律不开新仓** ✗')
        out['released'] = False
        return out
    # ★ 用户口径 ✓：**仓位一律按规则2 的比例** ✓（**部分放行** ✓，即便板块指数走的是规则1 ✗✓）
    try:
        low_ratio = float(resolve_position_cap_rules(config)['low_ratio'])
    except Exception:
        low_ratio = 0.0
    if low_ratio <= 0.0:
        # ⚠️ 档位**是**规则2/规则1 放行 ✓，但比例被配成 0 ✗ ⇒ **实际开不了仓** ✓
        #   ⇒ 如实归因（**不假装放行** ✗✓ —— 否则日志说"放行"✗ 而实际不买 ✗，最难查 ✗）
        out['error'] = (f'{out["board_name"]}指数({st["index_code"]}) '
                        f'**{("规则1" if out["rule_id"] == "high" else "规则2")}放行** ✓，'
                        f'但 `index_cap_low_ratio`={low_ratio:.0%} ✗ ⇒ **实际不可开仓** ✓'
                        f'（要按板块回退买 ⇒ 请把该比例配成 > 0 ✓）')
        out['released'] = False
        return out
    out.update(released=True, cap=low_ratio)
    return out


def any_board_release(signal_date: str, config: Optional[Dict] = None) -> bool:
    """★ 全A 兜底时：**是否至少有一个板块指数放行** ✓

    ⚠️ 用途 ✗✓：供「**不开新仓 ⇒ 跳过选股**」（`skip_selection_when_no_new_position` ✓）
      判断 —— 若板块放行却仍跳过选股 ✗ ⇒ **次日也没有候选** ✗ ⇒ 本功能**永远买不到** ✗✓
      （这是最容易漏的一处接线 ✓）。

    ★★【2026-10-05 用户口径二次调整 ✓】**"双创同时放行 ⇒ 整体不放行"也自动生效** ✗✓ ★★
      缘由 ✓：本函数复用 `board_release_cap` ✓ ⇒ 两边同时放行时它**两个都返回 False** ✗✓
      ⇒ 本函数**自然返回 False** ✓ ⇒ 当日"不开新仓"✓ ⇒ **正确跳过选股** ✓✓
      （⚠️ 这正是"两处必须同一判据"的价值 ✗✓：若各写一套 ✗ ⇒ 会出现"逐票不放行 ✗
        但没跳过选股 ✗"或反之 ⇒ **口径分裂** ✗。）
    """
    if not is_board_fallback_enabled(config):
        return False
    # ★ 与逐票闸门**同一判据实现** ✗✓（直接复用 `board_release_cap` ✓ 传一个该板块的
    #   **代表代码** ✓）—— 否则两处口径会漂移 ✗：例如"规则2 放行但比例配成 0"✗ 时
    #   逐票判"不放行"✗、而这里判"放行"✗ ⇒ 白跑一遍选股（不致错买 ✓，但**口径分裂** ✗✓）。
    for _code in ('688508', '300750'):
        if board_release_cap(signal_date, _code, config).get('released'):
            return True
    return False


def required_index_codes_for_gate(config: Optional[Dict] = None) -> list:
    """★【2026-10-05 适配 ✓】**回测数据闸门**该校验哪些指数 ✓（**主指数在前** ✓）

    组成 ✓：① 主指数（= 路由 / 当日仓位上限实际判档用的那个 ✓ `resolve_index_adx_code()` ✓）
           ② **板块回退启用时** ✓ 再追加两个板块指数 ✓（供 `check_index_adx` 的预热校验 ✓）。

    ⚠️ 与 `utils.market_index_adx.daily_index_codes()`（**每日采集**用 ✓）**刻意不同** ✗✓：
      · 采集 ✓ 恒算 3 个 ✗（开关随时可能打开 ✓，停更即陈旧 ✗）；
      · 闸门 ✓ 只在**真的会用**它们时才校验 ✓（回退关着 ⇒ 不必拦/不必提醒 ✗✓，避免噪音 ✗）。
    ⚠️ 板块指数在闸门里**只提醒不阻断** ✓（它们是回退路径 ✓，硬拦会误伤正常回测 ✗✓）——
      该语义由 `utils.backtest_data_gate.run_gate()` 实现 ✓（`index_codes[1:]` ✓）。
    """
    out = []
    try:
        _d = resolve_index_adx_code(config)
        if _d:
            out.append(str(_d).strip())
    except Exception:
        pass
    if not out:
        out = [DEFAULT_INDEX_CODE]
    try:
        if is_board_fallback_enabled(config):
            for _b in (BOARD_STAR, BOARD_CHINEXT):
                _c = str(resolve_board_index_code(_b, config) or '').strip()
                if _c and _c not in out:
                    out.append(_c)
    except Exception:                                 # 纯"该查什么"的计算 ✓ ⇒ 绝不抛 ✗
        pass
    return out


def resolve_cap_use_signal_day(config: Optional[Dict] = None) -> bool:
    """★★【2026-10-07 用户口径 ✓】**大盘档位用「信号日当天收盘」还是"前一根"** ✗→✓ ★★

    用户原话 ✓："**T 日出信号，T+1 实盘时按即时价格成交**，**和回测一致**，
      信号的价格只是**参考价**" ✓

    ⇒ 语义 ✓（**两边一致** ✗✓，都是"信号日当天"）：
      · **回测** ✓：信号日 = 执行日 T 的**前一根**（= T−1 ✓）⇒ 取 `dates[T-1]` ✓
        ⇒ 即"**回测的信号日当天**" ✓；
      · **实盘** ✓：信号日 = T ✓ ⇒ 取 `dates[T]` ✓ ⇒ 即"**实盘的信号日当天**" ✓。
    ⇒ `True` = 用"**信号日当天**" ✓（**实盘**默认 ✓）；`False` = 用"前一根" ✓
      （**回测**默认 ✓ ⇒ **逐字不变、零回归** ✓）。

    ⚠️ 取值走 `effective()` ✓ ⇒ yaml **顶层**或 **`backtest:` 节**里显式写该键都生效 ✓；
      实盘侧只在**未显式**时才注入默认值 ✓（`strategy_runner` ✓，用 `is_explicit` 判 ✓）。
    """
    from utils.backtest_mode import effective
    # ★★★★【2026-10-07 审计修复 ✓】**唯一解析器** ✗→✓ ★★★★
    #   缘由 ✗✓（审计发现 ✗）：本函数原先**只认** `index_cap_use_signal_day` ✗，
    #     而个股侧 `stock_adx_filter.resolve_use_signal_day` **先认** `adx_use_signal_day`
    #     ✗ ⇒ 一旦只写通用键（或两键写反 ✗）⇒ **大盘取一根、个股取另一根** ✗✗
    #     —— 恰好违反用户本次口径："**大盘和个股的 adx 应使用同一时点**" ✗。
    #   ⇒ 改为：**两键都认、顺序固定** ✓，并让个股侧**直接复用本函数** ✓
    #     （`stock_adx_filter.resolve_use_signal_day` ✓ ⇒ **同一实现** ✓ ⇒
    #      结构上**不可能**再分叉 ✓✓）。
    #   ⚠️ 顺序约定 ✗✓：**既有键优先** ✓（`index_cap_use_signal_day` ✓ —— 实盘运行器
    #     注入的就是它 ✓）；`adx_use_signal_day` ✓ 为新通用名 ✓、仅在前者**缺省**时生效 ✓。
    for _k in ('index_cap_use_signal_day', 'adx_use_signal_day'):
        raw = effective(_k, config, _load_engine_yaml(), default=None)
        if raw is None or raw == '':
            continue
        try:
            return (bool(raw) if not isinstance(raw, str)
                    else raw.strip().lower() in ('1', 'true', 'yes', 'on', '是', '开'))
        except Exception:
            continue
    return False        # ★ 默认 **False** ✓（回测安全 ✓）


def backtest_gate_config(config: Optional[Dict] = None) -> Dict:
    """★★【2026-10-07 审计修复 ✓】**回测专用：把"信号日时点"硬钉为「前一根」** ✗✓ ★★

    为什么必须硬钉 ✗✓（**反前视** ✓）：回测里**执行日 = T 日开盘成交** ✓ ⇒
      T 日收盘的 ADX **当天根本还不存在** ✗ ⇒ 若允许配置成"当天"✗ ⇒ **前视** ✗✗
      （回测曲线会虚高 ✓，且实盘永远复现不出来 ✗）。
    ⇒ 故回测**忽略**这两个键 ✓（`index_cap_use_signal_day` / `adx_use_signal_day` ✓），
      且**大盘 ✓ 与 个股 ✓ 用同一份被钉过的 cfg** ✓ ⇒ 两者**必然同一时点** ✓✓。

    ⚠️ 与默认行为的关系 ✓：默认本就是 `False` ✓ ⇒ 本函数**不改变**任何既有回测结果 ✓
      （它只挡住"误配成当天"这一种危险 ✗）。
    ⚠️ 实盘**不得**调用它 ✗✓（实盘要的正是"信号日当天" ✓ —— 见 `strategy_runner` 的注入 ✓）。
    """
    try:
        return {**(config or {}), 'index_cap_use_signal_day': False,
                'adx_use_signal_day': False}
    except Exception:
        return {'index_cap_use_signal_day': False, 'adx_use_signal_day': False}


def resolve_cap_ma_period(config: Optional[Dict] = None) -> int:
    """MA 周期 ✓（用户原话是 `MA20` ✓ ⇒ 默认 **20** ✓；可配 ✓）

    ⚠️ 非法（非数值 / <2 / >250）⇒ **回落 20** ✓ + 告警 ✓（**不抛** ✗、**不静默按 1** ✗
      —— 那会让"收盘 > 1 日均线"变成另一种口径 ✗）。
    """
    from utils.backtest_mode import effective
    raw = effective('index_cap_ma_period', config, _load_engine_yaml(), default=None)
    if raw is None or raw == '':
        return int(DEFAULT_CAP_MA_PERIOD)
    try:
        p = int(float(raw))
    except (TypeError, ValueError):
        logger.warning(f'index_cap_ma_period={raw!r} 非法 ⇒ 回落默认 '
                       f'{DEFAULT_CAP_MA_PERIOD} ✓')
        return int(DEFAULT_CAP_MA_PERIOD)
    if not (2 <= p <= 250):
        logger.warning(f'index_cap_ma_period={raw!r} 超出范围 [2, 250] ⇒ 回落默认 '
                       f'{DEFAULT_CAP_MA_PERIOD} ✓')
        return int(DEFAULT_CAP_MA_PERIOD)
    return p


def _resolve_ratio(config: Optional[Dict], key: str, default: float) -> float:
    """比例参数 ✓（0~1 ✓）；**兼容百分数写法** ✓（写 `50` ⇒ 视作 **50%** ✓）

    ⚠️ 非法（非数值 / 超范围）⇒ **回落默认** ✓ + 告警 ✓（**不抛** ✗ —— 绝不因一个
      配置写法阻断买/回测 ✗；**也不静默按 0** ✗ 那会变成"永不开仓"✗ 最危险 ✗）。
    """
    from utils.backtest_mode import effective
    raw = effective(key, config, _load_engine_yaml(), default=None)
    if raw is None or raw == '':
        return float(default)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        logger.warning(f'{key}={raw!r} 非法（需 0~1 或 0~100）⇒ 回落默认 {default:g} ✓')
        return float(default)
    if 1.0 < v <= 100.0:                          # 百分数写法 ✓（用户习惯写 `50` ✓）
        v = v / 100.0
    if not (0.0 <= v <= 1.0):
        logger.warning(f'{key}={raw!r} 超出范围 ⇒ 回落默认 {default:g} ✓')
        return float(default)
    return v


def resolve_position_cap_rules(config: Optional[Dict] = None) -> Dict:
    """读取**档位 + 比例 + 兜底** ✓（阈值与比例**全部可配** ✓）

    Returns:
        `{'high_adx','high_ratio','low_adx','low_ratio','other_ratio',
          'low_require_above_ma','ma_period'}` ✓
        ★【2026-09-30 ✓】末两项 = 规则2 的**附加条件开关与 MA 周期** ✓（用户要求 ✓）

    ⚠️ 校验 ✓：必须 `0 < low_adx < high_adx < 100` ✗✓（反序/相等 ⇒ **告警并按默认
      `18/25`** ✓ —— 否则两条规则会**重叠** ✗、档位无法解释 ✗）。
    """
    from utils.backtest_mode import effective

    def _num(key: str, default: float) -> float:
        raw = effective(key, config, _load_engine_yaml(), default=None)
        if raw is None or raw == '':
            return float(default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            logger.warning(f'{key}={raw!r} 非法 ⇒ 回落默认 {default:g} ✓')
            return float(default)

    lo = _num('index_cap_low_adx', DEFAULT_CAP_LOW_ADX)
    hi = _num('index_cap_high_adx', DEFAULT_CAP_HIGH_ADX)
    if not (0.0 < lo < hi < 100.0):
        logger.warning(f'仓位上限档位非法（low={lo:g} high={hi:g}）⇒ 按默认 '
                       f'{DEFAULT_CAP_LOW_ADX:g}/{DEFAULT_CAP_HIGH_ADX:g} ✓')
        lo, hi = DEFAULT_CAP_LOW_ADX, DEFAULT_CAP_HIGH_ADX
    return {
        'high_adx': hi,
        'high_ratio': _resolve_ratio(config, 'index_cap_high_ratio',
                                     DEFAULT_CAP_HIGH_RATIO),
        'low_adx': lo,
        'low_ratio': _resolve_ratio(config, 'index_cap_low_ratio',
                                    DEFAULT_CAP_LOW_RATIO),
        'other_ratio': _resolve_ratio(config, 'index_cap_other_ratio',
                                      DEFAULT_CAP_OTHER_RATIO),
        # ★【2026-09-30 用户要求 ✓】规则2 的**附加条件** ✓（`收盘 > MA{ma_period}` ✓）
        #   ⚠️ 放进 rules ✓ ⇒ `index_position_cap(..., rules=…)` 的调用方**也一并生效** ✓
        #     （否则"传 rules 时静默丢掉新条件"✗ —— 那正是最难查的一类不一致 ✗✓）
        'low_require_above_ma': resolve_cap_low_require_above_ma(config),
        'ma_period': resolve_cap_ma_period(config),
    }


def index_position_cap(signal_date, config: Optional[Dict] = None,
                       index_code: Optional[str] = None,
                       dir_mode: Optional[str] = None,
                       rules: Optional[Dict] = None) -> Dict:
    """**当日仓位上限** ✓（用户 2026-09-28 口径 ✓；★ 2026-09-30 规则2 加附加条件 ✓）

    规则 ✓：`ADX > 25` ∧ `dir=上升` ⇒ **100%** ✓；
    ★ `ADX < 18` ∧ `dir=上升` ∧ **指数收盘 > MA20** ⇒ **50%** ✓（附加条件 ✓，可关 ✓）；
    其余（`18 ≤ ADX ≤ 25` ✗ / `dir ≠ 上升` ✗ / ★ `ADX<18` 但**破 MA20 或 MA 不足** ✗ /
    缺数据 ✗）⇒ **兜底** ✓（默认 0% ⇒ 不允许开仓 ✓，可配 ✓）。

    ⚠️ 与大盘闸门**共用同一份 T-1 状态** ✓（`_state_at` ✓）⇒ 两处**看到同一个 ADX** ✓；
      ★ MA 判定也走 **T-1** ✓（`_ma_state_at` ✓）⇒ **不会前视** ✗✓。

    Returns:
        `{'cap','rule','adx','dir','band','state_date','signal_date','index_code','error',
          'close','ma','ma_period'}` ✓
        ★ 末三项（2026-09-30 ✓）：规则2 判定用的 **T-1 收盘 / MA / 周期** ✓
          ⚠️ `close` / `ma` **只在真的进入规则2 分支并读取后**才有值 ✓；规则1 / 兜底档下为
          `None` ✗（**不去白读一次 MA** ✗ —— 那是逐票逐日调用 ✓，多读一次就是纯浪费 ✗）；
          `ma_period` 则**总是**给出 ✓（纯配置 ✓，便于日志自证 ✓）。
    """
    code = str(index_code or resolve_index_adx_code(config))
    dm = str(dir_mode or resolve_index_adx_dir_mode(config))
    r = dict(rules or resolve_position_cap_rules(config))
    sd = str(signal_date or '').replace('-', '')[:8]
    # ★★【2026-10-07 用户要求 ✓】**实盘用 T 日收盘口径** 的开关 ✓（默认 False ⇒ 回测不变 ✓）★★
    _use_today = resolve_cap_use_signal_day(config)
    out = {'cap': float(r['other_ratio']), 'rule': '', 'adx': None, 'dir': '',
           'band': '', 'state_date': '', 'signal_date': sd, 'index_code': code,
           'error': '', 'close': None, 'ma': None,
           'ma_period': int(r.get('ma_period') or DEFAULT_CAP_MA_PERIOD),
           # ★★【2026-10-05】结构化**档位** ✓：`'high'`=规则1 / `'low'`=规则2 /
           #   `'other'`=兜底（含缺数据 / 无信号日 ✓）。
           #   ⚠️ 为什么要它 ✗✓（用户 2026-10-05 把口径写精确后必须补 ✓）：板块回退判
           #      "**板块指数是否放行**" ✗ —— 若拿 `cap > 0` 当判据 ✗，则一旦
           #      `index_cap_low_ratio` 被配成 **0** ✗ ⇒ "规则2 放行"**识别不出来** ✗✓
           #      （明明是规则2 档，却因比例为 0 被判成"不放行"✗）。
           #   ⇒ 改用**档位**判 ✓（与比例解耦 ✓）；默认 `'other'` ✓ ⇒ 所有兜底/早退
           #     路径**自动**正确 ✓（不必逐条改 ✓）。
           'rule_id': 'other',
           # ★【2026-10-07 ✓】口径自证 ✓：本行日志能直接看出用的是 **T** 还是 **T-1** ✓
           'use_signal_day': bool(_use_today)}
    if len(sd) != 8:
        out['rule'] = '无有效信号日期 ⇒ 用兜底上限 ✓'
        return out
    st = _state_at(sd, code, dm, use_signal_day=_use_today)
    out.update({k: st[k] for k in ('adx', 'dir', 'band', 'state_date')})
    if st['error']:
        out['error'] = st['error']
        out['rule'] = f'大盘数据不可用 ✗ ⇒ 用**兜底**上限 {float(r["other_ratio"]):.0%} ✓'
        return out
    from utils.stock_adx_state import DIR_UP
    a, d = st['adx'], str(st['dir'] or '')
    if a is None or d != DIR_UP:
        # ⚠️ 归因必须**精确** ✗✓（实测踩过 ✓：原先两句并列 ⇒ `dir=下降` 时也显示
        #   "预热不足"✗ ⇒ 排查时被误导 ✗ —— 项目惯例：日志要能**直接定位原因** ✓）
        _why = ('大盘 ADX 预热不足（无值 ✓）' if a is None
                else f'大盘 dir={d or "未定"}（**非上升** ✗）')
        out['rule'] = (f'{_why} ⇒ 用**兜底**上限 {float(r["other_ratio"]):.0%} ✓'
                       + ('（**不允许开仓** ✓）' if r['other_ratio'] <= 0 else ''))
        return out
    a = float(a)
    if a > float(r['high_adx']):
        out['cap'] = float(r['high_ratio'])
        out['rule_id'] = 'high'                       # ★ 结构化：规则1 ✓
        out['rule'] = (f'规则1 ✓：大盘 ADX({a:g}) > {float(r["high_adx"]):g} 且 dir=上升 ✓'
                       f' ⇒ 上限 {float(r["high_ratio"]):.0%} ✓')
    elif a < float(r['low_adx']):
        _lo = float(r['low_adx'])
        _other = float(r['other_ratio'])
        _other_txt = (f'{_other:.0%} ✓'
                      + ('（**不允许开仓** ✓）' if _other <= 0 else ''))
        if not r.get('low_require_above_ma'):
            # ⚠️ 开关关 ✓ ⇒ **旧行为** ✗✓：完全不读 MA ✗ ⇒ 与历史/基准**逐字一致** ✓（A/B 用 ✓）
            out['cap'] = float(r['low_ratio'])
            out['rule_id'] = 'low'                   # ★ 结构化：规则2 ✓（与比例无关 ✓）
            out['rule'] = (f'规则2 ✓：大盘 ADX({a:g}) < {_lo:g} 且 dir=上升 ✓'
                           f' ⇒ 上限 {float(r["low_ratio"]):.0%} ✓'
                           f'（`index_cap_low_require_above_ma=false` ⇒ **未加 MA 条件** ✓）')
            return out
        # ★★【2026-09-30 用户要求 ✓】附加条件 ✓：**指数收盘 > MA20**（同一 T-1 口径 ✓）★★
        _p = int(r.get('ma_period') or DEFAULT_CAP_MA_PERIOD)
        ma = _ma_state_at(sd, code, _p, use_signal_day=_use_today)
        out.update(close=ma['close'], ma=ma['ma'], ma_period=ma['ma_period'])
        if ma['error'] or ma['ma'] is None or ma['close'] is None:
            # ⚠️ MA 取不到 / 不足 _p 根 ⇒ **保守**落兜底 ✓（与"缺数据 ⇒ 不允许开仓"同取向 ✓）
            _err = ma['error'] or f'MA{_p} 不可用 ✗'
            out['rule'] = (f'规则2 **未通过** ✗：大盘 ADX({a:g}) < {_lo:g} 且 dir=上升 ✓，'
                           f'但 {_err} ⇒ 用**兜底**上限 {_other_txt}')
            return out
        _c, _m = float(ma['close']), float(ma['ma'])
        if _c > _m:
            out['cap'] = float(r['low_ratio'])
            out['rule_id'] = 'low'                   # ★ 结构化：规则2 ✓（与比例无关 ✓）
            out['rule'] = (f'规则2 ✓：大盘 ADX({a:g}) < {_lo:g} ✓ 且 dir=上升 ✓ 且 '
                           f'收盘({_c:.2f}) > MA{_p}({_m:.2f}) ✓'
                           f' ⇒ 上限 {float(r["low_ratio"]):.0%} ✓')
        else:
            out['rule'] = (f'规则2 **未通过** ✗：大盘 ADX({a:g}) < {_lo:g} 且 dir=上升 ✓，'
                           f'但 收盘({_c:.2f}) ≤ MA{_p}({_m:.2f}) ✗（**未站上均线** ✗）'
                           f' ⇒ 用**兜底**上限 {_other_txt}')
        return out
    else:
        out['rule'] = (f'大盘 ADX({a:g}) 落在 [{float(r["low_adx"]):g},'
                       f'{float(r["high_adx"]):g}] ✓ ⇒ 用**兜底**上限 '
                       f'{float(r["other_ratio"]):.0%} ✓（用户未定义该档 ✓）')
    return out


def index_position_cap_gate(signal_date, current_ratio,
                            config: Optional[Dict] = None,
                            stock_code: str = '', **kw) -> Dict:
    """**开新仓**前的仓位上限闸门 ✓

    用户口径 ✓："**当持仓 > 仓位上限时，停止开新仓** ✓（**可以加仓** ✓）"。

    ★★【2026-10-05 用户要求 ✓】**板块回退** ✗→✓：全A 兜底 0% 时，
      若**该票所属板块**的指数（科创板 `000688.SH` ✓ / 创业板 `399006.SZ` ✓）放行
      ⇒ 按**部分放行（规则2 比例）** ✓，但**只有该板块的票**能买 ✓。
      ⚠️ `stock_code` 不传（旧调用方 ✓）⇒ **不启用板块回退** ✓（= 旧行为 ✓）。

    Args:
        current_ratio: 当日**持仓比例** ✓（0~1 ✓；回测 = `1 − 现金/总资产` ✓，实盘同口径 ✓）
        stock_code: 个股代码 ✓（仅用于**板块回退**的"对应指数"判定 ✓；其余逻辑不用它 ✓）

    Returns:
        `{'passed','skipped','reason','cap','rule','ratio','adx','dir',
          'board','board_name','board_index_code','board_adx','board_released'}` ✓

    ⚠️ 比较用 **`≥`** ✗✓（**不是** `>` ✗ —— 见 `DEFAULT_CAP_OTHER_RATIO` 注释 ✓：
      上限 `0%` 时若用 `>` ⇒ **空仓反而能开仓** ✗，与"其他情况不允许开仓"✗ 矛盾 ✓）。
      ⇒ **上限 0% ⇒ 一律不开新仓** ✓（含空仓 ✓）。
    ⚠️ **只用于开新仓** ✗✓（**加仓不得**调用本函数 ✗）。
    """
    out = {'passed': True, 'skipped': True, 'reason': '', 'cap': None,
           'rule': '', 'ratio': None, 'adx': None, 'dir': '',
           # ★【2026-10-05】板块回退的自证字段 ✓（**无论走不走回退都给出** ✓，便于归因 ✓）
           'board': '', 'board_name': '', 'board_index_code': '',
           'board_adx': None, 'board_released': False}
    if not is_index_position_cap_enabled(config):
        out['reason'] = '未启用 ✓'
        return out
    cap = index_position_cap(signal_date, config, **kw)
    _board = {}
    # ★★【2026-10-05 用户要求 ✓】**全A 不放行**才看板块 ✓（全A 放行 ⇒ 全部股票照旧 ✓）★★
    if (float(cap.get('cap') or 0.0) <= 0.0 and str(stock_code or '').strip()
            and is_board_fallback_enabled(config)):
        _board = board_release_cap(signal_date, stock_code, config)
        if _board.get('released'):
            _base_cap = float(cap.get('cap') or 0.0)          # 全A 兜底值（0% ✓）
            _a = _board.get('adx')
            _a_txt = (f'{float(_a):.2f}' if _a is not None else '-')
            cap = dict(cap)                                   # ⚠️ 不改原 dict ✗
            cap['cap'] = float(_board['cap'])                 # ★ = 规则2 比例（部分放行 ✓）
            cap['rule'] = (
                f'**板块回退** ✓：全A 兜底 {_base_cap:.0%} ✗，但'
                f'{_board["board_name"]}指数({_board["index_code"]}) ADX({_a_txt}) '
                f'**放行** ✓ ⇒ 本票 {stock_code} 属{_board["board_name"]} ✓ '
                f'⇒ 按**部分放行**（规则2 比例）{float(_board["cap"]):.0%} ✓'
                f'；⚠️ **仅本板块**可买 ✗（其它板块仍 0% ✓）')
    if _board:
        out.update({'board': _board.get('board', ''),
                    'board_name': _board.get('board_name', ''),
                    'board_index_code': _board.get('index_code', ''),
                    'board_adx': _board.get('adx'),
                    'board_released': bool(_board.get('released'))})
    try:
        ratio = float(current_ratio)
    except (TypeError, ValueError):
        ratio = None
    out.update({'skipped': False, 'cap': cap['cap'], 'rule': cap['rule'],
                'ratio': ratio, 'adx': cap['adx'], 'dir': cap['dir']})
    if cap['cap'] <= 0.0:                         # ★ 上限 0% ⇒ **不允许开仓** ✓（**空仓也不许** ✓）
        out['passed'] = False
        # ⚠️ 数据不可用（`cap['error']` ✓）也走这里 ✓ —— 用户口径"**其他情况 ⇒ 不允许开仓**" ✓
        #    已把"缺数据"✗ 包含在内 ✓（`index_position_cap` 给了兜底 0% ✓）⇒ **保守拒绝** ✓；
        #    这与"大盘闸门缺数据 ⇒ 保守拒绝"**同一取向** ✓（两处不会互相矛盾 ✓）。
        out['reason'] = (f'仓位上限 {cap["cap"]:.0%} ✗ ⇒ **不允许开新仓** ✓'
                         f'（**可以加仓** ✓）；{cap["rule"]}'
                         + (f'；板块回退 ✗：{_board.get("error")}'
                            if _board and not _board.get('released') else ''))
        return out
    if cap['error']:                              # 兜底被配成 > 0 ✓ 且有取数异常 ⇒ 提示但不拦 ✗
        out['reason'] = cap['error']
        return out
    if ratio is None:
        out['reason'] = '持仓比例不可得 ✗ ⇒ 用兜底上限 ✓（**不因它拦买** ✗）'
        return out
    if ratio >= cap['cap']:                       # ★ `≥` ✓（上限 0% 已在上面拦住 ✓）
        out['passed'] = False
        out['reason'] = (f'持仓 {ratio:.2%} ≥ 仓位上限 {cap["cap"]:.0%} ✗ ⇒ '
                         f'**停止开新仓** ✓（**可以加仓** ✓）；{cap["rule"]}')
    return out


def format_index_position_cap_result(gate: Dict) -> str:
    """压成一行 ✓（**通过 / 未通过 / 跳过** 都打 ✓ —— 与其它闸门同风格 ✓）"""
    if not gate:
        return '仓位上限 无结果 ✗'
    head = ('[通过]' if gate.get('passed')
            else ('[跳过]' if gate.get('skipped') else '[未通过]'))
    cap = gate.get('cap')
    cap_txt = '—' if cap is None else f'{float(cap):.0%}'
    ratio = gate.get('ratio')
    r_txt = '—' if ratio is None else f'{float(ratio):.2%}'
    return (f"仓位上限 {head} 持仓={r_txt} 上限={cap_txt} "
            f"（{gate.get('reason') or gate.get('rule') or 'OK ✓'}）")


def describe_index_position_cap_params(config: Optional[Dict] = None) -> str:
    """**仓位上限参数一行摘要** ✓（回测/实盘**同一实现** ✓；打**真生效值 + 来源** ✓）"""
    from utils.backtest_mode import is_explicit, preset as _preset
    try:
        on = is_index_position_cap_enabled(config)
        r = resolve_position_cap_rules(config)
    except Exception as e:                       # 纯日志 ✓ ⇒ 绝不抛 ✗
        return f'（仓位上限参数读取失败 ✗({e})）'
    _pres = _preset(config) or {}

    def _src(key: str) -> str:
        if is_explicit(key, config):
            return '配置'
        return '模式预设' if key in _pres else '内置默认'

    # ★【2026-09-30 用户要求 ✓】规则2 的**附加条件**也要**自证** ✗→✓（否则 A/B 时看不出
    #   当天到底按哪套口径跑的 ✗ —— 本项目惯例：每次回测都把真值打进日志 ✓）
    _p = int(r.get('ma_period') or DEFAULT_CAP_MA_PERIOD)
    if r.get('low_require_above_ma'):
        _rule2 = (f'规则2：ADX<{r["low_adx"]:g} 且 dir=上升 且 **收盘>MA{_p}** ⇒ '
                  f'{r["low_ratio"]:.0%} ✓'
                  f'（MA{_p} 用 T-1 收盘 ✓；**MA 不足 ⇒ 落兜底** ✓；'
                  f'来源={_src("index_cap_low_require_above_ma")} ✓）')
        _other = (f'{r["low_adx"]:g}≤ADX≤{r["high_adx"]:g} / dir≠上升 / '
                  f'ADX<{r["low_adx"]:g} 但收盘≤MA{_p} / 缺数据')
    else:
        _rule2 = (f'规则2：ADX<{r["low_adx"]:g} 且 dir=上升 ⇒ {r["low_ratio"]:.0%} ✓'
                  f'（**未加 MA 条件** ✓ = 旧行为 ✓）')
        _other = (f'{r["low_adx"]:g}≤ADX≤{r["high_adx"]:g} / dir≠上升 / 缺数据')
    # ★★【2026-10-05 用户要求 ✓】**板块回退**也要**自证** ✗→✓ ★★
    #   为何必须打 ✗✓：这是**新增的开仓许可来源** ✓ —— 不打则"某天为什么买了科创板"
    #   或"为什么只有科创板能买"✗ 只能靠猜 ✗✓（本项目惯例：每次回测都打真生效值 ✓）。
    #   ⚠️ 先算好整段文案再拼 ✗✓（**不要在 f-string 里塞三元表达式** ✗ —— 实测极易数错括号 ✗）。
    if is_board_fallback_enabled(config):
        _fb_txt = (f'**板块回退**=开 ✓（{_src("index_cap_board_fallback")} ✓）：全A 兜底 0% 时 ⇒ '
                   f'科创板({resolve_board_index_code(BOARD_STAR, config)}) ✓ / '
                   f'创业板({resolve_board_index_code(BOARD_CHINEXT, config)}) ✓ '
                   f'**各自放行则按规则2 比例部分放行** ✓（⚠️ **仅本板块**可买 ✗✓）；'
                   f'★ **双创同时放行 ⇒ 整体不放行** ✗✓（2026-10-05 用户口径 ✓）')
    else:
        _fb_txt = '**板块回退**=关 ✓（= 旧行为：全A 兜底 0% ⇒ **全部不买** ✓）'
    return (f'enable_index_position_cap={on}（{_src("enable_index_position_cap")} ✓） | '
            f'规则1：ADX>{r["high_adx"]:g} 且 dir=上升 ⇒ {r["high_ratio"]:.0%} ✓ | '
            f'{_rule2} | '
            f'其他（{_other}）⇒ {r["other_ratio"]:.0%}'
            + ('（**不允许开仓** ✓）' if r['other_ratio'] <= 0 else '') + ' | '
            f'持仓 ≥ 上限 ⇒ **停开新仓** ✓（**加仓不受限** ✗✓；比较=`≥` ✗） | '
            + _fb_txt)
