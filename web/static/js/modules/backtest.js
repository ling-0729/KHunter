/**
 * 回测模块相关功能
 */

// 全局变量
let backtestConfig = {
    strategy_name: '',
    start_date: '',
    end_date: '',
    initial_capital: 300000,
    score_threshold: 60,
    buy_amount: 100000,
    max_daily_buys: 8,
    support_level_method: 'ma20',
    timing_strategy: 'support',
    timing_params: {
        // 【2026-09-23】海龟类参数统一由后端读取 yaml（唯一配置源 ✓），此处不再硬编码 ✗：
        //   原 `turtle: {n_entry: 6, n_exit: 6, atr_period: 6}` ✗ 会在请求里**覆盖**后端配置 ✗，
        //   导致单次回测的海龟参数与批量回测/实盘不一致 ✗（典型的"配置漂移"来源 ✓）。
        rsi: {
            overbought: 70,
            oversold: 30,
            period: 14
        },
        bollinger: {
            period: 20,
            std_dev: 2
        }
    },
    stop_loss: -0.05,  // 止损 5%
    take_profit: 0.15,
    max_hold_days: 10,
    enable_friday_buy_ban: true,      // 周五禁买
    enable_dynamic_stop_loss: true    // 持股3天内动态止损（2/3）
};

/**
 * 格式化日期时间
 * @param {string} dateTimeStr - 日期时间字符串
 * @returns {string} 格式化后的日期时间
 */
function formatDateTime(dateTimeStr) {
    if (!dateTimeStr) return '--';
    // 支持 YYYY-MM-DD HH:MM:SS 格式
    const match = dateTimeStr.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$/);
    if (match) {
        return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}`;
    }
    // 支持 YYYY-MM-DDTHH:MM:SS 格式
    const match2 = dateTimeStr.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
    if (match2) {
        return `${match2[1]}-${match2[2]}-${match2[3]} ${match2[4]}:${match2[5]}`;
    }
    return dateTimeStr;
}

/**
 * 切换支撑位置选择框的启用/禁用状态
 */
function toggleSupportLevel() {
    const timingStrategy = document.getElementById('backtest-timing-strategy');
    const supportLevel = document.getElementById('support-level');
    
    if (timingStrategy && supportLevel) {
        if (timingStrategy.value === 'turtle') {
            supportLevel.disabled = true;
            supportLevel.style.opacity = '0.5';
        } else {
            supportLevel.disabled = false;
            supportLevel.style.opacity = '1';
        }
    }
}

/**
 * 初始化回测配置页面
 */
export async function initBacktestConfigPage() {
    console.log('初始化回测配置页面');
    
    // 加载选股策略列表
    await loadStrategies();
    
    // 加载择时策略列表
    await loadTimingStrategies();
    
    // 绑定表单事件
    bindConfigFormEvents();
    
    // 初始化日期选择器
    initDatePickers();
}

/**
 * 加载择时策略列表
 */
async function loadTimingStrategies() {
    try {
        console.log('开始加载择时策略列表');
        const response = await fetch('/api/timing-strategies');
        if (!response.ok) {
            throw new Error('加载择时策略列表失败: ' + response.status);
        }
        const data = await response.json();
        console.log('择时策略API返回:', data);
        
        if (data.success && data.strategies) {
            const timingSelect = document.getElementById('backtest-timing-strategy');
            if (timingSelect) {
                timingSelect.innerHTML = '';
                data.strategies.forEach(strategy => {
                    const option = document.createElement('option');
                    option.value = strategy.name;
                    option.textContent = strategy.display_name || strategy.name;
                    timingSelect.appendChild(option);
                });
                console.log('择时策略列表加载成功, 共', data.strategies.length, '个策略');
            }
        } else {
            console.warn('择时策略列表为空或数据格式不正确');
        }
    } catch (error) {
        console.error('加载择时策略列表失败:', error);
    }
}

/**
 * 初始化回测参数配置页面
 */
export function initBacktestParamsPage() {
    console.log('初始化回测参数配置页面');
    
    // 加载保存的配置
    loadBacktestParams();
    
    // 绑定表单事件
    bindParamsFormEvents();
}

/**
 * 初始化回测结果页面
 */
export function initBacktestResultsPage() {
    console.log('初始化回测结果页面');
    
    // 显示默认提示
    showResultsEmptyState('请先运行回测以查看结果');
}

/**
 * 初始化回测历史页面
 */
export function initBacktestHistoryPage() {
    console.log('初始化回测历史页面');
    
    // 加载策略列表
    loadHistoryStrategies();
    
    // 加载历史回测记录
    loadBacktestHistory();
}

/**
 * 加载回测历史页面的策略列表
 */
async function loadHistoryStrategies() {
    try {
        console.log('loadHistoryStrategies 开始执行');
        
        // 先清空并重新构建选项
        const strategySelect = document.getElementById('backtest-history-strategy-filter');
        if (!strategySelect) {
            console.warn('未找到 backtest-history-strategy-filter 元素');
            return;
        }
        
        // 清空所有选项
        strategySelect.innerHTML = '';
        
        // 添加默认选项
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = '全部策略';
        defaultOption.selected = true;
        strategySelect.appendChild(defaultOption);
        
        // 调用策略API加载策略列表
        const response = await fetch('/api/trading/backtest/strategies');
        console.log('API 响应状态:', response.status);
        
        if (!response.ok) {
            throw new Error('加载策略列表失败: ' + response.status);
        }
        
        const data = await response.json();
        console.log('API 返回数据:', data);
        
        if (data.success && data.data && data.data.strategies) {
            const strategies = data.data.strategies;
            
            strategies.forEach(strategy => {
                const strategyName = strategy.display_name || strategy.name;
                const option = document.createElement('option');
                option.value = strategyName;
                option.textContent = strategyName;
                strategySelect.appendChild(option);
            });
            
            console.log('回测历史策略列表加载成功, 共', strategies.length, '个策略');
        } else {
            console.warn('API 返回数据为空或格式不正确:', data.message);
            // 如果没有策略数据，添加提示
            const emptyOption = document.createElement('option');
            emptyOption.value = '';
            emptyOption.textContent = '暂无策略数据';
            emptyOption.disabled = true;
            strategySelect.appendChild(emptyOption);
        }
    } catch (error) {
        console.error('加载回测历史策略列表失败:', error);
        // 加载失败时显示错误提示
        const strategySelect = document.getElementById('backtest-history-strategy-filter');
        if (strategySelect) {
            strategySelect.innerHTML = '';
            const errorOption = document.createElement('option');
            errorOption.value = '';
            errorOption.textContent = '加载策略失败，请刷新页面';
            errorOption.disabled = true;
            errorOption.selected = true;
            strategySelect.appendChild(errorOption);
        }
    }
}

/**
 * 加载策略列表
 */
async function loadStrategies() {
    try {
        const response = await fetch('/api/trading/backtest/strategies');
        if (!response.ok) {
            throw new Error('加载策略列表失败');
        }
        const data = await response.json();
        if (data.success && data.data && data.data.strategies) {
            const strategies = data.data.strategies;
            const strategySelect = document.getElementById('strategy-select');
            if (strategySelect) {
                strategySelect.innerHTML = '';
                strategies.forEach(strategy => {
                    const option = document.createElement('option');
                    // 使用中文名称作为value和显示文本
                    const chineseName = strategy.display_name || strategy.name;
                    option.value = chineseName;
                    option.textContent = chineseName;
                    strategySelect.appendChild(option);
                });
            }
        } else {
            console.warn('策略列表为空或数据格式不正确');
        }
    } catch (error) {
        console.error('加载策略列表失败:', error);
        alert('加载策略列表失败，请刷新页面重试');
    }
}

/**
 * 绑定配置表单事件
 */
function bindConfigFormEvents() {
    const runBacktestBtn = document.getElementById('run-backtest-btn');
    if (runBacktestBtn) {
        runBacktestBtn.addEventListener('click', async () => {
            await runBacktest();
        });
    }
}

/**
 * 绑定参数表单事件
 */
function bindParamsFormEvents() {
    const saveBacktestParamsBtn = document.getElementById('save-backtest-params-btn');
    if (saveBacktestParamsBtn) {
        saveBacktestParamsBtn.addEventListener('click', saveBacktestParams);
    }
}

/**
 * 保存回测配置
 */
async function saveBacktestParams() {
    try {
        // 收集配置数据
        const initialCapitalInput = document.getElementById('params-initial-capital');
        const scoreThresholdInput = document.getElementById('params-score-threshold');
        const buyAmountInput = document.getElementById('params-buy-amount');
        const maxDailyBuysInput = document.getElementById('params-max-daily-buys');
        const stopLossInput = document.getElementById('params-stop-loss');
        const takeProfitInput = document.getElementById('params-take-profit');
        const maxHoldDaysInput = document.getElementById('params-max-hold-days');
        
        const params = {
            config_name: '默认配置',
            score_threshold: parseFloat(scoreThresholdInput?.value) || 60,
            hold_period: parseInt(maxHoldDaysInput?.value) || 10,
            stop_loss: parseFloat(stopLossInput?.value) * 100, // 转换为百分比
            take_profit: parseFloat(takeProfitInput?.value) * 100, // 转换为百分比
            initial_capital: parseFloat(initialCapitalInput?.value) || 300000,
            buy_amount: parseFloat(buyAmountInput?.value) || 100000,
            max_daily_buys: parseInt(maxDailyBuysInput?.value) || 5
        };

        // 【2026-09-27 新增】模式与开关 ✓（写入 `config/backtest_engine_config.yaml` ✓）
        //   选「跟随回测模式」（空值 ✓）⇒ 发送 **null** ✓
        //   ⇒ 后端会把这些键**还原为注释** ✓✓（不再覆盖模式预设 ✓）
        const modeEl = document.getElementById('params-backtest-mode');
        const poolModeEl = document.getElementById('params-pool-entry-mode');
        // ⚠️ 控件 id 一律 = **键名派生** ✓（`params-` + 键名 `_`→`-` ✓）⇒ 见
        //   `test_backtest_config_store.py::TestExtraKeysAllHaveFrontendControls` ✓
        //   （穷尽校验"每个白名单键都有控件"✓，防再犯"加了键没加控件"✗）。
        const addRiseEl = document.getElementById('params-enable-add-open-rise-check');
        if (modeEl) params.backtest_mode = modeEl.value || null;
        if (poolModeEl) params.pool_entry_mode = poolModeEl.value || null;
        if (addRiseEl) {
            params.enable_add_open_rise_check = (addRiseEl.value === '')
                ? null : (addRiseEl.value === 'true');
        }
        // ★【2026-09-29 用户要求 ✓】"不开新仓 ⇒ 跳过选股"开关 ✗→✓
        //   空值 ⇒ 发 **null** ⇒ 后端把该键**还原为注释** ✓ = 走代码默认（**开启** ✓）
        //   ⇒ 不显式覆盖 ✓（与其它"跟随模式预设"的键同一处理 ✓）
        const skipSelEl = document.getElementById('params-skip-selection-when-no-new-position');
        if (skipSelEl) {
            params.skip_selection_when_no_new_position = (skipSelEl.value === '')
                ? null : (skipSelEl.value === 'true');
        }
        // ★★【2026-09-29 用户要求 ✓】**高级参数（ADX 口径 / 大盘仓位上限）** ✗→✓
        //   动机 ✗✓（用户："没有看到前端设置的地方"✗）：这些键此前**只有后端白名单** ✗、
        //     前端**零控件** ✗ ⇒ 只能手改 yaml ✗。
        //   统一口径 ✓：**留空 ⇒ 发 null** ⇒ 后端把该键**还原为注释** ✓ = 走模式预设/代码默认 ✓；
        //     ⚠️ 空值**绝不能**变成 0 / [] ✗✓（那是"**显式**改掉默认行为"✗）。
        //   ⚠️ 控件缺失（旧页面缓存 ✓）⇒ **整个块跳过** ✓（不发这些键 ✗，绝不清空用户配置 ✗✓）。
        const advEl = document.getElementById('params-advanced');
        if (advEl) {
            const _blank = (id) => {
                const el = document.getElementById(id);
                if (!el) return undefined;
                const v = (el.value === null || el.value === undefined)
                    ? '' : String(el.value).trim();
                return v === '' ? null : v;
            };
            const _num = (id) => {
                const v = _blank(id);
                if (v === undefined || v === null) return v;
                const n = Number(v);
                return Number.isFinite(n) ? n : null;   // 非法输入 ⇒ 当"未填"✓（绝不写坏值 ✗）
            };
            const _bool = (id) => {
                const v = _blank(id);
                return (v === 'true') ? true : (v === 'false' ? false : v);
            };
            params.enable_stock_adx_filter = _bool('params-enable-stock-adx-filter');
            params.adx_entry_mode = _blank('params-adx-entry-mode');
            params.adx_dir_mode = _blank('params-adx-dir-mode');
            // ★★【2026-09-30 用户要求 ✓】个股放行新增「`close(T-1) > MA20`」✗→✓
            //   ⚠️ **只约束首仓** ✗✓（加仓不判 ✓ —— 加仓只看 `dir=上升` ✓）
            //   留空 ⇒ **null** ⇒ 后端把该键**还原为注释** ✓ = 走默认（开启 ✓ / MA20 ✓）
            params.adx_entry_require_above_ma = _bool('params-adx-entry-require-above-ma');
            params.adx_entry_ma_period = _num('params-adx-entry-ma-period');
            // ★★【2026-10-04 用户要求 ✓】**加仓也判** `close(T-1) > MA20`（用户答"需要" ✓）
            //   ⚠️ **独立开关** ✗✓（与首仓分开 ⇒ 可各自 A/B、各自回退 ✓）；
            //     关掉 ⇒ 加仓回到 2026-09-29 口径（只看 `dir=上升` ✓）
            params.adx_add_require_above_ma = _bool('params-adx-add-require-above-ma');
            const _lo = _num('params-adx-range-lo');
            const _hi = _num('params-adx-range-hi');
            const _lo2 = _num('params-adx-range2-lo');
            const _hi2 = _num('params-adx-range2-hi');
            // ★【2026-09-29 用户要求 ✓】**两段并集** ✓（口径：`ADX<18 ∪ 23<ADX<42` ✓）
            //   ⚠️ 每段**两个都填**才算该段有效 ✓（只填一个 ⇒ **忽略该段** ✓，避免半套区间 ✗）；
            //   ⚠️ 两段都空 ⇒ 发 **null** ✓（后端还原为注释 ✓ = 走默认单段 ✓，**旧行为完整保留** ✓）；
            //   ⚠️ 保存格式：**扁平偶数个** ✓（`[0,18,23,42]` ✓ = 两两成段 ✓，后端按此解析 ✓）。
            const _rng = [];
            if (_lo !== null && _hi !== null) _rng.push(_lo, _hi);
            if (_lo2 !== null && _hi2 !== null) _rng.push(_lo2, _hi2);
            params.adx_entry_range = _rng.length ? _rng : null;
            const _bandsEl = document.getElementById('params-adx-entry-bands');
            const _picked = _bandsEl
                ? Array.from(_bandsEl.selectedOptions).map((o) => o.value) : [];
            params.adx_entry_bands = _picked.length ? _picked : null;
            params.index_adx_code = _blank('params-index-adx-code');
            params.index_adx_dir_mode = _blank('params-index-adx-dir-mode');
            params.enable_index_position_cap = _bool('params-enable-index-position-cap');
            params.index_cap_high_adx = _num('params-index-cap-high-adx');
            params.index_cap_high_ratio = _num('params-index-cap-high-ratio');
            params.index_cap_low_adx = _num('params-index-cap-low-adx');
            params.index_cap_low_ratio = _num('params-index-cap-low-ratio');
            params.index_cap_other_ratio = _num('params-index-cap-other-ratio');
            // ★★【2026-09-30 用户要求 ✓】规则2 **附加条件**（`ADX<18` 时还须**收盘 > MA20** ✓）
            //   留空 ⇒ **null** ⇒ 后端把该键**还原为注释** ✓ = 走代码默认（**开启** ✓）
            //   ⚠️ `false` 必须原样发 ✗（别用 `||` 兜底 ⇒ 会被当空值吞掉 ✗）
            params.index_cap_low_require_above_ma =
                _bool('params-index-cap-low-require-above-ma');
            params.index_cap_ma_period = _num('params-index-cap-ma-period');
            // ★★【2026-10-05 用户要求 ✓】**板块回退**（全A 不放行 ⇒ 看科创板/创业板 ✓）
            //   留空 ⇒ null ⇒ 后端把该键**还原为注释** ✓ = 走代码默认（**开启** ✓ / 两个默认代码 ✓）
            //   ⚠️ `false` 必须原样发 ✗（别用 `||` 兜底 ⇒ 会被当空值吞掉 ✗）
            //   ★ 同日口径二次调整 ✓："**双创同时放行 ⇒ 整体不放行**" ✓ 在**后端判定层** ✓
            //     ⇒ **前端无需改动** ✗✓（也不新增控件 ✓）
            params.index_cap_board_fallback =
                _bool('params-index-cap-board-fallback');
            params.index_cap_star_code = _blank('params-index-cap-star-code');
            params.index_cap_chinext_code = _blank('params-index-cap-chinext-code');
        }
        
        // 调用后端API保存配置
        const response = await fetch('/api/trading/backtest/configs', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        });
        
        if (!response.ok) {
            throw new Error('保存回测配置失败');
        }
        
        const data = await response.json();
        if (data.success) {
            // ★【2026-09-29 用户提问 ✓】"改这些参数要不要重启服务？" ⇒ **不用** ✓
            //   `save()` 写成功后会**自动清掉进程内的 yaml 缓存** ✓
            //   （`utils/backtest_mode.clear_engine_yaml_cache()` ✓，见 `backtest_config_store.py` ✓）
            //   ⇒ 下一轮回测/实盘**立刻**按新值判定 ✓。
            //   ⚠️ 唯一例外 ✓：**正在跑**的任务在启动时已快照参数 ✓ ⇒ 它按旧值跑完 ✓（下一轮生效 ✓）。
            alert('回测配置保存成功（已即时生效，无需重启服务；正在运行的任务下一轮生效）');
        } else {
            throw new Error(data.message || '保存回测配置失败');
        }
    } catch (error) {
        console.error('保存回测配置失败:', error);
        alert('保存回测配置失败: ' + error.message);
    }
}

/**
 * 加载回测配置
 */
async function loadBacktestParams() {
    try {
        // 从后端API加载配置
        const response = await fetch('/api/trading/backtest/configs');
        if (!response.ok) {
            throw new Error('加载回测配置失败');
        }
        
        const data = await response.json();
        if (data.success && data.data.configs && data.data.configs.length > 0) {
            // 使用最新的配置
            const params = data.data.configs[0];
            
            // 填充表单
            const initialCapitalInput = document.getElementById('params-initial-capital');
            const scoreThresholdInput = document.getElementById('params-score-threshold');
            const buyAmountInput = document.getElementById('params-buy-amount');
            const maxDailyBuysInput = document.getElementById('params-max-daily-buys');
            const stopLossInput = document.getElementById('params-stop-loss');
            const takeProfitInput = document.getElementById('params-take-profit');
            const maxHoldDaysInput = document.getElementById('params-max-hold-days');
            
            if (initialCapitalInput) initialCapitalInput.value = params.initial_capital || 300000;
            if (scoreThresholdInput) scoreThresholdInput.value = params.score_threshold || 60;
            if (buyAmountInput) buyAmountInput.value = params.buy_amount || 100000;
            if (maxDailyBuysInput) maxDailyBuysInput.value = params.max_daily_buys || 5;
            if (stopLossInput) stopLossInput.value = (params.stop_loss || -5) / 100; // 转换为小数
            if (takeProfitInput) takeProfitInput.value = (params.take_profit || 15) / 100; // 转换为小数
            if (maxHoldDaysInput) maxHoldDaysInput.value = params.hold_period || 10;

            // 【2026-09-27 新增】模式与开关回填 ✓
            //   ⚠️ `false` 不能用 `||` 兜底 ✗（会被当成空值 ✗）⇒ 用 `=== true/false` 显式判断 ✓
            const modeSel = document.getElementById('params-backtest-mode');
            const poolSel = document.getElementById('params-pool-entry-mode');
            // ★★【2026-10-05 修复 ✓】**控件 id 写错 ⇒ 该下拉永远不回填** ✗→✓ ★★
            //   事故 ✗✓（用户反馈："回测参数保存不成功"✓ 同一类症状 ✓）：
            //     这里原本写的 id 是 `params-add-open-rise` ✗，而模板里真实的 id 是
            //     `params-enable-add-open-rise-check` ✓（= `params-` + **键名** ✓）⇒
            //     `getElementById` 恒为 `null` ⇒ `if (riseSel)` 恒假 ✗
            //     ⇒ **保存后重新进页面，该下拉永远显示默认「跟随回测模式」** ✗
            //     （而保存侧用的是**正确** id ✓ ⇒ 值其实写进 yaml 了 ✓
            //       ⇒ 表现为"看着没保存"✗✓ —— 与 `backtest_mode` 那次同一坑 ✓）。
            //   ⚠️ 约定 ✓：控件 id **一律 = `params-` + 键名（`_`→`-`）** ✗✓ ——
            //     `test_backtest_config_store.py::TestExtraKeysAllHaveFrontendControls` 守着"有控件"✓，
            //     但**守不住"JS 读的 id 与控件 id 一致"** ✗ ⇒ 故这里按约定修正 ✓。
            const riseSel = document.getElementById('params-enable-add-open-rise-check');
            if (modeSel) modeSel.value = params.backtest_mode || 'legacy';
            // ★【2026-09-29】新增 `direct`（直通入池 ✓）⇒ 回填白名单**同步扩上** ✗→✓
            //   （否则选了 direct 保存后再进页面 ⇒ 下拉回落"跟随回测模式"✗，看着像没保存 ✗）
            if (poolSel) poolSel.value = ['veto_only', 'scored', 'direct']
                .includes(params.pool_entry_mode) ? params.pool_entry_mode : '';
            if (riseSel) {
                riseSel.value = (params.enable_add_open_rise_check === true) ? 'true'
                    : (params.enable_add_open_rise_check === false ? 'false' : '');
            }
            // ★【2026-09-29 用户要求 ✓】跳过选股开关回填 ✓
            //   ⚠️ `false` **不能**用 `||` 兜底 ✗（会被当成空值 ✗）⇒ 显式判 `=== true/false` ✓；
            //   yaml 里没写（= 默认 ✓）⇒ 后端**不会**返回该键 ⇒ 回落空值（未显式设置 ✓）。
            const skipSel = document.getElementById('params-skip-selection-when-no-new-position');
            if (skipSel) {
                skipSel.value = (params.skip_selection_when_no_new_position === true) ? 'true'
                    : (params.skip_selection_when_no_new_position === false ? 'false' : '');
            }
            // ★★【2026-09-29 用户要求 ✓】**高级参数回填** ✗→✓（与保存侧**逐键对应** ✓）
            //   ⚠️ `false` / `0` **不能**用 `||` 兜底 ✗（会被当成空值 ✗）⇒ 一律显式判类型 ✓；
            //   yaml 里没写（= 走默认 ✓）⇒ 后端**不会**返回该键 ⇒ 回落空值（未显式设置 ✓）。
            const advElL = document.getElementById('params-advanced');
            if (advElL) {
                const _setSel = (id, v) => {
                    const el = document.getElementById(id);
                    if (el) el.value = (v === null || v === undefined) ? '' : String(v);
                };
                const _setBoolSel = (id, v) => {
                    const el = document.getElementById(id);
                    if (el) {
                        el.value = (v === true) ? 'true' : (v === false ? 'false' : '');
                    }
                };
                const _setNum = (id, v) => {
                    const el = document.getElementById(id);
                    if (el) {
                        el.value = (typeof v === 'number' && Number.isFinite(v)) ? v : '';
                    }
                };
                _setBoolSel('params-enable-stock-adx-filter', params.enable_stock_adx_filter);
                _setSel('params-adx-entry-mode', params.adx_entry_mode);
                _setSel('params-adx-dir-mode', params.adx_dir_mode);
                // ★【2026-09-30】个股放行 MA 条件回填 ✓（`false` 显式判 ✓ 不用 `||` ✗）
                _setBoolSel('params-adx-entry-require-above-ma',
                    params.adx_entry_require_above_ma);
                // ★【2026-10-04】加仓独立开关回填 ✓（`false` 显式判 ✓ 不用 `||` ✗）
                _setBoolSel('params-adx-add-require-above-ma',
                    params.adx_add_require_above_ma);
                _setNum('params-adx-entry-ma-period', params.adx_entry_ma_period);
                // ⚠️ 区间键：**四个输入同属一键** ✗✓（容器 id = 键名派生 ✓）
                //   ★【2026-09-29】兼容**三种**存储形态 ✓：扁平 `[0,18,23,42]` ✓ /
                //     嵌套 `[[0,18],[23,42]]` ✓ / 单段 `[21,30]` ✓（旧值 ✓）
                const _rngWrap = document.getElementById('params-adx-entry-range');
                if (_rngWrap) {
                    const _arr = Array.isArray(params.adx_entry_range)
                        ? params.adx_entry_range : [];
                    const _segs = (typeof _arr[0] === 'object' && _arr[0] !== null)
                        ? _arr.map((r) => [r[0], r[1]])          // 嵌套 ✓
                        : (() => {                               // 扁平 ✓（两两成对）
                            const out = [];
                            for (let i = 0; i + 1 < _arr.length; i += 2) {
                                out.push([_arr[i], _arr[i + 1]]);
                            }
                            return out;
                        })();
                    _setNum('params-adx-range-lo', _segs[0] && _segs[0][0]);
                    _setNum('params-adx-range-hi', _segs[0] && _segs[0][1]);
                    _setNum('params-adx-range2-lo', _segs[1] && _segs[1][0]);
                    _setNum('params-adx-range2-hi', _segs[1] && _segs[1][1]);
                }
                const _bandsElL = document.getElementById('params-adx-entry-bands');
                if (_bandsElL) {
                    const _want = Array.isArray(params.adx_entry_bands)
                        ? params.adx_entry_bands.map(String) : [];
                    Array.from(_bandsElL.options).forEach((o) => {
                        o.selected = _want.includes(o.value);
                    });
                }
                _setSel('params-index-adx-code', params.index_adx_code);
                _setSel('params-index-adx-dir-mode', params.index_adx_dir_mode);
                _setBoolSel('params-enable-index-position-cap', params.enable_index_position_cap);
                _setNum('params-index-cap-high-adx', params.index_cap_high_adx);
                _setNum('params-index-cap-high-ratio', params.index_cap_high_ratio);
                _setNum('params-index-cap-low-adx', params.index_cap_low_adx);
                _setNum('params-index-cap-low-ratio', params.index_cap_low_ratio);
                _setNum('params-index-cap-other-ratio', params.index_cap_other_ratio);
                // ★【2026-09-30】规则2 附加条件回填 ✓（`false` 显式判 ✓ 不用 `||` ✗）；
                //   yaml 里没写（= 默认开启 ✓）⇒ 后端**不返回该键** ⇒ 回落空值 ✓
                _setBoolSel('params-index-cap-low-require-above-ma',
                    params.index_cap_low_require_above_ma);
                _setNum('params-index-cap-ma-period', params.index_cap_ma_period);
                // ★【2026-10-05】板块回退三键回填 ✓（`false` 显式判 ✓ 不用 `||` ✗）
                _setBoolSel('params-index-cap-board-fallback',
                    params.index_cap_board_fallback);
                _setSel('params-index-cap-star-code', params.index_cap_star_code);
                _setSel('params-index-cap-chinext-code', params.index_cap_chinext_code);
            }
        }
    } catch (error) {
        console.error('加载回测配置失败:', error);
    }
}

/**
 * 初始化日期选择器
 */
function initDatePickers() {
    // 获取当前日期
    const today = new Date();
    
    // 开始日期：重置为上个月1日
    const startDate = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    
    const startDateInput = document.getElementById('start-date');
    const endDateInput = document.getElementById('end-date');
    
    if (startDateInput) {
        startDateInput.value = startDate.toISOString().split('T')[0];
    }
    
    if (endDateInput) {
        endDateInput.value = today.toISOString().split('T')[0];
    }
}

/**
 * 运行回测
 */
async function runBacktest() {
    try {
        // 收集表单数据
        const strategySelect = document.getElementById('strategy-select');
        const startDateInput = document.getElementById('start-date');
        const endDateInput = document.getElementById('end-date');
        const supportLevelSelect = document.getElementById('support-level');
        const timingStrategySelect = document.getElementById('backtest-timing-strategy');
        const backtestEngineSelect = document.getElementById('backtest-engine');
        
        // 验证表单数据
        if (!strategySelect?.value || !startDateInput?.value || !endDateInput?.value) {
            alert('请填写完整的回测执行条件');
            return;
        }
        
        // 加载保存的回测配置
        let savedParams = {  
            initial_capital: 300000,
            score_threshold: 60,
            buy_amount: 100000,
            max_daily_buys: 8,
            stop_loss: 0.05,
            take_profit: 0.15,
            max_hold_days: 10,
            enable_friday_buy_ban: 1,
            enable_dynamic_stop_loss: 1
        };
        
        // 从后端API加载配置
        try {
            const response = await fetch('/api/trading/backtest/configs');
            if (response.ok) {
                const data = await response.json();
                if (data.success && data.data.configs && data.data.configs.length > 0) {
                    const config = data.data.configs[0];
                    savedParams = {
                        initial_capital: config.initial_capital || 300000,
                        score_threshold: config.score_threshold || 60,
                        buy_amount: config.buy_amount || 100000,
                        max_daily_buys: config.max_daily_buys || 5,
                        stop_loss: (config.stop_loss || -5) / 100, // 转换为小数
                        take_profit: (config.take_profit || 15) / 100, // 转换为小数
                        max_hold_days: config.hold_period || 10,
                        enable_friday_buy_ban: config.enable_friday_buy_ban !== 0 ? 1 : 0,
                        enable_dynamic_stop_loss: config.enable_dynamic_stop_loss !== 0 ? 1 : 0
                    };
                }
            }
        } catch (error) {
            console.error('加载回测配置失败:', error);
        }
        
        // 生成配置名称
        const configName = `${strategySelect?.value || '未知策略'}_${startDateInput?.value || ''}_${endDateInput?.value || ''}`;
        
        // 直接使用中文策略名称
        const chineseStrategyName = strategySelect?.value || '';
        
        let timingStrategy = timingStrategySelect?.value || 'turtle';
        let supportLevelMethod = 'ma20';
        
        // 处理支撑位策略的情况
        if (timingStrategy.startsWith('support_')) {
            supportLevelMethod = timingStrategy.replace('support_', '');
            timingStrategy = 'support';
        }
        
        backtestConfig = {
            config_name: configName,
            strategy_name: chineseStrategyName,  // 发送中文名称给后端
            start_date: startDateInput?.value || '',
            end_date: endDateInput?.value || '',
            initial_capital: savedParams.initial_capital,
            score_threshold: savedParams.score_threshold,
            buy_amount: savedParams.buy_amount,
            max_daily_buys: savedParams.max_daily_buys,
            support_level_method: supportLevelMethod,
            timing_strategy: timingStrategy,
            timing_params: backtestConfig.timing_params,
            stop_loss: savedParams.stop_loss * 100, // 转换为百分比
            take_profit: savedParams.take_profit * 100, // 转换为百分比
            max_hold_days: savedParams.max_hold_days,
            // 新增：周五禁买和动态止损
            enable_friday_buy_ban: savedParams.enable_friday_buy_ban !== undefined ? savedParams.enable_friday_buy_ban : 1,
            enable_dynamic_stop_loss: savedParams.enable_dynamic_stop_loss !== undefined ? savedParams.enable_dynamic_stop_loss : 1
        };
        
        // 显示加载状态
        const runBacktestBtn = document.getElementById('run-backtest-btn');
        if (runBacktestBtn) {
            runBacktestBtn.disabled = true;
            runBacktestBtn.textContent = '运行中...';
        }
        
        // 运行回测
        const response = await fetch('/api/trading/backtest/run', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(backtestConfig)
        });
        
        if (!response.ok) {
            throw new Error('运行回测失败');
        }
        
        const data = await response.json();
        if (data.success) {
            // 直接在当前页面展示回测结果
            const result = data.data;
            displayBacktestResultOnConfigPage(result);
            
            // 直接使用返回的交易记录数据，无需再次调用API
            if (result.trades && result.trades.length > 0) {
                displayBacktestTradesOnConfigPage(result.trades);
            } else {
                // 如果没有交易记录，显示空状态
                const tradesBody = document.getElementById('backtest-trades-body');
                if (tradesBody) {
                    tradesBody.innerHTML = '<tr><td colspan="9" class="text-center">暂无交易记录</td></tr>';
                }
            }
        } else {
            throw new Error(data.message || '运行回测失败');
        }
    } catch (error) {
        console.error('运行回测失败:', error);
        alert('运行回测失败: ' + error.message);
    } finally {
        // 恢复按钮状态
        const runBacktestBtn = document.getElementById('run-backtest-btn');
        if (runBacktestBtn) {
            runBacktestBtn.disabled = false;
            runBacktestBtn.textContent = '运行回测';
        }
    }
}

/**
 * 加载回测结果
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestResult(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}`);
        if (!response.ok) {
            throw new Error('加载回测结果失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const result = data.data;
            displayBacktestResult(result);
            
            // 绘制收益曲线
            if (result.equity_curve) {
                const capitalHistory = result.equity_curve.map(item => item.capital);
                const dates = result.equity_curve.map(item => item.date);
                drawEquityChart(capitalHistory, dates);
            }
            
            // 加载交易记录
            loadBacktestTrades(resultId);
        } else {
            throw new Error(data.message || '加载回测结果失败');
        }
    } catch (error) {
        console.error('加载回测结果失败:', error);
        showResultsEmptyState('加载回测结果失败: ' + error.message);
    }
}

/**
 * 显示回测结果
 * @param {Object} result - 回测结果数据
 */
function displayBacktestResult(result) {
    // 择时策略中文名称映射
    const timingStrategyNames = {
        'turtle': '海龟策略',
        'turtle_plus': '海龟plus',
        'rsi': 'RSI策略',
        'bollinger': '布林带策略',
        'support': '支撑位策略',
        'macd_bollinger': '顺势宝',
        'uptrend_pullback': '趋势回调缩量策略'
    };
    
    // 获取择时策略显示名称
    const timingStrategyDisplay = timingStrategyNames[result.support_level_method] || result.support_level_method || '支撑位策略';
    
    const resultsContainer = document.getElementById('backtest-results-container');
    if (resultsContainer) {
        resultsContainer.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>回测结果</h3>
                </div>
                <div class="card-body">
                    <div class="grid grid-cols-2 gap-4">
                        <div class="form-group">
                            <label>策略名称</label>
                            <input type="text" value="${result.strategy_name || ''}" disabled>
                        </div>
                        <div class="form-group">
                            <label>回测期间</label>
                            <input type="text" value="${result.start_date || ''} 至 ${result.end_date || ''}" disabled>
                        </div>
                        <div class="form-group">
                            <label>择时策略</label>
                            <input type="text" value="${timingStrategyDisplay}" disabled>
                        </div>
                        <div class="form-group">
                            <label>初始资金</label>
                            <input type="text" value="${result.initial_capital || 0}" disabled>
                        </div>
                        <div class="form-group">
                            <label>最终资金</label>
                            <input type="text" value="${(result.final_capital || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group">
                            <label>总收益率</label>
                            <input type="text" value="${(result.total_return || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>胜率</label>
                            <input type="text" value="${(result.win_rate || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>平均收益率</label>
                            <input type="text" value="${(result.avg_return || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>盈亏比</label>
                            <input type="text" value="${(result.profit_loss_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group">
                            <label>最大回撤</label>
                            <input type="text" value="${(result.max_drawdown || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>夏普比率</label>
                            <input type="text" value="${(result.sharpe_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group">
                            <label>波动率</label>
                            <input type="text" value="${(result.volatility || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>索提诺比率</label>
                            <input type="text" value="${(result.sortino_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group">
                            <label>总交易次数</label>
                            <input type="text" value="${result.total_trades || 0}" disabled>
                        </div>
                        <div class="form-group">
                            <label>盈利交易次数</label>
                            <input type="text" value="${result.winning_trades || 0}" disabled>
                        </div>
                        <div class="form-group">
                            <label>亏损交易次数</label>
                            <input type="text" value="${result.losing_trades || 0}" disabled>
                        </div>
                        <div class="form-group">
                            <label>平均持有天数</label>
                            <input type="text" value="${(result.avg_hold_days || 0).toFixed(2)}" disabled>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
}

/**
 * 加载回测交易记录
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestTrades(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}/trades`);
        if (!response.ok) {
            throw new Error('加载交易记录失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const trades = data.data.trades;
            displayBacktestTrades(trades);
        } else {
            throw new Error(data.message || '加载交易记录失败');
        }
    } catch (error) {
        console.error('加载交易记录失败:', error);
        alert('加载交易记录失败: ' + error.message);
    }
}

/**
 * 显示回测交易记录
 * @param {Array} trades - 交易记录数组
 */
function displayBacktestTrades(trades) {
    const tradesContainer = document.getElementById('backtest-trades-container');
    if (tradesContainer) {
        if (trades.length === 0) {
            tradesContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <h3>交易记录</h3>
                    </div>
                    <div class="card-body">
                        <p class="text-center">暂无交易记录</p>
                    </div>
                </div>
            `;
        } else {
            tradesContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <h3>交易记录</h3>
                    </div>
                    <div class="card-body">
                        <div class="overflow-x-auto">
                            <table class="table">
                                <thead>
                                    <tr>
                                        <th>股票代码</th>
                                        <th>股票名称</th>
                                        <th>买入日期</th>
                                        <th>买入价格</th>
                                        <th>卖出日期</th>
                                        <th>卖出价格</th>
                                        <th>收益率</th>
                                        <th>交易类型</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${trades.map(trade => `
                                        <tr>
                                            <td><a href="${trade.detail_url || 'javascript:void(0)'}" onclick="viewStockDetail('${trade.stock_code}'); return false;" class="stock-link" style="color: #2563eb; text-decoration: none; cursor: pointer; font-weight: 600;">${trade.stock_code}</a></td>
                                            <td>${trade.stock_name || ''}</td>
                                            <td>${trade.buy_date || ''}</td>
                                            <td>${trade.buy_price || 0}</td>
                                            <td>${trade.sell_date || ''}</td>
                                            <td>${trade.sell_price || 0}</td>
                                            <td class="${(trade.return_rate || 0) >= 0 ? 'text-green-500' : 'text-red-500'}">
                                                ${(trade.return_rate || 0).toFixed(2)}%
                                            </td>
                                            <td>${trade.sell_type || trade.trade_type || 'normal'}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            `;
        }
    }
}

/**
 * 加载回测历史记录
 */
async function loadBacktestHistory() {
    try {
        console.log('开始加载回测历史...');
        const response = await fetch('/api/trading/backtest/results');
        console.log('API 响应状态:', response.status);
        
        if (!response.ok) {
            throw new Error(`HTTP 错误! 状态: ${response.status}`);
        }
        
        const data = await response.json();
        console.log('API 返回数据:', data);
        
        if (data.success) {
            const results = data.data.results || [];
            console.log('回测结果数量:', results.length);
            displayBacktestHistory(results);
        } else {
            throw new Error(data.message || '加载回测历史失败');
        }
    } catch (error) {
        console.error('加载回测历史失败:', error);
        showHistoryEmptyState('加载回测历史失败: ' + error.message);
    }
}

/**
 * 显示回测历史记录
 * @param {Array} results - 回测结果数组
 */
function displayBacktestHistory(results) {
    // 择时策略中文名称映射
    const timingStrategyNames = {
        'turtle': '海龟策略',
        'turtle_plus': '海龟plus',
        'rsi': 'RSI策略',
        'bollinger': '布林带策略',
        'support': '支撑位策略',
        'macd_bollinger': '顺势宝',
        'uptrend_pullback': '趋势回调缩量策略'
    };
    
    const historyBody = document.getElementById('backtest-history-body');
    if (historyBody) {
        if (results.length === 0) {
            historyBody.innerHTML = '<tr><td colspan="12" class="loading">暂无回测历史记录</td></tr>';
        } else {
            historyBody.innerHTML = results.map(result => {
                // 获取择时策略显示名称
                const timingStrategyDisplay = timingStrategyNames[result.support_level_method] || result.support_level_method || '支撑位策略';
                return `
                <tr>
                    <td>${result.strategy_name || ''}</td>
                    <td>${timingStrategyDisplay}</td>
                    <td>${result.start_date || ''}</td>
                    <td>${result.end_date || ''}</td>
                    <td>${result.created_at ? formatDateTime(result.created_at) : ''}</td>
                    <td class="${result.total_return >= 0 ? 'text-green-500' : 'text-red-500'}">
                        ${(result.total_return || 0).toFixed(2)}%
                    </td>
                    <td>${(result.win_rate || 0).toFixed(2)}%</td>
                    <td>${(result.profit_loss_ratio || 0).toFixed(2)}</td>
                    <td>${(result.max_drawdown || 0).toFixed(2)}%</td>
                    <td>${(result.sharpe_ratio || 0).toFixed(2)}</td>
                    <td>
                        <button class="btn btn-primary btn-sm" onclick="viewBacktestResult(${result.id})">
                            查看
                        </button>
                    </td>
                    <td>
                        <button class="btn btn-success btn-sm" onclick="exportBacktestResult(${result.id})" title="导出Excel">
                            📥 导出
                        </button>
                    </td>
                    <td>
                        <button class="btn btn-danger btn-sm" onclick="deleteBacktestResult(${result.id})" title="删除回测结果">
                            🗑️ 删除
                        </button>
                    </td>
                </tr>
            `}).join('');
        }
    }
}

/**
 * 删除回测结果
 * @param {number} resultId - 回测结果ID
 */
export async function deleteBacktestResult(resultId) {
    try {
        // 确认删除操作
        if (!confirm('确定要删除这条回测结果吗？此操作不可撤销！')) {
            return;
        }

        const response = await fetch(`/api/trading/backtest/results/${resultId}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();
        if (data.success) {
            showAlert('删除回测结果成功', 'success');
            // 刷新回测历史列表
            loadBacktestHistory();
        } else {
            throw new Error(data.message || '删除失败');
        }
    } catch (error) {
        console.error('删除回测结果失败:', error);
        showAlert('删除回测结果失败: ' + error.message, 'error');
    }
}

/**
 * 导出回测结果为Excel
 * @param {number} resultId - 回测结果ID
 */
export async function exportBacktestResult(resultId) {
    try {
        // 显示加载提示
        showAlert('正在导出回测报告...', 'info');
        
        const response = await fetch(`/api/trading/backtest/results/${resultId}/export`);
        
        if (response.ok) {
            // 获取文件名
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = '回测报告.xlsx';
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
            
            showAlert('导出成功', 'success');
        } else {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.message || '导出失败');
        }
    } catch (error) {
        console.error('导出回测结果失败:', error);
        showAlert('导出失败: ' + error.message, 'error');
    }
}

/**
 * 查看回测结果
 * @param {number} resultId - 回测结果ID
 */
export function viewBacktestResult(resultId) {
    // 显示模态框
    const modal = document.getElementById('backtest-result-modal');
    if (modal) {
        modal.style.display = 'block';
    }
    
    // 加载回测结果到模态框
    loadBacktestResultInModal(resultId);
}

/**
 * 关闭回测结果模态框
 */
export function closeBacktestModal() {
    const modal = document.getElementById('backtest-result-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * 在模态框中加载回测结果
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestResultInModal(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}`);
        if (!response.ok) {
            throw new Error('加载回测结果失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const result = data.data;
            displayBacktestResultInModal(result);
            
            // 绘制收益曲线
            if (result.equity_curve) {
                const capitalHistory = result.equity_curve.map(item => item.capital);
                const dates = result.equity_curve.map(item => item.date);
                drawEquityChartInModal(capitalHistory, dates);
            }
            
            // 加载交易记录
            loadBacktestTradesInModal(resultId);
        } else {
            throw new Error(data.message || '加载回测结果失败');
        }
    } catch (error) {
        console.error('加载回测结果失败:', error);
        alert('加载回测结果失败: ' + error.message);
        closeBacktestModal();
    }
}

/**
 * 在模态框中显示回测结果
 * @param {Object} result - 回测结果数据
 */
function displayBacktestResultInModal(result) {
    const resultsContainer = document.getElementById('modal-backtest-results-container');
    if (resultsContainer) {
        resultsContainer.innerHTML = `
            <div class="card" style="margin-bottom: 20px;">
                <div class="card-header">
                    <h3>回测概览</h3>
                </div>
                <div class="card-body">
                    <!-- 第一行：基本信息 -->
                    <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 200px;">
                            <label>策略名称</label>
                            <input type="text" value="${result.strategy_name || ''}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 200px;">
                            <label>回测期间</label>
                            <input type="text" value="${result.start_date || ''} 至 ${result.end_date || ''}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 200px;">
                            <label>择时策略</label>
                            <input type="text" value="${result.support_level_method || ''}" disabled>
                        </div>
                    </div>
                    
                    <!-- 第二行：资金信息 -->
                    <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>初始资金</label>
                            <input type="text" value="${result.initial_capital || 0}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>最终资金</label>
                            <input type="text" value="${(result.final_capital || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>总收益率</label>
                            <input type="text" value="${(result.total_return || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>最大回撤</label>
                            <input type="text" value="${(result.max_drawdown || 0).toFixed(2)}%" disabled>
                        </div>
                    </div>
                    
                    <!-- 第三行：交易统计 -->
                    <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>胜率</label>
                            <input type="text" value="${(result.win_rate || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>平均收益率</label>
                            <input type="text" value="${(result.avg_return || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>盈亏比</label>
                            <input type="text" value="${(result.profit_loss_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>总交易次数</label>
                            <input type="text" value="${result.total_trades || 0}" disabled>
                        </div>
                    </div>
                    
                    <!-- 第四行：风险指标 -->
                    <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>夏普比率</label>
                            <input type="text" value="${(result.sharpe_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>索提诺比率</label>
                            <input type="text" value="${(result.sortino_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>波动率</label>
                            <input type="text" value="${(result.volatility || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>盈利交易次数</label>
                            <input type="text" value="${result.winning_trades || 0}" disabled>
                        </div>
                    </div>
                    
                    <!-- 第五行：其他统计 -->
                    <div style="display: flex; gap: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>亏损交易次数</label>
                            <input type="text" value="${result.losing_trades || 0}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>平均持有天数</label>
                            <input type="text" value="${(result.avg_hold_days || 0).toFixed(2)}" disabled>
                        </div>
                    </div>
                </div>
            </div>
            
            ${result.params_snapshot ? `
            <!-- ★★【2026-10-03 用户要求 ✓】本次回测的「**主要参数设置情况**」 ✗→✓
                 来源 ✓：trading/backtest_engine.py::build_param_snapshot ✓
                   ⇒ 与「回测参数」日志**同一份** ✓（日志里看到的 = 这里显示的 ✓）；
                 为什么要看它 ✗✓：两次回测收益不同时，**先看这里**就能定位
                   "是哪项参数变了" ✓（此前只能翻日志 + 手查 yaml ✗✓）。
                 ⚠️ timing_params 单独补打 ✗✓ —— 海龟参数（n_entry / n_exit / atr_period ✓）
                   不在文本快照里 ✓，但它恰恰是最常被调的一项 ✗。
                 ⚠️【2026-10-04 修复 ✓】**本注释内严禁反引号** ✗✓ —— 本块位于**模板字符串**
                   内部 ✗（外层是反引号包裹的 HTML 串 ✓），而反引号会**提前结束模板串** ✗
                   ⇒ 整个模块**语法错误** ✗ ⇒ 浏览器报「加载模块失败，请刷新页面重试」✗✓
                   （实测发生 ✓）。⇒ 以后此块注释请用普通文字 ✓
                   （旁边 router_config 那块同样没有反引号 ✓）。 -->
            <div class="card" style="margin-bottom: 20px;">
                <div class="card-header">
                    <h3>本次回测的参数设置</h3>
                </div>
                <div class="card-body">
                    <pre style="white-space: pre-wrap; margin: 0; font-size: 13px; line-height: 1.8; color: #334155; font-family: inherit;">${(() => {
                        try {
                            const s = JSON.parse(result.params_snapshot);
                            const tp = (s.timing_params && Object.keys(s.timing_params).length)
                                ? ('\n\n择时策略: ' + (s.timing_strategy || '-')
                                   + '\n择时参数: ' + JSON.stringify(s.timing_params, null, 2))
                                : '';
                            return String(s.text || result.params_snapshot) + tp;
                        } catch (e) {
                            return String(result.params_snapshot);
                        }
                    })().replace(/&/g, '&amp;').replace(/</g, '&lt;')}</pre>
                </div>
            </div>` : ''}

            ${result.router_config ? `
            <!-- 选股/择时条件（各档位配置）——自适应回测保存时持久化 -->
            <div class="card" style="margin-bottom: 20px;">
                <div class="card-header">
                    <h3>选股/择时条件（各档位配置）</h3>
                </div>
                <div class="card-body">
                    <pre style="white-space: pre-wrap; margin: 0; font-size: 13px; line-height: 1.8; color: #334155; font-family: inherit;">${String(result.router_config).replace(/&/g, '&amp;').replace(/</g, '&lt;')}</pre>
                </div>
            </div>` : ''}
            
            <!-- 收益曲线图表 -->
            <div class="card" style="margin-bottom: 20px;">
                <div class="card-header">
                    <h3>收益曲线</h3>
                </div>
                <div class="card-body">
                    <!-- 【2026-09-20】Chart.js 标准写法：外层固定高度定位容器。
                         原为 canvas 内联 height（只改显示盒、不改绘制缓冲）→ 父容器高度自适应
                         时画布缓冲为 0 → 图表一片空白。 -->
                    <div style="position:relative; height:300px; width:100%;">
                        <canvas id="modal-backtest-equity-chart"></canvas>
                    </div>
                </div>
            </div>
        `;
    }
}

/**
 * 在模态框中加载回测交易记录
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestTradesInModal(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}/trades`);
        if (!response.ok) {
            throw new Error('加载交易记录失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const trades = data.data.trades;
            displayBacktestTradesInModal(trades);
        } else {
            throw new Error(data.message || '加载交易记录失败');
        }
    } catch (error) {
        console.error('加载交易记录失败:', error);
        alert('加载交易记录失败: ' + error.message);
    }
}

/**
 * 在模态框中显示回测交易记录
 * @param {Array} trades - 交易记录数组
 */
function displayBacktestTradesInModal(trades) {
    const tradesContainer = document.getElementById('modal-backtest-trades-container');
    if (tradesContainer) {
        if (trades.length === 0) {
            tradesContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <h3>交易记录</h3>
                    </div>
                    <div class="card-body">
                        <p class="text-center">暂无交易记录</p>
                    </div>
                </div>
            `;
        } else {
            tradesContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <h3>交易记录</h3>
                    </div>
                    <div class="card-body">
                        <div class="overflow-x-auto">
                            <table class="table">
                                <thead>
                                    <tr>
                                        <th>股票代码</th>
                                        <th>股票名称</th>
                                        <th>买入日期</th>
                                        <th>买入价格</th>
                                        <th>卖出日期</th>
                                        <th>卖出价格</th>
                                        <th>收益率</th>
                                        <th>交易类型</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${trades.map(trade => `
                                        <tr>
                                            <td><a href="${trade.detail_url || 'javascript:void(0)'}" onclick="viewStockDetail('${trade.stock_code}'); return false;" class="stock-link" style="color: #2563eb; text-decoration: none; cursor: pointer; font-weight: 600;">${trade.stock_code}</a></td>
                                            <td>${trade.stock_name}</td>
                                            <td>${trade.buy_date}</td>
                                            <td>${trade.buy_price}</td>
                                            <td>${trade.sell_date}</td>
                                            <td>${trade.sell_price}</td>
                                            <td class="${trade.return_rate >= 0 ? 'text-green-500' : 'text-red-500'}">
                                                ${trade.return_rate.toFixed(2)}%
                                            </td>
                                            <td>${trade.sell_type}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            `;
        }
    }
}

/**
 * 显示结果页面空状态
 * @param {string} message - 提示信息
 */
function showResultsEmptyState(message) {
    const resultsContainer = document.getElementById('backtest-results-container');
    const tradesContainer = document.getElementById('backtest-trades-container');
    
    if (resultsContainer) {
        resultsContainer.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>回测结果</h3>
                </div>
                <div class="card-body">
                    <p class="text-center">${message}</p>
                </div>
            </div>
        `;
    }
    
    if (tradesContainer) {
        tradesContainer.innerHTML = '';
    }
}

/**
 * 显示历史页面空状态
 * @param {string} message - 提示信息
 */
function showHistoryEmptyState(message) {
    const historyBody = document.getElementById('backtest-history-body');
    if (historyBody) {
        historyBody.innerHTML = `<tr><td colspan="11" class="loading">${message}</td></tr>`;
    }
}

/**
 * 搜索回测历史
 */
export async function searchBacktestHistory() {
    try {
        const strategyFilter = document.getElementById('backtest-history-strategy-filter');
        const dateInput = document.getElementById('backtest-history-date');
        
        const params = new URLSearchParams();
        if (strategyFilter?.value) params.append('strategy', strategyFilter.value);
        if (dateInput?.value) params.append('created_date', dateInput.value);
        
        const queryString = params.toString();
        const url = `/api/trading/backtest/results${queryString ? `?${queryString}` : ''}`;
        
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error('搜索回测历史失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const results = data.data.results;
            displayBacktestHistory(results);
        } else {
            throw new Error(data.message || '搜索回测历史失败');
        }
    } catch (error) {
        console.error('搜索回测历史失败:', error);
        showHistoryEmptyState('搜索回测历史失败: ' + error.message);
    }
}

/**
 * 在策略回测页面显示回测结果
 * @param {Object} result - 回测结果数据
 */
function displayBacktestResultOnConfigPage(result) {
    // 显示结果容器
    const resultContainer = document.getElementById('backtest-result-container');
    if (resultContainer) {
        resultContainer.style.display = 'block';
    }
    
    // 更新绩效指标卡片
    const totalReturnEl = document.getElementById('backtest-total-return');
    const winRateEl = document.getElementById('backtest-win-rate');
    const profitLossRatioEl = document.getElementById('backtest-profit-loss-ratio');
    const maxDrawdownEl = document.getElementById('backtest-max-drawdown');
    const sharpeRatioEl = document.getElementById('backtest-sharpe-ratio');
    
    if (totalReturnEl) totalReturnEl.textContent = `${(result.total_return || 0).toFixed(2)}%`;
    if (winRateEl) winRateEl.textContent = `${(result.win_rate || 0).toFixed(2)}%`;
    if (profitLossRatioEl) profitLossRatioEl.textContent = (result.profit_loss_ratio || 0).toFixed(2);
    if (maxDrawdownEl) maxDrawdownEl.textContent = `${(result.max_drawdown || 0).toFixed(2)}%`;
    if (sharpeRatioEl) sharpeRatioEl.textContent = (result.sharpe_ratio || 0).toFixed(2);
    
    // 更新温度约束统计
    const tempStatsEl = document.getElementById('temp-constraint-stats');
    if (tempStatsEl && result.temp_constraint_stats) {
        const stats = result.temp_constraint_stats;
        if (stats.enabled) {
            tempStatsEl.style.display = 'block';
            const modeNames = {'count': '数量', 'position': '仓位', 'both': '两者'};
            document.getElementById('temp-stats-mode').textContent = modeNames[stats.mode] || stats.mode || '--';
            document.getElementById('temp-stats-constrained').textContent = `${stats.days_constrained || 0}天`;
            document.getElementById('temp-stats-banned').textContent = `${stats.days_banned || 0}天`;
            document.getElementById('temp-stats-position').textContent = `${((stats.avg_position_applied || 0) * 100).toFixed(0)}%`;
            document.getElementById('temp-stats-count').textContent = `${stats.constrained_by_count || 0}天`;
            document.getElementById('temp-stats-pos').textContent = `${stats.constrained_by_position || 0}天`;
        } else {
            tempStatsEl.style.display = 'none';
        }
    } else if (tempStatsEl) {
        tempStatsEl.style.display = 'none';
    }
    
    // 绘制收益曲线
    // 注意：result 中没有 capital_history 和 dates，需要从 equity_curve 中提取
    if (result.equity_curve && result.equity_curve.length > 0) {
        const capitalHistory = result.equity_curve.map(item => item.capital);
        const dates = result.equity_curve.map(item => item.date);
        drawEquityChart(capitalHistory, dates);
    } else if (result.capital_history && result.capital_history.length > 0) {
        // 如果没有 equity_curve，尝试使用 capital_history 和 dates（备用方案）
        drawEquityChart(result.capital_history, result.dates || []);
    } else {
        // 如果没有任何收益曲线数据，显示提示信息
        console.warn('没有收益曲线数据');
        const ctx = document.getElementById('backtest-equity-chart');
        if (ctx && ctx.parentElement) {
            ctx.parentElement.innerHTML = '<div style="text-align: center; padding: 40px; color: #6b7280;">暂无收益曲线数据</div>';
        }
    }
}

/**
 * 绘制收益曲线
 * @param {Array} capitalHistory - 资金历史
 * @param {Array} dates - 日期列表
 */
function drawEquityChart(capitalHistory, dates) {
    // 检查数据有效性
    if (!capitalHistory || capitalHistory.length === 0 || !dates || dates.length === 0) {
        console.warn('收益曲线数据为空，无法绘制图表');
        const ctx = document.getElementById('backtest-equity-chart');
        if (ctx) {
            const parent = ctx.parentElement;
            if (parent) {
                parent.innerHTML = '<div style="text-align: center; padding: 40px; color: #6b7280;">暂无收益曲线数据</div>';
            }
        }
        return;
    }
    
    const ctx = document.getElementById('backtest-equity-chart');
    if (!ctx) {
        console.error('找不到图表容器元素');
        return;
    }
    
    // 销毁旧图表
    if (window.equityChart) {
        window.equityChart.destroy();
    }
    
    // 准备数据
    const labels = dates.map(date => {
        if (date instanceof Date) {
            return date.toISOString().split('T')[0];
        }
        return date;
    });
    
    // 计算收益率
    const initialCapital = capitalHistory[0] || 1000000;
    const returns = capitalHistory.map(capital => {
        return ((capital - initialCapital) / initialCapital) * 100;
    });
    
    // 创建新图表
    try {
        if (!window.Chart) { throw new Error('图表库(Chart.js)未加载'); }
        window.equityChart = new window.Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: '收益率 (%)',
                    data: returns,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: '收益率 (%)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: '日期'
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error('绘制收益曲线失败:', error);
    }
}

/**
 * 在模态框中绘制收益曲线
 * @param {Array} capitalHistory - 资金历史
 * @param {Array} dates - 日期列表
 */
function _backtestChartHint() {
    const box = document.getElementById('modal-backtest-results-container');
    if (!box || document.getElementById('backtest-chart-hint')) return;
    const div = document.createElement('div');
    div.id = 'backtest-chart-hint';
    div.className = 'card';
    div.style.marginBottom = '20px';
    div.innerHTML = '<div class="card-header"><h3>收益曲线</h3></div>'
        + '<div class="card-body" style="color:#b45309;font-size:13px;">'
        + '⚠️ 图表库（Chart.js）未加载。项目已内置本地副本（无需联网），'
        + '请按 <b>F5</b> 重新加载页面；其余回测数据不受影响。</div>';
    box.appendChild(div);
}

function drawEquityChartInModal(capitalHistory, dates) {
    // 【2026-09-20 修复】Chart.js 由 CDN 引入，若未加载/被网络阻断，
    //   原实现用裸标识符 `new Chart(...)` 会抛 "Chart is not defined" →
    //   被 loadBacktestResultInModal 的 try 兜住 → 整个详情报"加载回测结果失败"。
    //   现：改用 window.Chart（ES 模块下更稳妥）+ 缺库时只提示、不阻断详情加载。
    if (!window.Chart) {
        // 【2026-09-20】自愈：缺库时动态加载**项目内置**的本地 Chart.js，加载完成后重绘本图。
        //   注意：不依赖 dashboard_stats.js（可能未加载或未更新），此处自带加载逻辑，
        //   因此只要页面重新加载过（F5）就一定能画出来，且**无需联网**。
        if (window.ensureChartJs) {
            window.ensureChartJs(function () { drawEquityChartInModal(capitalHistory, dates); });
            return;
        }
        if (!window.__backtestChartLoading) {
            window.__backtestChartLoading = true;
            const s = document.createElement('script');
            s.src = '/static/js/lib/chart.umd.min.js';
            s.onload = function () {
                window.__backtestChartLoading = false;
                if (window.Chart) {
                    drawEquityChartInModal(capitalHistory, dates);   // 加载成功 → 重绘
                } else {
                    _backtestChartHint();
                }
            };
            s.onerror = function () { window.__backtestChartLoading = false; _backtestChartHint(); };
            document.head.appendChild(s);
            return;
        }
        _backtestChartHint();
        return;
    }
    const ctx = document.getElementById('modal-backtest-equity-chart');
    if (!ctx) {
        // 如果模态框中没有图表元素，添加一个
        const modalContent = document.getElementById('modal-backtest-results-container');
        if (modalContent) {
            modalContent.innerHTML += `
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <h3>收益曲线</h3>
                    </div>
                    <div class="card-body">
                        <!-- 【2026-09-20】同上：固定高度定位容器（否则画布缓冲为 0 → 图表空白） -->
                        <div style="position:relative; height:300px; width:100%;">
                            <canvas id="modal-backtest-equity-chart"></canvas>
                        </div>
                    </div>
                </div>
            `;
        }
    }
    
    const _canvasEl = document.getElementById('modal-backtest-equity-chart');
    if (!_canvasEl) {   // 【2026-09-20】兜底：画布不存在时不再抛错中断整个详情加载
        console.warn('[回测详情] 未找到收益曲线画布，跳过绘制');
        return;
    }
    const chartCtx = _canvasEl.getContext('2d');
    
    // 销毁旧图表
    if (window.modalEquityChart) {
        window.modalEquityChart.destroy();
    }
    
    // 准备数据
    const labels = dates.map(date => {
        if (date instanceof Date) {
            return date.toISOString().split('T')[0];
        }
        return date;
    });
    
    // 计算收益率
    const initialCapital = capitalHistory[0] || 1000000;
    const returns = capitalHistory.map(capital => {
        return ((capital - initialCapital) / initialCapital) * 100;
    });
    
    // 创建新图表（window.Chart：ES 模块下避免裸标识符解析问题）
    window.modalEquityChart = new window.Chart(chartCtx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: '收益率 (%)',
                data: returns,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: '收益率 (%)'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: '日期'
                    }
                }
            }
        }
    });
}

/**
 * 加载回测交易记录（在策略回测页面）
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestTradesOnConfigPage(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}/trades`);
        if (!response.ok) {
            throw new Error('加载交易记录失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const trades = data.data.trades;
            displayBacktestTradesOnConfigPage(trades);
        } else {
            throw new Error(data.message || '加载交易记录失败');
        }
    } catch (error) {
        console.error('加载交易记录失败:', error);
        alert('加载交易记录失败: ' + error.message);
    }
}

/**
 * 在策略回测页面显示交易记录
 * @param {Array} trades - 交易记录数组
 */
function _tradeTypeLabel(tradeType, sellType) {
    // ★【2026-09-29 用户要求 ✓】交易类型**中文化** ✗→✓（自适应那份直接打英文 `normal/sell` ✗）
    //   口径 ✓：先看 `trade_type`（`new`=建仓 / `add`=加仓 / `sell`=清仓 / `reduce`=减仓 ✓），
    //   再看 `sell_type`（卖出原因 ✓，如 `stop_loss` / `take_profit` ✓）；
    //   ⚠️ **认不出就原样显示** ✓（绝不伪造语义 ✗），空值显示 `-` ✓。
    const MAP = {
        new: '建仓', add: '加仓', sell: '清仓', reduce: '减仓',
        stop_loss: '止损', take_profit: '止盈', time_exit: '到期',
        pool_remove: '池移除', normal: '普通卖出', final: '期末平仓',
    };
    const t = String(tradeType || '').trim();
    const s = String(sellType || '').trim();
    if (t && MAP[t]) return MAP[t];
    if (s && MAP[s]) return MAP[s];
    return (t || s || '-');
}

function displayBacktestTradesOnConfigPage(trades) {
    const tradesBody = document.getElementById('backtest-trades-body');
    if (!tradesBody) {
        console.error('找不到交易记录表格容器');
        return;
    }
    
    // 检查trades是否为有效的数组
    if (!Array.isArray(trades)) {
        console.warn('交易记录不是数组:', trades);
        tradesBody.innerHTML = '<tr><td colspan="9" class="text-center">交易记录格式错误</td></tr>';
        return;
    }
    
    if (trades.length === 0) {
        // ★【2026-09-29】`colspan` 必须与**表头列数**一致 ✗✓（表头 9 列 ✓ ⇒ 否则空态行错位 ✗）
        tradesBody.innerHTML = '<tr><td colspan="9" class="text-center">暂无交易记录</td></tr>';
    } else {
        try {
            tradesBody.innerHTML = trades.map(trade => {
                // 安全地获取交易数据
                const stockCode = trade.stock_code || '-';
                const stockName = trade.stock_name || '-';
                const buyDate = trade.buy_date || '-';
                const sellDate = trade.sell_date || '-';
                // ★【2026-09-29】`0` **不能**被 `||` 吞掉 ✗✓（持有 0 日 = 当日买当日卖 ✓ 是真值 ✓）
                const holdDays = (trade.hold_days === null || trade.hold_days === undefined)
                    ? '-' : trade.hold_days;
                // ★【2026-09-29 用户要求 ✓】新增三列 ✓（照自适应那份 ✓）：
                //   买入价格 / 卖出价格 / 交易类型 ✓；⚠️ 未平仓(`None`) ⇒ `-` ✓（**不写 0** ✗）
                const _num2 = (v) => (v === null || v === undefined || v === '')
                    ? '-' : Number(v).toFixed(2);
                const buyPrice = _num2(trade.buy_price);
                const sellPrice = _num2(trade.sell_price);
                const typeText = _tradeTypeLabel(trade.trade_type, trade.sell_type);
                const returnRate = trade.return_rate;
                const detailUrl = trade.detail_url || 'javascript:void(0)';
                
                // 确定收益率的颜色
                let returnRateClass = '';
                let returnRateText = '-';
                if (returnRate !== null && returnRate !== undefined) {
                    returnRateClass = returnRate >= 0 ? 'text-green-500' : 'text-red-500';
                    returnRateText = returnRate.toFixed(2) + '%';
                }
                
                // 生成股票代码链接
                const stockCodeLink = stockCode !== '-' 
                    ? `<a href="${detailUrl}" onclick="viewStockDetail('${stockCode}'); return false;" class="stock-link" style="color: #2563eb; text-decoration: none; cursor: pointer; font-weight: 600;">${stockCode}</a>`
                    : stockCode;
                
                return `
                    <tr>
                        <td>${stockCodeLink}</td>
                        <td>${stockName}</td>
                        <td>${buyDate}</td>
                        <td>${buyPrice}</td>
                        <td>${sellDate}</td>
                        <td>${sellPrice}</td>
                        <td>${holdDays}</td>
                        <td class="${returnRateClass}">${returnRateText}</td>
                        <td>${typeText}</td>
                    </tr>
                `;
            }).join('');
        } catch (error) {
            console.error('显示交易记录失败:', error);
            tradesBody.innerHTML = '<tr><td colspan="9" class="text-center">显示交易记录失败</td></tr>';
        }
    }
}

/**
 * 显示提示信息（兼容函数，确保在所有页面都能正常工作）
 * @param {string} message - 提示信息
 * @param {string} type - 提示类型：info/success/error/warning
 */
function showAlert(message, type = 'info') {
    // 如果全局已有showAlert函数，直接调用
    if (typeof window.showAlert === 'function') {
        window.showAlert(message, type);
        return;
    }
    
    // 否则使用原生alert作为后备（简化版）
    if (type === 'error') {
        alert('错误: ' + message);
    } else if (type === 'success') {
        alert('成功: ' + message);
    } else {
        console.log(message);
    }
}

// 暴露全局函数
window.viewBacktestResult = viewBacktestResult;
window.searchBacktestHistory = searchBacktestHistory;
window.closeBacktestModal = closeBacktestModal;
window.exportBacktestResult = exportBacktestResult;
