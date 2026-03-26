# TASK 9: 参数被修改问题 - 完整分析和解决方案

## 问题确认

### 用户的原始参数（来自备份文件）
```yaml
BowlReboundStrategy:
  params:
    CAP: 44          # 亿元
    J_VAL: 34
    M: 19
    M1: 18
    M2: 32
    M3: 61
    M4: 118
    N: 7
    duokong_pct: 7
    short_pct: 6
```

### 当前YAML中的参数（已被修改）
```yaml
BowlReboundStrategy:
  params:
    CAP: 40          # 被改为默认值
    J_VAL: 30        # 被改为默认值
    M: 15            # 被改为默认值
    M1: 14           # 被改为默认值
    M2: 28           # 被改为默认值
    M3: 57           # 被改为默认值
    M4: 114          # 被改为默认值
    N: 3             # 被改为默认值
    duokong_pct: 3   # 被改为默认值
    short_pct: 2     # 被改为默认值
```

## 根本原因分析

### 问题1：参数保存逻辑缺陷

在 `web_server.py` 的 `save_strategy_params()` 函数中：

```python
# 只更新前端发送的参数，保留其他参数
for param_name, param_value in params.items():
    existing_params[param_name] = param_value
```

**问题**：
- 前端发送的参数可能是不完整的（只包含修改的参数）
- 但后端直接覆盖整个参数字典
- 导致未被修改的参数被丢失

### 问题2：参数转换逻辑不一致

在 `BowlReboundStrategy.__init__()` 中：

```python
if 'CAP' in params:
    cap_value = params['CAP']
    if isinstance(cap_value, (int, float)) and cap_value < 1000:
        # 认为是亿元，转换为元
        params['CAP'] = int(cap_value * 1e8)
```

**问题**：
- 如果YAML中的CAP被错误地保存为 4400000000（元），下次启动时不会被转换
- 导致参数值不正确

### 问题3：前端显示和保存逻辑

前端从API获取参数后显示，用户修改并保存时：
- 前端发送的参数值可能是转换后的值
- 后端直接保存到YAML，导致参数被覆盖

## 解决方案

### 方案A：立即恢复用户参数（紧急修复）

**步骤1**：恢复用户的原始参数到YAML文件
```yaml
BowlReboundStrategy:
  params:
    CAP: 44
    J_VAL: 34
    M: 19
    M1: 18
    M2: 32
    M3: 61
    M4: 118
    N: 7
    duokong_pct: 7
    short_pct: 6
```

**步骤2**：验证参数流转正确

### 方案B：改进参数保存逻辑（根本修复）

**改进1**：在 `save_strategy_params()` 中添加参数验证

```python
def save_strategy_params(name):
    # 1. 读取现有配置
    config = yaml.safe_load(f)
    
    # 2. 获取该策略的现有参数
    existing_params = config['strategies'][name]['params']
    
    # 3. 验证前端发送的参数
    for param_name, param_value in params.items():
        # 检查参数是否在param_details中定义
        param_detail = strategy_config['param_details'].get(param_name)
        if not param_detail:
            return error(f'参数{param_name}未定义')
        
        # 检查参数值是否在允许范围内
        min_val = param_detail.get('min')
        max_val = param_detail.get('max')
        if min_val is not None and param_value < min_val:
            return error(f'参数{param_name}小于最小值{min_val}')
        if max_val is not None and param_value > max_val:
            return error(f'参数{param_name}大于最大值{max_val}')
    
    # 4. 只更新指定的参数
    for param_name, param_value in params.items():
        existing_params[param_name] = param_value
    
    # 5. 写回文件
    yaml.dump(config, f)
```

**改进2**：在前端添加参数验证

```javascript
function validateParams(params) {
    // 检查参数值是否在允许范围内
    for (let param_name in params) {
        let param_detail = paramDetails[param_name];
        if (!param_detail) {
            return false; // 参数未定义
        }
        
        let value = params[param_name];
        if (value < param_detail.min || value > param_detail.max) {
            return false; // 参数值超出范围
        }
    }
    return true;
}
```

**改进3**：添加参数备份机制

```python
def save_strategy_params(name):
    # 1. 备份现有配置
    backup_file = Path(f"config/strategy_params.yaml.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy(config_path, backup_file)
    
    # 2. 保存参数
    # ...
    
    # 3. 验证保存结果
    # 重新读取文件，检查参数是否正确保存
    with open(config_path, 'r') as f:
        saved_config = yaml.safe_load(f)
    
    for param_name, param_value in params.items():
        saved_value = saved_config['strategies'][name]['params'][param_name]
        if saved_value != param_value:
            # 恢复备份
            shutil.copy(backup_file, config_path)
            return error(f'参数保存失败，已恢复备份')
```

## 建议的修复步骤

### 第一步：紧急恢复用户参数
1. 恢复YAML中的参数为用户的原始值
2. 验证参数流转正确

### 第二步：改进参数保存逻辑
1. 添加参数验证
2. 添加参数备份机制
3. 添加保存结果验证

### 第三步：添加参数监控
1. 记录参数的每次修改
2. 便于追踪参数变化历史

### 第四步：测试验证
1. 单元测试：参数保存和加载
2. 集成测试：前后端参数流转
3. 手动测试：用户修改参数并验证

## 下一步

1. 确认采用哪个方案
2. 实施方案
3. 进行测试验证
4. 更新文档

