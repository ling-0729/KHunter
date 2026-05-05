#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KHunter 数据处理模块
负责完整的狩猎场数据处理流程，包括确定狩猎日期、获取选股记录、计算支撑位、判断买点等
"""

import logging
import json
import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import time

# 配置日志
logger = logging.getLogger(__name__)


class KHunterDataProcessor:
    """
    KHunter 数据处理器
    负责完整的狩猎场数据处理流程
    """
    
    # 默认跟踪天数
    DEFAULT_TRACKING_DAYS = 10
    
    def __init__(self, db_manager, support_calculator, buy_point_judge):
        """
        初始化数据处理器
        
        参数：
            db_manager: 数据库管理器
            support_calculator: 支撑位计算器
            buy_point_judge: 买点判断器
        """
        # db_manager: 数据库管理器，类型object，必填
        # support_calculator: 支撑位计算器，类型object，必填
        # buy_point_judge: 买点判断器，类型object，必填
        self.db_manager = db_manager
        self.support_calculator = support_calculator
        self.buy_point_judge = buy_point_judge
        logger.info("KHunter 数据处理器初始化完成")
    
    # ==================== 公开方法 ====================
    
    def process(
        self,
        hunting_date: str,
        tracking_days: int = DEFAULT_TRACKING_DAYS,
        timing_strategy: str = 'support'
    ) -> Dict[str, Any]:
        """
        处理狩猎场数据
        
        参数：
            hunting_date: 狩猎日期，格式 YYYY-MM-DD
            tracking_days: 跟踪天数，默认10
            timing_strategy: 择时策略名称，默认support，可选support/turtle/rsi/bollinger
        
        返回：
            Dict: {
                'hunting_date': str,
                'tracking_days': int,
                'timing_strategy': str,
                'from_cache': bool,
                'total_count': int,
                'calculation_time': float,
                'results': [
                    {
                        'stock_code': str,
                        'stock_name': str,
                        'industry': str,
                        'sector': str,
                        'support_level': float,
                        'current_price': float,
                        'price_diff': float,
                        'price_diff_percent': float,
                        'buy_range': str,
                        'strategy_name': str,
                        'score': float,
                        'timing_strategy': str,
                        'timing_signal': str
                    },
                    ...
                ]
            }
        
        异常：
            ValueError: 如果处理失败
        """
        # hunting_date: 狩猎日期，类型str，必填
        # tracking_days: 跟踪天数，类型int，默认10
        # timing_strategy: 择时策略名称，类型str，默认support
        start_time = time.time()
        
        try:
            # 1. 确定狩猎日期
            actual_hunting_date = self._determine_hunting_date(hunting_date)
            logger.info(f"确定狩猎日期: {hunting_date} -> {actual_hunting_date}")
            
            # 2. 检查缓存（按timing_strategy过滤）
            cached_results = self._check_cache(actual_hunting_date, timing_strategy)
            if cached_results is not None:
                calculation_time = time.time() - start_time
                logger.info(f"从缓存加载结果: {len(cached_results)} 条记录，耗时 {calculation_time:.2f}s")
                return {
                    'hunting_date': actual_hunting_date,
                    'tracking_days': tracking_days,
                    'timing_strategy': timing_strategy,
                    'from_cache': True,
                    'total_count': len(cached_results),
                    'calculation_time': calculation_time,
                    'results': cached_results
                }
            
            # 3. 获取选股记录
            selection_records = self._get_selection_records(
                actual_hunting_date, tracking_days
            )
            logger.info(f"获取选股记录: {len(selection_records)} 条")
            
            # 4. 按分数阈值过滤
            filtered_records = self._filter_by_score_threshold(selection_records)
            logger.info(f"按分数阈值过滤: {len(filtered_records)} 条")
            
            # 5. 根据择时策略类型判断买点
            results = []
            for record in filtered_records:
                try:
                    # 6. 根据择时策略选择不同的判断逻辑
                    if timing_strategy == 'support':
                        # 6a. 支撑位策略：走现有逻辑
                        result = self._calculate_and_judge(record, actual_hunting_date)
                    else:
                        # 6b. 其他择时策略：使用择时策略判断
                        result = self._judge_by_timing_strategy(
                            record, actual_hunting_date, timing_strategy
                        )
                    
                    # 7. 只保存符合买点条件的记录
                    if result is not None:
                        results.append(result)
                
                except Exception as e:
                    logger.warning(
                        f"处理股票 {record.get('stock_code')} 失败: {str(e)}"
                    )
                    continue
            
            logger.info(f"符合买点条件的记录: {len(results)} 条")
            
            # 8. 准备结果数据
            final_results = self._prepare_result(results)
            
            # 9. 计算耗时
            calculation_time = time.time() - start_time
            
            logger.info(f"数据处理完成，耗时 {calculation_time:.2f}s")
            
            return {
                'hunting_date': actual_hunting_date,
                'tracking_days': tracking_days,
                'timing_strategy': timing_strategy,
                'from_cache': False,
                'total_count': len(final_results),
                'calculation_time': calculation_time,
                'results': final_results
            }
        
        except Exception as e:
            logger.error(f"数据处理失败: {str(e)}")
            raise
    
    # ==================== 私有方法 - 核心处理 ====================
    
    def _determine_hunting_date(self, hunting_date: str) -> str:
        """
        确定狩猎日期
        
        参数：
            hunting_date: 用户选择的日期
        
        返回：
            str: 实际狩猎日期
        """
        # hunting_date: 用户选择的日期，类型str，必填
        try:
            # 1. 检查用户选择的日期是否有K线数据
            sql = "SELECT COUNT(*) as count FROM stock_kline WHERE date = ?"
            result = self.db_manager.query_one(sql, (hunting_date,))
            
            # 2. 如果有数据，使用选择日期
            if result and result['count'] > 0:
                logger.debug(f"狩猎日期 {hunting_date} 有K线数据")
                return hunting_date
            
            # 3. 如果没有数据，使用前一个交易日
            sql = "SELECT MAX(date) as prev_date FROM stock_kline WHERE date < ?"
            result = self.db_manager.query_one(sql, (hunting_date,))
            
            # 4. 返回前一个交易日
            if result and result['prev_date']:
                logger.debug(f"狩猎日期 {hunting_date} 无K线数据，使用前一个交易日 {result['prev_date']}")
                return result['prev_date']
            
            # 5. 如果都没有数据，抛出异常
            raise ValueError(f"无法确定狩猎日期，{hunting_date} 及之前没有K线数据")
        
        except Exception as e:
            logger.error(f"确定狩猎日期失败: {str(e)}")
            raise
    
    def _get_selection_records(
        self,
        hunting_date: str,
        tracking_days: int
    ) -> List[Dict]:
        """
        获取选股记录
        
        参数：
            hunting_date: 狩猎日期
            tracking_days: 跟踪天数
        
        返回：
            List: 选股记录列表
        """
        # hunting_date: 狩猎日期，类型str，必填
        # tracking_days: 跟踪天数，类型int，必填
        try:
            # 1. 计算选股日期范围
            start_date = self._calculate_date_before(hunting_date, tracking_days)
            end_date = hunting_date
            
            # 2. 查询选股记录
            sql = """
            SELECT id, stock_code, stock_name, industry, sector, 
                   strategy_name, score, selection_date, key_dates
            FROM stock_selection_record
            WHERE selection_date BETWEEN ? AND ?
              AND is_active = 1
            ORDER BY selection_date DESC, score DESC
            """
            
            # 3. 执行查询
            results = self.db_manager.query(sql, (start_date, end_date))
            
            logger.debug(f"获取选股记录: {start_date} 到 {end_date}，共 {len(results)} 条")
            return results
        
        except Exception as e:
            logger.error(f"获取选股记录失败: {str(e)}")
            raise
    
    def _filter_by_score_threshold(
        self,
        records: List[Dict]
    ) -> List[Dict]:
        """
        按分数阈值过滤
        
        参数：
            records: 选股记录列表
        
        返回：
            List: 过滤后的记录列表
        """
        # records: 选股记录列表，类型List[Dict]，必填
        try:
            # 1. 获取分数阈值
            score_threshold = self._get_score_threshold()
            
            # 2. 过滤记录：只保留有评分的记录，且分数 >= 阈值
            filtered = [r for r in records if r.get('score') is not None and r.get('score') >= score_threshold]
            
            # 3. 统计被过滤掉的记录
            no_score_count = sum(1 for r in records if r.get('score') is None)
            below_threshold_count = len(records) - len(filtered) - no_score_count
            
            logger.info(
                f"按分数阈值过滤: {len(records)} -> {len(filtered)} 条 "
                f"(阈值: {score_threshold}, 无评分: {no_score_count}, 低于阈值: {below_threshold_count})"
            )
            return filtered
        
        except Exception as e:
            logger.error(f"按分数阈值过滤失败: {str(e)}")
            raise
    
    def _calculate_and_judge(
        self,
        record: Dict,
        hunting_date: str
    ) -> Optional[Dict]:
        """
        计算支撑位和判断买点
        
        参数：
            record: 选股记录
            hunting_date: 狩猎日期
        
        返回：
            Dict: 处理结果，如果不符合买点条件返回 None
        """
        # record: 选股记录，类型Dict，必填
        # hunting_date: 狩猎日期，类型str，必填
        try:
            # 1. 获取必要信息
            stock_code = record['stock_code']
            strategy_name = record['strategy_name']
            
            # 2. 从key_dates字段解析关键日
            key_date = self._extract_key_date(record)
            if not key_date:
                logger.warning(f"{stock_code} 无法获取关键日")
                return None
            
            # 3. 获取当前价格
            current_price = self._get_current_price(stock_code, hunting_date)
            if not current_price:
                logger.warning(f"{stock_code} 无法获取当前价格")
                return None
            
            # 4. 计算支撑位，传入关键日
            try:
                support_level = self.support_calculator.calculate_support_level(
                    stock_code=stock_code,
                    hunting_date=hunting_date,
                    strategy_name=strategy_name,
                    key_date=key_date
                )
            except Exception as e:
                logger.warning(f"{stock_code} 计算支撑位失败: {str(e)}")
                return None
            
            # 4. 判断买点
            try:
                buy_point_result = self.buy_point_judge.judge_buy_point(
                    current_price, support_level
                )
            except Exception as e:
                logger.warning(f"{stock_code} 判断买点失败: {str(e)}")
                return None
            
            # 5. 只保存符合买点条件的记录
            if not buy_point_result['is_buy_point']:
                logger.debug(
                    f"{stock_code} 不符合买点条件: "
                    f"价格差百分比={buy_point_result['price_diff_percent']}% "
                    f"区间=[{buy_point_result['buy_point_lower']}, {buy_point_result['buy_point_upper']}]"
                )
                return None
            
            # 6. 计算买入区间（当前价格±1%）
            buy_range_lower = round(current_price * 0.99, 2)
            buy_range_upper = round(current_price * 1.01, 2)
            buy_range = f"{buy_range_lower}-{buy_range_upper}"
            
            # 7. 组织结果
            result = {
                'stock_code': stock_code,
                'stock_name': record['stock_name'],
                'industry': record.get('industry'),
                'sector': record.get('sector'),
                'key_date': key_date,  # 关键日（形态实际形成日期）
                'hunting_date': hunting_date,  # 选入日期
                'strategy_name': strategy_name,
                'support_level': support_level,
                'current_price': current_price,
                'price_diff': buy_point_result['price_diff'],
                'price_diff_percent': buy_point_result['price_diff_percent'],
                'buy_range': buy_range,
                'score': record.get('score'),
                'score_date': record.get('selection_date'),  # 分数对应的日期
                'selection_record_id': record['id'],
                'timing_strategy': 'support',
                'timing_signal': buy_point_result.get('message', '价格在支撑位区间')
            }
            
            logger.info(
                f"{stock_code} 符合买点条件: "
                f"关键日={key_date} 选入日={hunting_date} "
                f"支撑位={support_level} 当前价={current_price} "
                f"价格差百分比={buy_point_result['price_diff_percent']}%"
            )
            return result
        
        except Exception as e:
            logger.error(f"计算和判断失败: {str(e)}")
            return None
    
    def _judge_by_timing_strategy(
        self,
        record: Dict,
        hunting_date: str,
        timing_strategy_name: str
    ) -> Optional[Dict]:
        """
        使用择时策略判断是否纳入狩猎范围
        
        参数：
            record: 选股记录
            hunting_date: 狩猎日期
            timing_strategy_name: 择时策略名称(turtle/rsi/bollinger)
        
        返回：
            Dict: 处理结果，如果不符合条件返回None
        """
        # record: 选股记录，类型Dict，必填
        # hunting_date: 狩猎日期，类型str，必填
        # timing_strategy_name: 择时策略名称，类型str，必填
        try:
            # 1. 获取股票代码
            stock_code = record['stock_code']
            strategy_name = record['strategy_name']
            
            # 2. 获取当前价格
            current_price = self._get_current_price(stock_code, hunting_date)
            if not current_price:
                logger.warning(f"{stock_code} 无法获取当前价格")
                return None
            
            # 3. 加载K线数据
            df_kline = self._load_kline_for_timing(stock_code, hunting_date)
            if df_kline is None or len(df_kline) < 20:
                logger.warning(f"{stock_code} K线数据不足，无法使用择时策略")
                return None
            
            # 4. 创建择时策略实例
            from trading.timing_strategies import TimingStrategyFactory
            strategy = TimingStrategyFactory.create_strategy(timing_strategy_name, {})
            
            # 5. 调用策略获取择时结果
            # 狩猎场模式：使用当天信号判断（use_prev_day_signal=False）
            timing_result = strategy.get_timing_result(df_kline, None, None, use_prev_day_signal=False)
            
            # 6. 判断是否发出买入信号
            if not timing_result.is_buy:
                logger.info(
                    f"{stock_code} {timing_strategy_name}策略未发出买入信号: "
                    f"{timing_result.message}"
                )
                return None
            
            # 6a. 海龟策略额外过滤：狩猎日收盘价超过关键日收盘价105%则舍弃
            # 避免选入已经涨太多的股票，保留距离关键日涨幅不大的首次买点机会
            key_date = self._extract_key_date(record) if timing_strategy_name == 'turtle' else None
            if timing_strategy_name == 'turtle' and key_date:
                key_date_close = self._get_key_date_close(stock_code, key_date)
                if key_date_close and current_price > key_date_close * 1.05:
                    price_ratio = round((current_price / key_date_close - 1) * 100, 2)
                    logger.info(
                        f"{stock_code} 海龟策略过滤: 狩猎日收盘价={current_price} "
                        f"关键日收盘价={key_date_close} 涨幅={price_ratio}% > 5%，舍弃"
                    )
                    return None
            
            # 7. 获取支撑位（如果有）
            support_level = timing_result.support_level if timing_result.support_level > 0 else current_price
            
            # 8. 计算价格差
            price_diff = current_price - support_level
            price_diff_percent = round(
                (price_diff / support_level) * 100, 2
            ) if support_level > 0 else 0
            
            # 9. 择时策略中文名称映射
            timing_strategy_display = {
                'turtle': '海龟策略',
                'rsi': 'RSI策略',
                'bollinger': '布林带策略',
                'support': '支撑位策略'
            }.get(timing_strategy_name, timing_strategy_name)
            
            # 10. 计算买入区间（当前价格±1%）
            buy_range_lower = round(current_price * 0.99, 2)
            buy_range_upper = round(current_price * 1.01, 2)
            buy_range = f"{buy_range_lower}-{buy_range_upper}"
            
            # 11. 组织结果
            result = {
                'stock_code': stock_code,
                'stock_name': record['stock_name'],
                'industry': record.get('industry'),
                'sector': record.get('sector'),
                'key_date': key_date,  # 关键日（形态实际形成日期）
                'hunting_date': hunting_date,  # 选入日期
                'strategy_name': strategy_name,
                'support_level': support_level,
                'current_price': current_price,
                'price_diff': price_diff,
                'price_diff_percent': price_diff_percent,
                'buy_range': buy_range,
                'score': record.get('score'),
                'score_date': record.get('selection_date'),
                'selection_record_id': record.get('id'),
                'timing_strategy': timing_strategy_name,
                'timing_signal': timing_result.message or f'{timing_strategy_display}发出买入信号'
            }
            
            logger.info(
                f"{stock_code} {timing_strategy_display}发出买入信号: "
                f"关键日={key_date or 'N/A'} 选入日={hunting_date} "
                f"当前价={current_price} 支撑位={support_level} "
                f"信号={timing_result.message}"
            )
            return result
        
        except Exception as e:
            logger.error(f"择时策略判断失败: {str(e)}")
            return None
    
    def _load_kline_for_timing(
        self,
        stock_code: str,
        hunting_date: str,
        days: int = 200
    ) -> Optional[pd.DataFrame]:
        """
        为择时策略加载K线数据
        
        参数：
            stock_code: 股票代码
            hunting_date: 狩猎日期
            days: 加载天数（默认200个自然日，约120个交易日）
        
        返回：
            DataFrame: K线数据（正序，日期从早到晚），如果数据不足返回None
        """
        # stock_code: 股票代码，类型str，必填
        # hunting_date: 狩猎日期，类型str，必填
        # days: 加载天数，类型int，默认200
        try:
            # 1. 计算起始日期
            start_date = self._calculate_date_before(hunting_date, days)
            
            # 2. 查询K线数据
            sql = """
            SELECT date, open, high, low, close, volume
            FROM stock_kline
            WHERE code = ? AND date BETWEEN ? AND ?
            ORDER BY date ASC
            """
            results = self.db_manager.query(sql, (stock_code, start_date, hunting_date))
            
            # 3. 检查数据是否足够
            if not results or len(results) < 10:
                logger.warning(f"{stock_code} K线数据不足: {len(results) if results else 0} 条")
                return None
            
            # 4. 转换为DataFrame
            df = pd.DataFrame(results, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            
            # 5. 确保数值类型
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            logger.debug(f"{stock_code} 加载K线数据: {len(df)} 条，{start_date} ~ {hunting_date}")
            return df
        
        except Exception as e:
            logger.error(f"加载K线数据失败: {stock_code} - {str(e)}")
            return None
    
    def _prepare_result(
        self,
        records: List[Dict]
    ) -> List[Dict]:
        """
        准备结果数据
        
        参数：
            records: 处理后的记录列表
        
        返回：
            List: 去重后按评分倒序排列的结果
        """
        # records: 处理后的记录列表，类型List[Dict]，必填
        try:
            # 1. 按 stock_code 分组，进行去重
            # 这样可以确保每只股票只显示一次，不管它被多少个策略选中
            stock_dict = {}
            for record in records:
                stock_code = record.get('stock_code')
                
                # 2. 如果该股票还没有记录，直接添加
                if stock_code not in stock_dict:
                    stock_dict[stock_code] = record
                else:
                    # 3. 如果该股票已有记录，比较分数
                    existing_record = stock_dict[stock_code]
                    existing_score = existing_record.get('score', 0)
                    new_score = record.get('score', 0)
                    
                    # 4. 分数较高的保留
                    if new_score > existing_score:
                        stock_dict[stock_code] = record
                    # 5. 分数相同时，保留最近日期的一条
                    elif new_score == existing_score:
                        existing_date = existing_record.get('hunting_date', '')
                        new_date = record.get('hunting_date', '')
                        if new_date > existing_date:
                            stock_dict[stock_code] = record
            
            # 6. 转换为列表
            deduped_records = list(stock_dict.values())
            
            # 7. 按评分倒序排列
            sorted_records = sorted(
                deduped_records,
                key=lambda x: x.get('score', 0),
                reverse=True
            )
            
            logger.info(f"准备结果数据: {len(records)} -> {len(sorted_records)} 条记录（去重后）")
            return sorted_records
        
        except Exception as e:
            logger.error(f"准备结果数据失败: {str(e)}")
            raise
    
    # ==================== 私有方法 - 数据获取 ====================
    
    def _get_current_price(
        self,
        stock_code: str,
        hunting_date: str
    ) -> Optional[float]:
        """
        获取当前价格
        
        参数：
            stock_code: 股票代码
            hunting_date: 狩猎日期
        
        返回：
            float: 当前价格（收盘价）
        """
        # stock_code: 股票代码，类型str，必填
        # hunting_date: 狩猎日期，类型str，必填
        try:
            # 1. 查询狩猎日的收盘价
            sql = """
            SELECT close FROM stock_kline
            WHERE code = ? AND date = ?
            """
            
            # 2. 执行查询
            result = self.db_manager.query_one(sql, (stock_code, hunting_date))
            
            # 3. 如果有数据，返回收盘价
            if result and result.get('close'):
                return float(result['close'])
            
            # 4. 如果没有数据，使用前一个交易日的收盘价
            sql = """
            SELECT close FROM stock_kline
            WHERE code = ? AND date < ?
            ORDER BY date DESC
            LIMIT 1
            """
            
            # 5. 执行查询
            result = self.db_manager.query_one(sql, (stock_code, hunting_date))
            
            # 6. 如果有数据，返回收盘价
            if result and result.get('close'):
                logger.debug(f"{stock_code} 使用前一个交易日的收盘价")
                return float(result['close'])
            
            # 7. 如果都没有数据，返回 None
            logger.warning(f"{stock_code} 无法获取当前价格")
            return None
        
        except Exception as e:
            logger.error(f"获取当前价格失败: {stock_code} - {str(e)}")
            return None
    
    def _get_key_date_close(
        self,
        stock_code: str,
        key_date: str
    ) -> Optional[float]:
        """
        获取关键日收盘价
        
        参数：
            stock_code: 股票代码
            key_date: 关键日期（YYYY-MM-DD）
        
        返回：
            float: 关键日收盘价，获取失败返回None
        """
        # stock_code: 股票代码，类型str，必填
        # key_date: 关键日期，类型str，必填
        try:
            # 1. 查询关键日的收盘价
            sql = """
            SELECT close FROM stock_kline
            WHERE code = ? AND date = ?
            """
            
            # 2. 执行查询
            result = self.db_manager.query_one(sql, (stock_code, key_date))
            
            # 3. 如果精确匹配到，返回收盘价
            if result and result.get('close'):
                return float(result['close'])
            
            # 4. 精确匹配失败，尝试查找最接近关键日的交易日
            sql = """
            SELECT close, date FROM stock_kline
            WHERE code = ? AND date <= ?
            ORDER BY date DESC
            LIMIT 1
            """
            
            # 5. 执行查询
            result = self.db_manager.query_one(sql, (stock_code, key_date))
            
            # 6. 如果找到最近的交易日，返回收盘价
            if result and result.get('close'):
                logger.debug(
                    f"{stock_code} 关键日{key_date}无K线数据，"
                    f"使用最近交易日{result['date']}的收盘价"
                )
                return float(result['close'])
            
            # 7. 均未找到，返回None
            logger.warning(f"{stock_code} 无法获取关键日{key_date}的收盘价")
            return None
        
        except Exception as e:
            logger.error(f"获取关键日收盘价失败: {stock_code} - {str(e)}")
            return None
    
    def _check_cache(self, hunting_date: str, timing_strategy: str = 'support') -> Optional[List[Dict]]:
        """
        检查缓存
        
        参数：
            hunting_date: 狩猎日期
            timing_strategy: 择时策略名称
        
        返回：
            List: 缓存的结果列表，如果没有缓存返回 None
        """
        # hunting_date: 狩猎日期，类型str，必填
        # timing_strategy: 择时策略名称，类型str，默认support
        try:
            # 1. 查询 KHunter 表中是否存在该狩猎日的记录
            # 注意：使用 score_date 作为选入日期显示
            # 根据择时策略过滤缓存数据
            sql = """
            SELECT stock_code, stock_name, industry, sector,
                   support_level, current_price, price_diff, price_diff_percent,
                   buy_range, strategy_name, score, score_date,
                   timing_strategy, timing_signal
            FROM khunter
            WHERE hunting_date = ? AND timing_strategy = ?
            ORDER BY score DESC
            """
            
            # 2. 执行查询
            results = self.db_manager.query(sql, (hunting_date, timing_strategy))
            
            # 3. 如果有缓存，返回结果
            if results:
                logger.debug(f"缓存命中: {hunting_date}，{timing_strategy}，{len(results)} 条记录")
                return results
            
            # 4. 如果没有缓存，返回 None
            logger.debug(f"缓存未命中: {hunting_date}，{timing_strategy}")
            return None
        
        except Exception as e:
            logger.warning(f"检查缓存失败: {str(e)}")
            return None
    
    # ==================== 私有方法 - 配置管理 ====================
    
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
    
    def _extract_key_date(self, record: Dict) -> Optional[str]:
        """
        从选股记录中提取关键日
        
        参数：
            record: 选股记录，包含key_dates字段
        
        返回：
            str: 关键日日期字符串（YYYY-MM-DD），如果提取失败返回None
        """
        # record: 选股记录，类型Dict，必填
        try:
            # 1. 获取key_dates字段
            key_dates_str = record.get('key_dates')
            if not key_dates_str:
                logger.warning(f"股票 {record.get('stock_code')} 的key_dates字段为空")
                return None
            
            # 2. 解析JSON
            key_dates = json.loads(key_dates_str)
            
            # 3. 检查是否为列表且有数据
            if not isinstance(key_dates, list) or len(key_dates) == 0:
                logger.warning(f"股票 {record.get('stock_code')} 的key_dates格式错误")
                return None
            
            # 4. 获取第一个关键日的日期
            # key_dates是一个列表，每个元素包含date、type、description字段
            key_date_info = key_dates[0]
            key_date = key_date_info.get('date')
            
            if not key_date:
                logger.warning(f"股票 {record.get('stock_code')} 的关键日日期为空")
                return None
            
            # 5. 处理日期格式（可能是datetime对象或字符串）
            if isinstance(key_date, str):
                # 如果是字符串，截取YYYY-MM-DD部分
                key_date = key_date[:10]
            else:
                logger.warning(f"股票 {record.get('stock_code')} 的关键日格式未知: {type(key_date)}")
                return None
            
            logger.debug(f"股票 {record.get('stock_code')} 的关键日: {key_date}")
            return key_date
        
        except json.JSONDecodeError as e:
            logger.error(f"股票 {record.get('stock_code')} 解析key_dates失败: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"股票 {record.get('stock_code')} 提取关键日失败: {str(e)}")
            return None
    
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
