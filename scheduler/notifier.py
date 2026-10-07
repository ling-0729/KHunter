# -*- coding: utf-8 -*-
"""
飞书通知器

通过飞书 API 发送流水线运行摘要和异常告警。

支持两种认证方式（按优先级）：
  1. App ID + App Secret → 获取 tenant_access_token，通过 API 发送消息
  2. Webhook URL + 签名密钥 → 直接 POST 消息卡片（兼容旧方案）

激活条件: config.yaml 中 feishu 配置非空占位符时自动启用
通知模式: 默认发送运行摘要；支持 alert_only 模式（仅在异常时通知）
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

import requests

from scheduler.models import PipelineResult

logger = logging.getLogger(__name__)

# 飞书 API 端点
FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
FEISHU_CHAT_LIST_URL = "https://open.feishu.cn/open-apis/im/v1/chats"


class FeishuNotifier:
    """
    飞书消息通知器

    App ID + App Secret 方式:
      1. 调用 tenant_access_token 接口获取 token
      2. 使用 token 调用消息发送 API

    Webhook 方式（兜底）:
      1. 使用 webhook_url + 签名密钥直接 POST

    属性:
        app_id: 飞书应用 App ID
        app_secret: 飞书应用 App Secret
        webhook_url: 飞书机器人 webhook 地址（可选）
        signing_secret: webhook 签名密钥（可选）
        chat_id: 目标群聊 ID（API 方式必填）
        enabled: 是否启用通知（配置非空时自动启用）
        alert_only: 仅异常时通知模式
        _token: 缓存的 tenant_access_token
        _token_expire: token 过期时间戳
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        webhook_url: Optional[str] = None,
        signing_secret: Optional[str] = None,
        chat_id: Optional[str] = None,
        alert_only: bool = False,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.webhook_url = webhook_url
        self.signing_secret = signing_secret
        self.chat_id = chat_id
        self.alert_only = alert_only

        # 缓存 token
        self._token: Optional[str] = None
        self._token_expire: float = 0.0

        # 判断是否可用: App ID 方式或 webhook 方式任一配置即可
        self.enabled = self._has_valid_api_config() or self._has_valid_webhook_config()
        if self.enabled:
            # 记录已启用的方式
            mode = "API" if self._has_valid_api_config() else "webhook"
            logger.info("飞书通知器已启用 (模式: %s)", mode)

    # ---- 配置校验 ----

    def _has_valid_api_config(self) -> bool:
        """检查 App ID + Secret + chat_id 是否有效配置"""
        if not self.app_id or not self.app_secret:
            return False
        # 排除占位符
        for val in (self.app_id, self.app_secret):
            if any(kw in val for kw in ("YOUR_", "your_", "PLACEHOLDER", "placeholder", "TODO")):
                return False
        return True

    def _has_valid_webhook_config(self) -> bool:
        """检查 webhook URL 是否为有效配置"""
        if not self.webhook_url:
            return False
        for kw in ("YOUR_", "your_", "PLACEHOLDER", "placeholder", "TODO"):
            if kw in self.webhook_url:
                return False
        return True

    # ---- Token 管理 (App ID + Secret 方式) ----

    def _get_tenant_access_token(self) -> Optional[str]:
        """
        获取 tenant_access_token，自动处理缓存

        飞书 token 有效期 2 小时，缓存到过期前 5 分钟刷新。

        返回:
            token 字符串，获取失败返回 None
        """
        # 缓存的 token 还有 5 分钟以上有效期，直接返回
        if self._token and time.time() < self._token_expire - 300:
            return self._token

        if not self._has_valid_api_config():
            logger.warning("飞书 App 配置无效，无法获取 token")
            return None

        try:
            # 请求 tenant_access_token
            resp = requests.post(
                FEISHU_TOKEN_URL,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=10,
            )
            data = resp.json()
            # 飞书 API 返回 code=0 表示成功
            if data.get("code") != 0:
                logger.error("获取飞书 token 失败: code=%s, msg=%s",
                             data.get("code"), data.get("msg"))
                return None

            self._token = data["tenant_access_token"]
            # expire 字段单位是秒，转为时间戳
            self._token_expire = time.time() + data.get("expire", 7200)
            logger.info("飞书 tenant_access_token 获取成功")
            return self._token

        except requests.RequestException as e:
            logger.error("获取飞书 token 网络异常: %s", e)
            return None

    # ---- 消息发送 ----

    def send_summary(self, pipeline_result: PipelineResult) -> bool:
        """
        发送流水线运行摘要（Markdown 卡片）

        仅在 enabled=True 且 alert_only=False 时发送。

        参数:
            pipeline_result: 流水线执行结果

        返回:
            发送成功返回 True，失败或被跳过返回 False
        """
        if not self.enabled:
            logger.debug("飞书通知未启用，跳过摘要发送")
            return False
        if self.alert_only and pipeline_result.status == "success":
            logger.debug("alert_only 模式，流水线正常，跳过摘要")
            return False

        # 生成消息内容
        title = "KHunter 定时流水线运行报告"
        content = self._build_summary_markdown(pipeline_result)

        return self._send(title, content)

    def send_alert(self, pipeline_result: PipelineResult) -> bool:
        """
        发送异常告警（Markdown 卡片）

        仅在 enabled=True 且状态非 success 时发送。

        参数:
            pipeline_result: 流水线执行结果

        返回:
            发送成功返回 True，失败或被跳过返回 False
        """
        if not self.enabled:
            logger.debug("飞书通知未启用，跳过告警发送")
            return False

        # 仅异常时告警
        if pipeline_result.status == "success":
            return False

        # 生成告警消息
        title = "KHunter 定时流水线异常告警"
        content = self._build_alert_markdown(pipeline_result)

        return self._send(title, content)

    # ---- 消息构建 ----

    def _build_summary_markdown(self, result: PipelineResult) -> str:
        """
        构建运行摘要 Markdown 内容

        格式参考设计文档 7.2.2 节
        """
        # 获取当日日期
        from datetime import date
        today = date.today()
        weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
        weekday = weekday_map[today.weekday()]

        # 格式化耗时
        total_dur = self._format_duration(result.duration_seconds)
        start_str = result.start_time.strftime("%H:%M:%S") if result.start_time else "N/A"

        # 构建 Markdown 内容
        lines = [
            f"**日期**: {today} (周{weekday})",
            f"**开始时间**: {start_str} | **总耗时**: {total_dur}",
            "",
        ]

        # 【2026-09-20】市场环境：市场温度 + 市场 ADX（与市场速览、自适应回测同一数据源）
        try:
            _env = []
            from trading.market_temperature_dao import MarketTemperatureDAO
            _t = MarketTemperatureDAO().get_latest() or {}
            if _t.get('temperature') is not None:
                _env.append(
                    f"**市场温度**: {float(_t['temperature']):.1f}°（{_t.get('status') or '-'}）"
                    f" | 建议仓位 {float(_t.get('position_ratio') or 0):.0%}"
                    f" | {_t.get('action') or '-'}")
            from trading.market_index_adx_dao import MarketIndexADXDAO
            # ★★【2026-10-05 修复 ✓】**必须显式指定指数** ✗→✓（同 `web_server` 那处 ✓）★★
            #   `get_latest()` 不传指数 ✗ ⇒ 多指数后会取到**任意一行** ✗✓（飞书里数字与文案不符 ✗）。
            #   ⇒ 显式指定 ✓，且与大盘闸门/仓位上限**同一指数** ✓；并把指数代码**写进通知** ✓。
            from trading.index_adx_filter import resolve_index_adx_code
            _idx = resolve_index_adx_code()
            _a = MarketIndexADXDAO().get_latest(_idx) or {}
            if _a.get('adx') is not None:
                _chg = _a.get('adx_change')
                _chg_txt = '' if _chg is None else f"（环比 {float(_chg):+.2f}）"
                # ★【2026-10-07 ✓】补上**该行是哪一天的** ✗→✓（多指数/跨日后
                #   "数字与日期不符"是同类事故的根源 ✗ —— 见 `test_market_adx_multi_index` ✓）
                _d_txt = (f" @{_a.get('trade_date')}" if _a.get('trade_date') else '')
                _env.append(
                    f"**市场ADX(14)**[{_idx}]{_d_txt}: {float(_a['adx']):.1f}{_chg_txt}"
                    f"（{_a.get('trend_strength') or '-'} · {_a.get('trend_direction') or '-'}）"
                    f" ← **行情库最新** ✓（**展示用** ✓，非判定口径 ✗）")
            if _env:
                lines.append("### 市场环境 📊")
                lines.extend(_env)
                lines.append("")
        except Exception as e:
            logger.debug(f"飞书日报：市场温度/ADX 读取失败（忽略，不影响日报）: {e}")

        # ★★★★【2026-10-07 用户要求 ✓】新增「大盘 ADX + 当日仓位上限判定」✗→✓ ★★★★
        #   用户原话 ✓："**飞书信息上增加大盘adx和当日仓位上限判定信息**" ✓
        #   ⚠️ 口径铁律 ✗✓（本项目大忌：**看到的 ≠ 按它判的** ✗）：
        #     · 直接调**判定函数本身** `index_position_cap()` ✓（**绝不另写一套** ✗）
        #       ⇒ 拿到的 `adx / dir / band / state_date / cap / rule` 就是"开新仓时按它判的那一份" ✓；
        #     · 时点按**实盘** ✓（**信号日当天收盘** ✓ —— 与 `strategy_runner` 的注入一致 ✓），
        #       但**尊重 yaml 显式配置** ✓（写 `false` ⇒ 取前一根 ✓，供 A/B ✓）；
        #     · ⚠️ 取不到（无数据/异常）⇒ 只打 `-` ✓ 并**如实标注**，绝不编数 ✗（也不阻断日报 ✓）。
        try:
            from trading.index_adx_filter import (
                DEFAULT_CAP_USE_SIGNAL_DAY, any_board_release,
                index_position_cap, resolve_cap_use_signal_day)
            from utils.backtest_mode import is_explicit
            _capcfg = {}
            try:
                if not is_explicit('index_cap_use_signal_day', None, None):
                    _capcfg['index_cap_use_signal_day'] = DEFAULT_CAP_USE_SIGNAL_DAY
            except Exception:                     # 判显式失败 ⇒ 按实盘默认注入 ✓（不因此丢块 ✗）
                _capcfg['index_cap_use_signal_day'] = DEFAULT_CAP_USE_SIGNAL_DAY
            _td8 = today.strftime('%Y%m%d')
            _cap = index_position_cap(_td8, _capcfg) or {}
            _cl = []
            _adv = _cap.get('adx')
            _adv_txt = '-' if _adv is None else f'{float(_adv):.2f}'
            _cl.append(f"**大盘ADX(14)**[{_cap.get('index_code') or '-'}]: {_adv_txt}"
                       f"（{_cap.get('band') or '-'} · 方向={_cap.get('dir') or '未定'}）"
                       f" ← ★**判定用** ✓（与买入闸门**同源同口径** ✓）"
                       f"；⚠️ 与上行「市场ADX」可能**方向不同** ✗"
                       f"（那行取自**行情库列** ✓：展示口径 ✗）")
            # ★【2026-10-07 ✓】"口径"之后**必须带实际判定日** ✓；若因**当日无数据**而回退
            #   （非交易日 / 未采集 ✓）⇒ **显式写出回退** ✗→✓（否则读者会以为用的是当天 ✗✓）
            _sd = str(_cap.get('signal_date') or '')
            _st = str(_cap.get('state_date') or '')
            _fb = (f'；⚠️ 信号日 {_sd} 无数据 ⇒ **实际取 {_st}** ✓（不编数 ✗）'
                   if (_sd and _st and _sd != _st) else '')
            _cl.append(f"**判定日**: {_st or '-'} | **口径**: "
                       + ('信号日当天收盘 ✓' if resolve_cap_use_signal_day(_capcfg)
                          else '前一根 ✓') + _fb)
            _cap_v = float(_cap.get('cap') or 0.0)
            _cl.append(f"**当日仓位上限**: {_cap_v:.0%}（{_cap.get('rule') or '-'}）")
            if _cap.get('error'):                 # ⚠️ 取数异常也**如实打** ✓（不静默 ✗）
                _cl.append(f"⚠️ {_cap['error']}")
            if _cap_v <= 0.0:                     # ★ 0% ⇒ **一律不开新仓** ✓（**加仓不受限** ✓）
                try:
                    _rel = bool(any_board_release(_td8, _capcfg))
                except Exception:
                    _rel = False
                _cl.append('**结论**: 不开新仓 ✗（**加仓不受限** ✓）；'
                           + ('★ 板块回退：**仅对应板块**可买 ✓（⚠️ **双创同时放行 ⇒ 整体不放行** ✗✓）'
                              if _rel else '**整体不放行** ✗（含双创 ✓）'))
            else:
                _cl.append('**结论**: 允许开新仓 ✓；**持仓 ≥ 上限 ⇒ 停止开新仓** ✓'
                           '（⚠️ 加仓不受本规则限制 ✓）')
            lines.append("### 仓位上限（大盘档位）📉")
            lines.extend(_cl)
            lines.append("")
        except Exception as e:
            logger.debug(f"飞书日报：仓位上限/大盘ADX 读取失败（忽略，不影响日报）: {e}")

        # 各步骤详情
        for step in result.steps:
            step_dur = self._format_duration(step.duration_seconds)
            emoji = "✅" if step.status == "success" else ("❌" if step.status == "failed" else "⚠️")
            lines.append(f"### {step.step_name} {emoji} (耗时: {step_dur})")

            # 根据步骤名展示详情
            if step.step_name == "data_update" and step.details:
                lines.append(self._format_data_update_details(step.details))
            elif step.step_name == "strategy_run" and step.details:
                lines.append(self._format_strategy_run_details(step.details))
            elif step.step_name == "notification" and step.details:
                lines.append(self._format_notification_details(step.details))

            if step.error:
                lines.append(f"**错误**: {step.error}")
            lines.append("")

        # 整体状态
        status_emoji = "✅" if result.status == "success" else ("⚠️" if result.status == "partial_failure" else "❌")
        lines.append(f"**整体状态**: {status_emoji} {result.status}")

        return "\n".join(lines)

    def _build_alert_markdown(self, result: PipelineResult) -> str:
        """
        构建异常告警 Markdown 内容

        格式参考设计文档 7.2.3 节
        """
        from datetime import date
        today = date.today()

        lines = [
            f"**日期**: {today} | **状态**: {result.status}",
            "",
        ]

        # 各步骤状态
        for step in result.steps:
            emoji = "✅" if step.status == "success" else ("❌" if step.status == "failed" else "⚠️")
            err_info = f" - 错误: {step.error}" if step.error else ""
            lines.append(f"### {step.step_name} {emoji}{err_info}")

        return "\n".join(lines)

    def _format_duration(self, seconds: float) -> str:
        """将秒数格式化为人类可读的耗时字符串"""
        if seconds < 60:
            return f"{seconds:.0f}秒"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}分{secs}秒"

    def _format_data_update_details(self, details: dict) -> str:
        """格式化数据更新步骤详情
        
        details 键名须与 pipeline_orchestrator._step_data_update 中写入的字段一致：
        kline_added/updated/failed, fund_flow_added/updated,
        new_stock_detected/initialized, market_cap_updated, already_updated
        """
        parts = []
        # K线更新统计
        k_added = details.get("kline_added", 0)
        k_updated = details.get("kline_updated", 0)
        k_failed = details.get("kline_failed", 0)
        if k_added or k_updated:
            parts.append(f"- K线更新: 新增 {k_added} 只, 更新 {k_updated} 只"
                         + (f", 失败 {k_failed} 只" if k_failed else ""))
        elif k_failed:
            parts.append(f"- K线更新: 失败 {k_failed} 只")
        # 资金流向更新
        ff_added = details.get("fund_flow_added", 0)
        ff_updated = details.get("fund_flow_updated", 0)
        if ff_added or ff_updated:
            parts.append(f"- 资金流向: 新增 {ff_added} 只, 更新 {ff_updated} 只")
        # 新股检测与初始化
        ns_detected = details.get("new_stock_detected", 0)
        ns_init = details.get("new_stock_initialized", 0)
        if ns_detected or ns_init:
            parts.append(f"- 新股: 检测 {ns_detected} 只, 初始化 {ns_init} 只")
        # 市值更新
        mc_updated = details.get("market_cap_updated", 0)
        if mc_updated:
            parts.append(f"- 市值更新: {mc_updated} 只")
        # 当日已完成更新标记
        if details.get("already_updated"):
            parts.append("- 今日已更新过，跳过重复更新")
        # 被跳过标记
        if details.get("skipped"):
            parts.append("- 数据源未就绪，已跳过")
        return "\n".join(parts) if parts else "- 无详情"

    def _format_strategy_run_details(self, details: dict) -> str:
        """格式化策略运行步骤详情
        
        包含：可用资金、总资产、选股/择时策略、信号日期、详细信号信息
        所有策略名称统一转换为中文显示
        """
        from utils.strategy_name_mapper import get_chinese_name, get_chinese_timing_name
        
        # 异常终止时只显示错误信息，不显示默认资金数据
        error_msg = details.get("error_message", "")
        if error_msg:
            return f"**执行异常终止**: {error_msg}"

        parts = []
        # 资金信息
        avail_cash = details.get("available_cash", 0)
        total_assets = details.get("total_assets", 0)
        if avail_cash is not None:
            parts.append(f"**资金**: 可用 ¥{avail_cash:,.2f} | 总资产 ¥{total_assets:,.2f}")
        
        # 策略信息（转换为中文）
        strategies = details.get("selection_strategies", [])
        timing = details.get("timing_strategy", "")
        if strategies or timing:
            cn_strategies = [get_chinese_name(s) for s in strategies]
            cn_timing = get_chinese_timing_name(timing)
            strategy_text = ", ".join(cn_strategies) if cn_strategies else "无"
            parts.append(f"**策略**: 选股 [{strategy_text}] | 择时 [{cn_timing}]")
        
        # 信号日期和数量
        signal_date = details.get("signal_date", "未知")
        parts.append(f"**信号日期**: {signal_date}")
        
        buy_count = details.get("buy_signals", 0)
        sell_count = details.get("sell_signals", 0)
        parts.append(f"**信号统计**: 买入 {buy_count} 条 | 卖出 {sell_count} 条")
        
        # 买入信号详情
        buy_items = details.get("buy_signal_items", [])
        if buy_items:
            buy_lines = ["**买入信号详情**:"]
            for i, sig in enumerate(buy_items, 1):
                code = sig.get("stock_code", "")
                name = sig.get("stock_name", "")
                price = sig.get("price", 0)
                qty = sig.get("quantity", 0)
                amount = sig.get("amount", 0)
                trade_type = sig.get("trade_type", "")
                type_tag = "加仓" if trade_type == "add" else "首仓"
                cn_strategy = get_chinese_name(sig.get("strategy_name", ""))
                buy_lines.append(
                    f"  {i}. {name}({code}) {type_tag} [{cn_strategy}]: "
                    f"¥{price:.2f} × {qty}股 = ¥{amount:,.0f}"
                )
            parts.append("\n".join(buy_lines))
        
        # 卖出信号详情
        sell_items = details.get("sell_signal_items", [])
        if sell_items:
            sell_lines = ["**卖出信号详情**:"]
            for i, sig in enumerate(sell_items, 1):
                code = sig.get("stock_code", "")
                name = sig.get("stock_name", "")
                price = sig.get("price", 0)
                qty = sig.get("quantity", 0)
                amount = sig.get("amount", 0)
                cn_strategy = get_chinese_name(sig.get("strategy_name", ""))
                sell_lines.append(
                    f"  {i}. {name}({code}) [{cn_strategy}]: "
                    f"¥{price:.2f} × {qty}股 = ¥{amount:,.0f}"
                )
            parts.append("\n".join(sell_lines))
        
        # 【2026-09-24】股票池变动（新增/移除的**整体情况 + 明细**）✓
        pool_block = self._format_pool_change_details(details)
        if pool_block:
            parts.append(pool_block)

        # 信号文件
        if details.get("signal_file"):
            parts.append(f"信号文件: {details['signal_file']}")
        
        return "\n".join(parts) if parts else "- 无详情"

    # ==================== 【2026-09-24】股票池变动（新增/移除） ====================
    POOL_DETAIL_LIMIT = 20          # 明细最多逐条展示条数（超出提示看本地日报 ✓）
    # 说明：移除原因归类与"原因分布"统计**统一放在 `trading/pool_entry_rules.py`** ✓
    #   （`classify_pool_removal_reason` / `summarize_pool_removal_reasons` ✓），
    #   与本地 Markdown 日报**共用同一实现** ✓，避免两处各写一份而漂移 ✗

    def _format_pool_change_details(self, details: dict) -> str:
        """股票池变动 → **整体情况 + 明细**（飞书简报新增节 ✓）

        整体：池内合计 / 新增（选股 + 持仓回池）/ 移除 / **移除原因分布**
        明细：新增逐条（来源/策略/支撑位）、移除逐条（持有天数/收盘价/原因）

        数据来源：`StrategyRunner.run_strategies_batch` 返回的
                 `data['pool_added_items'] / data['pool_removed_items']`
                 （由 `pipeline_orchestrator._step_strategy_run` 透传进 details ✓）
        """
        from utils.strategy_name_mapper import get_chinese_name

        added = list(details.get("pool_added_items") or [])
        removed = list(details.get("pool_removed_items") or [])
        pool_count = details.get("pool_count", 0)

        if not added and not removed:
            # 无变动也给出池内合计 ✓（仅一行，不占版面 ✓）
            return (f"**股票池变动**: 池内合计 {pool_count} 只 | 今日无新增、无移除"
                    if pool_count else '')

        # ---- 整体情况 ----
        sel_n = details.get("pool_added_selection_count", 0)
        hold_n = details.get("pool_added_holding_count", 0)
        if not sel_n and not hold_n:
            sel_n = sum(1 for x in added if x.get('source') != 'holding')
            hold_n = len(added) - sel_n
        lines = [f"**股票池变动**: 池内合计 {pool_count} 只 | "
                 f"新增 {len(added)} 只（选股 {sel_n} + 持仓回池 {hold_n}）| "
                 f"移除 {len(removed)} 只"]

        # ---- 移除原因分布（整体统计 ✓；归类实现与本地日报**共用** ✓）----
        if removed:
            from trading.pool_entry_rules import summarize_pool_removal_reasons
            counts = summarize_pool_removal_reasons(
                [it.get('reason', '') for it in removed])
            if counts:
                dist = " | ".join(f"{k} {v} 只" for k, v in
                                  sorted(counts.items(), key=lambda kv: -kv[1]))
                lines.append(f"**移除原因分布**: {dist}")

        # ---- 新增明细 ----
        if added:
            lines.append(f"**新增明细**（{len(added)} 只）:")
            for i, it in enumerate(added[:self.POOL_DETAIL_LIMIT], 1):
                src = '持仓回池' if it.get('source') == 'holding' else '选股'
                raw_strategy = it.get('strategy', '') or ''
                cn_strategy = get_chinese_name(raw_strategy) or raw_strategy
                sup = it.get('support_level', 0) or 0
                sup_txt = f" 支撑 ¥{sup:.2f}" if sup else ""
                lines.append(f"  {i}. {it.get('name', '')}({it.get('code', '')}) "
                             f"[{src}/{cn_strategy}]{sup_txt}")
            if len(added) > self.POOL_DETAIL_LIMIT:
                lines.append(f"  …其余 {len(added) - self.POOL_DETAIL_LIMIT} 只见本地日报")

        # ---- 移除明细 ----
        if removed:
            lines.append(f"**移除明细**（{len(removed)} 只）:")
            for i, it in enumerate(removed[:self.POOL_DETAIL_LIMIT], 1):
                hold = it.get('hold_days')
                hold_txt = f" 持{hold}日" if hold is not None else ""
                price = it.get('price')
                price_txt = f" 收盘 ¥{price:.2f}" if price else ""
                reason = it.get('reason', '') or '—'
                lines.append(f"  {i}. {it.get('name', '')}({it.get('code', '')})"
                             f"{hold_txt}{price_txt} | 原因: {reason}")
            if len(removed) > self.POOL_DETAIL_LIMIT:
                lines.append(f"  …其余 {len(removed) - self.POOL_DETAIL_LIMIT} 只见本地日报")

        return "\n".join(lines)

    def _format_notification_details(self, details: dict) -> str:
        """格式化通知步骤详情"""
        parts = []
        if details.get("feishu_sent", False):
            parts.append("- 飞书通知: 已发送")
        return "\n".join(parts) if parts else "- 无详情"

    # ---- 发送核心逻辑 ----

    def _send(self, title: str, content: str) -> bool:
        """
        发送消息，优先使用 App API 方式，失败回退到 webhook

        参数:
            title: 卡片标题
            content: Markdown 内容

        返回:
            发送成功返回 True
        """
        # 优先尝试 App API 方式
        if self._has_valid_api_config():
            if self._send_via_api(title, content):
                return True
            logger.warning("App API 发送失败，尝试 webhook 兜底")

        # 回退到 webhook 方式
        if self._has_valid_webhook_config():
            return self._send_via_webhook(title, content)

        logger.error("飞书通知：无可用发送方式")
        return False

    def _send_via_api(self, title: str, content: str) -> bool:
        """
        通过飞书 API 发送消息

        1. 获取 tenant_access_token
        2. 构建 interactive 卡片
        3. POST 到消息发送接口

        需要 chat_id 配置。
        """
        if not self.chat_id:
            logger.error("飞书 API 方式缺少 chat_id 配置")
            return False

        # 获取 token
        token = self._get_tenant_access_token()
        if not token:
            return False

        # 构建卡片消息体
        card_body = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {"tag": "markdown", "content": content}
            ],
        }

        try:
            # 飞书 API 消息体格式: content 需要 JSON 字符串
            resp = requests.post(
                FEISHU_MSG_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "receive_id": self.chat_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card_body),
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("飞书消息发送失败: code=%s, msg=%s",
                             data.get("code"), data.get("msg"))
                return False

            logger.info("飞书消息发送成功 (API) - message_id=%s", data.get("data", {}).get("message_id"))
            return True

        except requests.RequestException as e:
            logger.error("飞书 API 发送网络异常: %s", e)
            return False
        except (ValueError, KeyError) as e:
            logger.error("飞书 API 响应解析异常: %s", e)
            return False

    def _send_via_webhook(self, title: str, content: str) -> bool:
        """
        通过飞书 webhook 发送消息（兜底方案）

        使用 HMAC-SHA256 签名机制:
          1. 计算 timestamp
          2. sign = base64(hmac_sha256(secret, timestamp + '\n' + secret))
          3. POST 到 webhook_url
        """
        if not self.webhook_url:
            return False

        # 计算签名
        timestamp = str(int(time.time()))
        sign = ""
        if self.signing_secret:
            string_to_sign = f"{timestamp}\n{self.signing_secret}"
            sign = base64.b64encode(
                hmac.new(
                    self.signing_secret.encode(),
                    string_to_sign.encode(),
                    hashlib.sha256,
                ).digest()
            ).decode()

        # 构建卡片消息体
        body = {
            "timestamp": timestamp,
            "sign": sign,
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue",
                },
                "elements": [
                    {"tag": "markdown", "content": content}
                ],
            },
        }

        try:
            resp = requests.post(self.webhook_url, json=body, timeout=10)
            data = resp.json()
            # webhook 成功返回 {"code": 0}
            if resp.status_code != 200 or data.get("code") != 0:
                logger.error("飞书 webhook 发送失败: http=%s, code=%s, msg=%s",
                             resp.status_code, data.get("code"), data.get("msg"))
                return False

            logger.info("飞书消息发送成功 (webhook)")
            return True

        except requests.RequestException as e:
            logger.error("飞书 webhook 发送网络异常: %s", e)
            return False
        except (ValueError, KeyError) as e:
            logger.error("飞书 webhook 响应解析异常: %s", e)
            return False

    # ---- 辅助方法 ----

    def get_chat_id(self) -> Optional[str]:
        """
        获取 bot 所在的群聊列表，返回第一个群聊 ID

        用于自动发现 chat_id，需要 im:chat 权限。

        返回:
            第一个群聊的 chat_id，失败返回 None
        """
        token = self._get_tenant_access_token()
        if not token:
            return None

        try:
            resp = requests.get(
                FEISHU_CHAT_LIST_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={"page_size": 10},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("获取群聊列表失败: code=%s, msg=%s",
                             data.get("code"), data.get("msg"))
                return None

            items = data.get("data", {}).get("items", [])
            if items:
                chat_id = items[0]["chat_id"]
                logger.info("发现群聊: name=%s, chat_id=%s",
                            items[0].get("name", "未知"), chat_id)
                return chat_id

            logger.warning("未发现任何群聊，请确认 bot 已添加到群中")
            return None

        except requests.RequestException as e:
            logger.error("获取群聊列表网络异常: %s", e)
            return None

    @classmethod
    def from_config(cls, config: dict) -> "FeishuNotifier":
        """
        从配置字典创建 FeishuNotifier 实例

        参数:
            config: 完整配置字典 (config.yaml 加载结果)

        返回:
            FeishuNotifier 实例
        """
        feishu = config.get("feishu", {})

        return cls(
            app_id=feishu.get("app_id"),
            app_secret=feishu.get("app_secret"),
            webhook_url=feishu.get("webhook_url"),
            signing_secret=feishu.get("signing_secret", feishu.get("secret")),
            chat_id=feishu.get("chat_id"),
            alert_only=feishu.get("alert_only", False),
        )
