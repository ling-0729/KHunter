"""缓存管理器"""

import os
import json
import pickle
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
import logging

class CacheManager:
    """缓存管理器"""
    
    def __init__(self, cache_dir="data/cache"):
        """
        初始化缓存管理器
        
        参数：
            cache_dir: 缓存目录路径
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True, parents=True)
        self.logger = logging.getLogger("cache_manager")
        self.logger.info(f"缓存管理器初始化完成，缓存目录: {self.cache_dir}")
    
    def _get_cache_key(self, prefix: str, **kwargs) -> str:
        """
        生成缓存键
        
        参数：
            prefix: 缓存键前缀
            **kwargs: 缓存参数
        
        返回：
            缓存键字符串
        """
        # 对参数进行排序，确保相同参数生成相同的键
        sorted_kwargs = sorted(kwargs.items(), key=lambda x: x[0])
        params_str = json.dumps(sorted_kwargs, ensure_ascii=False, sort_keys=True)
        hash_obj = hashlib.md5(params_str.encode('utf-8'))
        return f"{prefix}_{hash_obj.hexdigest()}"
    
    def _get_cache_file(self, key: str) -> Path:
        """
        获取缓存文件路径
        
        参数：
            key: 缓存键
        
        返回：
            缓存文件路径
        """
        return self.cache_dir / f"{key}.pkl"
    
    def set(self, prefix: str, data: any, expire_seconds: int = 3600, **kwargs) -> bool:
        """
        设置缓存
        
        参数：
            prefix: 缓存键前缀
            data: 要缓存的数据
            expire_seconds: 过期时间（秒）
            **kwargs: 缓存参数
        
        返回：
            是否成功设置缓存
        """
        try:
            key = self._get_cache_key(prefix, **kwargs)
            cache_file = self._get_cache_file(key)
            
            # 缓存数据结构
            cache_data = {
                'data': data,
                'expire_at': (datetime.now() + timedelta(seconds=expire_seconds)).timestamp()
            }
            
            # 写入缓存文件
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            
            self.logger.debug(f"缓存设置成功: {key}")
            return True
        except Exception as e:
            self.logger.error(f"设置缓存失败: {e}")
            return False
    
    def get(self, prefix: str, **kwargs) -> any:
        """
        获取缓存
        
        参数：
            prefix: 缓存键前缀
            **kwargs: 缓存参数
        
        返回：
            缓存的数据，如果缓存不存在或已过期则返回 None
        """
        try:
            key = self._get_cache_key(prefix, **kwargs)
            cache_file = self._get_cache_file(key)
            
            if not cache_file.exists():
                self.logger.debug(f"缓存不存在: {key}")
                return None
            
            # 读取缓存文件
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            
            # 检查是否过期
            if datetime.now().timestamp() > cache_data['expire_at']:
                self.logger.debug(f"缓存已过期: {key}")
                # 删除过期缓存
                self.delete(prefix, **kwargs)
                return None
            
            self.logger.debug(f"缓存获取成功: {key}")
            return cache_data['data']
        except Exception as e:
            self.logger.error(f"获取缓存失败: {e}")
            return None
    
    def delete(self, prefix: str, **kwargs) -> bool:
        """
        删除缓存
        
        参数：
            prefix: 缓存键前缀
            **kwargs: 缓存参数
        
        返回：
            是否成功删除缓存
        """
        try:
            key = self._get_cache_key(prefix, **kwargs)
            cache_file = self._get_cache_file(key)
            
            if cache_file.exists():
                cache_file.unlink()
                self.logger.debug(f"缓存删除成功: {key}")
            else:
                self.logger.debug(f"缓存不存在: {key}")
            
            return True
        except Exception as e:
            self.logger.error(f"删除缓存失败: {e}")
            return False
    
    def clear(self, prefix: str = None) -> bool:
        """
        清空缓存
        
        参数：
            prefix: 缓存键前缀，如果为 None 则清空所有缓存
        
        返回：
            是否成功清空缓存
        """
        try:
            count = 0
            for cache_file in self.cache_dir.glob("*.pkl"):
                if prefix:
                    if cache_file.stem.startswith(prefix):
                        cache_file.unlink()
                        count += 1
                else:
                    cache_file.unlink()
                    count += 1
            
            self.logger.info(f"缓存清空成功，共删除 {count} 个缓存文件")
            return True
        except Exception as e:
            self.logger.error(f"清空缓存失败: {e}")
            return False
    
    def get_cache_size(self) -> int:
        """
        获取缓存大小
        
        返回：
            缓存文件数量
        """
        try:
            return len(list(self.cache_dir.glob("*.pkl")))
        except Exception as e:
            self.logger.error(f"获取缓存大小失败: {e}")
            return 0
    
    def get_cache_info(self) -> list:
        """
        获取缓存信息
        
        返回：
            缓存信息列表
        """
        try:
            cache_info = []
            for cache_file in self.cache_dir.glob("*.pkl"):
                try:
                    with open(cache_file, 'rb') as f:
                        cache_data = pickle.load(f)
                    
                    expire_at = datetime.fromtimestamp(cache_data['expire_at'])
                    is_expired = datetime.now() > expire_at
                    
                    cache_info.append({
                        'key': cache_file.stem,
                        'size': cache_file.stat().st_size,
                        'expire_at': expire_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'is_expired': is_expired
                    })
                except Exception as e:
                    self.logger.warning(f"读取缓存文件 {cache_file} 失败: {e}")
            
            return cache_info
        except Exception as e:
            self.logger.error(f"获取缓存信息失败: {e}")
            return []

# 全局缓存管理器实例
cache_manager = CacheManager()
