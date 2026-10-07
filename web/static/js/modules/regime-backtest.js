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
 * 格式化秒数为时长文案（自适应显示 HH:MM:SS 或 MM:SS）
 * @param {number} seconds - 秒数
 * @returns {string} 格式化后的时长，例如 "02:15" 或 "01:02:03"
 */
function _rsFormatDuration(seconds) {
    // 输入校验：非数字或负数返回 "00:00"
    if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
    const s = Math.round(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    // 不足1小时显示 MM:SS，超过1小时显示 HH:MM:SS
    const pad = n => String(n).padStart(2, '0');
    return h > 0 ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

/**
 * 格式化 Date 为时刻文案 HH:MM
 * @param {Date} date - 日期对象
 * @returns {string} 形如 "14:50"
 */
function _rsFormatClock(date) {
    const pad = n => String(n).padStart(2, '0');
    return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * 更新进度条（p 为空则隐藏）
 * 预估算法：已耗时/已处理交易日 = 单日耗时；剩余交易日 × 单日耗时 = 剩余时间
 * 前3个交易日数据不稳定，仅显示已耗时，不展示预估（避免早期抖动）
 */
function _rsSetProgress(p) {
    const box = document.getElementById('regime-progress');
    if (!box) return;
    // 【2026-09-20】空闲且本地未在跑 → 直接隐藏。
    //   原实现仅在 p 为空时隐藏 ✗：后端在"引擎尚未上报"时会返回空闲快照
    //   （running=false、message=''、percent=0 ✗）→ 于是露出一个 0.0% 的空进度条，
    //   标签还落到 `p.message || '完成'` 显示「完成」✗（本次问题的直接现象 ✓）
    const _loading = !!(_regimeState && _regimeState.loading);
    _regimeState.lastProgressRunning = !!(p && p.running);   // 【2026-09-20】供"连接中断后续监控"判断 ✓
    if (!p || (!p.running && !_loading)) { box.style.display = 'none'; return; }
    box.style.display = 'block';
    const pct = Math.max(0, Math.min(100, Number(p.percent) || 0));
    const bar = document.getElementById('regime-progress-bar');
    const txt = document.getElementById('regime-progress-text');
    const num = document.getElementById('regime-progress-percent');
    // eta：预估时间展示元素
    const eta = document.getElementById('regime-progress-eta');
    if (bar) bar.style.width = pct + '%';
    if (num) num.textContent = pct.toFixed(1) + '%';
    if (txt) {
        if (p.running) {
            txt.textContent = `回测执行中：${p.current_date || '准备中'}（${p.done_days || 0}/${p.total_days || 0} 个交易日）`;
        } else {
            // 【2026-09-20】注意：这里**不能**依据 p.message / p.percent 判断"本轮已结束" ✗ ——
            //   上一轮遗留的 percent=100 / message='完成' 会在新一轮引擎尚未
            //   `_begin_regime_progress`（还没开始上报）时被读到 ✗ → 误显示「完成」✗
            //   （这正是本次"执行中却显示完成"的现象之一 ✓）。
            //   故：运行期间（_loading=true）一律显示"执行中" ✓；结束后进度区自动隐藏 ✓。
            // 【2026-09-20】本地仍在跑（loading ✓）但引擎还没上报 → 明确写"执行中"，
            //   并给出本地已耗时 ✓，绝不显示"完成" ✗
            // 【2026-09-20】去冗余 ✓：不再在这里显示"已耗时"（原与下面 ETA 行重复 ✗），
            //   且此阶段属**预处理/预加载** ✓ → 按用户要求不计入估算 ✓
            txt.textContent = '回测执行中：正在准备/计算（等待引擎上报交易日进度）';
        }
    }
    // 预估时间展示
    if (eta) {
        if (p.running) {
            eta.textContent = _rsCalcEtaText(p);
        } else if (_loading) {
            // 【2026-09-20】引擎尚未上报（预处理/预加载阶段 ✓）：
            //   ① 不再重复显示"已耗时"（与上一行重复 ✗）
            //   ② 明确告知：这段时间是预处理，**不计入**剩余时间估算 ✓
            eta.textContent = '预处理/预加载中（该阶段耗时不计入估算）· 等待引擎上报交易日进度…';
        } else {
            eta.textContent = '';
        }
    }
}

/**
 * 根据进度快照计算预估时间文案
 * @param {Object} p - 进度快照（含 started_at/done_days/total_days）
 * @returns {string} 预估文案，例如 "已耗时 02:15 · 预计剩余 05:30 · 预计 14:50 完成"
 */
/** 【2026-09-20】引擎侧已耗时（秒）
 *  基准 = **首次观测到 running=true** 的时刻（`_regimeState.engineStartedAt` ✓）
 *  → 天然排除"点击按钮 → 引擎开始跑"之间的预处理/预加载耗时 ✓
 *  （用户要求：估算只统计"处理每日流程"的时间 ✓）
 */
function _rsEngineElapsedSec() {
    const t0 = _regimeState && _regimeState.engineStartedAt;
    if (!t0) return 0;
    return Math.max(0, (Date.now() - t0) / 1000);
}

function _rsCalcEtaText(p) {
    const doneDays = Number(p.done_days) || 0;
    const totalDays = Number(p.total_days) || 0;
    // 【2026-09-20】基准时刻优先级：
    //   ① 本前端**首次观测到引擎在跑**的时刻 ✓（最准：已排除预处理 ✓）
    //   ② 兜底用引擎自带 started_at ✓（例如直接进页面时引擎已在跑 ✓）
    let t0 = _regimeState && _regimeState.engineStartedAt;
    if (!t0 && p.started_at) {
        const d = new Date(String(p.started_at).replace(' ', 'T'));
        if (!isNaN(d.getTime())) t0 = d.getTime();
    }
    if (!t0 || !totalDays) return '';
    const elapsedSec = (Date.now() - t0) / 1000;
    if (elapsedSec < 0) return '';
    // 前3个交易日数据不稳定，仅显示已耗时，不展示预估（按用户要求保留该门槛 ✓）
    if (doneDays < 3) {
        return `已耗时 ${_rsFormatDuration(elapsedSec)} · 预估中...（前3个交易日数据稳定后展示）`;
    }
    // 单日流程耗时 = 引擎耗时 / 已处理交易日数（**不含**预处理 ✓）
    const perDaySec = elapsedSec / doneDays;
    // 剩余交易日数（至少0）
    const remainDays = Math.max(0, totalDays - doneDays);
    // 剩余秒数 = 剩余交易日 × 单日流程耗时
    const remainSec = remainDays * perDaySec;
    // 预计完成时刻 = 当前时间 + 剩余秒数
    const finishAt = new Date(Date.now() + remainSec * 1000);
    return `已耗时 ${_rsFormatDuration(elapsedSec)} · 预计剩余 ${_rsFormatDuration(remainSec)} · 预计 ${_rsFormatClock(finishAt)} 完成`;
}

/** 轮询后端进度（失败静默，不打断回测等待） */
async function _rsPollProgress() {
    try {
        const r = await _rsFetchJSON('/api/trading/backtest/regime/progress');
        // 【2026-09-20】首次观测到"引擎在跑" → 记为估算基准（据此排除前面的预处理耗时 ✓）
        if (r && r.success && r.data && r.data.running && !_regimeState.engineStartedAt) {
            _regimeState.engineStartedAt = Date.now();
        }
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

/**
 * 【2026-09-20】连接中断后的"继续监控"模式
 *   背景：`/regime/run` 是**同步长请求**（可能跑几十分钟~几小时 ✗），
 *   服务端/中间层超时会把连接掐断 → 前端 `fetch` 抛 "Failed to fetch" ✗，
 *   而**后台引擎仍在继续跑** ✓（进度接口继续前进 ✓）。
 *   原实现在此直接判"回测失败"并停掉轮询 ✗ → 进度条停滞 ✗。
 *   现：识别为网络中断后**保持轮询** ✓，直到后台 `running` 变为 false ✓，
 *   期间进度/ETA 照常刷新 ✓；结束由外层 finally 统一收尾（按钮还原 ✓）。
 */
async function _rsWatchAfterDisconnect() {
    return new Promise(function (resolve) {
        let ticks = 0;
        const MAX_TICKS = 6 * 60 * 60;              // 安全上限：最多盯 6 小时 ✓
        const timer = setInterval(async function () {
            ticks += 1;
            await _rsPollProgress();
            const stillRunning = !!(_regimeState && _regimeState.lastProgressRunning);
            if (!stillRunning || ticks >= MAX_TICKS) {
                clearInterval(timer);
                _rsSetStatus(ticks >= MAX_TICKS
                    ? '后台仍在运行，但前端已达监控上限，请稍后到回测结果中查看'
                    : '后台回测已结束（前端连接曾中断，详细结果请查看回测结果列表）');
                resolve();
            }
        }, 1000);
    });
}

/**
 * 【2026-09-20】等待后台异步回测结束（配合异步提交 ✓）
 *   轮询 `/regime/progress`：一旦观测到 running=true → 说明已开工 ✓；
 *   之后 running 变 false ✓ → 视为结束 ✓。
 *   宽限：前 30 秒即使还没 running 也继续等 ✓（引擎启动+预加载需要时间 ✓）。
 * @returns {Promise<boolean>} true=已结束 / false=超过上限
 */
async function _rsWaitRunFinished() {
    const MAX_TICKS = 6 * 3600;          // 安全上限 6 小时 ✓
    let seenRunning = false;
    for (let i = 0; i < MAX_TICKS; i++) {
        await _rsPollProgress();
        if (_regimeState.lastProgressRunning) {
            seenRunning = true;
        } else if (seenRunning || i > 30) {
            return true;
        }
        await new Promise(function (r) { setTimeout(r, 1000); });
    }
    return false;
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
    if (btn) {
        // 【2026-09-20】运行中：文案改「回测中…」并**置灰** ✓
        //   （原来只设 disabled ✗，但按钮是内联 background:#1677ff → 看上去仍是可点的蓝色 ✗）
        if (btn.dataset.origText === undefined) btn.dataset.origText = btn.textContent.trim() || '开始回测';
        if (btn.dataset.origStyle === undefined) btn.dataset.origStyle = btn.getAttribute('style') || '';
        btn.textContent = '回测中…';
        btn.disabled = true;
        btn.setAttribute('style',
            'padding:8px 20px;background:#94a3b8;color:#fff;border:none;border-radius:4px;cursor:not-allowed;');
    }

    // 进度：先本地置零，再每 1s 轮询后端进度
    _regimeState.runStartedAt = Date.now();     // 总提交时刻（仅参考）
    _regimeState.engineStartedAt = null;        // 【2026-09-20】清空"引擎开始跑"的基准 → 由轮询首次 running=true 时打点 ✓
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
        // 【2026-09-20】自动持久化本次设置（已取消"保存配置"按钮）：
        //   ① 时间区间 → localStorage（下次进入页面默认加载）
        //   ② rules + confirm_days → 后端 config/regime_router.yaml（静默，不覆盖运行状态）
        try {
            localStorage.setItem('regime_last_range',
                JSON.stringify({ start: startDate, end: endDate }));
        } catch (e) { /* 隐私模式等场景忽略 */ }
        _rsSaveConfig(true);
        // 【2026-09-20】异步提交 ✓：接口立即返回 task_id（不再挂长连接 ✗ → 不会被超时掐断 ✓）
        const sub = await _rsFetchJSON('/api/trading/backtest/regime/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!sub.success) throw new Error(sub.message || '提交失败');
        // 轮询到后台结束 ✓（期间进度/已耗时/ETA 由 _rsPollProgress 持续刷新 ✓，不会停滞 ✓）
        const finished = await _rsWaitRunFinished();
        if (!finished) {
            _rsSetStatus('后台仍在运行：已超过前端等待上限，请稍后到回测结果中查看（进度不再刷新）');
            return;
        }
        // 取回结果 ✓
        const rr = await _rsFetchJSON('/api/trading/backtest/regime/result');
        const rdata = (rr && rr.data) || {};
        if (rdata.error) throw new Error(rdata.error);
        if (!rdata.result) throw new Error('未取到回测结果（可能已入库但结果态丢失，请到回测结果查看）');
        const resultData = rdata.result;
        // ★【2026-09-28 修复 ✗→✓】**成功后**的渲染与文案**单独兜底** ✗ ——
        //   ① 本块原先写作 `res.data.strategy_switches` ✗：本作用域**没有 `res`** ✗
        //      （正确变量是 `rdata` / `resultData` ✓）⇒ 抛 `ReferenceError` ✗ ⇒
        //      被**外层** catch 捕获 ✗ ⇒ 后端**明明已成功** ✓ 却弹
        //      「回测失败：res is not defined」✗（用户实测报障 ✓）。
        //   ② 更根本 ✗：外层 catch 把**渲染错**与**回测失败**混为一谈 ✗ ⇒
        //      任何渲染小错都会伪装成"回测失败"✗ ⇒ 现把它隔离在**内层** ✓
        //      （渲染出错只告警 ✓，**绝不**再改判回测结果 ✗）。
        try {
            _rsRenderResult(resultData);
            const perf = resultData.performance || {};
            const rid = resultData.result_id;
            // 两种形状都兼容 ✓（取不到就按 0 次 ✓，**不抛** ✗）
            const _sw = (resultData.strategy_switches || rdata.strategy_switches || []);
            _rsSetStatus(`完成：总收益 ${perf.total_return !== undefined ? perf.total_return.toFixed(2) : '-'}%`
                + `，切换 ${_sw.length} 次`
                + (rid ? `，结果已保存（#${rid}）` : '，结果保存失败'));
        } catch (e2) {
            console.error('[自适应回测] 结果渲染异常（**回测本身已成功** ✓）', e2);
            _rsSetStatus('完成：后端已跑完并出结果 ✓（前端展示有告警，详见控制台 ✗）', true);
        }
    } catch (e) {
        console.error('[自适应回测] 失败', e);
        // 【2026-09-20】区分"网络层中断"与"回测本身失败" ✓：
        //   前者（Failed to fetch / 连接被掐断）→ 后台其实还在跑 ✗ → 不报失败 ✗，
        //   改为"继续监控" ✓，进度条与 ETA 不再停滞 ✓
        const _msg = String((e && e.message) || e || '');
        const _isNetErr = (e instanceof TypeError)
            || /failed to fetch|networkerror|load failed|network error/i.test(_msg);
        if (_isNetErr) {
            _rsSetStatus('连接已中断（服务端在长耗时任务上断开，属正常超时），后台仍在运行：'
                + '正在继续监控进度，结果以服务端记录为准…');
            await _rsWatchAfterDisconnect();      // 保持轮询直到后台结束 ✓
        } else {
            _rsSetStatus('回测失败：' + _msg, true);
        }
    } finally {
        clearInterval(_progressTimer);
        await _rsPollProgress();       // 收尾刷新一次（显示 100%/完成）
        _regimeState.loading = false;
        if (btn) {
            // 【2026-09-20】结束后还原：文案与样式恢复 ✓
            btn.disabled = false;
            if (btn.dataset.origText) btn.textContent = btn.dataset.origText;
            if (btn.dataset.origStyle !== undefined) btn.setAttribute('style', btn.dataset.origStyle);
        }
    }
}

/**
 * 保存路由配置（rules + confirm_days）到后端 config/regime_router.yaml
 * @param {boolean} silent - true 时静默执行，不覆盖当前状态提示（用于运行前自动保存）
 */
async function _rsSaveConfig(silent) {
    const rules = _rsCollectRules();
    const confirmDays = parseInt(document.getElementById('regime-confirm-days').value || '5', 10);
    try {
        const res = await _rsFetchJSON('/api/trading/backtest/regime/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rules: rules, confirm_days: confirmDays }),
        });
        if (!silent) {
            _rsSetStatus(res.success ? '配置已保存为默认（原文件已备份 .bak）' : ('保存失败：' + res.message), !res.success);
        }
        if (res.success) {
            // 保存成功后同步本地状态，保证后续渲染/运行与后端一致
            _regimeState.rules = rules;
        }
        return !!res.success;
    } catch (e) {
        if (!silent) _rsSetStatus('保存失败：' + e.message, true);
        return false;
    }
}

export async function initRegimeBacktestPage() {
    // 【2026-09-20】时间区间：默认加载"上次运行区间"（localStorage），首次使用回退近一年
    const today = new Date();
    const startInput = document.getElementById('regime-start-date');
    const endInput = document.getElementById('regime-end-date');
    let _lastRange = null;
    try {
        _lastRange = JSON.parse(localStorage.getItem('regime_last_range') || 'null');
    } catch (e) { _lastRange = null; }
    // 【2026-09-20】修正日期恢复（两个问题都修）：
    //   ① 原实现带 `!startInput.value` 前置 ✗ → SPA 二次进入本页（DOM 保留旧值）
    //      或模板预置默认值时，**整段跳过恢复** ✗
    //   ② 原实现只在点「开始回测」时才写入 localStorage ✗
    //      → 若还没跑过回测，就"从来没有上次区间"可恢复 ✗
    //   现在：**只要存过"上次区间"就强制回填** ✓；且日期一改动就**立即**持久化 ✓
    const _ymd = function (d) {                    // 本地时区日期（原 toISOString 是 UTC，凌晨会差一天 ✗）
        const p = function (n) { return String(n).padStart(2, '0'); };
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
    };
    if (_lastRange && _lastRange.start && _lastRange.end) {
        if (startInput) startInput.value = _lastRange.start;
        if (endInput) endInput.value = _lastRange.end;
    } else {
        if (startInput && !startInput.value) {
            startInput.value = _ymd(new Date(today.getTime() - 365 * 24 * 3600 * 1000));
        }
        if (endInput && !endInput.value) {
            endInput.value = _ymd(today);
        }
    }

    // 【2026-09-20】日期一改动就记住（不必等"开始回测"）→ 下次进入自动恢复 ✓
    const _persistRange = function () {
        const s = startInput && startInput.value;
        const e2 = endInput && endInput.value;
        if (!s || !e2) return;
        try {
            localStorage.setItem('regime_last_range', JSON.stringify({ start: s, end: e2 }));
        } catch (err) { /* 隐私模式等场景忽略 */ }
    };
    [startInput, endInput].forEach(function (el) {
        if (el && !el.dataset.rangeBound) {
            el.addEventListener('change', _persistRange);
            el.addEventListener('input', _persistRange);
            el.dataset.rangeBound = '1';
        }
    });
    // 首次进入即把当前（默认/上次）区间落一次，保证"上次区间"一定存在 ✓
    if (startInput && startInput.value && endInput && endInput.value) _persistRange();

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
    // 【2026-09-20】"保存为默认配置"按钮已移除：配置在每次运行前自动持久化
    //   （rules/confirm_days → 后端 yaml；时间区间 → localStorage）
    // 【2026-09-20】兼容旧模板：服务端 Jinja 模板有进程内缓存（需重启服务才刷新 ✗），
    //   旧页面可能仍渲染出这个"死按钮"（无事件绑定 ✗）→ 这里直接移除，
    //   保证界面与新版一致 ✓（无需重启服务 ✓）
    const staleSaveBtn = document.getElementById('regime-save-config-btn');
    if (staleSaveBtn && staleSaveBtn.parentNode) {
        staleSaveBtn.parentNode.removeChild(staleSaveBtn);
        console.log('[自适应回测] 已移除旧模板残留的「保存为默认配置」按钮');
    }
}

// 兼容：app.js 若以命名空间方式装配
export default { initRegimeBacktestPage };
