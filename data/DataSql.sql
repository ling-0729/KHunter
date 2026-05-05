-- ============================================
-- KHunter 系统 - 数据库表定义模板
-- ============================================
-- 数据库类型: SQLite
-- 创建日期: 2026-04-08
-- 说明: 包含选股记录、交易账户、持仓、交易等所有表

-- ============================================
-- 1. 股票基本信息表
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
    market_cap REAL,
    -- market_cap: 市值，类型REAL，可选，单位亿元，例如100.5
    update_time TEXT DEFAULT CURRENT_TIMESTAMP
    -- update_time: 更新时间，类型TEXT，默认当前时间，格式YYYY-MM-DD HH:MM:SS
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
    -- total_profit_loss: 总盈亏，类型REAL，默认0，计算值=total_assets-initial_cash
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
    -- profit_loss: 盈亏，类型REAL，必填，计算值=market_value-(quantity*cost_price)
    profit_loss_rate REAL NOT NULL,
    -- profit_loss_rate: 盈亏率，类型REAL，必填，计算值=profit_loss/(quantity*cost_price)*100
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
    -- profit_loss: 盈亏，类型REAL，可选，仅卖出时有值
    transaction_date TEXT NOT NULL,
    -- transaction_date: 交易日期，类型TEXT，必填，格式YYYY-MM-DD
    created_date TEXT NOT NULL,
    -- created_date: 创建时间，类型TEXT，必填，格式YYYY-MM-DD HH:MM:SS
    FOREIGN KEY (account_id) REFERENCES trading_account(account_id) ON DELETE CASCADE
);

-- ============================================
-- 6. 行业信息表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_industry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    industry_code TEXT NOT NULL UNIQUE,
    -- industry_code: 行业代码，类型TEXT，必填，唯一，例如BK0001
    industry_name TEXT NOT NULL,
    -- industry_name: 行业名称，类型TEXT，必填，例如银行
    industry_level INTEGER,
    -- industry_level: 行业级别，类型INTEGER，可选，例如1
    parent_code TEXT,
    -- parent_code: 父级代码，类型TEXT，可选，用于多级行业分类
    stock_count INTEGER DEFAULT 0,
    -- stock_count: 行业内股票数量，类型INTEGER，默认0
    industry_change REAL,
    -- industry_change: 行业涨跌幅，类型REAL，可选，百分比，例如1.5
    rank_position INTEGER,
    -- rank_position: 排名位置，类型INTEGER，可选，例如1
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_date: 创建时间，类型DATETIME，默认当前时间
    updated_date DATETIME DEFAULT CURRENT_TIMESTAMP
    -- updated_date: 更新时间，类型DATETIME，默认当前时间
);



-- ============================================
-- 8. 板块信息表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_sector (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    sector_code TEXT NOT NULL UNIQUE,
    -- sector_code: 板块代码，类型TEXT，必填，唯一，例如BK0475
    sector_name TEXT NOT NULL,
    -- sector_name: 板块名称，类型TEXT，必填，例如银行
    sector_type TEXT,
    -- sector_type: 板块类型，类型TEXT，可选，例如行业、概念
    stock_count INTEGER DEFAULT 0,
    -- stock_count: 板块内股票数量，类型INTEGER，默认0
    sector_change REAL,
    -- sector_change: 板块涨跌幅，类型REAL，可选，百分比，例如1.5
    rank_position INTEGER,
    -- rank_position: 排名位置，类型INTEGER，可选，例如1
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_date: 创建时间，类型DATETIME，默认当前时间
    updated_date DATETIME DEFAULT CURRENT_TIMESTAMP
    -- updated_date: 更新时间，类型DATETIME，默认当前时间
);

-- ============================================
-- 9. 股票板块映射表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_sector_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    sector_code TEXT NOT NULL,
    -- sector_code: 板块代码，类型TEXT，必填，例如BK0475
    mapping_date DATE NOT NULL,
    -- mapping_date: 映射日期，类型DATE，必填，格式YYYY-MM-DD
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_date: 创建时间，类型DATETIME，默认当前时间
    UNIQUE(stock_code, sector_code, mapping_date),
    -- 股票代码、板块代码、映射日期的组合唯一
    FOREIGN KEY(sector_code) REFERENCES stock_sector(sector_code) ON DELETE CASCADE
);

-- ============================================
-- 2. 选股记录表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_selection_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    strategy_name VARCHAR(100) NOT NULL,
    -- strategy_name: 选股方案名称，类型VARCHAR(100)，必填，例如启明星策略+碗口反弹策略
    stock_code VARCHAR(20) NOT NULL,
    -- stock_code: 股票代码，类型VARCHAR(20)，必填，例如000001
    stock_name VARCHAR(50) NOT NULL,
    -- stock_name: 股票名称，类型VARCHAR(50)，必填，例如平安银行
    industry VARCHAR(50),
    -- industry: 所属行业，类型VARCHAR(50)，可选，例如银行
    sector VARCHAR(50),
    -- sector: 所属板块，类型VARCHAR(50)，可选，例如金融
    selection_date DATE NOT NULL,
    -- selection_date: 选入日期，类型DATE，必填，格式YYYY-MM-DD
    selection_time DATETIME NOT NULL,
    -- selection_time: 选入时间，类型DATETIME，必填，格式YYYY-MM-DD HH:MM:SS
    selection_price DECIMAL(10,2) NOT NULL,
    -- selection_price: 选入价格，类型DECIMAL(10,2)，必填，例如10.50
    score DECIMAL(5,2),
    -- score: 综合评分，类型DECIMAL(5,2)，可选，例如85.50
    rank_position INTEGER,
    -- rank_position: 排名位置，类型INTEGER，可选，例如1
    key_dates TEXT,
    -- key_dates: 关键日期信息，类型TEXT，可选，JSON格式
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- created_at: 创建时间，类型DATETIME，必填，默认当前时间
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- updated_at: 更新时间，类型DATETIME，必填，默认当前时间
    is_active INTEGER NOT NULL DEFAULT 1,
    -- is_active: 是否活跃，类型INTEGER，必填，默认1，1表示活跃，0表示已删除
    strategy_count INTEGER NOT NULL DEFAULT 1,
    -- strategy_count: 命中策略个数，类型INTEGER，必填，默认1
    UNIQUE(stock_code, selection_date)
    -- 股票代码和选入日期的组合唯一
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_strategy_name ON stock_selection_record(strategy_name);
CREATE INDEX IF NOT EXISTS idx_selection_date ON stock_selection_record(selection_date);
CREATE INDEX IF NOT EXISTS idx_is_active ON stock_selection_record(is_active);
CREATE INDEX IF NOT EXISTS idx_stock_code ON stock_selection_record(stock_code);
CREATE INDEX IF NOT EXISTS idx_score ON stock_selection_record(selection_date, score);
CREATE INDEX IF NOT EXISTS idx_rank_position ON stock_selection_record(selection_date, rank_position);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_date ON stock_selection_record(stock_code, selection_date);


-- ============================================
-- 10. 个股资金流向表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_fund_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    flow_date DATE NOT NULL,
    -- flow_date: 流向日期，类型DATE，必填，格式YYYY-MM-DD
    period TEXT,
    -- period: 时间周期，类型TEXT，可选，例如5d、10d、20d、60d、半年、全年
    main_net_flow REAL,
    -- main_net_flow: 主力净流入，类型REAL，可选，单位元，例如1000000
    super_large_net_flow REAL,
    -- super_large_net_flow: 超大单净流入，类型REAL，可选，单位元，例如500000
    large_net_flow REAL,
    -- large_net_flow: 大单净流入，类型REAL，可选，单位元，例如300000
    medium_net_flow REAL,
    -- medium_net_flow: 中单净流入，类型REAL，可选，单位元，例如100000
    small_net_flow REAL,
    -- small_net_flow: 小单净流入，类型REAL，可选，单位元，例如100000
    net_flow_rate REAL,
    -- net_flow_rate: 净流入率，类型REAL，可选，百分比，例如0.5
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_date: 创建时间，类型DATETIME，默认当前时间
    UNIQUE(stock_code, flow_date)
    -- 股票代码、流向日期的组合唯一，同一股票同一日期只有一条记录
);

-- ============================================
-- 11. 行业资金流向表
-- ============================================
CREATE TABLE IF NOT EXISTS industry_fund_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    industry_code TEXT NOT NULL,
    -- industry_code: 行业代码，类型TEXT，必填，例如BK0001
    industry_name TEXT,
    -- industry_name: 行业名称，类型TEXT，可选，例如银行
    flow_date DATE NOT NULL,
    -- flow_date: 流向日期，类型DATE，必填，格式YYYY-MM-DD
    period TEXT DEFAULT 'daily',
    -- period: 周期，类型TEXT，默认daily，可选值daily/weekly/monthly
    main_net_flow REAL,
    -- main_net_flow: 主力资金净流入，类型REAL，可选，单位亿元，例如1000
    super_large_net_flow REAL,
    -- super_large_net_flow: 超大单资金净流入，类型REAL，可选，单位亿元，例如500
    large_net_flow REAL,
    -- large_net_flow: 大单资金净流入，类型REAL，可选，单位亿元，例如300
    medium_net_flow REAL,
    -- medium_net_flow: 中单资金净流入，类型REAL，可选，单位亿元，例如100
    small_net_flow REAL,
    -- small_net_flow: 小单资金净流入，类型REAL，可选，单位亿元，例如100
    net_flow_rate REAL,
    -- net_flow_rate: 净流入率，类型REAL，可选，百分比，例如0.5
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_date: 创建时间，类型DATETIME，默认当前时间
    UNIQUE(industry_code, flow_date, period)
    -- 行业代码、流向日期、周期的组合唯一
);

-- ============================================
-- 12. 板块资金流向表
-- ============================================
CREATE TABLE IF NOT EXISTS sector_fund_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    sector_code TEXT NOT NULL,
    -- sector_code: 板块代码，类型TEXT，必填，例如BK0475
    sector_name TEXT,
    -- sector_name: 板块名称，类型TEXT，可选，例如银行
    flow_date DATE NOT NULL,
    -- flow_date: 流向日期，类型DATE，必填，格式YYYY-MM-DD
    period TEXT DEFAULT 'daily',
    -- period: 周期，类型TEXT，默认daily，可选值daily/weekly/monthly
    main_net_flow REAL,
    -- main_net_flow: 主力资金净流入，类型REAL，可选，单位亿元，例如1000
    super_large_net_flow REAL,
    -- super_large_net_flow: 超大单资金净流入，类型REAL，可选，单位亿元，例如500
    large_net_flow REAL,
    -- large_net_flow: 大单资金净流入，类型REAL，可选，单位亿元，例如300
    medium_net_flow REAL,
    -- medium_net_flow: 中单资金净流入，类型REAL，可选，单位亿元，例如100
    small_net_flow REAL,
    -- small_net_flow: 小单资金净流入，类型REAL，可选，单位亿元，例如100
    net_flow_rate REAL,
    -- net_flow_rate: 净流入率，类型REAL，可选，百分比，例如0.5
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_date: 创建时间，类型DATETIME，默认当前时间
    UNIQUE(sector_code, flow_date, period)
    -- 板块代码、流向日期、周期的组合唯一
);

-- ============================================
-- 13. 事件信息表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    event_type TEXT NOT NULL,
    -- event_type: 事件类型，类型TEXT，必填，例如announcement、lhb、margin_trading
    event_date DATE NOT NULL,
    -- event_date: 事件日期，类型DATE，必填，格式YYYY-MM-DD
    event_title TEXT NOT NULL,
    -- event_title: 事件标题，类型TEXT，必填，例如公告标题
    event_content TEXT,
    -- event_content: 事件内容，类型TEXT，可选，例如公告内容
    event_source TEXT,
    -- event_source: 事件来源，类型TEXT，可选，例如东方财富
    event_url TEXT,
    -- event_url: 事件URL，类型TEXT，可选，例如http://example.com
    importance INTEGER DEFAULT 1,
    -- importance: 重要程度，类型INTEGER，默认1，范围1-5
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP
    -- created_date: 创建时间，类型DATETIME，默认当前时间
);

-- ============================================
-- 14. 龙虎榜数据表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_lhb (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    lhb_date DATE NOT NULL,
    -- lhb_date: 上榜日期，类型DATE，必填，格式YYYY-MM-DD
    lhb_reason TEXT,
    -- lhb_reason: 上榜原因，类型TEXT，可选，例如涨幅偏离值达7%
    lhb_type TEXT,
    -- lhb_type: 上榜类型，类型TEXT，可选，例如买入、卖出
    rank_position INTEGER,
    -- rank_position: 排名位置，类型INTEGER，可选，例如1
    net_buy_amount REAL,
    -- net_buy_amount: 净买入金额，类型REAL，可选，单位元，例如1000000
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_date: 创建时间，类型DATETIME，默认当前时间
    UNIQUE(stock_code, lhb_date)
    -- 股票代码、上榜日期的组合唯一
);

-- ============================================
-- 15. 融资融券数据表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_margin_trading (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    trading_date DATE NOT NULL,
    -- trading_date: 交易日期，类型DATE，必填，格式YYYY-MM-DD
    margin_balance REAL,
    -- margin_balance: 融资余额，类型REAL，可选，单位元，例如1000000
    short_balance REAL,
    -- short_balance: 融券余额，类型REAL，可选，单位元，例如500000
    total_balance REAL,
    -- total_balance: 总余额，类型REAL，可选，单位元，例如1500000
    margin_change REAL,
    -- margin_change: 融资变化，类型REAL，可选，单位元，例如100000
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_date: 创建时间，类型DATETIME，默认当前时间
    UNIQUE(stock_code, trading_date)
    -- 股票代码、交易日期的组合唯一
);

-- ============================================
-- 16. 股票K线数据表（包含CSV文件）
-- ============================================
CREATE TABLE IF NOT EXISTS stock_kline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    code TEXT NOT NULL,
    -- code: 股票代码，类型TEXT，必填，例如000001
    date TEXT NOT NULL,
    -- date: 交易日期，类型TEXT，必填，格式YYYY-MM-DD
    open REAL,
    -- open: 开盘价，类型REAL，可选，例如10.50
    high REAL,
    -- high: 最高价，类型REAL，可选，例如10.60
    low REAL,
    -- low: 最低价，类型REAL，可选，例如10.40
    close REAL,
    -- close: 收盘价，类型REAL，可选，例如10.55
    volume INTEGER,
    -- volume: 成交量，类型INTEGER，可选，例如1000000
    market_cap REAL,
    -- market_cap: 市值，类型REAL，可选，单位亿元，例如100.5
    K REAL,
    -- K: KDJ指标K值，类型REAL，可选，范围0-100，例如70.5
    D REAL,
    -- D: KDJ指标D值，类型REAL，可选，范围0-100，例如68.3
    J REAL,
    -- J: KDJ指标J值，类型REAL，可选，范围0-100，例如74.9
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_date: 创建时间，类型DATETIME，默认当前时间
    updated_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- updated_date: 更新时间，类型DATETIME，默认当前时间
    UNIQUE(code, date)
    -- 股票代码、日期的组合唯一
);

-- ============================================
-- 17. 数据更新日志表
-- ============================================
CREATE TABLE IF NOT EXISTS update_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    update_date TEXT NOT NULL UNIQUE,
    -- update_date: 更新日期，类型TEXT，必填，唯一，格式YYYY-MM-DD
    update_time TEXT NOT NULL,
    -- update_time: 更新时间，类型TEXT，必填，格式YYYY-MM-DD HH:MM:SS
    new_stock_detected INTEGER DEFAULT 0,
    -- new_stock_detected: 检测到的新股数，类型INTEGER，默认0
    new_stock_initialized INTEGER DEFAULT 0,
    -- new_stock_initialized: 成功初始化的新股数，类型INTEGER，默认0
    kline_added INTEGER DEFAULT 0,
    -- kline_added: K线新增数，类型INTEGER，默认0
    kline_updated INTEGER DEFAULT 0,
    -- kline_updated: K线更新数，类型INTEGER，默认0
    fund_flow_added INTEGER DEFAULT 0,
    -- fund_flow_added: 资金流向新增数，类型INTEGER，默认0
    fund_flow_updated INTEGER DEFAULT 0,
    -- fund_flow_updated: 资金流向更新数，类型INTEGER，默认0
    status TEXT DEFAULT 'completed',
    -- status: 状态，类型TEXT，默认completed，可选值completed/failed/cancelled
    error_message TEXT,
    -- error_message: 错误信息，类型TEXT，可选
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    -- created_at: 创建时间，类型TIMESTAMP，默认当前时间
);

-- ============================================
-- 18. 个股评分结果表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_score (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    stock_name TEXT,
    -- stock_name: 股票名称，类型TEXT，可选，例如平安银行
    score_date TEXT NOT NULL,
    -- score_date: 评分日期，类型TEXT，必填，格式YYYY-MM-DD
    technical_score REAL,
    -- technical_score: 技术面得分，类型REAL，可选，范围0-100，基于策略权重加权计算
    moneyflow_score REAL,
    -- moneyflow_score: 资金面得分，类型REAL，可选，范围0-100，基于主力资金流向计算
    fundamental_score REAL,
    -- fundamental_score: 基本面得分，类型REAL，可选，范围0-100，基于财务指标计算
    sector_score REAL,
    -- sector_score: 板块热度得分，类型REAL，可选，范围0-100，基于板块涨幅和资金流向计算
    event_score REAL,
    -- event_score: 事件驱动得分，类型REAL，可选，范围0-100，基于事件类型和影响计算
    total_score REAL,
    -- total_score: 综合得分，类型REAL，可选，范围0-100，五维度加权求和
    score_level TEXT,
    -- score_level: 评分等级，类型TEXT，可选，可选值A+/A/B+/B/C/D，基于total_score区间设定
    veto_flag INTEGER DEFAULT 0,
    -- veto_flag: 一票否决标志，类型INTEGER，默认0，0=正常/1=被否决
    veto_reason TEXT,
    -- veto_reason: 否决原因，类型TEXT，可选，记录发现一票否决的具体条件
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_at: 创建时间，类型DATETIME，默认当前时间
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- updated_at: 更新时间，类型DATETIME，默认当前时间
    UNIQUE(stock_code, score_date)
    -- 股票代码、评分日期的组合唯一，同一股票同一日期只有一条评分记录
);

-- ============================================
-- 19. 个股评分详情表
-- ============================================
CREATE TABLE IF NOT EXISTS stock_score_detail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001，关联stock_score表
    score_date TEXT NOT NULL,
    -- score_date: 评分日期，类型TEXT，必填，格式YYYY-MM-DD，关联stock_score表
    technical_strategies TEXT,
    -- technical_strategies: 技术面策略详情，类型TEXT，可选，JSON格式，记录策略中的策略名称和权重
    moneyflow_details TEXT,
    -- moneyflow_details: 资金面详情，类型TEXT，可选，JSON格式，记录主力净流入、大单占比、北向资金等
    fundamental_details TEXT,
    -- fundamental_details: 基本面详情，类型TEXT，可选，JSON格式，记录净利润增长、ROE、经营现金流等
    sector_details TEXT,
    -- sector_details: 板块热度详情，类型TEXT，可选，JSON格式，记录板块涨幅排名和资金流向
    event_details TEXT,
    -- event_details: 事件驱动详情，类型TEXT，可选，JSON格式，记录正面和负面事件列表
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_at: 创建时间，类型DATETIME，默认当前时间
    FOREIGN KEY (stock_code, score_date)
        REFERENCES stock_score(stock_code, score_date)
);



-- ============================================
-- 创建索引以提高查询性能
-- ============================================
CREATE INDEX IF NOT EXISTS idx_stock_basic_code ON stock_basic(code);
CREATE INDEX IF NOT EXISTS idx_trading_position_account ON trading_position(account_id);
CREATE INDEX IF NOT EXISTS idx_trading_position_code ON trading_position(stock_code);
CREATE INDEX IF NOT EXISTS idx_trading_transaction_account ON trading_transaction(account_id);
CREATE INDEX IF NOT EXISTS idx_trading_transaction_code ON trading_transaction(stock_code);
CREATE INDEX IF NOT EXISTS idx_trading_transaction_date ON trading_transaction(transaction_date);
CREATE INDEX IF NOT EXISTS idx_stock_industry_code ON stock_industry(industry_code);
CREATE INDEX IF NOT EXISTS idx_stock_sector_code ON stock_sector(sector_code);
CREATE INDEX IF NOT EXISTS idx_stock_sector_mapping_code ON stock_sector_mapping(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_sector_mapping_date ON stock_sector_mapping(mapping_date);
CREATE INDEX IF NOT EXISTS idx_stock_fund_flow_code ON stock_fund_flow(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_fund_flow_date ON stock_fund_flow(flow_date);
CREATE INDEX IF NOT EXISTS idx_industry_fund_flow_code ON industry_fund_flow(industry_code);
CREATE INDEX IF NOT EXISTS idx_industry_fund_flow_date ON industry_fund_flow(flow_date);
CREATE INDEX IF NOT EXISTS idx_sector_fund_flow_code ON sector_fund_flow(sector_code);
CREATE INDEX IF NOT EXISTS idx_sector_fund_flow_date ON sector_fund_flow(flow_date);
CREATE INDEX IF NOT EXISTS idx_stock_event_code ON stock_event(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_event_date ON stock_event(event_date);
CREATE INDEX IF NOT EXISTS idx_stock_event_type ON stock_event(event_type);
CREATE INDEX IF NOT EXISTS idx_stock_lhb_code ON stock_lhb(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_lhb_date ON stock_lhb(lhb_date);
CREATE INDEX IF NOT EXISTS idx_stock_margin_code ON stock_margin_trading(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_margin_date ON stock_margin_trading(trading_date);
-- 为 stock_kline 表添加索引，加快查询性能（用于K线数据更新优化）
CREATE INDEX IF NOT EXISTS idx_stock_kline_code_date ON stock_kline(code, date);
-- 为 stock_score 表添加索引，加快评分查询性能（用于个股图谱功能）
CREATE INDEX IF NOT EXISTS idx_stock_score_code ON stock_score(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_score_date ON stock_score(score_date);
CREATE INDEX IF NOT EXISTS idx_stock_score_code_date ON stock_score(stock_code, score_date);
-- 为 stock_score_detail 表添加索引，加快评分详情查询性能（用于个股图谱功能）
CREATE INDEX IF NOT EXISTS idx_stock_score_detail_code ON stock_score_detail(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_score_detail_date ON stock_score_detail(score_date);

-- ============================================
-- 21. 回测配置表
-- ============================================
CREATE TABLE IF NOT EXISTS backtest_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 配置ID，自增主键
    config_name TEXT NOT NULL,
    -- config_name: 配置名称，类型TEXT，必填，例如默认回测配置
    score_threshold REAL DEFAULT 60,
    -- score_threshold: 评分阈值，类型REAL，默认60，范围0-100
    hold_period INTEGER DEFAULT 10,
    -- hold_period: 持有周期，类型INTEGER，默认10，单位交易日
    stop_loss REAL DEFAULT -7,
    -- stop_loss: 止损比例，类型REAL，默认-7，单位百分比
    take_profit REAL DEFAULT 21,
    -- take_profit: 止盈比例，类型REAL，默认21，单位百分比
    initial_capital REAL DEFAULT 300000,
    -- initial_capital: 初始资金，类型REAL，默认300000，单位元
    buy_amount REAL DEFAULT 100000,
    -- buy_amount: 每次买入金额，类型REAL，默认100000，单位元
    max_daily_buys INTEGER DEFAULT 8,
    -- max_daily_buys: 单日最大买入股票数量，类型INTEGER，默认8
    buy_point_lower REAL DEFAULT -1,
    -- buy_point_lower: 买点区间下限，类型REAL，默认-1，单位百分比（相对于支撑位置）
    buy_point_upper REAL DEFAULT 3,
    -- buy_point_upper: 买点区间上限，类型REAL，默认3，单位百分比（相对于支撑位置）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    -- created_at: 创建时间，类型TIMESTAMP，默认当前时间
);

-- ============================================
-- 22. 回测结果表
-- ============================================
CREATE TABLE IF NOT EXISTS backtest_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 结果ID，自增主键
    strategy_name TEXT NOT NULL,
    -- strategy_name: 策略名称，类型TEXT，必填，例如多方炮策略
    support_level_method TEXT NOT NULL,
    -- support_level_method: 支撑位置计算方法，类型TEXT，必填，默认ma20，可选值open/resistance/close_95/close/ma20
    backtest_name TEXT NOT NULL,
    -- backtest_name: 回测名称，类型TEXT，必填
    start_date TEXT NOT NULL,
    -- start_date: 回测开始日期，类型TEXT，必填，格式YYYY-MM-DD
    end_date TEXT NOT NULL,
    -- end_date: 回测结束日期，类型TEXT，必填，格式YYYY-MM-DD
    total_trades INTEGER DEFAULT 0,
    -- total_trades: 总交易次数，类型INTEGER，默认0
    win_trades INTEGER DEFAULT 0,
    -- win_trades: 盈利交易次数，类型INTEGER，默认0
    loss_trades INTEGER DEFAULT 0,
    -- loss_trades: 亏损交易次数，类型INTEGER，默认0
    win_rate REAL DEFAULT 0,
    -- win_rate: 胜率，类型REAL，默认0，单位百分比
    avg_return REAL DEFAULT 0,
    -- avg_return: 平均收益率，类型REAL，默认0，单位百分比
    total_return REAL DEFAULT 0,
    -- total_return: 总收益率，类型REAL，默认0，单位百分比
    max_return REAL DEFAULT 0,
    -- max_return: 最大单笔收益，类型REAL，默认0，单位百分比
    min_return REAL DEFAULT 0,
    -- min_return: 最小单笔收益，类型REAL，默认0，单位百分比
    profit_factor REAL DEFAULT 0,
    -- profit_factor: 盈利因子，类型REAL，默认0
    profit_loss_ratio REAL DEFAULT 0,
    -- profit_loss_ratio: 盈亏比，类型REAL，默认0
    max_drawdown REAL DEFAULT 0,
    -- max_drawdown: 最大回撤，类型REAL，默认0，单位百分比
    sharpe_ratio REAL DEFAULT 0,
    -- sharpe_ratio: 夏普比率，类型REAL，默认0
    initial_capital REAL DEFAULT 300000,
    -- initial_capital: 初始资金，类型REAL，默认300000，单位元
    final_capital REAL DEFAULT 0,
    -- final_capital: 最终资金，类型REAL，默认0，单位元
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    -- created_at: 创建时间，类型TIMESTAMP，默认当前时间
);

-- ============================================
-- 23. 回测交易记录表
-- ============================================
CREATE TABLE IF NOT EXISTS backtest_trade (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 交易ID，自增主键
    result_id INTEGER NOT NULL,
    -- result_id: 回测结果ID，类型INTEGER，必填，外键关联backtest_result
    stock_code TEXT NOT NULL,
    -- stock_code: 股票代码，类型TEXT，必填，例如000001
    stock_name TEXT NOT NULL,
    -- stock_name: 股票名称，类型TEXT，必填，例如平安银行
    selection_date TEXT NOT NULL,
    -- selection_date: 选入日期，类型TEXT，必填，格式YYYY-MM-DD
    buy_date TEXT NOT NULL,
    -- buy_date: 买入日期，类型TEXT，必填，格式YYYY-MM-DD
    buy_price REAL NOT NULL,
    -- buy_price: 买入价格，类型REAL，必填
    buy_amount REAL NOT NULL,
    -- buy_amount: 买入金额，类型REAL，必填
    quantity INTEGER NOT NULL,
    -- quantity: 买入数量，类型INTEGER，必填
    sell_date TEXT,
    -- sell_date: 卖出日期，类型TEXT，可选，格式YYYY-MM-DD
    sell_price REAL,
    -- sell_price: 卖出价格，类型REAL，可选
    sell_type TEXT,
    -- sell_type: 卖出类型，类型TEXT，可选，可选值take_profit/stop_loss/hold_expired
    return_rate REAL,
    -- return_rate: 收益率，类型REAL，可选，单位百分比
    profit_loss REAL,
    -- profit_loss: 盈亏金额，类型REAL，可选
    hold_days INTEGER,
    -- hold_days: 持有天数，类型INTEGER，可选
    support_level REAL,
    -- support_level: 支撑位置，类型REAL，可选
    trade_type TEXT DEFAULT 'normal',
    -- trade_type: 交易类型，类型TEXT，默认normal，可选值buy/add/sell/reduce
    buy_commission REAL DEFAULT 0,
    -- buy_commission: 买入佣金，类型REAL，默认0，单位元
    buy_transfer_fee REAL DEFAULT 0,
    -- buy_transfer_fee: 买入过户费，类型REAL，默认0，单位元（仅沪市）
    sell_commission REAL DEFAULT 0,
    -- sell_commission: 卖出佣金，类型REAL，默认0，单位元
    sell_transfer_fee REAL DEFAULT 0,
    -- sell_transfer_fee: 卖出过户费，类型REAL，默认0，单位元（仅沪市）
    sell_stamp_tax REAL DEFAULT 0,
    -- sell_stamp_tax: 卖出印花税，类型REAL，默认0，单位元
    total_cost REAL DEFAULT 0,
    -- total_cost: 总成本，类型REAL，默认0，单位元（佣金+过户费+印花税）
    net_profit REAL DEFAULT 0,
    -- net_profit: 扣成本后净盈亏，类型REAL，默认0，单位元
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_at: 创建时间，类型DATETIME，默认当前时间
    FOREIGN KEY (result_id) REFERENCES backtest_result(id) ON DELETE CASCADE
);

-- ============================================
-- 24. 回测收益曲线表
-- ============================================
CREATE TABLE IF NOT EXISTS backtest_equity_curve (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    result_id INTEGER NOT NULL,
    -- result_id: 回测结果ID，类型INTEGER，必填，外键关联backtest_result
    date TEXT NOT NULL,
    -- date: 日期，类型TEXT，必填，格式YYYY-MM-DD
    capital REAL NOT NULL,
    -- capital: 资金余额，类型REAL，必填，单位元
    return_rate REAL NOT NULL,
    -- return_rate: 收益率，类型REAL，必填，单位百分比
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- created_at: 创建时间，类型DATETIME，默认当前时间
    FOREIGN KEY (result_id) REFERENCES backtest_result(id) ON DELETE CASCADE
);

-- ============================================
-- 为回测表添加索引
-- ============================================
CREATE INDEX IF NOT EXISTS idx_backtest_result_dates ON backtest_result(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_backtest_trade_result ON backtest_trade(result_id);
CREATE INDEX IF NOT EXISTS idx_backtest_trade_code ON backtest_trade(stock_code);
CREATE INDEX IF NOT EXISTS idx_backtest_trade_dates ON backtest_trade(buy_date, sell_date);
CREATE INDEX IF NOT EXISTS idx_backtest_equity_curve_result ON backtest_equity_curve(result_id);
CREATE INDEX IF NOT EXISTS idx_backtest_equity_curve_date ON backtest_equity_curve(date);


-- ============================================
-- 25. 狩猎场结果表（KHunter）
-- ============================================
-- 说明：存储狩猎场计算结果，只记录符合买点条件的股票
CREATE TABLE IF NOT EXISTS khunter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 自增主键
    stock_code VARCHAR(20) NOT NULL,
    -- stock_code: 股票代码，类型VARCHAR(20)，必填，例如000001
    stock_name VARCHAR(50) NOT NULL,
    -- stock_name: 股票名称，类型VARCHAR(50)，必填，例如平安银行
    industry VARCHAR(50),
    -- industry: 所属行业，类型VARCHAR(50)，可选，例如银行
    sector VARCHAR(50),
    -- sector: 所属板块，类型VARCHAR(50)，可选，例如金融
    hunting_date DATE NOT NULL,
    -- hunting_date: 选入日期，类型DATE，必填，格式YYYY-MM-DD
    -- 说明：股票被系统选入股票池的日期（T+N日）
    strategy_name VARCHAR(100) NOT NULL,
    -- strategy_name: 策略名称，类型VARCHAR(100)，必填，例如多方炮策略
    support_level REAL NOT NULL,
    -- support_level: 支撑位价格，类型REAL，必填，精确到小数点后两位，例如10.50
    current_price REAL NOT NULL,
    -- current_price: 当前价格（选入日收盘价），类型REAL，必填，精确到小数点后两位，例如10.60
    price_diff REAL NOT NULL,
    -- price_diff: 价格差，类型REAL，必填，计算值=current_price-support_level，例如0.10
    price_diff_percent REAL NOT NULL,
    -- price_diff_percent: 价格差百分比，类型REAL，必填，计算值=(price_diff/support_level)*100，例如0.95
    buy_range VARCHAR(50),
    -- buy_range: 买入区间，类型VARCHAR(50)，可选，格式"10.39-10.60"，当前价格±1%
    score DECIMAL(5,2),
    -- score: 综合评分，类型DECIMAL(5,2)，可选，范围0-100，例如85.50
    score_date DATE,
    -- score_date: 评分对应的日期，类型DATE，可选，格式YYYY-MM-DD，用于调用评分API时传递正确的日期
    selection_record_id INTEGER,
    -- selection_record_id: 关联的选股记录ID，类型INTEGER，可选，外键关联stock_selection_record
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- created_at: 创建时间，类型DATETIME，必填，默认当前时间
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- updated_at: 更新时间，类型DATETIME，必填，默认当前时间
    timing_strategy VARCHAR(20) NOT NULL DEFAULT 'support',
    -- timing_strategy: 择时策略名称，类型VARCHAR(20)，必填，默认support，可选值support/turtle/rsi/bollinger
    timing_signal VARCHAR(200),
    -- timing_signal: 择时信号描述，类型VARCHAR(200)，可选，例如价格在支撑位区间
    UNIQUE(stock_code, hunting_date, strategy_name, timing_strategy)
    -- 股票代码、狩猎日期、策略名称、择时策略的组合唯一
);

-- 为 khunter 表创建索引
CREATE INDEX IF NOT EXISTS idx_khunter_code ON khunter(stock_code);
-- idx_khunter_code: 股票代码索引，用于快速查询特定股票的买点记录
CREATE INDEX IF NOT EXISTS idx_khunter_date ON khunter(hunting_date);
-- idx_khunter_date: 狩猎日期索引，用于快速查询特定日期的买点记录
CREATE INDEX IF NOT EXISTS idx_khunter_strategy ON khunter(strategy_name);
-- idx_khunter_strategy: 策略名称索引，用于快速查询特定策略的买点记录
CREATE INDEX IF NOT EXISTS idx_khunter_score ON khunter(hunting_date, score);
-- idx_khunter_score: 狩猎日期和评分的组合索引，用于按评分排序查询

-- ============================================
-- 26. 市场温度记录表
-- ============================================
-- 说明：存储每日市场温度计算结果，用于市场情绪监控和回测约束
CREATE TABLE IF NOT EXISTS market_temperature (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id: 主键ID，自增主键
    trade_date TEXT NOT NULL UNIQUE,
    -- trade_date: 交易日期，类型TEXT，必填，唯一，格式YYYYMMDD，例如20260421
    temperature REAL NOT NULL,
    -- temperature: 综合温度值，类型REAL，必填，范围0-100
    status TEXT NOT NULL,
    -- status: 市场状态，类型TEXT，必填，可选值活跃/正常/偏冷/寒冷/冰封/极端
    position_ratio REAL NOT NULL,
    -- position_ratio: 仓位系数，类型REAL，必填，范围0-1，例如0.8表示80%仓位
    action TEXT,
    -- action: 狩猎场执行规则，类型TEXT，可选，例如"只买入最高分的前3只"
    
    -- 各维度得分
    up_down_ratio_score REAL,
    -- up_down_ratio_score: 涨跌家数比得分，类型REAL，可选，范围0-100
    limit_down_score REAL,
    -- limit_down_score: 跌停家数得分，类型REAL，可选，范围0-100
    limit_up_performance_score REAL,
    -- limit_up_performance_score: 昨日涨停表现得分，类型REAL，可选，范围0-100
    volume_score REAL,
    -- volume_score: 成交额得分，类型REAL，可选，范围0-100
    
    -- 原始数据
    up_count INTEGER,
    -- up_count: 上涨家数，类型INTEGER，可选
    down_count INTEGER,
    -- down_count: 下跌家数，类型INTEGER，可选
    limit_down_count INTEGER,
    -- limit_down_count: 跌停家数，类型INTEGER，可选
    avg_limit_up_change REAL,
    -- avg_limit_up_change: 昨日涨停股今日平均涨幅，类型REAL，可选，单位百分比
    total_volume REAL,
    -- total_volume: 两市总成交额，类型REAL，可选，单位亿元
    volume_ma5_ratio REAL,
    -- volume_ma5_ratio: 成交额/5日均值，类型REAL，可选
    
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- created_at: 创建时间，类型TEXT，必填，默认当前时间，格式YYYY-MM-DD HH:MM:SS
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    -- updated_at: 更新时间，类型TEXT，必填，默认当前时间，格式YYYY-MM-DD HH:MM:SS
);

-- 为 market_temperature 表创建索引
CREATE INDEX IF NOT EXISTS idx_market_temp_date ON market_temperature(trade_date);
-- idx_market_temp_date: 交易日期索引，用于快速查询特定日期的温度数据
