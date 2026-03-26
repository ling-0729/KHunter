# W底策略BUG分析报告

## 问题描述
W底策略已在运行，但001325不符合规则却被选入了。

---

## 根本原因分析

### BUG 1：颈线突破检测逻辑错误（第一优先级）

**位置**：`_check_neckline_break()` 方法，第273-290行

**问题代码**：
```python
# 在 L2 之后（索引 < l2_idx）的交易日中检测
# 倒序数据中从 l2_idx-1 到 0，时间从早到新
# 找首次突破日（最早满足条件的）
first_break_idx = None
for idx in range(l2_idx - 1, -1, -1):
    # ... 检查逻辑 ...
    if close < break_price:
        continue
    # 放量条件检查
    if volume >= vol_ma * expand_ratio:
        first_break_idx = idx
        break
```

**问题分析**：
1. 循环从 `l2_idx - 1` 开始，向下遍历到 0
2. 在倒序数据中，索引越小表示时间越新
3. 代码注释说"找首次突破日（最早满足条件的）"，但实际上找的是**最新的突破日**
4. 对于001325：
   - L2日期：2026-03-04
   - 首次突破日应该是：2026-03-20（最早满足条件）
   - 但代码找到的是：2026-03-24（最新满足条件）

**为什么001325被错误选入**：
- 2026-03-24的收盘价54.33 < 颈线58.21 × 1.01 = 58.79
- 但代码仍然选入了，说明 `break_price` 的计算或比较有问题

### BUG 2：突破价格阈值计算错误（第二优先级）

**位置**：`_check_neckline_break()` 方法，第265行

**问题代码**：
```python
# 突破价格阈值
break_price = neckline * break_ratio
```

**问题分析**：
- 对于001325：neckline = 58.21，break_ratio = 1.01
- break_price = 58.21 × 1.01 = 58.79
- 但2026-03-24的收盘价是54.33，明显 < 58.79
- 代码应该拒绝这个突破，但却选入了

**可能的原因**：
- `break_ratio` 参数被修改为 < 1.0（例如0.93）
- 或者 `neckline` 的值被错误计算

### BUG 3：支撑位检查重复代码（第三优先级）

**位置**：`_check_fake_w_bottom()` 方法，第375-376行

**问题代码**：
```python
# 跌破支撑位则判定为假W底
if close < support_price:
    return False
    return False  # ← 重复的return语句
```

**问题分析**：
- 第376行的 `return False` 是重复的，应该删除
- 这不会导致逻辑错误，但是代码质量问题

### BUG 4：突破日时效检查不合理（第四优先级）

**位置**：`_check_neckline_break()` 方法，第291-293行

**问题代码**：
```python
# 检查首次突破日是否在 max_break_days 范围内
if first_break_idx is not None and first_break_idx <= max_break_days:
    return first_break_idx
```

**问题分析**：
- 倒序数据中，index=0是最新日期，index越大越早
- 条件 `first_break_idx <= max_break_days` 检查的是索引值，不是天数差
- 应该改为：`(l2_idx - first_break_idx) <= max_break_days`

**对001325的影响**：
- 如果 `max_break_days = 10`，而突破日索引 > 10，则会被拒绝
- 但这个检查可能被绕过了

---

## 001325被错误选入的完整链路

### 实际数据分析

| 日期 | 收盘价 | 最低价 | 成交量 | 说明 |
|------|--------|--------|--------|------|
| 2025-12-18 | 67.23 | 65.65 | 152,947 | L1（左底） |
| 2025-12-23 | 55.71 | 51.40 | 110,756 | H（中间高点） |
| 2026-03-04 | 49.87 | 49.30 | 16,407 | L2（右底） |
| 2026-03-20 | 56.88 | 54.09 | 54,261 | 应该的突破日 |
| 2026-03-24 | 54.33 | 52.66 | 32,389 | 被错误选中的日期 |

### 错误选入的原因

1. **颈线突破检测找错了日期**
   - 应该找2026-03-20（首次突破）
   - 实际找到2026-03-24（最新满足某条件）

2. **突破价格阈值可能被修改**
   - 如果 `neckline_break_ratio` 被改为 0.93
   - 则 break_price = 58.21 × 0.93 = 54.14
   - 2026-03-24的收盘价54.33 > 54.14，满足条件

3. **放量条件可能被绕过**
   - 2026-03-24的成交量32,389手
   - 如果 `volume_expand_ratio` 被改为 1.0
   - 则只需成交量 >= 均量即可

---

## 修复方案

### 修复1：颈线突破检测逻辑（优先级：高）

```python
def _check_neckline_break(self, df, l2_idx, neckline):
    """
    检测颈线突破+放量确认
    
    在 L2 之后的交易日中检测收盘价是否放量突破颈线。
    倒序数据中 L2 之后的交易日索引 < l2_idx。
    
    :param df: 含指标的DataFrame（倒序）
    :param l2_idx: L2 的索引
    :param neckline: 颈线价格（H的价格）
    :return: 突破日的索引，或 None
    """
    # 获取参数
    break_ratio = self.params['neckline_break_ratio']
    expand_ratio = self.params['volume_expand_ratio']
    max_break_days = self.params.get('max_break_days', 10)

    # 突破价格阈值
    break_price = neckline * break_ratio

    # 在 L2 之后（索引 < l2_idx）的交易日中检测
    # 倒序数据中从 l2_idx-1 到 0，时间从早到新
    # 找首次突破日（最早满足条件的）
    first_break_idx = None
    for idx in range(l2_idx - 1, -1, -1):
        # 跳过无效数据
        if idx not in df.index:
            continue
        close = df['close'].iloc[idx]
        volume = df['volume'].iloc[idx]
        vol_ma = df['volume_ma'].iloc[idx]

        # 检查收盘价是否 NaN
        if pd.isna(close) or pd.isna(volume):
            continue

        # 突破条件：收盘价 >= 颈线 × neckline_break_ratio
        if close < break_price:
            continue

        # 放量条件：成交量 >= volume_ma × volume_expand_ratio
        # 防止 volume_ma 为 0 或 NaN
        if pd.isna(vol_ma) or vol_ma <= 0:
            continue
        if volume >= vol_ma * expand_ratio:
            # 两个条件同时满足，记录首次突破日
            first_break_idx = idx
            # 不要break，继续找最早的突破日
            # break  ← 删除这行

    # 检查首次突破日是否在 max_break_days 范围内
    if first_break_idx is not None:
        # 修复：检查天数差，而不是索引值
        days_diff = l2_idx - first_break_idx
        if days_diff <= max_break_days:
            return first_break_idx

    # 无有效突破或突破日距今过久
    return None
```

**关键改动**：
- 删除 `break` 语句，继续遍历找最早的突破日
- 修改时效检查：`days_diff = l2_idx - first_break_idx`

### 修复2：删除重复代码（优先级：低）

```python
# 在 _check_fake_w_bottom() 方法中，删除第376行的重复 return False
```

---

## 验证方案

### 测试用例：001325

**预期结果**：
- 如果参数为默认值，001325应该被拒绝（因为价格差异24.9% > 3%）
- 如果参数被调整为允许更大的价格差异，则应该在2026-03-20被选入（首次突破日）
- 不应该在2026-03-24被选入

**测试步骤**：
1. 检查 `config/strategy_params.yaml` 中的参数值
2. 运行修复后的代码
3. 验证001325的选股结果

---

## 建议

1. **立即修复**：修复颈线突破检测逻辑（BUG 1）
2. **同时修复**：删除重复代码（BUG 3）
3. **检查参数**：确认 `config/strategy_params.yaml` 中的参数是否被修改
4. **添加日志**：在关键步骤添加日志，便于调试
5. **编写单元测试**：针对001325等边界情况编写测试用例

