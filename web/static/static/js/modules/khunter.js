/**
 * KHunter 狩猎场 - 前端交互脚本
 * 负责页面初始化、数据绑定、事件处理等
 */

// 全局变量
let totalCount = 0;
let currentResults = [];

/**
 * 页面初始化
 */
function initPage() {
    // 1. 设置默认日期（当前交易日期）
    const today = new Date();
    const dateStr = formatDate(today);
    document.getElementById('hunting-date').value = dateStr;
    
    // 2. 设置默认跟踪天数
    document.getElementById('tracking-days').value = 5;
    
    // 3. 绑定事件监听器
    document.getElementById('calculate-btn').addEventListener('click', calculate);
    document.getElementById('save-btn').addEventListener('click', saveResults);
    
    // 4. 绑定模态窗口关闭事件
    document.getElementById('stock-detail-modal').addEventListener('click', function(e) {
        if (e.target === this) {
            closeStockDetailModal();
        }
    });
    
    document.getElementById('score-detail-modal').addEventListener('click', function(e) {
        if (e.target === this) {
            closeScoreDetailModal();
        }
    });
    
    // 5. 绑定表格行点击事件（事件委托）
    document.getElementById('results-tbody').addEventListener('click', handleTableClick);
}

/**
 * 格式化日期为 YYYY-MM-DD
 */
function formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

/**
 * 计算狩猎场数据
 */
function calculate() {
    // 1. 获取参数
    const huntingDate = document.getElementById('hunting-date').value;
    const trackingDays = parseInt(document.getElementById('tracking-days').value);
    
    // 2. 验证参数
    if (!huntingDate) {
        showAlert('请选择狩猎日期', 'error');
        return;
    }
    
    if (!trackingDays || trackingDays < 1 || trackingDays > 365) {
        showAlert('跟踪天数必须在 1-365 之间', 'error');
        return;
    }
    
    // 3. 显示加载状态
    showLoading(true);
    disableControls(true);
    
    // 4. 调用 API
    fetch('/api/khunter/calculate', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            hunting_date: huntingDate,
            tracking_days: trackingDays
        })
    })
    .then(response => response.json())
    .then(data => {
        // 5. 处理响应
        if (data.success) {
            // 保存结果
            currentResults = data.data.results;
            totalCount = data.data.total_count;
            
            // 绑定数据
            bindTableData(currentResults);
            
            // 更新统计信息
            updateStats(data.data);
            
            // 显示保存按钮
            document.getElementById('save-btn').style.display = 'inline-flex';
            
            // 显示成功提示
            showAlert(`计算成功！找到 ${totalCount} 只符合买点的股票`, 'success');
        } else {
            showAlert(data.message || '计算失败', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showAlert('网络错误，请稍后重试', 'error');
    })
    .finally(() => {
        // 6. 隐藏加载状态
        showLoading(false);
        disableControls(false);
    });
}

/**
 * 绑定表格数据
 */
function bindTableData(results) {
    const tbody = document.getElementById('results-tbody');
    
    // 1. 清空表格
    tbody.innerHTML = '';
    
    // 2. 如果没有数据，显示占位符
    if (!results || results.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="placeholder">未找到符合条件的数据</td></tr>';
        return;
    }
    
    // 3. 遍历结果，创建表格行
    results.forEach(item => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><a class="stock-link" onclick="openStockDetail('${item.stock_code}')">${item.stock_code}</a></td>
            <td>${item.stock_name}</td>
            <td>${item.industry || '-'}</td>
            <td>${item.sector || '-'}</td>
            <td>${item.support_level.toFixed(2)}</td>
            <td>${item.current_price.toFixed(2)}</td>
            <td>${item.price_diff.toFixed(2)}</td>
            <td>${item.price_diff_percent.toFixed(2)}%</td>
            <td>${item.strategy_name}</td>
            <td>${item.score_date || '-'}</td>
            <td><a class="score-link" onclick="openScoreDetail('${item.stock_code}', '${item.score_date}')">${item.score.toFixed(2)}</a></td>
        `;
        tbody.appendChild(row);
    });
}

/**
 * 更新统计信息
 */
function updateStats(data) {
    // 1. 更新总数
    document.getElementById('total-count').textContent = data.total_count;
    
    // 2. 更新计算耗时
    document.getElementById('calculation-time').textContent = `${data.calculation_time.toFixed(2)}s`;
    
    // 3. 更新缓存状态
    const cacheStatus = data.from_cache ? '✅ 从缓存加载' : '❌ 新计算';
    document.getElementById('cache-status').textContent = cacheStatus;
    
    // 4. 更新结果摘要
    const summary = `共 ${data.total_count} 只股票，耗时 ${data.calculation_time.toFixed(2)}s`;
    document.getElementById('result-summary').textContent = summary;
    

}



/**
 * 保存计算结果
 */
function saveResults() {
    // 1. 获取参数
    const huntingDate = document.getElementById('hunting-date').value;
    const trackingDays = parseInt(document.getElementById('tracking-days').value);
    
    // 2. 显示加载状态
    showLoading(true);
    disableControls(true);
    
    // 3. 调用保存 API
    fetch('/api/khunter/save', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            hunting_date: huntingDate,
            tracking_days: trackingDays
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 4. 保存成功后，更新缓存状态
            updateCacheStatus(huntingDate, true);
            showAlert(`保存成功！已保存 ${data.data.saved_count} 条记录`, 'success');
        } else {
            showAlert(data.message || '保存失败', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showAlert('网络错误，请稍后重试', 'error');
    })
    .finally(() => {
        showLoading(false);
        disableControls(false);
    });
}

/**
 * 更新缓存状态
 */
function updateCacheStatus(huntingDate, hasCache) {
    // 1. 更新缓存状态显示
    const cacheStatus = hasCache ? '✅ 从缓存加载' : '❌ 新计算';
    document.getElementById('cache-status').textContent = cacheStatus;
    
    // 2. 记录日志
    console.log(`缓存状态已更新: ${huntingDate} - ${cacheStatus}`);
}

/**
 * 打开股票详情模态窗口
 */
function openStockDetail(stockCode) {
    // 1. 调用现有的 viewStockDetail 函数
    // 该函数会加载股票详情并显示在模态窗口中
    if (typeof window.viewStockDetail === 'function') {
        window.viewStockDetail(stockCode);
    } else {
        // 2. 如果 viewStockDetail 不可用，显示错误提示
        showAlert('无法加载股票详情，请稍后重试', 'error');
        logger.error('viewStockDetail 函数不可用');
    }
}

/**
 * 关闭股票详情模态窗口
 */
function closeStockDetailModal() {
    document.getElementById('stock-detail-modal').style.display = 'none';
}

/**
 * 打开评分详情模态窗口
 */
function openScoreDetail(stockCode, scoreDate) {
    // 1. 验证参数
    if (!scoreDate) {
        showAlert('无法获取评分日期，请稍后重试', 'error');
        return;
    }
    
    // 2. 调用"我的金股"的评分 API
    // 将日期格式从 YYYY-MM-DD 转换为 YYYYMMDD
    const dateParam = scoreDate.replace(/-/g, '');
    
    if (typeof window.showScoreDetail === 'function') {
        // 3. 调用现有的 showScoreDetail 函数
        window.showScoreDetail(stockCode, dateParam);
    } else {
        // 4. 如果 showScoreDetail 不可用，显示错误提示
        showAlert('无法加载评分详情，请稍后重试', 'error');
        console.error('showScoreDetail 函数不可用');
    }
}

/**
 * 关闭评分详情模态窗口
 */
function closeScoreDetailModal() {
    document.getElementById('score-detail-modal').style.display = 'none';
}

/**
 * 处理表格行点击事件
 */
function handleTableClick(e) {
    // 1. 检查是否点击了链接
    if (e.target.classList.contains('stock-link')) {
        e.preventDefault();
        const stockCode = e.target.textContent;
        openStockDetail(stockCode);
    } else if (e.target.classList.contains('score-link')) {
        e.preventDefault();
        // 获取该行的评分日期（第10列，index 9）
        const row = e.target.closest('tr');
        const scoreDate = row.cells[9].textContent.trim();
        const stockCode = row.cells[0].textContent.trim();
        openScoreDetail(stockCode, scoreDate);
    }
}

/**
 * 显示/隐藏加载状态
 */
function showLoading(show) {
    const indicator = document.getElementById('loading-indicator');
    if (show) {
        indicator.style.display = 'flex';
    } else {
        indicator.style.display = 'none';
    }
}

/**
 * 禁用/启用控制区
 */
function disableControls(disable) {
    document.getElementById('hunting-date').disabled = disable;
    document.getElementById('tracking-days').disabled = disable;
    document.getElementById('calculate-btn').disabled = disable;
    document.getElementById('save-btn').disabled = disable;
}

/**
 * 显示提示信息
 */
function showAlert(message, type = 'info') {
    // 1. 创建提示元素
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.textContent = message;
    alert.style.position = 'fixed';
    alert.style.top = '20px';
    alert.style.right = '20px';
    alert.style.zIndex = '2000';
    alert.style.maxWidth = '400px';
    
    // 2. 添加到页面
    document.body.appendChild(alert);
    
    // 3. 3秒后自动移除
    setTimeout(() => {
        alert.remove();
    }, 3000);
}

/**
 * 页面加载完成后初始化
 */
document.addEventListener('DOMContentLoaded', initPage);

/**
 * 导出 initKHunterPage 函数供 navigation.js 调用
 */
export function initKHunterPage() {
    // 如果页面已经初始化过，直接返回
    if (document.getElementById('hunting-date').value) {
        return;
    }
    // 否则调用 initPage 进行初始化
    initPage();
}

/**
 * 初始化狩猎跟踪页面
 */
export function initKHunterTrackPage() {
    console.log('初始化狩猎跟踪页面');
    // 加载可用的狩猎日期
    loadKHunterDates();
    // 重置结果区域
    document.getElementById('khunter-track-result').innerHTML = '';
}

/**
 * 加载狩猎可用日期
 */
export async function loadKHunterDates() {
    try {
        // 1. 计算昨天的日期
        const today = new Date();
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        
        // 2. 格式化日期为 YYYY-MM-DD
        const year = yesterday.getFullYear();
        const month = String(yesterday.getMonth() + 1).padStart(2, '0');
        const day = String(yesterday.getDate()).padStart(2, '0');
        const yesterdayStr = `${year}-${month}-${day}`;
        
        // 3. 设置默认日期为昨天
        const dateInput = document.getElementById('khunter-track-date');
        if (dateInput) {
            dateInput.value = yesterdayStr;
        }
    } catch (error) {
        console.error('加载狩猎日期失败:', error);
    }
}

/**
 * 执行狩猎跟踪
 */
export async function trackKHunter() {
    // 1. 获取日期输入框和结果容器
    const dateInput = document.getElementById('khunter-track-date');
    const resultContainer = document.getElementById('khunter-track-result');
    
    if (!dateInput || !resultContainer) return;
    
    // 2. 获取选择的日期
    const huntingDate = dateInput.value;
    if (!huntingDate) {
        alert('请选择狩猎日期');
        return;
    }
    
    // 3. 显示加载状态
    resultContainer.innerHTML = '<p class="loading">正在跟踪狩猎数据，请稍候...</p>';
    
    try {
        // 4. 调用API获取跟踪数据
        const response = await fetch(`/api/khunter/track?hunting_date=${huntingDate}`);
        const result = await response.json();
        
        // 5. 处理响应
        if (result.success) {
            renderKHunterTrackingResult(result.data, resultContainer, huntingDate);
        } else {
            resultContainer.innerHTML = `<p class="loading text-danger">跟踪失败: ${result.message}</p>`;
        }
    } catch (error) {
        console.error('狩猎跟踪异常:', error);
        resultContainer.innerHTML = `<p class="loading text-danger">跟踪失败: ${error.message}</p>`;
    }
}

/**
 * 渲染狩猎跟踪结果
 * @param {Array} data - 跟踪数据
 * @param {HTMLElement} container - 结果容器
 * @param {string} huntingDate - 狩猎日期
 */
export function renderKHunterTrackingResult(data, container, huntingDate) {
    // 1. 检查数据是否为空
    if (!data || data.length === 0) {
        container.innerHTML = '<p class="text-muted">暂无跟踪数据</p>';
        return;
    }
    
    // 2. 生成表格HTML
    let html = `
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>股票代码</th>
                        <th>股票名称</th>
                        <th>行业</th>
                        <th>板块</th>
                        <th>选入价</th>
                        <th>当前价</th>
                        <th>收益率</th>
                        <th>最高价格</th>
                        <th>最高收益</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    // 3. 计算统计数据
    let totalReturn = 0;
    let winCount = 0;
    let maxReturn = -Infinity;
    let minReturn = Infinity;
    let totalMaxReturn = 0;
    
    // 4. 遍历数据生成表格行
    data.forEach(item => {
        // 防御性代码，处理可能的undefined值
        const selectionPrice = item.selection_price || 0;
        const currentPrice = item.current_price || 0;
        const currentReturn = item.current_yield || 0;
        const highestPrice = item.highest_price || 0;
        const highestReturn = item.highest_yield || 0;
        
        // 累计统计数据
        totalReturn += currentReturn;
        if (currentReturn > 0) {
            winCount++;
        }
        maxReturn = Math.max(maxReturn, currentReturn);
        minReturn = Math.min(minReturn, currentReturn);
        totalMaxReturn += highestReturn;
        
        // 生成表格行
        html += `
            <tr>
                <td>${item.rank_position}</td>
                <td><a href="javascript:void(0)" onclick="viewStockDetail('${item.stock_code}')" class="stock-link">${item.stock_code}</a></td>
                <td>${item.stock_name}</td>
                <td>${item.industry || '-'}</td>
                <td>${item.sector || '-'}</td>
                <td>¥${selectionPrice.toFixed(2)}</td>
                <td>¥${currentPrice.toFixed(2)}</td>
                <td class="${currentReturn >= 0 ? 'text-success' : 'text-danger'}">${currentReturn.toFixed(2)}%</td>
                <td>¥${highestPrice.toFixed(2)}</td>
                <td class="${highestReturn >= 0 ? 'text-success' : 'text-danger'}">${highestReturn.toFixed(2)}%</td>
            </tr>
        `;
    });
    
    // 5. 计算平均值和胜率
    const avgReturn = (totalReturn / data.length).toFixed(2);
    const winRate = ((winCount / data.length) * 100).toFixed(2);
    const avgMaxReturn = (totalMaxReturn / data.length).toFixed(2);
    
    // 6. 处理无穷大的情况
    const displayMaxReturn = maxReturn === -Infinity ? '-' : maxReturn.toFixed(2) + '%';
    const displayMinReturn = minReturn === Infinity ? '-' : minReturn.toFixed(2) + '%';
    
    // 7. 生成统计信息
    html += `
                </tbody>
            </table>
        </div>
        
        <!-- 统计说明 -->
        <div style="margin-top: 20px; padding: 15px; background: #f9fafb; border-radius: 8px; border-left: 4px solid #3b82f6;">
            <div style="font-size: 14px; color: #374151; line-height: 1.8;">
                <strong>📊 ${data.length}只狩猎股票统计：</strong>
                平均收益 <span style="color: #3b82f6; font-weight: 600;">${avgReturn}%</span> | 
                胜率 <span style="color: #10b981; font-weight: 600;">${winRate}%</span> | 
                最高收益 <span style="color: #059669; font-weight: 600;">${displayMaxReturn}</span> | 
                最低收益 <span style="color: #dc2626; font-weight: 600;">${displayMinReturn}</span> | 
                最高涨幅平均 <span style="color: #f59e0b; font-weight: 600;">${avgMaxReturn}%</span>
            </div>
        </div>
    `;
    
    // 8. 设置容器内容
    container.innerHTML = html;
}

/**
 * 设置狩猎跟踪事件监听
 */
export function setupKHunterTrackingEvents() {
    // 绑定狩猎跟踪按钮
    const trackBtn = document.getElementById('track-khunter-btn');
    if (trackBtn) {
        trackBtn.addEventListener('click', trackKHunter);
    }
}

/**
 * 暴露全局函数供 HTML 调用
 */
window.calculate = calculate;
window.saveResults = saveResults;
window.openStockDetail = openStockDetail;
window.closeStockDetailModal = closeStockDetailModal;
window.openScoreDetail = openScoreDetail;
window.closeScoreDetailModal = closeScoreDetailModal;
window.trackKHunter = trackKHunter;
window.initKHunterTrackPage = initKHunterTrackPage;
window.setupKHunterTrackingEvents = setupKHunterTrackingEvents;
