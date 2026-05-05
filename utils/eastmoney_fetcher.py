#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
from requests.adapters import HTTPAdapter
from pathlib import Path
import time
import random
import logging

# 配置日志
logger = logging.getLogger(__name__)

# 默认Cookie（参考 stock-master 项目）
DEFAULT_COOKIE = 'st_si=78948464251292; st_psi=20260205091253851-119144370567-1089607836; st_pvi=07789985376191; st_sp=2026-02-05%2009%3A11%3A13; st_inirUrl=https%3A%2F%2Fxuangu.eastmoney.com%2FResult; st_sn=12; st_asi=20260205091253851-119144370567-1089607836-webznxg.dbssk.qxg-1'


class EastMoneyFetcher:
    """
    东方财富网数据获取器
    封装了Cookie管理、会话管理和请求发送功能
    支持多Cookie轮换：文件中每行一个Cookie，失败后自动切换下一个
    参考 stock-master 项目实现
    """

    def __init__(self):
        """初始化获取器"""
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        # 加载所有Cookie（文件中每行一个）
        self._cookies = self._load_cookies()
        self._cookie_index = 0  # 当前使用的Cookie索引
        self.session = self._create_session()
        self.proxies = self._get_proxies()

    def _load_cookies(self):
        """
        从文件加载所有Cookie，每行一个
        返回Cookie列表
        """
        cookies = []

        # 1. 尝试从环境变量获取
        env_cookie = os.environ.get('EAST_MONEY_COOKIE')
        if env_cookie:
            cookies.append(env_cookie)
            logger.debug(f"从环境变量加载了 1 个Cookie")

        # 2. 尝试从文件获取（每行一个Cookie）
        cookie_file = Path(os.path.join(self.base_dir, 'config', 'eastmoney_cookie.txt'))
        if cookie_file.exists():
            with open(cookie_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        cookies.append(line)
            logger.debug(f"从文件加载了 {len(cookies)} 个Cookie")

        # 3. 如果没有文件Cookie，添加默认Cookie
        if not cookies:
            cookies.append(DEFAULT_COOKIE)
            logger.debug("使用默认Cookie")

        return cookies

    def _get_current_cookie(self):
        """
        获取当前使用的Cookie
        """
        if self._cookie_index < len(self._cookies):
            return self._cookies[self._cookie_index]
        return DEFAULT_COOKIE

    def _switch_to_next_cookie(self):
        """
        切换到下一个Cookie
        返回是否还有可用的Cookie
        """
        next_index = self._cookie_index + 1
        if next_index < len(self._cookies):
            self._cookie_index = next_index
            cookie = self._cookies[self._cookie_index]
            self.session.cookies.update({'Cookie': cookie})
            logger.info(f"切换到第 {self._cookie_index + 1}/{len(self._cookies)} 个Cookie")
            return True
        else:
            # 所有文件Cookie都失败了，回退到默认Cookie
            logger.warning(f"所有 {len(self._cookies)} 个Cookie都失败，回退到默认Cookie")
            self.session.cookies.update({'Cookie': DEFAULT_COOKIE})
            return False

    def _create_session(self):
        """创建并配置会话，与 stock-master 保持一致"""
        session = requests.Session()

        # 禁用urllib3内置重试，由make_request统一控制重试和Cookie切换
        adapter = HTTPAdapter(
            max_retries=0,
            pool_connections=50,
            pool_maxsize=50
        )

        # 为http和https请求添加适配器
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # 设置请求头，与 stock-master 保持一致
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://quote.eastmoney.com/',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Connection': 'keep-alive',
        }
        session.headers.update(headers)

        # 设置第一个Cookie
        session.cookies.update({'Cookie': self._get_current_cookie()})
        return session

    def _get_proxies(self):
        """获取代理服务器配置"""
        try:
            from utils.proxy_manager import proxy_manager
            return proxy_manager.get_proxies()
        except Exception as e:
            logger.error(f"获取代理服务器失败: {e}")
            return None

    def make_request(self, url, params=None, retry=3, timeout=10):
        """
        发送GET请求，失败后直接切换Cookie，不重试
        :param url: 请求URL
        :param params: 请求参数
        :param retry: 可切换Cookie的最大次数
        :param timeout: 超时时间
        :return: 响应对象
        """
        for i in range(retry):
            try:
                response = self.session.get(
                    url,
                    proxies=self.proxies,
                    params=params,
                    timeout=timeout
                )
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                logger.warning(f"请求错误: {e}")
                # 直接切换到下一个Cookie，不重试
                if self._switch_to_next_cookie():
                    continue
                raise

    def make_post_request(self, url, data=None, json=None, params=None, retry=3, timeout=60):
        """
        发送POST请求，失败后直接切换Cookie，不重试
        :param url: 请求URL
        :param data: 请求数据（表单形式）
        :param json: 请求数据（JSON形式）
        :param params: URL参数
        :param retry: 可切换Cookie的最大次数
        :param timeout: 超时时间
        :return: 响应对象
        """
        for i in range(retry):
            try:
                response = self.session.post(
                    url,
                    proxies=self.proxies,
                    params=params,
                    data=data,
                    json=json,
                    timeout=timeout
                )
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                logger.warning(f"POST请求错误: {e}")
                if self._switch_to_next_cookie():
                    continue
                raise

    def update_cookie(self, new_cookie):
        """
        更新Cookie
        :param new_cookie: 新的Cookie值
        """
        if new_cookie:
            self._cookies = [new_cookie]
            self._cookie_index = 0
            self.session.cookies.update({'Cookie': new_cookie})


# 创建全局实例，供所有函数使用
fetcher = EastMoneyFetcher()
