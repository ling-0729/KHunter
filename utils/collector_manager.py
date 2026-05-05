"""
采集器管理器 - 管理各类数据采集器的初始化和获取
"""
import logging
from utils.base_fetcher import FetcherFactory
from utils.cache_manager import CacheManager

# 配置日志
logger = logging.getLogger(__name__)


class CollectorManager:
    """采集器管理器"""
    
    def __init__(self, db_manager):
        """
        初始化采集器管理器
        
        参数：
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.cache_manager = None
        self.collectors = {}
    
    def _init_collectors(self) -> None:
        """
        初始化所有采集器
        使用 FetcherFactory 创建采集器实例
        """
        try:
            # 初始化缓存（如果还未初始化）
            if not self.cache_manager:
                self.cache_manager = CacheManager()
                logger.info("缓存管理器初始化完成")
            
            # 使用 FetcherFactory 创建采集器
            self.collectors = {
                'basic': FetcherFactory.create('basic', self.db_manager, self.cache_manager),
                'industry': FetcherFactory.create('industry', self.db_manager, self.cache_manager),
                'sector': FetcherFactory.create('sector', self.db_manager, self.cache_manager),
                'fund_flow': FetcherFactory.create('fund_flow', self.db_manager, self.cache_manager),
                'event': FetcherFactory.create('event', self.db_manager, self.cache_manager),
            }
            
            logger.info(f"采集器初始化完成: {list(self.collectors.keys())}")
        
        except Exception as e:
            logger.error(f"采集器初始化失败: {e}")
            raise
    
    def _get_collector(self, collector_type: str):
        """
        获取指定类型的采集器
        
        参数：
            collector_type: 采集器类型 (basic, industry, sector, fund_flow, event)
        
        返回：
            采集器实例
        """
        if not self.collectors:
            self._init_collectors()
        
        if collector_type not in self.collectors:
            raise ValueError(f"未知的采集器类型: {collector_type}")
        
        return self.collectors[collector_type]
