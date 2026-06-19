"""
配置加载模块 - 加载和管理风控配置
"""
import yaml
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple

# 配置日志
logger = logging.getLogger(__name__)


class RiskConfigLoader:
    """风控配置加载器"""
    
    def __init__(self, config_path: str = 'config/risk_config.yaml'):
        """
        初始化配置加载器
        
        参数：
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self._config = None
        
        logger.info(f"RiskConfigLoader 初始化完成，配置文件: {config_path}")
    
    def load_config(self) -> Optional[Dict]:
        """
        加载配置文件
        
        返回：
            配置字典，失败返回None
        """
        if not self.config_path.exists():
            logger.error(f"配置文件不存在: {self.config_path}")
            return None
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            self._config = config
            logger.info(f"成功加载配置文件: {self.config_path}")
            return config
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            return None
    
    def get_config(self) -> Dict:
        """
        获取配置（自动加载）
        
        返回：
            配置字典
        """
        if self._config is None:
            self.load_config()
        
        return self._config or {}
    
    def get_risk_config(self) -> Dict:
        """
        获取风控基础配置
        
        返回：
            风控配置字典
        """
        config = self.get_config()
        return config.get('risk', {})
    
    def get_var_thresholds(self) -> Dict:
        """
        获取VaR阈值配置
        
        返回：
            VaR阈值字典
        """
        risk_config = self.get_risk_config()
        return risk_config.get('var_thresholds', {})
    
    def get_risk_levels_config(self) -> Dict:
        """
        获取风险等级配置
        
        返回：
            风险等级配置字典
        """
        risk_config = self.get_risk_config()
        return risk_config.get('risk_levels', {})
    
    def get_evt_config(self) -> Dict:
        """
        获取EVT配置
        
        返回：
            EVT配置字典
        """
        config = self.get_config()
        return config.get('evt', {})
    
    def get_cache_config(self) -> Dict:
        """
        获取缓存配置
        
        返回：
            缓存配置字典
        """
        config = self.get_config()
        return config.get('cache', {})
    
    def validate_config(self) -> Tuple[bool, str]:
        """
        验证配置有效性
        
        返回：
            (是否有效, 错误信息) 元组
        """
        config = self.get_config()
        
        if not config:
            return False, "配置为空"
        
        # 检查risk配置
        if 'risk' not in config:
            return False, "缺少risk配置"
        
        risk_config = config['risk']
        
        # 检查必需字段
        required_fields = ['index_code', 'lookback_days', 'confidence_level',
                          'var_thresholds', 'risk_levels']
        for field in required_fields:
            if field not in risk_config:
                return False, f"缺少必需字段: {field}"
        
        # 检查VaR阈值
        thresholds = risk_config['var_thresholds']
        required_thresholds = ['normal', 'caution', 'danger', 'crash']
        for threshold in required_thresholds:
            if threshold not in thresholds:
                return False, f"缺少VaR阈值: {threshold}"
        
        # 检查阈值顺序
        if not (thresholds['normal'] > thresholds['caution'] > 
                thresholds['danger'] >= thresholds['crash']):
            return False, "VaR阈值顺序错误"
        
        # 检查风险等级配置
        risk_levels = risk_config['risk_levels']
        required_levels = ['正常', '注意', '危险', '崩溃']
        for level in required_levels:
            if level not in risk_levels:
                return False, f"缺少风险等级配置: {level}"
            
            level_config = risk_levels[level]
            required_params = ['position_limit', 'stop_loss_multiplier',
                             'score_extra', 'strategy_enabled']
            for param in required_params:
                if param not in level_config:
                    return False, f"风险等级 {level} 缺少参数: {param}"
            
            # 检查仓位上限范围
            if not (0 <= level_config['position_limit'] <= 1):
                return False, f"风险等级 {level} 仓位上限超出范围"
        
        return True, ""
    
    def reload_config(self) -> Optional[Dict]:
        """
        重新加载配置文件
        
        返回：
            配置字典，失败返回None
        """
        self._config = None
        return self.load_config()


# 测试代码
if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 创建配置加载器
    loader = RiskConfigLoader()
    
    # 加载配置
    config = loader.load_config()
    if config:
        print("配置加载成功")
        print(f"\n基础配置:")
        risk_config = loader.get_risk_config()
        print(f"  指数代码: {risk_config.get('index_code')}")
        print(f"  回溯天数: {risk_config.get('lookback_days')}")
        print(f"  置信水平: {risk_config.get('confidence_level')}")
        print(f"  更新频率: {risk_config.get('update_frequency')}")
        
        print(f"\nVaR阈值:")
        thresholds = loader.get_var_thresholds()
        for key, value in thresholds.items():
            print(f"  {key}: {value:.2%}")
        
        print(f"\n风险等级配置:")
        risk_levels = loader.get_risk_levels_config()
        for level, params in risk_levels.items():
            print(f"  {level}:")
            print(f"    仓位上限: {params['position_limit']:.0%}")
            print(f"    止损倍数: {params['stop_loss_multiplier']:.1f}")
            print(f"    额外分数: {params['score_extra']}")
            print(f"    策略启用: {params['strategy_enabled']}")
        
        print(f"\nEVT配置:")
        evt_config = loader.get_evt_config()
        print(f"  启用EVT: {evt_config.get('enabled')}")
        print(f"  阈值分位数: {evt_config.get('threshold_percentile')}")
        
        print(f"\n缓存配置:")
        cache_config = loader.get_cache_config()
        print(f"  启用缓存: {cache_config.get('enabled')}")
        print(f"  缓存目录: {cache_config.get('cache_dir')}")
        print(f"  缓存过期时间: {cache_config.get('cache_expire_hours')}小时")
    
    # 验证配置
    is_valid, msg = loader.validate_config()
    print(f"\n配置验证: {'通过' if is_valid else '失败'} - {msg}")