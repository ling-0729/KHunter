-- SQLite 数据库性能优化脚本
-- 用于提升数据更新和查询性能

-- ========================================
-- 1. 添加关键索引
-- ========================================

-- K线数据表索引（用于快速查询和去重）
CREATE INDEX IF NOT EXISTS idx_kline_code_date ON stock_kline(code, date);
CREATE INDEX IF NOT EXISTS idx_kline_date ON stock_kline(date);

-- 股票基本信息表索引
CREATE INDEX IF NOT EXISTS idx_stock_code ON stock_basic(code);
CREATE INDEX IF NOT EXISTS idx_stock_name ON stock_basic(name);

-- 选股记录表索引
CREATE INDEX IF NOT EXISTS idx_selection_code_date ON stock_selection_record(stock_code, selection_date);
CREATE INDEX IF NOT EXISTS idx_selection_date ON stock_selection_record(selection_date);

-- 更新日志表索引
CREATE INDEX IF NOT EXISTS idx_update_log_date ON update_log(update_date);

-- ========================================
-- 2. SQLite 性能优化参数
-- ========================================

-- 使用 WAL (Write-Ahead Logging) 模式
-- 优点：提升并发性能，减少锁等待
PRAGMA journal_mode = WAL;

-- 设置同步模式为 NORMAL
-- 优点：平衡性能和数据安全性
PRAGMA synchronous = NORMAL;

-- 增大缓存大小到 64MB
-- 优点：减少磁盘I/O，提升查询速度
PRAGMA cache_size = -64000;

-- 临时表存储在内存中
-- 优点：加快临时数据处理速度
PRAGMA temp_store = MEMORY;

-- 启用自动清理
-- 优点：定期压缩数据库文件，保持性能
PRAGMA auto_vacuum = INCREMENTAL;

-- 设置页面大小为 4KB（默认值，但显式设置）
-- 注意：只能在创建数据库时设置
-- PRAGMA page_size = 4096;

-- ========================================
-- 3. 分析表统计信息
-- ========================================

-- 更新表统计信息，帮助查询优化器选择更好的执行计划
ANALYZE stock_kline;
ANALYZE stock_basic;
ANALYZE stock_selection_record;
ANALYZE update_log;

-- ========================================
-- 4. 清理和优化
-- ========================================

-- 清理未使用的空间
VACUUM;

-- ========================================
-- 验证优化结果
-- ========================================

-- 查看当前配置
SELECT 'journal_mode' as setting, journal_mode as value FROM pragma_journal_mode
UNION ALL
SELECT 'synchronous', synchronous FROM pragma_synchronous
UNION ALL
SELECT 'cache_size', cache_size FROM pragma_cache_size
UNION ALL
SELECT 'temp_store', temp_store FROM pragma_temp_store
UNION ALL
SELECT 'page_size', page_size FROM pragma_page_size;

-- 查看索引列表
SELECT 
    name as index_name,
    tbl_name as table_name,
    sql
FROM sqlite_master
WHERE type = 'index'
AND name LIKE 'idx_%'
ORDER BY tbl_name, name;