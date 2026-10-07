"""
资金流向数据增量更新器

功能：
1. 计算需要获取的天数
2. 获取个股、行业、板块资金流向数据
3. 覆盖数据库中该时间段的数据
4. 统计更新结果

特点：
- 支持三种资金流向数据：个股、行业、板块
- 使用DELETE + INSERT方式覆盖数据
- 完善的错误处理和重试机制
- 详细的统计信息
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger(__name__)


class FundFlowUpdater:
    """资金流向数据增量更新器"""
    
    def __init__(self, db_manager, fund_flow_fetcher):
        """
        初始化资金流向更新器
        
        参数：
            db_manager: 数据库管理器
            fund_flow_fetcher: 资金流向数据采集器
        """
        self.db_manager = db_manager
        self.fund_flow_fetcher = fund_flow_fetcher
        
        # 统计信息
        self.stats = {
            'added': 0,      # 新增记录数
            'updated': 0,    # 更新记录数
            'failed': 0      # 失败记录数
        }
        
        # 进度信息
        self.progress = {
            'current': 0,
            'total': 3,      # 三种资金流向数据
            'percentage': 0
        }
    
    def update_fund_flow_data(self, last_update_date: str, target_date: str) -> Dict:
        """
        更新资金流向数据
        
        流程：
        1. 计算需要获取的天数 (从 last_update_date 到 target_date)
        2. 获取个股、行业、板块资金流向数据
        3. 覆盖数据库中该时间段的数据
        
        参数：
            last_update_date: 上次更新日期 (YYYY-MM-DD)
            target_date: 目标更新日期 (YYYY-MM-DD)
        
        返回：
            {
                'success': bool,
                'added': int,
                'updated': int,
                'failed': int,
                'message': str,
                'total_time': float
            }
        """
        start_time = datetime.now()

        try:
            # ★★【2026-09-28 减噪 ✓】**三个子域全停用 ⇒ 整步短路** ✗→✓ ★★
            #   实测 ✗✓（用户指出 ✓）：本类维护的旧表 `stock_fund_flow` **已停用** ✗
            #   （规范表 = `stock_moneyflow_daily` ✓，由【第8.5步】本地数据维护 ✓），
            #   行业/板块**暂不处理** ✗ ⇒ 每次更新却仍白打 **6 行 INFO** ✗
            #   （开始更新 / 第1步 / 需要获取 N 天 / 第2步 / 第3步 / 第4步 / 完成 0 条 ✗）
            #   ⇒ 用户看到的是"**资金流向更新完成: 新增 0 条，耗时 0.0 秒**"✗
            #     并据此以为"资金流更新没成功" ✗✓。
            #   ⇒ 现直接短路 ✓，只留一条 `debug` ✓（排查时仍可见 ✓）。
            #   ⚠️ 判据取**配置真值** ✓（`_legacy_stock_ff_enabled` ✓ / `_industry_sector_enabled` ✓）
            #     ⇒ 任一被显式启用 ✓（旧表回填 / 行业板块 ✓）⇒ **照旧走全流程** ✓（行为不变 ✓，
            #     连上面 6 行日志也照旧 ✓）。
            if not self._legacy_stock_ff_enabled() and not self._industry_sector_enabled():
                logger.debug('资金流向（旧路径）整步空转 ⇒ 跳过 ✓：旧表 stock_fund_flow 已停用 ✗、'
                             '行业/板块暂不处理 ✗；规范表 stock_moneyflow_daily 由'
                             '【第8.5步】本地数据（含每日滚动 3 日增量 ✓）维护 ✓')
                return {
                    'success': True,
                    'added': 0,
                    'updated': 0,
                    'failed': 0,
                    'message': '资金流向（旧路径）已停用 ⇒ 跳过 ✓',
                    'total_time': 0.0
                }

            logger.info(f"开始更新资金流向数据")
            
            # 第1步：计算需要获取的天数
            logger.info("第1步: 计算需要获取的天数...")
            days_to_fetch = self._calculate_days_to_fetch(last_update_date, target_date)
            
            if days_to_fetch <= 0:
                logger.info("无需更新资金流向数据（已是最新）")
                return {
                    'success': True,
                    'added': 0,
                    'updated': 0,
                    'failed': 0,
                    'message': '无需更新资金流向数据（已是最新）',
                    'total_time': (datetime.now() - start_time).total_seconds()
                }
            
            logger.info(f"需要获取 {days_to_fetch} 天的资金流向数据")
            
            # 第2步：更新个股资金流向
            logger.info("第2步: 更新个股资金流向...")
            self.progress['current'] = 1
            self.progress['percentage'] = int((self.progress['current'] / self.progress['total']) * 100)
            
            try:
                stock_result = self._update_stock_fund_flow(days_to_fetch)
                self.stats['added'] += stock_result['added']
                self.stats['updated'] += stock_result['updated']
                self.stats['failed'] += stock_result['failed']
            except Exception as e:
                logger.warning(f"更新个股资金流向失败: {str(e)}")
                self.stats['failed'] += 1
            
            # 第3步：更新行业资金流向
            logger.info("第3步: 更新行业资金流向...")
            self.progress['current'] = 2
            self.progress['percentage'] = int((self.progress['current'] / self.progress['total']) * 100)
            
            try:
                industry_result = self._update_industry_fund_flow(days_to_fetch)
                self.stats['added'] += industry_result['added']
                self.stats['updated'] += industry_result['updated']
                self.stats['failed'] += industry_result['failed']
            except Exception as e:
                logger.warning(f"更新行业资金流向失败: {str(e)}")
                self.stats['failed'] += 1
            
            # 第4步：更新板块资金流向
            logger.info("第4步: 更新板块资金流向...")
            self.progress['current'] = 3
            self.progress['percentage'] = int((self.progress['current'] / self.progress['total']) * 100)
            
            try:
                sector_result = self._update_sector_fund_flow(days_to_fetch)
                self.stats['added'] += sector_result['added']
                self.stats['updated'] += sector_result['updated']
                self.stats['failed'] += sector_result['failed']
            except Exception as e:
                logger.warning(f"更新板块资金流向失败: {str(e)}")
                self.stats['failed'] += 1
            
            # 第5步：返回结果
            total_time = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"资金流向数据更新完成: 新增 {self.stats['added']} 条, 更新 {self.stats['updated']} 条, 失败 {self.stats['failed']} 条, 耗时 {total_time:.1f}秒")
            
            return {
                'success': True,
                'added': self.stats['added'],
                'updated': self.stats['updated'],
                'failed': self.stats['failed'],
                'message': f"资金流向数据更新完成: 新增 {self.stats['added']} 条, 更新 {self.stats['updated']} 条",
                'total_time': total_time
            }
        
        except Exception as e:
            logger.error(f"资金流向数据更新失败: {str(e)}")
            total_time = (datetime.now() - start_time).total_seconds()
            
            return {
                'success': False,
                'added': self.stats['added'],
                'updated': self.stats['updated'],
                'failed': self.stats['failed'],
                'message': f"资金流向数据更新失败: {str(e)}",
                'error': str(e),
                'total_time': total_time
            }
    
    def _get_latest_fund_flow_date(self) -> str:
        """查询**规范表**的最新资金流日期 ✓（YYYY-MM-DD ✓）

        【2026-09-25 修复 ✗→✓】原实现取"stock / industry / sector 三表最新日期的**最小值**"✗：
          · `industry_fund_flow` / `sector_fund_flow` 已停用 ✗（0 行 ✓）⇒ 实际只剩 `stock_fund_flow` ✗
          · 而该表 `flow_date` 存的是 **`'20260924'`（YYYYMMDD ✗）**，与"取最小值"所依赖的
            `YYYY-MM-DD` 语义**混用** ✗ ⇒ 字符串比较下 `'20260924' < '2026-09-24'` ✗，
            且返回值格式与下游期望不符 ✗ → 下游解析失败 → **静默退回"30 天前"** ✗✓
            （更新窗口因此可能偏大/异常 ✗）
        现改为**只读规范表** `stock_moneyflow_daily.trade_date` ✓（主源 `moneyflow_dc` ✓、
        4,276,029 行 ✓、格式统一 ✓、由 `moneyflow_dc_collector` 维护 ✓）。
        旧三表方法保留 ✓ 但**不再参与窗口计算** ✗（仅供诊断 ✓）。

        Returns:
            str: YYYY-MM-DD（规范表为空/异常 → 30 天前 ✓，与原兜底一致 ✓）
        """
        try:
            row = self.db_manager.query_one(
                "SELECT MAX(trade_date) AS d FROM stock_moneyflow_daily")
            d = None
            if row is not None:
                if isinstance(row, dict):
                    d = row.get('d')
                else:
                    try:
                        d = row[0]
                    except Exception:
                        d = None
            if d and str(d)[:10] not in ('None', 'null', ''):
                latest = str(d)[:10]
                logger.debug(f"最新资金流日期（规范表 ✓）: {latest}")
                return latest
            logger.warning("规范表 stock_moneyflow_daily 无数据 ⇒ 更新窗口回退"
                           "为 30 天前（请先运行资金流初始化 ✓）")
        except Exception as e:
            logger.error(f"查询规范表最新资金流日期失败（回退 30 天前）: {e}")
        return (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    def _legacy_stock_ff_enabled(self) -> bool:
        """旧表 `stock_fund_flow` 是否继续写入 ✓（默认 **False = 已停用** ✗，2026-09-25 决策 ✓）

        规则读取 `config/config.yaml → update.legacy_stock_fund_flow.enabled` ✓；
        读不到/非法 → **False** ✓（默认不再写 ✗，避免继续产生空值垃圾行 ✗）。
        """
        cached = getattr(FundFlowUpdater, '_LEGACY_STOCK_FF_ENABLED', None)
        if cached is not None:
            return cached
        val = False
        try:
            import yaml
            from pathlib import Path
            cfg = Path(__file__).resolve().parent.parent / 'config' / 'config.yaml'
            if cfg.exists():
                with open(cfg, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                raw = ((data.get('update') or {}).get('legacy_stock_fund_flow') or {}).get('enabled')
                if raw is not None:
                    val = str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
        except Exception as e:
            logger.warning(f"读取 update.legacy_stock_fund_flow.enabled 失败（按 false 处理）: {e}")
        FundFlowUpdater._LEGACY_STOCK_FF_ENABLED = val
        return val

    def _get_latest_stock_fund_flow_date(self) -> Optional[str]:
        """查询个股资金流向的最新日期"""
        try:
            sql = "SELECT MAX(flow_date) as max_date FROM stock_fund_flow"
            result = self.db_manager.query_one(sql)
            
            if result and result[0]:
                return result[0]
            
            return None
        
        except Exception as e:
            logger.debug(f"查询个股资金流向最新日期失败: {str(e)}")
            return None
    
    def _get_latest_industry_fund_flow_date(self) -> Optional[str]:
        """查询行业资金流向的最新日期"""
        try:
            sql = "SELECT MAX(trade_date) as max_date FROM industry_fund_flow"
            result = self.db_manager.query_one(sql)
            
            if result and result[0]:
                return result[0]
            
            return None
        
        except Exception as e:
            logger.debug(f"查询行业资金流向最新日期失败: {str(e)}")
            return None
    
    def _get_latest_sector_fund_flow_date(self) -> Optional[str]:
        """查询板块资金流向的最新日期"""
        try:
            sql = "SELECT MAX(trade_date) as max_date FROM sector_fund_flow"
            result = self.db_manager.query_one(sql)
            
            if result and result[0]:
                return result[0]
            
            return None
        
        except Exception as e:
            logger.debug(f"查询板块资金流向最新日期失败: {str(e)}")
            return None
    
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
            
            # 若上次更新日期已达到或超过目标日期，说明数据已是最新，直接返回 0（由调用方短路跳过）
            if days_diff <= 0:
                logger.debug(f"上次更新日期 {last_update_date} 已 >= 目标日期 {target_date}，无需获取，返回 0")
                return 0
            
            # 为了确保获取到所有新数据，多获取2天
            days_to_fetch = max(days_diff + 2, 5)
            
            logger.debug(f"上次更新日期: {last_update_date}, 目标日期: {target_date}, 需要获取: {days_to_fetch} 天")
            
            return days_to_fetch
        
        except Exception as e:
            logger.error(f"计算需要获取的天数失败: {str(e)}")
            # 默认获取30天
            return 30
    
    def _update_stock_fund_flow(self, days: int, enabled=None) -> Dict:
        """
        更新个股资金流向
        
        流程：
        1. 计算时间范围
        2. 删除该时间段的旧数据
        3. 获取新数据
        4. 插入新数据
        
        参数：
            days: 获取最近多少天的数据
        
        返回：
            {'added': int, 'updated': int, 'failed': int}
        """
        added = 0
        updated = 0
        failed = 0
        
        try:
            # 【2026-09-25 **停用** ✗】个股资金流的**规范表**是 `stock_moneyflow_daily` ✓
            #   （主源 `moneyflow_dc` ✓、4,276,029 行 ✓、日频 ✓、日期格式 YYYY-MM-DD ✓，
            #    由 `moneyflow_dc_collector` 维护 ✓）。
            #   本方法维护的旧表 `stock_fund_flow` 实测**93 行全部为空值** ✗✓：
            #     · `stock_code` 恒为空串 ✗ —— 源返回的字段名是 `ts_code` ✗，代码却取 `code` ✗
            #     · 6 个金额字段恒为 0 ✗ —— 源字段名为 `net_amount/net_buy_amount` ✗，
            #       代码却取 `main_net_flow/super_large_net_flow/...` ✗
            #     · `period` 硬编码 `'5d'` ✗、`flow_date` 存 **YYYYMMDD** ✗（与全库格式不一致 ✗）
            #     · 且 `saved += 1` 会**假装成功** ✗（值全空也计入"已保存" ✗）
            #   全仓**无任何读取方** ✓ ⇒ 唯一效果是持续产生垃圾行并污染更新窗口计算 ✗
            #   → 默认**停用** ✗；如需恢复旧表回填，置 true ✓（但请注意上述字段名错位 ✗）
            if enabled is None:
                enabled = self._legacy_stock_ff_enabled()
            if not enabled:
                # 【2026-09-28 减噪 ✓】"已停用 ⇒ 跳过"属**常态** ✗ ⇒ 降 `debug` ✓
                #   （配置文件里那行注释已足够说明 ✓，无需每轮更新播报 ✓）
                logger.debug("个股资金流**旧表 stock_fund_flow 已停用** ✓ "
                             "（规范表 = stock_moneyflow_daily ✓）→ 跳过；"
                             "如需回填旧表请置 update.legacy_stock_fund_flow.enabled=true ✓")
                return {'added': 0, 'updated': 0, 'failed': 0, 'skipped': True}
            logger.info(f"更新个股资金流向: 获取最近 {days} 天的数据...")
            
            # 计算时间范围
            end_date_str = datetime.now().strftime('%Y-%m-%d')
            start_date_str = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            logger.debug(f"时间范围: {start_date_str} 到 {end_date_str}")
            
            # 删除该时间段的旧数据
            logger.debug(f"删除 {start_date_str} 到 {end_date_str} 的旧数据...")
            delete_sql = "DELETE FROM stock_fund_flow WHERE flow_date >= ? AND flow_date <= ?"
            self.db_manager.execute_with_retry(delete_sql, (start_date_str, end_date_str))
            
            # 获取新数据 - 转换日期格式为 YYYYMMDD
            logger.debug(f"获取 {start_date_str} 到 {end_date_str} 的个股资金流向数据...")
            start_date_fmt = datetime.strptime(start_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            end_date_fmt = datetime.strptime(end_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            df_fund_flow = self.fund_flow_fetcher._fetch_daily_stock_moneyflow(start_date_fmt, end_date_fmt, None)
            
            if df_fund_flow is not None and len(df_fund_flow) > 0:
                # 插入新数据
                logger.debug(f"插入 {len(df_fund_flow)} 条个股资金流向数据...")
                added = self._save_stock_fund_flow_records(df_fund_flow)
                logger.info(f"个股资金流向更新完成: 新增 {added} 条")
            else:
                logger.warning(f"获取个股资金流向数据失败或无数据")
                failed = 1
            
            return {
                'added': added,
                'updated': updated,
                'failed': failed
            }
        
        except Exception as e:
            logger.error(f"更新个股资金流向失败: {str(e)}")
            return {
                'added': added,
                'updated': updated,
                'failed': 1
            }
    
    def _industry_sector_enabled(self) -> bool:
        """行业/板块资金流是否处理 ✓（默认 **False = 暂不处理** ✗，2026-09-25 决策 ✓）

        读取 `config/config.yaml → update.industry_sector_fund_flow.enabled` ✓；
        读不到/非法 → **False** ✓（默认不写 ✗ —— 避免"缺陷修好后突然开始产数据"的行为突变 ✗）。
        """
        cached = getattr(FundFlowUpdater, '_INDUSTRY_SECTOR_ENABLED', None)
        if cached is not None:
            return cached
        val = False
        try:
            import yaml
            from pathlib import Path
            cfg = Path(__file__).resolve().parent.parent / 'config' / 'config.yaml'
            if cfg.exists():
                with open(cfg, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                raw = ((data.get('update') or {}).get('industry_sector_fund_flow') or {}).get('enabled')
                if raw is not None:
                    val = str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
        except Exception as e:
            logger.warning(f"读取 update.industry_sector_fund_flow.enabled 失败（按 false 处理）: {e}")
        FundFlowUpdater._INDUSTRY_SECTOR_ENABLED = val
        return val

    def _assert_table_columns(self, table: str, *required: str) -> None:
        """写入前**硬校验**表结构 ✓（缺列 → 显式抛错 ✗，不再靠 except 静默 ✗）

        【2026-09-25 新增】起因（实证 ✗）：本类的行业/板块 INSERT 列名
        （`trade_date/buy_vol/buy_amount/...` ✗）与真实表结构
        （`flow_date/period/main_net_flow/...` ✓）**完全不同** ✗ →
        每次更新都会抛错 ✗，而异常被外层 `except` 吞掉 ✗ → 表现为
        "表长期 0 行 + 只有一句 warning" ✗✓（典型的静默失败 ✗）。

        现改为写入前校验 ✓：缺列即 `RuntimeError` ✗（日志带**具体列名与建表语句** ✓），
        由调用方记为 `failed` ✓ —— **失败可见** ✓，不再无声 ✗。
        """
        try:
            row = self.db_manager.query_one(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,))
        except Exception as e:
            logger.warning(f"校验 {table} 表结构失败（跳过校验）: {e}")
            return
        if not row:
            raise RuntimeError(f"表 {table} 不存在 ✗ → 拒绝写入（避免静默失败 ✗）")
        sql = row[0] if not isinstance(row, dict) else (row.get('sql') or '')
        sql = sql or ''
        missing = [c for c in required if c not in sql]
        if missing:
            raise RuntimeError(
                f"表 {table} 结构缺少列 {missing} ✗ → 拒绝写入（此前正是因此静默失败 ✗）；"
                f"实际建表语句: {sql[:200]}")
        logger.debug(f"{table} 表结构校验通过 ✓ ({len(required)} 列)")

    def _update_industry_fund_flow(self, days: int, enabled=None) -> Dict:
        """
        更新行业资金流向
        
        流程：
        1. 计算时间范围
        2. 删除该时间段的旧数据
        3. 获取新数据
        4. 插入新数据
        
        参数：
            days: 获取最近多少天的数据
        
        返回：
            {'added': int, 'updated': int, 'failed': int}
        """
        added = 0
        updated = 0
        failed = 0
        
        try:
            # 【2026-09-25 范围决策 ✓】行业/板块资金流**暂不处理** ✗
            #   决策依据（用户 2026-09-25）：这两张表**不在回测复现依赖范围内** ✓
            #   （回测四类数据 = 交易日历 / 个股资金流 / 个股基本面 / 个股事件 ✓）。
            #   注：本轮同时修掉了它的"列名冲突"静默失败 ✗ —— 若不加此闸门，
            #   原"永远失败 ✗→修好后真写入 ✗"会造成**行为突变** ✗（突然开始产数据 ✓）。
            #   故默认 `enabled=false` ✓ 显式跳过并留痕 ✓；日后需要时置 true 即启用 ✓。
            if enabled is None:
                enabled = self._industry_sector_enabled()
            if not enabled:
                # 【2026-09-28 减噪 ✓】"暂不处理"属**常态** ✗ ⇒ 降 `debug` ✓
                logger.debug("行业资金流**暂不处理** ✓（update.industry_sector_fund_flow."
                             "enabled=false）→ 跳过；需要时置 true 启用 ✓")
                return {'added': 0, 'updated': 0, 'failed': 0, 'skipped': True}
            logger.info(f"更新行业资金流向: 获取最近 {days} 天的数据...")
            
            # 计算时间范围
            end_date_str = datetime.now().strftime('%Y-%m-%d')
            start_date_str = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            logger.debug(f"时间范围: {start_date_str} 到 {end_date_str}")
            
            # 删除该时间段的旧数据
            logger.debug(f"删除 {start_date_str} 到 {end_date_str} 的旧数据...")
            delete_sql = "DELETE FROM industry_fund_flow WHERE flow_date >= ? AND flow_date <= ?"
            self.db_manager.execute_with_retry(delete_sql, (start_date_str, end_date_str))
            
            # 获取新数据 - 转换日期格式为 YYYYMMDD
            logger.debug(f"获取 {start_date_str} 到 {end_date_str} 的行业资金流向数据...")
            start_date_fmt = datetime.strptime(start_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            end_date_fmt = datetime.strptime(end_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            df_fund_flow = self.fund_flow_fetcher._fetch_daily_industry_moneyflow(start_date_fmt, end_date_fmt, None)
            
            if df_fund_flow is not None and len(df_fund_flow) > 0:
                # 插入新数据
                logger.debug(f"插入 {len(df_fund_flow)} 条行业资金流向数据...")
                # 【2026-09-25 修复·列名冲突 ✗→✓】统一写入者 ✓
                #   原实现 `_save_industry_fund_flow_records` 的 INSERT 列名为
                #   (industry_name, trade_date, buy_vol, buy_amount, sell_vol, sell_amount,
                #    net_vol, net_amount) ✗ —— 而真实表结构为
                #   (industry_code, industry_name, flow_date, period, main_net_flow,
                #    super_large_net_flow, large_net_flow, medium_net_flow, small_net_flow,
                #    net_flow_rate, created_date) ✓ ⇒ **列名全部不存在** ✗ → 每次都抛错 ✗，
                #   且异常被外层 `except` 吞掉 ✗ → 长期"表 0 行 + 静默失败" ✗✓
                #   现统一委托 `fund_flow_fetcher._save_industry_fund_flow` ✓
                #   （列名与表一致 ✓、写入 period='daily' ✓、含存在性检查走 UPDATE ✓）
                self._assert_table_columns('industry_fund_flow', 'industry_code', 'industry_name',
                                           'flow_date', 'period', 'main_net_flow', 'net_flow_rate')
                added = self.fund_flow_fetcher._save_industry_fund_flow(df_fund_flow, end_date_fmt)
                logger.info(f"行业资金流向更新完成: 新增 {added} 条")
            else:
                logger.warning(f"获取行业资金流向数据失败或无数据")
                failed = 1
            
            return {
                'added': added,
                'updated': updated,
                'failed': failed
            }
        
        except Exception as e:
            logger.error(f"更新行业资金流向失败: {str(e)}")
            return {
                'added': added,
                'updated': updated,
                'failed': 1
            }
    
    def _update_sector_fund_flow(self, days: int, enabled=None) -> Dict:
        """
        更新板块资金流向
        
        流程：
        1. 计算时间范围
        2. 删除该时间段的旧数据
        3. 获取新数据
        4. 插入新数据
        
        参数：
            days: 获取最近多少天的数据
        
        返回：
            {'added': int, 'updated': int, 'failed': int}
        """
        added = 0
        updated = 0
        failed = 0
        
        try:
            # 【2026-09-25 范围决策 ✓】同行业口径：**暂不处理** ✗（默认跳过 ✓，可配置启用 ✓）
            if enabled is None:
                enabled = self._industry_sector_enabled()
            if not enabled:
                # 【2026-09-28 减噪 ✓】"暂不处理"属**常态** ✗ ⇒ 降 `debug` ✓
                logger.debug("板块资金流**暂不处理** ✓（update.industry_sector_fund_flow."
                             "enabled=false）→ 跳过；需要时置 true 启用 ✓")
                return {'added': 0, 'updated': 0, 'failed': 0, 'skipped': True}
            logger.info(f"更新板块资金流向: 获取最近 {days} 天的数据...")
            
            # 计算时间范围
            end_date_str = datetime.now().strftime('%Y-%m-%d')
            start_date_str = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            logger.debug(f"时间范围: {start_date_str} 到 {end_date_str}")
            
            # 删除该时间段的旧数据
            logger.debug(f"删除 {start_date_str} 到 {end_date_str} 的旧数据...")
            delete_sql = "DELETE FROM sector_fund_flow WHERE flow_date >= ? AND flow_date <= ?"
            self.db_manager.execute_with_retry(delete_sql, (start_date_str, end_date_str))
            
            # 获取新数据 - 转换日期格式为 YYYYMMDD
            logger.debug(f"获取 {start_date_str} 到 {end_date_str} 的板块资金流向数据...")
            start_date_fmt = datetime.strptime(start_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            end_date_fmt = datetime.strptime(end_date_str, '%Y-%m-%d').strftime('%Y%m%d')
            df_fund_flow = self.fund_flow_fetcher._fetch_daily_sector_moneyflow(start_date_fmt, end_date_fmt, None)
            
            if df_fund_flow is not None and len(df_fund_flow) > 0:
                # 插入新数据
                logger.debug(f"插入 {len(df_fund_flow)} 条板块资金流向数据...")
                # 【2026-09-25 修复·列名冲突 ✗→✓】同行业口径：统一委托 fetcher ✓
                self._assert_table_columns('sector_fund_flow', 'sector_code', 'sector_name',
                                           'flow_date', 'period', 'main_net_flow', 'net_flow_rate')
                added = self.fund_flow_fetcher._save_sector_fund_flow(df_fund_flow, end_date_fmt)
                logger.info(f"板块资金流向更新完成: 新增 {added} 条")
            else:
                logger.warning(f"获取板块资金流向数据失败或无数据")
                failed = 1
            
            return {
                'added': added,
                'updated': updated,
                'failed': failed
            }
        
        except Exception as e:
            logger.error(f"更新板块资金流向失败: {str(e)}")
            return {
                'added': added,
                'updated': updated,
                'failed': 1
            }
    
    def _save_stock_fund_flow_records(self, df_fund_flow: pd.DataFrame) -> int:
        # 【2026-09-25 起**废弃** ✗】字段名与**源返回**不一致 ✗✓：
        #   源为 `ts_code` / `net_amount` / `net_buy_amount` ✓（见 fund_flow_fetcher ✓），
        #   本方法却取 `code` / `main_net_flow` / `super_large_net_flow` … ✗
        #   ⇒ `stock_code` 恒为空串 ✗、金额恒为 0 ✗（实测 93 行全空 ✓），
        #   还会 `saved += 1` **假装成功** ✗。
        #   ⇒ 请改用规范表 `stock_moneyflow_daily` ✓（`moneyflow_dc_collector` 维护 ✓）
        logger.error("_save_stock_fund_flow_records 已废弃 ✗（字段名与源不符 ⇒ 写入全空值 ✗）；"
                     "个股资金流请使用规范表 stock_moneyflow_daily ✓")
        """
        保存个股资金流向记录到数据库
        
        参数：
            df_fund_flow: 资金流向数据DataFrame
        
        返回：
            保存的记录数
        """
        saved = 0
        
        try:
            # INSERT SQL 语句
            insert_sql = """
            INSERT OR REPLACE INTO stock_fund_flow 
            (stock_code, flow_date, period, main_net_flow, super_large_net_flow, 
             large_net_flow, medium_net_flow, small_net_flow, net_flow_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            # 直接保存数据，不使用事务（由外层调用者管理事务）
            for _, row in df_fund_flow.iterrows():
                try:
                    # 将日期转换为字符串格式
                    date_str = str(row.get('trade_date', '')).split(' ')[0]
                    
                    # 执行 INSERT 操作
                    self.db_manager.execute_with_retry(insert_sql, (
                        row.get('code', ''),
                        date_str,
                        '5d',  # 默认周期为 5 日
                        float(row.get('main_net_flow', 0)),
                        float(row.get('super_large_net_flow', 0)),
                        float(row.get('large_net_flow', 0)),
                        float(row.get('medium_net_flow', 0)),
                        float(row.get('small_net_flow', 0)),
                        float(row.get('net_flow_rate', 0))
                    ))
                    
                    saved += 1
                
                except Exception as e:
                    logger.debug(f"保存个股资金流向数据失败：{str(e)}")
            
            logger.debug(f"保存个股资金流向数据成功：{saved} 条记录")
            
            return saved
        
        except Exception as e:
            logger.error(f"保存个股资金流向数据失败：{str(e)}")
            return 0
    
    def _save_industry_fund_flow_records(self, df_fund_flow: pd.DataFrame) -> int:
        # 【2026-09-25 起**废弃** ✗】此方法的 INSERT 列名（trade_date/buy_vol/buy_amount/
        #   sell_vol/sell_amount/net_vol/net_amount ✗）在真实表结构中**不存在** ✗ →
        #   必然抛错且被上层 except 吞掉 ✗。请改用
        #   `fund_flow_fetcher._save_industry_fund_flow` ✓（列名与表一致 ✓）
        logger.error("_save_industry_fund_flow_records 已废弃 ✗（列名与 industry_fund_flow "
                     "表结构不符，调用必然失败 ✗）→ 请改用 fund_flow_fetcher."
                     "_save_industry_fund_flow ✓")
        """
        保存行业资金流向记录到数据库
        
        参数：
            df_fund_flow: 资金流向数据DataFrame
        
        返回：
            保存的记录数
        """
        saved = 0
        
        try:
            # INSERT SQL 语句
            insert_sql = """
            INSERT OR REPLACE INTO industry_fund_flow 
            (industry_name, trade_date, buy_vol, buy_amount, sell_vol, sell_amount, net_vol, net_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            # 直接保存数据，不使用事务（由外层调用者管理事务）
            for _, row in df_fund_flow.iterrows():
                try:
                    # 将日期转换为字符串格式
                    date_str = str(row['trade_date']).split(' ')[0]
                    
                    # 执行 INSERT 操作
                    self.db_manager.execute_with_retry(insert_sql, (
                        row['industry_name'],
                        date_str,
                        int(row.get('buy_vol', 0)),
                        float(row.get('buy_amount', 0)),
                        int(row.get('sell_vol', 0)),
                        float(row.get('sell_amount', 0)),
                        int(row.get('net_vol', 0)),
                        float(row.get('net_amount', 0))
                    ))
                    
                    saved += 1
                
                except Exception as e:
                    logger.debug(f"保存行业资金流向数据失败：{str(e)}")
            
            logger.debug(f"保存行业资金流向数据成功：{saved} 条记录")
            
            return saved
        
        except Exception as e:
            logger.error(f"保存行业资金流向数据失败：{str(e)}")
            return 0
    
    def _save_sector_fund_flow_records(self, df_fund_flow: pd.DataFrame) -> int:
        # 【2026-09-25 起**废弃** ✗】同 `_save_industry_fund_flow_records`：列名与
        #   `sector_fund_flow` 真实表结构不符 ✗ → 必然失败 ✗。请改用
        #   `fund_flow_fetcher._save_sector_fund_flow` ✓
        logger.error("_save_sector_fund_flow_records 已废弃 ✗（列名与 sector_fund_flow "
                     "表结构不符，调用必然失败 ✗）→ 请改用 fund_flow_fetcher."
                     "_save_sector_fund_flow ✓")
        """
        保存板块资金流向记录到数据库
        
        参数：
            df_fund_flow: 资金流向数据DataFrame
        
        返回：
            保存的记录数
        """
        saved = 0
        
        try:
            # INSERT SQL 语句
            insert_sql = """
            INSERT INTO sector_fund_flow 
            (sector_name, trade_date, buy_vol, buy_amount, sell_vol, sell_amount, net_vol, net_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            # 直接保存数据，不使用事务（由外层调用者管理事务）
            for _, row in df_fund_flow.iterrows():
                try:
                    # 将日期转换为字符串格式
                    date_str = str(row['trade_date']).split(' ')[0]
                    
                    # 执行INSERT操作
                    self.db_manager.execute_with_retry(insert_sql, (
                        row['sector_name'],
                        date_str,
                        int(row.get('buy_vol', 0)),
                        float(row.get('buy_amount', 0)),
                        int(row.get('sell_vol', 0)),
                        float(row.get('sell_amount', 0)),
                        int(row.get('net_vol', 0)),
                        float(row.get('net_amount', 0))
                    ))
                    
                    saved += 1
                
                except Exception as e:
                    logger.debug(f"保存板块资金流向数据失败: {str(e)}")
            
            logger.debug(f"保存板块资金流向数据成功: {saved} 条记录")
            
            return saved
        
        except Exception as e:
            logger.error(f"保存板块资金流向数据失败: {str(e)}")
            return 0
    
    def get_progress(self) -> Dict:
        """获取更新进度"""
        return self.progress.copy()
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.stats.copy()
