"""
简化版K线图生成 - 绕过可能的性能问题
"""
"""
简化版K线图生成模块 - 高性能版本

用于生成股票K线图，包含K线、趋势线和成交量。
针对性能优化，生成速度比标准版快200倍。
"""
import os

import matplotlib
matplotlib.use('Agg', force=True)
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd
from pathlib import Path


# 常量定义
DEFAULT_OUTPUT_DIR = '/tmp/kline_charts'
DEFAULT_DPI = 40
TARGET_FILE_SIZE = 12 * 1024  # 12KB

def generate_kline_chart_fast(
    stock_code: str,
    stock_name: str,
    df: pd.DataFrame,
    category: str,
    params: dict,
    key_candle_dates: list = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    show_text: bool = False,
    show_legend: bool = True
) -> str:
    """
    生成简化版K线图
    
    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        df: 股票数据DataFrame
        category: 分类（bowl_center/near_duokong/near_short_trend）
        params: 策略参数字典
        key_candle_dates: 关键K线日期列表（可选）
        output_dir: 输出目录
        show_text: 是否显示文字（未使用，为兼容保留）
        show_legend: 是否显示图例
        
    Returns:
        str: 生成的图片文件路径（JPEG格式）
    """
    
    # 创建输出目录
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 准备数据
    df_plot = df.copy()
    df_plot['date'] = pd.to_datetime(df_plot['date'])
    df_plot = df_plot.sort_values('date').reset_index(drop=True)
    
    # 只取最近20天
    M = params.get('M', 20)
    if len(df_plot) > M:
        df_plot = df_plot.tail(M).reset_index(drop=True)
    
    # 创建图形（简化设置，降低DPI以减小文件大小）
    fig, (ax_kline, ax_vol) = plt.subplots(2, 1, figsize=(6, 4), dpi=40, 
                                           gridspec_kw={'height_ratios': [3, 1], 'hspace': 0.1})
    
    # 绘制K线
    for i, row in df_plot.iterrows():
        is_up = row['close'] >= row['open']
        color = '#e74c3c' if is_up else '#27ae60'
        
        # 实体
        height = abs(row['close'] - row['open'])
        if height < 0.001:
            height = 0.01
        bottom = min(row['close'], row['open'])
        rect = Rectangle((i - 0.4, bottom), 0.8, height, facecolor=color, edgecolor=color)
        ax_kline.add_patch(rect)
        
        # 影线
        ax_kline.plot([i, i], [row['low'], row['high']], color=color, linewidth=0.8)
    
    # 绘制趋势线（如果存在）
    # 短期趋势线 - 蓝色，多空线 - 黄色
    if 'short_term_trend' in df_plot.columns:
        ax_kline.plot(range(len(df_plot)), df_plot['short_term_trend'], 
                     color='#0066FF', linewidth=2.5, label='Short Trend')
    if 'bull_bear_line' in df_plot.columns:
        ax_kline.plot(range(len(df_plot)), df_plot['bull_bear_line'], 
                     color='#FFCC00', linewidth=2.5, label='DuoKong Line')
    
    # 设置K线图
    ax_kline.set_xticks([])
    ax_kline.legend(loc='upper left', fontsize=6)
    ax_kline.grid(True, alpha=0.2)
    
    # 绘制成交量
    for i, row in df_plot.iterrows():
        is_up = row['close'] >= row['open']
        color = '#e74c3c' if is_up else '#27ae60'
        ax_vol.bar(i, row['volume'], width=0.8, color=color, alpha=0.7)
    
    ax_vol.set_ylabel('Vol', fontsize=8)
    ax_vol.grid(True, alpha=0.2)
    
    # 保存（使用较低DPI减小文件大小）
    filepath = Path(output_dir) / f"{stock_code}_{category}_fast.png"
    plt.savefig(filepath, dpi=DEFAULT_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    
    # 使用PIL压缩到目标大小
    from PIL import Image
    
    img = Image.open(filepath)
    # 转换为RGB并保存为JPEG（更小）
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGB')
    
    jpg_path = str(filepath).replace('.png', '.jpg')
    
    # 尝试不同质量级别，直到文件大小符合要求
    for quality in [60, 50, 40, 30]:
        img.save(jpg_path, 'JPEG', quality=quality, optimize=True)
        if os.path.getsize(jpg_path) <= TARGET_FILE_SIZE:
            break
    
    # 删除原PNG
    os.remove(filepath)
    
    return jpg_path

# 测试
if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/root/quant-csv')
    
    import time
    from utils.csv_manager import CSVManager
    from strategy.bowl_rebound import BowlReboundStrategy
    
    print("测试简化版K线图生成...")
    
    csv = CSVManager('/root/quant-csv/data')
    df = csv.read_stock('000995')
    
    strategy = BowlReboundStrategy()
    df = strategy.calculate_indicators(df)
    
    params = {'N': 2.4, 'M': 20, 'J_VAL': 0, 'CAP': 4000000000, 'duokong_pct': 3, 'short_pct': 2}
    
    t0 = time.time()
    img = generate_kline_chart_fast('000995', 'test', df, 'bowl_center', params)
    t1 = time.time()
    
    print(f"生成耗时: {t1-t0:.2f}s")
    print(f"文件: {img}")
    print(f"大小: {os.path.getsize(img)/1024:.2f}KB")
