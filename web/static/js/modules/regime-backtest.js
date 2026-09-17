/**
 * 自适应回测页面（ADX regime 路由）
 *
 * 依赖接口：
 *   GET  /api/trading/backtest/regime/config   → 路由配置（默认=上次保存，首次=内置默认）
 *   POST /api/trading/backtest/regime/config   → 保存路由配置
 *   POST /api/trading/backtest/regime/run      → 执行回测（同步，与策略回测一致）
 *
 * 页面只填起止日期；初始资金/单笔比例等沿用「回测配置」页参数；
 * 选股与择时策略由每日 ADX 自动决定（本页可配置每种 regime 的对应策略与仓位）。
 */

const REGIME_ORDER = ['明确', '萌芽', '震荡'];

// 选股策略「空值」= 空仓：选中后该档位当日仍执行选股与评分流程，但选股结果固定为 0 只；
// 其余流程（卖出/止损/择时/买入方式/持仓管理/股票池维护）完全不变。
// 后端识别口径见 trading/regime_router.py → NO_SELECTION_VALUES（空仓/none/无）
const RS_NO_SELECTION = '空仓';

// 买入执行方式（对应后端 config['buy_execution'].mode）
// 默认规则：明确/萌芽 → open（T日开盘价）、震荡 → ma_limit（均线委托价）
const BUY_EXECUTION_OPTIONS = [
    { key: 'open', name: 'open（开盘价）' },
    { key: 'ma_limit', name: 'ma_limit（均线委托价）' },
];

const _regimeState = {
    rules: {},
    selectors: [],
    timings: [],      // [{key, name}]
    chart: null,
    loading: false,
};

function _rsFetchJSON(url, options) {
    return fetch(url, options).then(r => r.json().then(j => {
        if (!r.ok) throw new Error((j && j.message) || `HTTP ${r.status}`);
        return j;
    }));
}

function _rsExtractList(payload) {
    const d = payload && (payload.data !== undefined ? payload.data : payload);
    if (Array.isArray(d)) return d;
    if (d && Array.isArray(d.items)) return d.items;
    if (d && Array.isArray(d.strategies)) return d.strategies;
    if (d && Array.isArray(d.timing_strategies)) return d.timing_strategies;
    return [];
}

function _rsSetStatus(msg, isError) {
    const el = document.getElementById('regime-status');
    if (!el) return;
    el.textContent = msg || '';
    el.style.color = isError ? '#d4380d' : '#666';
}

async function _rsLoadOptions() {
    // 选股策略（中文名）
    try {
        const p = await _rsFetchJSON('/api/trading/backtest/strategies');
        _regimeState.selectors = _rsExtractList(p).map(x =>
            typeof x === 'string' ? x : (x.name || x.display_name || x.strategy_name)
        ).filter(Boolean);
    } catch (e) {
        console.warn('[自适应回测] 加载选股策略失败', e);
    }
    if (!_regimeState.selectors.length) {
        try {
            const p = await _rsFetchJSON('/api/strategies');
            _regimeState.selectors = _rsExtractList(p).map(x =>
                typeof x === 'string' ? x : (x.name || x.display_name || x.strategy_name)
            ).filter(Boolean);
        } catch (e) {
            console.warn('[自适应回测] 备用选股策略接口失败', e);
        }
    }
    // 追加选股「空值」（空仓）：无论接口是否返回都要可选项，且只保留一个
    _regimeState.selectors = [RS_NO_SELECTION].concat(
        _regimeState.selectors.filter(x => x !== RS_NO_SELECTION));
    // 择时策略（key + 中文名）
    try {
        const p = await _rsFetchJSON('/api/timing-strategies');
        _regimeState.timings = _rsExtractList(p).map(x => {
            if (typeof x === 'string') return { key: x, name: x };
            const key = x.key || x.value || x.name;
            return { key: key, name: x.display_name || x.label || x.name || key };
        }).filter(t => t.key);
    } catch (e) {
        console.warn('[自适应回测] 加载择时策略失败', e);
    }
}

function _rsMakeSelect(field, regime, current, options, pairs) {
    const td = document.createElement('td');
    td.style.cssText = 'padding:6px;border:1px solid #e0e0e0;';
    const sel = document.createElement('select');
    sel.dataset.field = field;
    sel.dataset.regime = regime;
    sel.style.cssText = 'width:100%;padding:4px;';
    options.forEach(opt => {
        const o = document.createElement('option');
        if (pairs) {
            o.value = opt.key;
            o.textContent = opt.name;
        } else {
            o.value = opt;
            o.textContent = opt;
        }
        if (opt === current || (pairs && opt.key === current)) o.selected = true;
        sel.appendChild(o);
    });
    // 当前值不在选项中时补一个（避免静默丢失配置）
    if (current && !options.some(opt => (pairs ? opt.key : opt) === current)) {
        const o = document.createElement('option');
        o.value = current;
        o.textContent = current + '（未在列表）';
        o.selected = true;
        sel.insertBefore(o, sel.firstChild);
    }
    td.appendChild(sel);
    return td;
}

function _rsRenderRules() {
    const tbody = document.getElementById('regime-rules-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    REGIME_ORDER.forEach(reg => {
        const rule = _regimeState.rules[reg] || {};
        const tr = document.createElement('tr');

        const tdReg = document.createElement('td');
        tdReg.style.cssText = 'padding:6px;border:1px solid #e0e0e0;white-space:nowrap;';
        tdReg.textContent = reg;
        tr.appendChild(tdReg);

        tr.appendChild(_rsMakeSelect('selector', reg, rule.selector, _regimeState.selectors));
        tr.appendChild(_rsMakeSelect('timing', reg, rule.timing,
            _regimeState.timings, true));

        const tdPos = document.createElement('td');
        tdPos.style.cssText = 'padding:6px;border:1px solid #e0e0e0;';
        const inp = document.createElement('input');
        inp.type = 'number';
        inp.min = 0; inp.max = 1; inp.step = 0.1;
        inp.dataset.field = 'position';
        inp.dataset.regime = reg;
        inp.value = (rule.position !== undefined && rule.position !== null) ? rule.position : 1.0;
        inp.style.cssText = 'width:80px;padding:4px;';
        tdPos.appendChild(inp);
        tr.appendChild(tdPos);

        // 买入方式：列顺序须与表头一致（Regime | 选股 | 择时 | 仓位 | 买入方式）
        tr.appendChild(_rsMakeSelect('buy_execution', reg, rule.buy_execution,
            BUY_EXECUTION_OPTIONS, true));
        tbody.appendChild(tr);
    });
}

function _rsCollectRules() {
    const rules = {};
    REGIME_ORDER.forEach(reg => {
        const sel = document.querySelector(
            `#regime-rules-body select[data-field="selector"][data-regime="${reg}"]`);
        const tim = document.querySelector(
            `#regime-rules-body select[data-field="timing"][data-regime="${reg}"]`);
        const pos = document.querySelector(
            `#regime-rules-body input[data-field="position"][data-regime="${reg}"]`);
        const bex = document.querySelector(
            `#regime-rules-body select[data-field="buy_execution"][data-regime="${reg}"]`);
        rules[reg] = {
            selector: sel ? sel.value : '',
            timing: tim ? tim.value : '',
            position: pos ? parseFloat(pos.value) : 1.0,
            buy_execution: bex ? bex.value : '',
        };
    });
    return rules;
}

/**
 * 更新进度条（p 为空则隐藏）
 */
function _rsSetProgress(p) {
    const box = document.getElementById('regime-progress');
    if (!box) return;
    if (!p) { box.style.display = 'none'; return; }
    box.style.display = 'block';
    const pct = Math.max(0, Math.min(100, Number(p.percent) || 0));
    const bar = document.getElementById('regime-progress-bar');
    const txt = document.getElementById('regime-progress-text');
    const num = document.getElementById('regime-progress-percent');
    if (bar) bar.style.width = pct + '%';
    if (num) num.textContent = pct.toFixed(1) + '%';
    if (txt) {
        txt.textContent = p.running
            ? `回测执行中：${p.current_date || '准备中'}（${p.done_days || 0}/${p.total_days || 0} 个交易日）`
            : (p.message || '完成');
    }
}

/** 轮询后端进度（失败静默，不打断回测等待） */
async function _rsPollProgress() {
    try {
        const r = await _rsFetchJSON('/api/trading/backtest/regime/progress');
        if (r && r.success) _rsSetProgress(r.data);
    } catch (e) {
        console.warn('[自适应回测] 进度查询失败', e);
    }
}

/**
 * 渲染成交明细（订单级）
 *
 * 数据表按**订单**存储：首仓(buy) / 加仓(add) / 卖出(sell) 各一行，
 * buy/add 行本身没有 sell_date。因此不能把“无 sell_date”当成“持仓中”——
 * 否则 226 笔首仓 + 168 笔加仓订单会被全部误标为“持仓中”。
 *
 * 后端 `_attach_position_status` 已为每笔订单补齐 `position_status`(已平仓/持仓中)
 * 与配对到的 `matched_sell_*`，这里据此渲染：
 *   - 已平仓订单：显示其所属持仓的卖出日/卖出价/收益率/盈亏
 *   - 真正未平仓：才显示“持仓中”
 *   - 类型列：首仓 / 加仓 / 卖出原因（原先 buy/add 行被硬编码成 'buy'）
 */
function _rsRenderTrades(trades) {
    const body = document.getElementById('regime-trades-body');
    if (!body) return;
    const list = trades || [];
    const setTxt = (id, v) => {
        const el = document.getElementById(id);
        if (el) el.textContent = v;
    };
    const kindOf = t => t.order_kind || t.trade_type || '';
    const buys = list.filter(t => kindOf(t) === 'buy');
    const adds = list.filter(t => kindOf(t) === 'add');
    const sells = list.filter(t => kindOf(t) === 'sell');
    // 只有后端明确标注 position_status='持仓中' 的订单才算“期末持仓中”；
    // 缺字段时不得默认“持仓中”（自适应回测响应曾漏配对，324 笔买/加仓被全部误计）
    const opened = list.filter(t => t.position_status === '持仓中');
    setTxt('regime-trades-count', list.length);
    setTxt('regime-trades-buy', buys.length);
    setTxt('regime-trades-add', adds.length);
    setTxt('regime-trades-closed', sells.length);
    setTxt('regime-trades-open', opened.length);

    const cell = 'padding:6px;border:1px solid #e0e0e0;';
    if (!list.length) {
        body.innerHTML = `<tr><td colspan="10" style="padding:10px;text-align:center;color:#888;">暂无成交记录</td></tr>`;
        return;
    }
    const fmt = v => (v === undefined || v === null || v === '') ? '-' : v;
    const num = v => (v === undefined || v === null || v === '') ? '-' : Number(v).toFixed(2);
    body.innerHTML = list.map(t => {
        const k = kindOf(t);
        const isSell = (k === 'sell');
        const closed = isSell || t.position_status === '已平仓';
        // 缺 position_status 的买/加仓行：状态未知（不是“持仓中”）
        const isOpen = !closed && t.position_status === '持仓中';
        // 已平仓的 buy/add 行：用配对卖出信息；卖出行：用自身字段
        const sd = isSell ? t.sell_date : (t.matched_sell_date || '');
        const sp = isSell ? t.sell_price : t.matched_sell_price;
        const rr = Number((isSell ? t.return_rate : t.matched_return_rate) || 0);
        const pl = isSell ? t.profit_loss : t.matched_profit_loss;
        const color = rr >= 0 ? '#cf1322' : '#3f8600';
        const typeLabel = k === 'buy' ? '首仓' : (k === 'add' ? '加仓' : (t.sell_type || '卖出'));
        return `<tr>
            <td style="${cell}">${fmt(t.stock_code)}</td>
            <td style="${cell}">${fmt(t.stock_name)}</td>
            <td style="${cell}">${fmt(t.buy_date)}</td>
            <td style="${cell}">${num(t.buy_price)}</td>
            <td style="${cell}">${closed ? fmt(sd) : (isOpen ? '持仓中' : '-')}</td>
            <td style="${cell}">${closed ? num(sp) : '-'}</td>
            <td style="${cell}">${fmt(t.quantity)}</td>
            <td style="${cell}color:${closed ? color : '#888'};">${closed ? rr.toFixed(2) + '%' : '-'}</td>
            <td style="${cell}color:${closed ? color : '#888'};">${closed ? num(pl) : '-'}</td>
            <td style="${cell}">${typeLabel}</td>
        </tr>`;
    }).join('');
}

function _rsMetricCard(label, value, color) {
    return `<div style="border:1px solid #e8e8e8;border-radius:6px;padding:10px 12px;">
        <div style="font-size:12px;color:#888;">${label}</div>
        <div style="font-size:18px;font-weight:600;color:${color || '#333'};">${value}</div>
    </div>`;
}

function _rsRenderResult(data) {
    // ⚠️ 必须先显示结果区：Chart.js 在 display:none 的容器内初始化会得到 0 尺寸，图表不可见
    const resultBox = document.getElementById('regime-result');
    if (resultBox) resultBox.style.display = 'block';

    const perf = data.performance || {};
    const metrics = document.getElementById('regime-metrics');
    metrics.innerHTML = [
        _rsMetricCard('总收益', (perf.total_return !== undefined ? perf.total_return.toFixed(2) + '%' : '-'),
            perf.total_return >= 0 ? '#cf1322' : '#3f8600'),
        _rsMetricCard('盈亏比', perf.profit_loss_ratio !== undefined ? perf.profit_loss_ratio.toFixed(2) : '-'),
        _rsMetricCard('最大回撤', perf.max_drawdown !== undefined ? perf.max_drawdown.toFixed(2) + '%' : '-'),
        _rsMetricCard('夏普', perf.sharpe_ratio !== undefined ? perf.sharpe_ratio.toFixed(2) : '-'),
        _rsMetricCard('胜率', perf.win_rate !== undefined ? perf.win_rate.toFixed(1) + '%' : '-'),
        _rsMetricCard('交易数', perf.total_trades !== undefined ? perf.total_trades : '-'),
    ].join('');

    // regime 贡献
    const statsBody = document.getElementById('regime-stats-body');
    statsBody.innerHTML = '';
    (data.regime_stats || []).forEach(s => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td style="padding:6px;border:1px solid #e0e0e0;">${s.regime}</td>
            <td style="padding:6px;border:1px solid #e0e0e0;">${s.trades}</td>
            <td style="padding:6px;border:1px solid #e0e0e0;">${s.win_rate}%</td>
            <td style="padding:6px;border:1px solid #e0e0e0;color:${s.avg_return >= 0 ? '#cf1322' : '#3f8600'};">${s.avg_return}%</td>`;
        statsBody.appendChild(tr);
    });

    // 切换记录
    const swBody = document.getElementById('regime-switches-body');
    swBody.innerHTML = '';
    (data.strategy_switches || []).forEach(s => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td style="padding:6px;border:1px solid #e0e0e0;">${s.date}</td>
            <td style="padding:6px;border:1px solid #e0e0e0;">${s.from}</td>
            <td style="padding:6px;border:1px solid #e0e0e0;">${s.to}</td>
            <td style="padding:6px;border:1px solid #e0e0e0;">${s.regime || ''}</td>`;
        swBody.appendChild(tr);
    });

    // 净值曲线
    const canvas = document.getElementById('regime-equity-chart');
    const history = data.capital_history || [];
    const dates = data.dates || [];
    if (!canvas) {
        console.warn('[regime] 找不到 #regime-equity-chart 容器');
    } else if (!window.Chart) {
        console.warn('[regime] Chart.js 未加载，无法绘制净值曲线');
        const holder = canvas.parentElement;
        if (holder) {
            holder.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#6b7280;font-size:13px;">图表库未加载（Chart.js）</div>';
        }
    } else if (history.length <= 1) {
        console.warn('[regime] 净值数据不足，capital_history 长度 =', history.length);
        const holder = canvas.parentElement;
        if (holder) {
            holder.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#6b7280;font-size:13px;">暂无净值曲线数据</div>';
        }
    } else {
        try {
            if (_regimeState.chart) {
                _regimeState.chart.destroy();
                _regimeState.chart = null;
            }
            // labels 与 history 长度对齐：history[0] 为初始资金
            const labels = ['起始'].concat(dates.map(d => String(d)));
            _regimeState.chart = new window.Chart(canvas.getContext('2d'), {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: '总资产',
                        data: history,
                        borderColor: '#1677ff',
                        backgroundColor: 'rgba(22,119,255,0.08)',
                        fill: true,
                        pointRadius: 0,
                        borderWidth: 1.6,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: { x: { ticks: { maxTicksLimit: 10 } } }
                }
            });
        } catch (e) {
            console.error('[regime] 绘制净值曲线失败:', e);
        }
    }
    // 成交明细
    _rsRenderTrades(data.trades);

    document.getElementById('regime-result').style.display = 'block';
}

async function _rsRunBacktest() {
    if (_regimeState.loading) return;
    const startDate = document.getElementById('regime-start-date').value;
    const endDate = document.getElementById('regime-end-date').value;
    if (!startDate || !endDate) {
        _rsSetStatus('请先选择开始与结束日期', true);
        return;
    }
    if (startDate > endDate) {
        _rsSetStatus('开始日期不能晚于结束日期', true);
        return;
    }
    const rules = _rsCollectRules();
    const emptyRegimes = Object.keys(rules).filter(k => !rules[k].selector);
    if (emptyRegimes.length) {
        _rsSetStatus(`以下 regime 未选择选股策略：${emptyRegimes.join('、')}`, true);
        return;
    }

    _regimeState.loading = true;
    _rsSetStatus('回测执行中，请稍候（区间越长耗时越久）...');
    const btn = document.getElementById('regime-run-btn');
    if (btn) btn.disabled = true;

    // 进度：先本地置零，再每 1s 轮询后端进度
    _rsSetProgress({ running: true, percent: 0, done_days: 0, total_days: 0,
                     current_date: '', message: '准备中' });
    const _progressTimer = setInterval(_rsPollProgress, 1000);
    _rsPollProgress();

    try {
        const payload = {
            start_date: startDate,
            end_date: endDate,
            confirm_days: parseInt(document.getElementById('regime-confirm-days').value || '5', 10),
            rules: rules,
        };
        const res = await _rsFetchJSON('/api/trading/backtest/regime/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.success) throw new Error(res.message || '回测失败');
        _rsRenderResult(res.data || {});
        const perf = (res.data || {}).performance || {};
        const rid = (res.data || {}).result_id;
        _rsSetStatus(`完成：总收益 ${perf.total_return !== undefined ? perf.total_return.toFixed(2) : '-'}%`
            + `，切换 ${((res.data || {}).strategy_switches || []).length} 次`
            + (rid ? `，结果已保存（#${rid}）` : '，结果保存失败'));
    } catch (e) {
        console.error('[自适应回测] 失败', e);
        _rsSetStatus('回测失败：' + e.message, true);
    } finally {
        clearInterval(_progressTimer);
        await _rsPollProgress();       // 收尾刷新一次（显示 100%/完成）
        _regimeState.loading = false;
        if (btn) btn.disabled = false;
    }
}

async function _rsSaveConfig() {
    const rules = _rsCollectRules();
    const confirmDays = parseInt(document.getElementById('regime-confirm-days').value || '5', 10);
    try {
        const res = await _rsFetchJSON('/api/trading/backtest/regime/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rules: rules, confirm_days: confirmDays }),
        });
        _rsSetStatus(res.success ? '配置已保存为默认（原文件已备份 .bak）' : ('保存失败：' + res.message), !res.success);
        if (res.success) {
            // 保存成功后同步本地状态，保证后续渲染/运行与后端一致
            _regimeState.rules = rules;
        }
    } catch (e) {
        _rsSetStatus('保存失败：' + e.message, true);
    }
}

export async function initRegimeBacktestPage() {
    // 默认区间：近一年
    const today = new Date();
    const startInput = document.getElementById('regime-start-date');
    const endInput = document.getElementById('regime-end-date');
    if (startInput && !startInput.value) {
        const s = new Date(today.getTime() - 365 * 24 * 3600 * 1000);
        startInput.value = s.toISOString().slice(0, 10);
    }
    if (endInput && !endInput.value) {
        endInput.value = today.toISOString().slice(0, 10);
    }

    if (!_regimeState.selectors.length || !_regimeState.timings.length) {
        await _rsLoadOptions();
    }

    // 每次进入页面都拉取「上次保存的配置」，保证展示与后端一致
    // （原实现仅在 _regimeState.rules 为空时拉取，SPA 切页面不会重置该变量，
    //   导致第二次以后回到本页仍显示旧值/默认值）
    try {
        const res = await _rsFetchJSON('/api/trading/backtest/regime/config',
            { cache: 'no-store' });
        const d = (res && res.data) || {};
        _regimeState.rules = d.rules || {};
        const cd = document.getElementById('regime-confirm-days');
        if (cd && d.confirm_days) cd.value = d.confirm_days;
        if (d.is_default) {
            _rsSetStatus('当前为内置默认配置（尚未保存过）');
        } else {
            _rsSetStatus('已加载上次保存的配置');
        }
    } catch (e) {
        console.warn('[自适应回测] 加载配置失败', e);
        _rsSetStatus('加载路由配置失败：' + e.message, true);
    }

    _rsRenderRules();

    const runBtn = document.getElementById('regime-run-btn');
    if (runBtn && !runBtn.dataset.bound) {
        runBtn.addEventListener('click', _rsRunBacktest);
        runBtn.dataset.bound = '1';
    }
    const saveBtn = document.getElementById('regime-save-config-btn');
    if (saveBtn && !saveBtn.dataset.bound) {
        saveBtn.addEventListener('click', _rsSaveConfig);
        saveBtn.dataset.bound = '1';
    }
}

// 兼容：app.js 若以命名空间方式装配
export default { initRegimeBacktestPage };
