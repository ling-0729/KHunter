"""
强势洗盘弱转强策略 - 识别股票在短期内经历放量上涨、洗盘回调后再次走强的形态

选股条件：
1. 放量大阳线：最近5个交易日内出现涨幅≥8%的大阳线，成交量≥5日均量的2倍
2. 放量阴线洗盘：大阳线次日出现阴线，成交量≥大阳线的1.5倍
3. 反包阳线：洗盘后3个交易日内出现反包阳线，收盘价>大阳线收盘价 或 >洗盘日开盘价
4. 持续强势：反包后至今天的收盘价都在大阳线上方

策略特点：
- 量价配合：强调成交量的配合，确保资金真实参与
- 形态确认：通过大阳线、阴线洗盘、反包阳线的形态组合，确认主力意图
- 时间窗口：严格的时间窗口限制，确保形态的有效性
- 趋势确认：反包后的持续强势，确认趋势反转
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy


class StrongWashWeakToStrongStrategy(BaseStrategy):
    """强势洗盘弱转强策略 - 识别股票在短期内经历放量上涨、洗盘回调后再次走强的形态"""
    
    def __init__(self, params=None):
        # 默认参数配置
        default_params = {
            # 大阳线条件
            'big_candle_lookback_days': 6,          # 大阳线回溯天数（6个交易日内）
            'big_candle_threshold': 0.08,           # 大阳线涨幅阈值（8%）
            'volume_ratio_threshold': 1.5,          # 大阳线成交量比（相对于5日均量）
            
            # 洗盘条件
            'wash_volume_ratio': 1.2,               # 洗盘成交量比（相对于大阳线成交量）
            
            # 反包条件
            'reversal_days': 3,                     # 反包时间窗口（3天内）
            'reversal_price_threshold': 0.0         # 反包价格阈值
        }
        
        # 合并用户参数
        if params:
            default_params.update(params)
        
        super().__init__("强势洗盘弱转强", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算强势洗盘弱转强策略所需的指标
        
        参数:
            df: 股票日线数据
            
        返回:
            添加了指标列的DataFrame
        """
        result = df.copy()
        
        # 按日期升序排序，确保技术指标计算正确
        result = result.sort_values('date', ascending=True)
        
        # 计算5日均量线
        result['volume_ma5'] = result['volume'].rolling(window=5, min_periods=1).mean()
        
        # 计算成交量比
        result['volume_ratio'] = result['volume'] / result['volume_ma5']
        
        # 计算涨幅（与前一天收盘价相比）
        result['change'] = (result['close'] - result['close'].shift(1)) / result['close'].shift(1)
        
        # 填充缺失值
        result = result.ffill().bfill()
        
        # 按日期降序排序，返回与输入相同的顺序
        result = result.sort_values('date', ascending=False)
        
        return result
    
    def get_selection_criteria(self):
        """
        获取选股条件描述
        :return: 选股条件描述列表
        """
        criteria = []
        
        # 条件1：放量大阳线
        big_candle_threshold = self.params['big_candle_threshold'] * 100
        volume_ratio_threshold = self.params['volume_ratio_threshold']
        big_candle_lookback_days = self.params['big_candle_lookback_days']
        criteria.append(f"1. 放量大阳线：最近{big_candle_lookback_days}个交易日内出现涨幅≥{big_candle_threshold:.1f}%的大阳线，成交量≥5日均量的{volume_ratio_threshold}倍")
        
        # 条件2：放量阴线洗盘
        wash_volume_ratio = self.params['wash_volume_ratio']
        criteria.append(f"2. 放量阴线洗盘：大阳线次日出现阴线，成交量≥大阳线的{wash_volume_ratio}倍")
        
        # 条件3：反包阳线
        reversal_days = self.params['reversal_days']
        criteria.append(f"3. 反包阳线：洗盘后{reversal_days}个交易日内出现反包阳线，收盘价>大阳线收盘价或洗盘日开盘价")
        
        # 条件4：持续强势
        criteria.append(f"4. 持续强势：反包后至今天的收盘价都在大阳线上方")
        
        return criteria
    
    def quick_filter(self, df) -> bool:
        """
        快速过滤：最近6个交易日内是否出现涨幅≥8%的大阳线
        
        只涉及价格过滤，不涉及技术指标计算
        df 是倒序数据（最新在前）
        """
        if df is None or df.empty or len(df) < 6:
            return False
        
        # 检查最近6个交易日内是否有涨幅≥8%的大阳线
        for i in range(min(6, len(df))):
            row = df.iloc[i]
            
            # 检查是否为阳线
            if row['close'] <= row['open']:
                continue
            
            # 计算涨幅：相对前一日收盘价的涨幅
            if i + 1 < len(df):
                prev_close = df.iloc[i + 1]['close']
                if prev_close > 0:
                    change = (row['close'] - prev_close) / prev_close
                    if change >= self.params['big_candle_threshold']:
                        return True
        
        return False
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别强势洗盘弱转强信号
        
        参数:
            df: 股票日线数据
            stock_name: 股票名称
            
        返回:
            选股信号列表
        """
        if df.empty or len(df) < self.params['big_candle_lookback_days'] + 5:
            return []
        
        # 快速预检查：过滤退市/异常股票
        if stock_name:
            if stock_name.startswith('*ST') or stock_name.startswith('ST') or '退' in stock_name:
                return []
        
        # 快速过滤
        if not self.quick_filter(df):
            return []
        
        # 计算技术指标
        df_with_indicators = self.calculate_indicators(df)
        if df_with_indicators.empty:
            return []
        
        # 获取回溯期间的数据
        lookback_days = self.params['big_candle_lookback_days']
        lookback_df = df_with_indicators.head(lookback_days)
        
        # 寻找放量大阳线
        big_candle_info = self._find_big_candle(lookback_df)
        if not big_candle_info:
            return []
        
        # 检查大阳线次日是否为放量阴线
        wash_candle_info = self._check_wash_candle(df_with_indicators, big_candle_info['date'])
        if not wash_candle_info:
            return []
        
        # 检查洗盘后是否出现反包阳线
        reversal_info = self._check_reversal_candle(df_with_indicators, wash_candle_info['date'], big_candle_info['close'])
        if not reversal_info:
            return []
        
        # 检查反包后是否持续强势
        if not self._check_continued_strength(df_with_indicators, reversal_info['date'], big_candle_info['close']):
            return []
        
        # 获取最新一天的数据
        latest = df_with_indicators.iloc[0]
        latest_date = latest['date']
        
        # 生成选股信号
        signal_info = {
            'date': latest_date,
            'close': round(latest['close'], 2),
            'key_date': reversal_info['date'],
            'key_date_type': '反包阳线日',
            'big_candle_date': big_candle_info['date'],
            'big_candle_price': round(big_candle_info['close'], 2),
            'wash_candle_date': wash_candle_info['date'],
            'wash_candle_price': round(wash_candle_info['close'], 2),
            'reversal_candle_date': reversal_info['date'],
            'reversal_candle_price': round(reversal_info['close'], 2),
            'volume_ratio': round(big_candle_info['volume_ratio'], 2),
            'wash_volume_ratio': round(wash_candle_info['volume_ratio'], 2),
            'reasons': ['放量大阳线', '放量阴线洗盘', '反包阳线', '持续强势']
        }
        
        return [signal_info]
    
    def _find_big_candle(self, df) -> dict:
        """
        寻找放量大阳线
        
        参数:
            df: 回溯期间的数据
            
        返回:
            大阳线信息字典，如果没有找到则返回None
        """
        for i, row in df.iterrows():
            # 检查是否为大阳线
            if row['change'] >= self.params['big_candle_threshold'] and row['close'] > row['open']:
                # 检查成交量是否满足要求
                if row['volume_ratio'] >= self.params['volume_ratio_threshold']:
                    return {
                        'date': row['date'],
                        'close': row['close'],
                        'volume': row['volume'],
                        'volume_ratio': row['volume_ratio']
                    }
        return {}
    
    def _check_wash_candle(self, df, big_candle_date) -> dict:
        """
        检查大阳线次日是否为放量阴线
        
        参数:
            df: 股票日线数据
            big_candle_date: 大阳线日期
            
        返回:
            洗盘阴线信息字典，如果没有找到则返回None
        """
        # 重置索引，使索引与位置一致
        df_reset = df.reset_index(drop=True)
        
        # 找到大阳线的位置
        big_candle_idx = df_reset[df_reset['date'] == big_candle_date].index
        if len(big_candle_idx) == 0:
            return {}
        
        big_candle_pos = big_candle_idx[0]
        # 检查大阳线次日是否存在（数据按日期降序排列，次日是前一天的索引减1）
        if big_candle_pos - 1 < 0:
            return {}
        
        # 获取大阳线数据
        big_candle_row = df_reset.loc[big_candle_pos]
        # 获取次日数据（数据按日期降序排列，次日是前一天的索引减1）
        wash_candle_row = df_reset.loc[big_candle_pos - 1]
        
        # 检查是否为阴线
        if wash_candle_row['close'] >= wash_candle_row['open']:
            return {}
        
        # 检查成交量是否满足要求
        wash_volume_ratio = wash_candle_row['volume'] / big_candle_row['volume']
        if wash_volume_ratio < self.params['wash_volume_ratio']:
            return {}
        
        # 检查洗盘是否在大阳线后1天内发生（严格次日）
        # 转换日期格式进行比较
        import pandas as pd
        big_candle_date_obj = pd.to_datetime(big_candle_date)
        wash_candle_date_obj = pd.to_datetime(wash_candle_row['date'])
        # 计算日期差（洗盘日期 - 大阳线日期）
        days_diff = (wash_candle_date_obj - big_candle_date_obj).days
        
        if days_diff != 1:  # 洗盘应严格在大阳线次日
            return {}
        
        return {
            'date': wash_candle_row['date'],
            'close': wash_candle_row['close'],
            'open': wash_candle_row['open'],
            'volume': wash_candle_row['volume'],
            'volume_ratio': wash_volume_ratio
        }
    
    def _check_reversal_candle(self, df, wash_candle_date, big_candle_close) -> dict:
        """
        检查洗盘后是否出现反包阳线
        
        参数:
            df: 股票日线数据
            wash_candle_date: 洗盘阴线日期
            big_candle_close: 大阳线收盘价
            
        返回:
            反包阳线信息字典，如果没有找到则返回None
        """
        # 重置索引，使索引与位置一致
        df_reset = df.reset_index(drop=True)
        
        # 找到洗盘阴线的位置
        wash_candle_idx = df_reset[df_reset['date'] == wash_candle_date].index
        if len(wash_candle_idx) == 0:
            return {}
        
        wash_candle_pos = wash_candle_idx[0]
        # 检查洗盘后是否有足够的交易日（数据按日期降序排列，洗盘后是索引减小的方向）
        if wash_candle_pos - self.params['reversal_days'] < 0:
            return {}
        
        # 获取洗盘阴线数据
        wash_candle_row = df_reset.loc[wash_candle_pos]
        
        # 检查洗盘后3个交易日内是否出现反包阳线（数据按日期降序排列，洗盘后是索引减小的方向）
        for i in range(1, self.params['reversal_days'] + 1):
            reversal_pos = wash_candle_pos - i
            if reversal_pos < 0:
                break
            
            reversal_row = df_reset.loc[reversal_pos]
            # 检查是否为阳线
            if reversal_row['close'] > reversal_row['open']:
                # 检查收盘价是否大于大阳线收盘价或洗盘日开盘价
                if reversal_row['close'] > big_candle_close or reversal_row['close'] > wash_candle_row['open']:
                    return {
                        'date': reversal_row['date'],
                        'close': reversal_row['close'],
                        'open': reversal_row['open']
                    }
        
        return {}
    
    def _check_continued_strength(self, df, reversal_date, big_candle_close) -> bool:
        """
        检查反包后是否持续强势
        
        参数:
            df: 股票日线数据
            reversal_date: 反包阳线日期
            big_candle_close: 大阳线收盘价
            
        返回:
            是否满足持续强势条件
        """
        # 重置索引，使索引与位置一致
        df_reset = df.reset_index(drop=True)
        
        # 找到反包阳线的位置
        reversal_idx = df_reset[df_reset['date'] == reversal_date].index
        if len(reversal_idx) == 0:
            return False
        
        reversal_pos = reversal_idx[0]
        
        # 检查反包后至今天的时间间隔是否合理（不超过5天）
        import pandas as pd
        reversal_date_obj = pd.to_datetime(reversal_date)
        latest_date_obj = pd.to_datetime(df_reset.iloc[0]['date'])
        days_diff = (latest_date_obj - reversal_date_obj).days
        
        if days_diff > 5:  # 反包后到今天不应超过5天
            return False
        
        # 检查反包后至今天的收盘价是否都在大阳线上方
        for i in range(reversal_pos):
            row = df_reset.loc[i]
            if row['close'] <= big_candle_close:
                return False
        
        return True
