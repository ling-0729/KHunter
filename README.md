# KHunter - 专注技术形态识别的量化选股工具

**一个完整的A股量化选股解决方案**，集数据获取、策略分析、选股执行、交易模拟于一体。支持多种（可扩展）选股策略，可灵活组合使用，帮助投资者快速发现投资机会。


## ✨ 核心优势

### 🎯 多维度选股
- **11种选股策略** - 覆盖底部反转、趋势加速、形态突破等多个维度
- **策略灵活组合** - 支持多策略OR/AND逻辑组合，精准捕捉投资机会

### 📊 完整的数据支持
- **5000+只A股数据** - 覆盖全市场股票，支持6年历史数据回溯
- **智能数据更新** - 自动判断更新时机，避免不必要的网络请求
- **多层降级机制** - 确保数据获取的稳定性和可用性

### 🌐 可视化管理界面
- **Web管理系统** - 实时查看股票数据、执行选股、分析结果
- **K线图可视化** - 为每只入选股票生成K线图，直观展示技术形态
- **策略参数配置** - 在线修改策略参数，无需重启系统

### 💼 交易模拟系统
- **虚拟账户管理** - 支持多账户、自定义初始资金
- **完整交易流程** - 模拟真实交易，包括买入、卖出、持仓、收益计算
- **交易记录追踪** - 完整的交易历史和收益分析

### 🚀 开箱即用
- **一键启动** - 简单的命令行接口，快速开始选股
- **自动风险过滤** - 自动排除ST股、退市股等风险股票
- **完善的文档** - 详细的策略说明和使用指南
### 环境要求
- Python 3.8+
- pip 或 conda

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/ling-0729/KHunter.git
cd KHunter

# 2. 安装依赖
pip install -r requirements.txt

# 3. 首次全量抓取数据（6年历史数据）
python main.py init

# 5. 启动Web界面
python main.py web
```

访问 `http://localhost:5000` 查看Web界面。

## 📊 11种选股策略

| # | 策略名称 | 核心逻辑 | 适用场景 |
|----|---------|--------|--------|
| 1 | **碗口反弹策略** | 知行趋势线与多空线的碗口反弹形态 | 中期反弹 |
| 2 | **阻力位突破策略** | 股价突破关键阻力位 | 突破选股 |
| 3 | **启明星策略** | 三根K线底部反转形态 | 底部反转 |
| 4 | **底部趋势拐点** | 深度下跌后的反转拐点 | 极端底部 |
| 5 | **趋势加速拐点** | 上升趋势中的加速拐点 | 趋势加速 |
| 6 | **多金叉共振** | 均线/KDJ/MACD金叉共振 | 多头共振 |
| 7 | **多死叉共振** | 均线/KDJ/MACD死叉共振 | 空头共振 |
| 8 | **多方炮策略** | 两阳夹一阴K线组合 | 短期反弹 |
| 9 | **缩量回调策略** | 上升趋势中的缩量回调 | 趋势回调 |
| 10 | **W底策略** | W底双底反转形态 | 双底反转 |
| 11 | **M头策略** | M头双顶反转形态 | 双顶反转 |

### 策略参数配置

编辑 `config/strategy_params.yaml` 调整策略参数。每个策略都有独立的参数配置，支持在线修改。

## 📝 命令说明

### 基础命令

```bash
# 首次全量抓取6年历史数据
python main.py init

# 启动Web界面（默认端口5000）
python main.py web

# 显示版本信息
python main.py --version
```



## 🌐 Web界面功能

访问 `http://localhost:5000` 可使用以下功能：

- **系统概览** - 股票数量、最新数据日期、系统状态
- **股票列表** - 所有股票基本信息，支持搜索和分页
- **选股执行** - 执行选股并查看详细结果
- **策略配置** - 在线查看和修改策略参数
- **交易管理** - 虚拟账户、持仓查询、交易记录、收益计算

## 💼 交易模拟系统

系统内置完整的交易模拟功能，支持：

- **虚拟账户管理** - 创建多个虚拟账户，设置初始资金
- **买入/卖出操作** - 模拟真实交易流程
- **持仓管理** - 查看当前持仓、成本价、收益率
- **交易记录** - 完整的交易历史记录
- **收益计算** - 自动计算成本价、手续费、收益

## 🛠️ 技术栈

- **Python 3.8+** - 核心语言
- **akshare** - A股实时/历史数据获取
- **pandas/numpy** - 数据处理与技术指标计算
- **matplotlib** - K线图生成
- **Flask** - Web管理界面
- **SQLite** - 数据存储

## 📁 项目结构

```
├── main.py                      # 主程序入口
├── web_server.py                # Web服务器
├── stock_analyzer.py            # 股票分析器
├── technical.py                 # 技术指标计算
├── strategy/                    # 策略模块
│   ├── base_strategy.py         # 策略基类
│   ├── bowl_rebound.py          # 碗口反弹策略
│   ├── morning_star.py          # 启明星策略
│   ├── pattern_*.py             # B1完美图形相关
│   └── ...                      # 其他策略
├── utils/                       # 工具模块
│   ├── akshare_fetcher.py       # 数据获取
│   ├── csv_manager.py           # CSV数据管理
│   ├── technical.py             # 技术指标
│   ├── kline_chart.py           # K线图生成
│   └── ...
├── trading/                     # 交易模拟模块
│   ├── trading_service.py       # 交易服务
│   ├── trading_dao.py           # 数据访问层
│   └── ...
├── config/                      # 配置文件
│   ├── config.yaml              # 主配置
│   ├── strategy_params.yaml     # 策略参数
│   └── strategy_order.yaml      # 策略顺序
├── web/                         # Web前端
│   ├── templates/               # HTML模板
│   └── static/                  # 静态资源
├── data/                        # 股票数据（CSV格式）
│   ├── 00/                      # 000xxx股票
│   ├── 30/                      # 300xxx股票
│   ├── 60/                      # 600xxx股票
│   └── 68/                      # 688xxx股票
└── test/                        # 测试文件
```

## ⚙️ 配置说明

### 主配置文件 (config/config.yaml)

```yaml
# 数据获取配置
data:
  max_retries: 3              # 最大重试次数
  timeout: 30                 # 超时时间（秒）
  cache_dir: data/akshare_cache

# 选股配置
selection:
  max_stocks: null            # 最大处理股票数（null表示全部）
  min_market_cap: 4000000000  # 最小市值（40亿）
  exclude_st: true            # 排除ST股票
  exclude_delisted: true      # 排除退市股票

# Web服务配置
web:
  host: 0.0.0.0
  port: 5000
  debug: false
```

### 策略参数配置 (config/strategy_params.yaml)

每个策略都有独立的参数配置，可根据需要调整。详见配置文件注释。

## 🔄 智能数据更新

系统采用智能更新策略：

1. **3点前** - 不更新，使用本地已有数据
2. **3点后** - 检查每只股票是否有当天数据
3. **100%有当天数据** - 跳过更新，直接使用
4. **否则** - 执行增量更新

这样既能保证数据的及时性，又能避免不必要的网络请求。

## 🔧 扩展新策略

### 创建新策略

1. 在 `strategy/` 目录创建新文件，继承 `BaseStrategy`
2. 实现 `calculate_indicators()` 和 `select_stocks()` 方法
3. 在 `config/strategy_params.yaml` 添加参数
4. 系统自动识别并执行

示例：
```python
from strategy.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self, params=None):
        super().__init__("我的策略", params)
    
    def calculate_indicators(self, df):
        # 计算指标
        return df
    
    def select_stocks(self, df, stock_name=''):
        # 选股逻辑
        return signals
```

## ⚠️ 免责声明
本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。使用者应基于独立判断进行投资决策，因使用本项目产生的任何投资损失，作者不承担任何责任。

📄 License
本项目基于 MIT 许可证开源，详见 LICENSE 文件。
特别致谢原项目 a-share-quant-selector 的作者 Dzy-HW-XD，本项目在其优秀的基础架构上扩展开发。

🙏 致谢
感谢以下开源项目：

a-share-quant-selector - 原项目基础架构

akshare - A股数据获取库

pandas - 数据处理库

Flask - Web框架

GitHub: https://github.com/ling-0729/khunter
文档: 详见 doc/ 目录
