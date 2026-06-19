/**
 * 个股图谱评分相关功能模块
 */

/**
 * 重置个股图谱页面状态，隐藏结果区域并重置表单
 */
export function resetScorePageState() {
    // 隐藏所有状态卡片和结果
    const ids = ['score-loading-state', 'score-error-state', 'score-empty-state', 'score-result-container'];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    // 重置表单
    const form = document.getElementById('score-form');
    if (form) form.reset();
    
    // 设置默认日期
    setDefaultDates();
}

/**
 * 设置默认日期
 * - 评分日期：今日
 * - 历史评分开始日期：一个月前的今天
 * - 历史评分结束日期：今日
 */
export function setDefaultDates() {
    const today = new Date();
    const oneMonthAgo = new Date();
    oneMonthAgo.setMonth(today.getMonth() - 1);
    
    // 格式化日期为 YYYY-MM-DD
    const formatDate = (date) => {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    };
    
    const todayStr = formatDate(today);
    const oneMonthAgoStr = formatDate(oneMonthAgo);
    
    // 设置评分日期
    const scoreDateInput = document.getElementById('score-date-input');
    if (scoreDateInput) {
        scoreDateInput.value = todayStr;
    }
    
    // 设置历史评分日期范围
    const startDateInput = document.getElementById('score-history-start');
    const endDateInput = document.getElementById('score-history-end');
    if (startDateInput) {
        startDateInput.value = oneMonthAgoStr;
    }
    if (endDateInput) {
        endDateInput.value = todayStr;
    }
}

/**
 * 重置查询状态（错误/空状态下的按钮回调）
 */
export function resetScoreQuery() {
    resetScorePageState();
}

/**
 * 初始化个股图谱表单事件绑定
 */
export function setupStockAnalysis() {
    console.log('setupStockAnalysis 被调用');
    // 绑定评分查询表单
    const scoreForm = document.getElementById('score-form');
    console.log('评分表单元素:', scoreForm);

    if (scoreForm) {
        console.log('为评分表单添加提交事件监听器');
        scoreForm.addEventListener('submit', async (e) => {
            console.log('评分表单提交事件触发');
            e.preventDefault();
            await queryStockScore();
        });
    } else {
        console.warn('找不到评分表单元素 score-form');
    }
}

/**
 * 查询个股图谱评分
 * 从表单获取股票代码和日期，调用评分API，渲染结果
 */
export async function queryStockScore() {
    // 获取表单输入值
    const stockCode = document.getElementById('score-stock-code').value.trim();
    const dateInput = document.getElementById('score-date-input').value;
    const btn = document.getElementById('score-query-btn');
    const btnText = document.getElementById('score-btn-text');
    const loadingIcon = document.getElementById('score-loading');

    // 校验股票代码
    if (!stockCode || !/^\d{6}$/.test(stockCode)) {
        const hint = document.getElementById('score-code-hint');
        if (hint) hint.style.display = 'block';
        return;
    }

    // 禁用按钮，显示加载状态
    btn.disabled = true;
    btnText.textContent = '分析中...';
    if (loadingIcon) loadingIcon.style.display = 'inline';

    // 隐藏之前的结果和状态
    hideAllScoreStates();
    // 显示加载状态卡片
    showElement('score-loading-state');

    try {
        // 构建API请求URL
        let url = `/api/stock/score/${stockCode}`;
        // 如果用户选择了日期，转换为 YYYYMMDD 格式
        if (dateInput) {
            const dateParam = dateInput.replace(/-/g, '');
            url += `?date=${dateParam}`;
        }

        console.log('请求评分API:', url);
        const response = await fetch(url);
        const result = await response.json();
        console.log('评分API返回:', result);

        // 隐藏加载状态
        hideElement('score-loading-state');

        // 判断返回结果
        if (result.code === 0 && result.data) {
            // 成功：渲染评分结果
            renderScoreResult(result.data);
            showElement('score-result-container');
            // 滚动到结果区域
            const container = document.getElementById('score-result-container');
            if (container) container.scrollIntoView({ behavior: 'smooth' });
        } else {
            // 失败：显示错误信息
            const errMsg = result.message || '获取评分失败';
            showScoreError(errMsg);
        }
    } catch (error) {
        // 网络异常
        console.error('查询评分异常:', error);
        hideElement('score-loading-state');
        showScoreError('网络请求失败: ' + error.message);
    } finally {
        // 恢复按钮状态
        btn.disabled = false;
        btnText.textContent = '开始分析';
        if (loadingIcon) loadingIcon.style.display = 'none';
    }
}

/**
 * 渲染评分结果到页面各元素
 * @param {Object} data - API返回的评分数据对象
 */
export function renderScoreResult(data) {
    // === 综合信息区域 ===
    setText('score-stock-name', data.stock_name || '--');
    setText('score-stock-code-display', data.stock_code || '--');
    // 日期格式化：YYYY-MM-DD
    setText('score-date-display', data.score_date || '--');

    // 综合得分（保留1位小数）
    const totalScore = data.total_score != null ? Number(data.total_score).toFixed(1) : '--';
    setText('score-total', totalScore);
    // 根据得分设置颜色样式
    applyScoreColor('score-total', data.total_score);

    // 评级
    setText('score-level', data.score_level || '--');
    applyLevelColor('score-level', data.score_level);

    // 一票否决标志
    const vetoFlag = data.veto_flag;
    const vetoEl = document.getElementById('score-veto-flag');
    if (vetoEl) {
        vetoEl.textContent = vetoFlag ? '是' : '否';
        vetoEl.style.color = vetoFlag ? '#dc2626' : '#10b981';
    }

    // 一票否决原因行
    const vetoRow = document.getElementById('score-veto-reason-row');
    const vetoReason = document.getElementById('score-veto-reason');
    if (vetoFlag && data.veto_reason) {
        if (vetoReason) vetoReason.textContent = data.veto_reason;
        if (vetoRow) vetoRow.style.display = 'flex';
    } else {
        if (vetoRow) vetoRow.style.display = 'none';
    }

    // === 五维度评分卡片 ===
    const dims = data.dimensions || {};
    // 技术面
    renderDimensionCard('technical', dims.technical);
    // 资金面
    renderDimensionCard('moneyflow', dims.moneyflow);
    // 基本面
    renderDimensionCard('fundamental', dims.fundamental);
    // 板块强度
    renderDimensionCard('sector', dims.sector);
    // 事件驱动
    renderDimensionCard('event', dims.event);
    
    // 显示评分卡片网格
    const detailGrid = document.querySelector('.score-dimension-grid');
    if (detailGrid) {
        detailGrid.style.display = 'grid';
    }
    
    // === 更新模态窗口中的评分明细 ===
    updateScoreDetailModal(data);
}

/**
 * 更新评分明细模态窗口
 * @param {Object} data - API返回的评分数据对象
 */
export function updateScoreDetailModal(data) {
    // 更新模态窗口标题
    const modalTitle = document.getElementById('score-detail-title');
    if (modalTitle) {
        modalTitle.textContent = `${data.stock_name || data.stock_code} 评分明细`;
    }
    
    // === 五维度评分卡片（模态窗口）===
    const dims = data.dimensions || {};
    // 技术面
    renderDimensionCard('technical', dims.technical, true);
    // 资金面
    renderDimensionCard('moneyflow', dims.moneyflow, true);
    // 基本面
    renderDimensionCard('fundamental', dims.fundamental, true);
    // 板块强度
    renderDimensionCard('sector', dims.sector, true);
    // 事件驱动
    renderDimensionCard('event', dims.event, true);
}

/**
 * 渲染单个维度评分卡片
 * @param {string} dimKey - 维度标识（technical/moneyflow/fundamental/sector/event）
 * @param {Object} dimData - 该维度的评分数据
 * @param {boolean} isModal - 是否渲染到模态窗口
 */
export function renderDimensionCard(dimKey, dimData, isModal = false) {
    if (!dimData) return;

    // 前缀，用于区分主页面和模态窗口的元素ID
    const prefix = isModal ? 'modal-dim-' : 'dim-';

    // 设置维度得分
    const scoreEl = document.getElementById(`${prefix}${dimKey}-score`);
    if (scoreEl) {
        const score = dimData.score != null ? Number(dimData.score).toFixed(1) : '0';
        scoreEl.textContent = score;
        // 根据得分设置颜色
        applyScoreColor(`${prefix}${dimKey}-score`, dimData.score);
    }

    // 根据维度类型渲染详情
    if (dimKey === 'technical') {
        // 命中策略列表
        const strategies = dimData.strategies || [];
        
        // 直接使用数据库中存储的中文策略名称
        const names = strategies.map(s => s.name || s).join('、');
        
        // 一票否决
        const detail = dimData.details || dimData;
        const techVeto = detail.veto || dimData.veto;
        let desc = names || '无';
        if (techVeto && (detail.veto_reason || dimData.veto_reason)) {
            desc = '🚫 ' + (detail.veto_reason || dimData.veto_reason);
        }
        setText(`${prefix}${dimKey}-desc`, desc);
        
        // 更新详细指标
        setText(`${prefix}${dimKey}-strategies`, names || '--');
        setText(`${prefix}${dimKey}-veto`, techVeto ? '是' : '否');
    } else if (dimKey === 'moneyflow') {
        // 资金面详情
        const d = dimData.details || {};
        // 主力净流入金额
        let desc = '';
        if (d.veto && d.veto_reason) {
            desc = '🚫 ' + d.veto_reason;
        } else {
            desc = [];
            if (d.main_net_flow != null) desc.push(formatMoney(d.main_net_flow) + ' (' + (d.main_net_flow_score || 0) + '分)');
            if (d.large_ratio_score != null) desc.push(d.large_ratio_score + '分');
            if (d.north_fund_status != null) desc.push(formatNorthFund(d.north_fund_status) + (d.north_fund_score != null ? ' (' + d.north_fund_score + '分)' : ''));
            if (d.direction_score != null) desc.push(d.direction_score + '分');
            desc = desc.join(' | ');
        }
        setText(`${prefix}${dimKey}-desc`, desc || '--');
        
        // 更新详细指标
        setText(`${prefix}${dimKey}-main-net`, d.main_net_flow != null ? formatMoney(d.main_net_flow) : '--');
        setText(`${prefix}${dimKey}-large-ratio`, d.large_ratio_score != null ? d.large_ratio_score + '分' : '--');
        setText(`${prefix}${dimKey}-north-fund`, d.north_fund_status != null ? formatNorthFund(d.north_fund_status) : '--');
        setText(`${prefix}${dimKey}-direction`, d.direction_score != null ? d.direction_score + '分' : '--');
    } else if (dimKey === 'fundamental') {
        // 基本面详情
        const d = dimData.details || {};
        const desc = [];
        if (d.net_profit_yoy != null) desc.push('净利润同比: ' + d.net_profit_yoy.toFixed(1) + '%');
        if (d.roe != null) desc.push('ROE: ' + d.roe.toFixed(1) + '%');
        if (d.ocf_to_income != null) desc.push('经营现金流/营收: ' + d.ocf_to_income.toFixed(2));
        setText(`${prefix}${dimKey}-desc`, desc.join(' | ') || '--');
        
        // 更新详细指标
        setText(`${prefix}${dimKey}-profit-yoy`, d.net_profit_yoy != null ? d.net_profit_yoy.toFixed(1) + '%' : '--');
        setText(`${prefix}${dimKey}-roe`, d.roe != null ? d.roe.toFixed(1) + '%' : '--');
        setText(`${prefix}${dimKey}-ocf`, d.ocf_to_income != null ? d.ocf_to_income.toFixed(2) : '--');
    } else if (dimKey === 'sector') {
        // 板块强度详情
        const desc = [];
        if (dimData.sector_name != null) desc.push(dimData.sector_name);
        if (dimData.rank_score != null) desc.push('排名: ' + dimData.rank_score + '分');
        if (dimData.moneyflow_score != null) desc.push('资金: ' + dimData.moneyflow_score + '分');
        setText(`${prefix}${dimKey}-desc`, desc.join(' | ') || '--');
        
        // 更新详细指标
        setText(`${prefix}${dimKey}-name`, dimData.sector_name || '--');
        setText(`${prefix}${dimKey}-rank-score`, dimData.rank_score != null ? dimData.rank_score + '分' : '--');
        setText(`${prefix}${dimKey}-moneyflow-score`, dimData.moneyflow_score != null ? dimData.moneyflow_score + '分' : '--');
    } else if (dimKey === 'event') {
        // 事件驱动详情
        const pos = dimData.positive_events || [];
        const neg = dimData.negative_events || [];
        // 一票否决
        const detail = dimData.details || dimData;
        const evtVeto = detail.veto || dimData.veto;
        let desc = '';
        if (evtVeto && (detail.veto_reason || dimData.veto_reason)) {
            desc = '🚫 ' + (detail.veto_reason || dimData.veto_reason);
        } else {
            const events = [];
            if (pos.length > 0) events.push('利好: ' + pos.map(e => e.type).join('、'));
            if (neg.length > 0) events.push('利空: ' + neg.map(e => e.type).join('、'));
            desc = events.join(' | ');
        }
        setText(`${prefix}${dimKey}-desc`, desc || '无');
        
        // 更新详细指标
        setText(`${prefix}${dimKey}-positive`, pos.length > 0 ? pos.map(e => e.type).join('、') : '--');
        setText(`${prefix}${dimKey}-negative`, neg.length > 0 ? neg.map(e => e.type).join('、') : '--');
        setText(`${prefix}${dimKey}-veto`, evtVeto ? '是' : '否');
    }
}

/**
 * 查询历史评分记录
 */
export async function queryScoreHistory() {
    // 获取当前查询的股票代码
    const stockCode = document.getElementById('score-stock-code').value.trim();
    if (!stockCode) {
        alert('请先输入股票代码');
        return;
    }

    const startDate = document.getElementById('score-history-start').value;
    const endDate = document.getElementById('score-history-end').value;

    // 显示加载状态
    hideElement('score-history-table-container');
    hideElement('score-history-empty');
    hideElement('score-history-pagination');
    showElement('score-history-loading');

    try {
        // 构建请求URL
        let url = `/api/stock/history/${stockCode}`;
        const params = [];
        if (startDate) params.push(`start_date=${startDate.replace(/-/g, '')}`);
        if (endDate) params.push(`end_date=${endDate.replace(/-/g, '')}`);
        if (params.length > 0) url += '?' + params.join('&');

        const response = await fetch(url);
        const result = await response.json();

        hideElement('score-history-loading');

        if (result.code === 0 && result.data && result.data.length > 0) {
            // 渲染历史表格
            renderScoreHistoryTable(result.data);
            showElement('score-history-table-container');
        } else {
            // 无数据
            showElement('score-history-empty');
        }
    } catch (error) {
        console.error('查询历史评分失败:', error);
        hideElement('score-history-loading');
        showElement('score-history-empty');
    }
}

/**
 * 渲染历史评分表格
 * @param {Array} records - 历史评分记录数组
 */
export function renderScoreHistoryTable(records) {
    const tbody = document.getElementById('score-history-tbody');
    if (!tbody) return;

    // 清空旧数据
    tbody.innerHTML = '';
    // 逐行渲染
    records.forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${r.score_date || '--'}</td>
            <td style="font-weight:600;">${r.total_score != null ? Number(r.total_score).toFixed(1) : '--'}</td>
            <td>${r.score_level || '--'}</td>
            <td>${r.technical_score != null ? Number(r.technical_score).toFixed(1) : '--'}</td>
            <td>${r.moneyflow_score != null ? Number(r.moneyflow_score).toFixed(1) : '--'}</td>
            <td>${r.fundamental_score != null ? Number(r.fundamental_score).toFixed(1) : '--'}</td>
            <td>${r.sector_score != null ? Number(r.sector_score).toFixed(1) : '--'}</td>
            <td>${r.event_score != null ? Number(r.event_score).toFixed(1) : '--'}</td>
        `;
        tbody.appendChild(tr);
    });
}

/** 隐藏所有评分状态卡片和结果容器 */
export function hideAllScoreStates() {
    ['score-loading-state', 'score-error-state', 'score-empty-state', 'score-result-container'].forEach(id => {
        hideElement(id);
    });
}

/** 显示错误状态 */
export function showScoreError(msg) {
    setText('score-error-message', msg);
    showElement('score-error-state');
}

/** 显示指定元素 */
export function showElement(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = '';
}

/** 隐藏指定元素 */
export function hideElement(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

/** 安全设置文本内容 */
export function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

/**
 * 根据得分值设置元素颜色
 * ≥80 绿色, 60-79 蓝色, 40-59 橙色, 20-39 红色, <20 紫色, -100 黑色
 */
export function applyScoreColor(elementId, score) {
    const el = document.getElementById(elementId);
    if (!el || score == null) return;
    // 颜色映射
    if (score <= -100) el.style.color = '#000000';
    else if (score < 20) el.style.color = '#9C27B0';
    else if (score < 40) el.style.color = '#F44336';
    else if (score < 60) el.style.color = '#FF9800';
    else if (score < 80) el.style.color = '#2196F3';
    else el.style.color = '#4CAF50';
}

/** 根据评级文本设置颜色 */
export function applyLevelColor(elementId, level) {
    const el = document.getElementById(elementId);
    if (!el || !level) return;
    const colorMap = {
        '强烈推荐': '#4CAF50', '推荐': '#2196F3', '中性': '#FF9800',
        '谨慎': '#F44336', '回避': '#9C27B0', '淘汰': '#000000'
    };
    el.style.color = colorMap[level] || '#333';
}

/** 格式化资金金额（万元） */
export function formatMoney(val) {
    if (val == null) return '--';
    if (Math.abs(val) >= 10000) return (val / 10000).toFixed(1) + '亿';
    return val.toFixed(0) + '万';
}

/** 格式化北向资金状态 */
export function formatNorthFund(status) {
    const map = { 'increase': '增持', 'decrease': '减持', 'hold': '持平', 'none': '无持股' };
    return map[status] || status || '--';
}

/**
 * 显示股票评分详细信息
 * @param {string} code - 股票代码
 */
export async function showScoreDetail(code, date) {
    // 显示评分明细模态窗口
    const modal = document.getElementById('score-detail-modal');
    if (modal) {
        modal.classList.add('active');
    }
    
    // 加载评分数据
    await loadStockScoreData(code, date);
}

export function closeScoreDetailModal() {
    // 关闭评分明细模态窗口
    const modal = document.getElementById('score-detail-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

/**
 * 加载股票评分数据
 * @param {string} code - 股票代码
 */
export async function loadStockScoreData(code, date) {
    try {
        // 构建API请求URL
        let url = `/api/stock/score/${code}`;
        // 如果提供了日期参数，添加到URL中
        if (date) {
            // 转换日期格式为YYYYMMDD
            const dateParam = date.replace(/-/g, '');
            url += `?date=${dateParam}`;
        }
        
        console.log('请求评分API:', url);
        const response = await fetch(url);
        const result = await response.json();
        console.log('评分API返回:', result);

        // 判断返回结果
        if (result.code === 0 && result.data) {
            // 成功：更新评分明细模态窗口
            updateScoreDetailModal(result.data);
        } else {
            // 失败：显示错误信息
            console.error('获取评分失败:', result.message);
        }
    } catch (error) {
        // 网络异常
        console.error('查询评分异常:', error);
    }
}
