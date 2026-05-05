#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import random

class ProxyManager:
    """
    代理服务器管理类
    从配置文件中读取代理服务器列表，并提供随机选择代理的功能
    """
    
    def __init__(self):
        """初始化代理管理器"""
        self.proxies = self._load_proxies()
    
    def _load_proxies(self):
        """
        从配置文件中加载代理服务器列表
        
        Returns:
            list: 代理服务器列表
        """
        proxy_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'proxy.txt')
        try:
            with open(proxy_file, 'r', encoding='utf-8') as f:
                proxies = [line.strip() for line in f if line.strip()]
            return proxies
        except Exception:
            return []
    
    def get_proxies(self):
        """
        随机获取一个代理服务器
        
        Returns:
            dict or None: 代理服务器配置，格式为 {"http": proxy, "https": proxy}
        """
        if not self.proxies:
            return None
        
        proxy = random.choice(self.proxies)
        return {"http": proxy, "https": proxy}


# 创建全局实例
proxy_manager = ProxyManager()
