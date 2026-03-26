# TASK5 前端API集成修复

## 问题描述

前端在调用模拟交易API时返回404错误：
```
GET /api/trading/account/summary?account_id=default_account HTTP/1.1" 404
```

## 根本原因

trading蓝图没有在web_server.py中注册，导致Flask应用无法识别/api/trading路由。

## 解决方案

在web_server.py中添加trading蓝图的注册代码：

```python
# 注册trading蓝图
from trading.routes import trading_bp
app.register_blueprint(trading_bp, url_prefix='/api/trading')
logger.info("已注册trading蓝图")
```

## 修改文件

- **web_server.py**: 在策略加载后添加蓝图注册代码

## 验证步骤

1. 重启Web服务器
2. 在浏览器中访问模拟交易页面
3. 点击"模拟交易"菜单项
4. 验证账户总览页面能正确加载数据

## 预期结果

- ✓ GET /api/trading/account/summary 返回200状态码
- ✓ 账户总览页面显示账户信息
- ✓ 所有交易API正常工作

## 测试结果

修复后，API调用应该返回正确的数据：
```json
{
    "success": true,
    "data": {
        "account_id": "default_account",
        "total_assets": 1000000,
        "current_cash": 1000000,
        "total_profit": 0,
        "profit_rate": 0,
        "positions_count": 0
    }
}
```

---

**修复时间**: 2026-03-25  
**修复者**: Kiro  
**状态**: 已完成
