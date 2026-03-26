-- 创建资金流向数据相关表

-- 资金流向表
CREATE TABLE IF NOT EXISTS stock_capital_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    date DATE NOT NULL,
    main_inflow REAL,
    super_inflow REAL,
    large_inflow REAL,
    medium_inflow REAL,
    small_inflow REAL,
    main_ratio REAL,
    net_inflow_ratio REAL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(stock_code, date)
);

-- 资金流向排行表
CREATE TABLE IF NOT EXISTS stock_capital_flow_rank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    date DATE NOT NULL,
    main_inflow REAL,
    main_inflow_rank INTEGER,
    main_ratio REAL,
    net_inflow_ratio REAL,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(stock_code, date)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_capital_flow_stock_date ON stock_capital_flow(stock_code, date);
CREATE INDEX IF NOT EXISTS idx_capital_flow_date ON stock_capital_flow(date);
CREATE INDEX IF NOT EXISTS idx_capital_flow_rank_date ON stock_capital_flow_rank(date);
CREATE INDEX IF NOT EXISTS idx_capital_flow_rank_stock_code ON stock_capital_flow_rank(stock_code);
