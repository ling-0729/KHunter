"""
测试脚本：阻力位突破策略 - 500只股票样本测试
验证策略在真实数据上的选股效果和各条件通过率
"""
import pandas as pd
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.resistance_breakout import ResistanceBreakoutStrategy


def test_resistance_breakout_strategy():
    """在500只股票样本上验证阻力位突破策略"""
    print("=" * 70)
    print("阻力位突破策略 - 500只股票样本测试")
    print("=" * 70)

    strategy = ResistanceBreakoutStrategy()

    # 读取股票名称映射
    names_file = Path(__file__).parent.parent / 'data' / 'stock_names.json'
    stock_names = {}
    if names_file.exists():
        with open(names_file, 'r', encoding='utf-8') as f:
            stock_names = json.load(f)

    # 输出策略参数
    print("\n策略参数：")
    for k, v in strategy.params.items():
        print(f"  {k}: {v}")

    # 收集股票文件（从各板块前部取）
    data_root = Path(__file__).parent.parent / 'data'
    stock_files = []
    boards = [('00', 0, 150), ('30', 0, 100), ('60', 0, 150), ('68', 0, 100)]
    for board, skip, count in boards:
        d = data_root / board
        if d.exists():
            fs = sorted(d.glob('*.csv'))
            stock_files.extend(fs[skip:skip + count])
    stock_files = stock_files[:500]
    print(f"\n共读取 {len(stock_files)} 只股票")

    # 统计变量
    total = len(stock_files)
    selected = []
    errors = 0
    stats = {
        'data_valid': 0, 'name_valid': 0, 'market_cap_valid': 0,
        'breakout_found': 0,
        'pullback_pass': 0, 'trend_pass': 0,
    }

    for i, sf in enumerate(stock_files, 1):
        try:
            code = sf.stem
            name = stock_names.get(code, code)

            df = pd.read_csv(sf, parse_dates=['date'])
            # 数据验证
            if not strategy._validate_data(df):
                continue
            stats['data_valid'] += 1

            # 名称过滤
            if name:
                if any(kw in name for kw in ['退', '未知', '退市', '已退']):
                    continue
                if name.startswith('ST') or name.startswith('*ST'):
                    continue
            stats['name_valid'] += 1

            # 计算指标
            df_ind = strategy.calculate_indicators(df)
            latest = df_ind.iloc[-1]

            # 市值过滤
            mc = latest['market_cap'] / 1e8
            if mc < strategy.params['min_market_cap']:
                continue
            if mc > strategy.params['max_market_cap']:
                continue
            stats['market_cap_valid'] += 1

            # 逐条件检查（统计通过率）
            pos = strategy._find_breakout_day(df_ind)
            if pos is not None:
                stats['breakout_found'] += 1
                if strategy._check_pullback(df_ind, pos):
                    stats['pullback_pass'] += 1
            if strategy._check_trend(df_ind):
                stats['trend_pass'] += 1

            # 完整选股
            results = strategy.select_stocks(df, stock_name=name)
            if results:
                for r in results:
                    r['stock_code'] = code
                    r['stock_name'] = name
                    selected.append(r)

            if i % 100 == 0:
                print(f"已处理 {i}/{total}，已选股 {len(selected)} 只")

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"处理 {sf.stem} 出错: {e}")

    # 输出统计
    print(f"\n{'=' * 70}")
    print("选股结果统计")
    print(f"{'=' * 70}")
    print(f"总股票数: {total}")
    print(f"选股数量: {len(selected)}")
    pct = len(selected) / total * 100 if total > 0 else 0
    print(f"选股比例: {pct:.2f}%")
    print(f"错误数量: {errors}")

    # 各条件通过率
    base = stats['market_cap_valid'] or 1
    print(f"\n{'=' * 70}")
    print("各条件通过率")
    print(f"{'=' * 70}")
    dv = stats['data_valid']
    print(f"  数据有效: {dv}/{total} ({dv/total*100:.1f}%)")
    nv = stats['name_valid']
    print(f"  名称有效: {nv}/{dv} ({nv/(dv or 1)*100:.1f}%)")
    mv = stats['market_cap_valid']
    print(f"  市值有效: {mv}/{nv} ({mv/(nv or 1)*100:.1f}%)")
    bf = stats['breakout_found']
    print(f"  放量长阳突破: {bf}/{base} ({bf/base*100:.1f}%)")
    pp = stats['pullback_pass']
    print(f"  回踩通过: {pp}/{bf or 1} ({pp/(bf or 1)*100:.1f}%)")
    tp = stats['trend_pass']
    print(f"  趋势通过: {tp}/{base} ({tp/base*100:.1f}%)")

    # 输出选股详情
    if selected:
        print(f"\n{'=' * 70}")
        print("选股股票详细信息")
        print(f"{'=' * 70}\n")
        for idx, s in enumerate(selected, 1):
            print(f"【{idx}】{s['stock_code']} {s['stock_name']}")
            print(f"  日期={s['date']} 收盘={s['close']}")
            print(f"  阻力位={s['resistance_level']} 突破={s['breakout_ratio']*100:.2f}%")
            bd = s.get('breakout_date', '')
            ds = s.get('days_since_breakout', '')
            print(f"  突破日={bd} 距今{ds}天")
            print(f"  量比={s['volume_ratio']} 趋势={s['short_term_trend']}")
            print(f"  原因: {', '.join(s['reasons'])}")
            print()
    else:
        print("\n未找到符合条件的股票")
        print("  可能原因：当前市场环境下满足全部5个条件的股票较少")

    print(f"\n{'=' * 70}")
    print("测试完成")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    test_resistance_breakout_strategy()
