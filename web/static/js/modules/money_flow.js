/**
 * 资金流向选股模块
 */

// 缓存选股结果
let moneyFlowLastResults = null;

/**
 * 初始化资金流向页面
 */
export function initMoneyFlowPage() {
    // 设置默认结束日期为今日
    const today = new Date();
    const endDateInput = document.getElementById('money-flow-end-date');
    if (endDateInput) {
        endDateInput.value = today.toISOString().split('T')[0];
    }
}

/**
 * 执行资金流向选股
 */
export async function runMoneyFlowSelection() {
    const btn = document.getElementById('run-money-flow-btn');
    const resultsContainer = document.getElementById('money-flow-results');
    const statsDiv = document.getElementById('money-flow-stats');
    const totalSpan = document.getElementById('money-flow-total');
    
    // 获取参数
    const endDateInput = document.getElementById('money-flow-end-date');
    const daysInput = document.getElementById('money-flow-days');
    const minAmountInput = document.getElementById('money-flow-min-amount');
    
    // 转换日期格式
    let endDate = endDateInput.value;
    if (endDate) {
        endDate = endDate.replace(/-/g, '');
    }
    
    const days = parseInt(daysInput.value) || 10;
    const minNetAmount = parseFloat(minAmountInput.value) || 0;
    
    // 按钮状态
    btn.disabled = true;
    btn.innerHTML = '<span class="icon">⏳</span> 选股中...';
    
    // 显示加载状态
    resultsContainer.innerHTML = '<p class="loading">正在查询资金流向数据，请稍候...</p>';
    
    console.log('资金流向选股参数:', { endDate, days, minNetAmount });
    
    try {
        const response = await fetch('/api/money-flow/select', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                days: days,
                min_net_amount: minNetAmount,
                end_date: endDate
            })
        });
        
        const result = await response.json();
        console.log('资金流向选股结果:', result);
        
        if (result.success) {
            // 缓存结果
            moneyFlowLastResults = result.data;
            
            // 显示统计
            statsDiv.style.display = '';
            totalSpan.textContent = result.data.length;
            
            // 渲染结果
            renderMoneyFlowResults(result.data, result.params);
        } else {
            resultsContainer.innerHTML = `<p class="loading text-danger">选股失败: ${result.message}</p>`;
            statsDiv.style.display = 'none';
        }
    } catch (error) {
        console.error('资金流向选股异常:', error);
        resultsContainer.innerHTML = `<p class="loading text-danger">选股失败: ${error.message}</p>`;
        statsDiv.style.display = 'none';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="icon">💰</span> 开始选股';
    }
}

/**
 * 渲染资金流向选股结果
 * @param {Array} results - 选股结果
 * @param {Object} params - 参数信息
 */
function renderMoneyFlowResults(results, params) {
    const container = document.getElementById('money-flow-results');
    
    if (!results || results.length === 0) {
        container.innerHTML = '<p class="placeholder">未找到符合条件的股票</p>';
        return;
    }
    
    // 构建HTML表格
    let html = `
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>序号</th>
                        <th>股票代码</th>
                        <th>股票名称</th>
                        <th>连续天数</th>
                        <th>10日净流入(万)</th>
                        <th>10日大单(万)</th>
                        <th>日均净流入(万)</th>
                        <th>最新涨跌幅</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    results.forEach((stock, index) => {
        // 计算涨跌幅颜色
        const pctChange = stock.latest_pct_change || 0;
        let pctColor = '#6b7280';
        if (pctChange > 0) pctColor = '#dc2626';
        else if (pctChange < 0) pctColor = '#16a34a';
        
        // 格式化金额
        const netAmount = formatNumber(stock.net_amount_10d);
        const lgAmount = formatNumber(stock.buy_lg_amount_10d);
        const avgAmount = formatNumber(stock.avg_net_amount);
        
        html += `
            <tr>
                <td>${index + 1}</td>
                <td>${stock.ts_code}</td>
                <td><a href="javascript:void(0)" onclick="viewStockDetail('${stock.ts_code.split('.')[0]}')" class="stock-link">${stock.name}</a></td>
                <td><span class="tag">${stock.continuous_days}天</span></td>
                <td style="color: #dc2626; font-weight: 600;">${netAmount}</td>
                <td style="color: #ea580c;">${lgAmount}</td>
                <td>${avgAmount}</td>
                <td style="color: ${pctColor}; font-weight: 600;">${pctChange > 0 ? '+' : ''}${pctChange.toFixed(2)}%</td>
            </tr>
        `;
    });
    
    html += `
                </tbody>
            </table>
        </div>
        <div style="margin-top: 15px; font-size: 12px; color: #6b7280;">
            <p>参数: 连续天数=${params.days}, 最小日均净流入=${params.min_net_amount}万</p>
            <p style="margin-top: 5px;">💡 点击股票名称可查看详细K线图</p>
        </div>
    `;
    
    container.innerHTML = html;
}

/**
 * 格式化数字（添加千分位）
 */
function formatNumber(num) {
    if (num === null || num === undefined) return '-';
    return num.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}

/**
 * 清空资金流向选股结果
 */
export function clearMoneyFlowResults() {
    const resultsContainer = document.getElementById('money-flow-results');
    const statsDiv = document.getElementById('money-flow-stats');
    
    resultsContainer.innerHTML = '<p class="placeholder">设置参数后点击"开始选股"</p>';
    statsDiv.style.display = 'none';
    
    // 重置参数
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('money-flow-end-date').value = today;
    document.getElementById('money-flow-days').value = '10';
    document.getElementById('money-flow-min-amount').value = '0';
    
    moneyFlowLastResults = null;
}

// 暴露全局函数
window.runMoneyFlowSelection = runMoneyFlowSelection;
window.clearMoneyFlowResults = clearMoneyFlowResults;
