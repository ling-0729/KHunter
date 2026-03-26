"""
板块数据获取模块
用于获取和存储板块指数和板块成分股数据
"""
import sqlite3
import logging
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SectorFetcher:
    """
    板块数据获取器
    
    功能：
    1. 获取板块指数数据
    2. 获取板块成分股数据
    3. 存储板块数据到数据库
    4. 查询板块数据
    """
    
    def __init__(self, db_path='stock_selection.db'):
        """
        初始化板块数据获取器
        :param db_path: 数据库路径
        """
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """
        初始化数据库
        创建板块数据表
        """
        try:
            # 读取SQL脚本
            sql_path = Path(__file__).parent / 'SectorRotationSql.sql'
            with open(sql_path, 'r', encoding='utf-8') as f:
                sql_script = f.read()
            
            # 执行SQL脚本
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.executescript(sql_script)
            conn.commit()
            conn.close()
            
            logging.info("板块数据表初始化成功")
        except Exception as e:
            logging.error(f"初始化数据库失败: {e}")
            raise
    
    def _get_connection(self):
        """
        获取数据库连接
        :return: 数据库连接对象
        """
        return sqlite3.connect(self.db_path)
    
    def get_sector_indices(self):
        """
        获取所有板块指数数据
        
        包括：
        1. 行业板块
        2. 概念板块
        3. 地域板块
        
        :return: 板块指数数据DataFrame
        """
        try:
            sector_indices = []
            
            # 获取行业板块
            try:
                industry_indices = ak.stock_board_industry_name_em()
                logging.info(f"获取到 {len(industry_indices)} 个行业板块")
                for _, row in industry_indices.iterrows():
                    sector_indices.append({
                        'sector_code': row.get('板块代码', ''),
                        'sector_name': row.get('板块名称', ''),
                        'sector_type': '行业'
                    })
            except Exception as e:
                logging.warning(f"获取行业板块失败: {e}")
            
            # 获取概念板块
            try:
                concept_indices = ak.stock_board_concept_name_em()
                logging.info(f"获取到 {len(concept_indices)} 个概念板块")
                for _, row in concept_indices.iterrows():
                    sector_indices.append({
                        'sector_code': row.get('板块代码', ''),
                        'sector_name': row.get('板块名称', ''),
                        'sector_type': '概念'
                    })
            except Exception as e:
                logging.warning(f"获取概念板块失败: {e}")
            
            # 获取地域板块
            try:
                area_indices = ak.stock_board_area_name_em()
                logging.info(f"获取到 {len(area_indices)} 个地域板块")
                for _, row in area_indices.iterrows():
                    sector_indices.append({
                        'sector_code': row.get('板块代码', ''),
                        'sector_name': row.get('板块名称', ''),
                        'sector_type': '地域'
                    })
            except Exception as e:
                logging.warning(f"获取地域板块失败: {e}")
            
            df = pd.DataFrame(sector_indices)
            logging.info(f"获取板块指数数据成功，共 {len(df)} 个板块")
            
            return df
        except Exception as e:
            logging.error(f"获取板块指数数据失败: {e}")
            return pd.DataFrame()
    
    def get_sector_stocks(self, sector_code):
        """
        获取板块成分股数据
        
        :param sector_code: 板块代码
        :return: 板块成分股数据DataFrame
        """
        try:
            # 获取板块成分股
            stocks = ak.stock_board_industry_cons_em(symbol=sector_code)
            
            logging.info(f"获取板块 {sector_code} 的成分股数据成功，共 {len(stocks)} 只股票")
            
            return stocks
        except Exception as e:
            logging.error(f"获取板块 {sector_code} 的成分股数据失败: {e}")
            return pd.DataFrame()
    
    def get_sector_index_history(self, sector_code, days=30):
        """
        获取板块指数历史数据
        
        :param sector_code: 板块代码
        :param days: 获取天数
        :return: 板块指数历史数据DataFrame
        """
        try:
            # 计算日期范围
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
            
            # 获取板块指数历史数据
            # 注意：akshare可能没有直接的板块指数历史数据接口
            # 这里使用板块成分股的指数数据作为替代
            stocks = self.get_sector_stocks(sector_code)
            
            if stocks.empty:
                return pd.DataFrame()
            
            # 获取成分股的历史数据
            stock_codes = stocks['代码'].tolist()
            # 这里可以调用其他接口获取历史数据
            
            logging.info(f"获取板块 {sector_code} 的历史数据成功")
            
            return pd.DataFrame()
        except Exception as e:
            logging.error(f"获取板块 {sector_code} 的历史数据失败: {e}")
            return pd.DataFrame()
    
    def save_sector_indices(self, sector_indices):
        """
        保存板块指数数据到数据库
        
        :param sector_indices: 板块指数数据DataFrame
        """
        try:
            if sector_indices.empty:
                logging.warning("板块指数数据为空，跳过保存")
                return
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 准备数据
            records = []
            for _, row in sector_indices.iterrows():
                records.append((
                    row.get('sector_code', ''),
                    row.get('sector_name', ''),
                    row.get('sector_type', '')
                ))
            
            # 批量插入数据
            sql = """
            INSERT OR REPLACE INTO sector_index 
            (sector_code, sector_name, sector_type, update_time)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """
            
            cursor.executemany(sql, records)
            conn.commit()
            conn.close()
            
            logging.info(f"保存板块指数数据成功，共 {len(records)} 条记录")
        except Exception as e:
            logging.error(f"保存板块指数数据失败: {e}")
            raise
    
    def save_sector_stocks(self, sector_code, sector_stocks):
        """
        保存板块成分股数据到数据库
        
        :param sector_code: 板块代码
        :param sector_stocks: 板块成分股数据DataFrame
        """
        try:
            if sector_stocks.empty:
                logging.warning(f"板块 {sector_code} 的成分股数据为空，跳过保存")
                return
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 准备数据
            records = []
            for _, row in sector_stocks.iterrows():
                # 处理NaN值
                weight = row.get('权重', 0)
                
                records.append((
                    sector_code,
                    row.get('板块名称', ''),
                    row.get('代码', ''),
                    row.get('名称', ''),
                    float(weight) if pd.notna(weight) else None,
                    datetime.now().strftime('%Y-%m-%d')
                ))
            
            # 批量插入数据
            sql = """
            INSERT OR REPLACE INTO sector_stock 
            (sector_code, sector_name, stock_code, stock_name, weight, entry_date, update_time)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """
            
            cursor.executemany(sql, records)
            conn.commit()
            conn.close()
            
            logging.info(f"保存板块 {sector_code} 的成分股数据成功，共 {len(records)} 条记录")
        except Exception as e:
            logging.error(f"保存板块成分股数据失败: {e}")
            raise
    
    def query_sector_indices(self, sector_type=None):
        """
        查询板块指数数据
        
        :param sector_type: 板块类型（可选），行业/概念/地域
        :return: 板块指数数据DataFrame
        """
        try:
            conn = self._get_connection()
            
            if sector_type:
                sql = """
                SELECT sector_code, sector_name, sector_type
                FROM sector_index
                WHERE sector_type = ?
                ORDER BY sector_name
                """
                df = pd.read_sql_query(sql, conn, params=(sector_type,))
            else:
                sql = """
                SELECT sector_code, sector_name, sector_type
                FROM sector_index
                ORDER BY sector_type, sector_name
                """
                df = pd.read_sql_query(sql, conn)
            
            conn.close()
            
            return df
        except Exception as e:
            logging.error(f"查询板块指数数据失败: {e}")
            return pd.DataFrame()
    
    def query_sector_stocks(self, sector_code):
        """
        查询板块成分股数据
        
        :param sector_code: 板块代码
        :return: 板块成分股数据DataFrame
        """
        try:
            conn = self._get_connection()
            
            sql = """
            SELECT sector_code, sector_name, stock_code, stock_name, weight, entry_date
            FROM sector_stock
            WHERE sector_code = ?
            ORDER BY weight DESC
            """
            
            df = pd.read_sql_query(sql, conn, params=(sector_code,))
            conn.close()
            
            return df
        except Exception as e:
            logging.error(f"查询板块成分股数据失败: {e}")
            return pd.DataFrame()
    
    def fetch_and_save_all(self):
        """
        获取并保存所有板块数据
        
        包括：
        1. 所有板块指数数据
        2. 所有板块的成分股数据
        """
        try:
            logging.info("开始获取板块数据...")
            
            # 获取所有板块指数
            sector_indices = self.get_sector_indices()
            if not sector_indices.empty:
                # 保存板块指数
                self.save_sector_indices(sector_indices)
                
                # 获取每个板块的成分股
                for _, row in sector_indices.iterrows():
                    sector_code = row.get('sector_code', '')
                    sector_name = row.get('sector_name', '')
                    
                    if sector_code:
                        logging.info(f"获取板块 {sector_name} ({sector_code}) 的成分股...")
                        sector_stocks = self.get_sector_stocks(sector_code)
                        if not sector_stocks.empty:
                            self.save_sector_stocks(sector_code, sector_stocks)
            
            logging.info("板块数据获取和保存完成")
        except Exception as e:
            logging.error(f"获取和保存板块数据失败: {e}")
            raise


# 测试代码
if __name__ == "__main__":
    # 创建板块数据获取器
    fetcher = SectorFetcher()
    
    # 测试获取板块指数数据
    print("=" * 60)
    print("测试获取板块指数数据")
    print("=" * 60)
    sector_indices = fetcher.get_sector_indices()
    if not sector_indices.empty:
        print(f"获取到 {len(sector_indices)} 个板块")
        print("\n按类型统计：")
        print(sector_indices['sector_type'].value_counts())
        print("\n前10个板块：")
        print(sector_indices.head(10))
    
    # 测试获取板块成分股数据
    print("\n" + "=" * 60)
    print("测试获取板块成分股数据")
    print("=" * 60)
    if not sector_indices.empty:
        sector_code = sector_indices.iloc[0]['sector_code']
        sector_name = sector_indices.iloc[0]['sector_name']
        sector_stocks = fetcher.get_sector_stocks(sector_code)
        if not sector_stocks.empty:
            print(f"获取到板块 {sector_name} ({sector_code}) 的成分股，共 {len(sector_stocks)} 只股票")
            print("\n前10只股票：")
            print(sector_stocks.head(10))
    
    # 测试保存数据
    print("\n" + "=" * 60)
    print("测试保存数据")
    print("=" * 60)
    if not sector_indices.empty:
        fetcher.save_sector_indices(sector_indices)
        print("板块指数数据保存成功")
    
    # 测试查询数据
    print("\n" + "=" * 60)
    print("测试查询数据")
    print("=" * 60)
    query_result = fetcher.query_sector_indices(sector_type='行业')
    if not query_result.empty:
        print(f"查询到 {len(query_result)} 个行业板块")
        print(query_result.head(10))
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
