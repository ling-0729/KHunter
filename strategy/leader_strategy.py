# -*- coding: utf-8 -*-
"""
龙头策略 (LeaderStrategy)

选股条件（涨停/换手/市值取自 tushare limit_list_d；量能取自本地K线 volume）：
  1. 当日涨停        -> limit_type='U'（已排除 ST/退市/炸板未封）
  2. 严格第 2 板     -> limit_times == 2（昨日也涨停，且排除 3 板及以上）
  3. 封板时间 < 11:00 -> 最后封板时间 last_time（默认判定字段，参数可配为 first_time）
  4. 当日换手率 5%-25% -> turnover_ratio（无限售流通股口径，单位 %，=通达信显示值）
  5. 流通市值 < 300 亿  -> float_mv（单位 元；300 亿 = 30000000000）
  6. 量能温和放大    -> 昨日成交量 < 今日成交量 <= 昨日成交量 × 2.0（K线 volume）
  7. 去除开盘即涨停  -> 选股日 open == 涨停价（一字板与 T 字板都排除，均买不到）
  8. 近期无其他涨停  -> 近 10 个交易日（不含选股日）除昨日外不得再有涨停（按涨停价精确比对）

实现说明：
  - 策略运行框架为“逐只股票传入 K 线”（BaseStrategy.execute_selection），
    本策略在 select_stocks 内按 (code, trade_date) 命中当日涨停股，
    涨停判定由数据层（limit_type='U'）保证，无需在 K 线里重算涨幅阈值。
  - 涨停数据按选股日实时批量获取：一次接口调用取回该交易日全部涨停股，
    仅在内存中参与选股，本地不落库存储任何涨停数据。
  - 同一交易日只请求一次（实例内缓存复用），全市场逐只选股不会重复请求接口。
  - 封板口径默认为最后封板时间 < 11:00，不限制炸板（max_open_times 保持 None 即不限制）。
  - 量能条件取本地K线（选股日与前一根K线的 volume 列）：要求选股日K线存在、昨日成交量 > 0；
    任一缺失（含 volume 列不存在）都保守淘汰，避免用错日期的量做比较。
  - 开盘即涨停与“近期涨停”同样取本地K线：前者看选股日 open 是否等于涨停价（同时覆盖
    一字板与 T 字板，均为开盘即封、无法参与）；近期涨停按
    close == round(前一日 close × (1+涨停幅度), 2) 精确比对（主板 10%、创业板 20%
    （2020-08-24 起，之前 10%）、科创板 20%、北交所 30%），避免用涨幅阈值近似误判。
"""
import os
import pandas as pd
from strategy.base_strategy import BaseStrategy


class LeaderStrategy(BaseStrategy):
    """龙头策略：当日涨停 + 严格第2板 + 早封板 + 换手率 5%-25% + 小流通盘 + 量能温和放大(≤昨日2倍)
    + 非一字板 + 近10日除昨日外无其他涨停。"""

    # 涨停数据获取相关状态（类级：跨实例复用，避免重复初始化）
    _collector = None             # 取数模块缓存（False 表示不可用）
    _pro = None                   # tushare pro_api 实例缓存

    def __init__(self, params=None):
        default_params = {
            'seal_time_field': 'last_time',    # 封板时间判定字段：last_time=最后封板（默认）；first_time=首次封板
            'seal_time_limit': 110000,         # 封板时间上限 HHMMSS（11:00）
            'max_open_times': None,            # 炸板次数上限；None=不限制（严格按字面条件）
            'turnover_min': 5.0,               # 换手率下限(%)
            'turnover_max': 25.0,              # 换手率上限(%)
            'float_mv_max': 30000000000,       # 流通市值上限(元) = 300 亿
            'min_limit_times': 2,              # 连板下限；2=昨日也涨停（严格第2板需上限也为 2）
            'max_limit_times': 2,              # 连板上限；与下限相同即为“严格第 N 板”，None=不限制
            'volume_ratio_max': 2.0,           # 量能上限倍率：昨日量 < 今日量 <= 昨日量×该值
            'exclude_open_limit_up': True,     # 去除开盘即涨停（一字板/T字板：选股日 open == 涨停价）
            'recent_limit_up_window': 10,      # 回看交易日数：窗口内除昨日外有其他涨停即剔除；null/<=1=不检查
            'limit_type': 'U',                 # 涨停（数据源仅取 U）
            'strategy_weight': 70,             # 技术面评分权重
        }
        if params:
            default_params.update(params)
        super().__init__("龙头策略", default_params)
        # 当日涨停池缓存（仅内存，不落库）：{trade_date: {code(6位): row}}
        self._pool_cache = {}
        self._current_code = ''
        # 本次选股中已实时获取过的交易日（实例级，保证同一交易日只请求一次）
        self._fetched_dates = set()

    # ---------- 框架接口重写 ----------
    def analyze_stock(self, stock_code, stock_name, df, selection_date=None):
        """捕获当前股票代码，并显式把 selection_date 透传给选股核心。

        说明：基类 BaseStrategy.execute_selection 调用 select_stocks 时不传 selection_date，
        会使本策略退而用 DataFrame 首行日期作为 trade_date 去查涨停池。web_server 传入的是
        升序 K 线（首行=最早历史日），从而导致查到古老交易日的涨停池而漏选。此处绕过该断点，
        直接以 web_server 传入的 selection_date（已按交易时段回退到前一交易日）作为选股日。
        """
        self._current_code = stock_code
        # 基础数据校验（与框架 execute_selection 保持一致）
        if not self._validate_data(df):
            return None
        signals = self.select_stocks(df, stock_name, selection_date=selection_date)
        if signals:
            return {
                'code': stock_code,
                'name': stock_name,
                'signals': signals,
            }
        return None

    def execute_selection(self, df, stock_code='', stock_name='', selection_date=None):
        """记录当前股票代码后，走基类标准选股流程。

        背景：本策略靠“股票代码 + 选股日”命中涨停池，而基类 execute_selection 并不会
        把 stock_code 传给 select_stocks（select_stocks 只接收 df 与 stock_name）。
        回测引擎与策略运行器正是通过 execute_selection 调用策略，若不在此处记录代码，
        select_stocks 会拿到空的 _current_code 而永远命中不到涨停池，
        表现为“回测/策略运行器选股结果恒为 0”（web_server 走 analyze_stock 则不受影响）。
        此处补齐代码记录，再交由基类完成数据校验、停牌判断与指标计算流程。
        """
        self._current_code = stock_code
        return super().execute_selection(df, stock_code, stock_name, selection_date=selection_date)

    def calculate_indicators(self, df):
        # 涨停判定由数据层保证，无需计算技术指标
        return df

    def quick_filter(self, df):
        return True

    # ---------- 工具 ----------
    @staticmethod
    def _to_yyyymmdd(d):
        s = str(d).replace('-', '').replace('/', '').strip()
        return s[:8] if len(s) >= 8 else s

    @staticmethod
    def _norm_code(code):
        code = str(code or '').strip()
        return code.split('.')[0] if '.' in code else code

    @staticmethod
    def _parse_nullable_int(value):
        """把配置值解析为“可空整数”，用于表示“不限制”的参数。

        背景：strategy_params.yaml 中“不限制”写作 null，经配置加载后常变成字符串
        'null'（本项目其它策略如 volume_ratio_max 亦采用该写法）。若直接用
        int('null') 会抛 ValueError，导致该股票被框架计为“分析失败”而漏选。
        此处统一把 None/''/'null'/'none'/'~'/'nan' 视为不限制（返回 None）。
        """
        if value is None:
            return None
        s = str(value).strip().lower()
        if s in ('', 'null', 'none', '~', 'nan'):
            return None
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_ratio_max(value):
        """解析量能倍率上限：None/''/null/none/≤0 → None（表示不限制上限）

        用于 volume_ratio_max：写 null 即"只要求今日放量、不限制倍率"，
        避免误配 get 到 None 后 float() 抛错而把所有股票静默淘汰。
        """
        if value is None:
            return None
        s = str(value).strip().lower()
        if s in ('', 'none', 'null', '~', 'nan'):
            return None
        try:
            v = float(s)
        except (ValueError, TypeError):
            return None
        return v if v > 0 else None

    @classmethod
    def _get_collector(cls):
        """按路径加载取数模块 scripts/collect_limit_up_pool.py（仅加载一次）。"""
        if cls._collector is not None:
            return cls._collector or None
        try:
            import importlib.util
            import os
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(root, 'scripts', 'collect_limit_up_pool.py')
            spec = importlib.util.spec_from_file_location(
                '_khunter_limit_up_collector', path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cls._collector = mod
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f'加载涨停取数模块失败，实时获取不可用: {e}')
            cls._collector = False
        return cls._collector or None

    def _fetch_pool_by_date(self, trade_date):
        """按交易日期实时批量获取当日全部涨停股（一次接口调用，仅内存使用，不落库）。

        本地不留存任何涨停数据：取回后直接构建 {code: row} 缓存供本次选股复用。
        同一交易日只请求一次——全市场 5000+ 只逐只选股时也不会重复请求接口。
        """
        if trade_date in self._fetched_dates:
            return self._pool_cache.get(trade_date, {})
        self._fetched_dates.add(trade_date)

        mod = LeaderStrategy._get_collector()
        if not mod:
            return {}
        try:
            if LeaderStrategy._pro is None:
                LeaderStrategy._pro = mod.get_pro()
            rows = mod.fetch_limit_up_day(LeaderStrategy._pro, trade_date)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f'按交易日实时获取涨停池失败 {trade_date}: {e}')
            return {}

        pool = {}
        for r in rows:
            pool[self._norm_code(r.get('code') or r.get('ts_code'))] = r
        import logging
        logging.getLogger(__name__).info(
            f'龙头策略按交易日实时获取涨停池 {trade_date}: {len(pool)} 只（内存，不落库）')
        return pool

    def _load_day_pool(self, trade_date):
        """取某交易日的涨停股：一次批量实时取回该日全部涨停股，内存缓存复用。"""
        if trade_date in self._pool_cache:
            return self._pool_cache[trade_date]
        pool = self._fetch_pool_by_date(trade_date)
        self._pool_cache[trade_date] = pool
        return pool

    # ---------- 选股核心 ----------
    @staticmethod
    def _limit_pct(code, date_str):
        """该股在指定交易日适用的涨停幅度（主板 10% / 创业板·科创板 20% / 北交所 30%）"""
        code = str(code or '').split('.')[0]
        d = str(date_str or '')[:10].replace('-', '')
        if code.startswith('688'):
            return 0.20      # 科创板
        if code.startswith('30'):
            # 创业板：2020-08-24 起 20%，此前 10%
            return 0.20 if d >= '20200824' else 0.10
        if code.startswith(('8', '4')):
            return 0.30      # 北交所
        return 0.10          # 沪深主板

    @staticmethod
    def _is_limit_up_bar(code, prev_close, close, date_str):
        """按涨停价精确判定某根K线是否涨停（涨停价 = 前收 ×(1+幅度)，四舍五入到分）"""
        try:
            prev_close = float(prev_close)
            if prev_close <= 0:
                return False
            limit_price = round(prev_close * (1 + LeaderStrategy._limit_pct(code, date_str)), 2)
            return abs(float(close) - limit_price) < 0.005
        except (ValueError, TypeError):
            return False

    def _check_board_style(self, df, code, sel_date):
        """条件7/8：去除一字板；近 N 个交易日（不含选股日）除昨日外不得再有涨停

        开盘即涨停：选股日K线 open == 涨停价（= 前收 ×(1+幅度) 四舍五入到分）。
                    涵盖一字板（全天封死）与 T 字板（开盘涨停→开板→回封），两者均买不到。
        窗口：取选股日之前（不含选股日）的最近 N 根K线，其中“昨日”（选股日前一根）允许涨停，
              其余任一根涨停即淘汰。窗口参数 recent_limit_up_window，null/<=1 表示不检查。

        Returns:
            (是否通过, 窗口内除昨日外的涨停日期列表)
        """
        try:
            sel = str(sel_date)[:10]
            past = (df[df['date'].astype(str).str.slice(0, 10) <= sel]
                    .sort_values('date').reset_index(drop=True))
            n = len(past)
            if n < 2 or str(past.at[n - 1, 'date']).split()[0][:10] != sel:
                return False, []

            # 条件7：去除“开盘即涨停”（一字板与 T 字板：开盘价 == 涨停价）
            if self.params.get('exclude_open_limit_up', True):
                prev_close = float(past.at[n - 2, 'close'])
                open_price = float(past.at[n - 1, 'open'])
                bar_date = str(past.at[n - 1, 'date']).split()[0][:10]
                limit_price = round(
                    prev_close * (1 + LeaderStrategy._limit_pct(code, bar_date)), 2)
                if abs(open_price - limit_price) < 0.005:
                    return False, []

            # 条件8：窗口内除昨日外不得再有涨停
            window = self._parse_nullable_int(self.params.get('recent_limit_up_window', 10))
            if not window or window <= 1:
                return True, []
            start = max(0, n - 1 - window)
            closes = past['close'].astype(float).tolist()
            dates = past['date'].astype(str).str.slice(0, 10).tolist()
            extra = []
            for i in range(start, n - 1):
                if i == 0:
                    continue
                if not LeaderStrategy._is_limit_up_bar(code, closes[i - 1], closes[i], dates[i]):
                    continue
                if i != n - 2:      # 昨日（选股日前一根）允许涨停
                    extra.append(dates[i])
            if extra:
                return False, extra
            return True, []
        except Exception:
            return False, []

    def _check_volume(self, df, sel_date):
        """量能条件：昨日成交量 < 今日成交量 <= 昨日成交量 × volume_ratio_max

        数据源为本地K线（df 的 volume 列）：
          - 取“选股日及之前”的K线并按日期升序；
          - 要求最后一根K线日期 == 选股日（否则为停牌/数据未更新 → 保守淘汰，避免用错日期数据）；
          - 昨日成交量必须 > 0，volume 列缺失或为 NaN → 保守淘汰。

        Returns:
            (是否通过, 今日成交量, 昨日成交量)
        """
        try:
            sel = str(sel_date)[:10]
            past = df[df['date'].astype(str).str.slice(0, 10) <= sel].sort_values('date')
            if len(past) < 2 or 'volume' not in past.columns:
                return False, None, None
            if str(past.iloc[-1]['date']).split()[0][:10] != sel:
                return False, None, None
            today_vol = float(past.iloc[-1]['volume'])
            prev_vol = float(past.iloc[-2]['volume'])
            if pd.isna(today_vol) or pd.isna(prev_vol) or prev_vol <= 0:
                return False, None, None
            ratio_max = self._parse_ratio_max(self.params.get('volume_ratio_max', 2.0))
            if ratio_max is None:
                # 不限制上限：仍要求今日放量
                return (today_vol > prev_vol), today_vol, prev_vol
            if not (prev_vol < today_vol <= prev_vol * ratio_max):
                return False, today_vol, prev_vol
            return True, today_vol, prev_vol
        except Exception:
            return False, None, None

    def select_stocks(self, df, stock_name='', selection_date=None):
        if df is None or len(df) == 0:
            return []
        if not self._validate_stock_name(stock_name):
            return []

        sel_date = selection_date or str(df.iloc[0]['date']).split()[0]
        trade_date = self._to_yyyymmdd(sel_date)
        code = self._norm_code(getattr(self, '_current_code', ''))

        # 条件1：当日涨停（数据层保证 limit_type='U'）
        pool = self._load_day_pool(trade_date)
        row = pool.get(code)
        if row is None:
            return []

        # 条件2：封板时间 < 上限（默认最后封板时间）
        seal_field = self.params.get('seal_time_field', 'last_time')
        seal_val = row.get(seal_field)
        if seal_val is None or seal_val == '':
            return []  # 封板时间缺失，保守不入选
        try:
            if int(str(seal_val).zfill(6)) >= int(self.params['seal_time_limit']):
                return []
        except (ValueError, TypeError):
            return []

        # 条件3：换手率 15%-25%
        tr = row.get('turnover_ratio')
        if tr is None or pd.isna(tr):
            return []
        tr = float(tr)
        if not (self.params['turnover_min'] <= tr <= self.params['turnover_max']):
            return []

        # 条件4：流通市值 < 200 亿
        mv = row.get('float_mv')
        if mv is None or pd.isna(mv):
            return []
        mv = float(mv)
        if mv >= self.params['float_mv_max']:
            return []

        # 附加过滤：炸板次数（None/'null' 等表示不限制）
        max_open = self._parse_nullable_int(self.params.get('max_open_times'))
        if max_open is not None:
            if (row.get('open_times') or 0) > max_open:
                return []

        # 连板条件：下限（昨日也涨停）+ 上限（排除高位连板）
        # 下限 2 且上限 2 → 严格第 2 板；上限 None/'null' → 不限制
        min_lt = self._parse_nullable_int(self.params.get('min_limit_times', 2))
        if min_lt and min_lt > 1:
            if (row.get('limit_times') or 0) < min_lt:
                return []
        max_lt = self._parse_nullable_int(self.params.get('max_limit_times', None))
        if max_lt:
            if (row.get('limit_times') or 0) > max_lt:
                return []

        # 条件6：量能温和放大（昨日量 < 今日量 <= 昨日量 × 倍率上限）
        vol_ok, vol_today, vol_prev = self._check_volume(df, sel_date)
        if not vol_ok:
            return []

        # 条件7/8：形态过滤（非一字板 + 近 N 个交易日除昨日外无其他涨停）
        style_ok, prev_limit_dates = self._check_board_style(df, code, sel_date)
        if not style_ok:
            return []

        # ---------- 命中：构造信号 ----------
        limit_times = row.get('limit_times') or 0
        vol_ratio = (vol_today / vol_prev) if (vol_today and vol_prev) else 0.0
        reasons = [
            f"当日涨停（limit_type={self.params.get('limit_type')}）",
            f"最后封板时间 {seal_val} < {self.params['seal_time_limit']}",
            f"换手率 {tr:.2f}% ∈ [{self.params['turnover_min']},{self.params['turnover_max']}]%",
            f"流通市值 {mv/1e8:.2f}亿 < {self.params['float_mv_max']/1e8:.0f}亿",
            f"量能 {vol_ratio:.2f} 倍（昨日量 < 今日量 ≤ {self.params.get('volume_ratio_max', 2.0)} 倍）",
        ]
        if limit_times and limit_times > 1:
            reasons.append(f"连板 {limit_times} 板")

        # 收盘价优先取涨停池当日快照（已与K线当日收盘价交叉核对一致）。
        # 回退时严格只用“选股日及之前”的K线取最近收盘价，避免未来函数：
        # 直接用 df.iloc[0] 在降序未切片数据上会取到选股日之后的K线。
        close = row.get('close')
        if not close:
            try:
                past = df[df['date'].astype(str).str.slice(0, 10) <= sel_date]
                past = past.sort_values('date')
                close = float(past.iloc[-1]['close']) if len(past) else 0.0
            except Exception:
                close = 0.0
        close = float(close)
        signal = {
            'date': sel_date,
            'close': round(close, 2),
            'volume_ratio': 0,
            'reasons': reasons,
            'key_date': sel_date,
            'key_date_type': '涨停日',
            'pattern_details': {
                'pct_chg': row.get('pct_chg'),
                'turnover_ratio': tr,
                'float_mv': mv,
                'float_mv_yi': round(mv / 1e8, 2),
                'first_time': row.get('first_time'),
                'last_time': row.get('last_time'),
                'open_times': row.get('open_times'),
                'limit_times': limit_times,
                'volume_today': vol_today,
                'volume_prev': vol_prev,
                'volume_ratio': round(vol_ratio, 3),
                'industry': row.get('industry'),
                'fd_amount': row.get('fd_amount'),
            },
            'confirmation_details': {
                'confirmed': True,
                'confirmed_date': sel_date,
                'support_level': round(close, 2),
            },
            'strategy_weight': self.params.get('strategy_weight', 70),
        }
        return [signal]

    # ---------- 展示 ----------
    def get_selection_criteria(self):
        p = self.params
        return [
            f"1. 当日涨停（数据源 tushare limit_list_d 实时获取，limit_type='{p.get('limit_type')}'，已排除ST/退市/炸板未封）",
            f"2. 最后封板时间 < {p['seal_time_limit']}（字段 {p.get('seal_time_field')}，HHMMSS）",
            f"3. 换手率 {p['turnover_min']}%-{p['turnover_max']}%（turnover_ratio，无限售流通股口径）",
            f"4. 流通市值 < {p['float_mv_max']/1e8:.0f} 亿（float_mv，单位元）",
            f"5. 炸板次数上限 {'不限' if p.get('max_open_times') is None else p['max_open_times']}；"
            f"连板条件 {self._describe_limit_times(p)}",
            f"6. 量能条件：昨日成交量 < 今日成交量 ≤ 昨日成交量 × {p.get('volume_ratio_max', 2.0)}（K线 volume）",
            f"7. 去除开盘即涨停：{'开启' if p.get('exclude_open_limit_up', True) else '关闭'}"
            f"（一字板与T字板都排除：选股日 open == 涨停价）",
            f"8. 近期涨停过滤：近 {p.get('recent_limit_up_window', 10)} 个交易日（不含选股日）除昨日外不得再有涨停"
            + ('' if p.get('recent_limit_up_window', 10) else '（当前关闭）'),
        ]

    @staticmethod
    def _describe_limit_times(p):
        """连板条件文案：上下限相同 → 严格第 N 板；否则为区间"""

        def _to_int(v):
            if v is None:
                return None
            s = str(v).strip().lower()
            if s in ('', 'none', 'null', '~', 'nan'):
                return None
            try:
                return int(float(s))
            except (ValueError, TypeError):
                return None

        lo, hi = _to_int(p.get('min_limit_times')), _to_int(p.get('max_limit_times'))
        if lo and hi and lo == hi:
            return f"严格第 {lo} 板（昨日也涨停）"
        return f"连板区间 {lo if lo else 1}~{'不限' if hi is None else hi}"


if __name__ == '__main__':
    # 自测：对指定交易日，按日实时获取涨停股并逐只跑 select_stocks，输出命中
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    td = sys.argv[1] if len(sys.argv) > 1 else '20260827'
    strat = LeaderStrategy()
    pool = strat._load_day_pool(td)      # 按交易日实时批量获取（内存，不落库）
    import datetime as _dt
    day = _dt.datetime.strptime(td, '%Y%m%d').strftime('%Y-%m-%d')
    hits = []
    for code, r in pool.items():
        strat._current_code = code
        df = pd.DataFrame([{'date': day, 'close': r.get('close')}])
        sig = strat.select_stocks(df, r.get('name'), selection_date=day)
        if sig:
            hits.append((code, r.get('name'), sig[0]['pattern_details']))
    print(f'{td} 龙头策略命中 {len(hits)} 只:')
    for code, name, det in hits:
        print(f"  {code} {name} | 换手{det['turnover_ratio']}% 流通{det['float_mv_yi']}亿 "
              f"首封{det['first_time']} 末封{det['last_time']} 炸板{det['open_times']} 连板{det['limit_times']}")
