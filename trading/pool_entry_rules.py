# -*- coding: utf-8 -*-
"""股票池「入池规则」（回测 + 实盘共用，参数化）

背景
----
策略切换会清空股票池；若入池门槛过严（评分阈值），容易出现
**股票池不足 → 持仓不足**。故提供"简化入池"开关：

- `simplified=True`（**简易评分**，2026-09-11 调整）：先排除一票否决（事件 / 基本面），
  通过的只计算**资金面得分**（`score` = 资金面得分，相当于资金面权重 100%），
  再按 `score >= score_threshold` 入池。
- `simplified=False`（标准评分）：否决票 + 五维度加权综合评分 `>= score_threshold`。

两种模式的**过滤规则相同**（否决票 + 评分达标），差异只在"分数怎么算"。

入池模式（`pool_entry_mode` ✓，2026-09-26 起 ✓，2026-09-29 增第三档 ✓）
------------------------------------------------------------------
| 模式 | 一票否决 | 评分门槛 | 说明 |
|---|---|---|---|
| `scored`（默认 ✓） | **算** ✓ | **算** ✓ | 与历史行为一致 ✓ |
| `veto_only` ✓ | **算** ✓ | 不算 ✗ | 去掉评分，**否决仍拦** ✓ |
| `direct` ✓（2026-09-29 ✓） | **不算** ✗ | 不算 ✗ | ★ **策略选出直接入池** ✓（用户要求 ✓） |

⚠️ `direct` 只在**入池**这一步放行 ✗✓ —— 买入前置过滤 / ADX 闸门 / 仓位上限 / 涨停板等
   **照旧生效** ✓（详见 `POOL_ENTRY_MODE_DIRECT` 注释 ✓）。

配置来源（优先级从高到低）
--------------------------
1. 传入 `config['pool_entry_simplified']`（回测/实盘请求参数）
2. `config/backtest_engine_config.yaml` → `pool_entry.simplified`
3. 内置默认 `DEFAULT_SIMPLIFIED = False`（向后兼容）
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# 内置默认：保持向后兼容（如需简化请在 yaml 或请求参数中显式开启）
DEFAULT_SIMPLIFIED = False

# 持仓股自动入池（当日卖出不计）：默认 **开启**
DEFAULT_AUTO_ADD_HOLDINGS = True

# ==================== 入池模式（2026-09-26 新增 ✓） ====================
#: 现状 ✓：**否决票 + 评分达标**（评分口径由 `simplified` 决定 ✓）
POOL_ENTRY_MODE_SCORED = 'scored'
#: **去除评分** ✗✓：**只排除一票否决** ✓，**不看 `score`** ✗（用户 2026-09-26 提出 ✓）
POOL_ENTRY_MODE_VETO_ONLY = 'veto_only'
#: ★★【2026-09-29 用户要求 ✓】**直通入池**：**既不看评分 ✗、也不看一票否决** ✗✓ ★★
#:   用户原话 ✓："现在买入条件比较严格，建议去除股票评分（**包括一票否决**）环节，
#:   策略选出的股票**直接入池** ✓。通过参数控制 ✓"
#:   ⇒ 语义 ✓：**策略选出什么就入池什么** ✓（`_score_stocks` 整个**不再调用** ✗ ⇒
#:     连五维打分与各维度否决（资金面/事件/基本面）都**不计算** ✓ ⇒ 既省时 ✓ 又无否决 ✓）；
#:   ⚠️ **只管"入池"这一步** ✗✓ —— 其它闸门（**买入前置过滤** ✓ ADX 闸门 ✓ **仓位上限** ✓、
#:     涨停/一字板、加仓开盘限幅 ✓）**全部照旧生效** ✓（用户未要求去掉它们 ✓）；
#:   ⚠️ 与 `veto_only` 的差别 ✗✓：`veto_only` **仍判否决** ✓（只是不算分 ✗）⇒
#:     被资金面/事件否决的股票**依然入不了池** ✗；`direct` 则**一律放行** ✓。
POOL_ENTRY_MODE_DIRECT = 'direct'
#: 别名 ✓（大小写/写法不敏感 ✓）
POOL_ENTRY_MODE_ALIASES = {
    'scored': POOL_ENTRY_MODE_SCORED, 'standard': POOL_ENTRY_MODE_SCORED,
    'score': POOL_ENTRY_MODE_SCORED, 'default': POOL_ENTRY_MODE_SCORED,
    'veto_only': POOL_ENTRY_MODE_VETO_ONLY, 'veto': POOL_ENTRY_MODE_VETO_ONLY,
    'no_score': POOL_ENTRY_MODE_VETO_ONLY, 'noscore': POOL_ENTRY_MODE_VETO_ONLY,
    'off': POOL_ENTRY_MODE_VETO_ONLY, '去除评分': POOL_ENTRY_MODE_VETO_ONLY,
    # ★ 直通 ✓（2026-09-29 ✓）—— ⚠️ **不**复用 `off` ✗（那是 `veto_only` ✓，语义不同 ✗）
    'direct': POOL_ENTRY_MODE_DIRECT, 'straight': POOL_ENTRY_MODE_DIRECT,
    'bypass': POOL_ENTRY_MODE_DIRECT, 'no_filter': POOL_ENTRY_MODE_DIRECT,
    'nofilter': POOL_ENTRY_MODE_DIRECT, 'skip_all': POOL_ENTRY_MODE_DIRECT,
    'all': POOL_ENTRY_MODE_DIRECT, '直通': POOL_ENTRY_MODE_DIRECT,
    '直接入池': POOL_ENTRY_MODE_DIRECT, '无否决': POOL_ENTRY_MODE_DIRECT,
}


def resolve_pool_entry_mode(config: Dict = None,
                            engine_config: Dict = None) -> str:
    """解析**入池模式** ✓（默认 `scored` ✗ ⇒ **与现状完全一致** ✓，不改变历史结果 ✓）

    优先级 ✓：
      1. `config['pool_entry_mode']` ✓
      2. yaml `pool_entry.mode` ✓ / 顶层 `pool_entry_mode` ✓
      3. **兜底推导** ✓：`score_threshold` 为 `None`/`0` ⇒ `veto_only` ✓（旧配置也能"去评分" ✓）
      4. 否则 `scored` ✓

    ⚠️ 为什么要"去评分"✗✓（用户 2026-09-26 ✓）：换源后**资金面均分 43.1 → 20.4** ✗，
       而门槛仍是 **60** ✗ ⇒ 该门槛已**不可达** ✗ ⇒ 池子被**系统性饿死** ✗
       （这正是上次回测质量回归的放大器 ✗）。⇒ 与其在坏口径上卡分 ✗，
       不如**交给 ADX 与策略把关** ✓（§5.6 ✓）。
    """
    cfg = config or {}
    ec = engine_config or {}
    section = ec.get('pool_entry') or {}
    # ★★★★【2026-10-07 修复 ✓】补上 **yaml `backtest:` 节**这一层来源 ✗→✓ ★★★★
    #   事故 ✗✓（用户反馈："**实盘模式下，入池方式和设置的参数不一致**"✗）：
    #     用户在前端把「入池模式」设成 `direct` ✓，它被写进
    #     `config/backtest_engine_config.yaml` 的 **`backtest:` 节内**（缩进 2 格 ✓），
    #     而本函数原先只查 ① `cfg` ✓ ② `pool_entry.mode` ✓ ③ **顶层** `ec['pool_entry_mode']` ✗
    #     ⇒ **节内的键读不到** ✗ ⇒ 回落到 `backtest_mode` 预设 `veto_only` ✗✓
    #     ⇒ 表现就是"**设置与实盘不一致**"✓ —— ⚠️ 这是**真没生效** ✗，不是日志问题 ✗。
    #   ⚠️ 为什么必须补 ✗✓：`utils/backtest_mode._holders()`（三开关的**单一事实源** ✓）
    #     **本来就认节** ✓ ⇒ 于是出现"`effective('pool_entry_mode')` = `direct` ✓、
    #     `resolve_pool_entry_mode()` = `veto_only` ✗"的**两套口径打架** ✗✓
    #     （本项目大忌 ✓ —— 日志、快照、实际行为会三方不一致 ✗）。
    #   ⇒ 顺序与 `backtest_mode._holders` **保持一致** ✗✓：
    #     `cfg` > `pool_entry.mode` > yaml **顶层** > yaml **`backtest:` 节** ✓。
    raw = None
    for holder, key in ((cfg, 'pool_entry_mode'), (section, 'mode'),
                        (ec, 'pool_entry_mode'),
                        (ec.get('backtest') or {}, 'pool_entry_mode')):
        if key in holder and holder.get(key) is not None:
            raw = holder.get(key)
            break
    if raw is not None:
        mode = POOL_ENTRY_MODE_ALIASES.get(str(raw).strip().lower())
        if mode:
            return mode
        logger.warning(f'未知入池模式 {raw!r} ⇒ 回落 `{POOL_ENTRY_MODE_SCORED}` ✓'
                       f'（已知：scored / veto_only / direct ✓）')
        return POOL_ENTRY_MODE_SCORED

    # 兜底推导 ✓：阈值为 None/0 ⇒ 等同于"去评分" ✓
    #   ⚠️ 顺序 ✗✓：显式 `score_threshold<=0` **优先于** `backtest_mode` 预设 ✓
    #      （它也是"显式配置" ✓ ⇒ 不该被模式盖掉 ✗）
    #   ⚠️【2026-09-29 口径确认 ✓】这里**仍然只推到 `veto_only`** ✗（**不**推到 `direct` ✗）：
    #      老配置把阈值写成 0 ⇒ 本意是"别卡分" ✓，**不是**"连否决也别拦" ✗
    #      ⇒ 推到 `direct` 会**静默去掉一票否决** ✗✓（改动历史语义 ✗）⇒ 必须显式指名 `direct` ✓。
    thr = None
    for holder, key in ((cfg, 'score_threshold'), (section, 'score_threshold')):
        if key in holder:
            thr = holder.get(key)
            break
    if thr is not None:
        try:
            if float(thr) <= 0:
                return POOL_ENTRY_MODE_VETO_ONLY
        except (TypeError, ValueError):
            pass

    # ★ **yaml 顶层 / `backtest:` 节 显式键** ✓（2026-09-27：节内也可写 ✓）
    #   ⚠️ 这里做**别名归一** ✓（2026-09-29 ✓）：以前只做**字面相等** ✗ ⇒
    #      `direct` 的别名（`直通` / `无否决` ✓）在 yaml 里会被**静默忽略** ✗✓。
    from utils.backtest_mode import effective
    _v = effective('pool_entry_mode', cfg, ec, None)
    if _v is not None:
        _norm = POOL_ENTRY_MODE_ALIASES.get(str(_v).strip().lower())
        if _norm:
            return _norm

    # ★ **模式预设** ✓：`backtest_mode: adx` ⇒ `veto_only` ✓（**免评分** ✓）
    from utils.backtest_mode import MODE_ADX, resolve_mode
    if resolve_mode(cfg, ec) == MODE_ADX:
        return POOL_ENTRY_MODE_VETO_ONLY
    return POOL_ENTRY_MODE_SCORED


# ==================== 股票池「移除原因」归类（飞书简报 + 本地日报共用） ====================
# 【2026-09-24】把 `StrategyRunner._check_pool_removal` 产生的原因文本归类到固定桶 ✓，
#   供「飞书简报」与「本地 Markdown 日报」的"移除原因分布"共用同一份口径 ✓
#   （避免两处各写一份而漂移 ✗）。
#   注意：归类**只影响统计展示** ✓，不参与任何移除判定 ✓（判定仍在 strategy_runner ✓）。
POOL_REMOVAL_REASON_BUCKETS = (
    ('跌破支撑位', ('支撑位',)),
    ('趋势走弱', ('MA10', '斜率', 'R²', 'R2')),
    ('资金流向', ('资金', '主力', '大单', '小单', '出货')),
)


def classify_pool_removal_reason(reason: str) -> str:
    """把单条移除原因归类到固定桶 ✓；未命中任何关键词 → '其他' ✓"""
    text = str(reason or '')
    for label, keys in POOL_REMOVAL_REASON_BUCKETS:
        if any(k in text for k in keys):
            return label
    return '其他'


def summarize_pool_removal_reasons(reasons) -> Dict[str, int]:
    """统计"移除原因分布" ✓

    Args:
        reasons: 可迭代对象，每项为一只股票的**原因串**
                 （可能含多个原因，以 '; ' 分隔，如 `跌破支撑位12.00-3.2%` ✓）

    Returns:
        dict: {归类名: 计数}；按**原因条目**计数 ✓
              （一只股票命中多个条件会各计 1，例：趋势走弱 2 只 ✓）
    """
    counts: Dict[str, int] = {}
    for reason in (reasons or []):
        for one in [r for r in str(reason or '').split('; ') if r]:
            label = classify_pool_removal_reason(one)
            counts[label] = counts.get(label, 0) + 1
    return counts


def resolve_pool_entry_simplified(config: Dict = None,
                                  engine_config: Dict = None) -> bool:
    """解析"简化入池"开关（见模块 docstring 的优先级说明）"""
    cfg = config or {}
    if 'pool_entry_simplified' in cfg:
        return bool(cfg.get('pool_entry_simplified'))

    ec = engine_config or {}
    section = ec.get('pool_entry') or {}
    if 'simplified' in section:
        return bool(section.get('simplified'))
    if 'pool_entry_simplified' in ec:
        return bool(ec.get('pool_entry_simplified'))
    # ★【2026-10-07 修复 ✓】同样补上 **yaml `backtest:` 节** ✓（与 `resolve_pool_entry_mode`
    #   同一层来源、同一顺序 ✓ —— 两处漏一层就会再现"设置不生效 / 口径打架"✗✓）
    _sec = ec.get('backtest') or {}
    if 'pool_entry_simplified' in _sec:
        return bool(_sec.get('pool_entry_simplified'))

    return DEFAULT_SIMPLIFIED


def resolve_auto_add_holdings(config: Dict = None,
                              engine_config: Dict = None) -> bool:
    """解析"持仓股自动入池"开关（默认 **True**）

    持仓股（当日卖出不计）自动回到候选池，使其能参与择时 `add` 判断（加仓）。
    优先级：`config['auto_add_holdings_to_pool']` > yaml `pool_entry.auto_add_holdings` > True
    """
    cfg = config or {}
    if 'auto_add_holdings_to_pool' in cfg:
        return bool(cfg.get('auto_add_holdings_to_pool'))

    ec = engine_config or {}
    section = ec.get('pool_entry') or {}
    if 'auto_add_holdings' in section:
        return bool(section.get('auto_add_holdings'))
    if 'auto_add_holdings_to_pool' in ec:
        return bool(ec.get('auto_add_holdings_to_pool'))

    return DEFAULT_AUTO_ADD_HOLDINGS


def filter_candidates(scored_stocks: List[Dict], score_threshold: float = 60,
                      simplified: bool = False, mode: str = None) -> List[Dict]:
    """按入池规则筛选候选股票

    统一规则（2026-09-11 调整）：**`veto_flag == False` 且 `score >= score_threshold`**

    说明：`score` 的含义由评分方式决定（见 `BacktestScoreCalculator`）——
      - **简化模式**：`score` = **资金面得分**（只算资金面维度，相当于权重 100%）
      - 标准模式：`score` = 五维度加权综合评分
    两种模式都做阈值比较，因此 `simplified` 只影响"分数怎么算"，
    不再影响过滤规则（此前简化模式会跳过评分比较，导致池子过大且无择优）。

    ★ **`mode`（2026-09-26 新增 ✓；2026-09-29 增 `direct` ✓）**：
      · `scored`（默认 ✗）✓：否决票 + 评分达标 ✓ —— **与历史行为一致** ✓
      · `veto_only` ✓：**只排除一票否决** ✓、**不看 `score`** ✗（**去除评分** ✓）；
        此时 `score_threshold` **被忽略** ✗（并记 INFO ✓，便于归因 ✓）
      · `direct` ✓（2026-09-29 ✓）：**一律放行** ✓ —— 既不看 `veto_flag` ✗ 也不看 `score` ✗
        （用户口径："策略选出的股票**直接入池**"✓；调用方通常搭配
        `should_skip_scoring()` ✓ **连评分都不跑** ✗ ⇒ 本函数的 `direct` 分支
        主要用于"评分已跑过、但仍要全放行"的兜底 ✓）

    Args:
        scored_stocks: 评分后的股票列表（每项含 `score` / `veto_flag`）
        score_threshold: 入池评分阈值（仅 `scored` 模式生效 ✓）
        simplified: 兼容用参数（分数口径差异在评分器中体现）
        mode: 入池模式 ✓（`None` ⇒ `scored` ✓；支持别名 ✓）

    Returns:
        list: 入池候选（保持原顺序 ✓）
    """
    _raw = str(mode).strip().lower() if mode else POOL_ENTRY_MODE_SCORED
    # ⚠️ 归一别名 ✓（2026-09-29 ✓）：调用方可能直接传 `直通` / `无否决` ✓ ⇒ 别让它们**静默变 scored** ✗✓
    _mode = POOL_ENTRY_MODE_ALIASES.get(_raw, _raw)
    _veto_only = (_mode == POOL_ENTRY_MODE_VETO_ONLY)
    _direct = (_mode == POOL_ENTRY_MODE_DIRECT)

    # ★ 直通 ✓：**不过滤任何一项** ✗✓（连 `veto_flag` 都不看 ✗ —— 用户明确要求"包括一票否决" ✓）
    if _direct:
        out = list(scored_stocks or [])
        logger.info(f'【入池规则】`direct`（**直通入池** ✓）：策略选出 {len(out)} 只'
                    f'**全部入池** ✓（既不看评分 ✗ 也不看一票否决 ✗；'
                    f'`score_threshold={score_threshold}` 已忽略 ✗）')
        return out

    out: List[Dict] = []
    for stock in (scored_stocks or []):
        try:
            if stock.get('veto_flag', False):
                continue
            if not _veto_only:
                try:
                    score = float(stock.get('score') or 0)
                except (TypeError, ValueError):
                    score = 0.0
                if score < float(score_threshold):
                    continue
        except Exception as e:      # 单项异常不影响整体
            logger.debug(f'入池过滤异常，已跳过该项: {e}')
            continue
        out.append(stock)
    if _veto_only:
        logger.info(f'【入池规则】`veto_only`（**去除评分** ✗）：'
                    f'{len(out)} 只通过一票否决 ✓（`score_threshold={score_threshold}` 已忽略 ✗）')
    return out


def should_skip_scoring(config: Dict = None,
                        engine_config: Dict = None) -> bool:
    """★★【2026-09-29 用户要求 ✓】本模式是否要**连评分都不跑** ✗→✓ ★★

    用户原话 ✓："去除股票评分（**包括一票否决**）环节，策略选出的股票**直接入池**" ✓
    ⇒ 只有 `pool_entry_mode=direct` 才为 `True` ✓（`scored` / `veto_only` 都要跑评分 ✓）：
      · `scored`：五维打分 + 看门槛 ✓（必须算分 ✓）
      · `veto_only`：**不算分** ✓，但**仍要判一票否决** ✗ ⇒ 评分器还得跑 ✗（`veto_only=True`
        下只判否决 ✓）；故**不能**跳过 ✗
      · `direct`：否决与分数**都不需要** ✗ ⇒ 整个 `_score_stocks` / `calculate_batch_scores`
        **不调用** ✓ ⇒ 直接省掉每只股票的五维评分开销 ✓（回测提速 ✓），
        且**天生不会**出现"被资金面/事件否决"✗（这正是用户要的 ✓）。

    ⚠️ 调用方**仍需**给出 `score` / `veto_flag` 字段 ✓（下游日志会读 ✓）——
      建议用 `0.0` / `False` 占位 ✓（`filter_candidates` 在 `direct` 下反正不看它们 ✓）。
    """
    return resolve_pool_entry_mode(config, engine_config) == POOL_ENTRY_MODE_DIRECT
