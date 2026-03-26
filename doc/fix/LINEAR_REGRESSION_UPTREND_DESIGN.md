# 线性回归法上升趋势判断 - 详细设计方案

**设计日期**: 2026-03-21  
**方案**: 线性回归斜率 + 显著性检验  
**目标**: 使用统计学方法准确判断上升趋势

---

## 核心原理

### 线性回归基础
对最近20个交易日的收盘价进行线性回归分析：
- **X轴**: 交易日序号 (0, 1, 2, ..., 19)
- **Y轴**: 收盘价
- **拟合直线**: y = slope * x + intercept

### 判断标准

**条件1: 斜率为正** (slope > 0)
- 表示价格总体呈上升趋势
- 斜率越大，上升趋势越强

**条件2: 统计显著性** (p-value < 0.05)
- p-value < 0.05: 趋势显著，不是随机波动
- p-value >= 0.05: 趋势不显著，可能是随机波动

**条件3: 拟合度良好** (R² > 0.3)
- R² 表示直线对数据的拟合程度
- R² > 0.3: 拟合度良好，趋势明显
- R² <= 0.3: 拟合度差，数据波动大

### 综合判断
```
if slope > 0 AND p_value < 0.05 AND r_squared > 0.3:
    判定为上升趋势
else:
    判定为非上升趋势
```

---

## 算法优势

### 相比波峰波谷法
- ✅ 不依赖波峰波谷识别，避免识别错误
- ✅ 使用统计学方法，科学严谨
- ✅ 能有效过滤随机波动
- ✅ 对异常值有一定容错能力

### 相比均线法
- ✅ 不会滞后（直接使用原始数据）
- ✅ 能识别微弱趋势
- ✅ 参数少，易于调整

---

## 实现细节

### 1. 数据准备
```python
# 获取最近20日的收盘价
prices = df['close'].iloc[:20].values  # 从新到旧
prices = prices[::-1]  # 反转为从旧到新 (0-19)
```

### 2. 线性回归计算
```python
from scipy import stats

# X轴: 交易日序号
X = np.arange(len(prices))

# 线性回归
slope, intercept, r_value, p_value, std_err = stats.linregress(X, prices)

# 计算R²
r_squared = r_value ** 2
```

### 3. 判断逻辑
```python
# 判断条件
is_uptrend = (slope > 0) and (p_value < 0.05) and (r_squared > 0.3)
```

---

## 参数配置

在 `config/strategy_params.yaml` 中添加：

```yaml
trend_acceleration_inflection:
  # ... 其他参数 ...
  
  # 上升趋势判断参数（线性回归法）
  uptrend_lookback_days: 20          # 回看天数
  uptrend_slope_threshold: 0         # 斜率阈值（> 0 表示上升）
  uptrend_pvalue_threshold: 0.05     # p值阈值（< 0.05 表示显著）
  uptrend_rsquared_threshold: 0.3    # R²阈值（> 0.3 表示拟合度良好）
```

---

## 测试用例

### 测试1: 000498 (明显下跌)
- 20日收益率: -3.44%
- 预期: slope < 0，判定为非上升趋势 ✅

### 测试2: 000049 (小幅上升)
- 20日收益率: +5.03%
- 预期: slope > 0，p_value < 0.05，判定为上升趋势 ✅

### 测试3: 震荡股票
- 20日收益率: 接近0%
- 预期: slope ≈ 0 或 p_value >= 0.05，判定为非上升趋势 ✅

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

## 实现步骤

### 第一步: 修改 `_check_uptrend()` 方法
使用线性回归法替换波峰波谷法

### 第二步: 添加辅助方法
- `_calculate_linear_regression()`: 计算线性回归参数

### 第三步: 更新参数配置
在 `config/strategy_params.yaml` 中添加新参数

### 第四步: 单元测试
- 验证 000498 不再被判定为上升趋势
- 验证 000049 的判定是否正确
- 验证其他上升趋势股票的判定

### 第五步: 集成测试
- 运行 500 股票样本测试
- 验证上升趋势股票数量是否合理
- 验证选股漏斗的效果是否改善

---

## 代码框架

```python
def _check_uptrend(self, df) -> bool:
    """
    检查条件1：上升趋势（线性回归法）
    
    使用线性回归判断20日内的趋势方向
    """
    uptrend_days = self.params['uptrend_lookback_days']
    
    # 获取最近20日的数据
    uptrend_df = df.head(uptrend_days)
    
    if uptrend_df.empty or len(uptrend_df) < 3:
        return False
    
    # 计算线性回归
    slope, p_value, r_squared = self._calculate_linear_regression(
        uptrend_df['close'].values
    )
    
    # 判断条件
    slope_threshold = self.params['uptrend_slope_threshold']
    pvalue_threshold = self.params['uptrend_pvalue_threshold']
    rsquared_threshold = self.params['uptrend_rsquared_threshold']
    
    is_uptrend = (
        slope > slope_threshold and
        p_value < pvalue_threshold and
        r_squared > rsquared_threshold
    )
    
    return is_uptrend


def _calculate_linear_regression(self, prices):
    """
    计算线性回归参数
    
    参数:
        prices: 收盘价数组（从新到旧）
    
    返回:
        (slope, p_value, r_squared)
    """
    from scipy import stats
    import numpy as np
    
    # 反转为从旧到新
    prices = prices[::-1]
    
    # X轴: 交易日序号
    X = np.arange(len(prices))
    
    # 线性回归
    slope, intercept, r_value, p_value, std_err = stats.linregress(X, prices)
    
    # 计算R²
    r_squared = r_value ** 2
    
    return slope, p_value, r_squared
```

---

## 总结

### 方案特点
- ✅ 科学严谨（基于统计学）
- ✅ 准确性高（考虑显著性）
- ✅ 参数少（3个）
- ✅ 易于理解和调整

### 下一步
1. 确认此设计方案
2. 实施代码修改
3. 运行单元测试
4. 运行集成测试
5. 验收确认

---

**设计完成日期**: 2026-03-21  
**建议**: 立即实施此方案

