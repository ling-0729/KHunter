#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
补充历史K线数据脚本

功能：补充2023年1月1日到2024年8月14日的K线数据
使用Tushare Pro接口获取前复权数据
"""

import sqlite3
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('补充历史K线数据.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 数据库路径
DB_PATH = 'data/stock_selection.db'

# 补充数据的时间范围
START_DATE = '20230101'  # 开始日期（Tushare格式：YYYYMMDD）
END_DATE = '20240814'    # 结束日期（Tushare格式：YYYYMMDD）

# Tushare API配置
try:
    import tushare as ts
    pro = ts.pro_api()
    TUSHARE_AVAILABLE = True
except Exception as e:
    logger.error(f"Tushare初始化失败: {str(e)}")
    TUSHARE_AVAILABLE = False

def get_stock_list():
    """从数据库获取股票列表"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT code FROM stock_basic")
        stock_list = [row[0] for row in cursor.fetchall()]
        conn.close()
        logger.info(f"从数据库获取到 {len(stock_list)} 只股票")
        return stock_list
    except Exception as e:
        logger.error(f"获取股票列表失败: {str(e)}")
        return []

def get_tushare_code(code):
    """
    将数据库中的股票代码转换为Tushare格式
    
    参数：
        code: 数据库中的股票代码（如 600001）
    
    返回：
        Tushare格式的股票代码（如 600001.SH）
    """
    if code.startswith('6'):
        return f"{code}.SH"  # 上海A股
    elif code.startswith('0') or code.startswith('3'):
        return f"{code}.SZ"  # 深圳A股/创业板
    else:
        return f"{code}.SH"  # 默认上海

def fetch_kline_data(ts_code, start_date, end_date):
    """
    使用Tushare获取前复权K线数据
    
    参数：
        ts_code: 股票代码（如 000001.SZ）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
    
    返回：
        K线数据DataFrame，如果失败返回None
    """
    try:
        # 使用pro_bar接口获取前复权数据
        df = pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            adjust='qfq'  # 前复权
        )
        
        if df is None or df.empty:
            logger.debug(f"{ts_code} 在 {start_date}-{end_date} 期间无数据")
            return None
        
        # 选择需要的列并重新命名
        df = df[['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol']]
        df.columns = ['code', 'date', 'open', 'high', 'low', 'close', 'volume']
        
        # 转换日期格式（YYYYMMDD -> YYYY-MM-DD）
        df['date'] = df['date'].apply(lambda x: f"{x[:4]}-{x[4:6]}-{x[6:8]}")
        
        # 确保数值类型正确
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        
        # 去除无效数据
        df = df.dropna()
        
        logger.debug(f"{ts_code} 获取到 {len(df)} 条K线数据")
        return df
        
    except Exception as e:
        logger.error(f"获取 {ts_code} K线数据失败: {str(e)}")
        return None

def save_kline_data(df, conn):
    """
    保存K线数据到数据库
    
    参数：
        df: K线数据DataFrame
        conn: 数据库连接
    
    返回：
        (added_count, updated_count)
    """
    added_count = 0
    updated_count = 0
    
    try:
        cursor = conn.cursor()
        
        # UPSERT SQL语句
        upsert_sql = """
        INSERT INTO stock_kline (code, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code, date) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume
        """
        
        for _, row in df.iterrows():
            try:
                cursor.execute(upsert_sql, (
                    row['code'],
                    row['date'],
                    row['open'],
                    row['high'],
                    row['low'],
                    row['close'],
                    row['volume']
                ))
                
                # 判断是新增还是更新
                if cursor.lastrowid > 0:
                    added_count += 1
                else:
                    # SQLite的lastrowid在UPDATE时可能为0，需要检查changes()
                    if cursor.connection.total_changes > 0:
                        updated_count += 1
                    
            except Exception as e:
                logger.debug(f"保存单条数据失败: {str(e)}")
        
        conn.commit()
        return (added_count, updated_count)
        
    except Exception as e:
        logger.error(f"保存K线数据失败: {str(e)}")
        conn.rollback()
        return (added_count, updated_count)

def main():
    """主函数"""
    if not TUSHARE_AVAILABLE:
        logger.error("Tushare不可用，请检查Tushare安装和token配置")
        return
    
    logger.info("=" * 60)
    logger.info(f"开始补充历史K线数据: {START_DATE} 至 {END_DATE}")
    logger.info("=" * 60)
    
    # 获取股票列表
    stock_list = get_stock_list()
    if not stock_list:
        logger.error("未获取到股票列表")
        return
    
    # 连接数据库
    conn = sqlite3.connect(DB_PATH)
    
    # 统计信息
    total_added = 0
    total_updated = 0
    total_failed = 0
    processed_count = 0
    
    # 分批处理（避免一次性处理太多）
    batch_size = 50
    total_batches = (len(stock_list) + batch_size - 1) // batch_size
    
    for batch_idx in range(total_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, len(stock_list))
        batch_stocks = stock_list[start_idx:end_idx]
        
        logger.info(f"\n处理批次 {batch_idx + 1}/{total_batches}")
        logger.info(f"股票范围: {start_idx + 1} - {end_idx}")
        
        for code in batch_stocks:
            processed_count += 1
            
            try:
                # 将数据库代码转换为Tushare格式
                ts_code = get_tushare_code(code)
                
                # 获取K线数据
                df = fetch_kline_data(ts_code, START_DATE, END_DATE)
                
                if df is not None and len(df) > 0:
                    # 将代码改回数据库格式（不带后缀）
                    df['code'] = code
                    
                    # 保存数据
                    added, updated = save_kline_data(df, conn)
                    total_added += added
                    total_updated += updated
                    
                    logger.info(f"[{processed_count}/{len(stock_list)}] {code}: 新增 {added} 条, 更新 {updated} 条")
                else:
                    total_failed += 1
                    logger.info(f"[{processed_count}/{len(stock_list)}] {code}: 无数据或获取失败")
                
                # 控制请求频率（避免超过Tushare限制）
                time.sleep(0.5)
                
            except Exception as e:
                total_failed += 1
                logger.error(f"[{processed_count}/{len(stock_list)}] {ts_code}: 处理失败 - {str(e)}")
    
    # 关闭数据库连接
    conn.close()
    
    logger.info("\n" + "=" * 60)
    logger.info("补充历史K线数据完成")
    logger.info(f"处理股票数: {len(stock_list)}")
    logger.info(f"新增记录数: {total_added}")
    logger.info(f"更新记录数: {total_updated}")
    logger.info(f"失败股票数: {total_failed}")
    logger.info("=" * 60)

if __name__ == '__main__':
    main()