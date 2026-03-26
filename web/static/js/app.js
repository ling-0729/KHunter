/**
 * A股量化选股系统 - 前端逻辑
 */

// 全局状态
let currentPage = 'dashboard';
let chartInstance = null;
// 缓存最近一次选股结果，用于手动保存
let lastSelectionResults = null;
let lastSelectionTime = null;

// WebSocket连接
let socket = null;
let updateStatusInterval = null;

// 初始化WebSocket连接
function initWebSocket() {
    // 创建Socket.IO连接
    socket = io();
    
    // 监听更新进度事件
    socket.on('update_progress', function(data) {
        console.log('收到更新进度:', data);
        updateProgressUI(data);
    });
    
    // 连接成功
    socket.on('connect', function() {
        console.log('WebSocket已连接');
    });
    
    // 连接断开
    socket.on('disconnect', function() {
        console.log('WebSocket已断开');
    });
    
    // 连接错误
    socket.on('connect_error', function(error) {
        console.error('WebSocket连接错误:', error);
    });
}

// 更新进度UI
function updateProgressUI(status) {
    const progressCard = document.getElementById('update-progress-card');
    if (!progressCard) return;
    
    // 显示进度卡片
    progressCard.style.display = 'block';
    
    // 计算进度百分比
    const progress = status.total > 0 ? Math.round((status.success / status.total) * 100) : 0;
    
    // 更新UI
    const progressFill = document.getElementById('progress-fill');
    const progressPercent = document.getElementById('progress-percent');
    const progressText = document.getElementById('progress-text');
    const updateSuccess = document.getElementById('update-success');
    const updateFailed = document.getElementById('update-failed');
    const updateMessage = document.getElementById('update-message');
    
    if (progressFill) progressFill.style.width = progress + '%';
    if (progressPercent) progressPercent.textContent = progress + '%';
    if (progressText) progressText.textContent = status.message || '正在更新...';
    if (updateSuccess) updateSuccess.textContent = status.success || 0;
    if (updateFailed) updateFailed.textContent = status.failed || 0;
    if (updateMessage) updateMessage.textContent = status.message || '';
    
    // 如果更新完成
    if (!status.running && status.start_time) {
        // 清除轮询（如果使用的话）
        if (updateStatusInterval) {
            clearInterval(updateStatusInterval);
            updateStatusInterval = null;
        }
        
        // 显示完成信息
        setTimeout(() => {
            alert(`Data update completed!\nSuccess: ${status.success}\nFailed: ${status.failed}`);
            progressCard.style.display = 'none';
            loadStats(); // 刷新统计信息
        }, 1000);
    }
}

// 页面切换
document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
        const page = item.dataset.page;
        switchPage(page);
    });
});

function switchPage(page) {
    currentPage = page;
    
    // 更新导航
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });
    
    // 更新页面标题
    const titles = {
        'dashboard': '市场速览',
        'stocks': '基础数据',
        'selection': '实时扫描',
        'history': '历史选股',
        'trading': '账户总览',
        'positions': '持仓明细',
        'transactions': '交易历史',
        'strategies': '策略配置',
        'analysis': '个股图谱',
        'indicators': '技术指标库',
        'personal': '个人设置',
        'preference': '偏好配置'
    };
    document.getElementById('page-title').textContent = titles[page];
    
    // 显示对应页面
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === page + '-page');
    });
    
    // 加载页面数据
    if (page === 'dashboard') {
        loadStats();
    } else if (page === 'stocks') {
        loadStocks();
    } else if (page === 'history') {
        loadHistoryStrategyOptions();
        // 不再自动查询，等待用户点击查询按钮
        showHistoryEmptyState('请点击"查询"按钮加载数据');
    } else if (page === 'trading') {
        // 初始化交易模块 - 账户总览
        initTrading();
    } else if (page === 'positions') {
        // 初始化交易模块 - 持仓明细
        initTrading();
    } else if (page === 'transactions') {
        // 初始化交易模块 - 交易历史
        initTrading();
    } else if (page === 'strategies') {
        loadStrategies();
    } else if (page === 'analysis') {
        // 股票分析页面不需要自动加载数据，等待用户输入股票代码
        // 确保分析结果区域隐藏
        const analysisResult = document.getElementById('analysis-result');
        if (analysisResult) {
            analysisResult.classList.add('hidden');
        }
        // 重置表单
        const analysisForm = document.getElementById('analysis-form');
        if (analysisForm) {
            analysisForm.reset();
        }
    }
}

// 加载策略列表到历史记录下拉框
async function loadHistoryStrategyOptions() {
    const strategySelect = document.getElementById('history-strategy-filter');
    if (!strategySelect) return;
    
    try {
        const response = await fetch('/api/strategies');
        const data = await response.json();
        
        if (data.success && data.data) {
            // 保留第一个选项（全部策略）
            strategySelect.innerHTML = '<option value="">全部策略</option>';
            
            data.data.forEach(strategy => {
                const option = document.createElement('option');
                // 使用display_name作为value，因为数据库中存储的是中文名称
                option.value = strategy.display_name || strategy.name;
                option.textContent = strategy.display_name || strategy.name;
                // 保存英文名称用于其他用途
                option.dataset.name = strategy.name;
                strategySelect.appendChild(option);
            });
        }
    } catch (error) {
        console.error('加载策略列表失败:', error);
    }
}

// 加载统计信息
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const result = await response.json();
        
        if (result.success) {
            document.getElementById('stat-stocks').textContent = result.data.total_stocks;
            document.getElementById('stat-date').textContent = result.data.latest_date;
            document.getElementById('stat-strategies').textContent = result.data.strategies;
        }
    } catch (error) {
        console.error('加载统计信息失败:', error);
    }
}

// 加载股票列表 - 支持分页获取所有股票
async function loadStocks() {
    const tbody = document.getElementById('stocks-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="loading">正在加载股票列表...</td></tr>';
    
    try {
        let allStocks = [];
        let page = 1;
        let totalPages = 1;
        
        // 分页获取所有股票
        do {
            const response = await fetch(`/api/stocks?page=${page}&per_page=500`);
            const result = await response.json();
            
            if (result.success) {
                allStocks = allStocks.concat(result.data);
                totalPages = result.total_pages;
                tbody.innerHTML = `<tr><td colspan="7" class="loading">已加载 ${allStocks.length} / ${result.total} 只股票...</td></tr>`;
                page++;
            } else {
                break;
            }
        } while (page <= totalPages);
        
        renderStocks(allStocks);
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading">加载失败: ${error.message}</td></tr>`;
    }
}

// 渲染股票列表
function renderStocks(stocks) {
    const tbody = document.getElementById('stocks-tbody');
    
    if (stocks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">暂无数据</td></tr>';
        return;
    }
    
    tbody.innerHTML = stocks.map(stock => `
        <tr>
            <td><strong>${stock.code}</strong></td>
            <td>${stock.name}</td>
            <td>¥${stock.latest_price}</td>
            <td>${stock.latest_date}</td>
            <td>${stock.market_cap}</td>
            <td>${stock.data_count}</td>
            <td>
                <button class="btn btn-secondary" onclick="viewStockDetail('${stock.code}')">
                    查看
                </button>
            </td>
        </tr>
    `).join('');
    
    // 搜索功能
    document.getElementById('stock-search').addEventListener('input', (e) => {
        const keyword = e.target.value.toLowerCase();
        const rows = tbody.querySelectorAll('tr');
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(keyword) ? '' : 'none';
        });
    });
}

// 查看股票详情
async function viewStockDetail(code) {
    try {
        const response = await fetch(`/api/stock/${code}`);
        const result = await response.json();
        
        if (result.success) {
            showStockModal(code, result.data);
        } else {
            alert('加载股票详情失败: ' + result.error);
        }
    } catch (error) {
        alert('加载股票详情失败: ' + error.message);
    }
}

// 显示股票详情弹窗
function showStockModal(code, data) {
    const modal = document.getElementById('stock-modal');
    document.getElementById('modal-title').textContent = `股票详情: ${code}`;
    
    // 准备图表数据（数据是最新的在前，图表需要最早的在前）
    const reversedData = [...data].reverse();
    const labels = reversedData.map(d => d.date);
    const prices = reversedData.map(d => d.close);
    const kValues = reversedData.map(d => d.K);
    const dValues = reversedData.map(d => d.D);
    const jValues = reversedData.map(d => d.J);
    
    // 绘制K线图和KDJ指标
    const ctx = document.getElementById('stock-chart').getContext('2d');
    
    if (chartInstance) {
        chartInstance.destroy();
    }
    
    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '收盘价',
                    data: prices,
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37, 99, 235, 0.1)',
                    fill: true,
                    tension: 0.1,
                    yAxisID: 'y'
                },
                {
                    label: 'K',
                    data: kValues,
                    borderColor: '#f59e0b',
                    backgroundColor: 'transparent',
                    borderWidth: 1,
                    pointRadius: 0,
                    yAxisID: 'y1'
                },
                {
                    label: 'D',
                    data: dValues,
                    borderColor: '#10b981',
                    backgroundColor: 'transparent',
                    borderWidth: 1,
                    pointRadius: 0,
                    yAxisID: 'y1'
                },
                {
                    label: 'J',
                    data: jValues,
                    borderColor: '#ef4444',
                    backgroundColor: 'transparent',
                    borderWidth: 1,
                    pointRadius: 0,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: true
                }
            },
            scales: {
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    title: {
                        display: true,
                        text: '价格'
                    }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    min: 0,
                    max: 100,
                    title: {
                        display: true,
                        text: 'KDJ'
                    },
                    grid: {
                        drawOnChartArea: false
                    }
                }
            }
        }
    });
    
    // 显示最新信息
    const latest = data[0];
    const jColor = latest.J > 80 ? '#ef4444' : (latest.J < 20 ? '#10b981' : '#666');
    document.getElementById('stock-info').innerHTML = `
        <div class="signal-details" style="margin-top: 16px;">
            <span>最新价: <strong>¥${latest.close}</strong></span>
            <span>最高: <strong>¥${latest.high}</strong></span>
            <span>最低: <strong>¥${latest.low}</strong></span>
            <span>成交量: <strong>${latest.volume}</strong></span>
            <span>市值: <strong>${latest.market_cap}亿</strong></span>
        </div>
        <div class="signal-details" style="margin-top: 12px; padding-top: 12px; border-top: 1px solid #e5e7eb;">
            <span>K: <strong style="color: #f59e0b">${latest.K}</strong></span>
            <span>D: <strong style="color: #10b981">${latest.D}</strong></span>
            <span>J: <strong style="color: ${jColor}">${latest.J}</strong></span>
        </div>
    `;
    
    modal.classList.add('active');
}

// 关闭弹窗
function closeModal() {
    document.getElementById('stock-modal').classList.remove('active');
}

// 执行选股 - 先显示策略选择对话框
async function runSelection() {
    try {
        // 加载策略列表
        const response = await fetch('/api/strategies');
        const result = await response.json();
        
        if (result.success) {
            showStrategySelectionModal(result.data);
        } else {
            alert('加载策略列表失败: ' + result.error);
        }
    } catch (error) {
        alert('加载策略列表失败: ' + error.message);
    }
}

// 显示策略选择对话框
function showStrategySelectionModal(strategies) {
    const modal = document.getElementById('strategy-selection-modal');
    const list = document.getElementById('strategy-list');
    
    // 生成策略列表 - 显示中文名称，默认未选中
    list.innerHTML = strategies.map(s => `
        <div class="strategy-item">
            <input type="checkbox" 
                   id="strategy-${s.name}" 
                   value="${s.name}">
            <label for="strategy-${s.name}">
                <strong>${s.icon} ${s.display_name}</strong>
                <p class="text-muted">${s.description}</p>
                <p class="text-muted">${Object.keys(s.params).length} 个参数</p>
            </label>
        </div>
    `).join('');
    
    modal.classList.add('active');
}

// 获取选中的策略和逻辑（OR/AND）
function getSelectedStrategiesAndLogic() {
    const checkboxes = document.querySelectorAll('#strategy-list input[type="checkbox"]:checked');
    const strategies = Array.from(checkboxes).map(cb => cb.value);
    
    // 获取选中的逻辑（OR/AND）
    const logicRadio = document.querySelector('input[name="logic"]:checked');
    const logic = logicRadio ? logicRadio.value : 'or';
    
    return { strategies, logic };
}

// 确认策略选择
async function confirmStrategySelection() {
    const { strategies, logic } = getSelectedStrategiesAndLogic();
    
    if (strategies.length === 0) {
        alert('请至少选择一个策略');
        return;
    }
    
    closeStrategyModal();
    executeSelectionWithStrategies(strategies, logic);
}

// 关闭策略选择对话框
function closeStrategyModal() {
    document.getElementById('strategy-selection-modal').classList.remove('active');
}

// 执行选股（指定策略和逻辑）
async function executeSelectionWithStrategies(strategies, logic = 'or') {
    const btn = document.getElementById('run-selection-btn');
    const indicator = document.getElementById('status-indicator');
    
    btn.disabled = true;
    btn.innerHTML = '<span class="icon">⏳</span> 选股中...';
    indicator.innerHTML = '<span class="dot yellow"></span> 运行中';
    
    // 切换到选股结果页
    switchPage('selection');
    document.getElementById('selection-results').innerHTML = '<p class="loading">正在执行选股策略，请稍候...</p>';
    
    console.log('选股请求开始', { strategies, logic });
    
    try {
        // 设置较长的超时时间（3小时）
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10800000);
        
        const requestBody = { strategies: strategies, logic: logic };
        console.log('发送请求体:', JSON.stringify(requestBody));
        
        const response = await fetch('/api/select', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody),
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        console.log('响应状态码:', response.status);
        
        // 检查响应是否为JSON
        const contentType = response.headers.get('content-type');
        console.log('响应Content-Type:', contentType);
        
        let result;
        try {
            result = await response.json();
            console.log('响应数据:', result);
        } catch (parseError) {
            console.error('JSON解析失败:', parseError);
            const text = await response.text();
            console.error('原始响应:', text.substring(0, 500));
            throw new Error('服务器返回的数据格式错误');
        }
        
        if (result.success) {
            console.log('选股成功，数据类型:', typeof result.data);
            console.log('选股结果键:', Object.keys(result.data || {}));
            // 缓存选股结果，供手动保存使用
            lastSelectionResults = result.data;
            lastSelectionTime = result.time;
            // 显示保存按钮
            const saveBtn = document.getElementById('save-selection-btn');
            if (saveBtn) {
                saveBtn.style.display = '';
                saveBtn.disabled = false;
                saveBtn.innerHTML = '<span class="icon">💾</span> 保存结果';
                saveBtn.classList.remove('btn-success');
            }
            renderSelectionResults(result.data, result.time);
        } else {
            console.error('选股失败:', result.error);
            document.getElementById('selection-results').innerHTML = 
                `<p class="loading text-danger">选股失败: ${result.error}</p>`;
        }
    } catch (error) {
        console.error('选股异常:', error);
        console.error('错误堆栈:', error.stack);
        
        if (error.name === 'AbortError') {
            document.getElementById('selection-results').innerHTML = 
                `<p class="loading text-danger">选股超时：请求耗时过长，请稍后重试或减少选股策略数量</p>`;
        } else {
            document.getElementById('selection-results').innerHTML = 
                `<p class="loading text-danger">选股失败: ${error.message}</p>`;
        }
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="icon">▶️</span> 执行选股';
        indicator.innerHTML = '<span class="dot green"></span> 就绪';
    }
}

// 分析策略交集
function analyzeStrategyIntersection(results) {
    const stockStrategies = {};
    for (const [strategyName, signals] of Object.entries(results)) {
        for (const signal of signals) {
            const code = signal.code;
            if (!stockStrategies[code]) {
                stockStrategies[code] = {code: code, name: signal.name, strategies: [], count: 0, signals: {}};
            }
            stockStrategies[code].strategies.push(strategyName);
            stockStrategies[code].signals[strategyName] = signal.signals;
            stockStrategies[code].count++;
        }
    }
    const byCount = {};
    for (const [code, data] of Object.entries(stockStrategies)) {
        const count = data.count;
        if (!byCount[count]) {
            byCount[count] = [];
        }
        byCount[count].push(data);
    }
    const totalStrategies = Object.keys(results).length;
    const stocksByStrategy = {};
    for (const [name, signals] of Object.entries(results)) {
        stocksByStrategy[name] = signals.length;
    }
    const multiStrategyCount = Object.values(byCount).filter((_, count) => count > 1).reduce((sum, stocks) => sum + stocks.length, 0);
    const intersectionRate = Object.keys(stockStrategies).length > 0 ? (multiStrategyCount / Object.keys(stockStrategies).length).toFixed(2) : 0;
    return {total: Object.keys(stockStrategies).length, byCount: byCount, intersectionStats: {totalStrategies: totalStrategies, stocksByStrategy: stocksByStrategy, intersectionRate: parseFloat(intersectionRate)}};
}

// 渲染交集分析
function renderIntersectionAnalysis(analysis) {
    // 验证分析数据是否有效
    if (!analysis || typeof analysis !== 'object') {
        console.warn('无效的交集分析数据:', analysis);
        return '';
    }
    
    // 获取 by_count 数据（后端返回的是 by_count，不是 byCount）
    const byCount = analysis.by_count || analysis.byCount || {};
    
    // 验证 by_count 是否为对象
    if (typeof byCount !== 'object' || byCount === null) {
        console.warn('by_count 不是有效的对象:', byCount);
        return '';
    }
    
    // 获取交集统计信息
    const intersectionStats = analysis.intersection_stats || analysis.intersectionStats || {};
    const intersectionRate = intersectionStats.intersection_rate || intersectionStats.intersectionRate || 0;
    
    // 构建HTML
    let html = '<div class="intersection-analysis"><h4>📊 策略交集分析</h4><p>总选股数：<strong>' + (analysis.total || 0) + '</strong>只</p><div class="intersection-stats">';
    
    // 获取并排序交集数量
    const sortedCounts = Object.keys(byCount).map(Number).sort((a, b) => b - a);
    
    // 如果没有交集数据，显示提示
    if (sortedCounts.length === 0) {
        html += '<div class="intersection-item"><span>暂无交集数据</span></div>';
    } else {
        // 遍历每个交集数量
        for (const count of sortedCounts) {
            const stocks = byCount[count];
            if (!Array.isArray(stocks)) {
                console.warn('stocks 不是数组:', stocks);
                continue;
            }
            
            const label = count === 1 ? '仅被1个策略选中' : '被' + count + '个策略同时选中';
            const badge = count > 1 ? '⭐' : '';
            html += '<div class="intersection-item"><span>' + label + '：<strong>' + stocks.length + '</strong>只 ' + badge + '</span></div>';
        }
    }
    
    html += '</div><p class="text-muted" style="margin: 8px 0 0 0; font-size: 13px;">交集率：' + (intersectionRate * 100).toFixed(1) + '%</p></div>';
    return html;
}

/**
 * 手动保存选股结果到数据库
 * 将缓存的选股数据发送到后端保存接口
 */
async function saveSelectionResults() {
    // 检查是否有可保存的数据
    if (!lastSelectionResults || !lastSelectionTime) {
        alert('没有可保存的选股结果，请先执行选股');
        return;
    }

    const btn = document.getElementById('save-selection-btn');
    if (!btn) return;

    // 按钮状态：保存中
    btn.disabled = true;
    btn.innerHTML = '<span class="icon">⏳</span> 保存中...';

    try {
        // 发送保存请求
        const response = await fetch('/api/save_selection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results: lastSelectionResults,
                time: lastSelectionTime
            })
        });

        const result = await response.json();

        if (result.success) {
            // 保存成功，显示统计信息
            const msg = `保存成功：新增${result.saved || 0}条，更新${result.updated || 0}条，跳过${result.skipped || 0}条`;
            btn.innerHTML = '<span class="icon">✅</span> 已保存';
            btn.classList.add('btn-success');
            // 3秒后恢复按钮状态
            setTimeout(() => {
                btn.innerHTML = '<span class="icon">💾</span> 保存结果';
                btn.classList.remove('btn-success');
                btn.disabled = false;
            }, 3000);
            console.log(msg);
        } else {
            // 保存失败
            alert('保存失败: ' + (result.error || '未知错误'));
            btn.innerHTML = '<span class="icon">💾</span> 保存结果';
            btn.disabled = false;
        }
    } catch (error) {
        console.error('保存选股结果异常:', error);
        alert('保存失败: ' + error.message);
        btn.innerHTML = '<span class="icon">💾</span> 保存结果';
        btn.disabled = false;
    }
}

// 渲染选股结果
function renderSelectionResults(results, time) {
    // 设置选股时间
    document.getElementById('selection-time').textContent = `选股时间: ${time}`;
    const container = document.getElementById('selection-results');
    
    // 检查results是否有效
    if (!results || typeof results !== 'object') {
        console.error('选股结果数据格式错误:', results);
        container.innerHTML = '<p class="loading text-danger">选股结果数据格式错误</p>';
        return;
    }
    
    let html = '';
    let totalCount = 0;
    let intersectionAnalysis = null;
    let intersectionStocks = null;
    
    // 提取特殊字段（后端返回的是 _intersection_analysis，不是 _intersectionAnalysis）
    if (results._intersection_analysis) {
        intersectionAnalysis = results._intersection_analysis;
        delete results._intersection_analysis;
    }
    if (results._intersection) {
        intersectionStocks = results._intersection;
        delete results._intersection;
    }
    
    // 处理交集结果（AND逻辑）
    if (intersectionStocks && Array.isArray(intersectionStocks)) {
        totalCount = intersectionStocks.length;
        html += '<p style="margin-bottom: 16px;"><strong>交集结果：共选出 ' + totalCount + ' 只股票</strong></p>';
        
        if (totalCount === 0) {
            html += '<p class="text-muted">两个策略没有同时选中的股票</p>';
        } else {
            html += intersectionStocks.map(signal => {
                // 验证信号结构
                if (!signal || typeof signal !== 'object') {
                    console.warn('无效的信号结构:', signal);
                    return '';
                }
                
                const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
                const strategiesStr = signal.strategies && Array.isArray(signal.strategies) ? signal.strategies.join(' + ') : '';
                const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + r + '</span>').join('') : '';
                
                return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategiesStr + '</span>' + reasons + '</div></div><div class="signal-details"><span>当前价: <strong>¥' + (s.close || 'N/A') + '</strong></span><span>J值: <strong>' + (s.J || 'N/A') + '</strong></span><span>量比: <strong>' + (s.volume_ratio || 'N/A') + 'x</strong></span><span>市值: <strong>' + (s.market_cap || 'N/A') + '亿</strong></span></div></div>';
            }).join('');
        }
    } else {
        // 处理OR逻辑结果 - 优先显示交集股票
        
        // 显示交集分析（如果有）
        if (intersectionAnalysis && typeof intersectionAnalysis === 'object') {
            const analysisHtml = renderIntersectionAnalysis(intersectionAnalysis);
            if (analysisHtml) {
                html += analysisHtml;
            }
        }
        
        // 构建交集股票集合（用于优先显示）
        const intersectionSet = new Set();
        const byCountMap = (intersectionAnalysis && intersectionAnalysis.by_count) || {};
        
        // 收集所有出现在多个策略中的股票代码
        // by_count 的格式: { '1': [{code, name, ...}, ...], '2': [{code, name, ...}, ...] }
        for (const count in byCountMap) {
            if (parseInt(count) > 1) {  // 只收集被多个策略选中的股票
                const stocks = byCountMap[count];
                if (Array.isArray(stocks)) {
                    stocks.forEach(stock => {
                        if (stock && stock.code) {
                            intersectionSet.add(stock.code);
                        }
                    });
                }
            }
        }
        
        // 处理每个策略的结果
        const strategyEntries = Object.entries(results || {});
        
        if (strategyEntries.length === 0) {
            html += '<p class="text-muted">暂无选股结果</p>';
        } else {
            // 第一步：优先显示交集股票（出现在多个策略中的股票）
            if (intersectionSet.size > 0) {
                // 按交集数量降序排列
                const sortedCounts = Object.keys(byCountMap)
                    .map(Number)
                    .sort((a, b) => b - a);  // 降序排列
                
                // 按交集数量显示股票
                for (const count of sortedCounts) {
                    if (count > 1) {
                        const stocks = byCountMap[count];
                        if (!Array.isArray(stocks) || stocks.length === 0) {
                            continue;
                        }
                        
                        // 收集这个交集数量的所有股票及其策略信息
                        const countStocksMap = {};
                        for (const stock of stocks) {
                            if (stock && stock.code) {
                                countStocksMap[stock.code] = stock;
                            }
                        }
                        
                        // 生成标题：显示被多少个策略同时选中
                        const countTitle = count === 2 ? '被2个策略同时选中' : ('被' + count + '个策略同时选中');
                        html += '<div class="selection-strategy"><h4>⭐ ' + countTitle + ' (' + Object.keys(countStocksMap).length + '只)</h4>';
                        
                        // 显示这个交集数量的所有股票
                        html += Object.values(countStocksMap).map(signal => {
                            if (!signal || typeof signal !== 'object') {
                                console.warn('无效的信号结构:', signal);
                                return '';
                            }
                            
                            const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
                            // 使用中文名称显示策略
                            const strategiesStr = signal.strategy_display_names && Array.isArray(signal.strategy_display_names) ? signal.strategy_display_names.join(' + ') : '';
                            const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + r + '</span>').join('') : '';
                            
                            return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategiesStr + '</span>' + reasons + '</div></div><div class="signal-details"><span>当前价: <strong>¥' + (s.close || 'N/A') + '</strong></span><span>J值: <strong>' + (s.J || 'N/A') + '</strong></span><span>量比: <strong>' + (s.volume_ratio || 'N/A') + 'x</strong></span><span>市值: <strong>' + (s.market_cap || 'N/A') + '亿</strong></span></div></div>';
                        }).join('');
                        
                        html += '</div>';
                        totalCount += Object.keys(countStocksMap).length;
                    }
                }
            }
            
            // 第二步：显示单个策略的股票（不在交集中的股票）
            for (const [strategyName, signals] of strategyEntries) {
                // 验证信号是否为数组
                if (!Array.isArray(signals)) {
                    console.warn(`策略 ${strategyName} 的信号不是数组:`, signals);
                    continue;
                }
                
                // 过滤出不在交集中的股票
                const uniqueSignals = signals.filter(signal => !intersectionSet.has(signal.code));
                
                if (uniqueSignals.length === 0) {
                    continue;  // 如果没有独有的股票，跳过此策略
                }
                
                // 获取策略的中文名称
                const strategyDisplayName = uniqueSignals[0] && uniqueSignals[0].strategy_display_name ? uniqueSignals[0].strategy_display_name : strategyName;
                
                totalCount += uniqueSignals.length;
                html += '<div class="selection-strategy"><h4>' + strategyDisplayName + ' (' + uniqueSignals.length + '只)</h4>';
                
                html += uniqueSignals.map(signal => {
                    // 验证信号结构
                    if (!signal || typeof signal !== 'object') {
                        console.warn('无效的信号结构:', signal);
                        return '';
                    }
                    
                    const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
                    const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + r + '</span>').join('') : '';
                    
                    return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags">' + reasons + '</div></div><div class="signal-details"><span>当前价: <strong>¥' + (s.close || 'N/A') + '</strong></span><span>J值: <strong>' + (s.J || 'N/A') + '</strong></span><span>量比: <strong>' + (s.volume_ratio || 'N/A') + 'x</strong></span><span>市值: <strong>' + (s.market_cap || 'N/A') + '亿</strong></span></div></div>';
                }).join('');
                
                html += '</div>';
            }
            
            // 添加总数统计
            if (totalCount > 0) {
                html = '<p style="margin-bottom: 16px;"><strong>共选出 ' + totalCount + ' 只股票</strong></p>' + html;
            }
        }
    }
    
    // 如果没有生成任何HTML，显示提示
    if (!html) {
        html = '<p class="text-muted">暂无选股结果</p>';
    }
    
    container.innerHTML = html;
}

// 加载策略配置
// 保存配置
async function saveConfig() {
    const inputs = document.querySelectorAll('#strategies-config input');
    const config = {};
    
    inputs.forEach(input => {
        const strategy = input.dataset.strategy;
        const param = input.dataset.param;
        let value = input.value;
        
        // 尝试转换为数字
        if (!isNaN(value) && value !== '') {
            value = Number(value);
        }
        
        if (!config[strategy]) {
            config[strategy] = {};
        }
        config[strategy][param] = value;
    });
    
    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(config)
        });
        
        const result = await response.json();
        
        if (result.success) {
            alert('配置保存成功！');
        } else {
            alert('保存失败: ' + result.error);
        }
    } catch (error) {
        alert('保存失败: ' + error.message);
    }
}

// 绑定执行选股按钮
document.getElementById('run-selection-btn').addEventListener('click', runSelection);

// 点击弹窗外部关闭弹窗
document.getElementById('stock-modal').addEventListener('click', (e) => {
    if (e.target.id === 'stock-modal') {
        closeModal();
    }
});

// 触发数据更新
async function triggerUpdate() {
    const progressCard = document.getElementById('update-progress-card');
    
    // 确认更新
    if (!confirm('确定要更新数据吗？这可能需要几分钟时间。')) {
        return;
    }
    
    progressCard.style.display = 'block';
    
    try {
        // 发起更新请求
        const response = await fetch('/api/update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ max_stocks: null })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 使用WebSocket接收实时进度，无需轮询
            console.log('Update started, waiting for WebSocket updates...');
            // 保留轮询作为WebSocket的备用方案
            checkUpdateStatusBackup(progressCard);
        } else {
            alert('Update failed: ' + result.error);
            progressCard.style.display = 'none';
        }
    } catch (error) {
        alert('Update failed: ' + error.message);
        progressCard.style.display = 'none';
    }
}

// 检查更新状态（备用方案，当WebSocket不可用时使用）
async function checkUpdateStatusBackup(progressCard) {
    // 如果已有WebSocket连接，减少轮询频率
    const pollInterval = socket && socket.connected ? 5000 : 1000;
    
    updateStatusInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/update/status');
            const result = await response.json();
            
            if (result.success) {
                const status = result.status;
                
                // 更新进度显示
                const progress = status.total > 0 ? Math.round((status.success / status.total) * 100) : 0;
                document.getElementById('progress-fill').style.width = progress + '%';
                document.getElementById('progress-percent').textContent = progress + '%';
                document.getElementById('progress-text').textContent = status.message;
                document.getElementById('update-success').textContent = status.success;
                document.getElementById('update-failed').textContent = status.failed;
                document.getElementById('update-message').textContent = status.message;
                
                // 如果更新完成
                if (!status.running) {
                    clearInterval(updateStatusInterval);
                    updateStatusInterval = null;
                    
                    // 显示完成信息
                    setTimeout(() => {
                        alert(`Data update completed!\nSuccess: ${status.success}\nFailed: ${status.failed}`);
                        progressCard.style.display = 'none';
                        loadStats(); // 刷新统计信息
                    }, 1000);
                }
            }
        } catch (error) {
            console.error('Check update status failed:', error);
        }
    }, pollInterval);
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    // 初始化WebSocket连接
    initWebSocket();
    
    loadStats();
    setupStockAnalysis();
});

// 股票分析相关功能
function setupStockAnalysis() {
    console.log('setupStockAnalysis 被调用');
    
    // 等待表单元素加载
    const analysisForm = document.getElementById('analysis-form');
    console.log('分析表单元素:', analysisForm);
    
    if (analysisForm) {
        console.log('为分析表单添加提交事件监听器');
        analysisForm.addEventListener('submit', async (e) => {
            console.log('表单提交事件触发');
            e.preventDefault();
            await analyzeStock();
        });
    } else {
        console.warn('找不到分析表单元素');
    }
    
    // 导出按钮
    const exportBtn = document.getElementById('export-btn');
    if (exportBtn) {
        console.log('为导出按钮添加点击事件监听器');
        exportBtn.addEventListener('click', exportReport);
    }
    
    // 重新分析按钮
    const newAnalysisBtn = document.getElementById('new-analysis-btn');
    if (newAnalysisBtn) {
        console.log('为重新分析按钮添加点击事件监听器');
        newAnalysisBtn.addEventListener('click', () => {
            document.getElementById('analysis-result').classList.add('hidden');
            document.getElementById('analysis-form').reset();
        });
    }
}

// 分析股票
async function analyzeStock() {
    const stockCode = document.getElementById('stock-code').value;
    const period = document.getElementById('period').value;
    const btn = document.getElementById('analyze-btn');
    const btnText = document.getElementById('btn-text');
    const loading = document.getElementById('loading');
    
    if (!stockCode) {
        alert('请输入股票代码');
        return;
    }
    
    btn.disabled = true;
    btnText.textContent = '分析中...';
    loading.classList.remove('hidden');
    
    try {
        console.log('开始分析股票:', stockCode, period);
        const response = await fetch('/api/analyze-stock', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ stock_code: stockCode, period: period })
        });
        
        console.log('响应状态:', response.status);
        const result = await response.json();
        console.log('分析结果:', result);
        
        if (result.success) {
            console.log('分析成功，渲染结果');
            renderAnalysisResult(result.data);
            loadAnalysisHistory();
            // 确保分析结果区域可见
            const resultDiv = document.getElementById('analysis-result');
            if (resultDiv) {
                resultDiv.scrollIntoView({ behavior: 'smooth' });
            }
        } else {
            // 处理错误信息，支持 message 和 error 两种字段
            const errorMsg = result.message || result.error || '未知错误';
            console.error('分析失败:', errorMsg);
            alert('分析失败: ' + errorMsg);
        }
    } catch (error) {
        console.error('分析股票异常:', error);
        alert('分析失败: ' + error.message);
    } finally {
        btn.disabled = false;
        btnText.textContent = '开始分析';
        loading.classList.add('hidden');
    }
}

// 渲染分析结果
function renderAnalysisResult(data) {
    // 显示结果区域
    document.getElementById('analysis-result').classList.remove('hidden');
    
    // 股票基本信息（防御性访问，缓存降级时部分字段可能缺失）
    document.getElementById('stock-name').textContent = data?.stock_info?.name || 'N/A';
    document.getElementById('stock-code-display').textContent = data?.stock_info?.code || 'N/A';
    document.getElementById('stock-industry').textContent = data?.stock_info?.industry || 'N/A';
    document.getElementById('stock-sector').textContent = data?.stock_info?.sector || 'N/A';
    
    // 技术面分析
    document.getElementById('technical-trend').textContent = data?.technical?.trend || 'N/A';
    document.getElementById('technical-macd').textContent = data?.technical?.indicators?.MACD || 'N/A';
    document.getElementById('technical-kdj').textContent = data?.technical?.indicators?.KDJ || 'N/A';
    document.getElementById('technical-rsi').textContent = data?.technical?.indicators?.RSI || 'N/A';
    document.getElementById('technical-bollinger').textContent = data?.technical?.indicators?.Bollinger || 'N/A';
    
    // 基本面分析
    document.getElementById('fundamental-revenue').textContent = data?.fundamental?.financial?.revenue || 'N/A';
    document.getElementById('fundamental-profit').textContent = data?.fundamental?.financial?.profit || 'N/A';
    document.getElementById('fundamental-roe').textContent = data?.fundamental?.financial?.roe || 'N/A';
    document.getElementById('fundamental-pe').textContent = data?.fundamental?.valuation?.pe || 'N/A';
    document.getElementById('fundamental-pb').textContent = data?.fundamental?.valuation?.pb || 'N/A';
    document.getElementById('fundamental-ps').textContent = data?.fundamental?.valuation?.ps || 'N/A';
    
    // 资金流向分析
    document.getElementById('fund-flow-direction').textContent = data?.fund_flow?.flow_analysis?.direction || 'N/A';
    document.getElementById('fund-flow-main-inflow').textContent = data?.fund_flow?.flow_analysis?.main_inflow || 'N/A';
    document.getElementById('fund-flow-volume-trend').textContent = data?.fund_flow?.volume_analysis?.trend || 'N/A';
    
    // 板块分析
    document.getElementById('sector-name').textContent = data?.sector?.sector_info?.name || 'N/A';
    document.getElementById('sector-change').textContent = data?.sector?.sector_info?.change || 'N/A';
    document.getElementById('sector-performance').textContent = data?.sector?.performance?.trend || 'N/A';
    
    // 分析结论
    document.getElementById('conclusion-rating').textContent = data?.conclusion?.rating || 'N/A';
    document.getElementById('conclusion-reason').textContent = data?.conclusion?.reason || 'N/A';
    document.getElementById('conclusion-risk').textContent = data?.conclusion?.risk || 'N/A';
}

// 绘制技术图表
function drawTechnicalChart(chartData) {
    const chartContainer = document.getElementById('technical-chart');
    if (!chartData) {
        chartContainer.innerHTML = '<p class="text-gray-500">暂无图表数据</p>';
        return;
    }
    
    // 这里可以使用Chart.js绘制图表
    chartContainer.innerHTML = '<canvas id="stock-price-chart" width="800" height="300"></canvas>';
    
    const ctx = document.getElementById('stock-price-chart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartData.labels || [],
            datasets: [{
                label: '收盘价',
                data: chartData.prices || [],
                borderColor: '#2563eb',
                backgroundColor: 'rgba(37, 99, 235, 0.1)',
                fill: true,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    display: true
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    title: {
                        display: true,
                        text: '价格'
                    }
                }
            }
        }
    });
}

// 导出报告
async function exportReport() {
    const stockCode = document.getElementById('stock-code').value;
    if (!stockCode) {
        alert('请先分析股票');
        return;
    }
    
    try {
        // 直接下载文件，不需要解析JSON
        const link = document.createElement('a');
        link.href = `/api/export-report?stock_code=${stockCode}`;
        link.download = `股票分析报告_${stockCode}.html`;
        link.click();
    } catch (error) {
        console.error('导出报告失败:', error);
        alert('导出失败: ' + error.message);
    }
}

// 加载分析历史
async function loadAnalysisHistory() {
    const historyContainer = document.getElementById('history-container');
    if (!historyContainer) return;
    
    try {
        const response = await fetch('/api/analysis-history');
        const result = await response.json();
        
        if (result.success && result.data && result.data.length > 0) {
            historyContainer.innerHTML = result.data.map(item => `
                <div class="history-item">
                    <div class="history-header">
                        <span class="history-stock">${item.stock_code} ${item.stock_name}</span>
                        <span class="history-date">${item.analysis_date}</span>
                    </div>
                    <div class="history-details">
                        <span>周期: ${item.period}</span>
                        <span>评级: ${item.rating}</span>
                        <button class="btn btn-sm btn-secondary" onclick="viewHistoryReport(${item.id})">查看</button>
                    </div>
                </div>
            `).join('');
        } else {
            historyContainer.innerHTML = '<p class="text-gray-500">暂无分析记录</p>';
        }
    } catch (error) {
        console.error('加载分析历史失败:', error);
        historyContainer.innerHTML = '<p class="text-gray-500">加载历史记录失败</p>';
    }
}

// 查看历史报告
async function viewHistoryReport(reportId) {
    try {
        const response = await fetch(`/api/report/${reportId}`);
        const result = await response.json();
        
        if (result.success) {
            renderAnalysisResult(result.data);
        } else {
            alert('加载报告失败: ' + result.error);
        }
    } catch (error) {
        console.error('加载报告失败:', error);
        alert('加载报告失败: ' + error.message);
    }
}


// ============ 策略配置相关函数 ============

// 全局变量：当前选中的策略
let currentStrategy = null;
let strategiesData = [];

// 加载策略列表 - 获取策略卡片列表和详情
async function loadStrategies() {
    try {
        // 获取策略列表
        const response = await fetch('/api/strategies');
        const result = await response.json();
        
        if (result.success) {
            strategiesData = result.data;
            renderStrategiesGrid(result.data);
        } else {
            document.getElementById('strategies-grid').innerHTML = 
                '<p class="placeholder">加载策略失败: ' + result.error + '</p>';
        }
    } catch (error) {
        console.error('加载策略失败:', error);
        document.getElementById('strategies-grid').innerHTML = 
            '<p class="placeholder">加载策略失败: ' + error.message + '</p>';
    }
}

// 渲染策略卡片网格
function renderStrategiesGrid(strategies) {
    const grid = document.getElementById('strategies-grid');
    
    if (!strategies || strategies.length === 0) {
        grid.innerHTML = '<p class="placeholder">暂无策略</p>';
        return;
    }
    
    // 生成策略卡片
    grid.innerHTML = strategies.map(strategy => `
        <div class="strategy-card" onclick="viewStrategyDetail('${strategy.name}')">
            <div class="strategy-card-icon">${strategy.icon || '📊'}</div>
            <div class="strategy-card-name">${strategy.display_name}</div>
            <div class="strategy-card-description">${strategy.description}</div>
            <div class="strategy-card-footer">
                <div class="strategy-card-params">${Object.keys(strategy.params || {}).length} 个参数</div>
                <div class="strategy-card-arrow">→</div>
            </div>
        </div>
    `).join('');
}

// 查看策略详情
async function viewStrategyDetail(strategyName) {
    try {
        // 获取策略详情
        const response = await fetch(`/api/strategies/${strategyName}`);
        const result = await response.json();
        
        if (result.success) {
            currentStrategy = result.data;
            renderStrategyDetail(result.data);
            
            // 切换到详情视图
            document.getElementById('strategies-list-view').style.display = 'none';
            document.getElementById('strategies-detail-view').style.display = 'block';
        } else {
            alert('加载策略详情失败: ' + result.error);
        }
    } catch (error) {
        console.error('加载策略详情失败:', error);
        alert('加载策略详情失败: ' + error.message);
    }
}

// 渲染策略详情
function renderStrategyDetail(detail) {
    // 设置基本信息
    document.getElementById('detail-icon').textContent = detail.icon || '📊';
    document.getElementById('detail-name').textContent = detail.display_name;
    document.getElementById('detail-description').textContent = detail.description;
    document.getElementById('detail-principle').textContent = detail.principle;
    
    // 设置颜色指示器
    const colorIndicator = document.getElementById('detail-color');
    colorIndicator.style.backgroundColor = detail.color || '#2563eb';
    
    // 渲染参数表单
    renderStrategyParamsForm(detail);
}

// 渲染参数表单
function renderStrategyParamsForm(detail) {
    const formContainer = document.getElementById('strategy-params-form');
    const paramGroups = detail.param_groups || [];
    const paramDetails = detail.param_details || {};
    const currentParams = detail.current_params || {};
    
    if (Object.keys(paramDetails).length === 0) {
        formContainer.innerHTML = '<p class="text-muted">该策略无可配置参数</p>';
        return;
    }
    
    // 按分组渲染参数
    let html = '';
    
    paramGroups.forEach(group => {
        // 获取该分组下的参数
        const groupParams = Object.entries(paramDetails).filter(
            ([_, param]) => param.group === group.name
        );
        
        if (groupParams.length === 0) return;
        
        html += `
            <div class="param-group">
                <div class="param-group-title">
                    <span>📋</span> ${group.name}
                </div>
                <div class="param-group-description">${group.description}</div>
        `;
        
        // 渲染该分组下的参数
        groupParams.forEach(([paramName, paramDef]) => {
            const currentValue = currentParams[paramName] !== undefined ? 
                currentParams[paramName] : paramDef.default;
            const minVal = paramDef.min !== undefined ? paramDef.min : '';
            const maxVal = paramDef.max !== undefined ? paramDef.max : '';
            const rangeText = minVal !== '' && maxVal !== '' ? 
                `${minVal} ~ ${maxVal}` : '';
            
            html += `
                <div class="param-item">
                    <div class="param-label">
                        <span class="param-label-text">${paramDef.display_name}</span>
                        <span class="param-label-default">默认: ${paramDef.default}</span>
                    </div>
                    <div class="param-input-wrapper">
                        <input type="text" class="param-input" 
                               id="param-${paramName}" 
                               value="${currentValue}"
                               data-param-name="${paramName}"
                               data-param-type="${paramDef.type}"
                               data-param-min="${minVal}"
                               data-param-max="${maxVal}"
                               onchange="validateParamInput(this)">
                        ${rangeText ? `<span class="param-range">${rangeText}</span>` : ''}
                        <button class="param-reset-btn" onclick="resetParamToDefault('${paramName}', ${paramDef.default})">
                            重置
                        </button>
                    </div>
                    <div class="param-description">${paramDef.description}</div>
                    <div class="param-error" id="error-${paramName}"></div>
                </div>
            `;
        });
        
        html += '</div>';
    });
    
    formContainer.innerHTML = html;
}

// 验证参数输入
function validateParamInput(input) {
    const paramName = input.dataset.paramName;
    const paramType = input.dataset.paramType;
    const minVal = parseFloat(input.dataset.paramMin);
    const maxVal = parseFloat(input.dataset.paramMax);
    const errorDiv = document.getElementById(`error-${paramName}`);
    
    // 清除之前的错误
    errorDiv.textContent = '';
    
    // 类型检查
    let value = input.value;
    try {
        if (paramType === 'int') {
            value = parseInt(value);
        } else if (paramType === 'float') {
            value = parseFloat(value);
        }
    } catch (e) {
        errorDiv.textContent = `参数类型错误，应为${paramType}`;
        return false;
    }
    
    // 范围检查
    if (!isNaN(minVal) && value < minVal) {
        errorDiv.textContent = `参数值不能小于${minVal}`;
        return false;
    }
    if (!isNaN(maxVal) && value > maxVal) {
        errorDiv.textContent = `参数值不能大于${maxVal}`;
        return false;
    }
    
    return true;
}

// 重置参数到默认值
function resetParamToDefault(paramName, defaultValue) {
    const input = document.getElementById(`param-${paramName}`);
    if (input) {
        input.value = defaultValue;
        validateParamInput(input);
    }
}

// 保存策略参数
async function saveStrategyParams() {
    if (!currentStrategy) return;
    
    // 收集所有参数值
    const params = {};
    const paramDetails = currentStrategy.param_details || {};
    
    let hasError = false;
    Object.keys(paramDetails).forEach(paramName => {
        const input = document.getElementById(`param-${paramName}`);
        if (input) {
            // 验证参数
            if (!validateParamInput(input)) {
                hasError = true;
                return;
            }
            params[paramName] = input.value;
        }
    });
    
    if (hasError) {
        alert('参数验证失败，请检查错误信息');
        return;
    }
    
    try {
        // 第一步：后端验证参数
        const validateResponse = await fetch(`/api/strategies/${currentStrategy.name}/validate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        });
        
        const validateResult = await validateResponse.json();
        
        if (!validateResult.success) {
            // 显示验证错误
            const errors = validateResult.errors || {};
            Object.entries(errors).forEach(([paramName, error]) => {
                const errorDiv = document.getElementById(`error-${paramName}`);
                if (errorDiv) {
                    errorDiv.textContent = error;
                }
            });
            alert('参数验证失败，请检查错误信息');
            return;
        }
        
        // 第二步：保存参数到后端
        const saveResponse = await fetch(`/api/strategies/${currentStrategy.name}/params`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        });
        
        const saveResult = await saveResponse.json();
        
        if (saveResult.success) {
            alert('参数保存成功！');
            // 更新当前策略的参数
            currentStrategy.current_params = params;
        } else {
            alert('参数保存失败: ' + saveResult.error);
        }
    } catch (error) {
        console.error('保存参数失败:', error);
        alert('保存参数失败: ' + error.message);
    }
}

// 恢复策略参数到默认值
function resetStrategyParams() {
    if (!currentStrategy) return;
    
    if (confirm('确定要恢复所有参数到默认值吗？')) {
        const paramDetails = currentStrategy.param_details || {};
        Object.entries(paramDetails).forEach(([paramName, paramDef]) => {
            const input = document.getElementById(`param-${paramName}`);
            if (input) {
                input.value = paramDef.default;
                validateParamInput(input);
            }
        });
    }
}

// 返回策略列表
function backToStrategyList() {
    currentStrategy = null;
    document.getElementById('strategies-list-view').style.display = 'block';
    document.getElementById('strategies-detail-view').style.display = 'none';
}


// ==================== 选股历史查询功能 ====================

/**
 * 查询选股历史
 */
function searchSelectionHistory() {
    console.log('开始查询选股历史...');
    
    // 获取筛选条件
    const strategyFilter = document.getElementById('history-strategy-filter');
    const startDateInput = document.getElementById('history-start-date');
    const endDateInput = document.getElementById('history-end-date');
    
    console.log('筛选元素:', { strategyFilter, startDateInput, endDateInput });
    
    const strategyName = strategyFilter?.value?.trim() || '';
    const startDate = startDateInput?.value || '';
    let endDate = endDateInput?.value || '';
    
    console.log('筛选条件:', { strategyName, startDate, endDate });
    
    // 如果结束日期为空，默认设置为当天
    if (!endDate) {
        const today = new Date();
        endDate = today.toISOString().split('T')[0];
    }
    
    // 调用API（不传递股票代码）
    fetchSelectionHistory(strategyName, startDate, endDate, 1);
}

/**
 * 获取选股历史数据
 */
function fetchSelectionHistory(strategyName, startDate, endDate, page) {
    // 构建查询参数
    const params = new URLSearchParams();
    if (strategyName) params.append('strategy_name', strategyName);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    params.append('page', page);
    params.append('limit', 20);
    
    // 发送请求
    const url = `/api/selection-history?${params.toString()}`;
    console.log('请求URL:', url);
    
    fetch(url)
        .then(response => {
            console.log('API响应状态:', response.status);
            return response.json();
        })
        .then(data => {
            console.log('API返回数据:', data);
            if (data.success) {
                renderHistoryTable(data.data);
                updateHistoryStats(data.total, data.page, data.limit);
                renderHistoryPagination(data.total, data.page, data.limit);
            } else {
                showHistoryError(data.error || '查询失败');
            }
        })
        .catch(error => {
            console.error('API请求错误:', error);
            showHistoryError('网络错误: ' + error.message);
        });
}

/**
 * 渲染历史表格
 */
function renderHistoryTable(data) {
    const tbody = document.getElementById('history-tbody');
    const table = document.getElementById('history-table');
    const emptyState = document.getElementById('history-empty');
    
    // 检查元素是否存在
    if (!tbody || !table || !emptyState) {
        console.error('历史记录表格元素不存在');
        return;
    }
    
    tbody.innerHTML = '';
    
    if (data.length === 0) {
        table.style.display = 'none';
        emptyState.style.display = 'block';
        return;
    }
    
    table.style.display = 'table';
    emptyState.style.display = 'none';
    
    // 遍历数据
    data.forEach(record => {
        const returnRate = record.return_rate || 0;
        let returnClass = 'return-neutral';
        if (returnRate > 0) {
            returnClass = 'return-positive';
        } else if (returnRate < 0) {
            returnClass = 'return-negative';
        }
        
        const row = document.createElement('tr');
        // 使用选入当日收盘价作为选入价格显示
        const selectionPrice = record.selection_day_price || record.selection_price || 0;
        row.innerHTML = `
            <td><span style="background: #dbeafe; color: #0c4a6e; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;">${escapeHtml(record.strategy_name)}</span></td>
            <td><a href="javascript:void(0)" onclick="viewStockDetail('${escapeHtml(record.stock_code)}')" class="stock-link" style="color: #2563eb; text-decoration: none; cursor: pointer; font-weight: 600;">${escapeHtml(record.stock_code)}</a></td>
            <td>${escapeHtml(record.stock_name)}</td>
            <td>${formatDate(record.selection_date)}</td>
            <td>¥${formatPrice(selectionPrice)}</td>
            <td>¥${formatPrice(record.current_price)}</td>
            <td>
                <div style="font-size: 12px;">
                    <div>最高: ¥${formatPrice(record.highest_price)}</div>
                    <div>最低: ¥${formatPrice(record.lowest_price)}</div>
                </div>
            </td>
        `;
        tbody.appendChild(row);
    });
}

/**
 * 更新统计信息
 */
function updateHistoryStats(total, page, limit) {
    const statsDiv = document.getElementById('history-stats');
    const totalElem = document.getElementById('history-total');
    const pageElem = document.getElementById('history-current-page');
    const totalPagesElem = document.getElementById('history-total-pages');
    
    // 检查元素是否存在
    if (!statsDiv || !totalElem || !pageElem) {
        console.error('统计信息元素不存在');
        return;
    }
    
    const totalPages = Math.ceil(total / limit);
    
    totalElem.textContent = total;
    pageElem.textContent = page;
    if (totalPagesElem) {
        totalPagesElem.textContent = totalPages;
    }
    statsDiv.style.display = 'block';
}

/**
 * 渲染分页
 */
function renderHistoryPagination(total, currentPage, limit) {
    const pagination = document.getElementById('history-pagination');
    const totalPages = Math.ceil(total / limit);
    
    if (totalPages <= 1) {
        pagination.style.display = 'none';
        return;
    }
    
    pagination.style.display = 'block';
    pagination.innerHTML = '';
    
    // 上一页
    const prevBtn = document.createElement('button');
    prevBtn.textContent = '← 上一页';
    prevBtn.disabled = currentPage === 1;
    prevBtn.onclick = () => goToHistoryPage(currentPage - 1);
    prevBtn.style.cssText = 'padding: 6px 12px; margin: 0 5px; border: 1px solid #d1d5db; background: white; border-radius: 4px; cursor: pointer; font-size: 12px;';
    pagination.appendChild(prevBtn);
    
    // 页码
    for (let i = Math.max(1, currentPage - 2); i <= Math.min(totalPages, currentPage + 2); i++) {
        const btn = document.createElement('button');
        btn.textContent = i;
        btn.style.cssText = `padding: 6px 10px; margin: 0 2px; border: 1px solid #d1d5db; background: ${i === currentPage ? '#2563eb' : 'white'}; color: ${i === currentPage ? 'white' : '#374151'}; border-radius: 4px; cursor: pointer; font-size: 12px;`;
        btn.onclick = () => goToHistoryPage(i);
        pagination.appendChild(btn);
    }
    
    // 下一页
    const nextBtn = document.createElement('button');
    nextBtn.textContent = '下一页 →';
    nextBtn.disabled = currentPage === totalPages;
    nextBtn.onclick = () => goToHistoryPage(currentPage + 1);
    nextBtn.style.cssText = 'padding: 6px 12px; margin: 0 5px; border: 1px solid #d1d5db; background: white; border-radius: 4px; cursor: pointer; font-size: 12px;';
    pagination.appendChild(nextBtn);
}

/**
 * 跳转到指定页
 */
function goToHistoryPage(page) {
    const strategyName = document.getElementById('history-strategy-filter')?.value.trim() || '';
    const startDate = document.getElementById('history-start-date')?.value || '';
    let endDate = document.getElementById('history-end-date')?.value || '';
    
    // 如果结束日期为空，默认设置为当天
    if (!endDate) {
        const today = new Date();
        endDate = today.toISOString().split('T')[0];
    }
    
    fetchSelectionHistory(strategyName, startDate, endDate, page);
}

/**
 * 重置筛选条件
 */
function resetHistoryFilters() {
    const strategyFilter = document.getElementById('history-strategy-filter');
    const startDate = document.getElementById('history-start-date');
    const endDate = document.getElementById('history-end-date');
    
    // 检查元素是否存在
    if (strategyFilter) strategyFilter.value = '';
    if (startDate) startDate.value = '';
    if (endDate) endDate.value = '';
    
    // 重置后显示空状态，不自动查询
    showHistoryEmptyState('请点击"查询"按钮加载数据');
}

/**
 * 显示空状态提示
 */
function showHistoryEmptyState(message) {
    const emptyState = document.getElementById('history-empty');
    if (emptyState) {
        emptyState.innerHTML = `<p style="color: #6b7280;">📭 ${message}</p>`;
        emptyState.style.display = 'block';
    }
    const table = document.getElementById('history-table');
    if (table) {
        table.style.display = 'none';
    }
    const stats = document.getElementById('history-stats');
    if (stats) {
        stats.style.display = 'none';
    }
}

/**
 * 显示错误信息
 */
function showHistoryError(message) {
    const emptyState = document.getElementById('history-empty');
    if (emptyState) {
        emptyState.innerHTML = `<p style="color: #ef4444;">⚠️ ${message}</p>`;
        emptyState.style.display = 'block';
    }
    const table = document.getElementById('history-table');
    if (table) {
        table.style.display = 'none';
    }
}

/**
 * 格式化日期
 */
function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN');
}

/**
 * 格式化价格
 */
function formatPrice(price) {
    if (price === null || price === undefined) return '0.00';
    return parseFloat(price).toFixed(2);
}

/**
 * HTML转义
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


/**
 * 初始化页面事件监听
 * 页面加载完成后执行
 */
document.addEventListener('DOMContentLoaded', function() {
    // 初始化WebSocket连接
    initWebSocket();
    
    // 加载初始页面
    switchPage('dashboard');
});
