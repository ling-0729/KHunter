"""监控告警系统"""

import time
import threading
import logging
from typing import Dict, List, Optional
from utils.data_fetcher import DataFetcher
from utils.cache_manager import cache_manager

class Monitor:
    """监控告警系统"""
    
    def __init__(self, check_interval: int = 300):
        """
        初始化监控告警系统
        
        参数：
            check_interval: 检查间隔（秒）
        """
        self.check_interval = check_interval
        self.data_fetcher = DataFetcher()
        self.logger = logging.getLogger("monitor")
        self.running = False
        self.thread = None
        self.alert_history = []
        self.logger.info("监控告警系统初始化完成")
    
    def start(self):
        """启动监控"""
        if self.running:
            self.logger.warning("监控已经在运行")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop)
        self.thread.daemon = True
        self.thread.start()
        self.logger.info("监控告警系统启动成功")
    
    def stop(self):
        """停止监控"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.logger.info("监控告警系统已停止")
    
    def _monitor_loop(self):
        """监控循环"""
        while self.running:
            try:
                self._check_data_sources()
                self._check_cache_health()
            except Exception as e:
                self.logger.error(f"监控过程中发生错误: {e}")
            
            # 等待下一次检查
            for _ in range(self.check_interval):
                if not self.running:
                    break
                time.sleep(1)
    
    def _check_data_sources(self):
        """检查数据源健康状态"""
        self.logger.info("开始检查数据源健康状态")
        
        available_sources = self.data_fetcher.get_available_sources()
        
        for source_info in available_sources:
            source_name = source_info['name']
            available = source_info['available']
            
            if not available:
                self._alert(f"数据源 {source_name} 不可用", "error")
                self.logger.error(f"数据源 {source_name} 不可用")
            else:
                self.logger.info(f"数据源 {source_name} 状态正常")
    
    def _check_cache_health(self):
        """检查缓存健康状态"""
        self.logger.info("开始检查缓存健康状态")
        
        try:
            cache_size = cache_manager.get_cache_size()
            cache_info = cache_manager.get_cache_info()
            
            # 检查缓存大小
            if cache_size > 1000:
                self._alert(f"缓存文件数量过多: {cache_size}", "warning")
                self.logger.warning(f"缓存文件数量过多: {cache_size}")
            
            # 检查过期缓存
            expired_count = sum(1 for info in cache_info if info['is_expired'])
            if expired_count > 500:
                self._alert(f"过期缓存文件过多: {expired_count}", "warning")
                self.logger.warning(f"过期缓存文件过多: {expired_count}")
            
            self.logger.info(f"缓存健康状态: {cache_size} 个文件, {expired_count} 个过期")
        except Exception as e:
            self.logger.error(f"检查缓存健康状态失败: {e}")
    
    def _alert(self, message: str, level: str = "info"):
        """
        发送告警
        
        参数：
            message: 告警信息
            level: 告警级别 (info, warning, error)
        """
        # 检查是否重复告警
        alert_key = f"{level}:{message}"
        if any(alert['key'] == alert_key for alert in self.alert_history):
            self.logger.debug(f"重复告警，跳过: {message}")
            return
        
        # 记录告警历史
        self.alert_history.append({
            'key': alert_key,
            'message': message,
            'level': level,
            'timestamp': time.time()
        })
        
        # 限制告警历史长度
        if len(self.alert_history) > 100:
            self.alert_history = self.alert_history[-100:]
        
        # 这里可以添加其他告警方式，如邮件、短信等
        self.logger.info(f"[ALERT] [{level.upper()}] {message}")
    
    def get_alert_history(self, limit: int = 50) -> List[Dict]:
        """
        获取告警历史
        
        参数：
            limit: 限制返回数量
        
        返回：
            告警历史列表
        """
        return self.alert_history[-limit:]
    
    def check_data_quality(self, stock_code: str) -> Dict:
        """
        检查数据质量
        
        参数：
            stock_code: 股票代码
        
        返回：
            数据质量检查结果
        """
        self.logger.info(f"检查股票 {stock_code} 的数据质量")
        
        result = {
            'stock_code': stock_code,
            'check_time': time.time(),
            'data_sources': {},
            'issues': []
        }
        
        # 检查各数据源的数据
        try:
            # 检查基本信息
            stock_basic = self.data_fetcher.fetch_stock_basic()
            if stock_basic:
                stock_info = next((s for s in stock_basic if s['code'] == stock_code), None)
                if stock_info:
                    result['data_sources']['basic'] = 'ok'
                else:
                    result['data_sources']['basic'] = 'missing'
                    result['issues'].append('基本信息缺失')
            else:
                result['data_sources']['basic'] = 'error'
                result['issues'].append('基本信息获取失败')
            
            # 检查资金流向
            fund_flow = self.data_fetcher.fetch_fund_flow(stock_code)
            if fund_flow:
                result['data_sources']['fund_flow'] = 'ok'
            else:
                result['data_sources']['fund_flow'] = 'error'
                result['issues'].append('资金流向获取失败')
            
            # 检查历史行情
            history = self.data_fetcher.fetch_stock_history(stock_code, years=1)
            if history is not None and len(history) > 0:
                result['data_sources']['history'] = 'ok'
            else:
                result['data_sources']['history'] = 'error'
                result['issues'].append('历史行情获取失败')
            
        except Exception as e:
            self.logger.error(f"检查数据质量失败: {e}")
            result['issues'].append(f"检查过程中发生错误: {str(e)}")
        
        return result
    
    def get_system_status(self) -> Dict:
        """
        获取系统状态
        
        返回：
            系统状态信息
        """
        status = {
            'timestamp': time.time(),
            'data_sources': self.data_fetcher.get_available_sources(),
            'cache': {
                'size': cache_manager.get_cache_size(),
                'info': cache_manager.get_cache_info()[:10]  # 只返回前10个
            },
            'alert_history': self.get_alert_history(10),
            'monitor_running': self.running
        }
        return status

# 全局监控实例
monitor = Monitor()
