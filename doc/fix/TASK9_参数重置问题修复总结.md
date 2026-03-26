# TASK 9: 参数被重置问题修复总结

## 问题描述

用户设置的策略参数（CAP: 44, J_VAL: 34, M: 19, M1: 18, M2: 32, M3: 61, M4: 118, N: 7, duokong_pct: 7, short_pct: 6）在每次选股请求后被重置为默认值。

## 根本原因分析

### 问题链路

**第一层问题**：参数单位转换导致的参数不一致
1. YAML文件中的参数：CAP = 44（亿元）
2. Registry初始化时：通过 `BowlReboundStrategy.__init__()` 转换，CAP = 4400000000（元）
3. get_strategy()调用时：直接从YAML读取参数，CAP = 44（亿元）
4. 结果：参数被"重置"为YAML中的值

**第二层问题**：前端显示转换后的参数值导致的参数覆盖
1. 前端从API获取参数，显示转换后的值（CAP: 4400000000）
2. 用户看到这个值，认为这是正确的参数
3. 用户修改其他参数并保存时，前端发送所有参数给后端
4. 后端将转换后的CAP值（4400000000）保存到YAML文件
5. 结果：YAML文件中的CAP被覆盖为 4400000000

### 技术细节

**问题1**：`strategy_registry.py` 的 `get_strategy()` 方法
- 直接从YAML读取参数，没有经过 `BowlReboundStrategy.__init__()` 的转换逻辑
- 导致参数被"重置"为YAML中的值

**问题2**：`web_server.py` 的 `get_strategies()` 和 `get_strategy_detail()` 方法
- 返回转换后的参数值给前端
- 前端显示转换后的值，用户修改并保存时，转换后的值被写入YAML文件
- 导致参数被覆盖

## 解决方案

### 修改1：改进 `strategy_registry.py` 的 `get_strategy()` 方法

重新实例化策略对象而不是直接赋值参数，确保参数经过正确的转换逻辑。

```python
def get_strategy(self, name):
    # 重新实例化策略对象，确保参数经过正确的转换逻辑
    strategy_class = type(strategy)
    new_strategy = strategy_class(params=latest_params)
    
    # 保留元数据和参数定义
    new_strategy.metadata = getattr(strategy, 'metadata', {})
    new_strategy.param_groups = getattr(strategy, 'param_groups', [])
    new_strategy.param_details = getattr(strategy, 'param_details', {})
    
    # 更新缓存中的策略对象
    self.strategies[name] = new_strategy
    
    return new_strategy
```

### 修改2：改进 `web_server.py` 的 `get_strategies()` 和 `get_strategy_detail()` 方法

直接从YAML文件读取原始参数值，而不是返回转换后的参数值。

```python
@app.route('/api/strategies')
def get_strategies():
    # 从YAML文件直接读取原始参数，而不是转换后的参数
    import yaml
    config_file = Path("config/strategy_params.yaml")
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}
    
    # 从YAML中获取原始参数值（不经过转换）
    original_params = strategy_config.get('params', {})
    
    strategies.append({
        'name': name,
        'params': original_params  # 使用原始参数，不是转换后的
    })
```

## 验证结果

### 参数流转验证

| 步骤 | CAP值 | 状态 |
|------|------|------|
| 1. YAML文件 | 44 | ✓ 原始值 |
| 2. Registry初始化 | 4400000000 | ✓ 正确转换（内部使用） |
| 3. get_strategy()调用 | 4400000000 | ✓ 内部使用转换后的值 |
| 4. /api/strategies返回 | 44 | ✓ 返回原始值给前端 |
| 5. /api/strategy/<name>返回 | 44 | ✓ 返回原始值给前端 |
| 6. 前端显示 | 44 | ✓ 显示原始值 |
| 7. 用户保存参数 | 44 | ✓ 保存原始值到YAML |
| 8. YAML文件（操作后） | 44 | ✓ 未被覆盖 |

### 参数一致性验证

所有参数在整个流程中保持一致：

```
✓ CAP: 44（YAML中的原始值）
✓ J_VAL: 34
✓ M: 19
✓ M1: 18
✓ M2: 32
✓ M3: 61
✓ M4: 118
✓ N: 7
✓ duokong_pct: 7
✓ short_pct: 6
```

## 影响范围

### 修改文件

- `strategy/strategy_registry.py` - `get_strategy()` 方法
- `web_server.py` - `get_strategies()` 和 `get_strategy_detail()` 方法

### 相关功能

- `/api/strategies` - 获取策略列表（现在返回原始参数值）
- `/api/strategy/<name>` - 获取策略详情（现在返回原始参数值）
- `/api/select` - 执行选股（内部使用转换后的参数）
- `/api/strategies/<name>/params` - 保存策略参数（现在保存原始参数值）

## 后续建议

1. **参数单位标准化**：考虑在YAML中统一使用元作为单位，避免转换逻辑
2. **参数验证**：在保存参数时添加验证，确保参数值在合理范围内
3. **参数缓存**：如果性能成为瓶颈，可以考虑添加参数缓存机制，但需要确保缓存失效策略正确

## 提交信息

```
TASK9: 修复参数被重置问题 - 改进get_strategy()方法重新实例化策略对象
TASK9: 修复参数显示问题 - 前端显示原始参数值而不是转换后的值
```

## 测试状态

- ✓ 参数修复验证通过
- ✓ 参数显示修复验证通过
- ✓ 代码已提交到git
- ✓ 参数锁定机制继续有效
