"""
PTrade 执行结果反馈解析模块

功能:
  1. 解析 PTrade 原生导出: Fund_YYYYMMDD.csv, Hold_YYYYMMDD.csv
  2. 以 PTrade 数据为准生成 portfolio_YYYY-MM-DD.json（完全覆盖，不继承旧数据）
  3. 反馈处理幂等性检查（同交易日不重复处理）

数据来源: PTrade 系统 15:05 自动导出的 Fund_/Hold_ 文件
核心原则: 自动模式下以 PTrade 数据为准，不继承旧 portfolio 的任何字段
"""

import csv
import json
import logging
import os
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认反馈文件目录（相对于项目根目录）
DEFAULT_FEEDBACK_DIR = "data/running/ptrade_feedback"

# 默认运行数据目录
DEFAULT_RUNNING_DIR = "data/running"

# 默认初始资金
DEFAULT_INITIAL_CAPITAL = 300000.0

# 交易所后缀映射
EXCHANGE_SUFFIX_MAP = {
    "深A": ".SZ",
    "深圳A股": ".SZ",
    "沪A": ".SH",
    "上海A股": ".SH",
}


class PTradeFeedbackHandler:
    """PTrade 反馈处理器

    读取 PTrade 导出的 Fund_/Hold_ CSV 文件，
    转换为 KHunter 兼容的 portfolio JSON 格式。
    
    配置来源优先级（由高到低）：
      1. _init_ 参数传入的 config dict
      2. 自动加载 config/config.yaml 中的 ptrade/trading 节
      3. 模块级默认常量
    """

    def __init__(self, project_root: str = None, config: Dict = None):
        """初始化反馈处理器

        Args:
            project_root: 项目根目录，默认为当前文件的上两级目录
            config: 主配置字典（如已加载的 config.yaml），可选
                    支持 ptrade 和 trading 两个顶层键
        """
        # 确定项目根目录
        if project_root is None:
            project_root = str(Path(__file__).resolve().parent.parent.parent)
        self.project_root = project_root

        # 加载配置（优先使用传入的 config，否则自动读取 config.yaml）
        if config is None:
            config = self._load_main_config(project_root)
        self._config = config
        # 解析 ptrade 子配置
        ptrade_cfg = config.get('ptrade', {}) if config else {}
        # PTrade 反馈文件所在目录（来自配置或默认值）
        feedback_dir_rel = ptrade_cfg.get('feedback_dir', DEFAULT_FEEDBACK_DIR)
        self.feedback_dir = os.path.join(project_root, feedback_dir_rel)
        # PTrade 是否启用
        self.enabled = ptrade_cfg.get('enabled', True) if ptrade_cfg else True
        # 返回文件读取模式
        self.feedback_mode = ptrade_cfg.get('feedback_mode', 'file') if ptrade_cfg else 'file'
        # KHunter 运行数据目录
        self.running_dir = os.path.join(project_root, DEFAULT_RUNNING_DIR)
        # 初始资金（来自 trading.initial_capital 或默认值）
        trading_cfg = config.get('trading', {}) if config else {}
        self.initial_capital = float(trading_cfg.get(
            'initial_capital', DEFAULT_INITIAL_CAPITAL))

        logger.info(
            f"PTradeFeedbackHandler 初始化: feedback_dir={self.feedback_dir}, "
            f"enabled={self.enabled}, feedback_mode={self.feedback_mode}, "
            f"initial_capital={self.initial_capital}")

    @staticmethod
    def _load_main_config(project_root: str) -> Dict:
        """加载 config/config.yaml 主配置文件
        
        Args:
            project_root: 项目根目录
            
        Returns:
            配置字典，加载失败返回空字典
        """
        config_path = os.path.join(project_root, "config", "config.yaml")
        if os.path.isfile(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"加载 config.yaml 失败: {e}")
        return {}

    # ========== 文件检查 ==========

    def check_feedback_exists(self, date_str: str) -> bool:
        """检查指定日期的 PTrade 反馈文件是否都存在

        Args:
            date_str: 日期，格式 YYYYMMDD

        Returns:
            Fund 和 Hold 两个文件都存在返回 True
        """
        fund_file = os.path.join(
            self.feedback_dir, f"Fund_{date_str}.csv")
        hold_file = os.path.join(
            self.feedback_dir, f"Hold_{date_str}.csv")
        fund_exists = os.path.isfile(fund_file)
        hold_exists = os.path.isfile(hold_file)
        if not fund_exists:
            logger.info(f"PTrade 反馈: Fund 文件不存在: {fund_file}")
        if not hold_exists:
            logger.info(f"PTrade 反馈: Hold 文件不存在: {hold_file}")
        return fund_exists and hold_exists

    def find_latest_feedback_date(self) -> Optional[str]:
        """扫描反馈目录，找到最新的反馈文件日期

        只考虑 Fund 和 Hold 同时存在的日期。

        Returns:
            最新日期 YYYYMMDD，无文件返回 None
        """
        if not os.path.isdir(self.feedback_dir):
            return None
        # 收集所有文件名
        files = os.listdir(self.feedback_dir)
        # 提取 Fund_*.csv 和 Hold_*.csv 中的日期
        fund_dates = set()
        hold_dates = set()
        for f in files:
            if f.startswith("Fund_") and f.endswith(".csv"):
                # Fund_YYYYMMDD.csv → YYMMDD
                date_part = f[5:-4]
                if len(date_part) == 8:
                    fund_dates.add(date_part)
            elif f.startswith("Hold_") and f.endswith(".csv"):
                date_part = f[5:-4]
                if len(date_part) == 8:
                    hold_dates.add(date_part)
        # 只保留两个文件都存在的日期
        common_dates = fund_dates & hold_dates
        if not common_dates:
            return None
        # 返回最新日期
        return max(common_dates)

    # ========== CSV 解析 ==========

    def read_fund(self, date_str: str) -> Dict:
        """解析 Fund_YYYYMMDD.csv，提取资金数据

        PTrade 原生格式（第 2 行为数据，第 1 行为表头）:
          列 0: 资金账号 / 列 3: 可用资金 / 列 5: 总资产 / 列 9: 证券市值

        Args:
            date_str: 日期 YYYYMMDD

        Returns:
            {available_cash, total_asset, market_value}
        """
        fund_file = os.path.join(
            self.feedback_dir, f"Fund_{date_str}.csv")
        if not os.path.isfile(fund_file):
            raise FileNotFoundError(f"Fund 文件不存在: {fund_file}")

        with open(fund_file, 'r', encoding='gbk') as f:
            reader = csv.reader(f)
            # 读取表头并构建列名索引
            headers = next(reader)
            # 构建列名 → 列索引映射
            col_map = {h.strip(): i for i, h in enumerate(headers)}
            # 读取数据行
            for row in reader:
                if not row or all(c.strip() == '' for c in row):
                    continue
                # 安全提取 float 值
                def _safe_float(idx):
                    if idx < len(row) and row[idx].strip():
                        return float(row[idx].strip())
                    return 0.0
                # 使用列名定位关键字段
                available_cash = _safe_float(col_map.get("可用资金", 3))
                total_asset = _safe_float(col_map.get("总资产", 5))
                market_value = _safe_float(col_map.get("证券市值", 9))
                result = {
                    "available_cash": round(available_cash, 2),
                    "total_asset": round(total_asset, 2),
                    "market_value": round(market_value, 2),
                }
                logger.info(
                    f"PTrade 反馈: 解析资金数据 {date_str} - "
                    f"可用资金={result['available_cash']}, "
                    f"总资产={result['total_asset']}, "
                    f"证券市值={result['market_value']}")
                return result
        # 无数据行
        return {"available_cash": 0.0, "total_asset": 0.0, "market_value": 0.0}

    def read_holdings(self, date_str: str) -> List[Dict]:
        """解析 Hold_YYYYMMDD.csv，提取持仓列表

        PTrade 原生格式:
          列 3: 交易类别 (深A/沪A) → 推导 suffix
          列 4: 证券代码 → stock_code (+ suffix)
          列 5: 证券名称 → stock_name
          列 6: 持有数量 → quantity
          列 7: 可用数量 → available_volume
          列 8: 盈亏金额 → profit_loss
          列 13: 成本价 → buy_price
          列 14: 证券市值 → market_value

        current_price = market_value / quantity (反算)

        Args:
            date_str: 日期 YYYYMMDD

        Returns:
            持仓列表 [{stock_code, stock_name, quantity, ...}]
        """
        hold_file = os.path.join(
            self.feedback_dir, f"Hold_{date_str}.csv")
        if not os.path.isfile(hold_file):
            raise FileNotFoundError(f"Hold 文件不存在: {hold_file}")

        holdings = []
        with open(hold_file, 'r', encoding='gbk') as f:
            reader = csv.reader(f)
            # 读取表头并构建列名索引
            headers = next(reader)
            col_map = {h.strip(): i for i, h in enumerate(headers)}

            for row in reader:
                if not row or all(c.strip() == '' for c in row):
                    continue
                # 安全提取值
                def _safe_str(idx):
                    if idx < len(row):
                        return row[idx].strip()
                    return ""

                def _safe_int(idx):
                    val = row[idx].strip() if idx < len(row) else "0"
                    return int(float(val)) if val else 0

                def _safe_float(idx):
                    val = row[idx].strip() if idx < len(row) else "0"
                    return float(val) if val else 0.0
                # 提取关键字段
                trade_category = _safe_str(col_map.get("交易类别", 3))
                stock_code_raw = _safe_str(col_map.get("证券代码", 4))
                stock_name = _safe_str(col_map.get("证券名称", 5))
                quantity = _safe_int(col_map.get("持有数量", 6))
                available_volume = _safe_int(col_map.get("可用数量", 7))
                profit_loss = _safe_float(col_map.get("盈亏金额", 8))
                cost_price = _safe_float(col_map.get("成本价", 13))
                market_value = _safe_float(col_map.get("证券市值", 14))
                # 推导 suffix 并构造完整代码
                suffix = self._get_stock_suffix(trade_category, stock_code_raw)
                stock_code = f"{stock_code_raw}{suffix}"
                # 反算当前价
                if quantity > 0:
                    current_price = round(market_value / quantity, 2)
                else:
                    current_price = 0.0
                holding = {
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "quantity": quantity,
                    "available_volume": available_volume,
                    "buy_price": round(cost_price, 4),
                    "market_value": round(market_value, 2),
                    "current_price": current_price,
                    "profit_loss": round(profit_loss, 2),
                }
                holdings.append(holding)
                logger.info(
                    f"PTrade 反馈: 持仓 {stock_code} {stock_name} "
                    f"数量={quantity} 成本价={cost_price} 市值={market_value}")
        return holdings

    # ========== 代码转换 ==========

    @staticmethod
    def _get_stock_suffix(trade_category: str, stock_code: str) -> str:
        """根据交易类别和证券代码推导交易所后缀

        Args:
            trade_category: PTrade 交易类别 (深A/沪A)
            stock_code: 6位数字代码

        Returns:
            .SZ 或 .SH
        """
        # 优先使用交易类别判断
        suffix = EXCHANGE_SUFFIX_MAP.get(trade_category, "")
        if suffix:
            return suffix
        # 回退：根据代码前缀判断
        if stock_code.startswith(('6', '9')):
            return ".SH"
        elif stock_code.startswith(('0', '3', '2')):
            return ".SZ"
        # 默认
        logger.warning(f"无法判断证券交易所后缀: {trade_category}, {stock_code}")
        return ".SZ"

    # ========== Portfolio 生成 ==========

    def build_portfolio(self, feedback_date: str) -> Dict:
        """根据 PTrade 反馈构建 portfolio 数据（完全覆盖，不继承旧数据）

        自动模式下 PTrade 数据就是唯一真实数据源，不需要从旧 portfolio 继承任何字段。

        Args:
            feedback_date: PTrade 反馈日期 YYYYMMDD

        Returns:
            portfolio 字典，可直接写入 JSON
        """
        # 读取 PTrade 资金和持仓数据
        fund = self.read_fund(feedback_date)
        ptrade_holdings = self.read_holdings(feedback_date)
        # 构建 positions（只包含 PTrade 导出的真实字段）
        new_positions = {}
        for h in ptrade_holdings:
            code = h["stock_code"]
            buy_price = h["buy_price"]
            quantity = h["quantity"]
            buy_amount = round(buy_price * quantity, 2)
            # 计算盈亏比例
            profit_loss = h["profit_loss"]
            profit_rate = round(profit_loss / (buy_amount + 0.01), 4) \
                if buy_amount > 0 else 0.0
            # 只使用 PTrade 数据构造持仓条目
            position = {
                "stock_name": h["stock_name"],
                "quantity": quantity,
                "buy_price": buy_price,
                "buy_date": self._ymd_to_dash(feedback_date),
                "current_price": h["current_price"],
                "buy_amount": buy_amount,
                "buy_fee": 0.0,
                "total_cost": buy_amount,
                "market_value": h["market_value"],
                "profit_loss": profit_loss,
                "profit_rate": profit_rate,
                "available_volume": h.get("available_volume", quantity),
            }
            new_positions[code] = position
        # 构建 portfolio
        cash = fund["available_cash"]
        portfolio = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cash": cash,
            "total_asset": fund["total_asset"],
            "market_value": fund["market_value"],
            "initial_capital": self.initial_capital,
            "positions": new_positions,
        }
        logger.info(
            f"PTrade 反馈: 构建 portfolio 完成 - "
            f"现金={cash}, 总资产={fund['total_asset']}, 持仓数={len(new_positions)}")
        return portfolio

    # ========== 主流程 ==========

    def process(self, feedback_date: str) -> Dict:
        """完整反馈处理流程（自动模式，PTrade 数据完全覆盖）

        步骤:
          1. 检查 PTrade 反馈文件是否存在
          2. 解析 Fund + Hold → 构建新 portfolio
          3. 保存 portfolio JSON

        Args:
            feedback_date: PTrade 反馈日期 YYYYMMDD

        Returns:
            处理结果 {success, portfolio_file, fund_data, holdings}
        """
        # 步骤1: 检查文件
        if not self.check_feedback_exists(feedback_date):
            return {
                "success": False,
                "error": f"PTrade 反馈文件不存在: {feedback_date}",
            }
        # 步骤2: 读取资金和持仓
        fund = self.read_fund(feedback_date)
        holdings = self.read_holdings(feedback_date)
        # 步骤3: 构建新 portfolio（自动模式不继承旧数据）
        portfolio = self.build_portfolio(feedback_date)
        # 步骤4: 保存
        pf_date_dash = self._ymd_to_dash(feedback_date)
        portfolio_file = os.path.join(
            self.running_dir, f"portfolio_{pf_date_dash}.json")
        with open(portfolio_file, 'w', encoding='utf-8') as f:
            json.dump(portfolio, f, ensure_ascii=False, indent=2)
        logger.info(f"PTrade 反馈: portfolio 已保存 → {portfolio_file}")
        return {
            "success": True,
            "feedback_date": feedback_date,
            "portfolio_date": pf_date_dash,
            "portfolio_file": portfolio_file,
            "fund_data": fund,
            "holdings": holdings,
            "portfolio": portfolio,
        }

    # ========== 工具方法 ==========

    @staticmethod
    def _ymd_to_dash(date_str: str) -> str:
        """YYYYMMDD → YYYY-MM-DD"""
        if len(date_str) == 8:
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        return date_str

    @staticmethod
    def _ymd_to_compact(date_str: str) -> str:
        """YYYY-MM-DD → YYYYMMDD"""
        return date_str.replace("-", "")


# ========== 便捷函数 ==========

def process_ptrade_feedback(
        feedback_date: str,
        project_root: str = None,
        config: Dict = None) -> Dict:
    """便捷函数：处理 PTrade 反馈文件

    Args:
        feedback_date: PTrade 反馈日期 YYYYMMDD
        project_root: 项目根目录
        config: 主配置字典（可选，支持 ptrade 和 trading 键）

    Returns:
        处理结果
    """
    handler = PTradeFeedbackHandler(project_root=project_root, config=config)
    return handler.process(feedback_date)


def get_pending_feedback_date(
        last_feedback_date: Optional[str],
        project_root: str = None,
        config: Dict = None) -> Optional[str]:
    """获取待处理的 PTrade 反馈日期

    与 last_feedback_date 对比，返回更新的交易日日期供处理。

    Args:
        last_feedback_date: 上次已处理的反馈日期 YYYYMMDD
        project_root: 项目根目录
        config: 主配置字典（可选，支持 ptrade 和 trading 键）

    Returns:
        待处理日期，无新数据返回 None
    """
    handler = PTradeFeedbackHandler(project_root=project_root, config=config)
    latest = handler.find_latest_feedback_date()
    if latest is None:
        return None
    if last_feedback_date is None:
        return latest
    # 对比：有新日期则返回
    if latest > last_feedback_date:
        return latest
    return None
