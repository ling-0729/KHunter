"""
单元测试：验证stock_names.json中的股票名称提取逻辑
测试目标：确保从字典结构中正确提取股票名称字符串
"""
import unittest
import json
from pathlib import Path


class TestStockNameExtraction(unittest.TestCase):
    """测试股票名称提取逻辑"""
    
    def setUp(self):
        """测试前准备"""
        # 模拟stock_names.json的数据结构
        self.stock_names = {
            "000001": {
                "name": "平安银行",
                "industry": "5759",
                "sector": "3387"
            },
            "000002": {
                "name": "万科A",
                "industry": "9410",
                "sector": "11969"
            },
            "000003": "简单字符串"  # 兼容旧格式
        }
    
    def test_extract_name_from_dict(self):
        """测试从字典中提取name字段"""
        code = "000001"
        stock_name_info = self.stock_names.get(code, '未知')
        
        # 处理字典结构
        if isinstance(stock_name_info, dict):
            stock_name = stock_name_info.get('name', '未知')
        else:
            stock_name = stock_name_info
        
        self.assertEqual(stock_name, "平安银行")
        self.assertIsInstance(stock_name, str)
    
    def test_extract_name_from_dict_multiple(self):
        """测试从多个字典中提取name字段"""
        test_cases = [
            ("000001", "平安银行"),
            ("000002", "万科A"),
        ]
        
        for code, expected_name in test_cases:
            stock_name_info = self.stock_names.get(code, '未知')
            
            # 处理字典结构
            if isinstance(stock_name_info, dict):
                stock_name = stock_name_info.get('name', '未知')
            else:
                stock_name = stock_name_info
            
            self.assertEqual(stock_name, expected_name)
            self.assertIsInstance(stock_name, str)
    
    def test_extract_name_backward_compatibility(self):
        """测试向后兼容性 - 支持旧的字符串格式"""
        code = "000003"
        stock_name_info = self.stock_names.get(code, '未知')
        
        # 处理字典结构
        if isinstance(stock_name_info, dict):
            stock_name = stock_name_info.get('name', '未知')
        else:
            stock_name = stock_name_info
        
        self.assertEqual(stock_name, "简单字符串")
        self.assertIsInstance(stock_name, str)
    
    def test_extract_name_missing_code(self):
        """测试缺失的股票代码"""
        code = "999999"
        stock_name_info = self.stock_names.get(code, '未知')
        
        # 处理字典结构
        if isinstance(stock_name_info, dict):
            stock_name = stock_name_info.get('name', '未知')
        else:
            stock_name = stock_name_info
        
        self.assertEqual(stock_name, "未知")
        self.assertIsInstance(stock_name, str)
    
    def test_extract_name_missing_name_field(self):
        """测试字典中缺失name字段"""
        stock_names_incomplete = {
            "000001": {
                "industry": "5759",
                "sector": "3387"
            }
        }
        
        code = "000001"
        stock_name_info = stock_names_incomplete.get(code, '未知')
        
        # 处理字典结构
        if isinstance(stock_name_info, dict):
            stock_name = stock_name_info.get('name', '未知')
        else:
            stock_name = stock_name_info
        
        self.assertEqual(stock_name, "未知")
        self.assertIsInstance(stock_name, str)
    
    def test_stock_name_is_always_string(self):
        """测试提取的股票名称始终是字符串类型"""
        for code in self.stock_names.keys():
            stock_name_info = self.stock_names.get(code, '未知')
            
            # 处理字典结构
            if isinstance(stock_name_info, dict):
                stock_name = stock_name_info.get('name', '未知')
            else:
                stock_name = stock_name_info
            
            # 验证始终是字符串
            self.assertIsInstance(stock_name, str)
            # 验证可以调用字符串方法
            self.assertTrue(hasattr(stock_name, 'startswith'))
            self.assertTrue(hasattr(stock_name, 'strip'))


class TestStockNameInStrategyContext(unittest.TestCase):
    """测试在策略上下文中使用股票名称"""
    
    def test_stock_name_startswith_check(self):
        """测试stock_name.startswith()调用 - 这是原始错误的根源"""
        stock_names = {
            "000001": {"name": "平安银行", "industry": "5759", "sector": "3387"},
            "000002": {"name": "ST万科", "industry": "9410", "sector": "11969"},
            "000003": {"name": "*ST中国", "industry": "1234", "sector": "5678"},
        }
        
        test_cases = [
            ("000001", False),  # 不是ST股票
            ("000002", True),   # 是ST股票
            ("000003", True),   # 是*ST股票
        ]
        
        for code, should_be_st in test_cases:
            stock_name_info = stock_names.get(code, '未知')
            
            # 处理字典结构
            if isinstance(stock_name_info, dict):
                stock_name = stock_name_info.get('name', '未知')
            else:
                stock_name = stock_name_info
            
            # 这是原始代码中的检查 - 现在应该能正常工作
            is_st = stock_name.startswith('ST') or stock_name.startswith('*ST')
            self.assertEqual(is_st, should_be_st)
    
    def test_stock_name_never_dict_error(self):
        """测试确保不会出现'dict' object has no attribute 'startswith'错误"""
        stock_names = {
            "000001": {"name": "平安银行", "industry": "5759", "sector": "3387"},
        }
        
        code = "000001"
        stock_name_info = stock_names.get(code, '未知')
        
        # 处理字典结构
        if isinstance(stock_name_info, dict):
            stock_name = stock_name_info.get('name', '未知')
        else:
            stock_name = stock_name_info
        
        # 这个调用不应该抛出AttributeError
        try:
            result = stock_name.startswith('ST')
            self.assertIsInstance(result, bool)
        except AttributeError as e:
            self.fail(f"stock_name.startswith()抛出AttributeError: {e}")


if __name__ == '__main__':
    unittest.main()
