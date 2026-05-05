"""
海归策略实现
基于唐奇安通道和ATR的趋势跟踪策略
"""
import pandas as pd
from trading.timing_strategies import TimingStrategy, TimingResult
from typing import Dict, Optional


def same_row(df: pd.DataFrame, row: pd.Series) -> pd.Series:
    """判断DataFrame中与给定Series相同的行"""
    return (df['date'] == row['date']) & (df['close'] == row['close'])


# 经典海龟配置（趋势跟踪，长周期）
CLASSIC_PRESET = {
    'n_entry': 20,        # 入场通道：20日高点
    'n_exit': 10,         # 出场通道：10日低点
    'atr_period': 20,     # ATR周期：20日
    'entry_atr': 0.02,    # 入场ATR比例
    'add_atr': 0.5,       # 加仓ATR间隔
    'exit_atr': 2.0,      # ATR止损倍数
}

# 短线海龟配置（短期趋势，快进快出）
SHORT_TURTLE_PRESET = {
    'n_entry': 10,        # 入场通道：10日高点
    'n_exit': 5,          # 出场通道：5日低点
    'atr_period': 10,     # ATR周期：10日
    'entry_atr': 0.02,    # 入场ATR比例
    'add_atr': 0.5,       # 加仓ATR间隔
    'exit_atr': 2.0,      # ATR止损倍数
}

# 超短海龟配置（强势股高频交易）
ULTRA_SHORT_PRESET = {
    'n_entry': 6,         # 入场通道：6日高点
    'n_exit': 3,          # 出场通道：3日低点
    'atr_period': 6,      # ATR周期：6日
    'entry_atr': 0.02,    # 入场ATR比例
    'add_atr': 0.5,       # 加仓ATR间隔
    'exit_atr': 2.0,      # ATR止损倍数
}


class TurtleStrategy(TimingStrategy):
    """海归策略"""
    
    # 预设配置映射
    PRESETS = {
        'classic': CLASSIC_PRESET,       # 经典海龟：20/10
        'short': SHORT_TURTLE_PRESET,    # 短线海龟：10/5
        'ultra_short': ULTRA_SHORT_PRESET,  # 超短海龟：6/3
    }
    
    def __init__(self, config):
        """初始化海归策略
        
        Args:
            config: 策略配置
        """
        super().__init__(config)
        
        # 应用预设配置（如果指定了preset）
        preset_name = self.config.get('preset', 'short')  # 默认短线海龟
        preset = self.PRESETS.get(preset_name, CLASSIC_PRESET)
        
        # 从预设或直接配置中获取参数
        self.n_entry = self.config.get('n_entry', preset['n_entry'])    # 入场通道周期
        self.n_exit = self.config.get('n_exit', preset['n_exit'])        # 出场通道周期
        self.atr_period = self.config.get('atr_period', preset['atr_period'])  # ATR周期
        self.entry_atr = self.config.get('entry_atr', preset['entry_atr'])    # 入场ATR比例
        self.add_atr = self.config.get('add_atr', preset['add_atr'])          # 加仓ATR间隔
        self.exit_atr = self.config.get('exit_atr', preset['exit_atr'])        # 出场ATR止损倍数
        self.base_position_amount = self.config.get('base_position_amount', 20000)  # 底仓金额（元）
        self.use_fixed_amount = self.config.get('use_fixed_amount', True)  # 是否使用固定金额
        
        # 向后兼容旧参数名
        self.n1 = self.n_entry   # 入场上线周期
        self.n2 = self.n_exit     # 出场下线周期
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算海归策略所需指标
        
        Args:
            df: 股票数据
            
        Returns:
            添加了指标的DataFrame
        """
        result = df.copy()
        
        # 确保数据按日期正序排列
        if len(result) > 1 and result['date'].iloc[0] > result['date'].iloc[1]:
            result = result.iloc[::-1].reset_index(drop=True)
        
        # 计算唐奇安通道
        # 关键：signal_bar['up'] 应该是"基于之前N天(不含当天)"的N日最高价
        # 因为买入信号是判断 signal_bar['high'] > signal_bar['up']
        # 所以 up 需要向右偏移1天，这样 signal_bar['up'] = T-1日及之前N-1天的最大值
        # 然后 T日 的 high 突破这个值时触发买入
        result['up'] = result['high'].rolling(window=self.n1).max().shift(1)   # 入场上线（不含当天）
        result['down'] = result['low'].rolling(window=self.n2).min().shift(1)  # 出场下线（不含当天，不直接用于买入判断）
        
        # 计算ATR（标准三因子公式 + SMA）
        # 经典海龟使用简单移动平均（SMA），而非EWM
        prev_close = result['close'].shift(1)
        tr1 = result['high'] - result['low']
        tr2 = (result['high'] - prev_close).abs()
        tr3 = (result['low'] - prev_close).abs()
        result['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        result['atr'] = result['tr'].rolling(window=self.atr_period).mean()
        
        # 计算均线过滤（20日均线）
        result['ma20'] = result['close'].rolling(window=20).mean()
        
        return result
    
    def _check_buy_signal(self, df: pd.DataFrame, signal_bar: pd.Series, latest: pd.Series, use_prev_day_signal: bool = True) -> bool:
        """检查买入信号
        
        Args:
            df: 股票数据
            signal_bar: 信号K线
            latest: 最新K线
            use_prev_day_signal: 是否使用前一天信号
            
        Returns:
            是否满足买入条件
        """
        # 1. 价格突破上线（使用突破当日的high与up比较）
        if not (pd.notna(signal_bar['up']) and bool(signal_bar['high'] > signal_bar['up'])):
            return False
        
        # 2. 上影线过滤：上影线不超过4%
        # 上影线 = high - max(open, close)，相对于实体上端计算
        # 这样对阳线和阴线都适用
        upper_shadow = signal_bar['high'] - max(signal_bar['open'], signal_bar['close'])
        upper_shadow_ratio = upper_shadow / max(signal_bar['open'], signal_bar['close'])
        if upper_shadow_ratio > 0.04:
            return False
        
        # 3. 阳线过滤：信号发出当日必须是阳线且收盘涨幅 > 0%
        # 回测模式（T-1日信号）：检查T-1日是否是阳线且收盘涨幅>0%
        # 狩猎场模式（T日信号，收盘后）：检查T日是否是阳线且收盘涨幅>0%
        # 找到signal_bar在df中的实际位置
        try:
            signal_bar_idx = df[same_row(df, signal_bar)].index[0]
            # 前一天索引
            prev_day_idx = signal_bar_idx - 1
            if prev_day_idx >= 0:
                prev_close = df['close'].iloc[prev_day_idx]
                is_bullish = bool(signal_bar['close'] > signal_bar['open'])  # 阳线
                is_rising = bool(signal_bar['close'] > prev_close)  # 收盘涨幅>0
                if not (is_bullish and is_rising):
                    return False
        except Exception:
            # 如果无法定位signal_bar，使用固定索引（兼容旧逻辑）
            if use_prev_day_signal:
                prev_close_idx = len(df) - 3
                if prev_close_idx >= 0:
                    prev_close = df['close'].iloc[prev_close_idx]
                    is_bullish = bool(signal_bar['close'] > signal_bar['open'])
                    is_rising = bool(signal_bar['close'] > prev_close)
                    if not (is_bullish and is_rising):
                        return False
            else:
                prev_close_idx = len(df) - 2
                if prev_close_idx >= 0:
                    prev_close = df['close'].iloc[prev_close_idx]
                    is_bullish = bool(signal_bar['close'] > signal_bar['open'])
                    is_rising = bool(signal_bar['close'] > prev_close)
                    if not (is_bullish and is_rising):
                        return False
        
        # 4. 均线过滤：价格在均线上方才做多
        # 统一使用最新K线的ma20，保持逻辑一致
        ma_filter = pd.notna(latest['ma20']) and bool(latest['close'] > latest['ma20'])
        if not ma_filter:
            return False
        
        return True
    
    def _check_sell_signal(self, df: pd.DataFrame, signal_bar: pd.Series, 
                           latest: pd.Series, entry_price: float, use_prev_day_signal: bool = True) -> tuple:
        """检查卖出信号（优化出场逻辑）
        
        Args:
            df: 股票数据
            signal_bar: 信号K线
            latest: 最新K线
            entry_price: 入场价格
            use_prev_day_signal: 是否使用前一天信号
            
        Returns:
            (是否卖出, 卖出原因)
        """
        # 出场条件1：跌破N日低点（下线）
        # 回测模式：最新K线跌破T-1信号的down
        # 狩猎场模式：最新K线跌破T日down（收盘后确认）
        if pd.notna(latest['down']) and bool(latest['low'] < latest['down']):
            return True, f"跌破{self.n_exit}日低点 {latest['down']:.2f}"
        
        # 出场条件2：ATR止损（跌破入场价 - exit_atr * ATR）
        if pd.notna(latest['atr']):
            stop_loss = entry_price - self.exit_atr * latest['atr']
            if bool(latest['low'] <= stop_loss):
                return True, f"ATR止损 {stop_loss:.2f}"
        
        return False, ""
    
    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None, 
                          cash: Optional[float] = None, use_prev_day_signal: bool = True) -> TimingResult:
        """获取海归策略择时结果
        
        Args:
            df: 股票数据
            position: 持仓信息
            cash: 可用资金
            use_prev_day_signal: 是否使用前一天信号
                - True: 回测模式，使用T-1日信号判断（df.iloc[-2]作为信号K线）
                - False: 狩猎场模式，使用T日信号判断（df.iloc[-1]作为信号K线）
            
        Returns:
            择时结果
        """
        result = TimingResult()
        
        # 计算指标
        df = self.calculate_indicators(df)
        
        # 获取数据
        latest = df.iloc[-1]  # 最新K线
        
        # 根据模式确定信号K线和判断逻辑
        if use_prev_day_signal:
            # 回测模式：使用前一天信号，T-1信号K线 + T开盘交易
            if len(df) < 2:
                return result
            signal_bar = df.iloc[-2]  # T-1日信号K线
            signal_date_offset = 1  # 信号日期偏移
        else:
            # 狩猎场模式：使用当天信号判断
            signal_bar = latest  # T日信号K线
            signal_date_offset = 0
        
        # 计算收益率
        entry_price = position['buy_price'] if position else 0
        current_price = latest['close']
        hold_return = (current_price - entry_price) / entry_price if entry_price > 0 else 0
        
        # === 卖出条件（优先判断） ===
        if position and len(df) >= 2:
            is_sell, reason = self._check_sell_signal(df, signal_bar, latest, entry_price, use_prev_day_signal)
            if is_sell:
                result.is_sell = True
                result.signal_strength = 1.0
                result.message = f"T-{signal_date_offset}日{reason}，卖出信号" if signal_date_offset else f"今日{reason}，卖出信号"
                result.trade_type = 'sell'
                result.sell_quantity = position.get('quantity', 0)
        
        # === 买入条件 ===
        if not position and not result.is_sell:
            if len(df) >= 2:
                if self._check_buy_signal(df, signal_bar, latest, use_prev_day_signal):
                    buy_price = latest['open']
                    result.is_buy = True
                    result.signal_strength = 1.0
                    result.message = f"T-{signal_date_offset}日突破上线 {signal_bar['up']:.2f}，买入信号" if signal_date_offset else f"今日突破上线 {signal_bar['up']:.2f}，买入信号"
                    result.support_level = signal_bar['up'] * 0.95
                    result.trade_type = 'buy'
                    buy_amount = self.base_position_amount
                    result.buy_quantity = max(int(buy_amount / buy_price) // 100 * 100, 100)
        
        # === 加仓/减仓信号 ===
        if position and not result.is_sell:
            # 获取持仓状态
            current_quantity = position.get('quantity', 0)
            add_count = position.get('add_count', 0)  # 已加仓次数
            
            # 海龟法则：最多加仓4次
            max_additions = 4
            
            # 加仓条件：价格上涨add_atr*ATR（每次加仓后更新参考价）
            # 首次加仓：以入场价为基准
            # 后续加仓：以上次加仓价为基准
            if add_count < max_additions:
                last_add_price = position.get('last_add_price', entry_price)
                add_threshold = last_add_price + self.add_atr * latest['atr']
                
                if latest['high'] >= add_threshold:
                    result.is_buy = True
                    result.signal_strength = 0.8
                    result.message = f"加仓#{add_count + 1}，突破{add_threshold:.2f}"
                    result.trade_type = 'add'
                    result.add_count = add_count + 1
                    result.indicators['last_add_price'] = latest['close']
                    # 海龟策略加仓规则：每次加仓金额 = 首次建仓金额 × 50%
                    # 首次建仓金额保存在 position['base_position_amount'] 中
                    base_amount = position.get('base_position_amount', self.base_position_amount)
                    add_amount = base_amount * 0.5  # 每次加仓为首次建仓的50%
                    buy_price = latest['open']
                    add_quantity = int(add_amount / buy_price) // 100 * 100
                    result.buy_quantity = max(add_quantity, 100)
            
            # 减仓逻辑：已移除
            # 说明：止损统一由卖出条件（_check_sell_signal）处理
            # 卖出条件包含：跌破N日下线、ATR止损
            # 不再单独设置减仓条件，避免重复触发
        
        # 填充指标值
        result.indicators['up'] = latest['up'] if pd.notna(latest['up']) else 0
        result.indicators['down'] = latest['down'] if pd.notna(latest['down']) else 0
        result.indicators['atr'] = latest['atr'] if pd.notna(latest['atr']) else 0
        result.indicators['ma20'] = latest['ma20'] if pd.notna(latest['ma20']) else 0
        result.indicators['current_price'] = current_price
        result.indicators['hold_return'] = hold_return
        
        return result
    
    def get_hunting_result(self, df: pd.DataFrame, position: Optional[Dict] = None,
                          cash: Optional[float] = None) -> TimingResult:
        """获取海归策略择时结果（狩猎场模式：t日信号，t日判断）
        
        兼容方法，实际调用get_timing_result(use_prev_day_signal=False)
        
        Args:
            df: 股票数据（包含当日数据）
            position: 持仓信息
            cash: 可用资金
            
        Returns:
            择时结果
        """
        return self.get_timing_result(df, position, cash, use_prev_day_signal=False)
    
    def calculate_support(self, df: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """计算海归策略的支撑位
        
        Args:
            df: 股票数据
            key_date: 关键日期
            
        Returns:
            支撑位价格
        """
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        
        # 海归策略的支撑位为下线
        if pd.notna(latest['down']):
            return latest['down']
        
        # fallback: 使用20日均线
        if len(df) >= 20:
            return df['close'].rolling(window=20).mean().iloc[-1]
        
        return 0.0
