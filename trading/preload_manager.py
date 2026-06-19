from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

from utils.strategy_name_mapper import get_chinese_name, get_english_name

logger = logging.getLogger(__name__)


class PreloadManager:
    """
    预加载管理器 - 负责回测前的股票池预加载逻辑
    
    在回测开始前，预加载前N个交易日的可选股票作为初始股票池，
    确保回测第一天就能有可交易的股票。
    """
    
    def __init__(self, backtest_engine):
        """
        初始化预加载管理器
        
        Args:
            backtest_engine: 回测引擎实例，提供策略执行、评分和交易日历功能
        """
        self.backtest_engine = backtest_engine
        self.enabled = True
        self.preload_days = 5
        self.exclude_recent_days = 0
    
    def set_config(self, enabled: bool = True, preload_days: int = 5, exclude_recent_days: int = 0):
        """
        设置预加载配置
        
        Args:
            enabled: 是否启用预加载功能
            preload_days: 预加载的交易天数
            exclude_recent_days: 排除最近N天（避免使用未来数据）
        """
        self.enabled = enabled
        self.preload_days = max(1, preload_days)
        self.exclude_recent_days = max(0, exclude_recent_days)
        logger.info(f"预加载配置已更新: enabled={enabled}, preload_days={preload_days}, exclude_recent_days={exclude_recent_days}")
    
    def calculate_preload_dates(self, start_date: str) -> List[str]:
        """
        计算预加载日期范围
        
        根据回测开始日期，向前推算N个交易日（跳过节假日），
        生成从最早预加载日期到回测前一个交易日的日期列表。
        
        Args:
            start_date: 回测开始日期（格式：YYYY-MM-DD）
            
        Returns:
            预加载日期列表，按日期升序排列
        """
        if not self.backtest_engine._sorted_trading_dates:
            logger.warning("交易日历未加载，尝试从股票数据中提取...")
            
            # 尝试从已加载的股票数据中提取交易日历
            if self.backtest_engine.stock_filtered_cache:
                # 获取第一只股票的所有日期
                code, df = list(self.backtest_engine.stock_filtered_cache.items())[0]
                if 'date' in df.columns:
                    all_dates = df['date'].unique().tolist()
                    all_dates.sort()
                    self.backtest_engine._sorted_trading_dates = all_dates
                    logger.info(f"从股票 {code} 提取到 {len(all_dates)} 个交易日")
                else:
                    logger.warning("股票数据中没有 'date' 列，无法提取交易日历")
                    return []
            else:
                logger.warning("没有已加载的股票数据，无法提取交易日历")
                return []
        
        # 解析回测开始日期
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            logger.error(f"日期格式错误: {start_date}")
            return []
        
        # 找到回测开始日期在交易日历中的位置
        trading_dates = self.backtest_engine._sorted_trading_dates
        start_idx = -1
        
        for i, date_str in enumerate(trading_dates):
            if date_str >= start_date:
                start_idx = i
                break
        
        if start_idx == -1:
            logger.warning(f"回测开始日期 {start_date} 不在交易日历范围内，使用最后一个可用日期")
            if trading_dates:
                start_date = trading_dates[-1]
                start_idx = len(trading_dates) - 1
            else:
                return []
        
        # 计算预加载日期的起始位置
        # 需要获取回测开始日期前的 preload_days 个交易日
        preload_start_idx = max(0, start_idx - self.preload_days - self.exclude_recent_days)
        
        # 预加载日期范围：从预加载起始位置到回测开始日期的前一个交易日
        # 如果exclude_recent_days > 0，需要额外排除最近的天数
        end_idx = max(0, start_idx - self.exclude_recent_days - 1)
        
        if preload_start_idx > end_idx:
            logger.warning(f"预加载天数配置过大，调整为可用范围")
            preload_start_idx = end_idx
        
        # 提取预加载日期列表（按升序排列）
        preload_dates = trading_dates[preload_start_idx:end_idx + 1]
        
        logger.info(f"计算预加载日期范围: 从 {preload_dates[0] if preload_dates else '无'} 到 "
                    f"{preload_dates[-1] if preload_dates else '无'}，共 {len(preload_dates)} 个交易日")
        
        return preload_dates
    
    def execute_preload(self, strategy_name: str, start_date: str) -> List[Dict]:
        """
        执行预加载逻辑
        
        按日期顺序遍历预加载日期，执行选股策略并评分，将达标的股票加入初始股票池。
        
        Args:
            strategy_name: 选股策略名称（前端选择的策略）
            start_date: 回测开始日期
            
        Returns:
            预加载的股票列表，每个元素包含股票代码、名称、预加载日期、来源策略、评分等信息
        """
        if not self.enabled:
            logger.info("预加载功能已禁用")
            return []
        
        logger.info(f"开始执行预加载，策略: {strategy_name}，回测开始日期: {start_date}")
        
        # 1. 计算预加载日期范围
        preload_dates = self.calculate_preload_dates(start_date)
        if not preload_dates:
            logger.warning("没有预加载日期，跳过预加载")
            return []
        
        # 2. 按日期顺序执行选股和评分
        preloaded_stocks = []
        stock_code_set = set()  # 用于去重

        # 将英文策略名转为中文（用于评分器查找策略权重）
        chinese_strategy_name = get_chinese_name(strategy_name)

        for preload_date in preload_dates:
            logger.info(f"\n-------------------- 预加载日期: {preload_date} --------------------")

            try:
                # 执行选股策略
                selected_stocks = self._execute_strategy_on_date(strategy_name, preload_date)

                if selected_stocks:
                    logger.info(f"选股结果: {len(selected_stocks)} 只股票")

                    # 执行评分（使用中文策略名）
                    scored_stocks = self._score_stocks(selected_stocks, preload_date, chinese_strategy_name)

                    # 添加到预加载股票列表（去重）
                    for stock in scored_stocks:
                        stock_code = stock.get('stock_code', stock.get('code', ''))
                        if stock_code and stock_code not in stock_code_set:
                            stock_code_set.add(stock_code)
                            preloaded_stocks.append({
                                'stock_code': stock_code,
                                'stock_name': stock.get('stock_name', stock.get('name', '')),
                                'preload_date': preload_date,
                                'source_strategy': chinese_strategy_name,
                                'score': stock.get('score', 0),
                                'veto_flag': stock.get('veto_flag', False),
                                'reason': stock.get('reason', '')
                            })

                    logger.info(f"预加载进度: 已收集 {len(preloaded_stocks)} 只股票")
                else:
                    logger.info(f"选股结果: 无")

            except Exception as e:
                logger.error(f"预加载日期 {preload_date} 处理失败: {str(e)}")
                continue

        logger.info(f"\n预加载完成，共加载 {len(preloaded_stocks)} 只股票")
        
        return preloaded_stocks
    
    def _execute_strategy_on_date(self, strategy_name: str, date: str) -> List[Dict]:
        """
        在指定日期执行选股策略
        
        Args:
            strategy_name: 策略名称
            date: 执行日期
            
        Returns:
            选股结果列表
        """
        try:
            # 将中文策略名称转换为英文名称
            english_strategy_name = get_english_name(strategy_name)
            
            # 使用策略注册器获取策略
            strategy = self.backtest_engine.strategy_registry.get_strategy(english_strategy_name)
            if not strategy:
                logger.error(f"策略 {strategy_name}（英文：{english_strategy_name}）不存在")
                return []

            cache_size = len(self.backtest_engine.stock_filtered_cache)
            logger.debug(f"股票缓存大小: {cache_size} 只股票")
            
            # 遍历缓存中的有效股票，执行策略判断
            selected_stocks = []
            
            for code, df in self.backtest_engine.stock_filtered_cache.items():
                try:
                    # 日期切片：使用 'date' 列进行字符串比较
                    # stock_filtered_cache 中 date 列是字符串格式 'YYYY-MM-DD'
                    df_slice = df[df['date'] <= date].copy()
                    
                    if len(df_slice) < 20:  # 需要至少20天数据
                        logger.debug(f"股票 {code} 数据不足20天（{len(df_slice)}天），跳过")
                        continue
                    
                    # 反转数据为倒序（最新的在前），供策略使用
                    # 注意：read_stock默认返回倒序数据，截断后仍为倒序，无需反转
                    # 仅当数据为升序时才反转
                    if len(df_slice) > 1 and df_slice['date'].iloc[0] < df_slice['date'].iloc[-1]:
                        df_slice = df_slice.iloc[::-1].reset_index(drop=True)
                    
                    # 获取股票名称
                    stock_name = self.backtest_engine.stock_name_cache.get(code, "未知")
                    
                    # 使用与回测引擎一致的 execute_selection 方法
                    # selection_date 为预加载日期（每个日期单独执行选股）
                    signal_list = strategy.execute_selection(df_slice, code, stock_name, selection_date=date)
                    
                    # 处理选股结果
                    if signal_list:
                        for signal in signal_list:
                            selected_stocks.append({
                                'stock_code': code,
                                'stock_name': stock_name
                            })
                        logger.debug(f"股票 {code} ({stock_name}) 被策略选中")
                    else:
                        logger.debug(f"股票 {code} 未被策略选中")
                        
                except Exception as e:
                    logger.debug(f"股票 {code} 策略判断失败: {str(e)}")
                    continue
            
            logger.info(f"执行策略 {strategy_name} 完成，共选中 {len(selected_stocks)} 只股票")
            return selected_stocks
            
        except Exception as e:
            logger.error(f"执行策略 {strategy_name} 失败: {str(e)}")
            return []
    
    def _score_stocks(self, stocks: List[Dict], date: str, strategy_name: str) -> List[Dict]:
        """
        对选中的股票进行评分
        
        Args:
            stocks: 股票列表
            date: 评分日期
            strategy_name: 策略名称
            
        Returns:
            带评分的股票列表
        """
        try:
            if not stocks:
                return []
            
            # 使用回测评分器进行批量评分
            scored_stocks = self.backtest_engine.score_calculator.calculate_batch_scores(
                stocks=stocks,
                score_date=date,
                strategy_name=strategy_name
            )
            
            return scored_stocks
            
        except Exception as e:
            logger.error(f"股票评分失败: {str(e)}")
            # 返回原始股票列表（不带评分）
            for stock in stocks:
                stock['score'] = 0
                stock['reason'] = ''
            return stocks
    
    def merge_stocks(self, stock_lists: List[List[Dict]]) -> List[Dict]:
        """
        合并多个日期的选股结果并去重
        
        Args:
            stock_lists: 多日期选股结果列表
            
        Returns:
            去重后的股票列表
        """
        stock_code_set = set()
        merged_stocks = []
        
        for stock_list in stock_lists:
            for stock in stock_list:
                stock_code = stock.get('stock_code', stock.get('code', ''))
                if stock_code and stock_code not in stock_code_set:
                    stock_code_set.add(stock_code)
                    merged_stocks.append(stock)
        
        logger.info(f"合并去重完成: {len(merged_stocks)} 只股票")
        
        return merged_stocks
