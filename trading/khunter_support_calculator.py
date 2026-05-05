#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KHunter 支撑位计算模块
负责计算股票的支撑位价格，支持多种计算方法
"""

import pandas as pd
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import yaml

# 配置日志
logger = logging.getLogger(__name__)


class KHunterSupportCalculator:
    """
    KHunter 支撑位计算器
    支持4种支撑位计算方法：ma20、key_close_5、key_open、key_close
    """
    
    # 支撑位计算方法映射
    SUPPORT_METHODS = {
        'ma20': '_calculate_ma20',
        'key_close_5': '_calculate_key_close_5',
        'key_open': '_calculate_key_open',
        'key_close': '_calculate_key_close',
    }
    
    # 方法名称映射（旧 -> 新）
    METHOD_NAME_MAPPING = {
        'ma': 'ma20',
        'low': None,  # 不支持
        'percentage': 'key_close_5',
        'resistance': None,  # 不支持
        'ma20': 'ma20',
        'key_close_5': 'key_close_5',
        'key_open': 'key_open',
        'key_close': 'key_close',
    }
    
    # 策略支撑位计算方法配置（已移到 config/support_methods.yaml）
    # 保留此处作为备用，但优先从配置文件读取
    STRATEGY_SUPPORT_METHODS = {
        'LimitUpPullbackStrategy': 'key_close_5',
        'MultiGoldenCrossStrategy': 'ma20',
        'MultiPartyCannonStrategy': 'key_open',
        'ResistanceBreakoutStrategy': 'key_close_5',
        'StrongWashWeakToStrongStrategy': 'key_close',
        'TrendAccelerationInflectionStrategy': 'key_close_5',
        'WBottomStrategy': 'ma20',
        'LimitUpSidewaysStrategy': 'key_close_5',
        'MorningStarStrategy': 'ma20',
        'BottomTrendInflectionStrategy': 'ma20',
    }
    
    # 默认支撑位计算方法
    DEFAULT_SUPPORT_METHOD = 'ma20'
    
    # 加载范围：跟踪天数 + 120个交易日（增加到120以确保关键日期在范围内）
    LOAD_DAYS_BUFFER = 120
    
    def __init__(self, db_manager, config_manager=None):
        """
        初始化支撑位计算器
        
        参数：
            db_manager: 数据库管理器
            config_manager: 配置管理器（可选）
        """
        # db_manager: 数据库管理器，类型object，必填
        # config_manager: 配置管理器，类型object，可选
        self.db_manager = db_manager
        self.config_manager = config_manager
        
        # 从配置文件加载支撑位配置
        self._load_support_methods_config()
        
        logger.info("KHunter 支撑位计算器初始化完成")
    
    def _load_support_methods_config(self):
        """
        从配置文件加载支撑位计算方法配置
        
        优先级：
        1. 从 config/support_methods.yaml 读取
        2. 如果失败，使用代码中的 STRATEGY_SUPPORT_METHODS
        """
        try:
            # 尝试从配置文件加载
            config_path = Path(__file__).parent.parent / "config" / "support_methods.yaml"
            
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                
                # 从配置文件中提取策略支撑位配置
                strategies_config = config.get('strategies', {})
                
                if strategies_config:
                    # 更新 STRATEGY_SUPPORT_METHODS
                    self.STRATEGY_SUPPORT_METHODS = {}
                    for strategy_name, strategy_config in strategies_config.items():
                        support_method = strategy_config.get('support_method')
                        if support_method:
                            self.STRATEGY_SUPPORT_METHODS[strategy_name] = support_method
                    
                    logger.info(f"从配置文件加载了 {len(self.STRATEGY_SUPPORT_METHODS)} 个策略的支撑位配置")
                
                # 更新默认支撑位方法
                default_method = config.get('default_support_method')
                if default_method:
                    self.DEFAULT_SUPPORT_METHOD = default_method
                    logger.info(f"默认支撑位计算方法: {self.DEFAULT_SUPPORT_METHOD}")
            else:
                logger.warning(f"支撑位配置文件不存在: {config_path}，使用代码中的默认配置")
        
        except Exception as e:
            logger.warning(f"加载支撑位配置文件失败: {str(e)}，使用代码中的默认配置")
    
    # ==================== 公开方法 ====================
    
    def calculate_support_level(
        self,
        stock_code: str,
        hunting_date: str,
        strategy_name: str,
        tracking_days: int = 10,
        key_date: Optional[str] = None
    ) -> float:
        """
        计算单个股票的支撑位
        
        参数：
            stock_code: 股票代码，例如 000001
            hunting_date: 狩猎日期，格式 YYYY-MM-DD
            strategy_name: 策略名称，例如 多方炮策略
            tracking_days: 跟踪天数，默认10
            key_date: 关键日期（策略的关键日期），格式 YYYY-MM-DD，可选
        
        返回：
            float: 支撑位价格，精确到小数点后两位
        
        异常：
            ValueError: 如果K线数据不足或计算失败
            KeyError: 如果策略配置不存在
        """
        # stock_code: 股票代码，类型str，必填
        # hunting_date: 狩猎日期，类型str，必填
        # strategy_name: 策略名称，类型str，必填
        # tracking_days: 跟踪天数，类型int，默认10
        # key_date: 关键日期，类型str，可选
        try:
            # 1. 加载K线数据
            df_kline = self._load_kline_data(
                stock_code, hunting_date, tracking_days
            )
            
            # 2. 获取支撑位计算方法
            support_method = self._get_support_method(strategy_name)
            
            # 3. 标准化方法名称
            support_method = self._normalize_support_method(support_method)
            
            # 4. 调用对应的计算方法
            method_func = getattr(self, self.SUPPORT_METHODS[support_method])
            
            # 5. 根据方法类型传递不同的参数
            if support_method in ['key_open', 'key_close', 'key_close_5']:
                # 这些方法需要关键日期
                if not key_date:
                    raise ValueError(f"策略 {strategy_name} 需要关键日期，请提供key_date参数")
                support_level = method_func(df_kline, key_date)
            else:
                # ma20方法不需要关键日期
                support_level = method_func(df_kline)
            
            logger.debug(
                f"计算支撑位成功: {stock_code} {hunting_date} "
                f"{strategy_name} {support_method} -> {support_level}"
            )
            return support_level
        
        except Exception as e:
            logger.error(
                f"计算支撑位失败: {stock_code} {hunting_date} "
                f"{strategy_name} - {str(e)}"
            )
            raise
    
    def calculate_support_levels_batch(
        self,
        stock_codes: List[str],
        hunting_date: str,
        tracking_days: int = 10,
        key_dates: Optional[Dict[str, str]] = None
    ) -> Dict[str, Dict[str, float]]:
        """
        批量计算多个股票的支撑位
        
        参数：
            stock_codes: 股票代码列表
            hunting_date: 狩猎日期，格式 YYYY-MM-DD
            tracking_days: 跟踪天数，默认10
            key_dates: 关键日期字典，格式 {stock_code: key_date}，可选
        
        返回：
            Dict: {
                stock_code: {
                    'support_level': float,
                    'strategy_name': str,
                    'method': str
                },
                ...
            }
        
        异常：
            ValueError: 如果K线数据不足或计算失败
        """
        # stock_codes: 股票代码列表，类型List[str]，必填
        # hunting_date: 狩猎日期，类型str，必填
        # tracking_days: 跟踪天数，类型int，默认10
        # key_dates: 关键日期字典，类型Dict[str, str]，可选
        try:
            # 1. 批量加载K线数据
            kline_dict = self._load_kline_data_batch(
                stock_codes, hunting_date, tracking_days
            )
            
            # 2. 批量计算支撑位
            results = {}
            for stock_code in stock_codes:
                if stock_code not in kline_dict:
                    logger.warning(f"{stock_code} K线数据不存在，跳过")
                    continue
                
                # 3. 获取支撑位计算方法
                support_method = self._get_support_method(stock_code)
                
                # 4. 调用对应的计算方法
                df_kline = kline_dict[stock_code]
                method_func = getattr(
                    self, self.SUPPORT_METHODS[support_method]
                )
                
                # 5. 根据方法类型传递不同的参数
                if support_method in ['resistance_break', 'key_open', 'key_close', 'key_close_5']:
                    # 这些方法需要关键日期
                    if not key_dates:
                        raise ValueError(f"策略 {strategy_name} 需要关键日期，请提供key_dates参数")
                    key_date = key_dates.get(stock_code)
                    if not key_date:
                        raise ValueError(f"股票 {stock_code} 缺少关键日期")
                    support_level = method_func(df_kline, key_date)
                else:
                    support_level = method_func(df_kline)
                
                # 6. 保存结果
                results[stock_code] = {
                    'support_level': support_level,
                    'strategy_name': stock_code,
                    'method': support_method
                }
            
            logger.info(
                f"批量计算支撑位完成: {len(results)}/{len(stock_codes)} 只股票"
            )
            return results
        
        except Exception as e:
            logger.error(f"批量计算支撑位失败: {str(e)}")
            raise
    
    # ==================== 私有方法 - 数据加载 ====================
    
    def _load_kline_data(
        self,
        stock_code: str,
        hunting_date: str,
        tracking_days: int
    ) -> pd.DataFrame:
        """
        加载单只股票的K线数据
        
        参数：
            stock_code: 股票代码
            hunting_date: 狩猎日期
            tracking_days: 跟踪天数
        
        返回：
            pd.DataFrame: K线数据
        """
        # stock_code: 股票代码，类型str，必填
        # hunting_date: 狩猎日期，类型str，必填
        # tracking_days: 跟踪天数，类型int，必填
        try:
            # 1. 计算加载范围
            load_days = tracking_days + self.LOAD_DAYS_BUFFER
            start_date = self._calculate_date_before(hunting_date, load_days)
            end_date = hunting_date
            
            # 2. 查询K线数据
            sql = """
            SELECT date, open, high, low, close, volume
            FROM stock_kline
            WHERE code = ? AND date BETWEEN ? AND ?
            ORDER BY date ASC
            """
            
            results = self.db_manager.query(
                sql, (stock_code, start_date, end_date)
            )
            
            # 3. 转换为DataFrame
            if not results:
                raise ValueError(f"{stock_code} 在 {start_date} 到 {end_date} 范围内没有K线数据")
            
            # 4. 创建DataFrame并设置列名（跳过第一列code）
            df = pd.DataFrame(results, columns=['code', 'date', 'open', 'high', 'low', 'close', 'volume'])
            df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
            
            # 4. 验证数据完整性
            if len(df) < 20:
                raise ValueError(
                    f"{stock_code} K线数据不足，需要至少20条记录，实际{len(df)}条"
                )
            
            logger.debug(f"加载K线数据成功: {stock_code} {len(df)} 条记录")
            return df
        
        except Exception as e:
            logger.error(f"加载K线数据失败: {stock_code} - {str(e)}")
            raise
    
    def _load_kline_data_batch(
        self,
        stock_codes: List[str],
        hunting_date: str,
        tracking_days: int
    ) -> Dict[str, pd.DataFrame]:
        """
        批量加载K线数据
        
        参数：
            stock_codes: 股票代码列表
            hunting_date: 狩猎日期
            tracking_days: 跟踪天数
        
        返回：
            Dict: {stock_code: DataFrame, ...}
        """
        # stock_codes: 股票代码列表，类型List[str]，必填
        # hunting_date: 狩猎日期，类型str，必填
        # tracking_days: 跟踪天数，类型int，必填
        try:
            # 1. 计算加载范围
            load_days = tracking_days + self.LOAD_DAYS_BUFFER
            start_date = self._calculate_date_before(hunting_date, load_days)
            end_date = hunting_date
            
            # 2. 批量查询K线数据
            placeholders = ','.join(['?' for _ in stock_codes])
            sql = f"""
            SELECT code, date, open, high, low, close, volume
            FROM stock_kline
            WHERE code IN ({placeholders})
              AND date BETWEEN ? AND ?
            ORDER BY code, date ASC
            """
            
            params = stock_codes + [start_date, end_date]
            results = self.db_manager.query(sql, tuple(params))
            
            # 3. 按股票代码分组
            kline_dict = {}
            for row in results:
                code = row[0]
                date = row[1]
                open_price = row[2]
                high = row[3]
                low = row[4]
                close = row[5]
                volume = row[6]
                
                if code not in kline_dict:
                    kline_dict[code] = []
                kline_dict[code].append({
                    'date': date,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'close': close,
                    'volume': volume
                })
            
            # 4. 转换为DataFrame
            df_dict = {}
            for code, data in kline_dict.items():
                df_dict[code] = pd.DataFrame(data)
            
            # 5. 验证数据完整性
            for code in stock_codes:
                if code not in df_dict:
                    logger.warning(f"{code} 没有K线数据")
                elif len(df_dict[code]) < 20:
                    logger.warning(
                        f"{code} K线数据不足，需要至少20条记录，实际{len(df_dict[code])}条"
                    )
            
            logger.info(
                f"批量加载K线数据完成: {len(df_dict)}/{len(stock_codes)} 只股票"
            )
            return df_dict
        
        except Exception as e:
            logger.error(f"批量加载K线数据失败: {str(e)}")
            raise
    
    # ==================== 私有方法 - 支撑位计算 ====================
    
    def _calculate_ma20(self, df_kline: pd.DataFrame) -> float:
        """
        计算20日均线
        
        参数：
            df_kline: K线数据，必须包含 close 列
        
        返回：
            float: 20日均线价格
        """
        # df_kline: K线数据，类型pd.DataFrame，必填
        try:
            # 1. 获取狩猎日前20个交易日的收盘价
            close_prices = df_kline['close'].tail(20).values
            
            # 2. 计算平均值
            ma20 = close_prices.mean()
            
            # 3. 精确到小数点后两位
            return round(ma20, 2)
        
        except Exception as e:
            logger.error(f"计算ma20失败: {str(e)}")
            raise
    
    def _calculate_key_open(self, df_kline: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """
        计算关键日开盘价
        
        参数：
            df_kline: K线数据，必须包含 open 列
            key_date: 关键日期，格式 YYYY-MM-DD，必填
        
        返回：
            float: 关键日开盘价
        
        异常：
            ValueError: 如果关键日期不存在或为空
        """
        # df_kline: K线数据，类型pd.DataFrame，必填
        # key_date: 关键日期，类型str，必填
        try:
            # 1. 验证关键日期是否提供
            if not key_date:
                raise ValueError("关键日期不能为空")
            
            # 2. 标准化日期格式（确保为 YYYY-MM-DD）
            key_date_str = str(key_date)[:10]
            
            # 3. 尝试精确匹配关键日期
            key_date_idx = df_kline[df_kline['date'].astype(str).str[:10] == key_date_str].index
            
            # 4. 如果精确匹配失败，尝试找最接近的日期
            if len(key_date_idx) == 0:
                logger.warning(f"关键日期 {key_date_str} 不在K线数据中，尝试查找最接近的日期")
                
                # 转换日期为 datetime 对象进行比较
                df_kline_copy = df_kline.copy()
                df_kline_copy['date_obj'] = pd.to_datetime(df_kline_copy['date'].astype(str).str[:10])
                key_date_obj = pd.to_datetime(key_date_str)
                
                # 计算日期差异
                df_kline_copy['date_diff'] = abs(df_kline_copy['date_obj'] - key_date_obj)
                
                # 找到最接近的日期
                closest_idx = df_kline_copy['date_diff'].idxmin()
                closest_diff_days = df_kline_copy.loc[closest_idx, 'date_diff'].days
                
                # 如果最接近的日期在 1 天以内，使用该日期
                if closest_diff_days <= 1:
                    logger.warning(
                        f"使用最接近的日期 {df_kline.loc[closest_idx, 'date']} "
                        f"（相差 {closest_diff_days} 天）作为关键日期"
                    )
                    key_date_idx = [closest_idx]
                else:
                    raise ValueError(
                        f"关键日期 {key_date_str} 不在K线数据中，"
                        f"最接近的日期相差 {closest_diff_days} 天"
                    )
            
            # 5. 获取关键日的开盘价
            key_open = df_kline['open'].iloc[key_date_idx[0]]
            
            # 6. 精确到小数点后两位
            return round(key_open, 2)
        
        except Exception as e:
            logger.error(f"计算key_open失败: {str(e)}")
            raise
    
    
    def _calculate_key_close_5(self, df_kline: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """
        计算关键日收盘价下5%
        
        参数：
            df_kline: K线数据，必须包含 close 列
            key_date: 关键日期，格式 YYYY-MM-DD，必填
        
        返回：
            float: 关键日收盘价下5%
        
        异常：
            ValueError: 如果关键日期不存在或为空
        """
        # df_kline: K线数据，类型pd.DataFrame，必填
        # key_date: 关键日期，类型str，必填
        try:
            # 1. 验证关键日期是否提供
            if not key_date:
                raise ValueError("关键日期不能为空")
            
            # 2. 查找关键日期在K线数据中的位置
            key_date_idx = df_kline[df_kline['date'] == key_date].index
            
            # 3. 验证关键日期是否存在于K线数据中
            if len(key_date_idx) == 0:
                raise ValueError(f"关键日期 {key_date} 不在K线数据中")
            
            # 4. 获取关键日的收盘价
            key_close = df_kline['close'].iloc[key_date_idx[0]]
            
            # 5. 计算下5%的价格
            support_level = key_close * (1 - 0.05)
            
            # 6. 精确到小数点后两位
            return round(support_level, 2)
        
        except Exception as e:
            logger.error(f"计算key_close_5失败: {str(e)}")
            raise
    
    def _calculate_key_close(self, df_kline: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """
        计算关键日收盘价
        
        参数：
            df_kline: K线数据，必须包含 close 列
            key_date: 关键日期，格式 YYYY-MM-DD，必填
        
        返回：
            float: 关键日收盘价
        
        异常：
            ValueError: 如果关键日期不存在或为空
        """
        # df_kline: K线数据，类型pd.DataFrame，必填
        # key_date: 关键日期，类型str，必填
        try:
            # 1. 验证关键日期是否提供
            if not key_date:
                raise ValueError("关键日期不能为空")
            
            # 2. 查找关键日期在K线数据中的位置
            key_date_idx = df_kline[df_kline['date'] == key_date].index
            
            # 3. 验证关键日期是否存在于K线数据中
            if len(key_date_idx) == 0:
                raise ValueError(f"关键日期 {key_date} 不在K线数据中")
            
            # 4. 获取关键日的收盘价
            key_close = df_kline['close'].iloc[key_date_idx[0]]
            
            # 5. 精确到小数点后两位
            return round(key_close, 2)
        
        except Exception as e:
            logger.error(f"计算key_close失败: {str(e)}")
            raise
    
    # ==================== 私有方法 - 配置管理 ====================
    
    def _normalize_support_method(self, method: str) -> str:
        """
        将旧方法名称转换为新方法名称
        
        参数：
            method: 支撑位计算方法名称
        
        返回：
            str: 标准化后的方法名称
        """
        # method: 支撑位计算方法名称，类型str，必填
        # 获取标准化后的方法名称
        normalized_method = self.METHOD_NAME_MAPPING.get(method, method)
        
        # 如果方法不支持，使用默认方法
        if normalized_method is None:
            logger.warning(f"方法 {method} 不再支持，使用默认方法 'ma20'")
            return 'ma20'
        
        # 如果是旧方法名称，添加警告日志
        if method != normalized_method and method in self.METHOD_NAME_MAPPING:
            logger.warning(f"方法 {method} 已过时，请使用 {normalized_method}")
        
        return normalized_method
    
    def _get_support_method(self, strategy_name: str) -> str:
        """
        获取策略的支撑位计算方法
        
        参数：
            strategy_name: 策略名称
        
        返回：
            str: 支撑位计算方法
        """
        # strategy_name: 策略名称，类型str，必填
        try:
            # 1. 优先从策略配置中获取
            if strategy_name in self.STRATEGY_SUPPORT_METHODS:
                method = self.STRATEGY_SUPPORT_METHODS[strategy_name]
                logger.debug(
                    f"策略 {strategy_name} 的支撑位计算方法: {method}"
                )
                return method
            
            # 2. 尝试从配置管理器读取
            if self.config_manager:
                # 3. 调用配置管理器的方法获取支撑位计算方法
                method = self.config_manager.get_support_method(strategy_name)
                
                # 4. 验证方法是否有效
                if method in self.SUPPORT_METHODS:
                    logger.debug(
                        f"策略 {strategy_name} 的支撑位计算方法: {method}"
                    )
                    return method
            
            # 5. 如果配置不存在或无效，使用默认方法
            logger.debug(
                f"策略 {strategy_name} 未配置支撑位计算方法，使用默认方法 {self.DEFAULT_SUPPORT_METHOD}"
            )
            return self.DEFAULT_SUPPORT_METHOD
        
        except Exception as e:
            logger.warning(f"读取支撑位计算方法失败: {str(e)}，使用默认方法")
            return self.DEFAULT_SUPPORT_METHOD
    
    def _get_score_threshold(self) -> float:
        """
        从 backtest_config 表读取评分阈值
        
        返回：
            float: 评分阈值，默认60
        """
        try:
            # 1. 查询评分阈值
            sql = "SELECT score_threshold FROM backtest_config LIMIT 1"
            result = self.db_manager.query_one(sql)
            
            # 2. 返回结果或默认值
            if result and 'score_threshold' in result:
                threshold = result['score_threshold']
                logger.debug(f"读取评分阈值: {threshold}")
                return float(threshold)
            
            # 3. 使用默认值
            logger.debug("评分阈值不存在，使用默认值 60")
            return 60.0
        
        except Exception as e:
            logger.warning(f"读取评分阈值失败: {str(e)}，使用默认值 60")
            return 60.0
    
    # ==================== 私有方法 - 工具函数 ====================
    
    def _calculate_date_before(self, date_str: str, days: int) -> str:
        """
        计算指定日期前N天的日期
        
        参数：
            date_str: 日期字符串，格式 YYYY-MM-DD
            days: 天数
        
        返回：
            str: 计算后的日期字符串
        """
        # date_str: 日期字符串，类型str，必填
        # days: 天数，类型int，必填
        try:
            # 1. 解析日期
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            
            # 2. 计算前N天
            before_date = date_obj - timedelta(days=days)
            
            # 3. 返回字符串格式
            return before_date.strftime('%Y-%m-%d')
        
        except Exception as e:
            logger.error(f"计算日期失败: {str(e)}")
            raise
    
    def _get_previous_trading_day(self, date_str: str) -> Optional[str]:
        """
        获取前一个交易日
        
        参数：
            date_str: 日期字符串，格式 YYYY-MM-DD
        
        返回：
            str: 前一个交易日，如果不存在返回 None
        """
        # date_str: 日期字符串，类型str，必填
        try:
            # 1. 查询前一个交易日
            sql = """
            SELECT MAX(date) as prev_date
            FROM stock_kline
            WHERE date < ?
            """
            
            result = self.db_manager.query_one(sql, (date_str,))
            
            # 2. 返回结果
            if result and result.get('prev_date'):
                return result['prev_date']
            
            return None
        
        except Exception as e:
            logger.error(f"获取前一个交易日失败: {str(e)}")
            return None
