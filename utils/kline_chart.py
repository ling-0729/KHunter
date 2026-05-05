"""
K线图可视化模块
生成包含策略参数、K线、均线、成交量、关键K线标记的图表
"""
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
import sys
import os

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'SimHei', 'Arial Unicode MS', 'WenQuanYi Micro Hei']
plt.rcParams['axes.unicode_minus'] = False

# 最大文件大小限制 (10KB)
MAX_FILE_SIZE = 10 * 1024


def compress_image(filepath: str, max_size: int = MAX_FILE_SIZE) -> str:
    """
    使用PIL二次压缩图片
    
    Args:
        filepath: 图片文件路径
        max_size: 最大文件大小（字节）
        
    Returns:
        str: 压缩后的文件路径
    """
    try:
        from PIL import Image
        
        # 获取当前文件大小
        current_size = os.path.getsize(filepath)
        if current_size <= max_size:
            return filepath
        
        # 打开图片
        img = Image.open(filepath)
        
        # 转换为RGB（去除透明通道）
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # 首先尝试PNG优化
        img.save(filepath, 'PNG', optimize=True)
        
        # 如果仍然超过限制，使用JPEG压缩
        if os.path.getsize(filepath) > max_size:
            # 尝试不同的质量级别 (更激进的压缩)
            for quality in [70, 60, 50, 40, 30]:
                img.save(filepath, 'JPEG', quality=quality, optimize=True)
                if os.path.getsize(filepath) <= max_size:
                    break
        
        final_size = os.path.getsize(filepath)
        print(f"   图片压缩: {current_size/1024:.1f}KB -> {final_size/1024:.1f}KB")
        
    except ImportError:
        # PIL不可用，跳过压缩
        pass
    except Exception as e:
        print(f"   图片压缩失败: {e}")
    
    return filepath


def generate_kline_chart(
    stock_code: str,
    stock_name: str,
    df: pd.DataFrame,
    category: str,
    params: dict,
    key_candle_dates: list,
    output_dir: str = '/tmp/kline_charts',
    show_text: bool = False,
    show_legend: bool = True
) -> str:
    """
    生成K线图
    
    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        df: M天历史数据DataFrame (需包含: date, open, close, high, low, volume, short_term_trend, bull_bear_line)
        category: 分类（bowl_center, near_duokong, near_short_trend）
        params: 策略参数字典
        key_candle_dates: 关键K线日期列表
        output_dir: 输出目录
        show_text: 是否显示文字（默认False，不显示以节省空间）
        show_legend: 是否显示图例（默认True）
        
    Returns:
        str: 生成的图片文件路径
    """
    # 创建输出目录
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 分类名称映射
    category_names = {
        'bowl_center': 'Bowl Center',
        'near_duokong': 'Near DuoKong',
        'near_short_trend': 'Near Short Trend'
    }
    category_name = category_names.get(category, category)
    
    # 准备数据 - 确保按日期正序排列（从早到晚）
    df = df.copy()
    if pd.api.types.is_datetime64_any_dtype(df['date']):
        df['date'] = pd.to_datetime(df['date'])
    else:
        df['date'] = pd.to_datetime(df['date'])
    
    # 按日期排序（正序）- 注意：需要在排序后重新计算趋势线
    df = df.sort_values('date').reset_index(drop=True)
    
    # 重新计算趋势线（需要足够的历史数据）- 优化：如果已有则跳过
    # MA114需要至少114天数据才能正确计算
    if 'close' in df.columns and len(df) >= 114:
        # 检查是否已有趋势线数据（策略已计算过）
        if 'short_term_trend' not in df.columns or 'bull_bear_line' not in df.columns:
            # 短期趋势线 = EMA(EMA(CLOSE,10),10)
            ema10 = df['close'].ewm(span=10, adjust=False, min_periods=1).mean()
            df['short_term_trend'] = ema10.ewm(span=10, adjust=False, min_periods=1).mean()
            
            # 多空线 = (MA14 + MA28 + MA57 + MA114) / 4
            ma14 = df['close'].rolling(window=14, min_periods=1).mean()
            ma28 = df['close'].rolling(window=28, min_periods=1).mean()
            ma57 = df['close'].rolling(window=57, min_periods=1).mean()
            ma114 = df['close'].rolling(window=114, min_periods=1).mean()
            df['bull_bear_line'] = (ma14 + ma28 + ma57 + ma114) / 4
        
        # 只显示最近M天（默认20天），但用全部数据计算了双线
        M = params.get('M', 20)
        if len(df) > M:
            df = df.tail(M).reset_index(drop=True)
    else:
        print(f"警告: 数据不足{len(df)}天，需要114天才能正确计算多空线")
    
    # 设置图表样式 (120dpi，清晰显示)
    if show_text:
        # 显示文字版本：保留顶部参数区域
        fig = plt.figure(figsize=(10, 8), dpi=120)
        gs = fig.add_gridspec(3, 1, height_ratios=[1.2, 5, 2], hspace=0.05)
        
        # ========== 顶部：策略参数 ==========
        ax_params = fig.add_subplot(gs[0])
        ax_params.axis('off')
        
        # 格式化参数显示
        cap = params.get('CAP', 4000000000)
        cap_display = f"{cap/1e8:.0f}B" if cap >= 1e8 else f"{cap/1e4:.0f}W"
        
        param_text = f"Strategy Params | N={params.get('N', 4)}  M={params.get('M', 15)}  J_VAL={params.get('J_VAL', 30)}  CAP={cap_display}"
        if 'duokong_pct' in params:
            param_text += f"  duokong_pct={params.get('duokong_pct')}%"
        if 'short_pct' in params:
            param_text += f"  short_pct={params.get('short_pct')}%"
        
        ax_params.text(0.5, 0.7, param_text, ha='center', va='center', 
                       fontsize=9, fontweight='bold', transform=ax_params.transAxes)
        
        # 股票标题
        title_text = f"{stock_code} {stock_name} - {category_name}"
        ax_params.text(0.5, 0.25, title_text, ha='center', va='center',
                       fontsize=11, fontweight='bold', color='#2c3e50', transform=ax_params.transAxes)
        
        # ========== 中部：K线图 ==========
        ax_kline = fig.add_subplot(gs[1])
    else:
        # 无文字版本：120dpi，清晰显示
        fig = plt.figure(figsize=(10, 7), dpi=120)
        gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.08)
        
        # ========== 上部：K线图（占更大比例） ==========
        ax_kline = fig.add_subplot(gs[0])
    
    ax_kline.set_xlim(-0.5, len(df) - 0.5)
    
    # 计算价格范围（包含上下影线）
    price_cols = ['high', 'low']
    if 'short_term_trend' in df.columns:
        price_cols.append('short_term_trend')
    if 'bull_bear_line' in df.columns:
        price_cols.append('bull_bear_line')
    
    price_max = df[price_cols].max().max()
    price_min = df[price_cols].min().min()
    price_range = price_max - price_min
    ax_kline.set_ylim(price_min - price_range * 0.1, price_max + price_range * 0.15)
    
    # 绘制K线
    width = 0.6
    for i, row in df.iterrows():
        is_up = row['close'] >= row['open']
        color = '#e74c3c' if is_up else '#27ae60'  # 涨红跌绿
        
        # 实体
        height = abs(row['close'] - row['open'])
        if height == 0:
            height = price_range * 0.005  # 最小显示高度（十字星）
        bottom = min(row['close'], row['open'])
        rect = Rectangle((i - width/2, bottom), width, height, 
                         facecolor=color, edgecolor=color, linewidth=0.5)
        ax_kline.add_patch(rect)
        
        # 影线
        ax_kline.plot([i, i], [row['low'], row['high']], color=color, linewidth=0.8)
        
        # 关键K线标记（星号）
        if row['date'] in key_candle_dates or (isinstance(row['date'], pd.Timestamp) and row['date'].strftime('%Y-%m-%d') in [d.strftime('%Y-%m-%d') if isinstance(d, pd.Timestamp) else d for d in key_candle_dates]):
            ax_kline.scatter(i, row['high'] + price_range * 0.03, marker='*', 
                           s=200, color='#f39c12', zorder=5)
    
    # 绘制趋势线（策略里的两根线）- 蓝色(短期)和绿色(多空)实线，加粗
    if 'short_term_trend' in df.columns:
        ax_kline.plot(range(len(df)), df['short_term_trend'], color='#0066FF', 
                     linewidth=2.5, linestyle='-', label='Short Trend', alpha=0.95)
    if 'bull_bear_line' in df.columns:
        ax_kline.plot(range(len(df)), df['bull_bear_line'], color='#00AA00', 
                     linewidth=2.5, linestyle='-', label='DuoKong Line', alpha=0.95)
    
    # 设置K线图标签和图例
    if show_text:
        ax_kline.set_ylabel('Price', fontsize=9)
        if show_legend:
            ax_kline.legend(loc='upper left', fontsize=7, framealpha=0.8)
        ax_kline.grid(True, alpha=0.2, linestyle='--')
    else:
        # 无文字版本：简化标签
        ax_kline.set_ylabel('')
        if show_legend:
            # 简化图例，使用更小的字体和透明背景
            ax_kline.legend(loc='upper left', fontsize=6, framealpha=0.5, 
                          fancybox=False, edgecolor='none')
        ax_kline.grid(True, alpha=0.15, linestyle='--')
        # 移除边框
        ax_kline.spines['top'].set_visible(False)
        ax_kline.spines['right'].set_visible(False)
    
    # 设置x轴刻度
    xticks = range(0, len(df), max(1, len(df) // 6))
    xlabels = [df.iloc[i]['date'].strftime('%m-%d') for i in xticks]
    ax_kline.set_xticks(xticks)
    ax_kline.set_xticklabels([])  # K线图不显示日期，留给成交量图
    
    # 添加图例说明 (仅在显示文字时)
    if show_text:
        legend_text = "Short|DuoKong|Key"
        ax_kline.text(0.02, 0.98, legend_text, transform=ax_kline.transAxes,
                     fontsize=7, verticalalignment='top', bbox=dict(boxstyle='round', 
                     facecolor='wheat', alpha=0.3))
    
    # ========== 底部：成交量 ==========
    if show_text:
        ax_vol = fig.add_subplot(gs[2], sharex=ax_kline)
    else:
        ax_vol = fig.add_subplot(gs[1], sharex=ax_kline)
    
    # 计算成交量范围
    vol_max = df['volume'].max()
    ax_vol.set_ylim(0, vol_max * 1.2)
    
    # 绘制成交量柱状图
    for i, row in df.iterrows():
        is_up = row['close'] >= row['open']
        color = '#e74c3c' if is_up else '#27ae60'  # 与K线同色
        
        # 成交量柱
        ax_vol.bar(i, row['volume'], width=0.7, color=color, alpha=0.7, edgecolor=color)
    
    # 设置成交量图标签
    if show_text:
        ax_vol.set_ylabel('Vol', fontsize=8)
        ax_vol.set_xlabel('Date', fontsize=8)
        ax_vol.grid(True, alpha=0.15, linestyle='--', axis='y')
        
        # 设置日期标签 (减少标签数量)
        xticks = range(0, len(df), max(1, len(df) // 4))
        xlabels = [df.iloc[i]['date'].strftime('%m-%d') for i in xticks]
        ax_vol.set_xticks(xticks)
        ax_vol.set_xticklabels(xlabels, rotation=30, ha='right', fontsize=7)
    else:
        # 无文字版本：简化标签和刻度
        ax_vol.set_ylabel('')
        ax_vol.set_xlabel('')
        ax_vol.grid(True, alpha=0.1, linestyle='--', axis='y')
        
        # 最小化日期标签
        xticks = range(0, len(df), max(1, len(df) // 3))
        xlabels = [df.iloc[i]['date'].strftime('%m-%d') for i in xticks]
        ax_vol.set_xticks(xticks)
        ax_vol.set_xticklabels(xlabels, rotation=0, ha='center', fontsize=6)
        
        # 移除边框
        ax_vol.spines['top'].set_visible(False)
        ax_vol.spines['right'].set_visible(False)
    
    # 保存图片 (使用较低DPI和优化)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{stock_code}_{category}_{timestamp}.png"
    filepath = Path(output_dir) / filename
    
    # 无文字版本使用更低DPI进一步压缩
    save_dpi = 50 if show_text else 40
    plt.savefig(filepath, dpi=save_dpi, bbox_inches='tight', facecolor='white', edgecolor='none', 
                pil_kwargs={'optimize': True})
    plt.close(fig)
    
    # 使用PIL二次压缩
    compress_image(str(filepath), MAX_FILE_SIZE)
    
    return str(filepath)


def generate_simple_chart(
    stock_code: str,
    stock_name: str,
    df: pd.DataFrame,
    category: str,
    params: dict,
    key_candle_dates: list,
    output_dir: str = '/tmp/kline_charts',
    show_text: bool = False,
    show_legend: bool = True
) -> str:
    """
    生成简化版K线图（用于快速测试）
    """
    return generate_kline_chart(stock_code, stock_name, df, category, params, key_candle_dates, 
                               output_dir, show_text, show_legend)


if __name__ == '__main__':
    # 测试代码
    print("K-Line Chart Module Test")
    
    # 创建测试数据
    test_data = {
        'date': pd.date_range('2026-02-01', periods=20, freq='D'),
        'open': [10.0 + i * 0.1 + np.random.randn() * 0.1 for i in range(20)],
        'close': [10.1 + i * 0.12 + np.random.randn() * 0.1 for i in range(20)],
        'high': [10.2 + i * 0.15 + np.random.randn() * 0.1 for i in range(20)],
        'low': [9.9 + i * 0.08 + np.random.randn() * 0.1 for i in range(20)],
        'volume': [100000 + np.random.randint(0, 50000) for _ in range(20)],
        'short_term_trend': [10.5 + i * 0.1 for i in range(20)],
        'bull_bear_line': [10.2 + i * 0.08 for i in range(20)],
    }
    
    # 确保 close >= open 时 high >= close, low <= open
    for i in range(20):
        test_data['high'][i] = max(test_data['high'][i], test_data['open'][i], test_data['close'][i]) + 0.05
        test_data['low'][i] = min(test_data['low'][i], test_data['open'][i], test_data['close'][i]) - 0.05
    
    test_df = pd.DataFrame(test_data)
    
    test_params = {
        'N': 2.4,
        'M': 20,
        'CAP': 4000000000,
        'J_VAL': 30,
        'duokong_pct': 3,
        'short_pct': 2
    }
    
    key_dates = [test_df.iloc[5]['date'], test_df.iloc[10]['date']]
    
    output = generate_kline_chart(
        stock_code='000001',
        stock_name='Ping An Bank',
        df=test_df,
        category='bowl_center',
        params=test_params,
        key_candle_dates=key_dates,
        output_dir='/tmp/kline_charts'
    )
    
    print(f"Chart generated: {output}")
