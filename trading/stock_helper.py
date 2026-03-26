# 股票辅助模块 - 提供股票信息查询和选股历史验证功能

import json
import sqlite3
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 股票名称文件路径
STOCK_NAMES_FILE = PROJECT_ROOT / 'data' / 'stock_names.json'

# 选股历史数据库路径
SELECTION_DB_PATH = PROJECT_ROOT / 'data' / 'stock_selection.db'


class StockHelper:
    """股票辅助类 - 提供股票信息查询和选股历史验证"""

    @staticmethod
    def get_stock_info(code: str) -> Optional[Dict[str, Any]]:
        """
        获取股票信息（名称）
        
        参数:
            code: 股票代码（6位数字）
        
        返回:
            {
                "code": "000001",
                "name": "平安银行"
            }
            或 None 如果股票不存在
        """
        try:
            # 验证代码格式
            if not code or len(code) != 6 or not code.isdigit():
                return None
            
            # 读取股票名称文件
            if not STOCK_NAMES_FILE.exists():
                return None
            
            with open(STOCK_NAMES_FILE, 'r', encoding='utf-8') as f:
                stock_names = json.load(f)
            
            # 查询股票名称
            if code not in stock_names:
                return None
            
            # 处理股票名称（可能是字符串或字典）
            stock_name_info = stock_names[code]
            if isinstance(stock_name_info, dict):
                name = stock_name_info.get('name', '未知')
            else:
                name = stock_name_info
            
            return {
                'code': code,
                'name': name
            }
        
        except Exception as e:
            # 记录错误并返回None
            return None

    @staticmethod
    def check_selection_history(code: str, days: int = 30) -> Dict[str, Any]:
        """
        检查股票是否在选股历史中
        
        参数:
            code: 股票代码
            days: 检查天数（默认30天）
        
        返回:
            {
                "in_history": True/False,
                "last_selection_date": "2026-03-25",
                "days_ago": 0,
                "selection_strategies": ["B1PatternMatch"],
                "message": "该股票在选股历史中（今天选中）"
            }
        """
        try:
            # 验证代码格式
            if not code or len(code) != 6 or not code.isdigit():
                return {
                    'in_history': False,
                    'last_selection_date': None,
                    'days_ago': None,
                    'selection_strategies': [],
                    'message': '股票代码格式错误'
                }
            
            # 检查数据库是否存在
            if not SELECTION_DB_PATH.exists():
                return {
                    'in_history': False,
                    'last_selection_date': None,
                    'days_ago': None,
                    'selection_strategies': [],
                    'message': '选股历史数据库不存在'
                }
            
            # 连接数据库
            conn = sqlite3.connect(str(SELECTION_DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 计算时间范围
            today = datetime.now().date()
            start_date = today - timedelta(days=days)
            
            # 查询选股历史（获取所有策略）
            cursor.execute(
                '''SELECT DISTINCT strategy_name, selection_date 
                   FROM stock_selection_record 
                   WHERE stock_code = ? AND selection_date >= ?
                   ORDER BY selection_date DESC''',
                (code, start_date.isoformat())
            )
            
            rows = cursor.fetchall()
            conn.close()
            
            # 处理查询结果
            if rows:
                # 获取最新的选中日期
                selection_date = rows[0]['selection_date']
                
                # 收集所有策略
                strategies = [row['strategy_name'] for row in rows if row['strategy_name']]
                
                # 计算天数差
                selection_date_obj = datetime.strptime(
                    selection_date, '%Y-%m-%d'
                ).date()
                days_ago = (today - selection_date_obj).days
                
                # 生成消息
                if days_ago == 0:
                    message = '该股票在选股历史中（今天选中）'
                elif days_ago == 1:
                    message = '该股票在选股历史中（昨天选中）'
                else:
                    message = f'该股票在选股历史中（{days_ago}天前选中）'
                
                return {
                    'in_history': True,
                    'last_selection_date': selection_date,
                    'days_ago': days_ago,
                    'selection_strategies': strategies,
                    'message': message
                }
            else:
                return {
                    'in_history': False,
                    'last_selection_date': None,
                    'days_ago': None,
                    'selection_strategies': [],
                    'message': f'该股票不在最近{days}天的选股历史中'
                }
        
        except Exception as e:
            # 记录错误并返回
            return {
                'in_history': False,
                'last_selection_date': None,
                'days_ago': None,
                'selection_strategies': [],
                'message': f'查询失败: {str(e)}'
            }

    @staticmethod
    def get_stock_full_info(code: str, days: int = 30) -> Dict[str, Any]:
        """
        获取股票完整信息（名称 + 选股历史）
        
        参数:
            code: 股票代码
            days: 检查选股历史的天数
        
        返回:
            {
                "success": True/False,
                "data": {
                    "code": "000001",
                    "name": "平安银行",
                    "in_selection_history": True,
                    "last_selection_date": "2026-03-25",
                    "days_ago": 0,
                    "selection_strategies": ["B1PatternMatch"],
                    "selection_message": "该股票在选股历史中（今天选中）"
                }
            }
        """
        try:
            # 获取股票名称
            stock_info = StockHelper.get_stock_info(code)
            if not stock_info:
                return {
                    'success': False,
                    'data': None,
                    'message': '股票不存在'
                }
            
            # 检查选股历史
            selection_info = StockHelper.check_selection_history(code, days)
            
            # 合并信息
            return {
                'success': True,
                'data': {
                    'code': code,
                    'name': stock_info['name'],
                    'in_selection_history': selection_info['in_history'],
                    'last_selection_date': selection_info['last_selection_date'],
                    'days_ago': selection_info['days_ago'],
                    'selection_strategies': selection_info['selection_strategies'],
                    'selection_message': selection_info['message']
                }
            }
        
        except Exception as e:
            # 记录错误并返回
            return {
                'success': False,
                'data': None,
                'message': f'获取股票信息失败: {str(e)}'
            }

    @staticmethod
    def get_price_range(code: str) -> Optional[Dict[str, Any]]:
        """
        获取股票当天的价格区间（最高价、最低价）
        
        通过腾讯财经接口获取当天的实时价格数据，包括开盘价、最高价、最低价等
        
        参数:
            code: 股票代码（6位数字）
        
        返回:
            {
                "code": "000001",
                "name": "平安银行",
                "open_price": 10.50,
                "high_price": 11.00,
                "low_price": 10.00,
                "current_price": 10.80,
                "message": "当天价格区间：10.00 - 11.00 元"
            }
            或 None 如果获取失败
        """
        try:
            # 验证代码格式
            if not code or len(code) != 6 or not code.isdigit():
                return None
            
            # 构建腾讯财经查询代码
            if code.startswith('6') or code.startswith('8'):
                query_code = f"sh{code}"
            else:
                query_code = f"sz{code}"
            
            # 调用腾讯财经接口
            url = f"https://qt.gtimg.cn/q={query_code}"
            resp = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            # 设置正确的字符编码
            resp.encoding = 'gbk'
            
            # 解析响应数据
            if resp.status_code == 200:
                # 腾讯接口返回格式: v_sh600519="~...~当前价~..."
                text = resp.text.strip()
                if '~' in text:
                    # 提取数据部分
                    parts = text.split('~')
                    
                    # 检查数据完整性（需要至少35个字段）
                    if len(parts) >= 35:
                        try:
                            # 提取价格信息
                            # parts[1]: 股票名称
                            # parts[3]: 当前价格
                            # parts[4]: 昨日收盘价
                            # parts[5]: 今日开盘价
                            # parts[33]: 当天最高价
                            # parts[34]: 当天最低价
                            
                            stock_name = parts[1] if len(parts) > 1 else '未知'
                            current_price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
                            open_price = float(parts[5]) if len(parts) > 5 and parts[5] else 0
                            high_price = float(parts[33]) if len(parts) > 33 and parts[33] else 0
                            low_price = float(parts[34]) if len(parts) > 34 and parts[34] else 0
                            
                            # 验证价格数据有效性
                            if high_price <= 0 or low_price <= 0:
                                return None
                            
                            # 返回价格区间信息
                            return {
                                'code': code,
                                'name': stock_name,
                                'open_price': round(open_price, 2),
                                'high_price': round(high_price, 2),
                                'low_price': round(low_price, 2),
                                'current_price': round(current_price, 2),
                                'message': f'当天价格区间：{round(low_price, 2)} - {round(high_price, 2)} 元'
                            }
                        except (ValueError, IndexError):
                            return None
            
            return None
        
        except Exception as e:
            # 记录错误并返回None
            return None
