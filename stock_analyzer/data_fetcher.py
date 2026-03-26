#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取模块
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import time
import sys
from pathlib import Path
import json
import requests
import random
from typing import Dict, List, Optional, Any

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.csv_manager import CSVManager
from utils.akshare_retry import akshare_call_with_retry


class DataFetcher:
    """数据获取器"""
    
    def __init__(self):
        """初始化数据获取器"""
        # 初始化CSV管理器
        self.csv_manager = CSVManager('data')
        
        # 设置请求会话
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://quote.eastmoney.com/',
            'Connection': 'keep-alive',
        })
        
        # 备选A股股票列表（当网络获取失败时使用）
        self.DEFAULT_STOCK_LIST = {
            "600519": "贵州茅台", "600036": "招商银行", "601398": "工商银行",
            "600900": "长江电力", "601288": "农业银行", "601088": "中国神华",
            "601857": "中国石油", "600030": "中信证券", "601628": "中国人寿",
            "600276": "恒瑞医药", "601318": "中国平安", "600309": "万华化学",
            "600887": "伊利股份", "601166": "兴业银行", "600028": "中国石化",
            "601888": "中国中免", "600031": "三一重工", "601012": "隆基绿能",
            "603288": "海天味业", "600009": "上海机场", "600436": "片仔癀",
            "603259": "药明康德", "601668": "中国建筑", "600048": "保利发展",
            "600585": "海螺水泥", "601601": "中国太保", "603501": "韦尔股份",
            "600690": "海尔智家", "601818": "光大银行", "600893": "航发动力",
            "601688": "华泰证券", "601211": "国泰君安", "600837": "海通证券",
            "000001": "平安银行", "000002": "万科A", "000333": "美的集团",
            "000858": "五粮液", "002594": "比亚迪", "000568": "泸州老窖",
            "000538": "云南白药", "002415": "海康威视", "000725": "京东方A",
        }
    
    def get_stock_basic(self, stock_code: str) -> Dict[str, Any]:
        """获取股票基本信息
        
        Args:
            stock_code: 股票代码
            
        Returns:
            dict: 股票基本信息
        """
        try:
            # 通过重试包装器从 akshare 获取（缓存TTL 7天，基本信息类）
            stock_info = akshare_call_with_retry(
                ak.stock_individual_info_em, cache_ttl=604800, symbol=stock_code
            )
            if stock_info is not None and not stock_info.empty:
                # 检查列是否存在
                name_col = "股票名称" if "股票名称" in stock_info.columns else "item"
                industry_col = "所属行业" if "所属行业" in stock_info.columns else "item"
                sector_col = "所属板块" if "所属板块" in stock_info.columns else "item"
                
                return {
                    "code": stock_code,
                    "name": stock_info.get(name_col, "").iloc[0] if not stock_info.get(name_col).empty else "",
                    "industry": stock_info.get(industry_col, "").iloc[0] if not stock_info.get(industry_col).empty else "",
                    "sector": stock_info.get(sector_col, "").iloc[0] if not stock_info.get(sector_col).empty else "",
                    "market": "沪市" if stock_code.startswith("6") else "深市"
                }
            
            # 如果获取失败，使用默认数据
            return {
                "code": stock_code,
                "name": self.DEFAULT_STOCK_LIST.get(stock_code, stock_code),
                "industry": "未知行业",
                "sector": "未知板块",
                "market": "沪市" if stock_code.startswith("6") else "深市"
            }
            
        except Exception as e:
            print(f"获取股票基本信息失败: {e}")
            # 返回默认数据
            return {
                "code": stock_code,
                "name": self.DEFAULT_STOCK_LIST.get(stock_code, stock_code),
                "industry": "未知行业",
                "sector": "未知板块",
                "market": "沪市" if stock_code.startswith("6") else "深市"
            }
    
    def get_stock_quote(self, stock_code: str, period: str = 'daily') -> pd.DataFrame:
        """获取历史行情数据
        
        Args:
            stock_code: 股票代码
            period: 周期 (daily, weekly, monthly) 或天数 (30d, 60d, 90d, 1y)
            
        Returns:
            pd.DataFrame: 历史行情数据
        """
        local_df = pd.DataFrame(columns=['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])
        
        try:
            # 1. 优先从本地读取数据
            local_df = self.csv_manager.read_stock(stock_code)
            if not local_df.empty:
                print(f"从本地获取 {stock_code} 历史数据: {len(local_df)} 条")
                
                # 计算需要的日期范围
                end_date = datetime.now()
                if period == '30d':
                    start_date = end_date - timedelta(days=30)
                elif period == '60d':
                    start_date = end_date - timedelta(days=60)
                elif period == '90d':
                    start_date = end_date - timedelta(days=90)
                elif period == '1y':
                    start_date = end_date - timedelta(days=365)
                else:
                    start_date = end_date - timedelta(days=30)
                
                # 过滤日期范围
                filtered_df = local_df[local_df['date'] >= start_date]
                if not filtered_df.empty:
                    # 确保列名正确
                    if 'date' in filtered_df.columns and 'close' in filtered_df.columns:
                        return filtered_df
                else:
                    # 本地数据不足，但有一些数据，返回全部本地数据
                    if 'date' in local_df.columns and 'close' in local_df.columns:
                        print(f"本地数据不足，返回全部本地数据: {len(local_df)} 条")
                        return local_df
            
            # 2. 本地数据为空，尝试从网络获取
            print(f"本地无数据，尝试从网络获取 {stock_code} 历史数据")
            
            # 计算日期范围
            end_date = datetime.now()
            if period == '30d':
                start_date = end_date - timedelta(days=30)
            elif period == '60d':
                start_date = end_date - timedelta(days=60)
            elif period == '90d':
                start_date = end_date - timedelta(days=90)
            elif period == '1y':
                start_date = end_date - timedelta(days=365)
            else:
                start_date = end_date - timedelta(days=30)
            
            # 格式化日期
            start_date_str = start_date.strftime("%Y%m%d")
            end_date_str = end_date.strftime("%Y%m%d")
            
            # 尝试从akshare获取
            if stock_code.startswith("6"):
                # 沪市股票
                data = ak.stock_zh_a_hist(symbol=stock_code, start_date=start_date_str, end_date=end_date_str)
            else:
                # 深市股票
                data = ak.stock_zh_a_hist(symbol=stock_code, start_date=start_date_str, end_date=end_date_str)
            
            # 重命名列
            if not data.empty:
                data = data.rename(columns={
                    "日期": "date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "amount"
                })
                # 转换日期格式
                data['date'] = pd.to_datetime(data['date'])
                # 按日期排序
                data = data.sort_values('date')
                
                # 保存到本地
                self.csv_manager.update_stock(stock_code, data)
                print(f"已保存 {stock_code} 历史数据到本地")
            
            return data
            
        except Exception as e:
            print(f"获取历史行情数据失败: {e}")
            # 即使网络失败，返回本地数据（如果有）
            if not local_df.empty:
                print(f"返回本地缓存数据: {len(local_df)} 条")
                return local_df
            # 返回空DataFrame
            return pd.DataFrame(columns=['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])
    
    def get_financial_data(self, stock_code: str, report_type: str = 'annual') -> Dict[str, Any]:
        """获取财务数据
        
        Args:
            stock_code: 股票代码
            report_type: 报告类型 (annual, quarterly)
            
        Returns:
            dict: 财务数据
        """
        try:
            # 通过重试包装器从 akshare 获取财务数据
            if report_type == 'annual':
                financial_data = akshare_call_with_retry(
                    ak.stock_financial_analysis_indicator, symbol=stock_code
                )
            else:
                financial_data = akshare_call_with_retry(
                    ak.stock_financial_analysis_indicator, symbol=stock_code
                )
            
            if financial_data is not None and not financial_data.empty:
                return {
                    "revenue": float(financial_data.get("营业总收入", 0).iloc[0]) if not financial_data.get("营业总收入").empty else 0,
                    "profit": float(financial_data.get("净利润", 0).iloc[0]) if not financial_data.get("净利润").empty else 0,
                    "roe": float(financial_data.get("净资产收益率", 0).iloc[0]) if not financial_data.get("净资产收益率").empty else 0,
                    "debt_ratio": float(financial_data.get("资产负债率", 0).iloc[0]) if not financial_data.get("资产负债率").empty else 0
                }
            
            return {"revenue": 0, "profit": 0, "roe": 0, "debt_ratio": 0}
            
        except Exception as e:
            print(f"获取财务数据失败: {e}")
            return {"revenue": 0, "profit": 0, "roe": 0, "debt_ratio": 0}
    
    def get_fund_flow(self, stock_code: str, days: int = 30) -> Dict[str, Any]:
        """获取资金流向数据
        
        Args:
            stock_code: 股票代码
            days: 天数
            
        Returns:
            dict: 资金流向数据
        """
        try:
            # 通过重试包装器从 akshare 获取资金流向
            fund_flow = akshare_call_with_retry(
                ak.stock_individual_fund_flow, stock=stock_code
            )
            
            if fund_flow is not None and not fund_flow.empty:
                # 获取主力净流入
                main_inflow = 0
                if "主力净流入" in fund_flow.columns:
                    main_inflow = fund_flow.get("主力净流入", 0).iloc[0] if not fund_flow.get("主力净流入").empty else 0
                
                # 获取成交量变化
                volume_change = "稳定"
                if "成交量" in fund_flow.columns and len(fund_flow) >= 2:
                    current_volume = fund_flow.get("成交量", 0).iloc[0] if not fund_flow.get("成交量").empty else 0
                    prev_volume = fund_flow.get("成交量", 0).iloc[1] if not fund_flow.get("成交量").empty else 0
                    volume_change = "增加" if current_volume > prev_volume else "减少"
                
                return {
                    "main_inflow": float(main_inflow) if main_inflow is not None else 0,
                    "north_inflow": 0,  # akshare暂时没有北向资金数据
                    "volume_change": volume_change
                }
            
            return {"main_inflow": 0, "north_inflow": 0, "volume_change": "稳定"}
            
        except Exception as e:
            print(f"获取资金流向数据失败: {e}")
            return {"main_inflow": 0, "north_inflow": 0, "volume_change": "稳定"}
    
    def get_sector_data(self, stock_code: str) -> Dict[str, Any]:
        """获取板块数据
        
        Args:
            stock_code: 股票代码
            
        Returns:
            dict: 板块数据
        """
        try:
            # 获取股票基本信息
            stock_info = self.get_stock_basic(stock_code)
            industry = stock_info.get("industry", "")
            
            if industry:
                # 通过重试包装器尝试获取行业板块数据
                try:
                    sector_data = akshare_call_with_retry(
                        ak.stock_board_industry_summary, symbol=industry
                    )
                    if sector_data is not None and not sector_data.empty:
                        return {
                            "name": industry,
                            "rank": int(sector_data.get("涨跌幅排名", 0).iloc[0]) if not sector_data.get("涨跌幅排名").empty else 0,
                            "change": float(sector_data.get("涨跌幅", 0).iloc[0]) if not sector_data.get("涨跌幅").empty else 0
                        }
                except:
                    pass
            
            return {"name": industry, "rank": 0, "change": 0}
            
        except Exception as e:
            print(f"获取板块数据失败: {e}")
            return {"name": "", "rank": 0, "change": 0}
    
    def get_event_data(self, stock_code: str, days: int = 30) -> List[Dict[str, Any]]:
        """获取事件数据
        
        Args:
            stock_code: 股票代码
            days: 天数
            
        Returns:
            list: 事件数据列表
        """
        try:
            # 尝试从akshare获取
            events = []
            
            # 获取公告数据
            try:
                notices = akshare_call_with_retry(
                    ak.stock_zh_a_notice, symbol=stock_code
                )
                if notices is not None and not notices.empty:
                    for _, row in notices.head(5).iterrows():
                        events.append({
                            "type": "公告",
                            "content": row.get("标题", ""),
                            "date": row.get("发布日期", "")
                        })
            except:
                pass
            
            return events
            
        except Exception as e:
            print(f"获取事件数据失败: {e}")
            return []


if __name__ == "__main__":
    # 测试数据获取器
    fetcher = DataFetcher()
    
    # 测试获取股票基本信息
    stock_info = fetcher.get_stock_basic("600519")
    print("股票基本信息:", stock_info)
    
    # 测试获取历史行情数据
    quote_data = fetcher.get_stock_quote("600519", period="30d")
    print("历史行情数据:", quote_data.head())
    
    # 测试获取财务数据
    financial_data = fetcher.get_financial_data("600519")
    print("财务数据:", financial_data)
    
    # 测试获取资金流向数据
    fund_flow = fetcher.get_fund_flow("600519")
    print("资金流向数据:", fund_flow)
    
    # 测试获取板块数据
    sector_data = fetcher.get_sector_data("600519")
    print("板块数据:", sector_data)
    
    # 测试获取事件数据
    events = fetcher.get_event_data("600519")
    print("事件数据:", events)
