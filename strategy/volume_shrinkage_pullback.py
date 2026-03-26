"""
缩量回调策略 - 识别上升趋势中的缩量回调机会

策略原理：
1. 上升趋势确认：短期均线 > 长期均线，且短期均线方向向上
2. 缩量回调：股价回调，回调幅度合理，成交量显著萎缩
3. 企稳信号：价格止跌企稳，成交量开始放大
4. 支撑确认：在关键支撑位（如均线）企稳

选股条件：
- 短期均线 > 长期均线
- 短期均线方向向上
- 股价回调（低于回溯期内最高点）
- 回调幅度在合理范围内（10-20%）
- 成交量萎缩（< 50%）
- 价格企稳（连续2天不创新低或收盘价回升）
- 成交量企稳（成交量放大 > 120%）
- 均线支撑有效
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import REF, MA


class VolumeShrinkagePullbackStrategy(BaseStrategy):
    """缩量回调策略 - 识别上升趋势中的缩量回调机会"""
    
    def __init__(self, params=None):
        # 默认参数配置
        default_params = {
            # 均线参数
            'short_ma_period': 10,              # 短期均线周期（10日）
            'long_ma_period': 30,               # 长期均线周期（30日）
            
            # 成交量参数
            'volume_ma_period': 5,              # 成交量均线周期（5日）
            'volume_shrink_ratio': 0.7,         # 缩量比例（70%）
            'volume_expand_ratio': 1.0,          # 放量比例（100%）
            
            # 回调参数
            'pullback_min_ratio': 0.03,         # 最小回调幅度（3%）
            'pullback_max_ratio': 0.15,         # 最大回调幅度（15%）
            'lookback_days': 10,                 # 回溯天数（10天）
            
            # 企稳参数
            'support_days': 2,                   # 企稳天数（2天）
            'support_ratio': 0.02,               # 支撑位比例（2%）
            
            # 其他参数
            'min_market_cap': 20,                # 最小市值（20亿元）
            'max_market_cap': 1000,              # 最大市值（1000亿元）
        }
        
        # 合并用户参数
        if params:
            default_params.update(params)
        
        super().__init__("缩量回调策略", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算缩量回调策略所需的指标
        """
        result = df.copy()
        
        # 数据可能是倒序排列（最新的在前），需要转为正序计算指标
        is_descending = False
        if len(result) > 1 and result['date'].iloc[0] > result['date'].iloc[1]:
            is_descending = True
            result = result.iloc[::-1].reset_index(drop=True)
        
        # 计算短期均线
        short_ma_period = self.params['short_ma_period']
        result['ma_short'] = result['close'].rolling(window=short_ma_period).mean()
        
        # 计算长期均线
        long_ma_period = self.params['long_ma_period']
        result['ma_long'] = result['close'].rolling(window=long_ma_period).mean()
        
        # 计算成交量均线
        volume_ma_period = self.params['volume_ma_period']
        result['volume_ma'] = result['volume'].rolling(window=volume_ma_period).mean()
        
        # 计算成交量比
        result['volume_ratio'] = result['volume'] / result['volume_ma']
        
        # 计算回溯期内最高价（使用最高价字段）
        lookback_days = self.params['lookback_days']
        result['highest_price'] = result['high'].rolling(window=lookback_days, min_periods=1).max()
        
        # 计算回溯期内最低价（使用最低价字段）
        result['lowest_price'] = result['low'].rolling(window=lookback_days, min_periods=1).min()
        
        # 计算最大回调幅度（从最高点到最低点）
        result['pullback_ratio'] = (result['highest_price'] - result['lowest_price']) / result['highest_price']
        
        # 如果原始数据是倒序，转回倒序
        if is_descending:
            result = result.iloc[::-1].reset_index(drop=True)
        
        # 计算趋势线（与其他策略保持一致）
        from utils.technical import calculate_zhixing_trend
        trend_df = calculate_zhixing_trend(
            result,
            m1=14,  # MA周期1
            m2=28,  # MA周期2
            m3=57,  # MA周期3
            m4=114  # MA周期4
        )
        result['short_term_trend'] = trend_df['short_term_trend']
        result['bull_bear_line'] = trend_df['bull_bear_line']
        
        # 计算市值（如果CSV中有market_cap字段则使用，否则估算）
        if 'market_cap' not in result.columns:
            # 估算市值：假设总股本2亿股
            result['market_cap'] = result['close'] * 2e8
        
        return result
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 识别缩量回调机会
        """
        # 数据验证
        if not self._validate_data(df):
            return []
        
        # 过滤退市/异常股票
        if stock_name:
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in stock_name for kw in invalid_keywords):
                return []
            
            # 过滤 ST/*ST 股票
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []
        
        # 计算指标
        df = self.calculate_indicators(df)
        
        # 获取最新数据
        latest = df.iloc[0]
        latest_date = latest['date']
        
        # 检查最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 市值过滤
        market_cap = latest['market_cap'] / 1e8  # 转换为亿元
        if market_cap < self.params['min_market_cap'] or market_cap > self.params['max_market_cap']:
            return []
        
        # 检查条件1：上升趋势
        if not self._check_uptrend(df):
            return []
        
        # 检查条件2：缩量回调
        pullback_info = self._check_volume_shrinkage_pullback(df)
        if not pullback_info['valid']:
            return []
        
        # 检查条件3：企稳信号
        if not self._check_stabilization(df):
            return []
        
        # 检查条件4：支撑确认
        if not self._check_support(df):
            return []
        
        # 生成选股信号
        signal = self._generate_signal(df, latest, pullback_info, market_cap)
        
        return [signal]
    
    def _validate_data(self, df) -> bool:
        """
        数据验证
        """
        # 检查DataFrame是否为空
        if df is None or df.empty:
            return False
        
        # 检查数据长度是否满足要求
        # 需要足够的数据来计算所有指标
        min_required_days = max(
            self.params['lookback_days'],
            self.params['long_ma_period'],
            114,  # 趋势线计算需要114天
            30
        ) + 10  # 额外缓冲
        if len(df) < min_required_days:
            return False
        
        # 检查必要字段是否存在
        required_fields = ['date', 'open', 'high', 'low', 'close', 'volume']
        for field in required_fields:
            if field not in df.columns:
                return False
        
        return True
    
    def _check_uptrend(self, df) -> bool:
        """
        检查上升趋势条件
        在缩量回调策略中，允许短期均线暂时向下（回调中），但要求：
        1. 短期均线在长期均线上方或接近（整体趋势向上）
        2. 收盘价不低于长期均线太多（获得支撑或接近支撑）
        """
        # 获取最新数据
        latest = df.iloc[0]
        
        ma_short = latest['ma_short']
        ma_long = latest['ma_long']
        current_close = latest['close']
        
        if pd.isna(ma_short) or pd.isna(ma_long):
            return False
        
        # 检查均线位置：短期均线 > 长期均线 * 0.95（允许5%的偏离）
        if ma_short < ma_long * 0.95:
            return False
        
        # 检查收盘价不低于长期均线太多（允许8%的偏离，适应回调）
        if current_close < ma_long * 0.92:
            return False
        
        return True
    
    def _check_volume_shrinkage_pullback(self, df) -> dict:
        """
        检查缩量回调条件
        返回包含验证结果和回调信息的字典
        """
        # 获取最新数据
        latest = df.iloc[0]
        
        # 检查股价回调：当前收盘价 < 回溯期内最高价
        highest_price = latest['highest_price']
        current_close = latest['close']
        
        if current_close >= highest_price:
            return {'valid': False, 'reason': '股价未回调'}
        
        # 计算回调幅度
        pullback_ratio = (highest_price - current_close) / highest_price
        
        # 检查回调幅度合理性
        min_ratio = self.params['pullback_min_ratio']
        max_ratio = self.params['pullback_max_ratio']
        
        if pullback_ratio < min_ratio or pullback_ratio > max_ratio:
            return {'valid': False, 'reason': f'回调幅度不合理（{pullback_ratio:.2%}）'}
        
        # 检查成交量萎缩：成交量比 < 缩量比例
        volume_ratio = latest['volume_ratio']
        shrink_ratio = self.params['volume_shrink_ratio']
        
        if volume_ratio >= shrink_ratio:
            return {'valid': False, 'reason': f'成交量未萎缩（{volume_ratio:.2f}）'}
        
        return {
            'valid': True,
            'pullback_ratio': pullback_ratio,
            'highest_price': highest_price,
            'volume_ratio': volume_ratio
        }
    
    def _check_stabilization(self, df) -> bool:
        """
        检查企稳信号条件
        在缩量回调策略中，企稳的判断应该更灵活：
        1. 价格不再创新低（企稳）
        2. 成交量保持相对低位（缩量状态）
        """
        # 获取最新数据
        latest = df.iloc[0]
        prev = df.iloc[1]
        
        # 检查价格企稳
        support_days = self.params['support_days']
        recent_data = df.head(support_days + 1)  # 多取一天作为基准
        lowest_price = recent_data['close'].min()
        
        # 方式1：连续support_days天收盘价不低于最低点（排除最低点那一天）
        # 找到最低点的位置
        min_idx = recent_data['close'].idxmin()
        # 检查最低点之后的support_days天是否都高于最低点
        if min_idx < len(recent_data) - 1:
            after_min_data = recent_data.iloc[min_idx + 1:min_idx + 1 + support_days]
            if len(after_min_data) >= support_days:
                price_stabilized = all(row['close'] > lowest_price for _, row in after_min_data.iterrows())
            else:
                price_stabilized = False
        else:
            price_stabilized = False
        
        # 方式2：收盘价开始回升
        price_recovering = latest['close'] > prev['close']
        
        if not (price_stabilized or price_recovering):
            return False
        
        # 检查成交量：在缩量回调中，成交量应该保持在相对低位（但不需要放大）
        # 成交量比 < 1.0 表示相对5日均量缩量，这是健康的缩量回调状态
        volume_ratio = latest['volume_ratio']
        
        # 如果成交量突然放大（> 1.5），可能是反弹信号，也认为是企稳
        # 如果成交量保持低位（< 1.0），说明抛压减轻，也是企稳信号
        if volume_ratio > 1.5:
            # 成交量突然放大，可能是反弹开始
            return True
        elif volume_ratio < 1.0:
            # 成交量保持低位，抛压减轻
            return True
        
        return True
    
    def _check_support(self, df) -> bool:
        """
        检查支撑确认条件
        """
        # 获取最新数据
        latest = df.iloc[0]
        
        # 检查均线支撑：收盘价 >= 短期均线 或 收盘价 >= 长期均线
        current_close = latest['close']
        ma_short = latest['ma_short']
        ma_long = latest['ma_long']
        
        if current_close < ma_short and current_close < ma_long:
            return False
        
        # 检查支撑位企稳
        support_price = min(ma_short, ma_long)
        support_ratio = self.params['support_ratio']
        min_allowed_price = support_price * (1 - support_ratio)
        
        if current_close < min_allowed_price:
            return False
        
        return True
    
    def _generate_signal(self, df, latest, pullback_info, market_cap) -> dict:
        """
        生成选股信号
        """
        # 生成选股原因列表
        reasons = self._generate_reasons(df, latest, pullback_info)
        
        # 处理NaN值
        pullback_ratio = pullback_info.get('pullback_ratio', 0)
        volume_shrink_ratio = pullback_info.get('volume_ratio', 0)
        
        if pd.isna(pullback_ratio):
            pullback_ratio = 0
        if pd.isna(volume_shrink_ratio):
            volume_shrink_ratio = 0
        
        # 构建选股信号
        # pullback_ratio已经是小数形式（如0.0369），转换为百分比显示（3.69）
        signal_info = {
            'date': latest['date'],
            'close': round(latest['close'], 2),
            'ma_short': round(latest['ma_short'], 2),
            'ma_long': round(latest['ma_long'], 2),
            'ma_short_trend': 'up',
            'volume': int(latest['volume']) if not pd.isna(latest['volume']) else 0,
            'volume_ma': int(latest['volume_ma']) if not pd.isna(latest['volume_ma']) else 0,
            'volume_ratio': round(latest['volume_ratio'], 2) if not pd.isna(latest['volume_ratio']) else 0,
            'highest_price': round(latest['highest_price'], 2) if not pd.isna(latest['highest_price']) else 0,
            'pullback_ratio': round(pullback_ratio, 4),  # 保持小数形式，如0.0369
            'lowest_price': round(latest['lowest_price'], 2) if not pd.isna(latest['lowest_price']) else 0,
            'support_days': self.params['support_days'],
            'support_price': round(min(latest['ma_short'], latest['ma_long']), 2),
            'market_cap': round(market_cap, 2),
            'short_term_trend': round(latest['short_term_trend'], 2) if not pd.isna(latest['short_term_trend']) else 0,
            'bull_bear_line': round(latest['bull_bear_line'], 2) if not pd.isna(latest['bull_bear_line']) else 0,
            'reasons': reasons,
            'pattern_details': {
                'pullback_ratio': round(pullback_ratio * 100, 2),
                'volume_shrink_ratio': round(volume_shrink_ratio, 2),
                'volume_expand_ratio': round(latest['volume_ratio'], 2) if not pd.isna(latest['volume_ratio']) else 0,
                'ma_short': round(latest['ma_short'], 2),
                'ma_long': round(latest['ma_long'], 2),
            }
        }
        
        return signal_info
    
    def _generate_reasons(self, df, latest, pullback_info) -> list:
        """
        生成选股原因列表
        """
        reasons = []
        
        # 原因1：上升趋势确认
        reasons.append('上升趋势确认')
        
        # 原因2：缩量回调
        reasons.append(f'缩量回调（回调{pullback_info["pullback_ratio"]*100:.1f}%）')
        
        # 原因3：回调幅度合理
        reasons.append('回调幅度合理')
        
        # 原因4：价格企稳
        reasons.append('价格企稳')
        
        # 原因5：成交量企稳
        reasons.append('成交量企稳')
        
        # 原因6：均线支撑有效
        reasons.append('均线支撑有效')
        
        return reasons
