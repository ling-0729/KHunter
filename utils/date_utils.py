# -*- coding: utf-8 -*-
"""
日期格式统一转换工具模块

功能：
- 将所有日期转换为统一的 YYYY-MM-DD 格式
- 支持多种输入格式：YYYY-MM-DD, YYYYMMDD, datetime, pd.Timestamp, date 等
- 用于数据入库前的日期标准化，确保数据库中所有日期字段格式一致

用法：
    from utils.date_utils import normalize_date
    
    # 所有输入都返回 "2026-06-15"
    normalize_date("2026-06-15")
    normalize_date("20260615")
    normalize_date(datetime.now())
    normalize_date(pd.Timestamp("2026-06-15"))
"""

import logging
from datetime import datetime, date
from typing import Union, Optional

# 配置日志记录器
logger = logging.getLogger(__name__)

# ==================== 日期格式常量 ====================
# 数据库标准日期格式
DB_DATE_FORMAT = "%Y-%m-%d"
# 数据库标准日期时间格式
DB_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
# Tushare 等外部数据源使用的紧凑日期格式
COMPACT_DATE_FORMAT = "%Y%m%d"


def normalize_date(date_value: Optional[Union[str, datetime, date, int, float]]) -> Optional[str]:
    """
    将各种日期格式统一转换为 YYYY-MM-DD 格式字符串

    支持以下输入类型：
    - str: "2026-06-15" 或 "20260615"
    - datetime: Python datetime 对象
    - date: Python date 对象
    - pd.Timestamp: pandas Timestamp 对象
    - float/int: 毫秒时间戳

    参数:
        date_value: 任意日期类型的值，None 返回 None

    返回:
        str: YYYY-MM-DD 格式的日期字符串，输入为 None 时返回 None

    示例:
        >>> normalize_date("20260615")
        "2026-06-15"
        >>> normalize_date("2026-06-15")
        "2026-06-15"
        >>> normalize_date(datetime(2026, 6, 15))
        "2026-06-15"
    """
    # None 值直接返回
    if date_value is None:
        return None

    try:
        # 尝试作为 pandas Timestamp 处理（最先处理，因为 pd.NaT 等需要特殊处理）
        try:
            import pandas as pd
            if isinstance(date_value, pd.Timestamp):
                return date_value.strftime(DB_DATE_FORMAT)
            # 处理 pd.NaT 等特殊值
            if pd.isna(date_value):
                return None
        except ImportError:
            pass

        # 处理 Python 原生 datetime/date 对象
        if isinstance(date_value, datetime):
            return date_value.strftime(DB_DATE_FORMAT)

        if isinstance(date_value, date):
            return date_value.strftime(DB_DATE_FORMAT)

        # 处理字符串输入
        if isinstance(date_value, str):
            date_str = date_value.strip()

            # 空字符串返回 None
            if not date_str:
                return None

            # 已经是 YYYY-MM-DD 格式（最常见情况，优先匹配）
            if '-' in date_str and len(date_str) == 10:
                # 格式: YYYY-MM-DD，直接返回
                return date_str

            # 包含时间部分的格式: "2026-06-15 00:00:00" 或 "2026-06-15 15:30:00"
            if ' ' in date_str:
                date_part = date_str.split(' ')[0]
                if '-' in date_part and len(date_part) == 10:
                    return date_part

            # YYYYMMDD 格式（8位纯数字）
            if len(date_str) == 8 and date_str.isdigit():
                return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

            # 其他可能的分隔符格式: "2026/06/15" 或 "2026.06.15"
            for sep in ['/', '.']:
                if sep in date_str:
                    parts = date_str.split(sep)
                    if len(parts) == 3 and len(parts[0]) == 4:
                        try:
                            dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                            return dt.strftime(DB_DATE_FORMAT)
                        except ValueError:
                            pass

            logger.debug(f"无法解析的日期字符串格式: {date_value}")
            return date_str

        # 处理数值类型（毫秒时间戳）
        if isinstance(date_value, (int, float)):
            # 尝试作为毫秒时间戳处理
            if date_value > 1000000000000:  # 大于此值的是毫秒时间戳
                try:
                    dt = datetime.fromtimestamp(date_value / 1000.0)
                    return dt.strftime(DB_DATE_FORMAT)
                except (ValueError, OSError):
                    pass
            # 尝试作为紧凑日期: 20260615
            date_int = int(date_value)
            if 19900101 <= date_int <= 20991231:
                date_str = str(date_int)
                return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

            logger.debug(f"无法解析的数值日期: {date_value}")
            return str(date_value)

        # 其他类型，尝试字符串转换
        logger.debug(f"未处理的日期类型: {type(date_value)}, value: {date_value}")
        return str(date_value)

    except Exception as e:
        logger.error(f"日期标准化失败: {e}, 输入值: {date_value}, 类型: {type(date_value)}")
        return str(date_value) if date_value is not None else None


def normalize_date_to_compact(date_value: Optional[Union[str, datetime, date]]) -> Optional[str]:
    """
    将日期转换为 YYYYMMDD 紧凑格式（用于 Tushare API 调用等场景）

    参数:
        date_value: 任意日期类型的值

    返回:
        str: YYYYMMDD 格式的日期字符串，输入为 None 时返回 None
    """
    normalized = normalize_date(date_value)
    if normalized is None:
        return None
    return normalized.replace('-', '')


def normalize_datetime(date_value: Optional[Union[str, datetime, date]]) -> Optional[str]:
    """
    将日期转换为 YYYY-MM-DD HH:MM:SS 格式（用于需要时间戳的场景）

    参数:
        date_value: 任意日期类型的值

    返回:
        str: YYYY-MM-DD HH:MM:SS 格式的日期时间字符串，输入为 None 时返回 None
    """
    if date_value is None:
        return None

    # 如果已是完整日期时间字符串
    if isinstance(date_value, str) and ' ' in date_value and len(date_value) >= 19:
        return date_value

    normalized = normalize_date(date_value)
    if normalized is None:
        return None
    # 附加默认时间 00:00:00
    return f"{normalized} 00:00:00"


def normalize_dataframe_date_column(df, date_col: str = 'date') -> None:
    """
    将 DataFrame 中的日期列统一转换为 YYYY-MM-DD 格式字符串
    原地修改 DataFrame，使用 normalize_date 处理每个单元格

    参数:
        df: pandas DataFrame
        date_col: 日期列名称，默认 'date'
    """
    try:
        if date_col not in df.columns:
            return

        # 对每个单元格使用 normalize_date 统一转换为 YYYY-MM-DD 格式
        df[date_col] = df[date_col].apply(
            lambda x: normalize_date(x) if x is not None else None
        )

    except Exception as e:
        logger.error(f"DataFrame 日期列标准化失败: {e}")


def is_valid_date(date_str: str) -> bool:
    """
    检查字符串是否为有效的 YYYY-MM-DD 日期格式

    参数:
        date_str: 待检查的日期字符串

    返回:
        bool: 是否为有效日期
    """
    if not date_str or not isinstance(date_str, str):
        return False

    try:
        normalized = normalize_date(date_str)
        if normalized is None:
            return False
        # 尝试解析确认日期合法（如排除 2026-02-30 这种）
        datetime.strptime(normalized, DB_DATE_FORMAT)
        return True
    except ValueError:
        return False
    except Exception:
        return False
