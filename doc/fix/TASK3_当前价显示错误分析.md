# TASK 3: 当前价显示错误分析

## 问题描述

前端持仓列表中显示的"当前价"和"成本价"不对：
- 000001 平安银行：显示当前价 ¥10.80（应该是 ¥10.94），成本价 ¥10.85（数据库中是 10.8471）
- 000002 平安银行：显示当前价 ¥4.10（应该是 ¥4.12），成本价 ¥4.10

## 问题分析

### 数据流

1. **前端请求** → `/api/trading/positions/{account_id}`
2. **后端处理** → `TradingService.get_positions()`
3. **获取实时价格** → `StockHelper.get_price_range(stock_code)`
4. **返回给前端** → 包含 `current_price` 字段

### 可能的问题

#### 问题 1：StockHelper.get_price_range() 返回的 current_price 不是实时价格

**现象**：
- 腾讯财经接口返回的数据中，`parts[3]` 可能不是当前价
- 或者接口返回的数据格式已变更

**验证方法**：
```python
# 直接调用 API 查看返回数据
import requests
code = "000001"
query_code = f"sz{code}"
url = f"https://qt.gtimg.cn/q={query_code}"
resp = requests.get(url, timeout=10, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})
resp.encoding = 'gbk'
print(resp.text)
```

#### 问题 2：前端缓存了旧的当前价

**现象**：
- 前端显示的是上次查询时的价格
- 没有实时更新

**验证方法**：
- 检查前端 JavaScript 代码中是否有缓存逻辑
- 查看 API 响应中的 `current_price` 值

#### 问题 3：数据库中的 current_price 没有更新

**现象**：
- `TradingService.get_positions()` 中更新数据库的逻辑可能失败
- 返回的是数据库中的旧价格

**验证方法**：
- 检查数据库中 `trading_position` 表的 `current_price` 字段
- 查看是否有异常日志

## 修复方案

### 方案 1：验证腾讯财经接口数据格式

**步骤**：
1. 编写测试脚本验证接口返回的数据格式
2. 确认 `parts[3]` 是否为当前价
3. 如果格式变更，更新解析逻辑

**代码**：
```python
# test/test_stock_helper_price.py
import requests

def test_tencent_api_format():
    """测试腾讯财经 API 返回的数据格式"""
    code = "000001"
    query_code = f"sz{code}"
    url = f"https://qt.gtimg.cn/q={query_code}"
    
    resp = requests.get(url, timeout=10, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    resp.encoding = 'gbk'
    
    print(f"Response: {resp.text}")
    
    # 解析数据
    parts = resp.text.strip().split('~')
    print(f"Total parts: {len(parts)}")
    
    # 打印关键字段
    if len(parts) > 35:
        print(f"parts[1] (name): {parts[1]}")
        print(f"parts[3] (current_price?): {parts[3]}")
        print(f"parts[4] (yesterday_close?): {parts[4]}")
        print(f"parts[5] (open_price?): {parts[5]}")
        print(f"parts[33] (high_price?): {parts[33]}")
        print(f"parts[34] (low_price?): {parts[34]}")
```

### 方案 2：增强错误处理和日志

**修改 `StockHelper.get_price_range()`**：
- 添加详细的日志记录
- 验证返回的价格数据有效性
- 添加备用数据源

**代码**：
```python
@staticmethod
def get_price_range(code: str) -> Optional[Dict[str, Any]]:
    """获取股票当天的价格区间"""
    try:
        # ... 现有代码 ...
        
        # 添加日志
        import logging
        logger = logging.getLogger(__name__)
        
        if resp.status_code == 200:
            text = resp.text.strip()
            if '~' in text:
                parts = text.split('~')
                
                # 添加调试日志
                logger.debug(f"Stock {code}: parts count = {len(parts)}")
                if len(parts) > 35:
                    logger.debug(f"Stock {code}: parts[3] = {parts[3]}, parts[33] = {parts[33]}, parts[34] = {parts[34]}")
                
                # ... 现有解析逻辑 ...
```

### 方案 3：前端实时更新

**修改前端 JavaScript**：
- 确保每次请求都获取最新数据
- 不使用缓存
- 定期刷新价格

**代码**：
```javascript
// web/static/js/trading.js
function loadPositions() {
    // 添加时间戳防止缓存
    const timestamp = new Date().getTime();
    
    fetch(`/api/trading/positions/${accountId}?t=${timestamp}`, {
        method: 'GET',
        headers: {
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 更新表格
            updatePositionsTable(data.data.positions);
        }
    });
}
```

## 建议的修复步骤

1. **第一步**：运行测试脚本验证腾讯财经 API 的数据格式
2. **第二步**：如果格式变更，更新 `StockHelper.get_price_range()` 的解析逻辑
3. **第三步**：添加详细的日志记录，便于调试
4. **第四步**：测试前端是否正确显示最新价格
5. **第五步**：如果问题仍存在，考虑使用其他数据源

## 问题根源（已确认）

通过数据库查询发现：
- `default_account` 账户的 000001 持仓：
  - 数量：5100 股
  - 成本价：10.8471（数据库中的值）
  - 当前价：10.8（数据库中的值，应该是 10.94）
  - 市值：55,080
  - 收益：-240.21

- `default_account` 账户的 000002 持仓：
  - 数量：500 股
  - 成本价：4.1（数据库中的值）
  - 当前价：4.1（数据库中的值，应该是 4.12）
  - 市值：2,050
  - 收益：0

**根本原因**：`TradingService.get_positions()` 中的 `update_position()` 调用失败，导致数据库中的 `current_price` 没有被更新为最新的市场价格。

### 代码问题

在 `trading/service.py` 的 `get_positions()` 方法中：

```python
try:
    price_range = StockHelper.get_price_range(position['stock_code'])
    if price_range and price_range.get('current_price'):
        current_price = price_range['current_price']
        # 更新数据库中的当前价格
        self.position_dao.update_position(
            position_id=position['position_id'],
            quantity=position['quantity'],
            cost_price=position['cost_price'],
            current_price=current_price,
            last_buy_date=position['last_buy_date']
        )
        position['current_price'] = current_price
except Exception as e:
    # 如果获取最新价格失败，使用数据库中的价格
    pass  # ← 异常被吞掉了，没有日志！
```

**问题**：
1. 异常被吞掉，无法调试
2. 即使 `update_position()` 失败，也没有任何提示
3. 前端显示的是数据库中的旧价格

## 修复方案

### 方案 1：添加日志记录（推荐）

修改 `trading/service.py` 的 `get_positions()` 方法，添加日志记录：

```python
import logging

logger = logging.getLogger(__name__)

def get_positions(self, account_id: str) -> Dict:
    # ... 现有代码 ...
    
    for position in positions:
        try:
            price_range = StockHelper.get_price_range(position['stock_code'])
            if price_range and price_range.get('current_price'):
                current_price = price_range['current_price']
                
                # 更新数据库中的当前价格
                update_result = self.position_dao.update_position(
                    position_id=position['position_id'],
                    quantity=position['quantity'],
                    cost_price=position['cost_price'],
                    current_price=current_price,
                    last_buy_date=position['last_buy_date']
                )
                
                if update_result:
                    position['current_price'] = current_price
                    logger.debug(f"Updated position {position['position_id']} current_price to {current_price}")
                else:
                    logger.warning(f"Failed to update position {position['position_id']} current_price")
        except Exception as e:
            logger.error(f"Error updating position {position['position_id']}: {str(e)}")
```

### 方案 2：确保返回最新价格

即使数据库更新失败，也要返回最新的价格给前端：

```python
for position in positions:
    try:
        price_range = StockHelper.get_price_range(position['stock_code'])
        if price_range and price_range.get('current_price'):
            current_price = price_range['current_price']
            
            # 尝试更新数据库
            try:
                self.position_dao.update_position(...)
            except Exception as e:
                logger.error(f"Failed to update DB: {e}")
            
            # 无论数据库是否更新成功，都使用最新价格
            position['current_price'] = current_price
    except Exception as e:
        logger.error(f"Error getting price: {e}")
```

## 下一步

1. 添加日志记录，找出 `update_position()` 失败的原因
2. 修复 `update_position()` 的问题
3. 确保即使数据库更新失败，前端也能显示最新价格
4. 运行测试验证修复
