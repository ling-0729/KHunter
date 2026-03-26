#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金流向分析模块
"""
from typing import Dict, Any
from .data_fetcher import DataFetcher


class FundFlowAnalyzer:
    """资金流向分析器"""
    
    def __init__(self):
        """初始化资金流向分析器"""
        self.data_fetcher = DataFetcher()
    
    def analyze(self, stock_code: str, period: str = '30d') -> Dict[str, Any]:
        """分析股票资金流向
        
        Args:
            stock_code: 股票代码
            period: 分析周期
            
        Returns:
            dict: 资金流向分析结果
        """
        try:
            # 获取资金流向数据
            fund_flow_data = self.data_fetcher.get_fund_flow(stock_code)
            
            # 分析资金流向
            flow_analysis = self._analyze_flow(fund_flow_data)
            
            # 分析成交量变化
            volume_analysis = self._analyze_volume(stock_code, period)
            
            # 分析主力资金
            main_fund_analysis = self._analyze_main_fund(stock_code)
            
            return {
                "flow_analysis": flow_analysis,
                "volume_analysis": volume_analysis,
                "main_fund_analysis": main_fund_analysis
            }
            
        except Exception as e:
            print(f"资金流向分析失败: {e}")
            return {
                "flow_analysis": {"direction": "未知", "strength": "未知"},
                "volume_analysis": {"trend": "稳定", "level": "正常"},
                "main_fund_analysis": {"status": "未知", "influence": "未知"}
            }
    
    def _analyze_flow(self, fund_flow_data: Dict[str, Any]) -> Dict[str, Any]:
        """分析资金流向
        
        Args:
            fund_flow_data: 资金流向数据
            
        Returns:
            dict: 资金流向分析结果
        """
        main_inflow = fund_flow_data.get("main_inflow", 0)
        
        # 判断资金流向方向
        direction = "流入" if main_inflow > 0 else "流出" if main_inflow < 0 else "平衡"
        
        # 判断资金流向强度
        abs_inflow = abs(main_inflow)
        if abs_inflow > 100000000:
            strength = "强"
        elif abs_inflow > 10000000:
            strength = "中"
        else:
            strength = "弱"
        
        return {
            "direction": direction,
            "strength": strength,
            "main_inflow": main_inflow
        }
    
    def _analyze_volume(self, stock_code: str, period: str) -> Dict[str, Any]:
        """分析成交量变化
        
        Args:
            stock_code: 股票代码
            period: 分析周期
            
        Returns:
            dict: 成交量分析结果
        """
        try:
            # 获取历史行情数据
            quote_data = self.data_fetcher.get_stock_quote(stock_code, period=period)
            
            if not quote_data.empty and 'volume' in quote_data.columns:
                # 计算成交量平均值
                avg_volume = quote_data['volume'].mean()
                
                # 计算最近成交量
                recent_volume = quote_data['volume'].iloc[-1] if len(quote_data) > 0 else 0
                
                # 判断成交量趋势
                if recent_volume > avg_volume * 1.5:
                    trend = "放量"
                    level = "高"
                elif recent_volume < avg_volume * 0.5:
                    trend = "缩量"
                    level = "低"
                else:
                    trend = "稳定"
                    level = "正常"
                
                return {
                    "trend": trend,
                    "level": level,
                    "avg_volume": float(avg_volume),
                    "recent_volume": float(recent_volume)
                }
            
            # 如果获取失败，返回默认值
            return {"trend": "稳定", "level": "正常", "avg_volume": 0, "recent_volume": 0}
            
        except Exception as e:
            print(f"成交量分析失败: {e}")
            # 返回默认值，而不是空数据
            return {"trend": "稳定", "level": "正常", "avg_volume": 0, "recent_volume": 0}
    
    def _analyze_main_fund(self, stock_code: str) -> Dict[str, Any]:
        """分析主力资金
        
        Args:
            stock_code: 股票代码
            
        Returns:
            dict: 主力资金分析结果
        """
        try:
            # 获取资金流向数据
            fund_flow_data = self.data_fetcher.get_fund_flow(stock_code)
            main_inflow = fund_flow_data.get("main_inflow", 0)
            
            # 判断主力资金状态
            if main_inflow > 0:
                status = "买入"
                influence = "正面"
            elif main_inflow < 0:
                status = "卖出"
                influence = "负面"
            else:
                status = "观望"
                influence = "中性"
            
            return {
                "status": status,
                "influence": influence,
                "main_inflow": main_inflow
            }
            
        except Exception as e:
            print(f"主力资金分析失败: {e}")
            return {"status": "未知", "influence": "未知", "main_inflow": 0}


if __name__ == "__main__":
    # 测试资金流向分析器
    analyzer = FundFlowAnalyzer()
    result = analyzer.analyze("600519", period="30d")
    print("资金流向分析结果:")
    print(f"资金流向分析: {result['flow_analysis']}")
    print(f"成交量分析: {result['volume_analysis']}")
    print(f"主力资金分析: {result['main_fund_analysis']}")
