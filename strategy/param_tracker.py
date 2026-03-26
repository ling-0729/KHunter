"""
参数修改追踪系统 - 追踪参数何时被修改以及由谁修改
"""
import yaml
import json
import hashlib
from pathlib import Path
from datetime import datetime
import traceback


class ParamTracker:
    """参数修改追踪器"""
    
    def __init__(self, params_file="config/strategy_params.yaml"):
        self.params_file = Path(params_file)
        self.track_file = Path("logs/param_changes.log")
        self.current_hash = None
        self.current_params = {}
        
        # 初始化追踪
        self._init_tracking()
    
    def _init_tracking(self):
        """初始化参数追踪"""
        if self.params_file.exists():
            with open(self.params_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            
            # 提取所有策略的参数
            strategies = config.get('strategies', {})
            for strategy_name, strategy_config in strategies.items():
                params = strategy_config.get('params', {})
                self.current_params[strategy_name] = params.copy()
            
            # 计算哈希值
            self.current_hash = self._compute_hash(self.current_params)
    
    def _compute_hash(self, params_dict):
        """计算参数的哈希值"""
        param_str = json.dumps(params_dict, sort_keys=True, default=str)
        return hashlib.md5(param_str.encode()).hexdigest()
    
    def check_changes(self):
        """
        检查参数是否被修改
        :return: (is_changed, changes_dict)
        """
        if not self.params_file.exists():
            return False, {}
        
        # 读取当前参数
        with open(self.params_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 提取所有策略的参数
        strategies = config.get('strategies', {})
        new_params = {}
        for strategy_name, strategy_config in strategies.items():
            params = strategy_config.get('params', {})
            new_params[strategy_name] = params.copy()
        
        # 计算新的哈希值
        new_hash = self._compute_hash(new_params)
        
        # 检查是否被修改
        if new_hash != self.current_hash:
            # 参数被修改，记录变化
            changes = self._detect_changes(self.current_params, new_params)
            self._log_changes(changes)
            
            # 更新当前参数和哈希值
            self.current_params = new_params
            self.current_hash = new_hash
            
            return True, changes
        
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
    
    def _log_changes(self, changes):
        """
        记录参数变化到日志文件
        :param changes: 变化字典
        """
        try:
            # 获取调用栈信息
            stack = traceback.extract_stack()
            caller_info = "Unknown"
            
            # 查找调用者信息（跳过当前文件）
            for frame in reversed(stack[:-1]):
                if 'param_tracker.py' not in frame.filename:
                    caller_info = f"{frame.filename}:{frame.lineno} in {frame.name}"
                    break
            
            # 构建日志消息
            log_message = f"\n{'='*60}\n"
            log_message += f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            log_message += f"调用者: {caller_info}\n"
            log_message += f"参数变化:\n"
            
            for strategy_name, param_changes in changes.items():
                log_message += f"\n  策略: {strategy_name}\n"
                for param_name, change in param_changes.items():
                    log_message += f"    {param_name}: {change['old']} -> {change['new']}\n"
            
            log_message += f"{'='*60}\n"
            
            # 写入日志文件
            with open(self.track_file, 'a', encoding='utf-8') as f:
                f.write(log_message)
            
            print(f"⚠️  参数被修改，已记录到 {self.track_file}")
            print(log_message)
        
        except Exception as e:
            print(f"记录参数变化失败: {e}")


# 全局参数追踪器实例
_param_tracker = None


def get_param_tracker(params_file="config/strategy_params.yaml"):
    """获取全局参数追踪器"""
    global _param_tracker
    if _param_tracker is None:
        _param_tracker = ParamTracker(params_file)
    return _param_tracker
