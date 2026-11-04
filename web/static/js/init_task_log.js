/** Render initialization results from the existing read-only progress API. */
const INIT_STEP_NAMES = [
    '基础数据与历史行情', '交易日历', '个股资金流向',
    '个股基本面', '个股公告事件', '大盘指数 ADX'
];
const INIT_STATUS_LABELS = {
    pending: '暂无结果', running: '执行中', paused: '已暂停',
    success: '成功', partial: '部分成功', failed: '失败',
    skipped: '已跳过', reported: '已结束，待核验', cancelled: '已取消'
};
let initLogSnapshot = { taskId: '', logs: [] };
try {
    const saved = JSON.parse(localStorage.getItem('khunter.initLogSnapshot') || 'null');
    if (saved && typeof saved.taskId === 'string' && Array.isArray(saved.logs)) {
        initLogSnapshot = { taskId: saved.taskId, logs: saved.logs.filter(x => typeof x === 'string').slice(-500) };
    }
} catch (_) { /* Storage may be unavailable; server logs still work. */ }

function initResultNumber(text, key) {
    const match = text.match(new RegExp("['\"]" + key + "['\"]\\s*:\\s*(\\d+)"));
    return match ? Number(match[1]) : null;
}

function classifyInitResult(text) {
    if (/^\s*(?:⏭|ℹ).*跳过/.test(text)) return 'skipped';
    if (/^\s*✗/.test(text)) return 'failed';
    const failed = initResultNumber(text, 'failed') || 0;
    const added = initResultNumber(text, 'added') || 0;
    const updated = initResultNumber(text, 'updated') || 0;
    const actual = initResultNumber(text, 'actual');
    const expected = initResultNumber(text, 'expected');
    if (failed > 0 || /失败\s*✗/.test(text) || (expected !== null && actual !== null && actual < expected)) {
        return added + updated + (actual || 0) > 0 ? 'partial' : 'failed';
    }
    if (/skipped[：:]|跳过/.test(text)) return 'partial';
    return 'success';
}

function describeInitResult(text) {
    const fields = { added: '新增', updated: '更新', changed: '变更', failed: '失败', skipped: '跳过', total: '总计', days: '采集天数' };
    const parts = [];
    for (const [key, label] of Object.entries(fields)) {
        const value = initResultNumber(text, key);
        if (value !== null) parts.push(`${label} ${value}`);
    }
    const actual = initResultNumber(text, 'actual');
    const expected = initResultNumber(text, 'expected');
    if (actual !== null && expected !== null) parts.push(`覆盖 ${actual}/${expected}`);
    if (parts.length) return parts.join('；');
    return text.length > 350 ? text.slice(0, 350) + '…（完整内容见下方日志）' : text;
}

function summarizeInitTask(data, logs) {
    const steps = new Map(INIT_STEP_NAMES.map(name => [name, { name, status: 'pending', result: '后台尚未提供该步骤结果' }]));
    const base = steps.get(INIT_STEP_NAMES[0]);
    for (const text of logs) {
        if (/正在初始化数据/.test(text)) Object.assign(base, { status: 'running', result: text });
        if (/^✓ 数据初始化完成/.test(text)) Object.assign(base, {
            status: 'reported', result: '基础数据与行情流程已结束；后台未提供内部各子步骤的成功/失败明细，不能据此认定全部成功。'
        });
        const match = text.match(/\[([^\]]+)\]/);
        if (!match) continue;
        const name = match[1];
        // Keep per-index results too, when the backend reports them separately.
        if (!steps.has(name)) steps.set(name, { name, status: 'pending', result: '' });
        const step = steps.get(name);
        if (/开始初始化/.test(text)) Object.assign(step, { status: 'running', result: text });
        else if (/完成|失败|跳过/.test(text)) Object.assign(step, {
            status: classifyInitResult(text), result: describeInitResult(text)
        });
    }
    const current = String(data.currentTask || '');
    if (data.running || data.paused || data.status === 'running') {
        let currentStep = [...steps.values()].find(step => step.status === 'running' && current.includes(step.name));
        if (!currentStep && /基础数据|K线|行业数据|板块数据|事件数据/.test(current) && base.status !== 'reported') currentStep = base;
        if (currentStep) Object.assign(currentStep, { status: data.paused ? 'paused' : 'running', result: current });
    } else if (['failed', 'cancelled'].includes(data.status)) {
        for (const step of steps.values()) {
            if (step.status === 'running') Object.assign(step, { status: data.status, result: data.message || current });
        }
    } else if (data.status === 'completed') {
        for (const step of steps.values()) {
            if (step.status === 'running') Object.assign(step, { status: 'reported', result: '任务已结束，但后台未返回该步骤明确结果，请核验日志与数据覆盖。' });
        }
    }
    return [...steps.values()];
}

function renderInitTaskLog(data) {
    const panel = document.getElementById('init-task-log-panel');
    if (!panel) return;
    if (data.status === 'idle') { panel.style.display = 'none'; return; }
    panel.style.display = 'block';
    const incoming = (data.logs || []).filter(x => typeof x === 'string');
    const task = incoming.join('\n').match(/初始化任务\s+(INIT_\d+_\d+)/);
    if (task && task[1] !== initLogSnapshot.taskId) initLogSnapshot = { taskId: task[1], logs: [] };
    initLogSnapshot.logs = [...new Set([...initLogSnapshot.logs, ...incoming])].slice(-500);
    try { localStorage.setItem('khunter.initLogSnapshot', JSON.stringify(initLogSnapshot)); } catch (_) {}
    const steps = summarizeInitTask(data, initLogSnapshot.logs);
    const tbody = document.getElementById('init-step-log-rows');
    tbody.replaceChildren();
    const colors = { success: '#15803d', failed: '#b91c1c', partial: '#b45309', running: '#0369a1', paused: '#b45309' };
    for (const step of steps) {
        const tr = document.createElement('tr');
        for (const text of [step.name, INIT_STATUS_LABELS[step.status], step.result]) {
            const td = document.createElement('td');
            td.textContent = text;
            td.style.cssText = 'padding:10px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top;overflow-wrap:anywhere;';
            tr.appendChild(td);
        }
        tr.children[1].style.color = colors[step.status] || '#64748b';
        tr.children[1].style.whiteSpace = 'nowrap';
        tbody.appendChild(tr);
    }
    const counts = status => steps.filter(step => step.status === status).length;
    const state = { running: '执行中', paused: '已暂停', completed: '任务已结束', failed: '任务失败', cancelled: '任务已取消' }[data.status] || data.status;
    const hasIssues = counts('failed') + counts('partial') > 0;
    const summary = document.getElementById('init-task-log-summary');
    summary.textContent = `${state} · 成功 ${counts('success')} · 部分成功 ${counts('partial')} · 失败 ${counts('failed')} · 跳过 ${counts('skipped')} · 待核验 ${counts('reported')}`;
    summary.style.color = hasIssues ? '#b45309' : '#334155';
    document.getElementById('init-task-log-time').textContent = `最后刷新：${new Date().toLocaleTimeString('zh-CN')}`;
    document.getElementById('init-task-raw-logs').textContent = initLogSnapshot.logs.join('\n') || '后台暂无日志';
    if (data.status === 'completed') {
        const title = document.getElementById('init-status-text');
        const icon = document.getElementById('init-status-icon');
        if (title) {
            title.textContent = hasIssues ? '初始化已结束，部分步骤未成功' : '初始化已结束，请核对各步骤结果';
            title.style.color = hasIssues ? '#b45309' : '#334155';
        }
        if (icon) icon.textContent = hasIssues ? '⚠️' : 'ℹ️';
    }
}
