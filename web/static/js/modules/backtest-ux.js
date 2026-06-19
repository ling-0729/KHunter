/**
 * 批量回测用户体验优化模块
 * 包括加载动画、成功/失败提示、快捷键支持和本地存储
 */

// ==================== 加载动画 ====================

/**
 * 加载动画管理器
 * 显示和隐藏加载动画
 */
class LoadingAnimator {
  constructor() {
    // 加载状态
    this.isLoading = false;
    // 加载元素
    this.loadingElement = null;
    // 加载消息
    this.loadingMessage = '加载中...';
  }

  /**
   * 显示加载动画
   * @param {string} message - 加载消息
   */
  show(message = '加载中...') {
    // 如果已在加载，则不重复显示
    if (this.isLoading) {
      return;
    }

    // 检查document是否存在（Node.js环境中不存在）
    if (typeof document === 'undefined') {
      console.log(`[加载动画] 显示: ${message} (Node.js环境)`);
      this.isLoading = true;
      this.loadingMessage = message;
      // 在Node.js环境中，创建一个虚拟的加载元素用于测试
      this.loadingElement = { message };
      return;
    }

    // 标记为加载中
    this.isLoading = true;
    this.loadingMessage = message;

    // 创建加载元素
    this.loadingElement = document.createElement('div');
    this.loadingElement.className = 'loading-overlay';
    this.loadingElement.innerHTML = `
      <div class="loading-spinner">
        <div class="spinner"></div>
        <p>${message}</p>
      </div>
    `;

    // 添加样式
    this.addStyles();

    // 添加到页面
    document.body.appendChild(this.loadingElement);

    console.log(`[加载动画] 显示: ${message}`);
  }

  /**
   * 隐藏加载动画
   */
  hide() {
    // 如果未在加载，则不需要隐藏
    if (!this.isLoading) {
      return;
    }

    // 标记为未加载
    this.isLoading = false;

    // 检查document是否存在（Node.js环境中不存在）
    if (typeof document === 'undefined') {
      console.log('[加载动画] 隐藏 (Node.js环境)');
      this.loadingElement = null;
      return;
    }

    // 移除加载元素
    if (this.loadingElement) {
      // 检查是否是真实的DOM元素
      if (this.loadingElement.remove) {
        this.loadingElement.remove();
      }
      this.loadingElement = null;
    }

    console.log('[加载动画] 隐藏');
  }

  /**
   * 更新加载消息
   * @param {string} message - 新的加载消息
   */
  updateMessage(message) {
    // 更新消息
    this.loadingMessage = message;

    // 检查document是否存在（Node.js环境中不存在）
    if (typeof document === 'undefined') {
      console.log(`[加载动画] 更新消息: ${message} (Node.js环境)`);
      return;
    }

    // 如果加载元素存在，则更新文本
    if (this.loadingElement && this.loadingElement.querySelector) {
      const messageElement = this.loadingElement.querySelector('p');
      if (messageElement) {
        messageElement.textContent = message;
      }
    }

    console.log(`[加载动画] 更新消息: ${message}`);
  }

  /**
   * 添加样式
   */
  addStyles() {
    // 检查document是否存在（Node.js环境中不存在）
    if (typeof document === 'undefined') {
      return;
    }

    // 检查是否已添加样式
    if (document.getElementById('loading-animator-styles')) {
      return;
    }

    // 创建样式标签
    const styleTag = document.createElement('style');
    styleTag.id = 'loading-animator-styles';
    styleTag.textContent = `
      .loading-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
      }

      .loading-spinner {
        text-align: center;
        color: white;
      }

      .spinner {
        border: 4px solid rgba(255, 255, 255, 0.3);
        border-top: 4px solid white;
        border-radius: 50%;
        width: 40px;
        height: 40px;
        animation: spin 1s linear infinite;
        margin: 0 auto 16px;
      }

      @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
      }

      .loading-spinner p {
        margin: 0;
        font-size: 14px;
      }
    `;

    // 添加到页面
    document.head.appendChild(styleTag);
  }
}

// ==================== 成功/失败提示 ====================

/**
 * 提示通知管理器
 * 显示成功、失败、警告和信息提示
 */
class ToastNotification {
  constructor() {
    // 提示列表
    this.toasts = [];
    // 添加样式
    this.addStyles();
  }

  /**
   * 显示成功提示
   * @param {string} message - 提示消息
   * @param {number} duration - 显示时长（毫秒）
   */
  success(message, duration = 3000) {
    this.show(message, 'success', duration);
  }

  /**
   * 显示失败提示
   * @param {string} message - 提示消息
   * @param {number} duration - 显示时长（毫秒）
   */
  error(message, duration = 5000) {
    this.show(message, 'error', duration);
  }

  /**
   * 显示警告提示
   * @param {string} message - 提示消息
   * @param {number} duration - 显示时长（毫秒）
   */
  warning(message, duration = 4000) {
    this.show(message, 'warning', duration);
  }

  /**
   * 显示信息提示
   * @param {string} message - 提示消息
   * @param {number} duration - 显示时长（毫秒）
   */
  info(message, duration = 3000) {
    this.show(message, 'info', duration);
  }

  /**
   * 显示提示
   * @param {string} message - 提示消息
   * @param {string} type - 提示类型 (success, error, warning, info)
   * @param {number} duration - 显示时长（毫秒）
   */
  show(message, type = 'info', duration = 3000) {
    // 检查document是否存在（Node.js环境中不存在）
    if (typeof document === 'undefined') {
      console.log(`[提示] ${type.toUpperCase()}: ${message} (Node.js环境)`);
      // 在Node.js环境中，创建一个虚拟的toast对象用于测试
      const mockToast = { message, type };
      this.toasts.push(mockToast);
      return;
    }

    // 创建提示元素
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    // 添加到页面
    document.body.appendChild(toast);
    this.toasts.push(toast);

    // 自动关闭
    if (duration > 0) {
      setTimeout(() => {
        // 添加隐藏动画
        toast.classList.add('toast-hide');

        // 移除元素
        setTimeout(() => {
          toast.remove();
          this.toasts = this.toasts.filter(t => t !== toast);
        }, 300);
      }, duration);
    }

    console.log(`[提示] ${type.toUpperCase()}: ${message}`);
  }

  /**
   * 清空所有提示
   */
  clearAll() {
    // 检查document是否存在（Node.js环境中不存在）
    if (typeof document === 'undefined') {
      this.toasts = [];
      console.log('[提示] 清空所有提示 (Node.js环境)');
      return;
    }

    // 移除所有提示
    this.toasts.forEach(toast => {
      toast.remove();
    });
    this.toasts = [];

    console.log('[提示] 清空所有提示');
  }

  /**
   * 添加样式
   */
  addStyles() {
    // 检查document是否存在（Node.js环境中不存在）
    if (typeof document === 'undefined') {
      return;
    }

    // 检查是否已添加样式
    if (document.getElementById('toast-notification-styles')) {
      return;
    }

    // 创建样式标签
    const styleTag = document.createElement('style');
    styleTag.id = 'toast-notification-styles';
    styleTag.textContent = `
      .toast {
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 12px 16px;
        border-radius: 6px;
        font-size: 14px;
        z-index: 10000;
        animation: slideUp 0.3s ease-out;
        max-width: 400px;
        word-wrap: break-word;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
      }

      .toast-success {
        background: #dcfce7;
        color: #166534;
        border: 1px solid #86efac;
      }

      .toast-error {
        background: #fee2e2;
        color: #991b1b;
        border: 1px solid #fca5a5;
      }

      .toast-warning {
        background: #fef3c7;
        color: #92400e;
        border: 1px solid #fcd34d;
      }

      .toast-info {
        background: #dbeafe;
        color: #1e40af;
        border: 1px solid #93c5fd;
      }

      .toast-hide {
        animation: slideDown 0.3s ease-out;
      }

      @keyframes slideUp {
        from {
          transform: translateY(100px);
          opacity: 0;
        }
        to {
          transform: translateY(0);
          opacity: 1;
        }
      }

      @keyframes slideDown {
        from {
          transform: translateY(0);
          opacity: 1;
        }
        to {
          transform: translateY(100px);
          opacity: 0;
        }
      }
    `;

    // 添加到页面
    document.head.appendChild(styleTag);
  }
}

// ==================== 快捷键支持 ====================

/**
 * 键盘快捷键管理器
 * 支持常用快捷键操作
 */
class KeyboardShortcuts {
  constructor(executor, uiManager) {
    // 依赖注入
    this.executor = executor;
    this.uiManager = uiManager;

    // 快捷键映射
    this.shortcuts = {
      'Enter': () => this.startExecution(),
      ' ': () => this.togglePause(),
      'Escape': () => this.cancelExecution()
    };

    // 绑定键盘事件
    this.bindKeyboardEvents();

    console.log('键盘快捷键已初始化');
  }

  /**
   * 绑定键盘事件
   */
  bindKeyboardEvents() {
    // 检查document是否存在（Node.js环境中不存在）
    if (typeof document === 'undefined') {
      console.log('[快捷键] 键盘事件绑定跳过 (Node.js环境)');
      return;
    }

    // 监听键盘按下事件
    document.addEventListener('keydown', (event) => {
      // 获取按键名称
      const key = event.key;

      // 检查是否是快捷键
      if (this.shortcuts[key]) {
        // 防止默认行为
        event.preventDefault();
        // 执行快捷键
        this.shortcuts[key]();
      }
    });
  }

  /**
   * 开始执行
   */
  startExecution() {
    // 检查是否已在执行
    if (!this.executor.isRunning) {
      console.log('[快捷键] 开始执行 (Enter)');
      this.executor.startExecution();
    }
  }

  /**
   * 暂停/继续
   */
  togglePause() {
    // 检查是否在执行
    if (this.executor.isRunning) {
      if (this.executor.isPaused) {
        console.log('[快捷键] 继续执行 (Space)');
        this.executor.resumeExecution();
      } else {
        console.log('[快捷键] 暂停执行 (Space)');
        this.executor.pauseExecution();
      }
    }
  }

  /**
   * 取消执行
   */
  cancelExecution() {
    // 检查是否在执行
    if (this.executor.isRunning) {
      console.log('[快捷键] 取消执行 (Escape)');
      this.executor.cancelExecution();
    }
  }

  /**
   * 注册自定义快捷键
   * @param {string} key - 按键
   * @param {Function} callback - 回调函数
   */
  registerShortcut(key, callback) {
    // 注册快捷键
    this.shortcuts[key] = callback;
    console.log(`[快捷键] 注册快捷键: ${key}`);
  }

  /**
   * 注销快捷键
   * @param {string} key - 按键
   */
  unregisterShortcut(key) {
    // 删除快捷键
    delete this.shortcuts[key];
    console.log(`[快捷键] 注销快捷键: ${key}`);
  }
}

// ==================== 本地存储 ====================

/**
 * 本地存储管理器
 * 保存和加载任务列表
 */
class LocalStorageManager {
  constructor(storageKey = 'backtest-tasks') {
    // 存储键
    this.storageKey = storageKey;
    // 检查本地存储是否可用
    this.isAvailable = this.checkAvailability();

    console.log(`本地存储管理器已初始化 (可用: ${this.isAvailable})`);
  }

  /**
   * 检查本地存储是否可用
   * @returns {boolean}
   */
  checkAvailability() {
    try {
      // 检查localStorage是否存在（Node.js环境中不存在）
      if (typeof localStorage === 'undefined') {
        console.warn('本地存储不可用: localStorage未定义 (Node.js环境)');
        return false;
      }

      // 尝试写入和读取
      const testKey = '__test__';
      localStorage.setItem(testKey, 'test');
      localStorage.removeItem(testKey);
      return true;
    } catch (error) {
      console.warn('本地存储不可用:', error);
      return false;
    }
  }

  /**
   * 保存任务列表
   * @param {Array} tasks - 任务列表
   */
  saveTasks(tasks) {
    // 检查本地存储是否可用
    if (!this.isAvailable) {
      console.warn('本地存储不可用，无法保存任务');
      return false;
    }

    try {
      // 转换为JSON字符串
      const data = JSON.stringify(tasks);
      // 保存到本地存储
      localStorage.setItem(this.storageKey, data);
      console.log(`[本地存储] 已保存 ${tasks.length} 个任务`);
      return true;
    } catch (error) {
      console.error('[本地存储] 保存任务失败:', error);
      return false;
    }
  }

  /**
   * 加载任务列表
   * @returns {Array} 任务列表
   */
  loadTasks() {
    // 检查本地存储是否可用
    if (!this.isAvailable) {
      console.warn('本地存储不可用，无法加载任务');
      return [];
    }

    try {
      // 从本地存储读取
      const data = localStorage.getItem(this.storageKey);
      if (data) {
        // 解析JSON字符串
        const tasks = JSON.parse(data);
        console.log(`[本地存储] 已加载 ${tasks.length} 个任务`);
        return tasks;
      }
    } catch (error) {
      console.error('[本地存储] 加载任务失败:', error);
    }

    return [];
  }

  /**
   * 清空任务列表
   */
  clearTasks() {
    // 检查本地存储是否可用
    if (!this.isAvailable) {
      console.warn('本地存储不可用，无法清空任务');
      return false;
    }

    try {
      // 删除本地存储中的数据
      localStorage.removeItem(this.storageKey);
      console.log('[本地存储] 已清空任务');
      return true;
    } catch (error) {
      console.error('[本地存储] 清空任务失败:', error);
      return false;
    }
  }

  /**
   * 检查是否有保存的任务
   * @returns {boolean}
   */
  hasSavedTasks() {
    // 检查本地存储是否可用
    if (!this.isAvailable) {
      return false;
    }

    // 检查是否存在数据
    return localStorage.getItem(this.storageKey) !== null;
  }

  /**
   * 获取保存的任务数量
   * @returns {number}
   */
  getSavedTaskCount() {
    // 加载任务列表
    const tasks = this.loadTasks();
    return tasks.length;
  }

  /**
   * 保存单个任务
   * @param {Object} task - 任务对象
   */
  saveTask(task) {
    // 加载现有任务
    const tasks = this.loadTasks();
    // 添加新任务
    tasks.push(task);
    // 保存任务列表
    return this.saveTasks(tasks);
  }

  /**
   * 删除单个任务
   * @param {number} taskId - 任务ID
   */
  deleteTask(taskId) {
    // 加载现有任务
    const tasks = this.loadTasks();
    // 过滤任务
    const filteredTasks = tasks.filter(t => t.id !== taskId);
    // 保存任务列表
    return this.saveTasks(filteredTasks);
  }
}

// ==================== 导出 ====================

// 导出模块
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    LoadingAnimator,
    ToastNotification,
    KeyboardShortcuts,
    LocalStorageManager
  };
}
