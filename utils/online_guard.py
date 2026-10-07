# -*- coding: utf-8 -*-
"""离线闸门：回测进程内**禁止一切在线调用** ✓（2026-09-25 定稿）

背景与原则：
  · 回测必须**完全离线**（无任何在线例外 ✗）—— 交易日历也只在"每日数据更新"流程中刷新 ✓
  · 数据一旦依赖在线接口，就会被上游修订/限流/改版影响 → **结果漂移且无痕** ✗
    （已实证：`002372 @ 2026-01-20` 资金面得分 16.5 vs 76.0 ✗）
  · 因此：**宁可失败，也不静默漂移** —— 离线模式下任何在线取数都**直接抛错** ✗

用法：
    from utils.online_guard import offline_mode, guard_online_call

    with offline_mode('回测'):
        ...                     # 其间的在线调用会抛错 ✓

    def _fetch_from_tushare(...):
        guard_online_call('Tushare moneyflow_dc 取数')   # 每个在线入口加一行检查点 ✓
        ...
"""

import functools
import logging
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_state: Dict = {
    'enabled': False,
    'reason': '',
    'enabled_at': None,
    'violations': [],      # [{what, at}] —— 便于事后审计 ✓
}


def enable_offline_mode(reason: str = 'backtest') -> None:
    """开启离线模式（幂等 ✓）

    ⚠️ **回测过程全部禁止** ✗（2026-09-25 用户契约 ✓）：一旦开启，期间**一切**在线调用
    都会被拦 ✗（`allow=True` 也不例外 ✓）。
    `KHUNTER_OFFLINE_GUARD=0` 会让**本函数不生效** ✗ —— 于是回测入口的
    `require_offline()` 自检会**拒绝运行回测** ✗✓（"放弃保护"= 不能跑回测 ✓，
     绝不能出现"回测在无保护下静默联网"✗）。
    """
    if _disabled_by_env():
        logger.error('⛔ `KHUNTER_OFFLINE_GUARD=0` ⇒ **离线保护被禁用** ✗ —— '
                     '本函数不会开启离线模式 ✓；回测入口将**拒绝运行** ✗'
                     '（请去掉该环境变量后再跑回测 ✓）')
        return
    with _lock:
        if not _state['enabled']:
            _state['enabled'] = True
            _state['reason'] = reason
            _state['enabled_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f'【离线闸门】已开启 ✓ 原因={reason}'
                        f'（期间**一切**在线取数都会直接失败 ✗，无例外 ✓）')


def disable_offline_mode() -> None:
    """关闭离线模式（幂等 ✓）"""
    with _lock:
        if _state['enabled']:
            logger.info(f'【离线闸门】已关闭（原因={_state["reason"]}，'
                        f'违规 {len(_state["violations"])} 次）')
        _state['enabled'] = False
        _state['reason'] = ''


def is_offline() -> bool:
    """当前是否处于离线模式"""
    return bool(_state['enabled'])


#: ★★【2026-10-07 用户要求 ✓】**"数据源无权限"的识别词** ✗→✓ ★★
#:   用户原话 ✓："**注意部分数据依赖 tushare 数据源，没有对应数据源权限时，自动跳过，避免中断**" ✓
#:   ⚠️ 为什么要"识别"而不是"照抛" ✗✓：Tushare 的权限不足**不是故障** ✓ ——
#:     它是"这个账号没买这个接口"✓（如 `fina_indicator_vip` 需积分 ✓、`limit_list_d` 需 5000 积分 ✓、
#:     `ths_daily` 需 6000 积分 ✓）⇒ 每个用户的可用接口**天然不同** ✓
#:     ⇒ 初始化/日更必须"**跳过并继续**"✓，否则一个没买的接口会让**整条流水线中断** ✗✗
#:     （= 用户点名要避免的行为 ✓）。
#:   ⚠️ 但**绝不是静默** ✗：调用方必须**如实记日志 + 记结果**（`skipped` ✓），
#:     与"离线闸门直接抛错"是**两码事** ✓ —— 那条是"回测不许联网"✓（用户契约 ✓），这条是"没权限也别死"✓。
PERMISSION_HINTS = (
    '没有权限', '无权限', '权限不足', '积分不足', '积分', '抱歉',
    'permission', 'not authorized', 'unauthorized', 'forbidden',
    'insufficient', '40203', 'access denied', 'no access',
)


def is_permission_error(err) -> bool:
    """★ 判断某个异常/文案是否属于"**数据源无权限**"✓（供初始化/日更"**跳过而不中断**"✓）

    用法 ✓：
        try:
            ...
        except Exception as e:
            if is_permission_error(e):
                log('⏭ 跳过（数据源无权限 ✓）')      # ★ 必须**留痕** ✗
            else:
                raise / 记为失败

    ⚠️ 判据只做**保守**的关键词匹配 ✓：宁可把"真故障"当权限（⇒ 跳过 ✓ 有日志 ✓）
      也不要把"权限不足"当故障 ✗（⇒ 整条流水线中断 ✗，正是用户要避免的 ✗）。
    """
    if err is None:
        return False
    try:
        text = str(err)
    except Exception:
        return False
    low = text.lower()
    for h in PERMISSION_HINTS:
        if h.lower() in low:
            return True
    return False


def violations() -> List[Dict]:
    """离线模式期间的在线调用违规记录 ✓（审计用）"""
    return list(_state['violations'])


def reset_violations() -> None:
    with _lock:
        _state['violations'] = []


#: 用途常量 ✓
PURPOSE_SCORE = 'score'      #: 评分 / 回测读路径 → **永远禁止联网** ✗（不依赖 offline_mode ✓）
PURPOSE_UPDATE = 'update'    #: 数据更新 / 初始化 → **合法联网** ✓


def _score_local_only() -> bool:
    """评分链路是否**只读本地** ✓（默认 True ✓ = 用户契约 "评分不再即时联网" ✗）

    可临时关闭：`KHUNTER_SCORE_LOCAL_ONLY=0` ✓（⚠️ 会使评分结果**不可复现** ✗，仅排查用 ✓）
    """
    import os
    v = str(os.environ.get('KHUNTER_SCORE_LOCAL_ONLY', '')).strip().lower()
    if v in ('0', 'false', 'no', 'off'):
        if not _state.get('score_warned'):
            _state['score_warned'] = True
            logger.warning('⚠ `KHUNTER_SCORE_LOCAL_ONLY=0` ⇒ 评分链路已**允许联网** ✗ —— '
                           '评分/回测结果**不再保证可复现** ✗（仅临时排查 ✓）')
        return False
    return True


def _disabled_by_env() -> bool:
    """`KHUNTER_OFFLINE_GUARD=0` ⇒ **显式关闸** ✓（平滑升级的"逃生口" ✓）

    用途：已使用用户在升级后若因某处遗留在线取数而跑不动回测 ✗，
    可先用它**临时**恢复"联网回测" ✓（首次生效时打印**醒目告警** ✗），
    以便继续工作；随后再按报错提示把该数据本地化 ✓。
    ⚠️ 关闸期间结果**不再保证可复现** ✗，请勿用于正式结论 ✓。
    """
    import os
    v = str(os.environ.get('KHUNTER_OFFLINE_GUARD', '')).strip().lower()
    if v in ('0', 'false', 'no', 'off'):
        if not _state.get('env_warned'):
            _state['env_warned'] = True
            logger.warning('⚠ `KHUNTER_OFFLINE_GUARD=0` ⇒ **离线闸门已被人为关闭** ✗ —— '
                           '回测期间允许联网取数，结果**不再保证可复现** ✗'
                           '（仅用于临时排查 ✓，正式跑请去掉该环境变量 ✓）')
        return True
    return False


def guard_online_call(what: str, allow: bool = False,
                      purpose: str = PURPOSE_SCORE) -> None:
    """在线调用前的检查点 ✓（**两道闸门** ✓）

    ① **评分链路只读本地** ✗（2026-09-25 用户契约 ✓）
         `purpose='score'`（**默认** ✓ 安全默认 ✓）⇒ **任何模式**下都不许联网 ✗ ——
         不依赖 `offline_mode` ✓，因此在**实盘/盘后评分**里同样生效 ✓。
         缺数据时**明确报错** ✗ 并提示"请先运行数据更新" ✓（不再静默联网导致结果漂移 ✗）。
    ② **回测离线** ✗（原有）
         `purpose='update'` 且处于离线模式时才拦截 ✗（数据更新流程允许联网 ✓）。

    Args:
        what: 调用描述（报错与审计用 ✓）
        allow: 显式放行（旧参数 ✓，保留兼容 ✓；新代码请用 `purpose` ✓）
        purpose: `'score'`（评分 ✓ 禁 ✗）/ `'update'`（数据更新 ✓ 允许 ✓）

    Raises:
        RuntimeError: 评分链路试图联网 ✗ / 回测离线模式下试图联网 ✗
    """
    # ① 评分链路：**无条件只读本地** ✗✓（除非显式设 KHUNTER_SCORE_LOCAL_ONLY=0 ✓）
    if purpose != PURPOSE_UPDATE and _score_local_only():
        with _lock:
            _state['violations'].append(
                {'what': f'[评分侧] {what}', 'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        raise RuntimeError(
            f'【本地数据闸门】评分/回测**只读本地数据** ✗：{what}\n'
            f'  原因：2026-09-25 起，涉及股票评分的路径**不再即时联网** ✗（避免评分漂移 ✗）\n'
            f'  处理：请先运行"数据更新"把该数据落库 ✓（资金流/基本面/公告/交易日历 ✓）\n'
            f'  临时排查可设 `KHUNTER_SCORE_LOCAL_ONLY=0` ✓（⚠️ 结果不可复现 ✗）')

    # ② **回测离线闸门** ✗：一旦开启，**一切在线调用都被禁止** ✗ —— **无例外** ✓✓
    #    （2026-09-25 用户契约："回测过程全部禁止" ✗）
    #    · `purpose='update'` **不能**豁免 ✗（它只豁免①评分禁网）
    #    · `allow=True` **也不能**豁免 ✗✓（旧逃生口已取消 ✓ —— 否则"顺手更新"即可绕过 ✗）
    #    · 想放弃保护只有一条路 ✓：让 `enable_offline_mode` 不生效 ✗
    #      ⇒ 回测入口的 `require_offline()` 会**拒绝运行回测** ✗（不会静默联网 ✗）
    if not _state['enabled']:
        return
    with _lock:
        _state['violations'].append(
            {'what': what, 'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    raise RuntimeError(
        f'【离线闸门】**回测过程禁止一切在线调用** ✗（无例外 ✓）：{what}\n'
        f'  说明：回测只读本地数据 ✓；数据采集/更新请**在回测之外**执行 ✓\n'
        f'  若确有数据缺失，请先跑"数据更新"补齐后再回测 ✓')


def online_blocked(purpose: str = PURPOSE_SCORE) -> Optional[str]:
    """**预判**：该用途的在线调用**是否会被本闸门拦下** ✓（拦 ⇒ 返回原因 ✓；放行 ⇒ None ✓）

    ★【2026-09-28 新增 ✓】动机 ✗✓（用户实测日志 ✓）：调用方（如减持计划缓存刷新 ✓）
      在"本地数据不足"时会**回退在线 + 重试退避** ✗ —— 但若本闸门**必然拦截** ✗
      （评分侧只读本地 ✓ / 回测离线 ✓），那 `for attempt in range(3)` + 睡 5/10/15 秒
      纯属**空耗** ✗（实测：**每只股票 ~32 秒** ✗ ⇒ 候选池几十只即把数据更新拖成
      分钟级 ✗，见 `trading/reduce_plan_cache.py:423` 的连续重试 ✗）。

    ⚠️ 与 `guard_online_call` **同一判据** ✗✓（抽公共，防两处判据漂移 ✗）：
      改判据**只改一处** ✓。
    ⚠️ 本函数**不抛错** ✓、**不记违规** ✗（纯预判 ✓）⇒ 真正的拦截与违规审计
      仍由 `guard_online_call` 独家负责 ✓（安全契约不变 ✓）。
    """
    # ① 评分链路：任何模式下都只读本地 ✗（除非显式 KHUNTER_SCORE_LOCAL_ONLY=0 ✓）
    if purpose != PURPOSE_UPDATE and _score_local_only():
        return '评分/回测只读本地数据（不再即时联网）'
    # ② 回测离线闸门：一切在线调用都被拦 ✗（无例外 ✓）
    if _state['enabled']:
        return f'回测离线模式（{_state["reason"]}）'
    return None


def require_offline(what: str = '回测') -> None:
    """自检：**必须**处于离线模式 ✓，否则拒绝继续 ✗（回测入口使用 ✓）

    用途 ✓：即使有人用 `KHUNTER_OFFLINE_GUARD=0` 关掉保护 ✗，
    回测入口也会**拒绝运行** ✗✓ —— 而不是"在无保护下静默联网跑出一个不可复现的结果"✗✓。

    Raises:
        RuntimeError: 离线保护未生效 ✗
    """
    if not _state['enabled']:
        raise RuntimeError(
            f'【离线闸门】{what}被拒绝执行 ✗：离线保护**未生效** ✓\n'
            f'  原因：可能设置了 `KHUNTER_OFFLINE_GUARD=0` ✗（或未调用 enable_offline_mode ✓）\n'
            f'  处理：请去掉该环境变量后重试 ✓ —— 回测**必须**在离线保护下运行 ✗')


def backtest_offline(fn):
    """装饰器 ✓：让回测入口**自动**处于离线保护下 ✓（2026-09-25 契约 ✓）

    背景（实测 ✗✓）：此前生产代码**没有任何地方**开启离线模式 ✗ ——
    "回测禁止联网"实际**从未生效** ✗；现由引擎**自己**在入口开启 ✓（不依赖调用方 ✓），
    退出时自动恢复 ✓（`offline_mode` 支持嵌套 ✓）。
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with offline_mode(f'回测:{fn.__name__}'):
            require_offline(fn.__name__)      # 自检 ✓：保护未生效则拒绝运行 ✗
            return fn(*args, **kwargs)
    return wrapper
    with _lock:
        _state['violations'].append(
            {'what': what, 'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    raise RuntimeError(
        f'【离线闸门】禁止在线调用：{what}\n'
        f'  原因：当前处于离线模式（{_state["reason"]}）—— 回测必须只读本地数据 ✓\n'
        f'  处理：请先运行"数据更新"把所需数据落库（资金流/基本面/事件/交易日历），'
        f'或确认该调用是否属于数据更新流程（如是，需显式 allow=True）')


@contextmanager
def offline_mode(reason: str = 'backtest'):
    """上下文管理器：进入即开启离线模式，退出自动关闭 ✓

    用法：
        with offline_mode('回测'):
            engine.run_backtest(...)
    """
    already = is_offline()
    if not already:
        enable_offline_mode(reason)
    try:
        yield
    finally:
        if not already:
            disable_offline_mode()


def state() -> Dict:
    """当前闸门状态快照（测试/审计用 ✓）"""
    return {'enabled': _state['enabled'], 'reason': _state['reason'],
            'enabled_at': _state['enabled_at'], 'violations': violations()}


def require_local_data(what: str, available: bool, detail: str = '') -> None:
    """要求"本地数据可用"否则报错 ✓（用于本地取数路径的显式校验）

    Args:
        what: 数据名称（如 '资金流向(5日)'）
        available: 本地数据是否满足（含完整性 ✓）
        detail: 缺失说明（表/日期/股票清单 ✓）
    """
    if available:
        return
    raise RuntimeError(
        f'【数据缺失】{what} 本地数据不满足回测要求 ✗\n'
        f'  {detail}\n'
        f'  处理：请先运行数据更新/初始化把该数据补齐（回测不联网 ✗）')


def get_last_error_detail() -> Optional[str]:
    """最近一次违规描述（便于上层拼接报错）"""
    v = violations()
    return v[-1]['what'] if v else None
