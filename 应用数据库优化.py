#!/usr/bin/env python3
"""
应用数据库优化脚本

自动执行数据库性能优化
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.global_db import get_global_db
import sqlite3


def apply_database_optimization():
    """
    应用数据库性能优化
    """
    print("=" * 60)
    print("数据库性能优化")
    print("=" * 60)
    
    db_manager = get_global_db()
    conn = db_manager.connect()
    
    try:
        print("\n[1/4] 创建索引...")
        
        # K线数据表索引
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_code_date ON stock_kline(code, date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_date ON stock_kline(date)")
        print("  ✓ K线数据表索引创建完成")
        
        # 股票基本信息表索引
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_code ON stock_basic(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_name ON stock_basic(name)")
        print("  ✓ 股票基本信息表索引创建完成")
        
        # 选股记录表索引
        conn.execute("CREATE INDEX IF NOT EXISTS idx_selection_code_date ON stock_selection_record(stock_code, selection_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_selection_date ON stock_selection_record(selection_date)")
        print("  ✓ 选股记录表索引创建完成")
        
        # 更新日志表索引
        conn.execute("CREATE INDEX IF NOT EXISTS idx_update_log_date ON update_log(update_date)")
        print("  ✓ 更新日志表索引创建完成")
        
        print("\n[2/4] 配置SQLite性能参数...")
        
        # WAL模式
        conn.execute("PRAGMA journal_mode = WAL")
        print("  ✓ 启用WAL模式")
        
        # 同步模式
        conn.execute("PRAGMA synchronous = NORMAL")
        print("  ✓ 设置同步模式为NORMAL")
        
        # 缓存大小
        conn.execute("PRAGMA cache_size = -64000")
        print("  ✓ 设置缓存大小为64MB")
        
        # 临时表存储
        conn.execute("PRAGMA temp_store = MEMORY")
        print("  ✓ 临时表存储在内存中")
        
        # 自动清理
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        print("  ✓ 启用自动增量清理")
        
        print("\n[3/4] 分析表统计信息...")
        
        tables = ['stock_kline', 'stock_basic', 'stock_selection_record', 'update_log']
        for table in tables:
            try:
                conn.execute(f"ANALYZE {table}")
                print(f"  ✓ {table}")
            except Exception as e:
                print(f"  ⚠ {table}: {str(e)}")
        
        print("\n[4/4] 清理未使用空间...")
        try:
            # 获取优化前的数据库大小
            cursor = conn.execute("PRAGMA page_count")
            page_count_before = cursor.fetchone()[0]
            cursor = conn.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            size_before_mb = (page_count_before * page_size) / (1024 * 1024)
            
            # 执行VACUUM
            conn.execute("VACUUM")
            
            # 获取优化后的数据库大小
            cursor = conn.execute("PRAGMA page_count")
            page_count_after = cursor.fetchone()[0]
            size_after_mb = (page_count_after * page_size) / (1024 * 1024)
            
            saved_mb = size_before_mb - size_after_mb
            print(f"  ✓ 数据库优化完成")
            print(f"    优化前: {size_before_mb:.2f} MB")
            print(f"    优化后: {size_after_mb:.2f} MB")
            if saved_mb > 0:
                print(f"    节省空间: {saved_mb:.2f} MB")
        except Exception as e:
            print(f"  ⚠ VACUUM执行失败: {str(e)}")
        
        # 验证配置
        print("\n" + "=" * 60)
        print("当前数据库配置")
        print("=" * 60)
        
        configs = [
            ("journal_mode", "PRAGMA journal_mode"),
            ("synchronous", "PRAGMA synchronous"),
            ("cache_size", "PRAGMA cache_size"),
            ("temp_store", "PRAGMA temp_store"),
            ("page_size", "PRAGMA page_size"),
        ]
        
        for name, pragma in configs:
            cursor = conn.execute(pragma)
            value = cursor.fetchone()[0]
            print(f"  {name}: {value}")
        
        # 显示索引信息
        print("\n" + "=" * 60)
        print("已创建的索引")
        print("=" * 60)
        
        cursor = conn.execute("""
            SELECT name, tbl_name
            FROM sqlite_master
            WHERE type = 'index'
            AND name LIKE 'idx_%'
            ORDER BY tbl_name, name
        """)
        
        for row in cursor.fetchall():
            print(f"  {row[1]}: {row[0]}")
        
        print("\n" + "=" * 60)
        print("✓ 数据库优化完成！")
        print("=" * 60)
        print("\n建议:")
        print("  1. 运行性能测试验证效果: python 测试数据更新性能.py")
        print("  2. 观察下次数据更新的耗时")
        print("  3. 定期执行此优化脚本（建议每月一次）")
        
    except Exception as e:
        print(f"\n✗ 优化失败: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        conn.commit()
        conn.close()


if __name__ == "__main__":
    apply_database_optimization()