"""
CSV 数据管理工具
"""
import os
import pandas as pd
from pathlib import Path


class CSVManager:
    """CSV文件管理器"""
    
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def get_stock_path(self, stock_code):
        """获取股票CSV文件路径"""
        # 按股票代码前两位分目录，避免单目录文件过多
        prefix = stock_code[:2] if len(stock_code) >= 2 else stock_code
        subdir = self.data_dir / prefix
        subdir.mkdir(exist_ok=True)
        return subdir / f"{stock_code}.csv"
    
    def read_stock(self, stock_code):
        """读取股票数据"""
        path = self.get_stock_path(stock_code)
        if not path.exists():
            return pd.DataFrame()
        
        # 检查文件是否为空
        if path.stat().st_size == 0:
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(path, parse_dates=['date'])
            return df
        except Exception as e:
            print(f"  读取 {stock_code} 数据失败: {e}")
            return pd.DataFrame()
    
    def write_stock(self, stock_code, df):
        """写入股票数据（自动去重排序）"""
        path = self.get_stock_path(stock_code)
        
        # 去重：按日期去重，保留最后出现的
        df = df.drop_duplicates(subset=['date'], keep='last')
        
        # 按日期倒序排列（最新在前）
        df = df.sort_values('date', ascending=False)
        
        # 确保目录存在
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入CSV
        df.to_csv(path, index=False)
        return path
    
    def update_stock(self, stock_code, new_df):
        """增量更新股票数据"""
        existing_df = self.read_stock(stock_code)
        
        if existing_df.empty:
            return self.write_stock(stock_code, new_df)
        
        # 合并数据
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        return self.write_stock(stock_code, combined)
    
    def list_all_stocks(self):
        """列出所有已保存的股票代码"""
        stocks = []
        for csv_file in self.data_dir.rglob("*.csv"):
            stock_code = csv_file.stem
            stocks.append(stock_code)
        return sorted(stocks)
    
    def get_stock_count(self):
        """获取已保存的股票数量"""
        return len(self.list_all_stocks())
    
    def stock_exists(self, stock_code):
        """检查股票数据是否存在"""
        return self.get_stock_path(stock_code).exists()
