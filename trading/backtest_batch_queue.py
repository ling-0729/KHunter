"""
批量回测任务队列管理模块
支持后端任务队列执行，解决浏览器关闭后任务中断的问题
"""
import json
import os
import threading
import uuid
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)

# 数据目录
DATA_DIR = Path("data")
BATCH_QUEUE_DIR = DATA_DIR / "backtest_batch"
BATCH_QUEUE_DIR.mkdir(parents=True, exist_ok=True)


class BacktestBatchQueue:
    """批量回测任务队列管理器"""

    _executors: Dict[str, 'BacktestBatchQueue'] = {}
    _lock = threading.Lock()

    def __init__(self, batch_id: str):
        self.batch_id = batch_id
        self.queue_file = BATCH_QUEUE_DIR / f"queue_{batch_id}.json"
        self.progress_file = BATCH_QUEUE_DIR / f"progress_{batch_id}.json"
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._data: Dict[str, Any] = {}

    @classmethod
    def create_batch(cls, tasks: List[Dict], config: Dict) -> 'BacktestBatchQueue':
        """创建新的批量任务队列

        Args:
            tasks: 任务列表
            config: 通用配置

        Returns:
            BacktestBatchQueue 实例
        """
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        batch_queue = cls(batch_id)

        batch_queue._data = {
            'batch_id': batch_id,
            'created_at': datetime.now().isoformat(),
            'status': 'pending',
            'config': config,
            'tasks': tasks,
            'current_index': -1,
            'started_at': None,
            'completed_at': None
        }

        batch_queue._save_queue()
        batch_queue._init_progress()

        logger.info(f"创建批量任务队列: {batch_id}, 任务数: {len(tasks)}")
        return batch_queue

    @classmethod
    def load_batch(cls, batch_id: str) -> Optional['BacktestBatchQueue']:
        """加载已有的批量任务队列

        Args:
            batch_id: 批量任务 ID

        Returns:
            BacktestBatchQueue 实例或 None
        """
        batch_queue = cls(batch_id)
        if batch_queue.queue_file.exists():
            batch_queue._load_queue()
            return batch_queue
        return None

    @classmethod
    def get_executor(cls, batch_id: str) -> Optional['BacktestBatchQueue']:
        """获取执行器

        Args:
            batch_id: 批量任务 ID

        Returns:
            BacktestBatchQueue 实例或 None
        """
        with cls._lock:
            if batch_id not in cls._executors:
                executor = cls.load_batch(batch_id)
                if executor is None:
                    return None
                cls._executors[batch_id] = executor
            return cls._executors[batch_id]

    def _deep_serialize(self, obj):
        """深度序列化对象，处理嵌套的 date/datetime 和 numpy 类型"""
        if isinstance(obj, dict):
            return {k: self._deep_serialize(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._deep_serialize(item) for item in obj]
        elif isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        else:
            return obj

    def _save_queue(self):
        """保存队列到文件"""
        data = self._deep_serialize(self._data)
        with open(self.queue_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_queue(self):
        """从文件加载队列"""
        with open(self.queue_file, 'r', encoding='utf-8') as f:
            self._data = json.load(f)

    def _init_progress(self):
        """初始化进度文件

        增加 batch_started_at 字段记录批次启动时间，
        供前端预估整体剩余耗时使用（批次3）
        """
        progress = {
            'batch_id': self.batch_id,
            'status': 'pending',
            'total_tasks': len(self._data.get('tasks', [])),
            'completed_tasks': 0,
            'failed_tasks': 0,
            'batch_started_at': None,  # 批次启动时间，start() 时填入
            'current_task': None,
            'task_results': []
        }
        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(self._deep_serialize(progress), f, ensure_ascii=False, indent=2)

    def _update_progress(self):
        """更新进度文件

        扩展字段（批次3）：
        - 顶层增加 batch_started_at，记录批次启动时间
        - current_task 增加 started_at/done_days/total_days，
          其中 done_days/total_days 实时从 backtest_engine.BACKTEST_PROGRESS 读取
        - task_results 每条增加 started_at/completed_at/total_days，
          供前端计算平均单任务耗时
        """
        # 延迟导入，避免循环依赖
        from trading.backtest_engine import BACKTEST_PROGRESS

        tasks = self._data.get('tasks', [])
        completed = sum(1 for t in tasks if t.get('status') == 'completed')
        failed = sum(1 for t in tasks if t.get('status') == 'failed')

        current_task = None
        if self._data.get('current_index', -1) >= 0 and self._data['current_index'] < len(tasks):
            task = tasks[self._data['current_index']]
            # 读取当前任务在引擎内的实时交易日进度
            bp = BACKTEST_PROGRESS
            current_task = {
                'index': self._data['current_index'],
                'strategy_name': task.get('strategy_name'),
                'status': task.get('status'),
                # 任务开始时间，_execute_loop 中记录
                'started_at': task.get('started_at'),
                # 当前任务已完成的交易日数
                'done_days': bp.get('done_days', 0),
                # 当前任务交易日总数
                'total_days': bp.get('total_days', 0),
                # 当前任务正在回测的交易日
                'current_date': bp.get('current_date'),
                # 引擎内任务启动时间（用于校验）
                'engine_started_at': bp.get('started_at'),
            }

        progress = {
            'batch_id': self.batch_id,
            'status': self._data.get('status', 'pending'),
            'total_tasks': len(tasks),
            'completed_tasks': completed,
            'failed_tasks': failed,
            # 批次启动时间，start() 中写入 self._data['started_at']
            'batch_started_at': self._data.get('started_at'),
            'current_task': current_task,
            'task_results': [
                {
                    'task_id': i + 1,
                    'strategy_name': t.get('strategy_name'),
                    'status': t.get('status'),
                    'result': t.get('result'),
                    'error': t.get('error'),
                    # 任务开始时间（_execute_loop 中写入）
                    'started_at': t.get('started_at'),
                    # 任务完成/失败时间（_execute_loop 中写入）
                    'completed_at': t.get('completed_at'),
                    # 该任务交易日总数（_execute_loop 任务结束时写入）
                    'total_days': t.get('total_days'),
                    # 【2026-09-21】回传任务区间 ✓
                    #   前端结果页签据此区分"同策略、不同区间"的多个任务 ✗
                    #   （此前不回传 ✗ → 唯一键相同 ✗ → 后 3 个结果被当成重复跳过 ✗，只显示 1 个 ✓）
                    #   兜底：任务定义里没有时，从回测结果里取（result 通常带 start_date/end_date ✓）
                    'start_date': t.get('start_date') or (t.get('result') or {}).get('start_date'),
                    'end_date': t.get('end_date') or (t.get('result') or {}).get('end_date'),
                }
                for i, t in enumerate(tasks)
                if t.get('status') in ('completed', 'failed')
            ]
        }

        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(self._deep_serialize(progress), f, ensure_ascii=False, indent=2)

    def start(self):
        """启动后台执行"""
        if self._running:
            logger.warning(f"批量任务 {self.batch_id} 已在执行中")
            return

        if self._data.get('status') in ('running', 'completed'):
            logger.warning(f"批量任务 {self.batch_id} 状态为 {self._data.get('status')}，无法启动")
            return

        self._running = True
        self._data['status'] = 'running'
        self._data['started_at'] = datetime.now().isoformat()
        self._save_queue()

        self._thread = threading.Thread(target=self._execute_loop, daemon=True)
        self._thread.start()

        logger.info(f"批量任务 {self.batch_id} 已启动后台执行")

    def _execute_loop(self):
        """执行循环"""
        try:
            tasks = self._data.get('tasks', [])
            logger.info(f"_execute_loop 开始执行，共 {len(tasks)} 个任务")

            for i, task in enumerate(tasks):
                logger.info(f"_execute_loop 检查任务 {i}, _running={self._running}")
                if not self._running:
                    logger.info(f"批量任务 {self.batch_id} 被中断于任务 {i}")
                    break

                self._data['current_index'] = i
                task['status'] = 'running'
                # 记录任务开始时间，供前端预估剩余耗时使用（批次3）
                task['started_at'] = datetime.now().isoformat()
                self._save_queue()
                self._update_progress()

                logger.info(f"执行任务 {i + 1}/{len(tasks)}: {task.get('strategy_name')}")

                try:
                    result = self._execute_single_task(task)
                    task['status'] = 'completed'
                    task['result'] = result
                    task['completed_at'] = datetime.now().isoformat()
                    # 任务结束后读取引擎内的交易日总数，供后续预估使用
                    try:
                        from trading.backtest_engine import BACKTEST_PROGRESS
                        task['total_days'] = BACKTEST_PROGRESS.get('total_days', 0)
                    except Exception as _e:
                        logger.warning(f"读取任务 {i + 1} total_days 失败: {str(_e)}")
                        task['total_days'] = task.get('total_days', 0)
                    logger.info(f"任务 {i + 1} 完成: {task.get('strategy_name')}")
                except Exception as e:
                    task['status'] = 'failed'
                    task['error'] = str(e)
                    task['completed_at'] = datetime.now().isoformat()
                    # 失败任务也尽量记录交易日总数
                    try:
                        from trading.backtest_engine import BACKTEST_PROGRESS
                        task['total_days'] = BACKTEST_PROGRESS.get('total_days', 0)
                    except Exception as _e:
                        task['total_days'] = task.get('total_days', 0)
                    logger.error(f"任务 {i + 1} 失败: {task.get('strategy_name')}, error: {str(e)}")

                self._save_queue()
                self._update_progress()

            if self._running:
                self._data['status'] = 'completed'
                self._data['completed_at'] = datetime.now().isoformat()
                self._save_queue()
                self._update_progress()
                logger.info(f"批量任务 {self.batch_id} 全部完成")
            else:
                logger.info(f"批量任务 {self.batch_id} 结束时 _running=False")

        except Exception as e:
            logger.error(f"批量任务执行异常: {str(e)}")
            self._data['status'] = 'failed'
            self._save_queue()
            self._update_progress()
        finally:
            logger.info(f"_execute_loop finally 块执行, _running 设置为 False")
            self._running = False

    def _execute_single_task(self, task: Dict) -> Dict:
        """执行单个回测任务

        Args:
            task: 任务配置

        Returns:
            回测结果
        """
        from trading.backtest_engine import BacktestEngine
        from trading.backtest_dao import BacktestDAO
        from utils.strategy_config_manager import StrategyConfigManager

        strategy_name = task.get('strategy_name')
        start_date = task.get('start_date')
        end_date = task.get('end_date')
        timing_strategy = task.get('timing_strategy', 'turtle')
        support_level_method = task.get('support_level_method', 'ma20')
        
        # 记录实际要执行的策略名称，确保日志和实际执行一致
        logger.info(f"_execute_single_task 开始执行: strategy_name={strategy_name}, timing_strategy={timing_strategy}, "
                   f"start_date={start_date}, end_date={end_date}")

        config = self._data.get('config', {}).copy()
        config.update({
            'timing_strategy': timing_strategy,
            'support_level_method': support_level_method,
            'start_date': start_date,
            'end_date': end_date
        })

        # 【2026-09-23 合并】海龟类参数统一走**唯一读取入口** ✓
        #   yaml 只保留一个海龟类配置块（TurtleStrategy.params ✓），海龟与海龟plus 共用 ✓；
        #   低位海龟由该入口返回自身 1/6/12 口径 ✓。
        #   历史坑（已消除）：本处原先手写 turtle / low_turtle 两个分支，
        #   海龟plus 漏注入 ✗ → 批量回测跑代码默认预设，与单次回测/配置不一致 ✗。
        from trading.timing_strategies import (TURTLE_FAMILY_STRATEGIES,
                                               TURTLE_FAMILY_PARAM_KEYS,
                                               load_turtle_family_params)
        if timing_strategy in TURTLE_FAMILY_STRATEGIES:
            try:
                config_manager = StrategyConfigManager()
                params = load_turtle_family_params(timing_strategy, config_manager)
                _tp = dict(config.get('timing_params') or {})
                # 调用方显式传入的同名键优先（不覆盖 ✓）
                params = {**params, **(_tp.get(timing_strategy) or {})}
                _tp[timing_strategy] = params
                config['timing_params'] = _tp
                # 顶层键（引擎/运行器优先读顶层配置 ✓），只写海龟类已知键 ✓
                config.update({k: v for k, v in params.items()
                               if v is not None and k in TURTLE_FAMILY_PARAM_KEYS})
                # 预设特例：顶层键名为 turtle_preset ✓（timing_params 内仍叫 preset ✓）
                if params.get('preset') is not None:
                    config['turtle_preset'] = params['preset']
                logger.info(
                    f"批量回测注入海龟类参数（{timing_strategy}）: n_entry={params.get('n_entry')}, "
                    f"n_exit={params.get('n_exit')}, atr_period={params.get('atr_period')}, "
                    f"preset={params.get('preset')}, lookback_days={params.get('lookback_days')}, "
                    f"max_additions={params.get('max_additions')}")
            except Exception as e:
                logger.warning(f"批量回测读取海龟类策略配置失败，沿用调用方参数: {e}")

        engine = BacktestEngine(db_path="data/stock_selection.db")
        result = engine.run_backtest(strategy_name, config)

        # 保存结果到数据库
        try:
            backtest_dao = BacktestDAO(db_path="data/stock_selection.db")

            # 使用引擎返回的 final_capital（引擎内已确保 capital_history 与其一致）
            final_capital = result.get('final_capital', config.get('initial_capital', 300000))

            # 构建保存到数据库的结果格式
            save_result = {
                'strategy_name': strategy_name,
                'support_level_method': timing_strategy,  # 保存择时策略
                'backtest_name': f"{strategy_name}_{start_date}_{end_date}",
                'start_date': start_date,
                'end_date': end_date,
                'total_trades': result.get('performance', {}).get('total_trades', 0),
                'win_trades': result.get('performance', {}).get('win_trades', 0),
                'loss_trades': result.get('performance', {}).get('loss_trades', 0),
                'win_rate': result.get('performance', {}).get('win_rate', 0),
                'avg_return': result.get('performance', {}).get('avg_return', 0),
                'total_return': result.get('performance', {}).get('total_return', 0),
                'max_return': result.get('performance', {}).get('max_return', 0),
                'min_return': result.get('performance', {}).get('min_return', 0),
                'profit_factor': result.get('performance', {}).get('profit_factor', 0),
                'profit_loss_ratio': result.get('performance', {}).get('profit_loss_ratio', 0),
                'max_drawdown': result.get('performance', {}).get('max_drawdown', 0),
                'sharpe_ratio': result.get('performance', {}).get('sharpe_ratio', 0),
                # 【2026-09-22 修复】同上：补上漏传的 avg_hold_days（否则落库恒为 0 ✗）
                'avg_hold_days': result.get('performance', {}).get('avg_hold_days', 0),
                'initial_capital': config.get('initial_capital', 300000),
                'final_capital': final_capital,
                # ★【2026-10-03 用户要求 ✓】批量回测同样落库**主要参数设置情况** ✓
                #   （与单次回测**同一实现** ✓：`build_param_snapshot` ✓）
                #   ⚠️ 批量尤其需要 ✓ —— 批量常做**参数网格** ✗✓，若无快照
                #     事后根本分不清每一行是用哪组参数跑出来的 ✗。
                'param_snapshot': result.get('param_snapshot'),
                'data_fingerprint': result.get('data_fingerprint'),
                'data_gate': result.get('data_gate'),
            }

            # 直接保存新回测结果，不检查是否已存在
            result_id = backtest_dao.save_result(save_result)
            logger.info(f"批量回测保存新回测结果，result_id: {result_id}")

            # 保存交易记录
            if 'trades' in result and result['trades']:
                trades = result['trades']
                for trade in trades:
                    trade['result_id'] = result_id
                    trade.setdefault('stock_code', '')
                    trade.setdefault('stock_name', '')
                    if not trade.get('selection_date'):
                        trade['selection_date'] = trade.get('buy_date', start_date)
                    trade.setdefault('buy_date', '')
                    trade.setdefault('buy_price', 0)
                    trade.setdefault('sell_date', '')
                    trade.setdefault('sell_price', 0)
                    trade.setdefault('buy_amount', 0)
                    trade.setdefault('sell_amount', 0)
                    trade.setdefault('profit', trade.get('profit_loss', 0))
                    trade.setdefault('profit_rate', trade.get('return_rate', 0))
                    trade.setdefault('trade_type', 'normal')
                backtest_dao.save_trades_batch(trades)
                logger.info(f"批量回测保存交易记录 {len(trades)} 条")

            # 保存收益曲线
            if 'capital_history' in result and 'dates' in result:
                equity_curve = [
                    {'date': date, 'capital': capital}
                    for date, capital in zip(result['dates'], result['capital_history'])
                ]
                backtest_dao.save_equity_curve(result_id, equity_curve)
                logger.info(f"批量回测保存收益曲线 {len(equity_curve)} 条")

            result['db_result_id'] = result_id

        except Exception as e:
            logger.error(f"批量回测保存数据库失败: {str(e)}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")

        return result

    def stop(self):
        """停止执行"""
        self._running = False
        logger.info(f"批量任务 {self.batch_id} 停止请求已提交")

    def get_status(self) -> Dict:
        """获取执行状态

        Returns:
            状态信息
        """
        try:
            if self.progress_file.exists():
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        return json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            logger.debug(f"读取进度文件失败，使用默认状态: {str(e)}")

        return {
            'batch_id': self.batch_id,
            'status': self._data.get('status', 'completed'),
            'total_tasks': len(self._data.get('tasks', [])),
            'completed_tasks': len(self._data.get('tasks', [])),
            'failed_tasks': 0,
            'current_task': None
        }

    def get_results(self) -> Dict:
        """获取执行结果

        Returns:
            执行结果
        """
        try:
            if self.queue_file.exists():
                with open(self.queue_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return {
                        'batch_id': data.get('batch_id'),
                        'status': data.get('status'),
                        'results': [
                            {
                                'task_id': i + 1,
                                'strategy_name': t.get('strategy_name'),
                                'status': t.get('status'),
                                'result': t.get('result'),
                                'error': t.get('error')
                            }
                            for i, t in enumerate(data.get('tasks', []))
                        ]
                    }
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取队列文件失败，使用内存数据: {str(e)}")

        return {
            'batch_id': self.batch_id,
            'status': self._data.get('status'),
            'results': [
                {
                    'task_id': i + 1,
                    'strategy_name': t.get('strategy_name'),
                    'status': t.get('status'),
                    'result': t.get('result'),
                    'error': t.get('error')
                }
                for i, t in enumerate(self._data.get('tasks', []))
            ]
        }

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status(self) -> str:
        return self._data.get('status', 'unknown')
