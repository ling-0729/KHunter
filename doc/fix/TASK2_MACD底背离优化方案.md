# TASK 2：MACD 底背离优化方案

## 问题分析

### 当前实现

**时间范围**：整个 120 天的回溯期间
- 在 120 天内找最低点
- 范围太大，导致底背离判断不准确

**判断逻辑**：
```python
# 获取最低点的索引
lowest_idx = df['low'].idxmin()  # 在整个120天内找最低点
lowest_low = df.loc[lowest_idx, 'low']
lowest_macd = df.loc[lowest_idx, 'MACD']

# 获取当前（最新）的数据
current_low = df.iloc[0]['low']
current_macd = df.iloc[0]['MACD']

# 判断底背离：价格创新低 AND MACD不创新低
price_new_low = current_low < lowest_low
macd_not_new_low = current_macd > lowest_macd
```

**问题**：
- 120 天的时间跨度太大
- 最低点可能在很久以前
- 无法准确反映最近的底背离形态

### 改进方案

**时间范围**：最近 20 个交易日
- 只在最近 20 天内找最低点
- 更准确地反映近期的底背离形态
- 符合技术分析的常见做法

**改进逻辑**：
```python
# 获取最近20天的数据
recent_days = 20
recent_df = df.head(recent_days)

# 在最近20天内找最低点
lowest_idx = recent_df['low'].idxmin()
lowest_low = recent_df.loc[lowest_idx, 'low']
lowest_macd = recent_df.loc[lowest_idx, 'MACD']

# 获取当前（最新）的数据
current_low = df.iloc[0]['low']
current_macd = df.iloc[0]['MACD']

# 判断底背离：价格创新低 AND MACD不创新低
price_new_low = current_low < lowest_low
macd_not_new_low = current_macd > lowest_macd
```

## 实施计划

### 步骤1：添加参数

在 `__init__` 中添加新参数：
```python
'macd_divergence_days': 20  # MACD底背离判断的时间窗口（交易日）
```

### 步骤2：修改判断逻辑

更新 `_check_macd_divergence()` 方法：
- 使用最近 20 天的数据
- 在 20 天内找最低点
- 判断是否形成底背离

### 步骤3：更新配置

在 `config/strategy_params.yaml` 中添加参数说明

### 步骤4：更新单元测试

修改相关测试用例以适应新的判断逻辑

## 预期效果

### 改进前

- 条件2（MACD底背离）：0% 通过率
- 原因：120 天范围太大，底背离判断不准确

### 改进后

- 条件2（MACD底背离）：预期 5-10% 通过率
- 原因：20 天范围更合理，能更准确地检测底背离

## 技术细节

### MACD 底背离的定义

**底背离**：
- 价格创新低（当前价格 < 最近 20 天最低价）
- MACD 不创新低（当前 MACD > 最近 20 天最低 MACD）
- 表示价格下跌但动能减弱，可能出现反转

### 为什么选择 20 天

1. **技术分析标准**：20 天是常见的短期周期
2. **数据充分性**：20 天足以形成有效的底背离形态
3. **灵敏度平衡**：不会过于敏感，也不会过于迟钝

## 验证方法

修改后运行诊断脚本：
```bash
python test/analyze_conditions.py
```

检查条件2的通过率是否提高

## 总结

通过将 MACD 底背离的判断时间窗口从 120 天改为 20 天，可以更准确地检测底背离形态，提高策略的选股能力。
