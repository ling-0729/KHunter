"""
股票基础数据采集器 - 获取股票列表、价格、历史K线数据
"""
import akshare as ak
import pandas as pd
import requests
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置日志
logger = logging.getLogger(__name__)

# TickFlow 免费 API 配置
TICKFLOW_FREE_API = "https://free-api.tickflow.org"
TICKFLOW_BATCH_MAX = 100   # 单次批量查询最大股票数（TickFlow API限制）

# 股票代码格式转换缓存
_CODE_TO_TF_CACHE: Dict[str, str] = {}


def _code_to_tf_symbol(code: str) -> str:
    """将6位纯数字代码转换为 TickFlow symbol 格式 (600000.SH / 000001.SZ)"""
    if code in _CODE_TO_TF_CACHE:
        return _CODE_TO_TF_CACHE[code]
    if code.startswith(('6', '68', '8', '88')):
        symbol = f"{code}.SH"
    else:
        symbol = f"{code}.SZ"
    _CODE_TO_TF_CACHE[code] = symbol
    return symbol


def _tf_symbol_to_code(symbol: str) -> str:
    """将 TickFlow symbol 转换回6位纯数字代码"""
    return symbol.split('.')[0]


# 备选A股股票列表（当网络获取失败时使用）
DEFAULT_STOCK_LIST = {
    # 上证指数成分股（部分）
    "600519": "贵州茅台", "600036": "招商银行", "601398": "工商银行",
    "600900": "长江电力", "601288": "农业银行", "601088": "中国神华",
    "601857": "中国石油", "600030": "中信证券", "601628": "中国人寿",
    "600276": "恒瑞医药", "601318": "中国平安", "600309": "万华化学",
    "600887": "伊利股份", "601166": "兴业银行", "600028": "中国石化",
    "601888": "中国中免", "600031": "三一重工", "601012": "隆基绿能",
    "603288": "海天味业", "600009": "上海机场", "600436": "片仔癀",
    "603259": "药明康德", "601668": "中国建筑", "600048": "保利发展",
    "600585": "海螺水泥", "601601": "中国太保", "603501": "韦尔股份",
    "600690": "海尔智家", "601818": "光大银行", "600893": "航发动力",
    "601688": "华泰证券", "601211": "国泰君安", "600837": "海通证券",
    "601669": "中国电建", "600406": "国电南瑞", "601989": "中国重工",
    "601186": "中国铁建", "601390": "中国中铁", "601800": "中国交建",
    "601618": "中国中冶", "601117": "中国化学", "601669": "中国电建",
    # 深证主板
    "000001": "平安银行", "000002": "万科A", "000333": "美的集团",
    "000858": "五粮液", "002594": "比亚迪", "000568": "泸州老窖",
    "000538": "云南白药", "002415": "海康威视", "000725": "京东方A",
    "000063": "中兴通讯", "002142": "宁波银行", "000651": "格力电器",
    "000895": "双汇发展", "002304": "洋河股份", "000776": "广发证券",
    "002271": "东方雨虹", "000938": "中芯国际", "002230": "科大讯飞",
    "000100": "TCL科技", "002460": "赣锋锂业", "002024": "苏宁易购",
    "000625": "长安汽车", "002007": "华兰生物", "000768": "中航西飞",
    "002049": "紫光国微", "000166": "申万宏源", "000069": "华侨城A",
    "000063": "中兴通讯", "000338": "潍柴动力", "000983": "山西焦煤",
    "000921": "海信家电", "000999": "华润三九", "000750": "国海证券",
}


class _TushareRateLimiter:
    """Tushare API 速率限制器"""

    def __init__(self, max_calls: int = 100, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self.calls = []

    def wait_if_needed(self):
        import time
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.period]
        if len(self.calls) >= self.max_calls:
            sleep_time = self.period - (now - self.calls[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
                self.calls = [t for t in self.calls if time.time() - t < self.period]
        self.calls.append(time.time())


_tushare_limiter = _TushareRateLimiter()


class StockDataFetcher:
    """股票基础数据采集器"""
    
    def __init__(self, data_dir="data"):
        """
        初始化股票数据采集器
        
        参数：
            data_dir: 数据目录路径
        """
        self.data_dir = Path(data_dir)
        # 设置请求会话（启用连接池、Gzip 压缩、自动重试）
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/javascript, */*',
            'Accept-Encoding': 'gzip, deflate',  # 启用压缩，JSON 可压缩 80%+
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://quote.eastmoney.com/',
            'Connection': 'keep-alive',
        })
        # 挂载 HTTPAdapter：连接池 10 个，支持连接复用
        # 注意：total=0 表示 urllib3 层不自动重试，防止与 Python 级重试叠加放大耗时
        # 所有重试策略统一由 _fetch_stock_batch_tickflow 内部管理（有日志、区分错误类型）
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=Retry(
                total=0,                # 禁用 urllib3 层自动重试
                allowed_methods=["GET"],
            ),
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
    
    # ==================== 股票列表管理 ====================
    
    def _load_local_stock_names(self) -> dict:
        """
        从本地文件加载股票名称缓存
        
        返回：
            股票代码到名称的映射字典
        """
        # 检查stock_names_file属性是否存在
        if hasattr(self, 'stock_names_file') and self.stock_names_file.exists():
            try:
                with open(self.stock_names_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载本地股票名称失败: {e}")
        return {}
    
    def _save_stock_names(self, stock_dict: dict) -> None:
        """
        保存股票名称到本地文件（已禁用，改为从数据库读取）
        
        参数：
            stock_dict: 股票代码到名称的映射字典
        """
        # 不再保存到 stock_names.json 文件
        # 系统已改为从数据库读取股票名称
        logger.debug(f"跳过保存股票名称到文件（已改为数据库存储）")
    
    def _fetch_stock_list_http(self) -> dict:
        """
        使用腾讯接口获取股票列表 - 覆盖5000+只A股
        
        返回：
            股票代码到名称的映射字典
        """
        try:
            stocks = {}
            
            # 从缓存加载已有的股票列表，避免重复查询
            cached_stocks = self._load_local_stock_names()
            if len(cached_stocks) >= 3000:
                logger.info(f"从本地缓存加载 {len(cached_stocks)} 只股票")
                return cached_stocks
            
            logger.info("正在通过腾讯接口获取股票列表...")
            
            # A股完整代码范围定义 - 分批次获取以加快速度
            sh_ranges = []
            for prefix in range(600, 610):  # 600-609
                sh_ranges.append((f'{prefix}000', f'{prefix}999'))
            # 添加其他沪市段
            sh_ranges.extend([
                ('601000', '601999'),  # 601
                ('603000', '603999'),  # 603
                ('605000', '605999'),  # 605
                ('688000', '689999'),  # 科创板688-689
            ])
            
            # 深市完整范围
            sz_ranges = [
                ('000001', '009999'),  # 000开头全部
                ('001000', '001999'),  # 001
                ('002000', '002999'),  # 002中小板
                ('003000', '003999'),  # 003
                ('300000', '309999'),  # 创业板300-309
            ]
            
            # 生成密集的代码列表
            batch_size = 100
            all_codes = []
            step = 1  # 步长1覆盖100%代码
            
            # 沪市 - 全覆盖
            for start, end in sh_ranges:
                for code_num in range(int(start), int(end) + 1, step):
                    code = str(code_num).zfill(6)
                    all_codes.append(code)
            
            # 深市 - 全覆盖
            for start, end in sz_ranges:
                for code_num in range(int(start), int(end) + 1, step):
                    code = str(code_num).zfill(6)
                    all_codes.append(code)
            
            logger.info(f"计划查询 {len(all_codes)} 个代码...")
            
            total_batches = (len(all_codes) + batch_size - 1) // batch_size
            
            # 分批查询
            for i in range(0, len(all_codes), batch_size):
                batch = all_codes[i:i + batch_size]
                batch_num = i // batch_size + 1
                
                query_codes_list = []
                for c in batch:
                    if c.startswith('6') or c.startswith('8'):
                        query_codes_list.append(f"sh{c}")
                    elif c.startswith('0') or c.startswith('3'):
                        query_codes_list.append(f"sz{c}")
                
                if not query_codes_list:
                    continue
                
                query_codes = ','.join(query_codes_list)
                url = f"https://qt.gtimg.cn/q={query_codes}"
                
                try:
                    resp = requests.get(url, timeout=30, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    
                    lines = resp.text.strip().split(';')
                    for line in lines:
                        if 'v_' in line and '~' in line:
                            parts = line.split('~')
                            if len(parts) >= 4:  # 只需要基本字段（至少包含代码、名称、价格）
                                code_match = line.split('v_')[1].split('=')[0] if 'v_' in line else ''
                                if code_match:
                                    code = code_match[2:]
                                    name = parts[1] if len(parts) > 1 else ''
                                    
                                    # 过滤条件
                                    exclude_keywords = ['债', '基', 'ETF', 'LOF', '理财', '信托', 'B股', '指数']
                                    
                                    is_valid = True
                                    
                                    # 1. 名称过滤
                                    if not name or name == '""' or any(x in name for x in exclude_keywords):
                                        is_valid = False
                                    
                                    # 2. 退市股票过滤
                                    if '退' in name:
                                        is_valid = False
                                    
                                    # 3. 价格异常过滤
                                    try:
                                        current_price = float(parts[3]) if len(parts) > 3 else 0
                                        if current_price <= 0:
                                            is_valid = False
                                    except:
                                        is_valid = False
                                    
                                    if is_valid:
                                        stocks[code] = name
                    
                    if batch_num % 20 == 0 or batch_num == 1:
                        logger.info(f"进度: {batch_num}/{total_batches} 批次, 已获取 {len(stocks)} 只股票...")
                    
                    time.sleep(0.1)  # 轻微限速
                
                except Exception as e:
                    logger.debug(f"批次 {batch_num} 查询失败: {e}")
                    continue
            
            if stocks:
                logger.info(f"通过腾讯接口获取: {len(stocks)} 只股票")
                return stocks
            
            # 如果获取失败，使用默认列表
            logger.warning(f"使用默认列表: {len(DEFAULT_STOCK_LIST)} 只股票")
            return DEFAULT_STOCK_LIST.copy()
        
        except Exception as e:
            logger.error(f"HTTP获取失败: {e}")
            return DEFAULT_STOCK_LIST.copy()
    
    def get_all_stock_codes(self, max_retries=3) -> dict:
        """
        获取所有A股股票代码（过滤债基、ETF、ST等）
        优先使用 Tushare 获取完整的 5800+ 只股票列表
        
        参数：
            max_retries: 最大重试次数
        
        返回：
            股票代码到名称的映射字典
        """
        logger.info("正在获取A股股票列表...")
        
        # 方法1: 优先使用 Tushare 获取完整股票列表
        for attempt in range(max_retries):
            try:
                logger.info(f"尝试 Tushare (第{attempt+1}/{max_retries}次)...")
                
                # 使用 Tushare 的 stock_basic 接口获取完整股票列表
                import tushare as ts
                
                # 读取 Tushare token
                tushare_token = None
                try:
                    with open('config/tushare_config.json', 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        tushare_token = config.get('token') or config.get('api_key')
                except:
                    pass
                
                if not tushare_token:
                    logger.warning("未找到 Tushare token，跳过 Tushare 方法")
                else:
                    # 初始化 Tushare Pro API
                    pro = ts.pro_api(tushare_token)
                    
                    # 获取股票基本信息（包含所有上市股票）
                    df = pro.stock_basic(exchange='', list_status='L')
                    
                    if df is not None and not df.empty:
                        # 提取代码和名称
                        stock_dict = {}
                        
                        for _, row in df.iterrows():
                            code = str(row['ts_code']).split('.')[0]  # 去掉交易所后缀
                            name = str(row['name'])
                            
                            # 过滤条件1: 排除非标准 A 股代码（只保留 00/30/60/68/88 开头）
                            if not code[0] in ['0', '3', '6', '8']:
                                continue
                            
                            # 过滤条件2: 排除债券、基金、ETF 等
                            exclude_keywords = ['债', '基', 'ETF', 'LOF', '基金', '理财', '信托', 'B股', '指数', '国债', '企债', '转债', '回购', 'R-', 'GC']
                            
                            # 检查是否应该排除
                            is_valid = True
                            if any(kw in name for kw in exclude_keywords):
                                is_valid = False
                            if '退' in name:
                                is_valid = False
                            
                            if is_valid:
                                stock_dict[code] = name
                        
                        if stock_dict:
                            logger.info(f"✓ Tushare 获取成功: {len(stock_dict)} 只A股股票")
                            self._save_stock_names(stock_dict)
                            return stock_dict
            
            except Exception as e:
                logger.debug(f"Tushare 失败: {e}")
                time.sleep(1)
        
        # 方法2: 腾讯接口（备选）
        for attempt in range(max_retries):
            try:
                logger.info(f"尝试腾讯接口 (第{attempt+1}/{max_retries}次)...")
                stocks = self._fetch_stock_list_http()
                if stocks:
                    # 过滤
                    filtered = {}
                    code_pattern = r'^(00|30|60|68|88)\d{4}$'
                    exclude_keywords = ['债', '基', 'ETF', 'LOF', '基金', '理财', '信托', 'B股', '指数', '国债', '企债', '转债', '回购', 'R-', 'GC']
                    
                    import re
                    for code, name in stocks.items():
                        if not re.match(code_pattern, code):
                            continue
                        if any(kw in name for kw in exclude_keywords):
                            continue
                        filtered[code] = name
                    
                    if filtered:
                        logger.info(f"✓ 腾讯接口获取成功: {len(filtered)} 只A股股票")
                        self._save_stock_names(filtered)
                        return filtered
            except Exception as e:
                logger.debug(f"腾讯接口失败: {e}")
                time.sleep(1)
        
        # 方法3: akshare
        for attempt in range(max_retries):
            try:
                logger.info(f"尝试 akshare (第{attempt+1}/{max_retries}次)...")
                
                sh_df = ak.stock_sh_a_spot_em()
                sz_df = ak.stock_sz_a_spot_em()
                
                all_stocks = pd.concat([sh_df[['代码', '名称']], sz_df[['代码', '名称']]])
                all_stocks = all_stocks.drop_duplicates(subset=['代码'])
                
                code_pattern = r'^(00|30|60|68|88)\d{4}$'
                all_stocks = all_stocks[all_stocks['代码'].str.match(code_pattern)]
                
                exclude_keywords = ['债', '基', 'ETF', 'LOF', '基金', '理财', '信托', 'B股', '指数', '国债', '企债', '转债', '回购', 'R-', 'GC']
                for keyword in exclude_keywords:
                    all_stocks = all_stocks[~all_stocks['名称'].str.contains(keyword, na=False)]
                
                stock_dict = dict(zip(all_stocks['代码'], all_stocks['名称']))
                logger.info(f"✓ akshare 获取成功: {len(stock_dict)} 只A股股票")
                self._save_stock_names(stock_dict)
                return stock_dict
                
            except Exception as e:
                logger.debug(f"akshare 失败: {e}")
                time.sleep(2 ** attempt)
        
        # 降级: 本地缓存或默认列表
        logger.warning("网络连接失败，尝试加载本地缓存...")
        local_stocks = self._load_local_stock_names()
        if local_stocks:
            logger.info(f"✓ 从本地缓存加载: {len(local_stocks)} 只股票")
            return local_stocks
        
        logger.warning("使用内置默认股票列表...")
        logger.info(f"✓ 加载默认列表: {len(DEFAULT_STOCK_LIST)} 只股票")
        return DEFAULT_STOCK_LIST.copy()
    
    # ==================== 实时数据获取 ====================
    
    def get_stock_price(self, stock_code: str) -> Optional[float]:
        """
        获取股票实时价格（使用腾讯财经接口）
        
        参数：
            stock_code: 股票代码（6位数字，如 '688426'）
        
        返回：
            实时价格，获取失败返回 None
        """
        try:
            # 构建腾讯财经查询代码
            if stock_code.startswith('6') or stock_code.startswith('8'):
                query_code = f"sh{stock_code}"
            else:
                query_code = f"sz{stock_code}"
            
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
                    if len(parts) >= 4:
                        # 第4个字段是当前价格
                        try:
                            price = float(parts[3])
                            if price > 0:
                                return price
                        except (ValueError, IndexError):
                            pass
            
            return None
        
        except Exception as e:
            logger.debug(f"获取实时价格失败 ({stock_code}): {str(e)}")
            return None
    
    def get_stock_prices_batch(self, stock_codes: list) -> dict:
        """
        批量获取股票实时价格（使用腾讯财经接口）
        
        参数：
            stock_codes: 股票代码列表，如 ['600519', '000001', ...]
        
        返回：
            {stock_code: price} 字典，获取失败的股票不包含在结果中
        """
        # 结果字典
        price_map = {}
        if not stock_codes:
            return price_map
        
        # 每批最多80只，避免URL过长
        batch_size = 80
        
        for i in range(0, len(stock_codes), batch_size):
            batch = stock_codes[i:i + batch_size]
            
            # 构建批量查询代码
            query_list = []
            for code in batch:
                # 根据代码前缀判断市场
                if code.startswith('6') or code.startswith('8'):
                    query_list.append(f"sh{code}")
                else:
                    query_list.append(f"sz{code}")
            
            # 拼接为逗号分隔的查询字符串
            query_str = ','.join(query_list)
            url = f"https://qt.gtimg.cn/q={query_str}"
            
            try:
                resp = requests.get(url, timeout=15, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                # 腾讯接口返回GBK编码
                resp.encoding = 'gbk'
                
                if resp.status_code == 200:
                    # 响应中每只股票用分号分隔
                    lines = resp.text.strip().split(';')
                    for line in lines:
                        if 'v_' not in line or '~' not in line:
                            continue
                        try:
                            # 提取股票代码：v_sh600519="1~贵州茅台~..."
                            code_part = line.split('v_')[1].split('=')[0]
                            # 去掉 sh/sz 前缀，得到6位代码
                            code = code_part[2:]
                            # 按~分割取第4个字段（当前价格）
                            parts = line.split('~')
                            if len(parts) >= 4:
                                price = float(parts[3])
                                if price > 0:
                                    price_map[code] = price
                        except (ValueError, IndexError):
                            continue
            
            except Exception as e:
                logger.debug(f"批量获取实时价格失败 (批次{i // batch_size + 1}): {str(e)}")
                continue
            
            # 批次间轻微延迟，避免请求过快
            if i + batch_size < len(stock_codes):
                time.sleep(0.05)
        
        logger.debug(f"批量获取实时价格完成: 请求{len(stock_codes)}只, 成功{len(price_map)}只")
        return price_map

    def _get_realtime_market_cap(self, stock_code: str) -> Optional[int]:
        """
        从腾讯财经接口获取单只股票总市值
        
        参数：
            stock_code: 股票代码（6位数字）
        
        返回：
            总市值（元），失败返回 None
        """
        try:
            # 构建腾讯财经查询代码
            if stock_code.startswith('6') or stock_code.startswith('8'):
                query_code = f"sh{stock_code}"
            else:
                query_code = f"sz{stock_code}"
            
            # 调用腾讯财经接口
            url = f"https://qt.gtimg.cn/q={query_code}"
            resp = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            # 解析返回数据
            if resp.status_code == 200:
                text = resp.text.strip()
                if '~' in text:
                    parts = text.split('~')
                    # 字段44是总市值（亿）
                    if len(parts) >= 46 and parts[44]:
                        cap = float(parts[44])
                        if cap > 0:
                            # 转为元
                            return int(cap * 1e8)
        except Exception as e:
            logger.debug(f"腾讯接口获取总市值失败 ({stock_code}): {e}")
        return None
    
    def _fetch_market_cap_tencent(self, stock_codes: list) -> dict:
        """
        使用腾讯接口批量获取市值数据
        
        参数：
            stock_codes: 股票代码列表
        
        返回：
            股票代码到市值的映射字典
        """
        market_cap_map = {}
        batch_size = 100
        total = len(stock_codes)
        
        try:
            for i in range(0, total, batch_size):
                batch = stock_codes[i:i + batch_size]
                query_codes = []
                for code in batch:
                    if code.startswith('6') or code.startswith('8'):
                        query_codes.append(f"sh{code}")
                    else:
                        query_codes.append(f"sz{code}")
                
                url = f"https://qt.gtimg.cn/q={','.join(query_codes)}"
                resp = requests.get(url, timeout=30, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                lines = resp.text.strip().split(';')
                for line in lines:
                    if 'v_' in line and '~' in line:
                        try:
                            # 提取代码
                            code_match = line.split('v_')[1].split('=')[0] if 'v_' in line else ''
                            if not code_match or len(code_match) < 8:
                                continue
                            code = code_match[2:]  # 去掉 sh/sz 前缀
                            
                            parts = line.split('~')
                            if len(parts) >= 46:
                                # 字段44是总市值（亿）
                                cap = float(parts[44]) if parts[44] else 0
                                if cap > 0:
                                    # 转为元（腾讯接口是亿）
                                    market_cap_map[code] = int(cap * 1e8)
                        except:
                            continue
                
                if i % 500 == 0 and i > 0:
                    logger.info(f"已获取 {i}/{total} 只市值...")
                    time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"腾讯接口获取市值失败: {e}")
        
        return market_cap_map

    # ==================== 历史数据获取 ====================
    
    def _fetch_stock_history_http(self, stock_code: str, years: int = 6) -> Optional[pd.DataFrame]:
        """
        使用腾讯财经接口获取股票历史数据
        
        参数：
            stock_code: 股票代码（6位数字）
            years: 获取数据的年份数（实际返回最多1000条）
        
        返回：
            DataFrame，包含date, open, high, low, close, volume, amount, turnover, market_cap字段
        """
        try:
            # 判断市场前缀
            if stock_code.startswith('6') or stock_code.startswith('88'):
                market_code = 'sh' + stock_code
            else:
                market_code = 'sz' + stock_code
            
            # 腾讯财经接口 - 获取日K线数据
            max_days = min(years * 365, 1000)
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_code},day,,,{max_days},qfq"
            
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://stock.finance.qq.com/'
            })
            
            data = resp.json()
            
            # 解析腾讯返回的数据
            data_level = data.get('data', {})
            
            # data_level 可能是 dict 或 list（大数据量时）
            if isinstance(data_level, dict):
                stock_data = data_level.get(market_code, {})
                if isinstance(stock_data, dict):
                    klines = stock_data.get('qfqday', []) or stock_data.get('day', [])
                else:
                    klines = []
            elif isinstance(data_level, list) and len(data_level) > 0:
                # 大数据量时返回列表，第一项是代码，第二项是数据
                klines = []
                for item in data_level:
                    if isinstance(item, list) and len(item) >= 2 and item[0] == market_code:
                        # item[1] 是K线数据
                        if isinstance(item[1], list):
                            klines = item[1]
                        break
            else:
                klines = []
            
            if klines:
                records = []
                # 腾讯财经对688/689(科创板)返回的成交量单位是"股"，
                # 对其他板块返回的单位是"手"（1手=100股）。
                # 统一转换为"手"单位存入数据库，与Tushare保持一致
                is_kcb = stock_code.startswith('688') or stock_code.startswith('689')
                for item in klines:
                    # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量, ...]
                    if len(item) >= 6 and isinstance(item, list):
                        raw_vol = int(float(item[5]))
                        # 科创板成交量从"股"转换为"手"（÷100）
                        volume = raw_vol // 100 if is_kcb else raw_vol
                        # 统一日期格式为 YYYY-MM-DD
                        from utils.date_utils import normalize_date
                        records.append({
                            'date': normalize_date(str(item[0])),
                            'open': float(item[1]),
                            'close': float(item[2]),
                            'high': float(item[3]),
                            'low': float(item[4]),
                            'volume': volume,
                            'amount': 0,
                            'turnover': 0,
                        })
                
                if records:
                    df = pd.DataFrame(records)
                    df['date'] = pd.to_datetime(df['date'])
                    # 从实时数据获取总市值
                    market_cap = self._get_realtime_market_cap(stock_code)
                    if market_cap:
                        df['market_cap'] = market_cap
                    else:
                        df['market_cap'] = abs(hash(stock_code)) % 500 * 100000000 + 5000000000
                    df = df.sort_values('date', ascending=False)
                    return df
            
            return None
        except Exception as e:
            logger.debug(f"HTTP获取历史数据失败: {e}")
            return None
    
    def _generate_mock_data(self, stock_code: str, years: int = 6) -> pd.DataFrame:
        """
        生成模拟数据（当网络不可用时使用）
        
        参数：
            stock_code: 股票代码
            years: 生成数据的年份数
        
        返回：
            模拟的历史数据DataFrame
        """
        import numpy as np
        
        np.random.seed(hash(stock_code) % 2**32)
        
        days = int(365 * years)
        end_date = datetime.now()
        dates = [end_date - timedelta(days=i) for i in range(days)]
        
        # 生成随机价格序列
        base_price = 10 + np.random.random() * 30
        returns = np.random.normal(0.0005, 0.02, days)
        prices = base_price * np.exp(np.cumsum(returns))
        
        # 生成OHLC数据
        df = pd.DataFrame({
            'date': dates,
            'close': prices,
            'volume': np.random.randint(1000000, 10000000, days),
            'amount': np.random.randint(10000000, 100000000, days),
            'turnover': np.random.uniform(1, 10, days),
        })
        
        # 生成合理的 open, high, low
        df['open'] = df['close'] * (1 + np.random.normal(0, 0.005, days))
        df['high'] = np.maximum(df[['open', 'close']].max(axis=1) * (1 + abs(np.random.normal(0, 0.01, days))), 
                                df[['open', 'close']].max(axis=1))
        df['low'] = np.minimum(df[['open', 'close']].min(axis=1) * (1 - abs(np.random.normal(0, 0.01, days))),
                               df[['open', 'close']].min(axis=1))
        
        # 添加总市值
        market_cap = self._get_realtime_market_cap(stock_code)
        if market_cap:
            df['market_cap'] = market_cap
        else:
            df['market_cap'] = np.random.uniform(5000000000, 50000000000)
        
        # 按日期倒序排列
        df = df.sort_values('date', ascending=False)
        
        return df
    
    def fetch_stock_history(self, stock_code: str, years: int = 6) -> pd.DataFrame:
        """
        抓取单只股票历史数据（前复权，按日期倒序排列）

        数据源优先级: TickFlow 免费 API > 腾讯财经 > 模拟数据

        参数：
            stock_code: 股票代码
            years: 获取数据的年份数

        返回：
            历史数据DataFrame
        """
        # 方法1: TickFlow 免费 API（批量端点，单只查询也支持）
        try:
            df = self._fetch_stock_history_tickflow(stock_code, years)
            if df is not None and not df.empty:
                logger.debug(f"TickFlow 获取 {len(df)} 条历史数据")
                return df
            else:
                logger.debug(f"TickFlow 返回空数据，降级到腾讯财经...")
        except Exception as e:
            logger.debug(f"TickFlow 异常: {e}，降级到腾讯财经...")

        # 方法2: 使用腾讯财经HTTP接口（最多1000天）
        try:
            df = self._fetch_stock_history_http(stock_code, years)
            if df is not None and not df.empty:
                logger.debug(f"腾讯财经获取 {len(df)} 条历史数据")
                return df
            else:
                logger.debug(f"腾讯财经返回空数据，使用模拟数据...")
        except Exception as e:
            logger.debug(f"腾讯财经异常: {e}，使用模拟数据...")
        
        # 降级: 使用模拟数据
        return self._generate_mock_data(stock_code, years)
    
    def _fetch_stock_update_tencent_light(self, stock_code: str, days: int) -> Optional[pd.DataFrame]:
        """
        【优化】轻量级腾讯财经获取 - 仅请求所需天数的数据，避免拉取全年数据触发限流

        参数：
            stock_code: 股票代码
            days: 需要获取的天数

        返回：
            增量数据DataFrame（前复权），失败返回 None
        """
        # 判断市场前缀
        if stock_code.startswith('6') or stock_code.startswith('88'):
            market_code = 'sh' + stock_code
        else:
            market_code = 'sz' + stock_code

        # 只获取需要天数 + 缓冲（多要 10 天防止缺失），最小 60 天保证 MA60 计算正确
        max_days = max(days + 10, 60)

        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_code},day,,,{max_days},qfq"

        resp = requests.get(url, timeout=5, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://stock.finance.qq.com/'
        })

        data = resp.json()
        data_level = data.get('data', {})

        # 解析K线数据（与 _fetch_stock_history_http 逻辑一致）
        klines = []
        if isinstance(data_level, dict):
            stock_data = data_level.get(market_code, {})
            if isinstance(stock_data, dict):
                klines = stock_data.get('qfqday', []) or stock_data.get('day', [])
        elif isinstance(data_level, list) and len(data_level) > 0:
            for item in data_level:
                if isinstance(item, list) and len(item) >= 2 and item[0] == market_code:
                    if isinstance(item[1], list):
                        klines = item[1]
                    break

        if not klines:
            return None

        records = []
        is_kcb = stock_code.startswith('688') or stock_code.startswith('689')
        for item in klines:
            if len(item) >= 6 and isinstance(item, list):
                raw_vol = int(float(item[5]))
                # 科创板成交量从"股"转换为"手"
                volume = raw_vol // 100 if is_kcb else raw_vol
                # 统一日期格式为 YYYY-MM-DD
                from utils.date_utils import normalize_date
                records.append({
                    'date': normalize_date(str(item[0])),
                    'open': float(item[1]),
                    'close': float(item[2]),
                    'high': float(item[3]),
                    'low': float(item[4]),
                    'volume': volume,
                })

        if records:
            df = pd.DataFrame(records)
            df['date'] = pd.to_datetime(df['date'])
            # 过滤到所需天数
            cutoff = datetime.now() - timedelta(days=days)
            df = df[df['date'] >= cutoff]
            df = df.sort_values('date', ascending=False)
            return df if len(df) > 0 else None

        return None

    def fetch_stock_update(self, stock_code: str, days: int = 10) -> Optional[pd.DataFrame]:
        """
        抓取近期数据用于增量更新（单次请求，不做重试）

        数据源策略：使用 TickFlow 批量接口获取前复权数据。
        不做单只股票重试，由调用方 kline_updater 在批次层做限流控制和重试。

        参数：
            stock_code: 股票代码
            days: 获取最近多少天的数据

        返回：
            增量数据DataFrame（前复权数据），失败返回 None
        """
        # 使用 TickFlow 批量接口获取 K 线数据（前复权）
        try:
            results, api_ok = self._fetch_stock_batch_tickflow([stock_code], days)
            if stock_code in results:
                return results[stock_code]
        except Exception as e:
            logger.debug(f"【增量更新】TickFlow 获取 {stock_code} 失败: {e}")

        return None

    def get_stock_market_cap(self, max_retries=3) -> dict:
        """
        从 Tushare daily_basic 接口批量获取股票市值信息
        
        参数：
            max_retries: 最大重试次数
        
        返回：
            {code: market_cap} 字典，market_cap 单位为亿元
        
        说明：
            - 调用 Tushare 的 daily_basic 接口（一次性获取所有股票）
            - 提取 ts_code 和 total_mv 字段
            - 转换格式：code = ts_code.split('.')[0]
            - 单位转换：market_cap = total_mv / 10000（万元转亿元）
            - 如果获取失败，返回空字典
            - 使用批量处理，避免逐个查询
        """
        logger.info("开始批量获取股票市值信息...")
        
        # 尝试使用 Tushare 获取市值信息
        for attempt in range(max_retries):
            try:
                logger.info(f"尝试 Tushare daily_basic 接口 (第{attempt+1}/{max_retries}次)...")
                
                import tushare as ts
                import json
                
                # 读取 Tushare token
                tushare_token = None
                try:
                    with open('config/tushare_config.json', 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        tushare_token = config.get('token') or config.get('api_key')
                except:
                    pass
                
                if not tushare_token:
                    logger.warning("未找到 Tushare token，跳过 Tushare 方法")
                    return {}
                
                # 初始化 Tushare Pro API
                pro = ts.pro_api(tushare_token)
                
                # 调用 daily_basic 接口获取所有股票的市值信息
                # daily_basic 接口返回所有股票的每日基本面指标
                df = pro.daily_basic(fields='ts_code,total_mv')
                
                if df is not None and not df.empty:
                    # 构建 {code: market_cap} 字典
                    market_caps = {}
                    
                    for _, row in df.iterrows():
                        try:
                            # 提取股票代码（去掉交易所后缀）
                            code = str(row['ts_code']).split('.')[0]
                            
                            # 提取总市值（单位：万元）
                            total_mv = float(row['total_mv']) if pd.notna(row['total_mv']) else 0
                            
                            # 转换为亿元
                            market_cap = total_mv / 10000
                            
                            market_caps[code] = market_cap
                        
                        except Exception as e:
                            logger.debug(f"处理市值数据失败: {e}")
                            continue
                    
                    if market_caps:
                        logger.info(f"✓ 成功获取 {len(market_caps)} 只股票的市值信息")
                        return market_caps
                    else:
                        logger.warning("daily_basic 返回空数据")
                        return {}
            
            except Exception as e:
                logger.debug(f"Tushare daily_basic 失败: {e}")
                time.sleep(1)
        
        logger.warning("获取市值信息失败，返回空字典")
        return {}
    
    def update_stock_market_cap(self, db_manager, max_retries=3) -> dict:
        """
        批量更新所有股票的市值信息到数据库
        
        参数：
            db_manager: 数据库管理器实例
            max_retries: 最大重试次数
        
        返回：
            {
                'updated': 更新成功的股票数,
                'failed': 更新失败的股票数,
                'market_caps': {code: market_cap} 字典
            }
        
        说明：
            - 调用 daily_basic 接口获取最新市值（一次性获取所有股票）
            - 批量更新 stock_basic 表的 market_cap 字段
            - 使用事务确保数据一致性
            - 记录更新时间
        """
        logger.info("开始批量更新股票市值信息...")
        
        # 获取最新市值信息
        market_caps = self.get_stock_market_cap(max_retries)
        
        if not market_caps:
            logger.warning("未获取到市值信息，更新失败")
            return {
                'updated': 0,
                'failed': 0,
                'market_caps': {}
            }
        
        # 批量更新数据库
        updated_count = 0
        failed_count = 0
        
        try:
            # 获取数据库连接
            conn = db_manager.connect()
            
            # 逐个更新股票市值
            for code, market_cap in market_caps.items():
                try:
                    # 更新 stock_basic 表的 market_cap 字段
                    update_sql = """
                    UPDATE stock_basic 
                    SET market_cap = ?, update_time = CURRENT_TIMESTAMP
                    WHERE code = ?
                    """
                    db_manager.execute(update_sql, (market_cap, code))
                    updated_count += 1
                
                except Exception as e:
                    failed_count += 1
                    logger.debug(f"更新 {code} 市值失败: {e}")
                    continue
            
            # 提交事务
            conn.commit()
            logger.info(f"市值更新完成: 成功 {updated_count} 只, 失败 {failed_count} 只")
        
        except Exception as e:
            logger.error(f"批量更新市值失败: {e}")
            if 'conn' in locals():
                try:
                    conn.rollback()
                except:
                    pass
        
        return {
            'updated': updated_count,
            'failed': failed_count,
            'market_caps': market_caps
        }

    # ==================== TickFlow 批量K线获取 ====================

    def _fetch_stock_batch_tickflow(self, stock_codes: list, days: int) -> tuple:
        """
        使用 TickFlow 免费 API 批量获取K线数据（前复权）

        一次 HTTP 请求获取所有股票的K线，大幅减少网络开销。
        内置 2 次指数退避重试 + Session 连接复用 + Gzip 压缩 + 自适应超时。

        参数：
            stock_codes: 6位纯数字股票代码列表，如 ['600000', '000001']
            days: 获取最近多少天的数据

        返回：
            (results: dict, api_ok: bool)
            - results: {stock_code: DataFrame} 字典，仅包含有数据的股票
            - api_ok: True=API调用成功，个别股票无数据属于正常情况无需降级；
                      False=API调用失败（限流/网络/超时），整批需要降级到腾讯财经
        """
        if not stock_codes:
            return ({}, True)

        # 转换代码格式: 600000 -> 600000.SH, 000001 -> 000001.SZ
        tf_symbols = [_code_to_tf_symbol(c) for c in stock_codes]
        symbols_str = ",".join(tf_symbols)

        # 确保有足够的缓冲天数
        count = max(days + 10, 60)

        # 自适应超时：基础 30s + 每只股票 0.3s（100 只 ≈ 60s）
        timeout = max(15, 30 + len(stock_codes) * 0.3)

        url = f"{TICKFLOW_FREE_API}/v1/klines/batch"
        params = {
            "symbols": symbols_str,
            "period": "1d",
            "count": count,
            "adjust": "forward",
        }

        # 可重试的错误类型（瞬态故障）
        RETRYABLE_EXCEPTIONS = (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        )
        # 最大重试次数（指数退避：1s, 2s）
        MAX_RETRIES = 2

        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                # 使用 session 复用连接，利用连接池 + Keep-Alive + Gzip 压缩
                resp = self.session.get(url, params=params, timeout=timeout)

                # 429 限流：不重试（等待只会加重限流）
                if resp.status_code == 429:
                    logger.warning("TickFlow batch 触发限流(429)，整批需降级")
                    return ({}, False)
                # 4xx 客户端错误：不重试
                if 400 <= resp.status_code < 500:
                    logger.warning(f"TickFlow batch API失败 HTTP {resp.status_code}，整批需降级")
                    return ({}, False)
                # 5xx 服务端错误：如还有重试配额则重试
                if resp.status_code != 200:
                    logger.warning(
                        f"TickFlow batch HTTP {resp.status_code}(尝试{attempt+1}/{MAX_RETRIES+1})"
                    )
                    if attempt < MAX_RETRIES:
                        backoff = 2 ** attempt  # 1s, 2s
                        time.sleep(backoff)
                        continue
                    return ({}, False)

                data = resp.json()
                raw_data = data.get("data", {}) if isinstance(data, dict) else {}

                # API 返回成功但 data 为空，视为 API 异常需降级
                if not raw_data:
                    logger.warning("TickFlow batch 返回空data，整批需降级")
                    return ({}, False)

                # 解析每只股票的K线数据（数组格式 → DataFrame）
                results = {}
                empty_count = 0
                for symbol, kline_obj in raw_data.items():
                    if not kline_obj or not kline_obj.get("close"):
                        empty_count += 1
                        continue

                    code = _tf_symbol_to_code(symbol)
                    df = self._tickflow_arrays_to_df(kline_obj, days)
                    # TickFlow 返回 volume 单位是「手」，DB统一以「手」存储，无需转换
                    if df is not None and len(df) > 0:
                        results[code] = df

                if empty_count > 0:
                    logger.debug(
                        f"TickFlow batch: {len(results)}只有数据, {empty_count}只无数据（正常，不需降级）"
                    )
                # API 成功，返回 (有数据的股票, api_ok=True)
                return (results, True)

            except RETRYABLE_EXCEPTIONS as e:
                # 超时或连接错误：指数退避重试
                last_error = e
                err_type = "超时" if isinstance(e, requests.exceptions.Timeout) else "连接失败"
                if attempt < MAX_RETRIES:
                    backoff = 2 ** attempt  # 1s, 2s
                    logger.warning(
                        f"TickFlow batch {err_type}(尝试{attempt+1}/{MAX_RETRIES+1})，{backoff}s后重试…"
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        f"TickFlow batch {err_type}，已重试{MAX_RETRIES}次全部失败，整批需降级"
                    )
            except Exception as e:
                # 未知异常：不重试，直接降级
                logger.error(f"TickFlow batch 请求异常: {e}，整批需降级")
                return ({}, False)

        # 所有重试耗尽
        return ({}, False)

    def _tickflow_arrays_to_df(self, kline_obj: dict, days: int = None) -> Optional[pd.DataFrame]:
        """
        将 TickFlow 数组格式的K线数据转换为 DataFrame

        TickFlow 返回格式（数组列）:
        {"timestamp": [ms, ...], "open": [...], "high": [...], "low": [...],
         "close": [...], "volume": [...]}

        转换为行格式 DataFrame: date, open, high, low, close, volume

        参数：
            kline_obj: TickFlow 单只股票的K线数据对象
            days: 需要保留的天数，None 表示保留全部

        返回：
            标准化 DataFrame（按日期倒序），失败返回 None
        """
        try:
            timestamps = kline_obj.get("timestamp", [])
            if not timestamps:
                return None

            # 将毫秒时间戳转为日期字符串
            dates = []
            for ts in timestamps:
                try:
                    dt = datetime.fromtimestamp(ts / 1000.0)
                    dates.append(dt.strftime('%Y-%m-%d'))
                except (ValueError, OSError):
                    dates.append(str(ts))

            records = {
                'date': dates,
                'open': [float(v) for v in kline_obj.get("open", [])],
                'high': [float(v) for v in kline_obj.get("high", [])],
                'low': [float(v) for v in kline_obj.get("low", [])],
                'close': [float(v) for v in kline_obj.get("close", [])],
                'volume': [int(float(v)) for v in kline_obj.get("volume", [])],
            }

            df = pd.DataFrame(records)
            df['date'] = pd.to_datetime(df['date'])

            # 按日期倒序排列
            df = df.sort_values('date', ascending=False)

            # 如果指定了天数，只保留最近N天
            if days is not None and days > 0 and len(df) > days:
                df = df.head(days)

            return df if len(df) > 0 else None

        except Exception as e:
            logger.debug(f"TickFlow 数据转换失败: {e}")
            return None

    # ==================== 腾讯财经批量K线获取（降级方案） ====================

    def _fetch_stock_batch_tencent(self, stock_codes: list, years: int = 3,
                                    concurrency: int = 2) -> dict:
        """
        批量使用腾讯财经接口并发获取K线数据（降级方案）

        当 TickFlow 不可用时使用。通过线程池低并发获取，避免触发反爬。

        参数：
            stock_codes: 6位纯数字股票代码列表
            years: 获取数据的年份数
            concurrency: 并发线程数（默认2，避免触发腾讯财经反爬/限流）

        返回：
            {stock_code: DataFrame} 字典，仅包含成功获取且有数据的股票
        """
        import time as time_module
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # 线程安全地收集结果
        results = {}
        failed_count = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            # 提交所有任务（每提交一个任务间隔0.3秒，避免瞬间并发冲击）
            future_map = {}
            for code in stock_codes:
                future_map[executor.submit(self._fetch_stock_history_http, code, years)] = code
                time_module.sleep(0.3)  # 提交间隔：降低对腾讯财经的瞬时并发压力

            # 收集结果
            for future in as_completed(future_map):
                code = future_map[future]
                try:
                    df = future.result()
                    if df is not None and len(df) > 0:
                        results[code] = df
                except Exception as e:
                    failed_count += 1
                    # WARNING 级别暴露错误原因，便于排查限流/反爬
                    if failed_count <= 3:
                        logger.warning(f"腾讯财经获取 {code} 失败: {e}")
                    elif failed_count == 4:
                        logger.warning(f"腾讯财经批量获取持续失败（已省略后续日志）...")

        return results

    def _fetch_stock_history_tickflow(self, stock_code: str, years: int = 6) -> Optional[pd.DataFrame]:
        """
        使用 TickFlow 免费 API 获取单只股票完整历史数据（前复权）

        用于除权后的历史数据重建。内置重试 + Session 连接复用 + Gzip 压缩。

        参数：
            stock_code: 6位纯数字股票代码
            years: 获取数据的年份数

        返回：
            DataFrame（按日期倒序），失败返回 None
        """
        tf_symbol = _code_to_tf_symbol(stock_code)
        # 估算交易日数：年 × 250
        count = max(years * 250, 1500)

        url = f"{TICKFLOW_FREE_API}/v1/klines/batch"
        params = {
            "symbols": tf_symbol,
            "period": "1d",
            "count": count,
            "adjust": "forward",
        }

        # 单只股票查询，超时 30s 即可
        MAX_RETRIES = 2
        RETRYABLE_EXCEPTIONS = (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        )

        for attempt in range(MAX_RETRIES + 1):
            try:
                # 使用 session 复用连接，利用 Gzip 压缩
                resp = self.session.get(url, params=params, timeout=30)

                if resp.status_code == 429:
                    logger.warning(f"TickFlow history ({stock_code}) 触发限流(429)")
                    return None
                if 400 <= resp.status_code < 500:
                    logger.warning(f"TickFlow history ({stock_code}) HTTP {resp.status_code}")
                    return None
                if resp.status_code != 200:
                    if attempt < MAX_RETRIES:
                        time.sleep(2 ** attempt)
                        continue
                    logger.warning(f"TickFlow history ({stock_code}) HTTP {resp.status_code}")
                    return None

                data = resp.json()
                raw_data = data.get("data", {}) if isinstance(data, dict) else {}
                kline_obj = raw_data.get(tf_symbol)

                if not kline_obj:
                    logger.warning(f"TickFlow history: {stock_code} 无数据")
                    return None

                df = self._tickflow_arrays_to_df(kline_obj)
                # TickFlow 返回 volume 单位是「手」，DB统一以「手」存储，无需转换
                return df

            except RETRYABLE_EXCEPTIONS as e:
                err_type = "超时" if isinstance(e, requests.exceptions.Timeout) else "连接失败"
                if attempt < MAX_RETRIES:
                    backoff = 2 ** attempt
                    logger.warning(
                        f"TickFlow history ({stock_code}) {err_type}，{backoff}s后重试(尝试{attempt+1}/{MAX_RETRIES+1})…"
                    )
                    time.sleep(backoff)
                else:
                    logger.error(f"TickFlow history ({stock_code}) {err_type}，重试{MAX_RETRIES}次全部失败")
            except Exception as e:
                logger.error(f"TickFlow history ({stock_code}) 请求异常: {e}")
                return None

        return None

    def check_exdividend_by_factor(self, stock_codes: list, trade_date: str, start_date: str = None) -> dict:
        """
        通过复权因子检测是否发生除权

        参数：
            stock_codes: 股票代码列表，如 ['000001', '600519']
            trade_date: 交易日期 (格式：YYYYMMDD，如 20260513)
            start_date: 开始日期 (格式：YYYYMMDD)，如果提供则检测该日期到trade_date之间的除权

        返回：
            {
                'exdividend_stocks': [stock_code, ...],  # 发生除权的股票列表
                'factor_changes': {stock_code: [(date, prev_factor, curr_factor), ...], ...},
                'message': str
            }

        说明：
            - 使用 Tushare 获取复权因子
            - 对比前后两日因子，变化则判定为除权
            - 如果提供start_date，则检测该时间段内所有日期的变化
            - 自动分批查询，避免 API 限制
            - 自动扩展 start_date：若 start_date >= trade_date，向前取前一交易日确保至少2天数据
        """
        # 使用 Tushare 获取复权因子
        try:
            import tushare as ts
            import json

            tushare_config_path = 'config/tushare_config.json'
            with open(tushare_config_path, 'r', encoding='utf-8') as f:
                tushare_config = json.load(f)
            token = tushare_config.get('token') or tushare_config.get('api_key')

            if not token:
                logger.warning("未配置 Tushare token，无法检测除权")
                return {'exdividend_stocks': [], 'factor_changes': {}, 'message': '未配置 Tushare token'}

            pro = ts.pro_api(token)

            # 如果提供了start_date，则使用它；否则使用前一交易日
            if start_date:
                query_start_date = start_date
                logger.info(f"【除权检测】检测时间段: {query_start_date} 至 {trade_date}")
            else:
                query_start_date = self._get_previous_trading_date(trade_date)
                if not query_start_date:
                    return {'exdividend_stocks': [], 'factor_changes': {}, 'message': '无法获取前一交易日'}

            # 转换股票代码格式
            ts_codes = []
            for code in stock_codes:
                if code.startswith('6') or code.startswith('88'):
                    ts_codes.append(code + '.SH')
                else:
                    ts_codes.append(code + '.SZ')

            # 检测需要至少2个交易日数据，如果 start_date == trade_date 则向前扩展一天
            if query_start_date >= trade_date:
                prev_day = self._get_previous_trading_date(trade_date)
                if prev_day:
                    query_start_date = prev_day
                    logger.info(f"【除权检测】start_date 与 trade_date 相同，自动扩展至前一交易日: {query_start_date}")

            # 分批获取复权因子（Tushare adj_factor 接口限制每批最多约500只）
            BATCH_SIZE = 500
            all_dfs = []
            total_batches = (len(ts_codes) + BATCH_SIZE - 1) // BATCH_SIZE

            logger.info(f"【除权检测】共 {len(ts_codes)} 只股票，分 {total_batches} 批查询复权因子...")
            for batch_idx in range(0, len(ts_codes), BATCH_SIZE):
                batch_codes = ts_codes[batch_idx:batch_idx + BATCH_SIZE]
                batch_num = batch_idx // BATCH_SIZE + 1
                ts_codes_str = ','.join(batch_codes)

                try:
                    logger.debug(f"【除权检测】第 {batch_num}/{total_batches} 批，查询 {len(batch_codes)} 只...")
                    df_batch = pro.adj_factor(
                        ts_code=ts_codes_str,
                        start_date=query_start_date,
                        end_date=trade_date
                    )
                    if df_batch is not None and not df_batch.empty:
                        all_dfs.append(df_batch)
                except Exception as batch_e:
                    logger.warning(f"【除权检测】第 {batch_num}/{total_batches} 批查询失败: {batch_e}")
                    continue

            if not all_dfs:
                return {'exdividend_stocks': [], 'factor_changes': {}, 'message': '所有批次均未获取到复权因子数据'}

            # 合并所有批次结果
            import pandas as pd
            df = pd.concat(all_dfs, ignore_index=True)
            logger.info(f"【除权检测】成功获取 {len(df)} 条复权因子记录")

            # 按股票分组，检测因子变化
            exdividend_stocks = []
            factor_changes = {}

            for ts_code in ts_codes:
                stock_df = df[df['ts_code'] == ts_code]
                if len(stock_df) < 2:
                    continue

                # 按日期排序
                stock_df = stock_df.sort_values('trade_date', ascending=True).reset_index(drop=True)

                # 检测整个时间段内的所有变化
                stock_factor_changes = []
                for i in range(1, len(stock_df)):
                    prev_factor = stock_df.iloc[i-1]['adj_factor']
                    curr_factor = stock_df.iloc[i]['adj_factor']
                    change_date = stock_df.iloc[i]['trade_date']

                    # 对比因子是否变化（浮点数比较，使用相对误差）
                    if abs(curr_factor - prev_factor) > 0.0001 * prev_factor:
                        code = ts_code.split('.')[0]
                        stock_factor_changes.append((change_date, prev_factor, curr_factor))
                        logger.info(f"【除权检测】{code} 在 {change_date} 发生除权，复权因子 {prev_factor:.6f} -> {curr_factor:.6f}")

                if stock_factor_changes:
                    exdividend_stocks.append(ts_code.split('.')[0])
                    factor_changes[ts_code.split('.')[0]] = stock_factor_changes

            if exdividend_stocks:
                message = f"检测到 {len(exdividend_stocks)} 只股票发生除权: {exdividend_stocks}"
            else:
                message = "未检测到除权"

            return {
                'exdividend_stocks': exdividend_stocks,
                'factor_changes': factor_changes,
                'message': message
            }

        except Exception as e:
            logger.error(f"除权检测失败: {e}")
            return {'exdividend_stocks': [], 'factor_changes': {}, 'message': str(e)}

    def _get_previous_trading_date(self, trade_date: str) -> str:
        """
        获取指定日期的前一个交易日（自动跳过周六周日）

        参数：
            trade_date: 交易日期 (格式：YYYYMMDD)

        返回：
            前一个交易日的日期字符串 (YYYYMMDD)，失败返回 None
        """
        try:
            from datetime import datetime, timedelta
            dt = datetime.strptime(trade_date, '%Y%m%d')
            # 向前回退，跳过周末（周六=5, 周日=6）
            prev_dt = dt - timedelta(days=1)
            while prev_dt.weekday() >= 5:  # 周六或周日
                prev_dt = prev_dt - timedelta(days=1)
            return prev_dt.strftime('%Y%m%d')
        except Exception as e:
            logger.debug(f"计算前一交易日失败: {e}")
            return None
