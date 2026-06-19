"""
重试处理模块
提供统一的错误重试机制
"""

import logging
import time
import functools
from typing import Callable, Type, Tuple, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class RetryStrategy(Enum):
    """重试策略"""
    FIXED = "fixed"           # 固定间隔
    LINEAR = "linear"         # 线性递增
    EXPONENTIAL = "exponential"  # 指数递增


class RetryHandler:
    """重试处理器"""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
        exceptions: Tuple[Type[Exception], ...] = (Exception,)
    ):
        """初始化重试处理器
        
        Args:
            max_retries: 最大重试次数
            base_delay: 基础延迟时间（秒）
            max_delay: 最大延迟时间（秒）
            strategy: 重试策略
            exceptions: 需要重试的异常类型
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.strategy = strategy
        self.exceptions = exceptions
    
    def _calculate_delay(self, attempt: int) -> float:
        """计算重试延迟时间
        
        Args:
            attempt: 当前尝试次数（从1开始）
            
        Returns:
            延迟时间（秒）
        """
        if self.strategy == RetryStrategy.FIXED:
            delay = self.base_delay
        elif self.strategy == RetryStrategy.LINEAR:
            delay = self.base_delay * attempt
        else:  # EXPONENTIAL
            delay = self.base_delay * (2 ** (attempt - 1))
        
        return min(delay, self.max_delay)
    
    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """执行带重试的函数
        
        Args:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            函数执行结果
            
        Raises:
            最后一次失败的异常
        """
        last_exception = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                if attempt > 1:
                    # 使用getattr安全获取函数名，避免Mock对象没有__name__属性
                    func_name = getattr(func, '__name__', 'unknown')
                    logger.info(f"重试成功: {func_name} 第{attempt}次尝试")
                return result
                
            except self.exceptions as e:
                last_exception = e
                # 使用getattr安全获取函数名
                func_name = getattr(func, '__name__', 'unknown')
                
                if attempt < self.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        f"执行失败，准备重试: {func_name} "
                        f"第{attempt}次尝试，错误: {str(e)}，"
                        f"{delay:.1f}秒后重试"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"重试次数耗尽: {func_name} "
                        f"共尝试{self.max_retries}次，最终错误: {str(e)}"
                    )
        
        raise last_exception


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """重试装饰器
    
    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间（秒）
        max_delay: 最大延迟时间（秒）
        strategy: 重试策略
        exceptions: 需要重试的异常类型
        
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            handler = RetryHandler(
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                strategy=strategy,
                exceptions=exceptions
            )
            return handler.execute(func, *args, **kwargs)
        return wrapper
    return decorator


class DataFetchRetryHandler(RetryHandler):
    """数据获取重试处理器"""
    
    def __init__(self):
        """初始化数据获取重试处理器"""
        super().__init__(
            max_retries=3,
            base_delay=2.0,
            max_delay=30.0,
            strategy=RetryStrategy.EXPONENTIAL,
            exceptions=(ConnectionError, TimeoutError, IOError)
        )


class FileSaveRetryHandler(RetryHandler):
    """文件保存重试处理器"""
    
    def __init__(self):
        """初始化文件保存重试处理器"""
        super().__init__(
            max_retries=5,
            base_delay=0.5,
            max_delay=10.0,
            strategy=RetryStrategy.LINEAR,
            exceptions=(IOError, PermissionError, OSError)
        )


class NetworkRequestRetryHandler(RetryHandler):
    """网络请求重试处理器"""
    
    def __init__(self):
        """初始化网络请求重试处理器"""
        super().__init__(
            max_retries=3,
            base_delay=1.0,
            max_delay=60.0,
            strategy=RetryStrategy.EXPONENTIAL,
            exceptions=(ConnectionError, TimeoutError, ConnectionResetError)
        )


# 预定义的重试处理器实例
data_fetch_retry = DataFetchRetryHandler()
file_save_retry = FileSaveRetryHandler()
network_request_retry = NetworkRequestRetryHandler()
