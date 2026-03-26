-- 创建板块轮动策略相关表

-- 板块指数表
CREATE TABLE IF NOT EXISTS sector_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    sector_type TEXT NOT NULL,
    date DATE NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    change_pct REAL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sector_code, date)
);

-- 板块成分股表
CREATE TABLE IF NOT EXISTS sector_stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    weight REAL,
    entry_date DATE,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sector_code, stock_code)
);

-- 个股基础信息表
CREATE TABLE IF NOT EXISTS stock_basic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    industry TEXT,
    area TEXT,
    market TEXT,
    list_date DATE,
    market_cap REAL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 个股价格表
CREATE TABLE IF NOT EXISTS stock_price (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    date DATE NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    change_pct REAL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(stock_code, date)
);

-- 板块轮动结果表
CREATE TABLE IF NOT EXISTS sector_rotation_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    sector_change_pct REAL,
    stock_change_pct REAL,
    volume_ratio REAL,
    trend_direction TEXT,
    correlation REAL,
    composite_score REAL,
    reason TEXT,
    selected_date DATE NOT NULL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_sector_index_code_date ON sector_index(sector_code, date);
CREATE INDEX IF NOT EXISTS idx_sector_index_type_date ON sector_index(sector_type, date);
CREATE INDEX IF NOT EXISTS idx_sector_stock_sector_code ON sector_stock(sector_code);
CREATE INDEX IF NOT EXISTS idx_sector_stock_stock_code ON sector_stock(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_basic_code ON stock_basic(code);
CREATE INDEX IF NOT EXISTS idx_stock_price_code_date ON stock_price(stock_code, date);
CREATE INDEX IF NOT EXISTS idx_sector_rotation_result_stock_code ON sector_rotation_result(stock_code);
CREATE INDEX IF NOT EXISTS idx_sector_rotation_result_sector_code ON sector_rotation_result(sector_code);
CREATE INDEX IF NOT EXISTS idx_sector_rotation_result_selected_date ON sector_rotation_result(selected_date);
