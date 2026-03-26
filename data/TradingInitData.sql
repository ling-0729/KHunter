-- 模拟交易功能初始化数据

-- 清除所有测试数据
DELETE FROM trading_transaction;
DELETE FROM trading_position;
DELETE FROM trading_account;

-- 插入测试账户
-- 账户ID: test_account
-- 初始资金: 1,000,000 元
-- 创建日期: 2026-03-25
INSERT INTO trading_account (
    account_id,
    account_name,
    initial_cash,
    current_cash,
    total_assets,
    total_profit_loss,
    profit_loss_rate,
    created_date,
    updated_date,
    status
) VALUES (
    'test_account',
    '测试账户',
    1000000.0,
    1000000.0,
    1000000.0,
    0.0,
    0.0,
    '2026-03-25',
    '2026-03-25',
    'active'
);

-- 插入实际模拟交易账户
-- 账户ID: trading_account
-- 初始资金: 1,000,000 元
-- 创建日期: 2026-03-25
INSERT INTO trading_account (
    account_id,
    account_name,
    initial_cash,
    current_cash,
    total_assets,
    total_profit_loss,
    profit_loss_rate,
    created_date,
    updated_date,
    status
) VALUES (
    'trading_account',
    '实际模拟交易账户',
    1000000.0,
    1000000.0,
    1000000.0,
    0.0,
    0.0,
    '2026-03-25',
    '2026-03-25',
    'active'
);
