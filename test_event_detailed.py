import akshare as ak
import pandas as pd

print('Testing detailed event data retrieval...')
print('akshare version:', ak.__version__)

# 测试1：获取股票公告
try:
    print('\n1. Testing stock_notice_report...')
    notice = ak.stock_notice_report()
    print('Success! Notice data shape:', notice.shape)
    print('Columns:', notice.columns.tolist())
    print('First 5 rows:')
    print(notice.head())
except Exception as e:
    print('Error getting notice:', e)

# 测试2：获取股票新闻
try:
    print('\n2. Testing stock_news_em...')
    news = ak.stock_news_em()
    print('Success! News data shape:', news.shape)
    print('Columns:', news.columns.tolist())
    print('First 5 rows:')
    print(news.head())
except Exception as e:
    print('Error getting news:', e)

# 测试3：获取IPO审核信息
try:
    print('\n3. Testing stock_ipo_review_em...')
    ipo_review = ak.stock_ipo_review_em()
    print('Success! IPO review data shape:', ipo_review.shape)
    print('Columns:', ipo_review.columns.tolist())
    print('First 5 rows:')
    print(ipo_review.head())
except Exception as e:
    print('Error getting IPO review:', e)

# 测试4：获取IPO汇总信息
try:
    print('\n4. Testing stock_ipo_summary_cninfo...')
    ipo_summary = ak.stock_ipo_summary_cninfo()
    print('Success! IPO summary data shape:', ipo_summary.shape)
    print('Columns:', ipo_summary.columns.tolist())
    print('First 5 rows:')
    print(ipo_summary.head())
except Exception as e:
    print('Error getting IPO summary:', e)

# 测试5：获取新IPO信息
try:
    print('\n5. Testing stock_new_ipo_cninfo...')
    new_ipo = ak.stock_new_ipo_cninfo()
    print('Success! New IPO data shape:', new_ipo.shape)
    print('Columns:', new_ipo.columns.tolist())
    print('First 5 rows:')
    print(new_ipo.head())
except Exception as e:
    print('Error getting new IPO:', e)
