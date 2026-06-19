/**
 * 批量回测工具函数模块
 * 提取公共工具函数，消除代码重复，提高代码复用性
 */

/**
 * 批量回测工具类
 * 包含日期格式化、百分比格式化、货币格式化、延迟执行、重试执行、深拷贝、对象合并等工具函数
 */
class BacktestUtils {
  /**
   * 格式化日期为 YYYY-MM-DD 格式
   * @param {Date|string} date - 日期对象或日期字符串
   * @returns {string} 格式化后的日期字符串
   */
  static formatDate(date) {
    // 如果是字符串，直接返回
    if (typeof date === 'string') {
      return date;
    }
    
    // 如果是Date对象，转换为YYYY-MM-DD格式
    if (date instanceof Date) {
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const day = String(date.getDate()).padStart(2, '0');
      return `${year}-${month}-${day}`;
    }
    
    // 其他情况返回空字符串
    return '';
  }

  /**
   * 格式化百分比
   * @param {number} value - 百分比值（0-1之间的小数）
   * @param {number} decimals - 小数位数，默认2位
   * @returns {string} 格式化后的百分比字符串
   */
  static formatPercent(value, decimals = 2) {
    // 验证输入
    if (typeof value !== 'number' || isNaN(value)) {
      return '0.00%';
    }
    
    // 转换为百分比并格式化
    const percent = (value * 100).toFixed(decimals);
    return `${percent}%`;
  }

  /**
   * 格式化货币
   * @param {number} value - 货币值
   * @param {number} decimals - 小数位数，默认2位
   * @returns {string} 格式化后的货币字符串
   */
  static formatCurrency(value, decimals = 2) {
    // 验证输入
    if (typeof value !== 'number' || isNaN(value)) {
      return '0.00';
    }
    
    // 格式化为指定小数位数
    return value.toFixed(decimals);
  }

  /**
   * 延迟执行
   * @param {number} ms - 延迟毫秒数
   * @returns {Promise} 延迟Promise
   */
  static delay(ms) {
    // 验证输入
    if (typeof ms !== 'number' || ms < 0) {
      ms = 0;
    }
    
    // 返回延迟Promise
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * 重试执行异步函数
   * @param {Function} fn - 异步函数
   * @param {number} maxRetries - 最大重试次数，默认3次
   * @param {number} delayMs - 初始延迟毫秒数，默认1000ms
   * @returns {Promise} 执行结果
   */
  static async retry(fn, maxRetries = 3, delayMs = 1000) {
    // 验证输入
    if (typeof fn !== 'function') {
      throw new Error('fn must be a function');
    }
    
    if (typeof maxRetries !== 'number' || maxRetries < 1) {
      maxRetries = 3;
    }
    
    if (typeof delayMs !== 'number' || delayMs < 0) {
      delayMs = 1000;
    }
    
    // 重试循环
    for (let i = 0; i < maxRetries; i++) {
      try {
        // 执行函数
        return await fn();
      } catch (error) {
        // 如果是最后一次重试，抛出错误
        if (i === maxRetries - 1) {
          throw error;
        }
        
        // 计算延迟时间（指数退避）
        const delay = delayMs * Math.pow(2, i);
        
        // 延迟后重试
        await this.delay(delay);
      }
    }
  }

  /**
   * 深拷贝对象
   * @param {*} obj - 要拷贝的对象
   * @returns {*} 拷贝后的对象
   */
  static deepClone(obj) {
    // 处理基本类型
    if (obj === null || typeof obj !== 'object') {
      return obj;
    }
    
    // 处理Date对象
    if (obj instanceof Date) {
      return new Date(obj.getTime());
    }
    
    // 处理Array
    if (Array.isArray(obj)) {
      return obj.map(item => this.deepClone(item));
    }
    
    // 处理Object
    if (obj instanceof Object) {
      const cloned = {};
      for (const key in obj) {
        if (obj.hasOwnProperty(key)) {
          cloned[key] = this.deepClone(obj[key]);
        }
      }
      return cloned;
    }
    
    // 其他情况直接返回
    return obj;
  }

  /**
   * 合并对象
   * @param {Object} target - 目标对象
   * @param {Object} source - 源对象
   * @returns {Object} 合并后的对象
   */
  static merge(target, source) {
    // 验证输入
    if (typeof target !== 'object' || target === null) {
      target = {};
    }
    
    if (typeof source !== 'object' || source === null) {
      return target;
    }
    
    // 合并对象
    return Object.assign({}, target, source);
  }

  /**
   * 验证日期范围
   * @param {string} startDate - 开始日期（YYYY-MM-DD格式）
   * @param {string} endDate - 结束日期（YYYY-MM-DD格式）
   * @returns {boolean} 日期范围是否有效
   */
  static isValidDateRange(startDate, endDate) {
    // 验证日期格式
    const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
    if (!dateRegex.test(startDate) || !dateRegex.test(endDate)) {
      return false;
    }
    
    // 比较日期
    return startDate <= endDate;
  }

  /**
   * 计算两个日期之间的天数
   * @param {string} startDate - 开始日期（YYYY-MM-DD格式）
   * @param {string} endDate - 结束日期（YYYY-MM-DD格式）
   * @returns {number} 天数
   */
  static daysBetween(startDate, endDate) {
    // 解析日期
    const start = new Date(startDate);
    const end = new Date(endDate);
    
    // 计算天数
    const diffTime = Math.abs(end - start);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    
    return diffDays;
  }

  /**
   * 生成唯一ID
   * @returns {string} 唯一ID
   */
  static generateId() {
    // 使用时间戳和随机数生成唯一ID
    return `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * 检查对象是否为空
   * @param {Object} obj - 要检查的对象
   * @returns {boolean} 对象是否为空
   */
  static isEmpty(obj) {
    // 检查null和undefined
    if (obj === null || obj === undefined) {
      return true;
    }
    
    // 检查Object
    if (typeof obj === 'object') {
      return Object.keys(obj).length === 0;
    }
    
    // 检查String
    if (typeof obj === 'string') {
      return obj.trim().length === 0;
    }
    
    // 其他情况返回false
    return false;
  }

  /**
   * 获取对象的值
   * @param {Object} obj - 对象
   * @param {string} path - 属性路径（支持点号分隔，如 'a.b.c'）
   * @param {*} defaultValue - 默认值
   * @returns {*} 属性值或默认值
   */
  static getValueByPath(obj, path, defaultValue = undefined) {
    // 验证输入
    if (typeof obj !== 'object' || obj === null) {
      return defaultValue;
    }
    
    if (typeof path !== 'string') {
      return defaultValue;
    }
    
    // 分割路径
    const keys = path.split('.');
    
    // 逐级获取值
    let value = obj;
    for (const key of keys) {
      if (typeof value === 'object' && value !== null && key in value) {
        value = value[key];
      } else {
        return defaultValue;
      }
    }
    
    return value;
  }

  /**
   * 设置对象的值
   * @param {Object} obj - 对象
   * @param {string} path - 属性路径（支持点号分隔，如 'a.b.c'）
   * @param {*} value - 要设置的值
   * @returns {Object} 修改后的对象
   */
  static setValueByPath(obj, path, value) {
    // 验证输入
    if (typeof obj !== 'object' || obj === null) {
      return obj;
    }
    
    if (typeof path !== 'string') {
      return obj;
    }
    
    // 分割路径
    const keys = path.split('.');
    
    // 逐级设置值
    let current = obj;
    for (let i = 0; i < keys.length - 1; i++) {
      const key = keys[i];
      if (!(key in current) || typeof current[key] !== 'object') {
        current[key] = {};
      }
      current = current[key];
    }
    
    // 设置最后一个键的值
    current[keys[keys.length - 1]] = value;
    
    return obj;
  }
}

// 导出工具类
if (typeof module !== 'undefined' && module.exports) {
  module.exports = BacktestUtils;
}
