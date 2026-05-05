"""
A股数据采集协调器 - 统一管理所有数据采集
使用模块化设计，将不同功能分解到独立的模块中
"""
import logging
from pathlib import Path
from typing import Optional, Dict

# 导入各个模块
from utils.stock_data_fetcher import StockDataFetcher
from utils.kline_fetcher import KlineFetcher
from utils.fund_flow_fetcher import FundFlowFetcher
from utils.data_initializer import DataInitializer
from utils.collector_manager import CollectorManager
from utils.db_manager import DBManager

# 配置日志
logger = logging.getLogger(__name__)


class AKShareFetcher:
    """A股数据采集协调器 - 统一管理所有数据采集"""
    
    def __init__(self, data_dir="data"):
        """
        初始化采集协调器
        
        参数：
            data_dir: 数据目录路径
        """
        # 初始化数据库管理器
        from utils.global_db import get_global_db
        self.db_manager = get_global_db()
        self.data_dir = Path(data_dir)
        
        # 初始化各个模块
        self.stock_data_fetcher = StockDataFetcher(data_dir)
        self.kline_fetcher = KlineFetcher(self.db_manager, self.stock_data_fetcher)
        self.fund_flow_fetcher = FundFlowFetcher(self.db_manager)
        self.data_initializer = DataInitializer(
            self.db_manager,
            self.stock_data_fetcher,
            self.kline_fetcher,
            self.fund_flow_fetcher
        )
        self.collector_manager = CollectorManager(self.db_manager)
        
        logger.info("AKShareFetcher 初始化完成")
    
    # ==================== 股票列表管理 ====================
    
    def get_all_stock_codes(self, max_retries=3) -> dict:
        """
        获取所有A股股票代码（过滤债基、ETF、ST等）
        
        参数：
            max_retries: 最大重试次数
        
        返回：
            股票代码到名称的映射字典
        """
        return self.stock_data_fetcher.get_all_stock_codes(max_retries)
    
    # ==================== 实时数据获取 ====================
    
    def get_stock_price(self, stock_code: str) -> Optional[float]:
        """
        获取股票实时价格
        
        参数：
            stock_code: 股票代码
        
        返回：
            实时价格，获取失败返回 None
        """
        return self.stock_data_fetcher.get_stock_price(stock_code)
    
    def get_stock_prices_batch(self, stock_codes: list) -> dict:
        """
        批量获取股票实时价格
        
        参数：
            stock_codes: 股票代码列表
        
        返回：
            {stock_code: price} 字典
        """
        return self.stock_data_fetcher.get_stock_prices_batch(stock_codes)
    
    # ==================== 历史数据获取 ====================
    
    def fetch_stock_history(self, stock_code: str, years: int = 6) -> dict:
        """
        抓取单只股票历史数据
        
        参数：
            stock_code: 股票代码
            years: 获取数据的年份数
        
        返回：
            历史数据DataFrame
        """
        return self.stock_data_fetcher.fetch_stock_history(stock_code, years)
    
    def fetch_stock_update(self, stock_code: str, days: int = 10) -> Optional[dict]:
        """
        抓取近期数据用于增量更新
        
        参数：
            stock_code: 股票代码
            days: 获取最近多少天的数据
        
        返回：
            增量数据DataFrame
        """
        return self.stock_data_fetcher.fetch_stock_update(stock_code, days)
    
    # ==================== K线数据处理 ====================
    
    def _fetch_kline_batch(self, stock_codes: list, days: int = 30, use_concurrent: bool = False, max_workers: int = 5) -> dict:
        """
        批量获取K线数据
        
        参数：
            stock_codes: 股票代码列表
            days: 获取最近多少天的数据
            use_concurrent: 是否使用并发获取
            max_workers: 并发线程数
        
        返回：
            {stock_code: DataFrame, ...}
        """
        return self.kline_fetcher._fetch_kline_batch(stock_codes, days, use_concurrent, max_workers)
    
    def _batch_update_kline_to_db(self, kline_data: dict) -> tuple:
        """
        批量更新K线数据到数据库
        
        参数：
            kline_data: {stock_code: DataFrame, ...}
        
        返回：
            (updated_count, failed_count)
        """
        return self.kline_fetcher._batch_update_kline_to_db(kline_data)
    
    def _get_latest_kline_date(self, stock_code: str) -> Optional[str]:
        """
        获取某只股票的最新K线日期
        
        参数：
            stock_code: 股票代码
        
        返回：
            最新K线日期（格式: YYYY-MM-DD）
        """
        return self.kline_fetcher._get_latest_kline_date(stock_code)
    
    def _calculate_days_to_fetch(self, stock_code: str) -> int:
        """
        计算某只股票需要获取的天数
        
        参数：
            stock_code: 股票代码
        
        返回：
            需要获取的天数
        """
        return self.kline_fetcher._calculate_days_to_fetch(stock_code)
    
    # ==================== 资金流向数据处理 ====================
    
    def _fetch_daily_stock_moneyflow(self, start_date: str, end_date: str, pro, stock_codes: Optional[list] = None) -> Optional[dict]:
        """
        逐日采集个股资金流向数据
        
        参数：
            start_date: 开始日期，格式 YYYYMMDD
            end_date: 结束日期，格式 YYYYMMDD
            pro: Tushare API 实例
            stock_codes: 股票代码列表（可选）
        
        返回：
            合并后的个股资金流向数据 DataFrame
        """
        return self.fund_flow_fetcher._fetch_daily_stock_moneyflow(start_date, end_date, pro, stock_codes)
    
    def _fetch_daily_industry_moneyflow(self, start_date: str, end_date: str, pro) -> Optional[dict]:
        """
        逐日采集行业资金流向数据
        
        参数：
            start_date: 开始日期，格式 YYYYMMDD
            end_date: 结束日期，格式 YYYYMMDD
            pro: Tushare API 实例
        
        返回：
            合并后的行业资金流向数据 DataFrame
        """
        return self.fund_flow_fetcher._fetch_daily_industry_moneyflow(start_date, end_date, pro)
    
    def _fetch_daily_sector_moneyflow(self, start_date: str, end_date: str, pro) -> Optional[dict]:
        """
        逐日采集板块资金流向数据
        
        参数：
            start_date: 开始日期，格式 YYYYMMDD
            end_date: 结束日期，格式 YYYYMMDD
            pro: Tushare API 实例
        
        返回：
            合并后的板块资金流向数据 DataFrame
        """
        return self.fund_flow_fetcher._fetch_daily_sector_moneyflow(start_date, end_date, pro)
    
    def _fetch_industry_fund_flow(self, trade_date: str) -> Optional[dict]:
        """
        获取行业资金流向数据
        
        参数：
            trade_date: 交易日期，格式 YYYYMMDD
        
        返回：
            包含行业资金流向数据的 DataFrame
        """
        return self.fund_flow_fetcher._fetch_industry_fund_flow(trade_date)
    
    def _save_industry_fund_flow(self, df_flow: dict, end_date: str) -> int:
        """
        保存行业资金流向数据到数据库
        
        参数：
            df_flow: 行业资金流向数据 DataFrame
            end_date: 结束日期，格式 YYYYMMDD
        
        返回：
            保存成功的记录数
        """
        return self.fund_flow_fetcher._save_industry_fund_flow(df_flow, end_date)
    
    def _fetch_sector_fund_flow(self, trade_date: str) -> Optional[dict]:
        """
        获取板块资金流向数据
        
        参数：
            trade_date: 交易日期，格式 YYYYMMDD
        
        返回：
            包含板块资金流向数据的 DataFrame
        """
        return self.fund_flow_fetcher._fetch_sector_fund_flow(trade_date)
    
    def _save_sector_fund_flow(self, df_flow: dict, end_date: str) -> int:
        """
        保存板块资金流向数据到数据库
        
        参数：
            df_flow: 板块资金流向数据 DataFrame
            end_date: 结束日期，格式 YYYYMMDD
        
        返回：
            保存成功的记录数
        """
        return self.fund_flow_fetcher._save_sector_fund_flow(df_flow, end_date)
    
    # ==================== 数据初始化 ====================
    
    def _init_basic_data(self, stock_codes: list, stock_dict: dict = None) -> None:
        """初始化基础数据"""
        self.data_initializer._init_basic_data(stock_codes, stock_dict)
    
    def _init_kline_history_data(self, stock_codes: list, years: int = 1) -> None:
        """初始化K线历史数据"""
        self.data_initializer._init_kline_history_data(stock_codes, years)
    
    def _init_history_data(self, stock_codes: list) -> None:
        """初始化历史行情数据"""
        self.data_initializer._init_history_data(stock_codes)
    
    def _init_industry_data(self, stock_codes: list) -> None:
        """初始化行业数据"""
        self.data_initializer._init_industry_data(stock_codes)
    
    def _init_sector_data(self, stock_codes: list) -> None:
        """初始化板块数据"""
        self.data_initializer._init_sector_data(stock_codes)
    
    def _init_fund_flow_data(self, stock_codes: list, include_industry_sector: bool = True) -> dict:
        """初始化资金流向数据"""
        return self.data_initializer._init_fund_flow_data(stock_codes, include_industry_sector)
    
    def _init_event_data(self, stock_codes: list) -> dict:
        """初始化事件数据"""
        return self.data_initializer._init_event_data(stock_codes)
    
    def init_full_data(self, max_stocks: Optional[int] = None, skip_failed: bool = True, years: int = 1) -> None:
        """全量初始化所有数据"""
        self.data_initializer.init_full_data(max_stocks, skip_failed, years)
    
    def init_incremental_data(self, max_stocks: Optional[int] = None, skip_failed: bool = True, years: int = 1) -> Dict[str, int]:
        """增量初始化数据"""
        return self.data_initializer.init_incremental_data(max_stocks, skip_failed, years)
    
    # ==================== 采集器管理 ====================
    
    def _init_collectors(self) -> None:
        """初始化所有采集器"""
        self.collector_manager._init_collectors()
    
    def _get_collector(self, collector_type: str):
        """获取指定类型的采集器"""
        return self.collector_manager._get_collector(collector_type)
