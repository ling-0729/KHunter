# -*- coding: utf-8 -*-
"""股票工具类

提供股票代码判断、最小买卖单位等工具方法
"""

def is_kcb(code: str) -> bool:
    """判断是否为科创板股票

    Args:
        code: 股票代码

    Returns:
        bool: 是否为科创板股票（688开头）
    """
    return code.startswith('688')


def is_cyb(code: str) -> bool:
    """判断是否为创业板股票

    Args:
        code: 股票代码

    Returns:
        bool: 是否为创业板股票（300开头）
    """
    return code.startswith('300')


def is_bse(code: str) -> bool:
    """判断是否为北交所股票

    Args:
        code: 股票代码

    Returns:
        bool: 是否为北交所股票（8开头）
    """
    return code.startswith('8')


def get_min_trade_unit(code: str) -> int:
    """获取股票最小买卖单位

    A股规则：
    - 科创板（688开头）：200股
    - 北交所（8开头）：100股
    - 创业板（300开头）：100股
    - 其他（沪市主板600/601/603、深市主板000/001）：100股

    Args:
        code: 股票代码

    Returns:
        int: 最小买卖单位（股数）
    """
    if is_kcb(code):
        return 200
    elif is_bse(code):
        return 100
    elif is_cyb(code):
        return 100
    else:
        return 100


def normalize_quantity(code: str, quantity: float) -> int:
    """将买入数量调整为最小买卖单位

    A股规则：
    - 科创板（688开头）：最小200股，超过200股后可1股递增（200、201、202...都可以）
    - 其他板块：最小100股，必须100股取整（100、200、300...，不能是101、102等）

    Args:
        code: 股票代码
        quantity: 原始买入数量

    Returns:
        int: 调整后的买入数量
    """
    if quantity <= 0:
        return 0
    
    min_unit = get_min_trade_unit(code)
    if quantity < min_unit:
        return 0
    
    if is_kcb(code):
        return int(quantity)
    else:
        return int(quantity // 100) * 100