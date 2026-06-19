#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库配置管理器
统一管理所有数据库相关配置
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

class DatabaseConfig:
    """数据库配置管理类"""
    
    _instance = None
    _config = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(DatabaseConfig, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """加载数据库配置"""
        config_path = Path(__file__).parent.parent / 'config' / 'database.yaml'
        
        if not config_path.exists():
            logger.warning(f"数据库配置文件不存在: {config_path}，使用默认配置")
            self._config = self._get_default_config()
        else:
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self._config = yaml.safe_load(f)
                logger.info(f"数据库配置加载成功: {config_path}")
            except Exception as e:
                logger.error(f"加载数据库配置失败: {e}，使用默认配置")
                self._config = self._get_default_config()
    
    @staticmethod
    def _get_default_config():
        """获取默认配置"""
        return {
            'database': {
                'type': 'sqlite',
                'path': 'data/stock_selection.db',
                'name': 'stock_selection',
                'timeout': 30,
                'foreign_keys': True,
                'wal_mode': True
            },
            'initialization': {
                'sql_script': 'data/DataSql.sql',
                'auto_init': True,
                'init_data_script': 'data/InitData.sql'
            },
            'backup': {
                'enabled': False,
                'directory': 'data/backups',
                'frequency': 24
            }
        }
    
    def get_db_path(self) -> str:
        """获取数据库文件路径（绝对路径）"""
        db_path = self._config['database']['path']
        
        # 如果是相对路径，转换为绝对路径
        if not os.path.isabs(db_path):
            project_root = Path(__file__).parent.parent
            db_path = str(project_root / db_path)
        
        return db_path
    
    def get_db_name(self) -> str:
        """获取数据库名称"""
        return self._config['database']['name']
    
    def get_db_type(self) -> str:
        """获取数据库类型"""
        return self._config['database']['type']
    
    def get_timeout(self) -> int:
        """获取连接超时时间"""
        return self._config['database'].get('timeout', 30)
    
    def is_foreign_keys_enabled(self) -> bool:
        """是否启用外键约束"""
        return self._config['database'].get('foreign_keys', True)
    
    def is_wal_mode_enabled(self) -> bool:
        """是否启用 WAL 模式"""
        return self._config['database'].get('wal_mode', True)
    
    def get_sql_script_path(self) -> str:
        """获取 SQL 脚本路径"""
        sql_path = self._config['initialization']['sql_script']
        
        if not os.path.isabs(sql_path):
            project_root = Path(__file__).parent.parent
            sql_path = str(project_root / sql_path)
        
        return sql_path
    
    def is_auto_init_enabled(self) -> bool:
        """是否启用自动初始化"""
        return self._config['initialization'].get('auto_init', True)
    
    def get_init_data_script_path(self) -> str:
        """获取初始化数据脚本路径"""
        init_path = self._config['initialization']['init_data_script']
        
        if not os.path.isabs(init_path):
            project_root = Path(__file__).parent.parent
            init_path = str(project_root / init_path)
        
        return init_path
    
    def is_backup_enabled(self) -> bool:
        """是否启用备份"""
        return self._config['backup'].get('enabled', False)
    
    def get_backup_directory(self) -> str:
        """获取备份目录"""
        backup_dir = self._config['backup']['directory']
        
        if not os.path.isabs(backup_dir):
            project_root = Path(__file__).parent.parent
            backup_dir = str(project_root / backup_dir)
        
        return backup_dir
    
    def get_backup_frequency(self) -> int:
        """获取备份频率（小时）"""
        return self._config['backup'].get('frequency', 24)
    
    def get_config(self) -> dict:
        """获取完整配置"""
        return self._config
    
    def reload(self):
        """重新加载配置"""
        self._load_config()
        logger.info("数据库配置已重新加载")


# 全局配置实例
db_config = DatabaseConfig()


def get_db_path() -> str:
    """获取数据库路径的便捷函数"""
    return db_config.get_db_path()


def get_db_config() -> DatabaseConfig:
    """获取数据库配置实例的便捷函数"""
    return db_config
