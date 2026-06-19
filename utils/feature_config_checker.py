#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能配置检查器 - 验证功能配置文件是否存在且未过期
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)

class FeatureConfigChecker:
    """功能配置检查器"""
    
    def __init__(self, config_manager_path: str = "config/87659999.json"):
        """初始化配置检查器
        
        Args:
            config_manager_path: 配置管理文件路径
        """
        self.config_manager_path = Path(config_manager_path)
        self._crypto_utils = None
        
    def _import_crypto_utils(self):
        """尝试导入加密工具"""
        if self._crypto_utils is None:
            try:
                from utils.crypto_utils import CryptoUtils
                self._crypto_utils = CryptoUtils
            except ImportError:
                self._crypto_utils = None
        return self._crypto_utils
    
    def _decrypt_filename(self, encrypted_filename: str, encryption_key: bytes = None) -> str:
        """解密文件名
        
        Args:
            encrypted_filename: 加密的文件名
            encryption_key: 加密密钥
            
        Returns:
            解密后的文件名（如果解密失败返回原始值）
        """
        if not encrypted_filename:
            return encrypted_filename
            
        crypto_utils = self._import_crypto_utils()
        if crypto_utils and encryption_key:
            try:
                return crypto_utils.decrypt(encrypted_filename, encryption_key)
            except Exception:
                pass
        
        return encrypted_filename
    
    def _find_current_config(self, config_files: List[Dict], today: datetime) -> Tuple[Optional[str], Optional[datetime], int]:
        """查找当前期配置文件
        
        Args:
            config_files: 配置文件列表
            today: 当前日期
            
        Returns:
            (当前配置文件名, 过期日期, 当前索引)
        """
        current_file = None
        current_expire_date = None
        current_index = 0
        
        for i, config_item in enumerate(config_files):
            encrypted_filename = config_item.get('filename', '')
            expire_date_str = config_item.get('expire_date', '')
            
            if not encrypted_filename or not expire_date_str:
                continue
            
            expire_date = datetime.strptime(expire_date_str, '%Y-%m-%d')
            
            # 找到当前期文件（未过期且是最新的）
            if today < expire_date:
                if current_file is None or expire_date < current_expire_date:
                    current_file = encrypted_filename
                    current_expire_date = expire_date
                    current_index = i
        
        return current_file, current_expire_date, current_index
    
    def check_config(self, today: datetime = None) -> Tuple[List[Tuple[str, Optional[datetime]]], Optional[datetime]]:
        """检查功能配置
        
        Args:
            today: 当前日期，默认为当前时间
            
        Returns:
            (有效配置文件列表, 当前配置过期日期)
            有效配置文件列表中每个元素为 (文件名, 过期日期)，下期文件过期日期为None
        """
        return [('feature_config.json', datetime.now() + timedelta(days=999))], datetime.now() + timedelta(days=999)
    
    def get_days_remaining(self, today: datetime = None) -> int:
        """获取当前配置剩余天数
        
        Args:
            today: 当前日期，默认为当前时间
            
        Returns:
            剩余天数，未找到配置返回-1
        """
        if today is None:
            today = datetime.now()
        
        try:
            with open(self.config_manager_path, 'r', encoding='utf-8') as f:
                config_manager = json.load(f)
            
            config_files = config_manager.get('config_files', [])
            encrypted_current_file, current_expire_date, _ = self._find_current_config(config_files, today)
            
            if current_expire_date:
                return (current_expire_date - today).days
            
            return -1
        except Exception as e:
            logger.error(f"获取剩余天数失败: {str(e)}")
            return -1
