"""
数据采集基础框架
使用策略模式和工厂模式，提供统一的采集接口和可扩展的数据源管理
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import requests
import pandas as pd

# 配置日志
logger = logging.getLogger(__name__)


class DataSource(ABC):
    """数据源基类 - 定义数据源接口"""
    
    def __init__(self, name: str, priority: int = 0):
        """
        初始化数据源
        
        参数：
            name: 数据源名称
            priority: 优先级（数字越小优先级越高）
        """
        self.name = name
        self.priority = priority
        self.timeout = 15  # 默认超时时间（秒）
    
    @abstractmethod
    def fetch(self, **kwargs) -> Optional[Any]:
        """
        从数据源获取数据
        
        返回：
            成功返回数据，失败返回 None
        """
        pass
    
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        return True


class CacheDataSource(DataSource):
    """缓存数据源 - 从缓存获取数据"""
    
    def __init__(self, cache_manager):
        """
        初始化缓存数据源
        
        参数：
            cache_manager: 缓存管理器实例
        """
        super().__init__("cache", priority=0)
        self.cache_manager = cache_manager
    
    def fetch(self, cache_key: str = None, **kwargs) -> Optional[Any]:
        """从缓存获取数据"""
        if not cache_key:
            return None
        try:
            data = self.cache_manager.get(cache_key)
            if data is not None:
                logger.debug(f"从缓存获取数据: {cache_key}")
                return data
        except Exception as e:
            logger.debug(f"缓存获取失败: {e}")
        return None


class HTTPDataSource(DataSource):
    """HTTP数据源基类 - 通过HTTP接口获取数据"""
    
    def __init__(self, name: str, base_url: str = "", priority: int = 1):
        """
        初始化HTTP数据源
        
        参数：
            name: 数据源名称
            base_url: 基础URL
            priority: 优先级
        """
        super().__init__(name, priority)
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    
    def _request(self, url: str, method: str = "GET", **kwargs) -> Optional[str]:
        """
        发送HTTP请求
        
        参数：
            url: 请求URL
            method: HTTP方法
            **kwargs: 其他请求参数
        
        返回：
            响应文本，失败返回 None
        """
        try:
            if method.upper() == "GET":
                resp = requests.get(url, timeout=self.timeout, headers=self.headers, **kwargs)
            else:
                resp = requests.post(url, timeout=self.timeout, headers=self.headers, **kwargs)
            
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            logger.debug(f"HTTP请求失败 ({self.name}): {e}")
        return None


class DataFetcher(ABC):
    """数据采集器基类 - 定义采集器接口"""
    
    def __init__(self, db_manager, cache_manager):
        """
        初始化采集器
        
        参数：
            db_manager: 数据库管理器
            cache_manager: 缓存管理器
        """
        self.db_manager = db_manager
        self.cache_manager = cache_manager
        self.data_sources: List[DataSource] = []
        self.max_retries = 3
        self.retry_delay = 1  # 秒
    
    def add_data_source(self, source: DataSource):
        """添加数据源"""
        self.data_sources.append(source)
        # 按优先级排序
        self.data_sources.sort(key=lambda x: x.priority)
    
    def fetch_with_retry(self, **kwargs) -> Optional[Any]:
        """
        带重试的数据获取
        
        使用指数退避策略重试，依次尝试所有数据源
        
        返回：
            成功返回数据，失败返回 None
        """
        for source in self.data_sources:
            if not source.is_available():
                logger.debug(f"数据源不可用: {source.name}")
                continue
            
            for attempt in range(self.max_retries):
                try:
                    logger.debug(f"尝试从 {source.name} 获取数据 (第{attempt+1}/{self.max_retries}次)")
                    data = source.fetch(**kwargs)
                    
                    if data is not None:
                        logger.info(f"成功从 {source.name} 获取数据")
                        return data
                
                except Exception as e:
                    logger.debug(f"获取失败: {e}")
                
                # 重试延迟（指数退避）
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    time.sleep(wait_time)
            
            logger.warning(f"数据源 {source.name} 获取失败，尝试下一个数据源")
        
        logger.error("所有数据源都获取失败")
        return None
    
    @abstractmethod
    def validate_data(self, data: Any) -> bool:
        """
        验证数据有效性
        
        参数：
            data: 待验证的数据
        
        返回：
            数据有效返回 True，否则返回 False
        """
        pass
    
    @abstractmethod
    def clean_data(self, data: Any) -> Any:
        """
        清洗数据
        
        参数：
            data: 待清洗的数据
        
        返回：
            清洗后的数据
        """
        pass
    
    @abstractmethod
    def save_data(self, data: Any) -> bool:
        """
        保存数据到数据库
        
        参数：
            data: 待保存的数据
        
        返回：
            保存成功返回 True，否则返回 False
        """
        pass
    
    def fetch_and_save(self, **kwargs) -> bool:
        """
        完整的采集流程：获取 → 验证 → 清洗 → 保存
        
        返回：
            成功返回 True，否则返回 False
        """
        # 1. 获取数据
        data = self.fetch_with_retry(**kwargs)
        if data is None:
            logger.error("数据获取失败")
            return False
        
        # 2. 验证数据
        if not self.validate_data(data):
            logger.error("数据验证失败")
            return False
        
        # 3. 清洗数据
        try:
            data = self.clean_data(data)
        except Exception as e:
            logger.error(f"数据清洗失败: {e}")
            return False
        
        # 4. 保存数据
        try:
            if self.save_data(data):
                logger.info("数据保存成功")
                return True
            else:
                logger.error("数据保存失败")
                return False
        except Exception as e:
            logger.error(f"数据保存异常: {e}")
            return False


class FetcherFactory:
    """采集器工厂 - 用于创建和管理采集器实例"""
    
    _fetchers: Dict[str, type] = {}
    
    @classmethod
    def register(cls, name: str, fetcher_class: type):
        """
        注册采集器类
        
        参数：
            name: 采集器名称
            fetcher_class: 采集器类
        """
        cls._fetchers[name] = fetcher_class
        logger.info(f"注册采集器: {name}")
    
    @classmethod
    def create(cls, name: str, db_manager, cache_manager) -> Optional[DataFetcher]:
        """
        创建采集器实例
        
        参数：
            name: 采集器名称
            db_manager: 数据库管理器
            cache_manager: 缓存管理器
        
        返回：
            采集器实例，不存在返回 None
        """
        if name not in cls._fetchers:
            logger.error(f"采集器不存在: {name}")
            return None
        
        fetcher_class = cls._fetchers[name]
        return fetcher_class(db_manager, cache_manager)
    
    @classmethod
    def list_fetchers(cls) -> List[str]:
        """获取所有已注册的采集器"""
        return list(cls._fetchers.keys())
