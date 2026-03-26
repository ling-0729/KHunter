#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票分析模块
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from .data_fetcher import DataFetcher
from .technical_analyzer import TechnicalAnalyzer
from .fundamental_analyzer import FundamentalAnalyzer
from .fund_flow_analyzer import FundFlowAnalyzer
from .sector_analyzer import SectorAnalyzer
from .report_generator import ReportGenerator


class StockAnalyzer:
    """股票分析器"""
    
    def __init__(self):
        """初始化分析器"""
        self.data_fetcher = DataFetcher()
        self.technical_analyzer = TechnicalAnalyzer()
        self.fundamental_analyzer = FundamentalAnalyzer()
        self.fund_flow_analyzer = FundFlowAnalyzer()
        self.sector_analyzer = SectorAnalyzer()
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
            
            # 3. 技术面分析（综合分析后转换为前端期望的格式）
            raw_technical = self.technical_analyzer.comprehensive_technical_analysis(quote_data)
            technical_result = self._convert_technical_result(raw_technical)
            
            # 4. 基本面分析
            fundamental_result = self.fundamental_analyzer.analyze(stock_code)
            
            # 5. 资金流向分析
            fund_flow_result = self.fund_flow_analyzer.analyze(stock_code, period=period)
            
            # 6. 板块分析
            sector_result = self.sector_analyzer.analyze(stock_code)
            
            # 7. 整合分析结果（移除事件分析，因为是模拟数据）
            analysis_result = {
                "stock_info": stock_info,
                "technical": technical_result,
                "fundamental": fundamental_result,
                "fund_flow": fund_flow_result,
                "sector": sector_result,
                "conclusion": self._generate_conclusion(technical_result, fundamental_result)
            }
            
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

    def _convert_technical_result(self, raw):
        """将 comprehensive_technical_analysis 结果转换为前端期望的格式

        前端期望: {trend, indicators: {MACD, KDJ, RSI, Bollinger}, patterns}
        原始格式: {trend_analysis, volatility_analysis, momentum_analysis, volume_analysis, ...}

        Args:
            raw: comprehensive_technical_analysis 返回的原始结果

        Returns:
            dict: 前端期望格式的技术分析结果
        """
        # 提取趋势信息
        trend_analysis = raw.get("trend_analysis", {})
        raw_trend = trend_analysis.get("trend", "未知")

        # 映射趋势名称：comprehensive 用"上升/下降"，前端用"上升趋势/下降趋势"
        trend_map = {"上升": "上升趋势", "下降": "下降趋势", "震荡": "横盘"}
        trend = trend_map.get(raw_trend, raw_trend)

        # 从趋势强度推断 MACD 状态
        strength = trend_analysis.get("strength", 0)
        if raw_trend == "上升" and strength >= 3:
            macd_status = "多头"
        elif raw_trend == "上升":
            macd_status = "金叉"
        elif raw_trend == "下降" and strength >= 3:
            macd_status = "空头"
        elif raw_trend == "下降":
            macd_status = "死叉"
        else:
            macd_status = "未知"

        # 从动量分析中提取 RSI 水平，映射为 KDJ 状态
        momentum = raw.get("momentum_analysis", {})
        rsi_level = momentum.get("rsi_level", "中性")
        kdj_map = {"超买": "超买", "超卖": "超卖", "中性": "中性"}
        kdj_status = kdj_map.get(rsi_level, "中性")

        # 波动率分析（布林带宽度判断通道状态）
        volatility = raw.get("volatility_analysis", {})
        bb_width = volatility.get("bb_width", 0)
        vol_level = volatility.get("volatility_level", "低")
        # 高波动率 + 宽布林带 → 可能突破
        if vol_level == "高" and bb_width > 15:
            bollinger_status = "突破上轨" if raw_trend == "上升" else "突破下轨"
        else:
            bollinger_status = "通道内"

        # 技术评分转换为 RSI 数值（0-100 映射）
        technical_score = raw.get("technical_score", 50)
        rsi_value = float(technical_score)

        return {
            "trend": trend,
            "indicators": {
                "MACD": macd_status,
                "KDJ": kdj_status,
                "RSI": rsi_value,
                "Bollinger": bollinger_status
            },
            "patterns": [],
            # 保留原始详细数据
            "technical_score": technical_score,
            "technical_opinion": raw.get("technical_opinion", "中性")
        }

    
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
