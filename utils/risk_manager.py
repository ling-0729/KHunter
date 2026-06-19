"""
风控决策模块 - 风险等级判定和风控参数输出
"""
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Tuple
from enum import Enum
from datetime import datetime

# 配置日志
logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """风险等级枚举"""
    NORMAL = "正常"
    CAUTION = "注意"
    DANGER = "危险"
    CRASH = "崩溃"


@dataclass
class RiskStatus:
    """风控状态数据类"""
    date: str                    # 日期
    var_1d: float                # 单日VaR
    var_5d: float                # 5日VaR
    es_1d: Optional[float]       # 单日ES
    risk_level: RiskLevel        # 风险等级
    position_limit: float        # 仓位上限（0-1）
    stop_loss_multiplier: float  # 止损倍数
    score_extra: int             # 狩猎场额外分数门槛
    strategy_enabled: bool       # 策略是否启用
    liquidate: bool = False      # 是否强制清仓
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'date': self.date,
            'var_1d': self.var_1d,
            'var_5d': self.var_5d,
            'es_1d': self.es_1d,
            'risk_level': self.risk_level.value,
            'position_limit': self.position_limit,
            'stop_loss_multiplier': self.stop_loss_multiplier,
            'score_extra': self.score_extra,
            'strategy_enabled': self.strategy_enabled,
            'liquidate': self.liquidate
        }


class RiskManager:
    """风控管理器 - 负责风险等级判定和风控参数输出"""
    
    def __init__(self, config: dict = None):
        """
        初始化风控管理器
        
        参数：
            config: 风控配置字典
        """
        self.config = config or self._load_default_config()
        
        # 提取VaR阈值
        self.var_thresholds = self.config.get('var_thresholds', {})
        
        # 提取各风险等级的风控参数
        self.risk_levels_config = self.config.get('risk_levels', {})
        
        logger.info("RiskManager 初始化完成")
    
    def _load_default_config(self) -> dict:
        """
        加载默认配置
        
        返回：
            默认配置字典
        """
        return {
            'var_thresholds': {
                'normal': -0.03,
                'caution': -0.05,
                'danger': -0.08,
                'crash': -0.08
            },
            'risk_levels': {
                '正常': {
                    'position_limit': 1.0,
                    'stop_loss_multiplier': 2.0,
                    'score_extra': 0,
                    'strategy_enabled': True,
                    'liquidate': False
                },
                '注意': {
                    'position_limit': 0.7,
                    'stop_loss_multiplier': 1.5,
                    'score_extra': 5,
                    'strategy_enabled': True,
                    'liquidate': False
                },
                '危险': {
                    'position_limit': 0.4,
                    'stop_loss_multiplier': 1.0,
                    'score_extra': 15,
                    'strategy_enabled': True,
                    'liquidate': False
                },
                '崩溃': {
                    'position_limit': 0.0,
                    'stop_loss_multiplier': 0.0,
                    'score_extra': 999,
                    'strategy_enabled': False,
                    'liquidate': True
                }
            }
        }
    
    def determine_risk_level(self, var_1d: float) -> RiskLevel:
        """
        根据VaR确定风险等级
        
        参数：
            var_1d: 单日VaR（负数表示亏损）
            
        返回：
            RiskLevel: 风险等级
        """
        # 获取阈值
        normal_threshold = self.var_thresholds.get('normal', -0.03)
        caution_threshold = self.var_thresholds.get('caution', -0.05)
        danger_threshold = self.var_thresholds.get('danger', -0.08)
        
        # 判定风险等级
        if var_1d > normal_threshold:
            return RiskLevel.NORMAL
        elif var_1d > caution_threshold:
            return RiskLevel.CAUTION
        elif var_1d > danger_threshold:
            return RiskLevel.DANGER
        else:
            return RiskLevel.CRASH
    
    def get_risk_params(self, risk_level: RiskLevel) -> dict:
        """
        获取指定风险等级的风控参数
        
        参数：
            risk_level: 风险等级
            
        返回：
            风控参数字典
        """
        level_name = risk_level.value
        params = self.risk_levels_config.get(level_name, {})
        
        if not params:
            logger.warning(f"未找到风险等级 {level_name} 的配置，使用默认配置")
            params = {
                'position_limit': 1.0,
                'stop_loss_multiplier': 2.0,
                'score_extra': 0,
                'strategy_enabled': True,
                'liquidate': False
            }
        
        return params
    
    def create_risk_status(self, date: str, var_1d: float, var_5d: float,
                          es_1d: Optional[float] = None) -> RiskStatus:
        """
        创建风控状态对象
        
        参数：
            date: 日期
            var_1d: 单日VaR
            var_5d: 5日VaR
            es_1d: 单日ES（可选）
            
        返回：
            RiskStatus: 风控状态对象
        """
        # 确定风险等级
        risk_level = self.determine_risk_level(var_1d)
        
        # 获取风控参数
        params = self.get_risk_params(risk_level)
        
        # 创建风控状态对象
        risk_status = RiskStatus(
            date=date,
            var_1d=var_1d,
            var_5d=var_5d,
            es_1d=es_1d,
            risk_level=risk_level,
            position_limit=params.get('position_limit', 1.0),
            stop_loss_multiplier=params.get('stop_loss_multiplier', 2.0),
            score_extra=params.get('score_extra', 0),
            strategy_enabled=params.get('strategy_enabled', True),
            liquidate=params.get('liquidate', False)
        )
        
        logger.info(f"创建风控状态: {date}, 风险等级={risk_level.value}, "
                   f"VaR(1d)={var_1d:.4f}, 仓位上限={risk_status.position_limit:.0%}")
        
        return risk_status
    
    def get_default_risk_status(self, date: str = None) -> RiskStatus:
        """
        获取默认风控状态（数据不足时使用）
        
        参数：
            date: 日期，默认为当前日期
            
        返回：
            RiskStatus: 默认风控状态对象（保守设置）
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        # 使用保守的默认值
        return RiskStatus(
            date=date,
            var_1d=-0.04,
            var_5d=-0.09,
            es_1d=-0.05,
            risk_level=RiskLevel.CAUTION,
            position_limit=0.7,
            stop_loss_multiplier=1.5,
            score_extra=5,
            strategy_enabled=True,
            liquidate=False
        )
    
    def validate_config(self) -> Tuple[bool, str]:
        """
        验证配置有效性
        
        返回：
            (是否有效, 错误信息) 元组
        """
        # 检查VaR阈值
        thresholds = self.var_thresholds
        if not thresholds:
            return False, "VaR阈值配置为空"
        
        required_keys = ['normal', 'caution', 'danger', 'crash']
        for key in required_keys:
            if key not in thresholds:
                return False, f"缺少VaR阈值配置: {key}"
        
        # 检查阈值顺序（应该递减）
        if not (thresholds['normal'] > thresholds['caution'] > 
                thresholds['danger'] >= thresholds['crash']):
            return False, "VaR阈值顺序错误"
        
        # 检查风险等级配置
        risk_levels = self.risk_levels_config
        if not risk_levels:
            return False, "风险等级配置为空"
        
        for level_name in ['正常', '注意', '危险', '崩溃']:
            if level_name not in risk_levels:
                return False, f"缺少风险等级配置: {level_name}"
            
            params = risk_levels[level_name]
            required_params = ['position_limit', 'stop_loss_multiplier', 
                             'score_extra', 'strategy_enabled']
            for param in required_params:
                if param not in params:
                    return False, f"风险等级 {level_name} 缺少参数: {param}"
            
            # 检查仓位上限范围
            if not (0 <= params['position_limit'] <= 1):
                return False, f"风险等级 {level_name} 仓位上限超出范围"
        
        return True, ""


# 测试代码
if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 创建风控管理器
    manager = RiskManager()
    
    # 验证配置
    is_valid, msg = manager.validate_config()
    print(f"配置验证: {'通过' if is_valid else '失败'} - {msg}")
    
    # 测试不同VaR值的风险等级判定
    test_cases = [
        (-0.01, "正常"),
        (-0.04, "注意"),
        (-0.06, "危险"),
        (-0.10, "崩溃")
    ]
    
    print("\n风险等级判定测试:")
    for var, expected_level in test_cases:
        risk_level = manager.determine_risk_level(var)
        status = manager.create_risk_status("2026-05-14", var, var * 2.236)
        print(f"  VaR={var:.4f}: 风险等级={risk_level.value} (预期: {expected_level}), "
              f"仓位上限={status.position_limit:.0%}")
    
    # 获取默认风控状态
    default_status = manager.get_default_risk_status()
    print(f"\n默认风控状态:")
    print(f"  风险等级: {default_status.risk_level.value}")
    print(f"  仓位上限: {default_status.position_limit:.0%}")
    print(f"  止损倍数: {default_status.stop_loss_multiplier:.1f}")
    print(f"  额外分数: {default_status.score_extra}")