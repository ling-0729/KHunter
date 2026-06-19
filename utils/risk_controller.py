"""
风控整合模块 - 整合所有风控功能，提供统一的接口
"""
import logging
from typing import Optional
from datetime import datetime
from pathlib import Path

from utils.index_data_fetcher import IndexDataFetcher
from utils.var_calculator import EnhancedVaRCalculator
from utils.risk_manager import RiskManager, RiskStatus
from utils.risk_config_loader import RiskConfigLoader

# 配置日志
logger = logging.getLogger(__name__)


class RiskController:
    """风控控制器 - 整合所有风控功能"""
    
    def __init__(self, config_path: str = 'config/risk_config.yaml'):
        """
        初始化风控控制器
        
        参数：
            config_path: 配置文件路径
        """
        # 加载配置
        self.config_loader = RiskConfigLoader(config_path)
        config = self.config_loader.load_config()
        
        if config is None:
            logger.error("加载风控配置失败，使用默认配置")
            config = {}
        
        # 提取风控配置
        risk_config = config.get('risk', {})
        
        # 获取基础配置
        self.lookback_days = risk_config.get('lookback_days', 500)
        self.confidence_level = risk_config.get('confidence_level', 0.99)
        
        # 初始化各模块
        self.index_fetcher = IndexDataFetcher()
        
        # 使用增强版VaR计算器，支持多种计算方法
        var_method = risk_config.get('calculation_method', 'hybrid')
        lambda_ewma = risk_config.get('lambda_ewma', 0.94)
        self.var_calculator = EnhancedVaRCalculator(
            method=var_method,
            lambda_ewma=lambda_ewma,
            lookback_days=self.lookback_days
        )
        
        self.risk_manager = RiskManager(risk_config)
        
        # 历史风控状态缓存
        self.risk_history = []
        self._load_risk_history()
        
        logger.info("RiskController 初始化完成")
    
    def get_risk_status(self, date: str = None, force_refresh: bool = False) -> Optional[RiskStatus]:
        """
        获取指定日期的风控状态
        
        参数：
            date: 日期字符串，格式YYYY-MM-DD，默认为当前日期
            force_refresh: 是否强制刷新（不使用缓存）
            
        返回：
            RiskStatus: 风控状态对象，失败返回None
        """
        # 设置默认日期
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        # 如果不强制刷新，优先从数据库获取
        if not force_refresh:
            # 1. 先检查数据库
            try:
                from trading.risk_status_dao import RiskStatusDAO
                dao = RiskStatusDAO()
                db_status = dao.query_by_date(date)
                if db_status is not None:
                    logger.info(f"从数据库获取风控状态: {date}")
                    # 转换为RiskStatus对象
                    from utils.risk_manager import RiskLevel
                    risk_status = RiskStatus(
                        date=db_status['date'],
                        var_1d=db_status['var_1d'],
                        var_5d=db_status['var_5d'],
                        es_1d=db_status.get('es_1d'),
                        risk_level=RiskLevel(db_status['risk_level']),
                        position_limit=db_status['position_limit'],
                        stop_loss_multiplier=db_status['stop_loss_multiplier'],
                        score_extra=db_status['score_extra'],
                        strategy_enabled=bool(db_status['strategy_enabled']),
                        liquidate=bool(db_status.get('liquidate', 0))
                    )
                    # 缓存到内存
                    self._cache_risk_status(risk_status)
                    return risk_status
            except Exception as e:
                logger.warning(f"从数据库获取风控状态失败: {e}")
            
            # 2. 再检查内存缓存
            cached_status = self._get_cached_risk_status(date)
            if cached_status is not None:
                logger.info(f"从内存缓存获取风控状态: {date}")
                return cached_status
        
        # 需要重新计算
        try:
            # 获取指数收益率
            # 使用查询日期作为结束日期，确保计算的是该日期当时的VaR
            logger.info(f"计算风控状态: {date}")
            returns = self.index_fetcher.fetch_index_returns(
                end_date=date.replace('-', ''),  # 转换为YYYYMMDD格式
                lookback_days=self.lookback_days,
                use_cache=not force_refresh  # 强制刷新时不使用缓存
            )
            
            if returns is None or len(returns) < 100:
                logger.warning(f"数据不足，使用默认风控状态: {date}")
                return self.risk_manager.get_default_risk_status(date)
            
            # 计算VaR
            var_1d = self.var_calculator.calculate_var(returns, self.confidence_level)
            
            if var_1d is None:
                logger.warning(f"计算VaR失败，使用默认风控状态: {date}")
                return self.risk_manager.get_default_risk_status(date)
            
            # 计算5日VaR
            var_5d = self.var_calculator.calculate_multi_day_var(var_1d, 5)
            
            # 计算ES
            _, es_1d = self.var_calculator.calculate_var_and_es(returns, self.confidence_level)
            
            # 创建风控状态
            risk_status = self.risk_manager.create_risk_status(
                date=date,
                var_1d=var_1d,
                var_5d=var_5d,
                es_1d=es_1d
            )
            
            # 保存到数据库
            try:
                from trading.risk_status_dao import RiskStatusDAO
                dao = RiskStatusDAO()
                dao.save(risk_status)
            except Exception as e:
                logger.warning(f"保存风控状态到数据库失败: {e}")
            
            # 缓存风控状态
            self._cache_risk_status(risk_status)
            
            # 添加到历史记录
            self._add_to_history(risk_status)
            
            logger.info(f"风控状态计算完成: {date}, 风险等级={risk_status.risk_level.value}")
            return risk_status
            
        except Exception as e:
            logger.error(f"获取风控状态失败: {str(e)}")
            return self.risk_manager.get_default_risk_status(date)
    
    def get_risk_history(self, days: int = 30) -> list:
        """
        获取历史风控状态
        
        参数：
            days: 获取最近多少天的历史记录
            
        返回：
            风控状态列表
        """
        # 返回最近N天的记录
        return self.risk_history[-days:] if self.risk_history else []
    
    def get_risk_config(self) -> dict:
        """
        获取风控配置
        
        返回：
            配置字典
        """
        return self.config_loader.get_config()
    
    def update_risk_config(self, new_config: dict) -> bool:
        """
        更新风控配置
        
        参数：
            new_config: 新配置字典
            
        返回：
            是否更新成功
        """
        try:
            # 验证配置
            self.config_loader._config = new_config
            is_valid, msg = self.config_loader.validate_config()
            
            if not is_valid:
                logger.error(f"配置验证失败: {msg}")
                return False
            
            # 保存配置
            import yaml
            config_path = Path(self.config_loader.config_path)
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(new_config, f, allow_unicode=True, default_flow_style=False)
            
            # 重新加载配置
            self.config_loader.reload_config()
            risk_config = self.config_loader.get_risk_config()
            self.risk_manager = RiskManager(risk_config)
            
            logger.info("风控配置更新成功")
            return True
            
        except Exception as e:
            logger.error(f"更新风控配置失败: {str(e)}")
            return False
    
    def _get_cached_risk_status(self, date: str) -> Optional[RiskStatus]:
        """
        从缓存获取风控状态
        
        参数：
            date: 日期
            
        返回：
            风控状态对象，未找到返回None
        """
        for status in reversed(self.risk_history):
            if status.date == date:
                return status
        return None
    
    def _cache_risk_status(self, risk_status: RiskStatus):
        """
        缓存风控状态
        
        参数：
            risk_status: 风控状态对象
        """
        # 保存到历史记录
        self._add_to_history(risk_status)
    
    def _add_to_history(self, risk_status: RiskStatus):
        """
        添加到历史记录
        
        参数：
            risk_status: 风控状态对象
        """
        # 检查是否已存在
        for i, status in enumerate(self.risk_history):
            if status.date == risk_status.date:
                # 更新现有记录
                self.risk_history[i] = risk_status
                return
        
        # 添加新记录
        self.risk_history.append(risk_status)
        
        # 限制历史记录数量（最多保存365天）
        if len(self.risk_history) > 365:
            self.risk_history = self.risk_history[-365:]
    
    def _load_risk_history(self):
        """从文件加载历史风控状态"""
        try:
            history_file = Path('data/risk_history.json')
            if history_file.exists():
                import json
                with open(history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 转换为RiskStatus对象
                from utils.risk_manager import RiskLevel
                for item in data:
                    risk_status = RiskStatus(
                        date=item['date'],
                        var_1d=item['var_1d'],
                        var_5d=item['var_5d'],
                        es_1d=item.get('es_1d'),
                        risk_level=RiskLevel(item['risk_level']),
                        position_limit=item['position_limit'],
                        stop_loss_multiplier=item['stop_loss_multiplier'],
                        score_extra=item['score_extra'],
                        strategy_enabled=item['strategy_enabled'],
                        liquidate=item.get('liquidate', False)
                    )
                    self.risk_history.append(risk_status)
                
                logger.info(f"加载历史风控状态: {len(self.risk_history)} 条记录")
        except Exception as e:
            logger.warning(f"加载历史风控状态失败: {str(e)}")
    
    def save_risk_history(self):
        """保存历史风控状态到文件"""
        try:
            history_file = Path('data/risk_history.json')
            history_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 转换为字典列表
            data = [status.to_dict() for status in self.risk_history]
            
            import json
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"保存历史风控状态: {len(self.risk_history)} 条记录")
        except Exception as e:
            logger.error(f"保存历史风控状态失败: {str(e)}")


# 全局风控控制器实例
_risk_controller = None


def get_risk_controller() -> RiskController:
    """
    获取全局风控控制器实例（单例模式）
    
    返回：
        RiskController: 风控控制器实例
    """
    global _risk_controller
    if _risk_controller is None:
        _risk_controller = RiskController()
    return _risk_controller


# 测试代码
if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 创建风控控制器
    controller = RiskController()
    
    # 获取当日风控状态
    today = datetime.now().strftime('%Y-%m-%d')
    risk_status = controller.get_risk_status(today)
    
    if risk_status:
        print(f"\n今日风控状态 ({today}):")
        print(f"  风险等级: {risk_status.risk_level.value}")
        print(f"  VaR(1d): {risk_status.var_1d:.4f} ({risk_status.var_1d*100:.2f}%)")
        print(f"  VaR(5d): {risk_status.var_5d:.4f} ({risk_status.var_5d*100:.2f}%)")
        print(f"  ES(1d): {risk_status.es_1d:.4f} ({risk_status.es_1d*100:.2f}%)")
        print(f"  仓位上限: {risk_status.position_limit:.0%}")
        print(f"  止损倍数: {risk_status.stop_loss_multiplier:.1f}")
        print(f"  额外分数: {risk_status.score_extra}")
        print(f"  策略启用: {risk_status.strategy_enabled}")
    
    # 获取历史风控状态
    history = controller.get_risk_history(days=7)
    print(f"\n最近7天风控历史:")
    for status in history:
        print(f"  {status.date}: {status.risk_level.value}, VaR={status.var_1d:.4f}")
    
    # 保存历史记录
    controller.save_risk_history()
    print("\n历史风控状态已保存")