"""
数据初始化器 - 初始化各类数据（基础数据、K线、资金流向等）
"""
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

# 配置日志
logger = logging.getLogger(__name__)


class DataInitializer:
    """数据初始化器"""
    
    def __init__(self, db_manager, stock_data_fetcher, kline_fetcher, fund_flow_fetcher,
                 progress_callback=None):
        """
        初始化数据初始化器
        
        参数：
            db_manager: 数据库管理器
            stock_data_fetcher: 股票数据采集器
            kline_fetcher: K线数据处理器
            fund_flow_fetcher: 资金流向数据采集器
            progress_callback: 进度回调函数 callback(progress_pct: int, message: str)
        """
        self.db_manager = db_manager
        self.stock_data_fetcher = stock_data_fetcher
        self.kline_fetcher = kline_fetcher
        self.fund_flow_fetcher = fund_flow_fetcher
        self.progress_callback = progress_callback
    
    def _report_progress(self, progress_pct: int, message: str = ""):
        """上报进度（通过回调函数）"""
        if self.progress_callback:
            try:
                self.progress_callback(progress_pct, message)
            except Exception:
                pass
    
    # ==================== 基础数据初始化 ====================
    
    def _init_basic_data(self, stock_codes: list, stock_dict: dict = None) -> None:
        """
        初始化基础数据（包括股票基本信息和市值）
        
        参数：
            stock_codes: 股票代码列表
            stock_dict: 股票代码到名称的映射字典
        """
        logger.info("开始初始化基础数据...")
        success_count = 0
        failed_count = 0
        
        try:
            # 步骤1：获取股票名称（批量）
            logger.info("获取股票基本信息...")
            if stock_dict:
                all_stocks = stock_dict
                logger.info(f"使用传入的股票基本信息: {len(all_stocks)} 只股票")
            else:
                all_stocks = self.stock_data_fetcher.get_all_stock_codes()
                
                if not all_stocks:
                    logger.error("获取股票基本信息失败")
                    return
                
                logger.info(f"成功获取 {len(all_stocks)} 只股票的基本信息")
            
            # 步骤2：获取股票市值（批量）
            logger.info("从 Tushare 获取股票市值信息...")
            market_caps = self.stock_data_fetcher.get_stock_market_cap()
            
            if market_caps:
                logger.info(f"成功获取 {len(market_caps)} 只股票的市值信息")
            else:
                logger.warning("未获取到市值信息，将使用默认值 0")
            
            # 步骤3：批量保存到数据库
            with self.db_manager.transaction():
                logger.info("保存股票基本信息和市值到数据库...")
                
                for idx, code in enumerate(stock_codes, 1):
                    try:
                        # 从批量获取的数据中查找基本信息
                        name = all_stocks.get(code, '')
                        # 获取市值信息，如果没有则使用 0
                        market_cap = market_caps.get(code, 0)
                        
                        if name:
                            # 保存基本信息和市值到 stock_basic 表
                            insert_sql = """
                            INSERT OR REPLACE INTO stock_basic 
                            (code, name, market_cap)
                            VALUES (?, ?, ?)
                            """
                            self.db_manager.execute_with_retry(insert_sql, (code, name, market_cap))
                            success_count += 1
                        else:
                            failed_count += 1
                            logger.debug(f"股票 {code} 不在批量获取的数据中")
                        
                        # 定期输出进度（每100只股票输出一次）
                        if idx % 100 == 0:
                            logger.info(f"基础数据采集进度: {idx}/{len(stock_codes)}, 成功: {success_count}")
                    
                    except Exception as e:
                        failed_count += 1
                        logger.warning(f"处理 {code} 基础数据失败: {e}")
                
                logger.info(f"基础数据保存完成: 成功 {success_count} 只, 失败 {failed_count} 只")
        
        except Exception as e:
            logger.error(f"初始化基础数据失败: {e}")
    
    # ==================== K线数据初始化 ====================
    
    def _init_kline_history_data(self, stock_codes: list, years: int = 3,
                                  progress_range: tuple = (0, 100)) -> None:
        """
        初始化K线历史数据（TickFlow 优先，智能降级 + 自动恢复）

        策略：
        1. 优先使用 TickFlow 批量 API，批次间延迟 3 秒防止限流
        2. TickFlow 失败时等待 30 秒后重试 1 次，再失败才降级
        3. 连续 3 次 TickFlow 失败才永久降级；否则尝试恢复
        4. 降级期间每 5 批自动探测 TickFlow 是否恢复
        5. 腾讯财经降级使用 2 线程低并发，避免反爬

        参数：
            stock_codes: 股票代码列表
            years: 获取数据的年份数（默认 3 年）
            progress_range: 进度映射区间 (start, end)，默认 (0, 100)
        """
        import time as time_module
        # batch_size: 每批处理的股票数，与日常更新对齐
        batch_size = 100
        # days: 将年份转换为交易日数，与 TickFlow batch API 参数对齐
        days = years * 250
        total = len(stock_codes)
        progress_start, progress_end = progress_range
        success_count = 0
        failed_count = 0
        total_inserted = 0
        # fallback_mode: 是否已降级到腾讯财经
        fallback_mode = False
        # 连续 TickFlow 失败计数（用于判断是否永久降级）
        consecutive_tf_fails = 0
        # 连续 3 次失败才永久降级
        TF_PERMANENT_THRESHOLD = 3
        # TickFlow 失败后重试前的等待时间（秒）
        TF_RETRY_DELAY = 30
        # 降级后每隔多少批次探测一次 TickFlow 恢复
        TF_PROBE_INTERVAL = 5
        # 降级模式下计数器
        fallback_batch_count = 0
        # 腾讯财经连续空批次计数（用于动态退避）
        consecutive_empty_tencent = 0

        logger.info("=" * 60)
        logger.info(f"K线初始化开始 | 股票: {total} 只 | 年份: {years}年 | 批次大小: {batch_size}")
        logger.info(f"数据源策略: TickFlow 优先(批间 3s 延迟) → TickFlow 失败重试(30s) → 腾讯财经降级(2线程)")
        logger.info(f"永久降级阈值: 连续 {TF_PERMANENT_THRESHOLD} 次 TickFlow 失败")
        logger.info("=" * 60)

        try:
            # 分批处理
            for batch_idx in range(0, total, batch_size):
                # 当前批次的股票代码列表
                batch_codes = stock_codes[batch_idx:batch_idx + batch_size]
                batch_num = batch_idx // batch_size + 1

                # ============ 步骤1: 选择数据源获取 K 线 ============
                if not fallback_mode:
                    # ---------- TickFlow 优先模式 ----------
                    kline_dict, api_ok = self.stock_data_fetcher._fetch_stock_batch_tickflow(
                        batch_codes, days=days
                    )
                    tickflow_hit = len(kline_dict)
                    if api_ok:
                        # TickFlow 成功，重置失败计数
                        consecutive_tf_fails = 0
                        logger.debug(f"批次{batch_num}: TickFlow 命中 {tickflow_hit}/{len(batch_codes)} 只")
                    else:
                        # TickFlow 失败 → 等待后重试1次
                        consecutive_tf_fails += 1
                        logger.warning(
                            f"批次{batch_num}: TickFlow 失败(连续第{consecutive_tf_fails}次)，"
                            f"等待 {TF_RETRY_DELAY}s 后重试…"
                        )
                        time_module.sleep(TF_RETRY_DELAY)
                        # 重试 TickFlow
                        kline_dict, api_ok = self.stock_data_fetcher._fetch_stock_batch_tickflow(
                            batch_codes, days=days
                        )
                        if api_ok:
                            # 重试成功
                            consecutive_tf_fails = 0
                            tickflow_hit = len(kline_dict)
                            logger.info(
                                f"批次{batch_num}: TickFlow 重试成功，命中 {tickflow_hit}/{len(batch_codes)} 只"
                            )
                        elif consecutive_tf_fails >= TF_PERMANENT_THRESHOLD:
                            # 连续失败达到阈值 → 永久降级
                            remaining = total - batch_idx
                            logger.warning("=" * 50)
                            logger.warning(
                                f"!!! TickFlow 连续失败 {consecutive_tf_fails} 次(批次{batch_num})，永久切换到腾讯财经 !!!"
                            )
                            logger.warning(
                                f"数据源切换: TickFlow → 腾讯财经(批量并发,2线程)"
                            )
                            logger.warning(
                                f"影响范围: 剩余 {remaining} 只 | 已成功: {success_count} 只"
                            )
                            logger.warning("=" * 50)
                            fallback_mode = True
                            # 用腾讯财经获取当前批次
                            kline_dict = self.stock_data_fetcher._fetch_stock_batch_tencent(
                                batch_codes, years=years, concurrency=2
                            )
                            tencent_hit = len(kline_dict)
                            logger.info(
                                f"批次{batch_num} 降级获取: 腾讯财经 {tencent_hit}/{len(batch_codes)} 只"
                            )
                        else:
                            # 连续失败次数未达阈值，临时用腾讯财经处理本批，下次继续尝试TickFlow
                            logger.warning(
                                f"批次{batch_num}: TickFlow 重试仍失败(连续{consecutive_tf_fails}/{TF_PERMANENT_THRESHOLD})，"
                                f"本批临时降级到腾讯财经，下批恢复 TickFlow"
                            )
                            kline_dict = self.stock_data_fetcher._fetch_stock_batch_tencent(
                                batch_codes, years=years, concurrency=2
                            )
                            tencent_hit = len(kline_dict)
                            logger.info(
                                f"批次{batch_num} 临时降级: 腾讯财经 {tencent_hit}/{len(batch_codes)} 只"
                            )
                else:
                    # ---------- 降级模式 ----------
                    # 定期探测 TickFlow 是否已恢复
                    fallback_batch_count += 1
                    if fallback_batch_count % TF_PROBE_INTERVAL == 0:
                        logger.info(f"批次{batch_num}: 探测 TickFlow 恢复状态(降级后第{fallback_batch_count}批)…")
                        probe_dict, probe_ok = self.stock_data_fetcher._fetch_stock_batch_tickflow(
                            batch_codes[:20], days=days  # 只探测 20 只，降低探测成本
                        )
                        if probe_ok and len(probe_dict) > 0:
                            logger.info(
                                f"批次{batch_num}: TickFlow 已恢复！切换回 TickFlow 模式"
                            )
                            fallback_mode = False
                            consecutive_tf_fails = 0
                            fallback_batch_count = 0
                            # 用 TickFlow 获取完整批次
                            kline_dict, api_ok = self.stock_data_fetcher._fetch_stock_batch_tickflow(
                                batch_codes, days=days
                            )
                            if not api_ok:
                                # 探测成功但完整批次失败，回到降级
                                logger.warning("批次{batch_num}: TickFlow 恢复探测成功但完整批次失败，维持降级")
                                fallback_mode = True
                                kline_dict = self.stock_data_fetcher._fetch_stock_batch_tencent(
                                    batch_codes, years=years, concurrency=2
                                )
                                tencent_hit = len(kline_dict)
                        else:
                            logger.debug(f"批次{batch_num}: TickFlow 仍未恢复，继续使用腾讯财经")
                            kline_dict = self.stock_data_fetcher._fetch_stock_batch_tencent(
                                batch_codes, years=years, concurrency=2
                            )
                            tencent_hit = len(kline_dict)
                    else:
                        # 直接使用腾讯财经
                        kline_dict = self.stock_data_fetcher._fetch_stock_batch_tencent(
                            batch_codes, years=years, concurrency=2
                        )
                        tencent_hit = len(kline_dict)
                        logger.info(f"批次{batch_num}: 腾讯财经(降级模式) 获取 {tencent_hit}/{len(batch_codes)} 只")

                # ============ 步骤2: 批量写入数据库（executemany 高效模式）============
                batch_inserted = 0
                with self.db_manager.transaction():
                    # 在事务中获取连接，与 kline_updater 保持一致
                    conn = self.db_manager.connect()
                    cursor = conn.cursor()
                    insert_sql = """
                    INSERT OR REPLACE INTO stock_kline
                    (code, date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """
                    for code, df_kline in kline_dict.items():
                        try:
                            if df_kline is None or len(df_kline) == 0:
                                continue

                            # 准备数据：向量化处理比 iterrows 快 10-100 倍
                            # 统一日期格式为 YYYY-MM-DD
                            from utils.date_utils import normalize_date
                            dates = df_kline['date'].apply(lambda x: normalize_date(x) if x is not None else None)
                            volumes = df_kline['volume'].fillna(0).astype(int)
                            opens = df_kline['open'].astype(float)
                            highs = df_kline['high'].astype(float)
                            lows = df_kline['low'].astype(float)
                            closes = df_kline['close'].astype(float)

                            # 构建记录列表
                            records = list(zip(
                                [code] * len(df_kline), dates, opens, highs, lows, closes, volumes
                            ))

                            # executemany 批量插入
                            cursor.executemany(insert_sql, records)
                            batch_inserted += len(records)
                            success_count += 1

                        except Exception as e:
                            failed_count += 1
                            logger.debug(f"批量保存 {code} K线失败: {e}")

                # ============ 步骤3: 统计与进度 ============
                # 统计批次中本批无数据的股票数（不在 kline_dict 即为最终失败）
                batch_failed_count = len([c for c in batch_codes if c not in kline_dict])
                failed_count += batch_failed_count

                total_inserted += batch_inserted

                # 每批次输出进度日志
                completed = min(batch_idx + len(batch_codes), total)
                progress_pct = completed / total * 100
                if fallback_mode:
                    mode_label = "[腾讯财经降级]"
                elif consecutive_tf_fails > 0:
                    mode_label = f"[TickFlow(重试{consecutive_tf_fails}次)]"
                else:
                    mode_label = "[TickFlow]"
                logger.info(
                    f"K线初始化进度 {mode_label}: {completed}/{total} "
                    f"({progress_pct:.1f}%) | 成功: {success_count} | "
                    f"本批插入: {batch_inserted} 条 | 累计插入: {total_inserted} 条"
                )
                # 映射到全局进度区间并上报
                global_pct = int(progress_start + progress_pct / 100.0 * (progress_end - progress_start))
                self._report_progress(global_pct,
                    f"K线数据: {completed}/{total} ({progress_pct:.0f}%)")

                # ============ 批次间延迟（防限流核心策略）============
                if not fallback_mode:
                    # TickFlow 模式：3 秒延迟，防止免费 API 限流
                    time_module.sleep(3)
                else:
                    # 降级模式：基础 2 秒延迟
                    time_module.sleep(2)
                    # 腾讯财经空批次动态退避（全部股票无数据即为空批次）
                    if batch_failed_count == len(batch_codes):
                        consecutive_empty_tencent += 1
                        backoff = min(consecutive_empty_tencent * 3, 30)
                        logger.warning(
                            f"腾讯财经连续 {consecutive_empty_tencent} 批全空，退避 {backoff}s"
                        )
                        time_module.sleep(backoff)
                    else:
                        consecutive_empty_tencent = 0

            # 计算最终失败数
            final_failed = total - success_count
            logger.info(
                f"K线历史数据初始化完成: 成功 {success_count} 只, "
                f"失败 {final_failed} 只, 总记录 {total_inserted} 条"
            )

            # 失败数超过阈值时抛出异常，提示重新初始化
            FAILURE_THRESHOLD = 1000
            if final_failed > FAILURE_THRESHOLD:
                raise RuntimeError(
                    f"K线初始化失败数({final_failed}只)超过阈值({FAILURE_THRESHOLD}只)，"
                    f"成功率仅 {success_count / total * 100:.1f}%。"
                    f"请检查数据源连通性后重新执行初始化。"
                )

        except Exception as e:
            logger.error(f"初始化K线历史数据失败: {e}")
            # 重新抛出异常，让上层 init_all 感知失败
            raise
    
    # ==================== 行业和板块数据初始化 ====================
    
    def _init_industry_data(self, stock_codes: list) -> None:
        """
        初始化行业数据
        
        参数：
            stock_codes: 股票代码列表
        """
        logger.info("初始化行业数据...")
        # TODO: 实现行业数据初始化逻辑
        logger.info("行业数据初始化完成")
    
    def _init_sector_data(self, stock_codes: list) -> None:
        """
        初始化板块数据
        
        参数：
            stock_codes: 股票代码列表
        """
        logger.info("初始化板块数据...")
        # TODO: 实现板块数据初始化逻辑
        logger.info("板块数据初始化完成")
    
    # ==================== 资金流向数据初始化 ====================
    
    def _init_fund_flow_data(self, stock_codes: list, include_industry_sector: bool = True) -> dict:
        """
        初始化资金流向数据
        
        参数：
            stock_codes: 股票代码列表
            include_industry_sector: 是否包括行业和板块资金流向
        
        返回：
            初始化统计信息字典
        """
        logger.info("开始初始化资金流向数据...")
        stats = {
            'stock_moneyflow': 0,
            'industry_moneyflow': 0,
            'sector_moneyflow': 0
        }
        
        try:
            # TODO: 实现资金流向数据初始化逻辑
            logger.info("资金流向数据初始化完成")
        except Exception as e:
            logger.error(f"初始化资金流向数据失败: {e}")
        
        return stats
    
    # ==================== 事件数据初始化 ====================
    
    def _init_event_data(self, stock_codes: list) -> dict:
        """
        初始化事件数据（暂时不可用）
        Tushare anns_d 接口权限未开通，暂时跳过事件数据初始化
        
        参数：
            stock_codes: 股票代码列表
        
        返回：
            初始化统计信息字典
        """
        logger.info("事件数据初始化暂时跳过（Tushare 权限未开通）")
        return {'event_data': 0}
    
    # ==================== 统一初始化入口 ====================
    
    def init_full_data(self, max_stocks: Optional[int] = None, years: int = 3,
                       incremental: bool = False, stock_dict: dict = None,
                       stock_codes: list = None) -> None:
        """
        统一的初始化入口，支持全量和增量两种模式
        
        参数：
            max_stocks: 最多初始化多少只股票（None 表示全部）
            years: 获取K线数据的年份数（默认 3 年）
            incremental: 是否仅初始化新增股票（默认 False，全量初始化）
            stock_dict: 预获取的股票代码到名称的映射字典（可选，避免重复拉取）
            stock_codes: 直接传入股票代码列表（可选，跳过API拉取步骤）
        """
        mode = "增量" if incremental else "全量"
        logger.info(f"开始{mode}初始化数据...")
        
        try:
            # 获取股票代码：优先使用传入的列表
            if stock_codes is not None:
                all_stocks = stock_dict or {}
                stock_codes = list(stock_codes)
            else:
                # 获取所有股票代码（如果未传入则拉取）
                if stock_dict:
                    all_stocks = stock_dict
                else:
                    self._report_progress(0, "正在获取股票列表...")
                    all_stocks = self.stock_data_fetcher.get_all_stock_codes()
                stock_codes = list(all_stocks.keys())
            
            # 增量模式：过滤掉数据库中已存在的股票
            if incremental:
                sql = "SELECT DISTINCT code FROM stock_basic"
                existing_stocks = set()
                try:
                    results = self.db_manager.query_all(sql)
                    existing_stocks = {row['code'] for row in results}
                except:
                    pass
                stock_codes = [c for c in stock_codes if c not in existing_stocks]
                logger.info(f"增量模式: 发现 {len(stock_codes)} 只新股票")
            
            # 限制股票数量
            if max_stocks:
                stock_codes = stock_codes[:max_stocks]
            
            if not stock_codes:
                logger.info("没有需要初始化的股票，跳过")
                return
            
            total = len(stock_codes)
            logger.info(f"准备初始化 {total} 只股票的数据...")
            
            # 进度分段（映射到 0-100）：
            # 基础数据 0%-15%, K线 15%-80%, 行业 80%-85%, 板块 85%-90%, 资金 90%-95%, 事件 95%-100%
            stages = [0, 15, 80, 85, 90, 95, 100]
            
            # 1. 初始化基础数据
            self._report_progress(stages[0], f"正在初始化基础数据（{total}只）...")
            self._init_basic_data(stock_codes, stock_dict if not incremental else all_stocks)
            self._report_progress(stages[1], "基础数据初始化完成")
            
            # 2. 初始化K线历史数据（内部会按批次回调）
            self._report_progress(stages[1], f"正在获取K线数据（{years}年）...")
            self._init_kline_history_data(stock_codes, years=years,
                                          progress_range=(stages[1], stages[2]))
            self._report_progress(stages[2], "K线数据初始化完成")
            
            # 3. 初始化行业数据
            self._report_progress(stages[2], "正在初始化行业数据...")
            self._init_industry_data(stock_codes)
            self._report_progress(stages[3], "行业数据初始化完成")
            
            # 4. 初始化板块数据
            self._report_progress(stages[3], "正在初始化板块数据...")
            self._init_sector_data(stock_codes)
            self._report_progress(stages[4], "板块数据初始化完成")
            
            # 5. 初始化资金流向数据
            self._report_progress(stages[4], "正在初始化资金流向数据...")
            self._init_fund_flow_data(stock_codes)
            self._report_progress(stages[5], "资金流向数据初始化完成")
            
            # 6. 初始化事件数据
            self._report_progress(stages[5], "正在初始化事件数据...")
            self._init_event_data(stock_codes)
            self._report_progress(stages[6], "事件数据初始化完成")
            
            logger.info(f"{mode}初始化完成")
        
        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"{mode}初始化失败: {e}")
            logger.error("请检查数据源连通性后重新执行初始化（运行主程序将自动触发）")
            logger.error("=" * 60)
    
    # ==================== 映射更新检查 ====================
    
    def _check_mapping_update_needed(self, mapping_type: str) -> bool:
        """
        检查映射是否需要更新
        
        参数：
            mapping_type: 映射类型 (industry, sector)
        
        返回：
            是否需要更新
        """
        logger.debug(f"检查 {mapping_type} 映射是否需要更新...")
        # TODO: 实现映射更新检查逻辑
        return False
    
    def _update_industry_data(self, stock_codes: list) -> None:
        """
        更新行业数据
        
        参数：
            stock_codes: 股票代码列表
        """
        logger.info("更新行业数据...")
        # TODO: 实现行业数据更新逻辑
        logger.info("行业数据更新完成")
    
    def _update_sector_data(self, stock_codes: list) -> None:
        """
        更新板块数据
        
        参数：
            stock_codes: 股票代码列表
        """
        logger.info("更新板块数据...")
        # TODO: 实现板块数据更新逻辑
        logger.info("板块数据更新完成")
