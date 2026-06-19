# -*- coding: utf-8 -*-
"""
个股评分 API 接口模块

提供 Flask Blueprint 实现的 RESTful API，包括：
- GET  /api/stock/score/<code>  获取单只股票评分
- POST /api/stock/scores        获取批量评分
- GET  /api/stock/ranking       获取评分排行榜
- GET  /api/stock/history/<code> 获取历史评分

所有接口统一返回格式：
  成功: {"code": 0, "message": "success", "data": ...}
  失败: {"code": -1, "message": "错误描述"}
"""

import re
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

# 导入评分计算引擎和数据访问对象
from trading.stock_score_calculator import StockScoreCalculator
from trading.stock_score_dao import StockScoreDAO
from trading.stock_score_models import StockScore
from utils.db_manager import DBManager

# 配置日志记录器
logger = logging.getLogger(__name__)

# 创建 Flask 蓝图，统一前缀 /api/stock
stock_score_bp = Blueprint('stock_score', __name__, url_prefix='/api/stock')

# 股票代码正则：必须为6位数字
STOCK_CODE_PATTERN = re.compile(r'^\d{6}$')

# 日期格式正则：YYYYMMDD
DATE_PATTERN = re.compile(r'^\d{8}$')

# 排行榜允许的排序字段白名单
ALLOWED_SORT_FIELDS = {
    "total_score", "technical_score", "moneyflow_score",
    "fundamental_score", "sector_score", "event_score",
}


# ============================================================
# 辅助函数
# ============================================================

def _validate_stock_code(code: str) -> str:
    """
    验证股票代码格式

    规则：必须为6位纯数字字符串。

    参数:
        code: 待验证的股票代码
    返回:
        str: 验证失败时返回错误信息，成功返回空字符串
    """
    # 检查是否为空
    if not code:
        return "股票代码不能为空"
    # 检查是否为6位数字
    if not STOCK_CODE_PATTERN.match(code):
        return "股票代码必须为6位数字"
    # 验证通过
    return ""


def _validate_date(date_str: str) -> str:
    """
    验证日期格式（YYYYMMDD）

    参数:
        date_str: 待验证的日期字符串
    返回:
        str: 验证失败时返回错误信息，成功返回空字符串
    """
    # 检查是否为空（日期通常可选）
    if not date_str:
        return ""
    # 检查格式是否为8位数字
    if not DATE_PATTERN.match(date_str):
        return "日期格式必须为YYYYMMDD"
    # 尝试解析日期，验证合法性
    try:
        datetime.strptime(date_str, "%Y%m%d")
    except ValueError:
        return "日期不合法"
    # 验证通过
    return ""


def _format_date(date_str: str) -> str:
    """
    将 YYYYMMDD 格式转换为 YYYY-MM-DD 格式

    DAO 层使用 YYYY-MM-DD 格式存储日期，
    API 层接收 YYYYMMDD 格式，需要转换。

    参数:
        date_str: YYYYMMDD 格式的日期字符串
    返回:
        str: YYYY-MM-DD 格式的日期字符串
    """
    # 空字符串直接返回
    if not date_str:
        return ""
    # 如果已经是 YYYY-MM-DD 格式，直接返回
    if "-" in date_str:
        return date_str
    # 转换 YYYYMMDD -> YYYY-MM-DD
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def _success_response(data, message="success"):
    """
    构建成功响应

    参数:
        data: 响应数据
        message: 成功消息
    返回:
        Flask JSON 响应
    """
    return jsonify({
        "code": 0,
        "message": message,
        "data": data,
    })


def _error_response(message, http_status=400):
    """
    构建错误响应

    参数:
        message: 错误描述
        http_status: HTTP 状态码
    返回:
        Flask JSON 响应和状态码
    """
    return jsonify({
        "code": -1,
        "message": message,
    }), http_status


def _get_calculator():
    """
    获取评分计算引擎实例（延迟初始化）

    每次请求创建新实例，避免线程安全问题。

    返回:
        StockScoreCalculator: 评分计算引擎实例
    """
    # 使用全局 DBManager 实例
    from utils.global_db import get_global_db
    db_manager = get_global_db()
    return StockScoreCalculator(db_manager=db_manager)


def _get_dao():
    """
    获取数据访问对象实例（延迟初始化）

    返回:
        StockScoreDAO: 数据访问对象实例
    """
    return StockScoreDAO()


def _is_score_complete(score) -> bool:
    """
    检查评分数据的维度详情是否完整
    缓存中可能存在早期版本保存的不完整数据

    参数:
        score: StockScore 对象
    返回:
        bool: 数据是否完整
    """
    # 检查 stock_name 是否存在
    if not score.stock_name:
        return False
    # 检查维度详情是否有实质内容
    d = score.to_dict()
    dims = d.get("dimensions", {})
    # 板块维度必须有 sector_name
    sector = dims.get("sector", {})
    if not sector.get("sector_name"):
        return False
    return True


def _get_default_date() -> str:
    """
    获取默认评分日期（今天，YYYY-MM-DD 格式）

    返回:
        str: 今天的日期字符串
    """
    return datetime.now().strftime("%Y-%m-%d")


def _get_latest_score_date(stock_code: str, dao: StockScoreDAO) -> str:
    """
    获取指定股票的最新评分日期

    参数:
        stock_code: 股票代码
        dao: 数据访问对象
    返回:
        str: 最新评分日期（YYYY-MM-DD 格式），如果没有评分记录则返回今天的日期
    """
    try:
        # 查询stock_score表中的最新日期
        sql = """
            SELECT MAX(score_date) as latest_date 
            FROM stock_score 
            WHERE stock_code = ?
        """
        result = dao.db.query_one(sql, (stock_code,))
        if result and result.get('latest_date'):
            return result['latest_date']
        
        # 如果stock_score表中没有记录，查询stock_score_detail表
        sql = """
            SELECT MAX(score_date) as latest_date 
            FROM stock_score_detail 
            WHERE stock_code = ?
        """
        result = dao.db.query_one(sql, (stock_code,))
        if result and result.get('latest_date'):
            return result['latest_date']
        
        # 如果都没有记录，返回今天的日期
        return _get_default_date()
    except Exception as e:
        logger.error(f"获取最新评分日期失败: {e}")
        return _get_default_date()


# ============================================================
# 接口1：获取单只股票评分
# ============================================================

@stock_score_bp.route('/score/<code>', methods=['GET'])
def get_stock_score(code):
    """
    获取单只股票评分

    路径参数:
        code: 股票代码（6位数字）
    查询参数:
        date: 评分日期 YYYYMMDD（可选，默认最新）

    返回:
        成功: {"code": 0, "message": "success", "data": {...}}
        失败: {"code": -1, "message": "错误描述"}
    """
    try:
        # 验证股票代码格式
        code_error = _validate_stock_code(code)
        if code_error:
            logger.warning(f"股票代码验证失败: {code} - {code_error}")
            return _error_response(code_error)

        # 获取并验证日期参数
        date_str = request.args.get('date', '').strip()
        date_error = _validate_date(date_str)
        if date_error:
            logger.warning(f"日期验证失败: {date_str} - {date_error}")
            return _error_response(date_error)

        # 转换日期格式（YYYYMMDD -> YYYY-MM-DD）
        if date_str:
            score_date = _format_date(date_str)
        else:
            # 如果没有指定日期，使用股票的最新评分日期
            dao = _get_dao()
            score_date = _get_latest_score_date(code, dao)
            logger.info(f"使用最新评分日期: {score_date}")
        
        # 先尝试从数据库获取已有评分
        dao = _get_dao() if 'dao' not in locals() else dao
        score = dao.get_score(code, score_date)

        # 检查缓存数据是否完整（维度详情可能缺失）
        if score and not _is_score_complete(score):
            logger.info(f"缓存数据不完整，重新计算: {code} {score_date}")
            score = None

        # 如果数据库中没有或不完整，则实时计算
        if not score:
            logger.info(f"实时计算评分: {code} {score_date}")
            calculator = _get_calculator()
            # 调用计算引擎计算评分
            score = calculator.calculate_score(code, score_date)
            # 保存计算结果到数据库
            dao.save_score(score)

        # 补全股票名称（数据库缓存可能缺失 stock_name）
        if not score.stock_name:
            try:
                from utils.db_manager import DBManager
                from utils.global_db import get_global_db
                db = get_global_db()
                result = db.query(
                    "SELECT name FROM stock_basic WHERE code = ? LIMIT 1",
                    (code,)
                )
                if result:
                    score.stock_name = result[0].get("name", "")
            except Exception as name_err:
                logger.debug(f"补全股票名称失败: {name_err}")

        # 返回评分数据
        logger.info(f"获取评分成功: {code} {score_date} 总分={score.total_score}")
        return _success_response(score.to_dict())

    except Exception as e:
        # 记录异常并返回错误响应
        logger.error(f"获取股票评分失败: {code} - {str(e)}")
        return _error_response(f"获取评分失败: {str(e)}", 500)


# ============================================================
# 接口2：获取批量评分
# ============================================================

@stock_score_bp.route('/scores', methods=['POST'])
def get_batch_scores():
    """
    获取批量股票评分

    请求体:
        {
            "codes": ["000001", "000002"],
            "date": "20260403"  (可选)
        }

    返回:
        成功: {"code": 0, "message": "success", "data": [...]}
        失败: {"code": -1, "message": "错误描述"}
    """
    try:
        # 解析请求体 JSON
        data = request.get_json(silent=True)
        if not data:
            return _error_response("请求体不能为空")

        # 获取股票代码列表
        codes = data.get('codes', [])
        if not codes:
            return _error_response("股票代码列表不能为空")

        # 验证 codes 是否为列表
        if not isinstance(codes, list):
            return _error_response("codes 必须为数组")

        # 限制批量查询数量，防止滥用
        if len(codes) > 500:
            return _error_response("批量查询最多支持500只股票")

        # 逐个验证股票代码格式
        for c in codes:
            code_error = _validate_stock_code(str(c))
            if code_error:
                return _error_response(f"股票代码 {c} 格式错误: {code_error}")

        # 获取并验证日期参数
        date_str = data.get('date', '').strip() if data.get('date') else ''
        date_error = _validate_date(date_str)
        if date_error:
            return _error_response(date_error)

        # 转换日期格式
        score_date = _format_date(date_str) if date_str else _get_default_date()

        # 先从数据库批量查询已有评分
        dao = _get_dao()
        results = []
        missing_codes = []

        # 逐个查询数据库
        for c in codes:
            score = dao.get_score(str(c), score_date)
            if score:
                results.append(score.to_dict())
            else:
                # 记录缺失的股票代码
                missing_codes.append(str(c))

        # 对缺失的股票实时计算评分
        if missing_codes:
            logger.info(f"批量评分: {len(missing_codes)} 只股票需要实时计算")
            calculator = _get_calculator()
            # 调用批量计算引擎
            batch_scores = calculator.calculate_batch_scores(missing_codes, score_date)
            # 保存并添加到结果
            for score in batch_scores:
                dao.save_score(score)
                results.append(score.to_dict())

        # 记录批量查询日志
        logger.info(f"批量评分完成: 共 {len(results)} 只股票")
        return _success_response(results)

    except Exception as e:
        # 记录异常并返回错误响应
        logger.error(f"批量评分失败: {str(e)}")
        return _error_response(f"批量评分失败: {str(e)}", 500)


# ============================================================
# 接口3：获取评分排行榜
# ============================================================

@stock_score_bp.route('/ranking', methods=['GET'])
def get_ranking():
    """
    获取评分排行榜

    查询参数:
        limit: 返回数量（默认100，最大500）
        offset: 偏移量（默认0）
        sort_by: 排序字段（默认 total_score）
        date: 评分日期 YYYYMMDD（可选，默认最新）

    返回:
        成功: {"code": 0, "message": "success", "data": {"total": N, "items": [...]}}
        失败: {"code": -1, "message": "错误描述"}
    """
    try:
        # 获取分页参数
        try:
            limit = int(request.args.get('limit', 100))
        except (ValueError, TypeError):
            return _error_response("limit 参数必须为整数")

        try:
            offset = int(request.args.get('offset', 0))
        except (ValueError, TypeError):
            return _error_response("offset 参数必须为整数")

        # 验证分页参数范围
        if limit < 1 or limit > 500:
            return _error_response("limit 必须在 1-500 之间")
        if offset < 0:
            return _error_response("offset 不能为负数")

        # 获取排序字段
        sort_by = request.args.get('sort_by', 'total_score').strip()
        if sort_by not in ALLOWED_SORT_FIELDS:
            return _error_response(
                f"sort_by 不支持 '{sort_by}'，"
                f"可选值: {', '.join(ALLOWED_SORT_FIELDS)}"
            )

        # 获取并验证日期参数
        date_str = request.args.get('date', '').strip()
        date_error = _validate_date(date_str)
        if date_error:
            return _error_response(date_error)

        # 转换日期格式
        score_date = _format_date(date_str) if date_str else _get_default_date()

        # 从 DAO 获取排行榜数据
        dao = _get_dao()
        items = dao.get_ranking(
            score_date=score_date,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
        )

        # 查询该日期的评分总数
        total = _get_ranking_total(dao, score_date)

        # 构建分页响应
        logger.info(
            f"排行榜查询: date={score_date} sort={sort_by} "
            f"limit={limit} offset={offset} total={total}"
        )
        return _success_response({
            "total": total,
            "items": items,
        })

    except Exception as e:
        # 记录异常并返回错误响应
        logger.error(f"获取排行榜失败: {str(e)}")
        return _error_response(f"获取排行榜失败: {str(e)}", 500)


def _get_ranking_total(dao: StockScoreDAO, score_date: str) -> int:
    """
    查询指定日期的评分记录总数

    参数:
        dao: 数据访问对象
        score_date: 评分日期（YYYY-MM-DD 格式）
    返回:
        int: 评分记录总数
    """
    try:
        # 执行 COUNT 查询
        sql = "SELECT COUNT(*) as cnt FROM stock_score WHERE score_date = ?"
        result = dao.db.query_one(sql, (score_date,))
        # 返回总数
        return result.get("cnt", 0) if result else 0
    except Exception as e:
        logger.error(f"查询排行榜总数失败: {str(e)}")
        return 0


# ============================================================
# 接口4：获取历史评分
# ============================================================

@stock_score_bp.route('/history/<code>', methods=['GET'])
def get_stock_history(code):
    """
    获取股票历史评分

    路径参数:
        code: 股票代码（6位数字）
    查询参数:
        start_date: 开始日期 YYYYMMDD（可选，默认30天前）
        end_date: 结束日期 YYYYMMDD（可选，默认今天）

    返回:
        成功: {"code": 0, "message": "success", "data": [...]}
        失败: {"code": -1, "message": "错误描述"}
    """
    try:
        # 验证股票代码格式
        code_error = _validate_stock_code(code)
        if code_error:
            logger.warning(f"股票代码验证失败: {code} - {code_error}")
            return _error_response(code_error)

        # 获取并验证开始日期
        start_str = request.args.get('start_date', '').strip()
        start_error = _validate_date(start_str)
        if start_error:
            return _error_response(f"start_date {start_error}")

        # 获取并验证结束日期
        end_str = request.args.get('end_date', '').strip()
        end_error = _validate_date(end_str)
        if end_error:
            return _error_response(f"end_date {end_error}")

        # 设置默认日期范围（最近30天）
        if start_str:
            start_date = _format_date(start_str)
        else:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        if end_str:
            end_date = _format_date(end_str)
        else:
            end_date = datetime.now().strftime("%Y-%m-%d")

        # 验证日期范围逻辑
        if start_date > end_date:
            return _error_response("start_date 不能晚于 end_date")

        # 从 DAO 获取历史评分
        dao = _get_dao()
        history = dao.get_history(code, start_date, end_date)

        # 将 StockScore 对象列表转换为字典列表
        history_data = [score.to_dict() for score in history]

        # 记录查询日志
        logger.info(
            f"历史评分查询: {code} {start_date}~{end_date} "
            f"共 {len(history_data)} 条"
        )
        return _success_response(history_data)

    except Exception as e:
        # 记录异常并返回错误响应
        logger.error(f"获取历史评分失败: {code} - {str(e)}")
        return _error_response(f"获取历史评分失败: {str(e)}", 500)


def calculate_stock_score(stock_code: str, score_date: str) -> float:
    """
    计算股票评分

    参数:
        stock_code: 股票代码
        score_date: 评分日期，格式 YYYY-MM-DD
    返回:
        float: 股票评分
    """
    try:
        calculator = _get_calculator()
        score_obj = calculator.calculate_score(stock_code, score_date)
        return score_obj.total_score
    except Exception as e:
        logger.error(f"计算股票评分失败: {str(e)}")
        return 0.0
