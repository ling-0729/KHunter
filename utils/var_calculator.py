"""
VaR计算核心模块 - 增强版VaR计算
支持多种计算方法：历史分位数法、EWMA法、混合法
"""
import numpy as np
import logging
from typing import Optional, Tuple, Literal

# 配置日志
logger = logging.getLogger(__name__)


class EnhancedVaRCalculator:
    """增强版VaR计算器 - 支持多种计算方法"""
    
    def __init__(self, method: Literal['historical', 'ewma', 'hybrid'] = 'hybrid', 
                 lambda_ewma: float = 0.94, lookback_days: int = 500):
        """
        初始化增强版VaR计算器
        
        参数：
            method: 计算方法
                - 'historical': 传统历史分位数法（对近期数据反应较慢）
                - 'ewma': 指数加权移动平均法（对近期数据反应较快）
                - 'hybrid': 混合方法（结合历史分位数和EWMA，推荐）
            lambda_ewma: EWMA衰减因子，默认0.94（越小对近期数据越敏感）
            lookback_days: 数据窗口大小，默认500天
        """
        self.method = method
        self.lambda_ewma = lambda_ewma
        self.lookback_days = lookback_days
        
        logger.info(f"EnhancedVaRCalculator 初始化完成，方法: {method}, λ={lambda_ewma}, 窗口={lookback_days}天")
    
    def calculate_var(self, returns: np.ndarray, 
                     confidence: float = 0.99) -> Optional[float]:
        """
        计算VaR（根据配置的方法）
        
        参数：
            returns: 收益率序列（负数表示亏损）
            confidence: 置信水平，默认99%
            
        返回：
            VaR值（负数表示亏损），数据不足返回None
        """
        # 数据质量检查
        if returns is None or len(returns) == 0:
            logger.warning("计算VaR失败: 数据为空")
            return None
        
        if len(returns) < 100:
            logger.warning(f"计算VaR失败: 数据点不足（{len(returns)} < 100）")
            return None
        
        if confidence <= 0 or confidence >= 1:
            logger.error(f"计算VaR失败: 置信水平无效（{confidence}）")
            return None
        
        try:
            if self.method == 'historical':
                var = self._calculate_historical_var(returns, confidence)
            elif self.method == 'ewma':
                var = self._calculate_ewma_var(returns, confidence)
            elif self.method == 'hybrid':
                var = self._calculate_hybrid_var(returns, confidence)
            else:
                var = self._calculate_historical_var(returns, confidence)
            
            logger.info(f"计算VaR成功: 方法={self.method}, 置信水平={confidence:.0%}, VaR={var:.4f}")
            return float(var)
            
        except Exception as e:
            logger.error(f"计算VaR失败: {str(e)}")
            return None
    
    def _calculate_historical_var(self, returns: np.ndarray, confidence: float) -> float:
        """
        传统历史分位数法计算VaR
        """
        alpha = 1 - confidence
        var = np.percentile(returns, alpha * 100)
        return float(var)
    
    def _calculate_ewma_var(self, returns: np.ndarray, confidence: float) -> float:
        """
        EWMA（指数加权移动平均）方法计算VaR
        对近期数据赋予更高权重，能更快反映市场变化
        """
        n = len(returns)
        
        # 计算权重：近期数据权重更高
        weights = np.array([self.lambda_ewma ** (n - i - 1) for i in range(n)])
        weights = weights / weights.sum()  # 归一化
        
        # 排序收益率和权重
        sorted_indices = np.argsort(returns)
        sorted_returns = returns[sorted_indices]
        sorted_weights = weights[sorted_indices]
        
        # 找到累积权重达到alpha的位置
        alpha = 1 - confidence
        cum_weights = np.cumsum(sorted_weights)
        
        # 找到第一个累积权重 >= alpha 的位置
        var_index = np.argmax(cum_weights >= alpha)
        
        if var_index == 0:
            # 如果第一个就超过，取第一个
            var = sorted_returns[0]
        else:
            # 线性插值
            prev_weight = cum_weights[var_index - 1]
            weight_diff = cum_weights[var_index] - prev_weight
            t = (alpha - prev_weight) / weight_diff
            var = sorted_returns[var_index - 1] + t * (sorted_returns[var_index] - sorted_returns[var_index - 1])
        
        return float(var)
    
    def _calculate_hybrid_var(self, returns: np.ndarray, confidence: float) -> float:
        """
        混合方法：历史分位数法 + EWMA法
        取两者的加权平均，平衡稳定性和敏感性
        """
        # 计算历史VaR
        var_hist = self._calculate_historical_var(returns, confidence)
        
        # 计算EWMA VaR
        var_ewma = self._calculate_ewma_var(returns, confidence)
        
        # 混合权重：历史VaR占40%，EWMA VaR占60%
        # 这样既保持一定稳定性，又能快速反映近期变化
        var_hybrid = 0.4 * var_hist + 0.6 * var_ewma
        
        return float(var_hybrid)
    
    def calculate_multi_day_var(self, var_1day: float, days: int) -> Optional[float]:
        """
        使用平方根法则计算多日VaR
        
        参数：
            var_1day: 单日VaR
            days: 天数
            
        返回：
            多日VaR，失败返回None
        """
        if var_1day is None:
            logger.warning("计算多日VaR失败: 单日VaR为空")
            return None
        
        if days <= 0:
            logger.error(f"计算多日VaR失败: 天数无效（{days}）")
            return None
        
        try:
            # 平方根法则: VaR_n = VaR_1 * sqrt(n)
            var_nday = var_1day * np.sqrt(days)
            
            logger.info(f"计算多日VaR成功: {days}日VaR={var_nday:.4f}")
            return float(var_nday)
            
        except Exception as e:
            logger.error(f"计算多日VaR失败: {str(e)}")
            return None
    
    def calculate_var_and_es(self, returns: np.ndarray,
                            confidence: float = 0.99) -> Tuple[Optional[float], Optional[float]]:
        """
        计算VaR和ES（期望损失）
        
        参数：
            returns: 收益率序列（负数表示亏损）
            confidence: 置信水平，默认99%
            
        返回：
            (VaR, ES) 元组，失败返回 (None, None)
        """
        # 计算VaR
        var = self.calculate_var(returns, confidence)
        
        if var is None:
            return None, None
        
        # 计算ES（期望损失）：超过VaR的平均损失
        try:
            tail_losses = returns[returns < var]
            
            if len(tail_losses) == 0:
                logger.warning("计算ES失败: 尾部数据为空")
                return var, None
            
            es = np.mean(tail_losses)
            
            logger.info(f"计算ES成功: 置信水平={confidence:.0%}, ES={es:.4f}")
            return var, float(es)
            
        except Exception as e:
            logger.error(f"计算ES失败: {str(e)}")
            return var, None
    
    def validate_returns(self, returns: np.ndarray) -> Tuple[bool, str]:
        """
        验证收益率数据质量
        
        参数：
            returns: 收益率序列
            
        返回：
            (是否有效, 错误信息) 元组
        """
        if returns is None:
            return False, "收益率数据为空"
        
        if len(returns) == 0:
            return False, "收益率数据长度为0"
        
        if len(returns) < 100:
            return False, f"收益率数据点不足（{len(returns)} < 100）"
        
        if np.any(np.isnan(returns)):
            return False, "收益率数据包含NaN"
        
        if np.any(np.isinf(returns)):
            return False, "收益率数据包含Inf"
        
        if np.any(returns < -0.2):
            return False, "收益率数据包含异常小值（<-20%）"
        
        if np.any(returns > 0.2):
            return False, "收益率数据包含异常大值（>20%）"
        
        return True, ""
    
    def get_var_statistics(self, returns: np.ndarray) -> dict:
        """
        获取收益率统计信息
        
        参数：
            returns: 收益率序列
            
        返回：
            统计信息字典
        """
        if returns is None or len(returns) == 0:
            return {}
        
        try:
            stats = {
                'count': len(returns),
                'mean': float(np.mean(returns)),
                'std': float(np.std(returns)),
                'min': float(np.min(returns)),
                'max': float(np.max(returns)),
                'median': float(np.median(returns)),
                'percentile_1': float(np.percentile(returns, 1)),
                'percentile_5': float(np.percentile(returns, 5)),
                'percentile_10': float(np.percentile(returns, 10)),
                'percentile_90': float(np.percentile(returns, 90)),
                'percentile_95': float(np.percentile(returns, 95)),
                'percentile_99': float(np.percentile(returns, 99)),
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {str(e)}")
            return {}


# 测试代码
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    np.random.seed(42)
    test_returns = np.random.normal(loc=0.0005, scale=0.02, size=500)
    
    # 测试不同方法
    methods = ['historical', 'ewma', 'hybrid']
    for method in methods:
        calculator = EnhancedVaRCalculator(method=method)
        var = calculator.calculate_var(test_returns, confidence=0.99)
        print(f"\n方法: {method}")
        print(f"  99% VaR: {var:.4f} ({var*100:.2f}%)")