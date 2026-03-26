# 模拟交易计算引擎
# 提供成本价、手续费、收益等计算功能

from typing import Tuple


class CostPriceCalculator:
    """成本价计算器"""

    @staticmethod
    def calculate_weighted_average_cost(
        current_quantity: int,
        current_cost_price: float,
        buy_quantity: int,
        buy_price: float,
        commission: float = 0.0
    ) -> float:
        # 计算加权平均成本价，包含手续费分摊
        # 公式: 新成本价 = (原持仓数量 × 原成本价 + 买入数量 × 买入价格 + 手续费) / (原持仓数量 + 买入数量)
        if current_quantity == 0:
            # 首次买入，成本价 = (买入金额 + 手续费) / 买入数量
            total_cost = buy_quantity * buy_price + commission
            new_cost_price = total_cost / buy_quantity
            return round(new_cost_price, 4)

        # 加权平均成本，包含手续费分摊
        total_cost = (current_quantity * current_cost_price +
                     buy_quantity * buy_price + commission)
        total_quantity = current_quantity + buy_quantity
        new_cost_price = total_cost / total_quantity
        return round(new_cost_price, 4)

    @staticmethod
    def calculate_sell_cost_basis(
        quantity: int,
        cost_price: float
    ) -> float:
        # 计算卖出的成本基数
        # 公式: 成本 = 卖出数量 × 成本价
        cost_basis = quantity * cost_price
        return round(cost_basis, 2)


class CommissionCalculator:
    """手续费计算器"""

    # 买入手续费率：0.02%，最低 5 元
    BUY_COMMISSION_RATE = 0.0002
    BUY_COMMISSION_MIN = 5.0

    # 卖出手续费率：0.02%，最低 5 元
    SELL_COMMISSION_RATE = 0.0002
    SELL_COMMISSION_MIN = 5.0

    # 印花税率：0.1%（仅卖出）
    STAMP_TAX_RATE = 0.001

    @staticmethod
    def calculate_buy_commission(amount: float) -> float:
        # 计算买入手续费
        # 公式: 手续费 = max(成交金额 × 0.02%, 5)
        commission = amount * CommissionCalculator.BUY_COMMISSION_RATE
        commission = max(commission, CommissionCalculator.BUY_COMMISSION_MIN)
        return round(commission, 2)

    @staticmethod
    def calculate_sell_commission(amount: float) -> float:
        # 计算卖出手续费
        # 公式: 手续费 = max(成交金额 × 0.02%, 5)
        commission = amount * CommissionCalculator.SELL_COMMISSION_RATE
        commission = max(commission, CommissionCalculator.SELL_COMMISSION_MIN)
        return round(commission, 2)

    @staticmethod
    def calculate_stamp_tax(amount: float) -> float:
        # 计算印花税（仅卖出）
        # 公式: 印花税 = 成交金额 × 0.1%
        stamp_tax = amount * CommissionCalculator.STAMP_TAX_RATE
        return round(stamp_tax, 2)

    @staticmethod
    def calculate_buy_total_cost(
        amount: float,
        commission: float
    ) -> float:
        # 计算买入总成本
        # 公式: 总成本 = 成交金额 + 手续费
        total_cost = amount + commission
        return round(total_cost, 2)

    @staticmethod
    def calculate_sell_net_proceeds(
        amount: float,
        commission: float,
        stamp_tax: float
    ) -> float:
        # 计算卖出净收益
        # 公式: 净收益 = 成交金额 - 手续费 - 印花税
        net_proceeds = amount - commission - stamp_tax
        return round(net_proceeds, 2)


class ProfitCalculator:
    """收益计算器"""

    @staticmethod
    def calculate_position_profit_loss(
        quantity: int,
        cost_price: float,
        current_price: float
    ) -> Tuple[float, float]:
        # 计算持仓收益和收益率
        # 公式: 收益 = 市值 - 成本 = 数量 × (当前价 - 成本价)
        # 收益率 = 收益 / 成本 × 100%
        market_value = quantity * current_price
        cost_basis = quantity * cost_price
        profit_loss = market_value - cost_basis

        if cost_basis == 0:
            profit_loss_rate = 0.0
        else:
            profit_loss_rate = (profit_loss / cost_basis) * 100

        return (round(profit_loss, 2), round(profit_loss_rate, 2))

    @staticmethod
    def calculate_sell_profit_loss(
        quantity: int,
        cost_price: float,
        sell_price: float,
        commission: float,
        stamp_tax: float
    ) -> Tuple[float, float]:
        # 计算卖出收益和收益率
        # 公式: 收益 = 卖出金额 - 成本 - 手续费 - 印花税
        # 收益率 = 收益 / 成本 × 100%
        sell_amount = quantity * sell_price
        cost_basis = quantity * cost_price
        profit_loss = sell_amount - cost_basis - commission - stamp_tax

        if cost_basis == 0:
            profit_loss_rate = 0.0
        else:
            profit_loss_rate = (profit_loss / cost_basis) * 100

        return (round(profit_loss, 2), round(profit_loss_rate, 2))

    @staticmethod
    def calculate_account_profit_loss(
        total_assets: float,
        initial_cash: float
    ) -> Tuple[float, float]:
        # 计算账户总收益和收益率
        # 公式: 总收益 = 总资产 - 初始资金
        # 收益率 = 总收益 / 初始资金 × 100%
        total_profit_loss = total_assets - initial_cash

        if initial_cash == 0:
            profit_loss_rate = 0.0
        else:
            profit_loss_rate = (total_profit_loss / initial_cash) * 100

        return (round(total_profit_loss, 2), round(profit_loss_rate, 2))

    @staticmethod
    def calculate_market_value(
        quantity: int,
        current_price: float
    ) -> float:
        # 计算市值
        # 公式: 市值 = 数量 × 当前价
        market_value = quantity * current_price
        return round(market_value, 2)
