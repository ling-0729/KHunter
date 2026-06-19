"""
K线数据增量更新器

功能：
1. 计算需要获取的天数
2. 分批获取K线数据
3. 流式处理：边获取边保存
4. 统计更新结果

特点：
- 流式处理，避免一次性加载所有数据到内存
- 使用UPSERT操作，避免重复检查
- 分批处理，提高网络请求成功率
- 完善的错误处理和重试机制
"""

import logging
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import pandas as pd
import time

logger = logging.getLogger(__name__)


class KlineUpdater:
    """K线数据增量更新器"""

    def __init__(self, db_manager, stock_data_fetcher):
        """
        初始化K线更新器

        参数：
            db_manager: 数据库管理器
            stock_data_fetcher: 股票数据采集器
        """
        self.db_manager = db_manager
        self.stock_data_fetcher = stock_data_fetcher

        from utils.kline_fetcher import KlineFetcher
        self.kline_fetcher = KlineFetcher(db_manager, stock_data_fetcher)

        self.stats = {
            'added': 0,
            'updated': 0,
            'failed': 0,
            'rebuilt': 0
        }

        self.progress = {
            'current': 0,
            'total': 0,
            'percentage': 0
        }

    def update_kline_data(self, stock_codes: List[str], last_update_date: str, target_date: str, batch_size: int = 100) -> Dict:
        """
        增量更新K线数据

        流程：
        1. 计算需要获取的天数
        2. 分批获取数据
        3. 检测除权：如有除权触发历史重建
        4. 返回统计结果

        参数：
            stock_codes: 股票代码列表
            last_update_date: 上次更新日期 (YYYY-MM-DD)
            target_date: 目标更新日期 (YYYY-MM-DD)
            batch_size: 每批处理的股票数

        返回：
            {
                'success': bool,
                'added': int,
                'updated': int,
                'failed': int,
                'rebuilt': int,
                'message': str,
                'total_time': float
            }
        """
        start_time = datetime.now()
        
        try:
            # 打印数据源信息
            logger.info("=" * 60)
            logger.info("K线数据更新任务启动")
            logger.info("=" * 60)
            logger.info(f"数据源策略: TickFlow 免费 API (前复权批量)")
            logger.info(f"待更新股票数量: {len(stock_codes)}")
            logger.info(f"上次更新日期: {last_update_date}")
            logger.info(f"目标更新日期: {target_date}")
            logger.info("=" * 60)
            
            logger.info(f"开始更新K线数据: {len(stock_codes)} 只股票")
            
            # 第0步：检查数据源是否已准备好目标日期数据
            logger.info("第0步: 检查数据源数据就绪状态...")
            if not self._is_data_source_ready(stock_codes, target_date):
                logger.warning(f"数据源 (TickFlow) 尚未返回 {target_date} 的数据，跳过本次更新")
                return {
                    'success': True,
                    'added': 0,
                    'updated': 0,
                    'failed': 0,
                    'rebuilt': 0,
                    'message': f"数据源尚未就绪，{target_date} 数据暂不可用，请稍后再试",
                    'total_time': (datetime.now() - start_time).total_seconds()
                }
            
            # 第1步：计算需要获取的天数
            logger.info("第1步: 计算需要获取的天数...")
            days_to_fetch = self._calculate_days_to_fetch(last_update_date, target_date)
            
            if days_to_fetch <= 0:
                logger.info("无需更新K线数据（已是最新）")
                return {
                    'success': True,
                    'added': 0,
                    'updated': 0,
                    'failed': 0,
                    'message': '无需更新K线数据（已是最新）',
                    'total_time': (datetime.now() - start_time).total_seconds()
                }
            
            logger.info(f"需要获取 {days_to_fetch} 天的K线数据")
            
            # 第2步：分批批量处理（TickFlow API）
            logger.info(f"第2步: TickFlow 批量处理 {len(stock_codes)} 只股票 (批次大小: {batch_size})...")
            self.progress['total'] = len(stock_codes)
            
            for batch_idx in range(0, len(stock_codes), batch_size):
                # 获取该批股票
                batch_codes = stock_codes[batch_idx:batch_idx + batch_size]
                batch_num = batch_idx // batch_size + 1
                total_batches = (len(stock_codes) + batch_size - 1) // batch_size
                
                # 更新进度
                self.progress['current'] = min(batch_idx + batch_size, len(stock_codes))
                self.progress['percentage'] = int((self.progress['current'] / self.progress['total']) * 100)
                
                logger.info(f"批次 {batch_num}/{total_batches}: TickFlow 处理 {len(batch_codes)} 只股票 [{self.progress['current']}/{self.progress['total']}] {self.progress['percentage']}%")
                
                try:
                    batch_start_time = time.time()
                    batch_result = self._fetch_and_save_batch_concurrent(batch_codes, days_to_fetch)
                    batch_elapsed = time.time() - batch_start_time

                    self.stats['added'] += batch_result['added']
                    self.stats['updated'] += batch_result['updated']
                    self.stats['failed'] += batch_result['failed']

                    logger.info(f"批次 {batch_num} 完成: 新增 {batch_result['added']} 条, 失败 {batch_result['failed']} 只, 耗时 {batch_elapsed:.1f}秒")

                except Exception as e:
                    logger.warning(f"批次 {batch_num} TickFlow 处理失败: {str(e)}")
                    self.stats['failed'] += len(batch_codes)
            
            # 第3步：检测除权并重建历史数据
            logger.info("=" * 60)
            logger.info("第3步: 检测除权并重建历史数据...")
            logger.info("=" * 60)
            try:
                # 将日期格式转换为 YYYYMMDD
                target_date_str = target_date.replace('-', '')
                last_update_date_str = last_update_date.replace('-', '')
                exdividend_result = self.check_exdividend_and_rebuild(stock_codes, target_date_str, last_update_date_str)
                
                if exdividend_result['exdividend_detected']:
                    # 重建结果已在 check_exdividend_and_rebuild 中输出，这里只输出简要汇总
                    rebuilt = exdividend_result.get('rebuilt_stocks', [])
                    if rebuilt:
                        logger.warning(f"【除权检测】已重建 {len(rebuilt)} 只股票历史数据")
                    self.stats['rebuilt'] = len(exdividend_result['rebuilt_stocks'])
                else:
                    logger.info(f"【除权检测】{exdividend_result['message']} (时间段: {last_update_date_str} ~ {target_date_str})")
            except Exception as e:
                logger.error(f"【除权检测】除权检测失败: {str(e)}")
                logger.exception(e)  # 打印详细异常信息
            
            # 第4步：返回结果
            total_time = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"K线数据更新完成: 新增 {self.stats['added']} 条, 更新 {self.stats['updated']} 条, 失败 {self.stats['failed']} 条, 重建 {self.stats['rebuilt']} 只, 耗时 {total_time:.1f}秒")
            
            return {
                'success': True,
                'added': self.stats['added'],
                'updated': self.stats['updated'],
                'failed': self.stats['failed'],
                'rebuilt': self.stats['rebuilt'],
                'message': f"K线数据更新完成: 新增 {self.stats['added']} 条, 更新 {self.stats['updated']} 条, 重建 {self.stats['rebuilt']} 只",
                'total_time': total_time
            }
        
        except Exception as e:
            logger.error(f"K线数据更新失败: {str(e)}")
            total_time = (datetime.now() - start_time).total_seconds()
            
            return {
                'success': False,
                'added': self.stats['added'],
                'updated': self.stats['updated'],
                'failed': self.stats['failed'],
                'rebuilt': self.stats['rebuilt'],
                'message': f"K线数据更新失败: {str(e)}",
                'error': str(e),
                'total_time': total_time
            }
    
    def _is_data_source_ready(self, stock_codes: List[str], target_date: str) -> bool:
        """
        检查数据源 (TickFlow) 是否已准备好目标日期的数据

        取样少量股票，拉取 TickFlow 最新 K 线，
        检查返回数据中是否包含 target_date。

        参数：
            stock_codes: 全部待更新股票代码列表
            target_date: 目标更新日期 (YYYY-MM-DD)

        返回：
            True 数据就绪，False 数据尚未可用
        """
        # 取样最多 3 只股票，覆盖主板、创业板、科创板
        sample_codes = self._sample_by_board(stock_codes)
        if not sample_codes:
            return True  # 没有待更新股票，视为就绪

        try:
            logger.info(f"取样 {len(sample_codes)} 只股票探测数据源就绪状态: {sample_codes}")

            # 用 TickFlow 拉取最近 3 天数据
            kline_data, api_ok = self.kline_fetcher._fetch_kline_tickflow_batch(
                sample_codes, days=3
            )

            if not api_ok:
                logger.warning("数据源就绪检查: TickFlow API 调用失败，认为数据未就绪")
                return False

            if not kline_data:
                logger.warning("数据源就绪检查: TickFlow 返回空数据，认为数据未就绪")
                return False

            # 统计有 target_date 数据的股票数，至少 2 只才视为就绪
            target_date_normalized = target_date.replace('-', '')  # YYYYMMDD
            ready_codes = []
            all_dates = set()

            for code, df in kline_data.items():
                if df is None or len(df) == 0:
                    continue
                dates = df['date'].astype(str).str.split(' ').str[0].tolist()
                all_dates.update(dates)
                for d in dates:
                    d_norm = d.replace('-', '')
                    if d_norm == target_date_normalized or d == target_date:
                        ready_codes.append(code)
                        break  # 该股票已有目标日期数据，不再检查

            # 至少 2 只返回目标日期数据才视为就绪
            if len(ready_codes) >= 2:
                logger.info(f"数据源就绪检查: {ready_codes} 已有 {target_date} 数据，数据源就绪")
                return True

            logger.warning(
                f"数据源就绪检查: {len(ready_codes)}/{len(kline_data)} 只有目标日期数据 "
                f"(要求 >= 2), 已有: {ready_codes}, 当前最新日期: {sorted(all_dates)}"
            )
            return False

        except Exception as e:
            logger.error(f"数据源就绪检查异常: {e}，保守认为数据未就绪")
            return False

    @staticmethod
    def _sample_by_board(stock_codes: List[str]) -> List[str]:
        """
        从股票列表中取样，覆盖主板、创业板、科创板

        板块分类：
            主板:   600/601/603/605 (沪), 000/001/002/003 (深)
            创业板: 300/301 (深)
            科创板: 688/689 (沪)
            北交所: 8 (920/83/87)

        每个板块最多取 1 只，最多返回 3 只。

        参数：
            stock_codes: 全部待检测股票代码列表

        返回：
            取样股票代码列表 (最多 3 只，覆盖主板/创业板/科创板)
        """
        # 定义板块分类规则
        boards = {
            '主板': [],
            '创业板': [],
            '科创板': [],
        }

        for code in stock_codes:
            code = str(code).strip()
            if not code or len(code) < 6:
                continue

            # 科创板 (688xxx, 689xxx)
            if code.startswith(('688', '689')):
                if not boards['科创板']:
                    boards['科创板'].append(code)
            # 创业板 (300xxx, 301xxx)
            elif code.startswith(('300', '301')):
                if not boards['创业板']:
                    boards['创业板'].append(code)
            # 主板 (600/601/603/605, 000/001/002/003)
            elif code.startswith(('600', '601', '603', '605', '000', '001', '002', '003')):
                if not boards['主板']:
                    boards['主板'].append(code)
            else:
                # 北交所或其他，归入主板（若主板已满则跳过）
                if not boards['主板']:
                    boards['主板'].append(code)

            # 三个板块都已取到，提前退出
            if all(boards.values()):
                break

        # 按优先级顺序合并: 主板 → 创业板 → 科创板
        result = boards['主板'] + boards['创业板'] + boards['科创板']
        return result

    def _calculate_days_to_fetch(self, last_update_date: str, target_date: str) -> int:
        """
        计算需要获取的天数
        
        参数：
            last_update_date: 上次更新日期 (YYYY-MM-DD)
            target_date: 目标更新日期 (YYYY-MM-DD)
        
        返回：
            需要获取的天数
        """
        try:
            # 解析日期
            last_date = datetime.strptime(last_update_date, '%Y-%m-%d')
            target = datetime.strptime(target_date, '%Y-%m-%d')
            
            # 计算天数差
            days_diff = (target - last_date).days
            
            # 为了确保获取到所有新数据，多获取2天，最小获取3天
            days_to_fetch = max(days_diff + 2, 3)
            
            logger.debug(f"上次更新日期: {last_update_date}, 目标日期: {target_date}, 需要获取: {days_to_fetch} 天")
            
            return days_to_fetch
        
        except Exception as e:
            logger.error(f"计算需要获取的天数失败: {str(e)}")
            # 默认获取30天
            return 30
    
    def _fetch_and_save_batch_concurrent(self, batch_codes: List[str], days: int) -> Dict:
        """
        【TickFlow 版】使用 TickFlow 批量 API 一次获取一批股票的K线数据并批量保存

        TickFlow API 成功但个别股票无数据 → 正常（不降级），仅标记为 failed
        TickFlow API 失败（限流/网络）→ 降级到腾讯财经逐只获取

        参数：
            batch_codes: 股票代码列表
            days: 获取最近多少天的数据

        返回：
            {'added': int, 'updated': int, 'failed': int}
        """
        added = 0
        updated = 0
        failed = 0

        try:
            # 使用 TickFlow 批量 API 一次获取所有股票K线
            logger.debug(f"TickFlow 批量获取 {len(batch_codes)} 只股票K线 (前复权, {days}天)...")
            kline_data, api_ok = self.kline_fetcher._fetch_kline_tickflow_batch(
                batch_codes,
                days=days
            )

            # TickFlow API 失败时，降级到腾讯财经逐只获取
            if not api_ok:
                logger.warning(f"TickFlow API 失败，降级到腾讯财经逐只获取 {len(batch_codes)} 只...")
                for code in batch_codes:
                    if code in kline_data:
                        continue  # 已有数据则跳过
                    try:
                        df = self.stock_data_fetcher.fetch_stock_update(code, days=days)
                        if df is not None and len(df) > 0:
                            kline_data[code] = df
                    except Exception as e:
                        logger.debug(f"腾讯财经降级获取 {code} 失败: {e}")
                logger.info(f"腾讯财经降级补充: {len(kline_data)}/{len(batch_codes)} 只有数据")

            # 批量保存到数据库
            if kline_data:
                logger.debug(f"批量保存 {len(kline_data)} 只股票的K线数据...")
                with self.db_manager.transaction():
                    for stock_code, df_kline in kline_data.items():
                        if df_kline is not None and len(df_kline) > 0:
                            try:
                                batch_added, batch_updated = self._save_kline_records_batch(
                                    stock_code, df_kline, batch_size=100
                                )
                                added += batch_added
                                updated += batch_updated
                            except Exception as e:
                                logger.error(f"保存 {stock_code} 数据失败: {str(e)}")
                                failed += 1
                        else:
                            failed += 1

                # 统计最终无数据的股票（TickFlow无数据 + 降级也无数据）
                final_missing = len([c for c in batch_codes if c not in kline_data])
                failed += final_missing
            else:
                # 全部获取失败
                failed = len(batch_codes)
                logger.warning(f"批次 {len(batch_codes)} 只股票全部获取失败")

            return {
                'added': added,
                'updated': updated,
                'failed': failed
            }

        except Exception as e:
            logger.error(f"TickFlow 批次处理失败: {str(e)}")
            return {
                'added': added,
                'updated': updated,
                'failed': failed + len(batch_codes)
            }
    
    def _fetch_and_save_batch(self, batch_codes: List[str], days: int) -> Dict:
        """
        【旧版串行方法 - 已弃用】获取一批股票的K线数据并立即保存
        
        注意：此方法已被 _fetch_and_save_batch_concurrent 替代
        保留此方法仅用于兼容性，不建议使用
        
        参数：
            batch_codes: 股票代码列表
            days: 获取最近多少天的数据
        
        返回：
            {'added': int, 'updated': int, 'failed': int}
        """
        logger.warning("使用了已弃用的串行方法 _fetch_and_save_batch，建议使用 _fetch_and_save_batch_concurrent")
        return self._fetch_and_save_batch_concurrent(batch_codes, days)
    
    def _fetch_with_retry(self, stock_code: str, days: int, max_retries: int = 2) -> Optional[pd.DataFrame]:
        """
        带重试机制的获取K线数据
        
        参数：
            stock_code: 股票代码
            days: 获取最近多少天的数据
            max_retries: 最大重试次数
        
        返回：
            K线数据DataFrame，如果失败则返回None
        """
        import time
        
        for attempt in range(max_retries):
            try:
                # 获取K线数据
                df_kline = self.stock_data_fetcher.fetch_stock_update(stock_code, days=days)
                
                if df_kline is not None and len(df_kline) > 0:
                    # 成功获取数据
                    if attempt > 0:
                        logger.debug(f"{stock_code} 第 {attempt + 1} 次尝试成功")
                    return df_kline
                
                # 数据为空，不需要重试
                return None
            
            except Exception as e:
                # 发生异常，尝试重试
                if attempt < max_retries - 1:
                    # 等待后重试（增加等待时间避免限流）
                    wait_time = 2.0 * (attempt + 1)  # 递增等待时间：2秒、4秒
                    logger.debug(f"{stock_code} 获取失败，{wait_time}秒后重试: {str(e)}")
                    time.sleep(wait_time)
                else:
                    # 最后一次重试也失败
                    logger.error(f"{stock_code} 重试 {max_retries} 次后仍失败: {str(e)}")
                    return None
        
        return None
    
    def _save_kline_records_batch(self, stock_code, df_kline, batch_size = 100):
        """
        批量保存K线记录到数据库
        
        使用UPSERT操作：INSERT OR REPLACE
        使用executemany批量执行，大幅提升性能
        
        参数：
            stock_code: 股票代码
            df_kline: K线数据DataFrame
            batch_size: 每批保存的记录数（已弃用，保留用于兼容性）
        
        返回：
            (新增数, 更新数)
        """
        added = 0
        updated = 0
        
        try:
            # UPSERT SQL 语句
            upsert_sql = """
            INSERT OR REPLACE INTO stock_kline 
            (code, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            
            # 确定成交量列名：优先使用volume，其次使用vol
            volume_col = 'volume' if 'volume' in df_kline.columns else 'vol'
            
            # 使用向量化操作准备数据，比iterrows()快10-100倍
            try:
                # 准备日期列（统一转换为 YYYY-MM-DD 格式）
                from utils.date_utils import normalize_date
                dates = df_kline['date'].apply(lambda x: normalize_date(x) if x is not None else None)
                
                # 准备成交量列，处理NaN值
                volumes = df_kline[volume_col].fillna(0).astype(int)
                
                # 准备OHLC数据
                opens = df_kline['open'].astype(float)
                highs = df_kline['high'].astype(float)
                lows = df_kline['low'].astype(float)
                closes = df_kline['close'].astype(float)
                
                # 构建记录列表（使用zip比iterrows快得多）
                records_to_save = list(zip(
                    [stock_code] * len(df_kline),  # 股票代码
                    dates,                           # 日期
                    opens,                           # 开盘价
                    highs,                           # 最高价
                    lows,                            # 最低价
                    closes,                          # 收盘价
                    volumes                          # 成交量
                ))
                
            except Exception as e:
                logger.error(f"准备 {stock_code} K线数据失败: {str(e)}")
                return 0, 0
            
            # 使用原生executemany批量保存所有记录，大幅提升性能
            if records_to_save:
                with self.db_manager.transaction():
                    conn = self.db_manager.connect()
                    cursor = conn.cursor()
                    cursor.executemany(upsert_sql, records_to_save)
                added = len(records_to_save)
            
            return added, updated
        
        except Exception as e:
            logger.error(f"保存 {stock_code} K线数据失败: {str(e)}")
            return 0, 0
    
    def get_progress(self) -> Dict:
        """获取更新进度"""
        return self.progress.copy()

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.stats.copy()

    def check_exdividend_and_rebuild(self, stock_codes: List[str], trade_date: str, start_date: str = None) -> Dict:
        """
        检测除权并在检测到除权时重建历史数据

        流程：
        1. 调用 stock_data_fetcher.check_exdividend_by_factor 检测除权
        2. 对每只发生除权的股票，重建完整历史数据
        3. 返回检测和重建结果

        参数：
            stock_codes: 股票代码列表
            trade_date: 交易日期 (YYYYMMDD)
            start_date: 开始日期 (YYYYMMDD)，检测该日期到trade_date之间的除权

        返回：
            {
                'exdividend_detected': bool,
                'exdividend_stocks': [stock_code, ...],
                'factor_changes': {stock_code: [(date, prev_factor, curr_factor), ...], ...},
                'rebuilt_stocks': [stock_code, ...],
                'message': str
            }
        """
        result = {
            'exdividend_detected': False,
            'exdividend_stocks': [],
            'factor_changes': {},
            'rebuilt_stocks': [],
            'message': ''
        }

        try:
            logger.info(f"【除权检测】开始检测 {len(stock_codes)} 只股票的除权情况...")

            check_result = self.stock_data_fetcher.check_exdividend_by_factor(stock_codes, trade_date, start_date)

            if not check_result['exdividend_stocks']:
                logger.info("【除权检测】未检测到除权")
                result['message'] = '未检测到除权'
                return result

            result['exdividend_detected'] = True
            result['exdividend_stocks'] = check_result['exdividend_stocks']
            # 传递复权因子变化详情，供上游日志展示
            result['factor_changes'] = check_result.get('factor_changes', {})
            logger.warning(f"【除权检测】检测到 {len(check_result['exdividend_stocks'])} 只股票发生除权")
            logger.warning(f"【除权检测】检测时间段：{start_date if start_date else '前一交易日'} ~ {trade_date}")
            # 逐只股票打印详细除权信息
            for stock_code in check_result['exdividend_stocks']:
                changes = check_result.get('factor_changes', {}).get(stock_code, [])
                if changes:
                    for chg_date, prev_f, curr_f in changes:
                        change_pct = abs(curr_f - prev_f) / prev_f * 100
                        logger.warning(
                            f"  >> {stock_code} 除权日={chg_date} "
                            f"复权因子 {prev_f:.6f} -> {curr_f:.6f} "
                            f"(变化 {change_pct:.2f}%)"
                        )
                else:
                    logger.warning(f"  >> {stock_code} (无详细因子数据)")

            # 重建检测到除权的股票历史数据
            logger.info(f"【除权检测】开始重建 {len(check_result['exdividend_stocks'])} 只除权股票历史数据...")
            for stock_code in check_result['exdividend_stocks']:
                rebuild_success = self._rebuild_stock_history(stock_code)
                if rebuild_success:
                    result['rebuilt_stocks'].append(stock_code)
                    self.stats['rebuilt'] += 1

            if result['rebuilt_stocks']:
                result['message'] = f"检测到除权，已重建 {len(result['rebuilt_stocks'])} 只股票: {result['rebuilt_stocks']}"
            else:
                result['message'] = f"检测到除权但重建失败: {check_result['exdividend_stocks']}"

            return result

        except Exception as e:
            logger.error(f"【除权检测】除权检测和重建失败: {str(e)}")
            result['message'] = f"除权检测失败: {str(e)}"
            return result

    def _rebuild_stock_history(self, stock_code: str, years: int = 6) -> bool:
        """
        重建单只股票完整历史数据（使用 TickFlow 免费 API）

        流程：
        1. 删除该股票现有历史数据
        2. 通过 TickFlow 重新获取多年历史数据（前复权）
        3. 保存新数据到数据库

        参数：
            stock_code: 股票代码
            years: 重建历史数据的年数

        返回：
            True 成功，False 失败
        """
        try:
            logger.info(f"【历史重建】{stock_code} 删除旧数据...")
            conn = self.db_manager.connect()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stock_kline WHERE code = ?", (stock_code,))
            conn.commit()
            conn.close()
            logger.info(f"【历史重建】{stock_code} 删除 {cursor.rowcount} 条旧数据")

            logger.info(f"【历史重建】{stock_code} 通过 TickFlow 重新获取 {years} 年历史数据...")
            df_history = self.stock_data_fetcher._fetch_stock_history_tickflow(stock_code, years=years)

            if df_history is None or df_history.empty:
                logger.info(f"【历史重建】{stock_code} TickFlow 获取历史数据失败")
                return False

            added, updated = self._save_kline_records_batch(stock_code, df_history)
            logger.info(f"【历史重建】{stock_code} 保存新数据：新增 {added} 条，更新 {updated} 条")
            return True

        except Exception as e:
            logger.error(f"【历史重建】{stock_code} 重建失败：{str(e)}")
            return False
