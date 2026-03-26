import akshare as ak
import pandas as pd

print('Testing industry data retrieval with akshare...')
print('akshare version:', ak.__version__)

# 测试1：获取行业分类
try:
    print('\n1. Testing industry classification...')
    industry_classification = ak.stock_board_industry_name_em()
    print('Success! Industry classification data shape:', industry_classification.shape)
    print('First 10 industries:')
    print(industry_classification.head(10))
except Exception as e:
    print('Error getting industry classification:', e)

# 测试2：获取概念板块分类
try:
    print('\n2. Testing concept classification...')
    concept_classification = ak.stock_board_concept_name_em()
    print('Success! Concept classification data shape:', concept_classification.shape)
    print('First 10 concepts:')
    print(concept_classification.head(10))
except Exception as e:
    print('Error getting concept classification:', e)

# 测试3：获取行业资金流向
try:
    print('\n3. Testing industry fund flow...')
    industry_fund_flow = ak.stock_fund_flow_industry()
    print('Success! Industry fund flow data shape:', industry_fund_flow.shape)
    print('Top 5 industries by net flow:')
    top_industries = industry_fund_flow.sort_values('净额', ascending=False).head(5)
    print(top_industries[['行业', '净额', '行业-涨跌幅']])
except Exception as e:
    print('Error getting industry fund flow:', e)

# 测试4：获取行业成分股
try:
    print('\n4. Testing industry stocks...')
    # 尝试获取第一个行业的成分股
    if 'industry_classification' in locals() and not industry_classification.empty:
        first_industry = industry_classification.iloc[0]['name']
        industry_stocks = ak.stock_board_industry_cons_em(symbol=first_industry)
        print(f'Success! {first_industry} industry stocks data shape:', industry_stocks.shape)
        print('First 10 stocks:')
        print(industry_stocks.head(10))
    else:
        print('No industry classification data available')
except Exception as e:
    print('Error getting industry stocks:', e)

# 测试5：获取行业指数历史数据
try:
    print('\n5. Testing industry index history...')
    if 'industry_classification' in locals() and not industry_classification.empty:
        first_industry = industry_classification.iloc[0]['name']
        industry_index = ak.stock_board_industry_hist_em(
            symbol=first_industry,
            start_date='20240101',
            end_date='20240105'
        )
        print(f'Success! {first_industry} index history data shape:', industry_index.shape)
        print('First 5 rows:')
        print(industry_index.head())
    else:
        print('No industry classification data available')
except Exception as e:
    print('Error getting industry index history:', e)
