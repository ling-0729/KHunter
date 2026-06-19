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
      strategy_name: config.strategy_name,
      start_date: config.start_date,
      end_date: config.end_date,
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
   * 计算预计耗时（小时）
   * 每个任务预计2-3小时，取平均2.5小时
   * @returns {string} 预计耗时字符串，格式: "X-Y小时"
   */
  estimateTime() {
    const count = this.getTaskCount();
    if (count === 0) return '0小时';
    
    const minHours = count * 2;
    const maxHours = count * 3;
    return `${minHours}-${maxHours}小时`;
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
      supportLevel: document.getElementById('support-level'),
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

    // 添加任务行
    tasks.forEach((task, index) => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${index + 1}</td>
        <td>${task.strategy_name}</td>
        <td>${task.start_date}</td>
        <td>${task.end_date}</td>
        <td>${task.support_level_method}</td>
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
    this.elements.currentTaskInfo.textContent = `正在执行: ${info.strategyName} (${info.currentIndex}/${info.totalCount})`;
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
    // 检查是否已经存在相同的页签
    const existingTabs = this.elements.resultTabsContainer.querySelectorAll('.result-tab');
    for (const tab of existingTabs) {
      if (tab.textContent.includes(`${task.strategy_name} ${task.start_date}~${task.end_date}`)) {
        console.warn('已经存在相同的结果页签，跳过添加');
        return;
      }
    }

    // 显示结果页签容器
    this.elements.resultTabs.style.display = 'block';

    // 创建页签标题
    const tabTitle = document.createElement('div');
    tabTitle.className = 'result-tab';
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
    tabTitle.innerHTML = `
      <span>${task.strategy_name} ${task.start_date}~${task.end_date}</span>
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
    // 计算收益率，确保它是一个数字
    const totalReturn = parseFloat(result.total_return) || 0;
    const winRate = parseFloat(result.win_rate) || 0;
    const maxDrawdown = parseFloat(result.max_drawdown) || 0;
    const sharpeRatio = parseFloat(result.sharpe_ratio) || 0;
    
    // 确保trades是一个数组
    const trades = Array.isArray(result.trades) ? result.trades : [];
    
    return `
      <div style="padding: 16px;">
        <h4 style="margin-bottom: 16px; color: #374151;">${task.strategy_name} 回测结果</h4>
        
        <!-- 统计数据 -->
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px;">
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
            <canvas id="equity-chart-${task.id}" height="300"></canvas>
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
                    <td style="padding: 8px; font-size: 12px;">${trade.stock_code || ''}</td>
                    <td style="padding: 8px; font-size: 12px;">${trade.buy_date || ''}</td>
                    <td style="padding: 8px; font-size: 12px;">${(trade.buy_price || 0).toFixed(2)}</td>
                    <td style="padding: 8px; font-size: 12px;">${trade.sell_date || ''}</td>
                    <td style="padding: 8px; font-size: 12px;">${(trade.sell_price || 0).toFixed(2)}</td>
                    <td style="padding: 8px; font-size: 12px; color: ${(trade.return_rate || 0) >= 0 ? '#22c55e' : '#ef4444'};">
                      ${(trade.return_rate || 0).toFixed(2)}%
                    </td>
                  </tr>
                `).join('') : '<tr><td colspan="6" style="padding: 16px; text-align: center; font-size: 12px; color: #6b7280;">暂无交易记录</td></tr>'}
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
      const chart = new Chart(ctx, {
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
    
    // 支撑位选择：重置为 'ma20'
    this.elements.supportLevel.value = 'ma20';
    
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
    return {
      strategy_name: this.elements.strategySelect.value,
      support_level_method: this.elements.supportLevel.value,
      start_date: this.elements.startDate.value,
      end_date: this.elements.endDate.value
    };
  }
}

// ==================== 全局初始化 ====================

// 创建全局实例
let backtestTaskManager = null;
let backtestUIManager = null;

/**
 * 初始化批量回测模块
 * 创建任务管理器和UI管理器实例，绑定事件处理
 */
function initBacktestBatchModule() {
  console.log('初始化批量回测模块');
  
  // 避免重复初始化
  if (backtestTaskManager && backtestUIManager) {
    console.log('批量回测模块已初始化，跳过重复初始化');
    return;
  }

  // 创建管理器实例
  backtestTaskManager = new BacktestTaskManager();
  backtestUIManager = new BacktestUIManager();

  // 绑定事件
  bindBacktestBatchEvents();
  
  // 初始化任务列表显示（初始为空）
  backtestUIManager.updateTaskList([]);
  backtestUIManager.updateTaskStats(0, '0小时');
  
  console.log('批量回测模块初始化完成');
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
 * 按顺序执行所有待执行的任务，显示进度，处理结果
 */
async function executeBacktestBatch() {
  try {
    const tasks = backtestTaskManager.getTasks();
    if (tasks.length === 0) {
      backtestUIManager.showError('没有待执行的任务');
      return;
    }

    // 禁用开始执行按钮
    backtestUIManager.elements.startExecutionBtn.disabled = true;

    // 加载保存的回测配置
    let savedParams = {
      initial_capital: 1000000,
      score_threshold: 60,
      buy_amount: 100000,
      max_daily_buys: 5,
      stop_loss: 0.05,
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
            stop_loss: (config.stop_loss || -5) / 100, // 转换为小数
            take_profit: (config.take_profit || 15) / 100, // 转换为小数
            max_hold_days: config.hold_period || 10
          };
        }
      }
    } catch (error) {
      console.error('加载回测配置失败:', error);
    }

    // 逐个执行任务
    for (let i = 0; i < tasks.length; i++) {
      const task = tasks[i];
      
      // 更新任务状态
      backtestTaskManager.updateTaskStatus(task.id, 'running');
      
      // 显示执行进度
      const progress = Math.round(((i + 1) / tasks.length) * 100);
      backtestUIManager.showProgress({
        strategyName: task.strategy_name,
        currentIndex: i + 1,
        totalCount: tasks.length,
        progress: progress,
        remainingTime: `${Math.round((tasks.length - i - 1) * 2.5)}小时`
      });

      let taskCompleted = false;
      let retryCount = 0;
      const maxRetries = 3;

      // 重试机制：如果任务失败，最多重试3次
      while (!taskCompleted && retryCount < maxRetries) {
        try {
          // 构建回测参数
          const backtestParams = {
            config_name: `${task.strategy_name}_${task.start_date}_${task.end_date}`,
            strategy_name: task.strategy_name,
            start_date: task.start_date,
            end_date: task.end_date,
            initial_capital: savedParams.initial_capital,
            score_threshold: savedParams.score_threshold,
            buy_amount: savedParams.buy_amount,
            max_daily_buys: savedParams.max_daily_buys,
            support_level_method: task.support_level_method,
            stop_loss: savedParams.stop_loss * 100, // 转换为百分比
            take_profit: savedParams.take_profit * 100, // 转换为百分比
            max_hold_days: savedParams.max_hold_days
          };

          // 执行回测
          console.log(`执行回测任务 ${i + 1}/${tasks.length}: ${task.strategy_name} (尝试 ${retryCount + 1}/${maxRetries})`);
          const response = await fetch('/api/trading/backtest/run', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify(backtestParams)
          });

          if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
          }

          const data = await response.json();
          if (data.success) {
            // 保存结果
            const result = data.data;
            backtestTaskManager.updateTaskStatus(task.id, 'completed', result);
            
            // 添加结果页签
            backtestUIManager.addResultTab(task, result);
            
            // 显示成功信息
            backtestUIManager.showInfo(`任务 ${i + 1}/${tasks.length} 执行完成: ${task.strategy_name}`, 'success');
            
            // 标记任务完成
            taskCompleted = true;
          } else {
            throw new Error(data.message || '执行回测失败');
          }
        } catch (error) {
          // 处理执行错误
          retryCount++;
          console.error(`执行任务 ${task.id} 失败 (尝试 ${retryCount}/${maxRetries}):`, error);
          
          if (retryCount >= maxRetries) {
            // 达到最大重试次数，标记任务失败
            backtestTaskManager.updateTaskStatus(task.id, 'failed');
            backtestUIManager.showError(`执行任务 ${i + 1} 失败: ${error.message}`);
            taskCompleted = true; // 退出重试循环，继续下一个任务
          } else {
            // 等待后重试
            console.log(`等待 5 秒后重试...`);
            await new Promise(resolve => setTimeout(resolve, 5000));
          }
        }
      }
    }

    // 执行完成后隐藏进度
    backtestUIManager.hideProgress();
    
    // 恢复按钮状态
    backtestUIManager.elements.startExecutionBtn.disabled = false;
    
    // 显示完成信息
    backtestUIManager.showInfo('批量回测执行完成', 'success');
    
  } catch (error) {
    console.error('批量回测执行失败:', error);
    backtestUIManager.showError(`批量回测执行失败: ${error.message}`);
    backtestUIManager.hideProgress();
    backtestUIManager.elements.startExecutionBtn.disabled = false;
  }
}
