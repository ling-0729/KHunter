"""Manage the isolated, LAN-accessible KHunter service."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.local'
STATE.mkdir(exist_ok=True)
PID = STATE / 'server.pid'
URL = 'http://127.0.0.1:5001'


def owned_pid():
    try:
        pid = int(PID.read_text())
        command = subprocess.check_output(
            ['ps', '-p', str(pid), '-o', 'command='], text=True
        ).strip()
        return pid if str(ROOT / 'main.py') in command else None
    except (ValueError, OSError, subprocess.CalledProcessError):
        return None


def healthy():
    try:
        with urllib.request.urlopen(URL + '/api/stats', timeout=2) as response:
            return json.load(response).get('success') is True
    except Exception:
        return False


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else 'start'
    if action not in {'start', 'stop', 'status', 'restart'}:
        raise SystemExit('用法：./khunter-local.command [start|stop|status|restart]')
    with (STATE / 'control.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pid = owned_pid()
        if action == 'status':
            print(f'PID={pid or "无"}  网页健康={healthy()}  {URL}')
            return
        if action in {'stop', 'restart'} and pid:
            os.kill(pid, signal.SIGTERM)
            for _ in range(100):
                if not owned_pid():
                    break
                time.sleep(0.1)
            else:
                raise SystemExit('服务尚未退出，请检查日志后重试。')
            PID.unlink(missing_ok=True)
            print('KHunter 已停止。')
        if action == 'stop':
            return
        if owned_pid():
            print(f'KHunter 已启动：{URL}，网页健康={healthy()}')
            return
        if healthy():
            raise SystemExit('5001 已有服务，未启动第二个实例。')
        env = dict(os.environ, MPLBACKEND='Agg', TZ='Asia/Shanghai',
                   MPLCONFIGDIR=str(STATE / 'matplotlib'), PYTHONUNBUFFERED='1')
        with (STATE / 'server.log').open('ab') as log:
            process = subprocess.Popen(
                [str(ROOT / '.venv/bin/python'), '-u', str(ROOT / 'main.py'),
                 'web', '--host', '0.0.0.0', '--port', '5001'],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
        PID.write_text(str(process.pid))
        for _ in range(120):
            if process.poll() is not None:
                PID.unlink(missing_ok=True)
                raise SystemExit(f'启动失败，请查看 {STATE / "server.log"}')
            if healthy():
                print(f'KHunter 已启动：{URL}（PID {process.pid}）')
                return
            time.sleep(0.5)
        raise SystemExit('服务仍在启动，请稍后运行 status 并检查 .local/server.log。')


if __name__ == '__main__':
    main()
