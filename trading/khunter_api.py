#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KHunter API 模块
负责处理前端请求，调用业务逻辑层和数据访问层
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

# 配置日志
logger = logging.getLogger(__name__)


class KHunterAPI:
    """
    KHunter API 处理器
    负责处理前端请求，返回标准化响应
    """
    
    # 默认参数
    DEFAULT_TRACKING_DAYS = 10
    DEFAULT_PAGE = 1
    DEFAULT_PAGE_SIZE = 20
    
    # 参数范围
    MIN_TRACKING_DAYS = 1
    MAX_TRACKING_DAYS = 365
    MIN_PAGE = 1
    MAX_PAGE = 10000
    MIN_PAGE_SIZE = 1
    MAX_PAGE_SIZE = 100
    
    def __init__(self, db_manager, data_processor, dao):
        """
        初始化 API
        
        参数：
            db_manager: 数据库管理器
            data_processor: 数据处理器
            dao: DAO 对象
        """
        # db_manager: 数据库管理器，类型object，必填
        # data_processor: 数据处理器，类型object，必填
        # dao: DAO 对象，类型object，必填
        self.db_manager = db_manager
        self.data_processor = data_processor
        self.dao = dao
        logger.info("KHunter API 初始化完成")
    
    # ==================== 公开方法 ====================
    
    def calculate(
        self,
        hunting_date: str,
        tracking_days: int = DEFAULT_TRACKING_DAYS,
        timing_strategy: str = 'support'
    ) -> Dict[str, Any]:
        """
        计算狩猎场数据
        
        参数：
            hunting_date: 狩猎日期
            tracking_days: 跟踪天数
            timing_strategy: 择时策略名称，默认support
        
        返回：
            Dict: 标准化响应
        """
        # hunting_date: 狩猎日期，类型str，必填
        # tracking_days: 跟踪天数，类型int，默认10
        # timing_strategy: 择时策略名称，类型str，默认support
        try:
            # 1. 验证参数
            self._validate_date(hunting_date)
            self._validate_tracking_days(tracking_days)
            self._validate_timing_strategy(timing_strategy)
            
            # 2. 调用数据处理器
            logger.info(f"计算请求: {hunting_date} {tracking_days} timing_strategy={timing_strategy}")
            result = self.data_processor.process(hunting_date, tracking_days, timing_strategy)
            
            # 3. 返回成功响应
            logger.info(f"计算成功: {hunting_date} {len(result['results'])} 条记录")
            return self._build_success_response(result, "计算成功")
        
        except ValueError as e:
            # 4. 参数验证失败
            logger.warning(f"计算参数验证失败: {str(e)}")
            return self._build_error_response(str(e))
        
        except Exception as e:
            # 5. 计算失败
            logger.error(f"计算失败: {str(e)}")
            return self._build_error_response(f"计算失败：{str(e)}")
    
    def save(
        self,
        hunting_date: str,
        tracking_days: int = DEFAULT_TRACKING_DAYS,
        timing_strategy: str = 'support'
    ) -> Dict[str, Any]:
        """
        保存计算结果
        
        参数：
            hunting_date: 狩猎日期
            tracking_days: 跟踪天数
            timing_strategy: 择时策略名称，默认support
        
        返回：
            Dict: 标准化响应
        """
        # hunting_date: 狩猎日期，类型str，必填
        # tracking_days: 跟踪天数，类型int，默认10
        # timing_strategy: 择时策略名称，类型str，默认support
        try:
            # 1. 验证参数
            self._validate_date(hunting_date)
            self._validate_tracking_days(tracking_days)
            self._validate_timing_strategy(timing_strategy)
            
            # 2. 先计算数据
            logger.info(f"保存请求: {hunting_date} {tracking_days} timing_strategy={timing_strategy}")
            result = self.data_processor.process(hunting_date, tracking_days, timing_strategy)
            
            # 3. 保存结果到数据库
            saved_count = self.dao.save_batch_results(result['results'])
            
            # 4. 返回成功响应
            response_data = {
                'saved_count': saved_count,
                'hunting_date': hunting_date
            }
            
            logger.info(f"保存成功: {hunting_date} {saved_count} 条记录")
            return self._build_success_response(response_data, "保存成功")
        
        except ValueError as e:
            # 5. 参数验证失败
            logger.warning(f"保存参数验证失败: {str(e)}")
            return self._build_error_response(str(e))
        
        except Exception as e:
            # 6. 保存失败
            logger.error(f"保存失败: {str(e)}")
            return self._build_error_response(f"保存失败：{str(e)}")
    
    def query(
        self,
        hunting_date: str,
        timing_strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        查询狩猎场数据
        
        参数：
            hunting_date: 狩猎日期
            timing_strategy: 择时策略名称（可选）
        
        返回：
            Dict: 标准化响应
        """
        # hunting_date: 狩猎日期，类型str，必填
        # timing_strategy: 择时策略名称，类型str，可选
        try:
            # 1. 验证参数
            self._validate_date(hunting_date)
            
            # 2. 调用 DAO 查询
            strategy_info = f" 策略={timing_strategy}" if timing_strategy else ""
            logger.info(f"查询请求: {hunting_date}{strategy_info}")
            result = self.dao.query_by_date(hunting_date, timing_strategy)
            
            # 3. 返回成功响应
            logger.info(f"查询成功: {hunting_date}{strategy_info} 返回 {len(result['results'])} 条记录")
            return self._build_success_response(result, "查询成功")
        
        except ValueError as e:
            # 4. 参数验证失败
            logger.warning(f"查询参数验证失败: {str(e)}")
            return self._build_error_response(str(e))
        
        except Exception as e:
            # 5. 查询失败
            logger.error(f"查询失败: {str(e)}")
            return self._build_error_response(f"查询失败：{str(e)}")
    
    def check_cache(self, hunting_date: str, timing_strategy: Optional[str] = None) -> Dict[str, Any]:
        """
        检查缓存
        
        参数：
            hunting_date: 狩猎日期
            timing_strategy: 择时策略名称（可选）
        
        返回：
            Dict: 标准化响应
        """
        # hunting_date: 狩猎日期，类型str，必填
        # timing_strategy: 择时策略名称，类型str，可选
        try:
            # 1. 验证参数
            self._validate_date(hunting_date)
            
            # 2. 检查缓存
            strategy_info = f" 策略={timing_strategy}" if timing_strategy else ""
            logger.info(f"缓存检查请求: {hunting_date}{strategy_info}")
            has_cache = self.dao.check_cache(hunting_date, timing_strategy)
            
            # 3. 如果有缓存，获取记录数
            record_count = 0
            if has_cache:
                # 4. 查询记录数
                result = self.dao.query_by_date(hunting_date, timing_strategy)
                record_count = result['total_count']
            
            # 5. 返回成功响应
            response_data = {
                'has_cache': has_cache,
                'record_count': record_count,
                'hunting_date': hunting_date
            }
            
            logger.info(f"缓存检查完成: {hunting_date}{strategy_info} - {'命中' if has_cache else '未命中'}")
            return self._build_success_response(response_data, "检查成功")
        
        except ValueError as e:
            # 6. 参数验证失败
            logger.warning(f"缓存检查参数验证失败: {str(e)}")
            return self._build_error_response(str(e))
        
        except Exception as e:
            # 7. 检查失败
            logger.error(f"缓存检查失败: {str(e)}")
            return self._build_error_response(f"检查失败：{str(e)}")
    
    def query_by_code(
        self,
        hunting_date: str,
        stock_code: str
    ) -> Dict[str, Any]:
        """
        按日期和股票代码查询
        
        参数：
            hunting_date: 狩猎日期
            stock_code: 股票代码
        
        返回：
            Dict: 标准化响应
        """
        # hunting_date: 狩猎日期，类型str，必填
        # stock_code: 股票代码，类型str，必填
        try:
            # 1. 验证参数
            self._validate_date(hunting_date)
            if not stock_code or not isinstance(stock_code, str):
                raise ValueError("股票代码不能为空")
            
            # 2. 调用 DAO 查询
            logger.info(f"按代码查询请求: {hunting_date} {stock_code}")
            results = self.dao.query_by_date_and_code(hunting_date, stock_code)
            
            # 3. 返回成功响应
            logger.info(f"按代码查询成功: {hunting_date} {stock_code} 返回 {len(results)} 条记录")
            return self._build_success_response(results, "查询成功")
        
        except ValueError as e:
            # 4. 参数验证失败
            logger.warning(f"按代码查询参数验证失败: {str(e)}")
            return self._build_error_response(str(e))
        
        except Exception as e:
            # 5. 查询失败
            logger.error(f"按代码查询失败: {str(e)}")
            return self._build_error_response(f"查询失败：{str(e)}")
    
    def track(
        self,
        hunting_date: str
    ) -> Dict[str, Any]:
        """
        跟踪狩猎场数据 - 获取指定日期的全部数据
        按日期分组，计算当前价、收益率、最高价格、最高收益
        
        参数：
            hunting_date: 狩猎日期
        
        返回：
            Dict: 标准化响应
        """
        # hunting_date: 狩猎日期，类型str，必填
        try:
            # 1. 验证参数
            self._validate_date(hunting_date)
            
            # 2. 查询指定日期的数据
            logger.info(f"跟踪请求: {hunting_date}")
            result = self.dao.query_by_date(hunting_date)
            
            if not result['results']:
                logger.info(f"跟踪数据为空: {hunting_date}")
                return self._build_success_response([], "暂无数据")
            
            # 3. 导入必要的模块
            from utils.akshare_fetcher import AKShareFetcher
            from utils.ranking_manager import RankingManager
            
            akshare_fetcher = AKShareFetcher("data")
            ranking_manager = RankingManager()
            
            # 4. 处理全部跟踪数据
            tracking_data = []
            for idx, record in enumerate(result['results'], 1):
                # 从数据库中获取选入价（current_price字段是狩猎日的收盘价）
                selection_price = float(record.get('current_price', 0))
                stock_code = record.get('stock_code')
                
                # 获取当前价格（实时价格）
                current_price = 0.0
                try:
                    current_price = akshare_fetcher.get_stock_price(stock_code)
                    if current_price is None:
                        current_price = selection_price
                except Exception as e:
                    logger.warning(f"获取{stock_code}当前价格失败: {str(e)}")
                    current_price = selection_price
                
                # 计算当前收益率
                if selection_price > 0:
                    current_yield = ((current_price - selection_price) / selection_price) * 100
                else:
                    current_yield = 0
                
                # 获取选入后最高价格（使用ranking_manager的方法）
                highest_price = 0.0
                try:
                    highest_price = ranking_manager._get_highest_price(stock_code, hunting_date)
                    if highest_price is None or highest_price == 0:
                        highest_price = current_price
                except Exception as e:
                    logger.warning(f"获取{stock_code}最高价格失败: {str(e)}")
                    highest_price = current_price
                
                # 计算最高收益率
                if selection_price > 0:
                    highest_yield = ((highest_price - selection_price) / selection_price) * 100
                else:
                    highest_yield = 0
                
                tracking_data.append({
                    'rank_position': idx,
                    'stock_code': stock_code,
                    'stock_name': record.get('stock_name'),
                    'score': float(record.get('score', 0)),
                    'industry': record.get('industry'),
                    'sector': record.get('sector'),
                    'key_date': record.get('key_date'),  # 关键日（形态实际形成日期）
                    'selection_date': record.get('hunting_date'),  # 选入日期
                    'selection_price': selection_price,
                    'current_price': current_price,
                    'current_yield': round(current_yield, 2),
                    'highest_price': highest_price,
                    'highest_yield': round(highest_yield, 2)
                })
            
            # 5. 返回成功响应
            logger.info(f"跟踪成功: {hunting_date} 返回 {len(tracking_data)} 条记录")
            return self._build_success_response(tracking_data, "跟踪成功")
        
        except ValueError as e:
            # 6. 参数验证失败
            logger.warning(f"跟踪参数验证失败: {str(e)}")
            return self._build_error_response(str(e))
        
        except Exception as e:
            # 7. 跟踪失败
            logger.error(f"跟踪失败: {str(e)}")
            return self._build_error_response(f"跟踪失败：{str(e)}")

    def get_latest_kline_date(self) -> Dict[str, Any]:
        """
        获取最后一根K线日期
        
        返回：
            Dict: 标准化响应，包含最后一根K线日期
        """
        try:
            # 从 stock_kline 表获取最新日期
            sql = "SELECT MAX(date) as latest_date FROM stock_kline"
            result = self.db_manager.query_one(sql)
            latest_date = result.get('latest_date') if result else None
            
            if latest_date:
                logger.info(f"获取最后一根K线日期: {latest_date}")
                return self._build_success_response({'latest_date': latest_date}, "获取成功")
            else:
                logger.warning("stock_kline表中没有数据")
                return self._build_error_response("K线数据为空")
        
        except Exception as e:
            logger.error(f"获取最后一根K线日期失败: {str(e)}")
            return self._build_error_response(f"获取失败：{str(e)}")
    
    
    # ==================== 私有方法 - 参数验证 ====================
    
    # 合法的择时策略列表
    VALID_TIMING_STRATEGIES = ['support', 'turtle', 'rsi', 'bollinger', 'macd_bollinger']
    
    def _validate_timing_strategy(self, timing_strategy: str) -> None:
        """
        验证择时策略名称
        
        参数：
            timing_strategy: 择时策略名称
        
        异常：
            ValueError: 如果策略名称无效
        """
        # timing_strategy: 择时策略名称，类型str，必填
        try:
            # 1. 检查类型
            if not timing_strategy or not isinstance(timing_strategy, str):
                raise ValueError("择时策略名称不能为空")
            
            # 2. 检查是否为合法策略
            if timing_strategy not in self.VALID_TIMING_STRATEGIES:
                raise ValueError(
                    f"无效的择时策略: {timing_strategy}，"
                    f"可选值: {', '.join(self.VALID_TIMING_STRATEGIES)}"
                )
            
            logger.debug(f"择时策略验证成功: {timing_strategy}")
        
        except ValueError as e:
            raise
    
    def _validate_date(self, date_str: str) -> None:
        """
        验证日期
        
        参数：
            date_str: 日期字符串
        
        异常：
            ValueError: 如果日期无效
        """
        # date_str: 日期字符串，类型str，必填
        try:
            # 1. 检查日期格式
            if not date_str:
                raise ValueError("日期不能为空")
            
            # 2. 解析日期
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            
            # 3. 检查日期不能是未来日期
            if date_obj > datetime.now():
                raise ValueError("日期不能是未来日期")
            
            logger.debug(f"日期验证成功: {date_str}")
        
        except ValueError as e:
            if "time data" in str(e):
                raise ValueError("日期格式无效，请使用 YYYY-MM-DD 格式")
            raise
    
    def _validate_tracking_days(self, tracking_days: int) -> None:
        """
        验证跟踪天数
        
        参数：
            tracking_days: 跟踪天数
        
        异常：
            ValueError: 如果跟踪天数无效
        """
        # tracking_days: 跟踪天数，类型int，必填
        try:
            # 1. 检查类型
            if not isinstance(tracking_days, int):
                raise ValueError("跟踪天数必须是整数")
            
            # 2. 检查范围
            if tracking_days < self.MIN_TRACKING_DAYS or tracking_days > self.MAX_TRACKING_DAYS:
                raise ValueError(
                    f"跟踪天数必须在 {self.MIN_TRACKING_DAYS}-{self.MAX_TRACKING_DAYS} 之间"
                )
            
            logger.debug(f"跟踪天数验证成功: {tracking_days}")
        
        except ValueError as e:
            raise
    
    def _validate_page(self, page: int) -> None:
        """
        验证页码
        
        参数：
            page: 页码
        
        异常：
            ValueError: 如果页码无效
        """
        # page: 页码，类型int，必填
        try:
            # 1. 检查类型
            if not isinstance(page, int):
                raise ValueError("页码必须是整数")
            
            # 2. 检查范围
            if page < self.MIN_PAGE or page > self.MAX_PAGE:
                raise ValueError(
                    f"页码必须在 {self.MIN_PAGE}-{self.MAX_PAGE} 之间"
                )
            
            logger.debug(f"页码验证成功: {page}")
        
        except ValueError as e:
            raise
    
    def _validate_page_size(self, page_size: int) -> None:
        """
        验证每页记录数
        
        参数：
            page_size: 每页记录数
        
        异常：
            ValueError: 如果每页记录数无效
        """
        # page_size: 每页记录数，类型int，必填
        try:
            # 1. 检查类型
            if not isinstance(page_size, int):
                raise ValueError("每页记录数必须是整数")
            
            # 2. 检查范围
            if page_size < self.MIN_PAGE_SIZE or page_size > self.MAX_PAGE_SIZE:
                raise ValueError(
                    f"每页记录数必须在 {self.MIN_PAGE_SIZE}-{self.MAX_PAGE_SIZE} 之间"
                )
            
            logger.debug(f"每页记录数验证成功: {page_size}")
        
        except ValueError as e:
            raise
    
    # ==================== 私有方法 - 响应构建 ====================
    
    def _build_success_response(
        self,
        data: Any,
        message: str = "成功"
    ) -> Dict[str, Any]:
        """
        构建成功响应
        
        参数：
            data: 响应数据
            message: 响应消息
        
        返回：
            Dict: 标准化响应
        """
        # data: 响应数据，类型Any，必填
        # message: 响应消息，类型str，默认"成功"
        return {
            'success': True,
            'message': message,
            'data': data
        }
    
    def _build_error_response(self, message: str = "失败") -> Dict[str, Any]:
        """
        构建错误响应
        
        参数：
            message: 错误消息
        
        返回：
            Dict: 标准化响应
        """
        # message: 错误消息，类型str，默认"失败"
        return {
            'success': False,
            'message': message,
            'data': None
        }
