-- 模拟交易功能数据库表定义
-- 使用 SQLite 语法

-- 创建账户表
CREATE TABLE IF NOT EXISTS trading_account (
    account_id TEXT PRIMARY KEY,
    -- 账户ID，格式为 ACC + 时间戳，主键
    account_name TEXT NOT NULL,
    -- 账户名称，默认为"默认账户"
    initial_cash REAL NOT NULL,
    -- 初始资金，固定为 1,000,000
    current_cash REAL NOT NULL,
    -- 当前可用资金，初始值为 1,000,000
    total_assets REAL NOT NULL,
    -- 总资产 = current_cash + 持仓市值
    total_profit_loss REAL DEFAULT 0,
    -- 总收益/亏损 = total_assets - initial_cash
    profit_loss_rate REAL DEFAULT 0,
    -- 收益率 = total_profit_loss / initial_cash × 100%
    created_date TEXT NOT NULL,
    -- 创建日期，格式 YYYY-MM-DD
    updated_date TEXT NOT NULL,
    -- 最后更新日期，格式 YYYY-MM-DD
    status TEXT NOT NULL DEFAULT 'active'
    -- 账户状态，active/closed
);

-- 创建持仓表
CREATE TABLE IF NOT EXISTS trading_position (
    position_id TEXT PRIMARY KEY,
    -- 持仓ID，格式为 POS + 时间戳，主键
    account_id TEXT NOT NULL,
    -- 账户ID，外键
    stock_code TEXT NOT NULL,
    -- 股票代码，如 000001
    stock_name TEXT NOT NULL,
    -- 股票名称，如 平安银行
    quantity INTEGER NOT NULL,
    -- 持仓数量，整数
    cost_price REAL NOT NULL,
    -- 成本价，加权平均价格
    current_price REAL NOT NULL,
    -- 当前价格，最新市场价格
    market_value REAL NOT NULL,
    -- 市值 = quantity × current_price
    profit_loss REAL NOT NULL,
    -- 收益/亏损 = market_value - (quantity × cost_price)
    profit_loss_rate REAL NOT NULL,
    -- 收益率 = profit_loss / (quantity × cost_price) × 100%
    last_buy_date TEXT NOT NULL,
    -- 最后买入日期，用于 T+1 验证
    created_date TEXT NOT NULL,
    -- 建仓日期
    updated_date TEXT NOT NULL,
    -- 最后更新日期
    FOREIGN KEY (account_id) REFERENCES trading_account(account_id)
);

-- 创建交易表
CREATE TABLE IF NOT EXISTS trading_transaction (
    transaction_id TEXT PRIMARY KEY,
    -- 交易ID，格式为 TXN + 时间戳，主键
    account_id TEXT NOT NULL,
    -- 账户ID，外键
    stock_code TEXT NOT NULL,
    -- 股票代码
    stock_name TEXT NOT NULL,
    -- 股票名称
    transaction_type TEXT NOT NULL,
    -- 交易类型，buy/sell
    quantity INTEGER NOT NULL,
    -- 交易数量
    price REAL NOT NULL,
    -- 交易价格
    amount REAL NOT NULL,
    -- 交易金额 = quantity × price
    commission REAL NOT NULL,
    -- 手续费
    stamp_tax REAL DEFAULT 0,
    -- 印花税（仅卖出）
    total_cost REAL NOT NULL,
    -- 总成本（买入）或净收益（卖出）
    profit_loss REAL,
    -- 收益/亏损（仅卖出）
    transaction_date TEXT NOT NULL,
    -- 交易日期，格式 YYYY-MM-DD
    created_date TEXT NOT NULL,
    -- 创建时间，格式 YYYY-MM-DD HH:MM:SS
    FOREIGN KEY (account_id) REFERENCES trading_account(account_id)
);

-- 创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_trading_position_account_id ON trading_position(account_id);
CREATE INDEX IF NOT EXISTS idx_trading_position_stock_code ON trading_position(stock_code);
CREATE INDEX IF NOT EXISTS idx_trading_transaction_account_id ON trading_transaction(account_id);
CREATE INDEX IF NOT EXISTS idx_trading_transaction_stock_code ON trading_transaction(stock_code);
CREATE INDEX IF NOT EXISTS idx_trading_transaction_date ON trading_transaction(transaction_date);
