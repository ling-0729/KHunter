"""
海归策略实现
基于唐奇安通道和ATR的趋势跟踪策略
"""
import pandas as pd
from trading.timing_strategies import TimingStrategy, TimingResult
from typing import Dict, Optional


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
# ★【2026-10-01 用户要求 ✓】"**改回 10/5/10**" ✓（先前曾试 12/6/12 ✓ 已回退 ✓）
#   = `n_entry` 10 / `n_exit` 5 / `atr_period` 10 ✓；本预设是"无配置时的默认口径"✓，
#   与 `config/strategy_params.yaml` ✓ 和 `TURTLE_DEFAULT_PARAMS` ✓ **三层同步** ✓
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
        'classic': CLASSIC_PRESET,       # 经典海龟：20/10/20
        'short': SHORT_TURTLE_PRESET,    # 短线海龟：**10/5/10**（2026-10-01 用户口径 ✓）
        'ultra_short': ULTRA_SHORT_PRESET,  # 超短海龟：6/3/6
    }

    # 是否启用 MA20 趋势过滤（买入与加仓判断均受此开关控制）
    # 低位海龟（LowTurtleStrategy）覆盖为 False：低位股常低于 MA20，
    # 启用会把信号全部否决，故子类关闭该过滤，仅保留突破/上影线/阳线条件。
    # 通过开关而非重写方法，保证子类自动继承父类的前视偏差修复与规则变更。
    USE_MA_FILTER = True

    # 买入信号文案标识（子类可覆盖，如低位海龟为"低位"），仅影响展示不影响判断
    SIGNAL_LABEL = ''
    
    def __init__(self, config):
        """初始化海归策略
        
        Args:
            config: 策略配置
        """
        super().__init__(config)
        
        # 应用预设配置（如果指定了preset）
        # 【2026-09-23】默认与兜底统一为 short（10/5/10）✓
        #   原实现：默认值 short ✓ 但**未知 preset 名**回退 classic（20/10/20）✗ ——
        #   `preset: custom` 这类非法值会静默变成"更宽的通道" ✗，与"默认 10/5/10"的预期不符 ✗。
        preset_name = self.config.get('preset', 'short')  # 默认短线海龟（10/5/10）
        preset = self.PRESETS.get(preset_name, SHORT_TURTLE_PRESET)
        # 【2026-09-23】记录最终生效的预设名，供回测/实盘日志打印真实口径 ✓
        #   （否则日志只能打印 config 里的原始 preset ✗ —— 精简后该键已不在配置中 ✗，
        #     会显示 None ✗，让人误以为"参数没读到" ✗，实际走的是默认 short = 10/5/10 ✓）
        self.preset_name = preset_name
        
        # 从预设或直接配置中获取参数
        self.n_entry = self.config.get('n_entry', preset['n_entry'])    # 入场通道周期
        self.n_exit = self.config.get('n_exit', preset['n_exit'])        # 出场通道周期
        self.atr_period = self.config.get('atr_period', preset['atr_period'])  # ATR周期
        self.entry_atr = self.config.get('entry_atr', preset['entry_atr'])    # 入场ATR比例
        self.add_atr = self.config.get('add_atr', preset['add_atr'])          # 加仓ATR间隔
        self.exit_atr = self.config.get('exit_atr', preset['exit_atr'])        # 出场ATR止损倍数
        self.base_position_amount = self.config.get('base_position_amount', 20000)  # 底仓金额（元）
        self.use_fixed_amount = self.config.get('use_fixed_amount', True)  # 是否使用固定金额

        # 【2026-09-23 口径统一】加仓参数改为**读配置** ✓（原实现在 get_timing_result 里硬编码 ✗，
        #   导致面板/配置文件改成任何值都不生效 ✗ —— 海龟plus 一直是读配置的 ✓，父子口径不一致 ✗）：
        #     · add_profit_min：加仓盈利门槛（缺省 2% ✓，与海龟plus 同键同默认 ✓）
        #     · max_additions ：加仓次数上限（正整数=上限；0=不设限；缺省/None/非法=4 ✓）
        #   盈利基准恒为**实际持仓均价** `position['buy_price']` ✓
        #   （回测引擎 :868-871 与实盘运行器 :3499-3500 在加仓后都会把它更新为加权均价 ✓）
        self.add_profit_min = self._to_float(self.config.get('add_profit_min'), 0.02)
        self.max_additions = self._parse_max_additions(self.config.get('max_additions'))

        # 向后兼容旧参数名
        self.n1 = self.n_entry   # 入场上线周期
        self.n2 = self.n_exit     # 出场下线周期

    @staticmethod
    def _to_float(value, default: float) -> float:
        """安全转 float ✓（None / 空白串 / 非法值 → default ✓）"""
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_max_additions(value) -> Optional[int]:
        """解析加仓次数上限（**海龟 / 低位海龟 / 海龟plus 共用同一实现** ✓）

        - 正整数          → 该上限
        - 0              → None（不设限，交由引擎/上层约束）
        - 缺省/None/''/非法 → **4（与海龟plus 一致）**

        Returns:
            上限次数；None 表示不设限
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return 4
        try:
            n = int(value)
        except (TypeError, ValueError):
            return 4
        return n if n > 0 else None

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
        # 上影线过滤：分母为实体上端 max(open, close)；
        # 异常数据下该值可能为 0，此时按 0 处理避免 ZeroDivisionError
        # （与加仓分支的保护口径保持一致）
        _body_high = max(signal_bar['open'], signal_bar['close'])
        upper_shadow = signal_bar['high'] - _body_high
        upper_shadow_ratio = upper_shadow / _body_high if _body_high > 0 else 0
        if upper_shadow_ratio > 0.04:
            return False
        
        # 3. 阳线过滤：信号发出当日必须是阳线且收盘涨幅 > 0%
        # signal_bar 的位置由 use_prev_day_signal 确定：
        #   回测模式（True）：signal_bar = df.iloc[-2]，前一天 = df.iloc[-3]
        #   狩猎场模式（False）：signal_bar = df.iloc[-1]，前一天 = df.iloc[-2]
        signal_bar_idx = len(df) - 2 if use_prev_day_signal else len(df) - 1
        prev_close_idx = signal_bar_idx - 1
        if prev_close_idx >= 0:
            prev_close = df['close'].iloc[prev_close_idx]
            is_bullish = bool(signal_bar['close'] > signal_bar['open'])  # 阳线
            is_rising = bool(signal_bar['close'] > prev_close)  # 收盘涨幅>0
            if not (is_bullish and is_rising):
                return False
        
        # 4. 均线过滤：价格在均线上方才做多（受 USE_MA_FILTER 开关控制）
        # 回测模式（T-1日信号）：用T-1日的ma20和close判断，避免前视偏差
        # 狩猎场模式（T日信号）：signal_bar=latest，自然用T日数据
        # 低位海龟关闭此过滤（低位股常低于MA20，启用会否决所有信号）
        if self.USE_MA_FILTER:
            ma_filter = pd.notna(signal_bar['ma20']) and bool(signal_bar['close'] > signal_bar['ma20'])
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
        # 回测模式：用T-1日信号K线的low和down判断，避免前视偏差
        # 狩猎场模式：signal_bar=latest，自然用T日数据
        if pd.notna(signal_bar['down']) and bool(signal_bar['low'] < signal_bar['down']):
            return True, f"跌破{self.n_exit}日低点 {signal_bar['down']:.2f}"
        
        # 出场条件2：ATR止损（跌破入场价 - exit_atr * ATR）
        # 回测模式：用T-1日信号K线的atr和low判断
        if pd.notna(signal_bar['atr']):
            stop_loss = entry_price - self.exit_atr * signal_bar['atr']
            if bool(signal_bar['low'] <= stop_loss):
                return True, f"ATR止损 {stop_loss:.2f}"
        
        return False, ""
    
    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None, 
                          cash: Optional[float] = None, use_prev_day_signal: bool = True, stock_code: str = "") -> TimingResult:
        """获取海归策略择时结果
        
        Args:
            df: 股票数据
            position: 持仓信息
            cash: 可用资金
            use_prev_day_signal: 是否使用前一天信号
                - True: 回测模式，使用T-1日信号判断（df.iloc[-2]作为信号K线）
                - False: 狩猎场模式，使用T日信号判断（df.iloc[-1]作为信号K线）
            stock_code: 股票代码（用于指标缓存隔离）
            
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
                    # 买入价测算口径：
                    # - 回测模式（T-1信号）：信号次日开盘成交，用 T 日开盘价（真实执行价）
                    # - 实盘模式（T日信号）：收盘后才确认信号、T+1 执行，
                    #   用 T 日开盘价属于"回到过去"的时点，以 T 日收盘价测算更贴合实际成交
                    buy_price = latest['open'] if use_prev_day_signal else latest['close']
                    result.is_buy = True
                    result.signal_strength = 1.0
                    # 文案含 SIGNAL_LABEL，子类（如低位海龟）可标识来源
                    result.message = (
                        f"T-{signal_date_offset}日突破上线 {signal_bar['up']:.2f}，"
                        f"{self.SIGNAL_LABEL}买入信号") if signal_date_offset else (
                        f"今日突破上线 {signal_bar['up']:.2f}，{self.SIGNAL_LABEL}买入信号")
                    result.support_level = signal_bar['up'] * 0.95
                    result.trade_type = 'buy'
                    buy_amount = self.base_position_amount
                    result.buy_quantity = max(int(buy_amount / buy_price) // 100 * 100, 100)
        
        # === 加仓/减仓信号 ===
        if position and not result.is_sell:
            # 获取持仓状态
            current_quantity = position.get('quantity', 0)
            add_count = position.get('add_count', 0)  # 已加仓次数

            # 加仓条件：价格上涨add_atr*ATR（每次加仓后更新参考价）
            # 首次加仓：以入场价为基准；后续加仓：以上次加仓价为基准
            # 加仓也需要阳线条件（与买入一致）
            # 前视偏差修复：所有信号判断用signal_bar（回测=T-1日，狩猎场=T日）
            #
            # 【2026-09-23 口径统一】两处硬编码改为**读配置** ✓：
            #   ① 加仓上限：`max_additions = 4` ✗ → `self.max_additions` ✓
            #      （正整数=上限；0=不设限；缺省/非法=4 ✓，与海龟plus 同一解析器 ✓）
            #   ② 盈利门槛：`profit_ratio > 0.02` ✗ → `>= self.add_profit_min` ✓（缺省 0.02 ✓）
            #      · 口径 = **实际盈利** ✓：基准恒为 `entry_price = position['buy_price']`
            #        （**持仓加权均价** ✓，回测/实盘加仓后均会更新 ✓），与海龟plus 一致 ✓
            #      · 边界由 `>` 统一为 `>=` ✓（恰好等于门槛时两策略结论一致 ✓）
            max_additions = self.max_additions
            if max_additions is None or add_count < max_additions:
                # 检查持仓盈利状态（按**实际持仓均价**衡量 ✓），用信号日收盘价
                signal_close = signal_bar['close']
                profit_ratio = (signal_close - entry_price) / entry_price if entry_price > 0 else 0
                if profit_ratio >= self.add_profit_min:  # 盈利达门槛（可配置 ✓）
                    # last_add_price 可能为空(None/0)：首次加仓以入场价为基准，
                    # 故缺失时回退 entry_price（避免 None + float 抛 TypeError）
                    last_add_price = position.get('last_add_price') or entry_price
                    add_threshold = last_add_price + self.add_atr * signal_bar['atr']

                    if signal_bar['high'] >= add_threshold:
                        # 检查阳线条件：加仓也需要阳线且涨幅>0，与买入规则一致
                        # 前一日收盘价：信号日的前一天
                        signal_bar_idx = len(df) - 1 - signal_date_offset
                        prev_close = df['close'].iloc[signal_bar_idx - 1] if signal_bar_idx > 0 else signal_close
                        is_bullish = signal_bar['close'] > signal_bar['open']
                        is_rising = signal_bar['close'] > prev_close
                        # 均线过滤：低位海龟通过 USE_MA_FILTER=False 关闭，此时恒为 True
                        is_above_ma20 = (
                            (pd.notna(signal_bar['ma20']) and signal_bar['close'] > signal_bar['ma20'])
                            if self.USE_MA_FILTER else True)

                        # 检查上影线
                        upper_shadow = signal_bar['high'] - max(signal_bar['open'], signal_bar['close'])
                        upper_shadow_ratio = upper_shadow / max(signal_bar['open'], signal_bar['close']) if max(signal_bar['open'], signal_bar['close']) > 0 else 0
                        upper_shadow_ok = upper_shadow_ratio <= 0.04

                        # 阳线 + 涨幅>0 + 上影线<4% + 均线过滤
                        if is_bullish and is_rising and upper_shadow_ok and is_above_ma20:
                            result.is_buy = True
                            result.signal_strength = 0.8
                            result.message = (
                                f"加仓#{add_count + 1}，突破{add_threshold:.2f}"
                                f"（持仓均价 {entry_price:.2f}，盈利 {profit_ratio * 100:.1f}%）")
                            result.trade_type = 'add'
                            result.add_count = add_count + 1
                            result.indicators['last_add_price'] = signal_bar['close']
                            # 【2026-09-23】回填盈利口径（与海龟plus 同名同义 ✓，便于排查）
                            result.indicators['add_ref_price'] = entry_price
                            result.indicators['add_ref_label'] = '持仓均价'
                            # 以持仓数量为基准，加仓比例递减：1/2, 1/3, 1/4, 1/5, 1/6
                            add_ratio = 1.0 / (add_count + 2)
                            add_quantity = int(current_quantity * add_ratio) // 100 * 100
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
