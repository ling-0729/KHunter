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
                      simplified: bool = False) -> List[Dict]:
    """按入池规则筛选候选股票

    统一规则（2026-09-11 调整）：**`veto_flag == False` 且 `score >= score_threshold`**

    说明：`score` 的含义由评分方式决定（见 `BacktestScoreCalculator`）——
      - **简化模式**：`score` = **资金面得分**（只算资金面维度，相当于权重 100%）
      - 标准模式：`score` = 五维度加权综合评分
    两种模式都做阈值比较，因此 `simplified` 只影响"分数怎么算"，
    不再影响过滤规则（此前简化模式会跳过评分比较，导致池子过大且无择优）。

    Args:
        scored_stocks: 评分后的股票列表（每项含 `score` / `veto_flag`）
        score_threshold: 入池评分阈值（两种模式均生效）
        simplified: 兼容用参数（分数口径差异在评分器中体现）

    Returns:
        list: 入池候选（保持原顺序）
    """
    out: List[Dict] = []
    for stock in (scored_stocks or []):
        try:
            if stock.get('veto_flag', False):
                continue
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
    return out
