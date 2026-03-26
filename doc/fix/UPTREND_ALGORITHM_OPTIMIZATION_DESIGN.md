# 上升趋势判断算法优化设计方案

**设计日期**: 2026-03-21  
**目标**: 优化上升趋势判断算法，提高准确性  
**当前问题**: 000498 等股票虽然下跌但被判定为上升趋势

---

## 优化方案对比

### 方案 1: 基于移动平均线的上升趋势判断

**原理**: 使用多条移动平均线判断趋势方向

**判断标准**:
1. 短期MA (5日) > 中期MA (10日) > 长期MA (20日)
2. 最新收盘价 > 短期MA (5日)
3. 最近3日收盘价都 > 20日MA

**优点**:
- 简单直观
- 避免波峰波谷识别的复杂性
- 能有效过滤虚假上升趋势

**缺点**:
- 可能滞后
- 需要调整MA周期参数

**代码示例**:
```python
def _check_uptrend_v1(self, df) -> bool:
    if len(df) < 20:
        return False
    
    # 计算移动平均线
    ma5 = df['close'].iloc[:5].mean()
    ma10 = df['close'].iloc[:10].mean()
    ma20 = df['close'].iloc[:20].mean()
    
    # 检查MA排列
    if not (ma5 > ma10 > ma20):
        return False
    
    # 检查最新价格
    latest_close = df.iloc[0]['close']
    if latest_close <= ma5:
        return False
    
    # 检查最近3日都在MA20之上
    recent_3 = df.iloc[:3]['close']
    if (recent_3 > ma20).sum() < 3:
        return False
    
    return True
```

---

### 方案 2: 基于价格位置的上升趋势判断

**原理**: 检查最新价格在20日范围内的位置

**判断标准**:
1. 最新收盘价 > 20日平均价格
2. 最新收盘价 > 20日最低价格 + (20日最高价 - 20日最低价) * 0.3
3. 最近5日平均价格 > 前5日平均价格
4. 最新价格 > 10日平均价格

**优点**:
- 直观易懂
- 能有效判断价格位置
- 避免复杂的波峰波谷识别

**缺点**:
- 需要调整多个参数
- 可能对震荡市场敏感

**代码示例**:
```python
def _check_uptrend_v2(self, df) -> bool:
    if len(df) < 20:
        return False
    
    # 获取20日数据
    df_20 = df.iloc[:20]
    latest_close = df.iloc[0]['close']
    
    # 检查1: 最新价格 > 20日平均价格
    ma20 = df_20['close'].mean()
    if latest_close <= ma20:
        return False
    
    # 检查2: 最新价格在20日范围的上半部分
    high_20 = df_20['high'].max()
    low_20 = df_20['low'].min()
    threshold = low_20 + (high_20 - low_20) * 0.3
    if latest_close <= threshold:
        return False
    
    # 检查3: 最近5日平均 > 前5日平均
    recent_5_avg = df.iloc[:5]['close'].mean()
    prev_5_avg = df.iloc[5:10]['close'].mean()
    if recent_5_avg <= prev_5_avg:
        return False
    
    # 检查4: 最新价格 > 10日平均
    ma10 = df.iloc[:10]['close'].mean()
    if latest_close <= ma10:
        return False
    
    return True
```

---

### 方案 3: 基于趋势强度的上升趋势判断

**原理**: 综合考虑价格、成交量、趋势强度

**判断标准**:
1. 最新收盘价 > 20日平均价格
2. 最新收盘价 > 20日最低价格
3. 最近10日中，上升日 > 下降日
4. 最近10日的最高价 > 前10日的最高价
5. 最新成交量 > 20日平均成交量 * 0.8

**优点**:
- 综合多个因素
- 能有效判断趋势强度
- 避免虚假信号

**缺点**:
- 逻辑复杂
- 需要调整多个参数

**代码示例**:
```python
def _check_uptrend_v3(self, df) -> bool:
    if len(df) < 20:
        return False
    
    # 检查1: 最新价格 > 20日平均
    ma20 = df.iloc[:20]['close'].mean()
    latest_close = df.iloc[0]['close']
    if latest_close <= ma20:
        return False
    
    # 检查2: 最新价格 > 20日最低
    low_20 = df.iloc[:20]['low'].min()
    if latest_close <= low_20:
        return False
    
    # 检查3: 最近10日上升日 > 下降日
    recent_10 = df.iloc[:10]
    up_days = 0
    for i in range(len(recent_10) - 1):
        if recent_10.iloc[i]['close'] > recent_10.iloc[i + 1]['close']:
            up_days += 1
    if up_days <= 5:
        return False
    
    # 检查4: 最近10日最高 > 前10日最高
    high_recent_10 = df.iloc[:10]['high'].max()
    high_prev_10 = df.iloc[10:20]['high'].max()
    if high_recent_10 <= high_prev_10:
        return False
    
    # 检查5: 最新成交量 > 20日平均 * 0.8
    latest_volume = df.iloc[0]['volume']
    avg_volume_20 = df.iloc[:20]['volume'].mean()
    if latest_volume < avg_volume_20 * 0.8:
        return False
    
    return True
```

---

## 方案对比表

| 方案 | 复杂度 | 准确性 | 参数数量 | 推荐度 |
|------|--------|--------|----------|--------|
| 方案1 (MA排列) | 低 | 中 | 3 | ⭐⭐⭐⭐ |
| 方案2 (价格位置) | 中 | 中高 | 4 | ⭐⭐⭐ |
| 方案3 (趋势强度) | 高 | 高 | 5 | ⭐⭐⭐⭐⭐ |

---

## 推荐方案

**推荐: 方案 1 + 方案 2 的混合**

结合两个方案的优点：
1. 使用 MA 排列判断基本趋势方向
2. 使用价格位置判断趋势强度
3. 简单易懂，参数少

**混合方案的判断标准**:
1. 短期MA (5日) > 中期MA (10日) > 长期MA (20日)
2. 最新收盘价 > 20日平均价格
3. 最新收盘价 > 20日最低价格 + (20日最高价 - 20日最低价) * 0.25
4. 最近5日平均价格 > 前5日平均价格

---

## 实施计划

### 第一步: 确认优化方案

选择以下方案之一：
- 方案 1: 基于 MA 排列
- 方案 2: 基于价格位置
- 方案 3: 基于趋势强度
- 混合方案: 方案 1 + 方案 2

### 第二步: 修改代码

修改 `_check_uptrend()` 方法，实现新的判断逻辑

### 第三步: 添加参数

在 `config/strategy_params.yaml` 中添加新的参数：
- `uptrend_ma_short`: 短期MA周期 (默认 5)
- `uptrend_ma_mid`: 中期MA周期 (默认 10)
- `uptrend_ma_long`: 长期MA周期 (默认 20)
- `uptrend_price_threshold`: 价格位置阈值 (默认 0.25)

### 第四步: 单元测试

添加新的单元测试用例，验证：
- 000498 不再被判定为上升趋势
- 000049 的判定是否正确
- 其他上升趋势股票的判定

### 第五步: 集成测试

运行 500 股票样本测试，验证：
- 上升趋势的股票数量是否合理
- 选股漏斗的效果是否改善

---

## 预期效果

### 修复前
- 上升趋势股票: 15 只 (包括错误的 000498)
- 步骤2 通过: 0 只
- 最终选股: 0 只

### 修复后 (预期)
- 上升趋势股票: 8-12 只 (去除虚假信号)
- 步骤2 通过: 1-3 只
- 最终选股: 0-1 只

---

## 总结

### 优化目标
- ✅ 提高上升趋势判断的准确性
- ✅ 去除虚假的上升趋势信号
- ✅ 简化判断逻辑

### 推荐方案
- 混合方案 (方案 1 + 方案 2)
- 简单易懂，参数少
- 准确性高

### 下一步
- 确认优化方案
- 实施代码修改
- 运行测试验证

---

**设计完成日期**: 2026-03-21  
**建议**: 采用混合方案，立即实施优化
