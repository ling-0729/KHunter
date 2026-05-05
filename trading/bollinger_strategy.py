"""
布林带策略实现
基于布林带的支撑压力判断
"""
import pandas as pd
from trading.timing_strategies import TimingStrategy, TimingResult
from trading.technical_indicators import TechnicalIndicators
from typing import Dict, Optional


class BollingerStrategy(TimingStrategy):
    """布林带策略"""
    
    def __init__(self, config):
        """初始化布林带策略
        
        Args:
            config: 策略配置
        """
        super().__init__(config)
        
        # 初始化技术指标计算
        self.technical_indicators = TechnicalIndicators()
        
        # 默认参数
        self.period = self.config.get('period', 20)  # 布林带周期
        self.multiplier = self.config.get('multiplier', 2)  # 标准差倍数
        self.base_position_amount = self.config.get('base_position_amount', 50000)  # 底仓金额（元）
        self.position_ratio = self.config.get('position_ratio', 0.05)  # 仓位比例（占总资金）
        self.use_fixed_amount = self.config.get('use_fixed_amount', True)  # 是否使用固定金额（False则使用仓位比例）
        self.buy_limit = self.config.get('buy_limit', 1.01)  # 买入限价比例
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算布林带指标
        
        Args:
            df: 股票数据
            
        Returns:
            添加了布林带的DataFrame
        """
        result = df.copy()
        
        # 确保数据按日期正序排列
        if len(result) > 1 and result['date'].iloc[0] > result['date'].iloc[1]:
            result = result.iloc[::-1].reset_index(drop=True)
        
        # 使用技术指标计算模块计算布林带
        mid, upper, lower = self.technical_indicators.calculate_bollinger_bands(result, self.period, self.multiplier)
        result['boll_mid'] = mid
        result['boll_upper'] = upper
        result['boll_lower'] = lower
        
        return result
    
    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None, cash: Optional[float] = None, use_prev_day_signal: bool = True) -> TimingResult:
        """获取布林带策略择时结果
        
        Args:
            df: 股票数据
            position: 持仓信息
            cash: 可用资金
            use_prev_day_signal: 是否使用前一天信号（回测模式），默认True
                - True: 使用T-1日指标判断信号（回测模式）
                - False: 使用T日指标判断信号（狩猎场模式）
            
        Returns:
            择时结果
        """
        result = TimingResult()
        
        # 计算布林带
        df = self.calculate_indicators(df)
        
        # 获取最新数据
        latest = df.iloc[-1]
        current_price = latest['close']
        trade_price = latest['open']  # 交易价格为当天开盘价
        
        # 根据模式选择信号判断基准
        if use_prev_day_signal and len(df) >= 2:
            # 回测模式：使用T-1日指标判断信号
            signal_bar = df.iloc[-2]
        else:
            # 狩猎场模式：使用T日指标判断信号
            signal_bar = latest
        
        # 计算支撑位和压力位
        if pd.notna(signal_bar['boll_lower']):
            result.support_level = signal_bar['boll_lower']
        if pd.notna(signal_bar['boll_upper']):
            result.resistance_level = signal_bar['boll_upper']
        
        # 买入条件：价格触及或跌破下轨
        if pd.notna(signal_bar['boll_lower']) and current_price <= signal_bar['boll_lower']:
            result.is_buy = True
            # 信号强度：(下轨 - 价格) / 下轨
            signal_strength = (signal_bar['boll_lower'] - current_price) / signal_bar['boll_lower']
            result.signal_strength = min(abs(signal_strength), 1.0)
            if use_prev_day_signal:
                result.message = f"前一天价格触及下轨 {signal_bar['boll_lower']:.2f}，买入信号"
            else:
                result.message = f"价格触及下轨 {signal_bar['boll_lower']:.2f}，买入信号"
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
        
        # 卖出条件：价格触及或突破上轨
        if pd.notna(signal_bar['boll_upper']) and current_price >= signal_bar['boll_upper']:
            result.is_sell = True
            # 信号强度：(价格 - 上轨) / 上轨
            signal_strength = (current_price - signal_bar['boll_upper']) / signal_bar['boll_upper']
            result.signal_strength = min(signal_strength, 1.0)
            if use_prev_day_signal:
                result.message = f"前一天价格触及上轨 {signal_bar['boll_upper']:.2f}，卖出信号"
            else:
                result.message = f"价格触及上轨 {signal_bar['boll_upper']:.2f}，卖出信号"
            result.trade_type = 'sell'
            # 清仓卖出：不需要100的整数倍
            if position:
                result.sell_quantity = position.get('quantity', 0)
        
        # 填充指标值（始终用最新数据）
        result.indicators['boll_mid'] = latest['boll_mid'] if pd.notna(latest['boll_mid']) else 0
        result.indicators['boll_upper'] = latest['boll_upper'] if pd.notna(latest['boll_upper']) else 0
        result.indicators['boll_lower'] = latest['boll_lower'] if pd.notna(latest['boll_lower']) else 0
        result.indicators['boll_width'] = (latest['boll_upper'] - latest['boll_lower']) if pd.notna(latest['boll_upper']) and pd.notna(latest['boll_lower']) else 0
        result.indicators['current_price'] = current_price
        
        return result
    
    def calculate_support(self, df: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """计算布林带策略的支撑位
        
        Args:
            df: 股票数据
            key_date: 关键日期
            
        Returns:
            支撑位价格
        """
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        
        if pd.notna(latest['boll_lower']):
            return latest['boll_lower']
        
        return 0.0
