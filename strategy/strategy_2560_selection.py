"""
2560战法选股策略
根据2560战法的买入信号规则进行选股

策略规则：
1. 股价向上突破25日均线
2. 5日均量线向上穿过60日均量线（金叉）

选股策略只需要发出选股信号，不需要考虑持仓、卖出、加仓等条件。
"""
import pandas as pd
import numpy as np
from strategy.base_strategy import BaseStrategy


class Strategy2560Selection(BaseStrategy):
    """
    2560战法选股策略

    核心规则：
    1. 股价向上突破25日均线（收盘价从MA25下方穿越到上方）
    2. 5日均量线向上穿过60日均量线（金叉）

    关键属性：
    - ma_period: 均线周期（默认25）
    - vol_ma_short: 短期均量线周期（默认5）
    - vol_ma_long: 长期均量线周期（默认60）
    """

    def __init__(self, params=None):
        default_params = {
            'ma_period': 25,
            'ma10_period': 10,
            'vol_ma_short': 5,
            'vol_ma_long': 60,
            'min_price_change': 0.05,
            'min_volume_ratio': 1.2,
            'strategy_weight': 70,
        }
        if params:
            default_params.update(params)
        super().__init__("2560战法选股策略", default_params)

    def quick_filter(self, df):
        if len(df) < max(self.params['ma_period'], self.params['vol_ma_long']) + 1:
            return False
        # 快速过滤：检查涨幅是否>=5%，提前过滤不满足条件的股票
        if len(df) >= 2:
            latest = df.iloc[0]
            prev = df.iloc[1]
            if prev['close'] > 0:
                price_change = (latest['close'] - prev['close']) / prev['close']
                if price_change < self.params['min_price_change']:
                    return False
        return True

    def calculate_indicators(self, df) -> pd.DataFrame:
        ma_period = self.params['ma_period']
        vol_ma_short = self.params['vol_ma_short']
        vol_ma_long = self.params['vol_ma_long']

        result = df.copy()
        
        # 确保数据按日期升序排序（最旧的在前，最新的在后）
        if len(result) > 1 and pd.notna(result['date'].iloc[0]) and pd.notna(result['date'].iloc[1]):
            # 如果第一行日期大于第二行日期，说明是降序，需要反转
            if result['date'].iloc[0] > result['date'].iloc[1]:
                result = result.sort_values('date', ascending=True).reset_index(drop=True)
        
        ma10_period = self.params['ma10_period']
        
        result['ma10'] = result['close'].rolling(window=ma10_period, min_periods=1).mean()
        result['ma25'] = result['close'].rolling(window=ma_period, min_periods=1).mean()
        result['vol_ma5'] = result['volume'].rolling(window=vol_ma_short, min_periods=1).mean()
        result['vol_ma60'] = result['volume'].rolling(window=vol_ma_long, min_periods=1).mean()

        return result

    def select_stocks(self, df, stock_name="", skip_data_check=False):
        if not skip_data_check:
            if len(df) < max(self.params['ma_period'], self.params['vol_ma_long']) + 1:
                return []

        result = self.calculate_indicators(df)

        latest = result.iloc[-1]
        prev = result.iloc[-2]

        price_break = (
            latest['close'] > latest['ma25'] and
            prev['close'] <= prev['ma25']
        )

        vol_cross = (
            latest['vol_ma5'] > latest['vol_ma60'] and
            prev['vol_ma5'] <= prev['vol_ma60']
        )

        if not (price_break and vol_cross):
            return []

        # 条件3: 收盘价在MA10之上
        price_above_ma10 = latest['close'] > latest['ma10']
        if not price_above_ma10:
            return []

        # 条件4: 涨幅≥5%
        price_change = (latest['close'] - prev['close']) / prev['close'] if prev['close'] > 0 else 0
        gain_condition = price_change >= self.params['min_price_change']
        if not gain_condition:
            return []

        # 条件5: 量能≥前5日均量的1.2倍
        volume_ratio = latest['volume'] / latest['vol_ma5'] if latest['vol_ma5'] > 0 else 0
        volume_condition = volume_ratio >= self.params['min_volume_ratio']
        if not volume_condition:
            return []

        if not self._validate_stock_name(stock_name):
            return []

        reasons = [
            f"股价突破{self.params['ma_period']}日均线",
            f"收盘价{latest['close']:.2f} > MA{self.params['ma_period']}{latest['ma25']:.2f}",
            f"5日均量线上穿{self.params['vol_ma_long']}日均量线",
            f"VOL_MA5={latest['vol_ma5']:.0f}, VOL_MA{self.params['vol_ma_long']}={latest['vol_ma60']:.0f}",
            f"收盘价在MA10之上: {latest['close']:.2f} > {latest['ma10']:.2f}",
            f"涨幅{price_change*100:.2f}% >= {self.params['min_price_change']*100:.0f}%",
            f"量能{volume_ratio:.2f}倍 >= {self.params['min_volume_ratio']}倍",
        ]

        key_date = latest['date']
        if hasattr(key_date, 'strftime'):
            key_date_str = key_date.strftime('%Y-%m-%d')
        else:
            key_date_str = str(key_date)[:10]

        today_date = latest['date']
        if hasattr(today_date, 'strftime'):
            today_date_str = today_date.strftime('%Y-%m-%d')
        else:
            today_date_str = str(today_date)[:10]

        return [{
            'date': today_date_str,
            'close': round(latest['close'], 2),
            'volume_ratio': round(latest['vol_ma5'] / max(1, latest['vol_ma60']), 2),
            'reasons': reasons,
            'key_date': key_date_str,
            'key_date_type': '信号日',
            'pattern_details': {
                'close': round(latest['close'], 2),
                'ma10': round(latest['ma10'], 2),
                'ma25': round(latest['ma25'], 2),
                'price_change': round(price_change * 100, 2),
                'volume_ratio': round(volume_ratio, 2),
                'vol_ma5': round(latest['vol_ma5'], 0),
                'vol_ma60': round(latest['vol_ma60'], 0),
            },
            'confirmation_details': {
                'confirmed': True,
                'confirmed_date': today_date_str,
            },
            'strategy_weight': self.params['strategy_weight'],
        }]
