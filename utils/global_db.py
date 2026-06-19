"""
全局数据库管理器模块

提供一个全局的 DBManager 实例，供所有模块共享，避免创建多个数据库连接导致的死锁问题。
"""

from utils.db_manager import DBManager

# 创建全局 DBManager 实例
global_db_manager = DBManager()

# 导出全局实例，供其他模块使用
def get_global_db():
    """
    获取全局数据库管理器实例
    
    Returns:
        DBManager: 全局数据库管理器实例
    """
    return global_db_manager