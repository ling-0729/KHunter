"""
KHunter 自动交易策略 (PTrade 云端部署脚本)
============================================
本文件同时维护在:
  1. KHunter 本地:  trading/ptrade/khunter_auto_trade.py  (git 版本控制)
  2. PTrade 云端:   /home/fly/notebook/khunter_auto_trade.py (策略执行)

功能:
  9:31 开盘读取 KHunter 信号文件并提交委托（通过 run_daily 定时触发）

处理顺序:
  - KHunter 端保证 CSV 中卖出信号排在买入信号前面
  - PTrade 端按 CSV 行顺序逐条处理，自然实现先卖后买
  - 卖出释放资金后再买入，避免资金不足

买入过滤规则:
  - 开盘涨幅 > 3% → 不买入（追高风险）
  - 开盘跌幅 > 3% → 不买入（强势下跌风险）
  - 当前价偏离信号价 > 3% → 不买入（价格波动风险）
  - 买入时按当前价下单（limit_price = 当前价）

反馈机制:
  - PTrade 原生自动导出 Fund_/Hold_ CSV 文件（不需要策略中手动生成）
  - KHunter 端 PTradeFeedbackHandler 读取 Fund_/Hold_ 文件更新 portfolio

在 PTrade 策略模块中配置:
  策略类型: 股票
  运行模式: 交易
  运行时间: 每天
"""

import pandas as pd
from datetime import datetime

# ============ 全局常量 ============
# 信号文件（固定文件名，KHunter 每天覆盖上传）
SIGNAL_FILE = "KHunter_signals.csv"

# 定时触发时间
MORNING_EXEC_TIME = '9:31'    # 开盘信号处理时间（9:30开盘后）

# 买入价格阈值（当前价偏离信号价 ±3% 以内才下单，信号价=昨收）
MAX_PRICE_UP_DEVIATION = 0.03    # 当前价高于信号价3%不买入（追高风险）
MAX_PRICE_DOWN_DEVIATION = 0.03  # 当前价低于信号价3%不买入（强势下跌风险）

# PTrade 研究模块 upload_files 目录名（相对研究模块路径）
UPLOAD_DIRNAME = "upload_files"


def _join_path(*parts):
    """
    拼接路径（替代 os.path.join，避免导入 os 模块）

    Args:
        *parts: 路径片段

    Returns:
        str: 以 / 连接的完整路径（保留绝对路径前缀）
    """
    # 记录第一个 part 是否以 / 开头（绝对路径）
    is_absolute = parts and parts[0].startswith("/")
    # 去掉每个 part 的首尾 / 再拼接
    result = "/".join(p.strip("/") for p in parts if p)
    # 恢复绝对路径前缀
    if is_absolute:
        result = "/" + result
    return result


def _file_exists(filepath):
    """
    检查文件是否存在（替代 os.path.exists）

    Args:
        filepath: 文件路径

    Returns:
        bool: 文件是否存在
    """
    try:
        with open(filepath, 'r'):
            return True
    except Exception:
        return False


def initialize(context):
    """
    策略初始化（PTrade 生命周期入口）

    初始化全局变量并注册定时任务：
    - 9:31 run_daily 开盘处理信号
    - PTrade 原生自动导出 Fund_/Hold_ 文件（15:05 后），无需策略处理
    """
    g.executed_signals = {}         # 当日已提交的信号记录 {signal_id: {...}}

    # 注册定时任务（PTrade 仅支持一个 run_daily）
    run_daily(context, morning_event, time=MORNING_EXEC_TIME)
    log.info(f"[KHunter] 策略初始化完成, 开盘处理={MORNING_EXEC_TIME}")


def before_trading_start(context, data):
    """
    PTrade 盘前事件（每个交易日约 9:25 触发一次）

    重置当日状态，信号处理由 run_daily(9:31) 定时触发
    """
    # 重置当日信号记录
    g.executed_signals = {}


def morning_event(context):
    """
    开盘处理事件（run_daily 定时触发，9:31 执行）

    功能: 读取 KHunter 信号文件，获取当前价，
          检查价格阈值后提交委托（按当前价下单）

    参照 ptradesample 的 daily_event 模式:
      - 使用 get_position(sec).last_sale_price 获取当前价
      - 使用 order(sec, vol, limit_price=current_price) 按当前价下单
    """
    today_str = context.current_dt.strftime('%Y%m%d')
    log.info(f"[KHunter] 开盘处理开始, 日期={today_str}")
    process_khunter_signals(context, today_str)



def handle_data(context, data):
    """
    PTrade 盘中事件（9:30-15:00 每分钟触发）

    本策略通过 run_daily 定时触发完成所有操作，
    handle_data 无需额外操作。PTrade 原生会在 15:05 后
    自动导出 Fund_/Hold_ 文件供 KHunter 读取。
    """
    pass


def _normalize_symbol(symbol):
    """
    标准化股票代码为 PTrade 格式（上海 .SS，深圳 .SZ）

    KHunter 信号文件使用 .SH 表示上海，PTrade 需要转为 .SS

    Args:
        symbol: 如 "688147.SH" 或 "301314.SZ" 或 "688147"

    Returns:
        str: PTrade 标准代码，如 "688147.SS" 或 "301314.SZ"

    Raises:
        ValueError: 若 symbol 无效（NaN/None/空字符串/非字符串类型）
    """
    # 防御：NaN 是 float 类型，不是 str
    if symbol is None or not isinstance(symbol, str) or pd.isna(symbol):
        raise ValueError(f"无效的股票代码: {symbol} (类型: {type(symbol).__name__})")
    symbol = str(symbol).strip()
    if not symbol:
        raise ValueError("股票代码为空字符串")
    if symbol.endswith('.SH'):
        return symbol[:-3] + '.SS'
    return symbol  # .SZ 已正确，或无后缀时保留原样


def process_khunter_signals(context, today_str):
    """
    读取 KHunter 信号文件并提交委托

    执行规则:
      0. exec_date 校验：信号执行日期必须等于当日，否则跳过全部信号
      1. 获取当前价
      2. 当前价偏离信号价（昨收）±3% 不买入
      3. 买入前检查可用资金是否充足
      4. 卖出前检查持仓是否足够
      5. 买入时按当前价下单

    Args:
        context: PTrade 上下文
        today_str: 当日日期字符串 YYYYMMDD
    """
    # 构造信号文件完整路径（用 get_research_path 获取研究模块路径）
    research_dir = get_research_path()
    file_path = _join_path(research_dir, UPLOAD_DIRNAME, SIGNAL_FILE)
    log.info(f"[KHunter] 查找信号文件: {file_path}")

    # 检查文件是否存在
    if not _file_exists(file_path):
        log.warning(f"[KHunter] 信号文件不存在: {file_path}，跳过今日交易")
        return

    # 读取信号文件（容错多种编码，优先 UTF-8）
    df = None
    # 尝试编码列表：UTF-8 优先，GBK/GB18030 作为回退（Windows 生成中文文件常见）
    for enc in ['utf-8', 'utf-8-sig', 'gbk', 'gb18030', 'latin-1']:
        try:
            df = pd.read_csv(file_path, encoding=enc)
            log.info(f"[KHunter] 读取到 {len(df)} 条信号 (编码: {enc})")
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as e:
            log.error(f"[KHunter] 编码 {enc} 读取失败: {e}")
            continue
    if df is None:
        log.error(f"[KHunter] 所有编码尝试均失败，无法读取信号文件")
        return

    # 防御：清理列名首尾空格（CSV 生成方可能引入尾随空格）
    df.columns = df.columns.str.strip()

    # 校验执行日期：exec_date 必须与当日相同（KHunter端已计算好T+1交易日）
    # 防御处理：去掉连字符（兼容 2026-06-16 和 20260616 两种格式）
    if 'exec_date' in df.columns and len(df) > 0:
        csv_exec_date = str(df.iloc[0]['exec_date']).strip().replace('-', '')
        if csv_exec_date != today_str:
            log.error(f"[KHunter] 信号执行日期 {csv_exec_date} ≠ 当日 {today_str}，"
                      f"信号不属于当日，跳过全部信号")
            return
        log.info(f"[KHunter] 信号执行日期校验通过: {csv_exec_date} == {today_str}")
    else:
        log.warning("[KHunter] 信号文件缺少 exec_date 列，无法校验日期，继续处理（兼容旧格式）")

    # 逐条处理信号
    buy_count = 0
    sell_count = 0
    skip_count = 0

    for idx, row in df.iterrows():
        try:
            signal_id = row.get('signal_id', f'unknown_{idx}')
            # 转换 KHunter 格式 → PTrade 格式: .SH → .SS
            symbol = _normalize_symbol(row['symbol'])
            side = row['side']
            volume = int(row['order_volume'])
            price = float(row['order_price'])
            price_type = row.get('price_type', 'limit')
        except (KeyError, ValueError, TypeError) as e:
            log.error(f"[KHunter] 信号行#{idx} 数据解析失败: {e}，跳过该信号")
            skip_count += 1
            continue

        # 防重复：检查是否已处理
        if signal_id in g.executed_signals:
            log.info(f"[KHunter] 信号 {signal_id} 已处理，跳过")
            continue

        # ---- 买入委托 ----
        if side == 'buy':
            # 规则1: 获取当前价（参照 ptradesample 使用 get_position(symbol).last_sale_price）
            try:
                current_pos = get_position(symbol)
                current_price = current_pos.last_sale_price if current_pos and current_pos.last_sale_price > 0 else price
            except Exception as e:
                log.warning(f"[KHunter] {symbol} 获取当前价失败: {e}，使用信号价 {price:.2f}")
                current_price = price

            # 规则2: 当前价偏离信号价（昨收）阈值检查，-3% ~ +3% 内才下单
            if price > 0 and current_price > 0:
                price_deviation = (current_price - price) / price
                # 当前价过高（追高风险）
                if price_deviation > MAX_PRICE_UP_DEVIATION:
                    log.info(f"[KHunter] {symbol} 当前价 {current_price:.2f} "
                             f"高于信号价 {price:.2f} ({price_deviation:.1%}) "
                             f"> {MAX_PRICE_UP_DEVIATION:.0%}，跳过买入")
                    skip_count += 1
                    continue
                # 当前价过低（强势下跌风险）
                if price_deviation < -MAX_PRICE_DOWN_DEVIATION:
                    log.info(f"[KHunter] {symbol} 当前价 {current_price:.2f} "
                             f"低于信号价 {price:.2f} ({price_deviation:.1%}) "
                             f"< -{MAX_PRICE_DOWN_DEVIATION:.0%}，跳过买入")
                    skip_count += 1
                    continue

            # 规则3: 检查可用资金（PTrade 用 context.portfolio.cash）
            available_cash = context.portfolio.cash
            required_amount = volume * current_price * 1.001  # 以当前价计算，预留手续费
            if available_cash < required_amount:
                log.warning(f"[KHunter] {symbol} 买入需要 {required_amount:.0f}，可用 {available_cash:.0f}，跳过")
                skip_count += 1
                continue

            # 提交委托：按当前价下单（参照 ptradesample 的 order(sec, vol) 模式）
            order_id = order(symbol, volume, limit_price=current_price)
            g.executed_signals[signal_id] = {
                'order_id': order_id,
                'symbol': symbol,
                'side': side,
                'volume': volume,
                'price': current_price,        # 记录实际下单价格
                'signal_price': price,         # 保留原始信号价供参考
                'price_type': 'current',       # 标记为按当前价下单
                'signal_id': signal_id,
                'submit_time': context.current_dt.strftime('%H:%M:%S')
            }
            buy_count += 1
            log.info(f"[KHunter] 买入委托: {symbol} {volume}股 "
                     f"信号价={price:.2f} 当前价={current_price:.2f} "
                     f"偏离={(current_price/price-1)*100:+.2f}% order_id={order_id}")

        # ---- 卖出委托 ----
        elif side == 'sell':
            # 检查持仓数量
            pos = get_position(symbol)
            if pos is None or pos.enable_amount < volume:
                available = pos.enable_amount if pos else 0
                log.warning(f"[KHunter] {symbol} 持仓不足，可用 {available}，需要 {volume}")
                skip_count += 1
                continue

            # 市价卖出（负数量表示卖出）
            order_id = order(symbol, -volume)
            g.executed_signals[signal_id] = {
                'order_id': order_id,
                'symbol': symbol,
                'side': side,
                'volume': volume,
                'price': 0,  # 市价单不设限价
                'price_type': 'market',
                'signal_id': signal_id,
                'submit_time': context.current_dt.strftime('%H:%M:%S')
            }
            sell_count += 1
            log.info(f"[KHunter] 卖出委托: {symbol} {volume}股 order_id={order_id}")

    log.info(f"[KHunter] 信号处理完成: 买入{buy_count}条, 卖出{sell_count}条, 跳过{skip_count}条")

