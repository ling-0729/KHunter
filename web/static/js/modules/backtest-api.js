/**
 * 批量回测API和状态管理模块
 * 提供统一的API接口和状态管理
 */

/**
 * 批量回测API类
 * 提供统一的API接口，包括执行回测、获取结果、获取策略列表等
 */
class BacktestAPI {
  /**
   * 构造函数
   * @param {string} baseURL - API基础URL，默认为 '/api'
   * @param {RequestOptimizer} requestOptimizer - 请求优化器（可选）
   */
  constructor(baseURL = '/api', requestOptimizer = null) {
    // API基础URL
    this.baseURL = baseURL;
    
    // 请求优化器
    this.requestOptimizer = requestOptimizer;
    
    // 请求超时时间（毫秒）
    this.timeout = 30000;
  }

  /**
   * 执行回测
   * @param {Object} params - 回测参数
   * @returns {Promise} 回测结果
   */
  async runBacktest(params) {
    // 验证参数
    if (!params || typeof params !== 'object') {
      throw new Error('Invalid backtest parameters');
    }
    
    // 构建请求URL
    const url = `${this.baseURL}/trading/backtest/run`;
    
    // 如果有请求优化器，使用优化器发送请求
    if (this.requestOptimizer) {
      return this.requestOptimizer.fetchWithCache(url, {
        method: 'POST',
        body: JSON.stringify(params),
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }
    
    // 否则直接发送请求
    return this._fetch(url, {
      method: 'POST',
      body: JSON.stringify(params),
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }

  /**
   * 获取回测结果
   * @param {string|number} taskId - 任务ID
   * @returns {Promise} 回测结果
   */
  async getBacktestResult(taskId) {
    // 验证参数
    if (!taskId) {
      throw new Error('Invalid task ID');
    }
    
    // 构建请求URL
    const url = `${this.baseURL}/trading/backtest/result/${taskId}`;
    
    // 如果有请求优化器，使用优化器发送请求
    if (this.requestOptimizer) {
      return this.requestOptimizer.fetchWithCache(url);
    }
    
    // 否则直接发送请求
    return this._fetch(url);
  }

  /**
   * 获取策略列表
   * @returns {Promise} 策略列表
   */
  async getStrategies() {
    // 构建请求URL
    const url = `${this.baseURL}/trading/strategies`;
    
    // 如果有请求优化器，使用优化器发送请求
    if (this.requestOptimizer) {
      return this.requestOptimizer.fetchWithCache(url);
    }
    
    // 否则直接发送请求
    return this._fetch(url);
  }

  /**
   * 获取支撑位方法列表
   * @returns {Promise} 支撑位方法列表
   */
  async getSupportLevelMethods() {
    // 构建请求URL
    const url = `${this.baseURL}/trading/support-level-methods`;
    
    // 如果有请求优化器，使用优化器发送请求
    if (this.requestOptimizer) {
      return this.requestOptimizer.fetchWithCache(url);
    }
    
    // 否则直接发送请求
    return this._fetch(url);
  }

  /**
   * 获取回测历史
   * @param {Object} params - 查询参数
   * @returns {Promise} 回测历史
   */
  async getBacktestHistory(params = {}) {
    // 构建请求URL
    const url = `${this.baseURL}/trading/backtest/history`;
    
    // 构建查询字符串
    const queryString = new URLSearchParams(params).toString();
    const fullUrl = queryString ? `${url}?${queryString}` : url;
    
    // 如果有请求优化器，使用优化器发送请求
    if (this.requestOptimizer) {
      return this.requestOptimizer.fetchWithCache(fullUrl);
    }
    
    // 否则直接发送请求
    return this._fetch(fullUrl);
  }

  /**
   * 删除回测结果
   * @param {string|number} taskId - 任务ID
   * @returns {Promise} 删除结果
   */
  async deleteBacktestResult(taskId) {
    // 验证参数
    if (!taskId) {
      throw new Error('Invalid task ID');
    }
    
    // 构建请求URL
    const url = `${this.baseURL}/trading/backtest/result/${taskId}`;
    
    // 发送DELETE请求
    return this._fetch(url, {
      method: 'DELETE'
    });
  }

  /**
   * 内部HTTP请求方法
   * @param {string} url - 请求URL
   * @param {Object} options - 请求选项
   * @returns {Promise} 响应数据
   * @private
   */
  async _fetch(url, options = {}) {
    // 设置默认选项
    const fetchOptions = {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      },
      ...options
    };
    
    // 创建超时Promise
    const timeoutPromise = new Promise((_, reject) => {
      setTimeout(() => {
        reject(new Error('Request timeout'));
      }, this.timeout);
    });
    
    try {
      // 发送请求（带超时）
      const response = await Promise.race([
        fetch(url, fetchOptions),
        timeoutPromise
      ]);
      
      // 检查响应状态
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      // 解析响应数据
      const data = await response.json();
      
      // 返回响应数据
      return data;
    } catch (error) {
      // 记录错误
      console.error(`API request failed: ${url}`, error);
      
      // 抛出错误
      throw error;
    }
  }

  /**
   * 设置请求超时时间
   * @param {number} ms - 超时时间（毫秒）
   */
  setTimeout(ms) {
    if (typeof ms === 'number' && ms > 0) {
      this.timeout = ms;
    }
  }

  /**
   * 设置请求优化器
   * @param {RequestOptimizer} requestOptimizer - 请求优化器
   */
  setRequestOptimizer(requestOptimizer) {
    this.requestOptimizer = requestOptimizer;
  }
}

/**
 * 批量回测状态管理类
 * 提供统一的状态管理，包括任务列表、结果、执行状态等
 */
class BacktestState {
  /**
   * 构造函数
   */
  constructor() {
    // 初始状态
    this.state = {
      // 任务列表
      tasks: [],
      
      // 结果字典（taskId -> result）
      results: {},
      
      // 是否正在执行
      isRunning: false,
      
      // 当前执行的任务ID
      currentTaskId: null,
      
      // 执行进度（0-100）
      progress: 0,
      
      // 错误信息
      error: null,
      
      // 统计信息
      stats: {
        total: 0,
        completed: 0,
        failed: 0,
        pending: 0
      }
    };
    
    // 状态变化监听器列表
    this.listeners = [];
  }

  /**
   * 订阅状态变化
   * @param {Function} listener - 监听器函数
   * @returns {Function} 取消订阅函数
   */
  subscribe(listener) {
    // 验证监听器
    if (typeof listener !== 'function') {
      throw new Error('Listener must be a function');
    }
    
    // 添加监听器
    this.listeners.push(listener);
    
    // 返回取消订阅函数
    return () => {
      const index = this.listeners.indexOf(listener);
      if (index !== -1) {
        this.listeners.splice(index, 1);
      }
    };
  }

  /**
   * 更新状态
   * @param {Object} newState - 新状态
   */
  setState(newState) {
    // 验证新状态
    if (typeof newState !== 'object' || newState === null) {
      return;
    }
    
    // 合并状态
    this.state = Object.assign({}, this.state, newState);
    
    // 通知所有监听器
    this.listeners.forEach(listener => {
      try {
        listener(this.state);
      } catch (error) {
        console.error('Error in state listener:', error);
      }
    });
  }

  /**
   * 获取状态
   * @returns {Object} 当前状态
   */
  getState() {
    // 返回状态的深拷贝
    return JSON.parse(JSON.stringify(this.state));
  }

  /**
   * 获取特定属性
   * @param {string} key - 属性键
   * @returns {*} 属性值
   */
  get(key) {
    return this.state[key];
  }

  /**
   * 添加任务
   * @param {Object} task - 任务对象
   */
  addTask(task) {
    // 验证任务
    if (!task || typeof task !== 'object') {
      throw new Error('Invalid task');
    }
    
    // 添加任务
    const tasks = [...this.state.tasks, task];
    
    // 更新统计信息
    const stats = this._calculateStats(tasks);
    
    // 更新状态
    this.setState({
      tasks,
      stats
    });
  }

  /**
   * 移除任务
   * @param {string|number} taskId - 任务ID
   */
  removeTask(taskId) {
    // 过滤任务
    const tasks = this.state.tasks.filter(t => t.id !== taskId);
    
    // 更新统计信息
    const stats = this._calculateStats(tasks);
    
    // 更新状态
    this.setState({
      tasks,
      stats
    });
  }

  /**
   * 更新任务
   * @param {string|number} taskId - 任务ID
   * @param {Object} updates - 更新内容
   */
  updateTask(taskId, updates) {
    // 查找任务
    const taskIndex = this.state.tasks.findIndex(t => t.id === taskId);
    if (taskIndex === -1) {
      return;
    }
    
    // 更新任务
    const tasks = [...this.state.tasks];
    tasks[taskIndex] = Object.assign({}, tasks[taskIndex], updates);
    
    // 更新统计信息
    const stats = this._calculateStats(tasks);
    
    // 更新状态
    this.setState({
      tasks,
      stats
    });
  }

  /**
   * 添加结果
   * @param {string|number} taskId - 任务ID
   * @param {Object} result - 结果对象
   */
  addResult(taskId, result) {
    // 验证参数
    if (!taskId || !result) {
      return;
    }
    
    // 添加结果
    const results = Object.assign({}, this.state.results, {
      [taskId]: result
    });
    
    // 更新状态
    this.setState({ results });
  }

  /**
   * 获取结果
   * @param {string|number} taskId - 任务ID
   * @returns {Object} 结果对象
   */
  getResult(taskId) {
    return this.state.results[taskId] || null;
  }

  /**
   * 清空所有状态
   */
  clear() {
    this.setState({
      tasks: [],
      results: {},
      isRunning: false,
      currentTaskId: null,
      progress: 0,
      error: null,
      stats: {
        total: 0,
        completed: 0,
        failed: 0,
        pending: 0
      }
    });
  }

  /**
   * 计算统计信息
   * @param {Array} tasks - 任务列表
   * @returns {Object} 统计信息
   * @private
   */
  _calculateStats(tasks) {
    // 初始化统计
    const stats = {
      total: tasks.length,
      completed: 0,
      failed: 0,
      pending: 0
    };
    
    // 统计各状态的任务数
    tasks.forEach(task => {
      if (task.status === 'completed') {
        stats.completed++;
      } else if (task.status === 'failed') {
        stats.failed++;
      } else if (task.status === 'pending') {
        stats.pending++;
      }
    });
    
    return stats;
  }
}

// 导出类
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    BacktestAPI,
    BacktestState
  };
}
