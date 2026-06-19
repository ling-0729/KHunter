"""
板块采集器 - 采集概念板块排名数据
数据源策略：
  - 板块排名：东方财富HTTP API（push2.eastmoney.com）
  - 备选：AKShare
参考 stock-master 项目的 eastmoney_fetcher 实现方式
"""

import logging
import math
import time
import random
import pandas as pd
import requests
from typing import Optional, Dict
from datetime import datetime

from utils.base_fetcher import DataFetcher, HTTPDataSource, CacheDataSource, FetcherFactory, DataSource

logger = logging.getLogger(__name__)

# 东方财富API通用请求头
EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://quote.eastmoney.com/',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Connection': 'keep-alive',
}


class TushareSectorSource(DataSource):
    """Tushare - 板块排名数据源"""
    
    def __init__(self):
        # 优先级0：Tushare为最高优先级
        super().__init__("tushare", priority=0)
        self._pro = None
    
    def _get_pro_api(self):
        """获取Tushare pro实例，支持缓存"""
        if self._pro is not None:
            return self._pro
        
        try:
            import tushare as ts
            import json
            
            # 读取Tushare配置
            try:
                with open('config/tushare_config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                token = config.get('token') or config.get('api_key')
            except Exception as e:
                logger.debug(f"读取Tushare配置失败: {e}")
                token = None
            
            # 创建pro实例
            if token:
                self._pro = ts.pro_api(token)
            else:
                self._pro = ts.pro_api()
            
            return self._pro
        except Exception as e:
            logger.debug(f"创建Tushare pro实例失败: {e}")
            return None
    
    def fetch(self, **kwargs) -> Optional[pd.DataFrame]:
        """
        从Tushare获取板块排名数据
        
        返回：
            包含板块排名的DataFrame
        """
        # 查询单只股票时不返回排名
        if kwargs.get('stock_code'):
            return None
        
        try:
            # 获取Tushare pro实例
            pro = self._get_pro_api()
            if pro is None:
                return None
            
            # 调用Tushare接口获取行业分类数据
            df = pro.industry_classified(fields='ts_code,industry,industry_name')
            
            if df is not None and len(df) > 0:
                return df
            
            return None
        
        except Exception as e:
            logger.debug(f"Tushare获取板块排名失败: {e}")
        
        return None


class EastMoneySectorRankingSource(HTTPDataSource):
    """东方财富 - 概念板块排名数据源（直接调用HTTP API）
    参考 stock-master: stock_sector_fund_flow_rank
    """
    
    def __init__(self):
        # 优先级1：东方财富为主要数据源
        super().__init__("eastmoney_sector_ranking", priority=1)
    
    def fetch(self, **kwargs) -> Optional[pd.DataFrame]:
        """
        从东方财富API获取概念板块排名
        接口：push2.eastmoney.com/api/qt/clist/get
        fs=m:90 t:3 表示概念板块
        
        返回：
            包含板块排名的DataFrame
        """
        # 查询单只股票时不返回排名
        if kwargs.get('stock_code'):
            return None
        
        try:
            url = "http://push2.eastmoney.com/api/qt/clist/get"
            page_size = 200
            params = {
                'pn': '1', 'pz': str(page_size),
                'po': '1', 'np': '1',
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                'fltt': '2', 'invt': '2',
                'fid': 'f3',
                'fs': 'm:90 t:3',  # t:3=概念板块
                'fields': 'f2,f3,f4,f8,f12,f14,f20,f104,f105,f128,f140',
                '_': int(time.time() * 1000),
            }
            
            # 发送第一页请求
            resp = requests.get(
                url, params=params, headers=EM_HEADERS, timeout=15
            )
            if resp.status_code != 200:
                return None
            
            # 解析JSON
            data_json = resp.json()
            if not data_json.get('data') or not data_json['data'].get('diff'):
                return None
            
            # 获取数据和总数
            records = data_json['data']['diff']
            total = data_json['data'].get('total', 0)
            page_count = math.ceil(total / page_size)
            
            # 分页获取剩余数据
            page = 1
            while page < page_count:
                time.sleep(random.uniform(0.3, 0.8))
                page += 1
                params['pn'] = str(page)
                resp = requests.get(
                    url, params=params, headers=EM_HEADERS, timeout=15
                )
                if resp.status_code == 200:
                    more = resp.json()
                    if more.get('data') and more['data'].get('diff'):
                        records.extend(more['data']['diff'])
            
            # 转换为DataFrame
            df = pd.DataFrame(records)
            
            # 重命名列
            col_map = {
                'f12': '板块代码', 'f14': '板块名称',
                'f2': '最新价', 'f3': '涨跌幅',
                'f4': '涨跌额', 'f8': '换手率',
                'f20': '总市值', 'f104': '上涨家数',
                'f105': '下跌家数', 'f128': '领涨股票',
                'f140': '领涨股票涨跌幅',
            }
            rename_map = {k: v for k, v in col_map.items() if k in df.columns}
            df = df.rename(columns=rename_map)
            
            # 过滤无效数据
            if '最新价' in df.columns:
                df = df[df['最新价'] != '-']
            
            return df
        
        except Exception as e:
            logger.debug(f"东方财富获取板块排名失败: {e}")
        
        return None


class SectorFetcher(DataFetcher):
    """板块采集器 - 采集概念板块排名"""
    
    def __init__(self, db_manager, cache_manager):
        """初始化板块采集器"""
        super().__init__(db_manager, cache_manager)
        
        # 数据源优先级：Tushare(0) → 东方财富(1)
        self.add_data_source(TushareSectorSource())
        self.add_data_source(EastMoneySectorRankingSource())
    
    def validate_data(self, data) -> bool:
        """验证数据有效性"""
        if data is None:
            return False
        if isinstance(data, dict):
            return 'sector_name' in data or 'stock_code' in data
        elif isinstance(data, pd.DataFrame):
            return not data.empty
        return False
    
    def clean_data(self, data) -> any:
        """清洗数据"""
        if isinstance(data, dict):
            data['sector_name'] = str(data.get('sector_name', '')).strip()
            return data
        elif isinstance(data, pd.DataFrame):
            data = data.dropna(how='all')
            return data
        return data
    
    def save_data(self, data: any) -> bool:
        """保存数据到数据库"""
        try:
            if isinstance(data, dict):
                return self._save_sector_mapping(data)
            elif isinstance(data, pd.DataFrame):
                return self._save_sector_ranking(data)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")
        return False
    
    def _save_sector_mapping(self, data: Dict) -> bool:
        """保存股票板块映射"""
        try:
            sql = """
            INSERT OR REPLACE INTO stock_sector_mapping 
            (stock_code, sector_code, mapping_date, created_date) 
            VALUES (?, ?, ?, ?)
            """
            params = (
                data.get('stock_code'),
                data.get('sector_name'),
                datetime.now().strftime('%Y-%m-%d'),
                datetime.now().isoformat()
            )
            self.db_manager.execute(sql, params)
            return True
        except Exception as e:
            logger.error(f"保存板块映射失败: {e}")
            return False
    
    def _save_sector_ranking(self, df: pd.DataFrame) -> bool:
        """保存板块排名数据"""
        try:
            for idx, row in df.iterrows():
                sector_code = row.get('板块代码') or ''
                sector_name = row.get('板块名称') or ''
                # 计算股票数量
                up = _safe_int(row.get('上涨家数'))
                down = _safe_int(row.get('下跌家数'))
                stock_count = up + down
                # 涨跌幅
                sector_change = _safe_float(row.get('涨跌幅'))
                
                sql = """
                INSERT OR REPLACE INTO stock_sector 
                (sector_code, sector_name, sector_type, stock_count, 
                 sector_change, rank_position, updated_date) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                params = (
                    sector_code, sector_name, '概念',
                    stock_count, sector_change, idx + 1,
                    datetime.now().isoformat()
                )
                self.db_manager.execute(sql, params)
            return True
        except Exception as e:
            logger.error(f"保存板块排名失败: {e}")
            return False
    
    def fetch_sector_ranking(self) -> Optional[pd.DataFrame]:
        """获取板块排名数据"""
        logger.info("获取板块排名数据")
        return self.fetch_with_retry()
    
    def fetch_stock_sector(self, stock_code: str) -> Optional[Dict]:
        """
        获取单只股票的板块信息
        
        参数：
            stock_code: 股票代码，例如000001
        
        返回：
            包含板块信息的字典，例如 {'stock_code': '000001', 'sector_code': 'BK0475', 'sector_name': '银行'}
            如果获取失败返回 None
        """
        try:
            # 这里可以调用东方财富API获取单只股票的板块信息
            # 由于API限制，暂时返回None，实际应该从数据源获取
            logger.debug(f"获取 {stock_code} 的板块信息")
            
            # TODO: 实现从东方财富或其他数据源获取单只股票的板块信息
            # 目前板块信息主要通过 fetch_sector_ranking 获取所有板块，
            # 然后通过其他方式关联到具体股票
            
            return None
        except Exception as e:
            logger.debug(f"获取 {stock_code} 板块信息失败: {e}")
            return None


def _safe_int(val, default=0) -> int:
    """安全转换为int"""
    try:
        return int(val) if val and val != '-' else default
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0) -> float:
    """安全转换为float"""
    try:
        return float(val) if val and val != '-' else default
    except (ValueError, TypeError):
        return default


# 注册采集器
FetcherFactory.register('sector', SectorFetcher)
