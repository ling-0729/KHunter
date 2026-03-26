import akshare as ak
import pandas as pd

print('Testing alternative stock industry data retrieval...')
print('akshare version:', ak.__version__)

# 测试1：获取股票基本信息（使用stock_zh_a_basic）
try:
    print('\n1. Testing stock basic information (stock_zh_a_basic)...')
    stock_basic = ak.stock_zh_a_basic()
    print('Success! Stock basic data shape:', stock_basic.shape)
    print('Columns:', stock_basic.columns.tolist())
    print('First 5 rows:')
    print(stock_basic.head())
except Exception as e:
    print('Error getting stock basic info:', e)

# 测试2：获取股票实时行情
try:
    print('\n2. Testing stock real-time data...')
    stock_spot = ak.stock_zh_a_spot()
    print('Success! Stock spot data shape:', stock_spot.shape)
    print('Columns:', stock_spot.columns.tolist())
    print('First 5 rows:')
    print(stock_spot.head())
except Exception as e:
    print('Error getting stock spot data:', e)

# 测试3：获取行业分类
try:
    print('\n3. Testing industry classification...')
    industry_class = ak.stock_board_industry_name_ths()
    print('Success! Industry classification data shape:', industry_class.shape)
    print('First 10 industries:')
    print(industry_class.head(10))
except Exception as e:
    print('Error getting industry classification:', e)
