import akshare as ak

print('akshare version:', ak.__version__)

# 测试个股资金流向的正确参数
try:
    print('\nTesting stock_individual_fund_flow with correct parameters...')
    # 尝试不同的参数
    data = ak.stock_individual_fund_flow(stock='600519')
    print('Success! Data shape:', data.shape)
    print('First 5 rows:')
    print(data.head())
except Exception as e:
    print('Error with stock parameter:', e)

try:
    print('\nTesting stock_individual_fund_flow with symbol parameter...')
    data = ak.stock_individual_fund_flow(symbol='600519')
    print('Success! Data shape:', data.shape)
    print('First 5 rows:')
    print(data.head())
except Exception as e:
    print('Error with symbol parameter:', e)

# 测试其他资金流向函数
try:
    print('\nTesting stock_fund_flow_individual...')
    data = ak.stock_fund_flow_individual(stock='600519')
    print('Success! Data shape:', data.shape)
    print('First 5 rows:')
    print(data.head())
except Exception as e:
    print('Error:', e)

# 测试资金流向排名
try:
    print('\nTesting stock_individual_fund_flow_rank...')
    data = ak.stock_individual_fund_flow_rank()
    print('Success! Data shape:', data.shape)
    print('First 5 rows:')
    print(data.head())
except Exception as e:
    print('Error:', e)
