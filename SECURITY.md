# 安全政策

## 报告安全漏洞

如果你发现了安全漏洞，请**不要**在公开的GitHub Issue中报告。

### 报告方式

请通过以下方式私密报告安全问题：

1. **GitHub Security Advisory**: 
   - 访问项目的 "Security" 标签页
   - 点击 "Report a vulnerability"
   - 填写漏洞详情

2. **电子邮件**: 
   - 发送至项目维护者邮箱
   - 主题行包含 `[SECURITY]` 标记

### 报告内容

请包含以下信息：

- 漏洞的详细描述
- 受影响的版本
- 复现步骤
- 潜在影响
- 建议的修复方案（如有）

## 安全最佳实践

### 配置文件安全

**不要**在代码中硬编码敏感信息：

```python
# ❌ 不要这样做
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=xxx"
API_KEY = "your-secret-key"

# ✅ 应该这样做
import os
from dotenv import load_dotenv

load_dotenv()
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK')
API_KEY = os.getenv('API_KEY')
```

### 环境变量配置

创建 `.env` 文件（**不要提交到Git**）：

```bash
# .env
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_SECRET=your-secret
DATABASE_URL=sqlite:///data/stock_selection.db
```

### .gitignore 配置

确保以下文件被忽略：

```
# 环境变量
.env
.env.local
.env.*.local

# 配置文件
config/config.yaml
config/github.yaml

# 数据文件
data/*.db
data/*.csv

# IDE
.vscode/
.idea/
*.swp
*.swo

# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/

# 日志
*.log
logs/
```

## 依赖安全

### 定期更新依赖

```bash
# 检查过期的依赖
pip list --outdated

# 更新所有依赖
pip install --upgrade -r requirements.txt

# 检查安全漏洞
pip install safety
safety check
```

### 依赖版本管理

在 `requirements.txt` 中指定版本范围：

```
# ✅ 推荐：指定最小版本
pandas>=1.3.0
numpy>=1.21.0

# ✅ 推荐：指定版本范围
requests>=2.25.0,<3.0.0
flask>=2.0.0,<3.0.0

# ❌ 不推荐：不指定版本
pandas
numpy
```

## 数据安全

### 股票数据

- 系统使用公开的A股数据源（akshare）
- 数据仅用于技术分析和选股
- 不涉及个人隐私信息

### 数据库

- SQLite数据库文件应排除在版本控制之外
- 定期备份数据库
- 不要在公开仓库中提交包含真实数据的数据库文件

## 代码安全

### SQL注入防护

使用参数化查询：

```python
# ❌ 不安全
query = f"SELECT * FROM stocks WHERE code = '{code}'"
db.execute(query)

# ✅ 安全
query = "SELECT * FROM stocks WHERE code = ?"
db.execute(query, (code,))
```

### 输入验证

验证所有用户输入：

```python
def validate_stock_code(code):
    """验证股票代码格式"""
    if not isinstance(code, str):
        raise ValueError("股票代码必须是字符串")
    
    if not code.isdigit() or len(code) != 6:
        raise ValueError("股票代码必须是6位数字")
    
    return code
```

### 错误处理

不要在错误消息中泄露敏感信息：

```python
# ❌ 不安全：泄露系统信息
try:
    result = db.query(sql)
except Exception as e:
    return {"error": str(e)}  # 可能包含SQL语句

# ✅ 安全：通用错误消息
try:
    result = db.query(sql)
except Exception as e:
    logger.error(f"Database error: {e}")
    return {"error": "数据库查询失败"}
```

## API安全

### Web服务器

```python
# 启用HTTPS
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# 添加安全头
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response
```

## 日志安全

不要在日志中记录敏感信息：

```python
# ❌ 不安全
logger.info(f"API Key: {api_key}")
logger.info(f"Webhook: {webhook_url}")

# ✅ 安全
logger.info("API Key configured")
logger.info("Webhook configured")
logger.debug(f"Webhook domain: {webhook_url.split('/')[2]}")
```

## 安全审计

### 定期检查

- 检查依赖的安全漏洞
- 审查代码中的敏感信息
- 验证配置文件的安全性
- 检查日志中的敏感数据

### 工具

```bash
# 检查Python安全问题
pip install bandit
bandit -r strategy/ utils/ web_server.py

# 检查依赖漏洞
pip install safety
safety check

# 代码质量检查
pip install pylint
pylint strategy/ utils/
```

## 版本支持

| 版本 | 支持状态 | 安全更新 |
|------|---------|---------|
| 1.0.x | ✅ 活跃 | 是 |
| 0.9.x | ⚠️ 维护 | 仅关键 |
| < 0.9 | ❌ 停止 | 否 |

## 安全更新流程

1. **发现漏洞** - 通过私密渠道报告
2. **确认漏洞** - 维护者验证和评估
3. **开发修复** - 在私密分支中修复
4. **测试修复** - 充分测试确保有效
5. **发布补丁** - 发布安全更新版本
6. **公开披露** - 发布安全公告

## 联系方式

- 📧 安全问题: [项目维护者邮箱]
- 🔒 GitHub Security: [项目地址]/security/advisories
- 📝 安全公告: [项目地址]/security/advisories

## 致谢

感谢所有报告安全问题的安全研究人员和用户。

---

**最后更新**: 2026-03-26
