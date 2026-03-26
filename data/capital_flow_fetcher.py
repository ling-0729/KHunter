"""
资金流向数据获取模块
用于获取和存储股票的资金流向数据
"""
import sqlite3
import logging
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class CapitalFlowFetcher:
    """
    资金流向数据获取器
    
    功能：
    1. 获取个股资金流向数据
    2. 获取资金流向排行数据
    3. 存储资金流向数据到数据库
    4. 查询资金流向数据
    """
    
    def __init__(self, db_path='stock_selection.db'):
        """
        初始化资金流向数据获取器
        :param db_path: 数据库路径
        """
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """
        初始化数据库
        创建资金流向数据表
        """
        try:
            # 读取SQL脚本
            sql_path = Path(__file__).parent / 'CapitalFlowSql.sql'
            with open(sql_path, 'r', encoding='utf-8') as f:
                sql_script = f.read()
            
            # 执行SQL脚本
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.executescript(sql_script)
            conn.commit()
            conn.close()
            
            logging.info("资金流向数据表初始化成功")
        except Exception as e:
            logging.error(f"初始化数据库失败: {e}")
            raise
    
    def _get_connection(self):
        """
        获取数据库连接
        :return: 数据库连接对象
        """
        return sqlite3.connect(self.db_path)
    
    def get_individual_capital_flow(self, stock_code, date=None):
        """
        获取个股资金流向数据
        
        :param stock_code: 股票代码
        :param date: 日期（可选），如果不指定则获取最新数据
        :return: 资金流向数据DataFrame
        """
        try:
            # 获取个股资金流向数据
            if date:
                # 指定日期的数据
                start_date = date
                end_date = date
            else:
                # 获取最近的数据
                end_date = datetime.now().strftime('%Y%m%d')
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
            
            # 使用akshare获取资金流向数据
            capital_flow_data = ak.stock_individual_fund_flow(
                stock=stock_code,
                indicator="今日"
            )
            
            logging.info(f"获取股票 {stock_code} 的资金流向数据成功，共 {len(capital_flow_data)} 条记录")
            
            return capital_flow_data
        except Exception as e:
            logging.error(f"获取股票 {stock_code} 的资金流向数据失败: {e}")
            return pd.DataFrame()
    
    def get_capital_flow_rank(self, date=None):
        """
        获取资金流向排行数据
        
        :param date: 日期（可选），如果不指定则获取最新数据
        :return: 资金流向排行数据DataFrame
        """
        try:
            # 使用akshare获取资金流向排行数据
            capital_flow_rank = ak.stock_individual_fund_flow_rank(
                indicator="今日"
            )
            
            logging.info(f"获取资金流向排行数据成功，共 {len(capital_flow_rank)} 条记录")
            
            return capital_flow_rank
        except Exception as e:
            logging.error(f"获取资金流向排行数据失败: {e}")
            return pd.DataFrame()
    
    def save_capital_flow(self, capital_flow_data):
        """
        保存资金流向数据到数据库
        
        :param capital_flow_data: 资金流向数据DataFrame
        """
        try:
            if capital_flow_data.empty:
                logging.warning("资金流向数据为空，跳过保存")
                return
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 准备数据
            records = []
            for _, row in capital_flow_data.iterrows():
                # 处理NaN值
                main_inflow = row.get('主力净流入', 0)
                super_inflow = row.get('超大单净流入', 0)
                large_inflow = row.get('大单净流入', 0)
                medium_inflow = row.get('中单净流入', 0)
                small_inflow = row.get('小单净流入', 0)
                main_ratio = row.get('主力净流入占比', 0)
                net_inflow_ratio = row.get('净流入占比', 0)
                
                # 处理NaT和None值
                date = row.get('日期')
                if pd.isna(date):
                    continue
                
                records.append((
                    row.get('代码', ''),
                    date,
                    float(main_inflow) if pd.notna(main_inflow) else None,
                    float(super_inflow) if pd.notna(super_inflow) else None,
                    float(large_inflow) if pd.notna(large_inflow) else None,
                    float(medium_inflow) if pd.notna(medium_inflow) else None,
                    float(small_inflow) if pd.notna(small_inflow) else None,
                    float(main_ratio) if pd.notna(main_ratio) else None,
                    float(net_inflow_ratio) if pd.notna(net_inflow_ratio) else None
                ))
            
            # 批量插入数据
            sql = """
            INSERT OR REPLACE INTO stock_capital_flow 
            (stock_code, date, main_inflow, super_inflow, large_inflow, 
             medium_inflow, small_inflow, main_ratio, net_inflow_ratio, update_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """
            
            cursor.executemany(sql, records)
            conn.commit()
            conn.close()
            
            logging.info(f"保存资金流向数据成功，共 {len(records)} 条记录")
        except Exception as e:
            logging.error(f"保存资金流向数据失败: {e}")
            raise
    
    def save_capital_flow_rank(self, rank_data):
        """
        保存资金流向排行数据到数据库
        
        :param rank_data: 资金流向排行数据DataFrame
        """
        try:
            if rank_data.empty:
                logging.warning("资金流向排行数据为空，跳过保存")
                return
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 准备数据
            records = []
            for idx, row in rank_data.iterrows():
                # 处理NaN值
                main_inflow = row.get('主力净流入', 0)
                main_ratio = row.get('主力净流入占比', 0)
                net_inflow_ratio = row.get('净流入占比', 0)
                
                # 处理NaT和None值
                date = row.get('日期')
                if pd.isna(date):
                    continue
                
                records.append((
                    row.get('代码', ''),
                    row.get('名称', ''),
                    date,
                    float(main_inflow) if pd.notna(main_inflow) else None,
                    idx + 1,  # 排名从1开始
                    float(main_ratio) if pd.notna(main_ratio) else None,
                    float(net_inflow_ratio) if pd.notna(net_inflow_ratio) else None
                ))
            
            # 批量插入数据
            sql = """
            INSERT OR REPLACE INTO stock_capital_flow_rank 
            (stock_code, stock_name, date, main_inflow, main_inflow_rank, 
             main_ratio, net_inflow_ratio, update_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """
            
            cursor.executemany(sql, records)
            conn.commit()
            conn.close()
            
            logging.info(f"保存资金流向排行数据成功，共 {len(records)} 条记录")
        except Exception as e:
            logging.error(f"保存资金流向排行数据失败: {e}")
            raise
    
    def query_capital_flow(self, stock_code, days=10):
        """
        查询股票的资金流向数据
        
        :param stock_code: 股票代码
        :param days: 查询天数
        :return: 资金流向数据DataFrame
        """
        try:
            conn = self._get_connection()
            
            # 计算查询的起始日期
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            sql = """
            SELECT stock_code, date, main_inflow, super_inflow, large_inflow, 
                   medium_inflow, small_inflow, main_ratio, net_inflow_ratio
            FROM stock_capital_flow
            WHERE stock_code = ? AND date >= ?
            ORDER BY date DESC
            """
            
            df = pd.read_sql_query(sql, conn, params=(stock_code, start_date))
            conn.close()
            
            return df
        except Exception as e:
            logging.error(f"查询资金流向数据失败: {e}")
            return pd.DataFrame()
    
    def query_capital_flow_rank(self, date=None, top_n=50):
        """
        查询资金流向排行数据
        
        :param date: 日期（可选），如果不指定则查询最新数据
        :param top_n: 返回前N条记录
        :return: 资金流向排行数据DataFrame
        """
        try:
            conn = self._get_connection()
            
            if date:
                sql = """
                SELECT stock_code, stock_name, date, main_inflow, main_inflow_rank, 
                       main_ratio, net_inflow_ratio
                FROM stock_capital_flow_rank
                WHERE date = ?
                ORDER BY main_inflow_rank ASC
                LIMIT ?
                """
                df = pd.read_sql_query(sql, conn, params=(date, top_n))
            else:
                sql = """
                SELECT stock_code, stock_name, date, main_inflow, main_inflow_rank, 
                       main_ratio, net_inflow_ratio
                FROM stock_capital_flow_rank
                WHERE date = (SELECT MAX(date) FROM stock_capital_flow_rank)
                ORDER BY main_inflow_rank ASC
                LIMIT ?
                """
                df = pd.read_sql_query(sql, conn, params=(top_n,))
            
            conn.close()
            
            return df
        except Exception as e:
            logging.error(f"查询资金流向排行数据失败: {e}")
            return pd.DataFrame()
    
    def fetch_and_save_all(self):
        """
        获取并保存所有资金流向数据
        
        包括：
        1. 资金流向排行数据
        2. 排行前50名个股的资金流向数据
        """
        try:
            logging.info("开始获取资金流向数据...")
            
            # 获取资金流向排行数据
            rank_data = self.get_capital_flow_rank()
            if not rank_data.empty:
                self.save_capital_flow_rank(rank_data)
                
                # 获取前50名个股的资金流向数据
                top_stocks = rank_data.head(50)
                for _, row in top_stocks.iterrows():
                    stock_code = row.get('代码', '')
                    if stock_code:
                        capital_flow_data = self.get_individual_capital_flow(stock_code)
                        if not capital_flow_data.empty:
                            self.save_capital_flow(capital_flow_data)
            
            logging.info("资金流向数据获取和保存完成")
        except Exception as e:
            logging.error(f"获取和保存资金流向数据失败: {e}")
            raise


# 测试代码
if __name__ == "__main__":
    # 创建资金流向数据获取器
    fetcher = CapitalFlowFetcher()
    
    # 测试获取资金流向排行数据
    print("=" * 60)
    print("测试获取资金流向排行数据")
    print("=" * 60)
    rank_data = fetcher.get_capital_flow_rank()
    if not rank_data.empty:
        print(f"获取到 {len(rank_data)} 条资金流向排行数据")
        print("\n前10名：")
        print(rank_data.head(10))
    
    # 测试获取个股资金流向数据
    print("\n" + "=" * 60)
    print("测试获取个股资金流向数据")
    print("=" * 60)
    if not rank_data.empty:
        stock_code = rank_data.iloc[0]['代码']
        capital_flow_data = fetcher.get_individual_capital_flow(stock_code)
        if not capital_flow_data.empty:
            print(f"获取到股票 {stock_code} 的资金流向数据")
            print(capital_flow_data.head(10))
    
    # 测试保存数据
    print("\n" + "=" * 60)
    print("测试保存数据")
    print("=" * 60)
    if not rank_data.empty:
        fetcher.save_capital_flow_rank(rank_data)
        print("资金流向排行数据保存成功")
    
    # 测试查询数据
    print("\n" + "=" * 60)
    print("测试查询数据")
    print("=" * 60)
    query_result = fetcher.query_capital_flow_rank(top_n=10)
    if not query_result.empty:
        print(f"查询到 {len(query_result)} 条资金流向排行数据")
        print(query_result)
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
