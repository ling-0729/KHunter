#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票分析主模块
"""
import os
import sys
import numpy as np
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from utils.akshare_fetcher import AkShareFetcher
from technical import TechnicalAnalyzer
from stock_analyzer.data_fetcher import DataFetcher
from stock_analyzer.fundamental_analyzer import FundamentalAnalyzer
from stock_analyzer.fund_flow_analyzer import FundFlowAnalyzer
from stock_analyzer.sector_analyzer import SectorAnalyzer
from stock_analyzer.event_analyzer import EventAnalyzer
from stock_analyzer.report_generator import ReportGenerator


class StockAnalyzer:
    """股票分析器"""
    
    def __init__(self):
        """初始化分析器"""
        self.data_fetcher = DataFetcher()
        self.technical_analyzer = TechnicalAnalyzer()
        self.fundamental_analyzer = FundamentalAnalyzer()
        self.fund_flow_analyzer = FundFlowAnalyzer()
        self.sector_analyzer = SectorAnalyzer()
        self.event_analyzer = EventAnalyzer()
        self.report_generator = ReportGenerator()
    
    def analyze(self, stock_code, period='30d'):
        """分析股票
        
        Args:
            stock_code: 股票代码
            period: 分析周期
            
        Returns:
            dict: 分析结果
        """
        try:
            # 1. 获取股票基本信息
            stock_info = self.data_fetcher.get_stock_basic(stock_code)
            
            # 2. 获取历史行情数据
            quote_data = self.data_fetcher.get_stock_quote(stock_code, period=period)
            
            # 3. 技术面分析
            technical_result = self.technical_analyzer.analyze(quote_data)
            
            # 4. 基本面分析
            fundamental_result = self.fundamental_analyzer.analyze(stock_code)
            
            # 5. 资金流向分析
            fund_flow_result = self.fund_flow_analyzer.analyze(stock_code, period=period)
            
            # 6. 板块分析
            sector_result = self.sector_analyzer.analyze(stock_code)
            
            # 7. 事件分析
            event_result = self.event_analyzer.analyze(stock_code, period=period)
            
            # 8. 整合分析结果
            analysis_result = {
                "stock_info": stock_info,
                "technical": technical_result,
                "fundamental": fundamental_result,
                "fund_flow": fund_flow_result,
                "sector": sector_result,
                "events": event_result,
                "conclusion": self._generate_conclusion(technical_result, fundamental_result)
            }
            
            # 转换numpy类型
            analysis_result = self._convert_numpy_types(analysis_result)
            
            return analysis_result
            
        except Exception as e:
            print(f"分析失败: {e}")
            return None
    
    def _generate_conclusion(self, technical_result, fundamental_result):
        """生成分析结论（仅基于技术面，不依赖实时数据）
        
        Args:
            technical_result: 技术面分析结果
            fundamental_result: 基本面分析结果（未使用）
            
        Returns:
            dict: 分析结论
        """
        # 提取技术面指标
        trend = technical_result.get("trend", "未知")
        indicators = technical_result.get("indicators", {})
        patterns = technical_result.get("patterns", [])
        
        macd = indicators.get("MACD", "未知")
        kdj = indicators.get("KDJ", "未知")
        rsi = indicators.get("RSI", 50.0)
        bollinger = indicators.get("Bollinger", "未知")
        
        # 技术面评分：根据各指标综合打分
        score = 0
        reasons = []
        risks = []
        
        # 趋势判断（权重最高）
        if trend == "上升趋势":
            score += 2
            reasons.append("趋势向上（MA5>MA20）")
        elif trend == "下降趋势":
            score -= 2
            reasons.append("趋势向下（MA5<MA20）")
        else:
            reasons.append("趋势横盘整理")
        
        # MACD 判断
        if macd in ("金叉", "多头"):
            score += 1
            reasons.append(f"MACD{macd}")
        elif macd in ("死叉", "空头"):
            score -= 1
            reasons.append(f"MACD{macd}")
        
        # KDJ 判断
        if kdj == "超买":
            score -= 1
            risks.append("KDJ超买，短期有回调风险")
        elif kdj == "超卖":
            score += 1
            reasons.append("KDJ超卖，可能存在反弹机会")
        elif kdj == "金叉":
            score += 1
            reasons.append("KDJ金叉")
        elif kdj == "死叉":
            score -= 1
            reasons.append("KDJ死叉")
        
        # RSI 判断
        if isinstance(rsi, (int, float)) and rsi != 50.0:
            if rsi > 70:
                risks.append(f"RSI={rsi}，处于超买区间")
            elif rsi < 30:
                score += 1
                reasons.append(f"RSI={rsi}，处于超卖区间")
        
        # 布林带判断
        if bollinger == "突破上轨":
            risks.append("价格突破布林带上轨，注意回调")
        elif bollinger == "突破下轨":
            reasons.append("价格突破布林带下轨，可能超跌")
        
        # K线形态
        if patterns:
            reasons.append(f"K线形态: {', '.join(patterns)}")
        
        # 综合评级
        if score >= 3:
            rating = "强烈看多"
        elif score >= 1:
            rating = "看多"
        elif score <= -3:
            rating = "强烈看空"
        elif score <= -1:
            rating = "看空"
        else:
            rating = "中性"
        
        # 默认风险提示
        if not risks:
            risks.append("市场系统性风险")
        
        return {
            "rating": rating,
            "reason": "；".join(reasons) if reasons else "技术指标数据不足",
            "risk": "；".join(risks)
        }
    
    def _convert_numpy_types(self, obj):
        """转换numpy类型为Python原生类型
        
        Args:
            obj: 要转换的对象
            
        Returns:
            转换后的对象
        """
        if isinstance(obj, dict):
            return {k: self._convert_numpy_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_numpy_types(item) for item in obj]
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return obj
    
    def generate_report(self, stock_code, period='30d', format='html'):
        """生成分析报告
        
        Args:
            stock_code: 股票代码
            period: 分析周期
            format: 报告格式
            
        Returns:
            str: 报告内容
        """
        # 分析股票
        analysis_result = self.analyze(stock_code, period=period)
        if not analysis_result:
            return "分析失败"
        
        # 生成报告
        report_content = self.report_generator.generate_report(analysis_result, format=format)
        
        # 保存报告
        report_path = self.report_generator.save_report(report_content, stock_code)
        
        return report_content, report_path


if __name__ == "__main__":
    # 测试分析器
    analyzer = StockAnalyzer()
    result = analyzer.analyze("600519", period="30d")
    if result:
        print("分析结果:")
        print(f"股票信息: {result['stock_info']}")
        print(f"技术面分析: {result['technical']}")
        print(f"分析结论: {result['conclusion']}")
        
        # 生成报告
        report_content, report_path = analyzer.generate_report("600519", period="30d")
        print(f"报告已保存至: {report_path}")
    else:
        print("分析失败")
