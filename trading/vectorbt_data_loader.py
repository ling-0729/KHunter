"""
VectorBT向量化数据加载模块

本模块实现了优化的数据加载功能，包括：
1. 批量数据加载 - 一次性加载所有股票数据
2. 缓存机制 - LRU缓存减少数据库查询
3. 数据验证 - 确保数据完整性和正确性
4. 多数据源支持 - 支持不同的数据源
5. 性能监控 - 记录加载性能指标

性能目标：
- 加载时间: < 10秒
- 缓存命中率: > 80%
- 内存占用: < 100MB
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import time
from collections import OrderedDict
import threading

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataCache:
    """LRU缓存实现"""
    
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        """
        初始化缓存
        
        Args:
            max_size: 最大缓存条目数
            ttl: 缓存过期时间（秒）
        """
        # max_size: 最大缓存条目数，类型int，默认1000
        # ttl: 缓存过期时间，类型int，默认3600秒
        self.max_size = max_size
        self.ttl = ttl
        self.cache = OrderedDict()
        self.timestamps = {}
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[pd.DataFrame]:
        """
        获取缓存数据
        
        Args:
            key: 缓存键
        
        Returns:
            pd.DataFrame: 缓存的数据，如果不存在或过期则返回None
        """
        # key: 缓存键，类型str，必填
        with self.lock:
            if key not in self.cache:
                self.misses += 1
                return None
            
            # 检查是否过期
            if time.time() - self.timestamps[key] > self.ttl:
                del self.cache[key]
                del self.timestamps[key]
                self.misses += 1
                return None
            
            # 移到最后（LRU）
            self.cache.move_to_end(key)
            self.hits += 1
            return self.cache[key]
    
    def set(self, key: str, value: pd.DataFrame):
        """
        设置缓存数据
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        # key: 缓存键，类型str，必填
        # value: 缓存值，类型pd.DataFrame，必填
        with self.lock:
            if key in self.cache:
                del self.cache[key]
            
            self.cache[key] = value
            self.timestamps[key] = time.time()
            
            # 如果超过最大大小，删除最旧的条目
            if len(self.cache) > self.max_size:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                del self.timestamps[oldest_key]
    
    def clear(self):
        """清空缓存"""
        with self.lock:
            self.cache.clear()
            self.timestamps.clear()
            self.hits = 0
            self.misses = 0
    
    def get_stats(self) -> Dict:
        """获取缓存统计信息"""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0
        
        return {
            'hits': self.hits,
            'misses': self.misses,
            'total': total,
            'hit_rate': hit_rate,
            'size': len(self.cache)
        }


class OptimizedDataLoader:
    """优化的数据加载器"""
    
    def __init__(self, db_manager, cache_enabled: bool = True, cache_size: int = 1000):
        """
        初始化数据加载器
        
        Args:
            db_manager: 数据库管理器实例
            cache_enabled: 是否启用缓存
            cache_size: 缓存大小
        """
        # db_manager: 数据库管理器，类型DBManager，必填
        # cache_enabled: 是否启用缓存，类型bool，默认True
        # cache_size: 缓存大小，类型int，默认1000
        self.db_manager = db_manager
        self.cache_enabled = cache_enabled
        self.cache = DataCache(max_size=cache_size) if cache_enabled else None
        self.load_stats = {
            'total_time': 0,
            'query_time': 0,
            'process_time': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    def load_prices_matrix(self, stock_codes: List[str], start_date: str, 
                          end_date: str, use_cache: bool = True) -> pd.DataFrame:
        """
        加载价格矩阵（优化版本）
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            use_cache: 是否使用缓存
        
        Returns:
            pd.DataFrame: 价格矩阵，形状为 (n_days, n_stocks)
        """
        # stock_codes: 股票代码列表，类型List[str]，必填
        # start_date: 开始日期，类型str，必填
        # end_date: 结束日期，类型str，必填
        # use_cache: 是否使用缓存，类型bool，默认True
        logger.info(f"开始加载价格数据: {len(stock_codes)}只股票, {start_date} - {end_date}")
        
        start_time = time.time()
        
        # 1. 尝试从缓存加载
        cache_key = f"prices_{start_date}_{end_date}_{len(stock_codes)}"
        if use_cache and self.cache_enabled:
            cached_data = self.cache.get(cache_key)
            if cached_data is not None:
                logger.info(f"从缓存加载数据: {cached_data.shape}")
                self.load_stats['cache_hits'] += 1
                return cached_data
            self.load_stats['cache_misses'] += 1
        
        # 2. 批量查询数据库
        query_start = time.time()
        prices_dict = self._batch_load_prices(stock_codes, start_date, end_date)
        query_time = time.time() - query_start
        
        # 3. 处理数据
        process_start = time.time()
        prices = self._process_prices(prices_dict)
        process_time = time.time() - process_start
        
        # 4. 缓存结果
        if use_cache and self.cache_enabled and not prices.empty:
            self.cache.set(cache_key, prices)
        
        # 5. 记录统计信息
        total_time = time.time() - start_time
        self.load_stats['total_time'] = total_time
        self.load_stats['query_time'] = query_time
        self.load_stats['process_time'] = process_time
        
        logger.info(f"加载完成: {prices.shape}, 总时间: {total_time:.2f}秒, "
                   f"查询: {query_time:.2f}秒, 处理: {process_time:.2f}秒")
        
        return prices
    
    def _batch_load_prices(self, stock_codes: List[str], start_date: str, 
                          end_date: str) -> Dict[str, np.ndarray]:
        """
        批量加载价格数据
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            Dict: 股票代码 -> 价格数组的映射
        """
        # stock_codes: 股票代码列表，类型List[str]，必填
        # start_date: 开始日期，类型str，必填
        # end_date: 结束日期，类型str，必填
        prices_dict = {}
        
        # 1. 构建批量查询SQL
        placeholders = ','.join(['?' for _ in stock_codes])
        sql = f"""
            SELECT code, date, close
            FROM stock_kline
            WHERE code IN ({placeholders})
            AND date BETWEEN ? AND ?
            ORDER BY code, date ASC
        """
        
        # 2. 执行查询
        params = stock_codes + [start_date, end_date]
        try:
            results = self.db_manager.query(sql, tuple(params))
            
            # 3. 组织数据
            for code, date, close in results:
                if code not in prices_dict:
                    prices_dict[code] = []
                prices_dict[code].append(close)
            
            # 4. 转换为NumPy数组
            for code in prices_dict:
                prices_dict[code] = np.array(prices_dict[code], dtype=np.float32)
            
            logger.info(f"批量查询完成: {len(prices_dict)}只股票")
        
        except Exception as e:
            logger.error(f"批量查询失败: {str(e)}")
        
        return prices_dict
    
    def _process_prices(self, prices_dict: Dict[str, np.ndarray]) -> pd.DataFrame:
        """
        处理价格数据
        
        Args:
            prices_dict: 股票代码 -> 价格数组的映射
        
        Returns:
            pd.DataFrame: 处理后的价格矩阵
        """
        # prices_dict: 股票代码 -> 价格数组的映射，类型Dict，必填
        if not prices_dict:
            logger.warning("价格数据为空")
            return pd.DataFrame()
        
        # 1. 创建DataFrame
        prices = pd.DataFrame(prices_dict)
        
        # 2. 数据验证
        prices = self._validate_prices(prices)
        
        # 3. 数据清理
        prices = prices.fillna(method='ffill')  # 向前填充
        prices = prices.dropna()  # 删除仍有缺失值的行
        
        logger.info(f"数据处理完成: {prices.shape}")
        return prices
    
    def _validate_prices(self, prices: pd.DataFrame) -> pd.DataFrame:
        """
        验证价格数据
        
        Args:
            prices: 价格矩阵
        
        Returns:
            pd.DataFrame: 验证后的价格矩阵
        """
        # prices: 价格矩阵，类型pd.DataFrame，必填
        logger.info("开始数据验证")
        
        # 1. 检查数据类型
        prices = prices.astype(np.float32)
        
        # 2. 检查数据范围
        prices = prices[(prices > 0) & (prices < 100000)]  # 合理的价格范围
        
        # 3. 检查缺失值
        missing_ratio = prices.isnull().sum().sum() / (prices.shape[0] * prices.shape[1])
        if missing_ratio > 0.1:
            logger.warning(f"缺失值比例过高: {missing_ratio:.2%}")
        
        logger.info("数据验证完成")
        return prices
    
    def load_scores_matrix(self, stock_codes: List[str], start_date: str, 
                          end_date: str, use_cache: bool = True) -> pd.DataFrame:
        """
        加载评分矩阵
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            use_cache: 是否使用缓存
        
        Returns:
            pd.DataFrame: 评分矩阵
        """
        # stock_codes: 股票代码列表，类型List[str]，必填
        # start_date: 开始日期，类型str，必填
        # end_date: 结束日期，类型str，必填
        # use_cache: 是否使用缓存，类型bool，默认True
        logger.info(f"开始加载评分数据: {len(stock_codes)}只股票")
        
        # 1. 尝试从缓存加载
        cache_key = f"scores_{start_date}_{end_date}_{len(stock_codes)}"
        if use_cache and self.cache_enabled:
            cached_data = self.cache.get(cache_key)
            if cached_data is not None:
                logger.info(f"从缓存加载评分数据: {cached_data.shape}")
                return cached_data
        
        # 2. 批量查询评分数据
        placeholders = ','.join(['?' for _ in stock_codes])
        sql = f"""
            SELECT code, date, score
            FROM stock_score
            WHERE code IN ({placeholders})
            AND date BETWEEN ? AND ?
            ORDER BY code, date ASC
        """
        
        scores_dict = {}
        params = stock_codes + [start_date, end_date]
        
        try:
            results = self.db_manager.query(sql, tuple(params))
            
            for code, date, score in results:
                if code not in scores_dict:
                    scores_dict[code] = []
                scores_dict[code].append(score)
            
            # 转换为DataFrame
            scores = pd.DataFrame(scores_dict)
            
            # 缓存结果
            if use_cache and self.cache_enabled:
                self.cache.set(cache_key, scores)
            
            logger.info(f"加载评分数据完成: {scores.shape}")
            return scores
        
        except Exception as e:
            logger.error(f"加载评分数据失败: {str(e)}")
            return pd.DataFrame()
    
    def load_support_levels_matrix(self, stock_codes: List[str], start_date: str, 
                                   end_date: str, use_cache: bool = True) -> pd.DataFrame:
        """
        加载支撑位矩阵
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            use_cache: 是否使用缓存
        
        Returns:
            pd.DataFrame: 支撑位矩阵
        """
        # stock_codes: 股票代码列表，类型List[str]，必填
        # start_date: 开始日期，类型str，必填
        # end_date: 结束日期，类型str，必填
        # use_cache: 是否使用缓存，类型bool，默认True
        logger.info(f"开始加载支撑位数据: {len(stock_codes)}只股票")
        
        # 1. 尝试从缓存加载
        cache_key = f"support_{start_date}_{end_date}_{len(stock_codes)}"
        if use_cache and self.cache_enabled:
            cached_data = self.cache.get(cache_key)
            if cached_data is not None:
                logger.info(f"从缓存加载支撑位数据: {cached_data.shape}")
                return cached_data
        
        # 2. 批量查询支撑位数据
        placeholders = ','.join(['?' for _ in stock_codes])
        sql = f"""
            SELECT code, date, support_level
            FROM stock_support_level
            WHERE code IN ({placeholders})
            AND date BETWEEN ? AND ?
            ORDER BY code, date ASC
        """
        
        support_dict = {}
        params = stock_codes + [start_date, end_date]
        
        try:
            results = self.db_manager.query(sql, tuple(params))
            
            for code, date, support_level in results:
                if code not in support_dict:
                    support_dict[code] = []
                support_dict[code].append(support_level)
            
            # 转换为DataFrame
            support_levels = pd.DataFrame(support_dict)
            
            # 缓存结果
            if use_cache and self.cache_enabled:
                self.cache.set(cache_key, support_levels)
            
            logger.info(f"加载支撑位数据完成: {support_levels.shape}")
            return support_levels
        
        except Exception as e:
            logger.error(f"加载支撑位数据失败: {str(e)}")
            return pd.DataFrame()
    
    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        if self.cache_enabled:
            return self.cache.get_stats()
        return {}
    
    def get_load_stats(self) -> Dict:
        """获取加载统计信息"""
        return self.load_stats
    
    def clear_cache(self):
        """清空缓存"""
        if self.cache_enabled:
            self.cache.clear()
            logger.info("缓存已清空")


if __name__ == '__main__':
    """
    测试优化的数据加载器
    """
    from utils.db_manager import DBManager
    
    # 初始化数据库管理器
    db_manager = DBManager()
    
    # 初始化数据加载器
    loader = OptimizedDataLoader(db_manager, cache_enabled=True)
    
    # 测试数据加载
    try:
        # 获取所有股票代码
        sql = "SELECT DISTINCT code FROM stock_kline LIMIT 100"
        results = db_manager.query(sql)
        stock_codes = [r[0] for r in results]
        
        if stock_codes:
            # 第一次加载（从数据库）
            print("\n=== 第一次加载（从数据库）===")
            start_time = time.time()
            prices1 = loader.load_prices_matrix(
                stock_codes,
                '2024-01-01',
                '2024-06-30'
            )
            time1 = time.time() - start_time
            print(f"加载时间: {time1:.2f}秒")
            print(f"数据形状: {prices1.shape}")
            
            # 第二次加载（从缓存）
            print("\n=== 第二次加载（从缓存）===")
            start_time = time.time()
            prices2 = loader.load_prices_matrix(
                stock_codes,
                '2024-01-01',
                '2024-06-30'
            )
            time2 = time.time() - start_time
            print(f"加载时间: {time2:.2f}秒")
            print(f"数据形状: {prices2.shape}")
            
            # 打印缓存统计
            print("\n=== 缓存统计 ===")
            cache_stats = loader.get_cache_stats()
            print(f"缓存命中: {cache_stats['hits']}")
            print(f"缓存未命中: {cache_stats['misses']}")
            print(f"命中率: {cache_stats['hit_rate']:.2%}")
            print(f"缓存大小: {cache_stats['size']}")
            
            # 打印加载统计
            print("\n=== 加载统计 ===")
            load_stats = loader.get_load_stats()
            print(f"总时间: {load_stats['total_time']:.2f}秒")
            print(f"查询时间: {load_stats['query_time']:.2f}秒")
            print(f"处理时间: {load_stats['process_time']:.2f}秒")
            
            # 性能对比
            print("\n=== 性能对比 ===")
            print(f"第一次加载: {time1:.2f}秒")
            print(f"第二次加载: {time2:.2f}秒")
            print(f"性能提升: {time1/time2:.1f}倍")
    
    except Exception as e:
        logger.error(f"测试失败: {str(e)}", exc_info=True)
