"""
结构化日志模块
提供统一的日志格式、运行ID追踪和上下文信息管理
"""

import logging
import json
import functools
import threading
from typing import Dict, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field
from contextvars import ContextVar
import traceback


# 上下文变量：存储当前运行ID和额外上下文
_run_id_var: ContextVar[str] = ContextVar('run_id', default='')
_context_var: ContextVar[Dict] = ContextVar('context', default={})


@dataclass
class LogContext:
    """日志上下文"""
    run_id: str = ""
    module: str = ""
    function: str = ""
    extra: Dict = field(default_factory=dict)


class StructuredFormatter(logging.Formatter):
    """结构化日志格式化器
    
    支持两种格式：
    1. 文本格式（默认）：适合控制台和文件
    2. JSON格式：适合日志收集系统
    """
    
    def __init__(self, fmt: str = None, datefmt: str = None, json_format: bool = False):
        """初始化格式化器
        
        Args:
            fmt: 格式字符串
            datefmt: 日期格式
            json_format: 是否使用JSON格式
        """
        super().__init__(fmt, datefmt)
        self.json_format = json_format
        
        # 默认文本格式
        self.default_fmt = (
            '%(asctime)s | %(levelname)-8s | %(run_id)s | %(name)s | '
            '%(message)s%(context)s'
        )
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录
        
        Args:
            record: 日志记录
            
        Returns:
            格式化后的字符串
        """
        # 添加运行ID
        record.run_id = _run_id_var.get() or '-'
        
        # 添加上下文信息
        context = _context_var.get()
        if context:
            record.context = f' | {json.dumps(context, ensure_ascii=False)}'
        else:
            record.context = ''
        
        if self.json_format:
            return self._format_json(record)
        else:
            return self._format_text(record)
    
    def _format_text(self, record: logging.LogRecord) -> str:
        """文本格式"""
        # 使用默认格式
        formatter = logging.Formatter(self.default_fmt)
        return formatter.format(record)
    
    def _format_json(self, record: logging.LogRecord) -> str:
        """JSON格式"""
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'run_id': record.run_id,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # 添加上下文
        context = _context_var.get()
        if context:
            log_data['context'] = context
        
        # 添加异常信息
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': ''.join(traceback.format_exception(*record.exc_info))
            }
        
        return json.dumps(log_data, ensure_ascii=False)


class StructuredLogger:
    """结构化日志器
    
    提供便捷的日志方法，自动添加运行ID和上下文信息
    """
    
    def __init__(self, name: str):
        """初始化日志器
        
        Args:
            name: 日志器名称
        """
        self._logger = logging.getLogger(name)
        self._name = name
    
    def _log(self, level: int, message: str, *args, **kwargs):
        """内部日志方法"""
        # 获取额外上下文
        extra_context = kwargs.pop('extra_context', None)
        
        if extra_context:
            # 临时设置上下文
            old_context = _context_var.get()
            new_context = {**old_context, **extra_context}
            _context_var.set(new_context)
            
            try:
                self._logger.log(level, message, *args, **kwargs)
            finally:
                _context_var.set(old_context)
        else:
            self._logger.log(level, message, *args, **kwargs)
    
    def debug(self, message: str, *args, **kwargs):
        """DEBUG级别日志"""
        self._log(logging.DEBUG, message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """INFO级别日志"""
        self._log(logging.INFO, message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """WARNING级别日志"""
        self._log(logging.WARNING, message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """ERROR级别日志"""
        self._log(logging.ERROR, message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        """CRITICAL级别日志"""
        self._log(logging.CRITICAL, message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """异常日志（包含堆栈信息）"""
        kwargs.setdefault('exc_info', True)
        self._log(logging.ERROR, message, *args, **kwargs)


class RunContext:
    """运行上下文管理器
    
    使用方式：
        with RunContext('run_001'):
            logger.info("message")  # 自动包含run_id='run_001'
    """
    
    def __init__(self, run_id: str, **extra_context):
        """初始化运行上下文
        
        Args:
            run_id: 运行ID
            **extra_context: 额外上下文信息
        """
        self.run_id = run_id
        self.extra_context = extra_context
        self._old_run_id = None
        self._old_context = None
    
    def __enter__(self):
        """进入上下文"""
        self._old_run_id = _run_id_var.get()
        self._old_context = _context_var.get()
        
        _run_id_var.set(self.run_id)
        _context_var.set(self.extra_context)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        _run_id_var.set(self._old_run_id)
        _context_var.set(self._old_context)
        
        return False  # 不抑制异常


def with_run_context(run_id: str, **extra_context):
    """运行上下文装饰器
    
    Args:
        run_id: 运行ID
        **extra_context: 额外上下文信息
        
    Returns:
        装饰器函数
        
    Example:
        @with_run_context('run_001', strategy='turtle')
        def my_function():
            logger.info("message")
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with RunContext(run_id, **extra_context):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def set_run_id(run_id: str):
    """设置当前运行ID
    
    Args:
        run_id: 运行ID
    """
    _run_id_var.set(run_id)


def get_run_id() -> str:
    """获取当前运行ID
    
    Returns:
        当前运行ID
    """
    return _run_id_var.get()


def set_context(key: str, value: Any):
    """设置上下文信息
    
    Args:
        key: 键
        value: 值
    """
    context = _context_var.get()
    new_context = {**context, key: value}
    _context_var.set(new_context)


def update_context(context: Dict):
    """更新上下文信息
    
    Args:
        context: 新的上下文字典
    """
    old_context = _context_var.get()
    new_context = {**old_context, **context}
    _context_var.set(new_context)


def clear_context():
    """清空上下文信息"""
    _context_var.set({})


def setup_logging(
    level: int = logging.INFO,
    json_format: bool = False,
    log_file: str = None
):
    """设置日志配置
    
    Args:
        level: 日志级别
        json_format: 是否使用JSON格式
        log_file: 日志文件路径（可选）
    """
    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 清除现有处理器
    root_logger.handlers.clear()
    
    # 创建格式化器
    formatter = StructuredFormatter(json_format=json_format)
    
    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 添加文件处理器（如果指定）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> StructuredLogger:
    """获取结构化日志器
    
    Args:
        name: 日志器名称
        
    Returns:
        结构化日志器实例
    """
    return StructuredLogger(name)


# 预定义的日志级别常量
LOG_LEVEL_DEBUG = logging.DEBUG      # 10
LOG_LEVEL_INFO = logging.INFO        # 20
LOG_LEVEL_WARNING = logging.WARNING  # 30
LOG_LEVEL_ERROR = logging.ERROR      # 40
LOG_LEVEL_CRITICAL = logging.CRITICAL  # 50
