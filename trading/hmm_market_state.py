# -*- coding: utf-8 -*-
"""
HMM市场状态识别模块

基于隐马尔可夫模型（HMM）识别市场状态，为策略选择和仓位管理提供动态依据。

功能：
- 识别市场当前所处的状态（牛市趋势、牛市震荡、熊市震荡、熊市趋势）
- 基于可观测的市场指标（收益率、成交量等）反推隐藏的市场状态
- 为KHunter提供市场状态的实时判断

作者：KHunter
日期：2026-05-12
"""

import os
import pickle
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
from hmmlearn import hmm

logger = logging.getLogger(__name__)


class MarketState(Enum):
    """市场状态枚举"""
    BULL_TREND = 0      # 牛市趋势（趋势上涨）
    BULL_OSCILLATION = 1 # 牛市震荡（震荡上涨）
    BEAR_OSCILLATION = 2 # 熊市震荡（震荡下跌）
    BEAR_TREND = 3      # 熊市趋势（趋势下跌）


class HMMConfig:
    """HMM配置类"""

    DEFAULT_CONFIG = {
        'n_states': 4,
        'covariance_type': 'full',
        'n_iter': 1000,
        'lookback_days': 500,
        'retrain_interval': 30,
        'min_samples': 200,
        'features': [
            {'name': 'return', 'weight': 1.0},
            {'name': 'volume_zscore', 'weight': 0.5},
            {'name': 'volatility', 'weight': 0.3},
            {'name': 'momentum', 'weight': 0.2}
        ],
        'state_mapping': {
            0: '趋势上涨',
            1: '震荡上涨',
            2: '震荡下跌',
            3: '趋势下跌'
        }
    }

    def __init__(self, config_path: str = None):
        """初始化HMM配置"""
        if config_path and os.path.exists(config_path):
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
        else:
            self.config = self.DEFAULT_CONFIG

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config.get(key, default)

    def get_n_states(self) -> int:
        """获取隐藏状态数量"""
        return self.config.get('n_states', 4)

    def get_covariance_type(self) -> str:
        """获取协方差类型"""
        return self.config.get('covariance_type', 'full')

    def get_n_iter(self) -> int:
        """获取训练迭代次数"""
        return self.config.get('n_iter', 1000)

    def get_lookback_days(self) -> int:
        """获取回看天数"""
        return self.config.get('lookback_days', 500)

    def get_retrain_interval(self) -> int:
        """获取重新训练间隔"""
        return self.config.get('retrain_interval', 30)

    def get_min_samples(self) -> int:
        """获取最小训练样本数"""
        return self.config.get('min_samples', 200)

    def get_feature_config(self) -> List[Dict]:
        """获取特征配置"""
        return self.config.get('features', [])

    def get_state_name(self, state_id: int) -> str:
        """获取状态名称"""
        mapping = self.config.get('state_mapping', {})
        return mapping.get(state_id, f'未知状态{state_id}')


class HMMFeatureCalculator:
    """HMM特征计算器"""

    @staticmethod
    def calculate_returns(prices: pd.Series) -> pd.Series:
        """计算日收益率"""
        return prices.pct_change().fillna(0)

    @staticmethod
    def calculate_volume_zscore(volumes: pd.Series, window: int = 20) -> pd.Series:
        """计算成交量Z分数"""
        mean = volumes.rolling(window=window, min_periods=1).mean()
        std = volumes.rolling(window=window, min_periods=1).std()
        std = std.replace(0, 1)
        return (volumes - mean) / std

    @staticmethod
    def calculate_volatility(returns: pd.Series, window: int = 20) -> pd.Series:
        """计算波动率（收益率标准差）"""
        return returns.rolling(window=window, min_periods=1).std().fillna(0)

    @staticmethod
    def calculate_momentum(prices: pd.Series, window: int = 20) -> pd.Series:
        """计算动量（累计收益率）"""
        return prices.pct_change(periods=window).fillna(0)

    def calculate_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有特征

        Args:
            df: 包含 'close' 和 'volume' 列的DataFrame

        Returns:
            包含所有特征的DataFrame
        """
        features = pd.DataFrame(index=df.index)

        if 'close' in df.columns:
            prices = df['close']
            features['return'] = self.calculate_returns(prices)
            features['momentum'] = self.calculate_momentum(prices)

        if 'volume' in df.columns:
            volumes = df['volume']
            features['volume_zscore'] = self.calculate_volume_zscore(volumes)

        if 'close' in df.columns:
            prices = df['close']
            returns = self.calculate_returns(prices)
            features['volatility'] = self.calculate_volatility(returns)

        return features.fillna(0)


class HMMMarketStateDetector:
    """HMM市场状态识别器"""

    def __init__(self, config_path: str = None, model_dir: str = None):
        """初始化HMM市场状态识别器

        Args:
            config_path: 配置文件路径
            model_dir: 模型存储目录
        """
        self.config = HMMConfig(config_path)
        self.model_dir = model_dir or 'data/hmm_model'
        self.feature_calculator = HMMFeatureCalculator()
        self.model = None
        self.last_train_date = None
        self.is_trained = False

        os.makedirs(self.model_dir, exist_ok=True)

    def _prepare_features(self, data: pd.DataFrame) -> np.ndarray:
        """准备特征矩阵

        Args:
            data: 包含市场数据的DataFrame

        Returns:
            特征矩阵
        """
        features = self.feature_calculator.calculate_features(data)
        feature_config = self.config.get_feature_config()

        feature_list = []
        for fc in feature_config:
            feature_name = fc['name']
            weight = fc.get('weight', 1.0)
            if feature_name in features.columns:
                feature_values = features[feature_name].values * weight
                feature_list.append(feature_values)

        if not feature_list:
            logger.warning("没有有效的特征数据，使用默认特征")
            return np.zeros((len(data), 2))

        features_matrix = np.column_stack(feature_list)
        return features_matrix

    def train(self, data: pd.DataFrame, dates: List[str] = None) -> bool:
        """训练HMM模型

        Args:
            data: 包含市场数据的DataFrame（需要 'close' 和 'volume' 列）
            dates: 对应的日期列表

        Returns:
            训练是否成功
        """
        try:
            features = self._prepare_features(data)

            if len(features) < self.config.get_min_samples():
                logger.warning(
                    f"样本数量不足: {len(features)} < {self.config.get_min_samples()}，使用所有可用样本"
                )

            features = features[-self.config.get_lookback_days():]

            # 尝试训练模型，处理协方差矩阵问题
            # 优先级: 先尝试配置的协方差类型，再尝试其他类型
            original_cov_type = self.config.get_covariance_type()
            covariance_types = [original_cov_type] + \
                [ct for ct in ['full', 'diag', 'tied', 'spherical'] if ct != original_cov_type]
            
            for cov_type in covariance_types:
                try:
                    self.model = hmm.GaussianHMM(
                        n_components=self.config.get_n_states(),
                        covariance_type=cov_type,
                        n_iter=self.config.get_n_iter(),
                        random_state=42
                    )

                    self.model.fit(features)
                    self.is_trained = True
                    self.last_train_date = datetime.now().strftime('%Y-%m-%d')

                    # 根据状态均值重新映射状态标签
                    self._remap_states_by_mean()

                    logger.info(
                        f"HMM模型训练完成: 状态数={self.config.get_n_states()}, "
                        f"协方差类型={cov_type}, 样本数={len(features)}, 训练日期={self.last_train_date}"
                    )

                    self._log_model_info()
                    return True

                except ValueError as e:
                    if 'covars' in str(e).lower() and 'positive-definite' in str(e).lower():
                        logger.warning(f"协方差类型 {cov_type} 训练失败，尝试其他类型: {str(e)}")
                        continue
                    else:
                        raise

            logger.error("所有协方差类型都无法训练成功")
            return False

        except Exception as e:
            logger.error(f"HMM模型训练失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            self.is_trained = False
            return False

    def _remap_states_by_mean(self):
        """
        根据状态均值创建状态重映射表
        
        HMM训练后的状态标签是随机分配的，需要根据特征均值（收益率）重新映射：
        - 状态0: 趋势上涨（收益率最高）
        - 状态1: 震荡上涨（收益率次高）
        - 状态2: 震荡下跌（收益率次低）
        - 状态3: 趋势下跌（收益率最低）
        """
        if self.model is None:
            self.state_remap = None
            return

        try:
            # 获取每个状态的收益率均值（第一个特征）
            means = self.model.means_
            n_states = len(means)
            
            # 创建状态索引和收益率均值的列表
            state_returns = [(i, means[i][0]) for i in range(n_states)]
            
            # 按收益率均值降序排序
            state_returns.sort(key=lambda x: -x[1])
            
            # 创建新的状态映射
            # 原始状态 -> 重映射后的状态
            self.state_remap = {original: new for new, (original, _) in enumerate(state_returns)}
            
            logger.info(f"状态重映射表: {self.state_remap}")
            
            # 打印重映射后的状态均值
            logger.info("重映射后的状态均值(收益率特征):")
            for new_state in range(n_states):
                original_state = None
                for orig, new in self.state_remap.items():
                    if new == new_state:
                        original_state = orig
                        break
                if original_state is not None:
                    state_name = self.get_state_name(new_state)
                    logger.info(f"  状态{new_state} ({state_name}): 收益率={means[original_state][0]:.4f}")
            
        except Exception as e:
            logger.warning(f"创建状态重映射失败: {str(e)}")
            self.state_remap = None
    
    def _remap_state_id(self, original_state: int) -> int:
        """
        将原始状态ID重映射到正确的状态ID
        
        Args:
            original_state: 模型预测的原始状态ID
            
        Returns:
            重映射后的状态ID
        """
        if self.state_remap is not None and original_state in self.state_remap:
            return self.state_remap[original_state]
        return original_state
    
    def _remap_state_probs(self, original_probs: np.ndarray) -> np.ndarray:
        """
        将原始状态概率重映射到正确的顺序
        
        Args:
            original_probs: 原始状态概率数组
            
        Returns:
            重映射后的状态概率数组
        """
        if self.state_remap is None:
            return original_probs
        
        new_probs = np.zeros_like(original_probs)
        for original, new in self.state_remap.items():
            new_probs[new] = original_probs[original]
        return new_probs

    def _log_model_info(self):
        """记录模型信息"""
        if self.model is None:
            return

        try:
            logger.info(f"HMM模型均值:\n{self.model.means_}")
            logger.info(f"HMM模型协方差矩阵形状: {self.model.covars_.shape}")
            logger.info(f"HMM模型起始概率: {self.model.startprob_}")
            logger.info(f"HMM模型转移概率矩阵:\n{self.model.transmat_}")
        except Exception as e:
            logger.warning(f"记录模型信息失败: {str(e)}")

    def predict(self, data: pd.DataFrame) -> Tuple[int, np.ndarray]:
        """预测当前市场状态

        Args:
            data: 包含市场数据的DataFrame（最新数据在最后）

        Returns:
            (state_id, state_probabilities)
        """
        if not self.is_trained or self.model is None:
            logger.warning("模型未训练，使用默认状态")
            return 0, np.array([0.25, 0.25, 0.25, 0.25])

        try:
            features = self._prepare_features(data)

            if len(features) == 0:
                logger.warning("特征数据为空，使用默认状态")
                return 0, np.array([0.25, 0.25, 0.25, 0.25])

            last_features = features[-1:]

            original_state_id = self.model.predict(last_features)[0]
            original_probs = self.model.predict_proba(last_features)[0]

            # 状态重映射
            state_id = self._remap_state_id(original_state_id)
            state_probs = self._remap_state_probs(original_probs)

            logger.info(
                f"市场状态预测: state={state_id}({self.get_state_name(state_id)}), "
                f"概率分布={state_probs}, 置信度={state_probs[state_id]:.2%}"
            )

            return int(state_id), state_probs

        except Exception as e:
            logger.error(f"市场状态预测失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return 0, np.array([0.25, 0.25, 0.25, 0.25])

    def predict_batch(self, data: pd.DataFrame) -> np.ndarray:
        """批量预测市场状态（用于历史分析）

        Args:
            data: 包含市场数据的DataFrame

        Returns:
            所有时间点的状态序列
        """
        if not self.is_trained or self.model is None:
            logger.warning("模型未训练，返回默认状态序列")
            return np.zeros(len(data), dtype=int)

        try:
            features = self._prepare_features(data)

            if len(features) == 0:
                return np.zeros(len(data), dtype=int)

            original_states = self.model.predict(features)
            
            # 状态重映射
            if self.state_remap is not None:
                hidden_states = np.array([self.state_remap[s] for s in original_states])
            else:
                hidden_states = original_states
                
            return hidden_states

        except Exception as e:
            logger.error(f"批量预测失败: {str(e)}")
            return np.zeros(len(data), dtype=int)

    def get_state_name(self, state_id: int) -> str:
        """获取状态名称"""
        return self.config.get_state_name(state_id)

    def get_state_confidence(self, state_probabilities: np.ndarray) -> float:
        """获取状态置信度（取最大概率）

        Args:
            state_probabilities: 状态概率分布

        Returns:
            置信度（0-1）
        """
        if state_probabilities is None or len(state_probabilities) == 0:
            return 0.0
        return float(np.max(state_probabilities))

    def get_state_info(self, state_id: int, state_probabilities: np.ndarray) -> Dict:
        """获取状态的详细信息

        Args:
            state_id: 状态ID
            state_probabilities: 状态概率分布

        Returns:
            状态详细信息字典
        """
        return {
            'state_id': state_id,
            'state_name': self.get_state_name(state_id),
            'confidence': self.get_state_confidence(state_probabilities),
            'probabilities': {
                self.get_state_name(i): float(prob)
                for i, prob in enumerate(state_probabilities)
            }
        }

    def should_retrain(self) -> bool:
        """检查是否需要重新训练

        Returns:
            是否需要重新训练
        """
        if not self.is_trained:
            return True

        if self.last_train_date is None:
            return True

        try:
            last_date = datetime.strptime(self.last_train_date, '%Y-%m-%d')
            days_since_train = (datetime.now() - last_date).days
            return days_since_train >= self.config.get_retrain_interval()
        except:
            return True

    def save_model(self, path: str = None) -> bool:
        """保存模型

        Args:
            path: 保存路径

        Returns:
            保存是否成功
        """
        if not self.is_trained or self.model is None:
            logger.warning("模型未训练，无法保存")
            return False

        if path is None:
            path = os.path.join(self.model_dir, 'hmm_model_latest.pkl')

        try:
            model_data = {
                'model': self.model,
                'config': self.config.config,
                'last_train_date': self.last_train_date,
                'is_trained': self.is_trained
            }

            with open(path, 'wb') as f:
                pickle.dump(model_data, f)

            logger.info(f"HMM模型已保存: {path}")
            return True

        except Exception as e:
            logger.error(f"保存模型失败: {str(e)}")
            return False

    def load_model(self, path: str = None) -> bool:
        """加载模型

        Args:
            path: 加载路径

        Returns:
            加载是否成功
        """
        if path is None:
            path = os.path.join(self.model_dir, 'hmm_model_latest.pkl')

        if not os.path.exists(path):
            logger.warning(f"模型文件不存在: {path}")
            return False

        try:
            with open(path, 'rb') as f:
                model_data = pickle.load(f)

            self.model = model_data.get('model')
            self.last_train_date = model_data.get('last_train_date')
            self.is_trained = model_data.get('is_trained', False)

            logger.info(f"HMM模型已加载: {path}, 训练日期: {self.last_train_date}")
            return True

        except Exception as e:
            logger.error(f"加载模型失败: {str(e)}")
            return False

    def get_model_summary(self) -> Dict:
        """获取模型摘要信息

        Returns:
            模型摘要字典
        """
        summary = {
            'is_trained': self.is_trained,
            'last_train_date': self.last_train_date,
            'n_states': self.config.get_n_states(),
            'model_dir': self.model_dir,
            'should_retrain': self.should_retrain()
        }

        if self.model is not None and self.is_trained:
            try:
                summary['n_features'] = self.model.n_features
                summary['means'] = self.model.means_.tolist()
                summary['model_info'] = {
                    'n_components': self.model.n_components,
                    'covariance_type': self.model.covariance_type,
                    'n_iter': self.model.n_iter
                }
            except Exception as e:
                logger.warning(f"获取模型详情失败: {str(e)}")

        return summary


def create_demo_data(n_days: int = 500, seed: int = 42) -> pd.DataFrame:
    """创建演示用的模拟数据

    Args:
        n_days: 数据天数
        seed: 随机种子

    Returns:
        模拟市场数据DataFrame
    """
    np.random.seed(seed)

    dates = pd.date_range(end=datetime.now(), periods=n_days, freq='B')

    close_prices = 3000 + np.cumsum(np.random.randn(n_days) * 30)

    volumes = np.random.gamma(2, 100000, n_days) + 50000000

    df = pd.DataFrame({
        'date': dates,
        'close': close_prices,
        'volume': volumes.astype(int)
    })

    df.set_index('date', inplace=True)

    return df


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    logger.info("=" * 60)
    logger.info("HMM市场状态识别器演示")
    logger.info("=" * 60)

    detector = HMMMarketStateDetector()

    logger.info("生成模拟数据...")
    demo_data = create_demo_data(n_days=500)
    logger.info(f"数据范围: {demo_data.index[0]} 至 {demo_data.index[-1]}, 共 {len(demo_data)} 条")

    logger.info("训练HMM模型...")
    if detector.train(demo_data):
        logger.info("模型训练成功！")

        logger.info("\n预测当前市场状态...")
        state_id, state_probs = detector.predict(demo_data)
        state_info = detector.get_state_info(state_id, state_probs)

        logger.info(f"当前市场状态: {state_info['state_name']}")
        logger.info(f"状态置信度: {state_info['confidence']:.2%}")
        logger.info(f"状态概率分布:")
        for name, prob in state_info['probabilities'].items():
            logger.info(f"  - {name}: {prob:.2%}")

        logger.info("\n批量预测（最近10天）...")
        recent_states = detector.predict_batch(demo_data[-10:])
        for i, (date, state) in enumerate(zip(demo_data.index[-10:], recent_states)):
            logger.info(f"  {date.strftime('%Y-%m-%d')}: {detector.get_state_name(state)}")

        logger.info("\n保存模型...")
        detector.save_model()

        logger.info("\n模型摘要:")
        summary = detector.get_model_summary()
        for key, value in summary.items():
            logger.info(f"  {key}: {value}")

    else:
        logger.error("模型训练失败！")

    logger.info("=" * 60)
    logger.info("演示完成")
    logger.info("=" * 60)
