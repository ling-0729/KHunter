# 发布文件清单

## 需要发布的文件和目录

### 核心目录
- `config/` - 配置文件目录
- `doc/` - 文档目录
- `strategy/` - 策略实现目录
- `trading/` - 交易相关代码目录
- `utils/` - 工具类目录
- `web/` - 前端文件目录

### 根目录文件
- `README.md` - 项目说明文件
- `RELEASE_NOTES.md` - 版本发布说明
- `LICENSE` - 许可证文件
- `CODE_OF_CONDUCT.md` - 行为准则
- `CONTRIBUTING.md` - 贡献指南
- `SECURITY.md` - 安全说明
- `requirements.txt` - 依赖文件
- `main.py` - 主脚本
- `web_server.py` - Web服务器脚本
- `start.bat` - 启动脚本

### 配置文件
- `config/config.yaml.template` - 配置模板
- `config/strategy_params.yaml` - 策略参数配置
- `config/strategy_order.yaml` - 策略排序配置
- `config/strategy_weights.json` - 策略权重配置
- `config/data_sources.json` - 数据源配置

### 文档文件
- `doc/GitHub开源资料清单.md`
- `doc/项目来源说明.md`
- `doc/策略列表.md`
- `doc/*策略说明书.md` - 各种策略的说明书

### 策略文件
- `strategy/*.py` - 所有策略实现文件

### 交易相关文件
- `trading/*.py` - 所有交易相关代码

### 工具类文件
- `utils/*.py` - 所有工具类文件
- `utils/data_sources/` - 数据源目录

### 前端文件

#### 模板文件
- `web/templates/index.html` - 主页面模板

#### 静态资源 - CSS
- `web/static/css/style.css` - 主样式表
- `web/static/css/khunter.css` - KHunter特定样式

#### 静态资源 - JavaScript (根级)
- `web/static/js/app.js` - 应用主入口
- `web/static/js/kline_chart.js` - K线图表功能
- `web/static/js/data_update.js` - 数据更新功能
- `web/static/js/data_update_simple.js` - 简化数据更新
- `web/static/js/init_simple.js` - 简化初始化
- `web/static/js/selection_history.js` - 选股历史
- `web/static/js/trading.js` - 交易功能
- `web/static/js/error_handler.js` - 错误处理
- `web/static/js/retry_policy.js` - 重试策略

#### 静态资源 - JavaScript 模块 (modules/)
- `web/static/js/modules/navigation.js` - 页面导航
- `web/static/js/modules/stocks.js` - 股票相关功能
- `web/static/js/modules/selection.js` - 选股功能
- `web/static/js/modules/analysis.js` - 分析功能
- `web/static/js/modules/strategies.js` - 策略配置
- `web/static/js/modules/history.js` - 历史记录
- `web/static/js/modules/ranking.js` - 排名功能
- `web/static/js/modules/utils.js` - 工具函数
- `web/static/js/modules/websocket.js` - WebSocket连接
- `web/static/js/modules/khunter.js` - KHunter狩猎功能
- `web/static/js/modules/backtest.js` - 回测功能
- `web/static/js/modules/backtest-batch.js` - 批量回测
- `web/static/js/modules/backtest-executor.js` - 回测执行器
- `web/static/js/modules/backtest-api.js` - 回测API
- `web/static/js/modules/backtest-error-handler.js` - 回测错误处理
- `web/static/js/modules/backtest-performance.js` - 回测性能
- `web/static/js/modules/backtest-utils.js` - 回测工具
- `web/static/js/modules/backtest-ux.js` - 回测用户体验

#### 静态资源 - 图片
- `web/static/images/logo.svg` - 系统Logo
- `web/static/images/favicon.svg` - 网站图标
- `web/static/images/logo-preview.html` - Logo预览页面

## 不需要发布的文件

### 临时文件和目录
- `logs/` - 日志目录
- `__pycache__/` - Python缓存目录
- `*.pyc` - 编译后的Python文件
- `.coverage` - 测试覆盖率文件

### 数据库文件
- `stock_selection.db` - 本地数据库文件

### 测试文件
- `test/` - 测试目录

### IDE配置文件
- `.kiro/` - Kiro IDE配置
- `.vscode/` - VS Code配置

### 其他临时文件
- `*.log` - 日志文件
- `*.bak` - 备份文件
- `*.swp` - Vim交换文件
- `*.tmp` - 临时文件

## 发布检查清单

### 前端功能验证
- [x] 页面导航菜单正常工作
- [x] 所有JavaScript模块正确加载
- [x] CSS样式表完整
- [x] 图片资源完整（Logo、Favicon）
- [x] 数据加载显示正确（暂无数据vs加载中）
- [x] 所有API端点可访问

### 后端功能验证
- [ ] 数据库初始化脚本完整
- [ ] 所有Python依赖已列出
- [ ] 配置文件模板正确
- [ ] 策略实现完整

### 文档完整性
- [x] README.md包含完整说明（含股票评分系统详解）
- [ ] 所有策略说明书已包含
- [ ] 安装和使用指南清晰

## 发布版本信息

**发布日期**: 2026-04-17
**版本**: 1.0.0
**状态**: 准备发布

### 最近修复
- 修复前端加载状态显示（最热行业、最热板块）
- 补充完整的JavaScript模块文件到release目录
- 更新发布文件清单
- 增强README文档，添加股票评分系统详细说明（五维度评分体系、计算过程、评分等级、各维度详解、一票否决条件、狩猎场使用流程）
