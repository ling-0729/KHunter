#!/usr/bin/env python3
"""
全市场数据初始化脚本
功能：获取全市场所有股票的1年历史数据，保留现有数据，补充缺失的
使用：python init_full_market_data.py
"""
import sys
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from main import QuantSystem


def main():
    """主函数：执行全市场数据初始化"""
    print("\n" + "=" * 70)
    print("🌍 全市场数据初始化")
    print("=" * 70)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n配置信息:")
    print("  • 数据范围: 全市场所有股票")
    print("  • 数据周期: 1年历史数据")
    print("  • 保留策略: 保留现有数据，补充缺失的")
    print("  • 限制数量: 无限制（全市场）")
    print("\n" + "=" * 70)
    
    try:
        # 初始化系统
        quant_system = QuantSystem("config/config.yaml")
        
        # 执行全市场数据初始化（1年数据）
        print("\n正在初始化全市场数据...")
        quant_system.init_data(max_stocks=None, years=1)
        
        # 完成提示
        print("\n" + "=" * 70)
        print("✓ 全市场数据初始化完成")
        print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        print("\n后续步骤:")
        print("  1. 启动Web服务器: python web_server.py")
        print("  2. 打开浏览器访问: http://127.0.0.1:5000")
        print("  3. 执行选股操作")
        print("\n")
        
        return 0
    
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断了初始化过程")
        return 1
    
    except Exception as e:
        print(f"\n\n❌ 初始化失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
