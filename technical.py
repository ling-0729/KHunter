#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术分析模块
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List


class TechnicalAnalyzer:
    """技术分析器"""
    
    def __init__(self):
        """初始化技术分析器"""
        pass
    
    def analyze(self, data: pd.DataFrame) -> Dict[str, Any]:
        """分析股票技术面
        
        Args:
            data: 历史行情数据
            
        Returns:
            dict: 技术分析结果
        """
        if data.empty:
            return {
                "trend": "未知",
                "indicators": {},
                "patterns": []
            }
        
        # 计算技术指标
        indicators = self._calculate_indicators(data)
        
        # 识别K线形态
        patterns = self._identify_patterns(data)
        
        # 分析趋势
        trend = self._analyze_trend(data)
        
        return {
            "trend": trend,
            "indicators": indicators,
            "patterns": patterns
        }
    
    def _calculate_indicators(self, data: pd.DataFrame) -> Dict[str, Any]:
        """计算技术指标
        
        Args:
            data: 历史行情数据
            
        Returns:
            dict: 技术指标
        """
        indicators = {}
        
        # 计算MACD
        macd = self._calculate_macd(data)
        if macd:
            indicators["MACD"] = macd
        
        # 计算KDJ
        kdj = self._calculate_kdj(data)
        if kdj:
            indicators["KDJ"] = kdj
        
        # 计算RSI
        rsi = self._calculate_rsi(data)
        if rsi:
            indicators["RSI"] = rsi
        
        # 计算布林带
        bollinger = self._calculate_bollinger(data)
        if bollinger:
            indicators["Bollinger"] = bollinger
        
        return indicators
    
    def _calculate_macd(self, data: pd.DataFrame) -> str:
        """计算MACD
        
        Args:
            data: 历史行情数据
            
        Returns:
            str: MACD状态
        """
        try:
            # 计算EMA12和EMA26
            ema12 = data['close'].ewm(span=12, adjust=False).mean()
            ema26 = data['close'].ewm(span=26, adjust=False).mean()
            
            # 计算DIF
            dif = ema12 - ema26
            
            # 计算DEA
            dea = dif.ewm(span=9, adjust=False).mean()
            
            # 计算MACD柱状图
            macd_hist = (dif - dea) * 2
            
            # 判断MACD状态
            if len(macd_hist) >= 2:
                if macd_hist.iloc[-1] > 0 and macd_hist.iloc[-2] <= 0:
                    return "金叉"
                elif macd_hist.iloc[-1] < 0 and macd_hist.iloc[-2] >= 0:
                    return "死叉"
                elif macd_hist.iloc[-1] > 0:
                    return "多头"
                else:
                    return "空头"
            
            return "未知"
            
        except Exception as e:
            print(f"计算MACD失败: {e}")
            return "未知"
    
    def _calculate_kdj(self, data: pd.DataFrame) -> str:
        """计算KDJ
        
        Args:
            data: 历史行情数据
            
        Returns:
            str: KDJ状态
        """
        try:
            # 计算RSV
            low = data['low'].rolling(window=9).min()
            high = data['high'].rolling(window=9).max()
            rsv = (data['close'] - low) / (high - low) * 100
            
            # 计算K、D、J值
            k = rsv.ewm(alpha=1/3, adjust=False).mean()
            d = k.ewm(alpha=1/3, adjust=False).mean()
            j = 3 * k - 2 * d
            
            # 判断KDJ状态
            if len(j) >= 1:
                if j.iloc[-1] > 80:
                    return "超买"
                elif j.iloc[-1] < 20:
                    return "超卖"
                elif k.iloc[-1] > d.iloc[-1]:
                    return "金叉"
                else:
                    return "死叉"
            
            return "未知"
            
        except Exception as e:
            print(f"计算KDJ失败: {e}")
            return "未知"
    
    def _calculate_rsi(self, data: pd.DataFrame) -> float:
        """计算RSI
        
        Args:
            data: 历史行情数据
            
        Returns:
            float: RSI值
        """
        try:
            # 计算价格变化
            delta = data['close'].diff()
            
            # 计算上涨和下跌
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            
            # 计算RS
            rs = gain / loss
            
            # 计算RSI
            rsi = 100 - (100 / (1 + rs))
            
            if len(rsi) >= 1:
                return float(round(rsi.iloc[-1], 2))
            
            return 50.0
            
        except Exception as e:
            print(f"计算RSI失败: {e}")
            return 50.0
    
    def _calculate_bollinger(self, data: pd.DataFrame) -> str:
        """计算布林带
        
        Args:
            data: 历史行情数据
            
        Returns:
            str: 布林带状态
        """
        try:
            # 计算移动平均线
            ma20 = data['close'].rolling(window=20).mean()
            
            # 计算标准差
            std20 = data['close'].rolling(window=20).std()
            
            # 计算布林带上轨和下轨
            upper = ma20 + 2 * std20
            lower = ma20 - 2 * std20
            
            # 判断布林带状态
            if len(data) >= 20:
                close = data['close'].iloc[-1]
                if close > upper.iloc[-1]:
                    return "突破上轨"
                elif close < lower.iloc[-1]:
                    return "突破下轨"
                else:
                    return "通道内"
            
            return "未知"
            
        except Exception as e:
            print(f"计算布林带失败: {e}")
            return "未知"
    
    def _identify_patterns(self, data: pd.DataFrame) -> List[str]:
        """识别K线形态
        
        Args:
            data: 历史行情数据
            
        Returns:
            list: K线形态列表
        """
        patterns = []
        
        if len(data) >= 3:
            # 简单的形态识别
            # 这里只是示例，实际中需要更复杂的形态识别算法
            if data['close'].iloc[-1] > data['open'].iloc[-1] and data['close'].iloc[-2] > data['open'].iloc[-2]:
                patterns.append("红三兵")
            elif data['close'].iloc[-1] < data['open'].iloc[-1] and data['close'].iloc[-2] < data['open'].iloc[-2]:
                patterns.append("黑三兵")
        
        return patterns
    
    def _analyze_trend(self, data: pd.DataFrame) -> str:
        """分析趋势
        
        Args:
            data: 历史行情数据
            
        Returns:
            str: 趋势状态
        """
        if len(data) < 10:
            return "未知"
        
        try:
            # 计算移动平均线
            ma5 = data['close'].rolling(window=5).mean()
            ma20 = data['close'].rolling(window=20).mean()
            
            # 判断趋势
            if ma5.iloc[-1] > ma20.iloc[-1] and ma5.iloc[-2] <= ma20.iloc[-2]:
                return "上升趋势"
            elif ma5.iloc[-1] < ma20.iloc[-1] and ma5.iloc[-2] >= ma20.iloc[-2]:
                return "下降趋势"
            elif ma5.iloc[-1] > ma20.iloc[-1]:
                return "上升趋势"
            elif ma5.iloc[-1] < ma20.iloc[-1]:
                return "下降趋势"
            else:
                return "横盘"
            
        except Exception as e:
            print(f"分析趋势失败: {e}")
            return "未知"


if __name__ == "__main__":
    # 测试技术分析器
    import akshare as ak
    import pandas as pd
    
    # 获取历史数据
    data = ak.stock_zh_a_hist(symbol="600519", start_date="20260101", end_date="20260323")
    data = data.rename(columns={
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount"
    })
    data['date'] = pd.to_datetime(data['date'])
    data = data.sort_values('date')
    
    # 分析技术面
    analyzer = TechnicalAnalyzer()
    result = analyzer.analyze(data)
    print("技术面分析结果:")
    print(f"趋势: {result['trend']}")
    print(f"指标: {result['indicators']}")
    print(f"形态: {result['patterns']}")
