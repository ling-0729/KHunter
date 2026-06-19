# -*- coding: utf-8 -*-
"""
连续市场温度风控模块

基于连续交易日市场温度的风险识别和仓位控制

核心功能：
1. 读取最近N个交易日的温度数据
2. 检查数据连续性，自动补充缺失数据
3. 计算连续2/3/5天平均温度
4. 按优先级匹配风控场景
5. 更新market_temperature表的action字段
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import yaml
from pathlib import Path

# 配置日志
logger = logging.getLogger(__name__)


@dataclass
class TempRiskScenario:
    """温度风控场景规则（从配置文件加载）"""
    scenario_code: str       # 场景编号
    scenario_name: str       # 场景名称
    consecutive_days: int    # 连续天数
    avg_temp_threshold: float # 平均温度阈值
    position_limit: float    # 仓位限制
    risk_level: str          # 风险等级
    priority: int            # 优先级（数字越小优先级越高）
    is_enabled: bool         # 是否启用


@dataclass
class ContinuousTempRiskResult:
    """连续温度风控结果（不存储，仅用于计算）"""
    trade_date: str                    # 交易日期
    current_temp: float               # 当日温度
    avg_temp_2d: Optional[float]      # 连续2天平均温度
    avg_temp_3d: Optional[float]      # 连续3天平均温度
    avg_temp_5d: Optional[float]      # 连续5天平均温度
    matched_scenario: Optional[str]   # 匹配的场景编号
    position_ratio: float             # 仓位系数
    action_text: str                  # action字段文本


class ContinuousTempRiskController:
    """连续市场温度风控控制器"""
    
    # 自动补充温度数据的最大日历天数：超过此天数的缺失数据不再调API，直接用默认值50
    MAX_AUTO_FILL_DAYS = 5
    
    def __init__(self, config_path: str = 'config/continuous_temp_risk.yaml'):
        """
        初始化控制器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.scenarios = self._load_scenarios()
        self.enabled = self._load_enabled()
        logger.info(f"连续温度风控模块初始化完成，共加载 {len(self.scenarios)} 个场景")
    
    def _load_enabled(self) -> bool:
        """
        加载模块启用状态
        
        Returns:
            是否启用连续温度风控模块
        """
        try:
            config_file = Path(self.config_path)
            if not config_file.exists():
                logger.warning(f"配置文件不存在: {self.config_path}")
                return False
            
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            
            return config.get('enabled', True)
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return False
    
    def _load_scenarios(self) -> List[TempRiskScenario]:
        """
        从配置文件加载场景规则
        
        Returns:
            场景规则列表（按优先级排序）
        """
        scenarios = []
        
        try:
            config_file = Path(self.config_path)
            if not config_file.exists():
                logger.warning(f"配置文件不存在: {self.config_path}")
                return scenarios
            
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            
            scenario_configs = config.get('scenarios', [])
            
            for scenario_cfg in scenario_configs:
                scenario = TempRiskScenario(
                    scenario_code=scenario_cfg.get('code', ''),
                    scenario_name=scenario_cfg.get('name', ''),
                    consecutive_days=scenario_cfg.get('consecutive_days', 1),
                    avg_temp_threshold=scenario_cfg.get('avg_temp_threshold', 0.0),
                    position_limit=scenario_cfg.get('position_limit', 1.0),
                    risk_level=scenario_cfg.get('risk_level', '正常'),
                    priority=scenario_cfg.get('priority', 99),
                    is_enabled=scenario_cfg.get('enabled', True)
                )
                scenarios.append(scenario)
            
            # 按优先级排序（数字越小优先级越高）
            scenarios.sort(key=lambda x: x.priority)
            
            logger.info(f"成功加载 {len(scenarios)} 个场景规则")
            
        except Exception as e:
            logger.error(f"加载场景配置失败: {e}")
        
        return scenarios
    
    def evaluate(self, trade_date: str) -> ContinuousTempRiskResult:
        """
        评估指定日期的连续温度风险
        
        Args:
            trade_date: 交易日期，格式YYYYMMDD
            
        Returns:
            ContinuousTempRiskResult: 风控评估结果
        """
        if not self.enabled:
            logger.info("连续温度风控模块未启用")
            return ContinuousTempRiskResult(
                trade_date=trade_date,
                current_temp=0.0,
                avg_temp_2d=None,
                avg_temp_3d=None,
                avg_temp_5d=None,
                matched_scenario=None,
                position_ratio=1.0,
                action_text="市场温度正常，无风控限制"
            )
        
        logger.info(f"开始评估连续温度风险，日期: {trade_date}")
        
        # 获取最近5天温度数据（支持自动补充）
        temp_data = self.get_recent_temperatures(trade_date, 5)
        
        if not temp_data:
            logger.warning("无法获取温度数据，使用默认值")
            return ContinuousTempRiskResult(
                trade_date=trade_date,
                current_temp=50.0,
                avg_temp_2d=None,
                avg_temp_3d=None,
                avg_temp_5d=None,
                matched_scenario=None,
                position_ratio=1.0,
                action_text="市场温度正常，无风控限制"
            )
        
        # 获取当日温度
        current_temp = temp_data[0].get('temperature', 50.0)
        
        # 计算各天数平均温度
        avg_temps = {}
        for days in [2, 3, 5]:
            avg_temp = self.calculate_average_temp(temp_data, days)
            avg_temps[days] = avg_temp
            logger.debug(f"连续{days}天平均温度: {avg_temp}")
        
        # 添加单日温度（用于SCENARIO_1）
        avg_temps[1] = current_temp
        
        # 匹配场景
        matched_scenario = self.match_scenario(avg_temps)
        
        # 生成结果
        if matched_scenario:
            position_ratio = matched_scenario.position_limit
            action_text = f"[{matched_scenario.scenario_code}] {matched_scenario.scenario_name}，仓位限制{int(position_ratio * 100)}%"
            logger.info(f"匹配到场景: {matched_scenario.scenario_code}，仓位限制: {position_ratio * 100}%")
        else:
            position_ratio = 1.0
            action_text = "市场温度正常，无风控限制"
            logger.info("未匹配到任何风控场景")
        
        # 更新market_temperature表的action字段
        self.update_market_temperature(trade_date, position_ratio, action_text)
        
        return ContinuousTempRiskResult(
            trade_date=trade_date,
            current_temp=current_temp,
            avg_temp_2d=avg_temps.get(2),
            avg_temp_3d=avg_temps.get(3),
            avg_temp_5d=avg_temps.get(5),
            matched_scenario=matched_scenario.scenario_code if matched_scenario else None,
            position_ratio=position_ratio,
            action_text=action_text
        )
    
    def get_recent_temperatures(self, trade_date: str, days: int, 
                                  auto_fill: bool = True) -> List[Dict]:
        """
        获取最近N个交易日的温度数据（支持自动补充缺失数据）
        
        逻辑：
        1. 从market_temperature表查询最近N天的数据
        2. 检查数据是否连续（按交易日历）
        3. 如果发现数据缺失：
           - auto_fill=True: 调用MarketTemperature.calculate()补充缺失日期数据
           - 最多补充连续5天缺失数据
           - 补充完成后重新查询
        4. 如果补充失败或auto_fill=False：
           - 缺失日期按默认温度值50计算
        
        Args:
            trade_date: 截止日期（YYYYMMDD格式）
            days: 期望获取天数
            auto_fill: 是否自动补充缺失数据，默认True
            
        Returns:
            List[Dict]: 温度数据列表，每个元素包含：
                - trade_date: 交易日期
                - temperature: 温度值
                - is_continuous: 是否与上一条连续
                - is_filled: 是否为补充数据（自动计算）
                - is_default: 是否为默认值填充（50）
        """
        from trading.market_temperature_dao import MarketTemperatureDAO
        
        dao = MarketTemperatureDAO()
        
        # 查询最近days+5天的数据（留有余量）
        results = dao.db.query(
            '''SELECT trade_date, temperature FROM market_temperature 
               WHERE trade_date <= ? 
               ORDER BY trade_date DESC LIMIT ?''',
            (trade_date, days + 5)
        )
        
        if not results:
            logger.warning(f"未查询到温度数据，日期: {trade_date}")
            return []
        
        # 按日期倒序排列
        temp_data = sorted(results, key=lambda x: x['trade_date'], reverse=True)
        
        # 检查数据连续性并补充缺失数据
        if auto_fill:
            # 获取最近的交易日期列表
            trade_dates = self._get_trade_dates(trade_date, days)
            
            if trade_dates:
                # 找出缺失的日期
                existing_dates = {item['trade_date'] for item in temp_data}
                missing_dates = [d for d in trade_dates if d not in existing_dates]
                
                # 最多补充连续5天缺失数据
                if missing_dates:
                    # 只补充最近的连续缺失日期
                    missing_dates_sorted = sorted(missing_dates)
                    consecutive_missing = []
                    
                    # 从最早的缺失日期开始检查连续性
                    for i, missing_date in enumerate(missing_dates_sorted):
                        if i == 0:
                            consecutive_missing.append(missing_date)
                        else:
                            # 检查是否连续（相差1天）
                            prev_date = missing_dates_sorted[i-1]
                            if self._is_consecutive(prev_date, missing_date):
                                consecutive_missing.append(missing_date)
                            else:
                                # 不连续，停止补充
                                break
                    
                    # 最多补充5天，且只补充最近MAX_AUTO_FILL_DAYS天内的数据
                    consecutive_missing = consecutive_missing[:5]
                    
                    # 过滤掉过早的日期：只自动补充最近窗口内的缺失数据
                    # 更早的数据直接用默认值50，避免大量Tushare API调用
                    recent_missing = self._filter_recent_dates(consecutive_missing)
                    
                    if recent_missing:
                        stale_missing = [d for d in consecutive_missing if d not in recent_missing]
                        if stale_missing:
                            logger.info(
                                f"跳过补充过早数据（>{self.MAX_AUTO_FILL_DAYS}天前）: {stale_missing}"
                            )
                        logger.info(f"发现缺失数据，尝试补充: {recent_missing}")
                        self.fill_missing_temperatures(recent_missing)
                        
                        # 补充后重新查询
                        results = dao.db.query(
                            '''SELECT trade_date, temperature FROM market_temperature 
                               WHERE trade_date <= ? 
                               ORDER BY trade_date DESC LIMIT ?''',
                            (trade_date, days + 5)
                        )
                        temp_data = sorted(results, key=lambda x: x['trade_date'], reverse=True)
        
        # 整理结果，确保连续
        return self._ensure_continuous_data(temp_data, days, trade_date)
    
    def _ensure_continuous_data(self, temp_data: List[Dict], days: int, 
                                end_date: str) -> List[Dict]:
        """
        确保数据连续性，缺失部分用默认值填充
        
        Args:
            temp_data: 原始温度数据
            days: 需要的天数
            end_date: 结束日期
            
        Returns:
            连续的温度数据列表
        """
        if not temp_data:
            return []
        
        # 获取应该有的交易日期
        trade_dates = self._get_trade_dates(end_date, days)
        if not trade_dates:
            return temp_data[:days]
        
        result = []
        existing_dict = {item['trade_date']: item['temperature'] for item in temp_data}
        
        for trade_date in trade_dates:
            if trade_date in existing_dict:
                result.append({
                    'trade_date': trade_date,
                    'temperature': existing_dict[trade_date],
                    'is_continuous': True,
                    'is_filled': False,
                    'is_default': False
                })
            else:
                # 使用默认值50填充
                result.append({
                    'trade_date': trade_date,
                    'temperature': 50.0,
                    'is_continuous': True,
                    'is_filled': False,
                    'is_default': True
                })
        
        return result
    
    def _is_consecutive(self, date1: str, date2: str) -> bool:
        """
        检查两个日期是否连续
        
        Args:
            date1: 日期1（YYYYMMDD格式）
            date2: 日期2（YYYYMMDD格式）
            
        Returns:
            是否连续
        """
        try:
            d1 = datetime.strptime(date1, '%Y%m%d')
            d2 = datetime.strptime(date2, '%Y%m%d')
            return (d2 - d1).days == 1
        except Exception:
            return False
    
    def _get_trade_dates(self, trade_date: str, count: int) -> List[str]:
        """
        获取最近的交易日列表
        
        Args:
            trade_date: 参考日期（YYYYMMDD格式）
            count: 需要的天数
            
        Returns:
            交易日列表（按日期降序排列）
        """
        try:
            from utils.market_temperature import MarketTemperature
            
            mt = MarketTemperature()
            dates = mt._get_trade_dates(trade_date, count)
            # 按日期降序排列
            return sorted(dates, reverse=True)
        except Exception as e:
            logger.error(f"获取交易日历失败: {e}")
            # 如果获取失败，返回模拟的连续日期
            return self._generate_consecutive_dates(trade_date, count)
    
    def _generate_consecutive_dates(self, trade_date: str, count: int) -> List[str]:
        """
        生成连续的日期列表（作为备用方案）
        
        Args:
            trade_date: 参考日期（YYYYMMDD格式）
            count: 需要的天数
            
        Returns:
            日期列表（按日期降序排列）
        """
        dates = []
        try:
            base_date = datetime.strptime(trade_date, '%Y%m%d')
            for i in range(count):
                date = base_date - timedelta(days=i)
                dates.append(date.strftime('%Y%m%d'))
        except Exception:
            pass
        return dates
    
    def _filter_recent_dates(self, dates: List[str]) -> List[str]:
        """
        过滤出最近 MAX_AUTO_FILL_DAYS 天内的日期

        只对最近的缺失数据自动补充（调用 Tushare API），
        更早的直接用默认值 50，避免大量无意义的 API 调用。

        Args:
            dates: 日期列表（YYYYMMDD格式）

        Returns:
            在最近窗口内的日期列表
        """
        if not dates:
            return []
        try:
            cutoff = datetime.now() - timedelta(days=self.MAX_AUTO_FILL_DAYS)
            cutoff_str = cutoff.strftime('%Y%m%d')
            return [d for d in dates if d >= cutoff_str]
        except Exception:
            return dates
    
    def fill_missing_temperatures(self, missing_dates: List[str]) -> bool:
        """
        补充缺失的温度数据
        
        调用MarketTemperature模块计算缺失日期的温度数据
        
        Args:
            missing_dates: 缺失日期列表
            
        Returns:
            bool: 是否全部补充成功
        """
        from utils.market_temperature import MarketTemperature
        
        success_count = 0
        mt = MarketTemperature()
        
        for trade_date in missing_dates:
            try:
                logger.info(f"尝试补充温度数据，日期: {trade_date}")
                # skip_risk_eval=True 避免递归级联：
                # calculate() 内部不再触发 evaluate_continuous_temp_risk()，
                # 防止补录 → 风控 → 补录 → 风控的无限循环
                result = mt.calculate(trade_date, use_cache=True, skip_risk_eval=True)
                if result:
                    success_count += 1
                    logger.info(f"成功补充温度数据，日期: {trade_date}，温度: {result.get('temperature')}")
            except Exception as e:
                logger.warning(f"补充温度数据失败，日期: {trade_date}，错误: {e}")
        
        return success_count == len(missing_dates)
    
    def calculate_average_temp(self, temp_data: List[Dict], days: int) -> Optional[float]:
        """
        计算最近N天的平均温度（确保数据连续）
        
        Args:
            temp_data: 温度数据列表（按日期倒序）
            days: 计算天数
            
        Returns:
            Optional[float]: 平均温度，数据不连续或不足返回None
        """
        if len(temp_data) < days:
            logger.debug(f"数据不足{days}天，无法计算平均温度")
            return None
        
        # 检查数据连续性
        continuous, _ = self.check_data_continuity(temp_data[:days])
        if not continuous:
            logger.debug(f"最近{days}天数据不连续，无法计算平均温度")
            return None
        
        # 计算平均温度
        temps = [item['temperature'] for item in temp_data[:days] if item.get('temperature') is not None]
        
        if not temps:
            return None
        
        return round(sum(temps) / len(temps), 1)
    
    def check_data_continuity(self, temp_data: List[Dict]) -> Tuple[bool, int]:
        """
        检查温度数据的连续性
        
        Args:
            temp_data: 温度数据列表（按日期倒序）
            
        Returns:
            Tuple[bool, int]: (是否连续, 连续天数)
        """
        if len(temp_data) < 2:
            return (True, len(temp_data))
        
        # 按日期升序排列检查
        sorted_data = sorted(temp_data, key=lambda x: x['trade_date'])
        
        for i in range(1, len(sorted_data)):
            prev_date = sorted_data[i-1]['trade_date']
            curr_date = sorted_data[i]['trade_date']
            
            if not self._is_consecutive(prev_date, curr_date):
                # 检查是否是周末或节假日导致的不连续
                d1 = datetime.strptime(prev_date, '%Y%m%d')
                d2 = datetime.strptime(curr_date, '%Y%m%d')
                days_diff = (d2 - d1).days
                
                # 最多允许间隔3天（考虑周末+节假日）
                if days_diff > 3:
                    return (False, i)
        
        return (True, len(temp_data))
    
    def match_scenario(self, avg_temps: Dict[int, float]) -> Optional[TempRiskScenario]:
        """
        根据平均温度匹配合适的场景
        
        匹配逻辑：按优先级从高到低遍历场景，找到第一个满足条件的场景
        
        Args:
            avg_temps: 各天数的平均温度字典 {1: 单日温度, 2: avg_2d, 3: avg_3d, 5: avg_5d}
            
        Returns:
            Optional[TempRiskScenario]: 匹配的场景，无匹配返回None
        """
        # 按优先级排序（已在加载时排序）
        for scenario in self.scenarios:
            if not scenario.is_enabled:
                continue
            
            days = scenario.consecutive_days
            avg_temp = avg_temps.get(days)
            
            # 如果该天数的平均温度不存在，跳过
            if avg_temp is None:
                continue
            
            # 检查是否满足条件（平均温度 < 阈值）
            if avg_temp < scenario.avg_temp_threshold:
                logger.debug(f"场景 {scenario.scenario_code} 匹配成功: {avg_temp} < {scenario.avg_temp_threshold}")
                return scenario
        
        return None
    
    def update_market_temperature(self, trade_date: str, position_ratio: float, action_text: str) -> bool:
        """
        更新market_temperature表的action字段和position_ratio字段
        
        Args:
            trade_date: 交易日期
            position_ratio: 仓位系数
            action_text: action字段文本
            
        Returns:
            bool: 是否更新成功
        """
        from trading.market_temperature_dao import MarketTemperatureDAO
        
        try:
            dao = MarketTemperatureDAO()
            existing = dao.query_by_date(trade_date)
            
            if existing:
                # 更新现有记录
                record = {
                    'trade_date': trade_date,
                    'position_ratio': position_ratio,
                    'action': action_text,
                    'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                dao.db.update('market_temperature', record, {'trade_date': trade_date})
                logger.info(f"更新市场温度风控信息成功，日期: {trade_date}, action: {action_text}")
                return True
            else:
                logger.warning(f"未找到市场温度记录，日期: {trade_date}")
                return False
        except Exception as e:
            logger.error(f"更新市场温度风控信息失败: {e}")
            return False


# ==================== 对外接口 ====================

def evaluate_continuous_temp_risk(trade_date: str, auto_fill: bool = True) -> Dict:
    """
    评估连续温度风险（对外接口）
    
    处理逻辑：
    1. 从market_temperature表读取最近5天温度数据
    2. 检查数据连续性，识别缺失日期
    3. 如果数据缺失且auto_fill=True：
       - 调用MarketTemperature.calculate()补充缺失日期数据（最多5天）
       - 重新读取完整数据
    4. 如果补充失败，缺失日期按默认温度值50计算
    5. 根据连续天数计算平均温度
    6. 匹配风控场景，生成仓位建议
    7. 更新market_temperature表的action字段
    
    Args:
        trade_date: 交易日期，格式YYYYMMDD
        auto_fill: 是否自动补充缺失数据，默认True
        
    Returns:
        Dict: 风控评估结果
    """
    try:
        controller = ContinuousTempRiskController()
        result = controller.evaluate(trade_date)
        
        return {
            'trade_date': result.trade_date,
            'current_temp': result.current_temp,
            'avg_temp_2d': result.avg_temp_2d,
            'avg_temp_3d': result.avg_temp_3d,
            'avg_temp_5d': result.avg_temp_5d,
            'matched_scenario': result.matched_scenario,
            'position_ratio': result.position_ratio,
            'action_text': result.action_text,
            'success': True,
            'warning': None
        }
    except Exception as e:
        logger.error(f"评估连续温度风险失败: {e}")
        return {
            'trade_date': trade_date,
            'current_temp': None,
            'avg_temp_2d': None,
            'avg_temp_3d': None,
            'avg_temp_5d': None,
            'matched_scenario': None,
            'position_ratio': 1.0,
            'action_text': "市场温度正常，无风控限制",
            'success': False,
            'warning': str(e)
        }


def get_consecutive_position_ratio(trade_date: str) -> float:
    """
    获取连续温度风控计算的仓位系数（替代单日温度风控）
    
    Args:
        trade_date: 交易日期（YYYYMMDD格式）
        
    Returns:
        float: 仓位系数（0.00-1.00），用于替代原有的position_ratio
    """
    try:
        result = evaluate_continuous_temp_risk(trade_date)
        return result.get('position_ratio', 0.5)
    except Exception as e:
        logger.error(f"获取连续温度风控仓位系数失败: {e}")
        return 0.5


# ==================== 测试函数 ====================

def test_continuous_temp_risk():
    """测试连续温度风控功能"""
    logger.info("=" * 60)
    logger.info("测试连续温度风控模块")
    logger.info("=" * 60)
    
    # 测试评估功能
    today = datetime.now().strftime('%Y%m%d')
    result = evaluate_continuous_temp_risk(today)
    
    logger.info(f"评估日期: {result['trade_date']}")
    logger.info(f"当前温度: {result['current_temp']}")
    logger.info(f"连续2天平均: {result['avg_temp_2d']}")
    logger.info(f"连续3天平均: {result['avg_temp_3d']}")
    logger.info(f"连续5天平均: {result['avg_temp_5d']}")
    logger.info(f"匹配场景: {result['matched_scenario']}")
    logger.info(f"仓位系数: {result['position_ratio']}")
    logger.info(f"Action文本: {result['action_text']}")
    logger.info(f"成功: {result['success']}")
    
    logger.info("=" * 60)
    logger.info("测试完成")
    logger.info("=" * 60)


if __name__ == '__main__':
    test_continuous_temp_risk()