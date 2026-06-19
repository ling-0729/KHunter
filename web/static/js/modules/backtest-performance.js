/**
 * 批量回测性能优化模块
 * 包括虚拟滚动、图表懒加载、内存管理和网络请求优化
 */

// ==================== 虚拟滚动 ====================

/**
 * 虚拟滚动器
 * 只渲染可见的任务行，提高列表性能
 */
class VirtualScroller {
  constructor(container, items, itemHeight = 50, visibleCount = 10) {
    // 容器元素
    this.container = container;
    // 所有项目
    this.items = items;
    // 每个项目的高度
    this.itemHeight = itemHeight;
    // 可见项目数量
    this.visibleCount = visibleCount;
    
    // 滚动位置
    this.scrollTop = 0;
    // 可见范围
    this.startIndex = 0;
    this.endIndex = visibleCount;
    
    // 绑定滚动事件
    this.onScroll = this.onScroll.bind(this);
  }

  /**
   * 计算可见范围
   * @returns {Object} 包含start和end的范围对象
   */
  calculateVisibleRange() {
    // 计算起始索引
    this.startIndex = Math.floor(this.scrollTop / this.itemHeight);
    // 计算结束索引
    this.endIndex = this.startIndex + this.visibleCount;
    
    return {
      start: this.startIndex,
      end: Math.min(this.endIndex, this.items.length)
    };
  }

  /**
   * 渲染可见项
   * @param {Function} renderItemFn - 渲染单个项的函数
   */
  render(renderItemFn) {
    // 计算可见范围
    const range = this.calculateVisibleRange();
    // 获取可见项
    const visibleItems = this.items.slice(range.start, range.end);
    
    // 清空容器
    this.container.innerHTML = '';
    
    // 渲染可见项
    visibleItems.forEach((item, index) => {
      const actualIndex = range.start + index;
      const element = renderItemFn(item, actualIndex);
      this.container.appendChild(element);
    });
  }

  /**
   * 处理滚动事件
   * @param {Event} event - 滚动事件
   */
  onScroll(event) {
    // 更新滚动位置
    this.scrollTop = event.target.scrollTop;
    // 重新渲染
    this.render(this.renderItemFn);
  }

  /**
   * 启用虚拟滚动
   * @param {HTMLElement} scrollContainer - 滚动容器
   * @param {Function} renderItemFn - 渲染单个项的函数
   */
  enable(scrollContainer, renderItemFn) {
    // 保存渲染函数
    this.renderItemFn = renderItemFn;
    // 添加滚动事件监听
    scrollContainer.addEventListener('scroll', this.onScroll);
    // 初始渲染
    this.render(renderItemFn);
  }

  /**
   * 禁用虚拟滚动
   * @param {HTMLElement} scrollContainer - 滚动容器
   */
  disable(scrollContainer) {
    // 移除滚动事件监听
    scrollContainer.removeEventListener('scroll', this.onScroll);
  }

  /**
   * 更新项目列表
   * @param {Array} items - 新的项目列表
   */
  updateItems(items) {
    // 更新项目列表
    this.items = items;
    // 重新渲染
    if (this.renderItemFn) {
      this.render(this.renderItemFn);
    }
  }
}

// ==================== 图表懒加载 ====================

/**
 * 图表懒加载器
 * 只在图表可见时才渲染
 */
class LazyChartLoader {
  constructor(options = {}) {
    // 配置选项
    this.options = {
      threshold: options.threshold || 0.1,
      rootMargin: options.rootMargin || '50px'
    };
    
    // 图表映射
    this.charts = new Map();
    
    // 创建 IntersectionObserver（如果可用）
    if (typeof IntersectionObserver !== 'undefined') {
      this.observer = new IntersectionObserver(
        entries => this.onIntersection(entries),
        {
          threshold: this.options.threshold,
          rootMargin: this.options.rootMargin
        }
      );
    } else {
      // Node.js 环境中不可用
      this.observer = null;
    }
  }

  /**
   * 注册图表
   * @param {string} chartId - 图表ID
   * @param {HTMLElement} chartElement - 图表元素
   * @param {Function} renderFn - 渲染函数
   */
  registerChart(chartId, chartElement, renderFn) {
    // 保存图表信息
    this.charts.set(chartId, {
      element: chartElement,
      renderFn: renderFn,
      rendered: false
    });
    
    // 观察元素（如果 observer 可用）
    if (this.observer) {
      this.observer.observe(chartElement);
    }
  }

  /**
   * 处理可见性变化
   * @param {Array} entries - IntersectionObserver 条目
   */
  onIntersection(entries) {
    entries.forEach(entry => {
      // 检查元素是否可见
      if (entry.isIntersecting) {
        // 获取图表ID
        const chartId = entry.target.id;
        const chart = this.charts.get(chartId);
        
        // 如果图表未渲染，则渲染
        if (chart && !chart.rendered) {
          // 使用 requestIdleCallback 延迟渲染，避免阻塞主线程
          if (typeof requestIdleCallback !== 'undefined') {
            requestIdleCallback(() => {
              chart.renderFn();
              chart.rendered = true;
            });
          } else {
            // 降级方案：使用 setTimeout
            setTimeout(() => {
              chart.renderFn();
              chart.rendered = true;
            }, 0);
          }
        }
      }
    });
  }

  /**
   * 清理资源
   */
  destroy() {
    // 停止观察（如果 observer 可用）
    if (this.observer) {
      this.observer.disconnect();
    }
    // 清空图表映射
    this.charts.clear();
  }
}

// ==================== 内存管理 ====================

/**
 * 内存管理器
 * 使用 LRU 缓存策略管理内存
 */
class MemoryManager {
  constructor(maxSize = 100) {
    // 最大缓存大小
    this.maxSize = maxSize;
    // 缓存映射
    this.cache = new Map();
  }

  /**
   * 添加数据到缓存
   * @param {string} key - 缓存键
   * @param {*} value - 缓存值
   */
  set(key, value) {
    // 如果键已存在，先删除（保持 LRU 顺序）
    if (this.cache.has(key)) {
      this.cache.delete(key);
    }
    
    // 如果缓存满了，删除最旧的数据
    if (this.cache.size >= this.maxSize) {
      // 获取第一个键（最旧的）
      const firstKey = this.cache.keys().next().value;
      this.cache.delete(firstKey);
    }
    
    // 添加新数据
    this.cache.set(key, value);
  }

  /**
   * 获取缓存数据
   * @param {string} key - 缓存键
   * @returns {*} 缓存值
   */
  get(key) {
    // 如果键存在，更新其位置（LRU）
    if (this.cache.has(key)) {
      const value = this.cache.get(key);
      // 删除并重新添加，使其成为最新的
      this.cache.delete(key);
      this.cache.set(key, value);
      return value;
    }
    return undefined;
  }

  /**
   * 检查键是否存在
   * @param {string} key - 缓存键
   * @returns {boolean}
   */
  has(key) {
    return this.cache.has(key);
  }

  /**
   * 删除缓存数据
   * @param {string} key - 缓存键
   */
  delete(key) {
    this.cache.delete(key);
  }

  /**
   * 清理缓存
   */
  clear() {
    this.cache.clear();
  }

  /**
   * 获取缓存大小
   * @returns {number}
   */
  size() {
    return this.cache.size;
  }

  /**
   * 获取缓存使用率
   * @returns {number} 0-100
   */
  getUsagePercent() {
    return (this.cache.size / this.maxSize) * 100;
  }
}

// ==================== 网络请求优化 ====================

/**
 * 请求优化器
 * 实现请求缓存和去重
 */
class RequestOptimizer {
  constructor(options = {}) {
    // 配置选项
    this.options = {
      cacheTimeout: options.cacheTimeout || 5 * 60 * 1000, // 5分钟
      maxCacheSize: options.maxCacheSize || 50
    };
    
    // 请求缓存
    this.requestCache = new Map();
    // 待处理请求
    this.pendingRequests = new Map();
    // 缓存时间戳
    this.cacheTimestamps = new Map();
  }

  /**
   * 生成缓存键
   * @param {string} url - 请求URL
   * @param {Object} options - 请求选项
   * @returns {string} 缓存键
   */
  generateCacheKey(url, options = {}) {
    // 只使用 method 和 body 作为缓存键的一部分
    const method = options.method || 'GET';
    const body = options.body ? JSON.stringify(options.body) : '';
    return `${method}:${url}:${body}`;
  }

  /**
   * 检查缓存是否过期
   * @param {string} cacheKey - 缓存键
   * @returns {boolean}
   */
  isCacheExpired(cacheKey) {
    // 获取缓存时间戳
    const timestamp = this.cacheTimestamps.get(cacheKey);
    if (!timestamp) {
      return true;
    }
    
    // 检查是否超过超时时间
    return Date.now() - timestamp > this.options.cacheTimeout;
  }

  /**
   * 带缓存的请求
   * @param {string} url - 请求URL
   * @param {Object} options - 请求选项
   * @returns {Promise} 响应数据
   */
  async fetchWithCache(url, options = {}) {
    // 生成缓存键
    const cacheKey = this.generateCacheKey(url, options);
    
    // 检查缓存是否有效
    if (this.requestCache.has(cacheKey) && !this.isCacheExpired(cacheKey)) {
      console.log(`[缓存命中] ${url}`);
      return this.requestCache.get(cacheKey);
    }

    // 检查是否有相同的待处理请求
    if (this.pendingRequests.has(cacheKey)) {
      console.log(`[请求去重] ${url}`);
      return this.pendingRequests.get(cacheKey);
    }

    // 发送新请求
    console.log(`[新请求] ${url}`);
    const promise = fetch(url, options)
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        // 缓存结果
        this.requestCache.set(cacheKey, data);
        this.cacheTimestamps.set(cacheKey, Date.now());
        
        // 清理待处理请求
        this.pendingRequests.delete(cacheKey);
        
        // 检查缓存大小
        if (this.requestCache.size > this.options.maxCacheSize) {
          // 删除最旧的缓存
          const firstKey = this.requestCache.keys().next().value;
          this.requestCache.delete(firstKey);
          this.cacheTimestamps.delete(firstKey);
        }
        
        return data;
      })
      .catch(error => {
        // 清理待处理请求
        this.pendingRequests.delete(cacheKey);
        throw error;
      });

    // 记录待处理请求
    this.pendingRequests.set(cacheKey, promise);
    return promise;
  }

  /**
   * 清理缓存
   */
  clearCache() {
    this.requestCache.clear();
    this.cacheTimestamps.clear();
  }

  /**
   * 获取缓存统计
   * @returns {Object} 统计信息
   */
  getStats() {
    return {
      cacheSize: this.requestCache.size,
      pendingRequests: this.pendingRequests.size,
      maxCacheSize: this.options.maxCacheSize
    };
  }
}

// ==================== 性能监控 ====================

/**
 * 性能监控器
 * 监控和记录性能指标
 */
class PerformanceMonitor {
  constructor() {
    // 性能指标
    this.metrics = {
      renderTime: [],
      networkTime: [],
      memoryUsage: []
    };
  }

  /**
   * 记录渲染时间
   * @param {number} duration - 渲染耗时（毫秒）
   */
  recordRenderTime(duration) {
    this.metrics.renderTime.push(duration);
    
    // 只保留最近100条记录
    if (this.metrics.renderTime.length > 100) {
      this.metrics.renderTime.shift();
    }
  }

  /**
   * 记录网络请求时间
   * @param {number} duration - 请求耗时（毫秒）
   */
  recordNetworkTime(duration) {
    this.metrics.networkTime.push(duration);
    
    // 只保留最近100条记录
    if (this.metrics.networkTime.length > 100) {
      this.metrics.networkTime.shift();
    }
  }

  /**
   * 记录内存使用
   * @param {number} usage - 内存使用（字节）
   */
  recordMemoryUsage(usage) {
    this.metrics.memoryUsage.push(usage);
    
    // 只保留最近100条记录
    if (this.metrics.memoryUsage.length > 100) {
      this.metrics.memoryUsage.shift();
    }
  }

  /**
   * 获取平均渲染时间
   * @returns {number}
   */
  getAverageRenderTime() {
    if (this.metrics.renderTime.length === 0) return 0;
    const sum = this.metrics.renderTime.reduce((a, b) => a + b, 0);
    return sum / this.metrics.renderTime.length;
  }

  /**
   * 获取平均网络请求时间
   * @returns {number}
   */
  getAverageNetworkTime() {
    if (this.metrics.networkTime.length === 0) return 0;
    const sum = this.metrics.networkTime.reduce((a, b) => a + b, 0);
    return sum / this.metrics.networkTime.length;
  }

  /**
   * 获取平均内存使用
   * @returns {number}
   */
  getAverageMemoryUsage() {
    if (this.metrics.memoryUsage.length === 0) return 0;
    const sum = this.metrics.memoryUsage.reduce((a, b) => a + b, 0);
    return sum / this.metrics.memoryUsage.length;
  }

  /**
   * 获取性能报告
   * @returns {Object}
   */
  getReport() {
    return {
      averageRenderTime: this.getAverageRenderTime().toFixed(2),
      averageNetworkTime: this.getAverageNetworkTime().toFixed(2),
      averageMemoryUsage: (this.getAverageMemoryUsage() / 1024 / 1024).toFixed(2),
      recordCount: {
        renderTime: this.metrics.renderTime.length,
        networkTime: this.metrics.networkTime.length,
        memoryUsage: this.metrics.memoryUsage.length
      }
    };
  }
}

// ==================== 导出 ====================

// 导出模块
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    VirtualScroller,
    LazyChartLoader,
    MemoryManager,
    RequestOptimizer,
    PerformanceMonitor
  };
}
