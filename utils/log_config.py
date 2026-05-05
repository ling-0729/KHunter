"""
日志配置模块
提供集中的日志配置管理，使用QueueHandler避免日志操作阻塞主线程
支持按天轮转的日志文件
"""

import logging
import logging.handlers
import queue
from pathlib import Path
from typing import Optional
from datetime import datetime


class LogConfig:
    """日志配置管理类"""

    _queue_listener: Optional[logging.handlers.QueueListener] = None
    _log_queue: Optional[queue.Queue] = None

    @classmethod
    def setup_logging(cls, log_dir: str = "logs", log_file: str = "app.log") -> None:
        """
        设置日志配置，使用QueueHandler避免阻塞，支持按天轮转日志

        Args:
            log_dir: 日志目录
            log_file: 日志文件名（不含日期后缀）
        """
        log_path = Path(log_dir)
        log_path.mkdir(exist_ok=True, parents=True)

        log_file_path = log_path / log_file

        cls._log_queue = queue.Queue(-1)

        log_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 使用 TimedRotatingFileHandler 实现按天轮转日志
        # when='midnight': 每天午夜零点轮转
        # interval=1: 每1个when单位轮转一次
        # backupCount=30: 保留最近30天的日志文件
        # encoding='utf-8': 指定UTF-8编码
        file_handler = logging.handlers.TimedRotatingFileHandler(
            str(log_file_path),
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8',
            utc=False  # 使用本地时间
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(log_format)

        # 设置日志文件名后缀格式（包含日期）
        file_handler.suffix = "%Y-%m-%d.log"

        # 添加自定义扩展名，在轮转时不添加额外扩展名
        file_handler.extMatch = None

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(log_format)

        queue_handler = logging.handlers.QueueHandler(cls._log_queue)
        queue_handler.setLevel(logging.DEBUG)

        cls._queue_listener = logging.handlers.QueueListener(
            cls._log_queue,
            file_handler,
            console_handler,
            respect_handler_level=True
        )
        cls._queue_listener.start()

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        if root_logger.handlers:
            root_logger.handlers.clear()

        root_logger.addHandler(queue_handler)

        logger = logging.getLogger(__name__)
        logger.info("=" * 60)
        logger.info("日志系统初始化完成（使用 TimedRotatingFileHandler，按天轮转）")
        logger.info(f"日志目录: {log_path}")
        logger.info(f"日志文件: {log_file_path}.YYYY-MM-DD.log")
        logger.info(f"保留天数: 30天")
        logger.info("=" * 60)

    @classmethod
    def shutdown_logging(cls) -> None:
        """关闭日志系统，确保所有日志都被写入"""
        if cls._queue_listener is not None:
            cls._queue_listener.stop()
            cls._queue_listener = None

        if cls._log_queue is not None:
            cls._log_queue = None


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        logging.Logger: 日志记录器
    """
    return logging.getLogger(name)
