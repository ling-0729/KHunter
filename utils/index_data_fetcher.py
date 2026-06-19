"""
指数数据获取模块 - 获取指数历史数据并计算收益率
"""
import tushare as ts
import pandas as pd
import numpy as np
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timedelta
from io import StringIO
from utils.cache_manager import CacheManager
from utils.risk_config_loader import RiskConfigLoader

# 配置日志
logger = logging.getLogger(__name__)

# 指数代码与名称映射
INDEX_NAME_MAP = {
    '932000': '中证2000',
    '000852': '中证1000',
    '000905': '中证500',
    '000001': '上证指数',
    '000300': '沪深300',
}


class IndexDataFetcher:
    """指数数据获取器 - 获取指数历史数据"""
    
    def __init__(self, cache_dir: str = 'data/risk_cache'):
        """
        初始化指数数据获取器
        
        参数：
            cache_dir: 缓存目录路径
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_manager = CacheManager(str(self.cache_dir))
        
        # 从配置文件读取指数代码
        try:
            config_loader = RiskConfigLoader()
            config = config_loader.load_config()
            # 支持两种格式：932000.CSI（完整ts_code）或 932000（纯数字，默认添加.SH）
            index_code_raw = config.get('risk', {}).get('index_code', '932000.CSI')
            if '.' in index_code_raw:
                # 完整格式如 932000.CSI，分别提取代码和后缀
                parts = index_code_raw.split('.')
                self.index_code = parts[0]
                self.index_suffix = parts[1]
            else:
                # 纯数字格式如 000852，默认上海市场
                self.index_code = index_code_raw
                self.index_suffix = 'SH'
            self.ts_code = f'{self.index_code}.{self.index_suffix}'
            self.index_name = INDEX_NAME_MAP.get(self.index_code, f'指数({self.index_code})')
        except Exception as e:
            logger.warning(f"加载指数配置失败，使用默认值: {e}")
            self.index_code = '932000'
            self.index_suffix = 'CSI'
            self.ts_code = '932000.CSI'
            self.index_name = '中证2000'
        
        logger.info(f"IndexDataFetcher 初始化完成，指数: {self.index_name}({self.index_code})")
    
    def fetch_index_data(self, start_date: str = None, end_date: str = None, 
                         use_cache: bool = True) -> Optional[pd.DataFrame]:
        """
        获取指数历史数据（指数代码由配置决定，默认中证2000）
        
        参数：
            start_date: 开始日期，格式YYYYMMDD
            end_date: 结束日期，格式YYYYMMDD
            use_cache: 是否使用缓存
            
        返回：
            DataFrame，包含日期、开盘、收盘、最高、最低、成交量等
        """
        # 计算默认日期范围
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        if start_date is None:
            # 默认获取最近3年数据
            start_date = (datetime.now() - timedelta(days=365*3)).strftime('%Y%m%d')
        
        # 检查缓存
        cache_key = f"index_{self.index_code}_{start_date}_{end_date}"
        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data is not None:
                logger.info(f"从缓存加载指数数据: {cache_key}")
                return pd.read_json(StringIO(cached_data))
        
        try:
            # 使用tushare获取指数数据
            logger.info(f"获取{self.index_name}指数数据: {start_date} ~ {end_date}")
            
            # 初始化tushare
            pro = ts.pro_api()
            
            # tushare指数数据接口（使用完整ts_code，如 932000.CSI / 000852.SH）
            df = pro.index_daily(ts_code=self.ts_code, 
                                start_date=start_date, 
                                end_date=end_date)
            
            if df is None or df.empty:
                logger.error(f"获取{self.index_name}指数数据失败: 数据为空")
                return None
            
            # 重命名列
            df = df.rename(columns={
                'trade_date': 'date',
                'open': 'open',
                'close': 'close',
                'high': 'high',
                'low': 'low',
                'vol': 'volume',
                'amount': 'amount',
                'pct_chg': 'change_pct'
            })
            
            # 确保日期格式正确
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            
            # 缓存数据
            if use_cache:
                self.cache_manager.set(cache_key, df.to_json())
                logger.info(f"指数数据已缓存: {cache_key}")
            
            logger.info(f"成功获取{self.index_name}指数数据，共 {len(df)} 条记录")
            return df
            
        except Exception as e:
            logger.error(f"获取{self.index_name}指数数据失败: {str(e)}")
            return None
    
    def calculate_returns(self, df: pd.DataFrame, method: str = 'log') -> np.ndarray:
        """
        计算指数收益率
        
        参数：
            df: 指数数据DataFrame
            method: 收益率计算方法，'log'为对数收益率，'simple'为简单收益率
            
        返回：
            收益率数组（numpy数组）
        """
        if df is None or df.empty or 'close' not in df.columns:
            logger.error("计算收益率失败: 数据为空或缺少收盘价列")
            return np.array([])
        
        try:
            if method == 'log':
                # 对数收益率: ln(Pt/Pt-1)
                returns = np.log(df['close'] / df['close'].shift(1))
            else:
                # 简单收益率: (Pt-Pt-1)/Pt-1
                returns = (df['close'] - df['close'].shift(1)) / df['close'].shift(1)
            
            # 删除第一行（NaN）
            returns = returns.dropna().values
            
            logger.info(f"计算收益率完成，共 {len(returns)} 个数据点")
            return returns
            
        except Exception as e:
            logger.error(f"计算收益率失败: {str(e)}")
            return np.array([])
    
    def fetch_index_returns(self, end_date: str = None, lookback_days: int = 500,
                            use_cache: bool = True) -> Optional[np.ndarray]:
        """
        获取指数过去lookback_days个交易日的对数收益率（指数代码由配置决定）
        
        参数：
            end_date: 结束日期，格式YYYYMMDD
            lookback_days: 回溯天数（交易日）
            use_cache: 是否使用缓存
            
        返回：
            对数收益率数组（numpy数组），失败返回None
        """
        # 计算开始日期
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        # 获取足够多的历史数据（考虑节假日，多取一些）
        start_date = (datetime.strptime(end_date, '%Y%m%d') - 
                     timedelta(days=lookback_days * 2)).strftime('%Y%m%d')
        
        # 获取指数数据
        df = self.fetch_index_data(start_date, end_date, use_cache)
        
        if df is None or df.empty:
            logger.error("获取指数数据失败")
            return None
        
        # 计算收益率
        returns = self.calculate_returns(df, method='log')
        
        if len(returns) == 0:
            logger.error("计算收益率失败")
            return None
        
        # 截取最后lookback_days个数据点
        if len(returns) > lookback_days:
            returns = returns[-lookback_days:]
        
        logger.info(f"获取指数收益率完成，共 {len(returns)} 个数据点（请求 {lookback_days} 个）")
        return returns
    
    def get_latest_index_info(self) -> Optional[dict]:
        """
        获取最新的指数信息
        
        返回：
            包含最新指数信息的字典
        """
        try:
            # 获取最近30天的数据
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d')
            df = self.fetch_index_data(start_date=start_date, end_date=end_date)
            
            if df is None or df.empty:
                return None
            
            # 获取最新一条记录
            latest = df.iloc[-1]
            
            return {
                'date': latest['date'].strftime('%Y-%m-%d'),
                'open': float(latest['open']),
                'close': float(latest['close']),
                'high': float(latest['high']),
                'low': float(latest['low']),
                'volume': float(latest['volume']),
                'change_pct': float(latest['change_pct']) if 'change_pct' in latest else None
            }
            
        except Exception as e:
            logger.error(f"获取最新指数信息失败: {str(e)}")
            return None
    
    def clear_cache(self):
        """清空缓存"""
        try:
            self.cache_manager.clear_all()
            logger.info("指数数据缓存已清空")
        except Exception as e:
            logger.error(f"清空缓存失败: {str(e)}")


# 测试代码
if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 测试数据获取
    fetcher = IndexDataFetcher()
    
    # 获取最近500个交易日的收益率
    returns = fetcher.fetch_index_returns(lookback_days=500)
    
    if returns is not None:
        print(f"成功获取 {len(returns)} 个收益率数据点")
        print(f"收益率统计:")
        print(f"  均值: {np.mean(returns):.4f}")
        print(f"  标准差: {np.std(returns):.4f}")
        print(f"  最小值: {np.min(returns):.4f}")
        print(f"  最大值: {np.max(returns):.4f}")
        print(f"  1%分位数: {np.percentile(returns, 1):.4f}")
        print(f"  99%分位数: {np.percentile(returns, 99):.4f}")
    
    # 获取最新指数信息
    latest_info = fetcher.get_latest_index_info()
    if latest_info:
        print(f"\n最新指数信息:")
        print(f"  日期: {latest_info['date']}")
        print(f"  收盘价: {latest_info['close']}")
        print(f"  涨跌幅: {latest_info['change_pct']:.2f}%")