"""
日志配置模块
提供集中的日志配置管理，使用QueueHandler避免日志操作阻塞主线程
支持按天轮转的日志文件，并自动清理10天前的旧日志
"""

import logging
import logging.handlers
import queue
import os
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta


class LogConfig:
    """日志配置管理类"""

    _queue_listener: Optional[logging.handlers.QueueListener] = None
    _log_queue: Optional[queue.Queue] = None
    # 日志保留天数
    LOG_RETENTION_DAYS = 10

    @classmethod
    def _clean_old_logs(cls, log_dir: Path, log_file_prefix: str) -> None:
        """
        清理指定天数以前的日志文件
        
        Args:
            log_dir: 日志目录
            log_file_prefix: 日志文件名前缀（不含日期和扩展名）
        """
        if not log_dir.exists():
            return
        
        # 计算过期日期
        cutoff_date = datetime.now() - timedelta(days=cls.LOG_RETENTION_DAYS)
        cutoff_str = cutoff_date.strftime('%Y-%m-%d')
        
        deleted_count = 0
        
        # 遍历日志目录中的文件
        for file_path in log_dir.iterdir():
            if file_path.is_file() and file_path.suffix == '.log':
                # 检查文件名是否符合模式: prefix.YYYY-MM-DD.log
                filename = file_path.stem  # 去掉扩展名
                parts = filename.split('.')
                
                # 检查是否是按日期命名的日志文件
                if len(parts) >= 2:
                    date_str = parts[-1]
                    try:
                        # 解析日期
                        file_date = datetime.strptime(date_str, '%Y-%m-%d')
                        file_date_str = date_str
                        
                        # 检查文件名前缀是否匹配
                        expected_prefix = '.'.join(parts[:-1])
                        if expected_prefix == log_file_prefix and file_date_str < cutoff_str:
                            # 删除过期日志
                            os.remove(file_path)
                            deleted_count += 1
                            logger = logging.getLogger(__name__)
                            logger.debug(f"已删除过期日志文件: {file_path.name}")
                    except ValueError:
                        # 不是有效的日期格式，跳过
                        continue
        
        if deleted_count > 0:
            logger = logging.getLogger(__name__)
            logger.info(f"已清理 {deleted_count} 个过期日志文件（保留最近{cls.LOG_RETENTION_DAYS}天）")

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

        # 提取日志文件名前缀（不含扩展名）
        log_file_prefix = log_file.rsplit('.', 1)[0] if '.' in log_file else log_file
        
        # 在设置日志之前清理旧日志
        cls._clean_old_logs(log_path, log_file_prefix)

        cls._log_queue = queue.Queue(-1)

        log_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 直接使用日期命名的日志文件，避免Windows文件锁问题
        date_str = datetime.now().strftime('%Y-%m-%d')
        dated_log_file = log_path / f"{log_file_prefix}.{date_str}.log"
        file_handler = logging.FileHandler(
            str(dated_log_file),
            encoding='utf-8'
        )
        
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(log_format)

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
        logger.info("日志系统初始化完成")
        logger.info(f"日志目录: {log_path}")
        logger.info(f"日志保留天数: {cls.LOG_RETENTION_DAYS}")
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
