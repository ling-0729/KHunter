# -*- coding: utf-8 -*-
"""回测/实盘 **模式一键开关** ✓（2026-09-27 用户需求 ✓）

## 为什么需要它 ✗✓

三件事（个股 ADX 闸门 ✓、入池免评分 ✓、加仓开盘限幅 ✓）此前**只能靠请求 `config` 传参** ✗
—— yaml 里**一个键都没有** ✗ ⇒ Web / 流水线 / 实盘**无法切换** ✗✓。
本模块把三件事收成**一个模式** ✓，写在 `config/backtest_engine_config.yaml` ✓
（**回测与实盘共用该文件** ✓ ⇒ 一处改、两处生效 ✓✓）。

## 两种模式 ✓

| 模式 | 含义 | 开关 + 入场口径 ✓ |
|---|---|---|
| **`legacy`** ✓（默认 ✗）| **原有模式** ✓ = **改造前行为** ✓ | `enable_stock_adx_filter=False` ✓、`pool_entry_mode=scored` ✓、`enable_add_open_rise_check=False` ✓ |
| **`adx`** ✓ | **ADX + 免评分** ✓ | `True` ✓、`veto_only` ✓、`True` ✓；★ 入场**区间口径** ✓ `21 < ADX < 30` ∧ `dir=上升` ✓（`adx_entry_mode=range` ✓ / `adx_entry_range=[21,30]` ✓；⚠️ **上限只约束首仓** ✗✓）|

## 优先级 ✓（**越靠前越高** ✗✓）

```
① 显式单键（请求 config 顶层 / yaml 顶层 / yaml 节内）
② backtest_mode 预设        ← 本文档这一层 ✓
③ 硬默认（legacy ✓ ⇒ 零行为变化 ✓）
```

⇒ 模式只是"**批量默认值**" ✓：想微调某一项 ✓，**单独写那一个键**即可覆盖 ✓✓
（例：`backtest_mode: adx` + `enable_add_open_rise_check: false` ⇒ 只关加仓限幅 ✓）。

## 配置位置 ✓

`config/backtest_engine_config.yaml` ✓：

```yaml
backtest_mode: legacy        # legacy（原有 ✓）| adx（ADX+免评分 ✓）
```
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

MODE_LEGACY = 'legacy'
MODE_ADX = 'adx'

#: 模式别名 ✓（大小写/写法不敏感 ✓）
MODE_ALIASES = {
    'legacy': MODE_LEGACY, 'off': MODE_LEGACY, 'original': MODE_LEGACY,
    'old': MODE_LEGACY, 'base': MODE_LEGACY, 'none': MODE_LEGACY,
    '原': MODE_LEGACY, '原有': MODE_LEGACY, '原有模式': MODE_LEGACY,
    'adx': MODE_ADX, 'adx_noscore': MODE_ADX, 'adx+': MODE_ADX,
    'adx免评分': MODE_ADX, '免评分': MODE_ADX, 'noscore': MODE_ADX,
}

#: 模式 → 三开关预设 ✓（**唯一事实源** ✓）
PRESETS: Dict[str, Dict] = {
    MODE_LEGACY: {
        'enable_stock_adx_filter': False,      # 个股 ADX 闸门 ✗
        'pool_entry_mode': 'scored',           # 入池：否决 + 评分门槛 ✓（原口径 ✓）
        'enable_add_open_rise_check': False,   # 加仓开盘限幅 ✗（原行为：加仓不过滤 ✓）
    },
    MODE_ADX: {
        'enable_stock_adx_filter': True,       # 个股 ADX 闸门 ✓（首仓 + 加仓 ✓）
        'pool_entry_mode': 'veto_only',        # **免评分** ✓（只排除一票否决 ✓）
        'enable_add_open_rise_check': True,    # 加仓也做开盘 ±4% ✓
        # ★【2026-09-28 用户口径 ✓】**当日仓位上限** ✓（**只约束"开新仓"** ✗加仓）
        #   ⚠️ 用户 2026-09-28 ✓：原「大盘 ADX 硬闸门」**整体取消** ✗
        #     （"这个规则取消，**由仓位上限总控**" ✓）⇒ 本预设**不再有**
        #     `enable_index_adx_filter` ✓（键已一并删除 ✗ —— 不留半开档 ✗，
        #      避免又出现"两套口径相冲"✗）
        #   规则 ✓：大盘 `ADX>25` ∧ `dir上升` ⇒ 100% ✓；`ADX<18` ∧ `dir上升` ⇒ 50% ✓；
        #   **持仓 > 上限 ⇒ 停止开新仓** ✓（**加仓不受限** ✓）；
        #   ⚠️ 阈值/比例**全部可配** ✓（`index_cap_high_adx` / `index_cap_low_adx` /
        #     `index_cap_high_ratio` / `index_cap_low_ratio` / `index_cap_other_ratio` ✓）
        'enable_index_position_cap': True,
        # ★【2026-09-28 用户口径 ✓】个股入场**区间口径** ✓（**显式写进预设** ⇒ 自证 ✓）
        #   `21 < ADX(T-1) < 30` ✓（开区间 ✓）∧ `dir=上升` ✓；
        #   ⚠️ **上限只约束「新买入（首仓）」** ✗✓ —— **加仓不校验上限** ✓（下界仍生效 ✓）。
        'adx_entry_mode': 'range',
        'adx_entry_range': [21, 30],
    },
}

_MODE_KEYS = ('backtest_mode', 'mode')


def _holders(config: Dict = None, engine_config: Dict = None):
    """按优先级产出"取值容器" ✓（**越靠前越高** ✓）

    顺序 ✓：请求 config ✓ > yaml 顶层 ✓ > **yaml `backtest:` 节** ✓
    —— 把节也纳入 ✓，是为了让用户"**一个块管全部**" ✓✓
    （`backtest_mode` / 三个开关 / 基础参数 都写在同一节里 ✓）。
    """
    cfg = config or {}
    ec = engine_config if engine_config is not None else load_engine_yaml()
    ec = ec or {}
    yield cfg
    yield ec
    sec = ec.get('backtest')
    if isinstance(sec, dict):
        yield sec


def resolve_mode(config: Dict = None, engine_config: Dict = None) -> str:
    """解析当前模式 ✓（默认 `legacy` ✗ ⇒ **不改变任何历史行为** ✓）

    优先级 ✓：请求 `config['backtest_mode']` > yaml 顶层 > yaml `backtest:` 节 > 默认 `legacy` ✓
    """
    raw = None
    for holder in _holders(config, engine_config):
        for k in _MODE_KEYS:
            if holder.get(k) is not None:
                raw = holder.get(k)
                break
        if raw is not None:
            break
    if raw is None:
        return MODE_LEGACY
    mode = MODE_ALIASES.get(str(raw).strip().lower())
    if not mode:
        logger.warning(f'未知回测模式 {raw!r} ⇒ 回落 `{MODE_LEGACY}` ✓'
                       f'（已知：legacy / adx ✓）')
        return MODE_LEGACY
    return mode


def preset(config: Dict = None, engine_config: Dict = None) -> Dict:
    """当前模式的**三开关预设** ✓"""
    return dict(PRESETS[resolve_mode(config, engine_config)])


def effective(key: str, config: Dict = None, engine_config: Dict = None,
              default=None):
    """**单键生效值** ✓ = 显式键（**请求 config 或 yaml 顶层** ✓）> 模式预设 ✓ > 硬默认 ✓

    三个消费点（`stock_adx_filter` ×2 ✓、`pool_entry_rules` ✓）都走这里 ✓ ⇒ **单一口径** ✓✓。

    ⚠️ **顺序很关键** ✗✓（曾写错并被单测抓出 ✓）：**两处显式单键都必须排在模式预设之前** ✓
    —— 因为**最常见的微调方式就是在同一份 yaml 里写单键** ✗✓
    （例：`backtest_mode: adx` + `enable_add_open_rise_check: false` ⇒ 必须**关**掉 ✓）。
    若把 yaml 单键排在预设之后 ✗ ⇒ 用户在 yaml 里怎么改都**不生效** ✗✗。
    """
    for holder in _holders(config, engine_config):   # ① 请求 config ✓ ② yaml 顶层 ✓ ③ yaml `backtest:` 节 ✓
        if key in holder and holder.get(key) is not None:
            return holder[key]
    pres = preset(config, engine_config)             # ④ `backtest_mode` 预设 ✓
    if key in pres:
        return pres[key]
    return default                                   # ⑤ 硬默认 ✓


def describe(config: Dict = None, engine_config: Dict = None) -> str:
    """一行说明 ✓（日志/排查用 ✓）—— ★ 打的是**生效值** ✓，不是"模式预设值" ✗✓

    ★★【2026-10-07 修复 ✓】**必须反映"显式单键"** ✗→✓ ★★
      事故 ✗✓（用户反馈："**实盘模式下，入池方式和设置的参数不一致**"✗）：
        本函数原先直接用 `PRESETS[mode]` ✗ ⇒ **完全忽略显式单键** ✗ ⇒
        用户 yaml 里写着 `pool_entry_mode: "direct"` ✓（**生效值确实是 `direct`** ✓，
        由 `effective()` 取到 ✓），日志却照报 `veto_only` ✗ ⇒
        **是日志在误导** ✗✓ —— 排查会一路往"实盘没接上/参数没传"✗ 的方向去 ✓。
      ⇒ 现改用 `effective()` 逐键取**生效值** ✓，并标出**来源** ✓：
        `（显式 ✓）` / `（模式预设 ✓）` / `（内置默认 ✓）` ✓
        ⇒ 一眼看出"**我改的那个键到底生效了没有**" ✓✓。

    ⚠️ 骨架保持 `回测模式=<m> ✓（ADX闸门=… ✓、入池=… ✓、加仓开盘限幅=… ✓）` ✓ 不变 ✗✓
      （日志检索/测试都按它找 ✓；只是每项后面**追加**了来源 ✓）。
    """
    m = resolve_mode(config, engine_config)
    pres = PRESETS[m]
    parts = []
    for key, label, is_flag in (('enable_stock_adx_filter', 'ADX闸门', True),
                                ('pool_entry_mode', '入池', False),
                                ('enable_add_open_rise_check', '加仓开盘限幅', True)):
        val = effective(key, config, engine_config, default=pres.get(key))
        txt = ('开' if val else '关') if is_flag else str(val)
        src = ('显式' if is_explicit(key, config, engine_config)
               else ('模式预设' if key in pres else '内置默认'))
        parts.append(f'{label}={txt}（{src} ✓）')
    return f'回测模式={m} ✓（' + '、'.join(parts) + '）'


def is_explicit(key: str, config: Dict = None, engine_config: Dict = None) -> bool:
    """该键是否**显式**给出 ✓ —— **三处任一**都算 ✓（= `effective` 的三个来源层 ✓）：

        ① 请求 `config` ✓（Web/流水线/DB + 已并入的 yaml `backtest:` 节 ✓）
        ② yaml **顶层** ✓  ③ yaml `backtest:` **节** ✓

    ★【2026-09-28】从 `BacktestEngine.log_backtest_params._explicit` **提公共实现** ✓
      ⇒ 回测参数快照 ✓ 与 ADX 摘要（`describe_adx_params` ✓）**同一判据** ✓
      —— 免得两处"来源"标注各写一份、日久漂移 ✗✓。

    ⚠️ 必须**三处都算** ✗✓（**实测踩过** ✓）：只看 `config` 会把 **yaml 顶层**键
      （如 `enable_limit_up_check` ✓）误标成"内置默认" ✗。
    """
    for holder in _holders(config, engine_config):
        if isinstance(holder, dict) and key in holder and holder.get(key) is not None:
            return True
    return False


# ============================================================================
# 【2026-09-27】`config/backtest_engine_config.yaml` **统一加载 + 回测默认值合并**
# ----------------------------------------------------------------------------
# 背景 ✗✓：回测参数此前散在三处（DB `backtest_config` ✓ / 请求 config ✓ / 本 yaml ✓），
#   而 yaml 里**只有少数键被个别读取** ✗ ⇒ 写进去**不生效** ✗✓。
# 方案 ✓：引擎入口统一把 yaml 的 `backtest:` 节**作为默认值合并** ✓（`setdefault` ✓）
#   ⇒ 优先级 = **请求 config（Web/流水线/DB ✓）> yaml `backtest:` 节 > 引擎内置默认** ✓✓
#   ⇒ **不覆盖**任何显式传入 ✓ ⇒ 把值写成"与内置默认相同"时 **行为零变化** ✓✓。
# ============================================================================

_ENGINE_YAML_CACHE: Optional[Dict] = None


def load_engine_yaml(use_cache: bool = True) -> Dict:
    """加载 `config/backtest_engine_config.yaml` ✓（**进程内缓存** ✓，失败返回空 ✓）

    回测引擎 / 实盘运行器 / 个股 ADX 闸门**共用本加载器** ✓ ⇒ 单一口径 ✓✓。
    """
    global _ENGINE_YAML_CACHE
    if use_cache and _ENGINE_YAML_CACHE is not None:
        return _ENGINE_YAML_CACHE
    cfg: Dict = {}
    try:
        import yaml
        from pathlib import Path as _P
        p = _P(__file__).resolve().parents[1] / 'config' / 'backtest_engine_config.yaml'
        if p.exists():
            with open(p, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        else:
            logger.warning(f'回测引擎配置文件不存在: {p} ⇒ 用内置默认 ✓')
    except Exception as e:
        logger.warning(f'读取回测引擎配置失败（按空处理 ✓）: {e}')
    if use_cache:
        _ENGINE_YAML_CACHE = cfg
    return cfg


def clear_engine_yaml_cache() -> None:
    """清缓存 ✓（改了 yaml 又不想重启进程时用 ✓；测试用 ✓）"""
    global _ENGINE_YAML_CACHE
    _ENGINE_YAML_CACHE = None


def merge_backtest_defaults(config: Dict,
                            engine_config: Dict = None) -> Dict:
    """把 yaml `backtest:` 节作为**默认值**并入回测 `config` ✓

    - **只补缺** ✗✓（`setdefault` 语义 ✓）：请求 config（含 DB 配置 ✓）**永远优先** ✓
    - 返回**新字典** ✓（不改调用方入参 ✓）
    - 会记录补齐了哪些键 ✓（便于确认"yaml 到底有没有生效" ✓✓）
    """
    out = dict(config or {})
    ec = engine_config if engine_config is not None else load_engine_yaml()
    section = (ec or {}).get('backtest') or {}
    filled = []
    for k, v in section.items():
        if out.get(k) is None:
            out[k] = v
            filled.append(k)
    if filled:
        logger.info(f'回测配置 ✓ 由 yaml `backtest:` 节补齐 {len(filled)} 项：'
                    f'{", ".join(filled)}（请求/DB 未传的项才补 ✓）')
    return out
