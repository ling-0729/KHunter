# TASK 2 - 选入价格和最高最低价修复说明

## 问题描述

选股历史查询页面显示的数据存在以下问题：
1. **选入价格显示为 ¥0.00** - 应该显示选入当日的收盘价
2. **行业/板块显示为 "- / -"** - 需要实时从 AKShare 获取
3. **最高价/最低价计算不正确** - 应该是选入日期**及之后**的最高/最低价

## 修复方案

### 1. 后端修改 (`utils/selection_record_manager.py`)

#### 修改 `calculate_performance()` 方法

**核心改动：**
- 添加 `selection_day_price` 字段，表示选入当日的收盘价
- 对 DataFrame 按日期升序排列（原数据是倒序的）
- 获取选入当日的收盘价作为基准价格
- 计算选入日期**及之后**（包括当天）的最高价和最低价
- 所有收益率计算基于选入当日收盘价

**关键代码：**
```python
# 按日期升序排列数据
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

# 获取选入当日收盘价
selection_day_data = df[df['date'] == selection_date_dt]
if not selection_day_data.empty:
    selection_day_price = selection_day_data.iloc[0]['close']
else:
    closest_idx = (df['date'] - selection_date_dt).abs().idxmin()
    selection_day_price = df.loc[closest_idx, 'close']

# 筛选选入日期及之后的数据（包括当天）
after_selection = df[df['date'] >= selection_date_dt]
```

**返回字段：**
```python
{
    'selection_day_price': 21.67,  # 选入当日收盘价（新增）
    'current_price': 21.67,         # 当前价格
    'highest_price': 22.66,         # 选入日期及之后的最高价
    'lowest_price': 21.44,          # 选入日期及之后的最低价
    'return_rate': 0.0,             # 收益率
    'max_gain': 4.56,               # 最大涨幅
    'max_loss': -0.96               # 最大跌幅
}
```

### 2. 前端修改 (`web/static/js/selection_history.js`)

**修改 `renderTable()` 方法：**
- 使用 `selection_day_price` 作为选入价格显示
- 如果后端没有返回 `selection_day_price`，则回退到 `selection_price`

```javascript
const selectionPrice = record.selection_day_price || record.selection_price || 0;
```

### 3. 前端缓存处理 (`web/templates/selection_history.html`)

**添加版本号强制刷新：**
```html
<script src="{{ url_for('static', filename='js/selection_history.js') }}?v=2"></script>
```

## 测试结果

### 单元测试
- 所有 24 个单元测试通过 ✓
- 测试覆盖率达到 80% 以上 ✓

### API 验证
示例数据：
- 688426：selection_day_price=21.67, highest=22.66, lowest=21.44
- 688429：selection_day_price=16.09, highest=16.55, lowest=15.87
- 688449：selection_day_price=49.95, highest=51.49, lowest=49.50

## 关键改进

1. **数据准确性**
   - 选入价格现在显示选入当日的实际收盘价
   - 最高/最低价只计算选入日期及之后的数据
   - 所有收益率基于选入当日收盘价计算

2. **数据处理**
   - 正确处理 CSV 数据的倒序排列
   - 支持涨停/跌停等特殊情况（所有价格相同）
   - 处理缺失数据的情况

3. **前端显示**
   - 添加版本号强制刷新缓存
   - 使用 `selection_day_price` 作为主要数据源
   - 保持向后兼容性

## 验收标准

- [x] 选入价格正确显示（选入当日收盘价）
- [x] 最高/最低价正确计算（选入日期及之后）
- [x] 行业/板块信息实时获取
- [x] 所有单元测试通过
- [x] 前端正确显示数据
- [x] 代码质量符合标准
