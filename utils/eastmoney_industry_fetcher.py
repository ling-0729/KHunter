#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import time
from utils.eastmoney_fetcher import fetcher

# 配置日志
logger = logging.getLogger(__name__)


def get_all_stocks_industry_info():
    """
    批量获取所有A股股票的行业信息
    使用分页方式获取，每页50条，与 stock-master 保持一致
    
    Returns:
        dict: 以股票代码为键，行业信息为值的字典
    """
    try:
        # 参考 stock-master 项目的实现，使用 push2.eastmoney.com API 端点
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        
        all_stocks = {}
        page_size = 50  # 与 stock-master 保持一致
        page_current = 1
        
        while True:
            params = {
                "pn": page_current,
                "pz": page_size,
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f12",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                "fields": "f12,f14,f114,f115,f221",
                "_": "1623833739532",
            }
            
            # 发送请求（make_request 内部已有重试机制）
            response = fetcher.make_request(url, params=params)
            data_json = response.json()
            
            # 解析响应数据
            if not data_json.get("data") or not data_json["data"].get("diff"):
                break
            
            data = data_json["data"]["diff"]
            if not data:
                break
            
            # 提取行业信息
            for item in data:
                stock_code = item.get("f12")
                if stock_code:
                    all_stocks[stock_code] = {
                        "code": stock_code,
                        "name": item.get("f14"),
                        "industry": str(item.get("f114", "")),
                        "area": str(item.get("f115", "")),
                        "market": "SZ" if stock_code.startswith(('00', '30')) else "SH",
                        "list_date": str(item.get("f221", ""))
                    }
            
            # 检查是否还有更多数据
            total_count = data_json["data"].get("total", 0)
            
            # 每50页输出一次进度（每2500条）
            if len(all_stocks) % 2500 < page_size:
                logger.info(f"已获取 {len(all_stocks)} 只股票的行业信息，共 {total_count} 只")
            
            # 用实际返回的数据量判断是否还有更多
            if len(data) < page_size:
                break
            
            # 每页之间添加间隔，避免被服务器限流
            time.sleep(0.5)
            
            page_current += 1
        
        logger.info(f"成功获取 {len(all_stocks)} 只股票的行业信息")
        return all_stocks
        
    except Exception as e:
        logger.error(f"批量获取股票行业信息失败：{e}")
        # 如果已经有部分数据，返回已获取的数据
        if all_stocks:
            logger.warning(f"返回已获取的 {len(all_stocks)} 只股票的行业信息")
            return all_stocks
        return {}


def get_stock_industry_info(stock_code):
    """
    从东方财富网获取个股行业信息
    
    Args:
        stock_code: 股票代码
        
    Returns:
        dict: 包含行业信息的字典，如果获取失败返回 None
    """
    try:
        # 根据股票代码判断市场
        if stock_code.startswith(('00', '30')):
            secid = f"0.{stock_code}"
            market = 'SZ'
        else:
            secid = f"1.{stock_code}"
            market = 'SH'
        
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "invt": "2",
            "fltt": "2",
            "fields": "f12,f14,f20,f30,f31,f32",
            "secid": secid
        }
        
        # 发送请求
        response = fetcher.make_request(url, params=params)
        data_json = response.json()
        
        # 解析响应数据
        if data_json.get("data"):
            stock_data = data_json["data"]
            industry_info = {
                "code": stock_data.get("f12"),
                "name": stock_data.get("f14"),
                "industry": str(stock_data.get("f20", "")),
                "area": str(stock_data.get("f30", "")),
                "market": stock_data.get("f31", market),
                "list_date": stock_data.get("f32", "")
            }
            return industry_info
        
        logger.warning(f"获取股票 {stock_code} 行业信息失败：无数据")
        return None
    except Exception as e:
        logger.error(f"获取股票 {stock_code} 行业信息失败：{e}")
        return None


def get_stock_industry_from_eastmoney(stock_code):
    """
    从东方财富网获取个股行业信息（兼容返回格式）
    
    Args:
        stock_code: 股票代码
        
    Returns:
        dict: 包含行业信息的字典
    """
    try:
        # 直接调用东方财富 API
        industry_info = get_stock_industry_info(stock_code)
        if industry_info:
            result = {
                "行业": industry_info.get("industry", ""),
                "地区": industry_info.get("area", ""),
                "市场": industry_info.get("market", ""),
                "股票代码": industry_info.get("code", ""),
                "股票名称": industry_info.get("name", ""),
                "上市日期": industry_info.get("list_date", "")
            }
            return result
        else:
            logger.warning(f"获取股票 {stock_code} 行业信息失败：无数据")
            return None
    except Exception as e:
        logger.error(f"处理股票 {stock_code} 行业信息失败：{e}")
        return None
