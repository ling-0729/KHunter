-- 创建事件驱动策略相关表

-- 公告事件表
CREATE TABLE IF NOT EXISTS stock_announcement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    title TEXT NOT NULL,
    type TEXT,
    announcement_date DATE NOT NULL,
    url TEXT,
    importance INTEGER,
    impact_score REAL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 新闻事件表
CREATE TABLE IF NOT EXISTS stock_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    publish_time TIMESTAMP NOT NULL,
    source TEXT,
    url TEXT,
    sentiment REAL,
    importance INTEGER,
    impact_score REAL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- IPO事件表
CREATE TABLE IF NOT EXISTS stock_ipo_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT,
    stock_name TEXT NOT NULL,
    listing_board TEXT,
    meeting_date DATE,
    review_status TEXT,
    underwriter TEXT,
    issue_amount REAL,
    financing_amount REAL,
    announcement_date DATE,
    listing_date DATE,
    importance INTEGER,
    impact_score REAL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 事件分析结果表
CREATE TABLE IF NOT EXISTS event_analysis_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    event_type TEXT NOT NULL,
    event_date DATE NOT NULL,
    importance INTEGER,
    impact_score REAL,
    price_change REAL,
    volume_change REAL,
    capital_inflow REAL,
    is_qualified INTEGER,
    reason TEXT,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_announcement_stock_date ON stock_announcement(stock_code, announcement_date);
CREATE INDEX IF NOT EXISTS idx_news_publish_time ON stock_news(publish_time);
CREATE INDEX IF NOT EXISTS idx_ipo_announcement_date ON stock_ipo_event(announcement_date);
CREATE INDEX IF NOT EXISTS idx_analysis_stock_date ON event_analysis_result(stock_code, event_date);
