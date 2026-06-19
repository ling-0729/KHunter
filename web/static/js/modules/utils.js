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
 * 格式化日期时间
 * @param {string} dateTimeStr - 日期时间字符串
 * @returns {string} 格式化后的日期时间
 */
export function formatDateTime(dateTimeStr) {
    if (!dateTimeStr) return '--';
    // 支持 YYYY-MM-DD HH:MM:SS 格式
    const match = dateTimeStr.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$/);
    if (match) {
        return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}`;
    }
    // 支持 YYYY-MM-DDTHH:MM:SS 格式
    const match2 = dateTimeStr.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
    if (match2) {
        return `${match2[1]}-${match2[2]}-${match2[3]} ${match2[4]}:${match2[5]}`;
    }
    return dateTimeStr;
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
