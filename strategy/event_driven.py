import os
import sys
import sqlite3
import time
import logging
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from strategy.base_strategy import BaseStrategy

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class EventDrivenStrategy(BaseStrategy):
    """
    事件驱动策略
    识别重大事件（如业绩预告、资产重组、政策利好等）驱动的股票机会
    """
    
    def __init__(self, params=None):
        super().__init__(name="事件驱动策略", params=params)
        self.strategy_name = "事件驱动策略"
        self.display_name = "事件驱动策略"
        self.description = "识别重大事件驱动的股票机会"
        self.color = "#ff6b6b"
        self.icon = "📰"
        
        # 策略参数
        self.default_params = {
            # 事件参数
            'event_types': ['业绩超预期', '资产重组', '政策利好', '分红派息'],
            'min_importance': 2,
            # 价格参数
            'price_change_threshold': 0.05,  # 5%
            'price_drop_threshold': -0.03,  # -3%
            # 成交量参数
            'volume_ratio': 2.0,
            'volume_increase_threshold': 0.5,  # 50%
            # 时间参数
            'event_days': 3,  # 事件发生天数
            'hold_days': 5,  # 持有天数
            'max_search_days': 10,  # 最大搜索天数
            # 风险控制参数
            'stop_loss_ratio': -0.05,  # -5%
            'take_profit_ratio': 0.10,  # 10%
        }
        
        # 使用传入的参数或默认参数
        self.params = params or self.default_params
        
        # 初始化数据库连接
        self.db_path = 'stock_selection.db'
        self._init_database()
    
    def calculate_indicators(self, df):
        """
        计算技术指标（事件驱动策略不需要计算技术指标）
        :param df: 股票数据DataFrame
        :return: 原始DataFrame
        """
        return df
    
    def select_stocks(self, df, stock_name=''):
        """
        选股逻辑（事件驱动策略的选股逻辑在自定义的select_stocks方法中实现）
        :param df: 包含指标的股票数据
        :param stock_name: 股票名称，用于过滤退市股票
        :return: 选股信号列表
        """
        return []
    
    def _init_database(self):
        """
        初始化数据库表结构
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 读取SQL文件
            with open('data/EventSql.sql', 'r', encoding='utf-8') as f:
                sql_commands = f.read().split(';')
            
            for command in sql_commands:
                if command.strip():
                    cursor.execute(command)
            
            conn.commit()
            logging.info("事件驱动策略数据库表初始化成功")
        except Exception as e:
            logging.error(f"初始化数据库失败: {e}")
        finally:
            if 'conn' in locals():
                conn.close()
    
    def get_db_connection(self):
        """
        获取数据库连接
        """
        return sqlite3.connect(self.db_path)
    
    def _classify_announcement(self, title):
        """
        对公告事件进行分类
        :param title: 公告标题
        :return: 事件类型和重要性等级
        """
        # 业绩类事件
        if any(keyword in title for keyword in ['业绩', '年报', '季报', '半年报', '快报', '预告']):
            if '预增' in title or '超预期' in title:
                return '业绩超预期', 3
            elif '预减' in title or '低于预期' in title:
                return '业绩低于预期', 3
            else:
                return '业绩公告', 2
        
        # 重组类事件
        elif any(keyword in title for keyword in ['重组', '并购', '收购', '资产注入', '股权转让']):
            return '资产重组', 3
        
        # 分红类事件
        elif any(keyword in title for keyword in ['分红', '派息', '送股', '转增']):
            return '分红派息', 2
        
        # 政策类事件
        elif any(keyword in title for keyword in ['政策', '补贴', '优惠', '扶持']):
            return '政策利好', 3
        
        # 其他事件
        else:
            return '其他事件', 1
    
    def _classify_news(self, title, content):
        """
        对新闻事件进行分类
        :param title: 新闻标题
        :param content: 新闻内容
        :return: 事件类型和重要性等级
        """
        # 业绩类事件
        if any(keyword in title or keyword in content for keyword in ['业绩', '盈利', '利润', '营收']):
            return '业绩新闻', 2
        
        # 重组类事件
        elif any(keyword in title or keyword in content for keyword in ['重组', '并购', '收购']):
            return '重组新闻', 3
        
        # 政策类事件
        elif any(keyword in title or keyword in content for keyword in ['政策', '利好', '支持', '扶持']):
            return '政策新闻', 3
        
        # 其他事件
        else:
            return '其他新闻', 1
    
    def _get_announcements(self):
        """
        获取公告数据
        :return: 公告事件列表
        """
        logging.info("获取公告数据...")
        try:
            announcement_data = ak.stock_notice_report()
            announcements = []
            
            for _, row in announcement_data.iterrows():
                stock_code = row['代码']
                stock_name = row['名称']
                title = row['公告标题']
                announcement_type = row['公告类型']
                announcement_date = row['公告日期']
                url = row['网址']
                
                # 分类和评级
                event_type, importance = self._classify_announcement(title)
                
                announcements.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'title': title,
                    'type': announcement_type,
                    'announcement_date': announcement_date,
                    'url': url,
                    'event_type': event_type,
                    'importance': importance
                })
            
            logging.info(f"获取到 {len(announcements)} 条公告")
            return announcements
        except Exception as e:
            logging.error(f"获取公告数据失败: {e}")
            return []
    
    def _get_news(self):
        """
        获取新闻数据
        :return: 新闻事件列表
        """
        logging.info("获取新闻数据...")
        try:
            news_data = ak.stock_news_em()
            news_list = []
            
            for _, row in news_data.iterrows():
                keyword = row['关键词']
                title = row['新闻标题']
                content = row['新闻内容']
                publish_time = row['发布时间']
                source = row['文章来源']
                url = row['新闻链接']
                
                # 分类和评级
                event_type, importance = self._classify_news(title, content)
                
                news_list.append({
                    'keyword': keyword,
                    'title': title,
                    'content': content,
                    'publish_time': publish_time,
                    'source': source,
                    'url': url,
                    'event_type': event_type,
                    'importance': importance
                })
            
            logging.info(f"获取到 {len(news_list)} 条新闻")
            return news_list
        except Exception as e:
            logging.error(f"获取新闻数据失败: {e}")
            return []
    
    def _get_ipo_events(self):
        """
        获取IPO事件数据
        :return: IPO事件列表
        """
        logging.info("获取IPO事件数据...")
        try:
            ipo_data = ak.stock_ipo_review_em()
            ipo_events = []
            
            for _, row in ipo_data.iterrows():
                stock_code = row['股票代码']
                stock_name = row['股票简称']
                listing_board = row['上市板块']
                meeting_date = row['上会日期']
                review_status = row['审核状态']
                underwriter = row['主承销商']
                issue_amount = row['发行数量(股)']
                financing_amount = row['拟融资额(元)']
                announcement_date = row['公告日期']
                listing_date = row['上市日期']
                
                ipo_events.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'listing_board': listing_board,
                    'meeting_date': meeting_date,
                    'review_status': review_status,
                    'underwriter': underwriter,
                    'issue_amount': issue_amount,
                    'financing_amount': financing_amount,
                    'announcement_date': announcement_date,
                    'listing_date': listing_date,
                    'event_type': 'IPO事件',
                    'importance': 2  # IPO事件默认为中等重要性
                })
            
            logging.info(f"获取到 {len(ipo_events)} 条IPO事件")
            return ipo_events
        except Exception as e:
            logging.error(f"获取IPO事件数据失败: {e}")
            return []
    
    def _save_announcements(self, announcements):
        """
        存储公告事件到数据库
        :param announcements: 公告事件列表
        """
        if not announcements:
            return
        
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        for event in announcements:
            sql = """
            INSERT OR REPLACE INTO stock_announcement 
            (stock_code, stock_name, title, type, announcement_date, url, importance, impact_score, update_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """
            cursor.execute(sql, (
                event['stock_code'],
                event['stock_name'],
                event['title'],
                event['type'],
                event['announcement_date'],
                event['url'],
                event['importance'],
                0.0  # 初始影响评分
            ))
        
        conn.commit()
        conn.close()
        logging.info(f"存储了 {len(announcements)} 条公告")
    
    def _save_news(self, news_list):
        """
        存储新闻事件到数据库
        :param news_list: 新闻事件列表
        """
        if not news_list:
            return
        
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        for event in news_list:
            sql = """
            INSERT OR REPLACE INTO stock_news 
            (keyword, title, content, publish_time, source, url, sentiment, importance, impact_score, update_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """
            cursor.execute(sql, (
                event['keyword'],
                event['title'],
                event['content'],
                event['publish_time'],
                event['source'],
                event['url'],
                0.0,  # 初始情感倾向
                event['importance'],
                0.0  # 初始影响评分
            ))
        
        conn.commit()
        conn.close()
        logging.info(f"存储了 {len(news_list)} 条新闻")
    
    def _save_ipo_events(self, ipo_events):
        """
        存储IPO事件到数据库
        :param ipo_events: IPO事件列表
        """
        if not ipo_events:
            return
        
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        for event in ipo_events:
            # 处理 NaTType 和空值
            stock_code = event['stock_code'] if event['stock_code'] else None
            stock_name = event['stock_name'] if event['stock_name'] else None
            listing_board = event['listing_board'] if event['listing_board'] else None
            meeting_date = event['meeting_date'] if pd.notna(event['meeting_date']) else None
            review_status = event['review_status'] if event['review_status'] else None
            underwriter = event['underwriter'] if event['underwriter'] else None
            issue_amount = event['issue_amount'] if pd.notna(event['issue_amount']) else 0
            financing_amount = event['financing_amount'] if pd.notna(event['financing_amount']) else 0
            announcement_date = event['announcement_date'] if pd.notna(event['announcement_date']) else None
            listing_date = event['listing_date'] if pd.notna(event['listing_date']) else None
            
            sql = """
            INSERT OR REPLACE INTO stock_ipo_event 
            (stock_code, stock_name, listing_board, meeting_date, review_status, underwriter, 
            issue_amount, financing_amount, announcement_date, listing_date, importance, impact_score, update_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """
            cursor.execute(sql, (
                stock_code,
                stock_name,
                listing_board,
                meeting_date,
                review_status,
                underwriter,
                issue_amount,
                financing_amount,
                announcement_date,
                listing_date,
                event['importance'],
                0.0  # 初始影响评分
            ))
        
        conn.commit()
        conn.close()
        logging.info(f"存储了 {len(ipo_events)} 条IPO事件")
    
    def _analyze_price_impact(self, stock_code, event_date, days=3):
        """
        分析事件对价格的影响
        :param stock_code: 股票代码
        :param event_date: 事件日期
        :param days: 分析天数
        :return: 价格变化率
        """
        try:
            # 检查股票代码格式
            if not stock_code or len(stock_code) < 6:
                return 0.0
            
            # 检查事件日期
            if not event_date:
                return 0.0
            
            # 尝试解析事件日期
            try:
                end_date = pd.to_datetime(event_date)
            except Exception as e:
                logging.error(f"解析事件日期失败: {e}")
                return 0.0
            
            start_date = end_date - timedelta(days=days)
            
            # 使用akshare获取股票历史数据
            try:
                stock_data = ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period="daily",
                    start_date=start_date.strftime('%Y%m%d'),
                    end_date=end_date.strftime('%Y%m%d'),
                    adjust="qfq"
                )
            except Exception as e:
                logging.error(f"获取股票数据失败: {e}")
                return 0.0
            
            if len(stock_data) < 2:
                return 0.0
            
            # 计算价格变化率（使用中文列名）
            if '收盘' in stock_data.columns:
                close_column = '收盘'
            elif '收盘价' in stock_data.columns:
                close_column = '收盘价'
            else:
                logging.error(f"未找到收盘价列: {stock_data.columns}")
                return 0.0
            
            # 检查数据类型
            if not pd.api.types.is_numeric_dtype(stock_data[close_column]):
                logging.error(f"收盘价列不是数值类型: {stock_data[close_column].dtype}")
                return 0.0
            
            start_price = stock_data.iloc[0][close_column]
            end_price = stock_data.iloc[-1][close_column]
            
            # 检查价格值
            if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0:
                return 0.0
            
            price_change = (end_price - start_price) / start_price
            
            return price_change
        except Exception as e:
            logging.error(f"分析价格影响失败: {e}")
            return 0.0
    
    def _analyze_volume_impact(self, stock_code, event_date, days=3):
        """
        分析事件对成交量的影响
        :param stock_code: 股票代码
        :param event_date: 事件日期
        :param days: 分析天数
        :return: 成交量变化率
        """
        try:
            # 检查股票代码格式
            if not stock_code or len(stock_code) < 6:
                return 0.0
            
            # 检查事件日期
            if not event_date:
                return 0.0
            
            # 尝试解析事件日期
            try:
                end_date = pd.to_datetime(event_date)
            except Exception as e:
                logging.error(f"解析事件日期失败: {e}")
                return 0.0
            
            start_date = end_date - timedelta(days=days)
            
            # 使用akshare获取股票历史数据
            try:
                stock_data = ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period="daily",
                    start_date=start_date.strftime('%Y%m%d'),
                    end_date=end_date.strftime('%Y%m%d'),
                    adjust="qfq"
                )
            except Exception as e:
                logging.error(f"获取股票数据失败: {e}")
                return 0.0
            
            if len(stock_data) < 2:
                return 0.0
            
            # 计算成交量变化率（使用中文列名）
            if '成交量' in stock_data.columns:
                volume_column = '成交量'
            elif 'volume' in stock_data.columns:
                volume_column = 'volume'
            else:
                logging.error(f"未找到成交量列: {stock_data.columns}")
                return 0.0
            
            # 检查数据类型
            if not pd.api.types.is_numeric_dtype(stock_data[volume_column]):
                logging.error(f"成交量列不是数值类型: {stock_data[volume_column].dtype}")
                return 0.0
            
            start_volume = stock_data.iloc[0][volume_column]
            end_volume = stock_data.iloc[-1][volume_column]
            
            # 检查成交量值
            if pd.isna(start_volume) or pd.isna(end_volume) or start_volume <= 0:
                return 0.0
            
            volume_change = (end_volume - start_volume) / start_volume
            
            return volume_change
        except Exception as e:
            logging.error(f"分析成交量影响失败: {e}")
            return 0.0
    
    def _calculate_impact_score(self, price_change, volume_change, importance):
        """
        计算事件影响评分
        :param price_change: 价格变化率
        :param volume_change: 成交量变化率
        :param importance: 重要性等级
        :return: 影响评分
        """
        # 计算基础评分
        base_score = 0
        
        # 价格变化评分
        if price_change > 0.05:
            base_score += 3
        elif price_change > 0.02:
            base_score += 2
        elif price_change > 0:
            base_score += 1
        
        # 成交量变化评分
        if volume_change > 1.0:
            base_score += 3
        elif volume_change > 0.5:
            base_score += 2
        elif volume_change > 0.2:
            base_score += 1
        
        # 重要性权重
        importance_weight = importance / 3.0
        
        # 计算最终评分
        impact_score = base_score * importance_weight
        
        return impact_score
    
    def _screen_stocks(self, events, params):
        """
        根据事件分析结果筛选股票
        :param events: 事件列表
        :param params: 筛选参数
        :return: 符合条件的股票列表
        """
        qualified_stocks = []
        
        for event in events:
            # 检查事件类型
            if event['event_type'] not in params['event_types']:
                continue
            
            # 检查重要性等级
            if event['importance'] < params['min_importance']:
                continue
            
            # 分析价格影响
            price_change = self._analyze_price_impact(event['stock_code'], event['announcement_date'])
            if price_change < params['price_change_threshold']:
                continue
            
            # 分析成交量影响
            volume_change = self._analyze_volume_impact(event['stock_code'], event['announcement_date'])
            if volume_change < params['volume_ratio']:
                continue
            
            # 计算影响评分
            impact_score = self._calculate_impact_score(price_change, volume_change, event['importance'])
            
            # 构建选股结果
            stock_info = {
                'code': event['stock_code'],
                'name': event['stock_name'],
                'industry': '',  # 后续可以从数据库或API获取
                'reason': f"{event['event_type']}事件，价格上涨{price_change:.2%}，成交量放大{volume_change:.2%}",
                'event_type': event['event_type'],
                'event_date': event['announcement_date'],
                'importance': event['importance'],
                'impact_score': impact_score,
                'price_change': price_change,
                'volume_change': volume_change,
                'selected_price': 0,  # 后续可以获取实时价格
                'selected_date': datetime.now().strftime('%Y-%m-%d')
            }
            
            qualified_stocks.append(stock_info)
        
        # 按影响评分排序
        qualified_stocks.sort(key=lambda x: x['impact_score'], reverse=True)
        
        return qualified_stocks
    
    def run_strategy(self, params=None):
        """
        执行事件驱动策略选股
        :param params: 选股参数
        :return: 选股结果
        """
        logging.info("开始执行事件驱动策略选股")
        
        # 使用默认参数或传入参数
        if params is None:
            params = self.params
        
        try:
            # 获取事件数据
            announcements = self._get_announcements()
            news = self._get_news()
            ipo_events = self._get_ipo_events()
            
            # 存储事件数据
            self._save_announcements(announcements)
            self._save_news(news)
            self._save_ipo_events(ipo_events)
            
            # 筛选符合条件的事件
            filtered_events = []
            
            # 处理公告事件
            for event in announcements:
                if event['importance'] >= params['min_importance']:
                    filtered_events.append(event)
            
            # 处理新闻事件
            for event in news:
                if event['importance'] >= params['min_importance']:
                    # 转换为统一格式
                    stock_event = {
                        'stock_code': event['keyword'],
                        'stock_name': '',  # 新闻事件可能没有股票名称
                        'event_type': event['event_type'],
                        'importance': event['importance'],
                        'announcement_date': event['publish_time']
                    }
                    filtered_events.append(stock_event)
            
            # 处理IPO事件
            for event in ipo_events:
                if event['importance'] >= params['min_importance']:
                    filtered_events.append(event)
            
            # 筛选股票
            qualified_stocks = self._screen_stocks(filtered_events, params)
            
            logging.info(f"事件驱动策略选股完成，共选出 {len(qualified_stocks)} 只股票")
            
            # 构建返回结果
            result = {
                'strategy': self.strategy_name,
                'display_name': self.display_name,
                'params': params,
                'stocks': qualified_stocks,
                'total': len(qualified_stocks),
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            return result
        except Exception as e:
            logging.error(f"执行事件驱动策略选股失败: {e}")
            return {
                'strategy': self.strategy_name,
                'display_name': self.display_name,
                'params': params,
                'stocks': [],
                'total': 0,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

# 策略注册
from strategy.strategy_registry import get_registry
registry = get_registry()
registry.register(EventDrivenStrategy, name="事件驱动策略")
