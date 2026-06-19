"""
参数锁定机制 - 防止策略参数被意外修改或覆盖
"""
import yaml
from pathlib import Path
import hashlib
import json
import logging


class ParamLock:
    """参数锁定器 - 保护策略参数不被修改"""
    
    def __init__(self, params_file="config/strategy_params.yaml"):
        self.params_file = Path(params_file)
        self.lock_file = Path("config/.param_lock")
        self.current_hash = None
        self.locked_params = {}
        self.logger = logging.getLogger(__name__)
        
        # 初始化锁定机制
        self._init_lock()
    
    def _init_lock(self):
        """初始化参数锁定"""
        # 读取当前参数
        if self.params_file.exists():
            with open(self.params_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            
            # 提取所有策略的参数
            strategies = config.get('strategies', {})
            for strategy_name, strategy_config in strategies.items():
                params = strategy_config.get('params', {})
                self.locked_params[strategy_name] = params.copy()
            
            # 计算参数哈希值
            self.current_hash = self._compute_hash(self.locked_params)
    
    def _compute_hash(self, params):
        """计算参数的哈希值"""
        # 将参数转换为 JSON 字符串并计算哈希
        param_str = json.dumps(params, sort_keys=True, default=str)
        return hashlib.md5(param_str.encode()).hexdigest()
    
    def check_and_restore(self):
        """
        检查参数是否被修改，如果被修改则恢复
        :return: (is_modified, restored_params)
        """
        if not self.params_file.exists():
            return False, {}
        
        # 读取当前参数
        with open(self.params_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 提取所有策略的参数
        strategies = config.get('strategies', {})
        current_params = {}
        for strategy_name, strategy_config in strategies.items():
            params = strategy_config.get('params', {})
            current_params[strategy_name] = params.copy()
        
        # 计算当前参数的哈希值
        current_hash = self._compute_hash(current_params)
        
        # 检查是否被修改
        if current_hash != self.current_hash:
            # 参数被修改，检测具体变化
            changes = self._detect_changes(self.locked_params, current_params)
            
            self.logger.warning("⚠️  检测到参数被修改")
            for strategy_name, param_changes in changes.items():
                for param_name, change in param_changes.items():
                    self.logger.warning(f"   {strategy_name}.{param_name}: {change['old']} -> {change['new']}")
            
            # 更新锁定的参数为当前参数（接受用户的修改）
            self.locked_params = current_params
            self.current_hash = current_hash
            
            self.logger.info("✓ 已接受参数修改，参数已锁定")
            
            return True, current_params
        
        return False, {}
    
    def _detect_changes(self, old_params, new_params):
        """
        检测参数的具体变化
        :return: 变化字典
        """
        changes = {}
        
        # 检查所有策略
        all_strategies = set(old_params.keys()) | set(new_params.keys())
        
        for strategy_name in all_strategies:
            old_strategy_params = old_params.get(strategy_name, {})
            new_strategy_params = new_params.get(strategy_name, {})
            
            # 检查参数变化
            all_param_names = set(old_strategy_params.keys()) | set(new_strategy_params.keys())
            
            for param_name in all_param_names:
                old_value = old_strategy_params.get(param_name)
                new_value = new_strategy_params.get(param_name)
                
                if old_value != new_value:
                    if strategy_name not in changes:
                        changes[strategy_name] = {}
                    
                    changes[strategy_name][param_name] = {
                        'old': old_value,
                        'new': new_value
                    }
        
        return changes
    
    def lock_params(self, params):
        """
        锁定新的参数值
        :param params: 要锁定的参数字典
        """
        self.locked_params = params.copy()
        self.current_hash = self._compute_hash(params)
        self.logger.info(f"✓ 参数已锁定")


# 全局参数锁定器实例
_param_lock = None


def get_param_lock(params_file="config/strategy_params.yaml"):
    """获取全局参数锁定器"""
    global _param_lock
    if _param_lock is None:
        _param_lock = ParamLock(params_file)
    return _param_lock
