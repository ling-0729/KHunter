"""
策略执行方案管理模块
支持多组策略组合（选股+择时）的配置、保存和加载
"""

import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class StrategyCombination:
    """策略组合类（一个选股策略 + 一个择时策略）"""
    
    def __init__(self, selection_strategy: str, timing_strategy: str, 
                enabled: bool = True, combination_id: str = None):
        """
        初始化策略组合
        
        Args:
            selection_strategy: 选股策略名称
            timing_strategy: 择时策略名称
            enabled: 是否启用该组合
            combination_id: 组合唯一标识，不传则自动生成
        """
        self.id = combination_id or self._generate_id()
        self.selection_strategy = selection_strategy
        self.timing_strategy = timing_strategy
        self.enabled = enabled
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        return str(uuid.uuid4())[:8]  # 使用短UUID
    
    def to_dict(self) -> dict:
        """转换为字典，用于序列化"""
        return {
            'id': self.id,
            'selection_strategy': self.selection_strategy,
            'timing_strategy': self.timing_strategy,
            'enabled': self.enabled
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'StrategyCombination':
        """从字典创建策略组合对象"""
        return cls(
            combination_id=data.get('id'),
            selection_strategy=data['selection_strategy'],
            timing_strategy=data['timing_strategy'],
            enabled=data.get('enabled', True)
        )
    
    def __eq__(self, other):
        """判断两个组合是否相等"""
        if not isinstance(other, StrategyCombination):
            return False
        return self.id == other.id
    
    def __repr__(self):
        """返回组合的字符串表示"""
        return f"StrategyCombination(id={self.id}, selection={self.selection_strategy}, timing={self.timing_strategy}, enabled={self.enabled})"


class ExecutionPlan:
    """执行方案类，管理一组策略组合"""
    
    PLANS_DIR = 'config/execution_plans'
    MAX_COMBINATIONS = 20
    
    def __init__(self, name: str, description: str = "", plan_id: str = None):
        """
        初始化执行方案
        
        Args:
            name: 方案名称（唯一）
            description: 方案描述
            plan_id: 方案唯一标识，不传则自动生成
        """
        self.id = plan_id or self._generate_id()
        self.name = name
        self.description = description
        self.combinations = []  # List[StrategyCombination]（按顺序执行）
        self.config_ref = 'default'  # 回测配置引用
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        return str(uuid.uuid4())
    
    def add_combination(self, combination: StrategyCombination, update_timestamp: bool = True):
        """
        添加策略组合（追加到列表末尾）
        
        Args:
            combination: 策略组合对象
            update_timestamp: 是否更新updated_at时间戳，默认为True
        
        Raises:
            ValueError: 当组合数量超过最大值时
        """
        if len(self.combinations) >= self.MAX_COMBINATIONS:
            raise ValueError(f"策略组合数量不能超过 {self.MAX_COMBINATIONS} 组")
        
        self.combinations.append(combination)
        if update_timestamp:
            self.updated_at = datetime.now().isoformat()
        logger.info(f"添加策略组合: {combination.id} -> {self.id}")
    
    def insert_combination(self, index: int, combination: StrategyCombination):
        """
        在指定位置插入策略组合
        
        Args:
            index: 插入位置
            combination: 策略组合对象
        
        Raises:
            ValueError: 当组合数量超过最大值时
        """
        if len(self.combinations) >= self.MAX_COMBINATIONS:
            raise ValueError(f"策略组合数量不能超过 {self.MAX_COMBINATIONS} 组")
        
        self.combinations.insert(index, combination)
        self.updated_at = datetime.now().isoformat()
        logger.info(f"插入策略组合: {combination.id} at index {index}")
    
    def remove_combination(self, combination_id: str):
        """
        移除指定ID的策略组合
        
        Args:
            combination_id: 组合ID
        """
        original_count = len(self.combinations)
        self.combinations = [c for c in self.combinations if c.id != combination_id]
        if len(self.combinations) < original_count:
            self.updated_at = datetime.now().isoformat()
            logger.info(f"移除策略组合: {combination_id}")
    
    def get_enabled_combinations(self) -> list:
        """获取所有启用的组合（按顺序）"""
        return [c for c in self.combinations if c.enabled]
    
    def move_combination(self, from_index: int, to_index: int):
        """
        移动组合位置（调整执行顺序）
        
        Args:
            from_index: 原位置
            to_index: 目标位置
        """
        if 0 <= from_index < len(self.combinations) and 0 <= to_index < len(self.combinations):
            combination = self.combinations.pop(from_index)
            self.combinations.insert(to_index, combination)
            self.updated_at = datetime.now().isoformat()
            logger.info(f"移动组合: index {from_index} -> {to_index}")
    
    def to_dict(self) -> dict:
        """转换为字典，用于序列化"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'combinations': [c.to_dict() for c in self.combinations],
            'config_ref': self.config_ref,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ExecutionPlan':
        """从字典创建执行方案对象"""
        plan = cls(
            plan_id=data.get('id'),
            name=data['name'],
            description=data.get('description', '')
        )
        plan.config_ref = data.get('config_ref', 'default')
        plan.created_at = data.get('created_at', datetime.now().isoformat())
        plan.updated_at = data.get('updated_at', datetime.now().isoformat())
        
        # 添加组合时不更新时间戳，保持原有的updated_at
        for combo_data in data.get('combinations', []):
            plan.add_combination(StrategyCombination.from_dict(combo_data), update_timestamp=False)
        
        return plan
    
    def save(self):
        """保存方案到JSON文件"""
        # 确保目录存在
        os.makedirs(self.PLANS_DIR, exist_ok=True)
        
        # 检查方案名称唯一性
        existing_plans = self.list_plans()
        for plan in existing_plans:
            if plan.id != self.id and plan.name == self.name:
                raise ValueError(f"方案名称 '{self.name}' 已存在")
        
        # 保存文件
        file_path = os.path.join(self.PLANS_DIR, f"{self.id}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"执行方案已保存: {file_path}")
    
    @classmethod
    def load(cls, plan_id: str) -> 'ExecutionPlan':
        """
        从JSON文件加载方案
        
        Args:
            plan_id: 方案ID
        
        Returns:
            ExecutionPlan对象
        
        Raises:
            FileNotFoundError: 当方案文件不存在时
        """
        file_path = os.path.join(cls.PLANS_DIR, f"{plan_id}.json")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"方案文件不存在: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info(f"执行方案已加载: {plan_id}")
        return cls.from_dict(data)
    
    @classmethod
    def list_plans(cls) -> list:
        """获取所有方案列表（按创建时间倒序）"""
        plans = []
        os.makedirs(cls.PLANS_DIR, exist_ok=True)
        
        for filename in os.listdir(cls.PLANS_DIR):
            if filename.endswith('.json'):
                plan_id = filename[:-5]
                try:
                    plan = cls.load(plan_id)
                    plans.append(plan)
                except Exception as e:
                    logger.warning(f"加载方案失败 {plan_id}: {e}")
        
        # 按创建时间倒序排列
        return sorted(plans, key=lambda p: p.created_at, reverse=True)
    
    def delete(self):
        """删除方案文件"""
        file_path = os.path.join(self.PLANS_DIR, f"{self.id}.json")
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"执行方案已删除: {file_path}")
    
    @classmethod
    def find_by_name(cls, name: str) -> Optional['ExecutionPlan']:
        """
        根据名称查找方案
        
        Args:
            name: 方案名称
        
        Returns:
            匹配的方案对象，未找到返回None
        """
        plans = cls.list_plans()
        for plan in plans:
            if plan.name == name:
                return plan
        return None
    
    def validate(self) -> bool:
        """
        验证方案是否有效
        
        Returns:
            True表示有效，False表示无效
        """
        if not self.name or len(self.name.strip()) == 0:
            logger.error("方案名称不能为空")
            return False
        
        if len(self.combinations) == 0:
            logger.error("方案至少需要包含一个策略组合")
            return False
        
        for combo in self.combinations:
            if not combo.selection_strategy or not combo.timing_strategy:
                logger.error(f"组合 {combo.id} 的策略名称不能为空")
                return False
        
        return True
    
    def __repr__(self):
        """返回方案的字符串表示"""
        return f"ExecutionPlan(id={self.id}, name={self.name}, combinations={len(self.combinations)})"