"""数据采集器"""

from typing import Dict, List, Optional, Any
import logging
import json
from pathlib import Path
from utils.data_sources import (
    DataSource,
    TushareProDataSource,
    TencentDataSource,
    EastMoneyDataSource
)

class DataFetcher:
    """数据采集器"""
    
    def __init__(self):
        """初始化数据采集器"""
        self.logger = logging.getLogger("data_fetcher")
        self.data_sources = []
        self._load_data_sources()
        self.logger.info("数据采集器初始化成功")
    
    def _load_data_sources(self):
        """加载数据源"""
        try:
            # 加载数据源配置
            config_path = Path("config/data_sources.json")
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                enabled_sources = config.get("enabled", ["tushare_pro", "tencent", "eastmoney"])
            else:
                # 默认启用所有数据源
                enabled_sources = ["tushare_pro", "tencent", "eastmoney"]
            
            # 初始化数据源
            if "tushare_pro" in enabled_sources:
                try:
                    tushare_source = TushareProDataSource()
                    self.data_sources.append(tushare_source)
                    self.logger.info("Tushare Pro 数据源加载成功")
                except Exception as e:
                    self.logger.error(f"Tushare Pro 数据源初始化失败: {e}")
            
            if "tencent" in enabled_sources:
                try:
                    tencent_source = TencentDataSource()
                    self.data_sources.append(tencent_source)
                    self.logger.info("腾讯财经数据源加载成功")
                except Exception as e:
                    self.logger.error(f"腾讯财经数据源初始化失败: {e}")
            
            if "eastmoney" in enabled_sources:
                try:
                    eastmoney_source = EastMoneyDataSource()
                    self.data_sources.append(eastmoney_source)
                    self.logger.info("东方财富数据源加载成功")
                except Exception as e:
                    self.logger.error(f"东方财富数据源初始化失败: {e}")
            
            # 按优先级排序
            self.data_sources.sort(key=lambda x: x.priority)
            self.logger.info(f"共加载了 {len(self.data_sources)} 个数据源")
        except Exception as e:
            self.logger.error(f"加载数据源失败: {e}")
    
    def fetch_stock_basic(self) -> Optional[List[Dict]]:
        """获取股票基本信息"""
        return self._fetch_with_fallback("fetch_stock_basic")
    
    def fetch_industry_data(self) -> Optional[List[Dict]]:
        """获取行业数据"""
        return self._fetch_with_fallback("fetch_industry_data")
    
    def fetch_fund_flow(self, stock_code: str) -> Optional[Dict]:
        """获取资金流向"""
        return self._fetch_with_fallback("fetch_fund_flow", stock_code=stock_code)
    
    def fetch_stock_history(self, stock_code: str, years: int = 1) -> Optional[Any]:
        """获取历史行情"""
        return self._fetch_with_fallback("fetch_stock_history", stock_code=stock_code, years=years)
    
    def fetch_stock_events(self, stock_code: str) -> Optional[List[Dict]]:
        """获取事件信息"""
        return self._fetch_with_fallback("fetch_stock_events", stock_code=stock_code)
    
    def _fetch_with_fallback(self, method_name: str, **kwargs) -> Any:
        """带 fallback 的数据获取"""
        self.logger.info(f"执行 {method_name}，参数: {kwargs}")
        
        for source in self.data_sources:
            try:
                self.logger.info(f"尝试从 {source.name} 获取数据")
                method = getattr(source, method_name)
                result = method(**kwargs)
                
                if result is not None:
                    self.logger.info(f"从 {source.name} 成功获取数据")
                    return result
                else:
                    self.logger.warning(f"从 {source.name} 获取数据为空")
            except Exception as e:
                self.logger.warning(f"从 {source.name} 获取数据失败: {e}")
                continue
        
        self.logger.error(f"所有数据源都无法获取 {method_name} 数据")
        return None
    
    def get_available_sources(self) -> List[Dict]:
        """获取可用的数据源"""
        available = []
        for source in self.data_sources:
            is_available = source.is_available()
            available.append({
                "name": source.name,
                "priority": source.priority,
                "available": is_available
            })
        return available
    
    def update_data_sources(self):
        """更新数据源"""
        self.data_sources.clear()
        self._load_data_sources()
        self.logger.info("数据源已更新")
