/**
 * 首页统计卡片和模态窗口交互模块
 */

// 全局变量
let riskChart = null;
let temperatureChart = null;
// 【2026-09-20】温度趋势数据缓存：弹窗打开时用它重绘。
//   首次渲染发生在页面加载阶段，此时 #temperature-modal 还是 display:none
//   → 容器尺寸为 0 → 图表会渲染成空白（与 ADX 弹窗同类问题）
let temperatureTrendData = null;
// 【2026-09-20】风险趋势数据缓存（同一问题：弹窗隐藏时首绘 → 0 尺寸 → 空白）
let riskTrendData = null;

/* 【2026-09-20】Chart.js 兜底加载器（自愈）
 * 背景：模板中 Chart.js 若未生效（旧缓存 HTML / 未重启服务 / CDN 被阻断），
 *      页面所有图表都会空白。此处在"需要画图"时按需加载**本地内置副本**
 *      /static/js/lib/chart.umd.min.js，加载完成后自动重绘 → 无需重启即可自愈。
 * 用法：_ensureChartJs(成功回调, 失败回调)
 */
function _ensureChartJs(onReady, onFail) {
    if (window.Chart) { if (onReady) onReady(); return; }
    if (window.__chartJsState === 'loading') {          // 已在加载 → 稍后重试
        setTimeout(function () { _ensureChartJs(onReady, onFail); }, 120);
        return;
    }
    if (window.__chartJsState === 'failed') {           // 已知失败 → 不再重复请求
        if (onFail) onFail();
        return;
    }
    window.__chartJsState = 'loading';
    const s = document.createElement('script');
    s.src = '/static/js/lib/chart.umd.min.js';
    s.onload = function () {
        if (window.Chart) {
            window.__chartJsState = 'ok';
            console.log('[图表] 已按需加载本地 Chart.js ✓');
            if (onReady) onReady();
        } else {
            window.__chartJsState = 'failed';
            if (onFail) onFail();
        }
    };
    s.onerror = function () {
        window.__chartJsState = 'failed';
        console.warn('[图表] 本地 Chart.js 加载失败：/static/js/lib/chart.umd.min.js');
        if (onFail) onFail();
    };
    document.head.appendChild(s);
}
window.ensureChartJs = _ensureChartJs;    // 供 ES 模块（backtest 等）复用

/** 在图表容器内显示"缺库"提示（同一容器只插一次） */
function _showChartHint(canvas, hintId, text) {
    const box = canvas && canvas.parentElement;
    if (!box || document.getElementById(hintId)) return;
    const hint = document.createElement('div');
    hint.id = hintId;
    hint.style.cssText = 'color:#b45309;font-size:12px;padding:8px 0;';
    hint.textContent = text || '⚠️ 图表库（Chart.js）未加载，趋势曲线暂不可用';
    box.appendChild(hint);
}

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
        
        let hist = (result.success && result.data) ? result.data : [];
        // 【2026-09-20】自愈兜底：若 /api/risk/history 只回 1 条（旧进程仍只读内存 ✗），
        //   改用**单日接口** /api/risk/status?date= 逐日补齐（该接口读库 ✓、无需重启 ✓）。
        //   重启服务后主路径即恢复正常 ✓，本兜底自动不再触发 ✓。
        if (hist.length <= 2) {
            const filled = await _backfillRiskHistory(days);
            if (filled.length > hist.length) {
                console.log('[风控] 已兜底补齐历史 ' + filled.length + ' 天（接口仅返回 ' + hist.length + ' 条）');
                hist = filled;
            }
        }
        renderRiskTrendChart(hist);
    } catch (error) {
        console.error('加载风控历史失败:', error);
    }
}

/**
 * 【2026-09-20】兜底补齐风控历史（免重启自愈）
 *   逐日调用 /api/risk/status?date=YYYY-MM-DD（该接口优先读库 ✓），
 *   组装成与 /api/risk/history 相同结构的数组（含 date/var_1d/var_5d）。
 *   仅取工作日（周末无数据），最多 days 条。
 */
async function _backfillRiskHistory(days) {
    const pad = function (n) { return String(n).padStart(2, '0'); };
    const ymd = function (d) {
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    };
    const today = new Date();
    const dates = [];
    for (let i = 0; i < days * 2 && dates.length < days; i++) {
        const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
        const wd = d.getDay();
        if (wd === 0 || wd === 6) continue;          // 跳过周末
        dates.push(ymd(d));
    }
    dates.reverse();                                  // 升序（与折线一致）
    const res = await Promise.all(dates.map(async function (dt) {
        try {
            const r = await fetch('/api/risk/status?date=' + dt);
            const j = await r.json();
            return (j && j.success && j.data
                && j.data.var_1d !== null && j.data.var_1d !== undefined) ? j.data : null;
        } catch (e) {
            return null;
        }
    }));
    return res.filter(function (x) { return x; });
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
    
    riskTrendData = data;        // 【2026-09-20】缓存，供弹窗打开时重绘

    // 销毁旧图表
    if (riskChart) {
        riskChart.destroy();
        riskChart = null;
    }

    // 【2026-09-20】缺库 → 按需加载本地 Chart.js 后自动重绘（自愈）；失败才提示
    if (!window.Chart) {
        _ensureChartJs(
            function () { renderRiskTrendChart(riskTrendData || data); },
            function () { _showChartHint(canvas, 'risk-chart-hint'); }
        );
        return;
    }
    const _oldRiskHint = document.getElementById('risk-chart-hint');
    if (_oldRiskHint) _oldRiskHint.remove();
    
    const labels = data.map(item => item.date);
    const var1dData = data.map(item => (item.var_1d * 100).toFixed(2));
    const var5dData = data.map(item => (item.var_5d * 100).toFixed(2));
    
    const ctx = canvas.getContext('2d');
    // 【2026-09-20】改用 window.Chart（与其它图表统一）
    riskChart = new window.Chart(ctx, {
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
    
    temperatureTrendData = data;        // 【2026-09-20】缓存，供弹窗打开时重绘

    // 销毁旧图表
    if (temperatureChart) {
        temperatureChart.destroy();
        temperatureChart = null;
    }

    // 【2026-09-20】缺库 → 先按需加载本地 Chart.js 并自动重绘（自愈）；真正失败才提示
    if (!window.Chart) {
        _ensureChartJs(
            function () { renderTemperatureTrendChart(temperatureTrendData || data); },
            function () { _showChartHint(canvas, 'temperature-chart-hint'); }
        );
        return;
    }
    const _oldTempHint = document.getElementById('temperature-chart-hint');
    if (_oldTempHint) _oldTempHint.remove();
    
    const labels = trendData.map(item => item.trade_date);
    const tempData = trendData.map(item => item.temperature);
    
    const ctx = canvas.getContext('2d');
    // 【2026-09-20】改用 window.Chart：经典脚本+ES 模块混用时更稳妥
    temperatureChart = new window.Chart(ctx, {
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
        // 【2026-09-20】弹窗显示后按真实尺寸重绘（首绘在隐藏状态下会发生 0 尺寸 → 空白）
        if (riskTrendData) {
            renderRiskTrendChart(riskTrendData);
        }
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
        // 【2026-09-20】用缓存数据重绘一次：首绘发生在弹窗隐藏时（容器 0 尺寸 → 空白），
        //   弹窗显示后按真实尺寸重绘即正常。
        if (temperatureTrendData) {
            renderTemperatureTrendChart(temperatureTrendData);
        }
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

/* ==================== 市场速览 · ADX（2026-09-20 新增）====================
 * 在"市场温度"卡片温度值后展示**全A指数 ADX**，点击下钻「近一个月 ADX 详情」。
 * 数据来源：GET /api/market-index-adx/trend?days=30（market_index_adx 表，每日落库）
 * 设计：徽章与弹窗均由本段自注入 DOM → 无需改动 index.html。
 */
let marketAdxChart = null;
let marketAdxData = null;

/* ★【2026-10-05 修复 ✓】卡片/弹窗**必须标出实际指数** ✗→✓
 * 事故 ✗✓：库里**新增**创业板指/科创50 后，本卡片因后端 `get_trend(days)` **没传指数**
 *   ⇒ 取到**任意一行** ✗ ⇒ 数字（17.3 = 科创50 ✓）与文案（"全A指数 000985.CSI" ✗）**不符** ✗✓。
 * 现 ✓：后端已显式按配置指数取数 ✓ 并回传 `data.index_code` ✓ ⇒ 这里把指数**写在脸上** ✓
 *   （将来再改配置/加指数，一眼就能看出"看的到底是哪一个" ✓）。
 */
const MARKET_ADX_INDEX_NAMES = {
    '000985.CSI': '中证全指',
    '399006.SZ': '创业板指',
    '000688.SH': '科创50'
};

function _marketAdxIndexLabel(data) {
    const code = (data && data.index_code) ? String(data.index_code) : '';
    if (!code) return '大盘指数';
    const name = MARKET_ADX_INDEX_NAMES[code];
    return name ? (name + ' ' + code) : code;      // 未知代码 ⇒ 原样显示 ✓（不猜 ✗）
}

function _marketAdxColor(strength) {
    const s = strength || '';
    if (s.indexOf('强趋势') >= 0) return '#dc2626';
    if (s.indexOf('趋势明确') >= 0) return '#f59e0b';
    if (s.indexOf('萌芽') >= 0) return '#0ea5e9';
    return '#64748b';
}

/**
 * 渲染「市场ADX」**独立卡片**（2026-09-20 调整）
 *   原先把 ADX 徽章塞进"市场温度"卡片内部 → 文字被挤压换行，观感差；
 *   现改为与其它概览卡同款（.stat-card）的独立卡片，位置紧邻"市场温度"，点击下钻详情。
 *   （函数名保留 _renderMarketAdxBadge 以兼容调用点，实际渲染卡片）
 */
function _renderMarketAdxBadge(data) {
    if (!data || data.latest_adx === null || data.latest_adx === undefined) return;
    const tempEl = document.getElementById('stat-temperature');
    if (!tempEl || !tempEl.parentNode) return;

    const trend = data.trend || [];
    const last = trend.length ? trend[trend.length - 1] : {};
    const st = data.latest_strength || '';
    const dir = last.trend_direction || '';
    const chg = (last.adx_change === null || last.adx_change === undefined)
        ? null : Number(last.adx_change);
    const color = _marketAdxColor(st);

    let card = document.getElementById('stat-adx-card');
    if (!card) {
        // ⚠️ 修正（2026-09-20）：#stat-temperature 是**温度卡片内部的 <h3>**，
        //   若插成它的兄弟会嵌进温度卡内部导致重叠错乱 → 必须挂到**网格容器**上，
        //   并紧邻"市场温度**卡片**"（.stat-card）插入。
        const tempCard = tempEl.closest ? tempEl.closest('.stat-card') : null;
        const grid = (tempCard && tempCard.parentNode) ? tempCard.parentNode : tempEl.parentNode;
        card = document.createElement('div');
        card.id = 'stat-adx-card';
        card.className = 'stat-card';                       // 与其它概览卡片同款样式
        card.style.cssText = 'cursor:pointer;';
        card.title = '点击查看近一个月 ADX 详情';
        card.onclick = function (e) {
            if (e && e.stopPropagation) e.stopPropagation();
            openMarketAdxModal();
        };
        if (tempCard && grid && tempCard.parentNode === grid) {
            grid.insertBefore(card, tempCard.nextSibling);   // 网格中紧邻温度卡
        } else if (grid) {
            grid.appendChild(card);                          // 兜底：追加到网格末尾
        }
    }

    // ★【2026-10-05】弹窗标题也标出**实际指数** ✓（原来写死"全A指数 000985.CSI"✗ ⇒ 与数字不符 ✗）
    const _adxTitle = document.getElementById('market-adx-title');
    if (_adxTitle) {
        _adxTitle.textContent = '📈 市场 ADX 详情（' + _marketAdxIndexLabel(data) + ' · 周期14）';
    }
    const chgTxt = chg === null ? '' : (chg >= 0 ? '↑ ' + chg.toFixed(2) : '↓ ' + Math.abs(chg).toFixed(2));
    card.innerHTML =
        '<div style="display:flex;align-items:center;gap:12px;">' +
        '  <span style="font-size:30px;line-height:1;">📈</span>' +
        '  <div style="min-width:0;">' +
        '    <h3 style="margin:0;font-size:30px;font-weight:700;line-height:1.15;color:' + color + ';">'
        + Number(data.latest_adx).toFixed(1) + '</h3>' +
        '    <div style="font-size:13px;color:#64748b;margin-top:2px;">市场ADX(14)'
        + ' · ' + _marketAdxIndexLabel(data)                 // ★ 2026-10-05：标出**实际指数** ✓
        + (chgTxt ? ' · ' + chgTxt : '') + '</div>' +
        '    <div style="font-size:12px;color:#64748b;margin-top:2px;white-space:nowrap;">' +
        '      <span style="color:' + color + ';font-weight:600;">' + (st || '-') + '</span>' +
        (dir ? ' · ' + dir : '') +
        '      <span style="margin-left:6px;color:#94a3b8;">▸详情</span>' +
        '    </div>' +
        '  </div>' +
        '</div>';
}

let marketAdxDays = 30;          // 详情区间（交易日）：30=近1月 / 60=近3月 / 120=近半年

async function _loadMarketAdx(days) {
    try {
        if (days) marketAdxDays = Number(days);
        const resp = await fetch('/api/market-index-adx/trend?days=' + marketAdxDays);
        const json = await resp.json();
        if (!json || !json.success) return false;
        marketAdxData = json.data || null;
        _renderMarketAdxBadge(marketAdxData);
        const modal = document.getElementById('market-adx-modal');
        if (modal && modal.classList.contains('show')) _renderMarketAdxChart();
        return true;
    } catch (e) {
        console.warn('[市场速览] ADX 数据获取失败', e);
        return false;
    }
}

function _syncMarketAdxRangeButtons() {
    document.querySelectorAll('#market-adx-range button').forEach(function (b) {
        const on = Number(b.getAttribute('data-days')) === Number(marketAdxDays);
        b.style.background = on ? '#2563eb' : '#f1f5f9';
        b.style.color = on ? '#ffffff' : '#475569';
    });
}

async function switchMarketAdxRange(days) {
    await _loadMarketAdx(days);
    _syncMarketAdxRangeButtons();
}

async function loadMarketIndexAdx() { await _loadMarketAdx(marketAdxDays); }

// 事件委托兜底：卡片可能被重渲染（onclick 属性丢失）→ 用 document 级委托保证点击必定生效
document.addEventListener('click', function (ev) {
    const t = ev.target;
    if (t && t.closest && t.closest('#stat-adx-card')) {
        if (ev.stopPropagation) ev.stopPropagation();
        openMarketAdxModal();
    }
}, true);

function _ensureMarketAdxModal() {
    let modal = document.getElementById('market-adx-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'market-adx-modal';
    modal.className = 'modal-overlay';   // ⚠️ 必须与既有弹窗(#temperature-modal)一致，否则遮罩样式不生效→弹窗不可见
    modal.innerHTML =
        '<div class="modal-content modal-lg">' +
        '  <div class="modal-header">' +
        // ★【2026-10-05】标题**不再写死指数** ✗→✓（由 `_renderMarketAdxBadge` 按实际
        //   `data.index_code` 填充 ✓）—— 写死正是本次"数字与文案不符"✗ 的一半原因 ✓
        '    <h3 id="market-adx-title">📈 市场 ADX 详情</h3>' +
        '    <button class="modal-close" onclick="closeMarketAdxModal()">&times;</button>' +
        '  </div>' +
        '  <div class="modal-body">' +
        '    <div id="market-adx-range" style="margin-bottom:10px;">' +
        '      <button data-days="30" onclick="switchMarketAdxRange(30)" style="padding:4px 12px;margin-right:6px;border:0;border-radius:4px;cursor:pointer;font-size:12px;background:#2563eb;color:#fff;">近1月</button>' +
        '      <button data-days="60" onclick="switchMarketAdxRange(60)" style="padding:4px 12px;margin-right:6px;border:0;border-radius:4px;cursor:pointer;font-size:12px;background:#f1f5f9;color:#475569;">近3月</button>' +
        '      <button data-days="120" onclick="switchMarketAdxRange(120)" style="padding:4px 12px;margin-right:6px;border:0;border-radius:4px;cursor:pointer;font-size:12px;background:#f1f5f9;color:#475569;">近半年</button>' +
        '    </div>' +
        '    <div id="market-adx-summary" style="margin-bottom:12px;font-size:13px;color:#475569;"></div>' +
        // ⚠️ 修复（2026-09-20）：Chart.js 用 maintainAspectRatio:false 时，画布尺寸取自
        //   **父容器**；canvas 自身写 height 只改显示盒、不改绘制缓冲（父容器高度自适应 → 缓冲 0
        //   → 图表一片空白）。标准写法：外层给"固定高度的定位容器"，canvas 不写尺寸。
        '    <div style="position:relative;height:300px;">' +
        '      <canvas id="market-adx-chart"></canvas>' +
        '    </div>' +
        '    <div id="market-adx-table-wrap" style="margin-top:16px;max-height:260px;overflow:auto;"></div>' +
        '  </div>' +
        '</div>';
    document.body.appendChild(modal);
    // ★【2026-10-05】首次打开时也按**已加载**的指数标好标题 ✓（否则通用标题撑到下次刷新 ✗）
    _renderMarketAdxBadge(marketAdxData || {});
    return modal;
}

function openMarketAdxModal() {
    const modal = _ensureMarketAdxModal();
    modal.classList.add('show');
    _syncMarketAdxRangeButtons();     // 弹窗可能被重建 → 恢复当前区间按钮态
    _renderMarketAdxChart();
}

function closeMarketAdxModal() {
    const modal = document.getElementById('market-adx-modal');
    if (modal) modal.classList.remove('show');
}

function _fmtDate8(v) {
    const s = String(v || '');
    return s.length === 8 ? (s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8)) : s;
}

function _fmtNum(v, digits) {
    return (v === null || v === undefined || isNaN(Number(v))) ? null : Number(v).toFixed(digits === undefined ? 2 : digits);
}

function _renderMarketAdxTable(trend) {
    const wrap = document.getElementById('market-adx-table-wrap');
    if (!wrap) return;
    const heads = ['日期', 'ADX', '变化', '+DI', '−DI', '档位', '方向', '收盘'];
    const th = 'padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:left;white-space:nowrap;';
    const td = 'padding:6px 8px;border-bottom:1px solid #f1f5f9;white-space:nowrap;';
    let html = '<table style="width:100%;border-collapse:collapse;font-size:12px;">'
        + '<thead><tr style="position:sticky;top:0;background:#f8fafc;">'
        + heads.map(function (h) { return '<th style="' + th + '">' + h + '</th>'; }).join('')
        + '</tr></thead><tbody>';
    trend.slice().reverse().forEach(function (r) {          // 最新在前
        const c = _marketAdxColor(r.trend_strength);
        const chg = (r.adx_change === null || r.adx_change === undefined)
            ? '' : ((Number(r.adx_change) >= 0 ? '+' : '') + Number(r.adx_change).toFixed(2));
        html += '<tr>'
            + '<td style="' + td + '">' + _fmtDate8(r.trade_date) + '</td>'
            + '<td style="' + td + 'font-weight:600;color:' + c + ';">' + (_fmtNum(r.adx) || '-') + '</td>'
            + '<td style="' + td + 'color:#64748b;">' + chg + '</td>'
            + '<td style="' + td + 'color:#10b981;">' + (_fmtNum(r.plus_di) || '-') + '</td>'
            + '<td style="' + td + 'color:#ef4444;">' + (_fmtNum(r.minus_di) || '-') + '</td>'
            + '<td style="' + td + 'color:' + c + ';">' + (r.trend_strength || '-') + '</td>'
            + '<td style="' + td + '">' + (r.trend_direction || '-') + '</td>'
            + '<td style="' + td + '">' + (_fmtNum(r.close) || '-') + '</td>'
            + '</tr>';
    });
    wrap.innerHTML = html + '</tbody></table>';
}

function _renderMarketAdxChart() {
    const canvas = document.getElementById('market-adx-chart');
    if (!canvas) return;
    const trend = (marketAdxData && marketAdxData.trend) || [];
    if (!trend.length) {
        const box = document.getElementById('market-adx-summary');
        if (box) box.textContent = '暂无 ADX 数据（请确认每日数据更新已执行）';
        return;
    }
    const labels = trend.map(function (r) { return _fmtDate8(r.trade_date); });
    const values = trend.map(function (r) { return r.adx === null ? null : Number(r.adx); });
    const plusDis = trend.map(function (r) { return r.plus_di === null ? null : Number(r.plus_di); });
    const minusDis = trend.map(function (r) { return r.minus_di === null ? null : Number(r.minus_di); });
    const strengths = trend.map(function (r) { return r.trend_strength || ''; });

    // +DI / −DI 交叉：金叉（+DI 上穿 −DI）/ 死叉（下穿）→ 仅交叉点画符号
    const crossUp = [], crossDown = [];
    let lastCross = null;
    for (let i = 0; i < trend.length; i++) {
        const p = plusDis[i], m = minusDis[i];
        const pp = i > 0 ? plusDis[i - 1] : null;
        const pm = i > 0 ? minusDis[i - 1] : null;
        if (p === null || m === null || pp === null || pm === null) {
            crossUp.push(null); crossDown.push(null); continue;
        }
        if (pp < pm && p >= m) {
            crossUp.push(p); crossDown.push(null);
            lastCross = { i: i, type: '金叉' };
        } else if (pp > pm && p <= m) {
            crossUp.push(null); crossDown.push(m);
            lastCross = { i: i, type: '死叉' };
        } else {
            crossUp.push(null); crossDown.push(null);
        }
    }

    const box = document.getElementById('market-adx-summary');
    if (box && marketAdxData) {
        const dir = marketAdxData.trend[marketAdxData.trend.length - 1].trend_direction || '-';
        box.innerHTML = '最新 <b>' + labels[labels.length - 1] + '</b>：ADX <b style="color:'
            + _marketAdxColor(marketAdxData.latest_strength) + ';">'
            + Number(marketAdxData.latest_adx || 0).toFixed(1) + '</b>（'
            + (marketAdxData.latest_strength || '-') + ' · ' + dir + '）&nbsp;|&nbsp; 区间均值 '
            + Number(marketAdxData.avg_adx || 0).toFixed(1)
            + '，最高 ' + Number(marketAdxData.max_adx || 0).toFixed(1)
            + '，最低 ' + Number(marketAdxData.min_adx || 0).toFixed(1)
            + (lastCross ? ('&nbsp;|&nbsp; 最近 DI 交叉：<b>' + labels[lastCross.i] + ' '
                + lastCross.type + '</b>') : '')
            + '&nbsp;|&nbsp; 档位：&lt;20 无趋势(震荡) · 20~25 趋势萌芽 · ≥25 趋势明确 · ≥50 强趋势';
    }
    _renderMarketAdxTable(trend);
    if (marketAdxChart) { marketAdxChart.destroy(); marketAdxChart = null; }
    // ⚠️ 2026-09-20：缺库 → 按需加载本地副本后自动重绘（自愈）；真正失败才在摘要处提示
    if (!window.Chart) {
        _ensureChartJs(
            function () { _renderMarketAdxChart(); },
            function () {
                if (box) {
                    box.innerHTML += '&nbsp;|&nbsp; <span style="color:#b45309;">'
                        + '⚠️ 图表库（Chart.js）未加载，曲线暂不可用</span>';
                }
            }
        );
        return;
    }
    const flat = function (v) { return labels.map(function () { return v; }); };
    marketAdxChart = new window.Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'ADX(14)', data: values,
                    borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.10)',
                    borderWidth: 2, pointRadius: 2, tension: 0.25, fill: true
                },
                {
                    label: '+DI', data: plusDis,
                    borderColor: '#10b981', borderWidth: 1.4, pointRadius: 0,
                    tension: 0.25, fill: false
                },
                {
                    label: '-DI', data: minusDis,
                    borderColor: '#ef4444', borderWidth: 1.4, pointRadius: 0,
                    tension: 0.25, fill: false
                },
                {
                    label: 'DI金叉(看多)', data: crossUp, showLine: false,
                    borderColor: '#059669', backgroundColor: '#059669',
                    pointRadius: 5, pointStyle: 'triangle'
                },
                {
                    label: 'DI死叉(看空)', data: crossDown, showLine: false,
                    borderColor: '#b91c1c', backgroundColor: '#b91c1c',
                    pointRadius: 5, pointStyle: 'rectRot'
                },
                {
                    label: '分档线 25', data: flat(25),
                    borderColor: '#f59e0b', borderDash: [6, 4], borderWidth: 1,
                    pointRadius: 0, fill: false
                },
                {
                    label: '分档线 20', data: flat(20),
                    borderColor: '#94a3b8', borderDash: [6, 4], borderWidth: 1,
                    pointRadius: 0, fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true },
                tooltip: {
                    callbacks: {
                        afterLabel: function (ctx) {
                            // 仅对 ADX 主序列附加"档位"说明
                            if (ctx.datasetIndex !== 0) return '';
                            return '趋势档位: ' + (strengths[ctx.dataIndex] || '-');
                        }
                    }
                }
            },
            scales: {
                y: { suggestedMin: 0, suggestedMax: 60, title: { display: true, text: 'ADX / DI' } }
            }
        }
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadMarketIndexAdx);
} else {
    loadMarketIndexAdx();
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