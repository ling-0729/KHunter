"""
碗口反弹策略 - 通达信公式 Python 实现

指标定义：
1. 知行短期趋势线 = EMA(EMA(CLOSE,10),10)
   - 对收盘价先做一次10日EMA，再做一次10日EMA

2. 知行多空线 = (MA(CLOSE,5) + MA(CLOSE,10) + MA(CLOSE,20) + MA(CLOSE,30)) / 4
   - 5日、10日、20日、30日均线平均值

选股条件：
3. 趋势线在上 = 知行短期趋势线 > 知行多空线
   - 短期趋势在多空线上方，表示上升趋势

4. 异动放量阳线 = V>=REF(V,1)*N AND C>O AND 总市值>CAP
   - 成交量是前一天的N倍以上 AND 阳线 AND 总市值达标

5. 异动 = EXIST(关键K线, M)
   - 在M天内存在关键K线

6. KDJ计算(9,3,3): RSV->K->D->J
   - J = 3*K - 2*D

7. J值低位 = J <= J_VAL

8. 分类标记（满足条件的按优先级标记）：
   - 回落碗中：价格位于知行短期趋势线和知行多空线之间（优先级最高）
   - 靠近多空线：价格距离知行多空线 ±duokong_pct% 范围内
   - 靠近短期趋势线：价格距离知行短期趋势线 ±short_pct% 范围内

9. 选股信号 = 异动 AND 趋势线在上 AND J值低位 AND (回落碗中 OR 靠近多空线 OR 靠近短期趋势线)
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import (
    MA, EMA, LLV, HHV, REF, EXIST,
    KDJ, calculate_zhixing_trend
)


class BowlReboundStrategy(BaseStrategy):
    """碗口反弹策略 - 分类标记版"""
    
    def __init__(self, params=None):
        # 默认参数 - 与 config/strategy_params.yaml 中的默认值保持一致
        # 注意：CAP 单位是亿元，需要转换为元
        default_params = {
            'N': 4,              # 成交量倍数
            'M': 15,             # 回溯天数
            'CAP': 4000000000,   # 总市值>40亿（单位：元）
            'J_VAL': 30,         # J值上限
            'duokong_pct': 3,    # 距离多空线百分比(默认3%)
            'short_pct': 2,      # 距离短期趋势线百分比(默认2%)
            'M1': 14,            # MA周期1 (多空线)
            'M2': 28,            # MA周期2 (多空线)
            'M3': 57,            # MA周期3 (多空线)
            'M4': 114            # MA周期4 (多空线)
        }
        
        # 合并用户参数 - 如果 params 不为空，则使用 params 中的值覆盖默认值
        # 这样可以确保从 YAML 加载的参数优先级最高
        if params:
            # 转换 CAP 参数：如果是整数且小于 1000，则认为是亿元，需要转换为元
            if 'CAP' in params:
                cap_value = params['CAP']
                # 参数转换逻辑：
                # 1. 如果CAP < 1000，认为是亿元，转换为元
                # 2. 如果CAP >= 1e8，认为已经是元，不转换
                # 3. 其他情况，保持原值
                if isinstance(cap_value, (int, float)):
                    if cap_value < 1000:
                        # 认为是亿元，转换为元
                        params['CAP'] = int(cap_value * 1e8)
                    elif cap_value >= 1e8:
                        # 已经是元，不转换
                        params['CAP'] = int(cap_value)
                    else:
                        # 其他情况，保持原值
                        params['CAP'] = int(cap_value)
            
            default_params.update(params)
        
        super().__init__("碗口反弹策略", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算碗口反弹策略所需的所有指标
        """
        result = df.copy()
        
        # 1. 知行趋势线（使用technical模块，正确处理倒序数据）
        from utils.technical import calculate_zhixing_trend
        trend_df = calculate_zhixing_trend(
            result, 
            m1=self.params['M1'],
            m2=self.params['M2'],
            m3=self.params['M3'],
            m4=self.params['M4']
        )
        result['short_term_trend'] = trend_df['short_term_trend']
        result['bull_bear_line'] = trend_df['bull_bear_line']
        
        # 2. 上升趋势
        result['trend_above'] = result['short_term_trend'] > result['bull_bear_line']
        
        # 3. 分类条件计算
        # 回落碗中：价格位于多空线和短期趋势线之间（优先级最高）
        result['fall_in_bowl'] = (
            (result['close'] >= result['bull_bear_line']) & 
            (result['close'] <= result['short_term_trend'])
        )
        
        # 靠近多空线：价格距离多空线 ±duokong_pct% 范围内
        duokong_pct = self.params['duokong_pct'] / 100
        result['near_duokong'] = (
            (result['close'] >= result['bull_bear_line'] * (1 - duokong_pct)) & 
            (result['close'] <= result['bull_bear_line'] * (1 + duokong_pct))
        )
        
        # 靠近短期趋势线：价格距离短期趋势线 ±short_pct% 范围内
        short_pct = self.params['short_pct'] / 100
        result['near_short_trend'] = (
            (result['close'] >= result['short_term_trend'] * (1 - short_pct)) & 
            (result['close'] <= result['short_term_trend'] * (1 + short_pct))
        )
        
        # 4. KDJ指标
        from utils.technical import KDJ
        kdj_df = KDJ(result, n=9, m1=3, m2=3)
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']
        
        # 5. 放量阳线条件
        # 成交量 >= 前一日 * N
        from utils.technical import REF
        result['vol_ratio'] = result['volume'] / REF(result['volume'], 1)
        result['vol_surge'] = result['vol_ratio'] >= self.params['N']
        
        # 阳线：收盘价 > 开盘价
        result['positive_candle'] = result['close'] > result['open']
        
        # 总市值达标（优先从实时数据获取）
        result['market_cap_ok'] = self._check_market_cap_realtime(result)
        
        # 关键K线 = 放量 AND 阳线 AND 市值达标
        result['key_candle'] = (
            result['vol_surge'] & 
            result['positive_candle'] & 
            result['market_cap_ok']
        )
        
        # 6. 异动 = EXIST(关键K线, M)
        from utils.technical import EXIST
        result['abnormal'] = EXIST(result['key_candle'], self.params['M'])
        
        # 7. J值低位
        result['j_low'] = result['J'] <= self.params['J_VAL']
        
        return result
    
    def _check_market_cap_realtime(self, df) -> pd.Series:
        """
        检查总市值是否达标
        优先从CSV数据获取，如果异常则从腾讯财经接口获取
        """
        
        # 尝试从CSV数据获取
        if 'market_cap' in df.columns:
            # 检查数据是否合理（单位应该是元）
            sample_cap = df['market_cap'].dropna().iloc[-1] if not df['market_cap'].dropna().empty else 0
            
            # 如果市值在合理范围（10亿到1000亿之间），使用CSV数据
            if 1e9 < sample_cap < 1e11:
                return df['market_cap'] > self.params['CAP']
        
        # 从腾讯财经接口获取总市值（不再使用东方财富接口，避免连接失败）
        try:
            import requests
            # 从股票代码推断市场
            stock_code = str(df['code'].iloc[0]) if 'code' in df.columns else None
            
            if stock_code:
                # 构建腾讯财经查询代码
                if stock_code.startswith('6') or stock_code.startswith('8'):
                    query_code = f"sh{stock_code}"
                else:
                    query_code = f"sz{stock_code}"
                
                # 调用腾讯财经接口获取市值
                url = f"https://qt.gtimg.cn/q={query_code}"
                resp = requests.get(url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                if resp.status_code == 200:
                    text = resp.text.strip()
                    if '~' in text:
                        parts = text.split('~')
                        # 字段44是总市值（亿）
                        if len(parts) >= 46 and parts[44]:
                            total_cap = float(parts[44]) * 1e8  # 转为元
                            if total_cap > 0:
                                return pd.Series([total_cap > self.params['CAP']] * len(df), index=df.index)
        except Exception as e:
            # 如果腾讯接口也失败，尝试用收盘价估算
            if 'close' in df.columns:
                # 假设总股本2亿股，估算市值
                estimated_cap = df['close'] * 2e8
                return estimated_cap > self.params['CAP']
        
        # 默认返回True（不过滤）
        return pd.Series([True] * len(df), index=df.index)
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 基于最新一天的数据进行筛选
        选股后按类型分类标记（优先级：回落碗中 > 靠近多空线 > 靠近短期趋势线）
        
        参数说明：
        - M: 回溯天数，用于检查异动。设置为1时只检查当天，设置为15时检查15天内的异动
        """
        if df.empty:
            return []
        
        # 过滤退市/异常股票
        if stock_name:
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in stock_name for kw in invalid_keywords):
                return []
            
            # 过滤 ST/*ST 股票
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []
        
        # 获取最新一天的数据
        latest = df.iloc[0]
        latest_date = latest['date']
        
        # 检查最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 过滤数据异常的股票
        recent_df = df.head(30)
        if recent_df['J'].abs().mean() > 80:
            return []
        
        # ========== 核心条件检查 ==========
        
        # 1. 上升趋势
        if not latest['trend_above']:
            return []
        
        # 2. J值条件
        if not latest['j_low']:
            return []
        
        # 3. 异动条件：在M天内存在放量阳线
        # M参数可以通过config/strategy_params.yaml调整
        # 设置M=1时只检查当天，设置M=15时检查15天内的异动
        lookback_df = df.head(self.params['M'])
        key_candles = lookback_df[
            (lookback_df['key_candle'] == True) & 
            (lookback_df['close'] > lookback_df['open'])
        ]
        
        if key_candles.empty:
            return []
        
        # ========== 分类标记（按优先级） ==========
        
        reasons = []
        category = None
        
        # 优先级1：回落碗中（价格位于多空线和短期趋势线之间）
        if latest['fall_in_bowl']:
            reasons.append('回落碗中')
            category = 'bowl_center'
        # 优先级2：靠近多空线
        elif latest['near_duokong']:
            reasons.append(f'靠近多空线(±{self.params["duokong_pct"]}%)')
            category = 'near_duokong'
        # 优先级3：靠近短期趋势线
        elif latest['near_short_trend']:
            reasons.append(f'靠近短期趋势线(±{self.params["short_pct"]}%)')
            category = 'near_short_trend'
        else:
            # 不满足任何位置条件
            return []
        
        # ========== 构建选股信号 ==========
        
        latest_key = key_candles.iloc[0]
        
        signal_info = {
            'date': latest_date,
            'close': round(latest['close'], 2),
            'J': round(latest['J'], 2),
            'volume_ratio': round(latest['vol_ratio'], 2) if not pd.isna(latest['vol_ratio']) else 1.0,
            'market_cap': round(latest['market_cap'] / 1e8, 2),
            'short_term_trend': round(latest['short_term_trend'], 2),
            'bull_bear_line': round(latest['bull_bear_line'], 2),
            'reasons': reasons,
            'category': category,  # 分类标记
            'key_candle_date': latest_key['date'],
        }
        
        return [signal_info]
