"""
趋势起点策略 - MACD金叉+布林带上穿中轨

策略逻辑（今天同时满足）：
1. MACD金叉在0轴上方：DIF > 0 且 DIF从下往上穿越DEA
2. 布林带上穿中轨：收盘价从下往上穿越BOLL中轨
3. 当日阳线：收盘价 > 开盘价
4. 站上5日线：收盘价 > MA5
5. 成交量放大：今日成交量 > 1.2倍5日均量

参数（与顺势宝策略保持一致）：
- macd_fast: 12
- macd_slow: 26
- macd_signal: 9
- boll_period: 20
- boll_multiplier: 2
- ma5_period: 5      # 5日均线周期
- volume_ratio: 1.2  # 成交量放大倍数
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy


class TrendStartStrategy(BaseStrategy):
    """趋势起点策略"""

    def __init__(self, params=None):
        # 默认参数（与顺势宝策略保持一致）
        default_params = {
            'macd_fast': 12,        # MACD快速线周期
            'macd_slow': 26,        # MACD慢速线周期
            'macd_signal': 9,       # MACD信号线周期
            'boll_period': 20,      # 布林带周期
            'boll_multiplier': 2,   # 布林带标准差倍数
            'ma5_period': 5,        # 5日均线周期
            'volume_ratio': 1.2,    # 成交量放大倍数
        }
        
        # 合并用户参数
        if params:
            default_params.update(params)
        
        super().__init__("趋势起点策略", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """计算MACD和布林带指标
        
        注意：输入数据应为倒序（最新在前），函数内部会转为正序计算
        """
        result = df.copy()
        
        # 检查数据是否为倒序排列（最新在前），如果是则反转
        if len(result) > 1 and str(result['date'].iloc[0]) > str(result['date'].iloc[1]):
            # 数据是倒序（最新在前），需要反转进行计算
            result = result.iloc[::-1].reset_index(drop=True)
        
        # 计算MACD指标
        macd_fast = self.params['macd_fast']
        macd_slow = self.params['macd_slow']
        macd_signal = self.params['macd_signal']
        
        ema_short = result['close'].ewm(span=macd_fast, adjust=False).mean()
        ema_long = result['close'].ewm(span=macd_slow, adjust=False).mean()
        macd_line = ema_short - ema_long
        signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()
        
        result['dif'] = macd_line
        result['dea'] = signal_line
        result['macd_hist'] = macd_line - signal_line
        
        # 计算布林带指标
        boll_period = self.params['boll_period']
        boll_multiplier = self.params['boll_multiplier']
        
        mid = result['close'].rolling(window=boll_period).mean()
        std = result['close'].rolling(window=boll_period).std()
        
        result['boll_mid'] = mid
        result['boll_upper'] = mid + boll_multiplier * std
        result['boll_lower'] = mid - boll_multiplier * std
        
        # 计算5日均线和5日均量
        ma5_period = self.params['ma5_period']
        result['ma5'] = result['close'].rolling(window=ma5_period).mean()
        result['ma5_volume'] = result['volume'].rolling(window=ma5_period).mean()
        
        # 填充缺失值
        # 注意：只使用bfill()向后填充，避免引入未来函数
        # ffill()会使用未来数据填充NaN，导致回测结果失真
        # result = result.ffill().bfill()  # ⚠️ ffill是未来函数！
        result = result.bfill()
        
        # 反转回倒序（最新在前），以符合策略其他方法的预期
        result = result.iloc[::-1].reset_index(drop=True)
        
        return result
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        """
        return [
            f"MACD参数: fast={self.params['macd_fast']}, slow={self.params['macd_slow']}, signal={self.params['macd_signal']}",
            f"布林带参数: period={self.params['boll_period']}, multiplier={self.params['boll_multiplier']}",
            "1. MACD金叉在0轴上方：DIF > DEA 且 DIF > 0",
            "2. 布林带上穿中轨：收盘价从下往上穿越BOLL中轨",
            "3. 当日阳线：收盘价 > 开盘价",
            "4. 站上5日线：收盘价 > MA5",
            "5. 成交量放大：今日成交量 > 1.2倍5日均量",
        ]
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别趋势起点形态
        
        Args:
            df: 股票数据DataFrame（倒序，最新在前）
            stock_name: 股票名称
            
        Returns:
            选中的股票信号列表
        """
        if df.empty or len(df) < 30:
            return []
        
        # 快速预检查：过滤退市/异常股票
        if stock_name:
            if '退' in stock_name or '未知' in stock_name or '已退' in stock_name:
                return []
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []
        
        # 计算技术指标
        df = self.calculate_indicators(df.copy())
        
        # 检查数据是否足够（需要至少26天计算MACD）
        if len(df) < 30:
            return []
        
        # 获取最新一天的数据
        latest = df.iloc[0]
        latest_date = latest['date']
        
        # 快速检查：最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 检查是否满足趋势起点形态
        signal_info = self._check_trend_start_pattern(df)
        
        if signal_info:
            # 计算市值
            market_cap_val = latest.get('market_cap')
            if market_cap_val is None:
                market_cap_val = latest['close'] * 2e8
            
            # 计算实际成交量比
            actual_volume_ratio = latest['volume'] / latest['ma5_volume'] if latest['ma5_volume'] > 0 else 1.0
            
            signal_info.update({
                'date': latest_date,
                'close': round(latest['close'], 2),
                'volume_ratio': round(actual_volume_ratio, 2),
                'market_cap': round(market_cap_val / 1e8, 2),
                'key_date': signal_info.get('key_date', str(latest_date)[:10]),
                'key_date_type': '趋势起点确认日',
            })
            return [signal_info]
        
        return []
    
    def _check_trend_start_pattern(self, df: pd.DataFrame) -> dict:
        """
        检查是否满足趋势起点形态
        
        规则：今天同时满足
        1. MACD金叉在0轴上方（DIF > 0 且 DIF上穿DEA）
        2. 布林带上穿中轨（收盘价从下往上穿越中轨）
        3. 当日阳线（收盘价 > 开盘价）
        4. 站上5日线（收盘价 > MA5）
        5. 成交量放大（今日成交量 > 1.2倍5日均量）
        
        数据排列：倒序（最新在前）
        - df.iloc[0] = 今天（T日）
        - df.iloc[1] = 昨天（T-1日）
        
        Returns:
            信号信息字典，如果满足条件的话
        """
        if len(df) < 6:  # 需要至少6天数据计算5日均线和均量
            return None
        
        today = df.iloc[0]      # 今天
        yesterday = df.iloc[1]  # 昨天
        
        # 检查今日MACD金叉（需DIF>0）
        today_macd_cross = self._is_macd_cross(today, yesterday)
        
        # 检查今日布林带上穿中轨
        today_boll_cross = self._is_boll_cross_mid(df, 0)
        
        # 检查当日阳线（收盘 > 开盘）
        is_bullish = today['close'] > today['open']
        
        # 检查站上5日线（收盘 > MA5）
        above_ma5 = today['close'] > today['ma5']
        
        # 检查成交量放大（今日 > 1.2倍5日均量）
        volume_ratio = self.params['volume_ratio']
        volume_enough = today['volume'] > today['ma5_volume'] * volume_ratio
        
        # 今天同时满足所有条件
        if today_macd_cross and today_boll_cross and is_bullish and above_ma5 and volume_enough:
            return self._build_signal(df, 0, 'today_macd_today_boll')
        
        return None
    
    def _is_macd_cross(self, today: pd.Series, yesterday: pd.Series) -> bool:
        """
        判断是否发生MACD金叉（在0轴上方）
        
        金叉定义：DIF从下往上穿越DEA，且DIF > 0
        """
        dif_today = today['dif']
        dif_yesterday = yesterday['dif']
        dea_today = today['dea']
        dea_yesterday = yesterday['dea']
        
        # 检查DIF是否在0轴上方
        if dif_today <= 0:
            return False
        
        # 检查是否从下方穿越DEA（严格要求从下往上穿越）
        # 昨天DIF <= 昨天DEA 且 今天DIF > 今天DEA
        if dif_yesterday > dea_yesterday:
            return False
        
        if dif_today <= dea_today:
            return False
        
        return True
    
    def _is_boll_cross_mid(self, df: pd.DataFrame, days_ago: int) -> bool:
        """
        判断布林带是否上穿中轨
        
        Args:
            df: 股票数据DataFrame（倒序）
            days_ago: 0表示今天，1表示昨天
        """
        if len(df) <= days_ago + 1:
            return False
        
        current = df.iloc[days_ago]      # 当前日期
        previous = df.iloc[days_ago + 1] # 前一天
        
        close_current = current['close']
        close_previous = previous['close']
        boll_mid_current = current['boll_mid']
        boll_mid_previous = previous['boll_mid']
        
        # 检查是否有有效值
        if pd.isna(close_current) or pd.isna(close_previous):
            return False
        if pd.isna(boll_mid_current) or pd.isna(boll_mid_previous):
            return False
        
        # 上穿中轨：昨天收盘价在下方，今天收盘价在上方
        return close_previous < boll_mid_previous and close_current > boll_mid_current
    
    def _build_signal(self, df: pd.DataFrame, days_ago: int, pattern_type: str) -> dict:
        """
        构建选股信号
        
        Args:
            df: 股票数据DataFrame
            days_ago: 信号日期偏移（0=今天）
            pattern_type: 形态类型
        """
        today = df.iloc[days_ago]
        today_date = today['date']
        today_date_str = today_date.strftime('%Y-%m-%d') if hasattr(today_date, 'strftime') else str(today_date)[:10]
        
        # 信号原因描述
        reason_map = {
            'today_macd_today_boll': '今日MACD金叉+布林带上穿+阳线+站上5日线+量能放大',
        }
        
        return {
            'reasons': [reason_map.get(pattern_type, '趋势起点形态')],
            'key_date': today_date_str,
            'pattern_type': pattern_type,
            'indicators': {
                'dif': round(today['dif'], 4),
                'dea': round(today['dea'], 4),
                'boll_mid': round(today['boll_mid'], 2),
                'ma5': round(today['ma5'], 2),
                'close': round(today['close'], 2),
                'volume_ratio': round(today['volume'] / today['ma5_volume'], 2),
            }
        }
