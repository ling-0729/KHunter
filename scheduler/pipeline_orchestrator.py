# -*- coding: utf-8 -*-
"""
流水线编排器

按顺序执行三步骤流水线：数据更新 → 策略运行 → 飞书通知。
每个步骤独立记录状态和耗时，单个步骤失败不阻断后续步骤。
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from scheduler.models import PipelineResult, StepResult

# 跨平台文件锁：使用原子文件创建 + 目录锁
# POSIX 用 fcntl，Windows 用 os.open O_EXCL 原子创建
if sys.platform == "win32":
    import msvcrt
    _HAS_FCNTL = False
else:
    import fcntl
    _HAS_FCNTL = True

logger = logging.getLogger(__name__)

# 文件锁路径，防止并发执行
LOCK_FILE = "data/running/pipeline.lock"
# 锁超时时间（秒），超过此时间未释放则视为残留锁自动清理
LOCK_TIMEOUT_SECONDS = 30 * 60  # 30 分钟


class PipelineOrchestrator:
    """
    流水线编排器

    负责按顺序执行：
        Step 1: 数据更新（K线增量 + 除权重建 + 新股初始化 + 基础数据同步）
        Step 2: 策略运行（5维评分 + 信号生成 + CSV输出）
        Step 3: 飞书通知（运行摘要推送）

    属性:
        config: 完整配置字典
        data_dir: 数据目录路径
        kline_updater: K线更新器实例
        new_stock_detector: 新股检测器实例
        strategy_runner: 策略运行器实例
        notifier: 飞书通知器实例
        calendar: 交易日历实例
    """

    def __init__(self, config: dict):
        """
        初始化流水线编排器

        参数:
            config: 完整配置字典 (config.yaml 加载结果)
        """
        self.config = config
        self.data_dir = config.get("data_dir", "data")

        # 延迟初始化的子模块（按需加载避免导入时异常）
        self._data_collection_service = None
        self._strategy_runner = None
        self._notifier = None
        self._calendar = None

    # ---- 子模块懒加载 ----

    @property
    def data_collection_service(self):
        """数据采集服务（懒加载）- 统一管理数据更新所有子步骤"""
        if self._data_collection_service is None:
            from utils.data_collection_service import DataCollectionService
            self._data_collection_service = DataCollectionService(self.data_dir)
        return self._data_collection_service

    @property
    def strategy_runner(self):
        """策略运行器（懒加载）"""
        if self._strategy_runner is None:
            from utils.global_db import get_global_db
            db = get_global_db()
            from trading.strategy_runner import StrategyRunner
            self._strategy_runner = StrategyRunner(db, self.data_dir, self.config)
        return self._strategy_runner

    @property
    def notifier(self):
        """飞书通知器（懒加载）"""
        if self._notifier is None:
            from scheduler.notifier import FeishuNotifier
            self._notifier = FeishuNotifier.from_config(self.config)
        return self._notifier

    @property
    def calendar(self):
        """交易日历（懒加载）"""
        if self._calendar is None:
            from scheduler.trading_calendar import TradingCalendar
            self._calendar = TradingCalendar()
        return self._calendar

    # ---- 锁管理 ----

    def _acquire_lock(self) -> bool:
        """
        获取文件锁，防止流水线并发执行

        使用原子文件创建（os.O_CREAT | os.O_EXCL）实现跨平台互斥。
        POSIX 上追加 fcntl.flock 确保进程崩溃后自动释放。

        超时检测：锁文件超过 LOCK_TIMEOUT_SECONDS 未更新则视为残留，
        自动删除后重试获取。

        返回:
            获取锁成功返回 True
        """
        lock_path = Path(LOCK_FILE)
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # 原子创建锁文件（O_EXCL 确保文件不存在时才创建）
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            self._lock_fd = os.fdopen(fd, 'w')
            # 写入 PID 和时间，便于排查
            self._lock_fd.write(f"pid={os.getpid()}\nstart={datetime.now()}\n")
            self._lock_fd.flush()

            # POSIX: 额外加 fcntl 锁，确保进程崩溃后内核自动释放
            if _HAS_FCNTL:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            return True
        except OSError:
            # 锁文件已存在 → 检测是否超时残留
            if self._is_lock_stale(lock_path):
                logger.warning("残留锁文件已超时，自动清理后重试")
                self._force_release_stale_lock(lock_path)
                # 清理后递归重试一次
                return self._acquire_lock()
            else:
                logger.warning("流水线正在执行中（lock held），跳过本次运行")
                return False

    def _is_lock_stale(self, lock_path: Path) -> bool:
        """
        检测锁文件是否已超时

        通过文件最后修改时间判断，超过 LOCK_TIMEOUT_SECONDS 视为残留。

        参数:
            lock_path: 锁文件路径

        返回:
            超时返回 True
        """
        try:
            mtime = os.path.getmtime(str(lock_path))
            age_seconds = time.time() - mtime
            if age_seconds > LOCK_TIMEOUT_SECONDS:
                logger.warning(
                    "锁文件已过期: %s (修改时间 %s 前, 超时阈值 %d 分钟)",
                    lock_path,
                    self._format_duration(age_seconds),
                    LOCK_TIMEOUT_SECONDS // 60
                )
                return True
        except OSError:
            # 文件可能在检测时被删除，视为可获取锁
            return True
        return False

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """格式化时间跨度为可读字符串"""
        if seconds < 60:
            return f"{seconds:.0f} 秒"
        elif seconds < 3600:
            return f"{seconds / 60:.1f} 分钟"
        else:
            return f"{seconds / 3600:.1f} 小时"

    @staticmethod
    def _force_release_stale_lock(lock_path: Path):
        """
        强制清理残留的锁文件

        参数:
            lock_path: 锁文件路径
        """
        try:
            if lock_path.exists():
                # 读取残留信息用于日志
                try:
                    content = lock_path.read_text()
                    logger.info("清理残留锁文件: %s (内容: %s)", lock_path, content.strip())
                except Exception:
                    logger.info("清理残留锁文件: %s", lock_path)
                lock_path.unlink()
        except Exception as e:
            logger.error("清理残留锁文件失败: %s - %s", lock_path, e)

    def _release_lock(self):
        """释放文件锁，删除锁文件"""
        try:
            if hasattr(self, '_lock_fd') and self._lock_fd:
                if _HAS_FCNTL:
                    try:
                        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                    except Exception:
                        pass
                self._lock_fd.close()
                self._lock_fd = None
            # 删除锁文件，允许下次运行获取锁
            lock_path = Path(LOCK_FILE)
            if lock_path.exists():
                lock_path.unlink()
        except Exception as e:
            logger.debug("释放锁异常: %s", e)

    # ---- 流水线主控 ----

    def run_pipeline(self) -> PipelineResult:
        """
        执行完整流水线

        流程:
            1. 获取文件锁（防并发）
            2. 交易日检测（可选跳过）
            3. Step 1: 数据更新
            4. Step 2: 策略运行
            5. Step 3: 通知

        返回:
            PipelineResult: 包含各步骤状态、耗时、摘要
        """
        result = PipelineResult()
        result.start_time = datetime.now()
        logger.info("流水线 %s 开始执行", result.pipeline_id)

        # 获取文件锁
        if not self._acquire_lock():
            result.status = "skipped"
            result.summary = "流水线正在执行中，跳过本次运行"
            return result

        try:
            # 检查交易日（可配置跳过）
            ps_config = self.config.get("pipeline_schedule", {})
            if ps_config.get("detect_trading_day", True):
                if not self.calendar.is_trading_day():
                    logger.info("当前非交易日，跳过流水线")
                    result.status = "skipped"
                    result.summary = "非交易日，流水线已跳过"
                    result.end_time = datetime.now()
                    result.duration_seconds = (
                        result.end_time - result.start_time
                    ).total_seconds()
                    return result

            # Step 1: 数据更新
            step1 = self._step_data_update()
            result.add_step(step1)

            # 数据更新未正常完成时，跳过策略运行，直接发通知
            if step1.status in ("failed", "skipped"):
                logger.warning("数据更新未正常完成（%s），跳过策略运行", step1.status)
            else:
                # Step 2: 策略运行
                step2 = self._step_strategy_run()
                result.add_step(step2)

            # 汇总状态（优先于通知计算，确保飞书消息拿到正确状态）
            # 优先级: failed > skipped > success
            statuses = [s.status for s in result.steps]
            if any(s == "failed" for s in statuses):
                result.status = "partial_failure"
            elif any(s == "skipped" for s in statuses):
                result.status = "skipped"
            else:
                result.status = "success"

            # 先计算结束时间和总耗时，确保飞书消息能拿到正确的耗时数据
            result.end_time = datetime.now()
            result.duration_seconds = (
                result.end_time - result.start_time
            ).total_seconds()

            # Step 3: 通知（无论什么状态都发送，确保用户知晓）
            step3 = self._step_notify(result)
            result.add_step(step3)

            # 生成摘要
            result.summary = self._build_summary(result)

        finally:
            self._release_lock()
        logger.info("流水线 %s 完成，状态: %s，耗时: %.1f 秒",
                     result.pipeline_id, result.status, result.duration_seconds)

        return result

    # ---- Step 1: 数据更新 ----

    # 轮询等待数据更新完成的最大时长（秒），防止异常情况下无限等待
    _UPDATE_POLL_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 小时
    _UPDATE_POLL_INTERVAL_SECONDS = 10  # 轮询间隔 10 秒

    def _step_data_update(self) -> StepResult:
        """
        Step 1: 数据更新

        通过 DataCollectionService.start_update() 触发更新（与前端 POST /api/data/update/start
        走完全一致的公共 API），然后轮询进度直至完成。

        子步骤（由 DataCollectionService 内部编排）：
            - 交易时间校验
            - 新股检测与初始化
            - K线增量更新
            - 资金流向更新
            - 市值更新
            - 市场温度计算

        返回:
            StepResult: 包含各子步骤状态和统计
        """
        import time as time_module

        step = StepResult(step_name="data_update")
        step.start_time = datetime.now()
        logger.info("Step 1/3: 数据更新开始（通过 start_update API 触发）")

        try:
            # 使用与前端 API 完全一致的公共方法触发更新（后台线程执行）
            start_result = self.data_collection_service.start_update(
                update_types=None  # None = 全部类型
            )

            if not start_result.get('success'):
                # 可能已有更新任务在运行
                err_msg = start_result.get('message', '启动更新任务失败')
                logger.warning("数据更新启动失败: %s", err_msg)
                step.status = "failed"
                step.error = err_msg
                step.details = {"error": err_msg}
                step.end_time = datetime.now()
                step.duration_seconds = (step.end_time - step.start_time).total_seconds()
                return step

            task_id = start_result.get('taskId', 'unknown')
            logger.info("数据更新任务已启动: %s，等待完成...", task_id)

            # 轮询等待更新完成
            deadline = time_module.time() + self._UPDATE_POLL_TIMEOUT_SECONDS
            while time_module.time() < deadline:
                progress = self.data_collection_service.get_update_progress()
                if not progress.get('running'):
                    # 更新完成（4种场景）
                    svc_state = progress.get('status', 'unknown')
                    is_skipped = progress.get('skipped', False)
                    message = progress.get('message', '')
                    total_stats = progress.get('totalStats', {})

                    step.details = {
                        "task_id": task_id,
                        "skipped": is_skipped,
                        "kline_added": total_stats.get('kline_added', 0),
                        "kline_updated": total_stats.get('kline_updated', 0),
                        "kline_failed": total_stats.get('kline_failed', 0),
                        "fund_flow_added": total_stats.get('fund_flow_added', 0),
                        "fund_flow_updated": total_stats.get('fund_flow_updated', 0),
                        "new_stock_detected": total_stats.get('new_stock_detected', 0),
                        "new_stock_initialized": total_stats.get('new_stock_initialized', 0),
                        "market_cap_updated": total_stats.get('market_cap_updated', 0),
                    }

                    # 4种场景：
                    #   场景1: completed + !skipped → success（正常完成，继续）
                    #   场景2: completed + skipped  → skipped（数据源未就绪，停止）
                    #   场景3: failed    + 其他错误 → failed （真正失败，停止）
                    #   场景4: failed    + "已更新过" → success（当日已完成，继续）
                    if is_skipped:
                        # 场景2: 数据源未就绪
                        step.status = "skipped"
                        step.error = message or '数据源未就绪，已跳过本次更新'
                    elif svc_state == 'completed':
                        # 场景1: 正常完成
                        step.status = "success"
                    elif svc_state == 'failed' and '已更新过' in message:
                        # 场景4: 当日已完成更新，视为正常（策略可继续运行）
                        step.status = "success"
                        step.details["already_updated"] = True
                        logger.info("当日数据已完成更新，跳过重复更新（流水线继续执行）")
                    else:
                        # 场景3: 真正失败
                        step.status = "failed"
                        step.error = message
                    break

                # 打印最新日志行（便于排查进度）
                logs = progress.get('logs', [])
                if logs:
                    logger.debug("数据更新进行中: %s", logs[-1].strip())

                time_module.sleep(self._UPDATE_POLL_INTERVAL_SECONDS)
            else:
                # 超时未完成
                step.status = "failed"
                step.error = f"数据更新超时（超过 {self._UPDATE_POLL_TIMEOUT_SECONDS // 60} 分钟）"
                step.details = {"error": step.error}
                logger.error(step.error)

        except Exception as e:
            logger.error("Step 1 数据更新失败: %s", e)
            step.status = "failed"
            step.error = str(e)
            step.details = {"error": str(e)}

        step.end_time = datetime.now()
        step.duration_seconds = (step.end_time - step.start_time).total_seconds()
        logger.info("Step 1 完成: %s (耗时 %.1f 秒)", step.status, step.duration_seconds)
        return step

    # ---- Step 2: 策略运行 ----

    def _step_strategy_run(self) -> StepResult:
        """
        Step 2: 策略运行

        调用 StrategyRunner.run_strategies_batch() 执行选股和信号生成。
        输出 KHunter_signals_{YYYYMMDD}.csv 到 PTrade 目录。

        返回:
            StepResult: 包含信号生成统计
        """
        step = StepResult(step_name="strategy_run")
        step.start_time = datetime.now()
        logger.info("Step 2/3: 策略运行开始")

        details = {
            "buy_signals": 0,
            "sell_signals": 0,
            "signals_generated": 0,
            "signal_file": "",
        }

        try:
            # 从 task_history.json 加载历史任务配置（不存在或无 strategies 时报错终止）
            tasks = self._load_historical_tasks()

            # 构建运行配置（与 web_server.py 一致）
            # 1. 从回测配置获取基础参数
            run_config = self.strategy_runner._get_backtest_config() or {}
            # 2. 流水线配置覆盖特定参数
            ps_config = self.config.get("pipeline_schedule", {})
            sr_config = ps_config.get("strategy_run", {})
            run_config["score_threshold"] = sr_config.get("score_threshold", run_config.get("score_threshold", 60))
            run_config["max_daily_buys"] = sr_config.get("max_daily_buys", run_config.get("max_daily_buys", 3))
            # 3. 海龟类策略（海龟/低位海龟/海龟plus）参数注入：按策略名写入 timing_params，
            #    与 web_server 批量执行、回测、运行器同一口径（build_turtle_family_params 合并）。
            #    2026-09-16 修复：原实现只认 'turtle' 且写顶层键 → 海龟plus 回退默认预设。
            # 【2026-09-23 合并】海龟类参数统一走**唯一读取入口** ✓（yaml 只保留一个配置块）
            from trading.timing_strategies import (
                TURTLE_FAMILY_STRATEGIES, load_turtle_family_params)
            _timing_names = {str(t.get('timing_strategy') or '') for t in tasks}
            _turtle_tasks = [n for n in TURTLE_FAMILY_STRATEGIES if n in _timing_names]
            if _turtle_tasks:
                try:
                    from utils.strategy_config_manager import StrategyConfigManager
                    config_manager = StrategyConfigManager()
                    _timing_params = dict(run_config.get('timing_params') or {})
                    for _name in _turtle_tasks:
                        _params = load_turtle_family_params(_name, config_manager)
                        _timing_params[_name] = {**_params, **(_timing_params.get(_name) or {})}
                        logger.info("  海龟类参数（%s）: %s", _name, _params)
                    run_config['timing_params'] = _timing_params
                    # 单一海龟类策略时同时写顶层键（运行器/引擎优先读顶层配置）
                    if len(_turtle_tasks) == 1:
                        run_config.update({k: v for k, v in
                                           _timing_params[_turtle_tasks[0]].items()
                                           if v is not None})
                except Exception as e:
                    logger.warning("  读取海龟类策略配置失败，沿用调用方参数: %s", e)

            # 日志显示实际使用的任务策略（兼容 selection_strategy 和 strategy_names 两种 key）
            task_summary = ", ".join(
                "[" + ",".join([t.get('selection_strategy', '')] if t.get('selection_strategy') else t.get('strategy_names', ['?'])) + "]/" + t.get('timing_strategy', '?')
                for t in tasks
            )
            logger.info("  任务数: %d, 策略: %s", len(tasks), task_summary)

            batch_result = self.strategy_runner.run_strategies_batch(
                tasks=tasks, config=run_config
            )

            # 提取统计数据（从 batch_result["data"] 中获取实际返回格式）
            if batch_result:
                batch_status = batch_result.get("status", "")

                # 策略运行失败（如 PTrade 反馈文件缺失）→ 直接标记失败
                if batch_status == "failed":
                    step.status = "failed"
                    step.error = batch_result.get("message", "策略运行失败")
                    details["error_message"] = step.error
                    step.details = details
                    logger.warning("  策略运行失败: %s", step.error)
                else:
                    data = batch_result.get("data", {})
                    details["buy_signals"] = data.get("buy_signals", 0)
                    details["sell_signals"] = data.get("sell_signals", 0)
                    details["signals_generated"] = data.get("total_signals", 0)
                    details["signal_file"] = data.get("ptrade_csv_file", "")

                    # 【2026-09-24】股票池增删（整体 + 明细）→ 透传给飞书简报 ✓
                    #   数据源：StrategyRunner.run_strategies_batch 返回的 data ✓
                    #   （池内合计 + 新增明细/移除明细 + 选股/持仓回池分项计数 ✓）
                    details["pool_count"] = data.get("pool_count", 0)
                    details["pool_added_items"] = data.get("pool_added_items", []) or []
                    details["pool_removed_items"] = data.get("pool_removed_items", []) or []
                    details["pool_added_selection_count"] = data.get("pool_added_selection_count", 0)
                    details["pool_added_holding_count"] = data.get("pool_added_holding_count", 0)
                    details["pool_removed_count"] = data.get("pool_removed_count", 0)

                    # ===== 获取资金信息 =====
                    sr = self.strategy_runner
                    # 可用资金（PTrade 反算的真实现金余额）
                    available_cash = getattr(sr, 'current_total_capital', 0)
                    details["available_cash"] = available_cash
                    # 持仓（KHunter 持仓刻意不含 ETF，仅含股票）
                    portfolio = getattr(sr, 'portfolio', {})
                    # 总资产：优先使用 PTrade 反馈的真实总资产（含 ETF 市值），
                    # 因 KHunter 持仓刻意不含 ETF，若用「可用现金 + 持仓市值」反算会漏算 ETF 市值；
                    # 仅在未同步 PTrade（如手动/非自动模式）时回退到现金 + 持仓市值反算
                    real_total_asset = getattr(sr, 'current_total_asset', None)
                    if real_total_asset:
                        total_assets = real_total_asset
                    else:
                        total_assets = available_cash
                        for pos in portfolio.values():
                            total_assets += pos.get('market_value', 0) or (pos.get('quantity', 0) * pos.get('current_price', 0))
                    details["total_assets"] = total_assets
                    # 持仓数量
                    details["position_count"] = len(portfolio)

                    # ===== 策略信息 =====
                    # 从加载的 tasks 中提取（兼容两种 key：selection_strategy 和 strategy_names）
                    all_strategies = []
                    timing = 'support'
                    for t in tasks:
                        sel = t.get('selection_strategy', None)
                        if sel:
                            # 单个策略（_load_historical_tasks 生成或 Web 端传入）
                            all_strategies.append(sel)
                        else:
                            # 多策略列表（Web 端批量运行传入）
                            names = t.get('strategy_names', [])
                            all_strategies.extend(names)
                        timing = t.get('timing_strategy', timing)
                    details["selection_strategies"] = list(set(all_strategies))  # 去重
                    details["timing_strategy"] = timing

                    # ===== 信号日期 =====
                    details["signal_date"] = data.get("run_date", "")

                    # ===== 信号详情 =====
                    # 从 signals JSON 文件读取详细信号信息
                    signal_details = self._load_signal_details(details["signal_date"])
                    details["buy_signal_items"] = signal_details.get("buy", [])
                    details["sell_signal_items"] = signal_details.get("sell", [])

                    step.details = details
                    step.status = "success"
                    logger.info("  信号: 买入 %d, 卖出 %d", details["buy_signals"], details["sell_signals"])

        except Exception as e:
            logger.error("  策略运行失败: %s", e)
            step.status = "failed"
            step.error = str(e)
            step.details = details

        step.end_time = datetime.now()
        step.duration_seconds = (step.end_time - step.start_time).total_seconds()
        logger.info("Step 2 完成: %s (耗时 %.1f 秒)", step.status, step.duration_seconds)
        return step

    # ---- Step 3: 通知 ----

    def _step_notify(self, result: PipelineResult) -> StepResult:
        """
        Step 3: 飞书通知

        发送流水线运行摘要到飞书群。
        通知失败不影响流水线主流程。

        参数:
            result: 当前流水线执行结果

        返回:
            StepResult: 包含通知发送状态
        """
        step = StepResult(step_name="notification")
        step.start_time = datetime.now()
        logger.info("Step 3/3: 飞书通知开始")

        details = {"feishu_sent": False}

        try:
            # 检查是否启用
            if not self.notifier.enabled:
                logger.info("  飞书通知未启用，跳过")
                step.status = "skipped"
            else:
                # 发送运行摘要
                success = self.notifier.send_summary(result)
                if success:
                    details["feishu_sent"] = True
                    logger.info("  运行摘要已发送")
                else:
                    logger.warning("  运行摘要发送失败（不阻断流水线）")

                # 异常时发送告警（含数据源跳过）
                if result.status in ("partial_failure", "failed", "skipped"):
                    alert_ok = self.notifier.send_alert(result)
                    if alert_ok:
                        logger.info("  异常告警已发送")

                step.status = "success"

        except Exception as e:
            logger.warning("  飞书通知失败（不阻断流水线）: %s", e)
            step.status = "success"  # 通知失败不标记为失败

        step.details = details
        step.end_time = datetime.now()
        step.duration_seconds = (step.end_time - step.start_time).total_seconds()
        logger.info("Step 3 完成: %s (耗时 %.1f 秒)", step.status, step.duration_seconds)
        return step

    # ---- 辅助方法 ----

    def _load_signal_details(self, signal_date: str) -> Dict[str, list]:
        """从 signals JSON 文件加载信号详情
        
        Args:
            signal_date: 信号日期，格式 YYYY-MM-DD
            
        Returns:
            {'buy': [...], 'sell': [...]} 格式的信号详情列表
        """
        result = {"buy": [], "sell": []}
        if not signal_date:
            return result
        signals_file = Path(self.data_dir) / "running" / f"signals_{signal_date}.json"
        if not signals_file.exists():
            logger.debug("信号文件不存在: %s", signals_file)
            return result
        try:
            with open(signals_file, 'r', encoding='utf-8') as f:
                signals = json.load(f)
            # 分类 buy/sell 信号，提取关键字段
            for sig in signals:
                item = {
                    "stock_code": sig.get("stock_code", ""),
                    "stock_name": sig.get("stock_name", ""),
                    "price": sig.get("price", 0),
                    "quantity": sig.get("quantity", 0),
                    "amount": sig.get("amount", 0),
                    "trade_type": sig.get("trade_type", ""),
                    "reason": sig.get("reason", ""),
                    "strategy_name": sig.get("strategy_name", ""),
                }
                sig_type = sig.get("signal_type", "")
                if sig_type == "buy":
                    result["buy"].append(item)
                elif sig_type == "sell":
                    result["sell"].append(item)
        except Exception as e:
            logger.warning("读取信号详情失败: %s", e)
        return result

    def _load_historical_tasks(self) -> List[Dict]:
        """从 task_history.json 加载上次任务配置（标准格式）
        
        task_history.json 标准格式：
        [{id, timestamp, strategies: [...], timing_strategy, ...}, ...]
        
        读取最新记录的 strategies 和 timing_strategy，
        映射为 run_strategies_batch 所需的 strategy_names 和 timing_strategy。
        
        文件不存在或无有效策略 → 直接抛异常，终止流水线并通知用户。
        
        Returns:
            任务列表（可直接传入 run_strategies_batch）
            
        Raises:
            RuntimeError: 无历史任务或无有效策略
        """
        running_dir = Path(self.data_dir) / "running"
        history_file = running_dir / "task_history.json"
        if not history_file.exists():
            raise RuntimeError(
                "task_history.json 不存在，请先通过界面/API 手动运行一次策略"
            )
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
        if not history:
            raise RuntimeError(
                "task_history.json 为空，请先通过界面/API 手动运行一次策略"
            )
        # 取最新一条记录
        latest = history[-1]
        strategies = latest.get('strategies', [])
        # 过滤空字符串，防止写入空值导致运行时策略名为空
        strategies = [s for s in strategies if s]
        timing_strategy = latest.get('timing_strategy', 'support')
        if not strategies:
            raise RuntimeError(
                "task_history.json 最新记录中 strategies 为空，"
                "请先通过界面/API 手动运行一次策略"
            )
        # 每个策略拆分为独立 task（与 Web 端 /api/strategy/run-batch 格式一致）
        tasks = [{
            'selection_strategy': s,
            'timing_strategy': timing_strategy,
        } for s in strategies]
        logger.info("  从 task_history.json 加载历史任务: 策略=%s, 择时=%s (共 %d 个任务)",
                     strategies, timing_strategy, len(tasks))
        return tasks

    def _build_summary(self, result: PipelineResult) -> str:
        """
        构建人类可读的流水线摘要

        参数:
            result: 流水线执行结果

        返回:
            摘要字符串
        """
        parts = [f"流水线 {result.pipeline_id}"]
        for step in result.steps:
            status_icon = "OK" if step.status == "success" else "FAIL"
            parts.append(
                f"  {step.step_name}: {status_icon} "
                f"({step.duration_seconds:.0f}s)"
            )
        parts.append(f"总耗时: {result.duration_seconds:.0f}s")
        return "\n".join(parts)
