/**
 * 选股相关功能模块
 */

// 缓存最近一次选股结果，用于手动保存
let lastSelectionResults = null;
let lastSelectionTime = null;
let lastSelectionDate = null;

/**
 * 执行选股 - 先显示策略选择对话框
 */
export async function runSelection() {
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

/**
 * 显示策略选择对话框
 * @param {Array} strategies - 策略列表
 */
export function showStrategySelectionModal(strategies) {
    const modal = document.getElementById('strategy-selection-modal');
    // 使用更精确的选择器，确保获取模态框内的策略列表
    const list = document.querySelector('#strategy-selection-modal #strategy-list');
    
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
    
    // 初始化日期选择器为当日（使用更精确的选择器避免与span冲突）
    const selectionDateInput = document.querySelector('#strategy-selection-modal #selection-date');
    if (selectionDateInput) {
        const today = new Date().toISOString().split('T')[0];
        selectionDateInput.value = today;
    }
    
    modal.classList.add('active');
}

/**
 * 获取选中的策略和逻辑（OR/AND）
 * @returns {Object} 选中的策略和逻辑
 */
export function getSelectedStrategiesAndLogic() {
    const checkboxes = document.querySelectorAll('#strategy-list input[type="checkbox"]:checked');
    const strategies = Array.from(checkboxes).map(cb => cb.value);
    
    // 获取逻辑值（从隐藏的input中获取，默认为 'or'）
    const logicInput = document.querySelector('input[name="logic"]');
    const logic = logicInput ? logicInput.value : 'or';
    
    return { strategies, logic };
}

/**
 * 确认策略选择
 */
export async function confirmStrategySelection() {
    const { strategies, logic } = getSelectedStrategiesAndLogic();
    
    if (strategies.length === 0) {
        alert('请至少选择一个策略');
        return;
    }
    
    // 获取用户选择的日期（使用更精确的选择器避免与span冲突）
    const selectionDateInput = document.querySelector('#strategy-selection-modal #selection-date');
    let selectionDate = null;

    console.log('选股日期输入框值:', selectionDateInput ? selectionDateInput.value : '未找到元素');

    if (selectionDateInput && selectionDateInput.value) {
        selectionDate = selectionDateInput.value;
    }

    console.log('最终选股日期:', selectionDate);
    closeStrategyModal();
    executeSelectionWithStrategies(strategies, logic, selectionDate);
}

/**
 * 关闭策略选择对话框
 */
export function closeStrategyModal() {
    document.getElementById('strategy-selection-modal').classList.remove('active');
}

/**
 * 全选所有策略
 */
export function selectAllStrategies() {
    const checkboxes = document.querySelectorAll('#strategy-list input[type="checkbox"]');
    checkboxes.forEach(cb => cb.checked = true);
}

/**
 * 反选所有策略
 */
export function deselectAllStrategies() {
    const checkboxes = document.querySelectorAll('#strategy-list input[type="checkbox"]');
    checkboxes.forEach(cb => cb.checked = !cb.checked);
}

/**
 * 执行选股（指定策略和逻辑）
 * @param {Array} strategies - 策略列表
 * @param {string} logic - 逻辑（OR/AND）
 * @param {string} selectionDate - 选股日期，格式为YYYY-MM-DD，null表示使用最新数据
 */
export async function executeSelectionWithStrategies(strategies, logic = 'or', selectionDate = null) {
    // 缓存选股日期，供手动保存使用
    lastSelectionDate = selectionDate;
    
    const btn = document.getElementById('run-selection-btn');
    const indicator = document.getElementById('status-indicator');
    
    btn.disabled = true;
    btn.innerHTML = '<span class="icon">⏳</span> 选股中...';
    indicator.innerHTML = '<span class="dot yellow"></span> 运行中';
    
    // 切换到选股结果页
    import('./navigation.js').then(module => module.switchPage('selection'));
    document.getElementById('selection-results').innerHTML = '<p class="loading">正在执行选股策略，请稍候...</p>';
    
    console.log('选股请求开始', { strategies, logic, selectionDate });
    
    try {
        // 设置较长的超时时间（3小时）
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10800000);
        
        const requestBody = { strategies: strategies, logic: logic, end_date: selectionDate };
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
        let responseText = null;
        try {
            // 先读取文本，避免重复读取响应体
            responseText = await response.text();
            console.log('原始响应长度:', responseText.length);
            
            // 尝试解析JSON
            if (!responseText) {
                throw new Error('响应体为空');
            }
            result = JSON.parse(responseText);
            console.log('响应数据:', result);
        } catch (parseError) {
            console.error('JSON解析失败:', parseError);
            if (responseText) {
                console.error('原始响应:', responseText.substring(0, 500));
            }
            throw new Error('服务器返回的数据格式错误: ' + parseError.message);
        }
        
        if (result.success) {
            console.log('选股成功，数据类型:', typeof result.data);
            console.log('选股结果键:', Object.keys(result.data || {}));
            // 缓存选股结果，供手动保存和导出使用
            lastSelectionResults = result.data;
            lastSelectionTime = result.time;
            lastSelectionDate = result.selection_date || result.time.split(' ')[0];  // 缓存选股日期
            
            // 显示选股日期（使用display元素，避免与弹窗中的input元素冲突）
            const selectionDateEl = document.getElementById('selection-date-display');
            if (selectionDateEl) {
                selectionDateEl.textContent = `选股日期: ${lastSelectionDate}`;
            }
            
            // 显示导出和保存按钮
            const exportBtn = document.getElementById('export-selection-btn');
            if (exportBtn) {
                exportBtn.style.display = '';
                exportBtn.disabled = false;
            }
            const saveBtn = document.getElementById('save-selection-btn');
            if (saveBtn) {
                saveBtn.style.display = '';
                saveBtn.disabled = false;
                saveBtn.innerHTML = '<span class="icon">💾</span> 保存结果';
                saveBtn.classList.remove('btn-success');
            }
            renderSelectionResults(result.data, result.time, result.filter_stats, result.strategy_display_names);
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

/**
 * 分析策略交集
 * @param {Object} results - 选股结果
 * @returns {Object} 交集分析结果
 */
export function analyzeStrategyIntersection(results) {
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

/**
 * 渲染交集分析
 * @param {Object} analysis - 交集分析数据
 * @returns {string} HTML字符串
 */
export function renderIntersectionAnalysis(analysis) {
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
export async function saveSelectionResults() {
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
        // 后端已经返回中文名称作为键，直接使用结果
        // 为每个信号添加策略名称（如果还没有）
        const resultsToSave = JSON.parse(JSON.stringify(lastSelectionResults));
        
        for (const [strategyName, signals] of Object.entries(resultsToSave)) {
            // 跳过特殊字段
            if (strategyName.startsWith('_')) {
                continue;
            }
            
            // 为每个信号添加策略名称
            if (Array.isArray(signals)) {
                signals.forEach(signal => {
                    if (!signal.strategies) {
                        signal.strategies = [strategyName];
                    }
                });
            }
        }
        
        // 发送保存请求
        const response = await fetch('/api/save_selection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results: resultsToSave,
                time: lastSelectionTime,
                end_date: lastSelectionDate
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

/**
 * 导出选股结果为Excel
 */
export async function exportSelectionResults() {
    // 检查是否有可导出的数据
    if (!lastSelectionResults || !lastSelectionTime) {
        alert('没有可导出的选股结果，请先执行选股');
        return;
    }
    
    const btn = document.getElementById('export-selection-btn');
    if (!btn) return;
    
    // 按钮状态：导出中
    btn.disabled = true;
    btn.innerHTML = '<span class="icon">⏳</span> 导出中...';
    
    try {
        // 调用后端API导出Excel
        const response = await fetch('/api/khunter/export_selection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results: lastSelectionResults,
                selection_date: lastSelectionDate,
                selection_time: lastSelectionTime
            })
        });
        
        if (response.ok) {
            // 获取文件名
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = '选股结果.xlsx';
            if (contentDisposition) {
                const match = contentDisposition.match(/filename="([^"]+)"/);
                if (match && match[1]) {
                    filename = decodeURIComponent(match[1]);
                }
            }
            
            // 下载文件
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        } else {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.message || '导出失败');
        }
        
        // 恢复按钮状态
        btn.innerHTML = '<span class="icon">📥</span> 导出结果';
        btn.disabled = false;
        
    } catch (error) {
        console.error('导出选股结果异常:', error);
        alert('导出失败: ' + error.message);
        btn.innerHTML = '<span class="icon">📥</span> 导出结果';
        btn.disabled = false;
    }
}

// 暴露全局函数
window.exportSelectionResults = exportSelectionResults;

/**
 * 渲染选股结果
 * @param {Object} results - 选股结果
 * @param {string} time - 选股时间
 * @param {Object} filterStats - 过滤统计信息
 * @param {Object} strategyDisplayNames - 策略名称映射
 */
export function renderSelectionResults(results, time, filterStats, strategyDisplayNames = {}) {
    // 保存策略名称映射到全局变量，供保存时使用
    window.strategyDisplayNames = strategyDisplayNames || {};
    
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
                
                const keyDate = s.key_date ? '<span class="tag">' + s.key_date_type + ': ' + s.key_date + '</span>' : '';
                return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategiesStr + '</span>' + keyDate + reasons + '</div></div></div>';
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
                            
                            const keyDate = s.key_date ? '<span class="tag">' + s.key_date_type + ': ' + s.key_date + '</span>' : '';
                            return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategiesStr + '</span>' + keyDate + reasons + '</div></div></div>';
                        }).join('');
                        
                        html += '</div>';
                        totalCount += Object.keys(countStocksMap).length;
                    }
                }
            }
            
            // 第二步：显示单个策略的股票（被1个策略选中的股票）
            if (byCountMap[1] && Array.isArray(byCountMap[1]) && byCountMap[1].length > 0) {
                const singleStrategyStocks = byCountMap[1];
                
                // 按策略分组股票
                const stocksByStrategy = {};
                for (const stock of singleStrategyStocks) {
                    if (stock && stock.code) {
                        // 获取策略名称
                        const strategyName = stock.strategy_display_names && Array.isArray(stock.strategy_display_names) ? 
                                           stock.strategy_display_names[0] : 
                                           (stock.strategies && Array.isArray(stock.strategies) ? stock.strategies[0] : '未知策略');
                        
                        if (!stocksByStrategy[strategyName]) {
                            stocksByStrategy[strategyName] = [];
                        }
                        stocksByStrategy[strategyName].push(stock);
                    }
                }
                
                // 按策略分组显示
                for (const [strategyName, stocks] of Object.entries(stocksByStrategy)) {
                    if (stocks.length > 0) {
                        totalCount += stocks.length;
                        html += '<div class="selection-strategy"><h4>' + strategyName + ' (' + stocks.length + '只)</h4>';
                        
                        // 显示这个策略的所有股票
                        html += stocks.map(signal => {
                            if (!signal || typeof signal !== 'object') {
                                console.warn('无效的信号结构:', signal);
                                return '';
                            }
                            
                            const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
                            // 使用中文名称显示策略
                            const strategiesStr = signal.strategy_display_names && Array.isArray(signal.strategy_display_names) ? signal.strategy_display_names.join(' + ') : '';
                            const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + r + '</span>').join('') : '';
                            
                            const keyDate = s.key_date ? '<span class="tag">' + s.key_date_type + ': ' + s.key_date + '</span>' : '';
                            return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategiesStr + '</span>' + keyDate + reasons + '</div></div></div>';
                        }).join('');
                        
                        html += '</div>';
                    }
                }
            } else if (strategyEntries.length > 0) {
                // 兜底逻辑：当没有交集分析数据时，直接遍历策略结果显示股票
                for (const [strategyName, signals] of strategyEntries) {
                    if (Array.isArray(signals) && signals.length > 0) {
                        // 尝试获取策略的中文名称
                        let strategyDisplayName = strategyName;
                        // 简单的策略名称映射，实际项目中可能需要从配置或API获取
                        const strategyNameMap = {
                            'TrendAccelerationInflectionStrategy': '趋势加速拐点',
                            'TrendReversalStrategy': '趋势共振反转策略',
                            'ResistanceBreakoutStrategy': '阻力位突破策略',
                            'WBottomStrategy': 'W底策略',
                            'MultiGoldenCrossStrategy': '多金叉共振策略',
                            'MorningStarStrategy': '启明星策略',
                            'MultiPartyCannonStrategy': '多方炮策略',
                            'MultiDeathCrossStrategy': '多死叉共振策略',
                            'MHeadStrategy': 'M头策略',
                            'StrongWashWeakToStrongStrategy': '强势洗盘弱转强策略',
                            'LimitUpPullbackStrategy': '涨停回马枪策略',
                            'LimitUpSidewaysStrategy': '涨停横盘策略',
                            'TrendStartStrategy': '趋势起点策略'
                        };
                        if (strategyNameMap[strategyName]) {
                            strategyDisplayName = strategyNameMap[strategyName];
                        }
                        
                        html += '<div class="selection-strategy"><h4>' + strategyDisplayName + ' (' + signals.length + '只)</h4>';
                        
                        html += signals.map(signal => {
                            if (!signal || typeof signal !== 'object') {
                                console.warn('无效的信号结构:', signal);
                                return '';
                            }
                            
                            const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
                            const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + r + '</span>').join('') : '';
                            
                            const keyDate = s.key_date ? '<span class="tag">' + s.key_date_type + ': ' + s.key_date + '</span>' : '';
                            return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategyDisplayName + '</span>' + keyDate + reasons + '</div></div></div>';
                        }).join('');
                        
                        html += '</div>';
                        totalCount += signals.length;
                    }
                }
            }
            
            // 添加总数统计
            if (totalCount > 0) {
                html = '<p style="margin-bottom: 16px;"><strong>共选出 ' + totalCount + ' 只股票</strong></p>' + html;
            }
        }
    }
    
    // 如果没有生成任何HTML，根据过滤统计信息决定是否显示提示
    if (!html) {
        // 检查是否有过滤统计信息且显示有股票
        const hasFilterStats = filterStats && filterStats.enabled && 
                              (filterStats.total_before > 0 || filterStats.total_after > 0 || filterStats.filtered_out > 0);
        
        if (!hasFilterStats) {
            html = '<p class="text-muted">暂无选股结果</p>';
        }
    }
    
    container.innerHTML = html;
    
    // 显示过滤统计信息
    if (filterStats && filterStats.enabled) {
        const filterHtml = `
            <div class="filter-stats-section">
                <h3>过滤统计</h3>
                <p>过滤前: ${filterStats.total_before} 只</p>
                <p>过滤后: ${filterStats.total_after} 只</p>
                <p>被过滤: ${filterStats.filtered_out} 只</p>
                <h4>过滤条件统计</h4>
                <ul>
                    ${Object.entries(filterStats.filters_applied || {}).map(([filter, count]) => {
                        if (count > 0) {
                            return `<li>${filter}: ${count} 只</li>`;
                        }
                        return '';
                    }).join('')}
                </ul>
                ${filterStats.filtered_stocks && filterStats.filtered_stocks.length > 0 ? `
                    <h4>被过滤的股票</h4>
                    <div class="filtered-stocks-list">
                        ${filterStats.filtered_stocks.map(stock => {
                            return `
                                <div class="filtered-stock-item">
                                    <span class="stock-code">${stock.code} ${stock.name}</span>
                                    <span class="stock-reason">${stock.reason}</span>
                                </div>
                            `;
                        }).join('')}
                    </div>
                ` : ''}
            </div>
        `;
        
        // 添加到容器的末尾
        container.insertAdjacentHTML('beforeend', filterHtml);
    }
}
