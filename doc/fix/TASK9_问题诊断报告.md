# TASK 9: 参数被修改问题 - 深度诊断报告

## 问题现象

用户手动修改了策略参数后，参数依然会被修改。最新的错误是：
- 前端发送POST请求到 `/api/select` 时出现 `net::ERR_CONNECTION_RESET` 错误
- 这表示后端服务器连接被重置

## 问题分析

### 1. 连接重置的可能原因

**原因A：后端服务崩溃**
- 选股过程中发生未捕获的异常
- 导致Flask应用崩溃或连接被强制关闭

**原因B：参数转换异常**
- BowlReboundStrategy.__init__() 中的CAP参数转换逻辑可能有问题
- 当参数值不符合预期时，可能导致异常

**原因C：参数加载逻辑问题**
- get_strategy() 方法每次都重新实例化策略对象
- 如果参数值不正确，可能导致异常

### 2. 参数被修改的根本原因

根据之前的分析，参数被修改有两个层面的问题：

**第一层：参数单位转换不一致**
```
YAML中: CAP = 44 (亿元)
Registry初始化: CAP = 4400000000 (元) ✓ 正确转换
get_strategy()调用: CAP = 44 (亿元) ✗ 直接从YAML读取，覆盖了转换后的值
```

**第二层：前端显示转换后的值**
```
前端从API获取: CAP = 4400000000 (转换后的值)
前端显示: CAP = 4400000000
用户看到这个值，认为这是正确的参数
用户修改其他参数并保存时，前端发送所有参数给后端
后端将转换后的CAP值 (4400000000) 保存到YAML文件
结果：YAML文件中的CAP被覆盖为 4400000000
```

### 3. 当前代码的问题

**问题1：BowlReboundStrategy.__init__() 的参数转换逻辑**

```python
if 'CAP' in params:
    cap_value = params['CAP']
    if isinstance(cap_value, (int, float)) and cap_value < 1000:
        # 认为是亿元，转换为元
        params['CAP'] = int(cap_value * 1e8)
```

这个逻辑有问题：
- 如果用户手动修改YAML中的CAP为 4400000000，这个条件不会触发
- 导致参数值不被转换，直接使用 4400000000
- 下次启动时，YAML中的CAP是 4400000000，再次转换会变成 440000000000000000（错误！）

**问题2：get_strategy() 方法的参数加载**

```python
def get_strategy(self, name):
    # 从配置文件加载最新的参数
    latest_params = self._load_strategy_params(name)
    
    # 重新实例化策略对象
    strategy_class = type(strategy)
    new_strategy = strategy_class(params=latest_params)
```

这个逻辑有问题：
- 每次调用 get_strategy() 都会重新实例化策略对象
- 如果参数值不正确（如 4400000000），会导致异常
- 异常可能导致连接重置

**问题3：参数保存逻辑**

```python
def save_strategy_params(name):
    # 只更新前端发送的参数，保留其他参数
    for param_name, param_value in params.items():
        existing_params[param_name] = param_value
```

这个逻辑有问题：
- 前端发送的参数值是转换后的值（如 4400000000）
- 后端直接保存这个值到YAML文件
- 导致YAML文件中的参数被覆盖为转换后的值

## 解决方案

### 方案1：统一参数单位（推荐）

**目标**：在YAML中统一使用元作为单位，避免转换逻辑

**步骤**：
1. 修改 `config/strategy_params.yaml`：CAP 改为 4400000000（元）
2. 修改 `BowlReboundStrategy.__init__()`：移除CAP参数转换逻辑
3. 修改 `web_server.py`：前端显示时转换为亿元显示，保存时转换回元

**优点**：
- 消除参数转换的复杂性
- 参数值在整个流程中保持一致
- 易于维护和调试

**缺点**：
- 需要修改YAML文件
- 需要修改前端显示逻辑

### 方案2：改进参数转换逻辑（备选）

**目标**：确保参数转换逻辑正确，避免重复转换

**步骤**：
1. 在BowlReboundStrategy中添加参数验证逻辑
2. 在save_strategy_params中添加参数反向转换逻辑
3. 在get_strategy中添加异常处理

**优点**：
- 不需要修改YAML文件
- 保持现有的参数单位

**缺点**：
- 转换逻辑复杂
- 易于出错

## 建议

**立即采取的行动**：

1. **修复连接重置问题**
   - 在 `run_selection()` 中添加更详细的异常处理
   - 确保所有异常都被捕获并返回JSON响应
   - 不要让异常导致连接重置

2. **修复参数转换问题**
   - 采用方案1（统一参数单位）
   - 这是最彻底的解决方案

3. **添加参数验证**
   - 在保存参数时验证参数值的合理性
   - 防止用户输入无效的参数值

4. **添加参数监控**
   - 在日志中记录参数的每次修改
   - 便于追踪参数变化历史

## 下一步

1. 确认采用哪个方案
2. 实施方案
3. 进行测试验证
4. 更新文档

