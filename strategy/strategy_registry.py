"""
策略注册器 - 支持动态加载策略
"""
import importlib
import sys
from pathlib import Path
import yaml


class StrategyRegistry:
    """策略注册器"""
    
    def __init__(self, params_file="config/strategy_params.yaml", order_file="config/strategy_order.yaml"):
        self.strategies = {}
        self.params_file = Path(params_file)
        self.order_file = Path(order_file)
        self.params = self._load_params()
        self.strategy_order = self._load_strategy_order()
    
    def _load_params(self):
        """加载策略参数配置"""
        if self.params_file.exists():
            with open(self.params_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}
    
    def _load_strategy_order(self):
        """加载策略排序配置"""
        # 如果排序文件不存在，返回空字典
        if not self.order_file.exists():
            return {}
        
        try:
            with open(self.order_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
                # 构建策略名称到排序的映射
                order_map = {}
                for item in config.get('strategy_order', []):
                    order_map[item['name']] = item['order']
                return order_map
        except Exception as e:
            print(f"[WARNING] 加载策略排序配置失败: {e}")
            return {}
    
    def register(self, strategy_class, name=None):
        """
        注册策略
        :param strategy_class: 策略类
        :param name: 策略名称（默认使用类名）
        """
        strategy_name = name or strategy_class.__name__
        
        # 获取该策略的配置 - 从 strategies 嵌套结构中获取
        strategies_config = self.params.get('strategies', {})
        strategy_config = strategies_config.get(strategy_name, {})
        
        # 分离元数据、参数定义和参数值
        # 元数据字段
        metadata_fields = {'display_name', 'description', 'icon', 'color'}
        # 参数定义字段
        definition_fields = {'param_groups', 'param_details'}
        
        # 提取参数值（排除元数据和定义字段）
        params = strategy_config.get('params', {})
        
        # 实例化策略
        strategy = strategy_class(params=params)
        
        # 存储元数据到策略对象
        strategy.metadata = {k: strategy_config.get(k) 
                            for k in metadata_fields 
                            if k in strategy_config}
        
        # 存储参数定义到策略对象
        strategy.param_groups = strategy_config.get('param_groups', [])
        strategy.param_details = strategy_config.get('param_details', {})
        
        self.strategies[strategy_name] = strategy
        
        return strategy
    
    def _load_strategy_params(self, strategy_name):
        """
        从配置文件加载指定策略的最新参数
        :param strategy_name: 策略名称
        :return: 参数字典
        """
        # 重新加载配置文件
        params_config = self._load_params()
        strategies_config = params_config.get('strategies', {})
        strategy_config = strategies_config.get(strategy_name, {})
        # 返回该策略的参数值
        return strategy_config.get('params', {})
    
    def get_strategy(self, name):
        """
        获取已注册的策略 - 每次都从配置文件重新加载参数
        :param name: 策略名称
        :return: 策略对象（参数为最新值）
        """
        if name not in self.strategies:
            return None
        
        # 从配置文件加载最新的参数
        latest_params = self._load_strategy_params(name)
        
        # 获取缓存的策略对象
        strategy = self.strategies[name]
        
        # 重新实例化策略对象，确保参数经过正确的转换逻辑
        # 这样可以确保CAP等参数的单位转换正确进行
        strategy_class = type(strategy)
        new_strategy = strategy_class(params=latest_params)
        
        # 保留元数据和参数定义
        new_strategy.metadata = getattr(strategy, 'metadata', {})
        new_strategy.param_groups = getattr(strategy, 'param_groups', [])
        new_strategy.param_details = getattr(strategy, 'param_details', {})
        
        # 更新缓存中的策略对象
        self.strategies[name] = new_strategy
        
        return new_strategy
    
    def list_strategies(self):
        """列出所有已注册的策略（按排序顺序）"""
        # 如果有排序配置，按排序顺序返回
        if self.strategy_order:
            sorted_strategies = sorted(
                self.strategies.keys(),
                key=lambda x: self.strategy_order.get(x, float('inf'))
            )
            return sorted_strategies
        # 否则返回原始顺序
        return list(self.strategies.keys())
    
    def auto_register_from_directory(self, strategy_dir="strategy"):
        """
        自动从目录加载策略
        导入所有非 _ 开头的 .py 文件
        """
        strategy_path = Path(strategy_dir)
        if not strategy_path.exists():
            strategy_path = Path(__file__).parent
        
        # 添加策略目录到路径
        if str(strategy_path) not in sys.path:
            sys.path.insert(0, str(strategy_path))
        
        # 遍历策略文件
        for py_file in strategy_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            
            module_name = py_file.stem
            
            try:
                # 动态导入模块
                if module_name in sys.modules:
                    module = sys.modules[module_name]
                else:
                    module = importlib.import_module(module_name)
                
                # 查找策略类（继承自 BaseStrategy 的类）
                from strategy.base_strategy import BaseStrategy
                
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, BaseStrategy) and 
                        attr is not BaseStrategy):
                        
                        # 检查是否有display_name属性
                        strategy_instance = attr()
                        strategy_name = getattr(strategy_instance, 'display_name', attr_name)
                        
                        # 注册策略（排除基类）
                        self.register(attr, name=strategy_name)
                        print(f"  [OK] 注册策略: {strategy_name}")
                        
            except Exception as e:
                print(f"  [ERROR] 加载 {module_name} 失败: {e}")
    
    def run_strategy(self, strategy_name, stock_data_dict):
        """
        运行单个策略
        :param strategy_name: 策略名称
        :param stock_data_dict: {code: (name, df)} 格式的股票数据
        :return: {strategy_name: [signals]} 格式的结果
        """
        if strategy_name not in self.strategies:
            return {}
        
        strategy = self.strategies[strategy_name]
        total_stocks = len(stock_data_dict)
        
        print(f"\n执行策略: {strategy_name}")
        print(f"  共 {total_stocks} 只股票待分析...")
        signals = []
        processed = 0
        
        for code, (name, df) in stock_data_dict.items():
            result = strategy.analyze_stock(code, name, df)
            if result:
                signals.append(result)
            
            processed += 1
            # 每100只股票显示一次进度
            if processed % 100 == 0 or processed == total_stocks:
                print(f"  进度: [{processed}/{total_stocks}] 已分析 {processed} 只，选出 {len(signals)} 只...")
        
        print(f"  ✓ 选股完成: 共 {len(signals)} 只股票符合策略")
        return {strategy_name: signals}
    
    def run_all(self, stock_data_dict, return_indicators=False):
        """
        运行所有策略（按排序顺序）
        :param stock_data_dict: {code: (name, df)} 格式的股票数据
        :param return_indicators: 是否返回计算了指标的数据
        :return: {strategy_name: [signals]} 格式的结果，或 (results, indicators_dict)
        """
        results = {}
        indicators_dict = {}  # 存储计算了指标的数据
        total_stocks = len(stock_data_dict)
        
        # 获取排序后的策略列表
        strategy_names = self.list_strategies()
        
        for strategy_name in strategy_names:
            strategy = self.strategies[strategy_name]
            print(f"\n执行策略: {strategy_name}")
            print(f"  共 {total_stocks} 只股票待分析...")
            signals = []
            processed = 0
            
            for code, (name, df) in stock_data_dict.items():
                # 计算指标并保存
                if return_indicators:
                    df_with_indicators = strategy.calculate_indicators(df)
                    indicators_dict[code] = df_with_indicators
                    result = strategy.select_stocks(df_with_indicators, name)
                    if result:
                        signals.append({
                            'code': code,
                            'name': name,
                            'signals': result
                        })
                else:
                    result = strategy.analyze_stock(code, name, df)
                    if result:
                        signals.append(result)
                
                processed += 1
                # 每100只股票显示一次进度
                if processed % 100 == 0 or processed == total_stocks:
                    print(f"  进度: [{processed}/{total_stocks}] 已分析 {processed} 只，选出 {len(signals)} 只...")
            
            results[strategy_name] = signals
            print(f"  ✓ 选股完成: 共 {len(signals)} 只股票符合策略")
        
        if return_indicators:
            return results, indicators_dict
        return results


# 全局注册器实例
_registry = None

def get_registry(params_file="config/strategy_params.yaml", order_file="config/strategy_order.yaml"):
    """获取全局策略注册器"""
    global _registry
    if _registry is None:
        _registry = StrategyRegistry(params_file, order_file)
    return _registry
