#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成模块
"""
import os
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path


class ReportGenerator:
    """报告生成器"""
    
    def __init__(self):
        """初始化报告生成器"""
        # 创建报告存储目录
        self.report_dir = Path(__file__).parent.parent / "reports"
        self.report_dir.mkdir(exist_ok=True)
    
    def generate_report(self, analysis_result: Dict[str, Any], format: str = 'html') -> str:
        """生成分析报告
        
        Args:
            analysis_result: 分析结果
            format: 报告格式
            
        Returns:
            str: 报告内容
        """
        if format == 'html':
            return self._generate_html_report(analysis_result)
        else:
            return "暂不支持的报告格式"
    
    def _generate_html_report(self, analysis_result: Dict[str, Any]) -> str:
        """生成HTML格式报告
        
        Args:
            analysis_result: 分析结果
            
        Returns:
            str: HTML报告内容
        """
        # 获取分析结果
        stock_info = analysis_result.get("stock_info", {})
        technical = analysis_result.get("technical", {})
        fundamental = analysis_result.get("fundamental", {})
        fund_flow = analysis_result.get("fund_flow", {})
        sector = analysis_result.get("sector", {})
        events = analysis_result.get("events", [])
        conclusion = analysis_result.get("conclusion", {})
        
        # 生成HTML报告
        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{stock_info.get('name', '股票')}分析报告</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1, h2, h3 {{
            color: #333;
        }}
        .header {{
            background-color: #f5f5f5;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .section {{
            background-color: #f9f9f9;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .info-item {{
            margin-bottom: 10px;
        }}
        .info-label {{
            font-weight: bold;
            display: inline-block;
            width: 100px;
        }}
        .event {{
            background-color: #fff;
            padding: 10px;
            border-left: 4px solid #4CAF50;
            margin-bottom: 10px;
        }}
        .event.negative {{
            border-left-color: #f44336;
        }}
        .conclusion {{
            background-color: #e3f2fd;
            padding: 20px;
            border-radius: 5px;
            margin-top: 20px;
        }}
        .rating {{"""
        
        # 根据评级设置不同颜色
        rating_color = "#4CAF50"  # 买入 - 绿色
        if conclusion.get("rating") == "卖出":
            rating_color = "#f44336"  # 卖出 - 红色
        elif conclusion.get("rating") == "中性":
            rating_color = "#ff9800"  # 中性 - 橙色
        
        html += f"""
            font-size: 18px;
            font-weight: bold;
            color: {rating_color};
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }}
        th, td {{
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #f2f2f2;
        }}
        .chart-container {{
            width: 100%;
            height: 300px;
            margin: 20px 0;
        }}
    </style>
    <!-- ECharts -->
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{stock_info.get('name', '股票')}({stock_info.get('code', '')}) 分析报告</h1>
            <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>所属行业: {stock_info.get('industry', '未知')}</p>
            <p>所属板块: {stock_info.get('sector', '未知')}</p>
        </div>
        
        <!-- 技术面分析 -->
        <div class="section">
            <h2>技术面分析</h2>
            <div class="info-item">
                <span class="info-label">趋势:</span> {technical.get('trend', '未知')}
            </div>
            <div class="info-item">
                <span class="info-label">指标:</span>
                <ul>
                    {self._generate_technical_indicators(technical.get('indicators', {}))}
                </ul>
            </div>
            <div class="info-item">
                <span class="info-label">形态:</span> {', '.join(technical.get('patterns', [])) or '无'}
            </div>
            <div class="chart-container" id="technical-chart"></div>
        </div>
        
        <!-- 基本面分析 -->
        <div class="section">
            <h2>基本面分析</h2>
            <h3>财务指标</h3>
            <table>
                <tr>
                    <th>指标</th>
                    <th>数值</th>
                </tr>
                <tr>
                    <td>营业收入</td>
                    <td>{fundamental.get('financial', {}).get('revenue', 0):,.2f}</td>
                </tr>
                <tr>
                    <td>净利润</td>
                    <td>{fundamental.get('financial', {}).get('profit', 0):,.2f}</td>
                </tr>
                <tr>
                    <td>净资产收益率</td>
                    <td>{fundamental.get('financial', {}).get('roe', 0):.2f}%</td>
                </tr>
                <tr>
                    <td>资产负债率</td>
                    <td>{fundamental.get('financial', {}).get('debt_ratio', 0):.2f}%</td>
                </tr>
                <tr>
                    <td>利润率</td>
                    <td>{fundamental.get('financial', {}).get('profit_margin', 0):.2f}%</td>
                </tr>
            </table>
            
            <h3>估值指标</h3>
            <table>
                <tr>
                    <th>指标</th>
                    <th>数值</th>
                    <th>水平</th>
                </tr>
                <tr>
                    <td>市盈率(PE)</td>
                    <td>{fundamental.get('valuation', {}).get('pe', 0):.2f}</td>
                    <td>{fundamental.get('valuation', {}).get('pe_level', '未知')}</td>
                </tr>
                <tr>
                    <td>市净率(PB)</td>
                    <td>{fundamental.get('valuation', {}).get('pb', 0):.2f}</td>
                    <td>{fundamental.get('valuation', {}).get('pb_level', '未知')}</td>
                </tr>
                <tr>
                    <td>市销率(PS)</td>
                    <td>{fundamental.get('valuation', {}).get('ps', 0):.2f}</td>
                    <td>-</td>
                </tr>
            </table>
            
            <h3>成长指标</h3>
            <table>
                <tr>
                    <th>指标</th>
                    <th>数值</th>
                    <th>水平</th>
                </tr>
                <tr>
                    <td>营收增长率</td>
                    <td>{fundamental.get('growth', {}).get('revenue_growth', 0):.2f}%</td>
                    <td rowspan="2">{fundamental.get('growth', {}).get('growth_level', '未知')}</td>
                </tr>
                <tr>
                    <td>利润增长率</td>
                    <td>{fundamental.get('growth', {}).get('profit_growth', 0):.2f}%</td>
                </tr>
            </table>
        </div>
        
        <!-- 资金流向分析 -->
        <div class="section">
            <h2>资金流向分析</h2>
            <div class="info-item">
                <span class="info-label">资金流向:</span> {fund_flow.get('flow_analysis', {}).get('direction', '未知')} ({fund_flow.get('flow_analysis', {}).get('strength', '未知')})
            </div>
            <div class="info-item">
                <span class="info-label">主力净流入:</span> {fund_flow.get('flow_analysis', {}).get('main_inflow', 0):,.2f}
            </div>
            <div class="info-item">
                <span class="info-label">成交量趋势:</span> {fund_flow.get('volume_analysis', {}).get('trend', '稳定')} ({fund_flow.get('volume_analysis', {}).get('level', '正常')})
            </div>
            <div class="info-item">
                <span class="info-label">主力资金状态:</span> {fund_flow.get('main_fund_analysis', {}).get('status', '未知')} ({fund_flow.get('main_fund_analysis', {}).get('influence', '未知')})
            </div>
        </div>
        
        <!-- 板块分析 -->
        <div class="section">
            <h2>板块分析</h2>
            <div class="info-item">
                <span class="info-label">板块名称:</span> {sector.get('sector_info', {}).get('name', '未知')}
            </div>
            <div class="info-item">
                <span class="info-label">板块涨跌幅:</span> {sector.get('sector_info', {}).get('change', 0):.2f}%
            </div>
            <div class="info-item">
                <span class="info-label">板块表现:</span> {sector.get('performance', {}).get('trend', '稳定')} ({sector.get('performance', {}).get('strength', '中等')})
            </div>
            <div class="info-item">
                <span class="info-label">板块排名:</span> 第{sector.get('rank', {}).get('position', 0)}位 ({sector.get('rank', {}).get('level', '中等')})
            </div>
            <div class="info-item">
                <span class="info-label">板块联动:</span> {sector.get('correlation', {}).get('level', '中等')} ({sector.get('correlation', {}).get('impact', '中性')})
            </div>
        </div>
        
        <!-- 事件分析 -->
        <div class="section">
            <h2>事件分析</h2>
            {self._generate_events_html(events)}
        </div>
        
        <!-- 分析结论 -->
        <div class="conclusion">
            <h2>分析结论</h2>
            <div class="info-item">
                <span class="info-label">评级:</span> <span class="rating">{conclusion.get('rating', '中性')}</span>
            </div>
            <div class="info-item">
                <span class="info-label">理由:</span> {conclusion.get('reason', '无')}
            </div>
            <div class="info-item">
                <span class="info-label">风险:</span> {conclusion.get('risk', '无')}
            </div>
        </div>
    </div>
    
    <script>
        // 技术面分析图表
        var technicalChart = echarts.init(document.getElementById('technical-chart'));
        var technicalOption = {{
            title: {{
                text: '技术指标走势',
                left: 'center'
            }},
            tooltip: {{
                trigger: 'axis'
            }},
            legend: {{
                data: ['MACD', 'KDJ', 'RSI'],
                bottom: 0
            }},
            grid: {{
                left: '3%',
                right: '4%',
                bottom: '15%',
                containLabel: true
            }},
            xAxis: {{
                type: 'category',
                boundaryGap: false,
                data: ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']
            }},
            yAxis: {{
                type: 'value'
            }},
            series: [
                {{
                    name: 'MACD',
                    type: 'line',
                    data: [0.5, 0.8, 1.2, 0.9, 1.5, 2.0, 1.8, 2.5, 3.0, 2.8, 3.5, 4.0]
                }},
                {{
                    name: 'KDJ',
                    type: 'line',
                    data: [20, 30, 40, 50, 60, 70, 65, 75, 80, 78, 85, 90]
                }},
                {{
                    name: 'RSI',
                    type: 'line',
                    data: [30, 40, 50, 45, 55, 65, 60, 70, 75, 72, 80, 85]
                }}
            ]
        }};
        technicalChart.setOption(technicalOption);
        
        // 响应式调整
        window.addEventListener('resize', function() {{
            technicalChart.resize();
        }});
    </script>
</body>
</html>
"""
        
        return html
    
    def _generate_technical_indicators(self, indicators: Dict[str, Any]) -> str:
        """生成技术指标HTML
        
        Args:
            indicators: 技术指标
            
        Returns:
            str: HTML字符串
        """
        if not indicators:
            return "<li>无</li>"
        
        html = ""
        for indicator, value in indicators.items():
            html += f"<li>{indicator}: {value}</li>"
        
        return html
    
    def _generate_events_html(self, events: List[Dict[str, Any]]) -> str:
        """生成事件HTML
        
        Args:
            events: 事件列表
            
        Returns:
            str: HTML字符串
        """
        if not events:
            return "<p>无相关事件</p>"
        
        html = ""
        for event in events:
            event_class = "event"
            if event.get("impact_level") == "负面":
                event_class += " negative"
            
            html += f"""
            <div class="{event_class}">
                <h4>{event.get('type', '事件')}: {event.get('content', '')}</h4>
                <p>日期: {event.get('date', '')}</p>
                <p>影响程度: {event.get('impact_level', '中性')}</p>
                <p>影响持续时间: {event.get('impact_duration', '短期')}</p>
                <p>分析: {event.get('analysis', '')}</p>
            </div>
            """
        
        return html
    
    def save_report(self, report_content: str, stock_code: str) -> str:
        """保存报告
        
        Args:
            report_content: 报告内容
            stock_code: 股票代码
            
        Returns:
            str: 报告保存路径
        """
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{stock_code}_{timestamp}.html"
        file_path = self.report_dir / filename
        
        # 保存报告
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        return str(file_path)


if __name__ == "__main__":
    # 测试报告生成器
    from stock_analyzer import StockAnalyzer
    
    analyzer = StockAnalyzer()
    result = analyzer.analyze("600519", period="30d")
    
    if result:
        generator = ReportGenerator()
        report_content, report_path = generator.generate_report(result), generator.save_report(generator.generate_report(result), "600519")
        print(f"报告已保存至: {report_path}")
    else:
        print("分析失败，无法生成报告")
