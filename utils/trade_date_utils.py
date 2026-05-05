# -*- coding: utf-8 -*-
"""
交易日工具模块

提供判断日期是否为交易日的功能。
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

# 配置日志记录器
logger = logging.getLogger(__name__)


def is_trading_day(date_str: str) -> bool:
    """
    判断指定日期是否为交易日

    优先使用 Tushare 获取真实交易日历，包含节假日判断。
    如果 Tushare 不可用，则回退到简单的周末排除逻辑。

    参数:
        date_str: 日期字符串，支持 YYYY-MM-DD 或 YYYYMMDD 格式
    返回:
        bool: 是否为交易日
    """
    try:
        # 统一日期格式
        if '-' in date_str:
            date_str_fmt = date_str.replace('-', '')
        else:
            date_str_fmt = date_str
            date = datetime.strptime(date_str, '%Y%m%d')
        
        # 先尝试使用 Tushare 获取真实交易日历
        try:
            import tushare as ts
            from pathlib import Path
            # 尝试从配置文件加载 token
            config_path = Path(__file__).parent.parent / "config" / "tushare_config.json"
            if config_path.exists():
                import json
                with open(config_path, 'r') as f:
                    tushare_config = json.load(f)
                if 'api_key' in tushare_config:
                    ts.set_token(tushare_config['api_key'])
            pro = ts.pro_api()
            df = pro.trade_cal(
                start_date=date_str_fmt,
                end_date=date_str_fmt,
                is_open='1'
            )
            if df is not None and not df.empty:
                logger.debug(f"Tushare 确认 {date_str} 是交易日")
                return True
            else:
                logger.debug(f"Tushare 确认 {date_str} 不是交易日")
                return False
        except Exception as e:
            logger.debug(f"Tushare 交易日查询失败，使用周末判断: {e}")
        
        # 回退：排除周六(5)和周日(6)
        if '-' in date_str:
            date = datetime.strptime(date_str, '%Y-%m-%d')
        else:
            date = datetime.strptime(date_str, '%Y%m%d')
        
        weekday = date.weekday()
        if weekday >= 5:
            logger.debug(f"日期 {date_str} 是周末，不是交易日")
            return False
        
        logger.debug(f"日期 {date_str} 是交易日（基于周末判断）")
        return True
    except Exception as e:
        logger.error(f"判断交易日时出错: {e}")
        return False


def get_trading_days(start_date: str, end_date: str) -> List[str]:
    """
    获取指定日期范围内的交易日列表

    参数:
        start_date: 开始日期，支持 YYYY-MM-DD 或 YYYYMMDD 格式
        end_date: 结束日期，支持 YYYY-MM-DD 或 YYYYMMDD 格式
    返回:
        List[str]: 交易日列表，格式为 YYYY-MM-DD
    """
    try:
        # 统一日期格式
        if '-' in start_date:
            start = datetime.strptime(start_date, '%Y-%m-%d')
        else:
            start = datetime.strptime(start_date, '%Y%m%d')
        
        if '-' in end_date:
            end = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            end = datetime.strptime(end_date, '%Y%m%d')
        
        # 生成日期范围
        trading_days = []
        current = start
        while current <= end:
            if is_trading_day(current.strftime('%Y-%m-%d')):
                trading_days.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        logger.info(f"获取到 {len(trading_days)} 个交易日")
        return trading_days
    except Exception as e:
        logger.error(f"获取交易日列表时出错: {e}")
        return []


def get_trading_days_between(start_date: str, end_date: str) -> int:
    """
    计算两个日期之间的交易日天数

    参数:
        start_date: 开始日期，支持 YYYY-MM-DD 格式或 date 对象
        end_date: 结束日期，支持 YYYY-MM-DD 格式或 date 对象
    返回:
        int: 交易日天数
    """
    try:
        # 处理 date 对象
        if hasattr(start_date, 'strftime'):
            start_date_str = start_date.strftime('%Y-%m-%d')
        else:
            start_date_str = start_date
        
        if hasattr(end_date, 'strftime'):
            end_date_str = end_date.strftime('%Y-%m-%d')
        else:
            end_date_str = end_date
        
        # 获取交易日列表并返回长度
        trading_days = get_trading_days(start_date_str, end_date_str)
        return len(trading_days) - 1  # 减去1，因为不包括买入当天
    except Exception as e:
        logger.error(f"计算交易日天数时出错: {e}")
        return 0


def get_previous_trading_day(date_str: str) -> str:
    """
    获取指定日期的前一个交易日

    参数:
        date_str: 日期字符串，支持 YYYY-MM-DD 格式
    返回:
        str: 前一个交易日，格式为 YYYY-MM-DD
    """
    try:
        # 解析日期
        date = datetime.strptime(date_str, '%Y-%m-%d')
        
        # 向前查找前一个交易日
        current = date - timedelta(days=1)
        while True:
            current_str = current.strftime('%Y-%m-%d')
            if is_trading_day(current_str):
                logger.debug(f"{date_str} 的前一个交易日是 {current_str}")
                return current_str
            current -= timedelta(days=1)
    except Exception as e:
        logger.error(f"获取前一个交易日时出错: {e}")
        # 返回默认值
        return date_str
