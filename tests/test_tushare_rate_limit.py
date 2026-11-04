"""Offline checks for the shared Tushare request budget and retry behavior."""
import ast
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import tempfile
import time
import unittest

from utils.tushare_client import RateLimitedPro, TushareRateLimiter


def record_process_request(state_path, queue):
    TushareRateLimiter(state_path).wait()
    queue.put(time.time())


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class RateLimitTests(unittest.TestCase):
    def test_shared_budget_is_below_200_in_every_minute(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = Clock()
            limiters = [TushareRateLimiter(Path(directory) / 'budget.db',
                        clock=clock.time, sleep=clock.sleep) for _ in range(2)]
            starts = []
            for i in range(400):
                limiters[i % 2].wait()
                starts.append(clock.now)
            for start in starts:
                self.assertLess(sum(start <= value < start + 60 for value in starts), 200)
            self.assertGreaterEqual(starts[-1] - starts[0], 399 * 60 / 180 - 1e-8)

    def test_shared_state_serializes_concurrent_clients(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'budget.db'
            clients = [TushareRateLimiter(state) for _ in range(4)]
            def request(client):
                client.wait()
                return time.time()
            with ThreadPoolExecutor(max_workers=4) as pool:
                starts = sorted(pool.map(request, clients))
            self.assertGreater(starts[-1] - starts[0], 0.95)

    def test_rate_error_cools_down_and_retries_same_request(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = Clock()
            limiter = TushareRateLimiter(Path(directory) / 'budget.db',
                                        clock=clock.time, sleep=clock.sleep)
            calls = []
            class Client:
                def fina_indicator(self, **kwargs):
                    calls.append((clock.now, kwargs))
                    if len(calls) == 1:
                        raise RuntimeError('访问接口频率超限(200次/分钟)')
                    return 'rows'
            client = RateLimitedPro(Client(), limiter)
            self.assertEqual(client.fina_indicator(ts_code='000001.SZ'), 'rows')
            self.assertEqual(calls[0][1], calls[1][1])
            self.assertGreaterEqual(calls[1][0] - calls[0][0], 61)

    def test_separate_processes_share_the_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context('spawn')
            queue = context.Queue()
            path = str(Path(directory) / 'budget.db')
            processes = [context.Process(target=record_process_request, args=(path, queue))
                         for _ in range(3)]
            for process in processes:
                process.start()
            try:
                starts = sorted(queue.get(timeout=15) for _ in processes)
                for process in processes:
                    process.join(timeout=15)
                    self.assertEqual(process.exitcode, 0)
                self.assertGreater(starts[-1] - starts[0], 0.63)
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=5)
                queue.close()

    def test_permission_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = Clock()
            limiter = TushareRateLimiter(Path(directory) / 'budget.db',
                                        clock=clock.time, sleep=clock.sleep)
            calls = []
            class Client:
                def moneyflow_ths(self):
                    calls.append(1)
                    raise RuntimeError('没有访问权限')
            with self.assertRaisesRegex(RuntimeError, '没有访问权限'):
                RateLimitedPro(Client(), limiter).moneyflow_ths()
            self.assertEqual(len(calls), 1)

    def test_repeated_rate_error_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = Clock()
            limiter = TushareRateLimiter(Path(directory) / 'budget.db',
                                        clock=clock.time, sleep=clock.sleep)
            calls = []
            class Client:
                def query(self, *args, **kwargs):
                    calls.append(1)
                    raise RuntimeError('rate limit')
            with self.assertRaisesRegex(RuntimeError, 'rate limit'):
                RateLimitedPro(Client(), limiter).query('daily')
            self.assertEqual(len(calls), 2)
            self.assertGreaterEqual(clock.now, 1061)

    def test_all_pro_factories_use_shared_wrapper(self):
        root = Path(__file__).resolve().parents[1]
        files = [root / 'web_server.py']
        for folder in ('utils', 'trading', 'tools', 'scripts'):
            files.extend((root / folder).rglob('*.py'))
        for path in files:
            if path.name == 'tushare_client.py':
                continue
            source = path.read_text(encoding='utf-8-sig')
            if '.pro_api(' not in source:
                continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotEqual(node.func.attr, 'pro_api', str(path))


if __name__ == '__main__':
    unittest.main()
