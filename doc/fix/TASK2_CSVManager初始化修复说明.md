# TASK 2: CSVManager 初始化错误修复

## 问题描述

在查询选股历史时，系统日志中出现以下错误：

```
ERROR - [selection_record_manager.py:501] - 计算表现指标失败: CSVManager.__init__() missing 1 required positional argument: 'data_dir'
```

## 根本原因

`CSVManager` 类的 `__init__` 方法需要一个 `data_dir` 参数，但在 `selection_record_manager.py` 中调用时没有传递这个参数。

### 错误代码
```python
# 错误的调用方式
csv_manager = CSVManager()  # 缺少 data_dir 参数
```

### 正确的调用方式
```python
# 正确的调用方式
csv_manager = CSVManager('data')  # 传递 data_dir 参数
```

## 修复方案

### 修改的文件
- `utils/selection_record_manager.py`

### 修改的方法
1. `calculate_performance()` 方法（第501行）
2. `_get_stock_price()` 方法

### 具体修改
在两个方法中，将：
```python
csv_manager = CSVManager()
```

改为：
```python
csv_manager = CSVManager('data')
```

## 测试结果

修复后，所有单元测试通过：
- **总数**：24个测试
- **通过**：24个 ✅
- **失败**：0个

## 验证

修复后，查询选股历史时不再出现 `CSVManager` 初始化错误。系统能够正常计算表现指标。

## 提交信息

```
修复CSVManager初始化错误 - 添加data_dir参数
```

## 影响范围

- 修复了查询选股历史时的错误
- 不影响其他功能
- 所有单元测试继续通过


---

# 附加修复：JSON序列化错误

## 问题描述

在查询选股历史时，前端出现以下错误：

```
⚠️ 网络错误: Unexpected token 'I', ..."ax_gain": Infinity, "... is not valid JSON
```

## 根本原因

当选入价格为0时，计算收益率会产生 `Infinity` 值，而JSON无法序列化 `Infinity`。

### 错误代码
```python
# 当 selection_price = 0 时，会产生 Infinity
return_rate = ((current_price - selection_price) / selection_price) * 100
```

### 正确的代码
```python
# 添加分母检查，避免除以0
return_rate = ((current_price - selection_price) / selection_price) * 100 if selection_price != 0 else 0.0
```

## 修复方案

### 修改的方法
`calculate_performance()` 方法中的收益率计算部分

### 具体修改
在计算 `return_rate`、`max_gain` 和 `max_loss` 时，添加分母检查：

```python
# 计算收益率
return_rate = ((current_price - selection_price) / selection_price) * 100 if selection_price != 0 else 0.0
max_gain = ((highest_price - selection_price) / selection_price) * 100 if selection_price != 0 else 0.0
max_loss = ((lowest_price - selection_price) / selection_price) * 100 if selection_price != 0 else 0.0
```

## 测试结果

修复后，所有单元测试继续通过：
- **总数**：24个测试
- **通过**：24个 ✅
- **失败**：0个

## 验证

修复后，查询选股历史时不再出现JSON序列化错误。前端能够正常显示选股历史数据。

## 提交信息

```
修复JSON序列化错误 - 处理Infinity值
```

## 影响范围

- 修复了查询选股历史时的JSON序列化错误
- 当选入价格为0时，收益率显示为0.0而不是Infinity
- 所有单元测试继续通过
