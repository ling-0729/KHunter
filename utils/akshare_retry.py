#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
akshare 统一调用包装器 — 提供超时控制和缓存降级

功能:
- AkshareCache: 基于 JSON 文件的缓存管理器
- akshare_call_with_retry(): 统一的调用包装函数（无重试）
- 超时控制（连接10s，读取30s）
- 缓存降级（调用失败后直接从本地缓存获取历史数据）
- 请求间隔控制（0.5-1秒随机间隔）
"""

import os
import json
import time
import random
import hashlib
import logging
import threading
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Any, Callable, Optional

# 日志配置
logger = logging.getLogger(__name__)

# 可重试的网络异常类型列表
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    ConnectionResetError,
    requests.exceptions.RequestException,
)

# 上次 akshare 调用的时间戳，用于请求间隔控制
_last_call_time = 0.0


# ============================================================================
# 【2026-09-27 事故修复 ✓】V8（py_mini_racer）**并发首次初始化**会**原生崩溃** ✗✗
# ----------------------------------------------------------------------------
# 现象 ✗：`FATAL:partition_address_space.cc(243)] Check failed: !IsConfigurablePoolInitialized().`
#   + 栈里全是 `python312.dll`（**不是** Python 异常 ✗）⇒ **整个进程被原生终止** ✗，
#   Python 层 `try/except` **完全拦不住** ✗（无法降级、无法记日志 ✗）。
#
# 根因 ✓（**本地实测复现 ✓**）：`akshare` 的**必装依赖** `mini-racer`（= **V8** 的 Python 绑定 ✓）
#   在**多线程同时首次初始化**时，V8 的 PartitionAlloc 被初始化**两次** ✗ ⇒ 触发断言 ✗。
#   实测 ✓：单线程创建 `MiniRacer()` 正常 ✓；**8 线程同时首次创建 ⇒ 100% 复现崩溃** ✗✓。
#   而本服务是 **waitress + Flask（多线程 ✓）+ flask-socketio** ✗ ⇒ 只要两个并发请求
#   （或后台线程 + 请求）**第一次**同时碰到 akshare 的 V8 接口，就会崩 ✗。
#
# 修复 ✓：把"**首次初始化**"收进**全局锁** ✓ —— 第一个调用者（持锁 ✓）完成 V8 初始化，
#   其余线程**排队等待** ✓ ⇒ 从根上消除"并发首次 init" ✗✓。
#   代价 ✓：akshare 调用被**串行化** ✗（它们本就带 0.5~1s 间隔限速 ✓ ⇒ 影响可接受 ✓）。
#   逃生开关 ✓：`KHUNTER_AKSHARE_LOCK=0` 可关（**不建议** ✗，除非确认已单线程使用 V8）。
# ============================================================================

#: 串行化 akshare 调用 + 保证 V8 **单次**初始化 ✓
_V8_LOCK = threading.RLock()
_V8_READY = False


def _env_lock_enabled() -> bool:
    """是否启用串行锁 ✓（默认**开** ✓）"""
    return str(os.environ.get('KHUNTER_AKSHARE_LOCK', '1')).strip() != '0'


def ensure_v8_ready() -> bool:
    """**一次性**初始化 V8 ✓（须在 `_V8_LOCK` 内调用 ✓）

    幂等 ✓、失败不抛 ✗（失败只记日志 ✓ —— 后续 akshare 自己会再尝试 ✓）。
    可用它做**启动预热** ✓（单线程阶段先建好 ✓，避免首个请求触发初始化 ✓）。
    """
    global _V8_READY
    if _V8_READY:
        return True
    try:
        from py_mini_racer import MiniRacer
        ctx = MiniRacer()
        ctx.eval('1+1')                 # 真正触发 V8 初始化 ✓
        logger.info('【V8】已单次初始化完成 ✓（规避并发首次 init 崩溃 ✗）')
    except Exception as e:              # 原生 abort **不会**走到这里 ✗（但锁已保证只一个线程进 ✗）
        logger.debug(f'【V8】预热跳过（{e}）—— 不影响非 V8 接口 ✓')
    _V8_READY = True
    return True


def warm_up_v8() -> bool:
    """**启动预热** ✓（建议在 Web 服务**多线程启动之前**调用一次 ✓）

    例 ✓：`web_server.py` / `main.py` 启动处 `from utils.akshare_retry import warm_up_v8; warm_up_v8()` ✓
    注 ✓：即使不预热 ✓，`akshare_call_with_retry` 也会在锁内自动完成首次初始化 ✓ ⇒ **不致命** ✓。
    """
    with _V8_LOCK:
        return ensure_v8_ready()


class AkshareCache:
    """基于 JSON 文件的 akshare 缓存管理器
    
    缓存目录: data/akshare_cache/
    缓存键: {api_func_name}_{参数hash}.json
    缓存内容: DataFrame 转 JSON 存储，附带时间戳
    """

    def __init__(self, cache_dir: str = "data/akshare_cache"):
        """初始化缓存管理器
        
        Args:
            cache_dir: 缓存文件存储目录
        """
        self.cache_dir = Path(cache_dir)
        # 确保缓存目录存在
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, func_name: str, **kwargs) -> str:
        """生成缓存键
        
        Args:
            func_name: API 函数名称
            **kwargs: 调用参数
            
        Returns:
            str: 缓存文件名（不含路径）
        """
        # 将参数排序后序列化，生成稳定的 hash
        params_str = json.dumps(kwargs, sort_keys=True, default=str)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:12]
        return f"{func_name}_{params_hash}.json"

    def get(self, func_name: str, cache_ttl: int = 86400, **kwargs) -> Optional[pd.DataFrame]:
        """从缓存获取数据
        
        Args:
            func_name: API 函数名称
            cache_ttl: 缓存有效期（秒），默认24小时
            **kwargs: 调用参数（用于生成缓存键）
            
        Returns:
            pd.DataFrame 或 None（缓存不存在或已过期）
        """
        key = self._make_key(func_name, **kwargs)
        cache_file = self.cache_dir / key

        # 检查缓存文件是否存在
        if not cache_file.exists():
            return None

        try:
            # 读取缓存文件
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)

            # 检查缓存是否过期
            cached_time = cached.get("timestamp", 0)
            if time.time() - cached_time > cache_ttl:
                # 缓存已过期，但作为降级数据仍可使用
                # 返回过期数据（调用方决定是否使用）
                logger.debug(f"缓存已过期: {key}")

            # 将 JSON 数据还原为 DataFrame
            data = cached.get("data")
            if data is not None:
                df = pd.DataFrame(data)
                return df

        except Exception as e:
            logger.warning(f"读取缓存失败 ({key}): {e}")

        return None

    def get_fallback(self, func_name: str, **kwargs) -> Optional[pd.DataFrame]:
        """获取降级缓存数据（忽略过期时间）
        
        Args:
            func_name: API 函数名称
            **kwargs: 调用参数
            
        Returns:
            pd.DataFrame 或 None
        """
        key = self._make_key(func_name, **kwargs)
        cache_file = self.cache_dir / key

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            data = cached.get("data")
            if data is not None:
                return pd.DataFrame(data)
        except Exception as e:
            logger.warning(f"读取降级缓存失败 ({key}): {e}")

        return None

    def set(self, func_name: str, data: pd.DataFrame, **kwargs) -> None:
        """将数据写入缓存
        
        Args:
            func_name: API 函数名称
            data: 要缓存的 DataFrame
            **kwargs: 调用参数（用于生成缓存键）
        """
        key = self._make_key(func_name, **kwargs)
        cache_file = self.cache_dir / key

        try:
            # DataFrame 转为可序列化的字典列表
            cached = {
                "timestamp": time.time(),
                "func_name": func_name,
                "params": kwargs,
                "data": data.to_dict(orient='records'),
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cached, f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning(f"写入缓存失败 ({key}): {e}")


# 全局缓存实例
_cache = AkshareCache()


def _apply_timeout():
    """通过 monkey-patch requests.Session 设置默认超时
    
    连接超时: 10秒
    读取超时: 30秒
    """
    _original_send = requests.Session.send

    def _send_with_timeout(self, request, **kwargs):
        """包装 send 方法，注入默认超时"""
        # 仅在未显式设置 timeout 时注入默认值
        if kwargs.get('timeout') is None:
            kwargs['timeout'] = (10, 30)
        return _original_send(self, request, **kwargs)

    # 仅 patch 一次
    if not getattr(requests.Session.send, '_patched_timeout', False):
        requests.Session.send = _send_with_timeout
        requests.Session.send._patched_timeout = True


def _enforce_call_interval():
    """请求间隔控制 — 连续 akshare 调用之间添加 0.5-1 秒随机间隔"""
    global _last_call_time
    now = time.time()
    elapsed = now - _last_call_time
    # 如果距上次调用不足 0.5 秒，则等待
    if _last_call_time > 0 and elapsed < 0.5:
        sleep_time = random.uniform(0.5, 1.0) - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)
    _last_call_time = time.time()


def akshare_call_with_retry(
    api_func: Callable,
    max_retries: int = 3,
    cache_ttl: int = 86400,
    **kwargs
) -> Optional[pd.DataFrame]:
    """统一的 akshare 调用包装器 — 超时控制 + 缓存降级 + 重试机制
    
    调用流程:
    1. 应用超时控制
    2. 执行请求间隔控制
    3. 调用 api_func，成功则更新缓存并返回
    4. 遇到网络异常时，进行重试（最多 max_retries 次）
    5. 所有重试都失败后，从缓存获取历史数据（降级）
    6. 缓存也不存在时，返回 None（由调用方处理默认值）
    
    Args:
        api_func: akshare API 函数（如 ak.stock_zh_a_spot_em）
        max_retries: 最大重试次数，默认 3 次
        cache_ttl: 缓存有效期（秒），默认 86400（24小时）
        **kwargs: 传递给 api_func 的参数
        
    Returns:
        pd.DataFrame 或 None
    """
    # 获取函数名称用于缓存键（兼容 MagicMock 等测试替身）
    func_name = getattr(api_func, '__name__', None)
    if func_name is None:
        func_name = getattr(api_func, '_mock_name', None) or str(api_func)

    # 应用超时控制（monkey-patch）
    _apply_timeout()

    # 尝试调用 API，支持重试
    for attempt in range(max_retries):
        try:
            # 请求间隔控制
            _enforce_call_interval()

            # 调用 akshare API
            # 【2026-09-27】**必须在锁内** ✗✓：
            #   ① 保证 V8 **单次**初始化 ✓（并发首次 init ⇒ 原生 FATAL ✗✗）
            #   ② 顺带串行化 akshare 调用 ✓（它们本就限速 ✓，代价可接受 ✓）
            if _env_lock_enabled():
                with _V8_LOCK:
                    ensure_v8_ready()
                    result = api_func(**kwargs)
            else:
                result = api_func(**kwargs)

            # 成功：更新缓存并返回
            if result is not None and not (isinstance(result, pd.DataFrame) and result.empty):
                if isinstance(result, pd.DataFrame):
                    _cache.set(func_name, result, **kwargs)
                return result

            # 返回空数据也视为成功（非网络异常）
            return result

        except RETRYABLE_EXCEPTIONS as e:
            # 网络异常 — 尝试重试
            logger.warning(f"akshare 调用失败 ({func_name})，第 {attempt + 1}/{max_retries} 次: {e}")
            if attempt < max_retries - 1:
                # 随机延迟后重试
                time.sleep(random.uniform(1, 3))
                continue
            else:
                # 所有重试都失败，尝试缓存降级
                logger.warning(f"所有重试都失败，尝试缓存降级")
                cached_data = _cache.get_fallback(func_name, **kwargs)
                if cached_data is not None:
                    logger.info(f"使用缓存降级数据: {func_name}")
                    return cached_data

                # 缓存也不存在
                logger.error(f"akshare 调用 {func_name} 失败，无缓存可降级。异常: {e}")
                return None

        except Exception as e:
            # 非网络异常（如参数错误），直接抛出
            logger.error(f"akshare 调用异常 ({func_name}): {e}")
            raise
