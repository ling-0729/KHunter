/**
 * 批量回测错误处理模块
 * 处理网络错误、超时、重试和日志记录
 */

/**
 * 错误日志记录器
 */
class ErrorLogger {
  constructor() {
    // 错误日志列表
    this.logs = [];
    // 最大日志数量
    this.maxLogs = 100;
    // 从本地存储加载日志
    this.loadFromLocalStorage();
  }

  /**
   * 记录错误
   * @param {Error} error - 错误对象
   * @param {Object} context - 错误上下文
   */
  log(error, context = {}) {
    // 创建日志条目
    const logEntry = {
      timestamp: new Date().toISOString(),
      type: error.name || 'Error',
      message: error.message,
      stack: error.stack,
      context: context,
      retries: context.retries || 0
    };

    // 添加到日志列表
    this.logs.push(logEntry);

    // 限制日志数量
    if (this.logs.length > this.maxLogs) {
      this.logs.shift();
    }

    // 保存到本地存储
    this.saveToLocalStorage();

    // 输出到控制台
    console.error('[错误日志]', logEntry);
  }

  /**
   * 保存日志到本地存储
   */
  saveToLocalStorage() {
    try {
      // 检查localStorage是否可用（浏览器环境）
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('backtest_error_logs', JSON.stringify(this.logs));
      }
    } catch (e) {
      console.warn('无法保存错误日志到本地存储:', e);
    }
  }

  /**
   * 从本地存储加载日志
   */
  loadFromLocalStorage() {
    try {
      // 检查localStorage是否可用（浏览器环境）
      if (typeof localStorage !== 'undefined') {
        const stored = localStorage.getItem('backtest_error_logs');
        if (stored) {
          this.logs = JSON.parse(stored);
        }
      }
    } catch (e) {
      console.warn('无法从本地存储加载错误日志:', e);
    }
  }

  /**
   * 获取所有日志
   */
  getLogs() {
    return [...this.logs];
  }

  /**
   * 清空日志
   */
  clearLogs() {
    this.logs = [];
    try {
      // 检查localStorage是否可用（浏览器环境）
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem('backtest_error_logs');
      }
    } catch (e) {
      console.warn('无法清空本地存储的错误日志:', e);
    }
  }

  /**
   * 获取最近的N条日志
   */
  getRecentLogs(count = 10) {
    return this.logs.slice(-count);
  }
}

/**
 * 错误处理器
 */
class BacktestErrorHandler {
  constructor(uiManager) {
    this.uiManager = uiManager;
    this.logger = new ErrorLogger();
    // 重试配置
    this.retryConfig = {
      maxRetries: 3,
      initialDelay: 1000, // 1秒
      maxDelay: 8000 // 8秒
    };
  }

  /**
   * 检查是否是可重试的错误
   * @param {Error} error - 错误对象
   * @returns {boolean}
   */
  isRetryableError(error) {
    const message = error.message.toLowerCase();
    return message.includes('网络') ||
           message.includes('超时') ||
           message.includes('连接') ||
           message.includes('econnrefused') ||
           message.includes('enotfound') ||
           message.includes('timeout');
  }

  /**
   * 获取用户友好的错误信息
   * @param {Error} error - 错误对象
   * @returns {string}
   */
  getUserFriendlyMessage(error) {
    const message = error.message.toLowerCase();

    if (message.includes('网络') || message.includes('econnrefused') || message.includes('enotfound')) {
      return '网络连接失败，请检查网络连接';
    } else if (message.includes('超时') || message.includes('timeout')) {
      return '操作超时，请重试';
    } else if (message.includes('500') || message.includes('服务器')) {
      return '服务器错误，请稍后重试';
    } else if (message.includes('404')) {
      return '请求的资源不存在';
    } else if (message.includes('401') || message.includes('403')) {
      return '权限不足，请检查权限';
    } else if (message.includes('400')) {
      return '请求参数错误';
    } else {
      return error.message || '发生未知错误';
    }
  }

  /**
   * 计算重试延迟时间（指数退避）
   * @param {number} retryCount - 重试次数
   * @returns {number} 延迟时间（毫秒）
   */
  calculateDelay(retryCount) {
    const delay = Math.pow(2, retryCount) * this.retryConfig.initialDelay;
    return Math.min(delay, this.retryConfig.maxDelay);
  }

  /**
   * 带重试的异步操作
   * @param {Function} fn - 异步函数
   * @param {Object} context - 上下文信息
   * @returns {Promise}
   */
  async executeWithRetry(fn, context = {}) {
    let lastError;

    for (let i = 0; i < this.retryConfig.maxRetries; i++) {
      try {
        return await fn();
      } catch (error) {
        lastError = error;

        // 记录错误
        this.logger.log(error, {
          ...context,
          retries: i + 1,
          isRetryable: this.isRetryableError(error)
        });

        // 检查是否应该重试
        if (!this.isRetryableError(error) || i === this.retryConfig.maxRetries - 1) {
          throw error;
        }

        // 计算延迟时间
        const delay = this.calculateDelay(i);

        // 显示重试提示
        if (this.uiManager && this.uiManager.showInfo) {
          this.uiManager.showInfo(`操作失败，${delay / 1000}秒后重试...`);
        }

        // 等待后重试
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    }

    throw lastError;
  }

  /**
   * 处理错误
   * @param {Error} error - 错误对象
   * @param {Object} context - 错误上下文
   */
  handleError(error, context = {}) {
    // 记录错误
    this.logger.log(error, context);

    // 获取用户友好的错误信息
    const userMessage = this.getUserFriendlyMessage(error);

    // 显示错误信息
    if (this.uiManager && this.uiManager.showError) {
      this.uiManager.showError(userMessage);
    } else {
      alert(`错误: ${userMessage}`);
    }

    // 输出到控制台
    console.error('[错误处理]', {
      error: error,
      userMessage: userMessage,
      context: context
    });
  }

  /**
   * 获取错误日志
   */
  getLogs() {
    return this.logger.getLogs();
  }

  /**
   * 清空错误日志
   */
  clearLogs() {
    this.logger.clearLogs();
  }
}

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { ErrorLogger, BacktestErrorHandler };
}
