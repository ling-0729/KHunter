import akshare as ak

print('akshare version:', ak.__version__)

# 测试个股资金流向
try:
    print('\nTesting stock_individual_fund_flow...')
    data = ak.stock_individual_fund_flow(symbol='600519')
    print('Success! Data shape:', data.shape)
    print('First 5 rows:')
    print(data.head())
except Exception as e:
    print('Error:', e)

# 测试资金流向汇总
try:
    print('\nTesting stock_market_fund_flow...')
    data = ak.stock_market_fund_flow()
    print('Success! Data shape:', data.shape)
    print('First 5 rows:')
    print(data.head())
except Exception as e:
    print('Error:', e)

# 测试行业资金流向
try:
    print('\nTesting stock_fund_flow_industry...')
    data = ak.stock_fund_flow_industry()
    print('Success! Data shape:', data.shape)
    print('First 5 rows:')
    print(data.head())
except Exception as e:
    print('Error:', e)
