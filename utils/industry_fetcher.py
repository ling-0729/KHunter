"""
行业采集器 - 采集股票行业信息和行业排名数据
数据源策略：
  - 单只股票行业查询：AKShare stock_individual_info_em（东方财富数据）
  - 行业排名：东方财富HTTP API（push2.eastmoney.com）
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


class TushareIndustrySource(DataSource):
    """Tushare - 个股行业信息数据源"""
    
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
    
    def fetch(self, stock_code: str = None, **kwargs) -> Optional[Dict]:
        """
        从Tushare获取个股行业信息
        
        参数：
            stock_code: 股票代码
        返回：
            包含行业信息的字典
        """
        if not stock_code:
            return None
        
        try:
            # 获取Tushare pro实例
            pro = self._get_pro_api()
            if pro is None:
                return None
            
            # 调用Tushare接口获取股票基础信息
            df = pro.stock_basic(fields='ts_code,symbol,name,industry')
            
            if df is not None and len(df) > 0:
                # 标准化股票代码（去掉.SZ/.SH后缀）
                normalized_code = stock_code.replace('.SZ', '').replace('.SH', '')
                
                # 查找匹配的股票
                for idx, row in df.iterrows():
                    # 检查symbol或ts_code是否匹配
                    if (str(row.get('symbol', '')).strip() == normalized_code or
                        str(row.get('ts_code', '')).strip().startswith(normalized_code)):
                        
                        industry_name = str(row.get('industry', '')).strip()
                        if industry_name:
                            return {
                                'stock_code': stock_code,
                                'industry_name': industry_name,
                                'source': 'tushare'
                            }
            
            return None
        
        except Exception as e:
            logger.debug(f"Tushare获取行业信息失败 ({stock_code}): {e}")
        
        return None


class EastMoneyIndustrySource(HTTPDataSource):
    """东方财富 - 个股行业信息数据源（通过AKShare接口）"""
    
    def __init__(self):
        # 优先级1：东方财富为主要数据源
        super().__init__("eastmoney_industry", priority=1)
    
    def fetch(self, stock_code: str = None, **kwargs) -> Optional[Dict]:
        """
        从东方财富获取个股行业信息
        使用AKShare的stock_individual_info_em接口（底层调用东方财富API）
        
        参数：
            stock_code: 股票代码
        返回：
            包含行业信息的字典
        """
        if not stock_code:
            return None
        
        try:
            import akshare as ak
            
            # 调用东方财富个股信息接口
            df = ak.stock_individual_info_em(symbol=stock_code)
            if df is not None and len(df) > 0:
                # 遍历查找行业字段
                for idx, row in df.iterrows():
                    field_name = str(row.iloc[0]).strip()
                    field_value = str(row.iloc[1]).strip()
                    
                    # 匹配行业字段
                    if '行业' in field_name:
                        return {
                            'stock_code': stock_code,
                            'industry_name': field_value,
                            'source': 'eastmoney'
                        }
            
            return None
        
        except Exception as e:
            logger.debug(f"东方财富获取行业信息失败 ({stock_code}): {e}")
        
        return None


class EastMoneyIndustryRankingSource(HTTPDataSource):
    """东方财富 - 行业排名数据源（直接调用HTTP API）
    参考 stock-master: stock_sector_fund_flow_rank
    """
    
    def __init__(self):
        # 优先级1：东方财富行业排名
        super().__init__("eastmoney_industry_ranking", priority=1)
    
    def fetch(self, **kwargs) -> Optional[pd.DataFrame]:
        """
        从东方财富API获取行业板块排名
        接口：push2.eastmoney.com/api/qt/clist/get
        fs=m:90 t:2 表示行业板块
        
        返回：
            包含行业排名的DataFrame
        """
        # 查询单只股票时不返回排名
        if kwargs.get('stock_code'):
            return None
        
        try:
            url = "http://push2.eastmoney.com/api/qt/clist/get"
            params = {
                'pn': '1', 'pz': '200', 'po': '1', 'np': '1',
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                'fltt': '2', 'invt': '2',
                'fid': 'f3',
                'fs': 'm:90 t:2',  # t:2=行业板块
                'fields': 'f2,f3,f4,f8,f12,f14,f20,f104,f105,f128,f140',
                '_': int(time.time() * 1000),
            }
            
            # 发送请求
            resp = requests.get(
                url, params=params, headers=EM_HEADERS, timeout=15
            )
            if resp.status_code != 200:
                return None
            
            # 解析JSON
            data_json = resp.json()
            if not data_json.get('data') or not data_json['data'].get('diff'):
                return None
            
            # 转换为DataFrame
            df = pd.DataFrame(data_json['data']['diff'])
            
            # 重命名列
            col_map = {
                'f12': '行业代码', 'f14': '行业名称',
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
            logger.debug(f"东方财富获取行业排名失败: {e}")
        
        return None


class IndustryFetcher(DataFetcher):
    """行业采集器 - 采集股票行业信息和行业排名"""
    
    def __init__(self, db_manager, cache_manager):
        """初始化行业采集器"""
        super().__init__(db_manager, cache_manager)
        
        # 数据源优先级：Tushare(0) → 东方财富(1)
        # 注意：不在更新时使用缓存，只在初始化时使用
        self.add_data_source(TushareIndustrySource())
        self.add_data_source(EastMoneyIndustrySource())
        self.add_data_source(EastMoneyIndustryRankingSource())
    
    def validate_data(self, data) -> bool:
        """验证数据有效性"""
        if data is None:
            return False
        if isinstance(data, dict):
            return 'industry_name' in data or 'stock_code' in data
        elif isinstance(data, pd.DataFrame):
            return not data.empty
        return False
    
    def clean_data(self, data) -> any:
        """清洗数据"""
        if isinstance(data, dict):
            data['industry_name'] = str(data.get('industry_name', '')).strip()
            return data
        elif isinstance(data, pd.DataFrame):
            data = data.dropna(how='all')
            return data
        return data
    
    def save_data(self, data: any) -> bool:
        """保存数据到数据库"""
        try:
            if isinstance(data, dict):
                return self._save_industry_mapping(data)
            elif isinstance(data, pd.DataFrame):
                return self._save_industry_ranking(data)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")
        return False
    
    def _save_industry_mapping(self, data: Dict) -> bool:
        """保存股票行业映射"""
        try:
            # 确保必要字段存在
            stock_code = data.get('stock_code')
            industry_name = data.get('industry_name')
            
            if not stock_code or not industry_name:
                return False
            
            # 如果没有industry_code，使用industry_name作为industry_code
            industry_code = data.get('industry_code') or industry_name
            
            # 先保存行业信息（如果不存在）
            industry_sql = """
            INSERT OR REPLACE INTO stock_industry 
            (industry_code, industry_name, updated_date) 
            VALUES (?, ?, ?)
            """
            self.db_manager.execute(industry_sql, (
                industry_code, industry_name, datetime.now().isoformat()
            ))
            

            return True
        except Exception as e:
            logger.error(f"保存行业映射失败: {e}")
            return False
    
    def _save_industry_ranking(self, df: pd.DataFrame) -> bool:
        """保存行业排名数据"""
        try:
            for idx, row in df.iterrows():
                # 提取行业信息
                industry_code = row.get('行业代码') or ''
                industry_name = row.get('行业名称') or ''
                # 计算股票数量
                up = _safe_int(row.get('上涨家数'))
                down = _safe_int(row.get('下跌家数'))
                stock_count = up + down
                # 涨跌幅
                industry_change = _safe_float(row.get('涨跌幅'))
                
                sql = """
                INSERT OR REPLACE INTO stock_industry 
                (industry_code, industry_name, stock_count, industry_change, 
                 rank_position, updated_date) 
                VALUES (?, ?, ?, ?, ?, ?)
                """
                params = (
                    industry_code, industry_name, stock_count,
                    industry_change, idx + 1,
                    datetime.now().isoformat()
                )
                self.db_manager.execute(sql, params)
            return True
        except Exception as e:
            logger.error(f"保存行业排名失败: {e}")
            return False
    
    def fetch_stock_industry(self, stock_code: str) -> Optional[Dict]:
        """获取单只股票的行业信息"""
        logger.info(f"获取股票行业信息: {stock_code}")
        return self.fetch_with_retry(stock_code=stock_code)
    
    def fetch_industry_ranking(self) -> Optional[pd.DataFrame]:
        """获取行业排名数据"""
        logger.info("获取行业排名数据")
        return self.fetch_with_retry()


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
FetcherFactory.register('industry', IndustryFetcher)
