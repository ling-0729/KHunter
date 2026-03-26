#!/usr/bin/env python3
"""
A股量化选股系统 - 主程序

使用方法:
    python main.py init      # 首次全量抓取
    python main.py update    # 每日增量更新（内部使用）
    python main.py select    # 执行选股
    python main.py run       # 完整流程（更新+选股+通知）
    python main.py schedule  # 启动定时调度
"""
import sys
import os
import argparse
import platform
from pathlib import Path
from datetime import datetime, time as dt_time
import time

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 版本信息
__version__ = "1.0.0"

from utils.akshare_fetcher import AKShareFetcher
from utils.csv_manager import CSVManager
from strategy.strategy_registry import get_registry
from utils.kline_chart import generate_kline_chart
import yaml


class QuantSystem:
    """量化系统主类"""
    
    def __init__(self, config_file="config/config.yaml"):
        self.config = self._load_config(config_file)
        self.data_dir = self.config.get('data_dir', 'data')
        self.csv_manager = CSVManager(self.data_dir)
        self.fetcher = AKShareFetcher(self.data_dir)
        self.registry = get_registry("config/strategy_params.yaml")
    
    def _load_config(self, config_file):
        """加载配置文件"""
        config_path = Path(config_file)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}
    

    def _load_stock_names(self, stock_data):
        """加载股票名称（优先从CSV文件）"""
        names_file = Path(self.data_dir) / 'stock_names.json'
        
        # 尝试从网络获取
        try:
            stock_names = self.fetcher.get_all_stock_codes()
            if stock_names:
                # 保存到本地
                import json
                with open(names_file, 'w', encoding='utf-8') as f:
                    json.dump(stock_names, f, ensure_ascii=False)
                return stock_names
        except:
            pass
        
        # 从本地缓存读取
        if names_file.exists():
            import json
            with open(names_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 使用默认名称
        return {code: f"股票{code}" for code in stock_data.keys()}
    
    def init_data(self, max_stocks=None, years=1):
        """首次全量抓取"""
        print("=" * 60)
        print("🚀 首次全量数据抓取")
        print("=" * 60)
        self.fetcher.init_full_data(max_stocks=max_stocks, years=years)
        print("\n✓ 数据初始化完成")

    def _smart_update(self, max_stocks=None, check_latest=True):
        """智能更新：3点前不更新，检查每只股票是否有当天数据"""
        from datetime import datetime
        import pandas as pd

        today = datetime.now().date()
        current_time = datetime.now().time()
        market_close_time = datetime.strptime("15:00", "%H:%M").time()

        # 3点前：不更新，使用旧数据
        if current_time < market_close_time:
            print("\n⏰ 当前时间尚未收盘 (15:00)")
            print("  使用本地已有数据，跳过网络更新")
            return

        # 检查每只股票是否有当天数据
        if check_latest:
            print("\n🔍 检查数据更新状态...")
            stock_codes = self.csv_manager.list_all_stocks()
            if max_stocks:
                stock_codes = stock_codes[:max_stocks]

            total = len(stock_codes)
            has_today = 0
            no_today = 0
            check_limit = min(100, total)  # 抽样检查100只

            for code in stock_codes[:check_limit]:
                df = self.csv_manager.read_stock(code)
                if not df.empty:
                    latest_date = pd.to_datetime(df.iloc[0]['date']).date()
                    if latest_date == today:
                        has_today += 1
                    else:
                        no_today += 1

            # 如果100%股票都有今天数据，跳过更新
            if check_limit > 0 and has_today == check_limit:
                print(f"  ✓ 已检查 {check_limit} 只股票，全部已有今天数据")
                print("  数据已是最新，跳过网络更新")
                return
            else:
                print(f"  已检查 {check_limit} 只，{has_today} 只有今天数据，{no_today} 只需要更新")

        # 执行更新
        print("\n🔄 执行数据更新...")
        self.fetcher.daily_update(max_stocks=max_stocks)
        print("\n✓ 数据更新完成")

    def update_data(self, max_stocks=None):
        """每日增量更新"""
        print("=" * 60)
        print("🔄 每日增量更新")
        print("=" * 60)
        self.fetcher.daily_update(max_stocks=max_stocks)
        print("\n✓ 数据更新完成")

    def select_stocks(self, category='all', max_stocks=None, return_data=False):
        """执行选股
        :param category: 股票分类筛选，'all'表示全部，其他值按分类筛选
        :param max_stocks: 限制处理的股票数量（用于快速测试）
        :param return_data: 是否返回股票数据字典（用于K线图生成）
        :return: (results, stock_names) 或 (results, stock_names, stock_data_dict)
        """
        print("=" * 60)
        print("🎯 执行选股策略")
        if max_stocks:
            print(f"   快速测试模式：只处理前 {max_stocks} 只股票")
        print("=" * 60)
        
        # 加载策略
        print("\n加载策略...")
        self.registry.auto_register_from_directory("strategy")
        
        if not self.registry.list_strategies():
            print("✗ 没有找到可用策略")
            return {}, {}
        
        print(f"已加载 {len(self.registry.list_strategies())} 个策略")
        
        # 输出当前策略参数
        print("\n当前策略参数:")
        for strategy_name, strategy_obj in self.registry.strategies.items():
            print(f"\n  🎯 {strategy_name}:")
            for param_name, param_value in strategy_obj.params.items():
                # 对特定参数添加说明
                note = ""
                if param_name == 'N':
                    note = " (成交量倍数)"
                elif param_name == 'M':
                    note = " (回溯天数)"
                elif param_name == 'CAP':
                    note = f" ({param_value/1e8:.0f}亿市值门槛)"
                elif param_name == 'J_VAL':
                    note = " (J值上限)"
                elif param_name in ['M1', 'M2', 'M3', 'M4']:
                    note = " (MA周期)"
                print(f"      {param_name}: {param_value}{note}")
        
        # 加载股票数据（流式处理，不预存全部数据）
        print("\n执行选股（流式处理，降低内存占用）...")
        stock_codes = self.csv_manager.list_all_stocks()
        
        if not stock_codes:
            print("✗ 没有股票数据，请先执行 init 或 update")
            return {}, {}
        
        print(f"共 {len(stock_codes)} 只股票")
        
        # 先获取股票名称
        stock_names = self._load_stock_names({})
        
        # 流式选股处理
        import gc
        results = {}
        indicators_dict = {}  # 只保存入选股票的数据
        category_count = {'bowl_center': 0, 'near_duokong': 0, 'near_short_trend': 0}
        
        # 限制处理数量
        process_codes = stock_codes[:max_stocks] if max_stocks else stock_codes
        
        for strategy_name, strategy in self.registry.strategies.items():
            print(f"\n执行策略: {strategy_name}")
            signals = []
            valid_count = 0
            invalid_count = 0
            
            for i, code in enumerate(process_codes, 1):
                # 读取单只股票
                df = self.csv_manager.read_stock(code)
                name = stock_names.get(code, '未知')
                
                # 过滤
                invalid_keywords = ['退', '未知', '退市', '已退']
                if any(kw in name for kw in invalid_keywords):
                    invalid_count += 1
                    continue
                
                # 过滤 ST/*ST 股票
                if name.startswith('ST') or name.startswith('*ST'):
                    invalid_count += 1
                    continue
                if df.empty or len(df) < 60:
                    continue
                
                valid_count += 1
                
                # 计算指标
                df_with_indicators = strategy.calculate_indicators(df)
                
                # 选股
                signal_list = strategy.select_stocks(df_with_indicators, name)
                
                if signal_list:
                    for s in signal_list:
                        cat = s.get('category', 'unknown')
                        category_count[cat] = category_count.get(cat, 0) + 1
                        
                        if category == 'all' or cat == category:
                            signals.append({
                                'code': code,
                                'name': name,
                                'signals': [s]
                            })
                            # 只保存入选股票的数据
                            if return_data:
                                indicators_dict[code] = df_with_indicators
                
                # 释放内存
                del df, df_with_indicators
                
                # 每100只显示进度并GC
                if i % 100 == 0 or i == len(process_codes):
                    gc.collect()
                    print(f"  进度: [{i}/{len(process_codes)}] 有效 {valid_count} 只，选出 {len(signals)} 只...")
            
            results[strategy_name] = signals
            print(f"  ✓ 选股完成: 共 {len(signals)} 只 (过滤 {invalid_count} 只)")
        
        # 显示结果汇总
        print("\n" + "=" * 60)
        print("📊 选股结果汇总")
        print("=" * 60)
        
        for strategy_name, signals in results.items():
            print(f"\n{strategy_name}: {len(signals)} 只")
            for signal in signals:
                code = signal['code']
                name = signal.get('name', stock_names.get(code, '未知'))
                for s in signal['signals']:
                    cat_emoji = {'bowl_center': '🥣', 'near_duokong': '📊', 'near_short_trend': '📈'}.get(s.get('category'), '❓')
                    print(f"  {cat_emoji} {code} {name}: 价格={s['close']}, J={s['J']}, 理由={s['reasons']}")
        
        # 显示分类统计
        print("\n" + "-" * 60)
        print("分类统计:")
        print(f"  🥣 回落碗中: {category_count.get('bowl_center', 0)} 只")
        print(f"  📊 靠近多空线: {category_count.get('near_duokong', 0)} 只")
        print(f"  📈 靠近短期趋势线: {category_count.get('near_short_trend', 0)} 只")
        print("-" * 60)
        
        # 如果需要返回数据字典（用于K线图生成）
        if return_data:
            # 返回计算了指标的数据（包含趋势线）
            return results, stock_names, indicators_dict
        
        return results, stock_names
    
    def run_full(self, category='all', max_stocks=None):
        """完整流程：更新 + 选股
        :param max_stocks: 限制处理的股票数量（用于快速测试）
        """
        from datetime import datetime
        import json
        from pathlib import Path

        print("=" * 60)
        print("🚀 执行完整流程")
        if max_stocks:
            print(f"   快速测试模式：只处理前 {max_stocks} 只股票")
        print("=" * 60)

        # 1. 更新数据（内置逻辑：3点前不更新，检查每只股票是否有当天数据）
        self._smart_update(max_stocks=max_stocks)

        # 2. 选股（返回数据和结果）
        results, stock_names, stock_data_dict = self.select_stocks(category=category, max_stocks=max_stocks, return_data=True)

        return results
    
    def select_with_b1_match(self, category='all', max_stocks=None, min_similarity=None, lookback_days=None):
        """
        执行选股 + B1完美图形匹配排序
        
        Args:
            category: 股票分类筛选，'all'表示全部
            max_stocks: 限制处理的股票数量
            min_similarity: 最小相似度阈值，低于此值不显示
            lookback_days: 回看天数，默认25天
            
        Returns:
            dict: 包含选股结果和匹配结果
        """
        # 从配置读取默认值
        from strategy.pattern_config import MIN_SIMILARITY_SCORE, DEFAULT_LOOKBACK_DAYS
        if min_similarity is None:
            min_similarity = MIN_SIMILARITY_SCORE
        if lookback_days is None:
            lookback_days = DEFAULT_LOOKBACK_DAYS
        
        print("=" * 60)
        print("🎯 执行选股 + B1完美图形匹配")
        if max_stocks:
            print(f"   快速测试模式：只处理前 {max_stocks} 只股票")
        print(f"   相似度阈值: {min_similarity}%")
        print(f"   回看天数: {lookback_days}天")
        print("=" * 60)
        
        # 1. 先执行原有选股逻辑
        print("\n[1/3] 执行策略选股...")
        results, stock_names, stock_data_dict = self.select_stocks(
            category=category, 
            max_stocks=max_stocks, 
            return_data=True
        )
        
        # 统计选股总数
        total_selected = sum(len(signals) for signals in results.values())
        if total_selected == 0:
            print("\n✗ 策略未选出任何股票，跳过匹配")
            return {'results': results, 'stock_names': stock_names, 'matched': []}
        
        print(f"\n✓ 策略选出 {total_selected} 只股票")
        
        # 2. 初始化B1完美图形库
        print("\n[2/3] 初始化B1完美图形库...")
        try:
            from strategy.pattern_library import B1PatternLibrary
            from strategy.pattern_config import MIN_SIMILARITY_SCORE
            
            library = B1PatternLibrary(self.csv_manager)
            
            if not library.cases:
                print("⚠️ 警告: 案例库为空，可能数据不足")
                return {'results': results, 'stock_names': stock_names, 'matched': []}
            
            print(f"✓ 案例库加载完成: {len(library.cases)} 个案例")
            
        except Exception as e:
            print(f"✗ 初始化案例库失败: {e}")
            import traceback
            traceback.print_exc()
            return {'results': results, 'stock_names': stock_names, 'matched': []}
        
        # 3. 对每只候选股进行匹配
        print("\n[3/3] 执行B1完美图形匹配...")
        matched_results = []
        
        for strategy_name, signals in results.items():
            for signal in signals:
                code = signal['code']
                name = signal.get('name', stock_names.get(code, '未知'))
                
                # 获取该股票的完整数据
                if code not in stock_data_dict:
                    continue
                
                df = stock_data_dict[code]
                if df.empty:
                    continue
                
                try:
                    # 匹配最佳案例（使用指定回看天数）
                    match_result = library.find_best_match(code, df, lookback_days=lookback_days)
                    
                    if match_result.get('best_match'):
                        best = match_result['best_match']
                        score = best.get('similarity_score', 0)
                        
                        # 只保留超过阈值的股票
                        if score >= min_similarity:
                            # 获取第一个信号的信息
                            s = signal['signals'][0] if signal.get('signals') else {}
                            
                            matched_results.append({
                                'stock_code': code,
                                'stock_name': name,
                                'strategy': strategy_name,
                                'category': s.get('category', 'unknown'),
                                'close': s.get('close', '-'),
                                'J': s.get('J', '-'),
                                'similarity_score': score,
                                'matched_case': best.get('case_name', ''),
                                'matched_date': best.get('case_date', ''),
                                'matched_code': best.get('case_code', ''),
                                'breakdown': best.get('breakdown', {}),
                                'tags': best.get('tags', []),
                                'all_matches': best.get('all_matches', []),
                            })
                            
                except Exception as e:
                    print(f"  ⚠️ 匹配 {code} 失败: {e}")
                    continue
        
        # 按相似度排序
        matched_results.sort(key=lambda x: x['similarity_score'], reverse=True)
        
        print(f"\n✓ 匹配完成: {len(matched_results)} 只股票超过阈值")
        
        # 显示Top N结果（使用配置）
        from strategy.pattern_config import TOP_N_RESULTS
        if matched_results:
            print("\n" + "=" * 60)
            print(f"📊 Top {TOP_N_RESULTS} B1完美图形匹配结果")
            print("=" * 60)
            for i, r in enumerate(matched_results[:TOP_N_RESULTS], 1):
                emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                print(f"{emoji} {r['stock_code']} {r['stock_name']}")
                print(f"   相似度: {r['similarity_score']}% | 匹配: {r['matched_case']}")
                bd = r.get('breakdown', {})
                print(f"   趋势:{bd.get('trend_structure', 0)}% "
                      f"KDJ:{bd.get('kdj_state', 0)}% "
                      f"量能:{bd.get('volume_pattern', 0)}% "
                      f"形态:{bd.get('price_shape', 0)}%")
        
        return {
            'results': results,
            'stock_names': stock_names,
            'matched': matched_results,
            'total_selected': total_selected,
        }
    
    def run_with_b1_match(self, category='all', max_stocks=None, min_similarity=60.0, lookback_days=25):
        """
        完整流程：更新 + 选股 + B1完美图形匹配

        Args:
            category: 股票分类筛选
            max_stocks: 限制处理的股票数量
            min_similarity: 最小相似度阈值
            lookback_days: 回看天数，默认25天
        """
        from datetime import datetime

        print("=" * 60)
        print("🚀 执行完整流程（含B1完美图形匹配）")
        if max_stocks:
            print(f"   快速测试模式：只处理前 {max_stocks} 只股票")
        print(f"   回看天数: {lookback_days}天")
        print("=" * 60)

        # 1. 更新数据
        self._smart_update(max_stocks=max_stocks)

        # 2. 选股 + B1完美图形匹配
        match_result = self.select_with_b1_match(
            category=category,
            max_stocks=max_stocks,
            min_similarity=min_similarity,
            lookback_days=lookback_days
        )
        
        return match_result
    
    def run_schedule(self):
        """启动定时调度"""
        try:
            import schedule
        except ImportError:
            print("✗ 请安装 schedule: pip install schedule")
            return
        
        schedule_time = self.config.get('schedule', {}).get('time', '15:05')
        
        print("=" * 60)
        print(f"⏰ 启动定时调度")
        print(f"   每日 {schedule_time} 执行选股任务")
        print("=" * 60)
        
        # 设置定时任务
        schedule.every().day.at(schedule_time).do(self.run_full)
        
        print("\n按 Ctrl+C 停止")
        
        while True:
            schedule.run_pending()
            time.sleep(60)


def print_version():
    """打印版本信息"""
    import akshare
    import pandas
    
    print(f"A-Share Quant v{__version__}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"akshare: {akshare.__version__}")
    print(f"pandas: {pandas.__version__}")
    print(f"System: {platform.system()}")
    print(f"B1 Pattern Match: 支持（基于双线+量比+形态三维匹配，10个历史案例）")


def main():
    parser = argparse.ArgumentParser(
        description='A股量化选股系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py init                          # 首次抓取6年历史数据
  python main.py run                           # 完整流程（更新+选股+通知）
  python main.py run --b1-match                # 完整流程+B1完美图形匹配排序
  python main.py run --b1-match --min-similarity 70  # 匹配+提高相似度阈值到70%
  python main.py run --b1-match --lookback-days 30   # 使用30天回看期
  python main.py web                           # 启动Web界面
  python main.py --version                     # 显示版本信息

分类说明:
  all              - 全部（回落碗中 + 靠近多空线 + 靠近短期趋势线）
  bowl_center      - 回落碗中（优先级最高）
  near_duokong     - 靠近多空线（±duokong_pct%，默认3%）
  near_short_trend - 靠近短期趋势线（±short_pct%，默认2%）

B1完美图形匹配:
  基于10个历史成功案例（双线+量比+形态三维相似度匹配）
  使用 --b1-match 参数启用，--lookback-days 调整回看天数（默认25天）
  使用 --min-similarity 调整匹配阈值（默认60%，范围0-100）
        """
    )

    parser.add_argument(
        '--version',
        action='store_true',
        help='显示版本信息并退出'
    )

    parser.add_argument(
        'command',
        choices=['init', 'run', 'web'],
        nargs='?',
        help='要执行的命令: init(初始化数据), run(执行选股), web(启动Web服务器)'
    )

    parser.add_argument(
        '--max-stocks',
        type=int,
        default=None,
        help='限制处理的股票数量（用于快速测试）'
    )

    parser.add_argument(
        '--config',
        default='config/config.yaml',
        help='配置文件路径'
    )

    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Web服务器监听地址 (默认: 0.0.0.0)'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='Web服务器端口 (默认: 5000)'
    )
    
    parser.add_argument(
        '--category',
        type=str,
        choices=['all', 'bowl_center', 'near_duokong', 'near_short_trend'],
        default='all',
        help='筛选股票分类: all(全部), bowl_center(回落碗中), near_duokong(靠近多空线), near_short_trend(靠近短期趋势线)'
    )
    
    # 从配置读取B1PatternMatch默认值
    try:
        from strategy.pattern_config import MIN_SIMILARITY_SCORE, DEFAULT_LOOKBACK_DAYS
        default_min_similarity = MIN_SIMILARITY_SCORE
        default_lookback_days = DEFAULT_LOOKBACK_DAYS
    except:
        default_min_similarity = 60.0
        default_lookback_days = 25
    
    parser.add_argument(
        '--min-similarity',
        type=float,
        default=None,
        help=f'B1完美图形匹配的最小相似度阈值 (默认: {default_min_similarity})'
    )
    
    parser.add_argument(
        '--b1-match',
        action='store_true',
        help='启用B1完美图形匹配排序（在run命令中使用）'
    )
    
    parser.add_argument(
        '--lookback-days',
        type=int,
        default=None,
        help=f'B1完美图形匹配的回看天数 (默认: {default_lookback_days})'
    )

    args = parser.parse_args()

    # 处理 --version 参数
    if args.version:
        print_version()
        sys.exit(0)

    # 检查命令是否提供
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # 切换工作目录
    os.chdir(project_root)
    
    # 创建系统实例
    quant = QuantSystem(args.config)
    
    # 执行命令
    if args.command == 'init':
        quant.init_data(max_stocks=args.max_stocks)
    
    elif args.command == 'run':
        # 原有选股流程（支持B1完美图形匹配）
        if args.b1_match:
            # 启用B1完美图形匹配
            # 如果命令行未指定，使用配置文件中的默认值
            min_sim = args.min_similarity if args.min_similarity is not None else default_min_similarity
            lookback = args.lookback_days if args.lookback_days is not None else default_lookback_days
            quant.run_with_b1_match(
                category=args.category,
                max_stocks=args.max_stocks,
                min_similarity=min_sim,
                lookback_days=lookback
            )
        else:
            # 原有选股流程（不带B1匹配）
            quant.run_full(category=args.category, max_stocks=args.max_stocks)
    
    elif args.command == 'web':
        # 启动Web服务器
        from web_server import run_web_server
        run_web_server(host=args.host, port=args.port)


if __name__ == '__main__':
    main()
