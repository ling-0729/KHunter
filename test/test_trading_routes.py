"""
模拟交易API路由集成测试
"""
import pytest
import json
from datetime import datetime, timedelta
from flask import Flask
from trading.routes import trading_bp
from trading.dao import TradingAccountDAO, TradingPositionDAO, TradingTransactionDAO
from trading.service import TradingService


@pytest.fixture
def app():
    """创建Flask应用测试实例"""
    app = Flask(__name__)
    app.config['TESTING'] = True
    
    # 注册蓝图
    app.register_blueprint(trading_bp)
    
    return app


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return app.test_client()


@pytest.fixture
def setup_test_data():
    """设置测试数据"""
    import uuid
    import sqlite3
    from pathlib import Path
    
    # 初始化DAO
    account_dao = TradingAccountDAO()
    position_dao = TradingPositionDAO()
    transaction_dao = TradingTransactionDAO()
    
    # 创建唯一的测试账户ID
    account_id = f'test_account_{uuid.uuid4().hex[:8]}'
    account_dao.create_account(
        account_id=account_id,
        account_name='测试账户',
        initial_cash=1000000
    )
    
    # 添加测试股票到选股历史
    # 获取选股历史数据库路径
    project_root = Path(__file__).parent.parent
    selection_db_path = project_root / 'data' / 'stock_selection.db'
    
    # 连接数据库并添加测试数据
    if selection_db_path.exists():
        try:
            conn = sqlite3.connect(str(selection_db_path))
            cursor = conn.cursor()
            
            # 添加测试股票到选股历史（今天）
            today = datetime.now().date().isoformat()
            test_stocks = [
                ('000001', '平安银行'),
                ('000002', '万科A'),
                ('600000', '浦发银行'),
                ('300001', '特锐德')
            ]
            
            for code, name in test_stocks:
                try:
                    cursor.execute(
                        '''INSERT INTO stock_selection_record 
                           (strategy_name, stock_code, stock_name, selection_date, selection_time, selection_price) 
                           VALUES (?, ?, ?, ?, ?, ?)''',
                        ('TestStrategy', code, name, today, datetime.now().isoformat(), 10.0)
                    )
                except sqlite3.IntegrityError:
                    # 如果记录已存在，忽略错误
                    pass
            
            conn.commit()
            conn.close()
        except Exception as e:
            # 如果添加失败，继续执行测试
            pass
    
    return {
        'account_id': account_id,
        'account_dao': account_dao,
        'position_dao': position_dao,
        'transaction_dao': transaction_dao
    }


class TestAccountSummaryAPI:
    """账户总览API测试"""
    
    def test_get_account_summary_success(self, client, setup_test_data):
        """测试成功获取账户总览"""
        account_id = setup_test_data['account_id']
        
        # 发送GET请求
        response = client.get(f'/api/trading/account/summary?account_id={account_id}')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['data']['account_id'] == account_id
        assert data['data']['total_assets'] == 1000000
        assert data['data']['current_cash'] == 1000000
    
    def test_get_account_summary_missing_account_id(self, client):
        """测试缺少account_id参数"""
        # 发送GET请求（不带account_id）
        response = client.get('/api/trading/account/summary')
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert '账户ID不能为空' in data['message']
    
    def test_get_account_summary_nonexistent_account(self, client):
        """测试获取不存在的账户"""
        # 发送GET请求
        response = client.get('/api/trading/account/summary?account_id=nonexistent')
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False


class TestBuyAPI:
    """买入API测试"""
    
    def test_buy_success(self, client, setup_test_data):
        """测试成功买入"""
        account_id = setup_test_data['account_id']
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 准备请求数据
        buy_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'stock_name': '平安银行',
            'quantity': 100,
            'price': 10.5,
            'transaction_date': today
        }
        
        # 发送POST请求
        response = client.post(
            '/api/trading/buy',
            data=json.dumps(buy_data),
            content_type='application/json'
        )
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['data']['stock_code'] == '000001'
        assert data['data']['quantity'] == 100
        assert data['data']['price'] == 10.5
    
    def test_buy_missing_required_field(self, client, setup_test_data):
        """测试缺少必需参数"""
        account_id = setup_test_data['account_id']
        
        # 准备请求数据（缺少stock_name）
        buy_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'quantity': 100,
            'price': 10.5,
            'transaction_date': datetime.now().strftime('%Y-%m-%d')
        }
        
        # 发送POST请求
        response = client.post(
            '/api/trading/buy',
            data=json.dumps(buy_data),
            content_type='application/json'
        )
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert '缺少必需参数' in data['message']
    
    def test_buy_invalid_quantity_type(self, client, setup_test_data):
        """测试无效的数量类型"""
        account_id = setup_test_data['account_id']
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 准备请求数据（quantity为字符串）
        buy_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'stock_name': '平安银行',
            'quantity': 'invalid',
            'price': 10.5,
            'transaction_date': today
        }
        
        # 发送POST请求
        response = client.post(
            '/api/trading/buy',
            data=json.dumps(buy_data),
            content_type='application/json'
        )
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert '参数类型错误' in data['message']
    
    def test_buy_insufficient_cash(self, client, setup_test_data):
        """测试资金不足"""
        account_id = setup_test_data['account_id']
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 准备请求数据（购买金额超过账户资金）
        buy_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'stock_name': '平安银行',
            'quantity': 1000000,  # 大量购买
            'price': 100,  # 高价格
            'transaction_date': today
        }
        
        # 发送POST请求
        response = client.post(
            '/api/trading/buy',
            data=json.dumps(buy_data),
            content_type='application/json'
        )
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False


class TestSellAPI:
    """卖出API测试"""
    
    def test_sell_success(self, client, setup_test_data):
        """测试成功卖出"""
        account_id = setup_test_data['account_id']
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        # 先执行买入
        buy_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'stock_name': '平安银行',
            'quantity': 100,
            'price': 10.5,
            'transaction_date': yesterday
        }
        
        client.post(
            '/api/trading/buy',
            data=json.dumps(buy_data),
            content_type='application/json'
        )
        
        # 然后执行卖出
        sell_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'quantity': 50,
            'price': 11.0,
            'transaction_date': today
        }
        
        response = client.post(
            '/api/trading/sell',
            data=json.dumps(sell_data),
            content_type='application/json'
        )
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['data']['stock_code'] == '000001'
        assert data['data']['quantity'] == 50
    
    def test_sell_missing_required_field(self, client, setup_test_data):
        """测试缺少必需参数"""
        account_id = setup_test_data['account_id']
        
        # 准备请求数据（缺少price）
        sell_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'quantity': 50,
            'transaction_date': datetime.now().strftime('%Y-%m-%d')
        }
        
        # 发送POST请求
        response = client.post(
            '/api/trading/sell',
            data=json.dumps(sell_data),
            content_type='application/json'
        )
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert '缺少必需参数' in data['message']
    
    def test_sell_position_not_exist(self, client, setup_test_data):
        """测试卖出不存在的持仓"""
        account_id = setup_test_data['account_id']
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 准备请求数据（卖出未持有的股票）
        sell_data = {
            'account_id': account_id,
            'stock_code': '999999',
            'quantity': 50,
            'price': 11.0,
            'transaction_date': today
        }
        
        # 发送POST请求
        response = client.post(
            '/api/trading/sell',
            data=json.dumps(sell_data),
            content_type='application/json'
        )
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False


class TestPositionsAPI:
    """持仓查询API测试"""
    
    def test_get_positions_empty(self, client, setup_test_data):
        """测试获取空持仓列表"""
        account_id = setup_test_data['account_id']
        
        # 发送GET请求
        response = client.get(f'/api/trading/account/positions?account_id={account_id}')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert isinstance(data['data'], dict)
        assert len(data['data']['positions']) == 0
    
    def test_get_positions_with_holdings(self, client, setup_test_data):
        """测试获取有持仓的列表"""
        account_id = setup_test_data['account_id']
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 先执行买入
        buy_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'stock_name': '平安银行',
            'quantity': 100,
            'price': 10.5,
            'transaction_date': today
        }
        
        client.post(
            '/api/trading/buy',
            data=json.dumps(buy_data),
            content_type='application/json'
        )
        
        # 获取持仓列表
        response = client.get(f'/api/trading/account/positions?account_id={account_id}')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['data']['positions']) == 1
        assert data['data']['positions'][0]['stock_code'] == '000001'
        assert data['data']['positions'][0]['quantity'] == 100
    
    def test_get_positions_missing_account_id(self, client):
        """测试缺少account_id参数"""
        # 发送GET请求（不带account_id）
        response = client.get('/api/trading/account/positions')
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False


class TestTransactionsAPI:
    """交易历史查询API测试"""
    
    def test_get_transactions_empty(self, client, setup_test_data):
        """测试获取空交易历史"""
        account_id = setup_test_data['account_id']
        
        # 发送GET请求
        response = client.get(f'/api/trading/account/transactions?account_id={account_id}')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'transactions' in data['data']
        assert len(data['data']['transactions']) == 0
    
    def test_get_transactions_with_data(self, client, setup_test_data):
        """测试获取有数据的交易历史"""
        account_id = setup_test_data['account_id']
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 先执行买入
        buy_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'stock_name': '平安银行',
            'quantity': 100,
            'price': 10.5,
            'transaction_date': today
        }
        
        client.post(
            '/api/trading/buy',
            data=json.dumps(buy_data),
            content_type='application/json'
        )
        
        # 获取交易历史
        response = client.get(f'/api/trading/account/transactions?account_id={account_id}')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['data']['transactions']) == 1
        assert data['data']['transactions'][0]['stock_code'] == '000001'
    
    def test_get_transactions_with_pagination(self, client, setup_test_data):
        """测试交易历史分页"""
        account_id = setup_test_data['account_id']
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 先添加测试股票到选股历史
        import sqlite3
        from pathlib import Path
        project_root = Path(__file__).parent.parent
        selection_db_path = project_root / 'data' / 'stock_selection.db'
        
        if selection_db_path.exists():
            conn = sqlite3.connect(str(selection_db_path))
            cursor = conn.cursor()
            
            # 添加5个测试股票
            test_stocks = [
                ('000001', '平安银行'),
                ('000002', '万科A'),
                ('000003', '平安银行'),
                ('000004', '万科A'),
                ('000005', '平安银行'),
            ]
            
            for code, name in test_stocks:
                try:
                    cursor.execute(
                        '''INSERT INTO stock_selection_record 
                           (strategy_name, stock_code, stock_name, selection_date, selection_time, selection_price) 
                           VALUES (?, ?, ?, ?, ?, ?)''',
                        ('TestStrategy', code, name, today, datetime.now().isoformat(), 10.0)
                    )
                except sqlite3.IntegrityError:
                    pass
            
            conn.commit()
            conn.close()
        
        # 执行多次买入
        for i in range(5):
            buy_data = {
                'account_id': account_id,
                'stock_code': f'00000{i+1}',
                'stock_name': f'股票{i+1}',
                'quantity': 100,
                'price': 10.5,
                'transaction_date': today
            }
            
            client.post(
                '/api/trading/buy',
                data=json.dumps(buy_data),
                content_type='application/json'
            )
        
        # 获取第一页（每页2条）
        response = client.get(
            f'/api/trading/account/transactions?account_id={account_id}&page=1&limit=2'
        )
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['data']['transactions']) == 2
        assert data['data']['page'] == 1
        assert data['data']['limit'] == 2
        assert data['data']['total'] == 5
    
    def test_get_transactions_missing_account_id(self, client):
        """测试缺少account_id参数"""
        # 发送GET请求（不带account_id）
        response = client.get('/api/trading/account/transactions')
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False


class TestAPIIntegration:
    """API集成测试"""
    
    def test_complete_trading_flow(self, client, setup_test_data):
        """测试完整的交易流程"""
        account_id = setup_test_data['account_id']
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        # 1. 获取初始账户总览
        response = client.get(f'/api/trading/account/summary?account_id={account_id}')
        assert response.status_code == 200
        initial_data = json.loads(response.data)
        assert initial_data['data']['total_assets'] == 1000000
        
        # 2. 执行买入
        buy_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'stock_name': '平安银行',
            'quantity': 100,
            'price': 10.5,
            'transaction_date': yesterday
        }
        
        response = client.post(
            '/api/trading/buy',
            data=json.dumps(buy_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        
        # 3. 获取持仓列表
        response = client.get(f'/api/trading/account/positions?account_id={account_id}')
        assert response.status_code == 200
        positions_data = json.loads(response.data)
        assert len(positions_data['data']['positions']) == 1
        
        # 4. 执行卖出
        sell_data = {
            'account_id': account_id,
            'stock_code': '000001',
            'quantity': 50,
            'price': 11.0,
            'transaction_date': today
        }
        
        response = client.post(
            '/api/trading/sell',
            data=json.dumps(sell_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        
        # 5. 获取交易历史
        response = client.get(f'/api/trading/account/transactions?account_id={account_id}')
        assert response.status_code == 200
        transactions_data = json.loads(response.data)
        assert len(transactions_data['data']['transactions']) == 2
        
        # 6. 获取最终账户总览
        response = client.get(f'/api/trading/account/summary?account_id={account_id}')
        assert response.status_code == 200
        final_data = json.loads(response.data)
        # 由于卖出价格(11.0)高于买入价格(10.5)，总资产应该增加
        # 但由于手续费，增加的幅度会小于理论收益
        assert final_data['data']['total_assets'] > initial_data['data']['total_assets']



class TestStockInfoAPI:
    """股票信息API测试"""
    
    def test_get_stock_info_success(self, client):
        """测试成功获取股票信息"""
        # 发送GET请求
        response = client.get('/api/trading/stock/info?code=000001')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['data']['code'] == '000001'
        assert 'name' in data['data']
        assert 'in_selection_history' in data['data']
    
    def test_get_stock_info_missing_code(self, client):
        """测试缺少股票代码参数"""
        # 发送GET请求（不带code）
        response = client.get('/api/trading/stock/info')
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert '股票代码不能为空' in data['message']
    
    def test_get_stock_info_invalid_code_format(self, client):
        """测试无效的股票代码格式"""
        # 代码太短
        response = client.get('/api/trading/stock/info?code=00001')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert '6位数字' in data['message']
        
        # 代码太长
        response = client.get('/api/trading/stock/info?code=0000001')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        
        # 包含非数字字符
        response = client.get('/api/trading/stock/info?code=00000A')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
    
    def test_get_stock_info_with_custom_days(self, client):
        """测试自定义天数范围"""
        # 发送GET请求，指定30天范围
        response = client.get('/api/trading/stock/info?code=000001&days=30')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['data']['code'] == '000001'
    
    def test_get_stock_info_nonexistent_stock(self, client):
        """测试不存在的股票"""
        # 发送GET请求
        response = client.get('/api/trading/stock/info?code=999999')
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False


class TestValidateSelectionAPI:
    """选股历史验证API测试"""
    
    def test_validate_selection_success(self, client):
        """测试成功验证选股历史"""
        # 发送GET请求
        response = client.get('/api/trading/stock/validate-selection?code=000001')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['data']['code'] == '000001'
        assert 'in_history' in data['data']
        assert 'message' in data['data']
    
    def test_validate_selection_missing_code(self, client):
        """测试缺少股票代码参数"""
        # 发送GET请求（不带code）
        response = client.get('/api/trading/stock/validate-selection')
        
        # 验证响应
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert '股票代码不能为空' in data['message']
    
    def test_validate_selection_invalid_code_format(self, client):
        """测试无效的股票代码格式"""
        # 代码太短
        response = client.get('/api/trading/stock/validate-selection?code=00001')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert '6位数字' in data['message']
        
        # 包含非数字字符
        response = client.get('/api/trading/stock/validate-selection?code=00000A')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
    
    def test_validate_selection_with_custom_days(self, client):
        """测试自定义天数范围"""
        # 发送GET请求，指定30天范围
        response = client.get('/api/trading/stock/validate-selection?code=000001&days=30')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['data']['code'] == '000001'
        assert 'in_history' in data['data']
    
    def test_validate_selection_response_structure(self, client):
        """测试响应结构完整性"""
        # 发送GET请求
        response = client.get('/api/trading/stock/validate-selection?code=000001')
        
        # 验证响应
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        
        # 验证数据结构
        result_data = data['data']
        assert 'code' in result_data
        assert 'in_history' in result_data
        assert 'last_selection_date' in result_data
        assert 'days_ago' in result_data
        assert 'selection_strategies' in result_data
        assert 'message' in result_data
        
        # 验证数据类型
        assert isinstance(result_data['code'], str)
        assert isinstance(result_data['in_history'], bool)
        assert isinstance(result_data['selection_strategies'], list)
        assert isinstance(result_data['message'], str)


class TestStockAPIIntegration:
    """股票API集成测试"""
    
    def test_stock_info_and_validation_flow(self, client):
        """测试股票信息和验证的完整流程"""
        # 1. 获取股票信息
        response = client.get('/api/trading/stock/info?code=000001')
        assert response.status_code == 200
        info_data = json.loads(response.data)
        assert info_data['success'] is True
        
        # 2. 验证选股历史
        response = client.get('/api/trading/stock/validate-selection?code=000001')
        assert response.status_code == 200
        validation_data = json.loads(response.data)
        assert validation_data['success'] is True
        
        # 3. 验证两个接口返回的选股历史信息一致
        assert info_data['data']['in_selection_history'] == validation_data['data']['in_history']
        assert info_data['data']['last_selection_date'] == validation_data['data']['last_selection_date']
    
    def test_multiple_stocks_validation(self, client):
        """测试多个股票的验证"""
        stocks = ['000001', '000002', '600000', '300001']
        
        for stock_code in stocks:
            # 获取股票信息
            response = client.get(f'/api/trading/stock/info?code={stock_code}')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True
            assert data['data']['code'] == stock_code
    
    def test_stock_api_error_handling(self, client):
        """测试股票API的错误处理"""
        # 测试各种错误情况
        test_cases = [
            ('/api/trading/stock/info', 400, '股票代码不能为空'),
            ('/api/trading/stock/info?code=', 400, '股票代码不能为空'),
            ('/api/trading/stock/info?code=00001', 400, '6位数字'),
            ('/api/trading/stock/validate-selection', 400, '股票代码不能为空'),
            ('/api/trading/stock/validate-selection?code=ABC', 400, '6位数字'),
        ]
        
        for url, expected_status, expected_message in test_cases:
            response = client.get(url)
            assert response.status_code == expected_status
            data = json.loads(response.data)
            assert data['success'] is False
            if expected_message:
                assert expected_message in data['message']
