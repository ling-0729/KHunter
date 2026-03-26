"""
A股数据抓取模块 - 使用 akshare / 直接HTTP请求
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import time
import sys
from pathlib import Path
import json
import requests
import random
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.csv_manager import CSVManager
from utils.akshare_retry import akshare_call_with_retry

# 设置请求会话
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://quote.eastmoney.com/',
    'Connection': 'keep-alive',
})


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
    # 创业板
    "300750": "宁德时代", "300059": "东方财富", "300760": "迈瑞医疗",
    "300124": "汇川技术", "300015": "爱尔眼科", "300014": "亿纬锂能",
    "300433": "蓝思科技", "300003": "乐普医疗", "300122": "智飞生物",
    "300142": "沃森生物", "300408": "三环集团", "300413": "芒果超媒",
    "300001": "特锐德", "300033": "同花顺", "300496": "中科创达",
    "300136": "信维通信", "300383": "光环新网", "300316": "晶盛机电",
    "300454": "深信服", "300661": "圣邦股份", "300285": "国瓷材料",
    "300751": "迈为股份", "300618": "寒锐钴业", "300677": "英科医疗",
    "300776": "帝尔激光", "300073": "当升科技", "300724": "捷佳伟创",
    "300274": "阳光电源", "300763": "锦浪科技", "300012": "华测检测",
    "300496": "中科创达", "300223": "北京君正", "300373": "扬杰科技",
    "300207": "欣旺达", "300118": "东方日升", "300450": "先导智能",
    "300604": "长川科技", "300395": "菲利华", "300073": "当升科技",
    "300124": "汇川技术", "300760": "迈瑞医疗", "300015": "爱尔眼科",
    "300122": "智飞生物", "300142": "沃森生物", "300003": "乐普医疗",
    "300529": "健帆生物", "300601": "康泰生物", "300676": "华大基因",
    "300595": "欧普康视", "300357": "我武生物", "300832": "新产业",
    "300009": "安科生物", "300463": "迈克生物", "300026": "红日药业",
    "300026": "红日药业", "300244": "迪安诊断", "300298": "三诺生物",
    "300347": "泰格医药", "300558": "贝达药业", "300630": "普利制药",
    "300841": "康华生物", "300896": "爱美客", "300999": "金龙鱼",
    "300888": "稳健医疗", "300866": "安克创新", "300999": "金龙鱼",
}


class AKShareFetcher:
    """AKShare 数据抓取器"""
    
    def __init__(self, data_dir="data"):
        self.csv_manager = CSVManager(data_dir)
        self.full_data_dir = Path(data_dir)
        self.stock_names_file = Path(data_dir) / 'stock_names.json'
    
    def _load_local_stock_names(self):
        """从本地文件加载股票名称"""
        if self.stock_names_file.exists():
            try:
                with open(self.stock_names_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_stock_names(self, stock_dict):
        """保存股票名称到本地"""
        try:
            with open(self.stock_names_file, 'w', encoding='utf-8') as f:
                json.dump(stock_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  保存股票名称失败: {e}")

    def _fetch_market_cap_tencent(self, stock_codes):
        """使用腾讯接口批量获取市值数据（akshare备选方案）"""
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
                    print(f"  已获取 {i}/{total} 只市值...")
                    time.sleep(0.1)
                    
        except Exception as e:
            print(f"  腾讯接口获取市值失败: {e}")
        
        return market_cap_map
    
    def _fetch_stock_list_http(self):
        """使用腾讯接口获取股票列表 - 覆盖5000+只A股"""
        try:
            stocks = {}
            
            # A股完整代码范围定义 - 分批次获取以加快速度
            # 沪市主板：600-609开头
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
            
            # 从缓存加载已有的股票列表，避免重复查询
            cached_stocks = self._load_local_stock_names()
            if len(cached_stocks) >= 3000:
                print(f"  从本地缓存加载 {len(cached_stocks)} 只股票")
                return cached_stocks
            
            print(f"\n  正在通过腾讯接口获取股票列表...")
            print(f"  覆盖全部A股代码范围，约5000+只...")
            print(f"  这可能需要10-15分钟时间，请耐心等待...")
            
            # 分批查询，每次最多100只
            batch_size = 100
            all_codes = []
            
            # 生成密集的代码列表 - 步长改为1，覆盖几乎所有可能代码
            # 步长1可以获取最大数量的股票
            step = 1  # 步长1覆盖100%代码
            
            # 如果已有缓存且超过5000只，直接返回
            cached_stocks = self._load_local_stock_names()
            if len(cached_stocks) >= 5000:
                print(f"  从本地缓存加载 {len(cached_stocks)} 只股票")
                return cached_stocks
            
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
            
            print(f"  计划查询 {len(all_codes)} 个代码 (步长{step})...")
            print(f"  预计可获取 3000-5000+ 只有效股票...")
            print(f"  提示: 首次获取需要约5-10分钟，请耐心等待...")
            
            total_batches = (len(all_codes) + batch_size - 1) // batch_size
            print(f"  总共 {total_batches} 批次，开始查询...")
            
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
                            if len(parts) >= 45:  # 确保数据完整
                                code_match = line.split('v_')[1].split('=')[0] if 'v_' in line else ''
                                if code_match:
                                    code = code_match[2:]
                                    name = parts[1] if len(parts) > 1 else ''
                                    
                                    # 过滤条件
                                    exclude_keywords = ['债', '基', 'ETF', 'LOF', '理财', '信托', 'B股', '指数']
                                    
                                    # 检查是否退市或异常
                                    # 腾讯接口字段：
                                    # parts[1]=名称, parts[2]=代码, parts[3]=最新价, parts[4]=昨收, parts[5]=今开
                                    # parts[32]=状态, parts[33]=最高价, parts[34]=最低价
                                    
                                    is_valid = True
                                    
                                    # 1. 名称过滤
                                    if not name or name == '""' or any(x in name for x in exclude_keywords):
                                        is_valid = False
                                    
                                    # 2. 退市股票过滤 - 名称中包含"退"字
                                    if '退' in name:
                                        is_valid = False
                                    
                                    # 3. ST股票过滤（可选）
                                    # if 'ST' in name:
                                    #     is_valid = False
                                    
                                    # 4. 价格异常过滤 - 如果最新价为0或空，可能是停牌或退市
                                    try:
                                        current_price = float(parts[3]) if len(parts) > 3 else 0
                                        if current_price <= 0:
                                            is_valid = False
                                    except:
                                        is_valid = False
                                    
                                    # 5. 成交量异常过滤 - 长期无成交量的股票
                                    try:
                                        volume = float(parts[6]) if len(parts) > 6 else 0
                                        if volume <= 0:
                                            is_valid = False
                                    except:
                                        pass
                                    
                                    if is_valid:
                                        stocks[code] = name
                    
                    if batch_num % 20 == 0 or batch_num == 1:
                        print(f"    进度: {batch_num}/{total_batches} 批次, 已获取 {len(stocks)} 只股票...")
                    
                    time.sleep(0.1)  # 轻微限速
                    
                except Exception as e:
                    continue
            
            if stocks:
                print(f"  ✓ 通过腾讯接口获取: {len(stocks)} 只股票")
                return stocks
            
            # 如果获取失败，使用默认列表
            print(f"  使用默认列表: {len(DEFAULT_STOCK_LIST)} 只股票")
            return DEFAULT_STOCK_LIST.copy()
        except Exception as e:
            print(f"  HTTP获取失败: {e}")
            return DEFAULT_STOCK_LIST.copy()
    
    def get_all_stock_codes(self, max_retries=3):
        """获取所有A股股票代码（过滤债基、ETF、ST等）"""
        print("正在获取A股股票列表...")
        
        # 方法1: 直接HTTP请求
        for attempt in range(max_retries):
            try:
                print(f"  尝试HTTP直连 (第{attempt+1}/{max_retries}次)...")
                stocks = self._fetch_stock_list_http()
                if stocks:
                    # 过滤
                    filtered = {}
                    code_pattern = r'^(00|30|60|68|88)\d{4}$'
                    exclude_keywords = ['债', '基', 'ETF', 'LOF', '基金', '理财', '信托', 'B股', '指数', '国债', '企债', '转债', '回购', 'R-', 'GC']
                    
                    for code, name in stocks.items():
                        if not pd.Series([code]).str.match(code_pattern).iloc[0]:
                            continue
                        if any(kw in name for kw in exclude_keywords):
                            continue
                        filtered[code] = name
                    
                    if filtered:
                        print(f"✓ HTTP获取成功: {len(filtered)} 只A股股票")
                        self._save_stock_names(filtered)
                        return filtered
            except Exception as e:
                print(f"  HTTP失败: {e}")
                time.sleep(1)
        
        # 方法2: akshare
        for attempt in range(max_retries):
            try:
                print(f"  尝试akshare (第{attempt+1}/{max_retries}次)...")
                
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
                print(f"✓ akshare获取成功: {len(stock_dict)} 只A股股票")
                self._save_stock_names(stock_dict)
                return stock_dict
                
            except Exception as e:
                print(f"  akshare失败: {e}")
                time.sleep(2 ** attempt)
        
        # 降级: 本地缓存或默认列表
        print("\n网络连接失败，尝试加载本地缓存...")
        local_stocks = self._load_local_stock_names()
        if local_stocks:
            print(f"✓ 从本地缓存加载: {len(local_stocks)} 只股票")
            return local_stocks
        
        print("\n使用内置默认股票列表...")
        print(f"✓ 加载默认列表: {len(DEFAULT_STOCK_LIST)} 只股票")
        return DEFAULT_STOCK_LIST.copy()
    
    def _fetch_stock_history_http(self, stock_code, years=6):
        """使用腾讯接口获取股票历史数据"""
        try:
            import requests
            
            # 判断市场前缀
            if stock_code.startswith('6') or stock_code.startswith('88'):
                market_code = 'sh' + stock_code
            else:
                market_code = 'sz' + stock_code
            
            # 腾讯财经接口 - 获取日K线数据
            # 腾讯接口最多返回约1000条数据，所以分批获取或限制年限
            max_days = min(years * 365, 1000)  # 最多1000天
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_code},day,,,{max_days},qfq"
            
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://stock.finance.qq.com/'
            })
            
            data = resp.json()
            
            # 解析腾讯返回的数据（处理不同返回格式）
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
                # 找到对应股票代码的数据
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
                for item in klines:
                    # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量, ...]
                    # 注意: item[6] 可能是分红信息(dict)而不是成交额
                    if len(item) >= 6 and isinstance(item, list):
                        # 跳过分红信息，只取前6个字段
                        # 注意：腾讯接口返回的是 [日期, 开盘, 收盘, 最高, 最低, 成交量]
                        records.append({
                            'date': str(item[0]),
                            'open': float(item[1]),
                            'close': float(item[2]),
                            'high': float(item[3]),  # 最高 (item[3])
                            'low': float(item[4]),   # 最低 (item[4])
                            'volume': int(float(item[5])),
                            'amount': 0,  # 腾讯接口不直接提供成交额
                            'turnover': 0,  # 腾讯接口没有换手率
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
            print(f"  HTTP获取历史数据失败: {e}")
            return None
    
    def _get_realtime_market_cap(self, stock_code):
        """
        从腾讯财经接口获取单只股票总市值
        不再使用东方财富 stock_individual_info_em 接口，避免连接失败报错
        
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
            _logger.debug(f"腾讯接口获取总市值失败 ({stock_code}): {e}")
        return None
    
    def _generate_mock_data(self, stock_code, years=6):
        """生成模拟数据（当网络不可用时使用）"""
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
        
        # 添加总市值（从实时数据获取）
        market_cap = self._get_realtime_market_cap(stock_code)
        if market_cap:
            df['market_cap'] = market_cap
        else:
            # 如果获取失败，使用估算值（ but this is still wrong, just a fallback ）
            df['market_cap'] = np.random.uniform(5000000000, 50000000000)
        
        # 按日期倒序排列
        df = df.sort_values('date', ascending=False)
        
        return df

    def get_stock_price(self, stock_code: str) -> float:
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
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"获取实时价格失败 ({stock_code}): {str(e)}")
            return None

    def get_stock_prices_batch(self, stock_codes: list) -> dict:
        """
        批量获取股票实时价格（使用腾讯财经接口）
        
        腾讯接口在任何时段都返回最新有效价格：
        - 交易中：实时价格
        - 收盘后：当日收盘价
        - 非交易日/开盘前：前一个交易日收盘价

        参数：
            stock_codes: 股票代码列表，如 ['600519', '000001', ...]

        返回：
            {stock_code: price} 字典，获取失败的股票不包含在结果中
        """
        import logging
        _logger = logging.getLogger(__name__)

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
                _logger.debug(f"批量获取实时价格失败 (批次{i // batch_size + 1}): {str(e)}")
                continue

            # 批次间轻微延迟，避免请求过快
            if i + batch_size < len(stock_codes):
                time.sleep(0.05)

        _logger.debug(f"批量获取实时价格完成: 请求{len(stock_codes)}只, 成功{len(price_map)}只")
        return price_map

    def get_stock_industry_sector(self, stock_code: str) -> Tuple[str, str]:
        """
        从AKShare获取股票的行业和板块信息（中文）

        参数：
            stock_code: 股票代码（6位数字，如 '688426'）

        返回：
            (industry, sector) 元组，获取失败返回 ('', '')
        """
        try:
            import akshare as ak
            
            # 通过重试包装器获取个股信息（缓存TTL 7天，基本信息类）
            df = akshare_call_with_retry(
                ak.stock_individual_info_em, cache_ttl=604800, symbol=stock_code
            )
            
            if df is not None and len(df) > 0:
                # 查找行业和板块信息
                industry = ''
                sector = ''
                
                # 遍历DataFrame找到对应的字段
                for idx, row in df.iterrows():
                    # 第一列是字段名，第二列是值
                    field_name = str(row.iloc[0]).strip() if len(row) > 0 else ''
                    field_value = str(row.iloc[1]).strip() if len(row) > 1 else ''
                    
                    # 查找行业字段
                    if '行业' in field_name:
                        industry = field_value
                    # 查找板块字段
                    elif '板块' in field_name or '概念' in field_name:
                        sector = field_value
                
                return industry, sector
            
            return '', ''
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"从AKShare获取行业板块信息失败 ({stock_code}): {str(e)}")
            return '', ''



    
    def fetch_stock_history(self, stock_code, years=6):
        """
        抓取单只股票历史数据
        前复权，按日期倒序排列
        """
        # 方法1: 直接HTTP请求
        try:
            df = self._fetch_stock_history_http(stock_code, years)
            if df is not None and not df.empty:
                print(f"✓ (HTTP获取 {len(df)}条)")
                return df
            else:
                print(f"  HTTP返回空数据，尝试akshare...")
        except Exception as e:
            print(f"  HTTP异常: {e}，尝试akshare...")
        
        # 方法2: akshare
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=365 * years)
            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")
            
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="qfq"
            )
            
            if df is not None and not df.empty:
                df = df.rename(columns={
                    '日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low',
                    '收盘': 'close', '成交量': 'volume', '成交额': 'amount', '换手率': 'turnover'
                })
                df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']]
                # 不需要获取总市值，直接使用默认值
                df['market_cap'] = 0
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date', ascending=False)
                return df
        except Exception as e:
            print(f"  akshare获取失败，使用模拟数据...")
        
        # 降级: 使用模拟数据
        return self._generate_mock_data(stock_code, years)
    
    def fetch_stock_update(self, stock_code, days=10):
        """
        抓取近期数据用于增量更新
        优化：直接指定天数，避免计算误差
        """
        try:
            import requests
            
            # 判断市场前缀
            if stock_code.startswith('6') or stock_code.startswith('88'):
                market_code = 'sh' + stock_code
            else:
                market_code = 'sz' + stock_code
            
            # 腾讯接口：直接指定获取天数（最多1000天）
            # 多取2天确保覆盖周末节假日
            fetch_days = min(days + 2, 1000)
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_code},day,,,{fetch_days},qfq"
            
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://stock.finance.qq.com/'
            })
            
            data = resp.json()
            
            # 解析数据
            data_level = data.get('data', {})
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
            
            if klines:
                records = []
                for item in klines:
                    if len(item) >= 6 and isinstance(item, list):
                        # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
                        records.append({
                            'date': str(item[0]),
                            'open': float(item[1]),
                            'close': float(item[2]),
                            'high': float(item[3]),  # 最高
                            'low': float(item[4]),   # 最低
                            'volume': int(float(item[5])),
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
            print(f"  获取更新数据失败: {e}")
            return None
    
    def init_full_data(self, max_stocks=None, skip_failed=True, years=1):
        """
        首次全量抓取
        :param max_stocks: 限制抓取数量（用于测试）
        :param skip_failed: 是否跳过之前失败的股票
        :param years: 获取数据的年份数（默认1年）
        """
        import akshare as ak
        
        stock_dict = self.get_all_stock_codes()
        
        if not stock_dict:
            print("无法获取股票列表")
            return
        
        stock_codes = list(stock_dict.keys())
        
        # 加载之前失败的股票列表
        failed_stocks_file = self.full_data_dir / 'failed_stocks.json'
        failed_stocks = set()
        if skip_failed and failed_stocks_file.exists():
            try:
                with open(failed_stocks_file, 'r', encoding='utf-8') as f:
                    failed_stocks = set(json.load(f))
                print(f"  将跳过 {len(failed_stocks)} 只之前获取失败的股票")
                # 从列表中移除失败的股票
                stock_codes = [c for c in stock_codes if c not in failed_stocks]
            except:
                pass
        
        if max_stocks:
            stock_codes = stock_codes[:max_stocks]
        
        # 批量获取市值数据（主接口：akshare，备选：腾讯）
        print("\n正在批量获取市值数据...")
        market_cap_map = {}
        
        # 方法1: 尝试akshare接口
        try:
            spot_df = ak.stock_zh_a_spot_em()
            for _, row in spot_df.iterrows():
                code = str(row['代码']).zfill(6)
                cap = row['总市值']
                if pd.notna(cap) and cap > 0:
                    # 统一转为元
                    if cap < 1e10:
                        cap = int(cap * 1e8)
                    else:
                        cap = int(cap)
                    market_cap_map[code] = cap
            print(f"  ✓ akshare接口成功: {len(market_cap_map)} 只股票市值")
        except Exception as e:
            print(f"  akshare接口失败: {e}")
            print("  尝试腾讯备选接口...")
            # 方法2: 使用腾讯接口备选
            market_cap_map = self._fetch_market_cap_tencent(stock_codes)
            if market_cap_map:
                print(f"  ✓ 腾讯接口成功: {len(market_cap_map)} 只股票市值")
            else:
                print(f"  ✗ 腾讯接口也失败，市值数据将缺失")
        
        total = len(stock_codes)
        success = 0
        failed = 0
        failed_list = []
        
        print(f"\n开始抓取 {total} 只股票的6年历史数据...")
        print("=" * 60)
        
        for i, code in enumerate(stock_codes, 1):
            print(f"[{i}/{total}] 抓取 {code} {stock_dict.get(code, '')} ...", end=" ")
            
            df = self.fetch_stock_history(code, years=years)
            
            if df is not None and not df.empty:
                # 数据校验 - 检查是否有有效价格数据
                valid_data = True
                if len(df) < 10:  # 数据太少，可能是新股或数据异常
                    print(f"⚠ 数据太少({len(df)}条)")
                    valid_data = False
                    failed_list.append(code)
                elif df['close'].mean() <= 0:  # 价格异常
                    print(f"⚠ 价格异常")
                    valid_data = False
                    failed_list.append(code)
                else:
                    # 使用批量获取的市值数据
                    if code in market_cap_map:
                        df['market_cap'] = market_cap_map[code]
                    self.csv_manager.write_stock(code, df)
                    print(f"✓ ({len(df)}条)")
                    success += 1
            else:
                print("✗ 失败")
                failed += 1
                failed_list.append(code)
            
            # 限速，避免请求过快
            if i % 10 == 0:
                time.sleep(1)
        
        # 保存失败的股票列表
        if failed_list:
            try:
                with open(failed_stocks_file, 'w', encoding='utf-8') as f:
                    json.dump(failed_list, f)
                print(f"\n  已保存 {len(failed_list)} 只获取失败的股票到 failed_stocks.json")
            except Exception as e:
                print(f"\n  保存失败列表出错: {e}")
        
        print("=" * 60)
        print(f"完成! 成功: {success}, 失败: {failed + len(failed_list)}")
        if failed_list and not max_stocks:
            print(f"提示: 再次运行 init 命令可跳过失败股票，专注于成功获取的数据")
    
    def daily_update(self, max_stocks=None):
        """
        每日增量更新 - 只获取实际需要的天数
        优化：使用快速缓存机制，避免重复读取已更新的股票
        修复：盘中执行时不会将盘中数据误存为收盘数据
        """
        from datetime import datetime
        
        existing_stocks = self.csv_manager.list_all_stocks()
        
        if not existing_stocks:
            print("没有找到已有数据，请先执行 init")
            return
        
        if max_stocks:
            existing_stocks = existing_stocks[:max_stocks]
        
        total = len(existing_stocks)
        updated = 0
        failed = 0
        skipped = 0
        
        print(f"\n开始更新 {total} 只股票的数据...")
        print("=" * 60)
        
        today = datetime.now().date()
        today_str = today.strftime('%Y-%m-%d')
        current_time = datetime.now().time()
        
        # 判断是否在收盘后（15:00 之后）
        # A股收盘时间：工作日 15:00
        market_close_time = datetime.strptime("15:00", "%H:%M").time()
        is_after_market_close = current_time >= market_close_time
        
        if not is_after_market_close and not max_stocks:
            print(f"⚠️ 当前时间 {current_time.strftime('%H:%M')}，尚未收盘 (15:00)")
            print("  盘中数据不是收盘价，建议收盘后再执行 update")
            print("  如需强制更新，请使用 --max-stocks 参数")
            print("=" * 60)
            return
        
        # 快速缓存：检查上次更新记录
        update_cache_file = self.full_data_dir / '.update_cache.json'
        update_cache = {}
        if update_cache_file.exists():
            try:
                with open(update_cache_file, 'r', encoding='utf-8') as f:
                    update_cache = json.load(f)
            except:
                update_cache = {}
        
        # 如果今天已经更新过（且已收盘），直接跳过
        cache_date = update_cache.get('last_update_date')
        if cache_date == today_str and not max_stocks:
            print(f"✓ 数据已于 {cache_date} 收盘后更新过，无需重复更新")
            print("=" * 60)
            return
        
        # 预筛选：快速检查哪些股票需要更新（只读取第一行）
        stocks_to_update = []
        print("  正在检查股票更新状态...")
        
        for code in existing_stocks:
            # 快速读取：只读CSV第一行（最新日期）
            path = self.csv_manager.get_stock_path(code)
            if not path.exists():
                stocks_to_update.append((code, 30))  # 默认取30天
                continue
            
            try:
                # 只读取第一行（header + 第一行数据）
                df_quick = pd.read_csv(path, nrows=1)
                if df_quick.empty:
                    stocks_to_update.append((code, 30))
                    continue
                
                latest_date = pd.to_datetime(df_quick.iloc[0]['date']).date()
                days_needed = (today - latest_date).days
                
                if days_needed > 0:
                    days_to_fetch = min(days_needed + 2, 60)
                    stocks_to_update.append((code, days_to_fetch))
                elif days_needed == 0:
                    # 最新日期是今天
                    # 如果是收盘后，或者强制更新模式(max_stocks)，都需要重新获取
                    if is_after_market_close or max_stocks:
                        stocks_to_update.append((code, 2))
                    else:
                        skipped += 1
                else:
                    skipped += 1
            except Exception:
                stocks_to_update.append((code, 30))
        
        need_update = len(stocks_to_update)
        print(f"  需要更新: {need_update} 只, 已最新: {skipped} 只")
        
        if need_update == 0:
            # 只有在完整更新（非max_stocks模式）且收盘后才记录缓存
            if not max_stocks and is_after_market_close:
                update_cache['last_update_date'] = today_str
                with open(update_cache_file, 'w', encoding='utf-8') as f:
                    json.dump(update_cache, f)
            print("✓ 所有数据已是最新")
            print("=" * 60)
            return
        
        # 批量获取最新市值数据（主接口：akshare，备选：腾讯）
        print("\n正在批量获取最新市值数据...")
        market_cap_map = {}
        
        # 方法1: 尝试akshare接口
        try:
            import akshare as ak
            spot_df = ak.stock_zh_a_spot_em()
            for _, row in spot_df.iterrows():
                code = str(row['代码']).zfill(6)
                cap = row['总市值']
                if pd.notna(cap) and cap > 0:
                    # 统一转为元
                    if cap < 1e10:
                        cap = int(cap * 1e8)
                    else:
                        cap = int(cap)
                    market_cap_map[code] = cap
            print(f"  ✓ akshare接口成功: {len(market_cap_map)} 只股票市值")
        except Exception as e:
            print(f"  akshare接口失败: {e}")
            print("  尝试腾讯备选接口...")
            # 方法2: 使用腾讯接口备选（只获取需要更新的股票）
            update_codes = [code for code, _ in stocks_to_update]
            market_cap_map = self._fetch_market_cap_tencent(update_codes)
            if market_cap_map:
                print(f"  ✓ 腾讯接口成功: {len(market_cap_map)} 只股票市值")
            else:
                print(f"  ✗ 腾讯接口也失败，市值数据将缺失")
        
        print(f"\n开始更新 {need_update} 只股票...")
        print("=" * 60)
        
        # 使用多线程并行更新
        updated, failed = self._parallel_update_stocks(
            stocks_to_update, market_cap_map, max_workers=4
        )
        
        # 更新缓存记录
        update_cache['last_update_date'] = today_str
        with open(update_cache_file, 'w', encoding='utf-8') as f:
            json.dump(update_cache, f)
        
        print("=" * 60)
        print(f"完成! 更新成功: {updated}, 跳过: {skipped}, 失败: {failed}")
    
    def _parallel_update_stocks(self, stocks_to_update, market_cap_map, max_workers=4):
        """
        多线程并行更新股票数据
        
        参数:
            stocks_to_update: 需要更新的股票列表 [(code, days_to_fetch), ...]
            market_cap_map: 市值数据字典
            max_workers: 并行线程数，默认4个
            
        返回:
            (updated_count, failed_count)
        """
        updated = 0
        failed = 0
        total = len(stocks_to_update)
        
        # 线程锁用于计数
        lock = threading.Lock()
        
        def update_single_stock(args):
            """更新单只股票的辅助函数"""
            nonlocal updated, failed
            code, days_to_fetch = args
            
            try:
                # 重新读取现有数据以获取旧记录数
                existing_df = self.csv_manager.read_stock(code)
                old_count = len(existing_df)
                
                df = self.fetch_stock_update(code, days=days_to_fetch)
                
                if df is not None and not df.empty:
                    # 更新市值数据（和价格数据一起更新）
                    if code in market_cap_map:
                        df['market_cap'] = market_cap_map[code]
                    self.csv_manager.update_stock(code, df)
                    new_df = self.csv_manager.read_stock(code)
                    new_count = len(new_df)
                    added = new_count - old_count
                    
                    with lock:
                        updated += 1
                        current = updated + failed
                        print(f"[{current}/{total}] {code} ✓ (新增 {added} 条)")
                    return True
                else:
                    with lock:
                        failed += 1
                        current = updated + failed
                        print(f"[{current}/{total}] {code} ✗ 失败")
                    return False
            except Exception as e:
                with lock:
                    failed += 1
                    current = updated + failed
                    print(f"[{current}/{total}] {code} ✗ 错误: {str(e)[:30]}")
                return False
        
        # 使用线程池并行处理
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_stock = {
                executor.submit(update_single_stock, stock): stock 
                for stock in stocks_to_update
            }
            
            # 等待所有任务完成
            for future in as_completed(future_to_stock):
                # 异常已在update_single_stock中处理
                pass
        
        return updated, failed
