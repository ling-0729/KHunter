# -*- coding: utf-8 -*-
"""KHunter 生产环境 WSGI 入口（waitress）—— 替代 `python web_server.py`

一、为什么需要本文件
  1. `python web_server.py` 走的是 werkzeug/socketio 的**开发服务器** ✗
     （启动日志里那条 "This is a development server..." 警告就是它 ✓），
     单线程、无进程守护、性能与稳定性都不适合长期运行 ✗。
  2. Windows 上推荐 **waitress**：纯 Python、pip 即装、无需编译 ✓
     （gunicorn/uWSGI 不支持 Windows ✗；eventlet/gevent 在 Windows 上常需编译 ✗）。
  3. 原 `run_web_server()` 除起服务外还做了两件**必须保留**的初始化 ✗：
       · `LogConfig.setup_logging()`   —— 日志落文件（utils/log_config.py ✓）
       · `get_commander().start_polling()` —— 飞书指令轮询线程 ✓
     本入口照做 ✓，避免"上了生产却不记日志 / 飞书指令不响应" ✗。

二、⚠️ 必须单进程、单 worker（本文件天然满足 ✓）
  飞书轮询、批量回测队列、数据更新任务都跑在**进程内** ✗ ——
  多 worker / 多实例会让同一件事被执行多次 ✗（历史上出现过"指令执行两次" ✓）。
  因此：**不要**用 gunicorn 的多 worker、也**不要**同时跑两份本入口 ✓。

三、Socket.IO 传输说明（重要 ✓）
  本项目为 `SocketIO(app, async_mode='threading')` ✓ ——
  waitress 下 WebSocket **不可用** ✗，前端 socket.io 客户端会**自动降级为长轮询** ✓
  （实时推送功能正常 ✓，只是不如 WebSocket 即时 ✗，本项目推送频率下无实质影响 ✓）。
  若必须使用 WebSocket ✗ → 改用 Linux + gunicorn + gevent 方案 ✓。

四、启动方式
  python wsgi.py                                  # 默认 0.0.0.0:5001
  set PORT=8080 && python wsgi.py                 # 指定端口
  set HOST=127.0.0.1 && python wsgi.py            # 仅本机（前面再挂反向代理 ✓）
  set KHUNTER_DISABLE_POLL=1 && python wsgi.py    # 只起 Web、不轮询飞书（冒烟测试 ✓）
  或直接双击：start_prod.bat ✓
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web_server import app, socketio  # noqa: E402  （Flask app + Flask-SocketIO 实例）

HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '5001'))
THREADS = int(os.environ.get('THREADS', '16'))
# 冒烟测试 / 已有实例在轮询时用：只起 Web，不起轮询线程 ✓
DISABLE_POLL = os.environ.get('KHUNTER_DISABLE_POLL') == '1'

# ---- 1) 日志（与开发入口一致：文件 + 控制台 ✓）----
from utils.log_config import LogConfig  # noqa: E402
LogConfig.setup_logging()

# ---- 2) 飞书指令轮询（**只允许在唯一实例中启动** ✓）----
if not DISABLE_POLL:
    from scheduler.feishu_commander import get_commander  # noqa: E402
    get_commander().start_polling()
    print('[prod] 飞书指令轮询线程已启动 ✓')
else:
    print('[prod] 已跳过飞书指令轮询（KHUNTER_DISABLE_POLL=1）✓')

# ---- 3) WSGI 应用：Flask + Socket.IO（threading 模式 → 长轮询可用 ✓）----
from socketio import WSGIApp  # noqa: E402

application = WSGIApp(socketio.server, app)


def main():
    from waitress import serve
    print('[prod] waitress 启动 → http://%s:%d  threads=%d  单进程/单worker ✓'
          % (HOST, PORT, THREADS))
    serve(
        application,
        host=HOST,
        port=PORT,
        threads=THREADS,          # 同步 Flask 靠线程并发；后台任务另有线程 ✓
        channel_timeout=600,      # 长接口/长轮询放宽超时（回测、导出等 ✓）
        connection_limit=200,
        ident='KHunter',
    )


if __name__ == '__main__':
    main()
