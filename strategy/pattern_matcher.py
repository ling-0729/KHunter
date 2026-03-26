"""
相似度计算引擎 - 支持多维度加权匹配
使用DTW进行形态相似度计算
"""
import numpy as np
from scipy.spatial.distance import euclidean


try:
    from fastdtw import fastdtw
    HAS_FASTDTW = True
except ImportError:
    HAS_FASTDTW = False
    print("⚠️ fastdtw 未安装，将使用简化版DTW")


class PatternMatcher:
    """完美图形匹配器 - 支持从配置文件读取参数"""
    
    def __init__(self, weights=None, tolerances=None):
        from strategy.pattern_config import SIMILARITY_WEIGHTS, MATCH_TOLERANCES
        self.weights = weights or SIMILARITY_WEIGHTS
        self.tolerances = tolerances or MATCH_TOLERANCES
    
    def match(self, candidate_features: dict, case_features: dict) -> dict:
        """
        计算候选股与案例的相似度
        返回0-1之间的分数
        """
        if not candidate_features or not case_features:
            return {"total_score": 0.0, "breakdown": {}}
        
        scores = {}
        
        # 1. 知行趋势线结构相似度
        if candidate_features.get("trend_structure") and case_features.get("trend_structure"):
            scores["trend_structure"] = self._calc_trend_similarity(
                candidate_features["trend_structure"],
                case_features["trend_structure"]
            )
        else:
            scores["trend_structure"] = 0.5
        
        # 2. KDJ状态相似度
        if candidate_features.get("kdj_state") and case_features.get("kdj_state"):
            scores["kdj_state"] = self._calc_kdj_similarity(
                candidate_features["kdj_state"],
                case_features["kdj_state"]
            )
        else:
            scores["kdj_state"] = 0.5
        
        # 3. 量能模式相似度
        if candidate_features.get("volume_pattern") and case_features.get("volume_pattern"):
            scores["volume_pattern"] = self._calc_volume_similarity(
                candidate_features["volume_pattern"],
                case_features["volume_pattern"]
            )
        else:
            scores["volume_pattern"] = 0.5
        
        # 4. 价格形态相似度（DTW）
        if candidate_features.get("price_shape") and case_features.get("price_shape"):
            scores["price_shape"] = self._calc_shape_similarity(
                candidate_features["price_shape"],
                case_features["price_shape"]
            )
        else:
            scores["price_shape"] = 0.5
        
        # 加权总分
        total_score = sum(
            scores[k] * self.weights.get(k, 0.25) for k in scores
        )
        
        return {
            "total_score": round(total_score * 100, 2),  # 转换为百分制
            "breakdown": {k: round(v * 100, 2) for k, v in scores.items()},
        }
    
    def _calc_trend_similarity(self, cand: dict, case: dict) -> float:
        """知行趋势线相似度 - 基于相对百分比偏离"""
        similarities = []
        
        # 从配置读取容差参数
        trend_ratio_tol = self.tolerances.get("trend_ratio", 0.10)
        price_bias_tol = self.tolerances.get("price_bias", 10)
        trend_spread_tol = self.tolerances.get("trend_spread", 10)
        
        # 1. short_vs_bullbear 比值相似
        if "short_vs_bullbear" in cand and "short_vs_bullbear" in case:
            ratio_diff = abs(cand["short_vs_bullbear"] - case["short_vs_bullbear"])
            sim = max(0, 1 - ratio_diff / trend_ratio_tol)
            similarities.append(sim)
        
        # 2. 斜率方向一致性（最重要）
        if "short_slope" in cand and "short_slope" in case:
            short_slope_same = (cand["short_slope"] > 0) == (case["short_slope"] > 0)
            if short_slope_same:
                slope_diff = abs(cand["short_slope"] - case["short_slope"])
                sim = max(0.7, 1 - slope_diff / 10)
            else:
                sim = max(0, 0.3 - abs(cand["short_slope"] - case["short_slope"]) / 20)
            similarities.append(sim)
        
        # 3. 是否在碗中（形态位置）
        if "is_in_bowl" in cand and "is_in_bowl" in case:
            if cand["is_in_bowl"] == case["is_in_bowl"]:
                similarities.append(1.0)
            else:
                similarities.append(0.2)
        
        # 4. 价格相对于短期趋势的偏离（百分比）
        cand_price_bias = cand.get("price_vs_short_pct", cand.get("price_vs_short", 0) * 100 - 100)
        case_price_bias = case.get("price_vs_short_pct", case.get("price_vs_short", 0) * 100 - 100)
        price_bias_diff = abs(cand_price_bias - case_price_bias)
        sim = max(0, 1 - price_bias_diff / price_bias_tol)
        similarities.append(sim)
        
        # 5. 趋势发散程度相似（百分比）
        cand_spread = cand.get("trend_spread_pct", cand.get("trend_spread", 0))
        case_spread = case.get("trend_spread_pct", case.get("trend_spread", 0))
        spread_diff = abs(cand_spread - case_spread)
        sim = max(0, 1 - spread_diff / trend_spread_tol)
        similarities.append(sim)
        
        # 6. 双线乖离率相似
        if "price_bias_pct" in cand and "price_bias_pct" in case:
            bias_diff = abs(cand["price_bias_pct"] - case["price_bias_pct"])
            sim = max(0, 1 - bias_diff / price_bias_tol)
            similarities.append(sim)
        
        return np.mean(similarities) if similarities else 0.5
    
    def _calc_kdj_similarity(self, cand: dict, case: dict) -> float:
        """KDJ状态相似度"""
        similarities = []
        
        # 从配置读取J值容差
        j_value_tol = self.tolerances.get("j_value", 30)
        
        # J值位置一致性（低位vs中位vs高位）
        if "j_position" in cand and "j_position" in case:
            if cand["j_position"] == case["j_position"]:
                similarities.append(1.0)
            elif (cand["j_position"] == "低位" and case["j_position"] == "低位") or \
                 (cand["j_position"] == "中位" and case["j_position"] == "中位"):
                similarities.append(0.8)
            else:
                similarities.append(0.4)
        
        # J值具体数值相似（使用配置的容差）
        if "j_value" in cand and "j_value" in case:
            j_diff = abs(cand["j_value"] - case["j_value"])
            sim = max(0, 1 - j_diff / j_value_tol)
            similarities.append(sim)
        
        # 金叉状态一致性
        if "k_cross_d" in cand and "k_cross_d" in case:
            if cand["k_cross_d"] == case["k_cross_d"]:
                similarities.append(1.0)
            else:
                similarities.append(0.6)
        
        # J值趋势方向
        if "j_rebound" in cand and "j_rebound" in case:
            if cand["j_rebound"] == case["j_rebound"]:
                similarities.append(1.0)
            else:
                similarities.append(0.7)
        
        return np.mean(similarities) if similarities else 0.5
    
    def _calc_volume_similarity(self, cand: dict, case: dict) -> float:
        """量能模式相似度"""
        similarities = []
        
        # 均量比相似
        if "avg_volume_ratio" in cand and "avg_volume_ratio" in case:
            ratio_diff = abs(cand["avg_volume_ratio"] - case["avg_volume_ratio"])
            sim = max(0, 1 - ratio_diff / 1.5)
            similarities.append(sim)
        
        # 缩量后放量模式一致性
        if "shrink_then_expand" in cand and "shrink_then_expand" in case:
            if cand["shrink_then_expand"] == case["shrink_then_expand"]:
                similarities.append(1.0)
            else:
                similarities.append(0.5)
        
        # 关键K线数量接近度
        if "key_candles_count" in cand and "key_candles_count" in case:
            count_diff = abs(cand["key_candles_count"] - case["key_candles_count"])
            sim = max(0, 1 - count_diff / 3)
            similarities.append(sim)
        
        # 量能趋势分类一致性
        if "volume_trend" in cand and "volume_trend" in case:
            if cand["volume_trend"] == case["volume_trend"]:
                similarities.append(1.0)
            else:
                similarities.append(0.6)
        
        # 最大量比相似
        if "max_volume_ratio" in cand and "max_volume_ratio" in case:
            max_vol_diff = abs(cand["max_volume_ratio"] - case["max_volume_ratio"])
            sim = max(0, 1 - max_vol_diff / 3)
            similarities.append(sim)
        
        return np.mean(similarities) if similarities else 0.5
    
    def _calc_shape_similarity(self, cand: dict, case: dict) -> float:
        """价格形态相似度 - 使用DTW"""
        similarities = []
        
        # 从配置读取回撤容差
        drawdown_tol = self.tolerances.get("drawdown", 15)
        
        # 使用DTW计算曲线相似度
        if "normalized_curve" in cand and "normalized_curve" in case:
            cand_curve = np.array(cand["normalized_curve"])
            case_curve = np.array(case["normalized_curve"])
            
            if len(cand_curve) > 0 and len(case_curve) > 0:
                if HAS_FASTDTW:
                    try:
                        distance, _ = fastdtw(cand_curve, case_curve, dist=euclidean)
                        max_dist = max(len(cand_curve), len(case_curve))
                        curve_sim = max(0, 1 - distance / max_dist) if max_dist > 0 else 0
                    except:
                        curve_sim = self._simple_dtw(cand_curve, case_curve)
                else:
                    curve_sim = self._simple_dtw(cand_curve, case_curve)
                
                similarities.append(curve_sim)
        
        # 回撤幅度相似（使用配置容差）
        if "max_drawdown" in cand and "max_drawdown" in case:
            drawdown_diff = abs(cand["max_drawdown"] - case["max_drawdown"])
            sim = max(0, 1 - drawdown_diff / drawdown_tol)
            similarities.append(sim)
        
        # 突破力度相似
        if "breakout_strength" in cand and "breakout_strength" in case:
            breakout_diff = abs(cand["breakout_strength"] - case["breakout_strength"])
            sim = max(0, 1 - breakout_diff / 5)
            similarities.append(sim)
        
        # 整体趋势方向一致性
        if "overall_trend" in cand and "overall_trend" in case:
            if cand["overall_trend"] == case["overall_trend"]:
                similarities.append(1.0)
            else:
                similarities.append(0.5)
        
        # 盘整天数接近度
        if "consolidation_days" in cand and "consolidation_days" in case:
            days_diff = abs(cand["consolidation_days"] - case["consolidation_days"])
            sim = max(0, 1 - days_diff / 10)
            similarities.append(sim)
        
        return np.mean(similarities) if similarities else 0.5
    
    def _simple_dtw(self, seq1: np.ndarray, seq2: np.ndarray) -> float:
        """简化版DTW（当fastdtw不可用时使用）"""
        n, m = len(seq1), len(seq2)
        if n == 0 or m == 0:
            return 0.0
        
        # 如果长度不同，进行线性插值到相同长度
        if n != m:
            target_len = max(n, m)
            if n < target_len:
                seq1 = np.interp(
                    np.linspace(0, n-1, target_len),
                    np.arange(n),
                    seq1
                )
            if m < target_len:
                seq2 = np.interp(
                    np.linspace(0, m-1, target_len),
                    np.arange(m),
                    seq2
                )
        
        # 计算欧氏距离
        distance = np.sqrt(np.sum((seq1 - seq2) ** 2))
        max_dist = np.sqrt(len(seq1))
        
        similarity = max(0, 1 - distance / max_dist) if max_dist > 0 else 0
        return similarity
