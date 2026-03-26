import akshare as ak
import pandas as pd

print('Testing stock industry and concept data retrieval...')
print('akshare version:', ak.__version__)

# 测试1：获取股票基本信息
try:
    print('\n1. Testing stock basic information...')
    stock_info = ak.stock_zh_a_spot_em()
    print('Success! Stock info data shape:', stock_info.shape)
    print('Columns:', stock_info.columns.tolist())
    print('First 5 rows:')
    print(stock_info[['代码', '名称', '行业', '地区']].head())
except Exception as e:
    print('Error getting stock info:', e)

# 测试2：获取概念板块列表
try:
    print('\n2. Testing concept board list...')
    concept_list = ak.stock_board_concept_name_em()
    print('Success! Concept list data shape:', concept_list.shape)
    print('First 10 concepts:')
    print(concept_list.head(10))
except Exception as e:
    print('Error getting concept list:', e)

# 测试3：获取概念板块成分股
try:
    print('\n3. Testing concept stocks...')
    if 'concept_list' in locals() and not concept_list.empty:
        first_concept = concept_list.iloc[0]['name']
        concept_stocks = ak.stock_board_concept_cons_em(symbol=first_concept)
        print(f'Success! {first_concept} concept stocks data shape:', concept_stocks.shape)
        print('First 5 stocks:')
        print(concept_stocks.head())
    else:
        print('No concept list data available')
except Exception as e:
    print('Error getting concept stocks:', e)
