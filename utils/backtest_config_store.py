# -*- coding: utf-8 -*-
"""回测基础参数 **单一存储层** ✓（yaml 为源 ✓，DB 为**兼容镜像** ✗，2026-09-27）

## 背景 ✗✓（用户 2026-09-27 建议 ✓）

用户建议"**去掉 DB 表存储、都改为 yaml** ✓ + 前端可配置" ✓。方向对 ✓，但**不能直接删表** ✗：

| 风险 ✗ | 说明 |
|---|---|
| **12 个模块在读它** ✗ | `strategy_runner` ✓ / `pipeline_orchestrator` ✓ / `routes.py` ✓ / `khunter_buy_point_judge` ✓ / `khunter_support_calculator` ✓ / `khunter_data_processor` ✓ / `web_server` ✓ / `backtest_dao` ✓ / `db_initializer` ✓ … |
| yaml **无事务** ✗ | 多进程/多线程同时写会**互相覆盖** ✗（DB 有事务 ✓）|
| yaml **无权限/审计** ✗ | DB 那套 `created_at` 等元信息会丢 ✗ |
| **注释会被毁** ✗✓ | 朴素 `yaml.safe_dump` 会把 `backtest_engine_config.yaml` 里**大量注释清空** ✗（该文件注释很密 ✓）|

## 三步走 ✓（**可回滚** ✓，每步都能停 ✓）

| 步 | 内容 | 状态 |
|---|---|---|
| **① yaml 为源 + DB 镜像** ✓ | 读写都走 yaml ✓；同时**镜像回 DB** ✗ ⇒ 老读取方**不受影响** ✓✓ | ✅ **本模块** ✓ |
| ② 停写 DB ✓ | 各读取方切到本 store ✓；镜像可关（`mirror_db=False` ✓）| 待办 ✗ |
| ③ 删表 ✓ | 确认**无任何**读取方 ✓ 后走迁移删 ✓（**在此之前绝不删** ✗✓）| 待办 ✗ |

## 关键实现点 ✗✓

1. **保注释** ✓：只**替换 `backtest:` 块内各键的"值"** ✓（逐行正则 ✓），**不重写整个文件** ✗
   —— 该 yaml 的注释是**设计文档级**的 ✓，不能被 `safe_dump` 冲掉 ✗✓。
2. **原子写** ✓：先写临时文件 ✓ → `os.replace` ✓（避免半截文件 ✗）。
3. **DB 兼容回退** ✓：yaml 缺键时回落到 DB ✓（平滑升级 ✓）；DB 不可用也不报错 ✓。
"""
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: 目标 yaml ✓（与引擎/实盘**同一份** ✓）
YAML_PATH = Path(__file__).resolve().parents[1] / 'config' / 'backtest_engine_config.yaml'
#: 目标节 ✓（`backtest:` ✓）
YAML_SECTION = 'backtest'

#: 本节管辖的键 ✓（= 前端"回测配置"页 ✓ + 引擎读取的那些 ✓；**DB 也有这些列** ✓）
SECTION_KEYS: Tuple[str, ...] = (
    'score_threshold', 'hold_period', 'stop_loss', 'take_profit',
    'initial_capital', 'buy_amount', 'max_daily_buys',
)

#: **仅 yaml 有**的键 ✓（DB 无对应列 ✗ ⇒ **不镜像 DB** ✗）：
#: 模式 ✓ / 三个开关 ✓ —— 写在 `backtest:` 节里 ✓ ⇒ 用户"**看一个块就够**" ✓✓
#: ⚠️ 默认是**注释掉**的 ✗✓（否则"显式单键"会盖掉**模式预设** ✗ ⇒ 切模式失效 ✗）；
#:    写值时**自动取消注释** ✓，写 `None` ⇒ **自动还原为注释** ✓（= 跟随模式预设 ✓）。
EXTRA_KEYS: Tuple[str, ...] = (
    'backtest_mode', 'enable_stock_adx_filter',
    'enable_add_open_rise_check', 'pool_entry_mode',
)

#: 允许出现在**节外（顶层 ✓ 缩进 0）**的键 ✓（`backtest_mode` 顶部那个 ✓）
TOP_KEYS: Tuple[str, ...] = ('backtest_mode',)

#: 本 store 管辖的全部键 ✓
ALL_KEYS: Tuple[str, ...] = SECTION_KEYS + EXTRA_KEYS


def _read_text() -> str:
    try:
        return YAML_PATH.read_text(encoding='utf-8')
    except Exception as e:
        logger.error(f'读取 {YAML_PATH} 失败 ✗: {e}')
        return ''


def _block_span(text: str, section: str = YAML_SECTION) -> Optional[Tuple[int, int]]:
    """定位 `section:` 块的**行号范围** ✓（`[start, end)` ✓；找不到 ⇒ None ✓）"""
    lines = text.splitlines(keepends=True)
    start = None
    pat = re.compile(r'^%s:\s*(#.*)?$' % re.escape(section))
    for i, ln in enumerate(lines):
        if pat.match(ln):
            start = i
            continue
        if start is not None:
            # 块结束 ✓：遇到"顶格且非注释"的新键，或文件结束 ✓
            if ln.strip() and not ln.startswith((' ', '\t', '#')):
                return start, i
    if start is not None:
        return start, len(lines)
    return None


def load_yaml_section() -> Dict:
    """读 yaml `backtest:` 节 ✓（缺失/异常 ⇒ 空字典 ✓）"""
    text = _read_text()
    span = _block_span(text)
    if not span:
        return {}
    import yaml
    lines = text.splitlines(keepends=True)
    block = ''.join(lines[span[0]:span[1]])
    try:
        data = yaml.safe_load(block) or {}
        sec = data.get(YAML_SECTION) or {}
        return {k: v for k, v in sec.items() if k in ALL_KEYS}
    except Exception as e:
        logger.error(f'解析 `{YAML_SECTION}:` 节失败 ✗: {e}')
        return {}


def load_db_config() -> Dict:
    """**兼容回退** ✗✓：读 DB `backtest_config` ✓（无库/无行 ⇒ 空 ✓，不抛 ✓）"""
    try:
        import sqlite3
        db = Path(__file__).resolve().parents[1] / 'data' / 'stock_selection.db'
        if not db.exists():
            return {}
        conn = sqlite3.connect(str(db))
        cols = [r[1] for r in conn.execute('PRAGMA table_info(backtest_config)')]
        row = conn.execute('SELECT * FROM backtest_config LIMIT 1').fetchone()
        if not row:
            return {}
        d = dict(zip(cols, row))
        return {k: d[k] for k in SECTION_KEYS if k in d and d[k] is not None}
    except Exception as e:
        logger.debug(f'读 DB 回测配置失败（按空处理 ✓）: {e}')
        return {}


def load(prefer: str = 'yaml', db_fallback: bool = True) -> Dict:
    """**读回测基础参数** ✓（默认：yaml 为源 ✓，缺键回落 DB ✓）

    Returns:
        dict（只含 `SECTION_KEYS` ✓；键缺失表示"两边都没有" ✓）
    """
    out: Dict = {}
    if db_fallback:
        out.update(load_db_config())
    if prefer == 'yaml':
        out.update(load_yaml_section())          # yaml 覆盖 DB ✓（yaml 为源 ✓）
    return out


def source_map() -> Dict[str, str]:
    """每个键的**来源** ✓（`yaml` / `db` / `-` ✓）—— 前端可据此显示"值从哪来" ✓"""
    y, d = load_yaml_section(), load_db_config()
    return {k: ('yaml' if k in y else 'db' if k in d else '-') for k in SECTION_KEYS}


def _fmt_value(val) -> Optional[str]:
    """值 → yaml token ✓（`None` ⇒ **None** ✓ = 表示"还原为注释 / 跟随模式预设" ✓）"""
    if val is None:
        return None
    if isinstance(val, bool):
        return 'true' if val else 'false'
    if isinstance(val, str):
        return '"%s"' % val
    return str(val)


def _update_block(text: str, values: Dict) -> Tuple[str, list]:
    """**只改"值"** ✓（**保留全部注释** ✗✓），并支持"**注释 ⇄ 取消注释**" ✓

    · 写入具体值 ⇒ 若该行是**注释**（`# key: …` ✓）⇒ **自动取消注释** ✓✓
    · 写入 `None` ⇒ 若该行是**生效行** ⇒ **自动还原为注释** ✓✓（= "跟随 `backtest_mode` 预设" ✓）
    · **行尾注释**一律原样保留 ✓
    · 值没变时**不报告 changed** ✓（避免"假改动" ✓）

    Returns: (新文本, **真正改动**的键列表 ✓)
    """
    lines = text.splitlines(keepends=True)
    changed = []
    span = _block_span(text)
    if not span:
        logger.error(f'yaml 中找不到 `{YAML_SECTION}:` 节 ✗（未写入 ✓）')
        return text, []

    # ① `backtest:` 节内（**缩进** ✓）
    for i in range(span[0] + 1, span[1]):
        m = re.match(r'^(\s+)([A-Za-z_][A-Za-z0-9_]*)(\s*:\s*)(.*)$', lines[i])
        if m:
            key = m.group(2)
            if key not in values or key not in ALL_KEYS:
                continue
            token = _fmt_value(values[key])
            if token is None:
                if lines[i].lstrip().startswith('#'):
                    continue                              # 已是注释 ⇒ 无需动 ✓
                _eol = '\n' if lines[i].endswith('\n') else ''
                lines[i] = (f'{m.group(1)}# {key}: '
                            f'# （跟随 `backtest_mode` 预设 ✓）{_eol}')
                changed.append(key)
                continue
            rest = m.group(4)
            cm = re.search(r'\s+#', rest)
            comment = rest[cm.start():] if cm else ''
            eol = '\n' if lines[i].endswith('\n') else ''    # ⚠️ **必须保留行尾换行** ✗✓
            new_line = f'{m.group(1)}{key}{m.group(3)}{token}{comment}{eol}'
            if new_line != lines[i]:
                lines[i] = new_line
                changed.append(key)
            continue
        # 被**注释掉**的键 ✓ ⇒ 要写值就**取消注释** ✓
        cm2 = re.match(r'^(\s*)#\s*([A-Za-z_][A-Za-z0-9_]*)(\s*:\s*)(.*)$', lines[i])
        if cm2:
            key = cm2.group(2)
            if key not in values or key not in ALL_KEYS:
                continue
            token = _fmt_value(values[key])
            if token is None:
                continue                                   # 已是注释 ⇒ 保持 ✓
            _dm = re.search(r'\s+#', cm2.group(4))
            desc = cm2.group(4)[_dm.start():] if _dm else ''
            eol = '\n' if lines[i].endswith('\n') else ''
            new_line = f'{cm2.group(1)}{key}{cm2.group(3)}{token}{desc}{eol}'
            if new_line != lines[i]:
                lines[i] = new_line
                changed.append(key)

    # ② 节外**顶层**键 ✓（仅 `TOP_KEYS` ✓，如 `backtest_mode` ✓）
    for i, ln in enumerate(lines):
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)(\s*:\s*)(.*)$', ln)
        if not m or m.group(1) not in TOP_KEYS:
            continue
        key = m.group(1)
        if key not in values:
            continue
        token = _fmt_value(values[key])
        if token is None:
            continue
        rest = m.group(3)
        cm = re.search(r'\s+#', rest)
        comment = rest[cm.start():] if cm else ''
        new_line = f'{key}{m.group(2)}{token}{comment}'
        if new_line != lines[i]:
            lines[i] = new_line
            changed.append(key)

    return ''.join(lines), changed


def save(values: Dict, mirror_db: bool = True) -> Dict:
    """**写回测基础参数** ✓：**yaml 为主** ✓（保注释 ✓ 原子写 ✓）+ **DB 镜像** ✗（兼容 ✓）

    Args:
        values: 要写入的键值 ✓（只认 `SECTION_KEYS` ✓，其余忽略 ✗）
        mirror_db: 是否同时镜像回 DB ✓（默认 True ✓ —— **旧读取方仍能拿到新值** ✓✓）

    Returns:
        {'changed': [...], 'yaml_ok': bool, 'db_ok': bool, 'source': {...}}
    """
    # ⚠️ **保留 `None`** ✗✓ —— 它是"**还原为注释 / 跟随模式预设**"的信号 ✓（不能滤掉 ✗）
    vals = {k: v for k, v in (values or {}).items() if k in ALL_KEYS}
    res = {'changed': [], 'yaml_ok': False, 'db_ok': False}

    if vals:
        text = _read_text()
        new_text, changed = _update_block(text, vals)
        if changed and new_text != text:
            try:
                fd, tmp = tempfile.mkstemp(dir=str(YAML_PATH.parent),
                                           prefix='.btcfg-', suffix='.tmp')
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(new_text)
                os.replace(tmp, YAML_PATH)            # **原子替换** ✓
                res['yaml_ok'] = True
                res['changed'] = changed
                try:                                    # 让共享缓存失效 ✓
                    from utils.backtest_mode import clear_engine_yaml_cache
                    clear_engine_yaml_cache()
                except Exception:
                    pass
                logger.info(f'回测参数已写入 yaml ✓ `{YAML_SECTION}:` 节：{changed} ✓（注释保留 ✓）')
            except Exception as e:
                logger.error(f'写入 yaml 失败 ✗: {e}（未改动原文件 ✓）')
        else:
            res['yaml_ok'] = True                       # 无变化也算成功 ✓

    if mirror_db:
        # ⚠️ **只镜像 DB 有的列** ✗✓（`backtest_mode` 等 4 键 DB 没有 ✗ ⇒ 不能镜像 ✗）
        #   `None`（= 还原信号 ✗）也**不镜像** ✗（避免把 DB 列写成 NULL ✗）
        res['db_ok'] = _mirror_to_db({k: v for k, v in vals.items()
                                      if k in SECTION_KEYS and v is not None})
    res['source'] = source_map()
    return res


def _mirror_to_db(values: Dict) -> bool:
    """把值**镜像**回 DB `backtest_config` ✓（失败只告警 ✗，不影响 yaml 主存储 ✓）"""
    if not values:
        return True
    try:
        import sqlite3
        db = Path(__file__).resolve().parents[1] / 'data' / 'stock_selection.db'
        conn = sqlite3.connect(str(db))
        cols = [r[1] for r in conn.execute('PRAGMA table_info(backtest_config)')]
        if not conn.execute('SELECT 1 FROM backtest_config LIMIT 1').fetchone():
            conn.execute(
                'INSERT INTO backtest_config (config_name, %s) VALUES (?, %s)'
                % (', '.join(values), ', '.join('?' * len(values))),
                ['默认配置'] + list(values.values()))
        else:
            sets = ', '.join(f'{k}=?' for k in values)
            conn.execute(f'UPDATE backtest_config SET {sets}', list(values.values()))
        conn.commit()
        logger.info(f'回测参数已**镜像**回 DB ✓（{list(values)} ✓）—— 旧的 DB 读取方不受影响 ✓')
        return True
    except Exception as e:
        logger.warning(f'镜像回 DB 失败 ✗（yaml 已写入 ✓，不影响主存储 ✓）: {e}')
        return False
