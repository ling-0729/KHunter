"""
Web 服务器 - A股量化选股系统前端
"""
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
import json
import sys
import math
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import logging
from logging.handlers import RotatingFileHandler
import os
import traceback
from json import JSONEncoder

# 自定义JSON编码器，处理numpy类型
class NumpyEncoder(JSONEncoder):
    """自定义JSON编码器，处理numpy类型"""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.Timestamp):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        return super().default(obj)

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.csv_manager import CSVManager
from strategy.strategy_registry import get_registry
from main import QuantSystem
import threading
from utils.selection_record_manager import SelectionRecordManager
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from stock_analyzer import StockAnalyzer

app = Flask(__name__, 
            template_folder='web/templates',
            static_folder='web/static')

# 配置JSON编码器
app.json_encoder = NumpyEncoder

# 初始化SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ==================== 日志配置 ====================
# 创建日志目录
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# 配置日志处理器
log_file = log_dir / "app.log"
log_format = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 文件处理器（带轮转）
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(log_format)

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_format)

# 配置根日志记录器
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# 获取应用日志记录器
logger = logging.getLogger(__name__)
logger.info("=" * 60)
logger.info("Web服务器启动")
logger.info(f"日志文件: {log_file}")
logger.info("=" * 60)

# 全局实例
csv_manager = CSVManager("data")
registry = get_registry("config/strategy_params.yaml")
quant_system = QuantSystem("config/config.yaml")
selection_record_manager = SelectionRecordManager("data/stock_selection.db")
stock_analyzer = StockAnalyzer()

# 初始化参数锁定机制
from strategy.param_lock import get_param_lock
param_lock = get_param_lock("config/strategy_params.yaml")

# 初始化参数追踪机制
from strategy.param_tracker import get_param_tracker
param_tracker = get_param_tracker("config/strategy_params.yaml")

# 加载策略
logger.info("正在加载策略...")
registry.auto_register_from_directory("strategy")
logger.info(f"已加载 {len(registry.strategies)} 个策略")

# 注册trading蓝图
from trading.routes import trading_bp
app.register_blueprint(trading_bp, url_prefix='/api/trading')
logger.info("已注册trading蓝图")

# 全局更新状态
update_status = {
    'running': False,
    'progress': 0,
    'total': 0,
    'success': 0,
    'failed': 0,
    'message': '',
    'start_time': None,
    'end_time': None
}


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/stocks')
def get_stocks():
    """获取股票列表"""
    try:
        stocks = csv_manager.list_all_stocks()
        
        # 加载股票名称
        names_file = Path("data/stock_names.json")
        stock_names = {}
        if names_file.exists():
            with open(names_file, 'r', encoding='utf-8') as f:
                stock_names = json.load(f)
        
        # 获取每只股票的基本信息 - 支持分页
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 500))  # 默认每页500只
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_stocks = stocks[start_idx:end_idx]
        
        stock_list = []
        for code in paginated_stocks:
            df = csv_manager.read_stock(code)
            if not df.empty:
                latest = df.iloc[0]
                stock_list.append({
                    'code': code,
                    'name': stock_names.get(code, '未知'),
                    'latest_price': round(latest['close'], 2),
                    'latest_date': latest['date'].strftime('%Y-%m-%d'),
                    'market_cap': round(latest.get('market_cap', 0) / 1e8, 2),  # 总市值，单位：亿
                    'data_count': len(df)
                })
        
        return jsonify({
            'success': True, 
            'data': stock_list, 
            'total': len(stocks),
            'page': page,
            'per_page': per_page,
            'total_pages': (len(stocks) + per_page - 1) // per_page
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/stock/<code>')
def get_stock_detail(code):
    """获取单只股票详情"""
    try:
        df = csv_manager.read_stock(code)
        if df.empty:
            return jsonify({'success': False, 'error': '股票不存在'})
        
        # 计算KDJ指标
        from utils.technical import KDJ
        kdj_df = KDJ(df, n=9, m1=3, m2=3)
        
        # 转换为列表格式
        data = []
        for i, (_, row) in enumerate(df.head(100).iterrows()):  # 返回最近100条
            data.append({
                'date': row['date'].strftime('%Y-%m-%d'),
                'open': round(row['open'], 2),
                'high': round(row['high'], 2),
                'low': round(row['low'], 2),
                'close': round(row['close'], 2),
                'volume': int(row['volume']),
                'amount': round(row['amount'] / 1e4, 2),  # 万元
                'turnover': round(row.get('turnover', 0), 2),
                'market_cap': round(row.get('market_cap', 0) / 1e8, 2),  # 总市值，单位：亿
                'K': round(kdj_df.iloc[i]['K'], 2),
                'D': round(kdj_df.iloc[i]['D'], 2),
                'J': round(kdj_df.iloc[i]['J'], 2)
            })
        
        return jsonify({'success': True, 'code': code, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


def analyze_intersection(results):
    """
    分析多策略选股结果的交集。构建股票->策略映射，按交集数量分组
    :param results: 策略选股结果字典 {策略名: [信号列表]}
    :return: 交集分析结果
    """
    try:
        # 获取策略的中文名称映射
        import yaml
        config_file = Path("config/strategy_params.yaml")
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        strategies_config = config.get('strategies', {})
        strategy_display_names = {}
        for strategy_name, strategy_config in strategies_config.items():
            strategy_display_names[strategy_name] = strategy_config.get('display_name', strategy_name)
        
        # 构建股票->策略映射
        stock_strategies = {}
        for strategy_name, signals in results.items():
            # 确保 signals 是列表
            if not isinstance(signals, list):
                logger.warning(f"策略 {strategy_name} 的信号不是列表，跳过")
                continue
            
            for signal in signals:
                # 验证信号结构
                if not isinstance(signal, dict) or 'code' not in signal:
                    logger.warning(f"无效的信号结构: {signal}")
                    continue
                
                code = signal['code']
                if code not in stock_strategies:
                    stock_strategies[code] = {
                        'code': code,
                        'name': signal.get('name', '未知'),
                        'strategies': [],
                        'strategy_display_names': [],  # 存储中文名称
                        'count': 0,
                        'signals': signal.get('signals', [])  # 保存信号信息
                    }
                
                stock_strategies[code]['strategies'].append(strategy_name)
                stock_strategies[code]['strategy_display_names'].append(strategy_display_names.get(strategy_name, strategy_name))
                stock_strategies[code]['count'] += 1
        
        # 按交集数量分组
        by_count = {}
        for code, data in stock_strategies.items():
            count = data['count']
            if count not in by_count:
                by_count[count] = []
            by_count[count].append(data)
        
        # 计算统计信息
        total_strategies = len(results)
        stocks_by_strategy = {name: len(signals) if isinstance(signals, list) else 0 for name, signals in results.items()}
        multi_strategy_count = sum(len(stocks) for count, stocks in by_count.items() if count > 1)
        intersection_rate = (multi_strategy_count / len(stock_strategies)) if stock_strategies else 0
        
        return {
            'total': len(stock_strategies),
            'by_count': by_count,
            'intersection_stats': {
                'total_strategies': total_strategies,
                'stocks_by_strategy': stocks_by_strategy,
                'intersection_rate': round(intersection_rate, 2)
            }
        }
    except Exception as e:
        logger.error(f"交集分析失败: {str(e)}")
        logger.error(f"错误堆栈: {traceback.format_exc()}")
        # 返回空的分析结果而不是抛出异常
        return {
            'total': 0,
            'by_count': {},
            'intersection_stats': {
                'total_strategies': 0,
                'stocks_by_strategy': {},
                'intersection_rate': 0
            }
        }


@app.route('/api/select', methods=['GET', 'POST'])
def run_selection():
    """执行选股 - 支持GET（执行所有策略）和POST（执行指定策略）。POST请求支持OR/AND逻辑：OR（并集）任意策略选中即可；AND（交集）所有策略都选中"""
    import traceback
    
    # 获取日志记录器
    func_logger = logging.getLogger(__name__)
    
    try:
        # 记录请求开始和时间
        request_start_time = datetime.now()
        func_logger.info("=" * 60)
        func_logger.info("选股请求开始")
        
        # 检查参数是否被修改，如果被修改则恢复
        is_modified, restored_params = param_lock.check_and_restore()
        if is_modified:
            func_logger.warning("⚠️  检测到参数被修改，已自动恢复")
            func_logger.warning(f"   恢复的参数: {restored_params}")
        
        # 检查参数是否有变化（用于追踪）
        is_changed, changes = param_tracker.check_changes()
        if is_changed:
            func_logger.warning("⚠️  检测到参数变化")
            for strategy_name, param_changes in changes.items():
                for param_name, change in param_changes.items():
                    func_logger.warning(f"   {strategy_name}.{param_name}: {change['old']} -> {change['new']}")
        
        strategies_to_run = None
        logic = 'or'
        
        # 解析请求参数
        if request.method == 'POST':
            try:
                data = request.json or {}
                strategies_to_run = data.get('strategies')
                logic = data.get('logic', 'or')
                func_logger.info(f"请求参数 - 策略: {strategies_to_run}, 逻辑: {logic}")
            except Exception as e:
                func_logger.error(f"解析请求参数失败: {str(e)}")
                return jsonify({'success': False, 'error': f'请求参数解析失败: {str(e)}'})
            
            # 检查策略列表是否为空
            if strategies_to_run is not None and len(strategies_to_run) == 0:
                func_logger.info("策略列表为空，返回空结果")
                return jsonify({'success': True, 'data': {}, 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        
        # 加载股票数据
        try:
            func_logger.info("开始加载股票数据...")
            stock_codes = csv_manager.list_all_stocks()
            func_logger.info(f"加载了 {len(stock_codes)} 只股票代码")
            
            # 加载股票名称
            names_file = Path("data/stock_names.json")
            stock_names = {}
            if names_file.exists():
                with open(names_file, 'r', encoding='utf-8') as f:
                    stock_names = json.load(f)
            func_logger.info(f"加载了 {len(stock_names)} 只股票名称")
        except Exception as e:
            func_logger.error(f"加载股票数据失败: {str(e)}")
            return jsonify({'success': False, 'error': f'加载股票数据失败: {str(e)}'})
        
        # 构建股票数据字典
        try:
            func_logger.info("构建股票数据字典...")
            stock_data = {}
            skip_count = 0
            load_start_time = datetime.now()
            
            for idx, code in enumerate(stock_codes):
                try:
                    df = csv_manager.read_stock(code)
                    if not df.empty and len(df) >= 60:
                        # 从stock_names中提取股票名称（处理字典结构）
                        stock_name_info = stock_names.get(code, '未知')
                        if isinstance(stock_name_info, dict):
                            stock_name = stock_name_info.get('name', '未知')
                        else:
                            stock_name = stock_name_info
                        stock_data[code] = (stock_name, df)
                except Exception as e:
                    # 跳过无法读取的股票
                    skip_count += 1
                    if skip_count <= 5:  # 只记录前5个错误
                        func_logger.debug(f"无法读取股票 {code}: {str(e)}")
                
                # 每加载500只股票输出一次进度
                if (idx + 1) % 500 == 0:
                    elapsed = (datetime.now() - load_start_time).total_seconds()
                    func_logger.info(f"  加载进度: [{idx + 1}/{len(stock_codes)}] 已加载 {len(stock_data)} 只，耗时 {elapsed:.1f}秒")
            
            load_time = (datetime.now() - load_start_time).total_seconds()
            func_logger.info(f"成功加载 {len(stock_data)} 只股票的K线数据，跳过 {skip_count} 只，总耗时 {load_time:.1f}秒")
        except Exception as e:
            func_logger.error(f"构建股票数据字典失败: {str(e)}")
            return jsonify({'success': False, 'error': f'构建股票数据字典失败: {str(e)}'})
        
        # 检查是否有可用的股票数据
        if not stock_data:
            func_logger.warning("没有可用的股票数据")
            return jsonify({'success': True, 'data': {}, 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        
        results = {}
        
        # AND逻辑：找出被所有选中策略都选中的股票
        if logic == 'and' and strategies_to_run and len(strategies_to_run) > 1:
            try:
                func_logger.info(f"执行AND逻辑，策略数: {len(strategies_to_run)}")
                func_logger.info(f"选中策略列表: {strategies_to_run}")
                all_signals = {}
                
                strategy_idx = 0
                for strategy_name, strategy in registry.strategies.items():
                    if strategy_name not in strategies_to_run:
                        continue
                    
                    strategy_idx += 1
                    func_logger.info(f"[{strategy_idx}/{len(strategies_to_run)}] 开始执行策略: {strategy_name}")
                    signals = []
                    error_count = 0
                    success_count = 0
                    strategy_start_time = datetime.now()
                    last_progress_time = datetime.now()
                    
                    total_stocks = len(stock_data)
                    for idx, (code, (name, df)) in enumerate(stock_data.items()):
                        try:
                            result = strategy.analyze_stock(code, name, df)
                            if result:
                                success_count += 1
                                # 从stock_names中提取股票名称（处理字典结构）
                                stock_name_info = stock_names.get(code, '未知')
                                if isinstance(stock_name_info, dict):
                                    fallback_name = stock_name_info.get('name', '未知')
                                else:
                                    fallback_name = stock_name_info
                                signals.append({
                                    'code': result['code'],
                                    'name': result.get('name', fallback_name),
                                    'signals': result['signals']
                                })
                        except Exception as e:
                            # 跳过分析失败的股票
                            error_count += 1
                            if error_count <= 5:  # 只记录前5个错误
                                func_logger.warning(f"策略 {strategy_name} 分析股票 {code} 失败: {str(e)}")
                        
                        # 每500只股票输出一次进度
                        if (idx + 1) % 500 == 0:
                            elapsed = (datetime.now() - last_progress_time).total_seconds()
                            progress = (idx + 1) / total_stocks * 100
                            func_logger.info(f"  策略 {strategy_name} 进度: [{idx + 1}/{total_stocks}] {progress:.1f}% - 选中 {len(signals)} 只，耗时 {elapsed:.1f}秒")
                            last_progress_time = datetime.now()
                    
                    strategy_time = (datetime.now() - strategy_start_time).total_seconds()
                    func_logger.info(f"策略 {strategy_name} 执行完成: 选中 {len(signals)} 只股票，分析成功 {success_count} 只，失败 {error_count} 只，耗时 {strategy_time:.1f}秒")
                    
                    results[strategy_name] = signals
                    
                    # 计算交集
                    if not all_signals:
                        all_signals = {s['code']: s for s in signals}
                        func_logger.info(f"第一个策略完成，当前交集数量: {len(all_signals)}")
                    else:
                        prev_count = len(all_signals)
                        all_signals = {code: s for code, s in all_signals.items() if any(sig['code'] == code for sig in signals)}
                        func_logger.info(f"交集计算完成: {prev_count} -> {len(all_signals)}")
                
                # 返回交集结果
                intersection_result = list(all_signals.values())
                results = {'_intersection': intersection_result}
                func_logger.info(f"AND逻辑执行完成，最终交集结果: {len(intersection_result)} 只股票")
            except Exception as e:
                func_logger.error(f"AND逻辑执行失败: {str(e)}")
                func_logger.error(f"错误堆栈: {traceback.format_exc()}")
                return jsonify({'success': False, 'error': f'AND逻辑执行失败: {str(e)}'})
        else:
            # OR逻辑（默认）：分别执行每个策略
            try:
                # 加载策略的中文名称映射
                import yaml
                config_file = Path("config/strategy_params.yaml")
                strategy_display_names = {}
                if config_file.exists():
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f) or {}
                    strategies_config = config.get('strategies', {})
                    for strategy_name, strategy_config in strategies_config.items():
                        strategy_display_names[strategy_name] = strategy_config.get('display_name', strategy_name)
                
                func_logger.info(f"执行OR逻辑，策略数: {len(registry.strategies)}")
                
                for strategy_name, strategy in registry.strategies.items():
                    if strategies_to_run and strategy_name not in strategies_to_run:
                        continue
                    
                    func_logger.info(f"执行策略: {strategy_name}")
                    signals = []
                    error_count = 0
                    strategy_start_time = datetime.now()
                    
                    # 获取该策略的中文名称
                    strategy_display_name = strategy_display_names.get(strategy_name, strategy_name)
                    
                    for idx, (code, (name, df)) in enumerate(stock_data.items()):
                        try:
                            result = strategy.analyze_stock(code, name, df)
                            if result:
                                # 从stock_names中提取股票名称（处理字典结构）
                                stock_name_info = stock_names.get(code, '未知')
                                if isinstance(stock_name_info, dict):
                                    fallback_name = stock_name_info.get('name', '未知')
                                else:
                                    fallback_name = stock_name_info
                                signals.append({
                                    'code': result['code'],
                                    'name': result.get('name', fallback_name),
                                    'signals': result['signals'],
                                    'strategy_display_name': strategy_display_name  # 添加中文名称
                                })
                        except Exception as e:
                            # 跳过分析失败的股票
                            error_count += 1
                            if error_count <= 3:  # 只记录前3个错误
                                func_logger.debug(f"策略 {strategy_name} 分析股票 {code} 失败: {str(e)}")
                        
                        # 每处理100只股票输出一次进度
                        if (idx + 1) % 100 == 0:
                            elapsed = (datetime.now() - strategy_start_time).total_seconds()
                            func_logger.info(f"    {strategy_display_name} 进度: [{idx + 1}/{len(stock_data)}] 已选中 {len(signals)} 只，耗时 {elapsed:.1f}秒")
                    
                    strategy_time = (datetime.now() - strategy_start_time).total_seconds()
                    results[strategy_name] = signals
                    func_logger.info(f"策略 {strategy_name} 完成 - 选中 {len(signals)} 只股票，分析失败 {error_count} 只，总耗时 {strategy_time:.1f}秒")
                
                # 计算交集分析（仅当有多个策略且都有结果时）
                if len(results) > 1:
                    # 检查是否有任何策略有结果
                    has_results = any(len(signals) > 0 for signals in results.values())
                    func_logger.info(f"多策略结果 - 总策略数: {len(results)}, 有结果: {has_results}")
                    
                    if has_results:
                        try:
                            func_logger.info("计算交集分析...")
                            intersection_analysis = analyze_intersection(results)
                            results['_intersection_analysis'] = intersection_analysis
                            func_logger.info(f"交集分析完成 - 总股票数: {intersection_analysis.get('total', 0)}")
                        except Exception as e:
                            func_logger.error(f"交集分析计算失败: {str(e)}")
                            func_logger.error(f"错误堆栈: {traceback.format_exc()}")
                            # 不返回错误，继续返回结果
            except Exception as e:
                func_logger.error(f"OR逻辑执行失败: {str(e)}")
                func_logger.error(f"错误堆栈: {traceback.format_exc()}")
                return jsonify({'success': False, 'error': f'OR逻辑执行失败: {str(e)}'})
        
        # 返回结果
        total_time = (datetime.now() - request_start_time).total_seconds()
        func_logger.info(f"选股完成 - 返回结果数: {len(results)}，总耗时 {total_time:.1f}秒")
        func_logger.info("=" * 60)
        
        # 用腾讯财经实时价格替换选股结果中的close字段
        try:
            from utils.akshare_fetcher import AKShareFetcher
            fetcher = AKShareFetcher()
            # 收集所有选中股票的代码
            all_codes = set()
            for key, signals in results.items():
                if isinstance(signals, list):
                    for s in signals:
                        if isinstance(s, dict) and 'code' in s:
                            all_codes.add(s['code'])
            
            if all_codes:
                # 批量获取实时价格
                realtime_prices = fetcher.get_stock_prices_batch(list(all_codes))
                func_logger.info(f"获取实时价格: 请求{len(all_codes)}只, 成功{len(realtime_prices)}只")
                
                # 替换signals中的close字段为实时价格
                for key, signals in results.items():
                    if isinstance(signals, list):
                        for item in signals:
                            if not isinstance(item, dict):
                                continue
                            code = item.get('code', '')
                            price = realtime_prices.get(code)
                            if price is None:
                                continue
                            # 替换嵌套signals列表中的close
                            if 'signals' in item and isinstance(item['signals'], list):
                                for sig in item['signals']:
                                    if isinstance(sig, dict) and 'close' in sig:
                                        sig['close'] = round(price, 2)
        except Exception as e:
            func_logger.warning(f"获取实时价格失败，使用CSV收盘价: {str(e)}")
        
        # 不再自动保存选股结果，由前端手动触发保存
        return jsonify({
            'success': True,
            'data': results,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    
    except Exception as e:
        # 捕获所有未预期的异常
        func_logger = logging.getLogger(__name__)
        error_msg = str(e)
        func_logger.error("=" * 60)
        func_logger.error(f"选股执行失败（未预期的异常）: {error_msg}")
        func_logger.error(f"错误堆栈: {traceback.format_exc()}")
        func_logger.error("=" * 60)
        
        return jsonify({
            'success': False,
            'error': f'选股执行失败: {error_msg}'
        })


@app.route('/api/save_selection', methods=['POST'])
def save_selection():
    """手动保存选股结果到数据库"""
    func_logger = logging.getLogger(__name__)
    try:
        data = request.json or {}
        # 从前端接收选股结果数据
        results = data.get('results', {})
        selection_time_str = data.get('time', '')

        # 解析选股时间
        try:
            selection_time = datetime.strptime(selection_time_str, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            selection_time = datetime.now()

        # 收集所有选股信号和策略名称
        all_signals = []
        strategy_names = []
        for strategy_name, signals in results.items():
            # 跳过特殊字段（如_intersection_analysis）
            if strategy_name.startswith('_'):
                continue
            strategy_names.append(strategy_name)
            all_signals.extend(signals)

        # 检查是否有数据可保存
        if not all_signals or not strategy_names:
            return jsonify({'success': False, 'error': '没有可保存的选股结果'})

        # 调用保存方法
        save_result = selection_record_manager.save_selection_result(
            strategy_names=strategy_names,
            signals=all_signals,
            selection_time=selection_time
        )
        func_logger.info(f"手动保存选股结果 - {save_result}")
        return jsonify(save_result)

    except Exception as e:
        func_logger.error(f"手动保存选股结果失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>')
def get_strategy_detail(name):
    """获取策略详情 - 包含参数详细信息"""
    try:
        # 从YAML文件直接读取原始参数，而不是转换后的参数
        import yaml
        config_file = Path("config/strategy_params.yaml")
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 获取策略配置
        strategy_config = config.get('strategies', {}).get(name, {})
        
        if not strategy_config:
            return jsonify({'success': False, 'error': '策略不存在'})
        
        # 获取策略对象用于获取元数据
        strategy = registry.get_strategy(name)
        metadata = getattr(strategy, 'metadata', {}) if strategy else {}
        
        # 从YAML中获取原始参数值（不经过转换）
        original_params = strategy_config.get('params', {})
        
        # 构建详情数据
        detail = {
            'name': name,
            'display_name': metadata.get('display_name', name),
            'description': metadata.get('description', ''),
            'icon': metadata.get('icon', ''),
            'color': metadata.get('color', '#2563eb'),
            'param_groups': strategy_config.get('param_groups', []),
            'param_details': strategy_config.get('param_details', {}),
            'current_params': original_params  # 使用原始参数，不是转换后的
        }
        
        return jsonify({'success': True, 'data': detail})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies')
def get_strategies():
    """获取策略列表 - 包含中文名称和元数据，按照strategy_order.yaml中定义的顺序排列"""
    try:
        # 从YAML文件直接读取原始参数，而不是转换后的参数
        import yaml
        config_file = Path("config/strategy_params.yaml")
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 构建策略列表
        strategies = []
        strategies_config = config.get('strategies', {})
        
        # 使用registry中的排序信息（从strategy_order.yaml加载）
        # 按照排序顺序获取策略名称
        sorted_strategy_names = registry.list_strategies()
        
        # 按照排序顺序遍历策略
        for name in sorted_strategy_names:
            if name not in registry.strategies:
                continue
            
            # 从YAML中获取策略配置
            strategy_config = strategies_config.get(name, {})
            
            # 获取策略对象用于获取元数据
            strategy = registry.strategies.get(name)
            metadata = getattr(strategy, 'metadata', {}) if strategy else {}
            
            # 从YAML中获取原始参数值（不经过转换）
            original_params = strategy_config.get('params', {})
            
            strategies.append({
                'name': name,
                'display_name': metadata.get('display_name', name),
                'description': metadata.get('description', ''),
                'icon': metadata.get('icon', ''),
                'color': metadata.get('color', '#2563eb'),
                'params': original_params  # 使用原始参数，不是转换后的
            })
        
        return jsonify({'success': True, 'data': strategies})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/validate', methods=['POST'])
def validate_strategy_params(name):
    """验证策略参数 - 检查策略是否存在"""
    try:
        # 检查策略是否存在
        strategy = registry.strategies.get(name)
        
        if not strategy:
            return jsonify({'success': False, 'error': '策略不存在'})
        
        # 获取待验证的参数
        params = request.get_json() or {}
        
        # 在新架构中，只需检查策略存在即可
        # 参数验证由前端或策略类自身处理
        return jsonify({'success': True, 'message': '参数验证通过'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/params', methods=['POST'])
def save_strategy_params(name):
    """
    保存策略参数 - 更新策略的参数配置并持久化到文件
    只更新前端发送的参数，保留其他参数不变
    :param name: 策略名称
    :return: JSON响应
    """
    global registry
    
    try:
        # 检查策略是否存在
        if name not in registry.strategies:
            return jsonify({'success': False, 'error': '策略不存在'})
        
        # 获取待保存的参数
        params = request.get_json() or {}
        strategy = registry.strategies[name]
        
        # 将参数保存到配置文件
        import yaml
        config_path = Path("config/strategy_params.yaml")
        
        # 读取现有配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 确保 strategies 字段存在
        if 'strategies' not in config:
            config['strategies'] = {}
        
        # 确保该策略的配置存在
        if name not in config['strategies']:
            config['strategies'][name] = {}
        
        # 确保 params 字段存在
        if 'params' not in config['strategies'][name]:
            config['strategies'][name]['params'] = {}
        
        # 获取该策略的现有参数
        existing_params = config['strategies'][name]['params']
        
        # 只更新前端发送的参数，保留其他参数
        for param_name, param_value in params.items():
            # 获取原参数的类型进行转换
            if param_name in existing_params:
                param_type = type(existing_params[param_name])
            else:
                # 如果参数不存在，尝试从策略对象获取类型
                if param_name in strategy.params:
                    param_type = type(strategy.params[param_name])
                else:
                    param_type = type(param_value)
            
            try:
                if param_type == int:
                    existing_params[param_name] = int(param_value)
                elif param_type == float:
                    existing_params[param_name] = float(param_value)
                else:
                    existing_params[param_name] = param_value
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': f'参数{param_name}类型转换失败'})
        
        # 写回配置文件
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        
        # 记录参数保存
        func_logger = logging.getLogger(__name__)
        func_logger.info(f"参数已保存: {name}")
        func_logger.info(f"保存的参数: {params}")
        
        # 重新加载策略参数 - 使用global声明确保更新全局registry
        registry = get_registry("config/strategy_params.yaml")
        registry.auto_register_from_directory("strategy")
        
        return jsonify({'success': True, 'message': '参数保存成功'})
    except Exception as e:
        import traceback
        func_logger = logging.getLogger(__name__)
        func_logger.error(f"保存策略参数失败: {str(e)}")
        func_logger.error(f"错误堆栈: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/stats')
def get_stats():
    """获取系统统计信息"""
    try:
        stocks = csv_manager.list_all_stocks()
        
        # 计算数据日期范围
        dates = []
        for code in stocks[:50]:  # 采样
            df = csv_manager.read_stock(code)
            if not df.empty:
                dates.append(df.iloc[0]['date'])
        
        latest_date = max(dates).strftime('%Y-%m-%d') if dates else '-'
        
        return jsonify({
            'success': True,
            'data': {
                'total_stocks': len(stocks),
                'latest_date': latest_date,
                'strategies': len(registry.strategies)
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/config', methods=['GET'])
def get_config():
    """获取配置"""
    try:
        config_file = Path("config/strategy_params.yaml")
        if config_file.exists():
            import yaml
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return jsonify({'success': True, 'data': config})
        return jsonify({'success': False, 'error': '配置文件不存在'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/config', methods=['POST'])
def update_config():
    """
    更新配置 - 只更新指定的参数，保留其他参数
    """
    try:
        import yaml
        from pathlib import Path
        
        # 获取前端发送的配置更新
        update_data = request.json or {}
        
        # 读取现有配置
        config_file = Path("config/strategy_params.yaml")
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 确保 strategies 字段存在
        if 'strategies' not in config:
            config['strategies'] = {}
        
        # 更新指定策略的参数
        # update_data 格式: {strategy_name: {param_name: value, ...}, ...}
        for strategy_name, params_update in update_data.items():
            if strategy_name not in config['strategies']:
                config['strategies'][strategy_name] = {}
            
            # 获取该策略的现有配置
            strategy_config = config['strategies'][strategy_name]
            
            # 确保 params 字段存在
            if 'params' not in strategy_config:
                strategy_config['params'] = {}
            
            # 只更新指定的参数，保留其他参数
            for param_name, param_value in params_update.items():
                strategy_config['params'][param_name] = param_value
        
        # 写回配置文件
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        
        # 记录配置更新
        func_logger = logging.getLogger(__name__)
        func_logger.info(f"配置已更新")
        func_logger.info(f"更新的数据: {update_data}")
        
        # 重新加载策略
        global registry
        registry = get_registry("config/strategy_params.yaml")
        registry.auto_register_from_directory("strategy")
        
        return jsonify({'success': True, 'message': '配置更新成功'})
    except Exception as e:
        import traceback
        func_logger = logging.getLogger(__name__)
        func_logger.error(f"更新配置失败: {str(e)}")
        func_logger.error(f"错误堆栈: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)})


def emit_update_progress():
    """通过WebSocket发送更新进度"""
    socketio.emit('update_progress', {
        'running': update_status['running'],
        'progress': update_status['progress'],
        'total': update_status['total'],
        'success': update_status['success'],
        'failed': update_status['failed'],
        'message': update_status['message'],
        'start_time': update_status['start_time'],
        'end_time': update_status['end_time']
    }, namespace='/')


@app.route('/api/update', methods=['POST'])
def trigger_update():
    """触发数据更新"""
    global update_status
    
    # 检查是否已有更新在运行
    if update_status['running']:
        return jsonify({'success': False, 'error': '已有更新任务在运行中'})
    
    # 获取参数
    max_stocks = request.json.get('max_stocks') if request.json else None
    
    # 在后台线程中执行更新
    def update_thread():
        global update_status
        try:
            update_status['running'] = True
            update_status['start_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            update_status['message'] = '正在更新数据...'
            emit_update_progress()
            
            # 执行更新
            quant_system.update_data(max_stocks=max_stocks)
            
            update_status['success'] += 1
            update_status['message'] = '数据更新完成'
            update_status['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            emit_update_progress()
        except Exception as e:
            update_status['failed'] += 1
            update_status['message'] = f'更新失败: {str(e)}'
            update_status['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            emit_update_progress()
        finally:
            update_status['running'] = False
            emit_update_progress()
    
    # 启动后台线程
    thread = threading.Thread(target=update_thread, daemon=True)
    thread.start()
    
    return jsonify({
        'success': True,
        'message': '数据更新已启动',
        'status': update_status
    })


@app.route('/api/update/status', methods=['GET'])
def get_update_status():
    """获取更新状态"""
    return jsonify({
        'success': True,
        'status': update_status
    })


@app.route('/selection-history')
def selection_history_page():
    """
    选股历史查询页面
    """
    return render_template('selection_history.html')


@app.route('/test-select')
def test_select_page():
    """
    下拉框测试页面
    """
    return render_template('test_select.html')


@app.route('/api/selection-history', methods=['GET'])
def get_selection_history():
    """
    查询选股历史
    
    参数：
        strategy_name: 策略名称（可选）
        start_date: 开始日期 YYYY-MM-DD（可选）
        end_date: 结束日期 YYYY-MM-DD（可选）
        stock_code: 股票代码（可选）
        page: 分页页码，默认1
        limit: 每页数量，默认20
    
    返回：
        {
            'success': True,
            'total': 100,
            'page': 1,
            'limit': 20,
            'data': [...]
        }
    """
    try:
        # 获取查询参数
        strategy_name = request.args.get('strategy_name', '')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        stock_code = request.args.get('stock_code', '')
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        
        # 构建筛选条件
        filters = {}
        if strategy_name:
            filters['strategy_name'] = strategy_name
        if start_date:
            filters['start_date'] = start_date
        if end_date:
            filters['end_date'] = end_date
        if stock_code:
            filters['stock_code'] = stock_code
        
        # 查询选股历史
        result = selection_record_manager.get_selection_history(
            filters=filters,
            page=page,
            limit=limit
        )
        
        # 转换 numpy 类型为 Python 原生类型
        if result.get('success') and result.get('data'):
            for record in result['data']:
                for key, value in record.items():
                    # 将 numpy 类型转换为 Python 原生类型
                    if hasattr(value, 'item'):
                        record[key] = value.item()
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"查询选股历史失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })


# ==================== 股票分析相关路由 ====================




@app.route('/api/analyze-stock', methods=['POST'])
def analyze_stock():
    """
    分析股票
    
    参数：
        stock_code: 股票代码
        period: 分析周期
    
    返回：
        {
            'success': True,
            'data': 分析结果
        }
    """
    try:
        # 获取请求参数
        data = request.json or {}
        stock_code = data.get('stock_code', '')
        period = data.get('period', '30d')
        
        if not stock_code:
            return jsonify({'success': False, 'message': '股票代码不能为空'})
        
        # 分析股票
        analysis_result = stock_analyzer.analyze(stock_code, period=period)
        
        if not analysis_result:
            return jsonify({'success': False, 'message': '分析失败'})
        
        # 转换numpy类型为Python原生类型，同时清理NaN/Infinity
        def convert_numpy_types(obj):
            """递归转换numpy类型，将NaN/Infinity替换为None"""
            if isinstance(obj, dict):
                return {k: convert_numpy_types(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy_types(item) for item in obj]
            # 先检查float类型的NaN/Infinity（含numpy.floating）
            elif isinstance(obj, float):
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return obj
            elif hasattr(obj, 'item'):
                # numpy标量类型，先转为Python原生类型再检查NaN
                val = obj.item()
                if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                    return None
                return val
            elif isinstance(obj, np.ndarray):
                return convert_numpy_types(obj.tolist())
            elif isinstance(obj, pd.Timestamp):
                return obj.strftime('%Y-%m-%d %H:%M:%S')
            # 使用hasattr检查其他numpy类型
            elif hasattr(obj, 'dtype'):
                val = obj.item()
                if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                    return None
                return val
            else:
                return obj
        
        # 转换分析结果
        analysis_result = convert_numpy_types(analysis_result)
        
        # 使用json.dumps并指定default参数来处理所有numpy类型
        import json
        def default_handler(obj):
            """处理json.dumps无法序列化的类型"""
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                # 检查NaN/Infinity
                val = float(obj)
                if math.isnan(val) or math.isinf(val):
                    return None
                return val
            elif isinstance(obj, np.ndarray):
                return convert_numpy_types(obj.tolist())
            elif isinstance(obj, pd.Timestamp):
                return obj.strftime('%Y-%m-%d %H:%M:%S')
            else:
                return obj
        
        response_data = {
            'success': True,
            'data': analysis_result
        }
        json_str = json.dumps(response_data, default=default_handler)
        return app.response_class(
            response=json_str,
            mimetype='application/json'
        )
        
    except Exception as e:
        logger.error(f"分析股票失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/analysis-history')
def get_analysis_history():
    """
    获取分析历史
    
    返回：
        {
            'success': True,
            'data': 分析历史列表
        }
    """
    try:
        # 这里简化处理，实际应该从数据库获取
        # 暂时返回模拟数据
        history = [
            {
                'id': 1,
                'stock_code': '600519',
                'stock_name': '贵州茅台',
                'analysis_time': '2026-03-23 10:00:00',
                'rating': '买入'
            },
            {
                'id': 2,
                'stock_code': '000858',
                'stock_name': '五粮液',
                'analysis_time': '2026-03-22 15:30:00',
                'rating': '中性'
            }
        ]
        
        return jsonify({
            'success': True,
            'data': history
        })
        
    except Exception as e:
        logger.error(f"获取分析历史失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/export-report')
def export_report():
    """
    导出分析报告
    
    参数：
        stock_code: 股票代码
    
    返回：
        报告文件
    """
    try:
        stock_code = request.args.get('stock_code', '')
        
        if not stock_code:
            return jsonify({'success': False, 'message': '股票代码不能为空'})
        
        # 生成报告
        report_content, report_path = stock_analyzer.generate_report(stock_code)
        
        # 返回报告文件
        return send_from_directory(
            directory=str(Path(report_path).parent),
            path=Path(report_path).name,
            as_attachment=True
        )
        
    except Exception as e:
        logger.error(f"导出报告失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/report/<int:report_id>')
def get_report(report_id):
    """
    获取分析报告
    
    参数：
        report_id: 报告ID
    
    返回：
        报告内容
    """
    try:
        # 这里简化处理，实际应该根据ID获取报告
        # 暂时返回模拟数据
        return jsonify({
            'success': True,
            'message': '报告获取功能暂未实现'
        })
        
    except Exception as e:
        logger.error(f"获取报告失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })


def run_web_server(host='0.0.0.0', port=5000, debug=False):
    """启动Web服务器"""
    print(f"🌐 启动Web服务器: http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_web_server(debug=False)
