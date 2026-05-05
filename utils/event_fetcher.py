"""
事件采集器 - 采集龙虎榜和融资融券数据
数据源：东方财富HTTP API（datacenter-web.eastmoney.com）
参考 stock-master: stock_lhb_em.py
"""

import json
import logging
import time
import random
import pandas as pd
import requests
from typing import Optional, Dict
from datetime import datetime, timedelta

from utils.base_fetcher import DataFetcher, HTTPDataSource, CacheDataSource, FetcherFactory, DataSource

logger = logging.getLogger(__name__)

# 东方财富数据中心请求头
EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://data.eastmoney.com/',
    'Accept': '*/*',
    'Connection': 'keep-alive',
}


class TushareEventSource(DataSource):
    """Tushare - 龙虎榜和融资融券数据源"""
    
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
        从Tushare获取龙虎榜数据
        
        返回：
            包含龙虎榜数据的DataFrame
        """
        try:
            # 获取Tushare pro实例
            pro = self._get_pro_api()
            if pro is None:
                return None
            
            # 调用Tushare接口获取龙虎榜数据
            # 获取最近一个交易日的龙虎榜数据
            df = pro.top10(fields='trade_date,ts_code,name,close,pct_change,amount,net_amount,net_pct,turnover_rate')
            
            if df is not None and len(df) > 0:
                return df
            
            return None
        
        except Exception as e:
            logger.debug(f"Tushare获取龙虎榜数据失败: {e}")
        
        return None


class EastMoneyLHBSource(HTTPDataSource):
    """东方财富 - 龙虎榜数据源
    参考 stock-master: stock_lhb_detail_em
    接口：datacenter-web.eastmoney.com/api/data/v1/get
    """
    
    def __init__(self):
        super().__init__("eastmoney_lhb", priority=1)
    
    def fetch(self, start_date: str = None, end_date: str = None,
              **kwargs) -> Optional[pd.DataFrame]:
        """
        从东方财富获取龙虎榜详情数据
        
        参数：
            start_date: 开始日期，格式YYYYMMDD，默认今天
            end_date: 结束日期，格式YYYYMMDD，默认今天
        返回：
            包含龙虎榜数据的DataFrame
        """
        try:
            # 默认日期：今天
            today = datetime.now().strftime('%Y%m%d')
            if not start_date:
                start_date = today
            if not end_date:
                end_date = today
            
            # 格式化日期
            sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
            ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
            
            url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                'sortColumns': 'SECURITY_CODE,TRADE_DATE',
                'sortTypes': '1,-1',
                'pageSize': '500',
                'pageNumber': '1',
                'reportName': 'RPT_DAILYBILLBOARD_DETAILSNEW',
                'columns': 'SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,'
                           'EXPLAIN,CLOSE_PRICE,CHANGE_RATE,'
                           'BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,'
                           'BILLBOARD_SELL_AMT,EXPLANATION',
                'source': 'WEB',
                'client': 'WEB',
                'filter': f"(TRADE_DATE<='{ed}')(TRADE_DATE>='{sd}')",
            }
            
            # 发送请求
            resp = requests.get(url, params=params, headers=EM_HEADERS, timeout=15)
            if resp.status_code != 200:
                return None
            
            # 解析响应
            data_json = resp.json()
            if not data_json.get('result') or not data_json['result'].get('data'):
                return None
            
            # 转换为DataFrame
            df = pd.DataFrame(data_json['result']['data'])
            
            # 重命名列
            col_map = {
                'SECURITY_CODE': '代码',
                'SECURITY_NAME_ABBR': '名称',
                'TRADE_DATE': '上榜日',
                'EXPLAIN': '解读',
                'CLOSE_PRICE': '收盘价',
                'CHANGE_RATE': '涨跌幅',
                'BILLBOARD_NET_AMT': '龙虎榜净买额',
                'BILLBOARD_BUY_AMT': '龙虎榜买入额',
                'BILLBOARD_SELL_AMT': '龙虎榜卖出额',
                'EXPLANATION': '上榜原因',
            }
            rename_map = {k: v for k, v in col_map.items() if k in df.columns}
            df = df.rename(columns=rename_map)
            
            # 日期格式化
            if '上榜日' in df.columns:
                df['上榜日'] = pd.to_datetime(df['上榜日']).dt.date
            
            # 数值转换
            for col in ['收盘价', '涨跌幅', '龙虎榜净买额', '龙虎榜买入额', '龙虎榜卖出额']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
        
        except Exception as e:
            logger.debug(f"东方财富获取龙虎榜数据失败: {e}")
        
        return None


class EastMoneyMarginTradingSource(HTTPDataSource):
    """东方财富 - 融资融券数据源
    接口：datacenter-web.eastmoney.com/api/data/v1/get
    """
    
    def __init__(self):
        super().__init__("eastmoney_margin_trading", priority=1)
    
    def fetch(self, start_date: str = None, **kwargs) -> Optional[pd.DataFrame]:
        """
        从东方财富获取融资融券数据
        
        参数：
            start_date: 查询日期，格式YYYYMMDD，默认最近交易日
        返回：
            包含融资融券数据的DataFrame
        """
        try:
            url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                'sortColumns': 'RZRQYE',
                'sortTypes': '-1',
                'pageSize': '500',
                'pageNumber': '1',
                'reportName': 'RPTA_WEB_RZRQ_GGMX',
                'columns': 'SCODE,SECNAME,DATE,RZYE,RQYE,RZRQYE,RZYEZB',
                'source': 'WEB',
                'client': 'WEB',
            }
            
            # 如果指定日期，添加过滤条件
            if start_date:
                sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
                params['filter'] = f"(DATE='{sd}')"
            
            # 发送请求
            resp = requests.get(url, params=params, headers=EM_HEADERS, timeout=15)
            if resp.status_code != 200:
                return None
            
            # 解析响应
            data_json = resp.json()
            if not data_json.get('result') or not data_json['result'].get('data'):
                return None
            
            # 转换为DataFrame
            df = pd.DataFrame(data_json['result']['data'])
            
            # 重命名列
            col_map = {
                'SCODE': '代码',
                'SECNAME': '名称',
                'DATE': '交易日期',
                'RZYE': '融资余额',
                'RQYE': '融券余额',
                'RZRQYE': '融资融券余额',
                'RZYEZB': '融资余额占比',
            }
            rename_map = {k: v for k, v in col_map.items() if k in df.columns}
            df = df.rename(columns=rename_map)
            
            # 日期格式化
            if '交易日期' in df.columns:
                df['交易日期'] = pd.to_datetime(df['交易日期']).dt.date
            
            # 数值转换
            for col in ['融资余额', '融券余额', '融资融券余额', '融资余额占比']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
        
        except Exception as e:
            logger.debug(f"东方财富获取融资融券数据失败: {e}")
        
        return None


class EventFetcher(DataFetcher):
    """事件采集器 - 采集龙虎榜和融资融券数据"""
    
    def __init__(self, db_manager, cache_manager):
        """初始化事件采集器"""
        super().__init__(db_manager, cache_manager)
        
        # 数据源优先级：Tushare(0) → 东方财富(1)
        self.add_data_source(TushareEventSource())
        self.add_data_source(EastMoneyLHBSource())
        self.add_data_source(EastMoneyMarginTradingSource())
    
    def validate_data(self, data) -> bool:
        """验证数据有效性"""
        if data is None:
            return False
        if isinstance(data, pd.DataFrame):
            return not data.empty
        return False
    
    def clean_data(self, data) -> any:
        """清洗数据"""
        if isinstance(data, pd.DataFrame):
            data = data.dropna(how='all').copy()
            return data
        return data
    
    def save_data(self, data: any) -> bool:
        """保存数据到数据库"""
        if not isinstance(data, pd.DataFrame):
            return False
        try:
            # 根据列名判断数据类型
            if '上榜原因' in data.columns or '龙虎榜净买额' in data.columns:
                return self._save_lhb_data(data)
            elif '融资余额' in data.columns:
                return self._save_margin_data(data)
        except Exception as e:
            logger.error(f"保存事件数据失败: {e}")
        return False
    
    def _save_lhb_data(self, df: pd.DataFrame) -> bool:
        """保存龙虎榜数据"""
        try:
            for _, row in df.iterrows():
                stock_code = row.get('代码', '')
                lhb_date = str(row.get('上榜日', ''))
                lhb_reason = row.get('上榜原因', '')
                net_buy = _safe_float(row.get('龙虎榜净买额'))
                
                sql = """
                INSERT OR REPLACE INTO stock_lhb 
                (stock_code, lhb_date, lhb_reason, lhb_type,
                 net_buy_amount, created_date) 
                VALUES (?, ?, ?, ?, ?, ?)
                """
                params = (
                    stock_code, lhb_date, lhb_reason, '龙虎榜',
                    net_buy, datetime.now().isoformat()
                )
                self.db_manager.execute(sql, params)
            return True
        except Exception as e:
            logger.error(f"保存龙虎榜数据失败: {e}")
            return False
    
    def _save_margin_data(self, df: pd.DataFrame) -> bool:
        """保存融资融券数据"""
        try:
            for _, row in df.iterrows():
                stock_code = row.get('代码', '')
                trade_date = str(row.get('交易日期', ''))
                margin_bal = _safe_float(row.get('融资余额'))
                short_bal = _safe_float(row.get('融券余额'))
                total_bal = _safe_float(row.get('融资融券余额'))
                
                sql = """
                INSERT OR REPLACE INTO stock_margin_trading 
                (stock_code, trading_date, margin_balance, short_balance,
                 total_balance, created_date) 
                VALUES (?, ?, ?, ?, ?, ?)
                """
                params = (
                    stock_code, trade_date, margin_bal, short_bal,
                    total_bal, datetime.now().isoformat()
                )
                self.db_manager.execute(sql, params)
            return True
        except Exception as e:
            logger.error(f"保存融资融券数据失败: {e}")
            return False
    
    def fetch_lhb_data(self, start_date: str = None,
                        end_date: str = None) -> Optional[pd.DataFrame]:
        """获取龙虎榜数据"""
        logger.info(f"获取龙虎榜数据: {start_date} ~ {end_date}")
        source = EastMoneyLHBSource()
        return source.fetch(start_date=start_date, end_date=end_date)
    
    def fetch_margin_trading(self, start_date: str = None) -> Optional[pd.DataFrame]:
        """获取融资融券数据"""
        logger.info(f"获取融资融券数据: {start_date}")
        source = EastMoneyMarginTradingSource()
        return source.fetch(start_date=start_date)
    
    def fetch_stock_events(self, stock_code: str) -> Optional[Dict]:
        """
        获取单只股票的事件信息
        
        参数：
            stock_code: 股票代码，例如000001
        
        返回：
            包含事件信息的字典，例如 {'stock_code': '000001', 'event_type': 'lhb', 'event_date': '2026-04-01'}
            如果获取失败返回 None
        """
        try:
            logger.debug(f"获取 {stock_code} 的事件信息")
            
            # TODO: 实现从东方财富或其他数据源获取单只股票的事件信息
            # 包括龙虎榜、融资融券、公告等
            
            return None
        except Exception as e:
            logger.debug(f"获取 {stock_code} 事件信息失败: {e}")
            return None
    
    def fetch_event_ranking(self) -> Optional[pd.DataFrame]:
        """
        获取事件排名数据（龙虎榜和融资融券）
        
        返回：
            包含事件排名的DataFrame，如果获取失败返回 None
        """
        try:
            logger.info("获取事件排名数据")
            
            # 采集龙虎榜数据
            lhb_data = self.fetch_lhb_data()
            
            # 采集融资融券数据
            margin_data = self.fetch_margin_trading()
            
            # 合并数据
            if lhb_data is not None and not lhb_data.empty:
                return lhb_data
            elif margin_data is not None and not margin_data.empty:
                return margin_data
            
            return None
        except Exception as e:
            logger.debug(f"获取事件排名数据失败: {e}")
            return None


def _safe_float(val, default=0.0) -> float:
    """安全转换为float"""
    try:
        return float(val) if val and val != '-' else default
    except (ValueError, TypeError):
        return default


# 注册采集器
FetcherFactory.register('event', EventFetcher)
