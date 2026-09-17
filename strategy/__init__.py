"""
策略模块

说明：
  - 选股策略由 strategy_registry.auto_register_from_directory("strategy") 自动注册，
    仅扫描**本目录下的 .py**（跳过 _ 开头文件）。
  - 暂不启用的策略已移至 strategy/disabled/ 子目录：代码保留、不参与注册，
    因而不会出现在选股与参数设置中；需要恢复时移回本目录即可。
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入策略
from strategy.limit_up_pullback_strategy import LimitUpPullbackStrategy

# 策略类映射
STRATEGIES = {
    'LimitUpPullbackStrategy': LimitUpPullbackStrategy,
}

__all__ = [
    'LimitUpPullbackStrategy',
    'STRATEGIES'
]
