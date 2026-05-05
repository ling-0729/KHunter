"""
策略模块

自动注册所有策略类
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入策略
from strategy.w_bottom_strategy import WBottomStrategy
from strategy.limit_up_pullback_strategy import LimitUpPullbackStrategy

# 策略类映射
STRATEGIES = {
    'WBottomStrategy': WBottomStrategy,
    'LimitUpPullbackStrategy': LimitUpPullbackStrategy,
}

__all__ = [
    'WBottomStrategy',
    'LimitUpPullbackStrategy',
    'STRATEGIES'
]
