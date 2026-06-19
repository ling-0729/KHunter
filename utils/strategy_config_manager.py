#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略配置管理器
负责读取和管理策略配置，包括支撑位计算方法等
"""

import yaml
import logging
from typing import Dict, Optional, Any
import os

# 配置日志
logger = logging.getLogger(__name__)


class StrategyConfigManager:
    """
    策略配置管理器
    从 YAML 配置文件读取策略配置
    """
    
    # 配置文件路径
    CONFIG_FILE = 'config/strategy_params.yaml'
    
    # 支撑位计算方法
    VALID_SUPPORT_METHODS = {
        'ma20', 'key_open', 'resistance_break', 'key_close_5', 'key_close'
    }
    
    # 默认支撑位计算方法
    DEFAULT_SUPPORT_METHOD = 'ma20'
    
    def __init__(self, config_file: Optional[str] = None):
        """
        初始化策略配置管理器
        
        参数：
            config_file: 配置文件路径，默认为 config/strategy_params.yaml
        """
        # config_file: 配置文件路径，类型str，可选
        self.config_file = config_file or self.CONFIG_FILE
        self.config = {}
        self._load_config()
        logger.info("策略配置管理器初始化完成")
    
    # ==================== 公开方法 ====================
    
    def get_support_method(self, strategy_name: str) -> str:
        """
        获取策略的支撑位计算方法
        
        参数：
            strategy_name: 策略名称（可以是类名或显示名称，支持组合策略）
        
        返回：
            str: 支撑位计算方法
        """
        # strategy_name: 策略名称，类型str，必填
        try:
            # 1. 尝试直接通过策略名称查找
            if strategy_name in self.config.get('strategies', {}):
                strategy_config = self.config['strategies'][strategy_name]
                support_method = strategy_config.get(
                    'support_method', self.DEFAULT_SUPPORT_METHOD
                )
                
                # 2. 验证支撑位计算方法是否有效
                if support_method not in self.VALID_SUPPORT_METHODS:
                    logger.warning(
                        f"策略 {strategy_name} 的支撑位计算方法 {support_method} 无效，"
                        f"使用默认方法 {self.DEFAULT_SUPPORT_METHOD}"
                    )
                    return self.DEFAULT_SUPPORT_METHOD
                
                logger.debug(f"获取策略 {strategy_name} 的支撑位计算方法: {support_method}")
                return support_method
            
            # 3. 如果直接查找失败，尝试通过显示名称查找
            for strategy_key, strategy_config in self.config.get('strategies', {}).items():
                display_name = strategy_config.get('display_name')
                if display_name == strategy_name:
                    support_method = strategy_config.get(
                        'support_method', self.DEFAULT_SUPPORT_METHOD
                    )
                    
                    # 4. 验证支撑位计算方法是否有效
                    if support_method not in self.VALID_SUPPORT_METHODS:
                        logger.warning(
                            f"策略 {strategy_name} 的支撑位计算方法 {support_method} 无效，"
                            f"使用默认方法 {self.DEFAULT_SUPPORT_METHOD}"
                        )
                        return self.DEFAULT_SUPPORT_METHOD
                    
                    logger.debug(f"通过显示名称获取策略 {strategy_name} 的支撑位计算方法: {support_method}")
                    return support_method
            
            # 5. 尝试处理策略名称变体（如添加或删除"策略"后缀）
            variants = [
                strategy_name + "策略",  # 添加"策略"后缀
                strategy_name.replace("策略", "")  # 删除"策略"后缀
            ]
            
            for variant in variants:
                # 尝试通过变体名称查找
                if variant in self.config.get('strategies', {}):
                    strategy_config = self.config['strategies'][variant]
                    support_method = strategy_config.get(
                        'support_method', self.DEFAULT_SUPPORT_METHOD
                    )
                    
                    # 验证支撑位计算方法是否有效
                    if support_method not in self.VALID_SUPPORT_METHODS:
                        continue
                    
                    logger.debug(f"通过变体名称获取策略 {strategy_name} 的支撑位计算方法: {support_method}")
                    return support_method
                
                # 尝试通过变体作为显示名称查找
                for strategy_key, strategy_config in self.config.get('strategies', {}).items():
                    display_name = strategy_config.get('display_name')
                    if display_name == variant:
                        support_method = strategy_config.get(
                            'support_method', self.DEFAULT_SUPPORT_METHOD
                        )
                        
                        # 验证支撑位计算方法是否有效
                        if support_method not in self.VALID_SUPPORT_METHODS:
                            continue
                        
                        logger.debug(f"通过变体显示名称获取策略 {strategy_name} 的支撑位计算方法: {support_method}")
                        return support_method
            
            # 6. 尝试处理组合策略（如"策略1+策略2"）
            if "+" in strategy_name:
                # 分割组合策略为单个策略
                individual_strategies = strategy_name.split("+")
                
                # 对每个单个策略，尝试获取其支撑位计算方法
                for individual_strategy in individual_strategies:
                    # 去除空格
                    individual_strategy = individual_strategy.strip()
                    
                    # 尝试获取单个策略的支撑位计算方法
                    individual_support_method = self.get_support_method(individual_strategy)
                    
                    # 如果找到有效方法，返回它
                    if individual_support_method != self.DEFAULT_SUPPORT_METHOD:
                        logger.debug(f"通过组合策略中的单个策略 '{individual_strategy}' 获取支撑位计算方法: {individual_support_method}")
                        return individual_support_method
            
            # 7. 如果所有方式都找不到，使用默认方法
            logger.warning(
                f"策略 {strategy_name} 不存在，使用默认方法 {self.DEFAULT_SUPPORT_METHOD}"
            )
            return self.DEFAULT_SUPPORT_METHOD
        
        except Exception as e:
            logger.error(f"获取支撑位计算方法失败: {str(e)}，使用默认方法")
            return self.DEFAULT_SUPPORT_METHOD
    
    def get_strategy_config(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """
        获取策略的完整配置
        
        参数：
            strategy_name: 策略名称（可以是类名或显示名称）
        
        返回：
            Dict: 策略配置，如果不存在返回 None
        """
        # strategy_name: 策略名称，类型str，必填
        try:
            # 1. 尝试直接通过策略名称查找
            if strategy_name in self.config.get('strategies', {}):
                return self.config['strategies'][strategy_name]
            
            # 2. 如果直接查找失败，尝试通过显示名称查找
            for strategy_key, strategy_config in self.config.get('strategies', {}).items():
                if strategy_config.get('display_name') == strategy_name:
                    return strategy_config
            
            # 3. 如果两种方式都找不到，返回 None
            logger.warning(f"策略 {strategy_name} 不存在")
            return None
        
        except Exception as e:
            logger.error(f"获取策略配置失败: {str(e)}")
            return None
    
    def get_all_strategies(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有策略配置
        
        返回：
            Dict: 所有策略配置
        """
        try:
            # 1. 返回所有策略配置
            return self.config.get('strategies', {})
        
        except Exception as e:
            logger.error(f"获取所有策略配置失败: {str(e)}")
            return {}
    
    def reload_config(self) -> bool:
        """
        重新加载配置文件
        
        返回：
            bool: 是否加载成功
        """
        try:
            # 1. 重新加载配置
            self._load_config()
            logger.info("配置文件重新加载成功")
            return True
        
        except Exception as e:
            logger.error(f"重新加载配置文件失败: {str(e)}")
            return False
    
    # ==================== 私有方法 ====================
    
    def _load_config(self) -> None:
        """
        从 YAML 文件加载配置
        """
        try:
            # 1. 检查配置文件是否存在
            if not os.path.exists(self.config_file):
                logger.warning(f"配置文件 {self.config_file} 不存在")
                self.config = {'strategies': {}}
                return
            
            # 2. 读取 YAML 文件
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {'strategies': {}}
            
            # 3. 验证配置结构
            if 'strategies' not in self.config:
                logger.warning("配置文件中没有 strategies 字段")
                self.config = {'strategies': {}}
            
            # 4. 记录加载的策略数量
            strategy_count = len(self.config.get('strategies', {}))
            logger.info(f"配置文件加载成功，共 {strategy_count} 个策略")
        
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            self.config = {'strategies': {}}

