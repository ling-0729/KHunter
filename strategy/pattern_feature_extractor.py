"""
基于知行指标的特征提取模块
复用项目已有的 technical.py 指标计算
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.technical import (
    MA, EMA, KDJ, calculate_zhixing_trend, REF, LLV, HHV
)


class PatternFeatureExtractor:
    """从股票数据中提取完美图形特征"""
    
    def __init__(self, lookback_days=25):
        self.lookback_days = lookback_days
    
    def extract(self, df: pd.DataFrame, lookback_days: int = None) -> dict:
        """
        提取完整特征向量
        df: 倒序排列的DataFrame（最新在前）
        lookback_days: 回看天数，None则使用默认值
        """
        if df.empty or len(df) < 10:
            return self._empty_features()
        
        # 使用指定的回看天数或默认值
        days = lookback_days if lookback_days is not None else self.lookback_days
        
        # 取回看期数据
        window_df = df.head(days).copy()
        
        # 按日期正序排列（便于计算趋势）
        window_df = window_df.sort_values('date').reset_index(drop=True)
        
        # 计算知行指标
        trend_df = calculate_zhixing_trend(window_df)
        window_df['short_term_trend'] = trend_df['short_term_trend']
        window_df['bull_bear_line'] = trend_df['bull_bear_line']
        
        # 计算KDJ
        kdj_df = KDJ(window_df, n=9, m1=3, m2=3)
        window_df['K'] = kdj_df['K']
        window_df['D'] = kdj_df['D']
        window_df['J'] = kdj_df['J']
        
        features = {
            "trend_structure": self._extract_trend_features(window_df),
            "kdj_state": self._extract_kdj_features(window_df),
            "volume_pattern": self._extract_volume_features(window_df),
            "price_shape": self._extract_shape_features(window_df),
        }
        
        return features
    
    def _empty_features(self) -> dict:
        """返回空特征结构"""
        return {
            "trend_structure": {},
            "kdj_state": {},
            "volume_pattern": {},
            "price_shape": {},
        }
    
    def _extract_trend_features(self, df: pd.DataFrame) -> dict:
        """提取知行趋势线特征 - 使用相对值，避免价格绝对值影响"""
        if len(df) < 5:
            return {}
        
        latest = df.iloc[-1]  # 最后一天（最新）
        
        # 1. 短期趋势 vs 多空线的相对位置（百分比偏离）
        short_bullbear_ratio = latest['short_term_trend'] / latest['bull_bear_line'] if latest['bull_bear_line'] != 0 else 1.0
        
        # 2. 斜率计算（近5日）- 使用百分比变化，标准化
        short_slope = (df['short_term_trend'].iloc[-1] / df['short_term_trend'].iloc[-5] - 1) * 100 if df['short_term_trend'].iloc[-5] != 0 else 0
        bullbear_slope = (df['bull_bear_line'].iloc[-1] / df['bull_bear_line'].iloc[-5] - 1) * 100 if df['bull_bear_line'].iloc[-5] != 0 else 0
        
        # 3. 价格相对于趋势线的偏离（百分比）- 关键：使用相对偏离而非绝对比值
        # 价格高于趋势线为正，低于为负
        price_vs_short_pct = (latest['close'] - latest['short_term_trend']) / latest['short_term_trend'] * 100 if latest['short_term_trend'] != 0 else 0
        price_vs_bullbear_pct = (latest['close'] - latest['bull_bear_line']) / latest['bull_bear_line'] * 100 if latest['bull_bear_line'] != 0 else 0
        
        # 4. 是否在碗中（短期趋势 > 价格 > 多空线）
        is_in_bowl = (latest['short_term_trend'] > latest['close'] > latest['bull_bear_line'])
        
        # 5. 趋势发散程度（短期趋势与多空线的百分比距离）
        trend_spread_pct = (latest['short_term_trend'] - latest['bull_bear_line']) / latest['bull_bear_line'] * 100 if latest['bull_bear_line'] != 0 else 0
        
        # 6. 双线乖离率（价格与两条趋势线的平均偏离）
        avg_trend = (latest['short_term_trend'] + latest['bull_bear_line']) / 2
        price_bias_pct = (latest['close'] - avg_trend) / avg_trend * 100 if avg_trend != 0 else 0
        
        return {
            "short_vs_bullbear": round(short_bullbear_ratio, 4),
            "short_slope": round(short_slope, 4),
            "bullbear_slope": round(bullbear_slope, 4),
            "price_vs_short_pct": round(price_vs_short_pct, 4),  # 改为百分比偏离
            "price_vs_bullbear_pct": round(price_vs_bullbear_pct, 4),  # 改为百分比偏离
            "is_in_bowl": is_in_bowl,
            "trend_spread_pct": round(trend_spread_pct, 4),  # 改为百分比
            "price_bias_pct": round(price_bias_pct, 4),  # 新增：双线乖离率
        }
    
    def _extract_kdj_features(self, df: pd.DataFrame) -> dict:
        """提取KDJ特征"""
        if len(df) < 2 or 'J' not in df.columns:
            return {}
        
        latest = df.iloc[-1]
        j_values = df['J'].values
        
        # J值趋势（线性回归斜率）
        if len(j_values) >= 5:
            x = np.arange(5)
            recent_j = j_values[-5:]
            j_trend = np.polyfit(x, recent_j, 1)[0] if not np.isnan(recent_j).any() else 0
        else:
            j_trend = 0
        
        # K金叉D（最新一天K上穿D）
        k_cross_d = False
        if len(df) >= 2 and not pd.isna(latest['K']) and not pd.isna(latest['D']):
            prev = df.iloc[-2]
            k_cross_d = (prev['K'] < prev['D']) and (latest['K'] > latest['D'])
        
        # J值位置
        j_val = latest['J'] if not pd.isna(latest['J']) else 50
        if j_val <= 20:
            j_position = "低位"
        elif j_val >= 80:
            j_position = "高位"
        else:
            j_position = "中位"
        
        # J值是否从低位回升
        j_rebound = j_values[-1] > j_values[-3] if len(j_values) >= 3 else False
        
        return {
            "j_value": round(float(j_val), 2),
            "j_trend": round(float(j_trend), 4),
            "j_min_lookback": round(float(df['J'].min()), 2),
            "k_cross_d": k_cross_d,
            "j_position": j_position,
            "j_rebound": j_rebound,
        }
    
    def _extract_volume_features(self, df: pd.DataFrame) -> dict:
        """提取量能特征"""
        if 'volume' not in df.columns or len(df) < 5:
            return {}
        
        volumes = df['volume'].values
        
        # 均量比（回看期 vs 回看期前）
        if len(volumes) >= 10:
            recent_avg = np.mean(volumes[-10:])
            before_avg = np.mean(volumes[-20:-10]) if len(volumes) >= 20 else recent_avg
            avg_volume_ratio = recent_avg / before_avg if before_avg > 0 else 1.0
        else:
            avg_volume_ratio = 1.0
        
        # 最大量比（单日最大放量倍数）
        vol_ratios = []
        for i in range(1, min(len(volumes), 20)):
            if volumes[i-1] > 0:
                vol_ratios.append(volumes[i] / volumes[i-1])
        max_volume_ratio = max(vol_ratios) if vol_ratios else 1.0
        
        # 缩量后放量检测
        shrink_then_expand = self._detect_shrink_expand(volumes)
        
        # 关键K线数量（放量+阳线）
        key_candles = 0
        for i in range(len(df)):
            if i > 0 and df['volume'].iloc[i] > df['volume'].iloc[i-1] * 2 and df['close'].iloc[i] > df['open'].iloc[i]:
                key_candles += 1
        
        # 量能趋势分类
        volume_trend = self._classify_volume_trend(volumes)
        
        return {
            "avg_volume_ratio": round(float(avg_volume_ratio), 2),
            "max_volume_ratio": round(float(max_volume_ratio), 2),
            "volume_trend": volume_trend,
            "key_candles_count": int(key_candles),
            "shrink_then_expand": shrink_then_expand,
        }
    
    def _extract_shape_features(self, df: pd.DataFrame) -> dict:
        """提取价格形态特征"""
        if len(df) < 5:
            return {}
        
        closes = df['close'].values
        
        # 归一化曲线（用于DTW匹配）- 缩放到0-1范围
        price_min = closes.min()
        price_max = closes.max()
        if price_max > price_min:
            normalized = (closes - price_min) / (price_max - price_min)
        else:
            normalized = np.zeros_like(closes)
        
        # 最大回撤（从最高点回落的最大幅度）
        peak = np.maximum.accumulate(closes)
        drawdown = (peak - closes) / peak
        max_drawdown = drawdown.max() * 100  # 转换为百分比
        
        # 突破力度（最后一日涨幅）
        breakout_strength = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 else 0
        
        # 波动率（收益率标准差）
        if len(closes) >= 2:
            returns = np.diff(closes) / closes[:-1]
            volatility = np.std(returns) * 100  # 百分比
        else:
            volatility = 0
        
        # 盘整天数（价格在一定范围内波动的天数）
        consolidation_days = self._count_consolidation_days(df)
        
        # 整体趋势方向（回看期首尾比较）
        overall_trend = "上升" if closes[-1] > closes[0] * 1.05 else "下降" if closes[-1] < closes[0] * 0.95 else "震荡"
        
        return {
            "consolidation_days": int(consolidation_days),
            "max_drawdown": round(float(max_drawdown), 2),
            "breakout_strength": round(float(breakout_strength), 2),
            "normalized_curve": normalized.tolist(),
            "volatility": round(float(volatility), 4),
            "overall_trend": overall_trend,
        }
    
    def _detect_shrink_expand(self, volumes: np.ndarray) -> bool:
        """检测是否缩量后放量"""
        if len(volumes) < 10:
            return False
        
        # 前一半是缩量期，后一半是放量期
        mid = len(volumes) // 2
        early_avg = np.mean(volumes[:mid])
        late_avg = np.mean(volumes[mid:])
        
        # 后期平均量比前期大，且前期有缩量（小于整体平均）
        overall_avg = np.mean(volumes)
        return late_avg > early_avg * 1.3 and early_avg < overall_avg * 0.9
    
    def _classify_volume_trend(self, volumes: np.ndarray) -> str:
        """分类量能趋势"""
        if len(volumes) < 5:
            return "unknown"
        
        # 计算线性趋势
        x = np.arange(len(volumes))
        slope = np.polyfit(x, volumes, 1)[0]
        
        avg_vol = np.mean(volumes)
        slope_pct = slope / avg_vol * 100 if avg_vol > 0 else 0
        
        if slope_pct > 5:
            return "持续放量"
        elif slope_pct < -5:
            return "持续缩量"
        elif self._detect_shrink_expand(volumes):
            return "缩量后放量"
        else:
            return "量能平稳"
    
    def _count_consolidation_days(self, df: pd.DataFrame) -> int:
        """计算盘整天数（价格在±5%范围内波动的天数）"""
        if len(df) < 5:
            return 0
        
        closes = df['close'].values
        max_price = closes.max()
        min_price = closes.min()
        
        # 如果波动范围小于10%，认为全程是盘整
        if max_price > 0 and (max_price - min_price) / max_price < 0.10:
            return len(df)
        
        # 否则找最大连续盘整天数
        consolidation_range = 0.05  # 5%波动范围
        max_days = 0
        current_days = 0
        
        for i in range(len(df) - 5):
            window = closes[i:i+5]
            window_max = window.max()
            window_min = window.min()
            
            if window_max > 0 and (window_max - window_min) / window_max < consolidation_range:
                current_days += 1
                max_days = max(max_days, current_days)
            else:
                current_days = 0
        
        return max_days
