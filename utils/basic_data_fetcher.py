"""
基础数据采集器 - 采集股票基本信息和历史行情数据
数据源：腾讯财经 → AKShare → 本地缓存
"""

import logging
import pandas as pd
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime, timedelta
import requests
import time

from utils.base_fetcher import DataFetcher, DataSource, HTTPDataSource, CacheDataSource, FetcherFactory

logger = logging.getLogger(__name__)


class TencentStockBasicSource(HTTPDataSource):
    """腾讯财经 - 股票基本信息数据源"""
    
    def __init__(self):
        super().__init__("tencent_basic", priority=1)
    
    def fetch(self, stock_code: str, **kwargs) -> Optional[Dict]:
        """
        从腾讯财经获取股票基本信息
        
        参数：
            stock_code: 股票代码（6位数字）
        
        返回：
            包含股票基本信息的字典
        """
        try:
            # 构建腾讯财经查询代码
            if stock_code.startswith('6') or stock_code.startswith('8'):
                query_code = f"sh{stock_code}"
            else:
                query_code = f"sz{stock_code}"
            
            # 调用腾讯财经接口
            url = f"https://qt.gtimg.cn/q={query_code}"
            text = self._request(url)
            
            if text and '~' in text:
                # 腾讯接口返回格式: v_sh600519="1~贵州茅台~600519~1800.5~..."
                # 需要先提取等号后的数据部分
                if '=' in text:
                    data_part = text.split('=')[1].strip('"')
                    parts = data_part.split('~')
                else:
                    parts = text.split('~')
                
                if len(parts) >= 4:
                    # 解析腾讯接口返回的数据
                    # parts[1]=名称, parts[3]=当前价, parts[44]=总市值(亿)
                    name = parts[1] if len(parts) > 1 else ""
                    price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
                    market_cap = float(parts[44]) if len(parts) > 44 and parts[44] else 0
                    
                    if market_cap > 0:
                        market_cap = int(market_cap * 1e8)  # 转为元
                    
                    return {
                        'code': stock_code,
                        'name': name,
                        'price': price,
                        'market_cap': market_cap,
                        'source': 'tencent'
                    }
        except Exception as e:
            logger.debug(f"腾讯财经获取基本信息失败 ({stock_code}): {e}")
        
        return None


class TencentHistorySource(HTTPDataSource):
    """腾讯财经 - 历史行情数据源"""
    
    def __init__(self):
        super().__init__("tencent_history", priority=1)
    
    def fetch(self, stock_code: str, days: int = 1000, **kwargs) -> Optional[pd.DataFrame]:
        """
        从腾讯财经获取历史行情数据
        
        参数：
            stock_code: 股票代码
            days: 获取天数（最多1000天）
        
        返回：
            包含历史行情的DataFrame
        """
        try:
            # 构建腾讯财经查询代码
            if stock_code.startswith('6') or stock_code.startswith('8'):
                market_code = f"sh{stock_code}"
            else:
                market_code = f"sz{stock_code}"
            
            # 腾讯接口：获取日K线数据
            fetch_days = min(days, 1000)
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_code},day,,,{fetch_days},qfq"
            
            resp = requests.get(url, timeout=self.timeout, headers=self.headers)
            data = resp.json()
            
            # 解析腾讯返回的数据
            data_level = data.get('data', {})
            klines = []
            
            if isinstance(data_level, dict):
                stock_data = data_level.get(market_code, {})
                if isinstance(stock_data, dict):
                    klines = stock_data.get('qfqday', []) or stock_data.get('day', [])
            
            if klines:
                records = []
                for item in klines:
                    # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
                    if len(item) >= 6 and isinstance(item, list):
                        records.append({
                            'date': str(item[0]),
                            'open': float(item[1]),
                            'close': float(item[2]),
                            'high': float(item[3]),
                            'low': float(item[4]),
                            'volume': int(float(item[5])),
                            'amount': 0,
                            'turnover': 0,
                        })
                
                if records:
                    df = pd.DataFrame(records)
                    df['date'] = pd.to_datetime(df['date'])
                    # 添加股票代码字段
                    df['stock_code'] = stock_code
                    df = df.sort_values('date', ascending=False)
                    return df
        
        except Exception as e:
            logger.debug(f"腾讯财经获取历史数据失败 ({stock_code}): {e}")
        
        return None


class BasicDataFetcher(DataFetcher):
    """基础数据采集器 - 采集股票基本信息和历史行情"""
    
    def __init__(self, db_manager, cache_manager):
        """初始化基础数据采集器"""
        super().__init__(db_manager, cache_manager)
        
        # 分别存储不同类型的数据源
        from utils.base_fetcher import CacheDataSource
        self.basic_sources = [TencentStockBasicSource()]
        self.history_sources = [TencentHistorySource()]
        # 添加缓存数据源（优先级最高）
        self.cache_source = CacheDataSource(cache_manager)
        # 合并所有数据源（用于测试），缓存数据源优先级最高
        self.data_sources = [self.cache_source] + self.basic_sources + self.history_sources
    
    def validate_data(self, data) -> bool:
        """验证数据有效性"""
        if data is None:
            return False
        
        if isinstance(data, dict):
            # 验证基本信息
            return 'code' in data and 'name' in data
        elif isinstance(data, pd.DataFrame):
            # 验证历史数据
            return not data.empty and 'date' in data.columns and 'close' in data.columns
        
        return False
    
    def clean_data(self, data) -> any:
        """清洗数据"""
        if isinstance(data, dict):
            # 清洗基本信息
            data['name'] = str(data.get('name', '')).strip()
            data['price'] = float(data.get('price', 0))
            data['market_cap'] = int(data.get('market_cap', 0))
            return data
        elif isinstance(data, pd.DataFrame):
            # 清洗历史数据
            data = data.dropna(subset=['close'])
            data['close'] = pd.to_numeric(data['close'], errors='coerce')
            data['volume'] = pd.to_numeric(data['volume'], errors='coerce').fillna(0).astype(int)
            return data
        
        return data
    
    def save_data(self, data: any) -> bool:
        """保存数据到数据库"""
        try:
            if isinstance(data, dict):
                # 保存基本信息到 stock_basic 表
                return self._save_basic_info(data)
            elif isinstance(data, pd.DataFrame):
                # 保存历史数据到 stock_kline 表
                return self._save_history_data(data)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")
        
        return False
    
    def _save_basic_info(self, data: Dict) -> bool:
        """保存股票基本信息"""
        try:
            # 使用 INSERT OR REPLACE 语句处理唯一约束
            sql = """
            INSERT OR REPLACE INTO stock_basic 
            (code, name, market_cap, update_time) 
            VALUES (?, ?, ?, ?)
            """
            params = (
                data['code'],
                data['name'],
                data.get('market_cap', 0),
                datetime.now().isoformat()
            )
            # 执行SQL语句
            self.db_manager.execute(sql, params)
            # 提交事务
            conn = self.db_manager.connect()
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"保存基本信息失败: {e}")
            return False
    
    def _save_history_data(self, df: pd.DataFrame) -> bool:
        """保存历史行情数据到 stock_kline 表"""
        try:
            # 准备数据列表
            kline_data_list = []
            for _, row in df.iterrows():
                # 准备数据字典
                kline_data = {
                    'code': row.get('stock_code'),
                    'date': row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date']),
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': int(row.get('volume', 0)),
                    'market_cap': float(row.get('market_cap', 0)),
                    'created_date': datetime.now().isoformat(),
                    'updated_date': datetime.now().isoformat()
                }
                kline_data_list.append(kline_data)
            
            # 使用 insert_many 方法批量插入，确保事务被正确处理
            if kline_data_list:
                self.db_manager.insert_many('stock_kline', kline_data_list)
            
            return True
        except Exception as e:
            logger.error(f"保存历史数据失败: {e}")
            return False
    
    def _fetch_with_sources(self, sources, **kwargs) -> Optional[Any]:
        """使用指定的数据源列表获取数据"""
        for source in sources:
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
    
    def fetch_stock_basic(self, stock_code: str) -> Optional[Dict]:
        """获取单只股票的基本信息"""
        logger.info(f"获取股票基本信息: {stock_code}")
        return self._fetch_with_sources(self.basic_sources, stock_code=stock_code)
    
    def fetch_stock_history(self, stock_code: str, days: int = 1000) -> Optional[pd.DataFrame]:
        """获取单只股票的历史行情数据"""
        logger.info(f"获取股票历史数据: {stock_code} ({days}天)")
        return self._fetch_with_sources(self.history_sources, stock_code=stock_code, days=days)


# 注册采集器
FetcherFactory.register('basic', BasicDataFetcher)
