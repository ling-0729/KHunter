import unittest
import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.event_driven import EventDrivenStrategy

class TestEventDrivenStrategy(unittest.TestCase):
    """
    测试事件驱动策略
    """
    
    def setUp(self):
        """
        初始化测试环境
        """
        self.strategy = EventDrivenStrategy()
    
    def test_initialization(self):
        """
        测试策略初始化
        """
        self.assertEqual(self.strategy.strategy_name, "EventDrivenStrategy")
        self.assertEqual(self.strategy.display_name, "事件驱动策略")
        self.assertEqual(self.strategy.description, "识别重大事件驱动的股票机会")
        self.assertEqual(self.strategy.color, "#ff6b6b")
        self.assertEqual(self.strategy.icon, "📰")
    
    def test_default_params(self):
        """
        测试默认参数
        """
        default_params = self.strategy.default_params
        self.assertIn('event_types', default_params)
        self.assertIn('min_importance', default_params)
        self.assertIn('price_change_threshold', default_params)
        self.assertIn('volume_ratio', default_params)
        self.assertIn('event_days', default_params)
        self.assertIn('hold_days', default_params)
    
    def test_announcement_classification(self):
        """
        测试公告分类
        """
        # 测试业绩超预期
        event_type, importance = self.strategy._classify_announcement("2023年业绩预增公告")
        self.assertEqual(event_type, "业绩超预期")
        self.assertEqual(importance, 3)
        
        # 测试业绩低于预期
        event_type, importance = self.strategy._classify_announcement("2023年业绩预减公告")
        self.assertEqual(event_type, "业绩低于预期")
        self.assertEqual(importance, 3)
        
        # 测试资产重组
        event_type, importance = self.strategy._classify_announcement("关于重大资产重组的公告")
        self.assertEqual(event_type, "资产重组")
        self.assertEqual(importance, 3)
        
        # 测试分红派息
        event_type, importance = self.strategy._classify_announcement("2023年度分红派息方案")
        self.assertEqual(event_type, "分红派息")
        self.assertEqual(importance, 2)
        
        # 测试政策利好
        event_type, importance = self.strategy._classify_announcement("关于获得政府补贴的公告")
        self.assertEqual(event_type, "政策利好")
        self.assertEqual(importance, 3)
        
        # 测试其他事件
        event_type, importance = self.strategy._classify_announcement("关于召开股东大会的公告")
        self.assertEqual(event_type, "其他事件")
        self.assertEqual(importance, 1)
    
    def test_news_classification(self):
        """
        测试新闻分类
        """
        # 测试业绩新闻
        event_type, importance = self.strategy._classify_news("公司业绩大幅增长", "公司2023年业绩同比增长50%")
        self.assertEqual(event_type, "业绩新闻")
        self.assertEqual(importance, 2)
        
        # 测试重组新闻
        event_type, importance = self.strategy._classify_news("公司拟进行重大资产重组", "公司计划收购某优质资产")
        self.assertEqual(event_type, "重组新闻")
        self.assertEqual(importance, 3)
        
        # 测试政策新闻
        event_type, importance = self.strategy._classify_news("政府发布利好政策", "政府出台支持行业发展的政策")
        self.assertEqual(event_type, "政策新闻")
        self.assertEqual(importance, 3)
        
        # 测试其他新闻
        event_type, importance = self.strategy._classify_news("公司召开董事会", "公司于近日召开了董事会")
        self.assertEqual(event_type, "其他新闻")
        self.assertEqual(importance, 1)
    
    def test_calculate_impact_score(self):
        """
        测试影响评分计算
        """
        # 高价格变化，高成交量变化，高重要性
        score1 = self.strategy._calculate_impact_score(0.08, 1.5, 3)
        self.assertGreater(score1, 0)
        
        # 低价格变化，低成交量变化，低重要性
        score2 = self.strategy._calculate_impact_score(0.01, 0.1, 1)
        self.assertLess(score2, score1)
    
    def test_select_stocks(self):
        """
        测试选股功能
        """
        # 使用默认参数执行选股
        result = self.strategy.select_stocks()
        
        # 检查返回结果结构
        self.assertIn('strategy', result)
        self.assertIn('display_name', result)
        self.assertIn('params', result)
        self.assertIn('stocks', result)
        self.assertIn('total', result)
        self.assertIn('date', result)
        
        # 检查策略名称
        self.assertEqual(result['strategy'], "EventDrivenStrategy")
        self.assertEqual(result['display_name'], "事件驱动策略")
        
        # 检查股票列表
        stocks = result['stocks']
        for stock in stocks:
            self.assertIn('code', stock)
            self.assertIn('name', stock)
            self.assertIn('reason', stock)
            self.assertIn('event_type', stock)
            self.assertIn('event_date', stock)
            self.assertIn('importance', stock)
            self.assertIn('impact_score', stock)
            self.assertIn('price_change', stock)
            self.assertIn('volume_change', stock)
            self.assertIn('selected_price', stock)
            self.assertIn('selected_date', stock)

if __name__ == '__main__':
    unittest.main()
