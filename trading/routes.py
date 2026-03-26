"""
模拟交易API路由 - 提供RESTful接口
"""
from flask import Blueprint, request, jsonify
from trading.service import TradingService
from trading.dao import TradingAccountDAO, TradingPositionDAO, TradingTransactionDAO
from trading.stock_helper import StockHelper
import logging

# 获取日志记录器
logger = logging.getLogger(__name__)

# 创建蓝图
trading_bp = Blueprint('trading', __name__, url_prefix='/api/trading')

# 初始化DAO和服务
account_dao = TradingAccountDAO()
position_dao = TradingPositionDAO()
transaction_dao = TradingTransactionDAO()
service = TradingService(account_dao, position_dao, transaction_dao)


# ==================== 账户相关接口 ====================

@trading_bp.route('/account/summary', methods=['GET'])
def get_account_summary():
    """
    获取账户总览接口
    
    参数:
        account_id: 账户ID (查询参数)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "account_id": "账户ID",
                "account_name": "账户名称",
                "initial_cash": 初始资金,
                "current_cash": 可用资金,
                "holding_value": 持仓市值,
                "total_assets": 总资产,
                "total_profit_loss": 总收益,
                "profit_loss_rate": 收益率(%),
                "holding_count": 持仓数量
            }
        }
    """
    try:
        # 获取并验证参数
        account_id = request.args.get('account_id', '').strip()
        if not account_id:
            return jsonify({
                'success': False,
                'message': '账户ID不能为空',
                'data': None
            }), 400
        
        # 调用服务获取账户总览
        result = service.get_account_summary(account_id)
        
        # 检查是否成功
        if not result.get('success'):
            return jsonify(result), 400
        
        return jsonify(result), 200
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"获取账户总览失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取账户总览失败: {str(e)}',
            'data': None
        }), 500


# ==================== 买入接口 ====================

@trading_bp.route('/buy', methods=['POST'])
def buy():
    """
    执行买入操作接口
    
    请求体:
        {
            "account_id": "账户ID",
            "stock_code": "股票代码",
            "stock_name": "股票名称",
            "quantity": 买入数量,
            "price": 买入价格,
            "transaction_date": "交易日期 (YYYY-MM-DD)"
        }
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "transaction_id": "交易ID",
                "stock_code": "股票代码",
                "quantity": 数量,
                "price": 价格,
                "cost": 成本,
                "commission": 手续费,
                "total_cost": 总成本
            }
        }
    """
    try:
        # 获取请求数据
        data = request.get_json() or {}
        
        # 验证必需参数
        required_fields = ['account_id', 'stock_code', 'stock_name', 'quantity', 'price', 'transaction_date']
        for field in required_fields:
            if field not in data or data[field] is None:
                return jsonify({
                    'success': False,
                    'message': f'缺少必需参数: {field}',
                    'data': None
                }), 400
        
        # 提取参数
        account_id = str(data['account_id']).strip()
        stock_code = str(data['stock_code']).strip()
        stock_name = str(data['stock_name']).strip()
        quantity = int(data['quantity'])
        price = float(data['price'])
        transaction_date = str(data['transaction_date']).strip()
        
        # 调用服务执行买入
        result = service.buy(
            account_id=account_id,
            stock_code=stock_code,
            stock_name=stock_name,
            quantity=quantity,
            price=price,
            transaction_date=transaction_date
        )
        
        # 检查是否成功
        if not result.get('success'):
            return jsonify(result), 400
        
        return jsonify(result), 200
    
    except ValueError as e:
        # 参数类型错误
        logger.error(f"买入参数类型错误: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'参数类型错误: {str(e)}',
            'data': None
        }), 400
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"买入操作失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'买入操作失败: {str(e)}',
            'data': None
        }), 500


# ==================== 卖出接口 ====================

@trading_bp.route('/sell', methods=['POST'])
def sell():
    """
    执行卖出操作接口
    
    请求体:
        {
            "account_id": "账户ID",
            "stock_code": "股票代码",
            "quantity": 卖出数量,
            "price": 卖出价格,
            "transaction_date": "交易日期 (YYYY-MM-DD)"
        }
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "transaction_id": "交易ID",
                "stock_code": "股票代码",
                "quantity": 数量,
                "price": 价格,
                "revenue": 卖出收入,
                "commission": 手续费,
                "stamp_tax": 印花税,
                "profit": 收益
            }
        }
    """
    try:
        # 获取请求数据
        data = request.get_json() or {}
        
        # 验证必需参数
        required_fields = ['account_id', 'stock_code', 'quantity', 'price', 'transaction_date']
        for field in required_fields:
            if field not in data or data[field] is None:
                return jsonify({
                    'success': False,
                    'message': f'缺少必需参数: {field}',
                    'data': None
                }), 400
        
        # 提取参数
        account_id = str(data['account_id']).strip()
        stock_code = str(data['stock_code']).strip()
        quantity = int(data['quantity'])
        price = float(data['price'])
        transaction_date = str(data['transaction_date']).strip()
        
        # 调用服务执行卖出
        result = service.sell(
            account_id=account_id,
            stock_code=stock_code,
            quantity=quantity,
            price=price,
            transaction_date=transaction_date
        )
        
        # 检查是否成功
        if not result.get('success'):
            return jsonify(result), 400
        
        return jsonify(result), 200
    
    except ValueError as e:
        # 参数类型错误
        logger.error(f"卖出参数类型错误: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'参数类型错误: {str(e)}',
            'data': None
        }), 400
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"卖出操作失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'卖出操作失败: {str(e)}',
            'data': None
        }), 500


# ==================== 查询接口 ====================

@trading_bp.route('/account/positions', methods=['GET'])
def get_positions():
    """
    获取持仓列表接口
    
    参数:
        account_id: 账户ID (查询参数)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": [
                {
                    "stock_code": "股票代码",
                    "stock_name": "股票名称",
                    "quantity": 持仓数量,
                    "cost_price": 成本价,
                    "market_value": 市值,
                    "profit": 收益,
                    "profit_rate": 收益率
                }
            ]
        }
    """
    try:
        # 获取并验证参数
        account_id = request.args.get('account_id', '').strip()
        if not account_id:
            return jsonify({
                'success': False,
                'message': '账户ID不能为空',
                'data': None
            }), 400
        
        # 调用服务获取持仓列表
        result = service.get_positions(account_id)
        
        # 检查是否成功
        if not result.get('success'):
            return jsonify(result), 400
        
        return jsonify(result), 200
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"获取持仓列表失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取持仓列表失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/account/transactions', methods=['GET'])
def get_transactions():
    """
    获取交易历史接口
    
    参数:
        account_id: 账户ID (查询参数)
        start_date: 开始日期 (可选, YYYY-MM-DD)
        end_date: 结束日期 (可选, YYYY-MM-DD)
        stock_code: 股票代码 (可选)
        page: 页码 (可选, 默认1)
        limit: 每页数量 (可选, 默认20)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "transactions": [
                    {
                        "transaction_id": "交易ID",
                        "stock_code": "股票代码",
                        "stock_name": "股票名称",
                        "transaction_type": "BUY/SELL",
                        "quantity": 数量,
                        "price": 价格,
                        "amount": 金额,
                        "commission": 手续费,
                        "transaction_date": "交易日期"
                    }
                ],
                "total": 总数,
                "page": 当前页,
                "limit": 每页数量,
                "total_pages": 总页数
            }
        }
    """
    try:
        # 获取并验证参数
        account_id = request.args.get('account_id', '').strip()
        if not account_id:
            return jsonify({
                'success': False,
                'message': '账户ID不能为空',
                'data': None
            }), 400
        
        # 获取可选参数
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)
        stock_code = request.args.get('stock_code', None)
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        
        # 调用服务获取交易历史
        result = service.get_transactions(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            stock_code=stock_code,
            page=page,
            limit=limit
        )
        
        # 检查是否成功
        if not result.get('success'):
            return jsonify(result), 400
        
        return jsonify(result), 200
    
    except ValueError as e:
        # 参数类型错误
        logger.error(f"查询参数类型错误: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'参数类型错误: {str(e)}',
            'data': None
        }), 400
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"获取交易历史失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取交易历史失败: {str(e)}',
            'data': None
        }), 500


# ==================== 股票信息接口 ====================

@trading_bp.route('/stock/info', methods=['GET'])
def get_stock_info():
    """
    获取股票信息接口 - 包含股票名称和选股历史验证
    
    参数:
        code: 股票代码 (查询参数, 必填, 6位数字)
        days: 检查选股历史的天数 (可选, 默认30)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "code": "000001",
                "name": "平安银行",
                "in_selection_history": true,
                "last_selection_date": "2026-03-25",
                "days_ago": 0,
                "selection_strategies": ["B1PatternMatch"],
                "selection_message": "该股票在选股历史中（今天选中）"
            }
        }
    """
    try:
        # 获取并验证参数
        code = request.args.get('code', '').strip()
        if not code:
            return jsonify({
                'success': False,
                'message': '股票代码不能为空',
                'data': None
            }), 400
        
        # 验证代码格式
        if len(code) != 6 or not code.isdigit():
            return jsonify({
                'success': False,
                'message': '股票代码必须为6位数字',
                'data': None
            }), 400
        
        # 获取可选参数
        days = int(request.args.get('days', 30))
        
        # 调用辅助类获取股票完整信息
        result = StockHelper.get_stock_full_info(code, days=days)
        
        # 检查是否成功
        if not result.get('success'):
            return jsonify({
                'success': False,
                'message': result.get('message', '获取股票信息失败'),
                'data': None
            }), 400
        
        return jsonify({
            'success': True,
            'message': '获取股票信息成功',
            'data': result['data']
        }), 200
    
    except ValueError as e:
        # 参数类型错误
        logger.error(f"股票信息查询参数错误: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'参数类型错误: {str(e)}',
            'data': None
        }), 400
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"获取股票信息失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取股票信息失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/stock/validate-selection', methods=['GET'])
def validate_stock_selection():
    """
    验证选股历史接口 - 检查股票是否在近期选股历史中
    
    参数:
        code: 股票代码 (查询参数, 必填, 6位数字)
        days: 检查天数范围 (可选, 默认30)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "code": "000001",
                "in_history": true,
                "last_selection_date": "2026-03-25",
                "days_ago": 0,
                "selection_strategies": ["B1PatternMatch"],
                "message": "该股票在选股历史中（今天选中）"
            }
        }
    """
    try:
        # 获取并验证参数
        code = request.args.get('code', '').strip()
        if not code:
            return jsonify({
                'success': False,
                'message': '股票代码不能为空',
                'data': None
            }), 400
        
        # 验证代码格式
        if len(code) != 6 or not code.isdigit():
            return jsonify({
                'success': False,
                'message': '股票代码必须为6位数字',
                'data': None
            }), 400
        
        # 获取可选参数
        days = int(request.args.get('days', 30))
        
        # 调用辅助类检查选股历史
        result = StockHelper.check_selection_history(code, days=days)
        
        # 返回验证结果
        return jsonify({
            'success': True,
            'message': '验证成功',
            'data': {
                'code': code,
                'in_history': result['in_history'],
                'last_selection_date': result['last_selection_date'],
                'days_ago': result['days_ago'],
                'selection_strategies': result['selection_strategies'],
                'message': result['message']
            }
        }), 200
    
    except ValueError as e:
        # 参数类型错误
        logger.error(f"选股历史验证参数错误: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'参数类型错误: {str(e)}',
            'data': None
        }), 400
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"验证选股历史失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'验证选股历史失败: {str(e)}',
            'data': None
        }), 500

@trading_bp.route('/stock/price-range', methods=['GET'])
def get_stock_price_range():
    """
    获取股票价格区间接口 - 获取当天的最高价和最低价
    
    参数:
        code: 股票代码 (查询参数, 必填, 6位数字)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "code": "000001",
                "name": "平安银行",
                "open_price": 10.50,
                "high_price": 11.00,
                "low_price": 10.00,
                "current_price": 10.80,
                "message": "当天价格区间：10.00 - 11.00 元"
            }
        }
    """
    try:
        # 获取并验证参数
        code = request.args.get('code', '').strip()
        if not code:
            return jsonify({
                'success': False,
                'message': '股票代码不能为空',
                'data': None
            }), 400
        
        # 验证代码格式
        if len(code) != 6 or not code.isdigit():
            return jsonify({
                'success': False,
                'message': '股票代码必须为6位数字',
                'data': None
            }), 400
        
        # 调用辅助类获取价格区间
        price_range = StockHelper.get_price_range(code)
        
        # 检查是否成功获取价格数据
        if not price_range:
            return jsonify({
                'success': False,
                'message': '无法获取该股票的实时价格数据',
                'data': None
            }), 400
        
        return jsonify({
            'success': True,
            'message': '获取价格区间成功',
            'data': price_range
        }), 200
    
    except ValueError as e:
        # 参数类型错误
        logger.error(f"价格区间查询参数错误: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'参数类型错误: {str(e)}',
            'data': None
        }), 400
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"获取价格区间失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取价格区间失败: {str(e)}',
            'data': None
        }), 500


# ==================== 账户管理接口 ====================

@trading_bp.route('/accounts', methods=['GET'])
def get_accounts():
    """
    获取所有账户列表接口
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "accounts": [
                    {
                        "account_id": "账户ID",
                        "account_name": "账户名称",
                        "initial_cash": 初始资金,
                        "current_cash": 可用资金,
                        "total_assets": 总资产,
                        "total_profit_loss": 总收益,
                        "profit_loss_rate": 收益率(%),
                        "holding_count": 持仓数量,
                        "created_date": "创建日期",
                        "status": "账户状态"
                    }
                ],
                "total_count": 账户总数
            }
        }
    """
    try:
        # 调用服务获取所有账户
        result = service.get_all_accounts()
        
        # 检查是否成功
        if not result.get('success'):
            return jsonify(result), 400
        
        return jsonify(result), 200
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"获取账户列表失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取账户列表失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/current-account', methods=['GET'])
def get_current_account():
    """
    获取当前账户接口
    
    参数:
        account_id: 账户ID (查询参数)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "account_id": "账户ID",
                "account_name": "账户名称",
                "initial_cash": 初始资金,
                "current_cash": 可用资金,
                "total_assets": 总资产,
                "total_profit_loss": 总收益,
                "profit_loss_rate": 收益率(%),
                "holding_count": 持仓数量,
                "created_date": "创建日期",
                "updated_date": "更新日期",
                "status": "账户状态"
            }
        }
    """
    try:
        # 获取并验证参数
        account_id = request.args.get('account_id', '').strip()
        if not account_id:
            return jsonify({
                'success': False,
                'message': '账户ID不能为空',
                'data': None
            }), 400
        
        # 调用服务获取当前账户
        result = service.get_current_account(account_id)
        
        # 检查是否成功
        if not result.get('success'):
            return jsonify(result), 400
        
        return jsonify(result), 200
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"获取当前账户失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取当前账户失败: {str(e)}',
            'data': None
        }), 500


@trading_bp.route('/switch-account/<account_id>', methods=['POST'])
def switch_account(account_id):
    """
    切换账户接口
    
    参数:
        account_id: 账户ID (路径参数)
    
    返回:
        {
            "success": true/false,
            "message": "成功或错误信息",
            "data": {
                "account_id": "账户ID",
                "account_name": "账户名称",
                "message": "切换成功"
            }
        }
    """
    try:
        # 验证账户ID
        account_id = str(account_id).strip()
        if not account_id:
            return jsonify({
                'success': False,
                'message': '账户ID不能为空',
                'data': None
            }), 400
        
        # 验证账户是否存在
        result = service.get_current_account(account_id)
        if not result.get('success'):
            return jsonify({
                'success': False,
                'message': '账户不存在',
                'data': None
            }), 400
        
        # 返回切换成功
        return jsonify({
            'success': True,
            'message': '账户切换成功',
            'data': {
                'account_id': account_id,
                'account_name': result['data']['account_name'],
                'message': f'已切换到账户: {result["data"]["account_name"]}'
            }
        }), 200
    
    except Exception as e:
        # 记录错误并返回
        logger.error(f"切换账户失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'切换账户失败: {str(e)}',
            'data': None
        }), 500
