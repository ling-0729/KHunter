# -*- coding: utf-8 -*-
"""
涨停股实时取数模块（龙头策略数据源）

数据来自 tushare 的 limit_list_d 接口（需 5000 积分）：按交易日一次调用即可取回
该交易日的全部涨停股，单接口覆盖龙头策略所需的全部字段：
  - limit_type='U'  -> 当日涨停（已排除 ST/退市/炸板未封）
  - first_time/last_time -> 封板时间
  - turnover_ratio -> 换手率（无限售流通股口径，单位 %，=通达信显示值）
  - float_mv       -> 流通市值（单位 元；200 亿 = 20000000000）

本模块只负责“取数”，不做任何本地落库：数据返回后由调用方（龙头策略）在内存中
按选股日参与选股，本地不留存/不维护任何涨停数据。

用法：
  python scripts/collect_limit_up_pool.py --date 20260827   # 查看某交易日涨停股
"""
import sys
import os
import json
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from utils.tushare_client import get_tushare_pro
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
)
logger = logging.getLogger('limit_up_fetcher')

# limit_list_d 取数字段（覆盖龙头策略 4 个选股条件）
# trade_date 一并取回：用于校验接口返回的交易日与请求一致，避免数据错日。
# up_stat 为涨停状态（含炸板情况），供后续扩展使用。
FIELDS = ('ts_code,trade_date,name,close,pct_chg,turnover_ratio,float_mv,'
          'first_time,last_time,open_times,up_stat,limit_times,fd_amount,industry')


def get_pro():
    """从项目配置读取 tushare token 并初始化 Pro API。"""
    cfg_path = os.path.join('config', 'tushare_config.json')
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f'未找到 tushare 配置: {cfg_path}')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    token = cfg.get('token') or cfg.get('api_key')
    if not token:
        raise ValueError('tushare_config.json 中未配置 token/api_key')
    return get_tushare_pro(token)


def _to_float(v):
    try:
        return float(v) if pd.notna(v) else None
    except (ValueError, TypeError):
        return None


def _to_int(v):
    try:
        return int(v) if pd.notna(v) else 0
    except (ValueError, TypeError):
        return 0


def _to_str(v):
    return str(v).strip() if (v is not None and pd.notna(v)) else None


def fetch_limit_up_day(pro, trade_date: str) -> list:
    """
    按交易日拉取当日全部涨停股（仅获取并返回，不落库）。

    龙头策略运行期调用本函数按选股日实时取数，数据只在内存中参与选股，
    本地不留存/不维护任何涨停数据。

    :param trade_date: YYYYMMDD
    :return: list[dict]，每只涨停股一条记录；非交易日、无数据或异常时返回 []
    """
    try:
        df = pro.limit_list_d(trade_date=trade_date, limit_type='U', fields=FIELDS)
    except Exception as e:
        logger.warning(f'{trade_date} 接口调用失败: {e}')
        return []

    if df is None or len(df) == 0:
        return []

    # 校验接口返回的交易日与请求一致，避免把其它交易日的数据当作本选股日
    if 'trade_date' in df.columns:
        got = {str(v).replace('-', '').strip() for v in df['trade_date'].dropna().unique()}
        got.discard('')
        if got and got != {trade_date}:
            logger.warning(f'{trade_date} 接口返回交易日不一致: {sorted(got)}，已忽略本次结果')
            return []

    rows = []
    for _, r in df.iterrows():
        ts_code = _to_str(r.get('ts_code'))
        rows.append({
            'ts_code': ts_code,
            'code': ts_code.split('.')[0] if ts_code else '',
            'name': _to_str(r.get('name')),
            'trade_date': trade_date,
            'close': _to_float(r.get('close')),
            'pct_chg': _to_float(r.get('pct_chg')),
            'turnover_ratio': _to_float(r.get('turnover_ratio')),
            'float_mv': _to_float(r.get('float_mv')),
            'first_time': _to_str(r.get('first_time')),
            'last_time': _to_str(r.get('last_time')),
            'open_times': _to_int(r.get('open_times')),
            'up_stat': _to_str(r.get('up_stat')),
            'limit_times': _to_int(r.get('limit_times')),
            'fd_amount': _to_float(r.get('fd_amount')),
            'industry': _to_str(r.get('industry')),
        })
    logger.info(f'[{trade_date}] 实时获取涨停 {len(rows)} 只（内存使用，不落库）')
    return rows


def main():
    parser = argparse.ArgumentParser(
        description='涨停股实时取数 (tushare limit_list_d，不落库)')
    parser.add_argument('--date', required=True, help='交易日期 YYYYMMDD')
    args = parser.parse_args()

    pro = get_pro()
    rows = fetch_limit_up_day(pro, args.date)
    print(f'{args.date} 涨停股 {len(rows)} 只')
    for r in rows[:20]:
        print('  %s %s close=%s 换手=%s 流通市值=%s 末封=%s' % (
            r['code'], r['name'], r['close'],
            r['turnover_ratio'], r['float_mv'], r['last_time']))


if __name__ == '__main__':
    main()
