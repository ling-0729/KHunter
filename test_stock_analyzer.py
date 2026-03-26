#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试股票分析模块
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from stock_analyzer import StockAnalyzer


if __name__ == "__main__":
    # 初始化股票分析器
    analyzer = StockAnalyzer()
    
    # 测试分析股票
    stock_code = "600519"  # 贵州茅台
    period = "30d"
    
    print(f"开始分析股票: {stock_code}")
    print(f"分析周期: {period}")
    print("=" * 60)
    
    # 执行分析
    analysis_result = analyzer.analyze(stock_code, period=period)
    
    if analysis_result:
        # 输出分析结果
        print("1. 股票基本信息:")
        print(f"   股票代码: {analysis_result['stock_info']['code']}")
        print(f"   股票名称: {analysis_result['stock_info']['name']}")
        print(f"   所属行业: {analysis_result['stock_info']['industry']}")
        print(f"   所属板块: {analysis_result['stock_info']['sector']}")
        print(f"   市场: {analysis_result['stock_info']['market']}")
        print()
        
        print("2. 技术面分析:")
        print(f"   技术评分: {analysis_result['technical']['technical_score']}")
        print(f"   技术意见: {analysis_result['technical']['technical_opinion']}")
        print(f"   趋势: {analysis_result['technical']['trend_analysis']['trend']}")
        print(f"   趋势强度: {analysis_result['technical']['trend_analysis']['strength']}")
        print(f"   支撑位: {analysis_result['technical']['trend_analysis']['support']}")
        print(f"   阻力位: {analysis_result['technical']['trend_analysis']['resistance']}")
        print()
        
        print("3. 基本面分析:")
        print(f"   财务数据: {analysis_result['fundamental']['financial']}")
        print(f"   估值指标: {analysis_result['fundamental']['valuation']}")
        print()
        
        print("4. 资金流向分析:")
        print(f"   主力净流入: {analysis_result['fund_flow']['flow_analysis']['main_inflow']}")
        print(f"   资金流向: {analysis_result['fund_flow']['flow_analysis']['direction']}")
        print(f"   资金流向强度: {analysis_result['fund_flow']['flow_analysis']['strength']}")
        print(f"   成交量趋势: {analysis_result['fund_flow']['volume_analysis']['trend']}")
        print(f"   成交量水平: {analysis_result['fund_flow']['volume_analysis']['level']}")
        print(f"   主力资金状态: {analysis_result['fund_flow']['main_fund_analysis']['status']}")
        print(f"   主力资金影响: {analysis_result['fund_flow']['main_fund_analysis']['influence']}")
        print()
        
        print("5. 板块分析:")
        print(f"   板块名称: {analysis_result['sector']['sector_info']['name']}")
        print(f"   板块涨跌幅: {analysis_result['sector']['sector_info']['change']}")
        print(f"   板块表现: {analysis_result['sector']['performance']['trend']}")
        print(f"   板块表现强度: {analysis_result['sector']['performance']['strength']}")
        print(f"   板块排名: {analysis_result['sector']['rank']['position']}")
        print(f"   板块排名水平: {analysis_result['sector']['rank']['level']}")
        print(f"   板块联动: {analysis_result['sector']['correlation']['level']}")
        print(f"   板块联动影响: {analysis_result['sector']['correlation']['impact']}")
        print()
        
        print("6. 事件分析:")
        if analysis_result['events']:
            for event in analysis_result['events']:
                print(f"   {event['date']} - {event['type']}: {event['content']}")
        else:
            print("   无事件数据")
        print()
        
        print("7. 分析结论:")
        print(f"   评级: {analysis_result['conclusion']['rating']}")
        print(f"   理由: {analysis_result['conclusion']['reason']}")
        print(f"   风险: {analysis_result['conclusion']['risk']}")
        print()
        
        # 测试生成报告
        print("8. 生成分析报告:")
        report_content, report_path = analyzer.generate_report(stock_code, period=period, format='html')
        print(f"   报告已生成: {report_path}")
        print()
        
        print("分析完成！")
    else:
        print("分析失败，请检查网络连接或股票代码是否正确。")
