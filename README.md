# KHunter - 开箱即用的A股量化交易系统

KHunter 是一套**开箱即用的A股量化交易系统**，集数据管理、策略选股、择时交易、风险控制、回测验证于一体，为个人投资者提供从数据到交易的全流程量化解决方案。

> **当前版本：1.7.1（2026-10-07）** ｜ 详细变更见 [`RELEASE_NOTES.md`](RELEASE_NOTES.md) ｜ 发布清单见 [`RELEASE_FILES.md`](RELEASE_FILES.md)
>
> ### 🆕 1.7.1 亮点（策略清单同步）
> - **选股策略：12 种**（原 13 种；**9 个已归档**至 `strategy/disabled/`，不再参与选股）；
> - **择时策略：8 种**（原 5 种；新增 **低位海龟**、**海龟plus**、**趋势回调缩量**）；
> - **顺势宝规则简化**：买 2 种（稳健启动 / 强势突破）＋ 加仓 1 种（=买②口径，数量按海龟递减）＋ 卖出 1 种（最低价 < 中轨 且 MACD 转绿 ⇒ 全清）；
> - ⚠️ 清单以**启动时注册表**为准（详见下方策略表与 `RELEASE_NOTES.md`）。
>
> ### 🆕 1.7.0 亮点
> - **当日仓位上限（大盘 ADX 判定）**：`ADX>25 ∧ 上升` ⇒ 100% ｜ `ADX<18 ∧ 上升 ∧ 收盘>MA20` ⇒ 50% ｜ **其他 ⇒ 0%（不开新仓，加仓不受限）**；
>   含**板块回退**（全A 兜底时按板块指数部分放行，**仅限对应板块**）与细则「**双创同时放行 ⇒ 整体不放行**」；
> - **实盘/回测时点口径统一**：两边都是「**信号日当天收盘**」（实盘 T 日信号 → T+1 成交；回测信号日 = 执行日前一根），
>   **大盘档位与个股闸门共用同一解析器**，且**回测硬钉"前一根"**（不会前视）；
> - **回测数据本地化 + 离线闸门**：四类本地数据（交易日历/资金流/基本面/公告）+ ADX；回测**完全离线**、结果可复现；
>   ★ **数据源无权限 ⇒ 自动跳过、不中断**（逐维度/逐指数留痕，不计失败）；
> - **结构完整性**：补齐 `trading_plan` 表与 `khunter.key_date` 列；启动**自动建表/补列**（含迁移前备份与审计表）；
> - **飞书日报**新增「大盘 ADX + 当日仓位上限判定」一节（含判定日与口径，缺数据如实标注）；
> - **初始化页**新增「大盘指数 ADX」维度（一键全量 = 7 项）；
> - ⚠️ **升级 / 新装后必做「ADX 两类回填」**（否则个股闸门会**静默不放行** ⇒ 完全不买入 ✗）：
>   ```python
>   # ① 个股 ADX（stock_kline.adx 的"值"不会随建表产生 ✗）
>   from utils.global_db import get_global_db
>   from utils import stock_adx as SA
>   print(SA.backfill_all(get_global_db().connect()))      # 分钟级 ✓ 幂等 ✓ 可反复跑 ✓
>   ```
>   ```powershell
>   # ② 指数 ADX（主指数 + 科创板 + 创业板）
>   python tools/backfill_index_adx.py --indexes 399006.SZ,000688.SH --start 20200101 --end 20260930
>   # ③ 自检（覆盖率 / 起点预热 / 接线 / yaml↔DB 一致性）
>   python tools/manual_check_adx.py
>   ```
>   顺序：**重启**（自动建表/补列）→ 初始化页勾全 **7 项** → ①②回填 → ③自检 → 才开回测 ✓。
>
> ⚠️ 本仓库**只发布源码**：`test_*.py`（回归测试）与 `config/config.yaml`（含本地凭据）**不入库** ℹ️


## ✨ 核心优势

### 🎯 多策略选股和择时
- **12种选股策略** - 覆盖底部反转、形态突破、均线共振等多个维度（★ 2026-10-07 更新：原 13 种中 **9 个已归档**至 `strategy/disabled/`，见下方说明）
- **8种择时策略** - 辅助判断买卖时机（★ 2026-10-07 更新：新增 低位海龟、海龟plus、趋势回调缩量；顺势宝规则已简化）
- **策略灵活组合** - 支持多策略组合，精准捕捉投资机会

### 📊 完整的数据支持
- **5000+只A股数据** - 覆盖全市场股票，支持最多三年历史数据回溯
- **智能数据更新** - 自动判断更新时机，避免不必要的网络请求
- **多层降级机制** - 确保数据获取的稳定性和可用性

### 🌐 可视化管理界面
- **Web管理系统** - 实时查看股票数据、执行选股、分析结果
- **K线图可视化** - 为每只入选股票生成K线图，直观展示技术形态
- **策略参数配置** - 在线修改策略参数

<!-- ⚠️【2026-10-07 ✓】此处原有 `![系统界面](image/imp.jpeg)` ✗ —— 但 `image/` 目录
     **不在仓库中** ✗（`git ls-files` 无此路径 ✓）⇒ 渲染时是**坏图** ✗ ⇒ 已移除占位 ✓。
     如需展示截图：把图片放到 `web/static/images/` 下再引用 ✓（该目录已在库 ✓）。 -->

### 🔒 风险控制
- **VaR风险控制** - 基于VaR的风险评估和仓位管理
- **自动风险过滤** - 自动排除ST股、退市股、市值过低股票、近期涨幅过高等高风险标的

## 📈 股票评分系统

KHunter采用**五维度综合评分模型**，从多个角度全面评估股票投资价值。

### 五维度评分体系

| 维度 | 权重 | 评分范围 | 说明 |
|------|------|--------|------|
| **技术面** | 35% | 不限 | 策略命中情况，权重累加 |
| **资金面** | 35% | -100~100 | 资金流向分析，最重要指标 |
| **基本面** | 10% | -60~+60 | 财务指标分析，排雷为主 |
| **板块强度** | 10% | -100~+200 | 所属板块表现，顺势而为 |
| **事件驱动** | 10% | -100~+100 | 重大事件催化，短期机会 |

### 狩猎场使用流程

1. **执行选股** - 运行选股策略，获得初步候选股票
2. **排名评分** - 对选股结果进行五维评分和排名
3. **筛选过滤** - 按评分等级、支撑位等条件筛选
4. **狩猎场展示** - 查看符合条件的优质股票
5. **追踪管理** - 对狩猎场股票进行追踪和管理

### 📈 策略回测功能
- **回测配置** - 配置回测参数，包括策略选择、回测时间范围、资金管理等
- **回测执行** - 执行策略回测，模拟真实交易环境
- **结果分析** - 展示回测结果，包括收益率、胜率、最大回撤等指标
- **交易记录** - 查看详细的交易记录，了解策略表现
- **收益曲线** - 展示资金曲线，直观展示策略效果


### 🚀 开箱即用
- **一键启动** - 快速开始选股
- **完善的文档** - 详细的策略说明和使用指南
### 环境要求
- ★ **Python 3.10+**（2026-10-07 更正 ✗→✓）
  - ⚠️ 原文档写 "3.8+" ✗ —— 实测**不成立** ✗：`web_server.py` 等使用
    `StrategyRunner | None` 形式的**联合类型注解** ✓，且文件**没有**
    `from __future__ import annotations` ✓ ⇒ 该语法会**立即求值** ✗ ⇒
    **3.8 / 3.9 会直接报错、服务起不来** ✗✓（按旧文档装环境会踩坑 ✗）
  - 开发/生产环境实测为 **3.12** ✓（`python --version` 复核过 ✓）
- pip 或 conda

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/ling-0729/KHunter.git
cd KHunter

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动Web界面
python main.py web
```
第2，3步也可以直接在windows下双击根目录下start.bat文件自动处理


## 🌐 Web界面功能

访问 `http://localhost:5001` 可使用以下功能：

- **系统概览** - 股票数量、最新数据日期、系统状态
- **股票列表** - 所有股票基本信息，支持搜索和分页
- **选股执行** - 执行选股并查看详细结果，支持多策略组合
- **策略配置** - 在线查看和修改策略参数
- **策略回测** - 配置和执行策略回测，查看回测结果
- **狩猎场** - 查看多维度评分的股票筛选结果
- **数据管理** - 查看数据更新状态，执行数据初始化和更新
- **看板功能** - 展示金股、热门行业和板块分布
- **策略运行器** - 策略自动化执行（需配置文件）

初次使用必须执行的功能：
初始化数据，数据更新
日常每天收盘后执行数据更新，增量更新最新k线数据
通过查询基础数据和首页的数据最新日期，股票数量等信息可以验证数据准备情况
数据准备好了以后，可以通过执行选股功能，按策略选股，并保存选股结果
选股完成后，可以通过选股排名功能，对选股结果进行五维分析，并对结果排名
对于选股结果，通过分数阈值和跟踪天数过滤，对当前价格和支撑位价格比较分析，对于符合条件的股票筛选到狩猎场
可以对排名靠前的股票，狩猎场股票进行跟踪，便于调整策略参数，迭代优化策略，有一定开发基础的朋友可以自己扩展策略
可以对策略进行历史数据回测，便于进一步优化策略

**注意**：由于免费数据源的稳定性问题，经过测试，策略选股功能可以稳定使用，但是由于选股排名和狩猎场等功能依赖于除k线以外的如资金面，基本面，板块，事件等数据，可能存在数据无法稳定获取的情况，对功能有一定影响。一方面开发者积极探索稳定数据源，另一方面可以通过注册tushare获取api token解决数据稳定性问题，完整功能需要6000积分，带来的困扰请理解。

## 📊 12种选股策略

> ★ **2026-10-07 更新**（以**实际注册**为准 ✓）：
> 1. 本表 = 启动时 `StrategyRegistry` **真实注册**的 12 个策略 ✓（与运行日志逐字一致 ✓）；
> 2. 另有 **9 个已归档**至 `strategy/disabled/` ✗：底部趋势拐点、趋势加速拐点、涨停横盘、强势洗盘弱转强、
>    趋势起点、W底、金叉未绿、低位TD9、碗口反弹（`_bowl_rebound_disabled.py`）——
>    ⚠️ 它们**不再参与选股**（仅留档备查 ✓）；如需启用 ⇒ 移回 `strategy/` 并在注册表登记 ✓；
> 3. `config/strategy_order.yaml` 中仍列有 `MTopStrategy` / `MultiDeathCrossStrategy` 等**已不存在的策略** ✗
>    ⇒ 该项配置属**历史遗留**，实际执行以注册表为准 ✓。

| # | 策略名称 | 核心逻辑 | 适用场景 |
|----|---------|--------|--------|
| 1 | **金三角策略** | 均线金三角形态（多头排列共振） | 趋势启动 |
| 2 | **涨停回马枪策略** | 涨停后回调再次启动 | 短期强势 |
| 3 | **启明星策略** | 三根K线底部反转形态 | 底部反转 |
| 4 | **多金叉共振** | 均线/KDJ/MACD金叉共振 | 多头共振 |
| 5 | **多方炮策略** | 两阳夹一阴K线组合 | 短期反弹 |
| 6 | **阻力位突破策略** | 股价突破关键阻力位 | 突破选股 |
| 7 | **仙人指路策略** | 长上影线突破形态 | 突破选股 |
| 8 | **龙头策略** | 强势领涨股识别 | 题材/主线 |
| 9 | **主升低吸策略** | 主升浪中的回调低吸 | 趋势回踩 |
| 10 | **次新腰斩策略** | 次新股大幅回撤后的反弹 | 超跌反弹 |
| 11 | **超跌反弹** | 短期超跌后的修复反弹 | 反弹博弈 |
| 12 | **2560战法** | 基于特定K线形态的选股策略 | 形态突破 |

## ⏰ 8种择时策略

> ★ **2026-10-07 更新** ✓：新增 **低位海龟**（去 MA20 过滤）、**海龟plus**（只做第二买点）、
> **趋势回调缩量策略** ✓；**顺势宝**规则已**简化**（见下 ✓）⇒ 共 **8 种**（原 5 种）。

| # | 策略名称 | 核心逻辑 | 适用场景 |
|----|---------|--------|--------|
| 1 | **布林带策略** | 基于布林带上下轨判断买卖时机 | 震荡行情 |
| 2 | **RSI策略** | 基于相对强弱指数判断超买超卖 | 短线交易 |
| 3 | **支撑位策略** | 基于支撑位和压力位判断买卖 | 波段操作 |
| 4 | **海龟策略** | 基于ATR的突破和仓位管理 | 趋势交易 |
| 5 | **低位海龟**（`low_turtle`） | 海龟系，**去掉 MA20 过滤** | 更早入场 |
| 6 | **海龟plus**（`turtle_plus`） | 海龟系，**只做第二买点** | 趋势确认后加仓 |
| 7 | **趋势回调缩量策略**（`uptrend_pullback`） | 上升趋势中**回调且缩量**时介入 | 趋势回踩 |
| 8 | **顺势宝**（`macd_bollinger`） | ★ **已简化**：买 2 种（稳健启动 / 强势突破）＋ 加仓 1 种（=买②口径，数量按**海龟递减** `1/(已加仓+2)`）＋ 卖出 1 种（**最低价 < 中轨 且 MACD 转绿** ⇒ 全清） | 趋势跟随 |

### 策略参数配置

可以前端功能调整策略参数。每个策略都有独立的参数配置，支持在线修改。


## 🛠️ 技术栈

- ★ **Python 3.10+** - 核心语言（⚠️ 原写 "3.8+" ✗ 与代码不符，见「环境要求」说明 ✓）
- **akshare** - A股实时/历史数据获取
- **pandas/numpy** - 数据处理与技术指标计算
- **matplotlib** - K线图生成
- **Flask** - Web管理界面
- **SQLite** - 数据存储

## 📁 项目结构

```
├── main.py                      # 主程序入口
├── web_server.py                # Web服务器
├── stock_analyzer/              # 股票分析器模块
│   ├── data_fetcher.py          # 数据获取
│   ├── technical_analyzer.py    # 技术分析
│   ├── fundamental_analyzer.py  # 基本面分析
│   ├── sector_analyzer.py       # 行业分析
│   ├── fund_flow_analyzer.py    # 资金流分析
│   ├── event_analyzer.py        # 事件分析
│   └── report_generator.py      # 报告生成
├── strategy/                    # 策略模块（★ 2026-10-07 按实际注册清单更正 ✓）
│   ├── __init__.py              # 初始化文件
│   ├── base_strategy.py         # 策略基类
│   ├── golden_triangle_strategy.py      # 金三角策略
│   ├── limit_up_pullback_strategy.py    # 涨停回马枪策略
│   ├── morning_star.py          # 启明星策略
│   ├── multi_golden_cross.py    # 多金叉共振
│   ├── multi_party_cannon.py    # 多方炮策略
│   ├── resistance_breakout.py   # 阻力位突破策略
│   ├── immortal_guidance_strategy.py    # 仙人指路策略
│   ├── leader_strategy.py       # 龙头策略
│   ├── main_uptrend_dip_buy_strategy.py # 主升低吸策略
│   ├── new_stock_drawdown_strategy.py   # 次新腰斩策略
│   ├── oversold_rebound_strategy.py     # 超跌反弹
│   ├── strategy_2560_selection.py       # 2560战法
│   ├── parallel_strategy_executor.py    # 并行策略执行器
│   ├── strategy_registry.py     # 策略注册表
│   ├── pattern_config.py / pattern_library.py / pattern_matcher.py  # 形态库
│   ├── _bowl_rebound_disabled.py        # 碗口反弹（**已禁用** ✗）
│   └── disabled/                # ★ 已归档策略（**不参与选股** ✗，共 8 个）
│       ├── bottom_trend_inflection.py   # 底部趋势拐点
│       ├── trend_acceleration_inflection.py  # 趋势加速拐点
│       ├── limit_up_sideways_strategy.py     # 涨停横盘
│       ├── strong_wash_weak_to_strong.py     # 强势洗盘弱转强
│       ├── trend_start_strategy.py      # 趋势起点
│       ├── w_bottom_strategy.py         # W底
│       ├── golden_cross_not_green.py    # 金叉未绿
│       └── low_td9_strategy.py          # 低位TD9
├── trading/                     # 交易和评分模块
│   ├── __init__.py              # 初始化文件
│   ├── backtest_engine.py       # 回测引擎
│   ├── backtest_dao.py          # 回测数据访问
│   ├── backtest_batch_queue.py  # 批量回测队列
│   ├── routes.py                # API路由
│   ├── khunter_api.py           # 狩猎场API
│   ├── khunter_dao.py           # 狩猎场数据访问
│   ├── khunter_data_processor.py  # 狩猎场数据处理
│   ├── khunter_support_calculator.py  # 狩猎场支撑位计算
│   ├── khunter_buy_point_judge.py  # 狩猎场买点判断
│   ├── stock_score_calculator.py  # 股票评分计算
│   ├── stock_score_dao.py       # 股票评分数据访问
│   ├── stock_score_api.py       # 股票评分API
│   ├── strategy_execution_plan.py  # 策略执行计划
│   ├── strategy_runner.py       # 策略运行器
│   ├── macd_bollinger_strategy.py  # 顺势宝策略
│   └── ...
├── utils/                       # 工具模块
│   ├── akshare_fetcher.py       # AKShare数据获取
│   ├── csv_manager.py           # CSV数据管理
│   ├── technical.py             # 技术指标
│   ├── kline_chart.py           # K线图生成
│   ├── log_config.py            # 日志配置与自动清理
│   ├── risk_manager.py          # 风险管理
│   ├── risk_controller.py       # 风险控制器
│   ├── var_calculator.py        # VaR计算器
│   ├── risk_config_loader.py    # 风险配置加载器
│   └── ...
├── config/                      # 配置文件
│   ├── config.yaml              # 主配置
│   ├── strategy_params.yaml     # 策略参数
│   ├── strategy_order.yaml      # 策略顺序
│   ├── strategy_weights.json    # 策略权重
│   ├── risk_config.yaml         # 风险配置
│   └── ...
├── web/                         # Web前端
│   ├── templates/               # HTML模板
│   └── static/                  # 静态资源
├── data/                        # 数据库脚本
│   ├── DataSql.sql              # 数据库结构脚本
│   └── InitData.sql             # 初始化数据脚本
└── doc/                         # 文档
```

## ⚙️ 配置说明

### 配置文件

- **主配置文件** (`config/config.yaml`) - 系统级配置，包括数据获取、选股和Web服务设置
- **策略参数配置** (`config/strategy_params.yaml`) - 各策略的参数配置
- **策略顺序配置** (`config/strategy_order.yaml`) - 策略执行顺序
- **策略权重配置** (`config/strategy_weights.json`) - 策略权重设置
- **风险配置** (`config/risk_config.yaml`) - 风险控制参数配置

详细配置说明请参考各配置文件中的注释。

## 🔄 智能数据更新

系统采用智能更新策略：

1. **3点前** - 不更新，使用本地已有数据
2. **3点后** - 检查每只股票是否有当天数据
3. **100%有当天数据** - 跳过更新，直接使用
4. **否则** - 执行增量更新

这样既能保证数据的及时性，又能避免不必要的网络请求。为保证数据完整准确，建议16：00后执行更新。

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
1. **本项目仅供学习和研究使用**，不构成任何投资建议。
2. **筛选结果仅为技术指标计算结果**，不代表对任何股票的推荐或预测。
3. **过往表现不代表未来收益**，股市有风险，投资需谨慎。
4. **使用者应基于独立判断进行投资决策**，因使用本项目产生的任何投资损失，作者不承担任何责任。
5. **本项目按“原样”提供**，不附带任何明示或暗示的保证，包括但不限于适销性、特定用途适用性的保证。

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

## 📫 联系与交流

如需获取项目更新、技术文档详细介绍、和作者深度交流，请访问飞书文档：

👉 [KHunter - 项目与技术交流入口](https://my.feishu.cn/wiki/NSOrwyfRNi6OhVkRiNucoL30nAh?from=from_copylink)