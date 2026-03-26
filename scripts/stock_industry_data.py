import akshare as ak
import pandas as pd
import sqlite3
import time
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 数据库文件路径
DB_PATH = 'stock_selection.db'

# 重试装饰器
def retry(max_attempts=3, delay=2):
    def decorator(func):
        def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    logging.warning(f"Attempt {attempts} failed: {e}")
                    if attempts < max_attempts:
                        logging.info(f"Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        logging.error(f"All attempts failed for {func.__name__}")
                        raise
        return wrapper
    return decorator

# 连接数据库
def get_db_connection():
    return sqlite3.connect(DB_PATH)

# 创建数据库表
def create_tables():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # SQLite兼容的创建表语句（移除COMMENT关键字）
        create_table_sql = """
        -- 创建股票基础信息表
        CREATE TABLE IF NOT EXISTS stock_basic (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            industry TEXT,
            area TEXT,
            market TEXT,
            list_date DATE,
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- 创建概念板块表
        CREATE TABLE IF NOT EXISTS concept_board (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- 创建股票-概念关联表
        CREATE TABLE IF NOT EXISTS stock_concept_relation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            concept_code TEXT NOT NULL,
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, concept_code)
        );
        
        -- 创建行业表
        CREATE TABLE IF NOT EXISTS industry_board (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- 创建股票-行业关联表
        CREATE TABLE IF NOT EXISTS stock_industry_relation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            industry_code TEXT NOT NULL,
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, industry_code)
        );
        """
        
        # 执行创建表语句
        for command in create_table_sql.split(';'):
            if command.strip():
                cursor.execute(command)
        
        conn.commit()
        logging.info("Tables created successfully")
    except Exception as e:
        logging.error(f"Error creating tables: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

# 获取股票基本信息
@retry()
def get_stock_basic():
    logging.info("Getting stock basic information...")
    try:
        # 尝试不同的函数获取股票基本信息
        try:
            stock_info = ak.stock_zh_a_spot_em()
        except Exception:
            stock_info = ak.stock_zh_a_spot()
        
        logging.info(f"Got {len(stock_info)} stocks")
        return stock_info
    except Exception as e:
        logging.error(f"Error getting stock basic info: {e}")
        return pd.DataFrame()

# 获取行业分类
@retry()
def get_industry_classification():
    logging.info("Getting industry classification...")
    try:
        industry_class = ak.stock_board_industry_name_ths()
        logging.info(f"Got {len(industry_class)} industries")
        return industry_class
    except Exception as e:
        logging.error(f"Error getting industry classification: {e}")
        return pd.DataFrame()

# 获取概念板块
@retry()
def get_concept_classification():
    logging.info("Getting concept classification...")
    try:
        concept_class = ak.stock_board_concept_name_em()
        logging.info(f"Got {len(concept_class)} concepts")
        return concept_class
    except Exception as e:
        logging.error(f"Error getting concept classification: {e}")
        return pd.DataFrame()

# 获取概念板块成分股
@retry()
def get_concept_stocks(concept_name):
    logging.info(f"Getting stocks for concept: {concept_name}")
    try:
        concept_stocks = ak.stock_board_concept_cons_em(symbol=concept_name)
        logging.info(f"Got {len(concept_stocks)} stocks for {concept_name}")
        return concept_stocks
    except Exception as e:
        logging.error(f"Error getting concept stocks: {e}")
        return pd.DataFrame()

# 存储股票基本信息
def save_stock_basic(stock_info):
    if stock_info.empty:
        logging.warning("No stock basic info to save")
        return
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for _, row in stock_info.iterrows():
            code = row.get('代码', '')
            name = row.get('名称', '')
            industry = row.get('行业', None)
            area = row.get('地区', None)
            
            if code and name:
                # 插入或更新股票基本信息（SQLite语法）
                sql = """
                INSERT OR REPLACE INTO stock_basic (code, name, industry, area, update_time) 
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """
                cursor.execute(sql, (code, name, industry, area))
        
        conn.commit()
        logging.info(f"Saved {len(stock_info)} stocks to database")
    except Exception as e:
        logging.error(f"Error saving stock basic info: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

# 存储行业分类
def save_industry_classification(industry_class):
    if industry_class.empty:
        logging.warning("No industry classification to save")
        return
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for _, row in industry_class.iterrows():
            name = row.get('name', '')
            code = row.get('code', '')
            
            if name and code:
                # 插入或更新行业分类（SQLite语法）
                sql = """
                INSERT OR REPLACE INTO industry_board (name, code, update_time) 
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """
                cursor.execute(sql, (name, code))
        
        conn.commit()
        logging.info(f"Saved {len(industry_class)} industries to database")
    except Exception as e:
        logging.error(f"Error saving industry classification: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

# 存储概念板块
def save_concept_classification(concept_class):
    if concept_class.empty:
        logging.warning("No concept classification to save")
        return
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for _, row in concept_class.iterrows():
            name = row.get('name', '')
            code = row.get('code', '')
            
            if name and code:
                # 插入或更新概念板块（SQLite语法）
                sql = """
                INSERT OR REPLACE INTO concept_board (name, code, update_time) 
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """
                cursor.execute(sql, (name, code))
        
        conn.commit()
        logging.info(f"Saved {len(concept_class)} concepts to database")
    except Exception as e:
        logging.error(f"Error saving concept classification: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

# 存储股票-概念关联
def save_stock_concept_relations():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取概念板块列表
        cursor.execute("SELECT name, code FROM concept_board")
        concepts = cursor.fetchall()
        
        for concept_name, concept_code in concepts[:10]:  # 限制处理前10个概念，避免请求过多
            concept_stocks = get_concept_stocks(concept_name)
            if not concept_stocks.empty:
                for _, row in concept_stocks.iterrows():
                    stock_code = row.get('代码', '')
                    if stock_code:
                        # 插入或更新股票-概念关联（SQLite语法）
                        sql = """
                        INSERT OR REPLACE INTO stock_concept_relation (stock_code, concept_code, update_time) 
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        """
                        cursor.execute(sql, (stock_code, concept_code))
                conn.commit()
                logging.info(f"Saved relations for concept: {concept_name}")
                time.sleep(1)  # 避免请求过快
    except Exception as e:
        logging.error(f"Error saving stock-concept relations: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

# 主函数
def main():
    # 创建数据库表
    create_tables()
    
    # 获取并存储股票基本信息
    stock_info = get_stock_basic()
    save_stock_basic(stock_info)
    
    # 获取并存储行业分类
    industry_class = get_industry_classification()
    save_industry_classification(industry_class)
    
    # 获取并存储概念板块
    concept_class = get_concept_classification()
    save_concept_classification(concept_class)
    
    # 存储股票-概念关联
    save_stock_concept_relations()
    
    logging.info("Stock industry data processing completed")

if __name__ == "__main__":
    main()
