# -*- coding: utf-8 -*-
"""
回测评分器模块

针对回测场景优化的高性能评分器：
1. 所有维度否决前置检查，一旦否决立即跳过其他维度
2. 批量处理评分，减少 API 调用
3. 日期级别数据缓存
4. 不保存评分结果到数据库

一票否决条件汇总：
- 技术面：M头策略 + 多死叉共振策略同时命中
- 资金面：5日主力净额 < -10000万元 OR 出货信号（大单流出+小单流入）
- 基本面：净利润同比下滑 > 50% OR ROE < -5%
- 板块：板块得分 = -100
- 事件：被ST OR 业绩暴雷 OR 大股东减持
"""

import logging
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta

from trading.stock_score_models import (
    StockScore, SCORE_WEIGHTS, VETO_SCORE
)
from trading.technical_scorer import (
    STRATEGY_WEIGHTS, VETO_STRATEGIES as TECH_VETO_STRATEGIES,
    VETO_ENABLED as TECH_VETO_ENABLED
)

# 配置日志
logger = logging.getLogger(__name__)


# 一票否决结果
class VetoResult:
    """一票否决结果"""
    def __init__(self, vetoed: bool = False, dimension: str = "", reason: str = ""):
        self.vetoed = vetoed
        self.dimension = dimension
        self.reason = reason
    
    def __bool__(self):
        return self.vetoed


class BacktestScoreCalculator:
    """
    回测专用评分计算器
    
    优化点：
    1. 所有维度否决前置检查，否决后立即跳过其他维度
    2. 支持批量评分，减少循环开销
    3. 添加日期级缓存，同一日期的数据不重复计算
    4. 不保存结果到数据库
    5. 使用与StockScoreCalculator相同的评分器，确保评分逻辑一致
    """

    def __init__(self, db_manager=None):
        """
        初始化回测评分器
        
        参数:
            db_manager: 数据库管理器实例
        """
        self.db = db_manager
        # 日期级缓存：{date: {stock_code: scores_dict}}
        self.date_cache: Dict[str, Dict[str, Dict]] = {}
        
        # 初始化评分器（与StockScoreCalculator保持一致）
        from trading.technical_scorer import TechnicalScorer
        from trading.moneyflow_scorer import MoneyflowScorer
        from trading.fundamental_scorer import FundamentalScorer
        from trading.sector_scorer import SectorScorer
        from trading.event_scorer import EventScorer
        
        self.technical_scorer = TechnicalScorer(db_manager=db_manager)
        self.moneyflow_scorer = MoneyflowScorer(db_manager=db_manager)
        self.fundamental_scorer = FundamentalScorer()
        self.sector_scorer = SectorScorer(db_manager=db_manager)
        self.event_scorer = EventScorer()
        
        logger.info("回测评分器初始化完成")
    
    def clear_cache(self):
        """清空评分缓存"""
        self.date_cache.clear()
    
    def is_tushare_available(self) -> bool:
        """检查Tushare数据源是否可用"""
        try:
            token = self.moneyflow_scorer._load_tushare_token()
            return bool(token)
        except Exception:
            return False
    
    def _is_cache_valid(self, date: str) -> bool:
        """检查缓存是否有效"""
        return date in self.date_cache
    
    def _get_cached_score(self, date: str, stock_code: str) -> Optional[Dict]:
        """从缓存获取评分"""
        if self._is_cache_valid(date):
            return self.date_cache[date].get(stock_code)
        return None
    
    def _set_cached_score(self, date: str, stock_code: str, scores: Dict):
        """设置评分缓存"""
        if date not in self.date_cache:
            self.date_cache[date] = {}
        self.date_cache[date][stock_code] = scores
    
    def _get_stock_name(self, stock_code: str) -> str:
        """获取股票名称"""
        try:
            if self.db:
                sql = "SELECT name FROM stock_basic WHERE code = ?"
                results = self.db.query(sql, (stock_code,))
                if results and results[0]:
                    return results[0].get('name', '')
        except Exception:
            pass
        return ''
    
    def calculate_score(
        self, 
        stock_code: str, 
        score_date: str, 
        hit_strategies: List[str]
    ) -> Tuple[StockScore, VetoResult]:
        """
        计算单只股票评分（回测模式）
        
        优化流程：
        1. 先计算技术面得分，检查否决
        2. 如果技术面否决，立即返回（不计算其他维度）
        3. 计算资金面得分，检查否决
        4. 如果资金面否决，立即返回
        5. 依次检查基本面、板块、事件维度
        6. 正常计算所有维度后，加权汇总
        
        参数:
            stock_code: 股票代码
            score_date: 评分日期（YYYY-MM-DD）
            hit_strategies: 命中的策略列表
            
        返回:
            Tuple[StockScore, VetoResult]: (评分对象, 否决结果)
        """
        # 检查缓存
        cached = self._get_cached_score(score_date, stock_code)
        if cached:
            score_obj = StockScore(
                stock_code=stock_code,
                stock_name=cached.get('stock_name', ''),
                score_date=score_date,
            )
            score_obj.total_score = cached['total_score']
            score_obj.technical_score = cached['technical_score']
            score_obj.moneyflow_score = cached.get('moneyflow_score', 0)
            score_obj.fundamental_score = cached.get('fundamental_score', 0)
            score_obj.sector_score = cached.get('sector_score', 0)
            score_obj.event_score = cached.get('event_score', 0)
            score_obj.score_level = cached.get('score_level', '中性')
            score_obj.veto_flag = cached.get('veto_flag', False)
            score_obj.veto_reason = cached.get('veto_reason', '')
            
            veto_result = VetoResult(
                vetoed=cached.get('veto_flag', False),
                dimension=cached.get('veto_dimension', ''),
                reason=cached.get('veto_reason', '')
            )
            return score_obj, veto_result
        
        # 获取股票名称
        stock_name = self._get_stock_name(stock_code)
        
        # 创建评分对象
        score_obj = StockScore(
            stock_code=stock_code,
            stock_name=stock_name,
            score_date=score_date,
        )
        
        # ============================================================
        # 第一步：计算技术面得分 + 否决检查
        # ============================================================
        veto = self._calculate_technical_score(stock_code, score_date, hit_strategies, score_obj)
        if veto.vetoed:
            # 缓存并返回
            self._cache_with_veto(score_date, stock_code, stock_name, score_obj, veto)
            return score_obj, veto
        
        # ============================================================
        # 第二步：计算资金面得分 + 否决检查
        # ============================================================
        veto = self._calculate_moneyflow_score(stock_code, score_date, score_obj)
        if veto.vetoed:
            self._cache_with_veto(score_date, stock_code, stock_name, score_obj, veto)
            return score_obj, veto
        
        # ============================================================
        # 第三步：计算基本面得分 + 否决检查
        # ============================================================
        veto = self._calculate_fundamental_score(stock_code, score_date, score_obj)
        if veto.vetoed:
            self._cache_with_veto(score_date, stock_code, stock_name, score_obj, veto)
            return score_obj, veto
        
        # ============================================================
        # 第四步：计算板块得分 + 否决检查
        # ============================================================
        veto = self._calculate_sector_score(stock_code, score_date, score_obj)
        if veto.vetoed:
            self._cache_with_veto(score_date, stock_code, stock_name, score_obj, veto)
            return score_obj, veto
        
        # ============================================================
        # 第五步：计算事件得分 + 否决检查
        # ============================================================
        veto = self._calculate_event_score(stock_code, score_date, score_obj)
        if veto.vetoed:
            self._cache_with_veto(score_date, stock_code, stock_name, score_obj, veto)
            return score_obj, veto
        
        # ============================================================
        # 第六步：计算综合得分
        # ============================================================
        total_score = (
            score_obj.technical_score * 0.25  # 技术面权重 25%
            + score_obj.moneyflow_score * 0.30  # 资金面权重 30%
            + score_obj.fundamental_score * 0.15  # 基本面权重 15%
            + score_obj.sector_score * 0.15  # 板块权重 15%
            + score_obj.event_score * 0.15  # 事件权重 15%
        )
        
        # 限制范围
        score_obj.total_score = max(0, min(100, round(total_score, 1)))
        score_obj.score_level = StockScore.get_score_level(score_obj.total_score)
        
        # 缓存结果
        self._set_cached_score(score_date, stock_code, {
            'stock_name': stock_name,
            'total_score': score_obj.total_score,
            'technical_score': score_obj.technical_score,
            'moneyflow_score': score_obj.moneyflow_score,
            'fundamental_score': score_obj.fundamental_score,
            'sector_score': score_obj.sector_score,
            'event_score': score_obj.event_score,
            'score_level': score_obj.score_level,
            'veto_flag': False,
            'veto_dimension': '',
            'veto_reason': '',
        })
        
        return score_obj, VetoResult()
    
    def _cache_with_veto(self, score_date: str, stock_code: str, stock_name: str, 
                          score_obj: StockScore, veto: VetoResult):
        """缓存带否决的结果"""
        self._set_cached_score(score_date, stock_code, {
            'stock_name': stock_name,
            'total_score': VETO_SCORE,
            'technical_score': score_obj.technical_score,
            'moneyflow_score': score_obj.moneyflow_score,
            'fundamental_score': score_obj.fundamental_score,
            'sector_score': score_obj.sector_score,
            'event_score': score_obj.event_score,
            'score_level': '淘汰',
            'veto_flag': True,
            'veto_dimension': veto.dimension,
            'veto_reason': veto.reason,
        })
        score_obj.total_score = VETO_SCORE
        score_obj.score_level = '淘汰'
        score_obj.veto_flag = True
        score_obj.veto_reason = veto.reason
    
    def _calculate_technical_score(
        self, 
        stock_code: str, 
        score_date: str, 
        hit_strategies: List[str],
        score_obj: StockScore
    ) -> VetoResult:
        """
        计算技术面得分 + 否决检查
        
        否决条件：M头策略 + 多死叉共振策略同时命中
        """
        try:
            # 直接计算技术面评分：根据命中策略的权重求和
            total_weight = 0.0
            for strategy in hit_strategies:
                # 尝试直接匹配策略名称
                weight = STRATEGY_WEIGHTS.get(strategy, 0)
                # 如果直接匹配失败，尝试添加策略后缀
                if weight == 0 and not strategy.endswith('策略'):
                    name_with_suffix = strategy + '策略'
                    weight = STRATEGY_WEIGHTS.get(name_with_suffix, 0)
                # 如果仍然失败，尝试去掉策略后缀
                if weight == 0 and strategy.endswith('策略'):
                    name_without_suffix = strategy[:-2]
                    weight = STRATEGY_WEIGHTS.get(name_without_suffix, 0)
                total_weight += weight
            
            score_obj.technical_score = total_weight
            logger.debug(f"股票 {stock_code} 技术面评分: {total_weight}, 命中策略: {hit_strategies}")
            
            # 检查一票否决
            if TECH_VETO_ENABLED and hit_strategies:
                # 检查是否同时命中M头策略和多死叉共振策略
                hit_mtop = any('M头' in s or 'MTop' in s for s in hit_strategies)
                hit_multi_death_cross = any('多死叉' in s or 'MultiDeathCross' in s for s in hit_strategies)
                if hit_mtop and hit_multi_death_cross:
                    reason = "技术面一票否决：同时命中 M头策略 和 多死叉共振策略"
                    logger.debug(f"股票 {stock_code} {reason}")
                    return VetoResult(vetoed=True, dimension="技术面", reason=reason)
            
            return VetoResult()
        except Exception as e:
            logger.debug(f"计算技术面评分失败: {e}")
            score_obj.technical_score = 50
            return VetoResult()
    
    def _calculate_moneyflow_score(
        self, 
        stock_code: str, 
        score_date: str,
        score_obj: StockScore
    ) -> VetoResult:
        """
        计算资金面得分 + 否决检查
        
        否决条件：
        1. 5日主力净额 < -10000万元
        2. 出货信号：大单净流入 < 0 且 小单净流入 > 0
        """
        try:
            # 使用MoneyflowScorer计算资金面评分
            moneyflow_score, moneyflow_detail = self.moneyflow_scorer.calculate_score(stock_code, score_date)
            score_obj.moneyflow_score = moneyflow_score
            
            # 检查资金面否决条件（从detail中获取否决信息）
            if moneyflow_detail.veto:
                return VetoResult(vetoed=True, dimension="资金面", reason=moneyflow_detail.veto_reason)
            
            return VetoResult()
        except Exception as e:
            logger.debug(f"计算资金面评分失败: {e}")
            score_obj.moneyflow_score = 50
            return VetoResult()
    
    def _calculate_fundamental_score(
        self, 
        stock_code: str, 
        score_date: str,
        score_obj: StockScore
    ) -> VetoResult:
        """
        计算基本面得分 + 否决检查
        
        否决条件：
        1. 净利润同比下滑 > 50%（net_profit_yoy < -50）
        2. ROE < -5%
        """
        try:
            # 使用FundamentalScorer计算基本面评分
            fundamental_score, fundamental_detail = self.fundamental_scorer.calculate_score(stock_code, score_date)
            score_obj.fundamental_score = fundamental_score
            
            # 检查基本面否决条件（从detail中获取否决信息）
            if fundamental_detail.veto:
                return VetoResult(vetoed=True, dimension="基本面", reason=fundamental_detail.veto_reason)
            
            return VetoResult()
        except Exception as e:
            logger.debug(f"计算基本面评分失败: {e}")
            score_obj.fundamental_score = 50
            return VetoResult()
    
    def _calculate_sector_score(
        self, 
        stock_code: str, 
        score_date: str,
        score_obj: StockScore
    ) -> VetoResult:
        """
        计算板块得分 + 否决检查
        
        否决条件：板块得分 = -100
        """
        try:
            # 使用SectorScorer计算板块评分
            sector_score, sector_detail = self.sector_scorer.calculate_score(stock_code, score_date)
            score_obj.sector_score = sector_score
            
            # 检查板块否决条件（从detail中获取否决信息）
            if sector_detail.veto:
                return VetoResult(vetoed=True, dimension="板块", reason=sector_detail.veto_reason)
            
            return VetoResult()
        except Exception as e:
            logger.debug(f"计算板块评分失败: {e}")
            score_obj.sector_score = 50
            return VetoResult()
    
    def _calculate_event_score(
        self, 
        stock_code: str, 
        score_date: str,
        score_obj: StockScore
    ) -> VetoResult:
        """
        计算事件得分 + 否决检查
        
        否决条件：
        1. 被ST或*ST
        2. 业绩暴雷（预减>80%或巨亏）
        3. 大股东减持
        """
        try:
            # 使用EventScorer计算事件驱动评分
            event_score, event_detail = self.event_scorer.calculate_score(stock_code, score_date)
            score_obj.event_score = event_score
            
            # 检查事件驱动否决条件（从detail中获取否决信息）
            if event_detail.veto:
                return VetoResult(vetoed=True, dimension="事件", reason=event_detail.veto_reason)
            
            return VetoResult()
        except Exception as e:
            logger.debug(f"计算事件驱动评分失败: {e}")
            score_obj.event_score = 50
            return VetoResult()
    
    def calculate_batch_scores(
        self,
        stocks: List[Dict],
        score_date: str,
        strategy_name: str
    ) -> List[Dict]:
        """
        批量计算股票评分
        
        参数:
            stocks: 股票列表，每项包含 stock_code, stock_name
            score_date: 评分日期
            strategy_name: 策略名称
            
        返回:
            带评分的股票列表
        """
        scored_stocks = []
        veto_count = 0
        
        # 检查Tushare数据源是否可用
        tushare_available = self.is_tushare_available()
        if not tushare_available:
            logger.info("Tushare数据源不可用，使用简化评分模式")
        
        for stock in stocks:
            stock_code = stock['stock_code']
            hit_strategies = [strategy_name]
            
            try:
                if not tushare_available:
                    # Tushare不可用时使用简化评分
                    # 计算策略权重作为技术面评分
                    strategy_weight = 0
                    for s in hit_strategies:
                        weight = STRATEGY_WEIGHTS.get(s, 0)
                        if weight == 0 and not s.endswith('策略'):
                            name_with_suffix = s + '策略'
                            weight = STRATEGY_WEIGHTS.get(name_with_suffix, 0)
                        if weight == 0 and s.endswith('策略'):
                            name_without_suffix = s[:-2]
                            weight = STRATEGY_WEIGHTS.get(name_without_suffix, 0)
                        strategy_weight += weight
                    
                    # 综合评分 = 技术面评分（策略权重）
                    stock['score'] = strategy_weight
                    stock['technical_score'] = strategy_weight
                    # 其他维度评分为0（没有tushare数据）
                    stock['moneyflow_score'] = 0
                    stock['fundamental_score'] = 0
                    stock['sector_score'] = 0
                    stock['event_score'] = 0
                    stock['veto_flag'] = False
                    stock['veto_reason'] = ''
                    stock['veto_dimension'] = ''
                    stock['score_level'] = '中性'
                    stock['strategy_details'] = [{'name': s, 'weight': STRATEGY_WEIGHTS.get(s, 0) if STRATEGY_WEIGHTS.get(s, 0) != 0 else (STRATEGY_WEIGHTS.get(s + '策略', 0) if not s.endswith('策略') else STRATEGY_WEIGHTS.get(s[:-2], 0))} for s in hit_strategies]
                    stock['total_strategy_weight'] = strategy_weight
                    scored_stocks.append(stock)
                    continue
                
                score_obj, veto = self.calculate_score(
                    stock_code, score_date, hit_strategies
                )
                
                if veto.vetoed:
                    veto_count += 1
                
                # 补充股票信息
                stock['score'] = score_obj.total_score
                stock['technical_score'] = score_obj.technical_score
                stock['moneyflow_score'] = score_obj.moneyflow_score
                stock['fundamental_score'] = score_obj.fundamental_score
                stock['sector_score'] = score_obj.sector_score
                stock['event_score'] = score_obj.event_score
                stock['veto_flag'] = score_obj.veto_flag
                stock['veto_reason'] = score_obj.veto_reason
                stock['veto_dimension'] = veto.dimension if veto else ''
                stock['score_level'] = score_obj.score_level
                # 计算策略权重
                strategy_weight = 0
                for s in hit_strategies:
                    weight = STRATEGY_WEIGHTS.get(s, 0)
                    if weight == 0 and not s.endswith('策略'):
                        name_with_suffix = s + '策略'
                        weight = STRATEGY_WEIGHTS.get(name_with_suffix, 0)
                    if weight == 0 and s.endswith('策略'):
                        name_without_suffix = s[:-2]
                        weight = STRATEGY_WEIGHTS.get(name_without_suffix, 0)
                    strategy_weight += weight
                stock['strategy_details'] = [{'name': s, 'weight': STRATEGY_WEIGHTS.get(s, 0) if STRATEGY_WEIGHTS.get(s, 0) != 0 else (STRATEGY_WEIGHTS.get(s + '策略', 0) if not s.endswith('策略') else STRATEGY_WEIGHTS.get(s[:-2], 0))} for s in hit_strategies]
                stock['total_strategy_weight'] = strategy_weight
                
                # 记录每只股票的各维度评分
                logger.info(f"股票 {stock['stock_code']} {stock['stock_name']} 评分详情：综合评分={stock['score']}, 技术面={stock['technical_score']}, 资金面={stock['moneyflow_score']}, 基本面={stock['fundamental_score']}, 板块={stock['sector_score']}, 事件={stock['event_score']}, 策略权重={stock['total_strategy_weight']}")
                
                scored_stocks.append(stock)
                
            except Exception as e:
                logger.warning(f"计算股票 {stock_code} 评分失败: {e}")
                stock['score'] = 50
                stock['technical_score'] = 0
                stock['moneyflow_score'] = 50
                stock['fundamental_score'] = 50
                stock['sector_score'] = 50
                stock['event_score'] = 50
                stock['veto_flag'] = False
                stock['veto_reason'] = ''
                stock['veto_dimension'] = ''
                stock['score_level'] = '中性'
                scored_stocks.append(stock)
        
        logger.info(f"批量评分完成: {len(stocks)} 只股票, 触发否决: {veto_count} 只")
        return scored_stocks


def create_backtest_calculator(db_manager=None) -> BacktestScoreCalculator:
    """
    工厂函数：创建回测评分器
    
    参数:
        db_manager: 数据库管理器实例
        
    返回:
        BacktestScoreCalculator 实例
    """
    return BacktestScoreCalculator(db_manager=db_manager)
