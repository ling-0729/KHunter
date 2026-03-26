# TASK 10: 多策略交集优先显示 - 需求设计说明书

## 问题陈述

**当前状态**：
- 用户使用OR逻辑执行多个策略选股时
- 前端显示结果，但没有优先显示被多个策略同时选中的股票
- 用户需要手动查找哪些股票被多个策略选中

**用户需求**：
- 在OR逻辑下，优先显示被多个策略同时选中的股票（交集股票）
- 交集股票应该单独分组显示，标记为"⭐ 多策略同时选中"
- 然后显示只被单个策略选中的股票

## 目标用户和核心用例

**目标用户**：量化选股系统的使用者

**核心用例**：
1. 用户选择多个策略（如碗口反弹 + 启明星）
2. 执行OR逻辑选股
3. 系统返回结果
4. **优先显示**被两个策略都选中的股票（交集）
5. 然后显示只被一个策略选中的股票

## 关键业务规则

1. **交集优先级**：被选中的策略数越多，优先级越高
   - 被2个策略选中 > 被1个策略选中
   - 被3个策略选中 > 被2个策略选中（如果有3个策略）

2. **显示分组**：
   - 第一组：被多个策略同时选中的股票（按策略数降序）
   - 第二组：只被单个策略选中的股票（按策略名称）

3. **标记方式**：
   - 交集股票：显示"⭐ 策略1 + 策略2"
   - 单个策略股票：显示"策略名"

## 技术方案

### 后端改动

**文件**：`web_server.py`

**改动点**：
1. `analyze_intersection()` 函数已经正确计算了交集
2. 返回的 `by_count` 字典包含了按交集数量分组的股票
3. 无需改动后端

### 前端改动

**文件**：`web/static/js/app.js`

**改动点**：
1. `renderSelectionResults()` 函数中的交集处理逻辑
2. 当前逻辑有问题：只从 `by_count` 中收集 `count > 1` 的股票
3. 需要改进：
   - 正确解析 `by_count` 中的股票代码
   - 按交集数量降序排列
   - 优先显示交集股票

**具体改动**：

```javascript
// 当前问题：by_count 中的值是对象数组，不是代码字符串
// by_count = {
//   '1': [{code: '600000', name: '浦发银行', ...}, ...],
//   '2': [{code: '600001', name: '邯郸钢铁', ...}, ...]
// }

// 改进方案：
// 1. 从 by_count 中提取所有 count > 1 的股票代码
// 2. 构建 intersectionSet
// 3. 优先显示交集股票，按 count 降序
```

## 实现步骤

### 第一步：修复前端交集处理逻辑

**目标**：正确从 `by_count` 中提取交集股票

**改动**：
```javascript
// 修改 renderSelectionResults 函数中的交集处理部分
// 从 by_count 中正确提取股票代码
const intersectionSet = new Set();
const byCountMap = (intersectionAnalysis && intersectionAnalysis.by_count) || {};

// 按交集数量降序排列（从大到小）
const sortedCounts = Object.keys(byCountMap)
    .map(Number)
    .sort((a, b) => b - a);  // 降序

// 收集所有 count > 1 的股票
for (const count of sortedCounts) {
    if (count > 1) {
        const stocks = byCountMap[count];
        if (Array.isArray(stocks)) {
            stocks.forEach(stock => {
                if (stock && stock.code) {
                    intersectionSet.add(stock.code);
                }
            });
        }
    }
}
```

### 第二步：优先显示交集股票

**目标**：在结果中优先显示交集股票

**改动**：
```javascript
// 在 renderSelectionResults 函数中
// 第一步：显示交集股票（按交集数量降序）
if (intersectionSet.size > 0) {
    // 按交集数量降序显示
    for (const count of sortedCounts) {
        if (count > 1) {
            const stocks = byCountMap[count];
            // 显示这个交集数量的所有股票
            // 标题：⭐ 被2个策略同时选中 (N只)
        }
    }
}

// 第二步：显示单个策略的股票
// 只显示不在交集中的股票
```

## 验收标准

1. ✓ 使用OR逻辑选股时，交集股票优先显示
2. ✓ 交集股票按交集数量降序排列
3. ✓ 交集股票标记为"⭐ 被N个策略同时选中"
4. ✓ 单个策略的股票在交集股票之后显示
5. ✓ 前端正确解析后端返回的 `by_count` 数据
6. ✓ 所有测试通过

## 开发计划

| 步骤 | 任务 | 预计时间 |
|------|------|--------|
| 1 | 修复前端交集处理逻辑 | 30分钟 |
| 2 | 测试交集显示效果 | 20分钟 |
| 3 | 验收确认 | 10分钟 |

**总计**：约1小时

## 相关文件

- `web/static/js/app.js` - 前端选股结果渲染
- `web_server.py` - 后端交集分析（无需改动）
- `logs/app.log` - 调试日志

