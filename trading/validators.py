# 模拟交易验证器
# 提供买入、卖出等交易的业务规则验证

from typing import Tuple, Optional, Dict, Any
from datetime import datetime
from trading.stock_helper import StockHelper


class BuyValidator:
    """买入验证器"""

    @staticmethod
    def validate_quantity(quantity: int) -> Tuple[bool, Optional[str]]:
        # 验证买入数量
        # 规则: 数量 > 0 且为整数
        if not isinstance(quantity, int):
            return False, "买入数量必须为整数"
        if quantity <= 0:
            return False, "买入数量必须大于0"
        return True, None

    @staticmethod
    def validate_price(price: float) -> Tuple[bool, Optional[str]]:
        # 验证买入价格
        # 规则: 价格 > 0
        if price <= 0:
            return False, "买入价格必须大于0"
        return True, None

    @staticmethod
    def validate_sufficient_cash(
        current_cash: float,
        total_cost: float
    ) -> Tuple[bool, Optional[str]]:
        # 验证资金充足
        # 规则: 可用资金 >= 总成本（包括手续费）
        if current_cash < total_cost:
            return False, f"资金不足，需要 {total_cost:.2f} 元，可用资金 {current_cash:.2f} 元"
        return True, None

    @staticmethod
    def validate_transaction_date(
        transaction_date: str,
        current_date: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        # 验证交易日期
        # 规则: 交易日期 <= 当前日期（不能是未来日期）
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')

        try:
            txn_date = datetime.strptime(transaction_date, '%Y-%m-%d')
            curr_date = datetime.strptime(current_date, '%Y-%m-%d')
            if txn_date > curr_date:
                return False, "不能进行未来交易"
            return True, None
        except ValueError:
            return False, "日期格式错误，应为 YYYY-MM-DD"

    @staticmethod
    def validate_no_same_day_buy_sell(
        account_id: str,
        stock_code: str,
        transaction_date: str,
        existing_transactions: list
    ) -> Tuple[bool, Optional[str]]:
        # 买入没有任何限制，总是允许
        # 规则: 买入可以在任何时间进行，不受同日买卖限制
        return True, None

    @staticmethod
    def validate_selection_history(
        stock_code: str,
        days: int = 30,
        allow_not_in_history: bool = False
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        # 验证股票是否在选股历史中
        # 参数:
        #   stock_code: 股票代码
        #   days: 检查天数范围（默认30天）
        #   allow_not_in_history: 是否允许股票不在历史中（默认False，即必须在历史中）
        # 返回: (是否通过验证, 错误信息, 选股历史信息)
        try:
            # 验证代码格式
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return False, "股票代码格式错误", None
            
            # 查询选股历史
            result = StockHelper.check_selection_history(stock_code, days=days)
            
            # 如果不在历史中且不允许
            if not result['in_history'] and not allow_not_in_history:
                return False, f"股票不在最近{days}天的选股历史中", result
            
            # 返回验证成功
            return True, None, result
        
        except Exception as e:
            # 记录错误
            return False, f"验证选股历史失败: {str(e)}", None

    @staticmethod
    def validate_buy_price(price: float, stock_code: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        # 验证买入价格是否在当天价格区间内
        # 参数:
        #   price: 买入价格
        #   stock_code: 股票代码
        # 返回: (是否通过验证, 错误信息, 价格区间信息)
        try:
            # 验证代码格式
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return False, "股票代码格式错误", None
            
            # 获取价格区间
            from trading.stock_helper import StockHelper
            price_range = StockHelper.get_price_range(stock_code)
            
            # 如果无法获取价格区间
            if not price_range:
                return False, "无法获取该股票的实时价格数据", None
            
            # 验证价格是否在区间内
            low_price = price_range['low_price']
            high_price = price_range['high_price']
            
            if price < low_price or price > high_price:
                error_msg = f"买入价格 {price:.2f} 不在当天价格区间内，当天价格区间：{low_price:.2f} - {high_price:.2f} 元"
                return False, error_msg, price_range
            
            # 返回验证成功
            return True, None, price_range
        
        except Exception as e:
            # 记录错误
            return False, f"验证买入价格失败: {str(e)}", None

    @staticmethod
    def validate_buy(
        quantity: int,
        price: float,
        current_cash: float,
        total_cost: float,
        transaction_date: str,
        current_date: Optional[str] = None,
        account_id: Optional[str] = None,
        stock_code: Optional[str] = None,
        existing_transactions: Optional[list] = None,
        validate_selection: bool = True,
        allow_not_in_history: bool = False,
        validate_price: bool = True
    ) -> Tuple[bool, Optional[str]]:
        # 综合验证买入条件
        # 参数:
        #   validate_selection: 是否验证选股历史（默认True）
        #   allow_not_in_history: 是否允许股票不在历史中（默认False）
        #   validate_price: 是否验证价格区间（默认True）
        # 验证数量
        valid, error = BuyValidator.validate_quantity(quantity)
        if not valid:
            return False, error

        # 验证价格基本有效性
        valid, error = BuyValidator.validate_price(price)
        if not valid:
            return False, error

        # 验证资金充足
        valid, error = BuyValidator.validate_sufficient_cash(
            current_cash,
            total_cost
        )
        if not valid:
            return False, error

        # 验证交易日期
        valid, error = BuyValidator.validate_transaction_date(
            transaction_date,
            current_date
        )
        if not valid:
            return False, error

        # 验证不能跨日买卖
        if (account_id and stock_code and existing_transactions is not None):
            valid, error = BuyValidator.validate_no_same_day_buy_sell(
                account_id,
                stock_code,
                transaction_date,
                existing_transactions
            )
            if not valid:
                return False, error

        # 验证选股历史（如果启用）
        if validate_selection and stock_code:
            valid, error, _ = BuyValidator.validate_selection_history(
                stock_code,
                days=30,
                allow_not_in_history=allow_not_in_history
            )
            if not valid:
                return False, error

        # 验证价格区间（如果启用）
        if validate_price and stock_code:
            valid, error, _ = BuyValidator.validate_buy_price(price, stock_code)
            if not valid:
                return False, error

        return True, None


class SellValidator:
    """卖出验证器"""

    @staticmethod
    def validate_quantity(quantity: int) -> Tuple[bool, Optional[str]]:
        # 验证卖出数量
        # 规则: 数量 > 0 且为整数
        if not isinstance(quantity, int):
            return False, "卖出数量必须为整数"
        if quantity <= 0:
            return False, "卖出数量必须大于0"
        return True, None

    @staticmethod
    def validate_sufficient_position(
        quantity: int,
        position_quantity: int
    ) -> Tuple[bool, Optional[str]]:
        # 验证持仓充足
        # 规则: 卖出数量 <= 持仓数量
        if quantity > position_quantity:
            return False, f"卖出数量超过持仓数量，持仓 {position_quantity}，卖出 {quantity}"
        return True, None

    @staticmethod
    def validate_price(price: float) -> Tuple[bool, Optional[str]]:
        # 验证卖出价格
        # 规则: 价格 > 0
        if price <= 0:
            return False, "卖出价格必须大于0"
        return True, None

    @staticmethod
    def validate_transaction_date(
        transaction_date: str,
        current_date: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        # 验证交易日期
        # 规则: 交易日期 <= 当前日期（不能是未来日期）
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')

        try:
            txn_date = datetime.strptime(transaction_date, '%Y-%m-%d')
            curr_date = datetime.strptime(current_date, '%Y-%m-%d')
            if txn_date > curr_date:
                return False, "不能进行未来交易"
            return True, None
        except ValueError:
            return False, "日期格式错误，应为 YYYY-MM-DD"

    @staticmethod
    def validate_t_plus_one(
        transaction_date: str,
        last_buy_date: Optional[str]
    ) -> Tuple[bool, Optional[str]]:
        # 验证 T+1 原则
        # 规则: 卖出日期必须晚于最后一次买入日期（不能同日买卖）
        if last_buy_date is None:
            return True, None

        try:
            txn_date = datetime.strptime(transaction_date, '%Y-%m-%d')
            buy_date = datetime.strptime(last_buy_date, '%Y-%m-%d')
            if txn_date <= buy_date:
                return False, "不能同日买卖（T+1原则）"
            return True, None
        except ValueError:
            return False, "日期格式错误，应为 YYYY-MM-DD"

    @staticmethod
    def validate_no_same_day_buy_sell(
        account_id: str,
        stock_code: str,
        transaction_date: str,
        sell_quantity: int,
        existing_transactions: list
    ) -> Tuple[bool, Optional[str]]:
        # 验证当天买入的股票不能卖出
        # 规则: 只有当天买入的不能卖出
        # 计算当天该股票的买入数量
        today_buy_quantity = 0
        
        for txn in existing_transactions:
            if (txn['account_id'] == account_id and
                txn['stock_code'] == stock_code and
                txn['transaction_date'] == transaction_date and
                txn['transaction_type'] == 'BUY'):
                today_buy_quantity += txn['quantity']
        
        # 如果当天有买入，则不能卖出
        if today_buy_quantity > 0:
            return False, f"当天买入的股票不能卖出，当天买入数量: {today_buy_quantity}"
        
        return True, None

    @staticmethod
    def validate_sell_price(price: float, stock_code: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        # 验证卖出价格是否在当天价格区间内
        # 参数:
        #   price: 卖出价格
        #   stock_code: 股票代码
        # 返回: (是否通过验证, 错误信息, 价格区间信息)
        try:
            # 验证代码格式
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return False, "股票代码格式错误", None
            
            # 获取价格区间
            from trading.stock_helper import StockHelper
            price_range = StockHelper.get_price_range(stock_code)
            
            # 如果无法获取价格区间
            if not price_range:
                return False, "无法获取该股票的实时价格数据", None
            
            # 验证价格是否在区间内
            low_price = price_range['low_price']
            high_price = price_range['high_price']
            
            if price < low_price or price > high_price:
                error_msg = f"卖出价格 {price:.2f} 不在当天价格区间内，当天价格区间：{low_price:.2f} - {high_price:.2f} 元"
                return False, error_msg, price_range
            
            # 返回验证成功
            return True, None, price_range
        
        except Exception as e:
            # 记录错误
            return False, f"验证卖出价格失败: {str(e)}", None

    @staticmethod
    def validate_sell(
        quantity: int,
        price: float,
        position_quantity: int,
        transaction_date: str,
        last_buy_date: Optional[str] = None,
        current_date: Optional[str] = None,
        account_id: Optional[str] = None,
        stock_code: Optional[str] = None,
        existing_transactions: Optional[list] = None,
        validate_price: bool = True
    ) -> Tuple[bool, Optional[str]]:
        # 综合验证卖出条件
        # 参数:
        #   validate_price: 是否验证价格区间（默认True）
        # 验证数量
        valid, error = SellValidator.validate_quantity(quantity)
        if not valid:
            return False, error

        # 验证持仓充足
        valid, error = SellValidator.validate_sufficient_position(
            quantity,
            position_quantity
        )
        if not valid:
            return False, error

        # 验证价格基本有效性
        valid, error = SellValidator.validate_price(price)
        if not valid:
            return False, error

        # 验证交易日期
        valid, error = SellValidator.validate_transaction_date(
            transaction_date,
            current_date
        )
        if not valid:
            return False, error

        # 验证 T+1 原则
        valid, error = SellValidator.validate_t_plus_one(
            transaction_date,
            last_buy_date
        )
        if not valid:
            return False, error

        # 验证不能跨日买卖
        if (account_id and stock_code and existing_transactions is not None):
            valid, error = SellValidator.validate_no_same_day_buy_sell(
                account_id,
                stock_code,
                transaction_date,
                quantity,
                existing_transactions
            )
            if not valid:
                return False, error

        # 验证价格区间（如果启用）
        if validate_price and stock_code:
            valid, error, _ = SellValidator.validate_sell_price(price, stock_code)
            if not valid:
                return False, error

        return True, None
