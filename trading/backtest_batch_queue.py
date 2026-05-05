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
        """初始化进度文件"""
        progress = {
            'batch_id': self.batch_id,
            'status': 'pending',
            'total_tasks': len(self._data.get('tasks', [])),
            'completed_tasks': 0,
            'failed_tasks': 0,
            'current_task': None,
            'task_results': []
        }
        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(self._deep_serialize(progress), f, ensure_ascii=False, indent=2)

    def _update_progress(self):
        """更新进度文件"""
        tasks = self._data.get('tasks', [])
        completed = sum(1 for t in tasks if t.get('status') == 'completed')
        failed = sum(1 for t in tasks if t.get('status') == 'failed')

        current_task = None
        if self._data.get('current_index', -1) >= 0 and self._data['current_index'] < len(tasks):
            task = tasks[self._data['current_index']]
            current_task = {
                'index': self._data['current_index'],
                'strategy_name': task.get('strategy_name'),
                'status': task.get('status')
            }

        progress = {
            'batch_id': self.batch_id,
            'status': self._data.get('status', 'pending'),
            'total_tasks': len(tasks),
            'completed_tasks': completed,
            'failed_tasks': failed,
            'current_task': current_task,
            'task_results': [
                {
                    'task_id': i + 1,
                    'strategy_name': t.get('strategy_name'),
                    'status': t.get('status'),
                    'result': t.get('result'),
                    'error': t.get('error')
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
                self._save_queue()
                self._update_progress()

                logger.info(f"执行任务 {i + 1}/{len(tasks)}: {task.get('strategy_name')}")

                try:
                    result = self._execute_single_task(task)
                    task['status'] = 'completed'
                    task['result'] = result
                    task['completed_at'] = datetime.now().isoformat()
                    logger.info(f"任务 {i + 1} 完成: {task.get('strategy_name')}")
                except Exception as e:
                    task['status'] = 'failed'
                    task['error'] = str(e)
                    task['completed_at'] = datetime.now().isoformat()
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

        config = self._data.get('config', {}).copy()
        config.update({
            'timing_strategy': timing_strategy,
            'support_level_method': support_level_method,
            'start_date': start_date,
            'end_date': end_date
        })

        # 从配置文件读取海龟策略参数
        if timing_strategy == 'turtle':
            try:
                config_manager = StrategyConfigManager()
                turtle_config = config_manager.get_strategy_config('TurtleStrategy')
                turtle_params = turtle_config.get('params', {})
                # 将海龟参数添加到config中，供backtest_engine使用
                config.update({
                    'n_entry': turtle_params.get('n_entry'),
                    'n_exit': turtle_params.get('n_exit'),
                    'atr_period': turtle_params.get('atr_period'),
                    'entry_atr': turtle_params.get('entry_atr'),
                    'add_atr': turtle_params.get('add_atr'),
                    'exit_atr': turtle_params.get('exit_atr'),
                    'preset': turtle_params.get('preset'),
                    'base_position_amount': turtle_params.get('base_position_amount')
                })
                logger.info(f"批量回测从配置文件读取海龟策略参数: n_entry={turtle_params.get('n_entry')}, "
                           f"n_exit={turtle_params.get('n_exit')}, atr_period={turtle_params.get('atr_period')}")
            except Exception as e:
                logger.warning(f"批量回测读取海龟策略配置失败，使用默认参数: {str(e)}")

        engine = BacktestEngine(db_path="data/stock_selection.db")
        result = engine.run_backtest(strategy_name, config)

        # 保存结果到数据库
        try:
            backtest_dao = BacktestDAO(db_path="data/stock_selection.db")

            # 计算final_capital
            final_capital = config.get('initial_capital', 300000)
            if 'capital_history' in result and result['capital_history']:
                final_capital = result['capital_history'][-1]

            # 构建保存到数据库的结果格式
            save_result = {
                'strategy_name': strategy_name,
                'support_level_method': support_level_method,
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
                'initial_capital': config.get('initial_capital', 300000),
                'final_capital': final_capital
            }

            # 检查是否已存在相同参数的回测结果
            existing_result = backtest_dao.get_result_by_strategy_and_dates(
                strategy_name, start_date, end_date
            )

            if existing_result:
                result_id = existing_result['id']
                backtest_dao.update_result(result_id, save_result)
                backtest_dao.delete_trades(result_id)
                backtest_dao.delete_equity_curve(result_id)
                logger.info(f"批量回测更新已存在的回测结果，result_id: {result_id}")
            else:
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
        if self.progress_file.exists():
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)

        return {
            'batch_id': self.batch_id,
            'status': self._data.get('status', 'unknown'),
            'total_tasks': len(self._data.get('tasks', [])),
            'completed_tasks': 0,
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
