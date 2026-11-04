# macOS 本地部署与进度查看

## 安装和启动

使用 Python 3.12 和独立虚拟环境，从仓库根目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./khunter-local.command start
./khunter-local.command status
```

也可以使用 uv：

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.local.lock
```

`requirements.local.lock` 是 Apple Silicon / Python 3.12 的安装快照，不代表所有平台都经过验证。启动管理器使用 POSIX 的 `fcntl` 和 `ps`，`.command` 入口面向 macOS；Windows 用户继续使用原有启动入口。

本机打开 `http://127.0.0.1:5001`。启动脚本监听 `0.0.0.0:5001`，局域网其他电脑使用 `http://服务器的局域网IP:5001`。电脑之间需要网络互通，防火墙需要允许该 Python 服务的入站连接。该入口未配置多用户认证，面向可信局域网使用。

```bash
./khunter-local.command stop
./khunter-local.command restart
tail -n 80 .local/server.log
```

服务以后台进程运行，状态和字体缓存保存在 `.local/`。未安装开机自启动，电脑重启后需重新 start。管理器仅向 PID 文件对应、命令行包含本仓库绝对入口路径的进程发送停止信号。

数据库为 `data/stock_selection.db`，业务日志保存在 `logs/`。备份前先停止服务，再备份 `data/` 和 `config/`。

## 配置与首次使用

本分支默认关闭定时流水线和 PTrade，并使用手工模式及相对的信号、反馈路径。根据自己的部署环境编辑 `config/config.yaml`；启用自动流程前确认数据与交易配置。

需要 Tushare 时，在已被 Git 忽略的 `config/tushare_config.json` 中填写：

```json
{"token": "替换为自己的Token"}
```

设置文件权限后重启服务：

```bash
chmod 600 config/tushare_config.json
./khunter-local.command restart
```

默认同花顺资金流接口的积分要求及其他接口的独立权限，以 Tushare 当前官方说明和账户权限为准。网页可启动不代表所有数据接口可用。

进入“初始化数据”，选择基础数据、历史 K 线及所需的交易日历、资金流、基本面、公告、指数 ADX 维度。首次采集后，检查实际股票数量、行情日期和覆盖情况，再执行选股、排名和回测。日常使用“数据更新”进行增量更新。

个股 ADX 回填和自检示例：

```bash
.venv/bin/python - <<'PY'
from utils.global_db import get_global_db
from utils import stock_adx
print(stock_adx.backfill_all(get_global_db().connect()))
PY
.venv/bin/python tools/manual_check_adx.py
```

ADX 自检现在从项目根目录读取配置；其部分检查日期仍沿用上游固定区间，实际回测还应核对所选区间的数据与预热要求。

## 刷新后恢复进度

刷新网页后重新进入“初始化数据”或“数据更新”，页面会读取后台当前任务并恢复进度轮询，不会因此重新启动采集。已有任务运行时不要点击“重新初始化”。

也可直接查看只读接口：

- `/api/data/init/progress`
- `/api/data/update/progress`

后台任务状态保存在服务进程内。刷新网页不会中断任务，重启服务会中断正在执行的采集，不能用服务重启恢复原进程任务。

## 步骤摘要与结果

初始化页面新增“执行步骤与结果”表格，显示每个后台已上报步骤的执行状态、日志摘要、写入计数及覆盖情况。任务结束后仍可查看，并可展开原始任务日志。

- 结果有失败计数或覆盖缺口时显示失败或部分成功，即使日志文字写着“完成”。
- 权限不足等跳过情况单列显示，不视为采集成功。
- 基础数据与历史行情目前由后台合并上报，缺少内部子步骤的结果时标为“已结束，待核验”。
- 后台每次返回最近 50 条任务日志；浏览器按任务标识缓存最近观察到的最多 500 条，不等同于完整业务日志。缓存不可用时仍可展示后台当前返回的内容。

## 检查改动

### Tushare 限流

项目统一通过 `utils/tushare_client.py` 创建 Tushare Pro 客户端，所有接口与重试共享每分钟 180 次的预算，约每 0.334 秒发送一次请求。多个线程和同一检出目录下的多个进程通过 `.local/tushare_rate_limit.db` 协调，不以客户端实例分别计数。若源端仍返回频率超限，会共享冷却 61 秒并重试一次；权限错误直接交给原有采集逻辑处理。

这只协调使用本项目封装和同一状态目录的请求；同一 Token 在其他软件或其他电脑上的调用不计入此预算。实际服务端配额仍可能因其他调用而耗尽。

仅勾选交易日历、资金流、基本面等数据维度的自定义初始化会保留已有基础数据和 K 线，不再额外运行基础行情流程。基本面采集通过已有断点跳过已完成的股票，重试未完成股票。

### 自动检查

从仓库根目录运行，无需真实行情、Token 或额外 Node 依赖：

```bash
node tests/frontend/check-progress-restore.cjs
node tests/frontend/check-init-task-log.cjs
node --check web/static/js/init_simple.js
node --check web/static/js/init_task_log.js
node --check web/static/js/data_update.js
node --input-type=module --check < web/static/js/modules/navigation.js
.venv/bin/python -m py_compile local_server.py tools/manual_check_adx.py
zsh -n khunter-local.command
.venv/bin/python -m unittest discover -s tests -p test_tushare_rate_limit.py -v
```

行为检查覆盖刷新恢复、任务无需旧页面 taskId、轮询去重、终止状态清理、失败计数、覆盖缺口、跳过和跨任务缓存隔离。未覆盖浏览器端到端操作、真实行情全链路或券商交易。
