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
            
            # 生成反向映射
            reverse_mapping = {v: k for k, v in strategy_names.items()}
            
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
        'TrendAccelerationInflectionStrategy': '趋势加速拐点',
        'MorningStarStrategy': '启明星策略',
        'MultiGoldenCrossStrategy': '多金叉共振',
        'MultiPartyCannonStrategy': '多方炮策略',
        'BottomTrendInflectionStrategy': '底部趋势拐点',
        'LimitUpPullbackStrategy': '涨停回马枪策略',
        'LimitUpSidewaysStrategy': '涨停横盘策略',
        'StrongWashWeakToStrongStrategy': '强势洗盘弱转强',
        'WBottomStrategy': 'W底策略',
        'ImmortalGuidanceStrategy': '仙人指路策略',
        'MA20MA60Strategy': '520560策略',
    }
    
    reverse_map = {v: k for k, v in default_map.items()}
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


def get_chinese_name(english_name: str) -> str:
    """
    将英文策略名称转换为中文名称
    
    Args:
        english_name: 英文策略名称（类名）
        
    Returns:
        中文策略名称，如果不存在则返回原名称
    """
    return STRATEGY_NAME_MAP.get(english_name, english_name)


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
