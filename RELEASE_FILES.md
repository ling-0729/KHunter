# 发布文件清单

## 需要发布的文件和目录

### 核心目录
- `config/` - 配置文件目录
- `data/` - 数据库脚本目录
- `image/` - 图片资源目录
- `stock_analyzer/` - 股票分析器模块
- `strategy/` - 策略实现目录
- `trading/` - 交易相关代码目录
- `utils/` - 工具类目录
- `web/` - 前端文件目录

### 根目录文件
- `README.md` - 项目说明文件（含Logo和系统截图）
- `RELEASE_NOTES.md` - 版本发布说明
- `RELEASE_FILES.md` - 发布文件清单
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
- `config/database.yaml` - 数据库配置
- `config/risk_config.yaml` - 风险控制配置
- `config/strategy_kelly_config.yaml` - 凯利公式配置
- `config/strategy_name_mapping.yaml` - 策略名称映射
- `config/support_methods.yaml` - 支撑位计算方法
- `config/pool_removal_config.yaml` - 股票池移除配置
- `config/continuous_temp_risk.yaml` - 连续温度风险配置（新增）

### 数据库脚本
- `data/DataSql.sql` - 数据库结构脚本
- `data/InitData.sql` - 初始化数据脚本（如有）

### 图片资源
- `image/imp.jpeg` - 系统界面截图

### 策略文件
- `strategy/*.py` - 所有策略实现文件（15个选股策略）
  - `strategy/base_strategy.py` - 策略基类
  - `strategy/bottom_trend_inflection.py` - 底部趋势拐点
  - `strategy/limit_up_pullback_strategy.py` - 涨停回马枪
  - `strategy/limit_up_sideways_strategy.py` - 涨停横盘
  - `strategy/morning_star.py` - 启明星策略
  - `strategy/multi_golden_cross.py` - 多金叉共振
  - `strategy/multi_party_cannon.py` - 多方炮策略
  - `strategy/immortal_guidance_strategy.py` - 仙人指路
  - `strategy/resistance_breakout.py` - 阻力位突破
  - `strategy/strong_wash_weak_to_strong.py` - 强势洗盘弱转强
  - `strategy/trend_acceleration_inflection.py` - 趋势加速拐点
  - `strategy/trend_start_strategy.py` - 趋势起点策略
  - `strategy/w_bottom_strategy.py` - W底策略
  - `strategy/strategy_2560_selection.py` - 2560战法
  - `strategy/golden_triangle_strategy.py` - 金三角策略（新增）
  - `strategy/golden_cross_not_green.py` - 金叉不绿策略（新增）
- `strategy/parallel_strategy_executor.py` - 并行策略执行器
- `strategy/strategy_registry.py` - 策略注册表

### 股票分析器文件
- `stock_analyzer/*.py` - 所有股票分析器模块
  - `stock_analyzer/data_fetcher.py` - 数据获取
  - `stock_analyzer/technical_analyzer.py` - 技术分析
  - `stock_analyzer/fundamental_analyzer.py` - 基本面分析
  - `stock_analyzer/sector_analyzer.py` - 行业分析
  - `stock_analyzer/fund_flow_analyzer.py` - 资金流分析
  - `stock_analyzer/event_analyzer.py` - 事件分析
  - `stock_analyzer/report_generator.py` - 报告生成

### 交易相关文件
- `trading/*.py` - 所有交易相关代码
  - `trading/strategy_runner.py` - 策略运行器
  - `trading/backtest_engine.py` - 回测引擎
  - `trading/backtest_dao.py` - 回测数据访问
  - `trading/backtest_batch_queue.py` - 批量回测队列
  - `trading/backtest_scorer.py` - 回测评分器
  - `trading/bollinger_strategy.py` - 布林带策略
  - `trading/rsi_strategy.py` - RSI策略
  - `trading/support_strategy.py` - 支撑位策略
  - `trading/turtle_strategy.py` - 海龟策略
  - `trading/macd_bollinger_strategy.py` - 顺势宝策略
  - `trading/timing_strategies.py` - 择时策略集合
  - `trading/khunter_api.py` - 狩猎场API
  - `trading/khunter_dao.py` - 狩猎场数据访问
  - `trading/stock_score_api.py` - 股票评分API
  - `trading/stock_score_calculator.py` - 股票评分计算
  - `trading/retry_handler.py` - API重试处理
  - `trading/structured_logger.py` - 结构化日志器
  - `trading/trading_plan_generator.py` - 交易计划生成
  - `trading/strategy_kelly_loader.py` - 凯利公式加载器
  - `trading/vectorbt_backtest_engine.py` - VectorBT回测引擎
  - `trading/vectorbt_strategies.py` - VectorBT策略定义
- `trading/ptrade/` - PTrade自动交易模块（新增）
  - `trading/ptrade/__init__.py` - 包初始化
  - `trading/ptrade/khunter_auto_trade.py` - KHunter自动交易主程序
  - `trading/ptrade/ptrade_feedback.py` - PTrade交易反馈
  - `trading/ptrade/ptradesample.py` - PTrade接入示例

### 工具类文件
- `utils/*.py` - 所有工具类文件
  - `utils/log_config.py` - 日志配置与自动清理
  - `utils/risk_manager.py` - 风险管理
  - `utils/risk_controller.py` - 风险控制器
  - `utils/var_calculator.py` - VaR计算器
  - `utils/risk_config_loader.py` - 风险配置加载器
  - `utils/akshare_fetcher.py` - AKShare数据获取
  - `utils/kline_fetcher.py` - K线数据获取
  - `utils/kline_updater.py` - K线数据更新
  - `utils/kline_initializer.py` - K线数据初始化
  - `utils/data_initializer.py` - 数据初始化器
  - `utils/data_collection_service.py` - 数据采集服务
  - `utils/feature_config_checker.py` - 配置文件检测
  - `utils/continuous_temp_risk.py` - 连续温度风险（新增）
  - `utils/date_utils.py` - 日期工具类（新增）
  - `utils/exdividend_utils.py` - 除权除息检测工具
  - `utils/stock_data_fetcher.py` - 股票数据获取器
  - `utils/new_stock_detector.py` - 新股检测器
  - `utils/crypto_utils.py` - 加密工具
  - `utils/strategy_name_mapper.py` - 策略名称映射
  - `utils/trade_date_utils.py` - 交易日历工具
  - `utils/trading_time_validator.py` - 交易时间验证

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
- `web/static/js/dashboard_stats.js` - 看板统计

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
- `web/static/js/modules/execution-plan.js` - 执行计划
- `web/static/js/modules/market_temperature.js` - 市场温度
- `web/static/js/modules/money_flow.js` - 资金流向
- `web/static/js/modules/risk.js` - 风险控制
- `web/static/js/modules/strategy-runner.js` - 策略运行器

#### 静态资源 - 图片
- `web/static/images/logo.svg` - 系统Logo
- `web/static/images/favicon.svg` - 网站图标
- `web/static/images/logo-preview.html` - Logo预览页面

## 不需要发布的文件

### 临时文件和目录
- `logs/` - 日志目录（运行时自动创建）
- `__pycache__/` - Python缓存目录
- `*.pyc` - 编译后的Python文件
- `.coverage` - 测试覆盖率文件

### 数据库文件
- `stock_selection.db` - 本地数据库文件（运行时自动创建）
- `trading_data.db` - 交易数据库文件（运行时自动创建）

### 测试文件
- `test/` - 测试目录
- `test_*.py` - 测试脚本
- `_*.py` - 临时脚本（下划线开头）

### 敏感配置文件（不发布）
- `config/config.yaml` - 本地配置（含API密钥）
- `config/87659999.json` - 加密配置文件
- `config/87659999_decrypted.json` - 解密配置文件
- `config/tushare_config.json` - Tushare API配置（含Token）
- `config/config_files_info.json` - 配置信息文件

### IDE配置文件
- `.kiro/` - Kiro IDE配置
- `.vscode/` - VS Code配置
- `.git/` - Git版本控制目录
- `.pytest_cache/` - Pytest缓存
- `.trae/` - Trae IDE配置
- `.codebuddy/` - CodeBuddy配置

### 其他临时文件
- `*.log` - 日志文件
- `*.bak` - 备份文件
- `*.swp` - Vim交换文件
- `*.tmp` - 临时文件
- `*.zip` - 压缩包文件
- `*.mp4` - 视频文件
- `*.pptx` - 演示文稿
- `venv/` - Python虚拟环境目录

## 发布检查清单

### 前端功能验证
- [ ] 页面导航菜单正常工作
- [ ] 所有JavaScript模块正确加载
- [ ] CSS样式表完整
- [ ] 图片资源完整（Logo、Favicon、系统截图）
- [ ] 数据加载显示正确（暂无数据vs加载中）
- [ ] 所有API端点可访问
- [ ] 策略运行器菜单显示正常（有配置文件时）
- [ ] 数据更新进度状态正确显示

### 后端功能验证
- [ ] 数据库初始化脚本完整
- [ ] 所有Python依赖已列出
- [ ] 配置文件模板正确
- [ ] 策略实现完整（15个选股策略）
- [ ] 择时策略完整（5个）
- [ ] 金三角策略功能正常（新增）
- [ ] PTrade自动交易模块正常（新增）
- [ ] 除权检测功能正常
- [ ] 风险控制模块完整
- [ ] 策略运行器功能正常

### 文档完整性
- [ ] README.md包含完整说明（含Logo、系统截图、五维度评分体系详解）
- [ ] RELEASE_NOTES.md版本信息更新
- [ ] RELEASE_FILES.md发布清单完整
- [ ] 安装和使用指南清晰

## 发布版本信息

**发布日期**: 2026-06-19
**版本**: 1.5.0
**状态**: 生产就绪

### v1.5.0 版本更新内容

#### 新增策略
- **选股策略**：金三角策略（GoldenTriangleStrategy）、金叉不绿策略（GoldenCrossNotGreen）
#### 新增功能模块
- **PTrade自动交易**：集成PTrade交易平台，支持自动交易闭环（`trading/ptrade/`目录）
  - KHunter自动交易主程序
  - PTrade交易反馈机制
  - PTrade接入示例代码
- **连续温度风险**：基于市场温度的连续风险监控（`utils/continuous_temp_risk.py`）
- **日期工具类**：统一的日期处理工具（`utils/date_utils.py`）
- **除权检测**：K线数据除权检测与自动修复

#### 新增配置文件
- `config/continuous_temp_risk.yaml` - 连续温度风险配置

#### 技术优化
- 数据源切换至 TickFlow 免费批量 API
- K线初始化改为批量 TickFlow + 腾讯财经降级
- 科创板(688) volume 单位统一为「手」
- 全面修复策略中的未来函数问题
- 修复停牌检查逻辑，区分交易日和非交易日
- 数据更新状态前端修复（数据源未就绪时正确结束）
- 策略运行器修复：持仓文件名搜索使用 today 而非 working_date
- 初始化数据默认获取3年K线（原1年）
- 自动补充温度数据最多5天

### v1.4.0 (2026-05-26) 历史版本
- 新增趋势起点策略、2560战法
- 新增顺势宝策略（MACD金叉 + 布林带）
- 新增风险控制模块
- 新增策略运行器
- 新增日志管理
