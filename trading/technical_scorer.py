# -*- coding: utf-8 -*-
"""
技术面评分器模块

基于选股策略命中情况计算技术面得分。
数据来源：stock_selection_record 表
评分规则：技术面得分 = Σ(策略权重 × 命中标志)
一票否决：M头策略 + 多死叉共振同时命中 → -100分
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

# 导入数据库管理器
from utils.db_manager import DBManager
# 导入技术面详情模型
from trading.stock_score_models import TechnicalDetail

# 配置日志记录器
logger = logging.getLogger(__name__)

# 全局 DBManager 实例
from utils.global_db import get_global_db
global_db_manager = get_global_db()


# ============================================================
# 从配置文件加载策略权重
# ============================================================
def _load_strategy_weights() -> Dict[str, int]:
    """
    从配置文件加载策略权重
    
    配置文件路径：config/strategy_weights.json
    
    返回:
        Dict[str, int]: 策略名称到权重的映射字典
    """
    # 配置文件路径
    config_path = Path(__file__).parent.parent / "config" / "strategy_weights.json"
    
    # 确保路径正确
    if not config_path.exists():
        # 尝试使用当前工作目录
        config_path = Path.cwd() / "config" / "strategy_weights.json"
    
    # 默认权重（配置文件不存在时使用）
    default_weights = {
        "底部趋势拐点": 50,
        "趋势加速拐点": 40,
        "阻力位突破策略": 40,
        "缩量回调策略": 30,
        "W底策略": 30,
        "多金叉共振策略": 20,
        "启明星策略": 20,
        "多方炮策略": 15,
        "多死叉共振策略": -30,
        "M头策略": -50,
        "趋势共振反转策略": 35,
    }
    
    # 检查配置文件是否存在
    if not config_path.exists():
        logger.warning(f"策略权重配置文件不存在: {config_path}，使用默认权重")
        return default_weights
    
    try:
        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 解析策略权重
        weights = {}
        for strategy in config.get('strategies', []):
            name = strategy.get('name')
            weight = strategy.get('weight', 0)
            if name:
                weights[name] = weight
        
        logger.info(f"从配置文件加载策略权重成功: {config_path}，共 {len(weights)} 个策略")
        return weights
    
    except Exception as e:
        logger.error(f"加载策略权重配置文件失败: {e}，使用默认权重")
        return default_weights


def _load_veto_config() -> Tuple[bool, int, List[str]]:
    """
    从配置文件加载一票否决配置
    
    返回:
        Tuple[bool, int, List[str]]: (是否启用, 否决分数, 触发否决的策略列表)
    """
    # 配置文件路径
    config_path = Path(__file__).parent.parent / "config" / "strategy_weights.json"
    
    # 确保路径正确
    if not config_path.exists():
        # 尝试使用当前工作目录
        config_path = Path.cwd() / "config" / "strategy_weights.json"
    
    # 默认配置
    default_enabled = True
    default_score = -100
    default_strategies = ["M头策略", "多死叉共振策略"]
    
    # 检查配置文件是否存在
    if not config_path.exists():
        return default_enabled, default_score, default_strategies
    
    try:
        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 解析一票否决配置
        veto_config = config.get('veto_config', {})
        enabled = veto_config.get('enabled', default_enabled)
        score = veto_config.get('score', default_score)
        strategies = veto_config.get('strategies', default_strategies)
        
        logger.info(f"加载一票否决配置: enabled={enabled}, score={score}, strategies={strategies}")
        return enabled, score, strategies
    
    except Exception as e:
        logger.error(f"加载一票否决配置失败: {e}，使用默认配置")
        return default_enabled, default_score, default_strategies


# 加载策略权重配置
STRATEGY_WEIGHTS = _load_strategy_weights()

# 加载一票否决配置
VETO_ENABLED, VETO_SCORE, VETO_STRATEGIES = _load_veto_config()


class TechnicalScorer:
    """
    技术面评分器

    根据 stock_selection_record 表中的策略命中记录，
    按策略权重计算技术面得分，并检查一票否决条件。
    """

    def __init__(self, db_manager: DBManager = None):
        """
        初始化技术面评分器

        参数:
            db_manager: 数据库管理器实例，为 None 时使用全局实例
        """
        # 使用传入的 db_manager 或全局实例
        self.db = db_manager or global_db_manager
        # 记录初始化日志
        logger.info("技术面评分器初始化完成")
        # 记录使用的 DBManager 实例
        logger.info(f"使用的 DBManager 实例: {id(self.db)}")

    def _query_hit_strategies(
        self, stock_code: str, score_date: str
    ) -> List[str]:
        """
        查询指定股票在指定日期命中的策略列表

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期，格式 YYYY-MM-DD 或 YYYYMMDD
        返回:
            List[str]: 命中的策略名称列表
        """
        # 统一日期格式为 YYYY-MM-DD（数据库中存储格式）
        formatted_date = self._format_date(score_date)
        logger.info(
            f"查询策略命中情况: stock_code={stock_code}, date={formatted_date}"
        )

        # 直接使用 SQLite 连接查询，避免 DBManager 实例之间的冲突
        import sqlite3
        from utils.db_config import get_db_path
        
        strategies = []
        try:
            # 获取数据库路径
            db_path = get_db_path()
            logger.info(f"使用数据库路径: {db_path}")
            
            # 创建新的 SQLite 连接
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 先查询所有记录，验证数据是否存在
            test_sql = """
                SELECT *
                FROM stock_selection_record
                WHERE stock_code = ?
            """
            cursor.execute(test_sql, (stock_code,))
            test_results = cursor.fetchall()
            logger.info(f"测试查询结果: {test_results}")
            
            # 从 stock_selection_record 表查询命中策略
            # 使用selection_date限制日期，确保只查询指定日期的策略
            sql = """
                SELECT DISTINCT strategy_name
                FROM stock_selection_record
                WHERE stock_code = ?
                  AND selection_date = ?
                  AND is_active = 1
            """
            # 执行查询
            logger.info(f"执行查询: {sql}, 参数: ({stock_code}, {formatted_date})")
            cursor.execute(sql, (stock_code, formatted_date))
            
            # 获取查询结果
            results = cursor.fetchall()
            logger.info(f"查询结果: {results}")
            
            # 提取策略名称列表
            strategies = [
                row[0]
                for row in results
                if row[0]
            ]
            
            # 关闭连接
            conn.close()
        except Exception as e:
            logger.error(f"查询策略命中情况失败: {e}")
        
        # 记录查询结果
        logger.info(
            f"股票 {stock_code} 在 {formatted_date} 命中 {len(strategies)} 个策略: {strategies}"
        )
        return strategies

    def _format_date(self, date_str: str) -> str:
        """
        将日期字符串统一转换为 YYYY-MM-DD 格式

        参数:
            date_str: 日期字符串，支持 YYYYMMDD 或 YYYY-MM-DD
        返回:
            str: YYYY-MM-DD 格式的日期字符串
        """
        # 去除空白字符
        date_str = date_str.strip()
        # 如果是 YYYYMMDD 格式（8位纯数字），转换为 YYYY-MM-DD
        if len(date_str) == 8 and date_str.isdigit():
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        # 已经是 YYYY-MM-DD 格式，直接返回
        return date_str

    def _expand_combined_strategies(
        self, strategies: List[str]
    ) -> List[str]:
        """
        将组合策略拆分为单个策略

        如果策略名称中包含"+"，则拆分为多个单个策略。
        例如："多金叉共振策略+W底策略" -> ["多金叉共振策略", "W底策略"]

        参数:
            strategies: 策略名称列表（可能包含组合策略）
        返回:
            List[str]: 拆分后的单个策略列表
        """
        individual_strategies = []
        for strategy in strategies:
            # 检查是否为组合策略（包含"+"）
            if "+" in strategy:
                # 拆分组合策略
                parts = strategy.split("+")
                # 添加每个单个策略
                for part in parts:
                    part = part.strip()
                    if part:
                        individual_strategies.append(part)
                # 记录拆分日志
                logger.debug(
                    f"拆分组合策略: {strategy} -> {parts}"
                )
            else:
                # 单个策略，直接添加
                individual_strategies.append(strategy)
        return individual_strategies

    def calculate_score(
        self, stock_code: str, score_date: str, hit_strategies: List[str] = None
    ) -> Tuple[float, TechnicalDetail]:
        """
        计算指定股票在指定日期的技术面得分

        如果传入 hit_strategies 参数，则使用传入的策略列表计算；
        否则从 stock_selection_record 表查询命中策略。

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期，格式 YYYY-MM-DD 或 YYYYMMDD
            hit_strategies: 命中的策略列表（可选，为 None 时从数据库查询）
        返回:
            Tuple[float, TechnicalDetail]: (技术面得分, 技术面详情对象)
        """
        logger.info(f"开始计算技术面得分: {stock_code}, 日期: {score_date}")

        # 初始化技术面详情对象
        detail = TechnicalDetail()

        # 统一日期格式
        formatted_date = self._format_date(score_date)
        
        # 如果没有传入策略列表，从数据库查询
        if hit_strategies is None:
            hit_strategies = self._query_hit_strategies(stock_code, formatted_date)
        
        if hit_strategies:
            # 有策略命中记录，直接计算评分
            # 拆分组合策略
            individual_strategies = self._expand_combined_strategies(hit_strategies)
            # 构建策略详情列表
            strategy_list = []
            total_score = 0.0
            
            # 完整的策略类名到中文名称的映射
            class_name_map = {
                'BottomTrendInflectionStrategy': '底部趋势拐点',
                'TrendAccelerationInflectionStrategy': '趋势加速拐点',
                'ResistanceBreakoutStrategy': '阻力位突破策略',
                'WBottomStrategy': 'W底策略',
                'MultiGoldenCrossStrategy': '多金叉共振策略',
                'MorningStarStrategy': '启明星策略',
                'MultiPartyCannonStrategy': '多方炮策略',
                'MultiDeathCrossStrategy': '多死叉共振策略',
                'MTopStrategy': 'M头策略',
                'StrongWashWeakToStrongStrategy': '强势洗盘弱转强策略',
                'LimitUpPullbackStrategy': '涨停回马枪策略',
                'LimitUpSidewaysStrategy': '涨停横盘策略'
            }
            
            # 构建策略名称映射列表，用于一票否决检查
            mapped_strategies = []
            
            for strategy in individual_strategies:
                # 直接使用策略名称（已经是中文名称）
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
                # 记录策略匹配过程
                logger.info(f"策略: {strategy}, 直接匹配权重: {STRATEGY_WEIGHTS.get(strategy, 0)}, 添加后缀后权重: {STRATEGY_WEIGHTS.get(strategy + '策略', 0) if not strategy.endswith('策略') else 0}, 去掉后缀后权重: {STRATEGY_WEIGHTS.get(strategy[:-2], 0) if strategy.endswith('策略') else 0}, 最终权重: {weight}")
                # 添加到映射策略列表
                mapped_strategies.append(strategy)
                # 构建策略详情
                strategy_list.append({"name": strategy, "weight": weight})
                
                total_score += weight
            
            # 检查一票否决，使用映射后的策略名称
            veto, veto_reason = self.check_veto(stock_code, formatted_date, mapped_strategies)
            
            # 设置详情
            detail.strategies = strategy_list
            detail.veto = veto
            detail.veto_reason = veto_reason
            
            logger.info(
                f"股票 {stock_code} 从stock_selection_record表计算技术面得分: {total_score}, "
                f"策略数: {len(strategy_list)}, 否决: {veto}"
            )
            return total_score, detail
        else:
            # 没有策略命中记录，返回0分
            logger.warning(f"股票 {stock_code} 在 {formatted_date} 没有命中任何策略")
            return 0.0, detail

        # 下面的代码暂时保留，但不会被执行（作为备用逻辑）
        # 从stock_score_detail表查询技术面评分数据
        sql = """
            SELECT technical_strategies
            FROM stock_score_detail
            WHERE stock_code = ?
              AND score_date = ?
        """
        results = self.db.query(sql, (stock_code, formatted_date))

        if not results:
            logger.warning(f"股票 {stock_code} 在 {formatted_date} 没有评分记录")
            return 0.0, detail

        # 解析技术面策略数据
        technical_strategies = results[0].get('technical_strategies')
        if not technical_strategies:
            logger.warning(f"股票 {stock_code} 在 {formatted_date} 没有技术面策略数据")
            # 从stock_selection_record表查询策略命中情况
            hit_strategies = self._query_hit_strategies(stock_code, formatted_date)
            if hit_strategies:
                # 拆分组合策略
                individual_strategies = self._expand_combined_strategies(hit_strategies)
                # 构建策略详情列表
                strategy_list = []
                total_score = 0.0
                
                for strategy in individual_strategies:
                    # 尝试直接匹配策略名称
                    weight = STRATEGY_WEIGHTS.get(strategy, 0)
                    # 如果直接匹配失败，尝试去掉策略后缀
                    if weight == 0 and strategy.endswith('策略'):
                        name_without_suffix = strategy[:-2]
                        weight = STRATEGY_WEIGHTS.get(name_without_suffix, 0)
                    # 如果仍然失败，尝试使用策略类名映射
                    if weight == 0:
                        # 完整的策略类名到中文名称的映射
                        class_name_map = {
                            'BottomTrendInflectionStrategy': '底部趋势拐点',
                            'TrendAccelerationInflectionStrategy': '趋势加速拐点',
                            'ResistanceBreakoutStrategy': '阻力位突破策略',
                            'WBottomStrategy': 'W底策略',
                            'MultiGoldenCrossStrategy': '多金叉共振策略',
                            'MorningStarStrategy': '启明星策略',
                            'MultiPartyCannonStrategy': '多方炮策略',
                            'MultiDeathCrossStrategy': '多死叉共振策略',
                            'MTopStrategy': 'M头策略',
                            'StrongWashWeakToStrongStrategy': '强势洗盘弱转强策略',
                            'LimitUpPullbackStrategy': '涨停回马枪策略',
                            'LimitUpSidewaysStrategy': '涨停横盘策略'
                        }
                        if strategy in class_name_map:
                            chinese_name = class_name_map[strategy]
                            weight = STRATEGY_WEIGHTS.get(chinese_name, 0)
                    total_score += weight
                    strategy_list.append({"name": strategy, "weight": weight})
                
                # 检查一票否决
                veto, veto_reason = self.check_veto(stock_code, formatted_date, individual_strategies)
                
                # 设置详情
                detail.strategies = strategy_list
                detail.veto = veto
                detail.veto_reason = veto_reason
                
                logger.info(
                    f"股票 {stock_code} 从stock_selection_record表计算技术面得分: {total_score}, "
                    f"策略数: {len(strategy_list)}, 否决: {veto}"
                )
                return total_score, detail
            else:
                return 0.0, detail

        try:
            # 解析JSON格式的策略数据
            import json
            strategies_data = json.loads(technical_strategies)
            
            # 计算总分
            total_score = 0.0
            strategy_list = []
            veto = False
            veto_reason = ""
            
            # 检查是否为字典格式（标准格式）
            if isinstance(strategies_data, dict):
                # 提取策略列表
                strategies = strategies_data.get('strategies', [])
                if isinstance(strategies, list):
                    for strategy in strategies:
                        if isinstance(strategy, dict):
                            name = strategy.get('name', '')
                            weight = strategy.get('weight', 0)
                            total_score += weight
                            strategy_list.append({"name": name, "weight": weight})
                
                # 提取否决信息
                veto = strategies_data.get('veto', False)
                veto_reason = strategies_data.get('veto_reason', "")
            elif isinstance(strategies_data, list):
                # 列表格式
                for strategy in strategies_data:
                    if isinstance(strategy, dict):
                        name = strategy.get('name', '')
                        weight = strategy.get('weight', 0)
                        total_score += weight
                        strategy_list.append({"name": name, "weight": weight})
                    elif isinstance(strategy, str):
                        # 尝试直接匹配策略名称
                        weight = STRATEGY_WEIGHTS.get(strategy, 0)
                        # 如果直接匹配失败，尝试去掉策略后缀
                        if weight == 0 and strategy.endswith('策略'):
                            name_without_suffix = strategy[:-2]
                            weight = STRATEGY_WEIGHTS.get(name_without_suffix, 0)
                        # 如果仍然失败，尝试使用策略类名映射
                        if weight == 0:
                            # 完整的策略类名到中文名称的映射
                            class_name_map = {
                                'BottomTrendInflectionStrategy': '底部趋势拐点',
                                'TrendAccelerationInflectionStrategy': '趋势加速拐点',
                                'ResistanceBreakoutStrategy': '阻力位突破策略',
                                'WBottomStrategy': 'W底策略',
                                'MultiGoldenCrossStrategy': '多金叉共振策略',
                                'MorningStarStrategy': '启明星策略',
                                'MultiPartyCannonStrategy': '多方炮策略',
                                'MultiDeathCrossStrategy': '多死叉共振策略',
                                'MTopStrategy': 'M头策略',
                                'StrongWashWeakToStrongStrategy': '强势洗盘弱转强策略',
                                'LimitUpPullbackStrategy': '涨停回马枪策略',
                                'LimitUpSidewaysStrategy': '涨停横盘策略'
                            }
                            if strategy in class_name_map:
                                chinese_name = class_name_map[strategy]
                                weight = STRATEGY_WEIGHTS.get(chinese_name, 0)
                        total_score += weight
                        strategy_list.append({"name": strategy, "weight": weight})
            elif isinstance(strategies_data, str):
                # 字符串格式，按逗号分割
                strategy_names = [s.strip() for s in strategies_data.split(',') if s.strip()]
                for name in strategy_names:
                    # 尝试直接匹配策略名称
                    weight = STRATEGY_WEIGHTS.get(name, 0)
                    # 如果直接匹配失败，尝试去掉策略后缀
                    if weight == 0 and name.endswith('策略'):
                        name_without_suffix = name[:-2]
                        weight = STRATEGY_WEIGHTS.get(name_without_suffix, 0)
                    # 如果仍然失败，尝试使用策略类名映射
                    if weight == 0:
                        # 完整的策略类名到中文名称的映射
                        class_name_map = {
                            'BottomTrendInflectionStrategy': '底部趋势拐点',
                            'TrendAccelerationInflectionStrategy': '趋势加速拐点',
                            'TrendResonanceReversalStrategy': '趋势共振反转策略',
                            'ResistanceBreakoutStrategy': '阻力位突破策略',
                            'WBottomStrategy': 'W底策略',
                            'MultiGoldenCrossStrategy': '多金叉共振策略',
                            'MorningStarStrategy': '启明星策略',
                            'MultiPartyCannonStrategy': '多方炮策略',
                            'MultiDeathCrossStrategy': '多死叉共振策略',
                            'MTopStrategy': 'M头策略',
                            'StrongWashWeakToStrongStrategy': '强势洗盘弱转强策略',
                            'LimitUpPullbackStrategy': '涨停回马枪策略',
                            'LimitUpSidewaysStrategy': '涨停横盘策略'
                        }
                        if name in class_name_map:
                            chinese_name = class_name_map[name]
                            weight = STRATEGY_WEIGHTS.get(chinese_name, 0)
                    total_score += weight
                    strategy_list.append({"name": name, "weight": weight})
            
            # 如果strategies为空，从stock_selection_record表查询
            if not strategy_list:
                logger.warning(f"股票 {stock_code} 在 {formatted_date} 的strategies为空，从stock_selection_record表查询")
                hit_strategies = self._query_hit_strategies(stock_code, formatted_date)
                if hit_strategies:
                    # 拆分组合策略
                    individual_strategies = self._expand_combined_strategies(hit_strategies)
                    # 构建策略详情列表
                    strategy_list = []
                    total_score = 0.0
                    
                    for strategy in individual_strategies:
                        # 尝试直接匹配策略名称
                        weight = STRATEGY_WEIGHTS.get(strategy, 0)
                        # 如果直接匹配失败，尝试去掉策略后缀
                        if weight == 0 and strategy.endswith('策略'):
                            name_without_suffix = strategy[:-2]
                            weight = STRATEGY_WEIGHTS.get(name_without_suffix, 0)
                        # 如果仍然失败，尝试使用策略类名映射
                        if weight == 0:
                            # 完整的策略类名到中文名称的映射
                            class_name_map = {
                                'BottomTrendInflectionStrategy': '底部趋势拐点',
                                'TrendAccelerationInflectionStrategy': '趋势加速拐点',
                                'ResistanceBreakoutStrategy': '阻力位突破策略',
                                'WBottomStrategy': 'W底策略',
                                'MultiGoldenCrossStrategy': '多金叉共振策略',
                                'MorningStarStrategy': '启明星策略',
                                'MultiPartyCannonStrategy': '多方炮策略',
                                'MultiDeathCrossStrategy': '多死叉共振策略',
                                'MTopStrategy': 'M头策略',
                                'StrongWashWeakToStrongStrategy': '强势洗盘弱转强策略',
                                'LimitUpPullbackStrategy': '涨停回马枪策略',
                                'LimitUpSidewaysStrategy': '涨停横盘策略'
                            }
                            if strategy in class_name_map:
                                chinese_name = class_name_map[strategy]
                                weight = STRATEGY_WEIGHTS.get(chinese_name, 0)
                        total_score += weight
                        strategy_list.append({"name": strategy, "weight": weight})
                    
                    # 检查一票否决
                    veto, veto_reason = self.check_veto(stock_code, formatted_date, individual_strategies)
                    
                    # 设置详情
                    detail.strategies = strategy_list
                    detail.veto = veto
                    detail.veto_reason = veto_reason
                    
                    logger.info(
                        f"股票 {stock_code} 从stock_selection_record表计算技术面得分: {total_score}, "
                        f"策略数: {len(strategy_list)}, 否决: {veto}"
                    )
                    return total_score, detail
                else:
                    return 0.0, detail
            
            # 设置详情
            detail.strategies = strategy_list
            detail.veto = veto
            detail.veto_reason = veto_reason
            
            # 记录最终得分
            logger.info(
                f"股票 {stock_code} 技术面得分: {total_score}, "
                f"策略数: {len(strategy_list)}, 否决: {veto}"
            )
            return total_score, detail
        except Exception as e:
            logger.error(f"解析技术面策略数据失败: {e}")
            return 0.0, detail

    def check_veto(
        self,
        stock_code: str,
        score_date: str,
        hit_strategies: List[str] = None,
    ) -> Tuple[bool, str]:
        """
        检查一票否决条件

        一票否决条件：M头策略 + 多死叉共振策略同时命中时，
        技术面得分直接为 -100 分。

        参数:
            stock_code: 股票代码（6位数字）
            score_date: 评分日期
            hit_strategies: 已查询的命中策略列表（可选，为 None 时重新查询）
        返回:
            Tuple[bool, str]: (是否触发一票否决, 否决原因)
        """
        # 如果未启用一票否决，直接返回
        if not VETO_ENABLED:
            return False, ""
        
        # 如果未传入策略列表，重新查询
        if hit_strategies is None:
            hit_strategies = self._query_hit_strategies(
                stock_code, score_date
            )

        # 检查是否同时命中所有否决策略
        hit_veto_strategies = [s for s in VETO_STRATEGIES if s in hit_strategies]
        
        # 所有否决策略同时命中才触发一票否决
        if len(hit_veto_strategies) == len(VETO_STRATEGIES):
            reason = f"一票否决：同时命中 {', '.join(VETO_STRATEGIES)}"
            # 记录否决日志
            logger.warning(f"股票 {stock_code} {reason}")
            return True, reason

        # 未触发一票否决
        return False, ""

    def _build_strategy_list(
        self, hit_strategies: List[str]
    ) -> List[dict]:
        """
        构建策略详情列表，包含策略名称和对应权重

        参数:
            hit_strategies: 命中的策略名称列表
        返回:
            List[dict]: 策略详情列表，每个元素为 {"name": 策略名, "weight": 权重}
        """
        strategy_list = []
        for name in hit_strategies:
            # 尝试从配置文件中获取策略的中文名称
            import yaml
            from pathlib import Path
            
            config_path = Path(__file__).parent.parent / "config" / "strategy_params.yaml"
            # 确保路径正确
            if not config_path.exists():
                # 尝试使用当前工作目录
                config_path = Path.cwd() / "config" / "strategy_params.yaml"
            
            strategy_display_name = name
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f) or {}
                    
                    # 从配置中提取每个策略的 display_name
                    strategies_config = config.get('strategies', {})
                    for strategy_key, strategy_config in strategies_config.items():
                        # 将策略标识符转换为策略类名（如'morning_star' -> 'MorningStarStrategy'）
                        if '_' in name:
                            strategy_class_name = ''.join(word.capitalize() for word in name.split('_')) + 'Strategy'
                            if strategy_class_name == strategy_key:
                                strategy_display_name = strategy_config.get('display_name', name)
                                break
                except Exception as e:
                    logger.warning(f"读取策略配置失败: {e}")
            
            # 获取策略权重
            weight = STRATEGY_WEIGHTS.get(strategy_display_name, 0)
            # 添加到详情列表
            strategy_list.append({"name": strategy_display_name, "weight": weight})
        return strategy_list
    
    @staticmethod
    def reload_config():
        """
        重新加载配置文件
        
        当用户修改配置文件后，可以调用此方法重新加载配置，
        无需重启服务。
        """
        global STRATEGY_WEIGHTS, VETO_ENABLED, VETO_SCORE, VETO_STRATEGIES
        
        # 重新加载策略权重
        STRATEGY_WEIGHTS = _load_strategy_weights()
        
        # 重新加载一票否决配置
        VETO_ENABLED, VETO_SCORE, VETO_STRATEGIES = _load_veto_config()
        
        logger.info("策略权重配置已重新加载")
