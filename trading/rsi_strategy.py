"""
RSI策略实现
基于相对强弱指数的超买超卖判断
"""
import pandas as pd
from trading.timing_strategies import TimingStrategy, TimingResult
from trading.technical_indicators import TechnicalIndicators
from typing import Dict, Optional


class RSIStrategy(TimingStrategy):
    """RSI策略"""
    
    def __init__(self, config):
        """初始化RSI策略
        
        Args:
            config: 策略配置
        """
        super().__init__(config)
        
        # 初始化技术指标计算
        self.technical_indicators = TechnicalIndicators()
        
        # 默认参数
        self.rsi_period = self.config.get('rsi_period', 14)  # RSI周期
        self.oversold = self.config.get('oversold', 30)  # 超卖阈值
        self.overbought = self.config.get('overbought', 70)  # 超买阈值
        self.base_position_amount = self.config.get('base_position_amount', 50000)  # 底仓金额（元）
        self.position_ratio = self.config.get('position_ratio', 0.05)  # 仓位比例（占总资金）
        self.use_fixed_amount = self.config.get('use_fixed_amount', True)  # 是否使用固定金额（False则使用仓位比例）
        self.buy_limit = self.config.get('buy_limit', 1.01)  # 买入限价比例
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算RSI指标
        
        Args:
            df: 股票数据
            
        Returns:
            添加了RSI的DataFrame
        """
        result = df.copy()
        
        # 确保数据按日期正序排列
        if len(result) > 1 and result['date'].iloc[0] > result['date'].iloc[1]:
            result = result.iloc[::-1].reset_index(drop=True)
        
        # 使用技术指标计算模块计算RSI
        rsi = self.technical_indicators.calculate_rsi(result, self.rsi_period)
        result['rsi'] = rsi
        
        return result
    
    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None, cash: Optional[float] = None, use_prev_day_signal: bool = True) -> TimingResult:
        """获取RSI策略择时结果
        
        Args:
            df: 股票数据
            position: 持仓信息
            cash: 可用资金
            use_prev_day_signal: 是否使用前一天信号（回测模式），默认True
                - True: 使用T-1日RSI判断信号（回测模式）
                - False: 使用T日RSI判断信号（狩猎场模式）
            
        Returns:
            择时结果
        """
        result = TimingResult()
        
        # 计算RSI
        df = self.calculate_indicators(df)
        
        # 获取最新数据
        latest = df.iloc[-1]
        
        # 根据模式选择信号判断基准
        if use_prev_day_signal and len(df) >= 2:
            # 回测模式：使用T-1日RSI判断信号，T日开盘价交易
            signal_bar = df.iloc[-2]
            rsi = signal_bar['rsi'] if pd.notna(signal_bar['rsi']) else 50
            trade_price = latest['open']  # 交易价格为T日开盘价
        else:
            # 狩猎场模式：使用T日RSI判断信号
            signal_bar = latest
            rsi = latest['rsi'] if pd.notna(latest['rsi']) else 50
            trade_price = latest['open']
        
        current_price = latest['close']
        
        # 买入条件：RSI超卖
        if rsi < self.oversold:
            result.is_buy = True
            # 信号强度：(超卖阈值 - RSI) / 超卖阈值
            signal_strength = (self.oversold - rsi) / self.oversold
            result.signal_strength = min(signal_strength, 1.0)
            if use_prev_day_signal:
                result.message = f"前一天RSI超卖 ({rsi:.1f} < {self.oversold})，买入信号"
            else:
                result.message = f"RSI超卖 ({rsi:.1f} < {self.oversold})，买入信号"
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
        
        # 卖出条件：RSI超买
        if rsi > self.overbought:
            result.is_sell = True
            # 信号强度：(RSI - 超买阈值) / (100 - 超买阈值)
            signal_strength = (rsi - self.overbought) / (100 - self.overbought)
            result.signal_strength = min(signal_strength, 1.0)
            if use_prev_day_signal:
                result.message = f"前一天RSI超买 ({rsi:.1f} > {self.overbought})，卖出信号"
            else:
                result.message = f"RSI超买 ({rsi:.1f} > {self.overbought})，卖出信号"
            result.trade_type = 'sell'
            # 清仓卖出：不需要100的整数倍
            if position:
                result.sell_quantity = position.get('quantity', 0)
        
        # 计算支撑位和压力位
        # RSI策略的支撑位和压力位基于价格通道
        if len(df) >= 20:
            # 20日最高价和最低价
            high_20 = df['high'].tail(20).max()
            low_20 = df['low'].tail(20).min()
            result.resistance_level = high_20
            result.support_level = low_20
        
        # 填充指标值
        result.indicators['rsi'] = rsi
        result.indicators['oversold'] = self.oversold
        result.indicators['overbought'] = self.overbought
        
        return result
    
    def calculate_support(self, df: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """计算RSI策略的支撑位
        
        Args:
            df: 股票数据
            key_date: 关键日期
            
        Returns:
            支撑位价格
        """
        # 使用20日最低价作为支撑位
        if len(df) >= 20:
            return df['low'].tail(20).min()
        
        return 0.0
