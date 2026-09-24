#!/usr/bin/env python3
"""
测试数据更新性能脚本

用于验证优化前后的性能对比
"""
import time
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.db_manager import DBManager
from utils.stock_data_fetcher import StockDataFetcher
from utils.kline_updater import KlineUpdater
from utils.global_db import get_global_db
from datetime import datetime, timedelta


def test_update_performance(num_stocks=100, batch_size=500):
    """
    测试数据更新性能
    
    参数：
        num_stocks: 测试的股票数量
        batch_size: 批次大小
    """
    print("=" * 60)
    print(f"数据更新性能测试")
    print(f"测试股票数: {num_stocks}")
    print(f"批次大小: {batch_size}")
    print("=" * 60)
    
    # 初始化组件
    db_manager = get_global_db()
    stock_data_fetcher = StockDataFetcher()
    kline_updater = KlineUpdater(db_manager, stock_data_fetcher)
    
    # 获取股票列表
    print("\n获取股票列表...")
    stock_codes = db_manager.list_all_stocks()
    
    if not stock_codes:
        print("✗ 数据库中没有股票数据")
        return
    
    # 只测试前N只股票
    test_codes = stock_codes[:num_stocks]
    print(f"✓ 获取到 {len(test_codes)} 只股票用于测试")
    
    # 计算测试日期范围
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    print(f"\n测试参数:")
    print(f"  起始日期: {start_date}")
    print(f"  结束日期: {end_date}")
    print(f"  批次大小: {batch_size}")
    print(f"  测试股票: {len(test_codes)} 只")
    
    # 开始测试
    print(f"\n开始测试...")
    start_time = time.time()
    
    try:
        result = kline_updater.update_kline_data(
            stock_codes=test_codes,
            last_update_date=start_date,
            target_date=end_date,
            batch_size=batch_size
        )
        
        elapsed = time.time() - start_time
        
        # 显示结果
        print("\n" + "=" * 60)
        print("测试结果")
        print("=" * 60)
        print(f"✓ 测试完成")
        print(f"\n统计信息:")
        print(f"  新增记录: {result['added']} 条")
        print(f"  更新记录: {result['updated']} 条")
        print(f"  失败数量: {result['failed']} 只")
        print(f"  测试耗时: {elapsed:.2f} 秒")
        print(f"  平均速度: {len(test_codes) / elapsed:.2f} 只/秒")
        
        # 预估全量更新时间
        total_stocks = len(stock_codes)
        estimated_time = (total_stocks / len(test_codes)) * elapsed
        estimated_minutes = estimated_time / 60
        
        print(f"\n性能预估:")
        print(f"  全量股票数: {total_stocks} 只")
        print(f"  预估总耗时: {estimated_time:.1f} 秒 = {estimated_minutes:.1f} 分钟")
        
        # 性能评级
        if estimated_minutes < 5:
            rating = "优秀 ⭐⭐⭐⭐⭐"
        elif estimated_minutes < 10:
            rating = "良好 ⭐⭐⭐⭐"
        elif estimated_minutes < 20:
            rating = "一般 ⭐⭐⭐"
        elif estimated_minutes < 60:
            rating = "较慢 ⭐⭐"
        else:
            rating = "需要优化 ⭐"
        
        print(f"  性能评级: {rating}")
        
        # 给出优化建议
        if estimated_minutes > 10:
            print(f"\n优化建议:")
            if batch_size < 500:
                print(f"  - 建议增大批次大小到 500")
            print(f"  - 确保已启用并发处理（max_workers=20）")
            print(f"  - 运行数据库优化脚本: python 应用数据库优化.py")
            print(f"  - 检查网络连接质量")
        
        print("=" * 60)
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n✗ 测试失败: {str(e)}")
        print(f"  已耗时: {elapsed:.2f} 秒")
        import traceback
        traceback.print_exc()


def test_concurrent_vs_serial():
    """
    对比并发和串行的性能差异
    """
    print("=" * 60)
    print("并发 vs 串行性能对比测试")
    print("=" * 60)
    
    # 测试少量股票以节省时间
    num_stocks = 50
    
    print(f"\n测试股票数: {num_stocks}")
    print("\n提示: 此测试需要修改代码以启用串行模式")
    print("当前版本已默认使用并发模式，无法直接对比")
    print("建议查看优化前后的日志文件进行对比")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='测试数据更新性能')
    parser.add_argument('--stocks', type=int, default=100, help='测试的股票数量（默认100）')
    parser.add_argument('--batch-size', type=int, default=500, help='批次大小（默认500）')
    parser.add_argument('--compare', action='store_true', help='进行并发vs串行对比测试')
    
    args = parser.parse_args()
    
    if args.compare:
        test_concurrent_vs_serial()
    else:
        test_update_performance(args.stocks, args.batch_size)