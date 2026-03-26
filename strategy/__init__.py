"""
策略模块

自动注册所有策略类
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入策略
from strategy.bowl_rebound import BowlReboundStrategy
from strategy.w_bottom_strategy import WBottomStrategy
from strategy.m_top_strategy import MTopStrategy

# 策略类映射
STRATEGIES = {
    'BowlReboundStrategy': BowlReboundStrategy,
    'WBottomStrategy': WBottomStrategy,
    'MTopStrategy': MTopStrategy,
}

__all__ = [
    'BowlReboundStrategy',
    'WBottomStrategy',
    'MTopStrategy',
    'STRATEGIES'
]
