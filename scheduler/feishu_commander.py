# -*- coding: utf-8 -*-
"""
?????????????

???? API ??????????????????? KHunter ???
????? IP?????? URL?????????

?????????????
  - im:message??? + ?????
  - ??????????

????:
  ???? / pipeline     -> ???????
  ???? / data          -> ???????
  ??? / strategy        -> ???????
  ?? / status            -> ????????
  ?? / help              -> ??????
"""

import json as jmod
import logging
import os
import re
import threading
import time as time_module
from typing import Optional

import requests

from scheduler.models import PipelineResult, StepResult

logger = logging.getLogger(__name__)

FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_LIST_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

# 耗时指令：同一时刻仅允许一个实例运行，防止并发触发（对齐 etfhunter 的流水线并发保护）
_HEAVY_COMMANDS = {"pipeline", "data_update", "strategy_run"}

# 指令展示描述：用于"即将执行"预回复消息，向用户说明接下来要执行的具体任务
_COMMAND_DESC = {
    "pipeline": {
        "name": "完整流水线",
        "detail": "依次执行：数据更新 → 策略运行 → 信号汇总",
    },
    "data_update": {
        "name": "数据更新",
        "detail": "拉取全市场股票基础信息、日K线、财务基本面数据",
    },
    "strategy_run": {
        "name": "策略运行",
        "detail": "基于最新数据筛选买入候选、生成卖出信号",
    },
}


class FeishuCommander:

    def __init__(self, config: dict):
        feishu = config.get("feishu", {})
        cmd_config = config.get("feishu_commander", {})
        self.enabled = cmd_config.get("enabled", False)
        self.app_id = feishu.get("app_id", "")
        self.app_secret = feishu.get("app_secret", "")
        self.chat_id = feishu.get("chat_id", "")
        self.poll_interval = cmd_config.get("poll_interval_seconds", 30)
        self.command_timeout = cmd_config.get("command_timeout_minutes", 15) * 60
        self.config = config
        self.trigger_prefix = cmd_config.get("trigger_prefix", "")
        self.mention_trigger = cmd_config.get("mention_trigger", "")  # 本应用飞书群 @mention 触发词
        self._token = None
        self._token_expire = 0.0
        self._last_message_id = None
        self._running = False
        # 【2026-09-18】已执行消息ID（落盘）：内存游标无法跨进程/跨重启去重，
        #   双进程（旧服务未停 + 新服务）或执行抛错都会导致同一指令被执行两次。
        #   采用"先记录再执行"（幂等），并持久化最近 N 条，供多进程互斥识别。
        self._state_path = os.path.join('data', 'running', 'feishu_commander_state.json')
        self._executed_ids = self._load_executed_ids()
        # 并发保护：避免同一耗时指令被重复触发并发执行（与轮询线程解耦）
        self._cmd_lock = threading.Lock()
        self._active_cmds = set()
        logger.info("FeishuCommander: enabled=%s, chat_id=%s, poll=%ds",
                     self.enabled, self.chat_id, self.poll_interval)

    # ==================== 指令幂等（防重复执行）====================

    def _load_executed_ids(self) -> list:
        """加载已执行消息ID（失败不阻断，返回空列表）"""
        try:
            with open(self._state_path, 'r', encoding='utf-8') as f:
                data = jmod.load(f)
            ids = data.get('executed_ids') or []
            logger.info("FeishuCommander: 载入已执行消息 %d 条（防重复执行）", len(ids))
            return list(ids)
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.warning("FeishuCommander: 载入已执行消息失败（忽略）: %s", e)
            return []

    def _save_executed_ids(self, keep: int = 200) -> None:
        """持久化已执行消息ID（仅保留最近 keep 条）"""
        try:
            self._executed_ids = self._executed_ids[-keep:]
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            with open(self._state_path, 'w', encoding='utf-8') as f:
                jmod.dump({'executed_ids': self._executed_ids,
                           'updated_at': time_module.strftime('%Y-%m-%d %H:%M:%S')},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("FeishuCommander: 保存已执行消息失败（忽略）: %s", e)

    def _already_executed(self, msg_id: str) -> bool:
        """该消息是否已执行过（跨进程/跨重启去重）"""
        return bool(msg_id) and msg_id in self._executed_ids

    def _mark_executed(self, msg_id: str) -> None:
        """标记消息已执行（**执行前**调用：即使执行抛错也不会重复执行）"""
        if msg_id and msg_id not in self._executed_ids:
            self._executed_ids.append(msg_id)
            self._save_executed_ids()

    def _get_tenant_access_token(self) -> Optional[str]:
        if self._token and time_module.time() < self._token_expire - 300:
            return self._token
        try:
            resp = requests.post(
                FEISHU_TOKEN_URL,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Get token failed: code=%s, msg=%s", data.get("code"), data.get("msg"))
                return None
            self._token = data["tenant_access_token"]
            self._token_expire = time_module.time() + data.get("expire", 7200)
            return self._token
        except requests.RequestException as e:
            logger.error("Get token error: %s", e)
            return None

    def start_polling(self):
        if not self.enabled:
            logger.info("FeishuCommander not enabled")
            return
        if self._running:
            return
        self._running = True
        thread = threading.Thread(target=self._poll_loop, daemon=True, name="feishu-poller")
        thread.start()
        logger.info("Polling started (interval %ds)", self.poll_interval)

    def _poll_loop(self):
        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                logger.error("Poll error: %s", e)
            time_module.sleep(self.poll_interval)

    def _poll_once(self):
        token = self._get_tenant_access_token()
        if not token:
            return
        messages = self._list_messages(token)
        if not messages:
            return
        # 首次轮询：仅记录最新消息ID，跳过历史消息，避免启动时重复执行旧指令（对齐 etfhunter）
        if self._last_message_id is None and messages:
            self._last_message_id = messages[0].get("message_id", "")
            logger.info("首次轮询，跳过历史消息，记录起始ID: %s", self._last_message_id)
            return
        newest_id = None
        processed_in_poll = set()  # 本轮已处理的消息ID，防列表内重复项导致同一条指令被处理多遍
        for msg in messages:
            msg_id = msg.get("message_id", "")
            sender = msg.get("sender", {})
            # 列表按创建时间倒序，命中已处理的最旧消息即停止（游标断点）
            if self._last_message_id and msg_id == self._last_message_id:
                break
            # 同一轮拉取中，飞书可能返回重复 message_id（分页/缓存边界），
            # 仅凭借游标断点无法拦截列表内重复项，需本轮去重避免同指令被处理多遍
            if msg_id in processed_in_poll:
                continue
            processed_in_poll.add(msg_id)
            # 记录已扫描到的最新消息ID：无论是否命中指令都推进游标，
            # 否则被忽略的消息会每轮重复拉取、重复打印日志（修复刷屏根因）
            if newest_id is None:
                newest_id = msg_id
            if sender.get("sender_type") == "app":
                continue
            if msg.get("msg_type", "") != "text":
                continue
            text = self._extract_text_content(msg.get("body", {}).get("content", ""))
            if not text:
                continue
            command = self._parse_command(text)
            if not command:
                continue
            chat_id = msg.get("chat_id", "")
            # 【2026-09-18】幂等：同一消息只执行一次（跨进程/跨重启/执行异常都不重复）
            if self._already_executed(msg_id):
                logger.info("跳过重复指令（该消息已执行过）: msg %s cmd=%s", msg_id, command)
                continue
            # 先记录 + 推进游标，再执行：避免执行抛错导致下一轮重复执行同一条指令
            self._mark_executed(msg_id)
            self._last_message_id = msg_id
            logger.info("Command: %s (msg %s)", command, msg_id)
            self._execute_command(command, chat_id)
        if newest_id:
            self._last_message_id = newest_id

    def _list_messages(self, token: str) -> list:
        try:
            resp = requests.get(
                FEISHU_LIST_MSG_URL,
                headers={"Authorization": "Bearer " + token},
                params={
                    "container_id_type": "chat",
                    "container_id": self.chat_id,
                    "page_size": 10,
                    "sort_type": "ByCreateTimeDesc",
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("List messages failed: code=%s, msg=%s", data.get("code"), data.get("msg"))
                return []
            return data.get("data", {}).get("items", [])
        except requests.RequestException as e:
            logger.error("List messages error: %s", e)
            return []

    @staticmethod
    def _extract_text_content(content_raw: str) -> str:
        try:
            content = jmod.loads(content_raw)
            return content.get("text", "").strip()
        except (jmod.JSONDecodeError, TypeError, AttributeError):
            return ""

    _COMMAND_MAP = {
        "pipeline": "pipeline",
        "data_update": "data_update",
        "data": "data_update",
        "strategy_run": "strategy_run",
        "strategy": "strategy_run",
        "status": "status",
        "help": "help",
    }

    _CHINESE_COMMAND_MAP = {
        "跑流水线": "pipeline",
        "流水线": "pipeline",
        "更新数据": "data_update",
        "更新": "data_update",
        "跑策略": "strategy_run",
        "策略": "strategy_run",
        "状态": "status",
        "帮助": "help",
        "指令": "help",
        "命令": "help",
    }

    def _parse_command(self, text: str) -> Optional[str]:
        t = text.strip()
        logger.debug("Feishu parse raw=%r", t)  # 诊断：打印飞书真实消息文本格式
        # 剥离本应用的 @mention 前缀（对齐 etfhunter 的鲁棒做法）
        # 飞书群聊 @ 机器人渲染变体较多（@khunter / @KHunter / @(khunter) 等），
        # 只要文本含 @<mention> 子串即视为对本应用提及，且仅移除提及词本身，
        # 不贪婪吃掉后续指令文本（避免 @KHunter跑流水线 把指令也吞掉）。
        mention = self.mention_trigger
        if mention:
            mention_pat = re.compile(r'@\s*\(?' + re.escape(mention) + r'\)?\s*', re.IGNORECASE)
            if not mention_pat.search(t):
                return None
            t = mention_pat.sub('', t, count=1).strip()
            # 仅 @ 提及但无指令文本时，默认执行完整流水线
            # （对齐 etfhunter：裸 @etfhunter -> pipeline，确保 @ 机器人一定有反应）
            if not t:
                return "pipeline"
        if self.trigger_prefix:
            if not t.startswith(self.trigger_prefix):
                return None
            t = t[len(self.trigger_prefix):].strip()
        # Check Chinese commands first
        if t in self._CHINESE_COMMAND_MAP:
            return self._CHINESE_COMMAND_MAP[t]
        for phrase, cmd in self._CHINESE_COMMAND_MAP.items():
            if t.startswith(phrase):
                return cmd
        # Fallback to English commands
        normalized = t.lower()
        if normalized in self._COMMAND_MAP:
            return self._COMMAND_MAP[normalized]
        for phrase, cmd in self._COMMAND_MAP.items():
            if normalized.startswith(phrase):
                return cmd
        return None

    def _execute_command(self, command: str, chat_id: str):
        """将指令派发到后台线程执行，避免阻塞轮询线程（对齐 etfhunter 的 _pipeline_worker）。

        耗时指令（流水线/数据更新/策略）同一时刻仅允许一个实例运行，
        重复触发时直接提示并跳过，防止并发执行。
        """
        logger.info("Exec: %s", command)
        # 耗时指令并发保护：已在运行时直接提示并跳过，避免重复触发
        if command in _HEAVY_COMMANDS:
            with self._cmd_lock:
                if command in self._active_cmds:
                    self._send_text(chat_id, "指令「" + command + "」正在执行中，请稍候...")
                    return
                self._active_cmds.add(command)
        # 放入后台线程执行，轮询线程立即返回，保证后续消息仍可及时响应
        threading.Thread(
            target=self._execute_command_worker,
            args=(command, chat_id),
            daemon=True,
            name="feishu-cmd-" + command,
        ).start()

    def _execute_command_worker(self, command: str, chat_id: str):
        """后台线程：实际执行指令逻辑（与轮询线程解耦，避免阻塞）。"""
        try:
            # 耗时指令在执行前先回"即将执行"提示，向用户展示具体任务并提醒等候
            if command in _HEAVY_COMMANDS:
                self._send_command_ack(command, chat_id)
            if command == "pipeline":
                self._run_pipeline(chat_id)
            elif command == "data_update":
                self._run_data_update(chat_id)
            elif command == "strategy_run":
                self._run_strategy(chat_id)
            elif command == "status":
                self._run_status()
            elif command == "help":
                self._send_help(chat_id)
        except Exception as e:
            logger.error("Exec failed: %s - %s", command, e)
            self._send_text(chat_id, "Execution failed: " + str(e))
        finally:
            # 指令结束，释放并发保护标记（仅耗时指令）
            if command in _HEAVY_COMMANDS:
                with self._cmd_lock:
                    self._active_cmds.discard(command)

    def _run_pipeline(self, chat_id=None):
        from scheduler.pipeline_orchestrator import PipelineOrchestrator
        orchestrator = PipelineOrchestrator(self.config)
        logger.info("Pipeline start (feishu triggered)")
        orchestrator.run_pipeline()
        logger.info("Pipeline done")
        # 流水线执行完毕回包到触发群（chat_id 缺省退回默认群）
        self._send_text(chat_id, "流水线执行完成。")

    def _run_data_update(self, chat_id=None):
        from utils.data_collection_service import get_data_collection_service
        service = get_data_collection_service(self.config.get("data_dir", "data"))
        start_result = service.start_update(update_types=None)
        if start_result.get("success"):
            # 注："开始执行"提示已由 _send_command_ack 统一发送，此处不再重复
            deadline = time_module.time() + self.command_timeout
            while time_module.time() < deadline:
                progress = service.get_update_progress()
                if not progress.get("running"):
                    status = progress.get("status", "unknown")
                    stats = progress.get("totalStats", {})
                    msg = "更新完成: " + status + "\nK线: +" + str(stats.get("kline_added", 0)) + " 更新 " + str(stats.get("kline_updated", 0))
                    self._send_text(chat_id, msg)
                    return
                time_module.sleep(5)
            self._send_text(chat_id, "更新超时")
        else:
            self._send_text(chat_id, "更新失败: " + start_result.get("message", "?"))

    def _run_strategy(self, chat_id=None):
        from utils.global_db import get_global_db
        db = get_global_db()
        data_dir = self.config.get("data_dir", "data")
        from trading.strategy_runner import StrategyRunner
        runner = StrategyRunner(db, data_dir, self.config)
        tasks = [{}]
        from pathlib import Path
        history_file = Path(data_dir) / "running" / "task_history.json"
        if history_file.exists():
            with open(history_file, "r", encoding="utf-8") as f:
                history = jmod.load(f)
            if history:
                latest = history[-1]
                strategies = latest.get("strategies", [])
                strategies = [s for s in strategies if s]
                timing = latest.get("timing_strategy", "support")
                if strategies:
                    # 每个策略拆分为独立 task（与 Web 端格式一致：selection_strategy + timing_strategy）
                    tasks = [{"selection_strategy": s, "timing_strategy": timing} for s in strategies]
        result = runner.run_strategies_batch(tasks=tasks, config={})
        status = "ok" if result and result.get("status") != "failed" else "fail"
        data = result.get("data", {}) if result else {}
        msg = "策略 " + status + "\n买入: " + str(data.get("buy_signals", 0)) + " 卖出: " + str(data.get("sell_signals", 0))
        self._send_text(chat_id, msg)

    def _run_status(self):
        from utils.global_db import get_global_db
        db = get_global_db()
        try:
            stock_count = db.query("SELECT COUNT(*) as c FROM stock_basic")[0]["c"]
        except Exception:
            stock_count = 0
        try:
            kline_count = db.query("SELECT COUNT(*) as c FROM stock_kline")[0]["c"]
        except Exception:
            kline_count = 0
        latest_kline_date = ""
        try:
            row = db.query("SELECT MAX(date) as d FROM stock_kline")
            if row and row[0]["d"]:
                latest_kline_date = row[0]["d"]
        except Exception:
            pass
        from trading.strategy_runner import StrategyRunner
        data_dir = self.config.get("data_dir", "data")
        runner = StrategyRunner(db, data_dir, self.config)
        working_date = runner.get_working_date()
        signals_file = runner.running_dir / ("signals_" + working_date + ".json")
        signals = runner._load_signals(str(signals_file)) if signals_file.exists() else []
        buy_count = sum(1 for s in signals if s.get("signal_type") == "buy")
        sell_count = sum(1 for s in signals if s.get("signal_type") == "sell")
        msg = "Stock count: " + str(stock_count) + "\nKline: " + str(kline_count) + " (latest " + latest_kline_date + ")\nDate: " + working_date + "\nSignals: buy " + str(buy_count) + " sell " + str(sell_count)
        self._send_text(None, msg)

    def _send_command_ack(self, command: str, chat_id: str):
        """耗时指令执行前先回包：展示即将执行的具体任务并提醒用户等候。

        入参:
            command: 内部指令名（pipeline/data_update/strategy_run）
            chat_id: 触发消息所在群，确保提示发到正确的会话
        """
        desc = _COMMAND_DESC.get(command)
        if not desc:
            return  # 非耗时指令无需预回复
        # 组装"即将执行"提示文案（中文），列出名称、具体任务与等候提醒
        msg = ("⏳ 收到指令，开始执行：**" + desc["name"] + "**\n"
               "具体任务：" + desc["detail"] + "\n"
               "预计耗时较长，请稍候；执行完成后会自动汇报结果。")
        self._send_text(chat_id, msg)

    def _send_help(self, chat_id: str):
        msg = ("Commands:\n"
               "pipeline - run full pipeline\n"
               "data_update - update data only\n"
               "strategy_run - run strategy only\n"
               "status - system status\n"
               "help - this help")
        self._send_text(chat_id, msg)

    def _send_text(self, chat_id, text):
        target = chat_id or self.chat_id
        if not target:
            logger.warning("No chat_id")
            return
        token = self._get_tenant_access_token()
        if not token:
            return
        card = {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "KHunter"}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": text}],
        }
        try:
            resp = requests.post(
                FEISHU_MSG_URL,
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                json={"receive_id": target, "msg_type": "interactive", "content": jmod.dumps(card)},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Send failed: code=%s, msg=%s", data.get("code"), data.get("msg"))
        except requests.RequestException as e:
            logger.error("Send error: %s", e)

    def handle_callback(self, body: dict) -> dict:
        """飞书事件回调入口（仅用于 URL 验证，不再处理指令）。

        系统采用"仅轮询"模式接收指令：指令由后台轮询线程从群聊拉取并执行，
        回调通道只保留飞书开放平台要求的 URL 验证响应，收到消息事件时直接
        忽略，避免与轮询通道重复执行同一指令（双通道去重根因消除）。

        返回:
            - url_verification / 含 challenge: {"challenge": value}（保留验证能力）
            - event_callback / 其他事件: {}（忽略，不执行任何指令）
        """
        event_type = body.get("type", "")
        # 飞书配置回调 URL 时的验证请求，必须原样返回 challenge
        if event_type == "url_verification":
            return {"challenge": body.get("challenge", "")}
        challenge = body.get("challenge")
        if challenge:
            return {"challenge": challenge}
        # 消息事件等一律忽略：指令统一由轮询通道（_poll_loop）处理
        logger.info("Feishu callback event=%s ignored (poll-only mode)", event_type)
        return {}




def get_commander(config: dict = None):
    if not hasattr(get_commander, "_instance"):
        if config is None:
            import os, yaml
            cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "config.yaml")
            with open(cfg_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        get_commander._instance = FeishuCommander(config)
    return get_commander._instance
