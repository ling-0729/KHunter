/**
 * 策略运行模块
 * 实现策略运行的前端界面和交互（简化版 - 无方案管理）
 */

// 策略运行模块
const StrategyRunnerModule = {
    // 执行任务列表
    tasks: [],
    
    // 正在执行标志（防止重复请求）
    _isExecuting: false,
    
    // 策略名称映射表（英文类名 -> 中文名称）
    strategyNameMap: {},
    
    // 事件监听器引用（用于解绑）
    _signalExecuteHandler: null,
    _signalIgnoreHandler: null,
    
    // 获取策略中文名称
    getStrategyDisplayName: function(strategyName) {
        return this.strategyNameMap[strategyName] || strategyName;
    },
    
    // 加载策略名称映射
    loadStrategyNames: async function() {
        try {
            const response = await fetch('/api/strategies/names');
            const result = await response.json();
            if (result.success) {
                this.strategyNameMap = result.data;
            }
        } catch (error) {
            console.error('加载策略名称映射失败:', error);
        }
    },
    
    // 初始化策略运行模块
    initStrategyRunnerModule: async function() {
        await this.loadStrategyNames();
        this.setupEventListeners();
        await this.loadStrategyRunnerPage();
        // 页面加载时自动加载持仓信息
        await this.loadPortfolio();
    },
    
    // 设置事件监听器
    setupEventListeners: function() {
        // 初始化按钮
        const initBtn = document.getElementById('init-runner-btn');
        if (initBtn) {
            initBtn.addEventListener('click', () => this.initializeRunner());
        }
        
        // 加入任务按钮（先解绑防止重复绑定）
        const addTaskBtn = document.getElementById('add-runner-task-btn');
        if (addTaskBtn) {
            addTaskBtn.removeEventListener('click', this._addTaskHandler);
            this._addTaskHandler = () => this.addTask();
            addTaskBtn.addEventListener('click', this._addTaskHandler);
        }
        
        // 开始执行按钮
        const startBtn = document.getElementById('start-runner-btn');
        if (startBtn) {
            startBtn.addEventListener('click', () => this.startExecution());
        }
        
        // 取消按钮
        const cancelBtn = document.getElementById('cancel-runner-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this.cancelExecution());
        }
        
        // 信号执行按钮（动态代理）- 先解绑防止重复绑定
        if (this._signalExecuteHandler) {
            document.removeEventListener('click', this._signalExecuteHandler);
        }
        this._signalExecuteHandler = (e) => {
            if (e.target.classList.contains('execute-signal-btn')) {
                const signalId = e.target.dataset.signalId;
                this.executeSignal(signalId);
            }
        };
        document.addEventListener('click', this._signalExecuteHandler);
        
        // 信号忽略按钮（动态代理）- 先解绑防止重复绑定
        if (this._signalIgnoreHandler) {
            document.removeEventListener('click', this._signalIgnoreHandler);
        }
        this._signalIgnoreHandler = (e) => {
            if (e.target.classList.contains('ignore-signal-btn')) {
                const signalId = e.target.dataset.signalId;
                this.ignoreSignal(signalId);
            }
        };
        document.addEventListener('click', this._signalIgnoreHandler);
        
        // 任务删除按钮（动态代理）
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('remove-task-btn')) {
                const index = parseInt(e.target.dataset.index);
                this.removeTask(index);
            }
        });
    },
    
    // 加载策略运行页面
    loadStrategyRunnerPage: async function() {
        // 检查策略运行器是否已经初始化
        await this.checkRunnerStatus();
        
        // 加载选股策略列表
        try {
            await this.loadSelectionStrategies();
        } catch (error) {
            console.error('加载选股策略失败:', error);
        }
        
        // 加载择时策略列表（从后端动态获取）
        try {
            await this.loadTimingStrategies();
        } catch (error) {
            console.error('加载择时策略失败:', error);
        }
        
        // 加载运行状态
        try {
            await this.loadStrategyStatus();
        } catch (error) {
            console.error('加载运行状态失败:', error);
        }
        
        // 加载持仓信息
        try {
            await this.loadPortfolio();
        } catch (error) {
            console.error('加载持仓信息失败:', error);
        }
        
        // 加载信号列表
        try {
            await this.loadSignals();
        } catch (error) {
            console.error('加载信号列表失败:', error);
        }
        
        // 加载股票池
        try {
            await this.loadStockPool();
        } catch (error) {
            console.error('加载股票池失败:', error);
        }
        
        // 加载上次运行的任务
        try {
            await this.loadLastTask();
        } catch (error) {
            console.error('加载上次任务失败:', error);
        }
    },
    
    // 加载选股策略列表
    loadSelectionStrategies: async function() {
        try {
            const response = await fetch('/api/strategies');
            const result = await response.json();
            
            if (result.success && result.strategies) {
                const select = document.getElementById('selection-strategy');
                if (select) {
                    select.innerHTML = result.strategies.map(strategy => 
                        `<option value="${strategy.name}">${strategy.display_name || strategy.name}</option>`
                    ).join('');
                }
            }
        } catch (error) {
            console.error('加载选股策略失败:', error);
        }
    },
    
    // 加载择时策略列表（从后端API动态获取）
    loadTimingStrategies: async function() {
        try {
            const response = await fetch('/api/timing-strategies');
            const result = await response.json();
            
            if (result.success && result.strategies) {
                // 更新所有择时策略选择器
                const timingSelects = document.querySelectorAll('select[id="timing-strategy"]');
                timingSelects.forEach(select => {
                    const selectedValue = select.value;
                    select.innerHTML = result.strategies.map(strategy => 
                        `<option value="${strategy.name}" ${strategy.name === selectedValue ? 'selected' : ''}>${strategy.display_name || strategy.name}</option>`
                    ).join('');
                });
            }
        } catch (error) {
            console.error('加载择时策略失败:', error);
        }
    },
    
    // 添加任务
    addTask: function(strategyName = null, displayName = null, timingStrategy = null, timingDisplayName = null) {
        const selectionSelect = document.getElementById('selection-strategy');
        // 如果提供了策略名称，使用它；否则从下拉框获取
        const selectionStrategy = strategyName || selectionSelect.value;
        
        // 如果没有提供策略名称且下拉框没有选中任何策略，显示错误
        if (!selectionStrategy) {
            alert('请选择选股策略');
            return;
        }
        
        // 获取显示名称（优先使用传入的displayName，然后尝试转换为中文）
        let selectionStrategyDisplayName = displayName || '';
        if (!selectionStrategyDisplayName) {
            if (strategyName) {
                // 尝试获取中文名称，找不到则使用原名称
                selectionStrategyDisplayName = this.getStrategyDisplayName(strategyName);
            } else {
                selectionStrategyDisplayName = selectionSelect.options[selectionSelect.selectedIndex].text;
            }
        }
        
        const timingSelect = document.getElementById('timing-strategy');
        // 如果提供了择时策略，使用它；否则从下拉框获取
        const finalTimingStrategy = timingStrategy || timingSelect.value;
        
        // 获取择时策略显示名称
        let finalTimingDisplayName = timingDisplayName || '';
        if (!finalTimingDisplayName) {
            // 在下拉框中查找对应的显示名称
            for (let i = 0; i < timingSelect.options.length; i++) {
                if (timingSelect.options[i].value === finalTimingStrategy) {
                    finalTimingDisplayName = timingSelect.options[i].text;
                    break;
                }
            }
            // 如果没找到，使用策略名作为显示名称
            if (!finalTimingDisplayName) {
                finalTimingDisplayName = finalTimingStrategy;
            }
        }
        
        const task = {
            selection_strategy: selectionStrategy,
            selection_strategy_display_name: selectionStrategyDisplayName,
            timing_strategy: finalTimingStrategy,
            timing_strategy_display_name: finalTimingDisplayName
        };
        
        this.tasks.push(task);
        this.renderTaskList();
    },
    
    // 移除任务
    removeTask: function(index) {
        if (index >= 0 && index < this.tasks.length) {
            this.tasks.splice(index, 1);
            this.renderTaskList();
        }
    },
    
    // 渲染任务列表
    renderTaskList: function() {
        const taskListEl = document.getElementById('runner-task-list');
        const taskBody = document.getElementById('runner-task-body');
        const taskCount = document.getElementById('runner-task-count');
        const startBtn = document.getElementById('start-runner-btn');
        
        if (this.tasks.length === 0) {
            taskListEl.style.display = 'none';
            return;
        }
        
        taskListEl.style.display = 'block';
        taskCount.textContent = this.tasks.length;
        startBtn.disabled = false;
        
        taskBody.innerHTML = this.tasks.map((task, index) => `
            <tr>
                <td>${index + 1}</td>
                <td style="word-break:break-all;">${task.selection_strategy_display_name || task.selection_strategy}</td>
                <td>${task.timing_strategy_display_name || task.timing_strategy}</td>
                <td style="text-align:center;">
                    <button class="btn btn-sm btn-outline-danger remove-task-btn" data-index="${index}">删除</button>
                </td>
            </tr>
        `).join('');
    },
    
    // 检查策略运行器状态
    checkRunnerStatus: async function() {
        try {
            const response = await fetch('/api/strategy/status');
            const result = await response.json();
            
            const initBtn = document.getElementById('init-runner-btn');
            const startBtn = document.getElementById('start-runner-btn');
            
            // 根据 status 字段判断是否初始化
            const isInitialized = result.success && result.data && result.data.status !== 'not_initialized';
            
            if (isInitialized) {
                // 已经初始化
                if (initBtn) {
                    initBtn.innerHTML = '已初始化';
                    initBtn.classList.remove('btn-primary');
                    initBtn.classList.add('btn-secondary');
                }
                if (startBtn) {
                    startBtn.disabled = false;
                }
                console.log('策略运行器已初始化');
            } else {
                // 未初始化
                if (initBtn) {
                    initBtn.innerHTML = '初始化策略运行器';
                    initBtn.classList.remove('btn-secondary');
                    initBtn.classList.add('btn-primary');
                }
                if (startBtn) {
                    startBtn.disabled = true;
                }
                console.log('策略运行器未初始化，需要手动点击初始化按钮');
            }
        } catch (error) {
            console.error('检查策略运行器状态失败:', error);
        }
    },
    
    // 手动初始化策略运行器
    initializeRunner: async function() {
        const initBtn = document.getElementById('init-runner-btn');
        const startBtn = document.getElementById('start-runner-btn');
        
        if (initBtn) {
            initBtn.disabled = true;
            initBtn.innerHTML = '初始化中...';
        }
        
        try {
            const response = await fetch('/api/strategy/initialize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const result = await response.json();
            
            if (result.success) {
                // 如果已经初始化，显示成功状态并启用按钮
                if (result.message.includes('已经初始化')) {
                    this.appendLog('✅ ' + result.message);
                } else {
                    this.appendLog('✅ 策略运行器初始化成功');
                }
                if (startBtn) {
                    startBtn.disabled = false;
                }
                // 修改初始化按钮状态
                if (initBtn) {
                    initBtn.innerHTML = '已初始化';
                    initBtn.classList.remove('btn-primary');
                    initBtn.classList.add('btn-secondary');
                }
                // 加载持仓信息，更新资金显示
                await this.loadPortfolio();
            } else {
                this.appendLog('❌ 策略运行器初始化失败: ' + result.message);
            }
        } catch (error) {
            this.appendLog('❌ 策略运行器初始化失败: ' + error.message);
        } finally {
            if (initBtn) {
                initBtn.disabled = false;
            }
        }
    },
    
    // 开始执行
    startExecution: async function() {
        if (this.tasks.length === 0) {
            alert('请先添加执行任务');
            return;
        }
        
        // 防止重复请求
        if (this._isExecuting) {
            this.appendLog('任务正在执行中，请稍候...');
            return;
        }
        this._isExecuting = true;
        
        // 更新状态
        document.getElementById('execution-status').className = 'execution-status status-running';
        document.getElementById('execution-status').textContent = '执行中';
        
        // 显示进度
        document.getElementById('runner-progress-container').style.display = 'block';
        document.getElementById('runner-current-task').textContent = '正在执行...';
        document.getElementById('runner-progress-fill').style.width = '0%';
        document.getElementById('runner-progress-percent').textContent = '0%';
        
        // 清空日志
        document.getElementById('execution-log').innerHTML = '<p style="color:#22c55e; margin:0;">开始执行...</p>';
        
        // 使用批量执行 API
        try {
            document.getElementById('runner-current-task').textContent = `批量执行 ${this.tasks.length} 个任务...`;
            this.appendLog(`批量执行 ${this.tasks.length} 个策略任务`);
            
            const response = await fetch('/api/strategy/run-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tasks: this.tasks.map(t => ({
                        selection_strategy: t.selection_strategy,
                        timing_strategy: t.timing_strategy
                    }))
                })
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.appendLog('✓ 批量执行成功');
                
                // 显示每个任务的执行结果
                if (result.data && result.data.task_results) {
                    result.data.task_results.forEach((task, idx) => {
                        if (task.status === 'success') {
                            this.appendLog(`  ${idx + 1}. ${task.selection_strategy}: 选出 ${task.selected_count} 只，新增 ${task.new_added} 只`);
                        } else {
                            this.appendLog(`  ${idx + 1}. ${task.selection_strategy}: 失败 - ${task.error || '未知错误'}`);
                        }
                    });
                }
                
                this.appendLog(`股票池: ${result.data?.pool_count || 0} 只`);
                this.appendLog(`买入信号: ${result.data?.buy_signals || 0} 个`);
                this.appendLog(`卖出信号: ${result.data?.sell_signals || 0} 个`);
            } else {
                this.appendLog(`✗ 失败: ${result.message || '未知错误'}`);
            }
        } catch (error) {
            console.error('批量执行失败:', error);
            this.appendLog(`✗ 失败: ${error.message}`);
        } finally {
            // 重置执行状态
            this._isExecuting = false;
        }
        
        // 执行完成
        this.appendLog('--- 执行完成 ---');
        document.getElementById('execution-status').className = 'execution-status status-idle';
        document.getElementById('execution-status').textContent = '就绪';
        
        // 更新进度条到100%并隐藏
        document.getElementById('runner-progress-fill').style.width = '100%';
        document.getElementById('runner-progress-percent').textContent = '100%';
        setTimeout(() => {
            document.getElementById('runner-progress-container').style.display = 'none';
        }, 500);
        
        // 刷新页面数据
        this.loadStrategyStatus();
        this.loadPortfolio();
        this.loadSignals();
        this.loadStockPool();  // 新增：刷新股票池
        
        // 清空任务列表
        this.tasks = [];
        this.renderTaskList();
    },
    
    // 取消执行
    cancelExecution: function() {
        document.getElementById('runner-progress-container').style.display = 'none';
        document.getElementById('execution-status').className = 'execution-status status-idle';
        document.getElementById('execution-status').textContent = '已取消';
        this.appendLog('执行已取消');
    },
    
    // 加载运行状态
    loadStrategyStatus: async function() {
        try {
            const response = await fetch('/api/strategy/status');
            const result = await response.json();
            
            if (result.success) {
                const statusContainer = document.getElementById('strategy-status');
                if (statusContainer) {
                    const status = result.data;
                    statusContainer.innerHTML = `
                        <div class="card-body" style="padding:10px 16px;">
                            <div style="display:flex; gap:24px; flex-wrap:wrap; font-size:13px;">
                                <div><strong>当前状态:</strong> ${status.running ? '运行中' : '停止'}</div>
                                <div><strong>今日已选股:</strong> ${status.selected_stocks || 0} 只</div>
                                <div><strong>今日已交易:</strong> ${status.today_trades || 0} 笔</div>
                                <div><strong>最后运行:</strong> ${status.last_run || '从未'}</div>
                            </div>
                        </div>
                    `;
                }
            }
        } catch (error) {
            console.error('加载策略状态失败:', error);
        }
    },
    
    // 加载持仓信息
    loadPortfolio: async function() {
        try {
            const response = await fetch('/api/portfolio');
            const result = await response.json();
            
            if (result.success) {
                const portfolio = result.data;
                
                // 更新统计卡片（含日期）
                const portfolioDate = portfolio.date || 'N/A';
                document.getElementById('position-count').textContent = portfolio.positions_count || 0;
                document.getElementById('available-cash').textContent = '¥' + (portfolio.available_cash || 0).toLocaleString();
                document.getElementById('total-assets').textContent = '¥' + (portfolio.total_assets || 0).toLocaleString();
                document.getElementById('portfolio-profit').textContent = (portfolio.total_profit_percent || 0).toFixed(2) + '%';
                
                // 存储运行模式（自动模式下隐藏操作按钮）
                const isAutoMode = portfolio.run_mode === 'auto';
                
                // 更新资金日期显示
                const portfolioDateEl = document.getElementById('portfolio-date');
                if (portfolioDateEl) {
                    portfolioDateEl.textContent = `数据日期: ${portfolioDate}`;
                }
                
                // 更新持仓列表
                const portfolioList = document.getElementById('portfolio-list');
                if (portfolioList) {
                    if (portfolio.positions && portfolio.positions.length > 0) {
                        portfolioList.innerHTML = portfolio.positions.map(pos => {
                            const costPrice = parseFloat(pos.cost_price) || 0;
                            const currentPrice = parseFloat(pos.current_price) || 0;
                            const profitLoss = parseFloat(pos.profit_loss) || 0;
                            const profitLossPercent = parseFloat(pos.profit_loss_percent) || 0;
                            const profitColor = profitLoss >= 0 ? '#22c55e' : '#ef4444';
                            // 自动模式下不显示卖出按钮，显示提示文字
                            const actionCell = isAutoMode
                                ? '<span style="color:#9ca3af; font-size:12px;">自动</span>'
                                : `<button onclick="sellPosition('${pos.stock_code}', '${pos.stock_name}')"
                                        style="padding:4px 12px; background:#ef4444; color:white; border:none; border-radius:4px; cursor:pointer; font-size:12px;">卖出</button>`;
                            return `
                            <tr>
                                <td><a href="javascript:void(0)" onclick="viewStockDetail('${pos.stock_code}')">${pos.stock_code}</a></td>
                                <td>${pos.stock_name}</td>
                                <td>${pos.quantity}</td>
                                <td>¥${costPrice.toFixed(2)}</td>
                                <td>¥${currentPrice.toFixed(2)}</td>
                                <td style="color: ${profitColor}">${profitLoss >= 0 ? '+' : ''}¥${profitLoss.toFixed(2)}</td>
                                <td style="color: ${profitLossPercent >= 0 ? '#22c55e' : '#ef4444'}">
                                    ${profitLossPercent >= 0 ? '+' : ''}${profitLossPercent.toFixed(2)}%
                                </td>
                                <td>${pos.hold_days}</td>
                                <td>${actionCell}</td>
                            </tr>
                            `;
                        }).join('');
                    } else {
                        portfolioList.innerHTML = '<tr><td colspan="9" style="text-align:center; color:#9ca3af;">暂无持仓</td></tr>';
                    }
                }
            }
        } catch (error) {
            console.error('加载持仓信息失败:', error);
        }
    },
    
    // 卖出持仓
    sellPosition: async function(stockCode, stockName) {
        if (!confirm(`确定要卖出 ${stockName} (${stockCode}) 吗？`)) {
            return;
        }
        
        try {
            const response = await fetch('/api/portfolio/sell', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    stock_code: stockCode
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                alert(`卖出成功: ${stockName} (${stockCode})`);
                // 重新加载持仓
                this.loadPortfolio();
            } else {
                alert(`卖出失败: ${result.error || '未知错误'}`);
            }
        } catch (error) {
            console.error('卖出失败:', error);
            alert(`卖出失败: ${error.message}`);
        }
    },
    
    // 加载信号列表
    loadSignals: async function() {
        try {
            const response = await fetch('/api/signals');
            const result = await response.json();
            
            if (result.success) {
                const signals = result.data.signals || [];  // 修复：获取signals数组
                const signalsDate = result.data.date || 'N/A';
                const signalsList = document.getElementById('signals-list');
                
                // 更新信号标题（格式：XX年X月X日信号（卖出XX条，买入XX条，其中加仓XX条））
                const signalsTitleEl = document.getElementById('signals-title');
                if (signalsTitleEl) {
                    const sellCount = signals.filter(s => s.signal_type === 'sell').length;
                    const buyCount = signals.filter(s => s.signal_type === 'buy').length;
                    const addCount = signals.filter(s => s.signal_type === 'buy' && s.trade_type === 'add').length;
                    
                    // 格式化日期
                    let formattedDate = '今日';
                    if (signalsDate !== 'N/A') {
                        const dateParts = signalsDate.split('-');
                        if (dateParts.length === 3) {
                            formattedDate = `${dateParts[0]}年${parseInt(dateParts[1])}月${parseInt(dateParts[2])}日`;
                        }
                    }
                    
                    signalsTitleEl.textContent = `${formattedDate}信号（卖出${sellCount}条，买入${buyCount}条，其中加仓${addCount}条）`;
                }
                
                if (signalsList) {
                    // 自动模式下信号操作按钮不可用
                    const isAutoMode = result.data.run_mode === 'auto';
                    if (signals && signals.length > 0) {
                        signalsList.innerHTML = signals.map(signal => {
                            // 自动模式下：已执行信号显示标记，未执行信号显示"自动"提示
                            let actionCell;
                            if (isAutoMode) {
                                actionCell = signal.executed
                                    ? '<span class="badge bg-secondary">已执行</span>'
                                    : '<span style="color:#9ca3af; font-size:12px;">自动</span>';
                            } else {
                                actionCell = signal.executed
                                    ? '<span class="badge bg-secondary">已执行</span>'
                                    : `<button class="btn btn-sm btn-success execute-signal-btn" data-signal-id="${signal.id}">执行</button>
                                       <button class="btn btn-sm btn-secondary ignore-signal-btn" data-signal-id="${signal.id}">忽略</button>`;
                            }
                            return `
                            <tr>
                                <td>${signal.signal_type === 'buy' ? '<span style="color:#22c55e;">买入</span>' : '<span style="color:#ef4444;">卖出</span>'}</td>
                                <td><a href="javascript:void(0)" onclick="viewStockDetail('${signal.stock_code}')">${signal.stock_code}</a></td>
                                <td>${signal.stock_name}</td>
                                <td>¥${signal.price.toFixed(2)}</td>
                                <td>${signal.quantity}</td>
                                <td>${this.getStrategyDisplayName(signal.strategy_name) || 'N/A'}</td>
                                <td>${signal.reason}</td>
                                <td>${actionCell}</td>
                            </tr>
                            `;
                        }).join('');
                    } else {
                        signalsList.innerHTML = '<tr><td colspan="8" style="text-align:center; color:#9ca3af;">今日暂无信号</td></tr>';
                    }
                }
            }
        } catch (error) {
            console.error('加载信号列表失败:', error);
        }
    },
    
    // 加载股票池
    loadStockPool: async function() {
        try {
            const response = await fetch('/api/stock-pool');
            const result = await response.json();
            
            if (result.success) {
                const pool = result.data.pool || [];
                const poolDate = result.data.date || 'N/A';
                const poolList = document.getElementById('pool-list');
                
                // 更新股票池标题（格式：X年X月X日股票池（XX只））
                const poolTitleEl = document.getElementById('pool-title');
                if (poolTitleEl) {
                    if (poolDate !== 'N/A') {
                        const dateObj = new Date(poolDate);
                        const year = dateObj.getFullYear();
                        const month = dateObj.getMonth() + 1;
                        const day = dateObj.getDate();
                        poolTitleEl.textContent = `${year}年${month}月${day}日股票池（${pool.length}只）`;
                    } else {
                        poolTitleEl.textContent = '股票池（用于择时）';
                    }
                }
                
                if (poolList) {
                    if (pool && pool.length > 0) {
                        poolList.innerHTML = pool.map(item => {
                            // 根据冷却状态设置样式
                            const statusColor = item.is_cooling ? '#f59e0b' : '#22c55e';
                            const rowStyle = item.is_cooling ? 'background-color: #fef3c7; opacity: 0.7;' : '';
                            return `
                                <tr style="${rowStyle}">
                                    <td><a href="javascript:void(0)" onclick="viewStockDetail('${item.stock_code}')">${item.stock_code}</a></td>
                                    <td>${item.stock_name}</td>
                                    <td>${item.score}</td>
                                    <td><span style="color:${statusColor}; font-weight: bold;">${item.status_text}</span></td>
                                    <td>${item.days_in_pool}</td>
                                    <td>¥${item.current_price.toFixed(2)}</td>
                                    <td>¥${item.support_level.toFixed(2)}</td>
                                </tr>
                            `;
                        }).join('');
                    } else {
                        poolList.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#9ca3af;">股票池为空</td></tr>';
                    }
                }
            }
        } catch (error) {
            console.error('加载股票池失败:', error);
        }
    },
    
    // 加载上次运行的任务
    loadLastTask: async function() {
        try {
            const response = await fetch('/api/task/last');
            const result = await response.json();
            
            if (result.success && result.data) {
                const lastTask = result.data;
                
                if (lastTask.strategies && lastTask.strategies.length > 0) {
                    this.tasks = [];
                    
                    // 获取历史任务的择时策略
                    const timingStrategy = lastTask.timing_strategy || 'support';
                    
                    for (const strategyName of lastTask.strategies) {
                        // 使用策略名称映射获取中文名称
                        const displayName = this.getStrategyDisplayName(strategyName);
                        // 将择时策略传递给 addTask
                        this.addTask(strategyName, displayName, timingStrategy);
                    }
                    
                    console.log('已加载上次任务配置:', lastTask);
                } else {
                    // 没有历史任务，添加默认策略
                    this.addTask('ImmortalGuidanceStrategy', '不朽指引策略');
                    console.log('没有历史任务，已添加默认策略');
                }
            } else {
                // 没有历史任务，添加默认策略
                this.addTask('ImmortalGuidanceStrategy', '不朽指引策略');
                console.log('没有历史任务，已添加默认策略');
            }
        } catch (error) {
            console.error('加载上次任务失败:', error);
            // 添加默认策略作为后备
            this.addTask('ImmortalGuidanceStrategy', '不朽指引策略');
        }
    },
    
    // 执行信号
    executeSignal: async function(signalId) {
        // 找到对应的按钮并禁用
        const btn = document.querySelector(`.execute-signal-btn[data-signal-id="${signalId}"]`);
        if (btn) {
            btn.disabled = true;
            btn.textContent = '执行中...';
        }
        
        try {
            const response = await fetch(`/api/signals/${signalId}/execute`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.appendLog('信号执行成功');
                this.loadSignals();
                this.loadPortfolio();
            } else {
                alert('信号执行失败: ' + (result.message || '未知错误'));
                // 失败时恢复按钮状态
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '执行';
                }
            }
        } catch (error) {
            console.error('执行信号失败:', error);
            alert('执行信号失败');
            // 异常时恢复按钮状态
            if (btn) {
                btn.disabled = false;
                btn.textContent = '执行';
            }
        }
    },
    
    // 忽略信号
    ignoreSignal: async function(signalId) {
        // 找到对应的按钮并禁用
        const btn = document.querySelector(`.ignore-signal-btn[data-signal-id="${signalId}"]`);
        if (btn) {
            btn.disabled = true;
            btn.textContent = '处理中...';
        }
        
        try {
            const response = await fetch(`/api/signals/${signalId}/ignore`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.appendLog('信号已忽略');
                this.loadSignals();
            } else {
                alert('忽略信号失败: ' + (result.message || '未知错误'));
                // 失败时恢复按钮状态
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '忽略';
                }
            }
        } catch (error) {
            console.error('忽略信号失败:', error);
            alert('忽略信号失败');
            // 异常时恢复按钮状态
            if (btn) {
                btn.disabled = false;
                btn.textContent = '忽略';
            }
        }
    },
    
    // 追加日志
    appendLog: function(message) {
        const logContainer = document.getElementById('execution-log');
        const timestamp = new Date().toLocaleTimeString();
        const logItem = document.createElement('div');
        logItem.innerHTML = `<span style="color:#9ca3af;">[${timestamp}]</span> ${message}`;
        logContainer.appendChild(logItem);
        logContainer.scrollTop = logContainer.scrollHeight;
    }
};

// 将卖出函数暴露到全局作用域，供HTML中的onclick调用
window.sellPosition = function(stockCode, stockName) {
    StrategyRunnerModule.sellPosition(stockCode, stockName);
};

// 导出模块
export default StrategyRunnerModule;
