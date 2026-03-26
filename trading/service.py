# 模拟交易业务逻辑层
# 提供买入、卖出、查询等交易服务

from typing import Dict, List, Optional
from datetime import datetime
import uuid
from trading.dao import (
    TradingAccountDAO,
    TradingPositionDAO,
    TradingTransactionDAO
)
from trading.calculator import (
    CostPriceCalculator,
    CommissionCalculator,
    ProfitCalculator
)
from trading.validators import BuyValidator, SellValidator


class TradingService:
    """交易服务类，提供买入、卖出、查询等业务逻辑"""

    def __init__(self, account_dao: TradingAccountDAO,
                 position_dao: TradingPositionDAO,
                 transaction_dao: TradingTransactionDAO):
        # 初始化数据访问对象
        self.account_dao = account_dao
        self.position_dao = position_dao
        self.transaction_dao = transaction_dao

    def _generate_id(self, prefix: str) -> str:
        # 生成唯一ID
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        random_part = str(uuid.uuid4())[:8]
        return f"{prefix}_{timestamp}_{random_part}"

    def buy(self, account_id: str, stock_code: str, stock_name: str,
            quantity: int, price: float, transaction_date: str,
            current_date: Optional[str] = None,
            allow_not_in_history: bool = False,
            validate_price: bool = True) -> Dict:
        # 执行买入操作
        # 参数:
        #   allow_not_in_history: 是否允许股票不在历史中（默认False，即必须在历史中）
        #   validate_price: 是否验证价格区间（默认True）
        # 返回格式: {'success': bool, 'message': str, 'data': dict}
        try:
            # 获取当前日期（用于验证）
            if current_date is None:
                current_date = datetime.now().strftime('%Y-%m-%d')

            # 获取账户信息
            account = self.account_dao.get_account(account_id)
            if not account:
                return {
                    'success': False,
                    'message': '账户不存在',
                    'data': None
                }

            # 计算买入成本和手续费
            buy_amount = quantity * price
            commission = CommissionCalculator.calculate_buy_commission(
                buy_amount
            )
            total_cost = CommissionCalculator.calculate_buy_total_cost(
                buy_amount,
                commission
            )

            # 获取该股票的交易记录（用于验证）
            txn_result = self.transaction_dao.get_transactions(
                account_id,
                stock_code=stock_code
            )
            existing_transactions = txn_result.get('transactions', [])

            # 验证买入条件（启用选股历史验证和价格验证）
            valid, error = BuyValidator.validate_buy(
                quantity=quantity,
                price=price,
                current_cash=account['current_cash'],
                total_cost=total_cost,
                transaction_date=transaction_date,
                current_date=current_date,
                account_id=account_id,
                stock_code=stock_code,
                existing_transactions=existing_transactions,
                validate_selection=True,
                allow_not_in_history=allow_not_in_history,
                validate_price=validate_price
            )
            if not valid:
                return {
                    'success': False,
                    'message': error,
                    'data': None
                }

            # 获取现有持仓（如果存在）
            position = self.position_dao.get_position_by_stock(
                account_id,
                stock_code
            )

            # 计算新的成本价，包含手续费分摊
            if position:
                # 已有持仓，计算加权平均成本价
                new_cost_price = (
                    CostPriceCalculator.calculate_weighted_average_cost(
                        current_quantity=position['quantity'],
                        current_cost_price=position['cost_price'],
                        buy_quantity=quantity,
                        buy_price=price,
                        commission=commission
                    )
                )
                new_quantity = position['quantity'] + quantity
            else:
                # 首次买入，成本价 = (买入金额 + 手续费) / 买入数量
                new_cost_price = (
                    CostPriceCalculator.calculate_weighted_average_cost(
                        current_quantity=0,
                        current_cost_price=0,
                        buy_quantity=quantity,
                        buy_price=price,
                        commission=commission
                    )
                )
                new_quantity = quantity

            # 更新账户资金
            new_cash = account['current_cash'] - total_cost

            # 创建或更新持仓
            if position:
                # 更新现有持仓
                self.position_dao.update_position(
                    position_id=position['position_id'],
                    quantity=new_quantity,
                    cost_price=new_cost_price,
                    current_price=price,
                    last_buy_date=transaction_date
                )
            else:
                # 创建新持仓
                position_id = self._generate_id('POS')
                self.position_dao.create_position(
                    position_id=position_id,
                    account_id=account_id,
                    stock_code=stock_code,
                    stock_name=stock_name,
                    quantity=new_quantity,
                    cost_price=new_cost_price,
                    current_price=price,
                    last_buy_date=transaction_date
                )

            # 计算新的总资产（在持仓创建/更新之后）
            # 获取所有持仓（包括新创建/更新的持仓）
            positions = self.position_dao.get_positions(account_id)
            holding_value = sum(
                p['quantity'] * p['current_price'] for p in positions
            )
            new_total_assets = new_cash + holding_value
            self.account_dao.update_account(
                account_id=account_id,
                current_cash=new_cash,
                total_assets=new_total_assets
            )

            # 记录交易
            transaction_id = self._generate_id('TXN')
            self.transaction_dao.create_transaction(
                transaction_id=transaction_id,
                account_id=account_id,
                stock_code=stock_code,
                stock_name=stock_name,
                transaction_type='BUY',
                quantity=quantity,
                price=price,
                amount=buy_amount,
                commission=commission,
                stamp_tax=0,
                total_cost=total_cost,
                profit_loss=None,
                transaction_date=transaction_date
            )

            # 返回成功结果
            return {
                'success': True,
                'message': '买入成功',
                'data': {
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'quantity': quantity,
                    'price': price,
                    'amount': buy_amount,
                    'commission': commission,
                    'total_cost': total_cost,
                    'new_cost_price': new_cost_price,
                    'transaction_date': transaction_date
                }
            }

        except Exception as e:
            # 捕获异常并返回错误
            return {
                'success': False,
                'message': f'买入失败: {str(e)}',
                'data': None
            }

    def sell(self, account_id: str, stock_code: str, quantity: int,
             price: float, transaction_date: str,
             current_date: Optional[str] = None,
             validate_price: bool = True) -> Dict:
        # 执行卖出操作
        # 参数:
        #   validate_price: 是否验证价格区间（默认True）
        # 返回格式: {'success': bool, 'message': str, 'data': dict}
        try:
            # 获取当前日期（用于验证）
            if current_date is None:
                current_date = datetime.now().strftime('%Y-%m-%d')

            # 获取账户和持仓信息
            account = self.account_dao.get_account(account_id)
            if not account:
                return {
                    'success': False,
                    'message': '账户不存在',
                    'data': None
                }

            position = self.position_dao.get_position_by_stock(
                account_id,
                stock_code
            )
            if not position:
                return {
                    'success': False,
                    'message': '持仓不存在',
                    'data': None
                }

            # 计算卖出成本和手续费
            sell_amount = quantity * price
            commission = CommissionCalculator.calculate_sell_commission(
                sell_amount
            )
            stamp_tax = CommissionCalculator.calculate_stamp_tax(
                sell_amount
            )
            cost_basis = CostPriceCalculator.calculate_sell_cost_basis(
                quantity,
                position['cost_price']
            )

            # 计算卖出收益
            profit_loss, profit_loss_rate = (
                ProfitCalculator.calculate_sell_profit_loss(
                    quantity=quantity,
                    cost_price=position['cost_price'],
                    sell_price=price,
                    commission=commission,
                    stamp_tax=stamp_tax
                )
            )

            # 获取该股票的交易记录（用于验证）
            txn_result = self.transaction_dao.get_transactions(
                account_id,
                stock_code=stock_code
            )
            existing_transactions = txn_result.get('transactions', [])

            # 验证卖出条件（包括价格验证）
            valid, error = SellValidator.validate_sell(
                quantity=quantity,
                price=price,
                position_quantity=position['quantity'],
                transaction_date=transaction_date,
                last_buy_date=position['last_buy_date'],
                current_date=current_date,
                account_id=account_id,
                stock_code=stock_code,
                existing_transactions=existing_transactions,
                validate_price=validate_price
            )
            if not valid:
                return {
                    'success': False,
                    'message': error,
                    'data': None
                }

            # 计算卖出净收益
            net_proceeds = (
                CommissionCalculator.calculate_sell_net_proceeds(
                    sell_amount,
                    commission,
                    stamp_tax
                )
            )

            # 更新账户资金
            new_cash = account['current_cash'] + net_proceeds

            # 更新或删除持仓
            remaining_quantity = position['quantity'] - quantity
            if remaining_quantity == 0:
                # 全部卖出，删除持仓
                self.position_dao.delete_position(
                    position_id=position['position_id']
                )
            else:
                # 部分卖出，更新持仓
                self.position_dao.update_position(
                    position_id=position['position_id'],
                    quantity=remaining_quantity,
                    cost_price=position['cost_price'],
                    current_price=price,
                    last_buy_date=position['last_buy_date']
                )

            # 计算新的总资产（在持仓更新/删除之后）
            # 获取所有持仓（包括更新/删除后的持仓）
            positions = self.position_dao.get_positions(account_id)
            holding_value = sum(
                p['quantity'] * p['current_price'] for p in positions
            )
            new_total_assets = new_cash + holding_value
            self.account_dao.update_account(
                account_id=account_id,
                current_cash=new_cash,
                total_assets=new_total_assets
            )

            # 记录交易
            transaction_id = self._generate_id('TXN')
            self.transaction_dao.create_transaction(
                transaction_id=transaction_id,
                account_id=account_id,
                stock_code=stock_code,
                stock_name=position['stock_name'],
                transaction_type='SELL',
                quantity=quantity,
                price=price,
                amount=sell_amount,
                commission=commission,
                stamp_tax=stamp_tax,
                total_cost=net_proceeds,
                profit_loss=profit_loss,
                transaction_date=transaction_date
            )

            # 返回成功结果
            return {
                'success': True,
                'message': '卖出成功',
                'data': {
                    'stock_code': stock_code,
                    'stock_name': position['stock_name'],
                    'quantity': quantity,
                    'price': price,
                    'amount': sell_amount,
                    'commission': commission,
                    'stamp_tax': stamp_tax,
                    'net_proceeds': net_proceeds,
                    'cost_basis': cost_basis,
                    'profit_loss': profit_loss,
                    'profit_loss_rate': profit_loss_rate,
                    'transaction_date': transaction_date
                }
            }

        except Exception as e:
            # 捕获异常并返回错误
            return {
                'success': False,
                'message': f'卖出失败: {str(e)}',
                'data': None
            }

    def get_account_summary(self, account_id: str) -> Dict:
        # 获取账户总览
        # 返回账户基本信息、总资产、收益等
        try:
            # 获取账户信息
            account = self.account_dao.get_account(account_id)
            if not account:
                return {
                    'success': False,
                    'message': '账户不存在',
                    'data': None
                }

            # 获取所有持仓
            positions = self.position_dao.get_positions(account_id)

            # 计算持仓市值
            holding_value = 0.0
            for position in positions:
                market_value = (
                    ProfitCalculator.calculate_market_value(
                        position['quantity'],
                        position['current_price']
                    )
                )
                holding_value += market_value

            # 计算总资产
            total_assets = account['current_cash'] + holding_value

            # 计算总收益
            total_profit_loss, profit_loss_rate = (
                ProfitCalculator.calculate_account_profit_loss(
                    total_assets,
                    account['initial_cash']
                )
            )

            # 返回账户总览
            return {
                'success': True,
                'message': '查询成功',
                'data': {
                    'account_id': account_id,
                    'account_name': account['account_name'],
                    'initial_cash': account['initial_cash'],
                    'current_cash': account['current_cash'],
                    'holding_value': round(holding_value, 2),
                    'total_assets': round(total_assets, 2),
                    'total_profit_loss': total_profit_loss,
                    'profit_loss_rate': profit_loss_rate,
                    'holding_count': len(positions)
                }
            }

        except Exception as e:
            # 捕获异常并返回错误
            return {
                'success': False,
                'message': f'查询失败: {str(e)}',
                'data': None
            }

    def get_positions(self, account_id: str) -> Dict:
        # 获取持仓列表
        # 返回所有持仓信息，并更新当前价格为最新市场价格
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # 获取账户信息（验证账户存在）
            account = self.account_dao.get_account(account_id)
            if not account:
                return {
                    'success': False,
                    'message': '账户不存在',
                    'data': None
                }

            # 获取所有持仓
            positions = self.position_dao.get_positions(account_id)

            # 构建持仓列表
            position_list = []
            for position in positions:
                # 获取股票的最新市场价格
                current_price = position['current_price']  # 默认使用数据库中的价格
                
                try:
                    price_range = StockHelper.get_price_range(position['stock_code'])
                    if price_range and price_range.get('current_price'):
                        # 获取最新市场价格
                        latest_price = price_range['current_price']
                        
                        # 尝试更新数据库中的当前价格
                        try:
                            update_result = self.position_dao.update_position(
                                position_id=position['position_id'],
                                quantity=position['quantity'],
                                cost_price=position['cost_price'],
                                current_price=latest_price,
                                last_buy_date=position['last_buy_date']
                            )
                            
                            if update_result:
                                current_price = latest_price
                                logger.debug(f"Updated position {position['position_id']} current_price to {latest_price}")
                            else:
                                logger.warning(f"Failed to update position {position['position_id']} current_price in DB")
                                # 即使数据库更新失败，也使用最新价格
                                current_price = latest_price
                        except Exception as db_error:
                            logger.error(f"Error updating position {position['position_id']} in DB: {str(db_error)}")
                            # 即使数据库更新失败，也使用最新价格
                            current_price = latest_price
                except Exception as price_error:
                    logger.error(f"Error getting price for {position['stock_code']}: {str(price_error)}")
                    # 如果获取最新价格失败，使用数据库中的价格
                    current_price = position['current_price']

                # 计算市值和收益
                market_value = (
                    ProfitCalculator.calculate_market_value(
                        position['quantity'],
                        current_price
                    )
                )
                profit_loss, profit_loss_rate = (
                    ProfitCalculator.calculate_position_profit_loss(
                        position['quantity'],
                        position['cost_price'],
                        current_price
                    )
                )

                position_list.append({
                    'position_id': position['position_id'],
                    'stock_code': position['stock_code'],
                    'stock_name': position['stock_name'],
                    'quantity': position['quantity'],
                    'cost_price': position['cost_price'],
                    'current_price': current_price,
                    'market_value': market_value,
                    'profit_loss': profit_loss,
                    'profit_loss_rate': profit_loss_rate,
                    'created_date': position['created_date']
                })

            # 返回持仓列表
            return {
                'success': True,
                'message': '查询成功',
                'data': {
                    'positions': position_list,
                    'total_count': len(position_list)
                }
            }

        except Exception as e:
            # 捕获异常并返回错误
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in get_positions: {str(e)}")
            return {
                'success': False,
                'message': f'查询失败: {str(e)}',
                'data': None
            }

    def get_transactions(self, account_id: str,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None,
                        stock_code: Optional[str] = None,
                        page: int = 1,
                        limit: int = 20) -> Dict:
        # 获取交易历史
        # 支持按日期、股票代码筛选和分页
        try:
            # 获取账户信息（验证账户存在）
            account = self.account_dao.get_account(account_id)
            if not account:
                return {
                    'success': False,
                    'message': '账户不存在',
                    'data': None
                }

            # 获取交易记录
            result = self.transaction_dao.get_transactions(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date,
                stock_code=stock_code,
                page=page,
                limit=limit
            )

            # 返回交易历史
            return {
                'success': True,
                'message': '查询成功',
                'data': result
            }

        except Exception as e:
            # 捕获异常并返回错误
            return {
                'success': False,
                'message': f'查询失败: {str(e)}',
                'data': None
            }

    def get_all_accounts(self) -> Dict:
        # 获取所有账户列表
        # 返回所有活跃账户的基本信息
        try:
            # 获取所有账户
            accounts = self.account_dao.get_all_accounts()

            # 构建账户列表
            account_list = []
            for account in accounts:
                # 获取该账户的持仓数量
                positions = self.position_dao.get_positions(account['account_id'])

                account_list.append({
                    'account_id': account['account_id'],
                    'account_name': account['account_name'],
                    'initial_cash': account['initial_cash'],
                    'current_cash': account['current_cash'],
                    'total_assets': account['total_assets'],
                    'total_profit_loss': account['total_profit_loss'],
                    'profit_loss_rate': account['profit_loss_rate'],
                    'holding_count': len(positions),
                    'created_date': account['created_date'],
                    'status': account['status']
                })

            # 返回账户列表
            return {
                'success': True,
                'message': '查询成功',
                'data': {
                    'accounts': account_list,
                    'total_count': len(account_list)
                }
            }

        except Exception as e:
            # 捕获异常并返回错误
            return {
                'success': False,
                'message': f'查询失败: {str(e)}',
                'data': None
            }

    def get_current_account(self, account_id: str) -> Dict:
        # 获取当前账户详细信息
        # 返回账户的完整信息
        try:
            # 获取账户信息
            account = self.account_dao.get_account(account_id)
            if not account:
                return {
                    'success': False,
                    'message': '账户不存在',
                    'data': None
                }

            # 获取持仓信息
            positions = self.position_dao.get_positions(account_id)

            # 返回账户详细信息
            return {
                'success': True,
                'message': '查询成功',
                'data': {
                    'account_id': account['account_id'],
                    'account_name': account['account_name'],
                    'initial_cash': account['initial_cash'],
                    'current_cash': account['current_cash'],
                    'total_assets': account['total_assets'],
                    'total_profit_loss': account['total_profit_loss'],
                    'profit_loss_rate': account['profit_loss_rate'],
                    'holding_count': len(positions),
                    'created_date': account['created_date'],
                    'updated_date': account['updated_date'],
                    'status': account['status']
                }
            }

        except Exception as e:
            # 捕获异常并返回错误
            return {
                'success': False,
                'message': f'查询失败: {str(e)}',
                'data': None
            }


