/**
 * 重试策略模块
 * 
 * 提供API调用的自动重试机制，支持指数退避策略
 */

// ==================== 重试策略类 ====================

/**
 * 重试策略
 * 
 * 支持指数退避算法，自动计算重试延迟时间
 */
class RetryPolicy {
    /**
     * 构造函数
     * 
     * @param {number} maxRetries - 最大重试次数，默认3
     * @param {number} initialDelay - 初始延迟（秒），默认1
     * @param {number} maxDelay - 最大延迟（秒），默认10
     * @param {number} backoffFactor - 延迟增长因子，默认2
     */
    constructor(maxRetries = 3, initialDelay = 1, maxDelay = 10, backoffFactor = 2) {
        this.maxRetries = maxRetries;
        this.initialDelay = initialDelay;
        this.maxDelay = maxDelay;
        this.backoffFactor = backoffFactor;
    }

    /**
     * 计算延迟时间（秒）
     * 
     * 使用指数退避算法：delay = initialDelay * (backoffFactor ^ retryCount)
     * 
     * @param {number} retryCount - 当前重试次数（从0开始）
     * @returns {number} 延迟时间（秒）
     */
    getDelay(retryCount) {
        // 计算延迟时间
        const delay = this.initialDelay * Math.pow(this.backoffFactor, retryCount);
        
        // 限制最大延迟
        return Math.min(delay, this.maxDelay);
    }

    /**
     * 判断是否应该重试
     * 
     * @param {Error} error - 错误对象
     * @param {number} retryCount - 当前重试次数
     * @returns {boolean} 是否应该重试
     */
    shouldRetry(error, retryCount) {
        // 检查是否超过最大重试次数
        if (retryCount >= this.maxRetries) {
            return false;
        }

        // 检查错误是否可重试
        if (error.isRetryable === false) {
            return false;
        }

        return true;
    }

    /**
     * 获取重试信息
     * 
     * @param {number} retryCount - 当前重试次数
     * @returns {object} 重试信息
     */
    getRetryInfo(retryCount) {
        return {
            retryCount: retryCount,
            maxRetries: this.maxRetries,
            delay: this.getDelay(retryCount),
            canRetry: retryCount < this.maxRetries
        };
    }
}

// ==================== 重试执行器 ====================

/**
 * 重试执行器
 * 
 * 执行带重试机制的异步操作
 */
class RetryExecutor {
    /**
     * 构造函数
     * 
     * @param {RetryPolicy} retryPolicy - 重试策略
     */
    constructor(retryPolicy = null) {
        this.retryPolicy = retryPolicy || new RetryPolicy();
        this.retryCount = 0;
        this.lastError = null;
    }

    /**
     * 执行异步操作，支持重试
     * 
     * @param {Function} asyncFn - 异步函数
     * @param {object} options - 选项
     * @returns {Promise} 执行结果
     */
    async execute(asyncFn, options = {}) {
        const {
            onRetry = null,
            onSuccess = null,
            onError = null
        } = options;

        this.retryCount = 0;
        this.lastError = null;

        while (true) {
            try {
                // 执行异步操作
                const result = await asyncFn();

                // 调用成功回调
                if (onSuccess) {
                    onSuccess(result, this.retryCount);
                }

                return result;
            } catch (error) {
                // 保存错误
                this.lastError = error;

                // 判断是否应该重试
                if (this.retryPolicy.shouldRetry(error, this.retryCount)) {
                    // 获取延迟时间
                    const delay = this.retryPolicy.getDelay(this.retryCount);

                    // 调用重试回调
                    if (onRetry) {
                        onRetry(error, this.retryCount, delay);
                    }

                    // 等待延迟
                    await this.sleep(delay * 1000);

                    // 增加重试计数
                    this.retryCount++;
                } else {
                    // 调用错误回调
                    if (onError) {
                        onError(error, this.retryCount);
                    }

                    throw error;
                }
            }
        }
    }

    /**
     * 睡眠指定时间
     * 
     * @param {number} ms - 毫秒数
     * @returns {Promise} 延迟Promise
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * 获取重试统计信息
     * 
     * @returns {object} 统计信息
     */
    getStats() {
        return {
            retryCount: this.retryCount,
            lastError: this.lastError,
            totalDelay: this.calculateTotalDelay()
        };
    }

    /**
     * 计算总延迟时间
     * 
     * @returns {number} 总延迟时间（秒）
     */
    calculateTotalDelay() {
        let totalDelay = 0;
        for (let i = 0; i < this.retryCount; i++) {
            totalDelay += this.retryPolicy.getDelay(i);
        }
        return totalDelay;
    }
}

// ==================== 重试装饰器 ====================

/**
 * 创建带重试的异步函数装饰器
 * 
 * @param {RetryPolicy} retryPolicy - 重试策略
 * @returns {Function} 装饰器函数
 */
function withRetry(retryPolicy = null) {
    return function(target, propertyKey, descriptor) {
        const originalMethod = descriptor.value;
        const policy = retryPolicy || new RetryPolicy();

        descriptor.value = async function(...args) {
            const executor = new RetryExecutor(policy);

            return executor.execute(
                () => originalMethod.apply(this, args),
                {
                    onRetry: (error, retryCount, delay) => {
                        console.warn(
                            `[重试] 第 ${retryCount + 1} 次重试，延迟 ${delay}s`,
                            error
                        );
                    },
                    onError: (error, retryCount) => {
                        console.error(
                            `[失败] 已重试 ${retryCount} 次，最终失败`,
                            error
                        );
                    }
                }
            );
        };

        return descriptor;
    };
}

// ==================== 重试工具函数 ====================

/**
 * 执行带重试的异步操作
 * 
 * @param {Function} asyncFn - 异步函数
 * @param {RetryPolicy} retryPolicy - 重试策略
 * @param {object} options - 选项
 * @returns {Promise} 执行结果
 */
async function executeWithRetry(asyncFn, retryPolicy = null, options = {}) {
    const executor = new RetryExecutor(retryPolicy);
    return executor.execute(asyncFn, options);
}

/**
 * 创建重试策略预设
 */
const RetryPolicyPresets = {
    // 快速重试：最多3次，初始延迟1秒
    FAST: new RetryPolicy(3, 1, 10, 2),

    // 标准重试：最多5次，初始延迟2秒
    STANDARD: new RetryPolicy(5, 2, 30, 2),

    // 慢速重试：最多10次，初始延迟5秒
    SLOW: new RetryPolicy(10, 5, 60, 2),

    // 无重试：不重试
    NONE: new RetryPolicy(0, 0, 0, 1)
};

// ==================== 重试统计 ====================

/**
 * 重试统计收集器
 */
class RetryStatistics {
    constructor() {
        this.stats = [];
        this.maxStats = 1000;
    }

    /**
     * 记录重试统计
     * 
     * @param {string} operationName - 操作名称
     * @param {object} retryStats - 重试统计信息
     * @param {boolean} success - 是否成功
     */
    record(operationName, retryStats, success) {
        // 创建统计条目
        const entry = {
            timestamp: new Date().toISOString(),
            operationName: operationName,
            retryCount: retryStats.retryCount,
            totalDelay: retryStats.totalDelay,
            success: success,
            error: retryStats.lastError ? retryStats.lastError.message : null
        };

        // 添加到统计列表
        this.stats.push(entry);

        // 限制统计数量
        if (this.stats.length > this.maxStats) {
            this.stats.shift();
        }
    }

    /**
     * 获取所有统计
     * 
     * @returns {Array} 统计列表
     */
    getStats() {
        return [...this.stats];
    }

    /**
     * 获取统计摘要
     * 
     * @returns {object} 统计摘要
     */
    getSummary() {
        if (this.stats.length === 0) {
            return {
                totalOperations: 0,
                successCount: 0,
                failureCount: 0,
                successRate: 0,
                averageRetries: 0,
                averageDelay: 0
            };
        }

        // 计算统计数据
        const successCount = this.stats.filter(s => s.success).length;
        const failureCount = this.stats.length - successCount;
        const totalRetries = this.stats.reduce((sum, s) => sum + s.retryCount, 0);
        const totalDelay = this.stats.reduce((sum, s) => sum + s.totalDelay, 0);

        return {
            totalOperations: this.stats.length,
            successCount: successCount,
            failureCount: failureCount,
            successRate: (successCount / this.stats.length * 100).toFixed(2) + '%',
            averageRetries: (totalRetries / this.stats.length).toFixed(2),
            averageDelay: (totalDelay / this.stats.length).toFixed(2) + 's'
        };
    }

    /**
     * 清空统计
     */
    clear() {
        this.stats = [];
    }

    /**
     * 导出统计为JSON
     * 
     * @returns {string} JSON字符串
     */
    exportJSON() {
        return JSON.stringify(this.stats, null, 2);
    }
}

// 创建全局重试统计收集器
const retryStatistics = new RetryStatistics();

// ==================== 导出 ====================

// 导出重试策略类
window.RetryPolicy = RetryPolicy;
window.RetryExecutor = RetryExecutor;

// 导出重试装饰器
window.withRetry = withRetry;

// 导出重试工具函数
window.executeWithRetry = executeWithRetry;

// 导出重试策略预设
window.RetryPolicyPresets = RetryPolicyPresets;

// 导出重试统计
window.RetryStatistics = RetryStatistics;
window.retryStatistics = retryStatistics;
