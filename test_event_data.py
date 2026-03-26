import akshare as ak
import pandas as pd

print('Testing event data retrieval with akshare...')
print('akshare version:', ak.__version__)

# 测试1：获取个股公告
try:
    print('\n1. Testing stock announcement...')
    announcement = ak.stock_bulletin_detail(stock='600519')
    print('Success! Announcement data shape:', announcement.shape)
    print('Columns:', announcement.columns.tolist())
    print('First 5 rows:')
    print(announcement.head())
except Exception as e:
    print('Error getting announcement:', e)

# 测试2：获取所有公告
try:
    print('\n2. Testing all announcements...')
    all_announcements = ak.stock_bulletin_all()
    print('Success! All announcements data shape:', all_announcements.shape)
    print('First 5 rows:')
    print(all_announcements.head())
except Exception as e:
    print('Error getting all announcements:', e)

# 测试3：获取事件日历
try:
    print('\n3. Testing event calendar...')
    event_calendar = ak.stock_event_calendar()
    print('Success! Event calendar data shape:', event_calendar.shape)
    print('First 5 rows:')
    print(event_calendar.head())
except Exception as e:
    print('Error getting event calendar:', e)

# 测试4：获取IPO信息
try:
    print('\n4. Testing IPO information...')
    ipo_info = ak.stock_ipo_info()
    print('Success! IPO info data shape:', ipo_info.shape)
    print('First 5 rows:')
    print(ipo_info.head())
except Exception as e:
    print('Error getting IPO info:', e)

# 测试5：获取停复牌信息
try:
    print('\n5. Testing suspension information...')
    suspension = ak.stock_suspension()
    print('Success! Suspension data shape:', suspension.shape)
    print('First 5 rows:')
    print(suspension.head())
except Exception as e:
    print('Error getting suspension info:', e)
