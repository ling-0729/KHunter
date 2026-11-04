"""Shared Tushare Pro budget: at most 180 evenly spaced requests/minute.

All clients in this checkout share a small SQLite rate-limit database, including
clients in other threads/processes. Retries consume the same budget.
"""
from contextlib import closing
from functools import wraps
import logging
from pathlib import Path
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)
STATE_PATH = Path(__file__).resolve().parent.parent / '.local' / 'tushare_rate_limit.db'


class TushareRateLimiter:
    def __init__(self, state_path=STATE_PATH, *, calls_per_minute=180,
                 clock=time.time, sleep=time.sleep):
        if not 0 < calls_per_minute < 200:
            raise ValueError('Tushare calls_per_minute must be below 200')
        self.state_path = Path(state_path)
        self.interval = 60.0 / calls_per_minute
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.Lock()

    def _connect(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.state_path), timeout=30)
        connection.execute('CREATE TABLE IF NOT EXISTS budget '
                           '(id INTEGER PRIMARY KEY CHECK(id=1), next_at REAL NOT NULL)')
        return connection

    def wait(self):
        with self.lock:
            while True:
                with closing(self._connect()) as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    now = self.clock()
                    row = conn.execute('SELECT next_at FROM budget WHERE id=1').fetchone()
                    delay = max(0.0, row[0] - now) if row else 0.0
                    if delay <= 0:
                        conn.execute('INSERT OR REPLACE INTO budget VALUES (1, ?)',
                                     (now + self.interval,))
                    conn.commit()
                if delay <= 0:
                    return
                # Release SQLite's write lock while waiting for the shared slot.
                self.sleep(delay)

    def cooldown(self, seconds=61):
        with self.lock, closing(self._connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT next_at FROM budget WHERE id=1').fetchone()
            next_at = max(row[0] if row else 0, self.clock() + seconds)
            conn.execute('INSERT OR REPLACE INTO budget VALUES (1, ?)', (next_at,))
            conn.commit()


_limiter = TushareRateLimiter()


def _is_rate_limit_error(error):
    text = str(error).lower()
    return any(marker in text for marker in (
        '频率超限', '频次超限', '每分钟最多', '每分钟访问',
        'rate limit', 'too many requests',
    ))


class RateLimitedPro:
    def __init__(self, client, limiter=None):
        self._client = client
        self._limiter = limiter if limiter is not None else _limiter

    def __getattr__(self, name):
        target = getattr(self._client, name)
        if not callable(target):
            return target

        @wraps(target)
        def call(*args, **kwargs):
            for attempt in range(2):
                self._limiter.wait()
                try:
                    return target(*args, **kwargs)
                except Exception as error:
                    if not _is_rate_limit_error(error):
                        raise
                    self._limiter.cooldown(61)
                    logger.warning('Tushare %s 触发频率限制，共享暂停 61 秒%s',
                                   name, '后重试一次' if attempt == 0 else '，交由上层处理')
                    if attempt:
                        raise
        return call


def get_tushare_pro(*args, **kwargs):
    """Drop-in factory for ts.pro_api with a shared request budget."""
    import tushare as ts
    return RateLimitedPro(ts.pro_api(*args, **kwargs))
