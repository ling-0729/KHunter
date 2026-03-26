import akshare as ak

print('Searching for event-related functions in akshare...')
print('akshare version:', ak.__version__)

# 搜索与事件、公告相关的函数
event_funcs = [f for f in dir(ak) if any(keyword in f.lower() for keyword in ['event', 'bulletin', 'notice', 'announcement', 'news', 'ipo', 'suspension'])]
print('Found event-related functions:', event_funcs)

# 测试一些可能的事件相关函数
print('\nTesting potential event functions:')

# 测试1：IPO相关
if 'stock_ipo_info' in event_funcs:
    try:
        print('\n1. Testing stock_ipo_info...')
        ipo_info = ak.stock_ipo_info()
        print('Success! IPO info data shape:', ipo_info.shape)
        print('First 3 rows:')
        print(ipo_info.head(3))
    except Exception as e:
        print('Error:', e)

# 测试2：新闻相关
if 'stock_news_em' in event_funcs:
    try:
        print('\n2. Testing stock_news_em...')
        news = ak.stock_news_em()
        print('Success! News data shape:', news.shape)
        print('First 3 rows:')
        print(news.head(3))
    except Exception as e:
        print('Error:', e)

# 测试3：公告相关
if 'stock_bulletin' in event_funcs:
    try:
        print('\n3. Testing stock_bulletin...')
        bulletin = ak.stock_bulletin()
        print('Success! Bulletin data shape:', bulletin.shape)
        print('First 3 rows:')
        print(bulletin.head(3))
    except Exception as e:
        print('Error:', e)

# 测试4：其他可能的事件函数
print('\n4. Testing other potential functions...')
# 尝试获取新闻
try:
    print('Testing stock_news...')
    news = ak.stock_news()
    print('Success! News data shape:', news.shape)
    print('First 3 rows:')
    print(news.head(3))
except Exception as e:
    print('Error:', e)
