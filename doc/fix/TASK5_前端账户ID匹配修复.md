# TASK5 前端账户ID匹配修复

## 问题描述

前端在调用模拟交易API时返回400错误：
```
GET /api/trading/account/summary?account_id=default_account HTTP/1.1" 400
错误信息: 账户不存在
```

## 根本原因

**两个问题的组合**：

1. **账户ID不匹配**：
   - 前端使用的账户ID: `default_account`
   - 数据库初始化的账户ID: `ACC_DEFAULT`

2. **数据库路径错误**（主要问题）：
   - DAO使用的数据库: `stock_selection.db`
   - 应该使用的数据库: `trading.db`
   - 导致DAO查询的是错误的数据库，找不到账户

## 解决方案

### 修改1：更新初始化脚本
修改 `data/TradingInitData.sql` 中的默认账户ID：

```sql
-- 修改前
INSERT INTO trading_account (...) VALUES ('ACC_DEFAULT', ...)

-- 修改后
INSERT INTO trading_account (...) VALUES ('default_account', ...)
```

### 修改2：修复DAO数据库路径
修改 `trading/dao.py` 中的DB_PATH：

```python
# 修改前
DB_PATH = os.path.join(..., 'stock_selection.db')

# 修改后
DB_PATH = os.path.join(..., 'trading.db')
```

## 修改文件

- **data/TradingInitData.sql**: 将默认账户ID从 `ACC_DEFAULT` 改为 `default_account`
- **trading/dao.py**: 将DB_PATH从 `stock_selection.db` 改为 `trading.db`

## 验证步骤

1. 修改初始化脚本中的账户ID
2. 修改DAO中的数据库路径
3. 重新初始化数据库
4. 重启Web服务器
5. 运行所有API集成测试
6. 验证前端能正确加载账户总览

## 测试结果

✅ **所有18个API集成测试通过（100%）**

```
test/test_trading_routes.py::TestAccountSummaryAPI::test_get_account_summary_success PASSED
test/test_trading_routes.py::TestBuyAPI::test_buy_success PASSED
test/test_trading_routes.py::TestSellAPI::test_sell_success PASSED
test/test_trading_routes.py::TestPositionsAPI::test_get_positions_with_holdings PASSED
test/test_trading_routes.py::TestTransactionsAPI::test_get_transactions_with_data PASSED
test/test_trading_routes.py::TestAPIIntegration::test_complete_trading_flow PASSED
... (共18个测试全部通过)
```

## API验证

✅ **API调用成功**

```
Status: 200
Success: True
Account ID: default_account
Total Assets: 1000000.0
```

## 预期结果

✅ 前端API调用返回200状态码
✅ 账户总览页面正确显示账户信息
✅ 所有交易API正常工作

## 数据库验证

```
✓ 数据库初始化完成
✓ 账户数量: 1
  - 账户ID: default_account
  - 账户名: 默认账户
  - 初始资金: 1,000,000.0
```

---

**修复时间**: 2026-03-25  
**修复者**: Kiro  
**状态**: ✅ 已完成，所有测试通过，API正常工作

