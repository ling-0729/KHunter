"""
系统工具类
提供防止系统睡眠等功能
"""
import ctypes
import sys
import logging

logger = logging.getLogger(__name__)

# Windows API 常量
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


class SystemSleepPreventer:
    """
    防止系统进入睡眠模式的工具类
    仅在 Windows 系统上有效
    """
    
    def __init__(self):
        self._is_active = False
        self._original_state = None
        self._supported = sys.platform.startswith('win')
    
    def _set_thread_execution_state(self, state):
        """
        设置线程执行状态（Windows API）
        
        Args:
            state: 执行状态标志位
        """
        if not self._supported:
            return
        
        try:
            result = ctypes.windll.kernel32.SetThreadExecutionState(state)
            if result == 0:
                logger.warning("设置线程执行状态失败")
            return result
        except Exception as e:
            logger.error(f"调用 Windows API 失败: {str(e)}")
            return 0
    
    def start(self):
        """
        开始防止系统睡眠
        """
        if not self._supported:
            logger.info("当前系统不支持防止睡眠功能（仅支持Windows）")
            return
        
        if self._is_active:
            logger.info("防止睡眠功能已激活")
            return
        
        logger.info("启动防止系统睡眠...")
        self._original_state = self._set_thread_execution_state(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )
        self._is_active = True
        logger.info("已防止系统进入睡眠模式")
    
    def stop(self):
        """
        停止防止系统睡眠，恢复系统默认设置
        """
        if not self._supported:
            return
        
        if not self._is_active:
            return
        
        logger.info("停止防止系统睡眠...")
        self._set_thread_execution_state(ES_CONTINUOUS)
        self._is_active = False
        logger.info("已恢复系统睡眠设置")
    
    def __enter__(self):
        """
        上下文管理器入口
        """
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        上下文管理器出口
        """
        self.stop()
    
    @property
    def is_active(self):
        """
        返回当前是否正在防止系统睡眠
        """
        return self._is_active


# 创建全局实例
sleep_preventer = SystemSleepPreventer()


def prevent_sleep():
    """
    防止系统睡眠（便捷函数）
    """
    sleep_preventer.start()


def allow_sleep():
    """
    允许系统睡眠（便捷函数）
    """
    sleep_preventer.stop()
