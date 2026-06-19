/**
 * 选股历史查询 - 前端逻辑
 */

// 全局变量
let currentPage = 1;
let pageLimit = 20;
let totalRecords = 0;

/**
 * 初始化页面
 */
document.addEventListener('DOMContentLoaded', function() {
    // 设置默认日期范围（最近3个月）
    const endDate = new Date();
    const startDate = new Date();
    startDate.setMonth(startDate.getMonth() - 3);
    
    document.getElementById('start-date-filter').valueAsDate = startDate;
    document.getElementById('end-date-filter').valueAsDate = endDate;
    
    // 加载策略列表到下拉框
    loadStrategyOptions();
    
    // 不再自动加载数据，等待用户点击查询
    // 显示空状态提示
    showEmptyState('请点击"查询"按钮加载数据');
});

/**
 * 加载策略列表到下拉框
 */
function loadStrategyOptions() {
    const strategySelect = document.getElementById('strategy-filter');
    
    console.log('开始加载策略列表...');
    
    // 从API获取策略列表
    fetch('/api/strategies')
        .then(response => response.json())
        .then(data => {
            console.log('API返回数据:', data);
            if (data.success && data.data && data.data.length > 0) {
                // 保留前两个选项（全部策略和测试选项），追加API返回的策略
                const existingOptions = Array.from(strategySelect.options);
                const optionsToKeep = existingOptions.slice(0, 2); // 保留前两个
                
                strategySelect.innerHTML = '';
                optionsToKeep.forEach(opt => strategySelect.appendChild(opt));
                
                data.data.forEach(strategy => {
                    const option = document.createElement('option');
                    option.value = strategy.name;
                    option.textContent = strategy.display_name || strategy.name;
                    strategySelect.appendChild(option);
                });
                console.log('成功加载', data.data.length, '个策略');
            }
        })
        .catch(error => {
            console.error('加载策略列表失败:', error);
        });
}

/**
 * 显示空状态
 * 
 * @param {string} message - 提示信息
 */
function showEmptyState(message) {
    const emptyState = document.getElementById('empty-state');
    const title = emptyState.querySelector('.empty-state-title');
    const text = emptyState.querySelector('.empty-state-text');
    
    title.textContent = '📭 暂无数据';
    text.textContent = message || '请调整筛选条件后重试';
    
    emptyState.style.display = 'block';
    document.getElementById('history-table').style.display = 'none';
    document.getElementById('loading').style.display = 'none';
    document.getElementById('result-stats').style.display = 'none';
    document.getElementById('pagination').style.display = 'none';
}

/**
 * 查询选股历史
 */
function searchHistory() {
    // 获取筛选条件
    const strategyName = document.getElementById('strategy-filter').value;
    const startDate = document.getElementById('start-date-filter').value;
    const endDate = document.getElementById('end-date-filter').value;
    const stockCode = document.getElementById('stock-code-filter').value.trim();
    
    // 重置分页
    currentPage = 1;
    
    // 调用API
    fetchSelectionHistory(strategyName, startDate, endDate, stockCode, currentPage);
}

/**
 * 获取选股历史数据
 * 
 * @param {string} strategyName - 策略名称
 * @param {string} startDate - 开始日期
 * @param {string} endDate - 结束日期
 * @param {string} stockCode - 股票代码
 * @param {number} page - 页码
 */
function fetchSelectionHistory(strategyName, startDate, endDate, stockCode, page) {
    // 显示加载状态
    showLoading(true);
    
    // 构建查询参数
    const params = new URLSearchParams();
    if (strategyName) params.append('strategy_name', strategyName);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    if (stockCode) params.append('stock_code', stockCode);
    params.append('page', page);
    params.append('limit', pageLimit);
    
    // 发送请求
    fetch(`/api/selection-history?${params.toString()}`)
        .then(response => response.json())
        .then(data => {
            showLoading(false);
            
            if (data.success) {
                // 更新数据
                totalRecords = data.total;
                currentPage = data.page;
                pageLimit = data.limit;
                
                // 渲染表格
                renderTable(data.data);
                
                // 显示统计信息
                showStats();
                
                // 渲染分页
                renderPagination(data.total, data.page, data.limit);
            } else {
                showError(data.error || '查询失败');
            }
        })
        .catch(error => {
            showLoading(false);
            showError('网络错误: ' + error.message);
        });
}

/**
 * 渲染表格
 * 
 * @param {array} data - 表格数据
 */
function renderTable(data) {
    const tbody = document.getElementById('history-tbody');
    const table = document.getElementById('history-table');
    const emptyState = document.getElementById('empty-state');
    
    // 清空表格
    tbody.innerHTML = '';
    
    if (data.length === 0) {
        // 显示空状态
        table.style.display = 'none';
        emptyState.style.display = 'block';
        return;
    }
    
    // 隐藏空状态
    table.style.display = 'table';
    emptyState.style.display = 'none';
    
    // 遍历数据
    data.forEach(record => {
        const row = document.createElement('tr');
        
        // 计算收益率样式
        const returnRate = record.return_rate || 0;
        let returnClass = 'return-neutral';
        if (returnRate > 0) {
            returnClass = 'return-positive';
        } else if (returnRate < 0) {
            returnClass = 'return-negative';
        }
        
        // 构建行HTML
        // 使用选入当日收盘价作为选入价格显示
        const selectionPrice = record.selection_day_price || record.selection_price || 0;
        row.innerHTML = `
            <td>
                <span class="strategy-tag">${escapeHtml(record.strategy_name)}</span>
            </td>
            <td>
                <a href="javascript:void(0)" onclick="viewStockDetail('${escapeHtml(record.stock_code)}')" class="stock-link" style="color: #2563eb; text-decoration: none; cursor: pointer; font-weight: 600;">
                    ${escapeHtml(record.stock_code)}
                </a>
            </td>
            <td>${escapeHtml(record.stock_name)}</td>
            <td>${formatDate(record.selection_date)}</td>
            <td>¥${formatPrice(selectionPrice)}</td>
            <td>¥${formatPrice(record.current_price)}</td>
            <td>
                <div class="price-info">
                    <div class="price-row">
                        <span class="price-label">最高:</span>
                        <span class="price-value">¥${formatPrice(record.highest_price)}</span>
                    </div>
                    <div class="price-row">
                        <span class="price-label">最低:</span>
                        <span class="price-value">¥${formatPrice(record.lowest_price)}</span>
                    </div>
                </div>
            </td>
        `;
        
        tbody.appendChild(row);
    });
}

/**
 * 渲染分页
 * 
 * @param {number} total - 总记录数
 * @param {number} currentPage - 当前页
 * @param {number} limit - 每页数量
 */
function renderPagination(total, currentPage, limit) {
    const pagination = document.getElementById('pagination');
    const totalPages = Math.ceil(total / limit);
    
    if (totalPages <= 1) {
        pagination.style.display = 'none';
        return;
    }
    
    pagination.style.display = 'flex';
    pagination.innerHTML = '';
    
    // 上一页按钮
    const prevBtn = document.createElement('button');
    prevBtn.textContent = '← 上一页';
    prevBtn.disabled = currentPage === 1;
    prevBtn.onclick = () => goToPage(currentPage - 1);
    pagination.appendChild(prevBtn);
    
    // 页码按钮
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    if (startPage > 1) {
        const firstBtn = document.createElement('button');
        firstBtn.textContent = '1';
        firstBtn.onclick = () => goToPage(1);
        pagination.appendChild(firstBtn);
        
        if (startPage > 2) {
            const dots = document.createElement('button');
            dots.textContent = '...';
            dots.disabled = true;
            pagination.appendChild(dots);
        }
    }
    
    for (let i = startPage; i <= endPage; i++) {
        const btn = document.createElement('button');
        btn.textContent = i;
        btn.className = i === currentPage ? 'active' : '';
        btn.onclick = () => goToPage(i);
        pagination.appendChild(btn);
    }
    
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            const dots = document.createElement('button');
            dots.textContent = '...';
            dots.disabled = true;
            pagination.appendChild(dots);
        }
        
        const lastBtn = document.createElement('button');
        lastBtn.textContent = totalPages;
        lastBtn.onclick = () => goToPage(totalPages);
        pagination.appendChild(lastBtn);
    }
    
    // 下一页按钮
    const nextBtn = document.createElement('button');
    nextBtn.textContent = '下一页 →';
    nextBtn.disabled = currentPage === totalPages;
    nextBtn.onclick = () => goToPage(currentPage + 1);
    pagination.appendChild(nextBtn);
}

/**
 * 跳转到指定页
 * 
 * @param {number} page - 页码
 */
function goToPage(page) {
    const strategyName = document.getElementById('strategy-filter').value;
    const startDate = document.getElementById('start-date-filter').value;
    const endDate = document.getElementById('end-date-filter').value;
    const stockCode = document.getElementById('stock-code-filter').value.trim();
    
    fetchSelectionHistory(strategyName, startDate, endDate, stockCode, page);
}

/**
 * 显示统计信息
 */
function showStats() {
    const statsDiv = document.getElementById('result-stats');
    document.getElementById('total-count').textContent = totalRecords;
    document.getElementById('current-page').textContent = currentPage;
    document.getElementById('page-limit').textContent = pageLimit;
    statsDiv.style.display = 'flex';
}

/**
 * 重置筛选条件
 */
function resetFilters() {
    document.getElementById('strategy-filter').value = '';
    document.getElementById('start-date-filter').value = '';
    document.getElementById('end-date-filter').value = '';
    document.getElementById('stock-code-filter').value = '';
    
    // 显示空状态提示
    showEmptyState('请点击"查询"按钮加载数据');
}

/**
 * 显示加载状态
 * 
 * @param {boolean} show - 是否显示
 */
function showLoading(show) {
    const loading = document.getElementById('loading');
    const table = document.getElementById('history-table');
    const emptyState = document.getElementById('empty-state');
    
    if (show) {
        loading.style.display = 'block';
        table.style.display = 'none';
        emptyState.style.display = 'none';
    } else {
        loading.style.display = 'none';
    }
}

/**
 * 显示错误信息
 * 
 * @param {string} message - 错误信息
 */
function showError(message) {
    const emptyState = document.getElementById('empty-state');
    const title = emptyState.querySelector('.empty-state-title');
    const text = emptyState.querySelector('.empty-state-text');
    
    title.textContent = '⚠️ 查询出错';
    text.textContent = message;
    
    emptyState.style.display = 'block';
    document.getElementById('history-table').style.display = 'none';
}

/**
 * 格式化日期
 * 
 * @param {string} dateStr - 日期字符串
 * @returns {string} 格式化后的日期
 */
function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN');
}

/**
 * 格式化价格
 * 
 * @param {number} price - 价格
 * @returns {string} 格式化后的价格
 */
function formatPrice(price) {
    if (price === null || price === undefined) return '0.00';
    return parseFloat(price).toFixed(2);
}

/**
 * HTML转义
 * 
 * @param {string} text - 文本
 * @returns {string} 转义后的文本
 */
function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}
