#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
策略名称映射工具

将策略的英文类名转换为中文名称，反之亦然
支持从配置文件加载映射表
"""

import yaml
from pathlib import Path

# 配置文件路径
CONFIG_FILE = Path(__file__).parent.parent / "config" / "strategy_name_mapping.yaml"

# 缓存映射表
_STRATEGY_NAME_MAP = None
_STRATEGY_NAME_REVERSE_MAP = None


def _load_mapping_from_config():
    """
    从配置文件加载策略名称映射
    
    Returns:
        tuple: (正向映射表, 反向映射表)
    """
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            
            # 获取正向映射
            strategy_names = config.get('strategy_names', {})
            
            # 生成反向映射（基于中文名->英文类名）
            reverse_mapping = {v: k for k, v in strategy_names.items()}
            
            # 合并显式定义的反向映射条目（如蛇形命名别名）
            explicit_reverse = config.get('reverse_mapping', {})
            reverse_mapping.update(explicit_reverse)
            
            return strategy_names, reverse_mapping
    except Exception as e:
        print(f"警告: 无法从配置文件加载策略名称映射: {str(e)}")
    
    # 如果配置文件不存在或加载失败，使用默认映射
    return _get_default_mapping()


def _get_default_mapping():
    """
    获取默认的策略名称映射（硬编码备用）
    
    Returns:
        tuple: (正向映射表, 反向映射表)
    """
    default_map = {
        'ContinuousRisingWithVolumeStrategyV2': '连阳回调策略',
        'ResistanceBreakoutStrategy': '阻力位突破策略',
        'MainUptrendDipBuyStrategy': '主升低吸策略',
        'NewStockDrawdownStrategy': '次新腰斩策略',
        'TrendAccelerationInflectionStrategy': '趋势加速拐点',
        'MorningStarStrategy': '启明星策略',
        'MultiGoldenCrossStrategy': '多金叉共振',
        'MultiPartyCannonStrategy': '多方炮策略',
        'BottomTrendInflectionStrategy': '底部趋势拐点',
        'LimitUpPullbackStrategy': '涨停回马枪策略',
        'LimitUpSidewaysStrategy': '涨停横盘策略',
        'StrongWashWeakToStrongStrategy': '强势洗盘弱转强',
        'TrendResonanceReversalStrategy': '趋势共振反转策略',
        'WBottomStrategy': 'W底策略',
        'ImmortalGuidanceStrategy': '仙人指路策略',
        'MA20MA60Strategy': '520560策略',
        'Strategy2560Selection': '2560战法选股策略',
        'TrendStartStrategy': '趋势起点策略',
        'GoldenCrossNotGreenStrategy': '金叉不绿策略',
    }

    reverse_map = {v: k for k, v in default_map.items()}

    # 添加蛇形命名别名，用于定时任务等场景
    reverse_map['immortal_guidance'] = 'ImmortalGuidanceStrategy'

    return default_map, reverse_map


def _get_strategy_name_map():
    """
    获取策略名称映射表（正向）
    
    Returns:
        dict: 英文类名 -> 中文名称的映射表
    """
    global _STRATEGY_NAME_MAP
    if _STRATEGY_NAME_MAP is None:
        _STRATEGY_NAME_MAP, _ = _load_mapping_from_config()
    return _STRATEGY_NAME_MAP


def _get_strategy_name_reverse_map():
    """
    获取策略名称映射表（反向）
    
    Returns:
        dict: 中文名称 -> 英文类名的映射表
    """
    global _STRATEGY_NAME_REVERSE_MAP
    if _STRATEGY_NAME_REVERSE_MAP is None:
        _, _STRATEGY_NAME_REVERSE_MAP = _load_mapping_from_config()
    return _STRATEGY_NAME_REVERSE_MAP


# 初始化映射表
STRATEGY_NAME_MAP = _get_strategy_name_map()
STRATEGY_NAME_REVERSE_MAP = _get_strategy_name_reverse_map()


def _normalize_name(name: str) -> str:
    """名称归一化：去下划线/连字符/空格 + 统一小写 + 去尾部 `Strategy` ✓

    目的：让「全类名 / 短名 / 蛇形名」三种写法互相等效 ✓
      例：`GoldenTriangleStrategy` == `GoldenTriangle` == `golden_triangle` ✓
    """
    s = (str(name or '').strip()
         .replace('_', '').replace('-', '').replace(' ', '').lower())
    if s.endswith('strategy') and len(s) > len('strategy'):
        s = s[:-len('strategy')]
    return s


def get_chinese_name(english_name: str) -> str:
    """
    将英文策略名称转换为中文名称
    
    支持类名直接映射和蛇形命名别名：
    1. 先用 english_name 直接在正向映射中查找
    2. 如果未找到，尝试通过反向映射获取类名，再查正向映射
       （处理 snake_case -> ClassName -> 中文名 的转换链）
    3. 【2026-09-24】归一化兜底：全类名 / 短名 / 蛇形名互认 ✓
    
    Args:
        english_name: 英文策略名称（类名 / 短名 / 蛇形命名别名）
        
    Returns:
        中文策略名称，如果不存在则返回原名称
    """
    # 步骤1: 直接正向查找
    if english_name in STRATEGY_NAME_MAP:
        return STRATEGY_NAME_MAP[english_name]
    # 步骤2: 通过反向映射获取类名，再正向查找
    class_name = STRATEGY_NAME_REVERSE_MAP.get(english_name)
    if class_name and class_name in STRATEGY_NAME_MAP:
        return STRATEGY_NAME_MAP[class_name]
    # 步骤3【2026-09-24】归一化兜底 ✓
    #   背景：映射表里通常只有**全类名**（如 GoldenTriangleStrategy ✓），
    #   而运行器/飞书简报/本地日报传进来的是**短名**（如 GoldenTriangle ✗）
    #   → 原先步骤 1、2 均未命中 → 直接返回英文 ✗，
    #     导致简报与日报里策略名显示为英文 ✗（如 [GoldenTriangle] ✗）。
    #   现按归一化名再匹配一次：短名/全类名/蛇形名三者等效 ✓
    norm = _normalize_name(english_name)
    if norm:
        for key, value in STRATEGY_NAME_MAP.items():
            if _normalize_name(key) == norm:
                return value
    return english_name


# ===== 择时策略英文→中文映射 =====
# 【2026-09-24】补齐海龟家族两个缺失键 ✓ ——
#   原先 'turtle_plus' / 'low_turtle' 未登记 ✗ → 飞书简报与本地日报里
#   择时策略显示为英文 ✗（如 [turtle_plus] ✗），与选股策略的显示风格不一致 ✗。
_TIMING_NAME_MAP = {
    'turtle': '海龟策略',
    'low_turtle': '低位海龟',
    'turtle_plus': '海龟plus',
    'support': '支撑位策略',
    'rsi': 'RSI策略',
    'bollinger': '布林带策略',
    'macd_bollinger': '顺势宝',
    'uptrend_pullback': '趋势回调缩量策略',
}


def get_chinese_timing_name(english_name: str) -> str:
    """
    将择时策略英文名称转换为中文名称
    
    Args:
        english_name: 择时策略英文名称
        
    Returns:
        中文择时策略名称，如果不存在则返回原名称
    """
    return _TIMING_NAME_MAP.get(english_name, english_name)


def get_english_name(chinese_name: str) -> str:
    """
    将中文策略名称转换为英文名称
    
    Args:
        chinese_name: 中文策略名称
        
    Returns:
        英文策略名称（类名），如果不存在则返回原名称
    """
    return STRATEGY_NAME_REVERSE_MAP.get(chinese_name, chinese_name)


def is_english_name(name: str) -> bool:
    """
    判断是否为英文策略名称
    
    Args:
        name: 策略名称
        
    Returns:
        True 如果是英文名称，False 如果是中文名称
    """
    return name in STRATEGY_NAME_MAP


def is_chinese_name(name: str) -> bool:
    """
    判断是否为中文策略名称
    
    Args:
        name: 策略名称
        
    Returns:
        True 如果是中文名称，False 如果是英文名称
    """
    return name in STRATEGY_NAME_REVERSE_MAP


def reload_mapping():
    """
    重新加载策略名称映射（用于配置文件更新后）
    """
    global _STRATEGY_NAME_MAP, _STRATEGY_NAME_REVERSE_MAP
    _STRATEGY_NAME_MAP = None
    _STRATEGY_NAME_REVERSE_MAP = None
    
    # 重新初始化
    globals()['STRATEGY_NAME_MAP'] = _get_strategy_name_map()
    globals()['STRATEGY_NAME_REVERSE_MAP'] = _get_strategy_name_reverse_map()
