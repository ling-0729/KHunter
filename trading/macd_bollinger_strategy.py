"""
顺势宝策略实现
顺势而为，在趋势启动初期捕捉买点，在趋势转弱时及时离场
"""
import pandas as pd
from trading.timing_strategies import TimingStrategy, TimingResult
from trading.technical_indicators import TechnicalIndicators
from typing import Dict, Optional


class ShunShiBaoStrategy(TimingStrategy):
    """顺势宝策略"""
    
    def __init__(self, config):
        """初始化策略
        
        Args:
            config: 策略配置字典
        """
        super().__init__(config)
        
        # MACD参数（默认标准参数）
        self.macd_fast = self.config.get('macd_fast', 12)
        self.macd_slow = self.config.get('macd_slow', 26)
        self.macd_signal = self.config.get('macd_signal', 9)
        
        # 布林带参数（默认标准参数）
        self.boll_period = self.config.get('boll_period', 20)
        self.boll_multiplier = self.config.get('boll_multiplier', 2)
        
        # ★★【2026-10-05 用户要求 ✓】**删除死参数 `base_position_amount`** ✗✓ ★★
        #   缘由 ✓：本策略**首仓数量不由自己决定** ✓（`trade_type='buy'` 时**不设**
        #     `buy_quantity` ✗ ⇒ 交给回测引擎 / 资金管理 ✓）；实测该键**只在 `__init__`
        #     赋值、全文再无引用** ✗（= 早期代码审查报告 **P0-002** 指的那处 ✓；⚠️ 该报告**已移出版本管理** ✗✓，故此处**不再指向具体文件** ✗）。
        #   ⚠️ **加仓数量**也不用它 ✗（2026-10-05 起照**海龟口径** ✓ = 按持仓比例递减 ✓，
        #     见 `get_timing_result` ✓）。
        #   ⇒ 若旧配置里还写着该键 ✓：**忽略即可** ✓（不再读取 ✓，不影响任何行为 ✓）。
        
        # 初始化技术指标计算器
        self.technical_indicators = TechnicalIndicators()
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算MACD和布林带指标
        
        Args:
            df: 股票数据DataFrame
            
        Returns:
            添加了指标的DataFrame
        """
        result = df.copy()
        
        # 确保数据按日期正序排列（最新在最后）
        if len(result) > 1 and result['date'].iloc[0] > result['date'].iloc[1]:
            result = result.iloc[::-1].reset_index(drop=True)
        
        # 计算MACD指标（直接计算，不使用缓存）
        ema_short = result['close'].ewm(span=self.macd_fast, adjust=False).mean()
        ema_long = result['close'].ewm(span=self.macd_slow, adjust=False).mean()
        macd_line = ema_short - ema_long
        signal_line = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
        hist = macd_line - signal_line
        
        result['dif'] = macd_line
        result['dea'] = signal_line
        result['macd'] = hist
        
        # 计算布林带指标（直接计算，不使用缓存）
        mid = result['close'].rolling(window=self.boll_period).mean()
        std = result['close'].rolling(window=self.boll_period).std()
        upper = mid + self.boll_multiplier * std
        lower = mid - self.boll_multiplier * std
        
        result['boll_mid'] = mid
        result['boll_upper'] = upper
        result['boll_lower'] = lower
        
        return result
    
    def _check_indicators_valid(self, row: pd.Series) -> bool:
        """检查指标是否有效（非空值）
        
        Args:
            row: 数据行
            
        Returns:
            是否有效
        """
        required = ['dif', 'dea', 'macd', 'boll_mid', 'boll_upper', 'boll_lower']
        for indicator in required:
            if pd.isna(row.get(indicator)):
                return False
        return True
    
    def _check_buy_signal_1(self, current: pd.Series, prev: pd.Series) -> bool:
        """判断一档买入信号（稳健型）
        条件：MACD零轴上方刚金叉 且 价格突破布林带中轨
        
        Args:
            current: 当前数据
            prev: 前一天数据
            
        Returns:
            是否满足买入条件
        """
        # MACD条件：零轴上方刚金叉
        macd_buy_1 = (
            current['dif'] > 0 and                    # DIF在零轴上方（上升趋势）
            current['dif'] > current['dea'] and       # DIF > DEA（金叉状态）
            prev['dif'] <= prev['dea']                # 前日未金叉（刚刚金叉）
        )
        
        # 布林带条件：突破中轨确认
        boll_buy_1 = (
            current['close'] > current['boll_mid'] and   # 收盘价突破中轨
            prev['close'] <= prev['boll_mid']           # 前日未突破（刚突破）
        )
        
        return macd_buy_1 and boll_buy_1
    
    def _check_buy_signal_2(self, current: pd.Series, prev: pd.Series) -> bool:
        """判断二档买入信号（突破型）
        条件：MACD强势多头 且 价格突破布林带上轨
        
        Args:
            current: 当前数据
            prev: 前一天数据
            
        Returns:
            是否满足买入条件
        """
        # MACD条件：强势多头
        macd_buy_2 = (
            current['dif'] > 0 and                    # DIF在零轴上方
            current['macd'] > prev['macd'] and        # MACD柱持续增长（多头力量增强）
            current['dif'] > current['dea']           # 保持金叉状态
        )
        
        # 布林带条件：突破上轨
        boll_buy_2 = (
            current['high'] > current['boll_upper'] and  # 最高价突破上轨
            current['close'] > current['boll_mid']       # 收盘价在中轨上方（收盘稳健）
        )
        
        return macd_buy_2 and boll_buy_2
    
    # ★★【2026-10-05 用户要求 ✓ 简化 ✓】**加仓判据 = 买②（突破型买入）** ✗✓ ★★
    #   用户原话 ✓："**加仓改为和买2一致**" ✓
    #   ⇒ 原 `_check_add_signal`（`DIF>0 ∧ 柱增长 ∧ DIF>DEA` ∧ **收盘站上上轨** ∧
    #     **放量×1.1** ✓）**整体删除** ✗✓ ⇒ 改为**直接复用** `_check_buy_signal_2` ✓。
    #   理由 ✓：
    #     ① **语义单一** ✓：同一个信号，**空仓时叫"买"** ✓、**持仓时叫"加"** ✓
    #        —— 不再出现"一信号两义"✗（旧版持仓时把买①/买②也当加仓 ✓，回测归因很难读 ✗）；
    #     ② 顺手去掉"必须**收在上轨之上** + **放量**"✗ ⇒ 加仓更易触发 ✓
    #        （新口径 = 买② ✓：`DIF>0 ∧ 柱>昨日柱 ∧ DIF>DEA ∧ 最高价>上轨 ∧ 收盘>中轨` ✓）。
    #   ⚠️ **数量**另算 ✓：照**海龟口径递减** ✓（`1/(已加仓次数+2)` ✓，见 `get_timing_result` ✓）。
    #   ⚠️ 海龟其余加仓闸门（`add_profit_min` 盈利门槛 ✓ / `add_atr` 突破间隔 ✓ /
    #     `max_additions` 次数上限 ✓）**本次未引入** ✗✓（用户只要求"数量一致"✓）——
    #     需要的话说一句即可加 ✓。
    
    def _check_sell_signal(self, current: pd.Series, prev: pd.Series) -> bool:
        """判断清仓信号（2026-10-05 简化后 **唯一** 卖出规则 ✓）

        用户原话 ✓："**卖出改为最低价<中轨 且 macd转绿**" ✓

        条件 ✓（**两者同时成立** ✓）：
          ① **最低价 < 布林带中轨** ✓ —— ⚠️ 用 `low` ✗（**不是** `close` ✓）：
             盘中触及即算 ✓ ⇒ 比"收盘跌破中轨"**更早** ✓；
          ② **MACD 转绿** ✓ = 柱为绿 = `DIF < DEA` ✓（等价于结果里的 `macd` 字段 < 0 ✓）。

        ⚠️ 口径说明（**重要** ✗✓，两处都是"避免永久不卖"的刻意选择 ✓）：
          · ②按**状态**判 ✗✓（"只要**现在**是绿的" ✓），**不要求"当天刚由红转绿"** ✗ ——
            否则若"首次转绿那天最低价还在中轨上方"✗ ⇒ 该**事件**当天不成立 ✓ ⇒
            之后再也不会成立 ✗ ⇒ **永不卖出** ✗✗（灾难性 ✓）。
            （若你确实要"刚转绿"事件口径 ✗ ⇒ 只需把这行改成
              `current_hist < 0 and prev_hist >= 0` ✓，一行之差 ✓。）
          · ①也**不要求"刚跌破中轨"** ✗✓（持有期间**天天判** ✓）—— 同理 ✓：
            否则"错过那一天"就永不卖 ✗。

        历史沿革 ✓（原三档已**全部删除** ✗✓）：
          · 一档（止损型 ✓）= 柱由正转负 **且** 同日跌破中轨 ✓ ⇒ 被本规则**吸收并放宽** ✓；
          · 二档（止盈型 ✓）= DIF 走弱 + 触上轨回落 + 阴线 ⇒ 全清 ✓ ⇒ **删除** ✗
            （与"丢中轨"重叠 ✓，且**过早** ✗——强度仅 0.7 却全清 ✗ 本就别扭 ✗）；
          · 三档（破位型 ✓）= `DIF<0` + 放量跌破下轨 ⇒ 清 ✓ ⇒ **删除** ✗（**太迟** ✗，回撤大 ✗）。
        """
        return bool(current['low'] < current['boll_mid']
                    and (current['dif'] - current['dea']) < 0)
    
    def get_timing_result(self, df: pd.DataFrame, position: Optional[Dict] = None,
                          cash: Optional[float] = None, use_prev_day_signal: bool = True, stock_code: str = "") -> TimingResult:
        """获取择时结果

        Args:
            df: 股票数据DataFrame
            position: 持仓信息
            cash: 可用资金
            use_prev_day_signal: 是否使用前一天信号
                - True: 回测模式，使用T-1日信号K线判断（信号K线=DF.iloc[-2]，执行日=DF.iloc[-1]）
                - False: 狩猎场模式，使用T日信号K线判断（信号K线=DF.iloc[-1]）
                回测模式逻辑：
                    - T-1日收盘后判断是否有买入信号
                    - 如果有信号，在T日以开盘价买入
                狩猎场模式逻辑：
                    - T日盘中或收盘判断是否有买入信号
            stock_code: 股票代码（用于指标缓存隔离）
                    - 如果有信号，在T日以当前价买入

        Returns:
            TimingResult对象
        """
        result = TimingResult()

        df = self.calculate_indicators(df)

        if len(df) < 2:
            return result

        if use_prev_day_signal:
            if len(df) < 3:
                return result
            signal_bar = df.iloc[-2]
            latest_bar = df.iloc[-1]
            prev_bar = df.iloc[-3]
        else:
            signal_bar = df.iloc[-1]
            latest_bar = df.iloc[-1]
            prev_bar = df.iloc[-2]

        if not self._check_indicators_valid(signal_bar) or not self._check_indicators_valid(prev_bar):
            return result

        # ★★★★【2026-10-05 用户要求 ✓ 简化 ✓】**四句规则** ✗→✓ ★★★★
        #   用户口径 ✓："买入只定两种，加仓只定一种，卖出只定一种" ✓ +
        #     "**加仓改为和买2一致** ✓" + "**加仓数量和海龟的规则一致** ✓" +
        #     "**卖出改为最低价<中轨 且 macd转绿** ✓"
        #   ⇒ 结构随之简化 ✓（旧版那条"买优先于卖"的隐式优先级**消失** ✗✓）：
        #     · **空仓** ⇒ 只看 买①（稳健启动 ✓）→ 买②（强势突破 ✓）；
        #     · **持仓** ⇒ 先看 卖①（趋势转弱 ✓）⇒ 再看 加①（**= 买② 同口径** ✓）。
        #   ⚠️ 为什么"卖先判"✗✓：沿用海龟取向 ✓（风险优先 ✓）；且两判据**天然互斥** ✓
        #     （加仓要 `DIF>DEA` 红柱 ✓ / 卖出要柱绿 ✓）⇒ 顺序其实不改结果 ✓，
        #     写"卖先"只为可读性与一致性 ✓。
        if not position:
            if self._check_buy_signal_1(signal_bar, prev_bar):
                result.is_buy = True
                result.message = "MACD零轴上方金叉且价格突破中轨，买入信号（稳健型）"
                result.signal_strength = 1.0
                result.trade_type = 'buy'
            elif self._check_buy_signal_2(signal_bar, prev_bar):
                result.is_buy = True
                result.message = "MACD强势且价格突破上轨，买入信号（突破型）"
                result.signal_strength = 0.8
                result.trade_type = 'buy'
            # ⚠️ 空仓时**不设** `buy_quantity` ✗✓（首仓数量交给回测引擎 / 资金管理 ✓，
            #    与简化前一致 ✓；原死参数 `base_position_amount` 已删 ✗）
        else:
            if self._check_sell_signal(signal_bar, prev_bar):
                # ★ **唯一** 卖出规则 ✓（2026-10-05 ✓）：`最低价<中轨 ∧ MACD柱为绿` ✓
                result.is_sell = True
                result.message = (
                    f"最低价跌破中轨且MACD转绿，清仓信号（趋势转弱）"
                    f"（最低价 {signal_bar['low']:.2f} < 中轨 "
                    f"{signal_bar['boll_mid']:.2f}，"
                    f"DIF {signal_bar['dif']:.3f} < DEA {signal_bar['dea']:.3f}）")
                result.signal_strength = 1.0
                result.trade_type = 'sell'
                result.sell_quantity = position.get('quantity', 0)   # ★ **全部清仓** ✓
            elif self._check_buy_signal_2(signal_bar, prev_bar):
                # ★ 加① = **买② 同口径** ✓（用户口径 ✓："加仓改为和买2一致" ✓）
                result.is_buy = True
                result.message = ("MACD强势且价格突破上轨，加仓信号"
                                  "（同买②口径：最高价>上轨 ∧ 收盘>中轨）")
                result.signal_strength = 0.8
                result.trade_type = 'add'
                # ★★ 数量 = **海龟口径** ✗→✓（用户口径 ✓："加仓数量和海龟的规则一致" ✓）：
                #   以**当前持仓数量**为基准、比例**递减** ✓ —— 第 1 次 `1/2` ✓、
                #   第 2 次 `1/3` ✓、第 3 次 `1/4` ✓ …（同 `turtle_strategy.py:383-386` ✓）
                #   · `add_count` 取 `position['add_count']`（= **已加仓次数** ✓，
                #     回测引擎 / 实盘运行器在加仓后维护 ✓；与 `TimingResult.add_count` 同义 ✓）；
                #   · ⚠️ 必须**回写** `result.add_count` ✗✓ —— 基类注释写明
                #     "产生 `trade_type='add'` 时必须设置" ✓；漏了 ⇒ 永远只按 `1/2` 加 ✗
                #     （递减口径静默失效 ✗✓）。
                current_quantity = position.get('quantity', 0)
                add_count = position.get('add_count', 0)
                add_ratio = 1.0 / (add_count + 2)
                add_quantity = int(current_quantity * add_ratio) // 100 * 100
                result.buy_quantity = max(add_quantity, 100)
                result.add_count = add_count + 1
                result.indicators['add_ref_label'] = '持仓数量'
                result.indicators['add_ratio'] = add_ratio

        result.support_level = latest_bar['boll_lower']
        result.resistance_level = latest_bar['boll_upper']

        # ★【2026-10-05 修 ✓】`result.indicators = {...}` **改成** `.update({...})` ✗→✓：
        #   加仓分支写进 `result.indicators` 的元信息（`add_ref_label` ✓ / `add_ratio` ✓）
        #   若在此被**整体覆盖** ✗ ⇒ 白写 ✗（且"数量按什么算的"就查不出来了 ✗）。
        #   （`TimingResult.__init__` 里 `self.indicators = {}` 是**每实例**新建 ✓
        #     ⇒ `update` 不会跨实例串数据 ✓。）
        result.indicators.update({
            'dif': latest_bar['dif'],
            'dea': latest_bar['dea'],
            'macd_hist': latest_bar['macd'],
            'boll_upper': latest_bar['boll_upper'],
            'boll_mid': latest_bar['boll_mid'],
            'boll_lower': latest_bar['boll_lower'],
            'boll_width': latest_bar['boll_upper'] - latest_bar['boll_lower'],
            'current_price': latest_bar['close']
        })
        
        return result
    
    def calculate_support(self, df: pd.DataFrame, key_date: Optional[str] = None) -> float:
        """计算支撑位
        
        Args:
            df: 股票数据DataFrame
            key_date: 关键日期（可选）
            
        Returns:
            支撑位价格（布林带下轨）
        """
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        
        if pd.notna(latest['boll_lower']):
            return latest['boll_lower']
        
        return 0.0