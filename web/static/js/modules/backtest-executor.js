/**
 * 批量回测执行管理模块
 * 负责任务的顺序执行、暂停、继续、取消等控制
 */

// ==================== 执行管理模块 ====================

/**
 * 回测执行管理器
 * 负责任务的执行控制和进度管理
 */
class BacktestExecutor {
  constructor(taskManager, uiManager, errorHandler = null) {
    // 依赖注入
    this.taskManager = taskManager;
    this.uiManager = uiManager;
    this.errorHandler = errorHandler;
    
    // 执行状态
    this.currentTaskId = null;
    this.isRunning = false;
    this.isPaused = false;
    this.isCancelled = false;
    
    // 时间统计
    this.executionStartTime = null;
    this.taskStartTime = null;
    
    // 执行统计
    this.completedTasks = 0;
    this.failedTasks = 0;
    this.totalTasks = 0;
    
    // 执行结果
    this.results = {};
    
    console.log('BacktestExecutor 初始化完成');
  }

  /**
   * 开始执行所有任务
   * 获取待执行任务列表，按顺序执行
   */
  async startExecution() {
    try {
      // 检查是否已在执行
      if (this.isRunning) {
        console.warn('已有执行任务在进行中，请先取消或等待完成');
        return;
      }

      // 获取待执行任务
      const tasks = this.taskManager.getTasks();
      if (tasks.length === 0) {
        console.warn('没有待执行的任务');
        this.uiManager.showError('没有待执行的任务');
        return;
      }

      // 初始化执行状态
      this.isRunning = true;
      this.isPaused = false;
      this.isCancelled = false;
      this.completedTasks = 0;
      this.failedTasks = 0;
      this.totalTasks = tasks.length;
      this.executionStartTime = new Date();
      this.results = {};

      console.log(`开始执行 ${this.totalTasks} 个任务`);

      // 显示执行进度
      this.uiManager.showProgress({
        strategyName: '准备中...',
        currentIndex: 0,
        totalCount: this.totalTasks,
        progress: 0,
        remainingTime: '计算中...'
      });

      // 顺序执行每个任务
      for (const task of tasks) {
        // 检查是否被取消
        if (this.isCancelled) {
          console.log('执行已被取消');
          break;
        }

        // 等待暂停恢复
        while (this.isPaused && !this.isCancelled) {
          await this.sleep(100);
        }

        // 如果在暂停期间被取消，则退出
        if (this.isCancelled) {
          break;
        }

        // 执行任务
        await this.executeTask(task.id);

        // 更新进度
        this.updateProgress();
      }

      // 执行完成
      this.isRunning = false;
      this.uiManager.hideProgress();

      // 显示完成信息
      const message = `执行完成！成功: ${this.completedTasks}, 失败: ${this.failedTasks}`;
      console.log(message);
      alert(message);

    } catch (error) {
      console.error('执行过程中出错:', error);
      this.isRunning = false;
      this.uiManager.showError(`执行出错: ${error.message}`);
    }
  }

  /**
   * 执行单个任务
   * 调用后端API执行回测，保存结果
   * @param {number} taskId - 任务ID
   */
  async executeTask(taskId) {
    try {
      // 获取任务信息
      const task = this.taskManager.getTask(taskId);
      if (!task) {
        console.error(`任务 ${taskId} 不存在`);
        this.failedTasks++;
        return;
      }

      // 更新任务状态为执行中
      this.currentTaskId = taskId;
      this.taskStartTime = new Date();
      this.taskManager.updateTaskStatus(taskId, 'running');

      console.log(`执行任务 ${taskId}: ${task.strategy_name}`);

      // 调用后端API执行回测
      const result = await this.callBacktestAPI(task);

      if (result && result.success) {
        // 任务成功
        this.onTaskCompleted(taskId, result.data);
      } else {
        // 任务失败
        const error = result ? result.error : '未知错误';
        this.onTaskFailed(taskId, error);
      }

    } catch (error) {
      console.error(`执行任务 ${taskId} 时出错:`, error);
      this.onTaskFailed(taskId, error.message);
    }
  }

  /**
   * 调用后端API执行回测
   * 支持重试机制和错误处理
   * @param {Object} task - 任务对象
   * @returns {Promise} API响应
   */
  async callBacktestAPI(task) {
    // 如果有错误处理器，使用带重试的执行方式
    if (this.errorHandler) {
      return await this.callBacktestAPIWithRetry(task);
    }

    // 否则使用基础的执行方式
    return await this.callBacktestAPIBasic(task);
  }

  /**
   * 基础的API调用（不带重试）
   * @param {Object} task - 任务对象
   * @returns {Promise} API响应
   */
  async callBacktestAPIBasic(task) {
    try {
      // 构建请求数据
      const requestData = {
        strategy_name: task.strategy_name,
        start_date: task.start_date,
        end_date: task.end_date,
        support_level_method: task.support_level_method
      };

      console.log('调用后端API:', requestData);

      // 发送请求
      const response = await fetch('/api/trading/backtest/run', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(requestData)
      });

      // 解析响应
      const data = await response.json();

      if (!response.ok) {
        return {
          success: false,
          error: data.error || `HTTP ${response.status}`
        };
      }

      return {
        success: true,
        data: data
      };

    } catch (error) {
      console.error('API调用失败:', error);
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * 带重试的API调用
   * 使用错误处理器的重试机制
   * @param {Object} task - 任务对象
   * @returns {Promise} API响应
   */
  async callBacktestAPIWithRetry(task) {
    try {
      // 构建请求数据
      const requestData = {
        strategy_name: task.strategy_name,
        start_date: task.start_date,
        end_date: task.end_date,
        support_level_method: task.support_level_method
      };

      console.log('调用后端API (带重试):', requestData);

      // 使用错误处理器的重试机制
      const data = await this.errorHandler.executeWithRetry(
        async () => {
          // 发送请求
          // 注意：回测任务可能需要 2-3 小时，不设置超时限制
          const response = await fetch('/api/trading/backtest/run', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestData)
            // 移除 30 秒超时限制，允许长时间连接
          });

          // 检查HTTP状态
          if (!response.ok) {
            const data = await response.json();
            const error = new Error(data.error || `HTTP ${response.status}`);
            error.statusCode = response.status;
            throw error;
          }

          // 解析响应
          return await response.json();
        },
        {
          taskId: task.id,
          strategyName: task.strategy_name
        }
      );

      return {
        success: true,
        data: data
      };

    } catch (error) {
      // 错误处理
      this.errorHandler.handleError(error, {
        taskId: task.id,
        strategyName: task.strategy_name,
        operation: 'callBacktestAPI'
      });

      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * 暂停执行
   * 设置暂停标志，当前任务完成后暂停
   */
  pauseExecution() {
    if (!this.isRunning) {
      console.warn('没有正在执行的任务');
      return;
    }

    this.isPaused = true;
    console.log('执行已暂停');
  }

  /**
   * 继续执行
   * 清除暂停标志，继续执行
   */
  resumeExecution() {
    if (!this.isRunning) {
      console.warn('没有正在执行的任务');
      return;
    }

    if (!this.isPaused) {
      console.warn('执行未暂停');
      return;
    }

    this.isPaused = false;
    console.log('执行已继续');
  }

  /**
   * 取消执行
   * 设置取消标志，停止执行后续任务
   */
  cancelExecution() {
    if (!this.isRunning) {
      console.warn('没有正在执行的任务');
      return;
    }

    this.isCancelled = true;
    this.isRunning = false;
    this.isPaused = false;
    console.log('执行已取消');
  }

  /**
   * 任务完成回调
   * 保存结果，创建结果页签
   * @param {number} taskId - 任务ID
   * @param {Object} result - 回测结果
   */
  onTaskCompleted(taskId, result) {
    try {
      // 获取任务信息
      const task = this.taskManager.getTask(taskId);
      if (!task) {
        console.error(`任务 ${taskId} 不存在`);
        return;
      }

      // 更新任务状态
      this.taskManager.updateTaskStatus(taskId, 'completed', result);

      // 保存结果
      this.results[taskId] = result;

      // 创建结果页签
      this.uiManager.addResultTab(task, result);

      // 更新统计
      this.completedTasks++;

      // 计算耗时
      const duration = (new Date() - this.taskStartTime) / 1000;
      console.log(`✓ 任务 ${taskId} 完成 (耗时: ${duration.toFixed(1)}秒)`);

    } catch (error) {
      console.error('处理任务完成时出错:', error);
    }
  }

  /**
   * 任务失败回调
   * 记录错误，更新任务状态
   * @param {number} taskId - 任务ID
   * @param {string} error - 错误信息
   */
  onTaskFailed(taskId, error) {
    try {
      // 获取任务信息
      const task = this.taskManager.getTask(taskId);
      if (!task) {
        console.error(`任务 ${taskId} 不存在`);
        return;
      }

      // 更新任务状态
      this.taskManager.updateTaskStatus(taskId, 'failed');

      // 更新统计
      this.failedTasks++;

      // 计算耗时
      const duration = (new Date() - this.taskStartTime) / 1000;
      console.error(`✗ 任务 ${taskId} 失败 (耗时: ${duration.toFixed(1)}秒)`);
      console.error(`  错误: ${error}`);

    } catch (err) {
      console.error('处理任务失败时出错:', err);
    }
  }

  /**
   * 更新执行进度
   * 计算进度百分比、剩余时间等
   */
  updateProgress() {
    try {
      // 计算进度
      const progress = (this.completedTasks + this.failedTasks) / this.totalTasks * 100;

      // 计算已用时间
      const elapsedSeconds = (new Date() - this.executionStartTime) / 1000;
      const elapsedMinutes = Math.floor(elapsedSeconds / 60);

      // 计算平均每个任务的耗时
      const completedCount = this.completedTasks + this.failedTasks;
      const avgTimePerTask = completedCount > 0 ? elapsedSeconds / completedCount : 0;

      // 计算剩余任务数和剩余时间
      const remainingCount = this.totalTasks - completedCount;
      const remainingSeconds = Math.ceil(avgTimePerTask * remainingCount);
      const remainingMinutes = Math.floor(remainingSeconds / 60);
      const remainingHours = Math.floor(remainingMinutes / 60);

      // 格式化剩余时间
      let remainingTimeStr = '计算中...';
      if (remainingHours > 0) {
        remainingTimeStr = `${remainingHours}小时${remainingMinutes % 60}分钟`;
      } else if (remainingMinutes > 0) {
        remainingTimeStr = `${remainingMinutes}分钟`;
      } else {
        remainingTimeStr = `${remainingSeconds}秒`;
      }

      // 获取当前任务信息
      const currentTask = this.taskManager.getTask(this.currentTaskId);
      const strategyName = currentTask ? currentTask.strategy_name : '未知';

      // 更新UI进度
      this.uiManager.showProgress({
        strategyName: strategyName,
        currentIndex: completedCount + 1,
        totalCount: this.totalTasks,
        progress: progress,
        remainingTime: remainingTimeStr
      });

    } catch (error) {
      console.error('更新进度时出错:', error);
    }
  }

  /**
   * 睡眠函数
   * 用于暂停执行
   * @param {number} ms - 毫秒数
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * 获取执行统计
   * @returns {Object} 统计信息
   */
  getStatistics() {
    return {
      isRunning: this.isRunning,
      isPaused: this.isPaused,
      isCancelled: this.isCancelled,
      completedTasks: this.completedTasks,
      failedTasks: this.failedTasks,
      totalTasks: this.totalTasks,
      successRate: this.totalTasks > 0 ? (this.completedTasks / this.totalTasks * 100).toFixed(2) : 0,
      elapsedTime: this.executionStartTime ? (new Date() - this.executionStartTime) / 1000 : 0
    };
  }
}

// ==================== 全局初始化 ====================

// 创建全局实例
let backtestExecutor = null;

/**
 * 初始化执行管理器
 * 创建BacktestExecutor实例，绑定事件处理
 * @param {BacktestTaskManager} taskManager - 任务管理器实例
 * @param {BacktestUIManager} uiManager - UI管理器实例
 * @param {BacktestErrorHandler} errorHandler - 错误处理器实例（可选）
 */
function initBacktestExecutor(taskManager, uiManager, errorHandler = null) {
  console.log('初始化执行管理器');
  
  // 检查依赖
  if (!taskManager || !uiManager) {
    console.error('依赖未初始化：taskManager 或 uiManager');
    return;
  }

  // 创建执行器实例
  backtestExecutor = new BacktestExecutor(taskManager, uiManager, errorHandler);

  // 绑定事件
  bindBacktestExecutorEvents();
  
  console.log('执行管理器初始化完成');
}

/**
 * 绑定事件处理
 */
function bindBacktestExecutorEvents() {
  // 开始执行按钮
  const startBtn = document.getElementById('start-execution-btn');
  if (startBtn) {
    startBtn.addEventListener('click', () => {
      backtestExecutor.startExecution();
    });
  }

  // 暂停按钮
  const pauseBtn = document.getElementById('pause-btn');
  if (pauseBtn) {
    pauseBtn.addEventListener('click', () => {
      backtestExecutor.pauseExecution();
      // 显示继续按钮，隐藏暂停按钮
      pauseBtn.style.display = 'none';
      const continueBtn = document.getElementById('continue-btn');
      if (continueBtn) {
        continueBtn.style.display = 'inline-block';
      }
    });
  }

  // 继续按钮
  const continueBtn = document.getElementById('continue-btn');
  if (continueBtn) {
    continueBtn.addEventListener('click', () => {
      backtestExecutor.resumeExecution();
      // 显示暂停按钮，隐藏继续按钮
      continueBtn.style.display = 'none';
      if (pauseBtn) {
        pauseBtn.style.display = 'inline-block';
      }
    });
  }

  // 取消按钮
  const cancelBtn = document.getElementById('cancel-btn');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      if (confirm('确定要取消执行吗？')) {
        backtestExecutor.cancelExecution();
      }
    });
  }
}

// 导出模块 - 支持ES6模块
export {
  BacktestExecutor,
  initBacktestExecutor
};
