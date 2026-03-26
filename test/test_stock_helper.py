# 股票辅助模块单元测试
# 测试 stock_helper.py 中的股票信息查询和选股历史验证功能

import pytest
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from trading.stock_helper import StockHelper


class TestStockHelper:
    """股票辅助类测试"""

    @pytest.fixture
    def temp_stock_names_file(self, tmp_path):
        # 创建临时股票名称文件
        stock_names = {
            "000001": "平安银行",
            "000002": "万科A",
            "600000": "浦发银行",
            "300001": "特锐德"
        }
        stock_file = tmp_path / "stock_names.json"
        with open(stock_file, 'w', encoding='utf-8') as f:
            json.dump(stock_names, f, ensure_ascii=False)
        return stock_file

    @pytest.fixture
    def temp_selection_db(self, tmp_path):
        # 创建临时选股历史数据库
        db_file = tmp_path / "stock_selection.db"
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        
        # 创建表（使用实际的表结构）
        cursor.execute('''
            CREATE TABLE stock_selection_record (
                id INTEGER PRIMARY KEY,
                strategy_name VARCHAR(100) NOT NULL,
                stock_code VARCHAR(20) NOT NULL,
                stock_name VARCHAR(50) NOT NULL,
                industry VARCHAR(50),
                sector VARCHAR(50),
                selection_date DATE NOT NULL,
                selection_time DATETIME NOT NULL,
                selection_price DECIMAL(10,2) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # 插入测试数据
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=31)
        
        test_data = [
            ('B1PatternMatch', '000001', '平安银行', None, None, today.isoformat(), datetime.now().isoformat(), 10.5),
            ('BowlReboundStrategy', '000002', '万科A', None, None, yesterday.isoformat(), datetime.now().isoformat(), 10.5),
            ('B1PatternMatch', '600000', '浦发银行', None, None, week_ago.isoformat(), datetime.now().isoformat(), 10.5),
            ('BowlReboundStrategy', '600000', '浦发银行', None, None, week_ago.isoformat(), datetime.now().isoformat(), 10.5),
            ('B1PatternMatch', '300001', '特锐德', None, None, month_ago.isoformat(), datetime.now().isoformat(), 10.5),
            ('B1PatternMatch', '999999', '不存在', None, None, (today - timedelta(days=40)).isoformat(), datetime.now().isoformat(), 10.5),
        ]
        
        for strategy, code, name, industry, sector, date, time, price in test_data:
            cursor.execute(
                '''INSERT INTO stock_selection_record 
                   (strategy_name, stock_code, stock_name, industry, sector, selection_date, selection_time, selection_price) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (strategy, code, name, industry, sector, date, time, price)
            )
        
        conn.commit()
        conn.close()
        return db_file

    # ==================== get_stock_info 测试 ====================

    def test_get_stock_info_success(self, temp_stock_names_file):
        # 测试成功获取股票信息
        with patch('trading.stock_helper.STOCK_NAMES_FILE', temp_stock_names_file):
            result = StockHelper.get_stock_info('000001')
            assert result is not None
            assert result['code'] == '000001'
            assert result['name'] == '平安银行'

    def test_get_stock_info_not_found(self, temp_stock_names_file):
        # 测试股票不存在
        with patch('trading.stock_helper.STOCK_NAMES_FILE', temp_stock_names_file):
            result = StockHelper.get_stock_info('999999')
            assert result is None

    def test_get_stock_info_invalid_code_format(self, temp_stock_names_file):
        # 测试无效的代码格式（不是6位数字）
        with patch('trading.stock_helper.STOCK_NAMES_FILE', temp_stock_names_file):
            # 代码太短
            result = StockHelper.get_stock_info('00001')
            assert result is None
            
            # 代码太长
            result = StockHelper.get_stock_info('0000001')
            assert result is None
            
            # 包含非数字字符
            result = StockHelper.get_stock_info('00000A')
            assert result is None

    def test_get_stock_info_empty_code(self, temp_stock_names_file):
        # 测试空代码
        with patch('trading.stock_helper.STOCK_NAMES_FILE', temp_stock_names_file):
            result = StockHelper.get_stock_info('')
            assert result is None

    def test_get_stock_info_file_not_exists(self):
        # 测试文件不存在
        with patch('trading.stock_helper.STOCK_NAMES_FILE', Path('/nonexistent/path/stock_names.json')):
            result = StockHelper.get_stock_info('000001')
            assert result is None

    # ==================== check_selection_history 测试 ====================

    def test_check_selection_history_found_today(self, temp_selection_db):
        # 测试找到今天选中的股票
        with patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.check_selection_history('000001', days=30)
            assert result['in_history'] is True
            assert result['days_ago'] == 0
            assert '今天选中' in result['message']
            assert 'B1PatternMatch' in result['selection_strategies']

    def test_check_selection_history_found_yesterday(self, temp_selection_db):
        # 测试找到昨天选中的股票
        with patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.check_selection_history('000002', days=30)
            assert result['in_history'] is True
            assert result['days_ago'] == 1
            assert '昨天选中' in result['message']

    def test_check_selection_history_found_days_ago(self, temp_selection_db):
        # 测试找到几天前选中的股票
        with patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.check_selection_history('600000', days=30)
            assert result['in_history'] is True
            assert result['days_ago'] == 7
            assert '7天前选中' in result['message']
            assert len(result['selection_strategies']) == 2

    def test_check_selection_history_outside_range(self, temp_selection_db):
        # 测试超出时间范围的股票
        with patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.check_selection_history('999999', days=30)
            assert result['in_history'] is False
            assert result['last_selection_date'] is None
            assert result['days_ago'] is None

    def test_check_selection_history_not_found(self, temp_selection_db):
        # 测试不存在的股票
        with patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.check_selection_history('888888', days=30)
            assert result['in_history'] is False
            assert result['last_selection_date'] is None

    def test_check_selection_history_invalid_code(self, temp_selection_db):
        # 测试无效的代码格式
        with patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.check_selection_history('00001', days=30)
            assert result['in_history'] is False
            assert '格式错误' in result['message']

    def test_check_selection_history_db_not_exists(self):
        # 测试数据库不存在
        with patch('trading.stock_helper.SELECTION_DB_PATH', Path('/nonexistent/path/stock_selection.db')):
            result = StockHelper.check_selection_history('000001', days=30)
            assert result['in_history'] is False
            assert '数据库不存在' in result['message']

    def test_check_selection_history_custom_days(self, temp_selection_db):
        # 测试自定义天数范围
        with patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            # 30天范围内
            result = StockHelper.check_selection_history('600000', days=30)
            assert result['in_history'] is True
            
            # 5天范围内（应该找不到）
            result = StockHelper.check_selection_history('600000', days=5)
            assert result['in_history'] is False

    # ==================== get_stock_full_info 测试 ====================

    def test_get_stock_full_info_success(self, temp_stock_names_file, temp_selection_db):
        # 测试成功获取完整股票信息
        with patch('trading.stock_helper.STOCK_NAMES_FILE', temp_stock_names_file), \
             patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.get_stock_full_info('000001', days=30)
            assert result['success'] is True
            assert result['data']['code'] == '000001'
            assert result['data']['name'] == '平安银行'
            assert result['data']['in_selection_history'] is True
            assert result['data']['days_ago'] == 0

    def test_get_stock_full_info_not_in_selection(self, temp_stock_names_file, temp_selection_db):
        # 测试股票存在但不在选股历史中
        with patch('trading.stock_helper.STOCK_NAMES_FILE', temp_stock_names_file), \
             patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.get_stock_full_info('300001', days=5)
            assert result['success'] is True
            assert result['data']['name'] == '特锐德'
            assert result['data']['in_selection_history'] is False

    def test_get_stock_full_info_stock_not_found(self, temp_stock_names_file, temp_selection_db):
        # 测试股票不存在
        with patch('trading.stock_helper.STOCK_NAMES_FILE', temp_stock_names_file), \
             patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.get_stock_full_info('999999', days=30)
            assert result['success'] is False
            assert result['data'] is None
            assert '股票不存在' in result['message']

    def test_get_stock_full_info_invalid_code(self, temp_stock_names_file, temp_selection_db):
        # 测试无效的代码格式
        with patch('trading.stock_helper.STOCK_NAMES_FILE', temp_stock_names_file), \
             patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.get_stock_full_info('00001', days=30)
            assert result['success'] is False

    def test_get_stock_full_info_multiple_strategies(self, temp_stock_names_file, temp_selection_db):
        # 测试多个策略选中的股票
        with patch('trading.stock_helper.STOCK_NAMES_FILE', temp_stock_names_file), \
             patch('trading.stock_helper.SELECTION_DB_PATH', temp_selection_db):
            result = StockHelper.get_stock_full_info('600000', days=30)
            assert result['success'] is True
            assert len(result['data']['selection_strategies']) == 2
            assert 'B1PatternMatch' in result['data']['selection_strategies']
            assert 'BowlReboundStrategy' in result['data']['selection_strategies']

    # ==================== 边界情况测试 ====================

    def test_stock_info_with_dict_format(self, tmp_path):
        # 测试股票名称为字典格式的情况
        stock_names = {
            "000001": {"name": "平安银行", "market": "深圳"}
        }
        stock_file = tmp_path / "stock_names.json"
        with open(stock_file, 'w', encoding='utf-8') as f:
            json.dump(stock_names, f, ensure_ascii=False)
        
        with patch('trading.stock_helper.STOCK_NAMES_FILE', stock_file):
            result = StockHelper.get_stock_info('000001')
            assert result is not None
            assert result['name'] == '平安银行'

    def test_check_selection_history_with_null_strategies(self, tmp_path):
        # 测试策略字段为空的情况
        db_file = tmp_path / "stock_selection.db"
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE stock_selection_record (
                id INTEGER PRIMARY KEY,
                strategy_name VARCHAR(100),
                stock_code VARCHAR(20) NOT NULL,
                stock_name VARCHAR(50) NOT NULL,
                industry VARCHAR(50),
                sector VARCHAR(50),
                selection_date DATE NOT NULL,
                selection_time DATETIME NOT NULL,
                selection_price DECIMAL(10,2) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        today = datetime.now().date()
        cursor.execute(
            '''INSERT INTO stock_selection_record 
               (strategy_name, stock_code, stock_name, selection_date, selection_time, selection_price) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            (None, '000001', '平安银行', today.isoformat(), datetime.now().isoformat(), 10.5)
        )
        
        conn.commit()
        conn.close()
        
        with patch('trading.stock_helper.SELECTION_DB_PATH', db_file):
            result = StockHelper.check_selection_history('000001', days=30)
            assert result['in_history'] is True
            assert result['selection_strategies'] == []


class TestStockHelperIntegration:
    """股票辅助类集成测试"""

    def test_workflow_complete_flow(self, tmp_path):
        # 测试完整的工作流程
        # 1. 创建股票名称文件
        stock_names = {
            "000001": "平安银行",
            "000002": "万科A"
        }
        stock_file = tmp_path / "stock_names.json"
        with open(stock_file, 'w', encoding='utf-8') as f:
            json.dump(stock_names, f, ensure_ascii=False)
        
        # 2. 创建选股历史数据库
        db_file = tmp_path / "stock_selection.db"
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        
        # 使用实际的表结构
        cursor.execute('''
            CREATE TABLE stock_selection_record (
                id INTEGER PRIMARY KEY,
                strategy_name VARCHAR(100) NOT NULL,
                stock_code VARCHAR(20) NOT NULL,
                stock_name VARCHAR(50) NOT NULL,
                industry VARCHAR(50),
                sector VARCHAR(50),
                selection_date DATE NOT NULL,
                selection_time DATETIME NOT NULL,
                selection_price DECIMAL(10,2) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        today = datetime.now().date()
        cursor.execute(
            '''INSERT INTO stock_selection_record 
               (strategy_name, stock_code, stock_name, selection_date, selection_time, selection_price) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            ('B1PatternMatch', '000001', '平安银行', today.isoformat(), datetime.now().isoformat(), 10.5)
        )
        
        conn.commit()
        conn.close()
        
        # 3. 测试完整流程
        with patch('trading.stock_helper.STOCK_NAMES_FILE', stock_file), \
             patch('trading.stock_helper.SELECTION_DB_PATH', db_file):
            
            # 获取股票完整信息
            result = StockHelper.get_stock_full_info('000001', days=30)
            assert result['success'] is True
            assert result['data']['name'] == '平安银行'
            assert result['data']['in_selection_history'] is True
            
            # 获取不在选股历史中的股票
            result = StockHelper.get_stock_full_info('000002', days=30)
            assert result['success'] is True
            assert result['data']['name'] == '万科A'
            assert result['data']['in_selection_history'] is False


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])


    def test_get_price_range_success(self):
        """测试成功获取价格区间"""
        # 这个测试需要实际调用腾讯财经接口
        # 由于接口可能不稳定，这里使用mock
        with patch('trading.stock_helper.requests.get') as mock_get:
            # 模拟腾讯财经接口返回数据
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.encoding = 'gbk'
            # 腾讯接口返回格式: v_sh000001="1~平安银行~10.80~10.50~11.00~10.00~..."
            # parts[1]: 股票名称, parts[3]: 当前价, parts[5]: 开盘价, parts[33]: 最高价, parts[34]: 最低价
            parts = [''] * 35
            parts[1] = '平安银行'
            parts[3] = '10.80'
            parts[5] = '10.50'
            parts[33] = '11.00'
            parts[34] = '10.00'
            mock_response.text = '~'.join(parts)
            mock_get.return_value = mock_response
            
            # 调用方法
            result = StockHelper.get_price_range('000001')
            
            # 验证结果
            self.assertIsNotNone(result)
            self.assertEqual(result['code'], '000001')
            self.assertEqual(result['name'], '平安银行')
            self.assertEqual(result['high_price'], 11.00)
            self.assertEqual(result['low_price'], 10.00)
            self.assertEqual(result['current_price'], 10.80)
            self.assertEqual(result['open_price'], 10.50)

    def test_get_price_range_invalid_code(self):
        """测试无效的股票代码"""
        # 代码格式错误
        result = StockHelper.get_price_range('12345')  # 5位数字
        self.assertIsNone(result)
        
        result = StockHelper.get_price_range('00000a')  # 包含字母
        self.assertIsNone(result)
        
        result = StockHelper.get_price_range('')  # 空字符串
        self.assertIsNone(result)

    def test_get_price_range_api_failure(self):
        """测试API调用失败"""
        with patch('trading.stock_helper.requests.get') as mock_get:
            # 模拟API返回错误
            mock_get.side_effect = Exception('Network error')
            
            # 调用方法
            result = StockHelper.get_price_range('000001')
            
            # 应该返回None
            self.assertIsNone(result)

    def test_get_price_range_invalid_response(self):
        """测试API返回无效数据"""
        with patch('trading.stock_helper.requests.get') as mock_get:
            # 模拟API返回无效数据
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.encoding = 'gbk'
            mock_response.text = 'invalid data'  # 没有~分隔符
            mock_get.return_value = mock_response
            
            # 调用方法
            result = StockHelper.get_price_range('000001')
            
            # 应该返回None
            self.assertIsNone(result)

    def test_get_price_range_missing_fields(self):
        """测试API返回数据字段不完整"""
        with patch('trading.stock_helper.requests.get') as mock_get:
            # 模拟API返回数据字段不完整
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.encoding = 'gbk'
            parts = [''] * 20  # 只有20个字段，不足35个
            mock_response.text = '~'.join(parts)
            mock_get.return_value = mock_response
            
            # 调用方法
            result = StockHelper.get_price_range('000001')
            
            # 应该返回None
            self.assertIsNone(result)

    def test_get_price_range_zero_price(self):
        """测试价格为0的情况"""
        with patch('trading.stock_helper.requests.get') as mock_get:
            # 模拟API返回价格为0
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.encoding = 'gbk'
            parts = [''] * 35
            parts[1] = '平安银行'
            parts[3] = '0'
            parts[5] = '0'
            parts[33] = '0'  # 最高价为0
            parts[34] = '0'  # 最低价为0
            mock_response.text = '~'.join(parts)
            mock_get.return_value = mock_response
            
            # 调用方法
            result = StockHelper.get_price_range('000001')
            
            # 应该返回None（价格无效）
            self.assertIsNone(result)
