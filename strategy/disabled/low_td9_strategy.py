"""
低位九转策略（LowTD9Strategy）

基于 Tom DeMark TD Sequential（TD 序列 / 9转序列）的底部反转选股策略。
通过识别"买入 Countdown（低位9转）今日完成"的个股，捕捉下跌动能衰竭的潜在底部买点。

核心规则（经需求确认）：
1. 强制前置买入 Setup：连续 9 根满足 close[t] < close[t-4] 完成后，才启动买入 Countdown。
2. 买入 Countdown：自 Setup 完成后，连续满足 close[t] <= close[t-2] 累计达到第 9 根，
   且仅当今日(T日)为该连续序列第 9 根时入选（"今天形成"低位9转）。
3. 低位环境过滤（默认开启）：距阶段高点回撤≥阈值 且 收盘价<60日均线 且 近20日涨幅<上限。
4. 取消规则（默认开启）：Countdown 累计过程中若出现卖出 Setup 完成（连续 9 根 close[t] > close[t-4]），
   当前买入 Countdown 作废清零。
5. 完美信号（硬门槛）：Countdown 第 8 或第 9 根最低价 < 第 6、7 根最低价，否则不入选。
6. 状态实时计算，不落库；复用 BaseStrategy 通用过滤（ST/退市/停牌）。
基准价统一使用收盘价（与评分/回测一致）。
"""
import pandas as pd
import numpy as np
from strategy.base_strategy import BaseStrategy


class LowTD9Strategy(BaseStrategy):
    """
    低位九转策略类

    继承 BaseStrategy，实现 calculate_indicators() 与 select_stocks() 方法。
    完整链路：买入 Setup 前置 → 买入 Countdown 计数 → 取消规则 → 低位环境过滤 → 完美信号硬门槛。
    """

    def __init__(self, params=None, **kwargs):
        """
        初始化低位九转策略

        :param params: 用户自定义参数字典，会覆盖默认参数
        :param kwargs: 兼容以关键字形式传入的单个参数（如 enable_cancellation=True）
        """
        # 合并 kwargs 到 params（支持 LowTD9Strategy(enable_low_filter=False) 写法）
        if kwargs:
            params = dict(params or {})
            params.update(kwargs)

        # 默认参数 - 与 config/strategy_params.yaml 中的默认值保持一致
        default_params = {
            # TD Setup 前置（买入结构）
            'setup_window': 9,                 # 买入/卖出 Setup 所需连续根数
            'setup_offset': 4,                 # 比较偏移 close[t] vs close[t-4]
            # TD Countdown（9转）
            'countdown_target': 9,             # Countdown 完成目标根数
            'countdown_offset': 2,             # 比较偏移 close[t] vs close[t-2]（DeMark 原版 Countdown）
            # 低位环境过滤（默认开启）
            'enable_low_filter': False,        # 是否启用低位环境过滤（已按需求关闭三项低位环境判定）
            'low_drawdown_window': 60,         # 回撤计算回溯交易日
            'low_drawdown_max': 0.85,          # 距阶段高点最大比例（≤则低位）
            'enable_ma60': True,               # 是否要求收盘价 < 60日均线
            'max_upwave': 0.30,                # 近20日最大涨幅上限
            # 取消规则（默认开启）
            'enable_cancellation': True,       # 卖出 Setup 完成则作废当前买入 Countdown
            # 完美信号（硬门槛）
            'enable_perfection': True,         # 是否要求完美信号（第8/9根低点<第6/7根低点）
            # 数据长度
            'min_data_len': 13,                # 最少历史交易日（TD Setup+Countdown 结构在13根内完成判定）
        }

        # 合并用户参数 - params 中的值覆盖默认值
        if params:
            default_params.update(params)

        # 调用父类初始化
        super().__init__("低位九转策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算技术指标（MA60，用于低位环境过滤）

        :param df: 股票数据DataFrame（倒序，最新在index=0）
        :return: 添加了指标列的DataFrame
        """
        # 检查输入数据是否为空
        if df is None or df.empty:
            return df

        # 已计算则跳过
        if 'ma60' in df.columns:
            return df

        result = df.copy()

        # 倒序数据：转正序计算均线，再恢复倒序
        close_reversed = result['close'].iloc[::-1]
        ma60_reversed = close_reversed.rolling(window=60, min_periods=1).mean()
        result['ma60'] = ma60_reversed.iloc[::-1].values

        return result

    def _run_td_state_machine(self, df, setup_window, setup_offset,
                               countdown_offset, target, enable_cancellation):
        """
        正向（时间顺序）运行 TD Sequential 状态机，识别买入 Setup 前置 + 买入 Countdown

        采用 Tom DeMark 标准时序：先累计买入 Setup（连续 setup_window 根 close[i] < close[i-offset]），
        Setup 完成后，紧接着的 bar 起累计买入 Countdown（close[i] <= close[i-countdown_offset]）。
        Countdown 累计到 target 根且恰为最新一根（今日）即视为"今日形成低位9转"。
        取消规则：Countdown 进行中若出现卖出 Setup 完成（连续 setup_window 根 close[i] > close[i-offset]），
        当前 Countdown 清零作废。

        :param df: 含 close/low 的 DataFrame（倒序，index=0 最新）
        :param setup_window: Setup 连续根数
        :param setup_offset: Setup 比较偏移（4）
        :param countdown_offset: Countdown 比较偏移（2）
        :param target: Countdown 目标根数（9）
        :param enable_cancellation: 是否启用卖出 Setup 取消规则
        :return: dict，含 setup_done/setup_end_pos(时间序)/countdown_complete(是否今日9转)/
                 countdown_end_pos(时间序)/cancelled
        """
        n = len(df)
        # 转为时间顺序（index=0 最旧）
        close_fwd = df['close'].iloc[::-1].reset_index(drop=True)
        low_fwd = df['low'].iloc[::-1].reset_index(drop=True)

        result = {
            'setup_done': False,
            'setup_end_pos': -1,          # 时间序
            'countdown_complete': False,  # 今日是否第9根
            'countdown_end_pos': -1,      # 时间序（今日完成时 = n-1）
            'cancelled': False,
        }

        setup_cnt = 0
        sell_setup_cnt = 0
        countdown_cnt = 0
        last_setup_end = -1
        countdown_active = False  # Countdown 一旦启动即锁定到该 Setup，后续重复 Setup 不接管

        for i in range(n):
            # 买入 Setup 更新（仅当 Countdown 尚未激活时才累计 Setup，避免重复 Setup 重置 Countdown）
            if not countdown_active:
                if i >= setup_offset:
                    c_ok = (not pd.isna(close_fwd.iloc[i])) and (not pd.isna(close_fwd.iloc[i - setup_offset]))
                    if c_ok and close_fwd.iloc[i] < close_fwd.iloc[i - setup_offset]:
                        setup_cnt += 1
                    else:
                        setup_cnt = 0
                else:
                    setup_cnt = 0

                # Setup 完成（刚好累计到 setup_window）
                if setup_cnt == setup_window:
                    last_setup_end = i
                    setup_cnt = 0           # 完成后重置
                    countdown_active = True  # 启动 Countdown，后续 Setup 不再接管
                    result['setup_done'] = True
                    result['setup_end_pos'] = i

            # 卖出 Setup 更新（取消规则，仅当 Countdown 进行中才判定）
            sell_just_done = False
            if enable_cancellation and countdown_active and i >= setup_offset:
                c_ok = (not pd.isna(close_fwd.iloc[i])) and (not pd.isna(close_fwd.iloc[i - setup_offset]))
                if c_ok and close_fwd.iloc[i] > close_fwd.iloc[i - setup_offset]:
                    sell_setup_cnt += 1
                else:
                    sell_setup_cnt = 0
                if sell_setup_cnt == setup_window:
                    sell_just_done = True
                    sell_setup_cnt = 0

            # 买入 Countdown 累计（Setup 完成并激活后）
            if countdown_active and i > last_setup_end:
                if sell_just_done:
                    countdown_cnt = 0   # 卖出 Setup 完成 -> 取消当前 Countdown
                    countdown_active = False
                    result['cancelled'] = True
                    continue
                if i >= countdown_offset:
                    c_ok = (not pd.isna(close_fwd.iloc[i])) and (not pd.isna(close_fwd.iloc[i - countdown_offset]))
                    if c_ok and close_fwd.iloc[i] <= close_fwd.iloc[i - countdown_offset]:
                        countdown_cnt += 1
                        if countdown_cnt == target:
                            # 达标：若恰为最后一根（今日）则记为今日形成
                            if i == n - 1:
                                result['countdown_complete'] = True
                                result['countdown_end_pos'] = i
                    else:
                        countdown_cnt = 0  # 中断清零

        return result

    def _calc_buy_setup_start(self, df, setup_window, offset):
        """
        定位最近一次"买入 Setup 完成"的结束位置（时间序 iloc）

        委托给正向状态机，返回 setup_end_pos；若无则返回 None。

        :param df: 含指标的DataFrame（倒序）
        :param setup_window: 连续根数
        :param offset: 比较偏移
        :return: 买入 Setup 完成最后一根的时间序位置；None 表示无
        """
        res = self._run_td_state_machine(df, setup_window, offset, 2, 9, False)
        if res['setup_done']:
            return res['setup_end_pos']
        return None

    def _calc_sell_setup_complete(self, df, setup_window, offset, countdown_start, countdown_end):
        """
        判定在买入 Countdown 区间是否出现"卖出 Setup 完成"（取消规则）

        :param df: 含指标的DataFrame（倒序）
        :param setup_window: 连续根数
        :param offset: 比较偏移
        :param countdown_start: 未使用（状态机内统一处理）
        :param countdown_end: 未使用
        :return: True 表示区间内出现卖出 Setup 完成（需取消）
        """
        res = self._run_td_state_machine(df, setup_window, offset, 2, 9, True)
        return res['cancelled']

    def _calc_countdown(self, df, offset, target, start_pos):
        """
        计算买入 Countdown 是否在第 target 根完成且今日为第 target 根

        委托给正向状态机；start_pos 为买入 Setup 完成位置（时间序），用于兼容旧调用签名。

        :param df: 含指标的DataFrame（倒序）
        :param offset: 比较偏移
        :param target: 目标根数（9）
        :param start_pos: 买入 Setup 完成位置（时间序），未使用（状态机内部已处理）
        :return: (是否今日完成9转, Countdown 终点时间序位置); 未完成为 (False, None)
        """
        res = self._run_td_state_machine(df, 9, 4, offset, target, False)
        if res['countdown_complete']:
            return True, res['countdown_end_pos']
        return False, (res['countdown_end_pos'] if res['countdown_end_pos'] != -1 else None)

    def _check_low_env(self, df, params):
        """
        低位环境过滤：确保处于相对低位而非高位中继

        条件（默认全开）：
          1. 距阶段高点回撤：close[0] / max(close[近 drawdown_window]) <= low_drawdown_max
          2. 收盘价 < 60日均线（弱势低位）
          3. 近20日最大涨幅 < max_upwave（排除主升浪中段的高位9转）

        :param df: 含指标的DataFrame（倒序）
        :param params: 参数字典
        :return: True 表示处于低位环境
        """
        if not params.get('enable_low_filter', True):
            return True

        n = len(df)
        latest_close = df['close'].iloc[0]

        # 条件1：距阶段高点回撤
        win = int(params.get('low_drawdown_window', 60))
        window_closes = df['close'].iloc[0: win + 1]
        if window_closes.empty:
            return False
        max_close = window_closes.max()
        if max_close <= 0:
            return False
        if (latest_close / max_close) > float(params.get('low_drawdown_max', 0.85)):
            return False

        # 条件2：收盘价 < 60日均线（自行滚动计算，避免依赖外部 ma60 列）
        if params.get('enable_ma60', True):
            ma_win = 60
            # df 为倒序（最新在前），取最近 ma_win 根收盘价求均值
            ma_closes = df['close'].iloc[0:ma_win]
            if len(ma_closes) < ma_win:
                return False  # 数据不足60根，无法计算MA60，判否
            ma60 = ma_closes.mean()
            if pd.isna(ma60) or latest_close >= ma60:
                return False

        # 条件3：近20日最大涨幅上限
        max_upwave = float(params.get('max_upwave', 0.30))
        recent20 = df['close'].iloc[0:21]
        if len(recent20) >= 2:
            ref = recent20.min()
            if ref > 0:
                # 近20日最大相对最低点的涨幅
                upwave = (latest_close / ref) - 1
                if upwave >= max_upwave:
                    return False

        return True

    def _check_perfection(self, df, complete_pos_fwd, params):
        """
        完美信号硬门槛（TD Perfection）

        要求 Countdown 第 8 或第 9 根最低价 < 第 6、7 根最低价。
        complete_pos_fwd 为第 9 根的时间序位置（时间序 index=0 最旧）。
        在时间序中，第9、8、7、6根分别为 complete_pos_fwd、complete_pos_fwd-1、
        complete_pos_fwd-2、complete_pos_fwd-3（朝向旧方向递减），需保证索引>=0。

        :param df: 含指标的DataFrame（倒序，index=0 最新）
        :param complete_pos_fwd: 第9根时间序位置
        :param params: 参数字典
        :return: True 表示满足完美信号
        """
        if not params.get('enable_perfection', True):
            return True

        if complete_pos_fwd is None or complete_pos_fwd < 3:
            return False  # 历史不足，无法验证完美，硬门槛下判否

        # 倒序 -> 时间序 low 序列
        low_fwd = df['low'].iloc[::-1].reset_index(drop=True)
        p9 = complete_pos_fwd
        p8 = complete_pos_fwd - 1
        p7 = complete_pos_fwd - 2
        p6 = complete_pos_fwd - 3
        if min(p6, p7, p8, p9) < 0:
            return False

        try:
            low9 = low_fwd.iloc[p9]
            low8 = low_fwd.iloc[p8]
            low7 = low_fwd.iloc[p7]
            low6 = low_fwd.iloc[p6]
            if pd.isna(low9) or pd.isna(low8) or pd.isna(low7) or pd.isna(low6):
                return False
            # 第8或第9根低点低于第6、7根低点
            return (low8 < low7 and low8 < low6) or (low9 < low7 and low9 < low6)
        except Exception:
            return False

    def _near_run(self, df, params) -> int:
        """
        计算当日就近连续满足"每天比4天前低"的根数（漏斗判定核心指标）

        规则：从最新一根（idx=0）向前数，连续满足 close[idx] <= close[idx + setup_offset]
              （即时间序 close[t] <= close[t-4]）的最大连续根数。

        Args:
            df: 股票数据DataFrame（倒序，最新在前）
            params: 策略参数字典

        Returns:
            int: 当日就近连续下跌结构根数（数据不足时返回 0）
        """
        setup_offset = int(params.get('setup_offset', 4))
        closes = df['close'].to_numpy(dtype=float)  # 倒序 numpy 数组，idx0=最新
        n = len(closes)
        max_run = n - setup_offset - 1
        if max_run <= 0:
            return 0
        run = 0
        # 从最新根向前连续计数，遇不满足即中断
        for i in range(max_run):
            if closes[i] <= closes[i + setup_offset]:
                run += 1
            else:
                break
        return run

    def _quick_prune(self, df, params) -> bool:
        """
        漏斗前置快速剪枝：判断当日就近是否具备连续下跌结构（买入 Setup 雏形）

        规则：当日就近连续满足 close[t] <= close[t-4]（"每天比4天前低"）的根数
              near_run 若 < min_near_run，说明当日就近未形成下跌结构，直接剪枝，
              跳过后续昂贵的完整状态机与各项过滤。

        Args:
            df: 股票数据DataFrame（倒序，最新在前）
            params: 策略参数字典

        Returns:
            bool: True 表示通过漏斗（需跑完整状态机），False 表示剪枝
        """
        min_near_run = int(params.get('min_near_run', 9))
        if min_near_run <= 0:
            return True  # 门槛关闭，全部放行
        return self._near_run(df, params) >= min_near_run

    def select_stocks(self, df, stock_name='') -> list:
        """
        选股主逻辑：低位9转完整判定

        流程：
          1. 数据长度校验（>= min_data_len）
          2. ST/*ST/退市过滤（基类通用，此处再补名称过滤）
          3. 定位最近买入 Setup 完成（前置门槛）
          4. 计算买入 Countdown，确认今日完成第 9 根
          5. 取消规则：Countdown 区间出现卖出 Setup 完成则作废
          6. 低位环境过滤
          7. 完美信号硬门槛
          8. 生成信号

        :param df: 股票数据DataFrame（倒序，最新在前）
        :param stock_name: 股票名称，用于过滤ST/退市
        :return: 选股信号列表，每个元素为字典包含信号详情
        """
        try:
            # 数据长度校验
            min_len = int(self.params.get('min_data_len', 13))
            if df is None or len(df) < min_len:
                return []

            # 过滤 ST/*ST 和退市股票（基类已做部分，此处补充名称）
            if stock_name:
                name_upper = stock_name.upper()
                if 'ST' in name_upper or '*ST' in name_upper:
                    return []
                for keyword in ['退', '未知', '退市', '已退']:
                    if keyword in stock_name:
                        return []

            setup_window = int(self.params.get('setup_window', 9))
            setup_offset = int(self.params.get('setup_offset', 4))
            countdown_target = int(self.params.get('countdown_target', 9))
            countdown_offset = int(self.params.get('countdown_offset', 2))

            # 漏斗前置：当日就近连续满足 close[t] <= close[t-4] 的根数不足则直接剪枝，
            # 跳过昂贵的完整状态机（参见低位九转策略性能优化设计说明书）
            if not self._quick_prune(df, self.params):
                return []

            # 步骤1~3：正向状态机一次性完成 Setup 前置、Countdown 今日完成、取消规则判定
            td = self._run_td_state_machine(
                df, setup_window, setup_offset, countdown_offset,
                countdown_target, bool(self.params.get('enable_cancellation', True)))

            # 步骤1：买入 Setup 前置（必须完成才启动 Countdown）
            if not td['setup_done']:
                return []

            # 步骤2：买入 Countdown 今日完成第9根
            if not td['countdown_complete'] or td['countdown_end_pos'] < 0:
                return []

            # 步骤3：取消规则已在状态机内处理（cancelled 时 countdown_complete 不会置位）

            # 步骤4：低位环境过滤
            if not self._check_low_env(df, self.params):
                return []

            # 步骤5：完美信号硬门槛
            if not self._check_perfection(df, td['countdown_end_pos'], self.params):
                return []

            # 生成信号
            reasons = ['低位9转完成（买入Countdown第9根）']
            if self.params.get('enable_low_filter', True):
                reasons.append('低位环境（回撤达标+弱势均线）')
            if self.params.get('enable_perfection', True):
                reasons.append('完美信号（低点结构确认）')

            # 关键日 = 今日（9转完成日）
            key_date = df['date'].iloc[0]

            signal = {
                'date': str(df['date'].iloc[0]),
                'close': float(df['close'].iloc[0]),
                'low': float(df['low'].iloc[0]),
                'ma60': float(df['ma60'].iloc[0]) if 'ma60' in df.columns and not pd.isna(df['ma60'].iloc[0]) else 0.0,
                'setup_end_pos': int(td['setup_end_pos']),
                'countdown_complete_pos': int(td['countdown_end_pos']),
                'key_date': key_date.strftime('%Y-%m-%d') if hasattr(key_date, 'strftime') else str(key_date)[:10],
                'key_date_type': '低位9转完成日',
                'reasons': reasons,
            }

            return [signal]

        except Exception:
            # 异常保护：返回空列表
            return []

    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []
        criteria.append("前置：买入 Setup 完成（连续9根 close[t] < close[t-4]）")
        criteria.append(f"核心：买入 Countdown 今日完成第{int(self.params.get('countdown_target', 9))}根（close[t] <= close[t-2] 连续累计）")
        if self.params.get('enable_cancellation', True):
            criteria.append("取消规则：Countdown 期间出现卖出 Setup 完成则作废")
        if self.params.get('enable_low_filter', True):
            criteria.append(f"低位环境：距阶段高点回撤≤{float(self.params.get('low_drawdown_max', 0.85))*100:.0f}% 且 收盘价<60日均线 且 近20日涨幅<{float(self.params.get('max_upwave', 0.30))*100:.0f}%")
        if self.params.get('enable_perfection', True):
            criteria.append("完美信号硬门槛：第8或第9根低点 < 第6、7根低点")
        return criteria
