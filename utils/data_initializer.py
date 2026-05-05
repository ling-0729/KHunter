"""
数据初始化器 - 初始化各类数据（基础数据、K线、资金流向等）
"""
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

# 配置日志
logger = logging.getLogger(__name__)


class DataInitializer:
    """数据初始化器"""
    
    def __init__(self, db_manager, stock_data_fetcher, kline_fetcher, fund_flow_fetcher):
        """
        初始化数据初始化器
        
        参数：
            db_manager: 数据库管理器
            stock_data_fetcher: 股票数据采集器
            kline_fetcher: K线数据处理器
            fund_flow_fetcher: 资金流向数据采集器
        """
        self.db_manager = db_manager
        self.stock_data_fetcher = stock_data_fetcher
        self.kline_fetcher = kline_fetcher
        self.fund_flow_fetcher = fund_flow_fetcher
    
    # ==================== 基础数据初始化 ====================
    
    def _init_basic_data(self, stock_codes: list, stock_dict: dict = None) -> None:
        """
        初始化基础数据（包括股票基本信息和市值）
        
        参数：
            stock_codes: 股票代码列表
            stock_dict: 股票代码到名称的映射字典
        """
        logger.info("开始初始化基础数据...")
        success_count = 0
        failed_count = 0
        
        try:
            # 步骤1：获取股票名称（批量）
            logger.info("获取股票基本信息...")
            if stock_dict:
                all_stocks = stock_dict
                logger.info(f"使用传入的股票基本信息: {len(all_stocks)} 只股票")
            else:
                all_stocks = self.stock_data_fetcher.get_all_stock_codes()
                
                if not all_stocks:
                    logger.error("获取股票基本信息失败")
                    return
                
                logger.info(f"成功获取 {len(all_stocks)} 只股票的基本信息")
            
            # 步骤2：获取股票市值（批量）
            logger.info("从 Tushare 获取股票市值信息...")
            market_caps = self.stock_data_fetcher.get_stock_market_cap()
            
            if market_caps:
                logger.info(f"成功获取 {len(market_caps)} 只股票的市值信息")
            else:
                logger.warning("未获取到市值信息，将使用默认值 0")
            
            # 步骤3：批量保存到数据库
            with self.db_manager.transaction():
                logger.info("保存股票基本信息和市值到数据库...")
                
                for idx, code in enumerate(stock_codes, 1):
                    try:
                        # 从批量获取的数据中查找基本信息
                        name = all_stocks.get(code, '')
                        # 获取市值信息，如果没有则使用 0
                        market_cap = market_caps.get(code, 0)
                        
                        if name:
                            # 保存基本信息和市值到 stock_basic 表
                            insert_sql = """
                            INSERT OR REPLACE INTO stock_basic 
                            (code, name, market_cap)
                            VALUES (?, ?, ?)
                            """
                            self.db_manager.execute_with_retry(insert_sql, (code, name, market_cap))
                            success_count += 1
                        else:
                            failed_count += 1
                            logger.debug(f"股票 {code} 不在批量获取的数据中")
                        
                        # 定期输出进度（每100只股票输出一次）
                        if idx % 100 == 0:
                            logger.info(f"基础数据采集进度: {idx}/{len(stock_codes)}, 成功: {success_count}")
                    
                    except Exception as e:
                        failed_count += 1
                        logger.warning(f"处理 {code} 基础数据失败: {e}")
                
                logger.info(f"基础数据保存完成: 成功 {success_count} 只, 失败 {failed_count} 只")
        
        except Exception as e:
            logger.error(f"初始化基础数据失败: {e}")
    
    # ==================== K线数据初始化 ====================
    
    def _init_kline_history_data(self, stock_codes: list, years: int = 1) -> None:
        """
        初始化K线历史数据
        获取新增股票的历史K线数据
        
        参数：
            stock_codes: 股票代码列表
            years: 获取数据的年份数（默认 1 年）
        """
        logger.info(f"开始初始化K线历史数据: {len(stock_codes)} 只股票...")
        success_count = 0
        failed_count = 0
        
        try:
            total = len(stock_codes)
            
            for idx, code in enumerate(stock_codes, 1):
                try:
                    # 获取K线历史数据
                    df_kline = self.stock_data_fetcher.fetch_stock_history(code, years=years)
                    
                    if df_kline is not None and len(df_kline) > 0:
                        # 保存到数据库
                        with self.db_manager.transaction():
                            for _, row in df_kline.iterrows():
                                try:
                                    # 将日期转换为字符串格式
                                    date_str = str(row['date']).split(' ')[0] if hasattr(row['date'], '__str__') else str(row['date'])
                                    
                                    # 插入K线数据
                                    insert_sql = """
                                    INSERT OR REPLACE INTO stock_kline 
                                    (code, date, open, high, low, close, volume)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                    """
                                    self.db_manager.execute_with_retry(insert_sql, (
                                        code,
                                        date_str,
                                        float(row['open']),
                                        float(row['high']),
                                        float(row['low']),
                                        float(row['close']),
                                        int(row['volume'])
                                    ))
                                except Exception as e:
                                    logger.debug(f"保存 {code} K线数据失败: {e}")
                        
                        success_count += 1
                    else:
                        failed_count += 1
                        logger.debug(f"获取 {code} K线数据失败或无数据")
                    
                    # 定期输出进度（每100只股票输出一次）
                    if idx % 100 == 0:
                        logger.info(f"K线历史数据采集进度: {idx}/{total}, 成功: {success_count}")
                
                except Exception as e:
                    failed_count += 1
                    logger.debug(f"初始化 {code} K线历史数据失败: {e}")
            
            logger.info(f"K线历史数据初始化完成: 成功 {success_count} 只, 失败 {failed_count} 只")
        
        except Exception as e:
            logger.error(f"初始化K线历史数据失败: {e}")
    
    def _init_history_data(self, stock_codes: list) -> None:
        """
        初始化历史行情数据
        
        参数：
            stock_codes: 股票代码列表
        """
        logger.info("开始初始化历史行情数据...")
        # 调用 _init_kline_history_data 实现
        self._init_kline_history_data(stock_codes, years=1)
    
    # ==================== 行业和板块数据初始化 ====================
    
    def _init_industry_data(self, stock_codes: list) -> None:
        """
        初始化行业数据
        
        参数：
            stock_codes: 股票代码列表
        """
        logger.info("初始化行业数据...")
        # TODO: 实现行业数据初始化逻辑
        logger.info("行业数据初始化完成")
    
    def _init_sector_data(self, stock_codes: list) -> None:
        """
        初始化板块数据
        
        参数：
            stock_codes: 股票代码列表
        """
        logger.info("初始化板块数据...")
        # TODO: 实现板块数据初始化逻辑
        logger.info("板块数据初始化完成")
    
    # ==================== 资金流向数据初始化 ====================
    
    def _init_fund_flow_data(self, stock_codes: list, include_industry_sector: bool = True) -> dict:
        """
        初始化资金流向数据
        
        参数：
            stock_codes: 股票代码列表
            include_industry_sector: 是否包括行业和板块资金流向
        
        返回：
            初始化统计信息字典
        """
        logger.info("开始初始化资金流向数据...")
        stats = {
            'stock_moneyflow': 0,
            'industry_moneyflow': 0,
            'sector_moneyflow': 0
        }
        
        try:
            # TODO: 实现资金流向数据初始化逻辑
            logger.info("资金流向数据初始化完成")
        except Exception as e:
            logger.error(f"初始化资金流向数据失败: {e}")
        
        return stats
    
    # ==================== 事件数据初始化 ====================
    
    def _init_event_data(self, stock_codes: list) -> dict:
        """
        初始化事件数据（暂时不可用）
        Tushare anns_d 接口权限未开通，暂时跳过事件数据初始化
        
        参数：
            stock_codes: 股票代码列表
        
        返回：
            初始化统计信息字典
        """
        logger.info("事件数据初始化暂时跳过（Tushare 权限未开通）")
        return {'event_data': 0}
    
    # ==================== 全量和增量初始化 ====================
    
    def init_full_data(self, max_stocks: Optional[int] = None, skip_failed: bool = True, years: int = 1) -> None:
        """
        全量初始化所有数据
        
        参数：
            max_stocks: 最多初始化多少只股票（None 表示全部）
            skip_failed: 是否跳过失败的股票继续处理
            years: 获取K线数据的年份数
        """
        logger.info("开始全量初始化数据...")
        
        try:
            # 获取所有股票代码
            all_stocks = self.stock_data_fetcher.get_all_stock_codes()
            stock_codes = list(all_stocks.keys())
            
            # 限制股票数量
            if max_stocks:
                stock_codes = stock_codes[:max_stocks]
            
            logger.info(f"准备初始化 {len(stock_codes)} 只股票的数据...")
            
            # 1. 初始化基础数据
            self._init_basic_data(stock_codes)
            
            # 2. 初始化K线历史数据
            self._init_kline_history_data(stock_codes, years=years)
            
            # 3. 初始化行业数据
            self._init_industry_data(stock_codes)
            
            # 4. 初始化板块数据
            self._init_sector_data(stock_codes)
            
            # 5. 初始化资金流向数据
            self._init_fund_flow_data(stock_codes)
            
            # 6. 初始化事件数据
            self._init_event_data(stock_codes)
            
            logger.info("全量初始化完成")
        
        except Exception as e:
            logger.error(f"全量初始化失败: {e}")
    
    def init_incremental_data(self, max_stocks: Optional[int] = None, skip_failed: bool = True, years: int = 1) -> Dict[str, int]:
        """
        增量初始化数据（仅初始化新增股票）
        
        参数：
            max_stocks: 最多初始化多少只新股票（None 表示全部）
            skip_failed: 是否跳过失败的股票继续处理
            years: 获取K线数据的年份数
        
        返回：
            初始化统计信息字典
        """
        logger.info("开始增量初始化数据...")
        stats = {
            'new_stocks': 0,
            'initialized': 0,
            'failed': 0
        }
        
        try:
            # 获取所有股票代码
            all_stocks = self.stock_data_fetcher.get_all_stock_codes()
            stock_codes = list(all_stocks.keys())
            
            # 查询数据库中已有的股票
            sql = "SELECT DISTINCT code FROM stock_basic"
            existing_stocks = set()
            try:
                results = self.db_manager.query_all(sql)
                existing_stocks = {row['code'] for row in results}
            except:
                pass
            
            # 找出新增股票
            new_stocks = [code for code in stock_codes if code not in existing_stocks]
            
            if max_stocks:
                new_stocks = new_stocks[:max_stocks]
            
            logger.info(f"发现 {len(new_stocks)} 只新股票，准备初始化...")
            stats['new_stocks'] = len(new_stocks)
            
            # 初始化新股票的数据
            if new_stocks:
                self._init_basic_data(new_stocks)
                self._init_kline_history_data(new_stocks, years=years)
                stats['initialized'] = len(new_stocks)
            
            logger.info(f"增量初始化完成: 新股票 {len(new_stocks)} 只")
        
        except Exception as e:
            logger.error(f"增量初始化失败: {e}")
        
        return stats
    
    # ==================== 映射更新检查 ====================
    
    def _check_mapping_update_needed(self, mapping_type: str) -> bool:
        """
        检查映射是否需要更新
        
        参数：
            mapping_type: 映射类型 (industry, sector)
        
        返回：
            是否需要更新
        """
        logger.debug(f"检查 {mapping_type} 映射是否需要更新...")
        # TODO: 实现映射更新检查逻辑
        return False
    
    def _update_industry_data(self, stock_codes: list) -> None:
        """
        更新行业数据
        
        参数：
            stock_codes: 股票代码列表
        """
        logger.info("更新行业数据...")
        # TODO: 实现行业数据更新逻辑
        logger.info("行业数据更新完成")
    
    def _update_sector_data(self, stock_codes: list) -> None:
        """
        更新板块数据
        
        参数：
            stock_codes: 股票代码列表
        """
        logger.info("更新板块数据...")
        # TODO: 实现板块数据更新逻辑
        logger.info("板块数据更新完成")
