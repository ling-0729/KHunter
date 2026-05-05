/**
 * 通用工具函数模块
 */

/**
 * 格式化成交量显示
 * @param {number} volume - 成交量
 * @returns {string} 格式化后的成交量
 */
export function formatVolume(volume) {
    if (volume >= 1e8) {
        return (volume / 1e8).toFixed(2) + '亿';
    } else if (volume >= 1e4) {
        return (volume / 1e4).toFixed(2) + '万';
    } else {
        return volume.toString();
    }
}

/**
 * 格式化日期
 * @param {string} dateStr - 日期字符串
 * @returns {string} 格式化后的日期
 */
export function formatDate(dateStr) {
    if (!dateStr) return '--';
    // 假设 dateStr 是 YYYYMMDD 格式
    if (dateStr.length === 8) {
        return `${dateStr.substring(0, 4)}-${dateStr.substring(4, 6)}-${dateStr.substring(6, 8)}`;
    }
    return dateStr;
}

/**
 * 格式化价格
 * @param {number} price - 价格
 * @returns {string} 格式化后的价格
 */
export function formatPrice(price) {
    if (price == null || isNaN(price)) return '--';
    return price.toFixed(2);
}

/**
 * 转义HTML字符
 * @param {string} text - 文本
 * @returns {string} 转义后的文本
 */
export function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
