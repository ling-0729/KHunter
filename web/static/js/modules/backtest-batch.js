/**
 * 批量回测任务执行模块
 * 支持多次添加回测任务，按顺序执行，显示多个结果页签
 */

// ==================== 任务管理模块 ====================

/**
 * 回测任务管理器
 * 负责任务的增删改查和统计
 */
class BacktestTaskManager {
  constructor() {
    // 任务列表，每个任务有唯一ID
    this.tasks = [];
    // 任务ID计数器
    this.taskIdCounter = 0;
  }

  /**
   * 添加任务到队列
   * @param {Object} config - 任务配置
   * @returns {Object} 创建的任务对象
   */
  addTask(config) {
    // 验证配置
    if (!config.strategy_name || !config.start_date || !config.end_date) {
      throw new Error('任务配置不完整');
    }

    // 创建任务对象
    const task = {
      id: ++this.taskIdCounter,
      strategy_name: config.strategy_name,  // 中文名称
      start_date: config.start_date,
      end_date: config.end_date,
      timing_strategy: config.timing_strategy || 'turtle',
      support_level_method: config.support_level_method || 'ma20',
      status: 'pending', // pending, running, completed, failed
      result: null,
      createdAt: new Date()
    };

    // 添加到任务列表
    this.tasks.push(task);
    console.log(`任务 ${task.id} 已添加: ${task.strategy_name}`);
    return task;
  }

  /**
   * 删除任务
   * @param {number} taskId - 任务ID
   * @returns {boolean} 是否删除成功
   */
  removeTask(taskId) {
    const index = this.tasks.findIndex(t => t.id === taskId);
    if (index !== -1) {
      const task = this.tasks[index];
      this.tasks.splice(index, 1);
      console.log(`任务 ${taskId} 已删除: ${task.strategy_name}`);
      return true;
    }
    return false;
  }

  /**
   * 获取所有任务
   * @returns {Array} 任务列表
   */
  getTasks() {
    return [...this.tasks];
  }

  /**
   * 获取指定ID的任务
   * @param {number} taskId - 任务ID
   * @returns {Object|null} 任务对象或null
   */
  getTask(taskId) {
    return this.tasks.find(t => t.id === taskId) || null;
  }

  /**
   * 清空所有任务
   */
  clearTasks() {
    this.tasks = [];
    this.taskIdCounter = 0;
    console.log('所有任务已清空');
  }

  /**
   * 获取任务总数
   * @returns {number} 任务数量
   */
  getTaskCount() {
    return this.tasks.length;
  }

  /**
   * 获取待执行任务数
   * @returns {number} 待执行任务数
   */
  getPendingTaskCount() {
    return this.tasks.filter(t => t.status === 'pending').length;
  }

  /**
   * 获取已完成任务数
   * @returns {number} 已完成任务数
   */
  getCompletedTaskCount() {
    return this.tasks.filter(t => t.status === 'completed').length;
  }

  /**
   * 计算预计耗时
   * 执行前无法准确预估，启动后由轮询逻辑按实际进度预估（批次3）
   * @returns {string} 预计耗时字符串
   */
  estimateTime() {
    const count = this.getTaskCount();
    if (count === 0) return '0个任务';
    // 执行前不再硬编码时长，启动后按实际进度预估
    return `${count}个任务，启动后预估`;
  }

  /**
   * 更新任务状态
   * @param {number} taskId - 任务ID
   * @param {string} status - 新状态
   * @param {Object} result - 任务结果（可选）
   */
  updateTaskStatus(taskId, status, result = null) {
    const task = this.getTask(taskId);
    if (task) {
      task.status = status;
      if (result) {
        task.result = result;
      }
      console.log(`任务 ${taskId} 状态已更新: ${status}`);
    }
  }
}

// ==================== UI管理模块 ====================

/**
 * 回测UI管理器
 * 负责页面UI的更新和显示
 */
class BacktestUIManager {
  constructor() {
    // 缓存DOM元素
    this.elements = {
      // 配置表单
      strategySelect: document.getElementById('strategy-select'),
      timingStrategy: document.getElementById('backtest-timing-strategy'),
      startDate: document.getElementById('start-date'),
      endDate: document.getElementById('end-date'),
      addTaskBtn: document.getElementById('add-task-btn'),
      
      // 任务列表
      taskListContainer: document.getElementById('backtest-task-list'),
      taskTable: document.getElementById('backtest-task-table'),
      taskBody: document.getElementById('backtest-task-body'),
      taskCount: document.getElementById('task-count'),
      estimatedTime: document.getElementById('estimated-time'),
      startExecutionBtn: document.getElementById('start-execution-btn'),
      
      // 执行进度
      progressContainer: document.getElementById('backtest-progress-container'),
      currentTaskInfo: document.getElementById('current-task-info'),
      progressFill: document.getElementById('progress-fill'),
      progressPercent: document.getElementById('progress-percent'),
      remainingTime: document.getElementById('remaining-time'),
      pauseBtn: document.getElementById('pause-btn'),
      continueBtn: document.getElementById('continue-btn'),
      cancelBtn: document.getElementById('cancel-btn'),
      
      // 结果页签
      resultTabs: document.getElementById('backtest-result-tabs'),
      resultTabsContainer: document.getElementById('result-tabs-container'),
      resultContent: document.getElementById('backtest-result-content')
    };
  }

  /**
   * 更新任务列表显示
   * @param {Array} tasks - 任务列表
   */
  updateTaskList(tasks) {
    // 清空表格
    this.elements.taskBody.innerHTML = '';

    if (tasks.length === 0) {
      // 隐藏任务列表容器
      this.elements.taskListContainer.style.display = 'none';
      return;
    }

    // 显示任务列表容器
    this.elements.taskListContainer.style.display = 'block';

    // 择时策略映射
    const timingStrategyMap = {
      'turtle': '海龟策略',
      'low_turtle': '低位海龟策略',
      'turtle_plus': '海龟plus',
      'rsi': 'RSI策略',
      'bollinger': '布林带策略',
      'support': '支撑位策略',
      'macd_bollinger': '顺势宝',
      'uptrend_pullback': '趋势回调缩量策略'
    };

    // 添加任务行
    tasks.forEach((task, index) => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${index + 1}</td>
        <td>${task.strategy_name}</td>
        <td>${timingStrategyMap[task.timing_strategy] || task.timing_strategy}</td>
        <td>${task.start_date}</td>
        <td>${task.end_date}</td>
        <td>
          <button class="btn btn-sm btn-danger" onclick="window.removeBacktestTask(${task.id})" style="padding:4px 8px; font-size:11px;">删除</button>
        </td>
      `;
      this.elements.taskBody.appendChild(row);
    });
  }

  /**
   * 更新任务统计信息
   * @param {number} count - 任务总数
   * @param {string} estimatedTime - 预计耗时
   */
  updateTaskStats(count, estimatedTime) {
    this.elements.taskCount.textContent = count;
    this.elements.estimatedTime.textContent = estimatedTime;
    
    // 根据任务数量启用/禁用执行按钮
    this.elements.startExecutionBtn.disabled = count === 0;
  }

  /**
   * 显示执行进度
   * @param {Object} info - 进度信息
   */
  showProgress(info) {
    this.elements.progressContainer.style.display = 'block';
    // 优先使用调用方传入的完整任务行（含交易日进度），否则回退到简单拼接
    if (info.currentTaskLine) {
      this.elements.currentTaskInfo.textContent = info.currentTaskLine;
    } else {
      this.elements.currentTaskInfo.textContent = `正在执行: ${info.strategyName} (${info.currentIndex}/${info.totalCount})`;
    }
    this.updateProgressBar(info.progress);
    this.elements.remainingTime.textContent = info.remainingTime;
  }

  /**
   * 隐藏执行进度
   */
  hideProgress() {
    this.elements.progressContainer.style.display = 'none';
  }

  /**
   * 更新进度条
   * @param {number} progress - 进度百分比 (0-100)
   */
  updateProgressBar(progress) {
    this.elements.progressFill.style.width = progress + '%';
    this.elements.progressPercent.textContent = Math.round(progress) + '%';
  }

  /**
   * 添加结果页签
   * @param {Object} task - 任务对象
   * @param {Object} result - 回测结果
   */
  addResultTab(task, result) {
    // 择时策略中文名称映射
    const timingStrategyNames = {
      'turtle': '海龟策略',
      'low_turtle': '低位海龟策略',
      'turtle_plus': '海龟plus',
      'rsi': 'RSI策略',
      'bollinger': '布林带策略',
      'support': '支撑位策略',
      'macd_bollinger': '顺势宝',
      'uptrend_pullback': '趋势回调缩量策略'
    };

    // 获取择时策略名称（优先从结果中获取，其次从任务中获取）
    let timingStrategy = null;
    if (result.timing_strategy) {
      if (typeof result.timing_strategy === 'object') {
        timingStrategy = result.timing_strategy.name;
      } else {
        timingStrategy = result.timing_strategy;
      }
    }
    if (!timingStrategy && task.timing_strategy) {
      timingStrategy = task.timing_strategy;
    }
    if (!timingStrategy) {
      timingStrategy = 'turtle';
    }
    
    // 获取择时策略显示名称
    const timingStrategyDisplay = timingStrategyNames[timingStrategy] || timingStrategy;
    
    // 检查是否已经存在相同的页签（根据任务ID或策略名称+择时策略+日期范围）
    const existingTabs = this.elements.resultTabsContainer.querySelectorAll('.result-tab');
    
    // 首先检查是否有相同任务ID的结果内容
    const existingContent = document.getElementById(`result-${task.id}`);
    if (existingContent) {
      console.warn(`已经存在任务ID ${task.id} 的结果页签，跳过添加`);
      return;
    }
    
    // 然后检查是否有相同策略名称+择时策略+日期范围的页签
    const strategyName = result.strategy_name || task.strategy_name;
    const dateRange = task.start_date && task.end_date ? `${task.start_date}~${task.end_date}` : '';
    // 【2026-09-21】唯一键纳入 task.id ✓
    //   背景：批量任务常是"同一策略 + 同一择时，仅区间不同" ✓，而后端 task_results
    //   **不回传** start_date/end_date ✗ → dateRange 为空 ✗ → 4 个结果的 uniqueKey
    //   完全相同 ✗ → 后 3 个被判"重复"直接跳过 ✗（本次现象：完成 4 个只显示 1 个 ✓）
    const uniqueKey = `${strategyName}-${timingStrategyDisplay}-${dateRange}-#${task.id}`;
    
    for (const tab of existingTabs) {
      if (tab.dataset.uniqueKey === uniqueKey) {
        console.warn(`已经存在相同策略 ${strategyName} (${timingStrategyDisplay}) ${dateRange} 的结果页签，跳过添加`);
        return;
      }
    }

    // 显示结果页签容器
    this.elements.resultTabs.style.display = 'block';

    // 创建页签标题
    const tabTitle = document.createElement('div');
    tabTitle.className = 'result-tab';
    tabTitle.dataset.uniqueKey = uniqueKey;
    tabTitle.style.cssText = `
      padding: 8px 16px;
      border: 1px solid #e5e7eb;
      border-radius: 4px;
      cursor: pointer;
      background: #f3f4f6;
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
    `;
    
    // 构建页签标题，包含择时策略
    let tabText = strategyName;
    tabText += ` - ${timingStrategyDisplay}`;
    if (task.start_date && task.end_date) {
      tabText += ` ${task.start_date}~${task.end_date}`;
    }
    // 【2026-09-21】无区间信息时补任务序号 ✓，避免"多个页签同名"难以区分 ✓
    //   （后端 task_results 未回传区间 ✗，前端只能用序号兜底 ✓）
    if (!(task.start_date && task.end_date) && task.id !== undefined && task.id !== null) {
      tabText += ` #${task.id}`;
    }
    
    tabTitle.innerHTML = `
      <span>${tabText}</span>
      <button class="close-tab" style="background:none; border:none; cursor:pointer; font-size:14px; padding:0; color:#6b7280;" onclick="event.stopPropagation();">✕</button>
    `;

    // 绑定页签点击事件
    tabTitle.addEventListener('click', () => {
      this.switchResultTab(task.id);
    });

    // 绑定关闭按钮事件
    tabTitle.querySelector('.close-tab').addEventListener('click', () => {
      this.closeResultTab(task.id);
    });

    // 添加到页签容器
    this.elements.resultTabsContainer.appendChild(tabTitle);

    // 创建结果内容容器
    const resultDiv = document.createElement('div');
    resultDiv.id = `result-${task.id}`;
    resultDiv.style.display = 'none';
    resultDiv.innerHTML = this.formatResultContent(task, result);
    this.elements.resultContent.appendChild(resultDiv);

    // 显示新添加的结果
    this.switchResultTab(task.id);
    
    // 绘制收益曲线
    if (result.equity_curve && result.equity_curve.length > 0) {
      this.drawEquityChart(task.id, result.equity_curve);
    } else if (result.capital_history && result.capital_history.length > 0) {
      // 如果没有 equity_curve，尝试使用 capital_history 和 dates（备用方案）
      const equityCurve = result.capital_history.map((capital, index) => ({
        capital: capital,
        date: result.dates ? result.dates[index] : ''
      }));
      this.drawEquityChart(task.id, equityCurve);
    }
  }

  /**
   * 格式化结果内容
   * @param {Object} task - 任务对象
   * @param {Object} result - 回测结果
   * @returns {string} HTML内容
   */
  formatResultContent(task, result) {
    // 择时策略中文名称映射
    const timingStrategyNames = {
      'turtle': '海龟策略',
      'low_turtle': '低位海龟策略',
      'turtle_plus': '海龟plus',
      'rsi': 'RSI策略',
      'bollinger': '布林带策略',
      'support': '支撑位策略',
      'macd_bollinger': '顺势宝',
      'uptrend_pullback': '趋势回调缩量策略'
    };

    // 获取择时策略名称（优先从结果中获取，其次从任务中获取）
    let timingStrategy = null;
    if (result.timing_strategy) {
      if (typeof result.timing_strategy === 'object') {
        timingStrategy = result.timing_strategy.name;
      } else {
        timingStrategy = result.timing_strategy;
      }
    }
    if (!timingStrategy && task.timing_strategy) {
      timingStrategy = task.timing_strategy;
    }
    if (!timingStrategy) {
      timingStrategy = 'turtle';
    }
    
    // 获取择时策略显示名称
    const timingStrategyDisplay = timingStrategyNames[timingStrategy] || timingStrategy;
    
    // 获取绩效指标（支持两种格式：直接字段或performance子对象）
    const performance = result.performance || result;
    const totalReturn = parseFloat(performance.total_return) || 0;
    const winRate = parseFloat(performance.win_rate) || 0;
    const profitLossRatio = parseFloat(performance.profit_loss_ratio) || 0;
    const maxDrawdown = parseFloat(performance.max_drawdown) || 0;
    const sharpeRatio = parseFloat(performance.sharpe_ratio) || 0;

    // 确保trades是一个数组
    const trades = Array.isArray(result.trades) ? result.trades : [];

    return `
      <div style="padding: 16px;">
        <h4 style="margin-bottom: 16px; color: #374151;">${result.strategy_name || task.strategy_name} 回测结果</h4>

        <!-- 基本信息 -->
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px;">
          <div style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff;">
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">择时策略</div>
            <div style="font-size: 14px; font-weight: 600; color: #374151;">
              ${timingStrategyDisplay}
            </div>
          </div>
          <div style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff;">
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">开始日期</div>
            <div style="font-size: 14px; font-weight: 600; color: #374151;">
              ${result.start_date || task.start_date || ''}
            </div>
          </div>
          <div style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff;">
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">结束日期</div>
            <div style="font-size: 14px; font-weight: 600; color: #374151;">
              ${result.end_date || task.end_date || ''}
            </div>
          </div>
          <div style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff;">
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">初始资金</div>
            <div style="font-size: 14px; font-weight: 600; color: #374151;">
              ${(result.initial_capital || 300000).toLocaleString()}
            </div>
          </div>
        </div>

        <!-- 统计数据 -->
        <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 24px;">
          <div style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff;">
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">总收益率</div>
            <div style="font-size: 24px; font-weight: bold; color: ${totalReturn >= 0 ? '#22c55e' : '#ef4444'};">
              ${totalReturn.toFixed(2)}%
            </div>
          </div>
          <div style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff;">
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">胜率</div>
            <div style="font-size: 24px; font-weight: bold; color: #3b82f6;">
              ${winRate.toFixed(2)}%
            </div>
          </div>
          <div style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff;">
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">盈亏比</div>
            <div style="font-size: 24px; font-weight: bold; color: #f59e0b;">
              ${profitLossRatio.toFixed(2)}
            </div>
          </div>
          <div style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff;">
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">最大回撤</div>
            <div style="font-size: 24px; font-weight: bold; color: #ef4444;">
              ${maxDrawdown.toFixed(2)}%
            </div>
          </div>
          <div style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff;">
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">夏普比率</div>
            <div style="font-size: 24px; font-weight: bold; color: #8b5cf6;">
              ${sharpeRatio.toFixed(2)}
            </div>
          </div>
        </div>

        <!-- 权益曲线 -->
        <div style="margin-bottom: 24px;">
          <h5 style="margin-bottom: 12px; color: #374151; font-size: 14px;">权益曲线</h5>
          <div style="border: 1px solid #e5e7eb; border-radius: 6px; padding: 16px; background: #ffffff;">
            <!-- 【2026-09-20】Chart.js 标准写法：固定高度定位容器
                 （原为 canvas 内联 height + 父容器无高度 → 画布缓冲为 0 → 权益曲线空白） -->
            <div style="position:relative; height:300px; width:100%;">
              <canvas id="equity-chart-${task.id}"></canvas>
            </div>
          </div>
        </div>

        <!-- 交易明细 -->
        <div>
          <h5 style="margin-bottom: 12px; color: #374151; font-size: 14px;">交易明细</h5>
          <div class="table-container" style="border: 1px solid #e5e7eb; border-radius: 6px; overflow: hidden;">
            <table class="data-table" style="width: 100%; border-collapse: collapse;">
              <thead>
                <tr style="background: #f9fafb;">
                  <th style="padding: 8px; text-align: left; font-size: 12px; border-bottom: 1px solid #e5e7eb;">股票代码</th>
                  <th style="padding: 8px; text-align: left; font-size: 12px; border-bottom: 1px solid #e5e7eb;">股票名称</th>
                  <th style="padding: 8px; text-align: left; font-size: 12px; border-bottom: 1px solid #e5e7eb;">买入日期</th>
                  <th style="padding: 8px; text-align: left; font-size: 12px; border-bottom: 1px solid #e5e7eb;">买入价格</th>
                  <th style="padding: 8px; text-align: left; font-size: 12px; border-bottom: 1px solid #e5e7eb;">卖出日期</th>
                  <th style="padding: 8px; text-align: left; font-size: 12px; border-bottom: 1px solid #e5e7eb;">卖出价格</th>
                  <th style="padding: 8px; text-align: left; font-size: 12px; border-bottom: 1px solid #e5e7eb;">收益率</th>
                </tr>
              </thead>
              <tbody>
                ${trades.length > 0 ? trades.map(trade => `
                  <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-size: 12px;"><a href="${trade.detail_url || 'javascript:void(0)'}" onclick="viewStockDetail('${trade.stock_code}'); return false;" style="color: #2563eb; text-decoration: none; cursor: pointer; font-weight: 600;">${trade.stock_code || ''}</a></td>
                    <td style="padding: 8px; font-size: 12px;">${trade.stock_name || ''}</td>
                    <td style="padding: 8px; font-size: 12px;">${trade.buy_date || ''}</td>
                    <td style="padding: 8px; font-size: 12px;">${(trade.buy_price || 0).toFixed(2)}</td>
                    <td style="padding: 8px; font-size: 12px;">${trade.sell_date || ''}</td>
                    <td style="padding: 8px; font-size: 12px;">${(trade.sell_price || 0).toFixed(2)}</td>
                    <td style="padding: 8px; font-size: 12px; color: ${(trade.return_rate || 0) >= 0 ? '#22c55e' : '#ef4444'};">
                      ${(trade.return_rate || 0).toFixed(2)}%
                    </td>
                  </tr>
                `).join('') : '<tr><td colspan="7" style="padding: 16px; text-align: center; font-size: 12px; color: #6b7280;">暂无交易记录</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * 切换结果页签
   * @param {number} taskId - 任务ID
   */
  switchResultTab(taskId) {
    // 隐藏所有结果内容
    const allResults = this.elements.resultContent.querySelectorAll('[id^="result-"]');
    allResults.forEach(el => el.style.display = 'none');

    // 显示指定的结果
    const resultDiv = document.getElementById(`result-${taskId}`);
    if (resultDiv) {
      resultDiv.style.display = 'block';
    }

    // 更新页签样式
    const tabs = this.elements.resultTabsContainer.querySelectorAll('.result-tab');
    tabs.forEach(tab => {
      tab.style.background = '#f3f4f6';
      tab.style.color = '#374151';
    });

    // 高亮当前页签
    const currentTab = Array.from(tabs).find(tab => {
      const resultDiv = document.getElementById(`result-${taskId}`);
      return resultDiv && tab.textContent.includes(resultDiv.id);
    });
    if (currentTab) {
      currentTab.style.background = '#dbeafe';
      currentTab.style.color = '#1e40af';
    }
  }

  /**
   * 绘制收益曲线
   * @param {number} taskId - 任务ID
   * @param {Array} equityCurve - 权益曲线数据
   */
  drawEquityChart(taskId, equityCurve) {
    if (!equityCurve || equityCurve.length === 0) {
      console.warn('没有收益曲线数据，无法绘制图表');
      const ctx = document.getElementById(`equity-chart-${taskId}`);
      if (ctx) {
        const parent = ctx.parentElement;
        if (parent) {
          parent.innerHTML = '<div style="text-align: center; padding: 40px; color: #6b7280;">暂无收益曲线数据</div>';
        }
      }
      return;
    }
    
    const ctx = document.getElementById(`equity-chart-${taskId}`);
    if (!ctx) {
      console.error('找不到图表容器元素');
      return;
    }
    
    // 提取数据
    const dates = equityCurve.map(item => item.date);
    const capital = equityCurve.map(item => item.capital);
    
    // 准备数据
    const labels = dates.map(date => {
      if (date instanceof Date) {
        return date.toISOString().split('T')[0];
      }
      return date;
    });
    
    // 计算收益率
    const initialCapital = capital[0] || 1000000;
    const returns = capital.map(capitalValue => {
      return ((capitalValue - initialCapital) / initialCapital) * 100;
    });
    
    // 销毁旧图表
    if (this.charts && this.charts[taskId]) {
      this.charts[taskId].destroy();
    }
    
    // 创建新图表
    try {
      const chart = new window.Chart(ctx, {   // 【2026-09-20】统一用 window.Chart
        type: 'line',
        data: {
          labels: labels,
          datasets: [{
            label: '收益率 (%)',
            data: returns,
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            borderWidth: 2,
            fill: true,
            tension: 0.4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'top',
              labels: {
                font: {
                  size: 12
                }
              }
            },
            tooltip: {
              mode: 'index',
              intersect: false
            }
          },
          scales: {
            x: {
              display: true,
              title: {
                display: true,
                text: '日期',
                font: {
                  size: 12
                }
              },
              ticks: {
                font: {
                  size: 10
                },
                maxRotation: 45,
                minRotation: 45
              }
            },
            y: {
              display: true,
              title: {
                display: true,
                text: '收益率 (%)',
                font: {
                  size: 12
                }
              },
              ticks: {
                font: {
                  size: 10
                }
              }
            }
          }
        }
      });
      
      // 保存图表实例
      if (!this.charts) {
        this.charts = {};
      }
      this.charts[taskId] = chart;
    } catch (error) {
      console.error('绘制收益曲线失败:', error);
      const parent = ctx.parentElement;
      if (parent) {
        parent.innerHTML = '<div style="text-align: center; padding: 40px; color: #6b7280;">绘制收益曲线失败</div>';
      }
    }
  }

  /**
   * 关闭结果页签
   * @param {number} taskId - 任务ID
   */
  closeResultTab(taskId) {
    // 删除页签
    const tabs = this.elements.resultTabsContainer.querySelectorAll('.result-tab');
    tabs.forEach(tab => {
      if (tab.textContent.includes(`result-${taskId}`)) {
        tab.remove();
      }
    });

    // 删除结果内容
    const resultDiv = document.getElementById(`result-${taskId}`);
    if (resultDiv) {
      resultDiv.remove();
    }

    // 如果没有页签了，隐藏结果容器
    if (this.elements.resultTabsContainer.children.length === 0) {
      this.elements.resultTabs.style.display = 'none';
    }
  }

  /**
   * 显示错误信息
   * @param {string} message - 错误信息
   */
  showError(message) {
    alert(`错误: ${message}`);
    console.error(message);
  }

  /**
   * 显示信息提示
   * 用于显示重试通知、成功提示等
   * @param {string} message - 提示信息
   * @param {string} type - 提示类型 ('info', 'success', 'warning', 'error')
   * @param {number} duration - 显示时长（毫秒，0表示不自动关闭）
   */
  showInfo(message, type = 'info', duration = 3000) {
    // 创建提示容器
    const notificationId = `notification-${Date.now()}`;
    const notification = document.createElement('div');
    notification.id = notificationId;
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      padding: 12px 16px;
      border-radius: 6px;
      font-size: 14px;
      z-index: 10000;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
      animation: slideIn 0.3s ease-out;
      max-width: 400px;
      word-wrap: break-word;
    `;

    // 根据类型设置样式
    const styles = {
      info: {
        background: '#dbeafe',
        color: '#1e40af',
        border: '1px solid #93c5fd'
      },
      success: {
        background: '#dcfce7',
        color: '#166534',
        border: '1px solid #86efac'
      },
      warning: {
        background: '#fef3c7',
        color: '#92400e',
        border: '1px solid #fcd34d'
      },
      error: {
        background: '#fee2e2',
        color: '#991b1b',
        border: '1px solid #fca5a5'
      }
    };

    const style = styles[type] || styles.info;
    notification.style.background = style.background;
    notification.style.color = style.color;
    notification.style.border = style.border;

    // 设置内容
    notification.textContent = message;

    // 添加到页面
    document.body.appendChild(notification);

    // 添加动画样式
    const style_tag = document.createElement('style');
    if (!document.getElementById('notification-styles')) {
      style_tag.id = 'notification-styles';
      style_tag.textContent = `
        @keyframes slideIn {
          from {
            transform: translateX(400px);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        @keyframes slideOut {
          from {
            transform: translateX(0);
            opacity: 1;
          }
          to {
            transform: translateX(400px);
            opacity: 0;
          }
        }
      `;
      document.head.appendChild(style_tag);
    }

    // 自动关闭
    if (duration > 0) {
      setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => {
          notification.remove();
        }, 300);
      }, duration);
    }

    console.log(`[${type.toUpperCase()}] ${message}`);
  }

  /**
   * 清空表单 - 重置到初始状态
   * 策略选择：重置为第一个选项
   * 支撑位选择：重置为 'ma20'（20日均线）
   * 开始日期：重置为上个月1日
   * 结束日期：重置为今天
   */
  clearForm() {
    // 策略选择：重置为第一个选项
    if (this.elements.strategySelect.options.length > 0) {
      this.elements.strategySelect.selectedIndex = 0;
    }
    
    // 获取当前日期
    const today = new Date();
    
    // 开始日期：重置为上个月1日
    const startDate = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    this.elements.startDate.value = this._formatDate(startDate);
    
    // 结束日期：重置为今天
    this.elements.endDate.value = this._formatDate(today);
  }

  /**
   * 格式化日期为 YYYY-MM-DD 格式
   * @param {Date} date - 日期对象
   * @returns {string} 格式化后的日期字符串
   */
  _formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  /**
   * 获取表单数据
   * @returns {Object} 表单数据
   */
  getFormData() {
    // 直接使用中文策略名称
    const chineseStrategyName = this.elements.strategySelect.value || '';
    let timingStrategy = this.elements.timingStrategy?.value || 'turtle';
    let supportLevelMethod = 'ma20';
    
    // 处理支撑位策略的情况
    if (timingStrategy.startsWith('support_')) {
      supportLevelMethod = timingStrategy.replace('support_', '');
      timingStrategy = 'support';
    }
    
    return {
      strategy_name: chineseStrategyName,  // 发送中文名称给后端
      timing_strategy: timingStrategy,
      support_level_method: supportLevelMethod,
      start_date: this.elements.startDate.value,
      end_date: this.elements.endDate.value
    };
  }
}

// ==================== ETA 预估工具（批次3） ====================

/**
 * 将秒数格式化为人类可读的时长
 * @param {number} seconds - 秒数
 * @returns {string} 格式化后的时长，如 "2小时15分钟"、"5分钟"、"30秒"
 */
function formatDuration(seconds) {
  // 异常值兜底
  if (!seconds || seconds < 0 || !isFinite(seconds)) return '--';
  // 不足1分钟按秒展示
  if (seconds < 60) return `${Math.round(seconds)}秒`;
  const minutes = Math.floor(seconds / 60);
  // 不足1小时按分钟展示
  if (minutes < 60) return `${minutes}分钟`;
  const hours = Math.floor(minutes / 60);
  const remainMinutes = minutes % 60;
  // 不足1天按"小时+分钟"展示
  if (hours < 24) return remainMinutes > 0 ? `${hours}小时${remainMinutes}分钟` : `${hours}小时`;
  const days = Math.floor(hours / 24);
  const remainHours = hours % 24;
  return remainHours > 0 ? `${days}天${remainHours}小时` : `${days}天`;
}

/**
 * 计算批量回测剩余耗时预估
 * 算法（批次3）：
 *   - 当前任务剩余 = (total_days - done_days) × (已耗时 / done_days)
 *     前3个交易日无法稳定估算单日耗时，标记为"预估中"
 *   - 平均任务耗时 = 已完成任务累计耗时 / 已完成任务数
 *   - 未开始任务预估 = 未开始任务数 × 平均任务耗时
 *   - 总剩余 = 当前任务剩余 + 未开始任务预估
 * @param {Object} status - /backtest/batch/status 返回的 data 对象
 * @returns {Object} { etaText, currentTaskText, progressPercent }
 */
// 【2026-09-20】ETA 观测基准：前端**首次看到当前任务在跑**的时刻
//   用途：排除"点击开始 → 引擎真正处理每日流程"之间的预处理/预加载耗时 ✓
//   （用户要求：估算只统计"处理每日流程"的时间 ✓；切任务/切批次自动重置 ✓）
const _batchEtaObs = { batchId: null, taskKey: null, taskSeenAt: null, durations: [] };

/** 【2026-09-20】还原「开始执行回测」按钮的文案与样式（运行结束后调用 ✓） */
function _restoreExecutionBtn() {
  const b = backtestUIManager && backtestUIManager.elements
    ? backtestUIManager.elements.startExecutionBtn : null;
  if (!b) return;
  if (b.dataset.origText) b.textContent = b.dataset.origText;
  if (b.dataset.origStyle !== undefined) b.setAttribute('style', b.dataset.origStyle);
}

function calcBatchEta(status) {
  // 缺少 current_task 时回退到粗粒度进度
  if (!status.current_task) {
    const pct = status.total_tasks > 0
      ? Math.round((status.completed_tasks / status.total_tasks) * 100)
      : 0;
    return { etaText: '--', currentTaskText: '', progressPercent: pct };
  }

  const ct = status.current_task;
  const now = Date.now();
  // 【2026-09-20】估算基准（排除预处理/预加载耗时 ✓）：
  //   ① 首选：前端**首次观测到当前任务在跑**的时刻（_batchEtaObs ✓）
  //   ② 兜底：后端 current_task.started_at（例如刚打开页面时任务已在跑 ✓）
  const _obsKey = `${status.batch_id || ''}#${ct.index !== undefined ? ct.index : (ct.strategy_name || '')}`;
  if (_batchEtaObs.batchId !== (status.batch_id || '')) {   // 换了批次 → 清空历史 ✓
    _batchEtaObs.batchId = status.batch_id || '';
    _batchEtaObs.durations = [];
  }
  if (_batchEtaObs.taskKey !== _obsKey) {       // 新任务 → 结算上一个任务的"每日流程"耗时 ✓
    if (_batchEtaObs.taskKey && _batchEtaObs.taskSeenAt) {
      const _prev = (now - _batchEtaObs.taskSeenAt) / 1000;
      if (_prev > 0) _batchEtaObs.durations.push(_prev);
    }
    _batchEtaObs.taskKey = _obsKey;
    _batchEtaObs.taskSeenAt = now;
  }
  const _backendStart = ct.started_at ? new Date(ct.started_at).getTime() : null;
  // 【2026-09-20】基准 = **第 1 个交易日完成的那一刻** ✓
  //   原因：任务刚"running"时引擎往往还在预处理/预加载 ✗（实测该任务 19:09 running、
  //   19:2x 才进入逐日循环 ✗）→ 用任务启动时刻会把预处理算进单日耗时 → 预估偏大 ✗。
  //   改为一观察到 done_days>0 就打点 ✓，并以 (done_days-1) 为分母 ✓ → 只统计"每日流程" ✓
  const _dd0 = Number(ct.done_days) || 0;     // ⚠️ 此处 doneDays 尚未声明 ✗ → 直接用 ct 字段 ✓
  if (_dd0 === 0) {
    _batchEtaObs.firstDoneAt = null;          // 新任务/回退 → 重置 ✓
  } else if (!_batchEtaObs.firstDoneAt) {
    _batchEtaObs.firstDoneAt = now;           // 首个交易日刚完成 ✓
  }
  const startedAt = _batchEtaObs.firstDoneAt || _batchEtaObs.taskSeenAt || _backendStart;
  const elapsedSec = startedAt ? Math.max(0, (now - startedAt) / 1000) : 0;

  const doneDays = ct.done_days || 0;
  const totalDays = ct.total_days || 0;

  // 1. 当前任务剩余预估
  let currentTaskRemainSec = null; // null 表示"预估中"
  // 前3个交易日单日耗时不稳定，不展示预估
  if (doneDays >= 3 && totalDays > 0 && startedAt) {
    // 【2026-09-20】分母用 (done_days - 1)：因为基准是"第 1 天完成时" ✓
    //   → 只反映"每日流程"的净耗时 ✓（不含预处理/预加载 ✓）
    const secPerDay = elapsedSec / Math.max(1, doneDays - 1);
    const remainDays = totalDays - doneDays;
    currentTaskRemainSec = remainDays * secPerDay;
  }

  // 2. 已完成任务平均耗时（用于预估未开始任务）
  const results = status.task_results || [];
  let totalTaskSec = 0;
  let validTaskCount = 0;
  results.forEach((r) => {
    // 仅计算同时具备开始和完成时间的任务
    if (r.started_at && r.completed_at) {
      const s = new Date(r.started_at).getTime();
      const e = new Date(r.completed_at).getTime();
      if (e > s) {
        totalTaskSec += (e - s) / 1000;
        validTaskCount += 1;
      }
    }
  });
  // 【2026-09-20】平均任务耗时优先用**前端观测值** ✓（其计时从"首次看到任务在跑"起 ✓，
  //   已排除预处理/预加载 ✗）；后端值（started_at→completed_at ✓）含预处理，仅作兜底 ✓
  const _feAvgSec = _batchEtaObs.durations.length
    ? _batchEtaObs.durations.reduce((a, b) => a + b, 0) / _batchEtaObs.durations.length
    : null;
  const avgTaskSec = _feAvgSec !== null
    ? _feAvgSec
    : (validTaskCount > 0 ? totalTaskSec / validTaskCount : null);

  // 3. 未开始任务数（总任务 - 已完成 - 当前执行中1个）
  const completedTasks = status.completed_tasks || 0;
  const totalTasks = status.total_tasks || 0;
  const pendingTaskCount = Math.max(0, totalTasks - completedTasks - 1);

  // 4. 未开始任务预估总耗时
  // 【2026-09-20】无"已完成任务均值"时，用**当前任务速率**外推 ✓
  //   （用户明确：本批共 5 个策略/任务 ✓ → 批次总剩余必须包含后续任务 ✗）
  //   该任务预计总耗时 ≈ 单日净耗时 × 任务总交易日数 ✓（≥3 天门槛与上面一致 ✓）
  const _rateTaskSec = (doneDays >= 3 && startedAt && totalDays > 0)
    ? (elapsedSec / Math.max(1, doneDays - 1)) * totalDays
    : null;
  const _pendingBaseSec = (avgTaskSec !== null) ? avgTaskSec : _rateTaskSec;
  const pendingTaskRemainSec = _pendingBaseSec !== null
    ? _pendingBaseSec * pendingTaskCount
    : null;

  // 5. 批次总剩余 = 当前任务剩余 + 未开始任务预估
  let totalRemainSec = null;
  let etaByTaskAvg = false;            // 【2026-09-20】是否采用"任务级均值"兜底
  if (currentTaskRemainSec !== null && pendingTaskRemainSec !== null) {
    totalRemainSec = currentTaskRemainSec + pendingTaskRemainSec;
  } else if (currentTaskRemainSec !== null) {
    // 仅有当前任务剩余（无历史平均）
    totalRemainSec = currentTaskRemainSec;
  } else if (pendingTaskRemainSec !== null) {
    // 【2026-09-20 修复】当前任务刚起步时（doneDays < 3 → 单日耗时不稳定，故
    //   currentTaskRemainSec = null ✗），"已完成任务的平均耗时"明明可用 ✓ 却
    //   被原实现整体丢弃 ✗ → 界面一直停在"预估中" ✗（本次问题的根因 ✓）。
    //   现改为：按均值估"当前任务 1 份 + 未开始任务 N 份" ✓，并标注估算依据 ✓
    totalRemainSec = avgTaskSec + pendingTaskRemainSec;
    etaByTaskAvg = true;
  }

  // 组装 ETA 文本
  let etaText;
  if (totalRemainSec !== null) {
    const remainTxt = formatDuration(totalRemainSec);
    // 同时展示当前任务剩余，便于用户判断
    if (currentTaskRemainSec !== null) {
      const curTxt = formatDuration(currentTaskRemainSec);
      etaText = `当前剩余 ${curTxt}，批次总剩余 ${remainTxt}`;
    } else if (etaByTaskAvg) {
      // 该分支只在"有已完成任务均值"时进入 ✓（当前任务剩余未知 ✓）
      etaText = `批次总剩余 ${remainTxt}（按已完成任务均值估算，共 ${totalTasks} 个任务）`;
    } else {
      etaText = `批次总剩余 ${remainTxt}`;
    }
  } else if (startedAt) {
    // 前3个交易日：展示已耗时，标注预估中
    etaText = `已耗时 ${formatDuration(elapsedSec)}，预估中`;
  } else {
    etaText = '预估中';
  }

  // 当前任务展示文本：交易日进度 + 当前交易日（策略名/序号由 showProgress 拼接）
  const dayProgress = totalDays > 0 ? ` | 交易日 ${doneDays}/${totalDays}` : '';
  const curDate = ct.current_date ? ` (${ct.current_date})` : '';
  const currentTaskText = `交易日进度${dayProgress}${curDate}`;

  // 整体进度百分比：按交易日加权
  let progressPercent;
  if (totalTasks > 0) {
    // 当前任务内交易日进度（0~1）
    const taskInnerRatio = totalDays > 0 ? doneDays / totalDays : 0;
    // 整体 = (已完成任务 + 当前任务内进度) / 总任务数
    progressPercent = Math.round(((completedTasks + taskInnerRatio) / totalTasks) * 100);
  } else {
    progressPercent = 0;
  }

  return { etaText, currentTaskText, progressPercent };
}

// ==================== 全局初始化 ====================

// 创建全局实例
let backtestTaskManager = null;
let backtestUIManager = null;

/**
 * 初始化批量回测模块
 * 创建任务管理器和UI管理器实例，绑定事件处理
 */
async function initBacktestBatchModule() {
  console.log('初始化批量回测模块');
  
  // 创建管理器实例
  backtestTaskManager = new BacktestTaskManager();
  backtestUIManager = new BacktestUIManager();

  // 加载策略列表
  await loadStrategies();

  // 初始化表单（设置默认日期）
  backtestUIManager.clearForm();

  // 绑定事件
  bindBacktestBatchEvents();
  
  // 初始化任务列表显示（初始为空）
  backtestUIManager.updateTaskList([]);
  backtestUIManager.updateTaskStats(0, '0小时');
  
  console.log('批量回测模块初始化完成');
}

/**
 * 加载策略列表
 */
async function loadStrategies() {
  try {
    const response = await fetch('/api/trading/backtest/strategies');
    if (!response.ok) {
      throw new Error('加载策略列表失败');
    }
    const data = await response.json();
    if (data.success && data.data && data.data.strategies) {
      const strategies = data.data.strategies;
      const strategySelect = document.getElementById('strategy-select');
      if (strategySelect) {
        strategySelect.innerHTML = '';
        strategies.forEach(strategy => {
          const option = document.createElement('option');
          // 使用中文名称作为value和显示文本
          const chineseName = strategy.display_name || strategy.name;
          option.value = chineseName;
          option.textContent = chineseName;
          strategySelect.appendChild(option);
        });
      }
    } else {
      console.warn('策略列表为空或数据格式不正确');
    }
  } catch (error) {
    console.error('加载策略列表失败:', error);
    alert('加载策略列表失败，请刷新页面重试');
  }
}

/**
 * 绑定事件处理
 */
function bindBacktestBatchEvents() {
  // 加入任务按钮
  backtestUIManager.elements.addTaskBtn.addEventListener('click', () => {
    try {
      const formData = backtestUIManager.getFormData();
      
      // 验证表单
      if (!formData.strategy_name || !formData.start_date || !formData.end_date) {
        backtestUIManager.showError('请填写完整的回测配置');
        return;
      }

      // 添加任务
      const task = backtestTaskManager.addTask(formData);
      
      // 更新UI
      const tasks = backtestTaskManager.getTasks();
      backtestUIManager.updateTaskList(tasks);
      backtestUIManager.updateTaskStats(
        backtestTaskManager.getTaskCount(),
        backtestTaskManager.estimateTime()
      );

      // 清空表单
      backtestUIManager.clearForm();
      
      console.log(`任务添加成功，当前任务数: ${backtestTaskManager.getTaskCount()}`);
    } catch (error) {
      backtestUIManager.showError(error.message);
    }
  });

  // 开始执行按钮
  backtestUIManager.elements.startExecutionBtn.addEventListener('click', async () => {
    console.log('开始执行回测');
    await executeBacktestBatch();
  });

  // 暂停按钮
  backtestUIManager.elements.pauseBtn.addEventListener('click', () => {
    console.log('暂停执行');
    // TODO: 实现暂停逻辑（第二阶段）
  });

  // 取消按钮
  backtestUIManager.elements.cancelBtn.addEventListener('click', () => {
    console.log('取消执行');
    // TODO: 实现取消逻辑（第二阶段）
  });
}

/**
 * 删除任务（供HTML调用）
 * 从任务队列中删除指定ID的任务，并更新UI显示
 * @param {number} taskId - 任务ID
 */
function removeBacktestTask(taskId) {
  // 从任务管理器中删除任务
  if (backtestTaskManager.removeTask(taskId)) {
    // 获取更新后的任务列表
    const tasks = backtestTaskManager.getTasks();
    // 更新任务列表显示
    backtestUIManager.updateTaskList(tasks);
    // 更新任务统计信息
    backtestUIManager.updateTaskStats(
      backtestTaskManager.getTaskCount(),
      backtestTaskManager.estimateTime()
    );
    console.log(`任务 ${taskId} 已删除，当前任务数: ${backtestTaskManager.getTaskCount()}`);
  }
}

// 导出模块 - 支持ES6模块
export {
  BacktestTaskManager,
  BacktestUIManager,
  initBacktestBatchModule,
  removeBacktestTask,
  backtestTaskManager,
  backtestUIManager
};

/**
 * 执行批量回测
 * 改为后端任务队列执行，支持浏览器关闭后继续执行
 */
async function executeBacktestBatch() {
  try {
    const tasks = backtestTaskManager.getTasks();
    if (tasks.length === 0) {
      backtestUIManager.showError('没有待执行的任务');
      return;
    }

    // 禁用开始执行按钮
    // 【2026-09-20】运行中：文案改「回测中…」并置灰 ✓（结束后由 _restoreExecutionBtn 还原 ✓）
  const _seBtn = backtestUIManager.elements.startExecutionBtn;
  if (_seBtn) {
    if (_seBtn.dataset.origText === undefined) _seBtn.dataset.origText = _seBtn.textContent.trim() || '开始执行回测';
    if (_seBtn.dataset.origStyle === undefined) _seBtn.dataset.origStyle = _seBtn.getAttribute('style') || '';
    _seBtn.textContent = '回测中…';
    _seBtn.disabled = true;
    _seBtn.setAttribute('style',
      'padding:6px 16px;font-size:12px;background:#94a3b8;border-color:#94a3b8;color:#fff;cursor:not-allowed;');
  }

    // 加载保存的回测配置
    let savedParams = {
      initial_capital: 1000000,
      score_threshold: 60,
      buy_amount: 100000,
      max_daily_buys: 5,
      stop_loss: -0.05,
      take_profit: 0.15,
      max_hold_days: 10
    };

    // 从后端API加载配置
    try {
      const response = await fetch('/api/trading/backtest/configs');
      if (response.ok) {
        const data = await response.json();
        if (data.success && data.data.configs && data.data.configs.length > 0) {
          const config = data.data.configs[0];
          savedParams = {
            initial_capital: config.initial_capital || 1000000,
            score_threshold: config.score_threshold || 60,
            buy_amount: config.buy_amount || 100000,
            max_daily_buys: config.max_daily_buys || 5,
            stop_loss: config.stop_loss || -5,  // 数据库存的是百分比，直接使用
            take_profit: config.take_profit || 15,  // 数据库存的是百分比，直接使用
            max_hold_days: config.hold_period || 10
          };
        }
      }
    } catch (error) {
      console.error('加载回测配置失败:', error);
    }

    // 构建任务列表
    const taskList = tasks.map(task => ({
      strategy_name: task.strategy_name,
      start_date: task.start_date,
      end_date: task.end_date,
      timing_strategy: task.timing_strategy || 'turtle',
      support_level_method: task.support_level_method || 'ma20'
    }));

    // 1. 提交批量任务到后端
    const submitResponse = await fetch('/api/trading/backtest/batch/submit', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        tasks: taskList,
        config: {
          initial_capital: savedParams.initial_capital,
          score_threshold: savedParams.score_threshold,
          max_daily_buys: savedParams.max_daily_buys,
          stop_loss: savedParams.stop_loss,
          take_profit: savedParams.take_profit,
          max_hold_days: savedParams.max_hold_days
        }
      })
    });

    if (!submitResponse.ok) {
      throw new Error('提交批量任务失败');
    }

    const submitData = await submitResponse.json();
    if (!submitData.success) {
      throw new Error(submitData.message || '提交批量任务失败');
    }

    const batchId = submitData.data.batch_id;
    console.log(`批量任务已提交: ${batchId}, 任务数: ${submitData.data.total_tasks}`);

    // 2. 开始执行
    const startResponse = await fetch('/api/trading/backtest/batch/start', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ batch_id: batchId })
    });

    if (!startResponse.ok) {
      throw new Error('启动批量任务失败');
    }

    const startData = await startResponse.json();
    if (!startData.success) {
      throw new Error(startData.message || '启动批量任务失败');
    }

    console.log(`批量任务已开始执行: ${batchId}`);

    // 3. 轮询进度
    await pollBatchStatus(batchId, tasks.length);

    // 4. 获取最终结果
    const resultsResponse = await fetch(`/api/trading/backtest/batch/results?batch_id=${batchId}`);
    if (resultsResponse.ok) {
      const resultsData = await resultsResponse.json();
      if (resultsData.success && resultsData.data.results) {
        // 更新任务状态和结果
        resultsData.data.results.forEach((result, index) => {
          const task = tasks[index];
          if (task) {
            if (result.status === 'completed' && result.result) {
              backtestTaskManager.updateTaskStatus(task.id, 'completed', result.result);
              backtestUIManager.addResultTab(task, result.result);
            } else if (result.status === 'failed') {
              backtestTaskManager.updateTaskStatus(task.id, 'failed');
              if (result.error) {
                backtestUIManager.showError(`${task.strategy_name}: ${result.error}`);
              }
            }
          }
        });
      }
    }

    // 执行完成
    backtestUIManager.hideProgress();
    backtestUIManager.elements.startExecutionBtn.disabled = false;
    _restoreExecutionBtn();      // 【2026-09-20】还原按钮文案与样式 ✓
    backtestUIManager.showInfo('批量回测执行完成', 'success');

  } catch (error) {
    console.error('批量回测执行失败:', error);
    backtestUIManager.showError(`批量回测执行失败: ${error.message}`);
    backtestUIManager.hideProgress();
    backtestUIManager.elements.startExecutionBtn.disabled = false;
    _restoreExecutionBtn();      // 【2026-09-20】还原按钮文案与样式 ✓
  }
}

/**
 * 轮询批量任务状态
 * @param {string} batchId - 批量任务ID
 * @param {number} totalTasks - 总任务数
 */
async function pollBatchStatus(batchId, totalTasks) {
  const pollInterval = 5000; // 5秒轮询一次
  const displayedTaskIndices = new Set(); // 记录已显示的任务索引

  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const response = await fetch(`/api/trading/backtest/batch/status?batch_id=${batchId}`);
        if (!response.ok) {
          throw new Error('查询状态失败');
        }

        const data = await response.json();
        if (!data.success) {
          throw new Error(data.message || '查询状态失败');
        }

        const status = data.data;
        console.log(`批量任务状态: ${status.status}, 进度: ${status.completed_tasks}/${status.total_tasks}`);

        // 更新 UI 进度（按实际交易日进度预估剩余耗时，批次3）
        if (status.current_task) {
          // 调用预估工具，计算 ETA、当前任务文本、加权进度百分比
          const eta = calcBatchEta(status);
          // 拼接当前任务展示文本：策略名 + 序号 + 交易日进度
          const taskLine = `正在执行: ${status.current_task.strategy_name || '执行中'} `
            + `(${status.completed_tasks + 1}/${status.total_tasks})${eta.currentTaskText}`;
          backtestUIManager.showProgress({
            strategyName: status.current_task.strategy_name || '执行中',
            currentIndex: status.completed_tasks + 1,
            totalCount: status.total_tasks,
            progress: eta.progressPercent,
            remainingTime: eta.etaText,
            // 透传当前任务行文本，供 UI 直接展示交易日进度
            currentTaskLine: taskLine
          });
        }

        // 实时检查并显示已完成的任务结果
        if (status.task_results && status.task_results.length > 0) {
          status.task_results.forEach((taskResult, index) => {
            if (taskResult.status === 'completed' && taskResult.result && !displayedTaskIndices.has(index)) {
              // 从结果中获取择时策略
              let timingStrategy = null;
              if (taskResult.result.timing_strategy) {
                if (typeof taskResult.result.timing_strategy === 'object') {
                  timingStrategy = taskResult.result.timing_strategy.name;
                } else {
                  timingStrategy = taskResult.result.timing_strategy;
                }
              }
              // 创建临时任务对象用于显示结果
              const tempTask = {
                id: index + 1,
                strategy_name: taskResult.strategy_name,
                start_date: taskResult.start_date || '',
                end_date: taskResult.end_date || '',
                timing_strategy: timingStrategy
              };
              backtestTaskManager.updateTaskStatus(tempTask.id, 'completed', taskResult.result);
              backtestUIManager.addResultTab(tempTask, taskResult.result);
              displayedTaskIndices.add(index);
              console.log(`已显示任务 ${index + 1} 的结果: ${taskResult.strategy_name}, 择时: ${timingStrategy}`);
            }
          });
        }

        // 检查是否完成
        if (status.status === 'completed' || status.status === 'failed') {
          // 显示剩余未显示的完成任务
          if (status.task_results && status.task_results.length > 0) {
            status.task_results.forEach((taskResult, index) => {
              if (taskResult.status === 'completed' && taskResult.result && !displayedTaskIndices.has(index)) {
                // 从结果中获取择时策略
                let timingStrategy = null;
                if (taskResult.result.timing_strategy) {
                  if (typeof taskResult.result.timing_strategy === 'object') {
                    timingStrategy = taskResult.result.timing_strategy.name;
                  } else {
                    timingStrategy = taskResult.result.timing_strategy;
                  }
                }
                const tempTask = {
                  id: index + 1,
                  strategy_name: taskResult.strategy_name,
                  start_date: taskResult.start_date || '',
                  end_date: taskResult.end_date || '',
                  timing_strategy: timingStrategy
                };
                backtestTaskManager.updateTaskStatus(tempTask.id, 'completed', taskResult.result);
                backtestUIManager.addResultTab(tempTask, taskResult.result);
                displayedTaskIndices.add(index);
              }
            });
          }
          resolve();
          return;
        }

        // 继续轮询
        setTimeout(poll, pollInterval);

      } catch (error) {
        console.error('轮询状态失败:', error);
        reject(error);
      }
    };

    poll();
  });
}
