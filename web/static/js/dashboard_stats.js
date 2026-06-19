/**
 * 首页统计卡片和模态窗口交互模块
 */

// 全局变量
let riskChart = null;
let temperatureChart = null;

/**
 * 初始化统计数据
 */
async function initStats() {
    console.log('初始化首页统计数据');
    
    // 加载风控状态
    await loadRiskStatus();
    
    // 加载市场温度
    await loadMarketTemperature();
}

/**
 * 加载风控状态
 */
async function loadRiskStatus() {
    try {
        const response = await fetch('/api/risk/status');
        const result = await response.json();
        
        if (result.success && result.data) {
            const data = result.data;
            
            // 更新首页卡片
            updateRiskCard(data);
            
            // 更新模态窗口内容
            updateRiskModal(data);
            
            // 加载历史数据用于图表
            await loadRiskHistory();
        }
    } catch (error) {
        console.error('加载风控状态失败:', error);
    }
}

/**
 * 加载风控历史数据
 */
async function loadRiskHistory(days = 30) {
    try {
        const response = await fetch(`/api/risk/history?days=${days}`);
        const result = await response.json();
        
        if (result.success && result.data) {
            renderRiskTrendChart(result.data);
        }
    } catch (error) {
        console.error('加载风控历史失败:', error);
    }
}

/**
 * 更新首页风控卡片
 */
function updateRiskCard(data) {
    const varElement = document.getElementById('stat-var');
    const riskLevelElement = document.getElementById('stat-risk-level');
    
    if (varElement) {
        const varPercent = (data.var_1d * 100).toFixed(2);
        varElement.textContent = `${varPercent}`;
        varElement.className = `var-display ${getVarClass(data.var_1d)}`;
    }
    
    if (riskLevelElement) {
        riskLevelElement.textContent = data.risk_level;
        riskLevelElement.className = `risk-badge ${getRiskLevelClass(data.risk_level)}`;
    }
}

/**
 * 更新风控模态窗口内容
 */
function updateRiskModal(data) {
    document.getElementById('modal-risk-date').textContent = data.date || '-';
    document.getElementById('modal-risk-level').textContent = data.risk_level || '-';
    document.getElementById('modal-risk-level').className = `risk-badge-lg ${getRiskLevelClass(data.risk_level)}`;
    
    const var1dElement = document.getElementById('modal-var-1d');
    const var5dElement = document.getElementById('modal-var-5d');
    const es1dElement = document.getElementById('modal-es-1d');
    
    if (var1dElement) {
        var1dElement.textContent = `${(data.var_1d * 100).toFixed(2)}%`;
        var1dElement.className = `var-value ${getVarClass(data.var_1d)}`;
    }
    if (var5dElement) {
        var5dElement.textContent = `${(data.var_5d * 100).toFixed(2)}%`;
        var5dElement.className = `var-value ${getVarClass(data.var_5d)}`;
    }
    if (es1dElement && data.es_1d) {
        es1dElement.textContent = `${(data.es_1d * 100).toFixed(2)}%`;
        es1dElement.className = `var-value ${getVarClass(data.es_1d)}`;
    }
    
    document.getElementById('modal-position-limit').textContent = `${(data.position_limit * 100).toFixed(0)}%`;
    document.getElementById('modal-stop-loss-multiplier').textContent = data.stop_loss_multiplier.toFixed(1);
    document.getElementById('modal-score-extra').textContent = data.score_extra;
    
    const strategyEnabled = document.getElementById('modal-strategy-enabled');
    if (strategyEnabled) {
        strategyEnabled.textContent = data.strategy_enabled ? '启用' : '禁用';
        strategyEnabled.className = `strategy-status ${data.strategy_enabled ? 'enabled' : 'disabled'}`;
    }
    
    const liquidate = document.getElementById('modal-liquidate');
    if (liquidate) {
        liquidate.textContent = data.liquidate ? '是' : '否';
        liquidate.className = `liquidate-status ${data.liquidate ? 'liquidate' : 'normal'}`;
    }
}

/**
 * 渲染风险趋势图表
 */
function renderRiskTrendChart(data) {
    const canvas = document.getElementById('risk-trend-chart');
    if (!canvas || !data.length) return;
    
    // 销毁旧图表
    if (riskChart) {
        riskChart.destroy();
    }
    
    const labels = data.map(item => item.date);
    const var1dData = data.map(item => (item.var_1d * 100).toFixed(2));
    const var5dData = data.map(item => (item.var_5d * 100).toFixed(2));
    
    const ctx = canvas.getContext('2d');
    riskChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'VaR(1日)',
                    data: var1dData,
                    borderColor: 'rgb(75, 192, 192)',
                    backgroundColor: 'rgba(75, 192, 192, 0.1)',
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'VaR(5日)',
                    data: var5dData,
                    borderColor: 'rgb(255, 99, 132)',
                    backgroundColor: 'rgba(255, 99, 132, 0.1)',
                    tension: 0.3,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: false,
                    title: {
                        display: true,
                        text: 'VaR (%)'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: '日期'
                    }
                }
            },
            plugins: {
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            }
        }
    });
}

/**
 * 加载市场温度
 */
async function loadMarketTemperature() {
    try {
        const response = await fetch('/api/market-temperature/latest');
        const result = await response.json();
        
        if (result.success && result.data) {
            const data = result.data;
            
            // 更新首页卡片
            updateTemperatureCard(data);
            
            // 更新模态窗口内容
            updateTemperatureModal(data);
            
            // 加载历史数据用于图表
            await loadTemperatureHistory();
        }
    } catch (error) {
        console.error('加载市场温度失败:', error);
    }
}

/**
 * 加载市场温度历史数据
 */
async function loadTemperatureHistory(days = 30) {
    try {
        const response = await fetch(`/api/market-temperature/trend?days=${days}`);
        const result = await response.json();
        
        if (result.success && result.data) {
            renderTemperatureTrendChart(result.data);
        }
    } catch (error) {
        console.error('加载温度历史失败:', error);
    }
}

/**
 * 获取action状态对应的图标和样式
 * @param {string} action - action文本
 * @returns {Object} 包含icon、颜色和边框样式
 */
function getActionStyle(action) {
    if (!action || action === '-' || action.includes('正常') || action.includes('无风控')) {
        return { 
            icon: '✓', 
            className: 'action-normal',
            bgColor: '#f0fdf4',
            textColor: '#16a34a',
            border: '1px solid #bbf7d0',
            iconBgColor: '#16a34a',
            iconTextColor: '#ffffff'
        };
    } else if (action.includes('50%')) {
        return { 
            icon: '⚠', 
            className: 'action-warning',
            bgColor: '#fffbeb',
            textColor: '#d97706',
            border: '1px solid #fde68a',
            iconBgColor: '#d97706',
            iconTextColor: '#ffffff'
        };
    } else if (action.includes('20%')) {
        return { 
            icon: '!', 
            className: 'action-danger',
            bgColor: '#fff7ed',
            textColor: '#ea580c',
            border: '1px solid #fdba74',
            iconBgColor: '#ea580c',
            iconTextColor: '#ffffff'
        };
    } else if (action.includes('0%')) {
        return { 
            icon: '✕', 
            className: 'action-critical',
            bgColor: '#fef2f2',
            textColor: '#dc2626',
            border: '1px solid #fecaca',
            iconBgColor: '#dc2626',
            iconTextColor: '#ffffff'
        };
    }
    return { 
        icon: 'i', 
        className: 'action-normal',
        bgColor: '#f3f4f6',
        textColor: '#6b7280',
        border: 'none',
        iconBgColor: '#6b7280',
        iconTextColor: '#ffffff'
    };
}

/**
 * 格式化action显示文本
 * @param {string} action - action文本
 * @returns {string} 格式化后的文本
 */
function formatActionText(action) {
    if (!action || action === '-') {
        return '暂无风控信息';
    }
    
    // 解析SCENARIO格式：[SCENARIO_X] 描述，仓位限制X%
    const match = action.match(/\[SCENARIO_(\d+)\]\s*(.+?)(，仓位限制(\d+)%)?/);
    if (match) {
        const scenarioNum = match[1];
        const desc = match[2] || '';
        const limit = match[4] || '';
        
        // 简化显示：场景X - 描述（仓位X%）
        let result = `场景${scenarioNum}: ${desc}`;
        if (limit) {
            result += ` (${limit})`;
        }
        return result;
    }
    
    return action;
}

/**
 * 更新首页温度卡片
 */
function updateTemperatureCard(data) {
    const tempElement = document.getElementById('stat-temperature');
    const statusElement = document.getElementById('stat-temp-status');
    const actionElement = document.getElementById('stat-temp-action');
    const mainRowElement = document.querySelector('.temp-main-row');
    
    // 设置主行布局（温度和状态同行）
    if (mainRowElement) {
        mainRowElement.style.display = 'flex';
        mainRowElement.style.flexDirection = 'row';
        mainRowElement.style.alignItems = 'center';
        mainRowElement.style.gap = '10px';
    }
    
    if (tempElement) {
        tempElement.textContent = `${(data.temperature || 0).toFixed(1)}°`;
        tempElement.className = `temp-display ${getTemperatureClass(data.status)}`;
    }
    
    if (statusElement) {
        statusElement.textContent = data.status || '-';
        statusElement.className = `temp-badge ${getTemperatureClass(data.status)}`;
    }
    
    // 更新action信息
    if (actionElement) {
        const actionStyle = getActionStyle(data.action);
        let actionText = data.action || '暂无数据';
        
        // 去除[SCENARIO_X]前缀，只保留正文
        actionText = actionText.replace(/\[SCENARIO_\d+\]\s*/g, '');
        
        // 简单布局：图标 + 文本
        actionElement.innerHTML = `<span class="action-icon" style="background-color:${actionStyle.iconBgColor};color:${actionStyle.iconTextColor};">${actionStyle.icon}</span>${actionText}`;
        
        // 设置基础样式
        actionElement.style.display = 'block';
        actionElement.style.fontSize = '11px';
        actionElement.style.lineHeight = '1.5';
        actionElement.style.marginTop = '8px';
        actionElement.style.padding = '6px 10px';
        actionElement.style.borderRadius = '6px';
        actionElement.style.border = actionStyle.border;
        actionElement.style.backgroundColor = actionStyle.bgColor;
        actionElement.style.color = actionStyle.textColor;
        actionElement.style.boxSizing = 'border-box';
        actionElement.style.whiteSpace = 'normal';
        actionElement.style.wordWrap = 'break-word';
        actionElement.style.overflow = 'visible';
    }
}

/**
 * 更新温度模态窗口内容
 */
function updateTemperatureModal(data) {
    document.getElementById('modal-temp-date').textContent = data.trade_date || '-';
    
    const tempElement = document.getElementById('modal-temperature');
    if (tempElement) {
        tempElement.textContent = `${data.temperature || 0}`;
        tempElement.className = `temp-value-lg ${getTemperatureClass(data.status)}`;
    }
    
    const statusElement = document.getElementById('modal-temp-status');
    if (statusElement) {
        statusElement.textContent = data.status || '-';
        statusElement.className = `temp-badge-lg ${getTemperatureClass(data.status)}`;
    }
    
    document.getElementById('modal-position-ratio').textContent = `${(data.position_ratio * 100).toFixed(0)}%`;
    document.getElementById('modal-action').textContent = data.action || '-';
    
    // 更新各维度得分
    updateScoreBar('score-up-down', data.up_down_ratio_score);
    updateScoreBar('score-limit-down', data.limit_down_score);
    updateScoreBar('score-limit-up', data.limit_up_performance_score);
    updateScoreBar('score-volume', data.volume_score);
    
    document.getElementById('score-up-down-value').textContent = data.up_down_ratio_score || '-';
    document.getElementById('score-limit-down-value').textContent = data.limit_down_score || '-';
    document.getElementById('score-limit-up-value').textContent = data.limit_up_performance_score || '-';
    document.getElementById('score-volume-value').textContent = data.volume_score || '-';
    
    // 更新原始数据
    document.getElementById('modal-up-count').textContent = data.up_count || '-';
    document.getElementById('modal-down-count').textContent = data.down_count || '-';
    document.getElementById('modal-limit-down-count').textContent = data.limit_down_count || '-';
    document.getElementById('modal-avg-limit-up').textContent = data.avg_limit_up_change ? `${data.avg_limit_up_change.toFixed(2)}%` : '-';
    document.getElementById('modal-total-volume').textContent = formatVolume(data.total_volume);
    document.getElementById('modal-volume-ma5').textContent = data.volume_ma5_ratio ? `${data.volume_ma5_ratio.toFixed(2)}x` : '-';
}

/**
 * 更新得分条
 */
function updateScoreBar(elementId, value) {
    const bar = document.getElementById(elementId);
    if (bar && value !== undefined) {
        bar.style.width = `${value}%`;
    }
}

/**
 * 格式化成交额
 */
function formatVolume(volume) {
    if (!volume) return '-';
    if (volume >= 10000) {
        return `${(volume / 10000).toFixed(2)}万亿`;
    } else if (volume >= 100) {
        return `${(volume / 100).toFixed(2)}百亿`;
    } else {
        return `${volume.toFixed(2)}亿`;
    }
}

/**
 * 渲染温度趋势图表
 */
function renderTemperatureTrendChart(data) {
    const canvas = document.getElementById('temperature-trend-chart');
    if (!canvas) return;
    
    // API返回的是包含trend字段的对象
    const trendData = data.trend || data;
    
    if (!trendData.length) return;
    
    // 销毁旧图表
    if (temperatureChart) {
        temperatureChart.destroy();
    }
    
    const labels = trendData.map(item => item.trade_date);
    const tempData = trendData.map(item => item.temperature);
    
    const ctx = canvas.getContext('2d');
    temperatureChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '市场温度',
                    data: tempData,
                    borderColor: 'rgb(249, 115, 22)',
                    backgroundColor: 'rgba(249, 115, 22, 0.1)',
                    tension: 0.3,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    title: {
                        display: true,
                        text: '温度'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: '日期'
                    }
                }
            },
            plugins: {
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            }
        }
    });
}

/**
 * 打开风控模态窗口
 */
function openRiskModal() {
    const modal = document.getElementById('risk-modal');
    if (modal) {
        modal.classList.add('show');
    }
}

/**
 * 关闭风控模态窗口
 */
function closeRiskModal() {
    const modal = document.getElementById('risk-modal');
    if (modal) {
        modal.classList.remove('show');
    }
}

/**
 * 打开温度模态窗口
 */
function openTemperatureModal() {
    const modal = document.getElementById('temperature-modal');
    if (modal) {
        modal.classList.add('show');
    }
}

/**
 * 关闭温度模态窗口
 */
function closeTemperatureModal() {
    const modal = document.getElementById('temperature-modal');
    if (modal) {
        modal.classList.remove('show');
    }
}

/**
 * 刷新风控数据
 */
async function refreshRiskData() {
    await loadRiskStatus();
}

/**
 * 刷新温度数据
 */
async function refreshTemperatureData() {
    await loadMarketTemperature();
}

/**
 * 重新计算当日温度（强制不使用缓存）
 */
async function recalculateTemperatureData() {
    try {
        // 获取当前日期
        const today = new Date();
        const tradeDate = today.toISOString().slice(0, 10).replace(/-/g, '');
        
        // 显示加载提示
        const btn = document.querySelector('.btn-warning');
        if (btn) {
            btn.textContent = '计算中...';
            btn.disabled = true;
        }
        
        // 发送请求重新计算温度（不使用缓存）
        const response = await fetch('/api/market-temperature/calculate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                trade_date: tradeDate,
                use_cache: false 
            })
        });
        
        const result = await response.json();
        
        if (result.success && result.data) {
            // 刷新显示
            await loadMarketTemperature();
            
            // 显示成功提示
            alert(`温度计算成功！\n日期: ${tradeDate}\n温度: ${result.data.temperature.toFixed(1)}°\n状态: ${result.data.status}\nAction: ${result.data.action}`);
        } else {
            alert(`温度计算失败：${result.message || '未知错误'}`);
        }
        
        // 恢复按钮状态
        if (btn) {
            btn.textContent = '重新计算当日温度';
            btn.disabled = false;
        }
        
    } catch (error) {
        console.error('重新计算温度失败:', error);
        alert('重新计算温度失败：' + error.message);
        
        // 恢复按钮状态
        const btn = document.querySelector('.btn-warning');
        if (btn) {
            btn.textContent = '重新计算当日温度';
            btn.disabled = false;
        }
    }
}

/**
 * 获取VaR值的CSS类
 */
function getVarClass(varValue) {
    const varPercent = varValue * 100;
    
    if (varPercent > -2) {
        return 'var-normal';
    } else if (varPercent > -4) {
        return 'var-caution';
    } else if (varPercent > -6) {
        return 'var-danger';
    } else {
        return 'var-crash';
    }
}

/**
 * 获取风险等级的CSS类
 */
function getRiskLevelClass(riskLevel) {
    const levelMap = {
        '正常': 'risk-normal',
        '注意': 'risk-caution',
        '危险': 'risk-danger',
        '崩溃': 'risk-crash'
    };
    return levelMap[riskLevel] || 'risk-normal';
}

/**
 * 获取温度状态的CSS类
 */
function getTemperatureClass(status) {
    const statusMap = {
        '活跃': 'temp-active',
        '正常': 'temp-normal',
        '偏冷': 'temp-cold',
        '寒冷': 'temp-cold',
        '冰封': 'temp-freezing',
        '极端': 'temp-freezing'
    };
    return statusMap[status] || 'temp-normal';
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    // 点击模态窗口外部关闭
    document.getElementById('risk-modal').addEventListener('click', (e) => {
        if (e.target === document.getElementById('risk-modal')) {
            closeRiskModal();
        }
    });
    
    document.getElementById('temperature-modal').addEventListener('click', (e) => {
        if (e.target === document.getElementById('temperature-modal')) {
            closeTemperatureModal();
        }
    });
    
    // ESC键关闭模态窗口
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeRiskModal();
            closeTemperatureModal();
        }
    });
});