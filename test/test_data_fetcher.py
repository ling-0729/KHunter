"""
数据获取模块单元测试
测试资金流向数据获取和板块数据获取功能
"""
import unittest
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.capital_flow_fetcher import CapitalFlowFetcher
from data.sector_fetcher import SectorFetcher


class TestCapitalFlowFetcher(unittest.TestCase):
    """资金流向数据获取器测试"""
    
    @classmethod
    def setUpClass(cls):
        """
        测试类初始化
        创建测试数据库
        """
        cls.test_db_path = 'test_stock_selection.db'
        cls.fetcher = CapitalFlowFetcher(db_path=cls.test_db_path)
    
    @classmethod
    def tearDownClass(cls):
        """
        测试类清理
        删除测试数据库
        """
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def test_database_initialization(self):
        """
        测试数据库初始化
        """
        self.assertIsNotNone(self.fetcher)
        self.assertTrue(os.path.exists(self.test_db_path))
        print("✓ 数据库初始化测试通过")
    
    def test_get_capital_flow_rank(self):
        """
        测试获取资金流向排行数据
        """
        rank_data = self.fetcher.get_capital_flow_rank()
        
        # 检查返回结果不为空
        self.assertIsNotNone(rank_data)
        print(f"✓ 获取到 {len(rank_data)} 条资金流向排行数据")
    
    def test_save_capital_flow_rank(self):
        """
        测试保存资金流向排行数据
        """
        # 先获取数据
        rank_data = self.fetcher.get_capital_flow_rank()
        
        if not rank_data.empty:
            # 保存数据
            self.fetcher.save_capital_flow_rank(rank_data)
            print("✓ 资金流向排行数据保存测试通过")
        else:
            self.skipTest("无法获取资金流向排行数据")
    
    def test_query_capital_flow_rank(self):
        """
        测试查询资金流向排行数据
        """
        # 先保存数据
        rank_data = self.fetcher.get_capital_flow_rank()
        if not rank_data.empty:
            self.fetcher.save_capital_flow_rank(rank_data)
            
            # 查询数据
            query_result = self.fetcher.query_capital_flow_rank(top_n=10)
            
            # 检查查询结果
            self.assertIsNotNone(query_result)
            self.assertLessEqual(len(query_result), 10)
            print(f"✓ 查询到 {len(query_result)} 条资金流向排行数据")
        else:
            self.skipTest("无法获取资金流向排行数据")


class TestSectorFetcher(unittest.TestCase):
    """板块数据获取器测试"""
    
    @classmethod
    def setUpClass(cls):
        """
        测试类初始化
        创建测试数据库
        """
        cls.test_db_path = 'test_stock_selection.db'
        cls.fetcher = SectorFetcher(db_path=cls.test_db_path)
    
    @classmethod
    def tearDownClass(cls):
        """
        测试类清理
        删除测试数据库
        """
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def test_database_initialization(self):
        """
        测试数据库初始化
        """
        self.assertIsNotNone(self.fetcher)
        self.assertTrue(os.path.exists(self.test_db_path))
        print("✓ 数据库初始化测试通过")
    
    def test_get_sector_indices(self):
        """
        测试获取板块指数数据
        """
        sector_indices = self.fetcher.get_sector_indices()
        
        # 检查返回结果不为空
        self.assertIsNotNone(sector_indices)
        self.assertFalse(sector_indices.empty)
        print(f"✓ 获取到 {len(sector_indices)} 个板块")
        
        # 检查数据结构
        self.assertIn('sector_code', sector_indices.columns)
        self.assertIn('sector_name', sector_indices.columns)
        self.assertIn('sector_type', sector_indices.columns)
        
        # 检查板块类型
        sector_types = sector_indices['sector_type'].unique()
        print(f"✓ 板块类型: {list(sector_types)}")
    
    def test_save_sector_indices(self):
        """
        测试保存板块指数数据
        """
        # 先获取数据
        sector_indices = self.fetcher.get_sector_indices()
        
        if not sector_indices.empty:
            # 保存数据
            self.fetcher.save_sector_indices(sector_indices)
            print("✓ 板块指数数据保存测试通过")
        else:
            self.skipTest("无法获取板块指数数据")
    
    def test_get_sector_stocks(self):
        """
        测试获取板块成分股数据
        """
        # 先获取板块列表
        sector_indices = self.fetcher.get_sector_indices()
        
        if not sector_indices.empty:
            # 获取第一个板块的成分股
            sector_code = sector_indices.iloc[0]['sector_code']
            sector_name = sector_indices.iloc[0]['sector_name']
            
            sector_stocks = self.fetcher.get_sector_stocks(sector_code)
            
            # 检查返回结果不为空
            self.assertIsNotNone(sector_stocks)
            print(f"✓ 获取到板块 {sector_name} ({sector_code}) 的成分股，共 {len(sector_stocks)} 只股票")
        else:
            self.skipTest("无法获取板块指数数据")
    
    def test_save_sector_stocks(self):
        """
        测试保存板块成分股数据
        """
        # 先获取板块列表
        sector_indices = self.fetcher.get_sector_indices()
        
        if not sector_indices.empty:
            # 获取第一个板块的成分股
            sector_code = sector_indices.iloc[0]['sector_code']
            
            sector_stocks = self.fetcher.get_sector_stocks(sector_code)
            
            if not sector_stocks.empty:
                # 保存数据
                self.fetcher.save_sector_stocks(sector_code, sector_stocks)
                print("✓ 板块成分股数据保存测试通过")
            else:
                self.skipTest("无法获取板块成分股数据")
        else:
            self.skipTest("无法获取板块指数数据")
    
    def test_query_sector_indices(self):
        """
        测试查询板块指数数据
        """
        # 先保存数据
        sector_indices = self.fetcher.get_sector_indices()
        if not sector_indices.empty:
            self.fetcher.save_sector_indices(sector_indices)
            
            # 查询数据
            query_result = self.fetcher.query_sector_indices(sector_type='行业')
            
            # 检查查询结果
            self.assertIsNotNone(query_result)
            self.assertFalse(query_result.empty)
            print(f"✓ 查询到 {len(query_result)} 个行业板块")
        else:
            self.skipTest("无法获取板块指数数据")
    
    def test_query_sector_stocks(self):
        """
        测试查询板块成分股数据
        """
        # 先获取板块列表
        sector_indices = self.fetcher.get_sector_indices()
        
        if not sector_indices.empty:
            # 获取第一个板块的成分股
            sector_code = sector_indices.iloc[0]['sector_code']
            
            sector_stocks = self.fetcher.get_sector_stocks(sector_code)
            
            if not sector_stocks.empty:
                # 保存数据
                self.fetcher.save_sector_stocks(sector_code, sector_stocks)
                
                # 查询数据
                query_result = self.fetcher.query_sector_stocks(sector_code)
                
                # 检查查询结果
                self.assertIsNotNone(query_result)
                self.assertFalse(query_result.empty)
                print(f"✓ 查询到板块 {sector_code} 的成分股，共 {len(query_result)} 只股票")
            else:
                self.skipTest("无法获取板块成分股数据")
        else:
            self.skipTest("无法获取板块指数数据")


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)
