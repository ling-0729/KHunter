#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析结论生成逻辑的单元测试
验证 _generate_conclusion 仅基于技术面指标生成结论
"""
import sys
import unittest
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from stock_analyzer import StockAnalyzer


class TestConclusionGeneration(unittest.TestCase):
    """测试结论生成逻辑"""

    def setUp(self):
        """初始化分析器"""
        self.analyzer = StockAnalyzer()

    def test_uptrend_with_bullish_indicators(self):
        """上升趋势 + MACD多头 + KDJ金叉 → 应为看多"""
        technical = {
            "trend": "上升趋势",
            "indicators": {"MACD": "多头", "KDJ": "金叉", "RSI": 55.0, "Bollinger": "通道内"},
            "patterns": []
        }
        # fundamental 传空，不应影响结论
        result = self.analyzer._generate_conclusion(technical, {})

        # 评级应为看多或强烈看多
        self.assertIn(result["rating"], ["看多", "强烈看多"])
        # 原因中应包含趋势和指标信息
        self.assertIn("趋势向上", result["reason"])
        self.assertIn("MACD", result["reason"])

    def test_downtrend_with_bearish_indicators(self):
        """下降趋势 + MACD空头 + KDJ死叉 → 应为看空"""
        technical = {
            "trend": "下降趋势",
            "indicators": {"MACD": "空头", "KDJ": "死叉", "RSI": 45.0, "Bollinger": "通道内"},
            "patterns": []
        }
        result = self.analyzer._generate_conclusion(technical, {})

        self.assertIn(result["rating"], ["看空", "强烈看空"])
        self.assertIn("趋势向下", result["reason"])

    def test_neutral_mixed_signals(self):
        """横盘 + 混合信号 → 应为中性"""
        technical = {
            "trend": "横盘",
            "indicators": {"MACD": "多头", "KDJ": "死叉", "RSI": 50.0, "Bollinger": "通道内"},
            "patterns": []
        }
        result = self.analyzer._generate_conclusion(technical, {})

        # MACD多头(+1) + KDJ死叉(-1) + 横盘(0) = 0 → 中性
        self.assertEqual(result["rating"], "中性")

    def test_overbought_risk(self):
        """KDJ超买时应在风险中提示"""
        technical = {
            "trend": "上升趋势",
            "indicators": {"MACD": "多头", "KDJ": "超买", "RSI": 75.0, "Bollinger": "通道内"},
            "patterns": []
        }
        result = self.analyzer._generate_conclusion(technical, {})

        # 风险中应包含超买提示
        self.assertIn("超买", result["risk"])
        # RSI超买也应提示
        self.assertIn("RSI", result["risk"])

    def test_oversold_opportunity(self):
        """KDJ超卖 + RSI低 → 应在原因中提示反弹机会"""
        technical = {
            "trend": "下降趋势",
            "indicators": {"MACD": "空头", "KDJ": "超卖", "RSI": 25.0, "Bollinger": "突破下轨"},
            "patterns": []
        }
        result = self.analyzer._generate_conclusion(technical, {})

        # 原因中应包含超卖/反弹信息
        self.assertIn("超卖", result["reason"])

    def test_fundamental_not_affect_conclusion(self):
        """基本面数据不应影响结论"""
        technical = {
            "trend": "上升趋势",
            "indicators": {"MACD": "金叉", "KDJ": "金叉", "RSI": 60.0, "Bollinger": "通道内"},
            "patterns": []
        }
        # 传入不同的基本面数据，结论应一致
        result1 = self.analyzer._generate_conclusion(technical, {})
        result2 = self.analyzer._generate_conclusion(technical, {"financial": {"profit": 100}})
        result3 = self.analyzer._generate_conclusion(technical, {"financial": {"profit": -50}})

        self.assertEqual(result1["rating"], result2["rating"])
        self.assertEqual(result1["rating"], result3["rating"])
        self.assertEqual(result1["reason"], result2["reason"])

    def test_kline_patterns_in_reason(self):
        """K线形态应出现在结论原因中"""
        technical = {
            "trend": "上升趋势",
            "indicators": {"MACD": "多头", "KDJ": "金叉"},
            "patterns": ["红三兵"]
        }
        result = self.analyzer._generate_conclusion(technical, {})

        self.assertIn("红三兵", result["reason"])

    def test_empty_technical_result(self):
        """技术面数据为空时应返回有效结论"""
        technical = {
            "trend": "未知",
            "indicators": {},
            "patterns": []
        }
        result = self.analyzer._generate_conclusion(technical, {})

        # 应返回完整结构
        self.assertIn("rating", result)
        self.assertIn("reason", result)
        self.assertIn("risk", result)
        # 不应为空字符串
        self.assertTrue(len(result["rating"]) > 0)
        self.assertTrue(len(result["risk"]) > 0)

    def test_conclusion_structure(self):
        """结论应包含 rating, reason, risk 三个字段"""
        technical = {
            "trend": "上升趋势",
            "indicators": {"MACD": "多头"},
            "patterns": []
        }
        result = self.analyzer._generate_conclusion(technical, {})

        self.assertIsInstance(result, dict)
        self.assertIn("rating", result)
        self.assertIn("reason", result)
        self.assertIn("risk", result)
        # 所有值应为字符串
        self.assertIsInstance(result["rating"], str)
        self.assertIsInstance(result["reason"], str)
        self.assertIsInstance(result["risk"], str)

    def test_strong_bullish(self):
        """多个看多信号叠加 → 强烈看多"""
        technical = {
            "trend": "上升趋势",
            "indicators": {"MACD": "金叉", "KDJ": "超卖", "RSI": 25.0, "Bollinger": "突破下轨"},
            "patterns": []
        }
        result = self.analyzer._generate_conclusion(technical, {})

        # 上升趋势(+2) + MACD金叉(+1) + KDJ超卖(+1) + RSI超卖(+1) = 5 → 强烈看多
        self.assertEqual(result["rating"], "强烈看多")


if __name__ == '__main__':
    unittest.main()
