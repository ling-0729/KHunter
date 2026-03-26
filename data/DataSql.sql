-- ============================================
-- KHunter 系统 - 数据库表定义脚本
-- ============================================
-- 数据库类型: SQLite
-- 创建日期: 2026-03-26
-- 说明: 包含选股记录、交易账户、持仓、交易等所有表

-- ============================================
-- 1. 股票基础信息表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_basic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    code TEXT NOT NULL UNIQUE,
    -- code: 股票代码，类型TEXT，必填，唯一，例如000001
    name TEXT NOT NULL,
    -- name: 股票名称，类型TEXT，必填，例如平安银行
    industry TEXT,
    -- industry: 所属行业，类型TEXT，可选，例如银行
    area TEXT,
    -- area: 所属地区，类型TEXT，可选，例如深圳
    market TEXT,
    -- market: 市场类型，类型TEXT，可选，例如主板
    list_date TEXT,
    -- list_date: 上市日期，类型TEXT，可选，格式YYYY-MM-DD
    update_time TEXT DEFAULT CURRENT_TIMESTAMP
    -- update_time: 更新时间，类型TEXT，默认当前时间，格式YYYY-MM-DD HH:MM:SS
);

-- ============================================
-- 2. 选股记录表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_selection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    selection_date TEXT NOT NULL,
    -- selection_date: 选股日期，类型TEXT，必填，格式YYYY-MM-DD
    strategy_name TEXT NOT NULL,
    -- strategy_name: 策略名称，类型TEXT，必填，例如碗口反弹策略
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    stock_name TEXT NOT NULL,
    -- stock_name: 股票名称，类型TEXT，必填，例如平安银行
    selection_price REAL,
    -- selection_price: 选入价格，类型REAL，可选，例如10.50
    current_price REAL,
    -- current_price: 当前价格，类型REAL，可选，例如10.60
    j_value REAL,
    -- j_value: J值，类型REAL，可选，例如-7.65
    category TEXT,
    -- category: 分类，类型TEXT，可选，例如回落碗中
    key_kline_date TEXT,
    -- key_kline_date: 关键K线日期，类型TEXT，可选，格式YYYY-MM-DD
    reason TEXT,
    -- reason: 入选理由，类型TEXT，可选，例如回落碗中
    similarity_score REAL,
    -- similarity_score: 相似度分数，类型REAL，可选，范围0-100
    create_time TEXT DEFAULT CURRENT_TIMESTAMP
    -- create_time: 创建时间，类型TEXT，默认当前时间，格式YYYY-MM-DD HH:MM:SS
);

-- ============================================
-- 3. 交易账户表
-- ============================================
CREATE TABLE IF NOT EXISTS trading_account (
    account_id TEXT PRIMARY KEY,
    -- account_id: 账户ID，类型TEXT，必填，主键，格式ACC+时间戳
    account_name TEXT NOT NULL,
    -- account_name: 账户名称，类型TEXT，必填，例如默认账户
    initial_cash REAL NOT NULL,
    -- initial_cash: 初始资金，类型REAL，必填，例如1000000.0
    current_cash REAL NOT NULL,
    -- current_cash: 当前可用资金，类型REAL，必填，例如900000.0
    total_assets REAL NOT NULL,
    -- total_assets: 总资产，类型REAL，必填，计算值=current_cash+持仓市值
    total_profit_loss REAL DEFAULT 0,
    -- total_profit_loss: 总收益/亏损，类型REAL，默认0，计算值=total_assets-initial_cash
    profit_loss_rate REAL DEFAULT 0,
    -- profit_loss_rate: 收益率，类型REAL，默认0，计算值=total_profit_loss/initial_cash*100
    created_date TEXT NOT NULL,
    -- created_date: 创建日期，类型TEXT，必填，格式YYYY-MM-DD
    updated_date TEXT NOT NULL,
    -- updated_date: 最后更新日期，类型TEXT，必填，格式YYYY-MM-DD
    status TEXT NOT NULL DEFAULT 'active'
    -- status: 账户状态，类型TEXT，必填，默认active，可选值active/closed
);

-- ============================================
-- 4. 持仓表
-- ============================================
CREATE TABLE IF NOT EXISTS trading_position (
    position_id TEXT PRIMARY KEY,
    -- position_id: 持仓ID，类型TEXT，必填，主键，格式POS+时间戳
    account_id TEXT NOT NULL,
    -- account_id: 账户ID，类型TEXT，必填，外键关联trading_account
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    stock_name TEXT NOT NULL,
    -- stock_name: 股票名称，类型TEXT，必填，例如平安银行
    quantity INTEGER NOT NULL,
    -- quantity: 持仓数量，类型INTEGER，必填，例如100
    cost_price REAL NOT NULL,
    -- cost_price: 成本价，类型REAL，必填，加权平均价格，例如10.50
    current_price REAL NOT NULL,
    -- current_price: 当前价格，类型REAL，必填，最新市场价格，例如10.60
    market_value REAL NOT NULL,
    -- market_value: 市值，类型REAL，必填，计算值=quantity*current_price
    profit_loss REAL NOT NULL,
    -- profit_loss: 收益/亏损，类型REAL，必填，计算值=market_value-(quantity*cost_price)
    profit_loss_rate REAL NOT NULL,
    -- profit_loss_rate: 收益率，类型REAL，必填，计算值=profit_loss/(quantity*cost_price)*100
    last_buy_date TEXT NOT NULL,
    -- last_buy_date: 最后买入日期，类型TEXT，必填，格式YYYY-MM-DD，用于T+1验证
    created_date TEXT NOT NULL,
    -- created_date: 建仓日期，类型TEXT，必填，格式YYYY-MM-DD
    updated_date TEXT NOT NULL,
    -- updated_date: 最后更新日期，类型TEXT，必填，格式YYYY-MM-DD
    FOREIGN KEY (account_id) REFERENCES trading_account(account_id) ON DELETE CASCADE
);

-- ============================================
-- 5. 交易记录表
-- ============================================
CREATE TABLE IF NOT EXISTS trading_transaction (
    transaction_id TEXT PRIMARY KEY,
    -- transaction_id: 交易ID，类型TEXT，必填，主键，格式TXN+时间戳
    account_id TEXT NOT NULL,
    -- account_id: 账户ID，类型TEXT，必填，外键关联trading_account
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    stock_name TEXT NOT NULL,
    -- stock_name: 股票名称，类型TEXT，必填，例如平安银行
    transaction_type TEXT NOT NULL,
    -- transaction_type: 交易类型，类型TEXT，必填，可选值buy/sell
    quantity INTEGER NOT NULL,
    -- quantity: 交易数量，类型INTEGER，必填，例如100
    price REAL NOT NULL,
    -- price: 交易价格，类型REAL，必填，例如10.50
    amount REAL NOT NULL,
    -- amount: 交易金额，类型REAL，必填，计算值=quantity*price
    commission REAL NOT NULL,
    -- commission: 手续费，类型REAL，必填，例如10.50
    stamp_tax REAL DEFAULT 0,
    -- stamp_tax: 印花税，类型REAL，默认0，仅卖出时有值
    total_cost REAL NOT NULL,
    -- total_cost: 总成本，类型REAL，必填，买入时=amount+commission，卖出时=amount-commission-stamp_tax
    profit_loss REAL,
    -- profit_loss: 收益/亏损，类型REAL，可选，仅卖出时有值
    transaction_date TEXT NOT NULL,
    -- transaction_date: 交易日期，类型TEXT，必填，格式YYYY-MM-DD
    created_date TEXT NOT NULL,
    -- created_date: 创建时间，类型TEXT，必填，格式YYYY-MM-DD HH:MM:SS
    FOREIGN KEY (account_id) REFERENCES trading_account(account_id) ON DELETE CASCADE
);

-- ============================================
-- 6. 创建索引以提高查询性能
-- ============================================
CREATE INDEX IF NOT EXISTS idx_stock_basic_code ON stock_basic(code);
CREATE INDEX IF NOT EXISTS idx_stock_selection_date ON stock_selection(selection_date);
CREATE INDEX IF NOT EXISTS idx_stock_selection_strategy ON stock_selection(strategy_name);
CREATE INDEX IF NOT EXISTS idx_stock_selection_code ON stock_selection(stock_code);
CREATE INDEX IF NOT EXISTS idx_trading_position_account ON trading_position(account_id);
CREATE INDEX IF NOT EXISTS idx_trading_position_code ON trading_position(stock_code);
CREATE INDEX IF NOT EXISTS idx_trading_transaction_account ON trading_transaction(account_id);
CREATE INDEX IF NOT EXISTS idx_trading_transaction_code ON trading_transaction(stock_code);
CREATE INDEX IF NOT EXISTS idx_trading_transaction_date ON trading_transaction(transaction_date);
