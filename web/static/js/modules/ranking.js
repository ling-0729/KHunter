/**
 * 选股排名相关功能模块
 */

/**
 * 初始化选股排名页面
 */
export function initStockRankingPage() {
    console.log('初始化选股排名页面');
    // 加载可用日期
    loadRankingDates('stock-ranking-date');
    // 重置结果区域
    document.getElementById('stock-ranking-result').innerHTML = '';
}

/**
 * 初始化排名跟踪页面
 */
export function initRankingTrackPage() {
    console.log('初始化排名跟踪页面');
    // 加载可用日期
    loadRankingDates('ranking-track-date');
    // 重置结果区域
    document.getElementById('ranking-track-result').innerHTML = '';
}

/**
 * 加载排名可用日期
 * @param {string} dateInputId - 日期输入框ID
 */
export async function loadRankingDates(dateInputId) {
    try {
        const response = await fetch('/api/ranking/dates');
        const result = await response.json();
        
        if (result.success && result.data) {
            const dates = result.data;
            if (dates.length > 0) {
                // 设置默认日期为最新的日期
                const dateInput = document.getElementById(dateInputId);
                if (dateInput) {
                    dateInput.value = dates[0];
                }
            }
        }
    } catch (error) {
        console.error('加载排名日期失败:', error);
    }
}

/**
 * 生成选股排名
 */
export async function generateRanking() {
    const dateInput = document.getElementById('stock-ranking-date');
    const resultContainer = document.getElementById('stock-ranking-result');
    
    if (!dateInput || !resultContainer) return;
    
    const selectionDate = dateInput.value;
    if (!selectionDate) {
        alert('请选择选股日期');
        return;
    }
    
    // 显示加载状态
    resultContainer.innerHTML = '<p class="loading">正在生成排名，请稍候...</p>';
    
    try {
        const response = await fetch('/api/ranking/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ selection_date: selectionDate })
        });
        
        const result = await response.json();
        
        if (result.success) {
            renderRankingResult(result.data, resultContainer, selectionDate);
        } else {
            resultContainer.innerHTML = `<p class="loading text-danger">生成排名失败: ${result.error}</p>`;
        }
    } catch (error) {
        console.error('生成排名异常:', error);
        resultContainer.innerHTML = `<p class="loading text-danger">生成排名失败: ${error.message}</p>`;
    }
}

/**
 * 跟踪排名
 */
export async function trackRanking() {
    const dateInput = document.getElementById('ranking-track-date');
    const topNSelect = document.getElementById('ranking-track-topn');
    const resultContainer = document.getElementById('ranking-track-result');
    
    if (!dateInput || !topNSelect || !resultContainer) return;
    
    const selectionDate = dateInput.value;
    const topN = parseInt(topNSelect.value);
    
    if (!selectionDate) {
        alert('请选择选股日期');
        return;
    }
    
    // 显示加载状态
    resultContainer.innerHTML = '<p class="loading">正在跟踪排名，请稍候...</p>';
    
    try {
        const response = await fetch(`/api/ranking/track?selection_date=${selectionDate}&top_n=${topN}`);
        const result = await response.json();
        
        if (result.success) {
            renderTrackingResult(result.data, resultContainer, selectionDate);
        } else {
            resultContainer.innerHTML = `<p class="loading text-danger">跟踪排名失败: ${result.error}</p>`;
        }
    } catch (error) {
        console.error('跟踪排名异常:', error);
        resultContainer.innerHTML = `<p class="loading text-danger">跟踪排名失败: ${error.message}</p>`;
    }
}

/**
 * 渲染排名结果
 * @param {Array} data - 排名数据
 * @param {HTMLElement} container - 结果容器
 */
export function renderRankingResult(data, container, selectionDate) {
    if (!data || data.length === 0) {
        container.innerHTML = '<p class="text-muted">暂无排名数据</p>';
        return;
    }
    
    let html = `
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>股票代码</th>
                        <th>股票名称</th>
                        <th>评分</th>
                        <th>行业</th>
                        <th>板块</th>
                        <th>选入价</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    data.forEach((item, index) => {
        // 防御性代码，处理可能的undefined值
        const score = item.score || 0;
        const selectionPrice = item.selection_price || 0;
        
        html += `
            <tr>
                <td>${index + 1}</td>
                <td><a href="javascript:void(0)" onclick="viewStockDetail('${item.stock_code}')" class="stock-link">${item.stock_code}</a></td>
                <td>${item.stock_name}</td>
                <td><a href="javascript:void(0)" onclick="showScoreDetail('${item.stock_code}', '${selectionDate}')" class="score-link">${score.toFixed(2)}</a></td>
                <td>${item.industry || '-'}</td>
                <td>${item.sector || '-'}</td>
                <td>¥${selectionPrice.toFixed(2)}</td>
            </tr>
        `;
    });
    
    html += `
                </tbody>
            </table>
        </div>
    `;
    
    container.innerHTML = html;
}

/**
 * 渲染排名跟踪结果
 * @param {Array} data - 排名数据
 * @param {HTMLElement} container - 结果容器
 */
export function renderTrackingResult(data, container, selectionDate) {
    if (!data || data.length === 0) {
        container.innerHTML = '<p class="text-muted">暂无排名数据</p>';
        return;
    }
    
    let html = `
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>股票代码</th>
                        <th>股票名称</th>
                        <th>评分</th>
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
    
    // 计算统计数据
    let totalReturn = 0;
    let winCount = 0;
    let maxReturn = -Infinity;
    let minReturn = Infinity;
    let totalMaxReturn = 0;
    
    data.forEach(item => {
        // 防御性代码，处理可能的undefined值
        const score = item.score || 0;
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
        
        html += `
            <tr>
                <td>${item.rank_position}</td>
                <td><a href="javascript:void(0)" onclick="viewStockDetail('${item.stock_code}')" class="stock-link">${item.stock_code}</a></td>
                <td>${item.stock_name}</td>
                <td><a href="javascript:void(0)" onclick="showScoreDetail('${item.stock_code}', '${selectionDate}')" class="score-link">${score.toFixed(2)}</a></td>
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
    
    // 计算平均值和胜率
    const avgReturn = (totalReturn / data.length).toFixed(2);
    const winRate = ((winCount / data.length) * 100).toFixed(2);
    const avgMaxReturn = (totalMaxReturn / data.length).toFixed(2);
    
    // 处理无穷大的情况
    const displayMaxReturn = maxReturn === -Infinity ? '-' : maxReturn.toFixed(2) + '%';
    const displayMinReturn = minReturn === Infinity ? '-' : minReturn.toFixed(2) + '%';
    
    html += `
                </tbody>
            </table>
        </div>
        
        <!-- 统计说明 -->
        <div style="margin-top: 20px; padding: 15px; background: #f9fafb; border-radius: 8px; border-left: 4px solid #3b82f6;">
            <div style="font-size: 14px; color: #374151; line-height: 1.8;">
                <strong>📊 Top${data.length}选入以来统计：</strong>
                平均收益 <span style="color: #3b82f6; font-weight: 600;">${avgReturn}%</span> | 
                胜率 <span style="color: #10b981; font-weight: 600;">${winRate}%</span> | 
                最高收益 <span style="color: #059669; font-weight: 600;">${displayMaxReturn}</span> | 
                最低收益 <span style="color: #dc2626; font-weight: 600;">${displayMinReturn}</span> | 
                最高涨幅平均 <span style="color: #f59e0b; font-weight: 600;">${avgMaxReturn}%</span>
            </div>
        </div>
    `;
    
    container.innerHTML = html;
}

/**
 * 重新生成排名 - 用于修复评分不完整或为0的情况
 */
export async function regenerateRanking() {
    const dateInput = document.getElementById('stock-ranking-date');
    const resultContainer = document.getElementById('stock-ranking-result');
    
    if (!dateInput || !resultContainer) return;
    
    const selectionDate = dateInput.value;
    if (!selectionDate) {
        alert('请选择选股日期');
        return;
    }
    
    // 确认操作
    if (!confirm('确定要重新生成排名吗？这将重新计算所有评分为0的股票。')) {
        return;
    }
    
    // 显示加载状态
    resultContainer.innerHTML = '<p class="loading">正在重新生成排名，请稍候...</p>';
    
    try {
        const response = await fetch('/api/ranking/regenerate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                selection_date: selectionDate,
                force_recalculate: false  // 默认只重新计算评分为0的股票
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 显示重新生成结果
            const data = result.data || {};
            resultContainer.innerHTML = `
                <div style="padding: 15px; background: #d1fae5; border: 1px solid #6ee7b7; border-radius: 8px; margin-bottom: 20px;">
                    <h5 style="color: #065f46; margin-bottom: 10px;">✅ 排名重新生成成功</h5>
                    <p style="color: #047857; margin: 5px 0;">
                        <strong>总股票数：</strong> ${data.total || 0}
                    </p>
                    <p style="color: #047857; margin: 5px 0;">
                        <strong>重新计算：</strong> ${data.recalculated || 0}
                    </p>
                    <p style="color: #047857; margin: 5px 0;">
                        <strong>失败数量：</strong> ${data.failed || 0}
                    </p>
                    <p style="color: #047857; margin: 5px 0;">
                        <strong>消息：</strong> ${result.message || ''}
                    </p>
                </div>
                <p class="text-muted">请点击"生成排名"按钮查看最新的排名结果。</p>
            `;
        } else {
            resultContainer.innerHTML = `
                <div style="padding: 15px; background: #fee2e2; border: 1px solid #fca5a5; border-radius: 8px;">
                    <h5 style="color: #7f1d1d; margin-bottom: 10px;">❌ 重新生成排名失败</h5>
                    <p style="color: #991b1b;">${result.message || '未知错误'}</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('重新生成排名异常:', error);
        resultContainer.innerHTML = `
            <div style="padding: 15px; background: #fee2e2; border: 1px solid #fca5a5; border-radius: 8px;">
                <h5 style="color: #7f1d1d; margin-bottom: 10px;">❌ 重新生成排名失败</h5>
                <p style="color: #991b1b;">${error.message || '网络错误'}</p>
            </div>
        `;
    }
}

/**
 * 强制重新生成排名 - 重新计算所有股票的评分
 */
export async function forceRegenerateRanking() {
    const dateInput = document.getElementById('stock-ranking-date');
    const resultContainer = document.getElementById('stock-ranking-result');
    
    if (!dateInput || !resultContainer) return;
    
    const selectionDate = dateInput.value;
    if (!selectionDate) {
        alert('请选择选股日期');
        return;
    }
    
    // 确认操作
    if (!confirm('确定要强制重新生成排名吗？这将重新计算所有股票的评分，可能需要较长时间。')) {
        return;
    }
    
    // 显示加载状态
    resultContainer.innerHTML = '<p class="loading">正在强制重新生成排名，请稍候...</p>';
    
    try {
        const response = await fetch('/api/ranking/regenerate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                selection_date: selectionDate,
                force_recalculate: true  // 强制重新计算所有股票
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 显示重新生成结果
            const data = result.data || {};
            resultContainer.innerHTML = `
                <div style="padding: 15px; background: #d1fae5; border: 1px solid #6ee7b7; border-radius: 8px; margin-bottom: 20px;">
                    <h5 style="color: #065f46; margin-bottom: 10px;">✅ 排名强制重新生成成功</h5>
                    <p style="color: #047857; margin: 5px 0;">
                        <strong>总股票数：</strong> ${data.total || 0}
                    </p>
                    <p style="color: #047857; margin: 5px 0;">
                        <strong>重新计算：</strong> ${data.recalculated || 0}
                    </p>
                    <p style="color: #047857; margin: 5px 0;">
                        <strong>失败数量：</strong> ${data.failed || 0}
                    </p>
                    <p style="color: #047857; margin: 5px 0;">
                        <strong>消息：</strong> ${result.message || ''}
                    </p>
                </div>
                <p class="text-muted">请点击"生成排名"按钮查看最新的排名结果。</p>
            `;
        } else {
            resultContainer.innerHTML = `
                <div style="padding: 15px; background: #fee2e2; border: 1px solid #fca5a5; border-radius: 8px;">
                    <h5 style="color: #7f1d1d; margin-bottom: 10px;">❌ 强制重新生成排名失败</h5>
                    <p style="color: #991b1b;">${result.message || '未知错误'}</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('强制重新生成排名异常:', error);
        resultContainer.innerHTML = `
            <div style="padding: 15px; background: #fee2e2; border: 1px solid #fca5a5; border-radius: 8px;">
                <h5 style="color: #7f1d1d; margin-bottom: 10px;">❌ 强制重新生成排名失败</h5>
                <p style="color: #991b1b;">${error.message || '网络错误'}</p>
            </div>
        `;
    }
}

/**
 * 设置排名相关事件监听
 */
export function setupRankingEvents() {
    // 绑定生成排名按钮
    const generateBtn = document.getElementById('generate-ranking-btn');
    if (generateBtn) {
        generateBtn.addEventListener('click', generateRanking);
    }
    
    // 绑定跟踪排名按钮
    const trackBtn = document.getElementById('track-ranking-btn');
    if (trackBtn) {
        trackBtn.addEventListener('click', trackRanking);
    }
    
    // 绑定强制重新生成排名按钮（改名为"重新生成"）
    const forceRegenerateBtn = document.getElementById('force-regenerate-ranking-btn');
    if (forceRegenerateBtn) {
        forceRegenerateBtn.addEventListener('click', forceRegenerateRanking);
    }
}
