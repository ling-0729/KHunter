#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本面分析模块
"""
import sys
from pathlib import Path
from typing import Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.akshare_retry import akshare_call_with_retry
from .data_fetcher import DataFetcher


class FundamentalAnalyzer:
    """基本面分析器"""
    
    def __init__(self):
        """初始化基本面分析器"""
        self.data_fetcher = DataFetcher()
    
    def analyze(self, stock_code: str) -> Dict[str, Any]:
        """分析股票基本面
        
        Args:
            stock_code: 股票代码
            
        Returns:
            dict: 基本面分析结果
        """
        try:
            # 获取财务数据
            financial_data = self.data_fetcher.get_financial_data(stock_code)
            
            # 分析财务指标
            financial_analysis = self._analyze_financial(financial_data)
            
            # 分析估值指标
            valuation_analysis = self._analyze_valuation(stock_code)
            
            # 分析成长指标
            growth_analysis = self._analyze_growth(stock_code)
            
            return {
                "financial": financial_analysis,
                "valuation": valuation_analysis,
                "growth": growth_analysis
            }
            
        except Exception as e:
            print(f"基本面分析失败: {e}")
            return {
                "financial": {"revenue": 0, "profit": 0, "roe": 0, "debt_ratio": 0},
                "valuation": {"pe": 0, "pb": 0, "ps": 0},
                "growth": {"revenue_growth": 0, "profit_growth": 0}
            }
    
    def _analyze_financial(self, financial_data: Dict[str, Any]) -> Dict[str, Any]:
        """分析财务指标
        
        Args:
            financial_data: 财务数据
            
        Returns:
            dict: 财务分析结果
        """
        revenue = financial_data.get("revenue", 0)
        profit = financial_data.get("profit", 0)
        roe = financial_data.get("roe", 0)
        debt_ratio = financial_data.get("debt_ratio", 0)
        
        # 分析盈利能力
        profit_margin = profit / revenue if revenue > 0 else 0
        
        # 分析偿债能力
        debt_level = "低" if debt_ratio < 50 else "中" if debt_ratio < 70 else "高"
        
        return {
            "revenue": revenue,
            "profit": profit,
            "roe": roe,
            "debt_ratio": debt_ratio,
            "profit_margin": profit_margin,
            "debt_level": debt_level
        }
    
    def _analyze_valuation(self, stock_code: str) -> Dict[str, Any]:
        """分析估值指标
        
        Args:
            stock_code: 股票代码
            
        Returns:
            dict: 估值分析结果
        """
        try:
            import akshare as ak
            
            # 通过重试包装器获取股票实时数据
            stock_quote = akshare_call_with_retry(ak.stock_zh_a_spot_em)
            
            if stock_quote is not None and not stock_quote.empty:
                # 检查列是否存在
                code_col = "代码" if "代码" in stock_quote.columns else "code"
                price_col = "最新价" if "最新价" in stock_quote.columns else "price"
                
                stock_data = stock_quote[stock_quote[code_col] == stock_code]
                
                if not stock_data.empty:
                    # 获取当前价格
                    price = stock_data[price_col].iloc[0]
                    
                    # 简单的估值计算（实际中需要更复杂的计算）
                    pe = price / 10 if price > 0 else 0  # 模拟PE
                    pb = price / 5 if price > 0 else 0   # 模拟PB
                    ps = price / 8 if price > 0 else 0   # 模拟PS
                    
                    # 估值水平判断
                    pe_level = "低" if pe < 20 else "中" if pe < 40 else "高"
                    pb_level = "低" if pb < 2 else "中" if pb < 4 else "高"
                    
                    return {
                        "pe": pe,
                        "pb": pb,
                        "ps": ps,
                        "pe_level": pe_level,
                        "pb_level": pb_level
                    }
            
            # 如果获取失败，返回默认值
            return {"pe": 0, "pb": 0, "ps": 0, "pe_level": "未知", "pb_level": "未知"}
            
        except Exception as e:
            print(f"估值分析失败: {e}")
            # 返回默认值，而不是空数据
            return {"pe": 0, "pb": 0, "ps": 0, "pe_level": "未知", "pb_level": "未知"}
    
    def _analyze_growth(self, stock_code: str) -> Dict[str, Any]:
        """分析成长指标
        
        Args:
            stock_code: 股票代码
            
        Returns:
            dict: 成长分析结果
        """
        try:
            import akshare as ak
            
            # 通过重试包装器获取财务数据
            financial_data = akshare_call_with_retry(
                ak.stock_financial_analysis_indicator, symbol=stock_code
            )
            
            if not financial_data.empty:
                # 计算增长率（简单模拟）
                revenue_growth = 0.1  # 模拟营收增长率
                profit_growth = 0.15  # 模拟利润增长率
                
                # 成长水平判断
                growth_level = "高" if profit_growth > 0.2 else "中" if profit_growth > 0 else "低"
                
                return {
                    "revenue_growth": revenue_growth,
                    "profit_growth": profit_growth,
                    "growth_level": growth_level
                }
            
            return {"revenue_growth": 0, "profit_growth": 0, "growth_level": "未知"}
            
        except Exception as e:
            print(f"成长分析失败: {e}")
            return {"revenue_growth": 0, "profit_growth": 0, "growth_level": "未知"}


if __name__ == "__main__":
    # 测试基本面分析器
    analyzer = FundamentalAnalyzer()
    result = analyzer.analyze("600519")
    print("基本面分析结果:")
    print(f"财务分析: {result['financial']}")
    print(f"估值分析: {result['valuation']}")
    print(f"成长分析: {result['growth']}")
