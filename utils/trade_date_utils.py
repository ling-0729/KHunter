# -*- coding: utf-8 -*-
"""
交易日工具模块

提供判断日期是否为交易日的功能。
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import List, Optional, Tuple

# 配置日志记录器
logger = logging.getLogger(__name__)


# 交易日历本地缓存（模块级，进程内全局复用）
_trading_calendar_cache: set = None
_CACHE_FILE = None

# 【2026-09-25 加固】写缓存互斥锁（进程内）+ 权威日历进程内缓存
#   背景：此前"读缓存 → 并入 → 整体覆盖写"三处各自实现（本模块 / backtest_engine /
#   数据更新脚本），无锁、非原子、无"拒绝缩水"保护 ✗ ——
#   并发写或读到半截 JSON 时会把 912 日的缓存**缩水**成少量日期，且全程**静默** ✗。
#   本模块统一收口为：进程内锁 + 临时文件原子替换 + 只增不减 + 权威源校验 ✓
_CACHE_LOCK = threading.RLock()
_AUTHORITY_CACHE = {'dates': None, 'fetched_at': 0.0}
_AUTHORITY_TTL = 6 * 3600  # 权威日历进程内缓存 6 小时

#: ★【2026-09-27 用户口径】权威日历**只保留最近 N 年** ✓
#:   · 原行为 ✗：直接吃 `ak.tool_trade_date_hist_sina()` 全量（**1990-12-19 起 8797 日** ✗）
#:   · 动机 ✗✓：系统回测/校验只涉及近年 ✓ ⇒ 全量列表在**内存 / 校验 / 日志**上都无谓 ✗
#:   · ⚠️ 该接口**只提供全量** ✗（无法按区间下载 ✗）⇒ 本常量只裁**保留窗口** ✓，
#:     **网络与接口耗时不变** ✗（仅省内存与日志噪音 ✓）
#:   · ⚠️ 若请求区间**早于**本窗口 ⇒ 权威源无数据 ⇒ 退化为「**无法校验**」✓
#:     （WARNING ✓ **不静默通过** ✓），仍可落到 `tushare` / 本地缓存 ✓
AUTHORITY_YEARS = 3
#: 权威日历**取数互斥** ✓ —— 实测首载会被并发调用 3 次（同秒 3 条相同 INFO ✗）
_AUTHORITY_LOCK = threading.Lock()


def _get_cache_file() -> str:
    """获取交易日历缓存文件路径"""
    from pathlib import Path
    global _CACHE_FILE
    if _CACHE_FILE is None:
        _CACHE_FILE = str(Path(__file__).parent.parent / "data" / "trading_calendar_cache.json")
    return _CACHE_FILE


def _quarantine_corrupt_cache(reason: str) -> Optional[str]:
    """把损坏的缓存文件**隔离备份**（改名而非删除）并返回备份路径

    【2026-09-25 加固】此前读到损坏 JSON 只 `logger.warning` 后返回空集 ✗ ——
    紧接着的"并入 → 覆盖写"会把缓存**清零** ✗。现改为保留现场，便于事后取证。
    """
    from pathlib import Path
    cache_file = Path(_get_cache_file())
    if not cache_file.exists():
        return None
    backup = cache_file.with_suffix(f".corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}.json")
    try:
        cache_file.rename(backup)
        logger.error(f"交易日历缓存文件损坏（{reason}）→ 已隔离备份为 {backup.name}，"
                     f"请检查并重建缓存（缺失日期将由权威日历自动补齐）")
        return str(backup)
    except Exception as e:
        logger.error(f"交易日历缓存文件损坏（{reason}）且隔离失败: {e}")
        return None


def _read_cache_payload() -> dict:
    """读取缓存文件载荷（含元信息，容错）

    Returns:
        dict: {"dates": [...], "updated_at":..., "source":...}；文件不存在返回 {}
    Raises:
        无（损坏情况已隔离备份并返回 {}，由调用方决定后续动作）
    """
    import json
    from pathlib import Path
    cache_file = Path(_get_cache_file())
    if not cache_file.exists():
        return {}
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("dates"), list):
            raise ValueError("缓存载荷结构非法（缺少 dates 列表）")
        return data
    except Exception as e:
        _quarantine_corrupt_cache(str(e))
        return {}


def _load_cache_from_file() -> set:
    """从本地缓存文件加载交易日历到内存（损坏时隔离备份 + 返回空集 ✓）"""
    global _trading_calendar_cache
    data = _read_cache_payload()
    _trading_calendar_cache = set(data.get("dates", [])) if data else set()
    if _trading_calendar_cache:
        logger.debug(f"从本地缓存加载交易日历: {len(_trading_calendar_cache)} 日")
    return _trading_calendar_cache


def _atomic_write_cache(dates, source: str = 'unknown') -> bool:
    """**原子**写回交易日历缓存（临时文件 + os.replace ✓）

    原子替换保证任何时刻读者只会看到"旧完整文件"或"新完整文件"，
    不会再出现读到半截 JSON → 静默清空缓存 ✗ 的情况。

    Args:
        dates: 日期集合/列表（YYYY-MM-DD）
        source: 数据来源标记（tushare / akshare / cache / merge），写入元信息便于取证

    Returns:
        bool: 是否写入成功
    """
    import json
    from pathlib import Path
    cache_file = Path(_get_cache_file())
    sorted_dates = sorted({str(d) for d in dates})
    if not sorted_dates:
        logger.error("拒绝写入空的交易日历缓存（防止把缓存清零 ✗）")
        return False
    payload = {
        "dates": sorted_dates,
        "count": len(sorted_dates),
        "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "source": source,
    }
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, cache_file)      # 原子替换 ✓
        return True
    except Exception as e:
        logger.error(f"写入交易日历缓存失败: {e}")
        return False


def save_trading_dates(dates, source: str = 'unknown', allow_shrink: bool = False) -> bool:
    """合并式保存交易日历（**统一入口**，杜绝"缩水覆盖" ✗）

    规则（2026-09-25 加固）：
      1. 以**文件中的现有内容**为基准做并集（而不信任内存快照 ✗）——
         避免"内存为空/不全 → 覆盖写 → 缓存缩水"这条静默损坏路径 ✗
      2. 只增不减：默认拒绝任何"净减少"的写入 ✗（allow_shrink=True 仅用于人工重建）
      3. 空集永远拒绝写入 ✓

    Args:
        dates: 待并入的日期集合（YYYY-MM-DD）
        source: 来源标记
        allow_shrink: 是否允许净减少（仅人工重建时使用）

    Returns:
        bool: 是否实际写入
    """
    with _CACHE_LOCK:
        existing = set(_read_cache_payload().get("dates", []))
        merged = existing | {str(d) for d in dates}
        if not allow_shrink and len(merged) < len(existing):
            logger.error(f"拒绝写入交易日历缓存：新集合({len(merged)}) 少于现有({len(existing)})，"
                         f"疑似缩水覆盖 ✗（source={source}）")
            return False
        if not merged:
            logger.error("拒绝写入空的交易日历缓存 ✗")
            return False
        if merged == existing:
            logger.debug(f"交易日历缓存无新增（现有 {len(existing)} 日），跳过写入")
            return False
        ok = _atomic_write_cache(merged, source=source)
        if ok:
            global _trading_calendar_cache
            _trading_calendar_cache = merged
            logger.info(f"交易日历缓存已更新: 新增 {len(merged) - len(existing)} 日 → "
                        f"总计 {len(merged)} 日（source={source}）")
        return ok


def _ensure_cache_loaded():
    """确保交易日历缓存已加载到内存（懒加载，空集合时自动重试加载）

    关键修复：模块级 _trading_calendar_cache 可能在缓存文件生成前被初始化为
    空集合（Flask 长驻进程场景），此时需要重新从文件加载。
    """
    global _trading_calendar_cache
    # None 时首次加载
    if _trading_calendar_cache is None:
        cached = _load_cache_from_file()
        if not cached:
            _trading_calendar_cache = set()
        return _trading_calendar_cache
    # 空集合时重试加载（回测引擎可能已生成缓存文件）
    if not _trading_calendar_cache:
        cached = _load_cache_from_file()
        if cached:
            _trading_calendar_cache = cached
            logger.info(f"交易日内存缓存已刷新，加载 {len(cached)} 个交易日")
    return _trading_calendar_cache


def refresh_trading_calendar_cache():
    """强制刷新交易日内存缓存（供回测引擎等上游模块写入缓存文件后调用）"""
    global _trading_calendar_cache
    # 清除 @lru_cache 缓存
    is_trading_day.cache_clear()
    get_trading_days.cache_clear()
    # 重新从文件加载
    _trading_calendar_cache = None
    _ensure_cache_loaded()


def is_trading_day(date_str: str) -> bool:
    """
    判断指定日期是否为交易日

    优先使用本地缓存（data/trading_calendar_cache.json）。
    缓存未命中时回退到 Tushare API，成功则更新缓存。
    均已失败时不再使用周末排除，直接报错。

    注意：不使用 @lru_cache，因模块级 _trading_calendar_cache 已做 set 查找，
    且 @lru_cache 会在缓存文件生成前后返回不一致的过期结果。

    参数:
        date_str: 日期字符串，支持 YYYY-MM-DD 或 YYYYMMDD 格式
    返回:
        bool: 是否为交易日
        
    Raises:
        RuntimeError: 缓存和 Tushare 均不可用
    """
    from pathlib import Path
    
    # 统一日期格式
    if '-' in date_str:
        date_str_fmt = date_str.replace('-', '')
        display_str = date_str
    else:
        date_str_fmt = date_str
        display_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    
    # 1. 优先从内存缓存查找（命中直接返回True）
    _ensure_cache_loaded()
    if _trading_calendar_cache and display_str in _trading_calendar_cache:
        return True
    
    # 1.5 周末快速判断：缓存只存交易日，周六/周日永远不会命中缓存，
    # 若直接回退 Tushare 会在离线（网络异常）时抛 RuntimeError 导致任务失败；
    # 周末必然是非交易日，直接返回 False，保证周末/节假日场景完全离线可用
    try:
        check_date = datetime.strptime(date_str_fmt, '%Y%m%d')
        if check_date.weekday() >= 5:  # 5=周六, 6=周日
            logger.debug(f"{display_str} 是周末，直接判定为非交易日")
            return False
    except ValueError:
        # 日期格式异常时交由后续 Tushare 逻辑处理（调用方应保证格式正确）
        pass

    # 2. 缓存未命中且非周末（工作日或节假日）→ 先用**权威日历**判定 ✓
    #    【2026-09-25 加固】此前直接问 Tushare 单日接口，且"返回空即判非交易日" ✗ ——
    #    遇到限流/异常返回空时会把**真实交易日静默判成非交易日** ✗（上游据此算错
    #    冷却池天数、持仓天数、前一交易日等）。现改为：权威日历优先；确实查不到
    #    任何来源时**报错**，绝不静默返回 False ✓
    authority, auth_src = get_authoritative_dates(display_str, display_str)
    # ★【2026-09-27 修复】权威源**明确回答**"该日无交易"（空列表 ✓，如**周末/节假日** ✓）
    #   时必须**返回 False** ✗ —— 此前把"空"一律当"权威不可用"✗ ⇒ 每逢节假日
    #   （实测 `2026-09-25` 中秋 ✓）都会落到 Tushare ✗ 并因**返回空**再报错 ✗✗。
    #   ⇒ 只有 `cache`/`none`（= **真的无法服务** ✓）才继续走 Tushare ✓。
    if authority or auth_src in ('akshare', 'tushare'):
        if display_str in set(authority):
            save_trading_dates([display_str], source=f'is_trading_day:{auth_src}')
            logger.debug(f"{auth_src} 确认 {display_str} 是交易日")
            return True
        logger.debug(f"{auth_src} 确认 {display_str} 不是交易日（含周末/节假日 ✓）")
        return False

    # 3. 权威日历不可用 → 退回 Tushare 单日查询
    try:
        import json
        from pathlib import Path
        import tushare as ts

        config_path = Path(__file__).parent.parent / "config" / "tushare_config.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                tushare_config = json.load(f)
            token = tushare_config.get('api_key') or tushare_config.get('token')
            if token:
                ts.set_token(token)
        pro = ts.pro_api()
        df = pro.trade_cal(exchange='SSE', start_date=date_str_fmt,
                           end_date=date_str_fmt, is_open='1')
        if df is not None and not df.empty:
            save_trading_dates([display_str], source='is_trading_day:tushare')
            logger.debug(f"Tushare 确认 {display_str} 是交易日")
            return True
        # 返回空 → 不可轻信（可能是限流/接口异常导致的空结果）→ 报错而非静默 False ✗
        raise RuntimeError(
            f"交易日判断不可信: {display_str}\n"
            f"权威日历(akshare)不可用，且 Tushare 单日接口返回空结果（疑似限流或接口异常）。\n"
            f"为避免把真实交易日误判为非交易日，此处直接失败。\n"
            f"缓存路径: {_get_cache_file()}"
        )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(
            f"交易日判断失败: {display_str}\n"
            f"本地缓存未命中，且权威日历(akshare)/Tushare API 均不可用。\n"
            f"缓存路径: {_get_cache_file()}\n"
            f"错误: {e}\n"
            f"请在网络正常时先运行一次回测/数据更新以生成并补全缓存文件。"
        )


def _fetch_tushare_dates(start_str: str, end_str: str) -> Optional[List[str]]:
    """从 Tushare 拉取区间交易日（**统一实现**，避免多处重复）

    Args:
        start_str / end_str: YYYYMMDD

    Returns:
        List[str] 或 None（不可用/失败）；返回列表按升序，格式 YYYY-MM-DD
    """
    try:
        import json
        from pathlib import Path
        import tushare as ts

        config_path = Path(__file__).parent.parent / "config" / "tushare_config.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                tushare_config = json.load(f)
            token = tushare_config.get('api_key') or tushare_config.get('token')
            if token:
                ts.set_token(token)
        pro = ts.pro_api()
        df = pro.trade_cal(exchange='SSE', start_date=start_str, end_date=end_str, is_open='1')
        if df is None or df.empty:
            return None
        dates = sorted({f"{str(r['cal_date'])[:4]}-{str(r['cal_date'])[4:6]}-{str(r['cal_date'])[6:8]}"
                        for _, r in df.iterrows()})
        return dates
    except Exception as e:
        logger.warning(f"Tushare 交易日历获取失败: {e}")
        return None


def _trim_recent_years(dates: List[str], years: int = AUTHORITY_YEARS,
                       today: Optional[str] = None) -> List[str]:
    """只保留**最近 `years` 年**（`>= today − years` ✓，含边界 ✓）

    · `years <= 0` / 空输入 ⇒ **原样返回** ✓（可关闭裁剪 ✓）
    · `today` 可注入 ✓ ⇒ **可单测** ✓（不依赖当前日期 ✓）；非法日期 ⇒ 原样返回 ✓
    · 纯函数 ✓：不触网、不读缓存 ✓
    """
    if not dates or not years or int(years) <= 0:
        return list(dates or [])
    anchor = (today or datetime.now().strftime('%Y-%m-%d'))[:10]
    try:
        d0 = datetime.strptime(anchor, '%Y-%m-%d')
        try:
            # ★ 按**日历年**精确回溯 ✓（不用 `365.25×N` ✗ —— 那会差 1 天 ✗，实测踩过 ✓）
            cut = d0.replace(year=d0.year - int(years))
        except ValueError:            # 2-29 落在非闰年 ✓ ⇒ 收敛到 2-28 ✓
            cut = d0.replace(year=d0.year - int(years), day=28)
        cutoff = cut.strftime('%Y-%m-%d')
    except Exception:
        return list(dates)
    return [d for d in dates if d >= cutoff]


def get_akshare_dates(force: bool = False) -> Optional[List[str]]:
    """获取 **akshare 交易日历**（权威源，无需 token；已含法定节假日）

    用作"完整性基准"：任何来源的区间结果都可与它比对，检出**局部缺日** ✗
    （这是此前 `_calendar_coverage_insufficient` 那种"只看总数占比"判据
      检不出来的失败模式 ✗ —— 本次 2026-01 空洞类问题即属此类）。

    ★【2026-09-27 用户口径 ✓】**只保留最近 `AUTHORITY_YEARS`（3）年** ✓
      —— 接口只提供全量 ✗ ⇒ 收到后**裁窗口** ✓（详见常量注释 ✓）。

    Args:
        force: 是否强制刷新（忽略进程内 6 小时缓存）
        （并发安全 ✓：`_AUTHORITY_LOCK` 双检 ✓，避免首载被并发拉多次 ✗）

    Returns:
        List[str] 或 None（akshare 不可用）
    """
    now = time.time()
    if (not force and _AUTHORITY_CACHE['dates']
            and (now - _AUTHORITY_CACHE['fetched_at']) < _AUTHORITY_TTL):
        return _AUTHORITY_CACHE['dates']
    with _AUTHORITY_LOCK:
        # 双检 ✓：等锁期间别人可能已填好（实测同秒 3 条相同日志 ✗）
        now = time.time()
        if (not force and _AUTHORITY_CACHE['dates']
                and (now - _AUTHORITY_CACHE['fetched_at']) < _AUTHORITY_TTL):
            return _AUTHORITY_CACHE['dates']
        try:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            raw = [str(x) for x in df['trade_date'].tolist()]
            full = sorted({x if '-' in x else f"{x[:4]}-{x[4:6]}-{x[6:8]}" for x in raw})
            if full:
                dates = _trim_recent_years(full, AUTHORITY_YEARS)
                if not dates:              # 极端：窗口内无数据 ⇒ 退回全量 ✓（不空手 ✗）
                    dates = full
                _AUTHORITY_CACHE['dates'] = dates
                _AUTHORITY_CACHE['fetched_at'] = now
                logger.info(f"权威交易日历（akshare）加载完成: {len(dates)} 日 "
                            f"({dates[0]} ~ {dates[-1]}) ✓ —— **只保留最近 "
                            f"{AUTHORITY_YEARS} 年** ✓（原始 {len(full)} 日 / "
                            f"{full[0]} 起 ✗；接口只提供全量 ⇒ 仅裁保留窗口 ✗）")
                return dates
        except Exception as e:
            logger.warning(f"akshare 交易日历不可用（将退回 Tushare/本地缓存校验）: {e}")
        return None


def get_authoritative_dates(start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> Tuple[List[str], str]:
    """按优先级取"权威"交易日列表：akshare → Tushare → 本地缓存

    Args:
        start_date / end_date: YYYY-MM-DD（None 表示不裁剪）

    Returns:
        (dates, source)；source ∈ {'akshare','tushare','cache','none'}
    """
    s8 = start_date.replace('-', '') if start_date else None
    e8 = end_date.replace('-', '') if end_date else None

    def _clip(seq):
        if not seq:
            return []
        if s8 and e8:
            return [d for d in seq if start_date <= d <= end_date]
        return list(seq)

    ak_dates = get_akshare_dates()
    if ak_dates:
        clipped = _clip(ak_dates)
        # ★【2026-09-27】**先判"窗口是否覆盖请求区间"** ✗✓（实测 `2026-09-25` 中秋 ✓）：
        #   · **覆盖** ✓ ⇒ 裁剪结果**就是权威答案** ✓ —— **空也采信** ✓
        #     （区间内确实没有交易日：周末/节假日 ✓；若在此处"空则回退"✗，
        #      就会把**节假日**误判成"权威不可用"✗ ⇒ `is_trading_day` 直接报错 ✗✗）
        #   · **不覆盖**（区间早于窗口 ✗）⇒ akshare **无法服务**该区间 ✓ ⇒ 继续 Tushare ✓
        #     （这是"只保留近 N 年"的必要兜底 ✓）
        _covered = True
        if s8 and e8:
            _covered = (start_date >= ak_dates[0] and end_date <= ak_dates[-1])
        if clipped or _covered:
            return clipped, 'akshare'

    if s8 and e8:
        ts_dates = _fetch_tushare_dates(s8, e8)
        if ts_dates:
            return _clip(ts_dates), 'tushare'

    _ensure_cache_loaded()
    cached = sorted(_trading_calendar_cache or set())
    if cached:
        return _clip(cached), 'cache'
    return [], 'none'


def verify_calendar_coverage(dates, start_date: str, end_date: str,
                             authority: Optional[List[str]] = None) -> dict:
    """校验交易日列表在 [start_date, end_date] 内的**完整性**

    Args:
        dates: 待校验的交易日列表（YYYY-MM-DD）
        start_date / end_date: YYYY-MM-DD
        authority: 权威日历（缺省自动取 akshare；不可用则退回 Tushare）

    Returns:
        dict: {
          'checked': 是否真正做了权威比对（权威源不可用时为 False）,
          'source': 权威源名称,
          'missing': [缺失的权威交易日],      # 核心：局部空洞 ✗
          'extra':   [多余的非交易日],        # 权威日历里没有的日期 ✗
          'expected': 权威源在该区间的交易日数,
          'actual':   实际提供的交易日数,
        }
    """
    have = {str(d) for d in (dates or [])}
    src = 'provided'
    if authority is None:
        authority, src = get_authoritative_dates(start_date, end_date)
    else:
        src = 'provided'
    exp = [d for d in (authority or []) if start_date <= d <= end_date]
    if not exp:
        return {'checked': False, 'source': src, 'missing': [], 'extra': [],
                'expected': 0, 'actual': len(have)}
    missing = [d for d in exp if d not in have]
    expected_set = set(exp)
    extra = sorted(d for d in have if start_date <= d <= end_date and d not in expected_set)
    return {'checked': True, 'source': src, 'missing': missing, 'extra': extra,
            'expected': len(exp), 'actual': len(have)}


def ensure_calendar_coverage(start_date: str, end_date: str, dates=None,
                             auto_heal: bool = True, strict: bool = True) -> List[str]:
    """确保 [start_date, end_date] 覆盖完整（缺失即补齐；仍缺则按 strict 抛错）

    【2026-09-25 新增】"杜绝静默缺日"的核心闸门：
      · 有缺失 → 用权威日历（akshare/Tushare）**自动补齐**并原子写回 ✓
      · 补齐后仍有缺失（权威源不可用等）→ strict=True 抛 RuntimeError ✗
        （宁可直接失败，也不再用残缺日历跑出一个"看着正常"的错结果 ✗）

    Args:
        start_date / end_date: 需要保证覆盖的区间（YYYY-MM-DD）
        dates: 现有交易日列表（None 表示从缓存取）
        auto_heal: 是否自动补齐
        strict: 补齐后仍有缺失时是否抛错

    Returns:
        List[str]: 覆盖完整的交易日列表（升序）
    """
    cur = sorted({str(d) for d in (dates if dates is not None else [])})
    if not cur:
        _ensure_cache_loaded()
        cur = sorted({d for d in (_trading_calendar_cache or set())
                      if start_date <= d <= end_date})
    report = verify_calendar_coverage(cur, start_date, end_date)
    if not report['checked']:
        logger.warning(f"交易日历完整性无法校验（权威源不可用）: {start_date} ~ {end_date}，"
                       f"当前仅 {len(cur)} 日，请检查网络/akshare 与 Tushare 配置")
        return cur
    if not report['missing']:
        logger.info(f"交易日历完整性校验通过 ✓ {start_date} ~ {end_date} "
                    f"共 {report['expected']} 个交易日（基准: {report['source']}）")
        return cur
    logger.error(f"交易日历存在缺失 ✗ {start_date} ~ {end_date}: "
                 f"期望 {report['expected']} 日，实际 {report['actual']} 日，"
                 f"缺失 {len(report['missing'])} 日 → {', '.join(report['missing'][:20])}"
                 f"{' ...' if len(report['missing']) > 20 else ''}")
    if not auto_heal:
        if strict:
            raise RuntimeError(f"交易日历缺失 {len(report['missing'])} 日且未启用自动补齐")
        return cur
    auth, src = get_authoritative_dates(start_date, end_date)
    if not auth:
        if strict:
            raise RuntimeError(f"交易日历缺失 {len(report['missing'])} 日且权威源不可用，"
                               f"已终止以避免用残缺日历产出错误结果")
        return cur
    healed = sorted(set(cur) | set(auth))
    save_trading_dates(healed, source=f'heal:{src}')
    after = verify_calendar_coverage(healed, start_date, end_date)
    if after['missing']:
        msg = (f"交易日历补齐后仍缺失 {len(after['missing'])} 日: "
               f"{', '.join(after['missing'][:20])}")
        if strict:
            raise RuntimeError(msg)
        logger.error(msg)
    else:
        logger.warning(f"交易日历已自动补齐 ✓ {start_date} ~ {end_date} 共 {len(healed)} 日"
                       f"（基准: {src}）→ 请留意此前是否有基于残缺日历的结果")
    return healed


def _update_cache_from_tushare(start_str: str, end_str: str):
    """从 Tushare 批量获取交易日历并合并进本地缓存（统一走 save_trading_dates ✓）

    Args:
        start_str: 开始日期 (YYYYMMDD)
        end_str: 结束日期 (YYYYMMDD)
    """
    new_dates = _fetch_tushare_dates(start_str, end_str)
    if not new_dates:
        logger.debug(f"更新交易日历缓存跳过：Tushare 未返回数据 ({start_str}~{end_str})")
        return
    save_trading_dates(new_dates, source='tushare')


@lru_cache(maxsize=256)
def get_trading_days(start_date: str, end_date: str) -> List[str]:
    """
    获取指定日期范围内的交易日列表（批量优化版 + LRU 缓存 + 本地文件缓存）

    策略：本地缓存 → Tushare API 补充 → 合并缓存。
    不再降级到周末排除模式（节假日不可靠）。

    参数:
        start_date: 开始日期，支持 YYYY-MM-DD 或 YYYYMMDD 格式
        end_date: 结束日期，支持 YYYY-MM-DD 或 YYYYMMDD 格式
    返回:
        List[str]: 交易日列表，格式为 YYYY-MM-DD
        
    Raises:
        RuntimeError: 缓存和 Tushare 均不可用时抛出
    """
    # 统一日期格式
    if '-' in start_date:
        start_str = start_date.replace('-', '')
    else:
        start_str = start_date

    if '-' in end_date:
        end_str = end_date.replace('-', '')
    else:
        end_str = end_date

    start_dt = datetime.strptime(start_str, '%Y%m%d')
    end_dt = datetime.strptime(end_str, '%Y%m%d')

    start_fmt = start_dt.strftime('%Y-%m-%d')
    end_fmt = end_dt.strftime('%Y-%m-%d')

    # 1. 先尝试从 Tushare 批量获取并更新缓存（统一走 _fetch_tushare_dates ✓）
    trading_days = _fetch_tushare_dates(start_str, end_str)
    if trading_days:
        _update_cache_from_tushare(start_str, end_str)
        logger.info(f"批量获取到 {len(trading_days)} 个交易日 (Tushare)")

    # 1.5 【2026-09-25 加固】权威日历校验 + 自动补齐（杜绝"局部缺日"静默通过 ✗）
    #     此前只有"Tushare 非空即用"✗ —— 一旦接口返回**局部**数据（限流/异常），
    #     区间会静默少若干天，回测照跑不误（本次 002372 类排查即暴露该风险）。
    if trading_days:
        try:
            healed = ensure_calendar_coverage(start_fmt, end_fmt, trading_days,
                                              auto_heal=True, strict=False)
            clipped = [d for d in healed if start_fmt <= d <= end_fmt]
            if clipped:
                return clipped
        except Exception as e:
            logger.warning(f"交易日历完整性校验异常（继续使用 Tushare 结果）: {e}")

    # 2. Tushare 失败，从本地缓存筛选（并用权威日历补齐缺失 ✓）
    _ensure_cache_loaded()
    if _trading_calendar_cache:
        trading_days = []
        for d_str in sorted(_trading_calendar_cache):
            d = datetime.strptime(d_str, '%Y-%m-%d')
            if start_dt <= d <= end_dt:
                trading_days.append(d_str)
        if trading_days:
            try:
                healed = ensure_calendar_coverage(start_fmt, end_fmt, trading_days,
                                                  auto_heal=True, strict=False)
                trading_days = [d for d in healed if start_fmt <= d <= end_fmt] or trading_days
            except Exception as e:
                logger.warning(f"本地缓存交易日完整性校验异常: {e}")
            logger.info(f"获取到 {len(trading_days)} 个交易日 (本地缓存)")
            return trading_days

    # 3. 缓存也没有 → 报错
    raise RuntimeError(
        f"获取交易日列表失败: {start_date} ~ {end_date}\n"
        f"Tushare API 不可用且本地缓存文件不存在或没有覆盖该日期范围。\n"
        f"缓存路径: {_get_cache_file()}\n"
        f"请在网络正常时先运行一次回测生成缓存文件。"
    )


def get_trading_days_between(start_date: str, end_date: str) -> int:
    """
    计算两个日期之间的交易日天数

    参数:
        start_date: 开始日期，支持 YYYY-MM-DD 格式或 date 对象
        end_date: 结束日期，支持 YYYY-MM-DD 格式或 date 对象
    返回:
        int: 交易日天数
    """
    try:
        # 处理 date 对象
        if hasattr(start_date, 'strftime'):
            start_date_str = start_date.strftime('%Y-%m-%d')
        else:
            start_date_str = start_date
        
        if hasattr(end_date, 'strftime'):
            end_date_str = end_date.strftime('%Y-%m-%d')
        else:
            end_date_str = end_date
        
        # 获取交易日列表并返回长度
        trading_days = get_trading_days(start_date_str, end_date_str)
        return len(trading_days) - 1  # 减去1，因为不包括买入当天
    except Exception as e:
        logger.error(f"计算交易日天数时出错: {e}")
        return 0


def count_trading_days_between(start_date, end_date, trading_dates=None) -> int:
    """统计 `(start, end]` 内的**交易日个数** ✓ —— 与 `get_trading_days_between` **同口径** ✓

    ★【2026-09-28 用户要求 ✓】**统一改为交易日** ✗→✓：

      · **入池/买入当日 = 0** ✓（例：`2025-12-31` 入池 ✓、`2026-01-05` 检查 ⇒ **1** ✓
        —— 而旧的"日历天"算法给 **5** ✗✓，正是用户困惑"只加入 1 天却写持 5 日"的根因 ✗）；
      · `start` **不含** ✓（入池当天不算持有 ✓）、`end` **含** ✓。

    ⚠️ 为什么另写一个 ✗✓：`get_trading_days_between` 内部走 `get_trading_days` ✓，
    而后者会**先尝试联网**（Tushare）✗ ⇒ **回测 / 离线**场景不可用 ✗（慢、且可能抛错 ✗）。
    故本函数支持传入**已加载的交易日列表** ✓（回测引擎与实盘运行器的
    `_sorted_trading_dates` ✓，升序 `YYYY-MM-DD` ✓）⇒ **零取数** ✓、纯内存 ✓、`bisect` ✓。

    Args:
        start_date: 起点 ✓（**不含** ✓；`date` / `YYYY-MM-DD` / `YYYYMMDD` ✓）
        end_date: 终点 ✓（**含** ✓）
        trading_dates: 升序交易日列表 ✓；`None` ⇒ 转调 `get_trading_days_between` ✓
            （**会取数** ✓，仅用于非回测环境 ✓）

    Returns:
        int ✓：**不含当日** ✓ 的交易日个数；区间反向 / 取不到 ⇒ `0` ✓（**不抛** ✗）
    """
    def _norm(x) -> str:
        if hasattr(x, 'strftime'):
            return x.strftime('%Y-%m-%d')
        s = str(x or '')
        if '-' in s:
            return s[:10]
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}' if len(s) >= 8 else ''

    s, e = _norm(start_date), _norm(end_date)
    if not s or not e or s >= e:
        return 0
    if trading_dates is None:
        return get_trading_days_between(s, e)
    seq = sorted({_norm(d) for d in trading_dates if d})
    if not seq:
        return 0
    import bisect
    lo = bisect.bisect_right(seq, s)      # 第一个 > s ✓（不含起点 ✓）
    hi = bisect.bisect_right(seq, e)      # 第一个 > e ✓（含终点 ✓）
    return max(0, hi - lo)


def get_previous_trading_day(date_str: str) -> str:
    """
    获取指定日期的前一个交易日

    参数:
        date_str: 日期字符串，支持 YYYY-MM-DD 或 YYYYMMDD 格式
    返回:
        str: 前一个交易日，格式为 YYYY-MM-DD
    """
    try:
        # 解析日期（支持两种格式）
        if '-' in date_str:
            date = datetime.strptime(date_str, '%Y-%m-%d')
        else:
            date = datetime.strptime(date_str, '%Y%m%d')
        
        # 向前查找前一个交易日
        current = date - timedelta(days=1)
        while True:
            current_str = current.strftime('%Y-%m-%d')
            if is_trading_day(current_str):
                logger.debug("{} 的前一个交易日是 {}".format(date_str, current_str))
                return current_str
            current -= timedelta(days=1)
    except Exception as e:
        logger.error("获取前一个交易日时出错: {}".format(e))
        # 返回默认值
        return date_str


def resolve_end_date_for_data(end_date: str, now=None) -> Tuple[str, str]:
    """把「**当日数据尚未产出**」的回测/选股终点**回退**到上一交易日 ✓

    背景 ✗✓（2026-09-28 用户实测报障 ✓）：
      2026-09-28 周一 **08:47**（**开盘前** ✗）跑批量回测 ⇒ 闸门报
      `个股资金流向(stock_moneyflow_daily)：[moneyflow_ths] 缺 1 天: 2026-09-28` ✗。
      根因 ✓：`utils/backtest_data_gate.py` 是**逐日**要求 `[起点, 终点]` 每个交易日的
      **本地**数据齐备 ✓，而**当日**数据（资金流 / K 线 / 大盘 ADX ✓）
      **收盘后才采集入库** ✗ ⇒ 只要终点 = **今天** ✓ 且现在**未收盘** ✗ ⇒ **必然**失败 ✗。
      ⚠️ 且原报错文案是"去运行数据更新"✗ —— 08:47 时**根本取不到**当日数据 ✗✓（无效指引 ✗）。

    规则 ✓（**与实盘选股完全同口径** ✓ —— 同规则另见 `web_server.py:989-1016` ✓）：
      ① 终点 = **今天** 且**未过 15:01** ✓ ⇒ 回退 ✓（原因 `交易时段` ✓；
         15:00 收盘时刻 K 线未生成 ✓，故 15:01 起才视为收盘后 ✓）
      ② 终点**非交易日**（周末/节假日 ✓）⇒ 回退 ✓（原因 `非交易日` ✓）
      ③ 其余 ✓（历史交易日 / 收盘后 ✓）⇒ **原样返回** ✓（原因 `''` ✓）
         —— 那才是**真缺数据** ✗，继续由闸门硬拦 ✓，**绝不**掩盖 ✗

    ⚠️ **只调终点** ✗：起点不动 ✓（起点早只是更保守 ✓，不会"少数据" ✓）。

    Args:
        end_date: 回测/选股终点 ✓（`YYYY-MM-DD` / `YYYYMMDD` ✓）
        now: 测试注入 ✓；`None` ⇒ `datetime.now()` ✓

    Returns:
        (生效终点 ✓（`YYYY-MM-DD` ✓）, 回退原因 ✓（`''` = **未回退** ✓）)
    """
    if not end_date:
        return end_date, ''
    now = now or datetime.now()
    raw = str(end_date)
    try:
        d = datetime.strptime(raw, '%Y-%m-%d' if '-' in raw else '%Y%m%d')
    except Exception:
        logger.warning("resolve_end_date_for_data 无法解析终点 {!r} ⇒ 原样返回".format(raw))
        return raw, ''
    eff = d.strftime('%Y-%m-%d')
    today = now.strftime('%Y-%m-%d')
    reason = ''
    if eff == today and (now.hour < 15 or (now.hour == 15 and now.minute == 0)):
        reason = '交易时段'
    elif not is_trading_day(eff):
        reason = '非交易日'
    if not reason:
        return eff, ''
    prev = get_previous_trading_day(eff)
    if not prev or prev == eff:
        # 兜底 ✓：取不到上一交易日 ⇒ **不回退** ✗（交给闸门如实报错 ✓）
        logger.warning("resolve_end_date_for_data 取不到 {} 的上一交易日 ⇒ 不回退".format(eff))
        return eff, ''
    return prev, reason
