"""
支撑位策略实现
整合现有的支撑位计算逻辑
"""
import pandas as pd
from trading.timing_strategies import TimingStrategy, TimingResult
from typing import Dict, Optional


class SupportStrategy(TimingStrategy):
    """支撑位策略"""
    
    def __init__(self, config):
        """初始化支撑位策略
        
        Args:
            config: 策略配置
        """
        super().__init__(config)
        
        # 默认参数
        self.method = self.config.get('method', 'ma20')  # 支撑位计算方法
        self.base_position_amount = self.config.get('base_position_amount', 50000)  # 底仓金额（元）
        self.position_ratio = self.config.get('position_ratio', 0.05)  # 仓位比例（占总资金）
        self.use_fixed_amount = self.config.get('use_fixed_amount', True)  # 是否使用固定金额（False则使用仓位比例）
        self.buy_limit = self.config.get('buy_limit', 1.01)  # 买入限价比例
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算支撑位相关指标
        
        Args:
            df: 股票数据
            
        Returns:
            添加了支撑位的DataFrame
        """
        result = df.copy()
        
        # 确保数据按日期正序排列
        if len(result) > 1 and result['date'].iloc[0] > result['date'].iloc[1]:
            result = result.iloc[::-1].reset_index(drop=True)
        
        # 计算MA20
        result['ma20'] = result['close'].rolling(window=20).mean()
        
        return result
    
    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None, cash: Optional[float] = None, use_prev_day_signal: bool = True) -> TimingResult:
        """获取支撑位策略择时结果
        
        Args:
            df: 股票数据
            position: 持仓信息
            cash: 可用资金
            
        Returns:
            择时结果
        """
        result = TimingResult()
        
        # 计算支撑位
        support_level = self.calculate_support(df)
        result.support_level = support_level
        
        # 获取最新价格
        latest = df.iloc[-1]
        current_price = latest['close']
        trade_price = latest['open']  # 交易价格为当天开盘价
        
        # 买入条件：价格在支撑位的-1%~3%区间
        if support_level > 0:
            # 价格在支撑位的-1%~3%区间（即支撑价的99%~103%）
            lower_bound = support_level * 0.99
            upper_bound = support_level * 1.03
            
            if lower_bound <= current_price <= upper_bound:
                result.is_buy = True
                result.signal_strength = 0.8
                result.message = f"价格在支撑位区间 {support_level:.2f}，买入信号"
                result.trade_type = 'buy'
                # 计算买入数量：根据固定金额（资金限制由回测引擎处理）
                if self.use_fixed_amount:
                    # 使用固定金额
                    buy_amount = self.base_position_amount
                else:
                    # 使用仓位比例（暂用固定金额兜底）
                    buy_amount = self.base_position_amount
                # A股规则：买入数量必须是100的整数倍
                result.buy_quantity = int(buy_amount / trade_price) // 100 * 100
        
        # 卖出条件：持有10天后卖出
        if position:
            # 检查是否持有超过10天
            buy_date = position.get('buy_date')
            if buy_date:
                # 计算持有天数
                import datetime
                if isinstance(buy_date, str):
                    buy_date = datetime.datetime.strptime(buy_date, '%Y-%m-%d').date()
                current_date_str = df.iloc[-1]['date']
                if isinstance(current_date_str, str):
                    current_date = datetime.datetime.strptime(current_date_str, '%Y-%m-%d').date()
                else:
                    current_date = current_date_str
                
                hold_days = (current_date - buy_date).days
                if hold_days >= 10:
                    result.is_sell = True
                    result.signal_strength = 0.8
                    result.message = f"持有{hold_days}天，卖出信号"
                    result.trade_type = 'sell'
                    # 清仓卖出：不需要100的整数倍
                    result.sell_quantity = position.get('quantity', 0)
        
        # 填充指标值
        result.indicators['support_level'] = support_level
        result.indicators['current_price'] = current_price
        result.indicators['method'] = self.method
        
        return result
    
    def calculate_support(self, df: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """计算支撑位
        
        Args:
            df: 股票数据
            key_date: 关键日期
            
        Returns:
            支撑位价格
        """
        # 确保数据按日期正序排列
        if len(df) > 1 and df['date'].iloc[0] > df['date'].iloc[1]:
            df = df.iloc[::-1].reset_index(drop=True)
        
        if self.method == 'ma20':
            # 20日均线支撑位
            if len(df) >= 20:
                return df['close'].rolling(window=20).mean().iloc[-1]
        
        elif self.method == 'key_close_5':
            # 关键日收盘价下5%
            if key_date and len(df) > 0:
                # 查找关键日数据
                key_date_data = df[df['date'] == key_date]
                if not key_date_data.empty:
                    key_close = key_date_data.iloc[0]['close']
                    return key_close * 0.95
        
        elif self.method == 'key_open':
            # 关键日开盘价
            if key_date and len(df) > 0:
                key_date_data = df[df['date'] == key_date]
                if not key_date_data.empty:
                    return key_date_data.iloc[0]['open']
        
        elif self.method == 'key_close':
            # 关键日收盘价
            if key_date and len(df) > 0:
                key_date_data = df[df['date'] == key_date]
                if not key_date_data.empty:
                    return key_date_data.iloc[0]['close']
        
        # fallback: 使用20日均线
        if len(df) >= 20:
            return df['close'].rolling(window=20).mean().iloc[-1]
        
        return 0.0
