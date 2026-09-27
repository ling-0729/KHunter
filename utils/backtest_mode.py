# -*- coding: utf-8 -*-
"""回测/实盘 **模式一键开关** ✓（2026-09-27 用户需求 ✓）

## 为什么需要它 ✗✓

三件事（个股 ADX 闸门 ✓、入池免评分 ✓、加仓开盘限幅 ✓）此前**只能靠请求 `config` 传参** ✗
—— yaml 里**一个键都没有** ✗ ⇒ Web / 流水线 / 实盘**无法切换** ✗✓。
本模块把三件事收成**一个模式** ✓，写在 `config/backtest_engine_config.yaml` ✓
（**回测与实盘共用该文件** ✓ ⇒ 一处改、两处生效 ✓✓）。

## 两种模式 ✓

| 模式 | 含义 | 三个开关 ✓ |
|---|---|---|
| **`legacy`** ✓（默认 ✗）| **原有模式** ✓ = **改造前行为** ✓ | `enable_stock_adx_filter=False` ✓、`pool_entry_mode=scored` ✓、`enable_add_open_rise_check=False` ✓ |
| **`adx`** ✓ | **ADX + 免评分** ✓ | `True` ✓、`veto_only` ✓、`True` ✓ |

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
    """一行说明 ✓（日志/排查用 ✓）"""
    m = resolve_mode(config, engine_config)
    p = PRESETS[m]
    return (f'回测模式={m} ✓（ADX闸门={"开" if p["enable_stock_adx_filter"] else "关"} ✓、'
            f'入池={p["pool_entry_mode"]} ✓、加仓开盘限幅='
            f'{"开" if p["enable_add_open_rise_check"] else "关"} ✓）')


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
