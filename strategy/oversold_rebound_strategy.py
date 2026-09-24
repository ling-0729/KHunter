"""
超跌反弹策略（OversoldReboundStrategy）

策略逻辑：
  1. 超跌深度检查（必要条件，C1）：近 lookback_days 个交易日内，区间最高价到最低价的
     下跌幅度超过 decline_threshold（默认50%），即股票处于深度超跌状态。
  2. 底部特征检查（C2）：
     a) MACD底背离：窗口内价格创新低，但MACD柱未同步创新低（动能背离）。【必须条件】
     b) 底分型形态：近三根K线最低价居中（缠论简化底分型）。
     c) 低位九转：最新交易日完成买入Countdown第9根（复用LowTD9Strategy状态机）。
     d) 启明星形态（宽松版，仅形态）：近三根K线呈"阴-小实体-阳"反转雏形。
     e) 其余底部特征（底分型/低位九转/启明星）满足之一。

  3. 反弹幅度约束（C3，必要条件）：选股日收盘价相对区间最低价涨幅 <= rebound_cap，
     避免已反弹过高的标的，只捕捉底部刚启动的买点。

组合：C1 AND C2a（MACD底背离，必须） AND (C2b OR C2c OR C2d) AND C3

数据约定：df 倒序，index=0 为最新交易日（与框架 execute_selection 入口规范化一致）。
"""

from strategy.base_strategy import BaseStrategy
# 低位九转策略已移入 strategy/disabled/（代码保留、不参与注册）；
# 本策略仅复用其底部形态判定。注意：这里导入的是**模块**而非类名 ——
# 若写成 `from ... import LowTD9Strategy`，该类会成为本模块属性，
# 注册器扫描模块时会把它重新注册进来（等于没停用）。
from strategy.disabled import low_td9_strategy
import pandas as pd


class OversoldReboundStrategy(BaseStrategy):
    """超跌反弹策略：深度超跌 + MACD底背离(必须) + 任一底部特征 + 反弹幅度受限"""

    # 默认参数（与 config/strategy_params.yaml 的 params 段保持一致）
    DEFAULT_PARAMS = {
        'lookback_days': 100,         # 反弹幅度约束(C3)回溯交易日数
        'high_drawdown_days': 120,    # 超跌窗口：近 N 日内最高价（2026-09-19 新增）
        'high_drawdown_min': 0.50,    # 选股日收盘价须低于近 N 日最高价的 (1-该值)
        # 【2026-09-19】与「次新腰斩策略」彻底分开：K 线数 ≤ 该值视为次新 → 本策略排除。
        # 次新腰斩条件的恰是"≤120 根"，两者互斥，避免同一标的同时被两个策略选中。
        'exclude_new_stock_bars': 120,
        # 预加载窗口驱动参数（已在回测/实盘 lookback_keys 白名单内）：
        # 需保证窗口内交易日 > exclude_new_stock_bars，否则正常老股会因窗口不足被误排除。
        'min_data_len': 130,
        'macd_divergence_days': 20,   # MACD底背离判断窗口
        'macd_fast': 12,              # MACD快线EMA周期
        'macd_slow': 26,              # MACD慢线EMA周期
        'macd_signal': 9,             # MACD信号线EMA周期
        'enable_bottom_fractal': True,   # 启用底分型特征
        'fractal_require_yang': True,    # 底分型右侧是否要求阳线
        'enable_low_td9': True,          # 启用低位九转特征
        'enable_morning_star': True,     # 启用启明星形态（宽松版）特征
        'morning_star_body_threshold': 0.03,  # 第一根阴线实体最小百分比
        'morning_star_small_ratio': 0.5,      # 第二根小实体相对第一根实体的比例上限
        'rebound_cap': 0.30,            # 选股日收盘相对区间最低价涨幅上限
        'require_selection_day_yang': True,  # 选股日必须阳线且涨幅>0
        'selection_day_min_gain': 0.01,      # 选股日相对前一日收盘最小涨幅(1%)
        'volume_surge_ratio': 1.3,           # 选股日量能/前5日均量 倍数下限
        'volume_avg_days': 5,                # 量能比较的基准均量窗口
    }

    def __init__(self, params=None):
        """初始化策略，合并默认参数并指定中文名称"""
        # 合并用户参数到默认参数（用户值覆盖默认值）
        merged = dict(self.DEFAULT_PARAMS)
        if params:
            merged.update(params)
        super().__init__("超跌反弹", merged)  # 合并后传给基类
        # 低位九转复用实例（仅调用其状态机，不含低位过滤）
        self._td9 = low_td9_strategy.LowTD9Strategy()

    # ------------------------------------------------------------------ #
    # 指标计算
    # ------------------------------------------------------------------ #
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 MACD 指标（DIF / DEA / MACD柱），返回带指标的 DataFrame

        :param df: 原始日线数据（倒序，index=0最新），需含 close 列
        :return: 新增 dif/dea/macd 三列的 DataFrame
        """
        df = df.copy()  # 避免修改原始数据
        close = df['close']  # 直接基于收盘价序列计算
        # 快线与慢线指数移动平均
        ema_fast = close.ewm(span=self.params['macd_fast'], adjust=False).mean()
        ema_slow = close.ewm(span=self.params['macd_slow'], adjust=False).mean()
        dif = ema_fast - ema_slow  # DIF = 快线 - 慢线
        dea = dif.ewm(span=self.params['macd_signal'], adjust=False).mean()  # 信号线
        df['dif'] = dif
        df['dea'] = dea
        df['macd'] = dif - dea  # MACD柱 = DIF - DEA
        return df

    # ------------------------------------------------------------------ #
    # 规则1：超跌深度检查（C1）
    # ------------------------------------------------------------------ #
    def _check_oversold(self, df: pd.DataFrame, reasons: list) -> float:
        """超跌检查（2026-09-19 按用户口径调整）

        条件：**选股日收盘价 < 近 high_drawdown_days 日最高价 × (1 − high_drawdown_min)**
        等价表述：选股日收盘相对近 N 日最高价跌幅 ≥ high_drawdown_min（默认 120 日 / 50%）。

        与旧口径（区间最高→最低跌幅）的区别：旧口径用"区间内最低价"判断，
        即使当前已大幅反弹也可能命中；新口径锚定**选股日收盘价**，更贴近"现价腰斩"。

        :param df: 含 high/close 的 DataFrame（倒序，index=0 最新）
        :param reasons: 命中理由列表（命中时追加说明）
        :return: 满足时返回相对最高价的跌幅(0~1)，否则返回 -1.0
        """
        days = int(self.params['high_drawdown_days'])        # 超跌窗口（交易日）
        min_dd = float(self.params['high_drawdown_min'])     # 相对最高价的最小跌幅
        if len(df) < days:
            return -1.0  # 数据不足无法判断
        window = df.head(days)                               # 近 N 日（倒序）
        max_high = window['high'].max()                      # 区间最高价
        close0 = float(df['close'].iloc[0])                  # 选股日收盘价
        if max_high <= 0 or pd.isna(max_high) or pd.isna(close0):
            return -1.0  # 价格异常
        ratio = close0 / max_high                            # 收盘 / 区间最高
        drawdown = 1.0 - ratio                               # 相对最高价的跌幅
        if drawdown >= min_dd:                               # 即 close ≤ 最高价 × (1-min_dd)
            reasons.append(
                f"选股日收盘{close0:.2f}低于近{days}日最高价{max_high:.2f}的"
                f"{ratio*100:.1f}%（跌幅{drawdown*100:.1f}%）")
            return drawdown
        return -1.0

    # ------------------------------------------------------------------ #
    # 规则3：反弹幅度约束（C3，必要条件）
    # ------------------------------------------------------------------ #
    def _check_rebound_cap(self, df: pd.DataFrame, reasons: list) -> bool:
        """
        检查选股日收盘价相对区间最低价的反弹幅度是否不超过上限

        仅捕捉底部刚启动、尚未大幅反弹的标的，避免追高。

        :param df: 含 low/close 的 DataFrame（倒序，index=0最新）
        :param reasons: 命中理由列表
        :return: True 表示反弹幅度 <= rebound_cap
        """
        lookback = int(self.params['lookback_days'])  # 与超跌窗口一致
        cap = float(self.params['rebound_cap'])        # 反弹幅度上限
        n = len(df)
        if n < lookback:
            return False  # 数据不足
        window = df.head(lookback)  # 最近 lookback 日
        min_low = window['low'].min()  # 区间最低价
        close0 = df['close'].iloc[0]   # 选股日收盘价
        if min_low <= 0 or pd.isna(min_low) or pd.isna(close0):
            return False  # 价格异常
        rebound = (close0 - min_low) / min_low  # 相对最低价反弹幅度
        if rebound <= cap:
            reasons.append(f"选股日收盘较区间最低价反弹{rebound*100:.1f}%（上限{cap*100:.0f}%）")
            return True
        return False

    # ------------------------------------------------------------------ #
    # 规则C3b：选股日阳线且涨幅>0（必要条件）
    # ------------------------------------------------------------------ #
    def _check_selection_day_yang(self, df: pd.DataFrame, reasons: list) -> bool:
        """
        检查选股日（最新交易日，倒序 idx0）是否为阳线且相对前一日收盘涨幅>0

        df 倒序：idx0 = 选股日，idx1 = 前一交易日。
        阳线：close[idx0] > open[idx0]
        涨幅>0：close[idx0] > close[idx1]（相对前一日收盘上涨）

        :param df: 含 open/close 的 DataFrame（倒序，index=0最新）
        :param reasons: 命中理由列表
        :return: True 表示选股日为阳线且涨幅>0
        """
        if len(df) < 2:
            return False  # 至少需要两根K线以判断涨幅
        today_close = df['close'].iloc[0]   # 选股日收盘价
        today_open = df['open'].iloc[0]     # 选股日开盘价
        prev_close = df['close'].iloc[1]    # 前一交易日收盘价
        # 阳线：收 > 开
        is_yang = today_close > today_open
        # 涨幅 > 0：收 > 昨收
        is_rising = today_close > prev_close
        if is_yang and is_rising:
            reasons.append("选股日为阳线且相对前一日收盘上涨")
            return True
        return False

    # ------------------------------------------------------------------ #
    # 规则C4：选股日涨幅阈值（必要条件）
    # ------------------------------------------------------------------ #
    def _check_selection_day_gain(self, df: pd.DataFrame, reasons: list) -> bool:
        """
        检查选股日（倒序 idx0）相对前一交易日收盘涨幅是否达到最小阈值

        涨幅 = (close[idx0] - close[idx1]) / close[idx1]
        要求涨幅 > selection_day_min_gain（默认 2%），用于过滤弱反弹。

        :param df: 含 close 的 DataFrame（倒序，index=0最新）
        :param reasons: 命中理由列表
        :return: True 表示选股日涨幅达到阈值
        """
        min_gain = float(self.params['selection_day_min_gain'])  # 最小涨幅阈值
        if len(df) < 2:
            return False  # 至少需要两根K线
        today_close = df['close'].iloc[0]   # 选股日收盘价
        prev_close = df['close'].iloc[1]    # 前一交易日收盘价
        if prev_close <= 0 or pd.isna(prev_close) or pd.isna(today_close):
            return False  # 价格异常
        gain = (today_close - prev_close) / prev_close  # 相对前收涨幅
        if gain > min_gain:
            reasons.append(f"选股日涨幅{gain*100:.1f}%（下限{min_gain*100:.0f}%）")
            return True
        return False

    # ------------------------------------------------------------------ #
    # 规则C5：选股日量能放大（必要条件）
    # ------------------------------------------------------------------ #
    def _check_volume_surge(self, df: pd.DataFrame, reasons: list) -> bool:
        """
        检查选股日（倒序 idx0）成交量是否达到前 N 日均量的 volume_surge_ratio 倍

        基准均量：选股日之前 volume_avg_days 日（idx1~idxN）收盘量均值
        要求：vol[idx0] >= avg_vol * volume_surge_ratio（默认 1.5 倍）

        :param df: 含 volume 的 DataFrame（倒序，index=0最新）
        :param reasons: 命中理由列表
        :return: True 表示选股日量能放大达到阈值
        """
        ratio = float(self.params['volume_surge_ratio'])  # 量能放大倍数下限
        avg_days = int(self.params['volume_avg_days'])     # 基准均量窗口
        if len(df) < avg_days + 1:
            return False  # 数据不足（需选股日 + 前 N 日）
        today_vol = df['volume'].iloc[0]  # 选股日成交量
        # 选股日之前的 avg_days 日量能均值（idx1 ~ idxN）
        base_vol = df['volume'].iloc[1:1 + avg_days].mean()
        if base_vol <= 0 or pd.isna(base_vol) or pd.isna(today_vol):
            return False  # 量能异常
        actual_ratio = today_vol / base_vol  # 实际放大倍数
        if actual_ratio >= ratio:
            reasons.append(f"选股日量能达前{avg_days}日均量{actual_ratio:.1f}倍（下限{ratio:.1f}倍）")
            return True
        return False

    # ------------------------------------------------------------------ #
    # 规则2a：MACD底背离
    # ------------------------------------------------------------------ #
    def _check_macd_divergence(self, df: pd.DataFrame, reasons: list) -> bool:
        """
        检查近 macd_divergence_days 窗口内是否出现价格新低而MACD柱未同步新低

        :param df: 含 low/macd 的 DataFrame（倒序，已计算指标）
        :param reasons: 命中理由列表
        :return: True 表示出现MACD底背离
        """
        days = int(self.params['macd_divergence_days'])  # 背离判断窗口
        n = len(df)
        if n < days:
            return False  # 数据不足
        window = df.head(days).reset_index(drop=True)  # 取窗口并重置索引（idx0最新）
        low = window['low']
        macd = window['macd']
        # 找最低价位置（时间序：iloc），取第一个最低点
        min_low_idx = int(low.idxmin())
        min_low = low.iloc[min_low_idx]  # 窗口最低价
        macd_at_low = macd.iloc[min_low_idx]  # 最低价当日的MACD柱
        macd_min = macd.min()  # 窗口内MACD柱最小值
        # 底背离：价格创新低时，MACD柱未同步创新低（动能背离）
        if macd_at_low > macd_min:
            reasons.append("底部特征：MACD底背离（价格新低而动能未新低）")
            return True
        return False

    # ------------------------------------------------------------------ #
    # 规则2b：底分型形态（缠论简化版）
    # ------------------------------------------------------------------ #
    def _check_bottom_fractal(self, df: pd.DataFrame, reasons: list) -> bool:
        """
        检查近三根K线是否构成底分型：中间K线最低价与最高价均低于左右两根

        倒序约定：idx0=最新，idx1=前一交易日，idx2=前二交易日
        底分型判定：low[idx1] < low[idx0] 且 low[idx1] < low[idx2]
                  且 high[idx1] < high[idx0] 且 high[idx1] < high[idx2]
        即中间K线的高低点均被左右两根包裹，构成标准底分型。

        :param df: 含 open/close/low/high 的 DataFrame（倒序）
        :param reasons: 命中理由列表
        :return: True 表示出现底分型
        """
        if len(df) < 3:
            return False  # 至少需要三根K线
        # 取最近三根（倒序 idx0/1/2）
        l0 = df['low'].iloc[0]
        l1 = df['low'].iloc[1]
        l2 = df['low'].iloc[2]
        h0 = df['high'].iloc[0]
        h1 = df['high'].iloc[1]
        h2 = df['high'].iloc[2]
        # 中间K线最低价低于左右两侧（底分型核心）
        if l1 < l0 and l1 < l2:
            # 中间K线最高点也低于左右两侧（标准底分型，高低点均被包裹）
            if h1 < h0 and h1 < h2:
                # 可选增强：右侧K线要求阳线确认
                if self.params.get('fractal_require_yang', True):
                    is_yang = df['close'].iloc[0] > df['open'].iloc[0]  # 最新K线收阳
                    if not is_yang:
                        return False
                reasons.append("底部特征：底分型形态（近三日最低价与最高价均居中）")
                return True
        return False

    # ------------------------------------------------------------------ #
    # 规则2c：低位九转（复用 LowTD9Strategy 状态机）
    # ------------------------------------------------------------------ #
    def _check_low_td9(self, df: pd.DataFrame, reasons: list) -> bool:
        """
        检查最新交易日是否完成买入 Countdown 第9根（今日9转）

        复用 LowTD9Strategy 的正向状态机，仅判定"今日9转完成"，
        不附加完美信号/低位环境过滤（超跌条件已由C1保证）。

        :param df: 含 close/low 的 DataFrame（倒序）
        :param reasons: 命中理由列表
        :return: True 表示今日完成低位九转
        """
        setup_window = int(self._td9.params.get('setup_window', 9))        # Setup连续根数
        setup_offset = int(self._td9.params.get('setup_offset', 4))        # Setup比较偏移
        countdown_offset = int(self._td9.params.get('countdown_offset', 2)) # Countdown偏移
        target = int(self._td9.params.get('countdown_target', 9))          # 9转目标
        res = self._td9._run_td_state_machine(
            df, setup_window, setup_offset, countdown_offset, target, True
        )
        if res.get('countdown_complete', False):
            reasons.append("底部特征：低位九转今日完成（买入Countdown第9根）")
            return True
        return False

    # ------------------------------------------------------------------ #
    # 规则2d：启明星形态（宽松版，仅形态，区别于系统 MorningStarStrategy）
    # ------------------------------------------------------------------ #
    def _check_morning_star(self, df: pd.DataFrame, reasons: list) -> bool:
        """
        检查近三根K线是否构成"阴-小实体-阳"的启明星反转雏形（宽松形态版）

        与系统 MorningStarStrategy 的区别：仅判定形态，不要求突破5日均线、
        不要求成交量放大、不要求第三根涨幅达到阈值，条件更宽松。

        倒序约定：idx0=最新(阳)，idx1=中间(小实体)，idx2=最旧(阴)
        判定：
          ① idx2 为大阴线（收盘<开盘，实体> morning_star_body_threshold）
          ② idx1 实体很小（实体 <= idx2实体 * morning_star_small_ratio）
          ③ idx0 为阳线（收盘>开盘）

        :param df: 含 open/close/low 的 DataFrame（倒序）
        :param reasons: 命中理由列表
        :return: True 表示出现启明星雏形
        """
        if len(df) < 3:
            return False  # 至少需要三根K线
        # 取最近三根（倒序 idx0/1/2）
        c0 = df.iloc[0]  # 最新（第三根/阳线）
        c1 = df.iloc[1]  # 中间（第二根/小实体）
        c2 = df.iloc[2]  # 最旧（第一根/阴线）
        # ① 第一根为大阴线
        body2 = abs(c2['close'] - c2['open']) / c2['open'] if c2['open'] != 0 else 0
        if not (c2['close'] < c2['open'] and body2 > self.params['morning_star_body_threshold']):
            return False
        # ② 第二根实体很小
        body1 = abs(c1['close'] - c1['open']) / c1['open'] if c1['open'] != 0 else 0
        if body1 > body2 * self.params['morning_star_small_ratio']:
            return False
        # ③ 第三根为阳线
        if not (c0['close'] > c0['open']):
            return False
        reasons.append("底部特征：启明星形态（阴-小实体-阳，宽松形态）")
        return True

    # ------------------------------------------------------------------ #
    # 选股主逻辑
    # ------------------------------------------------------------------ #
    def select_stocks(self, df: pd.DataFrame, stock_name: str = '') -> list:
        """
        超跌反弹选股主逻辑：C1 AND C2a(必须) AND (C2b OR C2c OR C2d) AND C3

        :param df: 个股日线数据（倒序，index=0最新）
        :param stock_name: 股票名称（用于信号说明）
        :return: 命中返回 [signal_dict]，否则 []
        """
        # 数据充足性检查（至少需覆盖超跌窗口 + 反弹窗口 + 背离窗口）
        min_len = max(
            int(self.params['lookback_days']),
            int(self.params.get('high_drawdown_days', 120)),
            int(self.params['macd_divergence_days']),
        )
        if df is None or len(df) < min_len:
            return []  # 数据不足，直接剪枝

        # ST/退市名称过滤（2026-09-19 补齐：此前策略内未校验，仅依赖上游配置）
        if stock_name and not self._validate_stock_name(stock_name):
            return []

        # 选股范围：排除次新股（K 线数 ≤ exclude_new_stock_bars）——与「次新腰斩策略」互斥
        #   注：df 已按选股日切片，len(df) 即"截至选股日的可见 K 线数"；min_data_len 保证
        #   预加载窗口内的根数足够（>阈值），因此本判定对老股不会误伤。
        _bars_now = int(len(df))
        _ex_bars = int(self.params.get('exclude_new_stock_bars', 120))
        if _bars_now <= _ex_bars:
            # 注意：本模块历史上**没有模块级 logger**，此处局部获取，避免 NameError
            import logging
            logging.getLogger(__name__).info(
                "【超跌反弹】%s K线数 %d ≤ %d（次新），不在本策略选股范围",
                stock_name or '', _bars_now, _ex_bars)
            return []

        # 计算 MACD 指标（C2a 需要）
        df = self.calculate_indicators(df)

        reasons = []  # 累计命中理由
        # 规则1：超跌深度（必要条件）
        decline = self._check_oversold(df, reasons)
        if decline < 0:
            return []  # 不满足超跌，快速剪枝

        # 规则3：反弹幅度约束（必要条件）
        if not self._check_rebound_cap(df, reasons):
            return []  # 反弹幅度已超过上限，快速剪枝

        # 规则C3b：选股日必须阳线且涨幅>0（必要条件，可通过参数关闭）
        if self.params.get('require_selection_day_yang', True):
            if not self._check_selection_day_yang(df, reasons):
                return []  # 选股日非阳线或收跌，快速剪枝

        # 规则C4：选股日涨幅需达到最小阈值（必要条件，过滤弱反弹）
        if not self._check_selection_day_gain(df, reasons):
            return []  # 选股日涨幅未达阈值，快速剪枝

        # 规则C5：选股日量能需放大至前 N 日均量的指定倍数（必要条件）
        if not self._check_volume_surge(df, reasons):
            return []  # 选股日量能未放大，快速剪枝

        # 规则2a：MACD底背离（必须条件，不满足则直接剪枝）
        hit_features = []  # 记录命中的特征标签
        if not self._check_macd_divergence(df, reasons):
            return []  # 无MACD底背离，不满足必须条件，快速剪枝
        hit_features.append('MACD底背离')

        # 规则2b/2c/2d：底分型 / 低位九转 / 启明星（满足之一即可）
        if self.params.get('enable_bottom_fractal', True) and self._check_bottom_fractal(df, reasons):
            hit_features.append('底分型')
        if self.params.get('enable_low_td9', True) and self._check_low_td9(df, reasons):
            hit_features.append('低位九转')
        if self.params.get('enable_morning_star', True) and self._check_morning_star(df, reasons):
            hit_features.append('启明星')

        if len(hit_features) < 2:
            return []  # 仅有底背离而无其他底部特征，不入选

        # 组装信号
        key_date = str(df['date'].iloc[0])[:10] if 'date' in df.columns else ''
        signal = {
            'code': '',  # 由调用方（execute_selection）填充
            'name': stock_name,
            'key_date': key_date,
            'key_date_type': '超跌反弹',
            'reasons': reasons,
            'strategy_type': 'OversoldReboundStrategy',
            'features': hit_features,  # 命中的底部特征列表
            'decline_pct': round(decline * 100, 2),  # 区间最高→最低下跌幅度(%)，用于排序展示
        }
        return [signal]

    # ------------------------------------------------------------------ #
    # 选股条件说明（前端展示用）
    # ------------------------------------------------------------------ #
    def get_selection_criteria(self) -> list:
        """
        返回策略选股条件的可读说明列表

        :return: 条件说明字符串列表
        """
        hd = int(self.params.get('high_drawdown_days', 120))
        hdd = float(self.params.get('high_drawdown_min', 0.50))
        lb = int(self.params['lookback_days'])
        cap = float(self.params['rebound_cap'])
        ex_bars = int(self.params.get('exclude_new_stock_bars', 120))
        return [
            f"选股范围：上市以来 K 线数 > {ex_bars} 根（排除次新，与次新腰斩策略互斥）",
            f"必要条件：选股日收盘价 < 近{hd}日最高价的 {(1-hdd)*100:.0f}%"
            f"（相对最高价跌幅 ≥ {hdd*100:.0f}%）",
            f"必要条件：选股日收盘较区间最低价反弹幅度 <= {cap*100:.0f}%",
            "必要条件：选股日为阳线且相对前一日收盘涨幅 > 0",
            f"必要条件：选股日相对前一日收盘涨幅 > {float(self.params['selection_day_min_gain'])*100:.0f}%",
            f"必要条件：选股日成交量达前{int(self.params['volume_avg_days'])}日均量的 {float(self.params['volume_surge_ratio']):.1f} 倍及以上",
            "必须特征：",
            "  ① MACD底背离：价格创新低而MACD柱未同步新低（必须）",
            "附加特征（满足之一）：",
            "  ② 底分型：近三根K线最低价居中",
            "  ③ 低位九转：最新交易日完成买入Countdown第9根",
            "  ④ 启明星形态：近三根K线呈阴-小实体-阳（宽松形态）",
        ]
